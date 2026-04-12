# Parametry: Precision per produkt + Modal + Auto-zaokrąglanie — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-product precision overrides for analytical parameters, replace the dropdown parameter picker with a filterable modal table, and auto-round values on blur and in the titration calculator.

**Architecture:** New `precision` column in `parametry_etapy` with cascade `COALESCE(pe.precision, pa.precision, 2)`. Modal renders all active parameters as a checkbox table with inline precision/order editing. Auto-rounding applied in JS on blur + in `acceptCalc()`, and on backend in `save_wyniki()`.

**Tech Stack:** Python/Flask, SQLite, Jinja2, vanilla JS

**Spec:** `docs/superpowers/specs/2026-04-12-parametry-precision-modal-design.md`

---

### Task 1: Add `precision` column to `parametry_etapy`

**Files:**
- Modify: `mbr/models.py:472-492` (table creation)
- Test: `tests/test_parametry_registry.py`

- [ ] **Step 1: Write failing test for precision cascade**

Add to `tests/test_parametry_registry.py`:

```python
def test_precision_cascade_global_default(db):
    """Without per-product override, precision comes from parametry_analityczne."""
    params = get_parametry_for_kontekst(db, "Chegina_K7", "analiza_koncowa")
    ph = next(p for p in params if p["kod"] == "ph")
    assert ph["precision"] == 2  # from parametry_analityczne seed


def test_precision_cascade_binding_override(db):
    """Per-product precision in parametry_etapy overrides global."""
    # Insert a per-product override
    pa_id = db.execute(
        "SELECT id FROM parametry_analityczne WHERE kod='ph'"
    ).fetchone()[0]
    # Find the binding for analiza_koncowa
    binding = db.execute(
        "SELECT id FROM parametry_etapy WHERE parametr_id=? AND kontekst='analiza_koncowa'",
        (pa_id,),
    ).fetchone()
    db.execute(
        "UPDATE parametry_etapy SET precision=4 WHERE id=?", (binding["id"],)
    )
    db.commit()
    params = get_parametry_for_kontekst(db, "Chegina_K7", "analiza_koncowa")
    ph = next(p for p in params if p["kod"] == "ph")
    assert ph["precision"] == 4


def test_precision_cascade_null_fallback(db):
    """When both are NULL, default to 2."""
    db.execute("UPDATE parametry_analityczne SET precision=NULL WHERE kod='ph'")
    db.commit()
    params = get_parametry_for_kontekst(db, "Chegina_K7", "analiza_koncowa")
    ph = next(p for p in params if p["kod"] == "ph")
    assert ph["precision"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_parametry_registry.py::test_precision_cascade_binding_override -v`
Expected: FAIL — `parametry_etapy` has no `precision` column

- [ ] **Step 3: Add column to schema + update query**

In `mbr/models.py`, in the `parametry_etapy` CREATE TABLE (around line 472), add `precision` column before the UNIQUE constraint:

```sql
precision       INTEGER,
```

Add it after the `cert_variant_id` line, before the `UNIQUE(produkt, kontekst, parametr_id)` line.

In `mbr/parametry/registry.py`, line 45, change:

```python
            pa.precision,
```

to:

```python
            COALESCE(pe.precision, pa.precision, 2) AS precision,
```

- [ ] **Step 4: Run all three precision tests**

Run: `pytest tests/test_parametry_registry.py -k "precision_cascade" -v`
Expected: All 3 PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `pytest tests/test_parametry_registry.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add mbr/models.py mbr/parametry/registry.py tests/test_parametry_registry.py
git commit -m "feat: add precision column to parametry_etapy with cascade resolution"
```

---

### Task 2: Update API endpoints for precision in bindings

**Files:**
- Modify: `mbr/parametry/routes.py:143-167` (PUT etapy — add `precision` to allowed fields)
- Test: `tests/test_param_centralization.py` (or `tests/test_parametry_registry.py`)

- [ ] **Step 1: Write failing test for PUT precision**

Add to `tests/test_parametry_registry.py`:

```python
def test_api_etapy_update_precision(db):
    """PUT /api/parametry/etapy/<id> accepts precision field."""
    from mbr.app import create_app
    app = create_app()
    with app.test_client() as c:
        # Login
        c.post("/login", data={"username": "admin", "password": "admin"})
        # Find a binding
        pa_id = db.execute(
            "SELECT id FROM parametry_analityczne WHERE kod='ph'"
        ).fetchone()[0]
        binding = db.execute(
            "SELECT id FROM parametry_etapy WHERE parametr_id=? AND kontekst='analiza_koncowa'",
            (pa_id,),
        ).fetchone()
        rv = c.put(
            f"/api/parametry/etapy/{binding['id']}",
            json={"precision": 3},
        )
        assert rv.status_code == 200
        row = db.execute(
            "SELECT precision FROM parametry_etapy WHERE id=?", (binding["id"],)
        ).fetchone()
        assert row["precision"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_parametry_registry.py::test_api_etapy_update_precision -v`
Expected: FAIL — `precision` not in allowed set, returns 400

- [ ] **Step 3: Add precision to allowed fields**

In `mbr/parametry/routes.py`, line 148, change:

```python
    allowed = {"nawazka_g", "min_limit", "max_limit", "target", "kolejnosc", "formula", "sa_bias"}
```

to:

```python
    allowed = {"nawazka_g", "min_limit", "max_limit", "target", "kolejnosc", "formula", "sa_bias", "precision"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_parametry_registry.py::test_api_etapy_update_precision -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mbr/parametry/routes.py tests/test_parametry_registry.py
git commit -m "feat: allow precision updates in PUT /api/parametry/etapy"
```

---

### Task 3: Auto-round on backend in `save_wyniki()`

**Files:**
- Modify: `mbr/laborant/models.py:430-541` (save_wyniki)
- Test: `tests/test_laborant.py`

- [ ] **Step 1: Write failing test for rounding on save**

Add to `tests/test_laborant.py` (or create section at end):

```python
def test_save_wyniki_rounds_to_precision(db_with_ebr):
    """save_wyniki() rounds wartosc to parameter precision before saving."""
    db, ebr_id = db_with_ebr
    from mbr.laborant.models import save_wyniki, get_ebr
    ebr = get_ebr(db, ebr_id)
    # ph has precision=2 in seed
    save_wyniki(db, ebr_id, "analiza_koncowa", {
        "ph": {"wartosc": "7.3456", "komentarz": ""}
    }, "tester", ebr=ebr)
    db.commit()
    row = db.execute(
        "SELECT wartosc FROM ebr_wyniki WHERE ebr_id=? AND kod_parametru='ph'",
        (ebr_id,),
    ).fetchone()
    assert row["wartosc"] == 7.35  # rounded to precision=2
```

Note: This test depends on the test fixture. Check existing `test_laborant.py` for the fixture pattern and adapt accordingly. The fixture must create a seeded DB with an EBR that has `parametry_lab` containing `ph` in `analiza_koncowa`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_laborant.py::test_save_wyniki_rounds_to_precision -v`
Expected: FAIL — `wartosc` is `7.3456` (not rounded)

- [ ] **Step 3: Implement rounding in save_wyniki**

In `mbr/laborant/models.py`, in `save_wyniki()`, after the line:

```python
        try:
            wartosc = float(wartosc_raw)
        except (ValueError, TypeError):
            continue
```

Add precision resolution and rounding:

```python
        prec = pole.get("precision", 2)
        try:
            from mbr.parametry_registry import get_parametry_for_kontekst
            produkt = ebr.get("produkt", "")
            db_params = get_parametry_for_kontekst(db, produkt, base_sekcja)
            if not db_params and base_sekcja == "analiza":
                db_params = get_parametry_for_kontekst(db, produkt, "analiza_koncowa")
            db_pole = next((p for p in db_params if p["kod"] == kod), None)
            if db_pole and db_pole.get("precision") is not None:
                prec = db_pole["precision"]
        except Exception:
            pass
        wartosc = round(wartosc, prec)
```

Note: The `get_parametry_for_kontekst` import and DB lookup already exist later in this function for limit resolution. Merge the precision lookup into that same block to avoid duplicate queries. The combined block (around line 510-520) should be:

```python
        try:
            from mbr.parametry_registry import get_parametry_for_kontekst
            produkt = ebr.get("produkt", "")
            db_params = get_parametry_for_kontekst(db, produkt, base_sekcja)
            if not db_params and base_sekcja == "analiza":
                db_params = get_parametry_for_kontekst(db, produkt, "analiza_koncowa")
            db_pole = next((p for p in db_params if p["kod"] == kod), None)
            if db_pole:
                min_limit = db_pole["min"]
                max_limit = db_pole["max"]
                if db_pole.get("precision") is not None:
                    prec = db_pole["precision"]
        except Exception:
            pass

        wartosc = round(wartosc, prec)
```

This replaces the existing try/except block that only resolves limits. The rounding line goes right after the block, before the `w_limicie` computation.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_laborant.py::test_save_wyniki_rounds_to_precision -v`
Expected: PASS

- [ ] **Step 5: Run full laborant tests**

Run: `pytest tests/test_laborant.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add mbr/laborant/models.py tests/test_laborant.py
git commit -m "feat: round wartosc to parameter precision in save_wyniki"
```

---

### Task 4: Add `data-precision` to frontend inputs + blur auto-round

**Files:**
- Modify: `mbr/templates/laborant/fast_entry.html:249-355` (renderSections)

- [ ] **Step 1: Add `data-precision` attribute to inputs in renderSections()**

In `mbr/templates/laborant/fast_entry.html`, inside `renderSections()`, in the `<input>` tag generation (around line 320), add `data-precision` attribute. Find:

```javascript
                        data-measurement-type="${esc(pole.measurement_type || '')}"
```

Add after it:

```javascript
                        data-precision="${pole.precision != null ? pole.precision : 2}"
```

- [ ] **Step 2: Add blur handler for auto-rounding**

In the same file, after the `renderSections()` function, add a delegated blur handler. Find a suitable location after the function (or in the initialization block) and add:

```javascript
document.getElementById('sections-container').addEventListener('blur', function(e) {
    const inp = e.target;
    if (inp.tagName !== 'INPUT' || inp.type !== 'number') return;
    if (inp.readOnly) return;
    const raw = inp.value.replace(',', '.');
    if (raw === '' || isNaN(raw)) return;
    const prec = parseInt(inp.dataset.precision || '2', 10);
    inp.value = parseFloat(raw).toFixed(prec).replace('.', ',');
}, true);
```

The `true` argument enables capture phase so blur (which doesn't bubble) is caught.

- [ ] **Step 3: Test manually in browser**

Run: `python -m mbr.app`

1. Log in as laborant
2. Open an EBR with analiza końcowa
3. Type `12.456` in a field with precision=2
4. Tab out — value should change to `12.46`
5. Type `7.1` in pH field (precision=2) — should stay `7.10`

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/fast_entry.html
git commit -m "feat: add data-precision to inputs and auto-round on blur"
```

---

### Task 5: Auto-round in titration calculator on accept

**Files:**
- Modify: `mbr/static/calculator.js:660-703` (acceptCalc)

- [ ] **Step 1: Change `.toFixed(4)` to use precision from target input**

In `mbr/static/calculator.js`, in `acceptCalc()`, find (around line 684):

```javascript
        input.value = avg.toFixed(4).replace('.', ',');
```

Replace with:

```javascript
        var prec = parseInt(input.dataset.precision || '4', 10);
        input.value = avg.toFixed(prec).replace('.', ',');
```

- [ ] **Step 2: Test manually in browser**

Run: `python -m mbr.app`

1. Log in as laborant
2. Open an EBR, click a titration field (e.g. NaCl, precision=2)
3. Enter sample masses and volumes in calculator
4. Click "Zatwierdź wynik"
5. Value should be rounded to 2 decimals (not 4)

- [ ] **Step 3: Commit**

```bash
git add mbr/static/calculator.js
git commit -m "feat: titration calculator uses parameter precision on accept"
```

---

### Task 6: Parametry modal — HTML template

**Files:**
- Create: `mbr/templates/laborant/_parametry_modal.html`

- [ ] **Step 1: Create the modal template**

Create `mbr/templates/laborant/_parametry_modal.html`:

```html
<div id="parametryModal" class="modal-overlay" style="display:none;">
  <div class="modal-box" style="max-width:800px;max-height:80vh;display:flex;flex-direction:column;">
    <div class="modal-head">
      <span class="modal-title">Parametry analizy — <span id="pmProdukt"></span></span>
      <button class="modal-close" onclick="closeParametryModal()">&times;</button>
    </div>
    <div style="padding:8px 16px;">
      <input type="text" id="pmFilter" placeholder="Filtruj po nazwie lub kodzie..."
             style="width:100%;padding:8px 10px;border:1.5px solid var(--border);border-radius:var(--radius);font-size:13px;"
             oninput="filterParametryRows()">
    </div>
    <div style="flex:1;overflow-y:auto;padding:0 16px 16px;">
      <table class="tbl" style="width:100%;">
        <thead>
          <tr>
            <th style="width:40px;"></th>
            <th>Nazwa</th>
            <th>Kod</th>
            <th>Typ</th>
            <th>Jednostka</th>
            <th style="width:80px;">Precyzja</th>
            <th style="width:80px;">Kolejność</th>
          </tr>
        </thead>
        <tbody id="pmBody"></tbody>
      </table>
    </div>
    <div style="padding:12px 16px;border-top:1px solid var(--border);text-align:right;">
      <button class="btn btn-s" onclick="closeParametryModal()">Zamknij</button>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Commit**

```bash
git add mbr/templates/laborant/_parametry_modal.html
git commit -m "feat: add parametry modal HTML template"
```

---

### Task 7: Parametry modal — JavaScript logic

**Files:**
- Modify: `mbr/templates/laborant/fast_entry.html` (add button + JS for modal)

- [ ] **Step 1: Include the modal template**

In `mbr/templates/laborant/fast_entry.html`, find the end of the main content (before closing `</body>` or before the final `</script>` block). Add:

```html
{% include 'laborant/_parametry_modal.html' %}
```

- [ ] **Step 2: Add the "Konfiguruj parametry" button**

In `renderSections()`, inside the section header for `analiza_koncowa` (or all sections), after the badge HTML, add a config button. Find in `renderSections()`:

```javascript
        let headHtml = `
            <div class="sec-head">
                <div class="sec-icon teal">${i + 1}</div>
                <span class="sec-title">${esc(etap.nazwa)}</span>
                ${badgeHtml}
            </div>
        `;
```

Replace with:

```javascript
        const configBtn = (!isReadonly && sekcja === 'analiza_koncowa')
            ? `<button class="btn btn-xs btn-ghost" onclick="openParametryModal('${esc(sekcja)}')" title="Konfiguruj parametry" style="margin-left:auto;">⚙ Parametry</button>`
            : '';

        let headHtml = `
            <div class="sec-head">
                <div class="sec-icon teal">${i + 1}</div>
                <span class="sec-title">${esc(etap.nazwa)}</span>
                ${badgeHtml}
                ${configBtn}
            </div>
        `;
```

- [ ] **Step 3: Add modal JS functions**

Add the following JS at the end of the `<script>` block in `fast_entry.html`:

```javascript
// ═══ PARAMETRY MODAL ═══

let _pmKontekst = '';
let _pmAllParams = [];
let _pmBindings = {};  // parametr_id → {id, precision, kolejnosc}

async function openParametryModal(kontekst) {
    _pmKontekst = kontekst;
    document.getElementById('pmProdukt').textContent = produkt;
    document.getElementById('pmFilter').value = '';

    // Fetch all active parameters
    const resAll = await fetch('/api/parametry/available');
    _pmAllParams = await resAll.json();

    // Fetch current bindings for this product+kontekst
    const resBindings = await fetch(`/api/parametry/etapy/${encodeURIComponent(produkt)}/${encodeURIComponent(kontekst)}`);
    const bindingsArr = await resBindings.json();
    _pmBindings = {};
    bindingsArr.forEach(b => {
        _pmBindings[b.parametr_id] = {
            id: b.id,
            precision: b.precision,
            kolejnosc: b.kolejnosc
        };
    });

    renderParametryRows();
    document.getElementById('parametryModal').style.display = 'flex';
}

function closeParametryModal() {
    document.getElementById('parametryModal').style.display = 'none';
    // Rebuild MBR parametry_lab
    fetch('/api/parametry/rebuild-mbr', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({produkt: produkt})
    }).then(() => location.reload());
}

function renderParametryRows() {
    const filter = (document.getElementById('pmFilter').value || '').toLowerCase();
    const tbody = document.getElementById('pmBody');
    tbody.innerHTML = '';

    _pmAllParams.forEach(p => {
        const label = (p.label || '').toLowerCase();
        const kod = (p.kod || '').toLowerCase();
        if (filter && !label.includes(filter) && !kod.includes(filter)) return;

        const binding = _pmBindings[p.id];
        const checked = !!binding;
        const precVal = binding ? (binding.precision != null ? binding.precision : '') : '';
        const precPlaceholder = p.precision != null ? p.precision : 2;
        const orderVal = binding ? (binding.kolejnosc || 0) : 0;

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><input type="checkbox" ${checked ? 'checked' : ''}
                 onchange="toggleBinding(${p.id}, this.checked)"></td>
            <td>${esc(p.label)}</td>
            <td><code>${esc(p.kod)}</code></td>
            <td>${esc(p.typ)}</td>
            <td>${esc(p.jednostka || '—')}</td>
            <td><input type="number" min="0" max="6" step="1"
                 value="${precVal}" placeholder="${precPlaceholder}"
                 style="width:60px;text-align:center;${!checked ? 'opacity:0.3;pointer-events:none;' : ''}"
                 onchange="updateBinding(${p.id}, 'precision', this.value === '' ? null : parseInt(this.value))"></td>
            <td><input type="number" min="0" step="1"
                 value="${orderVal}"
                 style="width:60px;text-align:center;${!checked ? 'opacity:0.3;pointer-events:none;' : ''}"
                 onchange="updateBinding(${p.id}, 'kolejnosc', parseInt(this.value) || 0)"></td>
        `;
        tbody.appendChild(tr);
    });
}

function filterParametryRows() {
    renderParametryRows();
}

async function toggleBinding(paramId, checked) {
    if (checked) {
        const res = await fetch('/api/parametry/etapy', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                parametr_id: paramId,
                kontekst: _pmKontekst,
                produkt: produkt
            })
        });
        const data = await res.json();
        if (data.ok) {
            _pmBindings[paramId] = {id: data.id, precision: null, kolejnosc: 0};
        }
    } else {
        const binding = _pmBindings[paramId];
        if (binding) {
            await fetch(`/api/parametry/etapy/${binding.id}`, {method: 'DELETE'});
            delete _pmBindings[paramId];
        }
    }
    renderParametryRows();
}

async function updateBinding(paramId, field, value) {
    const binding = _pmBindings[paramId];
    if (!binding) return;
    await fetch(`/api/parametry/etapy/${binding.id}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({[field]: value})
    });
    binding[field] = value;
}
```

- [ ] **Step 4: Test manually in browser**

Run: `python -m mbr.app`

1. Log in as laborant
2. Open an EBR (status=open) with analiza końcowa
3. Click "⚙ Parametry" button in section header
4. Modal opens — see all parameters in table
5. Type "ph" in filter — only pH row visible
6. Uncheck a parameter — row dims
7. Check it back — row re-enables
8. Change precision to 3 — field saves
9. Change kolejność — field saves
10. Close modal — page reloads with updated parameters

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/laborant/fast_entry.html
git commit -m "feat: parametry modal with checkbox table, filter, precision & order editing"
```

---

### Task 8: Endpoint for fetching bindings with precision

**Files:**
- Modify: `mbr/parametry/routes.py:281-294` (GET etapy endpoint)

- [ ] **Step 1: Verify current endpoint returns needed fields**

Read `mbr/parametry/routes.py` around line 281-294 to check the GET `/api/parametry/etapy/<produkt>/<kontekst>` response. It needs to include `parametr_id`, `id`, `precision`, and `kolejnosc`.

- [ ] **Step 2: Add precision to the query if missing**

In the GET endpoint, ensure the SELECT includes `precision`. If the current query is `SELECT *`, it already includes it after the ALTER TABLE. If it selects specific columns, add `precision`. Find the query and ensure it returns:

```sql
SELECT id, parametr_id, precision, kolejnosc, min_limit, max_limit, nawazka_g, target
FROM parametry_etapy
WHERE produkt = ? AND kontekst = ?
ORDER BY kolejnosc
```

- [ ] **Step 3: Test manually**

Run: `curl http://localhost:5001/api/parametry/etapy/Chegina_K7/analiza_koncowa`
Expected: JSON array with objects containing `id`, `parametr_id`, `precision`, `kolejnosc`

- [ ] **Step 4: Commit (if changes were needed)**

```bash
git add mbr/parametry/routes.py
git commit -m "feat: include precision in GET /api/parametry/etapy response"
```

---

### Task 9: Ensure `build_parametry_lab` propagates resolved precision

**Files:**
- Modify: `mbr/parametry/registry.py:206-267` (build_parametry_lab / _build_pole)
- Test: `tests/test_parametry_registry.py`

- [ ] **Step 1: Write test for precision in built parametry_lab**

Add to `tests/test_parametry_registry.py`:

```python
def test_build_parametry_lab_uses_resolved_precision(db):
    """build_parametry_lab() includes resolved precision (binding > global)."""
    plab = build_parametry_lab(db, "Chegina_K7")
    sekcja = plab.get("analiza_koncowa", plab.get("analiza", {}))
    pola = sekcja["pola"]
    ph = next(p for p in pola if p["kod"] == "ph")
    assert ph["precision"] == 2  # global default

    # Now override in binding
    pa_id = db.execute("SELECT id FROM parametry_analityczne WHERE kod='ph'").fetchone()[0]
    binding = db.execute(
        "SELECT id FROM parametry_etapy WHERE parametr_id=? AND kontekst='analiza_koncowa'",
        (pa_id,),
    ).fetchone()
    db.execute("UPDATE parametry_etapy SET precision=4 WHERE id=?", (binding["id"],))
    db.commit()

    plab2 = build_parametry_lab(db, "Chegina_K7")
    sekcja2 = plab2.get("analiza_koncowa", plab2.get("analiza", {}))
    ph2 = next(p for p in sekcja2["pola"] if p["kod"] == "ph")
    assert ph2["precision"] == 4  # binding override
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_parametry_registry.py::test_build_parametry_lab_uses_resolved_precision -v`
Expected: PASS (should already work after Task 1 changes to the SQL query). If it fails, check that `_build_pole` reads from the resolved `precision` field — it already does (`"precision": p["precision"]` at line ~225).

- [ ] **Step 3: Commit**

```bash
git add tests/test_parametry_registry.py
git commit -m "test: verify build_parametry_lab uses resolved precision cascade"
```

---

### Task 10: Migration script for existing database

**Files:**
- Create: `scripts/migrate_precision_etapy.py`

- [ ] **Step 1: Write migration script**

Create `scripts/migrate_precision_etapy.py`:

```python
"""Add precision column to parametry_etapy table.

Run once: python scripts/migrate_precision_etapy.py
"""

import sqlite3
import sys
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "batch_db.sqlite")


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"DB not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    cols = [r["name"] for r in conn.execute("PRAGMA table_info(parametry_etapy)")]
    if "precision" in cols:
        print("Column 'precision' already exists in parametry_etapy. Nothing to do.")
        conn.close()
        return

    conn.execute("ALTER TABLE parametry_etapy ADD COLUMN precision INTEGER")
    conn.commit()
    print("Added 'precision' column to parametry_etapy.")
    conn.close()


if __name__ == "__main__":
    migrate()
```

- [ ] **Step 2: Test on dev DB**

Run: `python scripts/migrate_precision_etapy.py`
Expected: "Added 'precision' column to parametry_etapy."

Run again: "Column 'precision' already exists..."

- [ ] **Step 3: Commit**

```bash
git add scripts/migrate_precision_etapy.py
git commit -m "feat: migration script for precision column in parametry_etapy"
```

---

### Task 11: End-to-end browser test

**Files:** None (manual testing)

- [ ] **Step 1: Full flow test**

Run: `python -m mbr.app`

Test the complete flow:

1. **Modal:** Open EBR → click "⚙ Parametry" → modal opens with all params
2. **Filter:** Type "su" → see only "Sucha masa" etc.
3. **Add param:** Check a previously unchecked parameter → it gets a binding
4. **Set precision:** Change precision to 1 for "Sucha masa" → close modal → page reloads
5. **Verify precision on input:** The sm input should have `data-precision="1"`
6. **Manual input rounding:** Type `45.678` in sm field, tab out → shows `45.7`
7. **Calculator rounding:** Open calculator for a titracja field (e.g. NaCl, precision=2), enter data, accept → result has 2 decimals
8. **Save & verify:** Save section, check DB: `SELECT wartosc FROM ebr_wyniki WHERE kod_parametru='sm'` → value is rounded
9. **Remove param:** Open modal, uncheck a param, close → param disappears from form
10. **New EBR:** Create new EBR for same product → inherits updated precision settings

- [ ] **Step 2: Edge cases**

- Empty precision field in modal (should use global default)
- Precision=0 → integer values only
- Precision=4 → 4 decimal places
- Existing saved values display correctly (not re-rounded on load, only on new input)
