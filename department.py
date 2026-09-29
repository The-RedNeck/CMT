from app import db
from datetime import datetime

class Department(db.Model):
    __tablename__ = 'department'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    code = db.Column(db.String(20), unique=True)
    description = db.Column(db.Text)
    manager_id = db.Column(db.Integer, db.ForeignKey('employee.id'))
    parent_department_id = db.Column(db.Integer, db.ForeignKey('department.id'))
    cost_center = db.Column(db.String(50))
    budget = db.Column(db.Float)
    
    # Audit fields
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    manager = db.relationship('Employee', backref='managed_departments', foreign_keys=[manager_id])
    parent_department = db.relationship('Department', backref='child_departments', remote_side=[id])
    employees = db.relationship('Employee', backref='department', lazy='dynamic', foreign_keys='Employee.department_id')
    
    def __repr__(self):
        return f'<Department {self.code}: {self.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'description': self.description,
            'manager': self.manager.name if self.manager else None,
            'parent_department': self.parent_department.name if self.parent_department else None,
            'cost_center': self.cost_center,
            'budget': self.budget,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        } 