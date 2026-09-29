from datetime import datetime
from app import db

class Maintenance(db.Model):
    """Model for asset maintenance records"""
    __tablename__ = 'maintenance'

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), nullable=False)
    maintenance_type = db.Column(db.String(50), nullable=False)  # Preventive, Corrective, Predictive, Condition-Based
    priority = db.Column(db.String(20), nullable=False)  # Low, Medium, High, Critical
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    cost = db.Column(db.Numeric(10, 2))
    description = db.Column(db.Text, nullable=False)
    findings = db.Column(db.Text)
    recommendations = db.Column(db.Text)
    requires_followup = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    asset = db.relationship('Asset', backref=db.backref('maintenance_records', lazy=True))

    def __repr__(self):
        return f'<Maintenance {self.id} - {self.asset.name}>' 