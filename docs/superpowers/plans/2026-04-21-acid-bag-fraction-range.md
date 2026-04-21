# Acid Dose — Bag-Fraction Range Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-number acid-dose suggestion in the correction panel with a format that pairs the raw model output with the nearest achievable bag-fraction doses (e.g. `87 (81,25–87,5) kg` for 25 kg bags ÷ 4).

**Architecture:** One-file JS-only change in `mbr/templates/laborant/_correction_panel.html`. Two new top-level helpers (`_bagFractionRange`, `_fmtKg`) and three constants (`BAG_KG`, `BAG_DIVISIONS`, `BAG_UNIT`). The display block inside `recomputeStandV2` is rewritten to use them. Manual input auto-fills with the `over` bound so operators get a realistically-dispensable default.

**Tech Stack:** Jinja-embedded vanilla JS, no build step. Cache-busting via existing template include chain (template HTML is `no-store`; inline JS refreshes on reload automatically).

---

## File Structure

**Modified (single file):**
- `mbr/templates/laborant/_correction_panel.html` — two new constants + two helper functions added at top of the `<script>` block; one display block inside `recomputeStandV2` rewritten.

No new files. No backend / Python changes. No test harness — this repo has no JS test infrastructure (verified earlier in session); smoke-test is manual in the browser.

---

## Task 1: Add constants and helper functions

**Files:**
- Modify: `mbr/templates/laborant/_correction_panel.html` — add right above `_acidModelPredict` (around line 442).

- [ ] **Step 1: Locate insertion point**

Run: `grep -n "function _acidModelPredict" mbr/templates/laborant/_correction_panel.html`

Expected output: a single line number (around `443`). Note this line — the new code goes immediately above it so `_acidModelPredict` and the new helpers sit together as a group of pricing/math helpers.

- [ ] **Step 2: Insert constants + helpers**

Immediately above the `function _acidModelPredict(phStart, phTarget, masaKg, masaEffKg) {` line, insert:

```javascript
// Citric acid bag-fraction constants. Production dispenses from 25 kg
// bags subdivided into quarters (6.25 kg each) — the suggested dose
// display aligns the model's raw output to the nearest achievable
// quarter boundary so the operator sees a realistically-dispensable
// number instead of a value they'd have to round mentally.
var BAG_KG = 25;
var BAG_DIVISIONS = 4;
var BAG_UNIT = BAG_KG / BAG_DIVISIONS;  // 6.25 kg

function _bagFractionRange(kwas) {
    if (!isFinite(kwas) || kwas <= 0) return null;
    var under = Math.floor(kwas / BAG_UNIT) * BAG_UNIT;
    var over  = Math.ceil(kwas / BAG_UNIT) * BAG_UNIT;
    return {under: under, over: over, model: kwas};
}

function _fmtKg(n) {
    // 81.25 → "81,25", 87.5 → "87,5", 100 → "100".
    // parseFloat drops trailing zeros; toFixed(2) caps at 2 decimals.
    return parseFloat(n.toFixed(2)).toString().replace('.', ',');
}

```

- [ ] **Step 3: Syntax sanity check**

Run: `python3 -c "open('mbr/templates/laborant/_correction_panel.html').read()"`
Expected: no output (file readable as UTF-8).

Also run: `grep -nE '_bagFractionRange|_fmtKg|BAG_UNIT' mbr/templates/laborant/_correction_panel.html`
Expected: ≥ 3 lines — the declarations at the top, and no usages yet (Task 2 adds usages).

- [ ] **Step 4: Do NOT commit yet**

These helpers are dead code until Task 2 wires them in. A single logical commit at the end of Task 2 keeps the change atomic and reviewable.

---

## Task 2: Rewrite the display block

**Files:**
- Modify: `mbr/templates/laborant/_correction_panel.html:412-435` — the `if (kwasCalcEl)` block inside `recomputeStandV2`.

- [ ] **Step 1: Locate the block**

Run: `grep -n "Kwas cytrynowy: Linear" mbr/templates/laborant/_correction_panel.html`

Expected: a single line number (around `406`). The block to rewrite is the one starting 6 lines below that (at `var kwasCalcEl = document.getElementById(...)`).

- [ ] **Step 2: Read the current block**

Use `Read` tool on lines 410–438 of the file. Confirm it matches:

```javascript
    var kwasCalcEl = document.getElementById('corr-kwas-calc-' + sekcja);
    var kwasManEl = document.getElementById('corr-manual-kwas-' + sekcja);
    if (kwasCalcEl) {
        if (!isNaN(ph) && !isNaN(tPh) && !isNaN(Meff) && Meff > 0) {
            var wodaKg = 0;
            if (wodaManEl && wodaManEl.value) {
                wodaKg = _parsePl(wodaManEl.value);
                if (isNaN(wodaKg)) wodaKg = 0;
            }
            var masaEffKg = Meff + wodaKg;
            var masaKg = ebrNastaw || Meff;
            var kwas = _acidModelPredict(ph, tPh, masaKg, masaEffKg);
            if (kwas !== null) {
                var kFmt = kwas.toFixed(1).replace('.', ',');
                kwasCalcEl.textContent = kFmt + ' kg';
                if (kwasManEl) {
                    kwasManEl.dataset.suggested = kwas.toFixed(1);
                    if (!kwasManEl.value) kwasManEl.value = kFmt;
                }
            } else {
                kwasCalcEl.textContent = '— kg';
            }
        } else {
            kwasCalcEl.textContent = '— kg';
        }
    }
```

- [ ] **Step 3: Replace the inner `if (kwas !== null)` branch**

Use `Edit` tool to replace this sub-block:

```javascript
            if (kwas !== null) {
                var kFmt = kwas.toFixed(1).replace('.', ',');
                kwasCalcEl.textContent = kFmt + ' kg';
                if (kwasManEl) {
                    kwasManEl.dataset.suggested = kwas.toFixed(1);
                    if (!kwasManEl.value) kwasManEl.value = kFmt;
                }
            } else {
                kwasCalcEl.textContent = '— kg';
            }
```

With this new version:

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

Leave the outer `if (!isNaN(ph) && ...)` and the outer `else { kwasCalcEl.textContent = '— kg'; }` branches untouched — their contract is identical to before.

- [ ] **Step 4: Verify the change**

Run: `grep -nE "_bagFractionRange|modelFmt|rangeStr|overFmt" mbr/templates/laborant/_correction_panel.html`

Expected: ≥ 6 matches — the declarations from Task 1 AND the 5 new usages in `recomputeStandV2` (`_bagFractionRange(kwas)`, `modelFmt`, `rangeStr`, `overFmt`, and the two uses of `range.*`).

Also run: `grep -n "kFmt + ' kg'" mbr/templates/laborant/_correction_panel.html`

Expected: **no matches**. The old format is fully replaced.

- [ ] **Step 5: Full-suite sanity (Python tests only — there are no JS tests, but Python imports the template via Flask rendering in some paths)**

Run: `python -m pytest --tb=short -q 2>&1 | tail -5`
Expected: all tests pass, same count as baseline (896 passed, 19 skipped).

- [ ] **Step 6: Commit**

```bash
git add mbr/templates/laborant/_correction_panel.html
git commit -m "feat(laborant): acid suggestion shows bag-fraction range

Display format changes from '87,5 kg' to '87 (81,25–87,5) kg' — the raw
model output plus the nearest achievable doses at 6.25 kg granularity
(25 kg bags ÷ 4 quarters). Manual input auto-fills with the upper bound
so operators see a realistically-dispensable dose by default.

Constants (BAG_KG=25, BAG_DIVISIONS=4) are hardcoded in JS; scope is
citric acid only. Water and other additives keep the old single-number
display.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Deploy + smoke test

**Files:** No code changes — verification only.

- [ ] **Step 1: Push main**

```bash
git push origin main
```

Expected: push succeeds, no conflicts.

- [ ] **Step 2: Trigger auto-deploy on prod**

```bash
expect -c '
set timeout 60
log_user 1
spawn ssh -o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no -o NumberOfPasswordPrompts=1 tbk@192.168.1.240 "echo z.S17DcxSy33 | sudo -S systemctl start auto-deploy.service 2>&1; sleep 10; echo ===HEAD===; cd /opt/lims && git log --oneline -1; echo ===LIMS===; systemctl is-active lims"
expect {
  -re "password:" { send "z.S17DcxSy33\r"; exp_continue }
  eof
}
' 2>&1 | tail -10
```

Expected:
- HEAD matches the commit from Task 2.
- `lims` is `active`.

If SSH is unreachable (network blip from Task 10 of previous feature is fresh in memory): the systemd auto-deploy.timer on prod fires every 5 min on its own, so the change lands within 5 minutes regardless.

- [ ] **Step 3: Operator smoke test**

Tell the user:

- Open a K7 batch in standaryzacja → trigger the correction panel (via gate failure: pH fail during pass).
- Expected display in `corr-kwas-calc-*`: `N (X,XX–Y,YY) kg` (or `N (Y,YY) kg` if `kwas` is exactly on a quarter boundary).
- Example concrete expectation: if model returns `~87 kg`, display shows `87 (81,25–87,5) kg`. Manual input box `corr-manual-kwas-*` auto-fills with `87,5`.
- Confirm: typing a different value in the manual input overrides the auto-fill, and saving the correction persists the override (existing behavior, unchanged).

- [ ] **Step 4: If operator confirms — done**

No further commit. The feature is live.

---

## Spec coverage audit

| Spec requirement                                                        | Covered by |
|-------------------------------------------------------------------------|-----------:|
| Display format `87 (81,25–87,5) kg`                                     | Task 2     |
| `under` = floor(kwas / 6.25) × 6.25                                     | Task 1 (`_bagFractionRange`) |
| `over` = ceil(kwas / 6.25) × 6.25                                       | Task 1 |
| Model value rounded to integer for middle slot                          | Task 2 (`Math.round(range.model)`) |
| Manual input auto-fill uses `over`                                      | Task 2 |
| `dataset.suggested` stored at `.toFixed(2)` precision                   | Task 2 |
| Edge case: exactly divisible → single value in parens                   | Task 2 (`range.under === range.over` branch) |
| Error handling: model null → `— kg`                                     | Task 2 (`else` preserved) |
| No admin UI, constants hardcoded                                        | Task 1 |
| Scope: citric acid only                                                 | Task 2 (only `corr-kwas-calc-*` touched; `corr-woda-calc-*` untouched) |
| En-dash (U+2013) between range values                                   | Task 2 (`'–'`) |
