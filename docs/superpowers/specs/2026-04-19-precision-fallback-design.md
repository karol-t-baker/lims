# Precision Fallback in resolve_limity — Design Spec

**Date:** 2026-04-19
**Status:** Approved for implementation
**Scope:** ~30 min of implementation (2-line code change + 5 regression tests).

## Problem

Admins set precision for a parameter in the "Rejestr" tab (writes to `parametry_analityczne.precision`), expecting the value to propagate to all products that use that parameter. The value persists correctly but is **silently ignored for pipeline-based products** (Cheminox_K, K40GLOL, K7, Alkinol, etc.). Laborants see values rendered with an implicit default precision (usually 2 decimals), ignoring the admin-configured value.

## Root Cause

`mbr/pipeline/models.py::resolve_limity` reads precision from two sources:

```python
"precision": r["ovr_precision"] if r["ovr_precision"] is not None else r["cat_precision"],
```

- `ovr_precision` = `produkt_etap_limity.precision` (per-product override; nullable; rarely set)
- `cat_precision` = `etap_parametry.precision` (stage-catalog default; nullable; usually NULL in production)

It never reads `parametry_analityczne.precision` (the global per-parameter value that admins edit). When both `ovr` and `cat` are NULL — the normal production case — `resolve_limity` returns `precision=None`. That `None` flows into `_build_pole`, into the `parametry_lab` JSON cached on `mbr_templates`, and finally into the UI, which falls back to 2 decimals by default.

The non-pipeline (legacy) path at `mbr/parametry/registry.py::get_parametry_for_kontekst` already does the right thing: `COALESCE(pe.precision, pa.precision, 2)`. The pipeline path is the only one missing the global fallback.

Database evidence for Chegina_Cheminox_K:
- `parametry_analityczne.precision`: ph=2, nd20=4, sm=1, barwa_hz=0 (admin-configured)
- `etap_parametry.precision`: all NULL
- `produkt_etap_limity.precision`: all NULL
- Cached `mbr_templates.parametry_lab` for Cheminox_K: precision=null for every pole

## Goal

Extend `resolve_limity` to fall back to `parametry_analityczne.precision` when both `produkt_etap_limity.precision` and `etap_parametry.precision` are NULL, with a final hardcoded default of `2` (matches legacy `COALESCE` semantics). No UI changes. No one-shot cache migration — existing cached `parametry_lab` JSONs regenerate naturally on the next admin save of any parameter affecting the product (the admin-save path already calls `build_parametry_lab`).

## Non-goals

- **Admin UI column "Precyzja" in Etapy tab.** The `PUT /api/bindings/<id>` API accepts `precision` in `_BINDING_FIELDS`, but the UI doesn't render a column for it. Out of scope here — YAGNI. Adding the column is a separate feature.
- **Range validation** for precision (e.g., 0-5). Not introduced as part of the bug fix.
- **One-shot migration** that rebuilds every `mbr_templates.parametry_lab` cache. User explicitly chose the lazy path; acceptable inconsistency window until each product gets its next admin save. Spec includes a Python snippet the operator can run manually for any single product that needs immediate refresh.
- **Changes to `get_parametry_for_kontekst`** (legacy non-pipeline path). That path already handles the fallback correctly via `COALESCE`.

## Architecture

**One-liner:** extend the `resolve_limity` SQL SELECT with `pa.precision AS global_precision` and change the Python dict's precision resolution from 2-tier (ovr → cat) to 3-tier (ovr → cat → global → 2).

All downstream code (`_build_pole`, `build_parametry_lab`, `parametry_lab` JSON consumers, UI) is unchanged: they already read `pole.precision` and will see the correct value automatically once the cache regenerates.

## Components

### 1. Backend — `resolve_limity` SELECT

**File:** `mbr/pipeline/models.py::resolve_limity` (~line 903-932).

Current SELECT projects 20+ columns. Add one more:

```sql
    pa.kod, pa.label, pa.typ, pa.skrot, pa.jednostka,
    pa.precision AS global_precision,                           -- NEW
    pel.min_limit  AS ovr_min, pel.max_limit  AS ovr_max,
```

### 2. Backend — `resolve_limity` return dict

**File:** `mbr/pipeline/models.py::resolve_limity` (~line 949).

Current line:

```python
"precision": r["ovr_precision"] if r["ovr_precision"] is not None else r["cat_precision"],
```

New line:

```python
"precision": (
    r["ovr_precision"] if r["ovr_precision"] is not None
    else r["cat_precision"] if r["cat_precision"] is not None
    else r["global_precision"] if r["global_precision"] is not None
    else 2
),
```

The `else 2` final fallback matches the legacy path's `COALESCE(..., 2)` default so both code paths return the same value for fully-unconfigured parameters.

### 3. Views / UI / cache

**No changes.** The fix alters the value `resolve_limity` returns. `_build_pole`, `build_parametry_lab`, and every `parametry_lab`-consuming UI read `pole.precision` unchanged. Cached `parametry_lab` JSONs in `mbr_templates` will regenerate on the next admin save (existing behavior in `api_parametry_update` and sibling PUT endpoints).

### 4. Rollback safety

The change is purely additive: one new column in SELECT, one extended fallback chain in Python. Reverting these two changes restores the pre-fix behavior exactly; no dangling references, no schema change, no cache poisoning.

## Data flow

1. Admin opens `/parametry`, Rejestr tab, edits `ph.precision` from 2 to 3.
2. `PUT /api/parametry/<id>` persists `parametry_analityczne.precision = 3` AND calls `build_parametry_lab(db, produkt)` for every affected active product → regenerates their `mbr_templates.parametry_lab` cache.
3. During rebuild, `build_parametry_lab` → `build_pipeline_context` → `_build_pole` → `resolve_limity`. With the new SELECT and fallback, precision resolves to `3` (global_precision) for products that have NULL ovr/cat.
4. Each product's `parametry_lab` JSON now has `precision: 3` in the relevant pole.
5. Laborant opens a batch → `/laborant/ebr/<id>/fast-entry` reads `parametry_lab` → renders input with correct precision.

## Error handling

| Condition | Behavior |
|---|---|
| Both `ovr` and `cat` are NULL, `global` is set | Returns `global_precision` (bug fix target) |
| All three are NULL | Returns hardcoded `2` (matches legacy `COALESCE`) |
| `ovr=0, cat=4, global=2` | Returns `0` (explicit override wins; must NOT be mistaken for falsy NULL) |
| `ovr=NULL, cat=NULL, global=0` | Returns `0` (admin may want 0-decimal integers; `None` check via `is not None`, not truthy check) |

All four checks use `is not None` — critical because precision can legitimately be `0`.

## Testing

**New test file: `tests/test_resolve_limity_precision_fallback.py`**

Five tests with exact names:

1. `test_precision_ovr_wins` — set all three (pel=3, ep=4, pa=2); expect `3`.
2. `test_precision_cat_fallback_when_ovr_null` — pel=NULL, ep=4, pa=2; expect `4`.
3. `test_precision_global_fallback_when_ovr_and_cat_null` — pel=NULL, ep=NULL, pa=2; expect `2`. **(Regression test for the reported bug.)**
4. `test_precision_default_2_when_all_null` — all NULL; expect `2`.
5. `test_precision_zero_override_wins` — pel=0, ep=4, pa=2; expect `0` (guards against `if value:` truthy check misuse).

Each test seeds a minimal `etapy_analityczne`, `etap_parametry`, `produkt_etap_limity`, `parametry_analityczne` fixture in an in-memory DB and calls `resolve_limity(db, produkt, etap_id)` directly — no Flask client needed.

**Regression check:** full suite (`pytest -q`) must stay at `829 passed, 19 skipped` + the 5 new tests = `834 passed, 19 skipped`. Existing `tests/test_pipeline_adapter.py` fixtures already set `etap_parametry.precision=1`, so `cat_precision` wins — the new global fallback code path is not exercised, existing tests unchanged.

**Post-deploy smoke (manual):**

1. Before fix: Cheminox_K laborant sees imprecise decimal counts.
2. Apply fix + restart app.
3. Trigger cache regen for a specific product via REPL (optional — otherwise wait for next admin save):
   ```python
   from mbr.db import db_session
   from mbr.parametry.registry import build_parametry_lab
   import json
   with db_session() as db:
       for produkt in ["Chegina_Cheminox_K", "Chegina_Cheminox_K35", "Chegina_Cheminox_LA"]:
           plab = build_parametry_lab(db, produkt)
           db.execute(
               "UPDATE mbr_templates SET parametry_lab=? WHERE produkt=? AND status='active'",
               (json.dumps(plab, ensure_ascii=False), produkt),
           )
       db.commit()
   ```
4. Reload Cheminox_K laborant view → values render with admin-configured precision.

## Open questions

None. All decisions locked in via brainstorming session 2026-04-19.

## References

- Explore agent report in conversation 2026-04-19 (precision-ignored investigation)
- Legacy precision resolution (reference): `mbr/parametry/registry.py::get_parametry_for_kontekst` — `COALESCE(pe.precision, pa.precision, 2)`
- Related recent fixes:
  - `8577fca` fix(laborant): apply pole.precision to hero/view cv-p values
  - `22306e0` fix(laborant): add data-precision to hero cv-p-input post-save re-format
  - Both are UI-only; this spec fixes the upstream backend source.
