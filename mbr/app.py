"""
app.py — Minimal Flask app for MBR/EBR management.
"""

import functools
import os
import socket

from flask import Flask, redirect, url_for, request, session, render_template, flash

from mbr.models import (
    get_db, init_mbr_tables, verify_user,
    list_mbr, get_mbr, save_mbr, activate_mbr, clone_mbr,
    list_ebr_open, list_ebr_completed, export_wyniki_csv,
)

app = Flask(__name__)
app.secret_key = os.environ.get("MBR_SECRET_KEY", "dev-secret-change-in-prod")


# ---------------------------------------------------------------------------
# Auth decorators
# ---------------------------------------------------------------------------

def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def role_required(rola):
    """Decorator requiring a specific role (e.g. 'technolog')."""
    def decorator(f):
        @functools.wraps(f)
        @login_required
        def wrapper(*args, **kwargs):
            if session["user"]["rola"] != rola:
                return "Brak uprawnień", 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        login_val = request.form.get("login", "")
        password = request.form.get("password", "")
        db = get_db()
        try:
            user = verify_user(db, login_val, password)
        finally:
            db.close()
        if user:
            session["user"] = {
                "login": user["login"],
                "rola": user["rola"],
                "imie_nazwisko": user.get("imie_nazwisko"),
            }
            return redirect(url_for("index"))
        error = "Nieprawidłowy login lub hasło"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Index — redirect based on role
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def index():
    if session["user"]["rola"] == "technolog":
        return redirect(url_for("mbr_list"))
    return redirect(url_for("szarze_list"))


# ---------------------------------------------------------------------------
# Stub routes
# ---------------------------------------------------------------------------

@app.route("/technolog/mbr")
@role_required("technolog")
def mbr_list():
    db = get_db()
    try:
        mbrs = list_mbr(db)
    finally:
        db.close()
    return render_template("technolog/mbr_list.html", mbrs=mbrs)


@app.route("/technolog/mbr/<int:mbr_id>", methods=["GET", "POST"])
@role_required("technolog")
def mbr_edit(mbr_id):
    db = get_db()
    try:
        if request.method == "POST":
            etapy_json = request.form.get("etapy_json", "[]")
            parametry_lab = request.form.get("parametry_lab", "{}")
            notatki = request.form.get("notatki", "")
            ok = save_mbr(db, mbr_id, etapy_json, parametry_lab, notatki)
            if not ok:
                flash("Nie udalo sie zapisac — szablon nie jest w trybie draft.")
            else:
                flash("Zapisano.")
            return redirect(url_for("mbr_edit", mbr_id=mbr_id))
        mbr = get_mbr(db, mbr_id)
    finally:
        db.close()
    if mbr is None:
        return "Nie znaleziono szablonu", 404
    return render_template("technolog/mbr_edit.html", mbr=mbr)


@app.route("/technolog/mbr/<int:mbr_id>/activate", methods=["POST"])
@role_required("technolog")
def mbr_activate(mbr_id):
    db = get_db()
    try:
        ok = activate_mbr(db, mbr_id)
    finally:
        db.close()
    if not ok:
        flash("Nie udalo sie aktywowac szablonu.")
    else:
        flash("Szablon aktywowany.")
    return redirect(url_for("mbr_list"))


@app.route("/technolog/mbr/<int:mbr_id>/clone", methods=["POST"])
@role_required("technolog")
def mbr_clone(mbr_id):
    db = get_db()
    try:
        user = session["user"]["login"]
        new_id = clone_mbr(db, mbr_id, user)
    finally:
        db.close()
    if new_id is None:
        flash("Nie udalo sie sklonowac szablonu.")
        return redirect(url_for("mbr_list"))
    flash("Sklonowano szablon.")
    return redirect(url_for("mbr_edit", mbr_id=new_id))


@app.route("/technolog/dashboard")
@role_required("technolog")
def tech_dashboard():
    db = get_db()
    try:
        open_batches = list_ebr_open(db)
        completed = list_ebr_completed(db, request.args.get("produkt"))
    finally:
        db.close()
    return render_template(
        "technolog/dashboard.html",
        open_batches=open_batches,
        completed=completed,
    )


@app.route("/technolog/export")
@role_required("technolog")
def tech_export():
    import csv
    import io
    from flask import Response

    db = get_db()
    try:
        rows = export_wyniki_csv(db, request.args.get("produkt"))
    finally:
        db.close()
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


@app.route("/laborant/szarze")
@role_required("laborant")
def szarze_list():
    return "<h2>Szarże EBR</h2><p>TODO</p>"


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

with app.app_context():
    db = get_db()
    try:
        init_mbr_tables(db)
    finally:
        db.close()


def _get_local_ip() -> str:
    """Best-effort local network IP."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    ip = _get_local_ip()
    print(f" * Network: http://{ip}:5001/")
    app.run(host="0.0.0.0", port=5001, debug=True)
