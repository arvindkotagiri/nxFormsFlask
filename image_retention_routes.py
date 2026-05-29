import os
import io
import base64
import psycopg2
from flask import Blueprint, request, jsonify, send_file
from dotenv import load_dotenv
from PIL import Image as PILImage

load_dotenv()

image_retention_bp = Blueprint('image_retention', __name__)

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "label_app")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "2914")
DB_PORT = os.getenv("DB_PORT", "5432")

@image_retention_bp.route('/auth/login', methods=['POST'])
def mock_login():
    # Return a dummy JWT token that expires in the year 2286 (exp = 9999999999)
    mock_payload = '{"exp": 9999999999}'
    encoded_payload = base64.b64encode(mock_payload.encode('utf-8')).decode('utf-8').replace('=', '')
    mock_token = f"mockheader.{encoded_payload}.mocksignature"
    
    return jsonify({
        "access_token": mock_token,
        "user": {
            "id": 1,
            "name": "Configurator",
            "email": "configurator@test.com",
            "role": "Admin"
        }
    }), 200

def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        port=DB_PORT
    )

def init_image_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS image_master (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            size VARCHAR(50),
            resolution VARCHAR(50),
            color BOOLEAN DEFAULT TRUE,
            image_data BYTEA NOT NULL,
            mime_type VARCHAR(50) DEFAULT 'image/png',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

# Initialize on load
try:
    init_image_db()
    print("[RELOAD] image_master table verified/created in database")
except Exception as e:
    print(f"[ERROR] Failed to initialize image master database: {e}")

@image_retention_bp.route('/image-retention', methods=['GET'])
def get_images():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, name, size, resolution, color FROM image_master ORDER BY id DESC")
        rows = cur.fetchall()
        cur.close()
        conn.close()

        result = []
        for r in rows:
            result.append({
                "id": str(r[0]),
                "name": r[1],
                "size": r[2],
                "resolution": r[3],
                "color": bool(r[4])
            })
        return jsonify(result), 200
    except Exception as e:
        print(f"Error fetching images: {e}")
        return jsonify({"error": str(e)}), 500

@image_retention_bp.route('/image-retention/metadata', methods=['POST'])
def upload_images():
    try:
        if 'images' not in request.files:
            return jsonify({"error": "No image files in request"}), 400

        files = request.files.getlist('images')
        conn = get_db_connection()
        cur = conn.cursor()

        for file in files:
            if not file or file.filename == '':
                continue

            file_bytes = file.read()
            filename = file.filename
            
            # Auto-downscale image to a maximum of 600px width/height to prevent out-of-memory browser crashes
            try:
                img = PILImage.open(io.BytesIO(file_bytes))
                MAX_SIZE = 600
                if img.width > MAX_SIZE or img.height > MAX_SIZE:
                    img.thumbnail((MAX_SIZE, MAX_SIZE), PILImage.Resampling.LANCZOS)
                    out_bytes = io.BytesIO()
                    # Keep original format if possible, default to PNG
                    img.save(out_bytes, format=img.format or 'PNG')
                    file_bytes = out_bytes.getvalue()
            except Exception as resize_err:
                print(f"[WARNING] Pre-resize failed for {filename}: {resize_err}")

            # Format size
            size_kb = len(file_bytes) / 1024.0
            if size_kb > 1024.0:
                size_str = f"{size_kb/1024.0:.1f} MB"
            else:
                size_str = f"{size_kb:.1f} KB"

            # Detect resolution & color using PIL
            try:
                img = PILImage.open(io.BytesIO(file_bytes))
                resolution_str = f"{img.width}x{img.height}"
                
                # Check if it has color channels
                if img.mode in ('RGB', 'RGBA', 'P', 'CMYK'):
                    color_val = True
                else:
                    color_val = False
            except Exception as pil_err:
                print(f"[WARNING] PIL parsing failed for {filename}: {pil_err}")
                resolution_str = "Unknown"
                color_val = True

            mime_type = file.content_type or 'image/png'

            # Insert into database
            cur.execute(
                "INSERT INTO image_master (name, size, resolution, color, image_data, mime_type) VALUES (%s, %s, %s, %s, %s, %s)",
                (filename, size_str, resolution_str, color_val, psycopg2.Binary(file_bytes), mime_type)
            )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"status": "success", "message": "Images imported successfully"}), 201
    except Exception as e:
        print(f"Error uploading images: {e}")
        return jsonify({"error": str(e)}), 500

@image_retention_bp.route('/image-retention/<int:image_id>/image', methods=['GET'])
def get_image_file(image_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT image_data, mime_type, name FROM image_master WHERE id = %s", (image_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return jsonify({"error": "Image not found"}), 404

        image_data, mime_type, filename = row

        # On-the-fly downscaling for existing large database images to guarantee rapid load and low memory footprint
        try:
            img = PILImage.open(io.BytesIO(image_data))
            MAX_SIZE = 600
            if img.width > MAX_SIZE or img.height > MAX_SIZE:
                img.thumbnail((MAX_SIZE, MAX_SIZE), PILImage.Resampling.LANCZOS)
                out_bytes = io.BytesIO()
                img.save(out_bytes, format=img.format or 'PNG')
                image_data = out_bytes.getvalue()
        except Exception as resize_err:
            print(f"[WARNING] On-the-fly downscaling failed: {resize_err}")

        response = send_file(
            io.BytesIO(image_data),
            mimetype=mime_type,
            as_attachment=False,
            download_name=filename
        )
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        return response
    except Exception as e:
        print(f"Error retrieving image file: {e}")
        return jsonify({"error": str(e)}), 500

@image_retention_bp.route('/image-retention/<int:image_id>', methods=['DELETE'])
def delete_image(image_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM image_master WHERE id = %s", (image_id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "success", "message": "Image deleted successfully"}), 200
    except Exception as e:
        print(f"Error deleting image: {e}")
        return jsonify({"error": str(e)}), 500
