import os, re, base64, requests, io, json
import PIL.Image
import fitz  # PyMuPDF
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from flask import Blueprint
from llm_utils import call_llm

load_dotenv()
zpl_bp = Blueprint('zpl', __name__)

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

        if filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(3, 3)) 
            llm_img_bytes = pix.tobytes("jpeg")
            pil_img = PIL.Image.open(io.BytesIO(llm_img_bytes)).convert("RGB")
            doc.close()
        else:
            pil_img = PIL.Image.open(io.BytesIO(file_bytes)).convert("RGB")
            llm_img_bytes = file_bytes

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
        8. TEMPLATING: Find dynamic fields (like names, dates, amounts, address). 
           - Use the format {{field_name}} in the ZPL for these dynamic parts.
           - For example: ^FD{{customer_name}}^FS
        """

        def get_zpl_graphic(pil_img):
            pil_img = pil_img.convert("1")
            width, height = pil_img.size
            width_bytes = (width + 7) // 8
            total_bytes = width_bytes * height
            hex_data = pil_img.tobytes().hex().upper()
            return f"^GFA,{total_bytes},{total_bytes},{width_bytes},{hex_data}"

        def crop_parts(pil_img, img_bytes):
            prompt_find = "Return JSON list of objects: {'field_name': 'logo'|'signature', 'box_2d': [ymin, xmin, ymax, xmax]}"
            try:
                res = call_llm(process_name='zpl', prompt=prompt_find, image_bytes=img_bytes, response_mime_type="application/json")
                items = json.loads(res)
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

        # Generate ZPL
        raw_zpl = call_llm(process_name='zpl', prompt=zpl_prompt, image_bytes=llm_img_bytes, response_mime_type="text/plain")
        zpl_code = clean_zpl(raw_zpl)
        
        if not zpl_code:
            return jsonify({"error": "AI failed to generate ZPL"}), 500

        # Replace placeholders
        crops_zpl = crop_parts(pil_img, llm_img_bytes)
        if 'logo' in crops_zpl:
            zpl_code = zpl_code.replace('^GF_LOGO_PLACEHOLDER', crops_zpl['logo'])
        else:
            zpl_code = zpl_code.replace('^GF_LOGO_PLACEHOLDER', '')
            
        if 'signature' in crops_zpl:
            zpl_code = zpl_code.replace('^GF_SIGNATURE_PLACEHOLDER', crops_zpl['signature'])
        else:
            zpl_code = zpl_code.replace('^GF_SIGNATURE_PLACEHOLDER', '')

        # Preview mapping
        preview_zpl = zpl_code
        try:
            analysis_prompt = "Return JSON list of {'field_name': '...', 'value': '...'}"
            analysis_res = call_llm(process_name='zpl', prompt=analysis_prompt, image_bytes=llm_img_bytes, response_mime_type="application/json")
            field_data = json.loads(analysis_res)
            # Handle potential nested lists
            if isinstance(field_data, dict) and "fields" in field_data: field_data = field_data["fields"]
            
            for item in field_data:
                placeholder = "{{" + item['field_name'] + "}}"
                if item['value']:
                    preview_zpl = preview_zpl.replace(placeholder, str(item['value']))
        except Exception as map_err:
            print(f"Mapping Error (ZPL): {map_err}")

        preview_b64 = get_labelary_preview(preview_zpl, width_in, height_in, dpmm)

        return jsonify({
            "status": "success",
            "zpl_code": zpl_code,
            "labelary_preview": f"data:image/png;base64,{preview_b64}" if preview_b64 else None,
            "preview_zpl": preview_zpl
        })

    except Exception as e:
        print(f"Server Error (ZPL): {str(e)}")
        return jsonify({"error": str(e)}), 500