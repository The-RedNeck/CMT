from collections import defaultdict
from threading import Lock
import time

from flask import Blueprint, request, jsonify
from flask_login import login_required
from app.models.employee import Employee
from app.models.department import Department
from app.utils.security import sanitize_search_term, validate_integer_param

bp = Blueprint('search', __name__, url_prefix='/api/search')

_RATE_LOCK = Lock()
_RATE_HITS = defaultdict(list)


def _client_rate_limited(bucket, limit, window_seconds):
    """In-process limit. Each Gunicorn worker keeps its own counts."""
    now = time.monotonic()
    with _RATE_LOCK:
        recent = [stamp for stamp in _RATE_HITS[bucket] if now - stamp < window_seconds]
        if len(recent) >= limit:
            _RATE_HITS[bucket] = recent
            return True
        recent.append(now)
        _RATE_HITS[bucket] = recent
        return False


def _ilike_contains(column, term):
    escaped = (
        str(term)
        .replace('\\', '\\\\')
        .replace('%', '\\%')
        .replace('_', '\\_')
    )
    return column.ilike(f'%{escaped}%', escape='\\')


@bp.route('/employees')
@login_required
def search_employees():
    client_ip = (request.headers.get('X-Forwarded-For') or request.remote_addr or 'unknown').split(',')[0].strip()
    if _client_rate_limited(f'search-employees:{client_ip}', 60, 60):
        return jsonify({'error': 'Too many requests. Try again in a minute.'}), 429

    # Sanitize search query to prevent SQL injection
    q = sanitize_search_term(request.args.get('q', ''))
    department_id = validate_integer_param(request.args.get('department_id'))
    location_id = validate_integer_param(request.args.get('location_id'))
    
    query = Employee.query
    if q:
        query = query.filter(
            _ilike_contains(Employee.first_name, q) | _ilike_contains(Employee.last_name, q)
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
