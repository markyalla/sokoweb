from flask import Blueprint, render_template, g, redirect, url_for, request, flash, session
from app.routes.models import Store, Product, Order, ShopCashoutRequest, User
from app.routes import analytics
from app import db

store_owner_bp = Blueprint('store_owner', __name__)

ACTIVE_STATUSES = [
    'pending', 'payment_pending', 'payment_confirmed', 'preparing',
    'ready_for_pickup', 'assigned_to_driver', 'picked_up', 'in_transit',
]
COMPLETED_STATUSES = ['delivered']
HISTORY_STATUSES = ['cancelled', 'refunded', 'failed']


def _get_owned_stores():
    """All stores owned by the logged-in user, ordered by name."""
    if not g.user:
        return []
    return Store.query.filter_by(owner_user_id=str(g.user.id)).order_by(Store.name).all()


def _get_store():
    """Return the active (session-selected) store for the logged-in user.

    Auto-selects when the user owns exactly one store, preserving the old
    zero-interstitial behavior. Returns None if the user owns zero stores,
    or owns more than one and hasn't picked one yet — callers must send
    them to the shop picker in that case.
    """
    if not g.user:
        return None
    stores = _get_owned_stores()
    if not stores:
        return None
    active_id = session.get('active_store_id')
    store = next((s for s in stores if str(s.id) == active_id), None)
    if store:
        return store
    if len(stores) == 1:
        session['active_store_id'] = str(stores[0].id)
        return stores[0]
    return None


def _require_owner():
    """Validate auth + store ownership. Returns (store, error_redirect)."""
    if not g.user:
        return None, redirect(url_for('auth.login'))
    if not _get_owned_stores():
        flash('No store is linked to your account.', 'danger')
        return None, redirect(url_for('auth.login'))
    store = _get_store()
    if not store:
        return None, redirect(url_for('store_owner.select_store'))
    return store, None


@store_owner_bp.context_processor
def inject_store_switcher():
    if not g.user:
        return {}
    return {
        'owner_stores': _get_owned_stores(),
        'active_store_id': session.get('active_store_id'),
    }


# ── Shop picker / switcher ─────────────────────────────────────────────────────

@store_owner_bp.route('/select')
def select_store():
    if not g.user:
        return redirect(url_for('auth.login'))
    stores = _get_owned_stores()
    if not stores:
        flash('No store is linked to your account.', 'danger')
        return redirect(url_for('auth.login'))
    if len(stores) == 1:
        session['active_store_id'] = str(stores[0].id)
        return redirect(url_for('store_owner.dashboard'))
    return render_template('store/select_store.html', stores=stores)


@store_owner_bp.route('/select/<uuid:store_id>', methods=['POST'])
def set_active_store(store_id):
    if not g.user:
        return redirect(url_for('auth.login'))
    store = next((s for s in _get_owned_stores() if str(s.id) == str(store_id)), None)
    if not store:
        flash('That shop is not linked to your account.', 'danger')
        return redirect(url_for('store_owner.select_store'))
    session['active_store_id'] = str(store.id)
    flash(f'Switched to {store.name}.', 'success')
    return redirect(url_for('store_owner.dashboard'))


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

    try:
        charts = analytics.dashboard_charts(store_id=store.id)
    except Exception as e:
        print(f"Store Dashboard Charts Error: {e}")
        import traceback; traceback.print_exc()
        charts = {}

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
        charts=charts,
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

    from datetime import datetime

    if new_status == 'preparing':
        prep_mins = request.form.get('estimated_prep_mins', '').strip()
        if not prep_mins.isdigit() or not (1 <= int(prep_mins) <= 180):
            flash('Enter an estimated prep time between 1 and 180 minutes.', 'danger')
            return redirect(url_for('store_owner.orders', tab='active'))
        order.estimated_prep_mins = int(prep_mins)
        order.accepted_at = datetime.utcnow()

    order.status = new_status
    if new_status == 'ready_for_pickup':
        order.ready_at = datetime.utcnow()
    db.session.commit()
    flash(f'Order #{str(order.id)[:8]} updated to {new_status.replace("_", " ").title()}.', 'success')
    return redirect(url_for('store_owner.orders', tab='active'))


# ── Update estimated prep time (while already preparing) ─────────────────────

@store_owner_bp.route('/orders/<uuid:order_id>/eta', methods=['POST'])
def update_order_eta(order_id):
    store, err = _require_owner()
    if err:
        return err

    order = Order.query.get_or_404(order_id)
    if order.store_id != str(store.id):
        flash('Unauthorized.', 'danger')
        return redirect(url_for('store_owner.orders'))

    if order.status != 'preparing':
        flash('Can only update the estimate while an order is being prepared.', 'danger')
        return redirect(url_for('store_owner.orders', tab='active'))

    prep_mins = request.form.get('estimated_prep_mins', '').strip()
    if not prep_mins.isdigit() or not (1 <= int(prep_mins) <= 180):
        flash('Enter an estimated prep time between 1 and 180 minutes.', 'danger')
        return redirect(url_for('store_owner.orders', tab='active'))

    order.estimated_prep_mins = int(prep_mins)
    db.session.commit()
    flash(f'Updated estimated time for order #{str(order.id)[:8]}.', 'success')
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
    pending_cashout = sum(float(c.amount or 0) for c in cashouts if c.status in ('pending', 'needs_correction'))
    available       = max(0.0, total_earned - paid_out - pending_cashout)

    active_cashout = next((c for c in cashouts if c.status in ('pending', 'needs_correction')), None)

    return render_template('store/earnings.html',
        store=store,
        earnings_rows=earnings_rows,
        total_earned=total_earned,
        paid_out=paid_out,
        pending_cashout=pending_cashout,
        available_balance=available,
        cashouts=cashouts,
        active_cashout=active_cashout,
    )


def _parse_cashout_form(form):
    """Parse method-specific payout destination fields from a cashout form
    into the structured ShopCashoutRequest columns."""
    method = form.get('method', 'momo')
    data = {
        'method': method,
        'momo_number': None,
        'bank_account_holder': None,
        'bank_account_number': None,
        'bank_name': None,
        'bank_branch': None,
        'note': form.get('note', '').strip() or None,
    }
    if method == 'momo':
        data['momo_number'] = form.get('momo_number', '').strip() or None
    elif method == 'bank':
        data['bank_account_holder'] = form.get('account_holder', '').strip() or None
        data['bank_account_number'] = form.get('account_number', '').strip() or None
        data['bank_name']           = form.get('bank_name', '').strip() or None
        data['bank_branch']         = form.get('bank_branch', '').strip() or None
    return data


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

    active = ShopCashoutRequest.query.filter(
        ShopCashoutRequest.store_id == str(store.id),
        ShopCashoutRequest.status.in_(['pending', 'needs_correction']),
    ).first()
    if active:
        flash('You already have an active cashout request. Edit or resubmit that one instead.', 'warning')
        return redirect(url_for('store_owner.earnings'))

    fields = _parse_cashout_form(request.form)
    cashout = ShopCashoutRequest(
        store_id=str(store.id),
        owner_user_id=str(g.user.id),
        amount=amount,
        status='pending',
        **fields,
    )
    db.session.add(cashout)
    db.session.commit()
    flash(f'Cashout request of GH₵ {amount:.2f} submitted. Admin will process it shortly.', 'success')
    return redirect(url_for('store_owner.earnings'))


@store_owner_bp.route('/cashout/<uuid:cashout_id>/resubmit', methods=['POST'])
def resubmit_cashout(cashout_id):
    store, err = _require_owner()
    if err:
        return err

    cr = ShopCashoutRequest.query.get_or_404(str(cashout_id))
    if cr.store_id != str(store.id) or cr.status != 'needs_correction':
        flash('This request cannot be resubmitted.', 'danger')
        return redirect(url_for('store_owner.earnings'))

    try:
        amount = float(request.form.get('amount', '0'))
    except ValueError:
        flash('Invalid amount.', 'danger')
        return redirect(url_for('store_owner.earnings'))

    if amount < 10:
        flash('Minimum cashout is GH₵ 10.00.', 'danger')
        return redirect(url_for('store_owner.earnings'))

    from datetime import datetime

    fields = _parse_cashout_form(request.form)
    cr.amount = amount
    for key, value in fields.items():
        setattr(cr, key, value)
    cr.status = 'pending'
    cr.correction_message = None
    cr.updated_at = datetime.utcnow()
    db.session.commit()
    flash('Cashout request resubmitted for review.', 'success')
    return redirect(url_for('store_owner.earnings'))
