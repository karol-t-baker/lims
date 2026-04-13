# Correction Context & Formula Resolve — Design Spec

## Context

The operator-driven analytical stages (sulfonowanie→utlenianie→standaryzacja) need contextual data visible when ordering corrections. Operators must see batch mass, measurements, spec values, and formula breakdowns to make informed decisions. Formulas already exist in `etap_korekty_katalog` with encoded variable references — they need a resolver.

## Core Principles

1. **Backend resolves everything** — one endpoint gathers all variables (measurements, specs, batch data), evaluates formulas, returns results + breakdown
2. **Operator sees the math** — not just "18.2 kg" but where it came from
3. **Editable reduction** — Meff (effective mass) uses a default reduction formula, but operator can override

---

## 1. New Endpoint: `POST /api/pipeline/lab/ebr/<ebr_id>/formula-resolve`

### Request
```json
{
  "korekta_typ_id": 4,
  "etap_id": 5,
  "sesja_id": 123,
  "redukcja_override": 800
}
```

`redukcja_override` is optional. When absent, reduction is computed from the expression in `formula_zmienne["Meff"]`.

### Response
```json
{
  "ok": true,
  "wynik": 18.2,
  "zmienne": {
    "wielkosc_szarzy_kg": 13300,
    "redukcja": 1000,
    "Meff": 12300,
    "C_so3": 0.05,
    "target_so3": 0.03,
    "target_nadtlenki": 0.005
  },
  "labels": {
    "wielkosc_szarzy_kg": "Masa szarży",
    "redukcja": "Redukcja",
    "Meff": "Masa efektywna",
    "C_so3": "Pomiar SO₃",
    "target_so3": "Spec SO₃",
    "target_nadtlenki": "Spec nadtlenki"
  }
}
```

If formula is missing or a required variable can't be resolved, return `"wynik": null` with partial `zmienne` (resolved values filled in, unresolved as `null`).

---

## 2. Variable Resolver: `resolve_formula_zmienne()`

New function in `mbr/pipeline/models.py`.

### Variable reference types in `formula_zmienne` JSON

| Pattern | Source | Example |
|---------|--------|---------|
| `pomiar:{kod}` | Measurement from current or previous stage session | `pomiar:so3` → 0.05 |
| `target:{kod}` | `spec_value` from `produkt_etap_limity` for the correction's stage | `target:so3` → 0.03 |
| `wielkosc_szarzy_kg` | Field from `ebr_batches` | 13300 |
| Expression with ternary | Evaluated after other variables resolved (Meff) | `wielkosc_szarzy_kg > 6600 ? wielkosc_szarzy_kg - 1000 : wielkosc_szarzy_kg - 500` |
| Unrecognized string | Passed through as-is (assumed numeric literal or ignored) | `0.01214` → 0.01214 |

### Measurement lookup order for `pomiar:{kod}`

1. Current session (`sesja_id` from request) — if it has a measurement for `{kod}`, use it
2. Walk backwards through pipeline stages (by `kolejnosc`) — find the most recent session with a measurement for `{kod}`
3. If not found anywhere → `null`

This handles the key case: utlenianie's formula references `pomiar:so3`, which may come from sulfonowanie's last session.

### Meff and editable reduction

The `Meff` variable in `formula_zmienne` is an expression (e.g., `wielkosc_szarzy_kg > 6600 ? wielkosc_szarzy_kg - 1000 : wielkosc_szarzy_kg - 500`).

Resolution:
1. If `redukcja_override` is provided: `Meff = wielkosc_szarzy_kg - redukcja_override`, `redukcja = redukcja_override`
2. If no override: evaluate the Meff expression, then derive `redukcja = wielkosc_szarzy_kg - Meff`

Both `Meff` and `redukcja` are returned in `zmienne` — frontend displays `redukcja` as editable.

### Label generation

Labels are generated from variable names using a static mapping:

```python
VARIABLE_LABELS = {
    "wielkosc_szarzy_kg": "Masa szarży",
    "redukcja": "Redukcja",
    "Meff": "Masa efektywna",
}
```

For `pomiar:{kod}` and `target:{kod}`, labels are derived from `parametry_analityczne.label`:
- `C_so3` (resolved from `pomiar:so3`) → "Pomiar SO₃" (prefix "Pomiar" + parameter label)
- `target_so3` (resolved from `target:so3`) → "Spec SO₃" (prefix "Spec" + parameter label)

---

## 3. Frontend: Correction Form with Context

### Flow

1. Operator clicks "Zlecenie korekty"
2. Frontend fetches correction catalog (`GET /korekty-katalog`)
3. For each substance WITH formula: `POST /formula-resolve` → gets breakdown
4. Renders form with context section + per-substance detail

### Layout

```
┌─ Zlecenie korekty — [Etap], runda [N] ────────────────┐
│                                                         │
│  KONTEKST:                                              │
│  Masa szarży:     13 300 kg                             │
│  Redukcja:        [1000] kg  ← editable input           │
│  Masa efektywna:  12 300 kg  ← recalculated on change   │
│                                                         │
│  ─────────────────────────────────────────────────────  │
│  ☑ Perhydrol 34%                                kg      │
│    Pomiar SO₃:       0.05%                              │
│    Spec SO₃:         0.03%                              │
│    Spec nadtlenki:   0.005%                             │
│    Wyliczone:        18.2 kg                            │
│    Ilość:            [18.2]  ← prefilled, editable      │
│                                                         │
│  ─────────────────────────────────────────────────────  │
│  ☑ Na2SO3                                      kg      │
│    (brak formuły — wpisz ręcznie)                       │
│    Ilość:            [    ]                              │
│                                                         │
│  Komentarz: [________________________]                  │
│  [Zleć]  [Anuluj]                                       │
└─────────────────────────────────────────────────────────┘
```

### Reduction edit behavior

When operator changes the "Redukcja" field:
1. Frontend sends `POST /formula-resolve` with `redukcja_override` for EACH substance with formula
2. Updates "Masa efektywna" and "Wyliczone" values
3. Updates prefilled "Ilość" (only if operator hasn't manually edited it)

### Substances without formula

Show the same context block (masa, redukcja, Meff) at the top, but the substance section only has the manual quantity input with a note "(brak formuły — wpisz ręcznie)".

### Standaryzacja — multiple substances

Context block shown once at top. Each substance (Woda, NaCl, Kw. cytrynowy) has its own expandable section with relevant measurements/specs/calculation.

---

## 4. Scope

### In scope
- `POST /formula-resolve` endpoint with full variable resolution
- `resolve_formula_zmienne()` function with `pomiar:`, `target:`, batch field, expression support
- Measurement lookup across pipeline stages (current → previous)
- Editable reduction with live recalculation
- Frontend correction form with context display

### Out of scope
- Dashboard display of stage data (separate feature)
- New formulas beyond what's in `etap_korekty_katalog`
- Changes to `submitCorrectionOrder()` (still sends `ilosc` as before)
- Old `GET /formula-hint` endpoint (stays for backward compat)
- Validation of measurement correctness
