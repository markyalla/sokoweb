"""Two front doors onto the same app, chosen by hostname:

- SUPERADMIN_HOST (e.g. admin.theagbeko.com) — superadmins only.
- PORTAL_HOST     (e.g. portal.theagbeko.com) — everyone else: the per-app
  sub-admins (sokoshopper_admin, sokodelivery_admin, …) and shop owners.

Enforced at login and on every request, so a session can't be carried from
one portal to the other (session cookies are host-only anyway). With either
variable unset — local development — nothing is enforced.
"""
from flask import current_app, request

ADMIN_PORTAL = 'admin'
PARTNER_PORTAL = 'partner'


def _hosts():
    cfg = current_app.config
    admin = (cfg.get('SUPERADMIN_HOST') or '').strip().lower()
    partner = (cfg.get('PORTAL_HOST') or '').strip().lower()
    return admin, partner


def current_portal():
    """'admin', 'partner', or None when separation isn't configured / the
    request came in on some other hostname."""
    admin, partner = _hosts()
    if not admin or not partner:
        return None
    host = request.host.split(':')[0].lower()
    if host == admin:
        return ADMIN_PORTAL
    if host == partner:
        return PARTNER_PORTAL
    return None


def portal_url(portal):
    admin, partner = _hosts()
    host = admin if portal == ADMIN_PORTAL else partner
    return f"https://{host}/auth/login" if host else None


def portal_mismatch(user):
    """If `user` is on the wrong portal, return the message to show them;
    otherwise None."""
    portal = current_portal()
    if portal is None or user is None:
        return None
    is_super = any(r.role == 'superadmin' for r in user.roles)
    if portal == ADMIN_PORTAL and not is_super:
        return (f"This address is for the platform administrator only. "
                f"Please sign in at {portal_url(PARTNER_PORTAL)}")
    if portal == PARTNER_PORTAL and is_super:
        return (f"Superadmin accounts sign in at {portal_url(ADMIN_PORTAL)}")
    return None
