import os

# The local demo is plain HTTP. Importing this module for Gunicorn does not set the flag,
# so production cookies stay Secure and HTTP is redirected.
if __name__ == '__main__':
    os.environ['CMT_DEV_HTTP'] = '1'

from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
