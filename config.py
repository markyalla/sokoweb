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

    SQLALCHEMY_DATABASE_URI = get_uri('sokoaccount')
    SQLALCHEMY_BINDS = {
        'account':   get_uri('sokoaccount'),
        'shopper':   get_uri('sokoshopper'),
        'delivery':  get_uri('sokodelivery'),
        'loan':      get_uri('sokoloan'),
        'susu':      get_uri('sokosusu'),
        'bank':      get_uri('sokobank'),
        'sokoindex': get_uri('sokoindex'),
    }