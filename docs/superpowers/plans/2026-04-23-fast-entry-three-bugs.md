# Fast-entry — three regressions (SM→SA recompute · stage korekta · titracja calc race)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three unrelated bugs in the laborant fast-entry UI without introducing regressions in adjacent features. Each fix is scoped to a single root cause and isolated to its own commit so it can be reverted independently if a regression surfaces.

**Architecture:** Pure frontend changes — no schema, no Python routes, no new endpoints. Each bug is a narrow fix in one JS/template file.

**Tech Stack:** Vanilla JS (IIFEs, no bundler) · Jinja2 · sqlite3. No frontend test harness; where a Python route is exercised, add a pytest integration test.

---

## Root-cause summary (Phase 1 investigation done, evidence in repo)

### Bug 1 — SM (srednia) does not trigger SA recompute

- **Root cause:** `mbr/static/calculator.js:686-702` (`acceptCalc` — the „Zatwierdź" handler for both titracja and srednia calc-panels). Line 688 sets `input.value = avg.toFixed(...)` programmatically, then calls `validateField` + `doSaveField`. It **never dispatches an `input` event**.
- `setupComputedFields` (`mbr/templates/laborant/_fast_entry_content.html:4466-4483`) attaches `addEventListener('input', handler)` on each dependency field. Programmatic `.value = …` assignments do NOT fire that event. So SA's `recomputeField()` (which parses SA's formula `sa = sm - nacl - sa_bias` and updates the SA input) never runs.
- Why only srednia triggers it in user reports: titracja also goes through `acceptCalc` but its typical dependents don't include obliczeniowy params in the same section; SM is the prominent case where a downstream obliczeniowy (SA) recomputes from it.
- **Fix direction:** dispatch a single `input` event after setting the value in `acceptCalc`. Idempotent side-effects (validateField is explicitly called right after; autoSaveField would queue a debounced duplicate — harmless since same value); benefit: all computed-dependency listeners fire.

### Bug 2 — Standaryzacja korekta panel doesn't appear when utlenienie is filled out of order

- **Root cause chain (confirmed with grep + read):**
  1. `showPipelineStage(sekcjaLab, readonly)` at `_fast_entry_content.html:5932-5938` sets `_activePipelineStage` and calls `renderSections()`. It does NOT call `/api/pipeline/lab/ebr/<id>/etap/<etap_id>/start`.
  2. The sidebar click wired at `szarze_list.html:963` (`onclick="showPipelineStage('utlenienie', false)"`) is how the operator jumps to utlenienie before closing sulfonowanie.
  3. After switching, the user fills utlenienie pomiary. Save goes through `POST /laborant/ebr/<id>/save` → `save_wyniki` → `pipeline_dual_write(sekcja='utlenienie', …)` (`mbr/pipeline/adapter.py:357-360`).
  4. `pipeline_dual_write` looks for an active session for etap_id=5 via `list_sesje(...)` filtered to `status IN ('nierozpoczety', 'w_trakcie')`. Since nothing created a utlenienie session, the list is empty → `return None`.
  5. No gate evaluated → response carries no `gate` → frontend's save-completion handler doesn't call `renderGateBanner` → no correction panel.
- Secondary silent failure: `renderGateBanner` itself has a defensive `if (!banner) return;` at `_fast_entry_content.html:2859` — when the gate lookup returns an ID for a stage whose section isn't currently rendered, the gate banner div doesn't exist either. (This protects against downstream breakage but hides the root issue.)
- **Fix direction:** make `showPipelineStage` await `/etap/<pipeline_etap_id>/start` before re-rendering, **only when `readonly=false`** and the target stage is editable. The endpoint is idempotent — if a session is already `w_trakcie`/`nierozpoczety`, it returns the existing id (see `lab_start_sesja` at `lab_routes.py:150-167`). Readonly switches (viewing a closed batch / past round) must NOT start a session.

### Bug 3 — Titracja calculator sometimes renders without nawazka/titrant inputs (fixed by F5)

- **Multiple plausible root causes, ranked:**
  1. (**HIGH**) Race on `CALC_METHODS` global — `calculator.js:16-41` fires a fetch-and-populate IIFE at module load without storing the promise. If the operator clicks a titracja field before the fetch resolves AND the DOM-attribute fallback fails (`data-calc-method` attribute missing/parse fails), `openCalculator` at line 173-175 falls through to `CALC_METHODS[tag] || CALC_METHODS[kod]` → `undefined` → `return` (line 175) silently.
  2. (**MEDIUM**) Missing `data-calc-method` DOM attribute when the param lacks a `calc_method` dict on the server side (`adapter.py:_build_pole` skips it for params without method_id + formula). Rare in practice but possible.
  3. (**MEDIUM**) Stale `_calcState` pollution — after `openCalculator` returns early (no method), `_calcState` is left holding the previous calc's shape; the right-panel render may still show residual fields or blank-out.
- **Fix direction:** two defense-in-depth additions, both low-risk:
  - (a) Store the CALC_METHODS fetch promise at module level and `await` it inside `openCalculator` before the method lookup. Eliminates the race.
  - (b) When `openCalculator` early-returns due to no method, emit a clear operator-visible message ("Brak metody miareczkowej dla parametru X — uzupełnij w rejestrze") instead of silent `return`. Protects against data-quality misses (cause #2) and stale-state misrender (cause #3 becomes visible instead of silent).
- Not doing speculative fixes for stale state without evidence — cause #3 lives in the same early-return path and is incidentally improved by fix (b).

---

## File structure

| Action | File | Responsibility |
|---|---|---|
| Modify | `mbr/static/calculator.js` | Fix 1 (dispatch input event after acceptCalc) + Fix 3a (await CALC_METHODS promise) + Fix 3b (user-visible no-method error) |
| Modify | `mbr/templates/laborant/_fast_entry_content.html` | Fix 2 (`showPipelineStage` awaits /start for editable switches) |
| Modify | `tests/test_pipeline_lab.py` | Fix 2 regression test: `lab_start_sesja` remains idempotent for existing w_trakcie/nierozpoczety sessions |

No new files, no schema changes.

---

## Task 1 — Fix 1: dispatch `input` event in `acceptCalc` so obliczeniowy params recompute

### Step 1.1 — Write a manual-reproducer doc (no JS test harness; document expected browser flow)

- [ ] Skip. No test. Fix is a 1-line addition with idempotent side-effects, and JS has no test harness in this repo. Verification happens in Step 1.3 via browser smoke test.

### Step 1.2 — Add the dispatch

- [ ] In `mbr/static/calculator.js`, find `acceptCalc` around line 686. The block is:

```js
    if (input) {
        var prec = parseInt(input.dataset.precision || '4', 10);
        input.value = avg.toFixed(prec).replace('.', ',');
        input.classList.add('calc');
        if (typeof validateField === 'function') {
            validateField(input);
        }
        // Trigger auto-save (oninput or onblur depending on context)
        if (input.dataset.etap) {
            // Process stage field — trigger psAutoSave + psSave
            if (typeof psAutoSave === 'function') psAutoSave(input);
            if (typeof psSave === 'function') psSave(input);
        } else {
            // Standaryzacja/AK field — trigger doSaveField
            if (typeof doSaveField === 'function') doSaveField(input, input.dataset.sekcja, input.dataset.kod);
        }
    }
```

Add a single `dispatchEvent` right after the `validateField` call (before the auto-save branch), so any `setupComputedFields` listener registered on this input fires:

```js
    if (input) {
        var prec = parseInt(input.dataset.precision || '4', 10);
        input.value = avg.toFixed(prec).replace('.', ',');
        input.classList.add('calc');
        if (typeof validateField === 'function') {
            validateField(input);
        }
        // Notify dependency listeners (setupComputedFields) — programmatic
        // .value = ... does not fire 'input'. Obliczeniowy params like SA
        // whose formula references this field recompute via that event.
        input.dispatchEvent(new Event('input', { bubbles: true }));
        // Trigger auto-save (oninput or onblur depending on context)
        if (input.dataset.etap) {
            if (typeof psAutoSave === 'function') psAutoSave(input);
            if (typeof psSave === 'function') psSave(input);
        } else {
            if (typeof doSaveField === 'function') doSaveField(input, input.dataset.sekcja, input.dataset.kod);
        }
    }
```

### Step 1.3 — Syntax check

- [ ] Run:

```bash
node --check mbr/static/calculator.js
```

Expected: no output (success).

### Step 1.4 — Smoke-test instructions for the reviewer

- [ ] (Document only — no code change here. Add to the commit message body.) Browser smoke test:
  1. Open K7 batch in fast-entry. Reach standaryzacja / AK section where SM is present with a computed SA.
  2. Focus SM (it should be typ='srednia'), enter two sample values in the calc side-panel, click "Zatwierdź".
  3. SM field shows the mean.
  4. **SA field should update automatically to `sm - nacl - sa_bias`.** Before this fix, SA stays at old value until the operator manually edits another dependency field.

### Step 1.5 — Commit

- [ ] Run:

```bash
git add mbr/static/calculator.js
git commit -m "$(cat <<'EOF'
fix(calculator): dispatch input event after acceptCalc so obliczeniowy params recompute

acceptCalc sets the target field's value programmatically (line 688),
then calls validateField + doSaveField. setupComputedFields registers
'input' listeners on every dependency field so that obliczeniowy
params like SA (formula sa = sm - nacl - sa_bias) auto-recompute when
SM changes. Programmatic .value = ... assignments don't fire that
event, so SA stayed stale after the srednia calc accepted SM's mean.

One-line addition of input.dispatchEvent(new Event('input',
{bubbles: true})) right after validateField. Side effects:
- validateField already fired explicitly, idempotent — no-op
- autoSaveField's debounce queue re-enqueues same value — harmless
- setupComputedFields recompute listeners fire — the fix

Covers both srednia and titracja accept paths.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2 — Fix 2: auto-start pipeline session when switching to an editable stage

### Step 2.1 — Write a failing pytest that pins the current behavior of `lab_start_sesja` (idempotency contract)

- [ ] Open `tests/test_pipeline_lab.py`. Add a test at the end of the file:

```python
def test_lab_start_sesja_is_idempotent_when_session_already_open(client, db):
    """Calling /etap/<id>/start on a stage whose session is already in
    'w_trakcie' or 'nierozpoczety' must return the same sesja_id with 200.
    showPipelineStage() relies on this to safely pre-start sessions on every
    sidebar switch without spawning duplicate sessions."""
    # Setup: create a K7 batch, start sulfonowanie (etap_id=4)
    batch_id = _create_k7_batch(client, db)
    r1 = client.post(f"/api/pipeline/lab/ebr/{batch_id}/etap/4/start")
    assert r1.status_code in (200, 201)
    sid = r1.get_json()["sesja_id"]
    # Start again — must return same id, status 200
    r2 = client.post(f"/api/pipeline/lab/ebr/{batch_id}/etap/4/start")
    assert r2.status_code == 200
    assert r2.get_json()["sesja_id"] == sid
    # Save a pomiar to move status to w_trakcie
    db.execute(
        "UPDATE ebr_etap_sesja SET status='w_trakcie' WHERE id=?", (sid,)
    )
    db.commit()
    # Start yet again — still idempotent
    r3 = client.post(f"/api/pipeline/lab/ebr/{batch_id}/etap/4/start")
    assert r3.status_code == 200
    assert r3.get_json()["sesja_id"] == sid
```

**Before writing this**, grep the existing tests for a helper that creates a K7 batch (something like `_create_k7_batch` or `_setup_batch`) — reuse it. If nothing exists and setup is more than ~10 lines, report BLOCKED rather than copying 50 lines of setup.

### Step 2.2 — Run the test; confirm it PASSES (behavior already exists, test just pins it)

- [ ] Run:

```bash
pytest tests/test_pipeline_lab.py::test_lab_start_sesja_is_idempotent_when_session_already_open -v
```

Expected: PASS. If it fails, the existing idempotency guarantee is broken — STOP and escalate; Fix 2 can't rely on an assumption that doesn't hold.

### Step 2.3 — Modify `showPipelineStage`

- [ ] In `mbr/templates/laborant/_fast_entry_content.html`, replace lines 5932-5938:

```js
window.showPipelineStage = function(sekcjaLab, readonly) {
    window._activePipelineStage = sekcjaLab;
    window._activePipelineReadonly = !!readonly;
    renderSections();
    updateSpecPanel();
    if (typeof renderSidebarEtapy === 'function') renderSidebarEtapy();
};
```

with:

```js
window.showPipelineStage = async function(sekcjaLab, readonly) {
    window._activePipelineStage = sekcjaLab;
    window._activePipelineReadonly = !!readonly;
    // When switching to an editable stage, ensure its pipeline session
    // exists. Without this, pipeline_dual_write on the first pomiar save
    // finds no active session for the etap (dual_write returns None), no
    // gate is evaluated, and the correction panel never appears. The
    // /start endpoint is idempotent — returns the existing sesja_id when
    // a nierozpoczety/w_trakcie session is already present.
    if (!readonly) {
        var stage = (typeof etapy !== 'undefined' ? etapy : []).find(function(e) {
            return e.sekcja_lab === sekcjaLab && !!e.pipeline_etap_id;
        });
        if (stage) {
            try {
                await fetch('/api/pipeline/lab/ebr/' + ebrId + '/etap/' + stage.pipeline_etap_id + '/start', {
                    method: 'POST'
                });
            } catch (err) {
                // Non-fatal: render even if start failed; the downstream
                // save will retry via pipeline_dual_write's lookup (which
                // simply returns None on miss — no crash, just no gate).
                console.warn('[showPipelineStage] /start failed:', err);
            }
        }
    }
    renderSections();
    updateSpecPanel();
    if (typeof renderSidebarEtapy === 'function') renderSidebarEtapy();
};
```

**Notes for the executor:**
- Function becomes `async`; callers (sidebar `onclick="showPipelineStage(...)"`) don't await, but that's fine — the render runs after the fetch resolves, session exists before any user input can trigger a save.
- `readonly=true` path is untouched. Closed batches / past rounds do NOT get a new session.
- Analiza_koncowa (jednorazowy) also gets its session started via this path, matching the pipeline adapter's behavior for jednorazowy stages.
- No change to `renderSections` / `updateSpecPanel` / `renderSidebarEtapy` invocation order.

### Step 2.4 — Syntax check

- [ ] Can't `node --check` a Jinja template directly. Instead, extract the script body mentally / by eye and check the inline js around lines 5932-5950 for balanced braces. If unsure, render the page via Flask (dev server running) and check the browser Console for syntax errors.

### Step 2.5 — Smoke test (document in commit body)

- [ ] Browser test path:
  1. Start a fresh K7 batch. Fill sulfonowanie pomiary, DO NOT click „Zatwierdź etap".
  2. Click utlenienie in the sidebar. Observe Network tab: `POST /api/pipeline/lab/ebr/<id>/etap/5/start` → 201 (new session).
  3. Fill utlenienie pomiary (SO3, nadtlenki). Observe gate banner + „Korekta standaryzująca — woda + kwas" panel appears.
  4. Return to sulfonowanie (sidebar click). Network: `POST /etap/4/start` → 200 (existing session, idempotent).
  5. Switch to a COMPLETED batch, click stages in sidebar — NO /start requests fire (readonly path).

### Step 2.6 — Run full test suite to confirm no regression

- [ ] Run:

```bash
pytest tests/test_pipeline_lab.py tests/test_chzt.py tests/test_laborant.py -v
```

Expected: all pass.

### Step 2.7 — Commit

- [ ] Run:

```bash
git add mbr/templates/laborant/_fast_entry_content.html tests/test_pipeline_lab.py
git commit -m "$(cat <<'EOF'
fix(pipeline): auto-start session on editable stage switch

When the operator clicked utlenienie in the sidebar before closing
sulfonowanie, showPipelineStage only set _activePipelineStage and
re-rendered — it never called /api/pipeline/lab/ebr/<id>/etap/<id>/start.
The first pomiar save then went through pipeline_dual_write, which
looked for an active session for utlenienie's etap_id, found none,
and returned None (adapter.py:357-360). No gate → no gate banner →
no standaryzacja_v2 correction panel. The whole "Korekta standaryzująca"
step was missed.

showPipelineStage now awaits /start when the switch is editable
(readonly=false). The endpoint is idempotent — returns the existing
sesja_id when a nierozpoczety/w_trakcie session already exists
(test_lab_start_sesja_is_idempotent_when_session_already_open pins
this invariant). Readonly switches (completed batches, past rounds)
are unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3 — Fix 3: await CALC_METHODS before opening the calculator, surface no-method as a visible error

### Step 3.1 — Store the CALC_METHODS fetch as a promise at module scope

- [ ] In `mbr/static/calculator.js`, lines 12-42 currently are:

```js
// Guard: only load CALC_METHODS once (may be loaded from multiple script tags)
if (typeof CALC_METHODS === 'undefined') {
var CALC_METHODS = {};

(function loadCalcMethods() {
    fetch('/api/parametry/calc-methods')
        .then(function(resp) { return resp.json(); })
        .then(function(data) {
            for (var kod in data) {
                var m = data[kod];
                CALC_METHODS[kod] = m;
                CALC_METHODS['procent_' + kod] = m;
            }
        })
        .catch(function() {
            CALC_METHODS = { /* fallback … */ };
            for (var k in CALC_METHODS) {
                CALC_METHODS['procent_' + k] = CALC_METHODS[k];
            }
        });
})();
} // end CALC_METHODS guard
```

Rewrite the IIFE to expose its resolution:

```js
// Guard: only load CALC_METHODS once (may be loaded from multiple script tags)
if (typeof CALC_METHODS === 'undefined') {
var CALC_METHODS = {};

// Promise resolves when CALC_METHODS is ready (either populated from the
// API or filled with the hardcoded fallback on catch). openCalculator()
// awaits this so rapid-click after page load doesn't race with the fetch.
var CALC_METHODS_READY = fetch('/api/parametry/calc-methods')
    .then(function(resp) { return resp.json(); })
    .then(function(data) {
        for (var kod in data) {
            var m = data[kod];
            CALC_METHODS[kod] = m;
            CALC_METHODS['procent_' + kod] = m;
        }
    })
    .catch(function() {
        // Fallback: hardcoded methods if API fails (e.g. not logged in)
        CALC_METHODS = {
            nacl:  { name: '%NaCl', method: 'Argentometryczna Mohr', formula: '% = (V * 0.00585 * 100) / m', factor: 0.585 },
            aa:    { name: '%AA',   method: 'Alkacymetria',          formula: '% = (V * C * M) / (m * 10)',   factor: 3.015 },
            so3:   { name: '%SO3',  method: 'Jodometryczna',         formula: '% = (V * 0.004 * 100) / m',   factor: 0.4 },
            h2o2:  { name: '%H2O2', method: 'Manganometryczna',      formula: '% = (V * 0.0017 * 100) / m',  factor: 0.17 },
            lk:    { name: 'LK',    method: 'Alkacymetria KOH',      formula: 'LK = (V * C * 56.1) / m',     factor: 5.61 },
        };
        for (var k in CALC_METHODS) {
            CALC_METHODS['procent_' + k] = CALC_METHODS[k];
        }
    });
} // end CALC_METHODS guard
```

### Step 3.2 — Await `CALC_METHODS_READY` in `openCalculator` + surface no-method as visible error

- [ ] In the same file, locate `openCalculator` (around line 161). The early `return` at line 175 silently fails. Replace the first block of the function:

```js
async function openCalculator(tag, kod, sekcja, calcMethod) {
    // Determine method
    let method;
    if (calcMethod && calcMethod.factor) {
        method = {
            name: calcMethod.name || kod,
            method: calcMethod.name || '',
            formula: calcMethod.formula || '',
            factor: calcMethod.factor,
            suggested_mass: calcMethod.suggested_mass || null,
        };
    } else {
        method = CALC_METHODS[tag] || CALC_METHODS[kod];
    }
    if (!method) return;
    ...
```

with:

```js
async function openCalculator(tag, kod, sekcja, calcMethod) {
    // Determine method
    let method;
    if (calcMethod && calcMethod.factor) {
        method = {
            name: calcMethod.name || kod,
            method: calcMethod.name || '',
            formula: calcMethod.formula || '',
            factor: calcMethod.factor,
            suggested_mass: calcMethod.suggested_mass || null,
        };
    } else {
        // Wait for the one-time CALC_METHODS fetch to finish. Rapid click
        // right after page load used to race with this, silently falling
        // through to `undefined` and returning below without rendering.
        if (typeof CALC_METHODS_READY !== 'undefined') {
            try { await CALC_METHODS_READY; } catch (_) { /* already handled via fallback */ }
        }
        method = CALC_METHODS[tag] || CALC_METHODS[kod];
    }
    if (!method) {
        // No DOM-embedded calcMethod AND no CALC_METHODS entry for this
        // kod/tag. Data issue (param lacks metoda_id / metoda_formula /
        // metoda_factor), not a transient glitch — surface it instead of
        // leaving the right panel blank.
        var container = document.getElementById('calc-container');
        if (container) {
            container.innerHTML =
                '<div class="calc-header">' +
                    '<div class="calc-param">' + (kod || '').toUpperCase() + '</div>' +
                    '<div class="calc-method" style="color:var(--red);">Brak metody miareczkowej</div>' +
                '</div>' +
                '<div style="padding:12px 14px;font-size:11px;color:var(--text-dim);line-height:1.5;">' +
                    'Parametr nie ma przypisanej metody (brak <code>metoda_id</code> lub pustych pól <code>metoda_formula</code> / <code>metoda_factor</code>). Uzupełnij w rejestrze parametrów (Technolog → Parametry).' +
                '</div>';
            showRightPanel('calc');
        }
        return;
    }
    ...
```

### Step 3.3 — Syntax check

- [ ] Run:

```bash
node --check mbr/static/calculator.js
```

Expected: no output.

### Step 3.4 — Smoke-test instructions (document)

- [ ] Document in commit body:
  1. Reproduce the race by using throttled network (Chrome DevTools → Network → Slow 3G). Reload page. Immediately click a titracja field before `/api/parametry/calc-methods` resolves. With the fix, the calculator waits for the fetch and then renders properly. Without the fix, the panel is blank.
  2. Simulate no-method case: in devtools, open a titracja field and temporarily patch `CALC_METHODS[kod] = undefined` before clicking. Expect the red „Brak metody miareczkowej" message instead of a blank panel.

### Step 3.5 — Commit

- [ ] Run:

```bash
git add mbr/static/calculator.js
git commit -m "$(cat <<'EOF'
fix(calculator): await CALC_METHODS fetch + visible error when no method

Two defense-in-depth fixes for the intermittent "calculator shows no
nawazka/titrant-volume fields" bug that required a page refresh.

1. CALC_METHODS is populated asynchronously at module load. Fast
   operators who clicked a titracja field before the fetch resolved
   (and whose field lacked the DOM-embedded data-calc-method fallback)
   hit the early `return` in openCalculator — silent failure, blank
   right panel. Store the fetch as CALC_METHODS_READY promise and
   await it before the lookup.

2. The same early `return` also fires when a param genuinely has no
   calc method in the DB (missing metoda_id / formula / factor). Now
   renders a red "Brak metody miareczkowej" block with a pointer to
   the parametry registry instead of a blank panel, so data quality
   issues surface instead of hiding behind a UI glitch.

No test — no JS harness in this repo. Manual smoke test documented
in the PR body.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4 — Push

### Step 4.1

- [ ] Run:

```bash
git push origin main
```

---

## Regression guard checklist (review before merge)

Run this mental pass for each fix to ensure we didn't trade one bug for another:

### Fix 1 side effects
- [ ] Verified: `input` event dispatch fires `validateField` again (already called explicitly one line above — idempotent).
- [ ] Verified: `input` event dispatch re-queues `autoSaveField`'s debounced save. Harmless — same value, same debounce collapses to one save.
- [ ] Verified: `input` event dispatch fires `setupComputedFields` recompute listeners (desired behavior).
- [ ] **No unintended listener**: grep `mbr/templates/laborant/_fast_entry_content.html` for other `addEventListener('input', …)` on fields that could be affected. All of them should be benign (revalidate, save, recompute).

### Fix 2 side effects
- [ ] Verified: `/start` is only called when `readonly=false` — completed batches and past-round views don't spawn new sessions.
- [ ] Verified: `lab_start_sesja` is idempotent (test in 2.1-2.2 pins it).
- [ ] Verified: function becomes `async` but sidebar `onclick` handlers don't await — no breakage since DOM consumers (save handlers) run AFTER the async chain resolves because user input takes at least a frame to land.
- [ ] **Edge case**: rapid sidebar clicks during slow network could fire multiple /start concurrently. Harmless — idempotent endpoint resolves them all to the same sesja_id.
- [ ] **Failure mode**: if /start returns 500, we log `console.warn` and still render. Degrades to pre-fix behavior — the specific bug stays open but nothing else breaks.

### Fix 3 side effects
- [ ] Verified: `CALC_METHODS_READY` is defined unconditionally in the `if (typeof CALC_METHODS === 'undefined')` guard block. If the file is loaded twice (shouldn't happen — the guard protects), only the first load creates the promise.
- [ ] Verified: `openCalculator`'s early-return no-method path is now a visible error, not a silent abort. If a param legitimately has no calc_method, operator sees WHY the panel is empty.
- [ ] **Backward-compat**: `calcMethod && calcMethod.factor` path (DOM-embedded method) is untouched — no change for the happy path.
- [ ] **Stale state**: `_calcState` is still overwritten on next successful openCalculator call (line 177-187 of current file). Not improved by this fix but not regressed either.

---

## Self-review

**Spec coverage:**
- ✅ Bug 1 (SM → SA recompute): Task 1, 1.2 dispatch event, commit.
- ✅ Bug 2 (out-of-order stage): Task 2, test pins idempotency, showPipelineStage awaits /start.
- ✅ Bug 3 (calculator intermittent): Task 3, await CALC_METHODS_READY promise + visible error on miss.

**Placeholder scan:** No "TBD", no "add validation". Every step has concrete code and exact commands.

**Type consistency:**
- `CALC_METHODS_READY` used identically in loader IIFE + `openCalculator` await.
- `dispatchEvent(new Event('input', { bubbles: true }))` matches the idiom already used in the file at `_fast_entry_content.html:4294` and `:4526`.
- `stage.pipeline_etap_id` is the frontend's normal way to reference server-side etap IDs (used in commits `afa0598`, `9a04f2b`, `d1eda80` and many more).

**Regressions we specifically guarded against** (listed in checklist above):
- Double-save race from dispatched input event → confirmed idempotent.
- Auto-start /start on readonly view → guarded by `if (!readonly)`.
- Double /start concurrent → idempotent per test 2.1.
- Calc panel stale state → left untouched but now more visible when no method.
