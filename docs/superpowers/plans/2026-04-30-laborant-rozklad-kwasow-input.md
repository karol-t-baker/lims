# Laborant input — rozkład kwasów tłuszczowych Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pozwolić laborantowi wpisać 9 wartości rozkładu łańcuchów C6–C18 w jednym wierszu fast-entry (grid 3×3) zamiast pustego dropdownu, tak żeby świadectwo Avon dla Monamid_KO miało prawidłową kolumnę Wynik.

**Architecture:** Hardcoded special-case w `_fast_entry_content.html` dla `kod === 'cert_qual_rozklad_kwasow'`. 9 wartości joinowane przez `|` zapisywane jako jeden `wartosc_text`. Cert renderer już renderuje `|` jako line break (commit d17a08f). Plus jednorazowa migracja danych (clear stale seed, change grupa to 'zewn') i fix latent bug w backend `w_limicie` semantics.

**Tech Stack:** Flask + Jinja2 + vanilla JS (no framework), SQLite, pytest. No new dependencies.

---

## File Structure

```
mbr/laborant/models.py                              [MODIFY] line 694: w_limicie semantics fix
mbr/templates/laborant/_fast_entry_content.html     [MODIFY] new render branch + save/load handlers
scripts/migrate_rozklad_kwasow_seed.py              [CREATE] one-shot idempotent migration
deploy/auto-deploy.sh                               [MODIFY] register migration script
tests/test_jakosciowy_w_limicie.py                  [CREATE] regression tests for w_limicie fix
tests/test_laborant_rozklad_kwasow.py               [CREATE] template smoke + roundtrip + cert
tests/test_migrate_rozklad_kwasow_seed.py           [CREATE] migration script idempotence
```

---

## Task 1: Migration script — clear stale seed + grupa change

**Files:**
- Create: `scripts/migrate_rozklad_kwasow_seed.py`
- Test: `tests/test_migrate_rozklad_kwasow_seed.py`

**Pattern reference:** `scripts/migrate_audit_log_v2.py` (argparse, --dry-run, idempotent guards).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migrate_rozklad_kwasow_seed.py
"""Migration: clear stale cert_qualitative_result + flip grupa to 'zewn'
+ purge old single-value ebr_wyniki rows for cert_qual_rozklad_kwasow."""

import sqlite3
import pytest
from mbr.models import init_mbr_tables
from scripts.migrate_rozklad_kwasow_seed import run_migration


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed_baseline(db):
    """Insert parametry_analityczne(id=59) + 2 parametry_etapy rows in
    pre-migration state (grupa='lab', cert_qualitative_result='≤1,0')."""
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, grupa, precision) "
        "VALUES (59, 'cert_qual_rozklad_kwasow', 'Rozkład kwasów', 'jakosciowy', 'lab', 2)"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('Monamid_KO', 'Monamid KO')")
    db.execute(
        "INSERT INTO parametry_etapy (id, produkt, kontekst, parametr_id, grupa, "
        "cert_qualitative_result) VALUES (472, 'Monamid_KO', 'analiza_koncowa', 59, 'lab', '≤1,0')"
    )
    db.execute(
        "INSERT INTO parametry_etapy (id, produkt, kontekst, parametr_id, grupa, "
        "cert_qualitative_result) VALUES (613, 'Monamid_KO', 'cert_variant', 59, 'lab', NULL)"
    )
    db.commit()


def test_migration_applies_all_four_changes(db):
    _seed_baseline(db)
    # Insert orphan ebr_wyniki row with stale seed
    db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start) "
        "VALUES (1, 'b1', '1/26', '2026-01-01T00:00:00')"
    )
    db.execute(
        "INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc_text, "
        "is_manual, dt_wpisu, wpisal) "
        "VALUES (1, 'analiza_koncowa', 'cert_qual_rozklad_kwasow', 'tag', '≤1,0', "
        "0, '2026-01-01T00:00:00', 'op')"
    )
    db.commit()

    counts = run_migration(db)

    # 1. parametry_etapy.cert_qualitative_result cleared (only the '≤1,0' one)
    rows = db.execute(
        "SELECT cert_qualitative_result FROM parametry_etapy WHERE parametr_id=59"
    ).fetchall()
    assert all(r["cert_qualitative_result"] is None for r in rows)

    # 2. parametry_analityczne.grupa flipped lab → zewn
    pa = db.execute("SELECT grupa FROM parametry_analityczne WHERE id=59").fetchone()
    assert pa["grupa"] == "zewn"

    # 3. parametry_etapy.grupa flipped lab → zewn (both rows)
    pe = db.execute("SELECT grupa FROM parametry_etapy WHERE parametr_id=59").fetchall()
    assert all(r["grupa"] == "zewn" for r in pe)

    # 4. Orphan ebr_wyniki row deleted
    n = db.execute(
        "SELECT COUNT(*) FROM ebr_wyniki WHERE kod_parametru='cert_qual_rozklad_kwasow'"
    ).fetchone()[0]
    assert n == 0

    # Counter dict reports work done
    assert counts == {"cert_qr_cleared": 1, "pa_grupa": 1, "pe_grupa": 2, "ebr_purged": 1}


def test_migration_is_idempotent(db):
    _seed_baseline(db)
    run_migration(db)  # first run
    counts = run_migration(db)  # second run
    # All counts should be 0 — nothing to do
    assert counts == {"cert_qr_cleared": 0, "pa_grupa": 0, "pe_grupa": 0, "ebr_purged": 0}


def test_migration_preserves_filled_ebr_wyniki(db):
    """ebr_wyniki rows with pipe-separated wartosc_text (laborant-filled)
    must NOT be deleted, even if they reference our kod_parametru."""
    _seed_baseline(db)
    db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start) "
        "VALUES (1, 'b1', '1/26', '2026-01-01T00:00:00')"
    )
    db.execute(
        "INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc_text, "
        "is_manual, dt_wpisu, wpisal) "
        "VALUES (1, 'analiza_koncowa', 'cert_qual_rozklad_kwasow', 'tag', "
        "'<1|45|22|18|10|3|1|0|0', 1, '2026-01-01T00:00:00', 'op')"
    )
    db.commit()

    run_migration(db)

    n = db.execute(
        "SELECT COUNT(*) FROM ebr_wyniki WHERE kod_parametru='cert_qual_rozklad_kwasow'"
    ).fetchone()[0]
    assert n == 1  # preserved


def test_migration_preserves_unrelated_etap_seed(db):
    """If parametry_etapy.cert_qualitative_result has a non-'≤1,0' value, leave it alone."""
    _seed_baseline(db)
    # Replace one row's seed with something else
    db.execute(
        "UPDATE parametry_etapy SET cert_qualitative_result='custom value' WHERE id=472"
    )
    db.commit()

    run_migration(db)

    row = db.execute(
        "SELECT cert_qualitative_result FROM parametry_etapy WHERE id=472"
    ).fetchone()
    assert row["cert_qualitative_result"] == "custom value"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_migrate_rozklad_kwasow_seed.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.migrate_rozklad_kwasow_seed'`

- [ ] **Step 3: Implement the migration script**

```python
# scripts/migrate_rozklad_kwasow_seed.py
"""
migrate_rozklad_kwasow_seed.py — one-shot migration for parametr 59
(cert_qual_rozklad_kwasow / Rozkład kwasów tłuszczowych).

Performs four idempotent operations:

  1. Clear stale parametry_etapy.cert_qualitative_result='≤1,0' (relict of
     the old single-value jakosciowy semantics — now obsolete since the
     parameter became a 9-chain composite).
  2. Flip parametry_analityczne.grupa from 'lab' to 'zewn' (semantic
     correction — values come from external lab certificates).
  3. Flip parametry_etapy.grupa from 'lab' to 'zewn' for all rows
     referencing parametr_id=59.
  4. Purge ebr_wyniki rows where wartosc_text='≤1,0' AND wartosc_text NOT
     LIKE '%|%' (= seed-only rows, never edited by laborant). Pipe-bearing
     rows are LEFT UNTOUCHED.

Idempotent: each operation has a guard such that re-running yields zero
mutations after the first successful application.

Usage:
    python scripts/migrate_rozklad_kwasow_seed.py --db data/batch_db.sqlite [--dry-run]
"""

import argparse
import sqlite3
import sys
from pathlib import Path


PARAMETR_ID = 59
KOD = "cert_qual_rozklad_kwasow"
SEED_VALUE = "≤1,0"


def run_migration(db: sqlite3.Connection) -> dict:
    """Apply the four migration operations. Returns counters dict."""
    counts = {"cert_qr_cleared": 0, "pa_grupa": 0, "pe_grupa": 0, "ebr_purged": 0}

    cur = db.execute(
        "UPDATE parametry_etapy SET cert_qualitative_result=NULL "
        "WHERE parametr_id=? AND cert_qualitative_result=?",
        (PARAMETR_ID, SEED_VALUE),
    )
    counts["cert_qr_cleared"] = cur.rowcount

    cur = db.execute(
        "UPDATE parametry_analityczne SET grupa='zewn' "
        "WHERE id=? AND grupa='lab'",
        (PARAMETR_ID,),
    )
    counts["pa_grupa"] = cur.rowcount

    cur = db.execute(
        "UPDATE parametry_etapy SET grupa='zewn' "
        "WHERE parametr_id=? AND grupa='lab'",
        (PARAMETR_ID,),
    )
    counts["pe_grupa"] = cur.rowcount

    cur = db.execute(
        "DELETE FROM ebr_wyniki "
        "WHERE kod_parametru=? AND wartosc_text=? AND wartosc_text NOT LIKE '%|%'",
        (KOD, SEED_VALUE),
    )
    counts["ebr_purged"] = cur.rowcount

    db.commit()
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Path to batch_db.sqlite")
    parser.add_argument("--dry-run", action="store_true", help="Report counts but rollback")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: DB not found: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        counts = run_migration(conn)
        if args.dry_run:
            conn.rollback()
            print("DRY-RUN — no changes committed.")
        print(
            f"cert_qr_cleared={counts['cert_qr_cleared']}, "
            f"pa_grupa={counts['pa_grupa']}, "
            f"pe_grupa={counts['pe_grupa']}, "
            f"ebr_purged={counts['ebr_purged']}"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_migrate_rozklad_kwasow_seed.py -v`
Expected: 4 PASS

- [ ] **Step 5: Run migration on local DB**

Run: `python scripts/migrate_rozklad_kwasow_seed.py --db data/batch_db.sqlite --dry-run`
Expected output: counters showing what would change (might be 0,0,0,0 if local already in target state)

Run for real: `python scripts/migrate_rozklad_kwasow_seed.py --db data/batch_db.sqlite`
Expected: counters reflecting actual changes; idempotent on second run.

- [ ] **Step 6: Commit**

```bash
git add scripts/migrate_rozklad_kwasow_seed.py tests/test_migrate_rozklad_kwasow_seed.py
git commit -m "feat(migration): clear stale rozkład kwasów seed + flip grupa to zewn"
```

---

## Task 2: Backend `w_limicie` semantics fix

**Files:**
- Modify: `mbr/laborant/models.py:694` (one-line change inside `save_wyniki`)
- Test: `tests/test_jakosciowy_w_limicie.py`

**Why:** Currently `w_limicie_val = 1 if text_val in allowed else 0` returns `0` whenever `opisowe_wartosci` is empty/NULL — this falsely flags qualitative params as "out of spec" upon manual save. Latent bug that surfaces once we wire the rozkład grid.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_jakosciowy_w_limicie.py
"""Backend regression: jakosciowy w_limicie should be NULL when
opisowe_wartosci is empty/NULL (no spec list = neutral, not 'out of spec')."""

import json
import sqlite3
import pytest

from mbr.models import init_mbr_tables
from mbr.laborant.models import save_wyniki


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed_jakosciowy_param(db, kod, opisowe_wartosci):
    """Returns (parametr_id, ebr_id) ready for save_wyniki call."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision, "
        "opisowe_wartosci) VALUES (?, ?, 'jakosciowy', 'lab', 0, ?)",
        (kod, kod.capitalize(), opisowe_wartosci),
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('P', 'P')")
    db.execute(
        "INSERT INTO mbr_templates (mbr_id, produkt, wersja, aktywna, "
        "etapy_json, parametry_lab) VALUES (1, 'P', 1, 1, '[]', '{}')"
    )
    db.execute(
        "INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start) "
        "VALUES (1, 1, 'P_b1', '1/26', '2026-01-01T00:00:00')"
    )
    db.commit()
    return 1  # ebr_id


def test_w_limicie_null_when_opisowe_wartosci_empty(db):
    """When parametry_analityczne.opisowe_wartosci is NULL, an explicit
    wartosc_text save must produce w_limicie=NULL (not 0)."""
    ebr_id = _seed_jakosciowy_param(db, "test_kod", None)

    save_wyniki(
        db, ebr_id=ebr_id, sekcja="analiza",
        values={"test_kod": {"wartosc_text": "<1|45|22"}},
        user="op",
    )

    row = db.execute(
        "SELECT w_limicie, wartosc_text FROM ebr_wyniki WHERE kod_parametru='test_kod'"
    ).fetchone()
    assert row["wartosc_text"] == "<1|45|22"
    assert row["w_limicie"] is None  # neutral — no spec to validate against


def test_w_limicie_set_when_opisowe_wartosci_present(db):
    """Existing semantics preserved: with a defined opisowe_wartosci list,
    in-list value → w_limicie=1, out-of-list → w_limicie=0."""
    ebr_id = _seed_jakosciowy_param(db, "test_kod", json.dumps(["OK", "nieOK"]))

    save_wyniki(
        db, ebr_id=ebr_id, sekcja="analiza",
        values={"test_kod": {"wartosc_text": "OK"}},
        user="op",
    )

    row = db.execute(
        "SELECT w_limicie FROM ebr_wyniki WHERE kod_parametru='test_kod'"
    ).fetchone()
    assert row["w_limicie"] == 1

    save_wyniki(
        db, ebr_id=ebr_id, sekcja="analiza",
        values={"test_kod": {"wartosc_text": "nieZdefiniowane"}},
        user="op",
    )

    row = db.execute(
        "SELECT w_limicie FROM ebr_wyniki WHERE kod_parametru='test_kod'"
    ).fetchone()
    assert row["w_limicie"] == 0
```

- [ ] **Step 2: Verify the first test fails (current backend bug)**

Run: `pytest tests/test_jakosciowy_w_limicie.py::test_w_limicie_null_when_opisowe_wartosci_empty -v`
Expected: FAIL — `assert 0 is None` (current code returns 0 when allowed=[]).

The second test should already pass against the current code.

Run: `pytest tests/test_jakosciowy_w_limicie.py::test_w_limicie_set_when_opisowe_wartosci_present -v`
Expected: PASS.

- [ ] **Step 3: Fix backend**

Edit `mbr/laborant/models.py` around line 694. Locate the block:

```python
            allowed = []
            if meta and meta["opisowe_wartosci"]:
                try:
                    allowed = json.loads(meta["opisowe_wartosci"])
                except Exception:
                    allowed = []
            w_limicie_val = 1 if text_val in allowed else 0
```

Replace with:

```python
            allowed = []
            if meta and meta["opisowe_wartosci"]:
                try:
                    allowed = json.loads(meta["opisowe_wartosci"])
                except Exception:
                    allowed = []
            if not allowed:
                w_limicie_val = None  # No spec list → neutral (cannot judge in/out)
            else:
                w_limicie_val = 1 if text_val in allowed else 0
```

- [ ] **Step 4: Run all tests to verify pass + no regressions**

Run: `pytest tests/test_jakosciowy_w_limicie.py -v`
Expected: 2 PASS

Run regression on related files: `pytest tests/test_backfill_jakosciowe.py tests/test_pipeline_adapter_jakosciowy.py tests/test_parametry_opisowe_wartosci.py tests/test_ebr_create_jakosciowe_autofill.py -v`
Expected: all PASS (no regressions).

- [ ] **Step 5: Commit**

```bash
git add mbr/laborant/models.py tests/test_jakosciowy_w_limicie.py
git commit -m "fix(laborant): w_limicie=NULL when opisowe_wartosci is empty/NULL"
```

---

## Task 3: Frontend constants + render branch

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html` (add constants + new branch in jakosciowy render code path around line 2681)

This task adds the visual rendering only. Save/load handlers come in Task 4.

- [ ] **Step 1: Locate the jakosciowy render branch**

Open `mbr/templates/laborant/_fast_entry_content.html`. Find the block starting at `} else if (pole.typ_analityczny === 'jakosciowy') {` (~line 2681). The new branch will live INSIDE this block, BEFORE the existing `<select>` rendering.

- [ ] **Step 2: Add module-level constants**

Find a top-level `<script>` or constants section near the top of the inline JS (before `_saveTimers` declaration is a good anchor; search for `var _saveTimers`). Add:

```js
// Special-case composite parameter: rozkład kwasów tłuszczowych (9 carbon chains).
// Renders as 3×3 grid of inputs whose values are joined with '|' into wartosc_text.
// See docs/superpowers/specs/2026-04-30-laborant-rozklad-kwasow-input-design.md
const ROZKLAD_KOD = 'cert_qual_rozklad_kwasow';
const ROZKLAD_CHAINS = [
  '≤C6:0', 'C8:0', 'C10:0',
  'C12:0', 'C14:0', 'C16:0',
  'C18:0', 'C18:1', 'C18:2',
];
```

- [ ] **Step 3: Insert the new render branch**

Inside the `} else if (pole.typ_analityczny === 'jakosciowy') {` block, BEFORE the existing dropdown rendering (the line that builds `optsHtml`), add:

```js
            // Special case: 9-chain composite (rozkład kwasów). Renders 3×3 grid.
            if (pole.kod === ROZKLAD_KOD) {
                var stored = (existing && existing.wartosc_text != null) ? String(existing.wartosc_text) : '';
                var parts = stored.split('|');
                while (parts.length < 9) parts.push('');
                if (parts.length > 9) parts.length = 9;
                var disabledAttr = isReadonly ? ' disabled' : '';
                var labelHtml = rtHtml(pole.skrot || pole.label);
                if (pole.grupa === 'zewn') {
                    labelHtml += ' <span class="pe-badge-zewn" title="Lab zewnętrzny">lab zewn.</span>';
                }
                var cellsHtml = '';
                for (var i = 0; i < 9; i++) {
                    var chainLabel = ROZKLAD_CHAINS[i];
                    var safeVal = String(parts[i]).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
                    cellsHtml +=
                        '<div class="ff-rozklad-cell">' +
                            '<span class="ff-rozklad-chain">' + chainLabel + '</span>' +
                            '<input type="text" class="ff-rozklad-input"' +
                                ' data-kod="' + esc(pole.kod) + '"' +
                                ' data-sekcja="' + esc(sekcja) + '"' +
                                ' data-rozklad-idx="' + i + '"' +
                                ' value="' + safeVal + '"' +
                                disabledAttr +
                                ' onchange="autoSaveRozkladRow(this)"' +
                                ' onblur="saveRozkladRow(this, true)">' +
                        '</div>';
                }
                fieldsHtml +=
                    '<div class="ff ff-rozklad' + highlightCls + '"' +
                        ' data-kod="' + esc(pole.kod) + '"' +
                        ' data-sekcja="' + esc(sekcja) + '">' +
                        '<div class="status-dot"></div>' +
                        '<label>' + labelHtml + '</label>' +
                        '<div class="ff-rozklad-grid">' + cellsHtml + '</div>' +
                    '</div>';
                return; // skip the default <select> branch below
            }
```

The `return` exits the per-pole forEach iteration so the default `<select>` is not also rendered.

- [ ] **Step 4: Add CSS for the grid**

Find the `<style>` block in the same template file (search for `/* PR3: jakosciowy select */`). Add adjacent CSS:

```css
/* Rozkład kwasów: 3×3 grid of small text inputs */
.ff-rozklad .ff-rozklad-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 6px 12px;
    flex: 1;
    max-width: 540px;
}
.ff-rozklad-cell {
    display: flex;
    align-items: center;
    gap: 6px;
}
.ff-rozklad-chain {
    font-size: 12px;
    color: var(--text-dim, #6b7280);
    min-width: 44px;
    text-align: right;
}
.ff-rozklad-input {
    width: 80px;
    padding: 3px 6px;
    border: 1px solid var(--border, #d1d5db);
    border-radius: 4px;
    font-size: 13px;
}
.ff-rozklad-input:focus {
    outline: 2px solid var(--teal);
}
```

- [ ] **Step 5: Add stub handlers (will be filled in Task 4)**

Just ABOVE `function autoSaveField(input) {` (search for that signature), add:

```js
// === Rozkład kwasów handlers (composite 9-chain saver) ===
// Implemented in Task 4. Stubs for now to prevent ReferenceError if the
// template loads before that task lands.
function autoSaveRozkladRow(input) { /* impl in Task 4 */ }
function saveRozkladRow(input, fromBlur) { /* impl in Task 4 */ }
```

- [ ] **Step 6: Smoke test the render path manually**

```bash
python -m mbr.app
# In another terminal: open a Monamid_KO completed batch in browser,
# inspect "Analiza końcowa" section. Expected: 3x3 grid of inputs, each
# labelled with chain name. No JS errors in console.
```

Note: backend save will NOT work yet — this is layout-only validation.

- [ ] **Step 7: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat(laborant): render 3x3 grid for rozkład kwasów (no save yet)"
```

---

## Task 4: Frontend save/load handlers

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html` (replace stubs from Task 3)

- [ ] **Step 1: Replace stub `autoSaveRozkladRow`**

Replace the stub `function autoSaveRozkladRow(input) { /* impl in Task 4 */ }` with:

```js
function autoSaveRozkladRow(input) {
    // Debounced save — joins all 9 inputs and posts once.
    var sekcja = input.dataset.sekcja;
    var kod = input.dataset.kod;
    if (!sekcja || !kod) return;
    var key = sekcja + '__' + kod;
    if (_saveTimers[key]) clearTimeout(_saveTimers[key].tid || _saveTimers[key]);
    _saveTimers[key] = {
        input: input, sekcja: sekcja, kod: kod, isRozklad: true,
        tid: setTimeout(function() {
            saveRozkladRow(input, false);
        }, 1500),
    };
}
```

- [ ] **Step 2: Replace stub `saveRozkladRow`**

Replace the stub `function saveRozkladRow(input, fromBlur) { /* impl in Task 4 */ }` with:

```js
function saveRozkladRow(input, fromBlur) {
    var sekcja = input.dataset.sekcja;
    var kod = input.dataset.kod;
    if (!sekcja || !kod) return;
    var key = sekcja + '__' + kod;
    if (_saveTimers[key]) {
        clearTimeout(_saveTimers[key].tid || _saveTimers[key]);
        delete _saveTimers[key];
    }

    // Find the container holding all 9 inputs (closest .ff-rozklad ancestor).
    var container = input.closest('.ff-rozklad');
    if (!container) return;

    // Collect 9 values in chain order.
    var raw = [];
    for (var i = 0; i < 9; i++) {
        var inp = container.querySelector('[data-rozklad-idx="' + i + '"]');
        raw.push(inp ? (inp.value || '').trim() : '');
    }
    var anyFilled = raw.some(function(v) { return v.length > 0; });

    // Build payload per spec — clear-all sends {wartosc:""} so backend
    // hits the is_clear branch (NULLs both fields). Otherwise send
    // wartosc_text explicitly to dodge the numeric-prefix sniffer.
    var values = {};
    if (anyFilled) {
        values[kod] = { wartosc_text: raw.join('|'), komentarz: '' };
    } else {
        values[kod] = { wartosc: '', komentarz: '' };
    }

    // Visual feedback: outline the input that triggered the save.
    input.style.outline = '2px solid var(--teal)';

    window._pendingFieldSaves = window._pendingFieldSaves || [];
    var promise = fetch('/laborant/ebr/' + _saveEbrId + '/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sekcja: sekcja, values: values}),
    }).then(async function(resp) {
        if (await _handleShiftRequired(resp)) return;
        if (resp.ok) {
            input.style.outline = '2px solid var(--green, #16a34a)';
            setTimeout(function() { input.style.outline = ''; }, 800);
            // Update local wyniki cache so other UI pieces (round state,
            // analiza re-render) see current value.
            if (!wyniki[sekcja]) wyniki[sekcja] = {};
            wyniki[sekcja][kod] = {
                wartosc: null,
                wartosc_text: anyFilled ? raw.join('|') : null,
                komentarz: '',
                w_limicie: null,  // composite — no spec list (Task 2 backend fix)
                tag: kod,
            };
        } else {
            input.style.outline = '2px solid var(--red, #dc2626)';
            setTimeout(function() { input.style.outline = ''; }, 2000);
        }
    }).catch(function() {
        input.style.outline = '2px solid var(--red, #dc2626)';
        setTimeout(function() { input.style.outline = ''; }, 2000);
    });
    window._pendingFieldSaves.push(promise);
    promise.finally(function() {
        var idx = window._pendingFieldSaves.indexOf(promise);
        if (idx >= 0) window._pendingFieldSaves.splice(idx, 1);
    });
    return promise;
}
```

- [ ] **Step 3: Patch `flushPendingSaves` to handle our isRozklad timers**

Find `async function flushPendingSaves()` (search for that signature). Inspect its current body — it iterates `_saveTimers` and calls `doSaveField(timer.input, timer.sekcja, timer.kod)`. Modify the iteration to dispatch on the `isRozklad` flag:

```js
async function flushPendingSaves() {
    var entries = Object.values(_saveTimers);
    _saveTimers = {};
    var promises = entries.map(function(t) {
        clearTimeout(t.tid);
        if (t.isRozklad) {
            return saveRozkladRow(t.input, false);
        }
        return doSaveField(t.input, t.sekcja, t.kod);
    });
    await Promise.allSettled(promises);
    if (window._pendingFieldSaves) {
        await Promise.allSettled(window._pendingFieldSaves);
    }
}
```

(If the existing function is structured slightly differently, preserve its outer logic and only adapt the per-timer dispatch line. Keep the same await + race semantics.)

- [ ] **Step 4: Manual test — save & reload flow**

```bash
python -m mbr.app
```

In browser:
1. Open a completed Monamid_KO batch.
2. Fill values: `<1`, `45`, `22`, `18`, `10`, `3`, `1`, `0`, `0`.
3. Wait 2s — outline turns green on edited input.
4. Refresh page. Expected: all 9 values restored in correct chain positions.
5. Clear all 9 → wait 2s. Refresh. Expected: all 9 empty.
6. Fill only chain 0 with `0.5`, leave 8 empty → save → refresh. Expected: chain 0 = `0.5`, others empty.

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat(laborant): wire rozkład kwasów save/load handlers"
```

---

## Task 5: Template smoke + roundtrip + cert tests

**Files:**
- Create: `tests/test_laborant_rozklad_kwasow.py`

Three tests as defined in spec.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_laborant_rozklad_kwasow.py
"""Tests for rozkład kwasów composite parameter input flow."""

import re
import sqlite3
import pytest
from pathlib import Path

from mbr.models import init_mbr_tables


REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "mbr" / "templates" / "laborant" / "_fast_entry_content.html"


def test_rozklad_template_constants_present():
    """Smoke: the special-case kod and all 9 chain labels must exist
    verbatim in the laborant fast-entry template. Catches regressions
    if anyone refactors the constants away."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "cert_qual_rozklad_kwasow" in text, "ROZKLAD_KOD constant missing"

    expected_chains = [
        "≤C6:0", "C8:0", "C10:0",
        "C12:0", "C14:0", "C16:0",
        "C18:0", "C18:1", "C18:2",
    ]
    for chain in expected_chains:
        assert chain in text, f"chain label {chain!r} missing from template"

    # Render branch markers
    assert "ROZKLAD_KOD" in text, "ROZKLAD_KOD reference missing in JS branch"
    assert "ff-rozklad-grid" in text, "grid CSS class missing"


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def test_wartosc_text_roundtrip_with_pipes(db):
    """Pipe-separated wartosc_text must survive insert/read round-trip
    without any character-level mangling by SQLite or the model layer."""
    pid = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision) "
        "VALUES ('cert_qual_rozklad_kwasow', 'Rozkład', 'jakosciowy', 'zewn', 0)"
    ).lastrowid
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('Monamid_KO', 'Monamid KO')")
    db.execute(
        "INSERT INTO mbr_templates (mbr_id, produkt, wersja, aktywna, etapy_json, parametry_lab) "
        "VALUES (1, 'Monamid_KO', 1, 1, '[]', '{}')"
    )
    db.execute(
        "INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start) "
        "VALUES (1, 1, 'b1', '1/26', '2026-01-01T00:00:00')"
    )
    pipe_value = "<1|45|22|18|10|3|1|0|0"
    db.execute(
        "INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc_text, "
        "is_manual, dt_wpisu, wpisal) VALUES (1, 'analiza_koncowa', "
        "'cert_qual_rozklad_kwasow', 'tag', ?, 1, '2026-01-01T00:00:00', 'op')",
        (pipe_value,),
    )
    db.commit()

    row = db.execute(
        "SELECT wartosc_text FROM ebr_wyniki WHERE kod_parametru='cert_qual_rozklad_kwasow'"
    ).fetchone()
    assert row["wartosc_text"] == pipe_value


def test_cert_renders_pipes_as_line_breaks_for_rozklad():
    """Cert generator must turn 9-segment wartosc_text into 8 <w:br/>
    runs in the result column. Regression for commit d17a08f
    (RichText conversion of result column)."""
    from docxtpl import DocxTemplate
    from mbr.certs.generator import _md_to_richtext

    template = REPO_ROOT / "mbr" / "templates" / "cert_master_template.docx"
    doc = DocxTemplate(str(template))

    # Minimal context with a single rozkład-shaped row.
    ctx = {
        "avon_code": "R26010", "avon_name": "TEST",
        "wzor": "Mxxx", "opinion_pl": "", "opinion_en": "",
        "order_number": "", "spec_number": "", "product_pl": "X", "product_en": "X",
        "inci": "", "nr_partii": "1/26", "dt_produkcji": "01.01.2026",
        "dt_waznosci": "01.01.2028", "dt_wystawienia": "01.01.2026", "wystawil": "X",
        "rspo_text": "", "cas_number": "", "certificate_number": "",
        "rows": [{
            "kod": "rozklad",
            "name_pl": _md_to_richtext("Rozkład kwasów"),
            "name_en": _md_to_richtext("/Fatty acid distribution|≤C6:0|C8:0|C10:0|C12:0|C14:0|C16:0|C18:0|C18:1|C18:2"),
            "requirement": "",
            "method": "GC",
            "result": _md_to_richtext("<1|45|22|18|10|3|1|0|0"),
        }],
        "has_avon_code": True, "has_avon_name": True,
        "display_name": "M", "rspo": "",
    }

    import tempfile, zipfile
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        out_path = tmp.name
    doc.render(ctx)
    doc.save(out_path)

    with zipfile.ZipFile(out_path) as z:
        xml = z.read("word/document.xml").decode("utf-8")

    # Find the Result cell content. We expect 8 <w:br/> for 9 segments.
    # Locate the result cell by anchoring on first value '<1' (which contains
    # &lt;1 in escaped XML). Then count <w:br/> until the next paragraph end.
    m = re.search(r"&lt;1.*?</w:p>", xml, re.DOTALL)
    assert m is not None, "result cell with '<1' not found"
    result_block = m.group(0)
    br_count = result_block.count("<w:br/>")
    assert br_count == 8, f"expected 8 <w:br/> in result cell, got {br_count}"
```

- [ ] **Step 2: Run the tests**

Run: `pytest tests/test_laborant_rozklad_kwasow.py -v`
Expected: 3 PASS (constants test passes if Tasks 3-4 are committed; roundtrip and cert tests pass independently of those tasks).

- [ ] **Step 3: Commit**

```bash
git add tests/test_laborant_rozklad_kwasow.py
git commit -m "test(laborant): rozkład kwasów template, roundtrip, cert render"
```

---

## Task 6: Register migration in auto-deploy.sh

**Files:**
- Modify: `deploy/auto-deploy.sh`

- [ ] **Step 1: Locate migration block in auto-deploy.sh**

Open `deploy/auto-deploy.sh`. Find the section under the comment `# Run pending migrations BEFORE restart`. There's a list of `python scripts/migrate_*.py` lines.

- [ ] **Step 2: Add our migration**

Insert after the existing `migrate_audit_log_v2.py` line:

```bash
/opt/lims/venv/bin/python scripts/migrate_rozklad_kwasow_seed.py --db data/batch_db.sqlite
```

The full block should now read (example — match your local context):

```bash
# Run pending migrations BEFORE restart (scripts must be idempotent — re-running is a no-op)
/opt/lims/venv/bin/python scripts/migrate_audit_log_v2.py --db data/batch_db.sqlite
/opt/lims/venv/bin/python scripts/migrate_rozklad_kwasow_seed.py --db data/batch_db.sqlite
```

- [ ] **Step 3: Verify shell syntax**

Run: `bash -n deploy/auto-deploy.sh`
Expected: no output (syntax OK).

- [ ] **Step 4: Commit**

```bash
git add deploy/auto-deploy.sh
git commit -m "ops(auto-deploy): register migrate_rozklad_kwasow_seed"
```

---

## Task 7: Manual end-to-end smoke

**Files:** None (operational verification).

This is the final gate before push to prod. Run in this order on local:

- [ ] **Step 1: Full test suite**

Run: `pytest -x 2>&1 | tail -30`
Expected: ALL pass (zero failures, zero errors).

- [ ] **Step 2: Local migration sanity check**

Run: `python scripts/migrate_rozklad_kwasow_seed.py --db data/batch_db.sqlite`
Expected: counters showing 0,0,0,0 (already applied earlier in Task 1) OR the migration fires once cleanly.

Run again immediately: `python scripts/migrate_rozklad_kwasow_seed.py --db data/batch_db.sqlite`
Expected: 0,0,0,0 (idempotence verified).

- [ ] **Step 3: Browser walkthrough — completed batch flow**

Start dev server: `python -m mbr.app`

In browser at `http://localhost:5001`:

1. Login as laborant.
2. Find or create a Monamid_KO batch with status='completed'. (If none exists locally, create one and complete it via standard flow.)
3. Open the batch's fast-entry. Confirm:
   - Section "Analiza końcowa" contains a row labelled "Rozkład kwasów tłuszczowych [%]" with badge "lab zewn."
   - The row body shows a 3×3 grid (9 inputs, each with chain label like "≤C6:0", "C8:0", …).
   - All inputs are empty (post-migration state).
4. Type `<1` into the first input (≤C6:0). Tab through and fill all 9: `<1, 45, 22, 18, 10, 3, 1, 0, 0`.
5. Wait ~2 s. Outline of last edited input flashes green.
6. Refresh page. All 9 values restored in their slots.
7. Open browser DevTools Network tab. Edit one value. Watch for POST to `/laborant/ebr/<id>/save`. Inspect request body — should include `values["cert_qual_rozklad_kwasow"].wartosc_text = "<1|45|..."`.
8. Clear ALL 9 inputs → wait 2 s → refresh. All 9 empty.
9. In Network: confirm the clear-all save sent `values["..."].wartosc = ""` (NOT `wartosc_text`).

- [ ] **Step 4: Cert preview check**

In admin panel → wzory świadectw → Monamid_KO → Avon variant → Generate preview.
Expected: cert PDF shows in result column 9 stacked values: `<1`, `45`, `22`, `18`, `10`, `3`, `1`, `0`, `0`.

- [ ] **Step 5: Push to prod**

If all steps above passed:

```bash
git push origin main
```

Auto-deploy will pick up the commits, run the migration on prod, and restart the service. SSH in to verify within ~3 minutes:

```bash
ssh tbk@labcore.local "sqlite3 /opt/lims/data/batch_db.sqlite \\
    'SELECT grupa, cert_qualitative_result FROM parametry_etapy WHERE parametr_id=59;'"
```

Expected output: rows with `grupa=zewn`, `cert_qualitative_result=NULL`.

```bash
ssh tbk@labcore.local "sqlite3 /opt/lims/data/batch_db.sqlite \\
    'SELECT grupa FROM parametry_analityczne WHERE id=59;'"
```

Expected: `zewn`.

---

## Spec coverage check

- [x] Hardcoded `kod` + 9 chain labels — Task 3 Step 2
- [x] 3×3 grid render — Task 3 Step 3 + Step 4 (CSS)
- [x] `data-rozklad-idx` attrs for save lookup — Task 3 Step 3
- [x] Visibility tied to existing jakosciowy hide-while-open rule — no code change required (Task 7 Step 3 verifies)
- [x] Save: explicit `wartosc_text` for filled, `wartosc=""` for clear-all — Task 4 Step 2
- [x] Debounce 1500 ms via `_saveTimers` — Task 4 Step 1
- [x] Custom save path (not `doSaveField` reuse) — Task 4 Step 2
- [x] `flushPendingSaves` integration — Task 4 Step 3
- [x] Backend `w_limicie` fix when no `opisowe_wartosci` — Task 2
- [x] Migration: cert_qualitative_result clear, grupa flip, ebr_wyniki purge — Task 1
- [x] Auto-deploy registration — Task 6
- [x] Pytest tests (5 across 3 files) — Tasks 1, 2, 5
- [x] Manual smoke plan — Task 7
