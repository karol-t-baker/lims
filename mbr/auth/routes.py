from flask import redirect, url_for, request, session, render_template

from mbr.auth import auth_bp
from mbr.shared.decorators import login_required
from mbr.db import db_session
from mbr.auth.models import verify_user


@auth_bp.route("/login", methods=["GET", "POST"])
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
            return redirect(url_for("auth.index"))
        error = "Nieprawidłowy login lub hasło"
    return render_template("login.html", error=error)


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@auth_bp.route("/")
@login_required
def index():
    rola = session["user"]["rola"]
    if rola == "technolog":
        return redirect(url_for("technolog.mbr_list"))
    if rola == "admin":
        return redirect(url_for("admin.admin_panel"))
    return redirect(url_for("laborant.szarze_list"))
