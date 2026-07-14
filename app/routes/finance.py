from flask import Blueprint, render_template, g, redirect, url_for, request, flash
from sqlalchemy import cast, String, desc
from app.routes.models import (
    User, Store, Order, OrderItem, OrderDelivery,
    Delivery, DeliveryAssignment, DriverEarning,
    DriverCashoutRequest, ShopCashoutRequest, Payment,
)
from app import db
from datetime import datetime
import uuid as _uuid

finance_bp = Blueprint('finance', __name__)


def _require_login():
    if not g.user:
        return redirect(url_for('auth.login'))


# ── Mark a driver cashout request as paid ────────────────────────
@finance_bp.route('/driver-cashout/<uuid:cashout_id>/mark-paid', methods=['POST'])
def driver_cashout_mark_paid(cashout_id):
    redir = _require_login()
    if redir:
        return redir
    cr = DriverCashoutRequest.query.get_or_404(str(cashout_id))
    if cr.status != 'pending':
        flash(f'Request is already {cr.status}.', 'warning')
    else:
        cr.status = 'paid'
        cr.updated_at = datetime.utcnow()
        db.session.commit()
        flash(f'Driver cashout of GH₵ {float(cr.amount):.2f} marked as paid.', 'success')
    return redirect(url_for('finance.track_expenses', **request.args))


# ── Create a shop cashout request (admin records a payout) ───────
@finance_bp.route('/shop-cashout/create', methods=['POST'])
def shop_cashout_create():
    redir = _require_login()
    if redir:
        return redir
    store_id = request.form.get('store_id', '').strip()
    amount_str = request.form.get('amount', '').strip()
    method = request.form.get('method', 'momo').strip()
    note = request.form.get('note', '').strip()

    if not store_id or not amount_str:
        flash('Store and amount are required.', 'danger')
        return redirect(url_for('finance.track_expenses'))

    try:
        amount = float(amount_str)
        if amount <= 0:
            raise ValueError
    except ValueError:
        flash('Enter a valid positive amount.', 'danger')
        return redirect(url_for('finance.track_expenses'))

    cr = ShopCashoutRequest(
        id=_uuid.uuid4(),
        store_id=store_id,
        amount=amount,
        method=method,
        note=note,
        status='pending',
    )
    db.session.add(cr)
    db.session.commit()
    store = Store.query.filter(cast(Store.id, String) == store_id).first()
    name = store.name if store else store_id[:8]
    flash(f'Payout request of GH₵ {amount:.2f} recorded for {name}.', 'success')
    return redirect(url_for('finance.track_expenses'))


# ── Mark a shop cashout request as paid ──────────────────────────
@finance_bp.route('/shop-cashout/<uuid:cashout_id>/mark-paid', methods=['POST'])
def shop_cashout_mark_paid(cashout_id):
    redir = _require_login()
    if redir:
        return redir
    cr = ShopCashoutRequest.query.get_or_404(str(cashout_id))
    if cr.status != 'pending':
        flash(f'Request is already {cr.status}.', 'warning')
    else:
        cr.status = 'paid'
        cr.updated_at = datetime.utcnow()
        db.session.commit()
        store = Store.query.filter(cast(Store.id, String) == cr.store_id).first()
        name = store.name if store else cr.store_id[:8]
        flash(f'Store payout of GH₵ {float(cr.amount):.2f} to {name} marked as paid.', 'success')
    return redirect(url_for('finance.track_expenses', **request.args))


# ── Reset a driver's financial records (clears cashouts + earning rows) ──
@finance_bp.route('/driver/<driver_uid>/reset-balance', methods=['POST'])
def driver_reset_balance(driver_uid):
    redir = _require_login()
    if redir:
        return redir
    DriverCashoutRequest.query.filter(
        cast(DriverCashoutRequest.driver_user_id, String) == driver_uid
    ).delete(synchronize_session=False)
    DriverEarning.query.filter(
        cast(DriverEarning.driver_user_id, String) == driver_uid
    ).delete(synchronize_session=False)
    db.session.commit()
    flash('Driver balance reset — all cashout requests and earning records cleared.', 'success')
    return redirect(url_for('finance.track_expenses', **request.args))


# ── Main dashboard ────────────────────────────────────────────────
@finance_bp.route('/track-expenses')
def track_expenses():
    redir = _require_login()
    if redir:
        return redir

    date_from_str = request.args.get('date_from', '')
    date_to_str   = request.args.get('date_to', '')
    date_from = date_to = None
    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str, '%Y-%m-%d')
        except ValueError:
            pass
    if date_to_str:
        try:
            date_to = datetime.strptime(date_to_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        except ValueError:
            pass

    # ── 0. Refunded shopper orders ────────────────────────────────
    refunded_orders = Order.query.filter(Order.status == 'refunded') \
        .order_by(desc(Order.cancelled_at)).all()
    refunded_order_ids = [str(o.id) for o in refunded_orders]

    refunded_payments = {}
    if refunded_order_ids:
        ref_payments = Payment.query.filter(
            cast(Payment.order_id, String).in_(refunded_order_ids)
        ).all()
        refunded_payments = {str(p.order_id): p for p in ref_payments}

    refunded_customer_ids = list({o.user_id for o in refunded_orders if o.user_id})
    refunded_customers = {}
    if refunded_customer_ids:
        refunded_customers = {
            str(u.id): u
            for u in User.query.filter(cast(User.id, String).in_(refunded_customer_ids)).all()
        }

    refunded_stores_ids = list({o.store_id for o in refunded_orders if o.store_id})
    refunded_stores = {}
    if refunded_stores_ids:
        refunded_stores = {
            str(s.id): s
            for s in Store.query.filter(cast(Store.id, String).in_(refunded_stores_ids)).all()
        }

    refund_display = [
        {
            'order': o,
            'payment': refunded_payments.get(str(o.id)),
            'customer': refunded_customers.get(str(o.user_id)),
            'store': refunded_stores.get(str(o.store_id)),
        }
        for o in refunded_orders
    ]
    total_refunded = sum(float(o.total_amount or 0) for o in refunded_orders)

    # ── 1. Completed shopper orders ───────────────────────────────
    sq = Order.query.filter(Order.status == 'delivered')
    if date_from:
        sq = sq.filter(Order.delivered_at >= date_from)
    if date_to:
        sq = sq.filter(Order.delivered_at <= date_to)
    shopper_orders = sq.order_by(desc(Order.delivered_at)).all()
    shopper_order_ids = [str(o.id) for o in shopper_orders]

    all_items = OrderItem.query.filter(OrderItem.order_id.in_(shopper_order_ids)).all() if shopper_order_ids else []
    items_by_order = {}
    for item in all_items:
        items_by_order.setdefault(str(item.order_id), []).append(item)

    shopper_deliveries = (
        OrderDelivery.query.filter(cast(OrderDelivery.order_id, String).in_(shopper_order_ids)).all()
        if shopper_order_ids else []
    )
    delivery_by_order = {str(od.order_id): od for od in shopper_deliveries}

    # ── 2. Completed parcel deliveries ────────────────────────────
    psq = DeliveryAssignment.query.filter(DeliveryAssignment.status == 'delivered')
    if date_from:
        psq = psq.filter(DeliveryAssignment.delivered_at >= date_from)
    if date_to:
        psq = psq.filter(DeliveryAssignment.delivered_at <= date_to)
    parcel_assignments = psq.order_by(desc(DeliveryAssignment.delivered_at)).all()

    parcel_order_ids = [a.order_id for a in parcel_assignments]
    parcel_orders_map = {}
    if parcel_order_ids:
        rows = Delivery.query.filter(cast(Delivery.id, String).in_(parcel_order_ids)).all()
        parcel_orders_map = {str(r.id): r for r in rows}

    # ── 3. All driver cashout requests ────────────────────────────
    driver_cashout_rows = DriverCashoutRequest.query.order_by(desc(DriverCashoutRequest.created_at)).all()
    cashout_by_driver = {}
    for cr in driver_cashout_rows:
        cashout_by_driver.setdefault(str(cr.driver_user_id), []).append(cr)
    pending_driver_cashouts = [c for c in driver_cashout_rows if c.status == 'pending']

    # ── 4. All shop cashout requests ──────────────────────────────
    shop_cashout_rows = ShopCashoutRequest.query.order_by(desc(ShopCashoutRequest.created_at)).all()
    shop_cashout_by_store = {}
    for cr in shop_cashout_rows:
        shop_cashout_by_store.setdefault(str(cr.store_id), []).append(cr)
    pending_shop_cashouts = [c for c in shop_cashout_rows if c.status == 'pending']

    # ── 5. Driver earning records (parcel) ────────────────────────
    parcel_earn_rows = DriverEarning.query.all()
    parcel_earn_by_driver = {}
    for er in parcel_earn_rows:
        uid = str(er.driver_user_id)
        parcel_earn_by_driver[uid] = parcel_earn_by_driver.get(uid, 0.0) + float(er.amount or 0)

    # ── 6. Collect all driver IDs ─────────────────────────────────
    driver_ids = set()
    for od in shopper_deliveries:
        if od.driver_id:
            driver_ids.add(str(od.driver_id))
    for pa in parcel_assignments:
        if pa.driver_id:
            driver_ids.add(str(pa.driver_id))
    driver_ids.update(cashout_by_driver.keys())
    driver_ids.update(parcel_earn_by_driver.keys())

    users_map = {}
    if driver_ids:
        users_map = {str(u.id): u for u in User.query.filter(cast(User.id, String).in_(list(driver_ids))).all()}

    # ── 7. Store map (all stores that have sales OR cashout requests) ──
    store_ids_with_sales = {o.store_id for o in shopper_orders}
    store_ids_with_cashout = {cr.store_id for cr in shop_cashout_rows}
    all_store_ids = list(store_ids_with_sales | store_ids_with_cashout)
    stores_map = {}
    if all_store_ids:
        stores_map = {str(s.id): s for s in Store.query.filter(cast(Store.id, String).in_(all_store_ids)).all()}

    # ── 8. Per-store breakdown ────────────────────────────────────
    store_stats = {}
    for order in shopper_orders:
        sid = str(order.store_id)
        if sid not in store_stats:
            store_stats[sid] = _empty_store_stat(stores_map.get(sid))
        st = store_stats[sid]
        st['order_count'] += 1
        gross = float(order.subtotal or 0)
        fee   = float(order.delivery_fee or 0)
        st['gross_product_sales']      += gross
        st['store_payout']             += gross * 0.80
        st['platform_product_cut']     += gross * 0.20
        st['delivery_fees_total']      += fee
        st['platform_delivery_cut']    += fee * 0.40
        st['driver_delivery_earnings'] += fee * 0.60

    # Attach cashout data to each store (including stores with no sales but with cashout history)
    for sid in store_ids_with_cashout:
        if sid not in store_stats:
            store_stats[sid] = _empty_store_stat(stores_map.get(sid))
        crs = shop_cashout_by_store.get(sid, [])
        paid    = sum(float(c.amount or 0) for c in crs if c.status == 'paid')
        pending = sum(float(c.amount or 0) for c in crs if c.status == 'pending')
        store_stats[sid]['cashout_paid']    = paid
        store_stats[sid]['cashout_pending'] = pending
        store_stats[sid]['cashout_balance'] = store_stats[sid]['store_payout'] - paid - pending
        store_stats[sid]['cashouts']        = crs

    # Ensure cashout fields exist on all store entries
    for st in store_stats.values():
        if 'cashouts' not in st:
            st['cashouts']        = []
            st['cashout_paid']    = 0.0
            st['cashout_pending'] = 0.0
            st['cashout_balance'] = st['store_payout']

    store_list = sorted(store_stats.values(), key=lambda x: x['gross_product_sales'], reverse=True)

    # ── 9. Per-driver breakdown ───────────────────────────────────
    shopper_earn_by_driver = {}
    shopper_count_by_driver = {}
    for order in shopper_orders:
        od = delivery_by_order.get(str(order.id))
        if od and od.driver_id:
            uid = str(od.driver_id)
            shopper_earn_by_driver[uid] = shopper_earn_by_driver.get(uid, 0.0) + float(order.delivery_fee or 0) * 0.60
            shopper_count_by_driver[uid] = shopper_count_by_driver.get(uid, 0) + 1

    parcel_count_by_driver = {}
    for pa in parcel_assignments:
        if pa.driver_id:
            uid = str(pa.driver_id)
            parcel_count_by_driver[uid] = parcel_count_by_driver.get(uid, 0) + 1

    driver_list = []
    for uid in driver_ids:
        parcel_earn  = parcel_earn_by_driver.get(uid, 0.0)
        shopper_earn = shopper_earn_by_driver.get(uid, 0.0)
        total_earn   = parcel_earn + shopper_earn
        crs     = cashout_by_driver.get(uid, [])
        paid    = sum(float(c.amount or 0) for c in crs if c.status == 'paid')
        pending = sum(float(c.amount or 0) for c in crs if c.status == 'pending')
        balance = total_earn - paid - pending
        driver_list.append({
            'user': users_map.get(uid),
            'uid': uid,
            'parcel_deliveries':  parcel_count_by_driver.get(uid, 0),
            'shopper_deliveries': shopper_count_by_driver.get(uid, 0),
            'total_deliveries':   parcel_count_by_driver.get(uid, 0) + shopper_count_by_driver.get(uid, 0),
            'parcel_earn':   parcel_earn,
            'shopper_earn':  shopper_earn,
            'total_earn':    total_earn,
            'cashout_paid':    paid,
            'cashout_pending': pending,
            'remaining_balance': balance,
            'cashouts': crs,
        })
    driver_list.sort(key=lambda x: x['total_earn'], reverse=True)

    # Enrich pending driver cashouts with user info
    pending_driver_cashouts_rich = [
        {'cashout': c, 'user': users_map.get(str(c.driver_user_id))}
        for c in pending_driver_cashouts
    ]

    # Enrich pending shop cashouts with store info
    pending_shop_cashouts_rich = [
        {'cashout': c, 'store': stores_map.get(str(c.store_id))}
        for c in pending_shop_cashouts
    ]

    # ── 10. SokoApp grand totals ──────────────────────────────────
    platform_from_products         = sum(s['platform_product_cut']   for s in store_list)
    platform_from_shopper_delivery = sum(s['platform_delivery_cut']  for s in store_list)
    platform_from_parcel_delivery  = sum(float(pa.platform_cut or 0) for pa in parcel_assignments)
    platform_grand_total           = platform_from_products + platform_from_shopper_delivery + platform_from_parcel_delivery

    total_driver_earnings = sum(d['total_earn']        for d in driver_list)
    total_driver_paid     = sum(d['cashout_paid']      for d in driver_list)
    total_driver_pending  = sum(d['cashout_pending']   for d in driver_list)
    total_driver_balance  = sum(d['remaining_balance'] for d in driver_list)
    total_store_payout    = sum(s['store_payout']      for s in store_list)
    total_gross_sales     = sum(s['gross_product_sales'] for s in store_list)
    total_store_paid      = sum(s['cashout_paid']      for s in store_list)
    total_store_pending   = sum(s['cashout_pending']   for s in store_list)

    # ── 11. Display lists (capped) ────────────────────────────────
    parcel_display = [
        {
            'assignment': pa,
            'order': parcel_orders_map.get(str(pa.order_id)),
            'driver': users_map.get(str(pa.driver_id)) if pa.driver_id else None,
        }
        for pa in parcel_assignments[:50]
    ]
    shopper_display = [
        {
            'order': o,
            'store': stores_map.get(str(o.store_id)),
            'driver': users_map.get(str(delivery_by_order[str(o.id)].driver_id))
                      if delivery_by_order.get(str(o.id)) and delivery_by_order[str(o.id)].driver_id
                      else None,
        }
        for o in shopper_orders[:50]
    ]

    # All stores (for the "Record Payout" modal dropdown)
    all_stores = Store.query.filter_by(status='active').order_by(Store.name).all()

    return render_template(
        'superadmin/track_expenses.html',
        refund_display=refund_display,
        total_refunded=total_refunded,
        platform_from_products=platform_from_products,
        platform_from_shopper_delivery=platform_from_shopper_delivery,
        platform_from_parcel_delivery=platform_from_parcel_delivery,
        platform_grand_total=platform_grand_total,
        total_driver_earnings=total_driver_earnings,
        total_driver_paid=total_driver_paid,
        total_driver_pending=total_driver_pending,
        total_driver_balance=total_driver_balance,
        total_store_payout=total_store_payout,
        total_gross_sales=total_gross_sales,
        total_store_paid=total_store_paid,
        total_store_pending=total_store_pending,
        driver_list=driver_list,
        store_list=store_list,
        parcel_display=parcel_display,
        shopper_display=shopper_display,
        pending_driver_cashouts=pending_driver_cashouts_rich,
        pending_shop_cashouts=pending_shop_cashouts_rich,
        all_stores=all_stores,
        date_from=date_from_str,
        date_to=date_to_str,
        total_shopper_orders=len(shopper_orders),
        total_parcel_deliveries=len(parcel_assignments),
    )


def _empty_store_stat(store_obj):
    return {
        'store': store_obj,
        'order_count': 0,
        'gross_product_sales': 0.0,
        'store_payout': 0.0,
        'platform_product_cut': 0.0,
        'delivery_fees_total': 0.0,
        'platform_delivery_cut': 0.0,
        'driver_delivery_earnings': 0.0,
        'cashout_paid': 0.0,
        'cashout_pending': 0.0,
        'cashout_balance': 0.0,
        'cashouts': [],
    }
