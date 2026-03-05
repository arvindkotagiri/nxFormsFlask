# import os, io, re, json, base64
# import PIL.Image, PIL.ImageDraw
# import fitz  # PyMuPDF
# from flask import Flask, request, jsonify
# from flask_cors import CORS
# from google import genai
# from google.genai import types 
# from dotenv import load_dotenv
# from flask import Blueprint

# load_dotenv()
# # app = Flask(__name__)
# # CORS(app)
# analyze_bp = Blueprint('analyze', __name__)

# # --- CONFIGURATION ---
# MODEL_ID = 'gemini-3-flash-preview' 
# client = genai.Client(api_key=os.getenv("GEMINI_API_KEY_ANNOTATE"))

# PROMPT_ANALYSIS = """
# Analyze this document with extreme precision. 

# Return a JSON list of objects. Each object must have:
# 1. "field_name": snake_case name.
# 2. "category": 'static' or 'dynamic'.
# 3. "content_type": 'text', 'barcode', 'qrcode', or 'table'.
# 4. "box_2d": [ymin, xmin, ymax, xmax] coordinates.

# CRITICAL INSTRUCTIONS FOR TABLES:
# - If a table is present, create ONE object with "content_type": "table".
# - The "box_2d" must encompass the ENTIRE table area.
# - Inside this object, add "table_data": a list of rows.
# - Each row should be an object where each cell is another object containing:
#   {"value": "the_text", "category": "static" or "dynamic"}
# """

# def get_annotated_base64(pil_img, extracted_data):
#     overlay = PIL.Image.new('RGBA', pil_img.size, (255, 255, 255, 0))
#     draw = PIL.ImageDraw.Draw(overlay)
#     width, height = pil_img.size

#     for item in extracted_data:
#         if 'box_2d' not in item: continue
#         ymin, xmin, ymax, xmax = item['box_2d']
#         left, top = (xmin * width) / 1000, (ymin * height) / 1000
#         right, bottom = (xmax * width) / 1000, (ymax * height) / 1000

#         is_table = item.get('content_type') == 'table'
#         border_col = (34, 197, 94, 255) if is_table else (37, 99, 235, 255)
#         fill_col = (34, 197, 94, 40) if is_table else (37, 99, 235, 40)

#         draw.rectangle([left, top, right, bottom], fill=fill_col, outline=border_col, width=4)
        
#         display_text = item.get('field_name', 'Field').upper()
#         tag_w = len(display_text) * 10 + 12
#         tag_top = max(0, top - 28)
#         draw.rectangle([left, tag_top, left + tag_w, tag_top + 28], fill=border_col)
#         draw.text((left + 6, tag_top + 6), display_text, fill=(255, 255, 255))

#     combined = PIL.Image.alpha_composite(pil_img.convert("RGBA"), overlay)
#     buffered = io.BytesIO()
#     combined.convert("RGB").save(buffered, format="PNG")
#     return base64.b64encode(buffered.getvalue()).decode()

# @analyze_bp.route('/analyze-label', methods=['POST'])
# def analyze_label():
#     if 'image' not in request.files: return jsonify({"error": "No file"}), 400
#     try:
#         file = request.files['image']
#         file_bytes = file.read()
#         filename = file.filename.lower()

#         if filename.endswith('.pdf'):
#             # --- PyMuPDF conversion (No Poppler Required) ---
#             doc = fitz.open(stream=file_bytes, filetype="pdf")
#             page = doc.load_page(0)  
#             pix = page.get_pixmap(matrix=fitz.Matrix(2, 2)) # High-res zoom
#             img_data = pix.tobytes("png")
#             pil_img = PIL.Image.open(io.BytesIO(img_data)).convert("RGB")
#             doc.close()
#             doc_part = types.Part.from_bytes(data=file_bytes, mime_type="application/pdf")
#         else:
#             pil_img = PIL.Image.open(io.BytesIO(file_bytes)).convert("RGB")
#             doc_part = types.Part.from_bytes(data=file_bytes, mime_type="image/jpeg")

#         response = client.models.generate_content(
#             model=MODEL_ID, 
#             contents=[PROMPT_ANALYSIS, doc_part],
#             config={'response_mime_type': 'application/json'}
#         )
        
#         extracted_data = json.loads(response.text.strip())
#         annotated_b64 = get_annotated_base64(pil_img.copy(), extracted_data)

#         # Generate clean base64 reference for frontend display (crucial for PDFs)
#         clean_buffered = io.BytesIO()
#         pil_img.save(clean_buffered, format="PNG")
#         clean_b64 = base64.b64encode(clean_buffered.getvalue()).decode()

#         return jsonify({
#             "status": "success",
#             "extracted_fields": extracted_data,
#             "annotated_image": f"data:image/png;base64,{annotated_b64}",
#             "clean_image": f"data:image/png;base64,{clean_b64}"
#         })
#     except Exception as e:
#         print(f"Error: {e}")
#         return jsonify({"error": str(e)}), 500

# # if __name__ == '__main__':

# #     app.run(port=5050, debug=False, threaded=True)


import os
import io
import re
import json
import base64

import PIL.Image
import PIL.ImageDraw
import fitz  # PyMuPDF

from flask import request, jsonify, Blueprint
from flask_cors import CORS

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

analyze_bp = Blueprint("analyze", __name__)
CORS(analyze_bp)

# CONFIG
MODEL_ID = "gemini-2.0-flash"
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY_ANNOTATE"))

PROMPT_ANALYSIS = """
Analyze this document with extreme precision.

Return a JSON list of objects. Each object must have:
1. "field_name": snake_case name.
2. "category": 'static' or 'dynamic'.
3. "content_type": 'text', 'barcode', 'qrcode', or 'table'.
4. "box_2d": [ymin, xmin, ymax, xmax] coordinates.

CRITICAL INSTRUCTIONS FOR TABLES:
- If a table is present, create ONE object with "content_type": "table".
- The "box_2d" must encompass the ENTIRE table area.
- Inside this object, add "table_data": a list of rows.
- Each row should be an object where each cell is another object containing:
  {"value": "the_text", "category": "static" or "dynamic"}
"""


# -------------------------
# Draw annotation boxes
# -------------------------
def get_annotated_base64(pil_img, extracted_data):

    overlay = PIL.Image.new("RGBA", pil_img.size, (255, 255, 255, 0))
    draw = PIL.ImageDraw.Draw(overlay)

    width, height = pil_img.size

    for item in extracted_data:

        if "box_2d" not in item:
            continue

        ymin, xmin, ymax, xmax = item["box_2d"]

        left = (xmin * width) / 1000
        top = (ymin * height) / 1000
        right = (xmax * width) / 1000
        bottom = (ymax * height) / 1000

        is_table = item.get("content_type") == "table"

        border = (34, 197, 94, 255) if is_table else (37, 99, 235, 255)
        fill = (34, 197, 94, 40) if is_table else (37, 99, 235, 40)

        draw.rectangle(
            [left, top, right, bottom],
            fill=fill,
            outline=border,
            width=3,
        )

        label = item.get("field_name", "Field").upper()

        tag_width = len(label) * 9 + 12
        tag_top = max(0, top - 26)

        draw.rectangle(
            [left, tag_top, left + tag_width, tag_top + 24],
            fill=border,
        )

        draw.text(
            (left + 5, tag_top + 5),
            label,
            fill=(255, 255, 255),
        )

    combined = PIL.Image.alpha_composite(pil_img.convert("RGBA"), overlay)

    buf = io.BytesIO()
    combined.convert("RGB").save(buf, format="PNG", optimize=True)

    return base64.b64encode(buf.getvalue()).decode()


# -------------------------
# Convert PDF safely
# -------------------------
def convert_pdf_to_image(file_bytes):

    doc = fitz.open(stream=file_bytes, filetype="pdf")

    page = doc.load_page(0)

    # LOWER resolution to save memory
    pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))

    img_bytes = pix.tobytes("png")

    pil_img = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")

    doc.close()

    return pil_img


# -------------------------
# Main API
# -------------------------
@analyze_bp.route("/analyze-label", methods=["POST"])
def analyze_label():

    if "image" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    try:

        file = request.files["image"]
        file_bytes = file.read()

        filename = file.filename.lower()

        # -------------------------
        # Load image
        # -------------------------
        if filename.endswith(".pdf"):

            pil_img = convert_pdf_to_image(file_bytes)

            doc_part = types.Part.from_bytes(
                data=file_bytes,
                mime_type="application/pdf",
            )

        else:

            pil_img = PIL.Image.open(io.BytesIO(file_bytes)).convert("RGB")

            doc_part = types.Part.from_bytes(
                data=file_bytes,
                mime_type="image/jpeg",
            )

        # -------------------------
        # Resize if very large
        # -------------------------
        max_size = 2000

        if max(pil_img.size) > max_size:
            pil_img.thumbnail((max_size, max_size))

        # -------------------------
        # Gemini call
        # -------------------------
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=[PROMPT_ANALYSIS, doc_part],
            config={"response_mime_type": "application/json"},
        )

        extracted_data = json.loads(response.text.strip())

        # -------------------------
        # Generate annotated image
        # -------------------------
        annotated_b64 = get_annotated_base64(
            pil_img.copy(),
            extracted_data,
        )

        # -------------------------
        # Clean reference image
        # -------------------------
        clean_buf = io.BytesIO()

        pil_img.save(
            clean_buf,
            format="PNG",
            optimize=True,
        )

        clean_b64 = base64.b64encode(clean_buf.getvalue()).decode()

        return jsonify(
            {
                "status": "success",
                "extracted_fields": extracted_data,
                "annotated_image": f"data:image/png;base64,{annotated_b64}",
                "clean_image": f"data:image/png;base64,{clean_b64}",
            }
        )

    except Exception as e:

        print("ANALYZE ERROR:", str(e))

        return jsonify(
            {
                "status": "error",
                "message": str(e),
            }
        ), 500
