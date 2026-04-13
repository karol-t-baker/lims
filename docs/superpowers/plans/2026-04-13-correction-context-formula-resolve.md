# Correction Context & Formula Resolve — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backend endpoint that auto-resolves formula variables (measurements, specs, batch data) and returns a full breakdown; frontend correction form that shows context and editable reduction.

**Architecture:** New `resolve_formula_zmienne()` in pipeline/models.py resolves `pomiar:`, `target:`, batch fields, and Meff expressions. New `POST /formula-resolve` endpoint calls it. Frontend `openCorrectionForm()` calls it per substance and renders context + breakdown.

**Tech Stack:** Python/Flask, SQLite, vanilla JS

**Spec:** `docs/superpowers/specs/2026-04-13-correction-context-formula-resolve-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `mbr/pipeline/models.py:718-737` | New `resolve_formula_zmienne()` + `resolve_single_variable()` helpers |
| Modify | `mbr/pipeline/lab_routes.py:317-328` | New `POST /formula-resolve` endpoint |
| Modify | `mbr/templates/laborant/_fast_entry_content.html:3116-3239` | Correction form with context display, reduction edit, formula breakdown |
| Modify | `tests/test_pipeline_models.py` | Tests for variable resolver |
| Modify | `tests/test_pipeline_routes.py` | Tests for formula-resolve endpoint |

---

### Task 1: Backend — Variable resolver `resolve_formula_zmienne()`

**Files:**
- Modify: `mbr/pipeline/models.py` (after `compute_formula_hint` at line ~737)
- Test: `tests/test_pipeline_models.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_pipeline_models.py — add

def test_resolve_formula_zmienne_pomiar_ref(db, setup_pipeline):
    """resolve_formula_zmienne resolves pomiar: references from current session."""
    from mbr.pipeline.models import resolve_formula_zmienne, create_sesja, save_pomiar

    p = setup_pipeline
    # Create session with a measurement
    sesja_id = create_sesja(db, p["ebr_id"], p["etap1_id"], runda=1, laborant="lab1")
    save_pomiar(db, sesja_id, p["param1_id"], 0.05, min_limit=None, max_limit=0.1, wpisal="lab1")
    db.commit()

    # Setup formula_zmienne on the correction type
    db.execute(
        """UPDATE etap_korekty_katalog
           SET formula_ilosc = ':C_so3 * :Meff',
               formula_zmienne = '{"C_so3": "pomiar:param1", "Meff": "wielkosc_szarzy_kg > 6600 ? wielkosc_szarzy_kg - 1000 : wielkosc_szarzy_kg - 500"}'
           WHERE id = ?""",
        (p["korekta_typ_id_1"],),
    )
    db.commit()

    result = resolve_formula_zmienne(
        db,
        korekta_typ_id=p["korekta_typ_id_1"],
        etap_id=p["etap1_id"],
        sesja_id=sesja_id,
        ebr_id=p["ebr_id"],
    )
    assert result["ok"] is True
    assert result["zmienne"]["C_so3"] == 0.05
    assert result["zmienne"]["wielkosc_szarzy_kg"] is not None
    assert result["zmienne"]["Meff"] is not None
    assert result["zmienne"]["redukcja"] is not None
    assert result["wynik"] is not None


def test_resolve_formula_zmienne_target_ref(db, setup_pipeline):
    """resolve_formula_zmienne resolves target: references from spec_value."""
    from mbr.pipeline.models import resolve_formula_zmienne, create_sesja

    p = setup_pipeline
    sesja_id = create_sesja(db, p["ebr_id"], p["etap1_id"], runda=1, laborant="lab1")
    db.commit()

    # Set spec_value on parameter
    db.execute(
        "UPDATE etap_parametry SET spec_value = 0.03 WHERE etap_id = ? AND parametr_id = ?",
        (p["etap1_id"], p["param1_id"]),
    )
    db.execute(
        """UPDATE etap_korekty_katalog
           SET formula_ilosc = ':target_p1 * 100',
               formula_zmienne = '{"target_p1": "target:param1"}'
           WHERE id = ?""",
        (p["korekta_typ_id_1"],),
    )
    db.commit()

    result = resolve_formula_zmienne(
        db,
        korekta_typ_id=p["korekta_typ_id_1"],
        etap_id=p["etap1_id"],
        sesja_id=sesja_id,
        ebr_id=p["ebr_id"],
    )
    assert result["ok"] is True
    assert result["zmienne"]["target_p1"] == 0.03
    assert abs(result["wynik"] - 3.0) < 0.01


def test_resolve_formula_zmienne_redukcja_override(db, setup_pipeline):
    """redukcja_override replaces default Meff calculation."""
    from mbr.pipeline.models import resolve_formula_zmienne, create_sesja

    p = setup_pipeline
    sesja_id = create_sesja(db, p["ebr_id"], p["etap1_id"], runda=1, laborant="lab1")
    db.commit()

    db.execute(
        """UPDATE etap_korekty_katalog
           SET formula_ilosc = ':Meff * 0.01',
               formula_zmienne = '{"Meff": "wielkosc_szarzy_kg > 6600 ? wielkosc_szarzy_kg - 1000 : wielkosc_szarzy_kg - 500"}'
           WHERE id = ?""",
        (p["korekta_typ_id_1"],),
    )
    db.commit()

    result = resolve_formula_zmienne(
        db,
        korekta_typ_id=p["korekta_typ_id_1"],
        etap_id=p["etap1_id"],
        sesja_id=sesja_id,
        ebr_id=p["ebr_id"],
        redukcja_override=800,
    )
    masa = result["zmienne"]["wielkosc_szarzy_kg"]
    assert result["zmienne"]["redukcja"] == 800
    assert result["zmienne"]["Meff"] == masa - 800


def test_resolve_formula_zmienne_previous_stage_pomiar(db, setup_pipeline):
    """pomiar: reference falls back to previous stage when current session has no measurement."""
    from mbr.pipeline.models import resolve_formula_zmienne, create_sesja, save_pomiar

    p = setup_pipeline
    # Create session in etap1 with measurement
    sesja1 = create_sesja(db, p["ebr_id"], p["etap1_id"], runda=1, laborant="lab1")
    save_pomiar(db, sesja1, p["param1_id"], 0.07, min_limit=None, max_limit=0.1, wpisal="lab1")
    db.commit()

    # Create session in etap2 (no measurement for param1)
    sesja2 = create_sesja(db, p["ebr_id"], p["etap2_id"], runda=1, laborant="lab1")
    db.commit()

    db.execute(
        """UPDATE etap_korekty_katalog
           SET formula_ilosc = ':C_p1 * 100',
               formula_zmienne = '{"C_p1": "pomiar:param1"}'
           WHERE id = ?""",
        (p["korekta_typ_id_2"],),
    )
    db.commit()

    result = resolve_formula_zmienne(
        db,
        korekta_typ_id=p["korekta_typ_id_2"],
        etap_id=p["etap2_id"],
        sesja_id=sesja2,
        ebr_id=p["ebr_id"],
    )
    assert result["zmienne"]["C_p1"] == 0.07
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pipeline_models.py::test_resolve_formula_zmienne_pomiar_ref tests/test_pipeline_models.py::test_resolve_formula_zmienne_target_ref tests/test_pipeline_models.py::test_resolve_formula_zmienne_redukcja_override tests/test_pipeline_models.py::test_resolve_formula_zmienne_previous_stage_pomiar -v`
Expected: FAIL — `resolve_formula_zmienne` not found

- [ ] **Step 3: Check and extend `setup_pipeline` fixture**

The existing `setup_pipeline` fixture needs: `ebr_id`, `etap1_id`, `etap2_id`, `param1_id`, `korekta_typ_id_1`, `korekta_typ_id_2`. It also needs `ebr_batches` to have `wielkosc_szarzy_kg` set, and a `produkt_pipeline` entry so pipeline ordering works. Check the existing fixture and extend it — ensure `wielkosc_szarzy_kg` is populated (e.g., 10000) and two stages exist in `produkt_pipeline` with correct `kolejnosc`.

- [ ] **Step 4: Implement `resolve_formula_zmienne()` in `mbr/pipeline/models.py`**

Add after `compute_formula_hint()` (line ~737):

```python
import json as _json

VARIABLE_LABELS = {
    "wielkosc_szarzy_kg": "Masa szarży",
    "redukcja": "Redukcja",
    "Meff": "Masa efektywna",
}


def _resolve_single_variable(
    db: sqlite3.Connection,
    var_name: str,
    var_ref: str,
    ebr_id: int,
    etap_id: int,
    sesja_id: int,
    produkt: str,
) -> tuple[float | None, str]:
    """Resolve a single formula variable reference.

    Returns (value, label).
    """
    if var_ref.startswith("pomiar:"):
        kod = var_ref.split(":", 1)[1]
        pa = db.execute("SELECT id, label FROM parametry_analityczne WHERE kod=?", (kod,)).fetchone()
        if not pa:
            return None, f"Pomiar {kod}"
        # Try current session first
        row = db.execute(
            "SELECT wartosc FROM ebr_pomiar WHERE sesja_id=? AND parametr_id=?",
            (sesja_id, pa["id"]),
        ).fetchone()
        if row and row["wartosc"] is not None:
            return row["wartosc"], f"Pomiar {pa['label']}"
        # Walk backwards through pipeline stages
        pipeline = db.execute(
            "SELECT etap_id FROM produkt_pipeline WHERE produkt=? ORDER BY kolejnosc DESC",
            (produkt,),
        ).fetchall()
        for step in pipeline:
            if step["etap_id"] == etap_id:
                continue
            sesje = db.execute(
                "SELECT id FROM ebr_etap_sesja WHERE ebr_id=? AND etap_id=? ORDER BY runda DESC LIMIT 1",
                (ebr_id, step["etap_id"]),
            ).fetchone()
            if not sesje:
                continue
            row = db.execute(
                "SELECT wartosc FROM ebr_pomiar WHERE sesja_id=? AND parametr_id=?",
                (sesje["id"], pa["id"]),
            ).fetchone()
            if row and row["wartosc"] is not None:
                return row["wartosc"], f"Pomiar {pa['label']}"
        return None, f"Pomiar {pa['label']}"

    if var_ref.startswith("target:"):
        kod = var_ref.split(":", 1)[1]
        pa = db.execute("SELECT id, label FROM parametry_analityczne WHERE kod=?", (kod,)).fetchone()
        if not pa:
            return None, f"Spec {kod}"
        limity = resolve_limity(db, produkt, etap_id)
        for lim in limity:
            if lim["parametr_id"] == pa["id"]:
                return lim.get("spec_value"), f"Spec {pa['label']}"
        return None, f"Spec {pa['label']}"

    if var_ref == "wielkosc_szarzy_kg":
        row = db.execute(
            "SELECT wielkosc_szarzy_kg FROM ebr_batches WHERE ebr_id=?", (ebr_id,)
        ).fetchone()
        return (row["wielkosc_szarzy_kg"] if row else None), "Masa szarży"

    # Expression or numeric literal — return as-is for later evaluation
    return var_ref, VARIABLE_LABELS.get(var_name, var_name)


def resolve_formula_zmienne(
    db: sqlite3.Connection,
    korekta_typ_id: int,
    etap_id: int,
    sesja_id: int,
    ebr_id: int,
    redukcja_override: float | None = None,
) -> dict:
    row = db.execute(
        "SELECT formula_ilosc, formula_zmienne, etap_id AS kor_etap_id FROM etap_korekty_katalog WHERE id=?",
        (korekta_typ_id,),
    ).fetchone()
    if not row or not row["formula_ilosc"]:
        return {"ok": False, "wynik": None, "zmienne": {}, "labels": {}}

    # Get product for this EBR
    ebr = db.execute(
        """SELECT m.produkt, e.wielkosc_szarzy_kg
           FROM ebr_batches e JOIN mbr_templates m ON m.mbr_id = e.mbr_id
           WHERE e.ebr_id = ?""",
        (ebr_id,),
    ).fetchone()
    produkt = ebr["produkt"] if ebr else ""
    masa = ebr["wielkosc_szarzy_kg"] if ebr else None

    zmienne_def = _json.loads(row["formula_zmienne"]) if row["formula_zmienne"] else {}
    resolved = {}
    labels = {}

    # Always include wielkosc_szarzy_kg
    resolved["wielkosc_szarzy_kg"] = masa
    labels["wielkosc_szarzy_kg"] = "Masa szarży"

    # Resolve each variable
    meff_expression = None
    for var_name, var_ref in zmienne_def.items():
        if var_name == "Meff":
            meff_expression = var_ref
            continue
        val, lbl = _resolve_single_variable(db, var_name, var_ref, ebr_id, etap_id, sesja_id, produkt)
        resolved[var_name] = val
        labels[var_name] = lbl

    # Handle Meff with optional reduction override
    if redukcja_override is not None and masa is not None:
        resolved["Meff"] = masa - redukcja_override
        resolved["redukcja"] = redukcja_override
    elif meff_expression and masa is not None:
        meff_expr = str(meff_expression)
        meff_expr = meff_expr.replace("wielkosc_szarzy_kg", str(float(masa)))
        try:
            meff_val = eval(meff_expr, {"__builtins__": {}})
            resolved["Meff"] = meff_val
            resolved["redukcja"] = masa - meff_val
        except Exception:
            resolved["Meff"] = None
            resolved["redukcja"] = None
    elif masa is not None:
        resolved["Meff"] = masa
        resolved["redukcja"] = 0

    labels["Meff"] = "Masa efektywna"
    labels["redukcja"] = "Redukcja"

    # Evaluate main formula
    formula = row["formula_ilosc"]
    for key, val in resolved.items():
        if val is not None and key != "wielkosc_szarzy_kg" and key != "redukcja":
            formula = formula.replace(f":{key}", str(float(val)))
    # Also replace wielkosc_szarzy_kg if referenced directly in formula
    if masa is not None:
        formula = formula.replace("wielkosc_szarzy_kg", str(float(masa)))

    try:
        wynik = eval(formula, {"__builtins__": {}})
    except Exception:
        wynik = None

    return {"ok": True, "wynik": wynik, "zmienne": resolved, "labels": labels}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pipeline_models.py -k "resolve_formula" -v`
Expected: PASS (all 4 tests)

- [ ] **Step 6: Run full suite for regressions**

Run: `pytest -x -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add mbr/pipeline/models.py tests/test_pipeline_models.py
git commit -m "feat: resolve_formula_zmienne — auto-resolve pomiar/target/batch/Meff variables"
```

---

### Task 2: Backend — `POST /formula-resolve` endpoint

**Files:**
- Modify: `mbr/pipeline/lab_routes.py` (after `lab_formula_hint` at line ~328)
- Test: `tests/test_pipeline_routes.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_pipeline_routes.py — add

def test_formula_resolve_endpoint(client, setup_pipeline_route):
    """POST formula-resolve should return resolved variables and computed result."""
    data = setup_pipeline_route
    resp = client.post(
        f"/api/pipeline/lab/ebr/{data['ebr_id']}/formula-resolve",
        json={
            "korekta_typ_id": data["korekta_typ_id"],
            "etap_id": data["etap_id"],
            "sesja_id": data["sesja_id"],
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert "zmienne" in body
    assert "wielkosc_szarzy_kg" in body["zmienne"]
    assert "labels" in body


def test_formula_resolve_with_redukcja_override(client, setup_pipeline_route):
    """POST formula-resolve with redukcja_override should use custom reduction."""
    data = setup_pipeline_route
    resp = client.post(
        f"/api/pipeline/lab/ebr/{data['ebr_id']}/formula-resolve",
        json={
            "korekta_typ_id": data["korekta_typ_id"],
            "etap_id": data["etap_id"],
            "sesja_id": data["sesja_id"],
            "redukcja_override": 800,
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["zmienne"]["redukcja"] == 800
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pipeline_routes.py::test_formula_resolve_endpoint tests/test_pipeline_routes.py::test_formula_resolve_with_redukcja_override -v`
Expected: FAIL — 404

- [ ] **Step 3: Implement endpoint in `mbr/pipeline/lab_routes.py`**

Add after `lab_formula_hint()`:

```python
@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/formula-resolve", methods=["POST"])
@login_required
def lab_formula_resolve(ebr_id):
    data = request.get_json(force=True) or {}
    korekta_typ_id = data["korekta_typ_id"]
    etap_id = data["etap_id"]
    sesja_id = data["sesja_id"]
    redukcja_override = data.get("redukcja_override")

    db = get_db()
    try:
        result = pm.resolve_formula_zmienne(
            db,
            korekta_typ_id=korekta_typ_id,
            etap_id=etap_id,
            sesja_id=sesja_id,
            ebr_id=ebr_id,
            redukcja_override=redukcja_override,
        )
        return jsonify(result)
    finally:
        db.close()
```

- [ ] **Step 4: Ensure `setup_pipeline_route` fixture has formula data**

Check the existing `setup_pipeline_route` fixture in `tests/test_pipeline_routes.py`. Ensure the correction type has `formula_ilosc` and `formula_zmienne` set so the endpoint has something to resolve. Extend fixture if needed.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pipeline_routes.py -k "formula_resolve" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add mbr/pipeline/lab_routes.py tests/test_pipeline_routes.py
git commit -m "feat: POST /formula-resolve endpoint for full variable resolution"
```

---

### Task 3: Frontend — Correction form with context display

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html:3116-3239`

- [ ] **Step 1: Replace `openCorrectionForm()` with context-aware version**

Find the existing `openCorrectionForm()` function (around line 3116). Replace it with:

```javascript
async function openCorrectionForm(sekcja, etapId, sesjaId) {
    var formDiv = document.getElementById('sdp-' + sekcja);
    if (!formDiv) return;

    // Fetch correction catalog
    var resp = await fetch('/api/pipeline/lab/etap/' + etapId + '/korekty-katalog');
    if (!resp.ok) return;
    var katalog = await resp.json();

    // Resolve formulas for each substance that has one
    var resolvedMap = {};
    var ebrId = window.ebrId || window._batchEbrId;
    for (var k of katalog) {
        if (k.formula_ilosc) {
            try {
                var fResp = await fetch('/api/pipeline/lab/ebr/' + ebrId + '/formula-resolve', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        korekta_typ_id: k.id,
                        etap_id: etapId,
                        sesja_id: sesjaId,
                    }),
                });
                if (fResp.ok) resolvedMap[k.id] = await fResp.json();
            } catch(e) {}
        }
    }

    // Find common context (masa, redukcja, Meff) from first resolved
    var ctx = null;
    for (var kid in resolvedMap) {
        ctx = resolvedMap[kid];
        break;
    }

    var html = '<div class="corr-form" style="padding:12px;border:1px solid var(--border-subtle);border-radius:6px;margin-top:8px;background:var(--surface-alt);">';

    // Context header
    if (ctx && ctx.zmienne) {
        var z = ctx.zmienne;
        var masa = z.wielkosc_szarzy_kg;
        var redukcja = z.redukcja != null ? z.redukcja : 0;
        var meff = z.Meff;
        html += '<div style="margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid var(--border-subtle);">';
        html += '<div style="font-weight:700;font-size:13px;margin-bottom:6px;">Kontekst</div>';
        html += '<table style="font-size:12px;width:100%;">';
        html += '<tr><td>Masa szarży:</td><td style="text-align:right;font-family:var(--mono);font-weight:600;">' + (masa != null ? masa.toLocaleString('pl') + ' kg' : '—') + '</td></tr>';
        html += '<tr><td>Redukcja:</td><td style="text-align:right;">'
            + '<input type="number" id="corr-redukcja-' + sekcja + '" value="' + redukcja + '" '
            + 'style="width:80px;text-align:right;font-family:var(--mono);font-size:12px;border:1px solid var(--border-subtle);border-radius:3px;padding:2px 4px;" '
            + 'data-sekcja="' + sekcja + '" data-etap-id="' + etapId + '" data-sesja-id="' + sesjaId + '" '
            + 'onchange="recalcRedukcja(this)"> kg</td></tr>';
        html += '<tr><td>Masa efektywna:</td><td id="corr-meff-' + sekcja + '" style="text-align:right;font-family:var(--mono);font-weight:600;">' + (meff != null ? meff.toLocaleString('pl') + ' kg' : '—') + '</td></tr>';
        html += '</table></div>';
    }

    // Per-substance sections
    katalog.forEach(function(k) {
        var res = resolvedMap[k.id];
        var hasFormula = !!k.formula_ilosc;
        var wynik = (res && res.wynik != null) ? res.wynik.toFixed(2) : '';

        html += '<div class="corr-substance" style="margin-bottom:10px;padding:8px;border:1px solid var(--border-subtle);border-radius:4px;">';
        html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">';
        html += '<input type="checkbox" id="corr-chk-' + sekcja + '-' + k.id + '" ' + (hasFormula && wynik ? 'checked' : '') + '>';
        html += '<span style="font-weight:700;">' + k.substancja + '</span>';
        html += '<span style="color:var(--text-dim);font-size:11px;">[' + k.jednostka + ']</span>';
        html += '</div>';

        if (hasFormula && res && res.zmienne) {
            // Show variable breakdown
            html += '<div style="font-size:11px;color:var(--text-dim);padding-left:24px;margin-bottom:6px;">';
            for (var vname in res.zmienne) {
                if (vname === 'wielkosc_szarzy_kg' || vname === 'redukcja' || vname === 'Meff') continue;
                var vval = res.zmienne[vname];
                var vlabel = (res.labels && res.labels[vname]) || vname;
                html += '<div>' + vlabel + ': <span style="font-family:var(--mono);font-weight:600;">' + (vval != null ? String(vval).replace('.', ',') : '—') + '</span></div>';
            }
            if (wynik) {
                html += '<div style="margin-top:4px;color:var(--teal);font-weight:600;">Wyliczone: ' + wynik.replace('.', ',') + ' ' + k.jednostka + '</div>';
            }
            html += '</div>';
        } else if (!hasFormula) {
            html += '<div style="font-size:11px;color:var(--text-dim);padding-left:24px;margin-bottom:6px;">(brak formuły — wpisz ręcznie)</div>';
        }

        // Quantity input
        html += '<div style="padding-left:24px;">';
        html += '<label style="font-size:11px;">Ilość:</label> ';
        html += '<input type="number" step="0.01" id="corr-qty-' + sekcja + '-' + k.id + '" '
            + 'class="corr-amount" data-korekta-typ-id="' + k.id + '" '
            + 'value="' + wynik + '" '
            + 'style="width:100px;text-align:right;font-family:var(--mono);font-size:13px;font-weight:600;border:1px solid var(--border-subtle);border-radius:3px;padding:2px 4px;"> '
            + k.jednostka;
        html += '</div></div>';
    });

    // Comment + buttons
    html += '<div style="margin-top:10px;">';
    html += '<textarea id="corr-comment-' + sekcja + '" placeholder="Komentarz (opcjonalnie)" rows="2" style="width:100%;font-size:12px;border:1px solid var(--border-subtle);border-radius:3px;padding:4px;"></textarea>';
    html += '</div>';
    html += '<div style="margin-top:8px;display:flex;gap:8px;">';
    html += '<button class="btn btn-primary" onclick="submitCorrectionOrder(\'' + sekcja + '\', ' + etapId + ', ' + sesjaId + ')">Zleć</button>';
    html += '<button class="btn btn-outline" onclick="closeCorrectionForm(\'' + sekcja + '\')">Anuluj</button>';
    html += '</div></div>';

    formDiv.innerHTML = html;
    formDiv.style.display = 'block';
}
```

- [ ] **Step 2: Replace `fetchFormulaHints()` with `recalcRedukcja()`**

Remove or replace the old `fetchFormulaHints()` function. Add `recalcRedukcja()`:

```javascript
async function recalcRedukcja(input) {
    var sekcja = input.dataset.sekcja;
    var etapId = parseInt(input.dataset.etapId);
    var sesjaId = parseInt(input.dataset.sesjaId);
    var redukcja = parseFloat(input.value) || 0;
    var ebrId = window.ebrId || window._batchEbrId;

    // Fetch correction catalog to find substances with formulas
    var resp = await fetch('/api/pipeline/lab/etap/' + etapId + '/korekty-katalog');
    if (!resp.ok) return;
    var katalog = await resp.json();

    for (var k of katalog) {
        if (!k.formula_ilosc) continue;
        try {
            var fResp = await fetch('/api/pipeline/lab/ebr/' + ebrId + '/formula-resolve', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    korekta_typ_id: k.id,
                    etap_id: etapId,
                    sesja_id: sesjaId,
                    redukcja_override: redukcja,
                }),
            });
            if (!fResp.ok) continue;
            var res = await fResp.json();

            // Update Meff display
            var meffEl = document.getElementById('corr-meff-' + sekcja);
            if (meffEl && res.zmienne && res.zmienne.Meff != null) {
                meffEl.textContent = res.zmienne.Meff.toLocaleString('pl') + ' kg';
            }

            // Update quantity field (only if user hasn't manually changed it)
            var qtyEl = document.getElementById('corr-qty-' + sekcja + '-' + k.id);
            if (qtyEl && res.wynik != null) {
                if (!qtyEl.dataset.manualEdit) {
                    qtyEl.value = res.wynik.toFixed(2);
                }
            }
        } catch(e) {}
    }
}
```

- [ ] **Step 3: Add manual-edit tracking to quantity inputs**

In the `openCorrectionForm()` code above, after rendering, add event listeners to track manual edits:

```javascript
// After formDiv.innerHTML = html; add:
formDiv.querySelectorAll('.corr-amount').forEach(function(inp) {
    inp.addEventListener('input', function() { this.dataset.manualEdit = '1'; });
});
```

- [ ] **Step 4: Clean up old `fetchFormulaHints` references**

Search for any remaining calls to `fetchFormulaHints` in the template and remove them. The new `openCorrectionForm()` handles everything internally.

- [ ] **Step 5: Manually test in browser**

Run: `python -m mbr.app`

Test checklist:
- Open a Chegina_K40GLO batch
- Navigate to sulfonowanie, enter SO3 measurement, save
- Click "Zlecenie korekty" — should show context (masa, redukcja, Meff) + Perhydrol breakdown
- Change redukcja field — Meff and Perhydrol amount should recalculate
- Navigate to standaryzacja — should show Woda + NaCl breakdowns with their variables
- Substance without formula (Na2SO3, Kw. cytrynowy) should show "(brak formuły)"
- Submit correction order — should work as before

- [ ] **Step 6: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: correction form with context display, formula breakdown, editable reduction"
```

---

### Task 4: Integration test — formula resolve with real-world data patterns

**Files:**
- Modify: `tests/test_operator_flow.py`

- [ ] **Step 1: Add integration test**

```python
# tests/test_operator_flow.py — add

def test_formula_resolve_cross_stage(db, pipeline):
    """Formula resolve in utlenianie should find SO3 measurement from sulfonowanie."""
    from mbr.pipeline.models import (
        create_sesja, save_pomiar, resolve_formula_zmienne,
    )
    p = pipeline

    # Add Perhydrol correction to utlenianie with formula
    db.execute(
        """INSERT INTO etap_korekty_katalog (etap_id, substancja, jednostka, kolejnosc,
               formula_ilosc, formula_zmienne)
           VALUES (?,'Perhydrol 34%','kg',1,
               '(:C_so3 - :target_so3) * 0.01214 * :Meff',
               '{"C_so3": "pomiar:so3", "target_so3": "target:so3", "Meff": "wielkosc_szarzy_kg > 6600 ? wielkosc_szarzy_kg - 1000 : wielkosc_szarzy_kg - 500"}')""",
        (p["utl_id"],),
    )
    perhydrol_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Add pipeline entries
    db.execute("INSERT OR IGNORE INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('K40GLO',?,1)", (p["sulf_id"],))
    db.execute("INSERT OR IGNORE INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('K40GLO',?,2)", (p["utl_id"],))

    # Set spec_value for SO3 on utlenianie
    db.execute(
        "INSERT OR IGNORE INTO etap_parametry (etap_id, parametr_id, kolejnosc, spec_value) VALUES (?,?,1,0.03)",
        (p["utl_id"], p["so3_id"]),
    )
    db.commit()

    # Sulfonowanie: measure SO3 = 0.05
    sesja_sulf = create_sesja(db, p["ebr_id"], p["sulf_id"], runda=1, laborant="lab1")
    save_pomiar(db, sesja_sulf, p["so3_id"], 0.05, min_limit=None, max_limit=0.1, wpisal="lab1")
    db.commit()

    # Utlenianie: start session (no SO3 measurement here)
    sesja_utl = create_sesja(db, p["ebr_id"], p["utl_id"], runda=1, laborant="lab1")
    db.commit()

    # Resolve formula — should find SO3 from sulfonowanie
    result = resolve_formula_zmienne(
        db,
        korekta_typ_id=perhydrol_id,
        etap_id=p["utl_id"],
        sesja_id=sesja_utl,
        ebr_id=p["ebr_id"],
    )
    assert result["ok"] is True
    assert result["zmienne"]["C_so3"] == 0.05
    assert result["zmienne"]["target_so3"] == 0.03
    assert result["zmienne"]["Meff"] is not None
    assert result["wynik"] is not None
    assert result["wynik"] > 0


def test_formula_resolve_redukcja_override(db, pipeline):
    """Redukcja override should change Meff and result."""
    from mbr.pipeline.models import create_sesja, save_pomiar, resolve_formula_zmienne
    p = pipeline

    db.execute(
        """INSERT INTO etap_korekty_katalog (etap_id, substancja, jednostka, kolejnosc,
               formula_ilosc, formula_zmienne)
           VALUES (?,'Woda','kg',1,
               ':Meff * 0.01',
               '{"Meff": "wielkosc_szarzy_kg > 6600 ? wielkosc_szarzy_kg - 1000 : wielkosc_szarzy_kg - 500"}')""",
        (p["sulf_id"],),
    )
    woda_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()

    sesja = create_sesja(db, p["ebr_id"], p["sulf_id"], runda=1, laborant="lab1")
    db.commit()

    # Without override
    r1 = resolve_formula_zmienne(db, woda_id, p["sulf_id"], sesja, p["ebr_id"])
    # With override
    r2 = resolve_formula_zmienne(db, woda_id, p["sulf_id"], sesja, p["ebr_id"], redukcja_override=2000)

    assert r2["zmienne"]["redukcja"] == 2000
    masa = r2["zmienne"]["wielkosc_szarzy_kg"]
    assert r2["zmienne"]["Meff"] == masa - 2000
    assert r1["wynik"] != r2["wynik"]
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/test_operator_flow.py -v`
Expected: PASS

- [ ] **Step 3: Run full suite**

Run: `pytest -x -q`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_operator_flow.py
git commit -m "test: integration tests for formula-resolve cross-stage and redukcja override"
```
