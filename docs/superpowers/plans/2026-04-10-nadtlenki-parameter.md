# Nadtlenki Parameter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `nadtlenki` parameter to `parametry_analityczne`, replace `h2o2` in `analiza_koncowa` contexts for 5 products, and rename h2o2 skrót to `%Perh.` — all as an idempotent DB migration.

**Architecture:** Single migration block appended to `init_mbr_tables()` in `mbr/models.py`. Migration is idempotent: INSERT OR IGNORE for the new parameter, UPDATE only when current value differs, INSERT OR REPLACE for `parametry_etapy` swaps. No UI changes, no new files.

**Tech Stack:** Python, SQLite, pytest (in-memory DB for tests)

---

## Files

- Modify: `mbr/models.py` — append migration block inside `init_mbr_tables()` before the closing `db.commit()`
- Modify: `tests/test_parametry_registry.py` — add tests verifying migration outcome

---

### Task 1: Write tests for the migration

**Files:**
- Modify: `tests/test_parametry_registry.py`

- [ ] **Step 1: Read current test file to understand fixture pattern**

Run: `cat -n tests/test_parametry_registry.py | head -40`

The fixture pattern uses `sqlite3.connect(":memory:")` + `init_mbr_tables(conn)`. Confirm the import before adding tests.

- [ ] **Step 2: Append the three tests**

Open `tests/test_parametry_registry.py` and add at the bottom:

```python
# ---------------------------------------------------------------------------
# Nadtlenki migration tests
# ---------------------------------------------------------------------------

def test_h2o2_skrot_renamed_to_perh(db):
    """After migration, h2o2 skrót must be '%Perh.' (not '%H₂O₂')."""
    row = db.execute(
        "SELECT skrot FROM parametry_analityczne WHERE kod='h2o2'"
    ).fetchone()
    assert row is not None, "h2o2 parameter must exist"
    assert row["skrot"] == "%Perh."


def test_nadtlenki_parameter_exists(db):
    """Migration must create a 'nadtlenki' parameter with correct fields."""
    row = db.execute(
        "SELECT kod, label, skrot, typ, metoda_id, jednostka "
        "FROM parametry_analityczne WHERE kod='nadtlenki'"
    ).fetchone()
    assert row is not None, "nadtlenki parameter must be created"
    assert row["label"] == "Nadtlenki"
    assert row["skrot"] == "%H\u2082O\u2082"
    assert row["typ"] == "titracja"
    assert row["metoda_id"] == 4
    assert row["jednostka"] == "%"


def test_nadtlenki_replaces_h2o2_in_analiza_koncowa(db):
    """For each of the 5 products, nadtlenki must be bound to analiza_koncowa
    and h2o2 must NOT be bound to analiza_koncowa."""
    products = [
        "Chegina_K40GLOL",
        "Cheminox_K",
        "Cheminox_K35",
        "Cheminox_LA",
        "Chemipol_ML",
    ]
    nadtlenki_id = db.execute(
        "SELECT id FROM parametry_analityczne WHERE kod='nadtlenki'"
    ).fetchone()
    assert nadtlenki_id is not None
    nadtlenki_id = nadtlenki_id["id"]

    h2o2_id = db.execute(
        "SELECT id FROM parametry_analityczne WHERE kod='h2o2'"
    ).fetchone()
    assert h2o2_id is not None
    h2o2_id = h2o2_id["id"]

    for prod in products:
        # nadtlenki must be present for this product in analiza_koncowa
        bound = db.execute(
            "SELECT id FROM parametry_etapy "
            "WHERE produkt=? AND kontekst='analiza_koncowa' AND parametr_id=?",
            (prod, nadtlenki_id),
        ).fetchone()
        assert bound is not None, f"{prod}: nadtlenki not bound to analiza_koncowa"

        # h2o2 must NOT be present for this product in analiza_koncowa
        old_bound = db.execute(
            "SELECT id FROM parametry_etapy "
            "WHERE produkt=? AND kontekst='analiza_koncowa' AND parametr_id=?",
            (prod, h2o2_id),
        ).fetchone()
        assert old_bound is None, f"{prod}: h2o2 still bound to analiza_koncowa"
```

- [ ] **Step 3: Run tests — expect FAIL (migration not written yet)**

```bash
cd /Users/tbk/Desktop/aa
python -m pytest tests/test_parametry_registry.py::test_h2o2_skrot_renamed_to_perh tests/test_parametry_registry.py::test_nadtlenki_parameter_exists tests/test_parametry_registry.py::test_nadtlenki_replaces_h2o2_in_analiza_koncowa -v 2>&1 | tail -30
```

Expected: 3 FAILED (h2o2 skrót not yet `%Perh.`, nadtlenki row doesn't exist, no parametry_etapy rows)

---

### Task 2: Implement the migration in models.py

**Files:**
- Modify: `mbr/models.py` — lines ~858–860 (just before `# ---------------------------------------------------------------------------`)

- [ ] **Step 1: Locate insertion point**

The last line of `init_mbr_tables` is `db.commit()` at the end of the `product_ref_values` block (around line 860). Insert the new migration block AFTER that commit and BEFORE the comment line `# ---------------------------------------------------------------------------`.

- [ ] **Step 2: Add the migration block**

In `mbr/models.py`, after the `product_ref_values` block's `db.commit()`, add:

```python
    # Migration: rename h2o2 skrót → %Perh., add nadtlenki parameter,
    # replace h2o2 with nadtlenki in analiza_koncowa for betaine products
    try:
        # 1. Rename h2o2 skrót (idempotent — UPDATE only when still old value)
        db.execute(
            "UPDATE parametry_analityczne SET skrot='%Perh.' "
            "WHERE kod='h2o2' AND (skrot IS NULL OR skrot != '%Perh.')"
        )

        # 2. Insert nadtlenki parameter (INSERT OR IGNORE = idempotent)
        db.execute("""
            INSERT OR IGNORE INTO parametry_analityczne
                (kod, label, typ, skrot, metoda_id, jednostka)
            VALUES
                ('nadtlenki', 'Nadtlenki', 'titracja', '%H\u2082O\u2082', 4, '%')
        """)

        # 3. Replace h2o2 → nadtlenki in parametry_etapy for analiza_koncowa
        _NADTLENKI_PRODUCTS = [
            # (produkt, kolejnosc, min_limit, max_limit, nawazka_g)
            ("Chegina_K40GLOL", 7,  0.0, 0.01, 10.0),
            ("Cheminox_K",      3,  0.0, 0.01, None),
            ("Cheminox_K35",    3,  0.0, 0.01, None),
            ("Cheminox_LA",     3,  0.0, 0.01, None),
            ("Chemipol_ML",     4,  0.0, 0.15, None),
        ]
        _h2o2_row = db.execute(
            "SELECT id FROM parametry_analityczne WHERE kod='h2o2'"
        ).fetchone()
        _nadtlenki_row = db.execute(
            "SELECT id FROM parametry_analityczne WHERE kod='nadtlenki'"
        ).fetchone()

        if _h2o2_row and _nadtlenki_row:
            _h2o2_id = _h2o2_row["id"]
            _nadtlenki_id = _nadtlenki_row["id"]

            for _prod, _kol, _mn, _mx, _naw in _NADTLENKI_PRODUCTS:
                # Remove old h2o2 binding for this product/context
                db.execute(
                    "DELETE FROM parametry_etapy "
                    "WHERE produkt=? AND kontekst='analiza_koncowa' AND parametr_id=?",
                    (_prod, _h2o2_id),
                )
                # Insert nadtlenki binding (INSERT OR IGNORE = idempotent)
                db.execute("""
                    INSERT OR IGNORE INTO parametry_etapy
                        (produkt, kontekst, parametr_id, kolejnosc, min_limit, max_limit, nawazka_g, wymagany)
                    VALUES (?, 'analiza_koncowa', ?, ?, ?, ?, ?, 1)
                """, (_prod, _nadtlenki_id, _kol, _mn, _mx, _naw))

        db.commit()
    except Exception:
        pass
```

- [ ] **Step 3: Run the three tests — expect PASS**

```bash
cd /Users/tbk/Desktop/aa
python -m pytest tests/test_parametry_registry.py::test_h2o2_skrot_renamed_to_perh tests/test_parametry_registry.py::test_nadtlenki_parameter_exists tests/test_parametry_registry.py::test_nadtlenki_replaces_h2o2_in_analiza_koncowa -v 2>&1 | tail -20
```

Expected: 3 PASSED

- [ ] **Step 4: Run the full test suite — no regressions**

```bash
cd /Users/tbk/Desktop/aa
python -m pytest --tb=short -q 2>&1 | tail -30
```

Expected: all previously passing tests still pass. New failures = regression, must fix before committing.

- [ ] **Step 5: Commit**

```bash
git add mbr/models.py tests/test_parametry_registry.py
git commit -m "feat: add nadtlenki parameter, rename h2o2 skrót to %Perh."
```

---

## Self-Review

**Spec coverage:**
1. ✅ Rename h2o2 skrót → `%Perh.` — Task 2 step 2 line 1
2. ✅ New `nadtlenki` parameter (label, skrót, typ, metoda_id=4, jednostka) — Task 2 step 2 line 2
3. ✅ Replace h2o2 → nadtlenki in `parametry_etapy` for 5 products with correct limits — Task 2 step 2 line 3
4. ✅ No historical data migration — not included by design
5. ✅ Idempotent migration in `models.py` — INSERT OR IGNORE + UPDATE with condition

**Placeholder scan:** None found.

**Type consistency:** `_h2o2_row["id"]` and `_nadtlenki_row["id"]` — both use sqlite3.Row dict access, consistent with connection having `row_factory = sqlite3.Row`. The in-memory test fixture sets this via `init_mbr_tables` which uses `executescript` (no row_factory needed there), and the test fixture explicitly sets `conn.row_factory = sqlite3.Row`. Guard `if _h2o2_row and _nadtlenki_row` prevents crash on empty DB.
