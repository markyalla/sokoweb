from app import db
from datetime import datetime
import uuid
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy import cast, String as SAString

# ----------------------------------------------------------------
# ACCOUNT DATABASE (sokoaccount)
# ----------------------------------------------------------------
class User(db.Model):
    __bind_key__ = 'account'
    __tablename__ = 'users'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    phone_number = db.Column(db.String(20), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    profile_image_url = db.Column(db.String(255))
    gender = db.Column(db.String(50))
    date_of_birth = db.Column(db.DateTime)
    is_email_verified = db.Column(db.Boolean, default=False)
    is_phone_verified = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    last_login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships (all within sokoaccount — safe to use ForeignKey)
    kyc = db.relationship('KYCSubmission', backref='user', uselist=False)
    driver_profile = db.relationship('DriverProfile', backref='user', uselist=False)
    roles = db.relationship('UserRole', backref='user', lazy=True)

    @property
    def is_authenticated(self):
        return True


class UserRole(db.Model):
    __bind_key__ = 'account'
    __tablename__ = 'user_roles'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False)
    role = db.Column(db.String(50), nullable=False)


class KYCSubmission(db.Model):
    __bind_key__ = 'account'
    __tablename__ = 'kyc_submissions'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False)
    full_name = db.Column(db.String(150))
    id_type = db.Column(db.String(50))
    id_number = db.Column(db.String(100))
    id_image_url = db.Column(db.Text)
    address = db.Column(db.Text)
    city = db.Column(db.String(100))
    country = db.Column(db.String(100))
    status = db.Column(db.String(20), default='pending')  # pending, submitted, approved, rejected
    submitted_at = db.Column(db.DateTime)
    ocr_mismatch = db.Column(db.Boolean, default=False)  # true if the typed id_number wasn't found on the ID photo by on-device OCR
    documents = db.relationship('KYCDocument', backref='kyc', lazy=True)


class KYCDocument(db.Model):
    __bind_key__ = 'account'
    __tablename__ = 'kyc_documents'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kyc_id = db.Column(UUID(as_uuid=True), db.ForeignKey('kyc_submissions.id'), nullable=False)
    document_type = db.Column(db.String(50))  # id_front, id_back, selfie
    file_url = db.Column(db.String(255), nullable=False)


class DriverProfile(db.Model):
    __bind_key__ = 'account'
    __tablename__ = 'driver_profiles'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')
    vehicle_type = db.Column(db.String(50))
    vehicle_model = db.Column(db.String(100))
    vehicle_color = db.Column(db.String(50))
    vehicle_plate = db.Column(db.String(20))
    license_number = db.Column(db.String(50))
    current_lat = db.Column(db.Float)
    current_lng = db.Column(db.Float)
    rating = db.Column(db.Numeric(3, 2), default=5.00)
    total_deliveries = db.Column(db.Integer, default=0)
    is_online = db.Column(db.Boolean, default=False)
    is_available = db.Column(db.Boolean, default=False)
# ----------------------------------------------------------------
# SHOPPER DATABASE (sokoshopper)
# ----------------------------------------------------------------
class Category(db.Model):
    __bind_key__ = 'shopper'
    __tablename__ = 'categories'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(120), nullable=False, unique=True)
    image_url = db.Column(db.String(255))
    sort_order = db.Column(db.SmallInteger, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Store(db.Model):
    __bind_key__ = 'shopper'
    __tablename__ = 'stores'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id = db.Column(db.String(36), nullable=False)
    category_id = db.Column(db.String(36), db.ForeignKey('categories.id'), nullable=True)
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(220), nullable=False, unique=True)
    description = db.Column(db.Text)
    logo_url = db.Column(db.String(255))
    cover_image_url = db.Column(db.String(255))
    phone_number = db.Column(db.String(20))
    email = db.Column(db.String(255))
    address = db.Column(db.Text)
    city = db.Column(db.String(100))
    country = db.Column(db.String(100), default='Ghana')
    lat = db.Column(db.Float)
    lng = db.Column(db.Float)
    status = db.Column(db.String(20), default='active') # active, inactive, suspended
    rating = db.Column(db.Numeric(3, 2), default=0.00)
    total_reviews = db.Column(db.Integer, default=0)
    delivery_fee = db.Column(db.Numeric(10, 2), default=0.00)
    min_order_amount = db.Column(db.Numeric(10, 2), default=0.00)
    avg_processing_time = db.Column(db.SmallInteger, default=30)
    is_open = db.Column(db.Boolean, default=True)
    opens_at = db.Column(db.String(10)) # Store as string to match Go's time type
    closes_at = db.Column(db.String(10))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Product(db.Model):
    __bind_key__ = 'shopper'
    __tablename__ = 'products'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = db.Column(db.String(36), nullable=False)
    section_id = db.Column(db.String(36))
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    base_price = db.Column(db.Numeric(10, 2), nullable=False)
    discount_price = db.Column(db.Numeric(10, 2))
    image_url = db.Column(db.String(255))
    is_available = db.Column(db.Boolean, default=True)
    is_featured = db.Column(db.Boolean, default=False)
    processing_time = db.Column(db.SmallInteger)
    weight_kg = db.Column(db.Numeric(10, 2))
    product_metadata = db.Column('metadata', JSONB) # Renamed to avoid SQLAlchemy reserved keyword
    tags = db.Column(db.ARRAY(db.String))
    sort_order = db.Column(db.SmallInteger, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Order(db.Model):
    __bind_key__ = 'shopper'
    __tablename__ = 'orders'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(db.String(36), nullable=False)
    store_id = db.Column(db.String(36), nullable=False)
    driver_user_id = db.Column(db.String(36))
    status = db.Column(db.String(50), default='pending')
    subtotal = db.Column(db.Numeric(10, 2))
    delivery_fee = db.Column(db.Numeric(10, 2), default=0.00)
    discount_amount = db.Column(db.Numeric(10, 2), default=0.00)
    total_amount = db.Column(db.Numeric(10, 2))
    delivery_address = db.Column(db.Text)
    delivery_lat = db.Column(db.Float)
    delivery_lng = db.Column(db.Float)
    delivery_instructions = db.Column(db.Text)
    estimated_prep_mins = db.Column(db.SmallInteger)
    estimated_delivery_mins = db.Column(db.SmallInteger)
    accepted_at = db.Column(db.DateTime)
    ready_at = db.Column(db.DateTime)
    driver_assigned_at = db.Column(db.DateTime)  # set when admin assigns driver; cleared on timeout
    picked_up_at = db.Column(db.DateTime)
    delivered_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.Text)
    paystack_reference = db.Column(db.String(100))
    promo_code = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    items = db.relationship('OrderItem', backref='order', lazy=True)

class OrderItem(db.Model):
    __bind_key__ = 'shopper'
    __tablename__ = 'order_items'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = db.Column(db.String(36), db.ForeignKey('orders.id'), nullable=False)
    product_id = db.Column(db.String(36), nullable=False)
    name = db.Column(db.String(255))
    quantity = db.Column(db.Integer)
    unit_price = db.Column(db.Numeric(10, 2))
    options = db.Column(JSONB)
    special_note = db.Column(db.Text)
    image_url = db.Column(db.String(255))

class OrderDelivery(db.Model):
    __bind_key__ = 'shopper'
    __tablename__ = 'order_deliveries'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = db.Column(UUID(as_uuid=True), db.ForeignKey('orders.id'), nullable=False)
    driver_id = db.Column(UUID(as_uuid=True), nullable=False)
    status = db.Column(db.String(50), default='assigned') # assigned, picked_up, in_transit, delivered
    current_lat = db.Column(db.Float)
    current_lng = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Payment(db.Model):
    __bind_key__ = 'shopper'
    __tablename__ = 'payments'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = db.Column(UUID(as_uuid=True), db.ForeignKey('orders.id'), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    currency = db.Column(db.String(3), default='GHS')
    status = db.Column(db.String(20), default='pending') # pending, success, failed, refunded
    payment_method = db.Column(db.String(50)) # e.g., paystack, mobile_money, card
    paystack_reference = db.Column(db.String(100), unique=True)
    paystack_transaction_id = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# ----------------------------------------------------------------
# DELIVERY DATABASE (sokodelivery)
# ----------------------------------------------------------------
class Delivery(db.Model):
    __bind_key__ = 'delivery'
    __tablename__ = 'delivery_orders'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), nullable=False)
    description = db.Column(db.String(500), nullable=False)
    package_size = db.Column(db.String(20))
    vehicle_type = db.Column(db.String(30))
    pickup_address = db.Column(db.Text)
    pickup_lat = db.Column(db.Numeric(10, 8))
    pickup_lng = db.Column(db.Numeric(11, 8))
    dropoff_address = db.Column(db.Text)
    dropoff_lat = db.Column(db.Numeric(10, 8))
    dropoff_lng = db.Column(db.Numeric(11, 8))
    receiver_name = db.Column(db.String(150))
    receiver_phone = db.Column(db.String(20))
    receiver_location_notes = db.Column(db.Text)
    receiver_user_id = db.Column(UUID(as_uuid=True))
    sender_name = db.Column(db.String(150))
    sender_phone = db.Column(db.String(20))
    sender_image_url = db.Column(db.String(500))
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    distance_km = db.Column(db.Numeric(8, 3))
    payment_status = db.Column(db.String(20), default='pending')
    payer_type = db.Column(db.String(20), default='sender')  # sender | receiver
    paystack_ref = db.Column(db.String(100), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = db.relationship('DeliveryItem', backref='delivery', lazy=True)


class DeliveryItem(db.Model):
    """Individual items inside a parcel — one delivery can carry multiple items."""
    __bind_key__ = 'delivery'
    __tablename__ = 'delivery_items'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    delivery_id = db.Column(UUID(as_uuid=True), db.ForeignKey('delivery_orders.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    weight_kg = db.Column(db.Numeric(8, 2))
    is_fragile = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class DeliveryAssignment(db.Model):
    __bind_key__ = 'delivery'
    __tablename__ = 'delivery_assignments'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = db.Column(db.String(36), nullable=False)   # GORM stored as text (no type:uuid tag)
    driver_id = db.Column(UUID(as_uuid=True))             # has gorm:"type:uuid", so it is uuid
    source = db.Column(db.String(30), default='sokodelivery')
    status = db.Column(db.String(50), default='pending')
    pickup_address = db.Column(db.Text)
    pickup_lat = db.Column(db.Numeric(10, 8))
    pickup_lng = db.Column(db.Numeric(11, 8))
    dropoff_address = db.Column(db.Text)
    dropoff_lat = db.Column(db.Numeric(10, 8))
    dropoff_lng = db.Column(db.Numeric(11, 8))
    distance_km = db.Column(db.Numeric(8, 3))
    delivery_fee = db.Column(db.Numeric(10, 2), default=0)
    driver_earnings = db.Column(db.Numeric(10, 2), default=0)
    platform_cut = db.Column(db.Numeric(10, 2), default=0)
    delivery_pin = db.Column(db.String(6))
    is_express = db.Column(db.Boolean, default=False)
    is_fragile = db.Column(db.Boolean, default=False)
    customer_rating = db.Column(db.SmallInteger)
    broadcast_at = db.Column(db.DateTime)
    accepted_at = db.Column(db.DateTime)
    arrived_vendor_at = db.Column(db.DateTime)
    picked_up_at = db.Column(db.DateTime)
    delivered_at = db.Column(db.DateTime)
    failed_at = db.Column(db.DateTime)
    fail_reason = db.Column(db.String(255))
    delivery_photo_url = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Defined here (after DeliveryAssignment) so we can use cast() to bridge
# Delivery.id (uuid) with DeliveryAssignment.order_id (text/varchar).
Delivery.assignments = db.relationship(
    'DeliveryAssignment',
    primaryjoin=cast(Delivery.id, SAString) == DeliveryAssignment.order_id,
    foreign_keys=[DeliveryAssignment.order_id],
    backref=db.backref('delivery', uselist=False),
    lazy=True,
    passive_deletes=True,
)

class DriverEarning(db.Model):
    __bind_key__ = 'delivery'
    __tablename__ = 'driver_earnings'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_user_id = db.Column(UUID(as_uuid=True), nullable=False)
    assignment_id = db.Column(UUID(as_uuid=True))
    amount = db.Column(db.Numeric(10, 2))
    bonus = db.Column(db.Numeric(10, 2), default=0)
    status = db.Column(db.String(20), default='pending')  # pending, settled, on_hold
    payment_ref = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class DriverCashoutRequest(db.Model):
    __bind_key__ = 'delivery'
    __tablename__ = 'driver_cashout_requests'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_user_id = db.Column(UUID(as_uuid=True), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    method = db.Column(db.String(20))   # momo | bank
    status = db.Column(db.String(20), default='pending')  # pending | paid | rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ShopCashoutRequest(db.Model):
    __bind_key__ = 'shopper'
    __tablename__ = 'shop_cashout_requests'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = db.Column(db.String(36), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    method = db.Column(db.String(20))   # momo | bank | cash
    status = db.Column(db.String(20), default='pending')  # pending | paid | rejected
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# ----------------------------------------------------------------
# BANK DATABASE (sokobank)
# ----------------------------------------------------------------
class BankAccount(db.Model):
    __bind_key__ = 'bank'
    __tablename__ = 'bank_accounts'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), nullable=False)
    balance = db.Column(db.Numeric(15, 2), default=0.00)
    currency = db.Column(db.String(3), default='GHS')
    status = db.Column(db.String(20), default='active')

class Transaction(db.Model):
    __bind_key__ = 'bank'
    __tablename__ = 'transactions'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = db.Column(UUID(as_uuid=True), nullable=False)
    amount = db.Column(db.Numeric(15, 2))
    type = db.Column(db.String(20)) # credit, debit
    description = db.Column(db.String(255))
    reference = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ----------------------------------------------------------------
# SUSU DATABASE (sokosusu)
# ----------------------------------------------------------------
class SusuGroup(db.Model):
    __bind_key__ = 'susu'
    __tablename__ = 'susu_groups'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(150), nullable=False)
    contribution_amount = db.Column(db.Numeric(18, 2), nullable=False)
    cycle_period = db.Column(db.String(20), default='monthly')  # weekly, monthly
    max_members = db.Column(db.Integer)
    status = db.Column(db.String(20), default='forming')  # forming, active, completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships — all within sokosusu, ForeignKey is safe
    members = db.relationship('SusuMember', backref='group', lazy=True)
    contributions = db.relationship('SusuContribution', backref='group', lazy=True)
    payouts = db.relationship('SusuPayout', backref='group', lazy=True)


class SusuMember(db.Model):
    __bind_key__ = 'susu'
    __tablename__ = 'susu_members'
    group_id = db.Column(UUID(as_uuid=True), db.ForeignKey('susu_groups.id'), primary_key=True)
    # user_id has NO ForeignKey — User lives in sokoaccount (different DB bind)
    # Integrity is enforced at the application level, not the DB level
    user_id = db.Column(UUID(as_uuid=True), primary_key=True, nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_admin = db.Column(db.Boolean, default=False)
    position = db.Column(db.Integer)  # payout turn order

    def get_user(self):
        """Cross-database user lookup — call explicitly when needed."""
        return User.query.get(self.user_id)


class SusuContribution(db.Model):
    __bind_key__ = 'susu'
    __tablename__ = 'susu_contributions'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id = db.Column(UUID(as_uuid=True), db.ForeignKey('susu_groups.id'), nullable=False)
    # user_id has NO ForeignKey — cross-database reference to sokoaccount.users
    user_id = db.Column(UUID(as_uuid=True), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    transaction_id = db.Column(UUID(as_uuid=True))
    cycle_number = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_user(self):
        """Cross-database user lookup — call explicitly when needed."""
        return User.query.get(self.user_id)


class SusuPayout(db.Model):
    __bind_key__ = 'susu'
    __tablename__ = 'susu_payouts'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id = db.Column(UUID(as_uuid=True), db.ForeignKey('susu_groups.id'), nullable=False)
    # user_id has NO ForeignKey — cross-database reference to sokoaccount.users
    user_id = db.Column(UUID(as_uuid=True), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    transaction_id = db.Column(UUID(as_uuid=True))
    payout_date = db.Column(db.DateTime, default=datetime.utcnow)
    cycle_number = db.Column(db.Integer, nullable=False)

    def get_user(self):
        """Cross-database user lookup — call explicitly when needed."""
        return User.query.get(self.user_id)

# ----------------------------------------------------------------
# SOKOINDEX DATABASE (sokoindex) — artisan marketplace
# ----------------------------------------------------------------
class ArtisanApplication(db.Model):
    __bind_key__ = 'sokoindex'
    __tablename__ = 'artisan_applications'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # user_id has NO ForeignKey — cross-database reference to sokoaccount.users
    # Identity (name, ID number/photo) is NOT collected here — it's already
    # verified via the user's sokoaccount KYC submission.
    user_id = db.Column(UUID(as_uuid=True), nullable=False)
    bio = db.Column(db.Text, nullable=False)
    trade_category = db.Column(db.String(100), nullable=False)
    location_text = db.Column(db.String(255))
    location_lat = db.Column(db.Numeric(10, 7))
    location_lng = db.Column(db.Numeric(10, 7))
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    rejection_reason = db.Column(db.Text)
    reviewed_by = db.Column(UUID(as_uuid=True))
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime)

    def get_user(self):
        return User.query.get(self.user_id)


class ArtisanProfile(db.Model):
    __bind_key__ = 'sokoindex'
    __tablename__ = 'artisan_profiles'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), nullable=False, unique=True)
    display_name = db.Column(db.String(150), nullable=False)
    bio = db.Column(db.Text)
    trade_category = db.Column(db.String(100), nullable=False)
    location_text = db.Column(db.String(255))
    location_lat = db.Column(db.Numeric(10, 7))
    location_lng = db.Column(db.Numeric(10, 7))
    profile_image_path = db.Column(db.Text)
    avg_rating = db.Column(db.Numeric(3, 2), default=0.00)
    rating_count = db.Column(db.Integer, default=0)
    recommendation_count = db.Column(db.Integer, default=0)
    is_published = db.Column(db.Boolean, default=False)
    is_suspended = db.Column(db.Boolean, default=False)
    suspension_reason = db.Column(db.Text)
    joining_fee_paid = db.Column(db.Boolean, default=False)
    joining_payment_ref = db.Column(db.String(255))
    # One-time payment to unlock incoming-jobs (customer contact info + accept/reject)
    contact_unlock_paid = db.Column(db.Boolean, default=False)
    contact_unlock_payment_ref = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    portfolio_items = db.relationship('Portfolio', backref='artisan', lazy=True)

    def get_user(self):
        return User.query.get(self.user_id)


class Portfolio(db.Model):
    __bind_key__ = 'sokoindex'
    __tablename__ = 'portfolios'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    artisan_id = db.Column(UUID(as_uuid=True), db.ForeignKey('artisan_profiles.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    image_path_1 = db.Column(db.Text, nullable=False)
    image_path_2 = db.Column(db.Text)
    image_path_3 = db.Column(db.Text)
    image_path_4 = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    rejection_reason = db.Column(db.Text)
    reviewed_by = db.Column(UUID(as_uuid=True))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime)


class SokoIndexBooking(db.Model):
    __bind_key__ = 'sokoindex'
    __tablename__ = 'sokoindex_bookings'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # customer_id has NO ForeignKey — cross-database reference to sokoaccount.users
    customer_id = db.Column(UUID(as_uuid=True), nullable=False)
    artisan_id = db.Column(UUID(as_uuid=True), db.ForeignKey('artisan_profiles.id'), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), default='pending')
    # pending, accepted, rejected, awaiting_confirmation, completed, cancelled
    rejection_reason = db.Column(db.Text)
    contact_unlocked = db.Column(db.Boolean, default=False)
    contact_payment_ref = db.Column(db.String(255))
    contact_payment_status = db.Column(db.String(20), default='pending')  # pending, paid, bypassed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    artisan = db.relationship('ArtisanProfile', foreign_keys=[artisan_id])

    def get_customer(self):
        return User.query.get(self.customer_id)


class SokoIndexRating(db.Model):
    __bind_key__ = 'sokoindex'
    __tablename__ = 'sokoindex_ratings'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id = db.Column(UUID(as_uuid=True), db.ForeignKey('sokoindex_bookings.id'), nullable=False, unique=True)
    customer_id = db.Column(UUID(as_uuid=True), nullable=False)
    artisan_id = db.Column(UUID(as_uuid=True), db.ForeignKey('artisan_profiles.id'), nullable=False)
    score = db.Column(db.SmallInteger, nullable=False)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Recommendation(db.Model):
    __bind_key__ = 'sokoindex'
    __tablename__ = 'recommendations'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    artisan_id = db.Column(UUID(as_uuid=True), db.ForeignKey('artisan_profiles.id'), nullable=False)
    recommended_by_user_id = db.Column(UUID(as_uuid=True), nullable=False)
    booking_id = db.Column(UUID(as_uuid=True))
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Complaint(db.Model):
    __bind_key__ = 'sokoindex'
    __tablename__ = 'complaints'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id = db.Column(UUID(as_uuid=True), db.ForeignKey('sokoindex_bookings.id'), nullable=False)
    complainant_user_id = db.Column(UUID(as_uuid=True), nullable=False)
    against_artisan_id = db.Column(UUID(as_uuid=True), db.ForeignKey('artisan_profiles.id'), nullable=False)
    category = db.Column(db.String(100))
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='open')  # open, in_review, resolved, dismissed
    artisan_at_fault = db.Column(db.Boolean)
    resolution_notes = db.Column(db.Text)
    resolved_by = db.Column(UUID(as_uuid=True))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)

    booking = db.relationship('SokoIndexBooking', foreign_keys=[booking_id])
    artisan = db.relationship('ArtisanProfile', foreign_keys=[against_artisan_id])

    def get_complainant(self):
        return User.query.get(self.complainant_user_id)


class SokoIndexFeatureFlag(db.Model):
    __bind_key__ = 'sokoindex'
    __tablename__ = 'sokoindex_feature_flags'
    id = db.Column(db.Integer, primary_key=True)
    contact_unlock_enabled = db.Column(db.Boolean, default=False)
    joining_fee_enabled = db.Column(db.Boolean, default=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SokoIndexCustomerUnlock(db.Model):
    """One row per customer who has paid the one-time contact-unlock fee.
    Unlocked=True means this customer can see every artisan's contact info
    and book freely — not tied to any single booking or artisan."""
    __bind_key__ = 'sokoindex'
    __tablename__ = 'sokoindex_customer_unlocks'
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), nullable=False, unique=True)
    unlocked = db.Column(db.Boolean, default=False)
    payment_ref = db.Column(db.String(255))
    payment_status = db.Column(db.String(20), default='pending')  # pending, paid, bypassed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_user(self):
        return User.query.get(self.user_id)