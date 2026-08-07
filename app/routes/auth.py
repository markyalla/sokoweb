from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, limiter
from app.routes.models import User, Store, UserRole
import jwt
import bcrypt as _bcrypt
import os
import requests
from datetime import datetime, timedelta, timezone

auth_bp = Blueprint('auth', __name__)

# Shared login-lockout policy (also enforced by the Go API against this same
# users row): 5 consecutive bad passwords locks the account for 30 minutes,
# or until a superadmin clears it early from the Users page.
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 30


def _lockout_message(locked_until) -> str:
    return (
        f"Account locked due to too many failed login attempts. "
        f"Try again after {locked_until.strftime('%I:%M %p')}, use 'Forgot password?' below to reset it "
        f"and regain access immediately, or ask a superadmin to unlock it."
    )


def _verify_password(stored_hash: str, password: str) -> bool:
    """Verify password against either bcrypt (Go backend) or Werkzeug hashes."""
    if not stored_hash:
        return False
    if stored_hash.startswith(('$2b$', '$2a$', '$2y$')):
        return _bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
    return check_password_hash(stored_hash, password)


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=['POST'])
def login():
    if request.method == 'POST':
        identifier = request.form.get('identifier')
        password   = request.form.get('password')

        user = User.query.filter(
            (User.email == identifier) | (User.phone_number == identifier)
        ).first()

        if user and user.locked_until and user.locked_until > datetime.utcnow():
            flash(_lockout_message(user.locked_until), 'danger')
            return render_template('auth/login.html', registration_open=(User.query.count() == 0))

        if user and _verify_password(user.password_hash or '', password):
            if user.failed_login_attempts or user.locked_until:
                user.failed_login_attempts = 0
                user.locked_until = None
                db.session.commit()

            session.clear()
            session['user_id'] = str(user.id)

            # Build and store the JWT for Go backend API calls
            try:
                secret = current_app.config.get('JWT_SECRET')
                if not secret:
                    raise ValueError("JWT_SECRET is not configured")

                roles = [r.role for r in user.roles]
                token_payload = {
                    "sub":   str(user.id),
                    "roles": roles,
                    "exp":   datetime.now(timezone.utc) + timedelta(hours=72),
                }
                backend_token = jwt.encode(token_payload, secret, algorithm="HS256")

                # PyJWT <2.0 returns bytes
                if isinstance(backend_token, bytes):
                    backend_token = backend_token.decode('utf-8')

                session['backend_token'] = backend_token

            except Exception as e:
                current_app.logger.error(f"[LOGIN] Failed to encode backend JWT: {e}")

            flash(f'Welcome back, {user.full_name}!', 'success')

            # Routing: admins → admin dashboard; store owners → shop portal
            admin_roles = (
                'superadmin', 'sokoshopper_admin', 'sokodelivery_admin',
                'sokoloan_admin', 'sokosusu_admin', 'sokobank_admin',
            )
            roles = [r.role for r in user.roles]
            is_admin = any(r in roles for r in admin_roles)
            if is_admin:
                return redirect(url_for('dashboard.index'))

            owned_stores = Store.query.filter_by(owner_user_id=str(user.id)).all()
            if len(owned_stores) == 1:
                session['active_store_id'] = str(owned_stores[0].id)
                return redirect(url_for('store_owner.dashboard'))
            elif len(owned_stores) > 1:
                return redirect(url_for('store_owner.select_store'))

            # Regular mobile user with no store — block web portal access
            session.clear()
            flash('This portal is for store owners and admins only. Please use the mobile app.', 'warning')
            return redirect(url_for('auth.login'))

        if user:
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:
                user.locked_until = datetime.utcnow() + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
                db.session.commit()
                flash(_lockout_message(user.locked_until), 'danger')
            else:
                db.session.commit()
                remaining = MAX_LOGIN_ATTEMPTS - user.failed_login_attempts
                flash(
                    f'Invalid email or password. {user.failed_login_attempts} of {MAX_LOGIN_ATTEMPTS} '
                    f'attempts used, {remaining} remaining before your account is locked.',
                    'danger'
                )
        else:
            # Unknown identifier — no account row to track attempts against;
            # stay generic to avoid leaking which identifiers are registered.
            flash('Invalid email or password', 'danger')

    return render_template('auth/login.html', registration_open=(User.query.count() == 0))


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    # Only the very first account may self-register (becomes superadmin).
    # Every admin after that is created from the Users page by a superadmin.
    if User.query.count() > 0:
        flash('Registration is closed. Ask your superadmin to create an account for you.', 'warning')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        full_name        = request.form.get('full_name')
        email            = request.form.get('email')
        phone_number     = request.form.get('phone_number')
        password         = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if not all([full_name, email, phone_number, password, confirm_password]):
            flash('All fields are required.', 'danger')
        elif password != confirm_password:
            flash('Passwords do not match.', 'danger')
        elif User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
        elif User.query.filter_by(phone_number=phone_number).first():
            flash('Phone number already registered.', 'danger')
        else:
            new_user = User(
                full_name=full_name,
                email=email,
                phone_number=phone_number,
                password_hash=generate_password_hash(password),
            )
            db.session.add(new_user)
            db.session.flush()

            db.session.add(UserRole(user_id=new_user.id, role='superadmin'))
            db.session.commit()

            flash('Registration successful! You are the first account and have been made superadmin. Please log in.', 'success')
            return redirect(url_for('auth.login'))

    return render_template('auth/register.html')


def _backend_post(path: str, payload: dict):
    """POST to the Go API's public auth endpoints. Returns (ok, error_message)."""
    api_base = current_app.config.get('API_BASE_URL', '').rstrip('/')
    try:
        resp = requests.post(f'{api_base}{path}', json=payload, timeout=10)
    except requests.RequestException as e:
        current_app.logger.error(f"[{path}] Backend request failed: {e}")
        return False, 'Could not reach the server. Please try again in a moment.'

    if resp.ok:
        return True, None

    try:
        error = resp.json().get('error', 'Something went wrong. Please try again.')
    except ValueError:
        error = 'Something went wrong. Please try again.'
    return False, error


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=['POST'])
def forgot_password():
    # This — and verify_otp / reset_password below — are thin proxies to the
    # Go API's existing OTP endpoints (internal/auth/handler.go): SokoWeb has
    # no email-sending infra of its own, and both apps share the same users
    # row, so there's no reason to duplicate OTP generation/hashing/email here.
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        if not email:
            flash('Please enter your email address.', 'danger')
            return render_template('auth/forgot_password.html')

        _backend_post('/api/v1/auth/forgot-password', {'email': email})
        # Always the same message regardless of whether the email is
        # registered, matching the Go API's own anti-enumeration behaviour.
        flash('If that email is registered, an OTP has been sent to it.', 'info')
        return redirect(url_for('auth.verify_otp', email=email))

    return render_template('auth/forgot_password.html')


@auth_bp.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    email = request.values.get('email', '')
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        otp = request.form.get('otp', '').strip()

        ok, error = _backend_post('/api/v1/auth/verify-otp', {'email': email, 'otp': otp})
        if ok:
            return redirect(url_for('auth.reset_password', email=email))
        flash(error, 'danger')

    return render_template('auth/verify_otp.html', email=email)


@auth_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    email = request.values.get('email', '')
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if new_password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('auth/reset_password.html', email=email)

        ok, error = _backend_post('/api/v1/auth/reset-password', {
            'email': email,
            'new_password': new_password,
            'confirm_password': confirm_password,
        })
        if ok:
            flash('Password reset successful. Please log in with your new password.', 'success')
            return redirect(url_for('auth.login'))
        flash(error, 'danger')

    return render_template('auth/reset_password.html', email=email)


@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))