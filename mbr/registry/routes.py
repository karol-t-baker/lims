"""
registry/routes.py — Routes for completed batch registry, export, and tools.
"""

import csv
import io
from datetime import date

from flask import Response, jsonify, render_template, request, session

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


@registry_bp.route("/narzedzia/metody")
@login_required
def narzedzia_metody():
    return render_template("technolog/narzedzia_metody.html")


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


# ---------------------------------------------------------------------------
# Titration methods + correction calculators
# ---------------------------------------------------------------------------

@registry_bp.route("/api/metody-miareczkowe")
@login_required
def api_metody_list():
    """List all active titration methods."""
    with db_session() as db:
        rows = db.execute(
            "SELECT * FROM metody_miareczkowe WHERE aktywna=1 ORDER BY nazwa"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@registry_bp.route("/api/metody-miareczkowe/<int:method_id>")
@login_required
def api_metoda_detail(method_id):
    """Get single method with parsed JSON fields."""
    import json as _json
    with db_session() as db:
        row = db.execute("SELECT * FROM metody_miareczkowe WHERE id=?", (method_id,)).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    d = dict(row)
    d["volumes"] = _json.loads(d.pop("volumes_json"))
    d["titrants"] = _json.loads(d.pop("titrants_json"))
    # Add suggested mass from most common nawazka for this method
    with db_session() as db2:
        naw_row = db2.execute(
            """SELECT nawazka_g FROM parametry_etapy pe
               JOIN parametry_analityczne pa ON pe.parametr_id = pa.id
               WHERE pa.metoda_id = ? AND pe.nawazka_g IS NOT NULL
               LIMIT 1""",
            (method_id,),
        ).fetchone()
    d["suggested_mass"] = naw_row["nawazka_g"] if naw_row else None
    return jsonify(d)


@registry_bp.route("/api/corrections")
@login_required
def api_corrections():
    """Return correction calculator configs."""
    import json as _json
    from pathlib import Path
    p = Path(__file__).parent.parent.parent / "data" / "corrections.json"
    if not p.exists():
        return jsonify({})
    return jsonify(_json.loads(p.read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# User settings
# ---------------------------------------------------------------------------

@registry_bp.route("/ustawienia")
@login_required
def ustawienia():
    user_login = session["user"]["login"]
    with db_session() as db:
        rows = db.execute(
            "SELECT key, value FROM user_settings WHERE login=?", (user_login,)
        ).fetchall()
    settings = {r["key"]: r["value"] for r in rows}
    return render_template("ustawienia.html", settings=settings)


@registry_bp.route("/api/settings", methods=["POST"])
@login_required
def api_settings_save():
    data = request.get_json(silent=True) or {}
    user_login = session["user"]["login"]
    with db_session() as db:
        for key, value in data.items():
            db.execute(
                """INSERT INTO user_settings (login, key, value) VALUES (?, ?, ?)
                   ON CONFLICT(login, key) DO UPDATE SET value=excluded.value""",
                (user_login, key, value),
            )
        db.commit()
    return jsonify({"ok": True})
