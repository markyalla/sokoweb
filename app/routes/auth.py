from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from app import db
from app.routes.models import User, Store, UserRole
import jwt
import bcrypt as _bcrypt
import os
from datetime import datetime, timedelta, timezone

auth_bp = Blueprint('auth', __name__)


def _verify_password(stored_hash: str, password: str) -> bool:
    """Verify password against either bcrypt (Go backend) or Werkzeug hashes."""
    if not stored_hash:
        return False
    if stored_hash.startswith(('$2b$', '$2a$', '$2y$')):
        return _bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
    return check_password_hash(stored_hash, password)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = request.form.get('identifier')
        password   = request.form.get('password')

        user = User.query.filter(
            (User.email == identifier) | (User.phone_number == identifier)
        ).first()

        if user and _verify_password(user.password_hash or '', password):
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

            owned_store = Store.query.filter_by(owner_user_id=str(user.id)).first()
            if owned_store:
                return redirect(url_for('store_owner.dashboard'))

            # Regular mobile user with no store — block web portal access
            session.clear()
            flash('This portal is for store owners and admins only. Please use the mobile app.', 'warning')
            return redirect(url_for('auth.login'))

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


@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))