"""zbiorniki/routes.py — API endpoints for tank management."""

from flask import jsonify, request, render_template

from mbr.db import db_session
from mbr.shared.decorators import login_required, role_required
from mbr.zbiorniki import zbiorniki_bp
from mbr.zbiorniki.models import (
    list_zbiorniki, create_zbiornik, update_zbiornik,
    link_szarza, unlink_szarza, get_links_for_ebr,
)


@zbiorniki_bp.route("/api/zbiorniki")
@login_required
def api_list():
    include_all = request.args.get("all") == "1"
    with db_session() as db:
        tanks = list_zbiorniki(db, include_inactive=include_all)
    return jsonify(tanks)


@zbiorniki_bp.route("/api/zbiorniki", methods=["POST"])
@role_required("admin")
def api_create():
    data = request.get_json(silent=True) or {}
    nr = data.get("nr_zbiornika", "").strip()
    if not nr:
        return jsonify({"error": "nr_zbiornika required"}), 400
    with db_session() as db:
        try:
            zid = create_zbiornik(db, nr, data.get("max_pojemnosc", 0), data.get("produkt", ""))
        except Exception:
            return jsonify({"error": "Zbiornik already exists"}), 409
    return jsonify({"ok": True, "id": zid})


@zbiorniki_bp.route("/api/zbiorniki/<int:zid>", methods=["PUT"])
@role_required("admin")
def api_update(zid):
    data = request.get_json(silent=True) or {}
    with db_session() as db:
        update_zbiornik(db, zid, **data)
    return jsonify({"ok": True})


@zbiorniki_bp.route("/api/zbiornik-szarze/<int:ebr_id>")
@login_required
def api_links(ebr_id):
    with db_session() as db:
        links = get_links_for_ebr(db, ebr_id)
    return jsonify(links)


@zbiorniki_bp.route("/api/zbiornik-szarze", methods=["POST"])
@login_required
def api_link():
    data = request.get_json(silent=True) or {}
    ebr_id = data.get("ebr_id")
    zbiornik_id = data.get("zbiornik_id")
    if not ebr_id or not zbiornik_id:
        return jsonify({"error": "ebr_id and zbiornik_id required"}), 400
    with db_session() as db:
        lid = link_szarza(db, ebr_id, zbiornik_id, data.get("masa_kg"))
    return jsonify({"ok": True, "id": lid})


@zbiorniki_bp.route("/api/zbiornik-szarze/<int:link_id>", methods=["DELETE"])
@login_required
def api_unlink(link_id):
    with db_session() as db:
        unlink_szarza(db, link_id)
    return jsonify({"ok": True})


@zbiorniki_bp.route("/admin/zbiorniki")
@role_required("admin")
def admin_zbiorniki():
    return render_template("admin/zbiorniki.html")


# ── Produkty API ──

@zbiorniki_bp.route("/api/produkty")
@login_required
def api_produkty():
    include_all = request.args.get("all") == "1"
    with db_session() as db:
        sql = "SELECT * FROM produkty"
        if not include_all:
            sql += " WHERE aktywny = 1"
        sql += " ORDER BY nazwa"
        rows = [dict(r) for r in db.execute(sql).fetchall()]
    return jsonify(rows)


@zbiorniki_bp.route("/api/produkty", methods=["POST"])
@role_required("admin")
def api_produkty_create():
    data = request.get_json(silent=True) or {}
    nazwa = data.get("nazwa", "").strip()
    kod = data.get("kod", "").strip()
    if not nazwa:
        return jsonify({"error": "nazwa required"}), 400
    with db_session() as db:
        try:
            cur = db.execute(
                "INSERT INTO produkty (nazwa, kod) VALUES (?, ?)",
                (nazwa, kod),
            )
            db.commit()
        except Exception:
            return jsonify({"error": "Produkt already exists"}), 409
    return jsonify({"ok": True, "id": cur.lastrowid})


@zbiorniki_bp.route("/api/produkty/<int:pid>", methods=["PUT"])
@role_required("admin")
def api_produkty_update(pid):
    data = request.get_json(silent=True) or {}
    allowed = {"nazwa", "kod", "aktywny"}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates:
        return jsonify({"ok": True})
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with db_session() as db:
        db.execute(f"UPDATE produkty SET {set_clause} WHERE id = ?", [*updates.values(), pid])
        db.commit()
    return jsonify({"ok": True})


@zbiorniki_bp.route("/admin/produkty")
@role_required("admin")
def admin_produkty():
    return render_template("admin/produkty.html")
