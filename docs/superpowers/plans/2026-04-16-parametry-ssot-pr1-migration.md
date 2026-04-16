# Parametry SSOT — PR 1 (Etap A) — Migracja danych — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate all parameter binding data into the extended `produkt_etap_limity` table (adding typ flags, sa_bias, formula, kolejnosc, grupa, wymagany, krok) and port cert metadata into `parametry_cert`, without dropping the legacy tables yet. Old code keeps working; new data shape is in place.

**Architecture:** One idempotent Python script (`scripts/migrate_parametry_ssot.py`) with CLI flags `--dry-run`, `--verify-only`. Migration logic split into testable helper functions. Tracks completion via `_migrations` table. Backs up DB file before first run.

**Tech Stack:** Python 3 stdlib (sqlite3, argparse, shutil), pytest with in-memory SQLite fixtures, existing `mbr/models.py::init_mbr_tables()` for test DB setup.

---

## File Structure

**Create:**
- `scripts/migrate_parametry_ssot.py` — migration script with `main()`, `migrate(conn)`, and helpers
- `tests/test_migrate_parametry_ssot.py` — unit + integration tests using in-memory SQLite

**Modify:**
- `mbr/models.py:542-553` — update `CREATE TABLE produkt_etap_limity` to include new columns with CHECK constraints (so fresh dev DBs match migrated production DBs)

**Not touched in this PR:**
- Application code (routes, templates, adapter) — PR 2-5
- `parametry_etapy`, `etap_parametry` tables — not dropped yet (PR 6)

---

## Spec reference

- Full design: `docs/superpowers/specs/2026-04-16-parametry-ssot-design.md`
- This PR implements section "Migracja danych" steps 1–8, plus the schema update for fresh DBs (step 3 extended). Drop of old tables (step 9) is deferred to PR 6.

---

## Task 1: Set up test file skeleton

**Files:**
- Create: `tests/test_migrate_parametry_ssot.py`

- [ ] **Step 1: Create the test file with imports and fixture helper**

```python
"""Tests for scripts/migrate_parametry_ssot.py — consolidation of parameter bindings
into produkt_etap_limity with typ flags + cert metadata into parametry_cert."""

import sqlite3
import pytest

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    """In-memory SQLite with MBR schema initialized."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed_minimal_catalog(db):
    """Seed just enough parametry_analityczne + etapy_analityczne for migration tests."""
    db.executemany(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, precision, aktywny) VALUES (?, ?, ?, ?, ?, 1)",
        [
            (1, "ph", "pH", "bezposredni", 2),
            (2, "dietanolamina", "%dietanolaminy", "titracja", 1),
            (3, "barwa_I2", "Barwa jodowa", "bezposredni", 0),
            (4, "gliceryny", "%gliceryny", "bezposredni", 2),
        ],
    )
    db.executemany(
        "INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (?, ?, ?, ?)",
        [
            (6, "analiza_koncowa", "Analiza końcowa", "jednorazowy"),
            (7, "dodatki", "Dodatki standaryzacyjne", "cykliczny"),
        ],
    )
    db.commit()
```

- [ ] **Step 2: Verify fixture imports cleanly**

Run: `pytest tests/test_migrate_parametry_ssot.py --collect-only`
Expected: `no tests ran` with no import errors.

- [ ] **Step 3: Commit**

```bash
git add tests/test_migrate_parametry_ssot.py
git commit -m "test: scaffold parametry SSOT migration test file"
```

---

## Task 2: Script skeleton with CLI

**Files:**
- Create: `scripts/migrate_parametry_ssot.py`

- [ ] **Step 1: Write the failing test for CLI entry point**

Add to `tests/test_migrate_parametry_ssot.py`:

```python
def test_migrate_script_importable():
    """Module should expose migrate() and main() callables."""
    from scripts import migrate_parametry_ssot as mod

    assert callable(mod.migrate)
    assert callable(mod.main)
    assert callable(mod.preflight)
    assert callable(mod.postflight)
```

- [ ] **Step 2: Run test, expect fail**

Run: `pytest tests/test_migrate_parametry_ssot.py::test_migrate_script_importable -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.migrate_parametry_ssot'`

- [ ] **Step 3: Create the script skeleton**

Create `scripts/migrate_parametry_ssot.py`:

```python
"""Migrate parameter binding data from parametry_etapy + etap_parametry into the
extended produkt_etap_limity table, and cert metadata into parametry_cert.

Does NOT drop the legacy tables — that happens in a later PR after application
code is refactored to read from the new SSOT.

Usage:
    python -m scripts.migrate_parametry_ssot [--db PATH] [--dry-run] [--verify-only] [--force]
"""

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


MIGRATION_NAME = "parametry_ssot_v1"


def backup(db_path: str) -> str:
    """Copy DB file next to original with timestamped suffix. Return backup path."""
    src = Path(db_path)
    if not src.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")
    dst = src.with_suffix(src.suffix + f".bak-pre-parametry-ssot")
    shutil.copy2(src, dst)
    return str(dst)


def already_applied(db: sqlite3.Connection) -> bool:
    """Check if migration has run before using _migrations marker table."""
    db.execute(
        "CREATE TABLE IF NOT EXISTS _migrations ("
        " name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    row = db.execute(
        "SELECT 1 FROM _migrations WHERE name=?", (MIGRATION_NAME,)
    ).fetchone()
    return row is not None


def mark_applied(db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO _migrations (name, applied_at) VALUES (?, ?)",
        (MIGRATION_NAME, datetime.now().isoformat(timespec="seconds")),
    )


def preflight(db: sqlite3.Connection) -> list[str]:
    """Return list of blocker messages. Empty list = OK to proceed."""
    return []  # filled in later tasks


def postflight(db: sqlite3.Connection) -> list[str]:
    """Return list of post-migration validation errors. Empty list = OK."""
    return []  # filled in later tasks


def migrate(db: sqlite3.Connection, dry_run: bool = False) -> None:
    """Run the full migration inside a single transaction."""
    if already_applied(db):
        print(f"Migration {MIGRATION_NAME} already applied — skipping.")
        return

    blockers = preflight(db)
    if blockers:
        print("Pre-flight checks failed:", file=sys.stderr)
        for b in blockers:
            print(f"  - {b}", file=sys.stderr)
        raise SystemExit(1)

    if dry_run:
        print("Dry run — no changes will be committed.")

    # Migration steps filled in by later tasks.

    errors = postflight(db)
    if errors:
        print("Post-flight validation failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        raise SystemExit(2)

    if dry_run:
        db.rollback()
        print("Dry run complete — rolled back.")
    else:
        mark_applied(db)
        db.commit()
        print(f"Migration {MIGRATION_NAME} committed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/batch_db.sqlite")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run migration inside a transaction and roll back at the end.")
    parser.add_argument("--verify-only", action="store_true",
                        help="Run postflight only without altering data.")
    parser.add_argument("--force", action="store_true",
                        help="Re-run even if _migrations marker is present.")
    args = parser.parse_args()

    if not args.dry_run and not args.verify_only:
        bkp = backup(args.db)
        print(f"Backup: {bkp}")

    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")

    try:
        if args.verify_only:
            errors = postflight(db)
            if errors:
                for e in errors:
                    print(f"  - {e}")
                raise SystemExit(2)
            print("Verification OK.")
        else:
            if args.force:
                db.execute("DELETE FROM _migrations WHERE name=?", (MIGRATION_NAME,))
            migrate(db, dry_run=args.dry_run)
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Ensure `scripts/` is a package**

Check: `ls scripts/__init__.py`. If missing, create an empty file:
```bash
touch scripts/__init__.py
```

- [ ] **Step 5: Run test, expect pass**

Run: `pytest tests/test_migrate_parametry_ssot.py::test_migrate_script_importable -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/migrate_parametry_ssot.py scripts/__init__.py tests/test_migrate_parametry_ssot.py
git commit -m "feat(migration): parametry SSOT script skeleton with CLI"
```

---

## Task 3: Idempotence guard test

**Files:**
- Modify: `tests/test_migrate_parametry_ssot.py`

- [ ] **Step 1: Write test for idempotence marker**

Append to `tests/test_migrate_parametry_ssot.py`:

```python
from scripts.migrate_parametry_ssot import migrate, already_applied, MIGRATION_NAME


def test_migrate_marks_as_applied(db):
    _seed_minimal_catalog(db)
    migrate(db)
    assert already_applied(db) is True


def test_migrate_skips_when_already_applied(db, capsys):
    _seed_minimal_catalog(db)
    migrate(db)
    migrate(db)  # second call
    captured = capsys.readouterr()
    assert "already applied — skipping" in captured.out
```

- [ ] **Step 2: Run tests, expect pass**

Run: `pytest tests/test_migrate_parametry_ssot.py -v`
Expected: PASS for both idempotence tests (migration currently does nothing but still marks done).

- [ ] **Step 3: Commit**

```bash
git add tests/test_migrate_parametry_ssot.py
git commit -m "test: idempotence guard for parametry SSOT migration"
```

---

## Task 4: Preflight — detect NULL-produkt legacy rows

**Files:**
- Modify: `scripts/migrate_parametry_ssot.py` (function `preflight`)
- Modify: `tests/test_migrate_parametry_ssot.py`

- [ ] **Step 1: Write failing test**

Append to test file:

```python
def test_preflight_blocks_on_null_produkt(db):
    from scripts.migrate_parametry_ssot import preflight
    _seed_minimal_catalog(db)
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, kontekst, produkt) VALUES (1, 'analiza_koncowa', NULL)"
    )
    db.commit()
    blockers = preflight(db)
    assert any("NULL produkt" in b for b in blockers)


def test_preflight_passes_on_clean_db(db):
    from scripts.migrate_parametry_ssot import preflight
    _seed_minimal_catalog(db)
    assert preflight(db) == []
```

- [ ] **Step 2: Run tests, expect fail**

Run: `pytest tests/test_migrate_parametry_ssot.py::test_preflight_blocks_on_null_produkt -v`
Expected: FAIL — preflight returns `[]`.

- [ ] **Step 3: Implement NULL-produkt check in preflight**

Replace the `preflight` function body in `scripts/migrate_parametry_ssot.py`:

```python
def preflight(db: sqlite3.Connection) -> list[str]:
    """Return list of blocker messages. Empty list = OK to proceed."""
    blockers: list[str] = []

    null_rows = db.execute(
        "SELECT COUNT(*) AS n FROM parametry_etapy WHERE produkt IS NULL"
    ).fetchone()["n"]
    if null_rows > 0:
        blockers.append(
            f"{null_rows} parametry_etapy rows with NULL produkt (shared) — "
            "resolve manually (assign to product or delete) before migrating."
        )

    return blockers
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/test_migrate_parametry_ssot.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_parametry_ssot.py tests/test_migrate_parametry_ssot.py
git commit -m "feat(migration): preflight — block on NULL-produkt parametry_etapy rows"
```

---

## Task 5: Preflight — detect products without pipeline

**Files:**
- Modify: `scripts/migrate_parametry_ssot.py` (function `preflight`)
- Modify: `tests/test_migrate_parametry_ssot.py`

- [ ] **Step 1: Write failing test**

Append to test file:

```python
def test_preflight_reports_products_without_pipeline(db):
    from scripts.migrate_parametry_ssot import preflight
    _seed_minimal_catalog(db)
    # Chegina_K40GL has parametry_etapy rows but no produkt_pipeline row
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, kontekst, produkt, min_limit, max_limit) "
        "VALUES (1, 'analiza_koncowa', 'Chegina_K40GL', 0, 10)"
    )
    db.commit()
    blockers = preflight(db)
    # Legacy-only products are NOT blockers — script auto-creates pipeline entries.
    # But preflight should WARN (print), not block.
    assert blockers == []  # no blockers
    # Instead, the script should log them — we'll assert via capsys in task 8.
```

- [ ] **Step 2: Run test, expect pass**

This test should already pass (empty blockers list). The point is to lock in that *missing pipeline* is NOT a blocker — just a to-be-created situation.

Run: `pytest tests/test_migrate_parametry_ssot.py::test_preflight_reports_products_without_pipeline -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_migrate_parametry_ssot.py
git commit -m "test: products without pipeline are not preflight blockers"
```

---

## Task 6: Schema extension — ALTER TABLE on existing DB + update init_mbr_tables

**Files:**
- Modify: `scripts/migrate_parametry_ssot.py` (add `alter_schema` function)
- Modify: `mbr/models.py:542-553` (update CREATE TABLE for fresh DBs)
- Modify: `tests/test_migrate_parametry_ssot.py`

- [ ] **Step 1: Write failing test for alter_schema**

Append to test file:

```python
def test_alter_schema_adds_flag_columns(db):
    from scripts.migrate_parametry_ssot import alter_schema
    alter_schema(db)
    cols = {r["name"] for r in db.execute("PRAGMA table_info(produkt_etap_limity)").fetchall()}
    for expected in (
        "kolejnosc", "formula", "sa_bias", "krok", "wymagany", "grupa",
        "dla_szarzy", "dla_zbiornika", "dla_platkowania",
    ):
        assert expected in cols, f"missing column {expected}"


def test_alter_schema_idempotent(db):
    from scripts.migrate_parametry_ssot import alter_schema
    alter_schema(db)
    alter_schema(db)  # second call must not raise
    # Still valid schema
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (99, 'x', 'X', 'bezposredni')")
    db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (99, 'e', 'E', 'jednorazowy')")
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, dla_szarzy, dla_zbiornika, dla_platkowania) "
        "VALUES ('TEST', 99, 99, 1, 0, 0)"
    )
    row = db.execute("SELECT dla_szarzy, dla_zbiornika, dla_platkowania FROM produkt_etap_limity WHERE produkt='TEST'").fetchone()
    assert row["dla_szarzy"] == 1
    assert row["dla_zbiornika"] == 0
```

- [ ] **Step 2: Run tests, expect fail**

Run: `pytest tests/test_migrate_parametry_ssot.py::test_alter_schema_adds_flag_columns -v`
Expected: FAIL — `alter_schema` not defined.

- [ ] **Step 3: Implement alter_schema**

Add to `scripts/migrate_parametry_ssot.py` above `migrate()`:

```python
# Columns to add to produkt_etap_limity. ALTER TABLE ADD COLUMN can't add CHECK
# inline in SQLite, but values are controlled by application + init_mbr_tables
# CREATE TABLE (which does include CHECK) for fresh DBs.
_NEW_COLUMNS = [
    ("kolejnosc",       "INTEGER NOT NULL DEFAULT 0"),
    ("formula",         "TEXT"),
    ("sa_bias",         "REAL"),
    ("krok",            "INTEGER"),
    ("wymagany",        "INTEGER NOT NULL DEFAULT 0"),
    ("grupa",           "TEXT NOT NULL DEFAULT 'lab'"),
    ("dla_szarzy",      "INTEGER NOT NULL DEFAULT 1"),
    ("dla_zbiornika",   "INTEGER NOT NULL DEFAULT 1"),
    ("dla_platkowania", "INTEGER NOT NULL DEFAULT 0"),
]


def alter_schema(db: sqlite3.Connection) -> None:
    """Add new columns to produkt_etap_limity if missing. Idempotent."""
    existing = {r["name"] for r in db.execute(
        "PRAGMA table_info(produkt_etap_limity)"
    ).fetchall()}
    for name, decl in _NEW_COLUMNS:
        if name not in existing:
            db.execute(f"ALTER TABLE produkt_etap_limity ADD COLUMN {name} {decl}")
```

- [ ] **Step 4: Update init_mbr_tables CREATE TABLE with same columns + CHECK**

Edit `mbr/models.py:542-553`. Replace the existing block:

```python
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
            spec_value      REAL,
            kolejnosc       INTEGER NOT NULL DEFAULT 0,
            formula         TEXT,
            sa_bias         REAL,
            krok            INTEGER,
            wymagany        INTEGER NOT NULL DEFAULT 0 CHECK(wymagany IN (0,1)),
            grupa           TEXT NOT NULL DEFAULT 'lab',
            dla_szarzy      INTEGER NOT NULL DEFAULT 1 CHECK(dla_szarzy IN (0,1)),
            dla_zbiornika   INTEGER NOT NULL DEFAULT 1 CHECK(dla_zbiornika IN (0,1)),
            dla_platkowania INTEGER NOT NULL DEFAULT 0 CHECK(dla_platkowania IN (0,1)),
            UNIQUE(produkt, etap_id, parametr_id)
        )
    """)
```

- [ ] **Step 5: Wire alter_schema into migrate()**

In `scripts/migrate_parametry_ssot.py`, inside `migrate()` function, replace the comment `# Migration steps filled in by later tasks.` with:

```python
    alter_schema(db)
```

- [ ] **Step 6: Run tests, expect pass**

Run: `pytest tests/test_migrate_parametry_ssot.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/migrate_parametry_ssot.py mbr/models.py tests/test_migrate_parametry_ssot.py
git commit -m "feat(migration): alter_schema adds typ flags + ordering columns"
```

---

## Task 7: Auto-create produkt_pipeline for legacy-only products

**Files:**
- Modify: `scripts/migrate_parametry_ssot.py` (add `ensure_pipeline_for_legacy` function)
- Modify: `tests/test_migrate_parametry_ssot.py`

- [ ] **Step 1: Write failing test**

Append to test file:

```python
def test_ensure_pipeline_creates_entries_for_legacy_products(db):
    from scripts.migrate_parametry_ssot import ensure_pipeline_for_legacy
    _seed_minimal_catalog(db)
    # Legacy product with no pipeline row, parametry_etapy uses kontekst='analiza_koncowa'
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, kontekst, produkt, min_limit, max_limit) "
        "VALUES (1, 'analiza_koncowa', 'Chegina_K40GL', 0, 10)"
    )
    db.commit()
    ensure_pipeline_for_legacy(db)
    row = db.execute(
        "SELECT etap_id FROM produkt_pipeline WHERE produkt='Chegina_K40GL'"
    ).fetchone()
    assert row is not None
    assert row["etap_id"] == 6  # analiza_koncowa's etap_id from _seed_minimal_catalog


def test_ensure_pipeline_idempotent(db):
    from scripts.migrate_parametry_ssot import ensure_pipeline_for_legacy
    _seed_minimal_catalog(db)
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, kontekst, produkt, min_limit, max_limit) "
        "VALUES (1, 'analiza_koncowa', 'Chegina_K40GL', 0, 10)"
    )
    db.commit()
    ensure_pipeline_for_legacy(db)
    ensure_pipeline_for_legacy(db)  # must not duplicate
    n = db.execute(
        "SELECT COUNT(*) AS n FROM produkt_pipeline WHERE produkt='Chegina_K40GL'"
    ).fetchone()["n"]
    assert n == 1
```

- [ ] **Step 2: Run test, expect fail**

Run: `pytest tests/test_migrate_parametry_ssot.py::test_ensure_pipeline_creates_entries_for_legacy_products -v`
Expected: FAIL — function not defined.

- [ ] **Step 3: Implement ensure_pipeline_for_legacy**

Add to `scripts/migrate_parametry_ssot.py`:

```python
# Known kontekst → etap kod mappings. cert_variant is not a measurement etap —
# those rows go to parametry_cert instead and are NOT added to produkt_pipeline.
_NON_ETAP_KONTEKSTY = {"cert_variant"}


def _kontekst_to_etap_id(db: sqlite3.Connection, kontekst: str) -> int | None:
    """Resolve kontekst name to etapy_analityczne.id. None if non-etap (cert_variant)."""
    if kontekst in _NON_ETAP_KONTEKSTY:
        return None
    row = db.execute(
        "SELECT id FROM etapy_analityczne WHERE kod=?", (kontekst,)
    ).fetchone()
    return row["id"] if row else None


def ensure_pipeline_for_legacy(db: sqlite3.Connection) -> list[tuple[str, int]]:
    """For each (produkt, kontekst) in parametry_etapy lacking a produkt_pipeline row,
    create one. Returns list of (produkt, etap_id) inserts made."""
    pairs = db.execute(
        "SELECT DISTINCT produkt, kontekst FROM parametry_etapy "
        "WHERE produkt IS NOT NULL"
    ).fetchall()
    inserted: list[tuple[str, int]] = []
    for pair in pairs:
        produkt = pair["produkt"]
        kontekst = pair["kontekst"]
        etap_id = _kontekst_to_etap_id(db, kontekst)
        if etap_id is None:
            continue
        exists = db.execute(
            "SELECT 1 FROM produkt_pipeline WHERE produkt=? AND etap_id=?",
            (produkt, etap_id),
        ).fetchone()
        if exists:
            continue
        next_kol = db.execute(
            "SELECT COALESCE(MAX(kolejnosc), 0) + 1 AS k FROM produkt_pipeline WHERE produkt=?",
            (produkt,),
        ).fetchone()["k"]
        db.execute(
            "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES (?, ?, ?)",
            (produkt, etap_id, next_kol),
        )
        inserted.append((produkt, etap_id))
    return inserted
```

- [ ] **Step 4: Wire into migrate()**

In `scripts/migrate_parametry_ssot.py`, update `migrate()`:

```python
    alter_schema(db)
    created_pipelines = ensure_pipeline_for_legacy(db)
    if created_pipelines:
        print(f"Created {len(created_pipelines)} produkt_pipeline entries for legacy products:")
        for produkt, etap_id in created_pipelines:
            print(f"  - {produkt} → etap_id={etap_id}")
```

- [ ] **Step 5: Run tests, expect pass**

Run: `pytest tests/test_migrate_parametry_ssot.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/migrate_parametry_ssot.py tests/test_migrate_parametry_ssot.py
git commit -m "feat(migration): auto-create produkt_pipeline for legacy-only products"
```

---

## Task 8: Copy limits from parametry_etapy into produkt_etap_limity

**Files:**
- Modify: `scripts/migrate_parametry_ssot.py` (add `copy_limits` function)
- Modify: `tests/test_migrate_parametry_ssot.py`

- [ ] **Step 1: Write failing test**

Append to test file:

```python
def test_copy_limits_inserts_rows_with_default_typ_flags(db):
    from scripts.migrate_parametry_ssot import alter_schema, ensure_pipeline_for_legacy, copy_limits
    _seed_minimal_catalog(db)
    alter_schema(db)
    # Legacy row: Chelamid_DK has parametry_etapy row for 'dietanolamina'
    db.execute(
        "INSERT INTO parametry_etapy "
        "(parametr_id, kontekst, produkt, min_limit, max_limit, nawazka_g, precision, target, "
        " kolejnosc, formula, sa_bias, krok, grupa) "
        "VALUES (2, 'analiza_koncowa', 'Chelamid_DK', 80, 9999, 0.5, 1, NULL, 3, NULL, NULL, NULL, 'lab')"
    )
    # produkt_pipeline entry (or ensure_pipeline_for_legacy creates it)
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chelamid_DK', 6, 1)")
    db.commit()
    copy_limits(db)
    row = db.execute(
        "SELECT min_limit, max_limit, nawazka_g, precision, kolejnosc, grupa, "
        "dla_szarzy, dla_zbiornika, dla_platkowania "
        "FROM produkt_etap_limity WHERE produkt='Chelamid_DK' AND etap_id=6 AND parametr_id=2"
    ).fetchone()
    assert row is not None
    assert row["min_limit"] == 80
    assert row["max_limit"] == 9999
    assert row["nawazka_g"] == 0.5
    assert row["precision"] == 1
    assert row["kolejnosc"] == 3
    assert row["dla_szarzy"] == 1
    assert row["dla_zbiornika"] == 1
    assert row["dla_platkowania"] == 0


def test_copy_limits_preserves_existing_produkt_etap_limity_values(db):
    """If a pipeline product already has produkt_etap_limity rows, do not overwrite
    non-null values with NULLs from parametry_etapy."""
    from scripts.migrate_parametry_ssot import alter_schema, copy_limits
    _seed_minimal_catalog(db)
    alter_schema(db)
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chelamid_DK', 6, 1)")
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, min_limit, max_limit, precision) "
        "VALUES ('Chelamid_DK', 6, 2, 85, 99, 2)"  # already-set values
    )
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, kontekst, produkt, min_limit, max_limit, precision) "
        "VALUES (2, 'analiza_koncowa', 'Chelamid_DK', NULL, NULL, NULL)"
    )
    db.commit()
    copy_limits(db)
    row = db.execute(
        "SELECT min_limit, max_limit, precision FROM produkt_etap_limity "
        "WHERE produkt='Chelamid_DK' AND etap_id=6 AND parametr_id=2"
    ).fetchone()
    assert row["min_limit"] == 85
    assert row["max_limit"] == 99
    assert row["precision"] == 2


def test_copy_limits_skips_cert_variant_kontekst(db):
    """cert_variant rows are cert metadata, not pomiar bindings."""
    from scripts.migrate_parametry_ssot import alter_schema, copy_limits
    _seed_minimal_catalog(db)
    alter_schema(db)
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, kontekst, produkt) VALUES (1, 'cert_variant', 'Chelamid_DK')"
    )
    db.commit()
    copy_limits(db)
    n = db.execute("SELECT COUNT(*) AS n FROM produkt_etap_limity").fetchone()["n"]
    assert n == 0
```

- [ ] **Step 2: Run tests, expect fail**

Run: `pytest tests/test_migrate_parametry_ssot.py::test_copy_limits_inserts_rows_with_default_typ_flags -v`
Expected: FAIL — `copy_limits` not defined.

- [ ] **Step 3: Implement copy_limits**

Add to `scripts/migrate_parametry_ssot.py`:

```python
def copy_limits(db: sqlite3.Connection) -> int:
    """Copy limits from parametry_etapy into produkt_etap_limity. Returns rows touched.

    - Skips kontekst='cert_variant' (handled by migrate_cert_fields instead)
    - If target row exists and destination value is NOT NULL, keep destination
    - Default typ flags: dla_szarzy=1, dla_zbiornika=1, dla_platkowania=0
    - Assumes ensure_pipeline_for_legacy has already run
    """
    src_rows = db.execute(
        "SELECT parametr_id, kontekst, produkt, min_limit, max_limit, nawazka_g, "
        "       precision, target, kolejnosc, formula, sa_bias, krok, grupa "
        "FROM parametry_etapy WHERE produkt IS NOT NULL"
    ).fetchall()
    touched = 0
    for r in src_rows:
        etap_id = _kontekst_to_etap_id(db, r["kontekst"])
        if etap_id is None:
            continue
        dst = db.execute(
            "SELECT id, min_limit, max_limit, nawazka_g, precision, spec_value, "
            "       kolejnosc, formula, sa_bias, krok, grupa "
            "FROM produkt_etap_limity WHERE produkt=? AND etap_id=? AND parametr_id=?",
            (r["produkt"], etap_id, r["parametr_id"]),
        ).fetchone()
        if dst is None:
            db.execute(
                "INSERT INTO produkt_etap_limity "
                "(produkt, etap_id, parametr_id, min_limit, max_limit, nawazka_g, precision, "
                " spec_value, kolejnosc, formula, sa_bias, krok, grupa, "
                " dla_szarzy, dla_zbiornika, dla_platkowania) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 0)",
                (r["produkt"], etap_id, r["parametr_id"],
                 r["min_limit"], r["max_limit"], r["nawazka_g"], r["precision"],
                 r["target"], r["kolejnosc"] or 0, r["formula"], r["sa_bias"],
                 r["krok"], r["grupa"] or "lab"),
            )
        else:
            # Partial update: fill only NULLs in destination with non-NULL from source
            updates: list[tuple[str, object]] = []
            src_map = {
                "min_limit": r["min_limit"],
                "max_limit": r["max_limit"],
                "nawazka_g": r["nawazka_g"],
                "precision": r["precision"],
                "spec_value": r["target"],
                "kolejnosc": r["kolejnosc"],
                "formula":   r["formula"],
                "sa_bias":   r["sa_bias"],
                "krok":      r["krok"],
                "grupa":     r["grupa"],
            }
            for col, src_val in src_map.items():
                if src_val is not None and dst[col] is None:
                    updates.append((col, src_val))
            if updates:
                sets = ", ".join(f"{c}=?" for c, _ in updates)
                vals = [v for _, v in updates] + [dst["id"]]
                db.execute(f"UPDATE produkt_etap_limity SET {sets} WHERE id=?", vals)
        touched += 1
    return touched
```

- [ ] **Step 4: Wire into migrate()**

In `scripts/migrate_parametry_ssot.py`, add after `ensure_pipeline_for_legacy` in `migrate()`:

```python
    n_limits = copy_limits(db)
    print(f"Copied/verified {n_limits} limit bindings.")
```

- [ ] **Step 5: Run tests, expect pass**

Run: `pytest tests/test_migrate_parametry_ssot.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/migrate_parametry_ssot.py tests/test_migrate_parametry_ssot.py
git commit -m "feat(migration): copy limits from parametry_etapy to produkt_etap_limity"
```

---

## Task 9: Migrate sa_bias from etap_parametry into produkt_etap_limity

**Files:**
- Modify: `scripts/migrate_parametry_ssot.py` (add `migrate_sa_bias` function)
- Modify: `tests/test_migrate_parametry_ssot.py`

- [ ] **Step 1: Write failing test**

Append to test file:

```python
def test_migrate_sa_bias_copies_global_to_per_product(db):
    from scripts.migrate_parametry_ssot import alter_schema, migrate_sa_bias
    _seed_minimal_catalog(db)
    alter_schema(db)
    # Parameter 1 has sa_bias set globally in etap_parametry for etap 6
    db.execute(
        "INSERT INTO etap_parametry (etap_id, parametr_id, sa_bias) VALUES (6, 1, 0.25)"
    )
    # Two products both bound to parametr_id=1 via produkt_etap_limity
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('A', 6, 1)")
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('B', 6, 1)")
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id) VALUES ('A', 6, 1)"
    )
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id) VALUES ('B', 6, 1)"
    )
    db.commit()
    migrate_sa_bias(db)
    rows = db.execute(
        "SELECT produkt, sa_bias FROM produkt_etap_limity WHERE parametr_id=1 ORDER BY produkt"
    ).fetchall()
    assert [(r["produkt"], r["sa_bias"]) for r in rows] == [("A", 0.25), ("B", 0.25)]


def test_migrate_sa_bias_preserves_per_product_override(db):
    """If produkt_etap_limity.sa_bias is already set, do NOT overwrite with etap_parametry value."""
    from scripts.migrate_parametry_ssot import alter_schema, migrate_sa_bias
    _seed_minimal_catalog(db)
    alter_schema(db)
    db.execute(
        "INSERT INTO etap_parametry (etap_id, parametr_id, sa_bias) VALUES (6, 1, 0.25)"
    )
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('A', 6, 1)")
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, sa_bias) VALUES ('A', 6, 1, 0.75)"
    )
    db.commit()
    migrate_sa_bias(db)
    row = db.execute(
        "SELECT sa_bias FROM produkt_etap_limity WHERE produkt='A' AND parametr_id=1"
    ).fetchone()
    assert row["sa_bias"] == 0.75
```

- [ ] **Step 2: Run tests, expect fail**

Run: `pytest tests/test_migrate_parametry_ssot.py::test_migrate_sa_bias_copies_global_to_per_product -v`
Expected: FAIL — `migrate_sa_bias` not defined.

- [ ] **Step 3: Implement migrate_sa_bias**

Add to `scripts/migrate_parametry_ssot.py`:

```python
def migrate_sa_bias(db: sqlite3.Connection) -> int:
    """Copy non-null sa_bias from etap_parametry to every matching produkt_etap_limity
    row, ONLY where the destination sa_bias is NULL. Returns updates made."""
    src_rows = db.execute(
        "SELECT etap_id, parametr_id, sa_bias FROM etap_parametry WHERE sa_bias IS NOT NULL"
    ).fetchall()
    updated = 0
    for r in src_rows:
        cur = db.execute(
            "UPDATE produkt_etap_limity SET sa_bias=? "
            "WHERE etap_id=? AND parametr_id=? AND sa_bias IS NULL",
            (r["sa_bias"], r["etap_id"], r["parametr_id"]),
        )
        updated += cur.rowcount
    return updated
```

- [ ] **Step 4: Wire into migrate()**

Add after `copy_limits` call:

```python
    n_sa = migrate_sa_bias(db)
    if n_sa:
        print(f"Propagated sa_bias to {n_sa} produkt_etap_limity rows.")
```

- [ ] **Step 5: Run tests, expect pass**

Run: `pytest tests/test_migrate_parametry_ssot.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/migrate_parametry_ssot.py tests/test_migrate_parametry_ssot.py
git commit -m "feat(migration): propagate sa_bias from etap_parametry to produkt_etap_limity"
```

---

## Task 10: Migrate cert metadata into parametry_cert

**Files:**
- Modify: `scripts/migrate_parametry_ssot.py` (add `migrate_cert_fields` function)
- Modify: `tests/test_migrate_parametry_ssot.py`

- [ ] **Step 1: Write failing test**

Append to test file:

```python
def test_migrate_cert_fields_inserts_into_parametry_cert(db):
    from scripts.migrate_parametry_ssot import migrate_cert_fields
    _seed_minimal_catalog(db)
    db.execute(
        "INSERT INTO parametry_etapy "
        "(parametr_id, kontekst, produkt, on_cert, cert_requirement, cert_format, "
        " cert_qualitative_result, cert_kolejnosc) "
        "VALUES (1, 'analiza_koncowa', 'Chelamid_DK', 1, 'max 11', '2', NULL, 3)"
    )
    db.commit()
    migrate_cert_fields(db)
    row = db.execute(
        "SELECT requirement, format, qualitative_result, kolejnosc, variant_id "
        "FROM parametry_cert WHERE produkt='Chelamid_DK' AND parametr_id=1"
    ).fetchone()
    assert row is not None
    assert row["requirement"] == "max 11"
    assert row["format"] == "2"
    assert row["qualitative_result"] is None
    assert row["kolejnosc"] == 3
    assert row["variant_id"] is None  # base cert (no variant)


def test_migrate_cert_fields_handles_variant(db):
    from scripts.migrate_parametry_ssot import migrate_cert_fields
    _seed_minimal_catalog(db)
    db.execute("INSERT INTO cert_variants (id, produkt, variant_id, label) VALUES (10, 'Chelamid_DK', 'pelna', 'Chelamid DK — PEŁNA')")
    db.execute(
        "INSERT INTO parametry_etapy "
        "(parametr_id, kontekst, produkt, on_cert, cert_requirement, cert_format, cert_variant_id, cert_kolejnosc) "
        "VALUES (2, 'cert_variant', 'Chelamid_DK', 1, '80-90', '1', 10, 5)"
    )
    db.commit()
    migrate_cert_fields(db)
    row = db.execute(
        "SELECT requirement, variant_id, kolejnosc FROM parametry_cert "
        "WHERE produkt='Chelamid_DK' AND parametr_id=2"
    ).fetchone()
    assert row["requirement"] == "80-90"
    assert row["variant_id"] == 10
    assert row["kolejnosc"] == 5


def test_migrate_cert_fields_skips_non_cert_rows(db):
    from scripts.migrate_parametry_ssot import migrate_cert_fields
    _seed_minimal_catalog(db)
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, kontekst, produkt, on_cert) "
        "VALUES (1, 'analiza_koncowa', 'Chelamid_DK', 0)"
    )
    db.commit()
    migrate_cert_fields(db)
    n = db.execute("SELECT COUNT(*) AS n FROM parametry_cert").fetchone()["n"]
    assert n == 0
```

- [ ] **Step 2: Run tests, expect fail**

Run: `pytest tests/test_migrate_parametry_ssot.py::test_migrate_cert_fields_inserts_into_parametry_cert -v`
Expected: FAIL — `migrate_cert_fields` not defined.

- [ ] **Step 3: Inspect parametry_cert schema**

Before implementing, confirm schema:

Run: `sqlite3 data/batch_db.sqlite ".schema parametry_cert"`
Confirm columns include: `produkt`, `parametr_id`, `variant_id`, `requirement`, `format`, `qualitative_result`, `kolejnosc`, `name_pl`, `name_en`, `method`.

- [ ] **Step 4: Implement migrate_cert_fields**

Add to `scripts/migrate_parametry_ssot.py`:

```python
def migrate_cert_fields(db: sqlite3.Connection) -> int:
    """Copy on_cert=1 rows from parametry_etapy into parametry_cert.
    UPSERT by (produkt, parametr_id, variant_id)."""
    src_rows = db.execute(
        "SELECT parametr_id, produkt, cert_requirement, cert_format, "
        "       cert_qualitative_result, cert_kolejnosc, cert_variant_id "
        "FROM parametry_etapy "
        "WHERE on_cert=1 AND produkt IS NOT NULL"
    ).fetchall()
    touched = 0
    for r in src_rows:
        existing = db.execute(
            "SELECT id FROM parametry_cert "
            "WHERE produkt=? AND parametr_id=? "
            "  AND ((variant_id IS NULL AND ? IS NULL) OR variant_id = ?)",
            (r["produkt"], r["parametr_id"], r["cert_variant_id"], r["cert_variant_id"]),
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE parametry_cert SET "
                " requirement         = COALESCE(?, requirement), "
                " format              = COALESCE(?, format), "
                " qualitative_result  = COALESCE(?, qualitative_result), "
                " kolejnosc           = COALESCE(?, kolejnosc) "
                "WHERE id=?",
                (r["cert_requirement"], r["cert_format"],
                 r["cert_qualitative_result"], r["cert_kolejnosc"], existing["id"]),
            )
        else:
            db.execute(
                "INSERT INTO parametry_cert "
                "(produkt, parametr_id, variant_id, requirement, format, "
                " qualitative_result, kolejnosc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (r["produkt"], r["parametr_id"], r["cert_variant_id"],
                 r["cert_requirement"], r["cert_format"],
                 r["cert_qualitative_result"], r["cert_kolejnosc"]),
            )
        touched += 1
    return touched
```

- [ ] **Step 5: Wire into migrate()**

Add after `migrate_sa_bias` call:

```python
    n_cert = migrate_cert_fields(db)
    print(f"Migrated {n_cert} cert metadata rows to parametry_cert.")
```

- [ ] **Step 6: Run tests, expect pass**

Run: `pytest tests/test_migrate_parametry_ssot.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/migrate_parametry_ssot.py tests/test_migrate_parametry_ssot.py
git commit -m "feat(migration): migrate cert fields from parametry_etapy to parametry_cert"
```

---

## Task 11: Post-flight validation

**Files:**
- Modify: `scripts/migrate_parametry_ssot.py` (replace `postflight` stub)
- Modify: `tests/test_migrate_parametry_ssot.py`

- [ ] **Step 1: Write failing tests**

Append to test file:

```python
def test_postflight_passes_on_healthy_migration(db):
    from scripts.migrate_parametry_ssot import alter_schema, postflight
    _seed_minimal_catalog(db)
    alter_schema(db)
    db.execute("INSERT INTO mbr_templates (mbr_id, produkt, status) VALUES (1, 'Chelamid_DK', 'active')")
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chelamid_DK', 6, 1)")
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, dla_szarzy) "
        "VALUES ('Chelamid_DK', 6, 1, 1)"
    )
    db.commit()
    assert postflight(db) == []


def test_postflight_fails_on_active_product_with_no_bindings(db):
    from scripts.migrate_parametry_ssot import alter_schema, postflight
    _seed_minimal_catalog(db)
    alter_schema(db)
    db.execute("INSERT INTO mbr_templates (mbr_id, produkt, status) VALUES (1, 'Chelamid_DK', 'active')")
    db.commit()
    errors = postflight(db)
    assert any("Chelamid_DK" in e and "no visible bindings" in e for e in errors)


def test_postflight_fails_on_orphan_binding(db):
    """produkt_etap_limity row for etap_id not in that produkt's pipeline."""
    from scripts.migrate_parametry_ssot import alter_schema, postflight
    _seed_minimal_catalog(db)
    alter_schema(db)
    db.execute("INSERT INTO mbr_templates (mbr_id, produkt, status) VALUES (1, 'Chelamid_DK', 'active')")
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chelamid_DK', 6, 1)")
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, dla_szarzy) "
        "VALUES ('Chelamid_DK', 7, 1, 1)"  # etap_id 7 NOT in pipeline for this produkt
    )
    db.commit()
    errors = postflight(db)
    assert any("orphan" in e.lower() for e in errors)
```

- [ ] **Step 2: Run tests, expect fail**

Run: `pytest tests/test_migrate_parametry_ssot.py::test_postflight_passes_on_healthy_migration -v`
Expected: FAIL (current postflight returns `[]` but the schema check for orphan not implemented yet — depending on current state, one of the tests may already pass).

- [ ] **Step 3: Implement postflight**

Replace the `postflight` stub in `scripts/migrate_parametry_ssot.py`:

```python
def postflight(db: sqlite3.Connection) -> list[str]:
    """Return list of post-migration validation errors. Empty list = OK."""
    errors: list[str] = []

    # Check 1: every active MBR template has at least one visible binding
    rows = db.execute("""
        SELECT mt.produkt
        FROM mbr_templates mt
        WHERE mt.status = 'active'
          AND NOT EXISTS (
            SELECT 1 FROM produkt_etap_limity pel
             WHERE pel.produkt = mt.produkt
               AND (pel.dla_szarzy=1 OR pel.dla_zbiornika=1 OR pel.dla_platkowania=1)
          )
    """).fetchall()
    for r in rows:
        errors.append(f"Active product '{r['produkt']}' has no visible bindings in produkt_etap_limity.")

    # Check 2: no orphan bindings (etap_id not in that produkt's pipeline)
    rows = db.execute("""
        SELECT pel.produkt, pel.etap_id
        FROM produkt_etap_limity pel
        WHERE NOT EXISTS (
            SELECT 1 FROM produkt_pipeline pp
             WHERE pp.produkt = pel.produkt AND pp.etap_id = pel.etap_id
        )
    """).fetchall()
    for r in rows:
        errors.append(
            f"Orphan binding: produkt='{r['produkt']}' etap_id={r['etap_id']} "
            "has no matching produkt_pipeline row."
        )

    return errors
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/test_migrate_parametry_ssot.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_parametry_ssot.py tests/test_migrate_parametry_ssot.py
git commit -m "feat(migration): postflight validates active products + no orphan bindings"
```

---

## Task 12: Integration test — full migration end-to-end

**Files:**
- Modify: `tests/test_migrate_parametry_ssot.py`

- [ ] **Step 1: Write an integration test**

Append to test file:

```python
def test_full_migration_end_to_end_chelamid_dk_shape(db):
    """Seed DB in the legacy shape, run migrate(), verify the new SSOT shape."""
    from scripts.migrate_parametry_ssot import migrate

    _seed_minimal_catalog(db)
    db.execute("INSERT INTO mbr_templates (mbr_id, produkt, status) VALUES (1, 'Chelamid_DK', 'active')")
    # Legacy-style bindings: parametry_etapy with limits + on_cert for dietanolamina
    db.execute(
        "INSERT INTO parametry_etapy "
        "(parametr_id, kontekst, produkt, min_limit, max_limit, nawazka_g, precision, "
        " kolejnosc, grupa, on_cert, cert_requirement, cert_format, cert_kolejnosc) "
        "VALUES (2, 'analiza_koncowa', 'Chelamid_DK', 80, 9999, 0.5, 1, 1, 'lab', "
        "        1, '80-90', '1', 5)"
    )
    db.execute(
        "INSERT INTO parametry_etapy "
        "(parametr_id, kontekst, produkt, min_limit, max_limit, precision, kolejnosc) "
        "VALUES (1, 'analiza_koncowa', 'Chelamid_DK', 0, 11, 2, 2)"
    )
    # Note: no produkt_pipeline row — migration will create it.
    db.commit()

    migrate(db)

    # Pipeline entry created
    pp = db.execute("SELECT etap_id FROM produkt_pipeline WHERE produkt='Chelamid_DK'").fetchall()
    assert len(pp) == 1
    assert pp[0]["etap_id"] == 6

    # Two produkt_etap_limity rows exist with default typ flags
    bindings = db.execute(
        "SELECT parametr_id, min_limit, max_limit, nawazka_g, precision, kolejnosc, "
        "       dla_szarzy, dla_zbiornika, dla_platkowania "
        "FROM produkt_etap_limity WHERE produkt='Chelamid_DK' ORDER BY kolejnosc"
    ).fetchall()
    assert len(bindings) == 2
    for b in bindings:
        assert b["dla_szarzy"] == 1
        assert b["dla_zbiornika"] == 1
        assert b["dla_platkowania"] == 0

    # Cert metadata migrated for dietanolamina
    cert = db.execute(
        "SELECT requirement, format, kolejnosc FROM parametry_cert "
        "WHERE produkt='Chelamid_DK' AND parametr_id=2"
    ).fetchone()
    assert cert["requirement"] == "80-90"
    assert cert["format"] == "1"
    assert cert["kolejnosc"] == 5

    # _migrations marker set
    from scripts.migrate_parametry_ssot import already_applied
    assert already_applied(db) is True
```

- [ ] **Step 2: Run test, expect pass**

Run: `pytest tests/test_migrate_parametry_ssot.py::test_full_migration_end_to_end_chelamid_dk_shape -v`
Expected: PASS.

- [ ] **Step 3: Run full suite**

Run: `pytest tests/test_migrate_parametry_ssot.py -v`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_migrate_parametry_ssot.py
git commit -m "test: full migration end-to-end integration test"
```

---

## Task 13: Golden snapshot for real-DB Chelamid_DK

**Files:**
- Create: `tests/test_migrate_parametry_ssot_realdb.py`

- [ ] **Step 1: Write the real-DB smoke test**

This test runs against a copy of the production DB to catch real-world divergences that synthetic fixtures miss. It skips cleanly in environments without the DB file.

Create `tests/test_migrate_parametry_ssot_realdb.py`:

```python
"""Real-DB integration test: copy data/batch_db.sqlite, run migration, assert
the post-migration shape for Chelamid_DK is identical (kodу, limits, kolejność)
to what the pre-migration queries produced."""

import shutil
import sqlite3
from pathlib import Path

import pytest

REAL_DB = Path("data/batch_db.sqlite")


pytestmark = pytest.mark.skipif(
    not REAL_DB.exists(),
    reason="data/batch_db.sqlite not available in this environment",
)


@pytest.fixture
def real_db_copy(tmp_path):
    dst = tmp_path / "batch_db.sqlite"
    shutil.copy2(REAL_DB, dst)
    conn = sqlite3.connect(dst)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    yield conn
    conn.close()


def _pre_migration_snapshot(db):
    """What Chelamid_DK 'should look like' pre-migration, via the pipeline path
    that the application currently uses for rendering."""
    return db.execute("""
        SELECT pa.kod, pel.min_limit, pel.max_limit, pel.nawazka_g, pel.precision
        FROM produkt_etap_limity pel
        JOIN parametry_analityczne pa ON pa.id = pel.parametr_id
        WHERE pel.produkt='Chelamid_DK' AND pel.etap_id=6
        ORDER BY pa.kod
    """).fetchall()


def _post_migration_snapshot(db):
    """Same query, but filtered to typ=szarza (should match pre-migration identity
    because default flag is dla_szarzy=1)."""
    return db.execute("""
        SELECT pa.kod, pel.min_limit, pel.max_limit, pel.nawazka_g, pel.precision
        FROM produkt_etap_limity pel
        JOIN parametry_analityczne pa ON pa.id = pel.parametr_id
        WHERE pel.produkt='Chelamid_DK' AND pel.etap_id=6 AND pel.dla_szarzy=1
        ORDER BY pa.kod
    """).fetchall()


def test_chelamid_dk_shape_unchanged_after_migration(real_db_copy):
    from scripts.migrate_parametry_ssot import migrate

    before = [dict(r) for r in _pre_migration_snapshot(real_db_copy)]
    migrate(real_db_copy)
    after = [dict(r) for r in _post_migration_snapshot(real_db_copy)]
    assert after == before, f"Chelamid_DK shape drifted.\nBefore: {before}\nAfter:  {after}"
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_migrate_parametry_ssot_realdb.py -v`
Expected: PASS (migration is no-op for already-aligned data in the real DB) or SKIP if DB absent.

- [ ] **Step 3: Commit**

```bash
git add tests/test_migrate_parametry_ssot_realdb.py
git commit -m "test: real-DB smoke test for Chelamid_DK migration shape"
```

---

## Task 14: Dry-run CLI smoke test

**Files:**
- Modify: `tests/test_migrate_parametry_ssot.py`

- [ ] **Step 1: Write failing test**

Append to test file:

```python
def test_dry_run_rolls_back_changes(db):
    from scripts.migrate_parametry_ssot import migrate, already_applied
    _seed_minimal_catalog(db)
    db.execute("INSERT INTO mbr_templates (mbr_id, produkt, status) VALUES (1, 'Chelamid_DK', 'active')")
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, kontekst, produkt, min_limit, max_limit) "
        "VALUES (1, 'analiza_koncowa', 'Chelamid_DK', 0, 11)"
    )
    db.commit()

    migrate(db, dry_run=True)

    # No pipeline entry, no produkt_etap_limity row, no marker
    assert db.execute("SELECT COUNT(*) AS n FROM produkt_pipeline WHERE produkt='Chelamid_DK'").fetchone()["n"] == 0
    assert db.execute("SELECT COUNT(*) AS n FROM produkt_etap_limity WHERE produkt='Chelamid_DK'").fetchone()["n"] == 0
    assert already_applied(db) is False
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_migrate_parametry_ssot.py::test_dry_run_rolls_back_changes -v`
Expected: PASS (dry_run=True rolls back in the current implementation).

If it fails, inspect `migrate()` to ensure `db.rollback()` is reached when `dry_run=True` — note that `alter_schema` uses DDL which commits implicitly in SQLite; the dry-run rollback may not fully undo ALTER TABLE. In that case, the test should assert that data mutations (INSERT/UPDATE) are rolled back but the schema change persists. Adjust the test accordingly.

If schema change persists in dry-run:

```python
def test_dry_run_rolls_back_data_changes_only(db):
    """ALTER TABLE is DDL and will persist in SQLite even under dry-run; data INSERT/UPDATE rolls back."""
    from scripts.migrate_parametry_ssot import migrate, already_applied
    _seed_minimal_catalog(db)
    db.execute("INSERT INTO mbr_templates (mbr_id, produkt, status) VALUES (1, 'Chelamid_DK', 'active')")
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, kontekst, produkt, min_limit, max_limit) "
        "VALUES (1, 'analiza_koncowa', 'Chelamid_DK', 0, 11)"
    )
    db.commit()

    migrate(db, dry_run=True)

    # Data inserts rolled back:
    assert db.execute("SELECT COUNT(*) AS n FROM produkt_pipeline WHERE produkt='Chelamid_DK'").fetchone()["n"] == 0
    assert db.execute("SELECT COUNT(*) AS n FROM produkt_etap_limity WHERE produkt='Chelamid_DK'").fetchone()["n"] == 0
    assert already_applied(db) is False
    # Schema change may or may not persist — don't assert on it.
```

Use whichever variant passes. If you had to change to the second variant, keep only that one.

- [ ] **Step 3: Commit**

```bash
git add tests/test_migrate_parametry_ssot.py
git commit -m "test: dry-run rolls back data changes"
```

---

## Task 15: Run migration on the real DB

**Files:**
- No code changes.

- [ ] **Step 1: Pre-flight: inspect current state**

Run:

```bash
sqlite3 data/batch_db.sqlite "SELECT COUNT(*) FROM parametry_etapy; SELECT COUNT(*) FROM produkt_etap_limity; SELECT COUNT(*) FROM parametry_cert;"
```

Record the counts as the "before" baseline.

- [ ] **Step 2: Run in dry-run first**

Run:

```bash
python -m scripts.migrate_parametry_ssot --dry-run
```

Expected output includes:
- `Backup: ...` skipped (dry-run)
- `Copied/verified N limit bindings.`
- `Migrated M cert metadata rows to parametry_cert.`
- `Dry run complete — rolled back.`

If `Pre-flight checks failed:` appears, stop and investigate before continuing.

- [ ] **Step 3: Run for real**

Run:

```bash
python -m scripts.migrate_parametry_ssot
```

Expected output:
- `Backup: data/batch_db.sqlite.bak-pre-parametry-ssot`
- Same summary lines as dry-run
- `Migration parametry_ssot_v1 committed.`

- [ ] **Step 4: Verify with postflight**

Run:

```bash
python -m scripts.migrate_parametry_ssot --verify-only
```

Expected: `Verification OK.`

- [ ] **Step 5: Spot-check Chelamid_DK manually**

Run:

```bash
sqlite3 data/batch_db.sqlite "SELECT pa.kod, pel.min_limit, pel.max_limit, pel.precision, pel.nawazka_g, pel.dla_szarzy, pel.dla_zbiornika FROM produkt_etap_limity pel JOIN parametry_analityczne pa ON pa.id=pel.parametr_id WHERE pel.produkt='Chelamid_DK' ORDER BY pel.kolejnosc, pa.kod;"
```

Expected: same 7 kodу as pre-migration state documented earlier (barwa_I2, cert_qual_cert_qual_form, cert_qual_glicerol, dietanolamina, gliceryny, ph, ph_10proc), all with `dla_szarzy=1 dla_zbiornika=1`.

- [ ] **Step 6: Smoke-test the application**

Start the dev server:

```bash
python -m mbr.app
```

Log in, open an existing Chelamid_DK batch or any other product's batch. Verify:
- Parameter list in the batch card is identical to before migration
- Saving a value works (no 500 errors)
- The parameter editor modal (`edytuj parametry`) opens and shows the same param list

If anything is off — stop, investigate, and restore from backup if needed:

```bash
cp data/batch_db.sqlite.bak-pre-parametry-ssot data/batch_db.sqlite
```

- [ ] **Step 7: No commit**

This task is operational — no code changes. If you made ad-hoc fixes during smoke-testing, commit each one with a clear message.

---

## Task 16: Final check — everything green

**Files:**
- No code changes.

- [ ] **Step 1: Run full test suite**

Run: `pytest`
Expected: all tests PASS (including existing ones — the schema change is additive so nothing should break).

- [ ] **Step 2: Update MEMORY.md for future sessions**

This refactor is a big one. Record it so future sessions know the state. Create or update the memory file via the auto memory system — record: "Parametry SSOT migration PR 1 completed 2026-04-16. Schema extended with typ flags and kolejnosc in produkt_etap_limity; cert metadata copied to parametry_cert. Legacy tables (parametry_etapy, etap_parametry) still present — to be dropped in PR 6 after code refactor."

- [ ] **Step 3: Open PR**

```bash
git log --oneline main..HEAD
```

Review the commit list. Push the branch and open a PR titled:

> `refactor: parametry SSOT — PR 1 (Etap A) — data migration`

PR description should include a summary of what's migrated, what's NOT changed (code still reads legacy), and link to the spec.

---

## Self-review checklist (done as part of writing this plan)

- Spec coverage: Every point in section "Migracja danych" of the spec has a corresponding task (backup → Task 2; preflight → 4,5; ALTER → 6; pipeline creation → 7; limits → 8; sa_bias → 9; cert → 10; postflight → 11; marker → 2/3; drop → deferred to PR 6 as spec mandates).
- No placeholders: each step has exact code or exact command.
- Type consistency: `_kontekst_to_etap_id` used consistently; flag columns named identically across tasks; `MIGRATION_NAME` constant referenced consistently.
- Bite-sized: each task is 1-6 steps of 2-5 minutes.

## Execution notes

- If Task 15's smoke test reveals an issue, **do not proceed to PR 2**. Migration must be rock-solid before code changes depend on the new shape.
- The `_migrations` marker table is defined in this migration and will be reused by future migration scripts. Don't drop it.
- `parametry_etapy` and `etap_parametry` remain fully populated after this PR — application code still reads them. Nothing to fear.
