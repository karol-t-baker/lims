# Parameter Centralization Design

**Date**: 2026-04-12
**Status**: Draft
**Goal**: Single source of truth for all parameter data — eliminate duplication across `parametry_analityczne`, `metody_miareczkowe` (inline copies), `parametry_cert`, and `etapy/config.py`.

## Problem

Parameters live in 5 places with overlapping data:

| Layer | Stores | Duplication |
|---|---|---|
| `parametry_analityczne` | kod, label, typ, inline metoda, formula, name_en | Metoda duplicated from `metody_miareczkowe` |
| `metody_miareczkowe` | Structured titration methods | Source of truth, but inline copies exist |
| `parametry_etapy` | Per-product limits, binding to stages | OK — legitimate per-product config |
| `parametry_cert` | name_pl/en, method, requirement per product | Duplicates from `parametry_analityczne` |
| `parametry_lab` JSON | MBR snapshot | Cache — acceptable if rebuild works |

Consequences: data drifts out of sync, cert editor can add parameters not in analysis, method edits don't propagate.

## Target Data Model

### `parametry_analityczne` — Global Parameter Registry (SSOT)

Changes from current:
- **Added**: `typ = 'jakosciowy'` (qualitative parameters: odour, appearance)
- **Removed**: `metoda_nazwa`, `metoda_formula`, `metoda_factor` (inline duplicates → read from FK `metoda_id` to `metody_miareczkowe`)
- **Unchanged**: `kod`, `label`, `skrot`, `name_en`, `typ`, `metoda_id`, `formula`, `precision`, `aktywny`, `jednostka`, `method_code`

Display convention:
- **Analysis/EBR UI**: shows `skrot` (short: `SM`, `pH`, `%SA`)
- **Certificates**: shows `label` as name_pl, `name_en` as name_en

### `metody_miareczkowe` — Titration Methods (SSOT)

No structural changes. Single place for CRUD of titration methods (formula, titrants, volumes). Referenced by `parametry_analityczne.metoda_id` FK.

### `parametry_etapy` — Per-Product Parameter Binding (extended)

New columns for cert configuration:

| Column | Type | Description |
|---|---|---|
| `cert_requirement` | TEXT | Requirement text on cert (e.g. `"min 35,5"`) |
| `cert_format` | TEXT | Decimal places on cert (`"0"`, `"1"`, `"2"`) |
| `cert_qualitative_result` | TEXT | Fixed text result for qualitative params |
| `cert_kolejnosc` | INTEGER | Display order on cert (may differ from analysis order) |
| `on_cert` | INTEGER DEFAULT 0 | Whether param appears on certificate |
| `cert_variant_id` | INTEGER | FK to `cert_variants.id` — NULL=base, NOT NULL=variant-specific addition |

Existing columns unchanged: `parametr_id`, `produkt`, `kontekst`, `krok`, `min_limit`, `max_limit`, `target`, `nawazka_g`, `kolejnosc`, `formula`, `sa_bias`.

### `parametry_cert` — Eliminated (Phase 4)

All data migrated to `parametry_etapy`. Table dropped.

### `cert_variants` — Unchanged

Keeps: `remove_params` (JSON array of parametr_id ints), flags, variant metadata (spec_number, opinion_pl/en, avon_code/name). No `add_parameters` — those move to `parametry_etapy` with `cert_variant_id`.

### `ebr_wyniki` — Unchanged

`kod_parametru` remains a string key without FK. Historical immutability preserved.

### `parametry_lab` JSON — Unchanged structure

Still a denormalized cache in MBR. `build_parametry_lab()` updated to read titration method from `metody_miareczkowe` via FK instead of inline columns.

## Data Flow

### Analysis / EBR (laborant)

```
parametry_etapy (kontekst='analiza_koncowa', produkt=X)
  → JOIN parametry_analityczne (skrot, typ, precision, formula)
  → JOIN metody_miareczkowe (formula, titrants, volumes) via metoda_id
  → snapshot to parametry_lab JSON in active MBR
  → laborant sees: skrot, limits, titration calculator
```

### Certificate Generation

```
parametry_etapy WHERE on_cert=1 AND kontekst='analiza_koncowa' AND cert_variant_id IS NULL
  → JOIN parametry_analityczne (label→name_pl, name_en, method_code)
  → cert_requirement, cert_format, cert_qualitative_result from parametry_etapy
  → result from ebr_wyniki via kod
  → cert_variants: apply remove_params filter
  → UNION parametry_etapy WHERE cert_variant_id = <variant.id>
  → ordered by cert_kolejnosc
```

### Admin Editor

```
Tab Rejestr:   CRUD parametry_analityczne
Tab Metody:    CRUD metody_miareczkowe
Tab Etapy:     CRUD parametry_etapy (limits + cert config + on_cert flag)
Tab Produkty:  CRUD produkty
```

Certificate editor (`/admin/wzory-cert`) reads `parametry_etapy WHERE kontekst='analiza_koncowa' AND on_cert=1`. Cannot add parameters not in analiza_koncowa. Admin sets `cert_requirement`, `cert_format`, `cert_kolejnosc`.

## Variant Handling

Base parameters:
```
parametry_etapy WHERE kontekst='analiza_koncowa' AND cert_variant_id IS NULL AND on_cert=1
```

Variant-specific additions:
```
parametry_etapy WHERE kontekst='cert_variant' AND cert_variant_id = <variant.id>
```

Generator builds cert parameter list:
1. Load base params with `on_cert=1`
2. Filter out `remove_params` from variant
3. Append variant-specific params
4. Order by `cert_kolejnosc`

## Migration Phases

### Phase 1: Extend `parametry_etapy` + migrate cert data

- ALTER TABLE `parametry_etapy`: add `cert_requirement`, `cert_format`, `cert_qualitative_result`, `cert_kolejnosc`, `on_cert`, `cert_variant_id`
- Migration script: for each `parametry_cert` row (base, `variant_id IS NULL`) → find matching `parametry_etapy` record (same `produkt` + `parametr_id` + `kontekst='analiza_koncowa'`) → copy requirement, format, qualitative_result, set `on_cert=1`. If no matching record exists (cert-only params like qualitative "zapach"), INSERT new `parametry_etapy` row with `on_cert=1`, zero limits, `kontekst='analiza_koncowa'`
- Variant `add_parameters` → INSERT into `parametry_etapy` with `kontekst='cert_variant'`, `cert_variant_id`
- Cert generator: read from `parametry_etapy` first, fallback to `parametry_cert`
- `parametry_cert` remains as fallback
- Tests: verify cert PDF output unchanged

### Phase 2: Remove inline titration method columns

- `build_parametry_lab()`: read method from `metody_miareczkowe` via FK, not inline columns
- Verify all `typ='titracja'` params have `metoda_id` set
- Remove columns: `metoda_nazwa`, `metoda_formula`, `metoda_factor` from `parametry_analityczne`
- Remove startup fixup in `app.py` (metoda_id backfill)
- Tests: verify titration calculator still works, MBR rebuild produces same output

### Phase 3: Process steps from DB

- Remove `parametry` lists from `kroki` in `etapy/config.py`
- Stage routes read parameters from `parametry_etapy WHERE krok=N`
- Etapy UI: allow assigning parameters to steps
- Tests: verify stage analysis flow unchanged

### Phase 4: Cleanup

- Cert generator: remove `parametry_cert` fallback
- DROP TABLE `parametry_cert`
- Remove related routes, models, tests
- Certificate editor: rebuild to read from `parametry_etapy`
- Re-export `cert_config.json` from new source
- Tests: full regression on cert generation

## Key Constraints

- **No breaking change to cert PDF output** — each phase must produce identical certificates
- **Historical data immutable** — `ebr_wyniki.kod_parametru` stays as string, no FK
- **`parametry_lab` JSON remains a cache** — rebuilt on any parameter/binding change
- **Idempotent migrations** — each phase's migration script safe to run multiple times
- **Each phase independently deployable** — fallbacks ensure partial deploy works

## Files Affected

| File | Phase | Change |
|---|---|---|
| `mbr/models.py` | 1,2 | Schema DDL, migrations |
| `mbr/parametry/registry.py` | 1,2 | `build_parametry_lab()`, `get_parametry_for_kontekst()` |
| `mbr/parametry/routes.py` | 1,2,4 | Cert binding endpoints |
| `mbr/certs/generator.py` | 1,4 | `build_context()` reads from new source |
| `mbr/certs/routes.py` | 1,4 | Cert config PUT endpoint |
| `mbr/etapy/config.py` | 3 | Remove hardcoded parameter lists |
| `mbr/etapy/routes.py` | 3 | Read step params from DB |
| `mbr/templates/parametry_editor.html` | 1,4 | Cert tab reads from parametry_etapy |
| `mbr/templates/admin/wzory_cert.html` | 4 | Rebuild to use parametry_etapy |
| `mbr/app.py` | 2 | Remove metoda_id fixup |
| `mbr/laborant/models.py` | 2 | `_apply_skroty()`, limit resolution |
