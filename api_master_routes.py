from flask import Blueprint, request, jsonify
import psycopg2
import psycopg2.extras
from psycopg2.extras import RealDictCursor
import os
import requests
import xml.etree.ElementTree as ET
from dotenv import load_dotenv

load_dotenv()

api_master_bp = Blueprint('api_master', __name__)

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "label_app"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASS", "2914"),
        port=os.getenv("DB_PORT", "5432")
    )

@api_master_bp.route('/catalog-init', methods=['POST'])
def init_api_db():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Create contexts table if it doesn't exist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS contexts (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                auth_type TEXT,
                client_id TEXT,
                client_secret TEXT,
                fields JSONB,
                entities JSONB,
                status TEXT DEFAULT 'Active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        return jsonify({"status": "success", "message": "Contexts table initialized"})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@api_master_bp.route('/catalog', methods=['GET'])
def get_apis():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM contexts ORDER BY created_at DESC")
    apis = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(apis)

@api_master_bp.route('/catalog', methods=['POST'])
def add_api():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO contexts (name, endpoint, auth_type, client_id, client_secret, fields, entities)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (
            data['name'], 
            data['endpoint'], 
            data.get('auth_type'), 
            data.get('client_id'), 
            data.get('client_secret'),
            psycopg2.extras.Json(data.get('fields', [])),
            psycopg2.extras.Json(data.get('entities', []))
        ))
        api_id = cur.fetchone()[0]
        conn.commit()
        return jsonify({"status": "success", "id": api_id})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@api_master_bp.route('/catalog/<int:api_id>', methods=['PUT'])
def update_api(api_id):
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE contexts 
            SET name = %s, endpoint = %s, auth_type = %s, client_id = %s, client_secret = %s, fields = %s, entities = %s
            WHERE id = %s
        """, (
            data['name'], 
            data['endpoint'], 
            data.get('auth_type'), 
            data.get('client_id'), 
            data.get('client_secret'),
            psycopg2.extras.Json(data.get('fields', [])),
            psycopg2.extras.Json(data.get('entities', [])),
            api_id
        ))
        conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@api_master_bp.route('/catalog/<int:api_id>', methods=['DELETE'])
def delete_api(api_id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM contexts WHERE id = %s", (api_id,))
        conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@api_master_bp.route('/fetch-metadata', methods=['POST'])
def fetch_metadata():
    data = request.json
    url = data.get('url')
    if not url:
        return jsonify({"status": "error", "message": "URL is required"}), 400
    
    # Append $metadata if not present
    metadata_url = url if url.endswith('$metadata') else (url if url.endswith('/') else url + '/') + '$metadata'
    
    try:
        # In a real scenario, you might need OAuth here.
        # For now, let's try a simple GET.
        response = requests.get(metadata_url, verify=False, timeout=10)
        if response.status_code != 200:
            return jsonify({"status": "error", "message": f"Failed to fetch metadata: {response.status_code}"}), response.status_code
        
        # Parse XML
        root = ET.fromstring(response.content)
        
        # OData metadata parsing (simplified)
        namespaces = {
            'edmx': 'http://schemas.microsoft.com/ado/2007/06/edmx',
            'edm': 'http://schemas.microsoft.com/ado/2008/09/edm' # This varies by OData version
        }
        
        # Find all EntityTypes and their properties using local-name() to be namespace-agnostic
        entities = []
        for entity_type in root.findall('.//{*}EntityType'):
            name = entity_type.get('Name')
            fields = []
            
            # Find properties
            for prop in entity_type.findall('.//{*}Property'):
                fields.append({
                    "name": prop.get('Name'),
                    "type": prop.get('Type'),
                    "label": prop.get('{http://www.sap.com/Protocols/SAPData}label') or prop.get('Name')
                })
            
            # Find navigation properties
            nav_props = []
            for nav in entity_type.findall('.//{*}NavigationProperty'):
                nav_props.append({
                    "name": nav.get('Name'),
                    "relationship": nav.get('Relationship'),
                    "to": nav.get('ToRole') or nav.get('Name')
                })

            entities.append({
                "name": name,
                "fields": fields,
                "navigation": nav_props
            })

        return jsonify({"status": "success", "entities": entities})

        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

