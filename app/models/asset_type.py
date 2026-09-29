from app import db

class AssetType(db.Model):
    __tablename__ = 'asset_type'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    
    def __repr__(self):
        return f'<AssetType {self.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description
        } 