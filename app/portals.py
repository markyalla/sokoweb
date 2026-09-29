"""Three front doors onto the same app, chosen by hostname:

- SUPERADMIN_HOST (admin.theagbeko.com)    — superadmins only.
- PORTAL_HOST     (portal.theagbeko.com)   — per-app sub-admins
  (sokoshopper_admin, sokodelivery_admin, …).
- MERCHANT_HOST   (merchant.theagbeko.com) — shop owners.

Enforced at login and on every request, so a session can't be carried from
one portal to another (session cookies are host-only anyway). Someone who is
both a sub-admin and a shop owner may use either of those two portals. With
any of the variables unset — local development — nothing is enforced.
"""
from flask import current_app, request

ADMIN_PORTAL = 'admin'
PARTNER_PORTAL = 'partner'
MERCHANT_PORTAL = 'merchant'

_CONFIG_KEYS = {
    ADMIN_PORTAL: 'SUPERADMIN_HOST',
    PARTNER_PORTAL: 'PORTAL_HOST',
    MERCHANT_PORTAL: 'MERCHANT_HOST',
}

_LABELS = {
    ADMIN_PORTAL: 'the platform administrator',
    PARTNER_PORTAL: 'app administrators',
    MERCHANT_PORTAL: 'shop owners',
}

# Pages each portal may serve (blueprint names). The admin portal serves
# everything; per-page role checks still apply inside each blueprint.
_ALWAYS = {'auth', 'static'}
_MERCHANT_ONLY = {'store_owner'}


def _hosts():
    cfg = current_app.config
    return {p: (cfg.get(k) or '').strip().lower() for p, k in _CONFIG_KEYS.items()}


def current_portal():
    """'admin', 'partner', 'merchant', or None when separation isn't
    configured or the request came in on some other hostname."""
    hosts = _hosts()
    if not all(hosts.values()):
        return None
    host = request.host.split(':')[0].lower()
    for portal, h in hosts.items():
        if host == h:
            return portal
    return None


def portal_url(portal):
    host = _hosts().get(portal)
    return f"https://{host}/auth/login" if host else None


def allowed_portals(user):
    from app.audit import ADMIN_ROLES
    from app.routes.models import Store

    roles = {r.role for r in user.roles}
    if 'superadmin' in roles:
        return [ADMIN_PORTAL]
    allowed = []
    if roles & (ADMIN_ROLES - {'superadmin'}):
        allowed.append(PARTNER_PORTAL)
    if Store.query.filter_by(owner_user_id=str(user.id)).first():
        allowed.append(MERCHANT_PORTAL)
    return allowed


def portal_mismatch(user):
    """If `user` is on a portal that isn't theirs, return the message to show
    them; otherwise None. Users with no web access at all (plain app users)
    return None here and are turned away by the login view as before."""
    portal = current_portal()
    if portal is None or user is None:
        return None
    allowed = allowed_portals(user)
    if not allowed or portal in allowed:
        return None
    where = ' or '.join(portal_url(p) for p in allowed)
    return f"This address is for {_LABELS[portal]} only. Please sign in at {where}"


def page_not_on_portal(blueprint):
    """True when the requested page doesn't belong on this portal: the
    merchant portal only serves shop-owner pages, and the partner portal
    doesn't serve them."""
    portal = current_portal()
    if portal is None or blueprint in _ALWAYS:
        return False
    if portal == MERCHANT_PORTAL:
        return blueprint not in _MERCHANT_ONLY
    if portal == PARTNER_PORTAL:
        return blueprint in _MERCHANT_ONLY
    return False


def home_endpoint():
    """Where a signed-in user lands on this portal."""
    return 'store_owner.select_store' if current_portal() == MERCHANT_PORTAL else 'dashboard.index'
