# Parametry SSOT — PR 4 (Etap B.3) — Laborant modal on /api/bindings — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Migrate the in-batch-card parameter editor modal (`openParamEditor` in `mbr/templates/laborant/_fast_entry_content.html`) from legacy `/api/parametry/etapy/*` endpoints to the new `/api/bindings/*` endpoints. Change checkbox semantics so that toggling reflects **visibility in the current batch's typ** (flips `dla_<mytyp>`) rather than "binding exists at all". Fix the "after add/delete, card doesn't refresh" UX bug by calling `loadBatch(ebrId)` after every mutation.

**Architecture:** One template file, one modal. No backend changes (endpoints from PR 3 already exist). After PR 4, the laborant modal and the admin panel share the same API surface — `/api/bindings/*`. The legacy `/api/parametry/etapy/*` endpoints remain unused (removed in PR 7).

**Tech Stack:** Template Jinja + vanilla JS. Same as PR 2/3.

**Dependencies:** PR 3 (`feature/parametry-ssot-pr3`) must be merged — depends on `/api/bindings/*` endpoints.

---

## UX semantics change

**Before:** Checkbox means "Is this parameter bound for (produkt, kontekst)?"
- Check → POST binding
- Uncheck → DELETE binding

**After:** Checkbox means "Is this parameter visible in MY batch's typ?"
- `ebrTyp` is e.g. `'szarza'`. Corresponding flag column is `dla_szarzy`.
- Check → if binding exists, PUT `{dla_szarzy: 1}`; if no binding, POST with `dla_szarzy=1, dla_zbiornika=0, dla_platkowania=0`
- Uncheck → PUT `{dla_szarzy: 0}` (server auto-DELETEs row if all three flags reach 0)

This keeps other typy's visibility untouched — a szarża laborant hiding a param doesn't affect zbiornik views.

After every toggle or limit save, the card calls `loadBatch(ebrId)` so the main table reflects the change without a full page reload.

---

## File Structure

**Modify:**
- `mbr/templates/laborant/_fast_entry_content.html` — Modal JS section (functions `openParamEditor`, `renderParamEditor`, `peToggle`, `peSaveLimits`, `_peSetupDragDrop`). Roughly lines 5178-5445.

**Not touched:**
- Backend routes — no changes.
- Admin panel `/parametry` — PR 3 handled.
- Other laborant flows (save_entry, fast_entry_partial) — PR 2 handled.

---

## Task 1: Rewrite openParamEditor to use new endpoints

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Read current code**

Read lines 5176-5210 of `mbr/templates/laborant/_fast_entry_content.html`. Confirm:
- `_peBindingMap` is a module-level object (line ~5178)
- `_peAllParams` is a module-level array (line ~5179)
- `openParamEditor(kontekst)` at line ~5181 fetches bindings + available params

- [ ] **Step 2: Replace openParamEditor**

Replace the body of `openParamEditor(kontekst)` with:

```javascript
function openParamEditor(kontekst) {
  kontekst = kontekst || 'analiza_koncowa';
  window._peEditKontekst = kontekst;
  // Fetch bindings for THIS product + etap (all typy-agnostic rows)
  // + catalog of all active parameters.
  Promise.all([
    fetch('/api/bindings?produkt=' + encodeURIComponent(window._batchProdukt) +
          '&etap_kod=' + encodeURIComponent(kontekst)).then(function(r){return r.json();}),
    fetch('/api/bindings/catalog').then(function(r){return r.json();})
  ]).then(function(results) {
    var bindings = results[0];
    var available = results[1];

    // Build binding map keyed by parametr_id. Store flag values too so
    // renderParamEditor can decide checked state per typ.
    _peBindingMap = {};
    bindings.forEach(function(b) {
      _peBindingMap[b.parametr_id] = {
        id: b.id,
        min: b.min_limit,
        max: b.max_limit,
        precision: b.precision,
        kolejnosc: b.kolejnosc,
        nawazka_g: b.nawazka_g,
        dla_szarzy: b.dla_szarzy,
        dla_zbiornika: b.dla_zbiornika,
        dla_platkowania: b.dla_platkowania,
      };
    });

    _peAllParams = available;

    document.getElementById('pe-filter').value = '';
    renderParamEditor();
    document.getElementById('pe-modal-overlay').classList.add('show');
  });
}
```

Key changes:
- `/api/parametry/etapy/<produkt>/<kontekst>` → `/api/bindings?produkt=X&etap_kod=Y`
- `/api/parametry/available` → `/api/bindings/catalog`
- `_peBindingMap` entries now also carry the three `dla_*` flags

- [ ] **Step 3: Verify template still parses**

Run: `python3 -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('mbr/templates')).get_template('laborant/_fast_entry_content.html')"`
Expected: no output.

Run: `pytest -q`
Expected: 546 passed, 15 skipped (template-only change).

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: openParamEditor uses /api/bindings + /api/bindings/catalog"
```

---

## Task 2: Update renderParamEditor checkbox to reflect typ flag

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Read current renderParamEditor (lines ~5215-5282)**

The current logic marks a parameter as `checked` purely based on presence in `_peBindingMap`. We need to switch to: `checked` iff binding exists AND the typ flag is 1.

- [ ] **Step 2: Add helper at top of the modal section**

Just before `function openParamEditor` (line ~5181), add:

```javascript
// Resolve the current batch's typ to the matching flag column name.
// ebrTyp is declared at line ~1060.
function _peFlagKey() {
  var m = {szarza: 'dla_szarzy', zbiornik: 'dla_zbiornika', platkowanie: 'dla_platkowania'};
  return m[ebrTyp] || 'dla_szarzy';
}
```

- [ ] **Step 3: Update renderParamEditor to use the flag**

In the function body, replace the condition `if (_peBindingMap[p.id])` (line ~5226) logic and the `var checked = !!b` (line ~5252) with typ-aware checks.

Replace the SPLIT logic (bound/unbound) and the per-row checked flag:

```javascript
  var flagKey = _peFlagKey();

  // Split: "visible in my typ" (checked) vs "not visible" (unchecked).
  // An existing binding whose flag for my typ is 0 falls into unchecked.
  var bound = [];
  var unbound = [];
  _peAllParams.forEach(function(p) {
    var label = (p.label || '').toLowerCase();
    var kod = (p.kod || '').toLowerCase();
    if (filter && label.indexOf(filter) === -1 && kod.indexOf(filter) === -1) return;
    var b = _peBindingMap[p.id];
    var visible = b && b[flagKey] === 1;
    if (visible) bound.push(p);
    else unbound.push(p);
  });
  bound.sort(function(a, b) {
    return (_peBindingMap[a.id].kolejnosc || 0) - (_peBindingMap[b.id].kolejnosc || 0);
  });
```

Then in the inner forEach (where each row is built), replace:

```javascript
  var b = _peBindingMap[p.id];
  var checked = !!b;
```

With:

```javascript
  var b = _peBindingMap[p.id];
  var checked = b && b[flagKey] === 1;
  var bindingExists = !!b;  // has ANY typ flag — used for showing limits below
```

Then wherever the current code uses `b &&` guards to show limit values, keep them as `bindingExists &&` (or keep `b &&` — they're now equivalent because `b` exists when any flag is set). The only new semantic: checkbox reflects `checked`, not `bindingExists`.

**Note:** Limits (`min`, `max`, `precision`) should still display when binding exists even if the current typ's flag is 0 — laborant can see what the limits are without them being enforced for their typ. If this is undesirable, only show limits when `checked`; decide per UX. **Recommendation:** show limits for any `bindingExists`, edit only when `checked` (the flag is 1 for my typ). Keep current visual behavior of greyed-out ped-row-disabled for unchecked rows.

- [ ] **Step 4: Test locally (manual)**

Open a szarża batch card, click "edytuj parametry", verify the checkboxes reflect `dla_szarzy=1` (currently all should be checked because that's the default from migration).

- [ ] **Step 5: Run pytest + commit**

```bash
pytest -q
```
Expected: 546 passed.

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: renderParamEditor checkbox reflects dla_<mytyp> flag"
```

---

## Task 3: Rewrite peToggle — flip flag instead of CREATE/DELETE

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Replace peToggle (lines ~5359-5395)**

```javascript
function peToggle(paramId, checked) {
  var flagKey = _peFlagKey();
  var b = _peBindingMap[paramId];
  var promise;

  if (checked) {
    if (b) {
      // Binding exists — flip flag for my typ to 1.
      promise = fetch('/api/bindings/' + b.id, {
        method: 'PUT', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify((function() { var o = {}; o[flagKey] = 1; return o; })())
      }).then(function(r) {
        if (!r.ok) { alert('Błąd aktualizacji parametru'); return null; }
        return r.json();
      }).then(function(d) {
        if (!d) return;
        b[flagKey] = 1;
        return b;
      });
    } else {
      // No binding — create one, with only MY typ's flag set to 1.
      var nextOrder = Object.keys(_peBindingMap).length + 1;
      var body = {
        produkt: window._batchProdukt,
        etap_kod_hint: window._peEditKontekst || 'analiza_koncowa',
        parametr_id: paramId,
        kolejnosc: nextOrder,
        dla_szarzy: 0, dla_zbiornika: 0, dla_platkowania: 0
      };
      body[flagKey] = 1;
      // Resolve kontekst to etap_id via /api/pipeline/etapy
      promise = fetch('/api/pipeline/etapy')
        .then(function(r){return r.json();})
        .then(function(etapy) {
          var etap = etapy.find(function(e) { return e.kod === (window._peEditKontekst || 'analiza_koncowa'); });
          if (!etap) { alert('Nie znaleziono etapu'); return null; }
          body.etap_id = etap.id;
          delete body.etap_kod_hint;
          return fetch('/api/bindings', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)
          });
        })
        .then(function(r){ return r ? r.json() : null; })
        .then(function(d) {
          if (!d || !d.ok) { alert('Błąd dodawania parametru'); return null; }
          _peBindingMap[paramId] = {
            id: d.id, min: null, max: null, precision: null,
            kolejnosc: nextOrder, nawazka_g: null,
            dla_szarzy: body.dla_szarzy, dla_zbiornika: body.dla_zbiornika,
            dla_platkowania: body.dla_platkowania,
          };
          return _peBindingMap[paramId];
        });
    }
  } else {
    if (!b) return;  // nothing to do
    promise = fetch('/api/bindings/' + b.id, {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify((function() { var o = {}; o[flagKey] = 0; return o; })())
    }).then(function(r) {
      if (!r.ok) { alert('Błąd aktualizacji parametru'); return null; }
      return r.json();
    }).then(function(d) {
      if (!d) return;
      b[flagKey] = 0;
      // Server may have auto-deleted if all flags = 0
      if (d.auto_deleted) delete _peBindingMap[paramId];
      return b;
    });
  }

  promise.then(function() {
    renderParamEditor();
    // Refresh the batch card so the change is visible immediately
    if (typeof loadBatch === 'function') loadBatch(ebrId);
  });
}
```

This is the bulk of the change. Semantics:
- Check + existing binding → PUT flag=1
- Check + no binding → resolve etap_id, POST new binding with only MY flag=1
- Uncheck + existing binding → PUT flag=0 (may trigger server-side auto-delete)
- Uncheck + no binding → no-op

After every path: re-render modal AND reload the card (fixes the UX bug).

- [ ] **Step 2: Run pytest**

Run: `pytest -q`
Expected: 546 passed (template change only).

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: peToggle flips dla_<mytyp> flag + reloads batch card"
```

---

## Task 4: Rewrite peSaveLimits

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Replace peSaveLimits (lines ~5397-5442)**

```javascript
function peSaveLimits() {
  // Collect all changed limits + precision
  var updates = {};  // binding_id → {field: value}
  document.querySelectorAll('.ped-lim, .ped-prec').forEach(function(input) {
    var paramId = parseInt(input.dataset.paramId);
    var field = input.dataset.field;
    var b = _peBindingMap[paramId];
    if (!b) return;

    var val, apiField;
    if (field === 'precision') {
      val = input.value.trim() === '' ? null : parseInt(input.value);
      apiField = 'precision';
      if (b.precision === val) return;
    } else {
      val = input.value.trim().replace(',', '.');
      val = val === '' ? null : parseFloat(val);
      apiField = field === 'min' ? 'min_limit' : 'max_limit';
      if (b[field] === val) return;
    }

    if (!updates[b.id]) updates[b.id] = {};
    updates[b.id][apiField] = val;
  });

  var promises = Object.keys(updates).map(function(bindingId) {
    return fetch('/api/bindings/' + bindingId, {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(updates[bindingId])
    });
  });

  Promise.all(promises).then(function() {
    closeParamEditor();
    if (typeof loadBatch === 'function') loadBatch(ebrId);
  });
}
```

Key changes:
- `/api/parametry/etapy/<id>` → `/api/bindings/<id>`
- Removed `/api/parametry/rebuild-mbr` call — PR 2's render path reads from SSOT directly, no snapshot to rebuild.
- Always call `loadBatch` after save.

- [ ] **Step 2: Run pytest + commit**

```bash
pytest -q
```
Expected: 546 passed.

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: peSaveLimits uses /api/bindings (no rebuild-mbr needed)"
```

---

## Task 5: Rewrite drag-drop reorder

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Update _peSetupDragDrop — only the drop handler (lines ~5336-5352)**

Find the block inside `drop` event handler:

```javascript
      // Update kolejnosc in map and save
      var promises = [];
      boundIds.forEach(function(pid, i) {
        _peBindingMap[pid].kolejnosc = i + 1;
        promises.push(fetch('/api/parametry/etapy/' + _peBindingMap[pid].id, {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({kolejnosc: i + 1})
        }));
      });
      Promise.all(promises).then(function() {
        fetch('/api/parametry/rebuild-mbr', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({produkt: window._batchProdukt})
        });
      });
```

Replace with:

```javascript
      // Update kolejnosc in map and persist via PUT /api/bindings/<id>
      var promises = [];
      boundIds.forEach(function(pid, i) {
        _peBindingMap[pid].kolejnosc = i + 1;
        promises.push(fetch('/api/bindings/' + _peBindingMap[pid].id, {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({kolejnosc: i + 1})
        }));
      });
      Promise.all(promises).then(function() {
        if (typeof loadBatch === 'function') loadBatch(ebrId);
      });
```

- [ ] **Step 2: Run pytest + commit**

```bash
pytest -q
```
Expected: 546 passed.

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: modal drag-drop reorder uses /api/bindings (no rebuild-mbr)"
```

---

## Task 6: Manual smoke-test

**Files:**
- No code changes.

- [ ] **Step 1: Restart dev server**

Kill any running Flask + restart:

```bash
pkill -f "python -m mbr.app" || true
python -m mbr.app &
```

- [ ] **Step 2: Smoke checklist**

With the running app:
- Log in as laborant
- Open a Chelamid_DK batch
- Click "edytuj parametry" — modal opens, 7 params checked (all have `dla_szarzy=1` from migration)
- Uncheck one (e.g. `ph`) — modal re-renders, card reloads, `ph` gone from card
- Check it back — reappears
- Check a NEW param that wasn't bound — new binding created, appears
- Edit a limit inline + click save — change saved, card reloads
- Drag-drop reorder → persists, card reflects new order
- Close modal — no errors in console

If anything breaks, STOP and investigate. The most likely failure mode is the `/api/pipeline/etapy` fallback for etap_id resolution on new bindings — verify the endpoint returns `[{id, kod, ...}]`.

- [ ] **Step 3: No commit** — purely operational.

---

## Task 7: Memory + push + PR

**Files:**
- Memory file in `~/.claude/projects/.../memory/`.

- [ ] **Step 1: Update project memory**

Edit `project_parametry_ssot.md` — add PR 4 done section:

```markdown
**PR 4 (Etap B.3) — DONE YYYY-MM-DD:**
- Laborant modal openParamEditor uses /api/bindings/* + /api/bindings/catalog
- Checkbox semantics: reflects dla_<mytyp> flag (not "bound at all"); toggle flips flag for current batch typ
- Auto-DELETE via backend when all flags go to 0
- Added loadBatch(ebrId) after every toggle/save → fixes "card doesn't refresh" bug
- Drag-drop reorder uses PUT /api/bindings/<id>
- No backend changes; PR 3 endpoints sufficient
- Full suite: 546 passed, 15 skipped
- Branch: feature/parametry-ssot-pr4
```

- [ ] **Step 2: Push branch**

```bash
git push -u origin feature/parametry-ssot-pr4
```

- [ ] **Step 3: Open PR on GitHub**

Title: `refactor: parametry SSOT — PR 4 (Etap B.3) — laborant modal on /api/bindings`

Body:
```
## Summary
- Laborant in-card modal (openParamEditor) migrated from /api/parametry/etapy/* to /api/bindings/*
- Checkbox flips dla_<mytyp> flag (typ-aware visibility) instead of creating/deleting bindings wholesale
- Server auto-deletes when all three flags go to 0
- Fixes UX bug: card now refreshes after add/delete (loadBatch called)
- No backend changes; depends on PR 3 endpoints

## Test plan
- [x] pytest: 546 passed, 15 skipped
- [x] Modal opens, checkboxes reflect current typ flag
- [x] Toggle + card refresh works
- [x] Inline limit edit + card refresh works
- [x] Drag-drop reorder persists

Depends on PR 1, 2, 3 merged.
```

---

## Self-review (controller)

**Spec coverage:**
- Laborant modal on new endpoints ✓
- Typ-aware checkbox ✓
- Auto-delete on all-zero flags ✓ (server-side from PR 3)
- `loadBatch` after every mutation ✓

**Risk:**
- Modal may be used from multiple places with different kontekst values. Tasks 1+3 resolve kontekst to etap_id via /api/pipeline/etapy — verify this endpoint returns the etap catalog.
- `_peBindingMap` semantic change: entries now include three flag fields. Any OTHER JS code that reads from `_peBindingMap` must still work. Grep for `_peBindingMap` in the template to confirm no other consumers.

**Out of scope:**
- Cert generator — PR 5
- Drop old tables — PR 6
- Remove legacy endpoints + rebuild-mbr helper — PR 7
