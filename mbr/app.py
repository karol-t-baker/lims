"""
app.py — Minimal Flask app for MBR/EBR management.
"""

import functools
import os

from flask import Flask, redirect, url_for, request, session, render_template_string, flash

from mbr.models import get_db, init_mbr_tables, verify_user

app = Flask(__name__)
app.secret_key = os.environ.get("MBR_SECRET_KEY", "dev-secret-change-in-production")


# ---------------------------------------------------------------------------
# Auth decorators
# ---------------------------------------------------------------------------

def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def role_required(rola):
    """Decorator requiring a specific role (e.g. 'technolog')."""
    def decorator(f):
        @functools.wraps(f)
        @login_required
        def wrapper(*args, **kwargs):
            if session.get("rola") != rola:
                return "Brak uprawnień", 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

LOGIN_HTML = """
<!doctype html>
<title>MBR — Logowanie</title>
<h2>Logowanie</h2>
{% with messages = get_flashed_messages() %}
{% if messages %}<ul>{% for m in messages %}<li>{{ m }}</li>{% endfor %}</ul>{% endif %}
{% endwith %}
<form method="post">
  <label>Login: <input name="login"></label><br>
  <label>Hasło: <input name="password" type="password"></label><br>
  <button type="submit">Zaloguj</button>
</form>
"""


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_val = request.form.get("login", "")
        password = request.form.get("password", "")
        db = get_db()
        try:
            user = verify_user(db, login_val, password)
        finally:
            db.close()
        if user:
            session["user_id"] = user["user_id"]
            session["login"] = user["login"]
            session["rola"] = user["rola"]
            return redirect(url_for("index"))
        flash("Nieprawidłowy login lub hasło")
    return render_template_string(LOGIN_HTML)


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
    if session.get("rola") == "technolog":
        return redirect(url_for("mbr_list"))
    return redirect(url_for("szarze_list"))


# ---------------------------------------------------------------------------
# Stub routes
# ---------------------------------------------------------------------------

@app.route("/mbr")
@login_required
def mbr_list():
    return "<h2>Szablony MBR</h2><p>TODO</p>"


@app.route("/szarze")
@login_required
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


if __name__ == "__main__":
    app.run(port=5001, debug=True)
