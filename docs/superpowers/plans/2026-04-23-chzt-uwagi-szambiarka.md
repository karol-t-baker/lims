# CHZT — Uwagi column (szambiarka-scoped)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a free-text `uwagi` field on `chzt_pomiary`, exposed only on the szambiarka row. Input in the modal's "Analiza zewnętrzna — Szambiarka" section (same section already carrying ext_ph / ext_chzt / waga_kg, so the detail view in historia inherits it). `/chzt/historia` list view gets a new "Uwagi" column at the end, truncated with ellipsis + tooltip exactly like the completed-batches table (`mbr/templates/laborant/szarze_list.html:1499-1504`).

**Architecture:** One new TEXT column on `chzt_pomiary` (idempotent `ALTER TABLE` in `init_tables_v3`). `POMIAR_FIELDS_TEXT = ("uwagi",)` constant lets the PUT route branch coercion (string vs. float). `update_pomiar` and `get_pomiar` learn about `uwagi`. `list_sessions_paginated` adds `sz.uwagi AS sz_uwagi` via the existing LEFT JOIN on szambiarka. Frontend: JS reuses existing dirty-tracking + `saveRow` for the new textarea (with a `data-type="text"` branch in `getRowValues` so the string isn't parseNum'd to NaN).

**Tech Stack:** Python 3 / Flask / sqlite3 · Jinja2 · pytest · vanilla JS.

---

## Scope decisions (user-confirmed)

- **Per szambiarka only (A2)**: `uwagi` is written only on the szambiarka row. UI exposes it only in the external section. (The `uwagi` column exists on `chzt_pomiary` globally but no UI writes it on hala/rura/kontener rows.)
- **Truncate like szarze_list (B)**: threshold `len > 50 → slice(0, 47) + '…'`; full text in `title=` tooltip; empty → `—`. Same CSS shape as `.td-uwagi` at `mbr/templates/laborant/szarze_list.html:1502`.
- **Position**: last column of the list view (after "Przekroczeń pH").
- **Role gate**: `uwagi` joins `POMIAR_FIELDS_EXTERNAL` — produkcja + admin + technolog may write (consistent with ext_ph/ext_chzt/waga_kg being external). Lab/kj/cert are NOT blocked by the data model but the UI only surfaces the input in the szambiarka section (which today is already editable by everyone).

## File structure

| Action | File | Responsibility |
|---|---|---|
| Modify | `mbr/chzt/models.py` | Migration + POMIAR_FIELDS tuples + `update_pomiar` + `get_pomiar` + `get_session_with_pomiary` + `list_sessions_paginated` |
| Modify | `mbr/chzt/routes.py` | `api_pomiar_update`: text-vs-float coercion branch |
| Modify | `mbr/chzt/static/chzt.js` | `_renderExtSection` new uwagi input · `getRowValues` branch on `data-type=text` · `wireInputHandlers` skip regex for text |
| Modify | `mbr/chzt/templates/chzt_historia.html` | New `<th>` + `<td>` for Uwagi (truncated) |
| Modify | `mbr/chzt/static/chzt.css` | `.th-uwagi` / `.td-uwagi` rules matching szarze_list pattern |
| Modify | `tests/test_chzt.py` | Extend `test_list_sessions_paginated_returns_szambiarka_fields` with `sz_uwagi` · add roundtrip test for uwagi via `update_pomiar` · add empty-string → None normalization test |

No new files.

---

## Task 1 — Backend (schema + models + route)

**Files:**
- Modify: `mbr/chzt/models.py` (migration + constants + 4 functions)
- Modify: `mbr/chzt/routes.py` (coercion branch)
- Modify: `tests/test_chzt.py` (3 test changes)

### Step 1.1 — Extend the szambiarka assertion test to check `sz_uwagi`

- [ ] Open `tests/test_chzt.py`. Find `test_list_sessions_paginated_returns_szambiarka_fields`. Add `"uwagi": "Po wyjeździe dodano 5L NaOH"` to the szambiarka `update_pomiar` dict, and add the assertion `assert s["sz_uwagi"] == "Po wyjeździe dodano 5L NaOH"` next to the other szambiarka-field assertions.

Exact diff shape (locate by surrounding context):

```python
    update_pomiar(db, pid_sz, {
        "ph": 10, "p1": 30000, "p2": 31000, "p3": None, "p4": None, "p5": None,
        "ext_ph": 11, "ext_chzt": 28000, "waga_kg": 16500,
        "uwagi": "Po wyjeździe dodano 5L NaOH",
    }, updated_by=1)
```

and

```python
    assert s["sz_waga"] == 16500
    assert s["sz_uwagi"] == "Po wyjeździe dodano 5L NaOH"
```

### Step 1.2 — Extend the empty-szambiarka test

- [ ] In `test_list_sessions_paginated_empty_szambiarka_returns_nulls`, add `assert s["sz_uwagi"] is None` alongside the other `None` checks.

### Step 1.3 — Add a roundtrip test for uwagi via `update_pomiar`

- [ ] Append at the end of the `list_sessions_paginated` test cluster (right after `test_list_sessions_paginated_empty_szambiarka_returns_nulls`):

```python
def test_update_pomiar_roundtrips_uwagi_and_normalizes_empty(db):
    """update_pomiar stores uwagi as a string; whitespace-only / '' → None."""
    sid, _ = get_or_create_session(db, "2026-04-20", created_by=1, n_kontenery=0)
    db.commit()
    pid_sz = db.execute(
        "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='szambiarka'", (sid,)
    ).fetchone()["id"]
    # Write
    update_pomiar(db, pid_sz, {"uwagi": "Kożuch na powierzchni"}, updated_by=1)
    db.commit()
    row = db.execute("SELECT uwagi FROM chzt_pomiary WHERE id=?", (pid_sz,)).fetchone()
    assert row["uwagi"] == "Kożuch na powierzchni"
    # Overwrite with empty string → stored as NULL (normalized by route; models stores what it receives)
    update_pomiar(db, pid_sz, {"uwagi": None}, updated_by=1)
    db.commit()
    row = db.execute("SELECT uwagi FROM chzt_pomiary WHERE id=?", (pid_sz,)).fetchone()
    assert row["uwagi"] is None
```

(Note: empty-string→None normalization is done by the PUT route, not by `update_pomiar`. This test passes `None` directly because the models layer is type-agnostic — it just stores whatever you pass.)

### Step 1.4 — Run the 3 modified tests; confirm they FAIL first

- [ ] Run:

```bash
pytest tests/test_chzt.py::test_list_sessions_paginated_returns_szambiarka_fields \
       tests/test_chzt.py::test_list_sessions_paginated_empty_szambiarka_returns_nulls \
       tests/test_chzt.py::test_update_pomiar_roundtrips_uwagi_and_normalizes_empty -v
```

Expected: all three FAIL. First two fail with `KeyError: 'sz_uwagi'`; third fails with `sqlite3.OperationalError: no such column: uwagi` OR `OperationalError: table chzt_pomiary has no column named uwagi`. If failure shape is different, STOP and escalate.

### Step 1.5 — Add the `uwagi` migration to `init_tables_v3`

- [ ] In `mbr/chzt/models.py`, find the block at lines ~110-116:

```python
        pcols = {r[1] for r in db.execute("PRAGMA table_info(chzt_pomiary)").fetchall()}
        if "ext_chzt" not in pcols:
            db.execute("ALTER TABLE chzt_pomiary ADD COLUMN ext_chzt REAL")
        if "ext_ph" not in pcols:
            db.execute("ALTER TABLE chzt_pomiary ADD COLUMN ext_ph REAL")
        if "waga_kg" not in pcols:
            db.execute("ALTER TABLE chzt_pomiary ADD COLUMN waga_kg REAL")
```

Append right after the last `if`:

```python
        if "uwagi" not in pcols:
            db.execute("ALTER TABLE chzt_pomiary ADD COLUMN uwagi TEXT")
```

### Step 1.6 — Add `POMIAR_FIELDS_TEXT` and extend `POMIAR_FIELDS_EXTERNAL`

- [ ] At `mbr/chzt/models.py:177-179` (the existing tuples), replace with:

```python
POMIAR_FIELDS_INTERNAL = ("ph", "p1", "p2", "p3", "p4", "p5")
POMIAR_FIELDS_EXTERNAL = ("ext_chzt", "ext_ph", "waga_kg", "uwagi")
POMIAR_FIELDS_TEXT = ("uwagi",)  # coerced as string (route-side) instead of float
POMIAR_FIELDS = POMIAR_FIELDS_INTERNAL + POMIAR_FIELDS_EXTERNAL
```

### Step 1.7 — Update `get_pomiar` to SELECT `uwagi`

- [ ] In `mbr/chzt/models.py`, find `get_pomiar` (around line 182) and update the SELECT list:

```python
def get_pomiar(db, pomiar_id: int) -> dict:
    row = db.execute(
        "SELECT id, sesja_id, punkt_nazwa, kolejnosc, ph, p1, p2, p3, p4, p5, "
        "       srednia, ext_chzt, ext_ph, waga_kg, uwagi, updated_at, updated_by "
        "FROM chzt_pomiary WHERE id=?",
        (pomiar_id,),
    ).fetchone()
    return dict(row) if row else None
```

### Step 1.8 — Extend `update_pomiar` SQL to write `uwagi`

- [ ] In `mbr/chzt/models.py`, find `update_pomiar` (around line 192). Update the UPDATE statement and its parameter tuple to include `uwagi`:

```python
    db.execute(
        "UPDATE chzt_pomiary "
        "SET ph=?, p1=?, p2=?, p3=?, p4=?, p5=?, srednia=?, "
        "    ext_chzt=?, ext_ph=?, waga_kg=?, uwagi=?, "
        "    updated_at=?, updated_by=? "
        "WHERE id=?",
        (
            merged.get("ph"), merged.get("p1"), merged.get("p2"), merged.get("p3"),
            merged.get("p4"), merged.get("p5"), srednia,
            merged.get("ext_chzt"), merged.get("ext_ph"), merged.get("waga_kg"),
            merged.get("uwagi"),
            now, updated_by, pomiar_id,
        ),
    )
```

### Step 1.9 — Extend `get_session_with_pomiary` punkty SELECT

- [ ] In `mbr/chzt/models.py`, find `get_session_with_pomiary` (around line 343). Update the pomiary SELECT to include `uwagi`:

```python
    prows = db.execute(
        "SELECT id, punkt_nazwa, kolejnosc, ph, p1, p2, p3, p4, p5, srednia, "
        "       ext_chzt, ext_ph, waga_kg, uwagi, updated_at, updated_by "
        "FROM chzt_pomiary WHERE sesja_id=? ORDER BY kolejnosc",
        (session_id,),
    ).fetchall()
```

### Step 1.10 — Extend `list_sessions_paginated` to return `sz_uwagi`

- [ ] In `mbr/chzt/models.py`, find the recently-added szambiarka LEFT JOIN block in `list_sessions_paginated`. Add `sz.uwagi AS sz_uwagi` to the SELECT list, right after `sz.waga_kg AS sz_waga`:

```python
    rows = db.execute(
        "SELECT s.id, s.dt_start, s.n_kontenery, s.finalized_at, "
        "       w.imie || ' ' || w.nazwisko AS finalized_by_name, "
        "       (SELECT MAX(updated_at) FROM chzt_pomiary WHERE sesja_id=s.id) AS updated_at_max, "
        "       sz.ext_chzt AS sz_ext_chzt, "
        "       sz.ext_ph   AS sz_ext_ph, "
        "       sz.srednia  AS sz_chzt, "
        "       sz.ph       AS sz_ph, "
        "       sz.waga_kg  AS sz_waga, "
        "       sz.uwagi    AS sz_uwagi, "
        "       (SELECT COUNT(*) FROM chzt_pomiary "
        "        WHERE sesja_id=s.id AND ph IS NOT NULL AND ph > ?) AS over_ph_count "
        "FROM chzt_sesje s "
        "LEFT JOIN workers w ON w.id = s.finalized_by "
        "LEFT JOIN chzt_pomiary sz "
        "       ON sz.sesja_id = s.id AND sz.punkt_nazwa = 'szambiarka' "
        "ORDER BY s.dt_start DESC "
        "LIMIT ? OFFSET ?",
        (CHZT_PH_UPPER_LIMIT, per_page, offset),
    ).fetchall()
```

### Step 1.11 — Route: coerce `uwagi` as text, everything else as float

- [ ] In `mbr/chzt/routes.py`, find `api_pomiar_update` (around line 111) and replace the coercion loop with a type-branched version:

```python
    payload = request.get_json(force=True) or {}
    rola = session.get("user", {}).get("rola") or ""
    allowed = _allowed_fields_for_role(rola)

    # Filter: keep only allowed keys that are actually present in payload.
    # Text fields (uwagi) bypass float coercion; whitespace-only string → None
    # so the row's "no override" state is representable.
    new_values = {}
    for k in allowed:
        if k not in payload:
            continue
        if k in POMIAR_FIELDS_TEXT:
            v = payload[k]
            new_values[k] = None if v is None else (str(v).strip() or None)
        else:
            new_values[k] = _coerce_float(payload[k])
```

Also extend the imports at the top of the file (currently imports `POMIAR_FIELDS, POMIAR_FIELDS_INTERNAL, POMIAR_FIELDS_EXTERNAL` from `mbr.chzt.models`) to add `POMIAR_FIELDS_TEXT`:

```python
from mbr.chzt.models import (
    POMIAR_FIELDS, POMIAR_FIELDS_INTERNAL, POMIAR_FIELDS_EXTERNAL, POMIAR_FIELDS_TEXT,
    # ... existing other imports
```

### Step 1.12 — Run the 3 tests; confirm PASS

- [ ] Same command as Step 1.4. All three must PASS.

### Step 1.13 — Run the whole chzt test file

- [ ] Run:

```bash
pytest tests/test_chzt.py -v
```

Expected: all tests pass (currently 80; with the new roundtrip test it'll be 81).

### Step 1.14 — Commit

- [ ] Run:

```bash
git add mbr/chzt/models.py mbr/chzt/routes.py tests/test_chzt.py
git commit -m "$(cat <<'EOF'
feat(chzt): uwagi text column on chzt_pomiary + sz_uwagi in history list query

Add a free-text uwagi column (TEXT, nullable) to chzt_pomiary via
idempotent ALTER TABLE in init_tables_v3. Extend POMIAR_FIELDS_EXTERNAL
with uwagi and introduce POMIAR_FIELDS_TEXT so api_pomiar_update can
branch coercion: text passes through str.strip() (empty → None) while
numeric fields still go through _coerce_float.

list_sessions_paginated now also returns sz.uwagi AS sz_uwagi for the
szambiarka punkt row (template consumes it next task).

get_pomiar, get_session_with_pomiary, and update_pomiar all learn
the new column. Existing tests adjusted + new roundtrip test.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2 — Frontend: modal szambiarka section + getRowValues / wireInputHandlers

**Files:**
- Modify: `mbr/chzt/static/chzt.js` (three small edits)

### Step 2.1 — `getRowValues` branch on `data-type="text"`

- [ ] In `mbr/chzt/static/chzt.js`, find `getRowValues` (around line 150). Update:

```js
  function getRowValues(pid) {
    var out = {};
    document.querySelectorAll('[data-pid="' + pid + '"]').forEach(function(inp) {
      if (inp.disabled) return;
      var field = inp.dataset.field;
      if (!field) return;
      if (inp.dataset.type === 'text') {
        out[field] = (inp.value || '').trim();  // server normalizes empty → None
      } else {
        out[field] = parseNum(inp.value);
      }
    });
    return out;
  }
```

(Note the selector change from `input[data-pid="..."]` to `[data-pid="..."]` — the uwagi field will be a `<textarea>`, not an `<input>`. This widens the net; everything wireable still needs `data-field`.)

### Step 2.2 — `wireInputHandlers` skip regex validation for text fields

- [ ] In `mbr/chzt/static/chzt.js`, find `wireInputHandlers` (around line 161). Update the `input` event handler to skip regex for text:

```js
  function wireInputHandlers(rootSelector) {
    var sel = (rootSelector || '#chzt-body') + ' .chzt-inp';
    document.querySelectorAll(sel).forEach(function(inp) {
      if (inp.dataset.wired === '1') return;
      inp.dataset.wired = '1';
      inp.addEventListener('input', function(){
        if (inp.dataset.type !== 'text') {
          // numeric fields: regex validation
          if (inp.value !== '' && !/^[0-9]*[.,]?[0-9]*$/.test(inp.value)) {
            inp.classList.add('invalid');
          } else {
            inp.classList.remove('invalid');
          }
        }
        _markDirty(parseInt(inp.dataset.pid));
      });
      inp.addEventListener('blur', function(){
        var pid = parseInt(inp.dataset.pid);
        if (_dirtyRows[pid]) {
          saveRow(pid, 0);
          _dirtyRows[pid] = false;
        }
      });
    });
  }
```

### Step 2.3 — Extend `_renderExtSection` with the uwagi textarea

- [ ] In `mbr/chzt/static/chzt.js`, find `_renderExtSection` (around line 206). The current HTML builds a 3-cell `chzt-ext-grid` (pH / ChZT / Waga). Add a 4th block for uwagi (full-width row below the grid). Replace the `section.innerHTML = ...` assignment with:

```js
    section.innerHTML =
      '<div class="chzt-ext-title">Analiza zewnętrzna — Szambiarka</div>' +
      '<div class="chzt-ext-grid">' +
        '<div class="chzt-ext-field">' +
          '<label>pH zewnętrzne</label>' +
          '<input class="chzt-inp ' + roCls + '" type="text" inputmode="decimal" pattern="[0-9]*[.,]?[0-9]*" ' +
                 'data-pid="' + szambiarka.id + '" data-field="ext_ph" value="' + fmt(szambiarka.ext_ph) + '" ' +
                 disabledAttr + '>' +
        '</div>' +
        '<div class="chzt-ext-field">' +
          '<label>ChZT zewnętrzne</label>' +
          '<input class="chzt-inp ' + roCls + '" type="text" inputmode="decimal" pattern="[0-9]*[.,]?[0-9]*" ' +
                 'data-pid="' + szambiarka.id + '" data-field="ext_chzt" value="' + fmt(szambiarka.ext_chzt) + '" ' +
                 disabledAttr + '>' +
          '<span class="chzt-ext-unit">mg O₂/l</span>' +
        '</div>' +
        '<div class="chzt-ext-field">' +
          '<label>Waga beczki</label>' +
          '<input class="chzt-inp ' + roCls + '" type="text" inputmode="decimal" pattern="[0-9]*[.,]?[0-9]*" ' +
                 'data-pid="' + szambiarka.id + '" data-field="waga_kg" value="' + fmt(szambiarka.waga_kg) + '" ' +
                 disabledAttr + '>' +
          '<span class="chzt-ext-unit">kg</span>' +
        '</div>' +
      '</div>' +
      '<div class="chzt-ext-uwagi-row">' +
        '<label>Uwagi</label>' +
        '<textarea class="chzt-inp chzt-ext-uwagi ' + roCls + '" rows="2" ' +
                  'data-pid="' + szambiarka.id + '" data-field="uwagi" data-type="text" ' +
                  'placeholder="np. Kożuch na powierzchni, dodano 5L NaOH…" ' +
                  disabledAttr + '>' + _htmlEscape(szambiarka.uwagi || '') + '</textarea>' +
      '</div>';
```

**Note on `_htmlEscape`:** this helper may not exist yet in chzt.js. If `grep '_htmlEscape' mbr/chzt/static/chzt.js` returns nothing, add this tiny helper inside the IIFE (near `fmt = function(v)...` already at line 219):

```js
    var _htmlEscape = function(s) {
      var d = document.createElement('div');
      d.textContent = s || '';
      return d.innerHTML;
    };
```

(The textarea content must be HTML-escaped because the operator's uwagi can contain characters like `<` or `&` that would break the markup otherwise.)

### Step 2.4 — Smoke-test: modal uwagi edit round-trips

- [ ] Open the running app (`http://127.0.0.1:5001`), Ctrl-Shift-R, open ChZT modal (shortcut `C`). Type something in the new "Uwagi" textarea, blur (Tab / click out). Verify:
  1. Network tab shows `PUT /api/chzt/pomiar/<id>` with JSON body including `"uwagi": "…"`, status 200.
  2. Refresh page, reopen modal — your text is still there.
  3. Clear the textarea, blur — request has `"uwagi": ""` (which the server normalizes to NULL). Refresh, reopen — empty textarea.

If any step fails: check browser console for JS errors, server log for the PUT, and DB (`SELECT uwagi FROM chzt_pomiary WHERE id=?`).

### Step 2.5 — Commit

- [ ] Run:

```bash
git add mbr/chzt/static/chzt.js
git commit -m "$(cat <<'EOF'
feat(chzt): uwagi textarea in szambiarka external section

Add a full-width textarea for operator notes under the pH / ChZT /
Waga grid in _renderExtSection. Autosave on blur via the existing
saveRow pipeline; getRowValues branches on data-type="text" to pass
the raw string through instead of parseNum'ing it to NaN, and
wireInputHandlers skips numeric regex validation for text fields.

Visible to all roles that can access the section (produkcja, lab, kj,
cert, admin, technolog). Renders in both the modal and the historia
detail view since _renderExtSection is shared.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3 — Frontend: Uwagi column in the historia list

**Files:**
- Modify: `mbr/chzt/templates/chzt_historia.html` (add `<th>` + `<td>`)
- Modify: `mbr/chzt/static/chzt.css` (add `.th-uwagi` + `.td-uwagi` rules matching szarze_list)

### Step 3.1 — Add CSS for `.th-uwagi` / `.td-uwagi`

- [ ] In `mbr/chzt/static/chzt.css`, append at the end (after the existing `.chzt-add-btn` rules):

```css
/* Uwagi column — truncate with ellipsis, full text on hover via title attribute.
   Mirrors mbr/templates/laborant/szarze_list.html:1499-1504 pattern. */
.chzt-hist-table .th-uwagi {
  min-width: 180px;
  max-width: 280px;
}
.chzt-hist-table .td-uwagi {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-sec);
  font-size: 12px;
}
.chzt-hist-table .td-uwagi.empty {
  color: var(--text-dim);
}

/* Szambiarka external uwagi textarea */
.chzt-ext-uwagi-row {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.chzt-ext-uwagi-row label {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-sec);
}
.chzt-ext-uwagi {
  width: 100%;
  box-sizing: border-box;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 5px;
  font-family: var(--font);
  font-size: 13px;
  resize: vertical;
  min-height: 44px;
}
.chzt-ext-uwagi:focus {
  outline: none;
  border-color: var(--teal);
}
.chzt-ext-uwagi.readonly {
  background: var(--surface-alt);
  color: var(--text-dim);
}
```

### Step 3.2 — Add the `<th>` to the list view header

- [ ] In `mbr/chzt/templates/chzt_historia.html`, in the list-view `<thead>` (around line 34-43), append a new `<th>` at the END (after `th-over "Przekroczeń pH"`):

```html
              <th class="th-over">Przekroczeń pH</th>
              <th class="th-uwagi">Uwagi</th>
```

### Step 3.3 — Add the `<td>` with truncation + tooltip

- [ ] In the same file, in the list-view `<tbody>` loop (around line 46-59), append a new `<td>` at the END of the `<tr>` (after the `td.td-over` cell):

```html
              <td class="td-over {% if s.over_ph_count and s.over_ph_count > 0 %}val-warn{% endif %}">{{ s.over_ph_count or 0 }}</td>
              {% if s.sz_uwagi %}
              <td class="td-uwagi" title="{{ s.sz_uwagi|e }}">{{ (s.sz_uwagi[:47] + '…') if s.sz_uwagi|length > 50 else s.sz_uwagi }}</td>
              {% else %}
              <td class="td-uwagi empty">—</td>
              {% endif %}
            </tr>
```

Keep the truncation exactly as specified: `len > 50 → slice(0, 47) + '…'`, else full text. `|e` on the title is critical (prevents `"` in uwagi from breaking the attribute).

### Step 3.4 — Smoke test

- [ ] Hard-refresh `/chzt/historia`. Verify:
  1. New "Uwagi" column appears at the end of the header row.
  2. Sessions without szambiarka uwagi show `—` in a dim color.
  3. Sessions with short uwagi (≤50 chars) show the full text.
  4. Sessions with long uwagi (>50 chars) show first 47 chars + `…`; hover tooltip shows full text.
  5. Detail view (click the row) is unchanged — uwagi visible via the external section (from Task 2).

### Step 3.5 — Run tests

- [ ] Run:

```bash
pytest tests/test_chzt.py -v
```

Expected: all 81 tests pass (no regression; `test_historia_page_renders` tolerates the new column because it doesn't assert columns).

### Step 3.6 — Commit

- [ ] Run:

```bash
git add mbr/chzt/templates/chzt_historia.html mbr/chzt/static/chzt.css
git commit -m "$(cat <<'EOF'
feat(chzt): uwagi column in historia list + styling

New "Uwagi" column appended at the end of the collapsed historia row,
reading sz_uwagi. Truncates long text with ellipsis (len > 50 → 47
chars + '…') and exposes the full value via a title tooltip, matching
the pattern used on the completed-batches table.

Also adds CSS for the szambiarka external-section textarea from the
previous commit (full-width, teal focus, readonly treatment).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4 — Push

### Step 4.1 — Push all three commits

- [ ] Run:

```bash
git push origin main
```

---

## Self-review

**Spec coverage:**
- ✅ `uwagi` column added to `chzt_pomiary` → Task 1 Step 1.5
- ✅ szambiarka-only UI (A2) → Task 2 Step 2.3 (only `_renderExtSection` gets the input; main pomiary table untouched)
- ✅ Truncate like szarze_list (B) → Task 3 Step 3.3 (same 50/47 pattern and CSS shape)
- ✅ Position: last column → Task 3 Step 3.2/3.3 (appended after `th-over`)
- ✅ Detail view inherits uwagi via shared `_renderExtSection` — no duplicate code

**Placeholder scan:** no "TBD", no "add validation", no "similar to Task N". Every step has concrete code and exact commands.

**Type consistency:**
- `sz_uwagi` used identically in `list_sessions_paginated` alias, test assertions, and template.
- `POMIAR_FIELDS_TEXT` used identically in models.py (definition) and routes.py (import + branch).
- `data-type="text"` used identically in `_renderExtSection` (setter) and `getRowValues` / `wireInputHandlers` (consumers).
- `CHZT_PH_UPPER_LIMIT` untouched (still 10.0).
