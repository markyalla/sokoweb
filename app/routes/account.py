from flask import Blueprint, render_template, g, redirect, url_for, flash, request, current_app, abort, Response
from app.routes.models import User, KYCSubmission, DriverProfile, UserRole, KYCDocument
from PIL import Image
from datetime import datetime, timezone
from app import db
from sqlalchemy.orm import joinedload
import os
import re
from datetime import timedelta
import jwt
import requests

account_bp = Blueprint('account', __name__)

# Roles a superadmin is allowed to hand out from the Users UI.
# 'user'/'driver'/'artisan' are assigned elsewhere (registration / driver approval / artisan flow).
ASSIGNABLE_ROLES = [
    'superadmin', 'sokoshopper_admin', 'sokodelivery_admin',
    'sokoloan_admin', 'sokosusu_admin',
]


def _require_superadmin():
    if not g.user:
        return redirect(url_for('auth.login'))
    if 'superadmin' not in [r.role for r in g.user.roles]:
        flash('Only a superadmin can access that.', 'danger')
        return redirect(url_for('dashboard.index'))
    return None


@account_bp.route('/users')
def user_list():
    redir = _require_superadmin()
    if redir:
        return redir

    from app.routes.models import Store

    users = User.query.options(
        joinedload(User.kyc).joinedload(KYCSubmission.documents),
        joinedload(User.driver_profile),
        joinedload(User.roles)
    ).order_by(User.created_at.desc()).all()

    store_owner_ids = {s.owner_user_id for s in Store.query.with_entities(Store.owner_user_id).all()}
    is_superadmin = 'superadmin' in [r.role for r in g.user.roles]

    return render_template(
        'superadmin/users.html',
        users=users,
        store_owner_ids=store_owner_ids,
        assignable_roles=ASSIGNABLE_ROLES,
        is_superadmin=is_superadmin,
        # Aware UTC: locked_until is timestamptz (created by the Go API), so a
        # naive now would raise TypeError on comparison in the template.
        now=datetime.now(timezone.utc),
    )

@account_bp.route('/users/<uuid:id>/update', methods=['POST'])
def update_user(id):
    redir = _require_superadmin()
    if redir:
        return redir
    user = User.query.get_or_404(id)
    user.full_name = request.form.get('full_name')
    user.email = request.form.get('email')
    user.phone_number = request.form.get('phone_number')
    user.gender = request.form.get('gender')
    user.is_active = request.form.get('is_active') == 'true'
    
    dob_val = request.form.get('date_of_birth')
    if dob_val:
        try:
            user.date_of_birth = datetime.strptime(dob_val, '%Y-%m-%d')
        except ValueError:
            pass
    
    db.session.commit()
    flash(f'User {user.full_name} updated successfully.', 'success')
    return redirect(url_for('account.user_list'))

@account_bp.route('/users/<uuid:id>/unlock', methods=['POST'])
def unlock_user(id):
    redir = _require_superadmin()
    if redir:
        return redir
    user = User.query.get_or_404(id)
    user.failed_login_attempts = 0
    user.locked_until = None
    db.session.commit()
    flash(f'{user.full_name} has been unlocked.', 'success')
    return redirect(url_for('account.user_list'))

@account_bp.route('/users/<uuid:id>/delete', methods=['POST'])
def delete_user(id):
    redir = _require_superadmin()
    if redir:
        return redir

    user = User.query.get_or_404(id)
    name = user.full_name

    try:
        kyc_ids = [k.id for k in KYCSubmission.query.filter_by(user_id=id).all()]
        if kyc_ids:
            KYCDocument.query.filter(KYCDocument.kyc_id.in_(kyc_ids)).delete(synchronize_session=False)
        KYCSubmission.query.filter_by(user_id=id).delete(synchronize_session=False)
        DriverProfile.query.filter_by(user_id=id).delete(synchronize_session=False)
        UserRole.query.filter_by(user_id=id).delete(synchronize_session=False)
        db.session.delete(user)
        db.session.commit()
        flash(f'User {name} and all associated data removed.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Failed to delete user: {str(e)}', 'danger')

    return redirect(url_for('account.user_list'))

@account_bp.route('/users/<uuid:id>/roles/add', methods=['POST'])
def add_role(id):
    redir = _require_superadmin()
    if redir:
        return redir

    role_name = request.form.get('role')
    if role_name not in ASSIGNABLE_ROLES:
        flash('Invalid role.', 'danger')
        return redirect(url_for('account.user_list'))

    user = User.query.get_or_404(id)
    exists = UserRole.query.filter_by(user_id=id, role=role_name).first()
    if not exists:
        db.session.add(UserRole(user_id=id, role=role_name))
        db.session.commit()
        flash(f'{role_name} granted to {user.full_name}.', 'success')
    else:
        flash(f'{user.full_name} already has that role.', 'warning')

    return redirect(url_for('account.user_list'))

@account_bp.route('/users/<uuid:id>/roles/remove', methods=['POST'])
def remove_role(id):
    redir = _require_superadmin()
    if redir:
        return redir

    role_name = request.form.get('role')
    user = User.query.get_or_404(id)

    if role_name == 'superadmin' and str(id) == str(g.user.id):
        flash('You cannot remove your own superadmin role.', 'danger')
        return redirect(url_for('account.user_list'))

    UserRole.query.filter_by(user_id=id, role=role_name).delete(synchronize_session=False)
    db.session.commit()
    flash(f'{role_name} revoked from {user.full_name}.', 'danger')
    return redirect(url_for('account.user_list'))

@account_bp.route('/profile')
def profile():
    if not g.user:
        return redirect(url_for('auth.login'))
    return render_template('account/profile.html', user=g.user)

@account_bp.route('/kyc')
def kyc_list():
    redir = _require_superadmin()
    if redir:
        return redir
    submissions = KYCSubmission.query.order_by(KYCSubmission.status.desc()).all()
    return render_template('auth/kyc.html', submissions=submissions)

@account_bp.route('/kyc/<uuid:id>/approve', methods=['POST'])
def approve_kyc(id):
    redir = _require_superadmin()
    if redir:
        return redir
    sub = KYCSubmission.query.filter_by(user_id=id).first_or_404()
    sub.status = 'approved'
    db.session.commit()
    flash(f'KYC for {sub.id_number} approved successfully.', 'success')
    return redirect(url_for('account.user_list'))

@account_bp.route('/kyc/<uuid:id>/reject', methods=['POST'])
def reject_kyc(id):
    redir = _require_superadmin()
    if redir:
        return redir
    sub = KYCSubmission.query.filter_by(user_id=id).first_or_404()
    sub.status = 'rejected'
    db.session.commit()
    flash(f'KYC for {sub.id_number} rejected.', 'warning')
    return redirect(url_for('account.user_list'))

@account_bp.route('/driver/<uuid:id>/approve', methods=['POST'])
def approve_driver(id):
    redir = _require_superadmin()
    if redir:
        return redir
    profile = DriverProfile.query.filter_by(user_id=id).first_or_404()
    profile.status = 'active'
    
    role_exists = UserRole.query.filter_by(user_id=profile.user_id, role='driver').first()
    if not role_exists:
        db.session.add(UserRole(user_id=profile.user_id, role='driver'))
        
    db.session.commit()
    flash('Driver application approved.', 'success')
    return redirect(url_for('account.user_list'))

@account_bp.route('/driver/<uuid:id>/reject', methods=['POST'])
def reject_driver(id):
    redir = _require_superadmin()
    if redir:
        return redir
    profile = DriverProfile.query.filter_by(user_id=id).first_or_404()
    profile.status = 'suspended'
    db.session.commit()
    flash('Driver application rejected.', 'warning')
    return redirect(url_for('account.user_list'))

@account_bp.route('/driver/<uuid:id>/suspend', methods=['POST'])
def suspend_driver(id):
    redir = _require_superadmin()
    if redir:
        return redir
    profile = DriverProfile.query.filter_by(user_id=id).first_or_404()
    profile.status = 'suspended'
    db.session.commit()
    flash(f'Driver account for {profile.user.full_name} has been suspended.', 'danger')
    return redirect(url_for('account.user_list'))

_KYC_FILE_RE = re.compile(r'[A-Za-z0-9._-]+')


def _kyc_filename(path):
    """Return the bare filename of a stored "kyc/<file>" path, or None."""
    if not path:
        return None
    p = str(path)
    if '/media/serve/' in p:
        p = p.split('/media/serve/', 1)[1]
    p = p.lstrip('/')
    if not p.startswith('kyc/'):
        return None
    name = p[len('kyc/'):]
    return name if _KYC_FILE_RE.fullmatch(name) else None


@account_bp.app_template_filter('kyc_media')
def kyc_media_filter(path):
    name = _kyc_filename(path)
    return url_for('account.kyc_media', subpath=name) if name else ''


@account_bp.route('/kyc-media/<path:subpath>')
def kyc_media(subpath):
    """Staff-only proxy for identity documents. The Go API no longer serves the
    private "kyc" bucket publicly, so SokoWeb fetches the file server-side with
    a short-lived admin token and streams it back — the document URL never
    works outside an authenticated admin session."""
    from app.audit import ADMIN_ROLES
    if not g.user:
        return redirect(url_for('auth.login'))
    roles = [r.role for r in g.user.roles]
    if not any(r in ADMIN_ROLES for r in roles):
        abort(403)
    if not _KYC_FILE_RE.fullmatch(subpath):
        abort(404)

    token = jwt.encode(
        {'sub': str(g.user.id), 'roles': roles,
         'exp': datetime.now(timezone.utc) + timedelta(seconds=60)},
        current_app.config['JWT_SECRET'], algorithm='HS256',
    )
    if isinstance(token, bytes):
        token = token.decode('utf-8')
    api_base = current_app.config.get('API_BASE_URL', '').rstrip('/')
    try:
        resp = requests.get(f'{api_base}/api/v1/media/serve/kyc/{subpath}',
                            headers={'Authorization': f'Bearer {token}'}, timeout=15)
    except requests.RequestException as e:
        current_app.logger.error(f'[kyc_media] backend fetch failed: {e}')
        abort(502)
    if resp.status_code != 200:
        abort(404)
    return Response(resp.content, mimetype=resp.headers.get('Content-Type', 'application/octet-stream'),
                    headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})
