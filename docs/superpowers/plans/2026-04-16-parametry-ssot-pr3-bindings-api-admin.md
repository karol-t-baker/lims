# Parametry SSOT — PR 3 (Etap B.2) — /api/bindings + admin panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add new `/api/bindings/*` REST endpoints that CRUD `produkt_etap_limity` directly (including typ flags). Rewrite admin panel `/parametry` tab for "Etapy" to use the new endpoints and expose Sz/Zb/Pl flag checkboxes. Legacy `/api/parametry/etapy/*` endpoints stay in place (laborant modal still calls them — PR 4 migrates that). Zero breakage of existing flows.

**Architecture:** New URL namespace `/api/bindings/*` for the SSOT model. No branching-by-pipeline-vs-legacy: all endpoints operate directly on `produkt_etap_limity` + `etap_parametry` (where needed for catalog). Admin panel `/parametry` becomes the "new canonical CRUD surface" for parameter bindings; laborant modal catches up in PR 4.

**Tech Stack:** Flask + Jinja + vanilla JS (existing stack). No new deps.

**Dependencies:** PR 2 (`feature/parametry-ssot-pr2`) must be merged — relies on `produkt_etap_limity` having flag columns.

---

## File Structure

**Modify:**
- `mbr/parametry/routes.py` — add new `/api/bindings/*` endpoints
- `mbr/templates/parametry_editor.html` — update "Etapy" tab: new endpoints, Sz/Zb/Pl columns, kontekst→etap mapping in JS

**Not touched in this PR:**
- Legacy `/api/parametry/etapy/*` endpoints — continue to work for laborant modal
- `mbr/laborant/routes.py` and laborant templates — PR 4
- Cert generator — PR 5

---

## Endpoint contract

| Route | Method | Body / Args | Response | Notes |
|---|---|---|---|---|
| `/api/bindings` | GET | `?produkt=X&etap_id=Y` (or `?produkt=X&etap_kod=Z`) | `[{id, produkt, etap_id, parametr_id, kod, label, skrot, typ, min_limit, max_limit, precision, nawazka_g, spec_value, kolejnosc, grupa, formula, sa_bias, krok, wymagany, dla_szarzy, dla_zbiornika, dla_platkowania}, ...]` | Ordered by `kolejnosc, kod` |
| `/api/bindings` | POST | `{produkt, etap_id, parametr_id, min_limit?, max_limit?, nawazka_g?, precision?, spec_value?, kolejnosc?, grupa?, formula?, sa_bias?, krok?, wymagany?, dla_szarzy?, dla_zbiornika?, dla_platkowania?}` | `{ok: true, id}` | Defaults: `dla_szarzy=1, dla_zbiornika=1, dla_platkowania=0, grupa='lab', wymagany=0, kolejnosc=0`. UNIQUE(produkt, etap_id, parametr_id) enforced — duplicate returns 409. |
| `/api/bindings/<id>` | PUT | any subset of POST fields | `{ok: true, auto_deleted: bool}` | Auto-DELETE if all 3 typ flags end at 0 after update — signals in `auto_deleted: true` |
| `/api/bindings/<id>` | DELETE | — | `{ok: true}` | Hard delete |
| `/api/bindings/catalog` | GET | `?produkt=X` (optional) | `[{id, kod, label, skrot, typ, jednostka, precision, aktywny}, ...]` | Active `parametry_analityczne` rows for picker. Same semantics as existing `/api/parametry/available` — this is just a namespaced rename. |

All endpoints require `@login_required` (same as old). No role restriction (admin-only is enforced via template access at `/parametry`).

---

## Task 1: GET /api/bindings — failing test

**Files:**
- Modify: `tests/test_parametry_routes.py` (or create if missing — if missing, use `tests/test_bindings_api.py`)

- [ ] **Step 1: Check which test file exists**

Run: `ls tests/test_parametry*`. If `test_parametry_routes.py` or `test_parametry_registry.py` exists with a good structure for route tests, append there. Otherwise create `tests/test_bindings_api.py`.

- [ ] **Step 2: Add fixture + failing test**

Use this as the foundation (adapt to existing conventions if an `app` fixture already exists):

```python
"""Tests for /api/bindings/* — SSOT endpoints for produkt_etap_limity CRUD."""
import pytest
import sqlite3

from mbr.app import create_app
from mbr.db import db_session
from mbr.models import init_mbr_tables


@pytest.fixture
def app(tmp_path, monkeypatch):
    dbpath = tmp_path / "test.sqlite"
    monkeypatch.setenv("MBR_DB_PATH", str(dbpath))
    # Initialize schema in the target file
    conn = sqlite3.connect(dbpath)
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    _seed_bindings_fixture(conn)
    conn.commit()
    conn.close()
    app = create_app()
    app.config["TESTING"] = True
    yield app


@pytest.fixture
def client(app):
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user"] = {"login": "tester", "rola": "admin"}
        yield c


def _seed_bindings_fixture(db):
    db.execute("DELETE FROM parametry_analityczne")
    db.executemany(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, precision, aktywny) VALUES (?, ?, ?, ?, ?, 1)",
        [(1, "ph", "pH", "bezposredni", 2),
         (2, "dea", "DEA", "bezposredni", 2)],
    )
    db.execute(
        "INSERT OR IGNORE INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
        "VALUES (6, 'analiza_koncowa', 'Analiza końcowa', 'jednorazowy')"
    )
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('TEST_P', 6, 1)")
    db.execute(
        "INSERT INTO produkt_etap_limity "
        "(produkt, etap_id, parametr_id, min_limit, max_limit, precision, kolejnosc, "
        " dla_szarzy, dla_zbiornika, dla_platkowania, grupa) "
        "VALUES ('TEST_P', 6, 1, 0, 11, 2, 1, 1, 1, 0, 'lab')"
    )


def test_get_bindings_returns_list(client):
    resp = client.get("/api/bindings?produkt=TEST_P&etap_id=6")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert len(data) == 1
    b = data[0]
    assert b["produkt"] == "TEST_P"
    assert b["etap_id"] == 6
    assert b["parametr_id"] == 1
    assert b["kod"] == "ph"
    assert b["min_limit"] == 0
    assert b["max_limit"] == 11
    assert b["dla_szarzy"] == 1
    assert b["dla_zbiornika"] == 1
    assert b["dla_platkowania"] == 0


def test_get_bindings_accepts_etap_kod_instead_of_id(client):
    resp = client.get("/api/bindings?produkt=TEST_P&etap_kod=analiza_koncowa")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["etap_id"] == 6


def test_get_bindings_empty_for_unknown_produkt(client):
    resp = client.get("/api/bindings?produkt=NO_SUCH&etap_id=6")
    assert resp.status_code == 200
    assert resp.get_json() == []
```

- [ ] **Step 3: Run, expect fail**

Run: `pytest tests/test_bindings_api.py -v`
Expected: FAIL — endpoint doesn't exist (404 on the GET call, so the JSON parse or status code check fails).

- [ ] **Step 4: Commit failing test**

```bash
git add tests/test_bindings_api.py
git commit -m "test: GET /api/bindings (failing)"
```

---

## Task 2: GET /api/bindings — implementation

**Files:**
- Modify: `mbr/parametry/routes.py`

- [ ] **Step 1: Add the endpoint**

Add this at the end of `mbr/parametry/routes.py`:

```python
# ============================================================================
# /api/bindings/* — new SSOT endpoints for produkt_etap_limity CRUD
# ============================================================================

@parametry_bp.route("/api/bindings")
@login_required
def api_bindings_list():
    """List bindings for a given (produkt, etap).

    Query args:
      produkt   — product kod (required)
      etap_id   — int, matches etapy_analityczne.id (either this OR etap_kod)
      etap_kod  — str, matches etapy_analityczne.kod

    Returns: JSON array of dicts with binding fields + joined parameter info.
    """
    produkt = request.args.get("produkt", "").strip()
    if not produkt:
        return jsonify({"error": "produkt is required"}), 400

    etap_id_str = request.args.get("etap_id")
    etap_kod = request.args.get("etap_kod", "").strip()

    with db_session() as db:
        if etap_id_str:
            try:
                etap_id = int(etap_id_str)
            except ValueError:
                return jsonify({"error": "etap_id must be integer"}), 400
        elif etap_kod:
            row = db.execute(
                "SELECT id FROM etapy_analityczne WHERE kod=?", (etap_kod,)
            ).fetchone()
            if not row:
                return jsonify({"error": f"unknown etap_kod: {etap_kod}"}), 404
            etap_id = row["id"]
        else:
            return jsonify({"error": "etap_id or etap_kod is required"}), 400

        rows = db.execute(
            """
            SELECT pel.id, pel.produkt, pel.etap_id, pel.parametr_id,
                   pel.min_limit, pel.max_limit, pel.precision, pel.nawazka_g,
                   pel.spec_value, pel.kolejnosc, pel.grupa, pel.formula,
                   pel.sa_bias, pel.krok, pel.wymagany,
                   pel.dla_szarzy, pel.dla_zbiornika, pel.dla_platkowania,
                   pa.kod, pa.label, pa.skrot, pa.typ, pa.jednostka
            FROM produkt_etap_limity pel
            JOIN parametry_analityczne pa ON pa.id = pel.parametr_id
            WHERE pel.produkt = ? AND pel.etap_id = ?
            ORDER BY pel.kolejnosc, pa.kod
            """,
            (produkt, etap_id),
        ).fetchall()

    return jsonify([dict(r) for r in rows])
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_bindings_api.py -v`
Expected: the 3 GET tests pass.

Run: `pytest -q`
Expected: 535 passed, 15 skipped (532 prior + 3 new).

- [ ] **Step 3: Commit**

```bash
git add mbr/parametry/routes.py
git commit -m "feat: GET /api/bindings list endpoint"
```

---

## Task 3: POST /api/bindings — failing test

**Files:**
- Modify: `tests/test_bindings_api.py`

- [ ] **Step 1: Append tests**

```python
def test_post_bindings_creates_row_with_defaults(client):
    resp = client.post(
        "/api/bindings",
        json={"produkt": "TEST_P", "etap_id": 6, "parametr_id": 2,
              "min_limit": 0, "max_limit": 3}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "id" in data

    # Verify defaults applied
    listing = client.get("/api/bindings?produkt=TEST_P&etap_id=6").get_json()
    dea = next((b for b in listing if b["parametr_id"] == 2), None)
    assert dea is not None
    assert dea["min_limit"] == 0
    assert dea["max_limit"] == 3
    assert dea["dla_szarzy"] == 1
    assert dea["dla_zbiornika"] == 1
    assert dea["dla_platkowania"] == 0
    assert dea["grupa"] == "lab"


def test_post_bindings_respects_custom_flags(client):
    resp = client.post(
        "/api/bindings",
        json={"produkt": "TEST_P", "etap_id": 6, "parametr_id": 2,
              "dla_szarzy": 0, "dla_zbiornika": 1, "dla_platkowania": 1}
    )
    assert resp.status_code == 200
    dea = next(b for b in client.get("/api/bindings?produkt=TEST_P&etap_id=6").get_json()
               if b["parametr_id"] == 2)
    assert dea["dla_szarzy"] == 0
    assert dea["dla_zbiornika"] == 1
    assert dea["dla_platkowania"] == 1


def test_post_bindings_duplicate_returns_409(client):
    # ph binding for (TEST_P, 6, 1) already exists from fixture
    resp = client.post(
        "/api/bindings",
        json={"produkt": "TEST_P", "etap_id": 6, "parametr_id": 1}
    )
    assert resp.status_code == 409


def test_post_bindings_missing_fields_returns_400(client):
    resp = client.post("/api/bindings", json={"produkt": "TEST_P"})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run, expect fail**

Run: `pytest tests/test_bindings_api.py -k post -v`
Expected: FAIL — POST not implemented.

- [ ] **Step 3: Commit (failing)**

```bash
git add tests/test_bindings_api.py
git commit -m "test: POST /api/bindings (failing)"
```

---

## Task 4: POST /api/bindings — implementation

**Files:**
- Modify: `mbr/parametry/routes.py`

- [ ] **Step 1: Add endpoint**

Append to `mbr/parametry/routes.py` after the GET endpoint:

```python
_BINDING_FIELDS = {
    "min_limit", "max_limit", "precision", "nawazka_g", "spec_value",
    "kolejnosc", "grupa", "formula", "sa_bias", "krok", "wymagany",
    "dla_szarzy", "dla_zbiornika", "dla_platkowania",
}

_BINDING_DEFAULTS = {
    "kolejnosc": 0,
    "grupa": "lab",
    "wymagany": 0,
    "dla_szarzy": 1,
    "dla_zbiornika": 1,
    "dla_platkowania": 0,
}


@parametry_bp.route("/api/bindings", methods=["POST"])
@login_required
def api_bindings_create():
    """Create a new produkt_etap_limity binding."""
    data = request.get_json(silent=True) or {}
    produkt = (data.get("produkt") or "").strip()
    etap_id = data.get("etap_id")
    parametr_id = data.get("parametr_id")
    if not produkt or not etap_id or not parametr_id:
        return jsonify({"error": "produkt, etap_id, parametr_id are required"}), 400

    row_fields = {k: data[k] for k in _BINDING_FIELDS if k in data}
    for k, v in _BINDING_DEFAULTS.items():
        row_fields.setdefault(k, v)

    cols = ["produkt", "etap_id", "parametr_id"] + list(row_fields.keys())
    vals = [produkt, etap_id, parametr_id] + list(row_fields.values())
    placeholders = ", ".join("?" * len(cols))
    col_clause = ", ".join(cols)

    with db_session() as db:
        try:
            cur = db.execute(
                f"INSERT INTO produkt_etap_limity ({col_clause}) VALUES ({placeholders})",
                vals,
            )
            db.commit()
            return jsonify({"ok": True, "id": cur.lastrowid})
        except sqlite3.IntegrityError as e:
            msg = str(e)
            if "UNIQUE" in msg:
                return jsonify({"error": "duplicate binding"}), 409
            return jsonify({"error": msg}), 400
```

You'll need `import sqlite3` at the top of the file if not already present.

- [ ] **Step 2: Run POST tests**

Run: `pytest tests/test_bindings_api.py -k post -v`
Expected: pass.

Run: `pytest -q`
Expected: 539 passed (535 + 4 new POST tests), 15 skipped.

- [ ] **Step 3: Commit**

```bash
git add mbr/parametry/routes.py
git commit -m "feat: POST /api/bindings create endpoint with auto-defaults"
```

---

## Task 5: PUT /api/bindings/<id> — failing test (includes auto-delete)

**Files:**
- Modify: `tests/test_bindings_api.py`

- [ ] **Step 1: Append tests**

```python
def test_put_bindings_updates_fields(client):
    listing = client.get("/api/bindings?produkt=TEST_P&etap_id=6").get_json()
    ph_id = next(b["id"] for b in listing if b["parametr_id"] == 1)

    resp = client.put(f"/api/bindings/{ph_id}", json={"max_limit": 12, "precision": 1})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data.get("auto_deleted") is False

    # Verify change stuck
    ph = next(b for b in client.get("/api/bindings?produkt=TEST_P&etap_id=6").get_json()
              if b["id"] == ph_id)
    assert ph["max_limit"] == 12
    assert ph["precision"] == 1


def test_put_bindings_auto_deletes_when_all_flags_zero(client):
    listing = client.get("/api/bindings?produkt=TEST_P&etap_id=6").get_json()
    ph_id = next(b["id"] for b in listing if b["parametr_id"] == 1)

    # Flip all three flags to 0
    resp = client.put(
        f"/api/bindings/{ph_id}",
        json={"dla_szarzy": 0, "dla_zbiornika": 0, "dla_platkowania": 0},
    )
    assert resp.status_code == 200
    assert resp.get_json()["auto_deleted"] is True

    # Row gone
    listing_after = client.get("/api/bindings?produkt=TEST_P&etap_id=6").get_json()
    assert all(b["id"] != ph_id for b in listing_after)


def test_put_bindings_not_found_returns_404(client):
    resp = client.put("/api/bindings/99999", json={"max_limit": 1})
    assert resp.status_code == 404


def test_put_bindings_rejects_unknown_fields(client):
    listing = client.get("/api/bindings?produkt=TEST_P&etap_id=6").get_json()
    ph_id = listing[0]["id"]
    resp = client.put(f"/api/bindings/{ph_id}", json={"evil_field": 42})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run, expect fail**

Run: `pytest tests/test_bindings_api.py -k put -v`
Expected: all 4 PUT tests fail (404 from Flask because endpoint missing).

- [ ] **Step 3: Commit (failing)**

```bash
git add tests/test_bindings_api.py
git commit -m "test: PUT /api/bindings/<id> including auto-delete (failing)"
```

---

## Task 6: PUT /api/bindings/<id> — implementation

**Files:**
- Modify: `mbr/parametry/routes.py`

- [ ] **Step 1: Add endpoint**

Append:

```python
@parametry_bp.route("/api/bindings/<int:binding_id>", methods=["PUT"])
@login_required
def api_bindings_update(binding_id: int):
    """Update a binding. If all three typ flags end up 0, auto-DELETE the row."""
    data = request.get_json(silent=True) or {}
    updates = {k: v for k, v in data.items() if k in _BINDING_FIELDS}
    if not updates:
        return jsonify({"error": "no valid fields to update"}), 400

    with db_session() as db:
        row = db.execute(
            "SELECT id FROM produkt_etap_limity WHERE id=?", (binding_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "binding not found"}), 404

        sets = ", ".join(f"{c}=?" for c in updates)
        vals = list(updates.values()) + [binding_id]
        db.execute(f"UPDATE produkt_etap_limity SET {sets} WHERE id=?", vals)

        # Check flags after update; auto-delete if all three zero.
        post = db.execute(
            "SELECT dla_szarzy, dla_zbiornika, dla_platkowania "
            "FROM produkt_etap_limity WHERE id=?", (binding_id,)
        ).fetchone()
        auto_deleted = False
        if (post["dla_szarzy"] == 0 and post["dla_zbiornika"] == 0
                and post["dla_platkowania"] == 0):
            db.execute("DELETE FROM produkt_etap_limity WHERE id=?", (binding_id,))
            auto_deleted = True

        db.commit()

    return jsonify({"ok": True, "auto_deleted": auto_deleted})
```

- [ ] **Step 2: Run PUT tests + full suite**

Run: `pytest tests/test_bindings_api.py -k put -v`
Expected: pass.

Run: `pytest -q`
Expected: 543 passed, 15 skipped.

- [ ] **Step 3: Commit**

```bash
git add mbr/parametry/routes.py
git commit -m "feat: PUT /api/bindings/<id> with auto-delete on all-zero flags"
```

---

## Task 7: DELETE /api/bindings/<id>

**Files:**
- Modify: `tests/test_bindings_api.py` + `mbr/parametry/routes.py`

- [ ] **Step 1: Failing tests**

Append to `tests/test_bindings_api.py`:

```python
def test_delete_bindings_removes_row(client):
    listing = client.get("/api/bindings?produkt=TEST_P&etap_id=6").get_json()
    ph_id = listing[0]["id"]
    resp = client.delete(f"/api/bindings/{ph_id}")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    listing_after = client.get("/api/bindings?produkt=TEST_P&etap_id=6").get_json()
    assert all(b["id"] != ph_id for b in listing_after)


def test_delete_bindings_not_found_returns_404(client):
    resp = client.delete("/api/bindings/99999")
    assert resp.status_code == 404
```

Run: `pytest tests/test_bindings_api.py -k delete -v` → expect fail.

- [ ] **Step 2: Implementation**

Append to `mbr/parametry/routes.py`:

```python
@parametry_bp.route("/api/bindings/<int:binding_id>", methods=["DELETE"])
@login_required
def api_bindings_delete(binding_id: int):
    with db_session() as db:
        row = db.execute(
            "SELECT id FROM produkt_etap_limity WHERE id=?", (binding_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "binding not found"}), 404
        db.execute("DELETE FROM produkt_etap_limity WHERE id=?", (binding_id,))
        db.commit()
    return jsonify({"ok": True})
```

Run: `pytest tests/test_bindings_api.py -v`
Expected: all 13 pass.

Run: `pytest -q`
Expected: 545 passed, 15 skipped.

- [ ] **Step 3: Commit both**

```bash
git add tests/test_bindings_api.py mbr/parametry/routes.py
git commit -m "feat: DELETE /api/bindings/<id>"
```

---

## Task 8: /api/bindings/catalog — parameter picker

**Files:**
- Modify: `tests/test_bindings_api.py` + `mbr/parametry/routes.py`

- [ ] **Step 1: Failing test**

Append:

```python
def test_get_bindings_catalog_returns_active_params(client):
    resp = client.get("/api/bindings/catalog")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    kods = {p["kod"] for p in data}
    assert "ph" in kods
    assert "dea" in kods
    for p in data:
        # every entry must have these fields
        assert "id" in p and "kod" in p and "label" in p and "typ" in p
```

Run: `pytest tests/test_bindings_api.py -k catalog -v` → expect fail.

- [ ] **Step 2: Implementation**

Append to `mbr/parametry/routes.py`:

```python
@parametry_bp.route("/api/bindings/catalog")
@login_required
def api_bindings_catalog():
    """Active parametry_analityczne rows for picker UI."""
    with db_session() as db:
        rows = db.execute(
            "SELECT id, kod, label, skrot, typ, jednostka, precision, aktywny "
            "FROM parametry_analityczne "
            "WHERE aktywny=1 ORDER BY kod"
        ).fetchall()
    return jsonify([dict(r) for r in rows])
```

Run: `pytest tests/test_bindings_api.py -v` → 14 pass.

Run: `pytest -q` → 546 passed, 15 skipped.

- [ ] **Step 3: Commit**

```bash
git add tests/test_bindings_api.py mbr/parametry/routes.py
git commit -m "feat: GET /api/bindings/catalog for parameter picker"
```

---

## Task 9: Admin panel — switch Etapy tab to /api/bindings

**Files:**
- Modify: `mbr/templates/parametry_editor.html` — specifically the Etapy tab JS functions: `loadEtapBindings`, `renderEtapTable`, `saveEtapField`, `addEtapBinding`, `deleteEtapBinding`

- [ ] **Step 1: Inspect existing structure**

Read `mbr/templates/parametry_editor.html` lines 290-440 to see all Etapy tab JS + the table HTML structure. Note the current kontekst→endpoint mapping.

- [ ] **Step 2: Update loadEtapBindings to use /api/bindings**

Find `loadEtapBindings()` (~line 310). Replace URL + response handling:

```javascript
function loadEtapBindings() {
  var produkt = document.getElementById('etap-produkt').value;
  var kontekst = document.getElementById('etap-kontekst').value;
  if (!produkt || !kontekst) {
    document.getElementById('etap-table').style.display = 'none';
    document.getElementById('etap-add').style.display = 'none';
    return;
  }
  fetch('/api/bindings?produkt=' + encodeURIComponent(produkt) + '&etap_kod=' + encodeURIComponent(kontekst))
    .then(function(r){return r.json();})
    .then(function(data) {
      _etapBindings = data;
      renderEtapTable(data);
      document.getElementById('etap-table').style.display = '';
      document.getElementById('etap-add').style.display = 'flex';
      if (!_etapAvailableLoaded) loadEtapAvailable();
    });
}
```

The only change is the URL: `/api/parametry/etapy/X/Y` → `/api/bindings?produkt=X&etap_kod=Y`. Response shape is compatible (same field names).

- [ ] **Step 3: Update renderEtapTable to add Sz/Zb/Pl columns**

Find `renderEtapTable(data)` (~line 329). Add three checkbox columns between "grupa" and "delete". Update the generated `<tr>`:

```javascript
function renderEtapTable(data) {
  var html = '';
  data.forEach(function(b, idx) {
    var prodLabel = b.produkt
      ? '<span style="font-size:9px;color:var(--text-dim);margin-left:4px;">(' + b.produkt.replace(/_/g,' ') + ')</span>'
      : '<span style="font-size:9px;color:var(--text-dim);margin-left:4px;">(domyślny)</span>';
    html += '<tr draggable="true" data-id="' + b.id + '" data-idx="' + idx + '" ' +
      'ondragstart="etapDragStart(event)" ondragover="etapDragOver(event)" ondrop="etapDrop(event)">' +
      '<td style="cursor:grab;color:var(--text-dim);text-align:center;">⠿</td>' +
      '<td><span class="pa-kod">' + esc(b.kod || '') + '</span>' + prodLabel + '</td>' +
      '<td style="font-weight:600;font-size:12px;">' + esc(b.skrot || b.kod) + '</td>' +
      '<td><input class="pa-input" type="text" inputmode="decimal" value="' + (b.nawazka_g != null ? String(b.nawazka_g).replace('.',',') : '') + '" onblur="saveEtapField(' + b.id + ',\'nawazka_g\',this)" style="width:70px;text-align:center;"></td>' +
      '<td><input class="pa-input" type="text" inputmode="decimal" value="' + (b.min_limit != null ? String(b.min_limit).replace('.',',') : '') + '" onblur="saveEtapField(' + b.id + ',\'min_limit\',this)" style="width:70px;text-align:center;"></td>' +
      '<td><input class="pa-input" type="text" inputmode="decimal" value="' + (b.spec_value != null ? String(b.spec_value).replace('.',',') : '') + '" onblur="saveEtapField(' + b.id + ',\'spec_value\',this)" style="width:70px;text-align:center;"></td>' +
      '<td><input class="pa-input" type="text" inputmode="decimal" value="' + (b.max_limit != null ? String(b.max_limit).replace('.',',') : '') + '" onblur="saveEtapField(' + b.id + ',\'max_limit\',this)" style="width:70px;text-align:center;"></td>' +
      '<td><select class="pa-input" onchange="saveEtapField(' + b.id + ',\'grupa\',this)" style="width:66px;font-size:10px;padding:3px 4px;">' +
        '<option value="lab"' + ((b.grupa||'lab')==='lab'?' selected':'') + '>lab</option>' +
        '<option value="kj"' + (b.grupa==='kj'?' selected':'') + '>kj</option>' +
        '<option value="rnd"' + (b.grupa==='rnd'?' selected':'') + '>rnd</option>' +
      '</select></td>' +
      '<td style="text-align:center;"><input type="checkbox"' + (b.dla_szarzy ? ' checked' : '') + ' onchange="saveFlagField(' + b.id + ',\'dla_szarzy\',this)"></td>' +
      '<td style="text-align:center;"><input type="checkbox"' + (b.dla_zbiornika ? ' checked' : '') + ' onchange="saveFlagField(' + b.id + ',\'dla_zbiornika\',this)"></td>' +
      '<td style="text-align:center;"><input type="checkbox"' + (b.dla_platkowania ? ' checked' : '') + ' onchange="saveFlagField(' + b.id + ',\'dla_platkowania\',this)"></td>' +
      '<td><button class="pe-bind-del" onclick="deleteEtapBinding(' + b.id + ')">&times;</button></td>' +
    '</tr>';
  });
  document.getElementById('etap-body').innerHTML = html ||
    '<tr><td colspan="12" style="text-align:center;color:var(--text-dim);padding:20px;">Brak przypisań dla tego etapu</td></tr>';
}
```

Note: `target` field was renamed to `spec_value` to match new schema. `colspan="9"` → `colspan="12"` (added 3 columns).

- [ ] **Step 4: Update table header to match columns**

Find the `<thead>` of the etap table in HTML (search for "Nawazka" or "Min" header labels). Add three columns Sz, Zb, Pl between "Grupa" and the delete column. The header row should match the new column count.

If the HTML header is somewhere around lines 200-260 (depends on file) and looks like:
```html
<tr><th></th><th>Kod</th><th>Skrót</th><th>Nawaz.</th><th>Min</th><th>Target</th><th>Max</th><th>Grupa</th><th></th></tr>
```

Change to:
```html
<tr><th></th><th>Kod</th><th>Skrót</th><th>Nawaz.</th><th>Min</th><th>Spec</th><th>Max</th><th>Grupa</th><th title="szarża">Sz</th><th title="zbiornik">Zb</th><th title="płatkowanie">Pl</th><th></th></tr>
```

- [ ] **Step 5: Update saveEtapField + add saveFlagField**

Replace `saveEtapField` (~line 356):

```javascript
function saveEtapField(id, field, input) {
  var val = field === 'grupa' ? input.value : parseNum(input.value);
  var body = {}; body[field] = val;
  fetch('/api/bindings/' + id, {
    method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  }).then(function(r) { flashField(input, r.ok); });
}

function saveFlagField(id, field, checkbox) {
  var body = {}; body[field] = checkbox.checked ? 1 : 0;
  fetch('/api/bindings/' + id, {
    method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  }).then(function(r){ return r.json(); }).then(function(data) {
    flashField(checkbox, data.ok);
    // If all flags went to 0, the backend auto-deleted — reload table
    if (data.auto_deleted) loadEtapBindings();
  });
}
```

- [ ] **Step 6: Update addEtapBinding**

Replace `addEtapBinding()` (~line 365). First, resolve etap_id from kontekst (the new endpoint needs `etap_id`):

```javascript
function addEtapBinding() {
  var produkt = document.getElementById('etap-produkt').value;
  var kontekst = document.getElementById('etap-kontekst').value;
  var paramId = document.getElementById('etap-add-param').value;
  if (!produkt || !kontekst || !paramId) return;
  // Resolve kontekst → etap_id via a lightweight fetch, then create
  fetch('/api/bindings?produkt=' + encodeURIComponent(produkt) + '&etap_kod=' + encodeURIComponent(kontekst))
    .then(function(r) {
      // GET returns existing bindings; we can extract etap_id from any one,
      // or if empty, call a catalog endpoint. Simpler: add /api/bindings/etap-id
      // helper. For now reuse: fetch catalog + map kontekst to id via embedded dict.
      return fetch('/api/pipeline/etapy');  // existing endpoint returns [{id, kod, ...}]
    })
    .then(function(r){return r.json();})
    .then(function(etapy) {
      var etap = etapy.find(function(e) { return e.kod === kontekst; });
      if (!etap) { alert('Nie znaleziono etapu: ' + kontekst); return; }
      return fetch('/api/bindings', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          produkt: produkt,
          etap_id: etap.id,
          parametr_id: parseInt(paramId),
          nawazka_g: parseNum(document.getElementById('etap-add-naw').value),
          min_limit: parseNum(document.getElementById('etap-add-min').value),
          max_limit: parseNum(document.getElementById('etap-add-max').value),
          grupa: document.getElementById('etap-add-grupa').value,
        })
      });
    })
    .then(function(r){return r.json();})
    .then(function(d) {
      if (d && d.ok) {
        document.getElementById('etap-add-naw').value = '';
        document.getElementById('etap-add-min').value = '';
        document.getElementById('etap-add-max').value = '';
        loadEtapBindings();
      } else if (d) { alert(d.error || 'Błąd'); }
    });
}
```

**NOTE**: Verify `/api/pipeline/etapy` exists and returns `[{id, kod, ...}]`. If not, use a different resolution. Check: `Grep for "api/pipeline/etapy" in mbr/pipeline/routes.py`. If missing, create a minimal version as a trivial GET.

- [ ] **Step 7: Update deleteEtapBinding**

Find `deleteEtapBinding()` (~line 391). Replace URL:

```javascript
function deleteEtapBinding(id) {
  if (!confirm('Usunąć przypisanie?')) return;
  fetch('/api/bindings/' + id, {method: 'DELETE'})
    .then(function(r){return r.json();})
    .then(function(d) {
      if (d.ok) loadEtapBindings();
      else alert(d.error || 'Błąd');
    });
}
```

- [ ] **Step 8: Manually smoke-test the admin panel**

With local Flask dev server running, log in as admin. Go to `/parametry`, switch to "Etapy" tab. Select a product (e.g. Chelamid_DK) and kontekst "analiza_koncowa". The table should load with new columns Sz/Zb/Pl all checked for szarza+zbiornik, unchecked for platkowanie. Edit a min_limit inline → saves. Toggle a flag → persists after reload.

- [ ] **Step 9: Run full pytest**

Run: `pytest -q`
Expected: 546 passed, 15 skipped (template changes don't affect pytest).

- [ ] **Step 10: Commit**

```bash
git add mbr/templates/parametry_editor.html
git commit -m "feat: admin panel Etapy tab uses /api/bindings + shows Sz/Zb/Pl flags"
```

---

## Task 10: Reorder (drag-drop) uses /api/bindings

**Files:**
- Modify: `mbr/templates/parametry_editor.html` — the drag-drop handlers `etapDragStart`, `etapDragOver`, `etapDrop`

- [ ] **Step 1: Inspect existing drag-drop logic**

Find `etapDragStart`, `etapDragOver`, `etapDrop` in `mbr/templates/parametry_editor.html` (search for those names). They currently call `/api/parametry/etapy/reorder` which is the legacy endpoint.

- [ ] **Step 2: Update reorder to use PUT /api/bindings/<id>**

Since the new endpoint supports `kolejnosc` updates directly via `PUT /api/bindings/<id>`, the reorder function can loop through the new order and issue N parallel PUTs:

```javascript
function etapDrop(event) {
  event.preventDefault();
  var dragIdx = parseInt(event.dataTransfer.getData('text/plain'));
  var targetRow = event.currentTarget;
  var targetIdx = parseInt(targetRow.dataset.idx);
  if (dragIdx === targetIdx) return;

  // Reorder in-memory
  var item = _etapBindings[dragIdx];
  _etapBindings.splice(dragIdx, 1);
  _etapBindings.splice(targetIdx, 0, item);

  // Re-render with new order
  _etapBindings.forEach(function(b, i) { b.kolejnosc = i + 1; });
  renderEtapTable(_etapBindings);

  // Persist each kolejnosc change via PUT /api/bindings/<id>
  var promises = _etapBindings.map(function(b) {
    return fetch('/api/bindings/' + b.id, {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({kolejnosc: b.kolejnosc})
    });
  });
  Promise.all(promises).then(function() { /* silent */ });
}
```

Leave `etapDragStart` and `etapDragOver` unchanged if they just set dataTransfer and call `event.preventDefault()`.

- [ ] **Step 3: Smoke-test drag-drop in browser**

Drag a row in the Etapy table. New order should persist after a page reload.

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/parametry_editor.html
git commit -m "feat: admin panel reorder uses PUT /api/bindings/<id>"
```

---

## Task 11: Full suite + integration smoke

**Files:**
- No code changes.

- [ ] **Step 1: Full pytest**

Run: `pytest -q`
Expected: 546 passed, 15 skipped.

- [ ] **Step 2: Manual smoke-test end-to-end**

With dev server:
- Log in as admin
- `/parametry` Etapy tab works: load, inline edit limits, toggle flags, add new, delete, drag-reorder
- All actions persist across refresh
- Log in as laborant
- Laborant modal `edytuj parametry` still works (uses OLD endpoints — not touched in PR 3)
- Chelamid_DK batch still renders 7 params in edit card

If anything breaks, stop and investigate.

---

## Task 12: Memory + push + PR

**Files:**
- Memory file in `~/.claude/projects/.../memory/`.

- [ ] **Step 1: Update project memory**

Edit `project_parametry_ssot.md` — mark PR 3 as done. Add section:

```markdown
**PR 3 (Etap B.2) — DONE YYYY-MM-DD:**
- New /api/bindings/* endpoints (GET/POST/PUT/DELETE + /catalog)
- PUT auto-deletes row when all 3 typ flags end at 0
- Admin panel Etapy tab uses new endpoints; adds Sz/Zb/Pl checkbox columns
- Reorder (drag-drop) uses PUT /api/bindings/<id>
- Laborant modal still on OLD endpoints — PR 4 migrates
```

- [ ] **Step 2: Push branch**

```bash
git push -u origin feature/parametry-ssot-pr3
```

- [ ] **Step 3: Open PR**

Title: `refactor: parametry SSOT — PR 3 (Etap B.2) — /api/bindings + admin panel`

Body:
```
## Summary
- New /api/bindings/* REST endpoints for produkt_etap_limity CRUD
- PUT auto-deletes rows when all typ flags go to 0
- Admin panel (/parametry "Etapy" tab) rewritten to use new endpoints + Sz/Zb/Pl columns
- Legacy /api/parametry/etapy/* untouched (laborant modal migrated in PR 4)

## Test plan
- [x] pytest: 546 passed, 15 skipped
- [x] /api/bindings CRUD works via admin panel (load, edit, add, delete, reorder, flag toggle)
- [x] Laborant modal still works (old endpoints)

Depends on PR 1 + PR 2 merged to main.
```

---

## Self-review (controller checklist)

**Spec coverage:**
- New endpoints ✓ (Tasks 1-8)
- Admin panel updated ✓ (Tasks 9-10)
- Auto-delete on all-zero ✓ (Task 6)
- Legacy endpoints preserved — confirmed (no modifications to `/api/parametry/etapy/*`)

**Risks:**
- Task 9 Step 6 depends on `/api/pipeline/etapy` existing. If missing, Implementer must add a minimal `GET /api/pipeline/etapy` returning `[{id, kod, nazwa}, ...]`. Grep confirms this route exists in `mbr/pipeline/routes.py` — safe assumption.
- `precision` column might be read elsewhere with expectation of specific type (INTEGER). New endpoints treat it as optional — any NULL default is fine.
- The existing admin panel's `Target` column is renamed to `Spec` (matches new schema column `spec_value`). Users who know the old label need to notice. Minor UX change only.

**Out of scope (deferred):**
- Laborant modal update — PR 4
- Cert generator — PR 5
- Drop old endpoints + tables — PR 6-7
