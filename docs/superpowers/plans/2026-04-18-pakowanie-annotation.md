# Pakowanie IBC/Beczki annotation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Przy kończeniu szarży, jeśli `ebr_batches.pakowanie_bezposrednie` = 'IBC' albo 'Beczki', automatycznie dopisać tę krótką adnotację do `uwagi_koncowe` (append z newline, idempotentne).

**Architecture:** Rozszerzenie istniejącej funkcji `complete_ebr` w `mbr/laborant/models.py`. Po UPDATE statusu — SELECT pakowania + uwag, regex word-boundary idempotency check, conditional UPDATE uwagi_koncowe. Wszystko w tej samej transakcji. Brak zmian schematu, brak retroaktywnej migracji.

**Tech Stack:** Python 3 · sqlite3 (raw) · pytest.

---

## File Structure

### Modyfikowane
- `mbr/laborant/models.py:712-724` — funkcja `complete_ebr`: dodać blok adnotacji po UPDATE statusu.

### Utworzone
- `tests/test_pakowanie_annotation.py` — testy: 6 przypadków zgodnie ze spec-em.

### Nietykane
- Schemat DB (`pakowanie_bezposrednie` i `uwagi_koncowe` już istnieją).
- `mbr/templates/laborant/szarze_list.html` (widok ukończonych).
- `mbr/certs/*`, PDF templates, widoki szczegółów szarży.

---

## Task 1: Add pakowanie annotation to complete_ebr

**Files:**
- Modify: `mbr/laborant/models.py:712-724`
- Test: `tests/test_pakowanie_annotation.py` (nowy)

### Step 1: Write failing tests

Utwórz `tests/test_pakowanie_annotation.py`:

```python
"""Tests for auto-append of pakowanie_bezposrednie annotation to uwagi_koncowe."""
import sqlite3
import pytest

from mbr.models import init_mbr_tables
from mbr.laborant.models import complete_ebr


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _mk_ebr(db, pakowanie=None, uwagi=None) -> int:
    """Create minimal MBR + EBR with optional pakowanie_bezposrednie/uwagi_koncowe."""
    cur = db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, dt_utworzenia) "
        "VALUES ('TestProd', 1, 'active', '[]', '{}', datetime('now'))"
    )
    mbr_id = cur.lastrowid
    cur = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, "
        "pakowanie_bezposrednie, uwagi_koncowe) "
        "VALUES (?, 'B001', '1/2026', datetime('now'), 'open', ?, ?)",
        (mbr_id, pakowanie, uwagi),
    )
    db.commit()
    return cur.lastrowid


def _uwagi_after(db, ebr_id):
    return db.execute(
        "SELECT uwagi_koncowe FROM ebr_batches WHERE ebr_id=?", (ebr_id,),
    ).fetchone()["uwagi_koncowe"]


def test_ibc_empty_uwagi_becomes_ibc(db):
    """IBC + no prior uwagi → uwagi_koncowe == 'IBC'."""
    ebr_id = _mk_ebr(db, pakowanie="IBC", uwagi=None)
    complete_ebr(db, ebr_id)
    assert _uwagi_after(db, ebr_id) == "IBC"


def test_beczki_appends_with_newline(db):
    """Beczki + existing uwagi → '<existing>\\nBeczki'."""
    ebr_id = _mk_ebr(db, pakowanie="Beczki", uwagi="Lepkość 2,5")
    complete_ebr(db, ebr_id)
    assert _uwagi_after(db, ebr_id) == "Lepkość 2,5\nBeczki"


def test_double_complete_is_idempotent(db):
    """Calling complete_ebr twice does not duplicate the annotation."""
    ebr_id = _mk_ebr(db, pakowanie="Beczki", uwagi="Lepkość 2,5")
    complete_ebr(db, ebr_id)
    complete_ebr(db, ebr_id)
    assert _uwagi_after(db, ebr_id) == "Lepkość 2,5\nBeczki"


def test_existing_manual_ibc_not_duplicated(db):
    """Word-boundary + case-insensitive: manual 'ibc' in uwagi blocks auto-append."""
    ebr_id = _mk_ebr(db, pakowanie="IBC", uwagi="już wpisałem ibc ręcznie")
    complete_ebr(db, ebr_id)
    assert _uwagi_after(db, ebr_id) == "już wpisałem ibc ręcznie"


def test_null_pakowanie_leaves_uwagi_unchanged(db):
    """pakowanie_bezposrednie=NULL → no annotation."""
    ebr_id = _mk_ebr(db, pakowanie=None, uwagi="Lepkość OK")
    complete_ebr(db, ebr_id)
    assert _uwagi_after(db, ebr_id) == "Lepkość OK"


def test_non_whitelisted_pakowanie_leaves_uwagi_unchanged(db):
    """Value outside whitelist ('xyz') → no annotation."""
    ebr_id = _mk_ebr(db, pakowanie="xyz", uwagi=None)
    complete_ebr(db, ebr_id)
    # uwagi_koncowe stays None (not set to 'xyz')
    assert _uwagi_after(db, ebr_id) is None
```

### Step 2: Run — tests should fail

```bash
cd /Users/tbk/Desktop/lims-clean
python -m pytest tests/test_pakowanie_annotation.py -v --no-header
```

Expected:
- `test_ibc_empty_uwagi_becomes_ibc` → FAIL (uwagi stays None)
- `test_beczki_appends_with_newline` → FAIL (uwagi stays 'Lepkość 2,5')
- `test_double_complete_is_idempotent` → FAIL (stays 'Lepkość 2,5')
- `test_existing_manual_ibc_not_duplicated` → pass (no-op since pre-annotated)
- `test_null_pakowanie_leaves_uwagi_unchanged` → pass (no-op)
- `test_non_whitelisted_pakowanie_leaves_uwagi_unchanged` → pass (no-op)

3 failed, 3 passed.

### Step 3: Add import `re` at top of models.py

Sprawdź `mbr/laborant/models.py` — jeśli `import re` nie jest jeszcze na górze, dodaj:

```bash
grep -n '^import re\|^from re' mbr/laborant/models.py
```

Jeśli brak — dodaj `import re` między istniejącymi `import` a `from datetime import datetime` (czy gdziekolwiek pasuje alfabetycznie). Jeśli `import re` już jest — skip.

### Step 4: Extend `complete_ebr`

Otwórz `mbr/laborant/models.py`. Znajdź `def complete_ebr` (linia ~712). Aktualnie kończy się na linii ~734 (po bloku zbiorniki).

Po bloku `if zbiorniki:` (około linia 734), dodaj nowy blok:

```python
    # Auto-append pakowanie_bezposrednie annotation to uwagi_koncowe.
    # Whitelist: 'IBC' / 'Beczki'. Word-boundary regex (case-insensitive)
    # makes this idempotent against repeated calls and respects manual
    # entries the laborant may have added to uwagi earlier. See spec
    # docs/superpowers/specs/2026-04-18-pakowanie-annotation-design.md.
    row = db.execute(
        "SELECT pakowanie_bezposrednie, uwagi_koncowe FROM ebr_batches WHERE ebr_id=?",
        (ebr_id,),
    ).fetchone()
    pak = (row["pakowanie_bezposrednie"] or "").strip()
    if pak in ("IBC", "Beczki"):
        uwagi = (row["uwagi_koncowe"] or "").strip()
        word_re = re.compile(rf"\b{re.escape(pak)}\b", re.IGNORECASE)
        if not word_re.search(uwagi):
            new_uwagi = f"{uwagi}\n{pak}" if uwagi else pak
            db.execute(
                "UPDATE ebr_batches SET uwagi_koncowe=? WHERE ebr_id=?",
                (new_uwagi, ebr_id),
            )
```

### Step 5: Run tests — should pass

```bash
cd /Users/tbk/Desktop/lims-clean
python -m pytest tests/test_pakowanie_annotation.py -v --no-header
```

Expected: 6 passed.

### Step 6: Full suite — no regressions

```bash
cd /Users/tbk/Desktop/lims-clean
python -m pytest -q 2>&1 | tail -3
```

Expected: baseline (670 passed) + 6 nowych = 676 passed, 19 skipped, 0 failed.

Jeśli jakikolwiek test kompletowania szarży z innego pliku (np. `tests/test_batch_card_v2.py`) nagle failuje — przyjrzyj się konkretnym asercjom. Istniejące testy `complete_ebr` nie powinny być wrażliwe, bo używają szarż bez `pakowanie_bezposrednie`.

### Step 7: Commit

```bash
cd /Users/tbk/Desktop/lims-clean
git add mbr/laborant/models.py tests/test_pakowanie_annotation.py
git commit -m "feat(laborant): auto-append IBC/Beczki annotation to uwagi_koncowe on complete

When completing a szarża with pakowanie_bezposrednie='IBC' or 'Beczki',
the short label is appended to uwagi_koncowe (newline-separated if
existing uwagi are present). Idempotent via word-boundary regex —
repeated completes or manually-entered annotations aren't duplicated.

Applies only to newly-completed szarże; no retroactive migration."
```

---

## Task 2: Deploy + smoke test

**Files:** (brak zmian kodowych)

### Step 1: Push + prod pull + restart

```bash
cd /Users/tbk/Desktop/lims-clean
git push origin main 2>&1 | tail -2
ssh tbk@192.168.100.171 "cd /opt/lims && git pull origin main 2>&1 | tail -2"
# Manual sudo restart (hasło nie w tym pliku — controller zna)
printf '%s\n' '<sudo-password>' | ssh tbk@192.168.100.171 "sudo -S -p '' systemctl restart lims 2>&1 && systemctl is-active lims"
```

### Step 2: Smoke test on prod

1. Zaloguj się jako laborant.
2. Stwórz lub otwórz szarżę z ustawionym `pakowanie_bezposrednie='IBC'` (lub 'Beczki') — jeśli jest taki workflow w UI.
3. Zakończ szarżę (przycisk "Zakończ" albo analog).
4. Otwórz widok ukończonych (`/laborant/szarze` → Rejestr ukończonych).
5. Sprawdź że w kolumnie Uwagi dla tej szarży widać "IBC" albo "Beczki" (per `pakowanie_bezposrednie`).

Jeśli nie widać — sprawdź w DB bezpośrednio:

```bash
ssh tbk@192.168.100.171 "/opt/lims/venv/bin/python -c \"
import sqlite3
db = sqlite3.connect('/opt/lims/data/batch_db.sqlite')
db.row_factory = sqlite3.Row
rows = db.execute('SELECT ebr_id, pakowanie_bezposrednie, uwagi_koncowe FROM ebr_batches WHERE status=\\\"completed\\\" AND pakowanie_bezposrednie IS NOT NULL ORDER BY ebr_id DESC LIMIT 5').fetchall()
for r in rows: print(dict(r))
\""
```

Najnowsze szarże powinny mieć adnotację w `uwagi_koncowe`. Starsze szarże (pre-deploy) nie mają — to zgodne ze scope (tylko nowe).

---

## Self-review

**Spec coverage:**
- Spec "Algorytm" → Task 1 Step 4 (dosłowny kod z komentarzem + linkiem do spec-u).
- Spec "Separator `\n`" → Task 1 Step 4 (`f"{uwagi}\n{pak}"` vs `pak` gdy puste) + test `test_beczki_appends_with_newline`.
- Spec "Idempotencja" → Task 1 Step 4 (regex word-boundary) + test `test_double_complete_is_idempotent` + `test_existing_manual_ibc_not_duplicated`.
- Spec "Brak zmian w widoku ukończonych" → plan nie dotyka `szarze_list.html`.
- Spec "Brak retroaktywnej migracji" → plan nie tworzy migration script.
- Spec "Tylko nowe" → zmiana tylko w `complete_ebr`; istniejące dane nie są modyfikowane.
- Spec "Weryfikacja pkt 1-6" → pokryte w 6 testach Task 1 Step 1.

**Placeholder scan:** Brak TBD/TODO. Komendy konkretne z expected output. Hasło sudo oznaczone `<sudo-password>` w Task 2 Step 1 — to nie placeholder do kodu, tylko secret który trzyma controller przy deploy.

**Type consistency:** `pak` jako `str`, `uwagi` jako `str`, `word_re` jako `re.Pattern` — spójne przez cały blok. `db.execute` calls używają named placeholders.

Plan gotowy.
