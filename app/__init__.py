from flask import Flask, session, g, request, got_request_exception, flash, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import jwt
from datetime import datetime, timedelta, timezone
from config import Config
import os

db = SQLAlchemy()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)

def get_full_url(path):
    from flask import current_app
    if not path:
        return ""
    media_endpoint = "/api/v1/media/serve/"
    if media_endpoint in path:
        path = path.split(media_endpoint)[-1]
    elif path.startswith('http'):
        return path
    base = current_app.config.get('API_BASE_URL', 'http://192.168.2.195:8082').rstrip('/')
    return f"{base}{media_endpoint}{path.lstrip('/')}"

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # The fallback secret in config.py is public (it's in the repo). Using it
    # in production would let anyone forge sessions and backend JWTs.
    if os.environ.get('FLASK_ENV') == 'production' and app.config['SECRET_KEY'] == 'dev-secret-key-123':
        raise RuntimeError('JWT_SECRET must be set to a strong secret in production')

    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    @app.before_request
    def load_logged_in_user():
        from app.routes.models import User
        user_id = session.get('user_id')
        if user_id is None:
            g.user = None
        else:
            g.user = db.session.get(User, user_id)
            # Deactivated or deleted accounts lose their existing session too.
            if g.user and (g.user.is_active is False or getattr(g.user, 'is_deleted', False)):
                session.clear()
                g.user = None

    # Captures the actual exception object for unhandled errors (Flask's
    # own signal, fired before the 500 response is finalized) so the audit
    # entry logged below can include a real message instead of just "500".
    @got_request_exception.connect_via(app)
    def _capture_exception_for_audit(sender, exception, **extra):
        g.audit_exception = exception

    _ADMIN_MUTATING_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}

    @app.after_request
    def audit_requests(response):
        """Generic activity log for two overlapping concerns that would
        otherwise be invisible: every mutating request made by a staff/admin
        user (a "who did what" trail covering every current and future admin
        route without instrumenting each one individually), and every 5xx
        response (an API-error feed). A mutating admin request that also
        fails is logged once, as an admin_action at error/critical severity,
        not twice. Mirrors sokoApp's internal/middleware/audit.go Gin
        middleware — see there for the Go-side equivalent."""
        from app.audit import (
            log_audit, CATEGORY_ADMIN_ACTION, CATEGORY_API_ERROR,
            SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_ERROR, SEVERITY_CRITICAL,
            ADMIN_ROLES,
        )

        user = getattr(g, 'user', None)
        roles = [r.role for r in user.roles] if user else []
        is_admin = any(r in ADMIN_ROLES for r in roles)

        should_log_admin_action = is_admin and request.method in _ADMIN_MUTATING_METHODS
        should_log_api_error = response.status_code >= 500
        if not should_log_admin_action and not should_log_api_error:
            return response

        exc = getattr(g, 'audit_exception', None)
        if exc is not None:
            severity = SEVERITY_CRITICAL
        elif response.status_code >= 500:
            severity = SEVERITY_ERROR
        elif response.status_code >= 400:
            severity = SEVERITY_WARNING
        else:
            severity = SEVERITY_INFO

        log_audit(
            category=CATEGORY_ADMIN_ACTION if should_log_admin_action else CATEGORY_API_ERROR,
            severity=severity,
            action=f"{request.method} {request.endpoint or request.path}",
            user=user,
            message=f"{type(exc).__name__}: {exc}" if exc else None,
            request_path=request.path,
            status_code=response.status_code,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
        )
        return response

    @app.errorhandler(429)
    def rate_limited(e):
        """Flask-Limiter otherwise returns Werkzeug's bare "Too Many Requests"
        page. Limits are POST-only, so bounce back to the same page via GET
        with a flash message instead."""
        message = f"Too many attempts ({e.description}). Please wait a minute and try again."
        if request.method == 'GET' or request.is_json or request.accept_mimetypes.best == 'application/json':
            return {'error': message}, 429
        flash(message, 'warning')
        return redirect(request.full_path.rstrip('?'))

    @app.after_request
    def security_headers(response):
        # Clickjacking, MIME sniffing and referrer leakage protection for the
        # admin panel. HSTS is left to Caddy, which terminates TLS.
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        return response

    # Register resolve_media as a global template function
    app.add_template_global(get_full_url, 'resolve_media')

    @app.context_processor
    def inject_globals():
        backend_jwt = None
        user = g.user
        if user:
            # Generate a JWT compatible with the Go backend's expectations
            payload = {
                "sub": str(user.id),
                "roles": [r.role for r in user.roles] or ["user"],
                "exp": datetime.now(timezone.utc) + timedelta(hours=2)
            }
            backend_jwt = jwt.encode(payload, app.config['SECRET_KEY'], algorithm="HS256")

        return {
            'current_user': user if user else type('AnonymousUser', (), {'is_authenticated': False})(),
            'backend_jwt': backend_jwt,
            'BACKEND_JWT': backend_jwt,
            'BACKEND_TOKEN': session.get('backend_token', ''),
            'API_BASE_URL': app.config.get('API_BASE_URL', 'http://192.168.2.195:8082').rstrip('/')
        }

    # Register Blueprints
    from app.routes.dashboard import dashboard_bp
    from app.routes.shopper import shopper_bp
    from app.routes.auth import auth_bp
    from app.routes.account import account_bp
    from app.routes.delivery import delivery_bp
    from app.routes.susu import susu_bp
    from app.routes.finance import finance_bp
    from app.routes.store_owner import store_owner_bp
    from app.routes.sokoindex import sokoindex_bp
    from app.routes.drivers import drivers_bp
    from app.routes.pricing import pricing_bp
    from app.routes.audit import audit_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(shopper_bp, url_prefix='/shopper')
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(account_bp, url_prefix='/account')
    app.register_blueprint(delivery_bp, url_prefix='/delivery')
    app.register_blueprint(susu_bp, url_prefix='/susu')
    app.register_blueprint(finance_bp, url_prefix='/finance')
    app.register_blueprint(store_owner_bp, url_prefix='/store')
    app.register_blueprint(sokoindex_bp, url_prefix='/sokoindex')
    app.register_blueprint(drivers_bp, url_prefix='/drivers')
    app.register_blueprint(pricing_bp, url_prefix='/pricing')
    app.register_blueprint(audit_bp, url_prefix='/audit')

    # Create any missing tables (e.g. shop_cashout_requests, driver_cashout_requests)
    # that Go's GORM AutoMigrate would normally create on next restart.
    # SQLAlchemy create_all() is safe — it skips tables that already exist.
    with app.app_context():
        db.create_all()

    return app