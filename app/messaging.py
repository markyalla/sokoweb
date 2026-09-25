"""Outbound SMS (Arkesel) and email (SMTP) for SokoWeb.

SMS uses Arkesel's v2 API:  POST https://sms.arkesel.com/api/v2/sms/send
with the `api-key` header and {"sender", "message", "recipients": [...]}.
Configure ARKESEL_API_KEY and ARKESEL_SENDER_ID in .env.

Email is sent over SMTP using the same SMTP_* variables the Go API already
uses for OTP emails (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM).

Sends run on a background thread so a large broadcast never blocks (or times
out) the admin's request. Every send is written to the Audit Log.
"""
import re
import smtplib
import threading
from email.message import EmailMessage

import requests
from flask import current_app

ARKESEL_SMS_URL = 'https://sms.arkesel.com/api/v2/sms/send'
SMS_BATCH_SIZE = 100          # recipients per Arkesel request
SMS_MAX_LENGTH = 612          # 4 SMS parts; keeps a typo from sending a huge bill


def normalize_phone(raw):
    """Return a Ghana-style international number without '+' (e.g. 233241234567),
    or None if it doesn't look like a phone number."""
    if not raw:
        return None
    digits = re.sub(r'\D', '', str(raw))
    if digits.startswith('00'):
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith('0'):   # local Ghana format 024...
        digits = '233' + digits[1:]
    if len(digits) < 10 or len(digits) > 15:
        return None
    return digits


def valid_email(addr):
    return bool(addr) and re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', addr.strip()) is not None \
        and not addr.strip().endswith('.invalid')


def sms_configured(app=None):
    cfg = (app or current_app).config
    return bool(cfg.get('ARKESEL_API_KEY') and cfg.get('ARKESEL_SENDER_ID'))


def email_configured(app=None):
    cfg = (app or current_app).config
    return bool(cfg.get('SMTP_HOST') and cfg.get('SMTP_FROM'))


# ── low-level senders (call inside an app context) ───────────────────────────

def send_sms(numbers, message):
    """Send one SMS to many numbers. Returns (sent_count, failed_count, errors)."""
    app = current_app
    recipients = sorted({n for n in (normalize_phone(x) for x in numbers) if n})
    if not recipients:
        return 0, 0, ['No valid phone numbers']
    if not sms_configured(app):
        return 0, len(recipients), ['Arkesel is not configured (ARKESEL_API_KEY / ARKESEL_SENDER_ID)']

    sent, failed, errors = 0, 0, []
    for i in range(0, len(recipients), SMS_BATCH_SIZE):
        batch = recipients[i:i + SMS_BATCH_SIZE]
        try:
            resp = requests.post(
                ARKESEL_SMS_URL,
                headers={'api-key': app.config['ARKESEL_API_KEY'], 'Content-Type': 'application/json'},
                json={'sender': app.config['ARKESEL_SENDER_ID'], 'message': message[:SMS_MAX_LENGTH],
                      'recipients': batch},
                timeout=20,
            )
            ok = resp.ok
            try:
                body = resp.json()
                ok = ok and str(body.get('status', 'success')).lower() == 'success'
            except ValueError:
                body = resp.text[:200]
            if ok:
                sent += len(batch)
            else:
                failed += len(batch)
                errors.append(f'Arkesel HTTP {resp.status_code}: {body}')
        except requests.RequestException as e:
            failed += len(batch)
            errors.append(f'Arkesel request failed: {e}')
    return sent, failed, errors


def send_email(addresses, subject, body):
    """Send the same email to many addresses (one message each, so recipients
    never see each other). Returns (sent_count, failed_count, errors)."""
    app = current_app
    recipients = sorted({a.strip() for a in addresses if valid_email(a)})
    if not recipients:
        return 0, 0, ['No valid email addresses']
    if not email_configured(app):
        return 0, len(recipients), ['SMTP is not configured (SMTP_HOST / SMTP_FROM)']

    cfg = app.config
    port = int(cfg.get('SMTP_PORT') or 587)
    sent, failed, errors = 0, 0, []
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(cfg['SMTP_HOST'], port, timeout=30)
        else:
            server = smtplib.SMTP(cfg['SMTP_HOST'], port, timeout=30)
            server.starttls()
        if cfg.get('SMTP_USER'):
            server.login(cfg['SMTP_USER'], cfg.get('SMTP_PASS') or '')
    except (smtplib.SMTPException, OSError) as e:
        return 0, len(recipients), [f'SMTP connection failed: {e}']

    with server:
        for addr in recipients:
            msg = EmailMessage()
            msg['From'] = cfg['SMTP_FROM']
            msg['To'] = addr
            msg['Subject'] = subject
            msg.set_content(body)
            try:
                server.send_message(msg)
                sent += 1
            except smtplib.SMTPException as e:
                failed += 1
                if len(errors) < 5:
                    errors.append(f'{addr}: {e}')
    return sent, failed, errors


# ── background dispatch ──────────────────────────────────────────────────────

def dispatch(action, phones=None, emails=None, sms_text=None, subject=None, email_body=None, user=None):
    """Send SMS and/or email on a background thread and write the outcome to
    the Audit Log. Returns immediately."""
    app = current_app._get_current_object()
    user_id = user.id if user else None
    phones, emails = list(phones or []), list(emails or [])

    def work():
        with app.app_context():
            from app.audit import log_audit, CATEGORY_ADMIN_ACTION, CATEGORY_JOB_FAILURE, \
                SEVERITY_INFO, SEVERITY_WARNING
            from app.routes.models import User
            actor = User.query.get(user_id) if user_id else None
            summary, problems = [], []
            if sms_text and phones:
                s, f, errs = send_sms(phones, sms_text)
                summary.append(f'SMS sent {s}, failed {f}')
                problems += errs
            if subject and email_body and emails:
                s, f, errs = send_email(emails, subject, email_body)
                summary.append(f'Email sent {s}, failed {f}')
                problems += errs
            log_audit(
                category=CATEGORY_JOB_FAILURE if problems else CATEGORY_ADMIN_ACTION,
                severity=SEVERITY_WARNING if problems else SEVERITY_INFO,
                action=action, user=actor, actor_label=None if actor else 'system',
                message='; '.join(summary + problems[:5]) or 'Nothing to send',
            )

    threading.Thread(target=work, daemon=True).start()


def notify_offline_driver(driver_id, reference):
    """SMS a driver who was just assigned a delivery but isn't online in the app,
    so they know to open SokoApp. Safe to call after any assignment commit —
    never raises and does nothing for online drivers or when SMS isn't set up."""
    try:
        from app.routes.models import DriverProfile, User
        if not sms_configured():
            return
        dp = DriverProfile.query.filter_by(user_id=str(driver_id)).first()
        if dp is None or dp.is_online:
            return
        driver = User.query.get(str(driver_id))
        if not driver or not driver.phone_number:
            return
        name = (driver.full_name or '').split(' ')[0] or 'there'
        dispatch(
            action='sms_offline_driver_assignment',
            phones=[driver.phone_number],
            sms_text=(f'Hi {name}, you have a new SokoApp delivery ({reference}) waiting. '
                      f'Open the SokoApp driver app and go online to accept it.'),
        )
    except Exception as e:  # never let a notification break an assignment
        current_app.logger.error(f'[notify_offline_driver] {e}')
