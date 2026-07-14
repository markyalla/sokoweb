from flask import Blueprint, render_template, g, redirect, url_for, flash, request
from app.routes.models import (
    ArtisanApplication, ArtisanProfile, Portfolio, SokoIndexBooking,
    SokoIndexRating, Recommendation, Complaint, UserRole, User,
    SokoIndexFeatureFlag,
)
from datetime import datetime
from app import db

sokoindex_bp = Blueprint('sokoindex', __name__)


def get_feature_flags():
    """Singleton row (id=1). Both flags default False so SokoIndex payments
    stay opt-in until an admin explicitly enables them from the dashboard."""
    flag = SokoIndexFeatureFlag.query.get(1)
    if not flag:
        flag = SokoIndexFeatureFlag(id=1, contact_unlock_enabled=False, joining_fee_enabled=False)
        db.session.add(flag)
        db.session.commit()
    return flag


# ─────────────────────────────────────────────
# Payment settings — free-to-use by default, admin flips these on later
# ─────────────────────────────────────────────

@sokoindex_bp.route('/settings/toggle-contact-unlock', methods=['POST'])
def toggle_contact_unlock():
    if not g.user:
        return redirect(url_for('auth.login'))
    flag = get_feature_flags()
    flag.contact_unlock_enabled = not flag.contact_unlock_enabled
    db.session.commit()
    flash(f"Contact-unlock payments {'enabled' if flag.contact_unlock_enabled else 'disabled — now free'}.", 'success')
    return redirect(url_for('sokoindex.applications_list'))


@sokoindex_bp.route('/settings/toggle-joining-fee', methods=['POST'])
def toggle_joining_fee():
    if not g.user:
        return redirect(url_for('auth.login'))
    flag = get_feature_flags()
    flag.joining_fee_enabled = not flag.joining_fee_enabled
    db.session.commit()
    flash(f"Artisan joining fee {'enabled' if flag.joining_fee_enabled else 'disabled — now free'}.", 'success')
    return redirect(url_for('sokoindex.applications_list'))


# ─────────────────────────────────────────────
# Artisan applications — mirrors account.py's driver-application review
# ─────────────────────────────────────────────

@sokoindex_bp.route('/applications')
def applications_list():
    if not g.user:
        return redirect(url_for('auth.login'))
    applications = ArtisanApplication.query.order_by(ArtisanApplication.status.desc(), ArtisanApplication.submitted_at.desc()).all()
    users_by_id = {u.id: u for u in User.query.filter(User.id.in_([a.user_id for a in applications])).all()} if applications else {}
    return render_template('sokoindex/applications.html', applications=applications, users_by_id=users_by_id, flag=get_feature_flags())


@sokoindex_bp.route('/applications/<uuid:id>/approve', methods=['POST'])
def approve_application(id):
    if not g.user:
        return redirect(url_for('auth.login'))
    application = ArtisanApplication.query.get_or_404(id)
    application.status = 'approved'
    application.reviewed_by = g.user.id
    application.reviewed_at = datetime.utcnow()

    applicant = User.query.get(application.user_id)
    existing_profile = ArtisanProfile.query.filter_by(user_id=application.user_id).first()
    if not existing_profile:
        db.session.add(ArtisanProfile(
            user_id=application.user_id,
            display_name=applicant.full_name if applicant else 'Artisan',
            bio=application.bio,
            trade_category=application.trade_category,
            location_text=application.location_text,
            location_lat=application.location_lat,
            location_lng=application.location_lng,
            is_published=True,
        ))

    role_exists = UserRole.query.filter_by(user_id=application.user_id, role='artisan').first()
    if not role_exists:
        db.session.add(UserRole(user_id=application.user_id, role='artisan'))

    db.session.commit()
    flash(f"Artisan application for {applicant.full_name if applicant else 'this user'} approved.", 'success')
    return redirect(url_for('sokoindex.applications_list'))


@sokoindex_bp.route('/applications/<uuid:id>/reject', methods=['POST'])
def reject_application(id):
    if not g.user:
        return redirect(url_for('auth.login'))
    application = ArtisanApplication.query.get_or_404(id)
    application.status = 'rejected'
    application.rejection_reason = request.form.get('reason', '')
    application.reviewed_by = g.user.id
    application.reviewed_at = datetime.utcnow()
    db.session.commit()
    applicant = User.query.get(application.user_id)
    flash(f"Artisan application for {applicant.full_name if applicant else 'this user'} rejected.", 'warning')
    return redirect(url_for('sokoindex.applications_list'))


# ─────────────────────────────────────────────
# Portfolio moderation
# ─────────────────────────────────────────────

@sokoindex_bp.route('/portfolio-review')
def portfolio_review_list():
    if not g.user:
        return redirect(url_for('auth.login'))
    items = Portfolio.query.order_by(Portfolio.status.desc(), Portfolio.created_at.desc()).all()
    return render_template('sokoindex/portfolio_review.html', items=items)


@sokoindex_bp.route('/portfolio-review/<uuid:id>/approve', methods=['POST'])
def approve_portfolio(id):
    if not g.user:
        return redirect(url_for('auth.login'))
    item = Portfolio.query.get_or_404(id)
    item.status = 'approved'
    item.reviewed_by = g.user.id
    item.reviewed_at = datetime.utcnow()
    db.session.commit()
    flash(f'Portfolio item "{item.title}" approved.', 'success')
    return redirect(url_for('sokoindex.portfolio_review_list'))


@sokoindex_bp.route('/portfolio-review/<uuid:id>/reject', methods=['POST'])
def reject_portfolio(id):
    if not g.user:
        return redirect(url_for('auth.login'))
    item = Portfolio.query.get_or_404(id)
    item.status = 'rejected'
    item.rejection_reason = request.form.get('reason', '')
    item.reviewed_by = g.user.id
    item.reviewed_at = datetime.utcnow()
    db.session.commit()
    flash(f'Portfolio item "{item.title}" rejected.', 'warning')
    return redirect(url_for('sokoindex.portfolio_review_list'))


# ─────────────────────────────────────────────
# Bookings oversight (read-only)
# ─────────────────────────────────────────────

@sokoindex_bp.route('/bookings')
def bookings_list():
    if not g.user:
        return redirect(url_for('auth.login'))
    status = request.args.get('status', '')
    page = request.args.get('page', 1, type=int)

    query = SokoIndexBooking.query
    if status:
        query = query.filter_by(status=status)
    pagination = query.order_by(SokoIndexBooking.created_at.desc()).paginate(page=page, per_page=25, error_out=False)
    return render_template('sokoindex/bookings.html', pagination=pagination, bookings=pagination.items, status=status)


# ─────────────────────────────────────────────
# Complaints review + artisan suspension
# ─────────────────────────────────────────────

@sokoindex_bp.route('/complaints')
def complaints_list():
    if not g.user:
        return redirect(url_for('auth.login'))
    complaints = Complaint.query.order_by(Complaint.status.desc(), Complaint.created_at.desc()).all()
    return render_template('sokoindex/complaints.html', complaints=complaints)


@sokoindex_bp.route('/complaints/<uuid:id>/resolve', methods=['POST'])
def resolve_complaint(id):
    if not g.user:
        return redirect(url_for('auth.login'))
    complaint = Complaint.query.get_or_404(id)
    complaint.status = request.form.get('status', 'resolved')
    complaint.artisan_at_fault = request.form.get('artisan_at_fault') == 'true'
    complaint.resolution_notes = request.form.get('resolution_notes', '')
    complaint.resolved_by = g.user.id
    complaint.resolved_at = datetime.utcnow()
    db.session.commit()
    flash('Complaint resolved.', 'success')
    return redirect(url_for('sokoindex.complaints_list'))


@sokoindex_bp.route('/artisans/<uuid:id>/suspend', methods=['POST'])
def suspend_artisan(id):
    if not g.user:
        return redirect(url_for('auth.login'))
    profile = ArtisanProfile.query.get_or_404(id)
    profile.is_suspended = True
    profile.suspension_reason = request.form.get('reason', '')
    db.session.commit()
    flash(f'Artisan {profile.display_name} has been suspended.', 'danger')
    return redirect(url_for('sokoindex.complaints_list'))


@sokoindex_bp.route('/artisans/<uuid:id>/unsuspend', methods=['POST'])
def unsuspend_artisan(id):
    if not g.user:
        return redirect(url_for('auth.login'))
    profile = ArtisanProfile.query.get_or_404(id)
    profile.is_suspended = False
    profile.suspension_reason = ''
    db.session.commit()
    flash(f'Artisan {profile.display_name} has been reinstated.', 'success')
    return redirect(url_for('sokoindex.complaints_list'))
