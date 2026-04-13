# Stage Decision Panels — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unconditional "Zatwierdź etap" button with contextual two-button decision panels per stage: korekta (loop) vs przejście (advance), with formula-calculated correction amounts.

**Architecture:** New `jest_przejscie` column on `etap_korekty_katalog` distinguishes loop-corrections from transition-corrections. New `renderStageDecisionPanel()` JS function fetches corrections from API and renders two-button choice with expandable correction inputs. Removes old approve bar and debug logs.

**Tech Stack:** SQLite migration, Python setup script, vanilla JS

---

## File Structure

### Files to modify:
```
mbr/models.py                                        — ALTER TABLE migration for jest_przejscie
mbr/pipeline/adapter.py                               — fix _dodatki skip in dual_write
scripts/setup_sulfonowanie_utlenienie.py               — add Perhydrol to sulfonowanie with jest_przejscie=1
mbr/templates/laborant/_fast_entry_content.html        — renderStageDecisionPanel, remove old approve bar + debug logs
```

---

## Task 1: Add jest_przejscie column + Perhydrol to sulfonowanie

**Files:**
- Modify: `mbr/models.py` (add migration)
- Modify: `scripts/setup_sulfonowanie_utlenienie.py` (add Perhydrol to sulfonowanie)

- [ ] **Step 1: Add migration in init_mbr_tables**

In `mbr/models.py`, find the last migration block (around the `product_ref_values` or latest ALTER TABLE section). Add:

```python
    # Migration: add jest_przejscie to etap_korekty_katalog
    try:
        ek_cols = [r[1] for r in db.execute("PRAGMA table_info(etap_korekty_katalog)").fetchall()]
        if "jest_przejscie" not in ek_cols:
            db.execute("ALTER TABLE etap_korekty_katalog ADD COLUMN jest_przejscie INTEGER DEFAULT 0")
            db.commit()
    except Exception:
        pass
```

Also update the CREATE TABLE for `etap_korekty_katalog` (around line 560) to include `jest_przejscie`:

Find:
```sql
            formula_opis    TEXT
        )
```

Add before the closing paren:
```sql
            formula_opis    TEXT,
            jest_przejscie  INTEGER DEFAULT 0
        )
```

- [ ] **Step 2: Update setup script to add Perhydrol to sulfonowanie**

In `scripts/setup_sulfonowanie_utlenienie.py`, in the setup function, after the sulfonowanie Na2SO3 correction setup, add Perhydrol with `jest_przejscie=1`:

Find the section that adds Na2SO3 to sulfonowanie and add after it:

```python
    # Add Perhydrol to sulfonowanie with jest_przejscie=1 (transition correction)
    perh_sulf = next((k for k in list_etap_korekty(db, sulf_id) if k["substancja"] == "Perhydrol 34%"), None)
    if not perh_sulf:
        kid = add_etap_korekta(db, sulf_id, "Perhydrol 34%", "kg", "produkcja", kolejnosc=2)
        stats["korekty"] += 1
    else:
        kid = perh_sulf["id"]

    # Set formula + jest_przejscie on Perhydrol for sulfonowanie
    perh_formula = "(C_so3 - target_so3) * 0.01214 * Meff + (target_nadtlenki > 0 ? target_nadtlenki * Meff / 350 : 0)"
    perh_zmienne = json.dumps({
        "C_so3": "pomiar:so3",
        "target_so3": "target:so3 (from utlenienie)",
        "target_nadtlenki": "target:nadtlenki (from utlenienie)",
        "Meff": "wielkosc_szarzy_kg > 6600 ? wielkosc_szarzy_kg - 1000 : wielkosc_szarzy_kg - 500",
    })
    db.execute(
        "UPDATE etap_korekty_katalog SET formula_ilosc=?, formula_zmienne=?, jest_przejscie=1 WHERE id=?",
        (perh_formula, perh_zmienne, kid),
    )
    stats["formuly"] += 1
```

Also need to ensure utlenienie targets (SO3, nadtlenki) are accessible for the perhydrol formula when called from sulfonowanie. The formula evaluator in JS needs targets from utlenienie's produkt_etap_limity. Add a step to copy utlenienie targets to sulfonowanie's produkt_etap_limity:

```python
    # Copy SO3/nadtlenki targets from utlenienie to sulfonowanie for formula eval
    for produkt in PRODUCTS:
        for param_kod in ["so3", "nadtlenki"]:
            pid = _get_param_id(db, param_kod)
            if not pid:
                continue
            utl_limit = db.execute(
                "SELECT target FROM produkt_etap_limity WHERE produkt=? AND etap_id=? AND parametr_id=?",
                (produkt, utl_id, pid),
            ).fetchone()
            if utl_limit and utl_limit["target"] is not None:
                set_produkt_etap_limit(db, produkt, sulf_id, pid, target=utl_limit["target"])
```

- [ ] **Step 3: Run setup + verify**

```bash
python -m scripts.setup_sulfonowanie_utlenienie
```

Verify:
```bash
sqlite3 data/batch_db.sqlite "SELECT substancja, jest_przejscie, formula_ilosc IS NOT NULL as has_formula FROM etap_korekty_katalog WHERE etap_id=4"
```

Expected: Na2SO3 (jest_przejscie=0, no formula), Perhydrol 34% (jest_przejscie=1, has formula)

- [ ] **Step 4: Run tests**

```bash
pytest --tb=short -q
```

- [ ] **Step 5: Commit**

```bash
git add mbr/models.py scripts/setup_sulfonowanie_utlenienie.py
git commit -m "feat: jest_przejscie column + Perhydrol transition correction for sulfonowanie"
```

---

## Task 2: Fix adapter + cleanup

**Files:**
- Modify: `mbr/pipeline/adapter.py` (fix _dodatki skip)
- Modify: `mbr/templates/laborant/_fast_entry_content.html` (remove debug logs)

- [ ] **Step 1: Fix pipeline_dual_write to skip all dodatki variants**

In `mbr/pipeline/adapter.py`, in `pipeline_dual_write`, find:

```python
    if base_sekcja == "dodatki":
        return None
```

Replace with:

```python
    if base_sekcja == "dodatki" or base_sekcja.endswith("_dodatki"):
        return None
```

- [ ] **Step 2: Remove debug console.log from _fast_entry_content.html**

Find and remove lines 1117-1118:

```javascript
    console.log('[PIPELINE] renderPipelineSections called, _activePipelineStage=' + window._activePipelineStage);
    console.trace('[PIPELINE] call stack');
```

- [ ] **Step 3: Run tests**

```bash
pytest --tb=short -q
```

- [ ] **Step 4: Commit**

```bash
git add mbr/pipeline/adapter.py mbr/templates/laborant/_fast_entry_content.html
git commit -m "fix: skip _dodatki in dual_write, remove debug console.log"
```

---

## Task 3: renderStageDecisionPanel

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Remove old unconditional approve bar**

In `renderPipelineSections()`, find and DELETE lines 1191-1205 (the entire block starting with `// "Zatwierdź etap" button`):

```javascript
    // "Zatwierdź etap" button — always visible when results exist (laborant decides when to proceed)
    if (!isReadonly && !activeReadonly && hasSomeResults) {
        var pipelineStages = etapy.filter(function(e){return e.pipeline_etap_id;});
        var isLastStage = pipelineStages.length > 0 && pipelineStages[pipelineStages.length - 1].pipeline_etap_id === activeEtap.pipeline_etap_id;
        var approveBar = document.createElement('div');
        approveBar.className = 'decision-bar';
        approveBar.style.cssText = 'padding:12px 16px;margin-top:12px;display:flex;gap:8px;align-items:center;';
        if (isLastStage) {
            approveBar.innerHTML = '<button class="btn-success" onclick="completePompuj()">Przepompuj na zbiornik</button>' +
                '<button class="btn-secondary" onclick="openSmallCorrectionDialog()">Mała korekta + przepompuj</button>';
        } else {
            approveBar.innerHTML = '<button class="btn-success" onclick="closePipelineStage(\'' + activeSekcja + '\')">Zatwierdź etap &rarr;</button>';
        }
        container.appendChild(approveBar);
    }
```

Replace with a single call:

```javascript
    // Stage decision panel — always visible for non-readonly pipeline stages
    if (!isReadonly && !activeReadonly) {
        renderStageDecisionPanel(container, activeSekcja, activeEtap);
    }
```

- [ ] **Step 2: Add renderStageDecisionPanel function**

Add this function BEFORE `renderPipelineSections` (around line 1115):

```javascript
// Cache for fetched correction catalogs per etap_id
var _correctionCache = {};

async function _fetchCorrections(etapId) {
    if (_correctionCache[etapId]) return _correctionCache[etapId];
    try {
        var resp = await fetch('/api/pipeline/lab/ebr/' + ebrId + '/etap/' + etapId);
        if (!resp.ok) return [];
        var data = await resp.json();
        _correctionCache[etapId] = data.korekty_katalog || [];
        return _correctionCache[etapId];
    } catch(e) { return []; }
}

function renderStageDecisionPanel(container, sekcja, activeEtap) {
    var pipelineStages = etapy.filter(function(e) { return e.pipeline_etap_id; });
    var isLastStage = pipelineStages.length > 0 &&
        pipelineStages[pipelineStages.length - 1].pipeline_etap_id === activeEtap.pipeline_etap_id;

    var panel = document.createElement('div');
    panel.className = 'stage-decision-panel';
    panel.id = 'sdp-' + sekcja;
    panel.style.cssText = 'margin-top:12px;padding:14px 18px;border:1.5px solid var(--border);border-radius:10px;background:var(--surface);';

    if (isLastStage) {
        // Last stage: pump/complete buttons
        panel.innerHTML =
            '<div style="display:flex;gap:8px;flex-wrap:wrap;">' +
                '<button class="btn-success" onclick="completePompuj()">Przepompuj na zbiornik</button>' +
                '<button class="btn-secondary" onclick="openSmallCorrectionDialog()">Mała korekta + przepompuj</button>' +
            '</div>';
        container.appendChild(panel);
        return;
    }

    // Loading state
    panel.innerHTML = '<span style="color:var(--text-dim);font-size:11px;">Ładowanie opcji...</span>';
    container.appendChild(panel);

    // Fetch corrections and render buttons
    var etapId = activeEtap.pipeline_etap_id;
    _fetchCorrections(etapId).then(function(korekty) {
        var korekcyjne = korekty.filter(function(k) { return !k.jest_przejscie; });
        var przejsciowe = korekty.filter(function(k) { return k.jest_przejscie; });

        // Find next stage name
        var currentIdx = pipelineStages.findIndex(function(e) { return e.pipeline_etap_id === etapId; });
        var nextStage = pipelineStages[currentIdx + 1];
        var nextName = nextStage ? nextStage.nazwa : 'następny etap';

        var html = '<div style="font-size:10px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">Decyzja</div>';
        html += '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;" id="sdp-buttons-' + sekcja + '">';

        // Loop corrections
        korekcyjne.forEach(function(k) {
            html += '<button class="btn-warn" onclick="showCorrectionInput(\'' + sekcja + '\',' + k.id + ',false)" data-kid="' + k.id + '">' +
                'Korekta ' + k.substancja + '</button>';
        });

        // Transition corrections (korekta + przejscie)
        przejsciowe.forEach(function(k) {
            html += '<button class="btn-success" onclick="showCorrectionInput(\'' + sekcja + '\',' + k.id + ',true)" data-kid="' + k.id + '">' +
                k.substancja + ' → ' + nextName + '</button>';
        });

        // Plain approve (if no transition corrections defined)
        if (przejsciowe.length === 0) {
            html += '<button class="btn-success" onclick="closePipelineStage(\'' + sekcja + '\')">' +
                'Zatwierdź → ' + nextName + '</button>';
        }

        html += '</div>';

        // Correction input area (hidden, shown on button click)
        html += '<div id="sdp-input-' + sekcja + '" style="display:none;"></div>';

        panel.innerHTML = html;

        // Store corrections data for later use
        panel._korektyData = korekty;
    });
}

function showCorrectionInput(sekcja, korektaId, jestPrzejscie) {
    var panel = document.getElementById('sdp-' + sekcja);
    var inputArea = document.getElementById('sdp-input-' + sekcja);
    if (!panel || !inputArea) return;

    var korekty = panel._korektyData || [];
    var k = korekty.find(function(x) { return x.id === korektaId; });
    if (!k) return;

    // Calculate formula if available
    var preVal = '';
    var preCalc = '';
    if (k.formula_ilosc) {
        var calc = evalCorrectionFormula(k.formula_ilosc, sekcja, k);
        if (calc !== null) {
            preVal = calc.toFixed(1);
            preCalc = '<span style="font-size:9px;color:var(--teal);margin-left:8px;">obliczono: ' + preVal.replace('.', ',') + ' ' + (k.jednostka || 'kg') + '</span>';
        }
    }

    var actionLabel = jestPrzejscie ? 'Zaleć i przejdź' : 'Zaleć korektę';
    var actionFn = jestPrzejscie
        ? 'submitCorrectionAndAdvance(\'' + sekcja + '\',' + korektaId + ')'
        : 'submitCorrectionAndLoop(\'' + sekcja + '\',' + korektaId + ')';

    inputArea.innerHTML =
        '<div style="display:flex;align-items:center;gap:8px;margin-top:6px;">' +
            '<span style="font-weight:600;font-size:12px;">' + k.substancja + '</span>' +
            '<span style="color:var(--text-dim);font-size:10px;">[' + (k.jednostka || 'kg') + ']</span>' +
            '<input type="number" step="any" class="pa-input" id="sdp-amount-' + sekcja + '" value="' + preVal + '" placeholder="Ilość" style="width:90px;font-size:12px;text-align:center;">' +
            preCalc +
            '<button class="btn-success" style="margin-left:auto;" onclick="' + actionFn + '">' + actionLabel + '</button>' +
            '<button class="btn-secondary" onclick="document.getElementById(\'sdp-input-' + sekcja + '\').style.display=\'none\'">Anuluj</button>' +
        '</div>';
    inputArea.style.display = '';
}

async function submitCorrectionAndLoop(sekcja, korektaId) {
    var amount = parseFloat(document.getElementById('sdp-amount-' + sekcja).value);
    if (!amount || amount <= 0) { alert('Wpisz ilość'); return; }

    var gate = window._lastGate;
    var etap_id = gate ? gate.etap_id : null;
    var sesja_id = gate ? gate.sesja_id : null;

    // Find etap_id from sekcja if no gate
    if (!etap_id) {
        var baseSekcja = sekcja.split('__')[0];
        var ae = etapy.find(function(e) { return e.pipeline_etap_id && e.sekcja_lab === baseSekcja; });
        if (ae) etap_id = ae.pipeline_etap_id;
    }
    if (!etap_id) return;

    // Get sesja_id if missing
    if (!sesja_id) {
        try {
            var resp = await fetch('/api/pipeline/lab/ebr/' + ebrId + '/etap/' + etap_id);
            if (resp.ok) {
                var data = await resp.json();
                if (data.current_sesja) sesja_id = data.current_sesja.id;
            }
        } catch(e) {}
    }
    if (!sesja_id) return;

    // POST correction
    await fetch('/api/pipeline/lab/ebr/' + ebrId + '/korekta', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sesja_id: sesja_id, korekta_typ_id: korektaId, ilosc: amount})
    });

    // Close session with korekta
    await fetch('/api/pipeline/lab/ebr/' + ebrId + '/etap/' + etap_id + '/close', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sesja_id: sesja_id, decyzja: 'korekta'})
    });

    // Start new round
    await fetch('/api/pipeline/lab/ebr/' + ebrId + '/etap/' + etap_id + '/start', {
        method: 'POST'
    });

    // Reload
    _correctionCache = {};
    if (typeof loadBatch === 'function') loadBatch(ebrId);
    else location.reload();
}

async function submitCorrectionAndAdvance(sekcja, korektaId) {
    var amount = parseFloat(document.getElementById('sdp-amount-' + sekcja).value);
    if (!amount || amount <= 0) { alert('Wpisz ilość'); return; }

    var gate = window._lastGate;
    var etap_id = gate ? gate.etap_id : null;
    var sesja_id = gate ? gate.sesja_id : null;

    if (!etap_id) {
        var baseSekcja = sekcja.split('__')[0];
        var ae = etapy.find(function(e) { return e.pipeline_etap_id && e.sekcja_lab === baseSekcja; });
        if (ae) etap_id = ae.pipeline_etap_id;
    }
    if (!etap_id) return;

    if (!sesja_id) {
        try {
            var resp = await fetch('/api/pipeline/lab/ebr/' + ebrId + '/etap/' + etap_id);
            if (resp.ok) {
                var data = await resp.json();
                if (data.current_sesja) sesja_id = data.current_sesja.id;
            }
        } catch(e) {}
    }
    if (!sesja_id) return;

    // POST correction
    await fetch('/api/pipeline/lab/ebr/' + ebrId + '/korekta', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sesja_id: sesja_id, korekta_typ_id: korektaId, ilosc: amount})
    });

    // Close session with przejscie (transition)
    await fetch('/api/pipeline/lab/ebr/' + ebrId + '/etap/' + etap_id + '/close', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sesja_id: sesja_id, decyzja: 'przejscie'})
    });

    // Start next stage session
    var stages = etapy.filter(function(e) { return e.pipeline_etap_id; });
    var currentIdx = stages.findIndex(function(e) { return e.pipeline_etap_id === etap_id; });
    var nextStage = stages[currentIdx + 1];

    if (nextStage) {
        await fetch('/api/pipeline/lab/ebr/' + ebrId + '/etap/' + nextStage.pipeline_etap_id + '/start', {
            method: 'POST'
        });
        _correctionCache = {};
        window._activePipelineStage = nextStage.sekcja_lab;
        window._activePipelineReadonly = false;
        if (typeof loadBatch === 'function') loadBatch(ebrId);
        else location.reload();
    }
}
```

- [ ] **Step 3: Ensure list_etap_korekty returns jest_przejscie**

Check `mbr/pipeline/models.py` `list_etap_korekty` — it uses `SELECT *` so it already returns all columns including `jest_przejscie`. No change needed.

- [ ] **Step 4: Run tests**

```bash
pytest --tb=short -q
```

- [ ] **Step 5: Manual test**

Open K7 batch, go to sulfonowanie:
1. Should see two buttons: "Korekta Na2SO3" and "Perhydrol 34% → Utlenienie"
2. Click "Korekta Na2SO3" → input expands → enter amount → "Zaleć korektę" → new round
3. Click "Perhydrol 34% → Utlenienie" → input with pre-calculated amount → "Zaleć i przejdź" → advances to utlenienie

Go to utlenienie:
1. Should see: "Korekta Perhydrol 34%" and "Zatwierdź → Standaryzacja"
2. Korekta → loop, Zatwierdź → advance

- [ ] **Step 6: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: stage decision panels with korekta/przejscie buttons and correction inputs"
```

---

## Task 4: E2E verification

- [ ] **Step 1: Full flow test**

K7 batch:
1. Sulfonowanie → enter SO3 → "Korekta Na2SO3" → enter amount → new round
2. Sulfonowanie round 2 → enter SO3 → "Perhydrol → Utlenienie" → pre-calculated amount → advance
3. Utlenienie → enter SO3, H2O2 → "Korekta Perhydrol" → amount → new round
4. Utlenienie round 2 → "Zatwierdź → Standaryzacja" → advance
5. Standaryzacja → existing cyclic flow → Przepompuj

- [ ] **Step 2: Test non-pipeline product**

Open a Chelamid_DK batch — should have no decision panel (analiza_koncowa only, last stage)

- [ ] **Step 3: Run full test suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 4: Commit + push**

```bash
git add -A
git commit -m "fix: stage decision panels e2e fixes"
git push
```

---

## Summary

| Task | What | Files |
|------|------|------|
| 1 | jest_przejscie column + Perhydrol in sulfonowanie | `models.py`, `setup script` |
| 2 | Fix dual_write + remove debug logs | `adapter.py`, `_fast_entry_content.html` |
| 3 | renderStageDecisionPanel + correction actions | `_fast_entry_content.html` |
| 4 | E2E verification | Manual testing |
