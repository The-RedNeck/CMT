"""Import models so SQLAlchemy registers every table before create_all."""

from app.models.asset import Asset, AssetHistory
from app.models.asset_type import AssetType
from app.models.available_tag_number import AvailableTagNumber
from app.models.department import Department
from app.models.employee import Employee, EmployeeHistory
from app.models.location import Location
from app.models.maintenance import Maintenance
from app.models.manufacturer import Manufacturer
from app.models.user import User

__all__ = [
    'Asset',
    'AssetHistory',
    'AssetType',
    'AvailableTagNumber',
    'Department',
    'Employee',
    'EmployeeHistory',
    'Location',
    'Maintenance',
    'Manufacturer',
    'User',
]
