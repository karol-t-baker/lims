from datetime import date

from flask import jsonify, request, Response

from mbr.db import db_session
from mbr.shared.decorators import login_required
from mbr.paliwo import paliwo_bp
from mbr.paliwo.models import (
    list_osoby, init_paliwo_tables, add_osoba, update_osoba, delete_osoba,
    calculate, last_workday, MIESIACE, generate_pdf, get_osoba,
)


@paliwo_bp.route("/api/paliwo/osoby")
@login_required
def api_paliwo_osoby():
    with db_session() as db:
        init_paliwo_tables(db)
        return jsonify({"osoby": list_osoby(db)})


@paliwo_bp.route("/api/paliwo/osoby", methods=["POST"])
@login_required
def api_paliwo_add_osoba():
    data = request.get_json(silent=True) or {}
    with db_session() as db:
        init_paliwo_tables(db)
        osoba_id = add_osoba(db, data.get("imie_nazwisko", ""), data.get("stanowisko", ""), data.get("nr_rejestracyjny", ""))
    return jsonify({"ok": True, "id": osoba_id})


@paliwo_bp.route("/api/paliwo/osoby/<int:osoba_id>", methods=["PUT"])
@login_required
def api_paliwo_update_osoba(osoba_id):
    data = request.get_json(silent=True) or {}
    with db_session() as db:
        update_osoba(db, osoba_id, data.get("imie_nazwisko", ""), data.get("stanowisko", ""), data.get("nr_rejestracyjny", ""))
    return jsonify({"ok": True})


@paliwo_bp.route("/api/paliwo/osoby/<int:osoba_id>", methods=["DELETE"])
@login_required
def api_paliwo_delete_osoba(osoba_id):
    with db_session() as db:
        delete_osoba(db, osoba_id)
    return jsonify({"ok": True})


@paliwo_bp.route("/api/paliwo/oblicz")
@login_required
def api_paliwo_oblicz():
    dni = int(request.args.get("dni", 0))
    today = date.today()
    calc = calculate(dni)
    lwd = last_workday(today.year, today.month)
    calc["miesiac"] = MIESIACE[today.month]
    calc["data_wystawienia"] = lwd.strftime("%d.%m.%Y")
    return jsonify(calc)


@paliwo_bp.route("/api/paliwo/generuj", methods=["POST"])
@login_required
def api_paliwo_generuj():
    data = request.get_json(silent=True) or {}
    osoby_data = data.get("osoby", [])
    if not osoby_data:
        # Backwards compat: single person
        osoby_data = [{"osoba_id": data.get("osoba_id"), "dni_urlopu": int(data.get("dni_urlopu", 0))}]
    with db_session() as db:
        init_paliwo_tables(db)
        osoby = []
        dni_list = []
        for od in osoby_data:
            osoba = get_osoba(db, od["osoba_id"])
            if not osoba:
                return jsonify({"ok": False, "error": f"Osoba {od['osoba_id']} nie znaleziona"}), 404
            osoby.append(osoba)
            dni_list.append(int(od.get("dni_urlopu", 0)))
    try:
        pdf_bytes = generate_pdf(osoby, dni_list)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return Response(pdf_bytes, mimetype="application/pdf",
                    headers={"Content-Disposition": "inline; filename=wniosek_paliwo.pdf"})
