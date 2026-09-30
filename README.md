# CMT - Configuration Management Tool

A comprehensive Flask-based web application for enterprise asset and configuration management. CMT provides complete lifecycle management for IT assets including tracking, assignment, maintenance, and reporting.

## Features

### Asset Management
- **Asset Tracking**: Track assets with unique tag numbers, serial numbers, and barcodes
- **Status Management**: Track asset status (Available, Checked Out, In Maintenance, Disposed)
- **Bulk Operations**: Bulk checkout and check-in of multiple assets
- **Asset History**: Complete audit trail of all asset changes
- **Receipt Generation**: Automatic PDF receipt generation for checkouts/check-ins

### Employee Management
- **Employee Directory**: Manage employee records with contact information
- **Department Assignment**: Organize employees by department and location
- **Asset Assignment**: Track which assets are assigned to each employee
- **Employment History**: Track hire dates, terminations, and employee changes

### Maintenance Tracking
- **Maintenance Records**: Log preventive, corrective, and predictive maintenance
- **Cost Tracking**: Track maintenance costs per asset
- **Priority Management**: Categorize maintenance by priority level
- **Follow-up Tracking**: Flag items requiring follow-up

### Reporting & Analytics
- **Dashboard**: Visual overview of asset status and statistics
- **Asset Reports**: Generate reports by location, department, type, and status
- **Maintenance Reports**: Track maintenance costs and frequency
- **Value Analysis**: Asset value tracking by various dimensions
- **Export**: Export reports to Excel format

### Administration
- **User Management**: Create and manage user accounts
- **Role-Based Access**: Super admin and regular user roles
- **Progressive Lockout**: Security protection against brute force attacks
- **Admin two-factor authentication**: Super admin sign-in requires an authenticator app after the password
- **Audit Trail**: Track all system changes with IP logging

## Tech Stack

- **Backend**: Python 3.x, Flask 3.1.1
- **Database**: SQLAlchemy ORM (supports SQLite, PostgreSQL, MySQL)
- **Authentication**: Flask-Login with session management
- **Forms**: Flask-WTF with CSRF protection
- **PDF Generation**: ReportLab
- **Excel Export**: OpenPyXL, Pandas
- **Barcode Generation**: python-barcode

## Installation

### Prerequisites
- Python 3.8 or higher
- pip (Python package manager)

### Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/The-RedNeck/CMT.git
   cd CMT
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the application**
   ```bash
   python run.py
   ```

   Tables are created on startup. A local demo account is added when the database is empty: `admin` / `admin123`.

   The application will be available at `http://localhost:5000`

   Optional environment variables: `SECRET_KEY`, `DATABASE_URL`.

   Super admin accounts set up an authenticator app the first time they sign in. Later sign-ins ask for that 6-digit code or a one-time recovery code. Other accounts still sign in with a password only.

   Passwords are stored with scrypt (`N=131072`, `r=8`, `p=1`, about 128 MiB per hash). A successful sign-in rewrites an older hash with those parameters. Recovery codes are 80 random bits, hashed the same way, and each code works once. New passwords must be at least 12 characters. The local demo account is unchanged so you can still sign in and look around.

   Set `SECRET_KEY` to a long random value before anyone else can reach the app. Set `CMT_DISABLE_DEMO_SEED=1` so a new database does not create `admin` / `admin123`.

   Sessions last 2 hours. Cookies are HttpOnly, SameSite=Lax, and Secure. `python run.py` turns Secure off so the local demo can use `http://localhost:5000`. A production process does not, and it redirects HTTP to HTTPS. Put a free Let's Encrypt certificate in front of Gunicorn (Certbot with nginx or Caddy). If a proxy terminates TLS, set `TRUST_PROXY=1` so the app sees the original client and the HTTPS scheme.

   Changing or deleting a user asks for the admin password again. That confirmation lasts 10 minutes. Sign-ins, failures, lockouts, and recovery-code use are listed under Users → Audit log. The log does not store passwords or codes.

   Back up the database with encryption. Set `AGE_RECIPIENT` to an age public key, or `GPG_RECIPIENT` to a GPG key id:

   ```bash
   python scripts/backup_db.py
   ```

   On Postgres, give the app its own login role and do not use the owner role for the web process. The app role needs `CONNECT` on the database, `USAGE` on the schema, and `SELECT`, `INSERT`, `UPDATE`, and `DELETE` on the tables. Run migrations as the owner, not as that role.

### MITRE ATT&CK

Super admins can open **ATT&CK** and refresh Enterprise ATT&CK from MITRE's TAXII 2.1 API (`https://attack-taxii.mitre.org/api/v21/`). That download is the same data shown on https://attack.mitre.org/. The page lists techniques that apply to this application, marks each one in place, partial, or still open, and keeps the rest of the Enterprise matrix so a later refresh shows MITRE's updates.

That page is a coverage check. It does not make CMT fully secure. Open items stay open until the control behind them changes.

### Subscriptions

Each account gets a 90-day trial stored as `trial_ends_at`. No card is required during the trial. When it ends, the app sends the user to Stripe Checkout. Access follows the Stripe webhook, not the browser return from Checkout.

```
STRIPE_SECRET_KEY
STRIPE_PRICE_ID
STRIPE_WEBHOOK_SECRET
STRIPE_PRICE_LABEL
```

`STRIPE_PRICE_LABEL` is optional text shown on the pricing page, such as `$49/month`. Create the price in the Stripe Dashboard, start in test mode, and subscribe the webhook endpoint `/stripe/webhook` to `customer.subscription.created`, `customer.subscription.updated`, and `customer.subscription.deleted`.

```bash
stripe listen --forward-to localhost:5000/stripe/webhook
```

Existing accounts with no trial date are given 90 days the next time the app starts.

### Production Deployment

For production, use a WSGI server:

**Linux/macOS (Gunicorn):**
```bash
gunicorn -w 4 -b 0.0.0.0:8000 "app:create_app()"
```

**Windows (Waitress):**
```bash
waitress-serve --port=8000 app:create_app
```

## Project Structure

```
CMT/
├── run.py                   # Development entry point
├── app/
│   ├── __init__.py          # Application factory
│   ├── auth.py              # Authentication routes
│   ├── billing.py           # Trial, Stripe Checkout, and webhooks
│   ├── asset_management.py  # Core asset management routes
│   ├── administration.py    # User management routes
│   ├── list_forms.py        # CRUD forms for entities
│   ├── reports.py           # Reporting and analytics routes
│   ├── search.py            # Search API endpoints
│   ├── tag_number.py        # Tag number generation
│   ├── models/              # SQLAlchemy models
│   ├── utils/               # History, export, receipts, input checks
│   └── templates/           # HTML pages
├── tests/                   # pytest suite
├── README.md
├── BUGS.md
└── requirements.txt
```

## API Endpoints

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/auth/login` | User login |
| GET | `/auth/logout` | User logout |
| GET | `/auth/refresh-csrf` | Refresh CSRF token |

### Asset Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/asset-management/` | Asset management dashboard |
| GET | `/asset-management/list` | List all assets |
| GET | `/asset-management/api/filtered-assets` | Get filtered assets (JSON) |
| GET/POST | `/asset-management/new` | Create new asset |
| GET/POST | `/asset-management/<id>/edit` | Edit asset |
| POST | `/asset-management/checkout/<id>` | Check out asset |
| POST | `/asset-management/checkin/<id>` | Check in asset |
| POST | `/asset-management/maintenance/<id>` | Send to maintenance |
| POST | `/asset-management/dispose/<id>` | Dispose asset |
| GET | `/asset-management/bulk-assign` | Bulk asset assignment |
| GET | `/asset-management/bulk-checkin` | Bulk check-in |
| GET | `/asset-management/export` | Export assets to Excel |

### Employees
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/list-forms/employees` | List employees |
| GET/POST | `/list-forms/employees/new` | Create employee |
| GET/POST | `/list-forms/employees/edit/<id>` | Edit employee |
| POST | `/list-forms/employees/<id>/delete` | Delete employee |
| GET | `/list-forms/employees/export` | Export to Excel |

### Reports
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/reports/` | Reports dashboard |
| GET | `/reports/api/asset-status` | Asset status summary |
| GET | `/reports/api/maintenance-costs` | Maintenance cost analysis |
| GET | `/reports/api/department-assets` | Assets by department |
| GET | `/reports/api/assets-by-location` | Assets grouped by location |

### Administration
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/administration/users` | User management |
| GET/POST | `/administration/users/create` | Create user |
| GET/POST | `/administration/users/<id>/edit` | Edit user |
| POST | `/administration/users/<id>/delete` | Delete user |
| GET | `/administration/connections` | View connection history |

## Configuration

Key configuration options in your Flask app config:

```python
# Security
SECRET_KEY = 'your-secret-key'
WTF_CSRF_ENABLED = True
PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

# Login Security
MAX_LOGIN_ATTEMPTS_BEFORE_PROGRESSIVE_LOCKOUT = 20
LOGIN_ATTEMPT_LOCKOUT_THRESHOLDS = [1, 2, 3, 4, 5]
LOGIN_ATTEMPT_LOCKOUT_DURATIONS = [
    timedelta(minutes=2),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=24)
]

# Database
SQLALCHEMY_DATABASE_URI = 'sqlite:///cmt.db'
SQLALCHEMY_TRACK_MODIFICATIONS = False
```

## Dependencies

### Core Framework
- Flask 3.1.1
- Flask-Login 0.6.3
- Flask-SQLAlchemy 3.1.1
- Flask-WTF 1.2.2
- Flask-Migrate 4.1.0
- Flask-Mail 0.10.0

### Database
- SQLAlchemy 2.0.41
- Alembic 1.16.2

### Data Processing
- Pandas 2.3.0
- NumPy 2.3.1
- OpenPyXL 3.1.5

### PDF & Barcode
- ReportLab 4.4.2
- Pillow 11.3.0
- python-barcode 0.15.1

### Production
- Gunicorn 21.2.0 (Linux/macOS)
- Waitress 2.1.2 (Windows)
- Supervisor 4.2.5 (Process management)

### Testing
- pytest 8.4.1
- pytest-flask 1.3.0
- pytest-cov 6.2.1

## Testing

Run the test suite:
```bash
pytest
pytest tests/test_assets.py
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Known Issues

See [BUGS.md](BUGS.md) for a comprehensive list of known issues and their status.

## Security

- CSRF protection enabled on all forms
- Password hashing using Werkzeug security
- Progressive account lockout for failed logins
- IP address logging for audit trails
- Session management with configurable timeouts

## License

This project is proprietary software. All rights reserved.

## Support

For issues or questions, please open a GitHub issue or contact the development team.
