"""
pipeline/routes.py — Admin API routes for analytical pipeline builder.

All routes require admin role. DB access via get_db().
"""

from flask import jsonify, request, session

from mbr.pipeline import pipeline_bp
from mbr.db import get_db
from mbr.pipeline import models as pm
from mbr.shared.decorators import role_required


# ---------------------------------------------------------------------------
# Stage catalog — etapy_analityczne
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/etapy", methods=["GET"])
@role_required("admin")
def list_etapy():
    db = get_db()
    try:
        rows = pm.list_etapy(db)
        return jsonify(rows)
    finally:
        db.close()


@pipeline_bp.route("/api/pipeline/etapy", methods=["POST"])
@role_required("admin")
def create_etap():
    data = request.get_json(force=True) or {}
    db = get_db()
    try:
        etap_id = pm.create_etap(
            db,
            kod=data["kod"],
            nazwa=data["nazwa"],
            typ_cyklu=data.get("typ_cyklu", "jednorazowy"),
            opis=data.get("opis"),
            kolejnosc_domyslna=data.get("kolejnosc_domyslna", 0),
        )
        db.commit()
        etap = pm.get_etap(db, etap_id)
        return jsonify(etap), 201
    finally:
        db.close()


@pipeline_bp.route("/api/pipeline/etapy/<int:etap_id>", methods=["GET"])
@role_required("admin")
def get_etap(etap_id):
    db = get_db()
    try:
        etap = pm.get_etap(db, etap_id)
        if etap is None:
            return jsonify({"error": "not found"}), 404
        parametry = pm.list_etap_parametry(db, etap_id)
        warunki = pm.list_etap_warunki(db, etap_id)
        korekty = pm.list_etap_korekty(db, etap_id)
        return jsonify({
            "etap": etap,
            "parametry": parametry,
            "warunki": warunki,
            "korekty": korekty,
        })
    finally:
        db.close()


@pipeline_bp.route("/api/pipeline/etapy/<int:etap_id>", methods=["PUT"])
@role_required("admin")
def update_etap(etap_id):
    data = request.get_json(force=True) or {}
    db = get_db()
    try:
        etap = pm.get_etap(db, etap_id)
        if etap is None:
            return jsonify({"error": "not found"}), 404
        pm.update_etap(db, etap_id, **data)
        db.commit()
        return jsonify(pm.get_etap(db, etap_id))
    finally:
        db.close()


@pipeline_bp.route("/api/pipeline/etapy/<int:etap_id>/deactivate", methods=["POST"])
@role_required("admin")
def deactivate_etap(etap_id):
    db = get_db()
    try:
        etap = pm.get_etap(db, etap_id)
        if etap is None:
            return jsonify({"error": "not found"}), 404
        pm.deactivate_etap(db, etap_id)
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Stage parameters — etap_parametry
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/etapy/<int:etap_id>/parametry", methods=["POST"])
@role_required("admin")
def add_parametr_to_etap(etap_id):
    data = request.get_json(force=True) or {}
    db = get_db()
    try:
        kwargs = {k: v for k, v in data.items() if k not in ("parametr_id", "kolejnosc")}
        ep_id = pm.add_etap_parametr(
            db,
            etap_id,
            data["parametr_id"],
            kolejnosc=data.get("kolejnosc", 0),
            **kwargs,
        )
        db.commit()
        rows = pm.list_etap_parametry(db, etap_id)
        row = next((r for r in rows if r["id"] == ep_id), None)
        return jsonify(row), 201
    finally:
        db.close()


@pipeline_bp.route("/api/pipeline/etapy/<int:etap_id>/parametry/<int:ep_id>", methods=["PUT"])
@role_required("admin")
def update_parametr_in_etap(etap_id, ep_id):
    data = request.get_json(force=True) or {}
    db = get_db()
    try:
        pm.update_etap_parametr(db, ep_id, **data)
        db.commit()
        rows = pm.list_etap_parametry(db, etap_id)
        row = next((r for r in rows if r["id"] == ep_id), None)
        return jsonify(row)
    finally:
        db.close()


@pipeline_bp.route("/api/pipeline/etapy/<int:etap_id>/parametry/<int:ep_id>", methods=["DELETE"])
@role_required("admin")
def remove_parametr_from_etap(etap_id, ep_id):
    db = get_db()
    try:
        pm.remove_etap_parametr(db, ep_id)
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Gate conditions — etap_warunki
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/etapy/<int:etap_id>/warunki", methods=["POST"])
@role_required("admin")
def add_warunek(etap_id):
    data = request.get_json(force=True) or {}
    db = get_db()
    try:
        wid = pm.add_etap_warunek(
            db,
            etap_id,
            data["parametr_id"],
            operator=data["operator"],
            wartosc=data["wartosc"],
            wartosc_max=data.get("wartosc_max"),
            opis_warunku=data.get("opis_warunku"),
        )
        db.commit()
        rows = pm.list_etap_warunki(db, etap_id)
        row = next((r for r in rows if r["id"] == wid), None)
        return jsonify(row), 201
    finally:
        db.close()


@pipeline_bp.route("/api/pipeline/warunki/<int:warunek_id>", methods=["DELETE"])
@role_required("admin")
def remove_warunek(warunek_id):
    db = get_db()
    try:
        pm.remove_etap_warunek(db, warunek_id)
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Corrections catalog — etap_korekty_katalog
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/etapy/<int:etap_id>/korekty", methods=["POST"])
@role_required("admin")
def add_korekta(etap_id):
    data = request.get_json(force=True) or {}
    db = get_db()
    try:
        kid = pm.add_etap_korekta(
            db,
            etap_id,
            substancja=data["substancja"],
            jednostka=data.get("jednostka", "kg"),
            wykonawca=data.get("wykonawca", "produkcja"),
            kolejnosc=data.get("kolejnosc", 0),
        )
        db.commit()
        rows = pm.list_etap_korekty(db, etap_id)
        row = next((r for r in rows if r["id"] == kid), None)
        return jsonify(row), 201
    finally:
        db.close()


@pipeline_bp.route("/api/pipeline/korekty/<int:korekta_id>", methods=["DELETE"])
@role_required("admin")
def remove_korekta(korekta_id):
    db = get_db()
    try:
        pm.remove_etap_korekta(db, korekta_id)
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Product pipeline — produkt_pipeline
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/produkt/<produkt>", methods=["GET"])
@role_required("admin")
def get_pipeline(produkt):
    db = get_db()
    try:
        rows = pm.get_produkt_pipeline(db, produkt)
        return jsonify(rows)
    finally:
        db.close()


@pipeline_bp.route("/api/pipeline/produkt/<produkt>/etapy", methods=["POST"])
@role_required("admin")
def add_etap_to_pipeline(produkt):
    data = request.get_json(force=True) or {}
    db = get_db()
    try:
        pm.set_produkt_pipeline(db, produkt, data["etap_id"], kolejnosc=data.get("kolejnosc", 0))
        db.commit()
        rows = pm.get_produkt_pipeline(db, produkt)
        return jsonify(rows), 201
    finally:
        db.close()


@pipeline_bp.route("/api/pipeline/produkt/<produkt>/etapy/<int:etap_id>", methods=["DELETE"])
@role_required("admin")
def remove_etap_from_pipeline(produkt, etap_id):
    db = get_db()
    try:
        pm.remove_pipeline_etap(db, produkt, etap_id)
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


@pipeline_bp.route("/api/pipeline/produkt/<produkt>/reorder", methods=["PUT"])
@role_required("admin")
def reorder_pipeline(produkt):
    data = request.get_json(force=True) or {}
    etap_ids = data.get("etap_ids", [])
    db = get_db()
    try:
        pm.reorder_pipeline(db, produkt, etap_ids)
        db.commit()
        rows = pm.get_produkt_pipeline(db, produkt)
        return jsonify(rows)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Product limit overrides — produkt_etap_limity
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/produkt/<produkt>/etapy/<int:etap_id>/limity", methods=["PUT"])
@role_required("admin")
def set_limity(produkt, etap_id):
    data = request.get_json(force=True) or {}
    overrides = data.get("overrides", [])
    remove = data.get("remove", [])
    db = get_db()
    try:
        for ovr in overrides:
            kwargs = {k: v for k, v in ovr.items() if k != "parametr_id"}
            pm.set_produkt_etap_limit(db, produkt, etap_id, ovr["parametr_id"], **kwargs)
        for parametr_id in remove:
            pm.remove_produkt_etap_limit(db, produkt, etap_id, parametr_id)
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


@pipeline_bp.route("/api/pipeline/produkt/<produkt>/etapy/<int:etap_id>/resolved", methods=["GET"])
@role_required("admin")
def get_resolved_limity(produkt, etap_id):
    db = get_db()
    try:
        rows = pm.resolve_limity(db, produkt, etap_id)
        return jsonify(rows)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Admin UI pages (stub templates)
# ---------------------------------------------------------------------------

@pipeline_bp.route("/admin/pipeline", methods=["GET"])
@role_required("admin")
def etapy_katalog():
    from flask import render_template
    return render_template("pipeline/etapy_katalog.html")


@pipeline_bp.route("/admin/pipeline/etap/<int:etap_id>", methods=["GET"])
@role_required("admin")
def etap_edit(etap_id):
    from flask import render_template
    return render_template("pipeline/etap_edit.html", etap_id=etap_id)


@pipeline_bp.route("/admin/pipeline/produkt/<produkt>", methods=["GET"])
@role_required("admin")
def pipeline_edit(produkt):
    from flask import render_template
    return render_template("pipeline/pipeline_edit.html", produkt=produkt)
