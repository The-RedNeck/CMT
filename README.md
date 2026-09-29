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

4. **Set up environment variables**
   Create a `.env` file in the root directory:
   ```env
   FLASK_APP=app
   FLASK_ENV=development
   SECRET_KEY=your-secret-key-here
   DATABASE_URL=sqlite:///cmt.db
   ```

5. **Initialize the database**
   ```bash
   flask db upgrade
   ```

6. **Run the application**
   ```bash
   flask run
   ```

   The application will be available at `http://localhost:5000`

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
├── __init__.py              # Package initialization with model imports
├── administration.py        # User management routes
├── asset.py                 # Asset model definition
├── asset_management.py      # Core asset management routes
├── asset_type.py            # Asset type model
├── auth.py                  # Authentication routes
├── available_tag_number.py  # Tag number pool model
├── department.py            # Department model
├── employee.py              # Employee model
├── labels.py                # Label printing utilities
├── list_forms.py            # CRUD forms for entities
├── location.py              # Location model
├── maintenance.py           # Maintenance record model
├── manufacturer.py          # Manufacturer model
├── new.py                   # New entity creation routes
├── reports.py               # Reporting and analytics routes
├── search.py                # Search API endpoints
├── tag_number.py            # Tag number generation
├── user.py                  # User authentication model
├── README.md                # This file
├── BUGS.md                  # Known issues and bug analysis
└── .gitignore               # Git ignore rules
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
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
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

Report vulnerabilities by email to kodgey1@gmail.com. See [SECURITY.md](SECURITY.md). Do not open a public issue for a security problem.

- CSRF protection enabled on all forms
- Password hashing using Werkzeug security
- Progressive account lockout for failed logins
- IP address logging for audit trails
- Session management with configurable timeouts

## License

This project is proprietary software. All rights reserved.

## Support

For issues or questions, please open a GitHub issue or contact the development team.
