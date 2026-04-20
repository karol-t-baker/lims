# Parametry opisowe — PR2 (laborant entry filter + auto-fill + backfill) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Laborant w formularzu wejściowym widzi tylko `grupa='lab' AND typ != 'jakosciowy'` parametry; parametry `typ='jakosciowy'` są automatycznie wypełniane wartością domyślną (`cert_qualitative_result`) przy tworzeniu EBR; skrypt backfill uzupełnia istniejące otwarte partie.

**Architecture:** Propaguj `parametry_analityczne.typ` jako pole `typ_analityczny` w pole-dict (zbudowane w `_build_pole`). Dodaj funkcję filtrującą `parametry_lab` dla trybu entry. W `create_ebr()` po INSERT EBR dodaj krok auto-insert `ebr_wyniki.wartosc_text` dla jakosciowych parametrów. Skrypt backfill powtarza to samo dla istniejących otwartych partii. Filtr w `fast_entry_partial` stosuje się tylko dla otwartych partii.

**Tech Stack:** Python 3 / Flask / sqlite3 / Jinja2 / pytest (in-memory SQLite).

**Spec reference:** `docs/superpowers/specs/2026-04-20-parametry-opisowe-design.md` § "PR2 — Laborant: entry filter + auto-fill + backfill".

---

## File Structure

### Create
- `tests/test_pipeline_adapter_jakosciowy.py` — testy `_build_pole` (nowy klucz `typ_analityczny`) + filtra `filter_parametry_lab_for_entry`.
- `tests/test_ebr_create_jakosciowe_autofill.py` — testy auto-insert `ebr_wyniki.wartosc_text` przy `create_ebr`.
- `tests/test_backfill_jakosciowe.py` — testy skryptu backfill.
- `scripts/backfill_jakosciowe_values.py` — idempotentny skrypt backfill.

### Modify
- `mbr/pipeline/adapter.py` — `_build_pole` dodaje klucz `typ_analityczny`; nowa funkcja `filter_parametry_lab_for_entry(parametry_lab) -> dict`.
- `mbr/laborant/models.py` — `create_ebr` po INSERT wywołuje nowy helper `_autofill_jakosciowe_wyniki(db, ebr_id, produkt, mbr_parametry_lab)`.
- `mbr/laborant/routes.py` — `fast_entry_partial` stosuje filtr `filter_parametry_lab_for_entry` gdy partia jest otwarta (`status != 'zakonczona'`).
- `deploy/auto-deploy.sh` — dodaje wywołanie `scripts/backfill_jakosciowe_values.py` przed restartem.

---

## Tasks

### Task 1: Propagate `typ_analityczny` in `_build_pole`

**Files:**
- Modify: `mbr/pipeline/adapter.py` (function `_build_pole` around lines 110–165)
- Test: `tests/test_pipeline_adapter_jakosciowy.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pipeline_adapter_jakosciowy.py`:

```python
"""PR2: propagate parametry_analityczne.typ into pole dict as typ_analityczny."""

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


def _seed_product_with_param(db, produkt="TESTPROD", kod="zapach", typ="jakosciowy",
                              grupa="lab", opisowe_wartosci=None):
    """Seed minimal pipeline so build_pipeline_context returns at least one pole."""
    import json as _json
    # Parameter
    pid = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision, opisowe_wartosci) "
        "VALUES (?, ?, ?, ?, 0, ?)",
        (kod, kod.capitalize(), typ, grupa,
         _json.dumps(opisowe_wartosci) if opisowe_wartosci else None),
    ).lastrowid
    # Product
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES (?, ?)", (produkt, produkt))
    # Pipeline stage
    eid = db.execute(
        "INSERT INTO etapy_katalog (kod, nazwa) VALUES ('e1', 'Etap 1')"
    ).lastrowid
    db.execute(
        "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc, typ_cyklu) "
        "VALUES (?, ?, 1, 'jednorazowy')",
        (produkt, eid),
    )
    db.execute(
        "INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc, grupa) "
        "VALUES (?, ?, 1, ?)",
        (eid, pid, grupa),
    )
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, "
        "dla_szarzy, dla_zbiornika, dla_platkowania, grupa) "
        "VALUES (?, ?, ?, 1, 0, 0, ?)",
        (produkt, eid, pid, grupa),
    )
    db.commit()
    return pid, eid


def test_build_pole_includes_typ_analityczny(db):
    """_build_pole exposes the raw parametry_analityczne.typ value as 'typ_analityczny'."""
    from mbr.pipeline.adapter import build_pipeline_context
    _seed_product_with_param(db, typ="jakosciowy",
                             opisowe_wartosci=["charakterystyczny", "obcy"])
    ctx = build_pipeline_context(db, "TESTPROD", typ="szarza")
    assert ctx is not None
    pola = []
    for sekcja in ctx["parametry_lab"].values():
        pola.extend(sekcja["pola"])
    assert len(pola) == 1
    assert pola[0]["typ_analityczny"] == "jakosciowy"


def test_build_pole_typ_analityczny_for_bezposredni(db):
    _seed_product_with_param(db, kod="gestosc", typ="bezposredni")
    from mbr.pipeline.adapter import build_pipeline_context
    ctx = build_pipeline_context(db, "TESTPROD", typ="szarza")
    assert ctx is not None
    pola = []
    for sekcja in ctx["parametry_lab"].values():
        pola.extend(sekcja["pola"])
    assert pola[0]["typ_analityczny"] == "bezposredni"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/tbk/Desktop/lims-clean && pytest tests/test_pipeline_adapter_jakosciowy.py -v`
Expected: FAIL — `"typ_analityczny"` not in pola dict.

- [ ] **Step 3: Add `typ_analityczny` key in `_build_pole`**

In `mbr/pipeline/adapter.py`, inside `_build_pole` (around line 118 where the `pole` dict is built), add:

```python
    pole: dict = {
        "kod":              param["kod"],
        "label":            param["label"],
        "skrot":            param["skrot"] or param["kod"],
        "tag":              param["kod"],
        "typ":              _pole_typ(typ),
        "typ_analityczny":  typ,        # <-- NEW: raw parametry_analityczne.typ
        "measurement_type": measurement_type,
        "min":              param["min_limit"],
        "max":              param["max_limit"],
        "min_limit":        param["min_limit"],
        "max_limit":        param["max_limit"],
        "precision":        param["precision"],
        "spec_value":       param["spec_value"],
        "grupa":            param["grupa"] or "lab",
        "pe_id":            param.get("pe_id"),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tbk/Desktop/lims-clean && pytest tests/test_pipeline_adapter_jakosciowy.py -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/pipeline/adapter.py tests/test_pipeline_adapter_jakosciowy.py
git commit -m "feat(pipeline): propagate parametry_analityczne.typ as typ_analityczny in pole dict"
```

---

### Task 2: `filter_parametry_lab_for_entry` helper

**Files:**
- Modify: `mbr/pipeline/adapter.py` (add new function below `build_pipeline_context`)
- Test: `tests/test_pipeline_adapter_jakosciowy.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline_adapter_jakosciowy.py`:

```python
def test_filter_hides_jakosciowy_and_zewn():
    """filter_parametry_lab_for_entry keeps only grupa='lab' AND typ != 'jakosciowy'."""
    from mbr.pipeline.adapter import filter_parametry_lab_for_entry
    parametry_lab = {
        "analiza": {"label": "Analiza", "pola": [
            {"kod": "gestosc", "grupa": "lab", "typ_analityczny": "bezposredni"},
            {"kod": "zapach", "grupa": "lab", "typ_analityczny": "jakosciowy"},
            {"kod": "siarka", "grupa": "zewn", "typ_analityczny": "bezposredni"},
            {"kod": "ph", "grupa": "lab", "typ_analityczny": "titracja"},
        ]},
        "standaryzacja": {"label": "Std", "pola": [
            {"kod": "x_zewn", "grupa": "zewn", "typ_analityczny": "bezposredni"},
        ]},
    }
    filtered = filter_parametry_lab_for_entry(parametry_lab)
    # Kept: gestosc (lab, bezposredni), ph (lab, titracja)
    analiza_kody = [p["kod"] for p in filtered["analiza"]["pola"]]
    assert analiza_kody == ["gestosc", "ph"]
    # Standaryzacja ends up with empty pola → section should be dropped
    assert "standaryzacja" not in filtered


def test_filter_preserves_empty_input():
    from mbr.pipeline.adapter import filter_parametry_lab_for_entry
    assert filter_parametry_lab_for_entry({}) == {}


def test_filter_treats_missing_grupa_as_lab():
    """Legacy fields without explicit grupa should be treated as lab."""
    from mbr.pipeline.adapter import filter_parametry_lab_for_entry
    parametry_lab = {
        "analiza": {"label": "Analiza", "pola": [
            {"kod": "gestosc", "typ_analityczny": "bezposredni"},  # no grupa key
        ]},
    }
    filtered = filter_parametry_lab_for_entry(parametry_lab)
    assert len(filtered["analiza"]["pola"]) == 1


def test_filter_treats_missing_typ_analityczny_as_non_jakosciowy():
    """Fields without typ_analityczny (e.g., pre-PR2 snapshots) default to visible."""
    from mbr.pipeline.adapter import filter_parametry_lab_for_entry
    parametry_lab = {
        "analiza": {"label": "Analiza", "pola": [
            {"kod": "legacy", "grupa": "lab"},  # no typ_analityczny
        ]},
    }
    filtered = filter_parametry_lab_for_entry(parametry_lab)
    assert len(filtered["analiza"]["pola"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tbk/Desktop/lims-clean && pytest tests/test_pipeline_adapter_jakosciowy.py -v -k "filter"`
Expected: FAIL — `filter_parametry_lab_for_entry` not defined.

- [ ] **Step 3: Add filter function in mbr/pipeline/adapter.py**

Add at the end of `mbr/pipeline/adapter.py`:

```python
# ---------------------------------------------------------------------------
# Entry-form filtering
# ---------------------------------------------------------------------------

def filter_parametry_lab_for_entry(parametry_lab: dict) -> dict:
    """Filter a parametry_lab dict down to fields visible in the laborant entry form.

    Entry form shows only internal-lab numeric params:
      grupa == 'lab' (or missing, treated as 'lab')  AND
      typ_analityczny != 'jakosciowy'

    Sections that end up with no visible pola are dropped entirely so the UI
    doesn't render empty groups.

    The full parametry_lab snapshot is preserved in ebr_batches; this filter
    only affects what's *rendered* in the entry form. Hero view uses the
    unfiltered snapshot.
    """
    result: dict = {}
    for sekcja_key, sekcja in parametry_lab.items():
        pola = sekcja.get("pola", [])
        visible = [
            p for p in pola
            if (p.get("grupa") or "lab") == "lab"
            and p.get("typ_analityczny") != "jakosciowy"
        ]
        if visible:
            result[sekcja_key] = {**sekcja, "pola": visible}
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tbk/Desktop/lims-clean && pytest tests/test_pipeline_adapter_jakosciowy.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/pipeline/adapter.py tests/test_pipeline_adapter_jakosciowy.py
git commit -m "feat(pipeline): filter_parametry_lab_for_entry hides zewn and jakosciowy"
```

---

### Task 3: Wire filter into `fast_entry_partial` for open batches

**Files:**
- Modify: `mbr/laborant/routes.py::fast_entry_partial` (around lines 200–216)
- Test: `tests/test_laborant_entry_filter.py` (new)

- [ ] **Step 1: Locate the route**

Run: `grep -n "def fast_entry_partial\|build_pipeline_context" /Users/tbk/Desktop/lims-clean/mbr/laborant/routes.py | head -10`

Read the function. Note how it obtains the batch (ebr_id), pulls `ebr_row` with status, and calls `build_pipeline_context`. We'll filter the returned `parametry_lab` when `ebr_row["status"]` indicates the batch is open (not completed).

- [ ] **Step 2: Write the failing test**

Create `tests/test_laborant_entry_filter.py`:

```python
"""PR2: fast_entry_partial filters jakosciowy + zewn for open batches, shows all for completed."""

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


@pytest.fixture
def client(monkeypatch, db):
    import mbr.db
    import mbr.laborant.routes
    import mbr.laborant.models
    from mbr.app import app

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.laborant.models, "db_session", fake_db_session)
    app.config["TESTING"] = True
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["user"] = {"login": "lab_test", "rola": "lab", "id": 1}
        yield c


def _seed_batch_with_mixed_params(db, status="otwarta"):
    """Seed an EBR with 1 lab-numeric + 1 jakosciowy + 1 zewn param."""
    # Params
    pid_num = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision) "
        "VALUES ('gestosc', 'Gęstość', 'bezposredni', 'lab', 2)"
    ).lastrowid
    pid_jak = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision, opisowe_wartosci) "
        "VALUES ('zapach', 'Zapach', 'jakosciowy', 'lab', 0, ?)",
        (_json.dumps(["charakterystyczny"]),),
    ).lastrowid
    pid_zewn = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision) "
        "VALUES ('siarka', 'Siarka', 'bezposredni', 'zewn', 3)"
    ).lastrowid

    # Product + pipeline
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('P1', 'P1')")
    eid = db.execute(
        "INSERT INTO etapy_katalog (kod, nazwa) VALUES ('e1', 'Etap 1')"
    ).lastrowid
    db.execute(
        "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc, typ_cyklu) "
        "VALUES ('P1', ?, 1, 'jednorazowy')",
        (eid,),
    )
    for pid, grupa in [(pid_num, 'lab'), (pid_jak, 'lab'), (pid_zewn, 'zewn')]:
        db.execute(
            "INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc, grupa) "
            "VALUES (?, ?, 1, ?)",
            (eid, pid, grupa),
        )
        db.execute(
            "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, "
            "dla_szarzy, grupa) VALUES ('P1', ?, ?, 1, ?)",
            (eid, pid, grupa),
        )

    # MBR template + EBR
    from mbr.parametry.registry import build_parametry_lab
    plab = _json.dumps(build_parametry_lab(db, "P1"), ensure_ascii=False)
    mbr_id = db.execute(
        "INSERT INTO mbr_templates (produkt, status, parametry_lab, etapy_json) "
        "VALUES ('P1', 'active', ?, '[]')",
        (plab,),
    ).lastrowid
    ebr_id = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, nr_amidatora, "
        "nr_mieszalnika, wielkosc_szarzy_kg, dt_start, operator, typ, status) "
        "VALUES (?, 'P1__1', '1', 'A', 'M', 100, '2026-04-20', 'lab', 'szarza', ?)",
        (mbr_id, status),
    ).lastrowid
    db.commit()
    return ebr_id


def test_entry_partial_hides_jakosciowy_and_zewn_for_open_batch(client, db):
    ebr_id = _seed_batch_with_mixed_params(db, status="otwarta")
    r = client.get(f"/laborant/ebr/{ebr_id}/partial")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "gestosc" in html
    assert "zapach" not in html
    assert "siarka" not in html


def test_entry_partial_shows_all_for_completed_batch(client, db):
    ebr_id = _seed_batch_with_mixed_params(db, status="zakonczona")
    r = client.get(f"/laborant/ebr/{ebr_id}/partial")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "gestosc" in html
    assert "zapach" in html
    assert "siarka" in html
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_laborant_entry_filter.py -v`
Expected: `test_entry_partial_hides_*` FAILS (all 3 kods appear regardless of status); `test_entry_partial_shows_all_*` may PASS trivially.

- [ ] **Step 4: Apply filter in `fast_entry_partial`**

In `mbr/laborant/routes.py::fast_entry_partial`, locate the block that calls `build_pipeline_context(db, produkt, typ=batch_typ)` and assigns to context. Immediately after, and before rendering, add:

```python
        from mbr.pipeline.adapter import filter_parametry_lab_for_entry
        # Hide grupa='zewn' and typ='jakosciowy' while batch is open (entry mode).
        # Completed batches fall through to hero mode — show everything for edit.
        if (ebr_row.get("status") or "").lower() != "zakonczona":
            ctx["parametry_lab"] = filter_parametry_lab_for_entry(ctx["parametry_lab"])
```

Replace `ebr_row` with whatever name the function uses locally for the joined EBR+MBR row; replace `ctx` with the local name holding the `build_pipeline_context` result. If the status field uses a different value (e.g., `"completed"` or `"DONE"`), adjust the string comparison. Inspect the function to confirm exact naming.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_laborant_entry_filter.py -v`
Expected: 2/2 PASS.

Run full suite: `pytest` — no regressions.

- [ ] **Step 6: Commit**

```bash
git add mbr/laborant/routes.py tests/test_laborant_entry_filter.py
git commit -m "feat(laborant): entry form hides zewn + jakosciowy for open batches"
```

---

### Task 4: Auto-insert `ebr_wyniki` for jakosciowe at `create_ebr`

**Files:**
- Modify: `mbr/laborant/models.py::create_ebr` (lines 387–413) + new helper `_autofill_jakosciowe_wyniki`
- Test: `tests/test_ebr_create_jakosciowe_autofill.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ebr_create_jakosciowe_autofill.py`:

```python
"""PR2: create_ebr auto-inserts ebr_wyniki.wartosc_text for typ='jakosciowy' params."""

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


def _seed_product_with_jakosciowy(db, produkt="P2", kod="zapach",
                                   cert_qr="charakterystyczny"):
    """Seed product + MBR with one jakosciowy param that has cert_qualitative_result set."""
    pid = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision, opisowe_wartosci) "
        "VALUES (?, ?, 'jakosciowy', 'lab', 0, ?)",
        (kod, kod.capitalize(), _json.dumps(["charakterystyczny", "obcy"])),
    ).lastrowid
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES (?, ?)", (produkt, produkt))
    eid = db.execute(
        "INSERT INTO etapy_katalog (kod, nazwa) VALUES ('e1', 'Etap 1')"
    ).lastrowid
    db.execute(
        "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc, typ_cyklu) "
        "VALUES (?, ?, 1, 'jednorazowy')",
        (produkt, eid),
    )
    db.execute(
        "INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc, grupa) "
        "VALUES (?, ?, 1, 'lab')",
        (eid, pid),
    )
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, "
        "dla_szarzy, grupa) VALUES (?, ?, ?, 1, 'lab')",
        (produkt, eid, pid),
    )
    # This is the source of the default value — mirrors what cert editor stores.
    db.execute(
        "INSERT INTO parametry_etapy (produkt, kontekst, parametr_id, "
        "cert_qualitative_result, on_cert) VALUES (?, 'e1', ?, ?, 1)",
        (produkt, pid, cert_qr),
    )
    # MBR snapshot
    from mbr.parametry.registry import build_parametry_lab
    plab = _json.dumps(build_parametry_lab(db, produkt), ensure_ascii=False)
    db.execute(
        "INSERT INTO mbr_templates (produkt, status, parametry_lab, etapy_json) "
        "VALUES (?, 'active', ?, '[]')",
        (produkt, plab),
    )
    db.commit()
    return pid


def test_create_ebr_autoinserts_jakosciowy_with_cert_default(db):
    from mbr.laborant.models import create_ebr
    _seed_product_with_jakosciowy(db, cert_qr="charakterystyczny")
    ebr_id = create_ebr(db, "P2", "1", "A", "M", 100, "lab_test", typ="szarza")
    assert ebr_id is not None
    rows = db.execute(
        "SELECT kod_parametru, wartosc, wartosc_text FROM ebr_wyniki WHERE ebr_id=?",
        (ebr_id,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["kod_parametru"] == "zapach"
    assert rows[0]["wartosc"] is None
    assert rows[0]["wartosc_text"] == "charakterystyczny"


def test_create_ebr_skips_jakosciowy_when_cert_default_empty(db):
    from mbr.laborant.models import create_ebr
    _seed_product_with_jakosciowy(db, cert_qr=None)
    ebr_id = create_ebr(db, "P2", "2", "A", "M", 100, "lab_test", typ="szarza")
    rows = db.execute(
        "SELECT * FROM ebr_wyniki WHERE ebr_id=?", (ebr_id,)
    ).fetchall()
    assert len(rows) == 0


def test_create_ebr_skips_non_jakosciowy_params(db):
    """bezposredni params are NOT auto-inserted (laborant fills them manually)."""
    from mbr.laborant.models import create_ebr
    # Seed a bezposredni-only product
    pid = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision) "
        "VALUES ('gestosc', 'Gęstość', 'bezposredni', 'lab', 2)"
    ).lastrowid
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('P3', 'P3')")
    eid = db.execute(
        "INSERT INTO etapy_katalog (kod, nazwa) VALUES ('e1', 'Etap 1')"
    ).lastrowid
    db.execute(
        "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc, typ_cyklu) "
        "VALUES ('P3', ?, 1, 'jednorazowy')",
        (eid,),
    )
    db.execute(
        "INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc, grupa) "
        "VALUES (?, ?, 1, 'lab')",
        (eid, pid),
    )
    db.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, "
        "dla_szarzy, grupa) VALUES ('P3', ?, ?, 1, 'lab')",
        (eid, pid),
    )
    from mbr.parametry.registry import build_parametry_lab
    plab = _json.dumps(build_parametry_lab(db, "P3"), ensure_ascii=False)
    db.execute(
        "INSERT INTO mbr_templates (produkt, status, parametry_lab, etapy_json) "
        "VALUES ('P3', 'active', ?, '[]')",
        (plab,),
    )
    db.commit()
    ebr_id = create_ebr(db, "P3", "1", "A", "M", 100, "lab_test", typ="szarza")
    rows = db.execute(
        "SELECT * FROM ebr_wyniki WHERE ebr_id=?", (ebr_id,)
    ).fetchall()
    assert len(rows) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ebr_create_jakosciowe_autofill.py -v`
Expected: `test_create_ebr_autoinserts_*` FAILS (no rows). Others may pass trivially.

- [ ] **Step 3: Add helper + wire into `create_ebr`**

In `mbr/laborant/models.py`, add above `create_ebr`:

```python
def _autofill_jakosciowe_wyniki(
    db: sqlite3.Connection,
    ebr_id: int,
    produkt: str,
    parametry_lab_json: str | None,
    operator: str,
) -> int:
    """After EBR creation, seed ebr_wyniki.wartosc_text for typ='jakosciowy'
    params using parametry_etapy.cert_qualitative_result as the default.

    Skips params where cert_qualitative_result is NULL/empty (laborant/KJ
    will fill them later in hero view).

    Returns the number of rows inserted.
    """
    if not parametry_lab_json:
        return 0
    try:
        parametry_lab = json.loads(parametry_lab_json)
    except Exception:
        return 0
    now = datetime.now().isoformat(timespec="seconds")
    inserted = 0
    for sekcja_key, sekcja in parametry_lab.items():
        for pole in sekcja.get("pola", []):
            if pole.get("typ_analityczny") != "jakosciowy":
                continue
            kod = pole.get("kod")
            if not kod:
                continue
            # Look up parametr_id + its cert_qualitative_result for this product.
            row = db.execute(
                """SELECT pe.cert_qualitative_result
                   FROM parametry_analityczne pa
                   JOIN parametry_etapy pe ON pe.parametr_id = pa.id
                   WHERE pa.kod = ? AND pe.produkt = ?
                   LIMIT 1""",
                (kod, produkt),
            ).fetchone()
            default = row["cert_qualitative_result"] if row else None
            if not default:
                continue
            db.execute(
                "INSERT OR IGNORE INTO ebr_wyniki "
                "(ebr_id, sekcja, kod_parametru, tag, wartosc, wartosc_text, "
                " is_manual, dt_wpisu, wpisal) "
                "VALUES (?, ?, ?, ?, NULL, ?, 0, ?, ?)",
                (ebr_id, sekcja_key, kod, pole.get("tag") or kod, default, now, operator),
            )
            inserted += 1
    return inserted
```

Modify `create_ebr` (after the `INSERT INTO ebr_batches`, before `return cur.lastrowid`):

```python
    ebr_id = cur.lastrowid
    # Seed jakosciowy params with their cert_qualitative_result default.
    # Rebuild parametry_lab fresh from DB so typ_analityczny is present even
    # when the MBR's stored snapshot predates PR2 (snapshots are backfilled
    # lazily on admin edits — we don't depend on that here).
    from mbr.parametry.registry import build_parametry_lab
    fresh_plab = build_parametry_lab(db, produkt)
    plab_json = json.dumps(fresh_plab, ensure_ascii=False) if fresh_plab else None
    if plab_json:
        _autofill_jakosciowe_wyniki(db, ebr_id, produkt, plab_json, operator)
    return ebr_id
```

Imports needed at top of `mbr/laborant/models.py`: confirm `json` and `datetime` are already imported.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ebr_create_jakosciowe_autofill.py -v`
Expected: 3/3 PASS.

Also run `pytest tests/test_laborant.py tests/test_laborant_entry_filter.py -v` — no regressions.

- [ ] **Step 5: Commit**

```bash
git add mbr/laborant/models.py tests/test_ebr_create_jakosciowe_autofill.py
git commit -m "feat(laborant): auto-insert ebr_wyniki.wartosc_text for jakosciowy params at create_ebr"
```

---

### Task 5: Backfill script for existing open batches

**Files:**
- Create: `scripts/backfill_jakosciowe_values.py`
- Modify: `deploy/auto-deploy.sh` (add one invocation line)
- Test: `tests/test_backfill_jakosciowe.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_backfill_jakosciowe.py`:

```python
"""PR2: backfill_jakosciowe_values.py seeds ebr_wyniki for existing open batches."""

import json as _json
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

from mbr.models import init_mbr_tables


def _seed_open_ebr_with_jakosciowy(db_path, cert_qr="charakterystyczny"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    pid = conn.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision, opisowe_wartosci) "
        "VALUES ('zapach', 'Zapach', 'jakosciowy', 'lab', 0, ?)",
        (_json.dumps(["charakterystyczny"]),),
    ).lastrowid
    conn.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('PB', 'PB')")
    eid = conn.execute(
        "INSERT INTO etapy_katalog (kod, nazwa) VALUES ('e1', 'Etap 1')"
    ).lastrowid
    conn.execute(
        "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc, typ_cyklu) "
        "VALUES ('PB', ?, 1, 'jednorazowy')",
        (eid,),
    )
    conn.execute(
        "INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc, grupa) "
        "VALUES (?, ?, 1, 'lab')",
        (eid, pid),
    )
    conn.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, "
        "dla_szarzy, grupa) VALUES ('PB', ?, ?, 1, 'lab')",
        (eid, pid),
    )
    conn.execute(
        "INSERT INTO parametry_etapy (produkt, kontekst, parametr_id, "
        "cert_qualitative_result, on_cert) VALUES ('PB', 'e1', ?, ?, 1)",
        (pid, cert_qr),
    )
    # MBR snapshot built from the adapter so typ_analityczny is present
    from mbr.parametry.registry import build_parametry_lab
    plab = _json.dumps(build_parametry_lab(conn, "PB"), ensure_ascii=False)
    mbr_id = conn.execute(
        "INSERT INTO mbr_templates (produkt, status, parametry_lab, etapy_json) "
        "VALUES ('PB', 'active', ?, '[]')",
        (plab,),
    ).lastrowid
    # Open EBR — no ebr_wyniki yet (simulating a batch created pre-PR2)
    ebr_id = conn.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, nr_amidatora, "
        "nr_mieszalnika, wielkosc_szarzy_kg, dt_start, operator, typ, status) "
        "VALUES (?, 'PB__1', '1', 'A', 'M', 100, '2026-04-20', 'lab', 'szarza', 'otwarta')",
        (mbr_id,),
    ).lastrowid
    conn.commit()
    conn.close()
    return ebr_id


def test_backfill_inserts_missing_jakosciowe_rows():
    from scripts import backfill_jakosciowe_values as bfj
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.sqlite"
        ebr_id = _seed_open_ebr_with_jakosciowy(db_path)
        inserted = bfj.run(str(db_path))
        assert inserted == 1
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT wartosc_text FROM ebr_wyniki WHERE ebr_id=?", (ebr_id,)
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0]["wartosc_text"] == "charakterystyczny"


def test_backfill_is_idempotent():
    from scripts import backfill_jakosciowe_values as bfj
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.sqlite"
        _seed_open_ebr_with_jakosciowy(db_path)
        first = bfj.run(str(db_path))
        second = bfj.run(str(db_path))
        assert first == 1
        assert second == 0  # Already filled — no duplicate inserts.


def test_backfill_skips_completed_batches():
    """Completed (zakonczona) batches are out of scope for the backfill."""
    from scripts import backfill_jakosciowe_values as bfj
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.sqlite"
        _seed_open_ebr_with_jakosciowy(db_path)
        # Mark batch as completed
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE ebr_batches SET status='zakonczona'")
        conn.commit()
        conn.close()
        inserted = bfj.run(str(db_path))
        assert inserted == 0


def test_backfill_handles_empty_db():
    from scripts import backfill_jakosciowe_values as bfj
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.sqlite"
        conn = sqlite3.connect(db_path)
        init_mbr_tables(conn)
        conn.close()
        inserted = bfj.run(str(db_path))
        assert inserted == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_backfill_jakosciowe.py -v`
Expected: FAIL — `scripts.backfill_jakosciowe_values` module does not exist.

- [ ] **Step 3: Create the script**

Create `scripts/backfill_jakosciowe_values.py`:

```python
"""Backfill: seed ebr_wyniki.wartosc_text for existing open batches' jakosciowy params.

Idempotent — uses INSERT OR IGNORE guarded by UNIQUE(ebr_id, sekcja, kod_parametru).
Skips completed batches (status='zakonczona') and rows already present.

Run via auto-deploy.sh or manually:
    python -m scripts.backfill_jakosciowe_values --db data/batch_db.sqlite
"""
from __future__ import annotations

import argparse
import json as _json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def run(db_path: str) -> int:
    """Run backfill on db at db_path. Returns number of rows inserted."""
    if not Path(db_path).exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 0
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    inserted = 0
    now = datetime.now().isoformat(timespec="seconds")
    # Open batches — we rebuild parametry_lab fresh per batch to pick up
    # typ_analityczny even when the stored snapshot predates PR2.
    from mbr.parametry.registry import build_parametry_lab
    rows = conn.execute("""
        SELECT eb.ebr_id, eb.operator, mt.produkt
          FROM ebr_batches eb
          JOIN mbr_templates mt ON mt.mbr_id = eb.mbr_id
         WHERE COALESCE(eb.status, '') != 'zakonczona'
    """).fetchall()
    for row in rows:
        parametry_lab = build_parametry_lab(conn, row["produkt"]) or {}
        for sekcja_key, sekcja in parametry_lab.items():
            for pole in sekcja.get("pola", []):
                if pole.get("typ_analityczny") != "jakosciowy":
                    continue
                kod = pole.get("kod")
                if not kod:
                    continue
                default_row = conn.execute(
                    """SELECT pe.cert_qualitative_result
                         FROM parametry_analityczne pa
                         JOIN parametry_etapy pe ON pe.parametr_id = pa.id
                        WHERE pa.kod = ? AND pe.produkt = ?
                        LIMIT 1""",
                    (kod, row["produkt"]),
                ).fetchone()
                default = default_row["cert_qualitative_result"] if default_row else None
                if not default:
                    continue
                cur = conn.execute(
                    """INSERT OR IGNORE INTO ebr_wyniki
                       (ebr_id, sekcja, kod_parametru, tag, wartosc, wartosc_text,
                        is_manual, dt_wpisu, wpisal)
                       VALUES (?, ?, ?, ?, NULL, ?, 0, ?, ?)""",
                    (row["ebr_id"], sekcja_key, kod, pole.get("tag") or kod,
                     default, now, row["operator"] or "backfill"),
                )
                if cur.rowcount > 0:
                    inserted += 1
    conn.commit()
    conn.close()
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/batch_db.sqlite",
                        help="Path to SQLite DB (default: data/batch_db.sqlite)")
    args = parser.parse_args()
    n = run(args.db)
    print(f"backfill_jakosciowe_values: inserted {n} ebr_wyniki rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_backfill_jakosciowe.py -v`
Expected: 4/4 PASS.

- [ ] **Step 5: Register in auto-deploy.sh**

Open `/Users/tbk/Desktop/lims-clean/deploy/auto-deploy.sh`. After the existing backfill invocations (search for `backfill_cert_name_en.py`), add:

```bash
/opt/lims/venv/bin/python -m scripts.backfill_jakosciowe_values --db data/batch_db.sqlite
```

Place it alongside the other `backfill_*` calls so it runs every deploy (safe because idempotent).

- [ ] **Step 6: Commit**

```bash
git add scripts/backfill_jakosciowe_values.py tests/test_backfill_jakosciowe.py deploy/auto-deploy.sh
git commit -m "feat(scripts): backfill jakosciowy values for existing open batches"
```

---

### Task 6: Full suite + merge-ready verification

**Files:**
- No code changes — just verification.

- [ ] **Step 1: Run full test suite**

Run: `cd /Users/tbk/Desktop/lims-clean && pytest`
Expected: All tests pass (includes PR1's 873-ish + PR2's new ~15). 0 failures.

- [ ] **Step 2: Review branch commits**

Run: `git log --oneline main..HEAD`
Expected: PR1 commits + 5 PR2 commits (Task 1-5), each independently describing its work.

- [ ] **Step 3: Verify manual regression points**

Start dev server briefly (optional, if UI is accessible):
- Seed a `jakosciowy` param + bind to a product's pipeline + set `cert_qualitative_result`.
- Create a new EBR — confirm `ebr_wyniki` has a row for the jakosciowy kod with the default `wartosc_text`.
- Open the entry form for that open EBR — confirm the jakosciowy field is hidden; the numeric params are visible.
- Mark the batch `zakonczona` manually (DB update) and reload — all params visible (hero mode).

If dev server not feasible, document that as "covered by tests, manual verification pending merge".

- [ ] **Step 4: Commit progress marker (optional)**

```bash
# No commit — branch already reflects the end state.
```

---

## Open Questions / Deferrals

- **Entry vs hero discriminator:** This plan uses `ebr_row["status"] != "zakonczona"` to decide whether to filter. Confirm this matches the app's status vocabulary (run `grep -r "status.*zakonczona\|'zakonczona'" mbr/laborant/` to verify). If another value is used (e.g., `"DONE"`, `"completed"`), adjust Task 3 Step 4 accordingly.

- **`parametry_lab` snapshot migration:** Existing MBR templates have `parametry_lab` without `typ_analityczny`. The entry filter (Task 3) works regardless because it operates on FRESH `build_pipeline_context` output, not on the stored snapshot. `create_ebr` (Task 4) and the backfill (Task 5) also rebuild `parametry_lab` on the fly via `build_parametry_lab(produkt)` so they see the new key. Stored snapshots get refreshed lazily whenever admin edits any parameter (existing behavior in `api_parametry_update`). No separate migration step needed.

- **Autofill scope:** Task 4 auto-fills from `parametry_etapy.cert_qualitative_result`. For products that use cert variants (`parametry_cert.qualitative_result` per variant), the default is still the base-cert value. Variant-specific defaults would need a separate resolver. This is out of scope for PR2 — spec accepts one default per product.
