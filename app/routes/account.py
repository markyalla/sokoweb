from flask import Blueprint, render_template, g, redirect, url_for, flash, request, current_app
from app.routes.models import User, KYCSubmission, DriverProfile, UserRole, KYCDocument
from PIL import Image
from datetime import datetime
from app import db
from sqlalchemy.orm import joinedload
import os

account_bp = Blueprint('account', __name__)

# Roles a superadmin is allowed to hand out from the Users UI.
# 'user'/'driver'/'artisan' are assigned elsewhere (registration / driver approval / artisan flow).
ASSIGNABLE_ROLES = [
    'superadmin', 'sokoshopper_admin', 'sokodelivery_admin',
    'sokoloan_admin', 'sokosusu_admin', 'sokobank_admin',
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
    media_base_url = f"{os.getenv('API_BASE_URL', 'http://localhost:8082')}/api/v1/media/serve/"
    return render_template('auth/kyc.html', submissions=submissions, media_base_url=media_base_url)

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