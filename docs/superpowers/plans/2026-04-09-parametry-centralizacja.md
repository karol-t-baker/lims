# Centralizacja parametrów analitycznych — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Single source of truth for all analytical parameters — global registry + process bindings + certificate bindings — with three-tab UI in `/parametry` editor.

**Architecture:** Extend `parametry_analityczne` with `name_en`/`method_code`, create `parametry_cert` table for certificate bindings, migrate `cert_config.json` parameters into DB, adapt certificate generator to read from DB. Three-tab UI: Rejestr (global CRUD), Etapy (existing bindings), Świadectwa (cert bindings). Stash `stash@{0}` provides two-tab UI code as starting point.

**Tech Stack:** Python/Flask, SQLite, Jinja2, vanilla JS, pytest

**Spec:** `docs/superpowers/specs/2026-04-09-parametry-centralizacja-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `mbr/models.py` | Modify | Add migrations: `name_en`, `method_code` columns + `parametry_cert` table + `jakosciowy` typ |
| `mbr/parametry/routes.py` | Modify | Admin CRUD endpoints, cert binding endpoints, `is_admin` flag |
| `mbr/templates/parametry_editor.html` | Modify | Three-tab UI (from stash two-tab base) |
| `mbr/certs/generator.py` | Modify | `build_context()` reads params from DB instead of `cert_config.json` |
| `mbr/parametry/seed.py` | Modify | Add `name_en`, `method_code` to PARAMETRY seed list |
| `scripts/migrate_cert_config.py` | Create | One-time migration script: cert_config.json → parametry_cert + enrich parametry_analityczne |
| `tests/test_parametry_cert.py` | Create | Tests for parametry_cert CRUD + cert generator with DB params |
| `tests/test_migrate_cert_config.py` | Create | Tests for migration script |

---

### Task 1: DB migrations — extend parametry_analityczne + create parametry_cert

**Files:**
- Modify: `mbr/models.py:490-560` (migration section)
- Test: `tests/test_parametry_cert.py`

- [ ] **Step 1: Write test for new columns and table**

```python
# tests/test_parametry_cert.py
"""Tests for parametry_cert table and extended parametry_analityczne columns."""

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


def test_parametry_analityczne_has_name_en(db):
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, name_en, method_code) "
        "VALUES ('test', 'Test', 'bezposredni', 'Test EN', 'L999')"
    )
    row = db.execute("SELECT name_en, method_code FROM parametry_analityczne WHERE kod='test'").fetchone()
    assert row["name_en"] == "Test EN"
    assert row["method_code"] == "L999"


def test_parametry_cert_table_exists(db):
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ) VALUES ('sm', 'Sucha masa', 'bezposredni')"
    )
    pa_id = db.execute("SELECT id FROM parametry_analityczne WHERE kod='sm'").fetchone()["id"]
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format) "
        "VALUES ('Chegina_K40GLOL', ?, 1, 'min. 44,0', '1')",
        (pa_id,),
    )
    row = db.execute("SELECT * FROM parametry_cert WHERE produkt='Chegina_K40GLOL'").fetchone()
    assert row["requirement"] == "min. 44,0"
    assert row["format"] == "1"
    assert row["qualitative_result"] is None


def test_parametry_cert_unique_constraint(db):
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ) VALUES ('ph', 'pH', 'bezposredni')"
    )
    pa_id = db.execute("SELECT id FROM parametry_analityczne WHERE kod='ph'").fetchone()["id"]
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc) VALUES ('Prod_A', ?, 1)",
        (pa_id,),
    )
    db.commit()
    with pytest.raises(Exception):
        db.execute(
            "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc) VALUES ('Prod_A', ?, 2)",
            (pa_id,),
        )


def test_jakosciowy_typ_allowed(db):
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ) VALUES ('zapach', 'Zapach', 'jakosciowy')"
    )
    db.commit()
    row = db.execute("SELECT typ FROM parametry_analityczne WHERE kod='zapach'").fetchone()
    assert row["typ"] == "jakosciowy"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/tbk/Desktop/aa && python -m pytest tests/test_parametry_cert.py -v`
Expected: FAIL — `name_en` column doesn't exist, `parametry_cert` table doesn't exist

- [ ] **Step 3: Add migrations to models.py**

Add after the existing migration block (after line ~558 in `mbr/models.py`):

```python
    # Migration: add name_en to parametry_analityczne (English name for certificates)
    try:
        db.execute("ALTER TABLE parametry_analityczne ADD COLUMN name_en TEXT")
        db.commit()
    except Exception:
        pass

    # Migration: add method_code to parametry_analityczne (lab method code e.g. L928)
    try:
        db.execute("ALTER TABLE parametry_analityczne ADD COLUMN method_code TEXT")
        db.commit()
    except Exception:
        pass

    # Migration: create parametry_cert table (certificate parameter bindings)
    db.execute("""
        CREATE TABLE IF NOT EXISTS parametry_cert (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            produkt             TEXT NOT NULL,
            parametr_id         INTEGER NOT NULL REFERENCES parametry_analityczne(id),
            kolejnosc           INTEGER DEFAULT 0,
            requirement         TEXT,
            format              TEXT DEFAULT '1',
            qualitative_result  TEXT,
            UNIQUE(produkt, parametr_id)
        )
    """)
    db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tbk/Desktop/aa && python -m pytest tests/test_parametry_cert.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add mbr/models.py tests/test_parametry_cert.py
git commit -m "feat: add parametry_cert table + name_en/method_code columns"
```

---

### Task 2: Migration script — cert_config.json → DB

**Files:**
- Create: `scripts/migrate_cert_config.py`
- Test: `tests/test_migrate_cert_config.py`

- [ ] **Step 1: Write test for migration**

```python
# tests/test_migrate_cert_config.py
"""Tests for cert_config.json → parametry_cert migration."""

import json
import sqlite3
import pytest
from mbr.models import init_mbr_tables


SAMPLE_CONFIG = {
    "products": {
        "Test_Prod": {
            "display_name": "Test Prod",
            "spec_number": "P100",
            "cas_number": "123-45-6",
            "expiry_months": 12,
            "opinion_pl": "Produkt OK",
            "opinion_en": "Product OK",
            "parameters": [
                {
                    "id": "barwa_hz",
                    "name_pl": "Barwa w skali Hazena",
                    "name_en": "Colour (Hazen scale)",
                    "requirement": "max 150",
                    "method": "L928",
                    "data_field": "barwa_hz",
                    "format": "0"
                },
                {
                    "id": "odour",
                    "name_pl": "Zapach",
                    "name_en": "Odour",
                    "requirement": "słaby /faint",
                    "method": "organoleptycznie /organoleptic",
                    "data_field": None,
                    "qualitative_result": "zgodny /right"
                },
                {
                    "id": "sm",
                    "name_pl": "Sucha masa [%]",
                    "name_en": "Dry matter [%]",
                    "requirement": "min. 44,0",
                    "method": "L903",
                    "data_field": "sm",
                    "format": "1"
                }
            ],
            "variants": []
        }
    }
}


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    # Seed some existing parameters
    conn.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, precision) "
        "VALUES ('barwa_hz', 'Barwa Hazena', 'bezposredni', 0)"
    )
    conn.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, precision) "
        "VALUES ('sm', 'Sucha masa', 'bezposredni', 1)"
    )
    conn.commit()
    yield conn
    conn.close()


def _run_migration(db, config):
    """Inline migration logic for testing."""
    from scripts.migrate_cert_config import migrate
    migrate(db, config)


def test_migration_creates_cert_bindings(db):
    _run_migration(db, SAMPLE_CONFIG)
    rows = db.execute(
        "SELECT * FROM parametry_cert WHERE produkt='Test_Prod' ORDER BY kolejnosc"
    ).fetchall()
    assert len(rows) == 3
    assert rows[0]["requirement"] == "max 150"
    assert rows[0]["format"] == "0"
    assert rows[1]["qualitative_result"] == "zgodny /right"
    assert rows[2]["requirement"] == "min. 44,0"


def test_migration_enriches_name_en(db):
    _run_migration(db, SAMPLE_CONFIG)
    row = db.execute("SELECT name_en, method_code FROM parametry_analityczne WHERE kod='barwa_hz'").fetchone()
    assert row["name_en"] == "Colour (Hazen scale)"
    assert row["method_code"] == "L928"


def test_migration_creates_jakosciowy_params(db):
    _run_migration(db, SAMPLE_CONFIG)
    row = db.execute("SELECT * FROM parametry_analityczne WHERE kod='odour'").fetchone()
    assert row is not None
    assert row["typ"] == "jakosciowy"
    assert row["name_en"] == "Odour"


def test_migration_preserves_order(db):
    _run_migration(db, SAMPLE_CONFIG)
    rows = db.execute(
        "SELECT pc.kolejnosc, pa.kod FROM parametry_cert pc "
        "JOIN parametry_analityczne pa ON pa.id = pc.parametr_id "
        "WHERE pc.produkt='Test_Prod' ORDER BY pc.kolejnosc"
    ).fetchall()
    kods = [r["kod"] for r in rows]
    assert kods == ["barwa_hz", "odour", "sm"]


def test_migration_idempotent(db):
    _run_migration(db, SAMPLE_CONFIG)
    _run_migration(db, SAMPLE_CONFIG)  # second run should not fail
    rows = db.execute("SELECT * FROM parametry_cert WHERE produkt='Test_Prod'").fetchall()
    assert len(rows) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/tbk/Desktop/aa && python -m pytest tests/test_migrate_cert_config.py -v`
Expected: FAIL — `scripts.migrate_cert_config` module not found

- [ ] **Step 3: Write migration script**

```python
# scripts/migrate_cert_config.py
"""One-time migration: cert_config.json parameters → parametry_cert table.

Usage:
    python scripts/migrate_cert_config.py [--dry-run]

Reads cert_config.json, for each product:
1. Maps parameters with data_field to existing parametry_analityczne rows
2. Creates jakosciowy params for qualitative entries (no data_field)
3. Enriches parametry_analityczne with name_en and method_code
4. Creates parametry_cert bindings with requirement, format, qualitative_result
"""

import json
import sys
from pathlib import Path


def migrate(db, config: dict, dry_run: bool = False):
    """Run migration against an open DB connection with parsed config."""
    products = config.get("products", {})
    stats = {"bindings": 0, "enriched": 0, "created": 0, "skipped": 0}

    for prod_key, prod_cfg in products.items():
        parameters = prod_cfg.get("parameters", [])
        for idx, param in enumerate(parameters):
            data_field = param.get("data_field")
            name_en = param.get("name_en", "")
            method_code = param.get("method", "")

            if data_field:
                # Find existing parameter by kod
                row = db.execute(
                    "SELECT id FROM parametry_analityczne WHERE kod=?", (data_field,)
                ).fetchone()
                if not row:
                    print(f"  WARN: kod '{data_field}' not found in parametry_analityczne, skipping")
                    stats["skipped"] += 1
                    continue
                pa_id = row["id"]

                # Enrich with name_en and method_code if not already set
                if not dry_run:
                    db.execute(
                        "UPDATE parametry_analityczne SET name_en=COALESCE(NULLIF(name_en,''), ?), "
                        "method_code=COALESCE(NULLIF(method_code,''), ?) WHERE id=?",
                        (name_en, method_code, pa_id),
                    )
                    stats["enriched"] += 1
            else:
                # Qualitative parameter — create if not exists
                qual_kod = param.get("id", f"qual_{prod_key}_{idx}")
                row = db.execute(
                    "SELECT id FROM parametry_analityczne WHERE kod=?", (qual_kod,)
                ).fetchone()
                if row:
                    pa_id = row["id"]
                else:
                    if not dry_run:
                        cur = db.execute(
                            "INSERT INTO parametry_analityczne (kod, label, typ, name_en, method_code, precision, aktywny) "
                            "VALUES (?, ?, 'jakosciowy', ?, ?, 0, 1)",
                            (qual_kod, param.get("name_pl", qual_kod), name_en, method_code),
                        )
                        pa_id = cur.lastrowid
                        stats["created"] += 1
                    else:
                        print(f"  DRY-RUN: would create jakosciowy param '{qual_kod}'")
                        continue

            # Create parametry_cert binding
            if not dry_run:
                db.execute(
                    "INSERT OR IGNORE INTO parametry_cert "
                    "(produkt, parametr_id, kolejnosc, requirement, format, qualitative_result) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        prod_key, pa_id, idx,
                        param.get("requirement", ""),
                        param.get("format", "1"),
                        param.get("qualitative_result"),
                    ),
                )
                stats["bindings"] += 1

    if not dry_run:
        db.commit()

    return stats


def main():
    dry_run = "--dry-run" in sys.argv

    project_root = Path(__file__).resolve().parent.parent
    config_path = project_root / "mbr" / "cert_config.json"
    db_path = project_root / "data" / "batch_db.sqlite"

    if not config_path.exists():
        print(f"ERROR: {config_path} not found")
        sys.exit(1)
    if not db_path.exists():
        print(f"ERROR: {db_path} not found")
        sys.exit(1)

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    print(f"Migrating {len(config.get('products', {}))} products...")
    if dry_run:
        print("(DRY RUN — no changes written)")

    stats = migrate(conn, config, dry_run=dry_run)

    print(f"Done: {stats['bindings']} bindings, {stats['enriched']} enriched, "
          f"{stats['created']} created, {stats['skipped']} skipped")

    conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tbk/Desktop/aa && python -m pytest tests/test_migrate_cert_config.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_cert_config.py tests/test_migrate_cert_config.py
git commit -m "feat: migration script cert_config.json → parametry_cert"
```

---

### Task 3: Seed extension — name_en + method_code in seed.py

**Files:**
- Modify: `mbr/parametry/seed.py:22-111` (PARAMETRY list)

- [ ] **Step 1: Write test for seeded name_en**

Add to `tests/test_parametry_cert.py`:

```python
def test_seed_has_name_en(db):
    """Verify seed populates name_en for key parameters."""
    from mbr.parametry.seed import seed
    seed(db)
    row = db.execute("SELECT name_en, method_code FROM parametry_analityczne WHERE kod='sm'").fetchone()
    assert row["name_en"] == "Dry matter [%]"
    assert row["method_code"] == "L903"


def test_seed_has_name_en_ph(db):
    from mbr.parametry.seed import seed
    seed(db)
    row = db.execute("SELECT name_en FROM parametry_analityczne WHERE kod='ph_10proc'").fetchone()
    assert row["name_en"] == "pH (20°C)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/tbk/Desktop/aa && python -m pytest tests/test_parametry_cert.py::test_seed_has_name_en -v`
Expected: FAIL — `name_en` is None after seed

- [ ] **Step 3: Extend PARAMETRY in seed.py**

Modify each entry in the `PARAMETRY` list in `mbr/parametry/seed.py` to include `name_en` and `method_code`. Example for the first few entries:

```python
# In PARAMETRY list, update each dict to include name_en and method_code:
{"kod": "ph", "label": "pH", "typ": "bezposredni", "precision": 2, "skrot": "pH",
 "name_en": "pH", "method_code": "L905"},
{"kod": "ph_10proc", "label": "pH (10%, 20°C)", "typ": "bezposredni", "precision": 2, "skrot": "pH",
 "name_en": "pH (20°C)", "method_code": "L905"},
{"kod": "nd20", "label": "Współczynnik załamania nD20", "typ": "bezposredni", "precision": 4, "skrot": "nD20",
 "name_en": "Refractive index nD20", "method_code": "L901"},
{"kod": "sm", "label": "Sucha masa", "typ": "bezposredni", "precision": 1, "skrot": "SM",
 "name_en": "Dry matter [%]", "method_code": "L903"},
{"kod": "le", "label": "Lotne z eterem", "typ": "bezposredni", "precision": 1, "skrot": "LE",
 "name_en": "Ether volatile [%]", "method_code": ""},
{"kod": "barwa_fau", "label": "Barwa FAU", "typ": "bezposredni", "precision": 0, "skrot": "FAU",
 "name_en": "Colour (FAU)", "method_code": ""},
{"kod": "barwa_hz", "label": "Barwa Hazena", "typ": "bezposredni", "precision": 0, "skrot": "Hz",
 "name_en": "Colour (Hazen scale)", "method_code": "L928"},
{"kod": "gestosc", "label": "Gęstość", "typ": "bezposredni", "precision": 3, "skrot": "d",
 "name_en": "Density [g/cm³]", "method_code": "L917"},
{"kod": "h2o", "label": "H₂O", "typ": "bezposredni", "precision": 1, "skrot": "H₂O",
 "name_en": "H₂O [%]", "method_code": "L903"},
```

Also update the `seed()` function's INSERT to include the new columns:

```python
# In seed() function, update the INSERT for parametry_analityczne:
db.execute(
    "INSERT OR IGNORE INTO parametry_analityczne (kod, label, typ, precision, skrot, "
    "metoda_nazwa, metoda_formula, metoda_factor, name_en, method_code) "
    "VALUES (:kod, :label, :typ, :precision, :skrot, "
    ":metoda_nazwa, :metoda_formula, :metoda_factor, :name_en, :method_code)",
    {**p, "metoda_nazwa": p.get("metoda_nazwa", ""),
     "metoda_formula": p.get("metoda_formula", ""),
     "metoda_factor": p.get("metoda_factor"),
     "name_en": p.get("name_en", ""),
     "method_code": p.get("method_code", "")},
)
```

Derive `name_en` and `method_code` values from `cert_config.json` for all parameters. Use `cert_config.json` as reference — every `data_field` in that file maps to a `kod` in seed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tbk/Desktop/aa && python -m pytest tests/test_parametry_cert.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add mbr/parametry/seed.py tests/test_parametry_cert.py
git commit -m "feat: add name_en + method_code to parametry seed"
```

---

### Task 4: Backend API — cert binding CRUD endpoints

**Files:**
- Modify: `mbr/parametry/routes.py`
- Test: `tests/test_parametry_cert.py` (add API tests)

- [ ] **Step 1: Write tests for cert CRUD endpoints**

Add to `tests/test_parametry_cert.py`:

```python
import json as _json
from flask import Flask


@pytest.fixture
def app(db):
    """Minimal Flask app with parametry routes for API testing."""
    from mbr.parametry import parametry_bp
    app = Flask(__name__)
    app.secret_key = "test"

    # Patch db_session to use our test db
    import mbr.db as _db
    _orig = _db.db_session

    from contextlib import contextmanager
    @contextmanager
    def _test_db_session():
        yield db

    _db.db_session = _test_db_session
    app.register_blueprint(parametry_bp)

    # Seed a parameter
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, precision) "
        "VALUES ('sm', 'Sucha masa', 'bezposredni', 1)"
    )
    db.commit()

    yield app

    _db.db_session = _orig


@pytest.fixture
def client(app):
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user"] = {"login": "admin", "rola": "admin"}
        yield c


def test_get_cert_bindings_empty(client):
    resp = client.get("/api/parametry/cert/Test_Prod")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_create_cert_binding(client, db):
    pa_id = db.execute("SELECT id FROM parametry_analityczne WHERE kod='sm'").fetchone()["id"]
    resp = client.post("/api/parametry/cert", json={
        "produkt": "Test_Prod",
        "parametr_id": pa_id,
        "kolejnosc": 1,
        "requirement": "min. 44,0",
        "format": "1",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "id" in data


def test_update_cert_binding(client, db):
    pa_id = db.execute("SELECT id FROM parametry_analityczne WHERE kod='sm'").fetchone()["id"]
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement) "
        "VALUES ('Test_Prod', ?, 1, 'old')", (pa_id,)
    )
    db.commit()
    cert_id = db.execute("SELECT id FROM parametry_cert").fetchone()["id"]
    resp = client.put(f"/api/parametry/cert/{cert_id}", json={"requirement": "min. 44,0"})
    assert resp.status_code == 200
    row = db.execute("SELECT requirement FROM parametry_cert WHERE id=?", (cert_id,)).fetchone()
    assert row["requirement"] == "min. 44,0"


def test_delete_cert_binding(client, db):
    pa_id = db.execute("SELECT id FROM parametry_analityczne WHERE kod='sm'").fetchone()["id"]
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc) VALUES ('Test_Prod', ?, 1)",
        (pa_id,),
    )
    db.commit()
    cert_id = db.execute("SELECT id FROM parametry_cert").fetchone()["id"]
    resp = client.delete(f"/api/parametry/cert/{cert_id}")
    assert resp.status_code == 200
    assert db.execute("SELECT * FROM parametry_cert WHERE id=?", (cert_id,)).fetchone() is None


def test_reorder_cert_bindings(client, db):
    pa_id = db.execute("SELECT id FROM parametry_analityczne WHERE kod='sm'").fetchone()["id"]
    db.execute("INSERT INTO parametry_analityczne (kod, label, typ) VALUES ('ph', 'pH', 'bezposredni')")
    db.commit()
    pa_id2 = db.execute("SELECT id FROM parametry_analityczne WHERE kod='ph'").fetchone()["id"]
    db.execute("INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc) VALUES ('P', ?, 0)", (pa_id,))
    db.execute("INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc) VALUES ('P', ?, 1)", (pa_id2,))
    db.commit()
    ids = [r["id"] for r in db.execute("SELECT id FROM parametry_cert ORDER BY kolejnosc").fetchall()]
    resp = client.post("/api/parametry/cert/reorder", json={
        "bindings": [{"id": ids[0], "kolejnosc": 1}, {"id": ids[1], "kolejnosc": 0}]
    })
    assert resp.status_code == 200
    rows = db.execute("SELECT parametr_id, kolejnosc FROM parametry_cert ORDER BY kolejnosc").fetchall()
    assert rows[0]["parametr_id"] == pa_id2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tbk/Desktop/aa && python -m pytest tests/test_parametry_cert.py::test_get_cert_bindings_empty -v`
Expected: FAIL — 404 (route doesn't exist)

- [ ] **Step 3: Add cert CRUD endpoints to routes.py**

Add to `mbr/parametry/routes.py`:

```python
# ═══ CERT BINDINGS ═══

@parametry_bp.route("/api/parametry/cert/<produkt>")
@login_required
def api_parametry_cert_list(produkt):
    """List cert bindings for a product, ordered by kolejnosc."""
    with db_session() as db:
        rows = db.execute(
            "SELECT pc.*, pa.kod, pa.label, pa.name_en, pa.method_code, pa.skrot "
            "FROM parametry_cert pc "
            "JOIN parametry_analityczne pa ON pa.id = pc.parametr_id "
            "WHERE pc.produkt = ? ORDER BY pc.kolejnosc",
            (produkt,),
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@parametry_bp.route("/api/parametry/cert", methods=["POST"])
@role_required("admin")
def api_parametry_cert_create():
    """Create a cert binding. Body: {produkt, parametr_id, kolejnosc, requirement, format, qualitative_result}."""
    data = request.get_json(silent=True) or {}
    produkt = data.get("produkt", "")
    parametr_id = data.get("parametr_id")
    if not produkt or not parametr_id:
        return jsonify({"error": "produkt and parametr_id required"}), 400
    with db_session() as db:
        try:
            cur = db.execute(
                "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format, qualitative_result) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    produkt, parametr_id,
                    data.get("kolejnosc", 0),
                    data.get("requirement", ""),
                    data.get("format", "1"),
                    data.get("qualitative_result"),
                ),
            )
            db.commit()
        except Exception:
            return jsonify({"error": "Binding already exists"}), 409
    return jsonify({"ok": True, "id": cur.lastrowid})


@parametry_bp.route("/api/parametry/cert/<int:binding_id>", methods=["PUT"])
@role_required("admin")
def api_parametry_cert_update(binding_id):
    """Update a cert binding."""
    data = request.get_json(silent=True) or {}
    allowed = {"kolejnosc", "requirement", "format", "qualitative_result"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "No valid fields"}), 400
    sets = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [binding_id]
    with db_session() as db:
        db.execute(f"UPDATE parametry_cert SET {sets} WHERE id=?", vals)
        db.commit()
    return jsonify({"ok": True})


@parametry_bp.route("/api/parametry/cert/<int:binding_id>", methods=["DELETE"])
@role_required("admin")
def api_parametry_cert_delete(binding_id):
    """Delete a cert binding."""
    with db_session() as db:
        db.execute("DELETE FROM parametry_cert WHERE id=?", (binding_id,))
        db.commit()
    return jsonify({"ok": True})


@parametry_bp.route("/api/parametry/cert/reorder", methods=["POST"])
@role_required("admin")
def api_parametry_cert_reorder():
    """Batch update kolejnosc. Body: {bindings: [{id, kolejnosc}, ...]}."""
    data = request.get_json(silent=True) or {}
    bindings = data.get("bindings", [])
    if not bindings:
        return jsonify({"error": "bindings required"}), 400
    with db_session() as db:
        for b in bindings:
            db.execute("UPDATE parametry_cert SET kolejnosc=? WHERE id=?", (b["kolejnosc"], b["id"]))
        db.commit()
    return jsonify({"ok": True})
```

Also ensure `role_required` is imported at the top if not already:

```python
from mbr.shared.decorators import login_required, role_required
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tbk/Desktop/aa && python -m pytest tests/test_parametry_cert.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add mbr/parametry/routes.py tests/test_parametry_cert.py
git commit -m "feat: cert binding CRUD endpoints in parametry routes"
```

---

### Task 5: Apply stash — restore two-tab UI + admin routes

**Files:**
- Modify: `mbr/parametry/routes.py` (selective merge from stash)
- Modify: `mbr/templates/parametry_editor.html` (selective merge from stash)

- [ ] **Step 1: Extract stash versions of relevant files**

```bash
cd /Users/tbk/Desktop/aa
git show stash@{0}:mbr/templates/parametry_editor.html > /tmp/stash_parametry_editor.html
git show stash@{0}:mbr/parametry/routes.py > /tmp/stash_parametry_routes.py
```

- [ ] **Step 2: Merge stash route changes into current routes.py**

From the stash version, selectively apply these changes to `mbr/parametry/routes.py`:

1. Import `session` from flask and `role_required` from decorators (if not already done in Task 4)
2. `api_parametry_list()` — admin sees inactive params (`WHERE` clause based on role)
3. `api_parametry_update()` — admin can edit `typ`, `jednostka`, `aktywny`
4. `api_parametry_create()` — POST endpoint for new params (admin only)
5. `parametry_editor()` — pass `is_admin` to template

Also add `name_en` and `method_code` to the allowed fields:
- In `api_parametry_update()`: add `"name_en", "method_code"` to the admin allowed set
- In `api_parametry_create()`: include `name_en` and `method_code` in the INSERT

Do NOT apply `product_ref_values` endpoints from stash (out of scope).

- [ ] **Step 3: Merge stash template into current parametry_editor.html**

From `/tmp/stash_parametry_editor.html`, copy into current `parametry_editor.html`:

1. CSS block: `.pe-tabs`, `.pe-tab`, `.pe-tab-active`, `.pa-table`, `.pa-input`, `.pa-select`, `.pa-toggle`, `.pa-add` styles
2. HTML: tab strip div with `pe-tabs` and two buttons (`tab-bind`, `tab-def`)
3. HTML: wrap existing content in `<div id="panel-bind">...</div>`
4. HTML: add `<div id="panel-def">...</div>` with admin table (from stash), guarded by `{% if is_admin %}`
5. JS: `switchTab()`, `loadDefinicje()`, `renderDefTable()`, `saveDefField()`, `toggleActive()`, `addParametr()` functions

Extend `renderDefTable()` to show `name_en` and `method_code` columns:
- Add `<th>Name EN</th>` and `<th>Metoda</th>` to the table header
- Add corresponding `<input>` cells calling `saveDefField()` with the new field names

- [ ] **Step 4: Test manually**

Run the app and verify:
1. `/parametry` shows two tabs: "Etapy" and "Rejestr"
2. "Rejestr" tab shows all parameters with inline editing including Name EN and Metoda columns
3. Adding a new parameter works
4. Toggle aktywny works
5. "Etapy" tab works as before

- [ ] **Step 5: Commit**

```bash
git add mbr/parametry/routes.py mbr/templates/parametry_editor.html
git commit -m "feat: restore two-tab UI from stash + name_en/method_code fields"
```

---

### Task 6: Add third tab — "Świadectwa"

**Files:**
- Modify: `mbr/templates/parametry_editor.html`

- [ ] **Step 1: Add "Świadectwa" tab button**

In the `.pe-tabs` div, add a third button (admin only):

```html
{% if is_admin %}
<button class="pe-tab" id="tab-cert" onclick="switchTab('cert')">Świadectwa</button>
{% endif %}
```

- [ ] **Step 2: Add the cert panel HTML**

After `panel-def`, add:

```html
{% if is_admin %}
<div id="panel-cert" style="display:none;">
  <div style="display:flex;gap:10px;align-items:center;margin-bottom:16px;">
    <label style="font-size:11px;font-weight:700;color:var(--text-sec);">Produkt:</label>
    <select id="cert-produkt" class="pa-select" style="border-color:var(--border);min-width:200px;" onchange="loadCertBindings()">
      <option value="">— wybierz —</option>
      {% for p in cert_products %}
      <option value="{{ p }}">{{ p.replace('_', ' ') }}</option>
      {% endfor %}
    </select>
  </div>

  <table class="pa-table" id="cert-table" style="display:none;">
    <thead>
      <tr>
        <th style="width:30px;">⠿</th>
        <th>Parametr</th>
        <th>Label PL</th>
        <th>Name EN</th>
        <th>Metoda</th>
        <th style="width:150px;">Requirement</th>
        <th style="width:60px;">Format</th>
        <th style="width:140px;">Qual. result</th>
        <th style="width:40px;"></th>
      </tr>
    </thead>
    <tbody id="cert-body"></tbody>
  </table>

  <div class="pa-add" id="cert-add" style="display:none;">
    <select id="cert-add-param" style="width:200px;">
      <option value="">— parametr —</option>
    </select>
    <input type="text" id="cert-add-req" placeholder="Requirement" style="width:140px;">
    <select id="cert-add-fmt" style="width:60px;">
      <option value="0">0</option>
      <option value="1" selected>1</option>
      <option value="2">2</option>
      <option value="3">3</option>
    </select>
    <input type="text" id="cert-add-qual" placeholder="Qual. result (opcjonalne)" style="width:160px;">
    <button onclick="addCertBinding()">+ Dodaj</button>
  </div>
</div>
{% endif %}
```

- [ ] **Step 3: Update switchTab() to handle three tabs**

```javascript
function switchTab(which) {
  ['bind', 'def', 'cert'].forEach(function(t) {
    var tab = document.getElementById('tab-' + t);
    var panel = document.getElementById('panel-' + t);
    if (tab) tab.classList.toggle('pe-tab-active', t === which);
    if (panel) panel.style.display = (t === which) ? '' : 'none';
  });
  if (which === 'def' && !_paLoaded) loadDefinicje();
  if (which === 'cert' && !_certLoaded) loadCertAvailable();
}
```

- [ ] **Step 4: Add cert tab JavaScript**

```javascript
var _certLoaded = false;
var _certAvailable = [];  // all active params for the select dropdown
var _certBindings = [];

function loadCertAvailable() {
  fetch('/api/parametry/available').then(function(r){return r.json();}).then(function(data) {
    _certAvailable = data;
    _certLoaded = true;
    var sel = document.getElementById('cert-add-param');
    var html = '<option value="">— parametr —</option>';
    data.forEach(function(p) {
      html += '<option value="' + p.id + '">' + p.kod + ' — ' + (p.skrot || p.label) + '</option>';
    });
    sel.innerHTML = html;
  });
}

function loadCertBindings() {
  var produkt = document.getElementById('cert-produkt').value;
  if (!produkt) {
    document.getElementById('cert-table').style.display = 'none';
    document.getElementById('cert-add').style.display = 'none';
    return;
  }
  fetch('/api/parametry/cert/' + encodeURIComponent(produkt))
    .then(function(r){return r.json();})
    .then(function(data) {
      _certBindings = data;
      renderCertTable(data);
      document.getElementById('cert-table').style.display = '';
      document.getElementById('cert-add').style.display = 'flex';
    });
}

function renderCertTable(data) {
  var html = '';
  data.forEach(function(b, idx) {
    html += '<tr draggable="true" data-id="' + b.id + '" data-idx="' + idx + '" ' +
      'ondragstart="certDragStart(event)" ondragover="certDragOver(event)" ondrop="certDrop(event)">' +
      '<td style="cursor:grab;color:var(--text-dim);text-align:center;">⠿</td>' +
      '<td><span class="pa-kod">' + (b.kod || '') + '</span></td>' +
      '<td style="font-size:11px;">' + (b.label || '') + '</td>' +
      '<td style="font-size:11px;color:var(--text-sec);">' + (b.name_en || '') + '</td>' +
      '<td style="font-size:11px;font-family:var(--mono);">' + (b.method_code || '') + '</td>' +
      '<td><input class="pa-input" value="' + (b.requirement||'').replace(/"/g,'&quot;') + '" ' +
        'onchange="saveCertField(' + b.id + ',\'requirement\',this.value)"></td>' +
      '<td><select class="pa-select" onchange="saveCertField(' + b.id + ',\'format\',this.value)">' +
        ['0','1','2','3'].map(function(f){return '<option'+(f===b.format?' selected':'')+'>'+f+'</option>';}).join('') +
      '</select></td>' +
      '<td><input class="pa-input" value="' + (b.qualitative_result||'').replace(/"/g,'&quot;') + '" ' +
        'onchange="saveCertField(' + b.id + ',\'qualitative_result\',this.value)" placeholder="—"></td>' +
      '<td><button class="pe-bind-del" onclick="deleteCertBinding(' + b.id + ')">&times;</button></td>' +
    '</tr>';
  });
  document.getElementById('cert-body').innerHTML = html || '<tr><td colspan="9" style="text-align:center;color:var(--text-dim);padding:20px;">Brak przypisań</td></tr>';
}

function saveCertField(id, field, value) {
  var body = {}; body[field] = value;
  fetch('/api/parametry/cert/' + id, {
    method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
}

function addCertBinding() {
  var produkt = document.getElementById('cert-produkt').value;
  var paramId = document.getElementById('cert-add-param').value;
  if (!produkt || !paramId) return;
  fetch('/api/parametry/cert', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      produkt: produkt,
      parametr_id: parseInt(paramId),
      kolejnosc: _certBindings.length,
      requirement: document.getElementById('cert-add-req').value.trim(),
      format: document.getElementById('cert-add-fmt').value,
      qualitative_result: document.getElementById('cert-add-qual').value.trim() || null,
    })
  }).then(function(r){return r.json();}).then(function(d) {
    if (d.ok) {
      document.getElementById('cert-add-req').value = '';
      document.getElementById('cert-add-qual').value = '';
      loadCertBindings();
    } else { alert(d.error || 'Błąd'); }
  });
}

function deleteCertBinding(id) {
  if (!confirm('Usunąć przypisanie?')) return;
  fetch('/api/parametry/cert/' + id, {method: 'DELETE'})
    .then(function(r){return r.json();})
    .then(function(d) { if (d.ok) loadCertBindings(); });
}

// Drag & drop reorder
var _certDragIdx = null;
function certDragStart(e) {
  _certDragIdx = parseInt(e.currentTarget.dataset.idx);
  e.dataTransfer.effectAllowed = 'move';
}
function certDragOver(e) { e.preventDefault(); }
function certDrop(e) {
  e.preventDefault();
  var targetIdx = parseInt(e.currentTarget.dataset.idx);
  if (_certDragIdx === null || _certDragIdx === targetIdx) return;
  // Swap in local array and reorder
  var item = _certBindings.splice(_certDragIdx, 1)[0];
  _certBindings.splice(targetIdx, 0, item);
  var reorderData = _certBindings.map(function(b, i) { return {id: b.id, kolejnosc: i}; });
  fetch('/api/parametry/cert/reorder', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({bindings: reorderData})
  });
  renderCertTable(_certBindings);
}
```

- [ ] **Step 5: Pass cert_products to template**

In `mbr/parametry/routes.py`, modify `parametry_editor()`:

```python
@parametry_bp.route("/parametry")
@login_required
def parametry_editor():
    """Parameter editor page."""
    rola = session.get("user", {}).get("rola", "")
    with db_session() as db:
        products = [r["produkt"] for r in db.execute(
            "SELECT DISTINCT produkt FROM mbr_templates WHERE status='active' ORDER BY produkt"
        ).fetchall()]
        konteksty = get_konteksty(db)
        # Products that have cert_config entries (for Świadectwa tab)
        cert_products = [r["produkt"] for r in db.execute(
            "SELECT DISTINCT produkt FROM parametry_cert ORDER BY produkt"
        ).fetchall()]
        # Also include products from mbr_templates not yet in parametry_cert
        all_products = sorted(set(products) | set(cert_products))
    return render_template(
        "parametry_editor.html",
        products=products, konteksty=konteksty,
        is_admin=(rola == "admin"),
        cert_products=all_products,
    )
```

- [ ] **Step 6: Test manually**

Run the app and verify:
1. Three tabs visible: "Etapy", "Rejestr", "Świadectwa"
2. Świadectwa tab shows product select
3. After selecting product and running migration (Task 2): bindings appear
4. Inline edit requirement, format, qualitative_result works
5. Add/delete bindings works
6. Drag-to-reorder works

- [ ] **Step 7: Commit**

```bash
git add mbr/parametry/routes.py mbr/templates/parametry_editor.html
git commit -m "feat: add Świadectwa tab — cert binding management UI"
```

---

### Task 7: Adapt certificate generator to read from DB

**Files:**
- Modify: `mbr/certs/generator.py:113-267` (build_context function)
- Test: `tests/test_parametry_cert.py` (add generator test)

- [ ] **Step 1: Write test for DB-backed build_context**

Add to `tests/test_parametry_cert.py`:

```python
def test_build_context_from_db(db):
    """build_context reads parameters from parametry_cert instead of cert_config.json."""
    # Seed parameter
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, name_en, method_code, precision) "
        "VALUES ('sm', 'Sucha masa', 'bezposredni', 'Dry matter [%]', 'L903', 1)"
    )
    db.commit()
    pa_id = db.execute("SELECT id FROM parametry_analityczne WHERE kod='sm'").fetchone()["id"]

    # Create cert binding
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format) "
        "VALUES ('Chegina_K40GLOL', ?, 0, 'min. 44,0', '1')",
        (pa_id,),
    )
    db.commit()

    from mbr.certs.generator import _build_rows_from_db
    rows = _build_rows_from_db(db, "Chegina_K40GLOL", {"sm": {"wartosc": 45.3}})
    assert len(rows) == 1
    assert rows[0]["name_pl"] == "Sucha masa"
    assert rows[0]["name_en"] == "Dry matter [%]"
    assert rows[0]["method"] == "L903"
    assert rows[0]["requirement"] == "min. 44,0"
    assert rows[0]["result"] == "45,3"


def test_build_rows_qualitative(db):
    """Qualitative params use qualitative_result from parametry_cert."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, name_en) "
        "VALUES ('odour', 'Zapach', 'jakosciowy', 'Odour')"
    )
    db.commit()
    pa_id = db.execute("SELECT id FROM parametry_analityczne WHERE kod='odour'").fetchone()["id"]
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, qualitative_result) "
        "VALUES ('Prod_A', ?, 0, 'słaby /faint', 'zgodny /right')",
        (pa_id,),
    )
    db.commit()

    from mbr.certs.generator import _build_rows_from_db
    rows = _build_rows_from_db(db, "Prod_A", {})
    assert len(rows) == 1
    assert rows[0]["result"] == "zgodny /right"
    assert rows[0]["requirement"] == "słaby /faint"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tbk/Desktop/aa && python -m pytest tests/test_parametry_cert.py::test_build_context_from_db -v`
Expected: FAIL — `_build_rows_from_db` doesn't exist

- [ ] **Step 3: Add _build_rows_from_db to generator.py**

Add new function to `mbr/certs/generator.py`:

```python
def _build_rows_from_db(db, produkt: str, wyniki_flat: dict) -> list[dict]:
    """Build certificate rows from parametry_cert + parametry_analityczne (DB source).

    Args:
        db: Database connection.
        produkt: Product key (e.g. "Chegina_K40GLOL").
        wyniki_flat: Lab results {kod: value_or_dict}.

    Returns:
        List of row dicts: {name_pl, name_en, requirement, method, result}.
    """
    rows_db = db.execute(
        "SELECT pc.*, pa.kod, pa.label, pa.name_en, pa.method_code, pa.precision as pa_precision "
        "FROM parametry_cert pc "
        "JOIN parametry_analityczne pa ON pa.id = pc.parametr_id "
        "WHERE pc.produkt = ? ORDER BY pc.kolejnosc",
        (produkt,),
    ).fetchall()

    rows = []
    for r in rows_db:
        result = ""
        if r["qualitative_result"]:
            result = r["qualitative_result"]
        elif r["kod"] and r["kod"] in wyniki_flat:
            raw = wyniki_flat[r["kod"]]
            if isinstance(raw, dict):
                val = raw.get("wartosc", raw.get("value", ""))
            else:
                val = raw
            if val is not None and val != "":
                try:
                    fmt = r["format"] or "1"
                    result = _format_value(float(val), fmt)
                except (ValueError, TypeError):
                    result = str(val).replace(".", ",")

        rows.append({
            "_kod": r["kod"] or "",  # internal, for variant filtering
            "name_pl": r["label"] or "",
            "name_en": r["name_en"] or "",
            "requirement": r["requirement"] or "",
            "method": r["method_code"] or "",
            "result": result,
        })

    return rows
```

- [ ] **Step 4: Modify build_context to use DB rows when available**

In `build_context()`, replace the parameters-from-config block with a DB-first approach. After finding the variant and applying overrides, change the rows building section:

```python
    # Build rows — prefer DB (parametry_cert), fallback to cert_config.json
    from mbr.db import db_session
    rows = []
    try:
        with db_session() as db:
            db_rows = _build_rows_from_db(db, key, wyniki_flat)
            if db_rows:
                rows = db_rows
                # Apply variant overrides (remove_parameters)
                remove_ids = set(overrides.get("remove_parameters", []))
                if remove_ids:
                    # Map remove IDs to kods via cert_config for backwards compat
                    remove_kods = set()
                    for p in product_cfg.get("parameters", []):
                        if p["id"] in remove_ids:
                            remove_kods.add(p.get("data_field", p["id"]))
                    rows = [r for r in rows if not any(
                        r["name_pl"] == _find_label(db, kod) for kod in remove_kods
                    )]
    except Exception:
        pass  # Fallback to config-based rows below

    if not rows:
        # Original config-based logic (fallback)
        parameters = copy.deepcopy(product_cfg["parameters"])
        # ... existing code unchanged ...
```

Simpler approach — `_build_rows_from_db` returns rows with `kod` attached, variant overrides filter by kod:

```python
    # Build rows — DB-first with config fallback
    from mbr.db import db_session
    rows = []
    use_db = False
    try:
        with db_session() as db:
            cert_count = db.execute(
                "SELECT COUNT(*) as c FROM parametry_cert WHERE produkt=?", (key,)
            ).fetchone()["c"]
            if cert_count > 0:
                use_db = True
                db_rows = _build_rows_from_db(db, key, wyniki_flat)

                # Variant: remove_parameters (list of config param IDs → map to kods)
                remove_ids = set(overrides.get("remove_parameters", []))
                if remove_ids:
                    remove_kods = set()
                    for p in product_cfg.get("parameters", []):
                        if p["id"] in remove_ids:
                            remove_kods.add(p.get("data_field") or p["id"])
                    db_rows = [r for r in db_rows if r.get("_kod") not in remove_kods]

                # Variant: add_parameters (still from config JSON for now)
                for ap in overrides.get("add_parameters", []):
                    result = ""
                    if ap.get("qualitative_result"):
                        result = ap["qualitative_result"]
                    elif ap.get("data_field") and ap["data_field"] in wyniki_flat:
                        raw = wyniki_flat[ap["data_field"]]
                        val = raw.get("wartosc", raw) if isinstance(raw, dict) else raw
                        if val is not None and val != "":
                            try:
                                result = _format_value(float(val), ap.get("format", "1"))
                            except (ValueError, TypeError):
                                result = str(val).replace(".", ",")
                    db_rows.append({
                        "name_pl": ap.get("name_pl", ""),
                        "name_en": ap.get("name_en", ""),
                        "requirement": ap.get("requirement", ""),
                        "method": ap.get("method", ""),
                        "result": result,
                    })

                # Strip internal _kod field before returning
                rows = [{k: v for k, v in r.items() if k != "_kod"} for r in db_rows]
    except Exception:
        use_db = False

    if not use_db:
        # Original config-based logic (unchanged fallback)
        parameters = copy.deepcopy(product_cfg["parameters"])
        remove_ids = set(overrides.get("remove_parameters", []))
        if remove_ids:
            parameters = [p for p in parameters if p["id"] not in remove_ids]
        add_params = overrides.get("add_parameters", [])
        if add_params:
            parameters.extend(copy.deepcopy(add_params))

        for param in parameters:
            result = ""
            if param.get("qualitative_result"):
                result = param["qualitative_result"]
            elif param.get("data_field") and param["data_field"] in wyniki_flat:
                raw = wyniki_flat[param["data_field"]]
                if isinstance(raw, dict):
                    val = raw.get("wartosc", raw.get("value", ""))
                else:
                    val = raw
                if val is not None and val != "":
                    try:
                        result = _format_value(float(val), param.get("format", "1"))
                    except (ValueError, TypeError):
                        result = str(val).replace(".", ",")
            rows.append({
                "name_pl": param["name_pl"],
                "name_en": param["name_en"],
                "requirement": param["requirement"],
                "method": param.get("method", ""),
                "result": result,
            })
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/tbk/Desktop/aa && python -m pytest tests/test_parametry_cert.py -v`
Expected: All tests PASS

- [ ] **Step 6: Run existing cert tests to ensure no regression**

Run: `cd /Users/tbk/Desktop/aa && python -m pytest tests/test_certs.py -v`
Expected: All existing tests still PASS

- [ ] **Step 7: Commit**

```bash
git add mbr/certs/generator.py tests/test_parametry_cert.py
git commit -m "feat: certificate generator reads params from DB (parametry_cert)"
```

---

### Task 8: Run migration on real data + cleanup

**Files:**
- Run: `scripts/migrate_cert_config.py`
- Modify: `mbr/certs/routes.py` (remove deprecated endpoints)

- [ ] **Step 1: Run migration in dry-run mode**

```bash
cd /Users/tbk/Desktop/aa && python scripts/migrate_cert_config.py --dry-run
```

Review output — check for WARNs about missing kods.

- [ ] **Step 2: Run migration for real**

```bash
cd /Users/tbk/Desktop/aa && python scripts/migrate_cert_config.py
```

Verify output shows expected counts (30 products × ~5-10 params each).

- [ ] **Step 3: Verify in app**

Run the app, go to `/parametry`, click "Świadectwa" tab, select a product — verify bindings appear correctly.

- [ ] **Step 4: Remove deprecated cert config endpoints**

In `mbr/certs/routes.py`, remove or comment out the endpoints at lines 197-239:
- `GET /api/cert/config/parameters`
- `PUT /api/cert/config/parameters`

These are replaced by the new `/api/parametry/cert/*` endpoints.

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/tbk/Desktop/aa && python -m pytest tests/ -v
```

Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add mbr/certs/routes.py
git commit -m "refactor: remove deprecated cert config parameter endpoints"
```

---

## Summary

| Task | Description | Depends on |
|------|-------------|------------|
| 1 | DB migrations (name_en, method_code, parametry_cert table) | — |
| 2 | Migration script cert_config.json → DB | Task 1 |
| 3 | Seed extension (name_en, method_code) | Task 1 |
| 4 | Backend API — cert binding CRUD | Task 1 |
| 5 | Apply stash — restore two-tab UI + admin routes | Task 1 |
| 6 | Add third tab "Świadectwa" | Tasks 4, 5 |
| 7 | Adapt certificate generator to read from DB | Tasks 1, 4 |
| 8 | Run migration + cleanup deprecated endpoints | Tasks 2, 7 |
