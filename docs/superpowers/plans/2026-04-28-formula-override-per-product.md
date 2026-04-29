# Formula Override Per Product Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dodać UI w Rejestrze (sekcja „Override per produkt" w detail panelu obliczeniowego/średnia parametru) + endpoint backend do nadpisywania `parametry_etapy.formula` per produkt. Główny use case: Cheminox_K + Cheminox_K35 z formułą `SA = SM` (bez NaCl).

**Architecture:** Schema już wspiera per-binding override przez `parametry_etapy.formula` (`get_parametry_for_kontekst:101-103` preferuje binding-formula nad globalną). Nowy endpoint `PUT /api/parametry/<id>/formula-override` ustawia/czyści formułę + rebuilds `mbr_templates.parametry_lab`. UI dodany w `_rejRenderTypConfig` w `mbr/templates/parametry_editor.html`. `sa_bias` (separate column) zostaje nietknięty — backward compat.

**Tech Stack:** Flask + SQLite (raw sqlite3); Jinja2 + vanilla JS; pytest TDD na backend; manual browser verification dla frontend.

**Spec:** `docs/superpowers/specs/2026-04-28-formula-override-per-product-design.md` (przeczytaj przed startem).

---

## File Structure

**Backend (Phase A):**
- Modify `mbr/parametry/routes.py`:
  - Nowy `api_parametry_formula_override` (PUT `/api/parametry/<id>/formula-override`)
  - Rozszerzenie `api_parametry_usage_impact` o `formula_override` w `mbr_products[]`
- Test: `tests/test_parametry_formula_override.py` (nowy, ~7 testów)
- Test: `tests/test_parametry_usage_impact_lists.py` (rozszerzenie 1 testu)

**Frontend (Phase B):**
- Modify `mbr/templates/parametry_editor.html`:
  - Nowa funkcja `_rejRenderFormulaOverrides(p)` — render sub-sekcji
  - Modyfikacja `_rejRenderTypConfig` — wywołanie `_rejRenderFormulaOverrides` dla obliczeniowy/srednia
  - Nowe funkcje: `rejSetFormulaOverride`, `rejClearFormulaOverride`, `rejAddFormulaOverrideRow`, `_rejFlashOverride`

---

## Phase A — Backend (TDD)

### Task A1: Endpoint PUT /api/parametry/<id>/formula-override

**Files:**
- Modify: `mbr/parametry/routes.py` (add new endpoint after `api_parametry_sa_bias`)
- Test: `tests/test_parametry_formula_override.py` (create)

- [ ] **Step 1: Write failing tests**

Create `tests/test_parametry_formula_override.py`:

```python
"""PUT /api/parametry/<id>/formula-override — set/clear per-binding formula override."""
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
        "INSERT INTO parametry_analityczne (id, kod, label, typ, formula) "
        "VALUES (1, 'sa', 'Substancja aktywna', 'obliczeniowy', 'sm - nacl - sa_bias')"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('Cheminox_K', 'Cheminox K')")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('Other', 'Other')")
    # Cheminox_K has SA binding in analiza_koncowa (no formula override yet)
    db.execute(
        "INSERT INTO parametry_etapy (id, parametr_id, produkt, kontekst, kolejnosc, sa_bias) "
        "VALUES (10, 1, 'Cheminox_K', 'analiza_koncowa', 0, 0.6)"
    )
    # Other product also has SA binding but in different kontekst (sulfonowanie)
    db.execute(
        "INSERT INTO parametry_etapy (id, parametr_id, produkt, kontekst, kolejnosc) "
        "VALUES (11, 1, 'Other', 'sulfonowanie', 0)"
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


def test_set_formula_override(monkeypatch, db):
    """PUT formula → updates parametry_etapy.formula in correct binding."""
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1/formula-override", json={"produkt": "Cheminox_K", "formula": "sm"})
    assert rv.status_code == 200, rv.get_json()
    j = rv.get_json()
    assert j["ok"] is True
    assert j["produkt"] == "Cheminox_K"
    assert j["formula"] == "sm"

    row = db.execute("SELECT formula FROM parametry_etapy WHERE id=10").fetchone()
    assert row["formula"] == "sm"


def test_clear_formula_override(monkeypatch, db):
    """PUT formula=null → SET NULL."""
    _seed(db)
    db.execute("UPDATE parametry_etapy SET formula='sm' WHERE id=10")
    db.commit()
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1/formula-override", json={"produkt": "Cheminox_K", "formula": None})
    assert rv.status_code == 200

    row = db.execute("SELECT formula FROM parametry_etapy WHERE id=10").fetchone()
    assert row["formula"] is None


def test_clear_formula_override_via_empty_string(monkeypatch, db):
    """PUT formula='' (or whitespace) → treated as null → SET NULL."""
    _seed(db)
    db.execute("UPDATE parametry_etapy SET formula='sm' WHERE id=10")
    db.commit()
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1/formula-override", json={"produkt": "Cheminox_K", "formula": "   "})
    assert rv.status_code == 200

    row = db.execute("SELECT formula FROM parametry_etapy WHERE id=10").fetchone()
    assert row["formula"] is None


def test_404_when_no_binding(monkeypatch, db):
    """PUT for produkt without binding in target kontekst → 404."""
    _seed(db)
    client = _admin_client(monkeypatch, db)

    # 'Other' has SA in 'sulfonowanie' but not 'analiza_koncowa' (default)
    rv = client.put("/api/parametry/1/formula-override", json={"produkt": "Other", "formula": "sm"})
    assert rv.status_code == 404


def test_kontekst_param_overrides_default(monkeypatch, db):
    """Body kontekst='sulfonowanie' targets that binding instead of default analiza_koncowa."""
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1/formula-override", json={
        "produkt": "Other", "formula": "sm * 2", "kontekst": "sulfonowanie"
    })
    assert rv.status_code == 200

    row = db.execute("SELECT formula FROM parametry_etapy WHERE id=11").fetchone()
    assert row["formula"] == "sm * 2"


def test_audit_event_emitted(monkeypatch, db):
    """Set/clear → parametr.updated audit with action + formula_old/new in payload."""
    _seed(db)
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1/formula-override", json={"produkt": "Cheminox_K", "formula": "sm"})
    assert rv.status_code == 200

    rows = db.execute(
        "SELECT entity_id, entity_label, payload_json FROM audit_log WHERE event_type='parametr.updated'"
    ).fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["entity_id"] == 1
    assert r["entity_label"] == "sa"
    payload = json.loads(r["payload_json"])
    assert payload["action"] == "formula_override_set"
    assert payload["produkt"] == "Cheminox_K"
    assert payload["kontekst"] == "analiza_koncowa"
    assert payload["formula_old"] is None
    assert payload["formula_new"] == "sm"
    assert payload["kod"] == "sa"


def test_audit_clear_action(monkeypatch, db):
    """Clear (formula=null) → audit action='formula_override_cleared'."""
    _seed(db)
    db.execute("UPDATE parametry_etapy SET formula='sm' WHERE id=10")
    db.commit()
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1/formula-override", json={"produkt": "Cheminox_K", "formula": None})
    assert rv.status_code == 200

    payload = json.loads(db.execute(
        "SELECT payload_json FROM audit_log WHERE event_type='parametr.updated'"
    ).fetchone()["payload_json"])
    assert payload["action"] == "formula_override_cleared"
    assert payload["formula_old"] == "sm"
    assert payload["formula_new"] is None


def test_admin_only(monkeypatch, db):
    """Non-admin gets 403."""
    _seed(db)
    import mbr.db, mbr.parametry.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.parametry.routes, "db_session", fake_db_session)

    from mbr.app import app
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "lab1", "rola": "laborant"}

    rv = client.put("/api/parametry/1/formula-override", json={"produkt": "Cheminox_K", "formula": "sm"})
    assert rv.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_parametry_formula_override.py -v
```

Expected: 8 failures — endpoint not registered.

- [ ] **Step 3: Implement endpoint in routes.py**

In `mbr/parametry/routes.py`, find existing `api_parametry_sa_bias` function (around line 366). After it (before `api_parametry_create`), add:

```python
@parametry_bp.route("/api/parametry/<int:param_id>/formula-override", methods=["PUT"])
@role_required("admin")
def api_parametry_formula_override(param_id):
    """Set or clear per-binding formula override in parametry_etapy.formula.

    Body: {produkt: <str>, formula: <str|null>, kontekst: <str|null>}
    - kontekst defaults to 'analiza_koncowa' (where obliczeniowy/srednia params currently live)
    - formula='' or whitespace-only → treated as null (clear override)
    - 404 if no binding exists for (parametr_id, produkt, kontekst)

    On success: rebuilds mbr_templates.parametry_lab snapshot for the produkt
    + emits parametr.updated audit with action='formula_override_set'/'formula_override_cleared'.
    """
    data = request.get_json(silent=True) or {}
    produkt = (data.get("produkt") or "").strip()
    kontekst = (data.get("kontekst") or "analiza_koncowa").strip()
    if not produkt:
        return jsonify({"error": "produkt required"}), 400

    raw_formula = data.get("formula")
    if raw_formula is None:
        new_formula = None
    elif isinstance(raw_formula, str) and raw_formula.strip() == "":
        new_formula = None  # empty/whitespace → clear
    else:
        new_formula = raw_formula.strip() if isinstance(raw_formula, str) else raw_formula

    with db_session() as db:
        # Locate binding
        row = db.execute(
            "SELECT pe.id, pe.formula AS formula_old, pa.kod "
            "FROM parametry_etapy pe "
            "JOIN parametry_analityczne pa ON pa.id = pe.parametr_id "
            "WHERE pe.parametr_id=? AND pe.produkt=? AND pe.kontekst=?",
            (param_id, produkt, kontekst),
        ).fetchone()
        if not row:
            return jsonify({"error": "Binding not found"}), 404

        # Skip no-op writes (idempotent — formula already at target value)
        if row["formula_old"] == new_formula:
            return jsonify({"ok": True, "produkt": produkt, "formula": new_formula})

        db.execute(
            "UPDATE parametry_etapy SET formula=? WHERE id=?",
            (new_formula, row["id"]),
        )

        # Rebuild parametry_lab snapshot so future fast-entry loads see updated formula
        plab = build_parametry_lab(db, produkt)
        db.execute(
            "UPDATE mbr_templates SET parametry_lab=? WHERE produkt=? AND status='active'",
            (_json.dumps(plab, ensure_ascii=False), produkt),
        )

        # Audit
        action = "formula_override_set" if new_formula is not None else "formula_override_cleared"
        log_event(
            EVENT_PARAMETR_UPDATED,
            entity_type="parametr",
            entity_id=param_id,
            entity_label=row["kod"],
            payload={
                "parametr_id": param_id,
                "kod": row["kod"],
                "produkt": produkt,
                "kontekst": kontekst,
                "action": action,
                "formula_old": row["formula_old"],
                "formula_new": new_formula,
            },
            db=db,
        )
        db.commit()

    return jsonify({"ok": True, "produkt": produkt, "formula": new_formula})
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_parametry_formula_override.py -v
```

Expected: 8 passing.

- [ ] **Step 5: Run regression suite**

```bash
pytest tests/test_parametry_audit_extended.py tests/test_parametry_create_audit.py tests/test_parametry_registry_audit.py tests/test_parametry_usage_impact.py tests/test_parametry_usage_impact_lists.py tests/test_parametry_grupa_api.py tests/test_parametry_opisowe_wartosci.py -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add mbr/parametry/routes.py tests/test_parametry_formula_override.py
git commit -m "feat(parametry): PUT /api/parametry/<id>/formula-override + audit"
```

---

### Task A2: Extend usage-impact response with formula_override

**Files:**
- Modify: `mbr/parametry/routes.py` (`api_parametry_usage_impact`)
- Modify: `tests/test_parametry_usage_impact_lists.py` (extend with formula_override test)

- [ ] **Step 1: Add failing test**

Append to `tests/test_parametry_usage_impact_lists.py`:

```python
def test_usage_impact_includes_formula_override(monkeypatch, db):
    """mbr_products items have formula_override field reflecting parametry_etapy.formula
    in analiza_koncowa kontekst (hardcoded for current obliczeniowy/srednia use case)."""
    db.execute("DELETE FROM parametry_analityczne")
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, formula) "
        "VALUES (1, 'sa', 'SA', 'obliczeniowy', 'sm - nacl - sa_bias')"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('Cheminox_K', 'Cheminox K')")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('Chegina_K7', 'Chegina K7')")
    # Cheminox_K has SA in analiza_koncowa with formula override
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, produkt, kontekst, kolejnosc, formula) "
        "VALUES (1, 'Cheminox_K', 'analiza_koncowa', 0, 'sm')"
    )
    # Chegina_K7 has SA in analiza_koncowa WITHOUT override
    db.execute(
        "INSERT INTO parametry_etapy (parametr_id, produkt, kontekst, kolejnosc) "
        "VALUES (1, 'Chegina_K7', 'analiza_koncowa', 0)"
    )
    db.commit()
    client = _client(monkeypatch, db)

    rv = client.get("/api/parametry/1/usage-impact")
    j = rv.get_json()
    by_key = {p["key"]: p for p in j["mbr_products"]}
    assert by_key["Cheminox_K"]["formula_override"] == "sm"
    assert by_key["Chegina_K7"]["formula_override"] is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_parametry_usage_impact_lists.py::test_usage_impact_includes_formula_override -v
```

Expected: 1 failure — `KeyError: 'formula_override'` or missing field.

- [ ] **Step 3: Modify api_parametry_usage_impact**

In `mbr/parametry/routes.py`, find the MBR products SQL block in `api_parametry_usage_impact`:

```python
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
```

Replace with (add formula_override fetch from analiza_koncowa kontekst, hardcoded per spec sec 6):

```python
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

        # Per-product formula override from analiza_koncowa kontekst
        # (hardcoded per spec — all current obliczeniowy/srednia params live there).
        # If a product doesn't have binding in analiza_koncowa, formula_override = None.
        ovr_rows = db.execute(
            """SELECT produkt, formula
               FROM parametry_etapy
               WHERE parametr_id = ? AND kontekst = 'analiza_koncowa'""",
            (param_id,),
        ).fetchall()
        ovr_by_produkt = {r["produkt"]: r["formula"] for r in ovr_rows}

        mbr_products = [
            {"key": k, "stages": v, "formula_override": ovr_by_produkt.get(k)}
            for k, v in mbr_grouped.items()
        ]
        mbr_bindings_count = len(mbr_rows)
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_parametry_usage_impact_lists.py -v
```

Expected: 4 passing (3 existing + 1 new).

- [ ] **Step 5: Run regression suite**

```bash
pytest tests/test_parametry_usage_impact.py tests/test_parametry_usage_impact_lists.py tests/test_parametry_formula_override.py -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add mbr/parametry/routes.py tests/test_parametry_usage_impact_lists.py
git commit -m "feat(parametry): usage-impact response includes formula_override per produkt"
```

---

## Phase B — Frontend Rejestr

> **Phase B note:** Manual browser verification at `http://localhost:5001/admin/parametry`. Each task verifies via hard reload, switch to Rejestr tab, click obliczeniowy/srednia parametr, observe expected behavior.

### Task B1: Render Override per produkt section

**Files:**
- Modify: `mbr/templates/parametry_editor.html` (JS — extend `_rejRenderTypConfig`, add `_rejRenderFormulaOverrides`)

- [ ] **Step 1: Add `_rejRenderFormulaOverrides` function**

In `mbr/templates/parametry_editor.html`, find existing `_rejRenderTypConfig` function. After it, add:

```javascript
function _rejRenderFormulaOverrides(p) {
  // Async-rendered placeholder; real content fills in via _rejFetchUsage callback.
  setTimeout(function() {
    _rejFetchUsage(p.id).then(function(impact) {
      if (_rejSelectedId !== p.id) return;  // user switched away
      var section = document.getElementById('pe-rej-formula-overrides');
      if (!section) return;

      var mbrProducts = (impact && impact.mbr_products) || [];
      var existingOverrides = mbrProducts.filter(function(mp) { return mp.formula_override !== null && mp.formula_override !== undefined; });
      var availableProducts = mbrProducts.filter(function(mp) { return mp.formula_override === null || mp.formula_override === undefined; });
      // Sort alphabetically per spec
      existingOverrides.sort(function(a, b) { return a.key.localeCompare(b.key); });
      availableProducts.sort(function(a, b) { return a.key.localeCompare(b.key); });

      var html = '<div style="margin-top:14px;padding-top:14px;border-top:1px solid var(--border-subtle);">';
      html += '<div style="font-size:9px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;">Override per produkt (opcjonalne)</div>';

      if (mbrProducts.length === 0) {
        html += '<div style="font-size:11px;color:var(--text-dim);font-style:italic;">Parametr nie jest jeszcze używany w żadnym produkcie MBR — najpierw dodaj go w zakładce Etapy.</div>';
      } else {
        // Existing overrides — rows with formula textarea + delete button
        existingOverrides.forEach(function(mp) {
          html += '<div class="pe-rej-fo-row" data-produkt="' + _rejEsc(mp.key) + '" style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border-subtle);">' +
            '<span class="wc-md-item-bind" style="min-width:120px;flex-shrink:0;">' + _rejEsc(mp.key) + '</span>' +
            '<input type="text" class="pe-rej-fo-input" data-produkt="' + _rejEsc(mp.key) + '" value="' + _rejEsc(mp.formula_override) + '" onblur="rejSetFormulaOverride(\'' + _rejEsc(mp.key) + '\', this.value)" style="flex:1;padding:5px 8px;font-family:var(--mono);font-size:11px;border:1.5px solid var(--border);border-radius:5px;">' +
            '<span class="pe-rej-fo-status" data-produkt="' + _rejEsc(mp.key) + '" style="font-size:10px;color:var(--text-dim);min-width:80px;text-align:right;"></span>' +
            '<button onclick="rejClearFormulaOverride(\'' + _rejEsc(mp.key) + '\')" style="background:none;border:none;color:var(--text-dim);cursor:pointer;padding:2px 8px;font-size:14px;" title="Usuń override (wróci do globalnej formuły)">×</button>' +
          '</div>';
        });

        // Add new override row
        if (availableProducts.length > 0) {
          html += '<div style="display:flex;gap:6px;margin-top:10px;align-items:center;">';
          html += '<input id="pe-rej-fo-add-produkt" list="pe-rej-fo-datalist" placeholder="Wpisz nazwę produktu..." style="flex:1;padding:6px 9px;border:1.5px solid var(--border);border-radius:5px;font-size:11.5px;">';
          html += '<datalist id="pe-rej-fo-datalist">';
          availableProducts.forEach(function(mp) {
            html += '<option value="' + _rejEsc(mp.key) + '">';
          });
          html += '</datalist>';
          html += '<button onclick="rejAddFormulaOverrideRow()" style="background:var(--teal);color:#fff;border:none;padding:6px 14px;border-radius:5px;font-size:11px;font-weight:600;cursor:pointer;">+ Dodaj</button>';
          html += '</div>';
        } else if (existingOverrides.length === mbrProducts.length) {
          html += '<div style="font-size:10px;color:var(--text-dim);font-style:italic;margin-top:8px;">Wszystkie produkty używające tego parametru mają już override.</div>';
        }
      }

      html += '</div>';
      section.innerHTML = html;
    });
  }, 0);

  return '<div id="pe-rej-formula-overrides"><div style="font-size:11px;color:var(--text-dim);margin-top:14px;">Ładowanie override-ów…</div></div>';
}
```

- [ ] **Step 2: Hook into `_rejRenderTypConfig`**

Find existing `_rejRenderTypConfig`. In the branch `else if (typ === 'obliczeniowy')` find the closing line. After:

```javascript
    html += '<div style="font-size:10px;color:var(--text-dim);margin-top:4px;padding-left:152px;">Tokeny: kod parametru w nawiasach klamrowych, np. {sa}, {nacl}. Lub bezpośrednio formuła SQL-style.</div>';
  }
```

(That's the end of obliczeniowy branch.)

Add `_rejRenderFormulaOverrides` call at the end of obliczeniowy AND srednia branches. The simplest approach: after the if/else if/else if chain ends, just before `return html;`, add:

```javascript
  // Sub-section: Override per produkt — only for obliczeniowy / srednia
  if (typ === 'obliczeniowy' || typ === 'srednia') {
    html += _rejRenderFormulaOverrides(p);
  }

  return html;
```

Find current `return html;` at the end of `_rejRenderTypConfig` and insert the if-block immediately before it.

- [ ] **Step 3: Add stub functions for B2 (auto-save / clear / add)**

After `_rejRenderFormulaOverrides`, add stubs (B2 will implement):

```javascript
function rejSetFormulaOverride(produkt, formula) { /* B2 */ }
function rejClearFormulaOverride(produkt) { /* B2 */ }
function rejAddFormulaOverrideRow() { /* B2 */ }
function _rejFlashOverride(produkt, msg, ok) { /* B2 */ }
```

- [ ] **Step 4: Verify in browser**

Server should be running. Hard reload `/admin/parametry` → Rejestr → klik parametr SA (obliczeniowy).

Expected:
- W detail panelu pod „Konfiguracja typu" pojawia się sekcja „Override per produkt (opcjonalne)"
- Lista pokazuje istniejące overrides (po teście B2 będzie pusta — wstępnie tylko Cheminox_K + Cheminox_K35 jeśli baza ma seedowane dane; na świeżym worktree DB lista pewnie pusta)
- Pod listą pole input + datalist z dostępnymi produktami + button „+ Dodaj"
- Klikanie nic nie robi (B2)

Klik parametr typu `bezposredni` (np. `aa`) → sekcja override NIE renderuje się.

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/parametry_editor.html
git commit -m "feat(parametry-rejestr): render Override per produkt section in Konfiguracja typu (B1)"
```

---

### Task B2: Auto-save + delete + add interactions

**Files:**
- Modify: `mbr/templates/parametry_editor.html` (JS — replace stubs)

- [ ] **Step 1: Replace stubs with implementations**

Find the 4 stubs added in B1:

```javascript
function rejSetFormulaOverride(produkt, formula) { /* B2 */ }
function rejClearFormulaOverride(produkt) { /* B2 */ }
function rejAddFormulaOverrideRow() { /* B2 */ }
function _rejFlashOverride(produkt, msg, ok) { /* B2 */ }
```

Replace with:

```javascript
function _rejFlashOverride(produkt, msg, ok) {
  var statusEl = document.querySelector('.pe-rej-fo-status[data-produkt="' + produkt.replace(/"/g, '') + '"]');
  if (!statusEl) return;
  statusEl.textContent = msg;
  statusEl.style.color = ok ? 'var(--green, #1a7a3a)' : 'var(--red, #b91c1c)';
  setTimeout(function() {
    if (statusEl) { statusEl.textContent = ''; statusEl.style.color = 'var(--text-dim)'; }
  }, 3000);
}

function rejSetFormulaOverride(produkt, formula) {
  if (_rejSelectedId == null) return;
  fetch('/api/parametry/' + _rejSelectedId + '/formula-override', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ produkt: produkt, formula: formula }),
  }).then(function(r) {
    return r.json().then(function(d) { return { status: r.status, data: d }; });
  }).then(function(res) {
    if (res.status === 200 && res.data.ok) {
      _rejFlashOverride(produkt, 'Zapisano', true);
      // Invalidate cache so next render fetches fresh formula_override values
      delete _rejUsageCache[_rejSelectedId];
    } else {
      _rejFlashOverride(produkt, 'Błąd: ' + (res.data.error || 'zapis nieudany'), false);
    }
  }).catch(function(e) {
    _rejFlashOverride(produkt, 'Błąd: ' + e.message, false);
  });
}

function rejClearFormulaOverride(produkt) {
  if (_rejSelectedId == null) return;
  if (!confirm('Usunąć override formuły dla „' + produkt + '"? Wróci do globalnej formuły.')) return;

  fetch('/api/parametry/' + _rejSelectedId + '/formula-override', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ produkt: produkt, formula: null }),
  }).then(function(r) {
    return r.json().then(function(d) { return { status: r.status, data: d }; });
  }).then(function(res) {
    if (res.status === 200 && res.data.ok) {
      // Re-render section: cache invalidate + force re-render of typ config
      delete _rejUsageCache[_rejSelectedId];
      _rejRerenderTypConfig();
    } else {
      alert('Błąd: ' + (res.data.error || 'nie udało się usunąć override'));
    }
  });
}

function rejAddFormulaOverrideRow() {
  if (_rejSelectedId == null) return;
  var inp = document.getElementById('pe-rej-fo-add-produkt');
  if (!inp) return;
  var produkt = (inp.value || '').trim();
  if (!produkt) { alert('Wybierz produkt z listy lub wpisz nazwę.'); return; }

  // Pre-fill with global formula (parametry_analityczne.formula)
  var p = _rejParams.find(function(x) { return x.id === _rejSelectedId; });
  if (!p) return;
  var globalFormula = p.formula || '';

  fetch('/api/parametry/' + _rejSelectedId + '/formula-override', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ produkt: produkt, formula: globalFormula }),
  }).then(function(r) {
    return r.json().then(function(d) { return { status: r.status, data: d }; });
  }).then(function(res) {
    if (res.status === 200 && res.data.ok) {
      delete _rejUsageCache[_rejSelectedId];
      _rejRerenderTypConfig();
      // Focus on the new row's formula input for immediate edit
      setTimeout(function() {
        var newInput = document.querySelector('.pe-rej-fo-input[data-produkt="' + produkt.replace(/"/g, '') + '"]');
        if (newInput) { newInput.focus(); newInput.select(); }
      }, 100);
    } else {
      alert('Błąd: ' + (res.data.error || 'nie udało się dodać override'));
    }
  });
}
```

- [ ] **Step 2: Verify end-to-end in browser**

Hard reload `/admin/parametry` → Rejestr → klik parametr `sa` (obliczeniowy).

Test flows:

1. **Add override**: w polu „Wpisz nazwę produktu" wybierz „Cheminox_K" z autocomplete → klik „+ Dodaj" → nowy wiersz pojawia się z pre-filled globalną formułą (`sm - nacl - sa_bias`) → kursor focused → edytuj formułę na `sm` → Tab/blur → status flash „Zapisano" przy wierszu (zielony, znika po 3s)

2. **Edit existing override**: kliknij w istniejące pole formuły → edytuj → blur → flash „Zapisano"

3. **Clear override (×)**: klik `×` przy wierszu → confirm „Usunąć override formuły dla 'Cheminox_K'?" → OK → wiersz znika z listy → Cheminox_K wraca do dropdown autocomplete

4. **Verify propagation**: ustaw override `sm` dla Cheminox_K → otwórz nową szarżę dla Cheminox_K → wpisz SM w fast-entry → SA powinno auto-recompute (bez NaCl) używając override formuły

5. **Audit**: `/admin/audit` → eventy `parametr.updated` z payload zawierającym `action: 'formula_override_set'` / `'formula_override_cleared'`, `produkt`, `formula_old`, `formula_new`

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/parametry_editor.html
git commit -m "feat(parametry-rejestr): formula override auto-save/clear/add interactions (B2)"
```

---

## Self-Review Notes

**Spec coverage:**
- Section 1 (Cel) — A1 + A2 + B1 + B2
- Section 2 (Lokalizacja UI) — B1 (sekcja w Konfiguracji typu, tylko obliczeniowy/srednia)
- Section 3 (Layout sekcji) — B1 (HTML), B2 (interactions)
- Section 4 (UX zachowania) — B1 (autocomplete + dropdown), B2 (auto-save/delete/add)
- Section 5 (Backend endpoint) — A1 (8 testów covering: set, clear, empty=clear, 404, kontekst override, audit set, audit clear, admin-only)
- Section 6 (usage-impact extension) — A2 (1 test)
- Section 7 (Frontend JS) — B1 (render) + B2 (interactions)
- Section 8 (Edge cases) — B1 covers empty state, A1 covers non-existent kod (no validation, fall-through), B2 covers re-render on cache invalidation
- Section 9 (Testy backend) — A1 (8) + A2 (1) = 9 testów backend
- Section 10 (Out of scope) — explicit; nie implementujemy

**Backward compat:**
- `sa_bias` mechanism — nietknięty (separate column, separate endpoint)
- Existing test_parametry_usage_impact_lists tests — extended with new `formula_override` field, 3 existing tests unaffected (just add field, don't break shape)
- Cert-side rendering — nie dotyczy (formula override żyje tylko w `parametry_etapy` MBR)

**No placeholders found** — all task steps include exact code, file paths, expected outputs.
