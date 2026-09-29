"""Server-side sessions stored in Redis.

Flask's default session cookie is signed but not encrypted: anyone holding it
can base64-decode the user id, CSRF token and the backend JWT kept in it.
Here the cookie carries only a random opaque id; the data lives in Redis and
expires after SESSION_IDLE_MINUTES of inactivity.

Enabled when REDIS_URL is set (production). Without it — local development —
Flask's default cookie session is used unchanged.
"""
import secrets
from datetime import timedelta

import redis
from flask.json.tag import TaggedJSONSerializer
from flask.sessions import SessionInterface, SessionMixin
from werkzeug.datastructures import CallbackDict

_KEY_PREFIX = 'sokoweb:session:'


class RedisSession(CallbackDict, SessionMixin):
    def __init__(self, initial=None, sid=None, new=False):
        def on_update(self):
            self.modified = True

        super().__init__(initial, on_update)
        self.sid = sid
        self.new = new
        self.modified = False
        self.rotate = False


class RedisSessionInterface(SessionInterface):
    serializer = TaggedJSONSerializer()

    def __init__(self, redis_url, idle_minutes):
        self.redis = redis.from_url(redis_url)
        self.ttl = timedelta(minutes=idle_minutes)

    def get_cookie_name(self, app):
        # __Host- makes the browser refuse the cookie unless it is Secure,
        # host-only and Path=/, so it can't be set by another subdomain or
        # sent over plain HTTP.
        return '__Host-sid' if self.get_cookie_secure(app) else 'sid'

    def open_session(self, app, request):
        sid = request.cookies.get(self.get_cookie_name(app))
        if sid:
            raw = self.redis.get(_KEY_PREFIX + sid)
            if raw is not None:
                return RedisSession(self.serializer.loads(raw.decode('utf-8')), sid=sid)
        # Unknown/expired id: start fresh under a new id (never reuse the
        # client-supplied one — that would allow session fixation).
        return RedisSession(sid=secrets.token_urlsafe(32), new=True)

    def save_session(self, app, session, response):
        name = self.get_cookie_name(app)
        secure = self.get_cookie_secure(app)
        httponly = self.get_cookie_httponly(app)
        samesite = self.get_cookie_samesite(app)

        if session.rotate and not session.new:
            self.redis.delete(_KEY_PREFIX + session.sid)
            session.sid = secrets.token_urlsafe(32)
            session.modified = True

        if not session:
            if session.modified and not session.new:
                self.redis.delete(_KEY_PREFIX + session.sid)
                response.delete_cookie(name, path='/', secure=secure, httponly=httponly, samesite=samesite)
            return

        # Every request slides the idle expiry forward, whether or not the
        # data changed.
        self.redis.setex(_KEY_PREFIX + session.sid, self.ttl, self.serializer.dumps(dict(session)))
        response.set_cookie(
            name, session.sid,
            max_age=int(self.ttl.total_seconds()),
            path='/', secure=secure, httponly=httponly, samesite=samesite,
        )


def regenerate_session(session):
    """Issue a new session id (call at login) so an id obtained before the
    user signed in stops working afterwards."""
    if isinstance(session, RedisSession):
        session.rotate = True


def init_sessions(app):
    url = app.config.get('REDIS_URL')
    if url:
        app.session_interface = RedisSessionInterface(url, app.config.get('SESSION_IDLE_MINUTES', 480))
