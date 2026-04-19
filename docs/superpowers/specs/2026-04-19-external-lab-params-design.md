# External-Lab Parameters — Design Spec

**Date:** 2026-04-19
**Status:** Approved for implementation
**Scope:** ~1 day of implementation (small feature, mostly plumbing).

## Problem

Some analytical parameters on a cert (świadectwo) are measured by an **external lab** (not the in-house LIMS lab). The external lab returns results days after the batch is completed. A KJ (quality-control) user then types the values into LIMS.

Today there is no supported way to:

1. **Mark a parameter as external-lab** so its source is traceable.
2. **Configure it** (bind to a product, flag on the cert) through the admin UI.
3. **Display it consistently** across completed-batches list, batch hero/summary view, and the cert PDF.

The data model has partial support (`parametry_etapy.grupa TEXT DEFAULT 'lab'`, role `kj` already exists), but no code uses non-`lab` values and the admin UI has no controls for this.

## Goal

Enable this full flow:

1. Admin creates a parameter marked `grupa='zewn'` (external).
2. Admin binds it to a product + sekcja via the existing Etapy tab.
3. Admin flags it on the cert via the existing cert admin.
4. Laborant completes a batch without the value (external lab hasn't responded yet); cert renders with an empty row.
5. KJ opens the completed batch via the existing edit flow and enters the external value.
6. Someone regenerates the cert manually — the value now shows.

No visual distinction between `lab` and `zewn` params is required anywhere in the UI. This is explicit scope, confirmed with the user.

## Non-goals

- **Auto-regenerate cert** after a late-arriving external value. The user explicitly opted for manual regeneration.
- **Visual badges / colors / separators** for `zewn` params. Not wanted.
- **Multiple external-lab groups** (e.g. `mikrobio`, `fizykochem`, `zewn_kontrakt`). One group is enough for now. Keep the column as free-form TEXT so future additions don't require schema changes, but the whitelist in this release is `{'lab', 'zewn'}`.
- **Separate entry UI** for KJ. Existing completed-batch edit route already supports role `kj`.
- **Stale-cert indicator** ("cert was generated before external value arrived"). Manual regen is the contract.
- **Cascade of `grupa` change onto existing bindings.** If admin changes a parameter from `lab` to `zewn` after bindings already exist, existing `parametry_etapy` rows keep their old `grupa`. Admin must update bindings explicitly. This is the safe default; re-cascade behavior is a future feature.
- **Cert admin changes.** The `on_cert` toggle, `cert_kolejnosc`, `cert_requirement` are configured through the existing `/admin/wzory-cert` editor — no changes there.

## Architecture

**One-liner:** add `grupa` column to `parametry_analityczne`, expose via admin UI dropdown, let the existing grupa-agnostic render pipeline do the rest.

The rendering pipeline is already grupa-agnostic (verified by code review: no `WHERE grupa = 'lab'` filter anywhere, no JS filter by `pole.grupa` except the cosmetic badge introduced in `_fast_entry_content.html:1803` which only applies when grupa≠'lab' and is currently never triggered because no data has non-'lab' grupa). So the only work is:

1. Add the schema column.
2. Let admin CRUD it.
3. Make sure new bindings inherit it.
4. Add regression tests so nothing silently stops rendering `grupa='zewn'` params.

## Components

### 1. Schema change

**File:** `mbr/models.py` (inside `init_mbr_tables`).

Add idempotent migration:

```python
try:
    db.execute("ALTER TABLE parametry_analityczne ADD COLUMN grupa TEXT DEFAULT 'lab'")
    db.commit()
except Exception:
    pass  # column already exists
```

`parametry_etapy.grupa` already exists; no schema change needed there.

### 2. Backend — API

**File:** `mbr/parametry/routes.py`.

- `POST /api/parametry` (create): accept `grupa` field in JSON body. Validate against whitelist `{'lab', 'zewn'}`. Default to `'lab'` if absent. Persist in `parametry_analityczne.grupa`.
- `PUT /api/parametry/<id>` (update): same validation rule; only update if field present in body.
- **Validation helper:** single constant `ALLOWED_GRUPY = {'lab', 'zewn'}` at module top. Reuse in both endpoints.
- `GET /api/parametry` (list): include `grupa` in returned rows so admin UI can render the current value.

### 3. Backend — binding inheritance

**File:** `mbr/parametry/routes.py`, route `POST /api/parametry/etapy` (has two code paths: pipeline products → `produkt_etap_limity`, legacy/non-pipeline → `parametry_etapy`). Also `mbr/pipeline/models.py::set_produkt_etap_limit` (whitelist `_PEL_ALLOWED_FIELDS` needs `grupa`).

Both `parametry_etapy.grupa` and `produkt_etap_limity.grupa` exist (both `TEXT DEFAULT 'lab'`). When a new binding row is created for a (produkt, kontekst, parametr_id) via either path:

- If the create-binding body does NOT include `grupa`, read it from `parametry_analityczne.grupa` for that `parametr_id` and use that as the default.
- If the body explicitly includes `grupa`, honor it (admin override).
- Validate the final value against the same `ALLOWED_GRUPY` whitelist.

This is *not* a cascade update — existing rows are untouched. Only new rows inherit.

### 4. Admin UI — Rejestr tab

**File:** `mbr/templates/parametry_editor.html`.

- Add a "Grupa" column/field in the Rejestr tab's parameter create/edit form (modal or inline — match existing pattern in the template).
- Field type: `<select>` with options `lab` (default) and `zewn`.
- On save, POST/PUT to `/api/parametry` with the `grupa` value.
- Render current `grupa` in the Rejestr list table so admin can see at a glance which params are external.

### 5. Views — verification only, no code changes expected

- **Completed batches list (`mbr/templates/laborant/szarze_list.html` + `mbr/registry/models.py::get_registry_columns`):** confirmed grupa-agnostic; pola from `build_parametry_lab` flow through unchanged. No code change. Regression test covers it.
- **Hero / cv-param view (`mbr/templates/laborant/_fast_entry_content.html`):** confirmed grupa-agnostic (badge logic at line 1803 is cosmetic; no filter). No code change. Manual smoke test covers it.
- **Cert generator (`mbr/certs/generator.py::build_context`):** confirmed grupa-agnostic; filters only by `on_cert=1` via `parametry_cert` / `parametry_etapy`. No code change.

### 6. Role access — existing

`mbr/laborant/routes.py::save_entry` is decorated `@role_required("lab", "cert", "kj", "admin")`. KJ can already save wyniki on completed batches. `ShiftRequiredError` handling also already works. No changes.

## Data flow

Concrete example: external-lab param `tpc` (total plate count) for product Chegina_K7.

1. **Admin** creates `tpc` in Rejestr. Body: `{kod: 'tpc', label: 'Total plate count', typ: 'bezposredni', grupa: 'zewn', precision: 0}`. New row in `parametry_analityczne`.
2. **Admin** binds `tpc` to Chegina_K7 / `analiza_koncowa` via Etapy tab. Backend reads `parametry_analityczne.grupa='zewn'` and inherits into the new `parametry_etapy` row.
3. **Admin** opens `/admin/wzory-cert`, sets `on_cert=1`, `cert_kolejnosc=12`, `cert_requirement='<100 CFU/g'` on the binding. (Existing UI, unchanged.)
4. **Laborant** runs a K7 batch. `parametry_lab` JSON for the product includes `tpc` in the `analiza_koncowa` sekcja with `grupa: 'zewn'`. Laborant sees it as a field in the entry form, leaves it empty (external result not back yet), closes the batch.
5. **Laborant** generates cert. PDF has a row for `tpc` with empty result. (Cert generator processes it because `on_cert=1`, doesn't care about `grupa`.)
6. **External lab** emails result 3 days later: `tpc = 45`.
7. **KJ** logs in, shift configured, opens the completed batch via existing "edit completed batch" route. Form shows `tpc` as not-yet-filled. KJ types `45`. `save_entry` → `save_wyniki` → row inserted in `ebr_wyniki` as `kod_parametru='tpc'`.
8. **Anyone** regenerates the cert. `tpc = 45` now appears on the PDF.

Completed-batches list (`/laborant/szarze`) and the hero/cv-param view automatically show the value too (same pipeline, same render code).

## Error handling

| Condition | Behavior |
|---|---|
| `POST/PUT /api/parametry` with `grupa` not in `{'lab','zewn'}` | HTTP 400, message `"grupa must be one of: lab, zewn"` |
| `POST/PUT /api/parametry` with no `grupa` field | Defaults to `'lab'` |
| Migration run on DB that already has the column | `ALTER TABLE ... ADD COLUMN` raises; swallowed by `except` (idempotent) |
| Admin changes `parametry_analityczne.grupa` after bindings exist | Existing bindings keep old `grupa`. Admin must manually update `parametry_etapy.grupa` for each binding if desired. (Intentional — avoid surprise cascades.) |
| KJ enters value on completed batch without shift_workers in session | Existing `ShiftRequiredError` → 400 JSON response |
| Laborant finishes batch before external value arrives | Cert renders with empty value row. No warning/error; that's the contract. |
| Someone forgets to regenerate cert after KJ enters value | User's problem — manual regen. |

## Testing

**New test file: `tests/test_parametry_grupa.py`**

Covers the four new things:

1. Schema migration idempotent (run `init_mbr_tables` twice, confirm `grupa` column present exactly once).
2. `POST /api/parametry` with `grupa='zewn'` persists it correctly; `GET /api/parametry` returns it.
3. `POST /api/parametry` with `grupa='invalid'` returns 400.
4. `PUT /api/parametry/<id>` updates `grupa` from `'lab'` to `'zewn'`.
5. Creating a new `parametry_etapy` binding for a param with `grupa='zewn'` inherits the grupa into the binding (binding row has `grupa='zewn'`).
6. Changing `parametry_analityczne.grupa` after a binding exists does NOT cascade — existing bindings retain their old grupa.

**Extend existing: `tests/test_registry.py` (or new `tests/test_registry_grupa.py`)**

7. `get_registry_columns(db, produkt)` for a product whose pipeline includes a `grupa='zewn'` parametry_etapy binding returns that parameter as a column (no filter applied).

**Extend existing: `tests/test_certs.py`**

8. Cert generation for a batch with a `grupa='zewn'`, `on_cert=1` parametr that has a value in `ebr_wyniki` — result string appears in the generated context/PDF.

**Manual smoke (post-deploy):**

9. Through admin UI: create `tpc` with `grupa='zewn'`, bind to a test product, set `on_cert=1` in cert admin, complete a dummy batch, KJ enters value on completed batch, regenerate cert, verify value appears in: cert PDF + `/laborant/szarze` table + batch hero view.

## Open questions

None. All decisions locked in via brainstorming session 2026-04-19.

## References

- Analysis of current state: Explorer agent report in conversation 2026-04-19
- Role definitions: `mbr/shared/decorators.py`, memory note `project_parametry_ssot.md`
- Grupa column precedent: `parametry_etapy.grupa TEXT DEFAULT 'lab'` (from PR1 parametry SSOT migration, 2026-04-16)
