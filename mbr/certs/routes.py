"""Certificate routes for the certs blueprint."""

import json as _json
from pathlib import Path

from flask import Response, abort, jsonify, render_template, request, send_file, session

from mbr.certs import certs_bp
from mbr.certs.generator import generate_certificate_pdf, get_required_fields, get_variants, save_certificate_data, build_preview_context, _docxtpl_render, _gotenberg_convert
from mbr.certs.models import create_swiadectwo, list_swiadectwa, get_pipeline_wyniki_flat
from mbr.db import db_session
from mbr.models import get_ebr, get_ebr_wyniki, get_mbr
from mbr.shared.decorators import login_required, role_required


# ---------------------------------------------------------------------------
# Certificate API
# ---------------------------------------------------------------------------

@certs_bp.route("/api/cert/templates")
@login_required
def api_cert_templates():
    produkt = request.args.get("produkt", "")
    include_archived = request.args.get("include_archived") == "1"
    if not produkt:
        return jsonify({"templates": []})

    from mbr.certs.generator import get_cert_aliases
    variants = list(get_variants(produkt, include_archived=include_archived))
    with db_session() as db:
        aliases = get_cert_aliases(db, produkt)
        for target_produkt in aliases:
            variants.extend(get_variants(target_produkt, include_archived=include_archived))

        # Resolve default_expiry_months once per owner_produkt.
        expiry_cache: dict = {}
        def _expiry_for(p: str) -> int:
            if p in expiry_cache:
                return expiry_cache[p]
            row = db.execute(
                "SELECT expiry_months FROM produkty WHERE nazwa=?", (p,)
            ).fetchone()
            val = (row["expiry_months"] if row else None) or 12
            expiry_cache[p] = val
            return val

        templates = []
        for v in variants:
            templates.append({
                "filename": v["id"],
                "display": v["label"],
                "flags": v["flags"],
                "owner_produkt": v["owner_produkt"],
                "required_fields": get_required_fields(v["owner_produkt"], v["id"]),
                "default_expiry_months": _expiry_for(v["owner_produkt"]),
                "archived": v.get("archived", False),
            })
    return jsonify({"templates": templates})


@certs_bp.route("/api/cert/recipient-suggestions")
@login_required
def api_cert_recipient_suggestions():
    """Autocomplete source for recipient_name field in cert generate modal.

    Threshold: 2 chars to avoid noisy short queries. Case-insensitive LIKE,
    distinct values, ordered alphabetically, capped at 20.
    """
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"suggestions": []})
    with db_session() as db:
        rows = db.execute(
            "SELECT DISTINCT recipient_name FROM swiadectwa "
            "WHERE recipient_name IS NOT NULL "
            "AND recipient_name LIKE ? COLLATE NOCASE "
            "ORDER BY recipient_name LIMIT 20",
            (f"%{q}%",),
        ).fetchall()
    return jsonify({"suggestions": [r["recipient_name"] for r in rows]})


@certs_bp.route("/api/cert/variants/<int:variant_id>/archive-preview")
@role_required("admin")
def api_cert_variant_archive_preview(variant_id):
    """Stats for the archive-with-backfill modal in cert editor.

    Returns count of swiadectwa rows that would be touched by backfill
    (those with template_name=variant_id AND recipient_name IS NULL),
    plus a parsed suggestion derived from the variant label after em-dash.
    """
    with db_session() as db:
        vrow = db.execute(
            "SELECT variant_id, label FROM cert_variants WHERE id=?",
            (variant_id,)).fetchone()
        if not vrow:
            abort(404)
        count = db.execute(
            "SELECT COUNT(*) c FROM swiadectwa "
            "WHERE template_name=? AND recipient_name IS NULL",
            (vrow["variant_id"],)).fetchone()["c"]
    suggested = ""
    if "—" in (vrow["label"] or ""):
        suggested = vrow["label"].split("—", 1)[1].strip()
    return jsonify({"swiadectwa_count": count, "suggested_recipient": suggested})


@certs_bp.route("/api/cert/variants/<int:variant_id>/archive", methods=["POST"])
@role_required("admin")
def api_cert_variant_archive(variant_id):
    """Soft-archive a cert variant; optionally backfill recipient_name on old certs.

    Payload:
        archived: bool (true → archive, false → unarchive)
        backfill_recipient: str | null (only honored when archived=true;
            sanitized via _sanitize_filename_segment before UPDATE)

    Idempotent: backfill UPDATEs rows WHERE recipient_name IS NULL only,
    so existing non-null values are never overwritten.
    """
    from mbr.shared import audit
    from mbr.certs.generator import _sanitize_filename_segment as _sanitize

    payload = request.get_json(silent=True) or {}
    archived = bool(payload.get("archived", True))
    backfill = payload.get("backfill_recipient")

    backfill_count = 0
    with db_session() as db:
        vrow = db.execute(
            "SELECT variant_id, label FROM cert_variants WHERE id=?",
            (variant_id,)).fetchone()
        if not vrow:
            abort(404)

        db.execute("UPDATE cert_variants SET archived=? WHERE id=?",
                   (1 if archived else 0, variant_id))
        audit.log_event(
            audit.EVENT_CERT_VARIANT_ARCHIVED if archived else audit.EVENT_CERT_VARIANT_UNARCHIVED,
            entity_type="cert_variant",
            entity_id=variant_id,
            entity_label=vrow["label"],
            payload={"variant_id": vrow["variant_id"]},
            db=db,
        )

        if archived and backfill:
            cleaned = _sanitize(backfill)
            if cleaned:
                cur = db.execute(
                    "UPDATE swiadectwa SET recipient_name=? "
                    "WHERE template_name=? AND recipient_name IS NULL",
                    (cleaned, vrow["variant_id"]))
                backfill_count = cur.rowcount
                if backfill_count > 0:
                    audit.log_event(
                        audit.EVENT_CERT_RECIPIENT_BACKFILLED,
                        entity_type="cert_variant",
                        entity_id=variant_id,
                        entity_label=vrow["label"],
                        payload={
                            "variant_id": vrow["variant_id"],
                            "recipient_name": cleaned,
                            "count": backfill_count,
                        },
                        db=db,
                    )
        db.commit()

    return jsonify({"ok": True, "archived": archived,
                    "backfill_count": backfill_count})


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
        is_pakowanie = ebr.get("typ") == "szarza" and (ebr.get("pakowanie_bezposrednie") or "").strip() != ""
        if ebr.get("typ") not in ("zbiornik", "platkowanie") and not is_pakowanie:
            return jsonify({"ok": False, "error": "Świadectwa tylko dla zbiorników, płatkowania i pakowania bezpośredniego"}), 400

        # Resolve target_produkt (defaults to ebr.produkt for backward compat)
        requested_target = data.get("target_produkt") or ebr["produkt"]
        if requested_target != ebr["produkt"]:
            from mbr.certs.generator import get_cert_aliases
            if requested_target not in get_cert_aliases(db, ebr["produkt"]):
                return jsonify({"ok": False,
                                "error": f"no cert alias configured: "
                                         f"{ebr['produkt']}→{requested_target}"}), 400
        target_produkt = requested_target

        if is_pakowanie:
            wyniki_flat = get_pipeline_wyniki_flat(db, ebr_id)
        else:
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

        # Find variant label for filename — look up in target_produkt's variants
        variants = get_variants(target_produkt)
        variant_label = variant_id
        for v in variants:
            if v["id"] == variant_id:
                variant_label = v["label"]
                break

        # --- Resolve & sanitize runtime fields. ---
        from mbr.certs.generator import _sanitize_filename_segment
        recipient_raw = (extra_fields or {}).get("recipient_name", "")
        recipient_clean = _sanitize_filename_segment(recipient_raw) or None

        # Effective expiry: override (validated by build_context) or product default.
        expiry_override = (extra_fields or {}).get("expiry_months")
        if expiry_override is not None and str(expiry_override).strip() != "":
            try:
                effective_expiry = int(expiry_override)
            except (ValueError, TypeError):
                return jsonify({"ok": False,
                                "error": f"invalid expiry_months: {expiry_override!r}"}), 400
            if not (1 <= effective_expiry <= 30):
                return jsonify({"ok": False,
                                "error": "expiry_months out of range 1..30"}), 400
        else:
            prod_row = db.execute(
                "SELECT expiry_months FROM produkty WHERE nazwa=?", (target_produkt,)
            ).fetchone()
            effective_expiry = (prod_row["expiry_months"] if prod_row else None) or 12

        order_number = (extra_fields or {}).get("order_number", "") or ""
        has_order_number = bool(order_number.strip())

        # Mirror sanitized recipient back into extra_fields so build_context /
        # generate_certificate_pdf get the cleaned value (no template uses it,
        # but downstream snapshot in data_json does).
        if extra_fields is None:
            extra_fields = {}
        extra_fields["recipient_name"] = recipient_clean or ""

        try:
            pdf_bytes = generate_certificate_pdf(
                target_produkt, variant_id, ebr["nr_partii"],
                ebr.get("dt_start"), wyniki_flat, extra_fields,
                wystawil=wystawil,
            )
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

        # Save generation data to archive (for regeneration)
        import json as _json
        generation_data = {
            "produkt": ebr["produkt"],
            "target_produkt": target_produkt,
            "variant_id": variant_id,
            "variant_label": variant_label,
            "nr_partii": ebr["nr_partii"],
            "dt_start": ebr.get("dt_start"),
            "wyniki_flat": {k: {"wartosc": v.get("wartosc"), "wartosc_text": v.get("wartosc_text"), "w_limicie": v.get("w_limicie")} for k, v in wyniki_flat.items()},
            "extra_fields": extra_fields,
            "wystawil": wystawil,
            "recipient_name": recipient_clean,
            "expiry_months_used": effective_expiry,
        }
        save_certificate_data(
            target_produkt, variant_label, ebr["nr_partii"], generation_data,
            recipient_name=recipient_clean, has_order_number=has_order_number,
        )

        # Persist target_produkt ONLY when it differs from ebr.produkt — NULL otherwise
        persist_target = target_produkt if target_produkt != ebr["produkt"] else None
        cert_id = create_swiadectwo(
            db, ebr_id, variant_label, ebr["nr_partii"], "regenerate", wystawil,
            data_json=_json.dumps(generation_data, ensure_ascii=False),
            target_produkt=persist_target,
            recipient_name=recipient_clean,
            expiry_months_used=effective_expiry,
        )
        db.commit()

    # Return PDF as download
    nr_only = ebr['nr_partii'].split('/')[0].strip()
    filename = f"{variant_label} {nr_only}.pdf"
    import unicodedata
    fn_safe = filename.replace('\u2014', '-').replace('\u2013', '-')
    filename_ascii = unicodedata.normalize('NFKD', fn_safe).encode('ascii', 'ignore').decode('ascii')
    from urllib.parse import quote
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename_ascii}\"; filename*=UTF-8''{quote(filename)}",
            "X-Cert-Id": str(cert_id),
        },
    )


@certs_bp.route("/api/cert/<int:cert_id>", methods=["DELETE"])
@login_required
def api_cert_delete(cert_id):
    with db_session() as db:
        row = db.execute("SELECT pdf_path FROM swiadectwa WHERE id = ?", (cert_id,)).fetchone()
        if row is None:
            return jsonify({"error": "not found"}), 404
        # Delete PDF file — handle both absolute and relative paths
        pdf_path = Path(row["pdf_path"])
        if not pdf_path.is_absolute():
            project_root = Path(__file__).parent.parent.parent
            pdf_path = (project_root / pdf_path).resolve()
        try:
            if pdf_path.exists():
                pdf_path.unlink()
        except Exception:
            pass  # File may already be deleted or inaccessible
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

    # Try regenerating from saved data_json (no file on disk)
    if row["data_json"]:
        import json as _json
        try:
            gen = _json.loads(row["data_json"])
            # For aliased certs, gen["target_produkt"] drives the template.
            # Legacy archive entries may lack it — fall back to produkt.
            regen_produkt = gen.get("target_produkt") or gen["produkt"]
            pdf_bytes = generate_certificate_pdf(
                regen_produkt, gen["variant_id"], gen["nr_partii"],
                gen.get("dt_start"), gen.get("wyniki_flat", {}),
                gen.get("extra_fields", {}), wystawil=gen.get("wystawil", ""),
            )
            return Response(pdf_bytes, mimetype="application/pdf",
                           headers={"Content-Disposition": "inline"})
        except Exception as e:
            return f"Błąd regeneracji PDF: {e}", 500

    # Fallback: try reading from disk (legacy)
    pdf_path = Path(row["pdf_path"])
    if not pdf_path.is_absolute():
        project_root = Path(__file__).parent.parent.parent
        pdf_path = (project_root / pdf_path).resolve()
    if not pdf_path.exists() or pdf_path.is_dir():
        return "Plik PDF nie istnieje i brak danych do regeneracji.", 404
    return send_file(str(pdf_path), mimetype="application/pdf",
                     download_name=None, as_attachment=False)


@certs_bp.route("/api/cert/list")
@login_required
def api_cert_list():
    ebr_id = request.args.get("ebr_id", type=int)
    if not ebr_id:
        return jsonify({"certs": []})
    with db_session() as db:
        certs = list_swiadectwa(db, ebr_id)
    return jsonify({"certs": certs})


# Cert config parameter endpoints removed — replaced by /api/parametry/cert/* endpoints
# in mbr/parametry/routes.py (parametry centralization, 2026-04-09)


# ---------------------------------------------------------------------------
# Product CRUD for cert config editor (DB-backed)
# ---------------------------------------------------------------------------


@certs_bp.route("/admin/wzory-cert")
@role_required("admin", "kj")
def admin_wzory_cert():
    return render_template("admin/wzory_cert.html")


@certs_bp.route("/api/cert/config/products")
@role_required("admin", "kj")
def api_cert_config_products():
    """List all products that have cert variants defined (from DB)."""
    with db_session() as db:
        rows = db.execute("""
            SELECT p.nazwa as key, p.display_name, p.aktywny,
                   (SELECT COUNT(*) FROM parametry_cert pc WHERE pc.produkt=p.nazwa AND pc.variant_id IS NULL) as params_count,
                   (SELECT COUNT(*) FROM cert_variants cv WHERE cv.produkt=p.nazwa) as variants_count
            FROM produkty p
            WHERE EXISTS (SELECT 1 FROM cert_variants cv WHERE cv.produkt=p.nazwa)
            ORDER BY p.aktywny DESC, p.display_name
        """).fetchall()
    return jsonify({"ok": True, "products": [dict(r) for r in rows]})


# ---------------------------------------------------------------------------
# Cert alias CRUD (admin only)
# ---------------------------------------------------------------------------


@certs_bp.route("/api/cert/aliases", methods=["GET"])
@role_required("admin")
def api_cert_aliases_list():
    """List all cert-alias pairs."""
    with db_session() as db:
        rows = db.execute(
            "SELECT source_produkt, target_produkt FROM cert_alias "
            "ORDER BY source_produkt, target_produkt"
        ).fetchall()
    return jsonify({"aliases": [dict(r) for r in rows]})


@certs_bp.route("/api/cert/aliases", methods=["POST"])
@role_required("admin")
def api_cert_aliases_create():
    """Create a cert alias. Idempotent (INSERT OR IGNORE)."""
    data = request.get_json(silent=True) or {}
    source = (data.get("source_produkt") or "").strip()
    target = (data.get("target_produkt") or "").strip()
    if not source or not target:
        return jsonify({"error": "source_produkt and target_produkt required"}), 400
    if source == target:
        return jsonify({"error": "self-alias not allowed"}), 400
    with db_session() as db:
        target_row = db.execute(
            "SELECT 1 FROM produkty WHERE nazwa=?", (target,)
        ).fetchone()
        if not target_row:
            return jsonify({"error": f"target produkt not found: {target}"}), 404
        db.execute(
            "INSERT OR IGNORE INTO cert_alias (source_produkt, target_produkt) VALUES (?, ?)",
            (source, target),
        )
        db.commit()
    return jsonify({"ok": True})


@certs_bp.route("/api/cert/aliases/<source_produkt>/<target_produkt>", methods=["DELETE"])
@role_required("admin")
def api_cert_aliases_delete(source_produkt, target_produkt):
    """Delete a cert alias. Idempotent (no error if the row didn't exist)."""
    with db_session() as db:
        db.execute(
            "DELETE FROM cert_alias WHERE source_produkt=? AND target_produkt=?",
            (source_produkt, target_produkt),
        )
        db.commit()
    return jsonify({"ok": True})


@certs_bp.route("/api/cert/config/product/<key>")
@role_required("admin", "kj")
def api_cert_config_product_get(key):
    """Full product data from DB, same JSON shape as the old JSON-based endpoint."""
    with db_session() as db:
        prod_row = db.execute(
            "SELECT id, nazwa, display_name, spec_number, cas_number, expiry_months, opinion_pl, opinion_en "
            "FROM produkty WHERE nazwa = ?",
            (key,),
        ).fetchone()
        if not prod_row:
            return jsonify({"error": "Product not found"}), 404

        # Check that cert_variants exist for this product
        has_variants = db.execute(
            "SELECT 1 FROM cert_variants WHERE produkt = ? LIMIT 1", (key,)
        ).fetchone()
        if not has_variants:
            return jsonify({"error": "Product not found"}), 404

        # Build product object matching old JSON shape
        product = {
            "display_name": prod_row["display_name"] or key,
            "spec_number": prod_row["spec_number"] or "",
            "cas_number": prod_row["cas_number"] or "",
            "expiry_months": prod_row["expiry_months"] or 12,
            "opinion_pl": prod_row["opinion_pl"] or "",
            "opinion_en": prod_row["opinion_en"] or "",
        }

        # Bulk id → kod lookup avoids the per-removed-param N+1 query below.
        id_to_kod = {
            r["id"]: r["kod"] for r in db.execute(
                "SELECT id, kod FROM parametry_analityczne"
            ).fetchall()
        }

        # Base parameters (variant_id IS NULL)
        base_params = db.execute(
            "SELECT pc.parametr_id, pc.kolejnosc, pc.requirement, pc.format, "
            "pc.qualitative_result, pc.name_pl, pc.name_en, pc.method, "
            "pa.kod, pa.label AS pa_label, pa.name_en AS pa_name_en, "
            "pa.method_code AS pa_method_code, pa.precision AS pa_precision "
            "FROM parametry_cert pc "
            "JOIN parametry_analityczne pa ON pa.id = pc.parametr_id "
            "WHERE pc.produkt = ? AND pc.variant_id IS NULL "
            "ORDER BY pc.kolejnosc",
            (key,),
        ).fetchall()

        parameters = []
        base_kods: set[str] = set()
        for bp in base_params:
            # name_en: use DB value if explicitly set (even empty string means "no EN name"),
            # fall back to parametry_analityczne only if parametry_cert.name_en is NULL
            name_en = bp["name_en"] if bp["name_en"] is not None else (bp["pa_name_en"] or "")
            pid = bp["kod"] or f"param_{bp['parametr_id']}"
            base_kods.add(pid)
            param = {
                "id": pid,
                "parametr_id": bp["parametr_id"],
                "name_pl": bp["name_pl"] or bp["pa_label"] or "",
                "name_en": name_en,
                "requirement": bp["requirement"] or "",
                "method": bp["method"] or bp["pa_method_code"] or "",
                "format": bp["format"] or "1",
                "data_field": bp["kod"] or "",
                # Dual-field surface for the editor (Cert Editor Redesign A4 + A5):
                # globals always present, overrides preserved raw (None = inherit,
                # "" = explicit blank). Legacy fields above keep existing consumers working.
                "name_pl_global": bp["pa_label"] or "",
                "name_en_global": bp["pa_name_en"] or "",
                "method_global": bp["pa_method_code"] or "",
                "format_global": str(bp["pa_precision"]) if bp["pa_precision"] is not None else "",
                "name_pl_override": bp["name_pl"],
                "name_en_override": bp["name_en"],
                "method_override": bp["method"],
                "format_override": bp["format"],
            }
            if bp["qualitative_result"]:
                param["qualitative_result"] = bp["qualitative_result"]
            parameters.append(param)
        product["parameters"] = parameters

        # Variants — admin editor opts into archived rows via ?include_archived=1
        # so the "Pokaż archiwalne warianty" toggle in the UI can surface them.
        include_archived = request.args.get("include_archived") == "1"
        archived_filter = "" if include_archived else "AND COALESCE(archived,0)=0"
        variants_db = db.execute(
            f"SELECT * FROM cert_variants WHERE produkt=? {archived_filter} "
            f"ORDER BY kolejnosc",
            (key,),
        ).fetchall()

        variants = []
        for vr in variants_db:
            variant_obj = {
                "id": vr["variant_id"],
                "db_id": vr["id"],  # numeric PK — used by produkt_pola UI (scope=cert_variant)
                "label": vr["label"],
                "flags": _json.loads(vr["flags"] or "[]"),
                "archived": bool(vr["archived"]) if "archived" in vr.keys() else False,
            }
            overrides = {}
            if vr["spec_number"]:
                overrides["spec_number"] = vr["spec_number"]
            if vr["opinion_pl"]:
                overrides["opinion_pl"] = vr["opinion_pl"]
            if vr["opinion_en"]:
                overrides["opinion_en"] = vr["opinion_en"]
            if vr["avon_code"]:
                overrides["avon_code"] = vr["avon_code"]
            if vr["avon_name"]:
                overrides["avon_name"] = vr["avon_name"]

            remove_params_ids = _json.loads(vr["remove_params"] or "[]")
            if remove_params_ids:
                resolved = [
                    id_to_kod.get(pid) or f"param_{pid}" for pid in remove_params_ids
                ]
                # Hide stale refs (base param already gone) so the editor
                # doesn't surface them as live variant overrides.
                live = [k for k in resolved if k in base_kods]
                if live:
                    overrides["remove_parameters"] = live

            # Variant-specific add_parameters
            add_params_db = db.execute(
                "SELECT pc.*, pa.kod, pa.label AS pa_label, pa.name_en AS pa_name_en, "
                "pa.method_code AS pa_method_code, pa.precision AS pa_precision "
                "FROM parametry_cert pc "
                "JOIN parametry_analityczne pa ON pa.id = pc.parametr_id "
                "WHERE pc.variant_id = ? "
                "ORDER BY pc.kolejnosc",
                (vr["id"],),
            ).fetchall()

            if add_params_db:
                add_parameters = []
                for ap in add_params_db:
                    ap_name_en = ap["name_en"] if ap["name_en"] is not None else (ap["pa_name_en"] or "")
                    param = {
                        "id": ap["kod"] or f"param_{ap['parametr_id']}",
                        "parametr_id": ap["parametr_id"],
                        "name_pl": ap["name_pl"] or ap["pa_label"] or "",
                        "name_en": ap_name_en,
                        "requirement": ap["requirement"] or "",
                        "method": ap["method"] or ap["pa_method_code"] or "",
                        "format": ap["format"] or "1",
                        "data_field": ap["kod"] or "",
                        # Dual-field surface for the editor (Cert Editor Redesign A4 + A5).
                        "name_pl_global": ap["pa_label"] or "",
                        "name_en_global": ap["pa_name_en"] or "",
                        "method_global": ap["pa_method_code"] or "",
                        "format_global": str(ap["pa_precision"]) if ap["pa_precision"] is not None else "",
                        "name_pl_override": ap["name_pl"],
                        "name_en_override": ap["name_en"],
                        "method_override": ap["method"],
                        "format_override": ap["format"],
                    }
                    if ap["qualitative_result"]:
                        param["qualitative_result"] = ap["qualitative_result"]
                    add_parameters.append(param)
                overrides["add_parameters"] = add_parameters

            if overrides:
                variant_obj["overrides"] = overrides
            variants.append(variant_obj)

        product["variants"] = variants

        db_meta = {
            "id": prod_row["id"],
            "display_name": prod_row["display_name"],
            "spec_number": prod_row["spec_number"],
            "cas_number": prod_row["cas_number"],
            "expiry_months": prod_row["expiry_months"],
            "opinion_pl": prod_row["opinion_pl"],
            "opinion_en": prod_row["opinion_en"],
        }

    return jsonify({"ok": True, "product": product, "db_meta": db_meta})


@certs_bp.route("/api/cert/config/product/<key>", methods=["PUT"])
@role_required("admin", "kj")
def api_cert_config_product_put(key):
    """Save product parameters + variants to DB, regenerate JSON export.

    Validate everything first, then mutate atomically. The old version
    deleted all parametry_cert rows BEFORE resolving every add_parameters
    mapping — a bad mapping raised NameError mid-write, leaving the product
    with an empty cert config.
    """
    from mbr.certs.generator import save_cert_config_export

    data = request.get_json(silent=True) or {}
    parameters = data.get("parameters")
    variants = data.get("variants")

    with db_session() as db:
        prod_row = db.execute("SELECT id FROM produkty WHERE nazwa = ?", (key,)).fetchone()
        if not prod_row:
            return jsonify({"error": "Product not found"}), 404
        has_variants = db.execute("SELECT 1 FROM cert_variants WHERE produkt = ? LIMIT 1", (key,)).fetchone()
        if not has_variants:
            return jsonify({"error": "Product not found"}), 404

        # Single scan over parametry_analityczne — kod_to_id for validation/writes,
        # id_to_kod for the round-trip in the GET endpoint (no more N+1 lookups).
        pa_rows = db.execute("SELECT id, kod FROM parametry_analityczne").fetchall()
        kod_to_id = {r["kod"]: r["id"] for r in pa_rows if r["kod"]}

        # Whitelist: only kody present in the active MBR's analiza_koncowa may
        # appear on the certificate. Empty analiza_kody (no active MBR) means
        # warnings are suppressed — but mapping errors still block the save.
        from mbr.technolog.models import get_active_mbr
        mbr = get_active_mbr(db, key)
        analiza_kody = set()
        if mbr:
            try:
                plab = _json.loads(mbr.get("parametry_lab") or "{}")
            except Exception:
                plab = {}
            for sekcja in plab.values():
                for p in (sekcja.get("pola") or []):
                    kod = p.get("kod")
                    if kod:
                        analiza_kody.add(kod)

        warnings = []

        # ── Validate qualitative_result for jakosciowy params ──
        # For params with typ='jakosciowy' and non-empty opisowe_wartosci,
        # qualitative_result must be from the allowed list (or empty).
        def _validate_qr(pid_row_id, qr_text, context_label):
            qr = (qr_text or "").strip()
            if not qr:
                return None
            meta = db.execute(
                "SELECT typ, opisowe_wartosci FROM parametry_analityczne WHERE id=?",
                (pid_row_id,),
            ).fetchone()
            if not meta or meta["typ"] != "jakosciowy":
                return None
            try:
                allowed = _json.loads(meta["opisowe_wartosci"] or "[]")
            except Exception:
                allowed = []
            if allowed and qr not in allowed:
                return (f"{context_label}: wartość '{qr}' jest niedozwolona "
                        f"(opisowe_wartosci: {allowed})")
            return None

        if parameters is not None:
            for p in parameters:
                df = (p.get("data_field") or p.get("id", "")).strip()
                pid_row_id = kod_to_id.get(df)
                if pid_row_id is None:
                    continue  # already caught by earlier validation
                err = _validate_qr(pid_row_id, p.get("qualitative_result"), f"Parametr '{df}'")
                if err:
                    return jsonify({"error": err}), 400

        if variants is not None:
            for v in variants:
                overrides = v.get("overrides") or {}
                for ap in overrides.get("add_parameters", []) or []:
                    ap_df = (ap.get("data_field") or ap.get("id") or "").strip()
                    pid_row_id = kod_to_id.get(ap_df)
                    if pid_row_id is None:
                        continue
                    err = _validate_qr(
                        pid_row_id, ap.get("qualitative_result"),
                        f"Wariant '{v.get('id', '?')}': parametr '{ap_df}'",
                    )
                    if err:
                        return jsonify({"error": err}), 400

        # ── PHASE 1: validate EVERYTHING before we touch any row ────────────
        if parameters is not None:
            param_ids = set()
            for p in parameters:
                pid = p.get("id", "").strip()
                if not pid:
                    return jsonify({"error": "Parameter missing id"}), 400
                if pid in param_ids:
                    return jsonify({"error": f"Duplicate parameter id: {pid}"}), 400
                param_ids.add(pid)
                if not p.get("name_pl"):
                    # Legacy NULL name_pl is allowed (warning only).
                    warnings.append(f"Parametr '{pid}' nie ma nazwy PL — uzupełnij w edytorze")
                df = (p.get("data_field") or p.get("id", "")).strip()
                if not df or df not in kod_to_id:
                    return jsonify({"error": f"Parametr '{pid}': powiązanie '{df}' nie istnieje w rejestrze parametrów"}), 400
                if analiza_kody and df not in analiza_kody:
                    warnings.append(f"Parametr '{pid}': '{df}' nie jest w MBR")

        if variants is not None:
            if parameters is not None:
                base_param_ids = {p.get("id", "").strip() for p in parameters}
            else:
                existing_base = db.execute(
                    "SELECT pa.kod FROM parametry_cert pc JOIN parametry_analityczne pa ON pa.id=pc.parametr_id "
                    "WHERE pc.produkt=? AND pc.variant_id IS NULL", (key,)
                ).fetchall()
                base_param_ids = {r["kod"] for r in existing_base if r["kod"]}

            variant_ids = set()
            for v in variants:
                vid = v.get("id", "").strip()
                if not vid:
                    return jsonify({"error": "Variant missing id"}), 400
                if vid in variant_ids:
                    return jsonify({"error": f"Duplicate variant id: {vid}"}), 400
                variant_ids.add(vid)
                if not v.get("label"):
                    return jsonify({"error": f"Variant '{vid}' missing label"}), 400
                overrides = v.get("overrides") or {}
                # Stale refs in remove_parameters (base param removed in the
                # same save) are NOT an error — just drop them and warn. The
                # variant still means "don't show X"; X already isn't there.
                remove_params = overrides.get("remove_parameters", []) or []
                cleaned_remove = []
                for rp in remove_params:
                    if rp in base_param_ids:
                        cleaned_remove.append(rp)
                    else:
                        warnings.append(f"Wariant '{vid}': pominięto 'remove {rp}' — brak w parametrach bazowych")
                overrides["remove_parameters"] = cleaned_remove
                for ap in overrides.get("add_parameters", []) or []:
                    ap_df = (ap.get("data_field") or ap.get("id") or "").strip()
                    # Resolve mapping during VALIDATION so we never fail
                    # halfway through the destructive write below.
                    if not ap_df or ap_df not in kod_to_id:
                        return jsonify({"error": f"Wariant '{vid}': parametr '{ap_df}' nie istnieje w rejestrze"}), 400
                    if analiza_kody and ap_df not in analiza_kody:
                        warnings.append(f"Wariant '{vid}': '{ap_df}' nie jest w MBR")

        # ── PHASE 2: atomic write ───────────────────────────────────────────
        # sqlite3 Connection context auto-rolls back on any exception,
        # commits on clean exit — no half-written state after a mid-flow fail.
        try:
            with db:
                for field in ("display_name", "spec_number", "cas_number",
                              "expiry_months", "opinion_pl", "opinion_en"):
                    if field in data:
                        db.execute(
                            f"UPDATE produkty SET {field} = ? WHERE nazwa = ?",
                            (data[field], key),
                        )

                if parameters is not None:
                    db.execute("DELETE FROM parametry_cert WHERE produkt = ? AND variant_id IS NULL", (key,))
                    for idx, p in enumerate(parameters):
                        df = (p.get("data_field") or p.get("id", "")).strip()
                        parametr_id = kod_to_id[df]  # validated above
                        db.execute(
                            "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format, qualitative_result, name_pl, name_en, method, variant_id) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                            (key, parametr_id, idx, p.get("requirement", ""), p.get("format", "1"),
                             p.get("qualitative_result") or None,
                             p.get("name_pl") or None, p.get("name_en", None), p.get("method") or None),
                        )

                if variants is not None:
                    # Preserve archived flag across the delete-then-reinsert
                    # variant write. The editor doesn't toggle archived through
                    # this endpoint (that's done via /archive), but the GET-PUT
                    # round-trip must not silently un-archive variants the admin
                    # is viewing while "Pokaż archiwalne" is on.
                    archived_by_vid = {
                        r["variant_id"]: r["archived"] for r in db.execute(
                            "SELECT variant_id, COALESCE(archived,0) AS archived "
                            "FROM cert_variants WHERE produkt=?", (key,),
                        ).fetchall()
                    }
                    old_variant_rows = db.execute(
                        "SELECT id FROM cert_variants WHERE produkt=?", (key,),
                    ).fetchall()
                    for ovr in old_variant_rows:
                        db.execute("DELETE FROM parametry_cert WHERE variant_id = ?", (ovr["id"],))
                    db.execute("DELETE FROM cert_variants WHERE produkt = ?", (key,))

                    for idx, v in enumerate(variants):
                        overrides = v.get("overrides") or {}
                        remove_kods = overrides.get("remove_parameters", [])
                        remove_ids = [kod_to_id[k] for k in remove_kods if k in kod_to_id]

                        # Trust client-supplied archived only as a fallback;
                        # primary source is the snapshot we took above.
                        prev_archived = archived_by_vid.get(v.get("id", ""), 0)
                        archived_val = 1 if (prev_archived or v.get("archived")) else 0

                        cur = db.execute(
                            "INSERT INTO cert_variants (produkt, variant_id, label, flags, spec_number, opinion_pl, opinion_en, avon_code, avon_name, remove_params, kolejnosc, archived) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (key, v.get("id", ""), v.get("label", ""),
                             _json.dumps(v.get("flags", []), ensure_ascii=False),
                             overrides.get("spec_number") or None,
                             overrides.get("opinion_pl") or None,
                             overrides.get("opinion_en") or None,
                             overrides.get("avon_code") or None,
                             overrides.get("avon_name") or None,
                             _json.dumps(remove_ids), idx, archived_val),
                        )
                        new_cv_id = cur.lastrowid

                        for ap_idx, ap in enumerate(overrides.get("add_parameters", []) or []):
                            ap_df = (ap.get("data_field") or ap.get("id", "")).strip()
                            ap_parametr_id = kod_to_id[ap_df]  # validated above
                            db.execute(
                                "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format, qualitative_result, name_pl, name_en, method, variant_id) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (key, ap_parametr_id, ap_idx, ap.get("requirement", ""), ap.get("format", "1"),
                                 ap.get("qualitative_result") or None,
                                 ap.get("name_pl") or None, ap.get("name_en", None), ap.get("method") or None,
                                 new_cv_id),
                            )

                from mbr.shared import audit
                audit.log_event(
                    audit.EVENT_CERT_CONFIG_UPDATED,
                    entity_type="cert",
                    entity_label=key,
                    payload={"params_count": len(parameters or []), "variants_count": len(variants or [])},
                    db=db,
                )
        except Exception as e:
            return jsonify({"error": f"zapis nie powiódł się: {e}"}), 500

    # Export runs against its own fresh connection — outside the session
    # to keep the write fully committed before the JSON snapshot is built.
    save_cert_config_export()

    result = {"ok": True}
    if warnings:
        result["warnings"] = warnings
    return jsonify(result)


@certs_bp.route("/api/cert/config/product", methods=["POST"])
@role_required("admin", "kj")
def api_cert_config_product_create():
    """Create a new product with cert config in DB."""
    import re
    from mbr.certs.generator import save_cert_config_export

    data = request.get_json(silent=True) or {}
    display_name = (data.get("display_name") or "").strip()
    if not display_name:
        return jsonify({"error": "display_name is required"}), 400

    key = display_name.replace(" ", "_")
    if not re.match(r'^[A-Za-z0-9_\-]+$', key):
        return jsonify({"error": "Nazwa zawiera niedozwolone znaki (dozwolone: litery, cyfry, _, -)"}), 400

    with db_session() as db:
        # Check if cert config already exists
        existing_cv = db.execute("SELECT 1 FROM cert_variants WHERE produkt = ? LIMIT 1", (key,)).fetchone()
        if existing_cv:
            return jsonify({"error": f"Product '{key}' already exists"}), 409

        # Insert into produkty if not exists
        existing_prod = db.execute("SELECT id FROM produkty WHERE nazwa = ?", (key,)).fetchone()
        if not existing_prod:
            db.execute(
                "INSERT INTO produkty (nazwa, display_name, spec_number, cas_number, expiry_months, opinion_pl, opinion_en) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (key, display_name, data.get("spec_number", ""), data.get("cas_number", ""),
                 data.get("expiry_months", 12), data.get("opinion_pl", ""), data.get("opinion_en", "")),
            )

        # Insert default "base" variant
        db.execute(
            "INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
            "VALUES (?, 'base', ?, '[]', 0)",
            (key, display_name),
        )

        db.commit()

    save_cert_config_export()
    return jsonify({"ok": True, "key": key})


@certs_bp.route("/api/cert/config/product/<src_key>/copy", methods=["POST"])
@role_required("admin", "kj")
def api_cert_config_product_copy(src_key):
    """Deep-copy parameters from source product to a new product.

    Copies:
      - all base parameters (parametry_cert with variant_id IS NULL) preserving order
      - a fresh 'base' variant with label = new display_name

    Does NOT copy:
      - product metadata (spec_number, cas_number, opinions, expiry_months) —
        user fills these in fresh via the editor
      - non-base variants and their add_parameters
    """
    import re
    from mbr.certs.generator import save_cert_config_export

    data = request.get_json(silent=True) or {}
    new_display_name = (data.get("new_display_name") or "").strip()
    if not new_display_name:
        return jsonify({"error": "new_display_name is required"}), 400

    new_key = new_display_name.replace(" ", "_")
    if not re.match(r'^[A-Za-z0-9_\-]+$', new_key):
        return jsonify({"error": "Nazwa zawiera niedozwolone znaki (dozwolone: litery, cyfry, _, -)"}), 400

    with db_session() as db:
        src_exists = db.execute(
            "SELECT 1 FROM cert_variants WHERE produkt = ? LIMIT 1", (src_key,)
        ).fetchone()
        if not src_exists:
            return jsonify({"error": "Source product not found"}), 404

        target_exists = db.execute(
            "SELECT 1 FROM cert_variants WHERE produkt = ? LIMIT 1", (new_key,)
        ).fetchone()
        if target_exists:
            return jsonify({"error": f"Product '{new_key}' already exists"}), 409

        try:
            with db:
                # 1. produkty row (if not exists)
                existing_prod = db.execute(
                    "SELECT id FROM produkty WHERE nazwa = ?", (new_key,)
                ).fetchone()
                if not existing_prod:
                    db.execute(
                        "INSERT INTO produkty (nazwa, display_name, spec_number, cas_number, "
                        "expiry_months, opinion_pl, opinion_en) VALUES (?, ?, '', '', 12, '', '')",
                        (new_key, new_display_name),
                    )

                # 2. base variant
                db.execute(
                    "INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
                    "VALUES (?, 'base', ?, '[]', 0)",
                    (new_key, new_display_name),
                )

                # 3. Copy base parametry_cert (variant_id IS NULL) — preserve order
                src_params = db.execute(
                    "SELECT parametr_id, kolejnosc, requirement, format, qualitative_result, "
                    "name_pl, name_en, method "
                    "FROM parametry_cert "
                    "WHERE produkt = ? AND variant_id IS NULL "
                    "ORDER BY kolejnosc",
                    (src_key,),
                ).fetchall()
                for p in src_params:
                    db.execute(
                        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, "
                        "format, qualitative_result, name_pl, name_en, method, variant_id) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                        (new_key, p["parametr_id"], p["kolejnosc"], p["requirement"],
                         p["format"], p["qualitative_result"],
                         p["name_pl"], p["name_en"], p["method"]),
                    )

                # 4. Audit entry
                from mbr.shared import audit
                audit.log_event(
                    audit.EVENT_CERT_CONFIG_UPDATED,
                    entity_type="cert",
                    entity_label=new_key,
                    payload={
                        "copied_from": src_key,
                        "params_count": len(src_params),
                        "variants_count": 1,
                    },
                    db=db,
                )
        except Exception as e:
            return jsonify({"error": f"kopia nie powiodła się: {e}"}), 500

    save_cert_config_export()
    return jsonify({"ok": True, "key": new_key})


@certs_bp.route("/api/cert/settings", methods=["GET"])
@role_required("admin", "kj")
def api_cert_settings_get():
    """Return current cert_settings (typography globals)."""
    with db_session() as db:
        rows = db.execute("SELECT key, value FROM cert_settings").fetchall()
    # Defaults mirror _cert_settings_defaults in mbr/models.py. Four size keys
    # are typed as int; body_font_family / header_font_family are str.
    out = {
        "body_font_family":          "Noto Serif",
        "header_font_family":        "Noto Sans",
        "header_font_size_pt":       14,
        "title_font_size_pt":        12,
        "product_name_font_size_pt": 16,
        "body_font_size_pt":         11,
    }
    int_keys = {"header_font_size_pt", "title_font_size_pt",
                "product_name_font_size_pt", "body_font_size_pt"}
    for r in rows:
        k = r["key"]
        v = r["value"]
        if k in int_keys:
            try:
                out[k] = int(v)
            except (ValueError, TypeError):
                pass
        elif k in out:
            out[k] = v
    return jsonify(out)


@certs_bp.route("/api/cert/settings", methods=["PUT"])
@role_required("admin", "kj")
def api_cert_settings_put():
    """Update cert_settings keys (font family + 3 granular font sizes).

    Legacy `header_font_size_pt` is silently dropped from the payload — the
    new `title_font_size_pt` and `product_name_font_size_pt` replace it.
    """
    data = request.get_json(silent=True) or {}
    updated = {}

    # Font-family fields share the same XML-attribute-safety constraint:
    # whitelist Unicode letters, digits, space, hyphen, period, apostrophe.
    # Google Fonts / standard font-family names all fit this.
    import re as _re
    _FONT_FAMILY_RE = _re.compile(r"^[\w\s\-.']+$", flags=_re.UNICODE)
    for font_key in ("body_font_family", "header_font_family"):
        if font_key not in data:
            continue
        val = (data[font_key] or "").strip()
        if not val or len(val) > 120:
            return jsonify({"error": f"{font_key}: pusta lub za długa nazwa"}), 400
        if not _FONT_FAMILY_RE.match(val):
            return jsonify({"error": f"{font_key}: niedozwolone znaki (dozwolone: litery, cyfry, spacje, - . ')"}), 400
        updated[font_key] = val

    # Numeric size keys — range 6–36 pt. Legacy header_font_size_pt is not in
    # this list, so any value passed there is silently ignored.
    _size_keys = (
        ("title_font_size_pt",        "Tytuł"),
        ("product_name_font_size_pt", "Nazwa produktu"),
        ("body_font_size_pt",         "Body"),
    )
    for key, label in _size_keys:
        if key not in data:
            continue
        try:
            n = int(data[key])
        except (ValueError, TypeError):
            return jsonify({"error": f"{label}: nieprawidłowa liczba"}), 400
        if n < 6 or n > 36:
            return jsonify({"error": f"{label}: zakres 6–36 pt"}), 400
        updated[key] = str(n)

    if not updated:
        return jsonify({"error": "brak pól do aktualizacji"}), 400

    with db_session() as db:
        try:
            with db:
                for k, v in updated.items():
                    db.execute(
                        "INSERT INTO cert_settings (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (k, v),
                    )
                from mbr.shared import audit
                audit.log_event(
                    audit.EVENT_CERT_SETTINGS_UPDATED,
                    entity_type="cert",
                    entity_label="_settings",
                    payload={"updated_keys": list(updated.keys())},
                    db=db,
                )
        except Exception as e:
            return jsonify({"error": f"zapis nie powiódł się: {e}"}), 500

    return jsonify({"ok": True, "updated": list(updated.keys())})


@certs_bp.route("/api/cert/config/product/<key>/issued-count", methods=["GET"])
@role_required("admin", "kj")
def api_cert_config_product_issued_count(key):
    """Return how many świadectwa have been issued for this product's templates.

    Used by the editor to surface the count in the delete-confirm dialog
    BEFORE the delete — previously the count was only revealed after.
    """
    with db_session() as db:
        prod_row = db.execute("SELECT display_name FROM produkty WHERE nazwa = ?", (key,)).fetchone()
        if not prod_row:
            return jsonify({"count": 0})
        display_name = prod_row["display_name"] or key
        row = db.execute(
            "SELECT COUNT(*) AS cnt FROM swiadectwa WHERE template_name LIKE ?",
            (f"{display_name}%",),
        ).fetchone()
    return jsonify({"count": row["cnt"] if row else 0})


@certs_bp.route("/api/cert/config/product/<key>", methods=["DELETE"])
@role_required("admin", "kj")
def api_cert_config_product_delete(key):
    """Delete a product's cert config from DB."""
    from mbr.certs.generator import save_cert_config_export

    with db_session() as db:
        has_variants = db.execute("SELECT 1 FROM cert_variants WHERE produkt = ? LIMIT 1", (key,)).fetchone()
        if not has_variants:
            return jsonify({"error": "Product not found"}), 404

        # Check for issued certificates
        warning = None
        prod_row = db.execute("SELECT display_name FROM produkty WHERE nazwa = ?", (key,)).fetchone()
        display_name = prod_row["display_name"] if prod_row else key
        row = db.execute(
            "SELECT COUNT(*) as cnt FROM swiadectwa WHERE template_name LIKE ?",
            (f"{display_name}%",),
        ).fetchone()
        if row and row["cnt"] > 0:
            warning = f"Istnieje {row['cnt']} wydanych świadectw dla tego produktu. Dane archiwalne pozostają nienaruszone."

        # Delete: variant add_params → cert_variants → base parametry_cert
        variant_rows = db.execute("SELECT id FROM cert_variants WHERE produkt=?", (key,)).fetchall()
        for vr in variant_rows:
            db.execute("DELETE FROM parametry_cert WHERE variant_id = ?", (vr["id"],))
        db.execute("DELETE FROM cert_variants WHERE produkt = ?", (key,))
        db.execute("DELETE FROM parametry_cert WHERE produkt = ? AND variant_id IS NULL", (key,))

        db.commit()

    save_cert_config_export()
    result = {"ok": True}
    if warning:
        result["warning"] = warning
    return jsonify(result)


@certs_bp.route("/api/cert/config/export")
@role_required("admin", "kj")
def api_cert_config_export():
    """Export cert config from DB, regenerate JSON file, and return it."""
    with db_session() as db:
        from mbr.certs.generator import save_cert_config_export, export_cert_config
        save_cert_config_export(db)
        cfg = export_cert_config(db)
    return jsonify(cfg)


# Size caps for the preview payload so a pathological JSON can't DoS
# Gotenberg or hand an unbounded string to docxtpl/Jinja2 evaluation.
_PREVIEW_MAX_PARAMETERS = 200
_PREVIEW_MAX_VARIANTS = 50
_PREVIEW_MAX_STR = 2000


def _preview_payload_ok(product: dict) -> str | None:
    """Return an error message if the editor payload is out of bounds, else None."""
    if not isinstance(product, dict):
        return "product must be an object"
    params = product.get("parameters") or []
    if not isinstance(params, list):
        return "parameters must be a list"
    if len(params) > _PREVIEW_MAX_PARAMETERS:
        return f"za dużo parametrów (max {_PREVIEW_MAX_PARAMETERS})"
    variants = product.get("variants") or []
    if len(variants) > _PREVIEW_MAX_VARIANTS:
        return f"za dużo wariantów (max {_PREVIEW_MAX_VARIANTS})"
    # Cheap string-length check — docxtpl uses Jinja2 internally, and a user
    # with access could otherwise stuff a multi-MB template expression into
    # any string field and have it evaluated in the render context.
    def _scan(obj):
        if isinstance(obj, str):
            if len(obj) > _PREVIEW_MAX_STR:
                return f"pole tekstowe przekracza {_PREVIEW_MAX_STR} znaków"
        elif isinstance(obj, dict):
            for v in obj.values():
                err = _scan(v)
                if err:
                    return err
        elif isinstance(obj, list):
            for v in obj:
                err = _scan(v)
                if err:
                    return err
        return None
    return _scan(product)


@certs_bp.route("/api/cert/config/preview", methods=["POST"])
@role_required("admin", "kj")
def api_cert_config_preview():
    """Generate a live PDF preview from editor JSON payload (no DB)."""
    data = request.get_json(silent=True) or {}
    product = data.get("product")
    variant_id = data.get("variant_id", "base")

    if not product:
        return jsonify({"error": "Missing 'product' in request body"}), 400

    err = _preview_payload_ok(product)
    if err:
        return jsonify({"error": err}), 400

    try:
        ctx = build_preview_context(product, variant_id)
        docx_bytes = _docxtpl_render(ctx)
        pdf_bytes = _gotenberg_convert(docx_bytes)
        return Response(pdf_bytes, mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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


@certs_bp.route("/api/cert/<int:cert_id>/audit-history")
@role_required("admin", "kj", "technolog", "cert", "lab")
def cert_audit_history(cert_id):
    """Return per-cert audit history (sorted DESC by dt, with actors)."""
    from mbr.shared import audit
    with db_session() as db:
        history = audit.query_audit_history_for_entity(db, "cert", cert_id)
    return jsonify({"history": history})


@certs_bp.route("/api/cert/config/product/<key>/audit-history")
@role_required("admin", "kj")
def cert_config_audit_history(key):
    """Return cert config edit history for a specific product.

    Filters audit_log on entity_type='cert' AND entity_label=key. Events
    include CERT_CONFIG_UPDATED (save, copy). Used by the editor's
    "Historia" tab (T14).
    """
    from mbr.shared import audit
    with db_session() as db:
        history = audit.query_audit_history_by_label(db, "cert", key)
    return jsonify({"history": history})


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
