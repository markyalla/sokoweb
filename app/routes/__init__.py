from flask import session, g # type: ignore
import os

def get_full_url(path):
    from flask import current_app # type: ignore
    if not path:
        return ""
    media_endpoint = "/api/v1/media/serve/"
    if media_endpoint in path:
        path = path.split(media_endpoint)[-1]
    elif path.startswith('http'):
        return path
    base = current_app.config.get('API_BASE_URL', 'http://localhost:8082').rstrip('/')
    return f"{base}{media_endpoint}{path.lstrip('/')}"

def get_relative_path(url):
    if not url:
        return ""
    if not url.startswith('http'):
        return url
    media_endpoint = "/api/v1/media/serve/"
    if media_endpoint in url:
        return url.split(media_endpoint)[-1]
    return url

    # Register Blueprints
    from app.routes.dashboard import dashboard_bp
    from app.routes.shopper   import shopper_bp
    from app.routes.auth      import auth_bp
    from app.routes.account   import account_bp
    from app.routes.delivery  import delivery_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(shopper_bp,  url_prefix='/shopper')
    app.register_blueprint(auth_bp,     url_prefix='/auth')
    app.register_blueprint(account_bp,  url_prefix='/account')
    app.register_blueprint(delivery_bp, url_prefix='/delivery')

    return app