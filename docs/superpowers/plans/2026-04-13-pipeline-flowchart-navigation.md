# Pipeline Flowchart + Section Navigation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dynamic pipeline flowchart to the sidebar and show/hide sections per active stage, so laborant works one stage at a time instead of seeing all sections at once.

**Architecture:** Two JS changes: (1) new branch in `renderSidebarEtapy()` in szarze_list.html for pipeline products, (2) new `renderPipelineSections()` path in `_fast_entry_content.html` that renders only the active stage's section. Detection via `pipeline_etap_id` field in etapy_json. No backend changes.

**Tech Stack:** Vanilla JS, existing CSS classes (`.se-step`, `.se-num`, `.se-list`)

---

## File Structure

### Files to modify:
```
mbr/templates/laborant/szarze_list.html              — renderSidebarEtapy() pipeline branch
mbr/templates/laborant/_fast_entry_content.html       — renderSections() pipeline dispatch + renderPipelineSections()
```

No new files. No backend changes.

---

## Task 1: Pipeline flowchart in sidebar

**Files:**
- Modify: `mbr/templates/laborant/szarze_list.html` (function `renderSidebarEtapy`, line 901)

- [ ] **Step 1: Add pipeline detection at start of renderSidebarEtapy**

At the top of `renderSidebarEtapy()` (line 901), after the existing guard clause (lines 902-906), add pipeline detection before the existing `isZbiornik` check:

```javascript
  // Pipeline products: dynamic flowchart from etapy_json
  var isPipeline = typeof etapy !== 'undefined' && etapy.some(function(e) { return e.pipeline_etap_id; });
  if (isPipeline) {
    renderPipelineFlowchart(container);
    return;
  }
```

- [ ] **Step 2: Add renderPipelineFlowchart function**

Add this function BEFORE `renderSidebarEtapy` (around line 900):

```javascript
function renderPipelineFlowchart(container) {
  // Filter out "dodatki" companion stages — they're part of cyclic stages, not separate steps
  var stages = etapy.filter(function(e) {
    var sek = e.sekcja_lab || '';
    return sek !== 'dodatki' && sek.indexOf('_dodatki') === -1;
  });

  // Determine stage statuses
  var stageStatuses = [];
  var foundActive = false;
  var rs = typeof roundState !== 'undefined' ? roundState : null;

  stages.forEach(function(e) {
    var sekcja = e.sekcja_lab || '';
    var status = 'pending';

    if (e.typ_cyklu === 'cykliczny') {
      // Cyclic stage (standaryzacja): check round state
      if (sekcja === 'analiza' && rs) {
        if (rs.last_analiza > 0) {
          if (rs.is_decision || ebrStatus === 'completed') {
            status = 'done';
          } else {
            status = 'active';
            foundActive = true;
          }
        } else if (!foundActive) {
          status = 'active';
          foundActive = true;
        }
      } else {
        // Non-main cyclic (utlenienie etc.)
        var hasWyniki = wyniki[sekcja] && Object.keys(wyniki[sekcja]).length > 0;
        if (hasWyniki) {
          status = 'done';
        } else if (!foundActive) {
          status = 'active';
          foundActive = true;
        }
      }
    } else {
      // Jednorazowy
      var hasWyniki = wyniki[sekcja] && Object.keys(wyniki[sekcja]).length > 0;
      if (hasWyniki || ebrStatus === 'completed') {
        status = 'done';
      } else if (!foundActive) {
        status = 'active';
        foundActive = true;
      }
    }

    stageStatuses.push({ etap: e, status: status, sekcja: sekcja });
  });

  // If nothing is active yet (all done or empty), mark first non-done as active
  if (!foundActive && ebrStatus === 'open') {
    var firstPending = stageStatuses.find(function(s) { return s.status === 'pending'; });
    if (firstPending) firstPending.status = 'active';
  }

  // Render
  var html = '<div class="se-list">';
  stageStatuses.forEach(function(ss, idx) {
    var e = ss.etap;
    var status = ss.status;
    var isCls = 'is-' + status;
    var numCls = status;

    // Special colors for standaryzacja and analiza_koncowa
    if (status === 'active') {
      if (e.typ_cyklu === 'cykliczny' && ss.sekcja === 'analiza') numCls = 'stand';
      if (ss.sekcja === 'analiza_koncowa') numCls = 'koncowa';
    }

    var clickable = status === 'done' || status === 'active';
    var clickAttr = clickable ? ' onclick="showPipelineStage(\'' + ss.sekcja + '\', ' + (status === 'done' ? 'true' : 'false') + ')"' : '';
    var cursorStyle = status === 'pending' ? ' style="cursor:not-allowed;opacity:0.5;"' : '';

    // Selected highlight
    var selectedSekcja = window._activePipelineStage || null;
    var selCls = (selectedSekcja === ss.sekcja) ? ' se-selected' : '';

    var statusText = status === 'done' ? 'Zakończone' : status === 'active' ? 'W toku' : 'Oczekuje';

    // Runda badge for cyclic stages
    var rundaBadge = '';
    if (e.typ_cyklu === 'cykliczny' && ss.sekcja === 'analiza' && rs && rs.last_analiza > 0) {
      rundaBadge = ' <span style="font-size:8px;background:var(--surface-alt);padding:1px 5px;border-radius:8px;color:var(--text-dim);">R' + rs.last_analiza + '</span>';
    }

    html += '<div class="se-step ' + isCls + selCls + '"' + clickAttr + cursorStyle + '>' +
      '<div class="se-num ' + numCls + '">' + (idx + 1) + '</div>' +
      '<div class="se-info">' +
        '<div class="se-name">' + e.nazwa + rundaBadge + '</div>' +
        '<div class="se-status">' + statusText + '</div>' +
      '</div>' +
    '</div>';
  });
  html += '</div>';
  container.innerHTML = html;
}
```

- [ ] **Step 3: Test manually**

```bash
python -m mbr.app
```

Open a K7 batch. Verify:
- Sidebar shows flowchart with 3 stages: Utlenienie, Standaryzacja, Analiza końcowa
- First stage without results is highlighted as active (teal pulse)
- Completed stages show green
- Pending stages are dimmed/unclickable
- Clicking done/active stages triggers `showPipelineStage` (may error if not yet implemented — that's OK)

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/szarze_list.html
git commit -m "feat: pipeline flowchart in sidebar with stage status + navigation"
```

---

## Task 2: Section show/hide per active stage

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html` (function `renderSections`, line 1070)

- [ ] **Step 1: Add pipeline detection in renderSections**

In `renderSections()` at line 1070, after the completed check (line 1082) and before the active process stage check (line 1084), add pipeline detection:

```javascript
    // Pipeline products: render only the active stage's section
    var isPipeline = etapy.some(function(e) { return e.pipeline_etap_id; });
    if (isPipeline) {
        renderPipelineSections();
        return;
    }
```

This goes AFTER the `ebrStatus === 'completed'` block (line 1077-1082) and BEFORE the `activeProcessStage` block (line 1084).

- [ ] **Step 2: Add renderPipelineSections function**

Add this function after `renderSections()` (around line 1100):

```javascript
function renderPipelineSections() {
    var container = document.getElementById('sections-container');
    container.innerHTML = '';
    var isReadonly = ebrStatus !== 'open';
    var rs = typeof roundState !== 'undefined' ? roundState : null;
    var entryGrupa = (ebrStatus === 'open' && userGrupa) ? userGrupa : null;

    // Determine which stage to show
    var activeSekcja = window._activePipelineStage || null;
    var activeReadonly = window._activePipelineReadonly || false;

    // If no stage selected, find the first active one
    if (!activeSekcja) {
        var stages = etapy.filter(function(e) {
            var sek = e.sekcja_lab || '';
            return sek !== 'dodatki' && sek.indexOf('_dodatki') === -1;
        });
        for (var i = 0; i < stages.length; i++) {
            var e = stages[i];
            var sekcja = e.sekcja_lab || '';
            var hasW = false;
            if (e.typ_cyklu === 'cykliczny' && sekcja === 'analiza') {
                hasW = rs && rs.last_analiza > 0;
            } else {
                hasW = wyniki[sekcja] && Object.keys(wyniki[sekcja]).length > 0;
            }
            if (!hasW) {
                activeSekcja = sekcja;
                break;
            }
        }
        if (!activeSekcja && stages.length > 0) {
            activeSekcja = stages[stages.length - 1].sekcja_lab;
        }
        window._activePipelineStage = activeSekcja;
    }

    // Find the etap for active sekcja
    var activeEtap = etapy.find(function(e) { return e.sekcja_lab === activeSekcja; });
    if (!activeEtap) return;

    // Cyclic stage (standaryzacja): use existing renderCyclicSections logic
    if (activeEtap.typ_cyklu === 'cykliczny' && activeSekcja === 'analiza') {
        if (activeReadonly) {
            // Show completed rounds read-only
            _renderCyclicReadonly(container, rs, entryGrupa);
        } else {
            renderCyclicSections();
        }
        return;
    }

    // Jednorazowy or non-main cyclic: render single section
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
}

function _renderCyclicReadonly(container, rs, entryGrupa) {
    // Show all completed cyclic rounds as readonly
    var completedRounds = [];
    Object.keys(wyniki).forEach(function(key) {
        var m = key.match(/^(analiza|dodatki)__(\d+)$/);
        if (m) completedRounds.push({base: m[1], runda: parseInt(m[2]), key: key});
    });
    completedRounds.sort(function(a, b) {
        if (a.runda !== b.runda) return a.runda - b.runda;
        return a.base === 'analiza' ? -1 : 1;
    });

    if (completedRounds.length === 0) {
        container.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-dim);font-size:13px;">Brak wyników.</div>';
        return;
    }

    completedRounds.forEach(function(item, idx) {
        var pola = getPola(item.key, entryGrupa);
        var sekWyniki = wyniki[item.key] || {};
        var hasSomeResults = Object.keys(sekWyniki).length > 0;
        var allInLimit = hasSomeResults && Object.values(sekWyniki).every(function(w) { return w.w_limicie === 1; });
        var title = getCyclicSectionTitle(item.base, item.runda);
        renderOneSection(container, {
            sekcja: item.key, title: title, index: idx + 1,
            pola: pola, sekWyniki: sekWyniki,
            hasSomeResults: hasSomeResults, allInLimit: allInLimit,
            isReadonly: true, isCurrent: false,
            prevOutOfLimit: [], saveBtnLabel: null, pastRound: true
        });
    });
}
```

- [ ] **Step 3: Add showPipelineStage global function**

Add at the end of the script block in `_fast_entry_content.html` (before the closing `</script>` tag):

```javascript
window.showPipelineStage = function(sekcjaLab, readonly) {
    window._activePipelineStage = sekcjaLab;
    window._activePipelineReadonly = !!readonly;
    renderSections();
    if (typeof renderSidebarEtapy === 'function') renderSidebarEtapy();
};
```

- [ ] **Step 4: Test manually**

Open a K7 batch:
1. Should see only the first active stage (Utlenienie) in main area
2. Click "Utlenienie" in flowchart → shows utlenienie section
3. Enter SO3 value, blur → auto-save works
4. Click "Standaryzacja" in flowchart → blocked (pending)
5. After utlenienie has results → becomes done (green), standaryzacja becomes active
6. Click done "Utlenienie" → shows read-only view

Open a Chelamid_DK batch (no cycle):
1. Should see only analiza_koncowa section
2. Flowchart shows single step

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: render only active pipeline stage, hide others"
```

---

## Task 3: Verify backward compatibility + edge cases

**Files:** No changes — verification only.

- [ ] **Step 1: Test non-pipeline product**

Open a product without pipeline modifications (if any exist with old parametry_etapy but no pipeline). Verify old flow works unchanged.

- [ ] **Step 2: Test zbiornik batch**

Open a zbiornik-type batch. Verify it renders normally (single analiza_koncowa).

- [ ] **Step 3: Test completed batch**

Open a completed batch. Verify completed view renders (sticker, read-only results).

- [ ] **Step 4: Test cyclic standaryzacja flow**

On a K7 batch:
1. Fill utlenienie params → done
2. Standaryzacja becomes active → shows cyclic form (analiza__1)
3. Fill analiza → shows decision/additives
4. Fill additives → next round (analiza__2)
5. Click back on utlenienie (done) → read-only view
6. Click standaryzacja (active) → back to editable form

- [ ] **Step 5: Run test suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 6: Commit any fixes**

```bash
git add -A
git commit -m "fix: flowchart + navigation edge case fixes"
```

---

## Summary

| Task | What | File |
|------|------|------|
| 1 | Pipeline flowchart in sidebar | `szarze_list.html` |
| 2 | Section show/hide per stage | `_fast_entry_content.html` |
| 3 | Backward compat + edge cases | Manual testing |
