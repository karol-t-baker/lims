# FAU `<1` quick-entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dodać przycisk "<1" obok pola `metnosc_fau` w Fast Entry, który zapisuje wartość jakościową "<1" zamiast liczby (stored jako `wartosc_text` w istniejącej kolumnie DB).

**Architecture:** Backend rozszerzenie `save_wyniki` — akceptuje prefix `<>≤≥`, zapisuje do `wartosc_text` z `wartosc=NULL`. Frontend w `_fast_entry_content.html` — dla `kod === "metnosc_fau"` renderuje mały przycisk "<1" obok input-u; klik → wartość "<1" + input readonly; reload czyta `wartosc_text` i odtwarza stan.

**Tech Stack:** Python 3 · sqlite3 (raw) · Flask · vanilla JS · pytest.

---

## File Structure

### Modyfikowane

- `mbr/laborant/models.py:545-684` — `save_wyniki` rozszerzone o qualitative parser i INSERT/UPDATE `wartosc_text`.
- `mbr/templates/laborant/_fast_entry_content.html` — FF div generator + renderer wyników + CSS dla stanu readonly.
- `tests/test_fau_below_lod.py` — nowy plik z testami save_wyniki qualitative flow.

### Nietykane

- Schemat DB — kolumna `wartosc_text` już istnieje w `ebr_wyniki`.
- `mbr/certs/*` — cert generator nie propaguje wartosc_text (per spec, potwierdzić manualnie).
- `get_ebr_wyniki` — zwraca pełny row dict, więc wartosc_text już wraca do frontendu.

---

## Task 1: Backend — `save_wyniki` akceptuje qualitative prefix

**Files:**
- Modify: `mbr/laborant/models.py:585-683`
- Test: `tests/test_fau_below_lod.py` (nowy)

### Step 1: Failing test

Utwórz `tests/test_fau_below_lod.py`:

```python
"""Tests for qualitative value handling in save_wyniki (FAU <1 flow)."""
import json
import sqlite3
import pytest

from mbr.models import init_mbr_tables
from mbr.laborant.models import save_wyniki, get_ebr_wyniki


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _setup_ebr_with_fau(db) -> int:
    """Create an MBR + EBR with metnosc_fau in analiza_koncowa."""
    parametry_lab = {
        "analiza_koncowa": {
            "pola": [
                {"kod": "metnosc_fau", "tag": "metnosc_fau", "precision": 1, "min": 0, "max": 50},
                {"kod": "ph", "tag": "ph", "precision": 2, "min": 6, "max": 8},
            ],
        },
    }
    cur = db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, dt_utworzenia) "
        "VALUES ('TestFAU', 1, 'active', '[]', ?, datetime('now'))",
        (json.dumps(parametry_lab),),
    )
    mbr_id = cur.lastrowid
    cur = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, produkt, parametry_lab) "
        "VALUES (?, 'B001', '1/2026', datetime('now'), 'active', 'TestFAU', ?)",
        (mbr_id, json.dumps(parametry_lab)),
    )
    db.commit()
    return cur.lastrowid


def test_save_wyniki_stores_lod_prefix_in_wartosc_text(db):
    """Value '<1' saves as wartosc_text, wartosc=NULL."""
    ebr_id = _setup_ebr_with_fau(db)
    save_wyniki(db, ebr_id, "analiza_koncowa",
                {"metnosc_fau": {"wartosc": "<1", "komentarz": ""}},
                "testuser")
    row = db.execute(
        "SELECT wartosc, wartosc_text, w_limicie FROM ebr_wyniki "
        "WHERE ebr_id=? AND kod_parametru='metnosc_fau'",
        (ebr_id,),
    ).fetchone()
    assert row is not None
    assert row["wartosc"] is None
    assert row["wartosc_text"] == "<1"
    assert row["w_limicie"] is None  # neutral — nie oceniamy jakościowo


def test_save_wyniki_numeric_clears_wartosc_text(db):
    """Numeric value overwrites previous qualitative state."""
    ebr_id = _setup_ebr_with_fau(db)
    save_wyniki(db, ebr_id, "analiza_koncowa",
                {"metnosc_fau": {"wartosc": "<1", "komentarz": ""}},
                "u1")
    save_wyniki(db, ebr_id, "analiza_koncowa",
                {"metnosc_fau": {"wartosc": "3,5", "komentarz": ""}},
                "u2")
    row = db.execute(
        "SELECT wartosc, wartosc_text FROM ebr_wyniki "
        "WHERE ebr_id=? AND kod_parametru='metnosc_fau'",
        (ebr_id,),
    ).fetchone()
    assert row["wartosc"] == 3.5
    assert row["wartosc_text"] is None


def test_save_wyniki_supports_all_comparison_prefixes(db):
    """Prefixes <, >, ≤, ≥ all route to wartosc_text."""
    ebr_id = _setup_ebr_with_fau(db)
    for val in ["<1", ">50", "≤1", "≥50"]:
        save_wyniki(db, ebr_id, "analiza_koncowa",
                    {"metnosc_fau": {"wartosc": val, "komentarz": ""}},
                    "u")
        row = db.execute(
            "SELECT wartosc, wartosc_text FROM ebr_wyniki "
            "WHERE ebr_id=? AND kod_parametru='metnosc_fau'",
            (ebr_id,),
        ).fetchone()
        assert row["wartosc"] is None, f"wartosc not None for {val}"
        assert row["wartosc_text"] == val


def test_save_wyniki_rejects_junk_text(db):
    """Plain non-numeric, non-prefix text is still rejected (silent skip)."""
    ebr_id = _setup_ebr_with_fau(db)
    save_wyniki(db, ebr_id, "analiza_koncowa",
                {"metnosc_fau": {"wartosc": "abc", "komentarz": ""}},
                "u")
    row = db.execute(
        "SELECT wartosc, wartosc_text FROM ebr_wyniki "
        "WHERE ebr_id=? AND kod_parametru='metnosc_fau'",
        (ebr_id,),
    ).fetchone()
    assert row is None, "junk text should not create a row"


def test_save_wyniki_numeric_unchanged_behavior(db):
    """Normal numeric flow still works."""
    ebr_id = _setup_ebr_with_fau(db)
    save_wyniki(db, ebr_id, "analiza_koncowa",
                {"ph": {"wartosc": "7,20", "komentarz": ""}},
                "u")
    row = db.execute(
        "SELECT wartosc, wartosc_text, w_limicie FROM ebr_wyniki "
        "WHERE ebr_id=? AND kod_parametru='ph'",
        (ebr_id,),
    ).fetchone()
    assert row["wartosc"] == 7.20
    assert row["wartosc_text"] is None
    assert row["w_limicie"] == 1
```

### Step 2: Run — tests should fail

```bash
cd /Users/tbk/Desktop/lims-clean
python -m pytest tests/test_fau_below_lod.py -v --no-header
```

Expected: 5 failed (save_wyniki silently drops `<1`; wartosc_text never populated).

### Step 3: Modify `save_wyniki`

In `mbr/laborant/models.py`, find the loop starting at `for kod, entry in values.items():` (around line 585). Current code:

```python
        wartosc_raw = entry.get("wartosc", "")
        komentarz = entry.get("komentarz", "")
        try:
            wartosc = float(str(wartosc_raw).replace(",", "."))
        except (ValueError, TypeError):
            continue
```

Replace with qualitative-aware parsing:

```python
        wartosc_raw = entry.get("wartosc", "")
        komentarz = entry.get("komentarz", "")
        # Qualitative prefix (<1, >50, ≤1, ≥50) — below/above detection
        # limit. Stored as wartosc_text, wartosc=NULL, w_limicie=NULL
        # (neutral — not numerically evaluated). Used for FAU <1 and
        # similar analytical-chemistry conventions.
        raw_str = str(wartosc_raw).strip()
        is_qualitative = bool(raw_str) and raw_str[0] in ("<", ">", "≤", "≥")
        if is_qualitative:
            wartosc = None
            wartosc_text = raw_str
        else:
            try:
                wartosc = float(raw_str.replace(",", "."))
            except (ValueError, TypeError):
                continue
            wartosc_text = None
```

Now extend the rounding/w_limicie/INSERT blocks to handle `wartosc is None` (qualitative path). Replace the block starting at `wartosc = round(wartosc, prec)` (around line 646) through the INSERT statement with:

```python
        if wartosc is not None:
            wartosc = round(wartosc, prec)

        # Check existing row for diff tracking (after rounding)
        old_row = db.execute(
            "SELECT wynik_id, wartosc, wartosc_text FROM ebr_wyniki "
            "WHERE ebr_id=? AND sekcja=? AND kod_parametru=?",
            (ebr_id, sekcja, kod),
        ).fetchone()
        if old_row:
            has_updates = True
            old_val = old_row["wartosc"] if old_row["wartosc"] is not None else old_row["wartosc_text"]
            new_val = wartosc if wartosc is not None else wartosc_text
            if old_val != new_val:
                diffs.append({"pole": kod, "stara": old_val, "nowa": new_val})
        else:
            has_inserts = True
            new_val = wartosc if wartosc is not None else wartosc_text
            diffs.append({"pole": kod, "stara": None, "nowa": new_val})

        # Compute w_limicie — only for numeric values
        if wartosc_text is not None:
            w_limicie = None
        else:
            w_limicie = 1
            if min_limit is not None and wartosc < min_limit:
                w_limicie = 0
            if max_limit is not None and wartosc > max_limit:
                w_limicie = 0

        db.execute("""
            INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc, wartosc_text,
                min_limit, max_limit, w_limicie, komentarz, is_manual, dt_wpisu, wpisal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(ebr_id, sekcja, kod_parametru) DO UPDATE SET
                wartosc = excluded.wartosc,
                wartosc_text = excluded.wartosc_text,
                min_limit = excluded.min_limit,
                max_limit = excluded.max_limit,
                w_limicie = excluded.w_limicie,
                komentarz = excluded.komentarz,
                dt_wpisu = excluded.dt_wpisu,
                wpisal = excluded.wpisal
                -- samples_json intentionally NOT overwritten here
        """, (ebr_id, sekcja, kod, tag, wartosc, wartosc_text, min_limit, max_limit,
              w_limicie, komentarz, now, user))
```

Key changes:
- `wartosc_text` dodany do kolumny INSERT + na VALUES (po `wartosc`)
- `wartosc_text = excluded.wartosc_text` w ON CONFLICT UPDATE (tak że przełączenie z qualitative na numeric czyści wartosc_text)
- `w_limicie = None` dla qualitative (neutral)
- `round(wartosc, prec)` tylko jeśli numeric

### Step 4: Run tests — should pass

```bash
cd /Users/tbk/Desktop/lims-clean
python -m pytest tests/test_fau_below_lod.py -v --no-header
```

Expected: 5 passed.

### Step 5: Full suite — no regressions

```bash
cd /Users/tbk/Desktop/lims-clean
python -m pytest -q 2>&1 | tail -3
```

Expected: passed count +5 over baseline, 0 new failures. In particular `test_save_wyniki_*` i `test_batch_card_v2` muszą nadal być zielone (sprawdzają numeric flow).

### Step 6: Commit

```bash
git add mbr/laborant/models.py tests/test_fau_below_lod.py
git commit -m "feat(laborant): save_wyniki accepts <1/>N/≤/≥ as wartosc_text

Qualitative prefix (< > ≤ ≥) routes to wartosc_text with wartosc=NULL
and w_limicie=NULL (neutral). Used for below/above detection limit
entries like FAU <1. Clearing qualitative state by entering a plain
number wipes wartosc_text via ON CONFLICT update.

Existing numeric flow unchanged."
```

---

## Task 2: Frontend — przycisk "<1" w Fast Entry

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

> Brak automatycznych testów dla template JS. Smoke test ręczny w Step 4-5.

### Step 1: Zidentyfikuj renderer pola numerycznego

W `mbr/templates/laborant/_fast_entry_content.html` znajdź blok generujący standardowy numeric field (około linii 2558-2575). Obecny kształt:

```javascript
        fieldsHtml +=
            '<div class="ff' + (isTitr ? ' titr' : '') + (isObl ? ' computed' : '') + highlightCls + '" ' +
                (isTitr && !isReadonly ? 'data-kod="' + esc(pole.kod) + '" data-tag="' + esc(pole.tag) + '" data-sekcja="' + esc(sekcja) + '"' : '') + ' ' + calcMethodAttr + '>' +
                '<div class="status-dot"></div>' +
                '<label>' + rtHtml(pole.skrot || pole.label) + '</label>' +
                '<input type="text" inputmode="decimal"' +
                    ' data-kod="' + esc(pole.kod) + '"' +
                    ' data-sekcja="' + esc(sekcja) + '"' +
                    ' data-tag="' + esc(pole.tag) + '"' +
                    ' data-min="' + (pole.min != null ? pole.min : '') + '"' +
                    ...
```

### Step 2: Wykrywanie aktualnego stanu qualitative na render-time

Gdzie ładuje się `wyniki` i ustawia `input.value` — znajdź (grep po `wartosc_text` w tym pliku; jeśli nic — to znak że frontend do tej pory ignorował wartosc_text):

```bash
grep -n 'wartosc_text\|val\s*=\|\.value\s*=' mbr/templates/laborant/_fast_entry_content.html | head -20
```

Znajdź miejsce gdzie wartość jest stawiana w input-ie. Tam dodaj:
- Jeśli `w.wartosc_text` jest niepusty → użyj tej wartości jako `input.value`, dodaj klasę `ff-qual` do `.ff` wrapper-a
- Inaczej: zwykły flow

### Step 3: Przycisk "<1" dla `metnosc_fau`

Zmodyfikuj blok renderowania `<div class="ff">` tak, żeby dla `pole.kod === "metnosc_fau"` dodać przycisk po `</input>`:

Zmiana HTML (wstaw po linii z `<input type="text" ...>` dla tego konkretnego przypadku):

```javascript
        var fauBelowBtn = '';
        if (pole.kod === 'metnosc_fau') {
            var isBelow = (w && w.wartosc_text === '<1');
            fauBelowBtn =
                '<button type="button" class="ff-lod-btn' + (isBelow ? ' active' : '') + '"' +
                ' onclick="toggleFauBelow(this)"' +
                ' title="Poniżej limitu detekcji (<1)">&lt;1</button>';
        }
```

Wkomponuj `fauBelowBtn` do struktury:

```javascript
        fieldsHtml +=
            '<div class="ff' + (isTitr ? ' titr' : '') + ... + highlightCls + (isBelow ? ' ff-qual' : '') + '" ... >' +
                '<div class="status-dot"></div>' +
                '<label>' + rtHtml(pole.skrot || pole.label) + '</label>' +
                '<input type="text" inputmode="decimal"' +
                    ' data-kod="' + esc(pole.kod) + '"' +
                    ...
                    ' value="' + esc(displayValue) + '"' +
                    (isBelow ? ' readonly' : '') +
                    '>' +
                fauBelowBtn +
            '</div>';
```

Gdzie `displayValue = w && w.wartosc_text ? w.wartosc_text : (w && w.wartosc != null ? String(w.wartosc).replace('.', ',') : '');`.

### Step 4: `toggleFauBelow` handler

Gdzieś w script-blocku (np. obok innych `window.toggle*` handlers), dodaj:

```javascript
window.toggleFauBelow = function(btn) {
    var inp = btn.parentElement.querySelector('input[data-kod="metnosc_fau"]');
    if (!inp) return;
    var wrapper = btn.parentElement;
    var nowBelow = !btn.classList.contains('active');
    if (nowBelow) {
        inp.value = '<1';
        inp.readOnly = true;
        btn.classList.add('active');
        wrapper.classList.add('ff-qual');
    } else {
        inp.value = '';
        inp.readOnly = false;
        btn.classList.remove('active');
        wrapper.classList.remove('ff-qual');
        inp.focus();
    }
    // Trigger save — użyj istniejącego debounced save mechanism
    // Wywołaj blur lub change event który istniejący kod monitoruje
    inp.dispatchEvent(new Event('change', { bubbles: true }));
};
```

Dostosuj mechanizm zapisywania — znajdź jakiego eventu słucha istniejący autosave (grep po `addEventListener\|oninput\|onblur\|onchange` w pliku). Prawdopodobnie `blur` lub `input`. Wyzwól odpowiedni event.

### Step 5: CSS dla `.ff-qual` i `.ff-lod-btn`

Znajdź blok `<style>` w pliku (lub blok z klasami `.ff`). Dodaj:

```css
/* FAU <1 (below LOD) quick-entry */
.ff-lod-btn {
    margin-left: 4px;
    padding: 3px 8px;
    border: 1px solid var(--border, #d4cbb9);
    border-radius: 4px;
    background: var(--surface, #fff);
    color: var(--text-sec, #666);
    font-size: 11px;
    font-family: var(--mono, monospace);
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
}
.ff-lod-btn:hover { background: var(--surface-alt, #f5f1e8); }
.ff-lod-btn.active {
    background: var(--text-dim, #999);
    color: #fff;
    border-color: var(--text-dim, #999);
}
.ff.ff-qual input { background: var(--surface-alt, #f5f1e8); color: var(--text-sec, #666); }
```

### Step 6: Smoke test manualny

1. Uruchom dev server: `python -m mbr.app`
2. Zaloguj się jako laborant.
3. Otwórz EBR-a produktu zawierającego `metnosc_fau` (np. K7 lub K40GLOL).
4. W Fast Entry dla analiza_koncowa znajdź pole "b. FAU" — obok input-u powinien być przycisk `<1`.
5. Kliknij `<1` → input staje się readonly, wartość "<1", szare tło.
6. Odśwież stronę → stan powinien się odtworzyć (przycisk aktywny, input readonly).
7. Kliknij ponownie `<1` → reset, input edytowalny.
8. Wpisz liczbę (np. "3,5") i blur → zapisane jako numeric. Odśwież → widać 3,5.
9. Sprawdź w DB:
   ```bash
   sqlite3 data/batch_db.sqlite "SELECT wartosc, wartosc_text, w_limicie FROM ebr_wyniki WHERE kod_parametru='metnosc_fau' ORDER BY wynik_id DESC LIMIT 5;"
   ```
   - Po kliknięciu `<1`: wartosc=NULL, wartosc_text='<1', w_limicie=NULL
   - Po wpisaniu liczby: wartosc=3.5, wartosc_text=NULL, w_limicie=1 (lub 0)

### Step 7: Commit

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat(laborant): <1 quick-entry button for metnosc_fau in Fast Entry

Small pill button next to FAU input — click to mark sample as
below detection limit (wartosc_text='<1', wartosc=NULL). Readonly
state + greyed background while active. Clicking again or typing
a number restores numeric input flow.

Respects reload via wartosc_text roundtrip from backend."
```

---

## Task 3: Regression + prod deploy

**Files:** (brak zmian kodowych)

- [ ] **Step 1: Pełna suita**

```bash
python -m pytest -q 2>&1 | tail -3
```

Expected: baseline + 5 nowych zielonych, 0 failed.

- [ ] **Step 2: Push + prod rebuild**

```bash
git push origin main 2>&1 | tail -2
ssh tbk@192.168.100.171 "cd /opt/lims && git pull origin main 2>&1 | tail -2"
# Restart LIMS na prod (wymaga sudo)
```

Auto-deploy timer pobierze zmiany; LIMS requires restart (manualny via sudo gdy cycle nie pchnie sam).

- [ ] **Step 3: Smoke test na prod**

Weryfikacja jak w Task 2 Step 6, ale na produkcyjnym LIMS-ie.

---

## Self-review

**Spec coverage:**

- Spec sekcja "UI Fast Entry": pokryta w Task 2 Step 3-5
- Spec sekcja "Autosave / send-to-backend": pokryta w Task 1 Step 3 (parser prefix + wartosc_text save)
- Spec sekcja "Render w Fast Entry": pokryta w Task 2 Step 2
- Spec sekcja "Widoczność w innych miejscach": istniejący `get_ebr_wyniki` zwraca pełny row, więc wartosc_text propaguje do ml_export/karta/etc. automatycznie. Smoke test w Task 2 Step 6 punkt 9.

**Placeholder scan:** Brak TBD/TODO. Wszystkie steps mają pełny kod albo konkretne komendy grep do znalezienia miejsca w kodzie. Step 2 w Task 2 ("zidentyfikuj renderer") zawiera grep — to research, nie placeholder.

**Type consistency:** `wartosc_text` (TEXT) NULL-able, `wartosc` (REAL) NULL-able, `w_limicie` (INTEGER) NULL-able — spójne między Task 1 (save) a Task 2 (load).

Plan gotowy.
