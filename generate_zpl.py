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
    print("\n[BACKEND] --- STARTING ZPL CODE GENERATION ---")
    width_in = float(request.form.get('width', 4))
    height_in = float(request.form.get('height', 6))
    dpi = int(request.form.get('dpi', 203))
    dpmm = 8 if dpi < 300 else 12

    html_design = request.form.get('html_design', '')
    if html_design:
        # Strip massive base64 image strings to prevent token bloat
        html_design = re.sub(r'data:image/[^;]+;base64,[^"]+', 'IMAGE_PLACEHOLDER', html_design)
        # Strip watermark image completely from ZPL prompt (it is limited to HTML only)
        html_design = re.sub(r'<img[^>]*id=["\']watermark-element["\'][^>]*>', '', html_design)

    if 'image' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    try:
        file = request.files['image']
        file_bytes = file.read()
        filename = file.filename.lower()

        # Determine page images
        if filename.endswith('.pdf'):
            print("[INFO] Converting PDF to images page by page for ZPL...", flush=True)
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            num_pages = len(doc)
            page_images = []
            for i in range(num_pages):
                page = doc.load_page(i)
                pix = page.get_pixmap(matrix=fitz.Matrix(3, 3)) 
                img_bytes = pix.tobytes("jpeg")
                page_images.append(PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB"))
            doc.close()
        else:
            # Single image uploaded (could be modifiedLabelBlob representing multiple pages stacked!)
            pil_img = PIL.Image.open(io.BytesIO(file_bytes)).convert("RGB")
            width, height = pil_img.size
            # The standard height of 1 page at 96dpi is 1056. The width is 816.
            # Page aspect ratio is height/width = 11/8.5 = 1.2941
            page_height = int(width * (11 / 8.5))
            num_pages = max(1, round(height / page_height))
            print(f"[INFO] Image height is {height}, page_height calculated as {page_height}. Detected {num_pages} pages.", flush=True)
            
            page_images = []
            for i in range(num_pages):
                top = i * page_height
                bottom = min(height, (i + 1) * page_height)
                page_img = pil_img.crop((0, top, width, bottom))
                page_images.append(page_img)

        zpl_prompt = f"""
        ACT AS A ZPL EXPERT.
        Convert the attached label image into valid ZPL II code.
        
        If an HTML_DESIGN is provided below, use it as the ABSOLUTE source of truth for positions, dimensions, and text content.
        
        HTML_DESIGN:
        {html_design or 'Not provided'}
        
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

        def get_html_element_dimensions(html_str, field_name):
            img_tags = re.findall(r'<img[^>]*>', html_str)
            for tag in img_tags:
                is_sig = 'signature' in tag.lower()
                is_wm = 'watermark-element' in tag
                
                if field_name == 'signature' and not is_sig:
                    continue
                if field_name == 'logo' and (is_sig or is_wm):
                    continue
                    
                w_match = re.search(r'width:\s*([0-9.]+)px', tag)
                h_match = re.search(r'height:\s*([0-9.]+)px', tag)
                if not w_match: w_match = re.search(r'width=["\']([0-9.]+)["\']', tag)
                if not h_match: h_match = re.search(r'height=["\']([0-9.]+)["\']', tag)
                
                if w_match and h_match:
                    try:
                        return int(float(w_match.group(1))), int(float(h_match.group(1)))
                    except:
                        pass
            return None

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
                
                # Calculate physical scaling ratio from screen pixels (816px for a standard 8.5in wide sheet) to printer dots
                scale_factor = (width_in * dpi) / 816.0
                
                for it in items:
                    box = it.get('box_2d')
                    if box:
                        ymin, xmin, ymax, xmax = box
                        left, top = (xmin * w) / 1000, (ymin * h) / 1000
                        right, bottom = (xmax * w) / 1000, (ymax * h) / 1000
                        crop = pil_img.crop((left, top, right, bottom))
                        
                        # Rescale cropped graphics to match their exact display size in the HTML layout
                        dims = get_html_element_dimensions(html_design, it['field_name'])
                        if dims:
                            target_w = int(dims[0] * scale_factor)
                            target_h = int(dims[1] * scale_factor)
                            if target_w > 0 and target_h > 0:
                                crop = crop.resize((target_w, target_h), PIL.Image.Resampling.LANCZOS)
                                
                        crops[it['field_name']] = get_zpl_graphic(crop)
                return crops
            except Exception as e:
                print(f"[WARNING] crop_parts failed: {e}")
                return {}

        zpl_blocks = []
        preview_zpls = []
        labelary_previews = []

        for page_idx, p_img in enumerate(page_images):
            print(f"[INFO] Generating ZPL for page {page_idx + 1}/{len(page_images)}...", flush=True)
            
            p_img_byte_arr = io.BytesIO()
            p_img.save(p_img_byte_arr, format='JPEG')
            p_img_bytes = p_img_byte_arr.getvalue()

            raw_zpl = call_llm(process_name='zpl', prompt=zpl_prompt, image_bytes=p_img_bytes, response_mime_type="text/plain")
            zpl_code = clean_zpl(raw_zpl)
            
            if not zpl_code:
                print(f"[WARNING] AI failed to generate ZPL for page {page_idx + 1}", flush=True)
                continue

            # Replace placeholders
            crops_zpl = crop_parts(p_img, p_img_bytes)
            if 'logo' in crops_zpl:
                zpl_code = zpl_code.replace('^GF_LOGO_PLACEHOLDER', crops_zpl['logo'])
            else:
                zpl_code = zpl_code.replace('^GF_LOGO_PLACEHOLDER', '')
                
            if 'signature' in crops_zpl:
                zpl_code = zpl_code.replace('^GF_SIGNATURE_PLACEHOLDER', crops_zpl['signature'])
            else:
                zpl_code = zpl_code.replace('^GF_SIGNATURE_PLACEHOLDER', '')

            zpl_blocks.append(zpl_code)

            # Preview mapping
            preview_zpl = zpl_code
            try:
                analysis_prompt = "Return JSON list of {'field_name': '...', 'value': '...'}"
                analysis_res = call_llm(process_name='zpl', prompt=analysis_prompt, image_bytes=p_img_bytes, response_mime_type="application/json")
                field_data = json.loads(analysis_res)
                if isinstance(field_data, dict) and "fields" in field_data: field_data = field_data["fields"]
                
                for item in field_data:
                    placeholder = "{{" + item['field_name'] + "}}"
                    if item['value']:
                        preview_zpl = preview_zpl.replace(placeholder, str(item['value']))
            except Exception as map_err:
                print(f"Mapping Error (ZPL Page {page_idx}): {map_err}")

            preview_zpls.append(preview_zpl)

            preview_b64 = get_labelary_preview(preview_zpl, width_in, height_in, dpmm)
            if preview_b64:
                labelary_previews.append(f"data:image/png;base64,{preview_b64}")

        full_zpl = "\n".join(zpl_blocks)
        full_preview_zpl = "\n".join(preview_zpls)

        print("[BACKEND] --- ZPL GENERATION COMPLETE ---")
        return jsonify({
            "status": "success",
            "zpl_code": full_zpl,
            "labelary_preview": labelary_previews[0] if labelary_previews else None,
            "labelary_previews": labelary_previews,
            "preview_zpl": full_preview_zpl
        })

    except Exception as e:
        print(f"Server Error (ZPL): {str(e)}")
        return jsonify({"error": str(e)}), 500