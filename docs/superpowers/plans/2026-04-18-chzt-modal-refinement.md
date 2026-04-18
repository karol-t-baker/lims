# ChZT Modal Refinement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Przenieść ChZT modal z zapisu do plików JSON na SQLite z autosave'em per wiersz (debounce 400ms), dodać podstronę historii i poprawić UX wpisywania.

**Architecture:** Nowy blueprint `mbr/chzt/` (wzorem `mbr.paliwo`, `mbr.certs`). Dwie tabele: `chzt_sesje` (jedna per data) + `chzt_pomiary` (1..N wierszy per sesja). Każde pole edytowane w UI wywołuje `PUT /api/chzt/pomiar/<id>` (debounce 400ms) — endpoint oblicza `srednia` i loguje audit. Historia pod `/chzt/historia`. DB jest SSOT — brak `localStorage`, brak JSON files dla nowych wpisów.

**Tech Stack:** Flask + raw sqlite3 (zgodnie z `CLAUDE.md`), Jinja2 templates, vanilla JS (wzorem `mbr/static/calculator.js`), pytest + in-memory sqlite fixtures.

**Spec:** `docs/superpowers/specs/2026-04-18-chzt-modal-refinement-design.md`

---

## File Structure

### Nowe pliki

| Plik | Odpowiedzialność |
|---|---|
| `mbr/chzt/__init__.py` | Blueprint definition (`chzt_bp`) |
| `mbr/chzt/models.py` | `init_chzt_tables()` + helpery SQL (session, pomiary, finalize, history) |
| `mbr/chzt/routes.py` | Flask handlers — strona historii + wszystkie endpointy API |
| `mbr/chzt/templates/chzt_modal.html` | Markup modala (include'owany z `narzedzia.html`) |
| `mbr/chzt/templates/chzt_historia.html` | Podstrona historii z paginacją |
| `mbr/chzt/static/chzt.js` | JS modala + historii (autosave, Enter-nav, expand/collapse) |
| `mbr/chzt/static/chzt.css` | Style modala + karty historii |
| `tests/test_chzt.py` | Testy modeli i endpointów |

### Modyfikowane

| Plik | Zmiana |
|---|---|
| `mbr/app.py` | Rejestracja `chzt_bp` + `init_chzt_tables()` w `create_app()` |
| `mbr/templates/technolog/narzedzia.html` | Usunąć inline markup/JS/CSS modala → `{% include "chzt/chzt_modal.html" %}` + link do `chzt.js`/`chzt.css`; dodać kartę "Historia ChZT" |
| `mbr/registry/routes.py` | Usunąć legacy endpoint `POST /api/chzt/save` |

### Nie ruszamy

- `data/chzt/*.json` — archiwum, zostaje na dysku
- `mbr/shared/audit.py` — używamy `log_event`, `diff_fields`, `query_audit_history_for_entity` jak są

---

## Konwencje projektu (przypomnienie dla implementatora)

- **Raw sqlite3**, no ORM. Query używają `?` placeholders. Caller commituje transakcję (helpery same nie commitują; patrz `mbr/certs/models.py`).
- **Blueprint pattern:** `__init__.py` → `Blueprint(...)` + `from mbr.chzt import routes`.
- **Role w `@role_required`:** `"lab"`, `"kj"`, `"cert"`, `"technolog"`, `"admin"` (NIE `laborant*`). Admin-only → `@role_required("admin")`.
- **Audit:** `log_event(event_type, entity_type=..., entity_id=..., diff=..., db=db)` → musi działać w request context (`actors_from_request` czyta `session['user']` + `shift_workers` dla roli `lab`/`cert`). W testach fixture ustawia oba.
- **Cache-bust:** `<script src="{{ url_for('chzt.static', filename='chzt.js') }}?v=1">` — after_request hook w `app.py` liczy na `?v=` żeby bezpiecznie cache'ować.
- **Jinja2:** templates per blueprint w `mbr/chzt/templates/chzt/...` NIE — Flask default search path wymaga `mbr/chzt/templates/<name>.html` i include'u po `chzt/name.html`. Zaznaczone w krokach niżej.

---

## Task 1: Scaffold blueprint + DB tables

**Cel:** Blueprint zarejestrowany, obie tabele tworzone przy starcie, nic jeszcze nie robi.

**Files:**
- Create: `mbr/chzt/__init__.py`
- Create: `mbr/chzt/models.py`
- Create: `mbr/chzt/routes.py`
- Create: `tests/test_chzt.py`
- Modify: `mbr/app.py`

- [ ] **Step 1: Napisz failing test dla `init_chzt_tables`**

Plik: `tests/test_chzt.py`

```python
"""Tests for mbr.chzt — sessions, pomiary, autosave, history."""

import json as _json
import sqlite3
import pytest
from contextlib import contextmanager
from datetime import datetime, date

from mbr.models import init_mbr_tables
from mbr.chzt.models import init_chzt_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    init_chzt_tables(conn)
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (1, 'Jan', 'Kowalski', 'JK', 'JK', 1)"
    )
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (2, 'Anna', 'Nowak', 'AN', 'AN', 1)"
    )
    conn.commit()
    yield conn
    conn.close()


def test_init_chzt_tables_creates_sesje(db):
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='chzt_sesje'"
    ).fetchone()
    assert row is not None


def test_init_chzt_tables_creates_pomiary(db):
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='chzt_pomiary'"
    ).fetchone()
    assert row is not None


def test_init_chzt_tables_data_unique(db):
    db.execute(
        "INSERT INTO chzt_sesje (data, n_kontenery, created_at, created_by) "
        "VALUES ('2026-04-18', 8, '2026-04-18T10:00:00', 1)"
    )
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO chzt_sesje (data, n_kontenery, created_at, created_by) "
            "VALUES ('2026-04-18', 8, '2026-04-18T11:00:00', 1)"
        )


def test_init_chzt_tables_pomiar_unique_per_session(db):
    db.execute(
        "INSERT INTO chzt_sesje (id, data, n_kontenery, created_at, created_by) "
        "VALUES (1, '2026-04-18', 8, '2026-04-18T10:00:00', 1)"
    )
    db.execute(
        "INSERT INTO chzt_pomiary (sesja_id, punkt_nazwa, kolejnosc, updated_at) "
        "VALUES (1, 'hala', 1, '2026-04-18T10:00:00')"
    )
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO chzt_pomiary (sesja_id, punkt_nazwa, kolejnosc, updated_at) "
            "VALUES (1, 'hala', 2, '2026-04-18T10:05:00')"
        )
```

- [ ] **Step 2: Uruchom testy — oczekiwany fail**

Run: `pytest tests/test_chzt.py -v`
Expected: ImportError `No module named 'mbr.chzt'`.

- [ ] **Step 3: Utwórz `mbr/chzt/__init__.py`**

```python
"""ChZT ścieków — sessions, autosave pomiary, historia, finalize."""

from flask import Blueprint

chzt_bp = Blueprint(
    "chzt",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/chzt/static",
)

from mbr.chzt import routes  # noqa: E402, F401
```

- [ ] **Step 4: Utwórz pusty `mbr/chzt/routes.py`**

```python
"""ChZT Flask handlers — to be implemented task-by-task."""

from mbr.chzt import chzt_bp  # noqa: F401
```

- [ ] **Step 5: Utwórz `mbr/chzt/models.py` z `init_chzt_tables()`**

```python
"""ChZT SQLite schema + helpers.

Neither helper commits — callers own the transaction.
"""

from datetime import datetime


def init_chzt_tables(db):
    """Create chzt_sesje + chzt_pomiary tables. Idempotent."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS chzt_sesje (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            data         TEXT NOT NULL UNIQUE,
            n_kontenery  INTEGER NOT NULL DEFAULT 8,
            created_at   TEXT NOT NULL,
            created_by   INTEGER REFERENCES workers(id),
            finalized_at TEXT,
            finalized_by INTEGER REFERENCES workers(id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS chzt_pomiary (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            sesja_id     INTEGER NOT NULL REFERENCES chzt_sesje(id) ON DELETE CASCADE,
            punkt_nazwa  TEXT NOT NULL,
            kolejnosc    INTEGER NOT NULL,
            ph           REAL,
            p1           REAL,
            p2           REAL,
            p3           REAL,
            p4           REAL,
            p5           REAL,
            srednia      REAL,
            updated_at   TEXT NOT NULL,
            updated_by   INTEGER REFERENCES workers(id),
            UNIQUE(sesja_id, punkt_nazwa)
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_chzt_sesje_data ON chzt_sesje(data DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_chzt_pomiary_sesja ON chzt_pomiary(sesja_id)")
    db.commit()
```

- [ ] **Step 6: Zarejestruj blueprint w `mbr/app.py`**

Odnajdź linię `from mbr.ml_export import ml_export_bp` (ok. linia 58) i **poniżej** dodaj:

```python
    from mbr.chzt import chzt_bp
```

Odnajdź `app.register_blueprint(ml_export_bp)` (ok. linia 72) i **poniżej** dodaj:

```python
    app.register_blueprint(chzt_bp)
```

Odnajdź `init_mbr_tables(db)` w bloku `with app.app_context():` (ok. linia 79) i **poniżej** dodaj (PRZED `_PARAM_METHOD_MAP` block):

```python
            from mbr.chzt.models import init_chzt_tables
            init_chzt_tables(db)
```

- [ ] **Step 7: Uruchom testy — powinny przejść**

Run: `pytest tests/test_chzt.py -v`
Expected: 4 passed.

- [ ] **Step 8: Smoke test — aplikacja startuje**

Run: `python -c "from mbr.app import create_app; create_app()"`
Expected: exit 0, bez błędów.

- [ ] **Step 9: Commit**

```bash
git add mbr/chzt/__init__.py mbr/chzt/models.py mbr/chzt/routes.py mbr/app.py tests/test_chzt.py
git commit -m "feat(chzt): scaffold blueprint + chzt_sesje/chzt_pomiary tables"
```

---

## Task 2: Session helpers + GET /api/chzt/session/today

**Cel:** Otwarcie modala zaciąga (lub tworzy) dzisiejszą sesję wraz z N+3 wierszami pomiarów.

**Files:**
- Modify: `mbr/chzt/models.py` (helpery `get_or_create_session`, `get_session_with_pomiary`, `build_punkty_names`)
- Modify: `mbr/chzt/routes.py` (endpoint + audit)
- Modify: `tests/test_chzt.py`

- [ ] **Step 1: Napisz failing test dla `build_punkty_names`**

Dopisz na końcu `tests/test_chzt.py`:

```python
from mbr.chzt.models import build_punkty_names


def test_build_punkty_names_n0():
    assert build_punkty_names(0) == ["hala", "rura", "szambiarka"]


def test_build_punkty_names_n8():
    names = build_punkty_names(8)
    assert names[0] == "hala"
    assert names[1] == "rura"
    assert names[2:10] == [f"kontener {i}" for i in range(1, 9)]
    assert names[-1] == "szambiarka"
    assert len(names) == 11
```

- [ ] **Step 2: Uruchom test — ImportError**

Run: `pytest tests/test_chzt.py::test_build_punkty_names_n8 -v`
Expected: FAIL — cannot import `build_punkty_names`.

- [ ] **Step 3: Dodaj `build_punkty_names` do `mbr/chzt/models.py`**

Dopisz na końcu `mbr/chzt/models.py`:

```python
def build_punkty_names(n_kontenery: int) -> list:
    """Return punkt_nazwa list in canonical order: hala, rura, kontener 1..N, szambiarka."""
    names = ["hala", "rura"]
    for i in range(1, n_kontenery + 1):
        names.append(f"kontener {i}")
    names.append("szambiarka")
    return names
```

- [ ] **Step 4: Testy przechodzą**

Run: `pytest tests/test_chzt.py -v`
Expected: 6 passed.

- [ ] **Step 5: Failing test dla `get_or_create_session`**

Dopisz do `tests/test_chzt.py`:

```python
from mbr.chzt.models import get_or_create_session, get_session_with_pomiary


def test_get_or_create_session_creates_fresh(db):
    session_id, created = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=8)
    db.commit()
    assert created is True
    assert isinstance(session_id, int)

    pomiary = db.execute(
        "SELECT punkt_nazwa, kolejnosc FROM chzt_pomiary WHERE sesja_id=? ORDER BY kolejnosc",
        (session_id,),
    ).fetchall()
    assert len(pomiary) == 11  # hala + rura + 8 kontenerów + szambiarka
    assert pomiary[0]["punkt_nazwa"] == "hala"
    assert pomiary[0]["kolejnosc"] == 1
    assert pomiary[-1]["punkt_nazwa"] == "szambiarka"
    assert pomiary[-1]["kolejnosc"] == 11


def test_get_or_create_session_idempotent(db):
    sid1, c1 = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=8)
    db.commit()
    sid2, c2 = get_or_create_session(db, "2026-04-18", created_by=2, n_kontenery=5)
    db.commit()
    assert sid1 == sid2
    assert c1 is True
    assert c2 is False
    # n_kontenery NOT overwritten
    row = db.execute("SELECT n_kontenery FROM chzt_sesje WHERE id=?", (sid1,)).fetchone()
    assert row["n_kontenery"] == 8


def test_get_session_with_pomiary_shape(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=2)
    db.commit()
    session = get_session_with_pomiary(db, sid)
    assert session["id"] == sid
    assert session["data"] == "2026-04-18"
    assert session["n_kontenery"] == 2
    assert session["finalized_at"] is None
    assert len(session["punkty"]) == 5  # hala, rura, k1, k2, szambiarka
    hala = session["punkty"][0]
    assert hala["punkt_nazwa"] == "hala"
    assert hala["ph"] is None
    assert hala["srednia"] is None
```

- [ ] **Step 6: Uruchom testy — FAIL**

Run: `pytest tests/test_chzt.py -v`
Expected: 3 fails (funkcje nie istnieją).

- [ ] **Step 7: Dodaj helpery do `mbr/chzt/models.py`**

Dopisz:

```python
def get_or_create_session(db, data_iso: str, *, created_by: int, n_kontenery: int = 8):
    """Return (session_id, created_bool).

    If session for `data_iso` exists, returns its id and created=False.
    Otherwise inserts a new session with n_kontenery and seeds pomiary rows
    in canonical order. `data_iso` format: YYYY-MM-DD.
    """
    row = db.execute("SELECT id FROM chzt_sesje WHERE data=?", (data_iso,)).fetchone()
    if row:
        return row["id"], False

    now = datetime.now().isoformat(timespec="seconds")
    cur = db.execute(
        "INSERT INTO chzt_sesje (data, n_kontenery, created_at, created_by) "
        "VALUES (?, ?, ?, ?)",
        (data_iso, n_kontenery, now, created_by),
    )
    session_id = cur.lastrowid

    names = build_punkty_names(n_kontenery)
    for idx, name in enumerate(names, start=1):
        db.execute(
            "INSERT INTO chzt_pomiary (sesja_id, punkt_nazwa, kolejnosc, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (session_id, name, idx, now),
        )

    return session_id, True


def get_session_with_pomiary(db, session_id: int) -> dict:
    """Return {session fields..., punkty: [pomiar rows ordered by kolejnosc]}.

    Returns None if session not found.
    """
    srow = db.execute(
        "SELECT id, data, n_kontenery, created_at, created_by, "
        "       finalized_at, finalized_by FROM chzt_sesje WHERE id=?",
        (session_id,),
    ).fetchone()
    if srow is None:
        return None
    prows = db.execute(
        "SELECT id, punkt_nazwa, kolejnosc, ph, p1, p2, p3, p4, p5, srednia, "
        "       updated_at, updated_by "
        "FROM chzt_pomiary WHERE sesja_id=? ORDER BY kolejnosc",
        (session_id,),
    ).fetchall()
    return {
        **dict(srow),
        "punkty": [dict(p) for p in prows],
    }
```

- [ ] **Step 8: Testy helperów przechodzą**

Run: `pytest tests/test_chzt.py -v`
Expected: 9 passed.

- [ ] **Step 9: Failing route test — `GET /api/chzt/session/today`**

Dopisz do `tests/test_chzt.py` (po fixture `db`):

```python
@pytest.fixture
def client(monkeypatch, db):
    """Flask test client with session user + shift workers seeded."""
    import mbr.db
    import mbr.chzt.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.chzt.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = {"login": "jk", "rola": "lab", "imie_nazwisko": "Jan Kowalski"}
        sess["shift_workers"] = [1]
    return c


@pytest.fixture
def admin_client(monkeypatch, db):
    import mbr.db
    import mbr.chzt.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.chzt.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = {"login": "admin", "rola": "admin", "imie_nazwisko": "Admin"}
    return c


def test_session_today_creates_and_returns(client, db):
    resp = client.get("/api/chzt/session/today")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["session"]["data"] == date.today().isoformat()
    assert data["session"]["finalized_at"] is None
    assert len(data["session"]["punkty"]) == 11


def test_session_today_idempotent(client, db):
    r1 = client.get("/api/chzt/session/today").get_json()
    r2 = client.get("/api/chzt/session/today").get_json()
    assert r1["session"]["id"] == r2["session"]["id"]


def test_session_today_logs_created_audit(client, db):
    client.get("/api/chzt/session/today")
    rows = db.execute(
        "SELECT event_type FROM audit_log WHERE event_type='chzt.session.created'"
    ).fetchall()
    assert len(rows) == 1


def test_session_today_logs_created_audit_only_once(client, db):
    client.get("/api/chzt/session/today")
    client.get("/api/chzt/session/today")
    rows = db.execute(
        "SELECT event_type FROM audit_log WHERE event_type='chzt.session.created'"
    ).fetchall()
    assert len(rows) == 1
```

- [ ] **Step 10: Uruchom — FAIL (brak route)**

Run: `pytest tests/test_chzt.py::test_session_today_creates_and_returns -v`
Expected: 404.

- [ ] **Step 11: Implementuj endpoint w `mbr/chzt/routes.py`**

Zastąp zawartość `mbr/chzt/routes.py`:

```python
"""ChZT Flask handlers."""

from datetime import date

from flask import jsonify, session

from mbr.chzt import chzt_bp
from mbr.chzt.models import get_or_create_session, get_session_with_pomiary
from mbr.db import db_session
from mbr.shared.audit import log_event
from mbr.shared.decorators import login_required, role_required


ROLES_EDIT = ("lab", "kj", "cert", "technolog", "admin")


def _current_worker_id(db):
    """Resolve session user → workers.id.

    For 'lab'/'cert' roles, returns the FIRST shift worker id (sessions can have
    multiple, but a single id is sufficient as `updated_by`; audit retains the
    full shift via actors_from_request).
    For other roles, returns None (audit still records actor, but updated_by
    column will be NULL — that's fine; NULL is used for non-laborant writes).
    """
    user = session.get("user") or {}
    rola = user.get("rola")
    if rola in ("lab", "cert"):
        sw = session.get("shift_workers") or []
        return sw[0] if sw else None
    return None


@chzt_bp.route("/api/chzt/session/today", methods=["GET"])
@role_required(*ROLES_EDIT)
def api_session_today():
    today = date.today().isoformat()
    with db_session() as db:
        worker_id = _current_worker_id(db)
        session_id, created = get_or_create_session(db, today, created_by=worker_id, n_kontenery=8)
        if created:
            log_event(
                "chzt.session.created",
                entity_type="chzt_sesje",
                entity_id=session_id,
                entity_label=today,
                db=db,
            )
        db.commit()
        payload = get_session_with_pomiary(db, session_id)
    return jsonify({"session": payload})
```

- [ ] **Step 12: Testy przechodzą**

Run: `pytest tests/test_chzt.py -v`
Expected: 13 passed.

- [ ] **Step 13: Commit**

```bash
git add mbr/chzt/models.py mbr/chzt/routes.py tests/test_chzt.py
git commit -m "feat(chzt): GET /api/chzt/session/today — get-or-create + seed pomiary + audit"
```

---

## Task 3: PUT /api/chzt/pomiar/<id> — autosave wiersza + srednia + audit

**Cel:** Jedno pole zmienione w UI → 1 PUT z całym wierszem → backend liczy `srednia`, zapisuje, loguje audit (tylko przy rzeczywistej zmianie).

**Files:**
- Modify: `mbr/chzt/models.py` (helpery `compute_srednia`, `get_pomiar`, `update_pomiar`)
- Modify: `mbr/chzt/routes.py` (endpoint PUT)
- Modify: `tests/test_chzt.py`

- [ ] **Step 1: Failing test dla `compute_srednia`**

Dopisz do `tests/test_chzt.py`:

```python
from mbr.chzt.models import compute_srednia


def test_compute_srednia_none_when_lt_2():
    assert compute_srednia({"p1": 10, "p2": None, "p3": None, "p4": None, "p5": None}) is None
    assert compute_srednia({"p1": None, "p2": None, "p3": None, "p4": None, "p5": None}) is None


def test_compute_srednia_average_of_nonnull():
    assert compute_srednia({"p1": 10, "p2": 20, "p3": None, "p4": None, "p5": None}) == 15.0
    assert compute_srednia({"p1": 10, "p2": 20, "p3": 30, "p4": 40, "p5": 50}) == 30.0
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `pytest tests/test_chzt.py::test_compute_srednia_none_when_lt_2 -v`
Expected: FAIL.

- [ ] **Step 3: Implementuj `compute_srednia`**

Dopisz do `mbr/chzt/models.py`:

```python
def compute_srednia(row: dict):
    """Return average of non-null p1..p5 if ≥2 non-null, else None."""
    vals = [row.get(k) for k in ("p1", "p2", "p3", "p4", "p5")]
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return None
    return sum(vals) / len(vals)
```

- [ ] **Step 4: Testy — PASS**

Run: `pytest tests/test_chzt.py -v`
Expected: 15 passed.

- [ ] **Step 5: Failing tests dla `get_pomiar` + `update_pomiar`**

Dopisz:

```python
from mbr.chzt.models import get_pomiar, update_pomiar


def test_get_pomiar_returns_row(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=2)
    db.commit()
    row = db.execute("SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='hala'", (sid,)).fetchone()
    p = get_pomiar(db, row["id"])
    assert p["punkt_nazwa"] == "hala"
    assert p["ph"] is None
    assert p["sesja_id"] == sid


def test_get_pomiar_returns_none_for_missing(db):
    assert get_pomiar(db, 99999) is None


def test_update_pomiar_writes_fields_and_srednia(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=2)
    db.commit()
    pid = db.execute("SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='hala'", (sid,)).fetchone()["id"]
    update_pomiar(db, pid, {"ph": 10, "p1": 100, "p2": 200, "p3": None, "p4": None, "p5": None}, updated_by=1)
    db.commit()
    row = db.execute("SELECT ph, p1, p2, srednia FROM chzt_pomiary WHERE id=?", (pid,)).fetchone()
    assert row["ph"] == 10
    assert row["p1"] == 100
    assert row["p2"] == 200
    assert row["srednia"] == 150.0


def test_update_pomiar_clears_srednia_if_lt_2(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=2)
    db.commit()
    pid = db.execute("SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='hala'", (sid,)).fetchone()["id"]
    update_pomiar(db, pid, {"ph": 10, "p1": 100, "p2": None, "p3": None, "p4": None, "p5": None}, updated_by=1)
    db.commit()
    row = db.execute("SELECT srednia FROM chzt_pomiary WHERE id=?", (pid,)).fetchone()
    assert row["srednia"] is None
```

- [ ] **Step 6: Uruchom — FAIL**

Run: `pytest tests/test_chzt.py -v`
Expected: 4 FAIL (brak helperów).

- [ ] **Step 7: Implementuj `get_pomiar` i `update_pomiar`**

Dopisz do `mbr/chzt/models.py`:

```python
POMIAR_FIELDS = ("ph", "p1", "p2", "p3", "p4", "p5")


def get_pomiar(db, pomiar_id: int) -> dict:
    row = db.execute(
        "SELECT id, sesja_id, punkt_nazwa, kolejnosc, ph, p1, p2, p3, p4, p5, "
        "       srednia, updated_at, updated_by "
        "FROM chzt_pomiary WHERE id=?",
        (pomiar_id,),
    ).fetchone()
    return dict(row) if row else None


def update_pomiar(db, pomiar_id: int, new_values: dict, *, updated_by: int):
    """Write new_values to the given pomiar + recompute srednia + timestamp.

    Caller owns the transaction (no commit here). Returns the updated row dict.
    """
    srednia = compute_srednia(new_values)
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "UPDATE chzt_pomiary "
        "SET ph=?, p1=?, p2=?, p3=?, p4=?, p5=?, srednia=?, updated_at=?, updated_by=? "
        "WHERE id=?",
        (
            new_values.get("ph"),
            new_values.get("p1"),
            new_values.get("p2"),
            new_values.get("p3"),
            new_values.get("p4"),
            new_values.get("p5"),
            srednia,
            now,
            updated_by,
            pomiar_id,
        ),
    )
    return get_pomiar(db, pomiar_id)
```

- [ ] **Step 8: Testy — PASS**

Run: `pytest tests/test_chzt.py -v`
Expected: 19 passed.

- [ ] **Step 9: Failing route tests dla `PUT /api/chzt/pomiar/<id>`**

Dopisz do `tests/test_chzt.py`:

```python
def _get_today_pomiar_id(client, db, punkt="hala"):
    resp = client.get("/api/chzt/session/today")
    session_payload = resp.get_json()["session"]
    for p in session_payload["punkty"]:
        if p["punkt_nazwa"] == punkt:
            return p["id"]
    raise AssertionError(f"punkt {punkt} not found")


def test_put_pomiar_updates_row(client, db):
    pid = _get_today_pomiar_id(client, db, "hala")
    resp = client.put(f"/api/chzt/pomiar/{pid}", json={
        "ph": 10, "p1": 25000, "p2": 26000, "p3": None, "p4": None, "p5": None
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["pomiar"]["ph"] == 10
    assert data["pomiar"]["srednia"] == 25500.0
    assert data["pomiar"]["updated_at"] is not None


def test_put_pomiar_logs_audit_with_diff(client, db):
    pid = _get_today_pomiar_id(client, db, "hala")
    client.put(f"/api/chzt/pomiar/{pid}", json={
        "ph": 10, "p1": 25000, "p2": 26000, "p3": None, "p4": None, "p5": None
    })
    rows = db.execute(
        "SELECT event_type, diff_json, entity_id FROM audit_log "
        "WHERE event_type='chzt.pomiar.updated'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["entity_id"] == pid
    diff = _json.loads(rows[0]["diff_json"])
    fields = {d["pole"] for d in diff}
    assert "ph" in fields
    assert "p1" in fields
    assert "p2" in fields


def test_put_pomiar_no_audit_on_noop(client, db):
    pid = _get_today_pomiar_id(client, db, "hala")
    client.put(f"/api/chzt/pomiar/{pid}", json={
        "ph": 10, "p1": 25000, "p2": 26000, "p3": None, "p4": None, "p5": None
    })
    # Second identical PUT should not log
    client.put(f"/api/chzt/pomiar/{pid}", json={
        "ph": 10, "p1": 25000, "p2": 26000, "p3": None, "p4": None, "p5": None
    })
    rows = db.execute(
        "SELECT event_type FROM audit_log WHERE event_type='chzt.pomiar.updated'"
    ).fetchall()
    assert len(rows) == 1


def test_put_pomiar_404_for_missing(client, db):
    resp = client.put("/api/chzt/pomiar/99999", json={
        "ph": 10, "p1": 1, "p2": 2, "p3": None, "p4": None, "p5": None
    })
    assert resp.status_code == 404
```

- [ ] **Step 10: Uruchom — FAIL**

Run: `pytest tests/test_chzt.py::test_put_pomiar_updates_row -v`
Expected: 404 (brak route).

- [ ] **Step 11: Dodaj route do `mbr/chzt/routes.py`**

Dopisz na końcu `mbr/chzt/routes.py`:

```python
from flask import request

from mbr.chzt.models import get_pomiar, update_pomiar, POMIAR_FIELDS
from mbr.shared.audit import diff_fields


@chzt_bp.route("/api/chzt/pomiar/<int:pomiar_id>", methods=["PUT"])
@role_required(*ROLES_EDIT)
def api_pomiar_update(pomiar_id: int):
    payload = request.get_json(force=True) or {}
    new_values = {k: payload.get(k) for k in POMIAR_FIELDS}

    with db_session() as db:
        old = get_pomiar(db, pomiar_id)
        if old is None:
            return jsonify({"error": "pomiar nie istnieje"}), 404

        changes = diff_fields(old, new_values, list(POMIAR_FIELDS))
        updated = update_pomiar(db, pomiar_id, new_values, updated_by=_current_worker_id(db))

        if changes:
            log_event(
                "chzt.pomiar.updated",
                entity_type="chzt_pomiary",
                entity_id=pomiar_id,
                entity_label=old["punkt_nazwa"],
                diff=changes,
                context={"sesja_id": old["sesja_id"]},
                db=db,
            )
        db.commit()

    return jsonify({"pomiar": updated})
```

- [ ] **Step 12: Testy — PASS**

Run: `pytest tests/test_chzt.py -v`
Expected: 23 passed.

- [ ] **Step 13: Commit**

```bash
git add mbr/chzt/models.py mbr/chzt/routes.py tests/test_chzt.py
git commit -m "feat(chzt): PUT /api/chzt/pomiar/<id> — autosave row + srednia + audit diff"
```

---

## Task 4: PATCH /api/chzt/session/<id> — n_kontenery resize

**Cel:** Zmiana liczby kontenerów dodaje/usuwa wiersze. Odrzuca usuwanie kontenerów z danymi.

**Files:**
- Modify: `mbr/chzt/models.py` (helper `resize_kontenery`)
- Modify: `mbr/chzt/routes.py` (endpoint PATCH)
- Modify: `tests/test_chzt.py`

- [ ] **Step 1: Failing tests dla `resize_kontenery`**

Dopisz do `tests/test_chzt.py`:

```python
from mbr.chzt.models import resize_kontenery


def test_resize_kontenery_up_adds_rows(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=2)
    db.commit()
    resize_kontenery(db, sid, new_n=5)
    db.commit()
    rows = db.execute(
        "SELECT punkt_nazwa, kolejnosc FROM chzt_pomiary WHERE sesja_id=? ORDER BY kolejnosc",
        (sid,),
    ).fetchall()
    names = [r["punkt_nazwa"] for r in rows]
    assert names == ["hala", "rura", "kontener 1", "kontener 2", "kontener 3",
                     "kontener 4", "kontener 5", "szambiarka"]
    # szambiarka kolejnosc
    assert rows[-1]["kolejnosc"] == 8


def test_resize_kontenery_down_empty_deletes(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=5)
    db.commit()
    resize_kontenery(db, sid, new_n=2)
    db.commit()
    names = [r["punkt_nazwa"] for r in db.execute(
        "SELECT punkt_nazwa FROM chzt_pomiary WHERE sesja_id=? ORDER BY kolejnosc", (sid,)
    ).fetchall()]
    assert "kontener 3" not in names
    assert "kontener 4" not in names
    assert "kontener 5" not in names
    assert names[-1] == "szambiarka"


def test_resize_kontenery_down_with_data_raises(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=5)
    db.commit()
    # Put data in kontener 4
    db.execute(
        "UPDATE chzt_pomiary SET ph=7 WHERE sesja_id=? AND punkt_nazwa='kontener 4'",
        (sid,),
    )
    db.commit()
    with pytest.raises(ValueError) as exc:
        resize_kontenery(db, sid, new_n=2)
    assert "kontener 4" in str(exc.value)


def test_resize_kontenery_updates_session_n(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=2)
    db.commit()
    resize_kontenery(db, sid, new_n=7)
    db.commit()
    n = db.execute("SELECT n_kontenery FROM chzt_sesje WHERE id=?", (sid,)).fetchone()["n_kontenery"]
    assert n == 7
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `pytest tests/test_chzt.py::test_resize_kontenery_up_adds_rows -v`
Expected: ImportError.

- [ ] **Step 3: Implementuj `resize_kontenery`**

Dopisz do `mbr/chzt/models.py`:

```python
def resize_kontenery(db, session_id: int, *, new_n: int):
    """Change n_kontenery — add missing kontener rows or delete trailing empty ones.

    Raises ValueError listing rejected punkt_nazwa values if shrinking would
    delete rows with any non-null data (ph, p1..p5).
    """
    srow = db.execute("SELECT n_kontenery FROM chzt_sesje WHERE id=?", (session_id,)).fetchone()
    if srow is None:
        raise ValueError(f"session {session_id} not found")
    old_n = srow["n_kontenery"]

    if new_n == old_n:
        return

    now = datetime.now().isoformat(timespec="seconds")

    if new_n > old_n:
        # Add kontener (old_n+1)..new_n. Shift szambiarka kolejnosc.
        # First, bump szambiarka kolejnosc to new_n + 3 (hala=1, rura=2, kontenery=3..new_n+2)
        db.execute(
            "UPDATE chzt_pomiary SET kolejnosc=? WHERE sesja_id=? AND punkt_nazwa='szambiarka'",
            (new_n + 3, session_id),
        )
        for i in range(old_n + 1, new_n + 1):
            db.execute(
                "INSERT INTO chzt_pomiary (sesja_id, punkt_nazwa, kolejnosc, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (session_id, f"kontener {i}", i + 2, now),
            )
    else:
        # Shrink — check kontener (new_n+1)..old_n have no data
        to_delete = [f"kontener {i}" for i in range(new_n + 1, old_n + 1)]
        placeholders = ",".join("?" * len(to_delete))
        rows_with_data = db.execute(
            f"SELECT punkt_nazwa FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa IN ({placeholders}) "
            f"AND (ph IS NOT NULL OR p1 IS NOT NULL OR p2 IS NOT NULL OR p3 IS NOT NULL "
            f"     OR p4 IS NOT NULL OR p5 IS NOT NULL)",
            (session_id, *to_delete),
        ).fetchall()
        if rows_with_data:
            names = [r["punkt_nazwa"] for r in rows_with_data]
            raise ValueError(f"Kontenery z danymi: {', '.join(names)}")

        db.execute(
            f"DELETE FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa IN ({placeholders})",
            (session_id, *to_delete),
        )
        # Move szambiarka kolejnosc down
        db.execute(
            "UPDATE chzt_pomiary SET kolejnosc=? WHERE sesja_id=? AND punkt_nazwa='szambiarka'",
            (new_n + 3, session_id),
        )

    db.execute(
        "UPDATE chzt_sesje SET n_kontenery=? WHERE id=?",
        (new_n, session_id),
    )
```

- [ ] **Step 4: Testy — PASS**

Run: `pytest tests/test_chzt.py -v`
Expected: 27 passed.

- [ ] **Step 5: Failing route tests**

Dopisz do `tests/test_chzt.py`:

```python
def test_patch_session_n_kontenery_up(client, db):
    r0 = client.get("/api/chzt/session/today").get_json()
    sid = r0["session"]["id"]
    resp = client.patch(f"/api/chzt/session/{sid}", json={"n_kontenery": 10})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["session"]["n_kontenery"] == 10
    names = [p["punkt_nazwa"] for p in data["session"]["punkty"]]
    assert "kontener 10" in names


def test_patch_session_n_kontenery_down_blocked(client, db):
    r0 = client.get("/api/chzt/session/today").get_json()
    sid = r0["session"]["id"]
    k5_pid = None
    for p in r0["session"]["punkty"]:
        if p["punkt_nazwa"] == "kontener 5":
            k5_pid = p["id"]
    client.put(f"/api/chzt/pomiar/{k5_pid}", json={
        "ph": 10, "p1": 100, "p2": 200, "p3": None, "p4": None, "p5": None
    })
    resp = client.patch(f"/api/chzt/session/{sid}", json={"n_kontenery": 3})
    assert resp.status_code == 409
    body = resp.get_json()
    assert "kontener 5" in body["error"]


def test_patch_session_logs_audit(client, db):
    r0 = client.get("/api/chzt/session/today").get_json()
    sid = r0["session"]["id"]
    client.patch(f"/api/chzt/session/{sid}", json={"n_kontenery": 10})
    rows = db.execute(
        "SELECT event_type, diff_json FROM audit_log "
        "WHERE event_type='chzt.session.n_kontenery_changed'"
    ).fetchall()
    assert len(rows) == 1
    diff = _json.loads(rows[0]["diff_json"])
    assert diff[0]["pole"] == "n_kontenery"
    assert diff[0]["stara"] == 8
    assert diff[0]["nowa"] == 10
```

- [ ] **Step 6: Uruchom — FAIL**

Run: `pytest tests/test_chzt.py::test_patch_session_n_kontenery_up -v`

- [ ] **Step 7: Dodaj route**

Dopisz do `mbr/chzt/routes.py`:

```python
from mbr.chzt.models import resize_kontenery


@chzt_bp.route("/api/chzt/session/<int:session_id>", methods=["PATCH"])
@role_required(*ROLES_EDIT)
def api_session_patch(session_id: int):
    payload = request.get_json(force=True) or {}
    new_n = payload.get("n_kontenery")
    if not isinstance(new_n, int) or new_n < 0 or new_n > 50:
        return jsonify({"error": "n_kontenery: oczekuję int 0..50"}), 400

    with db_session() as db:
        srow = db.execute("SELECT n_kontenery FROM chzt_sesje WHERE id=?", (session_id,)).fetchone()
        if srow is None:
            return jsonify({"error": "sesja nie istnieje"}), 404
        old_n = srow["n_kontenery"]
        try:
            resize_kontenery(db, session_id, new_n=new_n)
        except ValueError as e:
            return jsonify({"error": str(e)}), 409

        if new_n != old_n:
            log_event(
                "chzt.session.n_kontenery_changed",
                entity_type="chzt_sesje",
                entity_id=session_id,
                diff=[{"pole": "n_kontenery", "stara": old_n, "nowa": new_n}],
                db=db,
            )
        db.commit()
        payload_out = get_session_with_pomiary(db, session_id)
    return jsonify({"session": payload_out})
```

- [ ] **Step 8: Testy — PASS**

Run: `pytest tests/test_chzt.py -v`
Expected: 30 passed.

- [ ] **Step 9: Commit**

```bash
git add mbr/chzt/models.py mbr/chzt/routes.py tests/test_chzt.py
git commit -m "feat(chzt): PATCH /api/chzt/session/<id> — n_kontenery resize + 409 on non-empty"
```

---

## Task 5: Finalize + Unfinalize

**Cel:** `POST .../finalize` waliduje i ustawia marker + audit. `POST .../unfinalize` admin-only.

**Files:**
- Modify: `mbr/chzt/models.py` (helpery `validate_for_finalize`, `finalize_session`, `unfinalize_session`)
- Modify: `mbr/chzt/routes.py`
- Modify: `tests/test_chzt.py`

- [ ] **Step 1: Failing tests walidacji**

Dopisz:

```python
from mbr.chzt.models import validate_for_finalize, finalize_session, unfinalize_session


def test_validate_for_finalize_empty_fails(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=1)
    db.commit()
    errors = validate_for_finalize(db, sid)
    assert len(errors) == 4  # hala, rura, kontener 1, szambiarka all missing
    assert any(e["punkt_nazwa"] == "hala" and "ph" in e["reason"] for e in errors)


def test_validate_for_finalize_passes_when_complete(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=0)
    db.commit()
    for punkt in ("hala", "rura", "szambiarka"):
        pid = db.execute(
            "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa=?",
            (sid, punkt),
        ).fetchone()["id"]
        update_pomiar(db, pid, {"ph": 10, "p1": 1, "p2": 2, "p3": None, "p4": None, "p5": None}, updated_by=1)
    db.commit()
    errors = validate_for_finalize(db, sid)
    assert errors == []


def test_validate_for_finalize_flags_less_than_2(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=0)
    db.commit()
    for punkt in ("hala", "rura"):
        pid = db.execute(
            "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa=?",
            (sid, punkt),
        ).fetchone()["id"]
        update_pomiar(db, pid, {"ph": 10, "p1": 1, "p2": 2, "p3": None, "p4": None, "p5": None}, updated_by=1)
    # szambiarka: only 1 pomiar
    szam_id = db.execute(
        "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='szambiarka'", (sid,)
    ).fetchone()["id"]
    update_pomiar(db, szam_id, {"ph": 10, "p1": 1, "p2": None, "p3": None, "p4": None, "p5": None}, updated_by=1)
    db.commit()
    errors = validate_for_finalize(db, sid)
    assert len(errors) == 1
    assert errors[0]["punkt_nazwa"] == "szambiarka"
    assert "pomiary" in errors[0]["reason"]
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `pytest tests/test_chzt.py::test_validate_for_finalize_empty_fails -v`

- [ ] **Step 3: Implementuj helpery**

Dopisz do `mbr/chzt/models.py`:

```python
def validate_for_finalize(db, session_id: int) -> list:
    """Return list of errors [{punkt_nazwa, reason}]; empty list = OK."""
    rows = db.execute(
        "SELECT punkt_nazwa, ph, p1, p2, p3, p4, p5 "
        "FROM chzt_pomiary WHERE sesja_id=? ORDER BY kolejnosc",
        (session_id,),
    ).fetchall()
    errors = []
    for r in rows:
        if r["ph"] is None:
            errors.append({"punkt_nazwa": r["punkt_nazwa"], "reason": "brak ph"})
            continue
        nonnull = sum(1 for k in ("p1", "p2", "p3", "p4", "p5") if r[k] is not None)
        if nonnull < 2:
            errors.append({"punkt_nazwa": r["punkt_nazwa"], "reason": "min. 2 pomiary"})
    return errors


def finalize_session(db, session_id: int, *, finalized_by: int):
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "UPDATE chzt_sesje SET finalized_at=?, finalized_by=? WHERE id=?",
        (now, finalized_by, session_id),
    )


def unfinalize_session(db, session_id: int):
    db.execute(
        "UPDATE chzt_sesje SET finalized_at=NULL, finalized_by=NULL WHERE id=?",
        (session_id,),
    )
```

- [ ] **Step 4: Testy — PASS**

Run: `pytest tests/test_chzt.py -v`
Expected: 33 passed.

- [ ] **Step 5: Failing route tests**

Dopisz:

```python
def _fill_all_today(client, db, ph=10, p1=100, p2=200):
    r = client.get("/api/chzt/session/today").get_json()
    for p in r["session"]["punkty"]:
        client.put(f"/api/chzt/pomiar/{p['id']}", json={
            "ph": ph, "p1": p1, "p2": p2, "p3": None, "p4": None, "p5": None
        })
    return r["session"]["id"]


def test_finalize_empty_returns_400_with_errors(client, db):
    r = client.get("/api/chzt/session/today").get_json()
    sid = r["session"]["id"]
    resp = client.post(f"/api/chzt/session/{sid}/finalize")
    assert resp.status_code == 400
    body = resp.get_json()
    assert "errors" in body
    assert len(body["errors"]) > 0


def test_finalize_valid_sets_marker(client, db):
    sid = _fill_all_today(client, db)
    resp = client.post(f"/api/chzt/session/{sid}/finalize")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["session"]["finalized_at"] is not None
    assert body["session"]["finalized_by"] == 1


def test_finalize_logs_audit(client, db):
    sid = _fill_all_today(client, db)
    client.post(f"/api/chzt/session/{sid}/finalize")
    rows = db.execute(
        "SELECT event_type FROM audit_log WHERE event_type='chzt.session.finalized'"
    ).fetchall()
    assert len(rows) == 1


def test_finalize_allows_edit_after(client, db):
    """Post-finalize PUT still works and logs audit; finalized_at stays."""
    sid = _fill_all_today(client, db)
    client.post(f"/api/chzt/session/{sid}/finalize")
    pid = _get_today_pomiar_id(client, db, "hala")
    client.put(f"/api/chzt/pomiar/{pid}", json={
        "ph": 11, "p1": 100, "p2": 200, "p3": None, "p4": None, "p5": None
    })
    row = db.execute(
        "SELECT finalized_at FROM chzt_sesje WHERE id=?", (sid,)
    ).fetchone()
    assert row["finalized_at"] is not None


def test_unfinalize_lab_forbidden(client, db):
    sid = _fill_all_today(client, db)
    client.post(f"/api/chzt/session/{sid}/finalize")
    resp = client.post(f"/api/chzt/session/{sid}/unfinalize")
    assert resp.status_code == 403


def test_unfinalize_admin_ok(admin_client, client, db):
    sid = _fill_all_today(client, db)
    client.post(f"/api/chzt/session/{sid}/finalize")
    resp = admin_client.post(f"/api/chzt/session/{sid}/unfinalize")
    assert resp.status_code == 200
    row = db.execute(
        "SELECT finalized_at FROM chzt_sesje WHERE id=?", (sid,)
    ).fetchone()
    assert row["finalized_at"] is None
```

- [ ] **Step 6: Uruchom — FAIL**

Run: `pytest tests/test_chzt.py::test_finalize_empty_returns_400_with_errors -v`

- [ ] **Step 7: Dodaj route'y**

Dopisz do `mbr/chzt/routes.py`:

```python
from mbr.chzt.models import (
    validate_for_finalize, finalize_session, unfinalize_session,
)


@chzt_bp.route("/api/chzt/session/<int:session_id>/finalize", methods=["POST"])
@role_required(*ROLES_EDIT)
def api_session_finalize(session_id: int):
    with db_session() as db:
        if db.execute("SELECT 1 FROM chzt_sesje WHERE id=?", (session_id,)).fetchone() is None:
            return jsonify({"error": "sesja nie istnieje"}), 404
        errors = validate_for_finalize(db, session_id)
        if errors:
            return jsonify({"error": "walidacja", "errors": errors}), 400
        finalize_session(db, session_id, finalized_by=_current_worker_id(db))
        log_event(
            "chzt.session.finalized",
            entity_type="chzt_sesje",
            entity_id=session_id,
            db=db,
        )
        db.commit()
        payload = get_session_with_pomiary(db, session_id)
    return jsonify({"session": payload})


@chzt_bp.route("/api/chzt/session/<int:session_id>/unfinalize", methods=["POST"])
@role_required("admin")
def api_session_unfinalize(session_id: int):
    with db_session() as db:
        if db.execute("SELECT 1 FROM chzt_sesje WHERE id=?", (session_id,)).fetchone() is None:
            return jsonify({"error": "sesja nie istnieje"}), 404
        unfinalize_session(db, session_id)
        log_event(
            "chzt.session.unfinalized",
            entity_type="chzt_sesje",
            entity_id=session_id,
            db=db,
        )
        db.commit()
        payload = get_session_with_pomiary(db, session_id)
    return jsonify({"session": payload})
```

- [ ] **Step 8: Testy — PASS**

Run: `pytest tests/test_chzt.py -v`
Expected: 39 passed.

- [ ] **Step 9: Commit**

```bash
git add mbr/chzt/models.py mbr/chzt/routes.py tests/test_chzt.py
git commit -m "feat(chzt): finalize/unfinalize endpoints + walidacja + audit"
```

---

## Task 6: Read endpoints — session by date, day export, history

**Files:**
- Modify: `mbr/chzt/models.py` (helper `list_sessions_paginated`)
- Modify: `mbr/chzt/routes.py`
- Modify: `tests/test_chzt.py`

- [ ] **Step 1: Failing tests dla `list_sessions_paginated`**

Dopisz:

```python
from mbr.chzt.models import list_sessions_paginated


def test_list_sessions_paginated_desc_order(db):
    get_or_create_session(db, "2026-04-16", created_by=1, n_kontenery=8); db.commit()
    get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=8); db.commit()
    get_or_create_session(db, "2026-04-17", created_by=1, n_kontenery=8); db.commit()
    page = list_sessions_paginated(db, page=1, per_page=10)
    dates = [s["data"] for s in page["sesje"]]
    assert dates == ["2026-04-18", "2026-04-17", "2026-04-16"]
    assert page["total"] == 3
    assert page["page"] == 1
    assert page["pages"] == 1


def test_list_sessions_paginated_splits_pages(db):
    for d in ["2026-04-01", "2026-04-02", "2026-04-03", "2026-04-04", "2026-04-05",
              "2026-04-06", "2026-04-07", "2026-04-08", "2026-04-09", "2026-04-10",
              "2026-04-11", "2026-04-12"]:
        get_or_create_session(db, d, created_by=1, n_kontenery=0); db.commit()
    page1 = list_sessions_paginated(db, page=1, per_page=10)
    page2 = list_sessions_paginated(db, page=2, per_page=10)
    assert len(page1["sesje"]) == 10
    assert len(page2["sesje"]) == 2
    assert page1["pages"] == 2
    assert page2["page"] == 2
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `pytest tests/test_chzt.py::test_list_sessions_paginated_desc_order -v`

- [ ] **Step 3: Implementuj helper**

Dopisz do `mbr/chzt/models.py`:

```python
def list_sessions_paginated(db, *, page: int = 1, per_page: int = 10) -> dict:
    """Return paginated list of sessions DESC by data.

    Shape: {sesje: [{id, data, n_kontenery, finalized_at, finalized_by_name, updated_at_max}],
            total, page, pages}
    """
    page = max(1, int(page))
    per_page = max(1, min(100, int(per_page)))
    offset = (page - 1) * per_page

    total_row = db.execute("SELECT COUNT(*) AS c FROM chzt_sesje").fetchone()
    total = total_row["c"] if total_row else 0
    pages = max(1, (total + per_page - 1) // per_page)

    rows = db.execute(
        "SELECT s.id, s.data, s.n_kontenery, s.finalized_at, "
        "       w.imie || ' ' || w.nazwisko AS finalized_by_name, "
        "       (SELECT MAX(updated_at) FROM chzt_pomiary WHERE sesja_id=s.id) AS updated_at_max "
        "FROM chzt_sesje s "
        "LEFT JOIN workers w ON w.id = s.finalized_by "
        "ORDER BY s.data DESC "
        "LIMIT ? OFFSET ?",
        (per_page, offset),
    ).fetchall()
    return {
        "sesje": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "pages": pages,
        "per_page": per_page,
    }
```

- [ ] **Step 4: Testy — PASS**

Run: `pytest tests/test_chzt.py -v`
Expected: 41 passed.

- [ ] **Step 5: Failing route tests**

Dopisz:

```python
def test_get_session_by_date_ok(client, db):
    client.get("/api/chzt/session/today")
    today = date.today().isoformat()
    resp = client.get(f"/api/chzt/session/{today}")
    assert resp.status_code == 200
    assert resp.get_json()["session"]["data"] == today


def test_get_session_by_date_missing_404(client, db):
    resp = client.get("/api/chzt/session/2020-01-01")
    assert resp.status_code == 404


def test_get_day_finalized_returns_frame(client, db):
    sid = _fill_all_today(client, db, ph=10, p1=25000, p2=26000)
    client.post(f"/api/chzt/session/{sid}/finalize")
    today = date.today().isoformat()
    resp = client.get(f"/api/chzt/day/{today}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"] == today
    assert body["finalized_at"] is not None
    punkty = {p["nazwa"]: p for p in body["punkty"]}
    assert punkty["hala"]["ph"] == 10
    assert punkty["hala"]["srednia"] == 25500.0


def test_get_day_draft_returns_404(client, db):
    _fill_all_today(client, db)
    today = date.today().isoformat()
    resp = client.get(f"/api/chzt/day/{today}")
    assert resp.status_code == 404


def test_get_history_paginated(client, db):
    # Seed 3 past sessions directly
    for d in ["2026-04-10", "2026-04-11", "2026-04-12"]:
        db.execute(
            "INSERT INTO chzt_sesje (data, n_kontenery, created_at, created_by) "
            "VALUES (?, 0, ?, 1)",
            (d, d + "T10:00:00"),
        )
    db.commit()
    resp = client.get("/api/chzt/history?page=1")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total"] == 3
    assert body["sesje"][0]["data"] == "2026-04-12"
```

- [ ] **Step 6: Uruchom — FAIL**

Run: `pytest tests/test_chzt.py::test_get_session_by_date_ok -v`

- [ ] **Step 7: Dodaj route'y**

Dopisz do `mbr/chzt/routes.py`:

```python
from mbr.chzt.models import list_sessions_paginated


@chzt_bp.route("/api/chzt/session/<data_iso>", methods=["GET"])
@role_required(*ROLES_EDIT)
def api_session_by_date(data_iso: str):
    with db_session() as db:
        row = db.execute("SELECT id FROM chzt_sesje WHERE data=?", (data_iso,)).fetchone()
        if row is None:
            return jsonify({"error": "brak sesji dla tej daty"}), 404
        payload = get_session_with_pomiary(db, row["id"])
    return jsonify({"session": payload})


@chzt_bp.route("/api/chzt/day/<data_iso>", methods=["GET"])
@role_required(*ROLES_EDIT)
def api_day_frame(data_iso: str):
    """Export frame for Excel-filling script. Finalized sessions only."""
    with db_session() as db:
        row = db.execute(
            "SELECT id, data, finalized_at FROM chzt_sesje WHERE data=? AND finalized_at IS NOT NULL",
            (data_iso,),
        ).fetchone()
        if row is None:
            return jsonify({"error": "brak sfinalizowanej sesji"}), 404
        prows = db.execute(
            "SELECT punkt_nazwa, ph, srednia FROM chzt_pomiary "
            "WHERE sesja_id=? ORDER BY kolejnosc",
            (row["id"],),
        ).fetchall()
        punkty = [
            {"nazwa": p["punkt_nazwa"], "ph": p["ph"], "srednia": p["srednia"]}
            for p in prows
        ]
    return jsonify({
        "data": row["data"],
        "finalized_at": row["finalized_at"],
        "punkty": punkty,
    })


@chzt_bp.route("/api/chzt/history", methods=["GET"])
@role_required(*ROLES_EDIT)
def api_history():
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1
    with db_session() as db:
        payload = list_sessions_paginated(db, page=page, per_page=10)
    return jsonify(payload)
```

- [ ] **Step 8: Testy — PASS**

Run: `pytest tests/test_chzt.py -v`
Expected: 46 passed.

- [ ] **Step 9: Commit**

```bash
git add mbr/chzt/models.py mbr/chzt/routes.py tests/test_chzt.py
git commit -m "feat(chzt): GET session/<data>, day/<data> export, history pagination"
```

---

## Task 7: Audit history endpoint

**Cel:** Strona historii potrzebuje endpointu który zwróci wszystkie eventy (session + pomiary) jednej sesji.

**Files:**
- Modify: `mbr/chzt/routes.py`
- Modify: `tests/test_chzt.py`

- [ ] **Step 1: Failing test**

Dopisz:

```python
def test_audit_history_for_session(client, db):
    sid = _fill_all_today(client, db)
    client.post(f"/api/chzt/session/{sid}/finalize")
    resp = client.get(f"/api/chzt/session/{sid}/audit-history")
    assert resp.status_code == 200
    body = resp.get_json()
    types = [e["event_type"] for e in body["entries"]]
    assert "chzt.session.created" in types
    assert "chzt.pomiar.updated" in types
    assert "chzt.session.finalized" in types
```

- [ ] **Step 2: Uruchom — FAIL**

Run: `pytest tests/test_chzt.py::test_audit_history_for_session -v`

- [ ] **Step 3: Implementuj endpoint**

Dopisz do `mbr/chzt/routes.py`:

```python
@chzt_bp.route("/api/chzt/session/<int:session_id>/audit-history", methods=["GET"])
@role_required(*ROLES_EDIT)
def api_session_audit_history(session_id: int):
    """Return all audit entries for this session and its pomiary rows, newest-first."""
    with db_session() as db:
        pomiar_ids = [
            r["id"] for r in db.execute(
                "SELECT id FROM chzt_pomiary WHERE sesja_id=?", (session_id,)
            ).fetchall()
        ]
        rows_session = db.execute(
            "SELECT id, dt, event_type, entity_type, entity_id, entity_label, "
            "       diff_json FROM audit_log "
            "WHERE entity_type='chzt_sesje' AND entity_id=?",
            (session_id,),
        ).fetchall()
        rows_pomiar = []
        if pomiar_ids:
            placeholders = ",".join("?" * len(pomiar_ids))
            rows_pomiar = db.execute(
                f"SELECT id, dt, event_type, entity_type, entity_id, entity_label, "
                f"       diff_json FROM audit_log "
                f"WHERE entity_type='chzt_pomiary' AND entity_id IN ({placeholders})",
                pomiar_ids,
            ).fetchall()
        all_rows = sorted(
            [dict(r) for r in list(rows_session) + list(rows_pomiar)],
            key=lambda r: r["dt"],
            reverse=True,
        )
    return jsonify({"entries": all_rows})
```

- [ ] **Step 4: Testy — PASS**

Run: `pytest tests/test_chzt.py -v`
Expected: 47 passed.

- [ ] **Step 5: Commit**

```bash
git add mbr/chzt/routes.py tests/test_chzt.py
git commit -m "feat(chzt): GET /api/chzt/session/<id>/audit-history"
```

---

## Task 8: Migrate modal markup/CSS to blueprint

**Cel:** Markup + CSS modala przeniesione z inline `narzedzia.html` do nowego template/blueprint. Stary JS zostaje do Task 9.

**Files:**
- Create: `mbr/chzt/templates/chzt_modal.html`
- Create: `mbr/chzt/static/chzt.css`
- Modify: `mbr/templates/technolog/narzedzia.html` (usunięcie inline markup/CSS, dodanie include + link)

- [ ] **Step 1: Utwórz `mbr/chzt/templates/chzt_modal.html`**

```html
{# ChZT Ścieków modal — Stripe Accent style. Include z kart Narzędzi. #}
<div class="pal-overlay" id="chzt-overlay" onclick="if(event.target===this)closeChztModal()" style="display:none;">
  <div class="chzt-modal">
    <div class="chzt-topbar">
      <span class="chzt-topbar-title">ChZT Ścieków</span>
      <span class="chzt-topbar-date" id="chzt-date"></span>
      <span class="chzt-status-pill" id="chzt-status-pill"></span>
      <button class="chzt-topbar-close" onclick="closeChztModal()">&times;</button>
    </div>
    <div class="chzt-finalize-banner" id="chzt-finalize-banner" style="display:none;"></div>
    <div class="chzt-toolbar">
      <span class="chzt-toolbar-label">Kontenery:</span>
      <input type="number" id="chzt-n-kontenery" value="8" min="0" max="20" class="chzt-toolbar-input">
      <button class="chzt-btn chzt-btn-sm" id="chzt-generuj-btn" onclick="chztApplyKontenery()">Generuj</button>
      <span class="chzt-toolbar-error" id="chzt-toolbar-error"></span>
    </div>
    <div id="chzt-body" class="chzt-body"></div>
    <div class="chzt-errors" id="chzt-errors" style="display:none;"></div>
    <div class="chzt-footer">
      <button class="chzt-btn" id="chzt-save-btn" onclick="chztFinalize()">Zapisz (finalizuj)</button>
      <span class="chzt-finalized-info" id="chzt-finalized-info" style="display:none;"></span>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Utwórz `mbr/chzt/static/chzt.css`**

```css
/* ═══ ChZT Modal — Stripe Accent ═══ */
.chzt-modal {
  width: 940px; max-width: 95vw; max-height: 90vh;
  background: #fff; border: 1px solid var(--border); border-left: 3px solid var(--teal);
  border-radius: 10px; overflow: hidden;
  display: flex; flex-direction: column;
  box-shadow: 0 8px 40px rgba(0,0,0,0.12);
  animation: modalIn 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
.chzt-topbar {
  padding: 14px 18px; display: flex; align-items: center; gap: 10px;
  border-bottom: 1px solid var(--border-subtle, #e8e4dc);
}
.chzt-topbar-title { font-size: 15px; font-weight: 700; color: var(--teal); }
.chzt-topbar-date { font-size: 11px; color: var(--text-dim); }
.chzt-status-pill {
  margin-left: auto;
  font-size: 11px; padding: 3px 9px; border-radius: 999px;
  background: #f3f4f6; color: var(--text-dim);
  min-width: 120px; text-align: center;
}
.chzt-status-pill.saving { background: #fef3c7; color: #92400e; }
.chzt-status-pill.saved { background: #dcfce7; color: #166534; }
.chzt-status-pill.error { background: #fee2e2; color: #991b1b; }
.chzt-topbar-close {
  background: none; border: none; font-size: 20px;
  color: var(--text-dim); cursor: pointer; width: 30px; height: 30px;
  border-radius: 6px; display: flex; align-items: center; justify-content: center;
}
.chzt-topbar-close:hover { background: var(--surface-alt); color: var(--text); }

.chzt-finalize-banner {
  padding: 8px 18px; background: #ecfdf5; color: #166534;
  font-size: 11px; border-bottom: 1px solid #d1fae5;
}

.chzt-toolbar {
  padding: 10px 18px; display: flex; align-items: center; gap: 8px;
  border-bottom: 1px solid #f0ece4; font-size: 11px; color: var(--text-sec);
}
.chzt-toolbar-label { font-weight: 600; }
.chzt-toolbar-input {
  width: 56px; padding: 4px 8px; border: 1.5px solid var(--border);
  border-radius: 5px; font-size: 12px; text-align: center; font-family: var(--mono);
}
.chzt-toolbar-error {
  color: var(--red, #c13); font-size: 11px;
}

.chzt-body { padding: 14px 18px; overflow-y: auto; flex: 1; min-height: 0; }

.chzt-errors {
  padding: 8px 18px; background: #fee2e2; color: #991b1b;
  font-size: 11px; border-top: 1px solid #fecaca;
}

.chzt-footer {
  padding: 12px 18px; border-top: 1px solid var(--border-subtle, #e8e4dc);
  display: flex; justify-content: flex-end; align-items: center; gap: 12px;
}
.chzt-finalized-info {
  font-size: 11px; color: #166534;
}
.chzt-btn {
  padding: 7px 20px; border-radius: 6px; border: none; cursor: pointer;
  font-family: var(--font); font-size: 12px; font-weight: 600;
  background: var(--teal); color: #fff; transition: filter 0.15s;
}
.chzt-btn:hover { filter: brightness(0.9); }
.chzt-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.chzt-btn-sm { padding: 4px 10px; font-size: 10px; }

/* Table */
.chzt-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.chzt-table th {
  padding: 7px 4px; background: #fafaf7; font-size: 8px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-dim);
  text-align: center; border-bottom: 1px solid var(--border-subtle, #e8e4dc);
}
.chzt-table td {
  padding: 5px 3px; border-bottom: 1px solid #f0ece4; text-align: center;
}
.chzt-table tr.invalid td { border-left: 3px solid var(--red, #c13); }
.chzt-row-error {
  font-size: 10px; color: var(--red, #c13);
  padding-left: 10px;
}
.chzt-punkt {
  font-weight: 700; font-size: 12px; color: var(--teal);
  text-align: left !important; white-space: nowrap; padding-left: 10px !important;
}
.chzt-inp {
  width: 88px; height: 34px; padding: 6px 8px;
  border: 1px solid var(--border); border-radius: 4px;
  font-size: 14px; font-family: var(--mono);
  text-align: center; background: #fff; transition: border-color 0.15s;
}
.chzt-inp:focus {
  border-color: var(--teal); outline: none;
  box-shadow: 0 0 0 2px var(--teal-bg);
}
.chzt-inp.invalid {
  border-color: var(--red, #c13);
  animation: chztShake 0.2s;
}
@keyframes chztShake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-3px); }
  75% { transform: translateX(3px); }
}
.chzt-ph { width: 64px; }
.chzt-avg { font-weight: 700; font-family: var(--mono); font-size: 13px; color: var(--teal); }
#chzt-overlay.show { display: flex !important; align-items: center; justify-content: center; }
```

- [ ] **Step 3: Usuń inline markup/CSS z `narzedzia.html` i dodaj include + asset links**

W `mbr/templates/technolog/narzedzia.html`:

**(a)** W nagłówku sekcji `{% block content %}` (tuż po `<div class="narz-page">`) — nic nie zmieniamy.

**(b)** Usuń cały blok `<style>...</style>` od linii `/* ═══ ChZT Modal — Stripe Accent ═══ */` aż do zamykającego `</style>` (obecnie linie ~895-966).

**(c)** Usuń cały blok `<div class="pal-overlay" id="chzt-overlay" ...> ... </div>` (obecnie linie ~876-893).

**(d)** Po ostatnim `{# ═══ ChZT MODAL ... #}` (linia ~875) zastąp usunięty blok tym:

```jinja
{# ═══ ChZT MODAL (include'owany z blueprintu) ═══ #}
{% include "chzt_modal.html" %}
```

**(e)** Na końcu pliku (po `{% endblock %}`) dopisz w `{% block extra_head %}` albo nowym `{% block extra_css %}` — sprawdź `base.html` jaki blok jest; jeśli nie ma dedykowanego CSS block, dodaj `<link>` w środku `{% block content %}` na górze:

```jinja
<link rel="stylesheet" href="{{ url_for('chzt.static', filename='chzt.css') }}?v=1">
```

**Uwaga implementatora:** zanim wykonasz (e), zrób `grep -n "block extra" mbr/templates/base.html` i wybierz odpowiedni block. Jeśli żadnego nie ma — `<link>` wstaw na samej górze `{% block content %}` w `narzedzia.html`.

- [ ] **Step 4: Smoke test — app startuje, modal się otwiera**

Run: `python -m mbr.app` (CTRL-C po 2 sekundach)

Sprawdź: brak errorów. Następnie sam otwórz w przeglądarce `http://127.0.0.1:5001/technolog/narzedzia` i kliknij kartę "ChZT Ścieków". Modal ma się otworzyć z tabelą 8 kontenerów. (JS jeszcze ze starej wersji — nadpisze w Task 9.)

- [ ] **Step 5: Uruchom testy unit — dalej zielone**

Run: `pytest tests/test_chzt.py -v`
Expected: 47 passed (bez zmian — Python tests nie zależą od templates).

- [ ] **Step 6: Commit**

```bash
git add mbr/chzt/templates/chzt_modal.html mbr/chzt/static/chzt.css mbr/templates/technolog/narzedzia.html
git commit -m "refactor(chzt): migrate modal markup/CSS to blueprint templates + static"
```

---

## Task 9: Frontend JS rewrite — autosave, status pill, Enter-nav

**Cel:** Cała logika JS modala w osobnym pliku, z autosave'em per wiersz (debounce 400ms), statusem "zapisano", Enter-nawigacją, obsługą finalize + walidacji client-side.

**Files:**
- Create: `mbr/chzt/static/chzt.js`
- Modify: `mbr/templates/technolog/narzedzia.html` (usunięcie starego JS, dodanie `<script>` tag)

- [ ] **Step 1: Utwórz `mbr/chzt/static/chzt.js`**

```javascript
// ChZT Ścieków — modal logic with per-row autosave (debounce 400ms).
// Pattern: DB is SSOT. No localStorage. Modal opens → GET session → render.
// Each field edit → debounced PUT /api/chzt/pomiar/<id> with the whole row.

(function(){
  'use strict';

  var _session = null;           // {id, data, n_kontenery, finalized_at, finalized_by, punkty: [...]}
  var _debounceTimers = {};      // pomiar_id → timeout handle
  var _saveInFlight = {};        // pomiar_id → bool

  function el(id) { return document.getElementById(id); }

  function fmtTime(isoDt) {
    if (!isoDt) return '';
    var d = new Date(isoDt);
    return d.toLocaleTimeString('pl-PL', {hour:'2-digit', minute:'2-digit'});
  }

  function setStatus(kind, text) {
    var pill = el('chzt-status-pill');
    pill.className = 'chzt-status-pill ' + kind;
    pill.textContent = text;
  }

  function initialStatus() {
    if (!_session) return;
    var anyFilled = _session.punkty.some(function(p) {
      return p.ph !== null || p.p1 !== null || p.p2 !== null ||
             p.p3 !== null || p.p4 !== null || p.p5 !== null;
    });
    if (_session.finalized_at) {
      setStatus('saved', '✓ zapisano');
    } else if (!anyFilled) {
      setStatus('', '⚪ nowa sesja');
    } else {
      var maxUpdated = _session.punkty
        .map(function(p){ return p.updated_at; })
        .filter(Boolean)
        .sort()
        .slice(-1)[0];
      setStatus('saved', 'zapisano · ' + fmtTime(maxUpdated));
    }
  }

  function renderFinalizedBanner() {
    var banner = el('chzt-finalize-banner');
    var footerInfo = el('chzt-finalized-info');
    var saveBtn = el('chzt-save-btn');
    if (_session.finalized_at) {
      var who = _session.finalized_by_name || ('id=' + _session.finalized_by);
      banner.textContent = '✓ Sfinalizowano ' + fmtTime(_session.finalized_at) +
        ' przez ' + who + ' — edycja możliwa, logowana';
      banner.style.display = 'block';
      saveBtn.style.display = 'none';
      footerInfo.textContent = '✓ Zakończono · edycja aktywna';
      footerInfo.style.display = 'inline';
    } else {
      banner.style.display = 'none';
      saveBtn.style.display = '';
      footerInfo.style.display = 'none';
    }
  }

  function renderDate() {
    if (!_session) return;
    var parts = _session.data.split('-'); // YYYY-MM-DD
    el('chzt-date').textContent = parts[2] + '.' + parts[1] + '.' + parts[0];
  }

  function renderTable() {
    var html = '<table class="chzt-table">' +
      '<thead><tr><th>Punkt</th><th>pH</th><th>P1</th><th>P2</th><th>P3</th><th>P4</th><th>P5</th><th>\u015arednia</th></tr></thead><tbody>';
    _session.punkty.forEach(function(p) {
      var inv = (p.ph === null) || countNonNull(p) < 2;
      html += '<tr data-pid="' + p.id + '"' + (inv ? ' class="invalid"' : '') + '>' +
        '<td class="chzt-punkt">' + escapeHtml(p.punkt_nazwa) + '</td>' +
        inputCell(p, 'ph', 'chzt-ph') +
        inputCell(p, 'p1') + inputCell(p, 'p2') + inputCell(p, 'p3') +
        inputCell(p, 'p4') + inputCell(p, 'p5') +
        '<td class="chzt-avg" id="chzt-avg-' + p.id + '">' + fmtAvg(p.srednia) + '</td>' +
        '</tr>';
    });
    html += '</tbody></table>';
    el('chzt-body').innerHTML = html;
    wireEnterNavigation();
  }

  function countNonNull(p) {
    return ['p1','p2','p3','p4','p5'].filter(function(k){ return p[k] !== null; }).length;
  }

  function inputCell(p, field, extraCls) {
    var val = p[field] === null || p[field] === undefined ? '' : p[field];
    var cls = 'chzt-inp' + (extraCls ? ' ' + extraCls : '');
    return '<td><input class="' + cls + '" type="text" inputmode="decimal" ' +
      'pattern="[0-9]*[.,]?[0-9]*" ' +
      'data-pid="' + p.id + '" data-field="' + field + '" ' +
      'value="' + val + '"></td>';
  }

  function fmtAvg(v) {
    if (v === null || v === undefined) return '\u2014';
    return Math.round(v).toLocaleString('pl-PL');
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }

  function parseNum(s) {
    if (s === '' || s === null || s === undefined) return null;
    var n = parseFloat(String(s).replace(',', '.'));
    return isNaN(n) ? null : n;
  }

  function getRowValues(pid) {
    var out = {};
    ['ph','p1','p2','p3','p4','p5'].forEach(function(f){
      var inp = document.querySelector('input[data-pid="'+pid+'"][data-field="'+f+'"]');
      out[f] = inp ? parseNum(inp.value) : null;
    });
    return out;
  }

  function wireInputHandlers() {
    document.querySelectorAll('#chzt-body .chzt-inp').forEach(function(inp) {
      inp.addEventListener('input', function(){
        var pid = parseInt(inp.dataset.pid);
        // Regex validation visual
        if (inp.value !== '' && !/^[0-9]*[.,]?[0-9]*$/.test(inp.value)) {
          inp.classList.add('invalid');
        } else {
          inp.classList.remove('invalid');
        }
        scheduleAutosave(pid);
      });
    });
  }

  function scheduleAutosave(pid) {
    if (_debounceTimers[pid]) clearTimeout(_debounceTimers[pid]);
    _debounceTimers[pid] = setTimeout(function(){ saveRow(pid, 0); }, 400);
  }

  function saveRow(pid, attempt) {
    if (_saveInFlight[pid]) {
      // Re-schedule after current completes
      _debounceTimers[pid] = setTimeout(function(){ saveRow(pid, 0); }, 400);
      return;
    }
    _saveInFlight[pid] = true;
    setStatus('saving', '🟡 zapisywanie…');
    var values = getRowValues(pid);
    fetch('/api/chzt/pomiar/' + pid, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(values),
    }).then(function(r){
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function(resp){
      _saveInFlight[pid] = false;
      // Update session state cache
      for (var i = 0; i < _session.punkty.length; i++) {
        if (_session.punkty[i].id === pid) {
          _session.punkty[i] = Object.assign(_session.punkty[i], resp.pomiar);
          break;
        }
      }
      // Update srednia cell
      var avgEl = el('chzt-avg-' + pid);
      if (avgEl) avgEl.textContent = fmtAvg(resp.pomiar.srednia);
      setStatus('saved', 'zapisano · ' + fmtTime(resp.pomiar.updated_at));
    }).catch(function(err){
      _saveInFlight[pid] = false;
      if (attempt < 3) {
        setTimeout(function(){ saveRow(pid, attempt + 1); }, 1000);
      } else {
        setStatus('error', '🔴 błąd połączenia');
      }
    });
  }

  function wireEnterNavigation() {
    var inputs = Array.prototype.slice.call(document.querySelectorAll('#chzt-body .chzt-inp'));
    inputs.forEach(function(inp, idx) {
      inp.addEventListener('keydown', function(ev){
        if (ev.key !== 'Enter') return;
        ev.preventDefault();
        // Fields order in DOM reflects: pH, p1, p2, p3, p4, p5 per row.
        // Enter goes to next input in DOM; after P5 of last row → save button.
        var next = inputs[idx + 1];
        if (next) {
          next.focus();
          next.select();
        } else {
          var btn = el('chzt-save-btn');
          if (btn && btn.style.display !== 'none') btn.focus();
        }
      });
    });
    wireInputHandlers();
  }

  function loadSession(urlSuffix) {
    setStatus('saving', '🟡 ładowanie…');
    fetch('/api/chzt/session/' + urlSuffix, {
      headers: {'Accept': 'application/json'},
    }).then(function(r){
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function(resp){
      _session = resp.session;
      el('chzt-n-kontenery').value = _session.n_kontenery;
      renderDate();
      renderTable();
      renderFinalizedBanner();
      initialStatus();
    }).catch(function(){
      setStatus('error', '🔴 nie udało się wczytać');
    });
  }

  window.openChztModal = function(dataIso) {
    el('chzt-overlay').classList.add('show');
    el('chzt-errors').style.display = 'none';
    el('chzt-toolbar-error').textContent = '';
    loadSession(dataIso ? encodeURIComponent(dataIso) : 'today');
  };

  window.closeChztModal = function() {
    el('chzt-overlay').classList.remove('show');
  };

  window.chztApplyKontenery = function() {
    if (!_session) return;
    var v = parseInt(el('chzt-n-kontenery').value);
    if (isNaN(v) || v < 0 || v > 20) {
      el('chzt-toolbar-error').textContent = 'Oczekuję liczby 0–20';
      return;
    }
    el('chzt-toolbar-error').textContent = '';
    fetch('/api/chzt/session/' + _session.id, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({n_kontenery: v}),
    }).then(function(r){
      if (r.status === 409) {
        return r.json().then(function(b){
          el('chzt-toolbar-error').textContent = b.error || 'Kontenery z danymi — wyczyść najpierw.';
          throw new Error('conflict');
        });
      }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function(resp){
      _session = resp.session;
      renderTable();
      initialStatus();
    }).catch(function(){});
  };

  window.chztFinalize = function() {
    if (!_session) return;
    // Client-side validation
    var localErrors = [];
    _session.punkty.forEach(function(p) {
      var row = getRowValues(p.id);
      if (row.ph === null) {
        localErrors.push({punkt_nazwa: p.punkt_nazwa, reason: 'brak pH'});
      } else {
        var nonnull = ['p1','p2','p3','p4','p5'].filter(function(k){ return row[k] !== null; }).length;
        if (nonnull < 2) {
          localErrors.push({punkt_nazwa: p.punkt_nazwa, reason: 'min. 2 pomiary'});
        }
      }
    });
    var errBox = el('chzt-errors');
    if (localErrors.length > 0) {
      errBox.innerHTML = '<b>Nie można sfinalizować:</b><br>' +
        localErrors.map(function(e){ return '• ' + e.punkt_nazwa + ' — ' + e.reason; }).join('<br>');
      errBox.style.display = 'block';
      highlightInvalid(localErrors);
      return;
    }
    errBox.style.display = 'none';
    var btn = el('chzt-save-btn');
    btn.disabled = true;
    btn.textContent = 'Finalizowanie…';
    fetch('/api/chzt/session/' + _session.id + '/finalize', {method: 'POST'})
      .then(function(r){
        if (r.status === 400) {
          return r.json().then(function(b){
            errBox.innerHTML = '<b>Walidacja serwera:</b><br>' +
              (b.errors || []).map(function(e){ return '• ' + e.punkt_nazwa + ' — ' + e.reason; }).join('<br>');
            errBox.style.display = 'block';
            throw new Error('validation');
          });
        }
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function(resp){
        _session = resp.session;
        renderFinalizedBanner();
        initialStatus();
        btn.textContent = 'Zapisz (finalizuj)';
        btn.disabled = false;
      })
      .catch(function(){
        btn.textContent = 'Zapisz (finalizuj)';
        btn.disabled = false;
      });
  };

  function highlightInvalid(errors) {
    var byName = {};
    errors.forEach(function(e){ byName[e.punkt_nazwa] = e.reason; });
    document.querySelectorAll('#chzt-body tbody tr').forEach(function(tr){
      var pid = parseInt(tr.dataset.pid);
      var p = _session.punkty.find(function(x){ return x.id === pid; });
      if (p && byName[p.punkt_nazwa]) {
        tr.classList.add('invalid');
      } else {
        tr.classList.remove('invalid');
      }
    });
  }
})();
```

- [ ] **Step 2: Usuń stary JS modala z `narzedzia.html`**

W `mbr/templates/technolog/narzedzia.html` znajdź blok `// ═══ ChZT Ścieków Modal ═══` (ok. linia 757) i usuń wszystko od tego komentarza do zamykającego `}` funkcji `chztSave()` — czyli usuń bloki funkcji: `openChztModal`, `closeChztModal`, `chztSetKontenery`, `chztRender`, `chztCalcAvg`, `chztSave` oraz zmienną `_chztKontenery`. Wszystko co między tymi liniami.

**Uwaga:** te funkcje są wewnątrz jednego dużego `<script>` bloku wspólnego z paliwo/narzedzia — zachowaj `<script>...</script>` tagi i wszystkie inne funkcje, usuń tylko ChZT-specific.

- [ ] **Step 3: Dodaj nowy `<script>` tag w `narzedzia.html`**

Na górze `{% block content %}` (albo obok `<link>` z CSS z Task 8), dodaj:

```jinja
<script src="{{ url_for('chzt.static', filename='chzt.js') }}?v=1" defer></script>
```

- [ ] **Step 4: Smoke test — pełny flow**

Run: `python -m mbr.app` (CTRL-C po manualnym teście).

**Checklist manualny** (należy odhaczyć przed commitem):
- [ ] Modal się otwiera, pokazuje dzisiejszą datę, 11 wierszy (hala/rura/kont 1..8/szambiarka)
- [ ] Wpisanie liczby w P1 → po ~400ms status pill zmienia się na "zapisano · HH:MM"
- [ ] Dwa pomiary P1, P2 → kolumna "Średnia" aktualizuje się natychmiast po odpowiedzi
- [ ] F5 → wchodzisz ponownie → wpisane wartości są zachowane
- [ ] Enter w pH → focus skacze do P1; Enter w P5 → focus P1 next row (albo przycisk Zapisz dla ostatniego)
- [ ] Zmiana "Kontenery" z 8 na 10 + "Generuj" → dochodzą kontener 9, 10
- [ ] Zmiana z 10 na 5 bez danych → usuwa; z danymi → error w toolbar
- [ ] Kliknięcie "Zapisz" z pustymi wierszami → czerwone wiersze + komunikat w `chzt-errors`
- [ ] Wypełnienie wszystkich i "Zapisz" → banner "Sfinalizowano" na górze + przycisk znika

- [ ] **Step 5: Testy unit — dalej zielone**

Run: `pytest tests/test_chzt.py -v`
Expected: 47 passed.

- [ ] **Step 6: Commit**

```bash
git add mbr/chzt/static/chzt.js mbr/templates/technolog/narzedzia.html
git commit -m "feat(chzt): rewrite JS with per-row autosave + Enter-nav + status pill"
```

---

## Task 10: Strona historii `/chzt/historia`

**Cel:** Nowa podstrona z listą 10 ostatnich sesji + paginacją. Expand dla P1-P5, expand dla audit, link do edycji.

**Files:**
- Create: `mbr/chzt/templates/chzt_historia.html`
- Modify: `mbr/chzt/routes.py`
- Modify: `mbr/chzt/static/chzt.js` (expand/collapse handlers + openChztModal z param `date`)
- Modify: `mbr/chzt/static/chzt.css` (style kart)
- Modify: `mbr/templates/technolog/narzedzia.html` (dodanie karty "Historia ChZT")
- Modify: `tests/test_chzt.py` (test że strona się renderuje)

- [ ] **Step 1: Failing test — strona historii zwraca 200**

Dopisz do `tests/test_chzt.py`:

```python
def test_historia_page_renders(client, db):
    # Seed 2 sessions
    for d in ["2026-04-17", "2026-04-18"]:
        db.execute(
            "INSERT INTO chzt_sesje (data, n_kontenery, created_at, created_by) "
            "VALUES (?, 0, ?, 1)",
            (d, d + "T10:00:00"),
        )
    db.commit()
    resp = client.get("/chzt/historia")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "2026-04-18" in body
    assert "2026-04-17" in body
```

- [ ] **Step 2: FAIL**

Run: `pytest tests/test_chzt.py::test_historia_page_renders -v`

- [ ] **Step 3: Utwórz `mbr/chzt/templates/chzt_historia.html`**

```jinja
{% extends "base.html" %}

{% block title %}Historia ChZT{% endblock %}

{% block content %}
<link rel="stylesheet" href="{{ url_for('chzt.static', filename='chzt.css') }}?v=1">

<div class="chzt-historia-page">
  <div class="chzt-historia-head">
    <h1>ChZT Ścieków — Historia</h1>
    <div class="chzt-historia-sub">{{ total }} sesji · strona {{ page }}/{{ pages }}</div>
  </div>

  {% if sesje|length == 0 %}
  <div class="chzt-historia-empty">
    Brak zapisanych pomiarów ChZT.
    <a href="{{ url_for('technolog.narzedzia') }}">Zacznij nową sesję</a>
  </div>
  {% else %}
    {% for s in sesje %}
    <div class="chzt-card" data-sid="{{ s.id }}" data-data="{{ s.data }}">
      <div class="chzt-card-head">
        <div>
          <span class="chzt-card-date">{{ s.data }}</span>
          <span class="chzt-card-sub">· {{ s.n_kontenery }} kontenerów</span>
        </div>
        <div>
          {% if s.finalized_at %}
            <span class="chzt-card-status-ok">✓ Sfinalizowano · {{ s.finalized_by_name or '—' }} · {{ s.finalized_at[11:16] }}</span>
          {% else %}
            <span class="chzt-card-status-draft">🟡 Draft{% if s.updated_at_max %} · {{ s.updated_at_max[11:16] }}{% endif %}</span>
          {% endif %}
        </div>
      </div>
      <div class="chzt-card-body" id="chzt-card-body-{{ s.id }}">
        <!-- table loaded on expand -->
        <div class="chzt-card-loading">wczytywanie…</div>
      </div>
      <div class="chzt-card-actions">
        <button class="chzt-btn chzt-btn-sm" onclick="chztHistoriaTogglePomiary({{ s.id }})">Pokaż pomiary P1–P5</button>
        <button class="chzt-btn chzt-btn-sm" onclick="chztHistoriaToggleAudit({{ s.id }})">Pokaż audit</button>
        <button class="chzt-btn chzt-btn-sm" onclick="openChztModal('{{ s.data }}')">Edytuj</button>
      </div>
    </div>
    {% endfor %}

    <div class="chzt-pagination">
      {% if page > 1 %}
      <a href="?page={{ page - 1 }}">← Nowsze</a>
      {% endif %}
      <span>strona {{ page }}/{{ pages }}</span>
      {% if page < pages %}
      <a href="?page={{ page + 1 }}">Starsze →</a>
      {% endif %}
    </div>
  {% endif %}
</div>

{% include "chzt_modal.html" %}

<script src="{{ url_for('chzt.static', filename='chzt.js') }}?v=1" defer></script>
{% endblock %}
```

- [ ] **Step 4: Dodaj route do `mbr/chzt/routes.py`**

```python
from flask import render_template


@chzt_bp.route("/chzt/historia", methods=["GET"])
@role_required(*ROLES_EDIT)
def historia_page():
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1
    with db_session() as db:
        data = list_sessions_paginated(db, page=page, per_page=10)
    return render_template(
        "chzt_historia.html",
        sesje=data["sesje"],
        total=data["total"],
        page=data["page"],
        pages=data["pages"],
    )
```

- [ ] **Step 5: Dodaj style kart do `mbr/chzt/static/chzt.css`**

Dopisz na końcu `chzt.css`:

```css
/* ═══ Historia ChZT ═══ */
.chzt-historia-page {
  max-width: 1040px; margin: 24px auto; padding: 0 20px;
}
.chzt-historia-head h1 { font-size: 22px; margin: 0 0 4px; color: var(--teal); }
.chzt-historia-sub { font-size: 12px; color: var(--text-dim); margin-bottom: 18px; }
.chzt-historia-empty {
  padding: 40px; text-align: center; color: var(--text-dim);
  background: #fff; border: 1px solid var(--border); border-radius: 10px;
}
.chzt-card {
  background: #fff; border: 1px solid var(--border);
  border-left: 3px solid var(--teal); border-radius: 10px;
  margin-bottom: 16px; overflow: hidden;
}
.chzt-card-head {
  padding: 12px 16px; display: flex; justify-content: space-between; align-items: center;
  border-bottom: 1px solid var(--border-subtle, #e8e4dc);
}
.chzt-card-date { font-weight: 700; font-size: 14px; color: var(--teal); }
.chzt-card-sub { font-size: 11px; color: var(--text-dim); margin-left: 6px; }
.chzt-card-status-ok { color: #166534; font-size: 11px; font-weight: 600; }
.chzt-card-status-draft { color: #92400e; font-size: 11px; font-weight: 600; }
.chzt-card-body {
  padding: 12px 16px;
}
.chzt-card-body[data-loaded="no"] { display: none; }
.chzt-card-loading { color: var(--text-dim); font-size: 11px; font-style: italic; }
.chzt-card-actions {
  padding: 10px 16px; border-top: 1px solid var(--border-subtle, #e8e4dc);
  display: flex; gap: 8px;
}
.chzt-pagination {
  display: flex; justify-content: center; gap: 20px; align-items: center;
  margin: 24px 0; font-size: 12px;
}
.chzt-pagination a { color: var(--teal); text-decoration: none; font-weight: 600; }
```

- [ ] **Step 6: Dodaj expand/collapse handlers do `mbr/chzt/static/chzt.js`**

Na końcu `mbr/chzt/static/chzt.js` (w tej samej IIFE, przed `})();`) dopisz:

```javascript
  var _historiaLoaded = {};  // session_id → 'pomiary' | 'audit' | null

  function fetchJson(url) {
    return fetch(url, {headers: {'Accept': 'application/json'}})
      .then(function(r){ if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
  }

  window.chztHistoriaTogglePomiary = function(sid) {
    var body = document.getElementById('chzt-card-body-' + sid);
    if (!body) return;
    if (_historiaLoaded[sid] === 'pomiary' && body.dataset.loaded === 'yes') {
      body.dataset.loaded = 'no';
      body.style.display = 'none';
      _historiaLoaded[sid] = null;
      return;
    }
    body.style.display = 'block';
    body.dataset.loaded = 'yes';
    body.innerHTML = '<div class="chzt-card-loading">wczytywanie…</div>';
    var card = document.querySelector('.chzt-card[data-sid="'+sid+'"]');
    var dataIso = card.dataset.data;
    fetchJson('/api/chzt/session/' + encodeURIComponent(dataIso)).then(function(resp){
      var s = resp.session;
      var html = '<table class="chzt-table"><thead><tr>' +
        '<th>Punkt</th><th>pH</th><th>P1</th><th>P2</th><th>P3</th><th>P4</th><th>P5</th><th>\u015arednia</th>' +
        '</tr></thead><tbody>';
      s.punkty.forEach(function(p){
        html += '<tr><td class="chzt-punkt">' + escapeHtmlHist(p.punkt_nazwa) + '</td>' +
          readCell(p.ph) + readCell(p.p1) + readCell(p.p2) + readCell(p.p3) +
          readCell(p.p4) + readCell(p.p5) +
          '<td class="chzt-avg">' + (p.srednia === null ? '—' : Math.round(p.srednia).toLocaleString('pl-PL')) + '</td>' +
          '</tr>';
      });
      html += '</tbody></table>';
      body.innerHTML = html;
      _historiaLoaded[sid] = 'pomiary';
    }).catch(function(){
      body.innerHTML = '<div class="chzt-card-loading">błąd wczytywania</div>';
    });
  };

  function readCell(v) {
    return '<td>' + (v === null || v === undefined ? '—' : String(v).replace('.', ',')) + '</td>';
  }

  function escapeHtmlHist(s) {
    return String(s).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }

  window.chztHistoriaToggleAudit = function(sid) {
    var body = document.getElementById('chzt-card-body-' + sid);
    if (!body) return;
    if (_historiaLoaded[sid] === 'audit' && body.dataset.loaded === 'yes') {
      body.dataset.loaded = 'no';
      body.style.display = 'none';
      _historiaLoaded[sid] = null;
      return;
    }
    body.style.display = 'block';
    body.dataset.loaded = 'yes';
    body.innerHTML = '<div class="chzt-card-loading">wczytywanie…</div>';
    fetchJson('/api/chzt/session/' + sid + '/audit-history').then(function(resp){
      var entries = resp.entries || [];
      if (entries.length === 0) {
        body.innerHTML = '<div class="chzt-card-loading">brak wpisów audit</div>';
        return;
      }
      var html = '<table class="chzt-table"><thead><tr>' +
        '<th>Kiedy</th><th>Event</th><th>Co</th><th>Zmiana</th>' +
        '</tr></thead><tbody>';
      entries.forEach(function(e){
        var diff = e.diff_json ? JSON.parse(e.diff_json) : null;
        var diffText = diff ? diff.map(function(d){
          return d.pole + ': ' + JSON.stringify(d.stara) + ' → ' + JSON.stringify(d.nowa);
        }).join('; ') : '—';
        html += '<tr><td>' + e.dt.replace('T', ' ') + '</td>' +
          '<td>' + e.event_type + '</td>' +
          '<td>' + (e.entity_label || '') + '</td>' +
          '<td style="font-size:10px">' + escapeHtmlHist(diffText) + '</td></tr>';
      });
      html += '</tbody></table>';
      body.innerHTML = html;
      _historiaLoaded[sid] = 'audit';
    }).catch(function(){
      body.innerHTML = '<div class="chzt-card-loading">błąd wczytywania</div>';
    });
  };
```

- [ ] **Step 7: Domyślnie ukryj `chzt-card-body` — patch w template**

W `chzt_historia.html` zmień:

```jinja
<div class="chzt-card-body" id="chzt-card-body-{{ s.id }}">
```

na:

```jinja
<div class="chzt-card-body" id="chzt-card-body-{{ s.id }}" data-loaded="no" style="display:none;">
```

- [ ] **Step 8: Dodaj kartę "Historia ChZT" w `narzedzia.html`**

W `mbr/templates/technolog/narzedzia.html` znajdź sekcję `{# ═══ ChZT Ścieków ═══ #}` (linia ~67) i **wewnątrz** tej samej `<div class="narz-grid">` dodaj drugą kartę po karcie ChZT:

```jinja
      <a href="{{ url_for('chzt.historia_page') }}" class="narz-card" style="cursor:pointer;">
        <div class="narz-card-icon" style="background:#f3f4f6;color:#6b7280;">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
        </div>
        <div class="narz-card-body">
          <div class="narz-card-name">Historia ChZT</div>
          <div class="narz-card-desc">Poprzednie serie — pH i średnie, pomiary na żądanie</div>
        </div>
      </a>
```

- [ ] **Step 9: Testy + smoke test**

Run: `pytest tests/test_chzt.py -v`
Expected: 48 passed.

Manualny smoke:
- [ ] `/chzt/historia` otwiera się, widać wczorajszą sesję (jeśli istnieje — jeśli nie, dodaj ręcznie w DB lub przez modal z `_fill_all_today`)
- [ ] Kliknięcie "Pokaż pomiary P1–P5" — rozwija tabelę
- [ ] "Pokaż audit" — rozwija listę audit
- [ ] "Edytuj" — otwiera modal z tą datą (wartości z DB, nie dzisiejsze)

- [ ] **Step 10: Commit**

```bash
git add mbr/chzt/templates/chzt_historia.html mbr/chzt/routes.py mbr/chzt/static/chzt.js mbr/chzt/static/chzt.css mbr/templates/technolog/narzedzia.html tests/test_chzt.py
git commit -m "feat(chzt): /chzt/historia page with 10/page pagination + expand for pomiary/audit"
```

---

## Task 11: Remove legacy `POST /api/chzt/save` + cleanup

**Cel:** Stary endpoint plikowy przestaje być używany — usuwamy go razem z importami.

**Files:**
- Modify: `mbr/registry/routes.py`

- [ ] **Step 1: Usuń legacy endpoint**

W `mbr/registry/routes.py` znajdź blok:

```python
@registry_bp.route("/api/chzt/save", methods=["POST"])
@login_required
def api_chzt_save():
    ...
```

(linie 121-154). Usuń cały blok funkcji.

- [ ] **Step 2: Smoke — nic już nie importuje tej funkcji**

Run: `grep -rn "api_chzt_save" mbr/ tests/`
Expected: brak wyników.

Run: `grep -rn "/api/chzt/save" mbr/ tests/`
Expected: brak wyników (nowy modal używa `/api/chzt/pomiar/...`).

- [ ] **Step 3: Testy pełne — nic nie pękło**

Run: `pytest`
Expected: wszystkie testy zielone (baseline + nowe 48).

- [ ] **Step 4: Commit**

```bash
git add mbr/registry/routes.py
git commit -m "chore(chzt): remove legacy POST /api/chzt/save (JSON file writer)"
```

---

## Finish

- [ ] **Final step: Full test run + manual smoke**

Run: `pytest -q`
Expected: all green.

Manualne:
- [ ] `/technolog/narzedzia` pokazuje 2 karty ChZT (modal + Historia)
- [ ] Modal otwiera się z dzisiejszą datą, autosave działa, kolumna Średnia liczy live, finalize idzie do `/chzt/historia` gdzie widać dzień jako "Sfinalizowano"
- [ ] Edytuj z historii → modal z tą datą, edycja wchodzi do audit
- [ ] `GET /api/chzt/day/<today>` na sfinalizowaną sesję zwraca JSON z pH + średnimi (dla zewnętrznego skryptu)
- [ ] Admin może unfinalize (sprawdź via ręczny POST); laborant dostaje 403

---

## Self-review (to be done BEFORE handing off)

**Spec coverage check (manual walkthrough):**

| Spec section | Covered by task |
|---|---|
| Schemat DB (sesje + pomiary + indexy) | Task 1 |
| GET /api/chzt/session/today | Task 2 |
| PUT /api/chzt/pomiar/<id> autosave + srednia + audit | Task 3 |
| PATCH /api/chzt/session/<id> (n_kontenery resize, 409) | Task 4 |
| POST .../finalize + walidacja | Task 5 |
| POST .../unfinalize admin-only | Task 5 |
| GET /api/chzt/session/<data> | Task 6 |
| GET /api/chzt/day/<data> (finalized only, 404 draft) | Task 6 |
| GET /api/chzt/history paginated | Task 6 |
| GET .../audit-history | Task 7 |
| Modal markup/CSS w blueprint | Task 8 |
| JS autosave debounce 400ms + Enter-nav + status pill | Task 9 |
| /chzt/historia page + expand pomiary/audit + Edytuj | Task 10 |
| Usunięcie legacy endpointu | Task 11 |
| Input rozmiar 88×34, inputmode="decimal", bez spinnerów | Task 8 (CSS) + Task 9 (type=text/pattern) |
| Walidacja inline (bez alert) | Task 9 (highlightInvalid + errBox) |
| Wskaźnik autosave w nagłówku | Task 9 (status pill) |
| Audit: 5 typów zdarzeń (created, updated, n_kont_changed, finalized, unfinalized) | Tasks 2, 3, 4, 5 |
| Karta "Historia ChZT" w Narzędziach | Task 10 |

Wszystkie sekcje spec są pokryte przez co najmniej jedno zadanie.

**Ryzyka zaadresowane:**
- Race przy tworzeniu dzisiejszej sesji → `UNIQUE(data)` + `get_or_create_session` sprawdza i zwraca istniejącą (Task 2). Jeśli dwa jednoczesne calls są bardzo rzadkie — `IntegrityError` przy drugim INSERT byłby propagowany — można dodać `try/except IntegrityError` jako follow-up jeśli w prod zaczną się pojawiać.
- Audit volume → `log_event` wywołujemy tylko gdy `changes` (z `diff_fields`) jest niepuste (Task 3 Step 11).
- Export endpoint sesja — laborant się loguje normalnie; dedykowany account będzie w kolejnej iteracji.

**Type consistency:**
- `get_or_create_session(data_iso, created_by, n_kontenery)` → spójne wszędzie (Task 2, 6)
- `update_pomiar(pomiar_id, new_values, updated_by)` → spójne (Task 3, użyte w Task 5 testach)
- `resize_kontenery(session_id, new_n=N)` → spójne (Task 4)
- `POMIAR_FIELDS = ("ph","p1","p2","p3","p4","p5")` → używane w models.py + diff_fields w routes.py
