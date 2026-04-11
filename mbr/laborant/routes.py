"""
laborant/routes.py — Batch management and lab data entry routes.
"""

import json
from datetime import datetime
from urllib.parse import urlparse

from flask import request, session, render_template, redirect, url_for, flash, jsonify

from mbr.db import db_session
from mbr.shared.decorators import login_required, role_required
from mbr.laborant import laborant_bp
from mbr.laborant.models import (
    PRODUCTS,
    list_ebr_open, list_ebr_recent,
    create_ebr, get_ebr, get_ebr_wyniki, get_round_state,
    save_wyniki, complete_ebr, sync_ebr_to_v4,
    get_uwagi, save_uwagi,
)


def _resolve_actor_label(db, override: str = None) -> str:
    """Resolve a human-readable actor string for write operations.

    Resolution order:
      1. `override` if non-empty (form/body explicit pick — e.g. uwagi picker)
      2. session['shift_workers'] joined by ', ' using nickname || inicjaly
      3. For role 'laborant' with empty shift → ShiftRequiredError (Phase 3
         enforcement: laborant cannot write without a confirmed shift).
      4. For other roles (admin/technolog/laborant_kj/laborant_coa) with empty
         shift → fallback to session['user']['login'].
    """
    if override:
        cleaned = override.strip()
        if cleaned:
            return cleaned

    shift_ids = session.get("shift_workers", []) or []
    if shift_ids:
        placeholders = ",".join("?" * len(shift_ids))
        rows = db.execute(
            f"SELECT inicjaly, nickname FROM workers WHERE id IN ({placeholders})",
            shift_ids,
        ).fetchall()
        if rows:
            return ", ".join((r["nickname"] or r["inicjaly"]) for r in rows)

    rola = session.get("user", {}).get("rola")
    if rola == "laborant":
        from mbr.shared.audit import ShiftRequiredError
        raise ShiftRequiredError()

    return session["user"]["login"]


@laborant_bp.route("/laborant/szarze")
@role_required("laborant", "laborant_kj", "laborant_coa", "admin")
def szarze_list():
    from mbr.registry.models import list_completed_products
    with db_session() as db:
        batches = list_ebr_open(db)
        recent = list_ebr_recent(db, days=7)
        completed_products = list_completed_products(db)
    return render_template("laborant/szarze_list.html", batches=batches, recent=recent,
                           products=PRODUCTS, completed_products=completed_products)


@laborant_bp.route("/laborant/szarze/new", methods=["POST"])
@role_required("laborant", "laborant_kj", "admin")
def szarze_new():
    import sqlite3
    with db_session() as db:
        typ = request.form.get("typ", "szarza")
        wielkosc_kg = float(request.form.get("wielkosc_kg", 0) or 0)
        try:
            ebr_id = create_ebr(
                db,
                produkt=request.form["produkt"],
                nr_partii=request.form["nr_partii"],
                nr_amidatora=request.form.get("nr_amidatora", ""),
                nr_mieszalnika=request.form.get("nr_mieszalnika", ""),
                wielkosc_kg=wielkosc_kg,
                operator=session["user"]["login"],
                typ=typ,
                nastaw=int(wielkosc_kg) if wielkosc_kg else None,
                nr_zbiornika=request.form.get("nr_zbiornika", ""),
            )
        except sqlite3.IntegrityError:
            flash(f"Szarża o numerze {request.form['nr_partii']} już istnieje w systemie.")
            back = request.form.get("_back") or request.referrer or url_for("laborant.szarze_list")
            parsed = urlparse(back)
            if parsed.netloc and parsed.netloc != request.host:
                back = url_for("laborant.szarze_list")
            return redirect(back)

        # Save pre-selected zbiorniki (optional, from modal pill selection)
        if ebr_id:
            zbiorniki_ids = request.form.get("zbiorniki_ids", "")
            if zbiorniki_ids:
                from datetime import datetime
                now = datetime.now().isoformat(timespec="seconds")
                for zid_str in zbiorniki_ids.split(","):
                    zid = int(zid_str.strip()) if zid_str.strip() else 0
                    if zid:
                        db.execute(
                            "INSERT OR IGNORE INTO zbiornik_szarze (ebr_id, zbiornik_id, masa_kg, dt_dodania) VALUES (?, ?, NULL, ?)",
                            (ebr_id, zid, now),
                        )
                db.commit()

            # Save platkowanie substraty (optional, from modal substrat rows)
            substraty_json = request.form.get("substraty_json", "[]")
            import json as _json
            try:
                substraty = _json.loads(substraty_json)
                for sub in substraty:
                    sub_id = sub.get("substrat_id")
                    nr = sub.get("nr_partii", "")
                    if sub_id:
                        db.execute(
                            "INSERT OR IGNORE INTO platkowanie_substraty (ebr_id, substrat_id, nr_partii_substratu) VALUES (?, ?, ?)",
                            (ebr_id, sub_id, nr),
                        )
                if substraty:
                    db.commit()
            except Exception:
                pass

    if ebr_id is None:
        flash("Brak aktywnego szablonu MBR dla tego produktu.")
    # Return to referring page (fast_entry or szarze_list)
    back = request.form.get("_back") or request.referrer or url_for("laborant.szarze_list")
    # Prevent open redirect — only allow relative paths
    parsed = urlparse(back)
    if parsed.netloc and parsed.netloc != request.host:
        back = url_for("laborant.szarze_list")
    return redirect(back)


@laborant_bp.route("/laborant/ebr/<int:ebr_id>")
@login_required
def fast_entry(ebr_id):
    from mbr.registry.models import list_completed_products
    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        if ebr is None:
            return "Nie znaleziono szarzy", 404
        # Serve the SPA shell — JS will detect URL and load partial via AJAX
        batches = list_ebr_open(db)
        recent = list_ebr_recent(db, days=7)
        completed_products = list_completed_products(db)
    return render_template("laborant/szarze_list.html", batches=batches, recent=recent,
                           products=PRODUCTS, completed_products=completed_products)


@laborant_bp.route("/laborant/ebr/<int:ebr_id>/partial")
@login_required
def fast_entry_partial(ebr_id):
    """Return just the fast-entry form HTML (no base.html shell) for AJAX loading."""
    from mbr.etapy_models import get_etapy_status, get_etap_analizy, get_korekty
    from mbr.parametry_registry import get_etapy_config
    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        if ebr is None:
            return "Nie znaleziono", 404
        wyniki = get_ebr_wyniki(db, ebr_id)
        round_state = get_round_state(wyniki)
        etapy_status = get_etapy_status(db, ebr_id)
        etapy_analizy = get_etap_analizy(db, ebr_id)
        etapy_korekty = get_korekty(db, ebr_id)
        etapy_config = get_etapy_config(db, ebr.get("produkt", ""))
    return render_template("laborant/_fast_entry_content.html",
                           ebr=ebr, wyniki=wyniki, round_state=round_state,
                           etapy_status=etapy_status,
                           etapy_analizy=etapy_analizy,
                           etapy_korekty=etapy_korekty,
                           etapy_config=etapy_config)


@laborant_bp.route("/laborant/ebr/<int:ebr_id>/save", methods=["POST"])
@role_required("laborant", "laborant_kj", "admin")
def save_entry(ebr_id):
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    sekcja = data.get("sekcja", "")
    values = data.get("values", {})
    with db_session() as db_w:
        user = _resolve_actor_label(db_w)

    with db_session() as db:
        ebr = get_ebr(db, ebr_id)

        # For completed zbiornik: check if values actually changed before marking certs outdated
        values_changed = False
        if ebr and ebr["status"] == "completed" and ebr.get("typ") == "zbiornik":
            old_wyniki = get_ebr_wyniki(db, ebr_id)
            old_sek = old_wyniki.get(sekcja, {})
            for kod, entry in values.items():
                new_val = entry.get("wartosc", "")
                try:
                    new_val = float(new_val)
                except (ValueError, TypeError):
                    continue
                old_row = old_sek.get(kod)
                old_val = old_row["wartosc"] if old_row else None
                if old_val != new_val:
                    values_changed = True
                    break

        save_wyniki(db, ebr_id, sekcja, values, user, ebr=ebr)
        sync_ebr_to_v4(db, ebr_id, ebr=ebr)

        if values_changed:
            from mbr.certs.models import mark_swiadectwa_outdated
            mark_swiadectwa_outdated(db, ebr_id)

    return jsonify({"ok": True})


@laborant_bp.route("/api/ebr/<int:ebr_id>/golden", methods=["POST"])
@login_required
def toggle_golden(ebr_id):
    with db_session() as db:
        row = db.execute("SELECT is_golden FROM ebr_batches WHERE ebr_id=?", (ebr_id,)).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        new_val = 0 if row["is_golden"] else 1
        db.execute("UPDATE ebr_batches SET is_golden=? WHERE ebr_id=?", (new_val, ebr_id))
        db.commit()
    return jsonify({"ok": True, "is_golden": new_val})


@laborant_bp.route("/api/ebr/<int:ebr_id>/audit-history")
@role_required("laborant", "laborant_kj", "laborant_coa", "admin", "technolog")
def ebr_audit_history(ebr_id):
    """Return per-EBR audit history (sorted DESC by dt, with actors)."""
    from mbr.shared import audit
    with db_session() as db:
        history = audit.query_audit_history_for_entity(db, "ebr", ebr_id)
    return jsonify({"history": history})


@laborant_bp.route("/laborant/ebr/<int:ebr_id>/complete", methods=["POST"])
@role_required("laborant", "laborant_kj", "admin")
def complete_entry(ebr_id):
    data = request.get_json(silent=True) or {}
    zbiorniki = data.get("zbiorniki")
    with db_session() as db:
        complete_ebr(db, ebr_id, zbiorniki=zbiorniki)
        sync_ebr_to_v4(db, ebr_id)
    # Support AJAX calls from SPA
    if request.is_json or request.headers.get("Content-Type", "").startswith("application/json"):
        return jsonify({"ok": True})
    return redirect(url_for("laborant.szarze_list"))


# ---------------------------------------------------------------------------
# Titration samples API (persistent naważki/volumes)
# ---------------------------------------------------------------------------

@laborant_bp.route("/api/ebr/<int:ebr_id>/samples", methods=["POST"])
@login_required
def save_samples(ebr_id):
    """Save titration samples (naważki + optional volumes) for a parameter."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    with db_session() as db:
        samples_json = json.dumps(data["samples"])
        db.execute("""
            INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc,
                min_limit, max_limit, w_limicie, samples_json, is_manual, dt_wpisu, wpisal)
            VALUES (?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, 1, ?, ?)
            ON CONFLICT(ebr_id, sekcja, kod_parametru) DO UPDATE SET
                samples_json = excluded.samples_json,
                dt_wpisu = excluded.dt_wpisu,
                wpisal = excluded.wpisal
        """, (ebr_id, data["sekcja"], data["kod_parametru"], data.get("tag", ""),
              samples_json, datetime.now().isoformat(timespec="seconds"),
              session["user"]["login"]))
        db.commit()
    return jsonify({"ok": True})


@laborant_bp.route("/api/ebr/<int:ebr_id>/samples/<sekcja>/<kod>")
@login_required
def get_samples(ebr_id, sekcja, kod):
    """Get saved titration samples for a parameter."""
    with db_session() as db:
        row = db.execute(
            "SELECT samples_json FROM ebr_wyniki WHERE ebr_id = ? AND sekcja = ? AND kod_parametru = ?",
            (ebr_id, sekcja, kod)
        ).fetchone()
    samples = json.loads(row["samples_json"]) if row and row["samples_json"] else []
    return jsonify({"samples": samples})


# ---------------------------------------------------------------------------
# Uwagi końcowe API (final batch notes)
# ---------------------------------------------------------------------------

@laborant_bp.route("/api/ebr/<int:ebr_id>/uwagi", methods=["GET"])
@login_required
def api_get_uwagi(ebr_id):
    """Return current uwagi_koncowe + history for an EBR batch."""
    with db_session() as db:
        try:
            data = get_uwagi(db, ebr_id)
        except ValueError:
            return jsonify({"error": "Not found"}), 404
    return jsonify(data)


@laborant_bp.route("/api/ebr/<int:ebr_id>/uwagi", methods=["PUT"])
@role_required("laborant", "laborant_kj", "laborant_coa", "admin")
def api_put_uwagi(ebr_id):
    """Create or update uwagi_koncowe for an EBR batch.

    Body: {"tekst": "...", "autor": "..."}
    `autor` is optional; when omitted, defaults to the current shift workers
    joined as 'AK, MW' (or login fallback). When provided, it overrides — used
    by the front-end picker so a laborant can sign as a subset of the shift.
    """
    body = request.get_json(silent=True) or {}
    tekst = body.get("tekst", "")
    autor_override = body.get("autor")
    with db_session() as db:
        autor = _resolve_actor_label(db, override=autor_override)
        try:
            result = save_uwagi(db, ebr_id, tekst, autor=autor)
        except ValueError as e:
            msg = str(e)
            status = 404 if "not found" in msg.lower() else 400
            return jsonify({"error": msg}), status
    return jsonify(result)


@laborant_bp.route("/api/ebr/<int:ebr_id>/uwagi", methods=["DELETE"])
@role_required("laborant", "laborant_kj", "laborant_coa", "admin")
def api_delete_uwagi(ebr_id):
    """Clear uwagi_koncowe for an EBR batch (equivalent to PUT with tekst='')."""
    body = request.get_json(silent=True) or {}
    autor_override = body.get("autor")
    with db_session() as db:
        autor = _resolve_actor_label(db, override=autor_override)
        try:
            result = save_uwagi(db, ebr_id, "", autor=autor)
        except ValueError as e:
            msg = str(e)
            status = 404 if "not found" in msg.lower() else 400
            return jsonify({"error": msg}), status
    return jsonify(result)
