from flask import Blueprint, request, jsonify
from app.models.employee import Employee
from app.models.department import Department
from app.utils.security import sanitize_search_term, validate_integer_param

bp = Blueprint('search', __name__, url_prefix='/api/search')

@bp.route('/employees')
def search_employees():
    # Sanitize search query to prevent SQL injection
    q = sanitize_search_term(request.args.get('q', ''))
    department_id = validate_integer_param(request.args.get('department_id'))
    location_id = validate_integer_param(request.args.get('location_id'))
    
    query = Employee.query
    if q:
        # Use safe parameterized queries
        query = query.filter(
            (Employee.first_name.ilike(f'%{q}%')) | (Employee.last_name.ilike(f'%{q}%'))
        )
    if department_id:
        query = query.filter(Employee.department_id == department_id)
    if location_id:
        query = query.join(Employee.department).filter(Department.location_id == location_id)
    employees = query.limit(20).all()
    return jsonify([
        {'id': e.id, 'text': f'{e.first_name} {e.last_name}'}
        for e in employees
    ])
