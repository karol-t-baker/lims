# ML Data Export for K7 Pipeline — Design Spec

## Goal

Endpoint that exports completed K7 batch data as a flat CSV ready for ML/DL. One row per batch, all pipeline stages (sulfonowanie → utlenienie → standaryzacja) denormalized into columns. Supports incremental download so subsequent fetches only return new batches.

## Data Source

Primary: `ebr_pomiar` (per-session measurements) + `ebr_korekta_v2` (corrections).
Secondary: `ebr_batches` (metadata), `ebr_etap_sesja` (session structure).

`ebr_wyniki` is NOT used — it's a denormalized summary that loses multi-round history. We read directly from pipeline tables for full fidelity.

## CSV Schema

### Metadata columns

| Column | Type | Source | Description |
|--------|------|--------|-------------|
| `ebr_id` | int | ebr_batches.ebr_id | Primary key, used for incremental sync |
| `batch_id` | str | ebr_batches.batch_id | e.g. "Chegina_K7__1_2026" |
| `nr_partii` | str | ebr_batches.nr_partii | "1/2026" |
| `masa_kg` | float | ebr_batches.wielkosc_szarzy_kg | Batch mass |
| `meff_kg` | float | computed | masa > 6600 ? masa - 1000 : masa - 500 |
| `dt_start` | str | ebr_batches.dt_start | ISO timestamp |
| `dt_end` | str | ebr_batches.dt_end | ISO timestamp |

### Sulfonowanie columns (etap kod=sulfonowanie)

| Column | Type | Source | Description |
|--------|------|--------|-------------|
| `sulf_na2so3_recept_kg` | float | **NEW FIELD** ebr_wyniki sekcja=sulfonowanie, kod=na2so3_recept_kg | Recipe sulfite addition (from batch card) |
| `sulf_r1_ph` | float | ebr_pomiar session R1 | pH 10% |
| `sulf_r1_nd20` | float | ebr_pomiar session R1 | Refractive index |
| `sulf_r1_so3` | float | ebr_pomiar session R1 | % sulfites |
| `sulf_r1_barwa` | float | ebr_pomiar session R1 | Iodine color |
| `sulf_na2so3_kor_kg` | float | ebr_korekta_v2, substancja='Siarczyn sodu' | Actual sulfite correction (R1) |
| `sulf_perhydrol_kg` | float | ebr_korekta_v2, substancja='Perhydrol 34%', jest_przejscie=1 | Transition perhydrol |
| `sulf_r2_ph` | float/NaN | ebr_pomiar session R2 (if exists) | Round 2 measurements |
| `sulf_r2_nd20` | float/NaN | | |
| `sulf_r2_so3` | float/NaN | | |
| `sulf_r2_barwa` | float/NaN | | |
| `sulf_rundy` | int | count of sessions | Total rounds |

### Utlenienie columns (etap kod=utlenienie)

| Column | Type | Source | Description |
|--------|------|--------|-------------|
| `utl_r1_ph` | float | ebr_pomiar session R1 | pH 10% |
| `utl_r1_nd20` | float | | Refractive index |
| `utl_r1_so3` | float | | % sulfites |
| `utl_r1_barwa` | float | | Iodine color |
| `utl_r1_nadtlenki` | float | | Peroxides |
| `utl_perhydrol_r1_kg` | float | ebr_korekta_v2 R1 | Perhydrol correction R1 |
| `utl_r2_ph` | float/NaN | ebr_pomiar session R2 | Round 2 (if exists) |
| `utl_r2_nd20` | float/NaN | | |
| `utl_r2_so3` | float/NaN | | |
| `utl_r2_barwa` | float/NaN | | |
| `utl_r2_nadtlenki` | float/NaN | | |
| `utl_perhydrol_r2_kg` | float/NaN | ebr_korekta_v2 R2 | Perhydrol correction R2 |
| `utl_woda_kg` | float | ebr_korekta_v2, substancja='Woda' | Water correction (last round) |
| `utl_kwas_kg` | float | ebr_korekta_v2, substancja='Kwas cytrynowy' | Actual citric acid |
| `utl_kwas_sugest_kg` | float | ebr_korekta_v2.ilosc_wyliczona | Model-suggested acid (preserved because model may change) |
| `utl_rundy` | int | count of sessions | Total rounds |

### Standaryzacja columns (etap kod=standaryzacja)

| Column | Type | Source | Description |
|--------|------|--------|-------------|
| `stand_r1_ph` | float | ebr_pomiar session R1 | pH 10% |
| `stand_r1_nd20` | float | | Refractive index |
| `stand_r1_sm` | float | | Dry matter % |
| `stand_r1_nacl` | float | | NaCl % |
| `stand_r1_sa` | float | | Active substance % |
| `stand_woda_kg` | float | ebr_korekta_v2 R1 | Water correction |
| `stand_kwas_kg` | float | ebr_korekta_v2 R1 | Actual citric acid |
| `stand_kwas_sugest_kg` | float | ebr_korekta_v2.ilosc_wyliczona R1 | Model-suggested acid |
| `stand_r2_ph` | float/NaN | ebr_pomiar session R2 | Round 2 (if correction needed) |
| `stand_r2_nd20` | float/NaN | | |
| `stand_r2_sm` | float/NaN | | |
| `stand_r2_nacl` | float/NaN | | |
| `stand_r2_sa` | float/NaN | | |
| `stand_rundy` | int | count of sessions | Total rounds |

### Final result columns (last round of standaryzacja)

| Column | Type | Source | Description |
|--------|------|--------|-------------|
| `final_ph` | float | last standaryzacja session | Final pH |
| `final_nd20` | float | | Final refractive index |
| `final_sm` | float | | Final dry matter |
| `final_nacl` | float | | Final NaCl |
| `final_sa` | float | | Final active substance |
| `final_all_ok` | bool (0/1) | all w_limicie=1 | All params within spec |

## New UI Field: Recepturowy Na2SO3

A single numeric input field in the sulfonowanie stage form, above the analytical parameters. Label: "Recepturowy dodatek Na₂SO₃ [kg]". Stored in `ebr_wyniki` with `sekcja='sulfonowanie'`, `kod_parametru='na2so3_recept_kg'`. No limits, no gate evaluation — informational input only.

## Citric Acid Model Suggestion Persistence

When saving a citric acid correction (substancja='Kwas cytrynowy'), populate `ebr_korekta_v2.ilosc_wyliczona` with the model-computed suggestion at that moment. This preserves the suggestion even if the model coefficients change later.

Implementation: in the JS correction save functions (`advanceStandNewRound`, `advanceWithStandV2`, `advancePerhydrolWithStand`), read the calculated value from `corr-kwas-calc-*` element and include it in the POST body as `ilosc_wyliczona`. Backend `lab_create_korekta` already accepts this field via `create_ebr_korekta`.

## Incremental Download

**Endpoint:** `GET /api/export/ml/k7.csv?after_id=N`

- `after_id=0` or omitted: all completed K7 batches
- `after_id=42`: only batches with `ebr_id > 42`
- Response header `X-Last-Id: <max_ebr_id>` for client to store
- Response `Content-Type: text/csv; charset=utf-8`
- First row is column headers (always included)
- Only `status='completed'` batches with produkt matching K7 pipeline products

**Client workflow:**
1. First download: `GET /api/export/ml/k7.csv` → save CSV, note `X-Last-Id: 55`
2. Next download: `GET /api/export/ml/k7.csv?after_id=55` → append rows to existing CSV (skip header row)

## NaN Handling

Columns for rounds that didn't happen (e.g., `sulf_r2_*` when only 1 round) are empty strings in CSV (pandas reads as NaN). This is standard — tree-based models handle NaN natively, neural nets can impute with 0 or mean.

## Scope

- K7 products only (Chegina_K7, Chegina_K40GL, Chegina_K40GLO, Chegina_K40GLOL — those with sulfonowanie/utlenienie pipeline)
- Max 2 rounds per stage in CSV columns (R1, R2). If a batch has 3+ rounds (rare edge case), R3+ data is silently dropped. This can be extended later.
- No computed features (ratios, deltas) — raw data only. Feature engineering happens in the ML notebook, not in the export.
