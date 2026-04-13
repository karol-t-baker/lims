# Batch Card V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend fast_entry batch card with hard gates, intelligent round inheritance, global parameter editing, correction panels, and config-driven decision scenarios for sulfonowanie→utlenianie→standaryzacja across K7, K40GL, K40GLO, K40GLOL.

**Architecture:** Build on existing pipeline infrastructure (ebr_etap_sesja, ebr_pomiar, evaluate_gate). Add `etap_decyzje` table for config-driven decisions. Extend `_fast_entry_content.html` with new partials for correction panels and gate decision modal. Global Edit via PATCH endpoint on `parametry_etapy`.

**Tech Stack:** Python/Flask, SQLite, vanilla JS, Jinja2 templates

**Spec:** `docs/superpowers/specs/2026-04-13-batch-card-v2-design.md`

---

## File Structure

### New files
| File | Responsibility |
|------|---------------|
| `migrate_batch_card_v2.py` | Migration: new table, ALTER columns, populate gates + decisions |
| `mbr/templates/laborant/_correction_panel.html` | Reusable Jinja partial for correction auto-calc panels |
| `mbr/templates/laborant/_gate_decision_modal.html` | Jinja partial for gate pass/fail decision modal |
| `tests/test_batch_card_v2.py` | All V2 tests: inheritance, global edit, decisions |

### Modified files
| File | What changes |
|------|-------------|
| `mbr/models.py:578-606` | ALTER ebr_etap_sesja (decyzja CHECK + komentarz_decyzji), ALTER ebr_pomiar (+odziedziczony), ALTER parametry_etapy (+edytowalny, dt_modified, modified_by), CREATE etap_decyzje |
| `mbr/pipeline/models.py:346-572` | New `create_round_with_inheritance()`, extend `close_sesja()` for new decyzja codes, new `get_etap_decyzje()` |
| `mbr/pipeline/lab_routes.py:195-250` | Extend `/close` to read etap_decyzje, new PATCH `/api/pipeline/lab/parametry-etapy/<id>` endpoint, extend `/wykonaj-korekte` for inheritance |
| `mbr/pipeline/adapter.py:192-300` | Pass `odziedziczony` flag per pole to frontend context |
| `mbr/templates/laborant/_fast_entry_content.html:2825-3092` | Replace `renderGateBanner()` with modal-based flow, extend `updateSpecPanel()` for editable limits, add inherited field CSS + unlock logic |

---

### Task 1: Migration script — new table and columns

**Files:**
- Create: `migrate_batch_card_v2.py`
- Modify: `mbr/models.py:578-606` (init_mbr_tables CREATE TABLE updates)

- [ ] **Step 1: Write migration script**

```python
#!/usr/bin/env python3
"""migrate_batch_card_v2.py — Batch Card V2 schema + seed data."""
import sqlite3
import shutil
from datetime import datetime

DB_PATH = "data/batch_db.sqlite"


def migrate():
    backup = f"{DB_PATH}.bak-pre-batch-card-v2"
    shutil.copy2(DB_PATH, backup)
    print(f"Backup: {backup}")

    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    # --- 1. etap_decyzje table ---
    cur.execute("""
        CREATE TABLE IF NOT EXISTS etap_decyzje (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            etap_id             INTEGER NOT NULL REFERENCES produkt_pipeline(id),
            typ                 TEXT NOT NULL CHECK (typ IN ('pass', 'fail')),
            kod                 TEXT NOT NULL,
            label               TEXT NOT NULL,
            akcja               TEXT NOT NULL CHECK (akcja IN (
                'next_stage', 'new_round', 'release', 'close', 'skip_to_next'
            )),
            wymaga_komentarza   INTEGER DEFAULT 0,
            sort_order          INTEGER DEFAULT 0
        )
    """)
    print("Created etap_decyzje")

    # --- 2. ALTER ebr_pomiar + odziedziczony ---
    cols = [r["name"] for r in cur.execute("PRAGMA table_info(ebr_pomiar)")]
    if "odziedziczony" not in cols:
        cur.execute("ALTER TABLE ebr_pomiar ADD COLUMN odziedziczony INTEGER DEFAULT 0")
        print("Added ebr_pomiar.odziedziczony")

    # --- 3. ALTER ebr_etap_sesja + komentarz_decyzji ---
    cols = [r["name"] for r in cur.execute("PRAGMA table_info(ebr_etap_sesja)")]
    if "komentarz_decyzji" not in cols:
        cur.execute("ALTER TABLE ebr_etap_sesja ADD COLUMN komentarz_decyzji TEXT")
        print("Added ebr_etap_sesja.komentarz_decyzji")

    # --- 4. ALTER parametry_etapy + audit columns ---
    cols = [r["name"] for r in cur.execute("PRAGMA table_info(parametry_etapy)")]
    for col, ddl in [
        ("edytowalny", "INTEGER DEFAULT 1"),
        ("dt_modified", "TEXT"),
        ("modified_by", "INTEGER"),
    ]:
        if col not in cols:
            cur.execute(f"ALTER TABLE parametry_etapy ADD COLUMN {col} {ddl}")
            print(f"Added parametry_etapy.{col}")

    # --- 5. Relax decyzja CHECK on ebr_etap_sesja ---
    # SQLite cannot ALTER CHECK constraints; we rebuild if needed.
    # The existing CHECK is: decyzja IN ('zamknij_etap', 'reopen_etap')
    # New codes: 'przejscie', 'new_round', 'release_comment', 'close_note', 'skip_to_next'
    # Approach: drop CHECK by recreating table (preserving data).
    _rebuild_ebr_etap_sesja(cur)

    # --- 6. Populate etap_decyzje for 4 products × 3 stages ---
    _seed_etap_decyzje(cur)

    # --- 7. Populate etap_warunki for gates ---
    _seed_etap_warunki(cur)

    db.commit()
    db.close()
    print("Migration complete.")


def _rebuild_ebr_etap_sesja(cur):
    """Rebuild ebr_etap_sesja with relaxed decyzja CHECK."""
    cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='ebr_etap_sesja'")
    row = cur.fetchone()
    if row and "release_comment" in row["sql"]:
        print("ebr_etap_sesja CHECK already updated, skipping rebuild")
        return

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS _ebr_etap_sesja_new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ebr_id          INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
            etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
            runda           INTEGER NOT NULL DEFAULT 1,
            status          TEXT NOT NULL DEFAULT 'nierozpoczety'
                            CHECK(status IN ('nierozpoczety', 'w_trakcie', 'zamkniety')),
            dt_start        TEXT,
            dt_end          TEXT,
            laborant        TEXT,
            decyzja         TEXT CHECK(decyzja IN (
                'zamknij_etap', 'reopen_etap', 'przejscie',
                'new_round', 'release_comment', 'close_note', 'skip_to_next'
            )),
            komentarz       TEXT,
            komentarz_decyzji TEXT,
            UNIQUE(ebr_id, etap_id, runda)
        );
        INSERT INTO _ebr_etap_sesja_new
            SELECT id, ebr_id, etap_id, runda, status, dt_start, dt_end,
                   laborant, decyzja, komentarz, komentarz_decyzji
            FROM ebr_etap_sesja;
        DROP TABLE ebr_etap_sesja;
        ALTER TABLE _ebr_etap_sesja_new RENAME TO ebr_etap_sesja;
    """)
    print("Rebuilt ebr_etap_sesja with extended decyzja CHECK")


def _seed_etap_decyzje(cur):
    """Populate etap_decyzje for 4 products × 3 stages."""
    # Get pipeline stage IDs for target products
    products = ["K7", "K40GL", "K40GLO", "K40GLOL"]
    stage_kods = ["sulfonowanie", "utlenienie", "standaryzacja"]

    rows = cur.execute("""
        SELECT pp.id as pp_id, pp.produkt, ea.kod as etap_kod
        FROM produkt_pipeline pp
        JOIN etapy_analityczne ea ON ea.id = pp.etap_id
        WHERE pp.produkt IN ({}) AND ea.kod IN ({})
    """.format(
        ",".join("?" for _ in products),
        ",".join("?" for _ in stage_kods),
    ), products + stage_kods).fetchall()

    if not rows:
        print("WARNING: No pipeline stages found for target products. Skipping seed.")
        return

    # Clear old decisions for these stages
    pp_ids = [r["pp_id"] for r in rows]
    cur.execute(
        "DELETE FROM etap_decyzje WHERE etap_id IN ({})".format(
            ",".join("?" for _ in pp_ids)
        ), pp_ids,
    )

    decisions = {
        "sulfonowanie": [
            ("pass", "next_stage", "Przejdź do utleniania", "next_stage", 0, 0),
            ("fail", "new_round", "Nowa runda", "new_round", 0, 0),
        ],
        "utlenienie": [
            ("pass", "next_stage", "Przejdź do standaryzacji", "next_stage", 0, 0),
            ("fail", "new_round", "Nowa runda", "new_round", 0, 0),
            ("fail", "skip_to_next", "Przenieś korektę do standaryzacji", "skip_to_next", 0, 1),
        ],
        "standaryzacja": [
            ("pass", "release", "Zatwierdź szarżę", "release", 0, 0),
            ("fail", "new_round", "Kolejna runda (korekta)", "new_round", 0, 0),
            ("fail", "release_comment", "Zwolnij z komentarzem", "release", 1, 1),
            ("fail", "close_note", "Zamknij z notatką", "close", 1, 2),
        ],
    }

    count = 0
    for r in rows:
        etap_kod = r["etap_kod"]
        pp_id = r["pp_id"]
        for typ, kod, label, akcja, wymaga, sort in decisions.get(etap_kod, []):
            cur.execute("""
                INSERT INTO etap_decyzje (etap_id, typ, kod, label, akcja, wymaga_komentarza, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (pp_id, typ, kod, label, akcja, wymaga, sort))
            count += 1

    print(f"Seeded {count} etap_decyzje rows for {len(rows)} pipeline stages")


def _seed_etap_warunki(cur):
    """Populate gate conditions for SO₃²⁻ and H₂O₂."""
    products = ["K7", "K40GL", "K40GLO", "K40GLOL"]

    # Get parametr IDs
    so3_id = cur.execute(
        "SELECT id FROM parametry_analityczne WHERE kod = 'so3'"
    ).fetchone()
    h2o2_id = cur.execute(
        "SELECT id FROM parametry_analityczne WHERE kod = 'h2o2'"
    ).fetchone()

    if not so3_id or not h2o2_id:
        print("WARNING: so3 or h2o2 parameter not found. Skipping gate seed.")
        return

    so3_id = so3_id["id"]
    h2o2_id = h2o2_id["id"]

    # Get etap_ids (from etapy_analityczne, not produkt_pipeline)
    stages = cur.execute("""
        SELECT ea.id as ea_id, ea.kod, pp.produkt
        FROM produkt_pipeline pp
        JOIN etapy_analityczne ea ON ea.id = pp.etap_id
        WHERE pp.produkt IN ({}) AND ea.kod IN ('sulfonowanie', 'utlenienie')
    """.format(",".join("?" for _ in products)), products).fetchall()

    count = 0
    for s in stages:
        etap_id = s["ea_id"]
        kod = s["kod"]

        # SO₃²⁻ ≤ 0.1 for both sulfonowanie and utlenienie
        existing = cur.execute(
            "SELECT id FROM etap_warunki WHERE etap_id = ? AND parametr_id = ?",
            (etap_id, so3_id),
        ).fetchone()
        if not existing:
            cur.execute("""
                INSERT INTO etap_warunki (etap_id, parametr_id, operator, wartosc, opis_warunku)
                VALUES (?, ?, '<=', 0.1, 'SO₃²⁻ ≤ 0.1%')
            """, (etap_id, so3_id))
            count += 1

        # H₂O₂ gate only for utlenienie
        if kod == "utlenienie":
            existing = cur.execute(
                "SELECT id FROM etap_warunki WHERE etap_id = ? AND parametr_id = ?",
                (etap_id, h2o2_id),
            ).fetchone()
            if not existing:
                cur.execute("""
                    INSERT INTO etap_warunki (etap_id, parametr_id, operator, wartosc, opis_warunku)
                    VALUES (?, ?, '<=', 0.1, 'H₂O₂ ≤ 0.1%')
                """, (etap_id, h2o2_id))
                count += 1

    print(f"Seeded {count} etap_warunki gate conditions")


if __name__ == "__main__":
    migrate()
```

- [ ] **Step 2: Update init_mbr_tables() for new installs**

In `mbr/models.py`, add the `etap_decyzje` CREATE TABLE after the `etap_warunki` block (around line 560). Also add the new columns to existing CREATE TABLE statements so fresh DBs have them:

Add after `etap_warunki` CREATE (line ~560):
```python
    cur.execute("""
        CREATE TABLE IF NOT EXISTS etap_decyzje (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            etap_id             INTEGER NOT NULL REFERENCES produkt_pipeline(id),
            typ                 TEXT NOT NULL CHECK (typ IN ('pass', 'fail')),
            kod                 TEXT NOT NULL,
            label               TEXT NOT NULL,
            akcja               TEXT NOT NULL CHECK (akcja IN (
                'next_stage', 'new_round', 'release', 'close', 'skip_to_next'
            )),
            wymaga_komentarza   INTEGER DEFAULT 0,
            sort_order          INTEGER DEFAULT 0
        )
    """)
```

Update `ebr_etap_sesja` CREATE (line 578) — extend `decyzja` CHECK:
```python
    decyzja TEXT CHECK(decyzja IN (
        'zamknij_etap', 'reopen_etap', 'przejscie',
        'new_round', 'release_comment', 'close_note', 'skip_to_next'
    )),
    komentarz_decyzji TEXT,
```

Update `ebr_pomiar` CREATE (line 594) — add `odziedziczony`:
```python
    odziedziczony   INTEGER DEFAULT 0,
```

Update `parametry_etapy` CREATE (line 472) — add audit columns:
```python
    edytowalny      INTEGER DEFAULT 1,
    dt_modified     TEXT,
    modified_by     INTEGER,
```

- [ ] **Step 3: Run migration on dev DB**

Run: `python migrate_batch_card_v2.py`
Expected: Backup created, tables altered, seed data inserted, "Migration complete."

- [ ] **Step 4: Verify migration**

Run: `sqlite3 data/batch_db.sqlite "SELECT count(*) FROM etap_decyzje; PRAGMA table_info(ebr_pomiar); PRAGMA table_info(ebr_etap_sesja); PRAGMA table_info(parametry_etapy);"`
Expected: etap_decyzje count > 0, odziedziczony column present, komentarz_decyzji column present, edytowalny/dt_modified/modified_by present.

- [ ] **Step 5: Commit**

```bash
git add migrate_batch_card_v2.py mbr/models.py
git commit -m "feat: batch card V2 migration — etap_decyzje, gate seeds, schema extensions"
```

---

### Task 2: Backend — intelligent round inheritance

**Files:**
- Modify: `mbr/pipeline/models.py:346-475`
- Test: `tests/test_batch_card_v2.py`

- [ ] **Step 1: Write failing test for round inheritance**

Create `tests/test_batch_card_v2.py`:

```python
"""tests/test_batch_card_v2.py — Batch Card V2 unit tests."""
import sqlite3
import pytest
from mbr.models import init_mbr_tables
from mbr.pipeline.models import (
    create_sesja,
    save_pomiar,
    get_pomiary,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_mbr_tables(conn)
    # Seed minimal data: product, batch, pipeline stage
    conn.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, precision) VALUES (1, 'so3', 'Siarczyny', 'titracja', 3)"
    )
    conn.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, precision) VALUES (2, 'ph', 'pH', 'bezposredni', 1)"
    )
    conn.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, precision) VALUES (3, 'sm', 'Sucha masa', 'bezposredni', 1)"
    )
    conn.execute(
        "INSERT INTO ebr_batches (ebr_id, nr_partii, produkt, typ, status) VALUES (1, 'TEST-001', 'K40GLO', 'szarza', 'open')"
    )
    conn.execute(
        "INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (10, 'sulfonowanie', 'Sulfonowanie', 'cykliczny')"
    )
    conn.commit()
    yield conn
    conn.close()


def test_create_round_with_inheritance_copies_ok_skips_fail(db):
    """Round N+1 should inherit OK measurements, leave failed ones empty."""
    from mbr.pipeline.models import create_round_with_inheritance

    # Round 1: so3 out of limit, ph OK, sm OK (no limits)
    sesja1 = create_sesja(db, ebr_id=1, etap_id=10, runda=1)
    save_pomiar(db, sesja1, parametr_id=1, wartosc=0.15, min_limit=None, max_limit=0.1, wpisal="lab")  # so3 FAIL
    save_pomiar(db, sesja1, parametr_id=2, wartosc=7.2, min_limit=6.0, max_limit=8.0, wpisal="lab")    # ph OK
    save_pomiar(db, sesja1, parametr_id=3, wartosc=42.0, min_limit=None, max_limit=None, wpisal="lab")  # sm no limit

    # Create round 2 with inheritance
    sesja2 = create_round_with_inheritance(db, ebr_id=1, etap_id=10, prev_sesja_id=sesja1, laborant="lab")

    pomiary = {p["parametr_id"]: p for p in get_pomiary(db, sesja2)}

    # ph (OK) → copied with odziedziczony=1
    assert pomiary[2]["wartosc"] == 7.2
    assert pomiary[2]["odziedziczony"] == 1

    # sm (no limit, w_limicie=NULL) → copied with odziedziczony=1
    assert pomiary[3]["wartosc"] == 42.0
    assert pomiary[3]["odziedziczony"] == 1

    # so3 (FAIL) → NOT copied
    assert 1 not in pomiary


def test_inherited_measurement_preserves_limits(db):
    """Inherited measurements should keep their original min/max limits."""
    from mbr.pipeline.models import create_round_with_inheritance

    sesja1 = create_sesja(db, ebr_id=1, etap_id=10, runda=1)
    save_pomiar(db, sesja1, parametr_id=2, wartosc=7.2, min_limit=6.0, max_limit=8.0, wpisal="lab")

    sesja2 = create_round_with_inheritance(db, ebr_id=1, etap_id=10, prev_sesja_id=sesja1, laborant="lab")
    pomiary = {p["parametr_id"]: p for p in get_pomiary(db, sesja2)}

    assert pomiary[2]["min_limit"] == 6.0
    assert pomiary[2]["max_limit"] == 8.0
    assert pomiary[2]["w_limicie"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_batch_card_v2.py -v`
Expected: FAIL — `ImportError: cannot import name 'create_round_with_inheritance'`

- [ ] **Step 3: Implement create_round_with_inheritance()**

Add to `mbr/pipeline/models.py` after `create_sesja()` (after line ~360):

```python
def create_round_with_inheritance(
    db: sqlite3.Connection,
    ebr_id: int,
    etap_id: int,
    prev_sesja_id: int,
    laborant: str | None = None,
) -> int:
    """Create new round session, copying OK/no-limit measurements from previous round.

    Measurements with w_limicie=1 or w_limicie IS NULL are copied with odziedziczony=1.
    Measurements with w_limicie=0 (out of limit) are NOT copied — lab must re-enter.
    """
    # Determine next runda number
    prev = db.execute(
        "SELECT runda FROM ebr_etap_sesja WHERE id = ?", (prev_sesja_id,)
    ).fetchone()
    next_runda = (prev["runda"] if prev else 0) + 1

    new_sesja_id = create_sesja(db, ebr_id, etap_id, runda=next_runda, laborant=laborant)

    # Copy OK + no-limit measurements
    ok_pomiary = db.execute("""
        SELECT parametr_id, wartosc, min_limit, max_limit, w_limicie, wpisal
        FROM ebr_pomiar
        WHERE sesja_id = ? AND (w_limicie = 1 OR w_limicie IS NULL)
    """, (prev_sesja_id,)).fetchall()

    now = datetime.now().isoformat(timespec="seconds")
    for p in ok_pomiary:
        db.execute("""
            INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, min_limit, max_limit,
                                    w_limicie, is_manual, dt_wpisu, wpisal, odziedziczony)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, 1)
        """, (new_sesja_id, p["parametr_id"], p["wartosc"],
              p["min_limit"], p["max_limit"], p["w_limicie"],
              now, p["wpisal"]))

    db.commit()
    return new_sesja_id
```

Ensure `from datetime import datetime` is imported at the top of `pipeline/models.py` (check if already present).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_batch_card_v2.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add mbr/pipeline/models.py tests/test_batch_card_v2.py
git commit -m "feat: create_round_with_inheritance — copy OK measurements, skip failed"
```

---

### Task 3: Backend — etap_decyzje query + extended close_sesja

**Files:**
- Modify: `mbr/pipeline/models.py:393-408`
- Test: `tests/test_batch_card_v2.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_batch_card_v2.py`:

```python
def test_get_etap_decyzje_returns_sorted_options(db):
    """get_etap_decyzje should return decisions for given etap+typ, sorted by sort_order."""
    from mbr.pipeline.models import get_etap_decyzje

    # Seed etap_decyzje for etap_id=10
    db.execute("INSERT INTO produkt_pipeline (id, produkt, etap_id, kolejnosc) VALUES (100, 'K40GLO', 10, 1)")
    db.execute("""
        INSERT INTO etap_decyzje (etap_id, typ, kod, label, akcja, wymaga_komentarza, sort_order)
        VALUES (100, 'fail', 'new_round', 'Nowa runda', 'new_round', 0, 0)
    """)
    db.execute("""
        INSERT INTO etap_decyzje (etap_id, typ, kod, label, akcja, wymaga_komentarza, sort_order)
        VALUES (100, 'fail', 'release_comment', 'Zwolnij z komentarzem', 'release', 1, 1)
    """)
    db.execute("""
        INSERT INTO etap_decyzje (etap_id, typ, kod, label, akcja, wymaga_komentarza, sort_order)
        VALUES (100, 'pass', 'next_stage', 'Dalej', 'next_stage', 0, 0)
    """)
    db.commit()

    fail_opts = get_etap_decyzje(db, pp_id=100, typ="fail")
    assert len(fail_opts) == 2
    assert fail_opts[0]["kod"] == "new_round"
    assert fail_opts[1]["kod"] == "release_comment"
    assert fail_opts[1]["wymaga_komentarza"] == 1

    pass_opts = get_etap_decyzje(db, pp_id=100, typ="pass")
    assert len(pass_opts) == 1
    assert pass_opts[0]["akcja"] == "next_stage"


def test_close_sesja_with_new_decision_codes(db):
    """close_sesja should accept V2 decision codes and store komentarz_decyzji."""
    from mbr.pipeline.models import close_sesja

    sesja_id = create_sesja(db, ebr_id=1, etap_id=10, runda=1)
    # Start the session first
    db.execute("UPDATE ebr_etap_sesja SET status = 'w_trakcie' WHERE id = ?", (sesja_id,))
    db.commit()

    close_sesja(db, sesja_id, decyzja="release_comment", komentarz="Dodatek wody z ręki")

    row = db.execute("SELECT * FROM ebr_etap_sesja WHERE id = ?", (sesja_id,)).fetchone()
    assert row["status"] == "zamkniety"
    assert row["decyzja"] == "release_comment"
    assert row["komentarz_decyzji"] == "Dodatek wody z ręki"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_batch_card_v2.py::test_get_etap_decyzje_returns_sorted_options tests/test_batch_card_v2.py::test_close_sesja_with_new_decision_codes -v`
Expected: FAIL — `ImportError: cannot import name 'get_etap_decyzje'` and close_sesja CHECK violation

- [ ] **Step 3: Implement get_etap_decyzje()**

Add to `mbr/pipeline/models.py` after `list_etap_warunki()` (~line 174):

```python
def get_etap_decyzje(
    db: sqlite3.Connection,
    pp_id: int,
    typ: str,
) -> list[dict]:
    """Return decision options for a pipeline stage, filtered by pass/fail type."""
    rows = db.execute("""
        SELECT id, etap_id, typ, kod, label, akcja, wymaga_komentarza, sort_order
        FROM etap_decyzje
        WHERE etap_id = ? AND typ = ?
        ORDER BY sort_order
    """, (pp_id, typ)).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Update close_sesja() to accept new codes and komentarz_decyzji**

Modify `close_sesja()` at `mbr/pipeline/models.py:393-408`. The current function stores `decyzja` and updates status. Extend the `komentarz` parameter to also store `komentarz_decyzji`:

```python
def close_sesja(
    db: sqlite3.Connection,
    sesja_id: int,
    decyzja: str,
    komentarz: str = None,
) -> None:
    """Close an analytical session with a decision.

    decyzja values: zamknij_etap, reopen_etap, przejscie,
                    new_round, release_comment, close_note, skip_to_next
    """
    now = datetime.now().isoformat(timespec="seconds")
    if decyzja == "reopen_etap":
        db.execute("""
            UPDATE ebr_etap_sesja SET status = 'w_trakcie', decyzja = ?, komentarz = ?
            WHERE id = ?
        """, (decyzja, komentarz, sesja_id))
    else:
        db.execute("""
            UPDATE ebr_etap_sesja
            SET status = 'zamkniety', dt_end = ?, decyzja = ?, komentarz_decyzji = ?
            WHERE id = ?
        """, (now, decyzja, komentarz, sesja_id))
    db.commit()
```

Note: Check the exact current implementation before editing — the key change is:
1. Store `komentarz` in `komentarz_decyzji` column for non-reopen decisions
2. All new decyzja codes are accepted (CHECK constraint was relaxed in migration)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_batch_card_v2.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add mbr/pipeline/models.py tests/test_batch_card_v2.py
git commit -m "feat: get_etap_decyzje + extended close_sesja for V2 decision codes"
```

---

### Task 4: Backend — Global Edit PATCH endpoint

**Files:**
- Modify: `mbr/pipeline/lab_routes.py`
- Test: `tests/test_batch_card_v2.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_batch_card_v2.py`:

```python
from mbr.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        # Login as lab user
        with app.app_context():
            from mbr.db import get_db
            db = get_db()
            # Ensure a test user exists
            from mbr.auth.models import get_user_by_login
            user = get_user_by_login(db, "testlab")
            if not user:
                import bcrypt
                hashed = bcrypt.hashpw(b"test123", bcrypt.gensalt()).decode()
                db.execute(
                    "INSERT INTO workers (login, password_hash, rola, imie, nazwisko, aktywny) VALUES (?, ?, 'laborant', 'Test', 'Lab', 1)",
                    ("testlab", hashed),
                )
                db.commit()
        # Login
        c.post("/auth/login", data={"login": "testlab", "password": "test123"}, follow_redirects=True)
        yield c


def test_global_edit_patch_updates_limit(client):
    """PATCH /api/pipeline/lab/parametry-etapy/<id> should update limit and audit fields."""
    with client.application.app_context():
        from mbr.db import get_db
        db = get_db()

        # Find a parametry_etapy row
        row = db.execute("SELECT id, min_limit, max_limit FROM parametry_etapy LIMIT 1").fetchone()
        if not row:
            pytest.skip("No parametry_etapy rows in test DB")

        pe_id = row["id"]
        resp = client.patch(
            f"/api/pipeline/lab/parametry-etapy/{pe_id}",
            json={"max_limit": 0.2, "min_limit": 0.05},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

        updated = db.execute("SELECT * FROM parametry_etapy WHERE id = ?", (pe_id,)).fetchone()
        assert updated["max_limit"] == 0.2
        assert updated["min_limit"] == 0.05
        assert updated["dt_modified"] is not None
        assert updated["modified_by"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_batch_card_v2.py::test_global_edit_patch_updates_limit -v`
Expected: FAIL — 404 (route not found)

- [ ] **Step 3: Implement PATCH endpoint**

Add to `mbr/pipeline/lab_routes.py` after the last route (~line 381):

```python
@pipeline_bp.route("/api/pipeline/lab/parametry-etapy/<int:pe_id>", methods=["PATCH"])
@login_required
def lab_patch_parametry_etapy(pe_id):
    """Global Edit: update limits/target/formula on a parametry_etapy binding."""
    from mbr.db import get_db
    from flask import session

    db = get_db()
    row = db.execute("SELECT * FROM parametry_etapy WHERE id = ?", (pe_id,)).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404

    data = request.get_json(silent=True) or {}
    allowed = {"min_limit", "max_limit", "target", "formula", "sa_bias", "nawazka_g", "precision"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400

    # Build SET clause
    sets = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values())

    # Audit
    now = datetime.now().isoformat(timespec="seconds")
    user_id = session.get("user_id")
    sets += ", dt_modified = ?, modified_by = ?"
    vals.extend([now, user_id])

    vals.append(pe_id)
    db.execute(f"UPDATE parametry_etapy SET {sets} WHERE id = ?", vals)
    db.commit()

    return jsonify({"ok": True, "updated": list(updates.keys())})
```

Add required imports at top of `lab_routes.py` if not present:
```python
from datetime import datetime
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_batch_card_v2.py::test_global_edit_patch_updates_limit -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mbr/pipeline/lab_routes.py tests/test_batch_card_v2.py
git commit -m "feat: PATCH /api/pipeline/lab/parametry-etapy — Global Edit endpoint"
```

---

### Task 5: Backend — decision routing in close + wykonaj-korekte

**Files:**
- Modify: `mbr/pipeline/lab_routes.py:195-300`
- Test: `tests/test_batch_card_v2.py`

- [ ] **Step 1: Write failing test for decision-aware close**

Add to `tests/test_batch_card_v2.py`:

```python
def test_close_with_etap_decyzje_returns_options(client):
    """POST /close with gate fail should return decision options from etap_decyzje."""
    with client.application.app_context():
        from mbr.db import get_db
        db = get_db()

        # Find a pipeline batch with an active session
        sesja = db.execute("""
            SELECT s.id, s.ebr_id, s.etap_id, pp.id as pp_id
            FROM ebr_etap_sesja s
            JOIN produkt_pipeline pp ON pp.etap_id = s.etap_id
            JOIN ebr_batches b ON b.ebr_id = s.ebr_id AND b.produkt = pp.produkt
            WHERE s.status = 'w_trakcie'
            LIMIT 1
        """).fetchone()
        if not sesja:
            pytest.skip("No active pipeline session in test DB")

        # Seed a fail decision for this stage
        db.execute("""
            INSERT OR IGNORE INTO etap_decyzje (etap_id, typ, kod, label, akcja, wymaga_komentarza, sort_order)
            VALUES (?, 'fail', 'new_round', 'Nowa runda', 'new_round', 0, 0)
        """, (sesja["pp_id"],))
        db.commit()

        resp = client.post(
            f"/api/pipeline/lab/ebr/{sesja['ebr_id']}/etap/{sesja['etap_id']}/close",
            json={"sesja_id": sesja["id"], "decyzja": "new_round"},
            content_type="application/json",
        )
        assert resp.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_batch_card_v2.py::test_close_with_etap_decyzje_returns_options -v`
Expected: FAIL — 400/500 because current close_sesja rejects 'new_round' decyzja

- [ ] **Step 3: Extend lab_close_sesja route**

Modify `lab_close_sesja()` in `mbr/pipeline/lab_routes.py` (line ~195). The current handler calls `close_sesja(db, sesja_id, decyzja)`. Extend it to:

1. Accept V2 decision codes
2. For `new_round` → call `create_round_with_inheritance()` and return `new_sesja_id`
3. For `release_comment`/`close_note` → require `komentarz` in request body
4. For `skip_to_next` → close current + advance to next stage

```python
@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/etap/<int:etap_id>/close", methods=["POST"])
@login_required
def lab_close_sesja(ebr_id, etap_id):
    from mbr.db import get_db
    db = get_db()
    data = request.get_json(silent=True) or {}
    sesja_id = data.get("sesja_id")
    decyzja = data.get("decyzja", "zamknij_etap")
    komentarz = data.get("komentarz")

    if not sesja_id:
        return jsonify({"error": "sesja_id required"}), 400

    # V2 decision routing
    if decyzja == "new_round":
        close_sesja(db, sesja_id, decyzja="new_round", komentarz=komentarz)
        new_sesja_id = create_round_with_inheritance(
            db, ebr_id, etap_id, prev_sesja_id=sesja_id,
            laborant=session.get("login"),
        )
        return jsonify({"ok": True, "action": "new_round", "new_sesja_id": new_sesja_id})

    elif decyzja in ("release_comment", "close_note"):
        if not komentarz:
            return jsonify({"error": "komentarz required for this decision"}), 400
        close_sesja(db, sesja_id, decyzja=decyzja, komentarz=komentarz)
        return jsonify({"ok": True, "action": decyzja})

    elif decyzja == "skip_to_next":
        close_sesja(db, sesja_id, decyzja="skip_to_next", komentarz=komentarz)
        # Advance pipeline to next stage
        from mbr.etapy.models import zatwierdz_etap
        ebr = db.execute("SELECT produkt FROM ebr_batches WHERE ebr_id = ?", (ebr_id,)).fetchone()
        etap_kod = db.execute("SELECT kod FROM etapy_analityczne WHERE id = ?", (etap_id,)).fetchone()["kod"]
        next_stage = zatwierdz_etap(db, ebr_id, etap_kod, session.get("login", "system"), ebr["produkt"])
        return jsonify({"ok": True, "action": "skip_to_next", "next_stage": next_stage})

    else:
        # Original flow: zamknij_etap, przejscie, reopen_etap
        close_sesja(db, sesja_id, decyzja=decyzja, komentarz=komentarz)
        return jsonify({"ok": True})
```

Add import at the top of the function or file:
```python
from mbr.pipeline.models import close_sesja, create_round_with_inheritance
```

- [ ] **Step 4: Run all tests**

Run: `pytest tests/test_batch_card_v2.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add mbr/pipeline/lab_routes.py tests/test_batch_card_v2.py
git commit -m "feat: V2 decision routing in lab_close_sesja — new_round, release, close, skip"
```

---

### Task 6: Backend — expose decisions + inheritance flags via API

**Files:**
- Modify: `mbr/pipeline/lab_routes.py:70-110` (lab_get_etap_form)
- Modify: `mbr/pipeline/adapter.py:192-300` (build_pipeline_context)

- [ ] **Step 1: Extend lab_get_etap_form to return etap_decyzje**

In `mbr/pipeline/lab_routes.py`, the `lab_get_etap_form()` route (line ~70) returns `{etap, parametry, warunki, korekty_katalog, sesje, current_sesja, pomiary}`. Extend the response to include decision options:

Add after the existing response dict construction:
```python
    # V2: include decision options
    from mbr.pipeline.models import get_etap_decyzje
    pp_row = db.execute(
        "SELECT id FROM produkt_pipeline WHERE produkt = ? AND etap_id = ?",
        (ebr["produkt"], etap_id),
    ).fetchone()
    decyzje_pass = get_etap_decyzje(db, pp_row["id"], "pass") if pp_row else []
    decyzje_fail = get_etap_decyzje(db, pp_row["id"], "fail") if pp_row else []

    # Add to response
    result["decyzje_pass"] = decyzje_pass
    result["decyzje_fail"] = decyzje_fail
```

- [ ] **Step 2: Extend adapter to pass odziedziczony flag**

In `mbr/pipeline/adapter.py`, the `pipeline_dual_write()` function (line ~303) writes to `ebr_pomiar`. The read path is in `build_pipeline_context()` which builds `parametry_lab` dict. The actual pomiary values come through a separate channel — they're loaded in `lab_get_etap_form` via `get_pomiary()`.

Modify `get_pomiary()` in `mbr/pipeline/models.py` (line ~478) to include `odziedziczony` in the SELECT:

Current SELECT likely reads:
```sql
SELECT p.*, pa.kod, pa.label, pa.typ, pa.skrot
FROM ebr_pomiar p JOIN parametry_analityczne pa ON pa.id = p.parametr_id
WHERE p.sesja_id = ? ORDER BY p.id
```

Add `p.odziedziczony` to the SELECT (it's already there via `p.*`, but verify the column exists in the return dict).

- [ ] **Step 3: Run existing tests to check nothing breaks**

Run: `pytest tests/ -v --tb=short`
Expected: All existing tests PASS

- [ ] **Step 4: Commit**

```bash
git add mbr/pipeline/lab_routes.py mbr/pipeline/models.py mbr/pipeline/adapter.py
git commit -m "feat: expose etap_decyzje + odziedziczony flag in pipeline API"
```

---

### Task 7: Frontend — gate decision modal

**Files:**
- Create: `mbr/templates/laborant/_gate_decision_modal.html`
- Modify: `mbr/templates/laborant/_fast_entry_content.html:2825-3092`

- [ ] **Step 1: Create gate decision modal partial**

Create `mbr/templates/laborant/_gate_decision_modal.html`:

```html
{# _gate_decision_modal.html — Config-driven gate decision modal for V2 #}
{# Included by _fast_entry_content.html JS. Rendered client-side. #}

<script>
/**
 * Show gate decision modal after evaluating gate pass/fail.
 * @param {string} sekcja - Section key (e.g., "sulfonowanie")
 * @param {object} gate - Gate result from evaluate_gate: {passed, failures}
 * @param {object} etapMeta - Stage metadata with decyzje_pass, decyzje_fail
 * @param {number} sesjaId - Current session ID
 * @param {number} etapId - Current analytical stage ID
 */
function showGateDecisionModal(sekcja, gate, etapMeta, sesjaId, etapId) {
    // Remove any existing modal
    const existing = document.getElementById('gate-decision-modal');
    if (existing) existing.remove();

    const typ = gate.passed ? 'pass' : 'fail';
    const options = gate.passed
        ? (etapMeta.decyzje_pass || [])
        : (etapMeta.decyzje_fail || []);

    // If no config-driven options, fall back to default close
    if (!options.length) {
        if (gate.passed) {
            closePipelineStage(sekcja);
        }
        return;
    }

    // Build failure summary
    let failureHtml = '';
    if (!gate.passed && gate.failures && gate.failures.length) {
        failureHtml = '<div style="background:var(--red-bg,#fef2f2);border:1px solid var(--red,#dc2626);border-radius:6px;padding:10px;margin-bottom:12px;">';
        failureHtml += '<div style="font-weight:600;color:var(--red,#dc2626);margin-bottom:6px;">Bramka niespełniona:</div>';
        gate.failures.forEach(f => {
            const w = f.warunek || {};
            failureHtml += `<div style="display:flex;justify-content:space-between;padding:3px 0;">`;
            failureHtml += `<span>${f.kod || 'parametr'}</span>`;
            failureHtml += `<span style="font-family:var(--mono);">wynik: <b>${f.wartosc != null ? f.wartosc : '—'}</b> | limit: ${w.operator || ''} ${w.wartosc != null ? w.wartosc : ''}</span>`;
            failureHtml += `</div>`;
            // Editable threshold — Global Edit inline
            if (w.warunek_id) {
                failureHtml += `<div style="margin-top:4px;">`;
                failureHtml += `<label style="font-size:12px;color:var(--muted);">Zmień próg:</label> `;
                failureHtml += `<input type="text" inputmode="decimal" value="${w.wartosc}" `;
                failureHtml += `data-warunek-id="${w.warunek_id}" data-pe-id="${w.pe_id || ''}" `;
                failureHtml += `style="width:60px;border:1px solid var(--border);border-radius:3px;padding:2px 4px;font-family:var(--mono);" `;
                failureHtml += `onblur="reEvaluateThreshold(this, '${sekcja}', ${sesjaId}, ${etapId})" />`;
                failureHtml += `</div>`;
            }
        });
        failureHtml += '</div>';
    }

    // Build option buttons
    let optionsHtml = '';
    options.forEach(opt => {
        const btnColor = opt.akcja === 'new_round' ? 'var(--amber,#f59e0b)'
            : opt.akcja === 'release' ? 'var(--green,#16a34a)'
            : opt.akcja === 'close' ? 'var(--red,#dc2626)'
            : opt.akcja === 'next_stage' ? 'var(--teal,#0d9488)'
            : 'var(--blue,#2563eb)';

        optionsHtml += `<div style="margin-bottom:8px;">`;
        if (opt.wymaga_komentarza) {
            optionsHtml += `<textarea id="decyzja-komentarz-${opt.kod}" placeholder="Wpisz komentarz..." `;
            optionsHtml += `style="width:100%;min-height:50px;border:1px solid var(--border);border-radius:4px;padding:6px;margin-bottom:4px;font-family:inherit;"></textarea>`;
        }
        optionsHtml += `<button onclick="executeDecision('${opt.kod}', '${opt.akcja}', ${opt.wymaga_komentarza}, ${sesjaId}, ${etapId}, '${sekcja}')" `;
        optionsHtml += `style="width:100%;padding:10px;border:none;border-radius:6px;background:${btnColor};color:#fff;font-weight:600;cursor:pointer;">`;
        optionsHtml += `${opt.label}</button>`;
        optionsHtml += `</div>`;
    });

    const title = gate.passed ? 'Bramka spełniona' : 'Bramka niespełniona';
    const titleColor = gate.passed ? 'var(--green,#16a34a)' : 'var(--red,#dc2626)';

    const html = `
    <div id="gate-decision-modal" style="position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center;" onclick="if(event.target===this)this.remove()">
        <div style="background:var(--surface,#fff);border-radius:10px;padding:24px;max-width:440px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.3);">
            <div style="font-size:18px;font-weight:700;color:${titleColor};margin-bottom:12px;">${title}</div>
            ${failureHtml}
            <div style="margin-top:8px;">
                ${optionsHtml}
            </div>
            <button onclick="this.closest('#gate-decision-modal').remove()" style="margin-top:8px;width:100%;padding:8px;border:1px solid var(--border);border-radius:6px;background:transparent;cursor:pointer;color:var(--muted);">Anuluj</button>
        </div>
    </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
}


/**
 * Execute a decision chosen from the gate modal.
 */
function executeDecision(kod, akcja, wymagaKomentarza, sesjaId, etapId, sekcja) {
    let komentarz = null;
    if (wymagaKomentarza) {
        const ta = document.getElementById('decyzja-komentarz-' + kod);
        komentarz = ta ? ta.value.trim() : '';
        if (!komentarz) {
            ta.style.border = '2px solid var(--red,#dc2626)';
            ta.focus();
            return;
        }
    }

    const ebrId = window._ebrId || document.querySelector('[data-ebr-id]')?.dataset.ebrId;
    fetch(`/api/pipeline/lab/ebr/${ebrId}/etap/${etapId}/close`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sesja_id: sesjaId, decyzja: kod, komentarz: komentarz}),
    })
    .then(r => r.json())
    .then(data => {
        // Close modal
        document.getElementById('gate-decision-modal')?.remove();

        if (data.action === 'new_round') {
            // Reload batch card — new round will show inherited fields
            location.reload();
        } else if (akcja === 'next_stage' || akcja === 'skip_to_next') {
            // Advance to next stage — reload
            location.reload();
        } else if (akcja === 'release') {
            // Batch approved/released
            location.reload();
        } else if (akcja === 'close') {
            // Batch closed with note
            location.reload();
        } else {
            location.reload();
        }
    })
    .catch(err => {
        console.error('Decision error:', err);
        alert('Błąd: ' + err.message);
    });
}


/**
 * Re-evaluate gate threshold after inline edit in the failure modal.
 * Saves new limit via Global Edit, then re-evaluates gate.
 */
function reEvaluateThreshold(input, sekcja, sesjaId, etapId) {
    const newVal = parseFloat(input.value.replace(',', '.'));
    if (isNaN(newVal)) return;

    const peId = input.dataset.peId;
    const ebrId = window._ebrId || document.querySelector('[data-ebr-id]')?.dataset.ebrId;

    // 1. Update the limit via Global Edit
    if (peId) {
        fetch(`/api/pipeline/lab/parametry-etapy/${peId}`, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({max_limit: newVal}),
        }).then(r => r.json()).then(() => {
            // 2. Update etap_warunki too
            const warunkiId = input.dataset.warunkiId;
            // For now, just re-trigger gate evaluation by re-saving pomiary
            input.style.outline = '2px solid var(--green,#16a34a)';
            setTimeout(() => { input.style.outline = ''; }, 800);
        });
    }

    // 3. Re-evaluate gate — call pomiary endpoint which returns gate
    fetch(`/api/pipeline/lab/ebr/${ebrId}/etap/${etapId}/pomiary`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sesja_id: sesjaId, pomiary: []}),
    })
    .then(r => r.json())
    .then(data => {
        if (data.gate) {
            // Close old modal, show new one
            document.getElementById('gate-decision-modal')?.remove();
            const meta = window._pipelineDecyzje?.[etapId] || {};
            showGateDecisionModal(sekcja, data.gate, meta, sesjaId, etapId);
        }
    });
}
</script>
```

- [ ] **Step 2: Integrate modal into _fast_entry_content.html**

In `_fast_entry_content.html`, add the include at the top of the template (after other includes):

```html
{% include "laborant/_gate_decision_modal.html" %}
```

Replace the `renderGateBanner()` function (lines ~2825-2870) gate-pass buttons section. Instead of inline buttons for "Zatwierdź etap →", call `showGateDecisionModal()`. Modify the function body:

Find the section in `renderGateBanner()` where it renders pass buttons (around line 2840-2855). Replace the direct `closePipelineStage(sekcja)` call:

```javascript
// In renderGateBanner(), replace pass/fail button rendering with:
function renderGateBanner(sekcja, gate) {
    if (!gate) return;
    const bannerEl = document.getElementById('gate-' + sekcja)
        || document.getElementById('gate-' + sekcja.split('__')[0]);
    if (!bannerEl) return;

    // Store gate for later use
    window._lastGate = window._lastGate || {};
    window._lastGate[sekcja] = gate;

    const activeEtap = window._activePipelineStage;
    const sesjaId = activeEtap?.current_sesja_id;
    const etapId = activeEtap?.pipeline_etap_id;

    if (gate.passed) {
        bannerEl.innerHTML = `
            <div style="background:var(--green-bg,#f0fdf4);border:1px solid var(--green);border-radius:6px;padding:12px;margin:8px 0;">
                <div style="font-weight:600;color:var(--green);">✓ Bramka spełniona</div>
                <button onclick="showGateDecisionModal('${sekcja}', ${JSON.stringify(gate)}, window._pipelineDecyzje?.['${etapId}'] || {}, ${sesjaId}, ${etapId})"
                    style="margin-top:8px;padding:8px 16px;background:var(--teal);color:#fff;border:none;border-radius:6px;font-weight:600;cursor:pointer;">
                    Zatwierdź etap →
                </button>
            </div>`;
    } else {
        const reasons = gate.failures.map(f => f.kod || f.reason).join(', ');
        bannerEl.innerHTML = `
            <div style="background:var(--red-bg,#fef2f2);border:1px solid var(--red);border-radius:6px;padding:12px;margin:8px 0;">
                <div style="font-weight:600;color:var(--red);">✗ Bramka niespełniona: ${reasons}</div>
                <button onclick="showGateDecisionModal('${sekcja}', ${JSON.stringify(gate)}, window._pipelineDecyzje?.['${etapId}'] || {}, ${sesjaId}, ${etapId})"
                    style="margin-top:8px;padding:8px 16px;background:var(--amber);color:#fff;border:none;border-radius:6px;font-weight:600;cursor:pointer;">
                    Opcje decyzji…
                </button>
            </div>`;
    }
}
```

- [ ] **Step 3: Store pipeline decisions in JS context**

In `_fast_entry_content.html`, find where `etapy` JSON is loaded into JS (in the data-loading section). Add a block that fetches decision options and stores them:

```javascript
// After loading etapy data, fetch decisions for each pipeline stage
window._pipelineDecyzje = {};
(etapy || []).forEach(et => {
    if (et.pipeline_etap_id && et.decyzje_pass) {
        window._pipelineDecyzje[et.pipeline_etap_id] = {
            decyzje_pass: et.decyzje_pass || [],
            decyzje_fail: et.decyzje_fail || [],
        };
    }
});
```

This requires that `lab_get_etap_form()` response (from Task 6) includes `decyzje_pass`/`decyzje_fail` which gets passed through the etapy context.

- [ ] **Step 4: Test manually in browser**

Run: `python -m mbr.app`
Navigate to a K40GLO batch → sulfonowanie stage → enter SO₃²⁻ value above limit → verify gate banner shows "Opcje decyzji..." button → click → verify modal appears with "Nowa runda" option.

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/laborant/_gate_decision_modal.html mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: config-driven gate decision modal from etap_decyzje"
```

---

### Task 8: Frontend — inherited fields rendering

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html:297-346` (parameter rendering)

- [ ] **Step 1: Add CSS for inherited and needs-retest fields**

In `_fast_entry_content.html`, find the `<style>` section. Add:

```css
/* Inherited field from previous round */
.field-inherited input {
    background: var(--surface-alt, #f5f5f5) !important;
    color: var(--muted, #6b7280);
    font-style: italic;
    cursor: pointer;
}
.field-inherited::after {
    content: '↩';
    position: absolute;
    right: 6px;
    top: 50%;
    transform: translateY(-50%);
    font-size: 12px;
    color: var(--muted, #6b7280);
    pointer-events: none;
}
.field-inherited {
    position: relative;
}

/* Field that needs re-testing */
.needs-retest input {
    border: 2px solid var(--amber, #f59e0b) !important;
    background: #fffbeb;
}
.needs-retest input::placeholder {
    color: var(--amber);
}
```

- [ ] **Step 2: Modify field rendering to detect inherited measurements**

In the JS section where measurement fields are rendered (the section that builds `<input>` elements per parameter, around lines 297-346), add logic to check `odziedziczony` flag from pomiary:

```javascript
// When rendering a measurement field for a parameter:
function renderMeasurementField(pole, sekcja, wynikData, pomiarData) {
    const isInherited = pomiarData && pomiarData.odziedziczony === 1;
    const isEmpty = !wynikData || wynikData.wartosc == null || wynikData.wartosc === '';
    const isOutOfLimit = wynikData && wynikData.w_limicie === 0;

    let wrapperClass = '';
    let inputAttrs = '';

    if (isInherited) {
        wrapperClass = 'field-inherited';
        inputAttrs = 'readonly title="Wynik z poprzedniej rundy — kliknij aby odblokować"';
    } else if (isEmpty && !isInherited) {
        // Empty field in new round where previous was out of limit
        wrapperClass = 'needs-retest';
    }

    // ... existing input rendering, add wrapperClass to container div, inputAttrs to input element
}
```

- [ ] **Step 3: Add unlock handler for inherited fields**

```javascript
/**
 * Click on inherited (readonly) field to unlock it for re-entry.
 */
function unlockInherited(input) {
    const wrapper = input.closest('.field-inherited');
    if (!wrapper) return;
    wrapper.classList.remove('field-inherited');
    input.removeAttribute('readonly');
    input.removeAttribute('title');
    input.value = '';
    input.style.background = '';
    input.style.color = '';
    input.style.fontStyle = '';
    input.focus();

    // Mark as no longer inherited — save will send odziedziczony=0
    input.dataset.odziedziczony = '0';
}

// Attach click handler to inherited fields
document.addEventListener('click', function(e) {
    if (e.target.matches('.field-inherited input[readonly]')) {
        unlockInherited(e.target);
    }
});
```

- [ ] **Step 4: Extend doSaveField to send odziedziczony flag**

In `doSaveField()` (line ~3720), when building the POST body, include `odziedziczony`:

```javascript
// In doSaveField, extend values object:
const isInherited = input.dataset.odziedziczony === '0' ? 0
    : (input.closest('.field-inherited') ? 1 : 0);

// POST body values[kod] should include:
values[kod] = {wartosc: val, komentarz: comment, odziedziczony: isInherited};
```

- [ ] **Step 5: Test manually in browser**

Run dev server. Create a K40GLO batch → sulfonowanie → enter values → fail gate → choose "Nowa runda" → verify:
- OK values appear as grey/italic readonly fields with ↩ icon
- Failed values appear as empty fields with amber border
- Clicking inherited field unlocks it

- [ ] **Step 6: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: inherited field rendering with unlock + needs-retest styling"
```

---

### Task 9: Frontend — editable spec panel (Global Edit)

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html:3690-3718,4371-4400`

- [ ] **Step 1: Extend updateSpecPanel() for full editable limits**

The current `updateSpecPanel()` (line ~4371) renders spec_value as an editable input with `saveSpec()`. Extend it to also show min/max limits as editable inputs:

```javascript
function updateSpecPanel() {
    const stage = window._activePipelineStage;
    if (!stage || !stage.parametry) { return; }

    const body = document.getElementById('spec-body');
    if (!body) return;

    let html = '<table style="width:100%;border-collapse:collapse;">';
    html += '<tr style="font-size:11px;color:var(--muted);border-bottom:1px solid var(--border);">';
    html += '<th style="text-align:left;padding:4px;">Parametr</th>';
    html += '<th style="text-align:center;padding:4px;">Min</th>';
    html += '<th style="text-align:center;padding:4px;">Max</th>';
    html += '<th style="text-align:center;padding:4px;">Cel</th>';
    html += '</tr>';

    (stage.parametry || []).forEach(p => {
        if (p.min_limit == null && p.max_limit == null && p.spec_value == null) return;

        html += `<tr style="border-bottom:1px solid var(--border-light,#f0f0f0);">`;
        html += `<td style="padding:4px;font-size:13px;">${p.skrot || p.label || p.kod}</td>`;

        // Min limit — editable
        html += `<td style="text-align:center;padding:4px;">`;
        if (p.min_limit != null) {
            html += `<input type="text" inputmode="decimal" value="${p.min_limit}"
                data-pe-id="${p.pe_id || ''}" data-field="min_limit" data-kod="${p.kod}"
                style="width:55px;text-align:center;border:1px solid transparent;border-radius:3px;font-family:var(--mono);font-size:13px;padding:2px;"
                onfocus="this.style.borderColor='var(--border)'"
                onblur="this.style.borderColor='transparent';saveSpecLimit(this)" />`;
        }
        html += `</td>`;

        // Max limit — editable
        html += `<td style="text-align:center;padding:4px;">`;
        if (p.max_limit != null) {
            html += `<input type="text" inputmode="decimal" value="${p.max_limit}"
                data-pe-id="${p.pe_id || ''}" data-field="max_limit" data-kod="${p.kod}"
                style="width:55px;text-align:center;border:1px solid transparent;border-radius:3px;font-family:var(--mono);font-size:13px;padding:2px;"
                onfocus="this.style.borderColor='var(--border)'"
                onblur="this.style.borderColor='transparent';saveSpecLimit(this)" />`;
        }
        html += `</td>`;

        // Target — editable (existing saveSpec behavior)
        html += `<td style="text-align:center;padding:4px;">`;
        if (p.spec_value != null) {
            html += `<input type="text" inputmode="decimal" value="${p.spec_value}"
                data-pe-id="${p.pe_id || ''}" data-field="target" data-kod="${p.kod}"
                style="width:55px;text-align:center;border:1px solid transparent;border-radius:3px;font-family:var(--mono);font-size:13px;font-weight:700;color:var(--teal);padding:2px;"
                onfocus="this.style.borderColor='var(--border)'"
                onblur="this.style.borderColor='transparent';saveSpecLimit(this)" />`;
        }
        html += `</td>`;

        html += `</tr>`;
    });

    html += '</table>';
    body.innerHTML = html;
}
```

- [ ] **Step 2: Implement saveSpecLimit() using Global Edit endpoint**

Replace `saveSpec()` (lines ~3690-3718) with a generic `saveSpecLimit()`:

```javascript
/**
 * Save a spec field (min_limit, max_limit, target, formula) via Global Edit.
 */
function saveSpecLimit(input) {
    const peId = input.dataset.peId;
    const field = input.dataset.field;  // 'min_limit', 'max_limit', 'target'
    const val = parseFloat(input.value.replace(',', '.'));

    if (!peId || isNaN(val)) return;

    fetch(`/api/pipeline/lab/parametry-etapy/${peId}`, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({[field]: val}),
    })
    .then(r => r.json())
    .then(data => {
        if (data.ok) {
            input.style.outline = '2px solid var(--green,#16a34a)';
            setTimeout(() => { input.style.outline = ''; }, 800);

            // Update local parametry data so re-evaluations use new limits
            const stage = window._activePipelineStage;
            if (stage && stage.parametry) {
                const p = stage.parametry.find(x => x.kod === input.dataset.kod);
                if (p) p[field] = val;
            }
        } else {
            input.style.outline = '2px solid var(--red,#dc2626)';
            setTimeout(() => { input.style.outline = ''; }, 2000);
        }
    })
    .catch(() => {
        input.style.outline = '2px solid var(--red,#dc2626)';
        setTimeout(() => { input.style.outline = ''; }, 2000);
    });
}
```

- [ ] **Step 3: Ensure pe_id is passed through parametry context**

In `mbr/pipeline/models.py`, `resolve_limity()` (line ~742) returns parameter dicts. Verify it includes the `parametry_etapy.id` as `pe_id`. If not, add it to the SELECT:

```sql
SELECT pe.id as pe_id, pa.id as parametr_id, pa.kod, ...
```

And include `pe_id` in the returned dict.

- [ ] **Step 4: Test manually**

Run dev server → open K40GLO batch → check right panel "Specyfikacja" → verify min/max/target are editable inputs → change a value → verify green flash + value persists on reload.

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html mbr/pipeline/models.py
git commit -m "feat: editable spec panel — Global Edit for min/max/target limits"
```

---

### Task 10: Frontend — correction panels

**Files:**
- Create: `mbr/templates/laborant/_correction_panel.html`
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Create correction panel partial**

Create `mbr/templates/laborant/_correction_panel.html`:

```html
{# _correction_panel.html — Reusable correction auto-calc panel #}
{# Rendered client-side by JS. Two variants: perhydrol (etap1→2) and standaryzacja (etap2→3) #}

<script>
/**
 * Render a correction panel inside a gate-pass banner.
 * @param {string} panelType - 'perhydrol' or 'standaryzacja'
 * @param {string} sekcja - Section key
 * @param {object} context - {masa_szarzy, wynik_so3, wynik_sm, wynik_nacl, ...}
 */
function renderCorrectionPanel(panelType, sekcja, context) {
    const container = document.getElementById('correction-panel-' + sekcja);
    if (!container) return;

    if (panelType === 'perhydrol') {
        renderPerhydrolPanel(container, sekcja, context);
    } else if (panelType === 'standaryzacja') {
        renderStandaryzacjaPanel(container, sekcja, context);
    }
}

function renderPerhydrolPanel(container, sekcja, ctx) {
    container.innerHTML = `
    <div style="background:var(--blue-bg,#eff6ff);border:1px solid var(--blue,#3b82f6);border-radius:8px;padding:16px;margin:8px 0;">
        <div style="font-weight:700;margin-bottom:10px;">Korekta utleniania — dawka perhydrolu</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px;">
            <label style="font-size:12px;">
                SO₃²⁻ wynik [%]
                <input type="text" id="corr-so3-wynik" value="${ctx.wynik_so3 || ''}" readonly
                    style="width:100%;border:1px solid var(--border);border-radius:4px;padding:4px;font-family:var(--mono);background:var(--surface-alt);" />
            </label>
            <label style="font-size:12px;">
                SO₃²⁻ cel [%]
                <input type="text" id="corr-so3-target" value="${ctx.target_so3 || ''}" inputmode="decimal"
                    oninput="recomputePerhydrol()"
                    style="width:100%;border:1px solid var(--border);border-radius:4px;padding:4px;font-family:var(--mono);" />
            </label>
            <label style="font-size:12px;">
                Masa szarży [kg]
                <input type="text" id="corr-masa" value="${ctx.masa_szarzy || ''}" inputmode="decimal"
                    oninput="recomputePerhydrol()"
                    style="width:100%;border:1px solid var(--border);border-radius:4px;padding:4px;font-family:var(--mono);" />
            </label>
            <label style="font-size:12px;">
                Współczynnik
                <input type="text" id="corr-wspolczynnik" value="${ctx.wspolczynnik || '1.0'}" inputmode="decimal"
                    oninput="recomputePerhydrol()"
                    style="width:100%;border:1px solid var(--border);border-radius:4px;padding:4px;font-family:var(--mono);" />
                <span style="font-size:10px;color:var(--muted);">Edycja = zapis globalny</span>
            </label>
        </div>
        <div style="background:var(--surface);border-radius:6px;padding:12px;text-align:center;">
            <div style="font-size:12px;color:var(--muted);">Dawka perhydrolu</div>
            <div id="corr-perhydrol-result" style="font-size:24px;font-weight:700;font-family:var(--mono);color:var(--teal);">— kg</div>
        </div>
    </div>`;
    recomputePerhydrol();
}


function recomputePerhydrol() {
    const so3 = parseFloat((document.getElementById('corr-so3-wynik')?.value || '').replace(',', '.'));
    const target = parseFloat((document.getElementById('corr-so3-target')?.value || '').replace(',', '.'));
    const masa = parseFloat((document.getElementById('corr-masa')?.value || '').replace(',', '.'));
    const wsp = parseFloat((document.getElementById('corr-wspolczynnik')?.value || '1').replace(',', '.'));

    const result = document.getElementById('corr-perhydrol-result');
    if (isNaN(so3) || isNaN(target) || isNaN(masa) || isNaN(wsp)) {
        if (result) result.textContent = '— kg';
        return;
    }

    const dawka = (target - so3) * masa * wsp;
    if (result) result.textContent = dawka.toFixed(2).replace('.', ',') + ' kg';
}


function renderStandaryzacjaPanel(container, sekcja, ctx) {
    container.innerHTML = `
    <div style="background:var(--blue-bg,#eff6ff);border:1px solid var(--blue,#3b82f6);border-radius:8px;padding:16px;margin:8px 0;">
        <div style="font-weight:700;margin-bottom:10px;">Korekta standaryzująca — woda + NaCl</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px;">
            <label style="font-size:12px;">
                SM wynik [%]
                <input type="text" id="corr-sm-wynik" value="${ctx.wynik_sm || ''}" readonly
                    style="width:100%;border:1px solid var(--border);border-radius:4px;padding:4px;font-family:var(--mono);background:var(--surface-alt);" />
            </label>
            <label style="font-size:12px;">
                SM cel [%]
                <input type="text" id="corr-sm-target" value="${ctx.target_sm || ''}" inputmode="decimal"
                    oninput="recomputeStandaryzacja()"
                    style="width:100%;border:1px solid var(--border);border-radius:4px;padding:4px;font-family:var(--mono);" />
            </label>
            <label style="font-size:12px;">
                NaCl wynik [%]
                <input type="text" id="corr-nacl-wynik" value="${ctx.wynik_nacl || ''}" readonly
                    style="width:100%;border:1px solid var(--border);border-radius:4px;padding:4px;font-family:var(--mono);background:var(--surface-alt);" />
            </label>
            <label style="font-size:12px;">
                NaCl cel [%]
                <input type="text" id="corr-nacl-target" value="${ctx.target_nacl || ''}" inputmode="decimal"
                    oninput="recomputeStandaryzacja()"
                    style="width:100%;border:1px solid var(--border);border-radius:4px;padding:4px;font-family:var(--mono);" />
            </label>
            <label style="font-size:12px;">
                Masa [kg]
                <input type="text" id="corr-std-masa" value="${ctx.masa_szarzy || ''}" inputmode="decimal"
                    oninput="recomputeStandaryzacja()"
                    style="width:100%;border:1px solid var(--border);border-radius:4px;padding:4px;font-family:var(--mono);" />
            </label>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            <div style="background:var(--surface);border-radius:6px;padding:12px;text-align:center;">
                <div style="font-size:12px;color:var(--muted);">Dawka wody</div>
                <div id="corr-woda-result" style="font-size:20px;font-weight:700;font-family:var(--mono);color:var(--teal);">— kg</div>
            </div>
            <div style="background:var(--surface);border-radius:6px;padding:12px;text-align:center;">
                <div style="font-size:12px;color:var(--muted);">Dawka NaCl</div>
                <div id="corr-nacl-result" style="font-size:20px;font-weight:700;font-family:var(--mono);color:var(--teal);">— kg</div>
            </div>
        </div>
    </div>`;
    recomputeStandaryzacja();
}


function recomputeStandaryzacja() {
    const smWynik = parseFloat((document.getElementById('corr-sm-wynik')?.value || '').replace(',', '.'));
    const smTarget = parseFloat((document.getElementById('corr-sm-target')?.value || '').replace(',', '.'));
    const naclWynik = parseFloat((document.getElementById('corr-nacl-wynik')?.value || '').replace(',', '.'));
    const naclTarget = parseFloat((document.getElementById('corr-nacl-target')?.value || '').replace(',', '.'));
    const masa = parseFloat((document.getElementById('corr-std-masa')?.value || '').replace(',', '.'));

    const wodaResult = document.getElementById('corr-woda-result');
    const naclResult = document.getElementById('corr-nacl-result');

    // woda_kg = masa * (1 - target_sm / wynik_sm)
    if (!isNaN(smWynik) && !isNaN(smTarget) && !isNaN(masa) && smWynik > 0) {
        const woda = masa * (1 - smTarget / smWynik);
        if (wodaResult) wodaResult.textContent = woda.toFixed(2).replace('.', ',') + ' kg';
    } else {
        if (wodaResult) wodaResult.textContent = '— kg';
    }

    // nacl_kg = masa * (target_nacl - wynik_nacl) / 100
    if (!isNaN(naclWynik) && !isNaN(naclTarget) && !isNaN(masa)) {
        const nacl = masa * (naclTarget - naclWynik) / 100;
        if (naclResult) naclResult.textContent = nacl.toFixed(2).replace('.', ',') + ' kg';
    } else {
        if (naclResult) naclResult.textContent = '— kg';
    }
}
</script>
```

- [ ] **Step 2: Integrate correction panels into gate banner flow**

In `_fast_entry_content.html`, modify `renderGateBanner()` to show correction panels when gate passes on sulfonowanie/utlenianie:

```javascript
// Inside renderGateBanner(), after rendering pass banner, add correction panel trigger:
if (gate.passed) {
    const etapKod = activeEtap?.kod || '';

    // Insert correction panel container
    bannerEl.insertAdjacentHTML('afterend',
        `<div id="correction-panel-${sekcja}"></div>`);

    // Auto-render correction panel based on stage
    if (etapKod === 'sulfonowanie') {
        const ctx = {
            wynik_so3: window.wyniki?.[sekcja]?.['so3']?.wartosc,
            target_so3: activeEtap?.parametry?.find(p => p.kod === 'so3')?.spec_value,
            masa_szarzy: window._batchMeta?.wielkosc_szarzy_kg,
            wspolczynnik: '1.0',  // from formula config
        };
        renderCorrectionPanel('perhydrol', sekcja, ctx);
    } else if (etapKod === 'utlenienie') {
        const ctx = {
            wynik_sm: window.wyniki?.[sekcja]?.['sm']?.wartosc,
            target_sm: activeEtap?.parametry?.find(p => p.kod === 'sm')?.spec_value,
            wynik_nacl: window.wyniki?.[sekcja]?.['nacl']?.wartosc,
            target_nacl: activeEtap?.parametry?.find(p => p.kod === 'nacl')?.spec_value,
            masa_szarzy: window._batchMeta?.wielkosc_szarzy_kg,
        };
        renderCorrectionPanel('standaryzacja', sekcja, ctx);
    }
}
```

- [ ] **Step 3: Include the partial in _fast_entry_content.html**

Add near the top with other includes:
```html
{% include "laborant/_correction_panel.html" %}
```

- [ ] **Step 4: Test manually**

Run dev server → K40GLO batch → sulfonowanie → enter SO₃ within limit → verify perhydrol panel appears with auto-calculated dose. Change współczynnik → verify recalculation.

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/laborant/_correction_panel.html mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: correction panels — perhydrol + standaryzacja auto-calc"
```

---

### Task 11: Integration — wire up etap_decyzje context through pipeline adapter

**Files:**
- Modify: `mbr/pipeline/adapter.py:192-300`
- Modify: `mbr/laborant/routes.py:250-310`

- [ ] **Step 1: Extend build_pipeline_context to include decision options**

In `mbr/pipeline/adapter.py`, modify `build_pipeline_context()` to fetch and attach `decyzje_pass`/`decyzje_fail` per stage:

```python
# Inside build_pipeline_context(), after building etapy_json list:
from mbr.pipeline.models import get_etap_decyzje

for et in etapy_json:
    pp_id = et.get("pp_id")  # produkt_pipeline.id
    if pp_id:
        et["decyzje_pass"] = get_etap_decyzje(db, pp_id, "pass")
        et["decyzje_fail"] = get_etap_decyzje(db, pp_id, "fail")
```

Ensure `pp_id` (produkt_pipeline.id) is included in each etap dict. Check if it's already there as `pipeline_etap_id` or similar — if not, add it to the SELECT that builds etapy_json.

- [ ] **Step 2: Extend pipeline_dual_write to handle odziedziczony**

In `mbr/pipeline/adapter.py`, `pipeline_dual_write()` calls `save_pomiar()`. If the frontend sends `odziedziczony` flag, pass it through. Modify the call to `save_pomiar()`:

Currently `save_pomiar()` doesn't accept `odziedziczony`. Add it as an optional parameter in `mbr/pipeline/models.py`:

```python
def save_pomiar(
    db: sqlite3.Connection,
    sesja_id: int,
    parametr_id: int,
    wartosc: float | None,
    min_limit: float | None,
    max_limit: float | None,
    wpisal: str,
    is_manual: int = 1,
    odziedziczony: int = 0,
) -> int:
```

Update the INSERT to include `odziedziczony`:
```sql
INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, min_limit, max_limit,
                        w_limicie, is_manual, dt_wpisu, wpisal, odziedziczony)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

And the ON CONFLICT UPDATE to also set `odziedziczony`:
```sql
ON CONFLICT(sesja_id, parametr_id) DO UPDATE SET
    wartosc = excluded.wartosc, ..., odziedziczony = excluded.odziedziczony
```

- [ ] **Step 3: Verify save endpoint passes odziedziczony from request**

In `mbr/laborant/routes.py`, the `save_entry()` route (line ~234) extracts `values` dict. Check that `pipeline_dual_write()` passes through the `odziedziczony` flag from the request body when calling `save_pomiar()`.

- [ ] **Step 4: Run all tests**

Run: `pytest tests/ -v --tb=short`
Expected: All PASS (existing + new)

- [ ] **Step 5: Commit**

```bash
git add mbr/pipeline/adapter.py mbr/pipeline/models.py mbr/laborant/routes.py
git commit -m "feat: wire etap_decyzje through adapter + odziedziczony in save_pomiar"
```

---

### Task 12: End-to-end smoke test

**Files:**
- Test: `tests/test_batch_card_v2.py`

- [ ] **Step 1: Write E2E test for full sulfonowanie→utlenianie flow**

Add to `tests/test_batch_card_v2.py`:

```python
def test_full_pipeline_flow_sulfonowanie_to_utlenianie(db):
    """E2E: sulfonowanie fail → new_round with inheritance → pass → close."""
    from mbr.pipeline.models import (
        create_sesja, save_pomiar, evaluate_gate, close_sesja,
        create_round_with_inheritance, get_pomiary,
    )

    # Setup: add gate condition SO₃ <= 0.1 for etap 10 (sulfonowanie)
    db.execute(
        "INSERT INTO etap_warunki (etap_id, parametr_id, operator, wartosc) VALUES (10, 1, '<=', 0.1)"
    )
    db.commit()

    # Round 1: SO₃ = 0.15 (FAIL), pH = 7.2 (OK)
    s1 = create_sesja(db, ebr_id=1, etap_id=10, runda=1)
    db.execute("UPDATE ebr_etap_sesja SET status = 'w_trakcie' WHERE id = ?", (s1,))
    save_pomiar(db, s1, 1, 0.15, None, 0.1, "lab")  # so3 FAIL
    save_pomiar(db, s1, 2, 7.2, 6.0, 8.0, "lab")    # ph OK

    gate = evaluate_gate(db, etap_id=10, sesja_id=s1)
    assert gate["passed"] is False
    assert len(gate["failures"]) == 1
    assert gate["failures"][0]["kod"] == "so3"

    # Decision: new_round
    close_sesja(db, s1, decyzja="new_round")

    # Round 2: inherited
    s2 = create_round_with_inheritance(db, 1, 10, s1, "lab")
    pomiary2 = {p["parametr_id"]: p for p in get_pomiary(db, s2)}

    # pH inherited
    assert pomiary2[2]["odziedziczony"] == 1
    # so3 NOT inherited
    assert 1 not in pomiary2

    # Lab re-enters so3 = 0.05 (now OK)
    save_pomiar(db, s2, 1, 0.05, None, 0.1, "lab")
    db.execute("UPDATE ebr_etap_sesja SET status = 'w_trakcie' WHERE id = ?", (s2,))

    gate2 = evaluate_gate(db, etap_id=10, sesja_id=s2)
    assert gate2["passed"] is True

    # Close with pass → przejscie
    close_sesja(db, s2, decyzja="przejscie")
    row = db.execute("SELECT * FROM ebr_etap_sesja WHERE id = ?", (s2,)).fetchone()
    assert row["status"] == "zamkniety"
    assert row["decyzja"] == "przejscie"
```

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/test_batch_card_v2.py -v`
Expected: All PASS

- [ ] **Step 3: Run complete test suite for regression**

Run: `pytest tests/ -v --tb=short`
Expected: No regressions

- [ ] **Step 4: Commit**

```bash
git add tests/test_batch_card_v2.py
git commit -m "test: E2E smoke test for sulfonowanie pipeline with inheritance"
```

---

### Task 13: Manual QA in browser

- [ ] **Step 1: Start dev server**

Run: `python -m mbr.app`

- [ ] **Step 2: Test sulfonowanie flow**

1. Create new K40GLO batch
2. Navigate to sulfonowanie stage
3. Enter SO₃²⁻ above limit (e.g., 0.15)
4. Verify gate banner shows "Bramka niespełniona" with "Opcje decyzji..." button
5. Click → verify modal shows "Nowa runda" option
6. Click "Nowa runda" → verify page reloads with:
   - OK fields inherited (grey, readonly, ↩ icon)
   - Failed fields empty with amber border
7. Enter new SO₃²⁻ = 0.05 → verify gate passes
8. Click "Zatwierdź etap →" → verify modal shows "Przejdź do utleniania"
9. Verify perhydrol correction panel appears with auto-calc

- [ ] **Step 3: Test Global Edit**

1. In right panel "Specyfikacja", change SO₃²⁻ max limit from 0.1 to 0.2
2. Verify green flash on blur
3. Reload page → verify new limit persists
4. Create another batch → verify new limit is applied

- [ ] **Step 4: Test standaryzacja exit scenarios**

1. Navigate to standaryzacja stage
2. Enter parameters outside limits
3. Verify modal shows 3 options: "Kolejna runda", "Zwolnij z komentarzem", "Zamknij z notatką"
4. Choose "Zwolnij z komentarzem" → verify textarea required → enter text → verify batch status changes

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: Batch Card V2 — complete implementation"
```
