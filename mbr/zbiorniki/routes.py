"""zbiorniki/routes.py — API endpoints for tank management."""

from flask import jsonify, request, render_template, redirect, url_for

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
    typ_filter = request.args.get("typ", "")
    with db_session() as db:
        sql = "SELECT * FROM produkty"
        params = []
        conditions = []
        if not include_all:
            conditions.append("aktywny = 1")
        if typ_filter:
            conditions.append("typy LIKE ?")
            params.append(f'%"{typ_filter}"%')
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY nazwa"
        rows = [dict(r) for r in db.execute(sql, params).fetchall()]
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
    allowed = {"nazwa", "kod", "aktywny", "typy"}
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


# ── Substraty API ──

@zbiorniki_bp.route("/api/substraty")
@login_required
def api_substraty():
    produkt = request.args.get("produkt", "")
    include_all = request.args.get("all") == "1"
    with db_session() as db:
        if produkt:
            rows = db.execute("""
                SELECT s.* FROM substraty s
                WHERE s.aktywny = 1 AND (
                    s.id IN (SELECT substrat_id FROM substrat_produkty WHERE produkt = ?)
                    OR s.id NOT IN (SELECT substrat_id FROM substrat_produkty)
                )
                ORDER BY s.nazwa
            """, (produkt,)).fetchall()
        else:
            sql = "SELECT * FROM substraty"
            if not include_all:
                sql += " WHERE aktywny = 1"
            sql += " ORDER BY nazwa"
            rows = db.execute(sql).fetchall()
        result = [dict(r) for r in rows]
        if include_all:
            for sub in result:
                links = db.execute(
                    "SELECT produkt FROM substrat_produkty WHERE substrat_id = ?",
                    (sub["id"],)
                ).fetchall()
                sub["produkty"] = [r["produkt"] for r in links]
    return jsonify(result)


@zbiorniki_bp.route("/api/substraty", methods=["POST"])
@role_required("admin")
def api_substraty_create():
    data = request.get_json(silent=True) or {}
    nazwa = data.get("nazwa", "").strip()
    if not nazwa:
        return jsonify({"error": "nazwa required"}), 400
    with db_session() as db:
        try:
            cur = db.execute("INSERT INTO substraty (nazwa) VALUES (?)", (nazwa,))
            db.commit()
        except Exception:
            return jsonify({"error": "Substrat already exists"}), 409
    return jsonify({"ok": True, "id": cur.lastrowid})


@zbiorniki_bp.route("/api/substraty/<int:sid>", methods=["PUT"])
@role_required("admin")
def api_substraty_update(sid):
    data = request.get_json(silent=True) or {}
    allowed = {"nazwa", "aktywny"}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates:
        return jsonify({"ok": True})
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with db_session() as db:
        db.execute(f"UPDATE substraty SET {set_clause} WHERE id = ?", [*updates.values(), sid])
        db.commit()
    return jsonify({"ok": True})


@zbiorniki_bp.route("/api/substraty/<int:sid>/produkty", methods=["PUT"])
@role_required("admin")
def api_substraty_produkty(sid):
    data = request.get_json(silent=True) or {}
    produkty = data.get("produkty", [])
    with db_session() as db:
        db.execute("DELETE FROM substrat_produkty WHERE substrat_id = ?", (sid,))
        for p in produkty:
            db.execute("INSERT INTO substrat_produkty (substrat_id, produkt) VALUES (?, ?)", (sid, p))
        db.commit()
    return jsonify({"ok": True})


@zbiorniki_bp.route("/admin/substraty")
@role_required("admin")
def admin_substraty():
    return render_template("admin/substraty.html")


# ── Normy Admin ──

@zbiorniki_bp.route("/admin/normy")
@role_required("admin")
def admin_normy():
    return render_template("admin/normy.html")

@zbiorniki_bp.route("/api/normy/<produkt>")
@role_required("admin")
def api_normy(produkt):
    with db_session() as db:
        rows = db.execute("""
            SELECT pe.id, pe.parametr_id, pa.kod, pa.label, pa.skrot, pa.typ, pa.jednostka,
                   pe.min_limit, pe.max_limit, pe.target, pe.nawazka_g, pe.kolejnosc
            FROM parametry_etapy pe
            JOIN parametry_analityczne pa ON pa.id = pe.parametr_id
            WHERE pe.kontekst = 'analiza_koncowa' AND (pe.produkt = ? OR pe.produkt IS NULL)
            ORDER BY pe.kolejnosc
        """, (produkt,)).fetchall()
    return jsonify([dict(r) for r in rows])

@zbiorniki_bp.route("/api/normy/<int:binding_id>", methods=["PUT"])
@role_required("admin")
def api_normy_update(binding_id):
    data = request.get_json(silent=True) or {}
    allowed = {"min_limit", "max_limit", "target"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"ok": True})
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with db_session() as db:
        db.execute(f"UPDATE parametry_etapy SET {set_clause} WHERE id = ?",
                   [*updates.values(), binding_id])
        db.commit()
    return jsonify({"ok": True})


# ── Parametry Admin ──

@zbiorniki_bp.route("/admin/parametry")
@role_required("admin")
def admin_parametry():
    return redirect(url_for("parametry.parametry_editor"))

@zbiorniki_bp.route("/api/parametry/all")
@role_required("admin")
def api_parametry_all():
    with db_session() as db:
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM parametry_analityczne ORDER BY kod"
        ).fetchall()]
    return jsonify(rows)

@zbiorniki_bp.route("/api/parametry/admin/<int:pid>", methods=["PUT"])
@role_required("admin")
def api_parametry_admin_update(pid):
    data = request.get_json(silent=True) or {}
    allowed = {"label", "skrot", "typ", "jednostka", "precision", "aktywny"}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates:
        return jsonify({"ok": True})
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with db_session() as db:
        db.execute(f"UPDATE parametry_analityczne SET {set_clause} WHERE id = ?",
                   [*updates.values(), pid])
        db.commit()
    return jsonify({"ok": True})

@zbiorniki_bp.route("/api/parametry/admin", methods=["POST"])
@role_required("admin")
def api_parametry_admin_create():
    data = request.get_json(silent=True) or {}
    kod = data.get("kod", "").strip()
    label = data.get("label", "").strip()
    typ = data.get("typ", "bezposredni")
    if not kod or not label:
        return jsonify({"error": "kod and label required"}), 400
    with db_session() as db:
        try:
            cur = db.execute(
                "INSERT INTO parametry_analityczne (kod, label, typ, jednostka, precision) VALUES (?, ?, ?, ?, ?)",
                (kod, label, typ, data.get("jednostka", ""), data.get("precision", 2)),
            )
            db.commit()
        except Exception:
            return jsonify({"error": "Parametr already exists"}), 409
    return jsonify({"ok": True, "id": cur.lastrowid})


# ── Etapy Admin ──

@zbiorniki_bp.route("/admin/etapy")
@role_required("admin")
def admin_etapy():
    return render_template("admin/etapy.html")

@zbiorniki_bp.route("/api/etapy-procesowe")
@role_required("admin")
def api_etapy_list():
    with db_session() as db:
        etapy = [dict(r) for r in db.execute("SELECT * FROM etapy_procesowe ORDER BY kod").fetchall()]
        bindings = [dict(r) for r in db.execute("SELECT * FROM produkt_etapy ORDER BY produkt, kolejnosc").fetchall()]
    return jsonify({"etapy": etapy, "bindings": bindings})

@zbiorniki_bp.route("/api/etapy-procesowe/<int:eid>", methods=["PUT"])
@role_required("admin")
def api_etapy_update(eid):
    data = request.get_json(silent=True) or {}
    allowed = {"label", "aktywny"}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates:
        return jsonify({"ok": True})
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with db_session() as db:
        db.execute(f"UPDATE etapy_procesowe SET {set_clause} WHERE id = ?", [*updates.values(), eid])
        db.commit()
    return jsonify({"ok": True})

@zbiorniki_bp.route("/api/etapy-procesowe", methods=["POST"])
@role_required("admin")
def api_etapy_create():
    data = request.get_json(silent=True) or {}
    kod = data.get("kod", "").strip()
    label = data.get("label", "").strip()
    if not kod or not label:
        return jsonify({"error": "kod and label required"}), 400
    with db_session() as db:
        try:
            cur = db.execute("INSERT INTO etapy_procesowe (kod, label) VALUES (?, ?)", (kod, label))
            db.commit()
        except Exception:
            return jsonify({"error": "Etap already exists"}), 409
    return jsonify({"ok": True, "id": cur.lastrowid})
