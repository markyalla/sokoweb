"""Shopper order analytics shared by the superadmin dashboard (all stores)
and the store-owner dashboard (their own store only). Every function takes
an optional store_id — omit it for the system-wide view, pass it to scope
everything to one store.
"""
from sqlalchemy import func, extract

from app import db
from app.routes.models import Order, OrderItem, Store

# Orders that never became real fulfilled demand shouldn't count toward
# "what/when do people order" — a cancelled/refunded order tells us nothing
# useful about customer behavior. Must match order_status_enum in Postgres
# exactly (no 'failed' member exists there — binding one crashes the query).
EXCLUDED_STATUSES = ['cancelled', 'refunded']

# Ghana's fixed-date public holidays (month, day). Movable holidays (Eid,
# Easter) aren't included since they shift year to year and would need a
# lookup table — fixed dates cover the common ones without that upkeep.
GHANA_FIXED_HOLIDAYS = {
    (1, 1):   "New Year's Day",
    (3, 6):   "Independence Day",
    (5, 1):   "Labour Day",
    (7, 1):   "Republic Day",
    (8, 4):   "Founders' Day",
    (9, 21):  "Kwame Nkrumah Memorial Day",
    (12, 25): "Christmas Day",
    (12, 26): "Boxing Day",
}

WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def _base_query(store_id=None):
    q = Order.query.filter(~Order.status.in_(EXCLUDED_STATUSES))
    if store_id:
        q = q.filter(Order.store_id == str(store_id))
    return q


def top_stores(limit=10):
    """Stores ranked by order volume — system-wide, so superadmin only."""
    rows = db.session.query(
        Order.store_id,
        func.count(Order.id).label('order_count'),
        func.sum(Order.total_amount).label('revenue'),
    ).filter(~Order.status.in_(EXCLUDED_STATUSES)) \
     .group_by(Order.store_id) \
     .order_by(func.count(Order.id).desc()) \
     .limit(limit).all()

    store_ids = [r.store_id for r in rows]
    names = {}
    if store_ids:
        names = {str(s.id): s.name for s in Store.query.filter(Store.id.in_(store_ids)).all()}

    return [{
        'store': names.get(r.store_id, 'Unknown store'),
        'order_count': r.order_count,
        'revenue': float(r.revenue or 0),
    } for r in rows]


def top_items(store_id=None, limit=10):
    """Best-selling items by quantity, optionally scoped to one store."""
    order_ids = [str(oid) for (oid,) in _base_query(store_id).with_entities(Order.id).all()]
    if not order_ids:
        return []

    rows = db.session.query(
        OrderItem.name,
        func.sum(OrderItem.quantity).label('qty'),
        func.count(func.distinct(OrderItem.order_id)).label('order_count'),
    ).filter(OrderItem.order_id.in_(order_ids)) \
     .group_by(OrderItem.name) \
     .order_by(func.sum(OrderItem.quantity).desc()) \
     .limit(limit).all()

    return [{'name': r.name, 'quantity': int(r.qty or 0), 'orders': r.order_count} for r in rows]


def orders_by_hour(store_id=None):
    """Order count for each hour of the day (0-23), server local time."""
    rows = _base_query(store_id).with_entities(
        extract('hour', Order.created_at).label('hour'),
        func.count(Order.id).label('count'),
    ).group_by('hour').all()
    counts = {int(r.hour): r.count for r in rows if r.hour is not None}
    return [counts.get(h, 0) for h in range(24)]


def orders_by_weekday(store_id=None):
    """Order count for each weekday, Monday first. Postgres DOW is 0=Sunday..6=Saturday."""
    rows = _base_query(store_id).with_entities(
        extract('dow', Order.created_at).label('dow'),
        func.count(Order.id).label('count'),
    ).group_by('dow').all()
    counts = {int(r.dow): r.count for r in rows if r.dow is not None}
    dow_order = [1, 2, 3, 4, 5, 6, 0]  # Mon..Sun
    return [counts.get(d, 0) for d in dow_order]


def weekend_vs_weekday(store_id=None):
    values = orders_by_weekday(store_id)
    return {'weekday': sum(values[:5]), 'weekend': sum(values[5:])}


def holiday_vs_normal(store_id=None):
    rows = _base_query(store_id).with_entities(Order.created_at).all()
    holiday = sum(
        1 for (created_at,) in rows
        if created_at and (created_at.month, created_at.day) in GHANA_FIXED_HOLIDAYS
    )
    return {'holiday': holiday, 'normal': len(rows) - holiday}


def dashboard_charts(store_id=None):
    """Bundles every chart's data for a dashboard render call."""
    return {
        'top_items':         top_items(store_id),
        'orders_by_hour':    orders_by_hour(store_id),
        'orders_by_weekday': orders_by_weekday(store_id),
        'weekend_split':     weekend_vs_weekday(store_id),
        'holiday_split':     holiday_vs_normal(store_id),
    }
