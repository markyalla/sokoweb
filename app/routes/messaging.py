from flask import Blueprint, render_template, g, redirect, url_for, request, flash
from sqlalchemy import or_

from app import db
from app.routes.models import User, UserRole, DriverProfile
from app.messaging import dispatch, normalize_phone, valid_email, sms_configured, email_configured, SMS_MAX_LENGTH

messaging_bp = Blueprint('messaging', __name__)

AUDIENCES = {
    'customers': 'All customers (not drivers)',
    'drivers': 'All active drivers',
    'everyone': 'Everyone (customers and drivers)',
    'single': 'One user (by phone or email)',
    'custom': 'Custom list of phone numbers / emails',
}


def _require_superadmin():
    if not g.user:
        return redirect(url_for('auth.login'))
    if 'superadmin' not in [r.role for r in g.user.roles]:
        flash('Only a superadmin can send messages.', 'danger')
        return redirect(url_for('dashboard.index'))
    return None


def _active_users():
    return User.query.filter(
        or_(User.is_active.is_(True), User.is_active.is_(None)),
        or_(User.is_deleted.is_(False), User.is_deleted.is_(None)),
    )


def _driver_ids():
    return {str(d.user_id) for d in DriverProfile.query.filter_by(status='active').all()}


def _staff_ids():
    staff = ('superadmin', 'sokoshopper_admin', 'sokodelivery_admin', 'sokoloan_admin', 'sokosusu_admin')
    return {str(r.user_id) for r in UserRole.query.filter(UserRole.role.in_(staff)).all()}


def _audience_users(audience):
    users = _active_users().all()
    drivers, staff = _driver_ids(), _staff_ids()
    if audience == 'drivers':
        return [u for u in users if str(u.id) in drivers]
    if audience == 'customers':
        return [u for u in users if str(u.id) not in drivers and str(u.id) not in staff]
    if audience == 'everyone':
        return [u for u in users if str(u.id) not in staff]
    return []


@messaging_bp.route('/', methods=['GET', 'POST'])
def index():
    redir = _require_superadmin()
    if redir:
        return redir

    if request.method == 'POST':
        audience = request.form.get('audience', '')
        channel = request.form.get('channel', 'sms')
        sms_text = (request.form.get('sms_text') or '').strip()
        subject = (request.form.get('subject') or '').strip()
        email_body = (request.form.get('email_body') or '').strip()
        want_sms = channel in ('sms', 'both')
        want_email = channel in ('email', 'both')

        if audience not in AUDIENCES:
            flash('Choose who to send to.', 'danger')
            return redirect(url_for('messaging.index'))
        if want_sms and not sms_text:
            flash('Write the SMS message.', 'danger')
            return redirect(url_for('messaging.index'))
        if want_email and (not subject or not email_body):
            flash('Write the email subject and message.', 'danger')
            return redirect(url_for('messaging.index'))

        phones, emails = [], []
        if audience == 'single':
            target = (request.form.get('single_target') or '').strip()
            user = _active_users().filter(or_(User.email == target, User.phone_number == target)).first()
            if not user and normalize_phone(target):
                norm = normalize_phone(target)
                user = next((u for u in _active_users().all() if normalize_phone(u.phone_number) == norm), None)
            if not user:
                flash('No active user found with that phone number or email.', 'danger')
                return redirect(url_for('messaging.index'))
            phones, emails = [user.phone_number], [user.email]
        elif audience == 'custom':
            for item in (request.form.get('custom_list') or '').replace(',', '\n').splitlines():
                item = item.strip()
                if valid_email(item):
                    emails.append(item)
                elif normalize_phone(item):
                    phones.append(item)
        else:
            users = _audience_users(audience)
            phones = [u.phone_number for u in users if u.phone_number]
            emails = [u.email for u in users if u.email]

        n_sms = len({normalize_phone(p) for p in phones if normalize_phone(p)}) if want_sms else 0
        n_email = len({e for e in emails if valid_email(e)}) if want_email else 0
        if n_sms == 0 and n_email == 0:
            flash('No valid recipients for the selected channel.', 'warning')
            return redirect(url_for('messaging.index'))

        dispatch(
            action=f'bulk_message:{audience}:{channel}',
            phones=phones if want_sms else [],
            emails=emails if want_email else [],
            sms_text=sms_text if want_sms else None,
            subject=subject if want_email else None,
            email_body=email_body if want_email else None,
            user=g.user,
        )
        parts = []
        if want_sms:
            parts.append(f'{n_sms} SMS')
        if want_email:
            parts.append(f'{n_email} email(s)')
        flash(f'Sending {" and ".join(parts)} in the background. Results appear in the Audit Log.', 'success')
        return redirect(url_for('messaging.index'))

    counts = {k: len(_audience_users(k)) for k in ('customers', 'drivers', 'everyone')}
    return render_template('superadmin/messaging.html', audiences=AUDIENCES, counts=counts,
                           sms_ready=sms_configured(), email_ready=email_configured(),
                           sms_max=SMS_MAX_LENGTH)
