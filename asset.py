from datetime import datetime, timezone

from app import db


def _utcnow():
    """Naive UTC so comparisons stay compatible with existing rows."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

class Asset(db.Model):
    __tablename__ = 'assets'
    # Prevent SQLite from reusing IDs of deleted rows
    __table_args__ = {'sqlite_autoincrement': True}
    id = db.Column(db.Integer, primary_key=True)
    tag_number = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    serial_number = db.Column(db.String(100))
    model_number = db.Column(db.String(100))
    purchase_date = db.Column(db.Date)
    purchase_price = db.Column(db.Float)
    warranty_expiration = db.Column(db.Date)
    status = db.Column(db.String(20), default='Available')  # Available, Checked Out, In Maintenance, Disposed
    
    # Foreign Keys
    asset_type_id = db.Column(db.Integer, db.ForeignKey('asset_type.id'))
    manufacturer_id = db.Column(db.Integer, db.ForeignKey('manufacturer.id'))
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'))
    department_id = db.Column(db.Integer, db.ForeignKey('department.id'))
    current_employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'))
    
    # Relationships
    asset_type = db.relationship('AssetType', backref='assets')
    manufacturer = db.relationship('Manufacturer', backref='assets')
    location = db.relationship('Location', backref='assets')
    department = db.relationship('Department', backref='assets')
    current_employee = db.relationship('Employee', backref='checked_out_assets')
    
    # Audit fields
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    last_audit_date = db.Column(db.DateTime)
    last_maintenance_date = db.Column(db.DateTime)
    
    def __repr__(self):
        return f'<Asset {self.tag_number}: {self.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'tag_number': self.tag_number,
            'name': self.name,
            'description': self.description,
            'serial_number': self.serial_number,
            'model_number': self.model_number,
            'purchase_date': self.purchase_date.isoformat() if self.purchase_date else None,
            'purchase_price': self.purchase_price,
            'warranty_expiration': self.warranty_expiration.isoformat() if self.warranty_expiration else None,
            'status': self.status,
            'asset_type': self.asset_type.name if self.asset_type else None,
            'manufacturer': self.manufacturer.name if self.manufacturer else None,
            'location': self.location.name if self.location else None,
            'department': self.department.name if self.department else None,
            'current_employee': self.current_employee.name if self.current_employee else None
        }
    
    def is_assigned(self):
        """Return True if the asset is currently assigned to an employee."""
        return self.current_employee_id is not None
    
    @property
    def display_name(self):
        """Return the asset name, ensuring it's always in sync with asset type"""
        if self.asset_type:
            return self.asset_type.name
        return self.name or f"Asset-{self.tag_number}"
    
    def sync_name_with_type(self):
        """Ensure the asset name is synchronized with its asset type name"""
        if self.asset_type_id:
            # Load the asset type if not already loaded
            from app.models.asset_type import AssetType
            asset_type = AssetType.query.get(self.asset_type_id)
            if asset_type and self.name != asset_type.name:
                self.name = asset_type.name 

class AssetHistory(db.Model):
    __tablename__ = 'asset_history'
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, nullable=False)
    tag_number = db.Column(db.String(50))
    name = db.Column(db.String(100))
    description = db.Column(db.Text)
    serial_number = db.Column(db.String(100))
    model_number = db.Column(db.String(100))
    purchase_date = db.Column(db.Date)
    purchase_price = db.Column(db.Float)
    warranty_expiration = db.Column(db.Date)
    status = db.Column(db.String(20))
    asset_type_id = db.Column(db.Integer)
    manufacturer_id = db.Column(db.Integer)
    location_id = db.Column(db.Integer)
    department_id = db.Column(db.Integer)
    current_employee_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime)
    last_audit_date = db.Column(db.DateTime)
    last_maintenance_date = db.Column(db.DateTime)
    action = db.Column(db.String(20))  # created, updated, deleted
    changed_by = db.Column(db.String(64))  # username or user id
    changed_at = db.Column(db.DateTime, default=_utcnow)
    ip_address = db.Column(db.String(45))  # client IP address

    def __repr__(self):
        return f'<AssetHistory {self.asset_id} {self.action} at {self.changed_at}>' 