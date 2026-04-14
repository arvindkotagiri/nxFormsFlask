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
2. Generate the XDP XML structure including <template>, <subform>, and field definitions (<field>).
3. Ensure logical grouping of fields into subforms based on the visual layout.
4. Use descriptive names for fields (snake_case or camelCase).
5. For dynamic data, mark it clearly in the structure.
6. Return ONLY a JSON object: {"xdp_code": "<?xml...<xdp>...</xdp>"}
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

        return jsonify({
            "status": "success",
            "xdp_code": xdp_code
        })

    except Exception as e:
        print(f"CRITICAL ERROR (XDP): {str(e)}")
        return jsonify({"error": str(e)}), 500
