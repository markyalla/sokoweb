from flask import Flask, session, g
from flask_sqlalchemy import SQLAlchemy
import jwt
from datetime import datetime, timedelta, timezone
from config import Config

db = SQLAlchemy()

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

    db.init_app(app)

    @app.before_request
    def load_logged_in_user():
        from app.routes.models import User
        user_id = session.get('user_id')
        if user_id is None:
            g.user = None
        else:
            g.user = db.session.get(User, user_id)

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

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(shopper_bp, url_prefix='/shopper')
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(account_bp, url_prefix='/account')
    app.register_blueprint(delivery_bp, url_prefix='/delivery')
    app.register_blueprint(susu_bp, url_prefix='/susu')
    app.register_blueprint(finance_bp, url_prefix='/finance')
    app.register_blueprint(store_owner_bp, url_prefix='/store')
    app.register_blueprint(sokoindex_bp, url_prefix='/sokoindex')

    # Create any missing tables (e.g. shop_cashout_requests, driver_cashout_requests)
    # that Go's GORM AutoMigrate would normally create on next restart.
    # SQLAlchemy create_all() is safe — it skips tables that already exist.
    with app.app_context():
        db.create_all()

    return app