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
)


@laborant_bp.route("/laborant/szarze")
@role_required("laborant")
def szarze_list():
    from mbr.registry.models import list_completed_products
    with db_session() as db:
        batches = list_ebr_open(db)
        recent = list_ebr_recent(db, days=7)
        completed_products = list_completed_products(db)
    return render_template("laborant/szarze_list.html", batches=batches, recent=recent,
                           products=PRODUCTS, completed_products=completed_products)


@laborant_bp.route("/laborant/szarze/new", methods=["POST"])
@role_required("laborant")
def szarze_new():
    with db_session() as db:
        typ = request.form.get("typ", "szarza")
        wielkosc_kg = float(request.form.get("wielkosc_kg", 0) or 0)
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

        # Initialize process stage tracking for full-pipeline products
        if ebr_id and typ == 'szarza':
            from mbr.etapy_models import init_etapy_status, get_process_stages
            stages = get_process_stages(request.form["produkt"])
            if stages:
                init_etapy_status(db, ebr_id, request.form["produkt"])

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
@login_required
def save_entry(ebr_id):
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    sekcja = data.get("sekcja", "")
    values = data.get("values", {})
    # Use shift workers if set, otherwise fall back to login
    shift_ids = session.get("shift_workers", [])
    if shift_ids:
        with db_session() as db_w:
            placeholders = ",".join("?" * len(shift_ids))
            workers = db_w.execute(
                f"SELECT inicjaly, nickname FROM workers WHERE id IN ({placeholders})",
                shift_ids
            ).fetchall()
            user = ", ".join(w["nickname"] or w["inicjaly"] for w in workers)
    else:
        user = session["user"]["login"]

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


@laborant_bp.route("/api/ebr/<int:ebr_id>/audit")
@login_required
def get_audit_log(ebr_id):
    with db_session() as db:
        # Get all audit entries for this batch's records
        rows = db.execute("""
            SELECT a.* FROM audit_log a
            WHERE (a.tabela='ebr_etapy_analizy' AND a.rekord_id IN (SELECT id FROM ebr_etapy_analizy WHERE ebr_id=?))
               OR (a.tabela='ebr_wyniki' AND a.rekord_id IN (SELECT wynik_id FROM ebr_wyniki WHERE ebr_id=?))
            ORDER BY a.dt DESC
        """, (ebr_id, ebr_id)).fetchall()
    return jsonify({"audit": [dict(r) for r in rows]})


@laborant_bp.route("/laborant/ebr/<int:ebr_id>/complete", methods=["POST"])
@login_required
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
