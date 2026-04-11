# Uwagi końcowe (final batch notes) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dodać jedną notatkę tekstową per szarża/zbiornik/płatkowanie (`uwagi_koncowe`) z pełną historią edycji, widoczną w sekcji analizy końcowej oraz jako kolumnę w rejestrze ukończonych szarż.

**Architecture:** Nowa nullable kolumna `uwagi_koncowe` na `ebr_batches` + append-only tabela `ebr_uwagi_history` (stary stan przed zmianą + action). 4 endpointy w blueprintcie `laborant` (`GET`, `PUT`, `DELETE`, `GET /historia`). Frontend: osobny blok pod listą parametrów w `renderCompletedView()` (textarea + licznik + historia), plus nowa kolumna w registry table (`list_completed_registry` → API → `_buildRegistryRow`).

**Tech Stack:** Flask (blueprint `laborant`), raw `sqlite3`, pytest z in-memory SQLite, vanilla JS w Jinja templates, CSS klasy `.cv-notes*` w `_fast_entry_content.html`.

**Spec:** `docs/superpowers/specs/2026-04-11-uwagi-koncowe-design.md`

---

## File Structure

### New files
- `migrate_uwagi_koncowe.py` — idempotentny skrypt migracji ad-hoc (repo root, zgodnie z konwencją innych skryptów)
- `tests/test_uwagi.py` — pytest test suite dla helperów modelu i routes

### Modified files
- `mbr/models.py` — dopisanie kolumny `uwagi_koncowe` do `CREATE TABLE ebr_batches` + nowa tabela `ebr_uwagi_history` + index w `init_mbr_tables()`
- `mbr/laborant/models.py` — nowe helpery `get_uwagi()`, `save_uwagi()`; rozszerzenie `list_ebr_recent()` o kolumnę `uwagi_koncowe` w SELECT
- `mbr/laborant/routes.py` — 4 nowe endpointy pod `/api/ebr/<id>/uwagi*`
- `mbr/registry/models.py` — dodanie `uwagi_koncowe` do SELECT w `list_completed_registry()`
- `mbr/templates/laborant/_fast_entry_content.html` — nowe klasy CSS `.cv-notes*`, render bloku notatki w `renderCompletedView()`, funkcje JS `loadUwagi()`, `saveUwagi()`, `clearUwagi()`, `_renderUwagiBlock()`
- `mbr/templates/laborant/szarze_list.html` — dodanie kolumny "Uwagi" w `_buildRegistryRow()` i nagłówku tabeli w `renderRegistryTable()`

---

## Task 1: DB schema — kolumna `uwagi_koncowe` + tabela historii

**Files:**
- Modify: `mbr/models.py` (w `init_mbr_tables()` — ebr_batches CREATE TABLE około linii 41-59, nowa tabela za ebr_etapy_status około linii 112)

- [ ] **Step 1: Dodaj kolumnę `uwagi_koncowe` do CREATE TABLE ebr_batches**

W `mbr/models.py` w funkcji `init_mbr_tables()`, w sekcji `CREATE TABLE IF NOT EXISTS ebr_batches` dopisz kolumnę po `przepompowanie_json TEXT`:

```python
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
    status              TEXT NOT NULL DEFAULT 'open'
                        CHECK(status IN ('open', 'completed', 'cancelled')),
    operator            TEXT,
    typ                 TEXT NOT NULL DEFAULT 'szarza'
                        CHECK(typ IN ('szarza', 'zbiornik', 'platkowanie')),
    nastaw              INTEGER,
    przepompowanie_json TEXT,
    uwagi_koncowe       TEXT
);
```

- [ ] **Step 2: Dodaj CREATE TABLE ebr_uwagi_history**

Za blokiem `CREATE TABLE IF NOT EXISTS ebr_etapy_status` (około linii 112) dopisz:

```python
CREATE TABLE IF NOT EXISTS ebr_uwagi_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ebr_id     INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
    tekst      TEXT,
    action     TEXT NOT NULL CHECK(action IN ('create', 'update', 'delete')),
    autor      TEXT NOT NULL,
    dt         TEXT NOT NULL
);
```

Uwaga: cały string `CREATE TABLE` jest częścią jednej dużej wielolinijkowej instrukcji `db.executescript()` — dopisz w tym samym miejscu, nie osobnym wywołaniu.

- [ ] **Step 3: Dodaj index na historii**

Po zamknięciu `db.executescript(...)`, w osobnej linii dopisz:

```python
db.execute(
    "CREATE INDEX IF NOT EXISTS idx_ebr_uwagi_history_ebr "
    "ON ebr_uwagi_history(ebr_id, dt DESC)"
)
```

Znajdź odpowiednie miejsce: po `executescript`, przed sekcją ALTER TABLE (migracje), albo tuż za `_ZBIORNIKI_SEED` loop. Najbezpieczniej: przed pierwszym `try: db.execute("ALTER TABLE ...")`.

- [ ] **Step 4: Dodaj ALTER TABLE migration guard dla istniejących DB**

W sekcji ALTER TABLE ebr_batches (około linii 495+), gdzie są inne idempotentne ALTER TABLE w try/except, dopisz:

```python
try:
    db.execute("ALTER TABLE ebr_batches ADD COLUMN uwagi_koncowe TEXT")
    db.commit()
except Exception:
    pass  # already exists
```

- [ ] **Step 5: Commit**

```bash
git add mbr/models.py
git commit -m "feat: add uwagi_koncowe column + ebr_uwagi_history table"
```

---

## Task 2: Test fixture dla uwag

**Files:**
- Create: `tests/test_uwagi.py`

- [ ] **Step 1: Utwórz plik testowy z fixture**

```python
"""Tests for uwagi_koncowe (final batch notes) feature."""

import sqlite3
from datetime import datetime

import pytest

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    # Add nr_zbiornika column used by some queries
    try:
        conn.execute("ALTER TABLE ebr_batches ADD COLUMN nr_zbiornika TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass
    yield conn
    conn.close()


@pytest.fixture
def ebr_batch(db):
    """Creates a minimal MBR template + open EBR batch, returns ebr_id."""
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "utworzony_przez, dt_utworzenia) VALUES (?, 1, 'active', '[]', '{}', 'test', ?)",
        ("TestProduct", now),
    )
    mbr_id = db.execute(
        "SELECT mbr_id FROM mbr_templates WHERE produkt='TestProduct'"
    ).fetchone()["mbr_id"]
    db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, typ) "
        "VALUES (?, ?, ?, ?, 'open', 'szarza')",
        (mbr_id, "TestProduct__1", "1/2026", now),
    )
    db.commit()
    return db.execute("SELECT ebr_id FROM ebr_batches WHERE batch_id='TestProduct__1'").fetchone()["ebr_id"]


def test_schema_has_uwagi_koncowe_column(db):
    """Regression test: ebr_batches must have uwagi_koncowe column after init."""
    cols = [r["name"] for r in db.execute("PRAGMA table_info(ebr_batches)").fetchall()]
    assert "uwagi_koncowe" in cols


def test_schema_has_history_table(db):
    """Regression test: ebr_uwagi_history table must exist."""
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ebr_uwagi_history'"
    ).fetchall()
    assert len(rows) == 1
```

- [ ] **Step 2: Run tests — verify schema tests pass**

Run: `pytest tests/test_uwagi.py -v`
Expected: 2 passed (test_schema_has_uwagi_koncowe_column, test_schema_has_history_table)

- [ ] **Step 3: Commit**

```bash
git add tests/test_uwagi.py
git commit -m "test: add uwagi_koncowe schema tests"
```

---

## Task 3: `get_uwagi()` helper — empty state

**Files:**
- Modify: `mbr/laborant/models.py` (dopisanie nowego helpera)
- Modify: `tests/test_uwagi.py` (nowy test)

- [ ] **Step 1: Write failing test**

Dopisz w `tests/test_uwagi.py`:

```python
from mbr.laborant.models import get_uwagi


def test_get_uwagi_empty_for_new_batch(db, ebr_batch):
    result = get_uwagi(db, ebr_batch)
    assert result == {
        "tekst": None,
        "dt": None,
        "autor": None,
        "historia": [],
    }
```

- [ ] **Step 2: Run test — verify it fails with ImportError**

Run: `pytest tests/test_uwagi.py::test_get_uwagi_empty_for_new_batch -v`
Expected: FAIL with `ImportError: cannot import name 'get_uwagi'`

- [ ] **Step 3: Implement `get_uwagi` stub**

Dopisz na końcu `mbr/laborant/models.py`:

```python
def get_uwagi(db, ebr_id: int) -> dict:
    """Return current uwagi_koncowe state + history for a batch.

    Returns dict: {tekst, dt, autor, historia}
    - tekst/dt/autor from last history entry (if any) OR None if batch has no notes
    - historia: list of history entries, most recent first
    """
    row = db.execute(
        "SELECT uwagi_koncowe FROM ebr_batches WHERE ebr_id = ?", (ebr_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Batch {ebr_id} not found")

    historia_rows = db.execute(
        "SELECT id, tekst, action, autor, dt FROM ebr_uwagi_history "
        "WHERE ebr_id = ? ORDER BY dt DESC",
        (ebr_id,),
    ).fetchall()
    historia = [dict(r) for r in historia_rows]

    # Current state meta: last history entry's autor/dt, if uwagi is set
    if row["uwagi_koncowe"] is None:
        return {"tekst": None, "dt": None, "autor": None, "historia": historia}

    # Find most recent create/update entry for meta
    last_meta = next((h for h in historia if h["action"] in ("create", "update")), None)
    return {
        "tekst": row["uwagi_koncowe"],
        "dt": last_meta["dt"] if last_meta else None,
        "autor": last_meta["autor"] if last_meta else None,
        "historia": historia,
    }
```

- [ ] **Step 4: Run test — verify it passes**

Run: `pytest tests/test_uwagi.py::test_get_uwagi_empty_for_new_batch -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mbr/laborant/models.py tests/test_uwagi.py
git commit -m "feat: add get_uwagi helper (empty state)"
```

---

## Task 4: `save_uwagi()` — create action

**Files:**
- Modify: `mbr/laborant/models.py`
- Modify: `tests/test_uwagi.py`

- [ ] **Step 1: Write failing test**

Dopisz do `tests/test_uwagi.py`:

```python
from mbr.laborant.models import save_uwagi


def test_save_uwagi_create(db, ebr_batch):
    save_uwagi(db, ebr_batch, "Dodano 500 kg NaOH", "kowalski")

    # Check batch updated
    row = db.execute(
        "SELECT uwagi_koncowe FROM ebr_batches WHERE ebr_id = ?", (ebr_batch,)
    ).fetchone()
    assert row["uwagi_koncowe"] == "Dodano 500 kg NaOH"

    # Check history entry: create action with tekst=NULL
    hist = db.execute(
        "SELECT tekst, action, autor FROM ebr_uwagi_history WHERE ebr_id = ?",
        (ebr_batch,),
    ).fetchall()
    assert len(hist) == 1
    assert hist[0]["tekst"] is None
    assert hist[0]["action"] == "create"
    assert hist[0]["autor"] == "kowalski"
```

- [ ] **Step 2: Run test — verify it fails with ImportError**

Run: `pytest tests/test_uwagi.py::test_save_uwagi_create -v`
Expected: FAIL with `ImportError: cannot import name 'save_uwagi'`

- [ ] **Step 3: Implement `save_uwagi` (create path only)**

Dopisz na końcu `mbr/laborant/models.py`:

```python
def save_uwagi(db, ebr_id: int, tekst: str, autor: str) -> dict:
    """Save uwagi_koncowe with append-only history.

    Action detection:
    - old=NULL, new='' -> no-op
    - old=NULL, new=text -> create
    - old=A,    new=B (B!=A) -> update
    - old=A,    new=A -> no-op
    - old=A,    new='' -> delete

    Raises:
    - ValueError if batch not found, status='cancelled', or text > 500 chars
    """
    tekst = (tekst or "").strip()
    if len(tekst) > 500:
        raise ValueError("Za długie (max 500 znaków)")

    row = db.execute(
        "SELECT uwagi_koncowe, status FROM ebr_batches WHERE ebr_id = ?",
        (ebr_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Batch {ebr_id} not found")
    if row["status"] == "cancelled":
        raise ValueError("Nie można edytować notatki anulowanej szarży")

    old = row["uwagi_koncowe"]
    new = tekst or None  # empty string becomes NULL in storage

    # Detect action
    if old is None and new is None:
        return get_uwagi(db, ebr_id)  # no-op
    if old == new:
        return get_uwagi(db, ebr_id)  # no-op

    if old is None:
        action = "create"
    elif new is None:
        action = "delete"
    else:
        action = "update"

    from datetime import datetime
    now = datetime.now().isoformat(timespec="seconds")

    db.execute(
        "INSERT INTO ebr_uwagi_history (ebr_id, tekst, action, autor, dt) "
        "VALUES (?, ?, ?, ?, ?)",
        (ebr_id, old, action, autor, now),
    )
    db.execute(
        "UPDATE ebr_batches SET uwagi_koncowe = ? WHERE ebr_id = ?",
        (new, ebr_id),
    )
    # Bump sync_seq
    next_seq = db.execute(
        "SELECT COALESCE(MAX(sync_seq), 0) + 1 FROM ebr_batches"
    ).fetchone()[0]
    db.execute(
        "UPDATE ebr_batches SET sync_seq = ? WHERE ebr_id = ?",
        (next_seq, ebr_id),
    )
    db.commit()

    return get_uwagi(db, ebr_id)
```

Uwaga: history entry trzyma *stary* stan (`old`) — przy `create` stary stan to `NULL`. To spójne z tabelą decyzyjną w spec.

- [ ] **Step 4: Run test — verify it passes**

Run: `pytest tests/test_uwagi.py::test_save_uwagi_create -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mbr/laborant/models.py tests/test_uwagi.py
git commit -m "feat: save_uwagi — create action"
```

---

## Task 5: `save_uwagi()` — update action

**Files:**
- Modify: `tests/test_uwagi.py`

- [ ] **Step 1: Write failing test**

```python
def test_save_uwagi_update_stores_old_text(db, ebr_batch):
    save_uwagi(db, ebr_batch, "wersja A", "kowalski")
    save_uwagi(db, ebr_batch, "wersja B", "nowak")

    row = db.execute(
        "SELECT uwagi_koncowe FROM ebr_batches WHERE ebr_id = ?", (ebr_batch,)
    ).fetchone()
    assert row["uwagi_koncowe"] == "wersja B"

    hist = db.execute(
        "SELECT tekst, action, autor FROM ebr_uwagi_history "
        "WHERE ebr_id = ? ORDER BY id",
        (ebr_batch,),
    ).fetchall()
    assert len(hist) == 2
    assert hist[0]["action"] == "create"
    assert hist[0]["tekst"] is None
    assert hist[1]["action"] == "update"
    assert hist[1]["tekst"] == "wersja A"  # old value, not new
    assert hist[1]["autor"] == "nowak"
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_uwagi.py::test_save_uwagi_update_stores_old_text -v`
Expected: PASS (logic from Task 4 already handles this — this test just verifies it)

- [ ] **Step 3: Commit**

```bash
git add tests/test_uwagi.py
git commit -m "test: save_uwagi update action"
```

---

## Task 6: `save_uwagi()` — delete action + whitespace handling

**Files:**
- Modify: `tests/test_uwagi.py`

- [ ] **Step 1: Write failing tests**

```python
def test_save_uwagi_delete(db, ebr_batch):
    save_uwagi(db, ebr_batch, "do skasowania", "kowalski")
    save_uwagi(db, ebr_batch, "", "nowak")

    row = db.execute(
        "SELECT uwagi_koncowe FROM ebr_batches WHERE ebr_id = ?", (ebr_batch,)
    ).fetchone()
    assert row["uwagi_koncowe"] is None

    hist = db.execute(
        "SELECT tekst, action FROM ebr_uwagi_history "
        "WHERE ebr_id = ? ORDER BY id",
        (ebr_batch,),
    ).fetchall()
    assert len(hist) == 2
    assert hist[1]["action"] == "delete"
    assert hist[1]["tekst"] == "do skasowania"  # old value


def test_save_uwagi_noop_on_null_to_empty(db, ebr_batch):
    save_uwagi(db, ebr_batch, "   ", "kowalski")  # whitespace only

    row = db.execute(
        "SELECT uwagi_koncowe FROM ebr_batches WHERE ebr_id = ?", (ebr_batch,)
    ).fetchone()
    assert row["uwagi_koncowe"] is None

    hist = db.execute(
        "SELECT * FROM ebr_uwagi_history WHERE ebr_id = ?", (ebr_batch,)
    ).fetchall()
    assert len(hist) == 0  # nothing recorded


def test_save_uwagi_noop_on_same_text(db, ebr_batch):
    save_uwagi(db, ebr_batch, "ten sam", "kowalski")
    save_uwagi(db, ebr_batch, "ten sam", "nowak")

    hist = db.execute(
        "SELECT COUNT(*) as c FROM ebr_uwagi_history WHERE ebr_id = ?",
        (ebr_batch,),
    ).fetchone()
    assert hist["c"] == 1  # only the initial create


def test_save_uwagi_strips_whitespace(db, ebr_batch):
    save_uwagi(db, ebr_batch, "  z białymi znakami  ", "kowalski")

    row = db.execute(
        "SELECT uwagi_koncowe FROM ebr_batches WHERE ebr_id = ?", (ebr_batch,)
    ).fetchone()
    assert row["uwagi_koncowe"] == "z białymi znakami"
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_uwagi.py -v -k save_uwagi`
Expected: All pass (Task 4 implementation already handles these)

- [ ] **Step 3: Commit**

```bash
git add tests/test_uwagi.py
git commit -m "test: save_uwagi delete + no-op + whitespace cases"
```

---

## Task 7: `save_uwagi()` — validation errors

**Files:**
- Modify: `tests/test_uwagi.py`

- [ ] **Step 1: Write failing tests**

```python
def test_save_uwagi_rejects_too_long(db, ebr_batch):
    long_text = "a" * 501
    with pytest.raises(ValueError, match="500"):
        save_uwagi(db, ebr_batch, long_text, "kowalski")


def test_save_uwagi_allows_exactly_500(db, ebr_batch):
    text = "a" * 500
    save_uwagi(db, ebr_batch, text, "kowalski")
    row = db.execute(
        "SELECT uwagi_koncowe FROM ebr_batches WHERE ebr_id = ?", (ebr_batch,)
    ).fetchone()
    assert row["uwagi_koncowe"] == text


def test_save_uwagi_rejects_cancelled_batch(db, ebr_batch):
    db.execute(
        "UPDATE ebr_batches SET status='cancelled' WHERE ebr_id = ?",
        (ebr_batch,),
    )
    db.commit()
    with pytest.raises(ValueError, match="anulowanej"):
        save_uwagi(db, ebr_batch, "anything", "kowalski")


def test_save_uwagi_rejects_missing_batch(db):
    with pytest.raises(ValueError, match="not found"):
        save_uwagi(db, 9999, "anything", "kowalski")
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_uwagi.py -v -k save_uwagi`
Expected: All pass (Task 4 already validates length, status, and missing batch)

- [ ] **Step 3: Commit**

```bash
git add tests/test_uwagi.py
git commit -m "test: save_uwagi validation errors"
```

---

## Task 8: `get_uwagi()` — populated state with history metadata

**Files:**
- Modify: `tests/test_uwagi.py`

- [ ] **Step 1: Write failing test**

```python
def test_get_uwagi_returns_current_meta_from_history(db, ebr_batch):
    save_uwagi(db, ebr_batch, "pierwsza", "kowalski")
    save_uwagi(db, ebr_batch, "druga", "nowak")

    result = get_uwagi(db, ebr_batch)
    assert result["tekst"] == "druga"
    assert result["autor"] == "nowak"  # most recent update autor
    assert result["dt"] is not None
    assert len(result["historia"]) == 2
    assert result["historia"][0]["action"] == "update"
    assert result["historia"][1]["action"] == "create"


def test_get_uwagi_after_delete(db, ebr_batch):
    save_uwagi(db, ebr_batch, "temporary", "kowalski")
    save_uwagi(db, ebr_batch, "", "nowak")

    result = get_uwagi(db, ebr_batch)
    assert result["tekst"] is None
    assert result["autor"] is None
    assert len(result["historia"]) == 2  # create + delete both logged
    assert result["historia"][0]["action"] == "delete"
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_uwagi.py::test_get_uwagi_returns_current_meta_from_history tests/test_uwagi.py::test_get_uwagi_after_delete -v`
Expected: Both pass (Task 3 implementation already handles this shape)

- [ ] **Step 3: Commit**

```bash
git add tests/test_uwagi.py
git commit -m "test: get_uwagi populated state + after-delete"
```

---

## Task 9: API routes — GET

**Files:**
- Modify: `mbr/laborant/routes.py`
- Modify: `tests/test_uwagi.py`

- [ ] **Step 1: Write failing test**

Dopisz do `tests/test_uwagi.py`:

```python
import pytest
from mbr.app import create_app


@pytest.fixture
def client(monkeypatch, db, ebr_batch):
    """Flask test client with authenticated session."""
    app = create_app()
    app.config["TESTING"] = True

    # Monkeypatch db_session to yield our in-memory db
    from contextlib import contextmanager
    import mbr.db
    import mbr.laborant.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake_db_session)

    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user"] = {"login": "testuser", "rola": "laborant"}
        yield c


def test_api_get_uwagi_empty(client, ebr_batch):
    resp = client.get(f"/api/ebr/{ebr_batch}/uwagi")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"tekst": None, "dt": None, "autor": None, "historia": []}
```

- [ ] **Step 2: Run test — verify it fails**

Run: `pytest tests/test_uwagi.py::test_api_get_uwagi_empty -v`
Expected: FAIL with 404 (route doesn't exist yet)

- [ ] **Step 3: Implement GET route**

Dopisz do `mbr/laborant/routes.py` (importy i nowa trasa):

```python
# Add to imports at top
from mbr.laborant.models import (
    # ... existing imports ...
    get_uwagi,
    save_uwagi,
)

# Add new route (after existing laborant routes)
@laborant_bp.route("/api/ebr/<int:ebr_id>/uwagi")
@login_required
def api_uwagi_get(ebr_id):
    with db_session() as db:
        try:
            data = get_uwagi(db, ebr_id)
        except ValueError:
            return jsonify({"error": "Not found"}), 404
    return jsonify(data)
```

- [ ] **Step 4: Run test**

Run: `pytest tests/test_uwagi.py::test_api_get_uwagi_empty -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mbr/laborant/routes.py tests/test_uwagi.py
git commit -m "feat: GET /api/ebr/<id>/uwagi"
```

---

## Task 10: API routes — PUT

**Files:**
- Modify: `mbr/laborant/routes.py`
- Modify: `tests/test_uwagi.py`

- [ ] **Step 1: Write failing tests**

```python
def test_api_put_uwagi_create(client, ebr_batch):
    resp = client.put(
        f"/api/ebr/{ebr_batch}/uwagi",
        json={"tekst": "Dodano 500 kg NaOH"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["tekst"] == "Dodano 500 kg NaOH"
    assert data["autor"] == "testuser"
    assert len(data["historia"]) == 1
    assert data["historia"][0]["action"] == "create"


def test_api_put_uwagi_too_long(client, ebr_batch):
    resp = client.put(
        f"/api/ebr/{ebr_batch}/uwagi",
        json={"tekst": "a" * 501},
    )
    assert resp.status_code == 400
    assert "500" in resp.get_json()["error"]


def test_api_put_uwagi_cancelled_batch(client, db, ebr_batch):
    db.execute(
        "UPDATE ebr_batches SET status='cancelled' WHERE ebr_id = ?",
        (ebr_batch,),
    )
    db.commit()
    resp = client.put(
        f"/api/ebr/{ebr_batch}/uwagi",
        json={"tekst": "anything"},
    )
    assert resp.status_code == 400
    assert "anulowanej" in resp.get_json()["error"]


def test_api_put_uwagi_missing_batch(client):
    resp = client.put(
        "/api/ebr/99999/uwagi",
        json={"tekst": "whatever"},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_uwagi.py -v -k "test_api_put"`
Expected: All FAIL (route not implemented)

- [ ] **Step 3: Implement PUT route**

Dopisz po `api_uwagi_get` w `mbr/laborant/routes.py`:

```python
@laborant_bp.route("/api/ebr/<int:ebr_id>/uwagi", methods=["PUT"])
@role_required("laborant", "laborant_kj", "laborant_coa", "admin")
def api_uwagi_put(ebr_id):
    data = request.get_json(silent=True) or {}
    tekst = data.get("tekst", "")
    autor = session["user"]["login"]
    with db_session() as db:
        try:
            result = save_uwagi(db, ebr_id, tekst, autor)
        except ValueError as e:
            msg = str(e)
            if "not found" in msg:
                return jsonify({"error": msg}), 404
            return jsonify({"error": msg}), 400
    return jsonify(result)
```

Uwaga: `role_required` zapewnia też `@login_required` (sprawdź istniejący kod dekoratora — w blueprintach jest już tak używane).

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_uwagi.py -v -k "test_api_put"`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add mbr/laborant/routes.py tests/test_uwagi.py
git commit -m "feat: PUT /api/ebr/<id>/uwagi"
```

---

## Task 11: API routes — DELETE + technolog read-only

**Files:**
- Modify: `mbr/laborant/routes.py`
- Modify: `tests/test_uwagi.py`

- [ ] **Step 1: Write failing tests**

```python
def test_api_delete_uwagi(client, ebr_batch):
    client.put(f"/api/ebr/{ebr_batch}/uwagi", json={"tekst": "to delete"})
    resp = client.delete(f"/api/ebr/{ebr_batch}/uwagi")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["tekst"] is None
    assert len(data["historia"]) == 2  # create + delete


def test_api_delete_uwagi_noop(client, ebr_batch):
    """Deleting when no note exists is a no-op, not an error."""
    resp = client.delete(f"/api/ebr/{ebr_batch}/uwagi")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["tekst"] is None
    assert data["historia"] == []


def test_api_get_uwagi_accessible_to_technolog(monkeypatch, db, ebr_batch):
    """GET is available to any authenticated user (technolog read-only)."""
    from mbr.app import create_app
    from contextlib import contextmanager
    import mbr.db
    import mbr.laborant.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake_db_session)

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user"] = {"login": "tech", "rola": "technolog"}
        resp = c.get(f"/api/ebr/{ebr_batch}/uwagi")
        assert resp.status_code == 200


def test_api_put_uwagi_forbidden_for_technolog(monkeypatch, db, ebr_batch):
    """PUT requires laborant/kj/coa/admin — technolog is rejected."""
    from mbr.app import create_app
    from contextlib import contextmanager
    import mbr.db
    import mbr.laborant.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake_db_session)

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user"] = {"login": "tech", "rola": "technolog"}
        resp = c.put(f"/api/ebr/{ebr_batch}/uwagi", json={"tekst": "nope"})
        assert resp.status_code in (403, 302)  # forbid or redirect
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_uwagi.py -v -k "delete_uwagi or technolog"`
Expected: First two FAIL (DELETE route missing), last two PASS (login/role decorators already work for GET)

- [ ] **Step 3: Implement DELETE route**

Dopisz po `api_uwagi_put` w `mbr/laborant/routes.py`:

```python
@laborant_bp.route("/api/ebr/<int:ebr_id>/uwagi", methods=["DELETE"])
@role_required("laborant", "laborant_kj", "laborant_coa", "admin")
def api_uwagi_delete(ebr_id):
    autor = session["user"]["login"]
    with db_session() as db:
        try:
            result = save_uwagi(db, ebr_id, "", autor)
        except ValueError as e:
            msg = str(e)
            if "not found" in msg:
                return jsonify({"error": msg}), 404
            return jsonify({"error": msg}), 400
    return jsonify(result)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_uwagi.py -v -k "delete_uwagi or technolog"`
Expected: All 4 PASS

- [ ] **Step 5: Commit**

```bash
git add mbr/laborant/routes.py tests/test_uwagi.py
git commit -m "feat: DELETE /api/ebr/<id>/uwagi + technolog read-only"
```

---

## Task 12: Registry — dodanie `uwagi_koncowe` do list query

**Files:**
- Modify: `mbr/registry/models.py` (funkcja `list_completed_registry`)
- Modify: `tests/test_registry.py` (dodanie regresji)

- [ ] **Step 1: Write failing test**

Otwórz `tests/test_registry.py` i dopisz (lub stwórz nowy test function):

```python
def test_list_completed_registry_includes_uwagi_koncowe(db):
    """Registry should expose uwagi_koncowe column for the completed list view."""
    from datetime import datetime
    from mbr.registry.models import list_completed_registry

    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "utworzony_przez, dt_utworzenia) VALUES (?, 1, 'active', '[]', '{}', 'test', ?)",
        ("TestProduct", now),
    )
    mbr_id = db.execute(
        "SELECT mbr_id FROM mbr_templates WHERE produkt='TestProduct'"
    ).fetchone()["mbr_id"]
    db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, dt_end, status, typ, uwagi_koncowe) "
        "VALUES (?, 'TP__1', '1/2026', ?, ?, 'completed', 'szarza', 'nota testowa')",
        (mbr_id, now, now),
    )
    db.commit()

    result = list_completed_registry(db, produkt="TestProduct")
    assert len(result) == 1
    assert result[0]["uwagi_koncowe"] == "nota testowa"
```

- [ ] **Step 2: Run test — verify it fails**

Run: `pytest tests/test_registry.py::test_list_completed_registry_includes_uwagi_koncowe -v`
Expected: FAIL with KeyError or missing key `uwagi_koncowe`

- [ ] **Step 3: Update `list_completed_registry` SELECT**

W `mbr/registry/models.py` zmień SELECT:

```python
sql = """
    SELECT eb.ebr_id, eb.batch_id, eb.nr_partii, mt.produkt, eb.dt_end, eb.typ, eb.nr_zbiornika, eb.uwagi_koncowe
    FROM ebr_batches eb
    JOIN mbr_templates mt ON mt.mbr_id = eb.mbr_id
    WHERE eb.status = 'completed'
"""
```

- [ ] **Step 4: Run test**

Run: `pytest tests/test_registry.py::test_list_completed_registry_includes_uwagi_koncowe -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mbr/registry/models.py tests/test_registry.py
git commit -m "feat: expose uwagi_koncowe in registry list"
```

---

## Task 13: Migration script

**Files:**
- Create: `migrate_uwagi_koncowe.py`

- [ ] **Step 1: Utwórz skrypt migracji**

```python
"""Migration: add uwagi_koncowe column + ebr_uwagi_history table.

Idempotent — safe to run multiple times.

Usage:
    python migrate_uwagi_koncowe.py
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "batch_db.sqlite"


def main():
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    cols = [r[1] for r in conn.execute("PRAGMA table_info(ebr_batches)").fetchall()]
    if "uwagi_koncowe" not in cols:
        conn.execute("ALTER TABLE ebr_batches ADD COLUMN uwagi_koncowe TEXT")
        print("Added uwagi_koncowe column to ebr_batches")
    else:
        print("uwagi_koncowe column already exists")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS ebr_uwagi_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ebr_id     INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
            tekst      TEXT,
            action     TEXT NOT NULL CHECK(action IN ('create', 'update', 'delete')),
            autor      TEXT NOT NULL,
            dt         TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ebr_uwagi_history_ebr "
        "ON ebr_uwagi_history(ebr_id, dt DESC)"
    )
    conn.commit()
    conn.close()
    print("OK — uwagi_koncowe migration applied")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry-run test (opcjonalnie)**

Run: `python migrate_uwagi_koncowe.py`
Expected: `OK — uwagi_koncowe migration applied` (na świeżej DB już zawiera kolumnę dzięki `init_mbr_tables`, ale skrypt jest idempotentny)

- [ ] **Step 3: Commit**

```bash
git add migrate_uwagi_koncowe.py
git commit -m "feat: standalone migration script for uwagi_koncowe"
```

---

## Task 14: Frontend — CSS bloku notatki

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Dopisz klasy CSS**

W `mbr/templates/laborant/_fast_entry_content.html`, po sekcji `.cv-val-err` i przed `.cv-p-norm` (około linii 486, tuż po klasach dla parametrów), dopisz:

```css
/* ═══ UWAGI KOŃCOWE — final batch notes block ═══ */
.cv-notes {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
    margin-bottom: 12px;
}
.cv-notes-head {
    padding: 9px 16px;
    background: var(--surface-alt);
    border-bottom: 1px solid var(--border);
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--text-dim);
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.cv-notes-body { padding: 12px 16px; }
.cv-notes-textarea {
    width: 100%;
    min-height: 42px;
    font-family: var(--font);
    font-size: 13px;
    line-height: 1.45;
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 10px;
    background: white;
    resize: vertical;
    box-sizing: border-box;
    transition: border-color 0.14s ease;
}
.cv-notes-textarea:focus { outline: none; border-color: var(--teal); }
.cv-notes-textarea[readonly] {
    background: transparent;
    border-color: transparent;
    resize: none;
    padding: 4px 0;
}
.cv-notes-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin-top: 8px;
}
.cv-notes-counter {
    font-size: 10px;
    color: var(--text-dim);
    font-family: var(--mono);
}
.cv-notes-counter.over { color: var(--red); font-weight: 700; }
.cv-notes-actions { display: flex; gap: 6px; }
.cv-notes-btn {
    padding: 5px 12px;
    font-size: 11px;
    font-weight: 600;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: white;
    color: var(--text-sec);
    cursor: pointer;
    transition: all 0.12s;
}
.cv-notes-btn:hover { border-color: var(--text-dim); color: var(--text); }
.cv-notes-btn.primary { background: var(--teal); color: white; border-color: var(--teal); }
.cv-notes-btn.primary:hover { filter: brightness(1.08); }
.cv-notes-btn.danger { color: var(--red); border-color: var(--red); }
.cv-notes-btn.danger:hover { background: var(--red); color: white; }
.cv-notes-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.cv-notes-history {
    border-top: 1px solid var(--border-subtle, #f0ece4);
    padding: 10px 16px 12px;
    background: var(--surface-alt);
}
.cv-notes-history-title {
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-dim);
    margin-bottom: 6px;
}
.cv-notes-history-item {
    font-size: 11px;
    color: var(--text-sec);
    padding: 3px 0;
    line-height: 1.4;
}
.cv-notes-history-meta {
    color: var(--text-dim);
    font-family: var(--mono);
    font-size: 10px;
    margin-right: 6px;
}
.cv-notes-add-btn {
    border: 1px dashed var(--border);
    background: transparent;
    color: var(--text-dim);
    padding: 6px 12px;
    font-size: 11px;
    font-weight: 600;
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.14s;
}
.cv-notes-add-btn:hover { border-color: var(--teal); color: var(--teal); }
```

- [ ] **Step 2: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: CSS for uwagi_koncowe block"
```

---

## Task 15: Frontend — JS render + API calls

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Dopisz funkcje JS**

W `<script>` w `_fast_entry_content.html`, bezpośrednio przed `function renderCompletedView()` (około linii 867), dopisz:

```javascript
// ═══ UWAGI KOŃCOWE ═══
var _uwagiState = null;  // { tekst, dt, autor, historia }
var _uwagiSaveTimer = null;

function _renderUwagiBlock(canEdit) {
    var html = '<div class="cv-notes" id="cv-notes-block">';
    html += '<div class="cv-notes-head"><span>UWAGI KOŃCOWE</span>';
    if (canEdit && _uwagiState && _uwagiState.tekst) {
        html += '<button class="cv-notes-btn" onclick="_uwagiToggleEdit()">edytuj</button>';
    }
    html += '</div>';
    html += '<div class="cv-notes-body">';

    var tekst = _uwagiState ? (_uwagiState.tekst || '') : '';
    var isEmpty = !tekst;
    var readonly = !canEdit || (isEmpty ? false : !_uwagiEditMode);

    if (isEmpty && !canEdit) {
        html += '<div style="color:var(--text-dim);font-style:italic;font-size:12px;">— brak notatek —</div>';
    } else if (isEmpty && canEdit && !_uwagiEditMode) {
        html += '<button class="cv-notes-add-btn" onclick="_uwagiStartAdd()">📝 + Dodaj notatkę</button>';
    } else {
        html += '<textarea class="cv-notes-textarea" id="cv-notes-text" maxlength="500"' +
                (readonly ? ' readonly' : '') +
                ' oninput="_uwagiOnInput()">' + esc(tekst) + '</textarea>';
        if (canEdit) {
            html += '<div class="cv-notes-footer">' +
                    '<span class="cv-notes-counter" id="cv-notes-counter">' + tekst.length + ' / 500</span>' +
                    '<div class="cv-notes-actions">' +
                    '<button class="cv-notes-btn danger" onclick="_uwagiClear()">Wyczyść</button>' +
                    '<button class="cv-notes-btn primary" id="cv-notes-save-btn" onclick="_uwagiSave()">Zapisz</button>' +
                    '</div></div>';
        }
    }
    html += '</div>';

    // Historia
    if (_uwagiState && _uwagiState.historia && _uwagiState.historia.length > 0) {
        html += '<div class="cv-notes-history">';
        html += '<div class="cv-notes-history-title">Historia (' + _uwagiState.historia.length + ')</div>';
        _uwagiState.historia.forEach(function(h) {
            var dt = h.dt ? h.dt.substring(0, 16).replace('T', ' ') : '';
            var label = h.action === 'create' ? '[pierwszy wpis]' :
                       (h.action === 'delete' ? '[usunięto]' : '');
            var preview = h.tekst ? esc(h.tekst.length > 60 ? h.tekst.slice(0, 57) + '…' : h.tekst) : '';
            html += '<div class="cv-notes-history-item" title="' + esc(h.tekst || '') + '">' +
                    '<span class="cv-notes-history-meta">' + dt + ' — ' + esc(h.autor) + '</span>' +
                    ' ' + label + ' ' + preview +
                    '</div>';
        });
        html += '</div>';
    }

    html += '</div>';
    return html;
}

var _uwagiEditMode = false;

function _uwagiStartAdd() {
    _uwagiEditMode = true;
    var block = document.getElementById('cv-notes-block');
    if (block) block.outerHTML = _renderUwagiBlock(true);
    var ta = document.getElementById('cv-notes-text');
    if (ta) { ta.focus(); }
}

function _uwagiToggleEdit() {
    _uwagiEditMode = !_uwagiEditMode;
    var block = document.getElementById('cv-notes-block');
    if (block) block.outerHTML = _renderUwagiBlock(true);
    if (_uwagiEditMode) {
        var ta = document.getElementById('cv-notes-text');
        if (ta) ta.focus();
    }
}

function _uwagiOnInput() {
    var ta = document.getElementById('cv-notes-text');
    var counter = document.getElementById('cv-notes-counter');
    var saveBtn = document.getElementById('cv-notes-save-btn');
    if (!ta || !counter) return;
    var len = ta.value.length;
    counter.textContent = len + ' / 500';
    counter.classList.toggle('over', len > 500);
    if (saveBtn) saveBtn.disabled = len > 500;
    // Debounced autosave
    if (_uwagiSaveTimer) clearTimeout(_uwagiSaveTimer);
    _uwagiSaveTimer = setTimeout(function() { _uwagiSave(); }, 800);
}

async function loadUwagi(ebrId) {
    try {
        var resp = await fetch('/api/ebr/' + ebrId + '/uwagi');
        if (!resp.ok) throw new Error('fetch failed');
        _uwagiState = await resp.json();
    } catch (e) {
        _uwagiState = { tekst: null, dt: null, autor: null, historia: [] };
    }
}

async function _uwagiSave() {
    var ta = document.getElementById('cv-notes-text');
    if (!ta) return;
    var tekst = ta.value;
    if (tekst.length > 500) return;
    try {
        var resp = await fetch('/api/ebr/' + _currentEbrId + '/uwagi', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tekst: tekst }),
        });
        if (!resp.ok) {
            var err = await resp.json();
            alert(err.error || 'Błąd zapisu notatki');
            return;
        }
        _uwagiState = await resp.json();
        _uwagiEditMode = false;
        var block = document.getElementById('cv-notes-block');
        if (block) block.outerHTML = _renderUwagiBlock(userRola !== 'technolog');
    } catch (e) {
        alert('Błąd zapisu: ' + e.message);
    }
}

async function _uwagiClear() {
    if (!confirm('Na pewno usunąć notatkę?')) return;
    try {
        var resp = await fetch('/api/ebr/' + _currentEbrId + '/uwagi', { method: 'DELETE' });
        if (!resp.ok) {
            var err = await resp.json();
            alert(err.error || 'Błąd usuwania');
            return;
        }
        _uwagiState = await resp.json();
        _uwagiEditMode = false;
        var block = document.getElementById('cv-notes-block');
        if (block) block.outerHTML = _renderUwagiBlock(userRola !== 'technolog');
    } catch (e) {
        alert('Błąd: ' + e.message);
    }
}
```

Uwaga: `_currentEbrId` — ta zmienna musi istnieć gdzieś w pliku. Sprawdź czy jest (grep w pliku za `_currentEbrId`). Jeśli nie — użyj `{{ ebr.ebr_id }}` albo innej istniejącej zmiennej `ebrId` / `currentEbr.ebr_id`. Jeśli fast_entry ma state objekt z ID szarży, reference do niego — np. `currentEbr` bądź w templeicie `{{ ebr.ebr_id }}`.

- [ ] **Step 2: Sprawdź zmienną currentEbrId**

Run: `grep -n "_currentEbrId\|ebr_id\|currentEbr" mbr/templates/laborant/_fast_entry_content.html | head -30`
Expected: zidentyfikuj zmienną trzymającą ID aktywnej szarży. Podmień `_currentEbrId` w kodzie z Kroku 1 na właściwą.

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: JS render + API calls for uwagi_koncowe"
```

---

## Task 16: Frontend — wstawienie bloku do `renderCompletedView()`

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Wywołanie `loadUwagi` przed renderowaniem**

W funkcji `loadBatch` (albo gdzie wywoływane jest `renderCompletedView`), przed `renderCompletedView()`, dopisz:

```javascript
await loadUwagi(ebrId);  // ebrId — zmień na właściwą zmienną, zidentyfikowaną w Task 15
```

- [ ] **Step 2: Wstaw blok uwag do `renderCompletedView`**

W `renderCompletedView()` (około linii 958), po linii `var html = heroHtml + paramsHtml;`, dopisz:

```javascript
var canEditUwagi = userRola !== 'technolog' && statusBatch !== 'cancelled';
html += _renderUwagiBlock(canEditUwagi);
```

(`statusBatch` — jeśli zmienna o innej nazwie, podmień; szukaj `status` w kontekście szarży — prawdopodobnie dostępne przez `data.status` albo `batch.status`.)

- [ ] **Step 3: Manual browser test**

Run: `python -m mbr.app`
Open browser: `http://localhost:5001/laborant/szarze`, zaloguj się, otwórz ukończoną szarżę, sprawdź:
- Widoczny blok "UWAGI KOŃCOWE"
- Przy braku notatki — przycisk "📝 + Dodaj notatkę"
- Po kliknięciu otwiera textarea
- Wpisanie + czekanie 800ms zapisuje (lub klik "Zapisz")
- Historia pokazuje się po pierwszym zapisie
- Refresh strony — notatka i historia są zachowane

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: render uwagi_koncowe block in renderCompletedView"
```

---

## Task 17: Frontend — kolumna w registry table

**Files:**
- Modify: `mbr/templates/laborant/szarze_list.html`

- [ ] **Step 1: Dopisz nagłówek kolumny**

W `renderRegistryTable()` (około linii 1311), po:

```javascript
html += '<th class="th-date">Data</th>';
```

dopisz:

```javascript
html += '<th class="th-uwagi" style="min-width:180px;max-width:280px;">Uwagi</th>';
```

- [ ] **Step 2: Dopisz komórkę w `_buildRegistryRow()`**

W `_buildRegistryRow()` (około linii 1349), po:

```javascript
html += '<td class="td-date">' + dtStr + '</td>';
```

dopisz:

```javascript
// Uwagi końcowe
var uwagi = b.uwagi_koncowe || '';
var uwagiShort = uwagi.length > 50 ? uwagi.slice(0, 47) + '…' : uwagi;
var uwagiCell = uwagi
    ? '<td class="td-uwagi" style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-sec);font-size:12px;" title="' + uwagi.replace(/"/g, '&quot;') + '">' + uwagiShort + '</td>'
    : '<td class="td-uwagi" style="color:var(--text-dim);">—</td>';
html += uwagiCell;
```

- [ ] **Step 3: Manual browser test**

Run: `python -m mbr.app`
Open browser: `/laborant/szarze` → "Rejestr ukończonych" → sprawdź:
- Nowa kolumna "Uwagi" widoczna w nagłówku
- Szarże z notatką pokazują skrócony tekst (tooltip na hover — pełny)
- Szarże bez notatki pokazują `—`
- Kolumna mieści się i nie psuje layoutu

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/szarze_list.html
git commit -m "feat: Uwagi column in completed batches registry"
```

---

## Task 18: Pełny test suite run

- [ ] **Step 1: Uruchom wszystkie testy**

Run: `pytest -v`
Expected: wszystkie testy zielone. W szczególności:
- `tests/test_uwagi.py` — 16+ tests pass
- `tests/test_registry.py` — nowy test uwagi passes
- Żaden istniejący test nie jest złamany

- [ ] **Step 2: Jeśli coś się wysypuje**

Najczęstsze problemy:
- Import `create_app` w testach — sprawdź czy `mbr/app.py` eksportuje `create_app`
- `db_session` monkeypatch — sprawdź ścieżki modułów (`mbr.db` vs `mbr.laborant.routes`)
- `session["user"]` w testach — sprawdź strukturę sesji w innych testach (np. `test_auth.py`)

Napraw, commit każdą poprawkę osobno.

---

## Task 19: Migration na działającą bazę

- [ ] **Step 1: Backup DB**

Run: `cp data/batch_db.sqlite data/batch_db.sqlite.bak-uwagi-migration`

- [ ] **Step 2: Uruchom migrację**

Run: `python migrate_uwagi_koncowe.py`
Expected: `Added uwagi_koncowe column to ebr_batches` + `OK — uwagi_koncowe migration applied`

- [ ] **Step 3: Weryfikacja**

Run: `sqlite3 data/batch_db.sqlite "PRAGMA table_info(ebr_batches)" | grep uwagi_koncowe`
Expected: wiersz z `uwagi_koncowe|TEXT|0||0`

Run: `sqlite3 data/batch_db.sqlite ".schema ebr_uwagi_history"`
Expected: pełen `CREATE TABLE ebr_uwagi_history ...`

- [ ] **Step 4: Manual smoke test**

Run: `python -m mbr.app`
Otwórz ukończoną szarżę w przeglądarce, dodaj notatkę, zapisz, odśwież, sprawdź że się zachowała.

---

## Self-Review — sprawdzenie planu względem spec-a

Sekcja kontrolna — sprawdź, czy każdy wymóg ze spec-a ma task:

| Spec section | Task(s) | Status |
|---|---|---|
| Nowa kolumna `uwagi_koncowe` | 1 | ✓ |
| Nowa tabela `ebr_uwagi_history` + index | 1 | ✓ |
| `init_mbr_tables()` update | 1 | ✓ |
| Migration script | 13 | ✓ |
| `get_uwagi()` helper | 3, 8 | ✓ |
| `save_uwagi()` z action detection | 4, 5, 6, 7 | ✓ |
| `save_uwagi()` sync_seq bump | 4 | ✓ |
| `GET /api/ebr/<id>/uwagi` | 9 | ✓ |
| `PUT /api/ebr/<id>/uwagi` | 10 | ✓ |
| `DELETE /api/ebr/<id>/uwagi` | 11 | ✓ |
| `GET` dostępne dla wszystkich ról | 11 | ✓ |
| `PUT`/`DELETE` role_required | 10, 11 | ✓ |
| Walidacja długości, cancelled, missing | 7, 10 | ✓ |
| Frontend CSS `.cv-notes*` | 14 | ✓ |
| Frontend JS render + API | 15, 16 | ✓ |
| Blok pod listą parametrów (b=2) | 16 | ✓ |
| Historia zawsze widoczna (c=2) | 15 | ✓ |
| Licznik 500 znaków | 14, 15 | ✓ |
| Tryb view/edit/write | 15, 16 | ✓ |
| Szarża cancelled read-only | 16 | ✓ |
| Technolog read-only | 15, 16 | ✓ |
| Registry list column | 12, 17 | ✓ |
| Truncate 50 chars + tooltip | 17 | ✓ |
| Kolumna we wszystkich typach (szarza/zbiornik/płatkowanie) | 12, 17 | ✓ |
| Testy helpers + routes | 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12 | ✓ |

**Poza zakresem (YAGNI) — zgodnie ze spec:** filtrowanie/wyszukiwanie po uwagach, export, notyfikacje, szablony, linki do innych szarż jako relacje, timeline, załączniki, cert rendering, kolorowanie wierszy listy — żaden task nie wprowadza tych funkcji, zgodnie.

**Placeholder scan:** brak TODO/TBD/"implement later". Każdy krok zawiera konkretny kod.

**Type consistency:** `save_uwagi(db, ebr_id, tekst, autor)` używane spójnie w Task 4 i w routes w Task 10/11. `get_uwagi(db, ebr_id)` zwraca `{tekst, dt, autor, historia}` w Task 3 i routes. `_uwagiState` jako globalny `{tekst, dt, autor, historia}` — konsystentnie z API response.

**Jedno wymaga weryfikacji w trakcie implementacji:** Task 15 Step 2 — nazwa zmiennej dla ID aktywnej szarży w istniejącym kodzie (`_currentEbrId` vs `ebrId` vs `{{ ebr.ebr_id }}`). To `unknown at plan-time` — engineer musi znaleźć i podmienić. Udokumentowane w kroku.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-11-uwagi-koncowe.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — ja dispatchuję świeżego subagenta per task, review między taskami, szybka iteracja (używa skilla `superpowers:subagent-driven-development`)
2. **Inline Execution** — wykonuję taski w tej sesji, z checkpointami do review (używa skilla `superpowers:executing-plans`)

Którą wybierasz?
