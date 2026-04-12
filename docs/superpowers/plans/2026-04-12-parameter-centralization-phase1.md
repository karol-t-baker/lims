# Parameter Centralization — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `parametry_etapy` with cert columns, migrate data from `parametry_cert`, update cert generator to read from new source with fallback.

**Architecture:** Add 6 columns to `parametry_etapy` (`cert_requirement`, `cert_format`, `cert_qualitative_result`, `cert_kolejnosc`, `on_cert`, `cert_variant_id`). Migration script copies 319 base + 13 variant rows from `parametry_cert`. Cert generator reads `parametry_etapy` first, falls back to `parametry_cert` for safety. `parametry_cert` stays until Phase 4.

**Tech Stack:** Python 3.12, Flask, SQLite, pytest

**Spec:** `docs/superpowers/specs/2026-04-12-parameter-centralization-design.md`

---

### Task 1: Schema migration — add cert columns to `parametry_etapy`

**Files:**
- Modify: `mbr/models.py` (init_mbr_tables + migration block)
- Test: `tests/test_param_centralization.py` (new)

- [ ] **Step 1: Write test for new columns**

Create `tests/test_param_centralization.py`:

```python
"""Tests for parameter centralization Phase 1."""
import sqlite3
import pytest


@pytest.fixture
def db():
    """In-memory DB with full schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from mbr.models import init_mbr_tables
    init_mbr_tables(conn)
    return conn


def test_parametry_etapy_has_cert_columns(db):
    """After init, parametry_etapy should have all cert columns."""
    cols = {r[1] for r in db.execute("PRAGMA table_info(parametry_etapy)").fetchall()}
    for col in ("cert_requirement", "cert_format", "cert_qualitative_result",
                "cert_kolejnosc", "on_cert", "cert_variant_id"):
        assert col in cols, f"Missing column: {col}"


def test_on_cert_defaults_to_zero(db):
    """New parametry_etapy rows should default on_cert=0."""
    db.execute("INSERT INTO parametry_analityczne (kod, label, typ) VALUES ('test', 'Test', 'bezposredni')")
    db.execute("INSERT INTO parametry_etapy (kontekst, parametr_id, produkt) VALUES ('analiza_koncowa', 1, 'TestProd')")
    row = db.execute("SELECT on_cert FROM parametry_etapy WHERE id=1").fetchone()
    assert row["on_cert"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_param_centralization.py -v`
Expected: FAIL — columns don't exist yet

- [ ] **Step 3: Add columns to schema DDL in `init_mbr_tables`**

In `mbr/models.py`, update the `CREATE TABLE IF NOT EXISTS parametry_etapy` block to add the new columns after `target`:

```sql
CREATE TABLE IF NOT EXISTS parametry_etapy (
    id              INTEGER PRIMARY KEY,
    produkt         TEXT,
    kontekst        TEXT NOT NULL,
    parametr_id     INTEGER NOT NULL REFERENCES parametry_analityczne(id),
    kolejnosc       INTEGER DEFAULT 0,
    min_limit       REAL,
    max_limit       REAL,
    nawazka_g       REAL,
    wymagany        INTEGER DEFAULT 0,
    target          REAL,
    krok            INTEGER,
    cert_requirement       TEXT,
    cert_format            TEXT,
    cert_qualitative_result TEXT,
    cert_kolejnosc         INTEGER,
    on_cert                INTEGER DEFAULT 0,
    cert_variant_id        INTEGER,
    UNIQUE(produkt, kontekst, parametr_id)
)
```

Then add migration ALTER TABLE statements in the migration section (after the existing `formula`/`sa_bias` migrations), guarded by try/except:

```python
for col, typedef in [
    ("cert_requirement", "TEXT"),
    ("cert_format", "TEXT"),
    ("cert_qualitative_result", "TEXT"),
    ("cert_kolejnosc", "INTEGER"),
    ("on_cert", "INTEGER DEFAULT 0"),
    ("cert_variant_id", "INTEGER"),
]:
    try:
        db.execute(f"ALTER TABLE parametry_etapy ADD COLUMN {col} {typedef}")
        db.commit()
    except Exception:
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_param_centralization.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: all pass, no regressions

- [ ] **Step 6: Commit**

```bash
git add mbr/models.py tests/test_param_centralization.py
git commit -m "feat(params): add cert columns to parametry_etapy schema"
```

---

### Task 2: Migration script — copy data from `parametry_cert` to `parametry_etapy`

**Files:**
- Create: `scripts/migrate_cert_to_etapy.py`
- Test: `tests/test_param_centralization.py` (extend)

- [ ] **Step 1: Write test for migration**

Append to `tests/test_param_centralization.py`:

```python
def _seed_cert_data(db):
    """Seed parametry_analityczne, parametry_etapy, parametry_cert, cert_variants for migration test."""
    # Parameters
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (1, 'sm', 'Sucha masa', 'bezposredni')")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (2, 'nacl', 'Chlorek sodu', 'bezposredni')")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (3, 'odour', 'Zapach', 'binarny')")
    # Existing etapy binding for sm and nacl
    db.execute("INSERT INTO parametry_etapy (id, produkt, kontekst, parametr_id, kolejnosc, min_limit, max_limit) VALUES (1, 'Prod', 'analiza_koncowa', 1, 0, 35.0, NULL)")
    db.execute("INSERT INTO parametry_etapy (id, produkt, kontekst, parametr_id, kolejnosc, min_limit, max_limit) VALUES (2, 'Prod', 'analiza_koncowa', 2, 1, NULL, 5.5)")
    # parametry_cert — base rows
    db.execute("INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format, variant_id, name_pl, name_en, method) VALUES ('Prod', 1, 0, 'min 35,5', '1', NULL, 'Sucha masa', 'Dry matter', 'L903')")
    db.execute("INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format, qualitative_result, variant_id) VALUES ('Prod', 3, 2, 'charakterystyczny', '1', 'zgodny/right', NULL)")
    # cert_variants + variant add_parameter
    db.execute("INSERT INTO cert_variants (id, produkt, variant_id, label, flags, remove_params, kolejnosc) VALUES (1, 'Prod', 'loreal', 'L''Oreal', '[]', '[]', 0)")
    db.execute("INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format, variant_id, name_pl) VALUES ('Prod', 2, 0, 'max 5,5', '1', 1, 'NaCl extra')")
    db.commit()


def test_migration_copies_base_cert_params(db):
    """Base parametry_cert rows → on_cert=1 + cert fields in parametry_etapy."""
    _seed_cert_data(db)
    from scripts.migrate_cert_to_etapy import migrate
    migrate(db)

    # sm: existing etapy row updated with cert data
    row = db.execute("SELECT on_cert, cert_requirement, cert_format FROM parametry_etapy WHERE produkt='Prod' AND parametr_id=1 AND kontekst='analiza_koncowa'").fetchone()
    assert row["on_cert"] == 1
    assert row["cert_requirement"] == "min 35,5"
    assert row["cert_format"] == "1"


def test_migration_inserts_cert_only_params(db):
    """Cert-only params (no etapy match) → new row with on_cert=1."""
    _seed_cert_data(db)
    from scripts.migrate_cert_to_etapy import migrate
    migrate(db)

    row = db.execute("SELECT on_cert, cert_requirement, cert_qualitative_result FROM parametry_etapy WHERE produkt='Prod' AND parametr_id=3 AND kontekst='analiza_koncowa'").fetchone()
    assert row is not None, "Cert-only param should be inserted"
    assert row["on_cert"] == 1
    assert row["cert_qualitative_result"] == "zgodny/right"


def test_migration_handles_variant_add_params(db):
    """Variant add_parameters → new row with kontekst='cert_variant', cert_variant_id set."""
    _seed_cert_data(db)
    from scripts.migrate_cert_to_etapy import migrate
    migrate(db)

    row = db.execute("SELECT kontekst, cert_variant_id, cert_requirement, on_cert FROM parametry_etapy WHERE produkt='Prod' AND parametr_id=2 AND kontekst='cert_variant'").fetchone()
    assert row is not None, "Variant add_param should be inserted"
    assert row["cert_variant_id"] == 1
    assert row["cert_requirement"] == "max 5,5"
    assert row["on_cert"] == 1


def test_migration_is_idempotent(db):
    """Running migration twice produces the same result."""
    _seed_cert_data(db)
    from scripts.migrate_cert_to_etapy import migrate
    migrate(db)
    migrate(db)

    count = db.execute("SELECT COUNT(*) as c FROM parametry_etapy WHERE on_cert=1").fetchone()["c"]
    assert count == 3  # sm, odour (base), nacl (variant)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_param_centralization.py::test_migration_copies_base_cert_params -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write migration script**

Create `scripts/migrate_cert_to_etapy.py`:

```python
"""Migrate parametry_cert data into parametry_etapy cert columns.

Idempotent — skips rows already migrated (on_cert=1).
"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "batch_db.sqlite"


def migrate(db=None):
    own_conn = db is None
    if own_conn:
        db = sqlite3.connect(str(DB))
        db.row_factory = sqlite3.Row

    # 1. Base cert params (variant_id IS NULL)
    base_rows = db.execute("""
        SELECT pc.produkt, pc.parametr_id, pc.kolejnosc, pc.requirement,
               pc.format, pc.qualitative_result
        FROM parametry_cert pc
        WHERE pc.variant_id IS NULL
    """).fetchall()

    updated = 0
    inserted = 0
    for r in base_rows:
        # Try to find matching parametry_etapy row
        existing = db.execute("""
            SELECT id, on_cert FROM parametry_etapy
            WHERE produkt=? AND parametr_id=? AND kontekst='analiza_koncowa'
              AND cert_variant_id IS NULL
        """, (r["produkt"], r["parametr_id"])).fetchone()

        if existing:
            if not existing["on_cert"]:
                db.execute("""
                    UPDATE parametry_etapy
                    SET on_cert=1, cert_requirement=?, cert_format=?,
                        cert_qualitative_result=?, cert_kolejnosc=?
                    WHERE id=?
                """, (r["requirement"], r["format"], r["qualitative_result"],
                      r["kolejnosc"], existing["id"]))
                updated += 1
        else:
            # Cert-only param — insert new row
            db.execute("""
                INSERT INTO parametry_etapy
                    (produkt, kontekst, parametr_id, kolejnosc,
                     on_cert, cert_requirement, cert_format, cert_qualitative_result, cert_kolejnosc)
                VALUES (?, 'analiza_koncowa', ?, ?, 1, ?, ?, ?, ?)
            """, (r["produkt"], r["parametr_id"], r["kolejnosc"],
                  r["requirement"], r["format"], r["qualitative_result"], r["kolejnosc"]))
            inserted += 1

    # 2. Variant add_parameters (variant_id IS NOT NULL)
    variant_rows = db.execute("""
        SELECT pc.produkt, pc.parametr_id, pc.kolejnosc, pc.requirement,
               pc.format, pc.qualitative_result, pc.variant_id
        FROM parametry_cert pc
        WHERE pc.variant_id IS NOT NULL
    """).fetchall()

    var_inserted = 0
    for r in variant_rows:
        existing = db.execute("""
            SELECT id FROM parametry_etapy
            WHERE produkt=? AND parametr_id=? AND kontekst='cert_variant'
              AND cert_variant_id=?
        """, (r["produkt"], r["parametr_id"], r["variant_id"])).fetchone()

        if not existing:
            db.execute("""
                INSERT INTO parametry_etapy
                    (produkt, kontekst, parametr_id, kolejnosc,
                     on_cert, cert_requirement, cert_format, cert_qualitative_result,
                     cert_kolejnosc, cert_variant_id)
                VALUES (?, 'cert_variant', ?, ?, 1, ?, ?, ?, ?, ?)
            """, (r["produkt"], r["parametr_id"], r["kolejnosc"],
                  r["requirement"], r["format"], r["qualitative_result"],
                  r["kolejnosc"], r["variant_id"]))
            var_inserted += 1

    db.commit()
    print(f"migrate_cert_to_etapy: {updated} updated, {inserted} inserted (base), {var_inserted} inserted (variant)")

    if own_conn:
        db.close()


if __name__ == "__main__":
    migrate()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_param_centralization.py -v`
Expected: all 4 migration tests PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: all pass

- [ ] **Step 6: Run migration on real DB**

```bash
python scripts/migrate_cert_to_etapy.py
```

Expected output: `migrate_cert_to_etapy: ~300 updated, ~20 inserted (base), 13 inserted (variant)`

- [ ] **Step 7: Commit**

```bash
git add scripts/migrate_cert_to_etapy.py tests/test_param_centralization.py
git commit -m "feat(params): migration script — copy parametry_cert to parametry_etapy"
```

---

### Task 3: New query function — read cert params from `parametry_etapy`

**Files:**
- Modify: `mbr/parametry/registry.py`
- Test: `tests/test_param_centralization.py` (extend)

- [ ] **Step 1: Write test for new query function**

Append to `tests/test_param_centralization.py`:

```python
def _seed_etapy_with_cert(db):
    """Seed DB with parametry_etapy rows that have cert data (post-migration state)."""
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ, name_en, method_code) VALUES (1, 'sm', 'Sucha masa', 'bezposredni', 'Dry matter [%]', 'L903')")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ, name_en, method_code) VALUES (2, 'nacl', 'Chlorek sodu', 'bezposredni', 'NaCl [%]', 'L941')")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (3, 'odour', 'Zapach', 'binarny')")
    db.execute("""INSERT INTO parametry_etapy
        (produkt, kontekst, parametr_id, kolejnosc, on_cert, cert_requirement, cert_format, cert_kolejnosc)
        VALUES ('Prod', 'analiza_koncowa', 1, 0, 1, 'min 35,5', '1', 0)""")
    db.execute("""INSERT INTO parametry_etapy
        (produkt, kontekst, parametr_id, kolejnosc, on_cert, cert_requirement, cert_format, cert_kolejnosc)
        VALUES ('Prod', 'analiza_koncowa', 2, 1, 0, NULL, NULL, NULL)""")
    db.execute("""INSERT INTO parametry_etapy
        (produkt, kontekst, parametr_id, kolejnosc, on_cert, cert_requirement, cert_format, cert_qualitative_result, cert_kolejnosc)
        VALUES ('Prod', 'analiza_koncowa', 3, 2, 1, 'charakterystyczny', '1', 'zgodny/right', 1)""")
    # Variant
    db.execute("INSERT INTO cert_variants (id, produkt, variant_id, label, flags, remove_params, kolejnosc) VALUES (1, 'Prod', 'loreal', 'Loreal', '[]', '[3]', 0)")
    db.commit()


def test_get_cert_params_returns_on_cert_only(db):
    """get_cert_params should return only rows with on_cert=1."""
    _seed_etapy_with_cert(db)
    from mbr.parametry.registry import get_cert_params
    params = get_cert_params(db, "Prod")
    kods = [p["kod"] for p in params]
    assert "sm" in kods
    assert "odour" in kods
    assert "nacl" not in kods  # on_cert=0


def test_get_cert_params_includes_cert_fields(db):
    """Returned rows should have cert_requirement, cert_format etc."""
    _seed_etapy_with_cert(db)
    from mbr.parametry.registry import get_cert_params
    params = get_cert_params(db, "Prod")
    sm = next(p for p in params if p["kod"] == "sm")
    assert sm["requirement"] == "min 35,5"
    assert sm["format"] == "1"
    assert sm["name_pl"] == "Sucha masa"
    assert sm["name_en"] == "Dry matter [%]"
    assert sm["method"] == "L903"


def test_get_cert_params_qualitative(db):
    """Qualitative params should have qualitative_result set."""
    _seed_etapy_with_cert(db)
    from mbr.parametry.registry import get_cert_params
    params = get_cert_params(db, "Prod")
    odour = next(p for p in params if p["kod"] == "odour")
    assert odour["qualitative_result"] == "zgodny/right"


def test_get_cert_params_ordered_by_cert_kolejnosc(db):
    """Results should be ordered by cert_kolejnosc."""
    _seed_etapy_with_cert(db)
    from mbr.parametry.registry import get_cert_params
    params = get_cert_params(db, "Prod")
    assert params[0]["kod"] == "sm"   # cert_kolejnosc=0
    assert params[1]["kod"] == "odour"  # cert_kolejnosc=1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_param_centralization.py::test_get_cert_params_returns_on_cert_only -v`
Expected: FAIL — `get_cert_params` not found

- [ ] **Step 3: Implement `get_cert_params` in registry.py**

Add to `mbr/parametry/registry.py` after `get_parametry_for_kontekst`:

```python
def get_cert_params(db: sqlite3.Connection, produkt: str) -> list[dict]:
    """Get certificate parameters for a product from parametry_etapy.

    Returns base params (on_cert=1, cert_variant_id IS NULL) ordered by cert_kolejnosc.
    Each row includes name_pl/name_en/method resolved from parametry_analityczne.
    """
    rows = db.execute("""
        SELECT
            pa.kod, pa.label, pa.name_en, pa.method_code,
            pe.cert_requirement, pe.cert_format, pe.cert_qualitative_result,
            pe.cert_kolejnosc, pe.parametr_id
        FROM parametry_etapy pe
        JOIN parametry_analityczne pa ON pa.id = pe.parametr_id
        WHERE pe.produkt = ? AND pe.kontekst = 'analiza_koncowa'
          AND pe.on_cert = 1 AND pe.cert_variant_id IS NULL
        ORDER BY pe.cert_kolejnosc
    """, (produkt,)).fetchall()

    return [
        {
            "kod": r["kod"],
            "parametr_id": r["parametr_id"],
            "name_pl": r["label"] or "",
            "name_en": r["name_en"] or "",
            "method": r["method_code"] or "",
            "requirement": r["cert_requirement"] or "",
            "format": r["cert_format"] or "1",
            "qualitative_result": r["cert_qualitative_result"],
        }
        for r in rows
    ]


def get_cert_variant_params(db: sqlite3.Connection, cert_variant_db_id: int) -> list[dict]:
    """Get variant-specific add_parameters from parametry_etapy."""
    rows = db.execute("""
        SELECT
            pa.kod, pa.label, pa.name_en, pa.method_code,
            pe.cert_requirement, pe.cert_format, pe.cert_qualitative_result,
            pe.cert_kolejnosc, pe.parametr_id
        FROM parametry_etapy pe
        JOIN parametry_analityczne pa ON pa.id = pe.parametr_id
        WHERE pe.kontekst = 'cert_variant' AND pe.cert_variant_id = ?
        ORDER BY pe.cert_kolejnosc
    """, (cert_variant_db_id,)).fetchall()

    return [
        {
            "kod": r["kod"],
            "parametr_id": r["parametr_id"],
            "name_pl": r["label"] or "",
            "name_en": r["name_en"] or "",
            "method": r["method_code"] or "",
            "requirement": r["cert_requirement"] or "",
            "format": r["cert_format"] or "1",
            "qualitative_result": r["cert_qualitative_result"],
        }
        for r in rows
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_param_centralization.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add mbr/parametry/registry.py tests/test_param_centralization.py
git commit -m "feat(params): get_cert_params — read cert data from parametry_etapy"
```

---

### Task 4: Update cert generator — dual-source with fallback

**Files:**
- Modify: `mbr/certs/generator.py` (build_context function, lines 139–258)
- Test: `tests/test_param_centralization.py` (extend)

- [ ] **Step 1: Write test for dual-source generator**

Append to `tests/test_param_centralization.py`:

```python
def test_build_context_reads_from_etapy_first(db):
    """Cert generator should use parametry_etapy when on_cert data exists."""
    _seed_etapy_with_cert(db)
    # Also seed parametry_cert with DIFFERENT requirement to prove etapy wins
    db.execute("INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format, variant_id) VALUES ('Prod', 1, 0, 'OLD requirement', '2', NULL)")
    db.commit()

    from mbr.parametry.registry import get_cert_params
    params = get_cert_params(db, "Prod")
    sm = next(p for p in params if p["kod"] == "sm")
    assert sm["requirement"] == "min 35,5"  # from etapy, not "OLD requirement"
```

- [ ] **Step 2: Run test to verify it passes** (it should — `get_cert_params` ignores `parametry_cert`)

Run: `pytest tests/test_param_centralization.py::test_build_context_reads_from_etapy_first -v`
Expected: PASS

- [ ] **Step 3: Update `build_context` in generator.py**

Replace the parameter loading section (lines 200–226) in `mbr/certs/generator.py`. The current code reads:

```python
        # 3. Base parameter rows (variant_id IS NULL)
        base_rows = db.execute(
            "SELECT pc.*, pa.kod, ... FROM parametry_cert pc ...",
        ).fetchall()
```

Replace with dual-source logic:

```python
        # 3. Base parameter rows — prefer parametry_etapy, fallback to parametry_cert
        from mbr.parametry.registry import get_cert_params, get_cert_variant_params

        etapy_params = get_cert_params(db, key)
        if etapy_params:
            base_param_rows = etapy_params
        else:
            # Fallback: legacy parametry_cert (until Phase 4 cleanup)
            _legacy = db.execute(
                "SELECT pc.*, pa.kod, pa.label AS pa_label, pa.name_en AS pa_name_en, "
                "pa.method_code AS pa_method_code "
                "FROM parametry_cert pc "
                "JOIN parametry_analityczne pa ON pa.id = pc.parametr_id "
                "WHERE pc.produkt = ? AND pc.variant_id IS NULL "
                "ORDER BY pc.kolejnosc",
                (key,),
            ).fetchall()
            base_param_rows = [
                {
                    "kod": r["kod"],
                    "parametr_id": r["parametr_id"],
                    "name_pl": r["name_pl"] or r["pa_label"] or "",
                    "name_en": r["name_en"] or r["pa_name_en"] or "",
                    "method": r["method"] or r["pa_method_code"] or "",
                    "requirement": r["requirement"] or "",
                    "format": r["format"] or "1",
                    "qualitative_result": r["qualitative_result"],
                }
                for r in _legacy
            ]

        # 4. Filter out remove_params
        if remove_params:
            base_param_rows = [r for r in base_param_rows if r["parametr_id"] not in remove_params]

        # 5. Variant-specific params
        etapy_variant = get_cert_variant_params(db, var_row["id"])
        if etapy_variant:
            variant_param_rows = etapy_variant
        else:
            _legacy_v = db.execute(
                "SELECT pc.*, pa.kod, pa.label AS pa_label, pa.name_en AS pa_name_en, "
                "pa.method_code AS pa_method_code "
                "FROM parametry_cert pc "
                "JOIN parametry_analityczne pa ON pa.id = pc.parametr_id "
                "WHERE pc.variant_id = ? ORDER BY pc.kolejnosc",
                (var_row["id"],),
            ).fetchall()
            variant_param_rows = [
                {
                    "kod": r["kod"],
                    "parametr_id": r["parametr_id"],
                    "name_pl": r["name_pl"] or r["pa_label"] or "",
                    "name_en": r["name_en"] or r["pa_name_en"] or "",
                    "method": r["method"] or r["pa_method_code"] or "",
                    "requirement": r["requirement"] or "",
                    "format": r["format"] or "1",
                    "qualitative_result": r["qualitative_result"],
                }
                for r in _legacy_v
            ]

        all_param_rows = base_param_rows + variant_param_rows
```

Then update the row-building loop (lines 228–258) to use the new dict format. Replace:

```python
        for r in all_param_rows:
            name_pl = r["name_pl"] or r["pa_label"] or ""
            name_en = r["name_en"] or r["pa_name_en"] or ""
            method = r["method"] or r["pa_method_code"] or ""
            ...
            if r["qualitative_result"]:
                result = r["qualitative_result"]
            ...
                fmt = r["format"] or "1"
```

With:

```python
        for r in all_param_rows:
            name_pl = r["name_pl"]
            name_en = r["name_en"]
            method = r["method"]

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
                        result = _format_value(float(val), r["format"])
                    except (ValueError, TypeError):
                        result = str(val).replace(".", ",")

            rows.append({
                "name_pl": _md_to_richtext(name_pl),
                "name_en": _md_to_richtext(f"/{name_en}") if name_en else _md_to_richtext(""),
                "requirement": r["requirement"],
                "method": method,
                "result": result,
            })
```

- [ ] **Step 4: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: all pass — cert generation produces identical output

- [ ] **Step 5: Commit**

```bash
git add mbr/certs/generator.py
git commit -m "feat(params): cert generator reads from parametry_etapy with fallback"
```

---

### Task 5: Add migration to auto-deploy + push

**Files:**
- Modify: `deploy/auto-deploy.sh`

- [ ] **Step 1: Add migration to auto-deploy**

Add after the existing `backfill_cert_name_en.py` line in `deploy/auto-deploy.sh`:

```bash
/opt/lims/venv/bin/python scripts/migrate_cert_to_etapy.py
```

- [ ] **Step 2: Run migration on local DB**

```bash
python scripts/migrate_cert_to_etapy.py
```

- [ ] **Step 3: Run full test suite one more time**

Run: `pytest tests/ -x -q`
Expected: all pass

- [ ] **Step 4: Commit and push**

```bash
git add deploy/auto-deploy.sh
git commit -m "deploy: add cert-to-etapy migration to auto-deploy"
git push origin main
```

---

## Verification Checklist

After all tasks complete:

1. `parametry_etapy` has 6 new cert columns
2. All 319 base + 13 variant cert params migrated
3. Cert generator reads from `parametry_etapy` (with `parametry_cert` fallback)
4. Certificate PDF output is identical before/after
5. All existing tests pass
6. `parametry_cert` table still exists (removed in Phase 4)
