"""Certificate routes for the certs blueprint."""

from pathlib import Path

from flask import Response, abort, jsonify, request, send_file, session

from mbr.certs import certs_bp
from mbr.certs.generator import generate_certificate_pdf, get_required_fields, get_variants, save_certificate_pdf, save_certificate_data
from mbr.certs.models import create_swiadectwo, list_swiadectwa
from mbr.db import db_session
from mbr.models import get_ebr, get_ebr_wyniki, get_mbr
from mbr.shared.decorators import login_required


# ---------------------------------------------------------------------------
# Certificate API
# ---------------------------------------------------------------------------

@certs_bp.route("/api/cert/templates")
@login_required
def api_cert_templates():
    produkt = request.args.get("produkt", "")
    if not produkt:
        return jsonify({"templates": []})
    variants = get_variants(produkt)
    templates = []
    for v in variants:
        templates.append({
            "filename": v["id"],
            "display": v["label"],
            "flags": v["flags"],
            "required_fields": get_required_fields(produkt, v["id"]),
        })
    return jsonify({"templates": templates})


@certs_bp.route("/api/cert/generate", methods=["POST"])
@login_required
def api_cert_generate():
    data = request.get_json(silent=True) or {}
    ebr_id = data.get("ebr_id")
    variant_id = data.get("variant_id") or data.get("template_name")
    extra_fields = data.get("extra_fields", {})

    if not ebr_id or not variant_id:
        return jsonify({"ok": False, "error": "Missing ebr_id or variant_id"}), 400

    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        if not ebr:
            return jsonify({"ok": False, "error": "EBR not found"}), 404

        wyniki = get_ebr_wyniki(db, ebr_id)
        wyniki_flat = {}
        for sekcja_data in wyniki.values():
            for kod, row in sekcja_data.items():
                wyniki_flat[kod] = row

        # Resolve wystawil — prefer explicit from request, fallback to shift/session
        wystawil = (data.get("wystawil") or "").strip()
        if not wystawil:
            shift_ids = session.get("shift_workers", [])
            if shift_ids:
                workers = []
                for wid in shift_ids:
                    w = db.execute("SELECT imie, nazwisko FROM workers WHERE id=?", (wid,)).fetchone()
                    if w:
                        workers.append(w["imie"] + " " + w["nazwisko"])
                wystawil = ", ".join(workers) if workers else session["user"]["login"]
            else:
                wystawil = session["user"]["login"]

        # Find variant label for filename
        variants = get_variants(ebr["produkt"])
        variant_label = variant_id
        for v in variants:
            if v["id"] == variant_id:
                variant_label = v["label"]
                break

        try:
            pdf_bytes = generate_certificate_pdf(
                ebr["produkt"], variant_id, ebr["nr_partii"],
                ebr.get("dt_start"), wyniki_flat, extra_fields,
            )
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

        # Read user's configured output path
        user_login = session["user"]["login"]
        setting_row = db.execute(
            "SELECT value FROM user_settings WHERE login=? AND key='cert_output_dir'",
            (user_login,),
        ).fetchone()
        output_dir = setting_row["value"] if setting_row else None

        # Save PDF to user's configured path (or ~/Desktop/)
        pdf_path = save_certificate_pdf(pdf_bytes, ebr["produkt"], variant_label, ebr["nr_partii"], output_dir)

        # Save generation data to archive (for regeneration)
        import json as _json
        generation_data = {
            "produkt": ebr["produkt"],
            "variant_id": variant_id,
            "variant_label": variant_label,
            "nr_partii": ebr["nr_partii"],
            "dt_start": ebr.get("dt_start"),
            "wyniki_flat": {k: {"wartosc": v.get("wartosc"), "w_limicie": v.get("w_limicie")} for k, v in wyniki_flat.items()},
            "extra_fields": extra_fields,
            "wystawil": wystawil,
        }
        data_path = save_certificate_data(ebr["produkt"], variant_label, ebr["nr_partii"], generation_data)

        cert_id = create_swiadectwo(db, ebr_id, variant_label, ebr["nr_partii"], pdf_path, wystawil, data_json=_json.dumps(generation_data, ensure_ascii=False))

    return jsonify({"ok": True, "cert_id": cert_id, "pdf_path": pdf_path})


@certs_bp.route("/api/cert/<int:cert_id>", methods=["DELETE"])
@login_required
def api_cert_delete(cert_id):
    with db_session() as db:
        row = db.execute("SELECT pdf_path FROM swiadectwa WHERE id = ?", (cert_id,)).fetchone()
        if row is None:
            return jsonify({"error": "not found"}), 404
        # Delete PDF file — validate path stays within project
        project_root = Path(__file__).parent.parent.parent
        pdf_path = (project_root / row["pdf_path"]).resolve()
        if not str(pdf_path).startswith(str(project_root.resolve())):
            return jsonify({"error": "invalid path"}), 400
        if pdf_path.exists():
            pdf_path.unlink()
        # Delete DB record
        db.execute("DELETE FROM swiadectwa WHERE id = ?", (cert_id,))
        db.commit()
    return jsonify({"ok": True})


@certs_bp.route("/api/cert/<int:cert_id>/pdf")
@login_required
def api_cert_pdf(cert_id):
    with db_session() as db:
        row = db.execute(
            "SELECT * FROM swiadectwa WHERE id = ?", (cert_id,)
        ).fetchone()
    if row is None:
        return "Nie znaleziono świadectwa", 404
    pdf_path = Path(row["pdf_path"])
    # Support both absolute paths (new) and relative paths (legacy)
    if not pdf_path.is_absolute():
        project_root = Path(__file__).parent.parent.parent
        pdf_path = (project_root / pdf_path).resolve()
    if not pdf_path.exists():
        return "Plik PDF nie istnieje. Sprawdź ścieżkę w Ustawieniach.", 404
    return send_file(str(pdf_path), mimetype="application/pdf")


@certs_bp.route("/api/cert/list")
@login_required
def api_cert_list():
    ebr_id = request.args.get("ebr_id", type=int)
    if not ebr_id:
        return jsonify({"certs": []})
    with db_session() as db:
        certs = list_swiadectwa(db, ebr_id)
    return jsonify({"certs": certs})


# ---------------------------------------------------------------------------
# PDF routes
# ---------------------------------------------------------------------------

from mbr.pdf_gen import generate_pdf  # noqa: E402


@certs_bp.route("/pdf/mbr/<int:mbr_id>")
@login_required
def pdf_mbr(mbr_id):
    """Empty card from MBR template."""
    with db_session() as db:
        mbr = get_mbr(db, mbr_id)
    if not mbr:
        abort(404)
    pdf_bytes = generate_pdf(mbr)
    return Response(pdf_bytes, mimetype="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=MBR_{mbr['produkt']}_v{mbr['wersja']}.pdf"})


@certs_bp.route("/pdf/ebr/<int:ebr_id>")
@login_required
def pdf_ebr(ebr_id):
    """Filled card from EBR + MBR."""
    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        if not ebr:
            abort(404)
        mbr = get_mbr(db, ebr["mbr_id"])
        wyniki = get_ebr_wyniki(db, ebr_id)
    pdf_bytes = generate_pdf(mbr, ebr, wyniki)
    return Response(pdf_bytes, mimetype="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=EBR_{ebr['batch_id']}.pdf"})
