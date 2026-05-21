import os, io, json, re, PIL.Image, base64
import fitz  # PyMuPDF
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from flask import Blueprint
from llm_utils import call_llm

load_dotenv()
print("[RELOAD] replicate_invoice.py blueprint loaded", flush=True)

invoice_bp = Blueprint('invoice', __name__)

PROMPT_PRECISION = """
Role: Expert Screenshot-to-Code Engineer.
Task: Generate a PIXEL-PERFECT HTML replica of the attached image.

STRICT REQUIREMENTS:
1. DIMENSIONS: Use a fixed container of 816px (width) by 1056px (height). This is exactly 8.5in x 11in at 96DPI.
2. POSITIONING: Every single element (text, line, image) MUST use `position: absolute`.
3. COORDINATES: Use `px` values for `top`, `left`, `width`, `height`, `font-size`, and `line-height`. Do NOT use percentages.
4. STYLING: Use Tailwind CSS classes where possible, but use inline `style="..."` for precise pixel positioning and dimensions.
5. FONT ACCURACY: Match the font weight and size exactly. If a text is 12px and bold, use `text-[12px] font-bold`.
6. BORDERS & LINES: Horizontal and vertical lines must be 1px or 2px divs with a background color that matches the document.
7. ASSETS: 
   - <img src="LOGO_PLACEHOLDER" style="position: absolute; ...">
   - <img src="SIGNATURE_PLACEHOLDER" style="position: absolute; ...">

TEMPLATE FIELDS:
Replace all dynamic text with {{fieldName}} while keeping the exact position and style of the original text.

EXECUTION:
- Imagine a grid of 816x1056 pixels over the image.
- Map every visual element to its exact X/Y coordinate.
- The output must pass a visual overlay test.

Return ONLY a JSON object: {"full_invoice_html": "<div style='position: relative; width: 816px; height: 1056px; background: white;'>...</div>"}
"""

def strip_html_wrappers(html):
    """Clean the HTML for injection while preserving the core structure."""
    # Remove everything outside the main container if the LLM provided a full document
    match = re.search(r'<div.*?>.*</div>', html, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(0)
    
    # Fallback: just strip the obvious wrappers
    html = re.sub(r'<(?:html|body|!doctype|head)[^>]*>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'</(?:html|body|head)>', '', html, flags=re.IGNORECASE)
    return html.strip()

def crop_image_parts(pil_img, img_bytes):
    prompt_find_crops = """
    Identify the bounding boxes for 'logo' and 'signature' in this document.
    Return a JSON list of objects: {"field_name": "logo"|"signature", "box_2d": [ymin, xmin, ymax, xmax]}
    """
    try:
        res = call_llm(process_name='invoice', prompt=prompt_find_crops, image_bytes=img_bytes, response_mime_type="application/json")
        items = json.loads(res)
    except Exception as e:
        print(f"[WARNING] crop_image_parts LLM call or JSON parsing failed: {e}", flush=True)
        return {}

    crops = {}
    width, height = pil_img.size
    
    if not isinstance(items, list):
        print(f"[WARNING] Expected items list in crop_image_parts, got: {type(items)}", flush=True)
        return {}

    for item in items:
        try:
            if not isinstance(item, dict):
                continue
            name = item.get('field_name')
            box = item.get('box_2d')
            if name and box:
                # Normalize nesting (e.g. [[ymin, xmin, ymax, xmax]] to [ymin, xmin, ymax, xmax])
                if isinstance(box, list) and len(box) == 1 and isinstance(box[0], list):
                    box = box[0]

                if not isinstance(box, (list, tuple)) or len(box) != 4:
                    print(f"[WARNING] Invalid crop box for '{name}': {box}", flush=True)
                    continue

                ymin, xmin, ymax, xmax = box
                
                # Convert to floats and validate
                try:
                    ymin, xmin, ymax, xmax = float(ymin), float(xmin), float(ymax), float(xmax)
                except (ValueError, TypeError):
                    print(f"[WARNING] Crop box coordinates are not numeric for '{name}': {box}", flush=True)
                    continue

                left, top = (xmin * width) / 1000, (ymin * height) / 1000
                right, bottom = (xmax * width) / 1000, (ymax * height) / 1000
                
                p = 10
                cropped = pil_img.crop((max(0, left-p), max(0, top-p), min(width, right+p), min(height, bottom+p)))
                
                buffered = io.BytesIO()
                cropped.convert("RGB").save(buffered, format="PNG")
                crops[name] = base64.b64encode(buffered.getvalue()).decode()
        except Exception as item_err:
            print(f"[WARNING] Error processing item crop '{item}': {item_err}", flush=True)
            
    return crops

@invoice_bp.route('/replicate-invoice', methods=['POST'])
def replicate_invoice():
    print("\n" + "="*50, flush=True)
    print("[BACKEND] --- REPLICA GENERATION (HTML) INITIATED ---", flush=True)
    print("="*50, flush=True)
    
    if 'image' not in request.files: 
        print("[ERROR] No image file found in request", flush=True)
        return jsonify({"error": "No file"}), 400
        
    try:
        file = request.files['image']
        file_bytes = file.read()
        filename = file.filename.lower()
        print(f"[INFO] Processing file: {filename} ({len(file_bytes)} bytes)", flush=True)

        if filename.endswith('.pdf'):
            print("[INFO] Converting PDF to image...", flush=True)
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(3, 3)) 
            img_bytes = pix.tobytes("jpeg")
            doc.close()
            print("[SUCCESS] PDF converted to JPEG", flush=True)
        else:
            print("[INFO] Processing image file...", flush=True)
            img_byte_arr = io.BytesIO()
            PIL.Image.open(io.BytesIO(file_bytes)).convert("RGB").save(img_byte_arr, format='JPEG')
            img_bytes = img_byte_arr.getvalue()
            print("[SUCCESS] Image prepared for LLM", flush=True)

        # Generate HTML
        print("[INFO] Sending request to LLM (Pixel-Perfect Replica)...", flush=True)
        raw_response = call_llm(
            process_name='invoice',
            prompt=PROMPT_PRECISION,
            image_bytes=img_bytes,
            response_mime_type="application/json"
        )
        print("[SUCCESS] Received response from LLM", flush=True)
        
        try:
            data = json.loads(raw_response)
        except Exception as json_err:
            print(f"[ERROR] Failed to parse LLM JSON response: {json_err}", flush=True)
            print(f"[DEBUG] Raw response: {raw_response[:500]}...", flush=True)
            return jsonify({"error": "Invalid JSON from LLM", "raw": raw_response}), 500

        if isinstance(data, list): html_content = data[0].get('full_invoice_html', '')
        else: html_content = data.get('full_invoice_html', '')

        if not html_content:
            print("[ERROR] LLM returned JSON but 'full_invoice_html' is missing or empty", flush=True)
            return jsonify({"error": "No HTML found in LLM response", "raw": raw_response}), 500

        # Strip any accidental HTML wrappers from LLM
        html_content = strip_html_wrappers(html_content)

        print(f"[INFO] Generated HTML size: {len(html_content)} characters", flush=True)

        # Handle crops
        print("[INFO] Processing logo and signature assets...", flush=True)
        logo_b64 = request.form.get('logo_b64')
        signature_b64 = request.form.get('signature_b64')
        
        if logo_b64: print("[INFO] Using provided logo from frontend", flush=True)
        if signature_b64: print("[INFO] Using provided signature from frontend", flush=True)
        
        # Only call crop_image_parts if we don't have them from frontend
        if not logo_b64 or not signature_b64:
            print("[INFO] Missing assets from frontend, attempting backend cropping...", flush=True)
            pil_img_full = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")
            backend_crops = crop_image_parts(pil_img_full, img_bytes)
            if not logo_b64: 
                logo_b64 = backend_crops.get('logo')
                if logo_b64: print("[SUCCESS] Backend found logo", flush=True)
            if not signature_b64: 
                signature_b64 = backend_crops.get('signature')
                if signature_b64: print("[SUCCESS] Backend found signature", flush=True)
        
        if logo_b64:
            if logo_b64.startswith('data:'): logo_b64 = logo_b64.split(',')[1]
            html_content = html_content.replace('LOGO_PLACEHOLDER', f"data:image/png;base64,{logo_b64}")
        if signature_b64:
            if signature_b64.startswith('data:'): signature_b64 = signature_b64.split(',')[1]
            html_content = html_content.replace('SIGNATURE_PLACEHOLDER', f"data:image/png;base64,{signature_b64}")

        # Mapping for preview
        print("[INFO] Generating preview with sample values...", flush=True)
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
            print("[SUCCESS] Preview mapping complete", flush=True)
        except Exception as map_err:
            print(f"[WARNING] Preview mapping failed: {map_err}", flush=True)

        print("="*50, flush=True)
        print("[BACKEND] --- REPLICA GENERATION COMPLETE ---", flush=True)
        print("="*50 + "\n", flush=True)
        
        return jsonify({
            "status": "success",
            "full_html": html_content,
            "preview_html": preview_html
        })

    except Exception as e:
        print(f"\n[CRITICAL ERROR] Exception in replicate_invoice: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500