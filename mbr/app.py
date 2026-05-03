"""LIMS application — Flask app factory."""

import os
import socket

from flask import Flask


_DEV_SECRET_PLACEHOLDERS = {
    "dev-secret-change-in-prod",
    "CHANGE-ME-TO-RANDOM-STRING",
    "",
}


def create_app():
    app = Flask(__name__)
    secret = os.environ.get("MBR_SECRET_KEY", "")
    if secret in _DEV_SECRET_PLACEHOLDERS:
        if os.environ.get("MBR_TESTING") == "1":
            secret = "dev-secret-change-in-prod"  # test-only fallback
        else:
            raise RuntimeError(
                "MBR_SECRET_KEY is unset or is a known dev placeholder. "
                "Refusing to start — set a strong random value in /etc/lims.env."
            )
    app.secret_key = secret
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    @app.after_request
    def cache_control(response):
        ct = response.content_type or ''
        if 'text/html' in ct or 'application/json' in ct:
            # HTML + API: never cache
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
        elif 'text/css' in ct or 'javascript' in ct or 'image/' in ct or 'font/' in ct:
            # Static assets: cache for 1 year (cache-busted via ?v= query string)
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    # Audit trail: per-request UUID + ShiftRequiredError → 400 JSON
    import uuid
    from flask import g, jsonify
    from mbr.shared.audit import ShiftRequiredError

    @app.before_request
    def _audit_request_id():
        g.audit_request_id = str(uuid.uuid4())

    @app.errorhandler(ShiftRequiredError)
    def _audit_shift_required(e):
        return jsonify({"error": "shift_required"}), 400

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
    from mbr.admin import admin_bp
    from mbr.zbiorniki import zbiorniki_bp
    from mbr.pipeline import pipeline_bp
    from mbr.ml_export import ml_export_bp
    from mbr.chzt import chzt_bp
    from mbr.produkt_pola import produkt_pola_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(workers_bp)
    app.register_blueprint(paliwo_bp)
    app.register_blueprint(certs_bp)
    app.register_blueprint(registry_bp)
    app.register_blueprint(etapy_bp)
    app.register_blueprint(parametry_bp)
    app.register_blueprint(technolog_bp)
    app.register_blueprint(laborant_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(zbiorniki_bp)
    app.register_blueprint(pipeline_bp)
    app.register_blueprint(ml_export_bp)
    app.register_blueprint(chzt_bp)
    app.register_blueprint(produkt_pola_bp)

    # Initialize database tables
    from mbr.db import db_session
    from mbr.models import init_mbr_tables
    from mbr.chzt.models import init_chzt_tables
    with app.app_context():
        with db_session() as db:
            init_mbr_tables(db)
            init_chzt_tables(db)
            # Fix metoda_id links for parameters created after seed_metody ran
            from mbr.parametry.seed import _PARAM_METHOD_MAP
            nazwa_to_id = {
                r[0]: r[1]
                for r in db.execute("SELECT nazwa, id FROM metody_miareczkowe").fetchall()
            }
            for kod, nazwa in _PARAM_METHOD_MAP.items():
                mid = nazwa_to_id.get(nazwa)
                if mid:
                    db.execute(
                        "UPDATE parametry_analityczne SET metoda_id=? WHERE kod=? AND metoda_id IS NULL",
                        (mid, kod),
                    )
            db.commit()

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
