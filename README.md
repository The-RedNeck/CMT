# CMT

The Requirement to get the server running
CMT Flask App 
alembic==1.16.2
blinker==1.9.0
charset-normalizer==3.4.2
click==8.2.1
colorama==0.4.6
coverage==7.9.2
dnspython==2.7.0
email-validator==2.2.0
et-xmlfile==2.0.0
flask==3.1.1
flask-login==0.6.3
flask-mail==0.10.0
flask-migrate==4.1.0
flask-sqlalchemy==3.1.1
flask-wtf==1.2.2
greenlet==3.2.3
idna==3.10
iniconfig==2.1.0
itsdangerous==2.2.0
jinja2==3.1.6
mako==1.3.10
markupsafe==3.0.2
numpy==2.3.1
openpyxl==3.1.5
packaging==25.0
pandas==2.3.0
pillow==11.3.0
pluggy==1.6.0
pygments==2.19.2
pytest==8.4.1
pytest-cov==6.2.1
pytest-flask==1.3.0
python-barcode==0.15.1
python-dateutil==2.9.0.post0
python-dotenv==1.1.1
pytz==2025.2
reportlab==4.4.2
six==1.17.0
sqlalchemy==2.0.41
typing-extensions==4.14.1
tzdata==2025.2
werkzeug==3.1.3
wtforms==3.2.1

# Production WSGI server
gunicorn==21.2.0; sys_platform != "win32"
waitress==2.1.2; sys_platform == "win32"

# Process management
supervisor==4.2.5

# Additional production dependencies
python-dotenv==1.0.0
