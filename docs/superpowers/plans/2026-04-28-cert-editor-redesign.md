# Cert Editor Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Przebudować edytor szablonów świadectw (`/admin/wzory-cert`) na układ master-detail z dwukolumnową semantyką globalne | per produkt, dodać toolbar formatowania, banner usage-impact i skrypt migracji który wyczyści istniejące „pseudo-overrides" w `parametry_cert`.

**Architecture:** Backend reużywa istniejący `PUT /api/parametry/<id>` (dodaje audit), dodaje `GET /api/parametry/<id>/usage-impact`, modyfikuje `get_cert_params`/`get_cert_variant_params` żeby zwracały global+override osobno. Frontend (`mbr/templates/admin/wzory_cert.html`) dostaje master-detail layout z lewym panelem listy i prawym dwukolumnowym edytorem. Skrypt migracji `scripts/migrate_cert_override_cleanup.py` zNULLuje overrides equal-to-registry (po normalizacji whitespace).

**Tech Stack:** Flask + SQLite (raw sqlite3, no ORM) backend; Jinja2 + vanilla JS (no framework) frontend; pytest dla testów; `mbr.shared.audit.log_event` + `diff_fields` dla audytu.

**Spec:** `docs/superpowers/specs/2026-04-28-cert-editor-redesign-design.md` (przeczytaj przed startem).

---

## File Structure

**Backend (Phase A):**
- Modify `mbr/parametry/routes.py` — dodać audit do `PUT /api/parametry/<id>`, dodać GET `/api/parametry/<id>/usage-impact`
- Modify `mbr/parametry/registry.py` — `get_cert_params` i `get_cert_variant_params` zwracają nowe pola `*_global` i `*_override`
- Test: `tests/test_parametry_registry_audit.py` — audit emisja przy edycji label/name_en/method_code
- Test: `tests/test_parametry_usage_impact.py` — endpoint zwraca cert/mbr counts
- Test: `tests/test_cert_params_dual_field.py` — `get_cert_params` zwraca global+override

**Frontend (Phase B+C):**
- Modify `mbr/templates/admin/wzory_cert.html` — przepisanie zakładki Parametry i Warianty na master-detail. Plik już duży (1475 linii) — w ramach planu robimy **wewnętrzną reorganizację** (sekcje CSS pogrupowane, JS pogrupowany), ale nie wyciągamy do osobnych plików (zgodnie z konwencją projektu — całe blueprint UI w jednym template).

**Migracja (Phase D):**
- Create `scripts/migrate_cert_override_cleanup.py` — skrypt cleanup
- Test: `tests/test_migrate_cert_override_cleanup.py` — TDD migration script
- Create `docs/migrations/2026-04-cert-override-cleanup.md` — dokumentacja runbooku

---

## Phase A — Backend (TDD)

### Task A1: Audit logging w PUT /api/parametry/<id>

**Files:**
- Modify: `mbr/parametry/routes.py` (function `api_parametry_update`, lines 70-153)
- Test: `tests/test_parametry_registry_audit.py` (create)

- [ ] **Step 1: Write failing test — audit event emitted on label change**

```python
# tests/test_parametry_registry_audit.py
"""PUT /api/parametry/<id> emits audit event with diff."""
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
        "INSERT INTO parametry_analityczne (id, kod, label, typ, name_en, method_code) "
        "VALUES (1, 'nd20', 'nD20', 'bezposredni', 'Refractive index', 'PN-EN ISO 5661')"
    )
    db.commit()


def _admin_client(monkeypatch, db):
    import mbr.db
    import mbr.parametry.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.parametry.routes, "db_session", fake_db_session)

    from mbr.app import app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "admin", "rola": "admin", "imie_nazwisko": "Admin"}
    return client


def test_put_parametry_emits_audit_on_label_change(monkeypatch, db):
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1", json={"label": "Współczynnik załamania"})
    assert rv.status_code == 200

    rows = db.execute(
        "SELECT event_type, entity_type, entity_id, entity_label, diff_json "
        "FROM audit_log WHERE event_type='parametr.updated'"
    ).fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["entity_type"] == "parametr"
    assert r["entity_id"] == 1
    assert r["entity_label"] == "nd20"
    diff = json.loads(r["diff_json"])
    assert diff == [{"pole": "label", "stara": "nD20", "nowa": "Współczynnik załamania"}]


def test_put_parametry_no_audit_when_nothing_changes(monkeypatch, db):
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1", json={"label": "nD20"})  # same value
    assert rv.status_code == 200

    rows = db.execute(
        "SELECT 1 FROM audit_log WHERE event_type='parametr.updated'"
    ).fetchall()
    assert len(rows) == 0


def test_put_parametry_audit_multifield_diff(monkeypatch, db):
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1", json={
        "label": "Wsp. załamania",
        "name_en": "Refractive index 20°C",
        "method_code": "PN-EN ISO 5661:2024",
    })
    assert rv.status_code == 200

    rows = db.execute(
        "SELECT diff_json FROM audit_log WHERE event_type='parametr.updated'"
    ).fetchall()
    assert len(rows) == 1
    diff = json.loads(rows[0]["diff_json"])
    fields = sorted(d["pole"] for d in diff)
    assert fields == ["label", "method_code", "name_en"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_parametry_registry_audit.py -v
```

Expected: 3 failures — `audit_log` rows count == 0 (audit not currently emitted by endpoint).

- [ ] **Step 3: Add audit logging to endpoint**

In `mbr/parametry/routes.py`, modify `api_parametry_update`:

Add imports at top of file:
```python
from mbr.shared.audit import log_event, EVENT_PARAMETR_UPDATED, diff_fields
```

In the function, after fetching `existing` and BEFORE running the `UPDATE` (insert below line 86 `if not existing: return jsonify({"error": "Parametr not found"}), 404`):

```python
        # Snapshot old state for audit diff (label/name_en/method_code only).
        old_audit = db.execute(
            "SELECT label, name_en, method_code FROM parametry_analityczne WHERE id=?",
            (param_id,),
        ).fetchone()
```

After the `UPDATE` statement (line 136) and BEFORE the `affected = ...` block, insert:

```python
        # Audit registry-level field changes (label / name_en / method_code).
        # Other fields (skrot, formula, etc.) are admin-internal — not audited here.
        new_audit = db.execute(
            "SELECT label, name_en, method_code FROM parametry_analityczne WHERE id=?",
            (param_id,),
        ).fetchone()
        diff = diff_fields(dict(old_audit), dict(new_audit), ["label", "name_en", "method_code"])
        if diff:
            log_event(
                EVENT_PARAMETR_UPDATED,
                entity_type="parametr",
                entity_id=param_id,
                entity_label=existing["kod"],
                diff=diff,
                db=db,
            )
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_parametry_registry_audit.py -v
```

Expected: 3 passing.

- [ ] **Step 5: Run full parametry test suite to check no regressions**

```bash
pytest tests/test_migrate_parametry_ssot.py tests/test_bindings_api.py tests/test_admin_audit.py -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add mbr/parametry/routes.py tests/test_parametry_registry_audit.py
git commit -m "feat(parametry): audit log_event on PUT /api/parametry/<id> for label/name_en/method_code"
```

---

### Task A2: GET /api/parametry/<id>/usage-impact endpoint

**Files:**
- Modify: `mbr/parametry/routes.py` (add new route)
- Test: `tests/test_parametry_usage_impact.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_parametry_usage_impact.py
"""GET /api/parametry/<id>/usage-impact — counts for banner."""
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
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (2, 'orphan', 'orphan', 'bezposredni')")
    # 3 cert products use parametr 1, 0 use parametr 2
    for produkt in ("PROD_A", "PROD_B", "PROD_C"):
        db.execute("INSERT INTO produkty (nazwa, display_name) VALUES (?, ?)", (produkt, produkt))
        db.execute(
            "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, variant_id) VALUES (?, 1, 0, NULL)",
            (produkt,),
        )
    # 2 distinct mbr products use parametr 1 in parametry_etapy
    db.execute("INSERT INTO parametry_etapy (parametr_id, produkt, kontekst, kolejnosc) VALUES (1, 'PROD_A', 'analiza_koncowa', 0)")
    db.execute("INSERT INTO parametry_etapy (parametr_id, produkt, kontekst, kolejnosc) VALUES (1, 'PROD_X', 'analiza_koncowa', 0)")
    db.commit()


def _client(monkeypatch, db, rola="admin"):
    import mbr.db
    import mbr.parametry.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.parametry.routes, "db_session", fake_db_session)

    from mbr.app import app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "u", "rola": rola}
    return client


def test_usage_impact_counts_cert_and_mbr(monkeypatch, db):
    _seed(db)
    client = _client(monkeypatch, db)

    rv = client.get("/api/parametry/1/usage-impact")
    assert rv.status_code == 200
    j = rv.get_json()
    assert j["cert_products_count"] == 3
    assert j["mbr_products_count"] == 2


def test_usage_impact_zero_when_unused(monkeypatch, db):
    _seed(db)
    client = _client(monkeypatch, db)

    rv = client.get("/api/parametry/2/usage-impact")
    assert rv.status_code == 200
    j = rv.get_json()
    assert j["cert_products_count"] == 0
    assert j["mbr_products_count"] == 0


def test_usage_impact_404_for_unknown_parametr(monkeypatch, db):
    _seed(db)
    client = _client(monkeypatch, db)

    rv = client.get("/api/parametry/999/usage-impact")
    assert rv.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_parametry_usage_impact.py -v
```

Expected: 3 failures (404 for all — endpoint not registered).

- [ ] **Step 3: Implement the endpoint**

Add to `mbr/parametry/routes.py` (after `api_parametry_update`):

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

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_parametry_usage_impact.py -v
```

Expected: 3 passing.

- [ ] **Step 5: Commit**

```bash
git add mbr/parametry/routes.py tests/test_parametry_usage_impact.py
git commit -m "feat(parametry): GET /api/parametry/<id>/usage-impact for banner"
```

---

### Task A3: get_cert_params zwraca global + override osobno

**Files:**
- Modify: `mbr/parametry/registry.py` (functions `get_cert_params`, `get_cert_variant_params`, lines 231-298)
- Test: `tests/test_cert_params_dual_field.py` (create)

- [ ] **Step 1: Write failing test**

```python
# tests/test_cert_params_dual_field.py
"""get_cert_params returns name_pl_global + name_pl_override etc."""
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
    # Global registry values
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, name_en, method_code) "
        "VALUES (1, 'nd20', 'Wsp. załamania', 'bezposredni', 'Refractive index', 'PN-EN ISO 5661')"
    )
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, name_en, method_code) "
        "VALUES (2, 'lk', 'Liczba kwasowa', 'bezposredni', 'Acid value', 'PN-EN ISO 660')"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('TEST', 'Test')")
    # Row 1: no overrides (NULL)
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, name_en, method, variant_id) "
        "VALUES ('TEST', 1, 0, NULL, NULL, NULL, NULL)"
    )
    # Row 2: name_en overridden, method overridden, name_pl NULL
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, name_en, method, variant_id) "
        "VALUES ('TEST', 2, 1, NULL, 'Acid number', 'Internal proc 12', NULL)"
    )
    db.commit()


def test_get_cert_params_returns_global_fields(db):
    _seed(db)
    rows = get_cert_params(db, "TEST")
    assert len(rows) == 2

    r0 = rows[0]
    # Global from parametry_analityczne
    assert r0["name_pl_global"] == "Wsp. załamania"
    assert r0["name_en_global"] == "Refractive index"
    assert r0["method_global"] == "PN-EN ISO 5661"
    # Override raw — all NULL
    assert r0["name_pl_override"] is None
    assert r0["name_en_override"] is None
    assert r0["method_override"] is None
    # Effective fallback (legacy field names) — kept for backward compat
    assert r0["name_pl"] == "Wsp. załamania"
    assert r0["name_en"] == "Refractive index"
    assert r0["method"] == "PN-EN ISO 5661"


def test_get_cert_params_returns_override_when_set(db):
    _seed(db)
    rows = get_cert_params(db, "TEST")
    r1 = rows[1]
    # Globals present
    assert r1["name_pl_global"] == "Liczba kwasowa"
    assert r1["name_en_global"] == "Acid value"
    assert r1["method_global"] == "PN-EN ISO 660"
    # Overrides — only name_en and method
    assert r1["name_pl_override"] is None
    assert r1["name_en_override"] == "Acid number"
    assert r1["method_override"] == "Internal proc 12"
    # Effective fallback prefers override
    assert r1["name_pl"] == "Liczba kwasowa"  # fallback to global
    assert r1["name_en"] == "Acid number"  # override
    assert r1["method"] == "Internal proc 12"  # override


def test_get_cert_variant_params_dual_fields(db):
    _seed(db)
    db.execute(
        "INSERT INTO cert_variants (id, produkt, variant_id, label, flags, kolejnosc) "
        "VALUES (10, 'TEST', 'lv', 'LV', '[]', 0)"
    )
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, name_en, method, variant_id) "
        "VALUES ('TEST', 1, 0, 'Variant nazwa', NULL, NULL, 10)"
    )
    db.commit()

    rows = get_cert_variant_params(db, 10)
    assert len(rows) == 1
    r = rows[0]
    assert r["name_pl_global"] == "Wsp. załamania"
    assert r["name_pl_override"] == "Variant nazwa"
    assert r["name_en_global"] == "Refractive index"
    assert r["name_en_override"] is None
    assert r["name_pl"] == "Variant nazwa"  # effective
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cert_params_dual_field.py -v
```

Expected: 3 failures — `KeyError: 'name_pl_global'` (new fields not returned).

- [ ] **Step 3: Modify `get_cert_params`**

Replace return list comprehension in `mbr/parametry/registry.py:get_cert_params`:

```python
    return [
        {
            "kod": r["kod"],
            "parametr_id": r["parametr_id"],
            "typ": r["typ"],
            "grupa": r["grupa"],
            # Global registry values (always present)
            "name_pl_global": r["label"] or "",
            "name_en_global": r["name_en"] or "",
            "method_global": r["method_code"] or "",
            # Per-product overrides (raw — None means "inherit")
            "name_pl_override": r["cert_name_pl"],
            "name_en_override": r["cert_name_en"],
            "method_override": r["cert_method"],
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

- [ ] **Step 4: Modify `get_cert_variant_params` identically**

Apply the same return-comprehension change to `get_cert_variant_params`.

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_cert_params_dual_field.py -v
```

Expected: 3 passing.

- [ ] **Step 6: Run full cert test suite to check no regressions**

```bash
pytest tests/test_certs.py tests/test_cert_template_render.py tests/test_cert_jakosciowy_render.py tests/test_cert_editor_atomicity.py -v
```

Expected: all green (existing tests use legacy fields `name_pl/name_en/method` — these still work).

- [ ] **Step 7: Commit**

```bash
git add mbr/parametry/registry.py tests/test_cert_params_dual_field.py
git commit -m "feat(parametry): get_cert_params returns *_global + *_override fields"
```

---

### Task A4: Cert config GET endpoint exposes new fields

**Files:**
- Verify: `mbr/certs/routes.py` (function returning cert config — should auto-pick up new fields via `get_cert_params`)
- Test: `tests/test_cert_config_response_dual_field.py` (create)

- [ ] **Step 1: Identify the GET endpoint**

```bash
grep -n "def api_cert_config_product_get\|@certs_bp.route.*config/product/<\|GET.*config" mbr/certs/routes.py | head -20
```

Find the `GET /api/cert/config/product/<key>` route — it likely calls `get_cert_params`/`get_cert_variant_params`. Verify it returns whatever those functions return (no field whitelist).

- [ ] **Step 2: Write test that endpoint exposes new fields**

```python
# tests/test_cert_config_response_dual_field.py
"""GET /api/cert/config/product/<key> exposes *_global and *_override fields."""
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
        "INSERT INTO parametry_analityczne (id, kod, label, typ, name_en, method_code) "
        "VALUES (1, 'nd20', 'Wsp. załamania', 'bezposredni', 'Refractive index', 'PN-EN ISO 5661')"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('TEST', 'Test')")
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) VALUES ('TEST', 'base', 'Base', '[]', 0)"
    )
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, name_en, method, variant_id) "
        "VALUES ('TEST', 1, 0, NULL, 'Refractive index custom', NULL, NULL)"
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


def test_cert_config_get_returns_dual_fields(monkeypatch, db):
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.get("/api/cert/config/product/TEST")
    assert rv.status_code == 200
    j = rv.get_json()
    assert j["ok"] is True
    params = j["product"]["parameters"]
    assert len(params) == 1
    p = params[0]
    assert p["name_pl_global"] == "Wsp. załamania"
    assert p["name_en_global"] == "Refractive index"
    assert p["method_global"] == "PN-EN ISO 5661"
    assert p["name_pl_override"] is None
    assert p["name_en_override"] == "Refractive index custom"
    assert p["method_override"] is None
```

- [ ] **Step 3: Run test**

```bash
pytest tests/test_cert_config_response_dual_field.py -v
```

If endpoint passes through dict unchanged: PASS. If endpoint whitelists fields: FAIL — find the whitelist and add new field names. Most likely passes since previous testing of `name_pl_override` etc. depends on `get_cert_params` output flowing through.

- [ ] **Step 4: If failed, fix the endpoint**

Open `mbr/certs/routes.py`, find the cert config GET handler. If there's a field-whitelist on `parameters`, add new fields. If JSON serialization is `dict(row)` style — should work.

- [ ] **Step 5: Re-run + commit**

```bash
pytest tests/test_cert_config_response_dual_field.py -v
git add tests/test_cert_config_response_dual_field.py mbr/certs/routes.py
git commit -m "test(certs): cert config GET exposes *_global/*_override fields"
```

---

## Phase B — Frontend Parametry tab

> **Phase B note:** Frontend changes have no automated tests. Each task verifies in browser at `http://localhost:5001/admin/wzory-cert` after starting the dev server (`python -m mbr.app`). Provide screenshots / observed behavior in commit messages.

### Task B1: Master-detail HTML+CSS scaffold (Parametry tab)

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html` (replace lines ~245-268, the existing Parametry panel)

- [ ] **Step 1: Add CSS for master-detail layout**

In the `<style>` section (between the existing CSS rules), append:

```css
/* ═══ Master-detail (Parametry + Warianty) ═══ */
.wc-md { display: grid; grid-template-columns: 280px 1fr; gap: 14px; min-height: 340px; }
.wc-md-list { border: 1px solid var(--border); border-radius: 6px; background: var(--surface-alt); overflow: hidden; display: flex; flex-direction: column; }
.wc-md-search { padding: 8px; border-bottom: 1px solid var(--border); background: var(--surface); }
.wc-md-search input { width: 100%; padding: 5px 8px; border: 1px solid var(--border); border-radius: 4px; font-size: 11px; box-sizing: border-box; }
.wc-md-list-body { flex: 1; overflow-y: auto; max-height: 480px; }
.wc-md-item { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-bottom: 1px solid var(--border-subtle, #f0ece4); cursor: pointer; font-size: 11px; }
.wc-md-item:hover { background: var(--surface); }
.wc-md-item.active { background: var(--surface); border-left: 3px solid var(--teal); padding-left: 7px; }
.wc-md-item.dirty .wc-md-item-name::after { content: " •"; color: var(--orange, #d97706); font-weight: bold; }
.wc-md-drag { color: var(--text-dim); cursor: grab; user-select: none; font-size: 12px; }
.wc-md-drag:active { cursor: grabbing; }
.wc-md-item-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: 'Times New Roman', serif; }
.wc-md-item-name sub { font-size: .75em; vertical-align: sub; }
.wc-md-item-name sup { font-size: .75em; vertical-align: super; }
.wc-md-item-bind { font-family: var(--mono); font-size: 9px; background: var(--surface-alt); color: var(--teal); padding: 1px 5px; border-radius: 3px; flex-shrink: 0; }
.wc-md-add { padding: 8px 10px; background: var(--surface); border-top: 1px solid var(--border); color: var(--teal); cursor: pointer; font-weight: 600; text-align: center; font-size: 11px; }
.wc-md-add:hover { background: var(--surface-alt); }

.wc-md-detail { padding: 14px 16px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); }
.wc-md-detail-empty { display: flex; align-items: center; justify-content: center; min-height: 200px; color: var(--text-dim); font-size: 12px; }

/* Toolbar in detail header */
.wc-md-toolbar { display: flex; align-items: center; gap: 4px; padding: 6px 8px; background: var(--surface-alt); border: 1px solid var(--border); border-radius: 4px; margin-bottom: 12px; }
.wc-md-toolbar-label { font-size: 9px; color: var(--text-dim); text-transform: uppercase; letter-spacing: .3px; margin-right: 6px; }
.wc-md-tbtn { background: transparent; border: 1px solid transparent; cursor: pointer; padding: 3px 8px; font-size: 11px; border-radius: 3px; color: var(--text); font-family: var(--mono); min-width: 24px; }
.wc-md-tbtn:hover:not(:disabled) { background: var(--surface); border-color: var(--border); }
.wc-md-tbtn:disabled { opacity: .35; cursor: not-allowed; }
.wc-md-tbtn sub, .wc-md-tbtn sup { font-size: .75em; }

/* Two-column dual-field layout */
.wc-md-dual-header { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; font-size: 9px; color: var(--text-dim); text-transform: uppercase; letter-spacing: .3px; margin-bottom: 4px; padding-bottom: 4px; border-bottom: 1px solid var(--border-subtle, #f0ece4); }
.wc-md-dual-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 16px; margin-bottom: 10px; }
.wc-md-dual-cell { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.wc-md-dual-cell label { font-size: 10px; color: var(--text-dim); display: flex; align-items: center; gap: 6px; }
.wc-md-dual-cell input { padding: 6px 9px; font-size: 11px; border: 1.5px solid var(--border); border-radius: 4px; box-sizing: border-box; font-family: 'Times New Roman', serif; }
.wc-md-dual-cell input:focus { border-color: var(--teal); outline: none; }
.wc-md-dual-cell input.dirty-global { background: #fffbeb; }
.wc-md-rt-prev { font-size: 11px; color: var(--text-dim); padding: 0 9px; min-height: 13px; font-family: 'Times New Roman', serif; }
.wc-md-rt-prev sub { font-size: .75em; vertical-align: sub; }
.wc-md-rt-prev sup { font-size: .75em; vertical-align: super; }
.wc-md-reset { background: transparent; border: 1px solid var(--border); color: var(--text-dim); cursor: pointer; padding: 1px 6px; font-size: 11px; border-radius: 3px; }
.wc-md-reset:hover { color: var(--orange, #d97706); border-color: var(--orange, #d97706); }
.wc-md-reset.hidden { display: none; }

/* Single-column (per-product only) section */
.wc-md-single-section { margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--border-subtle, #f0ece4); }
.wc-md-single-row { display: grid; grid-template-columns: 130px 1fr; gap: 6px 12px; margin-bottom: 8px; align-items: center; }
.wc-md-single-row > label { font-size: 10px; color: var(--text-dim); text-transform: uppercase; letter-spacing: .3px; }
.wc-md-single-row > div { display: flex; gap: 8px; align-items: center; }
.wc-md-single-row input, .wc-md-single-row select { padding: 5px 8px; font-size: 11px; border: 1.5px solid var(--border); border-radius: 4px; box-sizing: border-box; }
.wc-md-single-row input:focus, .wc-md-single-row select:focus { border-color: var(--teal); outline: none; }
.wc-md-single-row input:disabled, .wc-md-single-row select:disabled { background: var(--surface-alt); color: var(--text-dim); cursor: not-allowed; }

/* Banner */
.wc-md-banner { background: #fef3c7; border: 1px solid #f59e0b; color: #78350f; padding: 8px 12px; border-radius: 4px; font-size: 11px; margin: 0 0 12px; line-height: 1.4; }
.wc-md-banner.hidden { display: none; }
.wc-md-banner strong { font-weight: 700; }

/* Detail header */
.wc-md-detail-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid var(--border-subtle, #f0ece4); }
.wc-md-detail-title { font-size: 13px; font-weight: 700; flex: 1; font-family: 'Times New Roman', serif; }
.wc-md-detail-title sub { font-size: .75em; vertical-align: sub; }
.wc-md-detail-title sup { font-size: .75em; vertical-align: super; }
.wc-md-detail-bind { font-family: var(--mono); font-size: 10px; background: var(--surface-alt); color: var(--teal); padding: 2px 7px; border-radius: 3px; }
.wc-md-detail-del { background: transparent; border: 1px solid var(--red); color: var(--red); padding: 2px 9px; font-size: 11px; border-radius: 3px; cursor: pointer; }
.wc-md-detail-del:hover { background: var(--red); color: #fff; }
```

- [ ] **Step 2: Replace the Parametry tab body**

In `mbr/templates/admin/wzory_cert.html`, find this block (around lines 245-268):

```html
<!-- Tab 2: Parametry -->
<div class="wc-panel" id="panel-parametry" style="display:none;">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
    <div style="font-size:13px;font-weight:600;color:var(--text);">Parametry na świadectwie</div>
    <button class="wc-btn wc-btn-o wc-btn-sm" onclick="addParameter()">+ Dodaj parametr</button>
  </div>
  <p class="wc-hint">Indeksy w nazwach: <code>^{...}</code> = górny, <code>_{...}</code> = dolny. Przykład: <code>n_{D}^{20}</code> → n<sub>D</sub><sup>20</sup></p>
  <table class="wc-tbl">
    ...existing table...
  </table>
</div>
```

Replace with:

```html
<!-- Tab 2: Parametry (master-detail layout) -->
<div class="wc-panel" id="panel-parametry" style="display:none;">
  <div class="wc-md">
    <!-- Left: list -->
    <div class="wc-md-list">
      <div class="wc-md-search">
        <input id="wc-md-filter" type="text" placeholder="Filtruj parametry..." oninput="filterParamList(this.value)">
      </div>
      <div class="wc-md-list-body" id="wc-md-list-body"></div>
      <div class="wc-md-add" onclick="openAddParamModal()">+ Dodaj parametr</div>
    </div>

    <!-- Right: detail editor -->
    <div class="wc-md-detail" id="wc-md-detail">
      <div class="wc-md-detail-empty">Wybierz parametr z listy po lewej</div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Verify in browser — empty state**

Run dev server, navigate to `/admin/wzory-cert`, open any product, click „Parametry świadectwa" tab. Expected: empty master-detail layout (left list empty, right says „Wybierz parametr z listy po lewej").

- [ ] **Step 4: Commit (scaffolding only, no JS yet — list won't populate)**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(wzory-cert): master-detail HTML+CSS scaffold for Parametry tab"
```

---

### Task B2: Render left list (renderParamsTable → renderParamList)

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html` (JS section)

- [ ] **Step 1: Replace `renderParamsTable` with `renderParamList`**

Find existing function `renderParamsTable` (around line 912):

```javascript
function renderParamsTable(params) {
  var html = '';
  params.forEach(function(p, i) { html += _paramRow(p, i); });
  document.getElementById('wc-params-body').innerHTML = html;
  initDragAndDrop();
}
```

Replace with:

```javascript
var _selectedParamIdx = null;
var _paramFilter = '';

function renderParamList() {
  var params = (_currentProduct && _currentProduct.parameters) || [];
  var body = document.getElementById('wc-md-list-body');
  if (!body) return;
  var filter = _paramFilter.toLowerCase();
  var html = '';
  params.forEach(function(p, i) {
    var name = p.name_pl_override || p.name_pl_global || p.name_pl || '';
    var kod = p.kod || p.data_field || '';
    if (filter) {
      var hay = (name + ' ' + kod).toLowerCase();
      if (hay.indexOf(filter) === -1) return;
    }
    var activeCls = (i === _selectedParamIdx) ? ' active' : '';
    var dirtyCls = (_paramDirty[i]) ? ' dirty' : '';
    html += '<div class="wc-md-item' + activeCls + dirtyCls + '" data-idx="' + i + '" onclick="selectParam(' + i + ')" draggable="true">' +
      '<span class="wc-md-drag" onmousedown="event.stopPropagation()">&#10303;</span>' +
      '<span class="wc-md-item-name">' + _rtHtml(name) + '</span>' +
      '<span class="wc-md-item-bind">' + _esc(kod) + '</span>' +
    '</div>';
  });
  if (!html) html = '<div style="padding:14px;color:var(--text-dim);font-size:11px;text-align:center;">' +
    (filter ? 'Brak wyników filtra.' : 'Brak parametrów. Kliknij + Dodaj parametr.') + '</div>';
  body.innerHTML = html;
  initParamListDragAndDrop();
}

function filterParamList(value) {
  _paramFilter = value || '';
  renderParamList();
}

var _paramDirty = {};  // idx → bool
function _markParamDirty(idx) { _paramDirty[idx] = true; renderParamList(); _setDirty(true); }

function selectParam(idx) {
  // Persist current edits before switching
  if (_selectedParamIdx !== null) saveCurrentParamToState();
  _selectedParamIdx = idx;
  renderParamList();
  renderParamDetail();
}

function saveCurrentParamToState() {
  // Read inputs from detail panel into _currentProduct.parameters[_selectedParamIdx]
  if (_selectedParamIdx == null || !_currentProduct) return;
  var detail = document.getElementById('wc-md-detail');
  if (!detail) return;
  var p = _currentProduct.parameters[_selectedParamIdx];
  if (!p) return;
  function _val(sel) { var el = detail.querySelector(sel); return el ? el.value : ''; }
  function _val_or_null(sel) { var v = _val(sel); return v === '' ? null : v; }
  p.name_pl_global = _val('[data-md="name_pl_global"]');
  p.name_en_global = _val('[data-md="name_en_global"]');
  p.method_global = _val('[data-md="method_global"]');
  p.name_pl_override = _val_or_null('[data-md="name_pl_override"]');
  p.name_en_override = _val_or_null('[data-md="name_en_override"]');
  p.method_override = _val_or_null('[data-md="method_override"]');
  p.requirement = _val('[data-md="requirement"]');
  p.format = _val('[data-md="format"]');
  p.qualitative_result = _val_or_null('[data-md="qualitative_result"]');
}

function renderParamDetail() {
  var detail = document.getElementById('wc-md-detail');
  if (_selectedParamIdx == null) {
    detail.innerHTML = '<div class="wc-md-detail-empty">Wybierz parametr z listy po lewej</div>';
    return;
  }
  var p = _currentProduct.parameters[_selectedParamIdx];
  if (!p) {
    detail.innerHTML = '<div class="wc-md-detail-empty">Brak parametru.</div>';
    return;
  }
  // Body filled by Task B3
  detail.innerHTML = '<div class="wc-md-detail-empty">[detail body — Task B3]</div>';
}
```

Also find existing `_paramRow` and `addParameter` and `removeBaseParam` and update / preserve them where they're still needed (they'll be repurposed in later tasks). Leave them in for now (unused but safe).

Find function `renderEditor` (around line 898) and replace its call:

```javascript
  renderParamsTable(p.parameters || []);
```

with:

```javascript
  _currentProduct.parameters = p.parameters || [];
  _selectedParamIdx = null;
  _paramDirty = {};
  _paramFilter = '';
  renderParamList();
  renderParamDetail();
```

- [ ] **Step 2: Add stub `initParamListDragAndDrop`**

Add after `renderParamList`:

```javascript
function initParamListDragAndDrop() {
  // Stub — real implementation in Task B9.
}
```

- [ ] **Step 3: Verify in browser — list renders**

Reload dev server. Navigate to `/admin/wzory-cert`, open product with several params, click „Parametry świadectwa". Expected: left list shows param names with rendered sub/sup (np. n<sub>D</sub><sup>20</sup>) + kod tag. Filter input filters list. Click on item → highlights as active. Right panel shows „[detail body — Task B3]".

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(wzory-cert): renderParamList + filter + selection (Task B2)"
```

---

### Task B3: Right detail panel — two-column dual-field editor

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html` (JS — `renderParamDetail`)

- [ ] **Step 1: Implement `renderParamDetail` body**

Replace stub `renderParamDetail` from Task B2:

```javascript
function renderParamDetail() {
  var detail = document.getElementById('wc-md-detail');
  if (_selectedParamIdx == null) {
    detail.innerHTML = '<div class="wc-md-detail-empty">Wybierz parametr z listy po lewej</div>';
    return;
  }
  var p = _currentProduct.parameters[_selectedParamIdx];
  if (!p) {
    detail.innerHTML = '<div class="wc-md-detail-empty">Brak parametru.</div>';
    return;
  }

  var name_pl_eff = p.name_pl_override || p.name_pl_global || '';
  var kod = p.kod || p.data_field || '';
  var bindingDisabled = (p.id || p.parametr_id) ? 'disabled' : '';

  detail.innerHTML =
    '<div class="wc-md-detail-head">' +
      '<div class="wc-md-detail-title">' + _rtHtml(name_pl_eff) + '</div>' +
      '<span class="wc-md-detail-bind">' + _esc(kod) + '</span>' +
      '<button class="wc-md-detail-del" onclick="removeSelectedParam()">Usuń parametr</button>' +
    '</div>' +

    '<div class="wc-md-banner hidden" id="wc-md-banner"></div>' +

    '<div class="wc-md-toolbar" id="wc-md-toolbar">' +
      '<span class="wc-md-toolbar-label">Wstaw do focused pola:</span>' +
      '<button class="wc-md-tbtn" data-tb="sup" onclick="tbInsert(\'sup\')" title="Górny indeks ^{}">X<sup>²</sup></button>' +
      '<button class="wc-md-tbtn" data-tb="sub" onclick="tbInsert(\'sub\')" title="Dolny indeks _{}">X<sub>₂</sub></button>' +
      '<button class="wc-md-tbtn" data-tb="br" onclick="tbInsert(\'br\')" title="Łamanie wiersza |">↲</button>' +
      '<span style="width:1px;height:14px;background:var(--border);margin:0 4px;"></span>' +
      '<button class="wc-md-tbtn" data-tb="leq" onclick="tbInsert(\'leq\')" title="≤">≤</button>' +
      '<button class="wc-md-tbtn" data-tb="geq" onclick="tbInsert(\'geq\')" title="≥">≥</button>' +
      '<button class="wc-md-tbtn" data-tb="div" onclick="tbInsert(\'div\')" title="÷">÷</button>' +
      '<button class="wc-md-tbtn" data-tb="deg" onclick="tbInsert(\'deg\')" title="°">°</button>' +
    '</div>' +

    '<div class="wc-md-dual-header">' +
      '<div>Globalne (rejestr — dotyczy wszystkich produktów)</div>' +
      '<div>Per produkt (puste = dziedzicz globalne)</div>' +
    '</div>' +

    _dualRow('Nazwa PL', 'name_pl', p.name_pl_global || '', p.name_pl_override) +
    _dualRow('Nazwa EN', 'name_en', p.name_en_global || '', p.name_en_override) +
    _dualRow('Metoda',  'method',  p.method_global  || '', p.method_override) +

    '<div class="wc-md-single-section">' +
      '<div class="wc-md-single-row">' +
        '<label>Wymaganie</label>' +
        '<div><input data-md="requirement" value="' + _esc(p.requirement || '') + '" oninput="onParamFieldChange()" style="flex:1;"></div>' +
      '</div>' +
      '<div class="wc-md-single-row">' +
        '<label>Precyzja</label>' +
        '<div><select data-md="format" onchange="onParamFieldChange()" style="width:120px;">' + _fmtOptions(p.format) + '</select></div>' +
      '</div>' +
      '<div class="wc-md-single-row">' +
        '<label>Wynik opisowy</label>' +
        '<div>' + _qualResultInputMd(p) + '</div>' +
      '</div>' +
      '<div class="wc-md-single-row">' +
        '<label>Powiąż z pomiarem</label>' +
        '<div><select data-md="data_field" onchange="onParamFieldChange()" ' + bindingDisabled + ' style="flex:1;max-width:320px;">' +
          _codeOptions(p.data_field || p.kod) + '</select>' +
          (bindingDisabled ? '<span style="font-size:10px;color:var(--text-dim);margin-left:8px;">read-only po utworzeniu</span>' : '') +
        '</div>' +
      '</div>' +
    '</div>';

  // Wire focus tracking on text inputs (toolbar target)
  detail.querySelectorAll('input[type="text"], input:not([type]), input[data-md]').forEach(function(inp) {
    if (inp.tagName !== 'INPUT') return;
    inp.addEventListener('focus', function() { _focusedTextInput = inp; updateToolbarState(); });
  });
  updateToolbarState();
  // Trigger banner on first global-column edit (B7 will fill this in)
}

function _dualRow(label, fieldKey, globalVal, overrideVal) {
  var hasOverride = overrideVal !== null && overrideVal !== undefined && overrideVal !== '';
  return '<div class="wc-md-dual-row">' +
    '<div class="wc-md-dual-cell">' +
      '<label>' + _esc(label) + '</label>' +
      '<input data-md="' + fieldKey + '_global" value="' + _esc(globalVal) + '" oninput="onGlobalFieldChange(this)">' +
      '<div class="wc-md-rt-prev" data-prev-for="' + fieldKey + '_global">' + _rtHtml(globalVal) + '</div>' +
    '</div>' +
    '<div class="wc-md-dual-cell">' +
      '<label>' + _esc(label) + ' (override) ' +
        '<button type="button" class="wc-md-reset' + (hasOverride ? '' : ' hidden') + '" data-reset-for="' + fieldKey + '_override" onclick="resetOverride(\'' + fieldKey + '_override\')" title="Reset do globalnego">⤺</button>' +
      '</label>' +
      '<input data-md="' + fieldKey + '_override" value="' + _esc(overrideVal == null ? '' : overrideVal) + '" placeholder="puste = jak globalne →" oninput="onOverrideFieldChange(this)">' +
      '<div class="wc-md-rt-prev" data-prev-for="' + fieldKey + '_override">' + _rtHtml(overrideVal || '') + '</div>' +
    '</div>' +
  '</div>';
}

function _qualResultInputMd(p) {
  var meta = window.__paramMeta && window.__paramMeta[p.kod || p.data_field];
  if (meta && meta.typ === 'jakosciowy') {
    var values = [];
    try { values = JSON.parse(meta.opisowe_wartosci || '[]'); } catch (e) { values = []; }
    if (values.length > 0) {
      var cur = p.qualitative_result || '';
      var opts = '<option value=""' + (cur === '' ? ' selected' : '') + '>—</option>';
      values.forEach(function(v) {
        opts += '<option value="' + _esc(v) + '"' + (v === cur ? ' selected' : '') + '>' + _esc(v) + '</option>';
      });
      if (cur && values.indexOf(cur) === -1) {
        opts += '<option value="' + _esc(cur) + '" selected>' + _esc(cur) + ' (historyczna)</option>';
      }
      return '<select data-md="qualitative_result" onchange="onParamFieldChange()" style="flex:1;max-width:240px;">' + opts + '</select>';
    }
  }
  return '<input data-md="qualitative_result" value="' + _esc(p.qualitative_result || '') + '" oninput="onParamFieldChange()" style="flex:1;max-width:240px;" placeholder="—">';
}

function onParamFieldChange() {
  if (_selectedParamIdx == null) return;
  _markParamDirty(_selectedParamIdx);
}

function onGlobalFieldChange(input) {
  // Update live preview
  var key = input.getAttribute('data-md').replace('_global', '');
  var prev = document.querySelector('[data-prev-for="' + key + '_global"]');
  if (prev) prev.innerHTML = _rtHtml(input.value || '');
  input.classList.add('dirty-global');
  _markParamDirty(_selectedParamIdx);
  // Banner update — Task B7
  if (typeof refreshUsageBanner === 'function') refreshUsageBanner();
}

function onOverrideFieldChange(input) {
  var key = input.getAttribute('data-md').replace('_override', '');
  var prev = document.querySelector('[data-prev-for="' + key + '_override"]');
  if (prev) prev.innerHTML = _rtHtml(input.value || '');
  // Toggle reset button visibility
  var resetBtn = document.querySelector('[data-reset-for="' + key + '_override"]');
  if (resetBtn) {
    if (input.value) resetBtn.classList.remove('hidden');
    else resetBtn.classList.add('hidden');
  }
  _markParamDirty(_selectedParamIdx);
}

function resetOverride(field) {
  var inp = document.querySelector('[data-md="' + field + '"]');
  if (!inp) return;
  inp.value = '';
  onOverrideFieldChange(inp);
}

// Toolbar focus tracking — implemented in Task B5
var _focusedTextInput = null;
function updateToolbarState() { /* Task B5 */ }
function tbInsert(kind) { /* Task B5 */ }

// Banner — Task B7
function refreshUsageBanner() { /* Task B7 */ }
```

- [ ] **Step 2: Verify in browser**

Reload, open Parametry tab, click param. Expected: right panel shows two-column editor (Nazwa PL globalne | override, etc.), single-column rows for Wymaganie/Precyzja/Wynik op./Powiąż. Toolbar visible. Reset button (⤺) appears next to override label only when override is set.

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(wzory-cert): two-column dual-field detail panel + reset-to-global (B3)"
```

---

### Task B4: Toolbar formatowania (Buttons → focused input)

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html` (JS — implement `updateToolbarState`, `tbInsert`)

- [ ] **Step 1: Implement toolbar logic**

Replace stub `updateToolbarState` and `tbInsert`:

```javascript
var _NAME_FIELDS = ['name_pl_global','name_pl_override','name_en_global','name_en_override','requirement'];
var _SUB_SUP_FIELDS = ['name_pl_global','name_pl_override','name_en_global','name_en_override']; // not requirement

function updateToolbarState() {
  var toolbar = document.getElementById('wc-md-toolbar');
  if (!toolbar) return;
  var inp = _focusedTextInput;
  var dataMd = inp && inp.getAttribute && inp.getAttribute('data-md');
  toolbar.querySelectorAll('.wc-md-tbtn').forEach(function(btn) {
    var kind = btn.getAttribute('data-tb');
    var allowed = false;
    if (!inp) {
      allowed = false;
    } else if (kind === 'sup' || kind === 'sub' || kind === 'br') {
      allowed = _SUB_SUP_FIELDS.indexOf(dataMd) !== -1;
    } else {
      // Special chars: any text input
      allowed = _NAME_FIELDS.indexOf(dataMd) !== -1;
    }
    btn.disabled = !allowed;
  });
}

function tbInsert(kind) {
  var inp = _focusedTextInput;
  if (!inp) return;
  var ins = '';
  var caretInside = false;
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
  var before = inp.value.slice(0, start);
  var after = inp.value.slice(end);
  inp.value = before + ins + after;

  // Position caret: inside braces for sup/sub, after the inserted char otherwise
  var newPos = start + ins.length;
  if (caretInside) newPos = start + 2; // between { and }
  inp.setSelectionRange(newPos, newPos);
  inp.focus();

  // Trigger input event so previews + dirty tracking fire
  inp.dispatchEvent(new Event('input', { bubbles: true }));
}
```

Also wire up focus/blur tracking in `renderParamDetail`. Already partially in B3 — verify the focus handler at the bottom is wiring `_focusedTextInput`. Add blur handler that **does not** clear `_focusedTextInput` (toolbar stays targeted at last-focused input even after click leaves):

In `renderParamDetail` body, after the focus listeners block:

```javascript
  // Toolbar buttons must not steal focus from input
  detail.querySelectorAll('.wc-md-tbtn').forEach(function(btn) {
    btn.addEventListener('mousedown', function(e) { e.preventDefault(); }); // prevent focus leave
  });
```

- [ ] **Step 2: Verify in browser**

Click in Nazwa PL globalne input. Expected: toolbar buttons enabled (X² X₂ ↲ ≤ ≥ ÷ °). Click X² → `^{}` inserted at cursor, caret between `{` and `}`. Click ÷ → `÷` inserted. Click in Wymaganie input → only `≤ ≥ ÷ °` enabled (X² X₂ ↲ greyed out). Click in Precyzja select → all greyed.

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(wzory-cert): formatting toolbar inserts at focused input (B4)"
```

---

### Task B5: Banner usage-impact (field-specific)

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html` (JS — implement `refreshUsageBanner`)

- [ ] **Step 1: Implement banner logic**

Replace `refreshUsageBanner` stub:

```javascript
var _usageImpactCache = {};  // parametr_id → {cert_products_count, mbr_products_count}

function _fetchUsageImpact(parametr_id) {
  if (_usageImpactCache[parametr_id]) return Promise.resolve(_usageImpactCache[parametr_id]);
  return fetch('/api/parametry/' + parametr_id + '/usage-impact')
    .then(function(r) { return r.json(); })
    .then(function(j) { _usageImpactCache[parametr_id] = j; return j; });
}

function refreshUsageBanner() {
  if (_selectedParamIdx == null) return;
  var p = _currentProduct.parameters[_selectedParamIdx];
  if (!p || !p.parametr_id) {
    var banner0 = document.getElementById('wc-md-banner');
    if (banner0) banner0.classList.add('hidden');
    return;
  }

  // Detect which global fields were modified (compare current input to value-on-load)
  var detail = document.getElementById('wc-md-detail');
  var labelChanged = false, name_en_changed = false, method_changed = false;
  var labelInp = detail.querySelector('[data-md="name_pl_global"]');
  var enInp = detail.querySelector('[data-md="name_en_global"]');
  var methodInp = detail.querySelector('[data-md="method_global"]');
  if (labelInp && labelInp.value !== (p.name_pl_global || '')) labelChanged = true;
  if (enInp && enInp.value !== (p.name_en_global || '')) name_en_changed = true;
  if (methodInp && methodInp.value !== (p.method_global || '')) method_changed = true;

  var banner = document.getElementById('wc-md-banner');
  if (!banner) return;
  if (!labelChanged && !name_en_changed && !method_changed) {
    banner.classList.add('hidden');
    return;
  }

  _fetchUsageImpact(p.parametr_id).then(function(impact) {
    var lines = [];
    var certN = impact.cert_products_count || 0;
    var mbrN = impact.mbr_products_count || 0;
    lines.push('⚠ Edytujesz wartości w <strong>rejestrze</strong> (zmiana wpłynie na inne produkty).');
    lines.push('Świadectwa: <strong>' + certN + ' produkt(ów)</strong>.');
    if (labelChanged) {
      // label = parametry_analityczne.label widoczne w laborant UI / MBR / kalkulator
      lines.push('Również widoczne w: laboratorium, MBR, kalkulator (' + mbrN + ' produkt(ów) z parametrem w MBR).');
    }
    banner.innerHTML = lines.join(' ');
    banner.classList.remove('hidden');
  });
}
```

- [ ] **Step 2: Verify in browser**

Open a param. Edit „Nazwa EN" globalne → banner pojawia się: „Świadectwa: N produkt(ów)" bez „Również widoczne". Cofnij zmianę (Ctrl+Z lub przepisz wartość) → banner znika. Edit „Nazwa PL globalne" → banner pokazuje także „Również widoczne w: laboratorium, MBR, kalkulator".

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(wzory-cert): field-specific usage-impact banner (B5)"
```

---

### Task B6: Save flow — split into two API calls

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html` (JS — `saveProduct`)

- [ ] **Step 1: Find and rewrite `saveProduct`**

Locate existing `saveProduct` function. Rewrite to:

```javascript
function saveProduct() {
  if (!_currentKey) return;
  // Persist current edits before saving
  saveCurrentParamToState();

  var products = _currentProduct.parameters || [];
  // Detect which params have global-field changes vs original DB values.
  // We use "*_global" field changes from initial state — initial copy taken on load.
  var registryUpdates = [];
  products.forEach(function(p) {
    var orig = (_originalParams && _originalParams[p._origIdx]) || null;
    if (!orig || !p.parametr_id) return;
    var diff = {};
    if (p.name_pl_global !== orig.name_pl_global) diff.label = p.name_pl_global;
    if (p.name_en_global !== orig.name_en_global) diff.name_en = p.name_en_global;
    if (p.method_global !== orig.method_global) diff.method_code = p.method_global;
    if (Object.keys(diff).length) {
      registryUpdates.push({ parametr_id: p.parametr_id, diff: diff });
    }
  });

  var status = document.getElementById('wc-save-status');
  status.textContent = 'Zapisuję...';

  // Step 1: parallel registry PUTs
  var registryPromise = registryUpdates.length === 0
    ? Promise.resolve([])
    : Promise.all(registryUpdates.map(function(u) {
        return fetch('/api/parametry/' + u.parametr_id, {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(u.diff),
        }).then(function(r) {
          if (!r.ok) throw new Error('Registry PUT failed for parametr_id=' + u.parametr_id);
          return r.json();
        });
      }));

  registryPromise.then(function() {
    // Step 2: cert config PUT (existing path)
    var payload = _buildCertConfigPayload();
    return fetch('/api/cert/config/product/' + encodeURIComponent(_currentKey), {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    }).then(function(r) { return r.json().then(function(d) { return { status: r.status, data: d }; }); });
  }).then(function(res) {
    if (res.data.ok) {
      var msg = 'Zapisano: ' + registryUpdates.length + ' globalnych, ' +
        'cert config OK';
      status.textContent = msg;
      flash(msg, true);
      _setDirty(false);
      _paramDirty = {};
      _usageImpactCache = {};
      // Reload to refresh state with persisted values
      editProduct(_currentKey);
    } else {
      status.textContent = 'Błąd: ' + (res.data.error || 'zapis nie powiódł się');
      flash(status.textContent, false);
    }
  }).catch(function(err) {
    status.textContent = 'Błąd: ' + err.message;
    flash(status.textContent, false);
  });
}
```

- [ ] **Step 2: Build cert config payload from in-memory state**

Add helper:

```javascript
function _buildCertConfigPayload() {
  var products = _currentProduct.parameters || [];
  return {
    display_name: document.getElementById('ed-dn').value,
    spec_number: document.getElementById('ed-spec').value,
    cas_number: document.getElementById('ed-cas').value,
    expiry_months: parseInt(document.getElementById('ed-exp').value) || 12,
    opinion_pl: document.getElementById('ed-opl').value,
    opinion_en: document.getElementById('ed-oen').value,
    parameters: products.map(function(p, i) {
      return {
        // server expects existing field names — we send overrides as "name_pl/en/method"
        // (NOT *_global). Empty string = NULL on server side per existing semantics.
        id: p.id || p.kod || p.data_field || '',
        data_field: p.kod || p.data_field || '',
        kolejnosc: i,
        name_pl: p.name_pl_override || '',
        name_en: p.name_en_override || '',
        method: p.method_override || '',
        requirement: p.requirement || '',
        format: p.format || '',
        qualitative_result: p.qualitative_result || null,
      };
    }),
    variants: _serializeVariantsForSave(),  // existing function, leave as-is
  };
}
```

- [ ] **Step 3: Snapshot original params on load**

In `editProduct`, after data fetched, before `renderEditor`:

```javascript
    _originalParams = JSON.parse(JSON.stringify(p.parameters || []));
    p.parameters.forEach(function(par, i) { par._origIdx = i; });
```

Add `var _originalParams = [];` at top with other state vars.

- [ ] **Step 4: Verify in browser end-to-end**

1. Open product, Parametry tab, pick a param
2. Edit Nazwa EN globalne → banner pojawia się
3. Edit Wymaganie (per-product) → banner nie pojawia się
4. Klik „Zapisz wszystko" → flash „Zapisano: 1 globalne, cert config OK"
5. Reload → zmiany utrwalone (Nazwa EN globalne ma nową wartość, Wymaganie ma nową wartość)
6. Sprawdź `audit_log` w DB / `/admin/audit`: jeden event `parametr.updated` z diff dla `name_en`

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(wzory-cert): split save — parallel registry PUTs then cert config PUT (B6)"
```

---

### Task B7: + Add parametr modal + binding read-only flow

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html` (HTML modal + JS flow)

- [ ] **Step 1: Add modal HTML**

Insert near other modals (after `wc-settings-modal`):

```html
<!-- ═══ Add Parameter Modal ═══ -->
<div class="wc-modal" id="wc-add-param-modal" onclick="if(event.target===this)closeAddParamModal()">
  <div class="wc-modal-box" style="max-width:440px;height:auto;">
    <div class="wc-modal-head">
      <span style="font-weight:700;">Dodaj parametr do świadectwa</span>
      <button class="wc-modal-close" onclick="closeAddParamModal()">&times;</button>
    </div>
    <div style="padding:16px 20px;">
      <label class="wc-lbl">Wybierz kod parametru z rejestru</label>
      <select class="wc-sel" id="wc-add-param-code" style="width:100%;"></select>
      <div style="font-size:11px;color:var(--text-dim);margin-top:6px;">
        Wartości nazwy PL/EN i metody pochodzą z rejestru. Wymaganie i precyzję ustawisz w edytorze po dodaniu.
      </div>
      <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:18px;">
        <button class="wc-btn wc-btn-o" onclick="closeAddParamModal()">Anuluj</button>
        <button class="wc-btn wc-btn-p" onclick="confirmAddParam()">Dodaj</button>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Add JS for modal flow**

Replace existing `addParameter` (or add new function):

```javascript
function openAddParamModal() {
  var sel = document.getElementById('wc-add-param-code');
  // Filter out kods already in cert (avoid duplicates)
  var taken = (_currentProduct.parameters || []).map(function(p) { return p.kod || p.data_field; });
  var candidates = _availableCodes.filter(function(c) { return taken.indexOf(c.kod) === -1; });
  var html = '<option value="">— wybierz —</option>';
  var inMbr = candidates.filter(function(c) { return c.in_mbr; });
  var notInMbr = candidates.filter(function(c) { return !c.in_mbr; });
  if (inMbr.length) {
    html += '<optgroup label="W MBR (mierzone przez laborantów)">';
    inMbr.forEach(function(c) {
      html += '<option value="' + _esc(c.kod) + '" data-id="' + (c.id || '') + '">● ' + _esc(c.kod) + ' — ' + _esc(c.skrot || c.label) + '</option>';
    });
    html += '</optgroup>';
  }
  if (notInMbr.length) {
    html += '<optgroup label="Poza MBR">';
    notInMbr.forEach(function(c) {
      html += '<option value="' + _esc(c.kod) + '" data-id="' + (c.id || '') + '">○ ' + _esc(c.kod) + ' — ' + _esc(c.skrot || c.label) + '</option>';
    });
    html += '</optgroup>';
  }
  sel.innerHTML = html;
  document.getElementById('wc-add-param-modal').classList.add('show');
}

function closeAddParamModal() {
  document.getElementById('wc-add-param-modal').classList.remove('show');
}

function confirmAddParam() {
  var sel = document.getElementById('wc-add-param-code');
  var kod = sel.value;
  if (!kod) { flash('Wybierz parametr', false); return; }
  var code = _availableCodes.find(function(c) { return c.kod === kod; });
  if (!code) return;
  var newParam = {
    id: kod,
    data_field: kod,
    kod: kod,
    parametr_id: code.id,
    name_pl_global: code.label || '',
    name_en_global: code.name_en || '',
    method_global: code.method_code || '',
    name_pl_override: null,
    name_en_override: null,
    method_override: null,
    requirement: '',
    format: String(code.precision || ''),
    qualitative_result: null,
    _origIdx: _currentProduct.parameters.length,
  };
  _currentProduct.parameters.push(newParam);
  _originalParams = _originalParams || [];
  _originalParams.push(JSON.parse(JSON.stringify(newParam)));
  _selectedParamIdx = _currentProduct.parameters.length - 1;
  _markParamDirty(_selectedParamIdx);
  closeAddParamModal();
  renderParamList();
  renderParamDetail();
}

function removeSelectedParam() {
  if (_selectedParamIdx == null) return;
  if (!confirm('Usunąć parametr „' + (_currentProduct.parameters[_selectedParamIdx].kod || '') + '"?')) return;
  var pid = _currentProduct.parameters[_selectedParamIdx].id;
  _currentProduct.parameters.splice(_selectedParamIdx, 1);
  // Also scrub from variants' remove_parameters (preserve existing logic)
  if (typeof saveCurrentVariantToData === 'function') saveCurrentVariantToData();
  if (Array.isArray(_variantsData)) {
    _variantsData.forEach(function(v) {
      var ov = v.overrides = v.overrides || {};
      if (Array.isArray(ov.remove_parameters) && ov.remove_parameters.indexOf(pid) !== -1) {
        ov.remove_parameters = ov.remove_parameters.filter(function(x) { return x !== pid; });
      }
    });
  }
  _selectedParamIdx = null;
  _setDirty(true);
  renderParamList();
  renderParamDetail();
}
```

- [ ] **Step 3: Verify in browser**

Klik „+ Dodaj parametr" → modal z dropdown → wybierz kod → klik Dodaj. Expected: nowy parametr w lewym liście, automatycznie zaznaczony, prawy panel pokazuje editor z wypełnionymi wartościami globalnymi i pustymi override-ami. Pole „Powiąż z pomiarem" disabled (nie można zmienić). Save Wszystko → zapisuje (cert config tworzy nowy wiersz w `parametry_cert`).

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(wzory-cert): + Dodaj parametr modal + binding read-only after creation (B7)"
```

---

### Task B8: Drag-and-drop reorder w lewym panelu

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html` (JS — `initParamListDragAndDrop`)

- [ ] **Step 1: Implement drag handlers**

Replace stub `initParamListDragAndDrop`:

```javascript
var _dragItem = null;
function initParamListDragAndDrop() {
  document.querySelectorAll('#wc-md-list-body .wc-md-item').forEach(function(item) {
    item.addEventListener('dragstart', function(e) {
      _dragItem = this;
      this.style.opacity = '0.4';
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', '');
    });
    item.addEventListener('dragover', function(e) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      if (_dragItem !== this) {
        var rect = this.getBoundingClientRect();
        var midY = rect.top + rect.height / 2;
        if (e.clientY < midY) this.style.borderTop = '2px solid var(--teal)';
        else this.style.borderBottom = '2px solid var(--teal)';
      }
    });
    item.addEventListener('dragleave', function() {
      this.style.borderTop = ''; this.style.borderBottom = '';
    });
    item.addEventListener('drop', function(e) {
      e.preventDefault();
      this.style.borderTop = ''; this.style.borderBottom = '';
      if (_dragItem === this) return;

      var fromIdx = parseInt(_dragItem.getAttribute('data-idx'));
      var toIdx = parseInt(this.getAttribute('data-idx'));
      var rect = this.getBoundingClientRect();
      var midY = rect.top + rect.height / 2;
      var insertBefore = e.clientY < midY;

      // Save current edits before reorder
      saveCurrentParamToState();

      var arr = _currentProduct.parameters;
      var moved = arr.splice(fromIdx, 1)[0];
      var newIdx = insertBefore ? toIdx : toIdx + 1;
      if (fromIdx < newIdx) newIdx--;
      arr.splice(newIdx, 0, moved);

      // Update _origIdx tracking — preserve original→new mapping
      // (registryUpdates depend on _origIdx, so don't reassign)
      // Just update selection
      if (_selectedParamIdx === fromIdx) _selectedParamIdx = newIdx;
      else if (_selectedParamIdx > fromIdx && _selectedParamIdx <= newIdx) _selectedParamIdx--;
      else if (_selectedParamIdx < fromIdx && _selectedParamIdx >= newIdx) _selectedParamIdx++;

      _setDirty(true);
      renderParamList();
    });
    item.addEventListener('dragend', function() {
      this.style.opacity = '';
    });
  });
}
```

- [ ] **Step 2: Verify in browser**

Drag a param item up/down in left list. Expected: list reorders, active selection follows the dragged param if it was selected. Save → kolejność persisted.

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(wzory-cert): drag-and-drop reorder in left list (B8)"
```

---

### Task B9: Cleanup — remove old tabular code

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html`

- [ ] **Step 1: Remove dead code**

Delete the following functions/blocks (no longer used):
- `renderParamsTable` (replaced by `renderParamList`/`renderParamDetail`)
- `_paramRow` (replaced by inline HTML in renderParamDetail)
- `addParameter` (replaced by `openAddParamModal`/`confirmAddParam`)
- `removeBaseParam` (replaced by `removeSelectedParam`)
- `_dragRow` and the original `initDragAndDrop` (replaced by `initParamListDragAndDrop`)
- `autoId` and `_isAutoValue` and `onCodeSelect` (no longer needed — binding is read-only post-create, name fields don't auto-fill)
- Old hint paragraph: `<p class="wc-hint">Indeksy w nazwach: ... ^{...}` — replaced by toolbar
- The old Parametry HTML table (already replaced in B1)

- [ ] **Step 2: Verify in browser**

Full smoke test:
1. Edit existing product → list renders, edit, save, all works
2. Add new param → modal, save, persists
3. Remove param → confirm, save, persists
4. Reorder → save, persists
5. Edit globalne → banner, save, audyt event

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "refactor(wzory-cert): remove dead tabular code from old Parametry tab (B9)"
```

---

## Phase C — Frontend Warianty tab

### Task C1: Apply master-detail to Warianty tab

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html` (HTML — replace Warianty params table; JS — adapt)

- [ ] **Step 1: Replace Warianty params table HTML**

Find HTML block (around lines 297-316) for variants param table. Replace with master-detail (parallel structure to Parametry tab):

```html
<div class="wc-md" id="wc-var-md" style="margin-top:14px;">
  <div class="wc-md-list">
    <div class="wc-md-search">
      <input id="wc-var-md-filter" type="text" placeholder="Filtruj parametry wariantu..." oninput="filterVariantParamList(this.value)">
    </div>
    <div class="wc-md-list-body" id="wc-var-md-list-body"></div>
    <div class="wc-md-add" onclick="openAddVariantParamModal()">+ Dodaj parametr wariantu</div>
  </div>
  <div class="wc-md-detail" id="wc-var-md-detail">
    <div class="wc-md-detail-empty">Wybierz parametr wariantu</div>
  </div>
</div>
```

- [ ] **Step 2: Add JS adapters**

Add (parallel to Parametry tab functions but for variants):

```javascript
var _selectedVarParamIdx = null;
var _varParamFilter = '';
var _varParamDirty = {};

function renderVariantParamList() {
  if (typeof _currentVarIdx !== 'number' || !_variantsData[_currentVarIdx]) return;
  var aps = _variantsData[_currentVarIdx].add_parameters || [];
  var body = document.getElementById('wc-var-md-list-body');
  var filter = _varParamFilter.toLowerCase();
  var html = '';
  aps.forEach(function(ap, i) {
    var name = ap.name_pl_override || ap.name_pl_global || ap.name_pl || '';
    var kod = ap.kod || ap.data_field || '';
    if (filter) {
      var hay = (name + ' ' + kod).toLowerCase();
      if (hay.indexOf(filter) === -1) return;
    }
    var activeCls = (i === _selectedVarParamIdx) ? ' active' : '';
    var dirtyCls = (_varParamDirty[i]) ? ' dirty' : '';
    html += '<div class="wc-md-item' + activeCls + dirtyCls + '" data-idx="' + i + '" onclick="selectVariantParam(' + i + ')" draggable="true">' +
      '<span class="wc-md-drag">&#10303;</span>' +
      '<span class="wc-md-item-name">' + _rtHtml(name) + '</span>' +
      '<span class="wc-md-item-bind">' + _esc(kod) + '</span>' +
    '</div>';
  });
  if (!html) html = '<div style="padding:14px;color:var(--text-dim);font-size:11px;text-align:center;">' +
    (filter ? 'Brak wyników filtra.' : 'Brak parametrów. Klik + Dodaj parametr wariantu.') + '</div>';
  body.innerHTML = html;
}

function filterVariantParamList(v) { _varParamFilter = v || ''; renderVariantParamList(); }

function selectVariantParam(i) {
  if (_selectedVarParamIdx !== null) saveCurrentVariantParamToState();
  _selectedVarParamIdx = i;
  renderVariantParamList();
  renderVariantParamDetail();
}

function saveCurrentVariantParamToState() {
  if (_selectedVarParamIdx == null) return;
  var v = _variantsData[_currentVarIdx];
  if (!v || !v.add_parameters || !v.add_parameters[_selectedVarParamIdx]) return;
  var ap = v.add_parameters[_selectedVarParamIdx];
  var detail = document.getElementById('wc-var-md-detail');
  if (!detail) return;
  function _val(s) { var e = detail.querySelector(s); return e ? e.value : ''; }
  function _val_or_null(s) { var v = _val(s); return v === '' ? null : v; }
  ap.name_pl_global = _val('[data-md="name_pl_global"]');
  ap.name_en_global = _val('[data-md="name_en_global"]');
  ap.method_global = _val('[data-md="method_global"]');
  ap.name_pl_override = _val_or_null('[data-md="name_pl_override"]');
  ap.name_en_override = _val_or_null('[data-md="name_en_override"]');
  ap.method_override = _val_or_null('[data-md="method_override"]');
  ap.requirement = _val('[data-md="requirement"]');
  ap.format = _val('[data-md="format"]');
  ap.qualitative_result = _val_or_null('[data-md="qualitative_result"]');
}

function renderVariantParamDetail() {
  // Same as renderParamDetail but operates on variant.add_parameters
  // and writes to wc-var-md-detail.
  // Implementation note: largely duplicates renderParamDetail — extract
  // shared `_renderDualDetail(targetEl, paramObj, mode)` if duplication
  // becomes painful. For now, keep it inline parallel for clarity.
  var detail = document.getElementById('wc-var-md-detail');
  if (_selectedVarParamIdx == null) {
    detail.innerHTML = '<div class="wc-md-detail-empty">Wybierz parametr wariantu</div>';
    return;
  }
  var v = _variantsData[_currentVarIdx];
  var ap = v.add_parameters[_selectedVarParamIdx];
  if (!ap) {
    detail.innerHTML = '<div class="wc-md-detail-empty">Brak parametru wariantu.</div>';
    return;
  }
  var name_pl_eff = ap.name_pl_override || ap.name_pl_global || '';
  var kod = ap.kod || ap.data_field || '';
  var bindingDisabled = (ap.id || ap.parametr_id) ? 'disabled' : '';

  detail.innerHTML =
    '<div class="wc-md-detail-head">' +
      '<div class="wc-md-detail-title">' + _rtHtml(name_pl_eff) + '</div>' +
      '<span class="wc-md-detail-bind">' + _esc(kod) + '</span>' +
      '<button class="wc-md-detail-del" onclick="removeSelectedVariantParam()">Usuń parametr</button>' +
    '</div>' +
    '<div class="wc-md-banner hidden" id="wc-var-md-banner"></div>' +
    // Toolbar — share with main one if possible; for now duplicate for variant detail
    '<div class="wc-md-toolbar" id="wc-var-md-toolbar">' +
      '<span class="wc-md-toolbar-label">Wstaw do focused pola:</span>' +
      '<button class="wc-md-tbtn" data-tb="sup" onclick="tbInsert(\'sup\')" title="^{}">X<sup>²</sup></button>' +
      '<button class="wc-md-tbtn" data-tb="sub" onclick="tbInsert(\'sub\')" title="_{}">X<sub>₂</sub></button>' +
      '<button class="wc-md-tbtn" data-tb="br" onclick="tbInsert(\'br\')" title="|">↲</button>' +
      '<span style="width:1px;height:14px;background:var(--border);margin:0 4px;"></span>' +
      '<button class="wc-md-tbtn" data-tb="leq" onclick="tbInsert(\'leq\')" title="≤">≤</button>' +
      '<button class="wc-md-tbtn" data-tb="geq" onclick="tbInsert(\'geq\')" title="≥">≥</button>' +
      '<button class="wc-md-tbtn" data-tb="div" onclick="tbInsert(\'div\')" title="÷">÷</button>' +
      '<button class="wc-md-tbtn" data-tb="deg" onclick="tbInsert(\'deg\')" title="°">°</button>' +
    '</div>' +
    '<div class="wc-md-dual-header">' +
      '<div>Globalne (rejestr — dotyczy wszystkich produktów)</div>' +
      '<div>Per wariant (puste = dziedzicz globalne)</div>' +
    '</div>' +
    _dualRow('Nazwa PL', 'name_pl', ap.name_pl_global || '', ap.name_pl_override) +
    _dualRow('Nazwa EN', 'name_en', ap.name_en_global || '', ap.name_en_override) +
    _dualRow('Metoda',  'method',  ap.method_global  || '', ap.method_override) +
    '<div class="wc-md-single-section">' +
      '<div class="wc-md-single-row"><label>Wymaganie</label><div><input data-md="requirement" value="' + _esc(ap.requirement || '') + '" oninput="onVarParamFieldChange()" style="flex:1;"></div></div>' +
      '<div class="wc-md-single-row"><label>Precyzja</label><div><select data-md="format" onchange="onVarParamFieldChange()" style="width:120px;">' + _fmtOptions(ap.format) + '</select></div></div>' +
      '<div class="wc-md-single-row"><label>Wynik opisowy</label><div>' + _qualResultInputMd(ap) + '</div></div>' +
      '<div class="wc-md-single-row"><label>Powiąż z pomiarem</label><div><select data-md="data_field" onchange="onVarParamFieldChange()" ' + bindingDisabled + ' style="flex:1;max-width:320px;">' + _codeOptions(ap.data_field || ap.kod) + '</select>' + (bindingDisabled ? '<span style="font-size:10px;color:var(--text-dim);margin-left:8px;">read-only po utworzeniu</span>' : '') + '</div></div>' +
    '</div>';

  detail.querySelectorAll('input[data-md]').forEach(function(inp) {
    inp.addEventListener('focus', function() { _focusedTextInput = inp; updateToolbarState(); });
  });
  detail.querySelectorAll('.wc-md-tbtn').forEach(function(btn) {
    btn.addEventListener('mousedown', function(e) { e.preventDefault(); });
  });
  updateToolbarState();
}

function onVarParamFieldChange() { if (_selectedVarParamIdx != null) { _varParamDirty[_selectedVarParamIdx] = true; renderVariantParamList(); _setDirty(true); } }

function removeSelectedVariantParam() {
  if (_selectedVarParamIdx == null) return;
  var v = _variantsData[_currentVarIdx];
  if (!confirm('Usunąć parametr „' + (v.add_parameters[_selectedVarParamIdx].kod || '') + '" z wariantu?')) return;
  v.add_parameters.splice(_selectedVarParamIdx, 1);
  _selectedVarParamIdx = null;
  _setDirty(true);
  renderVariantParamList();
  renderVariantParamDetail();
}

// Adapt openAddVariantParamModal — use same Add Param modal but flag for variant context
var _addParamMode = 'base';  // 'base' | 'variant'

function openAddVariantParamModal() { _addParamMode = 'variant'; openAddParamModal(); }

// Modify confirmAddParam to dispatch by mode
// (replace the version from Task B7):
```

Modify `confirmAddParam` from Task B7 to handle both modes:

```javascript
function confirmAddParam() {
  var sel = document.getElementById('wc-add-param-code');
  var kod = sel.value;
  if (!kod) { flash('Wybierz parametr', false); return; }
  var code = _availableCodes.find(function(c) { return c.kod === kod; });
  if (!code) return;
  var newParam = {
    id: kod, data_field: kod, kod: kod, parametr_id: code.id,
    name_pl_global: code.label || '', name_en_global: code.name_en || '', method_global: code.method_code || '',
    name_pl_override: null, name_en_override: null, method_override: null,
    requirement: '', format: String(code.precision || ''), qualitative_result: null,
  };
  if (_addParamMode === 'variant') {
    var v = _variantsData[_currentVarIdx];
    v.add_parameters = v.add_parameters || [];
    v.add_parameters.push(newParam);
    _selectedVarParamIdx = v.add_parameters.length - 1;
    _varParamDirty[_selectedVarParamIdx] = true;
    renderVariantParamList();
    renderVariantParamDetail();
  } else {
    newParam._origIdx = _currentProduct.parameters.length;
    _currentProduct.parameters.push(newParam);
    _originalParams.push(JSON.parse(JSON.stringify(newParam)));
    _selectedParamIdx = _currentProduct.parameters.length - 1;
    _markParamDirty(_selectedParamIdx);
    renderParamList();
    renderParamDetail();
  }
  _addParamMode = 'base';
  _setDirty(true);
  closeAddParamModal();
}
```

- [ ] **Step 3: Wire up variant tab to render master-detail when variant selected**

Find function `showVariant` (called when `_currentVarIdx` changes — it renders variant params). Replace its add_parameters rendering with:

```javascript
  // Reset and render variant param master-detail
  _selectedVarParamIdx = null;
  _varParamDirty = {};
  _varParamFilter = '';
  renderVariantParamList();
  renderVariantParamDetail();
```

(Existing `wc-var-params` table-based rendering becomes dead code — remove the `<tbody id="wc-var-params">` and its rendering function.)

- [ ] **Step 4: Verify in browser**

Open product, switch to „Warianty" tab. Pick variant. Expected: master-detail layout, left list of variant add_params, right detail editor with two-column layout. Add/edit/remove variant param → save → reload → persisted.

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(wzory-cert): master-detail layout for Warianty tab params (C1)"
```

---

## Phase D — Migracja produkcyjna

### Task D1: Migration script — TDD with normalized comparison

**Files:**
- Create: `scripts/migrate_cert_override_cleanup.py`
- Create: `tests/test_migrate_cert_override_cleanup.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_migrate_cert_override_cleanup.py
"""Migration script: NULL out parametry_cert overrides that equal registry value (after whitespace normalization)."""
import sqlite3
import pytest

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
        "INSERT INTO parametry_analityczne (id, kod, label, typ, name_en, method_code) "
        "VALUES (1, 'nd20', 'Wsp. załamania', 'bezposredni', 'Refractive index', 'PN-EN ISO 5661')"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('A', 'A')")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('B', 'B')")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('C', 'C')")
    # A: exact match → all 3 fields nulled
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, name_en, method, variant_id) "
        "VALUES ('A', 1, 0, 'Wsp. załamania', 'Refractive index', 'PN-EN ISO 5661', NULL)"
    )
    # B: trailing/inner whitespace → still matches after normalization
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, name_en, method, variant_id) "
        "VALUES ('B', 1, 0, '  Wsp.   załamania  ', 'Refractive  index', '  PN-EN ISO 5661 ', NULL)"
    )
    # C: real override (different value) → preserved
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, name_en, method, variant_id) "
        "VALUES ('C', 1, 0, 'Wsp. załamania n_{D}^{20}', 'Refr. idx (custom)', 'Internal proc 12', NULL)"
    )
    db.commit()


def test_migration_nulls_exact_match(db):
    _seed(db)
    from scripts.migrate_cert_override_cleanup import run_migration
    stats = run_migration(db)
    row = db.execute("SELECT name_pl, name_en, method FROM parametry_cert WHERE produkt='A'").fetchone()
    assert row["name_pl"] is None
    assert row["name_en"] is None
    assert row["method"] is None


def test_migration_nulls_after_whitespace_normalization(db):
    _seed(db)
    from scripts.migrate_cert_override_cleanup import run_migration
    stats = run_migration(db)
    row = db.execute("SELECT name_pl, name_en, method FROM parametry_cert WHERE produkt='B'").fetchone()
    assert row["name_pl"] is None
    assert row["name_en"] is None
    assert row["method"] is None


def test_migration_preserves_real_overrides(db):
    _seed(db)
    from scripts.migrate_cert_override_cleanup import run_migration
    stats = run_migration(db)
    row = db.execute("SELECT name_pl, name_en, method FROM parametry_cert WHERE produkt='C'").fetchone()
    assert row["name_pl"] == "Wsp. załamania n_{D}^{20}"
    assert row["name_en"] == "Refr. idx (custom)"
    assert row["method"] == "Internal proc 12"


def test_migration_returns_stats(db):
    _seed(db)
    from scripts.migrate_cert_override_cleanup import run_migration
    stats = run_migration(db)
    # 6 nullings: A×3 + B×3
    assert stats["nulled_total"] == 6
    assert stats["preserved_total"] == 3  # C×3
    assert stats["rows_processed"] == 3


def test_migration_idempotent(db):
    _seed(db)
    from scripts.migrate_cert_override_cleanup import run_migration
    stats1 = run_migration(db)
    stats2 = run_migration(db)
    # Second run nullifies nothing extra
    assert stats2["nulled_total"] == 0
    assert stats2["preserved_total"] == 3


def test_migration_handles_variant_rows(db):
    _seed(db)
    db.execute(
        "INSERT INTO cert_variants (id, produkt, variant_id, label, flags, kolejnosc) "
        "VALUES (10, 'A', 'lv', 'LV', '[]', 0)"
    )
    db.execute(
        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, name_pl, name_en, method, variant_id) "
        "VALUES ('A', 1, 0, 'Wsp. załamania', NULL, NULL, 10)"
    )
    db.commit()
    from scripts.migrate_cert_override_cleanup import run_migration
    stats = run_migration(db)
    row = db.execute("SELECT name_pl FROM parametry_cert WHERE variant_id=10").fetchone()
    assert row["name_pl"] is None  # variant override matched registry → NULL
    assert stats["rows_processed"] == 4  # 3 base + 1 variant
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_migrate_cert_override_cleanup.py -v
```

Expected: 6 failures with `ImportError: scripts.migrate_cert_override_cleanup`.

- [ ] **Step 3: Write the migration script**

```python
# scripts/migrate_cert_override_cleanup.py
"""Migration: NULL out parametry_cert.name_pl/name_en/method overrides that equal
the registry value (parametry_analityczne.label/name_en/method_code) after whitespace
normalization.

After this migration, cert UI semantics: empty override = inherit from registry.
Idempotent — safe to re-run.

Usage:
    python -m scripts.migrate_cert_override_cleanup            # run on default DB
    python -m scripts.migrate_cert_override_cleanup --dry-run  # report only

Logs detailed report to stdout: how many rows nulled per field, which products kept
explicit overrides.
"""

import argparse
import re
import sqlite3
import sys
from pathlib import Path

_WS_RE = re.compile(r"\s+")


def _norm(s):
    """Whitespace normalize: strip + collapse internal runs to single space.
    Case-sensitive (case has meaning in this domain — e.g. 'PN-EN' vs 'pn-en')."""
    if s is None:
        return None
    return _WS_RE.sub(" ", s.strip())


def _eq_norm(a, b):
    return _norm(a) == _norm(b)


def run_migration(db, dry_run=False):
    """Walk parametry_cert; for each row, NULL the override fields that match the
    registry value (after whitespace normalization).

    Args:
        db: sqlite3.Connection (caller commits unless dry_run).
        dry_run: if True, count what would change but don't UPDATE.

    Returns:
        Stats dict: {rows_processed, nulled_total, preserved_total,
                     nulled_per_field: {name_pl, name_en, method},
                     preserved_examples: [{produkt, kod, field, override_value}]}
    """
    rows = db.execute("""
        SELECT pc.rowid AS rid, pc.produkt, pc.variant_id, pc.parametr_id,
               pc.name_pl, pc.name_en, pc.method,
               pa.kod, pa.label, pa.name_en AS pa_name_en, pa.method_code
        FROM parametry_cert pc
        JOIN parametry_analityczne pa ON pa.id = pc.parametr_id
    """).fetchall()

    nulled = {"name_pl": 0, "name_en": 0, "method": 0}
    preserved_examples = []
    nulled_total = 0
    preserved_total = 0

    for r in rows:
        updates = {}
        for cert_field, registry_field, registry_val in [
            ("name_pl", "label", r["label"]),
            ("name_en", "pa_name_en", r["pa_name_en"]),
            ("method", "method_code", r["method_code"]),
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
                if len(preserved_examples) < 50:
                    preserved_examples.append({
                        "produkt": r["produkt"],
                        "variant_id": r["variant_id"],
                        "kod": r["kod"],
                        "field": cert_field,
                        "override_value": override,
                        "registry_value": registry_val,
                    })

        if updates and not dry_run:
            sets = ", ".join(f"{k}=NULL" for k in updates)
            db.execute(f"UPDATE parametry_cert SET {sets} WHERE rowid=?", (r["rid"],))

    if not dry_run:
        db.commit()

    return {
        "rows_processed": len(rows),
        "nulled_total": nulled_total,
        "preserved_total": preserved_total,
        "nulled_per_field": nulled,
        "preserved_examples": preserved_examples,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/batch_db.sqlite", help="Path to SQLite DB")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: DB not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    stats = run_migration(conn, dry_run=args.dry_run)

    print("=" * 60)
    print(f"Cert override cleanup — {'DRY RUN' if args.dry_run else 'EXECUTED'}")
    print("=" * 60)
    print(f"Rows processed:       {stats['rows_processed']}")
    print(f"Override fields nulled: {stats['nulled_total']}")
    print(f"  - name_pl:  {stats['nulled_per_field']['name_pl']}")
    print(f"  - name_en:  {stats['nulled_per_field']['name_en']}")
    print(f"  - method:   {stats['nulled_per_field']['method']}")
    print(f"Real overrides preserved: {stats['preserved_total']}")
    if stats['preserved_examples']:
        print()
        print("Sample preserved overrides (first 50):")
        for ex in stats['preserved_examples']:
            v = " (variant)" if ex.get("variant_id") else ""
            print(f"  {ex['produkt']}{v}/{ex['kod']}/{ex['field']}: ")
            print(f"    override:  {ex['override_value']!r}")
            print(f"    registry:  {ex['registry_value']!r}")
    conn.close()


if __name__ == "__main__":
    main()
```

Create `scripts/__init__.py` if it doesn't exist:

```bash
touch scripts/__init__.py
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_migrate_cert_override_cleanup.py -v
```

Expected: 6 passing.

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_cert_override_cleanup.py scripts/__init__.py tests/test_migrate_cert_override_cleanup.py
git commit -m "feat(scripts): cert override cleanup migration with whitespace normalization"
```

---

### Task D2: Migration runbook + dry-run on dev DB

**Files:**
- Create: `docs/migrations/2026-04-cert-override-cleanup.md`

- [ ] **Step 1: Write runbook**

```markdown
# Cert Override Cleanup Migration

**Date:** 2026-04-28
**Spec:** docs/superpowers/specs/2026-04-28-cert-editor-redesign-design.md (Section 6)
**Script:** scripts/migrate_cert_override_cleanup.py

## What it does

After the cert editor redesign, `parametry_cert.name_pl/name_en/method` columns
hold per-product overrides. Many existing rows have these columns filled with
values copied from `parametry_analityczne` (label/name_en/method_code) at
creation time — these are "pseudo-overrides" that prevent registry edits from
propagating.

This migration NULLs out `parametry_cert.name_pl/name_en/method` rows whose
value equals the registry value after whitespace normalization (strip + collapse
internal runs of whitespace; case-sensitive).

Idempotent. Safe to run in production.

## Pre-flight

1. Backup DB:
   ```bash
   cp data/batch_db.sqlite data/batch_db.sqlite.bak.$(date +%Y%m%d-%H%M)
   ```

2. Run dry-run to inspect:
   ```bash
   python -m scripts.migrate_cert_override_cleanup --dry-run
   ```

   Read the output. Look at "Sample preserved overrides" — these are rows that
   will keep their current value (real overrides). Confirm they look right.

## Execute

```bash
python -m scripts.migrate_cert_override_cleanup
```

Expected output (sample):

```
Rows processed:       347
Override fields nulled: 612
  - name_pl:  211
  - name_en:  201
  - method:   200
Real overrides preserved: 89
```

## Verify

After migration, sanity-check a few products in the cert editor:

1. Open `/admin/wzory-cert`, pick any product
2. Klik „Parametry świadectwa"
3. Sprawdź że pola w prawej kolumnie (override) są puste dla większości
   parametrów — wartości dziedziczone z lewej kolumny (rejestr)
4. Wygeneruj testowe świadectwo z dowolnej szarży — PDF powinien wyglądać
   identycznie jak przed migracją
5. Edytuj `parametry_analityczne.label` przez `/admin/parametry` →
   wygeneruj świadectwo → nowa wartość propagowała się

## Rollback

If something goes wrong:

```bash
cp data/batch_db.sqlite.bak.<TIMESTAMP> data/batch_db.sqlite
```
```

- [ ] **Step 2: Smoke test on dev DB copy**

```bash
cp data/batch_db.sqlite /tmp/batch_db.test.sqlite
python -m scripts.migrate_cert_override_cleanup --db /tmp/batch_db.test.sqlite --dry-run
```

Confirm output is sensible (preserved sample isn't empty if you have real overrides). Then run for real:

```bash
python -m scripts.migrate_cert_override_cleanup --db /tmp/batch_db.test.sqlite
```

Open the test DB in cert editor (point dev server at it temporarily), verify behavior.

- [ ] **Step 3: Commit**

```bash
git add docs/migrations/2026-04-cert-override-cleanup.md
git commit -m "docs(migrations): runbook for cert override cleanup"
```

- [ ] **Step 4: Production deploy (separate operation, owner-controlled)**

This is NOT a code-task — it's the actual production migration:

1. SSH to production
2. Stop service: `sudo systemctl stop lims`
3. Backup DB (per runbook)
4. Run dry-run, inspect
5. Run migration
6. Restart service: `sudo systemctl start lims`
7. Smoke test in browser

Document the run in audit (manual entry or via the migration audit event):

```bash
# Optional — emit an audit event for the migration
python -c "
from mbr.db import db_session
from mbr.shared.audit import log_event, EVENT_SYSTEM_MIGRATION_APPLIED, actors_system
with db_session() as db:
    log_event(EVENT_SYSTEM_MIGRATION_APPLIED, payload={'name': 'cert_override_cleanup_2026_04_28'}, actors=actors_system(), db=db)
    db.commit()
"
```

---

## Self-Review Notes

**Spec coverage:**
- Section 1 (semantics) → A3, A4 (registry + cert config dual-field returns)
- Section 2 (master-detail layout) → B1, B2, B3
- Section 3 (toolbar) → B4
- Section 4 (save flow split) → B6
- Section 5 (warianty same UI) → C1
- Section 6 (migration) → D1, D2
- Section 7 (backend endpoints) → A1, A2, A3, A4
- Section 8 (add param + binding read-only) → B7
- Section 9 (search/filter, drag, dirty state) → B2 (filter), B8 (drag), B7+B6 (dirty preserved across switches via JS state)
- Section 10 (audit) → A1
- Section 11 (out of scope) → not modified

**Type consistency:** function names match across tasks — `renderParamList` / `renderParamDetail` / `selectParam` consistent in B2-B9; variant equivalents `renderVariantParamList` / `renderVariantParamDetail` / `selectVariantParam` consistent in C1.

**Backward compat:** `get_cert_params` keeps legacy fields (`name_pl`, `name_en`, `method`) — cert generator (`mbr/certs/generator.py`) untouched.
