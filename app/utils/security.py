"""Input helpers shared by the search, export, and JSON endpoints."""

from datetime import datetime
from functools import wraps

from flask import jsonify
from flask_login import current_user


def sanitize_search_term(value):
    """Trim user text. LIKE escaping is applied where the pattern is built."""
    if value is None:
        return ''
    return str(value).replace('\x00', '').strip()[:200]


def sanitize_filter_value(value):
    if value is None:
        return ''
    return str(value).replace('\x00', '').strip()[:100]


def validate_date_string(value):
    """Return a YYYY-MM-DD string, or '' when the value is not a real date."""
    if value is None:
        return ''
    text = str(value).strip()[:10]
    if not text:
        return ''
    try:
        datetime.strptime(text, '%Y-%m-%d')
    except ValueError:
        return ''
    return text


def validate_integer_param(value, default=None, min_val=None, max_val=None):
    if value is None or value == '':
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if min_val is not None and number < min_val:
        return min_val
    if max_val is not None and number > max_val:
        return max_val
    return number


def validate_pagination_params(page):
    try:
        page_number = int(page)
    except (TypeError, ValueError):
        page_number = 1
    return max(page_number, 1)


def _escape_like(value):
    return (
        str(value)
        .replace('\\', '\\\\')
        .replace('%', '\\%')
        .replace('_', '\\_')
    )


def safe_equals_query(query, column, value):
    return query.filter(column == value)


def safe_like_query(query, column, value):
    return query.filter(column.like(f'%{_escape_like(value)}%', escape='\\'))


def safe_ilike_query(query, column, value):
    return query.filter(column.ilike(f'%{_escape_like(value)}%', escape='\\'))


def ajax_login_required(view):
    """JSON 401 for API routes. HTML routes keep using Flask-Login's redirect."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'error': 'Authentication required.'}), 401
        return view(*args, **kwargs)

    return wrapper
