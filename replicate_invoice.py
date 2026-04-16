import os, io, json, re, PIL.Image, base64
import fitz  # PyMuPDF
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from flask import Blueprint
from llm_utils import call_llm

load_dotenv()
invoice_bp = Blueprint('invoice', __name__)

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

def crop_image_parts(pil_img, img_bytes):
    prompt_find_crops = """
    Identify the bounding boxes for 'logo' and 'signature' in this document.
    Return a JSON list of objects: {"field_name": "logo"|"signature", "box_2d": [ymin, xmin, ymax, xmax]}
    """
    try:
        res = call_llm(process_name='invoice', prompt=prompt_find_crops, image_bytes=img_bytes, response_mime_type="application/json")
        items = json.loads(res)
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
            
            p = 10
            cropped = pil_img.crop((max(0, left-p), max(0, top-p), min(width, right+p), min(height, bottom+p)))
            
            buffered = io.BytesIO()
            cropped.convert("RGB").save(buffered, format="PNG")
            crops[name] = base64.b64encode(buffered.getvalue()).decode()
            
    return crops

@invoice_bp.route('/replicate-invoice', methods=['POST'])
def replicate_invoice():
    if 'image' not in request.files: return jsonify({"error": "No file"}), 400
    try:
        file = request.files['image']
        file_bytes = file.read()
        filename = file.filename.lower()

        if filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(3, 3)) 
            img_bytes = pix.tobytes("jpeg")
            doc.close()
        else:
            img_byte_arr = io.BytesIO()
            PIL.Image.open(io.BytesIO(file_bytes)).convert("RGB").save(img_byte_arr, format='JPEG')
            img_bytes = img_byte_arr.getvalue()

        # Generate HTML
        raw_response = call_llm(
            process_name='invoice',
            prompt=PROMPT_PRECISION,
            image_bytes=img_bytes,
            response_mime_type="application/json"
        )
        data = json.loads(raw_response)

        if isinstance(data, list): html_content = data[0].get('full_invoice_html', '')
        else: html_content = data.get('full_invoice_html', '')

        if not html_content:
            return jsonify({"error": "No HTML found", "raw": raw_response}), 500

        # Handle crops
        pil_img_full = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")
        crops = crop_image_parts(pil_img_full, img_bytes)
        
        if 'logo' in crops:
            html_content = html_content.replace('LOGO_PLACEHOLDER', f"data:image/png;base64,{crops['logo']}")
        if 'signature' in crops:
            html_content = html_content.replace('SIGNATURE_PLACEHOLDER', f"data:image/png;base64,{crops['signature']}")

        # Mapping for preview
        preview_html = html_content
        try:
            analysis_prompt = "Return JSON list of {'field_name': '...', 'value': '...'}"
            analysis_res = call_llm(process_name='invoice', prompt=analysis_prompt, image_bytes=img_bytes, response_mime_type="application/json")
            field_data = json.loads(analysis_res)
            if isinstance(field_data, dict) and "fields" in field_data: field_data = field_data["fields"]
            
            for item in field_data:
                placeholder = "{{" + item['field_name'] + "}}"
                if item['value']:
                    preview_html = preview_html.replace(placeholder, str(item['value']))
        except Exception as map_err:
            print(f"Mapping Error (Invoice): {map_err}")

        return jsonify({
            "status": "success",
            "full_html": html_content,
            "preview_html": preview_html
        })

    except Exception as e:
        print(f"CRITICAL ERROR (Invoice): {str(e)}")
        return jsonify({"error": str(e)}), 500