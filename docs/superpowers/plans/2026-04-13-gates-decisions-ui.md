# Gates & Decisions UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show gate pass/fail after auto-save, display decision buttons and correction panel, enable new round with OK value copying — all within the existing fast_entry view.

**Architecture:** Extend `pipeline_dual_write` to return `sesja_id`/`etap_id` alongside gate. In JS, after `doSaveField` response, check for `gate` and render banner/decisions/corrections inline. Pipeline API endpoints for close/start/korekta already exist — wire them into new JS functions.

**Tech Stack:** Vanilla JS in existing templates, existing pipeline REST API, existing CSS patterns.

---

## File Structure

### Files to modify:
```
mbr/pipeline/adapter.py                              — extend dual_write return value
mbr/laborant/routes.py                                — pass extended gate info to response
mbr/templates/laborant/_fast_entry_content.html        — gate banner, decisions, corrections, new round
```

### Tests to modify:
```
tests/test_pipeline_adapter.py                         — update dual_write test expectations
```

---

## Task 1: Extend dual-write response with sesja_id and etap_id

**Files:**
- Modify: `mbr/pipeline/adapter.py` (function `pipeline_dual_write`, line ~365)
- Modify: `mbr/laborant/routes.py` (function `save_entry`, line ~297)
- Modify: `tests/test_pipeline_adapter.py`

- [ ] **Step 1: Update pipeline_dual_write return**

In `mbr/pipeline/adapter.py`, change the last line of `pipeline_dual_write` (line 365):

```python
# BEFORE:
    return evaluate_gate(db, etap_id, sesja["id"])

# AFTER:
    gate = evaluate_gate(db, etap_id, sesja["id"])
    gate["sesja_id"] = sesja["id"]
    gate["etap_id"] = etap_id
    return gate
```

- [ ] **Step 2: Update test expectation**

In `tests/test_pipeline_adapter.py`, in `test_dual_write_saves_to_ebr_pomiar`, add:

```python
    assert "sesja_id" in gate
    assert "etap_id" in gate
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_pipeline_adapter.py -v
```

- [ ] **Step 4: Commit**

```bash
git add mbr/pipeline/adapter.py tests/test_pipeline_adapter.py
git commit -m "feat: dual-write returns sesja_id and etap_id with gate result"
```

---

## Task 2: Gate banner after auto-save

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Add gate banner container**

In `renderOneSection` (line ~2332), after the section fields HTML but before the section is appended to container, add a gate banner placeholder. Find the line where section is appended (after all field HTML is built). Add after the fields `</div>` closing tag but inside the section div:

Find this pattern near the end of `renderOneSection` (after the fields grid and save button):

```javascript
    section.innerHTML = headHtml + fieldsHtml;
```

After that line, add:

```javascript
    // Gate banner placeholder for pipeline stages
    section.innerHTML += '<div class="gate-banner" id="gate-' + sekcja + '"></div>';
```

- [ ] **Step 2: Modify doSaveField to handle gate response**

In `doSaveField` (line 2521), in the `.then(async function(resp)` handler, after the `resp.ok` block (line 2549-2568), after updating `wyniki[sekcja][kod]`, add gate handling:

Find this section (around line 2562-2568):
```javascript
            wyniki[sekcja][kod] = {
                wartosc: isNaN(numVal) ? null : numVal,
                wartosc_text: values[kod].wartosc,
                komentarz: values[kod].komentarz || '',
                w_limicie: inLimit,
                tag: kod
            };
```

After the closing `};` of that assignment, add:

```javascript
            // Pipeline gate banner
            var data = await resp.clone().json().catch(function(){return {};});
            if (data.gate) {
                renderGateBanner(sekcja, data.gate);
            }
```

Note: `resp` has already been consumed by `resp.ok` check, so we need `.clone()`. But actually `resp.ok` doesn't consume the body. The issue is we haven't parsed JSON yet. Let me restructure — parse JSON once at the top of the ok block:

Actually, looking more carefully at the code: `resp.ok` is a property check (doesn't consume body). We can parse JSON after. Change the approach — parse response JSON and use it:

Replace the entire success block inside `.then(async function(resp) {`:

```javascript
    }).then(async function(resp) {
        if (await _handleShiftRequired(resp)) return;
        if (resp.ok) {
            var data = {};
            try { data = await resp.json(); } catch(e) {}

            input.style.outline = '2px solid var(--green, #16a34a)';
            setTimeout(function() { input.style.outline = ''; }, 800);
            // Update local wyniki so repeatAnaliza sees current values
            if (!wyniki[sekcja]) wyniki[sekcja] = {};
            var numVal = parseFloat(values[kod].wartosc);
            var minVal = parseFloat(input.dataset.min);
            var maxVal = parseFloat(input.dataset.max);
            var inLimit = 1;
            if (!isNaN(numVal)) {
                if (!isNaN(minVal) && numVal < minVal) inLimit = 0;
                if (!isNaN(maxVal) && numVal > maxVal) inLimit = 0;
            }
            wyniki[sekcja][kod] = {
                wartosc: isNaN(numVal) ? null : numVal,
                wartosc_text: values[kod].wartosc,
                komentarz: values[kod].komentarz || '',
                w_limicie: inLimit,
                tag: kod
            };

            // Pipeline gate evaluation
            if (data.gate) {
                renderGateBanner(sekcja, data.gate);
            }
        } else {
            input.style.outline = '2px solid var(--red, #dc2626)';
            setTimeout(function() { input.style.outline = ''; }, 2000);
        }
    }).catch(function() {
```

- [ ] **Step 3: Add renderGateBanner function**

Add before `doSaveField` (around line 2520):

```javascript
function renderGateBanner(sekcja, gate) {
    // Find the gate banner container in current section
    var banner = document.getElementById('gate-' + sekcja);
    if (!banner) {
        // Try base sekcja (analiza__1 → analiza)
        var baseSekcja = sekcja.split('__')[0];
        banner = document.getElementById('gate-' + baseSekcja);
    }
    if (!banner) return;

    // Store gate data for decision handlers
    window._lastGate = gate;

    if (gate.passed) {
        var activeEtap = etapy.find(function(e) { return e.sekcja_lab === (sekcja.split('__')[0]); });
        var isCyclic = activeEtap && activeEtap.typ_cyklu === 'cykliczny';
        var isMainCyclic = isCyclic && (activeEtap.sekcja_lab === 'analiza');

        var buttonsHtml = '';
        if (isMainCyclic) {
            buttonsHtml =
                '<button class="btn-success" onclick="completePompuj()">Przepompuj na zbiornik</button>' +
                '<button class="btn-secondary" onclick="openSmallCorrectionDialog()">Mała korekta + przepompuj</button>';
        } else {
            buttonsHtml =
                '<button class="btn-success" onclick="closePipelineStage(\'' + sekcja + '\')">Zatwierdź etap &rarr;</button>';
        }

        banner.innerHTML =
            '<div class="decision-bar" style="background:var(--green-bg);border:1px solid var(--green);border-radius:8px;padding:12px 16px;margin-top:12px;">' +
                '<span style="color:var(--green);font-weight:600;font-size:13px;">&#10003; Warunek spełniony</span>' +
                '<div style="margin-top:8px;display:flex;gap:8px;">' + buttonsHtml + '</div>' +
            '</div>';
    } else {
        var failList = (gate.failures || []).map(function(f) {
            return f.kod || f.reason || 'nieznany';
        }).join(', ');

        banner.innerHTML =
            '<div class="decision-bar" style="background:var(--red-bg, #fef2f2);border:1px solid var(--red);border-radius:8px;padding:12px 16px;margin-top:12px;">' +
                '<span style="color:var(--red);font-weight:600;font-size:13px;">&#9888; Warunek niespełniony: ' + failList + '</span>' +
                '<div id="correction-panel-' + sekcja + '" style="margin-top:10px;">' +
                    '<div style="color:var(--text-dim);font-size:11px;">Ładowanie korekt...</div>' +
                '</div>' +
            '</div>';

        // Fetch correction catalog
        if (gate.etap_id) {
            loadCorrectionPanel(sekcja, gate);
        }
    }
}
```

- [ ] **Step 4: Run tests**

```bash
pytest --tb=short -q
```

- [ ] **Step 5: Test manually**

Open K7 batch, enter SO3 value in utlenienie. After blur+save, check if gate banner appears.

- [ ] **Step 6: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: gate banner (pass/fail) after auto-save in pipeline stages"
```

---

## Task 3: Correction panel + close/start pipeline actions

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Add loadCorrectionPanel function**

Add after `renderGateBanner`:

```javascript
async function loadCorrectionPanel(sekcja, gate) {
    var panel = document.getElementById('correction-panel-' + sekcja);
    if (!panel) return;

    try {
        var resp = await fetch('/api/pipeline/lab/ebr/' + ebrId + '/etap/' + gate.etap_id);
        if (!resp.ok) { panel.innerHTML = '<div style="color:var(--red);">Błąd ładowania korekt</div>'; return; }
        var data = await resp.json();
        var korekty = data.korekty_katalog || [];

        if (korekty.length === 0) {
            panel.innerHTML = '<div style="font-size:11px;color:var(--text-dim);">Brak zdefiniowanych korekt dla tego etapu.</div>';
            return;
        }

        var html = '<div style="font-size:11px;font-weight:600;margin-bottom:6px;">Zalecenie korekty:</div>';
        korekty.forEach(function(k) {
            html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;font-size:12px;">' +
                '<span style="min-width:120px;font-weight:500;">' + (k.substancja || '') + '</span>' +
                '<span style="color:var(--text-dim);font-size:10px;">[' + (k.jednostka || 'kg') + ']</span>' +
                '<span class="pa-badge" style="font-size:8px;">' + (k.wykonawca || '') + '</span>' +
                '<input type="number" step="any" class="pa-input" data-korekta-id="' + k.id + '" placeholder="Ilość" style="width:80px;font-size:11px;text-align:center;">' +
            '</div>';
        });
        html += '<div style="display:flex;gap:8px;margin-top:10px;">' +
            '<button class="btn-warn" onclick="submitCorrections(\'' + sekcja + '\')" id="btn-submit-corr-' + sekcja + '">Zaleć korektę</button>' +
            '<button class="btn-secondary" onclick="startNewPipelineRound(\'' + sekcja + '\')" id="btn-new-round-' + sekcja + '" style="display:none;">Nowa runda</button>' +
        '</div>';
        panel.innerHTML = html;
    } catch(e) {
        panel.innerHTML = '<div style="color:var(--red);">Błąd: ' + e.message + '</div>';
    }
}
```

- [ ] **Step 2: Add submitCorrections function**

```javascript
async function submitCorrections(sekcja) {
    var gate = window._lastGate;
    if (!gate || !gate.sesja_id) return;

    var panel = document.getElementById('correction-panel-' + sekcja);
    if (!panel) return;

    var inputs = panel.querySelectorAll('input[data-korekta-id]');
    var anySet = false;

    // Submit each correction with non-empty amount
    for (var i = 0; i < inputs.length; i++) {
        var inp = inputs[i];
        if (inp.value && parseFloat(inp.value) > 0) {
            anySet = true;
            await fetch('/api/pipeline/lab/ebr/' + ebrId + '/korekta', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    sesja_id: gate.sesja_id,
                    korekta_typ_id: parseInt(inp.dataset.korektaId),
                    ilosc: parseFloat(inp.value)
                })
            });
        }
    }

    if (!anySet) { alert('Wpisz ilość dla przynajmniej jednej korekty.'); return; }

    // Close session with korekta decision
    await fetch('/api/pipeline/lab/ebr/' + ebrId + '/etap/' + gate.etap_id + '/close', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sesja_id: gate.sesja_id, decyzja: 'korekta'})
    });

    // Disable inputs, hide submit, show new round button
    inputs.forEach(function(inp) { inp.disabled = true; });
    var submitBtn = document.getElementById('btn-submit-corr-' + sekcja);
    var roundBtn = document.getElementById('btn-new-round-' + sekcja);
    if (submitBtn) submitBtn.style.display = 'none';
    if (roundBtn) roundBtn.style.display = '';
}
```

- [ ] **Step 3: Add startNewPipelineRound function**

```javascript
async function startNewPipelineRound(sekcja) {
    var gate = window._lastGate;
    if (!gate || !gate.etap_id) return;

    // Start new session
    var resp = await fetch('/api/pipeline/lab/ebr/' + ebrId + '/etap/' + gate.etap_id + '/start', {
        method: 'POST'
    });
    if (!resp.ok) { alert('Błąd rozpoczęcia nowej rundy'); return; }

    // Copy OK values from last analiza round (reuse existing logic)
    var baseSekcja = sekcja.split('__')[0];
    if (baseSekcja === 'analiza' || baseSekcja === sekcja) {
        repeatAnalizaCyclic();
    } else {
        // Reload for non-cyclic
        if (typeof loadBatch === 'function') loadBatch(ebrId);
        else location.reload();
    }
}
```

- [ ] **Step 4: Add closePipelineStage function (for jednorazowy stages)**

```javascript
async function closePipelineStage(sekcja) {
    var gate = window._lastGate;
    if (!gate || !gate.sesja_id || !gate.etap_id) return;

    await fetch('/api/pipeline/lab/ebr/' + ebrId + '/etap/' + gate.etap_id + '/close', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sesja_id: gate.sesja_id, decyzja: 'przejscie'})
    });

    // Move to next stage
    var stages = etapy.filter(function(e) { return e.pipeline_etap_id; });
    var currentIdx = stages.findIndex(function(e) { return e.pipeline_etap_id === gate.etap_id; });
    var nextStage = stages[currentIdx + 1];

    if (nextStage) {
        showPipelineStage(nextStage.sekcja_lab, false);
    } else {
        // Last stage — reload
        if (typeof loadBatch === 'function') loadBatch(ebrId);
        else location.reload();
    }
}
```

- [ ] **Step 5: Add openSmallCorrectionDialog function (korekta_i_przejscie)**

```javascript
function openSmallCorrectionDialog() {
    var gate = window._lastGate;
    if (!gate || !gate.sesja_id) return;

    var komentarz = prompt('Opisz małą korektę (np. "dodatek 50kg wody"):');
    if (komentarz === null) return; // cancelled

    fetch('/api/pipeline/lab/ebr/' + ebrId + '/etap/' + gate.etap_id + '/close', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            sesja_id: gate.sesja_id,
            decyzja: 'korekta_i_przejscie',
            komentarz: komentarz
        })
    }).then(function(resp) {
        if (resp.ok) {
            completePompuj();
        }
    });
}
```

- [ ] **Step 6: Run tests**

```bash
pytest --tb=short -q
```

- [ ] **Step 7: Test manually — full flow**

On K7 batch:
1. Enter SO3 = 0.15 in utlenienie (above limit 0.1) → gate fail → correction panel appears
2. Enter Perhydrol amount → click "Zaleć korektę" → session closes, "Nowa runda" appears
3. Click "Nowa runda" → new round with copied OK values
4. Enter SO3 = 0.05 → gate pass → "Zatwierdź etap" button appears
5. Click "Zatwierdź etap" → flowchart updates, standaryzacja becomes active
6. In standaryzacja: fill SM, pH, NaCl, SA → gate pass → "Przepompuj" or "Mała korekta" buttons

- [ ] **Step 8: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: correction panel, decision buttons, new round in pipeline stages"
```

---

## Task 4: Verify end-to-end + edge cases

- [ ] **Step 1: Test utlenienie gate fail → correction → new round → pass → approve**

- [ ] **Step 2: Test standaryzacja cyclic flow: analiza → fail → correction → new round → pass → przepompuj**

- [ ] **Step 3: Test "Mała korekta + przepompuj" flow (korekta_i_przejscie)**

- [ ] **Step 4: Test non-pipeline product (e.g. Chelamid_DK with analiza_koncowa only) — no gate banner should appear for stages without warunki**

- [ ] **Step 5: Test batch switching — gate state resets**

- [ ] **Step 6: Run full test suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 7: Commit any fixes**

```bash
git add -A
git commit -m "fix: gates and decisions edge case fixes"
```

---

## Summary

| Task | What | File |
|------|------|------|
| 1 | Extend dual-write response | `adapter.py`, `routes.py` |
| 2 | Gate banner after save | `_fast_entry_content.html` |
| 3 | Correction panel + actions | `_fast_entry_content.html` |
| 4 | E2E verification | Manual testing |
