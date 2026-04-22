# Stage Rename — "Analiza po [etap]" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the user-facing display labels for three K7 process stages from the ambiguous chemical-phase names (`Sulfonowanie`, `Utlenienie`, `Standaryzacja`) to unambiguous analytical-checkpoint names (`Analiza po sulfonowaniu`, `Analiza po utlenianiu`, `Analiza po standaryzacji`). Internal `kod` identifiers stay unchanged, so no Python/SQL/JS code paths break.

**Architecture:** Pure label refactor. Three code files (defaults: `mbr/models.py`, `mbr/seed_mbr.py`, `mbr/etapy/config.py`) plus one DB UPDATE applied on local dev and production. Single pytest regression guards the seed defaults.

**Tech Stack:** Python 3.12, SQLite via stdlib `sqlite3`, pytest. No new deps.

---

## File Structure

**Modified (four files):**
- `mbr/models.py:365-367` — `_etapy_defaults` tuples inside `init_mbr_tables`. Three `(kod, nazwa)` entries get new `nazwa`.
- `mbr/seed_mbr.py:23-25, 35-38` — strona-1 batch card section labels (two blocks, one per K-series variant).
- `mbr/etapy/config.py:4-47` — `ETAPY_ANALIZY` dict, three product blocks (`Chegina_K7`, `Chegina_K40GLOL`, `Chegina_K40GLO`). Updates `label` for `sulfonowanie` and `utlenienie` only. `standaryzacja` is not defined in this file.
- Live SQL: 3-row UPDATE on `etapy_analityczne` (local DB + prod DB). No code file for this — one-off SQL executed via SSH-triggered script.

**New test:**
- `tests/test_etapy_seed_labels.py` — asserts the three stages have the new `nazwa` values after `init_mbr_tables` runs on a fresh in-memory DB.

---

## Task 1: Add regression test for seed defaults

**Files:**
- Create: `tests/test_etapy_seed_labels.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_etapy_seed_labels.py`:

```python
"""Regression: K7 process-stage labels clearly mark analytical checkpoints.

After init_mbr_tables(), the three K7 stages (sulfonowanie, utlenienie,
standaryzacja) must carry 'Analiza po …' labels — the 'Sulfonowanie' /
'Utlenienie' / 'Standaryzacja' originals were ambiguous with the chemical
phases themselves and confused operators.
"""

import sqlite3
import pytest

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def test_k7_stage_nazwa_uses_analiza_po_prefix(db):
    rows = dict(
        db.execute(
            "SELECT kod, nazwa FROM etapy_analityczne "
            "WHERE kod IN ('sulfonowanie','utlenienie','standaryzacja')"
        ).fetchall()
    )
    assert rows["sulfonowanie"]  == "Analiza po sulfonowaniu"
    assert rows["utlenienie"]    == "Analiza po utlenianiu"
    assert rows["standaryzacja"] == "Analiza po standaryzacji"


def test_analiza_koncowa_label_unchanged(db):
    """4th stage (analiza_koncowa) is already clearly named — keep it."""
    row = db.execute(
        "SELECT nazwa FROM etapy_analityczne WHERE kod = 'analiza_koncowa'"
    ).fetchone()
    assert row["nazwa"] == "Analiza końcowa"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_etapy_seed_labels.py -v`

Expected: `test_k7_stage_nazwa_uses_analiza_po_prefix` FAILS with
`AssertionError: assert 'Sulfonowanie' == 'Analiza po sulfonowaniu'`.
`test_analiza_koncowa_label_unchanged` PASSES (no label change for stage 4).

- [ ] **Step 3: Do not commit yet**

This test is the driver for Task 2. Commit happens after Task 2 makes it green.

---

## Task 2: Update `mbr/models.py` seed defaults

**Files:**
- Modify: `mbr/models.py:365-367`

- [ ] **Step 1: Open the file and locate the tuple list**

Run: `grep -n '"Sulfonowanie"\|"Utlenienie"\|"Standaryzacja"' mbr/models.py`

Expected: three lines around 365-367, inside a list of `(kod, nazwa)` tuples
for `etapy_analityczne` seed defaults.

- [ ] **Step 2: Replace three tuples**

Find:

```python
        ("czwartorzedowanie", "Czwartorzędowanie"), ("sulfonowanie", "Sulfonowanie"),
        ("utlenienie", "Utlenienie"), ("rozjasnianie", "Rozjaśnianie"),
        ("standaryzacja", "Standaryzacja"), ("analiza_koncowa", "Analiza końcowa"),
```

Replace with:

```python
        ("czwartorzedowanie", "Czwartorzędowanie"), ("sulfonowanie", "Analiza po sulfonowaniu"),
        ("utlenienie", "Analiza po utlenianiu"), ("rozjasnianie", "Rozjaśnianie"),
        ("standaryzacja", "Analiza po standaryzacji"), ("analiza_koncowa", "Analiza końcowa"),
```

- [ ] **Step 3: Run the regression test — now passes**

Run: `pytest tests/test_etapy_seed_labels.py -v`
Expected: both tests PASS.

- [ ] **Step 4: Run the full suite — no new regressions**

Run: `pytest --tb=short -q 2>&1 | tail -3`
Expected: prior baseline + 2 new tests, zero failures.

- [ ] **Step 5: Commit**

```bash
git add mbr/models.py tests/test_etapy_seed_labels.py
git commit -m "feat(stages): rename K7 process stages to 'Analiza po [etap]'

Replace the ambiguous 'Sulfonowanie' / 'Utlenienie' / 'Standaryzacja'
labels (which clash with the chemistry-phase jargon and confuse operators)
with explicit 'Analiza po sulfonowaniu' / '... po utlenianiu' / '... po
standaryzacji' labels. Only the nazwa changes; kod identifiers stay the
same so every SQL/JS reference to 'standaryzacja' keeps working.

First of 3 code changes + 1 live DB update. Covers init_mbr_tables seed
defaults (applied on every fresh DB init). Subsequent tasks cover
batch-card sections and process-stage config, then the live prod DB
UPDATE."
```

---

## Task 3: Update `mbr/seed_mbr.py` batch-card sections

**Files:**
- Modify: `mbr/seed_mbr.py:23-25, 35-38`

- [ ] **Step 1: Open the file and view lines 18-45**

Use Read on `mbr/seed_mbr.py` offset=15, limit=30. Confirm two list-of-dict blocks
defining batch-card section labels, one per K-series variant.

- [ ] **Step 2: Replace the three nazwa strings in each block**

Find the first block (around line 23-25):

```python
    {"nr": 4, "nazwa": "Sulfonowanie",         "read_only": True},
    {"nr": 5, "nazwa": "Utlenienie",           "read_only": True},
    {"nr": 6, "nazwa": "Standaryzacja",        "read_only": False, "sekcja_lab": "standaryzacja"},
```

Replace with:

```python
    {"nr": 4, "nazwa": "Analiza po sulfonowaniu",  "read_only": True},
    {"nr": 5, "nazwa": "Analiza po utlenianiu",    "read_only": True},
    {"nr": 6, "nazwa": "Analiza po standaryzacji", "read_only": False, "sekcja_lab": "standaryzacja"},
```

Then find the second block (around line 35-38):

```python
    {"nr": 4, "nazwa": "Sulfonowanie",         "read_only": True},
    {"nr": 5, "nazwa": "Utlenienie",           "read_only": True},
    {"nr": 6, ... (varies) ...},
    {"nr": 7, "nazwa": "Standaryzacja",        "read_only": False, "sekcja_lab": "standaryzacja"},
```

Apply the same substitution for `"Sulfonowanie"` → `"Analiza po sulfonowaniu"`,
`"Utlenienie"` → `"Analiza po utlenianiu"`, `"Standaryzacja"` →
`"Analiza po standaryzacji"`. Column alignment of the dict literals is
preserved (spaces may need adjustment so the `"read_only"` key lines up).

- [ ] **Step 3: Syntax sanity check**

Run: `python3 -c "from mbr import seed_mbr"`
Expected: no output (module imports cleanly).

- [ ] **Step 4: Full suite**

Run: `pytest --tb=short -q 2>&1 | tail -3`
Expected: all pass, unchanged count from Task 2.

- [ ] **Step 5: Commit**

```bash
git add mbr/seed_mbr.py
git commit -m "feat(stages): apply 'Analiza po [etap]' labels in batch-card seeds

Second of 3 code changes. Strona-1 section labels now match the new
stage naming used in etapy_analityczne defaults."
```

---

## Task 4: Update `mbr/etapy/config.py` product labels

**Files:**
- Modify: `mbr/etapy/config.py:4-47`

- [ ] **Step 1: Review current contents**

Use Read on `mbr/etapy/config.py` offset=1, limit=60.

Three product blocks (`Chegina_K7`, `Chegina_K40GLOL`, `Chegina_K40GLO`)
each reference `"sulfonowanie"` and `"utlenienie"` with `"label":
"Sulfonowanie"` / `"Utlenienie"`.

- [ ] **Step 2: Update the six label occurrences**

For `Chegina_K7` (lines 4-10):

Find:
```python
        "sulfonowanie":      {"label": "Sulfonowanie",      "korekty": ["Na2SO3"]},
        "utlenienie":        {"label": "Utlenienie",        "korekty": ["Perhydrol"]},
```

Replace with:
```python
        "sulfonowanie":      {"label": "Analiza po sulfonowaniu", "korekty": ["Na2SO3"]},
        "utlenienie":        {"label": "Analiza po utlenianiu",   "korekty": ["Perhydrol"]},
```

For `Chegina_K40GLOL` (lines 11-18):

Find:
```python
        "sulfonowanie":      {"label": "Sulfonowanie",      "korekty": ["Na2SO3"]},
        "utlenienie":        {"label": "Utlenienie",        "korekty": ["Kw. cytrynowy", "Perhydrol"]},
```

Replace with:
```python
        "sulfonowanie":      {"label": "Analiza po sulfonowaniu", "korekty": ["Na2SO3"]},
        "utlenienie":        {"label": "Analiza po utlenianiu",   "korekty": ["Kw. cytrynowy", "Perhydrol"]},
```

For `Chegina_K40GLO` (lines 19-47): two occurrences, one line and one
multi-line dict.

Find (around line 38):
```python
        "sulfonowanie": {"label": "Sulfonowanie", "korekty": ["Na2SO3"]},
```

Replace with:
```python
        "sulfonowanie": {"label": "Analiza po sulfonowaniu", "korekty": ["Na2SO3"]},
```

Find (around line 39-41):
```python
        "utlenienie": {
            "label": "Utlenienie",
```

Replace with:
```python
        "utlenienie": {
            "label": "Analiza po utlenianiu",
```

- [ ] **Step 3: Syntax sanity check**

Run: `python3 -c "from mbr.etapy.config import ETAPY_ANALIZY; assert ETAPY_ANALIZY['Chegina_K7']['sulfonowanie']['label'] == 'Analiza po sulfonowaniu'"`

Expected: no output (assertion holds).

- [ ] **Step 4: Full suite**

Run: `pytest --tb=short -q 2>&1 | tail -3`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add mbr/etapy/config.py
git commit -m "feat(stages): update Chegina product configs with new labels

Third of 3 code changes. ETAPY_ANALIZY labels for K7/K40GLOL/K40GLO
now say 'Analiza po sulfonowaniu' / 'Analiza po utlenianiu'. The file
does not reference standaryzacja (that stage is defined only through
etapy_analityczne + produkt_pipeline)."
```

---

## Task 5: Apply live DB UPDATE + push + deploy

**Files:**
- No code changes. SQL update on two databases (local + prod) plus a git push.

- [ ] **Step 1: Update local DB**

Run:

```bash
sqlite3 data/batch_db.sqlite "UPDATE etapy_analityczne SET nazwa = 'Analiza po sulfonowaniu'  WHERE kod = 'sulfonowanie';
UPDATE etapy_analityczne SET nazwa = 'Analiza po utlenianiu'    WHERE kod = 'utlenienie';
UPDATE etapy_analityczne SET nazwa = 'Analiza po standaryzacji' WHERE kod = 'standaryzacja';
SELECT kod, nazwa FROM etapy_analityczne WHERE kod IN ('sulfonowanie','utlenienie','standaryzacja') ORDER BY kod;"
```

Expected output (order may differ):

```
sulfonowanie|Analiza po sulfonowaniu
standaryzacja|Analiza po standaryzacji
utlenienie|Analiza po utlenianiu
```

- [ ] **Step 2: Push main**

Run: `git push origin main 2>&1 | tail -3`
Expected: push succeeds, no conflicts.

- [ ] **Step 3: Trigger deploy on prod + apply SQL UPDATE there too**

Auto-deploy syncs the code. The live prod DB still has the old labels
unless we UPDATE it (the seed defaults only fire on fresh installs). Do
both in one SSH call:

```bash
expect -c '
set timeout 90
log_user 1
spawn ssh -o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no -o NumberOfPasswordPrompts=1 tbk@192.168.1.240 "echo z.S17DcxSy33 | sudo -S systemctl start auto-deploy.service 2>&1; sleep 10; echo ===DB_UPDATE===; cd /opt/lims && sqlite3 data/batch_db.sqlite \"UPDATE etapy_analityczne SET nazwa=\x27Analiza po sulfonowaniu\x27 WHERE kod=\x27sulfonowanie\x27; UPDATE etapy_analityczne SET nazwa=\x27Analiza po utlenianiu\x27 WHERE kod=\x27utlenienie\x27; UPDATE etapy_analityczne SET nazwa=\x27Analiza po standaryzacji\x27 WHERE kod=\x27standaryzacja\x27; SELECT kod,nazwa FROM etapy_analityczne WHERE kod IN (\x27sulfonowanie\x27,\x27utlenienie\x27,\x27standaryzacja\x27) ORDER BY kod;\"; echo ===HEAD===; git log --oneline -1; echo ===LIMS===; systemctl is-active lims"
expect {
  -re "password:" { send "z.S17DcxSy33\r"; exp_continue }
  eof
}
' 2>&1 | tail -15
```

Expected:
- three rows with new labels (same order as local)
- HEAD matches local main after push
- `lims` reports `active`

- [ ] **Step 4: Operator smoke test**

Open a K7 batch hero on prod. Stage section headers should read
`Analiza po sulfonowaniu`, `Analiza po utlenianiu`, `Analiza po
standaryzacji`. Also open a fresh batch card (strona 1) — section
labels should match.

---

## Spec coverage audit

| Spec requirement                                                    | Task |
|---------------------------------------------------------------------|-----:|
| DB UPDATE for three rows in `etapy_analityczne`                      | 5    |
| `mbr/models.py:365-367` defaults rewritten                          | 2    |
| `mbr/seed_mbr.py:23-25, 35-38` section labels rewritten             | 3    |
| `mbr/etapy/config.py` K7 + K40GLOL + K40GLO labels rewritten         | 4    |
| `analiza_koncowa` unchanged                                          | 1 (explicit test) |
| `kod` identifiers unchanged                                          | N/A (no change anywhere) |
| Regression test covers new seed defaults                             | 1 + 2 |
| Operator smoke confirms UI reads new labels                          | 5    |
