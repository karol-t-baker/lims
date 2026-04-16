# K7 Batch Card Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 bugs in the K7 extended batch card: sulfite name error breaking correction saves, woda łącznie not editable/persisted, and standaryzacja showing correction panel when all params are in-spec.

**Architecture:** All fixes are in the frontend templates (`_fast_entry_content.html`, `_correction_panel.html`) and one setup script. No backend route changes needed. Fix 4 requires a DB migration (gate warunek operator change from `between` to `w_limicie` for standaryzacja).

**Tech Stack:** Jinja/HTML templates with inline JS, SQLite, Python (setup script)

---

### Task 1: Fix sulfite substance name (blocks nothing, standalone)

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html:2737,2739,2990`
- Modify: `docs/context/chegina-k7-pipeline.md:30`

The JS sends `substancja: 'Siarczynian sodu'` but `etap_korekty_katalog` stores `Na2SO3`. The API lookup `WHERE substancja=?` fails silently → correction never saved. Also the UI text says "siarczynianu" (sulfinate) instead of "siarczynu sodu" (sulfite).

- [ ] **Step 1: Fix UI text — "siarczynianu" → "siarczynu sodu"**

In `mbr/templates/laborant/_fast_entry_content.html`, change three lines:

Line 2737 — change:
```js
'<div class="gate-desc">Stężenie siarczynów poniżej wymaganego minimum. Wymagany dodatek siarczynianu i powtórzenie analizy.</div>' +
```
to:
```js
'<div class="gate-desc">Stężenie siarczynów poniżej wymaganego minimum. Wymagany dodatek siarczynu sodu i powtórzenie analizy.</div>' +
```

Line 2739 — change:
```js
'<label>Dodatek siarczynianu:</label>' +
```
to:
```js
'<label>Dodatek siarczynu sodu [kg]:</label>' +
```

Line 2990 — change:
```js
substancja: 'Siarczynian sodu',
```
to:
```js
substancja: 'Na2SO3',
```

- [ ] **Step 2: Fix docs reference**

In `docs/context/chegina-k7-pipeline.md` line 30, change `Siarczynian sodu` to `Na2SO3 (siarczyn sodu)`.

- [ ] **Step 3: Add error handling for sulfite correction save**

In `mbr/templates/laborant/_fast_entry_content.html`, in the `startNewPipelineRound` function (line ~2984), the fetch for sulfite correction silently ignores failures. Wrap it with error handling:

Change lines 2984-2993 from:
```js
        await fetch('/api/pipeline/lab/ebr/' + ebrId + '/korekta', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                sesja_id: gate.sesja_id,
                etap_id: gate.etap_id,
                substancja: 'Siarczynian sodu',
                ilosc: kg
            })
        });
```
to:
```js
        var resp = await fetch('/api/pipeline/lab/ebr/' + ebrId + '/korekta', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                sesja_id: gate.sesja_id,
                etap_id: gate.etap_id,
                substancja: 'Na2SO3',
                ilosc: kg
            })
        });
        if (!resp.ok) {
            alert('Błąd zapisu korekty siarczynu. Sprawdź i spróbuj ponownie.');
            return;
        }
```

- [ ] **Step 4: Verify fix manually**

1. Run `python -m mbr.app`
2. Open a K7 batch, go to sulfonowanie stage
3. Enter SO3 values below threshold → should show "Stężenie siarczynów poniżej wymaganego minimum. Wymagany dodatek siarczynu sodu..."
4. Enter kg value → click "Nowa runda" → correction should save (no alert)
5. Check dziennik zdarzeń — should show the sulfite correction attached to R1

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html docs/context/chegina-k7-pipeline.md
git commit -m "fix: sulfite name Na2SO3 — correction was never saved due to substancja mismatch"
```

---

### Task 2: Make "woda łącznie" editable and save to DB (depends on Task 1)

**Files:**
- Modify: `mbr/templates/laborant/_correction_panel.html:184-187,261-272,287-331,333-391`

Currently "WODA ŁĄCZNIE [KG]" is a read-only div showing `woda + kwas`. The operator needs to edit this value (laboranci often reduce water). The edited value should be saved to `ebr_korekta_v2` as a separate "Woda łącznie" correction entry, alongside the individual Woda and Kwas corrections.

**Approach:** Replace the read-only div with an editable input. Auto-populate from `woda + kwas` but allow manual edit. Save the final "woda łącznie" value as the `ilosc` of the Woda correction (replacing the individual woda field value), since this is what production actually adds. The individual Woda field becomes the "calculated water only" reference, and "Woda łącznie" becomes the actual dispatched amount.

- [ ] **Step 1: Replace read-only div with editable input**

In `mbr/templates/laborant/_correction_panel.html`, change lines 184-187 from:
```js
                '<div>' +
                    '<span class="corr-field-label">WODA ŁĄCZNIE [KG]</span>' +
                    '<div id="corr-total-woda-' + sekcja + '" style="padding:6px 10px;border:1.5px solid var(--teal);border-radius:6px;font-size:14px;font-family:var(--mono);text-align:center;background:var(--teal-bg);color:var(--teal);font-weight:700;">&mdash;</div>' +
                '</div>' +
```
to:
```js
                '<div>' +
                    '<span class="corr-field-label">WODA ŁĄCZNIE [KG]</span>' +
                    '<input id="corr-total-woda-' + sekcja + '" class="corr-field-input" type="text" inputmode="decimal"' +
                        ' style="font-weight:700;font-size:14px;border-color:var(--teal);background:var(--teal-bg);color:var(--teal);text-align:center;"' +
                        ' oninput="document.getElementById(\'corr-total-woda-' + sekcja + '\')._userEdited=true;">' +
                '</div>' +
```

- [ ] **Step 2: Update recomputeStandTotal to respect user edits**

In `mbr/templates/laborant/_correction_panel.html`, change the `recomputeStandTotal` function (lines 261-272) from:
```js
function recomputeStandTotal(sekcja) {
    var wodaEl = document.getElementById('corr-manual-woda-' + sekcja);
    var kwasEl = document.getElementById('corr-manual-kwas-' + sekcja);
    var totalEl = document.getElementById('corr-total-woda-' + sekcja);
    if (!totalEl) return;
    var woda = wodaEl ? _parsePl(wodaEl.value) : NaN;
    var kwas = kwasEl ? _parsePl(kwasEl.value) : NaN;
    if (isNaN(woda)) woda = 0;
    if (isNaN(kwas)) kwas = 0;
    var total = woda + kwas;
    totalEl.textContent = total > 0 ? total.toFixed(1).replace('.', ',') : '\u2014';
}
```
to:
```js
function recomputeStandTotal(sekcja) {
    var wodaEl = document.getElementById('corr-manual-woda-' + sekcja);
    var kwasEl = document.getElementById('corr-manual-kwas-' + sekcja);
    var totalEl = document.getElementById('corr-total-woda-' + sekcja);
    if (!totalEl) return;
    if (totalEl._userEdited) return;  // user has manually edited — don't overwrite
    var woda = wodaEl ? _parsePl(wodaEl.value) : NaN;
    var kwas = kwasEl ? _parsePl(kwasEl.value) : NaN;
    if (isNaN(woda)) woda = 0;
    if (isNaN(kwas)) kwas = 0;
    var total = woda + kwas;
    totalEl.value = total > 0 ? total.toFixed(1).replace('.', ',') : '';
}
```

- [ ] **Step 3: Update advanceStandNewRound to save woda łącznie instead of individual woda**

In `mbr/templates/laborant/_correction_panel.html`, in `advanceStandNewRound` (lines 287-331), replace the Woda correction save block. Change lines 293-303 from:
```js
    var wodaEl = document.getElementById('corr-manual-woda-' + sekcja);
    if (wodaEl && wodaEl.value) {
        var wKg = parseFloat(wodaEl.value.replace(',', '.'));
        if (!isNaN(wKg) && wKg > 0) {
            var rw = await fetch('/api/pipeline/lab/ebr/' + ebrId + '/korekta', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ sesja_id: gate.sesja_id, etap_id: gate.etap_id, substancja: 'Woda', ilosc: wKg })
            });
            if (!rw.ok) corrErrors.push('Woda');
        }
    }
```
to:
```js
    var totalWodaEl = document.getElementById('corr-total-woda-' + sekcja);
    if (totalWodaEl && totalWodaEl.value) {
        var wKg = parseFloat(totalWodaEl.value.replace(',', '.'));
        if (!isNaN(wKg) && wKg > 0) {
            var rw = await fetch('/api/pipeline/lab/ebr/' + ebrId + '/korekta', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ sesja_id: gate.sesja_id, etap_id: gate.etap_id, substancja: 'Woda', ilosc: wKg })
            });
            if (!rw.ok) corrErrors.push('Woda');
        }
    }
```

- [ ] **Step 4: Update advanceWithStandV2 the same way**

In `mbr/templates/laborant/_correction_panel.html`, in `advanceWithStandV2` (lines 333-391), apply the same change. Replace lines 339-349 from:
```js
    var wodaEl = document.getElementById('corr-manual-woda-' + sekcja);
    if (wodaEl && wodaEl.value) {
        var wKg = parseFloat(wodaEl.value.replace(',', '.'));
        if (!isNaN(wKg) && wKg > 0 && gate.sesja_id) {
            var rw = await fetch('/api/pipeline/lab/ebr/' + ebrId + '/korekta', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ sesja_id: gate.sesja_id, etap_id: gate.etap_id, substancja: 'Woda', ilosc: wKg })
            });
            if (!rw.ok) corrErrors.push('Woda');
        }
    }
```
to:
```js
    var totalWodaEl = document.getElementById('corr-total-woda-' + sekcja);
    if (totalWodaEl && totalWodaEl.value) {
        var wKg = parseFloat(totalWodaEl.value.replace(',', '.'));
        if (!isNaN(wKg) && wKg > 0 && gate.sesja_id) {
            var rw = await fetch('/api/pipeline/lab/ebr/' + ebrId + '/korekta', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ sesja_id: gate.sesja_id, etap_id: gate.etap_id, substancja: 'Woda', ilosc: wKg })
            });
            if (!rw.ok) corrErrors.push('Woda');
        }
    }
```

- [ ] **Step 5: Update advancePerhydrolWithStand the same way**

In `mbr/templates/laborant/_correction_panel.html`, in `advancePerhydrolWithStand` (around line 620), apply the same change:

Change lines 620-629 from:
```js
    var wodaEl = document.getElementById('corr-manual-woda-' + sekcja);
    if (wodaEl && wodaEl.value) {
        var wKg = parseFloat(wodaEl.value.replace(',', '.'));
        if (!isNaN(wKg) && wKg > 0) {
            var rw = await fetch('/api/pipeline/lab/ebr/' + ebrId + '/korekta', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ sesja_id: gate.sesja_id, etap_id: gate.etap_id, substancja: 'Woda', ilosc: wKg })
            });
            if (!rw.ok) corrErrors.push('Woda');
```
to:
```js
    var totalWodaEl = document.getElementById('corr-total-woda-' + sekcja);
    if (totalWodaEl && totalWodaEl.value) {
        var wKg = parseFloat(totalWodaEl.value.replace(',', '.'));
        if (!isNaN(wKg) && wKg > 0) {
            var rw = await fetch('/api/pipeline/lab/ebr/' + ebrId + '/korekta', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ sesja_id: gate.sesja_id, etap_id: gate.etap_id, substancja: 'Woda', ilosc: wKg })
            });
            if (!rw.ok) corrErrors.push('Woda');
```

- [ ] **Step 6: Verify manually**

1. Open K7 batch → standaryzacja stage → enter values with nD20 out of range
2. Correction panel shows: Woda suggested, Kwas suggested, Woda łącznie = sum
3. Edit "Woda łącznie" manually (reduce it) → value persists, doesn't revert
4. Click "Zaleć korektę + nowa runda" → check DB: `ebr_korekta_v2` has `substancja='Woda'` with the łącznie value
5. Open dziennik zdarzeń → correction row shows the edited łącznie value

- [ ] **Step 7: Commit**

```bash
git add mbr/templates/laborant/_correction_panel.html
git commit -m "fix: woda łącznie editable — operator can adjust total water, value saved to DB"
```

---

### Task 3: Standaryzacja — hide correction panel when all params in-spec

**Files:**
- Modify: `mbr/templates/laborant/_correction_panel.html:102-195,788-801`
- Modify: `scripts/setup_standaryzacja.py:117-125` (gate operator fix)
- Create: `scripts/migrate_standaryzacja_gate.py` (one-off migration)

**Root cause:** Standaryzacja gate conditions use `operator="between", wartosc=0, wartosc_max=9999` — this always passes regardless of product-specific limits. The gate should use `"w_limicie"` operator which checks the `w_limicie` flag computed during `save_pomiar` against the actual product-specific `produkt_etap_limity`.

**Result:** Gate will now FAIL when pH or nD20 is out of product limits → correction panel shown. Gate PASS means all OK → no correction panel, just "Przepompuj".

- [ ] **Step 1: Create migration script to update gate operator**

Create `scripts/migrate_standaryzacja_gate.py`:

```python
"""
Migrate standaryzacja gate conditions from 'between 0..9999' to 'w_limicie'.

The 'between' operator checked against hardcoded 0..9999 (always passes).
The 'w_limicie' operator checks the w_limicie flag set by save_pomiar
against product-specific limits in produkt_etap_limity.

Run: python -m scripts.migrate_standaryzacja_gate
"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mbr.db import get_db


def migrate(db: sqlite3.Connection) -> int:
    stand = db.execute(
        "SELECT id FROM etapy_analityczne WHERE kod = 'standaryzacja'"
    ).fetchone()
    if not stand:
        print("Standaryzacja etap not found — skipping.")
        return 0

    etap_id = stand[0]
    rows = db.execute(
        "SELECT id, parametr_id, operator, wartosc, wartosc_max FROM etap_warunki WHERE etap_id = ?",
        (etap_id,),
    ).fetchall()

    updated = 0
    for r in rows:
        if r["operator"] == "between" and r["wartosc"] == 0 and r["wartosc_max"] == 9999:
            db.execute(
                "UPDATE etap_warunki SET operator = 'w_limicie', wartosc = NULL, wartosc_max = NULL WHERE id = ?",
                (r["id"],),
            )
            updated += 1
            print(f"  Updated warunek id={r['id']} parametr_id={r['parametr_id']}: between 0..9999 → w_limicie")

    db.commit()
    print(f"Migrated {updated} standaryzacja gate conditions.")
    return updated


if __name__ == "__main__":
    db = get_db()
    try:
        migrate(db)
    finally:
        db.close()
```

- [ ] **Step 2: Update setup script to use w_limicie for new installs**

In `scripts/setup_standaryzacja.py`, change lines 121-124 from:
```python
        add_etap_warunek(
            db, etap_id, pid, "between", 0, wartosc_max=9999,
            opis_warunku=f"{kod} w zakresie limitów produktu",
        )
```
to:
```python
        add_etap_warunek(
            db, etap_id, pid, "w_limicie", None,
            opis_warunku=f"{kod} w zakresie limitów produktu",
        )
```

- [ ] **Step 3: Run migration**

```bash
python -m scripts.migrate_standaryzacja_gate
```

Expected output: `Migrated N standaryzacja gate conditions.` (N = number of params, likely 4: ph, nd20, nacl, sa)

- [ ] **Step 4: Update standaryzacja PASS rendering — skip correction panel when all OK**

In `mbr/templates/laborant/_correction_panel.html`, change `tryRenderCorrectionAfterGate` for the standaryzacja branch (lines 788-801).

Change from:
```js
    } else if (ctx.etapKod === 'standaryzacja') {
        var standEtap = etapy.find(function(e) { return e.kod === 'standaryzacja'; });
        var standEtapId = standEtap ? standEtap.pipeline_etap_id : 0;

        // Standaryzacja PASS or FAIL → show standaryzacja V2 panel
        // (action button adapts via _gatePassAction: 'new_round_stand' / 'pompuj')
        renderCorrectionPanel('standaryzacja_v2', sekcja, {
            wynik_nd20:  ctx.getWynik('nd20'),
            wynik_ph:    ctx.getWynik('ph_10proc'),
            masa_szarzy: ctx.masa,
            etap_id:     standEtapId,
            produkt:     produkt,
        });
    }
```
to:
```js
    } else if (ctx.etapKod === 'standaryzacja') {
        var standEtap = etapy.find(function(e) { return e.kod === 'standaryzacja'; });
        var standEtapId = standEtap ? standEtap.pipeline_etap_id : 0;

        if (window._gatePassAction === 'pompuj') {
            // All params in-spec → no correction panel, just Przepompuj button
            var container = document.getElementById('correction-panel-' + sekcja);
            if (container) {
                container.innerHTML =
                    '<div class="gate-section gate-h2o2" style="margin-top:8px;">' +
                        '<div class="gate-head">' +
                            '<div class="gate-icon gate-icon-blue" style="font-size:10px;">\u2714</div>' +
                            '<span class="gate-title">Wszystkie parametry w celu</span>' +
                            '<span class="gate-badge gate-badge-ok">PASS</span>' +
                        '</div>' +
                        '<div class="gate-actions">' +
                            '<button class="gate-btn gate-btn-ok" onclick="completePompuj()">Przepompuj na zbiornik</button>' +
                        '</div>' +
                    '</div>';
            }
        } else {
            // FAIL (pH/nD20 out of range) → show correction panel
            renderCorrectionPanel('standaryzacja_v2', sekcja, {
                wynik_nd20:  ctx.getWynik('nd20'),
                wynik_ph:    ctx.getWynik('ph_10proc'),
                masa_szarzy: ctx.masa,
                etap_id:     standEtapId,
                produkt:     produkt,
            });
        }
    }
```

- [ ] **Step 5: Verify manually**

1. Open K7 batch → standaryzacja
2. Enter values ALL within product limits → gate PASS → should show "Wszystkie parametry w celu" + "Przepompuj na zbiornik", NO correction fields
3. Enter values with nD20 out of range → gate FAIL → should show correction panel with woda/kwas fields + "Zaleć korektę + nowa runda"
4. Enter values with pH out of range → same FAIL behavior
5. Test: small correction scenario — FAIL → small woda value → can still "Przepompuj" and note in uwagi

- [ ] **Step 6: Commit**

```bash
git add mbr/templates/laborant/_correction_panel.html scripts/setup_standaryzacja.py scripts/migrate_standaryzacja_gate.py
git commit -m "fix: standaryzacja gate uses w_limicie — correction panel only when params out of spec"
```

---

### Task 4: Standaryzacja FAIL — allow approve with uwagi for small corrections

**Files:**
- Modify: `mbr/templates/laborant/_correction_panel.html` (in `_renderStandaryzacjaV2Panel`)

When standaryzacja FAIL shows the correction panel, if the correction is small, the operator should be able to approve the batch and note the small addition in uwagi instead of running another round.

- [ ] **Step 1: Add "Zatwierdź z uwagami" button to FAIL correction panel**

In `mbr/templates/laborant/_correction_panel.html`, in `_renderStandaryzacjaV2Panel` (line 126-141), modify the `isNewRoundStand` action button block. Change from:
```js
    } else if (isNewRoundStand) {
        actionBtn =
            '<button class="gate-btn gate-btn-warn" onclick="advanceStandNewRound(\'' + sekcja + '\')">Zale\u0107 korekt\u0119 + nowa runda \u2192</button>';
```
to:
```js
    } else if (isNewRoundStand) {
        actionBtn =
            '<button class="gate-btn gate-btn-warn" onclick="advanceStandNewRound(\'' + sekcja + '\')">Zale\u0107 korekt\u0119 + nowa runda \u2192</button>' +
            '<button class="gate-btn gate-btn-sec" style="margin-left:8px;" onclick="approveStandWithUwagi(\'' + sekcja + '\')">Zatwierd\u017A z uwagami</button>';
```

- [ ] **Step 2: Implement approveStandWithUwagi function**

Add this function after `advanceStandNewRound` (after line 331):

```js
async function approveStandWithUwagi(sekcja) {
    var gate = window._lastGate;
    if (!gate || !gate.etap_id || !gate.sesja_id) return;

    var uwagi = prompt('Wpisz uwagę dotyczącą małej korekty (np. "mały dodatek wody 5kg, pominięto powtórną analizę"):');
    if (uwagi === null) return;  // cancelled
    if (!uwagi.trim()) { alert('Uwaga nie może być pusta.'); return; }

    // Save corrections if any entered
    var corrErrors = [];
    var totalWodaEl = document.getElementById('corr-total-woda-' + sekcja);
    if (totalWodaEl && totalWodaEl.value) {
        var wKg = parseFloat(totalWodaEl.value.replace(',', '.'));
        if (!isNaN(wKg) && wKg > 0) {
            var rw = await fetch('/api/pipeline/lab/ebr/' + ebrId + '/korekta', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ sesja_id: gate.sesja_id, etap_id: gate.etap_id, substancja: 'Woda', ilosc: wKg })
            });
            if (!rw.ok) corrErrors.push('Woda');
        }
    }
    var kwasEl = document.getElementById('corr-manual-kwas-' + sekcja);
    if (kwasEl && kwasEl.value) {
        var kKg = parseFloat(kwasEl.value.replace(',', '.'));
        if (!isNaN(kKg) && kKg > 0) {
            var rk = await fetch('/api/pipeline/lab/ebr/' + ebrId + '/korekta', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ sesja_id: gate.sesja_id, etap_id: gate.etap_id, substancja: 'Kwas cytrynowy', ilosc: kKg })
            });
            if (!rk.ok) corrErrors.push('Kwas cytrynowy');
        }
    }
    if (corrErrors.length > 0) {
        alert('Błąd zapisu korekt: ' + corrErrors.join(', '));
        return;
    }

    // Close stage with pass (override gate) + save uwagi
    await fetch('/api/pipeline/lab/ebr/' + ebrId + '/etap/' + gate.etap_id + '/close', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ sesja_id: gate.sesja_id, decyzja: 'przejscie', komentarz: uwagi })
    });

    // Save uwagi_koncowe
    await fetch('/api/ebr/' + ebrId + '/uwagi', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ tekst: uwagi })
    });

    completePompuj();
}
```

- [ ] **Step 3: Verify manually**

1. Open K7 batch → standaryzacja → enter values with nD20 slightly out of range
2. Correction panel shows with two buttons: "Zaleć korektę + nowa runda" and "Zatwierdź z uwagami"
3. Click "Zatwierdź z uwagami" → prompt appears → enter text → OK
4. Batch proceeds to pump modal
5. Check: uwagi_koncowe saved, corrections saved, session closed

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/_correction_panel.html
git commit -m "feat: standaryzacja — approve with uwagi for small corrections"
```
