# Parametry Editor — Rejestr Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Przepisać zakładkę Rejestr w `/admin/parametry` na master-detail layout spójny z cert editor (Phase A/B/C już merged); rozszerzyć cert editor o 4-tą parę dual-field dla `format` (precyzja); rozszerzyć skrypt migracji o cleanup `format` overrides.

**Architecture:** Reuse istniejących komponentów cert editor (klasy CSS `.wc-md-*`, helpers `_rtHtml`, `_esc`, `_fmtOptions`, dirty tracking, banner usage-impact). Backend: rozszerzenie 2 endpointów (PUT diff keys, GET usage-impact returns lists), nowy POST audit, modyfikacja `get_cert_params` o format dual-fields. Frontend: jeden plik `mbr/templates/parametry_editor.html` (~800 linii) — sekcja Rejestr przepisana, sekcje Etapy + Produkty nietknięte.

**Tech Stack:** Flask + SQLite (raw sqlite3); Jinja2 + vanilla JS; pytest TDD na backend; manual browser verification dla frontend.

**Spec:** `docs/superpowers/specs/2026-04-28-parametry-editor-rejestr-redesign-design.md` (przeczytaj przed startem).

---

## File Structure

**Backend (Phase A):**
- Modify `mbr/parametry/routes.py`:
  - `api_parametry_update` — rozszerzenie diff_fields keys o `precision` + `aktywny`
  - `api_parametry_create` — dodanie audit `EVENT_PARAMETR_CREATED`
  - `api_parametry_usage_impact` — extension o listy produktów
- Modify `mbr/parametry/registry.py`:
  - `get_cert_params` / `get_cert_variant_params` — dodanie `format_global` + `format_override`
- Modify `mbr/certs/routes.py`:
  - `api_cert_config_product_get` — przepuścić nowe pola w response
- Tests: `tests/test_parametry_audit_extended.py`, `tests/test_parametry_usage_impact_lists.py`, `tests/test_cert_format_dual_field.py`

**Frontend (Phase B):**
- Modify `mbr/templates/parametry_editor.html` — sekcja Rejestr (`#panel-def`) przepisana, reuse `.wc-md-*` CSS z cert editor (już global w base.html — sprawdzić; jeśli nie, zaimportować lub zduplikować w head)

**Cert editor format (Phase C):**
- Modify `mbr/templates/admin/wzory_cert.html`:
  - `_dualRow` — dodać 4-ty wiersz dla `format`
  - `_buildCertConfigPayload` — dodać `format_override`
  - Wprowadzić `_precisionOptionsWithExamples` helper
- No new tests — manual browser

**Migration (Phase D):**
- Modify `scripts/migrate_cert_override_cleanup.py` — rozszerzyć o `format`
- Modify `tests/test_migrate_cert_override_cleanup.py` — 2 nowe testy

---

## Phase A — Backend (TDD)

### Task A1: Audit aktywny + precision changes in PUT /api/parametry/<id>

**Files:**
- Modify: `mbr/parametry/routes.py` (function `api_parametry_update`, line ~155)
- Test: `tests/test_parametry_audit_extended.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_parametry_audit_extended.py
"""PUT /api/parametry/<id> audit covers precision + aktywny in addition to label/name_en/method_code."""
import json
import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed(db):
    db.execute("DELETE FROM parametry_analityczne")
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, name_en, method_code, precision, aktywny) "
        "VALUES (1, 'nd20', 'Wsp. zalamania', 'bezposredni', 'Refractive index', 'PN-EN ISO 5661', 4, 1)"
    )
    db.commit()


def _admin_client(monkeypatch, db):
    import mbr.db, mbr.parametry.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.parametry.routes, "db_session", fake_db_session)

    from mbr.app import app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "admin", "rola": "admin"}
    return client


def test_put_parametry_audit_precision_change(monkeypatch, db):
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1", json={"precision": 2})
    assert rv.status_code == 200

    rows = db.execute(
        "SELECT diff_json FROM audit_log WHERE event_type='parametr.updated'"
    ).fetchall()
    assert len(rows) == 1
    diff = json.loads(rows[0]["diff_json"])
    assert diff == [{"pole": "precision", "stara": 4, "nowa": 2}]


def test_put_parametry_audit_aktywny_toggle(monkeypatch, db):
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1", json={"aktywny": 0})
    assert rv.status_code == 200

    rows = db.execute(
        "SELECT diff_json FROM audit_log WHERE event_type='parametr.updated'"
    ).fetchall()
    assert len(rows) == 1
    diff = json.loads(rows[0]["diff_json"])
    assert diff == [{"pole": "aktywny", "stara": 1, "nowa": 0}]


def test_put_parametry_audit_combined_label_precision(monkeypatch, db):
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1", json={"label": "Wsp. zalamania nD20", "precision": 5})
    assert rv.status_code == 200

    rows = db.execute(
        "SELECT diff_json FROM audit_log WHERE event_type='parametr.updated'"
    ).fetchall()
    assert len(rows) == 1
    diff = json.loads(rows[0]["diff_json"])
    fields = sorted(d["pole"] for d in diff)
    assert fields == ["label", "precision"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_parametry_audit_extended.py -v
```

Expected: 3 failures — current diff_fields includes only `["label", "name_en", "method_code"]`.

- [ ] **Step 3: Extend diff_fields keys + snapshot SELECT**

In `mbr/parametry/routes.py`, find:

```python
        # Snapshot old state for audit diff (admin-only — see post-UPDATE block).
        old_audit = None
        if rola == "admin":
            old_audit = db.execute(
                "SELECT label, name_en, method_code FROM parametry_analityczne WHERE id=?",
                (param_id,),
            ).fetchone()
```

Replace SELECT to include precision + aktywny:

```python
        # Snapshot old state for audit diff (admin-only — see post-UPDATE block).
        old_audit = None
        if rola == "admin":
            old_audit = db.execute(
                "SELECT label, name_en, method_code, precision, aktywny FROM parametry_analityczne WHERE id=?",
                (param_id,),
            ).fetchone()
```

Find the post-UPDATE audit block:

```python
        if rola == "admin":
            new_audit = db.execute(
                "SELECT label, name_en, method_code FROM parametry_analityczne WHERE id=?",
                (param_id,),
            ).fetchone()
            diff = diff_fields(dict(old_audit), dict(new_audit), ["label", "name_en", "method_code"])
```

Replace with:

```python
        if rola == "admin":
            new_audit = db.execute(
                "SELECT label, name_en, method_code, precision, aktywny FROM parametry_analityczne WHERE id=?",
                (param_id,),
            ).fetchone()
            diff = diff_fields(dict(old_audit), dict(new_audit), ["label", "name_en", "method_code", "precision", "aktywny"])
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_parametry_audit_extended.py -v
```

Expected: 3 passing.

- [ ] **Step 5: Run regression suite to verify A1 of cert editor still works**

```bash
pytest tests/test_parametry_registry_audit.py tests/test_parametry_grupa_api.py tests/test_parametry_opisowe_wartosci.py tests/test_parametry_usage_impact.py -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add mbr/parametry/routes.py tests/test_parametry_audit_extended.py
git commit -m "feat(parametry): audit precision + aktywny changes in PUT /api/parametry/<id>"
```

---

### Task A2: POST /api/parametry emits EVENT_PARAMETR_CREATED audit

**Files:**
- Modify: `mbr/parametry/routes.py` (function `api_parametry_create`)
- Test: `tests/test_parametry_create_audit.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_parametry_create_audit.py
"""POST /api/parametry emits parametr.created audit event."""
import json
import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _admin_client(monkeypatch, db):
    import mbr.db, mbr.parametry.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.parametry.routes, "db_session", fake_db_session)

    from mbr.app import app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "admin", "rola": "admin"}
    return client


def test_post_parametry_emits_create_audit(monkeypatch, db):
    db.execute("DELETE FROM parametry_analityczne")
    db.commit()
    client = _admin_client(monkeypatch, db)

    rv = client.post("/api/parametry", json={
        "kod": "test_kod",
        "label": "Test parameter",
        "typ": "bezposredni",
    })
    assert rv.status_code == 200, rv.get_json()
    new_id = rv.get_json()["id"]

    rows = db.execute(
        "SELECT entity_type, entity_id, entity_label, payload_json "
        "FROM audit_log WHERE event_type='parametr.created'"
    ).fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["entity_type"] == "parametr"
    assert r["entity_id"] == new_id
    assert r["entity_label"] == "test_kod"
    payload = json.loads(r["payload_json"])
    assert payload["kod"] == "test_kod"
    assert payload["label"] == "Test parameter"
    assert payload["typ"] == "bezposredni"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_parametry_create_audit.py -v
```

Expected: 1 failure — no audit row.

- [ ] **Step 3: Add audit emission in api_parametry_create**

In `mbr/parametry/routes.py`, find `api_parametry_create` (around line 200). After successful INSERT and before `db.commit()`, add audit. Find:

```python
            cur = db.execute(
                "INSERT INTO parametry_analityczne (kod, label, skrot, typ, jednostka, precision, name_en, method_code, grupa, opisowe_wartosci) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kod, label, data.get("skrot", ""), typ, data.get("jednostka", ""),
                 data.get("precision", 2), data.get("name_en", ""), data.get("method_code", ""),
                 grupa, opisowe_json),
            )
            db.commit()
```

Replace with:

```python
            cur = db.execute(
                "INSERT INTO parametry_analityczne (kod, label, skrot, typ, jednostka, precision, name_en, method_code, grupa, opisowe_wartosci) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kod, label, data.get("skrot", ""), typ, data.get("jednostka", ""),
                 data.get("precision", 2), data.get("name_en", ""), data.get("method_code", ""),
                 grupa, opisowe_json),
            )
            new_id = cur.lastrowid
            log_event(
                EVENT_PARAMETR_CREATED,
                entity_type="parametr",
                entity_id=new_id,
                entity_label=kod,
                payload={"kod": kod, "label": label, "typ": typ, "grupa": grupa},
                db=db,
            )
            db.commit()
```

Also extend imports at top of file. Find:

```python
from mbr.shared.audit import log_event, EVENT_PARAMETR_UPDATED, diff_fields
```

Replace with:

```python
from mbr.shared.audit import log_event, EVENT_PARAMETR_UPDATED, EVENT_PARAMETR_CREATED, diff_fields
```

Update the return at the end of `api_parametry_create` — replace `cur.lastrowid` with `new_id`:

```python
    return jsonify({"ok": True, "id": new_id})
```

- [ ] **Step 4: Run test to verify pass**

```bash
pytest tests/test_parametry_create_audit.py -v
```

Expected: 1 passing.

- [ ] **Step 5: Commit**

```bash
git add mbr/parametry/routes.py tests/test_parametry_create_audit.py
git commit -m "feat(parametry): audit parametr.created on POST /api/parametry"
```

---

### Task A3: Extend usage-impact endpoint with product lists

**Files:**
- Modify: `mbr/parametry/routes.py` (function `api_parametry_usage_impact`)
- Test: `tests/test_parametry_usage_impact_lists.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_parametry_usage_impact_lists.py
"""GET /api/parametry/<id>/usage-impact returns product lists alongside counts."""
import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed(db):
    db.execute("DELETE FROM parametry_analityczne")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (1, 'nd20', 'nD20', 'bezposredni')")
    for produkt, dn in [("PROD_A", "Produkt A"), ("PROD_B", "Produkt B")]:
        db.execute("INSERT INTO produkty (nazwa, display_name) VALUES (?, ?)", (produkt, dn))
        db.execute("INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, variant_id) VALUES (?, 1, 0, NULL)", (produkt,))
    db.execute("INSERT INTO parametry_etapy (parametr_id, produkt, kontekst, kolejnosc) VALUES (1, 'PROD_A', 'analiza_koncowa', 0)")
    db.execute("INSERT INTO parametry_etapy (parametr_id, produkt, kontekst, kolejnosc) VALUES (1, 'PROD_A', 'sulfonowanie', 1)")
    db.execute("INSERT INTO parametry_etapy (parametr_id, produkt, kontekst, kolejnosc) VALUES (1, 'PROD_C', 'analiza_koncowa', 0)")
    db.commit()


def _client(monkeypatch, db):
    import mbr.db, mbr.parametry.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.parametry.routes, "db_session", fake_db_session)

    from mbr.app import app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "admin", "rola": "admin"}
    return client


def test_usage_impact_includes_cert_products_list(monkeypatch, db):
    _seed(db)
    client = _client(monkeypatch, db)

    rv = client.get("/api/parametry/1/usage-impact")
    assert rv.status_code == 200
    j = rv.get_json()
    assert j["cert_products_count"] == 2
    assert "cert_products" in j
    assert sorted(p["key"] for p in j["cert_products"]) == ["PROD_A", "PROD_B"]
    a = next(p for p in j["cert_products"] if p["key"] == "PROD_A")
    assert a["display_name"] == "Produkt A"


def test_usage_impact_includes_mbr_products_list_with_stages(monkeypatch, db):
    _seed(db)
    client = _client(monkeypatch, db)

    rv = client.get("/api/parametry/1/usage-impact")
    j = rv.get_json()
    assert j["mbr_products_count"] == 2  # PROD_A + PROD_C
    assert j["mbr_bindings_count"] == 3  # PROD_A×2 + PROD_C×1
    by_key = {p["key"]: p for p in j["mbr_products"]}
    assert sorted(by_key["PROD_A"]["stages"]) == ["analiza_koncowa", "sulfonowanie"]
    assert by_key["PROD_C"]["stages"] == ["analiza_koncowa"]


def test_usage_impact_empty_lists_for_unused_param(monkeypatch, db):
    _seed(db)
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (2, 'orphan', 'orphan', 'bezposredni')")
    db.commit()
    client = _client(monkeypatch, db)

    rv = client.get("/api/parametry/2/usage-impact")
    j = rv.get_json()
    assert j["cert_products_count"] == 0
    assert j["mbr_products_count"] == 0
    assert j["cert_products"] == []
    assert j["mbr_products"] == []
    assert j["mbr_bindings_count"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_parametry_usage_impact_lists.py -v
```

Expected: 3 failures — `cert_products` / `mbr_products` keys missing.

- [ ] **Step 3: Extend endpoint**

In `mbr/parametry/routes.py`, find `api_parametry_usage_impact`:

```python
@parametry_bp.route("/api/parametry/<int:param_id>/usage-impact")
@login_required
def api_parametry_usage_impact(param_id):
    """Return product counts for usage banner: how many cert + mbr products use this param."""
    with db_session() as db:
        exists = db.execute(
            "SELECT 1 FROM parametry_analityczne WHERE id=?", (param_id,)
        ).fetchone()
        if not exists:
            return jsonify({"error": "Parametr not found"}), 404

        cert_count = db.execute(
            "SELECT COUNT(DISTINCT produkt) AS c FROM parametry_cert WHERE parametr_id=?",
            (param_id,),
        ).fetchone()["c"]
        mbr_count = db.execute(
            "SELECT COUNT(DISTINCT produkt) AS c FROM parametry_etapy WHERE parametr_id=?",
            (param_id,),
        ).fetchone()["c"]
    return jsonify({
        "cert_products_count": cert_count,
        "mbr_products_count": mbr_count,
    })
```

Replace with:

```python
@parametry_bp.route("/api/parametry/<int:param_id>/usage-impact")
@login_required
def api_parametry_usage_impact(param_id):
    """Return product counts + lists for the registry-edit banner and Powiązania accordion.

    Lists are shaped for direct UI consumption:
    - cert_products: distinct produkt rows from parametry_cert (with display_name JOIN)
    - mbr_products: distinct produkt rows from parametry_etapy with stages array
    - mbr_bindings_count: total parametry_etapy rows (= produkt × stages combinations)
    """
    with db_session() as db:
        exists = db.execute(
            "SELECT 1 FROM parametry_analityczne WHERE id=?", (param_id,)
        ).fetchone()
        if not exists:
            return jsonify({"error": "Parametr not found"}), 404

        # Cert products (distinct produkt + display_name JOIN)
        cert_rows = db.execute(
            """SELECT DISTINCT pc.produkt AS key,
                      COALESCE(p.display_name, pc.produkt) AS display_name
               FROM parametry_cert pc
               LEFT JOIN produkty p ON p.nazwa = pc.produkt
               WHERE pc.parametr_id = ?
               ORDER BY pc.produkt""",
            (param_id,),
        ).fetchall()
        cert_products = [{"key": r["key"], "display_name": r["display_name"]} for r in cert_rows]

        # MBR products with stages (group by produkt → stages list)
        mbr_rows = db.execute(
            """SELECT pe.produkt AS key, pe.kontekst AS stage
               FROM parametry_etapy pe
               WHERE pe.parametr_id = ?
               ORDER BY pe.produkt, pe.kontekst""",
            (param_id,),
        ).fetchall()
        mbr_grouped = {}
        for r in mbr_rows:
            mbr_grouped.setdefault(r["key"], []).append(r["stage"])
        mbr_products = [{"key": k, "stages": v} for k, v in mbr_grouped.items()]
        mbr_bindings_count = len(mbr_rows)

    return jsonify({
        "cert_products_count": len(cert_products),
        "cert_products": cert_products,
        "mbr_products_count": len(mbr_products),
        "mbr_products": mbr_products,
        "mbr_bindings_count": mbr_bindings_count,
    })
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_parametry_usage_impact_lists.py tests/test_parametry_usage_impact.py -v
```

Expected: 3 + 3 = 6 passing (existing test_parametry_usage_impact tests check the count fields which are preserved).

- [ ] **Step 5: Commit**

```bash
git add mbr/parametry/routes.py tests/test_parametry_usage_impact_lists.py
git commit -m "feat(parametry): /api/parametry/<id>/usage-impact returns product lists for Powiązania"
```

---

### Task A4: get_cert_params returns format_global + format_override

**Files:**
- Modify: `mbr/parametry/registry.py` (functions `get_cert_params` + `get_cert_variant_params`)
- Test: `tests/test_cert_format_dual_field.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_cert_format_dual_field.py
"""get_cert_params returns format_global + format_override (4-th dual-field pair after name_pl/name_en/method)."""
import sqlite3
import pytest

from mbr.models import init_mbr_tables
from mbr.parametry.registry import get_cert_params, get_cert_variant_params


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed(db):
    db.execute("DELETE FROM parametry_analityczne")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ, precision) VALUES (1, 'nd20', 'nD20', 'bezposredni', 4)")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ, precision) VALUES (2, 'lk', 'LK', 'bezposredni', 2)")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('TEST', 'Test')")
    # Row 1: format NULL → inherit from registry precision (4)
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, format, variant_id) "
        "VALUES ('TEST', 1, 0, NULL, NULL)"
    )
    # Row 2: format override = "1" (different from registry precision = 2)
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, format, variant_id) "
        "VALUES ('TEST', 2, 1, '1', NULL)"
    )
    db.commit()


def test_get_cert_params_returns_format_dual_fields(db):
    _seed(db)
    rows = get_cert_params(db, "TEST")
    assert len(rows) == 2

    r0 = rows[0]
    assert r0["format_global"] == "4"  # registry precision as string
    assert r0["format_override"] is None
    assert r0["format"] == "1"  # legacy effective fallback (current behaviour: NULL → "1")

    r1 = rows[1]
    assert r1["format_global"] == "2"
    assert r1["format_override"] == "1"
    assert r1["format"] == "1"  # override wins


def test_get_cert_variant_params_returns_format_dual_fields(db):
    _seed(db)
    db.execute("INSERT INTO cert_variants (id, produkt, variant_id, label, flags, kolejnosc) VALUES (10, 'TEST', 'lv', 'LV', '[]', 0)")
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, format, variant_id) "
        "VALUES ('TEST', 1, 0, '3', 10)"
    )
    db.commit()

    rows = get_cert_variant_params(db, 10)
    assert len(rows) == 1
    r = rows[0]
    assert r["format_global"] == "4"
    assert r["format_override"] == "3"
    assert r["format"] == "3"


def test_get_cert_params_format_global_empty_when_precision_null(db):
    """If registry precision is NULL, format_global should be '' (not 'None' string)."""
    db.execute("DELETE FROM parametry_analityczne")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ, precision) VALUES (1, 'x', 'X', 'bezposredni', NULL)")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('TEST', 'Test')")
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, variant_id) "
        "VALUES ('TEST', 1, 0, NULL)"
    )
    db.commit()

    rows = get_cert_params(db, "TEST")
    assert rows[0]["format_global"] == ""
    assert rows[0]["format_override"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cert_format_dual_field.py -v
```

Expected: 3 failures — `KeyError: 'format_global'`.

- [ ] **Step 3: Modify get_cert_params**

In `mbr/parametry/registry.py`, find the SELECT in `get_cert_params` (around line 239):

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
```

Replace with (add `pa.precision`):

```python
    rows = db.execute("""
        SELECT
            pa.kod, pa.label, pa.name_en, pa.method_code, pa.precision AS pa_precision,
            pa.typ, pa.grupa,
            pc.requirement, pc.format, pc.qualitative_result,
            pc.kolejnosc, pc.parametr_id,
            pc.name_pl AS cert_name_pl, pc.name_en AS cert_name_en, pc.method AS cert_method
        FROM parametry_cert pc
        JOIN parametry_analityczne pa ON pa.id = pc.parametr_id
        WHERE pc.produkt = ? AND pc.variant_id IS NULL
        ORDER BY pc.kolejnosc
    """, (produkt,)).fetchall()
```

In the return list comprehension, add `format_global` and `format_override` next to other dual-fields:

```python
    return [
        {
            "kod": r["kod"],
            "parametr_id": r["parametr_id"],
            "typ": r["typ"],
            "grupa": r["grupa"],
            # Global registry values (always present, may be empty string)
            "name_pl_global": r["label"] or "",
            "name_en_global": r["name_en"] or "",
            "method_global": r["method_code"] or "",
            "format_global": str(r["pa_precision"]) if r["pa_precision"] is not None else "",
            # Per-product overrides (raw — None means "inherit")
            "name_pl_override": r["cert_name_pl"],
            "name_en_override": r["cert_name_en"],
            "method_override": r["cert_method"],
            "format_override": r["format"],
            # Effective values (legacy — preserved for cert generator backward compat)
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

- [ ] **Step 4: Modify get_cert_variant_params identically**

Apply the same SELECT addition (`pa.precision AS pa_precision`) and return-comprehension changes (`format_global` + `format_override`) to `get_cert_variant_params`.

- [ ] **Step 5: Run tests to verify pass**

```bash
pytest tests/test_cert_format_dual_field.py tests/test_cert_params_dual_field.py -v
```

Expected: 3 + 4 = 7 passing.

- [ ] **Step 6: Run regression suite**

```bash
pytest tests/test_certs.py tests/test_cert_template_render.py tests/test_cert_jakosciowy_render.py tests/test_cert_editor_atomicity.py tests/test_cert_alias_api.py tests/test_cert_audit_history.py -q
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add mbr/parametry/registry.py tests/test_cert_format_dual_field.py
git commit -m "feat(parametry): get_cert_params returns format_global + format_override"
```

---

### Task A5: api_cert_config_product_get exposes format dual-fields

**Files:**
- Modify: `mbr/certs/routes.py` (handler `api_cert_config_product_get`, lines around 374-396 for base, 446-466 for variant)
- Test: `tests/test_cert_config_response_format_dual.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_cert_config_response_format_dual.py
"""GET /api/cert/config/product/<key> exposes format_global + format_override."""
import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed(db):
    db.execute("DELETE FROM parametry_analityczne")
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, precision) "
        "VALUES (1, 'nd20', 'nD20', 'bezposredni', 4)"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('TEST', 'Test')")
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) VALUES ('TEST', 'base', 'Base', '[]', 0)"
    )
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, format, variant_id) "
        "VALUES ('TEST', 1, 0, '2', NULL)"
    )
    db.commit()


def _admin_client(monkeypatch, db):
    import mbr.db, mbr.certs.routes, mbr.parametry.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.certs.routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.parametry.routes, "db_session", fake_db_session)

    from mbr.app import app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "admin", "rola": "admin"}
    return client


def test_cert_config_get_includes_format_dual_fields(monkeypatch, db):
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.get("/api/cert/config/product/TEST")
    assert rv.status_code == 200
    j = rv.get_json()
    p = j["product"]["parameters"][0]
    assert p["format_global"] == "4"  # registry precision
    assert p["format_override"] == "2"  # cert config override
    assert p["format"] == "2"  # legacy effective preserved
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_cert_config_response_format_dual.py -v
```

Expected: 1 failure — `KeyError: 'format_global'`.

- [ ] **Step 3: Update SELECT + response dict in api_cert_config_product_get**

In `mbr/certs/routes.py`, find the base-params SELECT (around line 354):

```python
            "SELECT pc.parametr_id, pc.kolejnosc, pc.requirement, pc.format, "
            "pc.qualitative_result, pc.name_pl, pc.name_en, pc.method, "
            "pa.kod, pa.label AS pa_label, pa.name_en AS pa_name_en, "
            "pa.method_code AS pa_method_code "
            "FROM parametry_cert pc "
```

Replace with (add `pa.precision AS pa_precision`):

```python
            "SELECT pc.parametr_id, pc.kolejnosc, pc.requirement, pc.format, "
            "pc.qualitative_result, pc.name_pl, pc.name_en, pc.method, "
            "pa.kod, pa.label AS pa_label, pa.name_en AS pa_name_en, "
            "pa.method_code AS pa_method_code, pa.precision AS pa_precision "
            "FROM parametry_cert pc "
```

In the response param dict (lines 374-391), add 2 new fields after `method_override`:

```python
            param = {
                "id": pid,
                "parametr_id": bp["parametr_id"],
                "name_pl": bp["name_pl"] or bp["pa_label"] or "",
                "name_en": name_en,
                "requirement": bp["requirement"] or "",
                "method": bp["method"] or bp["pa_method_code"] or "",
                "format": bp["format"] or "1",
                "data_field": bp["kod"] or "",
                # Dual-field surface for the editor (Cert Editor Redesign A4):
                # globals always present, overrides preserved raw (None = inherit,
                # "" = explicit blank). Legacy fields above keep existing consumers working.
                "name_pl_global": bp["pa_label"] or "",
                "name_en_global": bp["pa_name_en"] or "",
                "method_global": bp["pa_method_code"] or "",
                "format_global": str(bp["pa_precision"]) if bp["pa_precision"] is not None else "",
                "name_pl_override": bp["name_pl"],
                "name_en_override": bp["name_en"],
                "method_override": bp["method"],
                "format_override": bp["format"],
            }
```

- [ ] **Step 4: Apply same changes to variant add_parameters block**

Find the variant SELECT (around line 434) and add `pa.precision AS pa_precision`. In the variant param dict (lines 446-466), add the same `format_global` / `format_override` fields next to other dual-fields.

- [ ] **Step 5: Run test to verify pass**

```bash
pytest tests/test_cert_config_response_format_dual.py tests/test_cert_config_response_dual_field.py -v
```

Expected: 1 + 3 = 4 passing.

- [ ] **Step 6: Commit**

```bash
git add mbr/certs/routes.py tests/test_cert_config_response_format_dual.py
git commit -m "feat(certs): cert config GET exposes format_global + format_override (A5)"
```

---

## Phase B — Frontend Rejestr master-detail

> **Phase B note:** Manual browser verification at `http://localhost:5001/admin/parametry`. Each task verifies: hard reload, click „Rejestr" tab, observe expected behavior.
>
> CSS classes `.wc-md-*` from cert editor will be reused — they're defined in `mbr/templates/admin/wzory_cert.html` (scoped to that page). Need to copy them into `parametry_editor.html` head, OR move shared `.wc-md-*` styles to a static CSS file in `mbr/static/`. **Decision:** copy into `parametry_editor.html` head (parallel to cert editor's pattern — single-page templates own their styles). Reuse names: `.wc-md`, `.wc-md-list`, `.wc-md-item`, etc.

### Task B1: Master-detail HTML+CSS scaffold for Rejestr panel

**Files:**
- Modify: `mbr/templates/parametry_editor.html` (replace `#panel-def` block, add CSS in `<style>`)

- [ ] **Step 1: Add CSS block** (copy `.wc-md-*` classes from `mbr/templates/admin/wzory_cert.html` lines ~159-329)

Open `mbr/templates/admin/wzory_cert.html`, locate the `/* ═══ Master-detail (Parametry + Warianty) — refined ═══ */` block. Copy from that comment to the line before `</style>` (before this comment in cert editor: nothing relevant to copy after the `.wc-md-*` block ends with `.wc-md-detail-del:hover`). Paste into `mbr/templates/parametry_editor.html` `<style>` section, near the end.

- [ ] **Step 2: Replace `#panel-def` HTML block**

In `mbr/templates/parametry_editor.html`, find `<div id="panel-def" style="display:none;">` (around line 197). Replace the entire `<div id="panel-def">...</div>` block (down to line ~242 closing `</div>` of `panel-def`) with:

```html
<div id="panel-def" style="display:none;">
  <div class="wc-md">
    <!-- Left: list -->
    <div class="wc-md-list">
      <div class="wc-md-search">
        <input id="pe-rej-filter" type="text" placeholder="Filtruj parametry..." oninput="rejFilter(this.value)">
      </div>
      <div id="pe-rej-pills" style="display:flex;flex-wrap:wrap;gap:4px;padding:8px;border-bottom:1px solid var(--border);background:var(--surface);"></div>
      <div class="wc-md-list-body" id="pe-rej-list-body"></div>
      <div class="wc-md-add" onclick="rejOpenAddModal()">+ Dodaj parametr</div>
    </div>

    <!-- Right: detail editor -->
    <div class="wc-md-detail" id="pe-rej-detail">
      <div class="wc-md-detail-empty">Wybierz parametr z listy po lewej</div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Add typ-pill CSS**

Append to `<style>`:

```css
/* Typ filter pills (Rejestr) */
.pe-pill {
  font-size: 9px; padding: 4px 10px; border-radius: 12px;
  cursor: pointer; user-select: none;
  background: var(--surface-alt); color: var(--text-dim);
  border: 1px solid var(--border); font-weight: 600;
  text-transform: uppercase; letter-spacing: .4px;
  transition: background .12s ease, color .12s ease, border-color .12s ease;
}
.pe-pill:hover { border-color: var(--teal); color: var(--teal); }
.pe-pill.active { background: var(--teal); color: #fff; border-color: var(--teal); }
.pe-pill.reset { background: transparent; }
.pe-pill.reset.active { background: var(--text-sec); border-color: var(--text-sec); }
```

- [ ] **Step 4: Verify in browser (after starting dev server)**

```bash
MBR_SECRET_KEY=dev-test python -m mbr.app &
```

Navigate to `/admin/parametry` → Rejestr tab. Expected: empty master-detail layout (search bar at top, empty pills row, empty list, „Wybierz parametr…" placeholder right side). No JS errors.

The list will be empty until B2 wires JS. „+ Dodaj parametr" click does nothing (rejOpenAddModal not defined yet — silent failure or "function not defined" console error).

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/parametry_editor.html
git commit -m "feat(parametry-rejestr): master-detail HTML+CSS scaffold (B1)"
```

---

### Task B2: renderRejList + filter input + typ pills

**Files:**
- Modify: `mbr/templates/parametry_editor.html` (JS section)

- [ ] **Step 1: Add state vars + render functions in `<script>` block**

Find existing JS section (after `var _isAdmin = ...`). After the existing functions, before `loadDef()`, insert:

```javascript
/* ═══ REJESTR master-detail (B2) ═══ */

var _rejParams = [];
var _rejSelectedId = null;
var _rejFilter = '';
var _rejTypFilter = new Set();  // empty = show all
var _REJ_TYPS = ['bezposredni', 'titracja', 'obliczeniowy', 'jakosciowy', 'srednia'];
var _REJ_TYP_LABELS = {
  'bezposredni': 'Bezpośredni',
  'titracja': 'Titracja',
  'obliczeniowy': 'Obliczeniowy',
  'jakosciowy': 'Jakościowy',
  'srednia': 'Średnia',
};

function _rejEsc(s) { if (s == null) return ''; var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function _rejRtHtml(text) {
  if (!text) return '';
  var out = '', re = /(\^\{[^}]*\}|_\{[^}]*\})/g, last = 0, m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out += _rejEsc(text.slice(last, m.index));
    var inner = m[0].slice(2, -1);
    out += (m[0][0] === '^') ? '<sup>' + _rejEsc(inner) + '</sup>' : '<sub>' + _rejEsc(inner) + '</sub>';
    last = re.lastIndex;
  }
  if (last < text.length) out += _rejEsc(text.slice(last));
  return out;
}

function rejLoadParams() {
  fetch('/api/parametry/list').then(function(r) { return r.json(); }).then(function(data) {
    _rejParams = Array.isArray(data) ? data : [];
    rejRenderPills();
    rejRenderList();
  });
}

function rejRenderPills() {
  var el = document.getElementById('pe-rej-pills');
  if (!el) return;
  var html = '<span class="pe-pill reset' + (_rejTypFilter.size === 0 ? ' active' : '') + '" onclick="rejTogglePill(\'_all\')">Wszystkie</span>';
  _REJ_TYPS.forEach(function(t) {
    var active = _rejTypFilter.has(t) ? ' active' : '';
    html += '<span class="pe-pill' + active + '" onclick="rejTogglePill(\'' + t + '\')">' + _REJ_TYP_LABELS[t] + '</span>';
  });
  el.innerHTML = html;
}

function rejTogglePill(t) {
  if (t === '_all') { _rejTypFilter.clear(); }
  else if (_rejTypFilter.has(t)) { _rejTypFilter.delete(t); }
  else { _rejTypFilter.add(t); }
  rejRenderPills();
  rejRenderList();
}

function rejFilter(value) {
  _rejFilter = (value || '').toLowerCase();
  rejRenderList();
}

function rejRenderList() {
  var body = document.getElementById('pe-rej-list-body');
  if (!body) return;
  var filter = _rejFilter;
  var typFilter = _rejTypFilter;
  var html = '';
  // Active selected param always rendered (even if filtered out — w/ opacity .7)
  _rejParams.forEach(function(p) {
    if (!_isAdmin && !p.aktywny) return;  // non-admin sees only active
    var matchesFilter = !filter || (p.kod + ' ' + (p.label || '')).toLowerCase().indexOf(filter) !== -1;
    var matchesTyp = typFilter.size === 0 || typFilter.has(p.typ);
    var isSelected = (p.id === _rejSelectedId);
    if (!isSelected && (!matchesFilter || !matchesTyp)) return;

    var dimmed = (isSelected && (!matchesFilter || !matchesTyp)) ? ' style="opacity:.7;"' : '';
    var activeCls = isSelected ? ' active' : '';
    var inactiveDim = !p.aktywny ? ' style="opacity:.5;"' : '';
    var style = dimmed || inactiveDim;

    var typTag = '<span class="wc-md-item-tag-base" style="margin-left:4px;">' + _rejEsc(p.typ.slice(0, 4)) + '</span>';
    var grupaTag = p.grupa === 'zewn'
      ? '<span class="wc-md-item-tag-base" style="background:#fef3c7;color:#92400e;border-color:#fde68a;">zewn</span>'
      : '';
    var nameRendered = _rejRtHtml(p.label || p.kod);

    html += '<div class="wc-md-item' + activeCls + '"' + style + ' data-id="' + p.id + '" onclick="rejSelect(' + p.id + ')">' +
      '<span class="wc-md-item-name">' + nameRendered + '</span>' +
      typTag + grupaTag +
      '<span class="wc-md-item-bind">' + _rejEsc(p.kod) + '</span>' +
    '</div>';
  });
  if (!html) {
    html = '<div style="padding:14px;color:var(--text-dim);font-size:11px;text-align:center;">' +
      (filter || typFilter.size ? 'Brak wyników filtra.' : 'Brak parametrów.') + '</div>';
  }
  body.innerHTML = html;
}

function rejSelect(id) {
  // Persist current edits if dirty (B5 will implement saveCurrentRejToState)
  if (typeof rejSaveCurrentToState === 'function' && _rejSelectedId !== null) {
    rejSaveCurrentToState();
  }
  _rejSelectedId = id;
  rejRenderList();
  rejRenderDetail();
}

// Stub — real implementation in B3
function rejRenderDetail() {
  var detail = document.getElementById('pe-rej-detail');
  if (!detail) return;
  if (_rejSelectedId == null) {
    detail.innerHTML = '<div class="wc-md-detail-empty">Wybierz parametr z listy po lewej</div>';
    return;
  }
  var p = _rejParams.find(function(x) { return x.id === _rejSelectedId; });
  if (!p) {
    detail.innerHTML = '<div class="wc-md-detail-empty">Brak parametru.</div>';
    return;
  }
  detail.innerHTML = '<div class="wc-md-detail-empty">Wybrany: <strong>' + _rejEsc(p.kod) + '</strong> — szczegóły w Task B3</div>';
}

// Stub — Task B9 will implement
function rejOpenAddModal() { alert('B9 — Add Parameter modal'); }
```

- [ ] **Step 2: Wire `rejLoadParams` into tab switch**

Find existing `switchTab` function. The tab `def` should call `rejLoadParams()` on first activation. Find:

```javascript
function switchTab(name) { ... }
```

Look for the part that handles `def` tab. Add at end of `switchTab` (or wherever def panel becomes visible):

```javascript
  if (name === 'def' && _rejParams.length === 0) {
    rejLoadParams();
  }
```

If `switchTab` doesn't exist, find the inline onclick on the `<button class="pe-tab" id="tab-def" onclick="switchTab('def')">` and trace what it calls. Wire `rejLoadParams()` into that handler.

- [ ] **Step 3: Verify in browser**

Hard reload. Switch to Rejestr tab. Expected:
- Pills row shows `[Wszystkie] [Bezpośredni] [Titracja] [Obliczeniowy] [Jakościowy] [Średnia]`. „Wszystkie" is active by default.
- List shows all parameters, each with rendered name (sub/sup), typ tag (4 chars), grupa tag (`zewn` highlighted yellow), kod tag.
- Filter input narrows by kod/label substring.
- Click pill toggles it (multi-select). When ≥1 typ pill active, only those types show.
- Click „Wszystkie" clears all type pills.
- Click param → highlights in left list (active class), right panel shows „Wybrany: <kod>" placeholder.

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/parametry_editor.html
git commit -m "feat(parametry-rejestr): renderList + filter input + typ pills (B2)"
```

---

### Task B3: renderRejDetail with sections (Tożsamość, Klasyfikacja, Pomiar)

**Files:**
- Modify: `mbr/templates/parametry_editor.html` (JS — replace `rejRenderDetail` stub)

- [ ] **Step 1: Replace stub `rejRenderDetail` with full implementation**

Replace existing `rejRenderDetail` stub:

```javascript
function rejRenderDetail() {
  var detail = document.getElementById('pe-rej-detail');
  if (!detail) return;
  if (_rejSelectedId == null) {
    detail.innerHTML = '<div class="wc-md-detail-empty">Wybierz parametr z listy po lewej</div>';
    return;
  }
  var p = _rejParams.find(function(x) { return x.id === _rejSelectedId; });
  if (!p) {
    detail.innerHTML = '<div class="wc-md-detail-empty">Brak parametru.</div>';
    return;
  }

  var nameEff = p.label || p.kod;
  var inactiveBadge = !p.aktywny ? '<span class="wc-md-item-tag-base" style="background:#fef3c7;color:#92400e;border-color:#fde68a;">deakt.</span>' : '';

  detail.innerHTML =
    '<div class="wc-md-detail-head">' +
      '<div class="wc-md-detail-title">' + _rejRtHtml(nameEff) + '</div>' +
      '<span class="wc-md-detail-bind">' + _rejEsc(p.kod) + '</span>' +
      inactiveBadge +
      (p.aktywny
        ? '<button class="wc-md-detail-del" onclick="rejDeactivate()">Deaktywuj</button>'
        : '<button class="wc-md-detail-del" style="border-color:var(--teal);color:var(--teal);" onclick="rejReactivate()">Reaktywuj</button>'
      ) +
    '</div>' +

    '<div class="wc-md-banner hidden" id="pe-rej-banner"></div>' +

    '<div class="wc-md-toolbar" id="pe-rej-toolbar">' +
      '<span class="wc-md-toolbar-label">Wstaw do focused pola:</span>' +
      '<button class="wc-md-tbtn" data-tb="sup" onclick="rejTbInsert(\'sup\')" title="^{}">X<sup>²</sup></button>' +
      '<button class="wc-md-tbtn" data-tb="sub" onclick="rejTbInsert(\'sub\')" title="_{}">X<sub>₂</sub></button>' +
      '<button class="wc-md-tbtn" data-tb="br" onclick="rejTbInsert(\'br\')" title="|">↲</button>' +
      '<span class="wc-md-toolbar-sep"></span>' +
      '<button class="wc-md-tbtn" data-tb="leq" onclick="rejTbInsert(\'leq\')" title="≤">≤</button>' +
      '<button class="wc-md-tbtn" data-tb="geq" onclick="rejTbInsert(\'geq\')" title="≥">≥</button>' +
      '<button class="wc-md-tbtn" data-tb="div" onclick="rejTbInsert(\'div\')" title="÷">÷</button>' +
      '<button class="wc-md-tbtn" data-tb="deg" onclick="rejTbInsert(\'deg\')" title="°">°</button>' +
    '</div>' +

    '<div class="wc-md-single-section" style="margin-top:0;padding-top:0;border-top:none;">' +
      '<div style="font-size:9px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;">Tożsamość</div>' +
      '<div class="wc-md-single-row"><label>Kod</label><div><input data-rej="kod" value="' + _rejEsc(p.kod) + '" disabled style="font-family:var(--mono);max-width:200px;"><span style="font-size:10px;color:var(--text-dim);margin-left:8px;">read-only po utworzeniu</span></div></div>' +
      '<div class="wc-md-single-row"><label>Label PL</label><div style="flex:1;flex-direction:column;align-items:stretch;display:flex;gap:3px;">' +
        '<input data-rej="label" value="' + _rejEsc(p.label || '') + '" oninput="rejOnFieldInput(this)" style="font-family:\'Times New Roman\',serif;">' +
        '<div class="wc-md-rt-prev" data-rej-prev="label">' + _rejRtHtml(p.label || '') + '</div>' +
      '</div></div>' +
      '<div class="wc-md-single-row"><label>Label EN</label><div style="flex:1;flex-direction:column;align-items:stretch;display:flex;gap:3px;">' +
        '<input data-rej="name_en" value="' + _rejEsc(p.name_en || '') + '" oninput="rejOnFieldInput(this)" style="font-family:\'Times New Roman\',serif;">' +
        '<div class="wc-md-rt-prev" data-rej-prev="name_en">' + _rejRtHtml(p.name_en || '') + '</div>' +
      '</div></div>' +
      '<div class="wc-md-single-row"><label>Skrót</label><div><input data-rej="skrot" value="' + _rejEsc(p.skrot || '') + '" oninput="rejOnFieldInput(this)" style="max-width:160px;"></div></div>' +
    '</div>' +

    '<div class="wc-md-single-section">' +
      '<div style="font-size:9px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;">Klasyfikacja</div>' +
      '<div class="wc-md-single-row"><label>Typ</label><div><select data-rej="typ" onchange="rejOnTypChange(this)">' + _rejTypOptions(p.typ) + '</select></div></div>' +
      '<div class="wc-md-single-row"><label>Grupa</label><div><select data-rej="grupa" onchange="rejOnFieldInput(this)"><option value="lab"' + (p.grupa==='lab'?' selected':'') + '>lab (wewn.)</option><option value="zewn"' + (p.grupa==='zewn'?' selected':'') + '>zewn (lab. zewn.)</option></select></div></div>' +
    '</div>' +

    '<div class="wc-md-single-section">' +
      '<div style="font-size:9px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;">Pomiar</div>' +
      '<div class="wc-md-single-row"><label>Jednostka</label><div><input data-rej="jednostka" value="' + _rejEsc(p.jednostka || '') + '" oninput="rejOnFieldInput(this)" style="max-width:200px;font-family:\'Times New Roman\',serif;"></div></div>' +
      '<div class="wc-md-single-row"><label>Precyzja</label><div><select data-rej="precision" onchange="rejOnFieldInput(this)">' + _rejPrecisionOptions(p.precision) + '</select></div></div>' +
      '<div class="wc-md-single-row"><label>Metoda (kod)</label><div><input data-rej="method_code" value="' + _rejEsc(p.method_code || '') + '" oninput="rejOnFieldInput(this)" style="flex:1;"></div></div>' +
    '</div>' +

    // Konfiguracja typu — Task B4 will fill in dynamically
    '<div class="wc-md-single-section" id="pe-rej-typ-config">' +
      '<div style="font-size:9px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;">Konfiguracja typu</div>' +
      '<div style="font-size:11px;color:var(--text-dim);">[B4 — dynamic by typ]</div>' +
    '</div>' +

    // Powiązania — Task B7 will fill in
    '<div class="wc-md-single-section" id="pe-rej-powiazania">' +
      '<div style="font-size:9px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;">Powiązania</div>' +
      '<div style="font-size:11px;color:var(--text-dim);">[B7 — accordion z listami]</div>' +
    '</div>' +

    // Save button
    '<div style="display:flex;gap:12px;align-items:center;margin-top:18px;padding-top:14px;border-top:1.5px solid var(--border);">' +
      '<button class="wc-btn wc-btn-p" onclick="rejSaveAll()" style="background:var(--teal);color:#fff;border:none;padding:8px 18px;border-radius:6px;font-weight:700;cursor:pointer;">Zapisz wszystko</button>' +
      '<span id="pe-rej-status" style="font-size:11px;color:var(--text-dim);"></span>' +
    '</div>';

  // Wire focus tracking on text inputs (toolbar target — B5)
  detail.querySelectorAll('input[data-rej]').forEach(function(inp) {
    inp.addEventListener('focus', function() { _rejFocusedInput = inp; rejUpdateToolbarState(); });
  });
  detail.querySelectorAll('.wc-md-tbtn').forEach(function(btn) {
    btn.addEventListener('mousedown', function(e) { e.preventDefault(); });
  });
  rejUpdateToolbarState();
}

function _rejTypOptions(current) {
  return _REJ_TYPS.map(function(t) {
    return '<option value="' + t + '"' + (t === current ? ' selected' : '') + '>' + _REJ_TYP_LABELS[t] + '</option>';
  }).join('');
}

function _rejPrecisionOptions(current) {
  var opts = [
    {v: '0', l: '0 (123)'},
    {v: '1', l: '1 (123,4)'},
    {v: '2', l: '2 (123,45)'},
    {v: '3', l: '3 (123,456)'},
    {v: '4', l: '4 (123,4567)'},
    {v: '5', l: '5 (123,45678)'},
    {v: '6', l: '6 (123,456789)'},
  ];
  var cur = String(current == null ? '' : current);
  return opts.map(function(o) {
    return '<option value="' + o.v + '"' + (cur === o.v ? ' selected' : '') + '>' + o.l + '</option>';
  }).join('');
}

// Stubs — implemented in subsequent tasks
var _rejFocusedInput = null;
function rejUpdateToolbarState() { /* B5 */ }
function rejTbInsert(kind) { /* B5 */ }
function rejOnFieldInput(input) { /* B5 dirty tracking + banner */ }
function rejOnTypChange(select) { rejOnFieldInput(select); /* B4 also re-renders typ-config */ }
function rejSaveAll() { alert('B8 — Save Wszystko'); }
function rejDeactivate() { alert('B10 — Deactivate'); }
function rejReactivate() { alert('B10 — Reactivate'); }
```

- [ ] **Step 2: Verify in browser**

Hard reload. Click param in left list. Expected: detail panel shows:
- Header: rendered name + kod tag + Deaktywuj button
- Banner placeholder (hidden)
- Toolbar (buttons render but click does nothing)
- Sections: Tożsamość (kod read-only, label, name_en with live preview, skrot), Klasyfikacja (typ, grupa), Pomiar (jednostka, precyzja with dropdown showing examples, method_code)
- Placeholder sections for Konfiguracja typu (B4) and Powiązania (B7)
- Save button at bottom

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/parametry_editor.html
git commit -m "feat(parametry-rejestr): detail panel sections — Tożsamość/Klasyfikacja/Pomiar (B3)"
```

---

### Task B4: Konfiguracja typu — dynamic fields per typ

**Files:**
- Modify: `mbr/templates/parametry_editor.html` (JS — implement typ-config dynamic rendering)

- [ ] **Step 1: Add typ-specific renderer functions**

Append after `_rejPrecisionOptions`:

```javascript
function _rejRenderTypConfig(p) {
  var typ = p.typ;
  var html = '<div style="font-size:9px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;">Konfiguracja typu (' + _REJ_TYP_LABELS[typ] + ')</div>';

  if (typ === 'bezposredni') {
    html += '<div style="font-size:11px;color:var(--text-dim);font-style:italic;">Brak dodatkowej konfiguracji — wynik wpisywany ręcznie przez laboranta.</div>';
  }
  else if (typ === 'srednia') {
    html += '<div style="font-size:11px;color:var(--text-dim);font-style:italic;">Brak dodatkowej konfiguracji — UI laboranta liczy średnią z 2 pomiarów. Różnica od „bezpośredni" tylko w widgecie wprowadzania.</div>';
  }
  else if (typ === 'titracja') {
    html += '<div class="wc-md-single-row"><label>Metoda — nazwa</label><div><input data-rej="metoda_nazwa" value="' + _rejEsc(p.metoda_nazwa || '') + '" oninput="rejOnFieldInput(this)" placeholder="np. PN-EN ISO 660" style="flex:1;"></div></div>';
    html += '<div class="wc-md-single-row"><label>Metoda — formuła</label><div><input data-rej="metoda_formula" value="' + _rejEsc(p.metoda_formula || '') + '" oninput="rejOnFieldInput(this)" placeholder="np. (V * C * 56.1) / m" style="flex:1;"></div></div>';
    html += '<div class="wc-md-single-row"><label>Metoda — factor</label><div><input data-rej="metoda_factor" type="number" step="0.0001" value="' + _rejEsc(p.metoda_factor != null ? String(p.metoda_factor) : '') + '" oninput="rejOnFieldInput(this)" style="max-width:120px;"></div></div>';
  }
  else if (typ === 'obliczeniowy') {
    html += '<div class="wc-md-single-row"><label>Formuła</label><div><textarea data-rej="formula" oninput="rejOnFieldInput(this)" rows="3" placeholder="np. 100 * a / b - sa_bias" style="flex:1;font-family:var(--mono);font-size:11px;padding:6px 9px;border:1.5px solid var(--border);border-radius:5px;">' + _rejEsc(p.formula || '') + '</textarea></div></div>';
    html += '<div style="font-size:10px;color:var(--text-dim);margin-top:4px;padding-left:152px;">Tokens: kod parametru w nawiasach klamrowych, np. {sa}, {nacl}. Lub bezpośrednio formuła SQL-style.</div>';
  }
  else if (typ === 'jakosciowy') {
    var values = [];
    try { values = JSON.parse(p.opisowe_wartosci || '[]'); } catch (e) { values = []; }
    html += '<div style="font-size:11px;color:var(--text-dim);margin-bottom:8px;">Lista dozwolonych wartości opisowych. Pojawia się jako dropdown na cert i w UI laboranta.</div>';
    html += '<div id="pe-rej-opisowe-list" style="display:flex;flex-direction:column;gap:6px;">';
    values.forEach(function(v, i) {
      html += '<div class="pe-rej-opisowe-chip" data-idx="' + i + '" draggable="true" style="display:flex;align-items:center;gap:8px;padding:6px 10px;background:var(--surface-alt);border:1px solid var(--border);border-radius:5px;font-size:11.5px;cursor:grab;">' +
        '<span class="wc-md-drag" onmousedown="event.stopPropagation()" style="width:10px;height:14px;"></span>' +
        '<span class="pe-rej-opisowe-text" style="flex:1;font-family:\'Times New Roman\',serif;" ondblclick="rejOpisoweEditChip(this, ' + i + ')">' + _rejEsc(v) + '</span>' +
        '<button onclick="rejOpisoweRemove(' + i + ')" style="background:none;border:none;color:var(--text-dim);cursor:pointer;padding:2px 6px;" title="Usuń">×</button>' +
      '</div>';
    });
    html += '</div>';
    html += '<div style="display:flex;gap:6px;margin-top:10px;align-items:center;">' +
      '<input id="pe-rej-opisowe-new" placeholder="Dodaj wartość..." style="flex:1;padding:6px 9px;border:1.5px solid var(--border);border-radius:5px;font-size:11.5px;font-family:\'Times New Roman\',serif;" onkeydown="if(event.key===\'Enter\'){event.preventDefault();rejOpisoweAdd();}">' +
      '<button onclick="rejOpisoweAdd()" style="background:var(--teal);color:#fff;border:none;padding:6px 14px;border-radius:5px;font-size:11px;font-weight:600;cursor:pointer;">+ Dodaj</button>' +
    '</div>';
  }
  return html;
}
```

- [ ] **Step 2: Replace placeholder in `rejRenderDetail`**

Find in `rejRenderDetail`:

```javascript
    '<div class="wc-md-single-section" id="pe-rej-typ-config">' +
      '<div style="font-size:9px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;">Konfiguracja typu</div>' +
      '<div style="font-size:11px;color:var(--text-dim);">[B4 — dynamic by typ]</div>' +
    '</div>' +
```

Replace with:

```javascript
    '<div class="wc-md-single-section" id="pe-rej-typ-config">' +
      _rejRenderTypConfig(p) +
    '</div>' +
```

- [ ] **Step 3: Wire `rejOnTypChange` to re-render typ-config**

Replace existing `rejOnTypChange` stub:

```javascript
function rejOnTypChange(select) {
  rejOnFieldInput(select);
  // Re-render typ-config section using current in-memory state
  var p = _rejParams.find(function(x) { return x.id === _rejSelectedId; });
  if (!p) return;
  // Read all current detail-panel inputs into in-memory p (so we don't lose pending edits)
  rejSaveCurrentToState();
  // typ in-memory now reflects the dropdown change
  var section = document.getElementById('pe-rej-typ-config');
  if (section) section.innerHTML = _rejRenderTypConfig(p);
}
```

(`rejSaveCurrentToState` is implemented in B5 — for now stub it: add `function rejSaveCurrentToState() { /* B5 */ }` near other stubs.)

- [ ] **Step 4: Add opisowe_wartosci helpers**

Append:

```javascript
function rejOpisoweRemove(idx) {
  var p = _rejParams.find(function(x) { return x.id === _rejSelectedId; });
  if (!p) return;
  var values = [];
  try { values = JSON.parse(p.opisowe_wartosci || '[]'); } catch (e) { values = []; }
  if (values.length <= 1) { alert('Minimum 1 wartość — nie można usunąć ostatniej.'); return; }
  values.splice(idx, 1);
  p.opisowe_wartosci = JSON.stringify(values);
  rejMarkDirty();
  document.getElementById('pe-rej-typ-config').innerHTML = _rejRenderTypConfig(p);
}

function rejOpisoweAdd() {
  var inp = document.getElementById('pe-rej-opisowe-new');
  var v = (inp.value || '').trim();
  if (!v) return;
  var p = _rejParams.find(function(x) { return x.id === _rejSelectedId; });
  if (!p) return;
  var values = [];
  try { values = JSON.parse(p.opisowe_wartosci || '[]'); } catch (e) { values = []; }
  if (values.indexOf(v) !== -1) { alert('Wartość już istnieje na liście.'); return; }
  values.push(v);
  p.opisowe_wartosci = JSON.stringify(values);
  rejMarkDirty();
  inp.value = '';
  document.getElementById('pe-rej-typ-config').innerHTML = _rejRenderTypConfig(p);
  document.getElementById('pe-rej-opisowe-new').focus();
}

function rejOpisoweEditChip(span, idx) {
  var current = span.textContent;
  var inp = document.createElement('input');
  inp.value = current;
  inp.style.cssText = "flex:1;padding:2px 4px;border:1px solid var(--teal);border-radius:3px;font-family:'Times New Roman',serif;";
  span.replaceWith(inp);
  inp.focus();
  inp.select();

  function commit() {
    var v = (inp.value || '').trim();
    if (!v) { v = current; }
    var p = _rejParams.find(function(x) { return x.id === _rejSelectedId; });
    if (!p) return;
    var values = [];
    try { values = JSON.parse(p.opisowe_wartosci || '[]'); } catch (e) { values = []; }
    if (values.indexOf(v) !== -1 && v !== current) { alert('Duplikat — wartość już jest na liście.'); document.getElementById('pe-rej-typ-config').innerHTML = _rejRenderTypConfig(p); return; }
    values[idx] = v;
    p.opisowe_wartosci = JSON.stringify(values);
    rejMarkDirty();
    document.getElementById('pe-rej-typ-config').innerHTML = _rejRenderTypConfig(p);
  }

  inp.addEventListener('blur', commit);
  inp.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') { e.preventDefault(); commit(); }
    else if (e.key === 'Escape') { document.getElementById('pe-rej-typ-config').innerHTML = _rejRenderTypConfig({...{opisowe_wartosci: JSON.stringify([])}}); rejRenderDetail(); }
  });
}

// Drag-and-drop reorder for opisowe chips
var _rejOpisoweDrag = null;
function _rejInitOpisoweDrag() {
  document.querySelectorAll('#pe-rej-opisowe-list .pe-rej-opisowe-chip').forEach(function(chip) {
    chip.addEventListener('dragstart', function(e) {
      _rejOpisoweDrag = this; this.style.opacity = '0.4';
      e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', '');
    });
    chip.addEventListener('dragover', function(e) { e.preventDefault(); });
    chip.addEventListener('drop', function(e) {
      e.preventDefault();
      if (!_rejOpisoweDrag || _rejOpisoweDrag === this) return;
      var fromIdx = parseInt(_rejOpisoweDrag.getAttribute('data-idx'));
      var toIdx = parseInt(this.getAttribute('data-idx'));
      var p = _rejParams.find(function(x) { return x.id === _rejSelectedId; });
      if (!p) return;
      var values = [];
      try { values = JSON.parse(p.opisowe_wartosci || '[]'); } catch (e) { values = []; }
      var moved = values.splice(fromIdx, 1)[0];
      values.splice(toIdx, 0, moved);
      p.opisowe_wartosci = JSON.stringify(values);
      rejMarkDirty();
      document.getElementById('pe-rej-typ-config').innerHTML = _rejRenderTypConfig(p);
    });
    chip.addEventListener('dragend', function() { this.style.opacity = ''; _rejOpisoweDrag = null; });
  });
}

// Stub for B5 — markDirty
function rejMarkDirty() { /* B5 */ }
```

After replacing typ-config innerHTML in any of the above, also call `_rejInitOpisoweDrag()` to wire drag handlers. Update each `document.getElementById('pe-rej-typ-config').innerHTML = ...; ` to be followed by `_rejInitOpisoweDrag();`. Easier — wrap re-render in helper:

Add helper:

```javascript
function _rejRerenderTypConfig() {
  var p = _rejParams.find(function(x) { return x.id === _rejSelectedId; });
  if (!p) return;
  var section = document.getElementById('pe-rej-typ-config');
  if (!section) return;
  section.innerHTML = _rejRenderTypConfig(p);
  if (p.typ === 'jakosciowy') _rejInitOpisoweDrag();
}
```

Replace all `document.getElementById('pe-rej-typ-config').innerHTML = _rejRenderTypConfig(p);` calls with `_rejRerenderTypConfig();`.

Also call `_rejInitOpisoweDrag()` at end of `rejRenderDetail` for initial render:

In `rejRenderDetail`, after the `detail.querySelectorAll('.wc-md-tbtn')` block, add:

```javascript
  if (p.typ === 'jakosciowy') _rejInitOpisoweDrag();
```

- [ ] **Step 5: Verify in browser**

Hard reload. Pick params of different types:
- `bezposredni` / `srednia` → only italic note
- `titracja` (e.g. `lk` if exists) → 3 fields (metoda_nazwa, metoda_formula, metoda_factor)
- `obliczeniowy` → textarea formula
- `jakosciowy` (e.g. `cert_qual_*`) → list of chips, drag to reorder, double-click to inline edit, × to delete, + Dodaj to add

Change typ in dropdown → typ-config section updates dynamically.

- [ ] **Step 6: Commit**

```bash
git add mbr/templates/parametry_editor.html
git commit -m "feat(parametry-rejestr): typ-specific Konfiguracja typu section + opisowe chips drag/inline-edit (B4)"
```

---

### Task B5: Toolbar formatowania + dirty tracking + field input handler

**Files:**
- Modify: `mbr/templates/parametry_editor.html` (JS — implement stubs)

- [ ] **Step 1: Implement toolbar logic**

Replace stubs:

```javascript
var _rejFocusedInput = null;
var _REJ_SUB_SUP_FIELDS = ['label', 'name_en', 'jednostka'];  // these accept indices

function rejUpdateToolbarState() {
  var toolbar = document.getElementById('pe-rej-toolbar');
  if (!toolbar) return;
  var inp = _rejFocusedInput;
  var dataRej = (inp && inp.tagName === 'INPUT' && inp.getAttribute) ? inp.getAttribute('data-rej') : null;
  toolbar.querySelectorAll('.wc-md-tbtn').forEach(function(btn) {
    var kind = btn.getAttribute('data-tb');
    var allowed = false;
    if (!inp || !dataRej) { allowed = false; }
    else if (kind === 'sup' || kind === 'sub' || kind === 'br') {
      allowed = _REJ_SUB_SUP_FIELDS.indexOf(dataRej) !== -1;
    } else {
      allowed = true;
    }
    btn.disabled = !allowed;
  });
}

function rejTbInsert(kind) {
  var inp = _rejFocusedInput;
  if (!inp) return;
  var ins = ''; var caretInside = false;
  if (kind === 'sup') { ins = '^{}'; caretInside = true; }
  else if (kind === 'sub') { ins = '_{}'; caretInside = true; }
  else if (kind === 'br') { ins = '|'; }
  else if (kind === 'leq') { ins = '≤'; }
  else if (kind === 'geq') { ins = '≥'; }
  else if (kind === 'div') { ins = '÷'; }
  else if (kind === 'deg') { ins = '°'; }
  if (!ins) return;
  var start = inp.selectionStart || 0;
  var end = inp.selectionEnd || 0;
  inp.value = inp.value.slice(0, start) + ins + inp.value.slice(end);
  var newPos = caretInside ? start + 2 : start + ins.length;
  inp.setSelectionRange(newPos, newPos);
  inp.focus();
  inp.dispatchEvent(new Event('input', { bubbles: true }));
}
```

- [ ] **Step 2: Implement dirty tracking + live preview**

Replace stubs:

```javascript
var _rejDirty = false;
var _rejOriginalParam = null;  // snapshot for banner detection

function rejMarkDirty() {
  _rejDirty = true;
  var status = document.getElementById('pe-rej-status');
  if (status) { status.textContent = '● Niezapisane zmiany'; status.style.color = 'var(--orange, #d97706)'; }
}

function rejOnFieldInput(input) {
  var key = input.getAttribute('data-rej');
  // Live preview for label/name_en/jednostka
  if (['label', 'name_en'].indexOf(key) !== -1) {
    var prev = document.querySelector('[data-rej-prev="' + key + '"]');
    if (prev) prev.innerHTML = _rejRtHtml(input.value || '');
  }
  rejMarkDirty();
  rejRefreshBanner();
}

function rejSaveCurrentToState() {
  if (_rejSelectedId == null) return;
  var p = _rejParams.find(function(x) { return x.id === _rejSelectedId; });
  if (!p) return;
  var detail = document.getElementById('pe-rej-detail');
  if (!detail) return;
  detail.querySelectorAll('[data-rej]').forEach(function(el) {
    var key = el.getAttribute('data-rej');
    if (key === 'kod') return;  // read-only
    var val = el.value;
    if (key === 'precision' || key === 'metoda_factor') {
      val = val === '' ? null : parseFloat(val);
    }
    if (key === 'aktywny') {
      val = el.checked ? 1 : 0;
    }
    p[key] = val;
  });
}

// Override rejSelect to snapshot original on first selection
var _rejSelectOrig = rejSelect;
function rejSelect(id) {
  if (typeof rejSaveCurrentToState === 'function' && _rejSelectedId !== null && _rejDirty) {
    if (!confirm('Masz niezapisane zmiany. Porzucić?')) return;
  }
  _rejSelectedId = id;
  _rejDirty = false;
  var p = _rejParams.find(function(x) { return x.id === id; });
  _rejOriginalParam = p ? JSON.parse(JSON.stringify(p)) : null;
  rejRenderList();
  rejRenderDetail();
}
```

- [ ] **Step 3: Verify in browser**

Hard reload. Pick param. Click in „Label PL" input → toolbar buttons activate (X² X₂ ↲ ≤ ≥ ÷ °). Click X² → `^{}` inserts at cursor. Live preview updates.

Click in „Skrót" or „Method (kod)" → only special chars (≤ ≥ ÷ °) enabled, X² greyed.

Edit any field → dirty marker appears on Save row. Switch to another param while dirty → confirm dialog.

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/parametry_editor.html
git commit -m "feat(parametry-rejestr): toolbar formatowania + dirty tracking + live preview (B5)"
```

---

### Task B6: Banner usage-impact (4 cross-editor fields)

**Files:**
- Modify: `mbr/templates/parametry_editor.html` (JS — implement `rejRefreshBanner`)

- [ ] **Step 1: Implement banner logic**

Add:

```javascript
var _rejUsageCache = {};  // param_id → {cert_products_count, mbr_products_count, ...}

function _rejFetchUsage(paramId) {
  if (_rejUsageCache[paramId]) return Promise.resolve(_rejUsageCache[paramId]);
  return fetch('/api/parametry/' + paramId + '/usage-impact')
    .then(function(r) { return r.json(); })
    .then(function(j) {
      if (j && typeof j.cert_products_count === 'number') _rejUsageCache[paramId] = j;
      return j;
    });
}

function rejRefreshBanner() {
  if (_rejSelectedId == null) return;
  var p = _rejParams.find(function(x) { return x.id === _rejSelectedId; });
  if (!p || !_rejOriginalParam) {
    _rejHideBanner();
    return;
  }

  var detail = document.getElementById('pe-rej-detail');
  if (!detail) return;

  // Read current input values; compare to snapshot
  function _val(key) {
    var el = detail.querySelector('[data-rej="' + key + '"]');
    return el ? el.value : '';
  }
  var labelChanged = _val('label') !== (_rejOriginalParam.label || '');
  var enChanged = _val('name_en') !== (_rejOriginalParam.name_en || '');
  var methodChanged = _val('method_code') !== (_rejOriginalParam.method_code || '');
  var precChanged = _val('precision') !== String(_rejOriginalParam.precision != null ? _rejOriginalParam.precision : '');

  if (!labelChanged && !enChanged && !methodChanged && !precChanged) {
    _rejHideBanner();
    return;
  }

  _rejFetchUsage(p.id).then(function(impact) {
    var banner = document.getElementById('pe-rej-banner');
    if (!banner) return;
    var certN = (impact && impact.cert_products_count) || 0;
    var mbrN = (impact && impact.mbr_products_count) || 0;
    var lines = ['⚠ Edytujesz <strong>rejestr globalny</strong> (zmiana wpłynie na inne produkty).'];
    lines.push('Świadectwa: <strong>' + certN + ' produkt(ów)</strong>.');
    if (labelChanged) {
      lines.push('Również widoczne w: laboratorium, MBR, kalkulator (' + mbrN + ' produkt(ów) z parametrem w MBR).');
    }
    if (precChanged) {
      lines.push('MBR: <strong>' + mbrN + ' produkt(ów)</strong> (precyzja propaguje się przez COALESCE w parametry_etapy).');
    }
    banner.innerHTML = lines.join(' ');
    banner.classList.remove('hidden');
  });
}

function _rejHideBanner() {
  var banner = document.getElementById('pe-rej-banner');
  if (banner) banner.classList.add('hidden');
}
```

- [ ] **Step 2: Verify in browser**

Hard reload. Pick param. Edit:
- `Label PL` → banner appears with extended message (laborant + MBR scope)
- `Label EN` → banner appears with cert-only message
- `Skrót` → banner does NOT appear
- `Precision` (dropdown) → banner shows MBR scope addition

Cancel changes (revert input) → banner disappears.

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/parametry_editor.html
git commit -m "feat(parametry-rejestr): field-specific usage-impact banner (B6)"
```

---

### Task B7: Powiązania accordion read-only

**Files:**
- Modify: `mbr/templates/parametry_editor.html` (JS — implement `rejRenderPowiazania`)

- [ ] **Step 1: Add Powiązania renderer**

Append:

```javascript
function _rejRenderPowiazania(p) {
  var html = '<div style="font-size:9px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;">Powiązania</div>';
  html += '<div id="pe-rej-pow-loading" style="font-size:11px;color:var(--text-dim);">Ładowanie…</div>';

  // Async fetch
  setTimeout(function() {
    _rejFetchUsage(p.id).then(function(impact) {
      if (_rejSelectedId !== p.id) return;  // user switched away
      var section = document.getElementById('pe-rej-powiazania');
      if (!section) return;
      var inner = '<div style="font-size:9px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;">Powiązania</div>';

      var certCount = impact.cert_products_count || 0;
      var mbrCount = impact.mbr_products_count || 0;
      var mbrBindCount = impact.mbr_bindings_count || 0;
      var certProds = impact.cert_products || [];
      var mbrProds = impact.mbr_products || [];

      // Cert accordion
      inner += '<details ' + (certCount > 0 ? '' : 'open') + ' style="margin-bottom:6px;">' +
        '<summary style="cursor:pointer;font-size:11.5px;font-weight:600;color:var(--text);padding:6px 8px;background:var(--surface-alt);border-radius:4px;">Świadectwa: ' + certCount + ' produktów</summary>' +
        '<div style="padding:8px 4px 4px;display:flex;flex-wrap:wrap;gap:4px;">';
      if (certCount === 0) inner += '<span style="font-size:11px;color:var(--text-dim);font-style:italic;padding:4px 0;">Parametr nie jest jeszcze na żadnym świadectwie.</span>';
      else certProds.forEach(function(cp) {
        inner += '<span class="wc-md-item-bind" style="font-size:10px;">' + _rejEsc(cp.display_name || cp.key) + '</span>';
      });
      inner += '</div></details>';

      // MBR accordion
      inner += '<details>' +
        '<summary style="cursor:pointer;font-size:11.5px;font-weight:600;color:var(--text);padding:6px 8px;background:var(--surface-alt);border-radius:4px;">Etapy MBR: ' + mbrCount + ' produktów × ' + mbrBindCount + ' bindings</summary>' +
        '<div style="padding:8px 4px 4px;display:flex;flex-direction:column;gap:6px;">';
      if (mbrCount === 0) inner += '<span style="font-size:11px;color:var(--text-dim);font-style:italic;">Parametr nie jest powiązany z żadnym etapem MBR.</span>';
      else mbrProds.forEach(function(mp) {
        inner += '<div style="font-size:11px;display:flex;gap:6px;align-items:center;flex-wrap:wrap;">' +
          '<span style="font-weight:600;font-size:11px;">' + _rejEsc(mp.key) + '</span>' +
          '<span style="font-size:10px;color:var(--text-dim);">→</span>';
        mp.stages.forEach(function(s) {
          inner += '<span class="wc-md-item-bind" style="font-size:9.5px;">' + _rejEsc(s) + '</span>';
        });
        inner += '</div>';
      });
      inner += '</div></details>';

      section.innerHTML = inner;
    }).catch(function() {
      var section = document.getElementById('pe-rej-powiazania');
      if (section) section.innerHTML = '<div style="font-size:11px;color:var(--red);">Błąd ładowania powiązań.</div>';
    });
  }, 0);

  return html;
}
```

- [ ] **Step 2: Replace placeholder in `rejRenderDetail`**

Find:

```javascript
    '<div class="wc-md-single-section" id="pe-rej-powiazania">' +
      '<div style="font-size:9px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;">Powiązania</div>' +
      '<div style="font-size:11px;color:var(--text-dim);">[B7 — accordion z listami]</div>' +
    '</div>' +
```

Replace with:

```javascript
    '<div class="wc-md-single-section" id="pe-rej-powiazania">' +
      _rejRenderPowiazania(p) +
    '</div>' +
```

- [ ] **Step 3: Verify in browser**

Hard reload. Pick param. Section „Powiązania" loads asynchronously, shows two accordion blocks:
- „Świadectwa: N produktów" → expand → chip-y produktów
- „Etapy MBR: M × K bindings" → expand → produkt → stages chips

For unused params (np. `orphan` test data) shows „Parametr nie jest jeszcze na żadnym świadectwie."

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/parametry_editor.html
git commit -m "feat(parametry-rejestr): Powiązania accordion read-only (B7)"
```

---

### Task B8: Save Wszystko flow

**Files:**
- Modify: `mbr/templates/parametry_editor.html` (JS — implement `rejSaveAll`)

- [ ] **Step 1: Replace stub `rejSaveAll`**

```javascript
function rejSaveAll() {
  if (_rejSelectedId == null) return;
  rejSaveCurrentToState();  // flush pending input edits

  var p = _rejParams.find(function(x) { return x.id === _rejSelectedId; });
  if (!p) return;

  var status = document.getElementById('pe-rej-status');
  if (status) { status.textContent = 'Zapisuję...'; status.style.color = 'var(--text-dim)'; }

  // Build PUT body — all fields from p (PUT /api/parametry/<id> accepts arbitrary subset)
  var body = {
    label: p.label || '',
    name_en: p.name_en || '',
    skrot: p.skrot || '',
    typ: p.typ,
    grupa: p.grupa || 'lab',
    aktywny: p.aktywny != null ? p.aktywny : 1,
    method_code: p.method_code || '',
    jednostka: p.jednostka || '',
    precision: p.precision != null ? parseInt(p.precision) : null,
    formula: p.formula || '',
    metoda_nazwa: p.metoda_nazwa || '',
    metoda_formula: p.metoda_formula || '',
    metoda_factor: p.metoda_factor != null ? parseFloat(p.metoda_factor) : null,
  };
  // jakosciowy: send opisowe_wartosci as parsed array (server expects list)
  if (p.typ === 'jakosciowy') {
    var values = [];
    try { values = JSON.parse(p.opisowe_wartosci || '[]'); } catch (e) { values = []; }
    body.opisowe_wartosci = values;
  }

  fetch('/api/parametry/' + _rejSelectedId, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  }).then(function(r) {
    return r.json().then(function(d) { return { status: r.status, data: d }; });
  }).then(function(res) {
    if (res.status === 200 && res.data.ok) {
      if (status) { status.textContent = 'Zapisano: ' + p.kod; status.style.color = 'var(--green)'; }
      _rejDirty = false;
      _rejUsageCache = {};
      // Reload list to reflect changes
      rejLoadParams();
    } else {
      var err = res.data.error || 'Błąd zapisu';
      if (status) { status.textContent = 'Błąd: ' + err; status.style.color = 'var(--red)'; }
      alert('Zapis nieudany: ' + err);
    }
  }).catch(function(e) {
    if (status) { status.textContent = 'Błąd: ' + e.message; status.style.color = 'var(--red)'; }
  });
}
```

- [ ] **Step 2: Verify end-to-end**

Hard reload. Pick param. Edit:
- Label PL → save → `Zapisano: <kod>`, lista się odświeża, banner znika.
- Audit log w `/admin/audit` pokazuje `parametr.updated` z diff dla `label`.
- Edit precision → save → propaguje do cert generator (sprawdzić następnym renderem cert PDF).

Edge cases:
- Edit jakosciowy opisowe_wartosci → save → bez błędu (server akceptuje listę).
- Edit typu z historycznym wynikiem (np. zmiana `bezposredni` → `titracja` na param mającym `ebr_wyniki`) → zwraca 409 → flash error.

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/parametry_editor.html
git commit -m "feat(parametry-rejestr): Save Wszystko flow with audit (B8)"
```

---

### Task B9: Add Parameter modal

**Files:**
- Modify: `mbr/templates/parametry_editor.html` (HTML modal + JS flow)

- [ ] **Step 1: Add modal HTML**

In `mbr/templates/parametry_editor.html`, after the existing `</div>` closing `panel-prod` (around line 273) but before `{% endblock %}`, insert:

```html
<!-- ═══ Add Parameter Modal (Rejestr) ═══ -->
<div class="wc-modal" id="pe-rej-add-modal" style="position:fixed;inset:0;z-index:600;background:rgba(15,12,8,0.45);backdrop-filter:blur(4px);display:none;align-items:center;justify-content:center;" onclick="if(event.target===this)rejCloseAddModal()">
  <div style="background:var(--surface);border-radius:8px;width:90vw;max-width:480px;box-shadow:0 8px 32px rgba(0,0,0,.2);">
    <div style="display:flex;align-items:center;justify-content:space-between;padding:14px 20px;border-bottom:1px solid var(--border);">
      <span style="font-weight:700;">Dodaj nowy parametr do rejestru</span>
      <button onclick="rejCloseAddModal()" style="background:none;border:none;font-size:20px;color:var(--text-dim);cursor:pointer;">×</button>
    </div>
    <div style="padding:18px 22px;">
      <div style="margin-bottom:14px;">
        <label style="font-size:11px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;display:block;margin-bottom:4px;">Kod *</label>
        <input id="pe-rej-add-kod" type="text" placeholder="np. nD20, gestosc, lk" style="width:100%;padding:7px 10px;border:1.5px solid var(--border);border-radius:5px;font-family:var(--mono);font-size:12px;box-sizing:border-box;">
        <div style="font-size:10px;color:var(--text-dim);margin-top:3px;">Litery a-z, A-Z, cyfry, podkreślnik. Read-only po utworzeniu.</div>
      </div>
      <div style="margin-bottom:14px;">
        <label style="font-size:11px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;display:block;margin-bottom:4px;">Label PL *</label>
        <input id="pe-rej-add-label" type="text" placeholder="np. Współczynnik załamania" style="width:100%;padding:7px 10px;border:1.5px solid var(--border);border-radius:5px;font-family:'Times New Roman',serif;font-size:12px;box-sizing:border-box;">
      </div>
      <div style="margin-bottom:14px;">
        <label style="font-size:11px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;display:block;margin-bottom:4px;">Typ *</label>
        <select id="pe-rej-add-typ" style="width:100%;padding:7px 10px;border:1.5px solid var(--border);border-radius:5px;font-size:12px;box-sizing:border-box;">
          <option value="bezposredni">bezpośredni</option>
          <option value="titracja">titracja</option>
          <option value="obliczeniowy">obliczeniowy</option>
          <option value="jakosciowy">jakościowy (opisowy)</option>
          <option value="srednia">średnia (z 2 pomiarów)</option>
        </select>
      </div>
      <div style="margin-bottom:14px;">
        <label style="font-size:11px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;display:block;margin-bottom:4px;">Grupa</label>
        <select id="pe-rej-add-grupa" style="width:100%;padding:7px 10px;border:1.5px solid var(--border);border-radius:5px;font-size:12px;box-sizing:border-box;">
          <option value="lab" selected>lab (wewnętrzny)</option>
          <option value="zewn">zewn (lab. zewn.)</option>
        </select>
      </div>
      <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:18px;">
        <button onclick="rejCloseAddModal()" style="background:transparent;border:1.5px solid var(--border);padding:7px 14px;border-radius:5px;cursor:pointer;font-size:12px;">Anuluj</button>
        <button onclick="rejConfirmAdd()" style="background:var(--teal);color:#fff;border:none;padding:7px 14px;border-radius:5px;cursor:pointer;font-size:12px;font-weight:600;">Utwórz</button>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Replace stub `rejOpenAddModal` + add helpers**

Replace the existing stub:

```javascript
function rejOpenAddModal() {
  document.getElementById('pe-rej-add-kod').value = '';
  document.getElementById('pe-rej-add-label').value = '';
  document.getElementById('pe-rej-add-typ').value = 'bezposredni';
  document.getElementById('pe-rej-add-grupa').value = 'lab';
  document.getElementById('pe-rej-add-modal').style.display = 'flex';
  setTimeout(function() { document.getElementById('pe-rej-add-kod').focus(); }, 60);
}

function rejCloseAddModal() {
  document.getElementById('pe-rej-add-modal').style.display = 'none';
}

function rejConfirmAdd() {
  var kod = (document.getElementById('pe-rej-add-kod').value || '').trim();
  var label = (document.getElementById('pe-rej-add-label').value || '').trim();
  var typ = document.getElementById('pe-rej-add-typ').value;
  var grupa = document.getElementById('pe-rej-add-grupa').value;

  if (!kod) { alert('Kod jest wymagany'); return; }
  if (!/^[a-zA-Z0-9_]+$/.test(kod)) { alert('Kod może zawierać tylko litery, cyfry i podkreślnik.'); return; }
  if (kod.length > 30) { alert('Kod max 30 znaków.'); return; }
  if (!label) { alert('Label PL jest wymagany'); return; }
  if (label.length > 200) { alert('Label max 200 znaków.'); return; }

  // jakosciowy needs at least one opisowe_wartosci — not collected here (admin uzupełni w detail po utworzeniu).
  // Server requires for jakosciowy: opisowe_wartosci non-empty list. Send a placeholder.
  var body = { kod: kod, label: label, typ: typ, grupa: grupa };
  if (typ === 'jakosciowy') body.opisowe_wartosci = ['(uzupełnij)'];

  fetch('/api/parametry', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  }).then(function(r) {
    return r.json().then(function(d) { return { status: r.status, data: d }; });
  }).then(function(res) {
    if (res.status === 200 && res.data.ok) {
      rejCloseAddModal();
      rejLoadParams();
      // After list reload, select the new param
      setTimeout(function() { rejSelect(res.data.id); }, 200);
    } else {
      alert('Błąd: ' + (res.data.error || 'nie udało się utworzyć'));
    }
  });
}
```

- [ ] **Step 3: Verify in browser**

Hard reload. Klik „+ Dodaj parametr" w lewym panelu → modal otwarty. Wpisz kod, label, wybierz typ. Klik Utwórz → modal zamyka, parametr w liście, zaznaczony, prawy panel pokazuje detail. Walidacje: pusty kod, niedozwolone znaki, długość — alerty.

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/parametry_editor.html
git commit -m "feat(parametry-rejestr): + Dodaj parametr modal (B9)"
```

---

### Task B10: Soft delete (Deaktywuj) + Reaktywuj

**Files:**
- Modify: `mbr/templates/parametry_editor.html` (JS — replace stubs `rejDeactivate`, `rejReactivate`; add „Pokaż nieaktywne" toggle)

- [ ] **Step 1: Add „Pokaż nieaktywne" toggle in Rejestr panel**

In `#panel-def`, find the line with `<div id="pe-rej-pills">`. Just before it (or after the search), add a toggle:

Find:

```html
      <div id="pe-rej-pills" style="display:flex;flex-wrap:wrap;gap:4px;padding:8px;border-bottom:1px solid var(--border);background:var(--surface);"></div>
```

Replace with:

```html
      <div style="padding:6px 8px 0;background:var(--surface);">
        <label style="font-size:10px;color:var(--text-dim);cursor:pointer;display:flex;align-items:center;gap:5px;">
          <input type="checkbox" id="pe-rej-show-inactive" onchange="rejToggleShowInactive(this.checked)">
          Pokaż nieaktywne
        </label>
      </div>
      <div id="pe-rej-pills" style="display:flex;flex-wrap:wrap;gap:4px;padding:8px;border-bottom:1px solid var(--border);background:var(--surface);"></div>
```

- [ ] **Step 2: Add JS for toggle + replace stub `rejDeactivate`/`rejReactivate`**

```javascript
var _rejShowInactive = false;
function rejToggleShowInactive(checked) {
  _rejShowInactive = checked;
  rejRenderList();
}

// Override list filter — also exclude inactive when not showing them
// Find rejRenderList — modify the filter line:
//   if (!_isAdmin && !p.aktywny) return;  // non-admin sees only active
// Change to:
//   if (!_isAdmin && !p.aktywny) return;
//   if (_isAdmin && !p.aktywny && !_rejShowInactive) return;
```

Apply that filter change to `rejRenderList`:

Find:

```javascript
    if (!_isAdmin && !p.aktywny) return;  // non-admin sees only active
```

Replace with:

```javascript
    if (!_isAdmin && !p.aktywny) return;
    if (_isAdmin && !p.aktywny && !_rejShowInactive) return;
```

Replace stubs:

```javascript
function rejDeactivate() {
  if (_rejSelectedId == null) return;
  var p = _rejParams.find(function(x) { return x.id === _rejSelectedId; });
  if (!p) return;
  if (!p.aktywny) return;  // already inactive

  _rejFetchUsage(_rejSelectedId).then(function(impact) {
    var certN = impact.cert_products_count || 0;
    var mbrN = impact.mbr_products_count || 0;
    var msg = 'Deaktywować parametr „' + p.kod + '"?\n\n' +
      'Parametr jest używany w ' + certN + ' świadectwach + ' + mbrN + ' produktach MBR.\n\n' +
      'Po deaktywacji:\n' +
      '✓ historyczne szarże nadal generują się poprawnie\n' +
      '✓ nowe konfiguracje nie będą widziały tego parametru\n' +
      '✓ deaktywacja jest odwracalna (Reaktywuj)';
    if (!confirm(msg)) return;

    fetch('/api/parametry/' + _rejSelectedId, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ aktywny: 0 }),
    }).then(function(r) {
      if (r.ok) { rejLoadParams(); }
      else { r.json().then(function(d) { alert('Błąd: ' + (d.error || r.status)); }); }
    });
  });
}

function rejReactivate() {
  if (_rejSelectedId == null) return;
  var p = _rejParams.find(function(x) { return x.id === _rejSelectedId; });
  if (!p) return;
  if (p.aktywny) return;

  if (!confirm('Reaktywować parametr „' + p.kod + '"? Wróci do listy aktywnych parametrów.')) return;

  fetch('/api/parametry/' + _rejSelectedId, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ aktywny: 1 }),
  }).then(function(r) {
    if (r.ok) { rejLoadParams(); }
    else { r.json().then(function(d) { alert('Błąd: ' + (d.error || r.status)); }); }
  });
}
```

- [ ] **Step 3: Verify in browser**

Hard reload. Pick aktywny parametr → klik „Deaktywuj" → confirm dialog z impact info. OK → znika z listy (lista filtruje aktywne). Klik „Pokaż nieaktywne" → wraca z dim opacity + tag `[deakt.]`. Klik nieaktywnego → detail pokazuje „Reaktywuj" zamiast „Deaktywuj". Klik Reaktywuj → wraca aktywnych.

Audit `/admin/audit`: dwa eventy `parametr.updated` z diff `{pole: 'aktywny', stara: 1, nowa: 0}` i odwrotnie.

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/parametry_editor.html
git commit -m "feat(parametry-rejestr): soft delete via aktywny=0 toggle + reactivation flow (B10)"
```

---

## Phase C — Cert editor format dual-field

### Task C1: Add format_global + format_override to cert editor `_dualRow`

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html`

- [ ] **Step 1: Update `_precisionOptionsWithExamples` helper**

In `mbr/templates/admin/wzory_cert.html`, find existing `_fmtOptions` (around line 600):

```javascript
function _fmtOptions(current) {
  var opts = [{v:'',l:'—'},{v:'0',l:'0'},{v:'1',l:'1'},{v:'2',l:'2'},{v:'3',l:'3'},{v:'4',l:'4'}];
  var html = '';
  opts.forEach(function(o) {
    html += '<option value="' + o.v + '"' + (String(current||'') === o.v ? ' selected' : '') + '>' + o.l + '</option>';
  });
  return html;
}
```

Replace with:

```javascript
function _fmtOptions(current) {
  var opts = [
    {v: '',  l: '—'},
    {v: '0', l: '0 (123)'},
    {v: '1', l: '1 (123,4)'},
    {v: '2', l: '2 (123,45)'},
    {v: '3', l: '3 (123,456)'},
    {v: '4', l: '4 (123,4567)'},
    {v: '5', l: '5 (123,45678)'},
    {v: '6', l: '6 (123,456789)'},
  ];
  var html = '';
  var cur = String(current == null ? '' : current);
  opts.forEach(function(o) {
    html += '<option value="' + o.v + '"' + (cur === o.v ? ' selected' : '') + '>' + o.l + '</option>';
  });
  return html;
}
```

- [ ] **Step 2: Add 4-th dual-row for format**

Find in `renderParamDetail` (around the dual-row section):

```javascript
    _dualRow('Nazwa PL', 'name_pl', p.name_pl_global || '', p.name_pl_override) +
    _dualRow('Nazwa EN', 'name_en', p.name_en_global || '', p.name_en_override) +
    _dualRow('Metoda',  'method',  p.method_global  || '', p.method_override) +
```

Add after these 3 rows (before the single-section start):

```javascript
    _dualRowSelect('Precyzja', 'format', p.format_global || '', p.format_override) +
```

- [ ] **Step 3: Add `_dualRowSelect` helper**

Add near `_dualRow`:

```javascript
function _dualRowSelect(label, fieldKey, globalVal, overrideVal) {
  var hasOverride = overrideVal !== null && overrideVal !== undefined && overrideVal !== '';
  return '<div class="wc-md-dual-row">' +
    '<div class="wc-md-dual-cell">' +
      '<label>' + _esc(label) + '</label>' +
      '<select data-md="' + fieldKey + '_global" disabled style="opacity:.7;cursor:not-allowed;">' + _fmtOptions(globalVal) + '</select>' +
      '<div style="font-size:9px;color:var(--text-dim);padding:0 9px;">Z rejestru — edytuj w /admin/parametry</div>' +
    '</div>' +
    '<div class="wc-md-dual-cell">' +
      '<label>' + _esc(label) + ' (override) ' +
        '<button type="button" class="wc-md-reset' + (hasOverride ? '' : ' hidden') + '" data-reset-for="' + fieldKey + '_override" onclick="resetOverride(\'' + fieldKey + '_override\')" title="Reset do globalnego (rejestru)" aria-label="Reset"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg></button>' +
      '</label>' +
      '<select data-md="' + fieldKey + '_override" onchange="onOverrideFieldChange(this)">' + _fmtOptions(overrideVal == null ? '' : overrideVal) + '</select>' +
      '<div style="font-size:10px;color:var(--text-dim);padding:0 9px;">' + (hasOverride ? 'Override aktywny — kliknij ⤺ aby reset.' : 'Puste = dziedzicz precyzję z rejestru.') + '</div>' +
    '</div>' +
  '</div>';
}
```

The format_global is read-only (registry-only) — admin must go to Rejestr to change. format_override has dropdown. Existing `onOverrideFieldChange` and `resetOverride` already handle the override side via `data-md` query.

- [ ] **Step 4: Update `_buildCertConfigPayload`**

Find:

```javascript
        name_pl: p.name_pl_override == null ? null : p.name_pl_override,
        name_en: p.name_en_override == null ? null : p.name_en_override,
        method: p.method_override == null ? null : p.method_override,
        name_pl_global: p.name_pl_global || '',
        name_en_global: p.name_en_global || '',
        method_global: p.method_global || '',
```

Add after:

```javascript
        format: p.format_override == null ? null : p.format_override,
        format_global: p.format_global || '',
```

Also update the legacy `format` line (which uses effective). Find:

```javascript
        format: p.format || '',
```

Remove that line (it conflicts with our new `format` line above which sends override). The new line `format: p.format_override == null ? null : p.format_override` is the correct one.

- [ ] **Step 5: Update `saveCurrentParamToState` to capture format_override**

Find:

```javascript
  p.method_override = _val_or_null('[data-md="method_override"]');
```

Add after:

```javascript
  p.format_override = _val_or_null('[data-md="format_override"]');
```

- [ ] **Step 6: Update `build_preview_context` (server) to include format fallback**

In `mbr/certs/generator.py`, find the recently-added `build_preview_context` fallback block (commit `bf55fd4`):

```python
        name_pl_eff = param.get("name_pl") or param.get("name_pl_global") or ""
        ne_override = param.get("name_en")
        if ne_override is not None:
            _ne = ne_override
        else:
            _ne = param.get("name_en_global") or ""
        method_eff = param.get("method") or param.get("method_global") or ""
```

Add format fallback:

```python
        format_eff = param.get("format") or param.get("format_global") or "1"
```

Use it in the row dict. Find:

```python
        rows.append({
            "name_pl": _md_to_richtext(name_pl_eff, font=_settings["body_font_family"]),
            "name_en": _md_to_richtext(f"/{_ne}", font=_settings["body_font_family"]) if _ne else None,
            "requirement": param.get("requirement", ""),
            "method": method_eff,
            "result": result,
        })
```

The result computation might use format. Trace existing code; if `result = "1,0000"` placeholder is hardcoded, we don't need to change anything (preview is fixed-format placeholder for visual sizing). Skip this if result is hardcoded.

- [ ] **Step 7: Verify in browser**

Hard reload. Otwórz produkt → Parametry świadectwa → klik parametr. W detail panelu pojawia się 4-ty dual-row „Precyzja":
- Lewa kolumna: select disabled z aktualną precyzją z rejestru (opacity .7, „Z rejestru — edytuj w /admin/parametry")
- Prawa kolumna: select z opcjami przykładów. Domyślnie pusty (= dziedzicz). Wybierz np. `2 (123,45)` → reset ⤺ pojawia się.

Klik Save → cert config persisted z `format_override=2`. Reload → pokazuje override.

Klik ⤺ → pole pusto → zapisz → format_override = NULL → reload pokazuje że dziedzicze z lewej kolumny.

Wygeneruj Podgląd PDF — precyzja na cercie odzwierciedla efektywną wartość.

- [ ] **Step 8: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html mbr/certs/generator.py
git commit -m "feat(wzory-cert): format dual-field — 4-ty wiersz globalne|override (C1)"
```

---

## Phase D — Migration extension

### Task D1: Extend migrate_cert_override_cleanup.py for format

**Files:**
- Modify: `scripts/migrate_cert_override_cleanup.py`
- Modify: `tests/test_migrate_cert_override_cleanup.py` (add 2 tests)

- [ ] **Step 1: Add failing tests**

Append to `tests/test_migrate_cert_override_cleanup.py`:

```python
def test_migration_nulls_format_when_matches_precision(db):
    """format='4' + precision=4 → both numeric-equal after int conversion → NULL."""
    db.execute("DELETE FROM parametry_analityczne")
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, precision) "
        "VALUES (1, 'nd20', 'nD20', 'bezposredni', 4)"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('A', 'A')")
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, format, variant_id) "
        "VALUES ('A', 1, 0, '4', NULL)"
    )
    db.commit()
    from scripts.migrate_cert_override_cleanup import run_migration
    run_migration(db)
    row = db.execute("SELECT format FROM parametry_cert WHERE produkt='A'").fetchone()
    assert row["format"] is None


def test_migration_preserves_format_mismatch(db):
    """format='1' + precision=4 → numerically different → preserved."""
    db.execute("DELETE FROM parametry_analityczne")
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, precision) "
        "VALUES (1, 'nd20', 'nD20', 'bezposredni', 4)"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('A', 'A')")
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, format, variant_id) "
        "VALUES ('A', 1, 0, '1', NULL)"
    )
    db.commit()
    from scripts.migrate_cert_override_cleanup import run_migration
    run_migration(db)
    row = db.execute("SELECT format FROM parametry_cert WHERE produkt='A'").fetchone()
    assert row["format"] == '1'  # mismatch — preserved


def test_migration_format_handles_null_precision(db):
    """format='2' + precision=NULL → use default 2 → match → NULL."""
    db.execute("DELETE FROM parametry_analityczne")
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, precision) "
        "VALUES (1, 'x', 'X', 'bezposredni', NULL)"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('A', 'A')")
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, format, variant_id) "
        "VALUES ('A', 1, 0, '2', NULL)"
    )
    db.commit()
    from scripts.migrate_cert_override_cleanup import run_migration
    run_migration(db)
    row = db.execute("SELECT format FROM parametry_cert WHERE produkt='A'").fetchone()
    assert row["format"] is None  # 2 == default 2 → match


def test_migration_format_in_stats(db):
    """nulled_per_field stats include 'format' key."""
    _seed(db)
    db.execute("INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, format, variant_id) VALUES ('A', 1, 0, NULL, NULL)")
    db.execute("INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, format, variant_id) VALUES ('B', 1, 0, '5', NULL)")
    db.commit()
    from scripts.migrate_cert_override_cleanup import run_migration
    stats = run_migration(db)
    assert "format" in stats["nulled_per_field"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_migrate_cert_override_cleanup.py -v -k "format"
```

Expected: 4 failures.

- [ ] **Step 3: Extend migration script**

In `scripts/migrate_cert_override_cleanup.py`, find:

```python
    rows = db.execute(
        """
        SELECT pc.rowid AS rid, pc.produkt, pc.variant_id, pc.parametr_id,
               pc.name_pl, pc.name_en, pc.method,
               pa.kod, pa.label, pa.name_en AS pa_name_en, pa.method_code
        FROM parametry_cert pc
        JOIN parametry_analityczne pa ON pa.id = pc.parametr_id
        """
    ).fetchall()
```

Replace with (add `pc.format` and `pa.precision`):

```python
    rows = db.execute(
        """
        SELECT pc.rowid AS rid, pc.produkt, pc.variant_id, pc.parametr_id,
               pc.name_pl, pc.name_en, pc.method, pc.format,
               pa.kod, pa.label, pa.name_en AS pa_name_en, pa.method_code,
               pa.precision AS pa_precision
        FROM parametry_cert pc
        JOIN parametry_analityczne pa ON pa.id = pc.parametr_id
        """
    ).fetchall()
```

Find:

```python
    nulled = {"name_pl": 0, "name_en": 0, "method": 0}
```

Replace with:

```python
    nulled = {"name_pl": 0, "name_en": 0, "method": 0, "format": 0}
```

In the for loop, find:

```python
        for cert_field, registry_val in [
            ("name_pl", r["label"]),
            ("name_en", r["pa_name_en"]),
            ("method", r["method_code"]),
        ]:
            override = r[cert_field]
            if override is None:
                continue
            if _eq_norm(override, registry_val):
                updates[cert_field] = None
                nulled[cert_field] += 1
                nulled_total += 1
            else:
                preserved_total += 1
                ...
```

After the loop body but inside the row-iteration, add a separate handler for `format`:

```python
        # format compared numerically (string TEXT vs INTEGER)
        cert_format = r["format"]
        if cert_format is not None:
            try:
                cert_format_int = int(cert_format)
            except (ValueError, TypeError):
                cert_format_int = None  # malformed, skip

            if cert_format_int is not None:
                # NULL precision → treat as default 2 (legacy)
                reg_precision = r["pa_precision"] if r["pa_precision"] is not None else 2
                if cert_format_int == reg_precision:
                    updates["format"] = None
                    nulled["format"] += 1
                    nulled_total += 1
                else:
                    preserved_total += 1
                    if len(preserved_examples) < 50:
                        preserved_examples.append({
                            "produkt": r["produkt"],
                            "variant_id": r["variant_id"],
                            "kod": r["kod"],
                            "field": "format",
                            "override_value": cert_format,
                            "registry_value": str(reg_precision),
                        })
```

Update `main()` print stats output. Find:

```python
    print(f"  - name_pl:  {stats['nulled_per_field']['name_pl']}")
    print(f"  - name_en:  {stats['nulled_per_field']['name_en']}")
    print(f"  - method:   {stats['nulled_per_field']['method']}")
```

Add line:

```python
    print(f"  - format:   {stats['nulled_per_field']['format']}")
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_migrate_cert_override_cleanup.py -v
```

Expected: 8 (existing) + 4 (new) = 12 passing.

- [ ] **Step 5: Run dry-run on dev DB to inspect impact**

```bash
cp data/batch_db.sqlite /tmp/batch_db.format_test.sqlite
python -m scripts.migrate_cert_override_cleanup --db /tmp/batch_db.format_test.sqlite --dry-run | head -40
```

Spodziewane output: ~138 wierszy do zNULLowania w polu `format` (per analizę gdzie precision matched format).

- [ ] **Step 6: Commit**

```bash
git add scripts/migrate_cert_override_cleanup.py tests/test_migrate_cert_override_cleanup.py
git commit -m "feat(scripts): cleanup migration extension for format dual-field (D1)"
```

---

### Task D2: Update migration runbook

**Files:**
- Modify: `docs/migrations/2026-04-cert-override-cleanup.md`

- [ ] **Step 1: Add format section to runbook**

In `docs/migrations/2026-04-cert-override-cleanup.md`, in the "Co robi" section, add:

```markdown
**Update 2026-04-28 (parametry rejestr redesign):** Skrypt rozszerzony o czwarte pole — `parametry_cert.format` (precyzja cyfrowa cert względem `parametry_analityczne.precision`). Logika porównania: konwersja `format` (string TEXT) na int + `precision` (INTEGER, NULL → default 2 per legacy COALESCE w `get_parametry_for_kontekst`); jeśli numerycznie równe → NULL.
```

In the "Pre-flight" section, dry-run output sample, add the format line:

```
Override fields nulled:   522
  - name_pl:  43
  - name_en:  228
  - method:   251
  - format:   138    ← NEW (D1 extension)
```

- [ ] **Step 2: Commit**

```bash
git add docs/migrations/2026-04-cert-override-cleanup.md
git commit -m "docs(migrations): runbook update for format cleanup extension (D2)"
```

---

## Self-Review Notes

**Spec coverage:**
- Section 1 (master-detail layout) → B1, B2, B3, B4, B7
- Section 2 (banner usage-impact field-specific) → B6
- Section 3 (Save Wszystko) → B8
- Section 4 (Add Parameter modal) → B9
- Section 5 (soft delete + reactivate) → B10
- Section 6 (backend changes) → A1, A2, A3, A4, A5
- Section 7 (format dual-field cert editor) → A4, A5, C1
- Section 8 (frontend implementation details) → covered across B tasks
- Section 9 (migration extension) → D1, D2
- Section 10 (audit) → A1 (precision + aktywny), A2 (created), A3 covered

**Backward compat preserved:**
- `get_cert_params` legacy fields (`name_pl`, `name_en`, `method`, `format`) untouched
- `parametry_cert.format` schema unchanged
- `PUT /api/parametry/<id>` accepts arbitrary subset of fields (extends, no breaking change)
- Migration script idempotent (existing test still passes after extending logic)

**Type consistency:**
- All function names match: `rejLoadParams`, `rejRenderList`, `rejRenderDetail`, `rejSelect`, `rejFilter`, `rejTogglePill`, `rejOnFieldInput`, `rejOnTypChange`, `rejSaveCurrentToState`, `rejSaveAll`, `rejDeactivate`, `rejReactivate`, `rejOpenAddModal`, `rejConfirmAdd`, `rejRefreshBanner`, `rejTbInsert`, `rejUpdateToolbarState`, `rejMarkDirty`, `rejToggleShowInactive`
- State vars consistent: `_rejParams`, `_rejSelectedId`, `_rejFilter`, `_rejTypFilter`, `_rejDirty`, `_rejOriginalParam`, `_rejUsageCache`, `_rejFocusedInput`, `_rejShowInactive`
- Backend field names consistent: `format_global`/`format_override` mirrors `name_pl_global`/`name_pl_override`

**No placeholders found** — all task steps include exact code, file paths, expected outputs.
