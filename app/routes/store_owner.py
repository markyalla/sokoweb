from flask import Blueprint, render_template, g, redirect, url_for, request, flash
from app.routes.models import Store, Product, Order, ShopCashoutRequest, User
from app import db

store_owner_bp = Blueprint('store_owner', __name__)

ACTIVE_STATUSES = [
    'pending', 'payment_pending', 'payment_confirmed', 'preparing',
    'ready_for_pickup', 'assigned_to_driver', 'picked_up', 'in_transit',
]
COMPLETED_STATUSES = ['delivered']
HISTORY_STATUSES = ['cancelled', 'refunded', 'failed']


def _get_store():
    """Return the store owned by the logged-in user, or None."""
    if not g.user:
        return None
    return Store.query.filter_by(owner_user_id=str(g.user.id)).first()


def _require_owner():
    """Validate auth + store ownership. Returns (store, error_redirect)."""
    if not g.user:
        return None, redirect(url_for('auth.login'))
    store = _get_store()
    if not store:
        flash('No store is linked to your account.', 'danger')
        return None, redirect(url_for('auth.login'))
    return store, None


# ── Dashboard ─────────────────────────────────────────────────────────────────

@store_owner_bp.route('/')
def dashboard():
    store, err = _require_owner()
    if err:
        return err

    all_orders = Order.query.filter_by(store_id=str(store.id)).all()
    products = Product.query.filter_by(store_id=str(store.id)).all()

    active_orders    = [o for o in all_orders if o.status in ACTIVE_STATUSES]
    completed_orders = [o for o in all_orders if o.status in COMPLETED_STATUSES]
    history_orders   = [o for o in all_orders if o.status in HISTORY_STATUSES]

    # Store cut = 80% of subtotal on delivered orders
    total_earned = sum(float(o.subtotal or 0) * 0.8 for o in completed_orders)

    cashouts = ShopCashoutRequest.query.filter_by(store_id=str(store.id)).all()
    paid_out        = sum(float(c.amount or 0) for c in cashouts if c.status == 'paid')
    pending_cashout = sum(float(c.amount or 0) for c in cashouts if c.status == 'pending')
    available       = max(0.0, total_earned - paid_out - pending_cashout)

    recent_orders = Order.query.filter_by(store_id=str(store.id))\
        .order_by(Order.created_at.desc()).limit(6).all()

    # Customer names for recent orders
    cust_ids = list({o.user_id for o in recent_orders if o.user_id})
    customers_map = {
        str(u.id): u.full_name
        for u in User.query.filter(User.id.in_(cust_ids)).all()
    } if cust_ids else {}

    return render_template('store/dashboard.html',
        store=store,
        active_count=len(active_orders),
        completed_count=len(completed_orders),
        history_count=len(history_orders),
        products_count=len(products),
        total_earned=total_earned,
        available_balance=available,
        pending_cashout=pending_cashout,
        recent_orders=recent_orders,
        customers_map=customers_map,
    )


# ── Toggle store open/closed ───────────────────────────────────────────────────

@store_owner_bp.route('/toggle-open', methods=['POST'])
def toggle_open():
    store, err = _require_owner()
    if err:
        return err
    store.is_open = not store.is_open
    db.session.commit()
    flash(f'Your store is now {"Open" if store.is_open else "Closed"}.', 'info')
    return redirect(url_for('store_owner.dashboard'))


# ── Orders ────────────────────────────────────────────────────────────────────

@store_owner_bp.route('/orders')
def orders():
    store, err = _require_owner()
    if err:
        return err

    tab = request.args.get('tab', 'active')
    all_orders = Order.query.filter_by(store_id=str(store.id))\
        .order_by(Order.created_at.desc()).all()

    active    = [o for o in all_orders if o.status in ACTIVE_STATUSES]
    completed = [o for o in all_orders if o.status in COMPLETED_STATUSES]
    history   = [o for o in all_orders if o.status in HISTORY_STATUSES]

    cust_ids = list({o.user_id for o in all_orders if o.user_id})
    customers_map = {
        str(u.id): u.full_name
        for u in User.query.filter(User.id.in_(cust_ids)).all()
    } if cust_ids else {}

    return render_template('store/orders.html',
        store=store,
        tab=tab,
        active_orders=active,
        completed_orders=completed,
        history_orders=history,
        customers_map=customers_map,
    )


# ── Update order status (preparing / ready) ───────────────────────────────────

@store_owner_bp.route('/orders/<uuid:order_id>/status', methods=['POST'])
def update_order_status(order_id):
    store, err = _require_owner()
    if err:
        return err

    order = Order.query.get_or_404(order_id)
    if order.store_id != str(store.id):
        flash('Unauthorized.', 'danger')
        return redirect(url_for('store_owner.orders'))

    allowed = {'preparing', 'ready_for_pickup'}
    new_status = request.form.get('status')
    if new_status not in allowed:
        flash('Invalid status update.', 'danger')
        return redirect(url_for('store_owner.orders'))

    order.status = new_status
    if new_status == 'ready_for_pickup':
        from datetime import datetime
        order.ready_at = datetime.utcnow()
    db.session.commit()
    flash(f'Order #{str(order.id)[:8]} updated to {new_status.replace("_", " ").title()}.', 'success')
    return redirect(url_for('store_owner.orders', tab='active'))


# ── Products ──────────────────────────────────────────────────────────────────

@store_owner_bp.route('/products')
def products():
    store, err = _require_owner()
    if err:
        return err

    all_products = Product.query.filter_by(store_id=str(store.id))\
        .order_by(Product.sort_order, Product.name).all()

    return render_template('store/products.html', store=store, products=all_products)


@store_owner_bp.route('/products/<uuid:product_id>/toggle', methods=['POST'])
def toggle_product(product_id):
    store, err = _require_owner()
    if err:
        return err

    product = Product.query.get_or_404(product_id)
    if product.store_id != str(store.id):
        flash('Unauthorized.', 'danger')
        return redirect(url_for('store_owner.products'))

    product.is_available = not product.is_available
    db.session.commit()
    status = 'available' if product.is_available else 'unavailable'
    flash(f'"{product.name}" is now {status}.', 'info')
    return redirect(url_for('store_owner.products'))


# ── Earnings & Cashout ────────────────────────────────────────────────────────

@store_owner_bp.route('/earnings')
def earnings():
    store, err = _require_owner()
    if err:
        return err

    delivered = Order.query.filter_by(store_id=str(store.id), status='delivered')\
        .order_by(Order.delivered_at.desc()).all()

    earnings_rows = [
        {
            'order': o,
            'subtotal': float(o.subtotal or 0),
            'store_cut': float(o.subtotal or 0) * 0.8,
        }
        for o in delivered
    ]
    total_earned = sum(r['store_cut'] for r in earnings_rows)

    cashouts = ShopCashoutRequest.query.filter_by(store_id=str(store.id))\
        .order_by(ShopCashoutRequest.created_at.desc()).all()

    paid_out        = sum(float(c.amount or 0) for c in cashouts if c.status == 'paid')
    pending_cashout = sum(float(c.amount or 0) for c in cashouts if c.status == 'pending')
    available       = max(0.0, total_earned - paid_out - pending_cashout)

    return render_template('store/earnings.html',
        store=store,
        earnings_rows=earnings_rows,
        total_earned=total_earned,
        paid_out=paid_out,
        pending_cashout=pending_cashout,
        available_balance=available,
        cashouts=cashouts,
    )


@store_owner_bp.route('/cashout', methods=['POST'])
def request_cashout():
    store, err = _require_owner()
    if err:
        return err

    try:
        amount = float(request.form.get('amount', '0'))
    except ValueError:
        flash('Invalid amount.', 'danger')
        return redirect(url_for('store_owner.earnings'))

    if amount < 10:
        flash('Minimum cashout is GH₵ 10.00.', 'danger')
        return redirect(url_for('store_owner.earnings'))

    method = request.form.get('method', 'momo')

    if method == 'momo':
        momo_number = request.form.get('momo_number', '').strip()
        note = f'MoMo: {momo_number}' if momo_number else None
    elif method == 'bank':
        account_number = request.form.get('account_number', '').strip()
        account_holder = request.form.get('account_holder', '').strip()
        bank_name      = request.form.get('bank_name', '').strip()
        parts = []
        if account_number: parts.append(f'Account: {account_number}')
        if account_holder: parts.append(f'Holder: {account_holder}')
        if bank_name:      parts.append(f'Bank: {bank_name}')
        note = ' | '.join(parts) or None
    else:
        note = request.form.get('note', '').strip() or None

    cashout = ShopCashoutRequest(
        store_id=str(store.id),
        amount=amount,
        method=method,
        status='pending',
        note=note,
    )
    db.session.add(cashout)
    db.session.commit()
    flash(f'Cashout request of GH₵ {amount:.2f} submitted. Admin will process it shortly.', 'success')
    return redirect(url_for('store_owner.earnings'))
