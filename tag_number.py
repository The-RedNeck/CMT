from flask import Blueprint, request, jsonify, render_template, flash, make_response
from flask_wtf import FlaskForm
from wtforms import IntegerField, SubmitField
from wtforms.validators import DataRequired, NumberRange
from app import db
from app.models.available_tag_number import AvailableTagNumber
from app.models.asset import Asset
from app.utils.security import validate_integer_param, sanitize_search_term
from datetime import datetime
import re
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from barcode import Code128
from barcode.writer import ImageWriter
import io
import base64
from PIL import Image

bp = Blueprint('tag_number', __name__, url_prefix='/tag-numbers')

class TagGenerationForm(FlaskForm):
    count = IntegerField('Number of Tags', validators=[DataRequired(), NumberRange(min=1, max=100)])
    submit = SubmitField('Generate PDF')

@bp.route('/generate', methods=['POST'])
def generate_tag_numbers():
    data = request.get_json() or {}
    # Sanitize and validate inputs
    prefix = sanitize_search_term(data.get('prefix', 'T'))[:10]  # Limit prefix length
    start = validate_integer_param(data.get('start', 1), default=1, min_val=1, max_val=9999999)
    count = validate_integer_param(data.get('count', 100), default=100, min_val=1, max_val=1000)
    
    # Ensure we have valid integers (should not be None due to defaults)
    if start is None:
        start = 1
    if count is None:
        count = 100
    
    generated = []
    for i in range(start, start + count):
        # Generate base tag number
        base_tag = f"{prefix}{str(i).zfill(6)}"
        
        # Create full tag number with BHSN prefix: BHSN-TagNumber
        full_tag = f"BHSN-{base_tag}"
        
        # Use parameterized queries (already safe)
        exists = AvailableTagNumber.query.filter_by(tag_number=full_tag).first() or Asset.query.filter_by(tag_number=full_tag).first()
        if not exists:
            new_tag = AvailableTagNumber()
            new_tag.tag_number = full_tag
            db.session.add(new_tag)
            generated.append(full_tag)
    db.session.commit()
    return jsonify({'generated': generated, 'count': len(generated)})

@bp.route('/available', methods=['GET'])
def list_available_tags():
    tags = AvailableTagNumber.query.filter_by(is_used=False).all()
    return jsonify([t.tag_number for t in tags])

@bp.route('/used', methods=['GET'])
def list_used_tags():
    tags = AvailableTagNumber.query.filter_by(is_used=True).all()
    return jsonify([t.tag_number for t in tags])

def get_last_tag_number():
    """Get the highest tag number from the Asset table"""
    # Query all assets and find the highest numeric tag number
    assets = Asset.query.with_entities(Asset.tag_number).all()
    max_num = 0
    
    for asset in assets:
        # Check for both old format (T0000738) and new format (BHSN-T0000738-T0000738)
        if asset.tag_number:
            # Try to extract numeric part from old format
            if asset.tag_number.startswith('T'):
                try:
                    num_part = int(asset.tag_number[1:])  # Remove 'T' and convert to int
                    max_num = max(max_num, num_part)
                except ValueError:
                    continue
            # Try to extract numeric part from new format (BHSN-T0000738)
            elif asset.tag_number.startswith('BHSN-'):
                try:
                    # Extract the tag number part after BHSN-
                    parts = asset.tag_number.split('-')
                    if len(parts) >= 2 and parts[1].startswith('T'):
                        num_part = int(parts[1][1:])  # Remove 'T' and convert to int
                        max_num = max(max_num, num_part)
                except ValueError:
                    continue
    
    return f"T{str(max_num).zfill(7)}" if max_num > 0 else "T0000000"

def generate_barcode_image(tag_number):
    """Generate barcode image for PDF"""
    # Create barcode
    code = Code128(tag_number, writer=ImageWriter())
    buffer = io.BytesIO()
    code.write(buffer)
    buffer.seek(0)
    
    # Return ImageReader object for ReportLab
    return ImageReader(buffer)

@bp.route('/', methods=['GET', 'POST'])
def generate_tags_interface():
    """Web interface for generating tag numbers"""
    form = TagGenerationForm()
    last_tag = get_last_tag_number()
    
    if form.validate_on_submit():
        count = form.count.data or 1  # Ensure count is not None
        
        # Get next tag number
        if last_tag == "T0000000":
            start_num = 1
        else:
            start_num = int(last_tag[1:]) + 1
        
        # Generate PDF
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        
        # PDF settings
        tags_per_row = 3
        tag_width = width / tags_per_row
        tag_height = 2.5 * inch
        current_row = 0
        tags_in_row = 0
        
        for i in range(count):
            # Generate the base tag number (e.g., T0001449)
            base_tag_num = f"T{str(start_num + i).zfill(7)}"
            
            # Create the full tag number with BHSN prefix: BHSN-TagNumber
            # Format: BHSN-T0001449
            full_tag_num = f"BHSN-{base_tag_num}"
            
            # Calculate position
            x = (tags_in_row * tag_width) + (tag_width / 2)
            y = height - (current_row + 1) * tag_height - 50
            
            # Generate barcode image for the full tag number
            try:
                barcode_img = generate_barcode_image(full_tag_num)
                
                # Draw barcode image centered (includes text) with auto height
                barcode_width = 120
                p.drawImage(barcode_img, x - barcode_width/2, y + 10, 
                           width=barcode_width, preserveAspectRatio=True)
                
                # Note: Barcode image already includes the text label, so no need to add duplicate text
                
            except Exception as e:
                # Fallback to text only
                p.setFont("Helvetica-Bold", 12)
                p.drawCentredString(x, y + 25, full_tag_num)
                p.setFont("Helvetica", 10)
                p.drawCentredString(x, y + 10, f"Error: {str(e)[:30]}")
            
            tags_in_row += 1
            
            # Move to next row if needed
            if tags_in_row >= tags_per_row:
                tags_in_row = 0
                current_row += 1
                
                # Start new page if needed
                if y < 100:
                    p.showPage()
                    current_row = 0
        
        p.save()
        buffer.seek(0)
        
        # Create response
        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=BHSN_tag_numbers_{start_num}_to_{start_num + (count or 1) - 1}.pdf'
        
        buffer.close()
        return response
    
    return render_template('tag_numbers/generate.html', form=form, last_tag_number=last_tag) 