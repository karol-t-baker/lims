# Parametry opisowe — PR3 (hero edit + cert integration) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Hero (tryb edycji ukończonej partii) pokazuje wszystkie typy parametrów z odpowiednimi widgetami: dropdown dla `typ='jakosciowy'`, numeric input z "lab zewn." badge dla `grupa='zewn'`. `save_wyniki` przyjmuje `wartosc_text`. Świadectwo PDF renderuje per-partia `wartosc_text` dla jakosciowych oraz "−" dla pustych zewn.

**Architecture:** (1) Dodaj `opisowe_wartosci` do pole dict w `_build_pole` — analogicznie do T1 PR2. (2) W `_fast_entry_content.html` (renderOneSection) rozszerz render o branch dla `typ_analityczny==='jakosciowy'` (select) i `grupa==='zewn'` (badge). (3) Rozszerz `save_wyniki` w `laborant/models.py` — przyjmij `wartosc_text` bezpośrednio, ustaw `w_limicie` na podstawie `opisowe_wartosci`. (4) Cert `build_context` — fallback chain dla jakosciowy (`wartosc_text` → `qualitative_result`); "−" dla pustego zewn. (5) Audit — rozszerz diff payload o `typ`/`grupa`/`field`.

**Tech Stack:** Python 3 / Flask / sqlite3 / Jinja2 / vanilla JS / pytest.

**Spec reference:** `docs/superpowers/specs/2026-04-20-parametry-opisowe-design.md` § "PR3 — Hero/rejestr edit + cert integration".

---

## File Structure

### Create
- `tests/test_pipeline_adapter_opisowe_wartosci.py` — test propagacji `opisowe_wartosci` przez `_build_pole`.
- `tests/test_save_wyniki_jakosciowy.py` — testy `save_wyniki` z `wartosc_text`.
- `tests/test_cert_jakosciowy_render.py` — testy cert render dla jakosciowy i zewn.

### Modify
- `mbr/pipeline/adapter.py::_build_pole` — dodaj fetch `opisowe_wartosci` dla `typ='jakosciowy'` (parsed list).
- `mbr/templates/laborant/_fast_entry_content.html::renderOneSection` — branch na `typ_analityczny === 'jakosciowy'` (select) i `grupa === 'zewn'` (badge).
- `mbr/laborant/models.py::save_wyniki` — przyjmuje `wartosc_text` z klienta, `w_limicie` liczone z `opisowe_wartosci`.
- `mbr/certs/generator.py::build_context` — resolucja `row.result` dla `typ='jakosciowy'` i `grupa='zewn'`.
- `mbr/parametry/registry.py::get_cert_params` — rozszerz SELECT o `pa.typ`, `pa.grupa`, `pa.opisowe_wartosci` (potrzebne do cert render decyzji).

---

## Tasks

### Task 1: Propagate `opisowe_wartosci` into pole dict

**Files:**
- Modify: `mbr/pipeline/adapter.py` (function `_build_pole` around lines 110–165)
- Test: `tests/test_pipeline_adapter_opisowe_wartosci.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pipeline_adapter_opisowe_wartosci.py`:

```python
"""PR3: _build_pole propagates opisowe_wartosci as a parsed list for jakosciowy."""

import json as _json
import sqlite3
import pytest

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed_jakosciowy(db, wartosci):
    pid = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision, opisowe_wartosci) "
        "VALUES ('zapach', 'Zapach', 'jakosciowy', 'lab', 0, ?)",
        (_json.dumps(wartosci) if wartosci else None,),
    ).lastrowid
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('P', 'P')")
    eid = db.execute(
        "INSERT INTO etapy_analityczne (kod, nazwa, typ_cyklu) VALUES ('e1', 'Etap', 'jednorazowy')"
    ).lastrowid
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('P', ?, 1)", (eid,))
    db.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc, grupa) VALUES (?, ?, 1, 'lab')", (eid, pid))
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, dla_szarzy, grupa) "
        "VALUES ('P', ?, ?, 1, 'lab')", (eid, pid),
    )
    db.commit()
    return pid


def test_build_pole_includes_opisowe_wartosci_as_list(db):
    from mbr.pipeline.adapter import build_pipeline_context
    _seed_jakosciowy(db, ["charakterystyczny", "obcy", "brak"])
    ctx = build_pipeline_context(db, "P", typ="szarza")
    pola = [p for s in ctx["parametry_lab"].values() for p in s["pola"]]
    assert len(pola) == 1
    assert pola[0]["opisowe_wartosci"] == ["charakterystyczny", "obcy", "brak"]


def test_build_pole_opisowe_wartosci_empty_when_null(db):
    from mbr.pipeline.adapter import build_pipeline_context
    _seed_jakosciowy(db, None)
    ctx = build_pipeline_context(db, "P", typ="szarza")
    pola = [p for s in ctx["parametry_lab"].values() for p in s["pola"]]
    assert pola[0]["opisowe_wartosci"] == []


def test_build_pole_no_opisowe_wartosci_key_for_non_jakosciowy(db):
    """Non-jakosciowy params don't get the key at all (keeps dict lean)."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision) "
        "VALUES ('gestosc', 'Gęstość', 'bezposredni', 'lab', 2)"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('P', 'P')")
    eid = db.execute(
        "INSERT INTO etapy_analityczne (kod, nazwa, typ_cyklu) VALUES ('e1', 'Etap', 'jednorazowy')"
    ).lastrowid
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('P', ?, 1)", (eid,))
    db.execute(
        "INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc, grupa) "
        "VALUES (?, (SELECT id FROM parametry_analityczne WHERE kod='gestosc'), 1, 'lab')",
        (eid,),
    )
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, dla_szarzy, grupa) "
        "VALUES ('P', ?, (SELECT id FROM parametry_analityczne WHERE kod='gestosc'), 1, 'lab')",
        (eid,),
    )
    db.commit()
    from mbr.pipeline.adapter import build_pipeline_context
    ctx = build_pipeline_context(db, "P", typ="szarza")
    pola = [p for s in ctx["parametry_lab"].values() for p in s["pola"]]
    assert "opisowe_wartosci" not in pola[0]
```

- [ ] **Step 2: Run test to verify fails**

`pytest tests/test_pipeline_adapter_opisowe_wartosci.py -v`
Expected: FAIL — no `opisowe_wartosci` key in pole dict.

- [ ] **Step 3: Extend `_build_pole` in `mbr/pipeline/adapter.py`**

Inside the function, AFTER the `pole: dict = {...}` block (around line 133), add:

```python
    if typ == "jakosciowy":
        parametr_id = param.get("parametr_id")
        raw = None
        if parametr_id:
            row = db.execute(
                "SELECT opisowe_wartosci FROM parametry_analityczne WHERE id = ?",
                (parametr_id,),
            ).fetchone()
            raw = row["opisowe_wartosci"] if row else None
        try:
            pole["opisowe_wartosci"] = json.loads(raw) if raw else []
        except Exception:
            pole["opisowe_wartosci"] = []
```

Ensure `json` is imported at top of `mbr/pipeline/adapter.py` — check imports; add `import json` if missing.

- [ ] **Step 4: Run tests to verify pass**

`pytest tests/test_pipeline_adapter_opisowe_wartosci.py -v`
Expected: 3/3 PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/pipeline/adapter.py tests/test_pipeline_adapter_opisowe_wartosci.py
git commit -m "feat(pipeline): propagate opisowe_wartosci as parsed list for jakosciowy pola"
```

---

### Task 2: Hero render widgets — `<select>` for jakosciowy + "lab zewn." badge

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html::renderOneSection` (around lines 2517–2677)

This is a frontend-only change. No new Python tests — verify via manual smoke test + existing Jinja parse check. Coverage via PR3-T3 (save_wyniki) tests the server side.

- [ ] **Step 1: Inspect render function**

Run: `grep -n "function renderOneSection\|isReadonly" /Users/tbk/Desktop/lims-clean/mbr/templates/laborant/_fast_entry_content.html | head -20`

Read the function body (approximately lines 2517–2677). Identify:
- The default numeric-input render block (~line 2633-2650).
- Where `measurement_type === 'binarny'` / `'titracja'` branches live (~lines 2568-2570).
- Where `sekWyniki[pole.kod]` is consumed.

- [ ] **Step 2: Add branches for jakosciowy and zewn**

Add a new branch BEFORE the generic numeric input render. Pseudocode layout:

```javascript
// Inside renderOneSection, for each pole loop body:

// (1) jakosciowy → select
if (pole.typ_analityczny === 'jakosciowy') {
  var cur = (sekWyniki[pole.kod] && sekWyniki[pole.kod].wartosc_text) || '';
  var values = pole.opisowe_wartosci || [];
  var opts = '<option value=""' + (cur === '' ? ' selected' : '') + '>—</option>';
  values.forEach(function(v) {
    var sel = (v === cur) ? ' selected' : '';
    opts += '<option value="' + escAttr(v) + '"' + sel + '>' + escHtml(v) + '</option>';
  });
  if (cur && values.indexOf(cur) === -1) {
    opts += '<option value="' + escAttr(cur) + '" selected>' + escHtml(cur) + ' (historyczna)</option>';
  }
  var disabledAttr = isReadonly ? ' disabled' : '';
  return buildFieldRow(pole, '<select data-kod="' + escAttr(pole.kod) + '" data-field="wartosc_text"' + disabledAttr + '>' + opts + '</select>');
}

// (2) zewn badge — decoration only; field itself is still numeric input.
var labelHtml = escHtml(pole.skrot || pole.kod);
if (pole.grupa === 'zewn') {
  labelHtml += ' <span class="pe-badge-zewn" title="Lab zewnętrzny">lab zewn.</span>';
}
// Continue to default numeric render using labelHtml.
```

Adapt `escAttr`/`escHtml` to whatever escape helpers the template already uses (`_esc` or equivalent — inspect the file). Adapt `buildFieldRow`/the existing wrapping HTML pattern to the actual structure used elsewhere in `renderOneSection`. The key structural requirements:
- `<select>` uses `data-kod="..."` and `data-field="wartosc_text"` so client-side POST knows it's a qualitative value.
- Historical value (current `wartosc_text` not in `opisowe_wartosci`) renders as selected option with `(historyczna)` suffix.
- For `grupa==='zewn'` (non-jakosciowy), keep numeric input; just append the badge to the label.

Add CSS for `.pe-badge-zewn` in the same file's `<style>` block (or a nearby block):

```css
.pe-badge-zewn {
  display: inline-block;
  font-size: 8px; font-weight: 800;
  color: var(--amber, #b45309);
  background: var(--amber-bg, #fef3c7);
  padding: 1px 5px; border-radius: 3px;
  margin-left: 6px; letter-spacing: 0.4px;
  text-transform: uppercase; vertical-align: middle;
}
```

- [ ] **Step 3: Jinja parse check**

Run:
```bash
python3 -c "from jinja2 import Environment, FileSystemLoader; env = Environment(loader=FileSystemLoader('/Users/tbk/Desktop/lims-clean/mbr/templates')); env.get_template('laborant/_fast_entry_content.html')"
```
Expected: no exception.

- [ ] **Step 4: Grep sanity**

`grep -c "typ_analityczny.*jakosciowy\|pe-badge-zewn\|data-field=\"wartosc_text\"" mbr/templates/laborant/_fast_entry_content.html`
Expected: ≥3 matches.

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat(hero): dropdown for jakosciowy + 'lab zewn.' badge in renderOneSection"
```

---

### Task 3: `save_wyniki` accepts `wartosc_text` + w_limicie by allowed list

**Files:**
- Modify: `mbr/laborant/models.py::save_wyniki` (lines 607–770)
- Test: `tests/test_save_wyniki_jakosciowy.py`

- [ ] **Step 1: Inspect existing save_wyniki**

Run: `grep -n "def save_wyniki\|wartosc_text" /Users/tbk/Desktop/lims-clean/mbr/laborant/models.py | head -15`

Read the function, paying attention to:
- How current values parse (prefix detection for qualitative — lines ~690+)
- How `w_limicie` is computed (lines ~739-747)
- The upsert statement

- [ ] **Step 2: Write the failing test**

Create `tests/test_save_wyniki_jakosciowy.py`:

```python
"""PR3: save_wyniki accepts wartosc_text for jakosciowy params + computes w_limicie from opisowe_wartosci."""

import json as _json
import sqlite3
import pytest

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed(db):
    pid = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision, opisowe_wartosci) "
        "VALUES ('zapach', 'Zapach', 'jakosciowy', 'lab', 0, ?)",
        (_json.dumps(["charakterystyczny", "obcy", "brak"]),),
    ).lastrowid
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('P', 'P')")
    db.execute(
        "INSERT INTO mbr_templates (produkt, status, parametry_lab, etapy_json, wersja, dt_utworzenia) "
        "VALUES ('P', 'active', '{}', '[]', 1, '2026-01-01')"
    )
    mbr_id = db.execute("SELECT mbr_id FROM mbr_templates WHERE produkt='P'").fetchone()[0]
    ebr_id = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, nr_amidatora, nr_mieszalnika, "
        "wielkosc_szarzy_kg, dt_start, operator, typ, status) "
        "VALUES (?, 'P__1', '1', 'A', 'M', 100, '2026-04-20', 'op', 'szarza', 'open')",
        (mbr_id,),
    ).lastrowid
    db.commit()
    return ebr_id, pid


def test_save_wyniki_writes_wartosc_text_for_jakosciowy(db):
    from mbr.laborant.models import save_wyniki
    ebr_id, _ = _seed(db)
    save_wyniki(db, ebr_id, "analiza",
                {"zapach": {"wartosc_text": "obcy"}}, "op")
    row = db.execute(
        "SELECT wartosc, wartosc_text, w_limicie FROM ebr_wyniki "
        "WHERE ebr_id=? AND kod_parametru='zapach'",
        (ebr_id,),
    ).fetchone()
    assert row["wartosc"] is None
    assert row["wartosc_text"] == "obcy"
    # Allowed value → in-limit
    assert row["w_limicie"] == 1


def test_save_wyniki_w_limicie_zero_for_historical_value(db):
    """Value outside opisowe_wartosci is accepted but flagged w_limicie=0."""
    from mbr.laborant.models import save_wyniki
    ebr_id, _ = _seed(db)
    save_wyniki(db, ebr_id, "analiza",
                {"zapach": {"wartosc_text": "legacy_value_not_in_list"}}, "op")
    row = db.execute(
        "SELECT wartosc_text, w_limicie FROM ebr_wyniki "
        "WHERE ebr_id=? AND kod_parametru='zapach'",
        (ebr_id,),
    ).fetchone()
    assert row["wartosc_text"] == "legacy_value_not_in_list"
    assert row["w_limicie"] == 0


def test_save_wyniki_empty_wartosc_text_clears_value(db):
    """Empty wartosc_text clears the previous value."""
    from mbr.laborant.models import save_wyniki
    ebr_id, _ = _seed(db)
    save_wyniki(db, ebr_id, "analiza", {"zapach": {"wartosc_text": "obcy"}}, "op")
    save_wyniki(db, ebr_id, "analiza", {"zapach": {"wartosc_text": ""}}, "op")
    row = db.execute(
        "SELECT wartosc_text FROM ebr_wyniki "
        "WHERE ebr_id=? AND kod_parametru='zapach'",
        (ebr_id,),
    ).fetchone()
    # Acceptable behaviors: row either absent or wartosc_text is "" / NULL.
    # Pick the behavior matching save_wyniki's convention for empty numeric.
    assert row is None or (row["wartosc_text"] or "") == ""
```

- [ ] **Step 3: Run test to verify fail**

`pytest tests/test_save_wyniki_jakosciowy.py -v`
Expected: `test_save_wyniki_writes_wartosc_text_for_jakosciowy` FAILS (save_wyniki doesn't read `wartosc_text` from payload today).

- [ ] **Step 4: Extend save_wyniki**

In `save_wyniki`, inside the per-kod loop (around where `wartosc_raw = entry.get("wartosc", "")` lives), add handling for explicit `wartosc_text`:

```python
        # Accept explicit wartosc_text from client (jakosciowy dropdown).
        # Takes precedence over the legacy numeric prefix detection.
        explicit_text = entry.get("wartosc_text")
        if explicit_text is not None:
            text_val = (explicit_text or "").strip()
            if not text_val:
                # Empty — skip insert (or delete existing if policy says so).
                # For PR3 parity with numeric empty, skip write.
                continue
            # Look up opisowe_wartosci to compute w_limicie.
            meta = db.execute(
                "SELECT opisowe_wartosci FROM parametry_analityczne WHERE kod = ?",
                (kod,),
            ).fetchone()
            allowed = []
            if meta and meta["opisowe_wartosci"]:
                try:
                    allowed = json.loads(meta["opisowe_wartosci"])
                except Exception:
                    allowed = []
            w_limicie_val = 1 if text_val in allowed else 0

            # Build row for upsert. Mirror existing INSERT ... ON CONFLICT pattern
            # with wartosc=NULL, wartosc_text=text_val.
            # ... (use existing upsert code path; see current handler)
            # Track diff analogously to numeric path.
            ... # stitch into existing upsert logic
            continue
```

This is a pseudocode sketch. The real change must integrate with the existing prefix-detection + upsert pipeline in `save_wyniki`. Read the function carefully and find the right insertion point such that when `explicit_text is not None`, the legacy numeric path is bypassed and the upsert path runs with `wartosc=NULL, wartosc_text=text_val, w_limicie=(1 if text_val in allowed else 0)`. Preserve existing prefix detection for backward compat (e.g. `<0.1`).

The diff entry for audit should have `pole: kod`, `stara: <old wartosc_text>`, `nowa: <new text_val>`.

- [ ] **Step 5: Run tests to verify pass**

`pytest tests/test_save_wyniki_jakosciowy.py -v`
Expected: 3/3 PASS.

Also run `pytest tests/test_laborant.py -v` — no regressions in existing save_wyniki tests.

- [ ] **Step 6: Commit**

```bash
git add mbr/laborant/models.py tests/test_save_wyniki_jakosciowy.py
git commit -m "feat(laborant): save_wyniki accepts wartosc_text for jakosciowy + w_limicie from allowed list"
```

---

### Task 4: Cert render — jakosciowy uses `wartosc_text`, empty zewn shows "−"

**Files:**
- Modify: `mbr/parametry/registry.py::get_cert_params` + `get_cert_variant_params` — include `typ`, `grupa` in SELECT.
- Modify: `mbr/certs/generator.py::build_context` — resolution logic.
- Test: `tests/test_cert_jakosciowy_render.py`

- [ ] **Step 1: Extend `get_cert_params` SELECT**

In `mbr/parametry/registry.py::get_cert_params` (around line 239), add `pa.typ`, `pa.grupa` to the SELECT and to the returned dict. Mirror the change in `get_cert_variant_params` (around line 266).

Example (base params):

```python
    rows = db.execute("""
        SELECT
            pa.kod, pa.label, pa.name_en, pa.method_code,
            pa.typ, pa.grupa,
            pc.requirement, pc.format, pc.qualitative_result,
            pc.kolejnosc, pc.parametr_id,
            pc.name_pl AS cert_name_pl, pc.name_en AS cert_name_en, pc.method AS cert_method
        FROM parametry_cert pc
        JOIN parametry_analityczne pa ON pa.id = pc.parametr_id
        WHERE pc.produkt = ? AND pc.variant_id IS NULL
        ORDER BY pc.kolejnosc
    """, (produkt,)).fetchall()

    return [
        {
            "kod": r["kod"],
            "parametr_id": r["parametr_id"],
            "typ": r["typ"],                # NEW
            "grupa": r["grupa"],            # NEW
            "name_pl": r["cert_name_pl"] or r["label"] or "",
            "name_en": r["cert_name_en"] if r["cert_name_en"] is not None else (r["name_en"] or ""),
            "method": r["cert_method"] or r["method_code"] or "",
            "requirement": r["requirement"] or "",
            "format": r["format"] or "1",
            "qualitative_result": r["qualitative_result"],
        }
        for r in rows
    ]
```

Do the same for `get_cert_variant_params`.

- [ ] **Step 2: Write the failing test**

Create `tests/test_cert_jakosciowy_render.py`:

```python
"""PR3: cert build_context renders per-batch wartosc_text for jakosciowy; '−' for empty zewn."""

import json as _json
import sqlite3
from contextlib import contextmanager

import pytest

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed_cert_product(db, produkt="CP", kod="zapach", typ="jakosciowy", grupa="lab",
                       wartosci=None, cert_qr="charakterystyczny"):
    pid = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision, opisowe_wartosci) "
        "VALUES (?, ?, ?, ?, 0, ?)",
        (kod, kod.capitalize(), typ, grupa,
         _json.dumps(wartosci) if wartosci else None),
    ).lastrowid
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES (?, ?)", (produkt, produkt))
    cv = db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label) VALUES (?, 'base', 'Base')",
        (produkt,),
    ).lastrowid
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format, qualitative_result) "
        "VALUES (?, ?, 1, 'charakterystyczny', '1', ?)",
        (produkt, pid, cert_qr),
    )
    db.commit()
    return pid


def _patch_db(monkeypatch, db):
    import mbr.db
    import mbr.certs.generator

    @contextmanager
    def fake():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake)
    monkeypatch.setattr(mbr.certs.generator, "db_session", fake, raising=False)


def test_build_context_uses_wartosc_text_for_jakosciowy(monkeypatch, db):
    """When a batch has wartosc_text for a jakosciowy param, cert shows that, not cert_qualitative_result."""
    from mbr.certs.generator import build_context
    _seed_cert_product(db, wartosci=["charakterystyczny", "obcy"], cert_qr="charakterystyczny")
    _patch_db(monkeypatch, db)
    # wyniki_flat from caller contains per-batch value.
    wyniki_flat = {"zapach": {"wartosc": None, "wartosc_text": "obcy"}}
    ctx = build_context("CP", "base", "1/2026", "2026-04-20", wyniki_flat, {}, "wystawil")
    rows = ctx.get("rows", [])
    result_cell = next((r for r in rows if r["kod"] == "zapach"), None)
    assert result_cell is not None
    assert result_cell["result"] == "obcy"


def test_build_context_falls_back_to_qualitative_result_when_wartosc_text_empty(monkeypatch, db):
    from mbr.certs.generator import build_context
    _seed_cert_product(db, wartosci=["charakterystyczny"], cert_qr="charakterystyczny")
    _patch_db(monkeypatch, db)
    wyniki_flat = {}  # No per-batch value.
    ctx = build_context("CP", "base", "1/2026", "2026-04-20", wyniki_flat, {}, "wystawil")
    rows = ctx.get("rows", [])
    row = next((r for r in rows if r["kod"] == "zapach"), None)
    assert row["result"] == "charakterystyczny"


def test_build_context_renders_minus_for_empty_zewn(monkeypatch, db):
    from mbr.certs.generator import build_context
    _seed_cert_product(db, kod="siarka", typ="bezposredni", grupa="zewn",
                       cert_qr=None)
    _patch_db(monkeypatch, db)
    wyniki_flat = {}  # No per-batch value.
    ctx = build_context("CP", "base", "1/2026", "2026-04-20", wyniki_flat, {}, "wystawil")
    rows = ctx.get("rows", [])
    row = next((r for r in rows if r["kod"] == "siarka"), None)
    assert row is not None
    assert row["result"] == "\u2212"  # U+2212 minus sign


def test_build_context_lab_numeric_unchanged(monkeypatch, db):
    """Regression: existing lab numeric rendering (uses qualitative_result fallback + numeric wartosc) still works."""
    from mbr.certs.generator import build_context
    _seed_cert_product(db, kod="gestosc", typ="bezposredni", grupa="lab", cert_qr=None)
    _patch_db(monkeypatch, db)
    wyniki_flat = {"gestosc": {"wartosc": 1.0234}}
    ctx = build_context("CP", "base", "1/2026", "2026-04-20", wyniki_flat, {}, "wystawil")
    row = next((r for r in ctx["rows"] if r["kod"] == "gestosc"), None)
    assert row is not None
    # Numeric renders with formatting — just sanity check non-empty and not minus.
    assert row["result"] not in ("", "\u2212")
```

Note: `build_context` signature may vary. Inspect `mbr/certs/generator.py` for exact signature and adjust the call.

- [ ] **Step 3: Run tests to verify fail**

`pytest tests/test_cert_jakosciowy_render.py -v`
Expected: `test_build_context_uses_wartosc_text_*` FAILS (currently always uses qualitative_result); `test_build_context_renders_minus_for_empty_zewn` FAILS (currently returns "").

- [ ] **Step 4: Extend build_context resolution**

In `mbr/certs/generator.py::build_context`, find the block (around lines 346-360) that resolves `row.result`. Replace with:

```python
        kod = r["kod"]
        param_typ = r.get("typ")
        param_grupa = r.get("grupa")
        per_batch = wyniki_flat.get(kod) if wyniki_flat else None
        if isinstance(per_batch, dict):
            batch_wartosc = per_batch.get("wartosc")
            batch_text = per_batch.get("wartosc_text")
        else:
            batch_wartosc = per_batch
            batch_text = None

        if param_typ == "jakosciowy":
            # Per-batch wartosc_text first; fall back to cert-level qualitative_result.
            result_value = (batch_text or "").strip() or (r["qualitative_result"] or "")
        elif param_grupa == "zewn" and batch_wartosc in (None, ""):
            # Empty external-lab value → visible placeholder.
            result_value = "\u2212"
        elif r["qualitative_result"]:
            # Non-jakosciowy with admin-set qualitative text → unchanged fallback.
            result_value = r["qualitative_result"]
        else:
            # Numeric path (existing formatting).
            result_value = _format_numeric(batch_wartosc, r["format"]) if batch_wartosc not in (None, "") else ""
```

The `_format_numeric` (or equivalent) already exists — use the same helper the current code uses. Integrate the block into the existing loop that builds `rows`.

- [ ] **Step 5: Run tests**

`pytest tests/test_cert_jakosciowy_render.py -v` — 4/4 PASS.
Also `pytest tests/test_certs.py tests/test_certs_grupa.py tests/test_cert_template_render.py -v` — no regressions.

- [ ] **Step 6: Commit**

```bash
git add mbr/parametry/registry.py mbr/certs/generator.py tests/test_cert_jakosciowy_render.py
git commit -m "feat(certs): render per-batch wartosc_text for jakosciowy; '−' for empty zewn"
```

---

### Task 5: Audit payload extension

**Files:**
- Modify: `mbr/laborant/models.py::save_wyniki` (where `diff` entries are built — found in T3)
- Test: `tests/test_save_wyniki_jakosciowy.py` (append)

- [ ] **Step 1: Append failing test**

Add to `tests/test_save_wyniki_jakosciowy.py`:

```python
def test_save_wyniki_returns_diff_with_field_metadata(db):
    """Diff entries for jakosciowy include 'field': 'wartosc_text', plus typ and grupa."""
    from mbr.laborant.models import save_wyniki
    ebr_id, _ = _seed(db)
    result = save_wyniki(db, ebr_id, "analiza",
                         {"zapach": {"wartosc_text": "obcy"}}, "op")
    diffs = result.get("diffs", [])
    assert len(diffs) == 1
    d = diffs[0]
    assert d.get("field") == "wartosc_text"
    assert d.get("typ") == "jakosciowy"
    assert d.get("grupa") == "lab"
    assert d.get("nowa") == "obcy"
```

- [ ] **Step 2: Run test — verify fails**

`pytest tests/test_save_wyniki_jakosciowy.py::test_save_wyniki_returns_diff_with_field_metadata -v`
Expected: FAIL — diff entry lacks `field`/`typ`/`grupa`.

- [ ] **Step 3: Extend diff payload**

In `save_wyniki`, where diff entries are built (`diffs.append({"pole": kod, "stara": ..., "nowa": ...})` — find in the function), extend with the extra keys by looking up `typ`/`grupa` from `parametry_analityczne`:

```python
            # Enrich diff with param metadata + which field changed.
            meta = db.execute(
                "SELECT typ, grupa FROM parametry_analityczne WHERE kod = ?", (kod,)
            ).fetchone()
            diffs.append({
                "pole": kod,
                "stara": old_val,
                "nowa": new_val,
                "field": field_name,   # "wartosc" or "wartosc_text"
                "typ": meta["typ"] if meta else None,
                "grupa": meta["grupa"] if meta else None,
            })
```

`field_name` = `"wartosc_text"` for the jakosciowy branch added in T3, `"wartosc"` for the numeric branch. Ensure both paths emit it consistently (don't leave numeric path without `field`).

- [ ] **Step 4: Run tests**

`pytest tests/test_save_wyniki_jakosciowy.py -v` — 4/4 PASS.
`pytest tests/test_audit_phase4_wyniki.py tests/test_laborant.py -v` — no regressions.

- [ ] **Step 5: Commit**

```bash
git add mbr/laborant/models.py tests/test_save_wyniki_jakosciowy.py
git commit -m "feat(audit): ebr.wynik.* diff includes field/typ/grupa metadata"
```

---

### Task 6: Full suite + manual smoke

- [ ] **Step 1: Full suite**

`cd /Users/tbk/Desktop/lims-clean && pytest`
Expected: All tests pass.

- [ ] **Step 2: Review branch commit log**

`git log --oneline main..HEAD`
Expected: PR1 commits + PR2 commits + 5 PR3 commits.

- [ ] **Step 3: Manual smoke test (if dev server accessible)**

- Seed a product with a `jakosciowy` param (`opisowe_wartosci=["charakterystyczny","obcy"]`, `cert_qualitative_result="charakterystyczny"`).
- Create an EBR → verify `ebr_wyniki.wartosc_text = "charakterystyczny"` (from PR2 auto-fill).
- Open the entry form (open batch) → jakosciowy field hidden, numeric visible.
- Mark batch `completed` (DB update) and reload → jakosciowy field shows as `<select>` with "charakterystyczny" selected and options [—, charakterystyczny, obcy].
- Change dropdown to "obcy" → save. Confirm `ebr_wyniki.wartosc_text="obcy"`, `w_limicie=1`.
- Generate a cert for this batch → PDF shows `"obcy"` in Wynik column for zapach.
- For a zewn param with NULL wartosc → PDF shows `"−"`.

If dev server not accessible, document coverage via tests only.

---

## Out of scope (deferred)

- **Frontend tests** for renderOneSection (Task 2): manual smoke covers rendering; snapshotting DOM requires browser harness (not set up in this repo).
- **Historical value dropdown option behavior on save**: if user selects the `(historyczna)` option, save sends that text. Server accepts any wartosc_text but flags `w_limicie=0`. No data loss; no new server behavior needed.
- **Auto-regeneration of cert after hero edit**: user opted for manual regen (spec non-goal).
- **Role differentiation**: all laborant roles edit all types in hero (spec decision).
