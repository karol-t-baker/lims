"""HTTP API for produkt_pola — declarative metadata fields."""

from flask import jsonify, request, session

from mbr.db import db_session
from mbr.laborant.models import get_ebr
from mbr.shared.decorators import login_required, role_required
from mbr.shared import produkt_pola as pp
from mbr.produkt_pola import produkt_pola_bp


def _current_user_id() -> int | None:
    """Resolve current user.id from session login (nickname/inicjaly)."""
    user = session.get("user") or {}
    login = user.get("login")
    if not login:
        return None
    with db_session() as db:
        row = db.execute(
            "SELECT id FROM workers WHERE nickname=? OR inicjaly=?",
            (login, login),
        ).fetchone()
        return row["id"] if row else None


@produkt_pola_bp.route("/api/produkt-pola/_ping")
@login_required
def _ping():
    return jsonify({"ok": True})


@produkt_pola_bp.route("/api/produkt-pola", methods=["GET"])
@login_required
def list_pola():
    scope = request.args.get("scope")
    scope_id_raw = request.args.get("scope_id")
    if scope not in ("produkt", "cert_variant") or not scope_id_raw:
        return jsonify({"error": "scope and scope_id required"}), 400
    try:
        scope_id = int(scope_id_raw)
    except ValueError:
        return jsonify({"error": "scope_id must be int"}), 400
    only_active = request.args.get("only_active", "1") != "0"
    with db_session() as db:
        if scope == "produkt":
            pola = pp.list_pola_for_produkt(db, scope_id, only_active=only_active)
        else:
            pola = pp.list_pola_for_cert_variant(db, scope_id, only_active=only_active)
    return jsonify({"pola": pola})


@produkt_pola_bp.route("/api/produkt-pola", methods=["POST"])
@role_required("admin", "technolog")
def create_pole_endpoint():
    payload = request.get_json(silent=True) or {}
    user_id = _current_user_id()
    with db_session() as db:
        try:
            pole_id = pp.create_pole(db, payload, user_id=user_id)
            db.commit()
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            # UNIQUE constraint -> conflict
            msg = str(e)
            if "UNIQUE" in msg or "constraint" in msg.lower():
                return jsonify({
                    "error": "kod already exists for this scope+scope_id"
                }), 409
            raise
    return jsonify({"pole_id": pole_id}), 201


@produkt_pola_bp.route("/api/produkt-pola/<int:pole_id>", methods=["PUT"])
@role_required("admin", "technolog")
def update_pole_endpoint(pole_id: int):
    patch = request.get_json(silent=True) or {}
    user_id = _current_user_id()
    with db_session() as db:
        try:
            pp.update_pole(db, pole_id, patch, user_id=user_id)
            db.commit()
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


@produkt_pola_bp.route("/api/produkt-pola/<int:pole_id>", methods=["DELETE"])
@role_required("admin", "technolog")
def deactivate_pole_endpoint(pole_id: int):
    user_id = _current_user_id()
    with db_session() as db:
        try:
            pp.deactivate_pole(db, pole_id, user_id=user_id)
            db.commit()
        except ValueError as e:
            return jsonify({"error": str(e)}), 404
    return jsonify({"ok": True})


@produkt_pola_bp.route("/api/ebr/<int:ebr_id>/pola/<int:pole_id>", methods=["PUT"])
@role_required("lab", "kj", "cert", "admin")
def set_ebr_pola_value(ebr_id: int, pole_id: int):
    payload = request.get_json(silent=True) or {}
    if "wartosc" not in payload:
        return jsonify({"error": "wartosc required (string|null)"}), 400
    user_id = _current_user_id()
    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        if ebr is None:
            return jsonify({"error": "ebr not found"}), 404
        try:
            pp.set_wartosc(
                db, ebr_id, pole_id, payload["wartosc"], user_id=user_id
            )
            db.commit()
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


@produkt_pola_bp.route("/api/ebr/<int:ebr_id>/pola", methods=["GET"])
@login_required
def list_ebr_pola_values(ebr_id: int):
    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        if ebr is None:
            return jsonify({"error": "ebr not found"}), 404
        # Resolve produkt_id from mbr_template (joined via ebr_batches.mbr_id).
        prod = db.execute(
            "SELECT id FROM produkty WHERE nazwa=?", (ebr.get("produkt"),)
        ).fetchone()
        if prod is None:
            return jsonify({"wartosci": {}})
        wartosci = pp.get_wartosci_for_ebr(db, ebr_id, prod["id"])
    return jsonify({"wartosci": wartosci})
