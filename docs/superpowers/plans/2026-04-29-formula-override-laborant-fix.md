# Formula Override Laborant Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Naprawić propagację override formuły dla parametru SA do laboranta + odblokować ręczną edycję pola obliczeniowego z reactive recompute przy zmianie dependencji. Główny use case: Cheminox_K SA = `sm` (bez NaCl).

**Architecture:** Endpoint `PUT /api/parametry/<id>/formula-override` przepiszemy żeby zapisywał do `produkt_etap_limity.formula` (pipeline) zamiast `parametry_etapy.formula` (legacy) — tabela którą czyta `resolve_limity` → `build_pipeline_context` → snapshot `mbr_templates.parametry_lab` → laborant calculator. `usage-impact.mbr_products[]` też przepisany na `produkt_etap_limity` (filtruje ghost products). Frontend laboranta: usuwamy hard readonly, usuwamy initial recompute (manual edit survive F5), naprawiamy bias editor żeby zachowywał override.

**Tech Stack:** Flask + SQLite (raw sqlite3); Jinja2 + vanilla JS; pytest TDD na backend; manual browser verification dla frontend.

**Spec:** `docs/superpowers/specs/2026-04-29-formula-override-laborant-fix-design.md` (przeczytaj przed startem).

**Worktree:** `.worktrees/formula-override` (kontynuacja istniejącego brancha — backend endpoint + frontend rejestru już są tam zaimplementowane na pre-bug wersji).

---

## File Structure

**Backend (Phase A):**
- Modify: `mbr/parametry/routes.py:185-247` — `api_parametry_usage_impact` (zmiana źródła `mbr_products[]` + `formula_override` na `produkt_etap_limity`)
- Modify: `mbr/parametry/routes.py:486-562` — `api_parametry_formula_override` (zmiana lookup + UPDATE z `parametry_etapy` na `produkt_etap_limity`)
- Modify: `tests/test_parametry_formula_override.py` (8 testów — adaptacja fixture)
- Add: nowy test `test_override_propagates_to_parametry_lab` w tym samym pliku
- Modify: `tests/test_parametry_usage_impact_lists.py` (2 testy — adaptacja fixture)
- Create: `scripts/migrate_formula_override_to_pel.py` — jednorazowa migracja istniejących wpisów

**Frontend (Phase B):**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`:
  - linia 2738: usunąć `(isObl && !isReadonly ? ' readonly' : '')`
  - linia 4517: usunąć `computedInput.readOnly = true;`
  - linia 4482: usunąć `recomputeField(computedInput);` (initial recompute w setupComputedFields)
  - linie 4263-4264 i 4286-4289: bias editor preserving override (substytucja regex zamiast hardcoded)

---

## Phase A — Backend + Migration (TDD)

### Task A1: Adaptacja `tests/test_parametry_formula_override.py` fixture do `produkt_etap_limity`

**Files:**
- Modify: `tests/test_parametry_formula_override.py` (fixture `_seed`, asercje DB)

- [ ] **Step 1: Otwórz test, zlokalizuj fixture `_seed`**

```bash
sed -n '/def _seed/,/db\.commit()/p' tests/test_parametry_formula_override.py
```

Stara fixture seed-uje `parametry_etapy`. Adaptacja do `produkt_etap_limity` wymaga seed-u:
- `etapy_analityczne` (etap_id 10 = analiza_koncowa, 11 = sulfonowanie)
- `etap_parametry` (catalog binding parametr↔etap)
- `produkt_etap_limity` (per-product binding)

- [ ] **Step 2: Zastąp `_seed` nową implementacją**

```python
def _seed(db):
    db.execute("DELETE FROM parametry_analityczne")
    db.execute(
        "INSERT INTO parametry_analityczne (id, kod, label, typ, formula) "
        "VALUES (1, 'sa', 'Substancja aktywna', 'obliczeniowy', 'sm - nacl - sa_bias')"
    )
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('Cheminox_K', 'Cheminox K')")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('Other', 'Other')")
    db.execute(
        "INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
        "VALUES (10, 'analiza_koncowa', 'Analiza końcowa', 'jednorazowy')"
    )
    db.execute(
        "INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
        "VALUES (11, 'sulfonowanie', 'Sulfonowanie', 'cykliczny')"
    )
    db.execute(
        "INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (10, 1, 0)"
    )
    db.execute(
        "INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (11, 1, 0)"
    )
    # Cheminox_K has SA in analiza_koncowa with sa_bias=0.6 (no formula override yet)
    db.execute(
        "INSERT INTO produkt_etap_limity (id, produkt, etap_id, parametr_id, kolejnosc, sa_bias) "
        "VALUES (100, 'Cheminox_K', 10, 1, 0, 0.6)"
    )
    # Other product: SA in sulfonowanie kontekst (different etap)
    db.execute(
        "INSERT INTO produkt_etap_limity (id, produkt, etap_id, parametr_id, kolejnosc) "
        "VALUES (101, 'Other', 11, 1, 0)"
    )
    db.commit()
```

- [ ] **Step 3: Zmień asercje DB w testach z `parametry_etapy WHERE id=10` na `produkt_etap_limity WHERE id=100`**

Wszystkie miejsca:
```python
# Stare:
row = db.execute("SELECT formula FROM parametry_etapy WHERE id=10").fetchone()
# Nowe:
row = db.execute("SELECT formula FROM produkt_etap_limity WHERE id=100").fetchone()
```

Test `test_kontekst_param_overrides_default` ma asercję na id=11 → zmień na id=101 + tabela `produkt_etap_limity`.

- [ ] **Step 4: Sprawdź że testy się wywracają (na nieaktualnym endpoincie)**

```bash
pytest tests/test_parametry_formula_override.py -v
```

Expected: 8 failures — endpoint nadal pisze do `parametry_etapy`, fixture seed-uje `produkt_etap_limity`, więc UPDATE/SELECT się rozjeżdżają.

- [ ] **Step 5: Commit (red-stage)**

```bash
git add tests/test_parametry_formula_override.py
git commit -m "test(parametry): adapt formula-override fixture to produkt_etap_limity"
```

---

### Task A2: Endpoint `api_parametry_formula_override` — zmiana SQL na `produkt_etap_limity`

**Files:**
- Modify: `mbr/parametry/routes.py:486-562`

- [ ] **Step 1: Zlokalizuj endpoint**

```bash
sed -n '486,562p' mbr/parametry/routes.py
```

- [ ] **Step 2: Zmień SELECT lookup z `parametry_etapy` na `produkt_etap_limity` + `etapy_analityczne` JOIN**

W `mbr/parametry/routes.py`, w funkcji `api_parametry_formula_override`, zastąp blok:

```python
        row = db.execute(
            "SELECT pe.id, pe.formula AS formula_old, pa.kod "
            "FROM parametry_etapy pe "
            "JOIN parametry_analityczne pa ON pa.id = pe.parametr_id "
            "WHERE pe.parametr_id=? AND pe.produkt=? AND pe.kontekst=?",
            (param_id, produkt, kontekst),
        ).fetchone()
        if not row:
            return jsonify({"error": "Binding not found"}), 404
```

Na:

```python
        row = db.execute(
            "SELECT pel.id, pel.formula AS formula_old, pa.kod "
            "FROM produkt_etap_limity pel "
            "JOIN parametry_analityczne pa ON pa.id = pel.parametr_id "
            "JOIN etapy_analityczne ea ON ea.id = pel.etap_id "
            "WHERE pel.parametr_id=? AND pel.produkt=? AND ea.kod=?",
            (param_id, produkt, kontekst),
        ).fetchone()
        if not row:
            return jsonify({"error": "Binding not found"}), 404
```

- [ ] **Step 3: Zmień UPDATE z `parametry_etapy` na `produkt_etap_limity`**

W tej samej funkcji zastąp:

```python
        db.execute(
            "UPDATE parametry_etapy SET formula=? WHERE id=?",
            (new_formula, row["id"]),
        )
```

Na:

```python
        db.execute(
            "UPDATE produkt_etap_limity SET formula=? WHERE id=?",
            (new_formula, row["id"]),
        )
```

- [ ] **Step 4: Zaktualizuj docstring funkcji**

Stary docstring zaczyna się od `"""Set or clear per-binding formula override in parametry_etapy.formula.`. Zmień na:

```python
    """Set or clear per-binding formula override in produkt_etap_limity.formula.

    Body: {produkt: <str>, formula: <str|null>, kontekst: <str|null>}
    - kontekst defaults to 'analiza_koncowa' (mapped to etapy_analityczne.kod)
    - formula='' or whitespace-only → treated as null (clear override)
    - 404 if no binding exists for (parametr_id, produkt, etap)

    On success: rebuilds mbr_templates.parametry_lab snapshot for the produkt
    + emits parametr.updated audit with action='formula_override_set'/'formula_override_cleared'.
    """
```

- [ ] **Step 5: Run testy żeby zweryfikować że pass-ują**

```bash
pytest tests/test_parametry_formula_override.py -v
```

Expected: 8 passing.

- [ ] **Step 6: Run regression suite**

```bash
pytest tests/test_parametry_audit_extended.py tests/test_parametry_create_audit.py tests/test_parametry_registry_audit.py tests/test_parametry_usage_impact.py tests/test_sa_bias_per_product.py -q
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add mbr/parametry/routes.py
git commit -m "fix(parametry): formula-override endpoint writes to produkt_etap_limity (pipeline)"
```

---

### Task A3: Test integracyjny `test_override_propagates_to_parametry_lab`

**Files:**
- Modify: `tests/test_parametry_formula_override.py` (dodanie nowego testu)

- [ ] **Step 1: Dodaj test integracyjny na końcu pliku**

W `tests/test_parametry_formula_override.py`, na końcu pliku (po istniejącym `test_admin_only`), dodaj:

```python
def test_override_propagates_to_parametry_lab(monkeypatch, db):
    """End-to-end: PUT formula → rebuild widoczny w mbr_templates.parametry_lab.

    Łapie regresję write-vs-read mismatch (endpoint pisze do tabeli A,
    laborant czyta z tabeli B → override nie dociera).
    """
    _seed(db)
    db.execute(
        "INSERT INTO mbr_templates (produkt, status, parametry_lab) "
        "VALUES ('Cheminox_K', 'active', '{}')"
    )
    db.execute(
        "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Cheminox_K', 10, 1)"
    )
    db.commit()
    client = _admin_client(monkeypatch, db)

    rv = client.put(
        "/api/parametry/1/formula-override",
        json={"produkt": "Cheminox_K", "formula": "sm"},
    )
    assert rv.status_code == 200, rv.get_json()

    plab_json = db.execute(
        "SELECT parametry_lab FROM mbr_templates WHERE produkt='Cheminox_K'"
    ).fetchone()[0]
    plab = json.loads(plab_json)
    assert "analiza_koncowa" in plab, f"snapshot missing analiza_koncowa: {plab}"
    sa_pole = next(p for p in plab["analiza_koncowa"]["pola"] if p["kod"] == "sa")
    assert sa_pole["formula"] == "sm", f"expected formula='sm', got {sa_pole}"
```

- [ ] **Step 2: Run nowy test**

```bash
pytest tests/test_parametry_formula_override.py::test_override_propagates_to_parametry_lab -v
```

Expected: PASS (po Task A2 endpoint pisze do `produkt_etap_limity`, build_parametry_lab czyta stamtąd przez resolve_limity).

- [ ] **Step 3: Commit**

```bash
git add tests/test_parametry_formula_override.py
git commit -m "test(parametry): integration test for formula-override → parametry_lab snapshot"
```

---

### Task A4: `usage-impact` — `formula_override` z `produkt_etap_limity`

**Files:**
- Modify: `mbr/parametry/routes.py:228-234` — `ovr_rows` query
- Modify: `tests/test_parametry_usage_impact_lists.py` — adaptacja `test_usage_impact_includes_formula_override`

- [ ] **Step 1: Zaadaptuj fixture w `test_usage_impact_includes_formula_override`**

Zlokalizuj test:

```bash
grep -n "test_usage_impact_includes_formula_override" tests/test_parametry_usage_impact_lists.py
```

Zastąp fixture-bagaż w teście (insertu do `parametry_etapy`) na `produkt_etap_limity`. Konkretnie:

Stare:
```python
db.execute(
    "INSERT INTO parametry_etapy (parametr_id, produkt, kontekst, kolejnosc, formula) "
    "VALUES (1, 'Cheminox_K', 'analiza_koncowa', 0, 'sm')"
)
db.execute(
    "INSERT INTO parametry_etapy (parametr_id, produkt, kontekst, kolejnosc) "
    "VALUES (1, 'Chegina_K7', 'analiza_koncowa', 0)"
)
```

Nowe:
```python
db.execute(
    "INSERT INTO etapy_analityczne (id, kod, nazwa) "
    "VALUES (10, 'analiza_koncowa', 'AK')"
)
db.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (10, 1, 0)")
db.execute(
    "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, kolejnosc, formula) "
    "VALUES ('Cheminox_K', 10, 1, 0, 'sm')"
)
db.execute(
    "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, kolejnosc) "
    "VALUES ('Chegina_K7', 10, 1, 0)"
)
```

- [ ] **Step 2: Run test żeby zweryfikować że failuje (z powodu starego SQL w endpoint)**

```bash
pytest tests/test_parametry_usage_impact_lists.py::test_usage_impact_includes_formula_override -v
```

Expected: FAIL — `formula_override` jest `None` zamiast `"sm"` (endpoint nadal czyta `parametry_etapy.formula`).

- [ ] **Step 3: Zmień `ovr_rows` query w endpoint**

W `mbr/parametry/routes.py`, w `api_parametry_usage_impact`, zastąp:

```python
        ovr_rows = db.execute(
            """SELECT produkt, formula
               FROM parametry_etapy
               WHERE parametr_id = ? AND kontekst = 'analiza_koncowa'""",
            (param_id,),
        ).fetchall()
```

Na:

```python
        ovr_rows = db.execute(
            """SELECT pel.produkt, pel.formula
               FROM produkt_etap_limity pel
               JOIN etapy_analityczne ea ON ea.id = pel.etap_id
               WHERE pel.parametr_id = ? AND ea.kod = 'analiza_koncowa'""",
            (param_id,),
        ).fetchall()
```

- [ ] **Step 4: Run test żeby zweryfikować pass**

```bash
pytest tests/test_parametry_usage_impact_lists.py::test_usage_impact_includes_formula_override -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/parametry/routes.py tests/test_parametry_usage_impact_lists.py
git commit -m "fix(parametry): usage-impact reads formula_override from produkt_etap_limity"
```

---

### Task A5: `usage-impact` — `mbr_products[]` z `produkt_etap_limity` (filtruje ghost products)

**Files:**
- Modify: `mbr/parametry/routes.py:215-225` — `mbr_rows` query
- Modify: `tests/test_parametry_usage_impact_lists.py` — adaptacja `test_usage_impact_includes_mbr_products_list_with_stages`

- [ ] **Step 1: Zlokalizuj istniejący test `test_usage_impact_includes_mbr_products_list_with_stages`**

```bash
grep -n "test_usage_impact_includes_mbr_products_list_with_stages\|PROD_C\|PROD_A\|PROD_B" tests/test_parametry_usage_impact_lists.py | head -20
```

- [ ] **Step 2: Zaadaptuj fixture żeby seed-ował `produkt_etap_limity`**

Test seed-uje produkty `PROD_A`, `PROD_B`, `PROD_C` w `parametry_etapy`. Po zmianie źródła `mbr_products[]` na `produkt_etap_limity`, fixture musi też wstawić te produkty do `produkt_etap_limity`.

Dla każdej `parametry_etapy` insertu w fixture, dodaj odpowiadający insert do `produkt_etap_limity` (oraz `etapy_analityczne` + `etap_parametry` jeśli brakuje). Konkretnie struktura nowego seed-u:

```python
# Etapy + catalog binding
db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa) VALUES (10, 'analiza_koncowa', 'AK')")
db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa) VALUES (11, 'sulfonowanie', 'Sulf')")
db.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (10, 1, 0)")
db.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (11, 1, 0)")

# Per-product bindings (produkt_etap_limity = source of truth dla mbr_products[])
db.execute("INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, kolejnosc) VALUES ('PROD_A', 10, 1, 0)")
db.execute("INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, kolejnosc) VALUES ('PROD_B', 10, 1, 0)")
db.execute("INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, kolejnosc) VALUES ('PROD_B', 11, 1, 0)")
db.execute("INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, kolejnosc) VALUES ('PROD_C', 10, 1, 0)")
```

(Konkretne id parametru i etapy dopasuj do tego co już jest w fixture.)

- [ ] **Step 3: Run test żeby zweryfikować failure (endpoint nadal czyta parametry_etapy → wynik nie zgadza się z fixture)**

```bash
pytest tests/test_parametry_usage_impact_lists.py::test_usage_impact_includes_mbr_products_list_with_stages -v
```

Expected: PASS lub FAIL zależnie czy stary SQL nadal trafia w fixture.

- [ ] **Step 4: Zmień `mbr_rows` query w endpoint**

W `mbr/parametry/routes.py`, w `api_parametry_usage_impact`, zastąp:

```python
        mbr_rows = db.execute(
            """SELECT pe.produkt AS key, pe.kontekst AS stage
               FROM parametry_etapy pe
               WHERE pe.parametr_id = ?
               ORDER BY pe.produkt, pe.kontekst""",
            (param_id,),
        ).fetchall()
```

Na:

```python
        mbr_rows = db.execute(
            """SELECT pel.produkt AS key, ea.kod AS stage
               FROM produkt_etap_limity pel
               JOIN etapy_analityczne ea ON ea.id = pel.etap_id
               WHERE pel.parametr_id = ?
               ORDER BY pel.produkt, ea.kod""",
            (param_id,),
        ).fetchall()
```

Zaktualizuj też docstring (linia 192):

```python
    - mbr_products: distinct produkt rows from produkt_etap_limity with stages array
    - mbr_bindings_count: total produkt_etap_limity rows (= produkt × stages combinations)
```

- [ ] **Step 5: Run testy**

```bash
pytest tests/test_parametry_usage_impact_lists.py -v
```

Expected: all passing (4 testy: oba istniejące + nowy formula_override).

- [ ] **Step 6: Run regression suite**

```bash
pytest tests/test_parametry_usage_impact.py tests/test_parametry_usage_impact_lists.py tests/test_parametry_formula_override.py -q
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add mbr/parametry/routes.py tests/test_parametry_usage_impact_lists.py
git commit -m "fix(parametry): usage-impact mbr_products list reads from produkt_etap_limity"
```

---

### Task A6: Migration script `migrate_formula_override_to_pel.py`

**Files:**
- Create: `scripts/migrate_formula_override_to_pel.py`

- [ ] **Step 1: Stwórz skrypt migracji**

Stwórz `scripts/migrate_formula_override_to_pel.py`:

```python
"""One-shot migration: parametry_etapy.formula → produkt_etap_limity.formula.

Idempotent. Skips rows where pel.formula already populated (NOT NULL).
Does NOT clear parametry_etapy.formula (legacy column, untouched).

Usage:
    python scripts/migrate_formula_override_to_pel.py [path/to/db.sqlite]

Default DB path: data/batch_db.sqlite
"""

import json
import sqlite3
import sys
from pathlib import Path

# Repo root assumed parent of this script's parent dir
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mbr.parametry.registry import build_parametry_lab

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "data/batch_db.sqlite"
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")

rows = conn.execute("""
    SELECT pe.parametr_id, pe.produkt, pe.kontekst, pe.formula, pa.kod
    FROM parametry_etapy pe
    JOIN parametry_analityczne pa ON pa.id = pe.parametr_id
    WHERE pe.formula IS NOT NULL AND pe.formula != ''
""").fetchall()

migrated = 0
skipped = 0
products_to_rebuild = set()

for r in rows:
    ea = conn.execute(
        "SELECT id FROM etapy_analityczne WHERE kod = ?", (r["kontekst"],)
    ).fetchone()
    if not ea:
        print(f"WARN: no etap '{r['kontekst']}' for {r['kod']}/{r['produkt']}, skipping")
        skipped += 1
        continue

    pel = conn.execute(
        "SELECT id, formula FROM produkt_etap_limity "
        "WHERE produkt=? AND etap_id=? AND parametr_id=?",
        (r["produkt"], ea["id"], r["parametr_id"]),
    ).fetchone()
    if not pel:
        print(f"WARN: no pel binding for {r['kod']}/{r['produkt']}/{r['kontekst']}, skipping")
        skipped += 1
        continue

    if pel["formula"] is not None:
        print(f"SKIP: pel already has formula='{pel['formula']}' for {r['kod']}/{r['produkt']}")
        skipped += 1
        continue

    conn.execute(
        "UPDATE produkt_etap_limity SET formula = ? WHERE id = ?",
        (r["formula"], pel["id"]),
    )
    print(f"OK: {r['kod']}/{r['produkt']}/{r['kontekst']} → formula='{r['formula']}'")
    products_to_rebuild.add(r["produkt"])
    migrated += 1

# Rebuild mbr_templates.parametry_lab snapshot for affected products
for produkt in products_to_rebuild:
    plab = build_parametry_lab(conn, produkt)
    cur = conn.execute(
        "UPDATE mbr_templates SET parametry_lab=? WHERE produkt=? AND status='active'",
        (json.dumps(plab, ensure_ascii=False), produkt),
    )
    if cur.rowcount == 0:
        print(f"WARN: no active mbr_template for {produkt} — snapshot not rebuilt")
    else:
        print(f"REBUILT: parametry_lab for {produkt} ({cur.rowcount} row)")

conn.commit()
print(f"\nDone. Migrated: {migrated}, skipped: {skipped}, rebuilt snapshots: {len(products_to_rebuild)}")
```

- [ ] **Step 2: Backup DB przed migracją**

```bash
cp data/batch_db.sqlite data/batch_db.sqlite.bak-pre-formula-override-migration
```

- [ ] **Step 3: Odpal migrację**

```bash
python scripts/migrate_formula_override_to_pel.py
```

Expected output (Cheminox_K już ma override):
```
OK: sa/Cheminox_K/analiza_koncowa → formula='sm'
REBUILT: parametry_lab for Cheminox_K (1 row)

Done. Migrated: 1, skipped: 0, rebuilt snapshots: 1
```

- [ ] **Step 4: Weryfikacja w DB**

```bash
sqlite3 data/batch_db.sqlite "SELECT pa.kod, pel.produkt, pel.formula FROM produkt_etap_limity pel JOIN parametry_analityczne pa ON pa.id=pel.parametr_id WHERE pel.formula IS NOT NULL;"
```

Expected: `sa|Cheminox_K|sm`.

```bash
sqlite3 data/batch_db.sqlite "SELECT json_extract(parametry_lab, '\$.analiza_koncowa.pola') FROM mbr_templates WHERE produkt='Cheminox_K' AND status='active';" | python3 -c "import json,sys; arr=json.loads(sys.stdin.read()); print([p for p in arr if p['kod']=='sa'])"
```

Expected: `[{'kod': 'sa', ..., 'formula': 'sm', ...}]`.

- [ ] **Step 5: Idempotency check (drugi run = no-op)**

```bash
python scripts/migrate_formula_override_to_pel.py
```

Expected output:
```
SKIP: pel already has formula='sm' for sa/Cheminox_K
Done. Migrated: 0, skipped: 1, rebuilt snapshots: 0
```

- [ ] **Step 6: Commit**

```bash
git add scripts/migrate_formula_override_to_pel.py
git commit -m "feat(scripts): migrate formula overrides parametry_etapy → produkt_etap_limity"
```

---

## Phase B — Frontend Laboranta (Manual Verify)

> **Phase B note:** Manual browser verification — odpal dev server (`python -m mbr.app`), otwórz `/laborant/ebr/<id>`, hard reload (Cmd+Shift+R) po każdym diffie żeby cache-bust calculator.js.

### Task B1: Diff 1 — usuń wymuszony readonly z linii 2738

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html:2737-2738`

- [ ] **Step 1: Zlokalizuj linie**

```bash
sed -n '2735,2740p' mbr/templates/laborant/_fast_entry_content.html
```

Powinieneś zobaczyć:
```
                    ' value="' + val + '"' +
                    ' class="' + inputClass.trim() + '"' +
                    (isReadonly ? ' readonly' : '') +
                    (isObl && !isReadonly ? ' readonly' : '') +
                    ' placeholder="—"' +
```

- [ ] **Step 2: Usuń wymuszony readonly dla obliczeniowy**

W `mbr/templates/laborant/_fast_entry_content.html`, znajdź:

```js
                    (isReadonly ? ' readonly' : '') +
                    (isObl && !isReadonly ? ' readonly' : '') +
                    ' placeholder="—"' +
```

Zastąp na:

```js
                    (isReadonly ? ' readonly' : '') +
                    ' placeholder="—"' +
```

- [ ] **Step 3: Verify w przeglądarce**

- Otwórz `http://localhost:5001/laborant/ebr/<jakiś_id_szarży_Cheminox_K>` (jeśli brak — szybko stwórz przez technologa lub użyj Chegina_K7)
- Hard reload (Cmd+Shift+R)
- Pole SA powinno być editowalne — kliknięcie focusuje, kursor pojawia się, można pisać

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "fix(laborant): obliczeniowy field editable (no forced readonly)"
```

---

### Task B2: Diff 2 — usuń `readOnly = true` w `recomputeField`

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html:4517`

- [ ] **Step 1: Zlokalizuj linię**

```bash
sed -n '4513,4520p' mbr/templates/laborant/_fast_entry_content.html
```

Powinieneś zobaczyć:
```js
                var prec = parseInt(computedInput.dataset.precision || '2', 10);
                var newVal = result.toFixed(prec).replace('.', ',');
                computedInput.readOnly = true;
                if (computedInput.value !== newVal) {
```

- [ ] **Step 2: Usuń `computedInput.readOnly = true;`**

W `mbr/templates/laborant/_fast_entry_content.html`, znajdź:

```js
                var newVal = result.toFixed(prec).replace('.', ',');
                computedInput.readOnly = true;
                if (computedInput.value !== newVal) {
```

Zastąp na:

```js
                var newVal = result.toFixed(prec).replace('.', ',');
                if (computedInput.value !== newVal) {
```

- [ ] **Step 3: Verify w przeglądarce**

- Hard reload
- Wpisz SM = 35,5 dla Cheminox_K → SA pojawia się
- Zmień SA ręcznie na 36,0 → blur → pole pozostaje 36,0 (nie wraca do `readonly`)

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "fix(laborant): recomputeField no longer locks field to readonly"
```

---

### Task B3: Diff 3 — usuń initial `recomputeField` w `setupComputedFields`

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html:4482`

- [ ] **Step 1: Zlokalizuj linię**

```bash
sed -n '4478,4485p' mbr/templates/laborant/_fast_entry_content.html
```

Powinieneś zobaczyć:
```js
                depInput.setAttribute('data-computed-listener', '1');
                depInput.addEventListener('input', handler);
            }
        });
        recomputeField(computedInput);
    });
}
```

- [ ] **Step 2: Usuń linię `recomputeField(computedInput);`**

W `mbr/templates/laborant/_fast_entry_content.html`, znajdź:

```js
        });
        recomputeField(computedInput);
    });
}
```

Zastąp na:

```js
        });
    });
}
```

- [ ] **Step 3: Verify w przeglądarce — manual edit survive F5**

- Hard reload
- Wpisz SM = 35,5 → SA pojawia się jako 35,5 (z formuły `sm`)
- Zmień SA ręcznie na 36,0 → blur (zapisuje się on blur)
- F5 / hard reload tej samej szarży
- SA powinno pokazać 36,0 (z DB), NIE 35,5 (auto-recompute) ✅

- [ ] **Step 4: Verify reactive recompute nadal działa**

- Zmień SM na 35,8 → SA przelicza się na 35,8 (manual edit nadpisany — intent)

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "fix(laborant): no initial recompute — manual edit survives F5/reload"
```

---

### Task B4: Diff 4 — bias editor preserving override

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html:4257-4264` (`updateBiasPreview`)
- Modify: `mbr/templates/laborant/_fast_entry_content.html:4283-4296` (`saveBias`)

- [ ] **Step 1: Zlokalizuj `updateBiasPreview`**

```bash
sed -n '4255,4265p' mbr/templates/laborant/_fast_entry_content.html
```

Powinieneś zobaczyć:
```js
function updateBiasPreview(val, kod) {
    var el = document.getElementById('calc-bias-preview');
    if (el) {
        var b = parseFloat(val) || 0;
        el.textContent = 'Formuła: sm - nacl - ' + b;
    }
}
```

- [ ] **Step 2: Zaktualizuj `updateBiasPreview` — substitute last numeric**

Zastąp całą funkcję na:

```js
function updateBiasPreview(val, kod) {
    var saInp = document.querySelector('input[data-kod="' + kod + '"][data-formula]');
    var oldFormula = saInp ? saInp.dataset.formula : '';
    var b = parseFloat(val) || 0;
    var preview = oldFormula.replace(/([+-]\s*)[0-9.]+\s*$/, '$1' + b);
    var el = document.getElementById('calc-bias-preview');
    if (el) el.textContent = 'Formuła: ' + preview;
}
```

- [ ] **Step 3: Zlokalizuj `saveBias` recompute block**

```bash
sed -n '4283,4300p' mbr/templates/laborant/_fast_entry_content.html
```

Powinieneś zobaczyć (fragment):
```js
            var formulaEl = document.querySelector('#calc-container .calc-formula');
            if (formulaEl) formulaEl.textContent = 'sm - nacl - ' + bias;
            // Update data-formula on the SA input and recompute immediately
            var newFormula = 'sm - nacl - ' + bias;
            document.querySelectorAll('input[data-kod="' + kod + '"][data-formula]').forEach(function(saInp) {
                saInp.dataset.formula = newFormula;
                recomputeField(saInp);
                ...
```

- [ ] **Step 4: Zaktualizuj `saveBias` — per-input substitution + dynamic formula display**

Zastąp:
```js
            var formulaEl = document.querySelector('#calc-container .calc-formula');
            if (formulaEl) formulaEl.textContent = 'sm - nacl - ' + bias;
            // Update data-formula on the SA input and recompute immediately
            var newFormula = 'sm - nacl - ' + bias;
            document.querySelectorAll('input[data-kod="' + kod + '"][data-formula]').forEach(function(saInp) {
                saInp.dataset.formula = newFormula;
                recomputeField(saInp);
```

Na:
```js
            // Substitute last numeric in each SA input's formula (preserves override prefix)
            document.querySelectorAll('input[data-kod="' + kod + '"][data-formula]').forEach(function(saInp) {
                var oldFormula = saInp.dataset.formula || '';
                var newFormula = oldFormula.replace(/([+-]\s*)[0-9.]+\s*$/, '$1' + bias);
                saInp.dataset.formula = newFormula;
                // Update calc-formula display in calc panel for the focused input
                if (document.activeElement === saInp) {
                    var formulaEl = document.querySelector('#calc-container .calc-formula');
                    if (formulaEl) formulaEl.textContent = newFormula;
                }
                recomputeField(saInp);
```

- [ ] **Step 5: Verify w przeglądarce — bias editor dla Chegina_K7 SA (formuła `sm - nacl - 0.6`)**

- Otwórz szarżę Chegina_K7
- Hard reload
- Klik w pole SA → panel po prawej pokazuje bias editor (input z wartością `0.6`)
- Zmień bias na `0.7` → preview pod inputem pokazuje `Formuła: sm - nacl - 0.7` (NIE hardcoded `'sm - nacl - 0.7'` byłoby identyczne, ale dla potwierdzenia regex działa — czytaj wartość z `data-formula`)
- Klik Zapisz → status flash `✓ Zapisano`, SA przelicza się
- F5 → bias zachowany w DB

- [ ] **Step 6: Verify że Cheminox_K override `sm` nadal bez bias editora**

- Otwórz szarżę Cheminox_K
- Klik w pole SA → panel pokazuje formułę `sm`, **bez** bias editora (regex `[a-z_]+\s*[-+]\s*([0-9.]+)\s*$` nie matchuje samego `sm`)

- [ ] **Step 7: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "fix(laborant): bias editor preserves formula prefix (substitute last numeric only)"
```

---

## Phase C — End-to-End Verification

> Cel: przejść 10 punktów manual verify checklist ze spec sekcji „Manual verify".

### Task C1: Pełny manual verify Cheminox_K

**Files:** brak — verify w przeglądarce

- [ ] **Step 1: Setup**

```bash
# Restart dev server (cache-bust calculator.js per startup)
pkill -f "python -m mbr.app"
python -m mbr.app &
```

Otwórz `/laborant`, znajdź lub stwórz szarżę Cheminox_K (przez `/technolog` jeśli trzeba), wejdź w jej widok analiza_koncowa.

- [ ] **Step 2: Scenariusz 1 — auto-fill SA z formuły sm**

- Wpisz SM = 35,5 → blur
- SA powinno pojawić się jako 35,5 (formuła `sm`)
- Zapisuje się on blur

- [ ] **Step 3: Scenariusz 2 — manual edit survive blur**

- Po pkt 2: zmień SA ręcznie na 36,0 → blur → kliknij gdzieś indziej
- SA pozostaje 36,0

- [ ] **Step 4: Scenariusz 3 — manual edit survive F5**

- Po pkt 3: F5 / hard reload
- SA pokazuje 36,0 (z DB, bez initial recompute)

- [ ] **Step 5: Scenariusz 4 — recompute nadpisuje manual przy zmianie SM**

- Po pkt 4: zmień SM = 35,8 → SA przelicza się na 35,8
- Manual edit ginie (intent z B w pytaniu 2 spec)

- [ ] **Step 6: Scenariusz 5/6 — czysty model przy F5 z pustym SA**

- Zaczynij nową szarżę Cheminox_K, wpisz SM = 35,5, NIE wpisuj SA, F5
- SA pozostaje puste — laborant musi ruszyć SM albo wpisać ręcznie

- [ ] **Step 7: Scenariusz 7 — Chegina_K7 analiza_koncowa**

- Otwórz szarżę Chegina_K7
- Wpisz SM, NaCl → SA przelicza się z `sm - nacl - 0.6`
- Bias editor pokazuje się dla SA, zmiana biasu = preview `sm - nacl - X`

- [ ] **Step 8: Scenariusz 10 — pole SA edytowalne**

- Klik w pole SA → kursor pojawia się, można pisać
- Brak `readonly` w DOM (DevTools)

---

### Task C2: Audit log verification

**Files:** brak — verify w przeglądarce

- [ ] **Step 1: Sprawdź audit log dla istniejącego override**

```bash
sqlite3 data/batch_db.sqlite "SELECT dt, payload_json FROM audit_log WHERE event_type='parametr.updated' AND payload_json LIKE '%formula_override%' ORDER BY id DESC LIMIT 5;"
```

Expected: ≥1 wpis z `action='formula_override_set'`, `produkt='Cheminox_K'`, `formula_new='sm'`.

- [ ] **Step 2: Test świeżego override (na produktcie który go nie ma)**

W rejestrze `/admin/parametry`, wybierz parametr SA, dodaj override dla Chegina_K7B (lub innego z listy która ma SA w pipeline ale bez override). Wpisz dowolną formułę testową, zapisz.

```bash
sqlite3 data/batch_db.sqlite "SELECT dt, payload_json FROM audit_log WHERE event_type='parametr.updated' AND payload_json LIKE '%Chegina_K7B%' ORDER BY id DESC LIMIT 1;"
```

Expected: nowy wpis z `action='formula_override_set'`, `formula_old=null`, `formula_new=<twoja_formuła>`.

- [ ] **Step 3: Test clear override (× button)**

W rejestrze, klik `×` przy Chegina_K7B override, potwierdź. Audit:

```bash
sqlite3 data/batch_db.sqlite "SELECT payload_json FROM audit_log WHERE event_type='parametr.updated' AND payload_json LIKE '%Chegina_K7B%' ORDER BY id DESC LIMIT 1;"
```

Expected: `action='formula_override_cleared'`, `formula_old=<twoja_formuła>`, `formula_new=null`.

---

## Self-Review Notes

**Spec coverage:**
- Section 1 (Decision: produkt_etap_limity) — A2 endpoint + A4/A5 usage-impact
- Section 2 (Manual edit model) — B1 (no readonly) + B3 (no initial recompute)
- Section 3 (No initial auto-fill) — B3
- Section 4 (No visual distinction) — żaden diff nie dodaje klasy `.manual` (zachowane)
- Section 5 (Migration) — A6
- Section 6 (Architektura — endpoint) — A2
- Section 6.1/6.2 (usage-impact extensions) — A4 + A5
- Section "Diff 4 — bias editor preserving override" — B4
- Section Testy — A1 (fixture adapt), A3 (integration), A4/A5 (usage-impact tests)
- Section Manual verify — C1 (10 punktów)
- Section Audit — C2

**Granularity check:** każdy step 2-5 minut, exact code, exact paths, exact commands z expected output.

**Type/property consistency:**
- `produkt_etap_limity.formula` — używane konsekwentnie (A2, A4, A5, A6)
- `etapy_analityczne.kod` — JOIN klucz, hardcoded `'analiza_koncowa'` w A4 (zgodne ze spec)
- `formula_override` — pole w response, hardcoded `analiza_koncowa` kontekst (zgodne z A4)
- Migration script: `is not None` check (nie falsy, zgodne ze spec po grill-me revisions)

**Dependencies między taskami:**
- A1 (fixture adapt) → A2 (endpoint zmiana) musi być w tej kolejności (TDD red→green)
- A3 (integration test) wymaga A1 fixture + A2 endpoint
- A4 → A5 niezależne, ale oba modyfikują tę samą funkcję — kolejność matters
- A6 może być przed lub po A2-A5 (skrypt nie zależy od kodu app)
- B1-B4 niezależne, ale B3 kluczowy dla manual edit survive F5
- C1-C2 po wszystkich A i B

**Akceptacja zgodna ze spec sekcja Akceptacja** (12 punktów).
