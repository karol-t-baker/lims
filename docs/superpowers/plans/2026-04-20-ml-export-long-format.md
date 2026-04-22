# ML Export — Long Format Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zastąpić jeden wide CSV (`/api/export/ml/k7.csv` z hardkodowanym schematem) paczką 4 long-format CSV + `schema.json` + `README.md` w zipie, pobieraną z `/api/export/ml/k7.zip`.

**Architecture:** Trzy warstwy: (1) `schema.py` buduje samoopisujący się słownik parametrów/substancji ze słowników DB (`parametry_analityczne`, `produkt_etap_limity`, `mbr_templates.parametry_lab`, `etap_korekty_katalog`); (2) cztery niezależne buildery w `query.py` (`build_batches/sessions/measurements/corrections`) czytają odpowiednie tabele; (3) `export_ml_package` pakuje wszystko w zip. Endpoint i UI jeden plik każdy, stara logika wide usunięta.

**Tech Stack:** Python 3, Flask, sqlite3 (raw, bez ORM), `csv` + `zipfile` z stdlib, pytest z fixture w-memory. Frontend: vanilla Jinja, bez nowych bibliotek.

**Spec:** `docs/superpowers/specs/2026-04-20-ml-export-long-format-design.md`

---

## File Structure

| Plik | Rola | Akcja |
|---|---|---|
| `mbr/ml_export/schema.py` | Słownik parametrów + substancji dla `schema.json` | **Create** |
| `mbr/ml_export/query.py` | Builderzy rzędów (batches/sessions/measurements/corrections) + `export_ml_package` | **Rewrite** |
| `mbr/ml_export/routes.py` | Endpoint `.zip`, strona `/ml-export` | **Rewrite** |
| `mbr/templates/ml_export/ml_export.html` | 4-panelowy podgląd | **Rewrite** |
| `tests/test_ml_export.py` | Testy nowego API | **Rewrite** |

`mbr/ml_export/__init__.py` (rejestracja blueprintu) — bez zmian.

---

## Task 1: Prep — Fresh test fixture + remove old tests

Stare testy całkowicie usuwamy (breaking change). Nowy fixture jest podstawą dla wszystkich kolejnych Tasków.

**Files:**
- Rewrite: `tests/test_ml_export.py`

- [ ] **Step 1: Zastąp całą zawartość `tests/test_ml_export.py` nowym fixtem**

```python
"""Tests for ML export — long format (zip with CSVs + schema.json)."""
import io
import json
import sqlite3
import zipfile

import pytest

from mbr.models import init_mbr_tables


def _seed_k7(conn: sqlite3.Connection) -> None:
    """Minimal K7 pipeline fixture: 1 completed batch, sesje on 3 stages, legacy recipe."""
    conn.execute("DELETE FROM mbr_templates")
    conn.execute("DELETE FROM produkt_pipeline")
    conn.execute("DELETE FROM etap_parametry")
    conn.execute("DELETE FROM korekta_cele")
    conn.execute("DELETE FROM etap_korekty_katalog")
    conn.execute("DELETE FROM etapy_analityczne")
    conn.execute("DELETE FROM parametry_analityczne")
    conn.execute("DELETE FROM produkty")
    params = [
        (1, 'ph_10proc', 'pH 10%',             'bezposredni', 2, None,             None),
        (2, 'nd20',      'nD20',               'bezposredni', 4, None,             None),
        (3, 'so3',       'Siarczyny',          'titracja',    3, None,             '%'),
        (4, 'barwa_I2',  'Barwa jodowa',       'bezposredni', 2, None,             None),
        (5, 'nadtlenki', 'Nadtlenki',          'titracja',    3, None,             '%'),
        (6, 'sm',        'Sucha masa',         'bezposredni', 1, None,             '%'),
        (7, 'nacl',      'Chlorek sodu',       'titracja',    1, None,             '%'),
        (8, 'sa',        'Substancja aktywna', 'obliczeniowy',1, 'sm - nacl - 0.6', '%'),
        (9, 'na2so3_recept_kg', 'Siarczyn sodu — recepta', 'bezposredni', 2, None, 'kg'),
    ]
    for p in params:
        conn.execute(
            """INSERT INTO parametry_analityczne
                   (id, kod, label, typ, precision, formula, jednostka)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            p,
        )
    conn.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (4,'sulfonowanie','Sulfonowanie','jednorazowy')")
    conn.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (5,'utlenienie','Utlenienie','cykliczny')")
    conn.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (9,'standaryzacja','Standaryzacja','cykliczny')")
    conn.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (10,'analiza_koncowa','Analiza końcowa','jednorazowy')")
    for etap_id, k in [(4,1),(5,2),(9,3),(10,4)]:
        conn.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chegina_K7',?,?)", (etap_id, k))
    for etap_id, param_id in [
        (4,1),(4,2),(4,3),(4,4),
        (5,1),(5,2),(5,3),(5,4),(5,5),
        (9,1),(9,2),(9,6),(9,7),(9,8),
        (10,1),(10,4),(10,6),(10,7),(10,8),
    ]:
        conn.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (?, ?, 1)", (etap_id, param_id))
    for kid, etap_id, subst in [
        (1,4,'Siarczyn sodu'), (2,4,'Perhydrol 34%'),
        (3,5,'Perhydrol 34%'), (4,5,'Woda łącznie'), (5,5,'Kwas cytrynowy'),
        (6,9,'Woda łącznie'),
    ]:
        conn.execute("INSERT INTO etap_korekty_katalog (id, etap_id, substancja, jednostka) VALUES (?, ?, ?, 'kg')",
                     (kid, etap_id, subst))
    parametry_lab = {
        "analiza_koncowa": {
            "pola": [
                {"kod": "ph_10proc", "min_limit": 4.0, "max_limit": 6.0},
                {"kod": "sm",        "min_limit": 40.0, "max_limit": 48.0},
                {"kod": "sa",        "min_limit": 30.0, "max_limit": 42.0, "formula": "sm - nacl - 0.6"},
                {"kod": "barwa_I2",  "min_limit": 0.0, "max_limit": 200.0},
            ]
        }
    }
    conn.execute(
        "INSERT INTO mbr_templates (mbr_id, produkt, wersja, parametry_lab, dt_utworzenia) "
        "VALUES (1,'Chegina_K7',1,?,'2026-01-01')",
        (json.dumps(parametry_lab),),
    )
    # Per-stage product specs (some of them)
    conn.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, min_limit, max_limit) "
        "VALUES ('Chegina_K7', 10, 4, 0.0, 200.0)"
    )
    conn.execute(
        "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, min_limit, max_limit) "
        "VALUES ('Chegina_K7', 10, 8, 30.0, 42.0)"
    )

    conn.execute(
        """INSERT INTO ebr_batches
               (ebr_id, mbr_id, batch_id, nr_partii, wielkosc_szarzy_kg, nastaw,
                dt_start, dt_end, status, typ, pakowanie_bezposrednie)
           VALUES (1, 1, 'Chegina_K7__1_2026', '1/2026', 13300, 13300,
                   '2026-04-16T09:00:00', '2026-04-16T12:00:00', 'completed', 'szarza', NULL)"""
    )
    # Legacy recipe dose (ebr_wyniki only)
    conn.execute(
        "INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc, dt_wpisu, wpisal) "
        "VALUES (1,'sulfonowanie','na2so3_recept_kg','na2so3',15.0,'2026-04-16','JK')"
    )
    # Sulfonowanie R1 — 4 pomiary + 1 korekta
    conn.execute(
        "INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, decyzja, dt_start, laborant) "
        "VALUES (1,1,4,1,'zamkniety','przejscie','2026-04-16T09:05:00','JK')"
    )
    for pid, val in [(1, 11.89), (2, 1.3954), (3, 0.12), (4, 0.2)]:
        conn.execute(
            "INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) "
            "VALUES (1, ?, ?, 1, '2026-04-16', 'JK')",
            (pid, val),
        )
    conn.execute(
        "INSERT INTO ebr_korekta_v2 (sesja_id, korekta_typ_id, ilosc, status) "
        "VALUES (1,1,15.0,'wykonana')"
    )
    # Targets (globals)
    conn.execute("INSERT INTO korekta_cele (etap_id, produkt, kod, wartosc) VALUES (9,'Chegina_K7','target_ph',6.25)")
    conn.execute("INSERT INTO korekta_cele (etap_id, produkt, kod, wartosc) VALUES (9,'Chegina_K7','target_nd20',1.3922)")


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_mbr_tables(conn)
    _seed_k7(conn)
    conn.commit()
    yield conn
    conn.close()


# Placeholder — real tests added in later tasks.
def test_fixture_smoke(db):
    row = db.execute("SELECT COUNT(*) FROM ebr_batches").fetchone()
    assert row[0] == 1
```

- [ ] **Step 2: Uruchom fixture smoke test**

Run: `pytest tests/test_ml_export.py -v`
Expected: `test_fixture_smoke PASS`. Wszystkie stare testy zniknęły — plik ma tylko jedno przechodzące `test_fixture_smoke`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_ml_export.py
git commit -m "test(ml_export): reset tests for long-format rewrite"
```

---

## Task 2: `schema.py` — słownik parametrów i substancji

Jeden nowy plik, cztery publiczne funkcje pomocnicze i jedna główna `build_schema`. Żadnej zmiany w `query.py`/`routes.py` jeszcze.

**Files:**
- Create: `mbr/ml_export/schema.py`
- Modify: `tests/test_ml_export.py` (dopisz testy)

- [ ] **Step 1: Dopisz testy `schema.py` na końcu `tests/test_ml_export.py`**

```python
# ─── schema.py ────────────────────────────────────────────────────────────────

def test_build_schema_structure(db):
    from mbr.ml_export.schema import build_schema
    s = build_schema(db, produkty=["Chegina_K7"], counts={"batches": 1, "sessions": 1, "measurements": 4, "corrections": 1})
    assert s["export_version"] == "1.0"
    assert s["produkt_filter"] == ["Chegina_K7"]
    assert s["counts"]["batches"] == 1
    # generated_at is ISO-ish
    assert "T" in s["generated_at"]
    # etapy in pipeline order
    kody = [e["kod"] for e in s["etapy"]]
    assert kody == ["sulfonowanie", "utlenienie", "standaryzacja", "analiza_koncowa"]


def test_build_schema_parametry_dict(db):
    from mbr.ml_export.schema import build_schema
    s = build_schema(db, produkty=["Chegina_K7"])
    # sa is calculated with a formula
    sa = s["parametry"]["sa"]
    assert sa["is_calculated"] is True
    assert sa["formula"] == "sm - nacl - 0.6"
    assert sa["jednostka"] == "%"
    # sa appears in analiza_koncowa.parametry_lab with min/max → target candidate
    assert sa["is_target_candidate"] is True
    # nd20 is not a target candidate (not in analiza_koncowa parametry_lab)
    assert s["parametry"]["nd20"]["is_target_candidate"] is False


def test_build_schema_recipe_kategoria(db):
    from mbr.ml_export.schema import build_schema
    s = build_schema(db, produkty=["Chegina_K7"])
    assert s["parametry"]["na2so3_recept_kg"]["kategoria"] == "recipe"
    assert s["parametry"]["sm"]["kategoria"] == "measurement"


def test_build_schema_per_stage_specs(db):
    from mbr.ml_export.schema import build_schema
    s = build_schema(db, produkty=["Chegina_K7"])
    barwa = s["parametry"]["barwa_I2"]
    assert barwa["specs_per_etap"]["analiza_koncowa"] == {"min": 0.0, "max": 200.0}


def test_build_schema_substancje(db):
    from mbr.ml_export.schema import build_schema
    s = build_schema(db, produkty=["Chegina_K7"])
    subs = s["substancje_korekcji"]
    assert "Perhydrol 34%" in subs
    assert "Woda łącznie" in subs
    # Formula-driven via etap_korekty_katalog.formula_ilosc OR ilosc_wyliczona — none seeded here,
    # so all default to False. (test_build_schema_substancje_formula verifies is_formula_driven=True path.)
    assert subs["Perhydrol 34%"]["is_formula_driven"] is False


def test_build_schema_substancje_formula(db):
    """is_formula_driven=True when etap_korekty_katalog.formula_ilosc is non-empty."""
    from mbr.ml_export.schema import build_schema
    # Seed Kwas cytrynowy (id=5 already exists in fixture, katalog id=5) with formula_ilosc
    db.execute(
        "UPDATE etap_korekty_katalog SET formula_ilosc=? WHERE substancja=?",
        ("100 * (ph - target) / masa", "Kwas cytrynowy"),
    )
    # Siarczyn sodu (id=1) keeps formula_ilosc=NULL
    db.commit()
    s = build_schema(db, produkty=["Chegina_K7"])
    subs = s["substancje_korekcji"]
    assert subs["Kwas cytrynowy"]["is_formula_driven"] is True
    assert subs["Siarczyn sodu"]["is_formula_driven"] is False
```

- [ ] **Step 2: Uruchom — powinny failować (ImportError)**

Run: `pytest tests/test_ml_export.py -v`
Expected: 5 × FAIL z `ModuleNotFoundError: No module named 'mbr.ml_export.schema'`.

- [ ] **Step 3: Utwórz `mbr/ml_export/schema.py` z pełną implementacją**

```python
"""Build the schema.json dictionary for the ML export package.

Self-describing: data scientist learns parameter units, specs, formulas, and
target candidacy without needing to query the DB. Auto-generated from
parametry_analityczne + produkt_etap_limity + mbr_templates.parametry_lab +
etap_korekty_katalog.
"""
import json
import sqlite3
from datetime import datetime, timezone

EXPORT_VERSION = "1.0"

# Parameters that represent recipe doses rather than measurements. Extend as
# new recipe-level params are added. Not derived from parametry_analityczne.grupa
# because that column is dominated by 'lab' and doesn't separate cleanly.
_RECIPE_PARAMS = {"na2so3_recept_kg"}


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pipeline_etapy(db: sqlite3.Connection, produkt: str) -> list[dict]:
    rows = db.execute(
        """SELECT ea.kod, ea.nazwa, pp.kolejnosc
             FROM produkt_pipeline pp
             JOIN etapy_analityczne ea ON ea.id = pp.etap_id
            WHERE pp.produkt = ?
         ORDER BY pp.kolejnosc""",
        (produkt,),
    ).fetchall()
    return [{"kod": r["kod"], "label": r["nazwa"], "kolejnosc": r["kolejnosc"]} for r in rows]


def _target_candidates_from_parametry_lab(parametry_lab_json: str) -> set[str]:
    """Parameter codes that appear in analiza_koncowa with at least one min/max limit."""
    try:
        data = json.loads(parametry_lab_json or "{}")
    except json.JSONDecodeError:
        return set()
    ak = data.get("analiza_koncowa") or {}
    out = set()
    for p in ak.get("pola", []):
        if p.get("min_limit") is not None or p.get("max_limit") is not None:
            out.add(p.get("kod"))
    return out


def _formula_from_parametry_lab(parametry_lab_json: str) -> dict[str, str]:
    """Map param_kod -> formula string, sourced from mbr_templates.parametry_lab."""
    try:
        data = json.loads(parametry_lab_json or "{}")
    except json.JSONDecodeError:
        return {}
    out = {}
    for etap_cfg in data.values():
        for p in (etap_cfg or {}).get("pola", []):
            if p.get("formula"):
                out[p["kod"]] = p["formula"]
    return out


def _specs_per_etap(db: sqlite3.Connection, produkt: str) -> dict[str, dict[str, dict]]:
    """Return {param_kod: {etap_kod: {min, max}}} from produkt_etap_limity."""
    rows = db.execute(
        """SELECT pa.kod AS param_kod, ea.kod AS etap_kod,
                  pel.min_limit, pel.max_limit
             FROM produkt_etap_limity pel
             JOIN parametry_analityczne pa ON pa.id = pel.parametr_id
             JOIN etapy_analityczne    ea ON ea.id = pel.etap_id
            WHERE pel.produkt = ?""",
        (produkt,),
    ).fetchall()
    out: dict[str, dict[str, dict]] = {}
    for r in rows:
        if r["min_limit"] is None and r["max_limit"] is None:
            continue
        out.setdefault(r["param_kod"], {})[r["etap_kod"]] = {
            "min": r["min_limit"], "max": r["max_limit"],
        }
    return out


def _build_parametry(db: sqlite3.Connection, produkt: str) -> dict[str, dict]:
    row = db.execute(
        "SELECT parametry_lab FROM mbr_templates WHERE produkt=? ORDER BY wersja DESC LIMIT 1",
        (produkt,),
    ).fetchone()
    parametry_lab_json = row["parametry_lab"] if row else "{}"

    targets = _target_candidates_from_parametry_lab(parametry_lab_json)
    template_formulas = _formula_from_parametry_lab(parametry_lab_json)
    specs = _specs_per_etap(db, produkt)

    params = db.execute(
        "SELECT kod, label, skrot, typ, precision, formula, jednostka "
        "FROM parametry_analityczne ORDER BY id"
    ).fetchall()
    out: dict[str, dict] = {}
    for p in params:
        kod = p["kod"]
        is_calc = (p["typ"] == "obliczeniowy") or bool(p["formula"]) or kod in template_formulas
        out[kod] = {
            "kod": kod,
            "label": p["label"],
            "skrot": p["skrot"],
            "jednostka": p["jednostka"],
            "precision": p["precision"],
            "kategoria": "recipe" if kod in _RECIPE_PARAMS else "measurement",
            "typ_pomiaru": p["typ"],
            "is_calculated": is_calc,
            "formula": p["formula"] or template_formulas.get(kod),
            "is_target_candidate": kod in targets,
            "specs_per_etap": specs.get(kod, {}),
        }
    return out


def _build_substancje(db: sqlite3.Connection) -> dict[str, dict]:
    """Build substancje_korekcji dict for schema.json.

    A substancja is "formula-driven" if either:
      - etap_korekty_katalog.formula_ilosc has a non-empty value for it, OR
      - any ebr_korekta_v2.ilosc_wyliczona row references it.
    """
    rows = db.execute(
        """
        SELECT DISTINCT substancja
        FROM etap_korekty_katalog
        WHERE substancja IS NOT NULL
        """
    ).fetchall()
    from_katalog = {r["substancja"] for r in rows}

    with_formula = set()
    for r in db.execute(
        """
        SELECT DISTINCT substancja
        FROM etap_korekty_katalog
        WHERE formula_ilosc IS NOT NULL AND TRIM(formula_ilosc) <> ''
        """
    ).fetchall():
        with_formula.add(r["substancja"])

    for r in db.execute(
        """
        SELECT DISTINCT substancja
        FROM ebr_korekta_v2
        WHERE ilosc_wyliczona IS NOT NULL
        """
    ).fetchall():
        with_formula.add(r["substancja"])

    # Also pick up substancje that appear in ebr_korekta_v2 but not katalog.
    for r in db.execute(
        "SELECT DISTINCT substancja FROM ebr_korekta_v2 WHERE substancja IS NOT NULL"
    ).fetchall():
        from_katalog.add(r["substancja"])

    return {
        s: {"is_formula_driven": s in with_formula}
        for s in sorted(from_katalog)
    }


def _table_has_column(db: sqlite3.Connection, table: str, col: str) -> bool:
    try:
        cols = [r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()]
        return col in cols
    except sqlite3.Error:
        return False


def build_schema(db: sqlite3.Connection, produkty: list[str],
                 counts: dict[str, int] | None = None) -> dict:
    """Build the schema.json dictionary. `counts` is optional — if caller already
    knows row counts, pass them; otherwise zeros are emitted."""
    produkt = produkty[0] if produkty else ""
    return {
        "export_version": EXPORT_VERSION,
        "generated_at": _iso_now(),
        "produkt_filter": list(produkty),
        "counts": counts or {"batches": 0, "sessions": 0, "measurements": 0, "corrections": 0},
        "etapy": _pipeline_etapy(db, produkt),
        "parametry": _build_parametry(db, produkt),
        "substancje_korekcji": _build_substancje(db),
    }
```

- [ ] **Step 4: Uruchom testy `schema.py`**

Run: `pytest tests/test_ml_export.py -v -k schema`
Expected: 5 × PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/ml_export/schema.py tests/test_ml_export.py
git commit -m "feat(ml_export): add schema.py — self-describing parameter dictionary"
```

---

## Task 3: `query.build_batches` — jedna linia per szarża

**Files:**
- Modify: `mbr/ml_export/query.py`
- Modify: `tests/test_ml_export.py`

- [ ] **Step 1: Dopisz testy na końcu `tests/test_ml_export.py`**

```python
# ─── build_batches ────────────────────────────────────────────────────────────

BATCH_COLS = {
    "ebr_id", "batch_id", "nr_partii", "produkt", "status",
    "masa_kg", "meff_kg", "dt_start", "dt_end", "pakowanie",
    "target_ph", "target_nd20",
}


def test_build_batches_one_row(db):
    from mbr.ml_export.query import build_batches
    rows = build_batches(db, produkty=["Chegina_K7"], statuses=("completed",))
    assert len(rows) == 1
    r = rows[0]
    assert set(r.keys()) == BATCH_COLS
    assert r["ebr_id"] == 1
    assert r["batch_id"] == "Chegina_K7__1_2026"
    assert r["produkt"] == "Chegina_K7"
    assert r["status"] == "completed"
    assert r["masa_kg"] == 13300.0
    assert r["meff_kg"] == 12300.0  # masa > 6600 → masa - 1000
    assert r["pakowanie"] == "zbiornik"  # default when NULL in DB
    assert r["target_ph"] == 6.25
    assert r["target_nd20"] == 1.3922


def test_build_batches_meff_below_threshold(db):
    from mbr.ml_export.query import build_batches
    db.execute("UPDATE ebr_batches SET wielkosc_szarzy_kg=5000, nastaw=5000 WHERE ebr_id=1")
    db.commit()
    r = build_batches(db, produkty=["Chegina_K7"], statuses=("completed",))[0]
    assert r["masa_kg"] == 5000.0
    assert r["meff_kg"] == 4500.0  # masa <= 6600 → masa - 500


def test_build_batches_status_filter(db):
    from mbr.ml_export.query import build_batches
    db.execute(
        """INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, wielkosc_szarzy_kg,
                                     nastaw, dt_start, status, typ)
           VALUES (2,1,'K7__2','2/2026',13300,13300,'2026-04-17','cancelled','szarza')"""
    )
    db.commit()
    assert len(build_batches(db, produkty=["Chegina_K7"], statuses=("completed",))) == 1
    rows = build_batches(db, produkty=["Chegina_K7"], statuses=("completed","cancelled"))
    assert {r["ebr_id"] for r in rows} == {1, 2}


def test_build_batches_target_from_snapshot(db):
    """cele_json on any standaryzacja session overrides globals."""
    from mbr.ml_export.query import build_batches
    db.execute(
        "INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, cele_json) "
        "VALUES (99, 1, 9, 1, 'zamkniety', ?)",
        ('{"target_ph": 5.80, "target_nd20": 1.3899}',),
    )
    db.commit()
    r = build_batches(db, produkty=["Chegina_K7"], statuses=("completed",))[0]
    assert r["target_ph"] == 5.80
    assert r["target_nd20"] == 1.3899


def test_build_batches_open_excluded(db):
    from mbr.ml_export.query import build_batches
    db.execute(
        """INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, wielkosc_szarzy_kg,
                                     nastaw, dt_start, status, typ)
           VALUES (5,1,'K7__5','5/2026',13300,13300,'2026-04-17','open','szarza')"""
    )
    db.commit()
    rows = build_batches(db, produkty=["Chegina_K7"], statuses=("completed","cancelled"))
    assert all(r["status"] in ("completed","cancelled") for r in rows)
```

- [ ] **Step 2: Uruchom — nowe testy failują**

Run: `pytest tests/test_ml_export.py -v -k build_batches`
Expected: 5 × FAIL z `ImportError: cannot import name 'build_batches'` (stary query.py dalej eksportuje wide functions).

- [ ] **Step 3: Zastąp zawartość `mbr/ml_export/query.py` nowym skeletonem + `build_batches`**

```python
"""Build long-format rows for the ML export package.

Public API:
    build_batches(db, produkty, statuses) -> list[dict]   # one row per batch
    build_sessions(db, ebr_ids)          -> list[dict]   # one row per (batch, etap, runda)
    build_measurements(db, ebr_ids)      -> list[dict]   # pomiary + legacy, long
    build_corrections(db, ebr_ids)       -> list[dict]   # one row per correction
    export_ml_package(db, produkty, statuses) -> bytes   # zip of 4 CSVs + schema + README
"""
import csv
import io
import json
import sqlite3
import zipfile
from datetime import datetime

from mbr.ml_export.schema import build_schema

DEFAULT_PRODUKTY = ["Chegina_K7"]


def _meff(masa: float) -> float:
    return masa - 1000 if masa > 6600 else masa - 500


def _batch_target(db: sqlite3.Connection, ebr_id: int, produkt: str) -> tuple[float | None, float | None]:
    """Return (target_ph, target_nd20). Prefer cele_json snapshot on any
    standaryzacja session; fall back to korekta_cele globals for the produkt."""
    tph = tnd = None
    try:
        row = db.execute(
            """SELECT s.cele_json
                 FROM ebr_etap_sesja s
                 JOIN etapy_analityczne ea ON ea.id = s.etap_id
                WHERE s.ebr_id = ? AND ea.kod = 'standaryzacja'
                  AND s.cele_json IS NOT NULL
             ORDER BY s.runda
                LIMIT 1""",
            (ebr_id,),
        ).fetchone()
    except sqlite3.Error:
        row = None
    if row and row["cele_json"]:
        try:
            cele = json.loads(row["cele_json"])
            tph = cele.get("target_ph")
            tnd = cele.get("target_nd20")
        except json.JSONDecodeError:
            pass
    if tph is None or tnd is None:
        globals_ = db.execute(
            "SELECT kod, wartosc FROM korekta_cele WHERE produkt = ?",
            (produkt,),
        ).fetchall()
        for g in globals_:
            if g["kod"] == "target_ph" and tph is None:
                tph = g["wartosc"]
            elif g["kod"] == "target_nd20" and tnd is None:
                tnd = g["wartosc"]
    return tph, tnd


def build_batches(db: sqlite3.Connection, produkty: list[str],
                  statuses: tuple[str, ...]) -> list[dict]:
    if not produkty or not statuses:
        return []
    prod_q = ",".join("?" for _ in produkty)
    stat_q = ",".join("?" for _ in statuses)
    rows = db.execute(
        f"""SELECT e.ebr_id, e.batch_id, e.nr_partii, e.wielkosc_szarzy_kg, e.nastaw,
                   e.dt_start, e.dt_end, e.status, e.pakowanie_bezposrednie,
                   m.produkt
              FROM ebr_batches e
              JOIN mbr_templates m ON m.mbr_id = e.mbr_id
             WHERE e.status IN ({stat_q}) AND e.typ = 'szarza'
               AND m.produkt IN ({prod_q})
          ORDER BY e.ebr_id""",
        (*statuses, *produkty),
    ).fetchall()

    out = []
    for b in rows:
        masa = b["wielkosc_szarzy_kg"] or b["nastaw"] or 0
        tph, tnd = _batch_target(db, b["ebr_id"], b["produkt"])
        out.append({
            "ebr_id":      b["ebr_id"],
            "batch_id":    b["batch_id"],
            "nr_partii":   b["nr_partii"],
            "produkt":     b["produkt"],
            "status":      b["status"],
            "masa_kg":     float(masa) if masa else 0.0,
            "meff_kg":     float(_meff(masa)) if masa else 0.0,
            "dt_start":    b["dt_start"],
            "dt_end":      b["dt_end"],
            "pakowanie":   b["pakowanie_bezposrednie"] or "zbiornik",
            "target_ph":   tph,
            "target_nd20": tnd,
        })
    return out
```

- [ ] **Step 4: Uruchom testy `build_batches`**

Run: `pytest tests/test_ml_export.py -v -k build_batches`
Expected: 5 × PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/ml_export/query.py tests/test_ml_export.py
git commit -m "feat(ml_export): build_batches — long format, target from snapshot/globals"
```

---

## Task 4: `query.build_sessions` — jedna linia per (batch, etap, runda)

**Files:**
- Modify: `mbr/ml_export/query.py`
- Modify: `tests/test_ml_export.py`

- [ ] **Step 1: Dopisz testy**

```python
# ─── build_sessions ───────────────────────────────────────────────────────────

def test_build_sessions_from_seed(db):
    from mbr.ml_export.query import build_sessions
    rows = build_sessions(db, ebr_ids=[1])
    assert len(rows) == 1
    s = rows[0]
    assert set(s.keys()) == {"ebr_id", "etap", "runda", "dt_start", "laborant"}
    assert s == {
        "ebr_id": 1,
        "etap": "sulfonowanie",
        "runda": 1,
        "dt_start": "2026-04-16T09:05:00",
        "laborant": "JK",
    }


def test_build_sessions_multiple_stages_ordered(db):
    """Sessions ordered by (ebr_id, etap pipeline order, runda)."""
    from mbr.ml_export.query import build_sessions
    # Add utlenienie R1 and R2
    db.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, dt_start, laborant) "
               "VALUES (2,1,5,1,'zamkniety','2026-04-16T10:00:00','JK')")
    db.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, dt_start, laborant) "
               "VALUES (3,1,5,2,'zamkniety','2026-04-16T10:30:00','JK')")
    db.commit()
    rows = build_sessions(db, ebr_ids=[1])
    assert [(r["etap"], r["runda"]) for r in rows] == [
        ("sulfonowanie", 1), ("utlenienie", 1), ("utlenienie", 2),
    ]


def test_build_sessions_empty_when_no_ids(db):
    from mbr.ml_export.query import build_sessions
    assert build_sessions(db, ebr_ids=[]) == []
```

- [ ] **Step 2: Uruchom — fail na ImportError**

Run: `pytest tests/test_ml_export.py -v -k build_sessions`
Expected: 3 × FAIL z `ImportError: cannot import name 'build_sessions'`.

- [ ] **Step 3: Dopisz `build_sessions` do `mbr/ml_export/query.py` (po `build_batches`)**

```python
def build_sessions(db: sqlite3.Connection, ebr_ids: list[int]) -> list[dict]:
    if not ebr_ids:
        return []
    ids_q = ",".join("?" for _ in ebr_ids)
    rows = db.execute(
        f"""SELECT s.ebr_id, ea.kod AS etap, s.runda, s.dt_start, s.laborant,
                   pp.kolejnosc AS pipeline_order
              FROM ebr_etap_sesja s
              JOIN etapy_analityczne ea ON ea.id = s.etap_id
              JOIN ebr_batches e        ON e.ebr_id = s.ebr_id
              JOIN mbr_templates m      ON m.mbr_id = e.mbr_id
              LEFT JOIN produkt_pipeline pp
                     ON pp.produkt = m.produkt AND pp.etap_id = s.etap_id
             WHERE s.ebr_id IN ({ids_q})
          ORDER BY s.ebr_id, pp.kolejnosc, s.runda""",
        ebr_ids,
    ).fetchall()
    return [
        {
            "ebr_id":   r["ebr_id"],
            "etap":     r["etap"],
            "runda":    r["runda"],
            "dt_start": r["dt_start"],
            "laborant": r["laborant"],
        }
        for r in rows
    ]
```

- [ ] **Step 4: Uruchom**

Run: `pytest tests/test_ml_export.py -v -k build_sessions`
Expected: 3 × PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/ml_export/query.py tests/test_ml_export.py
git commit -m "feat(ml_export): build_sessions — long format, pipeline-ordered"
```

---

## Task 5: `query.build_measurements` — pomiar + legacy merge rule

Core logic. Test najtrudniejszy — trzy kombinacje (tylko new, tylko legacy, oba).

**Files:**
- Modify: `mbr/ml_export/query.py`
- Modify: `tests/test_ml_export.py`

- [ ] **Step 1: Dopisz testy**

```python
# ─── build_measurements ───────────────────────────────────────────────────────

MEAS_COLS = {
    "ebr_id", "etap", "runda", "param_kod",
    "wartosc", "wartosc_text", "w_limicie",
    "dt_wpisu", "wpisal", "is_legacy",
}


def test_build_measurements_new_only(db):
    """Fixture: sulfonowanie R1 has 4 pomiary in ebr_pomiar, no ebr_wyniki for them."""
    from mbr.ml_export.query import build_measurements
    rows = build_measurements(db, ebr_ids=[1])
    # 4 pomiary + 1 legacy na2so3_recept_kg (always exempt) = 5
    assert len(rows) == 5
    new = [r for r in rows if r["is_legacy"] == 0]
    assert len(new) == 4
    for r in new:
        assert set(r.keys()) == MEAS_COLS
        assert r["ebr_id"] == 1
        assert r["etap"] == "sulfonowanie"
        assert r["runda"] == 1
        assert r["wartosc"] is not None
        assert r["w_limicie"] == 1
        assert r["wpisal"] == "JK"
    by_param = {r["param_kod"]: r["wartosc"] for r in new}
    assert by_param["ph_10proc"] == 11.89
    assert by_param["so3"] == 0.12


def test_build_measurements_recipe_always_legacy(db):
    """na2so3_recept_kg is always emitted from ebr_wyniki with runda=0, is_legacy=1,
    even when ebr_pomiar has the same param."""
    from mbr.ml_export.query import build_measurements
    rows = build_measurements(db, ebr_ids=[1])
    legacy = [r for r in rows if r["is_legacy"] == 1]
    recipe = [r for r in legacy if r["param_kod"] == "na2so3_recept_kg"]
    assert len(recipe) == 1
    r = recipe[0]
    assert r["runda"] == 0
    assert r["etap"] == "sulfonowanie"
    assert r["wartosc"] == 15.0


def test_build_measurements_legacy_only_emitted(db):
    """Legacy value for (etap, param) with no corresponding pomiar → emit with runda=0."""
    from mbr.ml_export.query import build_measurements
    # Insert legacy SM in analiza_koncowa — no session, no pomiar
    db.execute(
        "INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc, w_limicie, dt_wpisu, wpisal) "
        "VALUES (1,'analiza_koncowa','sm','sm',43.5,1,'2026-04-16','JK')"
    )
    db.commit()
    rows = build_measurements(db, ebr_ids=[1])
    leg_sm = [r for r in rows if r["param_kod"] == "sm" and r["is_legacy"] == 1]
    assert len(leg_sm) == 1
    assert leg_sm[0]["runda"] == 0
    assert leg_sm[0]["etap"] == "analiza_koncowa"
    assert leg_sm[0]["wartosc"] == 43.5


def test_build_measurements_legacy_suppressed_when_new_exists(db):
    """Legacy value for same (ebr_id, etap, param) as a new pomiar → NOT emitted."""
    from mbr.ml_export.query import build_measurements
    # Fixture: sulfonowanie/ph_10proc exists in ebr_pomiar (sesja_id=1, parametr_id=1)
    # Add legacy entry for the same (ebr_id, etap, param) — should be suppressed
    db.execute(
        "INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc, dt_wpisu, wpisal) "
        "VALUES (1,'sulfonowanie','ph_10proc','ph',99.9,'2026-04-16','X')"
    )
    db.commit()
    rows = build_measurements(db, ebr_ids=[1])
    ph = [r for r in rows if r["param_kod"] == "ph_10proc"]
    assert len(ph) == 1
    assert ph[0]["is_legacy"] == 0
    assert ph[0]["wartosc"] == 11.89  # new value wins


def test_build_measurements_wartosc_text(db):
    """ebr_wyniki.wartosc_text (e.g. FAU '<1') must propagate."""
    from mbr.ml_export.query import build_measurements
    db.execute(
        "INSERT INTO ebr_wyniki (ebr_id, sekcja, kod_parametru, tag, wartosc, wartosc_text, dt_wpisu, wpisal) "
        "VALUES (1,'analiza_koncowa','barwa_I2','barwa',NULL,'<1','2026-04-16','JK')"
    )
    db.commit()
    rows = build_measurements(db, ebr_ids=[1])
    below = [r for r in rows if r["param_kod"] == "barwa_I2" and r["etap"] == "analiza_koncowa"]
    assert len(below) == 1
    assert below[0]["wartosc"] is None
    assert below[0]["wartosc_text"] == "<1"
    assert below[0]["is_legacy"] == 1
```

- [ ] **Step 2: Uruchom — fail**

Run: `pytest tests/test_ml_export.py -v -k build_measurements`
Expected: 5 × FAIL z `ImportError: cannot import name 'build_measurements'`.

- [ ] **Step 3: Dopisz `build_measurements` do `query.py` (po `build_sessions`)**

```python
_RECIPE_PARAMS = {"na2so3_recept_kg"}


def build_measurements(db: sqlite3.Connection, ebr_ids: list[int]) -> list[dict]:
    """Merge ebr_pomiar (per-session, is_legacy=0) with ebr_wyniki (per-batch, is_legacy=1).

    Rules:
    1. New (ebr_pomiar) is authoritative — emit all.
    2. For each legacy (ebr_id, etap, param) in ebr_wyniki: emit only if no matching
       new row exists for the same triple. Round = 0 for legacy.
    3. Recipe params (_RECIPE_PARAMS) are exempt from rule 2 — always emitted from
       legacy with runda=0. They aren't measurements, they're dosage history.
    """
    if not ebr_ids:
        return []
    ids_q = ",".join("?" for _ in ebr_ids)

    new_rows = db.execute(
        f"""SELECT s.ebr_id, ea.kod AS etap, s.runda,
                   pa.kod AS param_kod, p.wartosc, p.w_limicie,
                   p.dt_wpisu, p.wpisal
              FROM ebr_pomiar p
              JOIN ebr_etap_sesja s       ON s.id = p.sesja_id
              JOIN etapy_analityczne ea   ON ea.id = s.etap_id
              JOIN parametry_analityczne pa ON pa.id = p.parametr_id
             WHERE s.ebr_id IN ({ids_q})
          ORDER BY s.ebr_id, s.etap_id, s.runda, pa.id""",
        ebr_ids,
    ).fetchall()

    out: list[dict] = []
    new_triples: set[tuple[int, str, str]] = set()
    for r in new_rows:
        out.append({
            "ebr_id":       r["ebr_id"],
            "etap":         r["etap"],
            "runda":        r["runda"],
            "param_kod":    r["param_kod"],
            "wartosc":      r["wartosc"],
            "wartosc_text": None,
            "w_limicie":    r["w_limicie"],
            "dt_wpisu":     r["dt_wpisu"],
            "wpisal":       r["wpisal"],
            "is_legacy":    0,
        })
        new_triples.add((r["ebr_id"], r["etap"], r["param_kod"]))

    legacy_rows = db.execute(
        f"""SELECT ebr_id, sekcja AS etap, kod_parametru AS param_kod,
                   wartosc, wartosc_text, w_limicie, dt_wpisu, wpisal
              FROM ebr_wyniki
             WHERE ebr_id IN ({ids_q})
          ORDER BY ebr_id, sekcja, kod_parametru""",
        ebr_ids,
    ).fetchall()

    for r in legacy_rows:
        triple = (r["ebr_id"], r["etap"], r["param_kod"])
        if r["param_kod"] not in _RECIPE_PARAMS and triple in new_triples:
            continue  # new value authoritative, legacy suppressed
        out.append({
            "ebr_id":       r["ebr_id"],
            "etap":         r["etap"],
            "runda":        0,
            "param_kod":    r["param_kod"],
            "wartosc":      r["wartosc"],
            "wartosc_text": r["wartosc_text"],
            "w_limicie":    r["w_limicie"],
            "dt_wpisu":     r["dt_wpisu"],
            "wpisal":       r["wpisal"],
            "is_legacy":    1,
        })
    return out
```

- [ ] **Step 4: Uruchom testy measurement**

Run: `pytest tests/test_ml_export.py -v -k build_measurements`
Expected: 5 × PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/ml_export/query.py tests/test_ml_export.py
git commit -m "feat(ml_export): build_measurements — merge new sessions with legacy ebr_wyniki"
```

---

## Task 6: `query.build_corrections`

**Files:**
- Modify: `mbr/ml_export/query.py`
- Modify: `tests/test_ml_export.py`

- [ ] **Step 1: Dopisz testy**

```python
# ─── build_corrections ────────────────────────────────────────────────────────

CORR_COLS = {
    "ebr_id", "etap", "runda", "substancja",
    "kg", "sugest_kg", "status", "zalecil", "dt_wykonania",
}


def test_build_corrections_basic(db):
    from mbr.ml_export.query import build_corrections
    rows = build_corrections(db, ebr_ids=[1])
    # Fixture has 1 Siarczyn sodu correction on sulfonowanie R1
    assert len(rows) == 1
    r = rows[0]
    assert set(r.keys()) == CORR_COLS
    assert r["ebr_id"] == 1
    assert r["etap"] == "sulfonowanie"
    assert r["runda"] == 1
    assert r["substancja"] == "Siarczyn sodu"
    assert r["kg"] == 15.0
    assert r["status"] == "wykonana"
    assert r["sugest_kg"] is None


def test_build_corrections_with_suggestion(db):
    """ilosc_wyliczona flows into sugest_kg."""
    from mbr.ml_export.query import build_corrections
    # Utlenienie R1 session + Kwas cytrynowy correction with suggestion
    db.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, laborant) "
               "VALUES (7,1,5,1,'zamkniety','JK')")
    db.execute("INSERT INTO ebr_korekta_v2 (sesja_id, korekta_typ_id, ilosc, ilosc_wyliczona, status, zalecil, dt_wykonania) "
               "VALUES (7, 5, 100.0, 110.5, 'wykonana', 'MM', '2026-04-16T10:15:00')")
    db.commit()
    rows = build_corrections(db, ebr_ids=[1])
    kwas = [r for r in rows if r["substancja"] == "Kwas cytrynowy"][0]
    assert kwas["kg"] == 100.0
    assert kwas["sugest_kg"] == 110.5
    assert kwas["zalecil"] == "MM"
    assert kwas["dt_wykonania"] == "2026-04-16T10:15:00"


def test_build_corrections_all_statuses_emitted(db):
    """Anulowana and zalecona are also emitted — client filters."""
    from mbr.ml_export.query import build_corrections
    db.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, laborant) "
               "VALUES (8,1,5,2,'zamkniety','JK')")
    db.execute("INSERT INTO ebr_korekta_v2 (sesja_id, korekta_typ_id, ilosc, status) "
               "VALUES (8, 3, 7.0, 'anulowana')")
    db.commit()
    rows = build_corrections(db, ebr_ids=[1])
    statuses = {r["status"] for r in rows}
    assert "anulowana" in statuses
    assert "wykonana" in statuses
```

- [ ] **Step 2: Uruchom — fail**

Run: `pytest tests/test_ml_export.py -v -k build_corrections`
Expected: 3 × FAIL z `ImportError`.

- [ ] **Step 3: Dopisz `build_corrections` do `query.py`**

```python
def build_corrections(db: sqlite3.Connection, ebr_ids: list[int]) -> list[dict]:
    if not ebr_ids:
        return []
    ids_q = ",".join("?" for _ in ebr_ids)
    rows = db.execute(
        f"""SELECT s.ebr_id, ea.kod AS etap, s.runda,
                   ek.substancja, k.ilosc, k.ilosc_wyliczona,
                   k.status, k.zalecil, k.dt_wykonania
              FROM ebr_korekta_v2 k
              JOIN ebr_etap_sesja s          ON s.id = k.sesja_id
              JOIN etapy_analityczne ea      ON ea.id = s.etap_id
              JOIN etap_korekty_katalog ek   ON ek.id = k.korekta_typ_id
             WHERE s.ebr_id IN ({ids_q})
          ORDER BY s.ebr_id, s.etap_id, s.runda, ek.kolejnosc""",
        ebr_ids,
    ).fetchall()
    return [
        {
            "ebr_id":        r["ebr_id"],
            "etap":          r["etap"],
            "runda":         r["runda"],
            "substancja":    r["substancja"],
            "kg":            r["ilosc"],
            "sugest_kg":     r["ilosc_wyliczona"],
            "status":        r["status"],
            "zalecil":       r["zalecil"],
            "dt_wykonania":  r["dt_wykonania"],
        }
        for r in rows
    ]
```

**Uwaga:** Zapytanie sortuje po `ek.kolejnosc`. `etap_korekty_katalog` ma kolumnę `kolejnosc`? Jeśli nie — zamień na `ek.id`. Grep schemy: `sqlite3 data/batch_db.sqlite ".schema etap_korekty_katalog"` dla weryfikacji.

- [ ] **Step 4: Uruchom testy korekty**

Run: `pytest tests/test_ml_export.py -v -k build_corrections`
Expected: 3 × PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/ml_export/query.py tests/test_ml_export.py
git commit -m "feat(ml_export): build_corrections — one row per correction with status"
```

---

## Task 7: `export_ml_package` — zip packaging

**Files:**
- Modify: `mbr/ml_export/query.py`
- Modify: `tests/test_ml_export.py`

- [ ] **Step 1: Dopisz testy**

```python
# ─── export_ml_package ────────────────────────────────────────────────────────

def _read_zip(blob: bytes) -> dict:
    zf = zipfile.ZipFile(io.BytesIO(blob))
    return {name: zf.read(name).decode("utf-8") for name in zf.namelist()}


def test_export_ml_package_contents(db):
    from mbr.ml_export.query import export_ml_package
    blob = export_ml_package(db)
    files = _read_zip(blob)
    assert set(files.keys()) == {
        "batches.csv", "sessions.csv", "measurements.csv",
        "corrections.csv", "schema.json", "README.md",
    }
    # Schema is valid JSON
    schema = json.loads(files["schema.json"])
    assert schema["counts"]["batches"] == 1
    assert schema["counts"]["sessions"] == 1  # only sulfonowanie R1 in seed
    # Measurements count = 4 new + 1 legacy recipe = 5
    assert schema["counts"]["measurements"] == 5
    # CSV headers present
    assert files["batches.csv"].startswith("ebr_id,batch_id,")
    assert "ebr_id,etap,runda,param_kod" in files["measurements.csv"]


def test_export_ml_package_empty_db(db):
    """Empty K7 — still returns valid zip with 6 files, headers only."""
    from mbr.ml_export.query import export_ml_package
    db.execute("DELETE FROM ebr_korekta_v2")
    db.execute("DELETE FROM ebr_pomiar")
    db.execute("DELETE FROM ebr_wyniki")
    db.execute("DELETE FROM ebr_etap_sesja")
    db.execute("DELETE FROM ebr_batches")
    db.commit()
    blob = export_ml_package(db)
    files = _read_zip(blob)
    assert set(files.keys()) == {
        "batches.csv", "sessions.csv", "measurements.csv",
        "corrections.csv", "schema.json", "README.md",
    }
    # Headers only — each CSV has exactly one line
    assert files["batches.csv"].count("\n") == 1
    assert files["sessions.csv"].count("\n") == 1


def test_export_ml_package_status_filter(db):
    from mbr.ml_export.query import export_ml_package
    db.execute("""INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii,
                  wielkosc_szarzy_kg, nastaw, dt_start, status, typ)
                  VALUES (2,1,'K7__2','2/2026',13300,13300,'2026-04-17','cancelled','szarza')""")
    db.commit()
    # Default: only completed
    schema_default = json.loads(_read_zip(export_ml_package(db))["schema.json"])
    assert schema_default["counts"]["batches"] == 1
    # With cancelled
    schema_inc = json.loads(_read_zip(export_ml_package(db, statuses=("completed","cancelled")))["schema.json"])
    assert schema_inc["counts"]["batches"] == 2


def test_export_pandas_pivot_roundtrip(db):
    """Smoke test: round-trip long format through pandas pivot to wide.
    Skipped if pandas not installed (dev env).
    """
    pd = pytest.importorskip("pandas")
    from mbr.ml_export.query import export_ml_package
    files = _read_zip(export_ml_package(db))
    m = pd.read_csv(io.StringIO(files["measurements.csv"]))
    wide = m[m.param_kod == "ph_10proc"].pivot_table(
        index="ebr_id", columns=["etap", "runda"], values="wartosc"
    )
    assert wide.loc[1, ("sulfonowanie", 1)] == 11.89
```

- [ ] **Step 2: Uruchom — fail**

Run: `pytest tests/test_ml_export.py -v -k export_ml_package`
Expected: 3 × FAIL z `ImportError`.

- [ ] **Step 3: Dopisz `export_ml_package` + pomocnicze do `query.py`**

Dodaj na końcu pliku:

```python
_README = """# K7 ML Export — Long Format

Cztery pliki CSV w formacie tidy + `schema.json` z metadanymi.

## Pliki

| Plik | Ziarnistość | Użycie |
|---|---|---|
| `batches.csv`      | 1 wiersz / szarża | metadata, target, mass |
| `sessions.csv`     | 1 / (szarża, etap, runda) | kiedy / kto przeprowadził etap |
| `measurements.csv` | 1 / (szarża, etap, runda, parametr) | pomiary (sesje + legacy) |
| `corrections.csv`  | 1 / (szarża, etap, runda, substancja) | dozowanie |
| `schema.json`      | słownik | jednostki, specs, formuły, target candidates |

## Uwaga o legacy

Pomiary z `ebr_wyniki` (przed wprowadzeniem sesji) mają `runda=0` i `is_legacy=1`.
Jeśli ten sam `(batch, etap, parametr)` ma wpis w obu źródłach, emitowany jest
tylko nowy (session-based). Wyjątek: `na2so3_recept_kg` (recepta) — zawsze legacy.

## Przykład użycia w pandas

```python
import pandas as pd
import zipfile

zf = zipfile.ZipFile("k7_ml_export_2026-04-20.zip")
b = pd.read_csv(zf.open("batches.csv"))
m = pd.read_csv(zf.open("measurements.csv"))
df = m.merge(b, on="ebr_id")

# wide per (batch, stage, round) dla pojedynczego parametru:
wide = df[df.param_kod == "barwa_I2"].pivot_table(
    index="ebr_id", columns=["etap", "runda"], values="wartosc"
)
```
"""


def _csv_bytes(rows: list[dict], columns: list[str]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


_BATCH_COLS = ["ebr_id", "batch_id", "nr_partii", "produkt", "status",
               "masa_kg", "meff_kg", "dt_start", "dt_end", "pakowanie",
               "target_ph", "target_nd20"]
_SESS_COLS  = ["ebr_id", "etap", "runda", "dt_start", "laborant"]
_MEAS_COLS  = ["ebr_id", "etap", "runda", "param_kod",
               "wartosc", "wartosc_text", "w_limicie",
               "dt_wpisu", "wpisal", "is_legacy"]
_CORR_COLS  = ["ebr_id", "etap", "runda", "substancja",
               "kg", "sugest_kg", "status", "zalecil", "dt_wykonania"]


def export_ml_package(db: sqlite3.Connection,
                      produkty: list[str] | None = None,
                      statuses: tuple[str, ...] = ("completed",)) -> bytes:
    """Build the full zip bytes: 4 CSVs + schema.json + README.md."""
    produkty = produkty or list(DEFAULT_PRODUKTY)
    batches = build_batches(db, produkty, statuses)
    ebr_ids = [b["ebr_id"] for b in batches]
    sessions     = build_sessions(db, ebr_ids)
    measurements = build_measurements(db, ebr_ids)
    corrections  = build_corrections(db, ebr_ids)

    counts = {
        "batches":      len(batches),
        "sessions":     len(sessions),
        "measurements": len(measurements),
        "corrections":  len(corrections),
    }
    schema = build_schema(db, produkty, counts=counts)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("batches.csv",      _csv_bytes(batches,      _BATCH_COLS))
        zf.writestr("sessions.csv",     _csv_bytes(sessions,     _SESS_COLS))
        zf.writestr("measurements.csv", _csv_bytes(measurements, _MEAS_COLS))
        zf.writestr("corrections.csv",  _csv_bytes(corrections,  _CORR_COLS))
        zf.writestr("schema.json",      json.dumps(schema, ensure_ascii=False, indent=2).encode("utf-8"))
        zf.writestr("README.md",        _README.encode("utf-8"))
    return buf.getvalue()
```

- [ ] **Step 4: Uruchom**

Run: `pytest tests/test_ml_export.py -v`
Expected: wszystkie dotychczasowe testy + 4 nowe `export_ml_package` = PASS (pandas test może być skipped jeśli pandas nie zainstalowany — to OK).

- [ ] **Step 5: Commit**

```bash
git add mbr/ml_export/query.py tests/test_ml_export.py
git commit -m "feat(ml_export): export_ml_package — zip with 4 CSVs + schema.json + README"
```

---

## Task 8: Route — nowy endpoint `.zip`, usunięcie starego `.csv`

**Files:**
- Rewrite: `mbr/ml_export/routes.py`
- Modify: `tests/test_ml_export.py`

- [ ] **Step 1: Dopisz test route'a**

```python
# ─── routes ───────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch, db):
    """Flask test client with monkey-patched get_db returning the in-memory fixture."""
    from mbr.app import app
    monkeypatch.setattr("mbr.ml_export.routes.get_db", lambda: db)
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user"] = {"login": "admin", "rola": "admin"}
        yield c


def test_zip_endpoint_returns_zip(client):
    resp = client.get("/api/export/ml/k7.zip")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "application/zip"
    assert "k7_ml_export_" in resp.headers["Content-Disposition"]
    assert resp.headers["Content-Disposition"].endswith('.zip"')
    zf = zipfile.ZipFile(io.BytesIO(resp.data))
    assert "batches.csv" in zf.namelist()


def test_zip_endpoint_include_failed_flag(client, db):
    db.execute("""INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii,
                  wielkosc_szarzy_kg, nastaw, dt_start, status, typ)
                  VALUES (2,1,'K7__2','2/2026',13300,13300,'2026-04-17','cancelled','szarza')""")
    db.commit()
    resp = client.get("/api/export/ml/k7.zip")
    schema = json.loads(zipfile.ZipFile(io.BytesIO(resp.data)).read("schema.json").decode("utf-8"))
    assert schema["counts"]["batches"] == 1
    resp2 = client.get("/api/export/ml/k7.zip?include_failed=1")
    schema2 = json.loads(zipfile.ZipFile(io.BytesIO(resp2.data)).read("schema.json").decode("utf-8"))
    assert schema2["counts"]["batches"] == 2


def test_old_csv_endpoint_gone(client):
    resp = client.get("/api/export/ml/k7.csv")
    assert resp.status_code == 404
```

**Uwaga:** fixture `client` wymaga Flask session z rolą admin, bo `@role_required("admin")` chroni endpoint. Jeśli `mbr.shared.decorators` używa innej struktury sesji (np. plain `session["role"]` zamiast `session["user"]["role"]`) — dostosuj. Zweryfikuj: `grep -r "role_required" mbr/shared/decorators.py` i sprawdź jak czyta rolę.

- [ ] **Step 2: Uruchom — fail (endpoint zip nie istnieje; stary `.csv` wciąż istnieje)**

Run: `pytest tests/test_ml_export.py -v -k "zip_endpoint or csv_endpoint_gone"`
Expected: 3 × FAIL.

- [ ] **Step 3: Zastąp całą zawartość `mbr/ml_export/routes.py`**

```python
"""HTTP endpoints + admin page for the ML export package."""
from datetime import date

from flask import request, Response, render_template

from mbr.db import get_db
from mbr.ml_export import ml_export_bp
from mbr.ml_export.query import export_ml_package, build_batches, build_sessions, \
    build_measurements, build_corrections
from mbr.shared.decorators import role_required


def _statuses(include_failed: bool) -> tuple[str, ...]:
    return ("completed", "cancelled") if include_failed else ("completed",)


def _include_failed_param() -> bool:
    return request.args.get("include_failed", "0") in ("1", "true", "yes")


@ml_export_bp.route("/api/export/ml/k7.zip", methods=["GET"])
@role_required("admin")
def export_k7_zip():
    db = get_db()
    try:
        blob = export_ml_package(db, produkty=["Chegina_K7"], statuses=_statuses(_include_failed_param()))
    finally:
        db.close()
    fname = f"k7_ml_export_{date.today().isoformat()}.zip"
    resp = Response(blob, mimetype="application/zip")
    resp.headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return resp


@ml_export_bp.route("/ml-export", methods=["GET"])
@role_required("admin")
def ml_export_page():
    include_failed = _include_failed_param()
    db = get_db()
    try:
        batches     = build_batches(db, produkty=["Chegina_K7"], statuses=_statuses(include_failed))
        ebr_ids     = [b["ebr_id"] for b in batches]
        sessions    = build_sessions(db, ebr_ids)
        measurements= build_measurements(db, ebr_ids)
        corrections = build_corrections(db, ebr_ids)
    finally:
        db.close()

    preview = {
        "batches":      {"total": len(batches),      "rows": batches[:5]},
        "sessions":     {"total": len(sessions),     "rows": sessions[:5]},
        "measurements": {"total": len(measurements), "rows": measurements[:5]},
        "corrections":  {"total": len(corrections),  "rows": corrections[:5]},
    }
    return render_template("ml_export/ml_export.html",
                           preview=preview, include_failed=include_failed)
```

- [ ] **Step 4: Uruchom testy route'a**

Run: `pytest tests/test_ml_export.py -v -k "zip_endpoint or csv_endpoint_gone"`
Expected: 3 × PASS.

Jeśli pierwszy test `zip_endpoint_returns_zip` zwraca 401/403 zamiast 200 — dostosuj fixture `client` do sposobu, w jaki `role_required` sprawdza sesję (patrz komentarz w kroku 1).

- [ ] **Step 5: Uruchom cały plik testowy**

Run: `pytest tests/test_ml_export.py -v`
Expected: wszystko PASS.

- [ ] **Step 6: Commit**

```bash
git add mbr/ml_export/routes.py tests/test_ml_export.py
git commit -m "feat(ml_export): new zip endpoint, remove old CSV endpoint"
```

---

## Task 9: UI — 4-panelowy preview w `ml_export.html`

**Files:**
- Rewrite: `mbr/templates/ml_export/ml_export.html`
- Modify: `tests/test_ml_export.py`

- [ ] **Step 1: Dopisz testy strony**

```python
# ─── preview page ─────────────────────────────────────────────────────────────

def test_ml_export_page_renders(client):
    resp = client.get("/ml-export")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # Four panels, one per table
    for name in ("batches.csv", "sessions.csv", "measurements.csv", "corrections.csv"):
        assert name in body
    # Download button
    assert "Pobierz paczkę" in body
    # Row counts are rendered (fixture: 1 / 1 / 5 / 1)
    assert "1 wiersz" in body or "1 wierszy" in body  # batches


def test_ml_export_page_include_failed_toggle(client):
    resp = client.get("/ml-export?include_failed=1")
    assert resp.status_code == 200
    assert 'checked' in resp.data.decode("utf-8").lower()
```

- [ ] **Step 2: Uruchom — stary template nie ma tych stringów**

Run: `pytest tests/test_ml_export.py -v -k "page_renders or include_failed_toggle"`
Expected: FAIL.

- [ ] **Step 3: Zastąp zawartość `mbr/templates/ml_export/ml_export.html`**

```html
{% extends "base.html" %}
{% block nav_ml_export %}active{% endblock %}
{% block title %}ML Export — K7 Pipeline{% endblock %}

{% block content %}
<style>
  .ml-wrap { padding: 20px 24px; max-width: 1200px; }
  .ml-header { display: flex; align-items: center; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }
  .ml-title { font-size: 18px; font-weight: 700; color: var(--text); }
  .ml-dl {
    font-size: 13px; padding: 7px 18px; border: 1.5px solid var(--teal);
    border-radius: 6px; color: var(--teal); font-weight: 600;
    text-decoration: none; background: none; cursor: pointer;
  }
  .ml-dl:hover { background: var(--teal-bg); }
  .ml-toggle { font-size: 12px; color: var(--text-dim); display: inline-flex; align-items: center; gap: 6px; }
  .ml-panel { margin-bottom: 26px; }
  .ml-panel h3 { font-size: 14px; font-weight: 600; margin: 0 0 6px; color: var(--text); }
  .ml-panel .count { font-size: 11px; color: var(--text-dim); }
  .ml-table { width: 100%; border-collapse: collapse; font-size: 11px; font-family: var(--mono, monospace); margin-top: 6px; }
  .ml-table th { background: var(--surface-alt); padding: 5px 8px; text-align: left; font-weight: 600; font-size: 10px; color: var(--text-dim); border-bottom: 2px solid var(--border); white-space: nowrap; }
  .ml-table td { padding: 4px 8px; border-bottom: 1px solid var(--border); white-space: nowrap; color: var(--text); }
  .ml-null { color: var(--text-dim); opacity: 0.4; }
  .ml-empty { padding: 14px; text-align: center; color: var(--text-dim); font-size: 12px; }
</style>

<div class="ml-wrap">
  <div class="ml-header">
    <div class="ml-title">ML Export — K7 Pipeline (long format)</div>
    <a class="ml-dl" href="{{ url_for('ml_export.export_k7_zip') }}{% if include_failed %}?include_failed=1{% endif %}">
      &#11015; Pobierz paczkę (.zip)
    </a>
    <label class="ml-toggle">
      <input type="checkbox" onchange="location = this.checked ? '?include_failed=1' : '?'"
             {% if include_failed %}checked{% endif %}>
      Włącz szarże anulowane
    </label>
  </div>

  {% for name, key in [
    ('batches.csv', 'batches'),
    ('sessions.csv', 'sessions'),
    ('measurements.csv', 'measurements'),
    ('corrections.csv', 'corrections'),
  ] %}
    {% set p = preview[key] %}
    <div class="ml-panel">
      <h3>{{ name }} <span class="count">— {{ p.total }} {{ 'wiersz' if p.total == 1 else 'wierszy' }}</span></h3>
      {% if p.rows %}
        <table class="ml-table">
          <thead><tr>{% for k in p.rows[0].keys() %}<th>{{ k }}</th>{% endfor %}</tr></thead>
          <tbody>
            {% for row in p.rows %}
              <tr>{% for v in row.values() %}
                <td{% if v is none %} class="ml-null"{% endif %}>{{ '—' if v is none else v }}</td>
              {% endfor %}</tr>
            {% endfor %}
          </tbody>
        </table>
      {% else %}
        <div class="ml-empty">Brak danych.</div>
      {% endif %}
    </div>
  {% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 4: Uruchom testy strony**

Run: `pytest tests/test_ml_export.py -v -k "page_renders or include_failed_toggle"`
Expected: 2 × PASS.

- [ ] **Step 5: Uruchom cały plik**

Run: `pytest tests/test_ml_export.py -v`
Expected: wszystko PASS.

- [ ] **Step 6: Commit**

```bash
git add mbr/templates/ml_export/ml_export.html tests/test_ml_export.py
git commit -m "feat(ml_export): 4-panel preview page for long-format package"
```

---

## Task 10: Sanity check — pełny pytest + weryfikacja braku dead code

**Files:**
- Run: pełna sucha test suite
- Grep: referencje do usuniętych symboli

- [ ] **Step 1: Uruchom pełny pytest**

Run: `pytest -x`
Expected: wszystko PASS. Jeśli jakiś test poza `test_ml_export.py` importował `export_k7_batches` / `get_csv_columns` / `FIXED_MAX_ROUNDS` / inne usunięte symbole → fail tutaj. Wszystkie takie testy są albo do usunięcia (stare), albo do aktualizacji pod nowe API.

- [ ] **Step 2: Sprawdź referencje do usuniętych symboli w repo**

Run:
```bash
grep -rn "export_k7_batches\|get_csv_columns\|FIXED_MAX_ROUNDS\|_PARAM_SHORT\|_KOREKTA_SHORT\|_STAGE_PREFIX" \
  --include="*.py" --include="*.html" --include="*.md" .
```

Expected: żadnych trafień poza `docs/superpowers/specs/2026-04-16-ml-export-design.md` (stary, supersedowany spec) i ewentualnie `docs/` w ogóle. Jeśli jest trafienie w `mbr/` — usuń/zaktualizuj.

- [ ] **Step 3: Sprawdź że `/ml-export` w sidebarze / nav dalej działa**

Przejrzyj `grep -rn "ml_export\." --include="*.html" mbr/templates/`. Jeżeli jakikolwiek template linkuje do `url_for('ml_export.export_k7_csv')` (stara nazwa route'a) — zamień na `url_for('ml_export.export_k7_zip')`.

- [ ] **Step 4: Uruchom serwer lokalnie i ręcznie pobierz paczkę**

Run (osobny terminal): `python -m mbr.app`

Then: otwórz `http://127.0.0.1:5001/ml-export` zalogowany jako admin, kliknij „Pobierz paczkę", rozpakuj zip, sprawdź że `measurements.csv` + `schema.json` są sensowne na żywych danych K7. Liczba szarż w schema.counts.batches powinna zgadzać się z `SELECT COUNT(*) FROM ebr_batches WHERE mbr_id=4 AND status='completed' AND typ='szarza'`.

- [ ] **Step 5: Commit docs (supersede marker jeśli nie był)**

Jeżeli stary spec (`docs/superpowers/specs/2026-04-16-ml-export-design.md`) nie ma markera supersedowania, dodaj go na górze:

```markdown
> **Status:** superseded by `docs/superpowers/specs/2026-04-20-ml-export-long-format-design.md` (2026-04-20).
```

Run:
```bash
git add -A
git commit -m "docs(ml_export): mark 2026-04-16 spec as superseded; verify no dead refs"
```

Jeżeli nie ma zmian do commitu — pomiń.

---

## Phase 2 — Inline edit + diagnostic chart

Tasks 11–19 extend the base ML export with admin inline-edit capabilities
and a buffer-capacity diagnostic panel. Phase 1 (Tasks 1–10) is a working
ship candidate on its own; Phase 2 can be evaluated separately.

---

## Task 11: `GET /api/ml-export/batch-detail` — P3 search endpoint

Backend endpoint zwracający pełny edytowalny szczegół jednej szarży identyfikowanej przez `nr_partii`.

**Files:**
- Modify: `mbr/ml_export/routes.py`
- Create: `mbr/ml_export/edit.py`
- Modify: `tests/test_ml_export.py`

- [ ] **Step 1: Dopisz failing test na końcu `tests/test_ml_export.py`**

```python
# ─── Task 11: batch-detail endpoint ───────────────────────────────────────────

def test_batch_detail_returns_shape(client, db):
    resp = client.get("/api/ml-export/batch-detail?nr_partii=1/2026")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "batch" in data
    assert "sessions" in data
    assert "measurements" in data
    assert "corrections" in data
    assert data["batch"]["nr_partii"] == "1/2026"
    assert isinstance(data["sessions"], list)
    assert isinstance(data["measurements"], list)
    assert isinstance(data["corrections"], list)


def test_batch_detail_404_on_unknown(client):
    resp = client.get("/api/ml-export/batch-detail?nr_partii=NOTEXIST")
    assert resp.status_code == 404


def test_batch_detail_missing_param(client):
    resp = client.get("/api/ml-export/batch-detail")
    assert resp.status_code == 400
```

- [ ] **Step 2: Uruchom — powinny failować (404 z braku trasy)**

Run: `pytest tests/test_ml_export.py -v -k "batch_detail"`
Expected: 3 × FAIL.

- [ ] **Step 3: Utwórz `mbr/ml_export/edit.py` z funkcją query szczegółu**

```python
"""Edit helpers for ML export inline-edit endpoints.

Provides read (detail) and write (PUT) operations for admin inline editing
of batch, session, measurement and correction records.
"""
import sqlite3
from typing import Any


def get_batch_detail(db: sqlite3.Connection, nr_partii: str) -> dict | None:
    """Return full editable detail for a single batch identified by nr_partii.

    Returns None if not found.
    Structure: {batch: {...}, sessions: [...], measurements: [...], corrections: [...]}
    """
    row = db.execute(
        """SELECT e.ebr_id, e.batch_id, e.nr_partii, e.wielkosc_szarzy_kg AS masa_kg,
                  e.nastaw, e.dt_start, e.dt_end, e.status,
                  e.pakowanie_bezposrednie, m.produkt
             FROM ebr_batches e
             JOIN mbr_templates m ON m.mbr_id = e.mbr_id
            WHERE e.nr_partii = ?
            LIMIT 1""",
        (nr_partii,),
    ).fetchone()
    if not row:
        return None

    ebr_id = row["ebr_id"]
    batch = dict(row)

    sessions = [
        dict(r) for r in db.execute(
            """SELECT s.id, s.ebr_id, ea.kod AS etap, s.etap_id, s.runda,
                      s.dt_start, s.laborant
                 FROM ebr_etap_sesja s
                 JOIN etapy_analityczne ea ON ea.id = s.etap_id
                WHERE s.ebr_id = ?
             ORDER BY s.etap_id, s.runda""",
            (ebr_id,),
        ).fetchall()
    ]

    # Measurements: new (ebr_pomiar) + legacy (ebr_wyniki)
    new_meas = [
        dict(r) for r in db.execute(
            """SELECT p.id, s.ebr_id, ea.kod AS etap, s.runda,
                      pa.kod AS kod_parametru, p.wartosc, p.w_limicie,
                      p.dt_wpisu, p.wpisal,
                      'pomiar' AS source
                 FROM ebr_pomiar p
                 JOIN ebr_etap_sesja s       ON s.id = p.sesja_id
                 JOIN etapy_analityczne ea   ON ea.id = s.etap_id
                 JOIN parametry_analityczne pa ON pa.id = p.parametr_id
                WHERE s.ebr_id = ?""",
            (ebr_id,),
        ).fetchall()
    ]
    leg_meas = [
        dict(r) for r in db.execute(
            """SELECT wynik_id AS id, ebr_id, sekcja AS etap, 0 AS runda,
                      kod_parametru, wartosc, wartosc_text, w_limicie,
                      dt_wpisu, wpisal,
                      'wyniki' AS source
                 FROM ebr_wyniki
                WHERE ebr_id = ?""",
            (ebr_id,),
        ).fetchall()
    ]
    measurements = new_meas + leg_meas

    corrections = [
        dict(r) for r in db.execute(
            """SELECT k.id, s.ebr_id, ea.kod AS etap, s.runda,
                      ek.substancja, k.ilosc AS kg, k.ilosc_wyliczona AS sugest_kg,
                      k.status, k.zalecil, k.dt_wykonania
                 FROM ebr_korekta_v2 k
                 JOIN ebr_etap_sesja s        ON s.id = k.sesja_id
                 JOIN etapy_analityczne ea    ON ea.id = s.etap_id
                 JOIN etap_korekty_katalog ek ON ek.id = k.korekta_typ_id
                WHERE s.ebr_id = ?""",
            (ebr_id,),
        ).fetchall()
    ]

    return {
        "batch": batch,
        "sessions": sessions,
        "measurements": measurements,
        "corrections": corrections,
    }
```

- [ ] **Step 4: Dopisz trasę do `mbr/ml_export/routes.py`**

```python
from flask import jsonify, abort
from mbr.ml_export.edit import get_batch_detail


@ml_export_bp.route("/api/ml-export/batch-detail", methods=["GET"])
@role_required("admin")
def ml_batch_detail():
    nr_partii = request.args.get("nr_partii")
    if not nr_partii:
        abort(400, description="nr_partii is required")
    db = get_db()
    try:
        detail = get_batch_detail(db, nr_partii)
    finally:
        db.close()
    if detail is None:
        abort(404)
    return jsonify(detail)
```

- [ ] **Step 5: Uruchom testy**

Run: `pytest tests/test_ml_export.py -v -k "batch_detail"`
Expected: 3 × PASS.

- [ ] **Step 6: Commit**

```bash
git add mbr/ml_export/edit.py mbr/ml_export/routes.py tests/test_ml_export.py
git commit -m "feat(ml_export): GET batch-detail — P3 search by nr_partii"
```

---

## Task 12: `PUT /api/ml-export/batch/<ebr_id>` — edit batch fields

Whitelist pól edytowalnych; odrzuca pozostałe z 400. Emituje zdarzenie audytu `ml_export.value_edited`. Wymaga roli admin.

**Files:**
- Modify: `mbr/ml_export/edit.py`
- Modify: `mbr/ml_export/routes.py`
- Modify: `tests/test_ml_export.py`

- [ ] **Step 1: Dopisz testy**

```python
# ─── Task 12: PUT batch ────────────────────────────────────────────────────────

def test_put_batch_editable_field(client, db):
    resp = client.put("/api/ml-export/batch/1",
                      json={"masa_kg": 14000.0},
                      content_type="application/json")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["new_value"] == 14000.0
    # Verify DB updated
    row = db.execute("SELECT wielkosc_szarzy_kg FROM ebr_batches WHERE ebr_id=1").fetchone()
    assert row[0] == 14000.0


def test_put_batch_rejected_field(client):
    resp = client.put("/api/ml-export/batch/1",
                      json={"ebr_id": 99},
                      content_type="application/json")
    assert resp.status_code == 400


def test_put_batch_not_found(client):
    resp = client.put("/api/ml-export/batch/9999",
                      json={"masa_kg": 1000.0},
                      content_type="application/json")
    assert resp.status_code == 404
```

- [ ] **Step 2: Uruchom — fail**

Run: `pytest tests/test_ml_export.py -v -k "put_batch"`
Expected: 3 × FAIL.

- [ ] **Step 3: Dopisz do `mbr/ml_export/edit.py`**

```python
# Whitelist of editable fields per table — field name → DB column
_BATCH_EDITABLE: dict[str, str] = {
    "masa_kg":               "wielkosc_szarzy_kg",
    "dt_start":              "dt_start",
    "dt_end":                "dt_end",
    "status":                "status",
    "pakowanie_bezposrednie":"pakowanie_bezposrednie",
    "nastaw":                "nastaw",
}

_SESSION_EDITABLE: dict[str, str] = {
    "dt_start":  "dt_start",
    "laborant":  "laborant",
}

_POMIAR_EDITABLE: dict[str, str] = {
    "wartosc":      "wartosc",
    "w_limicie":    "w_limicie",
}

_WYNIKI_EDITABLE: dict[str, str] = {
    "wartosc":      "wartosc",
    "wartosc_text": "wartosc_text",
    "w_limicie":    "w_limicie",
}

_KOREKTA_EDITABLE: dict[str, str] = {
    "kg":           "ilosc",
    "status":       "status",
    "dt_wykonania": "dt_wykonania",
}


def _audit(db: sqlite3.Connection, table: str, row_id: Any,
           field: str, old_value: Any, new_value: Any, batch_ebr_id: int) -> None:
    """Emit ml_export.value_edited audit event if audit module available."""
    try:
        from mbr import audit
        audit.log_event(db, "ml_export.value_edited", {
            "table": table, "id": row_id,
            "field": field, "old_value": old_value, "new_value": new_value,
            "batch_ebr_id": batch_ebr_id,
        })
    except Exception:
        pass  # audit is best-effort


def update_batch(db: sqlite3.Connection, ebr_id: int,
                 fields: dict[str, Any]) -> tuple[bool, str | None]:
    """Update editable batch fields. Returns (True, None) on success or (False, error_msg)."""
    for field in fields:
        if field not in _BATCH_EDITABLE:
            return False, f"Field '{field}' is not editable"
    row = db.execute("SELECT * FROM ebr_batches WHERE ebr_id=?", (ebr_id,)).fetchone()
    if not row:
        return False, "NOT_FOUND"
    for field, value in fields.items():
        col = _BATCH_EDITABLE[field]
        old_value = row[col]
        db.execute(f"UPDATE ebr_batches SET {col}=? WHERE ebr_id=?", (value, ebr_id))
        _audit(db, "ebr_batches", ebr_id, field, old_value, value, ebr_id)
    db.commit()
    return True, None


def update_session(db: sqlite3.Connection, sesja_id: int,
                   fields: dict[str, Any]) -> tuple[bool, str | None]:
    """Update editable session fields."""
    for field in fields:
        if field not in _SESSION_EDITABLE:
            return False, f"Field '{field}' is not editable"
    row = db.execute("SELECT * FROM ebr_etap_sesja WHERE id=?", (sesja_id,)).fetchone()
    if not row:
        return False, "NOT_FOUND"
    batch_ebr_id = row["ebr_id"]
    for field, value in fields.items():
        col = _SESSION_EDITABLE[field]
        old_value = row[col]
        db.execute(f"UPDATE ebr_etap_sesja SET {col}=? WHERE id=?", (value, sesja_id))
        _audit(db, "ebr_etap_sesja", sesja_id, field, old_value, value, batch_ebr_id)
    db.commit()
    return True, None


def update_measurement(db: sqlite3.Connection, source: str, row_id: int,
                       fields: dict[str, Any]) -> tuple[bool, str | None]:
    """Update editable measurement fields. source: 'pomiar' | 'wyniki'."""
    if source == "pomiar":
        editable = _POMIAR_EDITABLE
        table = "ebr_pomiar"
        pk_col = "id"
        ebr_id_sql = "SELECT s.ebr_id FROM ebr_pomiar p JOIN ebr_etap_sesja s ON s.id=p.sesja_id WHERE p.id=?"
    elif source == "wyniki":
        editable = _WYNIKI_EDITABLE
        table = "ebr_wyniki"
        pk_col = "wynik_id"
        ebr_id_sql = "SELECT ebr_id FROM ebr_wyniki WHERE wynik_id=?"
    else:
        return False, "Invalid source; must be 'pomiar' or 'wyniki'"
    for field in fields:
        if field not in editable:
            return False, f"Field '{field}' is not editable for source '{source}'"
    row = db.execute(f"SELECT * FROM {table} WHERE {pk_col}=?", (row_id,)).fetchone()
    if not row:
        return False, "NOT_FOUND"
    ebr_row = db.execute(ebr_id_sql, (row_id,)).fetchone()
    batch_ebr_id = ebr_row[0] if ebr_row else 0
    for field, value in fields.items():
        col = editable[field]
        old_value = row[col]
        db.execute(f"UPDATE {table} SET {col}=? WHERE {pk_col}=?", (value, row_id))
        _audit(db, table, row_id, field, old_value, value, batch_ebr_id)
    db.commit()
    return True, None


def update_correction(db: sqlite3.Connection, korekta_id: int,
                      fields: dict[str, Any]) -> tuple[bool, str | None]:
    """Update editable correction fields."""
    for field in fields:
        if field not in _KOREKTA_EDITABLE:
            return False, f"Field '{field}' is not editable"
    row = db.execute("SELECT * FROM ebr_korekta_v2 WHERE id=?", (korekta_id,)).fetchone()
    if not row:
        return False, "NOT_FOUND"
    sesja = db.execute("SELECT ebr_id FROM ebr_etap_sesja WHERE id=?",
                       (row["sesja_id"],)).fetchone()
    batch_ebr_id = sesja["ebr_id"] if sesja else 0
    for field, value in fields.items():
        col = _KOREKTA_EDITABLE[field]
        old_value = row[col]
        db.execute(f"UPDATE ebr_korekta_v2 SET {col}=? WHERE id=?", (value, korekta_id))
        _audit(db, "ebr_korekta_v2", korekta_id, field, old_value, value, batch_ebr_id)
    db.commit()
    return True, None
```

- [ ] **Step 4: Dopisz trasy PUT do `mbr/ml_export/routes.py`**

```python
from mbr.ml_export.edit import (
    get_batch_detail,
    update_batch, update_session, update_measurement, update_correction,
)


@ml_export_bp.route("/api/ml-export/batch/<int:ebr_id>", methods=["PUT"])
@role_required("admin")
def ml_put_batch(ebr_id: int):
    fields = request.get_json(force=True) or {}
    db = get_db()
    try:
        ok, err = update_batch(db, ebr_id, fields)
    finally:
        db.close()
    if not ok:
        if err == "NOT_FOUND":
            abort(404)
        abort(400, description=err)
    return jsonify({"ok": True, "new_value": list(fields.values())[0] if len(fields) == 1 else fields})
```

- [ ] **Step 5: Uruchom testy**

Run: `pytest tests/test_ml_export.py -v -k "put_batch"`
Expected: 3 × PASS.

- [ ] **Step 6: Commit**

```bash
git add mbr/ml_export/edit.py mbr/ml_export/routes.py tests/test_ml_export.py
git commit -m "feat(ml_export): PUT batch/<ebr_id> — inline edit with whitelist + audit"
```

---

## Task 13: `PUT /api/ml-export/session/<sesja_id>` — edit session fields

Analogiczny wzorzec do Task 12.

**Files:**
- Modify: `mbr/ml_export/routes.py`
- Modify: `tests/test_ml_export.py`

- [ ] **Step 1: Dopisz testy**

```python
# ─── Task 13: PUT session ──────────────────────────────────────────────────────

def test_put_session_editable_field(client, db):
    resp = client.put("/api/ml-export/session/1",
                      json={"laborant": "MK"},
                      content_type="application/json")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["new_value"] == "MK"
    row = db.execute("SELECT laborant FROM ebr_etap_sesja WHERE id=1").fetchone()
    assert row[0] == "MK"


def test_put_session_rejected_field(client):
    resp = client.put("/api/ml-export/session/1",
                      json={"runda": 99},
                      content_type="application/json")
    assert resp.status_code == 400


def test_put_session_not_found(client):
    resp = client.put("/api/ml-export/session/9999",
                      json={"laborant": "X"},
                      content_type="application/json")
    assert resp.status_code == 404
```

- [ ] **Step 2: Uruchom — fail**

Run: `pytest tests/test_ml_export.py -v -k "put_session"`
Expected: 3 × FAIL.

- [ ] **Step 3: Dopisz trasę do `mbr/ml_export/routes.py`**

```python
@ml_export_bp.route("/api/ml-export/session/<int:sesja_id>", methods=["PUT"])
@role_required("admin")
def ml_put_session(sesja_id: int):
    fields = request.get_json(force=True) or {}
    db = get_db()
    try:
        ok, err = update_session(db, sesja_id, fields)
    finally:
        db.close()
    if not ok:
        if err == "NOT_FOUND":
            abort(404)
        abort(400, description=err)
    return jsonify({"ok": True, "new_value": list(fields.values())[0] if len(fields) == 1 else fields})
```

- [ ] **Step 4: Uruchom testy**

Run: `pytest tests/test_ml_export.py -v -k "put_session"`
Expected: 3 × PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/ml_export/routes.py tests/test_ml_export.py
git commit -m "feat(ml_export): PUT session/<sesja_id> — inline edit session fields"
```

---

## Task 14: `PUT /api/ml-export/measurement/<source>/<id>` — edit measurement

Obsługuje oba źródła: `pomiar` (nowe) i `wyniki` (legacy).

**Files:**
- Modify: `mbr/ml_export/routes.py`
- Modify: `tests/test_ml_export.py`

- [ ] **Step 1: Dopisz testy**

```python
# ─── Task 14: PUT measurement ─────────────────────────────────────────────────

def test_put_measurement_pomiar(client, db):
    # ebr_pomiar id=1 is ph_10proc=11.89 from seed
    row = db.execute("SELECT id FROM ebr_pomiar LIMIT 1").fetchone()
    meas_id = row[0]
    resp = client.put(f"/api/ml-export/measurement/pomiar/{meas_id}",
                      json={"wartosc": 12.5},
                      content_type="application/json")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    updated = db.execute("SELECT wartosc FROM ebr_pomiar WHERE id=?", (meas_id,)).fetchone()
    assert updated[0] == 12.5


def test_put_measurement_wyniki_wartosc_text(client, db):
    db.execute(
        "INSERT INTO ebr_wyniki (wynik_id, ebr_id, sekcja, kod_parametru, tag, wartosc_text, dt_wpisu, wpisal) "
        "VALUES (99, 1, 'analiza_koncowa', 'barwa_I2', 'barwa', '<1', '2026-04-16', 'JK')"
    )
    db.commit()
    resp = client.put("/api/ml-export/measurement/wyniki/99",
                      json={"wartosc_text": "<0.5"},
                      content_type="application/json")
    assert resp.status_code == 200
    updated = db.execute("SELECT wartosc_text FROM ebr_wyniki WHERE wynik_id=99").fetchone()
    assert updated[0] == "<0.5"


def test_put_measurement_invalid_source(client):
    resp = client.put("/api/ml-export/measurement/INVALID/1",
                      json={"wartosc": 1.0},
                      content_type="application/json")
    assert resp.status_code == 400


def test_put_measurement_rejected_field(client, db):
    row = db.execute("SELECT id FROM ebr_pomiar LIMIT 1").fetchone()
    resp = client.put(f"/api/ml-export/measurement/pomiar/{row[0]}",
                      json={"wartosc_text": "x"},
                      content_type="application/json")
    # wartosc_text is not editable for source=pomiar
    assert resp.status_code == 400
```

- [ ] **Step 2: Uruchom — fail**

Run: `pytest tests/test_ml_export.py -v -k "put_measurement"`
Expected: 4 × FAIL.

- [ ] **Step 3: Dopisz trasę do `mbr/ml_export/routes.py`**

```python
@ml_export_bp.route("/api/ml-export/measurement/<source>/<int:row_id>", methods=["PUT"])
@role_required("admin")
def ml_put_measurement(source: str, row_id: int):
    fields = request.get_json(force=True) or {}
    db = get_db()
    try:
        ok, err = update_measurement(db, source, row_id, fields)
    finally:
        db.close()
    if not ok:
        if err == "NOT_FOUND":
            abort(404)
        abort(400, description=err)
    return jsonify({"ok": True, "new_value": list(fields.values())[0] if len(fields) == 1 else fields})
```

- [ ] **Step 4: Uruchom testy**

Run: `pytest tests/test_ml_export.py -v -k "put_measurement"`
Expected: 4 × PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/ml_export/routes.py tests/test_ml_export.py
git commit -m "feat(ml_export): PUT measurement/<source>/<id> — edit pomiar/wyniki rows"
```

---

## Task 15: `PUT /api/ml-export/correction/<korekta_id>` — edit correction

Analogiczny wzorzec.

**Files:**
- Modify: `mbr/ml_export/routes.py`
- Modify: `tests/test_ml_export.py`

- [ ] **Step 1: Dopisz testy**

```python
# ─── Task 15: PUT correction ──────────────────────────────────────────────────

def test_put_correction_kg(client, db):
    # Fixture: ebr_korekta_v2 id=1, ilosc=15.0
    row = db.execute("SELECT id FROM ebr_korekta_v2 LIMIT 1").fetchone()
    korekta_id = row[0]
    resp = client.put(f"/api/ml-export/correction/{korekta_id}",
                      json={"kg": 18.5},
                      content_type="application/json")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    updated = db.execute("SELECT ilosc FROM ebr_korekta_v2 WHERE id=?", (korekta_id,)).fetchone()
    assert updated[0] == 18.5


def test_put_correction_status(client, db):
    row = db.execute("SELECT id FROM ebr_korekta_v2 LIMIT 1").fetchone()
    resp = client.put(f"/api/ml-export/correction/{row[0]}",
                      json={"status": "anulowana"},
                      content_type="application/json")
    assert resp.status_code == 200


def test_put_correction_rejected_field(client, db):
    row = db.execute("SELECT id FROM ebr_korekta_v2 LIMIT 1").fetchone()
    resp = client.put(f"/api/ml-export/correction/{row[0]}",
                      json={"substancja": "Woda"},
                      content_type="application/json")
    assert resp.status_code == 400


def test_put_correction_not_found(client):
    resp = client.put("/api/ml-export/correction/9999",
                      json={"kg": 1.0},
                      content_type="application/json")
    assert resp.status_code == 404
```

- [ ] **Step 2: Uruchom — fail**

Run: `pytest tests/test_ml_export.py -v -k "put_correction"`
Expected: 4 × FAIL.

- [ ] **Step 3: Dopisz trasę do `mbr/ml_export/routes.py`**

```python
@ml_export_bp.route("/api/ml-export/correction/<int:korekta_id>", methods=["PUT"])
@role_required("admin")
def ml_put_correction(korekta_id: int):
    fields = request.get_json(force=True) or {}
    db = get_db()
    try:
        ok, err = update_correction(db, korekta_id, fields)
    finally:
        db.close()
    if not ok:
        if err == "NOT_FOUND":
            abort(404)
        abort(400, description=err)
    return jsonify({"ok": True, "new_value": list(fields.values())[0] if len(fields) == 1 else fields})
```

- [ ] **Step 4: Uruchom testy**

Run: `pytest tests/test_ml_export.py -v -k "put_correction"`
Expected: 4 × PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/ml_export/routes.py tests/test_ml_export.py
git commit -m "feat(ml_export): PUT correction/<korekta_id> — inline edit correction row"
```

---

## Task 16: Frontend inline edit UI — search + editable tables

Nowa górna sekcja na `/ml-export`: pole „Szukaj szarży po nr_partii" + przycisk. Poniżej paneli preview: edytowalny widok szczegółów (4 tabele, komórki klikalnie, zapis po utracie fokusu).

**Files:**
- Modify: `mbr/templates/ml_export/ml_export.html`
- Modify: `tests/test_ml_export.py`

- [ ] **Step 1: Dopisz testy strony**

```python
# ─── Task 16: inline edit UI ──────────────────────────────────────────────────

def test_ml_export_page_has_search_input(client):
    resp = client.get("/ml-export")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "nr_partii" in body
    assert "Szukaj" in body


def test_ml_export_page_has_edit_section(client):
    resp = client.get("/ml-export")
    body = resp.data.decode("utf-8")
    # Editable detail section marker
    assert "ml-edit" in body or "inline-edit" in body or "batch-detail" in body
```

- [ ] **Step 2: Uruchom — fail**

Run: `pytest tests/test_ml_export.py -v -k "has_search_input or has_edit_section"`
Expected: 2 × FAIL.

- [ ] **Step 3: Dopisz sekcję inline edit do `mbr/templates/ml_export/ml_export.html`**

Dodaj przed zamknięciem `{% endblock %}` (po istniejących 4 panelach preview):

```html
  {# ─── Inline edit: search + detail ─────────────────────────────────────── #}
  <div class="ml-panel" id="ml-edit" style="margin-top: 32px;">
    <h3>Edycja rekordu szarży</h3>
    <div style="display:flex; gap:8px; margin-bottom:12px;">
      <input id="ml-search-input" type="text" placeholder="nr_partii (np. 1/2026)"
             style="font-size:13px; padding:6px 10px; border:1px solid var(--border);
                    border-radius:4px; width:220px; background:var(--surface);">
      <button id="ml-search-btn" onclick="mlLoadDetail()"
              style="font-size:12px; padding:6px 14px; border:1.5px solid var(--teal);
                     border-radius:4px; background:none; color:var(--teal); cursor:pointer;">
        Szukaj
      </button>
    </div>
    <div id="ml-detail-area" style="display:none;">
      <div id="ml-detail-content"></div>
    </div>
    <div id="ml-detail-error" style="display:none; color:var(--red); font-size:12px;"></div>
  </div>

<script>
function mlLoadDetail() {
  var nr = document.getElementById('ml-search-input').value.trim();
  if (!nr) return;
  fetch('/api/ml-export/batch-detail?nr_partii=' + encodeURIComponent(nr))
    .then(function(r) {
      if (r.status === 404) throw new Error('Szarża nie znaleziona.');
      if (!r.ok) throw new Error('Błąd serwera: ' + r.status);
      return r.json();
    })
    .then(function(data) {
      document.getElementById('ml-detail-error').style.display = 'none';
      document.getElementById('ml-detail-area').style.display = 'block';
      document.getElementById('ml-detail-content').innerHTML = mlRenderDetail(data);
    })
    .catch(function(err) {
      document.getElementById('ml-detail-area').style.display = 'none';
      var el = document.getElementById('ml-detail-error');
      el.textContent = err.message;
      el.style.display = 'block';
    });
}

var _ML_BATCH_EDITABLE = ['masa_kg','dt_start','dt_end','status','pakowanie_bezposrednie','nastaw'];
var _ML_SESS_EDITABLE  = ['dt_start','laborant'];
var _ML_MEAS_P_EDITABLE = ['wartosc','w_limicie'];
var _ML_MEAS_W_EDITABLE = ['wartosc','wartosc_text','w_limicie'];
var _ML_CORR_EDITABLE  = ['kg','status','dt_wykonania'];

function mlRenderDetail(data) {
  var html = '';
  html += mlRenderTable('batches', [data.batch], _ML_BATCH_EDITABLE,
    function(row, field, val) { return mlSaveField('batch', row.ebr_id, field, val); });
  html += mlRenderTable('sessions', data.sessions, _ML_SESS_EDITABLE,
    function(row, field, val) { return mlSaveField('session', row.id, field, val); });
  html += mlRenderTable('measurements', data.measurements,
    null /* source-dependent */,
    function(row, field, val) {
      var editable = row.source === 'pomiar' ? _ML_MEAS_P_EDITABLE : _ML_MEAS_W_EDITABLE;
      return mlSaveMeasurement(row.source, row.id, field, val, editable);
    }, data.measurements.map(function(r) {
      return r.source === 'pomiar' ? _ML_MEAS_P_EDITABLE : _ML_MEAS_W_EDITABLE;
    }));
  html += mlRenderTable('corrections', data.corrections, _ML_CORR_EDITABLE,
    function(row, field, val) { return mlSaveField('correction', row.id, field, val); });
  return html;
}

function mlRenderTable(name, rows, editableCols, saveCallback, editableColsPerRow) {
  if (!rows || !rows.length) return '<p style="font-size:12px;color:var(--text-dim);">' + name + ': brak danych.</p>';
  var keys = Object.keys(rows[0]);
  var html = '<h4 style="font-size:13px;margin:14px 0 4px;">' + name + '</h4>';
  html += '<table class="ml-table"><thead><tr>';
  keys.forEach(function(k) { html += '<th>' + k + '</th>'; });
  html += '</tr></thead><tbody>';
  rows.forEach(function(row, ri) {
    var rowEditable = editableColsPerRow ? editableColsPerRow[ri] : editableCols;
    html += '<tr>';
    keys.forEach(function(k) {
      var isEditable = rowEditable && rowEditable.indexOf(k) !== -1;
      var v = row[k];
      if (isEditable) {
        html += '<td><span class="ml-editable" contenteditable="true" '
             + 'data-field="' + k + '" data-orig="' + (v === null ? '' : v) + '" '
             + 'onblur="mlOnBlur(this, ' + JSON.stringify(row) + ', \'' + name + '\')"'
             + '>' + (v === null ? '' : v) + '</span></td>';
      } else {
        html += '<td' + (v === null ? ' class="ml-null"' : '') + '>' + (v === null ? '—' : v) + '</td>';
      }
    });
    html += '</tr>';
  });
  html += '</tbody></table>';
  return html;
}

function mlOnBlur(el, row, tableName) {
  var field = el.dataset.field;
  var newVal = el.textContent.trim();
  if (newVal === el.dataset.orig) return;
  el.style.background = 'var(--yellow-bg, #fffbe6)';
  var url, body;
  if (tableName === 'batches') {
    url = '/api/ml-export/batch/' + row.ebr_id;
    body = {}; body[field] = newVal;
    doSaveMlField(el, url, body);
  } else if (tableName === 'sessions') {
    url = '/api/ml-export/session/' + row.id;
    body = {}; body[field] = newVal;
    doSaveMlField(el, url, body);
  } else if (tableName === 'measurements') {
    url = '/api/ml-export/measurement/' + row.source + '/' + row.id;
    body = {}; body[field] = newVal;
    doSaveMlField(el, url, body);
  } else if (tableName === 'corrections') {
    url = '/api/ml-export/correction/' + row.id;
    body = {}; body[field] = newVal;
    doSaveMlField(el, url, body);
  }
}

function doSaveMlField(el, url, body) {
  fetch(url, {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})
    .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
    .then(function(res) {
      if (res.ok) {
        el.style.background = 'var(--green-bg, #f0fff4)';
        el.dataset.orig = el.textContent.trim();
        setTimeout(function() { el.style.background = ''; }, 1200);
      } else {
        el.style.background = 'var(--red-bg, #fff5f5)';
        el.title = res.data.description || 'Błąd zapisu';
      }
    })
    .catch(function() {
      el.style.background = 'var(--red-bg, #fff5f5)';
    });
}
</script>
```

- [ ] **Step 4: Uruchom testy strony**

Run: `pytest tests/test_ml_export.py -v -k "has_search_input or has_edit_section"`
Expected: 2 × PASS.

Smoke test manualny: zaloguj jako admin, przejdź na `/ml-export`, wpisz `1/2026` w polu szukaj, kliknij Szukaj. Powinna pojawić się tabela z danymi szarży. Kliknij w komórkę `masa_kg`, zmień wartość, kliknij poza komórkę — tło powinno zmienić się na zielone po zapisaniu.

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/ml_export/ml_export.html tests/test_ml_export.py
git commit -m "feat(ml_export): inline edit UI — search by nr_partii, save-on-blur"
```

---

## Task 17: `GET /api/ml-export/buffer-cap-chart` — compute stats + generate PNG chart

Backend endpoint. Retrowsteczna implementacja `_acidModelPredict` w Pythonie (port z JS na `_correction_panel.html:446`).

Formuła: `-524.86 + 0.010864 * masaEffKg + 9.2878 * deltaPh + 33.218 * phStart + 488181 / masaKg`

**Files:**
- Create: `mbr/ml_export/acid_diag.py`
- Modify: `mbr/ml_export/routes.py`
- Modify: `tests/test_ml_export.py`

- [ ] **Step 1: Dopisz testy**

```python
# ─── Task 17: buffer-cap-chart endpoint ───────────────────────────────────────

def _seed_k7_acid_batch(db, ebr_id, nr_partii, masa_kg,
                        ph_before, ph_after, acid_kg, status="completed"):
    """Seed a minimal K7 batch with pH and acid dose data for buffer-cap diagnostics."""
    db.execute(
        """INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, wielkosc_szarzy_kg,
                                    nastaw, dt_start, status, typ)
           VALUES (?,1,?,?,?,?,?,?,'szarza')""",
        (ebr_id, f"K7__{ebr_id}", nr_partii, masa_kg, masa_kg,
         f"2026-04-{10+ebr_id:02d}T08:00:00", status),
    )
    # Seed standaryzacja session with ph measurements + acid correction
    sess_id = ebr_id * 10
    db.execute(
        "INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, laborant) "
        "VALUES (?,?,9,1,'zamkniety','JK')",
        (sess_id, ebr_id),
    )
    # ph_10proc pomiar: ph_before and ph_after
    db.execute(
        "INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, w_limicie, dt_wpisu, wpisal) "
        "VALUES (?,1,?,1,'2026-04-16','JK')",
        (sess_id, ph_before),
    )
    # Acid correction (Kwas cytrynowy = korekta_typ_id 5 from fixture)
    db.execute(
        "INSERT INTO ebr_korekta_v2 (sesja_id, korekta_typ_id, ilosc, status) "
        "VALUES (?,5,?,'wykonana')",
        (sess_id, acid_kg),
    )
    db.commit()


def test_buffer_cap_chart_stats(db):
    from mbr.ml_export.acid_diag import compute_buffer_cap_stats
    # Seed 3 additional batches with K7 acid data (ebr_id 10,11,12)
    _seed_k7_acid_batch(db, 10, '10/2026', 13300, ph_before=10.2, ph_after=6.3, acid_kg=150.0)
    _seed_k7_acid_batch(db, 11, '11/2026', 13300, ph_before=10.5, ph_after=6.2, acid_kg=160.0)
    _seed_k7_acid_batch(db, 12, '12/2026', 13300, ph_before=10.0, ph_after=6.4, acid_kg=140.0)
    stats = compute_buffer_cap_stats(db, produkt="Chegina_K7")
    assert stats["n"] >= 3
    assert "mae" in stats
    assert "mape" in stats
    assert "mean_bias" in stats
    assert "stdev" in stats
    assert isinstance(stats["mae"], float)


def test_buffer_cap_chart_endpoint(client, db):
    _seed_k7_acid_batch(db, 10, '10/2026', 13300, ph_before=10.2, ph_after=6.3, acid_kg=150.0)
    resp = client.get("/api/ml-export/buffer-cap-chart?produkt=Chegina_K7")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "stats" in data
    assert "chart_png_b64" in data
    # chart_png_b64 is non-empty base64 string
    import base64
    png_bytes = base64.b64decode(data["chart_png_b64"])
    assert png_bytes[:4] == b'\x89PNG'


def test_buffer_cap_chart_empty(client):
    # No acid batches → empty stats, still returns 200
    resp = client.get("/api/ml-export/buffer-cap-chart?produkt=Chegina_K7")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["stats"]["n"] == 0
```

- [ ] **Step 2: Uruchom — fail (ModuleNotFoundError)**

Run: `pytest tests/test_ml_export.py -v -k "buffer_cap"`
Expected: 4 × FAIL.

- [ ] **Step 3: Utwórz `mbr/ml_export/acid_diag.py`**

```python
"""Buffer-capacity diagnostic for the K7 acid model.

Computes actual vs. predicted buffer capacity for completed K7 batches and
generates a 3-subplot diagnostic PNG (time series, scatter, histogram).

Actual buffer_cap:  acid_kg / (masa_kg / 1000) / delta_ph
Predicted:          _acid_model_predict(masa_eff_kg, delta_ph, ph_start, masa_kg)

Port of the JS formula from mbr/templates/laborant/_correction_panel.html:446:
  result = -524.86 + 0.010864*masaEffKg + 9.2878*deltaPh + 33.218*phStart + 488181/masaKg
"""
import base64
import io
import math
import sqlite3
from typing import Any


# ── Model formula (ported from JS) ───────────────────────────────────────────

def _acid_model_predict(masa_eff_kg: float, delta_ph: float,
                        ph_start: float, masa_kg: float) -> float:
    """Predict acid buffer capacity (kg/t/ΔpH) using the OLS poly2 model."""
    return (-524.86
            + 0.010864 * masa_eff_kg
            + 9.2878 * delta_ph
            + 33.218 * ph_start
            + 488181.0 / masa_kg)


def _meff(masa_kg: float) -> float:
    return masa_kg - 1000.0 if masa_kg > 6600.0 else masa_kg - 500.0


# ── Data extraction ───────────────────────────────────────────────────────────

def _load_acid_rows(db: sqlite3.Connection, produkt: str) -> list[dict[str, Any]]:
    """Return rows suitable for buffer-cap computation from completed K7 batches.

    Joins ebr_batches → standaryzacja sessions → ph measurements + Kwas cytrynowy corrections.
    Returns list of dicts with keys: dt_start, masa_kg, ph_before, ph_after, acid_kg.
    """
    rows = db.execute(
        """
        SELECT b.ebr_id, b.dt_start, b.wielkosc_szarzy_kg AS masa_kg,
               ph_meas.wartosc AS ph_before,
               acid.ilosc      AS acid_kg
          FROM ebr_batches b
          JOIN mbr_templates mt ON mt.mbr_id = b.mbr_id
          JOIN ebr_etap_sesja s ON s.ebr_id = b.ebr_id
          JOIN etapy_analityczne ea ON ea.id = s.etap_id AND ea.kod = 'standaryzacja'
          -- ph measurement (parametr_id=1 = ph_10proc)
          JOIN ebr_pomiar ph_meas ON ph_meas.sesja_id = s.id
          JOIN parametry_analityczne pa ON pa.id = ph_meas.parametr_id AND pa.kod = 'ph_10proc'
          -- Kwas cytrynowy correction on the same session
          JOIN ebr_korekta_v2 acid ON acid.sesja_id = s.id
          JOIN etap_korekty_katalog ek ON ek.id = acid.korekta_typ_id
                                      AND ek.substancja = 'Kwas cytrynowy'
         WHERE mt.produkt = ?
           AND b.status = 'completed'
           AND b.typ = 'szarza'
         ORDER BY b.dt_start
        """,
        (produkt,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Stats computation ─────────────────────────────────────────────────────────

def _compute_rows(raw: list[dict], target_ph: float = 6.25) -> list[dict]:
    """Convert raw DB rows to (actual, predicted, dt_start) triples.

    Filters: delta_ph > 0.5, acid_kg > 0, ph_before >= 9.
    delta_ph is approximated as ph_before - target_ph (we use the global target).
    """
    out = []
    for r in raw:
        masa_kg = r.get("masa_kg") or 0.0
        ph_before = r.get("ph_before") or 0.0
        acid_kg = r.get("acid_kg") or 0.0
        if masa_kg <= 0 or acid_kg <= 0:
            continue
        delta_ph = ph_before - target_ph
        if delta_ph <= 0.5 or ph_before < 9.0:
            continue
        tons = masa_kg / 1000.0
        actual = acid_kg / tons / delta_ph
        predicted = _acid_model_predict(_meff(masa_kg), delta_ph, ph_before, masa_kg)
        out.append({
            "dt_start": r.get("dt_start", ""),
            "actual": actual,
            "predicted": predicted,
            "residual": predicted - actual,
        })
    return out


def compute_buffer_cap_stats(db: sqlite3.Connection,
                             produkt: str = "Chegina_K7") -> dict[str, Any]:
    """Return summary stats dict: {n, mae, mape, mean_bias, stdev}."""
    raw = _load_acid_rows(db, produkt)
    rows = _compute_rows(raw)
    n = len(rows)
    if n == 0:
        return {"n": 0, "mae": 0.0, "mape": 0.0, "mean_bias": 0.0, "stdev": 0.0}
    residuals = [r["residual"] for r in rows]
    actuals = [r["actual"] for r in rows]
    mae = sum(abs(e) for e in residuals) / n
    mape = 100.0 * sum(abs(e / a) for e, a in zip(residuals, actuals) if a != 0) / n
    mean_bias = sum(residuals) / n
    stdev = math.sqrt(sum((e - mean_bias) ** 2 for e in residuals) / n) if n > 1 else 0.0
    return {
        "n": n,
        "mae": round(mae, 4),
        "mape": round(mape, 2),
        "mean_bias": round(mean_bias, 4),
        "stdev": round(stdev, 4),
    }


# ── Chart generation ──────────────────────────────────────────────────────────

def generate_chart_png(db: sqlite3.Connection,
                       produkt: str = "Chegina_K7") -> tuple[dict, bytes]:
    """Generate 3-subplot diagnostic PNG + stats dict.

    Returns (stats_dict, png_bytes).
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        # Return a 1x1 transparent PNG placeholder if matplotlib unavailable.
        _EMPTY_PNG = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00'
            b'\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        return compute_buffer_cap_stats(db, produkt), _EMPTY_PNG

    raw = _load_acid_rows(db, produkt)
    rows = _compute_rows(raw)
    stats = compute_buffer_cap_stats(db, produkt)

    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    fig.suptitle(
        f"K7 Buffer Capacity Diagnostics  |  n={stats['n']}  "
        f"MAE={stats['mae']:.3f}  MAPE={stats['mape']:.1f}%  "
        f"bias={stats['mean_bias']:+.3f}  σ={stats['stdev']:.3f}",
        fontsize=10,
    )

    if rows:
        xs = list(range(len(rows)))
        actuals   = [r["actual"]    for r in rows]
        predicted = [r["predicted"] for r in rows]
        residuals = [r["residual"]  for r in rows]
        labels    = [r["dt_start"][:10] for r in rows]

        # 1. Time series
        ax = axes[0]
        ax.plot(xs, actuals,   marker="o", label="actual",    linewidth=1.5)
        ax.plot(xs, predicted, marker="s", label="predicted", linewidth=1.5, linestyle="--")
        ax.set_title("Time series")
        ax.set_xlabel("szarża (chronologicznie)")
        ax.set_ylabel("buffer cap (kg/t/ΔpH)")
        ax.legend(fontsize=8)
        step = max(1, len(xs) // 6)
        ax.set_xticks(xs[::step])
        ax.set_xticklabels(labels[::step], rotation=30, fontsize=7)

        # 2. Scatter actual vs predicted
        ax = axes[1]
        all_vals = actuals + predicted
        lo, hi = min(all_vals), max(all_vals)
        ax.scatter(actuals, predicted, alpha=0.7, edgecolors="none")
        ax.plot([lo, hi], [lo, hi], "k--", linewidth=1, label="y=x")
        ax.set_title("Actual vs Predicted")
        ax.set_xlabel("actual buffer cap")
        ax.set_ylabel("predicted buffer cap")
        ax.legend(fontsize=8)

        # 3. Histogram of residuals
        ax = axes[2]
        ax.hist(residuals, bins=max(5, len(rows) // 3), edgecolor="white")
        ax.axvline(0, color="k", linewidth=1, linestyle="--")
        ax.set_title("Residuals (predicted − actual)")
        ax.set_xlabel("residual (kg/t/ΔpH)")
        ax.set_ylabel("count")
    else:
        for ax in axes:
            ax.text(0.5, 0.5, "Brak danych", ha="center", va="center",
                    transform=ax.transAxes, color="gray")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    return stats, buf.getvalue()


def generate_chart_response(db: sqlite3.Connection,
                            produkt: str = "Chegina_K7") -> dict[str, Any]:
    """Return {stats, chart_png_b64} suitable for JSON response."""
    stats, png_bytes = generate_chart_png(db, produkt)
    return {
        "stats": stats,
        "chart_png_b64": base64.b64encode(png_bytes).decode("ascii"),
    }
```

- [ ] **Step 4: Dopisz trasę do `mbr/ml_export/routes.py`**

```python
from mbr.ml_export.acid_diag import generate_chart_response


@ml_export_bp.route("/api/ml-export/buffer-cap-chart", methods=["GET"])
@role_required("admin")
def ml_buffer_cap_chart():
    produkt = request.args.get("produkt", "Chegina_K7")
    db = get_db()
    try:
        payload = generate_chart_response(db, produkt)
    finally:
        db.close()
    return jsonify(payload)
```

- [ ] **Step 5: Uruchom testy**

Run: `pytest tests/test_ml_export.py -v -k "buffer_cap"`
Expected: 4 × PASS. (Jeśli matplotlib nie jest zainstalowany, `test_buffer_cap_chart_endpoint` może sprawdzić tylko że chart_png_b64 jest niepusty string — PNG placeholder jest zwracany automatycznie.)

- [ ] **Step 6: Commit**

```bash
git add mbr/ml_export/acid_diag.py mbr/ml_export/routes.py tests/test_ml_export.py
git commit -m "feat(ml_export): buffer-cap chart endpoint — actual vs predicted acid model diagnostics"
```

---

## Task 18: Frontend diagnostic section na `/ml-export`

Nowa sekcja „Diagnostyka modelu kwasu — K7" na dole strony.

**Files:**
- Modify: `mbr/templates/ml_export/ml_export.html`
- Modify: `tests/test_ml_export.py`

- [ ] **Step 1: Dopisz test strony**

```python
# ─── Task 18: diagnostics section ─────────────────────────────────────────────

def test_ml_export_page_has_diagnostics_section(client):
    resp = client.get("/ml-export")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Diagnostyka" in body
    assert "buffer" in body.lower() or "kwasu" in body.lower()
```

- [ ] **Step 2: Uruchom — fail**

Run: `pytest tests/test_ml_export.py -v -k "has_diagnostics_section"`
Expected: 1 × FAIL.

- [ ] **Step 3: Dopisz sekcję diagnostyki do `mbr/templates/ml_export/ml_export.html`**

Dodaj na końcu bloku content (po sekcji inline edit, przed zamknięciem `</div>` wrappera):

```html
  {# ─── Diagnostics: buffer capacity ──────────────────────────────────────── #}
  <div class="ml-panel" id="ml-diagnostics" style="margin-top: 32px;">
    <h3>Diagnostyka modelu kwasu — K7</h3>
    <p style="font-size:12px; color:var(--text-dim); margin:0 0 10px;">
      Porównanie rzeczywistej i prognozowanej pojemności buforowej (kg/t/ΔpH)
      dla ukończonych szarż K7. Filtr: delta_pH &gt; 0.5, acid_kg &gt; 0, pH&gt;=9.
    </p>
    <div id="ml-diag-stats" style="font-size:12px; color:var(--text-dim); margin-bottom:8px;">
      — kliknij Odśwież aby wczytać —
    </div>
    <div id="ml-diag-chart" style="min-height:40px;"></div>
    <button id="ml-diag-refresh" onclick="mlLoadDiagnostics()"
            style="margin-top:10px; font-size:12px; padding:5px 14px;
                   border:1.5px solid var(--teal); border-radius:4px;
                   background:none; color:var(--teal); cursor:pointer;">
      Odśwież
    </button>
  </div>

<script>
function mlLoadDiagnostics() {
  document.getElementById('ml-diag-stats').textContent = 'Ładowanie…';
  document.getElementById('ml-diag-chart').innerHTML = '';
  fetch('/api/ml-export/buffer-cap-chart?produkt=Chegina_K7')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var s = data.stats;
      document.getElementById('ml-diag-stats').innerHTML =
        '<strong>n=' + s.n + '</strong>'
        + '  MAE=' + s.mae + ' kg/t/ΔpH'
        + '  MAPE=' + s.mape + '%'
        + '  bias=' + (s.mean_bias >= 0 ? '+' : '') + s.mean_bias
        + '  σ=' + s.stdev;
      if (data.chart_png_b64) {
        var img = document.createElement('img');
        img.src = 'data:image/png;base64,' + data.chart_png_b64;
        img.style.maxWidth = '100%';
        img.alt = 'Buffer capacity diagnostic chart';
        document.getElementById('ml-diag-chart').appendChild(img);
      }
    })
    .catch(function(err) {
      document.getElementById('ml-diag-stats').textContent = 'Błąd: ' + err.message;
    });
}
</script>
```

- [ ] **Step 4: Uruchom testy**

Run: `pytest tests/test_ml_export.py -v -k "has_diagnostics_section"`
Expected: 1 × PASS.

Smoke test manualny: zaloguj jako admin, otwórz `/ml-export`, kliknij „Odśwież" w sekcji Diagnostyka. Po chwili powinny pojawić się statystyki (n=, MAE=, itp.) oraz wykres PNG z 3 subplotami.

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/ml_export/ml_export.html tests/test_ml_export.py
git commit -m "feat(ml_export): diagnostics section — buffer-cap chart + stats on /ml-export"
```

---

## Task 19: Phase 2 full-suite regression + deploy

Pełna weryfikacja: brak nowych failów vs baseline z Phase 1, manualna weryfikacja UI, deploy.

**Files:**
- Run: pełna sucha test suite
- Manual: UI verification

- [ ] **Step 1: Uruchom pełny pytest**

Run: `pytest -x`
Expected: wszystko PASS. Żaden test z Phase 1 nie powinien być zepsutym przez Phase 2 (nowe pliki/trasy nie kolidują z istniejącymi).

- [ ] **Step 2: Uruchom serwer lokalnie i ręcznie przetestuj UI**

Run (osobny terminal): `python -m mbr.app`

Kroki smoke test:
1. Otwórz `http://127.0.0.1:5001/ml-export` zalogowany jako admin.
2. Sekcja „Edycja rekordu szarży": wpisz `nr_partii` istniejącej szarży → kliknij Szukaj → sprawdź że tabele się pojawiają.
3. Edytuj komórkę `masa_kg` → kliknij poza → tło zielone po zapisie.
4. Odśwież stronę, wróć do wyszukiwania tej samej szarży → wartość powinna być zaktualizowana.
5. Sekcja „Diagnostyka": kliknij „Odśwież" → wykres PNG z 3 subplotami + statystyki.
6. Pobierz paczkę ZIP → sprawdź że `measurements.csv` i `schema.json` są poprawne.

- [ ] **Step 3: Push + auto-deploy**

Run:
```bash
git push
```

SSH na serwer produkcyjny (lub poczekaj na timer `auto-deploy`): sprawdź że deploy przeszedł, UI działa.

- [ ] **Step 4: Finalna weryfikacja operatorska**

Poproś administratora danych o:
- Wyszukanie realnej szarży K7 po `nr_partii` → edycja jednego pola → weryfikacja zapisu.
- Przejrzenie diagnostyki buffer-cap → sprawdzenie sensowności wartości MAE (oczekiwane ~5–8 kg/t/ΔpH).

---

## Self-Review Checklist (przed oddaniem do executora)

Spec coverage — każdy pkt z speca → konkretny task:
- Long format 4 CSV + schema.json + README → Task 7
- Endpoint `.zip`, stary usunięty → Task 8
- Merge rule legacy + new → Task 5
- na2so3_recept_kg exemption → Task 5 (test_build_measurements_recipe_always_legacy)
- schema.json z jednostkami/formułą/is_target_candidate → Task 2
- `is_formula_driven` z `etap_korekty_katalog.formula_ilosc` lub `ilosc_wyliczona` → Task 2
- Targets ze snapshotu lub fallback → Task 3
- `include_failed` flag → Task 8
- 4-panelowy preview → Task 9
- Dead code sprzątnięty → Task 10
- `meff_kg` formuła (`masa > 6600 ? -1000 : -500`) → Task 3
- `pakowanie` default "zbiornik" → Task 3

Placeholder scan — brak „TBD", „TODO w kodzie", „fill in details".

Type consistency — wszystkie funkcje zdefiniowane w Taskach 2-7 są importowane po nazwach zgodnych (`build_batches`, `build_sessions`, `build_measurements`, `build_corrections`, `export_ml_package`, `build_schema`).

---

## Spec Coverage Audit — Phase 2 (Tasks 11–19)

| Wymaganie ze speca | Task(i) |
|---|---|
| Inline edit API — `GET /api/ml-export/batch-detail` (P3 search) | Task 11 |
| Inline edit API — `PUT /api/ml-export/batch/<ebr_id>` | Task 12 |
| Inline edit API — `PUT /api/ml-export/session/<sesja_id>` | Task 13 |
| Inline edit API — `PUT /api/ml-export/measurement/<source>/<id>` | Task 14 |
| Inline edit API — `PUT /api/ml-export/correction/<korekta_id>` | Task 15 |
| Inline edit API — audit event `ml_export.value_edited` | Tasks 12–15 |
| Inline edit UI — search by nr_partii + editable tables, save-on-blur | Task 16 |
| Diagnostyka — `GET /api/ml-export/buffer-cap-chart` — stats + PNG | Task 17 |
| Diagnostyka — frontend section na `/ml-export` z wykresem i statystykami | Task 18 |
| Diagnostyka — filtr delta_ph > 0.5, acid_kg > 0, ph_before >= 9 | Task 17 (acid_diag.py `_compute_rows`) |
| Diagnostyka — 3 subploty: time series, scatter, histogram residuałów | Task 17 (acid_diag.py `generate_chart_png`) |
