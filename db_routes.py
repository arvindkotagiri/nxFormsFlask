import os
import json
import psycopg2
from psycopg2.extras import Json
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
from dotenv import load_dotenv
from flask import Blueprint

load_dotenv()

db_bp = Blueprint('db', __name__)

# Default DB Connection: Update this or set in .env
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "label_app")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "2914")
DB_PORT = os.getenv("DB_PORT", "5432")

@db_bp.route('/init-labels-db', methods=['POST'])
def init_labels_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Create label_master if it doesn't exist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS label_master (
                uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                label_id VARCHAR(50),
                label_name VARCHAR(255),
                context TEXT,
                field_mapping JSONB,
                bar_code_type VARCHAR(50),
                zpl_code TEXT,
                html_code TEXT,
                fields JSONB,
                version NUMERIC,
                created_by VARCHAR(100),
                created_on TIMESTAMP,
                page_dimensions VARCHAR(50),
                output_mode VARCHAR(20)
            );
        """)
        
        # Add xdp_code if missing
        cur.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='label_master' AND column_name='xdp_code') THEN
                    ALTER TABLE label_master ADD COLUMN xdp_code TEXT;
                END IF;
            END $$;
        """)

        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "success", "message": "Label table schema updated"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def get_db_connection():
    conn = psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        port=DB_PORT
    )
    return conn

@db_bp.route('/save-label', methods=['POST'])
def save_label():
    try:
        data = request.json
        
        # Extract fields from frontend payload
        label_id = data.get('label_id')
        label_name = data.get('label_name')
        context = data.get('context')
        # Ensure field_mapping is a dictionary/JSON object
        field_mapping = json.dumps(data.get('field_mapping', {})) 
        bar_code_type = data.get('bar_code_type', '')
        zpl_code = data.get('zpl_code', '')
        html_code = data.get('html_code','')
        xdp_code = data.get('xdp_code', '')
        page_dimensions = data.get('page_dimensions', '')
        output_mode = data.get('output_mode', '')
        # Ensure fields is a list/JSON array
        fields = json.dumps(data.get('fields', []))
        version = data.get('version', 1.0)
        created_by = data.get('created_by', 'System')
        created_on = datetime.now()

        conn = get_db_connection()
        cur = conn.cursor()

        insert_query = """
            INSERT INTO label_master (
                label_id, label_name, context, field_mapping, 
                bar_code_type, zpl_code, fields, version, 
                created_by, created_on,
                html_code, page_dimensions, output_mode, xdp_code
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING uuid;
        """

        cur.execute(insert_query, (
            label_id, label_name, context, field_mapping,
            bar_code_type, zpl_code, fields, version,
            created_by, created_on,
            html_code, page_dimensions, output_mode, xdp_code
        ))

        new_uuid = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"status": "success", "uuid": new_uuid}), 201

    except Exception as e:
        print(f"Error saving label: {e}")
        return jsonify({"error": str(e)}), 500
