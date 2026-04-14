import os, io, json, re, PIL.Image
import fitz  # PyMuPDF
from flask import Flask, request, jsonify
from flask_cors import CORS
from google import genai
from google.genai import types 
from dotenv import load_dotenv
from flask import Blueprint

load_dotenv()
xdp_bp = Blueprint('xdp', __name__)

MODEL_ID = 'gemini-3.1-flash-lite-preview'
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY")) # Using the same key as analyze

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
    if 'image' not in request.files: return jsonify({"error": "No file"}), 400
    try:
        file = request.files['image']
        file_bytes = file.read()
        filename = file.filename.lower()

        # --- PDF TO IMAGE CONVERSION ---
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

        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=PROMPT_XDP),
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

        xdp_code = data.get('xdp_code', '')

        if not xdp_code:
            return jsonify({"error": "No XDP code found", "raw": raw_text}), 500

        # --- MAPPING FOR PREVIEW ---
        preview_xdp = xdp_code
        try:
            pil_img_full = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")
            analysis_prompt = "Return JSON list of {'field_name': '...', 'value': '...'}"
            analysis_res = client.models.generate_content(
                model=MODEL_ID,
                contents=[analysis_prompt, pil_img_full],
                config={'response_mime_type': 'application/json'}
            )
            field_data = json.loads(analysis_res.text.strip())
            for item in field_data:
                placeholder = "{{" + item['field_name'] + "}}"
                if item['value']:
                    preview_xdp = preview_xdp.replace(placeholder, str(item['value']))
        except Exception as map_err:
            print(f"Mapping Error (XDP): {map_err}")

        return jsonify({
            "status": "success",
            "xdp_code": xdp_code,      # Templated XDP
            "preview_xdp": preview_xdp, # Filled XDP for display/debug
            "data_summary": data.get('data_summary', '')
        })

    except Exception as e:
        print(f"CRITICAL ERROR (XDP): {str(e)}")
        return jsonify({"error": str(e)}), 500
