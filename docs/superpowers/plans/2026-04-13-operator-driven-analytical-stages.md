# Operator-Driven Analytical Stages — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the pipeline system from gate-driven to operator-driven flow for sulfonowanie/utlenianie/standaryzacja — free navigation, soft close, multi-substance correction orders, rename target→spec_value.

**Architecture:** Evolve existing pipeline tables and endpoints. Add `ebr_korekta_zlecenie` grouping table, extend `ebr_korekta_v2` with `zlecenie_id`/`ilosc_wyliczona`, rename `target` columns to `spec_value`, simplify decision endpoint, add correction order + formula hint endpoints.

**Tech Stack:** Python/Flask, SQLite, Jinja2 templates, vanilla JS frontend

**Spec:** `docs/superpowers/specs/2026-04-13-operator-driven-analytical-stages-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `mbr/models.py:510-621` | Table DDL: rename target→spec_value, new `ebr_korekta_zlecenie`, extend `ebr_korekta_v2`, update `ebr_etap_sesja` CHECK |
| Modify | `mbr/pipeline/models.py:344-686` | CRUD: rename target→spec_value in `resolve_limity()`, new zlecenie CRUD, formula hint helper, simplified session status |
| Modify | `mbr/pipeline/lab_routes.py:21-246` | Endpoints: simplify decision, add zlecenie-korekty, wykonaj-korekte, formula-hint |
| Modify | `mbr/pipeline/adapter.py:130,182,192-388` | Context builder: rename target→spec_value |
| Modify | `mbr/templates/laborant/_fast_entry_content.html:38-47,1135-1320,2617-2875,3128-3156,3809-3838` | Frontend: rename Cele→Specyfikacja, new correction order form, simplified decision buttons, round history |
| Create | `scripts/migrate_target_to_spec.py` | One-time migration script |
| Modify | `tests/test_pipeline_models.py` | Tests for renamed fields, new CRUD |
| Modify | `tests/test_pipeline_lab.py` | Tests for new session logic |
| Modify | `tests/test_pipeline_routes.py` | Tests for new/modified endpoints |
| Modify | `tests/test_pipeline_adapter.py` | Tests for renamed context fields |

---

### Task 1: DB Schema — New `ebr_korekta_zlecenie` table + extend `ebr_korekta_v2`

**Files:**
- Modify: `mbr/models.py:609-621`
- Test: `tests/test_pipeline_models.py`

- [ ] **Step 1: Write failing test for new table**

```python
# tests/test_pipeline_models.py — add at end of file

def test_ebr_korekta_zlecenie_table_exists(db):
    """ebr_korekta_zlecenie table should exist after init."""
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ebr_korekta_zlecenie'"
    ).fetchone()
    assert row is not None

def test_ebr_korekta_v2_has_zlecenie_columns(db):
    """ebr_korekta_v2 should have zlecenie_id and ilosc_wyliczona columns."""
    info = db.execute("PRAGMA table_info(ebr_korekta_v2)").fetchall()
    col_names = [r["name"] for r in info]
    assert "zlecenie_id" in col_names
    assert "ilosc_wyliczona" in col_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_models.py::test_ebr_korekta_zlecenie_table_exists tests/test_pipeline_models.py::test_ebr_korekta_v2_has_zlecenie_columns -v`
Expected: FAIL — table/columns don't exist

- [ ] **Step 3: Add DDL to `mbr/models.py`**

In `init_mbr_tables()`, after the existing `ebr_korekta_v2` CREATE TABLE block (around line 621), add:

```python
cur.execute("""
    CREATE TABLE IF NOT EXISTS ebr_korekta_zlecenie (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        sesja_id        INTEGER NOT NULL REFERENCES ebr_etap_sesja(id),
        zalecil         TEXT NOT NULL,
        dt_zalecenia    TEXT NOT NULL DEFAULT (datetime('now')),
        dt_wykonania    TEXT,
        status          TEXT NOT NULL DEFAULT 'zalecona'
                        CHECK(status IN ('zalecona', 'wykonana', 'anulowana')),
        komentarz       TEXT
    )
""")
```

Also add the two new columns to `ebr_korekta_v2`. Since SQLite doesn't support `ADD COLUMN IF NOT EXISTS`, use the existing try/except pattern from the codebase:

```python
for col, typ in [("zlecenie_id", "INTEGER REFERENCES ebr_korekta_zlecenie(id)"),
                 ("ilosc_wyliczona", "REAL")]:
    try:
        cur.execute(f"ALTER TABLE ebr_korekta_v2 ADD COLUMN {col} {typ}")
    except sqlite3.OperationalError:
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pipeline_models.py::test_ebr_korekta_zlecenie_table_exists tests/test_pipeline_models.py::test_ebr_korekta_v2_has_zlecenie_columns -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mbr/models.py tests/test_pipeline_models.py
git commit -m "feat: add ebr_korekta_zlecenie table + extend ebr_korekta_v2"
```

---

### Task 2: DB Schema — Rename `target` → `spec_value`

**Files:**
- Modify: `mbr/models.py:510-550`
- Create: `scripts/migrate_target_to_spec.py`
- Test: `tests/test_pipeline_models.py`

- [ ] **Step 1: Write failing test for renamed column**

```python
# tests/test_pipeline_models.py — add

def test_etap_parametry_has_spec_value(db):
    """etap_parametry should have spec_value column (not target)."""
    info = db.execute("PRAGMA table_info(etap_parametry)").fetchall()
    col_names = [r["name"] for r in info]
    assert "spec_value" in col_names
    assert "target" not in col_names

def test_produkt_etap_limity_has_spec_value(db):
    """produkt_etap_limity should have spec_value column (not target)."""
    info = db.execute("PRAGMA table_info(produkt_etap_limity)").fetchall()
    col_names = [r["name"] for r in info]
    assert "spec_value" in col_names
    assert "target" not in col_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_models.py::test_etap_parametry_has_spec_value tests/test_pipeline_models.py::test_produkt_etap_limity_has_spec_value -v`
Expected: FAIL — column is still `target`

- [ ] **Step 3: Update DDL in `mbr/models.py`**

In `init_mbr_tables()`, change the CREATE TABLE statements:

In `etap_parametry` (around line 520): replace `target REAL,` with `spec_value REAL,`

In `produkt_etap_limity` (around line 547): replace `target REAL,` with `spec_value REAL,`

Add migration for existing DBs (after CREATE TABLE blocks):

```python
for table in ("etap_parametry", "produkt_etap_limity"):
    info = cur.execute(f"PRAGMA table_info({table})").fetchall()
    col_names = [r[1] for r in info]
    if "target" in col_names and "spec_value" not in col_names:
        cur.execute(f"ALTER TABLE {table} RENAME COLUMN target TO spec_value")
```

- [ ] **Step 4: Create migration script `scripts/migrate_target_to_spec.py`**

```python
#!/usr/bin/env python3
"""One-time migration: rename target → spec_value in etap_parametry and produkt_etap_limity."""
import sqlite3, sys, os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "batch_db.sqlite")

def migrate():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    for table in ("etap_parametry", "produkt_etap_limity"):
        info = db.execute(f"PRAGMA table_info({table})").fetchall()
        col_names = [r["name"] for r in info]
        if "target" in col_names and "spec_value" not in col_names:
            db.execute(f"ALTER TABLE {table} RENAME COLUMN target TO spec_value")
            print(f"Renamed target → spec_value in {table}")
        elif "spec_value" in col_names:
            print(f"{table}: already has spec_value, skipping")
        else:
            print(f"{table}: no target column found, skipping")
    db.commit()
    db.close()

if __name__ == "__main__":
    migrate()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pipeline_models.py::test_etap_parametry_has_spec_value tests/test_pipeline_models.py::test_produkt_etap_limity_has_spec_value -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add mbr/models.py scripts/migrate_target_to_spec.py tests/test_pipeline_models.py
git commit -m "feat: rename target → spec_value in etap_parametry and produkt_etap_limity"
```

---

### Task 3: DB Schema — Update `ebr_etap_sesja` status CHECK constraint

**Files:**
- Modify: `mbr/models.py:578-591`
- Test: `tests/test_pipeline_models.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_pipeline_models.py — add

def test_ebr_etap_sesja_accepts_new_statuses(db):
    """ebr_etap_sesja should accept nierozpoczety, w_trakcie, zamkniety statuses."""
    db.execute("INSERT INTO etapy_analityczne (kod, nazwa, typ_cyklu) VALUES ('test_ea','Test','jednorazowy')")
    db.execute("INSERT INTO ebr_batches (produkt, nr_szarzy) VALUES ('TEST','T-001')")
    ebr_id = db.execute("SELECT ebr_id FROM ebr_batches WHERE nr_szarzy='T-001'").fetchone()["ebr_id"]
    etap_id = db.execute("SELECT id FROM etapy_analityczne WHERE kod='test_ea'").fetchone()["id"]

    for status in ("nierozpoczety", "w_trakcie", "zamkniety"):
        db.execute(
            "INSERT INTO ebr_etap_sesja (ebr_id, etap_id, runda, status) VALUES (?,?,?,?)",
            (ebr_id, etap_id, 1, status),
        )
    assert True  # no IntegrityError
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_models.py::test_ebr_etap_sesja_accepts_new_statuses -v`
Expected: FAIL — CHECK constraint rejects `nierozpoczety`/`zamkniety`

- [ ] **Step 3: Update DDL in `mbr/models.py`**

Change the `ebr_etap_sesja` CHECK constraint (around line 585) from:

```sql
CHECK(status IN ('w_trakcie', 'ok', 'poza_limitem', 'oczekuje_korekty'))
```

to:

```sql
CHECK(status IN ('nierozpoczety', 'w_trakcie', 'zamkniety'))
```

Since SQLite can't ALTER CHECK constraints, existing DBs need a migration. Add after CREATE TABLE:

```python
row = cur.execute(
    "SELECT sql FROM sqlite_master WHERE type='table' AND name='ebr_etap_sesja'"
).fetchone()
if row and "oczekuje_korekty" in (row[0] or ""):
    cur.execute("UPDATE ebr_etap_sesja SET status='w_trakcie' WHERE status IN ('ok','poza_limitem','oczekuje_korekty')")
```

Note: SQLite doesn't enforce CHECK constraints on existing rows after table creation, so old rows with legacy statuses will persist. The UPDATE above normalizes them. New inserts use the new DDL.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_models.py::test_ebr_etap_sesja_accepts_new_statuses -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mbr/models.py tests/test_pipeline_models.py
git commit -m "feat: update ebr_etap_sesja status values to operator-driven model"
```

---

### Task 4: Backend — Rename `target` → `spec_value` in `resolve_limity()` and adapter

**Files:**
- Modify: `mbr/pipeline/models.py:630-686`
- Modify: `mbr/pipeline/adapter.py:130,182`
- Test: `tests/test_pipeline_lab.py`, `tests/test_pipeline_adapter.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_pipeline_lab.py — add or modify existing test

def test_resolve_limity_returns_spec_value(db, setup_pipeline):
    """resolve_limity should return spec_value key, not target."""
    from mbr.pipeline.models import resolve_limity
    result = resolve_limity(db, "TEST_PROD", setup_pipeline["etap1_id"])
    assert len(result) > 0
    assert "spec_value" in result[0]
    assert "target" not in result[0]
```

```python
# tests/test_pipeline_adapter.py — add or modify existing test

def test_build_pipeline_context_uses_spec_value(db, setup_adapter):
    """Adapter context should use spec_value, not target."""
    from mbr.pipeline.adapter import build_pipeline_context
    ctx = build_pipeline_context(db, "TEST_PROD")
    assert ctx is not None
    for key, section in ctx["parametry_lab"].items():
        for pole in section["pola"]:
            if "spec_value" in pole or "target" in pole:
                assert "spec_value" in pole
                assert "target" not in pole
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pipeline_lab.py::test_resolve_limity_returns_spec_value tests/test_pipeline_adapter.py::test_build_pipeline_context_uses_spec_value -v`
Expected: FAIL — still returns `target`

- [ ] **Step 3: Update `resolve_limity()` in `mbr/pipeline/models.py`**

In the SQL query (around line 650): rename `ep.target AS cat_target` → `ep.spec_value AS cat_spec` and `pel.target AS ovr_target` → `pel.spec_value AS ovr_spec`.

In the result dict construction (around line 680): change:
```python
"target": r["ovr_target"] if r["ovr_target"] is not None else r["cat_target"],
```
to:
```python
"spec_value": r["ovr_spec"] if r["ovr_spec"] is not None else r["cat_spec"],
```

- [ ] **Step 4: Update adapter `_build_pole()` in `mbr/pipeline/adapter.py`**

At line 130, change:
```python
"target": param["target"],
```
to:
```python
"spec_value": param["spec_value"],
```

At line 182, change:
```python
"target": None,
```
to:
```python
"spec_value": None,
```

- [ ] **Step 5: Search and update any other `target` references in pipeline code**

Run `grep -rn '"target"' mbr/pipeline/` and update remaining references. Also update `pipeline_dual_write()` if it references `target`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_pipeline_lab.py tests/test_pipeline_adapter.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add mbr/pipeline/models.py mbr/pipeline/adapter.py tests/test_pipeline_lab.py tests/test_pipeline_adapter.py
git commit -m "feat: rename target → spec_value in pipeline models and adapter"
```

---

### Task 5: Backend — Zlecenie korekty CRUD (multi-substance)

**Files:**
- Modify: `mbr/pipeline/models.py`
- Test: `tests/test_pipeline_models.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_pipeline_models.py — add

def test_create_zlecenie_korekty(db, setup_pipeline):
    """Create a correction order with multiple items."""
    from mbr.pipeline.models import create_sesja, create_zlecenie_korekty, get_zlecenie

    sesja_id = create_sesja(db, setup_pipeline["ebr_id"], setup_pipeline["etap1_id"], runda=1, laborant="lab1")
    items = [
        {"korekta_typ_id": setup_pipeline["korekta_typ_id_1"], "ilosc": 5.0, "ilosc_wyliczona": 4.8},
        {"korekta_typ_id": setup_pipeline["korekta_typ_id_2"], "ilosc": 2.0, "ilosc_wyliczona": None},
    ]
    zlecenie_id = create_zlecenie_korekty(db, sesja_id, items, zalecil="lab1", komentarz="test")
    db.commit()

    zlecenie = get_zlecenie(db, zlecenie_id)
    assert zlecenie["status"] == "zalecona"
    assert len(zlecenie["items"]) == 2
    assert zlecenie["items"][0]["ilosc"] == 5.0
    assert zlecenie["items"][0]["ilosc_wyliczona"] == 4.8
    assert zlecenie["items"][1]["ilosc_wyliczona"] is None

def test_wykonaj_zlecenie(db, setup_pipeline):
    """Executing a correction order creates a new session (runda+1)."""
    from mbr.pipeline.models import create_sesja, create_zlecenie_korekty, wykonaj_zlecenie, get_zlecenie

    sesja_id = create_sesja(db, setup_pipeline["ebr_id"], setup_pipeline["etap1_id"], runda=1, laborant="lab1")
    items = [{"korekta_typ_id": setup_pipeline["korekta_typ_id_1"], "ilosc": 5.0, "ilosc_wyliczona": None}]
    zlecenie_id = create_zlecenie_korekty(db, sesja_id, items, zalecil="lab1")
    db.commit()

    new_sesja_id = wykonaj_zlecenie(db, zlecenie_id)
    db.commit()

    zlecenie = get_zlecenie(db, zlecenie_id)
    assert zlecenie["status"] == "wykonana"
    assert zlecenie["dt_wykonania"] is not None

    new_sesja = db.execute("SELECT * FROM ebr_etap_sesja WHERE id=?", (new_sesja_id,)).fetchone()
    assert new_sesja["runda"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pipeline_models.py::test_create_zlecenie_korekty tests/test_pipeline_models.py::test_wykonaj_zlecenie -v`
Expected: FAIL — functions don't exist

- [ ] **Step 3: Implement CRUD in `mbr/pipeline/models.py`**

Add after existing correction functions:

```python
def create_zlecenie_korekty(
    db: sqlite3.Connection,
    sesja_id: int,
    items: list[dict],
    zalecil: str,
    komentarz: str | None = None,
) -> int:
    cur = db.execute(
        "INSERT INTO ebr_korekta_zlecenie (sesja_id, zalecil, komentarz) VALUES (?,?,?)",
        (sesja_id, zalecil, komentarz),
    )
    zlecenie_id = cur.lastrowid
    for item in items:
        db.execute(
            """INSERT INTO ebr_korekta_v2
               (sesja_id, korekta_typ_id, ilosc, ilosc_wyliczona, zlecenie_id, zalecil, dt_zalecenia, status)
               VALUES (?,?,?,?,?,?, datetime('now'), 'zalecona')""",
            (sesja_id, item["korekta_typ_id"], item["ilosc"],
             item.get("ilosc_wyliczona"), zlecenie_id, zalecil),
        )
    return zlecenie_id


def get_zlecenie(db: sqlite3.Connection, zlecenie_id: int) -> dict | None:
    row = db.execute(
        "SELECT * FROM ebr_korekta_zlecenie WHERE id=?", (zlecenie_id,)
    ).fetchone()
    if not row:
        return None
    items = db.execute(
        """SELECT kv.*, ek.substancja, ek.jednostka
           FROM ebr_korekta_v2 kv
           JOIN etap_korekty_katalog ek ON ek.id = kv.korekta_typ_id
           WHERE kv.zlecenie_id=?""",
        (zlecenie_id,),
    ).fetchall()
    return {**dict(row), "items": [dict(i) for i in items]}


def wykonaj_zlecenie(db: sqlite3.Connection, zlecenie_id: int) -> int:
    zlecenie = db.execute(
        "SELECT * FROM ebr_korekta_zlecenie WHERE id=?", (zlecenie_id,)
    ).fetchone()
    db.execute(
        "UPDATE ebr_korekta_zlecenie SET status='wykonana', dt_wykonania=datetime('now') WHERE id=?",
        (zlecenie_id,),
    )
    db.execute(
        "UPDATE ebr_korekta_v2 SET status='wykonana', dt_wykonania=datetime('now') WHERE zlecenie_id=?",
        (zlecenie_id,),
    )
    sesja = db.execute(
        "SELECT * FROM ebr_etap_sesja WHERE id=?", (zlecenie["sesja_id"],)
    ).fetchone()
    new_runda = sesja["runda"] + 1
    cur = db.execute(
        """INSERT INTO ebr_etap_sesja (ebr_id, etap_id, runda, status, dt_start, laborant)
           VALUES (?,?,?,'w_trakcie', datetime('now'),?)""",
        (sesja["ebr_id"], sesja["etap_id"], new_runda, sesja["laborant"]),
    )
    return cur.lastrowid


def list_zlecenia_for_sesja(db: sqlite3.Connection, sesja_id: int) -> list[dict]:
    rows = db.execute(
        "SELECT * FROM ebr_korekta_zlecenie WHERE sesja_id=? ORDER BY dt_zalecenia",
        (sesja_id,),
    ).fetchall()
    result = []
    for row in rows:
        items = db.execute(
            """SELECT kv.*, ek.substancja, ek.jednostka
               FROM ebr_korekta_v2 kv
               JOIN etap_korekty_katalog ek ON ek.id = kv.korekta_typ_id
               WHERE kv.zlecenie_id=?""",
            (row["id"],),
        ).fetchall()
        result.append({**dict(row), "items": [dict(i) for i in items]})
    return result
```

- [ ] **Step 4: Update `setup_pipeline` fixture if needed**

Ensure the test fixture creates at least 2 `etap_korekty_katalog` entries so `korekta_typ_id_1` and `korekta_typ_id_2` are available. Check the existing fixture in `tests/test_pipeline_models.py` and extend it.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pipeline_models.py::test_create_zlecenie_korekty tests/test_pipeline_models.py::test_wykonaj_zlecenie -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add mbr/pipeline/models.py tests/test_pipeline_models.py
git commit -m "feat: multi-substance correction order CRUD (zlecenie korekty)"
```

---

### Task 6: Backend — Formula hint helper

**Files:**
- Modify: `mbr/pipeline/models.py`
- Test: `tests/test_pipeline_models.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_pipeline_models.py — add

def test_compute_formula_hint(db, setup_pipeline):
    """Formula hint should compute amount from formula_ilosc."""
    from mbr.pipeline.models import compute_formula_hint

    # Setup: etap_korekty_katalog with formula_ilosc
    db.execute(
        """UPDATE etap_korekty_katalog
           SET formula_ilosc = ':masa_wsadu * (:spec - :wynik) / 100',
               formula_zmienne = 'masa_wsadu,spec,wynik'
           WHERE id = ?""",
        (setup_pipeline["korekta_typ_id_1"],)
    )
    db.commit()

    result = compute_formula_hint(
        db,
        korekta_typ_id=setup_pipeline["korekta_typ_id_1"],
        zmienne={"masa_wsadu": 1000, "spec": 12.0, "wynik": 10.0},
    )
    assert result is not None
    assert abs(result - 20.0) < 0.01  # 1000 * (12-10) / 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_models.py::test_compute_formula_hint -v`
Expected: FAIL — function doesn't exist

- [ ] **Step 3: Implement `compute_formula_hint()`**

```python
def compute_formula_hint(
    db: sqlite3.Connection,
    korekta_typ_id: int,
    zmienne: dict[str, float],
) -> float | None:
    row = db.execute(
        "SELECT formula_ilosc, formula_zmienne FROM etap_korekty_katalog WHERE id=?",
        (korekta_typ_id,),
    ).fetchone()
    if not row or not row["formula_ilosc"]:
        return None

    formula = row["formula_ilosc"]
    for key, val in zmienne.items():
        formula = formula.replace(f":{key}", str(float(val)))

    try:
        return eval(formula, {"__builtins__": {}})
    except Exception:
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_models.py::test_compute_formula_hint -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mbr/pipeline/models.py tests/test_pipeline_models.py
git commit -m "feat: formula hint computation for correction amounts"
```

---

### Task 7: Backend — Simplified decision endpoint + new route endpoints

**Files:**
- Modify: `mbr/pipeline/lab_routes.py:189-246`
- Test: `tests/test_pipeline_routes.py`

- [ ] **Step 1: Write failing tests for new endpoints**

```python
# tests/test_pipeline_routes.py — add

def test_zamknij_etap(client, setup_pipeline_route):
    """POST decision with zamknij_etap should set session status to zamkniety."""
    data = setup_pipeline_route
    resp = client.post(
        f"/api/pipeline/lab/ebr/{data['ebr_id']}/etap/{data['etap_id']}/close",
        json={"sesja_id": data["sesja_id"], "decyzja": "zamknij_etap"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

def test_reopen_etap(client, setup_pipeline_route):
    """POST decision with reopen_etap should set session status to w_trakcie."""
    data = setup_pipeline_route
    # First close
    client.post(
        f"/api/pipeline/lab/ebr/{data['ebr_id']}/etap/{data['etap_id']}/close",
        json={"sesja_id": data["sesja_id"], "decyzja": "zamknij_etap"},
    )
    # Then reopen
    resp = client.post(
        f"/api/pipeline/lab/ebr/{data['ebr_id']}/etap/{data['etap_id']}/close",
        json={"sesja_id": data["sesja_id"], "decyzja": "reopen_etap"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

def test_zlecenie_korekty_endpoint(client, setup_pipeline_route):
    """POST zlecenie-korekty should create multi-substance correction order."""
    data = setup_pipeline_route
    resp = client.post(
        f"/api/pipeline/lab/ebr/{data['ebr_id']}/zlecenie-korekty",
        json={
            "sesja_id": data["sesja_id"],
            "items": [
                {"korekta_typ_id": data["korekta_typ_id"], "ilosc": 5.0},
            ],
            "komentarz": "test korekta",
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert "zlecenie_id" in body

def test_wykonaj_korekte_endpoint(client, setup_pipeline_route):
    """POST wykonaj-korekte should mark order as executed and create new session."""
    data = setup_pipeline_route
    # Create zlecenie first
    resp1 = client.post(
        f"/api/pipeline/lab/ebr/{data['ebr_id']}/zlecenie-korekty",
        json={
            "sesja_id": data["sesja_id"],
            "items": [{"korekta_typ_id": data["korekta_typ_id"], "ilosc": 5.0}],
        },
    )
    zlecenie_id = resp1.get_json()["zlecenie_id"]

    resp2 = client.post(
        f"/api/pipeline/lab/ebr/{data['ebr_id']}/wykonaj-korekte",
        json={"zlecenie_id": zlecenie_id},
    )
    assert resp2.status_code == 200
    body = resp2.get_json()
    assert body["ok"] is True
    assert "new_sesja_id" in body

def test_formula_hint_endpoint(client, setup_pipeline_route):
    """GET formula-hint should return computed amount."""
    data = setup_pipeline_route
    resp = client.get(
        f"/api/pipeline/lab/formula-hint",
        query_string={
            "korekta_typ_id": data["korekta_typ_id"],
            "masa_wsadu": 1000,
            "spec": 12.0,
            "wynik": 10.0,
        },
    )
    assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pipeline_routes.py::test_zamknij_etap tests/test_pipeline_routes.py::test_reopen_etap tests/test_pipeline_routes.py::test_zlecenie_korekty_endpoint tests/test_pipeline_routes.py::test_wykonaj_korekte_endpoint tests/test_pipeline_routes.py::test_formula_hint_endpoint -v`
Expected: FAIL

- [ ] **Step 3: Update decision endpoint in `mbr/pipeline/lab_routes.py`**

Modify `lab_close_sesja()` (around line 189) to handle new decision values:

```python
@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/etap/<int:etap_id>/close", methods=["POST"])
@login_required
def lab_close_sesja(ebr_id, etap_id):
    data = request.get_json(force=True) or {}
    sesja_id = data.get("sesja_id")
    decyzja = data.get("decyzja")

    db = get_db()
    try:
        if decyzja == "zamknij_etap":
            db.execute(
                "UPDATE ebr_etap_sesja SET status='zamkniety', dt_end=datetime('now') WHERE id=?",
                (sesja_id,),
            )
        elif decyzja == "reopen_etap":
            db.execute(
                "UPDATE ebr_etap_sesja SET status='w_trakcie', dt_end=NULL WHERE id=?",
                (sesja_id,),
            )
        else:
            pm.close_sesja(db, sesja_id, decyzja, komentarz=data.get("komentarz"))
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()
```

- [ ] **Step 4: Add new endpoints**

```python
@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/zlecenie-korekty", methods=["POST"])
@login_required
def lab_zlecenie_korekty(ebr_id):
    data = request.get_json(force=True) or {}
    sesja_id = data["sesja_id"]
    items = data["items"]
    komentarz = data.get("komentarz")
    zalecil = session.get("user", "unknown")

    db = get_db()
    try:
        zlecenie_id = pm.create_zlecenie_korekty(
            db, sesja_id, items, zalecil=zalecil, komentarz=komentarz,
        )
        db.commit()
        zlecenie = pm.get_zlecenie(db, zlecenie_id)
        return jsonify({"ok": True, "zlecenie_id": zlecenie_id, "zlecenie": zlecenie})
    finally:
        db.close()


@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/wykonaj-korekte", methods=["POST"])
@login_required
def lab_wykonaj_korekte(ebr_id):
    data = request.get_json(force=True) or {}
    zlecenie_id = data["zlecenie_id"]

    db = get_db()
    try:
        new_sesja_id = pm.wykonaj_zlecenie(db, zlecenie_id)
        db.commit()
        return jsonify({"ok": True, "new_sesja_id": new_sesja_id})
    finally:
        db.close()


@pipeline_bp.route("/api/pipeline/lab/formula-hint", methods=["GET"])
@login_required
def lab_formula_hint():
    korekta_typ_id = request.args.get("korekta_typ_id", type=int)
    zmienne = {k: float(v) for k, v in request.args.items() if k != "korekta_typ_id"}

    db = get_db()
    try:
        result = pm.compute_formula_hint(db, korekta_typ_id, zmienne)
        return jsonify({"ok": True, "hint": result})
    finally:
        db.close()
```

- [ ] **Step 5: Update `save_pomiar` / `lab_save_pomiary` to auto-set status `w_trakcie`**

In `lab_save_pomiary()` (around line 133), after saving measurements add:

```python
db.execute(
    "UPDATE ebr_etap_sesja SET status='w_trakcie' WHERE id=? AND status='nierozpoczety'",
    (sesja_id,),
)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_pipeline_routes.py -v`
Expected: PASS (all new + existing tests)

- [ ] **Step 7: Commit**

```bash
git add mbr/pipeline/lab_routes.py tests/test_pipeline_routes.py
git commit -m "feat: operator-driven decision endpoint + zlecenie/wykonaj/formula-hint routes"
```

---

### Task 8: Frontend — Rename Cele → Specyfikacja

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html:38-47,3128-3156,3809-3838`

- [ ] **Step 1: Rename tab label and container**

At line 38, change:
```html
<div class="rp-tab" id="tab-cele" onclick="showRightPanel('cele')">Cele</div>
```
to:
```html
<div class="rp-tab" id="tab-spec" onclick="showRightPanel('spec')">Specyfikacja</div>
```

At lines 42-47, change `id="rp-cele"` to `id="rp-spec"`, change `id="cele-container"` to `id="spec-container"`, change `id="cele-body"` to `id="spec-body"`, change "Cele aktywnego etapu" to "Specyfikacja etapu".

- [ ] **Step 2: Rename `updateCelePanel()` → `updateSpecPanel()`**

At lines 3809-3838, rename function and update element references:
- `function updateCelePanel()` → `function updateSpecPanel()`
- `getElementById('cele-body')` → `getElementById('spec-body')`
- `'Brak celów dla tego etapu'` → `'Brak specyfikacji dla tego etapu'`
- All references to `p.target` → `p.spec_value`
- `class="target-edit"` → `class="spec-edit"`

- [ ] **Step 3: Rename `saveTarget()` → `saveSpec()`**

At lines 3128-3156:
- `function saveTarget(input)` → `function saveSpec(input)`
- `body: JSON.stringify({target: val})` → `body: JSON.stringify({spec_value: val})`

- [ ] **Step 4: Update all callsites**

Search for `updateCelePanel` and `saveTarget` in the file and replace:
- `updateCelePanel()` → `updateSpecPanel()` (lines 1455, 1488, 5101, 5107)
- `saveTarget(this)` → `saveSpec(this)` (in the `onblur` handler inside `updateSpecPanel`)
- `showRightPanel('cele')` → `showRightPanel('spec')` wherever used

- [ ] **Step 5: Manually test in browser**

Run: `python -m mbr.app`
Navigate to a batch with pipeline stages. Verify:
- Right panel tab says "Specyfikacja" not "Cele"
- Panel shows spec values
- Editing a spec value saves correctly

- [ ] **Step 6: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: rename Cele → Specyfikacja in UI"
```

---

### Task 9: Frontend — Simplified decision panel with correction order form

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html:1135-1320,2617-2875`

- [ ] **Step 1: Replace decision panel buttons**

Find the existing decision panel rendering (around lines 1135-1187 and 2617-2875). Replace the three buttons (Przejście / Korekta / Mała korekta) with two:

```html
<div class="stage-decision-bar" id="decision-bar-${sekcja}">
    <button class="btn btn-outline" onclick="openCorrectionForm('${sekcja}', ${etapId}, ${sesjaId})">
        Zlecenie korekty
    </button>
    <button class="btn btn-primary" onclick="zamknijEtap(${etapId}, ${sesjaId})">
        Zamknij etap
    </button>
</div>
```

- [ ] **Step 2: Add correction order form (modal/inline)**

Add a collapsible correction form that appears when "Zlecenie korekty" is clicked:

```html
<div id="correction-form-${sekcja}" style="display:none;" class="correction-form">
    <h4>Zlecenie korekty — runda ${runda}</h4>
    <div id="correction-items-${sekcja}">
        <!-- Populated dynamically from etap_korekty_katalog -->
    </div>
    <textarea id="correction-comment-${sekcja}" placeholder="Komentarz (opcjonalnie)" rows="2"></textarea>
    <div style="margin-top:8px;">
        <button class="btn btn-primary" onclick="submitCorrectionOrder('${sekcja}', ${etapId}, ${sesjaId})">Zleć</button>
        <button class="btn btn-outline" onclick="closeCorrectionForm('${sekcja}')">Anuluj</button>
    </div>
</div>
```

- [ ] **Step 3: Implement `openCorrectionForm()` JS function**

```javascript
async function openCorrectionForm(sekcja, etapId, sesjaId) {
    var formDiv = document.getElementById('correction-form-' + sekcja);
    var itemsDiv = document.getElementById('correction-items-' + sekcja);
    formDiv.style.display = 'block';

    // Fetch available corrections for this stage from catalog
    var resp = await fetch('/api/pipeline/lab/etap/' + etapId + '/korekty-katalog');
    var katalog = await resp.json();

    var html = '';
    katalog.forEach(function(k) {
        html += '<div class="correction-item" style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">' +
            '<input type="checkbox" id="corr-check-' + k.id + '" checked>' +
            '<label style="min-width:120px;font-weight:600;">' + k.substancja + ' [' + k.jednostka + ']</label>' +
            '<input type="number" step="0.01" id="corr-amt-' + k.id + '" class="corr-amount" ' +
                'data-korekta-typ-id="' + k.id + '" placeholder="Ilość" style="width:100px;">' +
            '<span id="corr-hint-' + k.id + '" style="color:var(--text-dim);font-size:11px;"></span>' +
        '</div>';
    });
    itemsDiv.innerHTML = html;

    // Fetch formula hints for items that have formulas
    fetchFormulaHints(sekcja, etapId, katalog);
}
```

- [ ] **Step 4: Implement `fetchFormulaHints()` and `submitCorrectionOrder()`**

```javascript
async function fetchFormulaHints(sekcja, etapId, katalog) {
    var pomiary = gatherCurrentMeasurements(sekcja);
    for (var k of katalog) {
        if (!k.formula_ilosc) continue;
        var params = new URLSearchParams({korekta_typ_id: k.id});
        Object.entries(pomiary).forEach(function(e) { params.set(e[0], e[1]); });
        try {
            var resp = await fetch('/api/pipeline/lab/formula-hint?' + params);
            var data = await resp.json();
            if (data.hint != null) {
                document.getElementById('corr-amt-' + k.id).value = data.hint.toFixed(2);
                document.getElementById('corr-hint-' + k.id).textContent = '(wyliczone: ' + data.hint.toFixed(2) + ')';
            }
        } catch(e) {}
    }
}

async function submitCorrectionOrder(sekcja, etapId, sesjaId) {
    var itemsDiv = document.getElementById('correction-items-' + sekcja);
    var checks = itemsDiv.querySelectorAll('input[type=checkbox]:checked');
    var items = [];
    checks.forEach(function(ch) {
        var id = ch.id.replace('corr-check-', '');
        var amtInput = document.getElementById('corr-amt-' + id);
        items.push({
            korekta_typ_id: parseInt(amtInput.dataset.korektaTypId),
            ilosc: parseFloat(amtInput.value) || 0,
        });
    });
    if (items.length === 0) return;

    var komentarz = document.getElementById('correction-comment-' + sekcja).value;
    var ebrId = window._batchEbrId;

    var resp = await fetch('/api/pipeline/lab/ebr/' + ebrId + '/zlecenie-korekty', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sesja_id: sesjaId, items: items, komentarz: komentarz}),
    });
    if (resp.ok) {
        closeCorrectionForm(sekcja);
        reloadBatchData();
    }
}
```

- [ ] **Step 5: Implement `zamknijEtap()` and `reopenEtap()`**

```javascript
async function zamknijEtap(etapId, sesjaId) {
    var ebrId = window._batchEbrId;
    var resp = await fetch('/api/pipeline/lab/ebr/' + ebrId + '/etap/' + etapId + '/close', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sesja_id: sesjaId, decyzja: 'zamknij_etap'}),
    });
    if (resp.ok) reloadBatchData();
}

async function reopenEtap(etapId, sesjaId) {
    var ebrId = window._batchEbrId;
    var resp = await fetch('/api/pipeline/lab/ebr/' + ebrId + '/etap/' + etapId + '/close', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sesja_id: sesjaId, decyzja: 'reopen_etap'}),
    });
    if (resp.ok) reloadBatchData();
}
```

- [ ] **Step 6: Manually test in browser**

Run: `python -m mbr.app`
Test:
- Open a batch, navigate to sulfonowanie
- Click "Zlecenie korekty" — form opens with Na2SO3
- Enter amount, click "Zleć" — order created
- Click "Zamknij etap" — status changes to green
- Click closed etap — reopens

- [ ] **Step 7: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: operator-driven decision panel with multi-substance correction form"
```

---

### Task 10: Frontend — Round history display

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Add round history section to stage panel**

Below the active measurement table in each stage section, add a collapsible round history:

```javascript
function renderRoundHistory(sekcja, sesje) {
    if (!sesje || sesje.length <= 1) return '';
    var html = '<details class="round-history" style="margin-top:12px;">' +
        '<summary style="cursor:pointer;font-size:12px;color:var(--text-dim);">Historia rund (' + sesje.length + ')</summary>';

    sesje.forEach(function(s, idx) {
        var isCurrent = (idx === sesje.length - 1);
        if (isCurrent) return;
        html += '<div class="round-entry" style="padding:8px 12px;border-left:2px solid var(--border-subtle);margin:6px 0;">' +
            '<div style="font-weight:600;font-size:12px;">Runda ' + s.runda + '</div>';

        if (s.pomiary && s.pomiary.length > 0) {
            html += '<table style="font-size:11px;width:100%;margin-top:4px;">';
            s.pomiary.forEach(function(p) {
                html += '<tr><td>' + p.kod + '</td><td style="text-align:right;font-family:var(--mono);">' + (p.wartosc || '—') + '</td></tr>';
            });
            html += '</table>';
        }

        if (s.zlecenia && s.zlecenia.length > 0) {
            s.zlecenia.forEach(function(z) {
                html += '<div style="font-size:11px;color:var(--orange);margin-top:4px;">Korekta: ';
                z.items.forEach(function(item, i) {
                    if (i > 0) html += ', ';
                    html += item.substancja + ' ' + item.ilosc + ' ' + item.jednostka;
                });
                html += '</div>';
            });
        }
        html += '</div>';
    });
    html += '</details>';
    return html;
}
```

- [ ] **Step 2: Integrate into stage rendering**

In the section rendering code, after the measurement table, call `renderRoundHistory()` with session data from `build_pipeline_context()`.

- [ ] **Step 3: Ensure adapter returns round/zlecenie data**

In `mbr/pipeline/adapter.py`, extend context to include per-stage session history with measurements and zlecenia. Add to `build_pipeline_context()`:

```python
from mbr.pipeline.models import list_zlecenia_for_sesja

# Inside the per-stage loop, after building params:
sesje = db.execute(
    "SELECT * FROM ebr_etap_sesja WHERE ebr_id=? AND etap_id=? ORDER BY runda",
    (ebr_id, etap_id),
).fetchall()
```

Note: `build_pipeline_context()` currently doesn't take `ebr_id` — this will need to be passed from the route that calls it, or round history fetched separately via an API call.

- [ ] **Step 4: Manually test in browser**

Create a batch, go through 2+ rounds on a stage, verify history shows previous rounds with measurements and corrections.

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html mbr/pipeline/adapter.py
git commit -m "feat: round history display with measurements and correction orders"
```

---

### Task 11: Backend — Korekty-katalog endpoint for frontend

**Files:**
- Modify: `mbr/pipeline/lab_routes.py`
- Test: `tests/test_pipeline_routes.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_pipeline_routes.py — add

def test_korekty_katalog_endpoint(client, setup_pipeline_route):
    """GET korekty-katalog should return available correction types for a stage."""
    data = setup_pipeline_route
    resp = client.get(f"/api/pipeline/lab/etap/{data['etap_id']}/korekty-katalog")
    assert resp.status_code == 200
    katalog = resp.get_json()
    assert isinstance(katalog, list)
    assert len(katalog) > 0
    assert "substancja" in katalog[0]
    assert "jednostka" in katalog[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_routes.py::test_korekty_katalog_endpoint -v`
Expected: FAIL — 404

- [ ] **Step 3: Implement endpoint**

```python
@pipeline_bp.route("/api/pipeline/lab/etap/<int:etap_id>/korekty-katalog", methods=["GET"])
@login_required
def lab_korekty_katalog(etap_id):
    db = get_db()
    try:
        rows = db.execute(
            """SELECT id, substancja, jednostka, wykonawca, kolejnosc,
                      formula_ilosc, formula_zmienne, formula_opis
               FROM etap_korekty_katalog
               WHERE etap_id = ?
               ORDER BY kolejnosc""",
            (etap_id,),
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        db.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_routes.py::test_korekty_katalog_endpoint -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mbr/pipeline/lab_routes.py tests/test_pipeline_routes.py
git commit -m "feat: korekty-katalog endpoint for correction form"
```

---

### Task 12: Integration test — full sulfonowanie→utlenianie→standaryzacja flow

**Files:**
- Create: `tests/test_operator_flow.py`

- [ ] **Step 1: Write end-to-end test**

```python
"""Integration test: operator-driven flow through sulfonowanie → utlenianie → standaryzacja."""
import sqlite3
import pytest
from mbr.models import init_mbr_tables
from mbr.pipeline.models import (
    create_sesja, save_pomiar, create_zlecenie_korekty,
    wykonaj_zlecenie, get_zlecenie, resolve_limity,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def pipeline(db):
    """Set up 3-stage pipeline: sulfonowanie → utlenianie → standaryzacja."""
    db.execute("INSERT INTO etapy_analityczne (kod, nazwa, typ_cyklu) VALUES ('sulfonowanie','Sulfonowanie','cykliczny')")
    db.execute("INSERT INTO etapy_analityczne (kod, nazwa, typ_cyklu) VALUES ('utlenianie','Utlenianie','cykliczny')")
    db.execute("INSERT INTO etapy_analityczne (kod, nazwa, typ_cyklu) VALUES ('standaryzacja','Standaryzacja','cykliczny')")

    sulf_id = db.execute("SELECT id FROM etapy_analityczne WHERE kod='sulfonowanie'").fetchone()["id"]
    utl_id = db.execute("SELECT id FROM etapy_analityczne WHERE kod='utlenianie'").fetchone()["id"]
    std_id = db.execute("SELECT id FROM etapy_analityczne WHERE kod='standaryzacja'").fetchone()["id"]

    db.execute("INSERT INTO parametry_analityczne (kod, label, typ, jednostka) VALUES ('so3','SO3','oznaczeniowy','%')")
    so3_id = db.execute("SELECT id FROM parametry_analityczne WHERE kod='so3'").fetchone()["id"]

    db.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc, spec_value) VALUES (?,?,1,12.0)", (sulf_id, so3_id))

    db.execute("INSERT INTO etap_korekty_katalog (etap_id, substancja, jednostka, kolejnosc) VALUES (?,'Na2SO3','kg',1)", (sulf_id,))
    na2so3_id = db.execute("SELECT id FROM etap_korekty_katalog WHERE substancja='Na2SO3'").fetchone()["id"]

    db.execute("INSERT INTO ebr_batches (produkt, nr_szarzy) VALUES ('K40GLO','TEST-001')")
    ebr_id = db.execute("SELECT ebr_id FROM ebr_batches WHERE nr_szarzy='TEST-001'").fetchone()["ebr_id"]

    db.commit()
    return {
        "ebr_id": ebr_id, "sulf_id": sulf_id, "utl_id": utl_id, "std_id": std_id,
        "so3_id": so3_id, "na2so3_id": na2so3_id,
    }


def test_full_operator_flow(db, pipeline):
    """Operator flow: sulfonowanie oznaczenie → korekta → runda 2 → zamknij → utlenianie."""
    p = pipeline

    # Runda 1: oznaczenie SO3 = 10.0 (below spec 12.0)
    sesja1 = create_sesja(db, p["ebr_id"], p["sulf_id"], runda=1, laborant="lab1")
    save_pomiar(db, sesja1, p["so3_id"], 10.0)
    db.commit()

    sesja_row = db.execute("SELECT status FROM ebr_etap_sesja WHERE id=?", (sesja1,)).fetchone()
    assert sesja_row["status"] == "w_trakcie"

    # Operator orders correction: Na2SO3 5kg
    zlecenie_id = create_zlecenie_korekty(
        db, sesja1,
        items=[{"korekta_typ_id": p["na2so3_id"], "ilosc": 5.0, "ilosc_wyliczona": None}],
        zalecil="lab1",
    )
    db.commit()

    zlecenie = get_zlecenie(db, zlecenie_id)
    assert zlecenie["status"] == "zalecona"
    assert len(zlecenie["items"]) == 1

    # Correction executed → new session (runda 2)
    sesja2 = wykonaj_zlecenie(db, zlecenie_id)
    db.commit()

    sesja2_row = db.execute("SELECT * FROM ebr_etap_sesja WHERE id=?", (sesja2,)).fetchone()
    assert sesja2_row["runda"] == 2
    assert sesja2_row["status"] == "w_trakcie"

    # Runda 2: SO3 = 12.1 (in spec)
    save_pomiar(db, sesja2, p["so3_id"], 12.1)
    db.commit()

    # Operator closes sulfonowanie
    db.execute("UPDATE ebr_etap_sesja SET status='zamkniety' WHERE id=?", (sesja2,))
    db.commit()

    sesja2_row = db.execute("SELECT status FROM ebr_etap_sesja WHERE id=?", (sesja2,)).fetchone()
    assert sesja2_row["status"] == "zamkniety"

    # Operator can reopen
    db.execute("UPDATE ebr_etap_sesja SET status='w_trakcie' WHERE id=?", (sesja2,))
    db.commit()
    sesja2_row = db.execute("SELECT status FROM ebr_etap_sesja WHERE id=?", (sesja2,)).fetchone()
    assert sesja2_row["status"] == "w_trakcie"

    # Operator starts utlenianie (free navigation — no need to close sulfonowanie first)
    sesja_utl = create_sesja(db, p["ebr_id"], p["utl_id"], runda=1, laborant="lab1")
    db.commit()
    assert sesja_utl is not None


def test_resolve_limity_spec_value(db, pipeline):
    """resolve_limity returns spec_value, not target."""
    p = pipeline
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('K40GLO',?,1)", (p["sulf_id"],))
    db.commit()

    result = resolve_limity(db, "K40GLO", p["sulf_id"])
    assert len(result) > 0
    assert "spec_value" in result[0]
    assert result[0]["spec_value"] == 12.0
    assert "target" not in result[0]
```

- [ ] **Step 2: Run integration test**

Run: `pytest tests/test_operator_flow.py -v`
Expected: PASS (if all previous tasks completed)

- [ ] **Step 3: Commit**

```bash
git add tests/test_operator_flow.py
git commit -m "test: integration test for operator-driven analytical stage flow"
```

---

### Task 13: Run full test suite + manual smoke test

- [ ] **Step 1: Run all tests**

Run: `pytest -v`
Expected: All tests PASS. Fix any regressions from renamed fields.

- [ ] **Step 2: Fix any failures**

Likely regressions: existing tests that reference `target` instead of `spec_value`, or expect old session statuses (`ok`, `poza_limitem`). Update assertions accordingly.

- [ ] **Step 3: Manual smoke test in browser**

Run: `python -m mbr.app`

Test checklist:
- [ ] Open existing batch with pipeline stages
- [ ] Specyfikacja panel shows correctly (not "Cele")
- [ ] Can navigate freely between stages
- [ ] Can enter measurements in any stage
- [ ] Stage turns "w_trakcie" after first measurement
- [ ] "Zlecenie korekty" opens form with correct substances per stage
- [ ] Formula hints prefill for H2O2/H2O/NaCl
- [ ] Multi-substance correction order submits
- [ ] "Wykonaj korektę" creates new round
- [ ] "Zamknij etap" changes status to green
- [ ] Can reopen closed stage
- [ ] Round history shows previous rounds

- [ ] **Step 4: Commit any fixes**

```bash
git add -u
git commit -m "fix: test regressions from operator-driven stage refactor"
```
