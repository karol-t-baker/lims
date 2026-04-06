"""Routes for process stage analyses, corrections, and stage status."""

from flask import request, session, jsonify

from mbr.db import db_session
from mbr.models import get_ebr
from mbr.shared.decorators import login_required
from mbr.etapy import etapy_bp
from mbr.etapy.models import (
    get_all_etapy_analizy,
    save_etap_analizy,
    get_korekty,
    add_korekta,
    confirm_korekta,
    get_etapy_status,
    zatwierdz_etap,
)


@etapy_bp.route("/api/etapy-config/<produkt>")
@login_required
def api_etapy_config(produkt):
    from mbr.parametry_registry import get_etapy_config
    with db_session() as db:
        cfg = get_etapy_config(db, produkt)
    return jsonify({"config": cfg, "produkt": produkt})


@etapy_bp.route("/api/ebr/<int:ebr_id>/etapy-analizy")
@login_required
def api_etapy_analizy_get(ebr_id):
    with db_session() as db:
        data = get_all_etapy_analizy(db, ebr_id)
    return jsonify({"analizy": data})


@etapy_bp.route("/api/ebr/<int:ebr_id>/etapy-analizy", methods=["POST"])
@login_required
def api_etapy_analizy_save(ebr_id):
    data = request.get_json(silent=True) or {}
    etap = data.get("etap")
    runda = int(data.get("runda", 1))
    krok = int(data.get("krok", 1))
    wyniki = data.get("wyniki", {})
    if not etap or not wyniki:
        return jsonify({"ok": False, "error": "Missing etap or wyniki"}), 400
    user = session.get("user", {}).get("login", "unknown")
    with db_session() as db:
        save_etap_analizy(db, ebr_id, etap, runda, wyniki, user, krok=krok)
    return jsonify({"ok": True})


@etapy_bp.route("/api/ebr/<int:ebr_id>/korekty")
@login_required
def api_korekty_get(ebr_id):
    etap = request.args.get("etap")
    with db_session() as db:
        data = get_korekty(db, ebr_id, etap=etap)
    return jsonify({"korekty": data})


@etapy_bp.route("/api/ebr/<int:ebr_id>/korekty", methods=["POST"])
@login_required
def api_korekty_add(ebr_id):
    data = request.get_json(silent=True) or {}
    etap = data.get("etap")
    substancja = data.get("substancja")
    ilosc_kg = float(data.get("ilosc_kg", 0))
    po_rundzie = int(data.get("po_rundzie", 0))
    if not etap or not substancja:
        return jsonify({"ok": False, "error": "Missing etap or substancja"}), 400
    user = session.get("user", {}).get("login", "unknown")
    with db_session() as db:
        kid = add_korekta(db, ebr_id, etap, po_rundzie, substancja, ilosc_kg, user)
    return jsonify({"ok": True, "id": kid})


@etapy_bp.route("/api/ebr/<int:ebr_id>/korekty/<int:kid>", methods=["PUT"])
@login_required
def api_korekty_confirm(ebr_id, kid):
    with db_session() as db:
        confirm_korekta(db, kid)
    return jsonify({"ok": True})


@etapy_bp.route("/api/ebr/<int:ebr_id>/etapy-status")
@login_required
def api_etapy_status_get(ebr_id):
    with db_session() as db:
        data = get_etapy_status(db, ebr_id)
    return jsonify({"etapy_status": data})


@etapy_bp.route("/api/ebr/<int:ebr_id>/etapy-status/zatwierdz", methods=["POST"])
@login_required
def api_etapy_zatwierdz(ebr_id):
    data = request.get_json(silent=True) or {}
    etap = data.get("etap")
    if not etap:
        return jsonify({"ok": False, "error": "Missing etap"}), 400
    user = session.get("user", {}).get("login", "unknown")
    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        if not ebr:
            return jsonify({"ok": False, "error": "EBR not found"}), 404
        next_etap = zatwierdz_etap(db, ebr_id, etap, user, ebr["produkt"])
    return jsonify({"ok": True, "next_etap": next_etap})
