# Operator-Driven Analytical Stages — Design Spec

## Context

The existing pipeline system (`ebr_etap_sesja`, `ebr_pomiar`, `ebr_korekta_v2`, `etap_korekty_katalog`) supports cyclic analytical stages with gate-driven decisions. This redesign shifts control entirely to the operator — no automatic blocks, free navigation between stages, manual transitions.

Target stages: **sulfonowanie → utlenianie → standaryzacja**.

## Core Principles

1. **Operator-driven** — all transitions via explicit click, no automatic blocks
2. **Free navigation** — operator can start from any stage, move freely between stages
3. **Soft close** — closed stages remain editable (reopen on click)
4. **Corrections as formal orders** — multi-substance support per order

---

## 1. Stage Status Model

Replaces per-session statuses (`ok`, `poza_limitem`, `oczekuje_korekty`) with per-stage statuses:

```
nierozpoczety → w_trakcie → zamkniety
```

| Status | Trigger | Meaning |
|--------|---------|---------|
| `nierozpoczety` | Default | Stage visible in chartflow, no data |
| `w_trakcie` | First measurement saved | Active, operator working |
| `zamkniety` | Operator clicks "Zamknij etap" | Soft-closed, editable — click reopens to `w_trakcie` |

Sessions (`ebr_etap_sesja`) remain as round containers but do not block navigation. Operator can create new rounds freely.

---

## 2. Stage Workflows

All three stages follow the same cycle:

```
[Oznaczenie] → [Decyzja operatora] → [Zlecenie korekty + nowa runda] lub [Zamknij etap]
```

### Sulfonowanie
- **Oznaczenie:** pomiar SO3 (%)
- **Korekta:** Na2SO3 — ilość podawana ręcznie
- **Przejście:** operator zamyka etap → przechodzi do utleniania

### Utlenianie
- **Oznaczenie:** pomiar po dodaniu H2O2 (utlenienie siarczynów)
- **Korekta:** H2O2 — ilość z formuły (edytowalna)
- **Przejście:** operator zamyka → przechodzi do standaryzacji

### Standaryzacja
- **Operator podaje ilości dodatków** w jednym zleceniu: H2O, H2O2, NaCl, kwas cytrynowy, HCl
- **Czeka na próbkę**, oznaczenie
- **Korekta:** dodatkowe zlecenie (kolejna runda) lub zamknięcie = koniec procesu

---

## 3. Corrections — Multi-Substance Orders

### New table: `ebr_korekta_zlecenie`

Groups multiple correction items into a single order:

```sql
CREATE TABLE ebr_korekta_zlecenie (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sesja_id    INTEGER NOT NULL REFERENCES ebr_etap_sesja(id),
    zalecil     TEXT NOT NULL,
    dt_zalecenia TEXT NOT NULL DEFAULT (datetime('now')),
    dt_wykonania TEXT,
    status      TEXT NOT NULL DEFAULT 'zalecona',  -- zalecona / wykonana / anulowana
    komentarz   TEXT
);
```

### Extended: `ebr_korekta_v2`

Two new columns:

| Column | Type | Purpose |
|--------|------|---------|
| `zlecenie_id` | INTEGER REFERENCES ebr_korekta_zlecenie(id) | Groups items into one order |
| `ilosc_wyliczona` | REAL | Formula-computed value (NULL if manual) |

`zlecenie_id` is nullable — existing rows from before this migration will have `zlecenie_id = NULL`.

- Sulfonowanie: order with 1 item (Na2SO3)
- Standaryzacja: order with 2-5 items (H2O, H2O2, NaCl, etc.)
- `ilosc_wyliczona` preserves formula suggestion; `ilosc` is final value (operator may override)

### Formulas

Remain in `etap_korekty_katalog.formula_ilosc`. Active for now only for: **H2O2, H2O, NaCl**. Other substances (Na2SO3, kwas cytrynowy, HCl) — manual input.

---

## 4. Rename: target → spec_value

### DB columns renamed:
- `etap_parametry.target` → `etap_parametry.spec_value`
- `produkt_etap_limity.target` → `produkt_etap_limity.spec_value`

### Code impact:
- `pipeline/models.py`: `resolve_limity()`, queries
- `pipeline/adapter.py`: context building
- Frontend: "Cele" panel → "Specyfikacja" panel, `saveTarget()` → `saveSpec()`

### Migration:
```sql
ALTER TABLE etap_parametry RENAME COLUMN target TO spec_value;
ALTER TABLE produkt_etap_limity RENAME COLUMN target TO spec_value;
```

---

## 5. Frontend Changes

### Chartflow
- No navigation changes — existing interactive chartflow
- Stage status colors: nierozpoczęty (gray), w_trakcie (blue), zamknięty (green)

### Stage Panel Contents
1. **Header:** stage name + status badge + round number
2. **Measurements table:** input fields for results (as current)
3. **Specyfikacja panel** (right side): spec_value readonly display
4. **Decision buttons:**
   - **"Zlecenie korekty"** → opens form:
     - Substance list from catalog for this stage
     - Each: quantity field (prefilled from formula if available, editable)
     - Checkbox per substance (standaryzacja: select multiple)
     - "Zleć" button
   - **"Zamknij etap"** → status → zamknięty, highlights next stage in chartflow

### Round History
- Below active round: collapsible list of previous rounds
- Each round shows: measurements + correction order that led to it
- Operator can click old round and edit measurements

### Reopen Closed Stage
- Click on closed stage → status reverts to `w_trakcie`, full editing enabled

---

## 6. Backend — Endpoints

### Modified:

**`POST /pipeline/save-measurements`**
- On first measurement in stage: auto-set status to `w_trakcie`
- Remove automatic gate evaluation as blocker
- Gate evaluation optionally returned as advisory in response

**`POST /pipeline/decision`** — simplified:
- `zamknij_etap`: status → zamknięty
- `reopen_etap`: status → w_trakcie

### New:

**`POST /pipeline/zlecenie-korekty`**
- Input: `sesja_id`, `items: [{korekta_typ_id, ilosc}]`, `komentarz`
- Creates `ebr_korekta_zlecenie` + N rows in `ebr_korekta_v2`
- For items with formula: computes `ilosc_wyliczona`, returns in response

**`POST /pipeline/wykonaj-korekte`**
- Input: `zlecenie_id`
- Sets `status=wykonana`, `dt_wykonania`
- Creates new session (runda +1) for the stage

**`GET /pipeline/formula-hint`**
- Input: `etap_id`, `korekta_typ_id`, current measurements
- Returns computed quantity from formula — frontend shows as prefill

### Removed logic:
- `evaluate_gate()` as blocker (may remain as advisory helper)
- Automatic `oczekuje_korekty` / `poza_limitem` status setting
- Enforced session ordering

---

## 7. Out of Scope

- Automatic validations / blocks
- Certificate impact of target → spec_value rename (separate task)
- New formulas beyond H2O2, H2O, NaCl
- Audit log changes (existing `log_event()` calls remain)
