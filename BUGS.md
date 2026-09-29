# CMT Bug Analysis Report

This document contains a comprehensive analysis of potential bugs, issues, and areas for improvement in the CMT (Configuration Management Tool) codebase.

## Critical Issues

### 1. Duplicate Import Statement
**File:** `asset_management.py` (lines 20-23)
**Severity:** Low (Code Quality)
**Description:** The `os` module is imported twice.
```python
import os
from app.utils.export import export_to_excel
from sqlalchemy import and_, or_, func
import os  # Duplicate import
```
**Fix:** Remove the duplicate import.

### 2. Unimplemented Route Handlers
**File:** `asset_management.py`
**Severity:** High
**Description:** Several routes have empty POST handlers that do nothing:
- `move_asset()` (line 530-534): POST handler contains only `pass`
- `audit_asset()` (line 630-635): POST handler contains only `pass`
- `advanced_find()` (line 880-885): POST handler contains only `pass`

**Impact:** Users clicking submit buttons on these forms will see no action taken.
**Fix:** Implement the actual business logic or remove the POST method if not needed.

### 3. Missing CSRF Validation
**File:** `asset_management.py`
**Severity:** Medium (Security)
**Description:** The `api_add_department()` endpoint (line 1230) does NOT validate CSRF tokens, unlike other similar endpoints (`api_add_asset_type`, `api_add_location`, `api_add_manufacturer`) which do validate CSRF.
**Impact:** Potential CSRF vulnerability for department creation.
**Fix:** Add CSRF validation:
```python
from flask_wtf.csrf import validate_csrf
from wtforms import ValidationError
try:
    validate_csrf(request.form.get('csrf_token'))
except ValidationError:
    return jsonify({'success': False, 'message': 'Invalid CSRF token.'}), 400
```

### 4. Inconsistent Error Handling in Receipt Generation
**File:** `asset_management.py`
**Severity:** Medium
**Description:** In `generate_and_send_checkout_receipt()` and `generate_and_send_checkin_receipt()`, if an error occurs after the temporary file is created but before `os.unlink()` is called, the temporary file will be orphaned.
```python
try:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
        temp_path = temp_file.name
    receipt_path = generate_checkout_receipt(asset, employee, temp_path)
    # ... if error happens here ...
    os.unlink(receipt_path)  # Never reached
```
**Fix:** Use a `finally` block to ensure cleanup:
```python
try:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
        temp_path = temp_file.name
    receipt_path = generate_checkout_receipt(asset, employee, temp_path)
    # ...
except Exception as e:
    print(f"Error generating checkout receipt: {e}")
    return None
finally:
    if os.path.exists(temp_path):
        try:
            os.unlink(temp_path)
        except:
            pass
```

### 5. Hardcoded Debug Print Statements
**File:** Multiple files
**Severity:** Low (Security/Production)
**Description:** Many files contain `print()` statements that output sensitive information:
- `asset_management.py`: Lines 260, 271, 314, 317, etc. print filter parameters, query results
- `auth.py`: Lines 21, 30 print IP addresses and usernames
- `list_forms.py`: Lines 317, 318 print error messages

**Impact:** In production, these can leak sensitive information to logs.
**Fix:** Replace with proper logging using `current_app.logger` with appropriate log levels.

### 6. Potential SQL Injection in Search
**File:** `asset_management.py` (line 867-874)
**Severity:** Medium (Security)
**Description:** In `find_asset()`, the search query uses `ilike` with f-string interpolation without using the `sanitize_search_term` function on the final pattern:
```python
query = sanitize_search_term(request.args.get('q', ''))
if query:
    assets = Asset.query.outerjoin(...).filter(
        (Asset.tag_number.ilike(f'%{query}%')) |  # Pattern not sanitized
        ...
    )
```
While `sanitize_search_term` is called, SQLAlchemy's `ilike` with an f-string can still be vulnerable depending on the sanitization implementation.
**Fix:** Use parameterized queries consistently or ensure the sanitization strips all SQL-special characters.

### 7. Race Condition in Asset ID Generation
**File:** `asset_management.py` (lines 461-465)
**Severity:** High
**Description:** Manual ID calculation for new assets:
```python
max_id = db.session.query(db.func.max(Asset.id)).scalar()
next_id = (max_id or 0) + 1
asset.id = next_id
```
**Impact:** In concurrent requests, two assets could get the same ID, causing a database error.
**Fix:** Let the database handle auto-increment, or use a database sequence with proper locking.

### 8. Missing Input Validation
**File:** `list_forms.py` (lines 257-320)
**Severity:** Medium
**Description:** In `new_employee()`, there's no validation for:
- Email format (although the model has email column)
- Phone number format
- Employee ID uniqueness check is missing (only checks username/email)
**Fix:** Add proper validation using WTForms or manual checks.

## Moderate Issues

### 9. Deprecated datetime.utcnow() Usage
**File:** Multiple model files
**Severity:** Low
**Description:** `datetime.utcnow()` is deprecated in Python 3.12+. Should use `datetime.now(datetime.UTC)` instead.
**Files affected:** `asset.py`, `employee.py`, `department.py`, `location.py`, `maintenance.py`, `manufacturer.py`, `user.py`
**Fix:** Replace `datetime.utcnow()` with `datetime.now(datetime.UTC)`.

### 10. Missing Foreign Key Index
**File:** Model files
**Severity:** Low (Performance)
**Description:** Foreign key columns don't have explicit indexes:
- `Asset.current_employee_id`
- `Asset.location_id`
- `Asset.department_id`
- `Employee.department_id`
**Impact:** Slower queries when filtering or joining on these columns.
**Fix:** Add `index=True` to foreign key column definitions.

### 11. Inconsistent Error Response Formats
**File:** Multiple blueprint files
**Severity:** Low (API Consistency)
**Description:** API endpoints return errors in different formats:
- Some return `{'success': False, 'message': '...'}`
- Others return `{'error': '...'}`
- Some include HTTP status codes, others don't
**Fix:** Standardize on one error response format.

### 12. Missing Relationship Backref Conflicts
**File:** `employee.py` and `department.py`
**Severity:** Low
**Description:** Both `Employee` and `Department` have relationships that could conflict:
- `Employee.location` uses `backref='employees'`
- `Department.employees` also references employees

This could cause confusion when accessing relationships.

### 13. Unused Form Fields
**File:** `administration.py`
**Severity:** Low
**Description:** `DeleteUserForm` and `ToggleUserActiveForm` contain only a hidden submit field but no actual form logic beyond CSRF protection.

### 14. Receipt Files Not Cleaned Up
**File:** `asset_management.py` (lines 1564-1579, 1620-1635)
**Severity:** Medium
**Description:** Receipt files generated in `assign_asset()` and `generate_checkout_receipt_route()` are saved to `static/receipts/` but never cleaned up, leading to disk space accumulation over time.
**Fix:** Implement a cleanup job or use temporary files like other receipt generation functions.

### 15. Session Manipulation Without Validation
**File:** `asset_management.py` (lines 370-375)
**Severity:** Low
**Description:** Session is manipulated to keep it alive without proper validation:
```python
if session.get('_permanent'):
    session.permanent = True
    session.modified = True
```
This should be handled at the app configuration level, not in individual routes.

## Low Priority Issues

### 16. Magic Numbers
**File:** Multiple files
**Severity:** Low (Code Quality)
**Description:** Magic numbers used throughout:
- `per_page = 25` (hardcoded pagination)
- `max_attempts = 20` (login attempts)
- `lockout_durations = [2min, 5min, 15min, 1hour, 24hours]`
**Fix:** Move to configuration constants.

### 17. Missing Model Validation
**File:** Model files
**Severity:** Medium
**Description:** Models lack validation:
- `Asset.purchase_price` can be negative
- `Maintenance.cost` can be negative
- `Department.budget` can be negative
- Phone numbers have no format validation
**Fix:** Add column-level or model-level validators.

### 18. Inefficient Database Queries
**File:** `reports.py` (lines 90-100)
**Severity:** Low (Performance)
**Description:** In `asset_value_trend()`, all assets are loaded into memory to create a pandas DataFrame:
```python
assets = Asset.query.filter(...).all()
df = pd.DataFrame([{...} for asset in assets])
```
**Fix:** Use database aggregation instead for large datasets.

### 19. Missing Cascade Deletes
**File:** Model relationships
**Severity:** Medium
**Description:** Cascade deletes are not defined for most relationships. Deleting a department won't automatically handle related employees or assets.
**Fix:** Add appropriate cascade options to relationships or handle in application logic.

### 20. Duplicate Code in Export Functions
**File:** `reports.py` and `list_forms.py`
**Severity:** Low (Code Quality)
**Description:** Excel export logic is duplicated across multiple functions with similar patterns.
**Fix:** Create a reusable export utility function.

## Security Recommendations

1. **Rate Limiting:** No rate limiting on API endpoints
2. **Input Sanitization:** While `sanitize_search_term` exists, it's not used consistently
3. **Password Policy:** No password complexity requirements visible in user creation
4. **Audit Logging:** IP address logging exists but could be more comprehensive
5. **Session Security:** Consider adding session timeout configuration

## Code Quality Recommendations

1. Add type hints to all functions
2. Add docstrings to all public functions
3. Create constants file for magic numbers
4. Standardize error handling patterns
5. Add unit tests
6. Use logging instead of print statements
7. Consider using Flask-Limiter for rate limiting
8. Implement proper database migrations
