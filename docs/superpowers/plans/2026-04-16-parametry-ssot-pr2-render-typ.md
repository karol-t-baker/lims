# Parametry SSOT — PR 2 (Etap B.1) — Render paths read typ flags — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `build_pipeline_context` filter `produkt_etap_limity` by `dla_<typ>` flag so that szarża, zbiornik, and płatkowanie render their own parameter sets. Completed-batch card renders the union (no filter). All read paths pass through this one function — no dual paths, no legacy snapshot fallbacks.

**Architecture:** One function (`build_pipeline_context(db, produkt, typ)`) is the render SSOT. Callers pass `typ` from `ebr.typ`. `fast_entry_partial` route builds TWO contexts — one for edit (filtered by batch typ) and one for the completed-batch view (no filter). Template reads both from the Flask context.

**Tech Stack:** Flask + Jinja, SQLite, stdlib only. No new deps. Pytest in-memory fixtures.

**Dependencies:** **PR 1 (`feature/parametry-ssot-pr1`) must be merged to `main` first**, because this PR relies on the flag columns being present in `produkt_etap_limity`. Branch PR 2 off `main` after merge.

---

## File Structure

**Modify:**
- `mbr/pipeline/adapter.py` — `build_pipeline_context(db, produkt, typ=None)` signature + filter
- `mbr/pipeline/adapter.py` — `_build_pole()` unchanged, just inherits new rows
- `mbr/laborant/routes.py:194-246` — `fast_entry_partial` passes `typ`, builds second context
- `mbr/laborant/routes.py:249-344` — `save_entry` passes `typ`
- `mbr/templates/laborant/_fast_entry_content.html` — completed-batch renderer reads new context var
- `tests/test_pipeline_adapter.py` — new tests for typ filtering

**Not touched in this PR:**
- Write endpoints (`/api/parametry/etapy/*`) — PR 3 replaces these with `/api/bindings/*`
- Admin panel `/parametry` UI — PR 3
- Laborant modal `openParamEditor` — PR 4
- Cert generator — PR 5
- `parametry_etapy`, `etap_parametry` tables — still populated, still safe

---

## Spec reference

- Full design: `docs/superpowers/specs/2026-04-16-parametry-ssot-design.md` section "Ścieżki odczytu"
- This PR implements the "Sekcja 2" contract end-to-end for the reader side.

---

## Task 1: Failing test — typ filter in adapter

**Files:**
- Modify: `tests/test_pipeline_adapter.py`

- [ ] **Step 1: Add fixture seed helper (if not already present — verify first)**

Read `tests/test_pipeline_adapter.py` and check whether there's a seed helper that creates a product with a pipeline and produkt_etap_limity rows. If not, add one near the top:

```python
def _seed_produkt_with_flags(db, produkt="TEST_P", etap_id=6):
    """Seed a product with pipeline + produkt_etap_limity rows. Returns parametr_ids."""
    db.execute("DELETE FROM parametry_analityczne")
    db.executemany(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, precision, aktywny) VALUES (?, ?, ?, ?, ?, 1)",
        [(1, "ph", "pH", "bezposredni", 2),
         (2, "dea", "DEA", "bezposredni", 2),
         (3, "barwa", "Barwa", "bezposredni", 0)],
    )
    db.execute("INSERT OR IGNORE INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
               "VALUES (?, ?, ?, ?)", (etap_id, "analiza_koncowa", "Analiza końcowa", "jednorazowy"))
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES (?, ?, 1)",
               (produkt, etap_id))
    # ph: visible in szarza + zbiornik
    db.execute("INSERT INTO produkt_etap_limity "
               "(produkt, etap_id, parametr_id, dla_szarzy, dla_zbiornika, dla_platkowania, kolejnosc) "
               "VALUES (?, ?, 1, 1, 1, 0, 1)", (produkt, etap_id))
    # dea: visible only in zbiornik
    db.execute("INSERT INTO produkt_etap_limity "
               "(produkt, etap_id, parametr_id, dla_szarzy, dla_zbiornika, dla_platkowania, kolejnosc) "
               "VALUES (?, ?, 2, 0, 1, 0, 2)", (produkt, etap_id))
    # barwa: visible only in szarza
    db.execute("INSERT INTO produkt_etap_limity "
               "(produkt, etap_id, parametr_id, dla_szarzy, dla_zbiornika, dla_platkowania, kolejnosc) "
               "VALUES (?, ?, 3, 1, 0, 0, 3)", (produkt, etap_id))
    db.commit()
```

- [ ] **Step 2: Add failing test**

Append to `tests/test_pipeline_adapter.py`:

```python
def test_build_pipeline_context_filters_by_typ_szarza(db):
    from mbr.pipeline.adapter import build_pipeline_context
    _seed_produkt_with_flags(db, "TEST_P")
    ctx = build_pipeline_context(db, "TEST_P", typ="szarza")
    kods = [p["kod"] for p in ctx["parametry_lab"]["analiza_koncowa"]["pola"]]
    assert kods == ["ph", "barwa"]  # dea filtered out (dla_szarzy=0)


def test_build_pipeline_context_filters_by_typ_zbiornik(db):
    from mbr.pipeline.adapter import build_pipeline_context
    _seed_produkt_with_flags(db, "TEST_P")
    ctx = build_pipeline_context(db, "TEST_P", typ="zbiornik")
    kods = [p["kod"] for p in ctx["parametry_lab"]["analiza_koncowa"]["pola"]]
    assert kods == ["ph", "dea"]  # barwa filtered out (dla_zbiornika=0)


def test_build_pipeline_context_no_typ_returns_union(db):
    from mbr.pipeline.adapter import build_pipeline_context
    _seed_produkt_with_flags(db, "TEST_P")
    ctx = build_pipeline_context(db, "TEST_P", typ=None)
    kods = [p["kod"] for p in ctx["parametry_lab"]["analiza_koncowa"]["pola"]]
    assert kods == ["ph", "dea", "barwa"]  # all three visible


def test_build_pipeline_context_platkowanie_respects_flag(db):
    from mbr.pipeline.adapter import build_pipeline_context
    _seed_produkt_with_flags(db, "TEST_P")
    ctx = build_pipeline_context(db, "TEST_P", typ="platkowanie")
    kods = [p["kod"] for p in ctx["parametry_lab"]["analiza_koncowa"]["pola"]]
    assert kods == []  # no params opted into platkowanie
```

- [ ] **Step 3: Run, expect fail**

Run: `pytest tests/test_pipeline_adapter.py::test_build_pipeline_context_filters_by_typ_szarza -v`
Expected: FAIL — current adapter doesn't filter by typ (returns all 3 params).

- [ ] **Step 4: Commit the test**

```bash
git add tests/test_pipeline_adapter.py
git commit -m "test: typ-flag filter for build_pipeline_context (failing)"
```

---

## Task 2: Add typ filter to build_pipeline_context

**Files:**
- Modify: `mbr/pipeline/adapter.py:173-270` (function `build_pipeline_context` + filter in `resolve_limity` usage)

- [ ] **Step 1: Update signature and filter**

In `mbr/pipeline/adapter.py`, find `def build_pipeline_context(db: sqlite3.Connection, produkt: str) -> dict | None:` and change it to accept `typ`:

```python
def build_pipeline_context(
    db: sqlite3.Connection, produkt: str, typ: str | None = None,
) -> dict | None:
    """Transform pipeline catalog data into the fast_entry template context.

    Args:
        produkt: product kod (matches ebr_batches.produkt / mbr_templates.produkt)
        typ: one of 'szarza' | 'zbiornik' | 'platkowanie' | None.
             None means no filter — union of all typy. Used for the
             completed-batch view which shows every measurement taken.
    """
    pipeline = get_produkt_pipeline(db, produkt)
    if not pipeline:
        return None

    etapy_json: list[dict] = []
    parametry_lab: dict[str, dict] = {}

    cykliczne = [s for s in pipeline if s["typ_cyklu"] == "cykliczny"]
    main_cykliczny_id = cykliczne[-1]["etap_id"] if cykliczne else None

    for step in pipeline:
        etap_id   = step["etap_id"]
        typ_cyklu = step["typ_cyklu"]
        nazwa     = step["nazwa"]
        nr        = step["kolejnosc"]

        etap = get_etap(db, etap_id)
        if etap is None:
            continue

        params = resolve_limity(db, produkt, etap_id)

        # Product-specific filter — only params with produkt_etap_limity row,
        # additionally filtered by typ flag when typ is given.
        if typ is None:
            filter_sql = (
                "SELECT parametr_id FROM produkt_etap_limity "
                "WHERE produkt = ? AND etap_id = ?"
            )
            filter_args = (produkt, etap_id)
        else:
            flag_col = {
                "szarza":      "dla_szarzy",
                "zbiornik":    "dla_zbiornika",
                "platkowanie": "dla_platkowania",
            }.get(typ)
            if flag_col is None:
                raise ValueError(f"unknown typ: {typ!r}")
            filter_sql = (
                f"SELECT parametr_id FROM produkt_etap_limity "
                f"WHERE produkt = ? AND etap_id = ? AND {flag_col} = 1"
            )
            filter_args = (produkt, etap_id)

        product_param_ids = {r[0] for r in db.execute(filter_sql, filter_args).fetchall()}
        params = [p for p in params if p["parametr_id"] in product_param_ids]

        if typ_cyklu == "cykliczny" and etap_id == main_cykliczny_id:
            sekcja_key = "analiza"
        elif typ_cyklu == "cykliczny":
            sekcja_key = step["kod"]
        else:
            sekcja_key = step["kod"]

        etap_entry: dict = {
            "nr":               nr,
            "nazwa":            nazwa,
            "kod":              step["kod"],
            "read_only":        False,
            "sekcja_lab":       sekcja_key,
            "pipeline_etap_id": etap_id,
            "typ_cyklu":        typ_cyklu,
        }
        etapy_json.append(etap_entry)

        pola = [_build_pole(p, db) for p in params]
        if sekcja_key not in parametry_lab:
            parametry_lab[sekcja_key] = {"label": nazwa, "pola": pola}
        else:
            parametry_lab[sekcja_key]["pola"].extend(pola)

    for et in etapy_json:
        eid = et.get("pipeline_etap_id")
        if eid:
            et["decyzje_pass"] = get_etap_decyzje(db, eid, "pass")
            et["decyzje_fail"] = get_etap_decyzje(db, eid, "fail")
        else:
            et["decyzje_pass"] = []
            et["decyzje_fail"] = []

    return {"etapy_json": etapy_json, "parametry_lab": parametry_lab}
```

Note: The critical change is replacing the unconditional `product_param_ids` query with one that adds the `AND dla_<typ> = 1` clause when `typ` is passed.

- [ ] **Step 2: Run tests, expect pass**

Run: `pytest tests/test_pipeline_adapter.py -v`
Expected: the 4 new tests pass. Existing tests in this file should also still pass (they call `build_pipeline_context(db, produkt)` without typ — treated as `typ=None`, union, same behavior as before).

Run: `pytest -q`
Expected: all green. If anything else fails, re-check the default behavior (no typ = no filter) hasn't regressed.

- [ ] **Step 3: Commit**

```bash
git add mbr/pipeline/adapter.py
git commit -m "feat: build_pipeline_context accepts typ filter for dla_<typ> flags"
```

---

## Task 3: fast_entry_partial passes typ + builds second context

**Files:**
- Modify: `mbr/laborant/routes.py:194-246`

- [ ] **Step 1: Update route**

Find the `fast_entry_partial(ebr_id)` route in `mbr/laborant/routes.py`. Replace the current pipeline_ctx block (lines ~203-217) with:

```python
        # Pipeline adapter — two contexts:
        #  ctx_typ  — filtered by this batch's typ, used for the edit card
        #  ctx_all  — no filter (union), used for the "completed" view which
        #             must show every parameter measured regardless of typ
        from mbr.pipeline.adapter import build_pipeline_context
        import json as _json
        batch_typ = ebr.get("typ", "szarza")
        pipeline_ctx_typ = build_pipeline_context(db, ebr["produkt"], typ=batch_typ)
        pipeline_ctx_all = build_pipeline_context(db, ebr["produkt"], typ=None)
        pipeline_sesja_map = {}
        if pipeline_ctx_typ:
            ebr = dict(ebr)  # mutable
            ebr["etapy_json"] = _json.dumps(pipeline_ctx_typ["etapy_json"])
            ebr["parametry_lab"] = _json.dumps(pipeline_ctx_typ["parametry_lab"])
            from mbr.pipeline.models import list_sesje
            for s in list_sesje(db, ebr_id):
                pipeline_sesja_map[s["etap_id"]] = {
                    "status": s["status"], "runda": s["runda"], "sesja_id": s["id"]
                }
```

Then in the `render_template(...)` call at the end of the function, add one new keyword argument:

```python
    return render_template("laborant/_fast_entry_content.html",
                           ebr=ebr, wyniki=wyniki, round_state=round_state,
                           etapy_status=etapy_status,
                           etapy_analizy=etapy_analizy,
                           etapy_korekty=etapy_korekty,
                           etapy_config=etapy_config,
                           zatwierdzil_short=zatwierdzil_short,
                           zatwierdzil_full=zatwierdzil_full,
                           pipeline_sesja_map=pipeline_sesja_map,
                           parametry_lab_all=pipeline_ctx_all["parametry_lab"] if pipeline_ctx_all else {})
```

**Remove** the `if ebr.get("typ") != "zbiornik":` guard that previously skipped the pipeline call. After this change, pipeline runs for every batch; the typ just chooses the filter.

- [ ] **Step 2: Verify route still responds**

With the local Flask dev server running, open an existing Chelamid_DK batch in the browser. The card should load without errors. Edit card should show the same parameters as before (all flags are 1/1/0 default so `typ=szarza` filter returns the same set).

If any 500 error appears, inspect the log and fix.

- [ ] **Step 3: Commit**

```bash
git add mbr/laborant/routes.py
git commit -m "feat: fast_entry_partial passes typ + builds separate context for completed view"
```

---

## Task 4: save_entry also passes typ

**Files:**
- Modify: `mbr/laborant/routes.py:249-344`

- [ ] **Step 1: Update save_entry**

Find the `save_entry(ebr_id)` route. Replace the current pipeline-context block (lines ~263-271) with:

```python
        # Pipeline adapter — use the typ-filtered context so save_wyniki sees
        # only the parameters relevant for this batch typ.
        from mbr.pipeline.adapter import build_pipeline_context
        import json as _json
        batch_typ = (ebr or {}).get("typ") or "szarza"
        pipeline_ctx = build_pipeline_context(db, ebr["produkt"], typ=batch_typ) if ebr else None
        if pipeline_ctx:
            ebr = dict(ebr)
            ebr["parametry_lab"] = _json.dumps(pipeline_ctx["parametry_lab"])
```

**Remove** the `if ebr and ebr.get("typ") != "zbiornik":` guard here too. Pipeline runs for every batch.

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_laborant.py -v`
Expected: pass. If existing tests seed batches without `typ` column, they default to `'szarza'` via the `or "szarza"` fallback.

- [ ] **Step 3: Commit**

```bash
git add mbr/laborant/routes.py
git commit -m "feat: save_entry passes typ through to build_pipeline_context"
```

---

## Task 5: Template uses parametry_lab_all for completed view

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html` (render-completed section, around lines 1660-1870)

- [ ] **Step 1: Inspect current rendering**

Read `mbr/templates/laborant/_fast_entry_content.html` from line 1660 to 1870 to locate where the completed view renders parameters. Look for the JS function that populates the "ukończona" card — e.g. `renderCompleted`, `getPola`, or a block that iterates over `ebr.parametry_lab`.

The goal is: when rendering the completed view, use `{{ parametry_lab_all | tojson }}` (new context var) instead of `{{ ebr.parametry_lab }}` (which is typ-filtered).

- [ ] **Step 2: Add parametry_lab_all JS var**

Near the top of the `<script>` block in `_fast_entry_content.html`, find where `ebr.parametry_lab` is exposed to JS. Add a parallel variable:

```html
<script>
  // Filtered by batch typ — used for the edit card
  var parametryLab = {{ ebr.parametry_lab | safe }};
  // Union of all typy — used only by the "completed" view
  var parametryLabAll = {{ parametry_lab_all | tojson | safe }};
  // ... rest unchanged
</script>
```

(If the existing var name is different, adapt accordingly — just introduce a second one with `parametry_lab_all`.)

- [ ] **Step 3: Route completed renderer to parametryLabAll**

In the completed renderer (e.g. `renderCompleted()` starting around line 1660), find where it reads from `parametryLab` (or the equivalent parsed from ebr.parametry_lab). Change that reference to `parametryLabAll`. The edit path keeps `parametryLab`.

Example (the exact line depends on the function structure — adapt):

```javascript
// Before:
var pola = getPola(sekcja);  // reads from parametryLab
// After (in renderCompleted only):
var pola = getPolaAll(sekcja);  // reads from parametryLabAll
```

Or simpler — add an optional arg to `getPola`:

```javascript
function getPola(sekcja, fromAll) {
    var src = fromAll ? parametryLabAll : parametryLab;
    // ...rest unchanged
}
```

Then in the completed renderer, call `getPola(sekcja, true)`.

Pick whichever pattern fits the existing code style. Minimize blast radius — touch only the completed view call site.

- [ ] **Step 4: Manual smoke-test**

With local dev server running, open a completed batch (e.g. any Chelamid_DK batch with status='completed'). Verify the "ukończona" card shows all parameters. Open an open batch, switch to edit — still shows typ-filtered params.

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: completed-batch view reads parametry_lab_all (union of all typy)"
```

---

## Task 6: Remove `typ != 'zbiornik'` guards

**Files:**
- Modify: `mbr/laborant/routes.py` (should already be removed in Tasks 3 + 4)

- [ ] **Step 1: Grep for remaining guards**

Run: `Grep for 'typ != "zbiornik"' or "typ.*zbiornik" across mbr/laborant/routes.py and mbr/laborant/models.py`. If any remain (should be zero after Tasks 3+4), document why and remove or leave with a comment explaining.

- [ ] **Step 2: Commit (if needed)**

If no remaining guards — skip this task (already done in Tasks 3+4). Otherwise commit the final removal with message:

```bash
git commit -m "cleanup: remove last remaining typ != 'zbiornik' guards"
```

---

## Task 7: Run full suite + smoke-test

**Files:**
- No code changes.

- [ ] **Step 1: Full pytest**

Run: `pytest -q`
Expected: 528 passed + 4 new adapter tests = 532 passed, 15 skipped.

If any test fails — stop. The most likely failures:
- Existing pipeline_adapter tests that assert a specific param count without typ filter. Default `typ=None` keeps old behavior.
- Laborant/batch tests that seed batches without `typ`. Default `'szarza'` fallback should cover.

- [ ] **Step 2: Manual smoke — szarza**

- Open existing Chelamid_DK batch → edit card shows 7 parameters (same as before)
- Enter value, click save → no 500
- Close, reopen → value persists

- [ ] **Step 3: Manual smoke — zbiornik**

Without creating a zbiornik in DB (there are none yet), this can't be fully tested. Note this as a pending test — will exercise in PR 4 when a zbiornik modal becomes real.

- [ ] **Step 4: Manual smoke — completed view**

Open a completed batch → verify "ukończona" card shows all measured parameters. Since all flags are 1/1/0 default, this returns the same set as the edit card for now — but the code path is different and is what PR 4+ will exercise.

---

## Task 8: Update memory + open PR

**Files:**
- No code changes in repo. Memory file in `~/.claude/projects/.../memory/`.

- [ ] **Step 1: Update project memory**

Update `project_parametry_ssot.md` to mark PR 2 as done and note the render-side state. One-line amendment under the PR 1 section, plus a new section:

```markdown
**PR 2 (Etap B.1) — DONE YYYY-MM-DD:**
- `build_pipeline_context(db, produkt, typ)` filters by dla_<typ>=1
- `fast_entry_partial` builds two contexts: typ-filtered for edit, union for completed
- `save_entry` passes typ through
- Legacy `typ != "zbiornik"` guards removed
- Template exposes `parametryLab` (edit) and `parametryLabAll` (completed) to JS
```

- [ ] **Step 2: Push branch + open PR**

```bash
git push -u origin feature/parametry-ssot-pr2
```

Then open PR via the GitHub URL printed after push. Suggested title:

> `refactor: parametry SSOT — PR 2 (Etap B.1) — render paths read typ flags`

Body template:
```
## Summary
- build_pipeline_context(db, produkt, typ) filters produkt_etap_limity by dla_<typ>
- fast_entry_partial + save_entry pass typ from ebr.typ
- Completed-batch view reads a second unfiltered context (union of all typy)
- Removed legacy "typ != 'zbiornik'" guards

## Test plan
- [x] pytest: 532 passed, 15 skipped
- [x] Chelamid_DK szarza card renders 7 params as before
- [x] Chelamid_DK completed view renders all measured params
- [ ] Zbiornik edit flow: pending PR 4 (no zbiornik UI yet to exercise)

Depends on PR 1 (feature/parametry-ssot-pr1) being merged first.
```

---

## Self-review notes (for controller)

**Spec coverage:**
- Render paths: ✓ (Tasks 1-5)
- `typ != zbiornik` guards removed: ✓ (Tasks 3-6)
- Completed view reads union: ✓ (Task 5)
- `mbr_templates.parametry_lab` snapshot not read: ✓ (confirmed: it was only read in the `typ == zbiornik` branch, which is now gone)

**Out of scope (confirmed):**
- Write endpoints — PR 3
- Admin panel UI — PR 3
- Laborant modal updates — PR 4
- Cert generator — PR 5

**Risks:**
- Template JS pattern varies; Task 5 may need adaptation based on actual function structure. If `renderCompleted` uses a different data source than expected, the implementer should surface as DONE_WITH_CONCERNS and the controller picks pattern.
- Any existing test that hardcodes "simple products use mbr_templates.parametry_lab snapshot" will break. This is a signal we caught a stale code path, not a regression — fix by updating the test to use `build_pipeline_context`.

**After PR 2 merges:**
- Branch PR 3 off `main` with same pattern
- PR 3 focus: new `/api/bindings/*` endpoints + admin panel columns for Sz/Zb/Pl
