"""
registry/routes.py — Routes for completed batch registry, export, and tools.
"""

import csv
import io
from datetime import date

from flask import Response, jsonify, render_template, request

from mbr.db import db_session
from mbr.models import next_nr_partii
from mbr.registry import registry_bp
from mbr.registry.models import export_wyniki_csv, get_registry_columns, list_completed_registry
from mbr.shared.decorators import login_required, role_required


@registry_bp.route("/api/registry")
@login_required
def api_registry():
    produkt = request.args.get("produkt", "Chegina_K7")
    typ = request.args.get("typ", "")
    with db_session() as db:
        batches = list_completed_registry(db, produkt=produkt, typ=typ or None)
        columns = get_registry_columns(db, produkt)
    return jsonify({"batches": batches, "columns": columns, "produkt": produkt})


@registry_bp.route("/api/next-nr/<produkt>")
@login_required
def api_next_nr(produkt):
    with db_session() as db:
        nr = next_nr_partii(db, produkt)
    return jsonify({"nr_partii": nr})


@registry_bp.route("/narzedzia")
@login_required
def narzedzia():
    return render_template("technolog/narzedzia.html", today=date.today().isoformat())


@registry_bp.route("/narzedzia/wniosek-dojazd")
@login_required
def wniosek_dojazd():
    return render_template("technolog/wniosek_dojazd.html", today=date.today().isoformat())


@registry_bp.route("/narzedzia/wniosek-dojazd/pdf", methods=["POST"])
@login_required
def wniosek_dojazd_pdf():
    from mbr.pdf_gen import generate_wniosek_dojazd_pdf
    data = {
        "imie_nazwisko": request.form.get("imie_nazwisko", ""),
        "data": request.form.get("data", ""),
        "skad": request.form.get("skad", ""),
        "dokad": request.form.get("dokad", ""),
        "km": float(request.form.get("km", 0)),
        "stawka": float(request.form.get("stawka", 0.8358)),
        "cel": request.form.get("cel", ""),
    }
    data["kwota"] = round(data["km"] * data["stawka"], 2)
    pdf_bytes = generate_wniosek_dojazd_pdf(data)
    return Response(pdf_bytes, mimetype="application/pdf",
                    headers={"Content-Disposition": "inline; filename=wniosek_dojazd.pdf"})


@registry_bp.route("/technolog/export")
@role_required("technolog")
def tech_export():
    with db_session() as db:
        rows = export_wyniki_csv(db, request.args.get("produkt"))
    if not rows:
        return "Brak danych", 404
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=wyniki_ebr.csv"},
    )
