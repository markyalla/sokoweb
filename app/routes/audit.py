from datetime import datetime, timedelta

from flask import Blueprint, render_template, g, redirect, url_for, flash, request

from app import db
from app.routes.models import AuditLog, User

audit_bp = Blueprint('audit', __name__)

PAGE_SIZE = 50
CATEGORIES = ['admin_action', 'payment_failure', 'order_stuck', 'job_failure', 'api_error']
SEVERITIES = ['critical', 'error', 'warning', 'info']


def _require_superadmin():
    if not g.user:
        return redirect(url_for('auth.login'))
    if 'superadmin' not in [r.role for r in g.user.roles]:
        flash('You do not have access to that section.', 'danger')
        return redirect(url_for('dashboard.index'))
    return None


@audit_bp.route('/')
def index():
    """Superadmin-only. Everything sokoApp (Go) and SokoWeb (Flask) write to
    the shared audit_logs table — admin actions from both services, plus
    system-detected problems: failed/stuck payments, orders stuck in
    payment_pending, background job failures, and 5xx/panic API errors."""
    redir = _require_superadmin()
    if redir:
        return redir

    category = request.args.get('category', '').strip()
    severity = request.args.get('severity', '').strip()
    search = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)

    query = AuditLog.query
    if category in CATEGORIES:
        query = query.filter(AuditLog.category == category)
    if severity in SEVERITIES:
        query = query.filter(AuditLog.severity == severity)
    if search:
        like = f"%{search}%"
        query = query.filter(db.or_(
            AuditLog.action.ilike(like),
            AuditLog.message.ilike(like),
            AuditLog.actor_label.ilike(like),
            AuditLog.request_path.ilike(like),
        ))

    pagination = query.order_by(AuditLog.created_at.desc()).paginate(
        page=page, per_page=PAGE_SIZE, error_out=False)
    logs = pagination.items

    # sokoApp's generic middleware only has a user's ID (from the JWT), not
    # their name, so its admin_action rows store the raw user ID as
    # actor_label. Resolve names here in bulk for a friendlier display —
    # falls back to the stored actor_label (raw ID, or "system") if the user
    # was deleted or the row genuinely has no user (system-detected events).
    user_ids = {log.user_id for log in logs if log.user_id}
    names_by_id = {}
    if user_ids:
        for u in User.query.filter(User.id.in_(user_ids)).all():
            names_by_id[u.id] = u.full_name

    since_24h = datetime.utcnow() - timedelta(hours=24)
    counts = {
        sev: AuditLog.query.filter(AuditLog.severity == sev, AuditLog.created_at >= since_24h).count()
        for sev in SEVERITIES
    }

    return render_template(
        'superadmin/audit_log.html',
        logs=logs, pagination=pagination, names_by_id=names_by_id,
        category=category, severity=severity, search=search,
        counts=counts, categories=CATEGORIES, severities=SEVERITIES,
    )


@audit_bp.route('/api/critical-count')
def api_critical_count():
    """Lightweight JSON polled from base.html to badge the sidebar Audit Log
    link with a count of unread-feeling critical/error events in the last
    hour — same polling pattern already used for new-order/new-delivery
    toasts (no websocket/push channel in this app)."""
    if not g.user or 'superadmin' not in [r.role for r in g.user.roles]:
        return {'count': 0}, 200

    since = datetime.utcnow() - timedelta(hours=1)
    count = AuditLog.query.filter(
        AuditLog.severity.in_(['critical', 'error']),
        AuditLog.created_at >= since,
    ).count()
    return {'count': count}, 200
