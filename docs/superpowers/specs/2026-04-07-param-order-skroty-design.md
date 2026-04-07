# Parameter Order & Skroty — Design Spec

## Goal

Three improvements to the analiza końcowa panel:
1. Show parameter abbreviations (skrot) instead of full names in edit mode
2. Drag & drop reordering of parameters (global per product)
3. Remove year from certificate PDF filename

## 1. Skroty in edit form

**Problem:** Line 1554 in `_fast_entry_content.html` uses `pole.label`. Should use `pole.skrot || pole.label`.

**Fix:** Single line change.

## 2. Drag & drop parameter ordering

**Where:** Parameter editor modal (`openParamEditor` in `_fast_entry_content.html`)

**Current state:**
- `parametry_etapy` table has `kolejnosc` column
- `GET /api/parametry/config` returns params ordered by `kolejnosc`
- `PUT /api/parametry/etapy/<id>` accepts `kolejnosc` field
- `POST /api/parametry/rebuild-mbr` rebuilds `parametry_lab` JSON
- No reorder UI exists

**Design:**
- Add drag handle (⠿ grip icon) to each `ped-row` in the editor modal
- HTML5 Drag API: `draggable="true"`, `dragstart`, `dragover`, `drop` events
- On drop: reorder DOM, recalculate `kolejnosc` values (1, 2, 3...)
- New API endpoint `POST /api/parametry/etapy/reorder` — accepts `{bindings: [{id, kolejnosc}, ...]}` to batch-update all orderings in one request
- After reorder: auto-call rebuild-mbr to regenerate `parametry_lab`
- Order is global per product+kontekst (stored in `parametry_etapy`)

## 3. Certificate PDF filename

**Current:** `{variant_label} {nr_partii.replace('/', '_')}.pdf` → e.g. `Standard 1_2026.pdf`
**New:** `{variant_label} {nr_partii_without_year}.pdf` → e.g. `Standard 1.pdf`

**Where:** `mbr/certs/routes.py` line 108, and `mbr/certs/generator.py` `_cert_names()` function.

`nr_partii` format is `{N}/{YEAR}` (e.g. `1/2026`). Extract just `N` by splitting on `/` and taking first part.

## Files to modify

| File | Change |
|------|--------|
| `mbr/templates/laborant/_fast_entry_content.html` | skrot in edit label + drag & drop JS |
| `mbr/parametry/routes.py` | New `/api/parametry/etapy/reorder` endpoint |
| `mbr/certs/routes.py` | PDF filename without year |
| `mbr/certs/generator.py` | `_cert_names()` without year |
| `tests/test_parametry_registry.py` | Test for reorder endpoint |
| `tests/test_certs.py` | Test for filename change |
