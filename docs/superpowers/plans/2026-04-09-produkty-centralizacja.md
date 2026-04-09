# Centralizacja produktów — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `produkty` table the single source of truth for all product data — types, names, codes, certificate metadata — used by the entire application.

**Architecture:** Extend `produkty` table with cert_config fields (display_name, spec_number, etc.), migrate data from cert_config.json, add "Produkty" tab to `/parametry` editor, adapt certificate generator to read product metadata from DB. Auto-sync with `mbr_templates` on startup.

**Tech Stack:** Python/Flask, SQLite, Jinja2, vanilla JS, pytest

**Spec:** `docs/superpowers/specs/2026-04-09-produkty-centralizacja-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `mbr/models.py` | Modify | Add migrations for new columns + auto-sync produkty↔mbr_templates |
| `mbr/parametry/routes.py` | Modify | Move produkty CRUD endpoints here, extend with new fields, add to template context |
| `mbr/zbiorniki/routes.py` | Modify | Remove produkty endpoints (replaced by parametry/routes.py) |
| `mbr/templates/parametry_editor.html` | Modify | Add fourth "Produkty" tab |
| `mbr/certs/generator.py` | Modify | Read product metadata from DB instead of cert_config.json |
| `scripts/migrate_produkty.py` | Create | One-time migration: cert_config.json product metadata → produkty table |
| `tests/test_produkty.py` | Create | Tests for produkty CRUD + generator with DB product data |

---

### Task 1: DB migrations — extend produkty table

**Files:**
- Modify: `mbr/models.py`
- Create: `tests/test_produkty.py`

- [ ] **Step 1: Write test for new columns**

```python
# tests/test_produkty.py
"""Tests for produkty table extensions."""

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


def test_produkty_has_new_columns(db):
    db.execute(
        "INSERT INTO produkty (nazwa, kod, display_name, spec_number, cas_number, "
        "expiry_months, opinion_pl, opinion_en) "
        "VALUES ('Test_Prod', 'TP', 'Test Prod', 'P100', '123-45-6', 24, 'OK', 'OK EN')"
    )
    row = db.execute("SELECT * FROM produkty WHERE nazwa='Test_Prod'").fetchone()
    assert row["display_name"] == "Test Prod"
    assert row["spec_number"] == "P100"
    assert row["cas_number"] == "123-45-6"
    assert row["expiry_months"] == 24
    assert row["opinion_pl"] == "OK"
    assert row["opinion_en"] == "OK EN"


def test_produkty_expiry_default(db):
    db.execute("INSERT INTO produkty (nazwa) VALUES ('Default_Prod')")
    row = db.execute("SELECT expiry_months FROM produkty WHERE nazwa='Default_Prod'").fetchone()
    assert row["expiry_months"] == 12


def test_produkty_auto_sync_from_mbr(db):
    """Products in mbr_templates get auto-inserted into produkty."""
    db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "dt_utworzenia) VALUES ('NewProd_X', 1, 'active', '[]', '{}', datetime('now'))"
    )
    db.commit()
    # Re-run init to trigger sync
    init_mbr_tables(db)
    row = db.execute("SELECT * FROM produkty WHERE nazwa='NewProd_X'").fetchone()
    assert row is not None
    assert row["display_name"] == "NewProd X"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tbk/Desktop/aa && python -m pytest tests/test_produkty.py -v`
Expected: FAIL — `display_name` column doesn't exist

- [ ] **Step 3: Add migrations to models.py**

Add after the existing produkty-related migrations (after the `typy` seed block around line 236):

```python
    # Migration: add certificate metadata columns to produkty
    for col, coldef in [
        ("display_name", "TEXT"),
        ("spec_number", "TEXT"),
        ("cas_number", "TEXT"),
        ("expiry_months", "INTEGER DEFAULT 12"),
        ("opinion_pl", "TEXT"),
        ("opinion_en", "TEXT"),
    ]:
        try:
            db.execute(f"ALTER TABLE produkty ADD COLUMN {col} {coldef}")
            db.commit()
        except Exception:
            pass

    # Auto-generate display_name from nazwa where missing
    db.execute("""
        UPDATE produkty SET display_name = REPLACE(nazwa, '_', ' ')
        WHERE display_name IS NULL OR display_name = ''
    """)
    db.commit()

    # Auto-sync: products in mbr_templates but not in produkty
    db.execute("""
        INSERT OR IGNORE INTO produkty (nazwa, display_name)
        SELECT DISTINCT produkt, REPLACE(produkt, '_', ' ')
        FROM mbr_templates
        WHERE produkt NOT IN (SELECT nazwa FROM produkty)
    """)
    db.commit()
```

Also update the CREATE TABLE for `produkty` (for fresh DBs) to include new columns inline:

```sql
CREATE TABLE IF NOT EXISTS produkty (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazwa TEXT UNIQUE NOT NULL,
    kod TEXT,
    aktywny INTEGER DEFAULT 1,
    typy TEXT DEFAULT '["szarza"]',
    display_name TEXT,
    spec_number TEXT,
    cas_number TEXT,
    expiry_months INTEGER DEFAULT 12,
    opinion_pl TEXT,
    opinion_en TEXT
);
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tbk/Desktop/aa && python -m pytest tests/test_produkty.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add mbr/models.py tests/test_produkty.py
git commit -m "feat: extend produkty table with cert metadata columns + auto-sync"
```

---

### Task 2: Migration script — cert_config.json → produkty

**Files:**
- Create: `scripts/migrate_produkty.py`
- Add tests to: `tests/test_produkty.py`

- [ ] **Step 1: Write test for migration**

Add to `tests/test_produkty.py`:

```python
SAMPLE_CONFIG = {
    "products": {
        "Test_Prod": {
            "display_name": "Test Prod",
            "spec_number": "P100",
            "cas_number": "123-45-6",
            "expiry_months": 24,
            "opinion_pl": "Produkt OK",
            "opinion_en": "Product OK",
            "parameters": [],
            "variants": []
        },
        "Other_Prod": {
            "display_name": "Other Prod",
            "spec_number": "P200",
            "cas_number": "",
            "expiry_months": 6,
            "opinion_pl": "Dobry",
            "opinion_en": "Good",
            "parameters": [],
            "variants": []
        }
    }
}


def test_migrate_produkty(db):
    # Pre-seed one product
    db.execute("INSERT INTO produkty (nazwa, kod) VALUES ('Test_Prod', 'TP')")
    db.commit()
    from scripts.migrate_produkty import migrate
    stats = migrate(db, SAMPLE_CONFIG)
    assert stats["updated"] >= 1
    row = db.execute("SELECT * FROM produkty WHERE nazwa='Test_Prod'").fetchone()
    assert row["display_name"] == "Test Prod"
    assert row["spec_number"] == "P100"
    assert row["cas_number"] == "123-45-6"
    assert row["expiry_months"] == 24
    assert row["opinion_pl"] == "Produkt OK"


def test_migrate_produkty_creates_missing(db):
    """Products in cert_config but not in produkty get created."""
    from scripts.migrate_produkty import migrate
    migrate(db, SAMPLE_CONFIG)
    row = db.execute("SELECT * FROM produkty WHERE nazwa='Other_Prod'").fetchone()
    assert row is not None
    assert row["spec_number"] == "P200"
    assert row["expiry_months"] == 6


def test_migrate_produkty_coalesce(db):
    """Existing values not overwritten."""
    db.execute(
        "INSERT INTO produkty (nazwa, display_name) VALUES ('Test_Prod', 'Custom Name')"
    )
    db.commit()
    from scripts.migrate_produkty import migrate
    migrate(db, SAMPLE_CONFIG)
    row = db.execute("SELECT display_name FROM produkty WHERE nazwa='Test_Prod'").fetchone()
    assert row["display_name"] == "Custom Name"


def test_migrate_produkty_idempotent(db):
    from scripts.migrate_produkty import migrate
    migrate(db, SAMPLE_CONFIG)
    migrate(db, SAMPLE_CONFIG)
    count = db.execute("SELECT COUNT(*) as c FROM produkty").fetchone()["c"]
    assert count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tbk/Desktop/aa && python -m pytest tests/test_produkty.py::test_migrate_produkty -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write migration script**

```python
# scripts/migrate_produkty.py
"""One-time migration: cert_config.json product metadata → produkty table.

Usage:
    python scripts/migrate_produkty.py [--dry-run]
"""

import json
import sys
from pathlib import Path


def migrate(db, config: dict, dry_run: bool = False) -> dict:
    """Migrate product metadata from cert_config into produkty table."""
    products = config.get("products", {})
    stats = {"updated": 0, "created": 0}

    for prod_key, prod_cfg in products.items():
        display_name = prod_cfg.get("display_name", "")
        spec_number = prod_cfg.get("spec_number", "")
        cas_number = prod_cfg.get("cas_number", "")
        expiry_months = prod_cfg.get("expiry_months", 12)
        opinion_pl = prod_cfg.get("opinion_pl", "")
        opinion_en = prod_cfg.get("opinion_en", "")

        row = db.execute("SELECT id FROM produkty WHERE nazwa = ?", (prod_key,)).fetchone()
        if row:
            # COALESCE update — don't overwrite existing non-empty values
            db.execute("""
                UPDATE produkty SET
                    display_name = COALESCE(NULLIF(display_name, ''), ?),
                    spec_number  = COALESCE(NULLIF(spec_number, ''), ?),
                    cas_number   = COALESCE(NULLIF(cas_number, ''), ?),
                    expiry_months = CASE WHEN expiry_months IS NULL OR expiry_months = 12 THEN ? ELSE expiry_months END,
                    opinion_pl   = COALESCE(NULLIF(opinion_pl, ''), ?),
                    opinion_en   = COALESCE(NULLIF(opinion_en, ''), ?)
                WHERE nazwa = ?
            """, (display_name, spec_number, cas_number, expiry_months,
                  opinion_pl, opinion_en, prod_key))
            stats["updated"] += 1
        else:
            db.execute("""
                INSERT INTO produkty (nazwa, display_name, spec_number, cas_number,
                    expiry_months, opinion_pl, opinion_en)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (prod_key, display_name, spec_number, cas_number,
                  expiry_months, opinion_pl, opinion_en))
            stats["created"] += 1

    if not dry_run:
        db.commit()
    else:
        db.rollback()

    return stats


def main():
    dry_run = "--dry-run" in sys.argv
    project_root = Path(__file__).resolve().parent.parent
    config_path = project_root / "mbr" / "cert_config.json"
    db_path = project_root / "data" / "batch_db_v4.sqlite"

    if not config_path.exists():
        print(f"ERROR: {config_path} not found")
        sys.exit(1)

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    print(f"Migrating {len(config.get('products', {}))} products...")
    if dry_run:
        print("(DRY RUN)")

    stats = migrate(conn, config, dry_run=dry_run)
    print(f"Done: {stats['updated']} updated, {stats['created']} created")
    conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/tbk/Desktop/aa && python -m pytest tests/test_produkty.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_produkty.py tests/test_produkty.py
git commit -m "feat: migration script cert_config.json product metadata → produkty"
```

---

### Task 3: Move produkty API endpoints to parametry/routes.py

**Files:**
- Modify: `mbr/parametry/routes.py`
- Modify: `mbr/zbiorniki/routes.py`
- Add tests to: `tests/test_produkty.py`

- [ ] **Step 1: Write API tests**

Add to `tests/test_produkty.py`:

```python
from flask import Flask


@pytest.fixture
def app(db):
    from mbr.parametry import parametry_bp
    app = Flask(__name__)
    app.secret_key = "test"

    import mbr.parametry.routes as _routes
    _orig = _routes.db_session

    from contextlib import contextmanager
    @contextmanager
    def _test_db():
        yield db

    _routes.db_session = _test_db
    app.register_blueprint(parametry_bp)

    # Seed products
    db.execute("INSERT INTO produkty (nazwa, kod, typy, display_name) VALUES ('Prod_A', 'PA', '[\"szarza\"]', 'Prod A')")
    db.execute("INSERT INTO produkty (nazwa, kod, typy, display_name, aktywny) VALUES ('Prod_B', 'PB', '[\"zbiornik\"]', 'Prod B', 0)")
    db.execute("INSERT INTO produkty (nazwa, kod, typy, display_name) VALUES ('Prod_C', 'PC', '[\"szarza\",\"zbiornik\"]', 'Prod C')")
    db.commit()
    yield app
    _routes.db_session = _orig


@pytest.fixture
def client(app):
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user"] = {"login": "admin", "rola": "admin"}
        yield c


def test_get_produkty_active_only(client):
    resp = client.get("/api/produkty")
    data = resp.get_json()
    names = [p["nazwa"] for p in data]
    assert "Prod_A" in names
    assert "Prod_C" in names
    assert "Prod_B" not in names  # inactive


def test_get_produkty_filter_typ(client):
    resp = client.get("/api/produkty?typ=zbiornik")
    data = resp.get_json()
    names = [p["nazwa"] for p in data]
    assert "Prod_C" in names
    assert "Prod_A" not in names  # szarza only


def test_update_produkty_new_fields(client, db):
    pid = db.execute("SELECT id FROM produkty WHERE nazwa='Prod_A'").fetchone()["id"]
    resp = client.put(f"/api/produkty/{pid}", json={
        "display_name": "Product Alpha",
        "spec_number": "P999",
        "expiry_months": 24,
    })
    assert resp.status_code == 200
    row = db.execute("SELECT * FROM produkty WHERE id=?", (pid,)).fetchone()
    assert row["display_name"] == "Product Alpha"
    assert row["spec_number"] == "P999"
    assert row["expiry_months"] == 24


def test_create_produkt(client, db):
    resp = client.post("/api/produkty", json={
        "nazwa": "New_Product",
        "display_name": "New Product",
        "kod": "NP",
        "typy": '["szarza","zbiornik"]',
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"]
    row = db.execute("SELECT * FROM produkty WHERE nazwa='New_Product'").fetchone()
    assert row["display_name"] == "New Product"
    assert row["typy"] == '["szarza","zbiornik"]'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tbk/Desktop/aa && python -m pytest tests/test_produkty.py::test_get_produkty_active_only -v`
Expected: FAIL — route not found (endpoints still in zbiorniki)

- [ ] **Step 3: Add produkty endpoints to parametry/routes.py**

Add to `mbr/parametry/routes.py`:

```python
# ═══ PRODUKTY ═══

@parametry_bp.route("/api/produkty")
@login_required
def api_produkty():
    """List products. ?typ= filters by typy JSON. ?all=1 includes inactive."""
    include_all = request.args.get("all") == "1"
    typ_filter = request.args.get("typ", "")
    with db_session() as db:
        sql = "SELECT * FROM produkty"
        params = []
        conditions = []
        if not include_all:
            conditions.append("aktywny = 1")
        if typ_filter:
            conditions.append("typy LIKE ?")
            params.append(f'%"{typ_filter}"%')
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY nazwa"
        rows = [dict(r) for r in db.execute(sql, params).fetchall()]
    return jsonify(rows)


@parametry_bp.route("/api/produkty", methods=["POST"])
@role_required("admin")
def api_produkty_create():
    """Create a new product."""
    data = request.get_json(silent=True) or {}
    nazwa = (data.get("nazwa") or "").strip()
    if not nazwa:
        return jsonify({"error": "nazwa required"}), 400
    display_name = data.get("display_name") or nazwa.replace("_", " ")
    with db_session() as db:
        try:
            cur = db.execute(
                "INSERT INTO produkty (nazwa, kod, display_name, typy, spec_number, "
                "cas_number, expiry_months, opinion_pl, opinion_en) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (nazwa, data.get("kod", ""), display_name,
                 data.get("typy", '["szarza"]'),
                 data.get("spec_number", ""), data.get("cas_number", ""),
                 data.get("expiry_months", 12),
                 data.get("opinion_pl", ""), data.get("opinion_en", "")),
            )
            db.commit()
        except Exception:
            return jsonify({"error": "Produkt already exists"}), 409
    return jsonify({"ok": True, "id": cur.lastrowid})


@parametry_bp.route("/api/produkty/<int:pid>", methods=["PUT"])
@role_required("admin")
def api_produkty_update(pid):
    """Update product fields."""
    data = request.get_json(silent=True) or {}
    allowed = {"kod", "display_name", "aktywny", "typy", "spec_number",
               "cas_number", "expiry_months", "opinion_pl", "opinion_en"}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates:
        return jsonify({"ok": True})
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with db_session() as db:
        db.execute(f"UPDATE produkty SET {set_clause} WHERE id = ?",
                   [*updates.values(), pid])
        db.commit()
    return jsonify({"ok": True})


@parametry_bp.route("/api/produkty/<int:pid>", methods=["DELETE"])
@role_required("admin")
def api_produkty_delete(pid):
    """Soft delete — set aktywny=0."""
    with db_session() as db:
        db.execute("UPDATE produkty SET aktywny = 0 WHERE id = ?", (pid,))
        db.commit()
    return jsonify({"ok": True})
```

- [ ] **Step 4: Remove old endpoints from zbiorniki/routes.py**

In `mbr/zbiorniki/routes.py`, remove or redirect the old produkty endpoints:
- `api_produkty()` (GET /api/produkty)
- `api_produkty_create()` (POST /api/produkty)
- `api_produkty_update()` (PUT /api/produkty/<pid>)
- `admin_produkty()` (GET /admin/produkty)

Replace with a redirect for the admin page:

```python
@zbiorniki_bp.route("/admin/produkty")
@role_required("admin")
def admin_produkty():
    return redirect(url_for("parametry.parametry_editor"))
```

Remove the three API endpoints entirely (they're now in parametry/routes.py).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/tbk/Desktop/aa && python -m pytest tests/test_produkty.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add mbr/parametry/routes.py mbr/zbiorniki/routes.py tests/test_produkty.py
git commit -m "feat: move produkty CRUD to parametry routes, extend with new fields"
```

---

### Task 4: Add "Produkty" tab to parametry editor

**Files:**
- Modify: `mbr/templates/parametry_editor.html`
- Modify: `mbr/parametry/routes.py` (pass data to template)

- [ ] **Step 1: Update parametry_editor route to pass produkty list**

In `mbr/parametry/routes.py`, modify `parametry_editor()` to pass all products:

```python
    return render_template(
        "parametry_editor.html",
        products=products, konteksty=konteksty,
        is_admin=(rola == "admin"),
        cert_products=all_products,
        # no extra data needed — produkty tab loads via fetch
    )
```

No change needed — the tab will load data via `/api/produkty?all=1` fetch.

- [ ] **Step 2: Add tab button to HTML**

In the `.pe-tabs` div, add fourth button:

```html
{% if is_admin %}
<button class="pe-tab" id="tab-prod" onclick="switchTab('prod')">Produkty</button>
{% endif %}
```

- [ ] **Step 3: Add panel-prod HTML**

After `panel-cert` closing div:

```html
{% if is_admin %}
<div id="panel-prod" style="display:none;">
  <table class="pa-table" id="prod-table">
    <thead>
      <tr>
        <th>Nazwa</th>
        <th>Display name</th>
        <th style="width:60px;">Kod</th>
        <th style="width:80px;">Spec</th>
        <th style="width:90px;">CAS</th>
        <th style="width:50px;">Ważn.</th>
        <th style="width:40px;">Sz</th>
        <th style="width:40px;">Zb</th>
        <th style="width:40px;">Pł</th>
        <th style="width:60px;">Status</th>
      </tr>
    </thead>
    <tbody id="prod-body"></tbody>
  </table>

  <div class="pa-add" id="prod-add">
    <input type="text" id="prod-add-nazwa" placeholder="Nazwa (klucz)" style="width:150px;">
    <input type="text" id="prod-add-display" placeholder="Display name" style="width:150px;">
    <input type="text" id="prod-add-kod" placeholder="Kod" style="width:60px;">
    <label style="font-size:10px;"><input type="checkbox" id="prod-add-sz" checked> Sz</label>
    <label style="font-size:10px;"><input type="checkbox" id="prod-add-zb"> Zb</label>
    <label style="font-size:10px;"><input type="checkbox" id="prod-add-pl"> Pł</label>
    <button onclick="addProdukt()">+ Dodaj</button>
  </div>
</div>
{% endif %}
```

- [ ] **Step 4: Update switchTab to handle 4 tabs**

```javascript
function switchTab(which) {
  ['bind', 'def', 'cert', 'prod'].forEach(function(t) {
    var tab = document.getElementById('tab-' + t);
    var panel = document.getElementById('panel-' + t);
    if (tab) tab.classList.toggle('pe-tab-active', t === which);
    if (panel) panel.style.display = (t === which) ? '' : 'none';
  });
  if (which === 'def' && !_paLoaded) loadDefinicje();
  if (which === 'cert' && !_certLoaded) loadCertAvailable();
  if (which === 'prod' && !_prodLoaded) loadProdukty();
}
```

- [ ] **Step 5: Add produkty tab JavaScript**

```javascript
var _prodLoaded = false;
var _prodData = [];

function loadProdukty() {
  fetch('/api/produkty?all=1').then(function(r){return r.json();}).then(function(data) {
    _prodData = data;
    _prodLoaded = true;
    renderProdTable(data);
  });
}

function renderProdTable(data) {
  var html = '';
  data.forEach(function(p) {
    var typy = [];
    try { typy = JSON.parse(p.typy || '[]'); } catch(e) {}
    var hasSz = typy.indexOf('szarza') >= 0;
    var hasZb = typy.indexOf('zbiornik') >= 0;
    var hasPl = typy.indexOf('platkowanie') >= 0;

    html += '<tr>' +
      '<td style="font-weight:600;font-size:11px;">' + esc(p.nazwa) + '</td>' +
      '<td><input class="pa-input" value="' + esc(p.display_name || '') + '" onblur="saveProdField(' + p.id + ',\'display_name\',this.value)"></td>' +
      '<td><input class="pa-input" value="' + esc(p.kod || '') + '" onblur="saveProdField(' + p.id + ',\'kod\',this.value)" style="font-family:var(--mono);font-weight:700;color:var(--teal);"></td>' +
      '<td><input class="pa-input" value="' + esc(p.spec_number || '') + '" onblur="saveProdField(' + p.id + ',\'spec_number\',this.value)"></td>' +
      '<td><input class="pa-input" value="' + esc(p.cas_number || '') + '" onblur="saveProdField(' + p.id + ',\'cas_number\',this.value)"></td>' +
      '<td><input class="pa-input" type="number" value="' + (p.expiry_months || 12) + '" onblur="saveProdField(' + p.id + ',\'expiry_months\',parseInt(this.value))" style="width:45px;text-align:center;"></td>' +
      '<td style="text-align:center;"><input type="checkbox" ' + (hasSz ? 'checked' : '') + ' onchange="saveProdTypy(' + p.id + ',this.parentNode.parentNode)"></td>' +
      '<td style="text-align:center;"><input type="checkbox" ' + (hasZb ? 'checked' : '') + ' onchange="saveProdTypy(' + p.id + ',this.parentNode.parentNode)"></td>' +
      '<td style="text-align:center;"><input type="checkbox" ' + (hasPl ? 'checked' : '') + ' onchange="saveProdTypy(' + p.id + ',this.parentNode.parentNode)"></td>' +
      '<td><button class="pa-toggle ' + (p.aktywny ? 'on' : 'off') + '" onclick="toggleProdActive(' + p.id + ',' + p.aktywny + ')">' + (p.aktywny ? 'Aktywny' : 'Ukryty') + '</button></td>' +
    '</tr>';
  });
  document.getElementById('prod-body').innerHTML = html || '<tr><td colspan="10" style="text-align:center;color:var(--text-dim);padding:20px;">Brak produktów</td></tr>';
}

function saveProdField(id, field, value) {
  var body = {}; body[field] = value;
  fetch('/api/produkty/' + id, {
    method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
}

function saveProdTypy(id, row) {
  var checks = row.querySelectorAll('input[type=checkbox]');
  var typy = [];
  if (checks[0].checked) typy.push('szarza');
  if (checks[1].checked) typy.push('zbiornik');
  if (checks[2].checked) typy.push('platkowanie');
  saveProdField(id, 'typy', JSON.stringify(typy));
}

function toggleProdActive(id, current) {
  fetch('/api/produkty/' + id, {
    method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({aktywny: current ? 0 : 1})
  }).then(function(r) { if (r.ok) loadProdukty(); });
}

function addProdukt() {
  var nazwa = document.getElementById('prod-add-nazwa').value.trim();
  if (!nazwa) return;
  var typy = [];
  if (document.getElementById('prod-add-sz').checked) typy.push('szarza');
  if (document.getElementById('prod-add-zb').checked) typy.push('zbiornik');
  if (document.getElementById('prod-add-pl').checked) typy.push('platkowanie');
  fetch('/api/produkty', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      nazwa: nazwa,
      display_name: document.getElementById('prod-add-display').value.trim() || nazwa.replace(/_/g, ' '),
      kod: document.getElementById('prod-add-kod').value.trim(),
      typy: JSON.stringify(typy),
    })
  }).then(function(r){return r.json();}).then(function(d) {
    if (d.ok) {
      document.getElementById('prod-add-nazwa').value = '';
      document.getElementById('prod-add-display').value = '';
      document.getElementById('prod-add-kod').value = '';
      loadProdukty();
    } else { alert(d.error || 'Błąd'); }
  });
}
```

- [ ] **Step 6: Test manually + run existing tests**

Run: `cd /Users/tbk/Desktop/aa && python -m pytest tests/test_produkty.py tests/test_parametry_cert.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add mbr/templates/parametry_editor.html mbr/parametry/routes.py
git commit -m "feat: add Produkty tab to parametry editor with type checkboxes"
```

---

### Task 5: Adapt certificate generator to read from produkty table

**Files:**
- Modify: `mbr/certs/generator.py`
- Add tests to: `tests/test_produkty.py`

- [ ] **Step 1: Write test**

Add to `tests/test_produkty.py`:

```python
def test_get_product_meta_from_db(db):
    """_get_product_meta reads from produkty table."""
    db.execute(
        "INSERT INTO produkty (nazwa, display_name, spec_number, cas_number, "
        "expiry_months, opinion_pl, opinion_en) "
        "VALUES ('TestP', 'Test Product', 'P999', '111-22-3', 24, 'Dobry', 'Good')"
    )
    db.commit()
    from mbr.certs.generator import _get_product_meta
    meta = _get_product_meta(db, "TestP")
    assert meta is not None
    assert meta["display_name"] == "Test Product"
    assert meta["spec_number"] == "P999"
    assert meta["cas_number"] == "111-22-3"
    assert meta["expiry_months"] == 24
    assert meta["opinion_pl"] == "Dobry"
    assert meta["opinion_en"] == "Good"


def test_get_product_meta_missing(db):
    from mbr.certs.generator import _get_product_meta
    meta = _get_product_meta(db, "NonExistent")
    assert meta is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tbk/Desktop/aa && python -m pytest tests/test_produkty.py::test_get_product_meta_from_db -v`
Expected: FAIL — `_get_product_meta` doesn't exist

- [ ] **Step 3: Add _get_product_meta to generator.py**

```python
def _get_product_meta(db, produkt: str) -> dict | None:
    """Read product metadata from produkty table.

    Returns dict with display_name, spec_number, cas_number, expiry_months,
    opinion_pl, opinion_en — or None if not found.
    """
    row = db.execute(
        "SELECT display_name, spec_number, cas_number, expiry_months, "
        "opinion_pl, opinion_en FROM produkty WHERE nazwa = ?",
        (produkt,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)
```

- [ ] **Step 4: Modify build_context to use DB product metadata**

In `build_context()`, after the existing DB block (around line 260, after `use_db` rows section), add product meta lookup. Replace the lines that read from `product_cfg`:

```python
    # Product metadata — DB-first, fallback to cert_config.json
    product_meta = None
    try:
        with db_session() as db:
            product_meta = _get_product_meta(db, key)
    except Exception:
        pass

    if product_meta:
        display_name = product_meta["display_name"] or product_cfg.get("display_name", key)
        spec_number_base = product_meta["spec_number"] or product_cfg.get("spec_number", "")
        opinion_pl_base = product_meta["opinion_pl"] or product_cfg.get("opinion_pl", "")
        opinion_en_base = product_meta["opinion_en"] or product_cfg.get("opinion_en", "")
        expiry_months = product_meta["expiry_months"] or product_cfg.get("expiry_months", 12)
        cas_number = product_meta["cas_number"] or product_cfg.get("cas_number", "")
    else:
        display_name = product_cfg.get("display_name", key)
        spec_number_base = product_cfg.get("spec_number", "")
        opinion_pl_base = product_cfg.get("opinion_pl", "")
        opinion_en_base = product_cfg.get("opinion_en", "")
        expiry_months = product_cfg.get("expiry_months", 12)
        cas_number = product_cfg.get("cas_number", "")

    # Apply variant overrides (these still come from cert_config.json)
    spec_number = overrides.get("spec_number", spec_number_base)
    opinion_pl = overrides.get("opinion_pl", opinion_pl_base)
    opinion_en = overrides.get("opinion_en", opinion_en_base)
```

Then update the return dict to use these variables instead of `product_cfg[...]`:
- `"display_name": display_name + (" MB" if has_rspo else ""),`
- `"spec_number": spec_number,`
- `"cas_number": cas_number,`
- Replace `expiry_months = product_cfg.get("expiry_months", 12)` in the date calculation section with the already-resolved `expiry_months` variable

Remove the old lines that set `spec_number`, `opinion_pl`, `opinion_en` from `product_cfg` (around lines 200-212).

- [ ] **Step 5: Run tests**

Run: `cd /Users/tbk/Desktop/aa && python -m pytest tests/test_produkty.py tests/test_certs.py tests/test_parametry_cert.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add mbr/certs/generator.py tests/test_produkty.py
git commit -m "feat: certificate generator reads product metadata from DB"
```

---

### Task 6: Run migration on real data

**Files:**
- Run: `scripts/migrate_produkty.py`

- [ ] **Step 1: Dry run**

```bash
cd /Users/tbk/Desktop/aa && python scripts/migrate_produkty.py --dry-run
```

Review output — check counts.

- [ ] **Step 2: Run for real**

```bash
cd /Users/tbk/Desktop/aa && python scripts/migrate_produkty.py
```

- [ ] **Step 3: Verify**

```bash
python -c "
import sqlite3
db = sqlite3.connect('data/batch_db_v4.sqlite')
db.row_factory = sqlite3.Row
rows = db.execute('SELECT nazwa, display_name, spec_number, expiry_months FROM produkty WHERE spec_number IS NOT NULL AND spec_number != \"\" ORDER BY nazwa').fetchall()
for r in rows:
    print(f'{r[\"nazwa\"]:25} display={r[\"display_name\"]:25} spec={r[\"spec_number\"]:8} exp={r[\"expiry_months\"]}m')
"
```

- [ ] **Step 4: Run full test suite**

```bash
cd /Users/tbk/Desktop/aa && python -m pytest tests/test_produkty.py tests/test_parametry_cert.py tests/test_certs.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit any cleanup**

```bash
git add -A && git status
# Only commit if there are meaningful changes
```

---

## Summary

| Task | Description | Depends on |
|------|-------------|------------|
| 1 | DB migrations (new columns + auto-sync) | — |
| 2 | Migration script cert_config → produkty | Task 1 |
| 3 | Move produkty API to parametry/routes.py | Task 1 |
| 4 | Add "Produkty" tab UI | Tasks 1, 3 |
| 5 | Generator reads product meta from DB | Tasks 1, 2 |
| 6 | Run migration on real data | Tasks 2, 5 |
