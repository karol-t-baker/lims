# Zbiorniki jako encja — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create zbiorniki (tanks) as a first-class entity with DB tables, seed data, CRUD API, admin panel, batch→tank linking in fast entry, and tank stickers in registry.

**Architecture:** New `mbr/zbiorniki/` blueprint with models + routes. Two new DB tables (`zbiorniki`, `zbiornik_szarze`) seeded in `init_mbr_tables()`. Admin gets a dedicated "Zbiorniki" page. Fast entry completion flow uses dropdown from `zbiorniki` table instead of free-text number. Registry query JOINs `zbiornik_szarze` to show tank stickers.

**Tech Stack:** Python/Flask, SQLite, vanilla JS

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Create | `mbr/zbiorniki/__init__.py` | Blueprint definition |
| Create | `mbr/zbiorniki/models.py` | DB functions: list, create, update, link/unlink |
| Create | `mbr/zbiorniki/routes.py` | API endpoints |
| Create | `mbr/templates/admin/zbiorniki.html` | Admin CRUD page |
| Modify | `mbr/models.py` | CREATE TABLE + seed 19 tanks |
| Modify | `mbr/app.py` | Register blueprint |
| Modify | `mbr/registry/models.py` | JOIN zbiornik_szarze in registry query |
| Modify | `mbr/templates/laborant/szarze_list.html` | Tank stickers in registry rows |
| Modify | `mbr/templates/laborant/_fast_entry_content.html` | Replace free-text M+nr with dropdown |
| Modify | `mbr/laborant/models.py` | Save to zbiornik_szarze on complete |

---

### Task 1: DB tables + seed data

**Files:**
- Modify: `mbr/models.py`

- [ ] **Step 1: Add zbiorniki tables to init_mbr_tables()**

In `mbr/models.py`, inside `init_mbr_tables()`, after the last `CREATE TABLE IF NOT EXISTS` statement in the `executescript`, add:

```sql
CREATE TABLE IF NOT EXISTS zbiorniki (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nr_zbiornika TEXT UNIQUE NOT NULL,
    max_pojemnosc REAL,
    produkt TEXT,
    aktywny INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS zbiornik_szarze (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ebr_id INTEGER NOT NULL,
    zbiornik_id INTEGER NOT NULL REFERENCES zbiorniki(id),
    masa_kg REAL,
    dt_dodania TEXT,
    UNIQUE(ebr_id, zbiornik_id)
);
```

- [ ] **Step 2: Add seed data after executescript**

After the `db.executescript(...)` call (but still inside `init_mbr_tables`), before the existing migrations section, add:

```python
    # Seed zbiorniki (tanks) — INSERT OR IGNORE for idempotency
    _ZBIORNIKI_SEED = [
        ("M1", 30, "Cheginy GLOL"), ("M2", 30, "Cheginy GLO"),
        ("M3", 35, "Cheginy GLOL"), ("M4", 20, "Alkohole Cetostearylowe"),
        ("M5", 27, "DEA"), ("M6", 25, "Chelamid DK"),
        ("M7", 12, "Olej palmowy"), ("M8", 25, "Olej palmowy"),
        ("M9", 22, "Cheginy"), ("M10", 33, "Chelamid"),
        ("M11", 30, "Kwasy kokosowe"), ("M12", 30, "DMAPA"),
        ("M13", 25, "Olej kokosowy"), ("M14", 48, "Cheginy KK"),
        ("M15", 42, "Cheginy K7"), ("M16", 25, "Cheginy GL"),
        ("M17", 25, "Cheginy GLO"), ("M18", 27, "Chelamid DK"),
        ("M19", 25, "Kwasy kokosowe"),
    ]
    for nr, cap, prod in _ZBIORNIKI_SEED:
        db.execute(
            "INSERT OR IGNORE INTO zbiorniki (nr_zbiornika, max_pojemnosc, produkt) VALUES (?, ?, ?)",
            (nr, cap, prod),
        )
    db.commit()
```

- [ ] **Step 3: Commit**

```bash
git add mbr/models.py
git commit -m "feat: add zbiorniki + zbiornik_szarze tables with seed data"
```

---

### Task 2: Zbiorniki blueprint — models + routes

**Files:**
- Create: `mbr/zbiorniki/__init__.py`
- Create: `mbr/zbiorniki/models.py`
- Create: `mbr/zbiorniki/routes.py`
- Modify: `mbr/app.py`

- [ ] **Step 1: Create blueprint init**

Create `mbr/zbiorniki/__init__.py`:

```python
from flask import Blueprint
zbiorniki_bp = Blueprint('zbiorniki', __name__)
from mbr.zbiorniki import routes  # noqa: E402, F401
```

- [ ] **Step 2: Create models**

Create `mbr/zbiorniki/models.py`:

```python
"""zbiorniki/models.py — CRUD for tanks and batch-tank links."""

import sqlite3
from datetime import datetime


def list_zbiorniki(db: sqlite3.Connection, include_inactive: bool = False) -> list[dict]:
    sql = "SELECT * FROM zbiorniki"
    if not include_inactive:
        sql += " WHERE aktywny = 1"
    sql += " ORDER BY CAST(SUBSTR(nr_zbiornika, 2) AS INTEGER)"
    return [dict(r) for r in db.execute(sql).fetchall()]


def create_zbiornik(db: sqlite3.Connection, nr_zbiornika: str, max_pojemnosc: float, produkt: str) -> int:
    cur = db.execute(
        "INSERT INTO zbiorniki (nr_zbiornika, max_pojemnosc, produkt) VALUES (?, ?, ?)",
        (nr_zbiornika, max_pojemnosc, produkt),
    )
    db.commit()
    return cur.lastrowid


def update_zbiornik(db: sqlite3.Connection, zbiornik_id: int, **fields) -> None:
    allowed = {"max_pojemnosc", "produkt", "aktywny", "nr_zbiornika"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    db.execute(f"UPDATE zbiorniki SET {set_clause} WHERE id = ?", [*updates.values(), zbiornik_id])
    db.commit()


def link_szarza(db: sqlite3.Connection, ebr_id: int, zbiornik_id: int, masa_kg: float | None = None) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    cur = db.execute(
        "INSERT OR REPLACE INTO zbiornik_szarze (ebr_id, zbiornik_id, masa_kg, dt_dodania) VALUES (?, ?, ?, ?)",
        (ebr_id, zbiornik_id, masa_kg, now),
    )
    db.commit()
    return cur.lastrowid


def unlink_szarza(db: sqlite3.Connection, link_id: int) -> None:
    db.execute("DELETE FROM zbiornik_szarze WHERE id = ?", (link_id,))
    db.commit()


def get_links_for_ebr(db: sqlite3.Connection, ebr_id: int) -> list[dict]:
    rows = db.execute("""
        SELECT zs.id, zs.ebr_id, zs.zbiornik_id, zs.masa_kg, zs.dt_dodania,
               z.nr_zbiornika, z.max_pojemnosc, z.produkt
        FROM zbiornik_szarze zs
        JOIN zbiorniki z ON z.id = zs.zbiornik_id
        WHERE zs.ebr_id = ?
        ORDER BY z.nr_zbiornika
    """, (ebr_id,)).fetchall()
    return [dict(r) for r in rows]


def get_zbiorniki_for_batch_ids(db: sqlite3.Connection, ebr_ids: list[int]) -> dict[int, list[str]]:
    """Return {ebr_id: [nr_zbiornika, ...]} for a list of batch IDs."""
    if not ebr_ids:
        return {}
    placeholders = ",".join("?" * len(ebr_ids))
    rows = db.execute(f"""
        SELECT zs.ebr_id, z.nr_zbiornika
        FROM zbiornik_szarze zs
        JOIN zbiorniki z ON z.id = zs.zbiornik_id
        WHERE zs.ebr_id IN ({placeholders})
        ORDER BY z.nr_zbiornika
    """, ebr_ids).fetchall()
    result: dict[int, list[str]] = {}
    for r in rows:
        result.setdefault(r["ebr_id"], []).append(r["nr_zbiornika"])
    return result
```

- [ ] **Step 3: Create routes**

Create `mbr/zbiorniki/routes.py`:

```python
"""zbiorniki/routes.py — API endpoints for tank management."""

from flask import jsonify, request

from mbr.db import db_session
from mbr.shared.decorators import login_required, role_required
from mbr.zbiorniki import zbiorniki_bp
from mbr.zbiorniki.models import (
    list_zbiorniki, create_zbiornik, update_zbiornik,
    link_szarza, unlink_szarza, get_links_for_ebr,
)


@zbiorniki_bp.route("/api/zbiorniki")
@login_required
def api_list():
    include_all = request.args.get("all") == "1"
    with db_session() as db:
        tanks = list_zbiorniki(db, include_inactive=include_all)
    return jsonify(tanks)


@zbiorniki_bp.route("/api/zbiorniki", methods=["POST"])
@role_required("admin")
def api_create():
    data = request.get_json(silent=True) or {}
    nr = data.get("nr_zbiornika", "").strip()
    if not nr:
        return jsonify({"error": "nr_zbiornika required"}), 400
    with db_session() as db:
        try:
            zid = create_zbiornik(db, nr, data.get("max_pojemnosc", 0), data.get("produkt", ""))
        except Exception:
            return jsonify({"error": "Zbiornik already exists"}), 409
    return jsonify({"ok": True, "id": zid})


@zbiorniki_bp.route("/api/zbiorniki/<int:zid>", methods=["PUT"])
@role_required("admin")
def api_update(zid):
    data = request.get_json(silent=True) or {}
    with db_session() as db:
        update_zbiornik(db, zid, **data)
    return jsonify({"ok": True})


@zbiorniki_bp.route("/api/zbiornik-szarze/<int:ebr_id>")
@login_required
def api_links(ebr_id):
    with db_session() as db:
        links = get_links_for_ebr(db, ebr_id)
    return jsonify(links)


@zbiorniki_bp.route("/api/zbiornik-szarze", methods=["POST"])
@login_required
def api_link():
    data = request.get_json(silent=True) or {}
    ebr_id = data.get("ebr_id")
    zbiornik_id = data.get("zbiornik_id")
    if not ebr_id or not zbiornik_id:
        return jsonify({"error": "ebr_id and zbiornik_id required"}), 400
    with db_session() as db:
        lid = link_szarza(db, ebr_id, zbiornik_id, data.get("masa_kg"))
    return jsonify({"ok": True, "id": lid})


@zbiorniki_bp.route("/api/zbiornik-szarze/<int:link_id>", methods=["DELETE"])
@login_required
def api_unlink(link_id):
    with db_session() as db:
        unlink_szarza(db, link_id)
    return jsonify({"ok": True})
```

- [ ] **Step 4: Register blueprint in app.py**

In `mbr/app.py`, after `from mbr.admin import admin_bp` (line 42), add:

```python
    from mbr.zbiorniki import zbiorniki_bp
```

After `app.register_blueprint(admin_bp)` (line 53), add:

```python
    app.register_blueprint(zbiorniki_bp)
```

- [ ] **Step 5: Commit**

```bash
git add mbr/zbiorniki/ mbr/app.py
git commit -m "feat: zbiorniki blueprint with CRUD models and API routes"
```

---

### Task 3: Admin panel — zbiorniki page

**Files:**
- Create: `mbr/templates/admin/zbiorniki.html`
- Modify: `mbr/zbiorniki/routes.py`
- Modify: `mbr/templates/admin/panel.html`

- [ ] **Step 1: Add page route**

In `mbr/zbiorniki/routes.py`, add at the top with imports:

```python
from flask import jsonify, request, render_template
```

Add route at the end:

```python
@zbiorniki_bp.route("/admin/zbiorniki")
@role_required("admin")
def admin_zbiorniki():
    return render_template("admin/zbiorniki.html")
```

- [ ] **Step 2: Create admin template**

Create `mbr/templates/admin/zbiorniki.html`:

```html
{% extends "base.html" %}
{% block title %}Zbiorniki{% endblock %}
{% block nav_admin %}active{% endblock %}

{% block topbar_title %}
  <span style="font-weight:700;">Zbiorniki magazynowe</span>
{% endblock %}

{% block head %}
<style>
.zb-wrap { padding: 24px 32px; max-width: 900px; overflow-y: auto; max-height: calc(100vh - 52px); }
.zb-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.zb-table th { text-align: left; padding: 10px 12px; font-size: 10px; font-weight: 700; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid var(--border); }
.zb-table td { padding: 8px 12px; border-bottom: 1px solid var(--border-subtle); }
.zb-table tr:hover { background: var(--surface-alt); }
.zb-nr { font-weight: 700; font-family: var(--mono); }
.zb-input { border: 1px solid transparent; background: transparent; padding: 4px 8px; border-radius: 4px; font-size: 12px; width: 100%; font-family: inherit; }
.zb-input:hover { border-color: var(--border); }
.zb-input:focus { border-color: var(--teal); outline: none; background: var(--surface); }
.zb-toggle { cursor: pointer; padding: 3px 10px; border-radius: 12px; font-size: 10px; font-weight: 600; border: none; }
.zb-toggle.on { background: var(--green-bg, #dcfce7); color: var(--green, #16a34a); }
.zb-toggle.off { background: var(--red-bg, #fef2f2); color: var(--red, #dc2626); }
.zb-add { margin-top: 16px; display: flex; gap: 8px; align-items: center; }
.zb-add input { padding: 8px 12px; border: 1.5px solid var(--border); border-radius: 8px; font-size: 12px; }
.zb-add button { padding: 8px 16px; background: var(--teal); color: #fff; border: none; border-radius: 8px; font-size: 12px; font-weight: 600; cursor: pointer; }
.zb-add button:hover { opacity: 0.9; }
</style>
{% endblock %}

{% block content %}
<div class="zb-wrap">
  <table class="zb-table" id="zb-table">
    <thead>
      <tr>
        <th>Nr</th>
        <th>Pojemność [t]</th>
        <th>Produkt</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody id="zb-body"></tbody>
  </table>

  <div class="zb-add">
    <input type="text" id="add-nr" placeholder="np. M20" style="width:80px;">
    <input type="number" id="add-cap" placeholder="Pojemność" style="width:100px;">
    <input type="text" id="add-prod" placeholder="Produkt" style="width:180px;">
    <button onclick="addZbiornik()">Dodaj</button>
  </div>
</div>

<script>
var _zbData = [];

async function loadZbiorniki() {
  var resp = await fetch('/api/zbiorniki?all=1');
  _zbData = await resp.json();
  renderTable();
}

function renderTable() {
  var html = '';
  _zbData.forEach(function(z) {
    html += '<tr data-id="' + z.id + '">' +
      '<td class="zb-nr">' + z.nr_zbiornika + '</td>' +
      '<td><input class="zb-input" type="number" value="' + (z.max_pojemnosc || '') + '" onchange="saveField(' + z.id + ', \'max_pojemnosc\', parseFloat(this.value))"></td>' +
      '<td><input class="zb-input" type="text" value="' + (z.produkt || '') + '" onchange="saveField(' + z.id + ', \'produkt\', this.value)"></td>' +
      '<td><button class="zb-toggle ' + (z.aktywny ? 'on' : 'off') + '" onclick="toggleActive(' + z.id + ', ' + z.aktywny + ')">' + (z.aktywny ? 'Aktywny' : 'Nieaktywny') + '</button></td>' +
    '</tr>';
  });
  document.getElementById('zb-body').innerHTML = html;
}

async function saveField(id, field, value) {
  var body = {};
  body[field] = value;
  await fetch('/api/zbiorniki/' + id, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
}

async function toggleActive(id, current) {
  await saveField(id, 'aktywny', current ? 0 : 1);
  loadZbiorniki();
}

async function addZbiornik() {
  var nr = document.getElementById('add-nr').value.trim();
  var cap = parseFloat(document.getElementById('add-cap').value) || 0;
  var prod = document.getElementById('add-prod').value.trim();
  if (!nr) return;
  var resp = await fetch('/api/zbiorniki', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({nr_zbiornika: nr, max_pojemnosc: cap, produkt: prod})
  });
  if (resp.ok) {
    document.getElementById('add-nr').value = '';
    document.getElementById('add-cap').value = '';
    document.getElementById('add-prod').value = '';
    loadZbiorniki();
  }
}

loadZbiorniki();
</script>
{% endblock %}
```

- [ ] **Step 3: Add link in admin panel**

In `mbr/templates/admin/panel.html`, find where admin sections are defined and add a link/button to `/admin/zbiorniki`. Search for existing navigation links and add:

```html
<a href="/admin/zbiorniki" style="display:inline-flex;align-items:center;gap:8px;padding:10px 16px;background:var(--surface);border:1.5px solid var(--border);border-radius:8px;text-decoration:none;color:var(--text);font-size:12px;font-weight:600;">
  Zbiorniki magazynowe
</a>
```

(Read the file first to find the exact insertion point — look for other navigation links or section headers.)

- [ ] **Step 4: Commit**

```bash
git add mbr/zbiorniki/routes.py mbr/templates/admin/zbiorniki.html mbr/templates/admin/panel.html
git commit -m "feat: admin panel for zbiorniki CRUD management"
```

---

### Task 4: Replace free-text pump targets with dropdown

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Replace pump target HTML**

In `mbr/templates/laborant/_fast_entry_content.html`, find the pump form (lines 68-78):

```html
    <div class="ft-targets" id="ft-targets">
      <div class="ft-target-row">
        <span class="ft-m">M</span>
        <input class="ft-nr" type="number" min="1" max="99" placeholder="nr">
      </div>
    </div>
    <button type="button" class="ft-add" onclick="addPumpTarget()" title="Dodaj zbiornik">+</button>
```

Replace with:

```html
    <div class="ft-targets" id="ft-targets">
      <div class="ft-target-row">
        <select class="ft-zbiornik-select"></select>
        <input class="ft-masa" type="text" inputmode="decimal" placeholder="kg" style="width:80px;">
      </div>
    </div>
    <button type="button" class="ft-add" onclick="addPumpTarget()" title="Dodaj zbiornik">+</button>
```

- [ ] **Step 2: Add zbiorniki loading and update JS functions**

Find `showPumpInline()` (line ~1690). Replace the three functions `showPumpInline`, `addPumpTarget`, and `doCompleteFt` with:

```javascript
var _zbiornikList = [];
async function loadZbiornikList() {
    if (_zbiornikList.length > 0) return;
    var resp = await fetch('/api/zbiorniki');
    _zbiornikList = await resp.json();
}

function _buildZbiornikOptions() {
    var html = '<option value="">Wybierz...</option>';
    _zbiornikList.forEach(function(z) {
        html += '<option value="' + z.id + '">' + z.nr_zbiornika + ' (' + (z.produkt || '') + ', ' + (z.max_pojemnosc || '?') + 't)</option>';
    });
    return html;
}

async function showPumpInline() {
    await loadZbiornikList();
    document.getElementById('ft-pump').style.display = 'none';
    document.getElementById('ft-pump-form').style.display = 'flex';
    var opts = _buildZbiornikOptions();
    document.getElementById('ft-targets').innerHTML =
        '<div class="ft-target-row"><select class="ft-zbiornik-select">' + opts + '</select><input class="ft-masa" type="text" inputmode="decimal" placeholder="kg" style="width:80px;"></div>';
    var sel = document.querySelector('#ft-targets .ft-zbiornik-select');
    setTimeout(function() { sel.focus(); }, 50);
}

function addPumpTarget() {
    var opts = _buildZbiornikOptions();
    var row = document.createElement('div');
    row.className = 'ft-target-row';
    row.innerHTML = '<select class="ft-zbiornik-select">' + opts + '</select><input class="ft-masa" type="text" inputmode="decimal" placeholder="kg" style="width:80px;">';
    document.getElementById('ft-targets').appendChild(row);
    row.querySelector('.ft-zbiornik-select').focus();
}

async function doCompleteFt() {
    var rows = document.querySelectorAll('#ft-targets .ft-target-row');
    var targets = [];
    var valid = true;
    rows.forEach(function(row) {
        var sel = row.querySelector('.ft-zbiornik-select');
        var masaInput = row.querySelector('.ft-masa');
        var zbiornikId = sel ? parseInt(sel.value) : 0;
        if (!zbiornikId) {
            sel.style.borderColor = 'var(--red)';
            if (valid) sel.focus();
            valid = false;
        } else {
            sel.style.borderColor = '';
            var nr = sel.options[sel.selectedIndex].text.split(' ')[0];
            var masa = masaInput ? parseFloat(masaInput.value.replace(',', '.')) || null : null;
            targets.push({nr: nr, zbiornik_id: zbiornikId, kg: masa});
        }
    });
    if (!valid || targets.length === 0) return;
    var btn = document.querySelector('.ft-go');
    btn.textContent = '...';
    btn.disabled = true;
    var resp = await fetch('/laborant/ebr/' + ebrId + '/complete', {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({zbiorniki: targets})
    });
    if (resp.ok || resp.redirected) {
        location.href = '/laborant/szarze';
    }
}
```

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: replace free-text pump targets with zbiorniki dropdown"
```

---

### Task 5: Save batch→tank links on complete

**Files:**
- Modify: `mbr/laborant/models.py`

- [ ] **Step 1: Update complete_ebr to save zbiornik_szarze links**

In `mbr/laborant/models.py`, find `complete_ebr()` (line ~534). After the existing `db.execute(UPDATE ...)` and before `db.commit()`, add:

```python
    # Save batch→tank links if zbiorniki provided
    if zbiorniki:
        for z in zbiorniki:
            zbiornik_id = z.get("zbiornik_id")
            if zbiornik_id:
                db.execute(
                    "INSERT OR REPLACE INTO zbiornik_szarze (ebr_id, zbiornik_id, masa_kg, dt_dodania) VALUES (?, ?, ?, ?)",
                    (ebr_id, zbiornik_id, z.get("kg"), now),
                )
```

- [ ] **Step 2: Commit**

```bash
git add mbr/laborant/models.py
git commit -m "feat: save batch-to-tank links in zbiornik_szarze on complete"
```

---

### Task 6: Tank stickers in registry

**Files:**
- Modify: `mbr/registry/models.py`
- Modify: `mbr/templates/laborant/szarze_list.html`

- [ ] **Step 1: Add zbiorniki data to registry query**

In `mbr/registry/models.py`, in `list_completed_registry()`, after the existing loop that builds `result` (after line ~44 `result.append(d)`), add a bulk lookup:

```python
    # Attach zbiorniki links
    if result:
        from mbr.zbiorniki.models import get_zbiorniki_for_batch_ids
        ebr_ids = [r["ebr_id"] for r in result]
        zb_map = get_zbiorniki_for_batch_ids(db, ebr_ids)
        for r in result:
            r["zbiorniki"] = zb_map.get(r["ebr_id"], [])
```

Add this BEFORE the `return result` line.

- [ ] **Step 2: Render stickers in registry rows**

In `mbr/templates/laborant/szarze_list.html`, find `_buildRegistryRow()` (line ~1321). Find the `<td class="td-nr">` cell construction. After the existing content (highlight-marker or nr_partii + cert badge), add zbiorniki stickers:

Current line builds the `td-nr` cell. After the cert badge part, before the closing `</td>`, add:

```javascript
  // Zbiorniki stickers
  if (b.zbiorniki && b.zbiorniki.length > 0) {
    b.zbiorniki.forEach(function(nr) {
      html += ' <span class="td-zb-sticker">' + nr + '</span>';
    });
  }
```

- [ ] **Step 3: Add CSS for stickers**

In the `<style>` section of `szarze_list.html`, add:

```css
.td-zb-sticker {
  display: inline-block;
  padding: 1px 5px;
  font-size: 9px;
  font-weight: 600;
  font-family: var(--mono);
  background: var(--blue-bg, #e8f0fe);
  color: var(--blue, #1a73e8);
  border-radius: 3px;
  margin-left: 3px;
}
```

- [ ] **Step 4: Commit**

```bash
git add mbr/registry/models.py mbr/templates/laborant/szarze_list.html
git commit -m "feat: tank stickers in completed batch registry"
```
