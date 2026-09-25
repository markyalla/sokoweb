import os
from pathlib import Path
from urllib.parse import quote_plus
from dotenv import load_dotenv

# Explicit path — works regardless of where Flask is launched from
load_dotenv(Path(__file__).resolve().parent / '.env')

DB_USER = os.environ.get('DB_USER', 'user')
DB_PASS = os.environ.get('DB_PASSWORD', 'password')
DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_PORT = os.environ.get('DB_PORT', '5432')

def get_uri(db_name):
    # Credentials must be percent-encoded before going into a URI — an
    # unescaped special character (e.g. '@' or ':') in the password would
    # otherwise be misread as part of the host, breaking the connection.
    user = quote_plus(DB_USER)
    password = quote_plus(DB_PASS)
    return f"postgresql://{user}:{password}@{DB_HOST}:{DB_PORT}/{db_name}"

class Config:
    SECRET_KEY = os.environ.get('JWT_SECRET', 'dev-secret-key-123')
    JWT_SECRET = os.environ.get('JWT_SECRET', 'dev-secret-key-123')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    API_BASE_URL = os.environ.get('API_BASE_URL', 'http://192.168.2.195:8082')

    # Flask-Limiter's default storage is in-process memory, counted separately
    # per Gunicorn worker — with -w 2, a "10 per minute" limit becomes ~20 per
    # minute in practice. REDIS_URL points it at the same Redis instance the
    # Go backend already runs (docker-compose exposes it on 127.0.0.1:6379),
    # using a separate logical DB (/1) to keep its keys apart from Asynq's.
    # Falls back to memory:// for local dev where Redis may not be running.
    REDIS_URL = os.environ.get('REDIS_URL')
    RATELIMIT_STORAGE_URI = REDIS_URL or 'memory://'

    # Session cookie hardening — defense-in-depth alongside CSRFProtect.
    # SECURE is env-driven so local HTTP dev still works; set FLASK_ENV=production
    # (or COOKIE_SECURE=true) once served over HTTPS.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.environ.get('FLASK_ENV') == 'production' or os.environ.get('COOKIE_SECURE', '').lower() == 'true'

    # Match the Go API's DSN (TimeZone=UTC) so timestamptz columns come back
    # in UTC and naive utcnow() comparisons are interpreted as UTC too.
    SQLALCHEMY_ENGINE_OPTIONS = {'connect_args': {'options': '-c timezone=UTC'}}

    SQLALCHEMY_DATABASE_URI = get_uri('sokoaccount')
    SQLALCHEMY_BINDS = {
        'account':   get_uri('sokoaccount'),
        'shopper':   get_uri('sokoshopper'),
        'delivery':  get_uri('sokodelivery'),
        'loan':      get_uri('sokoloan'),
        'susu':      get_uri('sokosusu'),
        'sokoindex': get_uri('sokoindex'),
    }