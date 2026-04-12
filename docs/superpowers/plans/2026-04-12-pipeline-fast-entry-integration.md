# Pipeline → Fast Entry Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate pipeline data into the existing fast_entry view via a server-side adapter, revert the broken fast_entry_v2, and add dual-write + gate evaluation to the save flow.

**Architecture:** Server-side adapter function transforms pipeline tables (etapy_analityczne, etap_parametry, resolve_limity) into the `etapy_json` + `parametry_lab` format that the existing 192KB `_fast_entry_content.html` template already consumes. No template changes in Phase 1. Dual-write in save_entry persists to both ebr_wyniki (existing) and ebr_pomiar (pipeline/ML). Gate evaluation returns in save response for future JS consumption.

**Tech Stack:** Flask/Jinja2, SQLite (raw sqlite3), existing vanilla JS in `_fast_entry_content.html`

---

## File Structure

### Files to create:
```
mbr/pipeline/adapter.py          — build_pipeline_context(): pipeline → parametry_lab + etapy_json
tests/test_pipeline_adapter.py   — adapter unit tests
```

### Files to modify:
```
mbr/laborant/routes.py           — revert fast_entry redirect, integrate adapter in fast_entry_partial, add dual-write in save_entry
mbr/templates/laborant/szarze_list.html — revert loadBatch to AJAX partial
```

### Files to delete:
```
mbr/templates/pipeline/fast_entry_v2.html
mbr/templates/pipeline/_fast_entry_v2_content.html
```

### Files to modify (cleanup):
```
mbr/pipeline/lab_routes.py       — remove page routes (keep API routes)
```

---

## Task 1: Revert fast_entry and loadBatch redirects

**Files:**
- Modify: `mbr/laborant/routes.py` (lines 162-165)
- Modify: `mbr/templates/laborant/szarze_list.html` (lines 605-608)

- [ ] **Step 1: Revert fast_entry route**

In `mbr/laborant/routes.py`, replace lines 162-165:

```python
# CURRENT (broken redirect):
@laborant_bp.route("/laborant/ebr/<int:ebr_id>")
@login_required
def fast_entry(ebr_id):
    return redirect(url_for("pipeline.fast_entry_v2", ebr_id=ebr_id))
```

With the original implementation:

```python
@laborant_bp.route("/laborant/ebr/<int:ebr_id>")
@login_required
def fast_entry(ebr_id):
    from mbr.registry.models import list_completed_products
    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        if ebr is None:
            return "Nie znaleziono szarzy", 404
        batches = list_ebr_open(db)
        recent = list_ebr_recent(db, days=7)
        completed_products = list_completed_products(db)
    return render_template("laborant/szarze_list.html", batches=batches, recent=recent,
                           products=PRODUCTS, completed_products=completed_products)
```

- [ ] **Step 2: Revert loadBatch in szarze_list.html**

In `mbr/templates/laborant/szarze_list.html`, replace lines 605-618 (the redirect + unreachable legacy code start):

```javascript
// CURRENT:
async function loadBatch(ebrId) {
  // Redirect to pipeline fast entry v2
  window.location.href = `/laborant/pipeline/ebr/${ebrId}`;
  return;

  // --- Legacy code below (kept for reference, unreachable) ---
  // Cleanup + race condition guard
  const gen = ++_loadGen;
  if (_heroObserver) { _heroObserver.disconnect(); _heroObserver = null; }

  const resp = await fetch(`/laborant/ebr/${ebrId}/partial`);
```

With original (remove the redirect + return + comment lines):

```javascript
async function loadBatch(ebrId) {
  // Cleanup + race condition guard
  const gen = ++_loadGen;
  if (_heroObserver) { _heroObserver.disconnect(); _heroObserver = null; }

  const resp = await fetch(`/laborant/ebr/${ebrId}/partial`);
```

- [ ] **Step 3: Verify fast_entry works again**

```bash
pytest --tb=short -q
```

Then manually test: open http://localhost:5001/laborant/szarze, click a batch, verify the old fast entry loads correctly with calculator, auto-save, etc.

- [ ] **Step 4: Commit**

```bash
git add mbr/laborant/routes.py mbr/templates/laborant/szarze_list.html
git commit -m "revert: restore original fast_entry and loadBatch (remove broken redirect)"
```

---

## Task 2: Remove fast_entry_v2 templates and page routes

**Files:**
- Delete: `mbr/templates/pipeline/fast_entry_v2.html`
- Delete: `mbr/templates/pipeline/_fast_entry_v2_content.html`
- Modify: `mbr/pipeline/lab_routes.py` (remove lines 20-29)

- [ ] **Step 1: Delete v2 templates**

```bash
rm mbr/templates/pipeline/fast_entry_v2.html
rm mbr/templates/pipeline/_fast_entry_v2_content.html
```

- [ ] **Step 2: Remove page routes from lab_routes.py**

In `mbr/pipeline/lab_routes.py`, remove the two page route functions (fast_entry_v2 and fast_entry_v2_partial at lines 20-29). Keep ALL API routes (everything under `/api/pipeline/lab/`).

Find and remove:
```python
@pipeline_bp.route("/laborant/pipeline/ebr/<int:ebr_id>")
@login_required
def fast_entry_v2(ebr_id):
    return render_template("pipeline/fast_entry_v2.html", ebr_id=ebr_id)


@pipeline_bp.route("/laborant/pipeline/ebr/<int:ebr_id>/partial/<int:etap_id>")
@login_required
def fast_entry_v2_partial(ebr_id, etap_id):
    return render_template("pipeline/_fast_entry_v2_content.html", ebr_id=ebr_id, etap_id=etap_id)
```

Also remove the `render_template` import if it was only used by these routes (check if other routes in the file use it).

- [ ] **Step 3: Run tests — fix any that reference deleted routes**

```bash
pytest --tb=short -q
```

If tests reference `pipeline.fast_entry_v2` endpoint, remove those specific test cases.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "cleanup: remove broken fast_entry_v2 templates and page routes"
```

---

## Task 3: Build pipeline adapter — `build_pipeline_context()`

**Files:**
- Create: `mbr/pipeline/adapter.py`
- Create: `tests/test_pipeline_adapter.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_pipeline_adapter.py
import sqlite3
import json
import pytest
from mbr.models import init_mbr_tables
from mbr.pipeline.models import (
    create_etap, add_etap_parametr, set_produkt_pipeline,
    add_etap_warunek, add_etap_korekta,
    set_produkt_etap_limit,
)
from mbr.pipeline.adapter import build_pipeline_context


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed_params(db):
    """Seed analytical parameters matching real system."""
    db.execute("INSERT OR IGNORE INTO parametry_analityczne (id, kod, label, typ, skrot, precision, metoda_id) VALUES (9101, 'sm', 'Sucha masa', 'bezposredni', 'SM', 1, NULL)")
    db.execute("INSERT OR IGNORE INTO parametry_analityczne (id, kod, label, typ, skrot, precision, metoda_id, metoda_nazwa, metoda_formula, metoda_factor) VALUES (9102, 'nacl', 'Chlorek sodu', 'titracja', 'NaCl', 2, NULL, 'Argentometryczna Mohr', '%% = (V * 0.00585 * 100) / m', 0.585)")
    db.execute("INSERT OR IGNORE INTO parametry_analityczne (id, kod, label, typ, skrot, precision, formula) VALUES (9103, 'sa', 'Substancja aktywna', 'obliczeniowy', 'SA', 2, 'sm - nacl - 0.6')")
    db.execute("INSERT OR IGNORE INTO parametry_analityczne (id, kod, label, typ, skrot, precision) VALUES (9104, 'ph_10proc', 'pH roztworu 10%%', 'bezposredni', 'pH 10%%', 2)")


def _setup_pipeline(db):
    """Create a standaryzacja pipeline for TestProd."""
    _seed_params(db)

    e1 = create_etap(db, kod="standaryzacja", nazwa="Standaryzacja", typ_cyklu="cykliczny")
    add_etap_parametr(db, e1, 9101, kolejnosc=1)  # sm
    add_etap_parametr(db, e1, 9102, kolejnosc=2, nawazka_g=2.0)  # nacl (titracja)
    add_etap_parametr(db, e1, 9103, kolejnosc=3, formula="sm - nacl - 0.6")  # sa (obliczeniowy)
    add_etap_parametr(db, e1, 9104, kolejnosc=4)  # ph

    add_etap_warunek(db, e1, 9101, "between", 44.0, wartosc_max=48.0, opis_warunku="SM w zakresie")
    add_etap_korekta(db, e1, "Woda", "kg", "produkcja", kolejnosc=1)
    add_etap_korekta(db, e1, "NaCl", "kg", "produkcja", kolejnosc=2)

    set_produkt_pipeline(db, "TestProd", e1, kolejnosc=1)
    set_produkt_etap_limit(db, "TestProd", e1, 9101, min_limit=44.0, max_limit=48.0, target=46.0)
    set_produkt_etap_limit(db, "TestProd", e1, 9102, min_limit=5.8, max_limit=7.3)

    db.commit()
    return e1


def test_build_returns_etapy_and_parametry(db):
    _setup_pipeline(db)
    ctx = build_pipeline_context(db, "TestProd")
    assert "etapy_json" in ctx
    assert "parametry_lab" in ctx


def test_etapy_json_structure(db):
    _setup_pipeline(db)
    ctx = build_pipeline_context(db, "TestProd")
    etapy = ctx["etapy_json"]
    assert len(etapy) >= 1
    st = etapy[0]
    assert st["nazwa"] == "Standaryzacja"
    assert st["sekcja_lab"] == "standaryzacja"
    assert st["read_only"] is False


def test_cykliczny_generates_dodatki_stage(db):
    _setup_pipeline(db)
    ctx = build_pipeline_context(db, "TestProd")
    etapy = ctx["etapy_json"]
    sekcje = [e["sekcja_lab"] for e in etapy]
    assert "standaryzacja" in sekcje
    assert "dodatki" in sekcje  # cykliczny etap generuje sekcje dodatki


def test_parametry_lab_has_sekcja(db):
    _setup_pipeline(db)
    ctx = build_pipeline_context(db, "TestProd")
    plab = ctx["parametry_lab"]
    assert "standaryzacja" in plab or "analiza" in plab
    # Check it has pola
    main_sekcja = plab.get("standaryzacja") or plab.get("analiza")
    assert "pola" in main_sekcja
    assert len(main_sekcja["pola"]) >= 3


def test_parametry_lab_pole_format(db):
    _setup_pipeline(db)
    ctx = build_pipeline_context(db, "TestProd")
    plab = ctx["parametry_lab"]
    main_sekcja = plab.get("standaryzacja") or plab.get("analiza")
    sm_pole = next(p for p in main_sekcja["pola"] if p["kod"] == "sm")
    assert sm_pole["label"] is not None
    assert sm_pole["tag"] == "sm"
    assert sm_pole["typ"] == "float"
    assert sm_pole["min"] == 44.0  # from produkt_etap_limity
    assert sm_pole["max"] == 48.0
    assert sm_pole["precision"] == 1
    assert sm_pole["measurement_type"] == "bezp"
    assert sm_pole.get("target") == 46.0


def test_titracja_has_calc_method(db):
    _setup_pipeline(db)
    ctx = build_pipeline_context(db, "TestProd")
    plab = ctx["parametry_lab"]
    main_sekcja = plab.get("standaryzacja") or plab.get("analiza")
    nacl_pole = next(p for p in main_sekcja["pola"] if p["kod"] == "nacl")
    assert nacl_pole["measurement_type"] == "titracja"
    assert "calc_method" in nacl_pole
    assert nacl_pole["calc_method"]["factor"] == 0.585
    assert nacl_pole["calc_method"]["suggested_mass"] == 2.0


def test_obliczeniowy_has_formula(db):
    _setup_pipeline(db)
    ctx = build_pipeline_context(db, "TestProd")
    plab = ctx["parametry_lab"]
    main_sekcja = plab.get("standaryzacja") or plab.get("analiza")
    sa_pole = next(p for p in main_sekcja["pola"] if p["kod"] == "sa")
    assert sa_pole["measurement_type"] == "obliczeniowy"
    assert sa_pole["formula"] == "sm - nacl - 0.6"


def test_dodatki_sekcja_from_korekty(db):
    _setup_pipeline(db)
    ctx = build_pipeline_context(db, "TestProd")
    plab = ctx["parametry_lab"]
    assert "dodatki" in plab
    dodatki_pola = plab["dodatki"]["pola"]
    substancje = [p["kod"] for p in dodatki_pola]
    assert "korekta_woda" in substancje
    assert "korekta_nacl" in substancje


def test_empty_pipeline_returns_none(db):
    _seed_params(db)
    ctx = build_pipeline_context(db, "NoPipelineProd")
    assert ctx is None


def test_jednorazowy_no_dodatki(db):
    """jednorazowy stage should not generate a dodatki section."""
    _seed_params(db)
    e1 = create_etap(db, kod="analiza_koncowa_v2", nazwa="Analiza koncowa", typ_cyklu="jednorazowy")
    add_etap_parametr(db, e1, 9101, kolejnosc=1)
    set_produkt_pipeline(db, "SimpleProd", e1, kolejnosc=1)
    db.commit()

    ctx = build_pipeline_context(db, "SimpleProd")
    etapy = ctx["etapy_json"]
    sekcje = [e["sekcja_lab"] for e in etapy]
    assert "dodatki" not in sekcje
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pipeline_adapter.py -v
```
Expected: ImportError — adapter.py doesn't exist yet.

- [ ] **Step 3: Implement adapter**

```python
# mbr/pipeline/adapter.py
"""
Adapter: transform pipeline tables into the parametry_lab + etapy_json
format that the existing _fast_entry_content.html template consumes.

This is the bridge between the new normalized pipeline model and the
legacy JSON-blob-based fast_entry rendering.
"""
import sqlite3
from mbr.pipeline.models import (
    get_produkt_pipeline, resolve_limity, list_etap_korekty, get_etap,
)

TYP_MAP = {
    "bezposredni": "bezp",
    "titracja": "titracja",
    "obliczeniowy": "obliczeniowy",
    "binarny": "binarny",
    "jakosciowy": "bezp",
}


def build_pipeline_context(db: sqlite3.Connection, produkt: str) -> dict | None:
    """Build etapy_json + parametry_lab from pipeline tables.

    Returns None if product has no pipeline defined.
    Returns dict with keys 'etapy_json' and 'parametry_lab'.
    """
    pipeline = get_produkt_pipeline(db, produkt)
    if not pipeline:
        return None

    etapy_json = []
    parametry_lab = {}

    for step in pipeline:
        etap = get_etap(db, step["etap_id"])
        if not etap:
            continue

        kod = etap["kod"]
        nazwa = etap["nazwa"]
        typ_cyklu = etap["typ_cyklu"]

        etapy_json.append({
            "nr": step["kolejnosc"],
            "nazwa": nazwa,
            "read_only": False,
            "sekcja_lab": kod if typ_cyklu == "jednorazowy" else "analiza",
            "pipeline_etap_id": step["etap_id"],
            "typ_cyklu": typ_cyklu,
        })

        resolved = resolve_limity(db, produkt, step["etap_id"])
        pola = [_build_pole(db, r) for r in resolved]

        if typ_cyklu == "cykliczny":
            parametry_lab["analiza"] = {
                "label": nazwa,
                "pola": pola,
            }

            korekty = list_etap_korekty(db, step["etap_id"])
            if korekty:
                dodatki_pola = []
                for k in korekty:
                    safe_kod = "korekta_" + k["substancja"].lower().replace(" ", "_")
                    dodatki_pola.append({
                        "kod": safe_kod,
                        "label": f"{k['substancja']} [{k['jednostka']}]",
                        "skrot": k["substancja"],
                        "tag": safe_kod,
                        "typ": "float",
                        "measurement_type": "bezp",
                        "min": 0,
                        "max": None,
                        "min_limit": 0,
                        "max_limit": None,
                        "precision": 1,
                        "grupa": "lab",
                    })
                parametry_lab["dodatki"] = {
                    "label": "Dodatki standaryzacyjne",
                    "pola": dodatki_pola,
                }
                etapy_json.append({
                    "nr": step["kolejnosc"] + 0.5,
                    "nazwa": "Dodatki standaryzacyjne",
                    "read_only": False,
                    "sekcja_lab": "dodatki",
                })
        else:
            sekcja_key = kod
            parametry_lab[sekcja_key] = {
                "label": nazwa,
                "pola": pola,
            }

    if not etapy_json:
        return None

    etapy_json.sort(key=lambda e: e["nr"])

    return {
        "etapy_json": etapy_json,
        "parametry_lab": parametry_lab,
    }


def _build_pole(db: sqlite3.Connection, r: dict) -> dict:
    """Transform a resolved-limit row into a pole dict for parametry_lab."""
    measurement_type = TYP_MAP.get(r["typ"], "bezp")

    pole = {
        "kod": r["kod"],
        "label": r["skrot"] or r["label"],
        "skrot": r["skrot"],
        "tag": r["kod"],
        "typ": "float",
        "measurement_type": measurement_type,
        "min": r["min_limit"],
        "max": r["max_limit"],
        "min_limit": r["min_limit"],
        "max_limit": r["max_limit"],
        "precision": r["precision"] or 2,
        "grupa": r["grupa"] or "lab",
    }

    if r.get("target") is not None:
        pole["target"] = r["target"]

    if r.get("nawazka_g") is not None:
        pole["nawazka_g"] = r["nawazka_g"]

    if r.get("jednostka"):
        pole["jednostka"] = r["jednostka"]

    if measurement_type == "titracja" and r.get("parametr_id"):
        metoda = db.execute(
            """SELECT pa.metoda_nazwa, pa.metoda_formula, pa.metoda_factor, pa.metoda_id
               FROM parametry_analityczne pa WHERE pa.id = ?""",
            (r["parametr_id"],),
        ).fetchone()
        if metoda and metoda["metoda_factor"] is not None:
            pole["metoda_id"] = metoda["metoda_id"]
            pole["calc_method"] = {
                "name": metoda["metoda_nazwa"],
                "formula": metoda["metoda_formula"],
                "factor": metoda["metoda_factor"],
                "suggested_mass": r.get("nawazka_g"),
            }

    if measurement_type == "obliczeniowy":
        formula = r.get("formula")
        if not formula:
            pa = db.execute(
                "SELECT formula FROM parametry_analityczne WHERE id = ?",
                (r["parametr_id"],),
            ).fetchone()
            if pa:
                formula = pa["formula"]
        if formula and r.get("sa_bias") is not None and "sa_bias" in formula:
            formula = formula.replace("sa_bias", str(r["sa_bias"]))
        if formula:
            pole["formula"] = formula

    return pole
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_pipeline_adapter.py -v
```
Expected: all PASS.

- [ ] **Step 5: Run full suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 6: Commit**

```bash
git add mbr/pipeline/adapter.py tests/test_pipeline_adapter.py
git commit -m "feat: pipeline adapter — transforms pipeline data to fast_entry format"
```

---

## Task 4: Integrate adapter into fast_entry_partial

**Files:**
- Modify: `mbr/laborant/routes.py` (function `fast_entry_partial`, lines 168-205)
- Test: `tests/test_pipeline_adapter.py` (append integration test)

- [ ] **Step 1: Write failing integration test**

Append to `tests/test_pipeline_adapter.py`:

```python
def test_adapter_output_compatible_with_save_wyniki(db):
    """Verify adapter output can be consumed by save_wyniki (pole lookup)."""
    _setup_pipeline(db)
    ctx = build_pipeline_context(db, "TestProd")
    parametry_lab = ctx["parametry_lab"]

    # Simulate what save_wyniki does: parse parametry_lab, find base_sekcja, get pola_map
    import json
    parametry = parametry_lab  # already a dict, not JSON string
    # For cyclic: sekcja="analiza__1" → base_sekcja="analiza"
    base_sekcja = "analiza"
    sekcja_def = parametry.get(base_sekcja, {})
    pola = sekcja_def.get("pola", [])
    pola_map = {p["kod"]: p for p in pola}

    assert "sm" in pola_map
    assert "nacl" in pola_map
    assert pola_map["sm"]["min"] == 44.0
    assert pola_map["sm"]["max"] == 48.0
```

- [ ] **Step 2: Modify fast_entry_partial**

In `mbr/laborant/routes.py`, in the `fast_entry_partial` function, add pipeline adapter call after `ebr = get_ebr(db, ebr_id)`:

```python
@laborant_bp.route("/laborant/ebr/<int:ebr_id>/partial")
@login_required
def fast_entry_partial(ebr_id):
    """Return just the fast-entry form HTML (no base.html shell) for AJAX loading."""
    from mbr.etapy_models import get_etapy_status, get_etap_analizy, get_korekty
    from mbr.parametry_registry import get_etapy_config
    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        if ebr is None:
            return "Nie znaleziono", 404

        # Pipeline adapter: if product has pipeline, override etapy_json + parametry_lab
        from mbr.pipeline.adapter import build_pipeline_context
        pipeline_ctx = build_pipeline_context(db, ebr["produkt"])
        if pipeline_ctx:
            ebr = dict(ebr)  # make mutable copy
            ebr["etapy_json"] = json.dumps(pipeline_ctx["etapy_json"])
            ebr["parametry_lab"] = json.dumps(pipeline_ctx["parametry_lab"])

        wyniki = get_ebr_wyniki(db, ebr_id)
        round_state = get_round_state(wyniki)
        # ... rest unchanged ...
```

Make sure `import json` is at the top of the file (check if it's already imported).

- [ ] **Step 3: Run tests**

```bash
pytest --tb=short -q
```

- [ ] **Step 4: Manual test in browser**

Start dev server, open a K7 or K40GLOL batch. Verify:
- Sidebar shows standaryzacja stage (not "Analiza końcowa")
- Parameter table shows SM, pH, NaCl, SA with correct limits
- Titration calculator works for NaCl (click the field)
- Auto-save works (type a value, blur)
- Computed fields work if SA is obliczeniowy

- [ ] **Step 5: Commit**

```bash
git add mbr/laborant/routes.py tests/test_pipeline_adapter.py
git commit -m "feat: integrate pipeline adapter into fast_entry_partial"
```

---

## Task 5: Add dual-write to save_entry

**Files:**
- Modify: `mbr/laborant/routes.py` (function `save_entry`, lines 208-261)
- Test: `tests/test_pipeline_adapter.py` (append dual-write test)

- [ ] **Step 1: Write failing test**

Append to `tests/test_pipeline_adapter.py`:

```python
from mbr.pipeline.models import (
    create_sesja, get_pomiary, list_sesje, evaluate_gate,
)


def test_dual_write_saves_to_ebr_pomiar(db):
    """When pipeline is active, save to ebr_pomiar alongside ebr_wyniki."""
    from mbr.pipeline.adapter import pipeline_dual_write

    _setup_pipeline(db)

    # Create MBR + EBR
    db.execute("INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia, parametry_lab, etapy_json) VALUES (1, 'TestProd', 1, '2026-01-01', '{}', '[]')")
    db.execute("INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start) VALUES (1, 1, 'T-1', '1/2026', '2026-01-01')")

    # Create pipeline session
    etap_id = db.execute("SELECT id FROM etapy_analityczne WHERE kod='standaryzacja'").fetchone()[0]
    sesja_id = create_sesja(db, 1, etap_id, runda=1, laborant="lab1")
    db.commit()

    # Dual write
    values = {"sm": 45.5, "nacl": 6.2}
    gate = pipeline_dual_write(db, ebr_id=1, sekcja="analiza__1", values=values, wpisal="lab1")

    # Verify ebr_pomiar has data
    pomiary = get_pomiary(db, sesja_id)
    kods = {p["kod"] for p in pomiary}
    assert "sm" in kods
    assert "nacl" in kods

    # Verify gate result
    assert gate is not None
    assert "passed" in gate


def test_dual_write_no_pipeline_returns_none(db):
    """When no pipeline, dual_write returns None."""
    from mbr.pipeline.adapter import pipeline_dual_write
    _seed_params(db)

    db.execute("INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia, parametry_lab, etapy_json) VALUES (1, 'NoPipe', 1, '2026-01-01', '{}', '[]')")
    db.execute("INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start) VALUES (1, 1, 'T-1', '1/2026', '2026-01-01')")
    db.commit()

    gate = pipeline_dual_write(db, ebr_id=1, sekcja="analiza_koncowa", values={"sm": 45.0}, wpisal="lab1")
    assert gate is None
```

- [ ] **Step 2: Implement pipeline_dual_write in adapter.py**

Append to `mbr/pipeline/adapter.py`:

```python
from mbr.pipeline.models import (
    list_sesje, save_pomiar, evaluate_gate, get_produkt_pipeline,
)


def pipeline_dual_write(db: sqlite3.Connection, ebr_id: int, sekcja: str,
                        values: dict, wpisal: str) -> dict | None:
    """Write measurements to ebr_pomiar and evaluate gate.

    Called after save_wyniki in save_entry route.
    Returns gate evaluation dict or None if no pipeline active.

    Args:
        sekcja: e.g. "analiza__1", "dodatki__1", "standaryzacja"
        values: {kod: wartosc} (already parsed floats)
    """
    # Get product from batch
    ebr = db.execute(
        """SELECT m.produkt FROM ebr_batches e
           JOIN mbr_templates m ON m.mbr_id = e.mbr_id
           WHERE e.ebr_id = ?""",
        (ebr_id,),
    ).fetchone()
    if not ebr:
        return None

    produkt = ebr["produkt"]
    pipeline = get_produkt_pipeline(db, produkt)
    if not pipeline:
        return None

    # Map sekcja to pipeline stage
    base_sekcja = sekcja.split("__")[0] if "__" in sekcja else sekcja

    # For cykliczny stages: "analiza" maps to the cykliczny stage, "dodatki" maps to corrections
    if base_sekcja == "dodatki":
        return None  # corrections don't need gate evaluation

    # Find the active stage
    etap_id = None
    for step in pipeline:
        etap = db.execute(
            "SELECT typ_cyklu FROM etapy_analityczne WHERE id = ?",
            (step["etap_id"],),
        ).fetchone()
        if not etap:
            continue
        if etap["typ_cyklu"] == "cykliczny" and base_sekcja == "analiza":
            etap_id = step["etap_id"]
            break
        if etap["typ_cyklu"] == "jednorazowy":
            etap_kod = db.execute(
                "SELECT kod FROM etapy_analityczne WHERE id = ?",
                (step["etap_id"],),
            ).fetchone()
            if etap_kod and etap_kod["kod"] == base_sekcja:
                etap_id = step["etap_id"]
                break

    if etap_id is None:
        return None

    # Find active session (latest w_trakcie for this stage)
    sesje = list_sesje(db, ebr_id, etap_id=etap_id)
    active = [s for s in sesje if s["status"] == "w_trakcie"]
    if not active:
        return None
    sesja = active[-1]

    # Build parametr_id lookup
    resolved = resolve_limity(db, produkt, etap_id)
    kod_to_pid = {r["kod"]: r["parametr_id"] for r in resolved}
    kod_to_limits = {r["kod"]: r for r in resolved}

    # Write to ebr_pomiar
    for kod, wartosc in values.items():
        pid = kod_to_pid.get(kod)
        if pid is None:
            continue
        limits = kod_to_limits.get(kod, {})
        save_pomiar(
            db, sesja["id"], pid,
            wartosc=wartosc,
            min_limit=limits.get("min_limit"),
            max_limit=limits.get("max_limit"),
            wpisal=wpisal,
        )

    # Evaluate gate
    gate = evaluate_gate(db, etap_id, sesja["id"])
    return gate
```

- [ ] **Step 3: Integrate into save_entry route**

In `mbr/laborant/routes.py`, in the `save_entry` function, after `sync_ebr_to_v4(db, ebr_id, ebr=ebr)` and before the values_changed check, add:

```python
        # Pipeline dual-write: save to ebr_pomiar + evaluate gate
        gate_result = None
        try:
            from mbr.pipeline.adapter import pipeline_dual_write
            parsed_values = {}
            for kod, entry in values.items():
                v = entry.get("wartosc", "")
                try:
                    parsed_values[kod] = parse_decimal(v) if v != "" else None
                except (ValueError, TypeError):
                    pass
            gate_result = pipeline_dual_write(db, ebr_id, sekcja, parsed_values, user)
            if gate_result is not None:
                db.commit()
        except Exception:
            pass  # pipeline dual-write is non-critical
```

And in the return jsonify, add gate:

```python
    resp = {"ok": True}
    if gate_result is not None:
        resp["gate"] = gate_result
    return jsonify(resp)
```

- [ ] **Step 4: Run tests**

```bash
pytest --tb=short -q
```

- [ ] **Step 5: Manual test**

Open a K7 batch, enter SM value, verify auto-save works. Check in DB:

```bash
sqlite3 data/batch_db.sqlite "SELECT * FROM ebr_pomiar ORDER BY id DESC LIMIT 5"
```

- [ ] **Step 6: Commit**

```bash
git add mbr/pipeline/adapter.py mbr/laborant/routes.py tests/test_pipeline_adapter.py
git commit -m "feat: dual-write to ebr_pomiar + gate evaluation in save_entry"
```

---

## Task 6: Verify end-to-end and final cleanup

**Files:**
- No new files — verification task

- [ ] **Step 1: Run full test suite**

```bash
pytest --tb=short -q
```

- [ ] **Step 2: Manual end-to-end test**

1. Login as lab → open szarze list
2. Click K7 batch → verify fast entry loads with standaryzacja parameters
3. Enter SM=45.5 → verify auto-save (green flash)
4. Enter NaCl value using titration calculator → verify calc works
5. Check SA computes automatically (if obliczeniowy)
6. Verify sidebar shows stage name correctly
7. Switch to another batch → verify fast batch switching works (AJAX, not full page)
8. Open admin pipeline → verify admin UI still works

- [ ] **Step 3: Verify dual-write**

```bash
sqlite3 data/batch_db.sqlite "SELECT p.id, pa.kod, p.wartosc, p.w_limicie FROM ebr_pomiar p JOIN parametry_analityczne pa ON pa.id = p.parametr_id ORDER BY p.id DESC LIMIT 10"
```

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: end-to-end verification fixes"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | Revert redirects | `laborant/routes.py`, `szarze_list.html` |
| 2 | Delete v2 templates + routes | `pipeline/fast_entry_v2.html`, `_fast_entry_v2_content.html`, `lab_routes.py` |
| 3 | Build adapter | `pipeline/adapter.py`, `tests/test_pipeline_adapter.py` |
| 4 | Integrate adapter in fast_entry_partial | `laborant/routes.py` |
| 5 | Dual-write + gate evaluation | `pipeline/adapter.py`, `laborant/routes.py` |
| 6 | E2E verification | Manual testing |
