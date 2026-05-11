import os
import uuid
import psycopg2
import socket
from psycopg2.extras import RealDictCursor

from flask import Blueprint, request, jsonify
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

printer_bp = Blueprint('printer', __name__)

# DB connection configuration
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "label_app")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "2914")
DB_PORT = os.getenv("DB_PORT", "5432")

def get_db_connection():
    conn = psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        port=DB_PORT,
        cursor_factory=RealDictCursor
    )
    return conn

def send_to_printer(ip, port, data):
    """Sends raw ZPL data to a network printer via socket."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(10)
            s.connect((ip, int(port)))
            s.sendall(data.encode('utf-8'))
        return True, None
    except Exception as e:
        return False, str(e)


@printer_bp.route('/init-db', methods=['POST'])
def init_db():
    """Initializes the printer and jobs tables."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Create printer_master
        cur.execute("""
            CREATE TABLE IF NOT EXISTS printer_master (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(255) NOT NULL,
                ip_address VARCHAR(15) NOT NULL,
                site_id VARCHAR(50) NOT NULL,
                type VARCHAR(50) DEFAULT 'ZEBRA',
                status VARCHAR(20) DEFAULT 'Online',
                created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Create print_jobs
        cur.execute("""
            CREATE TABLE IF NOT EXISTS print_jobs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                printer_id UUID REFERENCES printer_master(id),
                site_id VARCHAR(50) NOT NULL,
                payload TEXT NOT NULL,
                copies INT DEFAULT 1,
                status VARCHAR(20) DEFAULT 'PENDING',
                error_msg TEXT,
                created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "success", "message": "Tables created"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@printer_bp.route('/printers', methods=['GET'])
def get_printers():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM printer_master ORDER BY created_on DESC")
        printers = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(printers), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@printer_bp.route('/printers', methods=['POST'])
def add_printer():
    try:
        data = request.json
        name = data.get('name')
        ip_address = data.get('ip_address')
        site_id = data.get('site_id')
        printer_type = data.get('type', 'ZEBRA')
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO printer_master (name, ip_address, site_id, type)
            VALUES (%s, %s, %s, %s) RETURNING id;
        """, (name, ip_address, site_id, printer_type))
        new_id = cur.fetchone()['id']
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "success", "id": new_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@printer_bp.route('/printers/<printer_id>', methods=['DELETE'])
def delete_printer(printer_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM printer_master WHERE id = %s", (printer_id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@printer_bp.route('/print-zpl', methods=['POST'])
def submit_print_job():
    try:
        data = request.json
        printer_id = data.get('printer_id')
        payload = data.get('payload') # This is the ZPL string
        site_id = data.get('site_id')
        copies = data.get('copies', 1)
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO print_jobs (printer_id, site_id, payload, copies, status)
            VALUES (%s, %s, %s, %s, 'PENDING') RETURNING id;
        """, (printer_id, site_id, payload, copies))
        job_id = cur.fetchone()['id']
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "queued", "job_id": job_id}), 202
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@printer_bp.route('/jobs/pending/<site_id>', methods=['GET'])
def get_pending_jobs(site_id):
    """Called by the Local Agent to fetch pending jobs for its site."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Fetch jobs and join with printer details to get the IP
        cur.execute("""
            SELECT j.id, j.payload, j.copies, p.ip_address, p.type
            FROM print_jobs j
            JOIN printer_master p ON j.printer_id = p.id
            WHERE j.site_id = %s AND j.status = 'PENDING'
            ORDER BY j.created_on ASC;
        """, (site_id,))
        jobs = cur.fetchall()
        
        # Update jobs to 'PROCESSING' so they aren't picked up multiple times
        if jobs:
            job_ids = [j['id'] for j in jobs]
            cur.execute("UPDATE print_jobs SET status = 'PROCESSING', updated_on = NOW() WHERE id = ANY(%s)", (job_ids,))
            conn.commit()
            
        cur.close()
        conn.close()
        return jsonify(jobs), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@printer_bp.route('/jobs/<job_id>/status', methods=['PATCH'])
def update_job_status(job_id):
    """Called by the Local Agent to update status (COMPLETED/FAILED)."""
    try:
        data = request.json
        status = data.get('status')
        error_msg = data.get('error_msg', None)
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE print_jobs 
            SET status = %s, error_msg = %s, updated_on = NOW()
            WHERE id = %s;
        """, (status, error_msg, job_id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@printer_bp.route('/direct-print', methods=['POST'])
def direct_print():
    """Immediately sends ZPL to a printer (used when UI acts as agent)."""
    try:
        data = request.json
        ip = data.get('ip_address')
        payload = data.get('payload')
        port = data.get('port', 9100)
        
        if not ip or not payload:
            return jsonify({"error": "Missing IP or payload"}), 400
            
        success, error = send_to_printer(ip, port, payload)
        if success:
            return jsonify({"status": "success"}), 200
        else:
            return jsonify({"status": "failed", "error": error}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

