import os
from flask import Flask, request, send_file, render_template
from PIL import Image # Pillow library for image processing
from fpdf import FPDF # FPDF library for PDF generation
import uuid # For generating unique filenames

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
    """
    Handles image uploads, converts them to a single PDF, and sends the PDF back.
    """
    if 'images' not in request.files:
        return {"error": "No image files part in the request"}, 400

    uploaded_files = request.files.getlist('images')
    if not uploaded_files:
        return {"error": "No selected image files"}, 400

    image_paths = []
    # Save uploaded images temporarily
    for file in uploaded_files:
        if file and allowed_file(file.filename):
            filename = str(uuid.uuid4()) + os.path.splitext(file.filename)[1]
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            image_paths.append(filepath)
        else:
            # Handle disallowed file types or empty files
            # For simplicity, we'll just skip them, but you might want to return an error
            print(f"Skipping disallowed or empty file: {file.filename}")

    if not image_paths:
        return {"error": "No valid image files provided for conversion."}, 400

    # Create a unique PDF filename
    pdf_filename = f"converted_images_{uuid.uuid4()}.pdf"
    pdf_filepath = os.path.join(PDF_OUTPUT_FOLDER, pdf_filename)

    # Initialize PDF document
    # 'P' for portrait, 'mm' for millimeters, 'A4' for page size
    pdf = FPDF(unit='mm', format='A4')

    try:
        # Add each image to a new page in the PDF
        for img_path in image_paths:
            pdf.add_page()
            # Calculate position and dimensions to fit image
            x, y, w, h = get_image_fit_dimensions(img_path)
            # Add image to PDF
            pdf.image(img_path, x=x, y=y, w=w, h=h)
    except Exception as e:
        # Catch any errors during image processing or PDF creation
        print(f"Error during PDF generation: {e}")
        return {"error": f"Failed to process images or create PDF: {e}"}, 500
    finally:
        # Clean up uploaded image files
        for img_path in image_paths:
            if os.path.exists(img_path):
                os.remove(img_path)

    # Save the PDF to the output folder
    pdf.output(pdf_filepath)

    # Send the generated PDF file to the client
    response = send_file(pdf_filepath, as_attachment=True, download_name=pdf_filename, mimetype='application/pdf')

    # Optional: Schedule cleanup of the generated PDF after it's sent
    # For a real application, consider a more robust cleanup mechanism (e.g., a background job)
    # For local usage, manual cleanup of temp_pdfs folder is fine.
    # If the response is successfully sent, you can attempt to delete the file immediately.
    # Note: send_file might keep the file open until response is fully sent,
    # so a slight delay or a separate cleanup script might be needed for production.
    # For this local demo, it's generally fine.
    @response.call_on_close
    def cleanup():
        if os.path.exists(pdf_filepath):
            os.remove(pdf_filepath)
            print(f"Cleaned up {pdf_filepath}")

    return response

# Run the Flask app
if __name__ == '__main__':
    # You can change the port if needed
    app.run(debug=True, port=5000)
