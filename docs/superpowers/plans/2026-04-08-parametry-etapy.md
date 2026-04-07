# Parametry i Etapy — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add binary parameter type, golden batch target, admin panels for parameters/etapy, migrate process stages to DB, rename SMCA→NaMCA.

**Architecture:** Extend existing `parametry_analityczne` and `parametry_etapy` tables with migrations. New `etapy_procesowe` + `produkt_etapy` tables. Admin pages reuse existing modal/zbiorniki patterns. Binary params rendered as pill buttons in fast entry.

**Tech Stack:** Python/Flask, SQLite, vanilla JS

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Modify | `mbr/models.py` | Migrations: jednostka, target, drop CHECK, new etapy tables + seed |
| Create | `mbr/templates/admin/parametry.html` | Admin parameter editor |
| Create | `mbr/templates/admin/etapy.html` | Admin etapy editor |
| Create | `mbr/templates/admin/normy.html` | Admin normy per produkt |
| Modify | `mbr/zbiorniki/routes.py` | Admin routes for parametry, etapy, normy |
| Modify | `mbr/templates/base.html` | Admin rail icons |
| Modify | `mbr/parametry/seed.py` | Seed klarownosc, zelowanie, etapy |
| Modify | `mbr/parametry/registry.py` | Return target + jednostka in API |
| Modify | `mbr/etapy/models.py` | get_process_stages from DB |
| Modify | `mbr/etapy/config.py` | SMCA→NaMCA label |
| Modify | `mbr/templates/laborant/_fast_entry_content.html` | Binary UI + target hint |

---

### Task 1: DB migrations — jednostka, target, CHECK constraint, etapy tables

**Files:**
- Modify: `mbr/models.py`

- [ ] **Step 1: Add new tables + migrations to init_mbr_tables()**

In `mbr/models.py`, inside `init_mbr_tables()`, after the existing `parametry_etapy` CREATE TABLE and before the zbiorniki tables, add:

```sql
CREATE TABLE IF NOT EXISTS etapy_procesowe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kod TEXT UNIQUE NOT NULL,
    label TEXT NOT NULL,
    aktywny INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS produkt_etapy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    produkt TEXT NOT NULL,
    etap_kod TEXT NOT NULL,
    kolejnosc INTEGER DEFAULT 0,
    rownolegle INTEGER DEFAULT 0,
    UNIQUE(produkt, etap_kod)
);
```

Then in the migrations section (after zbiorniki seed), add:

```python
    # Migration: add jednostka column to parametry_analityczne
    pa_cols = [r[1] for r in db.execute("PRAGMA table_info(parametry_analityczne)").fetchall()]
    if "jednostka" not in pa_cols:
        db.execute("ALTER TABLE parametry_analityczne ADD COLUMN jednostka TEXT")

    # Migration: add target column to parametry_etapy
    pe_cols = [r[1] for r in db.execute("PRAGMA table_info(parametry_etapy)").fetchall()]
    if "target" not in pe_cols:
        db.execute("ALTER TABLE parametry_etapy ADD COLUMN target REAL")

    # Migration: recreate parametry_analityczne without CHECK constraint on typ
    # (SQLite can't ALTER CHECK; we create new table, copy data, swap)
    # Only run if 'binarny' typ would fail
    try:
        db.execute("INSERT INTO parametry_analityczne (kod,label,typ) VALUES ('__test_binarny','test','binarny')")
        db.execute("DELETE FROM parametry_analityczne WHERE kod='__test_binarny'")
    except Exception:
        # CHECK constraint blocks 'binarny' — need to recreate table
        db.executescript("""
            CREATE TABLE parametry_analityczne_new (
                id              INTEGER PRIMARY KEY,
                kod             TEXT NOT NULL UNIQUE,
                label           TEXT NOT NULL,
                typ             TEXT NOT NULL,
                metoda_nazwa    TEXT,
                metoda_formula  TEXT,
                metoda_factor   REAL,
                formula         TEXT,
                precision       INTEGER DEFAULT 2,
                aktywny         INTEGER DEFAULT 1,
                skrot           TEXT,
                metoda_id       INTEGER,
                jednostka       TEXT
            );
            INSERT INTO parametry_analityczne_new SELECT id, kod, label, typ, metoda_nazwa, metoda_formula, metoda_factor, formula, precision, aktywny, skrot, metoda_id, jednostka FROM parametry_analityczne;
            DROP TABLE parametry_analityczne;
            ALTER TABLE parametry_analityczne_new RENAME TO parametry_analityczne;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pa_kod ON parametry_analityczne(kod);
        """)

    # Seed etapy_procesowe
    _ETAPY_SEED = [
        ("amidowanie", "Amidowanie"),
        ("namca", "NaMCA"),
        ("czwartorzedowanie", "Czwartorzędowanie"),
        ("sulfonowanie", "Sulfonowanie"),
        ("utlenienie", "Utlenienie"),
        ("rozjasnianie", "Rozjaśnianie"),
        ("standaryzacja", "Standaryzacja"),
        ("analiza_koncowa", "Analiza końcowa"),
        ("dodatki", "Dodatki standaryzacyjne"),
    ]
    for kod, label in _ETAPY_SEED:
        db.execute("INSERT OR IGNORE INTO etapy_procesowe (kod, label) VALUES (?, ?)", (kod, label))

    # Seed produkt_etapy (K7 pipeline)
    _K7_PRODUCTS = ["Chegina_K7", "Chegina_K40GL"]
    _K7_STAGES = [("amidowanie", 1, 1), ("namca", 2, 1), ("czwartorzedowanie", 3, 0),
                  ("sulfonowanie", 4, 0), ("utlenienie", 5, 0)]
    for prod in _K7_PRODUCTS:
        for etap, kolej, rown in _K7_STAGES:
            db.execute("INSERT OR IGNORE INTO produkt_etapy (produkt, etap_kod, kolejnosc, rownolegle) VALUES (?,?,?,?)",
                       (prod, etap, kolej, rown))

    # Seed produkt_etapy (GLOL pipeline — K7 + rozjasnianie)
    _GLOL_PRODUCTS = ["Chegina_K40GLO", "Chegina_K40GLOL", "Chegina_K40GLOS",
                      "Chegina_K40GLOL_HQ", "Chegina_K40GLN", "Chegina_GLOL40"]
    _GLOL_STAGES = _K7_STAGES + [("rozjasnianie", 6, 0)]
    for prod in _GLOL_PRODUCTS:
        for etap, kolej, rown in _GLOL_STAGES:
            db.execute("INSERT OR IGNORE INTO produkt_etapy (produkt, etap_kod, kolejnosc, rownolegle) VALUES (?,?,?,?)",
                       (prod, etap, kolej, rown))

    # Migration: rename smca → namca in existing data
    db.execute("UPDATE OR IGNORE parametry_etapy SET kontekst = 'namca' WHERE kontekst = 'smca'")
    db.execute("UPDATE OR IGNORE ebr_etapy_status SET etap = 'namca' WHERE etap = 'smca'")
    db.execute("UPDATE OR IGNORE ebr_etapy_analizy SET etap = 'namca' WHERE etap = 'smca'")
    db.execute("UPDATE OR IGNORE produkt_etapy SET etap_kod = 'namca' WHERE etap_kod = 'smca'")

    db.commit()
```

- [ ] **Step 2: Commit**

```bash
git add mbr/models.py
git commit -m "feat: DB migrations — jednostka, target, binary typ, etapy tables, SMCA→NaMCA"
```

---

### Task 2: Seed binary parameters (klarowność, żelowanie)

**Files:**
- Modify: `mbr/parametry/seed.py`

- [ ] **Step 1: Add binary parameters to PARAMETRY list**

In `mbr/parametry/seed.py`, at the end of the PARAMETRY list (before the closing `]`), add:

```python
    # --- binarny (OK / Nie OK) ---
    {"kod": "klarownosc", "label": "Klarowność", "skrot": "Klar.", "typ": "binarny", "precision": 0},
    {"kod": "zelowanie",  "label": "Żelowanie",  "skrot": "Żel.",  "typ": "binarny", "precision": 0},
```

- [ ] **Step 2: Add bindings to analiza_koncowa (global)**

Find the seed bindings section in `seed.py` (where parametry_etapy are seeded). Add global bindings (produkt=NULL) for klarownosc and zelowanie to kontekst `analiza_koncowa`. Find where other global bindings are defined and add:

```python
    # Binary parameters — global (all products)
    ("analiza_koncowa", None, "klarownosc", 900, None, None),
    ("analiza_koncowa", None, "zelowanie",  901, None, None),
```

Format: `(kontekst, produkt, kod, kolejnosc, min_limit, max_limit)`

- [ ] **Step 3: Commit**

```bash
git add mbr/parametry/seed.py
git commit -m "feat: seed klarowność and żelowanie as binary parameters"
```

---

### Task 3: Update registry.py to return target + jednostka

**Files:**
- Modify: `mbr/parametry/registry.py`

- [ ] **Step 1: Add target and jednostka to SQL query and result**

In `get_parametry_for_kontekst()`, add `pe.target` to the SELECT and `pa.jednostka` to the SELECT. Then include them in the result dict.

In the SQL query (~line 37), add after `pe.nawazka_g`:
```sql
            pe.target,
```
And add after `pa.metoda_id`:
```sql
            pa.jednostka,
```

In the result dict (~line 102), add:
```python
            "target": r["target"],
            "jednostka": r["jednostka"],
```

- [ ] **Step 2: Update build_parametry_lab to include target + jednostka**

In `build_parametry_lab()` function, in `_build_pole()`, add to the pole dict:
```python
        if p.get("target") is not None:
            pole["target"] = p["target"]
        if p.get("jednostka"):
            pole["jednostka"] = p["jednostka"]
```

- [ ] **Step 3: Commit**

```bash
git add mbr/parametry/registry.py
git commit -m "feat: return target and jednostka in parametry API"
```

---

### Task 4: Migrate get_process_stages to DB + rename SMCA

**Files:**
- Modify: `mbr/etapy/models.py`
- Modify: `mbr/etapy/config.py`

- [ ] **Step 1: Update get_process_stages to read from DB**

In `mbr/etapy/models.py`, replace `get_process_stages()`:

```python
def get_process_stages(produkt: str) -> list[str]:
    """Return ordered list of process stage codes for a product.
    Reads from produkt_etapy table, falls back to hardcoded lists."""
    from mbr.db import get_db
    try:
        db = get_db()
        rows = db.execute(
            """SELECT pe.etap_kod FROM produkt_etapy pe
               JOIN etapy_procesowe ep ON ep.kod = pe.etap_kod
               WHERE pe.produkt = ? AND ep.aktywny = 1
               ORDER BY pe.kolejnosc""",
            (produkt,),
        ).fetchall()
        db.close()
        if rows:
            return [r["etap_kod"] for r in rows]
    except Exception:
        pass
    # Fallback to hardcoded
    if produkt not in FULL_PIPELINE_PRODUCTS:
        return []
    if produkt in ROZJASNIANIE_PRODUCTS:
        return list(PROCESS_STAGES_GLOL)
    return list(PROCESS_STAGES_K7)
```

- [ ] **Step 2: Update PARALLEL_STAGES to include namca**

```python
PARALLEL_STAGES = {"amidowanie", "smca", "namca"}
```

- [ ] **Step 3: Update hardcoded fallback lists**

```python
PROCESS_STAGES_K7 = ["amidowanie", "namca", "czwartorzedowanie", "sulfonowanie", "utlenienie"]
PROCESS_STAGES_GLOL = ["amidowanie", "namca", "czwartorzedowanie", "sulfonowanie", "utlenienie", "rozjasnianie"]
```

- [ ] **Step 4: Rename SMCA in config.py**

In `mbr/etapy/config.py`, find all occurrences of `"smca"` key and rename to `"namca"`. Update label from `"Wytworzenie SMCA"` to `"NaMCA"`.

- [ ] **Step 5: Commit**

```bash
git add mbr/etapy/models.py mbr/etapy/config.py
git commit -m "feat: migrate process stages to DB, rename SMCA→NaMCA"
```

---

### Task 5: Admin panel — Parametry editor

**Files:**
- Create: `mbr/templates/admin/parametry.html`
- Modify: `mbr/zbiorniki/routes.py`
- Modify: `mbr/templates/base.html`

- [ ] **Step 1: Add routes**

In `mbr/zbiorniki/routes.py`, add:

```python
@zbiorniki_bp.route("/admin/parametry")
@role_required("admin")
def admin_parametry():
    return render_template("admin/parametry.html")

@zbiorniki_bp.route("/api/parametry/all")
@role_required("admin")
def api_parametry_all():
    with db_session() as db:
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM parametry_analityczne ORDER BY kod"
        ).fetchall()]
    return jsonify(rows)

@zbiorniki_bp.route("/api/parametry/admin/<int:pid>", methods=["PUT"])
@role_required("admin")
def api_parametry_admin_update(pid):
    data = request.get_json(silent=True) or {}
    allowed = {"label", "skrot", "typ", "jednostka", "precision", "aktywny"}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates:
        return jsonify({"ok": True})
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with db_session() as db:
        db.execute(f"UPDATE parametry_analityczne SET {set_clause} WHERE id = ?",
                   [*updates.values(), pid])
        db.commit()
    return jsonify({"ok": True})

@zbiorniki_bp.route("/api/parametry/admin", methods=["POST"])
@role_required("admin")
def api_parametry_admin_create():
    data = request.get_json(silent=True) or {}
    kod = data.get("kod", "").strip()
    label = data.get("label", "").strip()
    typ = data.get("typ", "bezposredni")
    if not kod or not label:
        return jsonify({"error": "kod and label required"}), 400
    with db_session() as db:
        try:
            cur = db.execute(
                "INSERT INTO parametry_analityczne (kod, label, typ, jednostka, precision) VALUES (?, ?, ?, ?, ?)",
                (kod, label, typ, data.get("jednostka", ""), data.get("precision", 2)),
            )
            db.commit()
        except Exception:
            return jsonify({"error": "Parametr already exists"}), 409
    return jsonify({"ok": True, "id": cur.lastrowid})
```

- [ ] **Step 2: Create admin template**

Create `mbr/templates/admin/parametry.html` — table with inline editing of label, skrót, typ (dropdown), jednostka, precyzja, aktywny toggle. Same pattern as `admin/zbiorniki.html`. Typ dropdown includes: bezposredni, titracja, obliczeniowy, binarny.

- [ ] **Step 3: Add rail icon**

In `mbr/templates/base.html`, in the admin rail section, add Parametry icon after Zbiorniki:

```html
<a class="rail-btn {% block nav_parametry %}{% endblock %}" href="{{ url_for('zbiorniki.admin_parametry') }}" title="Parametry"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg><span class="rail-label">Parametry</span></a>
```

- [ ] **Step 4: Commit**

```bash
git add mbr/zbiorniki/routes.py mbr/templates/admin/parametry.html mbr/templates/base.html
git commit -m "feat: admin panel for global parameter management"
```

---

### Task 6: Admin panel — Normy (dopuszczalne + target per produkt)

**Files:**
- Create: `mbr/templates/admin/normy.html`
- Modify: `mbr/zbiorniki/routes.py`

- [ ] **Step 1: Add routes**

```python
@zbiorniki_bp.route("/admin/normy")
@role_required("admin")
def admin_normy():
    return render_template("admin/normy.html")

@zbiorniki_bp.route("/api/normy/<produkt>")
@role_required("admin")
def api_normy(produkt):
    with db_session() as db:
        rows = db.execute("""
            SELECT pe.id, pe.parametr_id, pa.kod, pa.label, pa.skrot, pa.typ, pa.jednostka,
                   pe.min_limit, pe.max_limit, pe.target, pe.nawazka_g, pe.kolejnosc
            FROM parametry_etapy pe
            JOIN parametry_analityczne pa ON pa.id = pe.parametr_id
            WHERE pe.kontekst = 'analiza_koncowa' AND (pe.produkt = ? OR pe.produkt IS NULL)
            ORDER BY pe.kolejnosc
        """, (produkt,)).fetchall()
    return jsonify([dict(r) for r in rows])

@zbiorniki_bp.route("/api/normy/<int:binding_id>", methods=["PUT"])
@role_required("admin")
def api_normy_update(binding_id):
    data = request.get_json(silent=True) or {}
    allowed = {"min_limit", "max_limit", "target"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"ok": True})
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with db_session() as db:
        db.execute(f"UPDATE parametry_etapy SET {set_clause} WHERE id = ?",
                   [*updates.values(), binding_id])
        db.commit()
    return jsonify({"ok": True})
```

- [ ] **Step 2: Create normy template**

Create `mbr/templates/admin/normy.html` — product dropdown at top, then table of parameters with min, target (highlighted teal), max columns. Inline editable. Target column styled with mono font + teal color.

- [ ] **Step 3: Commit**

```bash
git add mbr/zbiorniki/routes.py mbr/templates/admin/normy.html
git commit -m "feat: admin panel for normy (dopuszczalne + golden batch target)"
```

---

### Task 7: Admin panel — Etapy editor

**Files:**
- Create: `mbr/templates/admin/etapy.html`
- Modify: `mbr/zbiorniki/routes.py`
- Modify: `mbr/templates/base.html`

- [ ] **Step 1: Add routes**

```python
@zbiorniki_bp.route("/admin/etapy")
@role_required("admin")
def admin_etapy():
    return render_template("admin/etapy.html")

@zbiorniki_bp.route("/api/etapy-procesowe")
@role_required("admin")
def api_etapy_list():
    with db_session() as db:
        etapy = [dict(r) for r in db.execute("SELECT * FROM etapy_procesowe ORDER BY kod").fetchall()]
        bindings = [dict(r) for r in db.execute("SELECT * FROM produkt_etapy ORDER BY produkt, kolejnosc").fetchall()]
    return jsonify({"etapy": etapy, "bindings": bindings})

@zbiorniki_bp.route("/api/etapy-procesowe/<int:eid>", methods=["PUT"])
@role_required("admin")
def api_etapy_update(eid):
    data = request.get_json(silent=True) or {}
    allowed = {"label", "aktywny"}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates:
        return jsonify({"ok": True})
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with db_session() as db:
        db.execute(f"UPDATE etapy_procesowe SET {set_clause} WHERE id = ?", [*updates.values(), eid])
        db.commit()
    return jsonify({"ok": True})

@zbiorniki_bp.route("/api/etapy-procesowe", methods=["POST"])
@role_required("admin")
def api_etapy_create():
    data = request.get_json(silent=True) or {}
    kod = data.get("kod", "").strip()
    label = data.get("label", "").strip()
    if not kod or not label:
        return jsonify({"error": "kod and label required"}), 400
    with db_session() as db:
        try:
            cur = db.execute("INSERT INTO etapy_procesowe (kod, label) VALUES (?, ?)", (kod, label))
            db.commit()
        except Exception:
            return jsonify({"error": "Etap already exists"}), 409
    return jsonify({"ok": True, "id": cur.lastrowid})
```

- [ ] **Step 2: Create etapy template**

Create `mbr/templates/admin/etapy.html` — list of stages with inline label editing + aktywny toggle. Below: product-stage assignments table.

- [ ] **Step 3: Add rail icon**

In `mbr/templates/base.html`, admin rail, add Etapy icon:

```html
<a class="rail-btn {% block nav_etapy %}{% endblock %}" href="{{ url_for('zbiorniki.admin_etapy') }}" title="Etapy"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z"/><path d="M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12"/><path d="M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17"/></svg><span class="rail-label">Etapy</span></a>
```

- [ ] **Step 4: Commit**

```bash
git add mbr/zbiorniki/routes.py mbr/templates/admin/etapy.html mbr/templates/base.html
git commit -m "feat: admin panel for process stages (etapy) management"
```

---

### Task 8: Fast entry — binary pill buttons + target hint

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Add binary parameter rendering**

In the section that renders fields (find where `isTitr` is checked and input is built), add handling for binary type. Find the field rendering loop (around line 1525+ in `pola.forEach`), and before the input element, add:

```javascript
var isBinary = pole.measurement_type === 'binarny' || pole.typ === 'binarny';
```

Then in the HTML building, if `isBinary`, render pills instead of input:

```javascript
if (isBinary) {
    var bVal = val || '';
    fieldsHtml +=
        '<div class="ff binary' + highlightCls + '">' +
            '<div class="status-dot"></div>' +
            '<label>' + esc(pole.skrot || pole.label) + '</label>' +
            '<div class="binary-pills">' +
                '<button type="button" class="bp-pill' + (bVal === 'OK' ? ' bp-ok' : '') + '" onclick="setBinary(this,\'' + esc(sekcja) + '\',\'' + esc(pole.kod) + '\',\'OK\')">OK</button>' +
                '<button type="button" class="bp-pill' + (bVal === 'Nie OK' ? ' bp-err' : '') + '" onclick="setBinary(this,\'' + esc(sekcja) + '\',\'' + esc(pole.kod) + '\',\'Nie OK\')">Nie OK</button>' +
            '</div>' +
        '</div>';
} else {
    // existing input rendering
}
```

- [ ] **Step 2: Add setBinary JS function**

```javascript
function setBinary(btn, sekcja, kod, value) {
    var container = btn.closest('.binary-pills');
    container.querySelectorAll('.bp-pill').forEach(function(p) {
        p.classList.remove('bp-ok', 'bp-err');
    });
    btn.classList.add(value === 'OK' ? 'bp-ok' : 'bp-err');
    // Save
    var values = {};
    values[kod] = { wartosc: value === 'OK' ? 1 : 0, wartosc_text: value, komentarz: '' };
    fetch('/laborant/ebr/' + ebrId + '/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sekcja: sekcja, values: values})
    });
}
```

- [ ] **Step 3: Add target hint display**

In the field rendering (for non-binary fields), after the input, add target hint if present:

```javascript
var targetHint = '';
if (pole.target != null) {
    var normRange = '';
    if (pole.min != null && pole.max != null) normRange = ' (' + pole.min + '–' + pole.max + ')';
    targetHint = '<div class="target-hint">cel: <strong>' + String(pole.target).replace('.', ',') + '</strong>' + normRange + '</div>';
}
```

Insert `targetHint` after the input element in the HTML.

- [ ] **Step 4: Add CSS**

In `mbr/static/style.css`, add:

```css
/* Binary parameter pills */
.ff.binary { }
.binary-pills { display: flex; gap: 4px; }
.bp-pill {
  padding: 6px 14px; border-radius: 6px;
  border: 1.5px solid var(--border);
  background: var(--surface); cursor: pointer;
  font-size: 11px; font-weight: 600; font-family: var(--font);
  transition: all 0.15s;
}
.bp-pill:hover { border-color: var(--text-sec); }
.bp-pill.bp-ok {
  border-color: var(--green); background: var(--green-bg); color: var(--green);
}
.bp-pill.bp-err {
  border-color: var(--red); background: var(--red-bg); color: var(--red);
}

/* Target hint */
.target-hint {
  font-size: 9px; color: var(--text-dim); margin-top: 2px;
  font-family: var(--mono);
}
.target-hint strong { color: var(--teal); }
```

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html mbr/static/style.css
git commit -m "feat: binary OK/Nie OK pills + golden batch target hint in fast entry"
```
