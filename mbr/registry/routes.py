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
from mbr.shared.filters import parse_decimal


@registry_bp.route("/api/registry")
@login_required
def api_registry():
    produkt = request.args.get("produkt", "Chegina_K7")
    typ = request.args.get("typ", "")
    offset = request.args.get("offset", 0, type=int)
    limit = 50
    with db_session() as db:
        batches = list_completed_registry(db, produkt=produkt, typ=typ or None, limit=limit + 1, offset=offset)
        has_more = len(batches) > limit
        if has_more:
            batches = batches[:limit]
        columns = get_registry_columns(db, produkt)
    return jsonify({"batches": batches, "columns": columns, "produkt": produkt, "has_more": has_more, "offset": offset})


@registry_bp.route("/api/registry/<int:ebr_id>/cancel", methods=["POST"])
@role_required("admin")
def api_cancel_batch(ebr_id):
    """Soft-delete a completed batch (set status='cancelled'). Admin only."""
    with db_session() as db:
        row = db.execute(
            "SELECT ebr_id, batch_id, status FROM ebr_batches WHERE ebr_id = ?",
            (ebr_id,),
        ).fetchone()
        if not row:
            return jsonify({"error": "Batch not found"}), 404
        if row["status"] != "completed":
            return jsonify({"error": "Only completed batches can be cancelled"}), 400

        next_seq = db.execute(
            "SELECT COALESCE(MAX(sync_seq), 0) + 1 FROM ebr_batches"
        ).fetchone()[0]
        db.execute(
            "UPDATE ebr_batches SET status = 'cancelled', sync_seq = ? WHERE ebr_id = ?",
            (next_seq, ebr_id),
        )
        db.commit()
    return jsonify({"ok": True, "ebr_id": ebr_id, "batch_id": row["batch_id"]})


@registry_bp.route("/api/next-nr/<produkt>")
@login_required
def api_next_nr(produkt):
    with db_session() as db:
        nr = next_nr_partii(db, produkt)
    return jsonify({"nr_partii": nr})


@registry_bp.route("/api/batch-exists", methods=["POST"])
@login_required
def api_batch_exists():
    data = request.get_json(silent=True) or {}
    produkt = data.get("produkt", "")
    nr_partii = data.get("nr_partii", "")
    if not produkt or not nr_partii:
        return jsonify({"exists": False})
    batch_id = f"{produkt}__{nr_partii.replace('/', '_')}"
    with db_session() as db:
        row = db.execute(
            "SELECT 1 FROM ebr_batches WHERE batch_id = ?", (batch_id,)
        ).fetchone()
    return jsonify({"exists": bool(row)})


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
        "km": parse_decimal(request.form.get("km", 0)),
        "stawka": parse_decimal(request.form.get("stawka", 0.8358), default=0.8358),
        "cel": request.form.get("cel", ""),
    }
    data["kwota"] = round(data["km"] * data["stawka"], 2)
    pdf_bytes = generate_wniosek_dojazd_pdf(data)
    return Response(pdf_bytes, mimetype="application/pdf",
                    headers={"Content-Disposition": "inline; filename=wniosek_dojazd.pdf"})


@registry_bp.route("/api/chzt/save", methods=["POST"])
@login_required
def api_chzt_save():
    """Save ChZT measurements to JSON file."""
    import json
    from pathlib import Path
    from datetime import datetime

    payload = request.get_json(force=True) or {}
    data_items = payload.get("data", [])
    if not data_items:
        return jsonify({"ok": False, "error": "Brak danych"}), 400

    today = date.today().isoformat()
    output = {
        "data": today,
        "dt_saved": datetime.now().isoformat(timespec="seconds"),
        "saved_by": session.get("user", {}).get("login", "unknown"),
        "punkty": data_items,
    }

    chzt_dir = Path(__file__).parent.parent.parent / "data" / "chzt"
    chzt_dir.mkdir(parents=True, exist_ok=True)
    filepath = chzt_dir / f"chzt_{today}.json"

    # If file exists for today, append index
    if filepath.exists():
        idx = 2
        while (chzt_dir / f"chzt_{today}_{idx}.json").exists():
            idx += 1
        filepath = chzt_dir / f"chzt_{today}_{idx}.json"

    filepath.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"ok": True, "file": filepath.name})


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
    titrants = _json.loads(d.pop("titrants_json"))
    stezenia = _json.loads(d.pop("stezenia_json") or "{}") if d.get("stezenia_json") else {}
    # Merge saved concentrations into titrant defaults
    for t in titrants:
        if t["id"] in stezenia:
            t["default"] = stezenia[t["id"]]
    d["titrants"] = titrants
    d["stezenia"] = stezenia
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


@registry_bp.route("/api/metody-miareczkowe/<int:method_id>/stezenia", methods=["PUT"])
@login_required
def api_metoda_stezenia(method_id):
    """Save titrant concentrations for a method. Body: {"T1": 0.1, "T2": 307.0}"""
    import json as _json
    data = request.get_json(silent=True) or {}
    with db_session() as db:
        db.execute(
            "UPDATE metody_miareczkowe SET stezenia_json=? WHERE id=?",
            (_json.dumps(data), method_id),
        )
        db.commit()
    return jsonify({"ok": True})


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
