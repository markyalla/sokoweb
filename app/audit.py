"""Shared audit log helper. Writes to the same audit_logs table (sokoaccount
database) that sokoApp's Go backend writes to directly via its
internal/audit package — see app/routes/models.py's AuditLog for the
SQLAlchemy side of that same shared schema, and keep both in sync if it
changes.

Writing here must never break the request it's describing: log_audit()
swallows its own errors (logged to the console only) instead of raising.
"""
import logging

from app import db
from app.routes.models import AuditLog

logger = logging.getLogger(__name__)

CATEGORY_ADMIN_ACTION = 'admin_action'
CATEGORY_PAYMENT_FAILURE = 'payment_failure'
CATEGORY_ORDER_STUCK = 'order_stuck'
CATEGORY_JOB_FAILURE = 'job_failure'
CATEGORY_API_ERROR = 'api_error'

SEVERITY_INFO = 'info'
SEVERITY_WARNING = 'warning'
SEVERITY_ERROR = 'error'
SEVERITY_CRITICAL = 'critical'

# Mirrors sokoApp's internal/middleware/audit.go adminRoles set — kept in
# sync so "what counts as an admin action" means the same thing on both
# sides of the shared audit_logs table.
ADMIN_ROLES = {
    'sokoshopper_admin', 'sokodelivery_admin', 'sokoloan_admin',
    'sokosusu_admin', 'sokobank_admin', 'superadmin',
}


def log_audit(category, severity, action, user=None, actor_label=None,
              entity_type=None, entity_id=None, message=None,
              old_value=None, new_value=None, metadata=None,
              request_path=None, status_code=None, ip_address=None,
              user_agent=None):
    """Best-effort audit write — never raises. A failure here is logged to
    the console and otherwise swallowed, since a broken audit write should
    never be the reason an admin action itself fails."""
    try:
        entry = AuditLog(
            category=category,
            severity=severity,
            user_id=user.id if user else None,
            actor_label=actor_label or (user.full_name if user else 'system'),
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            message=message,
            old_value=old_value,
            new_value=new_value,
            metadata_json=metadata,
            request_path=request_path,
            status_code=status_code,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        logger.exception("audit: failed to write log entry (category=%s action=%s)", category, action)
        db.session.rollback()
