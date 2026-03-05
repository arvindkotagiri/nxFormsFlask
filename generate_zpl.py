import os, re, base64, requests, io
import PIL.Image
import fitz  # PyMuPDF
from flask import Flask, request, jsonify
from flask_cors import CORS
from google import genai
from google.genai import types # Added for Part handling
from dotenv import load_dotenv
from flask import Blueprint

load_dotenv()
# app = Flask(__name__)
# CORS(app)
zpl_bp = Blueprint('zpl', __name__)

MODEL_ID = 'gemini-3-flash-preview'
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY_ANNOTATE"))

def clean_zpl(text):
    """Strictly extracts ZPL code block."""
    match = re.search(r'(\^XA[\s\S]*?\^XZ)', text)
    if match:
        return match.group(1).strip()
    return text.replace("```zpl", "").replace("```", "").strip()

def get_labelary_preview(zpl_text, width_in, height_in, dpmm):
    """Hits Labelary API for a visual preview."""
    url = f'http://api.labelary.com/v1/printers/{dpmm}dpmm/labels/{width_in}x{height_in}/0/'
    try:
        response = requests.post(url, data=zpl_text, timeout=10)
        if response.status_code == 200:
            return base64.b64encode(response.content).decode()
    except Exception as e:
        print(f"Labelary Error: {e}")
    return None

@zpl_bp.route('/generate-zpl', methods=['POST'])
def generate_zpl():
    width_in = float(request.form.get('width', 4))
    height_in = float(request.form.get('height', 6))
    dpi = int(request.form.get('dpi', 203))
    dpmm = 8 if dpi < 300 else 12

    if 'image' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    try:
        file = request.files['image']
        file_bytes = file.read()
        filename = file.filename.lower()

        # --- DYNAMIC PDF OR IMAGE HANDLING ---
        if filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            page = doc.load_page(0)
            # High-res render so Gemini sees fine-print details
            pix = page.get_pixmap(matrix=fitz.Matrix(3, 3)) 
            pil_img = PIL.Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            doc.close()
        else:
            pil_img = PIL.Image.open(io.BytesIO(file_bytes)).convert("RGB")

        zpl_prompt = f"""
        ACT AS A ZPL EXPERT.
        Convert the attached label image into valid ZPL II code.
        
        SPECS:
        - Target DPI: {dpi} ({dpmm} dpmm)
        - Label Size: {width_in}" x {height_in}"
        
        RULES:
        1. Use ^FB for multi-line text blocks.
        2. Use ^GB for boxes and separators.
        3. For Barcodes: Use ^BC (Code 128) or ^BX (Data Matrix) as seen in image.
        4. Return ONLY the code starting with ^XA and ending with ^XZ.
        5. DO NOT include markdown or explanations.
        """

        # Generate content using the image (either original or converted from PDF)
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=[zpl_prompt, pil_img]
        )
        
        zpl_code = clean_zpl(response.text)
        
        if not zpl_code:
            return jsonify({"error": "Gemini failed to generate ZPL"}), 500

        preview_b64 = get_labelary_preview(zpl_code, width_in, height_in, dpmm)

        return jsonify({
            "status": "success",
            "zpl_code": zpl_code,
            "labelary_preview": f"data:image/png;base64,{preview_b64}" if preview_b64 else None
        })

    except Exception as e:
        print(f"Server Error: {str(e)}")
        return jsonify({"error": str(e)}), 500

# if __name__ == '__main__':
#     app.run(port=5051, debug=False, threaded=True)