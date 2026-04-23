# Cert Issuance for Pakowanie Bezpośrednie + Płatkowanie + Show-all-Tanks Toggle

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend the cert issuance path beyond zbiorniki — laborant_coa can now also issue świadectwa for szarże packaged directly (`pakowanie_bezposrednie IS NOT NULL`) and for `typ='platkowanie'`. Additionally, loosen the tank-selection UI so atypical szarże can be poured into a zbiornik belonging to a different product (with an audit trail of cross-product assignments).

**Architecture:**
- Cert generator keeps consuming `wyniki_flat: dict[kod -> row]`. A new data-source helper produces that dict from `ebr_pomiar` (pipeline measurements — latest value per parametr) for szarże that never produced `ebr_wyniki` rows. Routes pick the data source based on batch typ + flags.
- `certs/routes.py` lifts the `typ in ('zbiornik','platkowanie')` gate to also allow `szarza` with `pakowanie_bezposrednie` set.
- Tank selection UI (`_modal_nowa_szarza.html` + `openPumpModal` in `_fast_entry_content.html`) gains a "Pokaż wszystkie zbiorniki" toggle that reveals tanks of any product (płatkowanie has no tanks — nothing to toggle there).
- Cross-product assignment is audit-logged at `complete_ebr` time so QA can trace unusual pours.

**Tech Stack:** Flask + SQLite + Jinja + vanilla JS + pytest.

---

## File Structure

**Create:**
- `tests/test_cert_pakowanie.py` — integration tests: cert generation for `pakowanie_bezposrednie` + `platkowanie`; cross-product audit emission.

**Modify:**
- `mbr/certs/models.py` — new helper `get_pipeline_wyniki_flat(db, ebr_id) -> dict[str, dict]`.
- `mbr/certs/routes.py` — accept new type mix, switch data source per batch type.
- `mbr/templates/laborant/_fast_entry_content.html` — cert panel visible for pakowanie + platkowanie; show-all toggle in `openPumpModal`.
- `mbr/templates/laborant/_modal_nowa_szarza.html` — show-all toggle in `_renderZbPills()`.
- `mbr/laborant/models.py::complete_ebr` — cross-product audit event.

No schema changes.

---

## Task 1: Helper — `get_pipeline_wyniki_flat`

**Why:** Cert generator currently needs `wyniki_flat = {kod: row}` sourced from `ebr_wyniki`. Pipeline-era szarże (K7) write to `ebr_pomiar`, not `ebr_wyniki`, so a direct-packaged K7 batch has empty `ebr_wyniki`. This helper produces the same shape from `ebr_pomiar`: latest value per `parametr_id`, keyed by `kod`.

**Files:**
- Create: function in `mbr/certs/models.py`
- Test:  `tests/test_cert_pakowanie.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_cert_pakowanie.py
import sqlite3
import pytest

from mbr.models import init_mbr_tables
from mbr.certs.models import get_pipeline_wyniki_flat


@pytest.fixture
def db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_mbr_tables(c)
    # Seed: one ebr, one stage, one sesja, 2 parametry with 2 pomiary (second overwrites)
    c.execute(
        "INSERT INTO mbr_templates (mbr_id, produkt, wersja, status, etapy_json, dt_utworzenia) "
        "VALUES (1, 'Chegina_K7', 1, 'active', '[]', '2026-04-23T00:00:00')"
    )
    c.execute(
        "INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, status, dt_start, pakowanie_bezposrednie) "
        "VALUES (100, 1, 'K7-PAK-1', 'K7/PAK-1', 'open', '2026-04-23T09:00:00', 'IBC')"
    )
    c.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
              "VALUES (20, 'standaryzacja', 'Standaryzacja', 'cykliczny')")
    c.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, dt_start) "
              "VALUES (2000, 100, 20, 1, 'zamkniety', '2026-04-23T10:00:00')")
    c.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (501, 'ph_10proc', 'pH 10%', 'bezposredni')")
    c.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (502, 'so3', 'SO3', 'bezposredni')")
    # First pomiar then a second (same parametr) — helper must return the later one
    c.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, wpisal, dt_wpisu) "
              "VALUES (2000, 501, 6.3, 'lab1', '2026-04-23T10:05:00')")
    c.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, wpisal, dt_wpisu) "
              "VALUES (2000, 501, 6.5, 'lab1', '2026-04-23T10:15:00')")
    c.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, wpisal, dt_wpisu) "
              "VALUES (2000, 502, 0.02, 'lab1', '2026-04-23T10:20:00')")
    c.commit()
    yield c
    c.close()


def test_returns_latest_per_kod(db):
    wf = get_pipeline_wyniki_flat(db, ebr_id=100)
    assert set(wf.keys()) == {"ph_10proc", "so3"}
    # Latest write per parametr wins
    assert wf["ph_10proc"]["wartosc"] == 6.5
    assert wf["so3"]["wartosc"] == 0.02


def test_empty_for_missing_ebr(db):
    assert get_pipeline_wyniki_flat(db, ebr_id=99999) == {}


def test_ignores_null_wartosc(db):
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (503, 'barwa_hz', 'Barwa', 'bezposredni')")
    db.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, wpisal, dt_wpisu) "
               "VALUES (2000, 503, NULL, 'lab1', '2026-04-23T10:25:00')")
    db.commit()
    wf = get_pipeline_wyniki_flat(db, ebr_id=100)
    assert "barwa_hz" not in wf
```

- [ ] **Step 2: Run → verify fail** (ImportError)

`pytest tests/test_cert_pakowanie.py -v`

- [ ] **Step 3: Implement helper in `mbr/certs/models.py`**

```python
def get_pipeline_wyniki_flat(db, ebr_id: int) -> dict:
    """Return {kod: row} from ebr_pomiar — latest non-null per parametr.

    Provides the same shape as `ebr_wyniki` flattened dict that cert generator
    consumes, so certs for pipeline-era szarże (which skip ebr_wyniki) work
    without a separate code path downstream.
    """
    rows = db.execute(
        """SELECT pa.kod,
                  p.wartosc,
                  p.wpisal,
                  p.dt_wpisu,
                  p.w_limicie,
                  p.min_limit,
                  p.max_limit
           FROM ebr_pomiar p
           JOIN ebr_etap_sesja s ON s.id = p.sesja_id
           JOIN parametry_analityczne pa ON pa.id = p.parametr_id
           WHERE s.ebr_id = ? AND p.wartosc IS NOT NULL
           ORDER BY p.dt_wpisu DESC, p.id DESC""",
        (ebr_id,),
    ).fetchall()
    flat: dict = {}
    for r in rows:
        kod = r["kod"]
        if kod not in flat:  # first row per kod = latest (ORDER BY DESC)
            flat[kod] = dict(r)
    return flat
```

- [ ] **Step 4: Run → 3 tests PASS**

`pytest tests/test_cert_pakowanie.py -v`

- [ ] **Step 5: Commit**

```bash
git add mbr/certs/models.py tests/test_cert_pakowanie.py
git commit -m "feat(certs): get_pipeline_wyniki_flat — ebr_pomiar-based cert data source"
```

---

## Task 2: Unblock cert generation for `pakowanie_bezposrednie`

**Why:** `mbr/certs/routes.py:62` currently returns an error for any `typ` other than `zbiornik`/`platkowanie`. We lift that check for szarże with `pakowanie_bezposrednie IS NOT NULL` and route them through the new data-source helper.

**Files:**
- Modify: `mbr/certs/routes.py` (the POST /generate handler)
- Modify: `tests/test_cert_pakowanie.py` (integration test via Flask client)

- [ ] **Step 1: Read current block**

Read `mbr/certs/routes.py` around lines 47–80 to see the handler + the `typ in (...)` check + the `get_ebr_wyniki` call.

- [ ] **Step 2: Append failing integration test**

Use the existing fixture pattern from `tests/test_lab_routes_reedit.py` (monkeypatched `get_db` + pre-seeded app). Seed a Chegina_K7 batch with `pakowanie_bezposrednie='IBC'` + closed standaryzacja sesja + a few pomiary that match the parametry the template expects.

```python
def test_cert_generate_accepts_pakowanie_bezposrednie(client, db):
    # Fixture has ebr 100 with pakowanie_bezposrednie='IBC' already seeded in conftest.
    # Here we only assert the endpoint no longer blocks on typ.
    resp = client.post("/api/cert/generate",
                       json={"ebr_id": 100, "variant_id": "STANDARD"})
    # 200 = cert generated OR 400 with a different error (e.g. missing variant config).
    # The only thing we're asserting is: the gate "Świadectwa tylko dla zbiorników i płatkowania" is gone.
    body = resp.get_json() or {}
    assert "tylko dla zbiorników" not in (body.get("error") or "")
```

- [ ] **Step 3: Run → verify fail** (current response rejects with the Polish error)

- [ ] **Step 4: Modify the handler**

Find the gate (around `routes.py:62`) — currently shaped like:

```python
if ebr["typ"] not in ("zbiornik", "platkowanie"):
    return jsonify({"error": "Świadectwa tylko dla zbiorników i płatkowania"}), 400
```

Replace with a shape-aware check:

```python
is_pakowanie = ebr["typ"] == "szarza" and (ebr["pakowanie_bezposrednie"] or "").strip()
if ebr["typ"] not in ("zbiornik", "platkowanie") and not is_pakowanie:
    return jsonify({"error": "Świadectwa tylko dla zbiorników, płatkowania i pakowania bezpośredniego"}), 400
```

Then, right before the existing `get_ebr_wyniki(db, ebr_id)` / `wyniki_flat = ...` block, branch the data source:

```python
from mbr.certs.models import get_pipeline_wyniki_flat

if is_pakowanie:
    wyniki_flat = get_pipeline_wyniki_flat(db, ebr_id)
else:
    wyniki_rows = get_ebr_wyniki(db, ebr_id)
    wyniki_flat = {r["kod_parametru"]: dict(r) for r in wyniki_rows}
```

Keep the downstream `generate_certificate_pdf(...)` call unchanged.

**SELECT shape note:** `ebr["pakowanie_bezposrednie"]` must be in the SELECT that fetches the batch row — grep the current SELECT and add the column if missing.

- [ ] **Step 5: Run all tests**

`pytest tests/test_cert_pakowanie.py tests/ -q`

- [ ] **Step 6: Commit**

```bash
git add mbr/certs/routes.py tests/test_cert_pakowanie.py
git commit -m "feat(certs): accept pakowanie_bezposrednie szarża in POST /generate"
```

---

## Task 3: Cert panel UI for `pakowanie_bezposrednie`

**Why:** Today the cert panel in `_fast_entry_content.html` only renders for `typ='zbiornik'`. Extend the render gate so a szarża with `pakowanie_bezposrednie IS NOT NULL` shows the same cert panel (template picker + "Generuj cert" button + issued-certs list).

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html` (cert panel block around line 2000–2110 per recon)

- [ ] **Step 1: Locate current cert panel render condition**

Grep for `typ === 'zbiornik'` or `ebr.typ == 'zbiornik'` inside `_fast_entry_content.html`. Read ±20 lines to understand the rendering block + variables in scope (likely `ebrTyp`, `ebrPakowanie`, etc.).

- [ ] **Step 2: Relax the condition**

Change the gate from
```javascript
if (ebrTyp === 'zbiornik') { ... render cert panel ... }
```
to
```javascript
var canIssueCert = (ebrTyp === 'zbiornik')
                 || (ebrTyp === 'platkowanie')
                 || (ebrTyp === 'szarza' && ebrPakowanie && ebrPakowanie.trim() !== '');
if (canIssueCert) { ... render cert panel ... }
```

Make sure `ebrPakowanie` variable exists (matches `ebr.pakowanie_bezposrednie`); if not, add it to the Jinja context export near the top of the template (search for where `ebrTyp` is defined, and mirror). You may need to extend the `get_ebr` return or the Jinja render call.

- [ ] **Step 3: Manual smoke**

```bash
MBR_SECRET_KEY=smoketest-key-32chars-padding-xxx python -m mbr.app &
```

Create a test szarża with `pakowanie_bezposrednie='IBC'`, open its detail view. Expected: cert template picker visible, "Generuj świadectwo" button enabled.

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat(laborant): cert panel visible for pakowanie_bezposrednie"
```

---

## Task 4: Verify + ensure cert panel for `typ='platkowanie'`

**Why:** `mbr/certs/routes.py:62` ALREADY allows `platkowanie` backend-side, but the UI block in `_fast_entry_content.html` may hide it. The condition from Task 3 (`ebrTyp === 'platkowanie'`) covers it — this task is verification + a minimal UI tweak if płatkowanie's batch detail page uses a different template than `_fast_entry_content.html`.

**Files:**
- Modify (maybe): whichever template renders the platkowanie detail view — grep to confirm.

- [ ] **Step 1: Verify what template renders platkowanie batches**

`grep -rn "typ.*platkowanie\|platkowanie_substraty" mbr/templates/ mbr/laborant/routes.py | head` — find the detail route for platkowanie.

If platkowanie shares `_fast_entry_content.html`, Task 3's change already covers it — skip to Step 3.

If platkowanie uses a different template (likely a `szarza_detail_platkowanie.html` or similar), mirror Task 3's cert panel block there.

- [ ] **Step 2: Add cert panel if missing**

(Skip if already present from Task 3 propagation.)

- [ ] **Step 3: Manual smoke**

Open an existing platkowanie batch (SQL: `SELECT ebr_id FROM ebr_batches WHERE typ='platkowanie' LIMIT 1`). Expected: cert panel visible, generation works.

- [ ] **Step 4: Commit**

If changes were made:
```bash
git add <files>
git commit -m "feat(laborant): cert panel visible for typ=platkowanie"
```

---

## Task 5: "Pokaż wszystkie zbiorniki" toggle in create-batch modal

**Files:**
- Modify: `mbr/templates/laborant/_modal_nowa_szarza.html` (`_renderZbPills()` around lines 296–330)

**Current behavior:** fetches `/api/zbiorniki` and filters client-side to `z.kod_produktu === batch_kod`; only matched pills are rendered.

**New behavior:** keep matched pills as the default view. Add a button below them: "+ Pokaż wszystkie (X)" where X = count of non-matching active tanks. Clicking renders the rest with a small product badge per pill (e.g., `[K40GL]`). Button disappears after expand.

- [ ] **Step 1: Read current `_renderZbPills()` block**

- [ ] **Step 2: Refactor**

Replace the splitting-and-rendering-only-matched logic with:

```javascript
function _renderZbPills() {
    var batch_kod = /* existing */;
    fetch('/api/zbiorniki').then(r => r.json()).then(function(tanks) {
        var matched = tanks.filter(function(z) { return z.aktywny && z.kod_produktu === batch_kod; });
        var others  = tanks.filter(function(z) { return z.aktywny && z.kod_produktu !== batch_kod; });
        var host = document.getElementById('zb-pick-szarza');
        host.innerHTML = matched.map(_tankPill).join('');

        if (others.length === 0) return;
        var expandBtn = document.createElement('button');
        expandBtn.type = 'button';
        expandBtn.className = 'pm-tank-expand';
        expandBtn.textContent = '+ Pokaż wszystkie (' + others.length + ')';
        expandBtn.onclick = function() {
            expandBtn.remove();
            host.insertAdjacentHTML('beforeend', others.map(function(z) {
                return _tankPill(z, /*crossProduct=*/true);
            }).join(''));
        };
        host.appendChild(expandBtn);
    });
}

function _tankPill(z, crossProduct) {
    var badge = crossProduct
        ? ' <span class="pm-tank-xp">[' + (z.kod_produktu || z.produkt || '?') + ']</span>'
        : '';
    return '<button type="button" class="pm-tank-pill' + (crossProduct ? ' pm-tank-xp-pill' : '')
         + '" data-id="' + z.id + '" onclick="selectZbPill(this)">'
         + (z.nr_zbiornika) + badge + '</button>';
}
```

Add CSS for `.pm-tank-expand` (text-link button) and `.pm-tank-xp` (small grey badge) + `.pm-tank-xp-pill` (dashed border to distinguish).

- [ ] **Step 3: Manual smoke**

Create a new K7 szarża — expected: K7 tanks shown, button "+ Pokaż wszystkie (N)" below. Click → remaining tanks appear with `[K40GL]` badge. Pick one → form submit goes through.

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/_modal_nowa_szarza.html
git commit -m "feat(laborant): show-all-tanks toggle in create-batch modal"
```

---

## Task 6: Same toggle in mid-batch `openPumpModal`

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html` (`openPumpModal` around line 3659–3695)

- [ ] **Step 1: Read existing pump modal**

- [ ] **Step 2: Mirror Task 5 logic**

Extract the same pill-rendering + expand-button pattern. Ideally factor `_tankPill` into a shared helper in `lab_common.js` so both modals use it — but only if trivial; otherwise duplicate with a comment pointing at the create-modal source of truth.

- [ ] **Step 3: Manual smoke**

Open an existing batch, hit "Zakończ → przepompuj". Same UX as create modal.

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html mbr/static/lab_common.js  # if shared
git commit -m "feat(laborant): show-all-tanks toggle in pump (complete) modal"
```

---

## Task 7: Audit cross-product tank assignment

**Why:** If laborant pours a K7 szarża into a K40GL tank, QA must be able to trace it. Add an audit event at `complete_ebr` time.

**Files:**
- Modify: `mbr/laborant/models.py::complete_ebr` (around line 892)
- Modify: `tests/test_cert_pakowanie.py` (append test)

- [ ] **Step 1: Failing test**

```python
def test_complete_ebr_logs_cross_product_assignment(client, db):
    # Seed: ebr 200 for Chegina_K7, + tank z1 assigned to Chegina_K40GL
    db.execute(
        "INSERT INTO mbr_templates (mbr_id, produkt, wersja, status, etapy_json, dt_utworzenia) "
        "VALUES (2, 'Chegina_K7', 1, 'active', '[]', '2026-04-23T00:00:00')"
    )
    db.execute(
        "INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, typ, status, dt_start) "
        "VALUES (200, 2, 'XP-1', 'K7/XP-1', 'szarza', 'open', '2026-04-23T09:00:00')"
    )
    db.execute(
        "INSERT INTO zbiorniki (id, nr_zbiornika, produkt, kod_produktu, aktywny) "
        "VALUES (50, 'Z50', 'Chegina_K40GL', 'K40GL', 1)"
    )
    db.commit()

    resp = client.post("/laborant/ebr/200/complete",
                       json={"zbiorniki": [{"zbiornik_id": 50, "kg": 1000}]})
    assert resp.status_code in (200, 302)  # backend may redirect or return JSON

    # Audit row with cross_product=1 should exist
    row = db.execute(
        "SELECT payload_json FROM audit_log "
        "WHERE entity_id=200 AND event_type LIKE 'ebr.przepompowanie.%' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    import json as _j
    assert _j.loads(row["payload_json"]).get("cross_product") == 1
```

- [ ] **Step 2: Run → verify fail**

- [ ] **Step 3: Implement**

In `complete_ebr` (`mbr/laborant/models.py:892`), after the zbiorniki rows are saved, detect cross-product and log:

```python
# Detect cross-product assignments for audit visibility.
batch_produkt = db.execute(
    "SELECT m.produkt FROM mbr_templates m JOIN ebr_batches b ON b.mbr_id=m.mbr_id WHERE b.ebr_id=?",
    (ebr_id,),
).fetchone()
if zbiorniki and batch_produkt:
    from mbr.shared import audit as _audit
    cross = []
    for z in zbiorniki:
        zb = db.execute(
            "SELECT nr_zbiornika, produkt FROM zbiorniki WHERE id=?",
            (z.get("zbiornik_id"),),
        ).fetchone()
        if zb and zb["produkt"] and zb["produkt"] != batch_produkt["produkt"]:
            cross.append({"zbiornik_id": z.get("zbiornik_id"),
                          "nr_zbiornika": zb["nr_zbiornika"],
                          "zbiornik_produkt": zb["produkt"]})
    if cross:
        _audit.log_event(
            _audit.EVENT_EBR_PRZEPOMPOWANIE_ADDED,
            entity_type="ebr",
            entity_id=ebr_id,
            payload={"cross_product": 1,
                     "batch_produkt": batch_produkt["produkt"],
                     "cross": cross},
            db=db,
        )
```

Use the existing `EVENT_EBR_PRZEPOMPOWANIE_ADDED` constant (see `mbr/shared/audit.py:62`) rather than inventing a new one. The `cross_product: 1` flag is what tests and future filters key on.

- [ ] **Step 4: Run all tests**

`pytest tests/test_cert_pakowanie.py tests/ -q`

- [ ] **Step 5: Commit**

```bash
git add mbr/laborant/models.py tests/test_cert_pakowanie.py
git commit -m "feat(audit): log cross_product=1 when szarża pours into mismatched tank"
```

---

## Task 8: Regression + smoke

- [ ] **Step 1: Full suite**

`pytest tests/ -q` — expect 954+ passes, 0 new failures.

- [ ] **Step 2: Manual smoke — pakowanie_bezposrednie**

Create a K7 szarża, pick "Bez zbiornika" → "IBC". Fill through sulfonowanie → standaryzacja (fake values). Close the batch (no tank pick). Open detail view. Cert panel visible. Generate cert → PDF contains the entered values.

- [ ] **Step 3: Manual smoke — platkowanie**

Open an existing `typ='platkowanie'` batch (or create one). Cert panel visible + generation works.

- [ ] **Step 4: Manual smoke — cross-product tank**

Create a K7 szarża. Open the pump modal. See "+ Pokaż wszystkie (N)" button. Expand → see K40GL tanks with `[K40GL]` badge. Pick one → complete. Open audit history for the batch → event `ebr.przepompowanie.added` has `cross_product: 1`.

- [ ] **Step 5: Optional polish commit**

If smoke reveals minor CSS/text tweaks, commit under `chore(cert-pakowanie): smoke fixes`.
