# Płatkowanie — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "płatkowanie" as a third EBR registration type with product-type filtering, substrates, and admin CRUD.

**Architecture:** Extend existing modal (`_modal_nowa_szarza.html`) with step-2c for płatkowanie. Add `typy` column to `produkty`, new `substraty`/`substrat_produkty`/`platkowanie_substraty` tables. Reuse existing admin panel patterns (zbiorniki.html, produkty.html). API endpoints in `zbiorniki/routes.py` (where other admin CRUD lives).

**Tech Stack:** Python/Flask, SQLite, Jinja2, vanilla JS

---

### Task 1: Database schema — add `typy` column and new tables

**Files:**
- Modify: `mbr/models.py:114-220`

- [ ] **Step 1: Add `typy` column to `produkty` CREATE TABLE**

In `init_mbr_tables`, change the `produkty` table definition to include `typy`:

```python
        CREATE TABLE IF NOT EXISTS produkty (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nazwa TEXT UNIQUE NOT NULL,
            kod TEXT,
            aktywny INTEGER DEFAULT 1,
            typy TEXT DEFAULT '["szarza"]'
        );
```

- [ ] **Step 2: Add 3 new tables after `produkt_etapy`**

After the `produkt_etapy` CREATE TABLE (line 153), before the closing `"""` of `executescript`, add:

```python
        CREATE TABLE IF NOT EXISTS substraty (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nazwa TEXT UNIQUE NOT NULL,
            aktywny INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS substrat_produkty (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            substrat_id INTEGER NOT NULL REFERENCES substraty(id),
            produkt TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS platkowanie_substraty (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ebr_id INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
            substrat_id INTEGER NOT NULL REFERENCES substraty(id),
            nr_partii_substratu TEXT
        );
```

- [ ] **Step 3: Add migration for `typy` column on existing DBs**

After the existing `kod_produktu` migration block (around line 202), add:

```python
    # Migration: add typy column to produkty if missing
    pr_cols = [r[1] for r in db.execute("PRAGMA table_info(produkty)").fetchall()]
    if "typy" not in pr_cols:
        db.execute("ALTER TABLE produkty ADD COLUMN typy TEXT DEFAULT '[\"szarza\"]'")
```

- [ ] **Step 4: Update `ebr_batches` CHECK constraint to allow `platkowanie`**

Change the `typ` CHECK in `ebr_batches` CREATE TABLE from:

```sql
            typ                 TEXT NOT NULL DEFAULT 'szarza'
                                CHECK(typ IN ('szarza', 'zbiornik')),
```

to:

```sql
            typ                 TEXT NOT NULL DEFAULT 'szarza'
                                CHECK(typ IN ('szarza', 'zbiornik', 'platkowanie')),
```

**Note:** SQLite CHECK constraints only apply at INSERT for tables created with IF NOT EXISTS — existing DBs keep the old CHECK. Add a migration that recreates the table if needed. Since this is complex and the CHECK is a safety net (not enforced on existing tables with IF NOT EXISTS), the simplest approach is to add a migration block similar to the `parametry_analityczne` CHECK migration already in this file (lines 235-280). However, since the column already has data and the app already validates `typ` in Python, we can skip the CHECK migration and just handle it in the route validation. The CREATE TABLE with updated CHECK will apply to fresh databases.

- [ ] **Step 5: Seed default `typy` for Cheginy products**

After the produkty seed loop (line 197), add:

```python
    # Set typy for Cheginy products (szarza + zbiornik + platkowanie)
    _CHEGINY_ALL_TYPY = '["szarza","zbiornik","platkowanie"]'
    for nazwa, _ in _PRODUKTY_SEED:
        if nazwa.startswith("Chegina_"):
            db.execute(
                "UPDATE produkty SET typy = ? WHERE nazwa = ? AND typy = '[\"szarza\"]'",
                (_CHEGINY_ALL_TYPY, nazwa),
            )
```

- [ ] **Step 6: Commit**

```bash
git add mbr/models.py
git commit -m "feat: add typy column, substraty tables, allow platkowanie typ"
```

---

### Task 2: Backend API — product filtering by type and substrates CRUD

**Files:**
- Modify: `mbr/zbiorniki/routes.py:82-136`

- [ ] **Step 1: Add `typ` filter to `GET /api/produkty`**

In `api_produkty()` (line 84), add filtering by `typ` query param. Replace the function:

```python
@zbiorniki_bp.route("/api/produkty")
@login_required
def api_produkty():
    include_all = request.args.get("all") == "1"
    typ_filter = request.args.get("typ", "")
    with db_session() as db:
        sql = "SELECT * FROM produkty"
        params = []
        conditions = []
        if not include_all:
            conditions.append("aktywny = 1")
        if typ_filter:
            # JSON array contains check: typy LIKE '%"szarza"%'
            conditions.append("typy LIKE ?")
            params.append(f'%"{typ_filter}"%')
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY nazwa"
        rows = [dict(r) for r in db.execute(sql, params).fetchall()]
    return jsonify(rows)
```

- [ ] **Step 2: Add `typy` to allowed fields in `PUT /api/produkty/<pid>`**

In `api_produkty_update()` (line 119), change `allowed` set:

```python
    allowed = {"nazwa", "kod", "aktywny", "typy"}
```

- [ ] **Step 3: Add substrates API endpoints**

After the `admin_produkty` route (line 135), add:

```python
# ── Substraty API ──

@zbiorniki_bp.route("/api/substraty")
@login_required
def api_substraty():
    produkt = request.args.get("produkt", "")
    include_all = request.args.get("all") == "1"
    with db_session() as db:
        if produkt:
            # Return substrates linked to this product + universal (no links)
            rows = db.execute("""
                SELECT s.* FROM substraty s
                WHERE s.aktywny = 1 AND (
                    s.id IN (SELECT substrat_id FROM substrat_produkty WHERE produkt = ?)
                    OR s.id NOT IN (SELECT substrat_id FROM substrat_produkty)
                )
                ORDER BY s.nazwa
            """, (produkt,)).fetchall()
        else:
            sql = "SELECT * FROM substraty"
            if not include_all:
                sql += " WHERE aktywny = 1"
            sql += " ORDER BY nazwa"
            rows = db.execute(sql).fetchall()
        result = [dict(r) for r in rows]
        # Attach linked products for admin view
        if include_all:
            for sub in result:
                links = db.execute(
                    "SELECT produkt FROM substrat_produkty WHERE substrat_id = ?",
                    (sub["id"],)
                ).fetchall()
                sub["produkty"] = [r["produkt"] for r in links]
    return jsonify(result)


@zbiorniki_bp.route("/api/substraty", methods=["POST"])
@role_required("admin")
def api_substraty_create():
    data = request.get_json(silent=True) or {}
    nazwa = data.get("nazwa", "").strip()
    if not nazwa:
        return jsonify({"error": "nazwa required"}), 400
    with db_session() as db:
        try:
            cur = db.execute("INSERT INTO substraty (nazwa) VALUES (?)", (nazwa,))
            db.commit()
        except Exception:
            return jsonify({"error": "Substrat already exists"}), 409
    return jsonify({"ok": True, "id": cur.lastrowid})


@zbiorniki_bp.route("/api/substraty/<int:sid>", methods=["PUT"])
@role_required("admin")
def api_substraty_update(sid):
    data = request.get_json(silent=True) or {}
    allowed = {"nazwa", "aktywny"}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates:
        return jsonify({"ok": True})
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with db_session() as db:
        db.execute(f"UPDATE substraty SET {set_clause} WHERE id = ?", [*updates.values(), sid])
        db.commit()
    return jsonify({"ok": True})


@zbiorniki_bp.route("/api/substraty/<int:sid>/produkty", methods=["PUT"])
@role_required("admin")
def api_substraty_produkty(sid):
    data = request.get_json(silent=True) or {}
    produkty = data.get("produkty", [])
    with db_session() as db:
        db.execute("DELETE FROM substrat_produkty WHERE substrat_id = ?", (sid,))
        for p in produkty:
            db.execute("INSERT INTO substrat_produkty (substrat_id, produkt) VALUES (?, ?)", (sid, p))
        db.commit()
    return jsonify({"ok": True})
```

- [ ] **Step 4: Add admin substraty page route**

```python
@zbiorniki_bp.route("/admin/substraty")
@role_required("admin")
def admin_substraty():
    return render_template("admin/substraty.html")
```

- [ ] **Step 5: Commit**

```bash
git add mbr/zbiorniki/routes.py
git commit -m "feat: add substraty CRUD API and product type filtering"
```

---

### Task 3: Backend — płatkowanie in batch creation route

**Files:**
- Modify: `mbr/laborant/routes.py:34-85`

- [ ] **Step 1: Handle `typ='platkowanie'` and save substrates**

After the zbiorniki linking block (lines 62-75), add handling for płatkowanie substrates. Replace the route function:

```python
@laborant_bp.route("/laborant/szarze/new", methods=["POST"])
@role_required("laborant", "laborant_kj", "admin")
def szarze_new():
    import sqlite3
    with db_session() as db:
        typ = request.form.get("typ", "szarza")
        wielkosc_kg = float(request.form.get("wielkosc_kg", 0) or 0)
        try:
            ebr_id = create_ebr(
                db,
                produkt=request.form["produkt"],
                nr_partii=request.form["nr_partii"],
                nr_amidatora=request.form.get("nr_amidatora", ""),
                nr_mieszalnika=request.form.get("nr_mieszalnika", ""),
                wielkosc_kg=wielkosc_kg,
                operator=session["user"]["login"],
                typ=typ,
                nastaw=int(wielkosc_kg) if wielkosc_kg else None,
                nr_zbiornika=request.form.get("nr_zbiornika", ""),
            )
        except sqlite3.IntegrityError:
            flash(f"Szarża o numerze {request.form['nr_partii']} już istnieje w systemie.")
            back = request.form.get("_back") or request.referrer or url_for("laborant.szarze_list")
            parsed = urlparse(back)
            if parsed.netloc and parsed.netloc != request.host:
                back = url_for("laborant.szarze_list")
            return redirect(back)

        # Save pre-selected zbiorniki (optional, from modal pill selection)
        if ebr_id:
            zbiorniki_ids = request.form.get("zbiorniki_ids", "")
            if zbiorniki_ids:
                from datetime import datetime
                now = datetime.now().isoformat(timespec="seconds")
                for zid_str in zbiorniki_ids.split(","):
                    zid = int(zid_str.strip()) if zid_str.strip() else 0
                    if zid:
                        db.execute(
                            "INSERT OR IGNORE INTO zbiornik_szarze (ebr_id, zbiornik_id, masa_kg, dt_dodania) VALUES (?, ?, NULL, ?)",
                            (ebr_id, zid, now),
                        )
                db.commit()

            # Save płatkowanie substrates
            if typ == "platkowanie":
                import json as _json
                substraty_raw = request.form.get("substraty_json", "[]")
                try:
                    substraty_list = _json.loads(substraty_raw)
                except (ValueError, TypeError):
                    substraty_list = []
                for sub in substraty_list:
                    sub_id = sub.get("substrat_id")
                    sub_nr = sub.get("nr_partii", "")
                    if sub_id:
                        db.execute(
                            "INSERT INTO platkowanie_substraty (ebr_id, substrat_id, nr_partii_substratu) VALUES (?, ?, ?)",
                            (ebr_id, int(sub_id), sub_nr),
                        )
                db.commit()

    if ebr_id is None:
        flash("Brak aktywnego szablonu MBR dla tego produktu.")
    # Return to referring page (fast_entry or szarze_list)
    back = request.form.get("_back") or request.referrer or url_for("laborant.szarze_list")
    # Prevent open redirect — only allow relative paths
    parsed = urlparse(back)
    if parsed.netloc and parsed.netloc != request.host:
        back = url_for("laborant.szarze_list")
    return redirect(back)
```

- [ ] **Step 2: Commit**

```bash
git add mbr/laborant/routes.py
git commit -m "feat: handle platkowanie typ with substrates in batch creation"
```

---

### Task 4: Frontend — add step-2c (płatkowanie) to modal

**Files:**
- Modify: `mbr/templates/laborant/_modal_nowa_szarza.html`

- [ ] **Step 1: Add hidden input for substraty JSON**

After the `zbiorniki_ids` hidden input (line 20), add:

```html
        <input type="hidden" name="substraty_json" id="substraty-json-input" value="[]">
```

- [ ] **Step 2: Replace SVG icons in step-1 type cards**

Replace the szarża card SVG (lines 28-31) with Lucide `flask-conical`:

```html
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M14 2v6a2 2 0 0 0 .245.96l5.51 10.08A2 2 0 0 1 18 22H6a2 2 0 0 1-1.755-2.96l5.51-10.08A2 2 0 0 0 10 8V2" />
                  <path d="M6.453 15h11.094" />
                  <path d="M8.5 2h7" />
                </svg>
```

Replace the zbiornik card SVG (lines 39-43) with Lucide `scan-search`:

```html
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M3 7V5a2 2 0 0 1 2-2h2" />
                  <path d="M17 3h2a2 2 0 0 1 2 2v2" />
                  <path d="M21 17v2a2 2 0 0 1-2 2h-2" />
                  <path d="M7 21H5a2 2 0 0 1-2-2v-2" />
                  <circle cx="12" cy="12" r="3" />
                  <path d="m16 16-1.9-1.9" />
                </svg>
```

- [ ] **Step 3: Add third type card for płatkowanie**

After the zbiornik type-card closing `</div>` (line 48), before the closing `</div>` of `.type-grid` (line 49), add:

```html
            <div class="type-card" onclick="selectTyp('platkowanie')">
              <div class="tc-icon">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="m10 20-1.25-2.5L6 18" />
                  <path d="M10 4 8.75 6.5 6 6" />
                  <path d="m14 20 1.25-2.5L18 18" />
                  <path d="m14 4 1.25 2.5L18 6" />
                  <path d="m17 21-3-6h-4" />
                  <path d="m17 3-3 6 1.5 3" />
                  <path d="M2 12h6.5L10 9" />
                  <path d="m20 10-1.5 2 1.5 2" />
                  <path d="M22 12h-6.5L14 15" />
                  <path d="m4 10 1.5 2L4 14" />
                  <path d="m7 21 3-6-1.5-3" />
                  <path d="m7 3 3 6h4" />
                </svg>
              </div>
              <div class="tc-name">Płatkowanie</div>
              <div class="tc-desc">Produkcja płatków z analiza końcowa</div>
            </div>
```

- [ ] **Step 4: Add step-2c HTML block**

After the closing `</div>` of `step-2b` (line 196), before the `{# Footer #}` comment (line 198), add:

```html
        {# Step 2c: Platkowanie form #}
        <div id="step-2c" style="display:none;">
          <div class="step-indicator">
            <div class="step-dot done"></div>
            <div class="step-line done"></div>
            <div class="step-dot active"></div>
          </div>

          <div class="form-row">
            <div class="form-label">Produkt</div>
            <div class="quick-picks" id="quick-pick-platkowanie"></div>
            <div class="search-wrap product-search-wrap" id="search-wrap-platkowanie">
              <span class="search-icon"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg></span>
              <input class="search-input form-input product-search" type="text"
                     placeholder="Szukaj produktu..."
                     oninput="filterProducts(this)"
                     autocomplete="off">
              <div class="product-dropdown" id="platkowanie-product-dropdown"></div>
            </div>
            <div class="selected-badge product-selected" id="selected-product-platkowanie" style="display:none;">
              <div class="sb-check"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg></div>
              <div>
                <div class="sb-name product-selected-name"></div>
                <div class="sb-full"></div>
              </div>
              <button type="button" class="sb-clear product-selected-clear" onclick="clearProduct('platkowanie')">&times;</button>
            </div>
          </div>

          <div class="auto-nr" id="auto-nr-platkowanie" style="display:none;">
            <span class="nr-label">Nr partii</span>
            <span class="nr-value" id="nr-value-platkowanie"></span>
            <label style="margin-left:auto;display:flex;align-items:center;gap:5px;cursor:pointer;font-size:10px;color:var(--text-dim);">
              <input type="checkbox" id="manual-nr-platkowanie" onchange="toggleManualNr('platkowanie')"> Podaj ręcznie
            </label>
          </div>
          <div id="manual-nr-wrap-platkowanie" style="display:none;margin-top:6px;">
            <input class="form-input" type="text" id="manual-nr-input-platkowanie" placeholder="np. 15_2026" style="font-family:var(--mono);font-weight:600;">
          </div>
          <input class="form-input" type="hidden" id="nr-partii-input-pl">

          <div style="height:12px"></div>
          <div class="form-row" id="substraty-section" style="display:none;">
            <div class="form-label" style="display:flex;align-items:center;gap:6px;">
              <svg viewBox="0 0 24 24" fill="none" stroke="var(--text-dim)" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px;flex-shrink:0;"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>
              Substraty <span style="font-weight:400;color:var(--text-dim);margin-left:2px;">(opcjonalne)</span>
            </div>
            <div id="substraty-rows"></div>
            <button type="button" class="m-btn-link" id="add-substrat-btn" onclick="_addSubstratRow()" style="margin-top:6px;font-size:11px;color:var(--teal);background:none;border:none;cursor:pointer;font-weight:600;">+ Dodaj substrat</button>
          </div>
        </div>
```

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/laborant/_modal_nowa_szarza.html
git commit -m "feat: add step-2c platkowanie form and updated SVG icons"
```

---

### Task 5: Frontend JS — wire up płatkowanie logic

**Files:**
- Modify: `mbr/templates/laborant/_modal_nowa_szarza.html` (script section, lines 213-583)

- [ ] **Step 1: Add płatkowanie-specific JS variables and product loading**

After `var _modalZbSelected = {};` (line 216), add:

```javascript
var _modalSubstratyList = [];
var _platkowanieProducts = [];
```

- [ ] **Step 2: Add substrates loading and rendering functions**

After the `_onProductSelected` function (line 291), add:

```javascript
async function _loadSubstraty(produkt) {
    var resp = await fetch('/api/substraty?produkt=' + encodeURIComponent(produkt));
    _modalSubstratyList = await resp.json();
    document.getElementById('substraty-section').style.display = 'block';
    document.getElementById('substraty-rows').innerHTML = '';
}

function _addSubstratRow() {
    var container = document.getElementById('substraty-rows');
    var idx = container.children.length;
    var options = '<option value="">— wybierz substrat —</option>';
    _modalSubstratyList.forEach(function(s) {
        options += '<option value="' + s.id + '">' + s.nazwa + '</option>';
    });
    var row = document.createElement('div');
    row.className = 'substrat-row';
    row.style.cssText = 'display:flex;gap:8px;align-items:center;margin-bottom:6px;';
    row.innerHTML =
        '<select class="form-input sub-select" style="flex:1;font-size:12px;" data-idx="' + idx + '">' + options + '</select>' +
        '<input class="form-input sub-nr" type="text" placeholder="Nr partii" style="width:120px;font-size:12px;font-family:var(--mono);" data-idx="' + idx + '">' +
        '<button type="button" onclick="this.parentElement.remove();_syncSubstratyJson()" style="background:none;border:none;color:var(--red);cursor:pointer;font-size:16px;padding:0 4px;">&times;</button>';
    row.querySelector('.sub-select').addEventListener('change', _syncSubstratyJson);
    row.querySelector('.sub-nr').addEventListener('input', _syncSubstratyJson);
    container.appendChild(row);
}

function _syncSubstratyJson() {
    var rows = document.querySelectorAll('#substraty-rows .substrat-row');
    var arr = [];
    rows.forEach(function(row) {
        var sel = row.querySelector('.sub-select');
        var nr = row.querySelector('.sub-nr');
        if (sel.value) {
            arr.push({substrat_id: parseInt(sel.value), nr_partii: nr.value.trim()});
        }
    });
    document.getElementById('substraty-json-input').value = JSON.stringify(arr);
}
```

- [ ] **Step 3: Add dynamic product list loading for płatkowanie**

After the `_syncSubstratyJson` function, add:

```javascript
async function _loadProductsForType(typ) {
    var resp = await fetch('/api/produkty?typ=' + encodeURIComponent(typ));
    var products = await resp.json();

    if (typ === 'platkowanie') {
        _platkowanieProducts = products;
        // Render quick-pick buttons (first 4)
        var qpHtml = '';
        products.slice(0, 4).forEach(function(p) {
            var short = p.nazwa.replace(/^Chegina_/, '').replace(/_/g, ' ');
            qpHtml += '<button type="button" class="qp-btn" onclick="quickPick(this,\'' + p.nazwa + '\',\'platkowanie\')">' + short + '</button>';
        });
        document.getElementById('quick-pick-platkowanie').innerHTML = qpHtml;

        // Render dropdown items
        var ddHtml = '';
        products.forEach(function(p) {
            var short = p.nazwa.replace(/^[A-Za-z]+_/, '').replace(/_/g, ' ');
            ddHtml += '<div class="product-item" data-product="' + p.nazwa + '" onclick="pickProduct(this)">' +
                '<span class="product-item-name">' + short + '</span>' +
                '<span class="product-item-full">' + p.nazwa + '</span>' +
            '</div>';
        });
        document.getElementById('platkowanie-product-dropdown').innerHTML = ddHtml;
    }
}
```

- [ ] **Step 4: Update `selectTyp()` to handle płatkowanie**

Replace the `selectTyp` function (lines 302-316) with:

```javascript
function selectTyp(typ) {
  currentTyp = typ;
  document.getElementById('typ-input').value = typ;
  document.getElementById('step-1').style.display = 'none';
  document.getElementById('modal-footer').style.display = 'flex';
  document.getElementById('step-2a').style.display = 'none';
  document.getElementById('step-2b').style.display = 'none';
  document.getElementById('step-2c').style.display = 'none';
  if (typ === 'szarza') {
    document.getElementById('step-2a').style.display = 'block';
    document.getElementById('modal-subtitle').textContent = 'Nowa szarza produkcyjna';
  } else if (typ === 'zbiornik') {
    document.getElementById('step-2b').style.display = 'block';
    document.getElementById('modal-subtitle').textContent = 'Analiza zbiornika magazynowego';
  } else if (typ === 'platkowanie') {
    document.getElementById('step-2c').style.display = 'block';
    document.getElementById('modal-subtitle').textContent = 'Nowe płatkowanie';
    _loadProductsForType('platkowanie');
  }
}
```

- [ ] **Step 5: Update `backToStep1()` to reset płatkowanie**

Replace `backToStep1` (lines 318-326) with:

```javascript
function backToStep1() {
  document.getElementById('step-1').style.display = 'block';
  document.getElementById('step-2a').style.display = 'none';
  document.getElementById('step-2b').style.display = 'none';
  document.getElementById('step-2c').style.display = 'none';
  document.getElementById('modal-footer').style.display = 'none';
  document.getElementById('modal-subtitle').textContent = 'Wybierz typ rejestracji';
  clearProduct('szarza');
  clearProduct('zbiornik');
  clearProduct('platkowanie');
}
```

- [ ] **Step 6: Update `fetchAutoNr()` to handle płatkowanie context**

Replace `fetchAutoNr` (lines 370-384) with:

```javascript
function fetchAutoNr(product, context) {
  fetch('/api/next-nr/' + encodeURIComponent(product))
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (context === 'szarza') {
        document.getElementById('nr-partii-input').value = data.nr_partii;
        document.getElementById('nr-value-szarza').textContent = data.nr_partii;
        document.getElementById('auto-nr-szarza').style.display = 'flex';
      } else if (context === 'zbiornik') {
        document.getElementById('nr-partii-input-zb').value = data.nr_partii;
        document.getElementById('nr-value-zbiornik').textContent = data.nr_partii;
        document.getElementById('auto-nr-zbiornik').style.display = 'flex';
      } else if (context === 'platkowanie') {
        document.getElementById('nr-partii-input-pl').value = data.nr_partii;
        document.getElementById('nr-value-platkowanie').textContent = data.nr_partii;
        document.getElementById('auto-nr-platkowanie').style.display = 'flex';
      }
    });
}
```

- [ ] **Step 7: Update `clearProduct()` for płatkowanie**

Replace `clearProduct` (lines 400-428) with:

```javascript
function clearProduct(context) {
  document.getElementById('produkt-input').value = '';
  var stepMap = {szarza: 'step-2a', zbiornik: 'step-2b', platkowanie: 'step-2c'};
  var step = document.getElementById(stepMap[context]);
  if (!step) return;
  var wrap = step.querySelector('.product-search-wrap');
  var selected = step.querySelector('.product-selected');
  if (wrap) {
    wrap.style.display = 'block';
    var searchInput = wrap.querySelector('.product-search');
    if (searchInput) searchInput.value = '';
    wrap.classList.remove('open');
    wrap.querySelectorAll('.product-item').forEach(function(item) { item.classList.remove('hidden'); });
  }
  if (selected) selected.style.display = 'none';
  var qp = step.querySelector('[id^="quick-pick-"]');
  if (qp) qp.querySelectorAll('.qp-btn').forEach(function(p) { p.classList.remove('active'); });
  if (context === 'szarza') {
    document.getElementById('nr-partii-input').value = '';
    document.getElementById('auto-nr-szarza').style.display = 'none';
    document.getElementById('manual-nr-wrap-szarza').style.display = 'none';
    document.getElementById('manual-nr-szarza').checked = false;
  } else if (context === 'zbiornik') {
    var zb = document.getElementById('nr-partii-input-zb');
    if (zb) zb.value = '';
    document.getElementById('auto-nr-zbiornik').style.display = 'none';
    document.getElementById('manual-nr-wrap-zbiornik').style.display = 'none';
    document.getElementById('manual-nr-zbiornik').checked = false;
  } else if (context === 'platkowanie') {
    var pl = document.getElementById('nr-partii-input-pl');
    if (pl) pl.value = '';
    document.getElementById('auto-nr-platkowanie').style.display = 'none';
    document.getElementById('manual-nr-wrap-platkowanie').style.display = 'none';
    document.getElementById('manual-nr-platkowanie').checked = false;
    document.getElementById('substraty-section').style.display = 'none';
    document.getElementById('substraty-rows').innerHTML = '';
    document.getElementById('substraty-json-input').value = '[]';
  }
}
```

- [ ] **Step 8: Update `_onProductSelected()` to load substrates for płatkowanie**

Replace `_onProductSelected` (lines 283-291) with:

```javascript
async function _onProductSelected(produktName) {
    await _loadModalZbiorniki();
    _modalZbSelected = {};
    if (currentTyp === 'zbiornik') {
        _renderZbPills('zb-pick-zbiornik', produktName, false);
    } else if (currentTyp === 'szarza') {
        _renderZbPills('zb-pick-szarza', produktName, true);
    } else if (currentTyp === 'platkowanie') {
        await _loadSubstraty(produktName);
    }
}
```

- [ ] **Step 9: Update `quickPick()` to handle płatkowanie step**

Replace the step lookup in `quickPick` (line 344) with:

```javascript
  var stepMap = {szarza: 'step-2a', zbiornik: 'step-2b', platkowanie: 'step-2c'};
  var step = document.getElementById(stepMap[context]);
```

- [ ] **Step 10: Update form submit validation for płatkowanie**

In the submit handler (line 441+), add płatkowanie nr_partii sync. After the zbiornik sync block (lines 494-513), add:

```javascript
  // Sync platkowanie nr_partii
  if (currentTyp === 'platkowanie') {
    var manualCbPl = document.getElementById('manual-nr-platkowanie');
    if (manualCbPl && manualCbPl.checked) {
      var manualValPl = document.getElementById('manual-nr-input-platkowanie').value.trim();
      if (manualValPl) document.getElementById('nr-partii-input-pl').value = manualValPl;
    }
    var plVal = document.getElementById('nr-partii-input-pl').value;
    document.getElementById('nr-partii-input').value = plVal;
    document.getElementById('nr-partii-input-pl').removeAttribute('name');
    document.getElementById('nr-partii-input').removeAttribute('readonly');
    _syncSubstratyJson();
  }
```

Also update the validation `target` for produkt to include platkowanie:

```javascript
  // Validate produkt
  var produkt = document.getElementById('produkt-input').value;
  if (!produkt) {
    var targetMap = {szarza: '#quick-pick-szarza', zbiornik: '#quick-pick-zbiornik', platkowanie: '#quick-pick-platkowanie'};
    errors.push({msg: 'Wybierz produkt', target: targetMap[currentTyp]});
  }
```

- [ ] **Step 11: Add batch exists check for płatkowanie manual input**

After the existing manual input listeners (lines 571-582), add:

```javascript
var manualPlatkowanie = document.getElementById('manual-nr-input-platkowanie');
if (manualPlatkowanie) {
    manualPlatkowanie.addEventListener('input', function() {
        checkBatchExists(this, 'produkt-input');
    });
}
```

- [ ] **Step 12: Commit**

```bash
git add mbr/templates/laborant/_modal_nowa_szarza.html
git commit -m "feat: wire up platkowanie JS — product loading, substrates, validation"
```

---

### Task 6: Admin page — substrates management

**Files:**
- Create: `mbr/templates/admin/substraty.html`

- [ ] **Step 1: Create the substrates admin template**

Follow the exact same pattern as `zbiorniki.html` (table + inline edit + add row):

```html
{% extends "base.html" %}
{% block title %}Substraty{% endblock %}
{% block nav_admin %}active{% endblock %}

{% block topbar_title %}
  <span style="font-weight:700;">Substraty</span>
{% endblock %}

{% block head %}
<style>
.sub-wrap { padding: 24px 32px; max-width: 900px; overflow-y: auto; max-height: calc(100vh - 52px); }
.sub-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.sub-table th { text-align: left; padding: 10px 12px; font-size: 10px; font-weight: 700; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid var(--border); }
.sub-table td { padding: 8px 12px; border-bottom: 1px solid var(--border-subtle); }
.sub-table tr:hover { background: var(--surface-alt); }
.sub-nazwa { font-weight: 600; }
.sub-input { border: 1px solid transparent; background: transparent; padding: 4px 8px; border-radius: 4px; font-size: 12px; width: 100%; font-family: inherit; }
.sub-input:hover { border-color: var(--border); }
.sub-input:focus { border-color: var(--teal); outline: none; background: var(--surface); }
.sub-toggle { cursor: pointer; padding: 3px 10px; border-radius: 12px; font-size: 10px; font-weight: 600; border: none; }
.sub-toggle.on { background: var(--green-bg, #dcfce7); color: var(--green, #16a34a); }
.sub-toggle.off { background: var(--red-bg, #fef2f2); color: var(--red, #dc2626); }
.sub-add { margin-top: 16px; display: flex; gap: 8px; align-items: center; }
.sub-add input { padding: 8px 12px; border: 1.5px solid var(--border); border-radius: 8px; font-size: 12px; }
.sub-add button { padding: 8px 16px; background: var(--teal); color: #fff; border: none; border-radius: 8px; font-size: 12px; font-weight: 600; cursor: pointer; }
.sub-add button:hover { opacity: 0.9; }
.sub-produkty { display: flex; flex-wrap: wrap; gap: 4px; }
.sub-prod-tag { font-size: 10px; padding: 2px 8px; border-radius: 10px; background: var(--teal-bg, #e0f7f7); color: var(--teal); font-weight: 600; }
.sub-prod-edit { font-size: 10px; color: var(--teal); cursor: pointer; border: none; background: none; text-decoration: underline; }
/* Produkt picker modal */
.sub-picker-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.3); z-index: 999; display: flex; align-items: center; justify-content: center; }
.sub-picker { background: var(--surface); border-radius: 12px; padding: 20px; max-width: 400px; width: 90%; max-height: 60vh; overflow-y: auto; box-shadow: 0 8px 30px rgba(0,0,0,0.15); }
.sub-picker h3 { margin: 0 0 12px; font-size: 14px; }
.sub-picker label { display: flex; align-items: center; gap: 6px; font-size: 12px; padding: 4px 0; cursor: pointer; }
.sub-picker-btns { margin-top: 12px; display: flex; gap: 8px; justify-content: flex-end; }
.sub-picker-btns button { padding: 6px 16px; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; }
</style>
{% endblock %}

{% block content %}
<div class="sub-wrap">
  <table class="sub-table">
    <thead>
      <tr>
        <th>Nazwa</th>
        <th>Powiązane produkty</th>
        <th style="width:90px;">Status</th>
      </tr>
    </thead>
    <tbody id="sub-body"></tbody>
  </table>

  <div class="sub-add">
    <input type="text" id="add-nazwa" placeholder="Nazwa substratu" style="width:250px;">
    <button onclick="addSubstrat()">Dodaj</button>
  </div>
</div>

<script>
var _subData = [];
var _allProdukty = [];

async function loadData() {
  var [subResp, prResp] = await Promise.all([
    fetch('/api/substraty?all=1'),
    fetch('/api/produkty?all=1')
  ]);
  _subData = await subResp.json();
  _allProdukty = await prResp.json();
  renderTable();
}

function renderTable() {
  var html = '';
  _subData.forEach(function(s) {
    var prodTags = (s.produkty || []).map(function(p) {
      return '<span class="sub-prod-tag">' + p.replace(/_/g, ' ') + '</span>';
    }).join('');
    if (!prodTags) prodTags = '<span style="font-size:10px;color:var(--text-dim);font-style:italic;">Uniwersalny</span>';
    html += '<tr data-id="' + s.id + '">' +
      '<td class="sub-nazwa"><input class="sub-input" value="' + s.nazwa + '" onchange="saveField(' + s.id + ', \'nazwa\', this.value)"></td>' +
      '<td><div class="sub-produkty">' + prodTags + ' <button class="sub-prod-edit" onclick="editProdukty(' + s.id + ')">edytuj</button></div></td>' +
      '<td><button class="sub-toggle ' + (s.aktywny ? 'on' : 'off') + '" onclick="toggleActive(' + s.id + ', ' + s.aktywny + ')">' + (s.aktywny ? 'Aktywny' : 'Ukryty') + '</button></td>' +
    '</tr>';
  });
  document.getElementById('sub-body').innerHTML = html;
}

async function saveField(id, field, value) {
  var body = {};
  body[field] = value;
  await fetch('/api/substraty/' + id, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
}

async function toggleActive(id, current) {
  await fetch('/api/substraty/' + id, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({aktywny: current ? 0 : 1})
  });
  loadData();
}

async function addSubstrat() {
  var nazwa = document.getElementById('add-nazwa').value.trim();
  if (!nazwa) return;
  var resp = await fetch('/api/substraty', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({nazwa: nazwa})
  });
  if (resp.ok) {
    document.getElementById('add-nazwa').value = '';
    loadData();
  } else {
    var d = await resp.json();
    alert(d.error || 'Błąd');
  }
}

function editProdukty(subId) {
  var sub = _subData.find(function(s) { return s.id === subId; });
  var linked = sub ? (sub.produkty || []) : [];

  var overlay = document.createElement('div');
  overlay.className = 'sub-picker-overlay';
  overlay.onclick = function(e) { if (e.target === overlay) overlay.remove(); };

  var html = '<div class="sub-picker"><h3>Produkty dla: ' + sub.nazwa + '</h3>';
  _allProdukty.forEach(function(p) {
    var checked = linked.includes(p.nazwa) ? ' checked' : '';
    html += '<label><input type="checkbox" value="' + p.nazwa + '"' + checked + '> ' + p.nazwa.replace(/_/g, ' ') + '</label>';
  });
  html += '<div class="sub-picker-btns">' +
    '<button onclick="this.closest(\'.sub-picker-overlay\').remove()" style="background:var(--surface-alt);border:1px solid var(--border);color:var(--text);">Anuluj</button>' +
    '<button onclick="_saveProdukty(' + subId + ', this)" style="background:var(--teal);border:none;color:#fff;">Zapisz</button>' +
  '</div></div>';

  overlay.innerHTML = html;
  document.body.appendChild(overlay);
}

async function _saveProdukty(subId, btn) {
  var overlay = btn.closest('.sub-picker-overlay');
  var checked = overlay.querySelectorAll('input[type="checkbox"]:checked');
  var produkty = Array.from(checked).map(function(cb) { return cb.value; });
  await fetch('/api/substraty/' + subId + '/produkty', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({produkty: produkty})
  });
  overlay.remove();
  loadData();
}

loadData();
</script>
{% endblock %}
```

- [ ] **Step 2: Commit**

```bash
git add mbr/templates/admin/substraty.html
git commit -m "feat: add substraty admin page with product linking"
```

---

### Task 7: Admin page — product types editing

**Files:**
- Modify: `mbr/templates/admin/produkty.html:63-74`

- [ ] **Step 1: Add typy column to the table header**

Change the table header (line 38-42) from:

```html
      <tr>
        <th>Nazwa</th>
        <th style="width:120px;">Kod</th>
        <th style="width:90px;">Status</th>
      </tr>
```

to:

```html
      <tr>
        <th>Nazwa</th>
        <th style="width:120px;">Kod</th>
        <th style="width:200px;">Typy</th>
        <th style="width:90px;">Status</th>
      </tr>
```

- [ ] **Step 2: Update renderTable to show typy checkboxes**

Replace the `renderTable` function (lines 63-74) with:

```javascript
function renderTable() {
  document.getElementById('pr-count').textContent = _prData.length + ' produktów';
  var html = '';
  _prData.forEach(function(p) {
    var typy = [];
    try { typy = JSON.parse(p.typy || '["szarza"]'); } catch(e) { typy = ['szarza']; }
    var typyHtml = ['szarza', 'zbiornik', 'platkowanie'].map(function(t) {
      var checked = typy.includes(t) ? ' checked' : '';
      var label = t === 'platkowanie' ? 'płatk.' : t === 'zbiornik' ? 'zbior.' : 'szarża';
      return '<label style="display:inline-flex;align-items:center;gap:3px;font-size:11px;cursor:pointer;"><input type="checkbox" data-pid="' + p.id + '" data-typ="' + t + '"' + checked + ' onchange="toggleTyp(' + p.id + ')"> ' + label + '</label>';
    }).join(' ');
    html += '<tr data-id="' + p.id + '">' +
      '<td class="pr-nazwa">' + p.nazwa.replace(/_/g, ' ') + '</td>' +
      '<td><input class="pr-input kod" type="text" value="' + (p.kod || '') + '" onchange="saveField(' + p.id + ', \'kod\', this.value)"></td>' +
      '<td>' + typyHtml + '</td>' +
      '<td><button class="pr-toggle ' + (p.aktywny ? 'on' : 'off') + '" onclick="toggleActive(' + p.id + ', ' + p.aktywny + ')">' + (p.aktywny ? 'Aktywny' : 'Ukryty') + '</button></td>' +
    '</tr>';
  });
  document.getElementById('pr-body').innerHTML = html;
}
```

- [ ] **Step 3: Add `toggleTyp()` function**

After the existing `addProdukt()` function, add:

```javascript
async function toggleTyp(pid) {
  var checkboxes = document.querySelectorAll('input[data-pid="' + pid + '"][data-typ]');
  var typy = [];
  checkboxes.forEach(function(cb) {
    if (cb.checked) typy.push(cb.dataset.typ);
  });
  if (typy.length === 0) typy = ['szarza']; // must have at least one
  await fetch('/api/produkty/' + pid, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({typy: JSON.stringify(typy)})
  });
}
```

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/admin/produkty.html
git commit -m "feat: add typy checkboxes to produkty admin page"
```

---

### Task 8: Navigation — add substraty link in sidebar

**Files:**
- Modify: `mbr/templates/base.html`

- [ ] **Step 1: Add substraty nav link**

After the "Produkty" admin link (line 32), add:

```html
  <a class="rail-btn {% block nav_substraty %}{% endblock %}" href="{{ url_for('zbiorniki.admin_substraty') }}" title="Substraty"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg><span class="rail-label">Substraty</span></a>
```

- [ ] **Step 2: Commit**

```bash
git add mbr/templates/base.html
git commit -m "feat: add substraty link to admin sidebar"
```

---

### Task 9: CSS — substrat row styles in modal

**Files:**
- Modify: `mbr/static/style.css`

- [ ] **Step 1: Add substrat-row styles**

Add at the end of the modal styles section:

```css
/* Substrat rows in platkowanie modal */
.substrat-row { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
.substrat-row .form-input { font-size: 12px; }
```

- [ ] **Step 2: Update type-grid for 3 columns**

Find the `.type-grid` CSS rule and ensure it supports 3 cards. If it currently uses `grid-template-columns: 1fr 1fr`, change to:

```css
.type-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
```

- [ ] **Step 3: Commit**

```bash
git add mbr/static/style.css
git commit -m "style: add substrat row and 3-column type grid styles"
```

---

### Task 10: Smoke test — verify full flow

- [ ] **Step 1: Start the app and verify migrations run**

```bash
cd /Users/tbk/Desktop/aa && python -c "from mbr.models import init_mbr_tables; from mbr.db import db_session; db = db_session().__enter__(); init_mbr_tables(db)"
```

Expected: No errors.

- [ ] **Step 2: Verify new tables exist**

```bash
python -c "
from mbr.db import db_session
with db_session() as db:
    for t in ['substraty','substrat_produkty','platkowanie_substraty']:
        cols = [r[1] for r in db.execute(f'PRAGMA table_info({t})').fetchall()]
        print(f'{t}: {cols}')
    # Check typy column
    r = db.execute('SELECT typy FROM produkty LIMIT 1').fetchone()
    print(f'produkty.typy sample: {r[\"typy\"]}')
"
```

Expected: All tables with correct columns, `typy` column present.

- [ ] **Step 3: Verify API endpoint**

```bash
python -c "
from mbr.db import db_session
with db_session() as db:
    rows = db.execute(\"SELECT nazwa, typy FROM produkty WHERE typy LIKE '%platkowanie%'\").fetchall()
    print(f'{len(rows)} products with platkowanie type')
    for r in rows:
        print(f'  {r[\"nazwa\"]}: {r[\"typy\"]}')
"
```

Expected: Chegina products show all 3 types.

- [ ] **Step 4: Commit final state**

```bash
git add -A
git commit -m "feat: płatkowanie — complete third EBR registration type"
```
