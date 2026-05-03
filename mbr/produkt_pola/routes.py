"""HTTP API for produkt_pola — declarative metadata fields."""

from flask import jsonify, request

from mbr.db import db_session
from mbr.shared.decorators import login_required, role_required
from mbr.produkt_pola import produkt_pola_bp


@produkt_pola_bp.route("/api/produkt-pola/_ping")
@login_required
def _ping():
    return jsonify({"ok": True})
