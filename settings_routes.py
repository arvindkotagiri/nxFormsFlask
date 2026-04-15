import os
import psycopg2
from flask import Blueprint, jsonify, request
from google import genai
from dotenv import load_dotenv

load_dotenv()

settings_bp = Blueprint('settings', __name__)

# DB Config
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "label_app")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "2914")
DB_PORT = os.getenv("DB_PORT", "5432")

def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        port=DB_PORT
    )

def init_settings_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    # Insert defaults if not exist
    defaults = {
        'model_analyze': 'gemini-2.0-flash-lite-preview-02-05',
        'model_zpl': 'gemini-2.0-flash-lite-preview-02-05',
        'model_xdp': 'gemini-2.0-flash-lite-preview-02-05',
        'model_invoice': 'gemini-2.0-flash-lite-preview-02-05'
    }
    for key, val in defaults.items():
        cur.execute("INSERT INTO system_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING", (key, val))
    # Ensure label_master has all required columns
    cur.execute("""
        CREATE TABLE IF NOT EXISTS label_master (
            uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            label_id TEXT,
            label_name TEXT,
            context TEXT,
            field_mapping JSONB,
            bar_code_type TEXT,
            zpl_code TEXT,
            fields JSONB,
            version NUMERIC,
            created_by TEXT,
            created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    # Add missing columns if they don't exist
    columns_to_add = [
        ("html_code", "TEXT"),
        ("page_dimensions", "TEXT"),
        ("output_mode", "TEXT")
    ]
    for col_name, col_type in columns_to_add:
        cur.execute(f"""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                               WHERE table_name='label_master' AND column_name='{col_name}') THEN
                    ALTER TABLE label_master ADD COLUMN {col_name} {col_type};
                END IF;
            END $$;
        """)
    
    conn.commit()
    cur.close()
    conn.close()

# Initialize on import
init_settings_db()

@settings_bp.route('/available-models', methods=['GET'])
def get_available_models():
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return jsonify({"error": "No API Key found"}), 400
    
    try:
        client = genai.Client(api_key=api_key)
        models = []
        for m in client.models.list():
            # Debug: print help(m) or dir(m) to console on first run
            if not models:
                print(f"DEBUG: Model object attributes: {dir(m)}")
            
            # Simple fallback: include it if it's gemini or has generateContent
            methods = getattr(m, 'supported_methods', []) or getattr(m, 'supported_generation_methods', [])
            if 'generateContent' in str(methods) or 'gemini' in m.name.lower():
                models.append({
                    "name": m.name,
                    "display_name": getattr(m, 'display_name', m.name)
                })
        return jsonify(models)
    except Exception as e:
        print(f"ERROR fetching models: {e}")
        return jsonify({"error": str(e)}), 500

@settings_bp.route('/model-configs', methods=['GET'])
def get_model_configs():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM system_settings WHERE key LIKE 'model_%'")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(dict(rows))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@settings_bp.route('/model-configs', methods=['POST'])
def save_model_configs():
    data = request.json
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        for key, val in data.items():
            if key.startswith('model_'):
                cur.execute("INSERT INTO system_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, val))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def get_model_for_process(process_name):
    """Utility to get model for a specific process."""
    key = f"model_{process_name}"
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT value FROM system_settings WHERE key = %s", (key,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return row[0]
    except:
        pass
    return 'gemini-2.0-flash-lite-preview-02-05' # Final fallback
