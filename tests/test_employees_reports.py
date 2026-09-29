import pytest

from app import db
from app.models.asset import Asset
from app.models.department import Department
from app.models.employee import Employee

from tests.conftest import login


def test_employee_pages_and_search(client, admin, catalog):
    login(client)
    page = client.get('/list-forms/employees')
    assert b'Jane Doe' in page.data
    options = client.get('/list-forms/employees?as_options=1')
    assert options.get_json()[0][1] == 'Jane Doe'
    search = client.get('/api/search/employees?q=Jane')
    assert search.get_json() == [{'id': catalog['employee_id'], 'text': 'Jane Doe'}]
    wildcard = client.get('/api/search/employees?q=%')
    assert wildcard.get_json() == []


def test_employee_with_assets_cannot_be_deleted(client, admin, catalog, app):
    login(client)
    with app.app_context():
        asset = db.session.get(Asset, catalog['asset_id'])
        asset.status = 'Checked Out'
        asset.current_employee_id = catalog['employee_id']
        db.session.commit()
    response = client.post(
        f"/list-forms/employees/{catalog['employee_id']}/delete",
        follow_redirects=True,
    )
    assert b'assigned assets' in response.data
    with app.app_context():
        assert db.session.get(Employee, catalog['employee_id']) is not None


def test_new_department_rejects_negative_budget(client, admin, catalog):
    login(client)
    response = client.post('/list-forms/departments/new', data={
        'name': 'Finance',
        'code': 'FIN',
        'budget': '-10',
    })
    assert b'cannot be negative' in response.data
    created = client.post('/list-forms/departments/new', data={
        'name': 'Finance',
        'code': 'FIN',
        'budget': '2500',
    }, follow_redirects=True)
    assert b'Finance' in created.data


def test_reports_status_and_location(client, admin, catalog):
    login(client)
    status = client.get('/reports/api/asset-status')
    body = status.get_json()
    assert 'Available' in body['labels']
    assert body['counts'][body['labels'].index('Available')] == 1
    locations = client.get('/reports/api/assets-by-location')
    grouped = locations.get_json()
    assert grouped['Headquarters']['pagination']['total_assets'] == 1
    dashboard = client.get('/reports/')
    assert b'Asset status' in dashboard.data


@pytest.mark.xfail(reason='Department.to_dict reads manager.name, but Employee only has first_name and last_name.')
def test_department_dict_with_manager(app, catalog):
    with app.app_context():
        department = db.session.get(Department, catalog['department_id'])
        department.manager_id = catalog['employee_id']
        db.session.commit()
        payload = department.to_dict()
        assert payload['manager'] == 'Jane Doe'


@pytest.mark.xfail(reason='Employee search filters Department.location_id, but departments have no location column.')
def test_employee_search_by_location(client, admin, catalog):
    login(client)
    response = client.get(f"/api/search/employees?location_id={catalog['location_id']}")
    assert response.status_code == 200


@pytest.mark.xfail(reason='Creating an employee from the HTML form is treated as AJAX because request.form is always set.')
def test_new_employee_form_redirects(client, admin, catalog):
    login(client)
    response = client.post('/list-forms/employees/new', data={
        'employee_id': 'E2002',
        'first_name': 'Sam',
        'last_name': 'Lee',
        'email': 'sam.lee@example.com',
        'username': 'slee',
    })
    assert response.status_code == 302
