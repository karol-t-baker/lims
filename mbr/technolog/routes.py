"""
technolog/routes.py — MBR CRUD and technolog dashboard routes.
"""

from flask import request, session, render_template, redirect, url_for, flash, jsonify

from mbr.technolog import technolog_bp
from mbr.technolog.models import list_mbr, get_mbr, save_mbr, activate_mbr, clone_mbr
from mbr.shared.decorators import role_required
from mbr.db import db_session


@technolog_bp.route("/technolog/mbr")
@role_required("technolog")
def mbr_list():
    with db_session() as db:
        mbrs = list_mbr(db)
    return render_template("technolog/mbr_list.html", mbrs=mbrs)


@technolog_bp.route("/technolog/mbr/<int:mbr_id>", methods=["GET", "POST"])
@role_required("technolog")
def mbr_edit(mbr_id):
    with db_session() as db:
        if request.method == "POST":
            etapy_json = request.form.get("etapy_json", "[]")
            parametry_lab = request.form.get("parametry_lab", "{}")
            notatki = request.form.get("notatki", "")
            ok = save_mbr(db, mbr_id, etapy_json, parametry_lab, notatki)
            if not ok:
                flash("Nie udalo sie zapisac — szablon nie jest w trybie draft.")
            else:
                flash("Zapisano.")
            return redirect(url_for("technolog.mbr_edit", mbr_id=mbr_id))
        mbr = get_mbr(db, mbr_id)
    if mbr is None:
        return "Nie znaleziono szablonu", 404
    return render_template("technolog/mbr_edit.html", mbr=mbr)


@technolog_bp.route("/technolog/mbr/<int:mbr_id>/activate", methods=["POST"])
@role_required("technolog")
def mbr_activate(mbr_id):
    with db_session() as db:
        ok = activate_mbr(db, mbr_id)
    if not ok:
        flash("Nie udalo sie aktywowac szablonu.")
    else:
        flash("Szablon aktywowany.")
    return redirect(url_for("technolog.mbr_list"))


@technolog_bp.route("/api/mbr/<int:mbr_id>/audit-history")
@role_required("admin", "technolog")
def mbr_audit_history(mbr_id):
    """Return per-MBR audit history (sorted DESC by dt, with actors)."""
    from mbr.shared import audit
    with db_session() as db:
        history = audit.query_audit_history_for_entity(db, "mbr", mbr_id)
    return jsonify({"history": history})


@technolog_bp.route("/technolog/mbr/<int:mbr_id>/clone", methods=["POST"])
@role_required("technolog")
def mbr_clone(mbr_id):
    with db_session() as db:
        user = session["user"]["login"]
        new_id = clone_mbr(db, mbr_id, user)
    if new_id is None:
        flash("Nie udalo sie sklonowac szablonu.")
        return redirect(url_for("technolog.mbr_list"))
    flash("Sklonowano szablon.")
    return redirect(url_for("technolog.mbr_edit", mbr_id=new_id))


@technolog_bp.route("/technolog/dashboard")
@role_required("technolog")
def tech_dashboard():
    from mbr.models import list_ebr_open, list_ebr_completed  # avoid circular import
    produkt = request.args.get("produkt")
    typ = request.args.get("typ")
    with db_session() as db:
        open_batches = list_ebr_open(db, produkt=produkt, typ=typ)
        completed = list_ebr_completed(db, produkt=produkt, typ=typ)
    return render_template(
        "technolog/dashboard.html",
        open_batches=open_batches,
        completed=completed,
        filter_produkt=produkt,
        filter_typ=typ,
    )
