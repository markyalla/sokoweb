from flask import Blueprint, render_template, g, redirect, url_for, flash, request
from app.routes.models import DriverProfile, User
from app import db

drivers_bp = Blueprint('drivers', __name__)


def _require_login():
    """Gate every route in this blueprint to sokodelivery_admin / superadmin."""
    if not g.user:
        return redirect(url_for('auth.login'))
    roles = [r.role for r in g.user.roles]
    if 'superadmin' not in roles and 'sokodelivery_admin' not in roles:
        flash('You do not have access to that section.', 'danger')
        return redirect(url_for('dashboard.index'))


SORTABLE_COLUMNS = {
    'rating':           DriverProfile.rating,
    'total_deliveries': DriverProfile.total_deliveries,
    'status':           DriverProfile.status,
    'is_online':        DriverProfile.is_online,
    'name':             User.full_name,
}


@drivers_bp.route('/')
def drivers_list():
    redir = _require_login()
    if redir:
        return redir

    sort = request.args.get('sort', 'rating')
    direction = request.args.get('dir', 'desc')
    sort_col = SORTABLE_COLUMNS.get(sort, DriverProfile.rating)
    order_by = sort_col.desc() if direction == 'desc' else sort_col.asc()

    rows = (
        db.session.query(DriverProfile, User)
        .join(User, DriverProfile.user_id == User.id)
        .order_by(order_by)
        .all()
    )
    drivers = [{'profile': dp, 'user': u} for dp, u in rows]

    return render_template(
        'superadmin/drivers.html',
        drivers=drivers, sort=sort, dir=direction,
    )
