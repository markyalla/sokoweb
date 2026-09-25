from app import create_app
import os

app = create_app()

if __name__ == '__main__':
    # Debug mode exposes an interactive console — opt in locally with FLASK_DEBUG=1 only.
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1', port=int(os.environ.get('ADMIN_PORT', 5000)))