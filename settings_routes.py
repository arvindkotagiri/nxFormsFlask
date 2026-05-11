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
        'model_analyze': 'google:gemini-2.0-flash-lite',
        'model_zpl': 'google:gemini-2.0-flash-lite',
        'model_xdp': 'google:gemini-2.0-flash-lite',
        'model_invoice': 'google:gemini-2.0-flash-lite',
        'api_gemini': os.getenv("GEMINI_API_KEY", ""),
        'api_openai': "",
        'api_anthropic': ""
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

def _build_models_list(gemini_key, openai_key, anthropic_key):
    """Build a list of available models given API keys."""
    all_models = []

    # 1. Google Gemini
    if gemini_key:
        try:
            client = genai.Client(api_key=gemini_key)
            for m in client.models.list():
                methods = getattr(m, 'supported_methods', []) or getattr(m, 'supported_generation_methods', [])
                if 'generateContent' in str(methods) or 'gemini' in m.name.lower():
                    short_name = m.name.replace("models/", "")
                    all_models.append({
                        "name": f"google:{short_name}",
                        "display_name": f"Google: {getattr(m, 'display_name', short_name)}",
                        "provider": "google"
                    })
        except Exception as e:
            print(f"Gemini Fetch Error: {e}")

    # 2. OpenAI (static list)
    if openai_key:
        all_models.extend([
            {"name": "openai:gpt-4o", "display_name": "OpenAI: GPT-4o", "provider": "openai"},
            {"name": "openai:gpt-4o-mini", "display_name": "OpenAI: GPT-4o-mini", "provider": "openai"},
            {"name": "openai:gpt-3.5-turbo", "display_name": "OpenAI: GPT-3.5 Turbo", "provider": "openai"},
        ])

    # 3. Anthropic (static list)
    # 3. Anthropic (static list)
    if anthropic_key:
        all_models.extend([
            {"name": "anthropic:claude-sonnet-4-6", "display_name": "Anthropic: Claude Sonnet 4.6", "provider": "anthropic"},
            {"name": "anthropic:claude-opus-4-6", "display_name": "Anthropic: Claude Opus 4.6", "provider": "anthropic"},
            {"name": "anthropic:claude-haiku-4-5-20251001", "display_name": "Anthropic: Claude Haiku 4.5", "provider": "anthropic"},
            {"name": "anthropic:claude-sonnet-4-20250514", "display_name": "Anthropic: Claude Sonnet 4 (stable)", "provider": "anthropic"},
        ])

    return all_models


@settings_bp.route('/available-models', methods=['GET'])
def get_available_models():
    """Fetch available models using API keys stored in DB (or env fallback)."""
    gemini_key = get_api_key('gemini') or os.getenv("GEMINI_API_KEY", "")
    openai_key = get_api_key('openai')
    anthropic_key = get_api_key('anthropic')
    return jsonify(_build_models_list(gemini_key, openai_key, anthropic_key))


@settings_bp.route('/available-models', methods=['POST'])
def preview_available_models():
    """Fetch available models using API keys provided in request body (live preview, no DB save)."""
    data = request.json or {}
    gemini_key = data.get('api_gemini') or get_api_key('gemini') or os.getenv("GEMINI_API_KEY", "")
    openai_key = data.get('api_openai') or get_api_key('openai')
    anthropic_key = data.get('api_anthropic') or get_api_key('anthropic')
    return jsonify(_build_models_list(gemini_key, openai_key, anthropic_key))

@settings_bp.route('/model-configs', methods=['GET'])
def get_model_configs():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM system_settings WHERE key LIKE 'model_%' OR key LIKE 'api_%' OR key LIKE 'agent_%'")
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
            if key.startswith('model_') or key.startswith('api_') or key.startswith('agent_'):
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
    return 'google:gemini-2.0-flash-lite' # Final fallback

def get_api_key(provider):
    """Utility to get API key for a provider."""
    # Normalize provider name: 'google' models use 'api_gemini' key in DB
    lookup_provider = provider
    if provider == 'google':
        lookup_provider = 'gemini'
        
    key = f"api_{lookup_provider}"
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT value FROM system_settings WHERE key = %s", (key,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0]:
            return row[0]
    except:
        pass
        
    # Fallback to env for gemini/google if not in DB
    if lookup_provider == 'gemini':
        return os.getenv("GEMINI_API_KEY", "")
    return ""
