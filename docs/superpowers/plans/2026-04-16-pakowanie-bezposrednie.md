# Pakowanie bezpośrednie (IBC / Beczki) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow batches to bypass zbiornik and go directly to IBC or barrels, with entry at batch creation or at pump stage.

**Architecture:** New `pakowanie_bezposrednie` column on `ebr_batches`, UI changes in batch creation modal and pump modal, badge in completed view.

**Tech Stack:** SQLite ALTER TABLE, Jinja2 templates, inline JS

---

## File Structure

| File | Change |
|------|--------|
| `mbr/models.py` | ALTER TABLE in `init_mbr_tables()` |
| `scripts/migrate_pakowanie_bezposrednie.py` | Migration for production |
| `mbr/laborant/routes.py` | Read `pakowanie_bezposrednie` from form POST + complete endpoint |
| `mbr/templates/laborant/_modal_nowa_szarza.html` | Checkbox + select + uwagi in szarza form |
| `mbr/templates/laborant/_fast_entry_content.html` | Pump modal: IBC/beczki option + adapted flow |
| `mbr/ml_export/query.py` | New `pakowanie` column |
| `DEPLOY_TODO.md` | Add migration step |

---

### Task 1: DB column + migration

**Files:**
- Modify: `mbr/models.py`
- Create: `scripts/migrate_pakowanie_bezposrednie.py`
- Modify: `DEPLOY_TODO.md`

- [ ] **Step 1: Add column to init_mbr_tables**

In `mbr/models.py`, find the `CREATE TABLE IF NOT EXISTS ebr_batches` block. After `uwagi_koncowe TEXT` add:

```sql
pakowanie_bezposrednie TEXT
```

Also add an ALTER TABLE fallback after the CREATE (same pattern as other migrations in `init_mbr_tables`):

```python
# Add pakowanie_bezposrednie if missing
try:
    db.execute("ALTER TABLE ebr_batches ADD COLUMN pakowanie_bezposrednie TEXT")
except Exception:
    pass
```

- [ ] **Step 2: Create migration script**

Create `scripts/migrate_pakowanie_bezposrednie.py`:

```python
"""
Add pakowanie_bezposrednie column to ebr_batches.

Run: python -m scripts.migrate_pakowanie_bezposrednie
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mbr.db import get_db

def migrate():
    db = get_db()
    try:
        db.execute("ALTER TABLE ebr_batches ADD COLUMN pakowanie_bezposrednie TEXT")
        db.commit()
        print("Added pakowanie_bezposrednie column.")
    except Exception as e:
        if "duplicate column" in str(e).lower():
            print("Column already exists.")
        else:
            raise
    finally:
        db.close()

if __name__ == "__main__":
    migrate()
```

- [ ] **Step 3: Update DEPLOY_TODO.md**

Add:
```
## Pakowanie bezpośrednie:

\```bash
python -m scripts.migrate_pakowanie_bezposrednie
\```

Dodaje kolumnę `pakowanie_bezposrednie` do `ebr_batches`.
```

- [ ] **Step 4: Run migration locally**

```bash
python -m scripts.migrate_pakowanie_bezposrednie
```

- [ ] **Step 5: Commit**

```bash
git add mbr/models.py scripts/migrate_pakowanie_bezposrednie.py DEPLOY_TODO.md
git commit -m "feat: pakowanie_bezposrednie column on ebr_batches"
```

---

### Task 2: Batch creation modal — checkbox + select

**Files:**
- Modify: `mbr/templates/laborant/_modal_nowa_szarza.html`
- Modify: `mbr/laborant/routes.py`

- [ ] **Step 1: Add pakowanie bezpośrednie UI in modal**

In `_modal_nowa_szarza.html`, find the zbiorniki docelowe section (line ~116-124, inside `#step-2a`). BEFORE it, add:

```html
          <div class="form-row" style="margin-top:14px;">
            <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:12px;font-weight:600;color:var(--text);">
              <input type="checkbox" id="chk-pakowanie-bezp" onchange="togglePakBezp()">
              Pakowanie bezpośrednie (bez zbiornika)
            </label>
            <div id="pak-bezp-fields" style="display:none;margin-top:10px;padding:12px 16px;background:var(--surface-alt);border-radius:8px;border:1px solid var(--border);">
              <div class="form-label" style="margin-bottom:6px;">Rodzaj opakowania</div>
              <div style="display:flex;gap:8px;">
                <button type="button" class="pm-tank-pill" id="pak-ibc" onclick="selectPakType('IBC')" style="padding:8px 20px;font-size:13px;">IBC</button>
                <button type="button" class="pm-tank-pill" id="pak-beczki" onclick="selectPakType('Beczki')" style="padding:8px 20px;font-size:13px;">Beczki</button>
              </div>
              <div class="form-label" style="margin-top:10px;margin-bottom:4px;">Uwagi (np. parametry klienta)</div>
              <textarea id="pak-bezp-uwagi" class="form-input" rows="2" placeholder="np. klient X, pH 5.5-6.0" style="font-size:12px;resize:vertical;"></textarea>
            </div>
            <input type="hidden" name="pakowanie_bezposrednie" id="pak-bezp-value" value="">
          </div>
```

- [ ] **Step 2: Add JS functions for toggle and select**

At the end of the `<script>` block in the modal template, add:

```javascript
function togglePakBezp() {
    var checked = document.getElementById('chk-pakowanie-bezp').checked;
    document.getElementById('pak-bezp-fields').style.display = checked ? '' : 'none';
    // Hide/show zbiorniki section
    var zbSec = document.querySelector('#step-2a .form-row:last-of-type');
    // Find the zbiorniki row by its label content
    var zbPickRow = document.getElementById('zb-pick-szarza');
    if (zbPickRow) zbPickRow.closest('.form-row').style.display = checked ? 'none' : '';
    if (!checked) {
        document.getElementById('pak-bezp-value').value = '';
        document.querySelectorAll('#pak-bezp-fields .pm-tank-pill').forEach(function(b) { b.classList.remove('pm-pill-active'); });
    }
}

function selectPakType(typ) {
    document.getElementById('pak-bezp-value').value = typ;
    document.querySelectorAll('#pak-bezp-fields .pm-tank-pill').forEach(function(b) { b.classList.remove('pm-pill-active'); });
    document.getElementById('pak-' + typ.toLowerCase()).classList.add('pm-pill-active');
}
```

- [ ] **Step 3: Handle in backend route**

In `mbr/laborant/routes.py`, in `szarze_new()` (line ~78), after the `create_ebr()` call, add:

```python
        # Save pakowanie bezpośrednie if set
        pak_bezp = request.form.get("pakowanie_bezposrednie", "").strip()
        if pak_bezp and ebr_id:
            uwagi_pak = request.form.get("pak_bezp_uwagi", "").strip()
            db.execute(
                "UPDATE ebr_batches SET pakowanie_bezposrednie = ? WHERE ebr_id = ?",
                (pak_bezp, ebr_id),
            )
            if uwagi_pak:
                db.execute(
                    "UPDATE ebr_batches SET uwagi_koncowe = ? WHERE ebr_id = ?",
                    (f"[Pakowanie bezpośrednie: {pak_bezp}] {uwagi_pak}", ebr_id),
                )
```

Also add the uwagi textarea name to the form. In the modal HTML, change the textarea to include name:

```html
<textarea id="pak-bezp-uwagi" name="pak_bezp_uwagi" ...>
```

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/_modal_nowa_szarza.html mbr/laborant/routes.py
git commit -m "feat: pakowanie bezpośrednie option in batch creation modal"
```

---

### Task 3: Pump modal — IBC/beczki option

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`
- Modify: `mbr/laborant/routes.py`

- [ ] **Step 1: Add IBC/beczki button in pump modal**

In `_fast_entry_content.html`, in `openPumpModal()`, after the uwagi field (line ~3529), before `html += '</div>'; // end modal-body`, add:

```javascript
    // Direct packaging option
    html += '<div style="margin-top:16px;padding-top:14px;border-top:1px dashed var(--border);">' +
        '<div class="pm-section-label">Lub pakowanie bezpośrednie</div>' +
        '<div style="display:flex;gap:8px;margin-top:6px;">' +
            '<button class="pm-tank-pill" id="pm-pak-ibc" onclick="selectPumpPakType(\'IBC\')" style="padding:8px 20px;font-size:13px;">IBC</button>' +
            '<button class="pm-tank-pill" id="pm-pak-beczki" onclick="selectPumpPakType(\'Beczki\')" style="padding:8px 20px;font-size:13px;">Beczki</button>' +
        '</div>' +
    '</div>';
```

- [ ] **Step 2: Add selectPumpPakType function**

After `closePumpModal()` function, add:

```javascript
window._pumpPakBezp = null;

function selectPumpPakType(typ) {
    window._pumpPakBezp = typ;
    // Deselect all tanks
    _pumpSelected = {};
    document.querySelectorAll('.pm-tank-pill[data-zid]').forEach(function(b) { b.classList.remove('pm-pill-active'); });
    // Highlight selected packaging type
    document.querySelectorAll('#pm-pak-ibc,#pm-pak-beczki').forEach(function(b) { b.classList.remove('pm-pill-active'); });
    document.getElementById('pm-pak-' + typ.toLowerCase()).classList.add('pm-pill-active');
    // Enable confirm button
    var btn = document.getElementById('pm-confirm-btn');
    if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
    // Hide mass section
    var ms = document.getElementById('pm-mass-section');
    if (ms) ms.style.display = 'none';
}
```

- [ ] **Step 3: Update toggleTank to clear pakowanie selection**

In `toggleTank()` function, at the beginning add:

```javascript
    // Clear direct packaging selection if user picks a tank
    window._pumpPakBezp = null;
    document.querySelectorAll('#pm-pak-ibc,#pm-pak-beczki').forEach(function(b) { b.classList.remove('pm-pill-active'); });
```

- [ ] **Step 4: Update confirmPump to handle pakowanie bezpośrednie**

In `confirmPump()`, at the very beginning (after `var keys = Object.keys(_pumpSelected);`), add handling for direct packaging:

```javascript
    // Direct packaging — no tanks needed
    if (window._pumpPakBezp && keys.length === 0) {
        var btn = document.getElementById('pm-confirm-btn');
        if (btn) { btn.textContent = 'Zatwierdzanie...'; btn.disabled = true; }
        var uwagi = (document.getElementById('pm-uwagi') || {}).value || '';
        var bodyObj = {
            zbiorniki: [],
            pakowanie_bezposrednie: window._pumpPakBezp,
        };
        if (uwagi.trim()) bodyObj.uwagi = uwagi.trim();
        var resp = await fetch('/laborant/ebr/' + ebrId + '/complete', {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(bodyObj)
        });
        if (resp.ok || resp.redirected) {
            location.href = '/laborant/szarze';
        }
        return;
    }
```

- [ ] **Step 5: Update complete_entry route to handle pakowanie_bezposrednie**

In `mbr/laborant/routes.py`, in `complete_entry()` (line ~367), after reading `uwagi`, add:

```python
    pak_bezp = data.get("pakowanie_bezposrednie", "").strip()
```

And after `complete_ebr()` call, add:

```python
        if pak_bezp:
            db.execute(
                "UPDATE ebr_batches SET pakowanie_bezposrednie = ? WHERE ebr_id = ?",
                (pak_bezp, ebr_id),
            )
```

- [ ] **Step 6: Update completePompuj for pre-set pakowanie**

In `_fast_entry_content.html`, find `completePompuj` / `openPumpModal` call. If `pakowanie_bezposrednie` is already set on the batch (from creation), skip the pump modal and go directly to complete. Add before `openPumpModal` definition:

```javascript
// Check if batch has pakowanie_bezposrednie set — if so, use simplified confirm
var _batchPakBezp = '{{ ebr.pakowanie_bezposrednie or "" }}';
```

And modify `completePompuj`:

```javascript
function completePompuj() {
    if (_batchPakBezp) {
        if (confirm('Zakończyć szarżę → ' + _batchPakBezp + '?')) {
            fetch('/laborant/ebr/' + ebrId + '/complete', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({zbiorniki: [], pakowanie_bezposrednie: _batchPakBezp})
            }).then(function(r) { if (r.ok) location.href = '/laborant/szarze'; });
        }
    } else {
        openPumpModal();
    }
}
```

- [ ] **Step 7: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html mbr/laborant/routes.py
git commit -m "feat: IBC/beczki option in pump modal + simplified complete for pre-set packaging"
```

---

### Task 4: Display badge + ML export column

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html` (completed view badges)
- Modify: `mbr/ml_export/query.py`

- [ ] **Step 1: Show badge in completed view**

In `_fast_entry_content.html`, find `loadBatchZbiorniki()` or the completed view rendering. Where zbiornik badges are shown, add a fallback for pakowanie_bezposrednie:

After the zbiorniki badges rendering, add:

```javascript
    // Show pakowanie bezpośrednie badge if no zbiorniki
    var pakBezp = '{{ ebr.pakowanie_bezposrednie or "" }}';
    if (pakBezp && (!window._batchZbiorniki || window._batchZbiorniki.length === 0)) {
        var zbContainer = document.getElementById('cv-h2-zbiorniki');
        if (zbContainer) {
            zbContainer.innerHTML = '<span class="cv-zb-badge" style="background:var(--amber-bg);color:var(--amber);border-color:var(--amber);">' + pakBezp + '</span>';
        }
        var tbZb = document.getElementById('cv-tb-zbiorniki');
        if (tbZb) tbZb.textContent = pakBezp;
    }
```

- [ ] **Step 2: Add pakowanie column to ML export**

In `mbr/ml_export/query.py`, in `build_columns()`, add `"pakowanie"` after `"dt_end"` in the metadata section.

In `export_k7_batches()`, after setting `dt_end`, add:

```python
        # Pakowanie type
        pak = db.execute(
            "SELECT pakowanie_bezposrednie FROM ebr_batches WHERE ebr_id = ?",
            (ebr_id,),
        ).fetchone()
        row["pakowanie"] = pak["pakowanie_bezposrednie"] if pak and pak["pakowanie_bezposrednie"] else "zbiornik"
```

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html mbr/ml_export/query.py
git commit -m "feat: IBC/Beczki badge in completed view + pakowanie column in ML export"
```
