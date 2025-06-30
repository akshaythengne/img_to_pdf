import os
from flask import Flask, request, send_file, render_template, jsonify, make_response
from PIL import Image # Pillow library for image processing
from fpdf import FPDF # FPDF library for PDF generation
import uuid # For generating unique filenames
import traceback # Import traceback for detailed error logging
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
import io
import smtplib
from email.message import EmailMessage

# Initialize the Flask application
app = Flask(__name__)

# --- Configuration ---
# Define a temporary directory for uploaded images and generated PDFs
# It's good practice to handle temp files carefully, e.g., cleanup after a period
UPLOAD_FOLDER = 'temp_uploads'
PDF_OUTPUT_FOLDER = 'temp_pdfs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True) # Create upload directory if it doesn't exist
os.makedirs(PDF_OUTPUT_FOLDER, exist_ok=True) # Create PDF output directory if it doesn't exist

# Allowed image extensions for security and filtering
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}

# A4 page dimensions in mm (standard for FPDF)
A4_WIDTH_MM = 210
A4_HEIGHT_MM = 297
# Margins for the images on the PDF page (in mm)
PAGE_MARGIN_MM = 10

def allowed_file(filename):
    """
    Checks if the uploaded file has an allowed extension.
    """
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_image_fit_dimensions(img_path):
    """
    Calculates dimensions and position to fit an image onto an A4 page
    with margins, maintaining its aspect ratio.
    """
    img = Image.open(img_path)
    img_width_px, img_height_px = img.size

    # Calculate usable area for image on PDF page
    usable_width_mm = A4_WIDTH_MM - 2 * PAGE_MARGIN_MM
    usable_height_mm = A4_HEIGHT_MM - 2 * PAGE_MARGIN_MM

    # Calculate aspect ratios
    aspect_ratio_img = img_width_px / img_height_px
    aspect_ratio_page = usable_width_mm / usable_height_mm

    # Determine final dimensions to fit the image
    if aspect_ratio_img > aspect_ratio_page:
        # Image is wider than the usable page area (proportionally), fit to width
        final_width_mm = usable_width_mm
        final_height_mm = usable_width_mm / aspect_ratio_img
    else:
        # Image is taller than the usable page area (proportionally), fit to height
        final_height_mm = usable_height_mm
        final_width_mm = usable_height_mm * aspect_ratio_img

    # Calculate centered position
    x_pos = PAGE_MARGIN_MM + (usable_width_mm - final_width_mm) / 2
    y_pos = PAGE_MARGIN_MM + (usable_height_mm - final_height_mm) / 2

    return x_pos, y_pos, final_width_mm, final_height_mm

# --- Routes ---
@app.route('/')
def index():
    """
    Renders the main HTML page for the application.
    """
    return render_template('index.html')

@app.route('/convert-to-pdf', methods=['POST'])
def convert_to_pdf():
    # --- Get options from form ---
    layout = request.form.get('layout', 'A4-P')
    compress = request.form.get('compress', 'false') == 'true'
    resize = request.form.get('resize', 'false') == 'true'
    watermark = request.form.get('watermark', '')
    password = request.form.get('password', '')
    email = request.form.get('email', '')

    # Layout parsing
    if layout.startswith('A4'):
        page_format = 'A4'
    else:
        page_format = 'Letter'
    orientation = 'L' if layout.endswith('-L') else 'P'

    # --- Handle images ---
    uploaded_files = request.files.getlist('images')
    image_paths = []
    for file in uploaded_files:
        if file.filename == '':
            continue
        if file and allowed_file(file.filename):
            filename = str(uuid.uuid4()) + os.path.splitext(file.filename)[1]
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            image_paths.append(filepath)

    # --- Handle PDF merge ---
    pdf_files = request.files.getlist('pdfs')
    pdf_paths = []
    for file in pdf_files:
        if file.filename and file.filename.lower().endswith('.pdf'):
            filename = str(uuid.uuid4()) + '.pdf'
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            pdf_paths.append(filepath)

    if not image_paths and not pdf_paths:
        return jsonify({"error": "No valid image or PDF files provided for conversion."}), 400

    # --- Create PDF from images ---
    pdf = FPDF(orientation=orientation, unit='mm', format=page_format)
    try:
        for img_path in image_paths:
            pdf.add_page()
            x, y, w, h = get_image_fit_dimensions(img_path)
            with Image.open(img_path) as img:
                if compress:
                    img = img.convert('RGB').resize((int(img.width*0.7), int(img.height*0.7)))
                    img.save(img_path, optimize=True, quality=60)
                if resize:
                    img = img.resize((int(w*3.78), int(h*3.78))) # 1mm ≈ 3.78px
                    img.save(img_path)
            pdf.image(img_path, x=x, y=y, w=w, h=h)
            if watermark:
                pdf.set_xy(x, y+h-10)
                pdf.set_text_color(150,150,150)
                pdf.set_font('Arial', 'I', 12)
                pdf.cell(w, 10, watermark, 0, 0, 'C')
    finally:
        for img_path in image_paths:
            try:
                os.remove(img_path)
            except Exception as e:
                print(f"Could not delete {img_path}: {e}")

    # --- Save to BytesIO for merging and password ---
    pdf_bytes = io.BytesIO(pdf.output(dest='S').encode('latin1'))
    pdf_bytes.seek(0)

    # --- Merge with uploaded PDFs if any ---
    merger = PdfMerger()
    open_pdfs = []
    try:
        for path in pdf_paths:
            f = open(path, 'rb')
            open_pdfs.append(f)
            merger.append(f)
        merger.append(pdf_bytes)
        merged_bytes = io.BytesIO()
        merger.write(merged_bytes)
        merger.close()
        merged_bytes.seek(0)
    finally:
        for f in open_pdfs:
            try:
                f.close()
            except Exception as e:
                print(f"Could not close PDF file: {e}")
        for path in pdf_paths:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception as e:
                print(f"Could not delete {path}: {e}")

    # --- Password protection ---
    if password:
        reader = PdfReader(merged_bytes)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.encrypt(password)
        protected_bytes = io.BytesIO()
        writer.write(protected_bytes)
        protected_bytes.seek(0)
        final_pdf = protected_bytes
    else:
        final_pdf = merged_bytes

    # --- Save final PDF to disk for download and email ---
    pdf_filename = f"converted_images_{uuid.uuid4()}.pdf"
    pdf_filepath = os.path.join(PDF_OUTPUT_FOLDER, pdf_filename)
    with open(pdf_filepath, 'wb') as f:
        f.write(final_pdf.read())
    final_pdf.seek(0)

    # --- Email PDF if requested ---
    if email:
        try:
            msg = EmailMessage()
            msg['Subject'] = 'Your Converted PDF'
            msg['From'] = 'noreply@example.com'
            msg['To'] = email
            msg.set_content('Your PDF is attached.')
            final_pdf.seek(0)
            msg.add_attachment(final_pdf.read(), maintype='application', subtype='pdf', filename=pdf_filename)
            # NOTE: Configure your SMTP server here
            with smtplib.SMTP('localhost') as s:
                s.send_message(msg)
        except Exception as e:
            print(f"Email send error: {e}")

    # --- Send PDF to client ---
    response = send_file(pdf_filepath, as_attachment=True, download_name=pdf_filename, mimetype='application/pdf')
    @response.call_on_close
    def cleanup():
        if os.path.exists(pdf_filepath):
            os.remove(pdf_filepath)
    return response

@app.errorhandler(Exception)
def handle_exception(e):
    # If the request is for HTML, return default
    if not request.path.startswith('/convert-to-pdf'):
        return e
    # Otherwise, return JSON error
    import traceback
    response = make_response(jsonify({
        "error": str(e),
        "trace": traceback.format_exc()
    }), 500)
    response.headers["Content-Type"] = "application/json"
    return response

# Run the Flask app
if __name__ == '__main__':
    # You can change the port if needed
    # debug=True allows for automatic reloading on code changes and more detailed error messages
    app.run(debug=True, port=5000)

