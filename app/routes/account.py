from flask import Blueprint, render_template, g, redirect, url_for, flash, request, current_app
from app.routes.models import User, KYCSubmission, DriverProfile, UserRole, KYCDocument
from PIL import Image
from datetime import datetime
from app import db
from sqlalchemy.orm import joinedload
import os

account_bp = Blueprint('account', __name__)

@account_bp.route('/users')
def user_list():
    if not g.user:
        return redirect(url_for('auth.login'))

    users = User.query.options(
        joinedload(User.kyc).joinedload(KYCSubmission.documents),
        joinedload(User.driver_profile),
        joinedload(User.roles)
    ).order_by(User.created_at.desc()).all()
    
    return render_template('superadmin/users.html', users=users)

@account_bp.route('/users/<uuid:id>/update', methods=['POST'])
def update_user(id):
    if not g.user:
        return redirect(url_for('auth.login'))
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
    if not g.user:
        return redirect(url_for('auth.login'))
    
    user = User.query.get_or_404(id)
    name = user.full_name
    
    db.session.delete(user)
    db.session.commit()
    flash(f'User {name} and all associated data removed.', 'danger')
    return redirect(url_for('account.user_list'))

@account_bp.route('/profile')
def profile():
    if not g.user:
        return redirect(url_for('auth.login'))
    return render_template('account/profile.html', user=g.user)

@account_bp.route('/kyc')
def kyc_list():
    if not g.user:
        return redirect(url_for('auth.login'))
    submissions = KYCSubmission.query.order_by(KYCSubmission.status.desc()).all()
    media_base_url = f"{os.getenv('API_BASE_URL', 'http://localhost:8082')}/api/v1/media/serve/"
    return render_template('auth/kyc.html', submissions=submissions, media_base_url=media_base_url)

@account_bp.route('/kyc/<uuid:id>/approve', methods=['POST'])
def approve_kyc(id):
    if not g.user:
        return redirect(url_for('auth.login'))
    sub = KYCSubmission.query.filter_by(user_id=id).first_or_404()
    sub.status = 'approved'
    db.session.commit()
    flash(f'KYC for {sub.id_number} approved successfully.', 'success')
    return redirect(url_for('account.user_list'))

@account_bp.route('/kyc/<uuid:id>/reject', methods=['POST'])
def reject_kyc(id):
    if not g.user:
        return redirect(url_for('auth.login'))
    sub = KYCSubmission.query.filter_by(user_id=id).first_or_404()
    sub.status = 'rejected'
    db.session.commit()
    flash(f'KYC for {sub.id_number} rejected.', 'warning')
    return redirect(url_for('account.user_list'))

@account_bp.route('/driver/<uuid:id>/approve', methods=['POST'])
def approve_driver(id):
    if not g.user:
        return redirect(url_for('auth.login'))
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
    if not g.user:
        return redirect(url_for('auth.login'))
    profile = DriverProfile.query.filter_by(user_id=id).first_or_404()
    profile.status = 'suspended'
    db.session.commit()
    flash('Driver application rejected.', 'warning')
    return redirect(url_for('account.user_list'))

@account_bp.route('/driver/<uuid:id>/suspend', methods=['POST'])
def suspend_driver(id):
    if not g.user:
        return redirect(url_for('auth.login'))
    profile = DriverProfile.query.filter_by(user_id=id).first_or_404()
    profile.status = 'suspended'
    db.session.commit()
    flash(f'Driver account for {profile.user.full_name} has been suspended.', 'danger')
    return redirect(url_for('account.user_list'))