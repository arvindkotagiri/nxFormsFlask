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
                auth_url TEXT,
                client_id TEXT,
                client_secret TEXT,
                fields JSONB,
                entities JSONB,
                username TEXT,
                password TEXT,
                status TEXT DEFAULT 'Active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Add columns if they don't exist (for existing tables)
        cur.execute("""
            ALTER TABLE contexts 
            ADD COLUMN IF NOT EXISTS username TEXT,
            ADD COLUMN IF NOT EXISTS password TEXT;
        """)

        cur.execute("""
            ALTER TABLE contexts
            ADD COLUMN IF NOT EXISTS application TEXT,
            ADD COLUMN IF NOT EXISTS environment TEXT,
            ADD COLUMN IF NOT EXISTS client NUMERIC(3);
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
            INSERT INTO contexts (name, endpoint, auth_type, auth_url, client_id, client_secret, fields, entities, username, password, application, environment, client)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (
            data['name'], 
            data['endpoint'], 
            data.get('auth_type'), 
            data.get('auth_url'), 
            data.get('client_id'), 
            data.get('client_secret'),
            psycopg2.extras.Json(data.get('fields', [])),
            psycopg2.extras.Json(data.get('entities', [])),
            data.get('username'),
            data.get('password'),
            data.get('application'),
            data.get('environment'),
            data.get('client')
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
            SET name = %s, endpoint = %s, auth_type = %s, auth_url = %s, client_id = %s, client_secret = %s, fields = %s, entities = %s, username = %s, password = %s, application = %s, environment = %s, client = %s
            WHERE id = %s
        """, (
            data['name'], 
            data['endpoint'], 
            data.get('auth_type'), 
            data.get('auth_url'), 
            data.get('client_id'), 
            data.get('client_secret'),
            psycopg2.extras.Json(data.get('fields', [])),
            psycopg2.extras.Json(data.get('entities', [])),
            data.get('username'),
            data.get('password'),
            data.get('application'),
            data.get('environment'),
            data.get('client'),
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
    token_url = data.get('tokenUrl')
    client_id = data.get('clientId')
    client_secret = data.get('clientSecret')
    auth_type = data.get('authType', 'OAuth2')
    username = data.get('username')
    password = data.get('password')

    if not url:
        return jsonify({"status": "error", "message": "URL is required"}), 400
    
    # Append $metadata if not present
    metadata_url = url if url.endswith('$metadata') else (url if url.endswith('/') else url + '/') + '$metadata'
    
    try:
        headers = {}
        auth = None
        # Fetch OAuth token if auth details are provided
        if auth_type == 'OAuth2' and token_url and client_id and client_secret:
            print(f"[FETCH_METADATA] Requesting token from {token_url}")
            auth_response = requests.post(
                token_url,
                data={
                    'grant_type': 'client_credentials',
                    'client_id': client_id,
                    'client_secret': client_secret
                },
                auth=(client_id, client_secret),
                verify=False,
                timeout=10
            )
            
            if auth_response.status_code != 200:
                print(f"[FETCH_METADATA] Auth Failed. Status code: {auth_response.status_code}. Response: {auth_response.text}")
                return jsonify({
                    "status": "error", 
                    "message": f"OAuth Authentication failed (Status {auth_response.status_code})"
                }), 401
                
            token_data = auth_response.json()
            access_token = token_data.get('access_token')
            if access_token:
                print(f"[FETCH_METADATA] Got token successfully! Length: {len(access_token)}")
                headers['Authorization'] = f'Bearer {access_token}'
        elif auth_type == 'Basic' and username and password:
            print(f"[FETCH_METADATA] Using Basic Auth for {username}")
            auth = (username, password)

        print(f"[FETCH_METADATA] Requesting OData metadata from {metadata_url} with headers {list(headers.keys())}")
        response = requests.get(metadata_url, headers=headers, auth=auth, verify=False, timeout=10)
        print(f"[FETCH_METADATA] Metadata Response Status: {response.status_code}")
        
        if response.status_code == 404:
            print("[FETCH_METADATA] Metadata returned 404. Testing base URL to see if it's reachable...")
            base_check = requests.get(url, headers=headers, auth=auth, verify=False, timeout=5)
            if base_check.status_code == 200:
                 return jsonify({"status": "error", "message": f"Connected successfully via Token, but $metadata endpoint is missing (404) at the provided Service Endpoint. Please check if your CAP service exposes $metadata. Base URL returned: 200 OK."}), 404
            elif base_check.status_code == 401:
                 return jsonify({"status": "error", "message": f"Connected, but token was rejected by the service (401 Unauthorized). Please check your credentials and token scopes."}), 401
            else:
                 return jsonify({"status": "error", "message": f"Service Endpoint returned {base_check.status_code} and $metadata returned 404. Ensure you provided the exact valid OData V4 Service Endpoint."}), 404

        if response.status_code != 200:
            print(f"[FETCH_METADATA] Metadata Fetch Failed. Output: {response.text[:200]}")
            return jsonify({"status": "error", "message": f"Failed to fetch metadata (Status {response.status_code}): {response.text[:100]}"}), response.status_code
        
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
            
            # Find keys
            key_names = set()
            for key in entity_type.findall('.//{*}Key/{*}PropertyRef'):
                key_names.add(key.get('Name'))
            
            # Find properties
            for prop in entity_type.findall('.//{*}Property'):
                prop_name = prop.get('Name')
                fields.append({
                    "name": prop_name,
                    "type": prop.get('Type'),
                    "label": prop.get('{http://www.sap.com/Protocols/SAPData}label') or prop_name,
                    "isKey": prop_name in key_names
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

