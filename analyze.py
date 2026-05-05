import os, io, re, json, base64
import PIL.Image, PIL.ImageDraw
import fitz  # PyMuPDF
from flask import Blueprint, request, jsonify
from dotenv import load_dotenv
from llm_utils import call_llm

load_dotenv()
analyze_bp = Blueprint('analyze', __name__)

PROMPT_ANALYSIS = """
Analyze this document with extreme precision. 

Return a JSON list of objects. Each object must have:
1. "field_name": snake_case name (e.g., logo, signature, company_name, total_amount).
2. "category": 'static' or 'dynamic'.
3. "content_type": 'text', 'barcode', 'qrcode', 'table', 'logo', or 'signature'.
4. "box_2d": [ymin, xmin, ymax, xmax] coordinates.
5. "value": The original text/content seen in the image for this field.

CRITICAL:
- If you see a logo, identify it as "content_type": "logo".
- If you see a signature, identify it as "content_type": "signature".

CRITICAL INSTRUCTIONS FOR TABLES:
- If a table is present, create ONE object with "content_type": "table".
- The "box_2d" must encompass the ENTIRE table area.
- Inside this object, add "table_data": a list of rows.
- Each row MUST be a LIST of cell objects (consistent column order).
- Each cell: {"value": "the_text", "category": "static" or "dynamic"}
"""

def get_annotated_base64(pil_img, extracted_data):
    overlay = PIL.Image.new('RGBA', pil_img.size, (255, 255, 255, 0))
    draw = PIL.ImageDraw.Draw(overlay)
    width, height = pil_img.size

    for item in extracted_data:
        if 'box_2d' not in item: continue
        ymin, xmin, ymax, xmax = item['box_2d']
        left, top = (xmin * width) / 1000, (ymin * height) / 1000
        right, bottom = (xmax * width) / 1000, (ymax * height) / 1000

        is_table = item.get('content_type') == 'table'
        border_col = (34, 197, 94, 255) if is_table else (37, 99, 235, 255)
        fill_col = (34, 197, 94, 40) if is_table else (37, 99, 235, 40)

        draw.rectangle([left, top, right, bottom], fill=fill_col, outline=border_col, width=4)
        
        display_text = item.get('field_name', 'Field').upper()
        tag_w = len(display_text) * 10 + 12
        tag_top = max(0, top - 28)
        draw.rectangle([left, tag_top, left + tag_w, tag_top + 28], fill=border_col)
        draw.text((left + 6, tag_top + 6), display_text, fill=(255, 255, 255))

    combined = PIL.Image.alpha_composite(pil_img.convert("RGBA"), overlay)
    buffered = io.BytesIO()
    combined.convert("RGB").save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()

def crop_and_save(pil_img, box_2d, field_name):
    width, height = pil_img.size
    ymin, xmin, ymax, xmax = box_2d
    left, top = (xmin * width) / 1000, (ymin * height) / 1000
    right, bottom = (xmax * width) / 1000, (ymax * height) / 1000
    
    padding = 5
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(width, right + padding)
    bottom = min(height, bottom + padding)
    
    cropped = pil_img.crop((left, top, right, bottom))
    
    if not os.path.exists('static/temp'):
        os.makedirs('static/temp')
        
    filename = f"{field_name}_{os.urandom(4).hex()}.png"
    filepath = os.path.join('static/temp', filename)
    cropped.save(filepath)
    
    buffered = io.BytesIO()
    cropped.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    
    return filepath, f"data:image/png;base64,{img_str}"

@analyze_bp.route('/analyze-label', methods=['POST'])
def analyze_label():
    print("\n[BACKEND] --- STARTING LABEL ANALYSIS ---")
    if 'image' not in request.files: 
        return jsonify({"error": "No file"}), 400
    try:
        file = request.files['image']
        file_bytes = file.read()
        filename = file.filename.lower()

        if filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            page = doc.load_page(0)  
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_data = pix.tobytes("png")
            pil_img = PIL.Image.open(io.BytesIO(img_data)).convert("RGB")
            doc.close()
            llm_img_bytes = img_data
        else:
            pil_img = PIL.Image.open(io.BytesIO(file_bytes)).convert("RGB")
            llm_img_bytes = file_bytes

        # --- Generate Content using Unified LLM Caller ---
        raw_response = call_llm(
            process_name='analyze',
            prompt=PROMPT_ANALYSIS,
            image_bytes=llm_img_bytes,
            response_mime_type="application/json"
        )
        
        extracted_data = json.loads(raw_response)
        
        # In case the model returns the list direct or in a wrapper
        if isinstance(extracted_data, dict) and "fields" in extracted_data:
            extracted_data = extracted_data["fields"]
        elif isinstance(extracted_data, dict) and "data" in extracted_data:
            extracted_data = extracted_data["data"]

        for item in extracted_data:
            if item.get('content_type') in ['logo', 'signature']:
                try:
                    filepath, b64_data = crop_and_save(pil_img, item['box_2d'], item['content_type'])
                    item['cropped_path'] = filepath
                    item['cropped_b64'] = b64_data
                except Exception as crop_err:
                    print(f"Crop Error: {crop_err}")

        annotated_b64 = get_annotated_base64(pil_img.copy(), extracted_data)

        clean_buffered = io.BytesIO()
        pil_img.save(clean_buffered, format="PNG")
        clean_b64 = base64.b64encode(clean_buffered.getvalue()).decode()

        print("[BACKEND] --- ANALYSIS COMPLETE ---")
        return jsonify({
            "status": "success",
            "extracted_fields": extracted_data,
            "annotated_image": f"data:image/png;base64,{annotated_b64}",
            "clean_image": f"data:image/png;base64,{clean_b64}"
        })
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500