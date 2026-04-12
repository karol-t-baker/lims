# Analytical Stages Builder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a gate-based analytical pipeline builder where admins define analytical stages (etapy analityczne) with parameters, gate conditions, and correction types, then assign them to products as ordered pipelines. Laborants execute analyses in a stage-by-stage fast entry with automatic gate evaluation and correction workflows.

**Architecture:** New blueprint `pipeline` under `mbr/pipeline/` with its own models, routes, and templates. New normalized tables replace the JSON-blob approach. Existing `parametry_analityczne` table is untouched. Migration script converts `parametry_etapy` data to new schema. Fast entry v2 reads pipeline config instead of `parametry_lab` JSON.

**Tech Stack:** Flask/Jinja2, SQLite (raw sqlite3), vanilla JS, existing CSS conventions from `mbr/static/style.css`

---

## File Structure

### New files to create:
```
mbr/pipeline/__init__.py          — Blueprint registration
mbr/pipeline/models.py            — DB helpers for new tables (catalog CRUD, pipeline CRUD, EBR session/pomiar/korekta)
mbr/pipeline/routes.py            — Admin API routes for builder UI
mbr/pipeline/lab_routes.py        — Laborant routes for fast entry v2
mbr/templates/pipeline/
  etapy_katalog.html              — Admin: list/create analytical stages
  etap_edit.html                  — Admin: edit stage (params, gates, corrections)
  pipeline_edit.html              — Admin: product pipeline editor
  fast_entry_v2.html              — Laborant: stage-based fast entry shell
  _fast_entry_v2_content.html     — Laborant: AJAX partial for stage content
scripts/migrate_parametry_etapy.py — One-time migration from old to new tables
tests/test_pipeline_models.py     — Unit tests for pipeline models
tests/test_pipeline_routes.py     — Integration tests for admin API
tests/test_pipeline_lab.py        — Integration tests for laborant flow
```

### Files to modify:
```
mbr/models.py                     — Add new table CREATE statements to init_mbr_tables()
mbr/app.py                        — Register pipeline blueprint
```

---

## Task 1: Database Schema — New Tables in init_mbr_tables()

**Files:**
- Modify: `mbr/models.py` (add CREATE TABLE statements after existing ones, ~line 495)
- Test: `tests/test_pipeline_models.py`

- [ ] **Step 1: Write failing test — tables exist after init**

```python
# tests/test_pipeline_models.py
import sqlite3
import pytest
from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def test_new_pipeline_tables_exist(db):
    tables = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    for t in [
        "etapy_analityczne", "etap_parametry", "produkt_pipeline",
        "produkt_etap_limity", "etap_warunki", "etap_korekty_katalog",
        "ebr_etap_sesja", "ebr_pomiar", "ebr_korekta_v2",
    ]:
        assert t in tables, f"Missing table: {t}"


def test_etapy_analityczne_columns(db):
    cols = [r[1] for r in db.execute("PRAGMA table_info(etapy_analityczne)").fetchall()]
    assert "kod" in cols
    assert "typ_cyklu" in cols
    assert "aktywny" in cols


def test_etapy_analityczne_unique_kod(db):
    db.execute("INSERT INTO etapy_analityczne (kod, nazwa) VALUES ('test', 'Test')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO etapy_analityczne (kod, nazwa) VALUES ('test', 'Test2')")


def test_etap_parametry_fk(db):
    db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa) VALUES (1, 'amid', 'Amid')")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (1, 'ph', 'pH', 'bezposredni')")
    db.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (1, 1, 1)")
    row = db.execute("SELECT * FROM etap_parametry WHERE etap_id=1").fetchone()
    assert row is not None


def test_ebr_etap_sesja_unique_constraint(db):
    db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa) VALUES (1, 'amid', 'Amid')")
    db.execute("""INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia)
                  VALUES (1, 'Test', 1, '2026-01-01')""")
    db.execute("""INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start)
                  VALUES (1, 1, 'T-1', '1/2026', '2026-01-01')""")
    db.execute("""INSERT INTO ebr_etap_sesja (ebr_id, etap_id, runda) VALUES (1, 1, 1)""")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("""INSERT INTO ebr_etap_sesja (ebr_id, etap_id, runda) VALUES (1, 1, 1)""")


def test_ebr_pomiar_unique_constraint(db):
    db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa) VALUES (1, 'amid', 'Amid')")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (1, 'ph', 'pH', 'bezposredni')")
    db.execute("""INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia)
                  VALUES (1, 'Test', 1, '2026-01-01')""")
    db.execute("""INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start)
                  VALUES (1, 1, 'T-1', '1/2026', '2026-01-01')""")
    db.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda) VALUES (1, 1, 1, 1)")
    db.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, dt_wpisu, wpisal) VALUES (1, 1, 7.5, '2026-01-01', 'lab1')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, dt_wpisu, wpisal) VALUES (1, 1, 7.6, '2026-01-01', 'lab1')")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pipeline_models.py -v
```
Expected: FAIL — tables don't exist yet.

- [ ] **Step 3: Add CREATE TABLE statements to init_mbr_tables()**

In `mbr/models.py`, after the `parametry_etapy` CREATE TABLE block (~line 495), add:

```python
    # --- Pipeline builder tables (analytical stages) ---
    db.execute("""
        CREATE TABLE IF NOT EXISTS etapy_analityczne (
            id                  INTEGER PRIMARY KEY,
            kod                 TEXT NOT NULL UNIQUE,
            nazwa               TEXT NOT NULL,
            opis                TEXT,
            typ_cyklu           TEXT NOT NULL DEFAULT 'jednorazowy'
                                CHECK(typ_cyklu IN ('jednorazowy', 'cykliczny')),
            aktywny             INTEGER DEFAULT 1,
            kolejnosc_domyslna  INTEGER DEFAULT 0
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS etap_parametry (
            id              INTEGER PRIMARY KEY,
            etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
            parametr_id     INTEGER NOT NULL REFERENCES parametry_analityczne(id),
            kolejnosc       INTEGER DEFAULT 0,
            min_limit       REAL,
            max_limit       REAL,
            nawazka_g       REAL,
            precision       INTEGER,
            target          REAL,
            wymagany        INTEGER DEFAULT 0,
            grupa           TEXT DEFAULT 'lab',
            formula         TEXT,
            sa_bias         REAL,
            krok            INTEGER,
            UNIQUE(etap_id, parametr_id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS produkt_pipeline (
            id              INTEGER PRIMARY KEY,
            produkt         TEXT NOT NULL,
            etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
            kolejnosc       INTEGER NOT NULL,
            UNIQUE(produkt, etap_id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS produkt_etap_limity (
            id              INTEGER PRIMARY KEY,
            produkt         TEXT NOT NULL,
            etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
            parametr_id     INTEGER NOT NULL REFERENCES parametry_analityczne(id),
            min_limit       REAL,
            max_limit       REAL,
            nawazka_g       REAL,
            precision       INTEGER,
            target          REAL,
            UNIQUE(produkt, etap_id, parametr_id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS etap_warunki (
            id              INTEGER PRIMARY KEY,
            etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
            parametr_id     INTEGER NOT NULL REFERENCES parametry_analityczne(id),
            operator        TEXT NOT NULL CHECK(operator IN ('<', '<=', '>=', '>', 'between', '=')),
            wartosc         REAL,
            wartosc_max     REAL,
            opis_warunku    TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS etap_korekty_katalog (
            id              INTEGER PRIMARY KEY,
            etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
            substancja      TEXT NOT NULL,
            jednostka       TEXT DEFAULT 'kg',
            wykonawca       TEXT NOT NULL DEFAULT 'produkcja'
                            CHECK(wykonawca IN ('laborant', 'produkcja')),
            kolejnosc       INTEGER DEFAULT 0,
            formula_ilosc   TEXT,
            formula_zmienne TEXT,
            formula_opis    TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS ebr_etap_sesja (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ebr_id          INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
            etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
            runda           INTEGER NOT NULL DEFAULT 1,
            status          TEXT NOT NULL DEFAULT 'w_trakcie'
                            CHECK(status IN ('w_trakcie', 'ok', 'poza_limitem', 'oczekuje_korekty')),
            dt_start        TEXT,
            dt_end          TEXT,
            laborant        TEXT,
            decyzja         TEXT CHECK(decyzja IN ('przejscie', 'korekta')),
            komentarz       TEXT,
            UNIQUE(ebr_id, etap_id, runda)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS ebr_pomiar (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sesja_id        INTEGER NOT NULL REFERENCES ebr_etap_sesja(id),
            parametr_id     INTEGER NOT NULL REFERENCES parametry_analityczne(id),
            wartosc         REAL,
            min_limit       REAL,
            max_limit       REAL,
            w_limicie       INTEGER,
            is_manual       INTEGER NOT NULL DEFAULT 1,
            dt_wpisu        TEXT NOT NULL,
            wpisal          TEXT NOT NULL,
            UNIQUE(sesja_id, parametr_id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS ebr_korekta_v2 (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sesja_id        INTEGER NOT NULL REFERENCES ebr_etap_sesja(id),
            korekta_typ_id  INTEGER NOT NULL REFERENCES etap_korekty_katalog(id),
            ilosc           REAL,
            zalecil         TEXT,
            wykonawca_info  TEXT,
            dt_zalecenia    TEXT,
            dt_wykonania    TEXT,
            status          TEXT NOT NULL DEFAULT 'zalecona'
                            CHECK(status IN ('zalecona', 'wykonana', 'anulowana'))
        )
    """)
```

Note: using `ebr_korekta_v2` to avoid collision with existing `ebr_korekty` table.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_pipeline_models.py -v
```
Expected: all PASS.

- [ ] **Step 5: Verify existing tests still pass**

```bash
pytest --tb=short -q
```
Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add mbr/models.py tests/test_pipeline_models.py
git commit -m "feat: add pipeline builder schema (9 new tables)"
```

---

## Task 2: Pipeline Models — Catalog CRUD

**Files:**
- Create: `mbr/pipeline/__init__.py`
- Create: `mbr/pipeline/models.py`
- Test: `tests/test_pipeline_models.py` (append)

- [ ] **Step 1: Create blueprint init**

```python
# mbr/pipeline/__init__.py
from flask import Blueprint

pipeline_bp = Blueprint("pipeline", __name__)

from mbr.pipeline import routes  # noqa: F401, E402
from mbr.pipeline import lab_routes  # noqa: F401, E402
```

- [ ] **Step 2: Create stub route files so import doesn't fail**

```python
# mbr/pipeline/routes.py
from mbr.pipeline import pipeline_bp  # noqa: F401
```

```python
# mbr/pipeline/lab_routes.py
from mbr.pipeline import pipeline_bp  # noqa: F401
```

- [ ] **Step 3: Write failing tests for catalog CRUD**

Append to `tests/test_pipeline_models.py`:

```python
from mbr.pipeline.models import (
    create_etap, list_etapy, get_etap, update_etap, deactivate_etap,
    add_etap_parametr, list_etap_parametry, remove_etap_parametr,
    add_etap_warunek, list_etap_warunki, remove_etap_warunek,
    add_etap_korekta, list_etap_korekty, remove_etap_korekta,
)


def _seed_param(db, pid=1, kod="ph", label="pH", typ="bezposredni"):
    db.execute(
        "INSERT OR IGNORE INTO parametry_analityczne (id, kod, label, typ) VALUES (?,?,?,?)",
        (pid, kod, label, typ),
    )
    return pid


# --- etapy_analityczne CRUD ---

def test_create_etap(db):
    eid = create_etap(db, kod="sulfonowanie", nazwa="Sulfonowanie", typ_cyklu="cykliczny")
    assert eid is not None
    row = db.execute("SELECT * FROM etapy_analityczne WHERE id=?", (eid,)).fetchone()
    assert row["kod"] == "sulfonowanie"
    assert row["typ_cyklu"] == "cykliczny"


def test_create_etap_duplicate_kod(db):
    create_etap(db, kod="amid", nazwa="Amidowanie")
    with pytest.raises(sqlite3.IntegrityError):
        create_etap(db, kod="amid", nazwa="Amidowanie 2")


def test_list_etapy(db):
    create_etap(db, kod="a1", nazwa="A1")
    create_etap(db, kod="a2", nazwa="A2")
    etapy = list_etapy(db)
    assert len(etapy) >= 2
    kody = [e["kod"] for e in etapy]
    assert "a1" in kody
    assert "a2" in kody


def test_list_etapy_only_active(db):
    eid = create_etap(db, kod="old", nazwa="Old")
    deactivate_etap(db, eid)
    active = list_etapy(db, only_active=True)
    kody = [e["kod"] for e in active]
    assert "old" not in kody


def test_get_etap(db):
    eid = create_etap(db, kod="test", nazwa="Test")
    etap = get_etap(db, eid)
    assert etap["kod"] == "test"


def test_update_etap(db):
    eid = create_etap(db, kod="test", nazwa="Test")
    update_etap(db, eid, nazwa="Updated", opis="Description")
    etap = get_etap(db, eid)
    assert etap["nazwa"] == "Updated"
    assert etap["opis"] == "Description"


def test_deactivate_etap(db):
    eid = create_etap(db, kod="test", nazwa="Test")
    deactivate_etap(db, eid)
    etap = get_etap(db, eid)
    assert etap["aktywny"] == 0


# --- etap_parametry ---

def test_add_etap_parametr(db):
    eid = create_etap(db, kod="test", nazwa="Test")
    pid = _seed_param(db)
    epid = add_etap_parametr(db, etap_id=eid, parametr_id=pid, kolejnosc=1, min_limit=3.0, max_limit=9.0)
    assert epid is not None


def test_list_etap_parametry(db):
    eid = create_etap(db, kod="test", nazwa="Test")
    pid1 = _seed_param(db, 1, "ph", "pH", "bezposredni")
    pid2 = _seed_param(db, 2, "sm", "SM", "bezposredni")
    add_etap_parametr(db, eid, pid1, kolejnosc=2)
    add_etap_parametr(db, eid, pid2, kolejnosc=1)
    params = list_etap_parametry(db, eid)
    assert len(params) == 2
    assert params[0]["kod"] == "sm"  # kolejnosc=1 first
    assert params[1]["kod"] == "ph"


def test_remove_etap_parametr(db):
    eid = create_etap(db, kod="test", nazwa="Test")
    pid = _seed_param(db)
    epid = add_etap_parametr(db, eid, pid, kolejnosc=1)
    remove_etap_parametr(db, epid)
    assert len(list_etap_parametry(db, eid)) == 0


# --- etap_warunki ---

def test_add_and_list_warunki(db):
    eid = create_etap(db, kod="test", nazwa="Test")
    pid = _seed_param(db)
    wid = add_etap_warunek(db, etap_id=eid, parametr_id=pid, operator="<", wartosc=0.1,
                           opis_warunku="Siarczyny < 0.1%")
    warunki = list_etap_warunki(db, eid)
    assert len(warunki) == 1
    assert warunki[0]["operator"] == "<"
    assert warunki[0]["wartosc"] == 0.1


def test_remove_warunek(db):
    eid = create_etap(db, kod="test", nazwa="Test")
    pid = _seed_param(db)
    wid = add_etap_warunek(db, eid, pid, "<", 0.1)
    remove_etap_warunek(db, wid)
    assert len(list_etap_warunki(db, eid)) == 0


# --- etap_korekty_katalog ---

def test_add_and_list_korekty(db):
    eid = create_etap(db, kod="test", nazwa="Test")
    kid = add_etap_korekta(db, etap_id=eid, substancja="Perhydrol", jednostka="kg", wykonawca="produkcja")
    korekty = list_etap_korekty(db, eid)
    assert len(korekty) == 1
    assert korekty[0]["substancja"] == "Perhydrol"
    assert korekty[0]["wykonawca"] == "produkcja"


def test_remove_korekta(db):
    eid = create_etap(db, kod="test", nazwa="Test")
    kid = add_etap_korekta(db, eid, "NaOH", "kg", "produkcja")
    remove_etap_korekta(db, kid)
    assert len(list_etap_korekty(db, eid)) == 0
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
pytest tests/test_pipeline_models.py -v -k "not test_new_pipeline_tables"
```
Expected: ImportError — `mbr.pipeline.models` doesn't exist yet.

- [ ] **Step 5: Implement catalog CRUD in models.py**

```python
# mbr/pipeline/models.py
"""Pipeline builder models — analytical stage catalog and product pipeline CRUD."""

import sqlite3


# ---------------------------------------------------------------------------
# etapy_analityczne — global catalog
# ---------------------------------------------------------------------------

def create_etap(db: sqlite3.Connection, *, kod: str, nazwa: str,
                typ_cyklu: str = "jednorazowy", opis: str = None,
                kolejnosc_domyslna: int = 0) -> int:
    cur = db.execute(
        """INSERT INTO etapy_analityczne (kod, nazwa, opis, typ_cyklu, kolejnosc_domyslna)
           VALUES (?, ?, ?, ?, ?)""",
        (kod, nazwa, opis, typ_cyklu, kolejnosc_domyslna),
    )
    return cur.lastrowid


def list_etapy(db: sqlite3.Connection, *, only_active: bool = False) -> list[dict]:
    sql = "SELECT * FROM etapy_analityczne"
    if only_active:
        sql += " WHERE aktywny = 1"
    sql += " ORDER BY kolejnosc_domyslna, nazwa"
    return [dict(r) for r in db.execute(sql).fetchall()]


def get_etap(db: sqlite3.Connection, etap_id: int) -> dict | None:
    row = db.execute("SELECT * FROM etapy_analityczne WHERE id = ?", (etap_id,)).fetchone()
    return dict(row) if row else None


def update_etap(db: sqlite3.Connection, etap_id: int, **fields) -> None:
    allowed = {"nazwa", "opis", "typ_cyklu", "kolejnosc_domyslna"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    db.execute(
        f"UPDATE etapy_analityczne SET {set_clause} WHERE id = ?",
        (*updates.values(), etap_id),
    )


def deactivate_etap(db: sqlite3.Connection, etap_id: int) -> None:
    db.execute("UPDATE etapy_analityczne SET aktywny = 0 WHERE id = ?", (etap_id,))


# ---------------------------------------------------------------------------
# etap_parametry — default params per stage
# ---------------------------------------------------------------------------

def add_etap_parametr(db: sqlite3.Connection, etap_id: int, parametr_id: int,
                      kolejnosc: int = 0, **kwargs) -> int:
    cols = ["etap_id", "parametr_id", "kolejnosc"]
    vals = [etap_id, parametr_id, kolejnosc]
    allowed = {"min_limit", "max_limit", "nawazka_g", "precision", "target",
               "wymagany", "grupa", "formula", "sa_bias", "krok"}
    for k, v in kwargs.items():
        if k in allowed:
            cols.append(k)
            vals.append(v)
    placeholders = ", ".join("?" for _ in cols)
    col_str = ", ".join(cols)
    cur = db.execute(f"INSERT INTO etap_parametry ({col_str}) VALUES ({placeholders})", vals)
    return cur.lastrowid


def list_etap_parametry(db: sqlite3.Connection, etap_id: int) -> list[dict]:
    return [dict(r) for r in db.execute(
        """SELECT ep.*, pa.kod, pa.label, pa.typ, pa.skrot, pa.jednostka,
                  pa.metoda_id, pa.metoda_nazwa, pa.metoda_formula, pa.metoda_factor
           FROM etap_parametry ep
           JOIN parametry_analityczne pa ON pa.id = ep.parametr_id
           WHERE ep.etap_id = ?
           ORDER BY ep.kolejnosc""",
        (etap_id,),
    ).fetchall()]


def update_etap_parametr(db: sqlite3.Connection, ep_id: int, **fields) -> None:
    allowed = {"kolejnosc", "min_limit", "max_limit", "nawazka_g", "precision",
               "target", "wymagany", "grupa", "formula", "sa_bias", "krok"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    db.execute(f"UPDATE etap_parametry SET {set_clause} WHERE id = ?",
               (*updates.values(), ep_id))


def remove_etap_parametr(db: sqlite3.Connection, ep_id: int) -> None:
    db.execute("DELETE FROM etap_parametry WHERE id = ?", (ep_id,))


# ---------------------------------------------------------------------------
# etap_warunki — gate conditions
# ---------------------------------------------------------------------------

def add_etap_warunek(db: sqlite3.Connection, etap_id: int, parametr_id: int,
                     operator: str, wartosc: float, wartosc_max: float = None,
                     opis_warunku: str = None) -> int:
    cur = db.execute(
        """INSERT INTO etap_warunki (etap_id, parametr_id, operator, wartosc, wartosc_max, opis_warunku)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (etap_id, parametr_id, operator, wartosc, wartosc_max, opis_warunku),
    )
    return cur.lastrowid


def list_etap_warunki(db: sqlite3.Connection, etap_id: int) -> list[dict]:
    return [dict(r) for r in db.execute(
        """SELECT ew.*, pa.kod, pa.label, pa.skrot
           FROM etap_warunki ew
           JOIN parametry_analityczne pa ON pa.id = ew.parametr_id
           WHERE ew.etap_id = ?""",
        (etap_id,),
    ).fetchall()]


def remove_etap_warunek(db: sqlite3.Connection, warunek_id: int) -> None:
    db.execute("DELETE FROM etap_warunki WHERE id = ?", (warunek_id,))


# ---------------------------------------------------------------------------
# etap_korekty_katalog — allowed corrections
# ---------------------------------------------------------------------------

def add_etap_korekta(db: sqlite3.Connection, etap_id: int, substancja: str,
                     jednostka: str = "kg", wykonawca: str = "produkcja",
                     kolejnosc: int = 0) -> int:
    cur = db.execute(
        """INSERT INTO etap_korekty_katalog (etap_id, substancja, jednostka, wykonawca, kolejnosc)
           VALUES (?, ?, ?, ?, ?)""",
        (etap_id, substancja, jednostka, wykonawca, kolejnosc),
    )
    return cur.lastrowid


def list_etap_korekty(db: sqlite3.Connection, etap_id: int) -> list[dict]:
    return [dict(r) for r in db.execute(
        "SELECT * FROM etap_korekty_katalog WHERE etap_id = ? ORDER BY kolejnosc",
        (etap_id,),
    ).fetchall()]


def remove_etap_korekta(db: sqlite3.Connection, korekta_id: int) -> None:
    db.execute("DELETE FROM etap_korekty_katalog WHERE id = ?", (korekta_id,))
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_pipeline_models.py -v
```
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add mbr/pipeline/__init__.py mbr/pipeline/models.py mbr/pipeline/routes.py mbr/pipeline/lab_routes.py tests/test_pipeline_models.py
git commit -m "feat: pipeline catalog CRUD models (etapy, params, gates, corrections)"
```

---

## Task 3: Pipeline Models — Product Pipeline CRUD

**Files:**
- Modify: `mbr/pipeline/models.py`
- Test: `tests/test_pipeline_models.py` (append)

- [ ] **Step 1: Write failing tests for product pipeline**

Append to `tests/test_pipeline_models.py`:

```python
from mbr.pipeline.models import (
    set_produkt_pipeline, get_produkt_pipeline, remove_pipeline_etap,
    reorder_pipeline,
    set_produkt_etap_limit, get_produkt_etap_limity, remove_produkt_etap_limit,
    resolve_limity,
)


def test_set_produkt_pipeline(db):
    e1 = create_etap(db, kod="a1", nazwa="A1")
    e2 = create_etap(db, kod="a2", nazwa="A2")
    set_produkt_pipeline(db, "Chegina_K7", e1, kolejnosc=1)
    set_produkt_pipeline(db, "Chegina_K7", e2, kolejnosc=2)
    pipe = get_produkt_pipeline(db, "Chegina_K7")
    assert len(pipe) == 2
    assert pipe[0]["kod"] == "a1"
    assert pipe[1]["kod"] == "a2"


def test_remove_pipeline_etap(db):
    e1 = create_etap(db, kod="a1", nazwa="A1")
    set_produkt_pipeline(db, "Chegina_K7", e1, kolejnosc=1)
    remove_pipeline_etap(db, "Chegina_K7", e1)
    assert len(get_produkt_pipeline(db, "Chegina_K7")) == 0


def test_reorder_pipeline(db):
    e1 = create_etap(db, kod="a1", nazwa="A1")
    e2 = create_etap(db, kod="a2", nazwa="A2")
    set_produkt_pipeline(db, "Chegina_K7", e1, kolejnosc=1)
    set_produkt_pipeline(db, "Chegina_K7", e2, kolejnosc=2)
    reorder_pipeline(db, "Chegina_K7", [e2, e1])  # swap order
    pipe = get_produkt_pipeline(db, "Chegina_K7")
    assert pipe[0]["kod"] == "a2"
    assert pipe[1]["kod"] == "a1"


def test_set_and_get_produkt_etap_limit(db):
    e1 = create_etap(db, kod="test", nazwa="Test")
    pid = _seed_param(db)
    add_etap_parametr(db, e1, pid, kolejnosc=1, min_limit=3.0, max_limit=9.0)
    set_produkt_etap_limit(db, "Chegina_K7", e1, pid, min_limit=4.0, max_limit=8.0)
    limity = get_produkt_etap_limity(db, "Chegina_K7", e1)
    assert len(limity) == 1
    assert limity[0]["min_limit"] == 4.0


def test_remove_produkt_etap_limit(db):
    e1 = create_etap(db, kod="test", nazwa="Test")
    pid = _seed_param(db)
    set_produkt_etap_limit(db, "Chegina_K7", e1, pid, min_limit=4.0)
    remove_produkt_etap_limit(db, "Chegina_K7", e1, pid)
    assert len(get_produkt_etap_limity(db, "Chegina_K7", e1)) == 0


def test_resolve_limity_uses_product_override(db):
    e1 = create_etap(db, kod="test", nazwa="Test")
    pid = _seed_param(db)
    add_etap_parametr(db, e1, pid, kolejnosc=1, min_limit=3.0, max_limit=9.0)
    set_produkt_etap_limit(db, "Chegina_K7", e1, pid, min_limit=5.0, max_limit=7.0)
    resolved = resolve_limity(db, "Chegina_K7", e1)
    assert resolved[0]["min_limit"] == 5.0
    assert resolved[0]["max_limit"] == 7.0


def test_resolve_limity_falls_back_to_default(db):
    e1 = create_etap(db, kod="test", nazwa="Test")
    pid = _seed_param(db)
    add_etap_parametr(db, e1, pid, kolejnosc=1, min_limit=3.0, max_limit=9.0)
    resolved = resolve_limity(db, "Chegina_K7", e1)
    assert resolved[0]["min_limit"] == 3.0
    assert resolved[0]["max_limit"] == 9.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pipeline_models.py -v -k "produkt_pipeline or resolve_limity or reorder"
```
Expected: ImportError.

- [ ] **Step 3: Implement product pipeline functions**

Append to `mbr/pipeline/models.py`:

```python
# ---------------------------------------------------------------------------
# produkt_pipeline — stage sequence per product
# ---------------------------------------------------------------------------

def set_produkt_pipeline(db: sqlite3.Connection, produkt: str, etap_id: int,
                         kolejnosc: int) -> int:
    cur = db.execute(
        """INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc)
           VALUES (?, ?, ?)
           ON CONFLICT(produkt, etap_id) DO UPDATE SET kolejnosc = excluded.kolejnosc""",
        (produkt, etap_id, kolejnosc),
    )
    return cur.lastrowid


def get_produkt_pipeline(db: sqlite3.Connection, produkt: str) -> list[dict]:
    return [dict(r) for r in db.execute(
        """SELECT pp.*, ea.kod, ea.nazwa, ea.typ_cyklu
           FROM produkt_pipeline pp
           JOIN etapy_analityczne ea ON ea.id = pp.etap_id
           WHERE pp.produkt = ?
           ORDER BY pp.kolejnosc""",
        (produkt,),
    ).fetchall()]


def remove_pipeline_etap(db: sqlite3.Connection, produkt: str, etap_id: int) -> None:
    db.execute("DELETE FROM produkt_pipeline WHERE produkt = ? AND etap_id = ?",
               (produkt, etap_id))


def reorder_pipeline(db: sqlite3.Connection, produkt: str, etap_ids: list[int]) -> None:
    for idx, etap_id in enumerate(etap_ids, start=1):
        db.execute(
            "UPDATE produkt_pipeline SET kolejnosc = ? WHERE produkt = ? AND etap_id = ?",
            (idx, produkt, etap_id),
        )


# ---------------------------------------------------------------------------
# produkt_etap_limity — per-product limit overrides
# ---------------------------------------------------------------------------

def set_produkt_etap_limit(db: sqlite3.Connection, produkt: str, etap_id: int,
                           parametr_id: int, **kwargs) -> int:
    cols = ["produkt", "etap_id", "parametr_id"]
    vals = [produkt, etap_id, parametr_id]
    allowed = {"min_limit", "max_limit", "nawazka_g", "precision", "target"}
    for k, v in kwargs.items():
        if k in allowed:
            cols.append(k)
            vals.append(v)
    placeholders = ", ".join("?" for _ in cols)
    col_str = ", ".join(cols)
    update_cols = [c for c in cols if c not in ("produkt", "etap_id", "parametr_id")]
    update_clause = ", ".join(f"{c} = excluded.{c}" for c in update_cols)
    cur = db.execute(
        f"""INSERT INTO produkt_etap_limity ({col_str}) VALUES ({placeholders})
            ON CONFLICT(produkt, etap_id, parametr_id)
            DO UPDATE SET {update_clause}""",
        vals,
    )
    return cur.lastrowid


def get_produkt_etap_limity(db: sqlite3.Connection, produkt: str,
                            etap_id: int) -> list[dict]:
    return [dict(r) for r in db.execute(
        """SELECT pel.*, pa.kod, pa.label
           FROM produkt_etap_limity pel
           JOIN parametry_analityczne pa ON pa.id = pel.parametr_id
           WHERE pel.produkt = ? AND pel.etap_id = ?""",
        (produkt, etap_id),
    ).fetchall()]


def remove_produkt_etap_limit(db: sqlite3.Connection, produkt: str,
                              etap_id: int, parametr_id: int) -> None:
    db.execute(
        "DELETE FROM produkt_etap_limity WHERE produkt = ? AND etap_id = ? AND parametr_id = ?",
        (produkt, etap_id, parametr_id),
    )


# ---------------------------------------------------------------------------
# resolve_limity — three-level limit resolution
# ---------------------------------------------------------------------------

def resolve_limity(db: sqlite3.Connection, produkt: str, etap_id: int) -> list[dict]:
    params = list_etap_parametry(db, etap_id)
    overrides = {r["parametr_id"]: dict(r) for r in db.execute(
        "SELECT * FROM produkt_etap_limity WHERE produkt = ? AND etap_id = ?",
        (produkt, etap_id),
    ).fetchall()}
    result = []
    for p in params:
        ov = overrides.get(p["parametr_id"], {})
        resolved = dict(p)
        for field in ("min_limit", "max_limit", "nawazka_g", "precision", "target"):
            if ov.get(field) is not None:
                resolved[field] = ov[field]
        result.append(resolved)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_pipeline_models.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/pipeline/models.py tests/test_pipeline_models.py
git commit -m "feat: product pipeline CRUD + three-level limit resolution"
```

---

## Task 4: Pipeline Models — EBR Execution (Session, Pomiar, Gate, Korekta)

**Files:**
- Modify: `mbr/pipeline/models.py`
- Test: `tests/test_pipeline_lab.py`

- [ ] **Step 1: Write failing tests for EBR execution**

```python
# tests/test_pipeline_lab.py
import sqlite3
import pytest
from mbr.models import init_mbr_tables
from mbr.pipeline.models import (
    create_etap, add_etap_parametr, set_produkt_pipeline,
    add_etap_warunek, add_etap_korekta,
    create_sesja, get_sesja, list_sesje,
    save_pomiar, get_pomiary,
    evaluate_gate, close_sesja,
    create_ebr_korekta, list_ebr_korekty, update_ebr_korekta_status,
    init_pipeline_sesje,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed_param(db, pid, kod, typ="bezposredni"):
    db.execute(
        "INSERT OR IGNORE INTO parametry_analityczne (id, kod, label, typ) VALUES (?,?,?,?)",
        (pid, kod, kod, typ),
    )


def _seed_ebr(db, produkt="TestProd"):
    db.execute("""INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia)
                  VALUES (1, ?, 1, '2026-01-01')""", (produkt,))
    db.execute("""INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start)
                  VALUES (1, 1, 'T-1', '1/2026', '2026-01-01')""")
    return 1


@pytest.fixture
def setup_pipeline(db):
    """Create a product with 2-stage pipeline, params, gates."""
    _seed_param(db, 1, "so3", "titracja")
    _seed_param(db, 2, "ph", "bezposredni")
    _seed_param(db, 3, "sm", "bezposredni")

    e1 = create_etap(db, kod="sulfonowanie", nazwa="Sulfonowanie", typ_cyklu="cykliczny")
    e2 = create_etap(db, kod="analiza_koncowa", nazwa="Analiza koncowa", typ_cyklu="jednorazowy")

    add_etap_parametr(db, e1, 1, kolejnosc=1, max_limit=0.1)  # so3 < 0.1
    add_etap_parametr(db, e1, 2, kolejnosc=2)  # ph — no limit
    add_etap_parametr(db, e2, 3, kolejnosc=1, min_limit=44.0, max_limit=48.0)  # sm

    add_etap_warunek(db, e1, 1, "<", 0.1, opis_warunku="SO3 < 0.1%")
    add_etap_korekta(db, e1, "Perhydrol", "kg", "produkcja")

    set_produkt_pipeline(db, "TestProd", e1, kolejnosc=1)
    set_produkt_pipeline(db, "TestProd", e2, kolejnosc=2)

    ebr_id = _seed_ebr(db, "TestProd")
    return {"db": db, "ebr_id": ebr_id, "e1": e1, "e2": e2}


def test_create_sesja(setup_pipeline):
    db = setup_pipeline["db"]
    sid = create_sesja(db, setup_pipeline["ebr_id"], setup_pipeline["e1"], runda=1, laborant="lab1")
    assert sid is not None
    sesja = get_sesja(db, sid)
    assert sesja["runda"] == 1
    assert sesja["status"] == "w_trakcie"


def test_save_and_get_pomiar(setup_pipeline):
    db = setup_pipeline["db"]
    sid = create_sesja(db, setup_pipeline["ebr_id"], setup_pipeline["e1"], runda=1, laborant="lab1")
    save_pomiar(db, sid, parametr_id=1, wartosc=0.05, min_limit=None, max_limit=0.1,
                wpisal="lab1")
    pomiary = get_pomiary(db, sid)
    assert len(pomiary) == 1
    assert pomiary[0]["wartosc"] == 0.05
    assert pomiary[0]["w_limicie"] == 1


def test_save_pomiar_out_of_limit(setup_pipeline):
    db = setup_pipeline["db"]
    sid = create_sesja(db, setup_pipeline["ebr_id"], setup_pipeline["e1"], runda=1, laborant="lab1")
    save_pomiar(db, sid, parametr_id=1, wartosc=0.15, min_limit=None, max_limit=0.1,
                wpisal="lab1")
    pomiary = get_pomiary(db, sid)
    assert pomiary[0]["w_limicie"] == 0


def test_evaluate_gate_pass(setup_pipeline):
    db = setup_pipeline["db"]
    sid = create_sesja(db, setup_pipeline["ebr_id"], setup_pipeline["e1"], runda=1, laborant="lab1")
    save_pomiar(db, sid, 1, 0.05, None, 0.1, "lab1")
    result = evaluate_gate(db, setup_pipeline["e1"], sid)
    assert result["passed"] is True
    assert len(result["failures"]) == 0


def test_evaluate_gate_fail(setup_pipeline):
    db = setup_pipeline["db"]
    sid = create_sesja(db, setup_pipeline["ebr_id"], setup_pipeline["e1"], runda=1, laborant="lab1")
    save_pomiar(db, sid, 1, 0.15, None, 0.1, "lab1")
    result = evaluate_gate(db, setup_pipeline["e1"], sid)
    assert result["passed"] is False
    assert len(result["failures"]) == 1
    assert result["failures"][0]["kod"] == "so3"


def test_close_sesja_ok(setup_pipeline):
    db = setup_pipeline["db"]
    sid = create_sesja(db, setup_pipeline["ebr_id"], setup_pipeline["e1"], runda=1, laborant="lab1")
    save_pomiar(db, sid, 1, 0.05, None, 0.1, "lab1")
    close_sesja(db, sid, decyzja="przejscie")
    sesja = get_sesja(db, sid)
    assert sesja["status"] == "ok"
    assert sesja["decyzja"] == "przejscie"


def test_close_sesja_korekta(setup_pipeline):
    db = setup_pipeline["db"]
    sid = create_sesja(db, setup_pipeline["ebr_id"], setup_pipeline["e1"], runda=1, laborant="lab1")
    save_pomiar(db, sid, 1, 0.15, None, 0.1, "lab1")
    close_sesja(db, sid, decyzja="korekta")
    sesja = get_sesja(db, sid)
    assert sesja["status"] == "oczekuje_korekty"
    assert sesja["decyzja"] == "korekta"


def test_create_ebr_korekta(setup_pipeline):
    db = setup_pipeline["db"]
    sid = create_sesja(db, setup_pipeline["ebr_id"], setup_pipeline["e1"], runda=1, laborant="lab1")
    korekty_kat = list(db.execute(
        "SELECT id FROM etap_korekty_katalog WHERE etap_id = ?",
        (setup_pipeline["e1"],)
    ).fetchall())
    kid = create_ebr_korekta(db, sid, korekty_kat[0]["id"], ilosc=5.0, zalecil="lab1")
    korekty = list_ebr_korekty(db, sid)
    assert len(korekty) == 1
    assert korekty[0]["ilosc"] == 5.0
    assert korekty[0]["status"] == "zalecona"


def test_update_korekta_status(setup_pipeline):
    db = setup_pipeline["db"]
    sid = create_sesja(db, setup_pipeline["ebr_id"], setup_pipeline["e1"], runda=1, laborant="lab1")
    korekty_kat = list(db.execute(
        "SELECT id FROM etap_korekty_katalog WHERE etap_id = ?",
        (setup_pipeline["e1"],)
    ).fetchall())
    kid = create_ebr_korekta(db, sid, korekty_kat[0]["id"], ilosc=5.0, zalecil="lab1")
    update_ebr_korekta_status(db, kid, "wykonana", wykonawca_info="Operator Jan")
    korekty = list_ebr_korekty(db, sid)
    assert korekty[0]["status"] == "wykonana"
    assert korekty[0]["wykonawca_info"] == "Operator Jan"


def test_init_pipeline_sesje(setup_pipeline):
    db = setup_pipeline["db"]
    init_pipeline_sesje(db, setup_pipeline["ebr_id"], "TestProd", laborant="lab1")
    sesje = list_sesje(db, setup_pipeline["ebr_id"])
    assert len(sesje) == 1  # only first stage gets a session
    assert sesje[0]["etap_id"] == setup_pipeline["e1"]
    assert sesje[0]["runda"] == 1


def test_multi_round_flow(setup_pipeline):
    """Full cycle: analyze -> fail gate -> correct -> analyze again -> pass."""
    db = setup_pipeline["db"]
    e1 = setup_pipeline["e1"]
    ebr_id = setup_pipeline["ebr_id"]

    # Round 1: fail
    s1 = create_sesja(db, ebr_id, e1, runda=1, laborant="lab1")
    save_pomiar(db, s1, 1, 0.15, None, 0.1, "lab1")
    gate = evaluate_gate(db, e1, s1)
    assert gate["passed"] is False
    close_sesja(db, s1, decyzja="korekta")

    # Round 2: pass
    s2 = create_sesja(db, ebr_id, e1, runda=2, laborant="lab1")
    save_pomiar(db, s2, 1, 0.05, None, 0.1, "lab1")
    gate = evaluate_gate(db, e1, s2)
    assert gate["passed"] is True
    close_sesja(db, s2, decyzja="przejscie")

    sesje = list_sesje(db, ebr_id, etap_id=e1)
    assert len(sesje) == 2
    assert sesje[0]["status"] == "oczekuje_korekty"
    assert sesje[1]["status"] == "ok"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pipeline_lab.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement EBR execution functions**

Append to `mbr/pipeline/models.py`:

```python
from datetime import datetime


# ---------------------------------------------------------------------------
# ebr_etap_sesja — analysis sessions (rounds)
# ---------------------------------------------------------------------------

def create_sesja(db: sqlite3.Connection, ebr_id: int, etap_id: int,
                 runda: int = 1, laborant: str = None) -> int:
    cur = db.execute(
        """INSERT INTO ebr_etap_sesja (ebr_id, etap_id, runda, laborant, dt_start)
           VALUES (?, ?, ?, ?, ?)""",
        (ebr_id, etap_id, runda, laborant, datetime.now().isoformat(timespec="seconds")),
    )
    return cur.lastrowid


def get_sesja(db: sqlite3.Connection, sesja_id: int) -> dict | None:
    row = db.execute("SELECT * FROM ebr_etap_sesja WHERE id = ?", (sesja_id,)).fetchone()
    return dict(row) if row else None


def list_sesje(db: sqlite3.Connection, ebr_id: int, etap_id: int = None) -> list[dict]:
    sql = "SELECT * FROM ebr_etap_sesja WHERE ebr_id = ?"
    params = [ebr_id]
    if etap_id is not None:
        sql += " AND etap_id = ?"
        params.append(etap_id)
    sql += " ORDER BY etap_id, runda"
    return [dict(r) for r in db.execute(sql, params).fetchall()]


def close_sesja(db: sqlite3.Connection, sesja_id: int, decyzja: str) -> None:
    status = "ok" if decyzja == "przejscie" else "oczekuje_korekty"
    db.execute(
        """UPDATE ebr_etap_sesja
           SET status = ?, decyzja = ?, dt_end = ?
           WHERE id = ?""",
        (status, decyzja, datetime.now().isoformat(timespec="seconds"), sesja_id),
    )


def init_pipeline_sesje(db: sqlite3.Connection, ebr_id: int, produkt: str,
                        laborant: str = None) -> int | None:
    pipeline = get_produkt_pipeline(db, produkt)
    if not pipeline:
        return None
    first = pipeline[0]
    return create_sesja(db, ebr_id, first["etap_id"], runda=1, laborant=laborant)


# ---------------------------------------------------------------------------
# ebr_pomiar — individual measurements
# ---------------------------------------------------------------------------

def _compute_w_limicie(wartosc, min_limit, max_limit) -> int | None:
    if wartosc is None:
        return None
    if min_limit is not None and wartosc < min_limit:
        return 0
    if max_limit is not None and wartosc > max_limit:
        return 0
    if min_limit is None and max_limit is None:
        return None
    return 1


def save_pomiar(db: sqlite3.Connection, sesja_id: int, parametr_id: int,
                wartosc: float, min_limit: float, max_limit: float,
                wpisal: str, is_manual: int = 1) -> int:
    w_limicie = _compute_w_limicie(wartosc, min_limit, max_limit)
    cur = db.execute(
        """INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, min_limit, max_limit,
                                   w_limicie, is_manual, dt_wpisu, wpisal)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(sesja_id, parametr_id)
           DO UPDATE SET wartosc = excluded.wartosc,
                         min_limit = excluded.min_limit,
                         max_limit = excluded.max_limit,
                         w_limicie = excluded.w_limicie,
                         dt_wpisu = excluded.dt_wpisu,
                         wpisal = excluded.wpisal""",
        (sesja_id, parametr_id, wartosc, min_limit, max_limit, w_limicie,
         is_manual, datetime.now().isoformat(timespec="seconds"), wpisal),
    )
    return cur.lastrowid


def get_pomiary(db: sqlite3.Connection, sesja_id: int) -> list[dict]:
    return [dict(r) for r in db.execute(
        """SELECT p.*, pa.kod, pa.label, pa.typ, pa.skrot
           FROM ebr_pomiar p
           JOIN parametry_analityczne pa ON pa.id = p.parametr_id
           WHERE p.sesja_id = ?
           ORDER BY p.id""",
        (sesja_id,),
    ).fetchall()]


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------

def evaluate_gate(db: sqlite3.Connection, etap_id: int, sesja_id: int) -> dict:
    warunki = list_etap_warunki(db, etap_id)
    if not warunki:
        return {"passed": True, "failures": []}

    pomiary = {p["parametr_id"]: p for p in get_pomiary(db, sesja_id)}
    failures = []

    for w in warunki:
        p = pomiary.get(w["parametr_id"])
        if p is None or p["wartosc"] is None:
            failures.append({"kod": w["kod"], "reason": "brak pomiaru",
                             "warunek": w["opis_warunku"]})
            continue

        val = p["wartosc"]
        op = w["operator"]
        ok = False
        if op == "<":
            ok = val < w["wartosc"]
        elif op == "<=":
            ok = val <= w["wartosc"]
        elif op == ">":
            ok = val > w["wartosc"]
        elif op == ">=":
            ok = val >= w["wartosc"]
        elif op == "=":
            ok = val == w["wartosc"]
        elif op == "between":
            ok = w["wartosc"] <= val <= w["wartosc_max"]

        if not ok:
            failures.append({
                "kod": w["kod"],
                "reason": f"{w.get('skrot', w['kod'])} = {val}, wymagane: {op} {w['wartosc']}",
                "warunek": w.get("opis_warunku"),
            })

    return {"passed": len(failures) == 0, "failures": failures}


# ---------------------------------------------------------------------------
# ebr_korekta_v2 — corrections
# ---------------------------------------------------------------------------

def create_ebr_korekta(db: sqlite3.Connection, sesja_id: int, korekta_typ_id: int,
                       ilosc: float, zalecil: str) -> int:
    cur = db.execute(
        """INSERT INTO ebr_korekta_v2 (sesja_id, korekta_typ_id, ilosc, zalecil, dt_zalecenia)
           VALUES (?, ?, ?, ?, ?)""",
        (sesja_id, korekta_typ_id, ilosc, zalecil,
         datetime.now().isoformat(timespec="seconds")),
    )
    return cur.lastrowid


def list_ebr_korekty(db: sqlite3.Connection, sesja_id: int) -> list[dict]:
    return [dict(r) for r in db.execute(
        """SELECT k.*, ek.substancja, ek.jednostka, ek.wykonawca
           FROM ebr_korekta_v2 k
           JOIN etap_korekty_katalog ek ON ek.id = k.korekta_typ_id
           WHERE k.sesja_id = ?
           ORDER BY k.id""",
        (sesja_id,),
    ).fetchall()]


def update_ebr_korekta_status(db: sqlite3.Connection, korekta_id: int,
                              status: str, wykonawca_info: str = None) -> None:
    db.execute(
        """UPDATE ebr_korekta_v2
           SET status = ?, wykonawca_info = ?, dt_wykonania = ?
           WHERE id = ?""",
        (status, wykonawca_info, datetime.now().isoformat(timespec="seconds"),
         korekta_id),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_pipeline_lab.py -v
```
Expected: all PASS.

- [ ] **Step 5: Verify all tests pass**

```bash
pytest --tb=short -q
```

- [ ] **Step 6: Commit**

```bash
git add mbr/pipeline/models.py tests/test_pipeline_lab.py
git commit -m "feat: EBR execution models (sessions, measurements, gates, corrections)"
```

---

## Task 5: Migration Script — parametry_etapy to New Tables

**Files:**
- Create: `scripts/migrate_parametry_etapy.py`
- Test: `tests/test_pipeline_models.py` (append migration test)

- [ ] **Step 1: Write failing test for migration**

Append to `tests/test_pipeline_models.py`:

```python
from scripts.migrate_parametry_etapy import migrate_parametry_etapy


def _seed_old_data(db):
    """Seed parametry_analityczne + parametry_etapy like the existing system."""
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (1, 'ph', 'pH', 'bezposredni')")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (2, 'sm', 'SM', 'bezposredni')")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (3, 'nacl', 'NaCl', 'titracja')")

    # Shared (produkt=NULL) bindings
    db.execute("""INSERT INTO parametry_etapy (produkt, kontekst, parametr_id, kolejnosc, min_limit, max_limit)
                  VALUES (NULL, 'amidowanie', 1, 1, 3.0, 9.0)""")
    db.execute("""INSERT INTO parametry_etapy (produkt, kontekst, parametr_id, kolejnosc, min_limit, max_limit)
                  VALUES (NULL, 'amidowanie', 2, 2, 40.0, 50.0)""")

    # Product-specific binding (overrides shared)
    db.execute("""INSERT INTO parametry_etapy (produkt, kontekst, parametr_id, kolejnosc, min_limit, max_limit)
                  VALUES ('Chegina_K7', 'amidowanie', 1, 1, 4.0, 8.0)""")

    # analiza_koncowa context
    db.execute("""INSERT INTO parametry_etapy (produkt, kontekst, parametr_id, kolejnosc, min_limit, max_limit)
                  VALUES ('Chegina_K7', 'analiza_koncowa', 2, 1, 44.0, 48.0)""")
    db.execute("""INSERT INTO parametry_etapy (produkt, kontekst, parametr_id, kolejnosc, min_limit, max_limit)
                  VALUES ('Chegina_K7', 'analiza_koncowa', 3, 2, 5.0, 8.0)""")


def test_migrate_creates_etapy(db):
    _seed_old_data(db)
    migrate_parametry_etapy(db)
    etapy = db.execute("SELECT * FROM etapy_analityczne ORDER BY kod").fetchall()
    kody = [r["kod"] for r in etapy]
    assert "amidowanie" in kody
    assert "analiza_koncowa" in kody


def test_migrate_creates_etap_parametry(db):
    _seed_old_data(db)
    migrate_parametry_etapy(db)
    amid = db.execute("SELECT id FROM etapy_analityczne WHERE kod='amidowanie'").fetchone()
    params = db.execute("SELECT * FROM etap_parametry WHERE etap_id=?", (amid["id"],)).fetchall()
    assert len(params) == 2  # ph and sm (shared bindings)


def test_migrate_creates_pipeline(db):
    _seed_old_data(db)
    migrate_parametry_etapy(db)
    pipe = db.execute("SELECT * FROM produkt_pipeline WHERE produkt='Chegina_K7' ORDER BY kolejnosc").fetchall()
    assert len(pipe) == 2  # amidowanie + analiza_koncowa


def test_migrate_creates_product_limits(db):
    _seed_old_data(db)
    migrate_parametry_etapy(db)
    amid = db.execute("SELECT id FROM etapy_analityczne WHERE kod='amidowanie'").fetchone()
    limits = db.execute(
        "SELECT * FROM produkt_etap_limity WHERE produkt='Chegina_K7' AND etap_id=?",
        (amid["id"],)
    ).fetchall()
    assert len(limits) == 1  # ph override
    assert limits[0]["min_limit"] == 4.0


def test_migrate_is_idempotent(db):
    _seed_old_data(db)
    migrate_parametry_etapy(db)
    migrate_parametry_etapy(db)  # second run should not fail
    etapy = db.execute("SELECT * FROM etapy_analityczne").fetchall()
    assert len(etapy) == 2  # still just 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pipeline_models.py -v -k "migrate"
```
Expected: ImportError.

- [ ] **Step 3: Implement migration script**

```python
# scripts/migrate_parametry_etapy.py
"""
Migrate parametry_etapy data to new pipeline tables.

One-time migration. Idempotent (INSERT OR IGNORE).

Usage:
    python -m scripts.migrate_parametry_etapy
"""
import sqlite3


KONTEKST_META = {
    "amidowanie":        {"nazwa": "Po amidowaniu",       "typ_cyklu": "jednorazowy", "kol": 1},
    "namca":             {"nazwa": "NAMCA (SMCA)",        "typ_cyklu": "jednorazowy", "kol": 2},
    "czwartorzedowanie": {"nazwa": "Czwartorzędowanie",   "typ_cyklu": "jednorazowy", "kol": 3},
    "sulfonowanie":      {"nazwa": "Sulfonowanie",        "typ_cyklu": "cykliczny",   "kol": 4},
    "utlenienie":        {"nazwa": "Utlenienie",          "typ_cyklu": "cykliczny",   "kol": 5},
    "rozjasnianie":      {"nazwa": "Rozjaśnianie",        "typ_cyklu": "cykliczny",   "kol": 6},
    "dodatki":           {"nazwa": "Dodatki standaryzacyjne", "typ_cyklu": "cykliczny", "kol": 7},
    "analiza_koncowa":   {"nazwa": "Analiza końcowa",     "typ_cyklu": "jednorazowy", "kol": 8},
}


def migrate_parametry_etapy(db: sqlite3.Connection) -> dict:
    stats = {"etapy": 0, "etap_parametry": 0, "pipeline": 0, "limity": 0}

    konteksty = [r[0] for r in db.execute(
        "SELECT DISTINCT kontekst FROM parametry_etapy WHERE kontekst != 'cert_variant'"
    ).fetchall()]

    etap_id_map = {}
    for kontekst in konteksty:
        meta = KONTEKST_META.get(kontekst, {
            "nazwa": kontekst.replace("_", " ").title(),
            "typ_cyklu": "jednorazowy",
            "kol": 99,
        })
        db.execute(
            """INSERT OR IGNORE INTO etapy_analityczne (kod, nazwa, typ_cyklu, kolejnosc_domyslna)
               VALUES (?, ?, ?, ?)""",
            (kontekst, meta["nazwa"], meta["typ_cyklu"], meta["kol"]),
        )
        row = db.execute("SELECT id FROM etapy_analityczne WHERE kod = ?", (kontekst,)).fetchone()
        etap_id_map[kontekst] = row[0]
        stats["etapy"] += 1

    shared = db.execute(
        """SELECT * FROM parametry_etapy
           WHERE produkt IS NULL AND kontekst != 'cert_variant'"""
    ).fetchall()
    for r in shared:
        etap_id = etap_id_map[r["kontekst"]]
        db.execute(
            """INSERT OR IGNORE INTO etap_parametry
               (etap_id, parametr_id, kolejnosc, min_limit, max_limit,
                nawazka_g, precision, target, wymagany, grupa, formula, sa_bias, krok)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (etap_id, r["parametr_id"], r["kolejnosc"], r["min_limit"], r["max_limit"],
             r["nawazka_g"], r["precision"], r["target"], r["wymagany"],
             r["grupa"], r.get("formula"), r.get("sa_bias"), r.get("krok")),
        )
        stats["etap_parametry"] += 1

    prod_rows = db.execute(
        """SELECT DISTINCT produkt, kontekst FROM parametry_etapy
           WHERE produkt IS NOT NULL AND kontekst != 'cert_variant'
           ORDER BY produkt, kontekst"""
    ).fetchall()

    pipeline_added = set()
    for pr in prod_rows:
        produkt = pr["produkt"]
        kontekst = pr["kontekst"]
        etap_id = etap_id_map[kontekst]

        if (produkt, etap_id) not in pipeline_added:
            meta = KONTEKST_META.get(kontekst, {"kol": 99})
            db.execute(
                """INSERT OR IGNORE INTO produkt_pipeline (produkt, etap_id, kolejnosc)
                   VALUES (?, ?, ?)""",
                (produkt, etap_id, meta["kol"]),
            )
            pipeline_added.add((produkt, etap_id))
            stats["pipeline"] += 1

        overrides = db.execute(
            """SELECT * FROM parametry_etapy
               WHERE produkt = ? AND kontekst = ?""",
            (produkt, kontekst),
        ).fetchall()
        for ov in overrides:
            has_override = any([
                ov["min_limit"] is not None,
                ov["max_limit"] is not None,
                ov["nawazka_g"] is not None,
                ov.get("precision") is not None,
                ov.get("target") is not None,
            ])
            if has_override:
                db.execute(
                    """INSERT OR IGNORE INTO produkt_etap_limity
                       (produkt, etap_id, parametr_id, min_limit, max_limit,
                        nawazka_g, precision, target)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (produkt, etap_id, ov["parametr_id"], ov["min_limit"],
                     ov["max_limit"], ov["nawazka_g"], ov.get("precision"),
                     ov.get("target")),
                )
                stats["limity"] += 1

    db.commit()
    return stats


if __name__ == "__main__":
    from mbr.db import get_db
    from mbr.models import init_mbr_tables
    import json

    db = get_db()
    init_mbr_tables(db)
    stats = migrate_parametry_etapy(db)
    print(json.dumps(stats, indent=2))
    db.close()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_pipeline_models.py -v -k "migrate"
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_parametry_etapy.py tests/test_pipeline_models.py
git commit -m "feat: migration script parametry_etapy -> pipeline tables"
```

---

## Task 6: Admin API Routes — Stage Catalog CRUD

**Files:**
- Modify: `mbr/pipeline/routes.py`
- Modify: `mbr/app.py` (register blueprint)
- Test: `tests/test_pipeline_routes.py`

- [ ] **Step 1: Register blueprint in app.py**

In `mbr/app.py`, after the existing blueprint imports (~line 55), add:

```python
from mbr.pipeline import pipeline_bp
```

After the existing `app.register_blueprint(zbiorniki_bp)` line, add:

```python
app.register_blueprint(pipeline_bp)
```

- [ ] **Step 2: Write failing tests for admin API**

```python
# tests/test_pipeline_routes.py
import json
import sqlite3
import pytest
from mbr.app import create_app
from mbr.models import init_mbr_tables


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        from mbr.db import get_db
        db = get_db()
        init_mbr_tables(db)
        db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (1, 'ph', 'pH', 'bezposredni')")
        db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (2, 'sm', 'SM', 'bezposredni')")
        db.commit()
        yield app


@pytest.fixture
def client(app):
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user"] = {"login": "admin1", "rola": "admin", "imie_nazwisko": "Admin"}
        yield c


@pytest.fixture
def non_admin_client(app):
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user"] = {"login": "lab1", "rola": "lab", "imie_nazwisko": "Lab"}
        yield c


def test_create_etap(client):
    resp = client.post("/api/pipeline/etapy", json={
        "kod": "sulfonowanie", "nazwa": "Sulfonowanie", "typ_cyklu": "cykliczny"
    })
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["id"] is not None
    assert data["kod"] == "sulfonowanie"


def test_create_etap_requires_admin(non_admin_client):
    resp = non_admin_client.post("/api/pipeline/etapy", json={
        "kod": "test", "nazwa": "Test"
    })
    assert resp.status_code == 403


def test_list_etapy(client):
    client.post("/api/pipeline/etapy", json={"kod": "a1", "nazwa": "A1"})
    client.post("/api/pipeline/etapy", json={"kod": "a2", "nazwa": "A2"})
    resp = client.get("/api/pipeline/etapy")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) >= 2


def test_get_etap_detail(client):
    r = client.post("/api/pipeline/etapy", json={"kod": "test", "nazwa": "Test"})
    eid = r.get_json()["id"]
    resp = client.get(f"/api/pipeline/etapy/{eid}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["etap"]["kod"] == "test"
    assert "parametry" in data
    assert "warunki" in data
    assert "korekty" in data


def test_update_etap(client):
    r = client.post("/api/pipeline/etapy", json={"kod": "test", "nazwa": "Test"})
    eid = r.get_json()["id"]
    resp = client.put(f"/api/pipeline/etapy/{eid}", json={"nazwa": "Updated"})
    assert resp.status_code == 200


def test_add_parametr_to_etap(client):
    r = client.post("/api/pipeline/etapy", json={"kod": "test", "nazwa": "Test"})
    eid = r.get_json()["id"]
    resp = client.post(f"/api/pipeline/etapy/{eid}/parametry", json={
        "parametr_id": 1, "kolejnosc": 1, "min_limit": 3.0, "max_limit": 9.0
    })
    assert resp.status_code == 201


def test_add_warunek(client):
    r = client.post("/api/pipeline/etapy", json={"kod": "test", "nazwa": "Test"})
    eid = r.get_json()["id"]
    resp = client.post(f"/api/pipeline/etapy/{eid}/warunki", json={
        "parametr_id": 1, "operator": "<", "wartosc": 0.1,
        "opis_warunku": "Test condition"
    })
    assert resp.status_code == 201


def test_add_korekta(client):
    r = client.post("/api/pipeline/etapy", json={"kod": "test", "nazwa": "Test"})
    eid = r.get_json()["id"]
    resp = client.post(f"/api/pipeline/etapy/{eid}/korekty", json={
        "substancja": "Perhydrol", "jednostka": "kg", "wykonawca": "produkcja"
    })
    assert resp.status_code == 201


def test_pipeline_crud(client):
    r1 = client.post("/api/pipeline/etapy", json={"kod": "e1", "nazwa": "E1"})
    r2 = client.post("/api/pipeline/etapy", json={"kod": "e2", "nazwa": "E2"})
    e1 = r1.get_json()["id"]
    e2 = r2.get_json()["id"]

    # Add to pipeline
    resp = client.post("/api/pipeline/produkt/TestProd/etapy", json={
        "etap_id": e1, "kolejnosc": 1
    })
    assert resp.status_code == 201
    resp = client.post("/api/pipeline/produkt/TestProd/etapy", json={
        "etap_id": e2, "kolejnosc": 2
    })
    assert resp.status_code == 201

    # Get pipeline
    resp = client.get("/api/pipeline/produkt/TestProd")
    data = resp.get_json()
    assert len(data) == 2
    assert data[0]["kod"] == "e1"

    # Reorder
    resp = client.put("/api/pipeline/produkt/TestProd/reorder", json={
        "etap_ids": [e2, e1]
    })
    assert resp.status_code == 200
    resp = client.get("/api/pipeline/produkt/TestProd")
    data = resp.get_json()
    assert data[0]["kod"] == "e2"


def test_produkt_etap_limity(client):
    r = client.post("/api/pipeline/etapy", json={"kod": "test", "nazwa": "Test"})
    eid = r.get_json()["id"]
    client.post(f"/api/pipeline/etapy/{eid}/parametry", json={
        "parametr_id": 1, "kolejnosc": 1, "min_limit": 3.0, "max_limit": 9.0
    })
    client.post("/api/pipeline/produkt/TestProd/etapy", json={
        "etap_id": eid, "kolejnosc": 1
    })

    # Set override
    resp = client.put(f"/api/pipeline/produkt/TestProd/etapy/{eid}/limity", json={
        "overrides": [{"parametr_id": 1, "min_limit": 5.0, "max_limit": 7.0}]
    })
    assert resp.status_code == 200

    # Get resolved
    resp = client.get(f"/api/pipeline/produkt/TestProd/etapy/{eid}/resolved")
    data = resp.get_json()
    assert data[0]["min_limit"] == 5.0
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_pipeline_routes.py -v
```
Expected: FAIL — routes not implemented.

- [ ] **Step 4: Implement admin API routes**

```python
# mbr/pipeline/routes.py
from flask import request, jsonify
from mbr.pipeline import pipeline_bp
from mbr.shared.decorators import role_required
from mbr.db import get_db
from mbr.pipeline import models as pm


# ---------------------------------------------------------------------------
# Stage catalog CRUD
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/etapy", methods=["GET"])
@role_required("admin")
def api_list_etapy():
    db = get_db()
    return jsonify(pm.list_etapy(db))


@pipeline_bp.route("/api/pipeline/etapy", methods=["POST"])
@role_required("admin")
def api_create_etap():
    db = get_db()
    data = request.get_json()
    eid = pm.create_etap(
        db, kod=data["kod"], nazwa=data["nazwa"],
        typ_cyklu=data.get("typ_cyklu", "jednorazowy"),
        opis=data.get("opis"),
        kolejnosc_domyslna=data.get("kolejnosc_domyslna", 0),
    )
    db.commit()
    etap = pm.get_etap(db, eid)
    return jsonify(etap), 201


@pipeline_bp.route("/api/pipeline/etapy/<int:etap_id>", methods=["GET"])
@role_required("admin")
def api_get_etap(etap_id):
    db = get_db()
    etap = pm.get_etap(db, etap_id)
    if not etap:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "etap": etap,
        "parametry": pm.list_etap_parametry(db, etap_id),
        "warunki": pm.list_etap_warunki(db, etap_id),
        "korekty": pm.list_etap_korekty(db, etap_id),
    })


@pipeline_bp.route("/api/pipeline/etapy/<int:etap_id>", methods=["PUT"])
@role_required("admin")
def api_update_etap(etap_id):
    db = get_db()
    data = request.get_json()
    pm.update_etap(db, etap_id, **data)
    db.commit()
    return jsonify(pm.get_etap(db, etap_id))


@pipeline_bp.route("/api/pipeline/etapy/<int:etap_id>/deactivate", methods=["POST"])
@role_required("admin")
def api_deactivate_etap(etap_id):
    db = get_db()
    pm.deactivate_etap(db, etap_id)
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Stage parameters
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/etapy/<int:etap_id>/parametry", methods=["POST"])
@role_required("admin")
def api_add_etap_parametr(etap_id):
    db = get_db()
    data = request.get_json()
    epid = pm.add_etap_parametr(db, etap_id, data["parametr_id"],
                                kolejnosc=data.get("kolejnosc", 0),
                                **{k: data[k] for k in
                                   ("min_limit", "max_limit", "nawazka_g", "precision",
                                    "target", "wymagany", "grupa", "formula", "sa_bias", "krok")
                                   if k in data})
    db.commit()
    return jsonify({"id": epid}), 201


@pipeline_bp.route("/api/pipeline/etapy/<int:etap_id>/parametry/<int:ep_id>", methods=["PUT"])
@role_required("admin")
def api_update_etap_parametr(etap_id, ep_id):
    db = get_db()
    data = request.get_json()
    pm.update_etap_parametr(db, ep_id, **data)
    db.commit()
    return jsonify({"ok": True})


@pipeline_bp.route("/api/pipeline/etapy/<int:etap_id>/parametry/<int:ep_id>", methods=["DELETE"])
@role_required("admin")
def api_delete_etap_parametr(etap_id, ep_id):
    db = get_db()
    pm.remove_etap_parametr(db, ep_id)
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Gate conditions
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/etapy/<int:etap_id>/warunki", methods=["POST"])
@role_required("admin")
def api_add_warunek(etap_id):
    db = get_db()
    data = request.get_json()
    wid = pm.add_etap_warunek(
        db, etap_id, data["parametr_id"], data["operator"], data["wartosc"],
        wartosc_max=data.get("wartosc_max"), opis_warunku=data.get("opis_warunku"),
    )
    db.commit()
    return jsonify({"id": wid}), 201


@pipeline_bp.route("/api/pipeline/warunki/<int:warunek_id>", methods=["DELETE"])
@role_required("admin")
def api_delete_warunek(warunek_id):
    db = get_db()
    pm.remove_etap_warunek(db, warunek_id)
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Correction catalog
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/etapy/<int:etap_id>/korekty", methods=["POST"])
@role_required("admin")
def api_add_korekta(etap_id):
    db = get_db()
    data = request.get_json()
    kid = pm.add_etap_korekta(
        db, etap_id, data["substancja"],
        jednostka=data.get("jednostka", "kg"),
        wykonawca=data.get("wykonawca", "produkcja"),
        kolejnosc=data.get("kolejnosc", 0),
    )
    db.commit()
    return jsonify({"id": kid}), 201


@pipeline_bp.route("/api/pipeline/korekty/<int:korekta_id>", methods=["DELETE"])
@role_required("admin")
def api_delete_korekta(korekta_id):
    db = get_db()
    pm.remove_etap_korekta(db, korekta_id)
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Product pipeline
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/produkt/<produkt>", methods=["GET"])
@role_required("admin")
def api_get_pipeline(produkt):
    db = get_db()
    return jsonify(pm.get_produkt_pipeline(db, produkt))


@pipeline_bp.route("/api/pipeline/produkt/<produkt>/etapy", methods=["POST"])
@role_required("admin")
def api_add_pipeline_etap(produkt):
    db = get_db()
    data = request.get_json()
    pm.set_produkt_pipeline(db, produkt, data["etap_id"], data["kolejnosc"])
    db.commit()
    return jsonify({"ok": True}), 201


@pipeline_bp.route("/api/pipeline/produkt/<produkt>/etapy/<int:etap_id>", methods=["DELETE"])
@role_required("admin")
def api_remove_pipeline_etap(produkt, etap_id):
    db = get_db()
    pm.remove_pipeline_etap(db, produkt, etap_id)
    db.commit()
    return jsonify({"ok": True})


@pipeline_bp.route("/api/pipeline/produkt/<produkt>/reorder", methods=["PUT"])
@role_required("admin")
def api_reorder_pipeline(produkt):
    db = get_db()
    data = request.get_json()
    pm.reorder_pipeline(db, produkt, data["etap_ids"])
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Product limit overrides
# ---------------------------------------------------------------------------

@pipeline_bp.route("/api/pipeline/produkt/<produkt>/etapy/<int:etap_id>/limity", methods=["PUT"])
@role_required("admin")
def api_set_limity(produkt, etap_id):
    db = get_db()
    data = request.get_json()
    for ov in data.get("overrides", []):
        pm.set_produkt_etap_limit(db, produkt, etap_id, ov["parametr_id"], **{
            k: ov[k] for k in ("min_limit", "max_limit", "nawazka_g", "precision", "target")
            if k in ov
        })
    db.commit()
    return jsonify({"ok": True})


@pipeline_bp.route("/api/pipeline/produkt/<produkt>/etapy/<int:etap_id>/resolved", methods=["GET"])
@role_required("admin")
def api_get_resolved(produkt, etap_id):
    db = get_db()
    return jsonify(pm.resolve_limity(db, produkt, etap_id))


# ---------------------------------------------------------------------------
# Admin UI pages
# ---------------------------------------------------------------------------

@pipeline_bp.route("/admin/pipeline")
@role_required("admin")
def pipeline_admin():
    from flask import render_template
    return render_template("pipeline/etapy_katalog.html")


@pipeline_bp.route("/admin/pipeline/etap/<int:etap_id>")
@role_required("admin")
def pipeline_etap_edit(etap_id):
    from flask import render_template
    return render_template("pipeline/etap_edit.html", etap_id=etap_id)


@pipeline_bp.route("/admin/pipeline/produkt/<produkt>")
@role_required("admin")
def pipeline_produkt(produkt):
    from flask import render_template
    return render_template("pipeline/pipeline_edit.html", produkt=produkt)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_pipeline_routes.py -v
```
Expected: all PASS (some may fail due to `create_app` needing adjustment — check if in-memory DB works with `get_db()` in test context; may need to mock or use app fixture pattern from existing tests).

- [ ] **Step 6: Verify all tests still pass**

```bash
pytest --tb=short -q
```

- [ ] **Step 7: Commit**

```bash
git add mbr/pipeline/routes.py mbr/app.py tests/test_pipeline_routes.py
git commit -m "feat: admin API routes for pipeline builder"
```

---

## Task 7: Admin UI — Stage Catalog Page

**Files:**
- Create: `mbr/templates/pipeline/etapy_katalog.html`

This task creates the admin page listing all analytical stages with create/edit/deactivate actions. The page follows the existing admin panel patterns (server-rendered shell, JS-driven CRUD via fetch to API).

- [ ] **Step 1: Create the template directory**

```bash
mkdir -p mbr/templates/pipeline
```

- [ ] **Step 2: Create etapy_katalog.html**

Build a Jinja2 template that extends the existing base layout. Uses fetch() calls to `/api/pipeline/etapy` endpoints. Renders a table of stages with inline actions. Follows the same CSS patterns used in `parametry_editor.html` (`.pe-tabs`, `.pa-table` class naming).

Key UI elements:
- Table listing all stages (kod, nazwa, typ_cyklu, aktywny status)
- "Dodaj etap" button → inline form row or modal
- Each row: click to navigate to `/admin/pipeline/etap/<id>` for editing
- Deactivate toggle button per row
- Product list with links to `/admin/pipeline/produkt/<produkt>`

The template should use `{% extends "base.html" %}` if it exists, or build a standalone page following the pattern from `parametry_editor.html`. JavaScript logic loads data via API on DOMContentLoaded, renders table rows dynamically.

- [ ] **Step 3: Test manually in browser**

```bash
python -m mbr.app
```
Navigate to `http://localhost:5001/admin/pipeline`. Verify:
- Page loads without errors
- Empty table shows (no stages yet)
- "Dodaj etap" creates a new stage via API
- Clicking a stage row navigates to edit page

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/pipeline/etapy_katalog.html
git commit -m "feat: admin UI — stage catalog page"
```

---

## Task 8: Admin UI — Stage Edit Page

**Files:**
- Create: `mbr/templates/pipeline/etap_edit.html`

Three-panel editor for a single stage: parameters, gate conditions, corrections. Each panel is a table with add/remove actions using the API endpoints from Task 6.

- [ ] **Step 1: Create etap_edit.html**

Key UI elements:

**Panel 1 — Parametry domyslne:**
- Table: #, Parametr (searchable dropdown from `/api/parametry/list`), Min, Max, Nawazka, Bramkowy?, actions
- "Dodaj parametr" button → adds row with dropdown
- Reorder via up/down buttons
- Delete button per row

**Panel 2 — Warunki przejscia (bramka):**
- Table: Parametr, Operator (<, <=, etc.), Wartosc, Wartosc max, Opis
- Only show parameters marked as "bramkowy" in Panel 1
- "Dodaj warunek" button

**Panel 3 — Dozwolone korekty:**
- Table: Substancja (text input), Jednostka, Wykonawca (laborant/produkcja radio), actions
- "Dodaj korekte" button

JavaScript fetches stage detail from `GET /api/pipeline/etapy/<id>`, populates all three panels. Add/delete actions call the appropriate API endpoints and re-render.

- [ ] **Step 2: Test manually in browser**

```bash
python -m mbr.app
```
Navigate to `http://localhost:5001/admin/pipeline/etap/<id>`. Verify all three panels work with CRUD operations.

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/pipeline/etap_edit.html
git commit -m "feat: admin UI — stage edit page (params, gates, corrections)"
```

---

## Task 9: Admin UI — Product Pipeline Editor

**Files:**
- Create: `mbr/templates/pipeline/pipeline_edit.html`

- [ ] **Step 1: Create pipeline_edit.html**

Key UI elements:
- Header: product name, link back to catalog
- Ordered list of stages in pipeline (from `GET /api/pipeline/produkt/<produkt>`)
- Each row: position #, stage name, typ_cyklu badge, up/down buttons, edit-limits button, remove button
- "Dodaj etap z katalogu" dropdown (filtered to active stages not already in pipeline)
- Click edit-limits → inline panel showing default vs override limits (from `GET /api/pipeline/produkt/<produkt>/etapy/<id>/resolved`)
- Override fields: empty = use default, filled = product-specific

- [ ] **Step 2: Test manually in browser**

Navigate to `http://localhost:5001/admin/pipeline/produkt/Chegina_K7`. Verify:
- Pipeline shows stages in order
- Can add/remove stages
- Can reorder via up/down
- Can set product-specific limit overrides

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/pipeline/pipeline_edit.html
git commit -m "feat: admin UI — product pipeline editor with limit overrides"
```

---

## Task 10: Laborant API Routes — Fast Entry v2

**Files:**
- Modify: `mbr/pipeline/lab_routes.py`
- Test: `tests/test_pipeline_lab.py` (append route tests)

- [ ] **Step 1: Write failing tests for laborant API**

Append to `tests/test_pipeline_lab.py`:

```python
from mbr.app import create_app


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    yield app


@pytest.fixture
def lab_client(app):
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user"] = {"login": "lab1", "rola": "lab", "imie_nazwisko": "Lab Tech"}
            sess["shift_workers"] = [{"imie_nazwisko": "Lab Tech"}]
        yield c


def _setup_pipeline_data(app):
    """Seed pipeline data for route tests."""
    with app.app_context():
        from mbr.db import get_db
        db = get_db()
        db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (1, 'so3', 'SO3', 'titracja')")
        db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (2, 'ph', 'pH', 'bezposredni')")
        db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (1, 'sulf', 'Sulfonowanie', 'cykliczny')")
        db.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc, max_limit) VALUES (1, 1, 1, 0.1)")
        db.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (1, 2, 2)")
        db.execute("INSERT INTO etap_warunki (etap_id, parametr_id, operator, wartosc) VALUES (1, 1, '<', 0.1)")
        db.execute("INSERT INTO etap_korekty_katalog (id, etap_id, substancja, jednostka, wykonawca) VALUES (1, 1, 'Perhydrol', 'kg', 'produkcja')")
        db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('TestProd', 1, 1)")
        db.execute("""INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia)
                      VALUES (1, 'TestProd', 1, '2026-01-01')""")
        db.execute("""INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start)
                      VALUES (1, 1, 'T-1', '1/2026', '2026-01-01')""")
        db.commit()


def test_get_etap_form(app, lab_client):
    _setup_pipeline_data(app)
    resp = lab_client.get("/api/pipeline/lab/ebr/1/etap/1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "parametry" in data
    assert "warunki" in data
    assert "korekty_katalog" in data


def test_save_pomiary(app, lab_client):
    _setup_pipeline_data(app)
    with app.app_context():
        from mbr.db import get_db
        from mbr.pipeline.models import create_sesja
        db = get_db()
        create_sesja(db, 1, 1, runda=1, laborant="lab1")
        db.commit()

    resp = lab_client.post("/api/pipeline/lab/ebr/1/etap/1/pomiary", json={
        "sesja_id": 1,
        "pomiary": [
            {"parametr_id": 1, "wartosc": 0.05},
            {"parametr_id": 2, "wartosc": 7.5},
        ]
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["gate"]["passed"] is True


def test_zalec_korekte(app, lab_client):
    _setup_pipeline_data(app)
    with app.app_context():
        from mbr.db import get_db
        from mbr.pipeline.models import create_sesja
        db = get_db()
        create_sesja(db, 1, 1, runda=1, laborant="lab1")
        db.commit()

    resp = lab_client.post("/api/pipeline/lab/ebr/1/korekta", json={
        "sesja_id": 1,
        "korekta_typ_id": 1,
        "ilosc": 5.0,
    })
    assert resp.status_code == 201
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pipeline_lab.py -v -k "test_get_etap_form or test_save_pomiary or test_zalec_korekte"
```

- [ ] **Step 3: Implement laborant API routes**

```python
# mbr/pipeline/lab_routes.py
from flask import request, jsonify
from mbr.pipeline import pipeline_bp
from mbr.shared.decorators import login_required
from mbr.db import get_db
from mbr.pipeline import models as pm


@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/etap/<int:etap_id>", methods=["GET"])
@login_required
def api_lab_get_etap(ebr_id, etap_id):
    db = get_db()
    ebr = db.execute("SELECT * FROM ebr_batches WHERE ebr_id = ?", (ebr_id,)).fetchone()
    if not ebr:
        return jsonify({"error": "batch not found"}), 404

    produkt = db.execute(
        "SELECT produkt FROM mbr_templates WHERE mbr_id = ?", (ebr["mbr_id"],)
    ).fetchone()["produkt"]

    parametry = pm.resolve_limity(db, produkt, etap_id)
    warunki = pm.list_etap_warunki(db, etap_id)
    korekty = pm.list_etap_korekty(db, etap_id)
    sesje = pm.list_sesje(db, ebr_id, etap_id=etap_id)

    current_sesja = None
    pomiary = []
    if sesje:
        current_sesja = sesje[-1]
        pomiary = pm.get_pomiary(db, current_sesja["id"])

    return jsonify({
        "parametry": parametry,
        "warunki": warunki,
        "korekty_katalog": korekty,
        "sesje": sesje,
        "current_sesja": dict(current_sesja) if current_sesja else None,
        "pomiary": pomiary,
    })


@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/etap/<int:etap_id>/start", methods=["POST"])
@login_required
def api_lab_start_sesja(ebr_id, etap_id):
    from flask import session
    db = get_db()
    sesje = pm.list_sesje(db, ebr_id, etap_id=etap_id)
    runda = len(sesje) + 1
    laborant = session["user"]["login"]
    sid = pm.create_sesja(db, ebr_id, etap_id, runda=runda, laborant=laborant)
    db.commit()
    return jsonify({"sesja_id": sid, "runda": runda}), 201


@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/etap/<int:etap_id>/pomiary", methods=["POST"])
@login_required
def api_lab_save_pomiary(ebr_id, etap_id):
    from flask import session
    db = get_db()
    data = request.get_json()
    sesja_id = data["sesja_id"]
    wpisal = session["user"]["login"]

    ebr = db.execute("SELECT * FROM ebr_batches WHERE ebr_id = ?", (ebr_id,)).fetchone()
    produkt = db.execute(
        "SELECT produkt FROM mbr_templates WHERE mbr_id = ?", (ebr["mbr_id"],)
    ).fetchone()["produkt"]
    resolved = {p["parametr_id"]: p for p in pm.resolve_limity(db, produkt, etap_id)}

    for entry in data["pomiary"]:
        pid = entry["parametr_id"]
        wartosc = entry.get("wartosc")
        limits = resolved.get(pid, {})
        pm.save_pomiar(
            db, sesja_id, pid, wartosc,
            min_limit=limits.get("min_limit"),
            max_limit=limits.get("max_limit"),
            wpisal=wpisal,
            is_manual=entry.get("is_manual", 1),
        )

    gate = pm.evaluate_gate(db, etap_id, sesja_id)
    db.commit()
    return jsonify({"gate": gate, "pomiary": pm.get_pomiary(db, sesja_id)})


@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/etap/<int:etap_id>/close", methods=["POST"])
@login_required
def api_lab_close_sesja(ebr_id, etap_id):
    db = get_db()
    data = request.get_json()
    pm.close_sesja(db, data["sesja_id"], decyzja=data["decyzja"])
    db.commit()
    return jsonify({"ok": True})


@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/korekta", methods=["POST"])
@login_required
def api_lab_korekta(ebr_id):
    from flask import session
    db = get_db()
    data = request.get_json()
    kid = pm.create_ebr_korekta(
        db, data["sesja_id"], data["korekta_typ_id"],
        ilosc=data.get("ilosc"), zalecil=session["user"]["login"],
    )
    db.commit()
    return jsonify({"id": kid}), 201


@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/korekta/<int:korekta_id>/status", methods=["PUT"])
@login_required
def api_lab_korekta_status(ebr_id, korekta_id):
    db = get_db()
    data = request.get_json()
    pm.update_ebr_korekta_status(db, korekta_id, data["status"],
                                 wykonawca_info=data.get("wykonawca_info"))
    db.commit()
    return jsonify({"ok": True})


@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/pipeline", methods=["GET"])
@login_required
def api_lab_get_pipeline(ebr_id):
    db = get_db()
    ebr = db.execute("SELECT * FROM ebr_batches WHERE ebr_id = ?", (ebr_id,)).fetchone()
    if not ebr:
        return jsonify({"error": "batch not found"}), 404

    produkt = db.execute(
        "SELECT produkt FROM mbr_templates WHERE mbr_id = ?", (ebr["mbr_id"],)
    ).fetchone()["produkt"]

    pipeline = pm.get_produkt_pipeline(db, produkt)
    sesje = pm.list_sesje(db, ebr_id)
    sesje_by_etap = {}
    for s in sesje:
        sesje_by_etap.setdefault(s["etap_id"], []).append(s)

    result = []
    for step in pipeline:
        etap_sesje = sesje_by_etap.get(step["etap_id"], [])
        last = etap_sesje[-1] if etap_sesje else None
        result.append({
            **step,
            "sesje_count": len(etap_sesje),
            "last_status": last["status"] if last else "pending",
            "last_runda": last["runda"] if last else 0,
        })

    return jsonify(result)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_pipeline_lab.py -v
```

- [ ] **Step 5: Commit**

```bash
git add mbr/pipeline/lab_routes.py tests/test_pipeline_lab.py
git commit -m "feat: laborant API routes (pomiary, gates, corrections)"
```

---

## Task 11: Laborant UI — Fast Entry v2 Shell

**Files:**
- Create: `mbr/templates/pipeline/fast_entry_v2.html`
- Create: `mbr/templates/pipeline/_fast_entry_v2_content.html`

- [ ] **Step 1: Create fast_entry_v2.html**

SPA shell similar to existing `fast_entry.html` but with pipeline-based sidebar:

Key structure:
- **Left sidebar:** Stage list from `GET /api/pipeline/lab/ebr/<id>/pipeline`
  - Each stage shows: name, status icon (circle/dot/checkmark), runda count
  - Active stage highlighted
  - Click to load stage content
- **Main area:** Loads `_fast_entry_v2_content.html` via AJAX
- **Right panel:** Calculator (reuse existing `calculator.js`)

JavaScript on load:
1. Fetch pipeline → render sidebar
2. Find first non-completed stage → load its content
3. Wire up stage clicks to load different stages

- [ ] **Step 2: Create _fast_entry_v2_content.html**

AJAX partial loaded per-stage. Fetches from `GET /api/pipeline/lab/ebr/<id>/etap/<etap_id>`:

Key structure:
- **Stage header:** name, runda badge, status
- **Parameter table:** one row per parameter from resolved limits
  - Input field (type=number, step based on precision)
  - Min/Max display
  - Color coding (green/red based on w_limicie)
  - Auto-save on blur → `POST /api/pipeline/lab/ebr/<id>/etap/<etap_id>/pomiary`
- **Gate status bar:** shows after all required params filled
  - Green: "Warunek spelniony — mozna przejsc dalej" + button "Zatwierdz etap"
  - Red: "Warunek niespelniony" + list of failures + correction panel
- **Correction panel** (shown when gate fails):
  - List of allowed corrections from catalog
  - Input field for amount (ilosc)
  - "Zalec korekte" button → POST to korekta endpoint
- **Round history:** collapsible list of previous rounds with results

- [ ] **Step 3: Test manually in browser**

```bash
python -m mbr.app
```

Create test data via admin UI first (stages, pipeline, batch). Then navigate to fast entry v2 and verify:
- Sidebar shows stages with correct status
- Can enter measurements
- Auto-save works
- Gate evaluation displays correctly
- Can create corrections
- Can start new round after correction
- Can approve stage and move to next

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/pipeline/fast_entry_v2.html mbr/templates/pipeline/_fast_entry_v2_content.html
git commit -m "feat: laborant fast entry v2 UI (stage-based with gates)"
```

---

## Task 12: Integration — Wire Up and End-to-End Test

**Files:**
- Modify: `mbr/templates/pipeline/etapy_katalog.html` (add link in admin nav if needed)
- Test: manual end-to-end flow

- [ ] **Step 1: Run migration on dev database**

```bash
python -m scripts.migrate_parametry_etapy
```

Verify output shows counts for migrated etapy, parametry, pipeline entries, limity.

- [ ] **Step 2: End-to-end test in browser**

Full flow:
1. Login as admin → `/admin/pipeline`
2. Verify migrated stages appear in catalog
3. Click a stage → verify params, warunki, korekty populated from migration
4. Navigate to a product pipeline → verify stages in correct order
5. Adjust a limit override → save → verify it persists
6. Login as laborant → open a batch
7. Navigate to fast entry v2
8. Enter measurements → verify auto-save
9. Trigger gate failure → verify correction panel appears
10. Create correction → start new round → pass gate → approve stage

- [ ] **Step 3: Run full test suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: pipeline builder v1 — integration and migration"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | Schema — 9 new tables | `mbr/models.py`, `tests/test_pipeline_models.py` |
| 2 | Catalog CRUD models | `mbr/pipeline/{__init__,models,routes,lab_routes}.py` |
| 3 | Product pipeline models | `mbr/pipeline/models.py` |
| 4 | EBR execution models | `mbr/pipeline/models.py`, `tests/test_pipeline_lab.py` |
| 5 | Migration script | `scripts/migrate_parametry_etapy.py` |
| 6 | Admin API routes | `mbr/pipeline/routes.py`, `mbr/app.py` |
| 7 | Admin UI — catalog | `mbr/templates/pipeline/etapy_katalog.html` |
| 8 | Admin UI — stage editor | `mbr/templates/pipeline/etap_edit.html` |
| 9 | Admin UI — pipeline editor | `mbr/templates/pipeline/pipeline_edit.html` |
| 10 | Laborant API routes | `mbr/pipeline/lab_routes.py` |
| 11 | Laborant UI — fast entry v2 | `mbr/templates/pipeline/fast_entry_v2.html` |
| 12 | Integration + e2e test | Migration run + manual testing |
