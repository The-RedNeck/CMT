from app import db
from datetime import datetime

class AvailableTagNumber(db.Model):
    __tablename__ = 'available_tag_numbers'
    id = db.Column(db.Integer, primary_key=True)
    tag_number = db.Column(db.String(50), unique=True, nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    assigned_asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<AvailableTagNumber {self.tag_number}>' 