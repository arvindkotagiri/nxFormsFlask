import os, io, json, re, PIL.Image
import fitz  # PyMuPDF
from flask import Flask, request, jsonify
from flask_cors import CORS
from google import genai
from google.genai import types 
from dotenv import load_dotenv
from flask import Blueprint

load_dotenv()
# app = Flask(__name__)
# CORS(app)
invoice_bp = Blueprint('invoice', __name__)

MODEL_ID = 'gemini-3-flash-preview' 
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY_INVOICE"))

PROMPT_PRECISION = """
Role: Expert Senior Frontend Engineer.
Task: Create a pixel-perfect Tailwind CSS replica of the attached invoice.
Return ONLY a JSON object: {"full_invoice_html": "<html>...</html>"}
"""

@invoice_bp.route('/replicate-invoice', methods=['POST'])
def replicate_invoice():
    if 'image' not in request.files: return jsonify({"error": "No file"}), 400
    try:
        file = request.files['image']
        file_bytes = file.read()
        filename = file.filename.lower()

        # --- PDF TO IMAGE CONVERSION ---
        if filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            page = doc.load_page(0)  # Replicating the first page layout
            # Use a high matrix for "pixel-perfect" detail
            pix = page.get_pixmap(matrix=fitz.Matrix(3, 3)) 
            img_bytes = pix.tobytes("jpeg")
            doc.close()
        else:
            # Handle standard Image
            img_byte_arr = io.BytesIO()
            PIL.Image.open(io.BytesIO(file_bytes)).convert("RGB").save(img_byte_arr, format='JPEG')
            img_bytes = img_byte_arr.getvalue()

        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=PROMPT_PRECISION),
                    types.Part.from_bytes(
                        data=img_bytes, 
                        mime_type="image/jpeg",
                        media_resolution="media_resolution_ultra_high" 
                    )
                ]
            )
        ]

        response = client.models.generate_content(
            model=MODEL_ID,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0,
                thinking_config=types.ThinkingConfig(thinking_level="high")
            )
        )
        
        raw_text = response.text.strip()
        data = json.loads(raw_text)

        # Extraction logic
        if isinstance(data, list):
            html_content = data[0].get('full_invoice_html', '')
        else:
            html_content = data.get('full_invoice_html', '')

        if not html_content:
            return jsonify({"error": "No HTML found", "raw": raw_text}), 500

        return jsonify({
            "status": "success",
            "full_html": html_content
        })

    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")
        return jsonify({"error": str(e)}), 500

# if __name__ == '__main__':
#     app.run(port=5052, debug=False, threaded=True)