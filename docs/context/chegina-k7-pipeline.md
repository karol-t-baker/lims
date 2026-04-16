# Chegina K7 — Pipeline Context

> Single source of truth for K7 pipeline: stages, parameters, gates, corrections, UI flow.
> Last updated: 2026-04-15

## Overview

Chegina K7 has a **3-stage cyclic pipeline**:

| # | Stage | etap_id | typ_cyklu | sekcja_lab |
|---|-------|---------|-----------|------------|
| 1 | Sulfonowanie | 4 | cykliczny | `sulfonowanie` |
| 2 | Utlenienie | 5 | cykliczny | `utlenienie` |
| 3 | Standaryzacja | 9 | cykliczny | `analiza` (main cykliczny) |

Standaryzacja is the **last cykliczny** stage → gets `sekcja_lab = "analiza"` (main cyclic key for round cycling UI). Other stages use their `kod` as `sekcja_lab`.

---

## Stage Parameters & K7 Limits

### Sulfonowanie (etap_id=4)

**Parameters:** pH 10%, SO₃, nD20, barwa I₂, barwa Hz, mętność FAU

**K7 limits:** SO₃ min=0.09, barwa_I₂ min=0.0

**Gate:** `so3 >= 0.09`

**Corrections:** Na2SO3 (siarczyn sodu) (kg), Perhydrol 34% (kg, `jest_przejscie=1`)

### Utlenienie (etap_id=5)

**Parameters:** pH 10%, SO₃, nadtlenki, H₂O₂, nD20, barwa I₂, barwa Hz, mętność FAU, NaCl

**K7 limits:** nadtlenki 0.002–0.005, SO₃ max=0.0

**Gate:** `so3 w_limicie` AND `nadtlenki w_limicie` (product-specific limits)

**Corrections:** Perhydrol 34%, Woda, Kwas cytrynowy

### Standaryzacja (etap_id=9)

**Parameters:** SM, pH 10%, NaCl, SA, nD20 (precision=4)

**K7 limits:**

| Param | Min | Max | Gate? |
|-------|-----|-----|-------|
| SM | 40.0 | 48.0 | no |
| pH 10% | 5.5 | 6.5 | **yes** (`w_limicie`) |
| NaCl | 4.0 | 8.0 | no |
| SA | 30.0 | 42.0 | no |
| nD20 | 1.3922 | 1.3925 | **yes** (`w_limicie`) |

**Gate:** `ph_10proc w_limicie` AND `nd20 w_limicie`

The `w_limicie` operator checks the pre-computed `w_limicie` flag from `ebr_pomiar` (set during `save_pomiar()` against product-specific limits). It does NOT use hardcoded values from `etap_warunki`.

**Corrections:** Woda (kg), NaCl (kg), Kwas cytrynowy (kg)

**Correction targets (korekta_cele):** `target_nd20 = 1.3922`, `target_ph = 6.0`

---

## Gate Decisions

### Sulfonowanie
- **PASS:** `next_stage` → advance to utlenienie
- **FAIL:** `new_round` → add sulfite + re-test

### Utlenienie
- **PASS:** `next_stage` → advance to standaryzacja
- **FAIL:** `new_round` (perhydrol + re-test) or `skip_to_next` (move correction to standaryzacja)

### Standaryzacja
- **PASS:** `release` → approve batch
- **FAIL:** `new_round` (correction + re-test), `release_comment` (release with note), `close_note` (close with note)

---

## Round Inheritance

`create_round_with_inheritance()` copies measurements from previous round where `w_limicie = 1` or `w_limicie IS NULL`. Out-of-limit params (`w_limicie = 0`) must be re-measured.

Example: pH OK (inherited) + nD20 FAIL (re-measure after water correction).

---

## Correction Panels

### Sulfonowanie FAIL
Dedicated banner with sulfite input + "Nowa runda" button.

### Utlenienie PASS/FAIL
Perhydrol panel (`_renderPerhydrolPanel`) with SO₃/nadtlenki formula calculation.

### Standaryzacja PASS/FAIL
`_renderStandaryzacjaV2Panel` — unified panel for both PASS and FAIL:

**Fields:**
1. nD20 wynik, pH wynik, masa efektywna (readonly)
2. Docelowe nD20, docelowe pH (editable, saved globally)
3. Woda — dawka sugerowana (auto-calc from refrakcja)
4. Kwas cytrynowy — dawka sugerowana (acid model)
5. Woda [kg], Kwas cytrynowy [kg] (manual override)
6. **Woda łącznie [kg]** (sum of woda + kwas, auto-updated)

**PASS action:** "Zatwierdź etap →" (`advanceWithStandV2`)
**FAIL action:** "Zaleć korektę + nowa runda →" (`advanceStandNewRound`)

### Water Formula
```
Woda = (R0 - Rk) × Meff / (Rk - 1.333)
  R0 = measured nD20
  Rk = target nD20 (1.3922)
  Meff = masa > 6600 ? masa - 1000 : masa - 500
```

### Acid Model (kwas cytrynowy)
```
kwas = -524.86 + 0.010864 × masa_eff + 9.2878 × ΔpH + 33.218 × pH_start + 488181 / masa_kg
```
- Trained: 45 obs (data/kwas.csv), LOO-CV MAE = 5.06 kg, MAPE = 6.1%
- `masa_eff = Meff + woda_kg`
- Includes `1/masa` term for non-linear buffering in smaller batches

---

## Pipeline Adapter

**File:** `mbr/pipeline/adapter.py` → `build_pipeline_context()`

Transforms DB catalog into frontend-ready `etapy_json` + `parametry_lab`:

```python
# Last cykliczny stage = main → sekcja_lab = "analiza"
# Other cykliczny stages → sekcja_lab = stage kod
# etap_entry includes: nr, nazwa, kod, sekcja_lab, pipeline_etap_id, typ_cyklu, decyzje_pass/fail
```

Product-specific parameter filtering: only params with entries in `produkt_etap_limity` are shown.

**Dual-write:** `pipeline_dual_write()` — after `save_wyniki`, writes to `ebr_pomiar` and evaluates gate.

---

## Session Lifecycle

```
nierozpoczety → (first measurement saved) → w_trakcie → (decision made) → zamkniety
```

Table: `ebr_etap_sesja` (UNIQUE: ebr_id + etap_id + runda)

---

## Event Log (Dziennik Zdarzeń)

`_loadPipelineRoundHistory()` loads from `/api/pipeline/lab/ebr/<ebr_id>/etap/<etap_id>` and renders `_renderRoundCards()` showing:
- Round number + measurement badges (OK/poza)
- Measurement values table (expandable)
- Corrections after each round (substancja + ilość + zalecił)

---

## Key Files

| File | Purpose |
|------|---------|
| `mbr/etapy/config.py` | Stage config (labels, corrections per product) |
| `mbr/pipeline/adapter.py` | DB catalog → UI context transform |
| `mbr/pipeline/models.py` | CRUD, gate evaluation, formula resolution |
| `mbr/pipeline/lab_routes.py` | REST API (start/close/pomiary/korekta) |
| `mbr/templates/laborant/_correction_panel.html` | Correction auto-calc panels + acid model |
| `mbr/templates/laborant/_fast_entry_content.html` | Main stage rendering + gate banners |
| `scripts/setup_standaryzacja.py` | Setup standaryzacja stage for products |
| `migrate_standaryzacja_k7.py` | K7-specific: nD20 param, gate, limits |
| `data/kwas.csv` | Training data for acid model (45 obs) |

---

## Example Flow: K7 Standaryzacja FAIL → New Round

1. Measure: pH=5.8 (✓ in 5.5–6.5), nD20=1.390 (✗ out of 1.3922–1.3925)
2. Gate FAIL → `_renderStandaryzacjaV2Panel` with badge KOREKTA
3. Auto-calc: Water = (1.390 - 1.3922) × 6000 / (1.3922 - 1.333) → negative → 0 kg
4. User enters water manually, clicks "Zaleć korektę + nowa runda"
5. `advanceStandNewRound`: save corrections → close session → create round 2
6. Round 2: pH inherited (5.8), nD20 re-measured after correction
7. nD20 = 1.3923 → Gate PASS → "Zatwierdź etap" → batch released
