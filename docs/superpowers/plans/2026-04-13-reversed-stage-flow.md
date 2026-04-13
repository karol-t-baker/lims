# Reversed Stage Flow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reverse non-main cyclic stage flow to DODATEK→ANALIZA→DECYZJA, add dynamic "Cele" tab in right panel replacing "Wartości typowe", remove companion dodatki stages from adapter.

**Architecture:** Adapter stops generating companion `_dodatki` etap entries and parametry_lab sections for non-main cyclic stages — korekty data stays in `etap_korekty_katalog` (fetched on demand by decision panel). `renderPipelineSections` renders inline DODATEK block (runda 2+) above ANALIZA within same section. Right panel tab "Wartości typowe" becomes "Cele" with targets from active stage's pola.

**Tech Stack:** Python adapter changes, vanilla JS template changes, CSS for new blocks

---

## File Structure

### Files to modify:
```
mbr/pipeline/adapter.py                               — remove companion dodatki for non-main cyclic
mbr/templates/laborant/_fast_entry_content.html        — reversed flow rendering + Cele panel
tests/test_pipeline_adapter.py                         — update tests for new adapter output
```

---

## Task 1: Remove companion dodatki from adapter

**Files:**
- Modify: `mbr/pipeline/adapter.py`
- Modify: `tests/test_pipeline_adapter.py`

- [ ] **Step 1: Update adapter — remove non-main cyclic companion stages**

In `mbr/pipeline/adapter.py`, in `build_pipeline_context`, find the block at lines 278-294 that generates companion dodatki entries. Change the condition so it ONLY generates companions for the main cyclic stage (standaryzacja), not for sulfonowanie/utlenienie.

Find:
```python
        # --- cykliczny: add companion "dodatki" entry ---
        if typ_cyklu == "cykliczny" and dodatki_key:
```

Replace with:
```python
        # --- main cykliczny only: add companion "dodatki" entry ---
        # Non-main cyclic stages (sulfonowanie, utlenienie) handle corrections
        # inline via renderStageDecisionPanel, not as separate sections.
        if typ_cyklu == "cykliczny" and dodatki_key and etap_id == main_cykliczny_id:
```

This means only standaryzacja (main cyclic) generates companion "dodatki"/"analiza" sections. Sulfonowanie and utlenienie get a single section each with no companion.

- [ ] **Step 2: Update adapter tests**

In `tests/test_pipeline_adapter.py`, find `test_cykliczny_generates_dodatki_stage`. This test creates a single cykliczny stage and checks for "dodatki" in etapy. Since a single cykliczny stage IS the main one, this test should still pass. But verify.

Also add a new test:

```python
def test_non_main_cyclic_no_companion_dodatki(db):
    """Non-main cyclic stages should NOT generate companion dodatki."""
    _seed_params(db)
    # Create two cyclic stages — first is non-main, second is main
    e1 = create_etap(db, kod="sulf_test", nazwa="Sulfonowanie", typ_cyklu="cykliczny")
    e2 = create_etap(db, kod="stand_test", nazwa="Standaryzacja", typ_cyklu="cykliczny")
    add_etap_parametr(db, e1, 9101, kolejnosc=1)
    add_etap_parametr(db, e2, 9101, kolejnosc=1)
    set_produkt_pipeline(db, "TestMultiCyclic", e1, kolejnosc=1)
    set_produkt_pipeline(db, "TestMultiCyclic", e2, kolejnosc=2)
    set_produkt_etap_limit(db, "TestMultiCyclic", e1, 9101, min_limit=0, max_limit=1)
    set_produkt_etap_limit(db, "TestMultiCyclic", e2, 9101, min_limit=40, max_limit=50)
    db.commit()

    ctx = build_pipeline_context(db, "TestMultiCyclic")
    sekcje = [e["sekcja_lab"] for e in ctx["etapy_json"]]
    # Main cyclic (last = stand_test) should have companion "dodatki"
    assert "dodatki" in sekcje or "analiza" in sekcje
    # Non-main cyclic (sulf_test) should NOT have companion
    assert "sulf_test_dodatki" not in sekcje
    # sulf_test should have its own sekcja
    assert "sulf_test" in sekcje
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_pipeline_adapter.py -v
pytest --tb=short -q
```

- [ ] **Step 4: Commit**

```bash
git add mbr/pipeline/adapter.py tests/test_pipeline_adapter.py
git commit -m "feat: adapter — non-main cyclic stages no longer generate companion dodatki"
```

---

## Task 2: Right panel — "Cele" tab replacing "Wartości typowe"

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Change tab HTML**

Find lines 37-39 (the rp-tabs div):
```html
    <div class="rp-tab" id="tab-hist" onclick="showRightPanel('hist')">Wartości typowe</div>
    <div class="rp-tab active" id="tab-calc" onclick="showRightPanel('calc')">Kalkulator</div>
```

Replace with:
```html
    <div class="rp-tab" id="tab-cele" onclick="showRightPanel('cele')">Cele</div>
    <div class="rp-tab active" id="tab-calc" onclick="showRightPanel('calc')">Kalkulator</div>
```

- [ ] **Step 2: Change rp-view for hist → cele**

Find lines 42-48 (the rp-hist view):
```html
    <div class="rp-view" id="rp-hist">
      <div style="padding:16px 12px;">
        <div style="font-size:12px; font-weight:600; color:var(--text-dim); margin-bottom:8px;">Wartości typowe (historyczne)</div>
        <div style="font-size:11px; color:var(--text-dim); line-height:1.6;">
          Dane pojawią się po zebraniu wystarczającej liczby szarż.
        </div>
      </div>
    </div>
```

Replace with:
```html
    <div class="rp-view" id="rp-cele">
      <div id="cele-container" style="padding:0;">
        <div style="padding:10px 14px;background:var(--teal-bg);font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:var(--teal);">Cele aktywnego etapu</div>
        <div id="cele-body" style="font-size:12px;color:var(--text-dim);padding:14px;">Wybierz etap.</div>
      </div>
    </div>
```

- [ ] **Step 3: Update showRightPanel function**

Find `showRightPanel` function (line ~3723). Replace with:

```javascript
function showRightPanel(view) {
    document.querySelectorAll('.rp-tab').forEach(function(t) { t.classList.remove('active'); });
    document.querySelectorAll('.rp-view').forEach(function(v) { v.classList.remove('active'); });
    var tabId = 'tab-' + view;
    var viewId = 'rp-' + view;
    var tab = document.getElementById(tabId);
    var vw = document.getElementById(viewId);
    if (tab) tab.classList.add('active');
    if (vw) vw.classList.add('active');
}
```

- [ ] **Step 4: Add updateCelePanel function**

Add before `showRightPanel`:

```javascript
function updateCelePanel() {
    var body = document.getElementById('cele-body');
    if (!body) return;

    var activeSekcja = window._activePipelineStage;
    if (!activeSekcja) { body.innerHTML = '<div style="padding:14px;color:var(--text-dim);font-size:11px;">Wybierz etap.</div>'; return; }

    // Find pola for active sekcja
    var sekData = parametry[activeSekcja];
    if (!sekData) {
        // Try 'analiza' for main cyclic
        sekData = parametry['analiza'];
    }
    if (!sekData || !sekData.pola) { body.innerHTML = '<div style="padding:14px;color:var(--text-dim);font-size:11px;">Brak danych.</div>'; return; }

    // Filter to pola with target
    var withTarget = sekData.pola.filter(function(p) { return p.target != null; });
    if (withTarget.length === 0) { body.innerHTML = '<div style="padding:14px;color:var(--text-dim);font-size:11px;">Brak celów dla tego etapu.</div>'; return; }

    var html = '<table style="width:100%;border-collapse:collapse;font-size:12px;">';
    withTarget.forEach(function(p) {
        var sek = wyniki[activeSekcja] || {};
        var pomiar = sek[p.kod];
        var aktVal = pomiar ? String(pomiar.wartosc).replace('.', ',') : '—';
        var aktColor = !pomiar ? 'var(--text-dim)' : (pomiar.w_limicie === 0 ? 'var(--red)' : 'var(--green)');

        html += '<tr style="border-bottom:1px solid var(--border-subtle);">' +
            '<td style="padding:10px 14px;font-weight:600;">' + (p.skrot || p.label || p.kod) + '</td>' +
            '<td style="padding:10px 14px;font-family:var(--mono);font-weight:700;color:var(--teal);text-align:right;font-size:14px;">' +
                '<input class="target-edit" type="text" inputmode="decimal" value="' + String(p.target).replace('.', ',') + '" ' +
                'data-kod="' + p.kod + '" data-sekcja="' + activeSekcja + '" onblur="saveTarget(this)" ' +
                'style="width:70px;border:1px solid transparent;border-radius:3px;padding:2px 4px;font-family:var(--mono);font-size:14px;font-weight:700;color:var(--teal);text-align:center;background:transparent;cursor:pointer;" ' +
                'onfocus="this.style.borderColor=\'var(--teal)\';this.style.background=\'#fff\'" ' +
                'onblur="this.style.borderColor=\'transparent\';this.style.background=\'transparent\';saveTarget(this)">' +
            '</td>' +
        '</tr>';
    });
    html += '</table>';
    body.innerHTML = html;
}
```

- [ ] **Step 5: Call updateCelePanel from showPipelineStage and renderPipelineSections**

In `showPipelineStage` (line ~4983), add `updateCelePanel()`:

```javascript
window.showPipelineStage = function(sekcjaLab, readonly) {
    window._activePipelineStage = sekcjaLab;
    window._activePipelineReadonly = !!readonly;
    renderSections();
    if (typeof renderSidebarEtapy === 'function') renderSidebarEtapy();
    updateCelePanel();
};
```

At the end of `renderPipelineSections`, add:

```javascript
    // Update right panel Cele tab
    updateCelePanel();
```

Also call it at init — at the end of the INIT section (after `renderSections()`):

```javascript
renderSections();
setupComputedFields();
loadBatchZbiorniki();
updateCelePanel();
```

- [ ] **Step 6: Remove old target-hint from renderOneSection**

Find in `renderOneSection` the line that renders target-hint inline (the `pole.target != null` conditional):

```javascript
                (pole.target != null ? '<div class="target-hint">cel: <input class="target-edit"...
```

Remove this entire conditional line (targets are now in the right panel, not inline).

- [ ] **Step 7: Run tests + manual test**

```bash
pytest --tb=short -q
```

Open K7 batch, verify:
- Tab "Cele" shows targets for active stage
- Switching stages updates targets
- Clicking target value makes it editable

- [ ] **Step 8: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: right panel Cele tab with dynamic per-stage targets, replaces Wartości typowe"
```

---

## Task 3: Reversed flow rendering — DODATEK block in runda 2+

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Add renderNonMainCyclicSection function**

Add before `renderPipelineSections`:

```javascript
function renderNonMainCyclicSection(container, activeSekcja, activeEtap, isReadonly, activeReadonly, entryGrupa) {
    // Determine round number from pipeline sessions
    // For non-main cyclic: count rounds by checking if correction data exists in wyniki
    var sekWyniki = wyniki[activeSekcja] || {};
    var hasSomeResults = Object.keys(sekWyniki).length > 0;

    // Check if this is runda 2+ by looking for correction entries in wyniki
    var korektaKeys = Object.keys(sekWyniki).filter(function(k) { return k.startsWith('korekta_') || k === 'Na2SO3' || k === 'Perhydrol 34%'; });
    var isRunda2Plus = korektaKeys.length > 0;

    // DODATEK block (runda 2+ only)
    if (isRunda2Plus && !isReadonly && !activeReadonly) {
        var dodatekDiv = document.createElement('div');
        dodatekDiv.className = 'section';
        dodatekDiv.style.cssText = 'margin-bottom:8px;';

        var dodatekHead = '<div class="sec-head" style="padding:10px 18px;">' +
            '<div class="sec-icon amber" style="width:22px;height:22px;font-size:9px;">+</div>' +
            '<span class="sec-title" style="font-size:12px;">Dodatek</span>' +
        '</div>';

        var dodatekBody = '<div class="fg">';
        // Render existing correction values as readonly
        korektaKeys.forEach(function(kod) {
            var val = sekWyniki[kod];
            var displayVal = val && val.wartosc != null ? String(val.wartosc).replace('.', ',') : '—';
            dodatekBody += '<div class="ff">' +
                '<div class="status-dot ok"></div>' +
                '<label>' + kod + '</label>' +
                '<span class="val ok">' + displayVal + ' kg</span>' +
            '</div>';
        });
        dodatekBody += '</div>';
        dodatekDiv.innerHTML = dodatekHead + dodatekBody;
        container.appendChild(dodatekDiv);
    }

    // ANALIZA block (always)
    var pola = getPola(activeSekcja, entryGrupa);
    // Filter out correction pola (they're shown in DODATEK block)
    pola = pola.filter(function(p) { return !p.kod.startsWith('korekta_') && p.kod !== 'Na2SO3' && p.kod !== 'Perhydrol 34%'; });

    if (pola.length === 0) {
        container.innerHTML += '<div style="padding:40px;text-align:center;color:var(--text-dim);font-size:13px;">Brak parametrów.</div>';
        return;
    }

    var allInLimit = hasSomeResults && Object.values(sekWyniki).every(function(w) { return w.w_limicie === 1 || w.w_limicie === null; });

    renderOneSection(container, {
        sekcja: activeSekcja,
        title: activeEtap.nazwa + ' — Analiza',
        index: 1,
        pola: pola,
        sekWyniki: sekWyniki,
        hasSomeResults: hasSomeResults,
        allInLimit: allInLimit,
        isReadonly: isReadonly || activeReadonly,
        isCurrent: !activeReadonly,
        prevOutOfLimit: [],
        saveBtnLabel: null
    });

    // DECISION panel (always for non-readonly)
    if (!isReadonly && !activeReadonly) {
        renderStageDecisionPanel(container, activeSekcja, activeEtap);
    }
}
```

- [ ] **Step 2: Use renderNonMainCyclicSection in renderPipelineSections**

In `renderPipelineSections`, find the block after the main cyclic check (line ~1374):

```javascript
    // Jednorazowy or non-main cyclic: render single section
    var pola = getPola(activeSekcja, entryGrupa);
```

Replace the entire block from there to the end of the function (including the decision panel call) with:

```javascript
    // Non-main cyclic stage: reversed flow (DODATEK → ANALIZA → DECYZJA)
    if (activeEtap.typ_cyklu === 'cykliczny') {
        renderNonMainCyclicSection(container, activeSekcja, activeEtap, isReadonly, activeReadonly, entryGrupa);
        updateCelePanel();
        return;
    }

    // Jednorazowy: render single section + decision
    var pola = getPola(activeSekcja, entryGrupa);
    if (pola.length === 0) {
        container.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-dim);font-size:13px;">Brak parametrów dla tego etapu.</div>';
        return;
    }

    var sekWyniki = wyniki[activeSekcja] || {};
    var hasSomeResults = Object.keys(sekWyniki).length > 0;
    var allInLimit = hasSomeResults && Object.values(sekWyniki).every(function(w) { return w.w_limicie === 1; });

    renderOneSection(container, {
        sekcja: activeSekcja,
        title: activeEtap.nazwa,
        index: 1,
        pola: pola,
        sekWyniki: sekWyniki,
        hasSomeResults: hasSomeResults,
        allInLimit: allInLimit,
        isReadonly: isReadonly || activeReadonly,
        isCurrent: !activeReadonly,
        prevOutOfLimit: [],
        saveBtnLabel: null
    });

    if (!isReadonly && !activeReadonly) {
        renderStageDecisionPanel(container, activeSekcja, activeEtap);
    }

    updateCelePanel();
```

- [ ] **Step 3: Update submitCorrectionAndLoop to save correction amount to wyniki**

In `submitCorrectionAndLoop`, after the POST korekta call and before closing the session, add saving the correction amount to wyniki so it appears in the DODATEK block next round:

Find in `submitCorrectionAndLoop`:
```javascript
    await fetch('/api/pipeline/lab/ebr/' + ebrId + '/korekta', {
```

After that fetch, add:
```javascript
    // Save correction amount to wyniki so DODATEK block shows it
    var k = (_correctionCache[etap_id] || []).find(function(x) { return x.id === korektaId; });
    if (k) {
        var corrValues = {};
        corrValues[k.substancja] = { wartosc: String(amount), komentarz: '' };
        await fetch('/laborant/ebr/' + ebrId + '/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({sekcja: sekcja, values: corrValues})
        });
    }
```

- [ ] **Step 4: Run tests + manual test**

```bash
pytest --tb=short -q
```

Open K7 batch 37 (99/2026):
1. Sulfonowanie runda 1: only ANALIZA block (SO₃, pH, nD20, Barwa) + decision buttons
2. Click "Korekta Na₂SO₃" → enter amount → "Zaleć korektę" → new round
3. Sulfonowanie runda 2: DODATEK block (shows Na₂SO₃ amount) + ANALIZA block + decision
4. Click "Perhydrol → Utlenienie" → enter amount → advance
5. Right panel "Cele" shows SO₃ target dynamically

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: reversed flow — DODATEK block (runda 2+) above ANALIZA for non-main cyclic stages"
```

---

## Task 4: E2E verification + push

- [ ] **Step 1: Full flow test K7**

1. Create new K7 batch
2. Sulfonowanie: enter SO₃ → see Cele panel with SO₃ target → click "Korekta Na₂SO₃" → amount → new round
3. Sulfonowanie runda 2: see DODATEK block with Na₂SO₃ → enter SO₃ → "Perhydrol → Utlenienie" → advance
4. Utlenienie: enter SO₃, H₂O₂ → Cele shows both targets → "Korekta Perhydrol" → amount → new round
5. Utlenienie runda 2: DODATEK with Perhydrol → enter SO₃ → "Zamknij → Standaryzacja" → advance
6. Standaryzacja: existing cyclic flow (unchanged)
7. Analiza końcowa: parameters only, last stage → "Przepompuj"

- [ ] **Step 2: Test non-pipeline product (Chelamid_DK)**

Should show analiza_koncowa only, no Cele panel data, existing flow works.

- [ ] **Step 3: Run full test suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 4: Push**

```bash
git add -A
git commit -m "fix: reversed flow e2e fixes"
git push
```

---

## Summary

| Task | What | Files |
|------|------|------|
| 1 | Remove companion dodatki from adapter | `adapter.py`, `test_pipeline_adapter.py` |
| 2 | Cele tab in right panel | `_fast_entry_content.html` |
| 3 | Reversed flow rendering (DODATEK → ANALIZA) | `_fast_entry_content.html` |
| 4 | E2E verification + push | Manual testing |
