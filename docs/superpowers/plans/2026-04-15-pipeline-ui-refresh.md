# Pipeline UI Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle pipeline correction panels to "inset" style and add a dedicated event log (dziennik zdarzeń) view with inset table layout.

**Architecture:** CSS-only changes for panel restyling (new `.gate-inset` modifier class). Dziennik zdarzeń as a new JS-rendered view toggled by a button under the pipeline flowchart, reusing existing API data.

**Tech Stack:** CSS, vanilla JS (Jinja templates), existing Flask API endpoints

---

## File Structure

| File | Change |
|------|--------|
| `mbr/static/style.css` | Add `.gate-inset` panel styles + `.dz-*` dziennik table styles |
| `mbr/templates/laborant/_correction_panel.html` | Replace `gate-h2o2`/`gate-fail` with `gate-inset` on panel containers |
| `mbr/templates/laborant/_fast_entry_content.html` | Add dziennik button + `renderDziennikView()` + navigation logic |

---

### Task 1: Add inset panel CSS classes

**Files:**
- Modify: `mbr/static/style.css` (after line ~1962, gate section block)

- [ ] **Step 1: Add `.gate-inset` CSS classes to style.css**

Append after the existing `.gate-btn-sec:hover` rule (~line 1963):

```css
/* ═══ Inset panel style (correction panels) ═══ */
.gate-section.gate-inset {
  background: var(--surface-alt); border: 1px solid var(--border);
  box-shadow: inset 0 1px 3px rgba(0,0,0,0.04); border-radius: 10px;
}
.gate-section.gate-inset .gate-head {
  background: #fff; margin: -1px -1px 0; padding: 12px 16px;
  border-radius: 10px 10px 0 0; border-bottom: 1px solid var(--border);
}
.gate-section.gate-inset .gate-body { padding: 14px 16px; }
.gate-section.gate-inset .gate-actions {
  background: transparent; border-top: 1px solid var(--border);
}
.gate-section.gate-inset .corr-field-input {
  background: #fff; border-color: #d4d0c8;
}
.gate-section.gate-inset .corr-result {
  background: #fff; border: 1px solid var(--border); border-radius: 8px;
}
.gate-section.gate-inset.gate-inset-fail {
  border-color: var(--amber);
  box-shadow: inset 0 1px 3px rgba(0,0,0,0.04), 0 0 0 2px var(--amber-bg);
}
```

- [ ] **Step 2: Verify CSS loads correctly**

Run: refresh browser at `http://127.0.0.1:5001`, check DevTools for parse errors.

- [ ] **Step 3: Commit**

```bash
git add mbr/static/style.css
git commit -m "feat: add gate-inset CSS classes for correction panels"
```

---

### Task 2: Apply inset style to correction panels

**Files:**
- Modify: `mbr/templates/laborant/_correction_panel.html`

The panels use inline class strings in JS. Replace `gate-h2o2` and `gate-fail` with `gate-inset` (and `gate-inset gate-inset-fail` for FAIL state).

- [ ] **Step 1: Update `_renderPerhydrolPanel` container class**

Find (line ~59-62):
```javascript
var h2o2Cls = isNewRoundUtl ? 'gate-fail' : 'gate-h2o2';

container.innerHTML =
    '<div class="gate-section ' + h2o2Cls + '" style="margin-top:8px;">' +
```

Replace with:
```javascript
var h2o2Cls = isNewRoundUtl ? 'gate-inset gate-inset-fail' : 'gate-inset';

container.innerHTML =
    '<div class="gate-section ' + h2o2Cls + '" style="margin-top:8px;">' +
```

- [ ] **Step 2: Update `_renderStandaryzacjaV2Panel` container class**

Find (line ~146-149):
```javascript
var standCls = (isNewRoundStand || isPerhydrolWithStand) ? 'gate-fail' : 'gate-h2o2';

container.innerHTML =
    '<div class="gate-section ' + standCls + '" style="margin-top:8px;">' +
```

Replace with:
```javascript
var standCls = (isNewRoundStand || isPerhydrolWithStand) ? 'gate-inset gate-inset-fail' : 'gate-inset';

container.innerHTML =
    '<div class="gate-section ' + standCls + '" style="margin-top:8px;">' +
```

- [ ] **Step 3: Update `_renderStandaryzacjaPanel` container class (legacy)**

Find in `_renderStandaryzacjaPanel` (line ~310):
```javascript
'<div style="border:2px solid var(--blue, #3b82f6);border-radius:10px;background:var(--blue-bg, #eff6ff);padding:14px 16px;margin-top:12px;">' +
```

Replace with:
```javascript
'<div class="gate-section gate-inset" style="margin-top:12px;">' +
```

- [ ] **Step 4: Test visually**

Open a K7 batch with pipeline stages, enter measurements, verify:
- Sulfonowanie PASS: inset panel (neutral border)
- Utlenienie FAIL: inset panel with amber border
- Standaryzacja panels: same inset style

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/laborant/_correction_panel.html
git commit -m "feat: apply inset style to all correction panels"
```

---

### Task 3: Add dziennik zdarzeń CSS

**Files:**
- Modify: `mbr/static/style.css`

- [ ] **Step 1: Add dziennik table CSS classes**

Append to end of style.css:

```css
/* ═══ Dziennik zdarzeń (event log table) ═══ */
.dz-wrap {
  background: var(--surface-alt); border: 1px solid var(--border);
  box-shadow: inset 0 1px 3px rgba(0,0,0,0.04);
  border-radius: 10px; overflow: hidden; margin-top: 12px;
}
.dz-toolbar {
  padding: 10px 16px; display: flex; align-items: center; gap: 8px;
  background: #fff; border-bottom: 1px solid var(--border);
}
.dz-toolbar-title { font-size: 13px; font-weight: 700; }
.dz-toolbar-back { margin-left: auto; }
.dz-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.dz-table th {
  padding: 8px 12px; background: #fff; text-align: left;
  font-weight: 700; font-size: 10px; color: var(--text-dim);
  text-transform: uppercase; letter-spacing: 0.5px;
  border-bottom: 1px solid var(--border);
}
.dz-table .dz-stage-row td {
  background: #fff; font-weight: 700; color: var(--teal);
  font-size: 12px; padding: 10px 12px;
  border-bottom: 1px solid #d0e8e8; border-top: 1px solid var(--border);
}
.dz-table .dz-data-row td {
  padding: 6px 12px; border-bottom: 1px solid var(--border-subtle, #e8e4dc);
  background: #fafaf7; vertical-align: top;
}
.dz-table .dz-kor-row td {
  padding: 6px 12px; color: var(--amber); font-size: 10px;
  background: #fef8ee; border-bottom: 1px solid var(--border-subtle, #e8e4dc);
}
.dz-runda-nr {
  font-weight: 700; color: var(--teal); background: var(--teal-bg);
  padding: 1px 6px; border-radius: 3px; font-size: 10px;
}
.dz-mono { font-family: var(--mono); font-size: 11px; }
.dz-actor { font-size: 9px; color: var(--text-dim); }
.dz-empty { padding: 30px; text-align: center; color: var(--text-dim); font-size: 12px; }
```

- [ ] **Step 2: Commit**

```bash
git add mbr/static/style.css
git commit -m "feat: add dziennik zdarzeń table CSS"
```

---

### Task 4: Add dziennik button and view rendering

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Add dziennik button after pipeline flowchart**

Find in `renderPipelineSections()` (after the stage rendering, before `updateSpecPanel()`):

```javascript
    updateSpecPanel();
    return;
```

Add before `updateSpecPanel();`:

```javascript
    // Dziennik zdarzeń button
    var dzBtn = document.createElement('div');
    dzBtn.style.cssText = 'margin-top:8px;text-align:center;';
    dzBtn.innerHTML = '<button class="gate-btn gate-btn-sec" onclick="showDziennikView()" id="btn-dziennik">' +
        '<span style="margin-right:4px;">✎</span> Dziennik zdarze\u0144</button>';
    container.appendChild(dzBtn);
```

- [ ] **Step 2: Add `showDziennikView()` function**

Add before `// ═══ INIT` section:

```javascript
// ═══ DZIENNIK ZDARZEŃ VIEW ═══

async function showDziennikView() {
    var container = document.getElementById('sections-container');
    container.innerHTML = '<div class="dz-wrap"><div class="dz-empty">Ładowanie dziennika...</div></div>';

    var stages = etapy.filter(function(e) { return !!e.pipeline_etap_id; });
    var allRows = [];

    for (var i = 0; i < stages.length; i++) {
        var stage = stages[i];
        try {
            var resp = await fetch('/api/pipeline/lab/ebr/' + ebrId + '/etap/' + stage.pipeline_etap_id);
            if (!resp.ok) continue;
            var data = await resp.json();
            var sesje = data.sesje || [];
            var sesje_pomiary = data.sesje_pomiary || {};
            var sesje_korekty = data.sesje_korekty || {};
            var pola = (parametry[stage.sekcja_lab] || {}).pola || [];

            // Stage header row
            allRows.push({type: 'stage', nazwa: stage.nazwa, count: sesje.length});

            if (sesje.length === 0) {
                allRows.push({type: 'empty', text: 'oczekuje na analizę...'});
                continue;
            }

            sesje.forEach(function(s) {
                var pomiary = sesje_pomiary[String(s.id)] || sesje_pomiary[s.id] || [];
                var korekty = sesje_korekty[String(s.id)] || sesje_korekty[s.id] || [];

                // Count OK/FAIL
                var okCnt = 0, errCnt = 0;
                pomiary.forEach(function(p) {
                    if (p.wartosc != null) { p.w_limicie === 0 ? errCnt++ : okCnt++; }
                });

                // Param values string
                var valsArr = [];
                pola.forEach(function(pole) {
                    var pm = pomiary.find(function(p) { return p.kod === pole.kod; });
                    if (pm && pm.wartosc != null) {
                        valsArr.push((pole.skrot || pole.kod) + ': ' + pm.wartosc.toFixed(pole.precision || 2).replace('.', ','));
                    }
                });

                allRows.push({
                    type: 'data',
                    runda: s.runda,
                    vals: valsArr.join(' \u00b7 '),
                    okCnt: okCnt,
                    errCnt: errCnt,
                    wpisal: s.wpisal || '',
                    dt: s.dt_start ? s.dt_start.substring(5, 16).replace('T', ' ') : ''
                });

                korekty.forEach(function(k) {
                    var iloscStr = k.ilosc != null ? parseFloat(k.ilosc).toFixed(1).replace('.', ',') : '\u2014';
                    allRows.push({
                        type: 'kor',
                        substancja: k.substancja || '',
                        ilosc: iloscStr,
                        jednostka: k.jednostka || 'kg',
                        zalecil: k.zalecil || ''
                    });
                });
            });
        } catch(e) {
            allRows.push({type: 'stage', nazwa: stage.nazwa, count: 0});
            allRows.push({type: 'empty', text: 'błąd ładowania'});
        }
    }

    // Render table
    var html = '<div class="dz-wrap">' +
        '<div class="dz-toolbar">' +
            '<span class="dz-toolbar-title">Dziennik zdarze\u0144</span>' +
            '<button class="gate-btn gate-btn-sec dz-toolbar-back" onclick="hideDziennikView()">Powr\u00f3t do etapu</button>' +
        '</div>' +
        '<table class="dz-table">' +
        '<tr><th>Runda</th><th>Parametry</th><th>Status</th><th>Korekta</th><th>Kto</th></tr>';

    allRows.forEach(function(row) {
        if (row.type === 'stage') {
            html += '<tr class="dz-stage-row"><td colspan="5">' + esc(row.nazwa) + '</td></tr>';
        } else if (row.type === 'empty') {
            html += '<tr class="dz-data-row"><td></td><td colspan="3" style="color:var(--text-dim);font-size:10px;">' + esc(row.text) + '</td><td></td></tr>';
        } else if (row.type === 'data') {
            var statusHtml = '';
            if (row.errCnt > 0) statusHtml = '<span class="rh-badge rh-badge-err">' + row.errCnt + ' poza</span>';
            else if (row.okCnt > 0) statusHtml = '<span class="rh-badge rh-badge-ok">' + row.okCnt + ' OK</span>';
            html += '<tr class="dz-data-row">' +
                '<td><span class="dz-runda-nr">R' + row.runda + '</span></td>' +
                '<td class="dz-mono">' + esc(row.vals) + '</td>' +
                '<td>' + statusHtml + '</td>' +
                '<td>\u2014</td>' +
                '<td class="dz-actor">' + esc(row.wpisal) + (row.dt ? ' \u00b7 ' + row.dt : '') + '</td>' +
            '</tr>';
        } else if (row.type === 'kor') {
            html += '<tr class="dz-kor-row">' +
                '<td></td>' +
                '<td colspan="3">\u2192 ' + esc(row.substancja) + ' \u2014 ' + row.ilosc + ' ' + esc(row.jednostka) + '</td>' +
                '<td class="dz-actor">' + esc(row.zalecil) + '</td>' +
            '</tr>';
        }
    });

    html += '</table></div>';
    container.innerHTML = html;
}

function hideDziennikView() {
    window._activePipelineStage = null;
    renderSections();
}
```

- [ ] **Step 3: Test visually**

Open K7 batch with completed stages, click "Dziennik zdarzeń", verify:
- All 3 stages shown with stage header rows
- Rounds with R1/R2 badges, parameter values, OK/FAIL badges
- Corrections shown with amber row
- "Powrót do etapu" returns to stage view

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: dziennik zdarzeń view with inset table"
```

---

### Task 5: Final verification and push

- [ ] **Step 1: Run tests**

```bash
pytest tests/ -x -q
```
Expected: all pass

- [ ] **Step 2: Visual smoke test**

Open K7 batch, test full flow:
1. Sulfonowanie: enter measurements → PASS panel (inset style) → zatwierdź
2. Utlenienie: enter measurements → PASS panel (inset) / FAIL panel (amber inset)
3. Standaryzacja: PASS/FAIL panels (inset)
4. Click "Dziennik zdarzeń" under flowchart → table view
5. Click "Powrót" → back to stage

- [ ] **Step 3: Push**

```bash
git push origin main
```
