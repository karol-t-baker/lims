"""
app.py — Minimal Flask app for MBR/EBR management.
"""

import functools
import json
import os
import socket
from datetime import datetime, date

from flask import Flask, Response, redirect, url_for, request, session, render_template, flash, jsonify, abort

from mbr.models import (
    get_db, db_session, init_mbr_tables, verify_user,
    list_mbr, get_mbr, save_mbr, activate_mbr, clone_mbr,
    list_ebr_open, list_ebr_completed, list_ebr_recent, export_wyniki_csv,
    create_ebr, get_ebr, get_ebr_wyniki, get_round_state, save_wyniki, complete_ebr,
    sync_ebr_to_v4, next_nr_partii, PRODUCTS,
    list_completed_registry, get_registry_columns, list_completed_products,
)

app = Flask(__name__)
app.secret_key = os.environ.get("MBR_SECRET_KEY", "dev-secret-change-in-prod")


# ---------------------------------------------------------------------------
# Template filters & context processors
# ---------------------------------------------------------------------------

@app.template_filter('pl_date')
def pl_date_filter(value):
    """Format ISO date to Polish: DD.MM.YYYY HH:MM"""
    if not value:
        return '\u2014'
    try:
        dt = datetime.fromisoformat(str(value))
        return dt.strftime('%d.%m.%Y %H:%M')
    except Exception:
        return str(value)[:16]


@app.template_filter('pl_date_short')
def pl_date_short_filter(value):
    """Format ISO date to Polish short: DD.MM.YYYY"""
    if not value:
        return '\u2014'
    try:
        dt = datetime.fromisoformat(str(value))
        return dt.strftime('%d.%m.%Y')
    except Exception:
        return str(value)[:10]


@app.template_filter('fmt_kg')
def fmt_kg_filter(value):
    """Format kg: 23444.0 -> 23 444"""
    if not value:
        return '\u2014'
    try:
        v = int(float(value))
        return f'{v:,}'.replace(',', ' ')
    except Exception:
        return str(value)


@app.template_filter('short_product')
def short_product_filter(value):
    """Chegina_K40GLOL -> K40GLOL, Chegina_K7 -> K7"""
    if not value:
        return ''
    return str(value).replace('Chegina_', '').replace('Chegina ', '')


@app.context_processor
def inject_today():
    return {'today': datetime.now().strftime('%d.%m.%Y')}


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
        with db_session() as db:
            user = verify_user(db, login_val, password)
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
    with db_session() as db:
        mbrs = list_mbr(db)
    return render_template("technolog/mbr_list.html", mbrs=mbrs)


@app.route("/technolog/mbr/<int:mbr_id>", methods=["GET", "POST"])
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
            return redirect(url_for("mbr_edit", mbr_id=mbr_id))
        mbr = get_mbr(db, mbr_id)
    if mbr is None:
        return "Nie znaleziono szablonu", 404
    return render_template("technolog/mbr_edit.html", mbr=mbr)


@app.route("/technolog/mbr/<int:mbr_id>/activate", methods=["POST"])
@role_required("technolog")
def mbr_activate(mbr_id):
    with db_session() as db:
        ok = activate_mbr(db, mbr_id)
    if not ok:
        flash("Nie udalo sie aktywowac szablonu.")
    else:
        flash("Szablon aktywowany.")
    return redirect(url_for("mbr_list"))


@app.route("/technolog/mbr/<int:mbr_id>/clone", methods=["POST"])
@role_required("technolog")
def mbr_clone(mbr_id):
    with db_session() as db:
        user = session["user"]["login"]
        new_id = clone_mbr(db, mbr_id, user)
    if new_id is None:
        flash("Nie udalo sie sklonowac szablonu.")
        return redirect(url_for("mbr_list"))
    flash("Sklonowano szablon.")
    return redirect(url_for("mbr_edit", mbr_id=new_id))


@app.route("/technolog/dashboard")
@role_required("technolog")
def tech_dashboard():
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


@app.route("/technolog/narzedzia")
@role_required("technolog")
def narzedzia():
    return render_template("technolog/narzedzia.html", today=date.today().isoformat())


@app.route("/technolog/narzedzia/wniosek-dojazd")
@role_required("technolog")
def wniosek_dojazd():
    return render_template("technolog/wniosek_dojazd.html", today=date.today().isoformat())


@app.route("/technolog/narzedzia/wniosek-dojazd/pdf", methods=["POST"])
@role_required("technolog")
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


@app.route("/technolog/export")
@role_required("technolog")
def tech_export():
    import csv
    import io

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


@app.route("/api/next-nr/<produkt>")
@login_required
def api_next_nr(produkt):
    with db_session() as db:
        nr = next_nr_partii(db, produkt)
    return jsonify({"nr_partii": nr})


@app.route("/api/registry")
@login_required
def api_registry():
    produkt = request.args.get("produkt", "Chegina_K7")
    typ = request.args.get("typ", "")
    with db_session() as db:
        batches = list_completed_registry(db, produkt=produkt, typ=typ or None)
        columns = get_registry_columns(db, produkt)
    return jsonify({"batches": batches, "columns": columns, "produkt": produkt})


@app.route("/laborant/szarze")
@role_required("laborant")
def szarze_list():
    with db_session() as db:
        batches = list_ebr_open(db)
        recent = list_ebr_recent(db, days=7)
        completed_products = list_completed_products(db)
    return render_template("laborant/szarze_list.html", batches=batches, recent=recent,
                           products=PRODUCTS, completed_products=completed_products)


@app.route("/laborant/szarze/new", methods=["POST"])
@role_required("laborant")
def szarze_new():
    with db_session() as db:
        typ = request.form.get("typ", "szarza")
        nastaw_raw = request.form.get("nastaw", "")
        nastaw = int(nastaw_raw) if nastaw_raw else None
        ebr_id = create_ebr(
            db,
            produkt=request.form["produkt"],
            nr_partii=request.form["nr_partii"],
            nr_amidatora=request.form.get("nr_amidatora", ""),
            nr_mieszalnika=request.form.get("nr_mieszalnika", ""),
            wielkosc_kg=float(request.form.get("wielkosc_kg", 0) or 0),
            operator=session["user"]["login"],
            typ=typ,
            nastaw=nastaw,
        )

    if ebr_id is None:
        flash("Brak aktywnego szablonu MBR dla tego produktu.")
    # Return to referring page (fast_entry or szarze_list)
    back = request.form.get("_back") or request.referrer or url_for("szarze_list")
    return redirect(back)


@app.route("/laborant/ebr/<int:ebr_id>")
@login_required
def fast_entry(ebr_id):
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


@app.route("/laborant/ebr/<int:ebr_id>/partial")
@login_required
def fast_entry_partial(ebr_id):
    """Return just the fast-entry form HTML (no base.html shell) for AJAX loading."""
    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        if ebr is None:
            return "Nie znaleziono", 404
        wyniki = get_ebr_wyniki(db, ebr_id)
        round_state = get_round_state(wyniki)
    return render_template("laborant/_fast_entry_content.html",
                           ebr=ebr, wyniki=wyniki, round_state=round_state)


@app.route("/laborant/ebr/<int:ebr_id>/save", methods=["POST"])
@login_required
def save_entry(ebr_id):
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    sekcja = data.get("sekcja", "")
    values = data.get("values", {})
    user = session["user"]["login"]

    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        save_wyniki(db, ebr_id, sekcja, values, user, ebr=ebr)
        sync_ebr_to_v4(db, ebr_id, ebr=ebr)
    return jsonify({"ok": True})


@app.route("/laborant/ebr/<int:ebr_id>/complete", methods=["POST"])
@login_required
def complete_entry(ebr_id):
    with db_session() as db:
        complete_ebr(db, ebr_id)
        sync_ebr_to_v4(db, ebr_id)
    # Support AJAX calls from SPA
    if request.is_json or request.headers.get("Content-Type", "").startswith("application/json"):
        return jsonify({"ok": True})
    return redirect(url_for("szarze_list"))


# ---------------------------------------------------------------------------
# Titration samples API (persistent naważki/volumes)
# ---------------------------------------------------------------------------

@app.route("/api/ebr/<int:ebr_id>/samples", methods=["POST"])
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


@app.route("/api/ebr/<int:ebr_id>/samples/<sekcja>/<kod>")
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
# PDF routes
# ---------------------------------------------------------------------------

from mbr.pdf_gen import generate_pdf


@app.route("/pdf/mbr/<int:mbr_id>")
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


@app.route("/pdf/ebr/<int:ebr_id>")
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


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

with app.app_context():
    with db_session() as db:
        init_mbr_tables(db)


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
