import os
import psycopg2
from flask import Blueprint, jsonify
from dotenv import load_dotenv

load_dotenv()

label_bp = Blueprint("labels", __name__)

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "label_app")
DB_USER = os.getenv("DB_USER", "label_app_user")
DB_PASS = os.getenv("DB_PASS", "aravindk10")
DB_PORT = os.getenv("DB_PORT", "5432")


def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        port=DB_PORT
    )


@label_bp.route("/labels", methods=["GET"])
def get_labels():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        query = """
            SELECT 
                uuid,
                label_id,
                label_name,
                context,
                field_mapping,
                bar_code_type,
                zpl_code,
                html_code,
                fields,
                version,
                created_by,
                created_on,
                page_dimensions,
                output_mode
            FROM label_master
            ORDER BY created_on DESC;
        """

        cur.execute(query)
        rows = cur.fetchall()

        columns = [desc[0] for desc in cur.description]

        labels = []
        for row in rows:
            label = dict(zip(columns, row))
            labels.append(label)

        cur.close()
        conn.close()

        return jsonify(labels), 200

    except Exception as e:
        print(f"Error fetching labels: {e}")
        return jsonify({"error": str(e)}), 500