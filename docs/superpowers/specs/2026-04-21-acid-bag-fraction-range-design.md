# Acid Dose — Bag-Fraction Range Display

Status: Draft for user review
Date: 2026-04-21
Scope: Single JS function in correction panel. No backend changes.

## Motivation

The existing acid-dose suggestion widget in `_correction_panel.html` shows
a single number (e.g. `87,5 kg`). Production dispenses citric acid from
25 kg bags that can be subdivided into 4 quarters (6.25 kg each), so the
lab laborant has to mentally round the model's number to a bag-aligned
dose. The value that lands in the manual input box is the raw model
output, which is rarely exactly achievable on the floor.

## Goal

Replace the single-number display with a compact range that shows:
- The model's suggestion (rounded to integer),
- The nearest bag-fraction-aligned dose below,
- The nearest bag-fraction-aligned dose at or above.

Example: model outputs 87 kg → display `87 (81,25–87,5)`.

Auto-fill into the manual input box uses the **upper bound** (`over`) so
the operator sees a realistically-dispensable number by default.

## Non-goals

- No admin configuration. Bag size and divisions are hardcoded in JS as
  `const BAG_KG = 25`, `const BAG_DIVISIONS = 4` (unit = 6.25 kg).
- No change to `_acidModelPredict` — the underlying model stays as-is.
- No change to water or other additive suggestions.
- No change to the audit/save path — manual input still saves the
  user-visible number verbatim.
- No per-product overrides. All products using this widget get the same
  bag parameters.

## Design

### Where the change lives

`mbr/templates/laborant/_correction_panel.html`, the block starting at
line 410 (`var kwasCalcEl = document.getElementById('corr-kwas-calc-...')`)
inside `recomputeStandV2`. Only this one function changes.

### Constants

Declared once at module scope in the same template (near existing
helpers at the top of the `<script>` block):

```javascript
var BAG_KG = 25;          // citric acid bag size
var BAG_DIVISIONS = 4;    // quarters per bag
var BAG_UNIT = BAG_KG / BAG_DIVISIONS;  // 6.25 kg
```

### Helper function

New helper `_bagFractionRange(kwas)` returns `{under, over, model}`:

```javascript
function _bagFractionRange(kwas) {
    if (!isFinite(kwas) || kwas <= 0) return null;
    var under = Math.floor(kwas / BAG_UNIT) * BAG_UNIT;
    var over  = Math.ceil(kwas / BAG_UNIT) * BAG_UNIT;
    return {under: under, over: over, model: kwas};
}
```

If `kwas` lands exactly on a boundary, `under === over` — render with
only one value: `87,5 (87,5)`.

### Formatting helpers

Polish decimals with trailing-zero stripping:

```javascript
function _fmtKg(n) {
    // 81.25 → "81,25", 87.5 → "87,5", 100 → "100"
    return parseFloat(n.toFixed(2)).toString().replace('.', ',');
}
```

### New display logic

Replaces lines 422–428 in `recomputeStandV2`:

```javascript
if (kwas !== null) {
    var range = _bagFractionRange(kwas);
    if (range) {
        var modelFmt = Math.round(range.model).toString();
        var underFmt = _fmtKg(range.under);
        var overFmt  = _fmtKg(range.over);
        var rangeStr = (range.under === range.over)
            ? overFmt
            : underFmt + '–' + overFmt;  // en-dash
        kwasCalcEl.textContent = modelFmt + ' (' + rangeStr + ') kg';
        if (kwasManEl) {
            kwasManEl.dataset.suggested = range.over.toFixed(2);
            if (!kwasManEl.value) kwasManEl.value = overFmt;
        }
    } else {
        kwasCalcEl.textContent = '— kg';
    }
} else {
    kwasCalcEl.textContent = '— kg';
}
```

Notes:
- `dataset.suggested` is set to the `over` value with 2 decimals (used
  programmatically downstream if anything reads it back).
- Manual input auto-fill uses the formatted `over` (e.g., `"87,5"`).
- Dash between range values is en-dash (`–`, U+2013) for typographic
  correctness — matches the existing `norm-range` convention in the hero.

## Error handling

- Model returns `null` (invalid pH/masa) → display stays `— kg` as today.
- `kwas <= 0` → `_bagFractionRange` returns `null` → display stays `— kg`.
- No bag parameters configured → cannot happen; constants are hardcoded.

## Testing

No Python tests (this is pure-template JS with no unit test harness).
Manual smoke test:

1. Enter a correction session for a K7 batch in standaryzacja.
2. Set `corr-ph-*` to 11.8 and `corr-target-ph-*` to 6.0.
3. Observe `corr-kwas-calc-*` shows format `X (A,B–C,D) kg`.
4. Confirm manual input `corr-manual-kwas-*` auto-fills with `C,D`.
5. Edge case: if the model happens to output a value exactly divisible
   by 6.25 kg, display shows `X (Y,Y) kg` — single value in parens.

## Risks

- **Bag constants change** (new supplier, different bag size): fix
  requires editing two JS constants. Low risk, trivially changed.
- **Operators overrode dose previously stored at `kwas.toFixed(1)`
  precision**; new `dataset.suggested` stores at `.toFixed(2)`.
  Impact: downstream consumers of `dataset.suggested` now get 2
  decimal places instead of 1. `grep` the codebase for `data-suggested`
  / `dataset.suggested` usage during implementation; adjust consumers
  if they parse with a specific decimal-place expectation. No action
  needed if consumers do numeric parsing.

## Open questions

None. All three decisions confirmed in chat 2026-04-21:
- Bag parameters: 25 kg / 4 parts (unit = 6.25 kg).
- Auto-fill: `over` (upper bound).
- Scope: only acid (citric), hardcoded JS constants, no admin UI.
