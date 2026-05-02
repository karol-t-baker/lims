# Uniwersalne pola produktu — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wprowadzić deklaratywny mechanizm pól dodatkowych per produkt / per wariant świadectwa, zastępujący hardkodowane kolumny w `ebr_batches` i flagi typu `has_avon_code`.

**Architecture:** Dwie nowe tabele (`produkt_pola` z definicjami, `ebr_pola_wartosci` z wartościami per szarża). Definicje mają `scope ∈ {produkt, cert_variant}` z logicznym FK na `produkty.id` lub `cert_variants.id`. Integracja w 4 punktach: modal tworzenia EBR (dynamiczne pola w sekcji "Pola dodatkowe"), Hero szarży/zbiornika (edycja inline), widok Ukończone (kolumny dynamiczne wstawiane przed kolumną "Uwagi"), generator certów (sub-namespace `pola.<kod>` w kontekście DOCX). UI definicji: zakładka w `parametry_editor.html` (scope=produkt), panel w `wzory_cert.html` (scope=cert_variant).

**Tech Stack:** Python/Flask, SQLite (raw sqlite3, brak ORM), Jinja2 templates, docxtpl dla DOCX, pytest, vanilla JS w templatach.

**Spec:** `docs/superpowers/specs/2026-05-01-produkt-pola-uniwersalne-design.md`

---

## File Structure

**Nowe pliki:**
- `mbr/produkt_pola/__init__.py` — blueprint registration
- `mbr/produkt_pola/routes.py` — API endpoints
- `mbr/shared/produkt_pola.py` — DAO (definicje + wartości + filtry)
- `tests/test_produkt_pola_dao.py`
- `tests/test_produkt_pola_api.py`
- `tests/test_registry_pola_columns.py`
- `tests/test_certs_pola_variant.py`

**Modyfikowane pliki:**
- `mbr/models.py` (linia ~15+ w `init_mbr_tables`) — CREATE TABLE dla nowych tabel
- `mbr/shared/audit.py` (linia ~38, sekcja "mbr / technolog") — nowe EVENT_* constants
- `mbr/app.py` (linia ~77+ blueprint registration) — register `produkt_pola_bp`
- `mbr/registry/models.py::list_completed_registry` (~linia 9–100) — dołączenie `pola` do output
- `mbr/registry/models.py::get_registry_columns` (~linia 103–173) — dynamiczne kolumny
- `mbr/templates/laborant/szarze_list.html` (~linia 1488 `th-uwagi`, ~1610 `td-uwagi`) — render dynamicznych kolumn przed Uwagi
- `mbr/templates/laborant/_modal_nowa_szarza.html` — sekcja "Pola dodatkowe" + JS fetch
- `mbr/templates/laborant/_fast_entry_content.html` — sekcja "Pola dodatkowe" w hero
- `mbr/templates/parametry_editor.html` — panel CRUD definicji (scope=produkt)
- `mbr/templates/admin/wzory_cert.html` — panel CRUD definicji (scope=cert_variant)
- `mbr/laborant/routes.py` lub `mbr/laborant/models.py::create_ebr` — przyjmowanie `pola: {pole_id: wartosc}`
- `mbr/certs/generator.py::build_context` — sub-namespace `pola.<kod>`
- `CLAUDE.md` — krótka notka o mechanizmie

---

## Task 1: Schema migration — tabele `produkt_pola` i `ebr_pola_wartosci`

**Files:**
- Modify: `mbr/models.py` (dodać nowe `CREATE TABLE IF NOT EXISTS` w `init_mbr_tables` po istniejących blokach, np. po `parametry_etapy`)
- Test: `tests/test_produkt_pola_dao.py` (nowy plik — minimalny test schemy)

- [ ] **Step 1: Napisz test sprawdzający że tabele powstają**

`tests/test_produkt_pola_dao.py`:

```python
"""Tests for produkt_pola DAO and schema."""
import sqlite3
import pytest
from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    yield conn
    conn.close()


def test_schema_produkt_pola_table_exists(db):
    cols = {r["name"] for r in db.execute("PRAGMA table_info(produkt_pola)")}
    expected = {
        "id", "scope", "scope_id", "kod", "label_pl", "typ_danych",
        "jednostka", "wartosc_stala", "obowiazkowe", "miejsca",
        "typy_rejestracji", "kolejnosc", "aktywne",
        "created_at", "created_by", "updated_at", "updated_by",
    }
    assert expected.issubset(cols), f"Missing columns: {expected - cols}"


def test_schema_ebr_pola_wartosci_table_exists(db):
    cols = {r["name"] for r in db.execute("PRAGMA table_info(ebr_pola_wartosci)")}
    expected = {
        "id", "ebr_id", "pole_id", "wartosc",
        "created_at", "created_by", "updated_at", "updated_by",
    }
    assert expected.issubset(cols), f"Missing columns: {expected - cols}"


def test_unique_constraint_scope_scope_id_kod(db):
    db.execute(
        "INSERT INTO produkty (id, nazwa, kod, aktywny) VALUES (1, 'Test', 'TST', 1)"
    )
    db.execute(
        "INSERT INTO produkt_pola (scope, scope_id, kod, label_pl, typ_danych, miejsca) "
        "VALUES ('produkt', 1, 'nr_zam', 'Nr zam.', 'text', '[]')"
    )
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO produkt_pola (scope, scope_id, kod, label_pl, typ_danych, miejsca) "
            "VALUES ('produkt', 1, 'nr_zam', 'Inne', 'text', '[]')"
        )
        db.commit()


def test_cascade_delete_pole_removes_wartosci(db):
    db.execute("INSERT INTO produkty (id, nazwa, kod, aktywny) VALUES (1, 'Test', 'TST', 1)")
    db.execute("INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
               "utworzony_przez, dt_utworzenia) VALUES ('Test', 1, 'active', '[]', '{}', 't', '2026-05-02')")
    db.execute("INSERT INTO ebr_batches (id, batch_id, mbr_id, nr_partii, dt_start, status) "
               "VALUES (1, 'B1', 1, '001', '2026-05-02', 'active')")
    db.execute("INSERT INTO produkt_pola (id, scope, scope_id, kod, label_pl, typ_danych, miejsca) "
               "VALUES (1, 'produkt', 1, 'k', 'L', 'text', '[]')")
    db.execute("INSERT INTO ebr_pola_wartosci (ebr_id, pole_id, wartosc) VALUES (1, 1, 'v')")
    db.commit()
    db.execute("DELETE FROM produkt_pola WHERE id=1")
    db.commit()
    cnt = db.execute("SELECT COUNT(*) FROM ebr_pola_wartosci").fetchone()[0]
    assert cnt == 0
```

- [ ] **Step 2: Uruchom test, potwierdź FAIL (no such table)**

```bash
pytest tests/test_produkt_pola_dao.py -v
```

Expected: 4 testy FAIL z `sqlite3.OperationalError: no such table: produkt_pola`.

- [ ] **Step 3: Dodaj CREATE TABLE w `init_mbr_tables`**

W `mbr/models.py`, po istniejącym bloku `parametry_etapy` (~linia 489+), wstaw:

```python
        db.execute("""
        CREATE TABLE IF NOT EXISTS produkt_pola (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            scope           TEXT NOT NULL CHECK(scope IN ('produkt','cert_variant')),
            scope_id        INTEGER NOT NULL,
            kod             TEXT NOT NULL,
            label_pl        TEXT NOT NULL,
            typ_danych      TEXT NOT NULL DEFAULT 'text' CHECK(typ_danych IN ('text','number','date')),
            jednostka       TEXT,
            wartosc_stala   TEXT,
            obowiazkowe     INTEGER NOT NULL DEFAULT 0,
            miejsca         TEXT NOT NULL DEFAULT '[]',
            typy_rejestracji TEXT,
            kolejnosc       INTEGER NOT NULL DEFAULT 0,
            aktywne         INTEGER NOT NULL DEFAULT 1,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_by      INTEGER,
            updated_at      DATETIME,
            updated_by      INTEGER,
            UNIQUE(scope, scope_id, kod)
        )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_produkt_pola_scope "
                   "ON produkt_pola(scope, scope_id, aktywne)")

        db.execute("""
        CREATE TABLE IF NOT EXISTS ebr_pola_wartosci (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ebr_id      INTEGER NOT NULL,
            pole_id     INTEGER NOT NULL,
            wartosc     TEXT,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_by  INTEGER,
            updated_at  DATETIME,
            updated_by  INTEGER,
            UNIQUE(ebr_id, pole_id),
            FOREIGN KEY(ebr_id) REFERENCES ebr_batches(id) ON DELETE CASCADE,
            FOREIGN KEY(pole_id) REFERENCES produkt_pola(id) ON DELETE CASCADE
        )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_ebr_pola_wartosci_ebr "
                   "ON ebr_pola_wartosci(ebr_id)")
```

- [ ] **Step 4: Uruchom testy ponownie**

```bash
pytest tests/test_produkt_pola_dao.py -v
```

Expected: 4 testy PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_produkt_pola_dao.py mbr/models.py
git commit -m "feat(produkt_pola): schema — tabele produkt_pola i ebr_pola_wartosci"
```

---

## Task 2: Audit event constants

**Files:**
- Modify: `mbr/shared/audit.py` (sekcja "mbr / technolog / rejestry" ~linia 38)

- [ ] **Step 1: Dodaj nowe stałe do `audit.py`**

Po linii `EVENT_PRODUKT_DELETED = "produkt.deleted"` (~linia 50), dodaj:

```python
EVENT_PRODUKT_POLA_CREATED = "produkt_pola.created"
EVENT_PRODUKT_POLA_UPDATED = "produkt_pola.updated"
EVENT_PRODUKT_POLA_DEACTIVATED = "produkt_pola.deactivated"
EVENT_EBR_POLA_VALUE_SET = "ebr_pola.value_set"
```

- [ ] **Step 2: Sanity test — imports działa**

```bash
python -c "from mbr.shared.audit import EVENT_PRODUKT_POLA_CREATED, EVENT_EBR_POLA_VALUE_SET; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add mbr/shared/audit.py
git commit -m "feat(produkt_pola): audit event constants"
```

---

## Task 3: DAO — `create_pole`, `update_pole`, `deactivate_pole`

**Files:**
- Create: `mbr/shared/produkt_pola.py`
- Test: `tests/test_produkt_pola_dao.py` (rozszerzenie istniejącego pliku)

- [ ] **Step 1: Napisz testy CRUD dla definicji**

Dopisz do `tests/test_produkt_pola_dao.py`:

```python
import json
from mbr.shared import produkt_pola as pp


@pytest.fixture
def db_with_produkt(db):
    db.execute("INSERT INTO produkty (id, nazwa, kod, aktywny) VALUES (1, 'Monamid_KO', 'MKO', 1)")
    db.execute("INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
               "VALUES (1, 'Test', 'User', 'TU', 'TU', 1)")
    db.commit()
    return db


def test_create_pole_minimal(db_with_produkt):
    pole_id = pp.create_pole(db_with_produkt, {
        "scope": "produkt",
        "scope_id": 1,
        "kod": "nr_zamowienia",
        "label_pl": "Nr zamówienia",
        "typ_danych": "text",
        "miejsca": ["modal", "hero", "ukonczone"],
    }, user_id=1)
    db_with_produkt.commit()
    row = db_with_produkt.execute("SELECT * FROM produkt_pola WHERE id=?", (pole_id,)).fetchone()
    assert row["kod"] == "nr_zamowienia"
    assert row["label_pl"] == "Nr zamówienia"
    assert row["aktywne"] == 1
    assert json.loads(row["miejsca"]) == ["modal", "hero", "ukonczone"]
    assert row["typy_rejestracji"] is None


def test_create_pole_with_typy_rejestracji(db_with_produkt):
    pole_id = pp.create_pole(db_with_produkt, {
        "scope": "produkt",
        "scope_id": 1,
        "kod": "ilosc_konserwantuna",
        "label_pl": "Ilość konserwantuna",
        "typ_danych": "number",
        "jednostka": "kg",
        "miejsca": ["hero", "ukonczone"],
        "typy_rejestracji": ["zbiornik"],
    }, user_id=1)
    db_with_produkt.commit()
    row = db_with_produkt.execute("SELECT * FROM produkt_pola WHERE id=?", (pole_id,)).fetchone()
    assert json.loads(row["typy_rejestracji"]) == ["zbiornik"]
    assert row["jednostka"] == "kg"


def test_create_pole_invalid_kod_regex(db_with_produkt):
    with pytest.raises(ValueError, match="kod"):
        pp.create_pole(db_with_produkt, {
            "scope": "produkt", "scope_id": 1,
            "kod": "Nr Zamówienia",  # spaces, uppercase, special chars
            "label_pl": "X", "typ_danych": "text", "miejsca": [],
        }, user_id=1)


def test_create_pole_cert_variant_requires_wartosc_stala(db_with_produkt):
    db_with_produkt.execute(
        "INSERT INTO cert_variants (id, produkt, variant_id, label) "
        "VALUES (1, 'Chegina_K40GLOLMB', 'kosmepol', 'Kosmepol')"
    )
    db_with_produkt.commit()
    with pytest.raises(ValueError, match="wartosc_stala"):
        pp.create_pole(db_with_produkt, {
            "scope": "cert_variant", "scope_id": 1,
            "kod": "nr_zam_kosmepol", "label_pl": "Nr zam. Kosmepol",
            "typ_danych": "text",
            # wartosc_stala missing → for active scope=cert_variant must error
            "aktywne": 1,
        }, user_id=1)


def test_update_pole(db_with_produkt):
    pid = pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 1, "kod": "k1",
        "label_pl": "Stary", "typ_danych": "text", "miejsca": ["hero"],
    }, user_id=1)
    db_with_produkt.commit()
    pp.update_pole(db_with_produkt, pid, {"label_pl": "Nowy", "kolejnosc": 5}, user_id=1)
    db_with_produkt.commit()
    row = db_with_produkt.execute("SELECT label_pl, kolejnosc FROM produkt_pola WHERE id=?", (pid,)).fetchone()
    assert row["label_pl"] == "Nowy"
    assert row["kolejnosc"] == 5


def test_update_pole_kod_immutable(db_with_produkt):
    pid = pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 1, "kod": "stary_kod",
        "label_pl": "L", "typ_danych": "text", "miejsca": [],
    }, user_id=1)
    db_with_produkt.commit()
    with pytest.raises(ValueError, match="kod.*immutable"):
        pp.update_pole(db_with_produkt, pid, {"kod": "nowy_kod"}, user_id=1)


def test_deactivate_pole(db_with_produkt):
    pid = pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 1, "kod": "k1",
        "label_pl": "L", "typ_danych": "text", "miejsca": [],
    }, user_id=1)
    db_with_produkt.commit()
    pp.deactivate_pole(db_with_produkt, pid, user_id=1)
    db_with_produkt.commit()
    row = db_with_produkt.execute("SELECT aktywne FROM produkt_pola WHERE id=?", (pid,)).fetchone()
    assert row["aktywne"] == 0


def test_audit_event_emitted_on_create(db_with_produkt, monkeypatch):
    captured = []
    from mbr.shared import audit
    real_log = audit.log_event

    def fake_log(event_type, **kwargs):
        captured.append((event_type, kwargs))
        return real_log(event_type, **kwargs)

    monkeypatch.setattr(audit, "log_event", fake_log)
    pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 1, "kod": "k1",
        "label_pl": "L", "typ_danych": "text", "miejsca": [],
    }, user_id=1)
    assert any(et == audit.EVENT_PRODUKT_POLA_CREATED for et, _ in captured)
```

- [ ] **Step 2: Uruchom testy, potwierdź FAIL**

```bash
pytest tests/test_produkt_pola_dao.py::test_create_pole_minimal -v
```

Expected: FAIL z `ImportError: No module named 'mbr.shared.produkt_pola'` (lub podobny).

- [ ] **Step 3: Stwórz `mbr/shared/produkt_pola.py` z funkcjami CRUD definicji**

```python
"""DAO for produkt_pola — declarative metadata fields per produkt / cert_variant.

See docs/superpowers/specs/2026-05-01-produkt-pola-uniwersalne-design.md
"""

import json
import re
from datetime import datetime
from typing import Any

from mbr.shared import audit

_KOD_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_VALID_SCOPES = {"produkt", "cert_variant"}
_VALID_TYP_DANYCH = {"text", "number", "date"}
_VALID_MIEJSCA = {"modal", "hero", "ukonczone", "cert"}
_VALID_TYPY_REJESTRACJI = {"szarza", "zbiornik", "platkowanie"}


def _validate_kod(kod: str) -> None:
    if not _KOD_RE.match(kod or ""):
        raise ValueError(f"kod must match {_KOD_RE.pattern}, got: {kod!r}")


def _validate_payload(payload: dict, *, is_create: bool) -> None:
    if is_create:
        if payload.get("scope") not in _VALID_SCOPES:
            raise ValueError(f"scope must be one of {_VALID_SCOPES}")
        _validate_kod(payload.get("kod", ""))
        if not payload.get("label_pl"):
            raise ValueError("label_pl required")
    typ = payload.get("typ_danych")
    if typ is not None and typ not in _VALID_TYP_DANYCH:
        raise ValueError(f"typ_danych must be one of {_VALID_TYP_DANYCH}")
    miejsca = payload.get("miejsca")
    if miejsca is not None:
        if not isinstance(miejsca, list) or not set(miejsca).issubset(_VALID_MIEJSCA):
            raise ValueError(f"miejsca must be subset of {_VALID_MIEJSCA}")
    typy = payload.get("typy_rejestracji")
    if typy is not None and typy != []:
        if not isinstance(typy, list) or not set(typy).issubset(_VALID_TYPY_REJESTRACJI):
            raise ValueError(f"typy_rejestracji must be subset of {_VALID_TYPY_REJESTRACJI}")
    # cert_variant requires text type and non-empty wartosc_stala when active
    scope = payload.get("scope")
    if scope == "cert_variant":
        if payload.get("typ_danych", "text") != "text":
            raise ValueError("scope=cert_variant requires typ_danych='text'")
        is_active = payload.get("aktywne", 1)
        ws = payload.get("wartosc_stala")
        if is_active and (ws is None or ws == ""):
            raise ValueError("scope=cert_variant with aktywne=1 requires non-empty wartosc_stala")


def create_pole(db, payload: dict, user_id: int) -> int:
    """Create a produkt_pola row. Validates payload, emits audit event."""
    _validate_payload(payload, is_create=True)
    miejsca_json = json.dumps(payload.get("miejsca", []))
    typy_json = json.dumps(payload["typy_rejestracji"]) if payload.get("typy_rejestracji") else None
    now = datetime.utcnow().isoformat(timespec="seconds")
    cur = db.execute("""
        INSERT INTO produkt_pola
        (scope, scope_id, kod, label_pl, typ_danych, jednostka, wartosc_stala,
         obowiazkowe, miejsca, typy_rejestracji, kolejnosc, aktywne,
         created_at, created_by, updated_at, updated_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        payload["scope"],
        payload["scope_id"],
        payload["kod"],
        payload["label_pl"],
        payload.get("typ_danych", "text"),
        payload.get("jednostka"),
        payload.get("wartosc_stala"),
        1 if payload.get("obowiazkowe") else 0,
        miejsca_json,
        typy_json,
        payload.get("kolejnosc", 0),
        1 if payload.get("aktywne", 1) else 0,
        now, user_id, now, user_id,
    ))
    pole_id = cur.lastrowid
    audit.log_event(
        audit.EVENT_PRODUKT_POLA_CREATED,
        entity_type="produkt_pola",
        entity_id=pole_id,
        entity_label=payload["kod"],
        payload={k: payload.get(k) for k in (
            "scope", "scope_id", "kod", "label_pl", "typ_danych",
            "wartosc_stala", "miejsca", "typy_rejestracji"
        )},
        db=db,
    )
    return pole_id


def update_pole(db, pole_id: int, patch: dict, user_id: int) -> None:
    """Update editable fields. `kod`, `scope`, `scope_id` are immutable."""
    if "kod" in patch:
        raise ValueError("kod is immutable after creation")
    if "scope" in patch or "scope_id" in patch:
        raise ValueError("scope/scope_id are immutable after creation")
    row = db.execute("SELECT * FROM produkt_pola WHERE id=?", (pole_id,)).fetchone()
    if row is None:
        raise ValueError(f"produkt_pola id={pole_id} not found")
    # Merge for validation: full picture must remain valid
    merged = {k: row[k] for k in row.keys()}
    merged["miejsca"] = json.loads(row["miejsca"] or "[]")
    merged["typy_rejestracji"] = json.loads(row["typy_rejestracji"]) if row["typy_rejestracji"] else None
    merged.update(patch)
    _validate_payload(merged, is_create=False)
    sets = []
    vals: list[Any] = []
    for k in ("label_pl", "typ_danych", "jednostka", "wartosc_stala",
              "obowiazkowe", "kolejnosc", "aktywne"):
        if k in patch:
            sets.append(f"{k}=?")
            v = patch[k]
            if k in ("obowiazkowe", "aktywne"):
                v = 1 if v else 0
            vals.append(v)
    if "miejsca" in patch:
        sets.append("miejsca=?")
        vals.append(json.dumps(patch["miejsca"]))
    if "typy_rejestracji" in patch:
        sets.append("typy_rejestracji=?")
        vals.append(json.dumps(patch["typy_rejestracji"]) if patch["typy_rejestracji"] else None)
    sets.extend(["updated_at=?", "updated_by=?"])
    vals.extend([datetime.utcnow().isoformat(timespec="seconds"), user_id])
    vals.append(pole_id)
    db.execute(f"UPDATE produkt_pola SET {', '.join(sets)} WHERE id=?", vals)
    audit.log_event(
        audit.EVENT_PRODUKT_POLA_UPDATED,
        entity_type="produkt_pola",
        entity_id=pole_id,
        entity_label=row["kod"],
        diff=[{"pole": k, "stara": row[k] if k in row.keys() else None, "nowa": patch[k]}
              for k in patch.keys() if k in row.keys()],
        db=db,
    )


def deactivate_pole(db, pole_id: int, user_id: int) -> None:
    """Soft-delete (`aktywne=0`). Historical values preserved."""
    row = db.execute("SELECT kod FROM produkt_pola WHERE id=?", (pole_id,)).fetchone()
    if row is None:
        raise ValueError(f"produkt_pola id={pole_id} not found")
    db.execute(
        "UPDATE produkt_pola SET aktywne=0, updated_at=?, updated_by=? WHERE id=?",
        (datetime.utcnow().isoformat(timespec="seconds"), user_id, pole_id),
    )
    audit.log_event(
        audit.EVENT_PRODUKT_POLA_DEACTIVATED,
        entity_type="produkt_pola",
        entity_id=pole_id,
        entity_label=row["kod"],
        db=db,
    )
```

- [ ] **Step 4: Uruchom testy, potwierdź PASS**

```bash
pytest tests/test_produkt_pola_dao.py -v -k "create_pole or update_pole or deactivate_pole or audit_event"
```

Expected: wszystkie 8 testów PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/shared/produkt_pola.py tests/test_produkt_pola_dao.py
git commit -m "feat(produkt_pola): DAO create/update/deactivate definicji + audit"
```

---

## Task 4: DAO — `set_wartosc`, `get_wartosci_for_ebr`

**Files:**
- Modify: `mbr/shared/produkt_pola.py`
- Test: `tests/test_produkt_pola_dao.py`

- [ ] **Step 1: Dodaj testy dla set/get wartości**

Dopisz do `tests/test_produkt_pola_dao.py`:

```python
def test_set_wartosc_text(db_with_produkt):
    db_with_produkt.execute("INSERT INTO mbr_templates (id, produkt, wersja, status, etapy_json, "
                            "parametry_lab, utworzony_przez, dt_utworzenia) "
                            "VALUES (1, 'Monamid_KO', 1, 'active', '[]', '{}', 't', '2026-05-02')")
    db_with_produkt.execute("INSERT INTO ebr_batches (id, batch_id, mbr_id, nr_partii, dt_start, status) "
                            "VALUES (1, 'B1', 1, '001', '2026-05-02', 'active')")
    pid = pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 1, "kod": "nr_zam",
        "label_pl": "Nr", "typ_danych": "text", "miejsca": ["hero"],
    }, user_id=1)
    db_with_produkt.commit()
    pp.set_wartosc(db_with_produkt, ebr_id=1, pole_id=pid, wartosc="ZAM/123", user_id=1)
    db_with_produkt.commit()
    row = db_with_produkt.execute(
        "SELECT wartosc FROM ebr_pola_wartosci WHERE ebr_id=1 AND pole_id=?", (pid,)
    ).fetchone()
    assert row["wartosc"] == "ZAM/123"


def test_set_wartosc_number_normalizes_comma(db_with_produkt):
    db_with_produkt.execute("INSERT INTO mbr_templates (id, produkt, wersja, status, etapy_json, "
                            "parametry_lab, utworzony_przez, dt_utworzenia) "
                            "VALUES (1, 'X', 1, 'active', '[]', '{}', 't', '2026-05-02')")
    db_with_produkt.execute("INSERT INTO ebr_batches (id, batch_id, mbr_id, nr_partii, dt_start, status) "
                            "VALUES (1, 'B1', 1, '001', '2026-05-02', 'active')")
    pid = pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 1, "kod": "ilosc",
        "label_pl": "I", "typ_danych": "number", "miejsca": ["hero"],
    }, user_id=1)
    db_with_produkt.commit()
    pp.set_wartosc(db_with_produkt, ebr_id=1, pole_id=pid, wartosc="12.5", user_id=1)
    db_with_produkt.commit()
    val = db_with_produkt.execute(
        "SELECT wartosc FROM ebr_pola_wartosci WHERE ebr_id=1 AND pole_id=?", (pid,)
    ).fetchone()["wartosc"]
    # Polish convention: storage uses comma
    assert val == "12,5"
    # accept comma input too
    pp.set_wartosc(db_with_produkt, ebr_id=1, pole_id=pid, wartosc="14,75", user_id=1)
    db_with_produkt.commit()
    val = db_with_produkt.execute(
        "SELECT wartosc FROM ebr_pola_wartosci WHERE ebr_id=1 AND pole_id=?", (pid,)
    ).fetchone()["wartosc"]
    assert val == "14,75"


def test_set_wartosc_number_invalid(db_with_produkt):
    db_with_produkt.execute("INSERT INTO mbr_templates (id, produkt, wersja, status, etapy_json, "
                            "parametry_lab, utworzony_przez, dt_utworzenia) "
                            "VALUES (1, 'X', 1, 'active', '[]', '{}', 't', '2026-05-02')")
    db_with_produkt.execute("INSERT INTO ebr_batches (id, batch_id, mbr_id, nr_partii, dt_start, status) "
                            "VALUES (1, 'B1', 1, '001', '2026-05-02', 'active')")
    pid = pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 1, "kod": "ilosc",
        "label_pl": "I", "typ_danych": "number", "miejsca": ["hero"],
    }, user_id=1)
    db_with_produkt.commit()
    with pytest.raises(ValueError):
        pp.set_wartosc(db_with_produkt, ebr_id=1, pole_id=pid, wartosc="abc", user_id=1)


def test_set_wartosc_null_clears(db_with_produkt):
    db_with_produkt.execute("INSERT INTO mbr_templates (id, produkt, wersja, status, etapy_json, "
                            "parametry_lab, utworzony_przez, dt_utworzenia) "
                            "VALUES (1, 'X', 1, 'active', '[]', '{}', 't', '2026-05-02')")
    db_with_produkt.execute("INSERT INTO ebr_batches (id, batch_id, mbr_id, nr_partii, dt_start, status) "
                            "VALUES (1, 'B1', 1, '001', '2026-05-02', 'active')")
    pid = pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 1, "kod": "k",
        "label_pl": "L", "typ_danych": "text", "miejsca": ["hero"],
    }, user_id=1)
    db_with_produkt.commit()
    pp.set_wartosc(db_with_produkt, 1, pid, "X", user_id=1)
    pp.set_wartosc(db_with_produkt, 1, pid, None, user_id=1)
    db_with_produkt.commit()
    val = db_with_produkt.execute(
        "SELECT wartosc FROM ebr_pola_wartosci WHERE ebr_id=1 AND pole_id=?", (pid,)
    ).fetchone()["wartosc"]
    assert val is None


def test_get_wartosci_for_ebr_returns_dict(db_with_produkt):
    db_with_produkt.execute("INSERT INTO mbr_templates (id, produkt, wersja, status, etapy_json, "
                            "parametry_lab, utworzony_przez, dt_utworzenia) "
                            "VALUES (1, 'Monamid_KO', 1, 'active', '[]', '{}', 't', '2026-05-02')")
    db_with_produkt.execute("INSERT INTO ebr_batches (id, batch_id, mbr_id, nr_partii, dt_start, status) "
                            "VALUES (1, 'B1', 1, '001', '2026-05-02', 'active')")
    p1 = pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 1, "kod": "nr_zam",
        "label_pl": "Nr", "typ_danych": "text", "miejsca": ["hero"],
    }, user_id=1)
    p2 = pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 1, "kod": "nr_dop",
        "label_pl": "Dop", "typ_danych": "text", "miejsca": ["hero"],
    }, user_id=1)
    pp.set_wartosc(db_with_produkt, 1, p1, "ZAM/1", user_id=1)
    pp.set_wartosc(db_with_produkt, 1, p2, "DOP/2", user_id=1)
    db_with_produkt.commit()
    result = pp.get_wartosci_for_ebr(db_with_produkt, ebr_id=1, produkt_id=1)
    assert result == {"nr_zam": "ZAM/1", "nr_dop": "DOP/2"}
```

- [ ] **Step 2: Uruchom testy, potwierdź FAIL**

```bash
pytest tests/test_produkt_pola_dao.py -v -k "set_wartosc or get_wartosci"
```

Expected: FAIL z `AttributeError: ... 'set_wartosc'`.

- [ ] **Step 3: Dodaj funkcje do `mbr/shared/produkt_pola.py`**

Dopisz na końcu pliku:

```python
def _coerce_value(typ_danych: str, raw: str | None) -> str | None:
    """Validate & normalize value per typ_danych. NULL/empty → None."""
    if raw is None or raw == "":
        return None
    if typ_danych == "text":
        return raw
    if typ_danych == "number":
        normalized = raw.replace(",", ".")
        try:
            float(normalized)
        except ValueError:
            raise ValueError(f"invalid number: {raw!r}")
        # Storage convention: Polish comma
        return normalized.replace(".", ",")
    if typ_danych == "date":
        # Accept ISO YYYY-MM-DD or DD-MM-YYYY / D.M.YYYY → normalize to ISO
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
            try:
                d = datetime.strptime(raw, fmt)
                return d.strftime("%Y-%m-%d")
            except ValueError:
                continue
        raise ValueError(f"invalid date (use YYYY-MM-DD): {raw!r}")
    raise ValueError(f"unknown typ_danych: {typ_danych}")


def set_wartosc(db, ebr_id: int, pole_id: int, wartosc, user_id: int) -> None:
    """Upsert value for (ebr_id, pole_id). Validates against pole.typ_danych. Audit-logged."""
    pole = db.execute(
        "SELECT kod, typ_danych FROM produkt_pola WHERE id=?", (pole_id,)
    ).fetchone()
    if pole is None:
        raise ValueError(f"pole id={pole_id} not found")
    coerced = _coerce_value(pole["typ_danych"], wartosc)
    existing = db.execute(
        "SELECT wartosc FROM ebr_pola_wartosci WHERE ebr_id=? AND pole_id=?",
        (ebr_id, pole_id),
    ).fetchone()
    before = existing["wartosc"] if existing else None
    now = datetime.utcnow().isoformat(timespec="seconds")
    if existing is None:
        db.execute("""
            INSERT INTO ebr_pola_wartosci
            (ebr_id, pole_id, wartosc, created_at, created_by, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (ebr_id, pole_id, coerced, now, user_id, now, user_id))
    else:
        db.execute("""
            UPDATE ebr_pola_wartosci SET wartosc=?, updated_at=?, updated_by=?
            WHERE ebr_id=? AND pole_id=?
        """, (coerced, now, user_id, ebr_id, pole_id))
    audit.log_event(
        audit.EVENT_EBR_POLA_VALUE_SET,
        entity_type="ebr_pola",
        entity_id=ebr_id,
        diff=[{"pole": pole["kod"], "stara": before, "nowa": coerced}],
        context={"ebr_id": ebr_id, "pole_id": pole_id, "kod": pole["kod"]},
        db=db,
    )


def get_wartosci_for_ebr(db, ebr_id: int, produkt_id: int) -> dict:
    """Return {kod: wartosc} for active fields scope=produkt of given produkt_id."""
    rows = db.execute("""
        SELECT pp.kod, ev.wartosc
        FROM produkt_pola pp
        LEFT JOIN ebr_pola_wartosci ev ON ev.pole_id = pp.id AND ev.ebr_id = ?
        WHERE pp.scope='produkt' AND pp.scope_id=? AND pp.aktywne=1
    """, (ebr_id, produkt_id)).fetchall()
    return {r["kod"]: r["wartosc"] for r in rows if r["wartosc"] is not None}
```

- [ ] **Step 4: Uruchom testy, potwierdź PASS**

```bash
pytest tests/test_produkt_pola_dao.py -v -k "set_wartosc or get_wartosci"
```

Expected: 5 testów PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/shared/produkt_pola.py tests/test_produkt_pola_dao.py
git commit -m "feat(produkt_pola): DAO set/get wartosci z normalizacja PL i audytem"
```

---

## Task 5: DAO — `list_pola_for_produkt` i `list_pola_for_cert_variant` z filtrami

**Files:**
- Modify: `mbr/shared/produkt_pola.py`
- Test: `tests/test_produkt_pola_dao.py`

- [ ] **Step 1: Dodaj testy dla list_pola filters**

Dopisz do `tests/test_produkt_pola_dao.py`:

```python
def test_list_pola_for_produkt_filters_miejsce(db_with_produkt):
    pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 1, "kod": "modal_only",
        "label_pl": "M", "typ_danych": "text", "miejsca": ["modal"],
    }, user_id=1)
    pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 1, "kod": "hero_modal",
        "label_pl": "HM", "typ_danych": "text", "miejsca": ["modal", "hero"],
    }, user_id=1)
    pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 1, "kod": "ukonczone_only",
        "label_pl": "U", "typ_danych": "text", "miejsca": ["ukonczone"],
    }, user_id=1)
    db_with_produkt.commit()
    modal = pp.list_pola_for_produkt(db_with_produkt, 1, miejsce="modal")
    assert {p["kod"] for p in modal} == {"modal_only", "hero_modal"}


def test_list_pola_for_produkt_filters_typ_rejestracji(db_with_produkt):
    pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 1, "kod": "wszystkie",
        "label_pl": "W", "typ_danych": "text", "miejsca": ["hero"],
        # typy_rejestracji NULL = wszystkie
    }, user_id=1)
    pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 1, "kod": "tylko_zbiornik",
        "label_pl": "Z", "typ_danych": "number", "miejsca": ["hero"],
        "typy_rejestracji": ["zbiornik"],
    }, user_id=1)
    db_with_produkt.commit()
    for_szarza = pp.list_pola_for_produkt(db_with_produkt, 1, typ_rejestracji="szarza")
    assert {p["kod"] for p in for_szarza} == {"wszystkie"}
    for_zbiornik = pp.list_pola_for_produkt(db_with_produkt, 1, typ_rejestracji="zbiornik")
    assert {p["kod"] for p in for_zbiornik} == {"wszystkie", "tylko_zbiornik"}


def test_list_pola_for_produkt_excludes_inactive(db_with_produkt):
    p1 = pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 1, "kod": "aktywne",
        "label_pl": "A", "typ_danych": "text", "miejsca": ["hero"],
    }, user_id=1)
    p2 = pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 1, "kod": "wylaczone",
        "label_pl": "W", "typ_danych": "text", "miejsca": ["hero"],
    }, user_id=1)
    pp.deactivate_pole(db_with_produkt, p2, user_id=1)
    db_with_produkt.commit()
    pola = pp.list_pola_for_produkt(db_with_produkt, 1)
    assert {p["kod"] for p in pola} == {"aktywne"}


def test_list_pola_for_produkt_sorted_by_kolejnosc(db_with_produkt):
    pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 1, "kod": "drugie",
        "label_pl": "D", "typ_danych": "text", "miejsca": ["hero"],
        "kolejnosc": 20,
    }, user_id=1)
    pp.create_pole(db_with_produkt, {
        "scope": "produkt", "scope_id": 1, "kod": "pierwsze",
        "label_pl": "P", "typ_danych": "text", "miejsca": ["hero"],
        "kolejnosc": 10,
    }, user_id=1)
    db_with_produkt.commit()
    pola = pp.list_pola_for_produkt(db_with_produkt, 1)
    assert [p["kod"] for p in pola] == ["pierwsze", "drugie"]


def test_list_pola_for_cert_variant(db_with_produkt):
    db_with_produkt.execute("INSERT INTO cert_variants (id, produkt, variant_id, label) "
                            "VALUES (10, 'Chegina_K40GLOLMB', 'kosmepol', 'Kosmepol')")
    db_with_produkt.commit()
    pp.create_pole(db_with_produkt, {
        "scope": "cert_variant", "scope_id": 10, "kod": "nr_zam_kosmepol",
        "label_pl": "Nr zam.", "typ_danych": "text",
        "wartosc_stala": "KSM/2026/STALY/001",
    }, user_id=1)
    db_with_produkt.commit()
    pola = pp.list_pola_for_cert_variant(db_with_produkt, 10)
    assert len(pola) == 1
    assert pola[0]["kod"] == "nr_zam_kosmepol"
    assert pola[0]["wartosc_stala"] == "KSM/2026/STALY/001"
```

- [ ] **Step 2: Uruchom testy, potwierdź FAIL**

```bash
pytest tests/test_produkt_pola_dao.py -v -k "list_pola"
```

Expected: FAIL z `AttributeError: ... 'list_pola_for_produkt'`.

- [ ] **Step 3: Dodaj funkcje do `mbr/shared/produkt_pola.py`**

Dopisz na końcu pliku:

```python
def _row_to_dict(row) -> dict:
    d = {k: row[k] for k in row.keys()}
    d["miejsca"] = json.loads(d.get("miejsca") or "[]")
    if d.get("typy_rejestracji"):
        d["typy_rejestracji"] = json.loads(d["typy_rejestracji"])
    else:
        d["typy_rejestracji"] = None
    d["obowiazkowe"] = bool(d.get("obowiazkowe"))
    d["aktywne"] = bool(d.get("aktywne"))
    return d


def list_pola_for_produkt(db, produkt_id: int, *,
                           miejsce: str | None = None,
                           typ_rejestracji: str | None = None,
                           only_active: bool = True) -> list[dict]:
    """List pola scope='produkt'. Filtruje po miejscu / typie rejestracji."""
    sql = "SELECT * FROM produkt_pola WHERE scope='produkt' AND scope_id=?"
    params: list = [produkt_id]
    if only_active:
        sql += " AND aktywne=1"
    sql += " ORDER BY kolejnosc, id"
    rows = [_row_to_dict(r) for r in db.execute(sql, params).fetchall()]
    if miejsce is not None:
        rows = [r for r in rows if miejsce in r["miejsca"]]
    if typ_rejestracji is not None:
        rows = [r for r in rows
                if r["typy_rejestracji"] is None or typ_rejestracji in r["typy_rejestracji"]]
    return rows


def list_pola_for_cert_variant(db, variant_id: int, *,
                                only_active: bool = True) -> list[dict]:
    """List pola scope='cert_variant'."""
    sql = "SELECT * FROM produkt_pola WHERE scope='cert_variant' AND scope_id=?"
    params: list = [variant_id]
    if only_active:
        sql += " AND aktywne=1"
    sql += " ORDER BY kolejnosc, id"
    return [_row_to_dict(r) for r in db.execute(sql, params).fetchall()]
```

- [ ] **Step 4: Uruchom testy, potwierdź PASS**

```bash
pytest tests/test_produkt_pola_dao.py -v
```

Expected: wszystkie testy DAO PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/shared/produkt_pola.py tests/test_produkt_pola_dao.py
git commit -m "feat(produkt_pola): DAO list_pola z filtrami miejsce/typ_rejestracji/aktywne"
```

---

## Task 6: Blueprint setup + register w app

**Files:**
- Create: `mbr/produkt_pola/__init__.py`
- Create: `mbr/produkt_pola/routes.py` (skeleton)
- Modify: `mbr/app.py`

- [ ] **Step 1: Stwórz blueprint module**

`mbr/produkt_pola/__init__.py`:

```python
from flask import Blueprint
produkt_pola_bp = Blueprint('produkt_pola', __name__)
from mbr.produkt_pola import routes  # noqa: E402, F401
```

`mbr/produkt_pola/routes.py`:

```python
"""HTTP API for produkt_pola — declarative metadata fields."""

from flask import jsonify, request

from mbr.db import db_session
from mbr.shared.decorators import login_required, role_required
from mbr.produkt_pola import produkt_pola_bp


@produkt_pola_bp.route("/api/produkt-pola/_ping")
@login_required
def _ping():
    return jsonify({"ok": True})
```

- [ ] **Step 2: Register blueprint w `mbr/app.py`**

W `create_app()` po `app.register_blueprint(chzt_bp)` (~linia 90) dodaj:

```python
    from mbr.produkt_pola import produkt_pola_bp
    app.register_blueprint(produkt_pola_bp)
```

- [ ] **Step 3: Smoke test — endpoint odpowiada**

```bash
python -c "from mbr.app import create_app; c = create_app().test_client(); r = c.get('/api/produkt-pola/_ping'); print(r.status_code)"
```

Expected: `302` lub `401` (login_required redirect/reject — endpoint istnieje).

- [ ] **Step 4: Commit**

```bash
git add mbr/produkt_pola/ mbr/app.py
git commit -m "feat(produkt_pola): blueprint skeleton + register"
```

---

## Task 7: API GET endpoints

**Files:**
- Modify: `mbr/produkt_pola/routes.py`
- Create: `tests/test_produkt_pola_api.py`

- [ ] **Step 1: Napisz testy GET endpointów**

`tests/test_produkt_pola_api.py`:

```python
"""HTTP API tests for /api/produkt-pola."""
import sqlite3
import pytest
from contextlib import contextmanager
from mbr.models import init_mbr_tables
from mbr.shared import produkt_pola as pp


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    conn.execute("INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
                 "VALUES (1, 'T', 'U', 'TU', 'TU', 1)")
    conn.execute("INSERT INTO produkty (id, nazwa, kod, aktywny) VALUES (1, 'Monamid_KO', 'MKO', 1)")
    conn.commit()
    yield conn
    conn.close()


def _client(monkeypatch, db, rola="admin"):
    import mbr.db
    import mbr.produkt_pola.routes

    @contextmanager
    def fake():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake)
    monkeypatch.setattr(mbr.produkt_pola.routes, "db_session", fake)
    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as s:
        s["user"] = {"login": "t", "rola": rola, "imie_nazwisko": None}
        s["shift_workers"] = [1]
    return c


def test_get_produkt_pola_empty(monkeypatch, db):
    c = _client(monkeypatch, db)
    r = c.get("/api/produkt-pola?scope=produkt&scope_id=1")
    assert r.status_code == 200
    assert r.json == {"pola": []}


def test_get_produkt_pola_returns_active_fields(monkeypatch, db):
    pp.create_pole(db, {
        "scope": "produkt", "scope_id": 1, "kod": "k1",
        "label_pl": "L1", "typ_danych": "text", "miejsca": ["modal"],
    }, user_id=1)
    db.commit()
    c = _client(monkeypatch, db)
    r = c.get("/api/produkt-pola?scope=produkt&scope_id=1")
    assert r.status_code == 200
    pola = r.json["pola"]
    assert len(pola) == 1
    assert pola[0]["kod"] == "k1"
    assert pola[0]["miejsca"] == ["modal"]


def test_get_ebr_pola_returns_values(monkeypatch, db):
    db.execute("INSERT INTO mbr_templates (id, produkt, wersja, status, etapy_json, "
               "parametry_lab, utworzony_przez, dt_utworzenia) "
               "VALUES (1, 'Monamid_KO', 1, 'active', '[]', '{}', 't', '2026-05-02')")
    db.execute("INSERT INTO ebr_batches (id, batch_id, mbr_id, nr_partii, dt_start, status) "
               "VALUES (1, 'B1', 1, '001', '2026-05-02', 'active')")
    pid = pp.create_pole(db, {
        "scope": "produkt", "scope_id": 1, "kod": "nr_zam",
        "label_pl": "Nr", "typ_danych": "text", "miejsca": ["hero"],
    }, user_id=1)
    pp.set_wartosc(db, 1, pid, "ZAM/1", user_id=1)
    db.commit()
    c = _client(monkeypatch, db, rola="lab")
    r = c.get("/api/ebr/1/pola")
    assert r.status_code == 200
    assert r.json["wartosci"] == {"nr_zam": "ZAM/1"}
```

- [ ] **Step 2: Uruchom testy, potwierdź FAIL**

```bash
pytest tests/test_produkt_pola_api.py -v
```

Expected: FAIL — endpointy nie istnieją (404).

- [ ] **Step 3: Dodaj endpointy GET do `mbr/produkt_pola/routes.py`**

Zastąp zawartość `routes.py`:

```python
"""HTTP API for produkt_pola — declarative metadata fields."""

from flask import jsonify, request

from mbr.db import db_session
from mbr.models import get_ebr
from mbr.shared.decorators import login_required, role_required
from mbr.shared import produkt_pola as pp
from mbr.produkt_pola import produkt_pola_bp


@produkt_pola_bp.route("/api/produkt-pola", methods=["GET"])
@login_required
def list_pola():
    scope = request.args.get("scope")
    scope_id_raw = request.args.get("scope_id")
    if scope not in ("produkt", "cert_variant") or not scope_id_raw:
        return jsonify({"error": "scope and scope_id required"}), 400
    try:
        scope_id = int(scope_id_raw)
    except ValueError:
        return jsonify({"error": "scope_id must be int"}), 400
    only_active = request.args.get("only_active", "1") != "0"
    with db_session() as db:
        if scope == "produkt":
            pola = pp.list_pola_for_produkt(db, scope_id, only_active=only_active)
        else:
            pola = pp.list_pola_for_cert_variant(db, scope_id, only_active=only_active)
    return jsonify({"pola": pola})


@produkt_pola_bp.route("/api/ebr/<int:ebr_id>/pola", methods=["GET"])
@login_required
def list_ebr_pola_values(ebr_id: int):
    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        if ebr is None:
            return jsonify({"error": "ebr not found"}), 404
        # Resolve produkt_id from mbr_template
        mbr = db.execute(
            "SELECT t.produkt FROM mbr_templates t "
            "JOIN ebr_batches eb ON eb.mbr_id = t.id WHERE eb.id=?", (ebr_id,)
        ).fetchone()
        if mbr is None:
            return jsonify({"wartosci": {}})
        prod = db.execute("SELECT id FROM produkty WHERE nazwa=?", (mbr["produkt"],)).fetchone()
        if prod is None:
            return jsonify({"wartosci": {}})
        wartosci = pp.get_wartosci_for_ebr(db, ebr_id, prod["id"])
    return jsonify({"wartosci": wartosci})
```

- [ ] **Step 4: Uruchom testy, potwierdź PASS**

```bash
pytest tests/test_produkt_pola_api.py -v
```

Expected: 3 testy PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/produkt_pola/routes.py tests/test_produkt_pola_api.py
git commit -m "feat(produkt_pola): GET /api/produkt-pola i /api/ebr/<id>/pola"
```

---

## Task 8: API POST `/api/produkt-pola` (create definicja)

**Files:**
- Modify: `mbr/produkt_pola/routes.py`
- Modify: `tests/test_produkt_pola_api.py`

- [ ] **Step 1: Napisz testy POST**

Dopisz do `tests/test_produkt_pola_api.py`:

```python
def test_post_produkt_pola_create(monkeypatch, db):
    c = _client(monkeypatch, db)
    r = c.post("/api/produkt-pola", json={
        "scope": "produkt", "scope_id": 1, "kod": "nr_zam",
        "label_pl": "Nr zamówienia", "typ_danych": "text",
        "miejsca": ["modal", "hero", "ukonczone"],
        "kolejnosc": 10,
    })
    assert r.status_code == 201, r.json
    pid = r.json["pole_id"]
    row = db.execute("SELECT * FROM produkt_pola WHERE id=?", (pid,)).fetchone()
    assert row["kod"] == "nr_zam"


def test_post_produkt_pola_invalid_kod(monkeypatch, db):
    c = _client(monkeypatch, db)
    r = c.post("/api/produkt-pola", json={
        "scope": "produkt", "scope_id": 1,
        "kod": "Bad Kod!", "label_pl": "L", "typ_danych": "text", "miejsca": [],
    })
    assert r.status_code == 400
    assert "kod" in (r.json.get("error") or "")


def test_post_produkt_pola_duplicate_409(monkeypatch, db):
    pp.create_pole(db, {
        "scope": "produkt", "scope_id": 1, "kod": "dupl",
        "label_pl": "L", "typ_danych": "text", "miejsca": [],
    }, user_id=1)
    db.commit()
    c = _client(monkeypatch, db)
    r = c.post("/api/produkt-pola", json={
        "scope": "produkt", "scope_id": 1, "kod": "dupl",
        "label_pl": "L2", "typ_danych": "text", "miejsca": [],
    })
    assert r.status_code == 409


def test_post_produkt_pola_requires_admin_or_technolog(monkeypatch, db):
    c = _client(monkeypatch, db, rola="lab")
    r = c.post("/api/produkt-pola", json={
        "scope": "produkt", "scope_id": 1, "kod": "k", "label_pl": "L",
        "typ_danych": "text", "miejsca": [],
    })
    assert r.status_code == 403
```

- [ ] **Step 2: Uruchom testy, potwierdź FAIL**

```bash
pytest tests/test_produkt_pola_api.py -v -k "post"
```

Expected: FAIL — endpoint POST nie istnieje.

- [ ] **Step 3: Dodaj POST endpoint**

W `mbr/produkt_pola/routes.py` dopisz:

```python
@produkt_pola_bp.route("/api/produkt-pola", methods=["POST"])
@role_required("admin", "technolog")
def create_pole_endpoint():
    payload = request.get_json(silent=True) or {}
    user_id = _current_user_id()
    with db_session() as db:
        try:
            pole_id = pp.create_pole(db, payload, user_id=user_id)
            db.commit()
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            # UNIQUE constraint
            if "UNIQUE" in str(e) or "constraint" in str(e).lower():
                return jsonify({"error": "kod already exists for this scope+scope_id"}), 409
            raise
    return jsonify({"pole_id": pole_id}), 201


def _current_user_id() -> int | None:
    """Resolve current user.id from session login."""
    from flask import session
    user = session.get("user") or {}
    login = user.get("login")
    if not login:
        return None
    with db_session() as db:
        row = db.execute("SELECT id FROM workers WHERE nickname=? OR inicjaly=?",
                         (login, login)).fetchone()
        return row["id"] if row else None
```

- [ ] **Step 4: Uruchom testy, potwierdź PASS**

```bash
pytest tests/test_produkt_pola_api.py -v -k "post"
```

Expected: 4 testy PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/produkt_pola/routes.py tests/test_produkt_pola_api.py
git commit -m "feat(produkt_pola): POST /api/produkt-pola create definicja"
```

---

## Task 9: API PUT/DELETE `/api/produkt-pola/<id>`

**Files:**
- Modify: `mbr/produkt_pola/routes.py`
- Modify: `tests/test_produkt_pola_api.py`

- [ ] **Step 1: Napisz testy PUT/DELETE**

Dopisz do `tests/test_produkt_pola_api.py`:

```python
def test_put_produkt_pola_update_label(monkeypatch, db):
    pid = pp.create_pole(db, {
        "scope": "produkt", "scope_id": 1, "kod": "k",
        "label_pl": "Stary", "typ_danych": "text", "miejsca": [],
    }, user_id=1)
    db.commit()
    c = _client(monkeypatch, db)
    r = c.put(f"/api/produkt-pola/{pid}", json={"label_pl": "Nowy"})
    assert r.status_code == 200
    row = db.execute("SELECT label_pl FROM produkt_pola WHERE id=?", (pid,)).fetchone()
    assert row["label_pl"] == "Nowy"


def test_put_produkt_pola_kod_immutable(monkeypatch, db):
    pid = pp.create_pole(db, {
        "scope": "produkt", "scope_id": 1, "kod": "k",
        "label_pl": "L", "typ_danych": "text", "miejsca": [],
    }, user_id=1)
    db.commit()
    c = _client(monkeypatch, db)
    r = c.put(f"/api/produkt-pola/{pid}", json={"kod": "inny"})
    assert r.status_code == 400


def test_delete_produkt_pola_soft(monkeypatch, db):
    pid = pp.create_pole(db, {
        "scope": "produkt", "scope_id": 1, "kod": "k",
        "label_pl": "L", "typ_danych": "text", "miejsca": [],
    }, user_id=1)
    db.commit()
    c = _client(monkeypatch, db)
    r = c.delete(f"/api/produkt-pola/{pid}")
    assert r.status_code == 200
    row = db.execute("SELECT aktywne FROM produkt_pola WHERE id=?", (pid,)).fetchone()
    assert row["aktywne"] == 0
```

- [ ] **Step 2: Uruchom testy, potwierdź FAIL**

```bash
pytest tests/test_produkt_pola_api.py -v -k "put or delete"
```

Expected: FAIL — endpointy nie istnieją.

- [ ] **Step 3: Dodaj PUT i DELETE**

W `mbr/produkt_pola/routes.py` dopisz:

```python
@produkt_pola_bp.route("/api/produkt-pola/<int:pole_id>", methods=["PUT"])
@role_required("admin", "technolog")
def update_pole_endpoint(pole_id: int):
    patch = request.get_json(silent=True) or {}
    user_id = _current_user_id()
    with db_session() as db:
        try:
            pp.update_pole(db, pole_id, patch, user_id=user_id)
            db.commit()
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


@produkt_pola_bp.route("/api/produkt-pola/<int:pole_id>", methods=["DELETE"])
@role_required("admin", "technolog")
def deactivate_pole_endpoint(pole_id: int):
    user_id = _current_user_id()
    with db_session() as db:
        try:
            pp.deactivate_pole(db, pole_id, user_id=user_id)
            db.commit()
        except ValueError as e:
            return jsonify({"error": str(e)}), 404
    return jsonify({"ok": True})
```

- [ ] **Step 4: Uruchom testy, potwierdź PASS**

```bash
pytest tests/test_produkt_pola_api.py -v
```

Expected: wszystkie testy PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/produkt_pola/routes.py tests/test_produkt_pola_api.py
git commit -m "feat(produkt_pola): PUT/DELETE /api/produkt-pola/<id>"
```

---

## Task 10: API PUT `/api/ebr/<ebr_id>/pola/<pole_id>` (set wartość)

**Files:**
- Modify: `mbr/produkt_pola/routes.py`
- Modify: `tests/test_produkt_pola_api.py`

- [ ] **Step 1: Napisz testy PUT wartości**

Dopisz do `tests/test_produkt_pola_api.py`:

```python
@pytest.fixture
def db_with_ebr(db):
    db.execute("INSERT INTO mbr_templates (id, produkt, wersja, status, etapy_json, "
               "parametry_lab, utworzony_przez, dt_utworzenia) "
               "VALUES (1, 'Monamid_KO', 1, 'active', '[]', '{}', 't', '2026-05-02')")
    db.execute("INSERT INTO ebr_batches (id, batch_id, mbr_id, nr_partii, dt_start, status) "
               "VALUES (1, 'B1', 1, '001', '2026-05-02', 'active')")
    db.commit()
    return db


def test_put_ebr_pola_value(monkeypatch, db_with_ebr):
    pid = pp.create_pole(db_with_ebr, {
        "scope": "produkt", "scope_id": 1, "kod": "nr_zam",
        "label_pl": "Nr", "typ_danych": "text", "miejsca": ["hero"],
    }, user_id=1)
    db_with_ebr.commit()
    c = _client(monkeypatch, db_with_ebr, rola="lab")
    r = c.put(f"/api/ebr/1/pola/{pid}", json={"wartosc": "ZAM/1"})
    assert r.status_code == 200
    row = db_with_ebr.execute(
        "SELECT wartosc FROM ebr_pola_wartosci WHERE ebr_id=1 AND pole_id=?", (pid,)
    ).fetchone()
    assert row["wartosc"] == "ZAM/1"


def test_put_ebr_pola_clear_to_null(monkeypatch, db_with_ebr):
    pid = pp.create_pole(db_with_ebr, {
        "scope": "produkt", "scope_id": 1, "kod": "k",
        "label_pl": "L", "typ_danych": "text", "miejsca": ["hero"],
    }, user_id=1)
    pp.set_wartosc(db_with_ebr, 1, pid, "X", user_id=1)
    db_with_ebr.commit()
    c = _client(monkeypatch, db_with_ebr, rola="lab")
    r = c.put(f"/api/ebr/1/pola/{pid}", json={"wartosc": None})
    assert r.status_code == 200
    row = db_with_ebr.execute(
        "SELECT wartosc FROM ebr_pola_wartosci WHERE ebr_id=1 AND pole_id=?", (pid,)
    ).fetchone()
    assert row["wartosc"] is None


def test_put_ebr_pola_invalid_number(monkeypatch, db_with_ebr):
    pid = pp.create_pole(db_with_ebr, {
        "scope": "produkt", "scope_id": 1, "kod": "i",
        "label_pl": "I", "typ_danych": "number", "miejsca": ["hero"],
    }, user_id=1)
    db_with_ebr.commit()
    c = _client(monkeypatch, db_with_ebr, rola="lab")
    r = c.put(f"/api/ebr/1/pola/{pid}", json={"wartosc": "abc"})
    assert r.status_code == 400
```

- [ ] **Step 2: Uruchom testy, potwierdź FAIL**

```bash
pytest tests/test_produkt_pola_api.py -v -k "put_ebr"
```

Expected: FAIL — endpoint nie istnieje.

- [ ] **Step 3: Dodaj PUT endpoint**

W `mbr/produkt_pola/routes.py` dopisz:

```python
@produkt_pola_bp.route("/api/ebr/<int:ebr_id>/pola/<int:pole_id>", methods=["PUT"])
@role_required("lab", "kj", "cert", "admin")
def set_ebr_pola_value(ebr_id: int, pole_id: int):
    payload = request.get_json(silent=True) or {}
    if "wartosc" not in payload:
        return jsonify({"error": "wartosc required (string|null)"}), 400
    user_id = _current_user_id()
    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        if ebr is None:
            return jsonify({"error": "ebr not found"}), 404
        try:
            pp.set_wartosc(db, ebr_id, pole_id, payload["wartosc"], user_id=user_id)
            db.commit()
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})
```

- [ ] **Step 4: Uruchom testy, potwierdź PASS**

```bash
pytest tests/test_produkt_pola_api.py -v
```

Expected: wszystkie testy PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/produkt_pola/routes.py tests/test_produkt_pola_api.py
git commit -m "feat(produkt_pola): PUT /api/ebr/<id>/pola/<pole_id> set wartosc"
```

---

## Task 11: UI definicji w `parametry_editor.html` (scope=produkt)

**Files:**
- Modify: `mbr/templates/parametry_editor.html`

- [ ] **Step 1: Sprawdź jak wygląda istniejący panel produktu w `parametry_editor.html`**

```bash
grep -n "panel-produkt\|tab-produkt\|produkt_id\|wybrany.*produkt" mbr/templates/parametry_editor.html | head -20
```

Zlokalizuj sekcję panelu produktu (gdzie technolog edytuje produkt). Zanotuj id i strukturę.

- [ ] **Step 2: Dodaj zakładkę / sekcję "Pola dodatkowe" w panelu produktu**

Wstaw nową sekcję w panelu produktu (per produkt — render zależnie od wybranego produktu). Struktura:

```html
<!-- Sekcja: Pola dodatkowe (scope=produkt) -->
<div class="pp-section" id="pp-section-produkt" data-produkt-id="">
  <h3>Pola dodatkowe</h3>
  <p class="pp-help">Pola wpisywane przez laboranta w modalu / Hero, widoczne w widoku Ukończone.</p>
  <table class="pp-table">
    <thead>
      <tr>
        <th>Kod</th><th>Etykieta</th><th>Typ</th><th>Miejsca</th>
        <th>Typy rejestracji</th><th>Obow.</th><th>Kol.</th><th></th>
      </tr>
    </thead>
    <tbody id="pp-tbody-produkt"></tbody>
  </table>
  <button type="button" id="pp-add-produkt" class="btn-secondary">+ Dodaj pole</button>
</div>

<!-- Modal: Dodaj/edytuj pole -->
<div class="pp-modal" id="pp-modal" style="display:none">
  <div class="pp-modal-inner">
    <h3 id="pp-modal-title">Nowe pole</h3>
    <input type="hidden" id="pp-pole-id" value="">
    <input type="hidden" id="pp-scope" value="">
    <input type="hidden" id="pp-scope-id" value="">

    <label>Kod (snake_case): <input type="text" id="pp-kod" pattern="^[a-z][a-z0-9_]*$"></label>
    <label>Etykieta PL: <input type="text" id="pp-label"></label>
    <label>Typ danych:
      <select id="pp-typ">
        <option value="text">text</option>
        <option value="number">number</option>
        <option value="date">date</option>
      </select>
    </label>
    <label>Jednostka (np. kg, %): <input type="text" id="pp-jedn"></label>
    <fieldset><legend>Miejsca</legend>
      <label><input type="checkbox" class="pp-miejsce" value="modal"> Modal tworzenia</label>
      <label><input type="checkbox" class="pp-miejsce" value="hero"> Hero (edycja)</label>
      <label><input type="checkbox" class="pp-miejsce" value="ukonczone"> Widok Ukończone</label>
    </fieldset>
    <fieldset><legend>Typy rejestracji (puste = wszystkie)</legend>
      <label><input type="checkbox" class="pp-typ-rej" value="szarza"> Szarża</label>
      <label><input type="checkbox" class="pp-typ-rej" value="zbiornik"> Zbiornik</label>
      <label><input type="checkbox" class="pp-typ-rej" value="platkowanie"> Płatkowanie</label>
    </fieldset>
    <label><input type="checkbox" id="pp-obow"> Obowiązkowe (gwiazdka, bez blokady)</label>
    <label>Kolejność: <input type="number" id="pp-kol" value="0"></label>
    <div class="pp-modal-actions">
      <button type="button" id="pp-save" class="btn-primary">Zapisz</button>
      <button type="button" id="pp-cancel" class="btn-secondary">Anuluj</button>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Dodaj JS rendering + CRUD**

Wstaw na końcu pliku, w istniejącym `<script>` block lub nowym:

```javascript
(function () {
  const tbody = document.getElementById('pp-tbody-produkt');
  const modal = document.getElementById('pp-modal');
  const title = document.getElementById('pp-modal-title');
  const $ = id => document.getElementById(id);

  function fetchPola(produktId) {
    return fetch(`/api/produkt-pola?scope=produkt&scope_id=${produktId}&only_active=0`)
      .then(r => r.json()).then(d => d.pola || []);
  }

  function renderRow(p) {
    const tr = document.createElement('tr');
    if (!p.aktywne) tr.style.opacity = '0.5';
    tr.innerHTML = `
      <td><code>${p.kod}</code></td>
      <td>${p.label_pl}${p.obowiazkowe ? ' *' : ''}</td>
      <td>${p.typ_danych}${p.jednostka ? ` [${p.jednostka}]` : ''}</td>
      <td>${(p.miejsca || []).join(', ')}</td>
      <td>${p.typy_rejestracji ? p.typy_rejestracji.join(', ') : '(wszystkie)'}</td>
      <td>${p.obowiazkowe ? '✓' : ''}</td>
      <td>${p.kolejnosc}</td>
      <td>
        <button class="pp-edit" data-id="${p.id}">Edytuj</button>
        ${p.aktywne ? `<button class="pp-deact" data-id="${p.id}">Wyłącz</button>` : ''}
      </td>`;
    return tr;
  }

  function refresh(produktId) {
    fetchPola(produktId).then(pola => {
      tbody.innerHTML = '';
      pola.forEach(p => tbody.appendChild(renderRow(p)));
    });
  }

  function openModal(produktId, existing) {
    title.textContent = existing ? 'Edytuj pole' : 'Nowe pole';
    $('pp-pole-id').value = existing ? existing.id : '';
    $('pp-scope').value = 'produkt';
    $('pp-scope-id').value = produktId;
    $('pp-kod').value = existing ? existing.kod : '';
    $('pp-kod').disabled = !!existing;  // immutable
    $('pp-label').value = existing ? existing.label_pl : '';
    $('pp-typ').value = existing ? existing.typ_danych : 'text';
    $('pp-jedn').value = existing ? (existing.jednostka || '') : '';
    document.querySelectorAll('.pp-miejsce').forEach(cb => {
      cb.checked = existing ? (existing.miejsca || []).includes(cb.value) : false;
    });
    document.querySelectorAll('.pp-typ-rej').forEach(cb => {
      const tr = existing ? existing.typy_rejestracji : null;
      cb.checked = tr ? tr.includes(cb.value) : false;
    });
    $('pp-obow').checked = existing ? !!existing.obowiazkowe : false;
    $('pp-kol').value = existing ? existing.kolejnosc : 0;
    modal.style.display = 'block';
  }

  function collectPayload() {
    const miejsca = [...document.querySelectorAll('.pp-miejsce:checked')].map(cb => cb.value);
    const typy = [...document.querySelectorAll('.pp-typ-rej:checked')].map(cb => cb.value);
    return {
      scope: $('pp-scope').value,
      scope_id: parseInt($('pp-scope-id').value, 10),
      kod: $('pp-kod').value.trim(),
      label_pl: $('pp-label').value.trim(),
      typ_danych: $('pp-typ').value,
      jednostka: $('pp-jedn').value.trim() || null,
      miejsca: miejsca,
      typy_rejestracji: typy.length ? typy : null,
      obowiazkowe: $('pp-obow').checked,
      kolejnosc: parseInt($('pp-kol').value, 10) || 0,
    };
  }

  // Wire up buttons
  document.addEventListener('click', (e) => {
    const produktId = parseInt(document.getElementById('pp-section-produkt').dataset.produktId, 10);
    if (!produktId) return;
    if (e.target.id === 'pp-add-produkt') openModal(produktId, null);
    if (e.target.classList.contains('pp-edit')) {
      const id = parseInt(e.target.dataset.id, 10);
      fetchPola(produktId).then(pola => openModal(produktId, pola.find(p => p.id === id)));
    }
    if (e.target.classList.contains('pp-deact')) {
      if (!confirm('Wyłączyć to pole?')) return;
      fetch(`/api/produkt-pola/${e.target.dataset.id}`, {method: 'DELETE'})
        .then(() => refresh(produktId));
    }
    if (e.target.id === 'pp-cancel') modal.style.display = 'none';
    if (e.target.id === 'pp-save') {
      const id = $('pp-pole-id').value;
      const payload = collectPayload();
      const url = id ? `/api/produkt-pola/${id}` : '/api/produkt-pola';
      const method = id ? 'PUT' : 'POST';
      fetch(url, {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)})
        .then(r => r.json().then(d => ({status: r.status, body: d})))
        .then(({status, body}) => {
          if (status >= 400) { alert('Błąd: ' + (body.error || 'unknown')); return; }
          modal.style.display = 'none';
          refresh(produktId);
        });
    }
  });

  // Hook into existing produkt-selection event in parametry_editor
  // (replace `selectProduktEvent` with the actual event/function name in parametry_editor.html)
  window.PP_refresh_produkt = function(produktId) {
    document.getElementById('pp-section-produkt').dataset.produktId = produktId;
    refresh(produktId);
  };
})();
```

- [ ] **Step 4: Hookuj `PP_refresh_produkt` do istniejącego flow wyboru produktu**

Znajdź w `parametry_editor.html` miejsce gdzie technolog wybiera produkt (np. funkcję `selectProdukt(id)` lub event `change` na select). Tam dodaj:

```javascript
if (window.PP_refresh_produkt) window.PP_refresh_produkt(produktId);
```

- [ ] **Step 5: Manual smoke test**

Uruchom dev server:

```bash
python -m mbr.app
```

W przeglądarce: zaloguj jako admin, otwórz `/admin/produkty` (redirect do parametry_editor), wybierz produkt Monamid_KO, sekcja "Pola dodatkowe" widoczna, dodaj pole `nr_zamowienia`, zapisz, edytuj, wyłącz. Wszystko działa.

- [ ] **Step 6: Commit**

```bash
git add mbr/templates/parametry_editor.html
git commit -m "feat(produkt_pola): UI CRUD definicji per produkt w technolog editor"
```

---

## Task 12: UI definicji w `wzory_cert.html` (scope=cert_variant)

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html`

- [ ] **Step 1: Zlokalizuj panel wariantu w `wzory_cert.html`**

```bash
grep -n "panel-produkt\|wc-var-\|wc-variant" mbr/templates/admin/wzory_cert.html | head -20
```

Zanotuj strukturę panelu wariantu (gdzie admin edytuje per-variant settings — `wc-var-avon-code` itp. już są).

- [ ] **Step 2: Dodaj sekcję "Stałe pola" do panelu wariantu**

Wstaw obok istniejącego `wc-var-avon`:

```html
<div class="wc-static-fields" id="wc-static-fields-section">
  <h4>Stałe pola wariantu</h4>
  <p class="wc-help">Wartości podstawiane do świadectwa przez <code>{% raw %}{{ pola.&lt;kod&gt; }}{% endraw %}</code> w master DOCX.</p>
  <table class="wc-static-table">
    <thead><tr><th>Kod</th><th>Etykieta</th><th>Wartość</th><th>Kol.</th><th></th></tr></thead>
    <tbody id="wc-static-tbody"></tbody>
  </table>
  <button type="button" id="wc-static-add" class="btn-secondary">+ Dodaj stałe pole</button>
</div>

<!-- Modal CRUD pole scope=cert_variant -->
<div class="wc-static-modal" id="wc-static-modal" style="display:none">
  <div class="wc-static-modal-inner">
    <h3 id="wc-static-modal-title">Nowe stałe pole</h3>
    <input type="hidden" id="wc-static-id">
    <input type="hidden" id="wc-static-variant-id">
    <label>Kod (snake_case): <input type="text" id="wc-static-kod" pattern="^[a-z][a-z0-9_]*$"></label>
    <label>Etykieta: <input type="text" id="wc-static-label"></label>
    <label>Wartość stała: <input type="text" id="wc-static-val"></label>
    <label>Kolejność: <input type="number" id="wc-static-kol" value="0"></label>
    <div>
      <button type="button" id="wc-static-save" class="btn-primary">Zapisz</button>
      <button type="button" id="wc-static-cancel" class="btn-secondary">Anuluj</button>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Dodaj JS dla CRUD scope=cert_variant**

W `<script>` block:

```javascript
(function () {
  const $$ = id => document.getElementById(id);
  const tbody = $$('wc-static-tbody');
  const modal = $$('wc-static-modal');

  function fetchPola(variantId) {
    return fetch(`/api/produkt-pola?scope=cert_variant&scope_id=${variantId}&only_active=0`)
      .then(r => r.json()).then(d => d.pola || []);
  }

  function row(p) {
    const tr = document.createElement('tr');
    if (!p.aktywne) tr.style.opacity = '0.5';
    tr.innerHTML = `
      <td><code>${p.kod}</code></td>
      <td>${p.label_pl}</td>
      <td>${p.wartosc_stala || ''}</td>
      <td>${p.kolejnosc}</td>
      <td>
        <button class="wc-static-edit" data-id="${p.id}">Edytuj</button>
        ${p.aktywne ? `<button class="wc-static-deact" data-id="${p.id}">Wyłącz</button>` : ''}
      </td>`;
    return tr;
  }

  function refresh(variantId) {
    fetchPola(variantId).then(pola => {
      tbody.innerHTML = '';
      pola.forEach(p => tbody.appendChild(row(p)));
    });
  }

  function openModal(variantId, existing) {
    $$('wc-static-modal-title').textContent = existing ? 'Edytuj stałe pole' : 'Nowe stałe pole';
    $$('wc-static-id').value = existing ? existing.id : '';
    $$('wc-static-variant-id').value = variantId;
    $$('wc-static-kod').value = existing ? existing.kod : '';
    $$('wc-static-kod').disabled = !!existing;
    $$('wc-static-label').value = existing ? existing.label_pl : '';
    $$('wc-static-val').value = existing ? (existing.wartosc_stala || '') : '';
    $$('wc-static-kol').value = existing ? existing.kolejnosc : 0;
    modal.style.display = 'block';
  }

  document.addEventListener('click', (e) => {
    const variantId = parseInt($$('wc-static-fields-section').dataset.variantId || '0', 10);
    if (e.target.id === 'wc-static-add' && variantId) openModal(variantId, null);
    if (e.target.classList.contains('wc-static-edit')) {
      fetchPola(variantId).then(pola => openModal(variantId,
        pola.find(p => p.id === parseInt(e.target.dataset.id, 10))));
    }
    if (e.target.classList.contains('wc-static-deact')) {
      if (!confirm('Wyłączyć?')) return;
      fetch(`/api/produkt-pola/${e.target.dataset.id}`, {method: 'DELETE'})
        .then(() => refresh(variantId));
    }
    if (e.target.id === 'wc-static-cancel') modal.style.display = 'none';
    if (e.target.id === 'wc-static-save') {
      const id = $$('wc-static-id').value;
      const payload = {
        scope: 'cert_variant',
        scope_id: parseInt($$('wc-static-variant-id').value, 10),
        kod: $$('wc-static-kod').value.trim(),
        label_pl: $$('wc-static-label').value.trim(),
        typ_danych: 'text',
        wartosc_stala: $$('wc-static-val').value,
        kolejnosc: parseInt($$('wc-static-kol').value, 10) || 0,
        miejsca: [],
      };
      fetch(id ? `/api/produkt-pola/${id}` : '/api/produkt-pola', {
        method: id ? 'PUT' : 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      })
        .then(r => r.json().then(d => ({status: r.status, body: d})))
        .then(({status, body}) => {
          if (status >= 400) { alert('Błąd: ' + (body.error || 'unknown')); return; }
          modal.style.display = 'none';
          refresh(variantId);
        });
    }
  });

  window.WC_static_refresh = function(variantId) {
    $$('wc-static-fields-section').dataset.variantId = variantId;
    refresh(variantId);
  };
})();
```

- [ ] **Step 4: Hookuj `WC_static_refresh` do wyboru wariantu**

Znajdź funkcję która ustawia aktywny wariant w `wzory_cert.html` (np. `selectVariant(id)` lub podobną), tam dodaj:

```javascript
if (window.WC_static_refresh) window.WC_static_refresh(variantId);
```

- [ ] **Step 5: Manual smoke test**

W przeglądarce: `/admin/wzory-cert`, wybierz produkt Chegina_K40GLOLMB, wybierz wariant "Kosmepol", sekcja "Stałe pola wariantu" pokazuje pustą tabelę. Klik "Dodaj", wpisz `kod=nr_zamowienia_kosmepol, label=Nr zamówienia (Kosmepol), wartość=KSM/2026/STALY/001`. Zapisz, edytuj, wyłącz.

- [ ] **Step 6: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(produkt_pola): UI CRUD stałych pól per wariant świadectwa"
```

---

## Task 13: Modal "Nowa szarża" — dynamiczne pola

**Files:**
- Modify: `mbr/templates/laborant/_modal_nowa_szarza.html`
- Modify: `mbr/laborant/models.py::create_ebr` (lub `routes.py::api_create_ebr`)
- Test: rozszerzenie `tests/test_produkt_pola_api.py` lub nowe `tests/test_modal_pola.py`

- [ ] **Step 1: Zlokalizuj endpoint create_ebr**

```bash
grep -n "def create_ebr\|def api_create_ebr\|api/ebr.*POST\|nowa.*szarza" mbr/laborant/routes.py mbr/laborant/models.py | head
```

Zanotuj sygnaturę i miejsce wstawiania nowych logik.

- [ ] **Step 2: Test backend — create_ebr akceptuje `pola`**

`tests/test_modal_pola.py` (nowy):

```python
"""Modal create EBR with dynamic pola."""
import sqlite3
import pytest
from contextlib import contextmanager
from mbr.models import init_mbr_tables
from mbr.shared import produkt_pola as pp


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    conn.execute("INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
                 "VALUES (1, 'T', 'U', 'TU', 'TU', 1)")
    conn.execute("INSERT INTO produkty (id, nazwa, kod, aktywny) VALUES (1, 'Monamid_KO', 'MKO', 1)")
    conn.execute("INSERT INTO mbr_templates (id, produkt, wersja, status, etapy_json, "
                 "parametry_lab, utworzony_przez, dt_utworzenia) "
                 "VALUES (1, 'Monamid_KO', 1, 'active', '[]', '{}', 't', '2026-05-02')")
    conn.commit()
    yield conn
    conn.close()


def _c(monkeypatch, db, rola="lab"):
    import mbr.db, mbr.laborant.routes
    @contextmanager
    def fake(): yield db
    monkeypatch.setattr(mbr.db, "db_session", fake)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake)
    from mbr.app import create_app
    app = create_app(); app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as s:
        s["user"] = {"login": "TU", "rola": rola, "imie_nazwisko": None}
        s["shift_workers"] = [1]
    return c


def test_create_ebr_with_pola_persists_values(monkeypatch, db):
    pid = pp.create_pole(db, {
        "scope": "produkt", "scope_id": 1, "kod": "nr_zam",
        "label_pl": "Nr", "typ_danych": "text", "miejsca": ["modal"],
    }, user_id=1)
    db.commit()
    c = _c(monkeypatch, db)
    # Replace endpoint path with the actual create_ebr route in laborant
    r = c.post("/api/ebr/create", json={
        "produkt": "Monamid_KO", "nr_partii": "100",
        "typ": "szarza", "wielkosc_kg": 1000,
        "pola": {str(pid): "ZAM/123"},
    })
    assert r.status_code in (200, 201), r.json
    ebr_id = r.json["ebr_id"]
    row = db.execute("SELECT wartosc FROM ebr_pola_wartosci WHERE ebr_id=? AND pole_id=?",
                     (ebr_id, pid)).fetchone()
    assert row["wartosc"] == "ZAM/123"
```

NOTE: ścieżkę `/api/ebr/create` zmień na faktyczny endpoint create_ebr w laborant — sprawdź w grep.

- [ ] **Step 3: Uruchom test, potwierdź FAIL**

```bash
pytest tests/test_modal_pola.py -v
```

Expected: FAIL — backend nie persistuje `pola`.

- [ ] **Step 4: Rozszerz endpoint create_ebr o obsługę `pola`**

W `mbr/laborant/routes.py` (lub `models.py::create_ebr`) po utworzeniu szarży i przed `db.commit()`:

```python
    # Persist dynamic produkt_pola values from modal
    pola_payload = (request.get_json(silent=True) or {}).get("pola") or {}
    if pola_payload:
        from mbr.shared import produkt_pola as _pp
        for pole_id_s, val in pola_payload.items():
            if not val:
                continue  # skip empty
            try:
                _pp.set_wartosc(db, ebr_id, int(pole_id_s), val,
                                user_id=_resolve_current_user_id())
            except ValueError:
                # Invalid value silently skipped — modal validation should catch
                pass
```

(`_resolve_current_user_id()` lub odpowiednik istnieje w laborant/routes.py — użyj.)

- [ ] **Step 5: Test PASS**

```bash
pytest tests/test_modal_pola.py -v
```

Expected: PASS.

- [ ] **Step 6: Frontend — dodaj sekcję "Pola dodatkowe" w modalu**

W `mbr/templates/laborant/_modal_nowa_szarza.html` przed przyciskiem submitu (np. przed `<button type="submit">Utwórz</button>`):

```html
<div class="ns-extra-section" id="ns-extra-section" style="display:none">
  <h4 style="margin-top:16px;border-top:1px solid var(--border);padding-top:12px;">Pola dodatkowe</h4>
  <div id="ns-extra-fields"></div>
</div>
```

- [ ] **Step 7: JS — pobierz definicje, render, dołącz do submit**

W `<script>` block (gdzie jest logika modalu — szukaj funkcji obsługującej zmianę produktu lub typu rejestracji):

```javascript
(function () {
  const section = document.getElementById('ns-extra-section');
  const fields = document.getElementById('ns-extra-fields');

  function loadExtras(produktId, typ) {
    fields.innerHTML = '';
    section.style.display = 'none';
    if (!produktId) return;
    fetch(`/api/produkt-pola?scope=produkt&scope_id=${produktId}`)
      .then(r => r.json()).then(d => {
        const pola = (d.pola || []).filter(p =>
          p.miejsca.includes('modal') &&
          (!p.typy_rejestracji || p.typy_rejestracji.includes(typ))
        );
        if (!pola.length) return;
        section.style.display = 'block';
        pola.forEach(p => {
          const wrap = document.createElement('label');
          wrap.style.display = 'block';
          wrap.style.margin = '8px 0';
          const star = p.obowiazkowe ? ' *' : '';
          const unit = p.jednostka ? ` [${p.jednostka}]` : '';
          let inputType = 'text';
          if (p.typ_danych === 'number') inputType = 'text';  // accept comma
          if (p.typ_danych === 'date') inputType = 'date';
          wrap.innerHTML = `
            <span>${p.label_pl}${unit}${star}</span>
            <input type="${inputType}" name="pola[${p.id}]" data-pole-id="${p.id}"
                   class="ns-extra-input" inputmode="${p.typ_danych === 'number' ? 'decimal' : 'text'}">
          `;
          fields.appendChild(wrap);
        });
      });
  }

  // Hook to existing modal events — replace selectors with actual ones
  // Example wiring (assumes there are #ns-produkt and #ns-typ-rejestracji selects):
  function refresh() {
    const produktId = document.getElementById('ns-produkt-id-hidden')?.value
                   || document.getElementById('ns-produkt')?.value;
    const typ = document.getElementById('ns-typ-rejestracji')?.value || 'szarza';
    if (produktId) loadExtras(produktId, typ);
  }
  document.getElementById('ns-produkt')?.addEventListener('change', refresh);
  document.getElementById('ns-typ-rejestracji')?.addEventListener('change', refresh);

  // Patch submit serializer — add pola object
  window.NS_collect_extras = function () {
    const out = {};
    document.querySelectorAll('.ns-extra-input').forEach(inp => {
      const id = inp.dataset.poleId;
      if (inp.value !== '') out[id] = inp.value;
    });
    return out;
  };
})();
```

W istniejącej funkcji submitu modalu, do payloadu POST `/api/ebr/create` (lub odpowiedniego endpointu) dodaj:

```javascript
payload.pola = window.NS_collect_extras ? window.NS_collect_extras() : {};
```

- [ ] **Step 8: Manual smoke test**

Uruchom dev: `python -m mbr.app`. Dodaj pole `nr_zamowienia` dla Monamid KO (Task 11). Otwórz modal "Nowa szarża", wybierz Monamid KO, sekcja "Pola dodatkowe" pojawia się z polem `Nr zamówienia`. Wpisz `ZAM/123`, utwórz szarżę. Sprawdź w bazie: `sqlite3 data/batch_db.sqlite "SELECT * FROM ebr_pola_wartosci"`.

- [ ] **Step 9: Commit**

```bash
git add mbr/templates/laborant/_modal_nowa_szarza.html mbr/laborant/routes.py mbr/laborant/models.py tests/test_modal_pola.py
git commit -m "feat(produkt_pola): modal nowa szarża z dynamicznymi polami"
```

---

## Task 14: Hero — dynamic fields rendering + edit

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html` (sekcja Hero `cv-hero`, ~linia 414+)

- [ ] **Step 1: Zlokalizuj cv-hero w `_fast_entry_content.html`**

```bash
grep -n "cv-hero\|hero" mbr/templates/laborant/_fast_entry_content.html | head -10
```

- [ ] **Step 2: Dodaj sekcję "Pola dodatkowe" w hero**

Po istniejących blokach Hero (po nagłówku z produktem/szarżą, przed parametrami) dodaj:

```html
<div class="cv-extra-section" id="cv-extra-section" style="display:none">
  <h4 style="margin:12px 0 6px;color:var(--text-sec);font-size:13px;">Pola dodatkowe</h4>
  <div id="cv-extra-fields" class="cv-extra-grid"></div>
</div>
```

CSS w `<style>`:

```css
.cv-extra-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; }
.cv-extra-grid label { font-size: 12px; color: var(--text-sec); }
.cv-extra-grid input { width: 100%; padding: 4px 6px; font-size: 13px;
                       border: 1px solid var(--border); border-radius: 4px; }
.cv-extra-grid input:disabled { background: var(--bg-disabled); }
.cv-extra-required-label::after { content: ' *'; color: var(--danger); }
```

- [ ] **Step 3: JS — load + render + save inline**

W odpowiednim `<script>` block (gdzie hero się renderuje per szarża):

```javascript
(function () {
  const section = document.getElementById('cv-extra-section');
  const grid = document.getElementById('cv-extra-fields');

  async function renderHeroExtras(ebrId, produktId, typ, isReadonly) {
    grid.innerHTML = '';
    section.style.display = 'none';
    if (!ebrId || !produktId) return;
    const [defResp, valResp] = await Promise.all([
      fetch(`/api/produkt-pola?scope=produkt&scope_id=${produktId}`).then(r => r.json()),
      fetch(`/api/ebr/${ebrId}/pola`).then(r => r.json()),
    ]);
    const pola = (defResp.pola || []).filter(p =>
      p.miejsca.includes('hero') &&
      (!p.typy_rejestracji || p.typy_rejestracji.includes(typ))
    );
    if (!pola.length) return;
    section.style.display = 'block';
    const wartosci = valResp.wartosci || {};
    pola.forEach(p => {
      const wrap = document.createElement('label');
      wrap.className = p.obowiazkowe ? 'cv-extra-required-label' : '';
      const unit = p.jednostka ? ` [${p.jednostka}]` : '';
      const inputType = p.typ_danych === 'date' ? 'date' : 'text';
      const initVal = wartosci[p.kod] || '';
      wrap.innerHTML = `<span>${p.label_pl}${unit}</span>
        <input type="${inputType}" data-pole-id="${p.id}" data-kod="${p.kod}"
               value="${initVal}" ${isReadonly ? 'disabled' : ''}>`;
      grid.appendChild(wrap);
    });
    grid.querySelectorAll('input').forEach(inp => {
      inp.addEventListener('blur', () => savePole(ebrId, inp));
    });
  }

  async function savePole(ebrId, inp) {
    const poleId = inp.dataset.poleId;
    const val = inp.value === '' ? null : inp.value;
    const r = await fetch(`/api/ebr/${ebrId}/pola/${poleId}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({wartosc: val}),
    });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      alert('Błąd zapisu: ' + (d.error || r.status));
      inp.style.borderColor = 'var(--danger)';
    } else {
      inp.style.borderColor = '';
    }
  }

  window.HERO_render_extras = renderHeroExtras;
})();
```

- [ ] **Step 4: Wywołanie HERO_render_extras w punkcie renderowania hero**

Znajdź miejsce w `_fast_entry_content.html` gdzie hero jest budowany dla wybranej szarży (zazwyczaj funkcja typu `renderHero(batch)` lub bind po wyborze szarży). Tam dodaj:

```javascript
if (window.HERO_render_extras) {
  // Replace placeholders with actual values from batch context
  HERO_render_extras(batch.ebr_id, batch.produkt_id, batch.typ || 'szarza', isReadonly);
}
```

(Gdzie `batch.produkt_id` to id produktu — może wymagać dodania query w backend lub wyciągnięcia z produkt_lookup. Jeśli batch nie ma `produkt_id`, dociągnij `GET /api/produkty?nazwa=<batch.produkt>`.)

- [ ] **Step 5: Manual smoke test**

Otwórz szarżę Monamid KO z polem `nr_zamowienia` ustawionym z modalu. Hero pokazuje sekcję "Pola dodatkowe" z wartością. Zmień, blur — zapis. Sprawdź w bazie.

- [ ] **Step 6: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat(produkt_pola): Hero z dynamicznymi polami i inline edit"
```

---

## Task 15: Registry models — `list_completed_registry` + `get_registry_columns`

**Files:**
- Modify: `mbr/registry/models.py`
- Create: `tests/test_registry_pola_columns.py`

- [ ] **Step 1: Test integracji rejestru**

`tests/test_registry_pola_columns.py`:

```python
"""Registry — dynamic columns from produkt_pola."""
import sqlite3
import pytest
from datetime import datetime
from mbr.models import init_mbr_tables
from mbr.shared import produkt_pola as pp
from mbr.registry import models as reg


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    conn.execute("INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
                 "VALUES (1, 'T', 'U', 'TU', 'TU', 1)")
    conn.execute("INSERT INTO produkty (id, nazwa, kod, aktywny) VALUES (1, 'Monamid_KO', 'MKO', 1)")
    conn.execute("INSERT INTO mbr_templates (id, produkt, wersja, status, etapy_json, parametry_lab, "
                 "utworzony_przez, dt_utworzenia) VALUES (1, 'Monamid_KO', 1, 'active', '[]', '{}', 't', '2026-05-02')")
    now = datetime.now().isoformat()
    conn.execute("INSERT INTO ebr_batches (id, batch_id, mbr_id, nr_partii, dt_start, dt_end, "
                 "status, typ) VALUES (1, 'B1', 1, '001', ?, ?, 'completed', 'szarza')", (now, now))
    conn.commit()
    yield conn
    conn.close()


def test_list_completed_includes_pola_dict(db):
    pid = pp.create_pole(db, {
        "scope": "produkt", "scope_id": 1, "kod": "nr_zam",
        "label_pl": "Nr zamówienia", "typ_danych": "text",
        "miejsca": ["ukonczone"],
    }, user_id=1)
    pp.set_wartosc(db, 1, pid, "ZAM/777", user_id=1)
    db.commit()
    rows = reg.list_completed_registry(db)
    assert len(rows) == 1
    assert rows[0]["pola"]["nr_zam"] == "ZAM/777"


def test_get_registry_columns_includes_dynamic(db):
    pp.create_pole(db, {
        "scope": "produkt", "scope_id": 1, "kod": "nr_zam",
        "label_pl": "Nr zamówienia", "typ_danych": "text",
        "miejsca": ["ukonczone"],
    }, user_id=1)
    pp.create_pole(db, {
        "scope": "produkt", "scope_id": 1, "kod": "ilosc_k",
        "label_pl": "Ilość konserwantuna", "typ_danych": "number", "jednostka": "kg",
        "miejsca": ["ukonczone"],
    }, user_id=1)
    db.commit()
    cols = reg.get_registry_columns(db)
    keys = [c["key"] for c in cols]
    assert "pola.nr_zam" in keys
    assert "pola.ilosc_k" in keys
    nr_col = next(c for c in cols if c["key"] == "pola.nr_zam")
    assert nr_col["label"] == "Nr zamówienia"
    ilosc_col = next(c for c in cols if c["key"] == "pola.ilosc_k")
    assert ilosc_col["label"] == "Ilość konserwantuna [kg]"


def test_get_registry_columns_excludes_inactive(db):
    pid = pp.create_pole(db, {
        "scope": "produkt", "scope_id": 1, "kod": "wylaczone",
        "label_pl": "W", "typ_danych": "text",
        "miejsca": ["ukonczone"],
    }, user_id=1)
    pp.deactivate_pole(db, pid, user_id=1)
    db.commit()
    cols = reg.get_registry_columns(db)
    keys = [c["key"] for c in cols]
    assert "pola.wylaczone" not in keys
```

- [ ] **Step 2: Uruchom testy, potwierdź FAIL**

```bash
pytest tests/test_registry_pola_columns.py -v
```

Expected: FAIL — funkcje rejestru nie zwracają `pola`.

- [ ] **Step 3: Rozszerz `list_completed_registry`**

W `mbr/registry/models.py::list_completed_registry`, po istniejącym wstawianiu `d["wyniki"]`:

```python
        # Dynamic produkt_pola values
        produkt_id_row = db.execute("SELECT id FROM produkty WHERE nazwa=?", (d["produkt"],)).fetchone()
        if produkt_id_row is not None:
            from mbr.shared.produkt_pola import get_wartosci_for_ebr
            d["pola"] = get_wartosci_for_ebr(db, d["ebr_id"], produkt_id_row["id"])
        else:
            d["pola"] = {}
```

- [ ] **Step 4: Rozszerz `get_registry_columns`**

W `mbr/registry/models.py::get_registry_columns`, po obecnym budowaniu kolumn z parametrów, dodaj:

```python
    # Dynamic produkt_pola columns (union across all active produkty)
    pola_rows = db.execute("""
        SELECT DISTINCT pp.kod, pp.label_pl, pp.jednostka, pp.kolejnosc
        FROM produkt_pola pp
        WHERE pp.scope='produkt' AND pp.aktywne=1
          AND pp.miejsca LIKE '%"ukonczone"%'
        ORDER BY pp.kolejnosc, pp.kod
    """).fetchall()
    for r in pola_rows:
        label = r["label_pl"]
        if r["jednostka"]:
            label = f"{label} [{r['jednostka']}]"
        columns.append({"key": f"pola.{r['kod']}", "label": label, "kind": "pola"})
```

(Dostosuj nazwę zmiennej `columns` do tego co już istnieje w `get_registry_columns`.)

- [ ] **Step 5: Uruchom testy, potwierdź PASS**

```bash
pytest tests/test_registry_pola_columns.py -v
```

Expected: 3 testy PASS.

- [ ] **Step 6: Commit**

```bash
git add mbr/registry/models.py tests/test_registry_pola_columns.py
git commit -m "feat(produkt_pola): rejestr ukonczonych — dynamiczne kolumny i wartosci"
```

---

## Task 16: Registry template — render kolumn przed "Uwagi"

**Files:**
- Modify: `mbr/templates/laborant/szarze_list.html` (~linia 1488 `th-uwagi`, ~1610 `td-uwagi`)

- [ ] **Step 1: Zlokalizuj jak są dziś budowane dynamiczne kolumny w template**

```bash
grep -n "th-\|getRegistryColumns\|columns\|registry.*columns\|pola\\." mbr/templates/laborant/szarze_list.html | head -30
```

- [ ] **Step 2: Wstaw render dynamicznych kolumn przed `th-uwagi`**

W okolicy linii 1488 (header) — przed:

```javascript
html += '<th class="th-uwagi" ...>Uwagi</th>';
```

dodaj iterację po dynamicznych kolumnach:

```javascript
// Dynamic produkt_pola columns
(window.REGISTRY_COLUMNS || []).filter(c => c.kind === 'pola').forEach(c => {
  html += `<th class="th-pola" style="min-width:120px;">${_htmlEsc(c.label)}</th>`;
});
```

W okolicy linii 1610 (cell) — przed `<td class="td-uwagi" ...>`:

```javascript
(window.REGISTRY_COLUMNS || []).filter(c => c.kind === 'pola').forEach(c => {
  const kod = c.key.replace('pola.', '');
  const val = (b.pola && b.pola[kod]) || '';
  html += `<td class="td-pola" style="font-size:12px;color:var(--text-sec);">${_htmlEsc(val)}</td>`;
});
```

- [ ] **Step 3: Sprawdź jak `REGISTRY_COLUMNS` jest exposed**

Endpoint który zwraca dane do `szarze_list.html` musi zwracać `columns` (z `get_registry_columns()`). Sprawdź:

```bash
grep -n "get_registry_columns\|REGISTRY_COLUMNS" mbr/registry/routes.py mbr/templates/laborant/szarze_list.html
```

Jeśli endpoint nie zwraca jeszcze `columns`, rozszerz go (zazwyczaj endpoint listing rejestru zwraca `{batches: [...], columns: [...]}`).

- [ ] **Step 4: Manual smoke test**

Uruchom dev. Stwórz szarżę Monamid KO z polami z modalu (Task 13). Zatwierdź szarżę (zmień status na completed). Otwórz `/registry/ukonczone` — kolumny "Nr zamówienia" / "Nr dopuszczenia oleju kokosowego" widoczne tuż przed "Uwagi" z wartościami.

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/laborant/szarze_list.html mbr/registry/routes.py
git commit -m "feat(produkt_pola): kolumny dynamiczne przed Uwagi w widoku Ukonczone"
```

---

## Task 17: Generator certów — sub-namespace `pola.<kod>`

**Files:**
- Modify: `mbr/certs/generator.py::build_context`
- Create: `tests/test_certs_pola_variant.py`

- [ ] **Step 1: Test build_context dla wariantu z polami**

`tests/test_certs_pola_variant.py`:

```python
"""Generator certów — sub-namespace pola dla scope=cert_variant."""
import sqlite3
import pytest
from mbr.models import init_mbr_tables
from mbr.shared import produkt_pola as pp


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    conn.execute("INSERT INTO produkty (id, nazwa, kod, aktywny) VALUES (1, 'Chegina_K40GLOLMB', 'K4', 1)")
    conn.execute("INSERT INTO cert_variants (id, produkt, variant_id, label) "
                 "VALUES (10, 'Chegina_K40GLOLMB', 'kosmepol', 'Kosmepol')")
    conn.execute("INSERT INTO cert_variants (id, produkt, variant_id, label) "
                 "VALUES (11, 'Chegina_K40GLOLMB', 'inny', 'Inny')")
    conn.execute("INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
                 "VALUES (1, 'T', 'U', 'TU', 'TU', 1)")
    conn.commit()
    yield conn
    conn.close()


def test_build_context_includes_pola_for_variant(db, monkeypatch):
    pp.create_pole(db, {
        "scope": "cert_variant", "scope_id": 10, "kod": "nr_zam_kosmepol",
        "label_pl": "Nr", "typ_danych": "text",
        "wartosc_stala": "KSM/2026/001",
    }, user_id=1)
    db.commit()
    from mbr.certs import generator
    pola = generator.build_pola_context(db, variant_id=10)
    assert pola == {"nr_zam_kosmepol": "KSM/2026/001"}


def test_build_context_isolates_pola_per_variant(db, monkeypatch):
    pp.create_pole(db, {
        "scope": "cert_variant", "scope_id": 10, "kod": "nr_zam_kosmepol",
        "label_pl": "Nr", "typ_danych": "text",
        "wartosc_stala": "KSM/A",
    }, user_id=1)
    pp.create_pole(db, {
        "scope": "cert_variant", "scope_id": 11, "kod": "nr_zam_inny",
        "label_pl": "Inny", "typ_danych": "text",
        "wartosc_stala": "INNY/B",
    }, user_id=1)
    db.commit()
    from mbr.certs import generator
    pola_kosmepol = generator.build_pola_context(db, variant_id=10)
    pola_inny = generator.build_pola_context(db, variant_id=11)
    assert "nr_zam_kosmepol" in pola_kosmepol
    assert "nr_zam_inny" not in pola_kosmepol
    assert "nr_zam_inny" in pola_inny
    assert "nr_zam_kosmepol" not in pola_inny


def test_build_context_excludes_inactive_pole(db, monkeypatch):
    pid = pp.create_pole(db, {
        "scope": "cert_variant", "scope_id": 10, "kod": "wylaczone",
        "label_pl": "W", "typ_danych": "text",
        "wartosc_stala": "X",
    }, user_id=1)
    pp.deactivate_pole(db, pid, user_id=1)
    db.commit()
    from mbr.certs import generator
    pola = generator.build_pola_context(db, variant_id=10)
    assert "wylaczone" not in pola
```

- [ ] **Step 2: Uruchom testy, potwierdź FAIL**

```bash
pytest tests/test_certs_pola_variant.py -v
```

Expected: FAIL — `build_pola_context` nie istnieje.

- [ ] **Step 3: Dodaj `build_pola_context` w `generator.py`**

W `mbr/certs/generator.py` dopisz:

```python
def build_pola_context(db, *, variant_id: int | None) -> dict:
    """Return {kod: wartosc_stala} for active pola scope=cert_variant of given variant.

    Returns empty dict if variant_id is None or no active fields. Used as
    sub-namespace `pola.` in DOCX context to avoid collisions with top-level keys.
    """
    if variant_id is None:
        return {}
    from mbr.shared.produkt_pola import list_pola_for_cert_variant
    pola = list_pola_for_cert_variant(db, variant_id)
    return {p["kod"]: p["wartosc_stala"] or "" for p in pola}
```

- [ ] **Step 4: Wpięcie do `build_context`**

W `mbr/certs/generator.py` znajdź `build_context` i przed return / na końcu (po standardowym kontekście) dodaj:

```python
    # Sub-namespace `pola.<kod>` for scope=cert_variant fields
    variant_id = context.get("_variant_id")  # whatever key holds active variant id
    context["pola"] = build_pola_context(db, variant_id=variant_id)
```

(Jeśli `build_context` nie ma jeszcze `db` w sygnaturze, dodaj — funkcja jest wywoływana z routera który już ma db_session.)

NOTE: dokładny mechanizm pobrania `variant_id` zależy od istniejącego kodu. Skim `build_context` przed implementacją: `grep -n 'def build_context' mbr/certs/generator.py`. Wartość variantu może już być w lokalnej zmiennej `vr["id"]` (patrz `mbr/certs/routes.py:419`).

- [ ] **Step 5: Uruchom testy, potwierdź PASS**

```bash
pytest tests/test_certs_pola_variant.py -v
```

Expected: 3 testy PASS.

- [ ] **Step 6: Manual smoke test**

Dodaj pole scope=cert_variant dla wariantu Kosmepol (Task 12). Otwórz master DOCX `mbr/templates/cert_master_template.docx` w Wordzie. Wstaw w wybranym miejscu np.:

```
{% if pola.nr_zamowienia_kosmepol %}Nr zamówienia: {{ pola.nr_zamowienia_kosmepol }}{% endif %}
```

Zapisz DOCX. Wygeneruj świadectwo dla szarży Chegina K40GLOLMB z wariantem Kosmepol — w PDF widoczna linia "Nr zamówienia: KSM/2026/STALY/001". Generuj świadectwo dla wariantu innego niż Kosmepol — linia nie pojawia się.

- [ ] **Step 7: Commit**

```bash
git add mbr/certs/generator.py tests/test_certs_pola_variant.py
git commit -m "feat(produkt_pola): generator certow — sub-namespace pola.<kod>"
```

---

## Task 18: CLAUDE.md — krótka notka o mechanizmie

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Dopisz sekcję w CLAUDE.md**

W `CLAUDE.md`, w sekcji "Conventions" (lub innej pasującej), dopisz:

```markdown
### Pola dodatkowe per produkt / per wariant świadectwa

Deklaratywny mechanizm pól metadanych (zamiast hardkodowanych kolumn na `ebr_batches` jak `nr_zbiornika` czy flag `has_avon_code`).

- **Tabele:** `produkt_pola` (definicje, `scope ∈ {produkt, cert_variant}`) + `ebr_pola_wartosci` (wartości per szarża).
- **DAO:** `mbr/shared/produkt_pola.py` (`create_pole`, `update_pole`, `set_wartosc`, `get_wartosci_for_ebr`, `list_pola_for_*`).
- **API:** `GET/POST/PUT/DELETE /api/produkt-pola[/<id>]`, `GET/PUT /api/ebr/<id>/pola[/<pole_id>]`.
- **UI definicji:** `parametry_editor.html` (scope=produkt), `wzory_cert.html` (scope=cert_variant).
- **Integracja:** modal "Nowa szarża" (sekcja "Pola dodatkowe" na końcu), Hero (sekcja edytowalna), `/registry/ukonczone` (kolumny tuż przed "Uwagi"), generator certów (sub-namespace `pola.<kod>` w kontekście DOCX, używać jako `{% if pola.<kod> %}{{ pola.<kod> }}{% endif %}`).
- **Konwencje:** `kod` = snake_case (`^[a-z][a-z0-9_]*$`); `obowiazkowe` = tylko gwiazdka w UI (nie blokuje); `wartosc_stala` tylko dla scope=cert_variant; wartości typu `number` przechowywane z polskim przecinkiem.
- **Spec:** `docs/superpowers/specs/2026-05-01-produkt-pola-uniwersalne-design.md`.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: notka o mechanizmie produkt_pola w CLAUDE.md"
```

---

## Task 19: End-to-end smoke test (manual checklist)

**Files:** none (manual testing).

- [ ] **Step 1: Restart serwera dev**

```bash
pkill -f "python -m mbr.app" 2>/dev/null
python -m mbr.app
```

- [ ] **Step 2: Scenariusz Monamid KO (scope=produkt)**

Zaloguj jako admin/technolog:

1. `/admin/produkty` → wybierz Monamid_KO → zakładka "Pola dodatkowe":
   - Dodaj `kod=nr_zamowienia, label=Nr zamówienia, typ=text, miejsca=[modal,hero,ukonczone]`.
   - Dodaj `kod=nr_dop_oleju, label=Nr dopuszczenia oleju kokosowego, typ=text, miejsca=[modal,hero,ukonczone]`.

Zaloguj jako lab:

2. Modal "Nowa szarża" → produkt=Monamid_KO, typ=szarza → sekcja "Pola dodatkowe" pokazuje 2 nowe pola → wpisz `nr_zamowienia=ZAM/123/2026`, zostaw `nr_dop_oleju` puste → utwórz.
3. Otwórz hero szarży → sekcja "Pola dodatkowe" pokazuje `nr_zamowienia=ZAM/123/2026` (zapisane) + puste `nr_dop_oleju` → wpisz w `nr_dop_oleju` wartość `OL/2026/04/15` → blur → zapis automatyczny.
4. Zatwierdź szarżę (laborant_kj path).
5. `/registry/ukonczone` → tabela ma 2 nowe kolumny "Nr zamówienia" i "Nr dopuszczenia oleju kokosowego" tuż przed "Uwagi" — z wartościami.

- [ ] **Step 3: Scenariusz Chegina KK (scope=produkt + typy_rejestracji=zbiornik)**

Jako admin:

6. `/admin/produkty` → Chegina_KK → Pola dodatkowe → dodaj `kod=ilosc_konserwantuna, label=Ilość konserwantuna, typ=number, jednostka=kg, miejsca=[hero,ukonczone], typy_rejestracji=[zbiornik]`.

Jako lab:

7. Modal "Nowa szarża" → produkt=Chegina_KK, typ=szarza → sekcja "Pola dodatkowe" NIE pokazuje pola (filter typ=zbiornik).
8. Modal "Nowy zbiornik" lub odpowiednik dla typu zbiornik → produkt=Chegina_KK → sekcja pokazuje `Ilość konserwantuna [kg]`. NIE pokazuje w modalu (bo `miejsca=[hero,ukonczone]`, nie `[modal,...]`). Utwórz zbiornik.
9. Hero zbiornika → sekcja "Pola dodatkowe" → wpisz `12,5` → blur → zapis.
10. `/registry/ukonczone` → kolumna "Ilość konserwantuna [kg]" widoczna z wartością `12,5`.

- [ ] **Step 4: Scenariusz Kosmepol (scope=cert_variant)**

Jako admin:

11. `/admin/wzory-cert` → produkt=Chegina_K40GLOLMB → wariant=Kosmepol → "Stałe pola" → dodaj `kod=nr_zamowienia_kosmepol, label=Nr zamówienia (Kosmepol), wartosc_stala=KSM/2026/STALY/001`.
12. Otwórz `mbr/templates/cert_master_template.docx` w Wordzie → wstaw `{% if pola.nr_zamowienia_kosmepol %}Nr zamówienia: {{ pola.nr_zamowienia_kosmepol }}{% endif %}` w nagłówku → zapisz.

Jako lab:

13. Wygeneruj świadectwo dla szarży Chegina K40GLOLMB / wariant Kosmepol → PDF zawiera linię "Nr zamówienia: KSM/2026/STALY/001".
14. Wygeneruj świadectwo dla tej samej szarży / wariant inny niż Kosmepol → PDF NIE zawiera linii.

- [ ] **Step 5: Scenariusz dezaktywacji (scope=cert_variant)**

15. Admin: dezaktywuj pole `nr_zamowienia_kosmepol`.
16. Wygeneruj świadectwo Kosmepol → PDF NIE zawiera linii (klucz `pola.nr_zamowienia_kosmepol` nie istnieje, conditional pomija blok). Brak literalnego `{{ pola.nr_zamowienia_kosmepol }}` w PDF.

- [ ] **Step 6: Sprawdź audit log**

```bash
sqlite3 data/batch_db.sqlite "SELECT event_type, entity_type, entity_label, dt_event FROM audit_log WHERE event_type LIKE 'produkt_pola%' OR event_type='ebr_pola.value_set' ORDER BY id DESC LIMIT 20"
```

Wpisy dla każdej operacji (create_pole, update_pole, deactivate_pole, value_set).

- [ ] **Step 7: Wszystkie testy przechodzą**

```bash
pytest tests/test_produkt_pola_dao.py tests/test_produkt_pola_api.py tests/test_modal_pola.py tests/test_registry_pola_columns.py tests/test_certs_pola_variant.py -v
```

Expected: wszystkie testy PASS.

- [ ] **Step 8: Commit (jeśli były dodatkowe poprawki w smoke teście)**

Zapisz odkrycia i poprawki (jeśli jakiekolwiek wyszły) w osobnych commitach.

---

## Self-Review

Przejrzałem plan vs spec — pokrycie:

- ✅ Schema (Task 1)
- ✅ DAO definicji + audit (Task 3)
- ✅ DAO wartości (Task 4)
- ✅ DAO filtry (Task 5)
- ✅ API blueprint (Task 6)
- ✅ API GET (Task 7)
- ✅ API POST (Task 8)
- ✅ API PUT/DELETE definicji (Task 9)
- ✅ API PUT wartości (Task 10)
- ✅ UI scope=produkt (Task 11)
- ✅ UI scope=cert_variant (Task 12)
- ✅ Modal create_ebr (Task 13)
- ✅ Hero (Task 14)
- ✅ Registry models (Task 15)
- ✅ Registry template (Task 16)
- ✅ Generator certów (Task 17)
- ✅ CLAUDE.md (Task 18)
- ✅ Smoke test E2E (Task 19)

Spec sekcje pokryte: schema ✓, DAO ✓, API ✓, UI definicji ✓, modal ✓, Hero ✓, registry ✓, generator certów ✓, audit ✓, edge cases (concurrency LWW, hard-delete sieroty, dezaktywacja, kod immutable, walidacja number z przecinkiem, sub-namespace pola) ✓, testy ✓.

Brak placeholderów typu "TBD". Każdy task ma konkretne ścieżki, kod, komendy testowe.

Type consistency: `pp.create_pole(db, payload, user_id=...)` — używane spójnie. `set_wartosc(db, ebr_id, pole_id, wartosc, user_id=...)` — spójnie. `list_pola_for_produkt(db, produkt_id, *, miejsce=, typ_rejestracji=)` — spójnie.
