"""Small PDF receipts written to a caller-supplied path."""

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def _write(path, title, lines):
    document = canvas.Canvas(path, pagesize=letter)
    document.setTitle(title)
    document.setFont('Helvetica-Bold', 16)
    document.drawString(72, 740, title)
    document.setFont('Helvetica', 11)
    y = 700
    for line in lines:
        document.drawString(72, y, str(line)[:110])
        y -= 18
        if y < 72:
            document.showPage()
            document.setFont('Helvetica', 11)
            y = 740
    document.save()
    return path


def _asset_lines(asset, employee):
    employee_name = employee.full_name if employee is not None else 'Unassigned'
    return [
        f'Tag number: {asset.tag_number}',
        f'Name: {asset.name}',
        f'Serial: {asset.serial_number or "-"}',
        f'Status: {asset.status}',
        f'Employee: {employee_name}',
    ]


def generate_checkout_receipt(asset, employee, path):
    return _write(path, 'Asset checkout receipt', _asset_lines(asset, employee))


def generate_checkin_receipt(asset, employee, path):
    return _write(path, 'Asset check-in receipt', _asset_lines(asset, employee))


def generate_bulk_checkout_receipt(assets, employee, path):
    lines = [f'Employee: {employee.full_name}', f'Assets: {len(assets)}', '']
    lines.extend(f'{asset.tag_number}  {asset.name}' for asset in assets)
    return _write(path, 'Bulk checkout receipt', lines)


def generate_bulk_checkin_receipt(assets, employee, path):
    lines = [f'Employee: {employee.full_name}', f'Assets: {len(assets)}', '']
    lines.extend(f'{asset.tag_number}  {asset.name}' for asset in assets)
    return _write(path, 'Bulk check-in receipt', lines)
