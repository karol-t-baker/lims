# Sulfonowanie/Utlenienie + Correction Formulas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add sulfonowanie stage to pipeline, configure utlenienie with perhydrol correction formula, add woda/NaCl formulas to standaryzacja, and unlock param editor for all pipeline sections.

**Architecture:** Setup script configures new stages and formulas in DB. JS correction panel evaluates formulas client-side using pomiary + targets + batch size. Param editor accepts section context parameter instead of hardcoded analiza_koncowa.

**Tech Stack:** Python setup script, vanilla JS formula evaluator, existing pipeline tables

---

## File Structure

### Files to create:
```
scripts/setup_sulfonowanie_utlenienie.py    — configure stages, params, gates, corrections with formulas
```

### Files to modify:
```
mbr/templates/laborant/_fast_entry_content.html  — formula eval in correction panel, param editor context
```

---

## Task 1: Setup sulfonowanie + utlenienie stages with formulas

**Files:**
- Create: `scripts/setup_sulfonowanie_utlenienie.py`

- [ ] **Step 1: Create setup script**

```python
# scripts/setup_sulfonowanie_utlenienie.py
"""
Configure sulfonowanie + utlenienie stages for K40GLOL/GLO/GL/K7.

Pipeline becomes: sulfonowanie → utlenienie → standaryzacja → analiza_koncowa

Also fills correction formulas for:
- Perhydrol (utlenienie)
- Woda (standaryzacja)
- NaCl (standaryzacja)

Run: python -m scripts.setup_sulfonowanie_utlenienie
"""
import sqlite3
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mbr.db import get_db
from mbr.models import init_mbr_tables
from mbr.pipeline.models import (
    create_etap, get_etap, add_etap_parametr, list_etap_parametry,
    add_etap_warunek, list_etap_warunki, add_etap_korekta, list_etap_korekty,
    set_produkt_pipeline, get_produkt_pipeline, remove_pipeline_etap,
    set_produkt_etap_limit,
)

PRODUCTS = ["Chegina_K40GLOL", "Chegina_K40GLO", "Chegina_K40GL", "Chegina_K7"]

# Parameter IDs (from parametry_analityczne)
PARAM_IDS = {}  # filled at runtime


def _get_param_id(db, kod):
    if kod not in PARAM_IDS:
        row = db.execute("SELECT id FROM parametry_analityczne WHERE kod=?", (kod,)).fetchone()
        PARAM_IDS[kod] = row[0] if row else None
    return PARAM_IDS[kod]


def _get_or_create_etap(db, kod, nazwa, typ_cyklu, kolejnosc_domyslna):
    row = db.execute("SELECT id FROM etapy_analityczne WHERE kod=?", (kod,)).fetchone()
    if row:
        return row[0]
    return create_etap(db, kod=kod, nazwa=nazwa, typ_cyklu=typ_cyklu,
                       kolejnosc_domyslna=kolejnosc_domyslna)


def setup(db):
    stats = {"etapy": 0, "params": 0, "warunki": 0, "korekty": 0, "formuly": 0, "pipeline": 0, "limity": 0}

    # ── 1. Ensure sulfonowanie etap exists ──
    sulf_id = _get_or_create_etap(db, "sulfonowanie", "Sulfonowanie", "jednorazowy", 4)

    # Add params to sulfonowanie (if not already)
    sulf_params = [("so3", 1), ("ph_10proc", 2), ("nd20", 3), ("barwa_I2", 4)]
    existing = {p["kod"] for p in list_etap_parametry(db, sulf_id)}
    for kod, kol in sulf_params:
        pid = _get_param_id(db, kod)
        if pid and kod not in existing:
            add_etap_parametr(db, sulf_id, pid, kolejnosc=kol)
            stats["params"] += 1

    # ── 2. Configure utlenienie etap ──
    utl_id = db.execute("SELECT id FROM etapy_analityczne WHERE kod='utlenienie'").fetchone()[0]

    # Add params (so3, h2o2/nadtlenki, ph_10proc, nd20, barwa)
    utl_params = [("so3", 1), ("nadtlenki", 2), ("ph_10proc", 3), ("nd20", 4), ("barwa_I2", 5)]
    existing = {p["kod"] for p in list_etap_parametry(db, utl_id)}
    for kod, kol in utl_params:
        pid = _get_param_id(db, kod)
        if pid and kod not in existing:
            add_etap_parametr(db, utl_id, pid, kolejnosc=kol)
            stats["params"] += 1

    # Gate: SO3 <= target (target set per product in produkt_etap_limity)
    if not list_etap_warunki(db, utl_id):
        so3_pid = _get_param_id(db, "so3")
        if so3_pid:
            add_etap_warunek(db, utl_id, so3_pid, "<=", 0.1,
                             opis_warunku="SO₃²⁻ poniżej celu")
            stats["warunki"] += 1

    # Correction: Perhydrol with formula
    utl_korekty = list_etap_korekty(db, utl_id)
    perh_exists = any(k["substancja"] == "Perhydrol 34%" for k in utl_korekty)
    if not perh_exists:
        kid = add_etap_korekta(db, utl_id, "Perhydrol 34%", "kg", "produkcja", kolejnosc=1)
        stats["korekty"] += 1
    else:
        kid = next(k["id"] for k in utl_korekty if k["substancja"] == "Perhydrol 34%")

    # Set formula on perhydrol correction
    formula = "(C_so3 - target_so3) * 0.01214 * Meff + (target_nadtlenki > 0 ? target_nadtlenki * Meff / 350 : 0)"
    zmienne = json.dumps({
        "C_so3": "pomiar:so3",
        "target_so3": "target:so3",
        "target_nadtlenki": "target:nadtlenki",
        "Meff": "wielkosc_szarzy_kg > 6600 ? wielkosc_szarzy_kg - 1000 : wielkosc_szarzy_kg - 500",
    })
    db.execute("UPDATE etap_korekty_katalog SET formula_ilosc=?, formula_zmienne=? WHERE id=?",
               (formula, zmienne, kid))
    stats["formuly"] += 1

    # ── 3. Standaryzacja formulas ──
    stand_id = db.execute("SELECT id FROM etapy_analityczne WHERE kod='standaryzacja'").fetchone()[0]
    stand_korekty = list_etap_korekty(db, stand_id)

    # Woda formula
    woda_k = next((k for k in stand_korekty if k["substancja"] == "Woda"), None)
    if woda_k:
        formula_woda = "(R0 - Rk) * Meff / (Rk - 1.333)"
        zmienne_woda = json.dumps({
            "R0": "pomiar:nd20",
            "Rk": "target:nd20",
            "Meff": "wielkosc_szarzy_kg > 6600 ? wielkosc_szarzy_kg - 1000 : wielkosc_szarzy_kg - 500",
        })
        db.execute("UPDATE etap_korekty_katalog SET formula_ilosc=?, formula_zmienne=? WHERE id=?",
                   (formula_woda, zmienne_woda, woda_k["id"]))
        stats["formuly"] += 1

    # NaCl formula
    nacl_k = next((k for k in stand_korekty if k["substancja"] == "NaCl"), None)
    if nacl_k:
        formula_nacl = "(Ck / 100 * Meff - Meff * Ccl / 100) / (1 - Ck / 100)"
        zmienne_nacl = json.dumps({
            "Ccl": "pomiar:nacl",
            "Ck": "target:nacl",
            "Meff": "wielkosc_szarzy_kg > 6600 ? wielkosc_szarzy_kg - 1000 : wielkosc_szarzy_kg - 500",
        })
        db.execute("UPDATE etap_korekty_katalog SET formula_ilosc=?, formula_zmienne=? WHERE id=?",
                   (formula_nacl, zmienne_nacl, nacl_k["id"]))
        stats["formuly"] += 1

    db.commit()

    # ── 4. Update pipelines ──
    ak_id = db.execute("SELECT id FROM etapy_analityczne WHERE kod='analiza_koncowa'").fetchone()[0]

    for produkt in PRODUCTS:
        pipe = get_produkt_pipeline(db, produkt)
        kody = [p["kod"] for p in pipe]

        # Ensure order: sulfonowanie(1) → utlenienie(2) → standaryzacja(3) → analiza_koncowa(4)
        if "sulfonowanie" not in kody:
            set_produkt_pipeline(db, produkt, sulf_id, kolejnosc=1)
            stats["pipeline"] += 1
        if "utlenienie" not in kody:
            set_produkt_pipeline(db, produkt, utl_id, kolejnosc=2)
        # Reorder existing
        set_produkt_pipeline(db, produkt, sulf_id, kolejnosc=1)
        set_produkt_pipeline(db, produkt, utl_id, kolejnosc=2)
        set_produkt_pipeline(db, produkt, stand_id, kolejnosc=3)
        if "analiza_koncowa" in kody:
            set_produkt_pipeline(db, produkt, ak_id, kolejnosc=4)

        # ── 5. Product-specific limits + targets ──
        # Sulfonowanie: SO3 limits per product (no target, just measurement)
        set_produkt_etap_limit(db, produkt, sulf_id, _get_param_id(db, "so3"))
        set_produkt_etap_limit(db, produkt, sulf_id, _get_param_id(db, "ph_10proc"))
        set_produkt_etap_limit(db, produkt, sulf_id, _get_param_id(db, "nd20"))
        set_produkt_etap_limit(db, produkt, sulf_id, _get_param_id(db, "barwa_I2"))

        # Utlenienie: SO3 + nadtlenki with targets
        set_produkt_etap_limit(db, produkt, utl_id, _get_param_id(db, "so3"),
                               max_limit=0.1, target=0.03)
        set_produkt_etap_limit(db, produkt, utl_id, _get_param_id(db, "nadtlenki"),
                               max_limit=0.01, target=0.005)
        set_produkt_etap_limit(db, produkt, utl_id, _get_param_id(db, "ph_10proc"))
        set_produkt_etap_limit(db, produkt, utl_id, _get_param_id(db, "nd20"))
        set_produkt_etap_limit(db, produkt, utl_id, _get_param_id(db, "barwa_I2"))

        # Standaryzacja: ensure targets for nd20 and nacl (for formulas)
        # nd20 target per product (Rk)
        nd20_targets = {
            "Chegina_K40GLOL": 1.4070, "Chegina_K40GLO": 1.4070,
            "Chegina_K40GL": 1.4070, "Chegina_K7": 1.3922,
        }
        nacl_targets = {
            "Chegina_K40GLOL": 6.5, "Chegina_K40GLO": 6.5,
            "Chegina_K40GL": 6.5, "Chegina_K7": 6.0,
        }
        if produkt in nd20_targets:
            set_produkt_etap_limit(db, produkt, stand_id, _get_param_id(db, "nd20"),
                                   target=nd20_targets[produkt])
        if produkt in nacl_targets:
            set_produkt_etap_limit(db, produkt, stand_id, _get_param_id(db, "nacl"),
                                   target=nacl_targets[produkt])

        stats["limity"] += 1

    db.commit()
    return stats


if __name__ == "__main__":
    db = get_db()
    init_mbr_tables(db)
    stats = setup(db)
    print(json.dumps(stats, indent=2))

    for p in PRODUCTS:
        pipe = get_produkt_pipeline(db, p)
        print(f"{p}: {' → '.join(s['kod'] for s in pipe)}")

    # Show formulas
    for kod in ["utlenienie", "standaryzacja"]:
        eid = db.execute("SELECT id FROM etapy_analityczne WHERE kod=?", (kod,)).fetchone()[0]
        korekty = list_etap_korekty(db, eid)
        for k in korekty:
            if k["formula_ilosc"]:
                print(f"  {kod}/{k['substancja']}: {k['formula_ilosc']}")

    db.close()
```

- [ ] **Step 2: Run setup script**

```bash
python -m scripts.setup_sulfonowanie_utlenienie
```

Verify output shows correct pipeline and formulas.

- [ ] **Step 3: Run tests**

```bash
pytest --tb=short -q
```

- [ ] **Step 4: Commit**

```bash
git add scripts/setup_sulfonowanie_utlenienie.py
git commit -m "feat: setup sulfonowanie/utlenienie stages with perhydrol/woda/NaCl formulas"
```

---

## Task 2: Formula evaluation in correction panel

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Add formula evaluator function**

Add before `loadCorrectionPanel` function:

```javascript
function evalCorrectionFormula(formulaStr, sekcja, korekta) {
    // Collect variables for formula
    var nastaw = ebrNastaw || 0;
    var Meff = nastaw > 6600 ? nastaw - 1000 : nastaw - 500;
    if (Meff <= 0) return null;

    // Parse formula_zmienne to understand what we need
    var zmienne = {};
    try { zmienne = JSON.parse(korekta.formula_zmienne || '{}'); } catch(e) {}

    // Build variable map from pomiary + targets + batch size
    var vars = { Meff: Meff, wielkosc_szarzy_kg: nastaw };

    // Collect all pomiary from current section's wyniki
    var baseSekcja = sekcja.split('__')[0];
    // Find latest round wyniki
    var latestWyniki = {};
    if (baseSekcja === 'analiza' && roundState) {
        var lastN = roundState.last_analiza || 1;
        latestWyniki = wyniki['analiza__' + lastN] || wyniki[sekcja] || {};
    } else {
        latestWyniki = wyniki[sekcja] || wyniki[baseSekcja] || {};
    }

    // Map pomiar:kod → value
    Object.keys(latestWyniki).forEach(function(kod) {
        var w = latestWyniki[kod];
        if (w && w.wartosc != null) {
            vars['C_' + kod] = w.wartosc;
            vars[kod] = w.wartosc;
        }
    });

    // Map target:kod → value from pola
    var activeEtap = etapy.find(function(e) { return e.sekcja_lab === baseSekcja; });
    var sekKey = activeEtap ? (activeEtap.typ_cyklu === 'cykliczny' && baseSekcja === 'analiza' ? 'analiza' : baseSekcja) : baseSekcja;
    var pola = (parametry[sekKey] || {}).pola || [];
    pola.forEach(function(p) {
        if (p.target != null) {
            vars['target_' + p.kod] = p.target;
        }
    });

    // Also check utlenienie pola if we're in utlenienie context
    // (adapter maps utlenienie as non-main cykliczny)
    ['utlenienie', 'analiza'].forEach(function(sek) {
        var sekPola = (parametry[sek] || {}).pola || [];
        sekPola.forEach(function(p) {
            if (p.target != null && !vars['target_' + p.kod]) {
                vars['target_' + p.kod] = p.target;
            }
        });
    });

    // Map R0 = nd20, Rk = target nd20 (convenience aliases)
    if (vars.nd20 != null) vars.R0 = vars.nd20;
    if (vars.target_nd20 != null) vars.Rk = vars.target_nd20;
    if (vars.nacl != null) vars.Ccl = vars.nacl;
    if (vars.target_nacl != null) vars.Ck = vars.target_nacl;
    if (vars.so3 != null) vars.C_so3 = vars.so3;
    if (vars.target_so3 == null) vars.target_so3 = 0;
    if (vars.target_nadtlenki == null) vars.target_nadtlenki = 0;

    try {
        var keys = Object.keys(vars);
        var vals = keys.map(function(k) { return vars[k]; });
        var fn = new Function(keys.join(','), 'return ' + formulaStr);
        var result = fn.apply(null, vals);
        if (isNaN(result) || !isFinite(result) || result < 0) return null;
        return Math.round(result * 100) / 100;
    } catch(e) {
        return null;
    }
}
```

- [ ] **Step 2: Modify loadCorrectionPanel to use formula**

In `loadCorrectionPanel` function, find the line that builds each correction input:

```javascript
        '<input type="number" step="any" class="pa-input" data-korekta-id="' + k.id + '" placeholder="Ilość" style="width:80px;font-size:11px;text-align:center;">' +
```

Replace with formula-aware version. The full correction row becomes:

Find the `korekty.forEach` loop in `loadCorrectionPanel` and replace it:

```javascript
        korekty.forEach(function(k) {
            var preCalc = '';
            var preVal = '';
            if (k.formula_ilosc) {
                var calc = evalCorrectionFormula(k.formula_ilosc, sekcja, k);
                if (calc !== null) {
                    preVal = calc.toFixed(1);
                    preCalc = '<div style="font-size:9px;color:var(--teal);margin-top:2px;">obliczono: ' + preVal.replace('.', ',') + ' ' + (k.jednostka || 'kg') + '</div>';
                }
            }
            html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;font-size:12px;">' +
                '<span style="min-width:120px;font-weight:500;">' + (k.substancja || '') + '</span>' +
                '<span style="color:var(--text-dim);font-size:10px;">[' + (k.jednostka || 'kg') + ']</span>' +
                '<span class="pa-badge" style="font-size:8px;">' + (k.wykonawca || '') + '</span>' +
                '<div><input type="number" step="any" class="pa-input" data-korekta-id="' + k.id + '" ' +
                  'value="' + preVal + '" placeholder="Ilość" ' +
                  'style="width:80px;font-size:11px;text-align:center;">' +
                preCalc + '</div>' +
            '</div>';
        });
```

- [ ] **Step 3: Run tests**

```bash
pytest --tb=short -q
```

- [ ] **Step 4: Manual test**

Open K7 batch, navigate to utlenienie, enter SO3 = 0.15. After save, gate should fail, correction panel should show Perhydrol with pre-calculated amount.

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: auto-calculate correction amounts from formulas (perhydrol, woda, NaCl)"
```

---

## Task 3: Unlock param editor for all pipeline sections

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Change editBtn condition in renderOneSection**

Find line 2360:
```javascript
    if (sekcja === 'analiza_koncowa' && userRola !== 'cert' && !isReadonly) {
        editBtn = '<button class="sec-edit-btn" onclick="openParamEditor()" title="Edytuj parametry">' +
```

Replace with:
```javascript
    var baseSekcja = sekcja.split('__')[0];
    var isPipelineSection = etapy.some(function(e) { return e.pipeline_etap_id; });
    if ((sekcja === 'analiza_koncowa' || isPipelineSection) && userRola !== 'cert' && !isReadonly) {
        var editorKontekst = baseSekcja === 'analiza' ? 'analiza_koncowa' : baseSekcja;
        editBtn = '<button class="sec-edit-btn" onclick="openParamEditor(\'' + editorKontekst + '\')" title="Edytuj parametry">' +
```

- [ ] **Step 2: Add kontekst parameter to openParamEditor**

Find `function openParamEditor()` at line 4345. Change to accept kontekst parameter:

```javascript
function openParamEditor(kontekst) {
  kontekst = kontekst || 'analiza_koncowa';
  window._peEditKontekst = kontekst;
  // Fetch current bindings + all available params in parallel
  Promise.all([
    fetch('/api/parametry/etapy/' + encodeURIComponent(window._batchProdukt) + '/' + encodeURIComponent(kontekst)).then(function(r){return r.json();}),
    fetch('/api/parametry/available').then(function(r){return r.json();})
  ]).then(function(results) {
```

- [ ] **Step 3: Update save binding calls to use kontekst**

In the param editor save/add/delete functions, find references to `'analiza_koncowa'` and replace with `window._peEditKontekst || 'analiza_koncowa'`.

Find the `fetch('/api/parametry/etapy'` POST call (around line 4499-4520) that creates new bindings:

```javascript
    fetch('/api/parametry/etapy', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({...produkt: window._batchProdukt})
```

Add kontekst to the body:
```javascript
        body: JSON.stringify({parametr_id: ..., kontekst: window._peEditKontekst || 'analiza_koncowa', produkt: window._batchProdukt, ...})
```

Find all similar hardcoded `'analiza_koncowa'` references in the param editor section and replace with `window._peEditKontekst || 'analiza_koncowa'`.

- [ ] **Step 4: Run tests**

```bash
pytest --tb=short -q
```

- [ ] **Step 5: Manual test**

Open K7 batch, click pencil on utlenienie section. Verify:
- Editor opens with utlenienie params (SO3, nadtlenki, etc.)
- Can add/remove params
- Changes persist on reload

- [ ] **Step 6: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: param editor unlocked for all pipeline sections, not just analiza_koncowa"
```

---

## Task 4: Run setup + E2E verification

- [ ] **Step 1: Run setup script**

```bash
python -m scripts.setup_sulfonowanie_utlenienie
```

- [ ] **Step 2: Verify pipeline in admin**

Open `/admin/pipeline/produkt/Chegina_K7` — should show: sulfonowanie → utlenienie → standaryzacja → analiza_koncowa

- [ ] **Step 3: Test full flow in browser**

On K7 batch:
1. Sulfonowanie: enter SO3 value → save → no gate (jednorazowy, informational)
2. Click "Zatwierdź etap" → move to utlenienie
3. Utlenienie: enter SO3 = 0.15 → gate fail → correction panel with Perhydrol pre-calculated
4. Enter correction amount → "Zaleć korektę" → "Nowa runda"
5. Enter SO3 = 0.03 → gate pass → "Zatwierdź etap" → move to standaryzacja
6. Standaryzacja: enter SM, nD20, NaCl → gate fail → woda/NaCl pre-calculated
7. Click pencil on standaryzacja → edit params → verify changes persist

- [ ] **Step 4: Run full test suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix: sulfonowanie/utlenienie e2e fixes"
```

---

## Summary

| Task | What | Files |
|------|------|------|
| 1 | Setup stages + formulas in DB | `scripts/setup_sulfonowanie_utlenienie.py` |
| 2 | Formula eval in correction panel | `_fast_entry_content.html` |
| 3 | Param editor for all sections | `_fast_entry_content.html` |
| 4 | E2E verification | Manual testing |
