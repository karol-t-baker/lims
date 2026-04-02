# MBR/EBR System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Flask webapp for managing batch card templates (MBR) and electronic batch records (EBR) with lab data entry and PDF generation.

**Architecture:** Flask + SQLite (same `batch_db_v4.sqlite`) + Jinja2 templates + vanilla JS. New tables (`mbr_templates`, `ebr_batches`, `ebr_wyniki`, `mbr_users`) alongside existing v4 tables. Warm teal design system from `ui_concepts/selected/`. EBR results sync to v4 `events` table with `_source = "digital"`.

**Tech Stack:** Python 3, Flask, SQLite, bcrypt, Jinja2, WeasyPrint, vanilla JS

**Spec:** `docs/superpowers/specs/2026-04-02-mbr-ebr-system-design.md`

**UI References:**
- Layout: `ui_concepts/selected/layout_split_sidebar.html`
- Style: `ui_concepts/selected/styl_warm_teal.html`
- Calculator: `ui_concepts/selected/koncowa_right_panel_calc.html`
- Dashboard: `ui_concepts/selected/dashboard_queue.html`
- Sidebar tabs: `ui_concepts/selected/v6_02_three_tabs.html`

---

## File Structure

```
mbr/
├── app.py                  # Flask app factory, auth, routing
├── models.py               # SQLite DAL — all CRUD for MBR, EBR, wyniki, users
├── pdf_gen.py              # Jinja2 → WeasyPrint PDF generation
├── seed_mbr.py             # One-time: create 4 MBR templates + seed users
├── templates/
│   ├── base.html           # Shell layout: nav rail + sidebar + main + footer
│   ├── login.html          # Login form
│   ├── technolog/
│   │   ├── mbr_list.html   # MBR list with status/actions
│   │   ├── mbr_edit.html   # Two-tab MBR editor (etapy + parametry)
│   │   └── dashboard.html  # Live + history views
│   ├── laborant/
│   │   ├── szarze_list.html    # Open batches list
│   │   └── fast_entry.html     # Analysis form + right panel (ref/calc)
│   └── pdf/
│       └── karta_base.html     # A4 PDF template (4-page batch card)
├── static/
│   ├── style.css           # Warm teal design system (extracted from concepts)
│   └── calculator.js       # Titration calculator (extracted from concepts)
└── requirements.txt        # Flask, bcrypt, WeasyPrint
```

---

## Task 1: Project scaffold + database schema

**Files:**
- Create: `mbr/requirements.txt`
- Create: `mbr/models.py`
- Create: `mbr/app.py` (minimal)

- [ ] **Step 1: Create requirements.txt**

```
Flask>=3.0
bcrypt>=4.1
WeasyPrint>=62.0
```

- [ ] **Step 2: Install dependencies**

Run: `cd /Users/tbk/Desktop/aa && pip install -r mbr/requirements.txt`

- [ ] **Step 3: Write models.py with schema creation and user CRUD**

Create `mbr/models.py` with:

```python
import sqlite3
import json
import bcrypt
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "data" / "batch_db_v4.sqlite"


def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_mbr_tables(db: sqlite3.Connection):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS mbr_users (
        user_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        login       TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        rola        TEXT NOT NULL CHECK(rola IN ('technolog', 'laborant')),
        imie_nazwisko TEXT
    );

    CREATE TABLE IF NOT EXISTS mbr_templates (
        mbr_id          INTEGER PRIMARY KEY AUTOINCREMENT,
        produkt         TEXT NOT NULL,
        wersja          INTEGER NOT NULL DEFAULT 1,
        status          TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'active', 'archived')),
        etapy_json      TEXT NOT NULL DEFAULT '[]',
        parametry_lab   TEXT NOT NULL DEFAULT '{}',
        utworzony_przez  TEXT,
        dt_utworzenia    TEXT NOT NULL,
        dt_aktywacji    TEXT,
        notatki         TEXT,
        UNIQUE(produkt, wersja)
    );

    CREATE TABLE IF NOT EXISTS ebr_batches (
        ebr_id              INTEGER PRIMARY KEY AUTOINCREMENT,
        mbr_id              INTEGER NOT NULL REFERENCES mbr_templates(mbr_id),
        batch_id            TEXT UNIQUE NOT NULL,
        nr_partii           TEXT NOT NULL,
        nr_amidatora        TEXT,
        nr_mieszalnika      TEXT,
        wielkosc_szarzy_kg  REAL,
        surowce_json        TEXT,
        dt_start            TEXT NOT NULL,
        dt_end              TEXT,
        status              TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'completed', 'cancelled')),
        operator            TEXT
    );

    CREATE TABLE IF NOT EXISTS ebr_wyniki (
        wynik_id        INTEGER PRIMARY KEY AUTOINCREMENT,
        ebr_id          INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
        sekcja          TEXT NOT NULL,
        kod_parametru   TEXT NOT NULL,
        tag             TEXT NOT NULL,
        wartosc         REAL,
        min_limit       REAL,
        max_limit       REAL,
        w_limicie       INTEGER,
        komentarz       TEXT,
        is_manual       INTEGER NOT NULL DEFAULT 1,
        dt_wpisu        TEXT NOT NULL,
        wpisal          TEXT NOT NULL,
        UNIQUE(ebr_id, sekcja, kod_parametru)
    );
    """)
    db.commit()


# ── User CRUD ──

def create_user(db: sqlite3.Connection, login: str, password: str, rola: str, imie_nazwisko: str = ""):
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    db.execute(
        "INSERT INTO mbr_users (login, password_hash, rola, imie_nazwisko) VALUES (?, ?, ?, ?)",
        (login, pw_hash, rola, imie_nazwisko),
    )
    db.commit()


def verify_user(db: sqlite3.Connection, login: str, password: str) -> dict | None:
    row = db.execute("SELECT * FROM mbr_users WHERE login = ?", (login,)).fetchone()
    if row and bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        return dict(row)
    return None
```

- [ ] **Step 4: Write minimal app.py with auth**

Create `mbr/app.py`:

```python
from flask import Flask, session, request, redirect, url_for, render_template, jsonify, abort
from functools import wraps
from models import get_db, init_mbr_tables, verify_user
import os

app = Flask(__name__)
app.secret_key = os.urandom(32)


# ── Auth helpers ──

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def role_required(rola):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user" not in session:
                return redirect(url_for("login"))
            if session["user"]["rola"] != rola:
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        db = get_db()
        user = verify_user(db, request.form["login"], request.form["password"])
        db.close()
        if user:
            session["user"] = {"login": user["login"], "rola": user["rola"], "imie_nazwisko": user["imie_nazwisko"]}
            if user["rola"] == "technolog":
                return redirect(url_for("mbr_list"))
            return redirect(url_for("szarze_list"))
        error = "Nieprawidłowy login lub hasło"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    if session["user"]["rola"] == "technolog":
        return redirect(url_for("mbr_list"))
    return redirect(url_for("szarze_list"))


# ── Stub routes (implemented in later tasks) ──

@app.route("/technolog/mbr")
@role_required("technolog")
def mbr_list():
    return "MBR list (Task 3)"


@app.route("/laborant/szarze")
@role_required("laborant")
def szarze_list():
    return "Szarże list (Task 5)"


# ── Init ──

with app.app_context():
    db = get_db()
    init_mbr_tables(db)
    db.close()


if __name__ == "__main__":
    import socket
    local_ip = socket.gethostbyname(socket.gethostname())
    print(f"MBR: http://localhost:5001  |  sieć: http://{local_ip}:5001")
    app.run(host="0.0.0.0", port=5001, debug=True)
```

- [ ] **Step 5: Test scaffold manually**

Run: `cd /Users/tbk/Desktop/aa && python -c "from mbr.models import get_db, init_mbr_tables; db = get_db(); init_mbr_tables(db); print('OK'); db.close()"`
Expected: `OK` — tables created in `data/batch_db_v4.sqlite`

Verify tables:
Run: `sqlite3 data/batch_db_v4.sqlite ".tables" | grep mbr`
Expected: output contains `mbr_templates  mbr_users  ebr_batches  ebr_wyniki`

- [ ] **Step 6: Commit**

```bash
git add mbr/requirements.txt mbr/models.py mbr/app.py
git commit -m "feat(mbr): project scaffold — models, auth, DB schema"
```

---

## Task 2: Seed MBR data + static assets

**Files:**
- Create: `mbr/seed_mbr.py`
- Create: `mbr/static/style.css`
- Create: `mbr/templates/login.html`
- Create: `mbr/templates/base.html`

- [ ] **Step 1: Write seed_mbr.py**

This script creates 4 MBR templates (one per product) + 2 seed users. The `parametry_lab` fields use placeholder limits — user will provide real values later from a separate file.

```python
"""One-time seed: create 4 MBR templates + demo users."""
import json
from datetime import datetime
from models import get_db, init_mbr_tables, create_user

ETAPY_COMMON = [
    {"nr": 1, "nazwa": "Amidowanie", "instrukcja": "Załadować surowce wg receptury. Włączyć reaktor, ustawić temperaturę docelową.", "read_only": True},
    {"nr": 2, "nazwa": "Wytworzenie SMCA", "instrukcja": "Rozpuścić MCA w wodzie, dodać NaOH do neutralizacji.", "read_only": True},
    {"nr": 3, "nazwa": "Czwartorzędowanie", "instrukcja": "Przeciągnąć amid do mieszalnika. Dozować SMCA porcjami z NaOH.", "read_only": True},
    {"nr": 4, "nazwa": "Analiza przed standaryzacją", "instrukcja": "Pobrać próbkę do analizy międzyoperacyjnej.", "read_only": False, "sekcja_lab": "przed_standaryzacja"},
    {"nr": 5, "nazwa": "Standaryzacja", "instrukcja": "Dodatek wody, kwasu cytrynowego i pozostałych dodatków.", "read_only": True},
    {"nr": 6, "nazwa": "Analiza końcowa", "instrukcja": "Pobrać próbkę końcową. Wykonać pełną analizę.", "read_only": False, "sekcja_lab": "analiza_koncowa"},
    {"nr": 7, "nazwa": "Przepompowanie", "instrukcja": "Przepompować produkt do zbiornika magazynowego.", "read_only": True},
]

# Placeholder limits — will be replaced with real values from user's file
PARAMETRY_TEMPLATE = {
    "przed_standaryzacja": {
        "label": "Analiza przed standaryzacją",
        "pola": [
            {"kod": "ph_10proc", "label": "pH 10%", "tag": "ph_10proc", "typ": "float", "min": 4.0, "max": 7.0, "precision": 1},
            {"kod": "nd20", "label": "nd20", "tag": "nd20", "typ": "float", "min": 1.3900, "max": 1.4200, "precision": 4},
            {"kod": "procent_so3", "label": "%SO3", "tag": "procent_so3", "typ": "float", "min": 0.0, "max": 0.030, "precision": 3},
            {"kod": "barwa_fau", "label": "Barwa FAU", "tag": "barwa_fau", "typ": "float", "min": 0, "max": 200, "precision": 0},
        ],
    },
    "analiza_koncowa": {
        "label": "Analiza końcowa",
        "pola": [
            {"kod": "ph_10proc", "label": "pH 10%", "tag": "ph_10proc", "typ": "float", "min": 4.0, "max": 6.5, "precision": 1},
            {"kod": "nd20", "label": "nd20", "tag": "nd20", "typ": "float", "min": 1.3900, "max": 1.4200, "precision": 4},
            {"kod": "procent_sm", "label": "%SM", "tag": "procent_sm", "typ": "float", "min": 40.0, "max": 50.0, "precision": 1},
            {"kod": "procent_sa", "label": "%SA", "tag": "procent_sa", "typ": "float", "min": 30.0, "max": 45.0, "precision": 2},
            {"kod": "procent_nacl", "label": "%NaCl", "tag": "procent_nacl", "typ": "float", "min": 4.0, "max": 8.0, "precision": 1},
            {"kod": "procent_aa", "label": "%AA", "tag": "procent_aa", "typ": "float", "min": 0.0, "max": 0.5, "precision": 2},
            {"kod": "procent_so3", "label": "%SO3", "tag": "procent_so3", "typ": "float", "min": 0.0, "max": 0.030, "precision": 3},
            {"kod": "procent_h2o2", "label": "%H2O2", "tag": "procent_h2o2", "typ": "float", "min": 0.0, "max": 0.010, "precision": 3},
            {"kod": "le_liczba_kwasowa", "label": "LK=", "tag": "lk", "typ": "float", "min": 1.0, "max": 10.0, "precision": 1},
            {"kod": "barwa_fau", "label": "Barwa FAU", "tag": "barwa_fau", "typ": "float", "min": 0, "max": 200, "precision": 0},
            {"kod": "barwa_hz", "label": "Barwa Hz", "tag": "barwa_hz", "typ": "float", "min": 0, "max": 100, "precision": 0},
        ],
    },
}

PRODUCTS = [
    ("Chegina_K7", "T121"),
    ("Chegina_K40GL", "T111"),
    ("Chegina_K40GLO", "T118"),
    ("Chegina_K40GLOL", "T118"),
]


def seed():
    db = get_db()
    init_mbr_tables(db)

    # Check if already seeded
    count = db.execute("SELECT COUNT(*) FROM mbr_templates").fetchone()[0]
    if count > 0:
        print(f"Already seeded ({count} MBR templates). Skipping.")
        db.close()
        return

    now = datetime.now().isoformat(timespec="seconds")

    for produkt, template_id in PRODUCTS:
        db.execute(
            """INSERT INTO mbr_templates
               (produkt, wersja, status, etapy_json, parametry_lab, utworzony_przez, dt_utworzenia, dt_aktywacji, notatki)
               VALUES (?, 1, 'active', ?, ?, 'seed', ?, ?, ?)""",
            (
                produkt,
                json.dumps(ETAPY_COMMON, ensure_ascii=False),
                json.dumps(PARAMETRY_TEMPLATE, ensure_ascii=False),
                now,
                now,
                f"Seed z szablonu {template_id}. Limity placeholder — do uzupełnienia.",
            ),
        )
        print(f"  MBR: {produkt} v1 (active)")

    # Seed users
    try:
        create_user(db, "technolog", "tech123", "technolog", "Technolog Demo")
        create_user(db, "laborant", "lab123", "laborant", "Laborant Demo")
        print("  Users: technolog, laborant")
    except Exception:
        print("  Users already exist, skipping.")

    db.commit()
    db.close()
    print("Seed complete.")


if __name__ == "__main__":
    seed()
```

- [ ] **Step 2: Write static/style.css**

Extract warm teal design system from `ui_concepts/selected/styl_warm_teal.html`. This is the complete CSS for the app — all components (rail, sidebar, stages, entries, forms, buttons, reference cards, footer).

Copy the full CSS from `styl_warm_teal.html` (lines 8-113) plus additional components from `layout_split_sidebar.html` (sidebar toggle, stage items) and `koncowa_right_panel_calc.html` (right panel tabs, calculator, section cards, form fields with titr indicator). Merge into one file, deduplicate. Keep all CSS variables in `:root`.

Key additions beyond the base warm_teal:
- `.locked` stage styling (opacity 0.5, cursor not-allowed, lock icon)
- `.sb-toggle` 3-way toggle from `v6_02_three_tabs.html` (lines 33-36)
- `.rp-tabs`, `.rp-view`, `.calc-*` from `koncowa_right_panel_calc.html` (lines 57-103)
- `.section`, `.sec-head`, `.fg`, `.ff`, `.ff.titr` from `koncowa_right_panel_calc.html` (lines 106-132)
- Red state: `--red: #b91c1c; --red-bg: #fef2f2;` for out-of-limit validation

- [ ] **Step 3: Write templates/login.html**

```html
<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MBR — Logowanie</title>
<link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
<style>
body { display: flex; align-items: center; justify-content: center; min-height: 100vh; background: var(--bg); }
.login-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 40px; width: 360px; }
.login-card h1 { font-size: 20px; font-weight: 700; margin-bottom: 4px; }
.login-card .sub { font-size: 13px; color: var(--text-dim); margin-bottom: 24px; }
.login-card label { display: block; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-dim); font-weight: 600; margin-bottom: 4px; }
.login-card input { width: 100%; padding: 10px 12px; border: 1.5px solid var(--border); border-radius: var(--radius); font-size: 14px; margin-bottom: 16px; font-family: var(--font); }
.login-card input:focus { outline: none; border-color: var(--teal); box-shadow: 0 0 0 3px var(--teal-bg); }
.login-card button { width: 100%; padding: 11px; background: var(--teal); color: white; border: none; border-radius: var(--radius); font-size: 14px; font-weight: 600; cursor: pointer; }
.login-card button:hover { filter: brightness(1.1); }
.login-error { background: var(--red-bg, #fef2f2); color: var(--red, #b91c1c); padding: 8px 12px; border-radius: var(--radius); font-size: 12px; margin-bottom: 16px; }
</style>
</head>
<body>
<div class="login-card">
  <h1>Karty Szarżowe</h1>
  <div class="sub">System MBR / EBR</div>
  {% if error %}<div class="login-error">{{ error }}</div>{% endif %}
  <form method="POST">
    <label>Login</label>
    <input name="login" type="text" required autofocus>
    <label>Hasło</label>
    <input name="password" type="password" required>
    <button type="submit">Zaloguj</button>
  </form>
</div>
</body>
</html>
```

- [ ] **Step 4: Write templates/base.html**

Shell layout matching `layout_split_sidebar.html`:

```html
<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{% block title %}MBR{% endblock %}</title>
<link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
{% block head %}{% endblock %}
</head>
<body>

<div class="rail">
  <div class="rail-logo">KS</div>
  {% if session.user.rola == 'technolog' %}
  <a href="{{ url_for('mbr_list') }}" class="rail-btn {% block nav_mbr %}{% endblock %}" title="Szablony MBR">&#9881;</a>
  <a href="{{ url_for('tech_dashboard') }}" class="rail-btn {% block nav_dashboard %}{% endblock %}" title="Dashboard">&#128203;</a>
  {% else %}
  <a href="{{ url_for('szarze_list') }}" class="rail-btn {% block nav_szarze %}{% endblock %}" title="Analizy">&#9883;</a>
  {% endif %}
  <div class="rail-sp"></div>
  <a href="{{ url_for('logout') }}" class="rail-av" title="{{ session.user.imie_nazwisko }} — wyloguj">
    {{ session.user.imie_nazwisko[:2] | upper }}
  </a>
</div>

{% block sidebar %}{% endblock %}

<div class="main">
  <div class="topbar">
    {% block topbar %}{% endblock %}
  </div>
  <div class="workspace">
    {% block content %}{% endblock %}
  </div>
  <div class="footer">
    {% block footer %}{% endblock %}
  </div>
</div>

{% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 5: Run seed + verify**

Run: `cd /Users/tbk/Desktop/aa && python -m mbr.seed_mbr`
Expected: prints 4 MBR entries + 2 users

Run: `sqlite3 data/batch_db_v4.sqlite "SELECT produkt, wersja, status FROM mbr_templates"`
Expected: 4 rows, all `active`, version 1

Run: `cd /Users/tbk/Desktop/aa && python -m mbr.app`
Open `http://localhost:5001/login`, login as `technolog` / `tech123`.
Expected: redirect to `/technolog/mbr` (shows stub text)

- [ ] **Step 6: Commit**

```bash
git add mbr/seed_mbr.py mbr/static/style.css mbr/templates/login.html mbr/templates/base.html
git commit -m "feat(mbr): seed MBR data, auth UI, base layout, warm teal CSS"
```

---

## Task 3: MBR List + Editor (Panel Technologa)

**Files:**
- Modify: `mbr/models.py` — add MBR CRUD functions
- Modify: `mbr/app.py` — add MBR routes
- Create: `mbr/templates/technolog/mbr_list.html`
- Create: `mbr/templates/technolog/mbr_edit.html`

- [ ] **Step 1: Add MBR CRUD to models.py**

Append to `mbr/models.py`:

```python
# ── MBR CRUD ──

def list_mbr(db: sqlite3.Connection) -> list[dict]:
    rows = db.execute(
        "SELECT * FROM mbr_templates ORDER BY produkt, wersja DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_mbr(db: sqlite3.Connection, mbr_id: int) -> dict | None:
    row = db.execute("SELECT * FROM mbr_templates WHERE mbr_id = ?", (mbr_id,)).fetchone()
    return dict(row) if row else None


def get_active_mbr(db: sqlite3.Connection, produkt: str) -> dict | None:
    row = db.execute(
        "SELECT * FROM mbr_templates WHERE produkt = ? AND status = 'active'", (produkt,)
    ).fetchone()
    return dict(row) if row else None


def save_mbr(db: sqlite3.Connection, mbr_id: int, etapy_json: str, parametry_lab: str, notatki: str):
    db.execute(
        "UPDATE mbr_templates SET etapy_json = ?, parametry_lab = ?, notatki = ? WHERE mbr_id = ? AND status = 'draft'",
        (etapy_json, parametry_lab, notatki, mbr_id),
    )
    db.commit()


def activate_mbr(db: sqlite3.Connection, mbr_id: int):
    mbr = get_mbr(db, mbr_id)
    if not mbr or mbr["status"] != "draft":
        raise ValueError("Tylko draft można aktywować")
    # Archive current active for this product
    db.execute(
        "UPDATE mbr_templates SET status = 'archived' WHERE produkt = ? AND status = 'active'",
        (mbr["produkt"],),
    )
    db.execute(
        "UPDATE mbr_templates SET status = 'active', dt_aktywacji = ? WHERE mbr_id = ?",
        (datetime.now().isoformat(timespec="seconds"), mbr_id),
    )
    db.commit()


def clone_mbr(db: sqlite3.Connection, mbr_id: int, user: str) -> int:
    src = get_mbr(db, mbr_id)
    if not src:
        raise ValueError("MBR not found")
    max_ver = db.execute(
        "SELECT MAX(wersja) FROM mbr_templates WHERE produkt = ?", (src["produkt"],)
    ).fetchone()[0] or 0
    now = datetime.now().isoformat(timespec="seconds")
    cursor = db.execute(
        """INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, utworzony_przez, dt_utworzenia, notatki)
           VALUES (?, ?, 'draft', ?, ?, ?, ?, ?)""",
        (src["produkt"], max_ver + 1, src["etapy_json"], src["parametry_lab"], user, now,
         f"Klon z wersji {src['wersja']}"),
    )
    db.commit()
    return cursor.lastrowid
```

- [ ] **Step 2: Add MBR routes to app.py**

Replace the `mbr_list` stub and add new routes in `mbr/app.py`:

```python
from models import get_db, init_mbr_tables, verify_user, list_mbr, get_mbr, save_mbr, activate_mbr, clone_mbr
import json

@app.route("/technolog/mbr")
@role_required("technolog")
def mbr_list():
    db = get_db()
    templates = list_mbr(db)
    db.close()
    return render_template("technolog/mbr_list.html", templates=templates)


@app.route("/technolog/mbr/<int:mbr_id>", methods=["GET", "POST"])
@role_required("technolog")
def mbr_edit(mbr_id):
    db = get_db()
    mbr = get_mbr(db, mbr_id)
    if not mbr:
        abort(404)
    if request.method == "POST" and mbr["status"] == "draft":
        save_mbr(db, mbr_id, request.form["etapy_json"], request.form["parametry_lab"], request.form.get("notatki", ""))
        db.close()
        return redirect(url_for("mbr_edit", mbr_id=mbr_id))
    db.close()
    return render_template("technolog/mbr_edit.html", mbr=mbr)


@app.route("/technolog/mbr/<int:mbr_id>/activate", methods=["POST"])
@role_required("technolog")
def mbr_activate(mbr_id):
    db = get_db()
    activate_mbr(db, mbr_id)
    db.close()
    return redirect(url_for("mbr_list"))


@app.route("/technolog/mbr/<int:mbr_id>/clone", methods=["POST"])
@role_required("technolog")
def mbr_clone(mbr_id):
    db = get_db()
    new_id = clone_mbr(db, mbr_id, session["user"]["login"])
    db.close()
    return redirect(url_for("mbr_edit", mbr_id=new_id))
```

- [ ] **Step 3: Write mbr_list.html**

Create `mbr/templates/technolog/mbr_list.html`:

Template extends `base.html`. Shows a table of all MBR templates with columns: Produkt, Wersja, Status (badge colored by status), Data aktywacji, Akcje (Edytuj if draft, Aktywuj if draft, Klonuj, Podgląd PDF link).

Status badges: `draft` → amber, `active` → green, `archived` → dim.

Group by produkt visually with row separators.

- [ ] **Step 4: Write mbr_edit.html**

Create `mbr/templates/technolog/mbr_edit.html`:

Two-tab editor:
- **Tab 1: Etapy** — renders `etapy_json` as editable list. Each etap: name input, textarea for instrukcja, checkbox "Sekcja lab", sekcja_lab input (if checked). JS to add/remove/reorder etapy. Hidden input `etapy_json` holds serialized JSON on form submit.
- **Tab 2: Parametry lab** — for each sekcja_lab defined in Tab 1, shows a table of pola: Kod, Tag, Label, Min, Max, Precision. Buttons to add/remove rows. Hidden input `parametry_lab` holds serialized JSON.

If `mbr.status != "draft"`, all inputs are disabled (read-only view).

Form POSTs to same URL. JS serializes the structured editor data into hidden JSON fields before submit.

- [ ] **Step 5: Test the editor flow**

Run: `cd /Users/tbk/Desktop/aa && python -m mbr.app`
1. Login as `technolog` / `tech123`
2. See 4 active MBR templates in list
3. Click "Klonuj" on K7 → creates K7 v2 (draft)
4. Click "Edytuj" on v2 → edit etapy/parametry
5. Save → changes persist
6. "Aktywuj" → v2 becomes active, v1 archived

- [ ] **Step 6: Commit**

```bash
git add mbr/models.py mbr/app.py mbr/templates/technolog/
git commit -m "feat(mbr): technolog panel — MBR list, editor, clone, activate"
```

---

## Task 4: Technolog Dashboard (Live + Historia)

**Files:**
- Modify: `mbr/models.py` — add EBR query functions
- Modify: `mbr/app.py` — add dashboard route
- Create: `mbr/templates/technolog/dashboard.html`

- [ ] **Step 1: Add EBR query functions to models.py**

```python
# ── EBR queries ──

def list_ebr_open(db: sqlite3.Connection) -> list[dict]:
    rows = db.execute("""
        SELECT e.*, m.produkt, m.wersja AS mbr_wersja,
               (SELECT MAX(w.dt_wpisu) FROM ebr_wyniki w WHERE w.ebr_id = e.ebr_id) AS last_entry,
               (SELECT COUNT(*) FROM ebr_wyniki w WHERE w.ebr_id = e.ebr_id AND w.w_limicie = 0) AS out_of_limit
        FROM ebr_batches e
        JOIN mbr_templates m ON e.mbr_id = m.mbr_id
        WHERE e.status = 'open'
        ORDER BY e.dt_start DESC
    """).fetchall()
    return [dict(r) for r in rows]


def list_ebr_completed(db: sqlite3.Connection, produkt: str = None, limit: int = 50) -> list[dict]:
    query = """
        SELECT e.*, m.produkt, m.wersja AS mbr_wersja,
               (SELECT COUNT(*) FROM ebr_wyniki w WHERE w.ebr_id = e.ebr_id AND w.w_limicie = 0) AS out_of_limit
        FROM ebr_batches e
        JOIN mbr_templates m ON e.mbr_id = m.mbr_id
        WHERE e.status = 'completed'
    """
    params = []
    if produkt:
        query += " AND m.produkt = ?"
        params.append(produkt)
    query += " ORDER BY e.dt_end DESC LIMIT ?"
    params.append(limit)
    rows = db.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def export_wyniki_csv(db: sqlite3.Connection, produkt: str = None) -> list[dict]:
    query = """
        SELECT e.batch_id, m.produkt, e.nr_partii, w.sekcja, w.kod_parametru, w.tag,
               w.wartosc, w.min_limit, w.max_limit, w.w_limicie, w.komentarz,
               w.is_manual, w.dt_wpisu, w.wpisal
        FROM ebr_wyniki w
        JOIN ebr_batches e ON w.ebr_id = e.ebr_id
        JOIN mbr_templates m ON e.mbr_id = m.mbr_id
        WHERE e.status = 'completed'
    """
    params = []
    if produkt:
        query += " AND m.produkt = ?"
        params.append(produkt)
    query += " ORDER BY e.batch_id, w.sekcja, w.kod_parametru"
    rows = db.execute(query, params).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 2: Add dashboard + export routes to app.py**

```python
import csv
import io
from flask import Response
from models import list_ebr_open, list_ebr_completed, export_wyniki_csv

@app.route("/technolog/dashboard")
@role_required("technolog")
def tech_dashboard():
    db = get_db()
    open_batches = list_ebr_open(db)
    completed = list_ebr_completed(db, request.args.get("produkt"))
    db.close()
    return render_template("technolog/dashboard.html", open_batches=open_batches, completed=completed)


@app.route("/technolog/export")
@role_required("technolog")
def tech_export():
    db = get_db()
    rows = export_wyniki_csv(db, request.args.get("produkt"))
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
```

- [ ] **Step 3: Write dashboard.html**

Create `mbr/templates/technolog/dashboard.html`:

Extends `base.html`. Two sections:

**Live — Aktywne szarże:** Table from `open_batches`: Nr partii | Produkt | Amidator | Start | Status | Ostatni wpis. Status colored: green (open, has entries), yellow (open, no entries), red (has out_of_limit > 0).

**Historia — Zamknięte szarże:** Table from `completed`: Nr partii | Produkt | Data zakończenia | Wyniki w/poza limitem | PDF link. Filter dropdown by produkt at top. "Eksport CSV" button links to `/technolog/export?produkt=...`.

- [ ] **Step 4: Test dashboard**

Run app, login as technolog, navigate to dashboard.
Expected: empty tables (no EBR data yet — will be populated after Task 5).

- [ ] **Step 5: Commit**

```bash
git add mbr/models.py mbr/app.py mbr/templates/technolog/dashboard.html
git commit -m "feat(mbr): technolog dashboard — live batches, history, CSV export"
```

---

## Task 5: Laborant — batch list + new batch + fast-entry form

**Files:**
- Modify: `mbr/models.py` — add EBR create + wyniki CRUD
- Modify: `mbr/app.py` — add laborant routes
- Create: `mbr/templates/laborant/szarze_list.html`
- Create: `mbr/templates/laborant/fast_entry.html`
- Create: `mbr/static/calculator.js`

- [ ] **Step 1: Add EBR + wyniki CRUD to models.py**

```python
# ── EBR CRUD ──

PRODUCTS = ["Chegina_K7", "Chegina_K40GL", "Chegina_K40GLO", "Chegina_K40GLOL"]


def create_ebr(db: sqlite3.Connection, produkt: str, nr_partii: str,
               nr_amidatora: str, nr_mieszalnika: str, wielkosc_kg: float, operator: str) -> int:
    mbr = get_active_mbr(db, produkt)
    if not mbr:
        raise ValueError(f"Brak aktywnego MBR dla {produkt}")
    batch_id = f"{produkt.replace(' ', '_')}__{nr_partii.replace('/', '_')}"
    now = datetime.now().isoformat(timespec="seconds")
    cursor = db.execute(
        """INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, nr_amidatora, nr_mieszalnika,
           wielkosc_szarzy_kg, dt_start, operator)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (mbr["mbr_id"], batch_id, nr_partii, nr_amidatora, nr_mieszalnika, wielkosc_kg, now, operator),
    )
    db.commit()
    return cursor.lastrowid


def get_ebr(db: sqlite3.Connection, ebr_id: int) -> dict | None:
    row = db.execute("""
        SELECT e.*, m.produkt, m.etapy_json, m.parametry_lab
        FROM ebr_batches e
        JOIN mbr_templates m ON e.mbr_id = m.mbr_id
        WHERE e.ebr_id = ?
    """, (ebr_id,)).fetchone()
    return dict(row) if row else None


def get_ebr_wyniki(db: sqlite3.Connection, ebr_id: int) -> dict[str, dict]:
    """Returns {sekcja: {kod_parametru: row_dict}}."""
    rows = db.execute("SELECT * FROM ebr_wyniki WHERE ebr_id = ?", (ebr_id,)).fetchall()
    result = {}
    for r in rows:
        d = dict(r)
        result.setdefault(d["sekcja"], {})[d["kod_parametru"]] = d
    return result


def save_wyniki(db: sqlite3.Connection, ebr_id: int, sekcja: str, values: dict, user: str):
    """Save lab results for a section. values = {kod_parametru: {wartosc, komentarz}}."""
    ebr = get_ebr(db, ebr_id)
    if not ebr:
        raise ValueError("EBR not found")
    parametry = json.loads(ebr["parametry_lab"])
    sekcja_def = parametry.get(sekcja)
    if not sekcja_def:
        raise ValueError(f"Sekcja {sekcja} not in MBR")

    now = datetime.now().isoformat(timespec="seconds")
    pola_by_kod = {p["kod"]: p for p in sekcja_def["pola"]}

    for kod, val_data in values.items():
        pole = pola_by_kod.get(kod)
        if not pole:
            continue
        wartosc = val_data.get("wartosc")
        if wartosc is None or wartosc == "":
            continue
        wartosc = float(wartosc)
        komentarz = val_data.get("komentarz", "")
        w_limicie = 1 if (pole["min"] <= wartosc <= pole["max"]) else 0

        db.execute("""
            INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc, min_limit, max_limit,
                                    w_limicie, komentarz, is_manual, dt_wpisu, wpisal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(ebr_id, sekcja, kod_parametru)
            DO UPDATE SET wartosc=?, min_limit=?, max_limit=?, w_limicie=?, komentarz=?, dt_wpisu=?, wpisal=?
        """, (
            ebr_id, sekcja, kod, pole["tag"], wartosc, pole["min"], pole["max"],
            w_limicie, komentarz, now, user,
            wartosc, pole["min"], pole["max"], w_limicie, komentarz, now, user,
        ))
    db.commit()


def complete_ebr(db: sqlite3.Connection, ebr_id: int):
    now = datetime.now().isoformat(timespec="seconds")
    db.execute("UPDATE ebr_batches SET status = 'completed', dt_end = ? WHERE ebr_id = ?", (now, ebr_id))
    db.commit()
```

- [ ] **Step 2: Add v4 sync function to models.py**

```python
# ── V4 sync ──

def sync_ebr_to_v4(db: sqlite3.Connection, ebr_id: int):
    """Sync EBR wyniki to v4 events table + batch ak_ fields on completion."""
    ebr = get_ebr(db, ebr_id)
    if not ebr:
        return
    wyniki = get_ebr_wyniki(db, ebr_id)
    batch_id = ebr["batch_id"]

    SEKCJA_TO_STAGE = {
        "przed_standaryzacja": "standaryzacja",
        "analiza_koncowa": "analiza_koncowa",
    }

    # Delete old digital events for this batch
    db.execute("DELETE FROM events WHERE batch_id = ? AND _source = 'digital'", (batch_id,))

    for sekcja, params in wyniki.items():
        stage = SEKCJA_TO_STAGE.get(sekcja, sekcja)
        # Build one event row with all params for this section
        event = {
            "batch_id": batch_id,
            "equipment_id": ebr["nr_amidatora"],
            "dt": max(p["dt_wpisu"] for p in params.values()),
            "stage": stage,
            "event_type": "analiza",
            "seq": 1,
            "_source": "digital",
            "_ts_precision": "second",
        }
        # Map tags to event columns
        TAG_TO_COL = {
            "ph": "ph", "ph_10proc": "ph_10proc", "nd20": "nd20",
            "procent_aa": "procent_aa", "procent_sm": "procent_sm",
            "procent_sa": "procent_sa", "procent_nacl": "procent_nacl",
            "procent_so3": "procent_so3", "procent_h2o2": "procent_h2o2",
            "lk": "lk", "barwa_fau": "barwa_fau", "barwa_hz": "barwa_hz",
        }
        for p in params.values():
            col = TAG_TO_COL.get(p["tag"])
            if col:
                event[col] = p["wartosc"]

        cols = list(event.keys())
        placeholders = ", ".join(["?"] * len(cols))
        db.execute(
            f"INSERT INTO events ({', '.join(cols)}) VALUES ({placeholders})",
            [event[c] for c in cols],
        )

    # If completed, update batch ak_ fields
    if ebr["status"] == "completed" and "analiza_koncowa" in wyniki:
        ak = wyniki["analiza_koncowa"]
        ak_map = {
            "ph": "ak_ph", "ph_10proc": "ak_ph_10proc", "nd20": "ak_nd20",
            "procent_sm": "ak_procent_sm", "procent_sa": "ak_procent_sa",
            "procent_nacl": "ak_procent_nacl", "procent_aa": "ak_procent_aa",
            "procent_so3": "ak_procent_so3", "procent_h2o2": "ak_procent_h2o2",
            "barwa_fau": "ak_barwa_fau", "barwa_hz": "ak_barwa_hz",
            "lk": "ak_le_liczba_kwasowa",
        }
        sets = []
        vals = []
        for param in ak.values():
            ak_col = ak_map.get(param["tag"])
            if ak_col:
                sets.append(f"{ak_col} = ?")
                vals.append(param["wartosc"])
        if sets:
            # Ensure batch row exists
            existing = db.execute("SELECT 1 FROM batch WHERE batch_id = ?", (batch_id,)).fetchone()
            if existing:
                vals.append(batch_id)
                db.execute(f"UPDATE batch SET {', '.join(sets)} WHERE batch_id = ?", vals)
            else:
                db.execute(
                    """INSERT INTO batch (batch_id, produkt, nr_partii, equipment_id, nr_mieszalnika,
                       dt_start, dt_end, wielkosc_kg, _source, _schema_version, _verified)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'digital', '4.0', 1)""",
                    (batch_id, ebr["produkt"], ebr["nr_partii"], ebr["nr_amidatora"],
                     ebr["nr_mieszalnika"], ebr["dt_start"], ebr["dt_end"], ebr["wielkosc_szarzy_kg"]),
                )
                vals.append(batch_id)
                db.execute(f"UPDATE batch SET {', '.join(sets)} WHERE batch_id = ?", vals)
    db.commit()
```

- [ ] **Step 3: Add laborant routes to app.py**

```python
from models import (get_db, init_mbr_tables, verify_user, list_mbr, get_mbr, save_mbr,
                     activate_mbr, clone_mbr, list_ebr_open, list_ebr_completed,
                     export_wyniki_csv, create_ebr, get_ebr, get_ebr_wyniki, save_wyniki,
                     complete_ebr, sync_ebr_to_v4, get_active_mbr, PRODUCTS)

@app.route("/laborant/szarze")
@login_required
def szarze_list():
    db = get_db()
    open_batches = list_ebr_open(db)
    db.close()
    return render_template("laborant/szarze_list.html", batches=open_batches, products=PRODUCTS)


@app.route("/laborant/szarze/new", methods=["POST"])
@login_required
def szarze_new():
    db = get_db()
    ebr_id = create_ebr(
        db,
        produkt=request.form["produkt"],
        nr_partii=request.form["nr_partii"],
        nr_amidatora=request.form["nr_amidatora"],
        nr_mieszalnika=request.form["nr_mieszalnika"],
        wielkosc_kg=float(request.form["wielkosc_kg"]),
        operator=session["user"]["login"],
    )
    db.close()
    return redirect(url_for("fast_entry", ebr_id=ebr_id))


@app.route("/laborant/ebr/<int:ebr_id>")
@login_required
def fast_entry(ebr_id):
    db = get_db()
    ebr = get_ebr(db, ebr_id)
    if not ebr:
        abort(404)
    wyniki = get_ebr_wyniki(db, ebr_id)
    db.close()
    etapy = json.loads(ebr["etapy_json"])
    parametry = json.loads(ebr["parametry_lab"])
    return render_template("laborant/fast_entry.html", ebr=ebr, etapy=etapy, parametry=parametry, wyniki=wyniki)


@app.route("/laborant/ebr/<int:ebr_id>/save", methods=["POST"])
@login_required
def save_entry(ebr_id):
    db = get_db()
    data = request.get_json()
    sekcja = data["sekcja"]
    values = data["values"]  # {kod: {wartosc, komentarz}}
    save_wyniki(db, ebr_id, sekcja, values, session["user"]["login"])
    sync_ebr_to_v4(db, ebr_id)
    db.close()
    return jsonify({"ok": True})


@app.route("/laborant/ebr/<int:ebr_id>/complete", methods=["POST"])
@login_required
def complete_entry(ebr_id):
    db = get_db()
    complete_ebr(db, ebr_id)
    sync_ebr_to_v4(db, ebr_id)
    db.close()
    return redirect(url_for("szarze_list"))
```

- [ ] **Step 4: Write szarze_list.html**

Create `mbr/templates/laborant/szarze_list.html`:

Extends `base.html`. Sidebar with list of open batches (from `batches`). Each item shows: batch_id, produkt, nr_amidatora, progress dots. Button `+ Nowa szarża` opens a modal form (produkt dropdown, nr_partii, nr_amidatora, nr_mieszalnika, wielkość kg) that POSTs to `/laborant/szarze/new`.

Click on batch → navigates to `/laborant/ebr/<ebr_id>`.

- [ ] **Step 5: Write fast_entry.html**

Create `mbr/templates/laborant/fast_entry.html`:

This is the main lab entry form. Extends `base.html` with custom sidebar and content.

**Sidebar:** Batch dropdown + meta + 7 etapy from `etapy` list. 5 locked (class `locked` — greyed, lock icon, not clickable). 2 unlocked: items with `sekcja_lab` key — clickable, show active/done status based on `wyniki`.

**Main content:** Two sections rendered from `parametry`:

For each sekcja in `parametry`:
- Section card with header (icon, title, badge: "Wypełnione" green / "Do uzupełnienia" amber)
- Grid of fields generated from `parametry[sekcja]["pola"]`:
  - Each field: `<label>{{ pole.label }} <span class="norm">{{ pole.min }}–{{ pole.max }}</span></label>`
  - `<input>` with existing value from `wyniki[sekcja][pole.kod].wartosc` if exists
  - Class `ok` if w_limicie, class `err` (red border) if not
  - Fields with tag in `[procent_sa, procent_nacl, procent_aa, procent_so3, procent_h2o2, lk]` get class `titr` and onclick to open calculator
- Komentarz textarea (hidden by default, expands on out-of-limit)

**Right panel (280px):**
- Two tabs: Referencje | Kalkulator
- Referencje: normy from MBR (list of param → min–max)
- Kalkulator: loaded from `calculator.js`

**Footer:** "Zapisz sekcję" button (JS: serialize form → POST JSON to `/laborant/ebr/<id>/save`), "Zatwierdź kartę" button (POST to `/laborant/ebr/<id>/complete`).

JS on save:
```javascript
async function saveSection(sekcja) {
    const fields = document.querySelectorAll(`[data-sekcja="${sekcja}"] input[data-kod]`);
    const values = {};
    fields.forEach(f => {
        if (f.value) {
            const komentarz = document.querySelector(`[data-sekcja="${sekcja}"] [data-komentarz="${f.dataset.kod}"]`);
            values[f.dataset.kod] = {
                wartosc: f.value,
                komentarz: komentarz ? komentarz.value : ""
            };
        }
    });
    const resp = await fetch(`/laborant/ebr/${ebrId}/save`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({sekcja, values})
    });
    if (resp.ok) location.reload();
}
```

- [ ] **Step 6: Write calculator.js**

Create `mbr/static/calculator.js`. Extract from `ui_concepts/selected/koncowa_right_panel_calc.html` lines 275-350:

```javascript
const CALC_METHODS = {
    procent_sa:   { name: '%SA',   method: 'Dwufazowa Epton',      formula: '% = (V × C × M) / (m × 10)', factor: 3.261 },
    procent_nacl: { name: '%NaCl', method: 'Argentometryczna Mohr', formula: '% = (V × 0.00585 × 100) / m', factor: 0.585 },
    procent_aa:   { name: '%AA',   method: 'Alkacymetria',          formula: '% = (V × C × M) / (m × 10)', factor: 3.015 },
    procent_so3:  { name: '%SO3',  method: 'Jodometryczna',         formula: '% = (V × 0.004 × 100) / m',  factor: 0.4 },
    procent_h2o2: { name: '%H2O2', method: 'Manganometryczna',      formula: '% = (V × 0.0017 × 100) / m', factor: 0.17 },
    lk:           { name: 'LK=',   method: 'Alkacymetria KOH',     formula: 'LK = (V × C × 56.1) / m',    factor: 5.61 },
};

let currentCalcTag = null;

function openCalc(tag) {
    currentCalcTag = tag;
    const m = CALC_METHODS[tag];
    if (!m) return;
    document.getElementById('calc-param-name').textContent = m.name;
    document.getElementById('calc-method-name').textContent = 'Metoda: ' + m.method;
    document.getElementById('calc-formula').textContent = m.formula;
    document.getElementById('calc-accept-btn').textContent = 'Zatwierdź wynik → ' + m.name;
    // Reset sample inputs
    document.querySelectorAll('.calc-sample input').forEach(i => i.value = '');
    document.querySelectorAll('.cs-result-tag').forEach(t => t.textContent = '—');
    document.getElementById('calc-avg').textContent = '—';
    document.getElementById('calc-conv').textContent = '';
    // Show calc tab
    showRightPanel('calc');
    // Highlight active field
    document.querySelectorAll('.ff.titr').forEach(f => f.classList.remove('active-calc'));
    const active = document.querySelector(`.ff.titr[data-tag="${tag}"]`);
    if (active) active.classList.add('active-calc');
}

function recalc() {
    if (!currentCalcTag || !CALC_METHODS[currentCalcTag]) return;
    const factor = CALC_METHODS[currentCalcTag].factor;
    const samples = document.querySelectorAll('.calc-sample');
    const results = [];
    samples.forEach((s, i) => {
        const inputs = s.querySelectorAll('input');
        const mass = parseFloat(inputs[0].value);
        const vol = parseFloat(inputs[1].value);
        const tag = s.querySelector('.cs-result-tag');
        if (mass > 0 && vol > 0) {
            const r = (vol * factor / mass);
            tag.textContent = r.toFixed(2) + '%';
            results.push(r);
        } else {
            tag.textContent = '—';
        }
    });
    const avgEl = document.getElementById('calc-avg');
    const convEl = document.getElementById('calc-conv');
    if (results.length >= 2) {
        const avg = results.reduce((a, b) => a + b, 0) / results.length;
        const delta = Math.abs(results[0] - results[1]);
        avgEl.textContent = avg.toFixed(2);
        convEl.textContent = `Δ = ${delta.toFixed(2)}% — ${delta < 0.5 ? 'zbieżne' : 'BRAK ZBIEŻNOŚCI'}`;
        convEl.className = 'calc-convergence ' + (delta < 0.5 ? 'ok' : '');
    } else if (results.length === 1) {
        avgEl.textContent = results[0].toFixed(2);
        convEl.textContent = 'Jedna próbka';
        convEl.className = 'calc-convergence';
    } else {
        avgEl.textContent = '—';
        convEl.textContent = '';
    }
}

function acceptCalc() {
    const val = document.getElementById('calc-avg').textContent;
    if (val !== '—' && currentCalcTag) {
        const field = document.querySelector(`input[data-kod="${currentCalcTag}"]`);
        if (field) {
            field.value = val;
            field.classList.add('calc');
            field.dispatchEvent(new Event('input'));
        }
    }
}

function showRightPanel(view) {
    document.querySelectorAll('.rp-view').forEach(v => v.classList.remove('active'));
    document.querySelectorAll('.rp-tab').forEach(t => t.classList.remove('active'));
    document.getElementById('view-' + view).classList.add('active');
    document.getElementById('tab-' + view).classList.add('active');
}
```

- [ ] **Step 7: Test full lab workflow**

Run: `cd /Users/tbk/Desktop/aa && python -m mbr.app`

1. Login as `laborant` / `lab123`
2. Click "+ Nowa szarża" → fill: Chegina_K7, 99/2026, amidator 8, mieszalnik 25, 5000 kg → Start
3. See fast-entry form with 7 etapy (5 locked, 2 unlocked)
4. Fill "Analiza przed standaryzacją" fields → "Zapisz sekcję"
5. Fill "Analiza końcowa" fields → use calculator for %SA → "Zapisz sekcję"
6. Click "Zatwierdź kartę" → batch moves to completed

Verify v4 sync:
Run: `sqlite3 data/batch_db_v4.sqlite "SELECT batch_id, stage, event_type, _source FROM events WHERE _source = 'digital'"`
Expected: rows with `_source = "digital"`

- [ ] **Step 8: Commit**

```bash
git add mbr/models.py mbr/app.py mbr/templates/laborant/ mbr/static/calculator.js
git commit -m "feat(mbr): laborant panel — batch list, fast-entry form, calculator, v4 sync"
```

---

## Task 6: PDF Generation

**Files:**
- Create: `mbr/pdf_gen.py`
- Create: `mbr/templates/pdf/karta_base.html`
- Modify: `mbr/app.py` — add PDF route

- [ ] **Step 1: Write pdf_gen.py**

```python
"""Generate batch card PDF from MBR template + EBR data."""
import json
from pathlib import Path
from flask import render_template
from weasyprint import HTML


def generate_pdf(mbr: dict, ebr: dict | None = None, wyniki: dict | None = None) -> bytes:
    """Generate PDF bytes for a batch card.

    mbr: dict from mbr_templates row (with etapy_json, parametry_lab as strings)
    ebr: dict from ebr_batches row (optional — if None, generates empty card from MBR)
    wyniki: dict {sekcja: {kod: row_dict}} (optional)
    """
    etapy = json.loads(mbr["etapy_json"])
    parametry = json.loads(mbr["parametry_lab"])

    html = render_template(
        "pdf/karta_base.html",
        mbr=mbr,
        ebr=ebr,
        wyniki=wyniki or {},
        etapy=etapy,
        parametry=parametry,
    )
    return HTML(string=html).write_pdf()
```

- [ ] **Step 2: Write karta_base.html**

Create `mbr/templates/pdf/karta_base.html`:

A4 PDF template styled to match the physical batch cards from `data/done/`. Use `@page` CSS for A4 sizing, margins, page breaks.

Structure (matching scanned cards):

```html
<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<style>
@page { size: A4; margin: 15mm 12mm; }
body { font-family: 'Times New Roman', serif; font-size: 10pt; color: black; }
table { width: 100%; border-collapse: collapse; margin-bottom: 8pt; }
th, td { border: 1px solid black; padding: 3pt 5pt; text-align: left; font-size: 9pt; }
th { background: #f0f0f0; font-weight: bold; }
.header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10pt; border-bottom: 2px solid black; padding-bottom: 6pt; }
.logo { font-weight: bold; font-size: 14pt; }
.meta-box { border: 1px solid black; padding: 4pt 8pt; font-size: 8pt; text-align: right; }
h1 { text-align: center; font-size: 14pt; margin: 8pt 0; }
h2 { font-size: 11pt; margin: 10pt 0 4pt; text-transform: uppercase; }
.page-break { page-break-before: always; }
.val { font-family: 'Courier New', monospace; font-weight: bold; }
.empty { color: #999; }
.out-of-limit { color: red; font-weight: bold; }
</style>
</head>
<body>

<!-- PAGE 1: Header + Surowce + Standaryzowanie -->
<div class="header">
  <div class="logo">CHEMCO</div>
  <div style="text-align:center; flex:1">
    <h1>KARTA SZARŻOWA nr.....</h1>
    <div style="font-size:14pt; font-weight:bold">{{ mbr.produkt }}</div>
  </div>
  <div class="meta-box">
    MBR v{{ mbr.wersja }}<br>
    {% if ebr %}Szarża: {{ ebr.nr_partii }}{% endif %}
  </div>
</div>

<table>
  <tr>
    <td>Nr aparatu: <span class="val">{{ ebr.nr_amidatora if ebr else '........' }}</span></td>
    <td>Nr partii: <span class="val">{{ ebr.nr_partii if ebr else '........' }}</span></td>
  </tr>
  <tr>
    <td>Data rozpoczęcia: <span class="val">{{ ebr.dt_start[:10] if ebr else '........' }}</span></td>
    <td>Data zakończenia: <span class="val">{{ ebr.dt_end[:10] if ebr and ebr.dt_end else '........' }}</span></td>
  </tr>
  <tr>
    <td colspan="2">Wielkość szarży: <span class="val">{{ ebr.wielkosc_szarzy_kg if ebr else '........' }}</span> kg</td>
  </tr>
</table>

<h2>Załadunek surowców</h2>
<table>
  <tr><th>Lp.</th><th>Nazwa surowca</th><th>Ilość recepturowa</th><th>Ilość załadowana</th><th>Nr partii</th><th>Pulpa</th></tr>
  {% for i in range(8) %}<tr><td>{{ i+1 }}</td><td></td><td></td><td></td><td></td><td></td></tr>{% endfor %}
</table>

<h2>Standaryzowanie produktu</h2>
<table>
  <tr><th>Dodatek</th><th>Ilość [kg]</th><th>Data i godzina</th><th>Nr partii</th><th>Pulpa</th></tr>
  {% for i in range(6) %}<tr><td></td><td></td><td></td><td></td><td></td></tr>{% endfor %}
</table>

<!-- PAGE 2-3: Przebieg procesu -->
<div class="page-break"></div>
<h2>Przebieg i parametry procesu</h2>
<table>
  <tr><th>Operacja</th><th>Data</th><th>Temperatura</th><th>Próżnia</th><th>Pulpa</th><th>Uwagi</th></tr>
  {% for etap in etapy %}
  {% if etap.read_only %}
  <tr><td colspan="6" style="font-weight:bold; background:#f0f0f0">{{ etap.nr }}. {{ etap.nazwa }}</td></tr>
  <tr><td colspan="6" style="font-size:8pt; color:#666">{{ etap.instrukcja }}</td></tr>
  {% for i in range(4) %}<tr><td></td><td></td><td></td><td></td><td></td><td></td></tr>{% endfor %}
  {% endif %}
  {% endfor %}
</table>

<!-- PAGE 4: Analizy + Przepompowanie -->
<div class="page-break"></div>

{% for sekcja_key, sekcja_def in parametry.items() %}
<h2>{{ sekcja_def.label }}</h2>
<table>
  <tr><th>Parametr</th><th>Wynik</th><th>Norma</th></tr>
  {% for pole in sekcja_def.pola %}
  <tr>
    <td>{{ pole.label }}</td>
    <td class="val {% if wyniki.get(sekcja_key, {}).get(pole.kod) and not wyniki[sekcja_key][pole.kod].w_limicie %}out-of-limit{% endif %}">
      {% if wyniki.get(sekcja_key, {}).get(pole.kod) %}
        {{ wyniki[sekcja_key][pole.kod].wartosc }}
      {% else %}
        <span class="empty">—</span>
      {% endif %}
    </td>
    <td>{{ pole.min }} – {{ pole.max }}</td>
  </tr>
  {% endfor %}
</table>
{% endfor %}

<h2>Przepompowanie produktu</h2>
<table>
  <tr><td>Rozpoczęcie: ........</td><td>Zakończenie: ........</td></tr>
  <tr><td>Temperatura max: ........°C</td><td>Zbiornik: ........</td></tr>
  <tr><td>Wsk. od: ........</td><td>Wsk. do: ........</td></tr>
</table>

<div style="margin-top: 30pt">
  <table style="border:none">
    <tr style="border:none"><td style="border:none; width:33%">Operator: ................</td><td style="border:none; width:33%">Laborant: ................</td><td style="border:none; width:33%">Technolog: ................</td></tr>
  </table>
</div>

</body>
</html>
```

- [ ] **Step 3: Add PDF routes to app.py**

```python
from flask import Response
from pdf_gen import generate_pdf

@app.route("/pdf/mbr/<int:mbr_id>")
@login_required
def pdf_mbr(mbr_id):
    """Empty card from MBR template (for printing)."""
    db = get_db()
    mbr = get_mbr(db, mbr_id)
    db.close()
    if not mbr:
        abort(404)
    pdf_bytes = generate_pdf(mbr)
    return Response(pdf_bytes, mimetype="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=MBR_{mbr['produkt']}_v{mbr['wersja']}.pdf"})


@app.route("/pdf/ebr/<int:ebr_id>")
@login_required
def pdf_ebr(ebr_id):
    """Filled card from EBR + MBR."""
    db = get_db()
    ebr = get_ebr(db, ebr_id)
    if not ebr:
        db.close()
        abort(404)
    mbr = get_mbr(db, ebr["mbr_id"])
    wyniki = get_ebr_wyniki(db, ebr_id)
    db.close()
    pdf_bytes = generate_pdf(mbr, ebr, wyniki)
    return Response(pdf_bytes, mimetype="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=EBR_{ebr['batch_id']}.pdf"})
```

- [ ] **Step 4: Test PDF generation**

Run: `cd /Users/tbk/Desktop/aa && python -m mbr.app`

1. Login as technolog → MBR list → "Podgląd PDF" on K7 → should download/display A4 PDF with empty batch card
2. Login as laborant → open a completed batch → "PDF" → should show filled card with lab results

Compare visual layout with scanned card from `data/done/Chegina_K40GL/1_2026/strona_001.jpg` and `strona_004.jpg`.

- [ ] **Step 5: Commit**

```bash
git add mbr/pdf_gen.py mbr/templates/pdf/karta_base.html mbr/app.py
git commit -m "feat(mbr): PDF generation — empty MBR cards + filled EBR cards"
```

---

## Task 7: Integration test — full workflow

**Files:**
- Create: `mbr/test_workflow.py`

- [ ] **Step 1: Write integration test**

```python
"""End-to-end test: seed → create EBR → enter results → complete → verify v4 sync."""
import sqlite3
import json
from pathlib import Path
from models import get_db, init_mbr_tables, create_user, get_active_mbr, create_ebr, save_wyniki, complete_ebr, sync_ebr_to_v4, get_ebr, get_ebr_wyniki

def test_full_workflow():
    db = get_db()
    init_mbr_tables(db)

    # Ensure seed data exists
    count = db.execute("SELECT COUNT(*) FROM mbr_templates").fetchone()[0]
    assert count >= 4, f"Expected 4+ MBR templates, got {count}. Run seed_mbr.py first."

    # 1. Create EBR
    ebr_id = create_ebr(db, "Chegina_K7", "99/2026", "8", "25", 5000.0, "test")
    ebr = get_ebr(db, ebr_id)
    assert ebr is not None
    assert ebr["batch_id"] == "Chegina_K7__99_2026"
    assert ebr["status"] == "open"
    print(f"  [OK] EBR created: {ebr['batch_id']}")

    # 2. Save przed_standaryzacja results
    save_wyniki(db, ebr_id, "przed_standaryzacja", {
        "ph_10proc": {"wartosc": 5.5, "komentarz": ""},
        "nd20": {"wartosc": 1.4050, "komentarz": ""},
        "procent_so3": {"wartosc": 0.008, "komentarz": ""},
    }, "test_laborant")
    wyniki = get_ebr_wyniki(db, ebr_id)
    assert "przed_standaryzacja" in wyniki
    assert wyniki["przed_standaryzacja"]["ph_10proc"]["w_limicie"] == 1
    print("  [OK] przed_standaryzacja saved, limits checked")

    # 3. Save analiza_koncowa results (one out of limit)
    save_wyniki(db, ebr_id, "analiza_koncowa", {
        "ph_10proc": {"wartosc": 5.2, "komentarz": ""},
        "nd20": {"wartosc": 1.4050, "komentarz": ""},
        "procent_sm": {"wartosc": 45.0, "komentarz": ""},
        "procent_sa": {"wartosc": 38.5, "komentarz": ""},
        "procent_nacl": {"wartosc": 5.8, "komentarz": ""},
        "procent_aa": {"wartosc": 0.12, "komentarz": ""},
        "procent_so3": {"wartosc": 0.008, "komentarz": ""},
        "procent_h2o2": {"wartosc": 0.003, "komentarz": ""},
        "le_liczba_kwasowa": {"wartosc": 3.4, "komentarz": ""},
    }, "test_laborant")
    wyniki = get_ebr_wyniki(db, ebr_id)
    assert "analiza_koncowa" in wyniki
    print("  [OK] analiza_koncowa saved")

    # 4. Complete + sync
    complete_ebr(db, ebr_id)
    sync_ebr_to_v4(db, ebr_id)

    # 5. Verify v4 events
    events = db.execute(
        "SELECT * FROM events WHERE batch_id = 'Chegina_K7__99_2026' AND _source = 'digital'"
    ).fetchall()
    assert len(events) >= 2, f"Expected 2+ events, got {len(events)}"
    print(f"  [OK] v4 events synced: {len(events)} rows")

    # 6. Verify v4 batch ak_ fields
    batch = db.execute("SELECT * FROM batch WHERE batch_id = 'Chegina_K7__99_2026'").fetchone()
    assert batch is not None
    assert batch["ak_procent_sa"] == 38.5
    assert batch["_source"] == "digital"
    print(f"  [OK] v4 batch synced: ak_procent_sa = {batch['ak_procent_sa']}")

    # Cleanup
    db.execute("DELETE FROM ebr_wyniki WHERE ebr_id = ?", (ebr_id,))
    db.execute("DELETE FROM ebr_batches WHERE ebr_id = ?", (ebr_id,))
    db.execute("DELETE FROM events WHERE batch_id = 'Chegina_K7__99_2026' AND _source = 'digital'")
    db.execute("DELETE FROM batch WHERE batch_id = 'Chegina_K7__99_2026'")
    db.commit()
    db.close()
    print("\nAll tests passed!")


if __name__ == "__main__":
    test_full_workflow()
```

- [ ] **Step 2: Run integration test**

Run: `cd /Users/tbk/Desktop/aa && python -m mbr.test_workflow`
Expected: all assertions pass, prints "All tests passed!"

- [ ] **Step 3: Commit**

```bash
git add mbr/test_workflow.py
git commit -m "test(mbr): end-to-end workflow test — EBR create, lab entry, v4 sync"
```

---

## Task 8: Final polish + manual smoke test

**Files:**
- Modify: `mbr/app.py` — add PDF links to templates
- Review all templates for missing links

- [ ] **Step 1: Add PDF links everywhere**

In `mbr/templates/technolog/mbr_list.html`: "Podgląd PDF" button links to `/pdf/mbr/{{ t.mbr_id }}`

In `mbr/templates/technolog/dashboard.html`: per-batch PDF link to `/pdf/ebr/{{ b.ebr_id }}`

In `mbr/templates/laborant/fast_entry.html`: "PDF" button for completed batches to `/pdf/ebr/{{ ebr.ebr_id }}`

- [ ] **Step 2: Full manual smoke test**

Run: `cd /Users/tbk/Desktop/aa && python -m mbr.app`

**Technolog flow:**
1. Login `technolog` / `tech123`
2. See 4 MBR templates in list
3. Clone K7 → get K7 v2 (draft)
4. Edit v2: change pH limit → save
5. Activate v2 → v1 archived
6. Podgląd PDF → empty card renders
7. Dashboard → see open/completed batches (if any)
8. Export CSV → downloads file

**Laborant flow:**
1. Login `laborant` / `lab123`
2. New batch: K7, 100/2026, amidator 8, mieszalnik 25, 5000 kg
3. Fill "Przed standaryzacją": pH=5.5, nd20=1.405, SO3=0.008, FAU=50 → Save
4. Fill "Analiza końcowa": all fields → use calculator for %SA → Save
5. Enter one value out of limit → see red border + komentarz expands
6. Zatwierdź kartę → batch completed
7. PDF → shows filled card

- [ ] **Step 3: Commit**

```bash
git add -A mbr/
git commit -m "feat(mbr): final polish — PDF links, complete MBR/EBR system"
```
