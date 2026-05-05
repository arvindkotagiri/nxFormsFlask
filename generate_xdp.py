import os, io, json, re, PIL.Image
import fitz  # PyMuPDF
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from flask import Blueprint
from llm_utils import call_llm

load_dotenv()
xdp_bp = Blueprint('xdp', __name__)

PROMPT_XDP = """
Role: Expert Adobe Forms Architect.

Task: Convert the attached document image into a valid, well-structured Adobe XDP (XML Data Package) file using XFA (XML Forms Architecture).

Instructions:
1. Identify all labels, fields (static and dynamic), and layout structures (containers, subforms) from the image.
2. Ensure logical grouping of fields into subforms based on the visual layout.
3. Use descriptive names for fields (snake_case or camelCase).
4. TEMPLATING: For dynamic data, use the format {{field_name}} (e.g., {{customer_name}}) clearly in the structure instead of hardcoded values.
5. Identify 'brand_logo' [ymin, xmin, ymax, xmax].
6. Identify 'containers' (all shaded bars, borders, or text boxes) [ymin, xmin, ymax, xmax].
7. Extract all text elements with [ymin, xmin, ymax, xmax]. IMPORTANT: For table headers, provide a wide x-range to prevent text wrapping. If text is part of the brand_logo graphic, do not include it in text_elements.
8. Maintain the pixel perfect coordinates of elements like boxes, text elements same as the source document.
9. Generate the XDP XML structure including <template>, <subform>, and field definitions (<field>).
10. Provide a summary of all the Data fields and tables to support building the data provider program.

Return ONLY a JSON object: {
    "xdp_code": "<?xml...<xdp>...</xdp>",
    "data_summary": "Summary of fields and tables..."
}
"""

@xdp_bp.route('/generate-xdp', methods=['POST'])
def generate_xdp():
    print("\n[BACKEND] --- STARTING XDP ARCHITECTURE GENERATION ---")
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

        # Generate XDP
        raw_response = call_llm(
            process_name='xdp',
            prompt=PROMPT_XDP,
            image_bytes=img_bytes,
            response_mime_type="application/json"
        )
        data = json.loads(raw_response)
        xdp_code = data.get('xdp_code', '')

        if not xdp_code:
            return jsonify({"error": "No XDP code found", "raw": raw_response}), 500

        # Mapping for preview
        preview_xdp = xdp_code
        layout_preview = []
        try:
            # Parse XDP to extract fields and coordinates for a "Ghost Preview"
            # Remove namespaces for easier parsing
            xml_no_ns = re.sub(r' xmlns(:[a-z0-9]+)?="[^"]+"', '', xdp_code)
            root = ET.fromstring(xml_no_ns)
            for field in root.findall('.//field'):
                layout_preview.append({
                    "name": field.get('name'),
                    "x": field.get('x', '0'),
                    "y": field.get('y', '0'),
                    "w": field.get('w', '0'),
                    "h": field.get('h', '0')
                })
        except Exception as p_err:
            print(f"XDP Parse Error for Preview: {p_err}")

        try:
            analysis_prompt = "Return JSON list of {'field_name': '...', 'value': '...'}"
            analysis_res = call_llm(process_name='xdp', prompt=analysis_prompt, image_bytes=img_bytes, response_mime_type="application/json")
            field_data = json.loads(analysis_res)
            if isinstance(field_data, dict) and "fields" in field_data: field_data = field_data["fields"]
            
            for item in field_data:
                placeholder = "{{" + item['field_name'] + "}}"
                if item['value']:
                    preview_xdp = preview_xdp.replace(placeholder, str(item['value']))
        except Exception as map_err:
            print(f"Mapping Error (XDP): {map_err}")

        print("[BACKEND] --- XDP GENERATION COMPLETE ---")
        return jsonify({
            "status": "success",
            "xdp_code": xdp_code,
            "preview_xdp": preview_xdp,
            "layout_preview": layout_preview,
            "data_summary": data.get('data_summary', '')
        })

    except Exception as e:
        print(f"CRITICAL ERROR (XDP): {str(e)}")
        return jsonify({"error": str(e)}), 500
