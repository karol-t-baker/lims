# CHZT Historia — szambiarka-centric list columns

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Swap the collapsed history row of `/chzt/historia` from session-wide aggregates (Śr. ChZT, Min, Max, Rozstęp, Przekroczeń >40k, Śr. pH, Status, Sfinalizował) to the szambiarka-centric row (Data, ChZT zew, pH zew, ChZT, pH, Waga) while keeping Kontenery and replacing "Przekroczeń >40k" with "Przekroczeń pH". Expanded detail view and the modal stay unchanged.

**Architecture:** The backend `list_sessions_paginated()` already joins a LEFT tuple per session; we add szambiarka fields via a LEFT JOIN on a filtered subquery of `chzt_pomiary WHERE punkt_nazwa='szambiarka'`, and swap the `over_40k_count` subquery for an `over_ph_count` using a module-level threshold constant. The Jinja template swaps `<thead>`/`<tbody>` columns one-for-one.

**Tech Stack:** Python 3 / Flask / sqlite3 (raw queries, no ORM) · Jinja2 · pytest · vanilla JS (no change this plan).

---

## Design decisions (configurable post-implementation)

- **pH upper limit**: `CHZT_PH_UPPER_LIMIT = 10.0` constant in `mbr/chzt/models.py`. Rows with `ph > 10.0` counted as "przekroczenie". Change the constant in one place to retune.
- **szambiarka "ChZT" value**: `srednia` column of the szambiarka `chzt_pomiary` row (mean of P1-P5 that the laborant already fills in the modal).
- **szambiarka "pH" value**: `ph` column of the same row (internal measurement, not `ext_ph`).
- **Missing szambiarka row**: all six szambiarka columns (ChZT zew, pH zew, ChZT, pH, Waga) render `—`.
- **Dropped columns from current view**: Min, Max, Rozstęp, Śr. ChZT, Śr. pH, Status, Sfinalizował. Status+finalizator are still visible after expanding the row.

## File structure

| Action | File | Responsibility |
|---|---|---|
| Modify | `mbr/chzt/models.py` | `list_sessions_paginated()` query + new `CHZT_PH_UPPER_LIMIT` constant |
| Modify | `mbr/chzt/templates/chzt_historia.html` | List-view `<table>` columns (lines 32-70) |
| Modify | `tests/test_chzt.py` | Replace `test_list_sessions_paginated_includes_avg_and_max` with szambiarka + pH-count assertions; add empty-szambiarka test |

No new files. No route changes (route just forwards the dict). No JS changes.

---

## Task 1 — Backend: szambiarka columns + `CHZT_PH_UPPER_LIMIT`

**Files:**
- Modify: `mbr/chzt/models.py:310-340` (`list_sessions_paginated`) + top-of-file constant
- Modify: `tests/test_chzt.py:498-519` (replace existing assertion test)
- Modify: `tests/test_chzt.py` (add empty-szambiarka test after the replaced one)

### Step 1.1 — Replace the existing positive-case test

- [ ] Replace the body of `test_list_sessions_paginated_includes_avg_and_max` (currently lines 498-519) with the szambiarka-aware version. Also rename it for clarity.

```python
def test_list_sessions_paginated_returns_szambiarka_fields(db):
    sid, _ = get_or_create_session(db, "2026-04-18", created_by=1, n_kontenery=1)
    db.commit()
    pid_hala = db.execute(
        "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='hala'", (sid,)
    ).fetchone()["id"]
    pid_k1 = db.execute(
        "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='kontener 1'", (sid,)
    ).fetchone()["id"]
    pid_sz = db.execute(
        "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='szambiarka'", (sid,)
    ).fetchone()["id"]
    update_pomiar(db, pid_hala, {"ph": 9, "p1": 20000, "p2": 22000, "p3": None, "p4": None, "p5": None}, updated_by=1)
    update_pomiar(db, pid_k1,   {"ph": 11, "p1": 45000, "p2": 44000, "p3": None, "p4": None, "p5": None}, updated_by=1)
    update_pomiar(db, pid_sz, {
        "ph": 10, "p1": 30000, "p2": 31000, "p3": None, "p4": None, "p5": None,
        "ext_ph": 11, "ext_chzt": 28000, "waga_kg": 16500,
    }, updated_by=1)
    db.commit()
    page = list_sessions_paginated(db, page=1, per_page=10)
    s = page["sesje"][0]
    # szambiarka row fields
    assert s["sz_chzt"] == 30500       # avg of 30000, 31000
    assert s["sz_ph"] == 10
    assert s["sz_ext_chzt"] == 28000
    assert s["sz_ext_ph"] == 11
    assert s["sz_waga"] == 16500
    # pH breach count: hala=9 OK, k1=11 > 10 ✓, szambiarka=10 NOT over (strict >)
    assert s["over_ph_count"] == 1
    # n_kontenery passthrough
    assert s["n_kontenery"] == 1
```

**Note:** this replaces the old test — delete the old `test_list_sessions_paginated_includes_avg_and_max` body entirely (lines 498-519 of the current file).

### Step 1.2 — Add the empty-szambiarka test right after it

- [ ] Append a new test function right below the one from Step 1.1.

```python
def test_list_sessions_paginated_empty_szambiarka_returns_nulls(db):
    """Session with no measurements on the szambiarka punkt → sz_* fields are None
    and over_ph_count is 0. Template renders '—' for None."""
    sid, _ = get_or_create_session(db, "2026-04-19", created_by=1, n_kontenery=0)
    db.commit()
    page = list_sessions_paginated(db, page=1, per_page=10)
    s = page["sesje"][0]
    assert s["sz_chzt"] is None
    assert s["sz_ph"] is None
    assert s["sz_ext_chzt"] is None
    assert s["sz_ext_ph"] is None
    assert s["sz_waga"] is None
    assert s["over_ph_count"] == 0
```

### Step 1.3 — Run the two tests; confirm they fail for the right reason

- [ ] Run:

```bash
pytest tests/test_chzt.py::test_list_sessions_paginated_returns_szambiarka_fields tests/test_chzt.py::test_list_sessions_paginated_empty_szambiarka_returns_nulls -v
```

Expected: both FAIL with `KeyError: 'sz_chzt'` (or similar), because the query doesn't yet return these fields. **DO NOT proceed if failure is for any other reason** (e.g. `get_or_create_session` missing szambiarka punkt — inspect seeding).

### Step 1.4 — Add the constant to `mbr/chzt/models.py`

- [ ] Open `mbr/chzt/models.py`. Right under the existing module docstring / imports block (before the first `def`), add:

```python
# Threshold for "pH exceedance" count shown in the history list view.
# Only the upper bound is checked (matches the existing ">40k ChZT" upper-only
# framing). Change this single constant to retune.
CHZT_PH_UPPER_LIMIT = 10.0
```

(If you cannot find a clean spot — put it immediately after the imports and before the first `def`. The exact location in the file is cosmetic; tests don't care.)

### Step 1.5 — Rewrite the `list_sessions_paginated` query

- [ ] Replace the `rows = db.execute(...)` block inside `list_sessions_paginated` (currently `mbr/chzt/models.py:319-333`) with:

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

Notes for the executor:
- The old 5 scalar-subselects (`avg_chzt`, `min_chzt`, `max_chzt`, `over_40k_count`, `avg_ph`) are **deleted**, not kept. No other code reads them — `chzt_historia.html` is the only consumer and we rewrite it in Task 2.
- The `LEFT JOIN chzt_pomiary sz ON ... AND punkt_nazwa='szambiarka'` is safe: `UNIQUE(sesja_id, punkt_nazwa)` on `chzt_pomiary` guarantees at most one szambiarka row per sesja.
- The `?` placeholder for `CHZT_PH_UPPER_LIMIT` goes FIRST in the params tuple (inside the SELECT clause), then `per_page`, then `offset`. Check the ordering carefully — getting this wrong silently shifts all filters.

### Step 1.6 — Run the two new tests; confirm they pass

- [ ] Run the same command as Step 1.3. Expected: both PASS.

### Step 1.7 — Run the whole chzt test file; confirm no regression

- [ ] Run:

```bash
pytest tests/test_chzt.py -v
```

Expected: all tests pass. If `test_list_sessions_paginated_desc_order`, `test_list_sessions_paginated_splits_pages`, `test_list_sessions_paginated_sorts_by_dt_start_desc`, `test_list_sessions_paginated_returns_dt_start_not_data` break — they use only `dt_start`/`total`/`pages`/etc., which didn't change, so a failure indicates a regression in my SQL. Fix before continuing.

### Step 1.8 — Commit

- [ ] Run:

```bash
git add mbr/chzt/models.py tests/test_chzt.py
git commit -m "$(cat <<'EOF'
feat(chzt): szambiarka-centric fields + pH exceedance count in list_sessions_paginated

Add CHZT_PH_UPPER_LIMIT constant (default 10.0). Rewrite the history
list query to return sz_ext_chzt / sz_ext_ph / sz_chzt / sz_ph /
sz_waga (read from the szambiarka punkt row via LEFT JOIN) and
over_ph_count. Drop the unused session-wide avg_chzt / min_chzt /
max_chzt / over_40k_count / avg_ph that no longer feed the template.

Replaces tests/test_chzt.py::test_list_sessions_paginated_includes_avg_and_max
with a szambiarka-aware variant and adds the empty-szambiarka case.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2 — Frontend: swap list-view columns

**Files:**
- Modify: `mbr/chzt/templates/chzt_historia.html:33-67` (list view `<thead>` + `<tbody>`)

### Step 2.1 — Rewrite the `<thead>` row

- [ ] Replace lines 33-46 (`<thead>…</thead>`) with:

```html
          <thead>
            <tr>
              <th class="th-date">Data</th>
              <th class="th-sz-ext-chzt">ChZT zew</th>
              <th class="th-sz-ext-ph">pH zew</th>
              <th class="th-sz-chzt">ChZT</th>
              <th class="th-sz-ph">pH</th>
              <th class="th-sz-waga">Waga</th>
              <th class="th-kont">Kontenery</th>
              <th class="th-over">Przekroczeń pH</th>
            </tr>
          </thead>
```

### Step 2.2 — Rewrite the row loop

- [ ] Replace lines 47-68 (`<tbody>…</tbody>`) with:

```html
          <tbody>
            {% for s in sesje %}
            {% set fmt_int = '{:,}'.format(s.sz_ext_chzt|int).replace(',', ' ') if s.sz_ext_chzt is not none else None %}
            {% set fmt_chzt = '{:,}'.format(s.sz_chzt|int).replace(',', ' ') if s.sz_chzt is not none else None %}
            <tr class="chzt-hist-row" data-sid="{{ s.id }}" data-data="{{ s.dt_start }}" onclick="chztShowDetail({{ s.id }}, '{{ s.dt_start }}')">
              <td class="td-date-iso">{{ s.dt_start|pl_date }}</td>
              <td class="td-sz-ext-chzt">{{ fmt_int if fmt_int is not none else '—' }}</td>
              <td class="td-sz-ext-ph">{% if s.sz_ext_ph is not none %}{{ ('%.1f' % s.sz_ext_ph)|replace('.', ',') }}{% else %}—{% endif %}</td>
              <td class="td-sz-chzt">{{ fmt_chzt if fmt_chzt is not none else '—' }}</td>
              <td class="td-sz-ph">{% if s.sz_ph is not none %}{{ ('%.1f' % s.sz_ph)|replace('.', ',') }}{% else %}—{% endif %}</td>
              <td class="td-sz-waga">{% if s.sz_waga is not none %}{{ '{:,}'.format(s.sz_waga|int).replace(',', ' ') }}{% else %}—{% endif %}</td>
              <td class="td-kont">{{ s.n_kontenery }}</td>
              <td class="td-over {% if s.over_ph_count and s.over_ph_count > 0 %}val-warn{% endif %}">{{ s.over_ph_count or 0 }}</td>
            </tr>
            {% endfor %}
          </tbody>
```

**Notes for the executor:**
- Keep the `onclick="chztShowDetail(...)"` binding unchanged — that's what expands the row into the existing detail view.
- Do NOT touch lines 83-116 (detail view) — it stays as-is per user requirement.
- The `val-warn` class on the last `<td>` is the **same** CSS class used by the old "Przekroczeń >40k" column (it already exists in `chzt.css` — verify with `grep val-warn mbr/chzt/static/chzt.css` before the next step; if it's not a class I recognize, don't add a new CSS rule — just keep the class name for consistency).
- pH formatting: `%.1f` with `,` decimal separator matches the old `avg_ph` formatting so operators see the same style.

### Step 2.3 — Smoke test in the browser

- [ ] Hard-refresh `/chzt/historia` in the browser. Verify:
  1. Header row shows: `Data | ChZT zew | pH zew | ChZT | pH | Waga | Kontenery | Przekroczeń pH`.
  2. Each data row shows szambiarka values; rows with no szambiarka pomiary show `—` in the 5 szambiarka cells.
  3. Clicking a row still opens the detail view (unchanged per-punkt P1-P5 table).
  4. "+ Dodaj nowy pomiar" button still works (from previous commit).

**If the page 500s:** check Flask log — most likely a typo in the template's Jinja conditional; the `is not none` (not `!= None`) distinction matters with `sqlite3.Row` → dict values.

### Step 2.4 — Commit

- [ ] Run:

```bash
git add mbr/chzt/templates/chzt_historia.html
git commit -m "$(cat <<'EOF'
feat(chzt): history list view shows szambiarka row per session

Collapsed rows of /chzt/historia now display Data, ChZT zew, pH zew,
ChZT, pH, Waga (all from the szambiarka punkt), plus the surviving
Kontenery and Przekroczeń pH (count of pomiary with ph > 10.0).

Dropped columns from the list view: Śr. ChZT, Min, Max, Rozstęp,
Przekroczeń >40k, Śr. pH, Status, Sfinalizował. Sessions without a
szambiarka pomiar render "—" in the five szambiarka cells. The
expanded detail view is unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3 — Push

### Step 3.1 — Push both commits

- [ ] Run:

```bash
git push origin main
```

---

## Self-review

**Spec coverage:**
- ✅ Data, ChZT zew, pH zew, ChZT, pH, Waga columns → Task 2 Step 2.1/2.2
- ✅ Kontenery column kept → Task 2 Step 2.1/2.2
- ✅ "Ilość przekroczeń pH" column → Task 1 `over_ph_count` + Task 2 last `<td>`
- ✅ Expanded view unchanged → no edits to lines 83-116 of `chzt_historia.html`
- ✅ Empty szambiarka → `—` → Task 1 Step 1.2 test + Task 2 `is not none` checks

**Placeholder scan:** no "TBD", no "add validation", no "similar to Task N". Every step has concrete code and exact commands.

**Type consistency:** `sz_ext_chzt`, `sz_ext_ph`, `sz_chzt`, `sz_ph`, `sz_waga`, `over_ph_count` — all six names used identically in SQL aliases (Task 1 Step 1.5), test assertions (Task 1 Step 1.1-1.2) and template bindings (Task 2 Step 2.2). `CHZT_PH_UPPER_LIMIT` is used both in SQL params (Task 1 Step 1.5) and conceptually in the commit message; no divergent spellings.
