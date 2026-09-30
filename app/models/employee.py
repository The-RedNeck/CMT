from datetime import datetime, timezone

from flask_login import UserMixin

from app import db
from app.passwords import hash_secret, needs_rehash, upgrade_stored_hash, verify_secret


def _utcnow():
    """Naive UTC so comparisons stay compatible with existing rows."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

class Employee(UserMixin, db.Model):
    __tablename__ = 'employee'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(50), unique=True, nullable=False)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.Text)
    first_name = db.Column(db.String(64))
    last_name = db.Column(db.String(64))
    title = db.Column(db.String(100))
    department_id = db.Column(db.Integer, db.ForeignKey('department.id'))
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'))
    phone = db.Column(db.String(20))
    mobile = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)
    hire_date = db.Column(db.Date)
    termination_date = db.Column(db.Date)
    
    # Audit fields
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    last_login = db.Column(db.DateTime)
    
    # Relationships
    location = db.relationship('Location', backref='employees')
    
    def __repr__(self):
        return f'<Employee {self.employee_id}: {self.username}>'
    
    def set_password(self, password):
        self.password_hash = hash_secret(password)

    def check_password(self, password):
        if not verify_secret(self.password_hash, password):
            return False
        if needs_rehash(self.password_hash):
            upgrade_stored_hash(self, password)
        return True
    
    def to_dict(self):
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'username': self.username,
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'title': self.title,
            'department': self.department.name if self.department else None,
            'location': self.location.name if self.location else None,
            'phone': self.phone,
            'mobile': self.mobile,
            'is_active': self.is_active,
            'is_admin': self.is_admin,
            'hire_date': self.hire_date.isoformat() if self.hire_date else None,
            'termination_date': self.termination_date.isoformat() if self.termination_date else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'last_login': self.last_login.isoformat() if self.last_login else None
        }
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def is_terminated(self):
        return self.termination_date is not None
    
    def has_assets(self):
        """Return True if the employee has any checked out assets."""
        return len(self.checked_out_assets) > 0

class EmployeeHistory(db.Model):
    __tablename__ = 'employee_history'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, nullable=False)
    username = db.Column(db.String(64))
    email = db.Column(db.String(120))
    first_name = db.Column(db.String(64))
    last_name = db.Column(db.String(64))
    title = db.Column(db.String(100))
    department_id = db.Column(db.Integer)
    location_id = db.Column(db.Integer)
    phone = db.Column(db.String(20))
    mobile = db.Column(db.String(20))
    is_active = db.Column(db.Boolean)
    is_admin = db.Column(db.Boolean)
    hire_date = db.Column(db.Date)
    termination_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime)
    last_login = db.Column(db.DateTime)
    action = db.Column(db.String(20))  # created, updated, deleted
    changed_by = db.Column(db.String(64))  # username or user id
    changed_at = db.Column(db.DateTime, default=_utcnow)
    ip_address = db.Column(db.String(45))  # client IP address

    def __repr__(self):
        return f'<EmployeeHistory {self.employee_id} {self.action} at {self.changed_at}>' 