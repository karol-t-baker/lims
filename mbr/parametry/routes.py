from flask import request, jsonify, render_template

from mbr.parametry import parametry_bp
from mbr.parametry.registry import get_parametry_for_kontekst, get_calc_methods, get_konteksty
from mbr.shared.decorators import login_required
from mbr.db import db_session


@parametry_bp.route("/api/parametry/config")
@login_required
def api_parametry_config():
    """Universal parameter config endpoint."""
    produkt = request.args.get("produkt", "")
    kontekst = request.args.get("kontekst", "")
    if not kontekst:
        return jsonify({"error": "kontekst is required"}), 400
    with db_session() as db:
        params = get_parametry_for_kontekst(db, produkt, kontekst)
    return jsonify(params)


@parametry_bp.route("/api/parametry/calc-methods")
@login_required
def api_calc_methods():
    """Titration calc methods for calculator.js."""
    with db_session() as db:
        methods = get_calc_methods(db)
    return jsonify(methods)


@parametry_bp.route("/api/parametry/list")
@login_required
def api_parametry_list():
    """All parameters with their etapy bindings."""
    with db_session() as db:
        params = db.execute(
            "SELECT * FROM parametry_analityczne WHERE aktywny=1 ORDER BY typ, kod"
        ).fetchall()
        result = []
        for p in params:
            d = dict(p)
            bindings = db.execute(
                "SELECT * FROM parametry_etapy WHERE parametr_id=? ORDER BY kontekst, produkt",
                (p["id"],),
            ).fetchall()
            d["bindings"] = [dict(b) for b in bindings]
            result.append(d)
    return jsonify(result)


@parametry_bp.route("/api/parametry/<int:param_id>", methods=["PUT"])
@login_required
def api_parametry_update(param_id):
    """Update global parameter fields."""
    data = request.get_json(silent=True) or {}
    allowed = {"label", "skrot", "formula", "metoda_nazwa", "metoda_formula", "metoda_factor", "precision"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "No valid fields"}), 400
    sets = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [param_id]
    with db_session() as db:
        db.execute(f"UPDATE parametry_analityczne SET {sets} WHERE id=?", vals)
        db.commit()
    return jsonify({"ok": True})


@parametry_bp.route("/api/parametry/etapy", methods=["POST"])
@login_required
def api_parametry_etapy_create():
    """Create new binding."""
    data = request.get_json(silent=True) or {}
    parametr_id = data.get("parametr_id")
    kontekst = data.get("kontekst", "")
    produkt = data.get("produkt") or None
    nawazka = data.get("nawazka_g")
    mn = data.get("min_limit")
    mx = data.get("max_limit")
    if not parametr_id or not kontekst:
        return jsonify({"error": "parametr_id and kontekst required"}), 400
    with db_session() as db:
        existing = db.execute(
            "SELECT id FROM parametry_etapy WHERE parametr_id=? AND kontekst=? AND produkt IS ?",
            (parametr_id, kontekst, produkt),
        ).fetchone()
        if existing:
            return jsonify({"error": "Duplicate binding"}), 409
        cur = db.execute(
            """INSERT INTO parametry_etapy (parametr_id, kontekst, produkt, nawazka_g, min_limit, max_limit)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (parametr_id, kontekst, produkt, nawazka, mn, mx),
        )
        db.commit()
        new_id = cur.lastrowid
    return jsonify({"ok": True, "id": new_id})


@parametry_bp.route("/api/parametry/etapy/<int:binding_id>", methods=["PUT"])
@login_required
def api_parametry_etapy_update(binding_id):
    """Update binding fields."""
    data = request.get_json(silent=True) or {}
    allowed = {"nawazka_g", "min_limit", "max_limit", "kolejnosc", "formula", "sa_bias"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "No valid fields"}), 400
    sets = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [binding_id]
    with db_session() as db:
        db.execute(f"UPDATE parametry_etapy SET {sets} WHERE id=?", vals)
        db.commit()
    return jsonify({"ok": True})


@parametry_bp.route("/api/parametry/etapy/<int:binding_id>", methods=["DELETE"])
@login_required
def api_parametry_etapy_delete(binding_id):
    """Delete a binding."""
    with db_session() as db:
        db.execute("DELETE FROM parametry_etapy WHERE id=?", (binding_id,))
        db.commit()
    return jsonify({"ok": True})


@parametry_bp.route("/parametry")
@login_required
def parametry_editor():
    """Parameter editor page."""
    with db_session() as db:
        products = [r["produkt"] for r in db.execute(
            "SELECT DISTINCT produkt FROM mbr_templates WHERE status='active' ORDER BY produkt"
        ).fetchall()]
        konteksty = get_konteksty(db)
    return render_template("parametry_editor.html", products=products, konteksty=konteksty)
