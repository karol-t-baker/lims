"""LIMS application — Flask app factory."""

import os
import socket

from flask import Flask


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("MBR_SECRET_KEY", "dev-secret-change-in-prod")

    # Shared: filters, context processor
    from mbr.shared.filters import register_filters
    from mbr.shared.context import register_context
    register_filters(app)
    register_context(app)

    # Blueprints
    from mbr.auth import auth_bp
    from mbr.workers import workers_bp
    from mbr.paliwo import paliwo_bp
    from mbr.certs import certs_bp
    from mbr.registry import registry_bp
    from mbr.etapy import etapy_bp
    from mbr.parametry import parametry_bp
    from mbr.technolog import technolog_bp
    from mbr.laborant import laborant_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(workers_bp)
    app.register_blueprint(paliwo_bp)
    app.register_blueprint(certs_bp)
    app.register_blueprint(registry_bp)
    app.register_blueprint(etapy_bp)
    app.register_blueprint(parametry_bp)
    app.register_blueprint(technolog_bp)
    app.register_blueprint(laborant_bp)

    # Initialize database tables
    from mbr.db import db_session
    from mbr.models import init_mbr_tables
    with app.app_context():
        with db_session() as db:
            init_mbr_tables(db)

    return app


def _get_local_ip() -> str:
    """Best-effort local network IP."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# Module-level instance for backward compat (flask run, gunicorn mbr.app:app)
app = create_app()

if __name__ == "__main__":
    ip = _get_local_ip()
    print(f" * Network: http://{ip}:5001/")
    app.run(host="0.0.0.0", port=5001, debug=True)
