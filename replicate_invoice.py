# import os, io, json, re, PIL.Image, base64
# import fitz  # PyMuPDF
# from flask import Flask, request, jsonify
# from flask_cors import CORS
# from dotenv import load_dotenv
# from flask import Blueprint
# from llm_utils import call_llm

# load_dotenv()
# print("[RELOAD] replicate_invoice.py blueprint loaded", flush=True)

# invoice_bp = Blueprint('invoice', __name__)

# PROMPT_PRECISION = """
# Role: Expert Screenshot-to-Code Engineer.
# Task: Generate a PIXEL-PERFECT HTML replica of the attached image.

# STRICT REQUIREMENTS:
# 1. DIMENSIONS: Use a fixed container of 816px (width) by 1056px (height). This is exactly 8.5in x 11in at 96DPI.
# 2. POSITIONING: Every single element (text, line, image) MUST use `position: absolute`.
# 3. COORDINATES: Use `px` values for `top`, `left`, `width`, `height`, `font-size`, and `line-height`. Do NOT use percentages.
# 4. STYLING: Use Tailwind CSS classes where possible, but use inline `style="..."` for precise pixel positioning and dimensions.
# 5. FONT ACCURACY: Match the font weight and size exactly. If a text is 12px and bold, use `text-[12px] font-bold`.
# 6. BORDERS & LINES: Horizontal and vertical lines must be 1px or 2px divs with a background color that matches the document.
# 7. ASSETS: 
#    - <img src="LOGO_PLACEHOLDER" style="position: absolute; ...">
#    - <img src="SIGNATURE_PLACEHOLDER" style="position: absolute; ...">

# TEMPLATE FIELDS:
# Replace all dynamic text with {{fieldName}} while keeping the exact position and style of the original text.

# EXECUTION:
# - Imagine a grid of 816x1056 pixels over the image.
# - Map every visual element to its exact X/Y coordinate.
# - The output must pass a visual overlay test.

# Return ONLY a JSON object: {"full_invoice_html": "<div style='position: relative; width: 816px; height: 1056px; background: white;'>...</div>"}
# """

# def strip_html_wrappers(html):
#     """Clean the HTML for injection while preserving the core structure."""
#     # Remove everything outside the main container if the LLM provided a full document
#     match = re.search(r'<div.*?>.*</div>', html, flags=re.DOTALL | re.IGNORECASE)
#     if match:
#         return match.group(0)
    
#     # Fallback: just strip the obvious wrappers
#     html = re.sub(r'<(?:html|body|!doctype|head)[^>]*>', '', html, flags=re.IGNORECASE)
#     html = re.sub(r'</(?:html|body|head)>', '', html, flags=re.IGNORECASE)
#     return html.strip()

# def crop_image_parts(pil_img, img_bytes):
#     prompt_find_crops = """
#     Identify the bounding boxes for 'logo' and 'signature' in this document.
#     Return a JSON list of objects: {"field_name": "logo"|"signature", "box_2d": [ymin, xmin, ymax, xmax]}
#     """
#     try:
#         res = call_llm(process_name='invoice', prompt=prompt_find_crops, image_bytes=img_bytes, response_mime_type="application/json")
#         items = json.loads(res)
#     except:
#         return {}

#     crops = {}
#     width, height = pil_img.size
#     for item in items:
#         name = item.get('field_name')
#         box = item.get('box_2d')
#         if name and box:
#             ymin, xmin, ymax, xmax = box
#             left, top = (xmin * width) / 1000, (ymin * height) / 1000
#             right, bottom = (xmax * width) / 1000, (ymax * height) / 1000
            
#             p = 10
#             cropped = pil_img.crop((max(0, left-p), max(0, top-p), min(width, right+p), min(height, bottom+p)))
            
#             buffered = io.BytesIO()
#             cropped.convert("RGB").save(buffered, format="PNG")
#             crops[name] = base64.b64encode(buffered.getvalue()).decode()
            
#     return crops

# @invoice_bp.route('/replicate-invoice', methods=['POST'])
# def replicate_invoice():
#     print("\n" + "="*50, flush=True)
#     print("[BACKEND] --- REPLICA GENERATION (HTML) INITIATED ---", flush=True)
#     print("="*50, flush=True)
    
#     if 'image' not in request.files: 
#         print("[ERROR] No image file found in request", flush=True)
#         return jsonify({"error": "No file"}), 400
        
#     try:
#         file = request.files['image']
#         file_bytes = file.read()
#         filename = file.filename.lower()
#         print(f"[INFO] Processing file: {filename} ({len(file_bytes)} bytes)", flush=True)

#         if filename.endswith('.pdf'):
#             print("[INFO] Converting PDF to image...", flush=True)
#             doc = fitz.open(stream=file_bytes, filetype="pdf")
#             page = doc.load_page(0)
#             pix = page.get_pixmap(matrix=fitz.Matrix(3, 3)) 
#             img_bytes = pix.tobytes("jpeg")
#             doc.close()
#             print("[SUCCESS] PDF converted to JPEG", flush=True)
#         else:
#             print("[INFO] Processing image file...", flush=True)
#             img_byte_arr = io.BytesIO()
#             PIL.Image.open(io.BytesIO(file_bytes)).convert("RGB").save(img_byte_arr, format='JPEG')
#             img_bytes = img_byte_arr.getvalue()
#             print("[SUCCESS] Image prepared for LLM", flush=True)

#         # Generate HTML
#         print("[INFO] Sending request to LLM (Pixel-Perfect Replica)...", flush=True)
#         raw_response = call_llm(
#             process_name='invoice',
#             prompt=PROMPT_PRECISION,
#             image_bytes=img_bytes,
#             response_mime_type="application/json"
#         )
#         print("[SUCCESS] Received response from LLM", flush=True)
        
#         try:
#             data = json.loads(raw_response)
#         except Exception as json_err:
#             print(f"[ERROR] Failed to parse LLM JSON response: {json_err}", flush=True)
#             print(f"[DEBUG] Raw response: {raw_response[:500]}...", flush=True)
#             return jsonify({"error": "Invalid JSON from LLM", "raw": raw_response}), 500

#         if isinstance(data, list): html_content = data[0].get('full_invoice_html', '')
#         else: html_content = data.get('full_invoice_html', '')

#         if not html_content:
#             print("[ERROR] LLM returned JSON but 'full_invoice_html' is missing or empty", flush=True)
#             return jsonify({"error": "No HTML found in LLM response", "raw": raw_response}), 500

#         # Strip any accidental HTML wrappers from LLM
#         html_content = strip_html_wrappers(html_content)

#         print(f"[INFO] Generated HTML size: {len(html_content)} characters", flush=True)

#         # Handle crops
#         print("[INFO] Processing logo and signature assets...", flush=True)
#         logo_b64 = request.form.get('logo_b64')
#         signature_b64 = request.form.get('signature_b64')
        
#         if logo_b64: print("[INFO] Using provided logo from frontend", flush=True)
#         if signature_b64: print("[INFO] Using provided signature from frontend", flush=True)
        
#         # Only call crop_image_parts if we don't have them from frontend
#         if not logo_b64 or not signature_b64:
#             print("[INFO] Missing assets from frontend, attempting backend cropping...", flush=True)
#             pil_img_full = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")
#             backend_crops = crop_image_parts(pil_img_full, img_bytes)
#             if not logo_b64: 
#                 logo_b64 = backend_crops.get('logo')
#                 if logo_b64: print("[SUCCESS] Backend found logo", flush=True)
#             if not signature_b64: 
#                 signature_b64 = backend_crops.get('signature')
#                 if signature_b64: print("[SUCCESS] Backend found signature", flush=True)
        
#         if logo_b64:
#             if logo_b64.startswith('data:'): logo_b64 = logo_b64.split(',')[1]
#             html_content = html_content.replace('LOGO_PLACEHOLDER', f"data:image/png;base64,{logo_b64}")
#         if signature_b64:
#             if signature_b64.startswith('data:'): signature_b64 = signature_b64.split(',')[1]
#             html_content = html_content.replace('SIGNATURE_PLACEHOLDER', f"data:image/png;base64,{signature_b64}")

#         # Mapping for preview
#         print("[INFO] Generating preview with sample values...", flush=True)
#         preview_html = html_content
#         try:
#             analysis_prompt = "Return JSON list of {'field_name': '...', 'value': '...'}"
#             analysis_res = call_llm(process_name='invoice', prompt=analysis_prompt, image_bytes=img_bytes, response_mime_type="application/json")
#             field_data = json.loads(analysis_res)
#             if isinstance(field_data, dict) and "fields" in field_data: field_data = field_data["fields"]
            
#             for item in field_data:
#                 placeholder = "{{" + item['field_name'] + "}}"
#                 if item['value']:
#                     preview_html = preview_html.replace(placeholder, str(item['value']))
#             print("[SUCCESS] Preview mapping complete", flush=True)
#         except Exception as map_err:
#             print(f"[WARNING] Preview mapping failed: {map_err}", flush=True)

#         print("="*50, flush=True)
#         print("[BACKEND] --- REPLICA GENERATION COMPLETE ---", flush=True)
#         print("="*50 + "\n", flush=True)
        
#         return jsonify({
#             "status": "success",
#             "full_html": html_content,
#             "preview_html": preview_html
#         })

#     except Exception as e:
#         print(f"\n[CRITICAL ERROR] Exception in replicate_invoice: {str(e)}")
#         import traceback
#         traceback.print_exc()
#         return jsonify({"error": str(e)}), 500

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
    match = re.search(r'<div.*?>.*</div>', html, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(0)
    html = re.sub(r'<(?:html|body|!doctype|head)[^>]*>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'</(?:html|body|head)>', '', html, flags=re.IGNORECASE)
    return html.strip()


def build_placeholder_prompt_block(field_mappings: dict) -> str:
    """
    Build the field placeholder dictionary block to inject into the LLM prompt.

    field_mappings = { "Invoice Number": "Header.BillingDocument", ... }
      key   = the visible text label on the image at that bounding box
      value = the SAP field path the user selected (entity.fieldName)

    Returns a formatted string block to append to PROMPT_PRECISION.
    """
    if not field_mappings:
        return ""

    lines = []
    for label, sap_path in field_mappings.items():
        if not label or not sap_path:
            continue
        # Strip entity prefix: "Header.ShipToParty" → "ShipToParty"
        field_name = sap_path.split('.')[-1] if '.' in sap_path else sap_path
        lines.append(f'  - Text label "{label}" → use placeholder {{{{{field_name}}}}}')

    if not lines:
        return ""

    return (
        "\n\nFIELD PLACEHOLDER DICTIONARY (MANDATORY — DO NOT DEVIATE):\n"
        "The following visible text labels appear in the image. For each one, you MUST use "
        "EXACTLY the placeholder name shown below — do NOT invent your own names, do NOT "
        "paraphrase, do NOT add prefixes or suffixes:\n"
        + "\n".join(lines)
        + "\n\nFor any other dynamic fields not listed above, invent a descriptive {{camelCaseName}}."
    )


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

        is_pdf = filename.endswith('.pdf')
        logo_b64 = request.form.get('logo_b64')
        signature_b64 = request.form.get('signature_b64')

        if is_pdf:
            print("[INFO] Converting PDF to images page by page...", flush=True)
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            num_pages = len(doc)
            print(f"[INFO] PDF has {num_pages} pages.", flush=True)

            page_htmls = []
            preview_fields = []

            for page_idx in range(num_pages):
                print(f"[INFO] Rendering page {page_idx + 1}/{num_pages}...", flush=True)
                page = doc.load_page(page_idx)
                pix = page.get_pixmap(matrix=fitz.Matrix(3, 3)) 
                img_bytes = pix.tobytes("jpeg")

                # Generate HTML for this page
                print(f"[INFO] Sending page {page_idx + 1} request to LLM...", flush=True)
                raw_response = call_llm(
                    process_name='invoice',
                    prompt=PROMPT_PRECISION,
                    image_bytes=img_bytes,
                    response_mime_type="application/json"
                )
                print(f"[SUCCESS] Page {page_idx + 1} replica received", flush=True)

                try:
                    data = json.loads(raw_response)
                except Exception as json_err:
                    print(f"[ERROR] Failed to parse page {page_idx + 1} JSON: {json_err}", flush=True)
                    continue

                if isinstance(data, list):
                    html_content = data[0].get('full_invoice_html', '')
                else:
                    html_content = data.get('full_invoice_html', '')

                if html_content:
                    html_content = strip_html_wrappers(html_content)
                    page_htmls.append((page_idx, html_content, img_bytes))

            doc.close()

            if not page_htmls:
                return jsonify({"error": "Failed to generate HTML for any page"}), 500

            # Combine page blocks into a single wrapper
            combined_html = '<div class="multi-page-container" style="display: flex; flex-direction: column; gap: 20px; background: #f1f5f9; padding: 20px;">'
            for page_idx, p_html, p_img_bytes in page_htmls:
                # Localize replacements for this specific page (like logos/signatures)
                local_html = p_html
                
                # Check for logo/signature crops on this page
                p_logo_b64 = logo_b64
                p_sig_b64 = signature_b64

                if not p_logo_b64 or not p_sig_b64:
                    pil_img_full = PIL.Image.open(io.BytesIO(p_img_bytes)).convert("RGB")
                    backend_crops = crop_image_parts(pil_img_full, p_img_bytes)
                    if not p_logo_b64: p_logo_b64 = backend_crops.get('logo')
                    if not p_sig_b64: p_sig_b64 = backend_crops.get('signature')

                if p_logo_b64:
                    if p_logo_b64.startswith('data:'): p_logo_b64 = p_logo_b64.split(',')[1]
                    local_html = local_html.replace('LOGO_PLACEHOLDER', f"data:image/png;base64,{p_logo_b64}")
                if p_sig_b64:
                    if p_sig_b64.startswith('data:'): p_sig_b64 = p_sig_b64.split(',')[1]
                    local_html = local_html.replace('SIGNATURE_PLACEHOLDER', f"data:image/png;base64,{p_sig_b64}")

                combined_html += f"""
                <div class="pdf-page-wrapper" data-page-index="{page_idx}" style="position: relative; width: 816px; height: 1056px; background: white; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); margin: 0 auto; page-break-after: always;">
                    {local_html}
                </div>
                """
            combined_html += '</div>'

            html_result = combined_html
            preview_html = combined_html

            # Perform preview replacements by calling LLM on the first page
            first_img_bytes = page_htmls[0][2]
            try:
                analysis_prompt = "Return JSON list of {'field_name': '...', 'value': '...'}"
                analysis_res = call_llm(process_name='invoice', prompt=analysis_prompt, image_bytes=first_img_bytes, response_mime_type="application/json")
                field_data = json.loads(analysis_res)
                if isinstance(field_data, dict) and "fields" in field_data: field_data = field_data["fields"]
                
                for item in field_data:
                    placeholder = "{{" + item['field_name'] + "}}"
                    if item['value']:
                        preview_html = preview_html.replace(placeholder, str(item['value']))
            except Exception as map_err:
                print(f"[WARNING] Preview mapping failed on multi-page PDF: {map_err}", flush=True)

        else:
            print("[INFO] Processing image file...", flush=True)
            img_byte_arr = io.BytesIO()
            PIL.Image.open(io.BytesIO(file_bytes)).convert("RGB").save(img_byte_arr, format='JPEG')
            img_bytes = img_byte_arr.getvalue()
            print("[SUCCESS] Image prepared for LLM", flush=True)

        # ── Parse user-defined field mappings from frontend ──────────────────
        # Format: { "BoundingBoxLabel": "Entity.SAPFieldPath" }
        # e.g.  { "Invoice Number": "Header.BillingDocument" }
        raw_mappings = request.form.get('field_mappings', '{}')
        try:
            field_mappings = json.loads(raw_mappings)
            if field_mappings:
                print(f"[INFO] Received {len(field_mappings)} field mapping(s):", flush=True)
                for k, v in field_mappings.items():
                    field_name = v.split('.')[-1] if '.' in v else v
                    print(f"       Label {k!r}  →  SAP {v!r}  →  placeholder {{{{{field_name}}}}}", flush=True)
            else:
                print("[INFO] No field mappings — LLM placeholder names kept as-is", flush=True)
        except Exception as parse_err:
            print(f"[WARNING] Could not parse field_mappings JSON: {parse_err}", flush=True)
            field_mappings = {}
        # ─────────────────────────────────────────────────────────────────────

        # ── Inject field mappings directly into the prompt (THE KEY FIX) ─────
        # Instead of replacing LLM-invented names AFTER generation (which fails
        # because the LLM picks different names every run), we tell the LLM
        # EXACTLY what placeholder names to use BEFORE it generates the HTML.
        placeholder_block = build_placeholder_prompt_block(field_mappings)
        prompt_with_mappings = PROMPT_PRECISION + placeholder_block

        if placeholder_block:
            print(f"[INFO] Injected {len(field_mappings)} placeholder mapping(s) into prompt", flush=True)
        # ─────────────────────────────────────────────────────────────────────

        # Generate HTML via LLM
        print("[INFO] Sending request to LLM (Pixel-Perfect Replica)...", flush=True)
        raw_response = call_llm(
            process_name='invoice',
            prompt=prompt_with_mappings,
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

        if isinstance(data, list):
            html_content = data[0].get('full_invoice_html', '')
        else:
            html_content = data.get('full_invoice_html', '')

            if not html_content:
                return jsonify({"error": "No HTML found in LLM response", "raw": raw_response}), 500

        # Strip accidental HTML wrappers
        html_content = strip_html_wrappers(html_content)
        print(f"[INFO] Generated HTML size: {len(html_content)} characters", flush=True)

        # ── NO post-hoc apply_field_mappings call needed ──────────────────────
        # The LLM was instructed to use the correct names from the start.
        # Running a fuzzy replacement after-the-fact would risk corrupting the HTML.
        # ─────────────────────────────────────────────────────────────────────

        # Handle logo / signature crops
        print("[INFO] Processing logo and signature assets...", flush=True)
        logo_b64 = request.form.get('logo_b64')
        signature_b64 = request.form.get('signature_b64')

        if logo_b64: print("[INFO] Using provided logo from frontend", flush=True)
        if signature_b64: print("[INFO] Using provided signature from frontend", flush=True)

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

        html_result = html_content

        # ── Build preview with sample values from the original image ─────────
        # The LLM analyses the image to extract current values, then we fill
        # the placeholders using the MAPPED field names (not the LLM's guesses).
        print("[INFO] Generating preview with sample values...", flush=True)
        preview_html = html_content
        try:
            analysis_prompt = (
                "Look at this document image and extract the current values of all dynamic fields. "
                "Return ONLY a JSON list of objects with keys 'field_name' and 'value'. "
                "field_name should be the visible text label (e.g. 'Invoice Number', 'Ship To'). "
                "Example: [{'field_name': 'Invoice Number', 'value': 'INV-2024-001'}, ...]"
            )
            analysis_res = call_llm(
                process_name='invoice',
                prompt=analysis_prompt,
                image_bytes=img_bytes,
                response_mime_type="application/json"
            )
            field_data = json.loads(analysis_res)
            if isinstance(field_data, dict) and "fields" in field_data:
                field_data = field_data["fields"]

            for item in field_data:
                if not isinstance(item, dict):
                    continue
                llm_label = item.get('field_name', '')
                sample_value = item.get('value', '')
                if not llm_label or not sample_value:
                    continue

                # Look up the SAP field name via the bounding-box label
                # field_mappings keys = bounding-box labels = what LLM returns here
                sap_path = field_mappings.get(llm_label, llm_label)
                mapped_field = sap_path.split('.')[-1] if '.' in sap_path else sap_path
                placeholder = "{{" + mapped_field + "}}"
                preview_html = preview_html.replace(placeholder, str(sample_value))
                print(f"  [Preview] {placeholder}  →  '{sample_value}'", flush=True)

            print("[SUCCESS] Preview substitution complete", flush=True)
        except Exception as map_err:
            print(f"[WARNING] Preview substitution failed: {map_err}", flush=True)
        # ─────────────────────────────────────────────────────────────────────

        print("="*50, flush=True)
        print("[BACKEND] --- REPLICA GENERATION COMPLETE ---", flush=True)
        print("="*50 + "\n", flush=True)

        return jsonify({
            "status": "success",
            "full_html": html_result,
            "preview_html": preview_html
        })

    except Exception as e:
        print(f"\n[CRITICAL ERROR] Exception in replicate_invoice: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500