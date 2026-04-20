# Parametry opisowe — PR1 (schema + admin UI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pozwolić adminowi na konfigurację parametrów `typ='jakosciowy'` (opisowych) z listą dozwolonych wartości — bez zmian w flow laboranta.

**Architecture:** Dodaj jedną kolumnę JSON `opisowe_wartosci` do `parametry_analityczne`. Rozszerz CRUD parametrów o tę kolumnę + walidację per typ. W `/admin/wzory-cert` podmień free-text `<input>` dla `qualitative_result` na `<select>` dla parametrów `jakosciowy`. Filtr/dropdown/auto-fill w laborant flow są poza zakresem PR1 (pójdą w PR2/PR3).

**Tech Stack:** Python 3 / Flask / sqlite3 (`mbr.db.db_session`) / Jinja2 / vanilla JS / pytest (in-memory SQLite via `init_mbr_tables`).

**Spec reference:** `docs/superpowers/specs/2026-04-20-parametry-opisowe-design.md` § "PR1 — Schema + Admin UI".

---

## File Structure

### Create
- `tests/test_parametry_opisowe_wartosci.py` — testy PUT/POST, walidacja JSON + typ guard, odczyt przez `/api/parametry/list`.
- `tests/test_wzory_cert_opisowe.py` — test PUT `/api/cert/config/product/<key>` walidujący `qualitative_result ∈ opisowe_wartosci` dla `jakosciowy`.

### Modify
- `mbr/models.py` — dodaj migrację `ALTER TABLE parametry_analityczne ADD COLUMN opisowe_wartosci TEXT DEFAULT NULL` (wzorzec jak `grupa` w linii 1491).
- `mbr/parametry/routes.py` — POST `/api/parametry` (linia ~106) i PUT `/api/parametry/<id>` (linia 70) akceptują `opisowe_wartosci`; dodaj walidację + typ guard.
- `mbr/templates/parametry_editor.html` — dodaj `jakosciowy` do dropdownu `pa-new-typ` (linia 225), dodaj warunkowy edytor listy wartości w wierszu parametru.
- `mbr/certs/routes.py` — PUT `/api/cert/config/product/<key>` waliduje `qualitative_result` dla parametrów `jakosciowy`.
- `mbr/templates/admin/wzory_cert.html` — dla parametrów `jakosciowy` (z `opisowe_wartosci`) render `<select>` zamiast `<input>` (linia 865 i 1051).

---

## Tasks

### Task 1: Schema migration

**Files:**
- Modify: `mbr/models.py` (dodaj po linii 1494 — zaraz za migracją `grupa`)
- Test: `tests/test_parametry_opisowe_wartosci.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_parametry_opisowe_wartosci.py`:

```python
"""PR1: opisowe_wartosci column + CRUD + validation."""

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
    """Flask test client with db_session monkeypatched to shared in-memory db."""
    import mbr.db
    from mbr.app import app

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    app.config["TESTING"] = True
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["user"] = {"username": "admin_test", "rola": "admin", "id": 1}
        yield c


def test_opisowe_wartosci_column_exists(db):
    """Schema migration adds opisowe_wartosci column to parametry_analityczne."""
    cols = [r[1] for r in db.execute("PRAGMA table_info(parametry_analityczne)")]
    assert "opisowe_wartosci" in cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_parametry_opisowe_wartosci.py::test_opisowe_wartosci_column_exists -v`
Expected: FAIL — `assert "opisowe_wartosci" in cols` fails because column doesn't exist yet.

- [ ] **Step 3: Add migration in mbr/models.py**

Immediately after the `grupa` migration block (around line 1494 — after `except Exception: pass`), add:

```python
    # Migration: add opisowe_wartosci (JSON array) to parametry_analityczne
    # Used for typ='jakosciowy' params — allowed values for dropdown in hero/cert editor.
    try:
        db.execute("ALTER TABLE parametry_analityczne ADD COLUMN opisowe_wartosci TEXT DEFAULT NULL")
        db.commit()
    except Exception:
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_parametry_opisowe_wartosci.py::test_opisowe_wartosci_column_exists -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/models.py tests/test_parametry_opisowe_wartosci.py
git commit -m "feat(schema): add opisowe_wartosci column to parametry_analityczne"
```

---

### Task 2: PUT /api/parametry — accept + validate opisowe_wartosci

**Files:**
- Modify: `mbr/parametry/routes.py:70-103` (api_parametry_update)
- Test: `tests/test_parametry_opisowe_wartosci.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_parametry_opisowe_wartosci.py`:

```python
def _mk_param(db, kod="zapach", typ="jakosciowy"):
    cur = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision) "
        "VALUES (?, ?, ?, 'lab', 0)",
        (kod, kod.capitalize(), typ),
    )
    db.commit()
    return cur.lastrowid


def test_put_accepts_opisowe_wartosci_for_jakosciowy(client, db):
    pid = _mk_param(db, kod="zapach", typ="jakosciowy")
    payload = {"opisowe_wartosci": ["charakterystyczny", "obcy", "brak"]}
    r = client.put(f"/api/parametry/{pid}", json=payload)
    assert r.status_code == 200
    row = db.execute(
        "SELECT opisowe_wartosci FROM parametry_analityczne WHERE id=?", (pid,)
    ).fetchone()
    assert _json.loads(row["opisowe_wartosci"]) == ["charakterystyczny", "obcy", "brak"]


def test_put_rejects_empty_list_for_jakosciowy(client, db):
    pid = _mk_param(db, kod="barwa", typ="jakosciowy")
    r = client.put(f"/api/parametry/{pid}", json={"opisowe_wartosci": []})
    assert r.status_code == 400
    assert "opisowe_wartosci" in r.get_json()["error"].lower()


def test_put_rejects_non_list_for_jakosciowy(client, db):
    pid = _mk_param(db, kod="wyglad", typ="jakosciowy")
    r = client.put(f"/api/parametry/{pid}", json={"opisowe_wartosci": "foo"})
    assert r.status_code == 400


def test_put_rejects_non_string_items(client, db):
    pid = _mk_param(db, kod="smak", typ="jakosciowy")
    r = client.put(f"/api/parametry/{pid}", json={"opisowe_wartosci": ["ok", 5]})
    assert r.status_code == 400


def test_put_ignores_opisowe_wartosci_for_non_jakosciowy(client, db):
    pid = _mk_param(db, kod="gestosc", typ="bezposredni")
    r = client.put(f"/api/parametry/{pid}", json={"opisowe_wartosci": ["a", "b"]})
    assert r.status_code == 200
    row = db.execute(
        "SELECT opisowe_wartosci FROM parametry_analityczne WHERE id=?", (pid,)
    ).fetchone()
    # Non-jakosciowy: field should NOT be stored (stays NULL)
    assert row["opisowe_wartosci"] is None


def test_put_changing_typ_to_jakosciowy_requires_opisowe_wartosci(client, db):
    pid = _mk_param(db, kod="test1", typ="bezposredni")
    # Change typ to jakosciowy WITHOUT providing opisowe_wartosci
    r = client.put(f"/api/parametry/{pid}", json={"typ": "jakosciowy"})
    assert r.status_code == 400


def test_put_typ_guard_rejects_change_with_historical_results(client, db):
    """Cannot change typ once ebr_wyniki exist for this param."""
    pid = _mk_param(db, kod="histtest", typ="bezposredni")
    # Seed an ebr_wyniki row
    db.execute(
        "INSERT INTO ebr_wyniki (ebr_id, parametr_id, wartosc, w_limicie) "
        "VALUES (1, ?, 1.5, 1)",
        (pid,),
    )
    db.commit()
    r = client.put(
        f"/api/parametry/{pid}",
        json={"typ": "jakosciowy", "opisowe_wartosci": ["a", "b"]},
    )
    assert r.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_parametry_opisowe_wartosci.py -v -k "put_"`
Expected: All `test_put_*` FAIL — `opisowe_wartosci` not in allowed fields, no validation.

- [ ] **Step 3: Extend api_parametry_update in mbr/parametry/routes.py**

Replace the body of `api_parametry_update` (lines 70–103) with:

```python
@parametry_bp.route("/api/parametry/<int:param_id>", methods=["PUT"])
@login_required
def api_parametry_update(param_id):
    """Update global parameter fields. Admin can edit additional fields."""
    data = request.get_json(silent=True) or {}
    rola = session.get("user", {}).get("rola", "")
    allowed = {"label", "skrot", "formula", "metoda_nazwa", "metoda_formula", "metoda_factor", "precision"}
    if rola == "admin":
        allowed |= {"typ", "jednostka", "aktywny", "name_en", "method_code", "grupa", "opisowe_wartosci"}
    if "grupa" in data and data["grupa"] not in ALLOWED_GRUPY:
        return jsonify({"error": f"grupa must be one of: {', '.join(sorted(ALLOWED_GRUPY))}"}), 400

    with db_session() as db:
        existing = db.execute(
            "SELECT typ, opisowe_wartosci FROM parametry_analityczne WHERE id=?",
            (param_id,),
        ).fetchone()
        if not existing:
            return jsonify({"error": "Parametr not found"}), 404

        # Determine effective typ after this update
        new_typ = data.get("typ", existing["typ"]) if "typ" in data else existing["typ"]

        # Guard: block typ change if there are historical ebr_wyniki rows for this param.
        # Admin must remove or migrate the data manually before switching typ.
        if "typ" in data and data["typ"] != existing["typ"]:
            historical = db.execute(
                "SELECT 1 FROM ebr_wyniki WHERE parametr_id=? LIMIT 1", (param_id,)
            ).fetchone()
            if historical:
                return jsonify({
                    "error": "Nie można zmienić typ parametru — istnieją historyczne wyniki. Admin musi je usunąć ręcznie."
                }), 409

        # Validate opisowe_wartosci: JSON array of non-empty strings.
        # Required (non-empty) if effective typ == 'jakosciowy'; ignored otherwise.
        opisowe_raw = data.get("opisowe_wartosci", "__UNSET__")
        if new_typ == "jakosciowy":
            if opisowe_raw == "__UNSET__":
                # Changing TO jakosciowy requires the list explicitly.
                if "typ" in data and data["typ"] == "jakosciowy" and existing["typ"] != "jakosciowy":
                    return jsonify({"error": "opisowe_wartosci is required when typ='jakosciowy'"}), 400
                # Otherwise leave existing value untouched.
            else:
                if not isinstance(opisowe_raw, list) or len(opisowe_raw) == 0:
                    return jsonify({"error": "opisowe_wartosci must be a non-empty list"}), 400
                if not all(isinstance(v, str) and v.strip() for v in opisowe_raw):
                    return jsonify({"error": "opisowe_wartosci must be a list of non-empty strings"}), 400
        else:
            # typ != jakosciowy: force NULL in storage regardless of what was sent.
            if opisowe_raw != "__UNSET__":
                data.pop("opisowe_wartosci", None)
                data["opisowe_wartosci"] = None
            # Ensure stored value is NULL when switching away from jakosciowy.
            if existing["typ"] == "jakosciowy" and new_typ != "jakosciowy":
                data["opisowe_wartosci"] = None

        # Serialize opisowe_wartosci to JSON string if present and not None.
        if "opisowe_wartosci" in data and isinstance(data["opisowe_wartosci"], list):
            data["opisowe_wartosci"] = _json.dumps(data["opisowe_wartosci"], ensure_ascii=False)

        updates = {k: v for k, v in data.items() if k in allowed}
        if not updates:
            return jsonify({"error": "No valid fields"}), 400
        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [param_id]
        db.execute(f"UPDATE parametry_analityczne SET {sets} WHERE id=?", vals)

        # Rebuild parametry_lab for all active templates that use this parameter
        affected = db.execute(
            """SELECT DISTINCT mt.produkt
               FROM mbr_templates mt
               JOIN parametry_etapy pe ON pe.produkt = mt.produkt
               WHERE pe.parametr_id = ? AND mt.status = 'active'""",
            (param_id,),
        ).fetchall()
        for row in affected:
            plab = build_parametry_lab(db, row["produkt"])
            db.execute(
                "UPDATE mbr_templates SET parametry_lab=? WHERE produkt=? AND status='active'",
                (_json.dumps(plab, ensure_ascii=False), row["produkt"]),
            )
        db.commit()
    return jsonify({"ok": True})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_parametry_opisowe_wartosci.py -v -k "put_"`
Expected: All `test_put_*` PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/parametry/routes.py tests/test_parametry_opisowe_wartosci.py
git commit -m "feat(parametry): PUT /api/parametry accepts opisowe_wartosci + typ guard"
```

---

### Task 3: POST /api/parametry — accept opisowe_wartosci + `jakosciowy` typ

**Files:**
- Modify: `mbr/parametry/routes.py:106-131` (api_parametry_create)
- Test: `tests/test_parametry_opisowe_wartosci.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_parametry_opisowe_wartosci.py`:

```python
def test_post_creates_jakosciowy_param_with_wartosci(client, db):
    payload = {
        "kod": "zapach",
        "label": "Zapach",
        "typ": "jakosciowy",
        "grupa": "lab",
        "opisowe_wartosci": ["charakterystyczny", "obcy", "brak"],
    }
    r = client.post("/api/parametry", json=payload)
    assert r.status_code == 200, r.get_json()
    new_id = r.get_json()["id"]
    row = db.execute(
        "SELECT typ, opisowe_wartosci FROM parametry_analityczne WHERE id=?", (new_id,)
    ).fetchone()
    assert row["typ"] == "jakosciowy"
    assert _json.loads(row["opisowe_wartosci"]) == ["charakterystyczny", "obcy", "brak"]


def test_post_rejects_jakosciowy_without_wartosci(client, db):
    payload = {"kod": "barwa", "label": "Barwa", "typ": "jakosciowy", "grupa": "lab"}
    r = client.post("/api/parametry", json=payload)
    assert r.status_code == 400


def test_post_ignores_opisowe_wartosci_for_non_jakosciowy(client, db):
    payload = {
        "kod": "gestosc",
        "label": "Gęstość",
        "typ": "bezposredni",
        "grupa": "lab",
        "opisowe_wartosci": ["a", "b"],
    }
    r = client.post("/api/parametry", json=payload)
    assert r.status_code == 200
    new_id = r.get_json()["id"]
    row = db.execute(
        "SELECT opisowe_wartosci FROM parametry_analityczne WHERE id=?", (new_id,)
    ).fetchone()
    assert row["opisowe_wartosci"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_parametry_opisowe_wartosci.py -v -k "post_"`
Expected: `test_post_creates_*` FAIL (column not in INSERT); `test_post_rejects_*` FAIL (no validation).

- [ ] **Step 3: Extend api_parametry_create in mbr/parametry/routes.py**

Replace `api_parametry_create` (lines 106–131) with:

```python
@parametry_bp.route("/api/parametry", methods=["POST"])
@role_required("admin")
def api_parametry_create():
    """Create a new analytical parameter (admin only)."""
    data = request.get_json(silent=True) or {}
    kod = (data.get("kod") or "").strip()
    label = (data.get("label") or "").strip()
    typ = data.get("typ", "bezposredni")
    grupa = data.get("grupa", "lab")
    if not kod or not label:
        return jsonify({"error": "kod and label required"}), 400
    if grupa not in ALLOWED_GRUPY:
        return jsonify({"error": f"grupa must be one of: {', '.join(sorted(ALLOWED_GRUPY))}"}), 400

    # Validate opisowe_wartosci for jakosciowy
    opisowe_json = None
    if typ == "jakosciowy":
        raw = data.get("opisowe_wartosci")
        if not isinstance(raw, list) or len(raw) == 0:
            return jsonify({"error": "opisowe_wartosci must be a non-empty list for typ='jakosciowy'"}), 400
        if not all(isinstance(v, str) and v.strip() for v in raw):
            return jsonify({"error": "opisowe_wartosci must be a list of non-empty strings"}), 400
        opisowe_json = _json.dumps(raw, ensure_ascii=False)
    # For non-jakosciowy: opisowe_json stays None regardless of body.

    with db_session() as db:
        try:
            cur = db.execute(
                "INSERT INTO parametry_analityczne (kod, label, skrot, typ, jednostka, precision, name_en, method_code, grupa, opisowe_wartosci) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kod, label, data.get("skrot", ""), typ, data.get("jednostka", ""),
                 data.get("precision", 2), data.get("name_en", ""), data.get("method_code", ""),
                 grupa, opisowe_json),
            )
            db.commit()
        except Exception:
            return jsonify({"error": "Parametr already exists"}), 409
    return jsonify({"ok": True, "id": cur.lastrowid})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_parametry_opisowe_wartosci.py -v -k "post_"`
Expected: All `test_post_*` PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/parametry/routes.py tests/test_parametry_opisowe_wartosci.py
git commit -m "feat(parametry): POST /api/parametry accepts opisowe_wartosci"
```

---

### Task 4: GET /api/parametry/list — exposes opisowe_wartosci

**Files:**
- Test: `tests/test_parametry_opisowe_wartosci.py`
- (No code change — endpoint already `SELECT *`, so new column is auto-exposed. Test verifies.)

- [ ] **Step 1: Write the test**

Add to `tests/test_parametry_opisowe_wartosci.py`:

```python
def test_list_exposes_opisowe_wartosci(client, db):
    """GET /api/parametry/list returns opisowe_wartosci as JSON string."""
    pid = _mk_param(db, kod="zapach_list", typ="jakosciowy")
    db.execute(
        "UPDATE parametry_analityczne SET opisowe_wartosci=? WHERE id=?",
        (_json.dumps(["a", "b"]), pid),
    )
    db.commit()
    r = client.get("/api/parametry/list")
    assert r.status_code == 200
    rows = r.get_json()
    row = next((x for x in rows if x["id"] == pid), None)
    assert row is not None
    assert "opisowe_wartosci" in row
    assert _json.loads(row["opisowe_wartosci"]) == ["a", "b"]
```

- [ ] **Step 2: Run test to verify it passes immediately**

Run: `pytest tests/test_parametry_opisowe_wartosci.py::test_list_exposes_opisowe_wartosci -v`
Expected: PASS (SELECT * already includes the column).

If it fails, inspect `api_parametry_list` and add `opisowe_wartosci` to the returned dict explicitly.

- [ ] **Step 3: Commit**

```bash
git add tests/test_parametry_opisowe_wartosci.py
git commit -m "test(parametry): verify GET /api/parametry/list exposes opisowe_wartosci"
```

---

### Task 5: Add `jakosciowy` to typ dropdown in parametry_editor.html

**Files:**
- Modify: `mbr/templates/parametry_editor.html:225-229` (`pa-new-typ` select)

- [ ] **Step 1: Apply edit**

In `mbr/templates/parametry_editor.html` around line 225, replace:

```html
      <select id="pa-new-typ">
        <option value="bezposredni">bezpośredni</option>
        <option value="titracja">titracja</option>
        <option value="obliczeniowy">obliczeniowy</option>
      </select>
```

with:

```html
      <select id="pa-new-typ">
        <option value="bezposredni">bezpośredni</option>
        <option value="titracja">titracja</option>
        <option value="obliczeniowy">obliczeniowy</option>
        <option value="jakosciowy">jakościowy (opisowy)</option>
      </select>
```

- [ ] **Step 2: Verify renders (manual smoke)**

Start dev server: `python -m mbr.app`
Open `/parametry` as admin, confirm "jakościowy (opisowy)" appears in the "Nowy parametr" typ dropdown.

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/parametry_editor.html
git commit -m "feat(parametry-editor): add 'jakosciowy' to typ dropdown"
```

---

### Task 6: Opisowe wartości — UI editor in parametry_editor.html

**Files:**
- Modify: `mbr/templates/parametry_editor.html` (JS rendering the parametry table rows; around the `renderParametryRejestr` / `paReload` function — exact location depends on existing structure)

The editor must appear only when the row's `typ === 'jakosciowy'`. Implementation: a collapsible detail row (or inline expand button) with a list of inputs + remove buttons + "Dodaj wartość" button. Save on blur of the whole list via PUT.

- [ ] **Step 1: Locate the row-render function**

Run: `grep -n "function pa\|function render.*[Pp]ara" mbr/templates/parametry_editor.html | head -20`

Identify the JS function that renders one row of the parametry table. The qualitative_result input reference is at line 865 in wzory_cert.html — but for `parametry_editor.html` we need to find the equivalent. Expected: a `paRow(p)` or similar function that builds each `<tr>`.

- [ ] **Step 2: Add expand-row markup and handler**

Insert after the standard cells of a jakosciowy row, a new button "✏ Wartości opisowe (N)" that toggles an inline `<tr class="pa-opisowe-row">` containing:

```html
<td colspan="<N>">
  <div class="pa-opisowe-editor" data-param-id="<id>">
    <div class="pa-opisowe-list"></div>
    <button type="button" onclick="paOpisoweAdd(<id>)">+ Dodaj wartość</button>
    <button type="button" onclick="paOpisoweSave(<id>)">Zapisz</button>
    <span class="pa-opisowe-status" style="font-size:10px;color:var(--text-dim);"></span>
  </div>
</td>
```

And the three JS helpers:

```javascript
function paOpisoweRender(paramId, values) {
  var editor = document.querySelector('.pa-opisowe-editor[data-param-id="' + paramId + '"]');
  if (!editor) return;
  var list = editor.querySelector('.pa-opisowe-list');
  list.innerHTML = '';
  (values || []).forEach(function(v, i) {
    var row = document.createElement('div');
    row.className = 'pa-opisowe-item';
    row.style.cssText = 'display:flex;gap:4px;margin-bottom:3px;';
    row.innerHTML =
      '<input class="pa-input" type="text" value="' + esc(v) + '" style="flex:1;">' +
      '<button type="button" onclick="paOpisoweRemove(' + paramId + ',' + i + ')">×</button>';
    list.appendChild(row);
  });
}

function paOpisoweAdd(paramId) {
  var editor = document.querySelector('.pa-opisowe-editor[data-param-id="' + paramId + '"]');
  var list = editor.querySelector('.pa-opisowe-list');
  var current = Array.prototype.map.call(list.querySelectorAll('input'), function(i) { return i.value; });
  current.push('');
  paOpisoweRender(paramId, current);
}

function paOpisoweRemove(paramId, idx) {
  var editor = document.querySelector('.pa-opisowe-editor[data-param-id="' + paramId + '"]');
  var list = editor.querySelector('.pa-opisowe-list');
  var current = Array.prototype.map.call(list.querySelectorAll('input'), function(i) { return i.value; });
  current.splice(idx, 1);
  paOpisoweRender(paramId, current);
}

function paOpisoweSave(paramId) {
  var editor = document.querySelector('.pa-opisowe-editor[data-param-id="' + paramId + '"]');
  var list = editor.querySelector('.pa-opisowe-list');
  var values = Array.prototype.map.call(list.querySelectorAll('input'), function(i) { return i.value.trim(); })
    .filter(function(v) { return v; });
  var status = editor.querySelector('.pa-opisowe-status');
  if (values.length === 0) {
    status.textContent = 'Lista nie może być pusta';
    status.style.color = 'var(--red)';
    return;
  }
  fetch('/api/parametry/' + paramId, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({opisowe_wartosci: values}),
  }).then(function(r) { return r.json(); }).then(function(resp) {
    if (resp.ok) {
      status.textContent = '✓ Zapisano';
      status.style.color = 'var(--green)';
    } else {
      status.textContent = '✗ ' + (resp.error || 'Błąd');
      status.style.color = 'var(--red)';
    }
    setTimeout(function() { status.textContent = ''; }, 2500);
  });
}
```

When the row is expanded, call `paOpisoweRender(paramId, JSON.parse(param.opisowe_wartosci || '[]'))` to seed the editor.

- [ ] **Step 3: Wire the expand toggle**

In the row template (wherever `typ` is shown for a param row), if `p.typ === 'jakosciowy'` render a small button `✏` that toggles `.pa-opisowe-row` visibility and calls `paOpisoweRender`.

- [ ] **Step 4: Smoke test manually**

Dev server, open `/parametry`, expand a `typ='jakosciowy'` row, add values, click Zapisz. Verify status shows "✓ Zapisano". Reload page, confirm values persisted.

Seed one test param if none exist:
```python
python -c "
from mbr.db import db_session
with db_session() as db:
    db.execute(\"INSERT OR IGNORE INTO parametry_analityczne (kod,label,typ,grupa,precision) VALUES ('zapach','Zapach','jakosciowy','lab',0)\")
    db.commit()
"
```

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/parametry_editor.html
git commit -m "feat(parametry-editor): UI editor for opisowe_wartosci (jakosciowy params)"
```

---

### Task 7: Cert editor validation — qualitative_result ∈ opisowe_wartosci

**Files:**
- Modify: `mbr/certs/routes.py` (PUT `/api/cert/config/product/<key>` — search for `qualitative_result` handling)
- Test: `tests/test_wzory_cert_opisowe.py`

**Payload shape (confirmed from mbr/certs/routes.py:468-615):**

```json
{
  "parameters": [
    {"id": "zapach", "data_field": "zapach", "qualitative_result": "charakterystyczny",
     "requirement": "...", "format": "1", "name_pl": "...", "name_en": "...", "method": "..."}
  ],
  "variants": [
    {"id": "base", "label": "Base",
     "overrides": {
       "remove_parameters": [...],
       "add_parameters": [
         {"id": "wyglad", "data_field": "wyglad", "qualitative_result": "bezbarwna ciecz", ...}
       ]
     }}
  ]
}
```

Param identifier in the payload is `id` (= kod string), **not** `parametr_id`. Validation must use `kod_to_id` map (already built at line 495) to resolve to parametr_id.

- [ ] **Step 1: Write the failing test**

Create `tests/test_wzory_cert_opisowe.py`:

```python
"""PR1: PUT /api/cert/config/product/<key> validates qualitative_result for jakosciowy params."""

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
    from mbr.app import app

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    app.config["TESTING"] = True
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["user"] = {"username": "admin_test", "rola": "admin", "id": 1}
        yield c


def _seed_jakosciowy_param_on_product(db, produkt="TESTPROD", kod="zapach",
                                      wartosci=None):
    wartosci = wartosci or ["charakterystyczny", "obcy"]
    pid = db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision, opisowe_wartosci) "
        "VALUES (?, ?, 'jakosciowy', 'lab', 0, ?)",
        (kod, kod.capitalize(), _json.dumps(wartosci)),
    ).lastrowid
    db.execute(
        "INSERT INTO produkty (nazwa, display_name) VALUES (?, ?)",
        (produkt, produkt),
    )
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label) VALUES (?, 'base', 'Base')",
        (produkt,),
    )
    db.commit()
    return pid, kod


def _base_payload(kod, qr):
    return {
        "parameters": [
            {"id": kod, "data_field": kod, "qualitative_result": qr,
             "requirement": "charakterystyczny", "format": "1",
             "name_pl": "Zapach", "name_en": "Odour"}
        ],
        "variants": [],
    }


def test_put_accepts_qualitative_result_from_allowed_list(client, db):
    _, kod = _seed_jakosciowy_param_on_product(db)
    r = client.put(f"/api/cert/config/product/TESTPROD", json=_base_payload(kod, "obcy"))
    assert r.status_code == 200, r.get_json()


def test_put_rejects_qualitative_result_outside_allowed_list(client, db):
    _, kod = _seed_jakosciowy_param_on_product(db)
    r = client.put(f"/api/cert/config/product/TESTPROD", json=_base_payload(kod, "invalid_value"))
    assert r.status_code == 400
    err = (r.get_json() or {}).get("error", "").lower()
    assert "niedozwolona" in err or "opisowe_wartosci" in err


def test_put_allows_empty_qualitative_result_for_jakosciowy(client, db):
    _, kod = _seed_jakosciowy_param_on_product(db)
    r = client.put(f"/api/cert/config/product/TESTPROD", json=_base_payload(kod, ""))
    assert r.status_code == 200


def test_put_validates_qualitative_result_in_variant_add_parameters(client, db):
    _, kod = _seed_jakosciowy_param_on_product(db)
    payload = {
        "parameters": [],
        "variants": [
            {"id": "base", "label": "Base", "overrides": {
                "remove_parameters": [],
                "add_parameters": [
                    {"id": kod, "data_field": kod, "qualitative_result": "invalid_value",
                     "requirement": "x", "format": "1"}
                ],
            }}
        ],
    }
    r = client.put("/api/cert/config/product/TESTPROD", json=payload)
    assert r.status_code == 400


def test_put_skips_validation_for_non_jakosciowy(client, db):
    """Non-jakosciowy params accept any qualitative_result text (backward compat)."""
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa, precision) "
        "VALUES ('dens', 'Gęstość', 'bezposredni', 'lab', 2)"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('TP2', 'TP2')")
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label) VALUES ('TP2', 'base', 'Base')"
    )
    db.commit()
    payload = {
        "parameters": [
            {"id": "dens", "data_field": "dens", "qualitative_result": "anything goes",
             "requirement": "0.98-1.02", "format": "2"}
        ],
        "variants": [],
    }
    r = client.put("/api/cert/config/product/TP2", json=payload)
    assert r.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_wzory_cert_opisowe.py -v`
Expected: `test_put_rejects_*` and `test_put_validates_qualitative_result_in_variant_*` FAIL (return 200 instead of 400); other tests likely pass trivially.

- [ ] **Step 3: Add validation in mbr/certs/routes.py**

In `api_cert_config_product_put` (starts line 468), inside the validation phase (inside `with db_session() as db:`, after `kod_to_id` is built around line 495, BEFORE the PHASE 2 atomic write block around line 576), insert:

```python
        # ── Validate qualitative_result for jakosciowy params ──
        # For params with typ='jakosciowy' and non-empty opisowe_wartosci,
        # qualitative_result must be from the allowed list (or empty).
        def _validate_qr(pid_row_id, qr_text, context_label):
            qr = (qr_text or "").strip()
            if not qr:
                return None
            meta = db.execute(
                "SELECT typ, opisowe_wartosci FROM parametry_analityczne WHERE id=?",
                (pid_row_id,),
            ).fetchone()
            if not meta or meta["typ"] != "jakosciowy":
                return None
            try:
                allowed = _json.loads(meta["opisowe_wartosci"] or "[]")
            except Exception:
                allowed = []
            if allowed and qr not in allowed:
                return (f"{context_label}: wartość '{qr}' jest niedozwolona "
                        f"(opisowe_wartosci: {allowed})")
            return None

        if parameters is not None:
            for p in parameters:
                df = (p.get("data_field") or p.get("id", "")).strip()
                pid_row_id = kod_to_id.get(df)
                if pid_row_id is None:
                    continue  # already caught by earlier validation
                err = _validate_qr(pid_row_id, p.get("qualitative_result"), f"Parametr '{df}'")
                if err:
                    return jsonify({"error": err}), 400

        if variants is not None:
            for v in variants:
                overrides = v.get("overrides") or {}
                for ap in overrides.get("add_parameters", []) or []:
                    ap_df = (ap.get("data_field") or ap.get("id") or "").strip()
                    pid_row_id = kod_to_id.get(ap_df)
                    if pid_row_id is None:
                        continue
                    err = _validate_qr(
                        pid_row_id, ap.get("qualitative_result"),
                        f"Wariant '{v.get('id', '?')}': parametr '{ap_df}'",
                    )
                    if err:
                        return jsonify({"error": err}), 400
```

Note: `_json` is already imported at the top of `mbr/certs/routes.py` (check with grep if unsure). If not imported, add `import json as _json` at the top.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_wzory_cert_opisowe.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/certs/routes.py tests/test_wzory_cert_opisowe.py
git commit -m "feat(certs): validate qualitative_result against opisowe_wartosci for jakosciowy"
```

---

### Task 8: Cert editor UI — `<select>` for jakosciowy params

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html:865` and `:1051` (the two places where `qualitative_result` input is rendered — base params and add_parameters)

- [ ] **Step 1: Fetch param meta in the editor**

Check whether the editor already has access to `parametry_analityczne.typ` and `opisowe_wartosci` for each param (via `/api/parametry/list` or embedded in product config payload).

Run: `grep -n "fetch.*parametry\|fetchParams\|loadParams" mbr/templates/admin/wzory_cert.html | head -10`

If param meta is not yet fetched, add `fetch('/api/parametry/list').then(...)` in page init; store as `window.__paramMeta = {paramId: {typ, opisowe_wartosci}}`.

- [ ] **Step 2: Replace input with conditional select in row render**

Around line 865 (base params row):

```javascript
// OLD:
'<td><input data-field="qualitative_result" value="' + _esc(p.qualitative_result || '') + '" placeholder="—"></td>' +

// NEW:
'<td>' + renderQualResultInput(p) + '</td>' +
```

And add the helper:

```javascript
function renderQualResultInput(p) {
  var meta = (window.__paramMeta || {})[p.parametr_id];
  if (meta && meta.typ === 'jakosciowy') {
    var values = [];
    try { values = JSON.parse(meta.opisowe_wartosci || '[]'); } catch (e) {}
    if (values.length > 0) {
      var cur = p.qualitative_result || '';
      var opts = '<option value=""' + (cur === '' ? ' selected' : '') + '>—</option>';
      values.forEach(function(v) {
        var sel = (v === cur) ? ' selected' : '';
        opts += '<option value="' + _esc(v) + '"' + sel + '>' + _esc(v) + '</option>';
      });
      if (cur && values.indexOf(cur) === -1) {
        opts += '<option value="' + _esc(cur) + '" selected>' + _esc(cur) + ' (historyczna)</option>';
      }
      return '<select data-field="qualitative_result">' + opts + '</select>';
    }
  }
  return '<input data-field="qualitative_result" value="' + _esc(p.qualitative_result || '') + '" placeholder="—">';
}
```

Do the same for the add_parameters row at line 1051, replacing `data-vp="qualitative_result"` with the same conditional `select`/`input` logic (extract to a second helper `renderVpQualInput(ap)`, mirroring the above with `data-vp` attribute).

The save path at line 1155–1156 reads `.value` from the element — works identically for `<select>` and `<input>`, so no save-side change needed.

- [ ] **Step 3: Smoke test manually**

Dev server. Open `/admin/wzory-cert`, open a product that has a `jakosciowy` param with `opisowe_wartosci` set. Verify:
- Kolumna "Wynik opisowy" renderuje `<select>` (nie input).
- Dropdown zawiera wartości z `opisowe_wartosci` + opcję "—".
- Zapis działa; po reloadzie wybór utrzymany.
- Parametr `bezposredni` dalej ma `<input>` (nie rozbity).

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(wzory-cert): <select> for qualitative_result on jakosciowy params"
```

---

### Task 9: Regression — existing cert render + laborant flow untouched

**Files:**
- Test: `tests/test_parametry_opisowe_wartosci.py` (add final test)

- [ ] **Step 1: Add regression test**

```python
def test_existing_params_unaffected_by_new_column(client, db):
    """A bezposredni param without opisowe_wartosci continues to work: PUT updates label, no errors."""
    pid = _mk_param(db, kod="gestosc2", typ="bezposredni")
    r = client.put(f"/api/parametry/{pid}", json={"label": "Gęstość v2"})
    assert r.status_code == 200
    row = db.execute(
        "SELECT label, opisowe_wartosci FROM parametry_analityczne WHERE id=?", (pid,)
    ).fetchone()
    assert row["label"] == "Gęstość v2"
    assert row["opisowe_wartosci"] is None
```

- [ ] **Step 2: Run all PR1 tests**

Run: `pytest tests/test_parametry_opisowe_wartosci.py tests/test_wzory_cert_opisowe.py -v`
Expected: ALL PASS.

Run full suite as well: `pytest`
Expected: ALL PASS — no regressions in existing tests (`test_parametry.py`, `test_certs.py`, `test_certs_grupa.py`, etc.).

- [ ] **Step 3: Commit**

```bash
git add tests/test_parametry_opisowe_wartosci.py
git commit -m "test(parametry): regression — non-jakosciowy params unaffected"
```

---

### Task 10: Push and verify deploy

- [ ] **Step 1: Push**

```bash
git push origin main
```

- [ ] **Step 2: Wait for auto-deploy**

≤5 min. Check `/opt/lims/logs/auto-deploy.log` or `systemctl status lims` on prod.

- [ ] **Step 3: Smoke test on prod**

- Open `/parametry` as admin — widać `jakościowy (opisowy)` w dropdownie typu przy dodawaniu.
- Otwórz istniejący parametr `typ='jakosciowy'` (jeśli jest), rozwiń edytor wartości opisowych, dodaj/usuń wartość, zapisz.
- Otwórz `/admin/wzory-cert` — parametry `jakosciowy` ze skonfigurowaną listą mają `<select>` zamiast `<input>`.
- Wygeneruj świadectwo — zachowanie identyczne jak przed PR1 (używa `cert_qualitative_result`, jak dziś).
- Laborant flow (entry form, hero) — identyczny, bez zmian (filtrowanie przychodzi w PR2/PR3).

---

## Open Questions Resolved

- **UI listy wartości** → Inline expand-row z input+remove+dodaj+zapisz (Task 6). Prostsze niż drag-reorder, wystarczające dla 3–5 wartości.
- **Guard zmiany typu** → Konserwatywnie: blokuj jeśli istnieją JAKIEKOLWIEK `ebr_wyniki` dla tego parametru. Admin musi wyczyścić historię przed zmianą typu.
- **Walidacja cert qualitative_result** → Enforcowana tylko gdy parametr jest `typ='jakosciowy'` i ma niepustą `opisowe_wartosci`. Dla innych typów — dalej free-text (backward compat).

## Out of scope for PR1

- Filtrowanie `grupa='zewn' OR typ='jakosciowy'` w formularzu laboranta → PR2.
- Auto-insert `ebr_wyniki.wartosc_text` przy tworzeniu EBR → PR2.
- Backfill dla istniejących otwartych partii → PR2.
- Dropdown w hero, numeric input z badge dla zewn → PR3.
- Cert render używający `ebr_wyniki.wartosc_text` per partia → PR3.
- Myślnik dla pustego zewn w cert → PR3.
