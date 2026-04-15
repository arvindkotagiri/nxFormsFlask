import os, io, json, re, PIL.Image, base64
import fitz  # PyMuPDF
from flask import Flask, request, jsonify
from flask_cors import CORS
from google import genai
from google.genai import types 
from dotenv import load_dotenv
from flask import Blueprint
from settings_routes import get_model_for_process

load_dotenv()
# app = Flask(__name__)
# CORS(app)
invoice_bp = Blueprint('invoice', __name__)

# MODEL_ID = 'gemini-1.5-flash-002'
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY_INVOICE"))

PROMPT_PRECISION = """
Role: Expert Senior Frontend Engineer.
Task: Create a pixel-perfect Tailwind CSS replica of the attached invoice.
Instructions for Images:
- If there is a logo, use an <img src="LOGO_PLACEHOLDER" alt="Logo"> tag.
- If there is a signature, use an <img src="SIGNATURE_PLACEHOLDER" alt="Signature"> tag.
- Do NOT use generic CSS for these; we will replace the placeholders.

Instructions for Templating:
- For dynamic content (customer name, dates, item descriptions, prices, totals), use the format {{fieldName}} instead of the hardcoded text.
- Example: <div class="text-xl font-bold">{{CheckNumber}}</div>

Return ONLY a JSON object: {"full_invoice_html": "<html>...</html>"}
"""

def crop_image_parts(pil_img):
    # We use Gemini to find the boxes for logo and signature specifically
    from google.genai import types
    
    prompt_find_crops = """
    Identify the bounding boxes for 'logo' and 'signature' in this document.
    Return a JSON list of objects: {"field_name": "logo"|"signature", "box_2d": [ymin, xmin, ymax, xmax]}
    """
    
    client_crops = genai.Client(api_key=os.getenv("GEMINI_API_KEY")) # Using main key or similar
    res = client_crops.models.generate_content(
        model=get_model_for_process('invoice'),
        contents=[prompt_find_crops, pil_img],
        config={'response_mime_type': 'application/json'}
    )
    
    try:
        items = json.loads(res.text.strip())
    except:
        return {}

    crops = {}
    width, height = pil_img.size
    for item in items:
        name = item.get('field_name')
        box = item.get('box_2d')
        if name and box:
            ymin, xmin, ymax, xmax = box
            left, top = (xmin * width) / 1000, (ymin * height) / 1000
            right, bottom = (xmax * width) / 1000, (ymax * height) / 1000
            
            # Add padding
            p = 10
            cropped = pil_img.crop((max(0, left-p), max(0, top-p), min(width, right+p), min(height, bottom+p)))
            
            buffered = io.BytesIO()
            cropped.convert("RGB").save(buffered, format="PNG")
            crops[name] = base64.b64encode(buffered.getvalue()).decode()
            
    return crops

@invoice_bp.route('/replicate-invoice', methods=['POST'])
def replicate_invoice():
    model_id = get_model_for_process('invoice')
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
            model=model_id,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0
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

        # Now handle the crops and replacement
        pil_img_full = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")
        crops = crop_image_parts(pil_img_full)
        
        if 'logo' in crops:
            html_content = html_content.replace('LOGO_PLACEHOLDER', f"data:image/png;base64,{crops['logo']}")
        if 'signature' in crops:
            html_content = html_content.replace('SIGNATURE_PLACEHOLDER', f"data:image/png;base64,{crops['signature']}")

        # --- MAPPING FOR PREVIEW ---
        preview_html = html_content
        try:
            analysis_prompt = "Return JSON list of {'field_name': '...', 'value': '...'}"
            analysis_res = client.models.generate_content(
                model=model_id,
                contents=[analysis_prompt, pil_img_full],
                config={'response_mime_type': 'application/json'}
            )
            field_data = json.loads(analysis_res.text.strip())
            for item in field_data:
                placeholder = "{{" + item['field_name'] + "}}"
                if item['value']:
                    preview_html = preview_html.replace(placeholder, str(item['value']))
        except Exception as map_err:
            print(f"Mapping Error: {map_err}")

        return jsonify({
            "status": "success",
            "full_html": html_content,      # Templated HTML
            "preview_html": preview_html    # Filled HTML for preview
        })

    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")
        return jsonify({"error": str(e)}), 500

# if __name__ == '__main__':
#     app.run(port=5052, debug=False, threaded=True)