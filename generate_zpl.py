import os, re, base64, requests, io, json
import PIL.Image
import fitz  # PyMuPDF
from flask import Flask, request, jsonify
from flask_cors import CORS
from google import genai
from google.genai import types # Added for Part handling
from dotenv import load_dotenv
from flask import Blueprint
from settings_routes import get_model_for_process

load_dotenv()
# app = Flask(__name__)
# CORS(app)
zpl_bp = Blueprint('zpl', __name__)

# MODEL_ID = 'gemini-1.5-flash-002'
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
    model_id = get_model_for_process('zpl')
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
        6. If there is a LOGO, use the placeholder ^GF_LOGO_PLACEHOLDER.
        7. If there is a SIGNATURE, use the placeholder ^GF_SIGNATURE_PLACEHOLDER.
        8. If there is a LOGO, use the placeholder ^GF_LOGO_PLACEHOLDER.
        9. If there is a SIGNATURE, use the placeholder ^GF_SIGNATURE_PLACEHOLDER.
        10. TEMPLATING (STRICT RULE - DO NOT IGNORE):
            - ANY text that looks like variable data MUST be replaced with placeholders.
            - DO NOT include actual values.
            - Use ONLY placeholders like:
            {{CheckDate}}, {{VendorName}}, {{Amount}}, {{CheckNumber}}, {{AmountInWords}}, {{VendorAddress1}}
            - Example:
            WRONG: ^FDSep/25/2023^FS
            CORRECT: ^FD{{CheckDate}}^FS
        """

        def get_zpl_graphic(pil_img):
            """Converts a PIL image to ZPL ^GF format."""
            # Convert to 1-bit black and white (dithered)
            pil_img = pil_img.convert("1")
            width, height = pil_img.size
            
            # Width in bytes (must be multiple of 8 bits)
            width_bytes = (width + 7) // 8
            total_bytes = width_bytes * height
            
            # Convert to hex
            hex_data = pil_img.tobytes().hex().upper()
            
            return f"^GFA,{total_bytes},{total_bytes},{width_bytes},{hex_data}"

        def crop_parts(pil_img):
            prompt_find = "Return JSON list of objects: {'field_name': 'logo'|'signature', 'box_2d': [ymin, xmin, ymax, xmax]}"
            res = client.models.generate_content(
                model=model_id,
                contents=[prompt_find, pil_img],
                config={'response_mime_type': 'application/json'}
            )
            try:
                items = json.loads(res.text.strip())
                crops = {}
                w, h = pil_img.size
                for it in items:
                    box = it.get('box_2d')
                    if box:
                        ymin, xmin, ymax, xmax = box
                        left, top = (xmin * w) / 1000, (ymin * h) / 1000
                        right, bottom = (xmax * w) / 1000, (ymax * h) / 1000
                        crop = pil_img.crop((left, top, right, bottom))
                        crops[it['field_name']] = get_zpl_graphic(crop)
                return crops
            except: return {}

        # Generate content using the image (either original or converted from PDF)
        response = client.models.generate_content(
            model=model_id,
            contents=[zpl_prompt, pil_img]
        )
        
        zpl_code = clean_zpl(response.text)
        
        if not zpl_code:
            return jsonify({"error": "Gemini failed to generate ZPL"}), 500

        # Replace placeholders
        crops_zpl = crop_parts(pil_img)
        if 'logo' in crops_zpl:
            zpl_code = zpl_code.replace('^GF_LOGO_PLACEHOLDER', crops_zpl['logo'])
        else:
            zpl_code = zpl_code.replace('^GF_LOGO_PLACEHOLDER', '')
            
        if 'signature' in crops_zpl:
            zpl_code = zpl_code.replace('^GF_SIGNATURE_PLACEHOLDER', crops_zpl['signature'])
        else:
            zpl_code = zpl_code.replace('^GF_SIGNATURE_PLACEHOLDER', '')

        # --- MAPPING FOR PREVIEW ---
        # We need the original values to show a real preview
        preview_zpl = zpl_code
        try:
            analysis_prompt = "Return JSON list of {'field_name': '...', 'value': '...'}"
            analysis_res = client.models.generate_content(
                model=model_id,
                contents=[analysis_prompt, pil_img],
                config={'response_mime_type': 'application/json'}
            )
            field_data = json.loads(analysis_res.text.strip())
            for item in field_data:
                placeholder = "{{" + item['field_name'] + "}}"
                if item['value']:
                    preview_zpl = preview_zpl.replace(placeholder, str(item['value']))
        except Exception as map_err:
            print(f"Mapping Error: {map_err}")

        preview_b64 = get_labelary_preview(preview_zpl, width_in, height_in, dpmm)

        return jsonify({
            "status": "success",
            "zpl_code": zpl_code, # This contains templates {{...}}
            "labelary_preview": f"data:image/png;base64,{preview_b64}" if preview_b64 else None,
            "preview_zpl": preview_zpl # For debug/display if needed
        })

    except Exception as e:
        print(f"Server Error: {str(e)}")
        return jsonify({"error": str(e)}), 500

# if __name__ == '__main__':
#     app.run(port=5051, debug=False, threaded=True)