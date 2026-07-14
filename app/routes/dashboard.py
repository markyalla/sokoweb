from flask import Blueprint, render_template, g, redirect, url_for, jsonify, flash
from app.routes.models import (User, Order, DeliveryAssignment, Store, Product,
                                DriverProfile, Payment, SusuGroup, KYCSubmission,
                                Delivery, Category)
from app import db
from sqlalchemy import func, cast, String
from datetime import datetime

dashboard_bp = Blueprint('dashboard', __name__)

# Mirrors the "active" definitions already used for their own stat counters
# above / in delivery.py — kept in one place so the unified feed and the
# individual per-domain pages never silently drift apart.
SHOPPER_ACTIVE_STATUSES = ['payment_confirmed', 'preparing', 'ready_for_pickup',
                           'assigned_to_driver', 'picked_up', 'in_transit']
PARCEL_ACTIVE_STATUSES = ['pending', 'broadcast', 'assigned', 'accepted',
                          'arrived_at_vendor', 'picked_up', 'in_transit']

@dashboard_bp.route('/')
def index():
    if not g.user:
        return redirect(url_for('auth.login'))

    roles = [r.role for r in g.user.roles]
    is_superadmin = 'superadmin' in roles
    show_account  = is_superadmin
    show_shopper  = is_superadmin or 'sokoshopper_admin' in roles
    show_delivery = is_superadmin or 'sokodelivery_admin' in roles
    show_susu     = is_superadmin or 'sokosusu_admin' in roles

    recent_orders = []
    recent_deliveries = []

    try:
        # ── Account ────────────────────────────────────────────────
        users_total    = User.query.count()
        users_active   = User.query.filter_by(is_active=True).count()
        kyc_pending    = KYCSubmission.query.filter(
                             KYCSubmission.status.in_(['pending', 'submitted'])).count()
        kyc_approved   = KYCSubmission.query.filter_by(status='approved').count()
        drivers_total  = DriverProfile.query.count()
        drivers_active = DriverProfile.query.filter_by(status='active').count()
        drivers_online = DriverProfile.query.filter_by(is_online=True).count()

        # ── Shopper ────────────────────────────────────────────────
        stores_total     = Store.query.count()
        stores_open      = Store.query.filter_by(is_open=True).count()
        products_total   = Product.query.count()
        categories_total = Category.query.count()
        orders_total     = Order.query.count()
        orders_pending   = Order.query.filter_by(status='pending').count()
        orders_delivered = Order.query.filter_by(status='delivered').count()
        orders_revenue   = db.session.query(func.sum(Payment.amount))\
                               .filter_by(status='success').scalar() or 0

        # ── Delivery ───────────────────────────────────────────────
        deliveries_total  = Delivery.query.count()
        deliveries_active = DeliveryAssignment.query.filter(
            DeliveryAssignment.status.in_(
                ['pending', 'broadcast', 'assigned', 'accepted',
                 'arrived_at_vendor', 'picked_up', 'in_transit']
            )).count()
        deliveries_done   = DeliveryAssignment.query.filter_by(status='delivered').count()

        # ── Susu ───────────────────────────────────────────────────
        susu_total  = SusuGroup.query.count()
        susu_active = SusuGroup.query.filter_by(status='active').count()

        # ── Recent data ────────────────────────────────────────────
        if show_shopper:
            recent_orders = Order.query.order_by(Order.created_at.desc()).limit(8).all()
        if show_delivery:
            recent_deliveries = DeliveryAssignment.query.filter(
                DeliveryAssignment.status.in_(
                    ['pending', 'broadcast', 'assigned', 'accepted', 'picked_up', 'in_transit']
                )).order_by(DeliveryAssignment.created_at.desc()).limit(8).all()

        stats = {
            'users_total':     users_total,
            'users_active':    users_active,
            'kyc_pending':     kyc_pending,
            'kyc_approved':    kyc_approved,
            'drivers_total':   drivers_total,
            'drivers_active':  drivers_active,
            'drivers_online':  drivers_online,
            'stores_total':    stores_total,
            'stores_open':     stores_open,
            'products_total':  products_total,
            'categories_total':categories_total,
            'orders_total':    orders_total,
            'orders_pending':  orders_pending,
            'orders_delivered':orders_delivered,
            'orders_revenue':  float(orders_revenue),
            'deliveries_total': deliveries_total,
            'deliveries_active':deliveries_active,
            'deliveries_done':  deliveries_done,
            'susu_total':      susu_total,
            'susu_active':     susu_active,
        }
    except Exception as e:
        print(f"Dashboard Stats Error: {e}")
        import traceback; traceback.print_exc()
        stats = {k: 0 for k in [
            'users_total','users_active','kyc_pending','kyc_approved',
            'drivers_total','drivers_active','drivers_online',
            'stores_total','stores_open','products_total','categories_total',
            'orders_total','orders_pending','orders_delivered','orders_revenue',
            'deliveries_total','deliveries_active','deliveries_done',
            'susu_total','susu_active',
        ]}

    return render_template('superadmin/dashboard.html',
                           stats=stats,
                           recent_orders=recent_orders,
                           recent_deliveries=recent_deliveries,
                           is_superadmin=is_superadmin,
                           show_account=show_account,
                           show_shopper=show_shopper,
                           show_delivery=show_delivery,
                           show_susu=show_susu)


@dashboard_bp.route('/active-deliveries')
def active_deliveries():
    """Superadmin-only feed combining every in-flight shopper order and
    parcel delivery into one timeline, regardless of store — so nothing
    needs opening two separate silos to see everything moving right now."""
    if not g.user:
        return redirect(url_for('auth.login'))
    if 'superadmin' not in [r.role for r in g.user.roles]:
        flash('You do not have access to that section.', 'danger')
        return redirect(url_for('dashboard.index'))

    orders = Order.query.filter(Order.status.in_(SHOPPER_ACTIVE_STATUSES)) \
        .order_by(Order.created_at.desc()).all()

    store_ids = list({o.store_id for o in orders if o.store_id})
    stores_map = {}
    if store_ids:
        stores_map = {s.id: s.name for s in Store.query.filter(Store.id.in_(store_ids)).all()}

    assignments = DeliveryAssignment.query.filter(DeliveryAssignment.status.in_(PARCEL_ACTIVE_STATUSES)) \
        .order_by(DeliveryAssignment.created_at.desc()).all()

    parcel_order_ids = [a.order_id for a in assignments if a.order_id]
    parcels_map = {}
    if parcel_order_ids:
        parcels_map = {
            str(p.id): p
            for p in Delivery.query.filter(cast(Delivery.id, String).in_(parcel_order_ids)).all()
        }

    driver_ids = {o.driver_user_id for o in orders if o.driver_user_id} | \
                 {str(a.driver_id) for a in assignments if a.driver_id}
    drivers_map = {}
    if driver_ids:
        rows = db.session.query(DriverProfile, User) \
            .join(User, User.id == DriverProfile.user_id) \
            .filter(User.id.in_(list(driver_ids))).all()
        drivers_map = {str(u.id): {'name': u.full_name, 'is_online': dp.is_online} for dp, u in rows}

    feed = []
    for o in orders:
        feed.append({
            'kind':        'shopper',
            'ref':         f"FD-{str(o.id)[:8].upper()}",
            'party_label': 'Store',
            'party':       stores_map.get(o.store_id, 'Unknown store'),
            'status':      o.status,
            'driver':      drivers_map.get(str(o.driver_user_id)) if o.driver_user_id else None,
            'amount':      float(o.total_amount or 0),
            'created_at':  o.created_at,
            'detail_url':  url_for('shopper.manage_store', id=o.store_id),
        })
    for a in assignments:
        parcel = parcels_map.get(str(a.order_id))
        feed.append({
            'kind':        'parcel',
            'ref':         f"PD-{str(a.id)[:8].upper()}",
            'party_label': 'Receiver',
            'party':       (parcel.receiver_name if parcel else 'Unknown receiver'),
            'status':      a.status,
            'driver':      drivers_map.get(str(a.driver_id)) if a.driver_id else None,
            'amount':      float(a.delivery_fee or 0),
            'created_at':  a.created_at,
            'detail_url':  url_for('delivery.order_detail', order_id=a.order_id),
        })

    feed.sort(key=lambda x: x['created_at'] or datetime.min, reverse=True)

    return render_template(
        'superadmin/active_deliveries.html',
        feed=feed,
        shopper_count=len(orders),
        parcel_count=len(assignments),
    )


@dashboard_bp.route('/api/drivers/online')
def api_drivers_online():
    """Lightweight JSON polled from base.html to toast the admin the moment
    a driver comes online — SokoWeb is a classic server-rendered app with no
    websocket/push channel, so polling is the pragmatic way to get this."""
    if not g.user:
        return jsonify({'drivers': []}), 401

    rows = db.session.query(DriverProfile, User) \
        .join(User, User.id == DriverProfile.user_id) \
        .filter(DriverProfile.is_online == True).all()

    return jsonify({'drivers': [{'id': str(u.id), 'name': u.full_name} for dp, u in rows]})
