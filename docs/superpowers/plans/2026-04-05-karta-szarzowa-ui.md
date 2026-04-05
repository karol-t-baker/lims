# Batch Card UI — Process Stages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add interactive process-stage forms (amidowanie → utlenienie/rozjaśnianie) to the batch card UI, with sequential navigation, correction workflow, and stage approval.

**Architecture:** New `ebr_etapy_status` table tracks stage progress. Backend initializes stages at EBR creation. Frontend renders stage forms (same style as standaryzacja) with auto-save, correction panel, and "Zatwierdź etap" button. Sidebar pipeline becomes clickable for process stages.

**Tech Stack:** Python/Flask, SQLite3, Jinja2, vanilla JS (existing LIMS stack)

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `mbr/models.py` | MODIFY | Add CREATE TABLE ebr_etapy_status |
| `mbr/etapy_models.py` | MODIFY | Add init/get/zatwierdz stage status functions |
| `mbr/app.py` | MODIFY | Add 2 endpoints + init stages at EBR creation |
| `mbr/templates/laborant/_fast_entry_content.html` | MODIFY | Process stage form rendering |
| `mbr/templates/laborant/szarze_list.html` | MODIFY | Clickable pipeline sidebar |

---

### Task 1: Add ebr_etapy_status Table + Model Functions

**Files:**
- Modify: `mbr/models.py`
- Modify: `mbr/etapy_models.py`

- [ ] **Step 1: Add CREATE TABLE to models.py**

In `mbr/models.py`, inside `init_mbr_tables`'s `db.executescript(...)`, add after the `ebr_korekty` CREATE TABLE:

```sql
CREATE TABLE IF NOT EXISTS ebr_etapy_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ebr_id INTEGER NOT NULL,
    etap TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    dt_start TEXT,
    dt_end TEXT,
    zatwierdzil TEXT,
    UNIQUE(ebr_id, etap)
);
```

- [ ] **Step 2: Add stage status functions to etapy_models.py**

Append to `mbr/etapy_models.py`:

```python
# ---------------------------------------------------------------------------
# Stage status tracking
# ---------------------------------------------------------------------------

# Process stages that get tracked (before standaryzacja)
PROCESS_STAGES_K7 = ["amidowanie", "smca", "czwartorzedowanie", "sulfonowanie", "utlenienie"]
PROCESS_STAGES_GLOL = ["amidowanie", "smca", "czwartorzedowanie", "sulfonowanie", "utlenienie", "rozjasnianie"]

GLOL_PRODUCTS = {"Chegina_K40GLOL", "Chegina_K40GLOS", "Chegina_K40GLOL_HQ", "Chegina_K40GLN", "Chegina_GLOL40"}


def get_process_stages(produkt: str) -> list[str]:
    """Return ordered list of process stage names for a product."""
    if produkt in GLOL_PRODUCTS:
        return list(PROCESS_STAGES_GLOL)
    return list(PROCESS_STAGES_K7)


def init_etapy_status(db: sqlite3.Connection, ebr_id: int, produkt: str) -> None:
    """Initialize stage status records for a new szarża. First stage = in_progress."""
    stages = get_process_stages(produkt)
    if not stages:
        return
    now = datetime.now().isoformat(timespec="seconds")
    for i, etap in enumerate(stages):
        status = "in_progress" if i == 0 else "pending"
        dt_start = now if i == 0 else None
        db.execute(
            """INSERT OR IGNORE INTO ebr_etapy_status (ebr_id, etap, status, dt_start)
               VALUES (?, ?, ?, ?)""",
            (ebr_id, etap, status, dt_start),
        )
    db.commit()


def get_etapy_status(db: sqlite3.Connection, ebr_id: int) -> list[dict]:
    """Get status of all process stages for a batch. Returns ordered list."""
    rows = db.execute(
        "SELECT * FROM ebr_etapy_status WHERE ebr_id = ? ORDER BY id",
        (ebr_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_aktualny_etap(db: sqlite3.Connection, ebr_id: int) -> str | None:
    """Get the name of the current (in_progress) process stage, or None if all done."""
    row = db.execute(
        "SELECT etap FROM ebr_etapy_status WHERE ebr_id = ? AND status = 'in_progress'",
        (ebr_id,),
    ).fetchone()
    return row["etap"] if row else None


def zatwierdz_etap(db: sqlite3.Connection, ebr_id: int, etap: str, user: str, produkt: str) -> str | None:
    """Approve current stage, advance to next. Returns next stage name or None if last."""
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "UPDATE ebr_etapy_status SET status='done', dt_end=?, zatwierdzil=? WHERE ebr_id=? AND etap=?",
        (now, user, ebr_id, etap),
    )
    # Find next stage
    stages = get_process_stages(produkt)
    try:
        idx = stages.index(etap)
        if idx + 1 < len(stages):
            next_etap = stages[idx + 1]
            db.execute(
                "UPDATE ebr_etapy_status SET status='in_progress', dt_start=? WHERE ebr_id=? AND etap=?",
                (now, ebr_id, next_etap),
            )
            db.commit()
            return next_etap
    except ValueError:
        pass
    db.commit()
    return None  # All process stages done → standaryzacja next
```

- [ ] **Step 3: Verify**

```bash
python3 -c "
from mbr.models import get_db, init_mbr_tables
from mbr.etapy_models import init_etapy_status, get_etapy_status, get_aktualny_etap, zatwierdz_etap
db = get_db()
init_mbr_tables(db)
print('Tables OK')
# Test with a dummy
init_etapy_status(db, 9999, 'Chegina_K7')
st = get_etapy_status(db, 9999)
print(f'K7 stages: {[(s[\"etap\"], s[\"status\"]) for s in st]}')
akt = get_aktualny_etap(db, 9999)
print(f'Aktualny: {akt}')
nxt = zatwierdz_etap(db, 9999, 'amidowanie', 'test', 'Chegina_K7')
print(f'After approve amid: next={nxt}')
st2 = get_etapy_status(db, 9999)
print(f'Updated: {[(s[\"etap\"], s[\"status\"]) for s in st2]}')
# Cleanup
db.execute('DELETE FROM ebr_etapy_status WHERE ebr_id=9999')
db.commit()
"
```

Expected:
```
Tables OK
K7 stages: [('amidowanie', 'in_progress'), ('smca', 'pending'), ('czwartorzedowanie', 'pending'), ('sulfonowanie', 'pending'), ('utlenienie', 'pending')]
Aktualny: amidowanie
After approve amid: next=smca
Updated: [('amidowanie', 'done'), ('smca', 'in_progress'), ...]
```

- [ ] **Step 4: Commit**

```bash
git add mbr/models.py mbr/etapy_models.py
git commit -m "feat: add ebr_etapy_status table + init/get/zatwierdz functions"
```

---

### Task 2: Add API Endpoints + Init at EBR Creation

**Files:**
- Modify: `mbr/app.py`

- [ ] **Step 1: Add stage status endpoints**

In `mbr/app.py`, add these routes after the existing korekty endpoints (after line ~672):

```python
@app.route("/api/ebr/<int:ebr_id>/etapy-status")
@login_required
def api_etapy_status_get(ebr_id):
    from mbr.etapy_models import get_etapy_status
    with db_session() as db:
        data = get_etapy_status(db, ebr_id)
    return jsonify({"etapy_status": data})


@app.route("/api/ebr/<int:ebr_id>/etapy-status/zatwierdz", methods=["POST"])
@login_required
def api_etapy_zatwierdz(ebr_id):
    from mbr.etapy_models import zatwierdz_etap
    from mbr.models import get_ebr
    data = request.get_json(silent=True) or {}
    etap = data.get("etap")
    if not etap:
        return jsonify({"ok": False, "error": "Missing etap"}), 400
    user = session.get("user", {}).get("login", "unknown")
    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        if not ebr:
            return jsonify({"ok": False, "error": "EBR not found"}), 404
        next_etap = zatwierdz_etap(db, ebr_id, etap, user, ebr["produkt"])
    return jsonify({"ok": True, "next_etap": next_etap})
```

- [ ] **Step 2: Init stages when creating new szarża**

In `mbr/app.py`, find the `szarze_new` route. After `ebr_id = create_ebr(...)` and before the `if ebr_id is None:` check, add stage initialization for ETAPY_FULL products:

```python
        # Initialize process stage tracking for full-pipeline products
        if ebr_id and typ == 'szarza':
            from mbr.etapy_models import init_etapy_status, get_process_stages
            stages = get_process_stages(request.form["produkt"])
            if stages:  # Only for products with process stages (K7, K40GLOL, etc.)
                init_etapy_status(db, ebr_id, request.form["produkt"])
```

- [ ] **Step 3: Pass stage data to fast_entry_partial**

In `mbr/app.py`, find `fast_entry_partial` route. Add etapy_status and etapy_analizy to the template context:

```python
@app.route("/laborant/ebr/<int:ebr_id>/partial")
@login_required
def fast_entry_partial(ebr_id):
    from mbr.etapy_models import get_etapy_status, get_etap_analizy, get_korekty
    from mbr.etapy_config import get_etapy_config
    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        if ebr is None:
            return "Nie znaleziono", 404
        wyniki = get_ebr_wyniki(db, ebr_id)
        round_state = get_round_state(wyniki)
        etapy_status = get_etapy_status(db, ebr_id)
        etapy_analizy = get_etap_analizy(db, ebr_id)
        etapy_korekty = get_korekty(db, ebr_id)
    etapy_config = get_etapy_config(ebr.get("produkt", ""))
    return render_template("laborant/_fast_entry_content.html",
                           ebr=ebr, wyniki=wyniki, round_state=round_state,
                           etapy_status=etapy_status,
                           etapy_analizy=etapy_analizy,
                           etapy_korekty=etapy_korekty,
                           etapy_config=etapy_config)
```

- [ ] **Step 4: Verify**

```bash
python3 -c "from mbr.app import app; print('App loads OK')"
```

- [ ] **Step 5: Commit**

```bash
git add mbr/app.py
git commit -m "feat: add stage status API + init stages at EBR creation + pass to partial"
```

---

### Task 3: Clickable Pipeline Sidebar

**Files:**
- Modify: `mbr/templates/laborant/szarze_list.html`

- [ ] **Step 1: Update renderSidebarEtapy to handle process stages**

In `mbr/templates/laborant/szarze_list.html`, find the `renderSidebarEtapy` function (around line 675). Replace the entire function with an updated version that:
1. Reads `window._etapyStatus` (set by _fast_entry_content.html)
2. Makes process stages clickable
3. Highlights the active stage

Replace the function body (from `function renderSidebarEtapy() {` to its closing `}`) with:

```javascript
function renderSidebarEtapy() {
  const container = document.getElementById('sidebar-etapy');
  if (typeof window.ebrId === 'undefined' || typeof etapy === 'undefined') {
    container.innerHTML = '<div style="color:var(--text-dim);font-size:11px;padding:16px 4px;">Wybierz szarżę aby zobaczyć etapy.</div>';
    return;
  }

  const rs = typeof roundState !== 'undefined' ? roundState : null;
  const hasCycle = typeof parametry !== 'undefined' && parametry.analiza && parametry.dodatki;
  const isZbiornik = typeof ebrTyp !== 'undefined' && ebrTyp === 'zbiornik';
  const esData = window._etapyStatus || [];

  const filteredEtapy = isZbiornik
    ? etapy.filter(e => e.sekcja_lab === 'analiza_koncowa')
    : etapy.filter(e => e.nazwa !== 'Przepompowanie');

  let html = '';
  filteredEtapy.forEach((etap, i) => {
    const isLab = etap.sekcja_lab && !etap.read_only;
    let status = 'pending';
    let detail = '';
    let clickable = false;
    let etapKey = '';

    // Check if this is a process stage with status tracking
    const esMatch = esData.find(es => {
      // Match by stage name (lowercase, no spaces)
      const normalized = etap.nazwa.toLowerCase().replace(/[ąćęłńóśźż]/g, c => {
        return {'ą':'a','ć':'c','ę':'e','ł':'l','ń':'n','ó':'o','ś':'s','ź':'z','ż':'z'}[c] || c;
      }).replace(/\s+/g, '').replace('wytworzenie', '');
      return es.etap === normalized || es.etap === etap.nazwa.toLowerCase().replace(' ', '_')
          || (etap.nazwa === 'Amidowanie' && es.etap === 'amidowanie')
          || (etap.nazwa === 'Wytworzenie SMCA' && es.etap === 'smca')
          || (etap.nazwa === 'Czwartorzędowanie' && es.etap === 'czwartorzedowanie')
          || (etap.nazwa === 'Sulfonowanie' && es.etap === 'sulfonowanie')
          || (etap.nazwa === 'Utlenienie' && es.etap === 'utlenienie')
          || (etap.nazwa === 'Rozjaśnianie' && es.etap === 'rozjasnianie');
    });

    if (esMatch) {
      etapKey = esMatch.etap;
      status = esMatch.status === 'done' ? 'done' : esMatch.status === 'in_progress' ? 'active' : 'pending';
      clickable = true;
    } else if (etap.read_only) {
      const labStageIndices = etapy.map((e, j) => e.sekcja_lab && !e.read_only ? j : -1).filter(j => j >= 0);
      const lastLabIdx = labStageIndices.length > 0 ? labStageIndices[labStageIndices.length - 1] : -1;
      status = i <= lastLabIdx ? 'done' : 'pending';
    } else if (hasCycle && rs) {
      if (etap.sekcja_lab === 'standaryzacja') {
        // Check if all process stages are done
        const allProcessDone = esData.length > 0 && esData.every(es => es.status === 'done');
        if (!allProcessDone && esData.length > 0) {
          status = 'pending';
        } else if (rs.last_analiza === 0) {
          status = 'active'; detail = 'Analiza';
        } else if (rs.last_analiza === 1 && rs.last_dodatki === 0) {
          status = 'active'; detail = 'Dodatki';
        } else { status = 'done'; }
      } else if (etap.sekcja_lab === 'analiza_koncowa') {
        if (rs.is_decision) { status = 'active'; }
        else if (ebrStatus === 'completed') { status = 'done'; }
      }
    } else if (!etap.read_only) {
      if (ebrStatus === 'completed') status = 'done';
      else if (typeof ebrStatus !== 'undefined') status = 'active';
    }

    const statusIcon = status === 'done' ? '✓' : status === 'active' ? '●' : '○';
    const statusCls = 'se-' + status;
    const stageCls = etap.sekcja_lab === 'standaryzacja' ? 'se-stg-stand' : etap.sekcja_lab === 'analiza_koncowa' ? 'se-stg-koncowa' : '';
    const clickAttr = clickable ? ` onclick="openProcessStage('${etapKey}')" style="cursor:pointer;"` : '';

    html += '<div class="sb-etap ' + statusCls + ' ' + stageCls + '"' + clickAttr + '>' +
      '<div class="se-icon">' + statusIcon + '</div>' +
      '<div class="se-body">' +
        '<div class="se-name">' + etap.nazwa + '</div>' +
        (detail ? '<div class="se-detail">' + detail + '</div>' : '') +
      '</div>' +
    '</div>';
  });

  if (hasCycle && rs && rs.last_dodatki > 1) {
    for (let k = 2; k <= rs.last_dodatki; k++) {
      html += '<div class="sb-etap se-done"><div class="se-icon">✓</div><div class="se-body"><div class="se-name">Korekta ' + (k-1) + '</div></div></div>';
    }
  }

  container.innerHTML = html;
}

function openProcessStage(etapKey) {
  // Dispatch event to _fast_entry_content.html handler
  if (typeof window.showProcessStage === 'function') {
    window.showProcessStage(etapKey);
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add mbr/templates/laborant/szarze_list.html
git commit -m "feat: clickable process stages in sidebar pipeline"
```

---

### Task 4: Process Stage Form in _fast_entry_content.html

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

This is the largest task — adds JS globals for stage data, renders stage forms, handles save/correction/approval.

- [ ] **Step 1: Add JS globals for stage data**

In `_fast_entry_content.html`, find the `<script>` block where JS globals are set (around line 484 where `var ebrId = {{ ebr.ebr_id }};` is). Add after the existing globals:

```javascript
// Process stage data (from backend)
var _etapyStatus = {{ etapy_status | default([], true) | tojson }};
var _etapyAnalizy = {{ etapy_analizy | default({}, true) | tojson }};
var _etapyKorekty = {{ etapy_korekty | default([], true) | tojson }};
var _etapyConfig = {{ etapy_config | default({}, true) | tojson }};
window._etapyStatus = _etapyStatus;
```

- [ ] **Step 2: Add CSS for process stage form**

In the `<style>` block of `_fast_entry_content.html`, add:

```css
/* Process stage form */
.ps-form { padding: 16px; }
.ps-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.ps-title { font-size: 14px; font-weight: 700; }
.ps-runda { font-size: 11px; color: var(--text-dim); background: var(--surface-alt); padding: 3px 10px; border-radius: 12px; }
.ps-status-badge { font-size: 10px; font-weight: 600; padding: 3px 10px; border-radius: 12px; }
.ps-status-done { background: var(--green-bg); color: var(--green); }
.ps-status-active { background: var(--teal-bg); color: var(--teal); }
.ps-status-pending { background: var(--surface-alt); color: var(--text-dim); }

.ps-fields { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
.ps-field { display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: var(--surface); border: 1px solid var(--border-subtle); border-radius: 8px; }
.ps-field-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; background: var(--text-dim); }
.ps-field-dot.ok { background: var(--green); }
.ps-field-label { font-size: 12px; font-weight: 500; width: 120px; flex-shrink: 0; }
.ps-field-input {
  padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px;
  font-size: 13px; font-family: var(--mono); font-weight: 600; width: 90px;
  text-align: center; background: var(--surface);
}
.ps-field-input:focus { outline: none; border-color: var(--teal); }
.ps-field-input[readonly] { background: var(--surface-alt); color: var(--text-sec); }
.ps-field-info { font-size: 10px; color: var(--text-dim); }

.ps-korekty-section { margin: 14px 0; }
.ps-korekty-title { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-dim); margin-bottom: 6px; }
.ps-korekta-item { display: flex; align-items: center; gap: 8px; padding: 6px 10px; background: var(--surface-alt); border-radius: 6px; margin-bottom: 4px; font-size: 11px; }
.ps-korekta-sub { font-weight: 600; }
.ps-korekta-kg { font-family: var(--mono); }
.ps-korekta-badge { font-size: 9px; padding: 2px 6px; border-radius: 3px; background: var(--green-bg); color: var(--green); }

.ps-add-korekta { display: flex; align-items: center; gap: 6px; margin: 10px 0; }
.ps-add-korekta select {
  padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px;
  font-size: 11px; font-family: var(--font);
}
.ps-add-korekta input {
  width: 70px; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px;
  font-size: 12px; font-family: var(--mono); text-align: center;
}
.ps-add-korekta button {
  padding: 6px 12px; background: var(--amber); color: #fff; border: none;
  border-radius: 6px; font-size: 11px; font-weight: 600; cursor: pointer; font-family: var(--font);
}
.ps-approve-btn {
  width: 100%; padding: 10px; background: var(--teal); color: #fff; border: none;
  border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer;
  font-family: var(--font); display: flex; align-items: center; justify-content: center; gap: 6px;
  margin-top: 14px;
}
.ps-approve-btn:hover { opacity: 0.9; }
.ps-locked-msg { padding: 20px; text-align: center; color: var(--text-dim); font-size: 12px; }
```

- [ ] **Step 3: Add showProcessStage function and rendering logic**

At the end of the `<script>` block in `_fast_entry_content.html` (before the closing `</script>`), add:

```javascript
// ═══ PROCESS STAGE FORM ═══

window.showProcessStage = function(etapKey) {
  var container = document.getElementById('sections-container');
  if (!container) return;

  var stageConfig = _etapyConfig[etapKey];
  if (!stageConfig) {
    container.innerHTML = '<div class="ps-locked-msg">Brak konfiguracji dla etapu: ' + etapKey + '</div>';
    return;
  }

  // Find stage status
  var stageStatus = _etapyStatus.find(function(s) { return s.etap === etapKey; });
  var status = stageStatus ? stageStatus.status : 'pending';

  // Get analyses for this stage
  var stageAnalizy = _etapyAnalizy[etapKey] || {};
  var rundas = Object.keys(stageAnalizy).map(Number).sort();
  var currentRunda = rundas.length > 0 ? Math.max.apply(null, rundas) : 1;

  // Get corrections for this stage
  var stageKorekty = _etapyKorekty.filter(function(k) { return k.etap === etapKey; });

  var isActive = status === 'in_progress' && ebrStatus === 'open';
  var isDone = status === 'done';
  var isPending = status === 'pending';

  var html = '<div class="ps-form">';

  // Header
  html += '<div class="ps-header">';
  html += '<span class="ps-title">' + stageConfig.label + '</span>';
  html += '<span class="ps-runda">Runda ' + currentRunda + '</span>';
  if (isDone) html += '<span class="ps-status-badge ps-status-done">Zatwierdzony ✓</span>';
  else if (isActive) html += '<span class="ps-status-badge ps-status-active">Aktywny</span>';
  else html += '<span class="ps-status-badge ps-status-pending">Oczekuje</span>';
  html += '</div>';

  if (isPending) {
    html += '<div class="ps-locked-msg">Etap będzie dostępny po zatwierdzeniu poprzedniego etapu.</div>';
    html += '</div>';
    container.innerHTML = html;
    return;
  }

  // Fields for current round
  html += '<div class="ps-fields">';
  stageConfig.parametry.forEach(function(param) {
    var val = '';
    var rundaData = stageAnalizy[currentRunda];
    if (rundaData && rundaData[param.kod]) {
      val = String(rundaData[param.kod].wartosc).replace('.', ',');
    }
    var dotCls = val ? 'ps-field-dot ok' : 'ps-field-dot';

    html += '<div class="ps-field">';
    html += '<div class="' + dotCls + '"></div>';
    html += '<span class="ps-field-label">' + param.label + '</span>';
    if (isActive) {
      html += '<input class="ps-field-input" type="text" inputmode="decimal"' +
        ' data-etap="' + etapKey + '" data-runda="' + currentRunda + '" data-kod="' + param.kod + '"' +
        ' value="' + val + '" oninput="psAutoSave(this)" onblur="psSave(this)">';
    } else {
      html += '<input class="ps-field-input" type="text" value="' + val + '" readonly>';
    }
    html += '<span class="ps-field-info">' + (param.info || param.typ) + '</span>';
    html += '</div>';
  });
  html += '</div>';

  // Corrections history
  if (stageKorekty.length > 0) {
    html += '<div class="ps-korekty-section">';
    html += '<div class="ps-korekty-title">Historia korekt</div>';
    stageKorekty.forEach(function(k) {
      html += '<div class="ps-korekta-item">';
      html += '<span>R' + (k.po_rundzie || '?') + ' →</span>';
      html += '<span class="ps-korekta-sub">' + k.substancja + '</span>';
      html += '<span class="ps-korekta-kg">' + k.ilosc_kg + ' kg</span>';
      if (k.wykonano) html += '<span class="ps-korekta-badge">Wykonano</span>';
      else html += '<span style="font-size:9px;color:var(--amber);">Zalecono</span>';
      html += '</div>';
    });
    html += '</div>';
  }

  // Add correction form (active only)
  if (isActive && stageConfig.korekty && stageConfig.korekty.length > 0) {
    html += '<div class="ps-korekty-section">';
    html += '<div class="ps-korekty-title">Zalecenie korekty</div>';
    html += '<div class="ps-add-korekta">';
    html += '<select id="ps-korekta-sub">';
    stageConfig.korekty.forEach(function(s) {
      html += '<option value="' + s + '">' + s + '</option>';
    });
    html += '</select>';
    html += '<input id="ps-korekta-kg" type="number" step="0.1" placeholder="kg">';
    html += '<span>kg</span>';
    html += '<button onclick="psAddKorekta(\'' + etapKey + '\',' + currentRunda + ')">+ Zaleć korektę</button>';
    html += '</div>';
    html += '</div>';
  }

  // Approve button (active only)
  if (isActive) {
    html += '<button class="ps-approve-btn" onclick="psApproveStage(\'' + etapKey + '\')">';
    html += 'Zatwierdź etap →</button>';
  }

  html += '</div>';
  container.innerHTML = html;

  // Hide the existing standaryzacja/AK sections
  var dtWork = document.getElementById('detail-workspace');
  if (dtWork) {
    var existingSections = dtWork.querySelectorAll('.cv-params, .cv-certs-section');
    existingSections.forEach(function(el) { el.style.display = 'none'; });
  }
}

// Auto-save debounce for process stage fields
var _psSaveTimers = {};
function psAutoSave(input) {
  var key = input.dataset.etap + '__' + input.dataset.runda + '__' + input.dataset.kod;
  if (_psSaveTimers[key]) clearTimeout(_psSaveTimers[key]);
  // Normalize comma
  if (input.value.indexOf('.') >= 0) {
    var pos = input.selectionStart;
    input.value = input.value.replace(/\./g, ',');
    input.setSelectionRange(pos, pos);
  }
  _psSaveTimers[key] = setTimeout(function() { psSave(input); }, 1500);
}

function psSave(input) {
  var etap = input.dataset.etap;
  var runda = parseInt(input.dataset.runda);
  var kod = input.dataset.kod;
  var key = etap + '__' + runda + '__' + kod;
  if (_psSaveTimers[key]) { clearTimeout(_psSaveTimers[key]); delete _psSaveTimers[key]; }
  if (!input.value.trim()) return;

  var val = input.value.replace(',', '.');
  var wyniki = {};
  wyniki[kod] = parseFloat(val);

  input.style.outline = '2px solid var(--teal)';
  fetch('/api/ebr/' + ebrId + '/etapy-analizy', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({etap: etap, runda: runda, wyniki: wyniki})
  }).then(function(resp) {
    if (resp.ok) {
      input.style.outline = '2px solid var(--green)';
      // Update local cache
      if (!_etapyAnalizy[etap]) _etapyAnalizy[etap] = {};
      if (!_etapyAnalizy[etap][runda]) _etapyAnalizy[etap][runda] = {};
      _etapyAnalizy[etap][runda][kod] = {wartosc: parseFloat(val), dt_wpisu: new Date().toISOString(), wpisal: 'me'};
      input.querySelector && (input.previousElementSibling.className = 'ps-field-dot ok');
    } else {
      input.style.outline = '2px solid var(--red)';
    }
    setTimeout(function() { input.style.outline = ''; }, 800);
  });
}

function psAddKorekta(etap, poRundzie) {
  var sub = document.getElementById('ps-korekta-sub').value;
  var kg = parseFloat(document.getElementById('ps-korekta-kg').value);
  if (!sub || !kg || kg <= 0) { alert('Podaj substancję i ilość'); return; }

  fetch('/api/ebr/' + ebrId + '/korekty', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({etap: etap, po_rundzie: poRundzie, substancja: sub, ilosc_kg: kg})
  }).then(function(resp) {
    if (resp.ok) {
      // Refresh: increment runda and re-render
      _etapyKorekty.push({etap: etap, po_rundzie: poRundzie, substancja: sub, ilosc_kg: kg, wykonano: 0});
      // New runda for re-analysis
      var newRunda = poRundzie + 1;
      if (!_etapyAnalizy[etap]) _etapyAnalizy[etap] = {};
      _etapyAnalizy[etap][newRunda] = {};
      showProcessStage(etap);
      renderSidebarEtapy();
    }
  });
}

function psApproveStage(etap) {
  fetch('/api/ebr/' + ebrId + '/etapy-status/zatwierdz', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({etap: etap})
  }).then(function(resp) { return resp.json(); }).then(function(data) {
    if (data.ok) {
      // Update local status
      _etapyStatus.forEach(function(s) {
        if (s.etap === etap) s.status = 'done';
        if (data.next_etap && s.etap === data.next_etap) s.status = 'in_progress';
      });
      window._etapyStatus = _etapyStatus;
      renderSidebarEtapy();
      if (data.next_etap) {
        showProcessStage(data.next_etap);
      } else {
        // All process stages done — show standaryzacja
        loadBatch(ebrId);
      }
    }
  });
}
```

- [ ] **Step 4: Auto-open active stage on batch load**

In `_fast_entry_content.html`, find `renderCompletedView` function. At the very end of it (after `container.innerHTML = heroHtml + paramsHtml + certsHtml;`), add:

```javascript
    // If batch is open and has process stages, auto-open active stage
    if (ebrStatus === 'open' && _etapyStatus.length > 0) {
      var activeStage = _etapyStatus.find(function(s) { return s.status === 'in_progress'; });
      if (activeStage) {
        setTimeout(function() { showProcessStage(activeStage.etap); }, 100);
      }
    }
```

Also add the same logic at the end of the open-batch rendering path. Find where `renderOneSection` is called for open batches (the section rendering loop). After the sections are rendered, add:

```javascript
    // Auto-open active process stage for open batches with stage tracking
    if (_etapyStatus.length > 0) {
      var activeStage = _etapyStatus.find(function(s) { return s.status === 'in_progress'; });
      if (activeStage) {
        setTimeout(function() { showProcessStage(activeStage.etap); }, 200);
      }
    }
```

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: process stage form — fields, auto-save, corrections, approve button"
```

---

### Task 5: Integration Test

- [ ] **Step 1: Create a test szarża and verify full flow**

```bash
python3 -c "
from mbr.models import get_db, init_mbr_tables, get_ebr
from mbr.etapy_models import init_etapy_status, get_etapy_status, get_aktualny_etap, zatwierdz_etap, save_etap_analizy, add_korekta, get_korekty, get_etap_analizy

db = get_db()
init_mbr_tables(db)

# Find an open K7 szarza or use existing
row = db.execute(\"\"\"SELECT eb.ebr_id, mt.produkt FROM ebr_batches eb
    JOIN mbr_templates mt ON mt.mbr_id=eb.mbr_id
    WHERE mt.produkt='Chegina_K7' AND eb.status='open' AND eb.typ='szarza' LIMIT 1\"\"\").fetchone()

if row:
    eid = row['ebr_id']
    prod = row['produkt']
    print(f'Using existing EBR {eid} ({prod})')
    # Init stages if not already
    existing = get_etapy_status(db, eid)
    if not existing:
        init_etapy_status(db, eid, prod)
        print('  Initialized stages')
else:
    print('No open K7 szarza found — create one in LIMS first')
    exit()

# Verify stages
st = get_etapy_status(db, eid)
print(f'Stages: {[(s[\"etap\"], s[\"status\"]) for s in st]}')
print(f'Aktualny: {get_aktualny_etap(db, eid)}')

# Simulate: save analysis on amidowanie
save_etap_analizy(db, eid, 'amidowanie', 1, {'le': 8.5, 'lk': 0.8, 'nd20': 1.462}, 'test')
print('Saved amidowanie analysis')

# Approve amidowanie
nxt = zatwierdz_etap(db, eid, 'amidowanie', 'test', prod)
print(f'Approved amidowanie → next: {nxt}')

# Check updated status
st2 = get_etapy_status(db, eid)
print(f'Updated: {[(s[\"etap\"], s[\"status\"]) for s in st2]}')

# Save SMCA analysis + approve
save_etap_analizy(db, eid, 'smca', 1, {'ph': 3.5}, 'test')
nxt2 = zatwierdz_etap(db, eid, 'smca', 'test', prod)
print(f'Approved smca → next: {nxt2}')

# Czwart: save + correct + save round 2
save_etap_analizy(db, eid, 'czwartorzedowanie', 1, {'ph_10proc': 10.5, 'nd20': 1.395, 'aa': 0.35}, 'test')
kid = add_korekta(db, eid, 'czwartorzedowanie', 1, 'NaOH', 10.0, 'test')
print(f'Added correction (id={kid})')
save_etap_analizy(db, eid, 'czwartorzedowanie', 2, {'ph_10proc': 11.76, 'aa': 0.08}, 'test')
nxt3 = zatwierdz_etap(db, eid, 'czwartorzedowanie', 'test', prod)
print(f'Approved czwart → next: {nxt3}')

# Final check
data = get_etap_analizy(db, eid)
for etap, rundas in data.items():
    for runda, params in rundas.items():
        print(f'  {etap}/r{runda}: {list(params.keys())}')

kor = get_korekty(db, eid)
print(f'Korekty: {len(kor)}')
print(f'Final status: {[(s[\"etap\"], s[\"status\"]) for s in get_etapy_status(db, eid)]}')
print()
print('✓ Integration test PASSED')
"
```

- [ ] **Step 2: Test in browser**

Start Flask and test:
1. Open an existing K7 szarża or create new one
2. Verify pipeline shows process stages with status indicators
3. Click on active stage → form appears
4. Enter values → auto-save works
5. Add correction → new round appears
6. Click "Zatwierdź etap" → advances to next stage
7. Verify sidebar updates in real-time

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat: complete batch card UI — process stage forms with sequential flow

Process stages (amidowanie → utlenienie/rozjaśnianie) now have:
- Interactive forms with auto-save per field
- Correction workflow (substance + kg → new analysis round)
- Stage approval button → advances to next stage
- Clickable pipeline sidebar with live status
- Auto-opens active stage on batch load
- Read-only view for completed stages"
```
