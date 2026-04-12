"""
laborant/routes.py — Batch management and lab data entry routes.
"""

import json
from datetime import datetime
from urllib.parse import urlparse

from flask import request, session, render_template, redirect, url_for, flash, jsonify

from mbr.db import db_session
from mbr.shared import audit
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
      3. For role 'lab'/'cert' with empty shift → ShiftRequiredError.
      4. For other roles (admin/technolog) with empty shift → fallback
         to session['user']['login'].
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
    if rola in ("lab", "cert"):
        from mbr.shared.audit import ShiftRequiredError
        raise ShiftRequiredError()

    return session["user"]["login"]


@laborant_bp.route("/laborant/szarze")
@role_required("lab", "cert", "admin")
def szarze_list():
    from mbr.registry.models import list_completed_products
    with db_session() as db:
        batches = list_ebr_open(db)
        recent = list_ebr_recent(db, days=7)
        completed_products = list_completed_products(db)
    return render_template("laborant/szarze_list.html", batches=batches, recent=recent,
                           products=PRODUCTS, completed_products=completed_products)


@laborant_bp.route("/laborant/szarze/new", methods=["POST"])
@role_required("lab", "admin")
def szarze_new():
    import sqlite3
    with db_session() as db:
        typ = request.form.get("typ", "szarza")
        from mbr.shared.filters import parse_decimal
        wielkosc_kg = parse_decimal(request.form.get("wielkosc_kg", 0))
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
            except Exception:
                pass

            # Audit: log batch creation
            audit.log_event(
                audit.EVENT_EBR_BATCH_CREATED,
                entity_type="ebr",
                entity_id=ebr_id,
                entity_label=f"{request.form['produkt']} {request.form['nr_partii']}",
                payload={
                    "produkt": request.form["produkt"],
                    "nr_partii": request.form["nr_partii"],
                    "nr_amidatora": request.form.get("nr_amidatora", ""),
                    "nr_mieszalnika": request.form.get("nr_mieszalnika", ""),
                    "wielkosc_kg": wielkosc_kg,
                    "typ": typ,
                },
                db=db,
            )
            db.commit()

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
        zatwierdzil_short = ""
        zatwierdzil_full = ""
        if ebr.get("status") == "completed":
            row = db.execute("""
                SELECT GROUP_CONCAT(COALESCE(w.inicjaly, aa.actor_login), '/') AS who_short,
                       GROUP_CONCAT(COALESCE(aa.actor_name, aa.actor_login), ', ') AS who_full
                FROM audit_log al
                JOIN audit_log_actors aa ON aa.audit_id = al.id
                LEFT JOIN workers w ON w.id = aa.worker_id
                WHERE al.event_type = 'ebr.batch.status_changed' AND al.entity_id = ?
            """, (ebr_id,)).fetchone()
            zatwierdzil_short = row["who_short"] if row and row["who_short"] else ""
            zatwierdzil_full = row["who_full"] if row and row["who_full"] else ""
    return render_template("laborant/_fast_entry_content.html",
                           ebr=ebr, wyniki=wyniki, round_state=round_state,
                           etapy_status=etapy_status,
                           etapy_analizy=etapy_analizy,
                           etapy_korekty=etapy_korekty,
                           etapy_config=etapy_config,
                           zatwierdzil_short=zatwierdzil_short,
                           zatwierdzil_full=zatwierdzil_full)


@laborant_bp.route("/laborant/ebr/<int:ebr_id>/save", methods=["POST"])
@role_required("lab", "admin")
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
                    new_val = parse_decimal(new_val)
                except (ValueError, TypeError):
                    continue
                old_row = old_sek.get(kod)
                old_val = old_row["wartosc"] if old_row else None
                if old_val != new_val:
                    values_changed = True
                    break

        result = save_wyniki(db, ebr_id, sekcja, values, user, ebr=ebr)

        # Audit: log wynik saved/updated if there were actual changes
        if result["diffs"]:
            # If only updates (no inserts) → updated; otherwise → saved
            event = audit.EVENT_EBR_WYNIK_UPDATED if (result["has_updates"] and not result["has_inserts"]) else audit.EVENT_EBR_WYNIK_SAVED
            audit.log_event(
                event,
                entity_type="ebr",
                entity_id=ebr_id,
                diff=result["diffs"],
                payload={"sekcja": sekcja},
                db=db,
            )
        db.commit()

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
        old_val = row["is_golden"]
        new_val = 0 if old_val else 1
        db.execute("UPDATE ebr_batches SET is_golden=? WHERE ebr_id=?", (new_val, ebr_id))

        audit.log_event(
            audit.EVENT_EBR_BATCH_UPDATED,
            entity_type="ebr",
            entity_id=ebr_id,
            diff=[{"pole": "is_golden", "stara": old_val, "nowa": new_val}],
            db=db,
        )
        db.commit()
    return jsonify({"ok": True, "is_golden": new_val})


@laborant_bp.route("/api/ebr/<int:ebr_id>/audit-history")
@role_required("lab", "cert", "admin", "technolog")
def ebr_audit_history(ebr_id):
    """Return per-EBR audit history (sorted DESC by dt, with actors)."""
    from mbr.shared import audit
    with db_session() as db:
        history = audit.query_audit_history_for_entity(db, "ebr", ebr_id)
    return jsonify({"history": history})


@laborant_bp.route("/laborant/ebr/<int:ebr_id>/complete", methods=["POST"])
@role_required("lab", "admin")
def complete_entry(ebr_id):
    data = request.get_json(silent=True) or {}
    zbiorniki = data.get("zbiorniki")
    uwagi = (data.get("uwagi") or "").strip()
    with db_session() as db:
        # Read old status BEFORE completing
        row = db.execute("SELECT status FROM ebr_batches WHERE ebr_id=?", (ebr_id,)).fetchone()
        old_status = row["status"] if row else "unknown"

        complete_ebr(db, ebr_id, zbiorniki=zbiorniki)

        if uwagi:
            db.execute(
                "UPDATE ebr_batches SET uwagi_koncowe = ? WHERE ebr_id = ?",
                (uwagi, ebr_id),
            )

        # Audit: log status change
        payload = {"old_status": old_status, "new_status": "completed"}
        if zbiorniki:
            payload["przepompowanie_json"] = zbiorniki
        audit.log_event(
            audit.EVENT_EBR_BATCH_STATUS_CHANGED,
            entity_type="ebr",
            entity_id=ebr_id,
            payload=payload,
            db=db,
        )
        db.commit()

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
    sekcja = data["sekcja"]
    kod = data["kod_parametru"]
    with db_session() as db:
        # Read old samples_json before update
        old_row = db.execute(
            "SELECT samples_json FROM ebr_wyniki WHERE ebr_id=? AND sekcja=? AND kod_parametru=?",
            (ebr_id, sekcja, kod),
        ).fetchone()

        samples_json = json.dumps(data["samples"])
        now = datetime.now().isoformat(timespec="seconds")
        db.execute("""
            INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc,
                min_limit, max_limit, w_limicie, samples_json, is_manual, dt_wpisu, wpisal)
            VALUES (?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, 1, ?, ?)
            ON CONFLICT(ebr_id, sekcja, kod_parametru) DO UPDATE SET
                samples_json = excluded.samples_json,
                dt_wpisu = excluded.dt_wpisu,
                wpisal = excluded.wpisal
        """, (ebr_id, sekcja, kod, data.get("tag", ""),
              samples_json, now, session["user"]["login"]))

        # Audit: log samples update
        audit.log_event(
            audit.EVENT_EBR_WYNIK_UPDATED,
            entity_type="ebr",
            entity_id=ebr_id,
            payload={"sekcja": sekcja, "kod": kod, "type": "samples"},
            db=db,
        )
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
@role_required("lab", "cert", "admin")
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

        # Audit log (if save_uwagi actually did something)
        action = result.pop("_action", None)
        old_text = result.pop("_old_text", None)
        if action:
            audit.log_event(
                audit.EVENT_EBR_UWAGI_UPDATED,
                entity_type="ebr",
                entity_id=ebr_id,
                payload={"action": action, "tekst": old_text, "autor": autor},
                db=db,
            )
        db.commit()

        # Re-read after commit so historia includes the just-logged entry
        result = get_uwagi(db, ebr_id)
    return jsonify(result)


@laborant_bp.route("/api/ebr/<int:ebr_id>/uwagi", methods=["DELETE"])
@role_required("lab", "cert", "admin")
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

        # Audit log (if save_uwagi actually did something)
        action = result.pop("_action", None)
        old_text = result.pop("_old_text", None)
        if action:
            audit.log_event(
                audit.EVENT_EBR_UWAGI_UPDATED,
                entity_type="ebr",
                entity_id=ebr_id,
                payload={"action": action, "tekst": old_text, "autor": autor},
                db=db,
            )
        db.commit()

        # Re-read after commit so historia includes the just-logged entry
        result = get_uwagi(db, ebr_id)
    return jsonify(result)
