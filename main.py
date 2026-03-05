from flask import Flask
from flask_cors import CORS

from analyze import analyze_bp
from generate_zpl import zpl_bp
from replicate_invoice import invoice_bp
from db_routes import db_bp
from label_routes import label_bp

def create_app():
    app = Flask(__name__)
    CORS(app)

    # Register Blueprints
    app.register_blueprint(analyze_bp)
    app.register_blueprint(zpl_bp)
    app.register_blueprint(invoice_bp)
    app.register_blueprint(db_bp)
    app.register_blueprint(label_bp)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(port=5050, debug=False, threaded=True)