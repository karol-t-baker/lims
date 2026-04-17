# MVP Pipeline Cleanup — PR 1 (Data cleanup) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One-shot data migration that strips multi-stage pipeline entries from all products except Chegina_K7, sets K7's typ flags correctly, and removes the artificial `dodatki` stage. Zero runtime code changes — old constants and code paths still work.

**Architecture:** Idempotent Python script `scripts/mvp_pipeline_cleanup.py` with `--dry-run`/`--verify-only`, backup, single-transaction atomicity, `_migrations` marker. Operates on 3 tables: `produkt_pipeline`, `produkt_etapy`, `produkt_etap_limity`. Whitelist of multi-stage products hardcoded in script: `{"Chegina_K7"}`.

**Tech Stack:** Python 3 stdlib, SQLite 3.45.3, pytest with in-memory fixtures (established pattern from `tests/test_migrate_parametry_ssot.py`).

**Dependencies:** PR 1–6 of parametry SSOT refactor already merged. This is an independent data-only migration.

---

## File Structure

**Create:**
- `scripts/mvp_pipeline_cleanup.py` — migration script
- `tests/test_mvp_pipeline_cleanup.py` — unit + integration tests

**Modify:**
- None (this PR is data-only)

**Not touched in this PR:**
- `mbr/etapy/models.py` `FULL_PIPELINE_PRODUCTS` — left alone (PR 3 removes)
- `mbr/pipeline/adapter.py` — filter enhancement in PR 2
- `mbr/parametry/registry.py::build_parametry_lab` — refactor in PR 3

---

## Spec reference

Full design: `docs/superpowers/specs/2026-04-16-mvp-pipeline-cleanup-design.md`. This PR implements the "Data cleanup" section end-to-end.

---

## Task 1: Scaffold test file

**Files:**
- Create: `tests/test_mvp_pipeline_cleanup.py`

- [ ] **Step 1: Create test file with fixture + seed helper**

```python
"""Tests for scripts/mvp_pipeline_cleanup.py — MVP narrowing of multi-stage
pipeline to Chegina_K7 only, plus K7 typ-flag fixup."""

import sqlite3
import pytest

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed_full_pipeline_state(db):
    """Seed DB state as it looks AFTER PR 1-6 of parametry SSOT refactor:
    Chegina_K7 has 5 analytical etapy + 5 process etapy, Chegina_K40GL has
    5 analytical + 5 process, Chelamid_DK has 1 analytical + 0 process.
    All typ flags default 1/1/0."""
    db.execute("DELETE FROM parametry_analityczne")
    db.executemany(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, precision, aktywny) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        [
            (1, "ph_10proc", "pH 10%", "bezposredni", 2),
            (2, "nd20", "nD20", "bezposredni", 4),
            (3, "sm", "Sucha masa", "bezposredni", 2),
            (4, "sa", "SA", "titracja", 2),
            (5, "so3", "SO3", "titracja", 2),
            (6, "nacl", "NaCl", "titracja", 2),
            (7, "barwa_I2", "Barwa I2", "bezposredni", 0),
            (8, "kwas_ca", "Kwas cytrynowy [kg]", "bezposredni", 1),
        ],
    )
    db.executemany(
        "INSERT OR IGNORE INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (?, ?, ?, ?)",
        [
            (1, "amidowanie", "Amidowanie", "cykliczny"),
            (3, "namca", "NAMCA", "cykliczny"),
            (2, "czwartorzedowanie", "Czwartorzedowanie", "cykliczny"),
            (4, "sulfonowanie", "Sulfonowanie", "cykliczny"),
            (5, "utlenienie", "Utlenienie", "cykliczny"),
            (6, "analiza_koncowa", "Analiza koncowa", "jednorazowy"),
            (7, "dodatki", "Dodatki standaryzacyjne", "cykliczny"),
            (9, "standaryzacja", "Standaryzacja", "cykliczny"),
        ],
    )
    db.execute(
        "INSERT OR IGNORE INTO etapy_procesowe (kod, nazwa, opis, aktywny) VALUES (?, ?, ?, 1)",
        ("amidowanie", "Amidowanie", None),
    )
    for kod in ("namca", "czwartorzedowanie", "sulfonowanie", "utlenienie", "standaryzacja"):
        db.execute(
            "INSERT OR IGNORE INTO etapy_procesowe (kod, nazwa, opis, aktywny) VALUES (?, ?, ?, 1)",
            (kod, kod.capitalize(), None),
        )

    # ---- Chegina_K7: 5 analytical etapy + 5 process etapy ----
    k7_pipeline = [
        (4, 1),   # sulfonowanie, kolejnosc 1
        (5, 2),   # utlenienie
        (9, 3),   # standaryzacja
        (6, 4),   # analiza_koncowa
        (7, 5),   # dodatki
    ]
    for etap_id, kol in k7_pipeline:
        db.execute(
            "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chegina_K7', ?, ?)",
            (etap_id, kol),
        )
    k7_process = ["amidowanie", "namca", "czwartorzedowanie", "sulfonowanie", "utlenienie"]
    for i, kod in enumerate(k7_process, 1):
        db.execute(
            "INSERT INTO produkt_etapy (produkt, etap_kod, kolejnosc) VALUES ('Chegina_K7', ?, ?)",
            (kod, i),
        )
    # Sulfonowanie (4): 2 params, utlenienie (5): 2, standaryzacja (9): 2, analiza_koncowa (6): 3, dodatki (7): 1
    k7_params = [
        (4, 5),  # sulfonowanie, so3
        (4, 1),  # sulfonowanie, ph_10proc
        (5, 5),  # utlenienie, so3
        (5, 6),  # utlenienie, nacl
        (9, 2),  # standaryzacja, nd20
        (9, 6),  # standaryzacja, nacl
        (6, 1),  # analiza_koncowa, ph_10proc
        (6, 3),  # analiza_koncowa, sm
        (6, 7),  # analiza_koncowa, barwa_I2
        (7, 8),  # dodatki, kwas_ca
    ]
    for etap_id, parametr_id in k7_params:
        db.execute(
            "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, "
            "dla_szarzy, dla_zbiornika, dla_platkowania) VALUES ('Chegina_K7', ?, ?, 1, 1, 0)",
            (etap_id, parametr_id),
        )

    # ---- Chegina_K40GL: 5 analytical + 5 process (needs to be stripped) ----
    k40gl_pipeline = [(4, 1), (5, 2), (9, 3), (6, 4), (7, 5)]
    for etap_id, kol in k40gl_pipeline:
        db.execute(
            "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chegina_K40GL', ?, ?)",
            (etap_id, kol),
        )
    for i, kod in enumerate(k7_process, 1):
        db.execute(
            "INSERT INTO produkt_etapy (produkt, etap_kod, kolejnosc) VALUES ('Chegina_K40GL', ?, ?)",
            (kod, i),
        )
    for etap_id, parametr_id in k7_params:
        db.execute(
            "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, "
            "dla_szarzy, dla_zbiornika, dla_platkowania) VALUES ('Chegina_K40GL', ?, ?, 1, 1, 0)",
            (etap_id, parametr_id),
        )

    # ---- Chelamid_DK: 1 analytical (analiza_koncowa) ----
    db.execute(
        "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chelamid_DK', 6, 1)"
    )
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, "
        "dla_szarzy, dla_zbiornika, dla_platkowania) VALUES ('Chelamid_DK', 6, 1, 1, 1, 0)"
    )

    # Active MBR templates for postflight
    for produkt in ("Chegina_K7", "Chegina_K40GL", "Chelamid_DK"):
        db.execute(
            "INSERT INTO mbr_templates (mbr_id, produkt, status) "
            "VALUES (NULL, ?, 'active')",
            (produkt,),
        )

    db.commit()
```

- [ ] **Step 2: Verify collection**

Run: `pytest tests/test_mvp_pipeline_cleanup.py --collect-only`
Expected: `no tests ran` with no import errors.

- [ ] **Step 3: Commit**

```bash
git add tests/test_mvp_pipeline_cleanup.py
git commit -m "test: scaffold MVP pipeline cleanup test file"
```

---

## Task 2: Script skeleton with CLI + backup + marker

**Files:**
- Create: `scripts/mvp_pipeline_cleanup.py`
- Modify: `tests/test_mvp_pipeline_cleanup.py`

- [ ] **Step 1: Write importability test**

Append to `tests/test_mvp_pipeline_cleanup.py`:

```python
def test_script_importable():
    from scripts import mvp_pipeline_cleanup as mod
    assert callable(mod.migrate)
    assert callable(mod.main)
    assert callable(mod.backup)
    assert callable(mod.already_applied)
    assert mod.MIGRATION_NAME == "mvp_pipeline_cleanup_v1"
    assert mod.MVP_MULTI_STAGE == {"Chegina_K7"}
```

- [ ] **Step 2: Run, expect fail**

Run: `pytest tests/test_mvp_pipeline_cleanup.py::test_script_importable -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.mvp_pipeline_cleanup'`.

- [ ] **Step 3: Create the script**

Create `scripts/mvp_pipeline_cleanup.py`:

```python
"""MVP pipeline cleanup — narrow multi-stage pipeline to Chegina_K7 only,
strip dodatki stage from K7, set K7 typ flags per spec.

See docs/superpowers/specs/2026-04-16-mvp-pipeline-cleanup-design.md

Usage:
    python -m scripts.mvp_pipeline_cleanup [--db PATH] [--dry-run] [--verify-only] [--force]
"""

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


MIGRATION_NAME = "mvp_pipeline_cleanup_v1"
MVP_MULTI_STAGE = {"Chegina_K7"}


def backup(db_path: str) -> str:
    src = Path(db_path)
    if not src.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")
    dst = src.with_suffix(src.suffix + ".bak-pre-mvp-cleanup")
    shutil.copy2(src, dst)
    return str(dst)


def already_applied(db: sqlite3.Connection) -> bool:
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


def migrate(db: sqlite3.Connection, dry_run: bool = False) -> None:
    if already_applied(db):
        print(f"Migration {MIGRATION_NAME} already applied — skipping.")
        return

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


def postflight(db: sqlite3.Connection) -> list[str]:
    """Return list of post-migration validation errors. Empty list = OK."""
    return []  # filled in later tasks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/batch_db.sqlite")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--force", action="store_true")
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

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_mvp_pipeline_cleanup.py -v`
Expected: `test_script_importable` passes.

- [ ] **Step 5: Commit**

```bash
git add scripts/mvp_pipeline_cleanup.py tests/test_mvp_pipeline_cleanup.py
git commit -m "feat(cleanup): MVP pipeline cleanup script skeleton with CLI"
```

---

## Task 3: Idempotence guard

**Files:**
- Modify: `tests/test_mvp_pipeline_cleanup.py`

- [ ] **Step 1: Append tests**

```python
from scripts.mvp_pipeline_cleanup import migrate, already_applied


def test_migrate_marks_as_applied(db):
    _seed_full_pipeline_state(db)
    migrate(db)
    assert already_applied(db) is True


def test_migrate_skips_when_already_applied(db, capsys):
    _seed_full_pipeline_state(db)
    migrate(db)
    migrate(db)
    captured = capsys.readouterr()
    assert "already applied — skipping" in captured.out
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_mvp_pipeline_cleanup.py -v`
Expected: 3 tests pass (skeleton migrate() marks done even without any cleanup steps).

- [ ] **Step 3: Commit**

```bash
git add tests/test_mvp_pipeline_cleanup.py
git commit -m "test: idempotence guard for MVP pipeline cleanup"
```

---

## Task 4: Strip non-K7 produkt_pipeline + produkt_etapy

**Files:**
- Modify: `scripts/mvp_pipeline_cleanup.py` (add `strip_non_k7_pipeline` function)
- Modify: `tests/test_mvp_pipeline_cleanup.py`

- [ ] **Step 1: Write failing tests**

```python
def test_strip_removes_k40gl_multi_stage(db):
    from scripts.mvp_pipeline_cleanup import strip_non_k7_pipeline
    _seed_full_pipeline_state(db)
    strip_non_k7_pipeline(db)
    rows = db.execute(
        "SELECT etap_id FROM produkt_pipeline WHERE produkt='Chegina_K40GL' ORDER BY kolejnosc"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["etap_id"] == 6  # only analiza_koncowa


def test_strip_removes_k40gl_process_stages(db):
    from scripts.mvp_pipeline_cleanup import strip_non_k7_pipeline
    _seed_full_pipeline_state(db)
    strip_non_k7_pipeline(db)
    n = db.execute(
        "SELECT COUNT(*) AS n FROM produkt_etapy WHERE produkt='Chegina_K40GL'"
    ).fetchone()["n"]
    assert n == 0


def test_strip_preserves_chegina_k7(db):
    from scripts.mvp_pipeline_cleanup import strip_non_k7_pipeline
    _seed_full_pipeline_state(db)
    strip_non_k7_pipeline(db)
    n_pipeline = db.execute(
        "SELECT COUNT(*) AS n FROM produkt_pipeline WHERE produkt='Chegina_K7'"
    ).fetchone()["n"]
    n_process = db.execute(
        "SELECT COUNT(*) AS n FROM produkt_etapy WHERE produkt='Chegina_K7'"
    ).fetchone()["n"]
    assert n_pipeline == 5
    assert n_process == 5


def test_strip_preserves_already_simple_products(db):
    from scripts.mvp_pipeline_cleanup import strip_non_k7_pipeline
    _seed_full_pipeline_state(db)
    strip_non_k7_pipeline(db)
    rows = db.execute(
        "SELECT etap_id FROM produkt_pipeline WHERE produkt='Chelamid_DK'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["etap_id"] == 6


def test_strip_inserts_analiza_koncowa_if_missing(db):
    """Edge case: a product with multi-stage pipeline but no analiza_koncowa row
    should have analiza_koncowa inserted when its multi-stage entries are stripped."""
    from scripts.mvp_pipeline_cleanup import strip_non_k7_pipeline
    _seed_full_pipeline_state(db)
    # Remove K40GL's analiza_koncowa specifically
    db.execute("DELETE FROM produkt_pipeline WHERE produkt='Chegina_K40GL' AND etap_id=6")
    db.commit()
    strip_non_k7_pipeline(db)
    rows = db.execute(
        "SELECT etap_id FROM produkt_pipeline WHERE produkt='Chegina_K40GL'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["etap_id"] == 6
```

- [ ] **Step 2: Run tests, expect fail**

Run: `pytest tests/test_mvp_pipeline_cleanup.py::test_strip_removes_k40gl_multi_stage -v`
Expected: FAIL — `strip_non_k7_pipeline` not defined.

- [ ] **Step 3: Add constants and function to script**

In `scripts/mvp_pipeline_cleanup.py`, add the following BEFORE the `migrate()` function:

```python
# etap_id for analiza_koncowa, resolved at runtime to stay robust against
# environments where etapy_analityczne ids differ.
def _analiza_koncowa_etap_id(db: sqlite3.Connection) -> int:
    row = db.execute(
        "SELECT id FROM etapy_analityczne WHERE kod='analiza_koncowa'"
    ).fetchone()
    if not row:
        raise RuntimeError("etapy_analityczne has no 'analiza_koncowa' row")
    return row["id"]


def strip_non_k7_pipeline(db: sqlite3.Connection) -> dict:
    """For every product not in MVP_MULTI_STAGE: remove all produkt_pipeline
    entries except analiza_koncowa; remove all produkt_etapy entries.

    Returns counts: {'pipeline_deleted': N, 'pipeline_inserted': N, 'etapy_deleted': N}.
    """
    ak_id = _analiza_koncowa_etap_id(db)
    counts = {"pipeline_deleted": 0, "pipeline_inserted": 0, "etapy_deleted": 0}

    # All products with pipeline entries, outside the whitelist.
    produkty = db.execute(
        "SELECT DISTINCT produkt FROM produkt_pipeline"
    ).fetchall()
    for row in produkty:
        produkt = row["produkt"]
        if produkt in MVP_MULTI_STAGE:
            continue
        # Delete non-analiza_koncowa pipeline rows
        cur = db.execute(
            "DELETE FROM produkt_pipeline WHERE produkt=? AND etap_id != ?",
            (produkt, ak_id),
        )
        counts["pipeline_deleted"] += cur.rowcount
        # Ensure analiza_koncowa row exists
        exists = db.execute(
            "SELECT 1 FROM produkt_pipeline WHERE produkt=? AND etap_id=?",
            (produkt, ak_id),
        ).fetchone()
        if not exists:
            db.execute(
                "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES (?, ?, 1)",
                (produkt, ak_id),
            )
            counts["pipeline_inserted"] += 1

    # Delete ALL produkt_etapy for non-K7 products (process workflow)
    produkty = db.execute(
        "SELECT DISTINCT produkt FROM produkt_etapy"
    ).fetchall()
    for row in produkty:
        produkt = row["produkt"]
        if produkt in MVP_MULTI_STAGE:
            continue
        cur = db.execute("DELETE FROM produkt_etapy WHERE produkt=?", (produkt,))
        counts["etapy_deleted"] += cur.rowcount

    return counts
```

- [ ] **Step 4: Wire into `migrate()`**

Replace the comment `# Migration steps filled in by later tasks.` with:

```python
    counts1 = strip_non_k7_pipeline(db)
    if any(counts1.values()):
        print(
            f"Stripped non-K7 pipeline: deleted {counts1['pipeline_deleted']} pipeline rows, "
            f"inserted {counts1['pipeline_inserted']} analiza_koncowa rows, "
            f"deleted {counts1['etapy_deleted']} produkt_etapy rows."
        )
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_mvp_pipeline_cleanup.py -v`
Expected: all 8 tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/mvp_pipeline_cleanup.py tests/test_mvp_pipeline_cleanup.py
git commit -m "feat(cleanup): strip non-K7 multi-stage pipeline + process etapy"
```

---

## Task 5: Strip dodatki stage from K7 + fix K7 typ flags

**Files:**
- Modify: `scripts/mvp_pipeline_cleanup.py` (add `fixup_chegina_k7` function)
- Modify: `tests/test_mvp_pipeline_cleanup.py`

- [ ] **Step 1: Write failing tests**

```python
def test_fixup_k7_removes_dodatki_stage(db):
    from scripts.mvp_pipeline_cleanup import fixup_chegina_k7
    _seed_full_pipeline_state(db)
    fixup_chegina_k7(db)
    kody = [r["kod"] for r in db.execute(
        "SELECT ea.kod FROM produkt_pipeline pp "
        "JOIN etapy_analityczne ea ON pp.etap_id=ea.id "
        "WHERE pp.produkt='Chegina_K7' ORDER BY pp.kolejnosc"
    ).fetchall()]
    assert "dodatki" not in kody
    assert kody == ["sulfonowanie", "utlenienie", "standaryzacja", "analiza_koncowa"]


def test_fixup_k7_removes_dodatki_params(db):
    from scripts.mvp_pipeline_cleanup import fixup_chegina_k7
    _seed_full_pipeline_state(db)
    fixup_chegina_k7(db)
    n = db.execute(
        "SELECT COUNT(*) AS n FROM produkt_etap_limity WHERE produkt='Chegina_K7' AND etap_id=7"
    ).fetchone()["n"]
    assert n == 0


def test_fixup_k7_sets_szarza_flags_on_process_stages(db):
    """sulfonowanie/utlenienie/standaryzacja params → dla_szarzy=1, dla_zbiornika=0."""
    from scripts.mvp_pipeline_cleanup import fixup_chegina_k7
    _seed_full_pipeline_state(db)
    fixup_chegina_k7(db)
    rows = db.execute(
        "SELECT pel.dla_szarzy, pel.dla_zbiornika FROM produkt_etap_limity pel "
        "WHERE pel.produkt='Chegina_K7' AND pel.etap_id IN (4, 5, 9)"
    ).fetchall()
    assert len(rows) > 0
    for r in rows:
        assert r["dla_szarzy"] == 1
        assert r["dla_zbiornika"] == 0


def test_fixup_k7_sets_zbiornik_flags_on_analiza_koncowa(db):
    """analiza_koncowa params → dla_szarzy=0, dla_zbiornika=1."""
    from scripts.mvp_pipeline_cleanup import fixup_chegina_k7
    _seed_full_pipeline_state(db)
    fixup_chegina_k7(db)
    rows = db.execute(
        "SELECT dla_szarzy, dla_zbiornika FROM produkt_etap_limity "
        "WHERE produkt='Chegina_K7' AND etap_id=6"
    ).fetchall()
    assert len(rows) > 0
    for r in rows:
        assert r["dla_szarzy"] == 0
        assert r["dla_zbiornika"] == 1


def test_fixup_k7_trims_process_etapy(db):
    """produkt_etapy for K7: keep sulfonowanie, utlenienie, add standaryzacja;
    drop amidowanie, namca, czwartorzedowanie."""
    from scripts.mvp_pipeline_cleanup import fixup_chegina_k7
    _seed_full_pipeline_state(db)
    fixup_chegina_k7(db)
    kody = {r["etap_kod"] for r in db.execute(
        "SELECT etap_kod FROM produkt_etapy WHERE produkt='Chegina_K7'"
    ).fetchall()}
    assert kody == {"sulfonowanie", "utlenienie", "standaryzacja"}
```

- [ ] **Step 2: Run tests, expect fail**

Run: `pytest tests/test_mvp_pipeline_cleanup.py -k fixup -v`
Expected: 5 tests fail — `fixup_chegina_k7` not defined.

- [ ] **Step 3: Implement fixup_chegina_k7**

Add to `scripts/mvp_pipeline_cleanup.py`:

```python
# Etap kody handled by K7 fixup
_K7_SZARZA_STAGES = ("sulfonowanie", "utlenienie", "standaryzacja")
_K7_DROP_PROCESS_KODY = ("amidowanie", "namca", "czwartorzedowanie")


def _etap_ids_by_kod(db: sqlite3.Connection, kody) -> dict:
    rows = db.execute(
        f"SELECT id, kod FROM etapy_analityczne WHERE kod IN ({','.join('?' * len(kody))})",
        tuple(kody),
    ).fetchall()
    return {r["kod"]: r["id"] for r in rows}


def fixup_chegina_k7(db: sqlite3.Connection) -> dict:
    """Apply K7-specific normalisation:
      - drop dodatki stage (from produkt_pipeline + produkt_etap_limity)
      - set dla_szarzy=1 dla_zbiornika=0 on sulfonowanie/utlenienie/standaryzacja params
      - set dla_szarzy=0 dla_zbiornika=1 on analiza_koncowa params
      - trim produkt_etapy to {sulfonowanie, utlenienie, standaryzacja}
    """
    counts = {
        "pipeline_dodatki_dropped": 0,
        "limity_dodatki_dropped": 0,
        "szarza_params_set": 0,
        "zbiornik_params_set": 0,
        "process_etapy_deleted": 0,
        "process_etapy_inserted": 0,
    }
    etap_ids = _etap_ids_by_kod(db, ["dodatki", "analiza_koncowa",
                                     "sulfonowanie", "utlenienie", "standaryzacja"])
    dodatki_id = etap_ids.get("dodatki")
    ak_id = etap_ids["analiza_koncowa"]
    szarza_ids = [etap_ids["sulfonowanie"], etap_ids["utlenienie"], etap_ids["standaryzacja"]]

    # 1. Drop dodatki from produkt_pipeline for K7
    if dodatki_id is not None:
        cur = db.execute(
            "DELETE FROM produkt_pipeline WHERE produkt='Chegina_K7' AND etap_id=?",
            (dodatki_id,),
        )
        counts["pipeline_dodatki_dropped"] = cur.rowcount
        # Drop dodatki params from produkt_etap_limity for K7
        cur = db.execute(
            "DELETE FROM produkt_etap_limity WHERE produkt='Chegina_K7' AND etap_id=?",
            (dodatki_id,),
        )
        counts["limity_dodatki_dropped"] = cur.rowcount

    # 2. Set szarza flags on process-stage params
    placeholders = ",".join("?" * len(szarza_ids))
    cur = db.execute(
        f"UPDATE produkt_etap_limity SET dla_szarzy=1, dla_zbiornika=0 "
        f"WHERE produkt='Chegina_K7' AND etap_id IN ({placeholders})",
        szarza_ids,
    )
    counts["szarza_params_set"] = cur.rowcount

    # 3. Set zbiornik flags on analiza_koncowa params
    cur = db.execute(
        "UPDATE produkt_etap_limity SET dla_szarzy=0, dla_zbiornika=1 "
        "WHERE produkt='Chegina_K7' AND etap_id=?",
        (ak_id,),
    )
    counts["zbiornik_params_set"] = cur.rowcount

    # 4. Trim produkt_etapy
    if _K7_DROP_PROCESS_KODY:
        placeholders = ",".join("?" * len(_K7_DROP_PROCESS_KODY))
        cur = db.execute(
            f"DELETE FROM produkt_etapy WHERE produkt='Chegina_K7' "
            f"AND etap_kod IN ({placeholders})",
            _K7_DROP_PROCESS_KODY,
        )
        counts["process_etapy_deleted"] = cur.rowcount
    # Ensure standaryzacja in produkt_etapy (idempotent)
    exists = db.execute(
        "SELECT 1 FROM produkt_etapy WHERE produkt='Chegina_K7' AND etap_kod='standaryzacja'"
    ).fetchone()
    if not exists:
        max_kol = db.execute(
            "SELECT COALESCE(MAX(kolejnosc), 0) AS k FROM produkt_etapy WHERE produkt='Chegina_K7'"
        ).fetchone()["k"]
        db.execute(
            "INSERT INTO produkt_etapy (produkt, etap_kod, kolejnosc) "
            "VALUES ('Chegina_K7', 'standaryzacja', ?)",
            (max_kol + 1,),
        )
        counts["process_etapy_inserted"] = 1

    return counts
```

- [ ] **Step 4: Wire into migrate()**

Add after `strip_non_k7_pipeline` call:

```python
    counts2 = fixup_chegina_k7(db)
    if any(counts2.values()):
        print(
            f"K7 fixup: dropped dodatki stage ({counts2['pipeline_dodatki_dropped']} pipeline, "
            f"{counts2['limity_dodatki_dropped']} limity), "
            f"set szarza flags on {counts2['szarza_params_set']} params, "
            f"zbiornik flags on {counts2['zbiornik_params_set']} params, "
            f"deleted {counts2['process_etapy_deleted']} process etapy, "
            f"inserted {counts2['process_etapy_inserted']} standaryzacja."
        )
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_mvp_pipeline_cleanup.py -v`
Expected: all 13 tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/mvp_pipeline_cleanup.py tests/test_mvp_pipeline_cleanup.py
git commit -m "feat(cleanup): drop dodatki stage + fix K7 typ flags"
```

---

## Task 6: Orphan cleanup — delete produkt_etap_limity rows without matching pipeline

**Files:**
- Modify: `scripts/mvp_pipeline_cleanup.py` (add `clean_orphan_limits` function)
- Modify: `tests/test_mvp_pipeline_cleanup.py`

- [ ] **Step 1: Write failing test**

```python
def test_orphan_cleanup_removes_stranded_limity(db):
    """After strip+fixup, K40GL has orphan produkt_etap_limity rows for etap_ids
    no longer in its pipeline. Those must be deleted."""
    from scripts.mvp_pipeline_cleanup import strip_non_k7_pipeline, fixup_chegina_k7, clean_orphan_limits
    _seed_full_pipeline_state(db)
    strip_non_k7_pipeline(db)
    fixup_chegina_k7(db)
    clean_orphan_limits(db)
    # K40GL should have produkt_etap_limity only for etap_id=6 (analiza_koncowa)
    rows = db.execute(
        "SELECT DISTINCT etap_id FROM produkt_etap_limity WHERE produkt='Chegina_K40GL'"
    ).fetchall()
    etap_ids = sorted(r["etap_id"] for r in rows)
    assert etap_ids == [6]


def test_orphan_cleanup_preserves_k7_limity(db):
    """K7 has pipeline for 4 etapy after fixup (dodatki dropped). Its limity
    for those 4 etapy must survive orphan cleanup."""
    from scripts.mvp_pipeline_cleanup import strip_non_k7_pipeline, fixup_chegina_k7, clean_orphan_limits
    _seed_full_pipeline_state(db)
    strip_non_k7_pipeline(db)
    fixup_chegina_k7(db)
    clean_orphan_limits(db)
    etap_ids = {r["etap_id"] for r in db.execute(
        "SELECT DISTINCT etap_id FROM produkt_etap_limity WHERE produkt='Chegina_K7'"
    ).fetchall()}
    assert etap_ids == {4, 5, 9, 6}  # sulfonowanie, utlenienie, standaryzacja, analiza_koncowa
```

- [ ] **Step 2: Run, expect fail**

Run: `pytest tests/test_mvp_pipeline_cleanup.py::test_orphan_cleanup_removes_stranded_limity -v`
Expected: FAIL — `clean_orphan_limits` not defined.

- [ ] **Step 3: Implement clean_orphan_limits**

Add to `scripts/mvp_pipeline_cleanup.py`:

```python
def clean_orphan_limits(db: sqlite3.Connection) -> int:
    """Delete produkt_etap_limity rows whose (produkt, etap_id) pair no longer
    exists in produkt_pipeline."""
    cur = db.execute("""
        DELETE FROM produkt_etap_limity
        WHERE (produkt, etap_id) NOT IN (
            SELECT produkt, etap_id FROM produkt_pipeline
        )
    """)
    return cur.rowcount
```

- [ ] **Step 4: Wire into migrate()**

Add after `fixup_chegina_k7` call:

```python
    n_orphans = clean_orphan_limits(db)
    if n_orphans:
        print(f"Deleted {n_orphans} orphan produkt_etap_limity rows.")
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_mvp_pipeline_cleanup.py -v`
Expected: all 15 tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/mvp_pipeline_cleanup.py tests/test_mvp_pipeline_cleanup.py
git commit -m "feat(cleanup): delete orphan produkt_etap_limity rows"
```

---

## Task 7: Postflight validation

**Files:**
- Modify: `scripts/mvp_pipeline_cleanup.py` (replace `postflight` stub)
- Modify: `tests/test_mvp_pipeline_cleanup.py`

- [ ] **Step 1: Write failing tests**

```python
def test_postflight_passes_after_full_cleanup(db):
    from scripts.mvp_pipeline_cleanup import migrate, postflight
    _seed_full_pipeline_state(db)
    migrate(db)
    assert postflight(db) == []


def test_postflight_detects_active_product_without_pipeline(db):
    """If an active MBR product has 0 produkt_pipeline rows, postflight fails."""
    from scripts.mvp_pipeline_cleanup import postflight
    _seed_full_pipeline_state(db)
    db.execute("DELETE FROM produkt_pipeline WHERE produkt='Chelamid_DK'")
    db.commit()
    errors = postflight(db)
    assert any("Chelamid_DK" in e and "no pipeline" in e.lower() for e in errors)


def test_postflight_detects_non_k7_with_multi_stage_leftover(db):
    """If any non-K7 product still has multi-stage pipeline, postflight fails."""
    from scripts.mvp_pipeline_cleanup import postflight
    _seed_full_pipeline_state(db)
    errors = postflight(db)
    # Pre-cleanup state — K40GL still has 5 pipeline rows
    assert any("Chegina_K40GL" in e and "multi-stage" in e.lower() for e in errors)


def test_postflight_detects_k7_with_dodatki(db):
    """K7 pipeline must not contain dodatki etap."""
    from scripts.mvp_pipeline_cleanup import strip_non_k7_pipeline, postflight
    _seed_full_pipeline_state(db)
    strip_non_k7_pipeline(db)  # dodatki still present for K7
    errors = postflight(db)
    assert any("Chegina_K7" in e and "dodatki" in e.lower() for e in errors)
```

- [ ] **Step 2: Run, expect fail**

Run: `pytest tests/test_mvp_pipeline_cleanup.py -k postflight -v`
Expected: 4 tests fail — postflight currently returns `[]`.

- [ ] **Step 3: Implement postflight**

Replace the `postflight` stub:

```python
def postflight(db: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    ak_id = _analiza_koncowa_etap_id(db)

    # 1. Every active MBR product has at least one produkt_pipeline row
    rows = db.execute("""
        SELECT mt.produkt
        FROM mbr_templates mt
        WHERE mt.status = 'active'
          AND NOT EXISTS (
            SELECT 1 FROM produkt_pipeline pp WHERE pp.produkt = mt.produkt
          )
    """).fetchall()
    for r in rows:
        errors.append(f"Active product '{r['produkt']}' has no pipeline entries.")

    # 2. No non-K7 product has multi-stage pipeline
    rows = db.execute("""
        SELECT produkt, COUNT(*) AS n
        FROM produkt_pipeline
        GROUP BY produkt
        HAVING n > 1
    """).fetchall()
    for r in rows:
        if r["produkt"] not in MVP_MULTI_STAGE:
            errors.append(
                f"Product '{r['produkt']}' still has multi-stage pipeline ({r['n']} rows); "
                "expected 1 (analiza_koncowa) after cleanup."
            )

    # 3. K7 pipeline must not contain dodatki
    dodatki_row = db.execute(
        "SELECT id FROM etapy_analityczne WHERE kod='dodatki'"
    ).fetchone()
    if dodatki_row:
        row = db.execute(
            "SELECT 1 FROM produkt_pipeline WHERE produkt='Chegina_K7' AND etap_id=?",
            (dodatki_row["id"],),
        ).fetchone()
        if row:
            errors.append("Chegina_K7 pipeline still contains 'dodatki' etap.")

    return errors
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_mvp_pipeline_cleanup.py -v`
Expected: all 19 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/mvp_pipeline_cleanup.py tests/test_mvp_pipeline_cleanup.py
git commit -m "feat(cleanup): postflight — no orphan products, K7 has no dodatki, no multi-stage leakage"
```

---

## Task 8: End-to-end integration test

**Files:**
- Modify: `tests/test_mvp_pipeline_cleanup.py`

- [ ] **Step 1: Append the integration test**

```python
def test_full_migrate_cleans_state_correctly(db):
    """One-shot migrate() call moves seeded state to target MVP shape."""
    from scripts.mvp_pipeline_cleanup import migrate, already_applied

    _seed_full_pipeline_state(db)

    # Pre-migration sanity
    assert db.execute(
        "SELECT COUNT(*) AS n FROM produkt_pipeline WHERE produkt='Chegina_K40GL'"
    ).fetchone()["n"] == 5

    migrate(db)

    # K7: 4 pipeline rows (sulfon, utlen, standard, analiza_koncowa), no dodatki
    k7_kody = [r["kod"] for r in db.execute(
        "SELECT ea.kod FROM produkt_pipeline pp JOIN etapy_analityczne ea ON pp.etap_id=ea.id "
        "WHERE pp.produkt='Chegina_K7' ORDER BY pp.kolejnosc"
    ).fetchall()]
    assert k7_kody == ["sulfonowanie", "utlenienie", "standaryzacja", "analiza_koncowa"]

    # K7 process workflow: 3 stages
    k7_proc = {r["etap_kod"] for r in db.execute(
        "SELECT etap_kod FROM produkt_etapy WHERE produkt='Chegina_K7'"
    ).fetchall()}
    assert k7_proc == {"sulfonowanie", "utlenienie", "standaryzacja"}

    # K40GL: 1 pipeline row (analiza_koncowa), no process etapy
    k40gl = db.execute(
        "SELECT etap_id FROM produkt_pipeline WHERE produkt='Chegina_K40GL'"
    ).fetchall()
    assert len(k40gl) == 1
    assert k40gl[0]["etap_id"] == 6
    assert db.execute(
        "SELECT COUNT(*) AS n FROM produkt_etapy WHERE produkt='Chegina_K40GL'"
    ).fetchone()["n"] == 0

    # K7 typ flags: szarza stages vs analiza_koncowa
    szarza_rows = db.execute(
        "SELECT dla_szarzy, dla_zbiornika FROM produkt_etap_limity "
        "WHERE produkt='Chegina_K7' AND etap_id IN (4, 5, 9)"
    ).fetchall()
    assert all(r["dla_szarzy"] == 1 and r["dla_zbiornika"] == 0 for r in szarza_rows)
    zbiornik_rows = db.execute(
        "SELECT dla_szarzy, dla_zbiornika FROM produkt_etap_limity "
        "WHERE produkt='Chegina_K7' AND etap_id=6"
    ).fetchall()
    assert all(r["dla_szarzy"] == 0 and r["dla_zbiornika"] == 1 for r in zbiornik_rows)

    # No orphan limits
    orphans = db.execute("""
        SELECT COUNT(*) AS n FROM produkt_etap_limity pel
        WHERE (pel.produkt, pel.etap_id) NOT IN (SELECT produkt, etap_id FROM produkt_pipeline)
    """).fetchone()["n"]
    assert orphans == 0

    # Marker set
    assert already_applied(db) is True
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_mvp_pipeline_cleanup.py -v`
Expected: all 20 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_mvp_pipeline_cleanup.py
git commit -m "test: full migrate() end-to-end integration test"
```

---

## Task 9: Dry-run rollback test

**Files:**
- Modify: `tests/test_mvp_pipeline_cleanup.py`

- [ ] **Step 1: Append test**

```python
def test_dry_run_rolls_back_data_changes(db):
    from scripts.mvp_pipeline_cleanup import migrate, already_applied
    _seed_full_pipeline_state(db)

    migrate(db, dry_run=True)

    # K40GL still has 5 pipeline rows, K7 still has dodatki
    assert db.execute(
        "SELECT COUNT(*) AS n FROM produkt_pipeline WHERE produkt='Chegina_K40GL'"
    ).fetchone()["n"] == 5
    assert db.execute(
        "SELECT COUNT(*) AS n FROM produkt_pipeline pp "
        "JOIN etapy_analityczne ea ON pp.etap_id=ea.id "
        "WHERE pp.produkt='Chegina_K7' AND ea.kod='dodatki'"
    ).fetchone()["n"] == 1
    # Marker NOT set
    assert already_applied(db) is False
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_mvp_pipeline_cleanup.py::test_dry_run_rolls_back_data_changes -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_mvp_pipeline_cleanup.py
git commit -m "test: dry-run rolls back data changes"
```

---

## Task 10: Real-DB smoke test (skip if DB absent)

**Files:**
- Create: `tests/test_mvp_pipeline_cleanup_realdb.py`

- [ ] **Step 1: Create the test file**

```python
"""Real-DB integration test: run MVP cleanup on a copy of data/batch_db.sqlite
and assert key invariants. Skips cleanly when DB file is missing."""

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


def test_migrate_on_real_db_produces_k7_3_szarza_stages(real_db_copy):
    from scripts.mvp_pipeline_cleanup import migrate

    migrate(real_db_copy)

    # K7 pipeline: 4 rows (sulfon, utlen, standard, analiza_koncowa)
    rows = real_db_copy.execute(
        "SELECT ea.kod FROM produkt_pipeline pp "
        "JOIN etapy_analityczne ea ON pp.etap_id=ea.id "
        "WHERE pp.produkt='Chegina_K7' ORDER BY pp.kolejnosc"
    ).fetchall()
    kody = [r["kod"] for r in rows]
    assert kody == ["sulfonowanie", "utlenienie", "standaryzacja", "analiza_koncowa"]


def test_migrate_on_real_db_reduces_non_k7_to_single_stage(real_db_copy):
    from scripts.mvp_pipeline_cleanup import migrate

    migrate(real_db_copy)

    # Every non-K7 product with pipeline has exactly 1 row (analiza_koncowa)
    rows = real_db_copy.execute(
        "SELECT produkt, COUNT(*) AS n FROM produkt_pipeline "
        "WHERE produkt != 'Chegina_K7' GROUP BY produkt HAVING n > 1"
    ).fetchall()
    assert len(rows) == 0, (
        f"Non-K7 products still have multi-stage: "
        f"{[(r['produkt'], r['n']) for r in rows]}"
    )


def test_migrate_on_real_db_is_idempotent(real_db_copy):
    from scripts.mvp_pipeline_cleanup import migrate

    migrate(real_db_copy)
    # Counts after first run
    before = real_db_copy.execute(
        "SELECT COUNT(*) AS n FROM produkt_pipeline"
    ).fetchone()["n"]

    migrate(real_db_copy)  # second call — should short-circuit
    after = real_db_copy.execute(
        "SELECT COUNT(*) AS n FROM produkt_pipeline"
    ).fetchone()["n"]
    assert after == before
```

- [ ] **Step 2: Run**

Run: `pytest tests/test_mvp_pipeline_cleanup_realdb.py -v`
Expected: 3 tests pass (or SKIP if real DB absent). If any test fails, STOP — indicates unexpected real-DB state needing investigation.

- [ ] **Step 3: Commit**

```bash
git add tests/test_mvp_pipeline_cleanup_realdb.py
git commit -m "test: real-DB smoke test for MVP cleanup"
```

---

## Task 11: Run migration on the real DB

**Files:**
- No code changes.

- [ ] **Step 1: Pre-flight inspection**

Run:

```bash
sqlite3 data/batch_db.sqlite "SELECT produkt, COUNT(*) AS n FROM produkt_pipeline GROUP BY produkt ORDER BY n DESC, produkt;"
```

Record counts. Expect Chegina_K40GL/K40GLO/K40GLOL with >1 rows, Chegina_K7 with 5, others with 1.

- [ ] **Step 2: Dry-run**

Run:

```bash
python -m scripts.mvp_pipeline_cleanup --dry-run
```

Expected output includes:
- `Dry run — no changes will be committed.`
- `Stripped non-K7 pipeline: deleted N pipeline rows, ...`
- `K7 fixup: dropped dodatki stage (1 pipeline, 4 limity), ...`
- `Deleted N orphan produkt_etap_limity rows.`
- `Dry run complete — rolled back.`

If preflight or postflight errors appear, STOP and investigate.

- [ ] **Step 3: Run for real**

Run:

```bash
python -m scripts.mvp_pipeline_cleanup
```

Expected output:
- `Backup: data/batch_db.sqlite.bak-pre-mvp-cleanup`
- Same summary as dry-run
- `Migration mvp_pipeline_cleanup_v1 committed.`

- [ ] **Step 4: Verify**

Run:

```bash
python -m scripts.mvp_pipeline_cleanup --verify-only
```

Expected: `Verification OK.`

- [ ] **Step 5: Spot-check K7 state**

Run:

```bash
sqlite3 data/batch_db.sqlite "SELECT ea.kod, pel.dla_szarzy, pel.dla_zbiornika, COUNT(*) AS n FROM produkt_etap_limity pel JOIN etapy_analityczne ea ON pel.etap_id=ea.id WHERE pel.produkt='Chegina_K7' GROUP BY ea.kod;"
```

Expected output:
- `analiza_koncowa|0|1|N`
- `sulfonowanie|1|0|N`
- `utlenienie|1|0|N`
- `standaryzacja|1|0|N`

No `dodatki` row.

Run:

```bash
sqlite3 data/batch_db.sqlite "SELECT etap_kod FROM produkt_etapy WHERE produkt='Chegina_K7' ORDER BY kolejnosc;"
```

Expected:
- `sulfonowanie`
- `utlenienie`
- `standaryzacja`

- [ ] **Step 6: Smoke-test app UI**

Start dev server (or confirm running):

```bash
python -m mbr.app
```

- Log in as laborant
- Open an existing **Chelamid_DK** batch → should still show 7 params in `analiza_koncowa` — no change
- Open an existing **Chegina_K7** batch (if any exists) — should show multi-stage card with sulfonowanie/utlenienie/standaryzacja; `dodatki` sekcja should be gone or empty (acceptable for this PR — filter logic arrives in PR 2)
- Admin `/parametry` Etapy tab → pick Chegina_K40GL, kontekst `sulfonowanie` → should return empty list (correct, because K40GL no longer has sulfonowanie in pipeline)

**Note:** Full UX improvements (skip empty etap for typ; simplified K40GL card) land in PR 2 and PR 3. This PR only cleans data.

- [ ] **Step 7: If anything unexpected**

Restore from backup:

```bash
cp data/batch_db.sqlite.bak-pre-mvp-cleanup data/batch_db.sqlite
```

Otherwise, no commit needed — this is operational.

---

## Task 12: Full suite + memory update + push

**Files:**
- Memory: update `project_parametry_ssot.md` (adjacent to existing entries)

- [ ] **Step 1: Full pytest**

Run: `pytest -q`
Expected: all tests pass (current baseline was 548 passed, 15 skipped; +20 new tests gives ~568).

- [ ] **Step 2: Update project memory**

Append to `/Users/tbk/.claude/projects/-Users-tbk-Desktop-lims-clean/memory/project_parametry_ssot.md` (as an additional section):

```markdown
**MVP pipeline cleanup — PR 1 DONE 2026-04-16:**
- `scripts/mvp_pipeline_cleanup.py` — data-only migration
- Stripped non-K7 multi-stage pipeline (K40GL/GLO/GLOL etc. → single analiza_koncowa)
- K7 fixup: dropped dodatki stage, set dla_szarzy=1 on sulfonowanie/utlenienie/standaryzacja, dla_zbiornika=1 on analiza_koncowa
- K7 produkt_etapy trimmed to {sulfonowanie, utlenienie, standaryzacja}
- Deleted orphan produkt_etap_limity rows
- Marker: `mvp_pipeline_cleanup_v1`. Backup: `data/batch_db.sqlite.bak-pre-mvp-cleanup`
- Code unchanged — PR 2 (filter logic) and PR 3 (constants removal) follow
```

- [ ] **Step 3: Push branch**

```bash
git log --oneline main..HEAD    # review commit list
git push -u origin feature/mvp-pipeline-pr1
```

(Branch name assumes you created it before Task 1 — if not, rename via `git branch -m feature/mvp-pipeline-pr1` and push.)

- [ ] **Step 4: Suggest PR**

Print the GitHub PR URL for the user to open manually.

---

## Self-review (controller checklist)

**Spec coverage:**
- Backup + `_migrations` marker — Task 2 ✓
- Strip non-K7 pipeline + produkt_etapy — Task 4 ✓
- K7 fixup (drop dodatki, typ flags, process etapy trim) — Task 5 ✓
- Orphan cleanup — Task 6 ✓
- Postflight — Task 7 ✓
- Integration + dry-run tests — Tasks 8–9 ✓
- Real-DB smoke — Task 10 ✓
- Production run — Task 11 ✓

**No placeholders:** each step has explicit code, command, or assertion.

**Type consistency:**
- `MVP_MULTI_STAGE` = `{"Chegina_K7"}` — referenced by Tasks 2, 4, 7
- `MIGRATION_NAME` = `"mvp_pipeline_cleanup_v1"` — referenced by Tasks 2, 7, 11
- `_analiza_koncowa_etap_id` helper — defined Task 4, reused Task 7
- `_etap_ids_by_kod` helper — defined Task 5, not reused elsewhere (that's fine)
- Function names: `strip_non_k7_pipeline`, `fixup_chegina_k7`, `clean_orphan_limits`, `postflight`, `migrate`, `backup`, `already_applied`, `mark_applied` — all used consistently

**Out of scope (deferred to PR 2/3):**
- `build_pipeline_context` skip empty etap → PR 2
- `pipeline_has_multi_stage` helper → PR 2
- Remove `FULL_PIPELINE_PRODUCTS` + refactor `get_process_stages`, `build_parametry_lab` → PR 3
- UI cleanup for K40GL/GLO/GLOL → arrives automatically with PR 2 filter

**Risks documented:**
- Backup exists before mutation
- Dry-run path uses `db.rollback()`
- Marker prevents double-apply
- Postflight catches unexpected states before commit
