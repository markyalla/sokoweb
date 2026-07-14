from app import create_app
import os

app = create_app()

if __name__ == '__main__':
    app.run(debug=True, port=int(os.environ.get('ADMIN_PORT', 5000)))