# UI Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Six independent UI improvements: registry type filter, "Narzędzia" nav tab, shift worker modal, auto-save on debounce/blur, remove references panel, move nastaw to batch creation.

**Architecture:** Each task is independent and can be implemented in any order. All changes follow existing Flask/Jinja2/vanilla JS patterns. No new dependencies.

**Tech Stack:** Python/Flask, SQLite, Jinja2, vanilla JS, HTML/CSS

**Spec:** `docs/superpowers/specs/2026-04-03-ui-improvements-design.md`

---

## File Structure

| File | Action | Tasks |
|------|--------|-------|
| `mbr/models.py` | Modify | T1 (registry filter), T3 (workers table), T6 (nastaw column) |
| `mbr/app.py` | Modify | T1 (api param), T2 (narzedzia route), T3 (shift endpoints), T6 (nastaw in create) |
| `mbr/seed_mbr.py` | Modify | T3 (seed workers), T6 (remove nastaw from analiza) |
| `mbr/templates/base.html` | Modify | T2 (nav button), T3 (shift indicator) |
| `mbr/templates/laborant/szarze_list.html` | Modify | T1 (registry filter UI) |
| `mbr/templates/laborant/_fast_entry_content.html` | Modify | T4 (autosave), T5 (remove refs) |
| `mbr/templates/laborant/_modal_nowa_szarza.html` | Modify | T6 (nastaw field) |
| `mbr/templates/technolog/narzedzia.html` | Create | T2 (tools page) |
| `mbr/templates/technolog/wniosek_dojazd.html` | Create | T2 (expense form) |
| `mbr/pdf_gen.py` | Modify | T2 (expense PDF) |

---

### Task 1: Registry — filtr zbiornik/szarża

**Files:**
- Modify: `mbr/app.py:249-256`
- Modify: `mbr/models.py:499-526` (list_completed_registry)
- Modify: `mbr/templates/laborant/szarze_list.html` (registry UI)

- [ ] **Step 1: Add `typ` filter to `list_completed_registry`**

In `mbr/models.py`, find `list_completed_registry` (line 499). Add `typ` parameter:

```python
def list_completed_registry(
    db: sqlite3.Connection, produkt: str | None = None, typ: str | None = None, limit: int = 100
) -> list[dict]:
    """Get completed batches with all wyniki for registry table view."""
    sql = """
        SELECT eb.ebr_id, eb.batch_id, eb.nr_partii, mt.produkt, eb.dt_end, eb.typ
        FROM ebr_batches eb
        JOIN mbr_templates mt ON mt.mbr_id = eb.mbr_id
        WHERE eb.status = 'completed'
    """
    params: list = []
    if produkt:
        sql += " AND mt.produkt = ?"
        params.append(produkt)
    if typ:
        sql += " AND eb.typ = ?"
        params.append(typ)
    sql += " ORDER BY eb.dt_end DESC LIMIT ?"
    params.append(limit)
```

Rest of function stays the same.

- [ ] **Step 2: Pass `typ` in API route**

In `mbr/app.py`, update the `/api/registry` route (line 249):

```python
@app.route("/api/registry")
@login_required
def api_registry():
    produkt = request.args.get("produkt", "Chegina_K7")
    typ = request.args.get("typ", "")
    with db_session() as db:
        batches = list_completed_registry(db, produkt=produkt, typ=typ or None)
        columns = get_registry_columns(db, produkt)
    return jsonify({"batches": batches, "columns": columns, "produkt": produkt})
```

- [ ] **Step 3: Add filter UI to registry header**

In `mbr/templates/laborant/szarze_list.html`, find the `<div class="completed-header">` section (around line 234). Add a type segmented control after the `ch-tabs` div:

```html
    <div class="ch-typ-filter" style="padding:0 16px 8px;">
      <div class="sb-seg" style="width:fit-content;">
        <div class="sb-pill" data-regtyp="szarza" onclick="filterRegistryType('szarza',this)">Szarze</div>
        <div class="sb-pill" data-regtyp="zbiornik" onclick="filterRegistryType('zbiornik',this)">Zbiorniki</div>
      </div>
    </div>
```

- [ ] **Step 4: Add JS for registry type filter**

In the `<script>` block, add after `loadRegistry` function:

```javascript
let registryTyp = 'szarza'; // default

function filterRegistryType(typ, btn) {
  registryTyp = typ;
  btn.parentElement.querySelectorAll('.sb-pill').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  // Reload current product with type filter
  var activeTab = document.querySelector('#ch-tabs .ch-tab.active');
  var produkt = activeTab ? activeTab.dataset.product : 'Chegina_K7';
  loadRegistry(produkt);
}
```

Update `loadRegistry` to pass typ:

Find `var resp = await fetch('/api/registry?produkt=' + encodeURIComponent(produkt));` and replace with:

```javascript
var resp = await fetch('/api/registry?produkt=' + encodeURIComponent(produkt) + (registryTyp ? '&typ=' + registryTyp : ''));
```

- [ ] **Step 5: Set default filter to szarza on registry open**

In `showRegistry` function, after setting display, add:

```javascript
  // Default to szarza filter
  registryTyp = 'szarza';
  var typBtns = document.querySelectorAll('.ch-typ-filter .sb-pill');
  typBtns.forEach(function(b) { b.classList.toggle('active', b.dataset.regtyp === 'szarza'); });
```

- [ ] **Step 6: Commit**

```bash
git add mbr/models.py mbr/app.py mbr/templates/laborant/szarze_list.html
git commit -m "feat: registry type filter — szarze/zbiorniki with szarza as default"
```

---

### Task 2: Zakładka "Narzędzia" + wniosek o zwrot kosztów

**Files:**
- Modify: `mbr/templates/base.html:16-18` (add nav button for technolog)
- Modify: `mbr/app.py` (add routes)
- Create: `mbr/templates/technolog/narzedzia.html`
- Create: `mbr/templates/technolog/wniosek_dojazd.html`
- Modify: `mbr/pdf_gen.py` (add expense PDF generation)

- [ ] **Step 1: Add "Narzędzia" button to rail for technolog**

In `mbr/templates/base.html`, find the technolog section (lines 16-18):

```html
{% if session.get('user', {}).get('rola') == 'technolog' %}
  <a class="rail-btn {% block nav_szablony %}{% endblock %}" href="{{ url_for('mbr_list') }}">
    <svg ...>...</svg><span class="rail-label">Szablony</span>
  </a>
  <a class="rail-btn {% block nav_dashboard %}{% endblock %}" href="{{ url_for('tech_dashboard') }}">
    <svg ...>...</svg><span class="rail-label">Dashboard</span>
  </a>
```

Add after the Dashboard button (before the `{% endif %}`):

```html
  <a class="rail-btn {% block nav_narzedzia %}{% endblock %}" href="{{ url_for('narzedzia') }}">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" style="width:20px;height:20px;"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/></svg>
    <span class="rail-label">Narzędzia</span>
  </a>
```

- [ ] **Step 2: Create narzedzia.html template**

Create `mbr/templates/technolog/narzedzia.html`:

```html
{% extends "base.html" %}

{% block title %}Narzędzia{% endblock %}
{% block nav_narzedzia %}active{% endblock %}

{% block content %}
<div style="padding:24px; max-width:800px;">
  <h2 style="font-size:18px; font-weight:600; margin-bottom:20px;">Narzędzia</h2>

  <div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(220px, 1fr)); gap:14px;">
    <a href="{{ url_for('wniosek_dojazd') }}" class="tool-card">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" style="width:28px;height:28px;color:var(--teal);"><path d="M9 17H5a2 2 0 01-2-2V5a2 2 0 012-2h14a2 2 0 012 2v10a2 2 0 01-2 2h-4"/><path d="M12 15v6"/><path d="M8 21h8"/></svg>
      <div class="tc-name">Wniosek o zwrot kosztów</div>
      <div class="tc-desc">Dojazd samochodem prywatnym</div>
    </a>
  </div>
</div>

<style>
.tool-card {
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  padding: 24px 16px; border: 1.5px solid var(--border); border-radius: var(--radius);
  background: var(--surface); text-decoration: none; color: var(--text);
  transition: border-color 0.15s, box-shadow 0.15s; cursor: pointer; text-align: center;
}
.tool-card:hover { border-color: var(--teal); box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.tc-name { font-size: 13px; font-weight: 600; }
.tc-desc { font-size: 11px; color: var(--text-dim); }
</style>
{% endblock %}
```

- [ ] **Step 3: Create wniosek_dojazd.html template**

Create `mbr/templates/technolog/wniosek_dojazd.html`:

```html
{% extends "base.html" %}

{% block title %}Wniosek o zwrot kosztów{% endblock %}
{% block nav_narzedzia %}active{% endblock %}

{% block content %}
<div style="padding:24px; max-width:600px;">
  <a href="{{ url_for('narzedzia') }}" style="font-size:12px; color:var(--text-dim); text-decoration:none; margin-bottom:16px; display:inline-block;">&larr; Narzędzia</a>
  <h2 style="font-size:18px; font-weight:600; margin-bottom:20px;">Wniosek o zwrot kosztów dojazdu</h2>

  <form method="POST" action="{{ url_for('wniosek_dojazd_pdf') }}" target="_blank">
    <div style="display:flex; flex-direction:column; gap:14px;">
      <div>
        <label class="form-label">Imię i nazwisko</label>
        <input class="form-input" name="imie_nazwisko" value="{{ session.get('user',{}).get('imie_nazwisko','') }}" required style="width:100%;">
      </div>
      <div>
        <label class="form-label">Data</label>
        <input class="form-input" type="date" name="data" value="{{ today }}" required style="width:100%;">
      </div>
      <div style="display:flex; gap:12px;">
        <div style="flex:1;">
          <label class="form-label">Skąd</label>
          <input class="form-input" name="skad" required style="width:100%;">
        </div>
        <div style="flex:1;">
          <label class="form-label">Dokąd</label>
          <input class="form-input" name="dokad" required style="width:100%;">
        </div>
      </div>
      <div style="display:flex; gap:12px;">
        <div style="flex:1;">
          <label class="form-label">Kilometry</label>
          <input class="form-input" type="number" step="0.1" name="km" required style="width:100%;">
        </div>
        <div style="flex:1;">
          <label class="form-label">Stawka za km [zł]</label>
          <input class="form-input" type="number" step="0.01" name="stawka" value="0.8358" required style="width:100%;">
        </div>
      </div>
      <div>
        <label class="form-label">Cel wyjazdu</label>
        <input class="form-input" name="cel" value="Dojazd do pracy" style="width:100%;">
      </div>
      <button type="submit" class="btn btn-p" style="align-self:flex-end; margin-top:8px;">Generuj PDF</button>
    </div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 4: Add routes to app.py**

Add to `mbr/app.py`, in the technolog section:

```python
@app.route("/technolog/narzedzia")
@role_required("technolog")
def narzedzia():
    return render_template("technolog/narzedzia.html", today=date.today().isoformat())


@app.route("/technolog/narzedzia/wniosek-dojazd")
@role_required("technolog")
def wniosek_dojazd():
    return render_template("technolog/wniosek_dojazd.html", today=date.today().isoformat())


@app.route("/technolog/narzedzia/wniosek-dojazd/pdf", methods=["POST"])
@role_required("technolog")
def wniosek_dojazd_pdf():
    from mbr.pdf_gen import generate_wniosek_dojazd_pdf
    data = {
        "imie_nazwisko": request.form.get("imie_nazwisko", ""),
        "data": request.form.get("data", ""),
        "skad": request.form.get("skad", ""),
        "dokad": request.form.get("dokad", ""),
        "km": float(request.form.get("km", 0)),
        "stawka": float(request.form.get("stawka", 0.8358)),
        "cel": request.form.get("cel", ""),
    }
    data["kwota"] = round(data["km"] * data["stawka"], 2)
    pdf_bytes = generate_wniosek_dojazd_pdf(data)
    return Response(pdf_bytes, mimetype="application/pdf",
                    headers={"Content-Disposition": "inline; filename=wniosek_dojazd.pdf"})
```

Add `from datetime import date` to imports if not present. Add `from flask import Response` if not present.

- [ ] **Step 5: Add PDF generation function**

In `mbr/pdf_gen.py`, add function `generate_wniosek_dojazd_pdf(data: dict) -> bytes`. This should generate a simple A4 PDF with:
- Header: "Wniosek o zwrot kosztów dojazdu samochodem prywatnym"
- Table with fields: Data, Imię i nazwisko, Trasa (skąd → dokąd), Km, Stawka, Kwota, Cel
- Footer: place for signature, date
- Use existing PDF generation patterns from pdf_gen.py (fpdf2 or reportlab, whichever is already used)

Read the current `mbr/pdf_gen.py` to see what library is used and follow the same pattern.

- [ ] **Step 6: Commit**

```bash
git add mbr/templates/base.html mbr/templates/technolog/narzedzia.html mbr/templates/technolog/wniosek_dojazd.html mbr/app.py mbr/pdf_gen.py
git commit -m "feat: Narzędzia tab with wniosek o zwrot kosztów dojazdu PDF"
```

---

### Task 3: System zmianowy — modal operatora

**Files:**
- Modify: `mbr/models.py` (workers table, CRUD)
- Modify: `mbr/seed_mbr.py` (seed workers)
- Modify: `mbr/app.py` (shift endpoints)
- Modify: `mbr/templates/base.html` (shift indicator + modal)

- [ ] **Step 1: Add workers table to models.py**

In `mbr/models.py`, in `init_mbr_tables`, add after existing CREATE TABLE statements:

```python
    db.execute("""
        CREATE TABLE IF NOT EXISTS workers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            imie        TEXT NOT NULL,
            nazwisko    TEXT NOT NULL,
            inicjaly    TEXT NOT NULL,
            nickname    TEXT DEFAULT '',
            aktywny     INTEGER NOT NULL DEFAULT 1
        )
    """)
```

Add helper functions:

```python
def list_workers(db: sqlite3.Connection, aktywny: bool = True) -> list[dict]:
    """List workers, optionally filtered by active status."""
    sql = "SELECT * FROM workers"
    if aktywny:
        sql += " WHERE aktywny = 1"
    sql += " ORDER BY nazwisko, imie"
    return [dict(r) for r in db.execute(sql).fetchall()]


def update_worker_nickname(db: sqlite3.Connection, worker_id: int, nickname: str) -> None:
    db.execute("UPDATE workers SET nickname = ? WHERE id = ?", (nickname, worker_id))
    db.commit()
```

- [ ] **Step 2: Seed workers in seed_mbr.py**

In `mbr/seed_mbr.py`, in the `seed()` function (after user creation), add:

```python
    # Seed workers (skip if already exist)
    existing_workers = db.execute("SELECT COUNT(*) FROM workers").fetchone()[0]
    if existing_workers == 0:
        workers = [
            # Add actual workers here — placeholder initials
            ("Imie1", "Nazwisko1", "IN"),
            ("Imie2", "Nazwisko2", "IN"),
        ]
        for imie, nazwisko, inicjaly in workers:
            db.execute(
                "INSERT INTO workers (imie, nazwisko, inicjaly) VALUES (?, ?, ?)",
                (imie, nazwisko, inicjaly),
            )
        db.commit()
        print(f"  + {len(workers)} workers seeded")
```

Note: The actual worker names need to be provided by the user. Use placeholders that will be replaced.

- [ ] **Step 3: Add shift API endpoints to app.py**

```python
@app.route("/api/workers")
@login_required
def api_workers():
    with db_session() as db:
        workers = list_workers(db)
    return jsonify({"workers": workers})


@app.route("/api/shift", methods=["GET", "POST"])
@login_required
def api_shift():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        worker_ids = data.get("worker_ids", [])
        session["shift_workers"] = worker_ids
        return jsonify({"ok": True})
    return jsonify({"worker_ids": session.get("shift_workers", [])})


@app.route("/api/worker/<int:worker_id>/nickname", methods=["POST"])
@login_required
def api_worker_nickname(worker_id):
    data = request.get_json(silent=True) or {}
    nickname = data.get("nickname", "")
    with db_session() as db:
        update_worker_nickname(db, worker_id, nickname)
    return jsonify({"ok": True})
```

Add `list_workers, update_worker_nickname` to imports from models.

- [ ] **Step 4: Add shift indicator and modal to base.html**

In `mbr/templates/base.html`, find the user avatar section at the bottom of the rail (around line 34). Before the avatar, add:

```html
    <div class="rail-shift" id="shift-indicator" onclick="openShiftModal()" title="Zmiana">
      <span id="shift-initials">--</span>
    </div>
```

At the end of `<body>`, before `</body>`, add the modal:

```html
<!-- Shift modal -->
<div class="modal-overlay" id="shift-overlay" style="display:none;" onclick="if(event.target===this)closeShiftModal()">
  <div class="modal" style="max-width:380px;">
    <div class="modal-header">
      <span class="modal-title">Kto jest na zmianie?</span>
      <button class="modal-close" onclick="closeShiftModal()">&times;</button>
    </div>
    <div class="modal-body" id="shift-worker-list" style="padding:16px;">
      Ładowanie...
    </div>
    <div class="modal-footer" style="padding:12px 16px;">
      <button class="btn btn-p" onclick="saveShift()">Potwierdź</button>
    </div>
  </div>
</div>

<!-- Shift reminder banner -->
<div id="shift-reminder" style="display:none; position:fixed; top:0; left:0; right:0; z-index:9999;
  background:var(--amber-bg, #fef3c7); color:var(--amber, #92400e); padding:8px 16px;
  font-size:12px; font-weight:500; text-align:center; cursor:pointer; border-bottom:1px solid #f59e0b;"
  onclick="openShiftModal()">
  ⏰ Zmiana — potwierdź kto jest na zmianie
</div>

<script>
// Shift management
let shiftWorkerIds = {{ session.get('shift_workers', []) | tojson }};

async function openShiftModal() {
  document.getElementById('shift-overlay').style.display = 'flex';
  const resp = await fetch('/api/workers');
  const data = await resp.json();
  const list = document.getElementById('shift-worker-list');
  list.innerHTML = data.workers.map(w => {
    const checked = shiftWorkerIds.includes(w.id) ? 'checked' : '';
    const display = w.nickname || (w.imie + ' ' + w.nazwisko);
    return '<label style="display:flex;align-items:center;gap:8px;padding:6px 0;cursor:pointer;">' +
      '<input type="checkbox" class="shift-cb" value="' + w.id + '" ' + checked + '>' +
      '<span style="font-weight:500;">' + w.inicjaly + '</span>' +
      '<span style="color:var(--text-dim);font-size:12px;">' + display + '</span></label>';
  }).join('');
}

function closeShiftModal() { document.getElementById('shift-overlay').style.display = 'none'; }

async function saveShift() {
  const ids = Array.from(document.querySelectorAll('.shift-cb:checked')).map(cb => parseInt(cb.value));
  shiftWorkerIds = ids;
  await fetch('/api/shift', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({worker_ids: ids}) });
  updateShiftIndicator();
  closeShiftModal();
  localStorage.setItem('lastShiftConfirm', Date.now().toString());
  document.getElementById('shift-reminder').style.display = 'none';
}

function updateShiftIndicator() {
  const el = document.getElementById('shift-initials');
  if (!el) return;
  // Fetch worker details is overkill — just show count or stored initials
  el.textContent = shiftWorkerIds.length > 0 ? shiftWorkerIds.length + ' os.' : '--';
}

// Shift reminder check (6:00, 14:00, 22:00)
function checkShiftReminder() {
  const h = new Date().getHours();
  const shiftHours = [6, 14, 22];
  const isShiftHour = shiftHours.includes(h);
  const lastConfirm = parseInt(localStorage.getItem('lastShiftConfirm') || '0');
  const minutesSinceConfirm = (Date.now() - lastConfirm) / 60000;
  // Show reminder if it's a shift hour and not confirmed in last 30 minutes
  if (isShiftHour && minutesSinceConfirm > 30) {
    document.getElementById('shift-reminder').style.display = '';
  } else {
    document.getElementById('shift-reminder').style.display = 'none';
  }
}

updateShiftIndicator();
checkShiftReminder();
setInterval(checkShiftReminder, 60000);
</script>

<style>
.rail-shift {
  width: 36px; height: 36px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: var(--surface-alt); color: var(--text-dim);
  font-size: 10px; font-weight: 600; cursor: pointer;
  border: 1.5px solid var(--border); transition: border-color 0.15s;
}
.rail-shift:hover { border-color: var(--teal); color: var(--teal); }
</style>
```

- [ ] **Step 5: Update save_wyniki to use shift workers**

In `mbr/app.py`, update the `save_entry` route (line 330) to use shift workers instead of login:

```python
    # Use shift workers if set, otherwise fall back to login
    shift_ids = session.get("shift_workers", [])
    if shift_ids:
        with db_session() as db2:
            workers = db2.execute(
                f"SELECT inicjaly, nickname FROM workers WHERE id IN ({','.join('?' * len(shift_ids))})",
                shift_ids
            ).fetchall()
            user = ", ".join(w["nickname"] or w["inicjaly"] for w in workers)
    else:
        user = session["user"]["login"]
```

Replace the existing `user = session["user"]["login"]` line in `save_entry`.

- [ ] **Step 6: Commit**

```bash
git add mbr/models.py mbr/seed_mbr.py mbr/app.py mbr/templates/base.html
git commit -m "feat: shift worker system — modal, indicator, reminder at 6/14/22"
```

---

### Task 4: Auto-zapis (debounce + blur)

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Add autosave function**

In the `<script>` block, after the `saveSection` function, add:

```javascript
var _saveTimers = {};
var _savingIndicators = {};

function autoSaveField(input) {
    var sekcja = input.dataset.sekcja;
    var kod = input.dataset.kod;
    if (!sekcja || !kod) return;
    var key = sekcja + '__' + kod;

    // Clear existing timer
    if (_saveTimers[key]) clearTimeout(_saveTimers[key]);

    // Set debounce timer
    _saveTimers[key] = setTimeout(function() {
        doSaveField(input, sekcja, kod);
    }, 1500);
}

function doSaveField(input, sekcja, kod) {
    if (input.value === '') return;
    var komentarz = document.querySelector('textarea[data-komentarz="' + kod + '"][data-sekcja="' + sekcja + '"]');
    var values = {};
    values[kod] = {
        wartosc: input.value,
        komentarz: komentarz ? komentarz.value : ""
    };

    // Show saving indicator
    input.style.outline = '2px solid var(--teal)';

    fetch('/laborant/ebr/' + ebrId + '/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sekcja: sekcja, values: values})
    }).then(function(resp) {
        if (resp.ok) {
            // Brief success flash
            input.style.outline = '2px solid var(--green)';
            setTimeout(function() { input.style.outline = ''; }, 800);
        } else {
            input.style.outline = '2px solid var(--red)';
            setTimeout(function() { input.style.outline = ''; }, 2000);
        }
    }).catch(function() {
        input.style.outline = '2px solid var(--red)';
        setTimeout(function() { input.style.outline = ''; }, 2000);
    });
}
```

- [ ] **Step 2: Wire up input events**

In the `renderOneSection` function, find where `<input>` elements are created (the `oninput="validateField(this)"` attribute). Change the oninput and add onblur:

Replace:
```
oninput="validateField(this)"
```
With:
```
oninput="validateField(this); autoSaveField(this)" onblur="autoSaveField(this)"
```

- [ ] **Step 3: Remove "Zapisz" section buttons for cyclic products**

In `renderOneSection`, find where `saveBtnLabel` is used to create the save button. Wrap it in a condition:

```javascript
    // Save button — only for linear products (cyclic uses autosave)
    if (opts.saveBtnLabel && !isCyclicProduct()) {
        // existing save button code
    }
```

Actually, apply autosave to ALL products (cyclic and linear). Remove section save buttons entirely. Find the save button HTML generation and remove it. The `saveBtnLabel` option becomes unused.

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: auto-save fields on debounce 1.5s and blur — remove save buttons"
```

---

### Task 5: Prawy panel — usunięcie referencji

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Remove Referencje tab, keep only Kalkulator**

Replace the right panel tabs section (around lines 26-40):

```html
  <div class="col-right">
    <div class="rp-tabs">
      <div class="rp-tab active" id="tab-calc">Kalkulator</div>
    </div>
    <div class="rp-body">
      <div class="rp-view active" id="rp-calc">
        <div id="calc-container">
          <div class="calc-method">Kliknij pole miareczkowe aby otworzyc kalkulator.</div>
        </div>
        <div style="margin-top:24px; padding:12px; border-top:1px solid var(--border);">
          <div style="font-size:11px; font-weight:600; color:var(--text-dim); margin-bottom:4px;">Wartości historyczne</div>
          <div style="font-size:11px; color:var(--text-dim);">Dane pojawią się po zebraniu wystarczającej liczby szarż.</div>
        </div>
      </div>
    </div>
  </div>
```

- [ ] **Step 2: Remove renderReferences function and calls**

Delete the `renderReferences()` function entirely (around lines 458-543).

Remove the call `renderReferences();` from the init block at the bottom.

Remove the `_refBridge` event listener that opens the ref panel on field click.

Remove the `showRightPanel` function and all references to `tab-ref` and `rp-ref`.

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: remove Referencje panel, keep Kalkulator with historical data placeholder"
```

---

### Task 6: Nastaw — wymagany przy tworzeniu szarży

**Files:**
- Modify: `mbr/seed_mbr.py` (remove nastaw from analiza pola)
- Modify: `mbr/models.py` (add nastaw column, update create_ebr)
- Modify: `mbr/app.py` (pass nastaw from form)
- Modify: `mbr/templates/laborant/_modal_nowa_szarza.html` (add nastaw field)

- [ ] **Step 1: Add nastaw column to ebr_batches**

In `mbr/models.py`, in `init_mbr_tables`, after the CREATE TABLE for ebr_batches, add migration:

```python
    # Migration: add nastaw column if not exists
    cols = [r[1] for r in db.execute("PRAGMA table_info(ebr_batches)").fetchall()]
    if "nastaw" not in cols:
        db.execute("ALTER TABLE ebr_batches ADD COLUMN nastaw INTEGER")
```

Also update the CREATE TABLE to include nastaw for fresh DBs:

```sql
    nastaw              INTEGER,
```

Add it after the `typ` column line.

- [ ] **Step 2: Update create_ebr to accept nastaw**

In `mbr/models.py`, update `create_ebr` signature (line 596):

```python
def create_ebr(
    db: sqlite3.Connection,
    produkt: str,
    nr_partii: str,
    nr_amidatora: str,
    nr_mieszalnika: str,
    wielkosc_kg: float | None,
    operator: str,
    typ: str = 'szarza',
    nastaw: int | None = None,
) -> int | None:
```

Update the INSERT statement to include nastaw:

```python
    cur = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, nr_amidatora, "
        "nr_mieszalnika, wielkosc_szarzy_kg, dt_start, operator, typ, nastaw) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (mbr["mbr_id"], batch_id, nr_partii, nr_amidatora,
         nr_mieszalnika, wielkosc_kg, now, operator, typ, nastaw),
    )
```

- [ ] **Step 3: Pass nastaw from form in app.py**

In `mbr/app.py`, update `szarze_new` (line 272):

```python
        nastaw_raw = request.form.get("nastaw", "")
        nastaw = int(nastaw_raw) if nastaw_raw else None
        ebr_id = create_ebr(
            db,
            produkt=request.form["produkt"],
            nr_partii=request.form["nr_partii"],
            nr_amidatora=request.form.get("nr_amidatora", ""),
            nr_mieszalnika=request.form.get("nr_mieszalnika", ""),
            wielkosc_kg=float(request.form.get("wielkosc_kg", 0) or 0),
            operator=session["user"]["login"],
            typ=typ,
            nastaw=nastaw,
        )
```

- [ ] **Step 4: Add nastaw field to modal**

In `mbr/templates/laborant/_modal_nowa_szarza.html`, find the szarża form (Step 2a). After the "Wielkosc szarzy" field, add:

```html
        <div class="nf-field">
          <label class="form-label">Nastaw</label>
          <input class="form-input" type="number" name="nastaw" required
                 placeholder="Nastaw..." style="width:100%;">
        </div>
```

- [ ] **Step 5: Remove nastaw from seed_mbr.py analiza sections**

In `mbr/seed_mbr.py`, remove `_nastaw()` from the `analiza.pola` list in all products where it appears. The products are: Chegina_K40GL, K40GLO, K40GLOL, K7, K40GLOS, K40GLOL_HQ, K7GLO, KK, CC, CCR.

For each product, find the `_nastaw(),` line in the `analiza` (or `analiza_koncowa`) pola list and delete it.

- [ ] **Step 6: Run seed update**

```bash
python -m mbr.seed_mbr --update
```

- [ ] **Step 7: Commit**

```bash
git add mbr/models.py mbr/app.py mbr/seed_mbr.py mbr/templates/laborant/_modal_nowa_szarza.html
git commit -m "feat: nastaw required at batch creation, removed from analiza fields"
```
