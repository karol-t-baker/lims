# Bugfixy i Quick Wins — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 5 bugs in the MBR lab system: calculator averaging, comma separator, DEA method trigger, white screen on duplicate batch, and real-time batch number validation.

**Architecture:** All fixes are independent. Each touches 1-2 files. No new tables or migrations. Calculator fixes are JS-only. DEA fix is a seed order change + migration. Batch fixes touch one Python route + one HTML template.

**Tech Stack:** JavaScript (frontend), Python/Flask (backend), SQLite

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Modify | `mbr/static/calculator.js:649-691` | Fix 1: average calculation in acceptCalc() |
| Modify | `mbr/static/calculator.js:414,480,486,507,587,593` | Fix 2: comma input handling on calculator fields |
| Modify | `mbr/parametry/seed.py:645-651` | Fix 3: swap seed order so metoda_id links work |
| Modify | `mbr/app.py:58-60` | Fix 3: re-link metoda_id on app startup |
| Modify | `mbr/laborant/routes.py:34-69` | Fix 4: catch IntegrityError on duplicate batch |
| Modify | `mbr/registry/routes.py` | Fix 5: add /api/batch-exists endpoint |
| Modify | `mbr/templates/laborant/_modal_nowa_szarza.html` | Fix 5: real-time validation JS |

---

### Task 1: Fix calculator average (acceptCalc ignores second sample)

**Files:**
- Modify: `mbr/static/calculator.js`

The bug: `acceptCalc()` already computes `avg` correctly at line 659, and uses it at line 673. But the issue is that the **summary display** in `renderCalculator()` (lines 606-627) shows results inline during editing but when only 1 sample has results, it shows `results[0]` — and the user sees that as the final value.

After reading the code more carefully: `acceptCalc()` at line 659 DOES compute the average correctly and writes it at line 673. The actual bug the user reports ("nie wgl nie liczy średniej") must be that only one sample's result is computed (the second sample returns `null` from `calcSample`/`calcSampleFull`).

The root cause: sample inputs use `type="number"` which may reject comma input silently, leaving the value empty → `parseFloat('')` → `NaN` → `calcSample` returns `null`. This means Fix 2 (comma) will likely fix the averaging too. But let's also add a safety net.

- [ ] **Step 1: Verify acceptCalc computes average**

Read `mbr/static/calculator.js` lines 649-692. Confirm `avg` is computed at line 659 and used at line 673. The code IS correct — if both samples have valid numbers, the average is computed.

No code change needed here — the averaging code is correct. The root cause is Fix 2 (comma rejection).

- [ ] **Step 2: Commit (skip — no change needed)**

---

### Task 2: Fix calculator comma input

**Files:**
- Modify: `mbr/static/calculator.js`

The bug: Calculator sample inputs use `type="number"` which silently rejects comma. The value stays empty, so the second sample is never computed.

The fix: Change inputs from `type="number"` to `type="text" inputmode="decimal"` and normalize comma→dot on input. This matches how `lab_common.js` handles fast entry fields.

- [ ] **Step 1: Add comma normalization helper at the top of calculator.js**

After line 43 (end of CALC_METHODS loading), before `calcStats`, add:

```javascript
function _normalizeDecimal(value) {
    return value.replace(',', '.');
}
```

- [ ] **Step 2: Fix legacy calculator sample inputs (renderCalculator)**

In `renderCalculator()` (~line 587-593), change the sample field inputs from `type="number"` to `type="text" inputmode="decimal"` and normalize values on input.

Replace the two input lines in the sample template (inside the forEach at line 574):

Old (line 587-589):
```javascript
                    <input type="number" step="any" value="${s.m || ''}"
                        oninput="onSampleInput(${i}, 'm', this.value)"
                        placeholder="---">
```

New:
```javascript
                    <input type="text" inputmode="decimal" value="${s.m || ''}"
                        oninput="onSampleInput(${i}, 'm', _normalizeDecimal(this.value))"
                        placeholder="---">
```

Old (line 593-595):
```javascript
                    <input type="number" step="any" value="${s.v || ''}"
                        oninput="onSampleInput(${i}, 'v', this.value)"
                        placeholder="---">
```

New:
```javascript
                    <input type="text" inputmode="decimal" value="${s.v || ''}"
                        oninput="onSampleInput(${i}, 'v', _normalizeDecimal(this.value))"
                        placeholder="---">
```

- [ ] **Step 3: Fix full calculator sample inputs (renderCalculatorFull)**

In `renderCalculatorFull()` (~line 479-486), same change for mass and volume inputs.

Old mass input (line 479-480):
```javascript
            html += '<input type="number" step="any" value="' + (s.m || '') + '" oninput="onSampleInputFull(' + i + ', \'m\', this.value)" placeholder="---"></div>';
```

New:
```javascript
            html += '<input type="text" inputmode="decimal" value="' + (s.m || '') + '" oninput="onSampleInputFull(' + i + ', \'m\', _normalizeDecimal(this.value))" placeholder="---"></div>';
```

Old volume input (line 486):
```javascript
            html += '<input type="number" step="any" value="' + (s.vols[vi] || '') + '" oninput="onSampleInputFull(' + i + ', ' + vi + ', this.value)" placeholder="---"></div>';
```

New:
```javascript
            html += '<input type="text" inputmode="decimal" value="' + (s.vols[vi] || '') + '" oninput="onSampleInputFull(' + i + ', ' + vi + ', _normalizeDecimal(this.value))" placeholder="---"></div>';
```

- [ ] **Step 4: Fix titrant inputs (renderCalculatorFull)**

Old titrant input (line 458):
```javascript
                html += '<input type="number" step="any" value="' + val + '" oninput="onTitrantChange(\'' + t.id + '\', parseFloat(this.value))" placeholder="---">';
```

New:
```javascript
                html += '<input type="text" inputmode="decimal" value="' + val + '" oninput="onTitrantChange(\'' + t.id + '\', parseFloat(_normalizeDecimal(this.value)))" placeholder="---">';
```

- [ ] **Step 5: Test manually**

Open fast entry for any batch with a titracja parameter. Click on it to open calculator.
1. Type `1,5` in nawazka → should parse as 1.5
2. Type `12,34` in volume → should parse as 12.34
3. Both samples should show results
4. Summary should show average of both
5. "Zatwierdź wynik" should insert average with comma format

- [ ] **Step 6: Commit**

```bash
git add mbr/static/calculator.js
git commit -m "fix: calculator accepts comma as decimal separator and averages correctly"
```

---

### Task 3: Fix DEA method not triggering calculator

**Files:**
- Modify: `mbr/parametry/seed.py:645-651`
- Modify: `mbr/app.py:58-60`

The bug: In `seed.py` `__main__`, `seed_metody()` runs at line 649 BEFORE `seed_from_seed_mbr()` at line 650. The `UPDATE parametry_analityczne SET metoda_id=? WHERE kod='dietanolamina'` finds 0 rows because `dietanolamina` doesn't exist yet. So `metoda_id` stays NULL for DEA, and the frontend never gets `data-metoda-id` on the input.

- [ ] **Step 1: Fix seed order in seed.py**

In `mbr/parametry/seed.py`, swap lines 649-650 so `seed_from_seed_mbr` runs before `seed_metody`:

Old (lines 645-651):
```python
if __name__ == "__main__":
    db = get_db()
    init_mbr_tables(db)
    seed(db)
    seed_metody(db)
    seed_from_seed_mbr(db)
    db.close()
```

New:
```python
if __name__ == "__main__":
    db = get_db()
    init_mbr_tables(db)
    seed(db)
    seed_from_seed_mbr(db)
    seed_metody(db)
    db.close()
```

- [ ] **Step 2: Add metoda_id re-linking on app startup**

For existing databases where the seed already ran in the wrong order, add a one-time fix. In `mbr/app.py`, inside `create_app()`, after `init_mbr_tables(db)` (line 60), add the re-link:

```python
            # Fix metoda_id links for parameters created after seed_metody ran
            from mbr.parametry.seed import _PARAM_METHOD_MAP
            nazwa_to_id = {
                r[0]: r[1]
                for r in db.execute("SELECT nazwa, id FROM metody_miareczkowe").fetchall()
            }
            for kod, nazwa in _PARAM_METHOD_MAP.items():
                mid = nazwa_to_id.get(nazwa)
                if mid:
                    db.execute(
                        "UPDATE parametry_analityczne SET metoda_id=? WHERE kod=? AND metoda_id IS NULL",
                        (mid, kod),
                    )
            db.commit()
```

- [ ] **Step 3: Test manually**

1. Restart app
2. Open fast entry for a Chelamid DK batch
3. Focus on DEA/dietanolamina field
4. Calculator should open with DEA formula: `((V1 - V2) * T1 * 10.5) / M`

- [ ] **Step 4: Commit**

```bash
git add mbr/parametry/seed.py mbr/app.py
git commit -m "fix: DEA method triggers titration calculator (seed order + migration)"
```

---

### Task 4: Fix white screen on duplicate batch number

**Files:**
- Modify: `mbr/laborant/routes.py:34-69`

The bug: `create_ebr()` raises `sqlite3.IntegrityError` on duplicate `batch_id` UNIQUE constraint. Not caught → 500 white screen.

- [ ] **Step 1: Add try/except around create_ebr in szarze_new()**

In `mbr/laborant/routes.py`, modify `szarze_new()`. Wrap the `create_ebr()` call in try/except:

Old (lines 37-51):
```python
    with db_session() as db:
        typ = request.form.get("typ", "szarza")
        wielkosc_kg = float(request.form.get("wielkosc_kg", 0) or 0)
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
```

New:
```python
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
```

- [ ] **Step 2: Test manually**

1. Create a batch with nr_partii "1/2026"
2. Try creating another with the same product and nr_partii "1/2026"
3. Should see flash message, NOT white screen
4. Should redirect back to the form

- [ ] **Step 3: Commit**

```bash
git add mbr/laborant/routes.py
git commit -m "fix: catch duplicate batch number instead of white screen crash"
```

---

### Task 5: Real-time batch number validation

**Files:**
- Modify: `mbr/registry/routes.py`
- Modify: `mbr/templates/laborant/_modal_nowa_szarza.html`

- [ ] **Step 1: Add /api/batch-exists endpoint**

In `mbr/registry/routes.py`, after the `api_next_nr` route (line 64), add:

```python
@registry_bp.route("/api/batch-exists", methods=["POST"])
@login_required
def api_batch_exists():
    data = request.get_json(silent=True) or {}
    produkt = data.get("produkt", "")
    nr_partii = data.get("nr_partii", "")
    if not produkt or not nr_partii:
        return jsonify({"exists": False})
    batch_id = f"{produkt}__{nr_partii.replace('/', '_')}"
    with db_session() as db:
        row = db.execute(
            "SELECT 1 FROM ebr_batches WHERE batch_id = ?", (batch_id,)
        ).fetchone()
    return jsonify({"exists": bool(row)})
```

Add `request` to the flask imports at the top of the file (line 9) if not already present. Check: `request` is already imported at line 9.

- [ ] **Step 2: Add validation JS to modal**

In `mbr/templates/laborant/_modal_nowa_szarza.html`, before the closing `</script>` tag (line 422), add the validation code:

```javascript
// --- Real-time batch number validation ---
var _batchCheckTimer = null;
var _batchCheckCtrl = null;

function checkBatchExists(inputEl, produktInputId) {
    clearTimeout(_batchCheckTimer);
    if (_batchCheckCtrl) _batchCheckCtrl.abort();

    var nr = inputEl.value.trim();
    var produkt = document.getElementById(produktInputId || 'produkt-input').value;
    var hint = inputEl.parentElement.querySelector('.batch-exists-hint');

    if (!nr || !produkt) {
        if (hint) hint.remove();
        inputEl.classList.remove('invalid');
        enableSubmitBtn(true);
        return;
    }

    _batchCheckTimer = setTimeout(function() {
        _batchCheckCtrl = new AbortController();
        fetch('/api/batch-exists', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({produkt: produkt, nr_partii: nr}),
            signal: _batchCheckCtrl.signal
        })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (hint) hint.remove();
            if (d.exists) {
                inputEl.classList.add('invalid');
                var h = document.createElement('div');
                h.className = 'field-error batch-exists-hint';
                h.textContent = 'Ten numer szarży jest już w systemie';
                inputEl.parentElement.appendChild(h);
                enableSubmitBtn(false);
            } else {
                inputEl.classList.remove('invalid');
                enableSubmitBtn(true);
            }
        })
        .catch(function() {});
    }, 300);
}

function enableSubmitBtn(enabled) {
    var btn = document.querySelector('#new-batch-form button[type="submit"]');
    if (btn) {
        btn.disabled = !enabled;
        btn.style.opacity = enabled ? '1' : '0.5';
    }
}

// Attach to manual nr input fields
var manualSzarza = document.getElementById('manual-nr-input-szarza');
if (manualSzarza) {
    manualSzarza.addEventListener('input', function() {
        checkBatchExists(this, 'produkt-input');
    });
}
var manualZbiornik = document.getElementById('manual-nr-input-zbiornik');
if (manualZbiornik) {
    manualZbiornik.addEventListener('input', function() {
        checkBatchExists(this, 'produkt-input');
    });
}
```

- [ ] **Step 3: Test manually**

1. Open "Nowa szarża" modal
2. Select a product
3. Check "Podaj ręcznie"
4. Type an existing batch number (e.g., "1/2026")
5. After 300ms: field turns red, message appears, "Utwórz" button disabled
6. Change to a new number → field clears, button re-enabled

- [ ] **Step 4: Commit**

```bash
git add mbr/registry/routes.py mbr/templates/laborant/_modal_nowa_szarza.html
git commit -m "feat: real-time batch number uniqueness validation"
```
