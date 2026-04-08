# Powtórzenie analizy + edycja zbiorników — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "Powtórz analizę" button to analiza końcowa for all products (linear + cyclic), with accordion-based round history. Add zbiorniki edit button on completed batches.

**Architecture:** Modify `renderLinearSections()` to detect `analiza_koncowa__N` rounds in wyniki and render accordion. Add repeat button after last AK section. For cyclic products, reuse existing decision bar. Zbiorniki edit uses existing pump modal with pre-selection.

**Tech Stack:** Python/Flask, SQLite, vanilla JS

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Modify | `mbr/templates/laborant/_fast_entry_content.html` | Accordion rounds in linear, repeat button, zbiorniki edit |
| Modify | `mbr/laborant/models.py` | Extend save_wyniki to handle wartosc_text for binary |

---

### Task 1: Render analiza_koncowa rounds in linear products

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

Currently `renderLinearSections()` (line 1286) renders `analiza_koncowa` as a single flat section. Need to detect if multiple rounds exist (`analiza_koncowa`, `analiza_koncowa__2`, `analiza_koncowa__3`...) and render old rounds as readonly collapsed accordions.

- [ ] **Step 1: Replace renderLinearSections()**

Find `function renderLinearSections()` (line 1286). Replace the entire function with:

```javascript
function renderLinearSections() {
    var container = document.getElementById('sections-container');
    container.innerHTML = '';
    var isReadonly = ebrStatus !== 'open';

    // Collect analiza_koncowa rounds from wyniki
    var akRounds = [];
    Object.keys(wyniki).forEach(function(key) {
        if (key === 'analiza_koncowa') {
            akRounds.push({sekcja: key, runda: 1});
        } else if (key.match(/^analiza_koncowa__(\d+)$/)) {
            var n = parseInt(key.split('__')[1]);
            akRounds.push({sekcja: key, runda: n});
        }
    });
    akRounds.sort(function(a, b) { return a.runda - b.runda; });

    // Determine current runda
    var lastRunda = akRounds.length > 0 ? akRounds[akRounds.length - 1].runda : 0;

    // For non-AK sections (zbiornik has only analiza_koncowa, skip others)
    etapy.forEach(function(etap, i) {
        var sekcja = etap.sekcja_lab || '';
        if (!sekcja) return;
        if (etap.read_only === true) return;
        if (sekcja === 'analiza_koncowa') return; // handled below with rounds
        var pola = getPola(sekcja);
        if (pola.length === 0) return;
        if (ebrTyp === 'zbiornik') return; // zbiornik only has AK

        var sekWyniki = wyniki[sekcja] || {};
        var hasSomeResults = Object.keys(sekWyniki).length > 0;
        var allInLimit = hasSomeResults && Object.values(sekWyniki).every(function(w) { return w.w_limicie === 1; });

        renderOneSection(container, {
            sekcja: sekcja,
            title: etap.nazwa,
            index: i + 1,
            pola: pola,
            sekWyniki: sekWyniki,
            hasSomeResults: hasSomeResults,
            allInLimit: allInLimit,
            isReadonly: isReadonly,
            isCurrent: false,
            prevOutOfLimit: [],
            saveBtnLabel: null
        });
    });

    // Render completed AK rounds as collapsed accordions
    var akPola = getPola('analiza_koncowa');
    if (akPola.length === 0) return;

    akRounds.forEach(function(round, idx) {
        var sekWyniki = wyniki[round.sekcja] || {};
        var hasSomeResults = Object.keys(sekWyniki).length > 0;
        var allInLimit = hasSomeResults && Object.values(sekWyniki).every(function(w) { return w.w_limicie === 1; });
        var isLast = idx === akRounds.length - 1;

        if (!isLast || isReadonly) {
            // Old round — collapsed accordion with summary
            var summary = _buildAkSummary(akPola, sekWyniki);
            var accId = 'ak-acc-' + round.runda;
            var section = document.createElement('div');
            section.className = 'ps-accordion';
            section.id = accId;
            section.innerHTML =
                '<div class="ps-acc-toggle" onclick="document.getElementById(\'' + accId + '\').classList.toggle(\'ps-acc-open\')">' +
                    '<svg class="ps-acc-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="9 18 15 12 9 6"/></svg>' +
                    '<span class="ps-acc-title">' + (round.runda === 1 ? 'Analiza końcowa' : 'Analiza końcowa — powtórzenie ' + (round.runda - 1)) + '</span>' +
                    '<span class="sec-badge ' + (allInLimit ? 'b-ok' : '') + '" style="margin-left:auto;">' + (allInLimit ? 'OK' : 'Poza limitem') + '</span>' +
                '</div>' +
                '<div class="ps-acc-body">' + summary + '</div>';
            container.appendChild(section);
        } else {
            // Current (last) round — editable
            renderOneSection(container, {
                sekcja: round.sekcja,
                title: round.runda === 1 ? 'Analiza końcowa' : 'Analiza końcowa — powtórzenie ' + (round.runda - 1),
                index: akRounds.length,
                pola: akPola,
                sekWyniki: sekWyniki,
                hasSomeResults: hasSomeResults,
                allInLimit: allInLimit,
                isReadonly: false,
                isCurrent: true,
                prevOutOfLimit: [],
                saveBtnLabel: null
            });
        }
    });

    // If no rounds yet, render empty editable AK section
    if (akRounds.length === 0 && !isReadonly) {
        renderOneSection(container, {
            sekcja: 'analiza_koncowa',
            title: 'Analiza końcowa',
            index: 1,
            pola: akPola,
            sekWyniki: {},
            hasSomeResults: false,
            allInLimit: false,
            isReadonly: false,
            isCurrent: true,
            prevOutOfLimit: [],
            saveBtnLabel: null
        });
    }

    // "Powtórz analizę" button — show after last AK if has results and is open
    if (!isReadonly && lastRunda > 0) {
        var lastWyniki = wyniki[akRounds[akRounds.length - 1].sekcja] || {};
        if (Object.keys(lastWyniki).length > 0) {
            var repeatBar = document.createElement('div');
            repeatBar.className = 'repeat-bar';
            repeatBar.innerHTML =
                '<button class="btn-secondary" onclick="repeatAnaliza()" style="display:flex;align-items:center;gap:6px;">' +
                    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px;"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/></svg>' +
                    'Powtórz analizę' +
                '</button>';
            container.appendChild(repeatBar);
        }
    }
}
```

- [ ] **Step 2: Add helper functions**

After `renderLinearSections()`, add:

```javascript
function _buildAkSummary(pola, sekWyniki) {
    var html = '<div class="ak-summary">';
    pola.forEach(function(pole) {
        var w = sekWyniki[pole.kod];
        if (!w) return;
        var val = w.wartosc != null ? String(w.wartosc).replace('.', ',') : (w.wartosc_text || '—');
        var cls = w.w_limicie === 1 ? 'val-ok' : w.w_limicie === 0 ? 'val-err' : '';
        html += '<span class="ak-sum-item ' + cls + '">' +
            '<span class="ak-sum-label">' + (pole.skrot || pole.label) + '</span> ' +
            '<span class="ak-sum-val">' + val + '</span>' +
        '</span>';
    });
    html += '</div>';
    return html;
}

function repeatAnaliza() {
    // Find next runda number
    var maxRunda = 0;
    Object.keys(wyniki).forEach(function(key) {
        if (key === 'analiza_koncowa') maxRunda = Math.max(maxRunda, 1);
        var m = key.match(/^analiza_koncowa__(\d+)$/);
        if (m) maxRunda = Math.max(maxRunda, parseInt(m[1]));
    });
    var nextRunda = maxRunda + 1;
    var nextSekcja = 'analiza_koncowa__' + nextRunda;
    // Add empty wyniki entry so renderLinearSections picks it up
    wyniki[nextSekcja] = {};
    renderSections();
    // Scroll to new section
    setTimeout(function() {
        var sections = document.querySelectorAll('.section.current');
        if (sections.length > 0) sections[sections.length - 1].scrollIntoView({behavior: 'smooth', block: 'start'});
    }, 100);
}
```

- [ ] **Step 3: Add CSS for repeat bar and AK summary**

In `mbr/static/style.css`, add at the end:

```css
/* Repeat analysis bar */
.repeat-bar {
  display: flex; justify-content: center; padding: 16px;
  margin-top: 8px;
}
.repeat-bar .btn-secondary {
  padding: 10px 20px; border-radius: 8px;
  border: 1.5px solid var(--border); background: var(--surface);
  font-size: 12px; font-weight: 600; font-family: var(--font);
  color: var(--text-sec); cursor: pointer;
  transition: all 0.15s;
}
.repeat-bar .btn-secondary:hover {
  border-color: var(--teal); color: var(--teal); background: var(--teal-bg);
}

/* AK round summary (inside accordion) */
.ak-summary {
  display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 16px;
}
.ak-sum-item {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 3px 8px; border-radius: 4px;
  font-size: 11px; background: var(--surface-alt);
  border: 1px solid var(--border-subtle);
}
.ak-sum-item.val-ok { background: var(--green-bg); border-color: var(--green); color: var(--green); }
.ak-sum-item.val-err { background: var(--red-bg); border-color: var(--red); color: var(--red); }
.ak-sum-label { font-weight: 600; }
.ak-sum-val { font-family: var(--mono); }
```

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html mbr/static/style.css
git commit -m "feat: repeat analiza końcowa with accordion rounds for linear products"
```

---

### Task 2: Add repeat button to cyclic products (decision bar)

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

Currently `renderDecisionButtons()` (line 1454) shows "Przepompuj" and "Korekta". "Korekta" starts a new standaryzacja round (additives + re-analysis). Need to also offer "Powtórz analizę" which skips additives and goes straight to a new AK round.

- [ ] **Step 1: Add "Powtórz analizę" to decision bar**

Find `function renderDecisionButtons(container)` (line 1454). Modify the innerHTML:

Old:
```javascript
    bar.innerHTML =
        '<span class="decision-label">Analiza zakonczona. Co dalej?</span>' +
        '<button class="btn-success" onclick="completePompuj()">Przepompuj na zbiornik</button>' +
        '<button class="btn-secondary" onclick="startKorekta()">Korekta</button>';
```

New:
```javascript
    bar.innerHTML =
        '<span class="decision-label">Analiza zakończona. Co dalej?</span>' +
        '<button class="btn-success" onclick="completePompuj()">Przepompuj na zbiornik</button>' +
        '<button class="btn-secondary" onclick="repeatAnalizaCyclic()">Powtórz analizę</button>' +
        '<button class="btn-secondary" onclick="startKorekta()">Korekta (standaryzacja)</button>';
```

- [ ] **Step 2: Add repeatAnalizaCyclic function**

After `startKorekta()` function, add:

```javascript
function repeatAnalizaCyclic() {
    // For cyclic products: skip additives, go straight to next analiza round
    var nextN = roundState.last_analiza + 1;
    var nextSekcja = 'analiza__' + nextN;
    wyniki[nextSekcja] = {};
    roundState.next_sekcja = nextSekcja;
    roundState.next_step = 'analiza';
    roundState.is_decision = false;
    renderSections();
}
```

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: add 'Powtórz analizę' option to cyclic product decision bar"
```

---

### Task 3: Edit zbiorniki on completed batch

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

On completed batch view, show assigned tanks with an edit button that opens pump modal.

- [ ] **Step 1: Add zbiorniki display + edit button to completed view**

Find `function renderCompletedView()` (line 824). After the existing content is rendered (after the cert section), add zbiorniki section. Find the line:

```javascript
    container.innerHTML = html;
```

(This is around line 1025 inside renderCompletedView). Before this line, add:

```javascript
    // Zbiorniki section for completed batch
    html += '<div class="cv-zbiorniki" id="cv-zbiorniki">';
    html += '<div class="cv-section-label" style="display:flex;align-items:center;gap:8px;margin-top:20px;margin-bottom:8px;">' +
        '<span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-dim);">Zbiorniki</span>' +
        '<button class="btn-secondary" onclick="editCompletedZbiorniki()" style="font-size:10px;padding:4px 10px;border-radius:6px;border:1px solid var(--border);background:var(--surface);cursor:pointer;color:var(--text-dim);">Edytuj</button>' +
    '</div>';
    html += '<div id="cv-zb-list" style="display:flex;flex-wrap:wrap;gap:6px;"></div>';
    html += '</div>';
```

- [ ] **Step 2: Add JS to load and display zbiorniki + edit function**

After renderCompletedView, add:

```javascript
async function loadCompletedZbiorniki() {
    var container = document.getElementById('cv-zb-list');
    if (!container) return;
    try {
        var resp = await fetch('/api/zbiornik-szarze/' + ebrId);
        var links = await resp.json();
        if (links.length === 0) {
            container.innerHTML = '<span style="font-size:11px;color:var(--text-dim);">Brak przypisanych zbiorników</span>';
            return;
        }
        var html = '';
        links.forEach(function(l) {
            html += '<span class="td-zb-sticker" style="font-size:11px;padding:4px 10px;">' + l.nr_zbiornika +
                (l.masa_kg ? ' · ' + l.masa_kg.toLocaleString('pl') + ' kg' : '') + '</span>';
        });
        container.innerHTML = html;
    } catch(e) {}
}

function editCompletedZbiorniki() {
    openPumpModal();
}
```

Then add `loadCompletedZbiorniki()` call after `container.innerHTML = html;` in renderCompletedView:

```javascript
    setTimeout(loadCompletedZbiorniki, 100);
```

- [ ] **Step 3: Update pump modal confirmPump to handle edit mode (no completion)**

Find `async function confirmPump()`. Currently it always calls `/laborant/ebr/{id}/complete`. For completed batches, it should just save links without completing again.

After the targets are built, before the fetch, add:

```javascript
    // Edit mode: if batch already completed, just save links without re-completing
    if (ebrStatus === 'completed') {
        // Delete existing links, save new ones
        var delResp = await fetch('/api/zbiornik-szarze/' + ebrId);
        var existing = await delResp.json();
        for (var el of existing) {
            await fetch('/api/zbiornik-szarze/' + el.id, {method: 'DELETE'});
        }
        for (var t of targets) {
            await fetch('/api/zbiornik-szarze', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ebr_id: ebrId, zbiornik_id: t.zbiornik_id, masa_kg: t.kg})
            });
        }
        closePumpModal();
        loadCompletedZbiorniki();
        return;
    }
```

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: display and edit zbiorniki on completed batches"
```
