"""Excel download helper used by the list and history exports."""

import io

import pandas as pd
from flask import send_file


def export_to_excel(data, sheet_name='Export', base_filename='export'):
    if not data:
        return None
    frame = pd.DataFrame(data)
    output = io.BytesIO()
    safe_sheet = str(sheet_name)[:31] or 'Export'
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        frame.to_excel(writer, sheet_name=safe_sheet, index=False)
    output.seek(0)
    filename = f'{base_filename}.xlsx'
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
