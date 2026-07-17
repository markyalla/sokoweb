from flask import Blueprint, render_template, g, redirect, url_for, request, flash, current_app
from sqlalchemy import func, desc, cast, String
from app.routes.models import Delivery, DeliveryAssignment, DriverEarning, DriverProfile, User, DriverComplaint
from app import db
from datetime import datetime
import math

delivery_bp = Blueprint('delivery', __name__)


def _require_login():
    """Gate every route in this blueprint to sokodelivery_admin / superadmin."""
    if not g.user:
        return redirect(url_for('auth.login'))
    roles = [r.role for r in g.user.roles]
    if 'superadmin' not in roles and 'sokodelivery_admin' not in roles:
        flash('You do not have access to that section.', 'danger')
        return redirect(url_for('dashboard.index'))


def _api_base():
    return current_app.config.get('API_BASE_URL', 'http://192.168.2.195:8082').rstrip('/')


STATUS_CLASSES = {
    'pending':             'secondary',
    'broadcast':           'info',
    'assigned':            'warning',   # admin assigned, driver not yet accepted
    'accepted':            'primary',   # driver confirmed
    'arrived_at_vendor':   'info',
    'picked_up':           'warning',
    'in_transit':          'warning',
    'arrived_at_customer': 'success',
    'delivered':           'success',
    'failed':              'danger',
    'cancelled':           'dark',
}

# delivery_orders has no status column — status lives on delivery_assignments.
# These helpers let the admin filter and count by the latest assignment status.

def _ids_with_status(statuses):
    """Return a subquery of delivery order_ids (as text) matching any of the given statuses."""
    return (
        db.session.query(DeliveryAssignment.order_id)
        .filter(DeliveryAssignment.status.in_(statuses))
        .distinct()
        .subquery()
    )


def _delivery_id_filter(subq):
    """
    Compare Delivery.id (uuid column) against a subquery that returns text order_ids.
    PostgreSQL won't do uuid = text implicitly, so cast Delivery.id to text first.
    """
    return cast(Delivery.id, String).in_(subq)


def _latest_status_map(order_ids):
    """
    Given a list of order id strings, return {order_id_str: status_str}
    using the most recent assignment for each.
    """
    if not order_ids:
        return {}
    rows = (
        DeliveryAssignment.query
        .filter(DeliveryAssignment.order_id.in_(order_ids))
        .order_by(desc(DeliveryAssignment.created_at))
        .all()
    )
    seen = {}
    for a in rows:
        key = str(a.order_id)
        if key not in seen:
            seen[key] = a.status
    return seen


# ── Deliveries list ───────────────────────────────────────────────────────────

@delivery_bp.route('/')
def orders_list():
    redir = _require_login()
    if redir:
        return redir

    status_filter  = request.args.get('status', '')
    payer_filter   = request.args.get('payer_type', '')
    payment_filter = request.args.get('payment_status', '')
    search         = request.args.get('q', '').strip()
    page           = request.args.get('page', 1, type=int)
    per_page       = 20

    q = Delivery.query.order_by(desc(Delivery.created_at))

    if status_filter:
        q = q.filter(_delivery_id_filter(_ids_with_status([status_filter])))
    if payer_filter:
        q = q.filter(Delivery.payer_type == payer_filter)
    if payment_filter:
        q = q.filter(Delivery.payment_status == payment_filter)
    if search:
        like = f'%{search}%'
        q = q.filter(
            Delivery.receiver_name.ilike(like) |
            Delivery.receiver_phone.ilike(like) |
            Delivery.description.ilike(like)
        )

    pagination = q.paginate(page=page, per_page=per_page, error_out=False)

    # Build status map for current page (one extra query, no N+1)
    page_ids = [str(d.id) for d in pagination.items]
    status_map = _latest_status_map(page_ids)

    # Stats
    active_sq    = _ids_with_status(['assigned', 'accepted', 'in_transit', 'picked_up'])
    delivered_sq = _ids_with_status(['delivered'])

    total     = Delivery.query.count()
    active    = db.session.query(func.count(Delivery.id)).filter(_delivery_id_filter(active_sq)).scalar()
    delivered = db.session.query(func.count(Delivery.id)).filter(_delivery_id_filter(delivered_sq)).scalar()
    unpaid    = Delivery.query.filter_by(payment_status='pending').count()
    revenue   = float(
        db.session.query(func.sum(Delivery.total_amount))
        .filter(Delivery.payment_status == 'success').scalar() or 0
    )

    return render_template(
        'delivery/delivery.html',
        orders=pagination.items,
        pagination=pagination,
        status_map=status_map,
        status_filter=status_filter,
        payer_filter=payer_filter,
        payment_filter=payment_filter,
        search=search,
        status_classes=STATUS_CLASSES,
        stats={
            'total': total,
            'active': active,
            'delivered': delivered,
            'unpaid': unpaid,
            'revenue': revenue,
        },
    )


@delivery_bp.route('/<uuid:order_id>')
def order_detail(order_id):
    redir = _require_login()
    if redir:
        return redir

    delivery = Delivery.query.get_or_404(str(order_id))
    assignments = (DeliveryAssignment.query
                   .filter_by(order_id=str(order_id))
                   .order_by(desc(DeliveryAssignment.created_at))
                   .all())
    current_status = assignments[0].status if assignments else 'pending'

    # All active drivers for the manual assignment dropdown
    driver_rows = (
        db.session.query(DriverProfile, User)
        .join(User, User.id == DriverProfile.user_id)
        .filter(DriverProfile.status == 'active')
        .order_by(User.full_name)
        .all()
    )
    # Map user_id → full name for resolving UUIDs in the assignments table
    drivers_map = {str(dp.user_id): u.full_name for dp, u in driver_rows}

    return render_template(
        'delivery/delivery_detail.html',
        order=delivery,
        assignments=assignments,
        current_status=current_status,
        status_classes=STATUS_CLASSES,
        driver_rows=driver_rows,
        drivers_map=drivers_map,
    )


@delivery_bp.route('/<uuid:order_id>/update-status', methods=['POST'])
def update_order_status(order_id):
    redir = _require_login()
    if redir:
        return redir

    new_status = request.form.get('status')
    if new_status:
        # Status lives on the assignment, not the delivery row
        assignment = (DeliveryAssignment.query
                      .filter_by(order_id=str(order_id))
                      .order_by(desc(DeliveryAssignment.created_at))
                      .first())
        if assignment:
            assignment.status = new_status
            db.session.commit()
            flash(f'Status updated to {new_status}.', 'success')
        else:
            flash('No assignment found — assign a driver first.', 'warning')

    return redirect(url_for('delivery.order_detail', order_id=order_id))


# ── Assignments ───────────────────────────────────────────────────────────────

@delivery_bp.route('/assignments')
def assignments_list():
    redir = _require_login()
    if redir:
        return redir

    status_filter = request.args.get('status', '')
    page          = request.args.get('page', 1, type=int)
    per_page      = 20

    q = DeliveryAssignment.query.order_by(desc(DeliveryAssignment.created_at))
    if status_filter:
        q = q.filter(DeliveryAssignment.status == status_filter)

    pagination = q.paginate(page=page, per_page=per_page, error_out=False)

    order_ids = [a.order_id for a in pagination.items]   # already strings (text column)
    deliveries_map = {}
    if order_ids:
        # cast Delivery.id (uuid) to text for comparison with text order_ids
        rows = Delivery.query.filter(cast(Delivery.id, String).in_(order_ids)).all()
        deliveries_map = {str(r.id): r for r in rows}

    return render_template(
        'delivery/assignments.html',
        assignments=pagination.items,
        pagination=pagination,
        orders_map=deliveries_map,
        status_filter=status_filter,
        status_classes=STATUS_CLASSES,
    )


@delivery_bp.route('/assignments/<uuid:assignment_id>/update-status', methods=['POST'])
def update_assignment_status(assignment_id):
    redir = _require_login()
    if redir:
        return redir

    new_status = request.form.get('status')
    assignment = DeliveryAssignment.query.get_or_404(str(assignment_id))
    if new_status:
        assignment.status = new_status
        db.session.commit()
        flash(f'Assignment status updated to {new_status}.', 'success')

    return redirect(url_for('delivery.order_detail', order_id=assignment.order_id))


@delivery_bp.route('/assignments/<uuid:assignment_id>/delete', methods=['POST'])
def delete_assignment(assignment_id):
    redir = _require_login()
    if redir:
        return redir
    assignment = DeliveryAssignment.query.get_or_404(str(assignment_id))
    order_id = assignment.order_id
    db.session.delete(assignment)
    db.session.commit()
    flash('Assignment deleted.', 'danger')
    return redirect(url_for('delivery.order_detail', order_id=order_id))


@delivery_bp.route('/orders/<uuid:order_id>/delete', methods=['POST'])
def delete_order(order_id):
    redir = _require_login()
    if redir:
        return redir
    from app.routes.models import DeliveryItem
    order = Delivery.query.get_or_404(str(order_id))
    # DriverEarning links to assignments, not directly to the order
    assignment_ids = [a.id for a in DeliveryAssignment.query.filter_by(order_id=str(order.id)).all()]
    if assignment_ids:
        DriverEarning.query.filter(DriverEarning.assignment_id.in_(assignment_ids)).delete(synchronize_session=False)
    DeliveryItem.query.filter_by(delivery_id=order.id).delete(synchronize_session=False)
    DeliveryAssignment.query.filter_by(order_id=str(order.id)).delete(synchronize_session=False)
    db.session.delete(order)
    db.session.commit()
    flash('Delivery order deleted.', 'danger')
    return redirect(url_for('delivery.orders_list'))


# ── Driver Earnings ───────────────────────────────────────────────────────────

@delivery_bp.route('/earnings')
def earnings_list():
    redir = _require_login()
    if redir:
        return redir

    page     = request.args.get('page', 1, type=int)
    per_page = 25

    q = DriverEarning.query.order_by(desc(DriverEarning.created_at))
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)

    total_earned  = db.session.query(func.sum(DriverEarning.amount)).scalar() or 0
    total_settled = db.session.query(func.sum(DriverEarning.amount)).filter_by(status='settled').scalar() or 0
    total_pending = db.session.query(func.sum(DriverEarning.amount)).filter_by(status='pending').scalar() or 0

    return render_template(
        'delivery/earnings.html',
        earnings=pagination.items,
        pagination=pagination,
        total_earned=float(total_earned),
        total_settled=float(total_settled),
        total_pending=float(total_pending),
    )


# ── Admin: Driver Complaints ─────────────────────────────────────────────────

@delivery_bp.route('/complaints')
def driver_complaints_list():
    redir = _require_login()
    if redir:
        return redir
    complaints = DriverComplaint.query.order_by(
        DriverComplaint.status.desc(), DriverComplaint.created_at.desc()
    ).all()

    complainant_ids = [c.complainant_user_id for c in complaints if c.complainant_user_id]
    driver_ids = [c.against_driver_id for c in complaints if c.against_driver_id]
    all_ids = list(set(complainant_ids + driver_ids))
    users_by_id = {u.id: u for u in User.query.filter(User.id.in_(all_ids)).all()} if all_ids else {}

    return render_template(
        'delivery/driver_complaints.html',
        complaints=complaints, users_by_id=users_by_id,
    )


@delivery_bp.route('/complaints/<uuid:id>/resolve', methods=['POST'])
def resolve_driver_complaint(id):
    redir = _require_login()
    if redir:
        return redir
    complaint = DriverComplaint.query.get_or_404(id)
    complaint.status = request.form.get('status', 'resolved')
    complaint.driver_at_fault = request.form.get('driver_at_fault') == 'true'
    complaint.resolution_notes = request.form.get('resolution_notes', '')
    complaint.resolved_by = g.user.id
    complaint.resolved_at = datetime.utcnow()
    db.session.commit()
    flash('Complaint resolved.', 'success')
    return redirect(url_for('delivery.driver_complaints_list'))


# ── Admin: Manual Driver Assignment ──────────────────────────────────────────

@delivery_bp.route('/<uuid:order_id>/assign-manual', methods=['POST'])
def assign_driver_manual(order_id):
    redir = _require_login()
    if redir:
        return redir

    driver_id = request.form.get('driver_id')
    if not driver_id:
        flash('Please select a driver.', 'warning')
        return redirect(url_for('delivery.order_detail', order_id=order_id))

    delivery = Delivery.query.get_or_404(str(order_id))

    assignment = (DeliveryAssignment.query
                  .filter_by(order_id=str(order_id))
                  .order_by(desc(DeliveryAssignment.created_at))
                  .first())

    # Idempotent: re-submitting the same driver (a double-click on Assign, or
    # the admin re-assigning after not noticing the flash message on a page
    # refresh) must not re-touch driver_id/status — a DB trigger watches that
    # column pair and pushes a "new delivery" notification to the driver's
    # phone, so a no-op write here would fire a duplicate push for an
    # assignment that already exists.
    if (assignment and assignment.status == 'assigned'
            and str(assignment.driver_id) == driver_id):
        flash('Driver is already assigned to this order.', 'info')
        return redirect(url_for('delivery.order_detail', order_id=order_id))

    if assignment and assignment.status in ('pending', 'broadcast'):
        # Upgrade the existing broadcast/pending assignment to this driver
        assignment.driver_id = driver_id
        assignment.status = 'assigned'
    elif assignment and assignment.status not in ('delivered', 'cancelled', 'failed'):
        # Active assignment — swap the driver, reset to assigned so driver must re-accept
        assignment.driver_id = driver_id
        assignment.status = 'assigned'
    else:
        # No usable assignment — create a fresh one
        assignment = DeliveryAssignment(
            order_id=str(delivery.id),
            driver_id=driver_id,
            source='sokodelivery',
            status='assigned',
            pickup_address=delivery.pickup_address,
            pickup_lat=delivery.pickup_lat,
            pickup_lng=delivery.pickup_lng,
            dropoff_address=delivery.dropoff_address,
            dropoff_lat=delivery.dropoff_lat,
            dropoff_lng=delivery.dropoff_lng,
            distance_km=delivery.distance_km,
            delivery_fee=delivery.total_amount,
        )
        db.session.add(assignment)

    # Mark driver unavailable until the delivery is complete
    dp = DriverProfile.query.filter_by(user_id=driver_id).first()
    if dp:
        dp.is_available = False

    db.session.commit()

    driver_user = User.query.get(driver_id)
    name = driver_user.full_name if driver_user else str(driver_id)[:8]
    flash(f'Driver "{name}" assigned successfully.', 'success')
    return redirect(url_for('delivery.order_detail', order_id=order_id))


# ── Admin: Assign Nearest Driver ──────────────────────────────────────────────

def _haversine(lat1, lng1, lat2, lng2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _vehicle_matches(requested, candidate):
    """'motorbike' and 'motorcycle' refer to the same vehicle — the customer-
    facing app and the driver-profile enum just spell it differently."""
    if not requested:
        return True
    requested, candidate = (requested or '').lower(), (candidate or '').lower()
    if requested == candidate:
        return True
    motorbike_aliases = {'motorbike', 'motorcycle'}
    return requested in motorbike_aliases and candidate in motorbike_aliases


@delivery_bp.route('/<uuid:order_id>/assign-driver', methods=['POST'])
def assign_nearest_driver(order_id):
    redir = _require_login()
    if redir:
        return redir

    delivery = Delivery.query.get_or_404(str(order_id))

    pickup_lat = float(delivery.pickup_lat or 0)
    pickup_lng = float(delivery.pickup_lng or 0)

    if not pickup_lat or not pickup_lng:
        flash('No pickup GPS coordinates on this delivery — cannot find nearest driver.', 'danger')
        return redirect(url_for('delivery.order_detail', order_id=order_id))

    all_online = DriverProfile.query.filter(
        DriverProfile.is_online == True,
        DriverProfile.is_available == True,
        DriverProfile.current_lat.isnot(None),
        DriverProfile.current_lng.isnot(None),
    ).all()

    if not all_online:
        flash('No drivers are online and available right now.', 'warning')
        return redirect(url_for('delivery.order_detail', order_id=order_id))

    # A van/truck-sized item can't ride on a motorbike or bicycle — only
    # consider drivers whose vehicle matches what the customer requested.
    candidates = [d for d in all_online if _vehicle_matches(delivery.vehicle_type, d.vehicle_type)]

    if not candidates:
        flash(
            f'No {delivery.vehicle_type or "matching"}-vehicle drivers are online right now — '
            'other drivers are available if you want to assign manually instead.',
            'warning',
        )
        return redirect(url_for('delivery.order_detail', order_id=order_id))

    nearest = min(
        candidates,
        key=lambda d: _haversine(pickup_lat, pickup_lng, d.current_lat, d.current_lng)
    )
    distance_km = _haversine(pickup_lat, pickup_lng, nearest.current_lat, nearest.current_lng)

    # Update existing pending/broadcast assignment or create a new one
    assignment = (DeliveryAssignment.query
                  .filter_by(order_id=str(order_id))
                  .order_by(desc(DeliveryAssignment.created_at))
                  .first())

    # Idempotent: re-clicking "Assign Nearest" when the nearest driver hasn't
    # changed must not re-touch driver_id/status — a DB trigger watches that
    # column pair and pushes a "new delivery" notification to the driver's
    # phone, so a no-op write here would fire a duplicate push.
    if (assignment and assignment.status == 'assigned'
            and str(assignment.driver_id) == str(nearest.user_id)):
        flash('Nearest driver is already assigned to this order.', 'info')
        return redirect(url_for('delivery.order_detail', order_id=order_id))

    if assignment and assignment.status in ('pending', 'broadcast'):
        assignment.driver_id = nearest.user_id
        assignment.status = 'assigned'
    else:
        assignment = DeliveryAssignment(
            order_id=str(delivery.id),   # text column
            driver_id=nearest.user_id,
            source='sokodelivery',
            status='assigned',
            pickup_address=delivery.pickup_address,
            pickup_lat=delivery.pickup_lat,
            pickup_lng=delivery.pickup_lng,
            dropoff_address=delivery.dropoff_address,
            dropoff_lat=delivery.dropoff_lat,
            dropoff_lng=delivery.dropoff_lng,
            distance_km=delivery.distance_km,
            delivery_fee=delivery.total_amount,
        )
        db.session.add(assignment)

    # Mark driver unavailable until the delivery is complete
    nearest.is_available = False

    db.session.commit()

    flash(f'Nearest driver assigned — {distance_km:.1f} km from pickup.', 'success')
    return redirect(url_for('delivery.order_detail', order_id=order_id))


# ── Legacy redirect ───────────────────────────────────────────────────────────

@delivery_bp.route('/status')
def status():
    return redirect(url_for('delivery.orders_list'))
