from flask import Blueprint, render_template, g, redirect, url_for, request, flash, current_app, session # type: ignore
from app.routes.models import Store, Product, Order, OrderItem, Category, User, DriverProfile, OrderDelivery, Payment, ShopCashoutRequest
from app import db
from app.routes import get_relative_path
from math import radians, cos, sin, asin, sqrt
import requests
from sqlalchemy.orm import joinedload
import os
import uuid

shopper_bp = Blueprint('shopper', __name__)


def _require_role():
    if not g.user:
        return redirect(url_for('auth.login'))
    roles = [r.role for r in g.user.roles]
    if 'superadmin' not in roles and 'sokoshopper_admin' not in roles:
        flash('You do not have access to that section.', 'danger')
        return redirect(url_for('dashboard.index'))


def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculates distance between two points in km using Haversine formula."""
    if None in (lat1, lon1, lat2, lon2):
        return 999.9
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return c * 6371

@shopper_bp.route('/')
def index():
    redir = _require_role()
    if redir:
        return redir
    stores = Store.query.all()
    categories = Category.query.all()
    users = User.query.options(
        joinedload(User.kyc),
        joinedload(User.driver_profile)
    ).all()
    return render_template('superadmin/stores.html', stores=stores, categories=categories, users=users)

@shopper_bp.route('/categories/add', methods=['GET', 'POST'])
def add_category():
    redir = _require_role()
    if redir:
        return redir

    if request.method == 'POST':
        data = {
            "name": request.form.get('name'),
            "slug": request.form.get('name').lower().replace(" ", "-"),
            "image_url": request.form.get('image_url'),
            "sort_order": int(request.form.get('sort_order', 0))
        }
        
        # Proxy to Go Backend
        token = session.get('backend_token')
        headers = {"Authorization": f"Bearer {token}"}
        go_url = f"{os.getenv('API_BASE_URL', 'http://localhost:8082')}/api/v1/shopper/admin/categories"
        
        try:
            resp = requests.post(go_url, json=data, headers=headers)
            if resp.status_code == 201:
                flash('Category added successfully!', 'success')
                return redirect(url_for('shopper.index'))
            flash(f'Backend Error: {resp.text}', 'danger')
        except Exception as e:
            flash(f'Request failed: {str(e)}', 'danger')

    return render_template('superadmin/add_category.html')

@shopper_bp.route('/stores/add', methods=['GET', 'POST'])
def add_store():
    redir = _require_role()
    if redir:
        return redir
    
    if request.method == 'POST':
        name             = request.form.get('name')
        address          = request.form.get('address')
        category_id      = request.form.get('category_id')
        owner_user_id    = request.form.get('owner_user_id')
        description      = request.form.get('description')
        email            = request.form.get('email')
        phone_number     = request.form.get('phone_number')
        city             = request.form.get('city')
        delivery_fee     = request.form.get('delivery_fee', 0)
        min_order_amount = request.form.get('min_order_amount', 0)
        logo_url         = request.form.get('logo_url')

        slug = name.lower().replace(" ", "-")

        new_store = Store(
            name=name,
            address=address,
            category_id=category_id,
            owner_user_id=str(owner_user_id),
            slug=slug,
            description=description,
            email=email,
            phone_number=phone_number,
            city=city,
            delivery_fee=float(delivery_fee),
            min_order_amount=float(min_order_amount),
            logo_url=logo_url,
        )
        db.session.add(new_store)
        db.session.commit()
        flash('Store created successfully!', 'success')
        return redirect(url_for('shopper.index'))

    categories = Category.query.all()
    stores     = Store.query.all()
    users      = User.query.all()
    return render_template('superadmin/stores.html', categories=categories, stores=stores, users=users)

@shopper_bp.route('/stores/<uuid:id>/delete', methods=['POST'])
def delete_store(id):
    redir = _require_role()
    if redir:
        return redir
    store = Store.query.get_or_404(id)
    name  = store.name
    Product.query.filter_by(store_id=str(id)).delete(synchronize_session=False)
    ShopCashoutRequest.query.filter_by(store_id=str(id)).delete(synchronize_session=False)
    db.session.delete(store)
    db.session.commit()
    flash(f'Store "{name}" has been permanently removed.', 'danger')
    return redirect(url_for('shopper.index'))

@shopper_bp.route('/products/<uuid:id>/delete', methods=['POST'])
def delete_product(id):
    redir = _require_role()
    if redir:
        return redir
    product = Product.query.get_or_404(id)
    store_id = product.store_id
    db.session.delete(product)
    db.session.commit()
    flash(f'Product "{product.name}" deleted.', 'danger')
    return redirect(url_for('shopper.manage_store', id=store_id))

@shopper_bp.route('/orders/<uuid:order_id>/delete', methods=['POST'])
def delete_order(order_id):
    redir = _require_role()
    if redir:
        return redir
    order = Order.query.get_or_404(order_id)
    store_id = order.store_id
    # Delete child records first to satisfy NOT NULL FK constraints
    Payment.query.filter_by(order_id=order.id).delete(synchronize_session=False)
    OrderDelivery.query.filter_by(order_id=order.id).delete(synchronize_session=False)
    OrderItem.query.filter_by(order_id=str(order.id)).delete(synchronize_session=False)
    db.session.delete(order)
    db.session.commit()
    flash('Order deleted.', 'danger')
    return redirect(url_for('shopper.manage_store', id=store_id))

@shopper_bp.route('/stores/<uuid:id>/manage')
def manage_store(id):
    redir = _require_role()
    if redir:
        return redir
    store = Store.query.get_or_404(id)

    media_base_url = f"{os.getenv('API_BASE_URL', 'http://localhost:8082')}/api/v1/media/serve/"

    # ── Drivers ──────────────────────────────────────────────────────────────
    # Removed status filter to allow all drivers with a profile to be visible for selection
    raw_drivers = db.session.query(DriverProfile, User)\
        .join(User, DriverProfile.user_id == User.id).all()

    all_drivers = []
    eligible_drivers = []
    for dp, u in raw_drivers:
        dist = calculate_distance(store.lat, store.lng, dp.current_lat, dp.current_lng)
        driver_data = {
            'id':           str(u.id),
            'name':         u.full_name,
            'distance':     round(dist, 2),
            'phone':        u.phone_number,
            'is_online':    dp.is_online,
            'status':       dp.status,
            'vehicle_type': dp.vehicle_type or 'N/A',
        }
        all_drivers.append(driver_data)
        
        # Priority: Online, active status, and within 20km
        if dp.is_online and dp.status == 'active' and dist < 20:
            eligible_drivers.append(driver_data)

    eligible_drivers.sort(key=lambda x: x['distance'])
    all_drivers.sort(key=lambda x: x['name'])

    # ── Products ─────────────────────────────────────────────────────────────
    products = Product.query.filter_by(store_id=str(id)).all()

    # ── Orders ───────────────────────────────────────────────────────────────
    orders = Order.query.options(joinedload(Order.items))\
        .filter_by(store_id=str(id))\
        .order_by(Order.created_at.desc()).all()

    # ── Assigned-driver names map ─────────────────────────────────────────
    assigned_driver_ids = [o.driver_user_id for o in orders if o.driver_user_id]
    drivers_map = {
        str(u.id): u.full_name
        for u in User.query.filter(User.id.in_(assigned_driver_ids)).all()
    } if assigned_driver_ids else {}

    # ── Payments map  {order_id_str: Payment} ────────────────────────────────
    order_ids = [o.id for o in orders]
    payments_map = {}
    if order_ids:
        payments = Payment.query.filter(Payment.order_id.in_(order_ids)).all()
        payments_map = {str(p.order_id): p for p in payments}

    # ── Customer details map {user_id_str: {name, phone}} ────────────────────
    customer_user_ids = list({o.user_id for o in orders if o.user_id})
    customers_map = {}
    if customer_user_ids:
        customers_map = {
            str(u.id): {'name': u.full_name, 'phone': u.phone_number}
            for u in User.query.filter(User.id.in_(customer_user_ids)).all()
        }

    return render_template(
        'superadmin/manage_store.html',
        store=store,
        products=products,
        orders=orders,
        eligible_drivers=eligible_drivers,
        all_drivers=all_drivers,
        drivers_map=drivers_map,
        payments_map=payments_map,
        customers_map=customers_map,
        media_base_url=media_base_url
    )

@shopper_bp.route('/stores/<uuid:id>/products/add', methods=['POST'])
def add_product(id):
    redir = _require_role()
    if redir:
        return redir
    new_product = Product(
        store_id=str(id),
        name=request.form.get('name'),
        description=request.form.get('description'),
        base_price=request.form.get('price'),
        image_url=request.form.get('image_url'),
        is_available=True,
    )
    db.session.add(new_product)
    db.session.commit()
    flash('Product added successfully!', 'success')
    return redirect(url_for('shopper.manage_store', id=id))

@shopper_bp.route('/products/<uuid:id>/edit', methods=['POST'])
def edit_product(id):
    redir = _require_role()
    if redir:
        return redir
    product              = Product.query.get_or_404(id)
    product.name         = request.form.get('name')
    product.description  = request.form.get('description')
    product.base_price   = request.form.get('price')
    product.image_url    = request.form.get('image_url')
    product.is_available = 'is_available' in request.form
    db.session.commit()
    flash('Product updated successfully!', 'success')
    return redirect(url_for('shopper.manage_store', id=product.store_id))

@shopper_bp.route('/products/<uuid:id>/toggle-availability', methods=['POST'])
def toggle_product_availability(id):
    redir = _require_role()
    if redir:
        return redir
    product              = Product.query.get_or_404(id)
    product.is_available = not product.is_available
    db.session.commit()
    status = "available" if product.is_available else "unavailable"
    flash(f'Product {product.name} is now {status}.', 'info')
    return redirect(request.referrer)

@shopper_bp.route('/stores/<uuid:id>/toggle-open', methods=['POST'])
def toggle_store_open(id):
    redir = _require_role()
    if redir:
        return redir
    store        = Store.query.get_or_404(id)
    store.is_open = not store.is_open
    db.session.commit()
    status = "Open" if store.is_open else "Closed"
    flash(f'Store {store.name} is now {status}.', 'info')
    return redirect(request.referrer)

@shopper_bp.route('/orders/<uuid:id>/status', methods=['POST'])
def update_order_status(id):
    redir = _require_role()
    if redir:
        return redir
    order        = Order.query.get_or_404(id)
    order.status = request.form.get('status')
    db.session.commit()
    flash(f'Order status updated to {order.status}', 'success')
    return redirect(request.referrer)

@shopper_bp.route('/orders/<uuid:order_id>/assign_driver', methods=['POST'])
def assign_driver(order_id):
    redir = _require_role()
    if redir:
        return redir

    driver_id_str = request.form.get('driver_id')
    driver_uuid   = uuid.UUID(driver_id_str)
    order         = Order.query.get_or_404(order_id)
    
    from datetime import datetime
    now = datetime.utcnow()

    # Update main Order record (column is String(36))
    order.driver_user_id    = driver_id_str
    order.status            = 'assigned_to_driver'
    order.driver_assigned_at = now  # starts the 5-minute pickup countdown

    # Sync with standalone OrderDelivery tracking record
    assignment = OrderDelivery.query.filter_by(order_id=order.id).first()
    if not assignment:
        assignment = OrderDelivery(
            order_id=order.id,
            driver_id=driver_uuid,
            status='assigned',
        )
        db.session.add(assignment)
    else:
        assignment.driver_id = driver_uuid
        assignment.status    = 'assigned'

    # Mark driver unavailable until the delivery is complete
    dp = DriverProfile.query.filter_by(user_id=driver_uuid).first()
    if dp:
        dp.is_available = False

    db.session.commit()
    flash('Driver assigned successfully!', 'success')
    return redirect(request.referrer)

@shopper_bp.route('/orders')
def orders():
    redir = _require_role()
    if redir:
        return redir
    all_orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template('superadmin/orders.html', orders=all_orders)