# Precision Fallback in resolve_limity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `resolve_limity` fall back to `parametry_analityczne.precision` when both `produkt_etap_limity.precision` and `etap_parametry.precision` are NULL, with a final default of `2` — matching the legacy `COALESCE` semantics used by `get_parametry_for_kontekst`.

**Architecture:** Extend the SELECT in `resolve_limity` with `pa.precision AS global_precision`; change the return-dict's precision resolution from 2-tier (`ovr` → `cat`) to 3-tier (`ovr` → `cat` → `global` → `2`). Single file backend change; no schema, no UI, no cache migration.

**Tech Stack:** Python/Flask, sqlite3, pytest.

**Baseline:** `pytest -q` → `829 passed, 19 skipped` (post cert-alias merge on main). Every task ends green.

**Guard rails:**
1. One commit for the fix (test + code together — TDD cycle is small). Co-Authored-By trailer.
2. DO NOT stage `mbr/cert_config.json` or `data/batch_db 2.sqlite-wal` (pre-existing dirty files).
3. Work on feature branch `fix/precision-fallback` (do NOT commit directly to main).
4. No `git push`.

---

## Task 0: Branch setup

**Files:** n/a (git only).

- [ ] **Step 1: Create feature branch**

```bash
cd /Users/tbk/Desktop/lims-clean
git checkout main
git log -1 --format='%H %s'
```
Expected HEAD: `04f6c11 docs(spec): precision fallback in resolve_limity` or newer.

```bash
git checkout -b fix/precision-fallback
git branch --show-current
```
Expected: `fix/precision-fallback`.

---

## Task 1: Add `global_precision` fallback to `resolve_limity`

**Files:**
- Modify: `mbr/pipeline/models.py::resolve_limity` (lines 915 + 949)
- Create test: `tests/test_resolve_limity_precision_fallback.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_resolve_limity_precision_fallback.py`:

```python
"""Regression: resolve_limity must fall back to parametry_analityczne.precision
when both produkt_etap_limity.precision and etap_parametry.precision are NULL.
Final default is 2 (matches legacy COALESCE(..., 2) semantics)."""

import sqlite3
import pytest

from mbr.models import init_mbr_tables
from mbr.pipeline.models import resolve_limity


def _seed(db, *, pa_precision, ep_precision, pel_precision):
    """Insert one parametr + etap + (maybe) product override, varying precision."""
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, skrot, precision) "
        "VALUES (1, 'ph', 'pH', 'bezposredni', 'pH', ?)",
        (pa_precision,),
    )
    db.execute(
        "INSERT OR IGNORE INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
        "VALUES (6, 'analiza_koncowa', 'Analiza końcowa', 'jednorazowy')"
    )
    db.execute(
        "INSERT INTO etap_parametry (id, etap_id, parametr_id, kolejnosc, precision) "
        "VALUES (10, 6, 1, 1, ?)",
        (ep_precision,),
    )
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, precision, "
        "dla_szarzy, dla_zbiornika, dla_platkowania) "
        "VALUES ('TEST_P', 6, 1, ?, 1, 1, 0)",
        (pel_precision,),
    )
    db.commit()


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def test_precision_ovr_wins(db):
    """produkt_etap_limity.precision overrides all others."""
    _seed(db, pa_precision=2, ep_precision=4, pel_precision=3)
    [row] = resolve_limity(db, "TEST_P", 6)
    assert row["precision"] == 3


def test_precision_cat_fallback_when_ovr_null(db):
    """ovr NULL → etap_parametry.precision wins."""
    _seed(db, pa_precision=2, ep_precision=4, pel_precision=None)
    [row] = resolve_limity(db, "TEST_P", 6)
    assert row["precision"] == 4


def test_precision_global_fallback_when_ovr_and_cat_null(db):
    """ovr and cat both NULL → parametry_analityczne.precision wins. THE BUG FIX."""
    _seed(db, pa_precision=2, ep_precision=None, pel_precision=None)
    [row] = resolve_limity(db, "TEST_P", 6)
    assert row["precision"] == 2


def test_precision_default_2_when_all_null(db):
    """All three NULL → hardcoded default 2 (matches legacy COALESCE)."""
    _seed(db, pa_precision=None, ep_precision=None, pel_precision=None)
    [row] = resolve_limity(db, "TEST_P", 6)
    assert row["precision"] == 2


def test_precision_zero_override_wins(db):
    """Explicit override of 0 is valid (integer display); must NOT be mistaken for NULL."""
    _seed(db, pa_precision=2, ep_precision=4, pel_precision=0)
    [row] = resolve_limity(db, "TEST_P", 6)
    assert row["precision"] == 0
```

- [ ] **Step 2: Run the new tests — confirm FAIL**

Run: `pytest tests/test_resolve_limity_precision_fallback.py -v`
Expected: `test_precision_global_fallback_when_ovr_and_cat_null` FAILS (returns `None`, expected `2`). `test_precision_default_2_when_all_null` also FAILS (returns `None`, expected `2`). The other 3 may pass trivially.

- [ ] **Step 3: Modify the SELECT to surface `pa.precision`**

In `mbr/pipeline/models.py` (around line 915), locate the SELECT list in `resolve_limity` and find the line:

```python
            pa.kod, pa.label, pa.typ, pa.skrot, pa.jednostka,
```

Replace with (adds one projection):

```python
            pa.kod, pa.label, pa.typ, pa.skrot, pa.jednostka,
            pa.precision AS global_precision,
```

- [ ] **Step 4: Replace the precision resolution line**

Still in `mbr/pipeline/models.py::resolve_limity`, locate line 949:

```python
            "precision": r["ovr_precision"] if r["ovr_precision"] is not None else r["cat_precision"],
```

Replace with:

```python
            "precision": (
                r["ovr_precision"] if r["ovr_precision"] is not None
                else r["cat_precision"] if r["cat_precision"] is not None
                else r["global_precision"] if r["global_precision"] is not None
                else 2
            ),
```

Every check uses `is not None` — critical because `0` is a legitimate precision value (integer display), and truthy checks would silently treat it as NULL.

- [ ] **Step 5: Run the new tests — confirm PASS**

Run: `pytest tests/test_resolve_limity_precision_fallback.py -v`
Expected: all 5 pass.

- [ ] **Step 6: Run full suite**

Run: `pytest -q`
Expected: `834 passed, 19 skipped` (829 + 5 new).

**If existing tests regress:** inspect the failure. Any existing test asserting `precision` should keep passing — the 2-tier → 3-tier change only affects the NULL-NULL-and-something case, which existing fixtures don't exercise (they always seed either `ep.precision` or `pel.precision`). If something does regress, stop and report; do NOT adjust the new fallback logic.

- [ ] **Step 7: Commit**

```bash
git add mbr/pipeline/models.py tests/test_resolve_limity_precision_fallback.py
git commit -m "$(cat <<'EOF'
fix(pipeline): resolve_limity falls back to parametry_analityczne.precision

Pipeline products had their admin-set precision silently ignored. The
legacy non-pipeline path already does COALESCE(pe.precision, pa.precision, 2);
resolve_limity only read ovr (produkt_etap_limity) and cat (etap_parametry),
both usually NULL in production, returning None for every pole. The None
cached in mbr_templates.parametry_lab and the UI fell back to its default 2.

Extends SELECT with pa.precision AS global_precision; adds a third tier
to the resolution chain with final hardcoded default 2, matching legacy
semantics. All `is not None` checks to preserve 0 as a valid precision.

Lazy cache rebuild: existing parametry_lab JSONs with precision=null
regenerate on next admin save (build_parametry_lab trigger unchanged).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Final verification

**Files:** n/a (verification only).

- [ ] **Step 1: Full test suite**

Run: `pytest -q`
Expected: `834 passed, 19 skipped` (baseline 829 + 5 new).

- [ ] **Step 2: Branch log**

Run:
```bash
git log --oneline main..HEAD
```

Expected: 1 commit (Task 1). Task 0 has no commit; Task 2 has no commit.

- [ ] **Step 3: Ready for merge**

No additional commits. Branch `fix/precision-fallback` ready for `superpowers:finishing-a-development-branch`.

---

## Self-Review

**Spec coverage:**
- Architecture §Components 1 (SELECT extension) → Task 1 Step 3 ✓
- Architecture §Components 2 (return dict resolution) → Task 1 Step 4 ✓
- Architecture §Components 3 (no UI change) — verified implicitly; no UI file touched ✓
- Architecture §Components 4 (rollback safety) — noted in commit body; no schema change ✓
- Error handling table (5 cases) → each maps 1:1 to a test in Task 1 Step 1 ✓
- Testing §New test file — Task 1 creates `tests/test_resolve_limity_precision_fallback.py` ✓
- Non-goals respected: no UI column, no range validation, no one-shot migration, no legacy-path changes ✓

All spec requirements covered.

**Placeholder scan:** No TBD/TODO/"handle edge cases" strings. Each step shows exact code or exact command.

**Type consistency:**
- SQL alias `global_precision` used in both Task 1 Step 3 (SELECT) and Step 4 (dict resolution) — same name.
- All 5 test function names use the same `test_precision_*` prefix pattern.
- `is not None` consistently used across all four precision checks.

**Risk of breaking existing tests (829 baseline):**
- Additive SELECT column — no existing caller iterates Row keys exhaustively; confirmed by prior grep in the Explore phase.
- Precision resolution change: pre-fix behavior for `ovr_precision=X` or `cat_precision=X` is preserved exactly. Only the `(None, None, ...)` case changes — and existing fixtures (per `tests/test_pipeline_adapter.py`) always seed at least `etap_parametry.precision=1`, so this path wasn't exercised.
- Risk: LOW.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-19-precision-fallback.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent for Task 1 + spec/code-quality review. Single task → ~20-30 min.
2. **Inline Execution** — tasks in this session via `superpowers:executing-plans`.

Which approach?
