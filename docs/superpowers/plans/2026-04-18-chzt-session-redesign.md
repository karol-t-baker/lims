# ChZT Session Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Przerobić sesję ChZT z date-keyed (UNIQUE(data)) na on-demand (dt_start datetime), dodać pola zewnętrznej analizy szambiarki (ext_chzt, ext_ph, waga_kg), wprowadzić rolę `produkcja` z dostępem tylko do historii + edycji pól szambiarki.

**Architecture:** Migracja DB idempotentna w `init_chzt_tables` (rebuild `chzt_sesje`, ALTER `chzt_pomiary`) + w `init_mbr_tables` (CHECK dla `rola`). Backend RBAC per-pole przez filtrację payloadu w `PUT /api/chzt/pomiar/<id>`. UI — modal ma nowy "create-session" stan; detail view historii dostaje dolną sekcję "Analiza zewnętrzna — Szambiarka" edytowalną per rola.

**Tech Stack:** Flask + raw sqlite3, Jinja2, vanilla JS, pytest.

**Spec:** `docs/superpowers/specs/2026-04-18-chzt-session-redesign-design.md`

---

## File Structure

### Modyfikowane

| Plik | Zakres zmian |
|---|---|
| `mbr/chzt/models.py` | Migracja `chzt_sesje` (rebuild bez UNIQUE(data), dodanie `dt_start`), ALTER `chzt_pomiary` (+3 kolumny). Nowe helpery: `get_active_session`, `create_session`. Rozszerzone: `get_pomiar`, `update_pomiar`, `get_session_with_pomiary`, `list_sessions_paginated`. Usunięte: `get_or_create_session`. |
| `mbr/chzt/routes.py` | Nowe role constants: `ROLES_VIEW`, `ROLES_EDIT_INTERNAL`, `ROLES_EDIT_EXTERNAL`. Nowe endpointy: `GET /api/chzt/session/active`, `POST /api/chzt/session/new`, `GET /api/chzt/session/<int:id>`. Usunięte: `/today`, `/<data_iso>`. Zaktualizowane: `PUT /api/chzt/pomiar/<id>` (RBAC per-pole), `GET /api/chzt/day/<data>` (DATE(dt_start), ext fields), `GET /api/chzt/history` (ORDER BY dt_start). |
| `mbr/chzt/static/chzt.js` | Nowy stan `create-pane`, `loadActiveSession()`, `createSession()`. W `chztShowDetail` — renderowanie sekcji ext szambiarki + wire handlers dla ext/waga inputów. Role check na froncie dla readonly stylu. |
| `mbr/chzt/static/chzt.css` | `.chzt-create-pane`, `.chzt-ext-section`, `.chzt-inp.readonly`. |
| `mbr/chzt/templates/chzt_modal.html` | Dodać `<div class="chzt-create-pane">` ukryty domyślnie. |
| `mbr/chzt/templates/chzt_historia.html` | Kolumna `Data` → `Rozpoczęto`, format datetime. |
| `mbr/templates/technolog/narzedzia.html` | Gate karty "ChZT Ścieków" (ukryta dla rola=produkcja). |
| `mbr/models.py` | Dodać `'produkcja'` do CHECK constraint `mbr_users.rola` (w CREATE TABLE IF NOT EXISTS + runtime migration pattern). |
| `tests/test_chzt.py` | Usunąć testy `/today` + `get_or_create_session`. Dodać: testy migracji, `/active`, `/new`, RBAC, ext fields, crossing midnight. Zaktualizować fixtures. |

### Nowe

Brak. Wszystko rozszerzenie istniejących plików.

---

## Konwencje przypomnienie

- **Raw sqlite3**, `?` placeholders, `Row` factory
- **Helpery nie commitują** — caller owns transakcję (`init_*_tables` to wyjątek — commituje DDL)
- **Role w `role_required`**: `"lab"`, `"kj"`, `"cert"`, `"technolog"`, `"admin"`, `"produkcja"` (nowa)
- **Audit**: `log_event(event_type, entity_type=, entity_id=, diff=, db=)`; eventy jako `EVENT_CHZT_*` w `mbr/shared/audit.py`
- **Cache-bust**: bumpnąć `?v=N` w linkach JS/CSS po zmianach frontend
- **TDD**: test first, fail, impl, pass, commit na każdy step

---

## Task 1: DB migration — chzt_sesje rebuild + chzt_pomiary extra cols + mbr_users CHECK

**Cel:** Migracja idempotentna z dotychczasowego schematu (`UNIQUE(data)` na chzt_sesje, brak ext pól na chzt_pomiary, CHECK rola bez `'produkcja'`) do nowego. Dane zachowane.

**Files:**
- Modify: `mbr/models.py`
- Modify: `mbr/chzt/models.py`
- Modify: `tests/test_chzt.py`

- [ ] **Step 1: Write failing tests for migration**

Append at top of `tests/test_chzt.py` imports (dodaj `text` jeśli brak):

Już istnieje `from mbr.chzt.models import init_chzt_tables` etc.

Dopisać nowe testy na końcu pliku:

```python
# ───────────────────────────────────────────────────────────────
# Migracja: stary schemat → nowy (idempotentna)
# ───────────────────────────────────────────────────────────────

def test_migration_from_old_schema_preserves_sesje_data():
    """Old schema (with `data` and UNIQUE(data)) migrates to new (dt_start)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    # Ręcznie stwórz stary schemat chzt_sesje (z kolumną `data` + UNIQUE)
    conn.execute("""
        CREATE TABLE chzt_sesje (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            data         TEXT NOT NULL UNIQUE,
            n_kontenery  INTEGER NOT NULL DEFAULT 8,
            created_at   TEXT NOT NULL,
            created_by   INTEGER REFERENCES workers(id),
            finalized_at TEXT,
            finalized_by INTEGER REFERENCES workers(id)
        )
    """)
    conn.execute("""
        CREATE TABLE chzt_pomiary (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            sesja_id     INTEGER NOT NULL REFERENCES chzt_sesje(id) ON DELETE CASCADE,
            punkt_nazwa  TEXT NOT NULL,
            kolejnosc    INTEGER NOT NULL,
            ph           REAL,
            p1           REAL, p2 REAL, p3 REAL, p4 REAL, p5 REAL,
            srednia      REAL,
            updated_at   TEXT NOT NULL,
            updated_by   INTEGER REFERENCES workers(id),
            UNIQUE(sesja_id, punkt_nazwa)
        )
    """)
    conn.execute(
        "INSERT INTO chzt_sesje (data, n_kontenery, created_at) "
        "VALUES ('2026-04-10', 8, '2026-04-10T10:00:00')"
    )
    conn.execute(
        "INSERT INTO chzt_pomiary (sesja_id, punkt_nazwa, kolejnosc, ph, p1, p2, updated_at) "
        "VALUES (1, 'hala', 1, 10, 20000, 22000, '2026-04-10T10:30:00')"
    )
    conn.commit()

    # Run migration
    init_chzt_tables(conn)

    # Verify: chzt_sesje has dt_start, no UNIQUE(data), row preserved
    cols = {r[1] for r in conn.execute("PRAGMA table_info(chzt_sesje)").fetchall()}
    assert "dt_start" in cols
    assert "data" not in cols

    row = conn.execute("SELECT id, dt_start, n_kontenery FROM chzt_sesje").fetchone()
    assert row["id"] == 1
    assert row["dt_start"].startswith("2026-04-10")
    assert row["n_kontenery"] == 8

    # chzt_pomiary gets ext_chzt/ext_ph/waga_kg
    pcols = {r[1] for r in conn.execute("PRAGMA table_info(chzt_pomiary)").fetchall()}
    assert "ext_chzt" in pcols
    assert "ext_ph" in pcols
    assert "waga_kg" in pcols

    prow = conn.execute("SELECT punkt_nazwa, ph FROM chzt_pomiary WHERE id=1").fetchone()
    assert prow["punkt_nazwa"] == "hala"
    assert prow["ph"] == 10

    # UNIQUE(data) gone — can now insert two sessions with same calendar date
    conn.execute(
        "INSERT INTO chzt_sesje (dt_start, n_kontenery, created_at) "
        "VALUES ('2026-04-11T08:00:00', 8, '2026-04-11T08:00:00')"
    )
    conn.execute(
        "INSERT INTO chzt_sesje (dt_start, n_kontenery, created_at) "
        "VALUES ('2026-04-11T14:00:00', 8, '2026-04-11T14:00:00')"
    )
    conn.commit()

    conn.close()


def test_migration_idempotent_on_fresh_db():
    """Running init_chzt_tables twice on a fresh DB is a no-op after first."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_mbr_tables(conn)
    init_chzt_tables(conn)
    init_chzt_tables(conn)  # second call must not fail
    cols = {r[1] for r in conn.execute("PRAGMA table_info(chzt_sesje)").fetchall()}
    assert "dt_start" in cols
    assert "data" not in cols
    conn.close()


def test_migration_mbr_users_rola_check_includes_produkcja():
    """mbr_users.rola CHECK must include 'produkcja' after init_mbr_tables."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    # Insert a produkcja user — should succeed
    conn.execute(
        "INSERT INTO mbr_users (login, password_hash, rola, imie_nazwisko) "
        "VALUES ('mag1', 'hash', 'produkcja', 'Jan Magazyn')"
    )
    conn.commit()
    row = conn.execute("SELECT rola FROM mbr_users WHERE login='mag1'").fetchone()
    assert row["rola"] == "produkcja"
    conn.close()
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/test_chzt.py::test_migration_from_old_schema_preserves_sesje_data tests/test_chzt.py::test_migration_mbr_users_rola_check_includes_produkcja -v`

Expected: both fail. First because `init_chzt_tables` doesn't have migration logic for existing `data` column. Second because `init_mbr_tables` CHECK doesn't include `produkcja`.

- [ ] **Step 3: Implement mbr_users CHECK update in `mbr/models.py`**

**(a)** Znajdź CREATE TABLE IF NOT EXISTS mbr_users (ok. linia 18) i zaktualizuj CHECK:

```python
CREATE TABLE IF NOT EXISTS mbr_users (
    user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    login           TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    rola            TEXT NOT NULL CHECK(rola IN ('technolog', 'lab', 'cert', 'kj', 'admin', 'produkcja')),
    imie_nazwisko   TEXT
);
```

**(b)** Znajdź runtime migration block (ok. linia 995-1016, zaczyna się "Migration: expand rola CHECK to include all roles") i dodaj nowy block PO nim:

```python
    # Migration: expand rola CHECK to include 'produkcja'
    try:
        row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='mbr_users'").fetchone()
        if row:
            ddl = row[0] if isinstance(row, tuple) else row["sql"]
            if "'produkcja'" not in ddl:
                db.executescript("""
                    CREATE TABLE mbr_users_new_prodcheck (
                        user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        login           TEXT UNIQUE NOT NULL,
                        password_hash   TEXT NOT NULL,
                        rola            TEXT NOT NULL CHECK(rola IN ('technolog', 'lab', 'cert', 'kj', 'admin', 'produkcja')),
                        imie_nazwisko   TEXT
                    );
                    INSERT INTO mbr_users_new_prodcheck SELECT * FROM mbr_users;
                    DROP TABLE mbr_users;
                    ALTER TABLE mbr_users_new_prodcheck RENAME TO mbr_users;
                """)
    except Exception:
        pass
```

- [ ] **Step 4: Implement migration in `mbr/chzt/models.py` — `init_chzt_tables`**

Zastąp `init_chzt_tables` poniższym:

```python
def init_chzt_tables(db):
    """Create/migrate chzt_sesje + chzt_pomiary. Idempotent.

    Nowy schemat (v2):
      chzt_sesje.dt_start (TEXT, zastępuje UNIQUE(data))
      chzt_pomiary + ext_chzt, ext_ph, waga_kg (nullable)

    Migracja ze starego:
      - Jeśli chzt_sesje ma kolumnę `data` → rebuild bez UNIQUE
      - Jeśli chzt_pomiary nie ma ext_chzt → ALTER TABLE ADD COLUMN × 3
    """
    # --- chzt_sesje: create new OR migrate from old ---
    sesje_exists = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chzt_sesje'"
    ).fetchone()

    if not sesje_exists:
        db.execute("""
            CREATE TABLE chzt_sesje (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                dt_start     TEXT NOT NULL,
                n_kontenery  INTEGER NOT NULL DEFAULT 8,
                created_at   TEXT NOT NULL,
                created_by   INTEGER REFERENCES workers(id),
                finalized_at TEXT,
                finalized_by INTEGER REFERENCES workers(id)
            )
        """)
    else:
        cols = {r[1] for r in db.execute("PRAGMA table_info(chzt_sesje)").fetchall()}
        if "dt_start" not in cols and "data" in cols:
            # Rebuild: copy from old `data` → `dt_start`
            db.executescript("""
                CREATE TABLE chzt_sesje_v2 (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    dt_start     TEXT NOT NULL,
                    n_kontenery  INTEGER NOT NULL DEFAULT 8,
                    created_at   TEXT NOT NULL,
                    created_by   INTEGER,
                    finalized_at TEXT,
                    finalized_by INTEGER
                );
                INSERT INTO chzt_sesje_v2 (id, dt_start, n_kontenery, created_at, created_by, finalized_at, finalized_by)
                SELECT id,
                       CASE WHEN length(data) = 10 THEN data || 'T00:00:00' ELSE data END AS dt_start,
                       n_kontenery, created_at, created_by, finalized_at, finalized_by
                FROM chzt_sesje;
                DROP TABLE chzt_sesje;
                ALTER TABLE chzt_sesje_v2 RENAME TO chzt_sesje;
            """)

    db.execute("DROP INDEX IF EXISTS idx_chzt_sesje_data")
    db.execute("CREATE INDEX IF NOT EXISTS idx_chzt_sesje_dt_start ON chzt_sesje(dt_start DESC)")

    # --- chzt_pomiary: create OR ALTER ---
    pomiary_exists = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chzt_pomiary'"
    ).fetchone()

    if not pomiary_exists:
        db.execute("""
            CREATE TABLE chzt_pomiary (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                sesja_id     INTEGER NOT NULL REFERENCES chzt_sesje(id) ON DELETE CASCADE,
                punkt_nazwa  TEXT NOT NULL,
                kolejnosc    INTEGER NOT NULL,
                ph           REAL,
                p1           REAL,
                p2           REAL,
                p3           REAL,
                p4           REAL,
                p5           REAL,
                srednia      REAL,
                ext_chzt     REAL,
                ext_ph       REAL,
                waga_kg      REAL,
                updated_at   TEXT NOT NULL,
                updated_by   INTEGER REFERENCES workers(id),
                UNIQUE(sesja_id, punkt_nazwa)
            )
        """)
    else:
        pcols = {r[1] for r in db.execute("PRAGMA table_info(chzt_pomiary)").fetchall()}
        if "ext_chzt" not in pcols:
            db.execute("ALTER TABLE chzt_pomiary ADD COLUMN ext_chzt REAL")
        if "ext_ph" not in pcols:
            db.execute("ALTER TABLE chzt_pomiary ADD COLUMN ext_ph REAL")
        if "waga_kg" not in pcols:
            db.execute("ALTER TABLE chzt_pomiary ADD COLUMN waga_kg REAL")

    db.execute("CREATE INDEX IF NOT EXISTS idx_chzt_pomiary_sesja ON chzt_pomiary(sesja_id)")
    db.commit()
```

- [ ] **Step 5: Run migration tests — PASS**

Run: `pytest tests/test_chzt.py::test_migration_from_old_schema_preserves_sesje_data tests/test_chzt.py::test_migration_idempotent_on_fresh_db tests/test_chzt.py::test_migration_mbr_users_rola_check_includes_produkcja -v`

Expected: 3 passed.

- [ ] **Step 6: Run full chzt tests — niektóre istniejące mogą failować**

Run: `pytest tests/test_chzt.py -v 2>&1 | tail -30`

Expected: wiele failów (poprzednie testy zakładały `get_or_create_session`, `/today`, kolumnę `data`). Te naprawimy w kolejnych taskach — zanotować, iść dalej.

- [ ] **Step 7: Commit**

```bash
git add mbr/models.py mbr/chzt/models.py tests/test_chzt.py
git commit -m "feat(chzt): schema migration — dt_start replaces data, add ext fields, produkcja role CHECK"
```

---

## Task 2: Model helpers — session (get_active_session + create_session)

**Cel:** Zastąpić `get_or_create_session` dwoma oddzielnymi helperami odpowiadającymi nowej polityce "manual trigger, max one open".

**Files:**
- Modify: `mbr/chzt/models.py`
- Modify: `tests/test_chzt.py`

- [ ] **Step 1: Failing tests**

Dopisz do `tests/test_chzt.py`:

```python
from mbr.chzt.models import get_active_session, create_session


def test_create_session_returns_id_and_seeds_pomiary(db):
    sid = create_session(db, created_by=1, n_kontenery=3)
    db.commit()
    assert isinstance(sid, int)

    # Session has dt_start near "now" (ISO datetime)
    row = db.execute("SELECT dt_start, n_kontenery, finalized_at FROM chzt_sesje WHERE id=?", (sid,)).fetchone()
    assert row["n_kontenery"] == 3
    assert row["finalized_at"] is None
    assert "T" in row["dt_start"]  # ISO datetime format

    # Pomiary: hala + rura + kontener 1..3 + szambiarka = 6 rows
    pomiary = db.execute(
        "SELECT punkt_nazwa FROM chzt_pomiary WHERE sesja_id=? ORDER BY kolejnosc", (sid,)
    ).fetchall()
    names = [r["punkt_nazwa"] for r in pomiary]
    assert names == ["hala", "rura", "kontener 1", "kontener 2", "kontener 3", "szambiarka"]


def test_create_session_raises_when_another_open(db):
    create_session(db, created_by=1, n_kontenery=3)
    db.commit()
    with pytest.raises(ValueError) as exc:
        create_session(db, created_by=1, n_kontenery=5)
    assert "already_open" in str(exc.value)


def test_create_session_ok_after_previous_finalized(db):
    sid1 = create_session(db, created_by=1, n_kontenery=3)
    db.execute("UPDATE chzt_sesje SET finalized_at=? WHERE id=?", ("2026-04-18T12:00:00", sid1))
    db.commit()
    sid2 = create_session(db, created_by=2, n_kontenery=8)
    db.commit()
    assert sid2 != sid1


def test_get_active_session_returns_open_one(db):
    sid = create_session(db, created_by=1, n_kontenery=3)
    db.commit()
    active = get_active_session(db)
    assert active is not None
    assert active["id"] == sid
    assert active["finalized_at"] is None


def test_get_active_session_returns_none_when_no_open(db):
    assert get_active_session(db) is None
    # Create + finalize → still none
    sid = create_session(db, created_by=1, n_kontenery=1)
    db.execute("UPDATE chzt_sesje SET finalized_at=? WHERE id=?", ("2026-04-18T12:00:00", sid))
    db.commit()
    assert get_active_session(db) is None
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/test_chzt.py::test_create_session_returns_id_and_seeds_pomiary -v`
Expected: ImportError.

- [ ] **Step 3: Implement helpers in `mbr/chzt/models.py`**

Usuń funkcję `get_or_create_session` w całości.

Dodaj na końcu pliku:

```python
def get_active_session(db) -> dict | None:
    """Return the single open (finalized_at IS NULL) session as dict, or None."""
    row = db.execute(
        "SELECT id, dt_start, n_kontenery, created_at, created_by, finalized_at, finalized_by "
        "FROM chzt_sesje WHERE finalized_at IS NULL "
        "ORDER BY dt_start DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def create_session(db, *, created_by: int, n_kontenery: int = 8) -> int:
    """Create a new session with dt_start=now() and seed N+3 pomiary rows.

    Raises ValueError("already_open") if another session is already open
    (finalized_at IS NULL). Caller owns the transaction.
    """
    if db.execute("SELECT 1 FROM chzt_sesje WHERE finalized_at IS NULL LIMIT 1").fetchone():
        raise ValueError("already_open")

    now = datetime.now().isoformat(timespec="seconds")
    cur = db.execute(
        "INSERT INTO chzt_sesje (dt_start, n_kontenery, created_at, created_by) "
        "VALUES (?, ?, ?, ?)",
        (now, n_kontenery, now, created_by),
    )
    session_id = cur.lastrowid

    names = build_punkty_names(n_kontenery)
    for idx, name in enumerate(names, start=1):
        db.execute(
            "INSERT INTO chzt_pomiary (sesja_id, punkt_nazwa, kolejnosc, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (session_id, name, idx, now),
        )
    return session_id
```

- [ ] **Step 4: Tests pass**

Run: `pytest tests/test_chzt.py::test_create_session_returns_id_and_seeds_pomiary tests/test_chzt.py::test_create_session_raises_when_another_open tests/test_chzt.py::test_create_session_ok_after_previous_finalized tests/test_chzt.py::test_get_active_session_returns_open_one tests/test_chzt.py::test_get_active_session_returns_none_when_no_open -v`

Expected: 5 passed.

- [ ] **Step 5: Usuń testy używające `get_or_create_session` z poprzedniej iteracji**

W `tests/test_chzt.py` usuń lub zaktualizuj:

- `test_get_or_create_session_creates_fresh`
- `test_get_or_create_session_idempotent`
- `test_get_session_with_pomiary_shape` (używa `get_or_create_session`) — zaktualizuj na `create_session`
- `test_get_session_with_pomiary_returns_none_when_missing` (zostaje)
- Wszystkie inne używające `get_or_create_session`

Znajdź: `grep -n "get_or_create_session" tests/test_chzt.py`

Dla każdego wystąpienia w treści testu — zastąp `get_or_create_session(db, "YYYY-MM-DD", created_by=N, n_kontenery=K)` przez `sid = create_session(db, created_by=N, n_kontenery=K)`.

Usuń import `get_or_create_session`.

- [ ] **Step 6: Run affected tests — niektóre mogą dalej failować (używają np. /today) — to naprawimy w Task 3**

Run: `pytest tests/test_chzt.py -v 2>&1 | tail -20`

Expected: testy modelowe przechodzą; testy route'ów nadal failują (używają `/today` — Task 3).

- [ ] **Step 7: Commit**

```bash
git add mbr/chzt/models.py tests/test_chzt.py
git commit -m "feat(chzt): replace get_or_create_session with get_active_session + create_session (409 on double-open)"
```

---

## Task 3: Model helpers — extend for ext fields + fix list_sessions_paginated

**Cel:** Rozszerzyć `get_pomiar`, `update_pomiar`, `get_session_with_pomiary` o pola `ext_chzt`, `ext_ph`, `waga_kg`. Zaktualizować `list_sessions_paginated` o sort po `dt_start` + zwracanie `dt_start` zamiast `data`.

**Files:**
- Modify: `mbr/chzt/models.py`
- Modify: `tests/test_chzt.py`

- [ ] **Step 1: Failing tests**

Dopisz:

```python
def test_update_pomiar_writes_ext_fields(db):
    sid = create_session(db, created_by=1, n_kontenery=0)
    db.commit()
    pid = db.execute(
        "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='szambiarka'", (sid,)
    ).fetchone()["id"]
    update_pomiar(db, pid, {
        "ph": 11, "p1": 25000, "p2": 26000, "p3": None, "p4": None, "p5": None,
        "ext_chzt": 13250, "ext_ph": 11, "waga_kg": 19060,
    }, updated_by=1)
    db.commit()
    row = db.execute(
        "SELECT ph, ext_chzt, ext_ph, waga_kg, srednia FROM chzt_pomiary WHERE id=?", (pid,)
    ).fetchone()
    assert row["ph"] == 11
    assert row["ext_chzt"] == 13250
    assert row["ext_ph"] == 11
    assert row["waga_kg"] == 19060
    assert row["srednia"] == 25500  # from p1, p2


def test_get_pomiar_includes_ext_fields(db):
    sid = create_session(db, created_by=1, n_kontenery=0)
    db.commit()
    pid = db.execute(
        "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='szambiarka'", (sid,)
    ).fetchone()["id"]
    update_pomiar(db, pid, {"ext_chzt": 13250}, updated_by=1)
    db.commit()
    p = get_pomiar(db, pid)
    assert "ext_chzt" in p
    assert p["ext_chzt"] == 13250
    assert p["ext_ph"] is None
    assert p["waga_kg"] is None


def test_get_session_with_pomiary_includes_ext_fields(db):
    sid = create_session(db, created_by=1, n_kontenery=0)
    db.commit()
    s = get_session_with_pomiary(db, sid)
    for p in s["punkty"]:
        assert "ext_chzt" in p
        assert "ext_ph" in p
        assert "waga_kg" in p


def test_list_sessions_paginated_sorts_by_dt_start_desc(db):
    # Seed 3 sessions with different dt_start manually (faster than create+finalize cycle)
    for dt in ["2026-04-10T08:00:00", "2026-04-12T10:00:00", "2026-04-11T14:00:00"]:
        db.execute(
            "INSERT INTO chzt_sesje (dt_start, n_kontenery, created_at, created_by) "
            "VALUES (?, 0, ?, 1)", (dt, dt)
        )
    db.commit()
    page = list_sessions_paginated(db, page=1, per_page=10)
    dts = [s["dt_start"] for s in page["sesje"]]
    assert dts[0].startswith("2026-04-12")
    assert dts[1].startswith("2026-04-11")
    assert dts[2].startswith("2026-04-10")
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/test_chzt.py::test_update_pomiar_writes_ext_fields tests/test_chzt.py::test_get_pomiar_includes_ext_fields tests/test_chzt.py::test_get_session_with_pomiary_includes_ext_fields tests/test_chzt.py::test_list_sessions_paginated_sorts_by_dt_start_desc -v`
Expected: 4 fails — helpery nie obsługują nowych pól / kolumny `dt_start`.

- [ ] **Step 3: Update `POMIAR_FIELDS` + extend helpers in `mbr/chzt/models.py`**

Znajdź `POMIAR_FIELDS = ("ph", "p1", "p2", "p3", "p4", "p5")` i **dodaj nowe constants obok** (nie rozszerzaj istniejącego — używany dla internal-only fields):

```python
POMIAR_FIELDS_INTERNAL = ("ph", "p1", "p2", "p3", "p4", "p5")
POMIAR_FIELDS_EXTERNAL = ("ext_chzt", "ext_ph", "waga_kg")
POMIAR_FIELDS = POMIAR_FIELDS_INTERNAL + POMIAR_FIELDS_EXTERNAL
```

(`POMIAR_FIELDS` pozostaje — obecne importy dalej działają; do RBAC Task 4 użyjemy _INTERNAL / _EXTERNAL osobno.)

Zaktualizuj `get_pomiar`:

```python
def get_pomiar(db, pomiar_id: int) -> dict:
    row = db.execute(
        "SELECT id, sesja_id, punkt_nazwa, kolejnosc, ph, p1, p2, p3, p4, p5, "
        "       srednia, ext_chzt, ext_ph, waga_kg, updated_at, updated_by "
        "FROM chzt_pomiary WHERE id=?",
        (pomiar_id,),
    ).fetchone()
    return dict(row) if row else None
```

Zaktualizuj `update_pomiar` — ma przyjmować partial dict (tylko pola które user chce zmienić):

```python
def update_pomiar(db, pomiar_id: int, new_values: dict, *, updated_by: int):
    """Update the subset of fields present in new_values. Recompute srednia
    from resulting p1..p5 state. Caller owns the transaction.

    Returns the updated row dict. Raises ValueError if pomiar_id not found.
    """
    existing = get_pomiar(db, pomiar_id)
    if existing is None:
        raise ValueError(f"pomiar {pomiar_id} not found")

    # Merge: new_values overrides, rest keeps existing
    merged = dict(existing)
    for k in POMIAR_FIELDS:
        if k in new_values:
            merged[k] = new_values[k]

    srednia = compute_srednia(merged)
    now = datetime.now().isoformat(timespec="seconds")

    db.execute(
        "UPDATE chzt_pomiary "
        "SET ph=?, p1=?, p2=?, p3=?, p4=?, p5=?, srednia=?, "
        "    ext_chzt=?, ext_ph=?, waga_kg=?, "
        "    updated_at=?, updated_by=? "
        "WHERE id=?",
        (
            merged.get("ph"), merged.get("p1"), merged.get("p2"), merged.get("p3"),
            merged.get("p4"), merged.get("p5"), srednia,
            merged.get("ext_chzt"), merged.get("ext_ph"), merged.get("waga_kg"),
            now, updated_by, pomiar_id,
        ),
    )
    return get_pomiar(db, pomiar_id)
```

**WAŻNE**: poprzednia wersja `update_pomiar` wymagała kompletnego new_values dict (wszystkie 6 pól). Zmieniamy semantykę: PARTIAL update. To jest kompatybilne z RBAC — endpoint może przekazać tylko dozwolone pola.

Zaktualizuj `get_session_with_pomiary` — rozszerz SELECT o ext fields:

```python
def get_session_with_pomiary(db, session_id: int) -> dict:
    srow = db.execute(
        "SELECT s.id, s.dt_start, s.n_kontenery, s.created_at, s.created_by, "
        "       s.finalized_at, s.finalized_by, "
        "       w.imie || ' ' || w.nazwisko AS finalized_by_name "
        "FROM chzt_sesje s "
        "LEFT JOIN workers w ON w.id = s.finalized_by "
        "WHERE s.id=?",
        (session_id,),
    ).fetchone()
    if srow is None:
        return None
    prows = db.execute(
        "SELECT id, punkt_nazwa, kolejnosc, ph, p1, p2, p3, p4, p5, srednia, "
        "       ext_chzt, ext_ph, waga_kg, updated_at, updated_by "
        "FROM chzt_pomiary WHERE sesja_id=? ORDER BY kolejnosc",
        (session_id,),
    ).fetchall()
    return {**dict(srow), "punkty": [dict(p) for p in prows]}
```

Zaktualizuj `list_sessions_paginated` — `s.data` → `s.dt_start`:

```python
def list_sessions_paginated(db, *, page: int = 1, per_page: int = 10) -> dict:
    page = max(1, int(page))
    per_page = max(1, min(100, int(per_page)))
    offset = (page - 1) * per_page

    total_row = db.execute("SELECT COUNT(*) AS c FROM chzt_sesje").fetchone()
    total = total_row["c"] if total_row else 0
    pages = max(1, (total + per_page - 1) // per_page)

    rows = db.execute(
        "SELECT s.id, s.dt_start, s.n_kontenery, s.finalized_at, "
        "       w.imie || ' ' || w.nazwisko AS finalized_by_name, "
        "       (SELECT MAX(updated_at) FROM chzt_pomiary WHERE sesja_id=s.id) AS updated_at_max, "
        "       (SELECT ROUND(AVG(srednia)) FROM chzt_pomiary WHERE sesja_id=s.id AND srednia IS NOT NULL) AS avg_chzt, "
        "       (SELECT ROUND(MIN(srednia)) FROM chzt_pomiary WHERE sesja_id=s.id AND srednia IS NOT NULL) AS min_chzt, "
        "       (SELECT ROUND(MAX(srednia)) FROM chzt_pomiary WHERE sesja_id=s.id AND srednia IS NOT NULL) AS max_chzt, "
        "       (SELECT COUNT(*) FROM chzt_pomiary WHERE sesja_id=s.id AND srednia IS NOT NULL AND srednia > 40000) AS over_40k_count, "
        "       (SELECT ROUND(AVG(ph), 1) FROM chzt_pomiary WHERE sesja_id=s.id AND ph IS NOT NULL) AS avg_ph "
        "FROM chzt_sesje s "
        "LEFT JOIN workers w ON w.id = s.finalized_by "
        "ORDER BY s.dt_start DESC "
        "LIMIT ? OFFSET ?",
        (per_page, offset),
    ).fetchall()
    return {
        "sesje": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "pages": pages,
        "per_page": per_page,
    }
```

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/test_chzt.py::test_update_pomiar_writes_ext_fields tests/test_chzt.py::test_get_pomiar_includes_ext_fields tests/test_chzt.py::test_get_session_with_pomiary_includes_ext_fields tests/test_chzt.py::test_list_sessions_paginated_sorts_by_dt_start_desc -v`
Expected: 4 passed.

- [ ] **Step 5: Fix existing tests że używają starej signatury `update_pomiar` (kompletny dict)**

Wiele istniejących testów wywołuje:
```python
update_pomiar(db, pid, {"ph": 10, "p1": 100, "p2": 200, "p3": None, "p4": None, "p5": None}, updated_by=1)
```

Nowa wersja jest backward-compatible (6 pól wszystkich → pełny update dla internal). Testy powinny przejść bez zmian.

Ale test `test_update_pomiar_clears_srednia_if_lt_2` może wymagać sprawdzenia — sprawdź że srednia jest liczona poprawnie gdy tylko część pól w input. Uruchom:

Run: `pytest tests/test_chzt.py::test_update_pomiar_clears_srednia_if_lt_2 -v`
Expected: PASS.

Testy poprzedniej iteracji używające `list_sessions_paginated` — zaktualizować asserty jeśli opierały się na `data` (powinny używać `dt_start`). Przeszukaj: `grep -n '"data"' tests/test_chzt.py`.

Konkretne miejsca do zmiany:
- `test_list_sessions_paginated_desc_order` — zamiast INSERT sesji po dacie (`data="2026-04-16"`), używać `dt_start="2026-04-16T08:00:00"`:

```python
def test_list_sessions_paginated_desc_order(db):
    db.execute("INSERT INTO chzt_sesje (dt_start, n_kontenery, created_at) VALUES ('2026-04-16T08:00:00', 8, '2026-04-16T08:00:00')")
    db.execute("INSERT INTO chzt_sesje (dt_start, n_kontenery, created_at) VALUES ('2026-04-18T08:00:00', 8, '2026-04-18T08:00:00')")
    db.execute("INSERT INTO chzt_sesje (dt_start, n_kontenery, created_at) VALUES ('2026-04-17T08:00:00', 8, '2026-04-17T08:00:00')")
    db.commit()
    page = list_sessions_paginated(db, page=1, per_page=10)
    dts_prefixes = [s["dt_start"][:10] for s in page["sesje"]]
    assert dts_prefixes == ["2026-04-18", "2026-04-17", "2026-04-16"]
    assert page["total"] == 3
```

- `test_list_sessions_paginated_splits_pages` — wszystkie `data=` zamienić na `dt_start=` z datetime:

```python
for d in ["2026-04-01", "2026-04-02", ..., "2026-04-12"]:
    dt = d + "T08:00:00"
    db.execute("INSERT INTO chzt_sesje (dt_start, n_kontenery, created_at) VALUES (?, 0, ?)", (dt, dt))
    db.commit()
```

- `test_list_sessions_paginated_includes_avg_and_max` — testowana sesja teraz tworzona przez `create_session`, zostaje bez zmian jeśli używa helpera. Jeśli używa INSERT po `data=` — zamienić.

Run: `pytest tests/test_chzt.py -k "list_sessions_paginated" -v`
Expected: wszystkie PASS.

- [ ] **Step 6: Smoke test całego chzt suite (niektóre route'y jeszcze failują — to Task 4+)**

Run: `pytest tests/test_chzt.py -v 2>&1 | tail -30`

Zliczyć ile PASS/FAIL. Failujące powinny być głównie route'y używające `/today` lub `/session/<data_iso>` — to naprawimy w Task 4.

- [ ] **Step 7: Commit**

```bash
git add mbr/chzt/models.py tests/test_chzt.py
git commit -m "feat(chzt): partial-update update_pomiar + ext fields in get_pomiar / get_session_with_pomiary / list_sessions_paginated; sort by dt_start"
```

---

## Task 4: API — nowe endpointy /active, /new, /<int:id> + usunięcie /today, /<data_iso>

**Cel:** Przejście z date-keyed API na session-id API.

**Files:**
- Modify: `mbr/chzt/routes.py`
- Modify: `tests/test_chzt.py`

- [ ] **Step 1: Failing tests**

Dopisz (fixtures `client`, `admin_client` już istnieją):

```python
def test_session_active_returns_null_when_no_open(client, db):
    resp = client.get("/api/chzt/session/active")
    assert resp.status_code == 200
    assert resp.get_json() == {"session": None}


def test_session_active_returns_open_session(client, db):
    r1 = client.post("/api/chzt/session/new", json={"n_kontenery": 8})
    assert r1.status_code == 200
    sid = r1.get_json()["session"]["id"]
    r2 = client.get("/api/chzt/session/active")
    assert r2.status_code == 200
    assert r2.get_json()["session"]["id"] == sid


def test_session_new_creates_and_returns_session(client, db):
    resp = client.post("/api/chzt/session/new", json={"n_kontenery": 3})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["session"]["n_kontenery"] == 3
    assert len(data["session"]["punkty"]) == 6  # hala + rura + 3 kontener + szambiarka


def test_session_new_409_when_already_open(client, db):
    client.post("/api/chzt/session/new", json={"n_kontenery": 3})
    resp = client.post("/api/chzt/session/new", json={"n_kontenery": 3})
    assert resp.status_code == 409


def test_session_new_after_finalize_ok(client, db):
    r1 = client.post("/api/chzt/session/new", json={"n_kontenery": 0})
    sid1 = r1.get_json()["session"]["id"]
    # Fill required fields + finalize
    for p in r1.get_json()["session"]["punkty"]:
        client.put(f"/api/chzt/pomiar/{p['id']}", json={"ph": 10, "p1": 1, "p2": 2})
    client.post(f"/api/chzt/session/{sid1}/finalize")

    r2 = client.post("/api/chzt/session/new", json={"n_kontenery": 0})
    assert r2.status_code == 200
    assert r2.get_json()["session"]["id"] != sid1


def test_get_session_by_int_id(client, db):
    r1 = client.post("/api/chzt/session/new", json={"n_kontenery": 2})
    sid = r1.get_json()["session"]["id"]
    r2 = client.get(f"/api/chzt/session/{sid}")
    assert r2.status_code == 200
    assert r2.get_json()["session"]["id"] == sid


def test_get_session_by_int_id_404(client, db):
    resp = client.get("/api/chzt/session/99999")
    assert resp.status_code == 404


def test_session_new_logs_audit(client, db):
    client.post("/api/chzt/session/new", json={"n_kontenery": 3})
    rows = db.execute(
        "SELECT event_type FROM audit_log WHERE event_type='chzt.session.created'"
    ).fetchall()
    assert len(rows) == 1
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/test_chzt.py::test_session_active_returns_null_when_no_open tests/test_chzt.py::test_session_new_creates_and_returns_session -v`
Expected: 404/405 (route nie istnieje).

- [ ] **Step 3: Zaktualizuj `mbr/chzt/routes.py`**

**(a)** Usuń starą funkcję `api_session_today`:

```python
# DELETE:
# @chzt_bp.route("/api/chzt/session/today", methods=["GET"])
# @role_required(*ROLES_EDIT)
# def api_session_today(): ...
```

**(b)** Usuń starą funkcję `api_session_by_date`:

```python
# DELETE:
# @chzt_bp.route("/api/chzt/session/<data_iso>", methods=["GET"])
# @role_required(*ROLES_EDIT)
# def api_session_by_date(data_iso): ...
```

**(c)** Zmień importy na górze `routes.py`:

```python
from mbr.chzt.models import (
    get_active_session, create_session, get_session_with_pomiary,
    get_pomiar, update_pomiar, resize_kontenery,
    validate_for_finalize, finalize_session, unfinalize_session,
    list_sessions_paginated,
    POMIAR_FIELDS, POMIAR_FIELDS_INTERNAL, POMIAR_FIELDS_EXTERNAL,
)
```

Zamiast `ROLES_EDIT` (który zniknie w Task 5) tymczasowo wprowadź stałe (zostaną rozwinięte w Task 5):

```python
ROLES_VIEW = ("lab", "kj", "cert", "technolog", "admin", "produkcja")
ROLES_EDIT_INTERNAL = ("lab", "kj", "cert", "technolog", "admin")
ROLES_EDIT_EXTERNAL = ("produkcja", "technolog", "admin")
```

Usuń `ROLES_EDIT = ("lab", "kj", "cert", "technolog", "admin")` (zastąpione przez `ROLES_EDIT_INTERNAL`).

Zamień wszystkie `@role_required(*ROLES_EDIT)` na odpowiednie:
- `api_pomiar_update` → `@role_required(*ROLES_VIEW)` (RBAC per-pole w Task 5)
- `api_session_patch` (n_kontenery) → `@role_required(*ROLES_EDIT_INTERNAL)`
- `api_session_finalize` → `@role_required(*ROLES_EDIT_INTERNAL)`
- `api_session_unfinalize` już `@role_required("admin")` — zostaje
- `api_day_frame` → `@role_required(*ROLES_VIEW)`
- `api_history` → `@role_required(*ROLES_VIEW)`
- `historia_page` → `@role_required(*ROLES_VIEW)`

**(d)** Dodaj nowe handlery (w odpowiednim miejscu w pliku, np. po istniejących session endpointach):

```python
@chzt_bp.route("/api/chzt/session/active", methods=["GET"])
@role_required(*ROLES_VIEW)
def api_session_active():
    with db_session() as db:
        active = get_active_session(db)
        if active is None:
            return jsonify({"session": None})
        payload = get_session_with_pomiary(db, active["id"])
    return jsonify({"session": payload})


@chzt_bp.route("/api/chzt/session/new", methods=["POST"])
@role_required(*ROLES_EDIT_INTERNAL)
def api_session_create():
    payload = request.get_json(force=True) or {}
    n_kontenery = payload.get("n_kontenery", 8)
    if not isinstance(n_kontenery, int) or isinstance(n_kontenery, bool) or n_kontenery < 0 or n_kontenery > 20:
        return jsonify({"error": "n_kontenery: oczekuję int 0..20"}), 400

    with db_session() as db:
        try:
            session_id = create_session(db, created_by=_current_worker_id(), n_kontenery=n_kontenery)
        except ValueError as e:
            if "already_open" in str(e):
                return jsonify({"error": "Istnieje otwarta sesja — zakończ ją najpierw."}), 409
            raise
        log_event(
            EVENT_CHZT_SESSION_CREATED,
            entity_type="chzt_sesje",
            entity_id=session_id,
            db=db,
        )
        db.commit()
        payload_out = get_session_with_pomiary(db, session_id)
    return jsonify({"session": payload_out})


@chzt_bp.route("/api/chzt/session/<int:session_id>", methods=["GET"])
@role_required(*ROLES_VIEW)
def api_session_by_id(session_id: int):
    with db_session() as db:
        payload = get_session_with_pomiary(db, session_id)
        if payload is None:
            return jsonify({"error": "sesja nie istnieje"}), 404
    return jsonify({"session": payload})
```

- [ ] **Step 4: Tests PASS**

Run: `pytest tests/test_chzt.py -k "session_active or session_new or get_session_by_int" -v`
Expected: 8 passed.

- [ ] **Step 5: Update istniejące testy użwające `/today`**

Znajdź: `grep -n "/api/chzt/session/today" tests/test_chzt.py`

Dla każdego wystąpienia:
- `client.get("/api/chzt/session/today")` → `client.post("/api/chzt/session/new", json={"n_kontenery": 8})` (jeśli test chciał "utworzyć i zwrócić") lub `client.get("/api/chzt/session/active")` (jeśli chciał tylko sprawdzić istnienie).

Najczęściej kontekst testu — _fill_all_today, _get_today_pomiar_id, etc. — używają flow "utwórz sesję + wypełnij". Zastąp przez /new.

Przykładowo `_fill_all_today`:

```python
def _fill_all_today(client, db, ph=10, p1=100, p2=200):
    r = client.post("/api/chzt/session/new", json={"n_kontenery": 8}).get_json()
    sid = r["session"]["id"]
    for p in r["session"]["punkty"]:
        client.put(f"/api/chzt/pomiar/{p['id']}", json={
            "ph": ph, "p1": p1, "p2": p2, "p3": None, "p4": None, "p5": None
        })
    return sid
```

`_get_today_pomiar_id`:

```python
def _get_today_pomiar_id(client, db, punkt="hala"):
    resp = client.post("/api/chzt/session/new", json={"n_kontenery": 8})
    session_payload = resp.get_json()["session"]
    for p in session_payload["punkty"]:
        if p["punkt_nazwa"] == punkt:
            return p["id"]
    raise AssertionError(f"punkt {punkt} not found")
```

Uwaga: _get_today_pomiar_id wywołany kilkukrotnie w pojedynczym teście wywali 409. Zastąp przez helper który szuka istniejącej otwartej:

```python
def _get_today_pomiar_id(client, db, punkt="hala"):
    # Get active session (created if needed)
    active = client.get("/api/chzt/session/active").get_json()["session"]
    if active is None:
        active = client.post("/api/chzt/session/new", json={"n_kontenery": 8}).get_json()["session"]
    for p in active["punkty"]:
        if p["punkt_nazwa"] == punkt:
            return p["id"]
    raise AssertionError(f"punkt {punkt} not found")
```

Usuń testy:
- `test_session_today_creates_and_returns` — zastąpione przez testy w Step 1
- `test_session_today_idempotent` — idempotencja nie ma sensu (każde /new to nowa sesja)
- `test_session_today_logs_created_audit` — logic przeniesione na /new
- `test_session_today_logs_created_audit_only_once` — jak wyżej
- `test_get_session_by_date_ok` — endpoint zniknął
- `test_get_session_by_date_missing_404` — endpoint zniknął

- [ ] **Step 6: Run chzt suite — większość testów PASS, tylko RBAC-related failują**

Run: `pytest tests/test_chzt.py -v 2>&1 | tail -40`
Expected: testy RBAC per-pole (których jeszcze nie ma) brakują. Reszta przechodzi.

- [ ] **Step 7: Commit**

```bash
git add mbr/chzt/routes.py tests/test_chzt.py
git commit -m "feat(chzt): /session/active, /session/new, /session/<int:id> — replace date-keyed endpoints"
```

---

## Task 5: API — RBAC per-field in PUT /api/chzt/pomiar/<id>

**Cel:** Backend filtruje payload po rola: `lab` → ph+p1..p5, `produkcja` → ext_chzt+ext_ph+waga_kg, `admin/technolog` → wszystko.

**Files:**
- Modify: `mbr/chzt/routes.py`
- Modify: `tests/test_chzt.py`

- [ ] **Step 1: Failing tests**

Dopisz (nowy fixture dla produkcja client):

```python
@pytest.fixture
def produkcja_client(monkeypatch, db):
    import mbr.db
    import mbr.chzt.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.chzt.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = {"login": "mag", "rola": "produkcja", "imie_nazwisko": "Jan Magazyn"}
    return c


def _bootstrap_session_with_lab(client):
    """Utility: create open session as lab."""
    r = client.post("/api/chzt/session/new", json={"n_kontenery": 0})
    return r.get_json()["session"]


def test_lab_put_pomiar_can_write_internal_fields(client, db):
    s = _bootstrap_session_with_lab(client)
    pid = s["punkty"][0]["id"]
    resp = client.put(f"/api/chzt/pomiar/{pid}", json={
        "ph": 10, "p1": 100, "p2": 200
    })
    assert resp.status_code == 200
    row = db.execute("SELECT ph, p1, p2, ext_chzt FROM chzt_pomiary WHERE id=?", (pid,)).fetchone()
    assert row["ph"] == 10
    assert row["p1"] == 100


def test_lab_put_pomiar_cannot_write_ext_fields(client, db):
    s = _bootstrap_session_with_lab(client)
    pid = s["punkty"][0]["id"]
    # Lab próbuje ustawić ext_chzt — powinno zostać zignorowane
    client.put(f"/api/chzt/pomiar/{pid}", json={
        "ph": 10, "p1": 100, "p2": 200,
        "ext_chzt": 99999, "ext_ph": 99, "waga_kg": 99999,
    })
    row = db.execute("SELECT ph, ext_chzt, ext_ph, waga_kg FROM chzt_pomiary WHERE id=?", (pid,)).fetchone()
    assert row["ph"] == 10  # internal written
    assert row["ext_chzt"] is None  # ext silent-dropped
    assert row["ext_ph"] is None
    assert row["waga_kg"] is None


def test_produkcja_put_pomiar_can_write_ext_fields(produkcja_client, client, db):
    # Lab tworzy sesję (produkcja nie może)
    s = _bootstrap_session_with_lab(client)
    pid = s["punkty"][-1]["id"]  # szambiarka
    resp = produkcja_client.put(f"/api/chzt/pomiar/{pid}", json={
        "ext_chzt": 13250, "ext_ph": 11, "waga_kg": 19060
    })
    assert resp.status_code == 200
    row = db.execute("SELECT ext_chzt, ext_ph, waga_kg, ph FROM chzt_pomiary WHERE id=?", (pid,)).fetchone()
    assert row["ext_chzt"] == 13250
    assert row["ext_ph"] == 11
    assert row["waga_kg"] == 19060
    assert row["ph"] is None  # lab hasn't filled it


def test_produkcja_put_pomiar_cannot_write_internal(produkcja_client, client, db):
    s = _bootstrap_session_with_lab(client)
    # Lab najpierw ustawia ph
    client.put(f"/api/chzt/pomiar/{s['punkty'][0]['id']}", json={"ph": 10, "p1": 100, "p2": 200})
    pid = s["punkty"][0]["id"]
    # Produkcja próbuje nadpisać ph
    produkcja_client.put(f"/api/chzt/pomiar/{pid}", json={"ph": 99, "ext_chzt": 5000})
    row = db.execute("SELECT ph, ext_chzt FROM chzt_pomiary WHERE id=?", (pid,)).fetchone()
    assert row["ph"] == 10  # NIE nadpisane przez produkcja
    assert row["ext_chzt"] == 5000


def test_produkcja_cannot_create_session(produkcja_client, db):
    resp = produkcja_client.post("/api/chzt/session/new", json={"n_kontenery": 8})
    assert resp.status_code == 403


def test_produkcja_can_view_history(produkcja_client, client, db):
    _bootstrap_session_with_lab(client)
    resp = produkcja_client.get("/api/chzt/history")
    assert resp.status_code == 200


def test_admin_put_pomiar_can_write_all_fields(admin_client, client, db):
    s = _bootstrap_session_with_lab(client)
    pid = s["punkty"][-1]["id"]
    resp = admin_client.put(f"/api/chzt/pomiar/{pid}", json={
        "ph": 10, "p1": 100, "p2": 200,
        "ext_chzt": 5000, "ext_ph": 11, "waga_kg": 1000,
    })
    assert resp.status_code == 200
    row = db.execute(
        "SELECT ph, p1, ext_chzt, ext_ph, waga_kg FROM chzt_pomiary WHERE id=?", (pid,)
    ).fetchone()
    assert row["ph"] == 10
    assert row["p1"] == 100
    assert row["ext_chzt"] == 5000
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/test_chzt.py::test_lab_put_pomiar_cannot_write_ext_fields tests/test_chzt.py::test_produkcja_put_pomiar_can_write_ext_fields -v`
Expected: oba FAIL — endpoint nie filtruje per rola.

- [ ] **Step 3: Implement RBAC filtering in `api_pomiar_update`**

W `mbr/chzt/routes.py` dodaj helper (po `_current_worker_id`):

```python
def _allowed_fields_for_role(rola: str) -> tuple:
    if rola in ("admin", "technolog"):
        return POMIAR_FIELDS
    if rola in ("lab", "kj", "cert"):
        return POMIAR_FIELDS_INTERNAL
    if rola == "produkcja":
        return POMIAR_FIELDS_EXTERNAL
    return ()
```

Zaktualizuj `api_pomiar_update`:

```python
@chzt_bp.route("/api/chzt/pomiar/<int:pomiar_id>", methods=["PUT"])
@role_required(*ROLES_VIEW)
def api_pomiar_update(pomiar_id: int):
    payload = request.get_json(force=True) or {}
    rola = session.get("user", {}).get("rola") or ""
    allowed = _allowed_fields_for_role(rola)

    # Filter: keep only allowed keys that are actually present in payload
    new_values = {}
    for k in allowed:
        if k in payload:
            new_values[k] = _coerce_float(payload[k])

    with db_session() as db:
        old = get_pomiar(db, pomiar_id)
        if old is None:
            return jsonify({"error": "pomiar nie istnieje"}), 404

        if not new_values:
            # Nothing to write — return current state without audit
            return jsonify({"pomiar": old})

        # Build diff only on the subset we're writing
        changes = diff_fields(old, new_values, list(new_values.keys()))

        try:
            updated = update_pomiar(db, pomiar_id, new_values, updated_by=_current_worker_id())
        except ValueError:
            return jsonify({"error": "pomiar nie istnieje"}), 404

        if changes:
            log_event(
                EVENT_CHZT_POMIAR_UPDATED,
                entity_type="chzt_pomiary",
                entity_id=pomiar_id,
                entity_label=old["punkt_nazwa"],
                diff=changes,
                context={"sesja_id": old["sesja_id"]},
                db=db,
            )
        db.commit()

    return jsonify({"pomiar": updated})
```

- [ ] **Step 4: Tests PASS**

Run: `pytest tests/test_chzt.py -k "lab_put or produkcja_put or admin_put or produkcja_cannot or produkcja_can_view" -v`
Expected: 7 passed.

- [ ] **Step 5: Pełny chzt suite**

Run: `pytest tests/test_chzt.py -v 2>&1 | tail -20`
Expected: wszystkie PASS.

- [ ] **Step 6: Full suite smoke**

Run: `pytest -q 2>&1 | tail -5`
Expected: no regressions.

- [ ] **Step 7: Commit**

```bash
git add mbr/chzt/routes.py tests/test_chzt.py
git commit -m "feat(chzt): per-field RBAC in PUT pomiar (lab=internal, produkcja=external, admin=all)"
```

---

## Task 6: API — day endpoint uses DATE(dt_start) + includes ext fields

**Cel:** Endpoint `/api/chzt/day/<data>` szuka po `DATE(dt_start)` i zwraca pola zewnętrzne.

**Files:**
- Modify: `mbr/chzt/routes.py`
- Modify: `tests/test_chzt.py`

- [ ] **Step 1: Failing tests**

Dopisz:

```python
def test_day_endpoint_finds_by_dt_start_date(client, db):
    """Session starting 2026-04-18T22:00 is found by /day/2026-04-18, not /day/2026-04-19."""
    # Create + fill + finalize with specific dt_start
    db.execute(
        "INSERT INTO chzt_sesje (dt_start, n_kontenery, created_at, finalized_at, finalized_by) "
        "VALUES ('2026-04-18T22:00:00', 0, '2026-04-18T22:00:00', '2026-04-19T06:00:00', 1)"
    )
    sid = db.execute("SELECT id FROM chzt_sesje WHERE dt_start='2026-04-18T22:00:00'").fetchone()["id"]
    for idx, name in enumerate(["hala", "rura", "szambiarka"], start=1):
        db.execute(
            "INSERT INTO chzt_pomiary (sesja_id, punkt_nazwa, kolejnosc, ph, p1, p2, srednia, "
            "ext_chzt, ext_ph, waga_kg, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, name, idx, 10, 100, 200, 150,
             13250 if name == "szambiarka" else None,
             11 if name == "szambiarka" else None,
             19060 if name == "szambiarka" else None,
             "2026-04-18T22:30:00"),
        )
    db.commit()

    r1 = client.get("/api/chzt/day/2026-04-18")
    assert r1.status_code == 200
    body = r1.get_json()
    assert body["dt_start"].startswith("2026-04-18T22")
    szamb = next(p for p in body["punkty"] if p["nazwa"] == "szambiarka")
    assert szamb["ext_chzt"] == 13250
    assert szamb["ext_ph"] == 11
    assert szamb["waga_kg"] == 19060

    # /day/2026-04-19 nie znajduje — sesja startowała 18
    r2 = client.get("/api/chzt/day/2026-04-19")
    assert r2.status_code == 404


def test_day_endpoint_ignores_draft(client, db):
    """Open session (not finalized) returns 404 on /day endpoint."""
    db.execute(
        "INSERT INTO chzt_sesje (dt_start, n_kontenery, created_at) "
        "VALUES ('2026-04-20T10:00:00', 0, '2026-04-20T10:00:00')"
    )
    db.commit()
    resp = client.get("/api/chzt/day/2026-04-20")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/test_chzt.py::test_day_endpoint_finds_by_dt_start_date -v`
Expected: FAIL (stary endpoint używa `data=?`).

- [ ] **Step 3: Update `api_day_frame` in `mbr/chzt/routes.py`**

```python
@chzt_bp.route("/api/chzt/day/<data_iso>", methods=["GET"])
@role_required(*ROLES_VIEW)
def api_day_frame(data_iso: str):
    """Export frame for Excel script. Returns newest finalized session whose
    DATE(dt_start) matches. Max 1/day guaranteed by policy — LIMIT 1.
    Includes ext fields (ext_chzt, ext_ph, waga_kg)."""
    with db_session() as db:
        row = db.execute(
            "SELECT id, dt_start, finalized_at "
            "FROM chzt_sesje "
            "WHERE DATE(dt_start) = ? AND finalized_at IS NOT NULL "
            "ORDER BY dt_start DESC LIMIT 1",
            (data_iso,),
        ).fetchone()
        if row is None:
            return jsonify({"error": "brak sfinalizowanej sesji"}), 404
        prows = db.execute(
            "SELECT punkt_nazwa, ph, srednia, ext_chzt, ext_ph, waga_kg "
            "FROM chzt_pomiary WHERE sesja_id=? ORDER BY kolejnosc",
            (row["id"],),
        ).fetchall()
        punkty = [
            {
                "nazwa": p["punkt_nazwa"],
                "ph": p["ph"],
                "srednia": p["srednia"],
                "ext_chzt": p["ext_chzt"],
                "ext_ph": p["ext_ph"],
                "waga_kg": p["waga_kg"],
            }
            for p in prows
        ]
    return jsonify({
        "dt_start": row["dt_start"],
        "finalized_at": row["finalized_at"],
        "punkty": punkty,
    })
```

Uwaga: zmieniamy kluczy response z `data` na `dt_start`. Stary skrypt zewnętrzny (jeśli istnieje) musi się dostosować. Spec explicit "poza zakresem".

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/test_chzt.py::test_day_endpoint_finds_by_dt_start_date tests/test_chzt.py::test_day_endpoint_ignores_draft -v`
Expected: 2 passed.

- [ ] **Step 5: Update istniejące testy `/day`**

`test_get_day_finalized_returns_frame` i `test_get_day_draft_returns_404` — zaktualizować aby sprawdzały `body["dt_start"]` zamiast `body["data"]`.

Znajdź: `grep -n "test_get_day" tests/test_chzt.py`

Zmień assertion:
```python
assert body["data"] == today        # STARE
assert body["dt_start"].startswith(today)  # NOWE
```

- [ ] **Step 6: Pełne testy chzt**

Run: `pytest tests/test_chzt.py -v 2>&1 | tail -10`
Expected: wszystkie PASS.

- [ ] **Step 7: Commit**

```bash
git add mbr/chzt/routes.py tests/test_chzt.py
git commit -m "feat(chzt): day endpoint uses DATE(dt_start) + returns ext fields"
```

---

## Task 7: UI — Modal create-pane (template + JS + CSS)

**Cel:** Klik karty "ChZT Ścieków" → fetch `/api/chzt/session/active` → jeśli brak aktywnej, pokazać picker n_kontenery + przycisk "Rozpocznij sesję".

**Files:**
- Modify: `mbr/chzt/templates/chzt_modal.html`
- Modify: `mbr/chzt/static/chzt.js`
- Modify: `mbr/chzt/static/chzt.css`
- Modify: `mbr/templates/technolog/narzedzia.html` (bumpnąć cache-bust)
- Modify: `mbr/chzt/templates/chzt_historia.html` (bumpnąć cache-bust)

- [ ] **Step 1: Update modal template**

W `mbr/chzt/templates/chzt_modal.html`, znajdź `<div class="chzt-modal">` i na początku (przed `<div class="chzt-head">`) dodaj create-pane:

```html
<!-- Create-pane state: shown when no active session exists -->
<div class="chzt-create-pane" id="chzt-create-pane" style="display:none;">
  <div class="chzt-create-inner">
    <div class="chzt-create-eyebrow">ChZT Ścieków</div>
    <h2 class="chzt-create-title">Rozpocznij nową sesję pomiarową</h2>
    <div class="chzt-create-form">
      <label for="chzt-create-n">Liczba kontenerów</label>
      <input type="number" id="chzt-create-n" value="8" min="0" max="20">
    </div>
    <div class="chzt-create-error" id="chzt-create-error"></div>
    <button class="chzt-btn-primary" id="chzt-create-submit" onclick="chztSubmitNew()">Rozpocznij sesję</button>
  </div>
</div>
```

Istniejący `<div class="chzt-head">...`, `<div class="chzt-subbar">...`, table wrapper — wszystkie muszą być w kontenerze który można ukryć. Zawiń je w:

```html
<div class="chzt-edit-pane" id="chzt-edit-pane">
  <div class="chzt-head">...</div>
  <div class="chzt-finalize-banner">...</div>
  <div class="chzt-subbar">...</div>
  <div id="chzt-body" class="chzt-body"></div>
  <div class="chzt-errors">...</div>
  <div class="chzt-footer">...</div>
</div>
```

- [ ] **Step 2: Update CSS**

Dopisz do `mbr/chzt/static/chzt.css` (sekcja modala):

```css
.chzt-create-pane {
  padding: 48px 40px;
  display: flex; align-items: center; justify-content: center;
  flex-direction: column;
  min-height: 320px;
}
.chzt-create-inner {
  width: 100%; max-width: 380px;
  text-align: center;
}
.chzt-create-eyebrow {
  font-size: 11px; font-weight: 500;
  letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--teal);
  margin-bottom: 10px;
}
.chzt-create-title {
  font-size: 20px; font-weight: 300;
  color: var(--text); letter-spacing: -0.5px;
  margin-bottom: 28px;
}
.chzt-create-form {
  display: flex; flex-direction: column; align-items: center; gap: 10px;
  margin-bottom: 20px;
}
.chzt-create-form label {
  font-size: 12px; font-weight: 600; color: var(--text-sec);
  text-transform: uppercase; letter-spacing: 0.3px;
}
.chzt-create-form input {
  width: 120px; height: 44px;
  padding: 8px 12px;
  border: 1px solid var(--border); border-radius: 6px;
  font-family: var(--mono); font-size: 18px; font-weight: 600;
  text-align: center;
  background: var(--surface); color: var(--text);
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.chzt-create-form input:focus {
  border-color: var(--teal);
  box-shadow: 0 0 0 3px rgba(13,115,119,0.14);
}
.chzt-create-error {
  color: var(--red); font-size: 11px;
  margin-bottom: 10px; min-height: 14px;
}
.chzt-create-pane .chzt-btn-primary {
  padding: 10px 24px; font-size: 13px;
}
.chzt-edit-pane {
  display: flex; flex-direction: column;
  flex: 1; overflow: hidden; min-height: 0;
}
.chzt-edit-pane[style*="none"] + .chzt-create-pane,
.chzt-edit-pane {
  /* State swap controlled via JS */
}
```

- [ ] **Step 3: Update JS — add state swap logic**

W `mbr/chzt/static/chzt.js` znajdź funkcję `window.openChztModal`. Zastąp ją:

```javascript
  window.openChztModal = function(dataIso) {
    el('chzt-overlay').classList.add('show');
    el('chzt-errors').style.display = 'none';
    el('chzt-toolbar-error').textContent = '';
    el('chzt-create-error').textContent = '';
    if (dataIso) {
      // Historia edit entry — load specific session by date
      // (fallback for back-compat; in new code flow, historia uses chztShowDetail)
      _showEditPane();
      loadSession(encodeURIComponent(dataIso));
    } else {
      // From narzedzia card: try active session, else show create pane
      loadActiveOrCreate();
    }
  };

  function _showCreatePane() {
    el('chzt-create-pane').style.display = '';
    el('chzt-edit-pane').style.display = 'none';
  }

  function _showEditPane() {
    el('chzt-create-pane').style.display = 'none';
    el('chzt-edit-pane').style.display = '';
  }

  function loadActiveOrCreate() {
    fetch('/api/chzt/session/active', {headers: {'Accept': 'application/json'}})
      .then(function(r){ if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function(resp){
        if (resp.session === null) {
          _showCreatePane();
          el('chzt-create-n').value = 8;
          setTimeout(function(){ el('chzt-create-n').focus(); el('chzt-create-n').select(); }, 50);
        } else {
          _showEditPane();
          _session = resp.session;
          el('chzt-n-kontenery').value = _session.n_kontenery;
          var pct = _session.punkty.length;
          el('chzt-meta-punkty').textContent = pct + ' punktów';
          el('chzt-meta-kontenery').textContent = _session.n_kontenery + ' kontenerów';
          renderDate();
          renderTable();
          renderFinalizedBanner();
          initialStatus();
        }
      })
      .catch(function(){
        _showEditPane();
        setStatus('error', '🔴 nie udało się wczytać');
      });
  }

  window.chztSubmitNew = function() {
    var input = el('chzt-create-n');
    var n = parseInt(input.value);
    var errBox = el('chzt-create-error');
    if (isNaN(n) || n < 0 || n > 20) {
      errBox.textContent = 'Oczekuję liczby 0–20';
      return;
    }
    errBox.textContent = '';
    var btn = el('chzt-create-submit');
    btn.disabled = true;
    btn.textContent = 'Tworzenie…';

    fetch('/api/chzt/session/new', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({n_kontenery: n}),
    }).then(function(r){
      if (r.status === 409) {
        return r.json().then(function(b){
          errBox.textContent = b.error || 'Istnieje otwarta sesja';
          throw new Error('conflict');
        });
      }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function(resp){
      _session = resp.session;
      _showEditPane();
      el('chzt-n-kontenery').value = _session.n_kontenery;
      el('chzt-meta-punkty').textContent = _session.punkty.length + ' punktów';
      el('chzt-meta-kontenery').textContent = _session.n_kontenery + ' kontenerów';
      renderDate();
      renderTable();
      renderFinalizedBanner();
      initialStatus();
      btn.disabled = false;
      btn.textContent = 'Rozpocznij sesję';
    }).catch(function(){
      btn.disabled = false;
      btn.textContent = 'Rozpocznij sesję';
    });
  };
```

**Update `loadSession(urlSuffix)`** — używana przez historia edit (i fallback przy openChztModal(dataIso)):

Zachowaj istniejącą funkcję, ale zaktualizuj URL — nowy endpoint dla historia edit to `/api/chzt/session/<int:id>` po numerycznym id. W `loadSession` używa starego `/api/chzt/session/<data>` który usunęliśmy. Zmień na:

```javascript
function loadSession(urlSuffix) {
  // urlSuffix może być numerycznym id sesji
  setStatus('saving', '🟡 ładowanie…');
  fetch('/api/chzt/session/' + urlSuffix, {
    headers: {'Accept': 'application/json'},
  }).then(function(r){
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }).then(function(resp){
    _session = resp.session;
    el('chzt-n-kontenery').value = _session.n_kontenery;
    renderDate();
    renderTable();
    renderFinalizedBanner();
    initialStatus();
  }).catch(function(){
    setStatus('error', '🔴 nie udało się wczytać');
  });
}
```

**Update `renderDate`** — teraz `_session.data` nie istnieje, jest `_session.dt_start`:

```javascript
function renderDate() {
  if (!_session) return;
  // dt_start = "2026-04-18T14:22:00" → "18.04.2026 14:22"
  var iso = _session.dt_start || '';
  var parts = iso.split('T');
  var dateParts = (parts[0] || '').split('-');
  var timeParts = (parts[1] || '').split(':');
  var formatted = (dateParts[2] || '—') + '.' + (dateParts[1] || '—') + '.' + (dateParts[0] || '—');
  if (timeParts.length >= 2) {
    formatted += ' ' + timeParts[0] + ':' + timeParts[1];
  }
  el('chzt-date').textContent = formatted;
}
```

- [ ] **Step 4: Update historia template — klik wiersza używa id**

W `mbr/chzt/templates/chzt_historia.html` znajdź row onclick:

```jinja
<tr class="chzt-hist-row" ... onclick="chztShowDetail({{ s.id }}, '{{ s.data }}')">
```

Zmień na:

```jinja
<tr class="chzt-hist-row" data-sid="{{ s.id }}" data-dt-start="{{ s.dt_start }}" onclick="chztShowDetail({{ s.id }}, '{{ s.dt_start }}')">
```

Zaktualizuj kolumnę `Data`:

```jinja
<th class="th-date">Rozpoczęto</th>
...
<td class="td-date-iso">{{ s.dt_start|replace('T', ' ')[:16] }}</td>
```

W `chztShowDetail` w JS — zamiast `fetchJson('/api/chzt/session/' + encodeURIComponent(dataIso))` użyj id:

```javascript
window.chztShowDetail = function(sid, dtStart) {
  // ...
  fetchJson('/api/chzt/session/' + sid).then(function(resp){
    // ... same as before
  });
};
```

Ustaw datę w headerze detail view z `dtStart`:

```javascript
if (dateEl) {
  var iso = dtStart || '';
  var p = iso.split('T');
  var d = (p[0] || '').split('-');
  var t = (p[1] || '').split(':');
  var fmt = (d[2] || '—') + '.' + (d[1] || '—') + '.' + (d[0] || '—');
  if (t.length >= 2) fmt += ' ' + t[0] + ':' + t[1];
  dateEl.textContent = fmt;
}
```

- [ ] **Step 5: Bump cache-bust in templates**

Znajdź `?v=8` w `mbr/chzt/templates/chzt_historia.html` i `mbr/templates/technolog/narzedzia.html`. Zamień na `?v=9`.

Run: `grep -rn "?v=" mbr/chzt/templates/ mbr/templates/technolog/narzedzia.html`
Expected: wszystkie `?v=9`.

- [ ] **Step 6: Smoke test — aplikacja startuje + tests**

```bash
python -c "from mbr.app import create_app; create_app()"
node --check mbr/chzt/static/chzt.js
pytest tests/test_chzt.py -q
```

Expected: all three OK.

Manualny smoke (dopisać checklistę w commicie):
- Kliknij "ChZT Ścieków" z brakiem aktywnej sesji → widać create-pane z input + przyciskiem
- Klik "Rozpocznij sesję" → modal przechodzi w edit mode, tabela wypełniona punktami
- Ponowny klik karty → widać tę samą otwartą sesję w edit mode (nie create-pane)

- [ ] **Step 7: Commit**

```bash
git add mbr/chzt/ mbr/templates/technolog/narzedzia.html
git commit -m "feat(chzt): modal create-pane state + loadActiveSession flow + dt_start in detail title"
```

---

## Task 8: UI — Detail view "Analiza zewnętrzna" section (szambiarka)

**Cel:** W `/chzt/historia` detail view, pod główną tabelą pomiarów, dolna sekcja z 3 polami (ext_chzt, ext_ph, waga_kg) — edytowalnymi dla produkcja/admin/technolog, readonly dla innych.

**Files:**
- Modify: `mbr/chzt/static/chzt.js` (extend `chztShowDetail`)
- Modify: `mbr/chzt/static/chzt.css` (add `.chzt-ext-section`, `.chzt-inp.readonly`)
- Modify: `mbr/chzt/templates/chzt_historia.html` — expose `user_rola` do JS

- [ ] **Step 1: Expose user rola in historia template**

Na początku `mbr/chzt/templates/chzt_historia.html` w `{% block content %}` (po link) dodaj:

```jinja
<script>
  window._chztUserRola = {{ session.user.rola|tojson }};
</script>
```

Musi być przed `<script src="chzt.js">`, najlepiej od razu po `<link>`.

- [ ] **Step 2: Extend `chztShowDetail` in chzt.js**

Znajdź koniec `chztShowDetail` — po wire'owaniu `wireInputHandlers('#chzt-detail-tbody')` i styleAvgCell loop. Dopisz renderowanie sekcji ext:

```javascript
function _canEditExt(rola) {
  return ['produkcja', 'admin', 'technolog'].indexOf(rola) >= 0;
}

function _canEditInternal(rola) {
  return ['lab', 'kj', 'cert', 'admin', 'technolog'].indexOf(rola) >= 0;
}

// Modify chztShowDetail body — rozszerz:

window.chztShowDetail = function(sid, dtStart) {
  flushDirtyRows();

  var listView = el('chzt-list-view');
  var detailView = el('chzt-detail-view');
  var tbody = el('chzt-detail-tbody');
  var badge = el('chzt-detail-badge');
  var dateEl = el('chzt-detail-date');
  var statusEl = el('chzt-detail-status');
  if (!listView || !detailView || !tbody) return;

  listView.style.display = 'none';
  detailView.style.display = '';
  tbody.innerHTML = '<tr><td colspan="8" class="chzt-card-loading">wczytywanie…</td></tr>';
  if (badge) badge.innerHTML = '';
  if (statusEl) { statusEl.className = 'chzt-expand-status'; statusEl.textContent = ''; }

  // Remove any prior ext section (from a previous detail open)
  var prevExt = document.getElementById('chzt-ext-section');
  if (prevExt) prevExt.remove();

  // Format date
  if (dateEl) {
    var p = (dtStart || '').split('T');
    var d = (p[0] || '').split('-');
    var t = (p[1] || '').split(':');
    var fmt = (d[2] || '—') + '.' + (d[1] || '—') + '.' + (d[0] || '—');
    if (t.length >= 2) fmt += ' ' + t[0] + ':' + t[1];
    dateEl.textContent = fmt;
  }

  fetchJson('/api/chzt/session/' + sid).then(function(resp){
    _session = resp.session;
    var rola = window._chztUserRola || 'lab';

    if (badge) {
      if (_session.finalized_at) {
        var who = _session.finalized_by_name || '—';
        badge.innerHTML = '<span class="chzt-expand-finalized">✓ Ukończono ' +
          fmtTime(_session.finalized_at) + ' · ' + escapeHtmlHist(who) + '</span>';
      } else {
        badge.innerHTML = '<span class="chzt-expand-draft">● Otwarta</span>';
      }
    }

    // Main pomiary table
    var canEditInt = _canEditInternal(rola);
    var rows = '';
    _session.punkty.forEach(function(p) {
      var warn = p.srednia !== null && p.srednia > 40000;
      rows += '<tr data-pid="' + p.id + '"' + (warn ? ' class="row-warn"' : '') + '>' +
        '<td>' + escapeHtmlHist(p.punkt_nazwa) + '</td>' +
        inputCell(p, 'ph', 'chzt-ph' + (canEditInt ? '' : ' readonly'), !canEditInt) +
        inputCell(p, 'p1', canEditInt ? '' : 'readonly', !canEditInt) +
        inputCell(p, 'p2', canEditInt ? '' : 'readonly', !canEditInt) +
        inputCell(p, 'p3', canEditInt ? '' : 'readonly', !canEditInt) +
        inputCell(p, 'p4', canEditInt ? '' : 'readonly', !canEditInt) +
        inputCell(p, 'p5', canEditInt ? '' : 'readonly', !canEditInt) +
        '<td><span class="srednia-val' + (warn ? ' warn' : '') + '" id="chzt-avg-' + p.id + '">' +
          (p.srednia === null ? '—' : Math.round(p.srednia).toLocaleString('pl-PL')) +
        '</span></td>' +
        '</tr>';
    });
    tbody.innerHTML = rows;

    wireInputHandlers('#chzt-detail-tbody');

    _session.punkty.forEach(function(p) {
      var avgEl = el('chzt-avg-' + p.id);
      if (avgEl) styleAvgCell(avgEl, p.srednia);
    });

    // Render ext section (szambiarka)
    _renderExtSection(rola);

  }).catch(function(){
    tbody.innerHTML = '<tr><td colspan="8" class="chzt-card-loading">błąd wczytywania</td></tr>';
  });
};

function _renderExtSection(rola) {
  if (!_session) return;
  var szambiarka = _session.punkty.find(function(p){ return p.punkt_nazwa === 'szambiarka'; });
  if (!szambiarka) return;

  var canEdit = _canEditExt(rola);
  var detailView = el('chzt-detail-view');
  if (!detailView) return;

  var section = document.createElement('div');
  section.id = 'chzt-ext-section';
  section.className = 'chzt-ext-section';

  var fmt = function(v) { return v === null || v === undefined ? '' : v; };

  section.innerHTML =
    '<div class="chzt-ext-title">Analiza zewnętrzna — Szambiarka</div>' +
    '<div class="chzt-ext-grid">' +
      '<div class="chzt-ext-field">' +
        '<label>pH zewnętrzne</label>' +
        '<input class="chzt-inp ' + (canEdit ? '' : 'readonly') + '" type="text" inputmode="decimal" pattern="[0-9]*[.,]?[0-9]*" ' +
               'data-pid="' + szambiarka.id + '" data-field="ext_ph" value="' + fmt(szambiarka.ext_ph) + '" ' +
               (canEdit ? '' : 'disabled') + '>' +
      '</div>' +
      '<div class="chzt-ext-field">' +
        '<label>ChZT zewnętrzne</label>' +
        '<input class="chzt-inp ' + (canEdit ? '' : 'readonly') + '" type="text" inputmode="decimal" pattern="[0-9]*[.,]?[0-9]*" ' +
               'data-pid="' + szambiarka.id + '" data-field="ext_chzt" value="' + fmt(szambiarka.ext_chzt) + '" ' +
               (canEdit ? '' : 'disabled') + '>' +
        '<span class="chzt-ext-unit">mg O₂/l</span>' +
      '</div>' +
      '<div class="chzt-ext-field">' +
        '<label>Waga beczki</label>' +
        '<input class="chzt-inp ' + (canEdit ? '' : 'readonly') + '" type="text" inputmode="decimal" pattern="[0-9]*[.,]?[0-9]*" ' +
               'data-pid="' + szambiarka.id + '" data-field="waga_kg" value="' + fmt(szambiarka.waga_kg) + '" ' +
               (canEdit ? '' : 'disabled') + '>' +
        '<span class="chzt-ext-unit">kg</span>' +
      '</div>' +
    '</div>';

  // Insert after the main .registry (i.e. after the detail table wrapper)
  var registryEl = detailView.querySelector('.registry');
  if (registryEl && registryEl.parentNode) {
    registryEl.parentNode.insertAdjacentElement('afterend', section);
  } else {
    detailView.appendChild(section);
  }

  // Wire handlers for editable ext inputs
  if (canEdit) {
    wireInputHandlers('#chzt-ext-section');
  }
}
```

**Update `inputCell`** — zaktualizuj signature aby przyjmowało `disabled` flag (obecnie ma tylko extraCls):

Znajdź funkcję `inputCell`:

```javascript
function inputCell(p, field, extraCls) {
  var val = p[field] === null || p[field] === undefined ? '' : p[field];
  var cls = 'chzt-inp' + (extraCls ? ' ' + extraCls : '');
  return '<td><input class="' + cls + '" type="text" inputmode="decimal" ' +
    'pattern="[0-9]*[.,]?[0-9]*" ' +
    'data-pid="' + p.id + '" data-field="' + field + '" ' +
    'value="' + val + '"></td>';
}
```

Zastąp:

```javascript
function inputCell(p, field, extraCls, disabled) {
  var val = p[field] === null || p[field] === undefined ? '' : p[field];
  var cls = 'chzt-inp' + (extraCls ? ' ' + extraCls : '');
  var disabledAttr = disabled ? ' disabled' : '';
  return '<td><input class="' + cls + '" type="text" inputmode="decimal" ' +
    'pattern="[0-9]*[.,]?[0-9]*" ' +
    'data-pid="' + p.id + '" data-field="' + field + '" ' +
    'value="' + val + '"' + disabledAttr + '></td>';
}
```

- [ ] **Step 3: Add CSS for ext section**

Dopisz do `mbr/chzt/static/chzt.css`:

```css
/* Sekcja analizy zewnętrznej — pod główną tabelą w detail view */
.chzt-ext-section {
  margin: 16px 28px 20px;
  padding: 18px 22px 22px;
  background: var(--surface);
  border: 1px solid var(--border-subtle);
  border-left: 3px solid var(--amber);
  border-radius: var(--radius, 10px);
  box-shadow: var(--shadow-sm);
}
.chzt-ext-title {
  font-size: 11px; font-weight: 700;
  color: var(--amber); letter-spacing: 0.4px;
  text-transform: uppercase;
  margin-bottom: 14px;
}
.chzt-ext-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  max-width: 680px;
}
.chzt-ext-field {
  display: flex; flex-direction: column; gap: 6px;
  position: relative;
}
.chzt-ext-field label {
  font-size: 11px; font-weight: 600;
  color: var(--text-sec);
  text-transform: uppercase; letter-spacing: 0.3px;
}
.chzt-ext-field .chzt-inp {
  width: 100%; max-width: 160px;
}
.chzt-ext-unit {
  position: absolute; right: 0; bottom: 10px;
  font-size: 11px; color: var(--text-dim);
  font-family: var(--mono);
}
.chzt-inp.readonly,
.chzt-inp:disabled {
  background: var(--surface-alt);
  color: var(--text-dim);
  cursor: not-allowed;
}
.chzt-inp.readonly:hover,
.chzt-inp:disabled:hover {
  background: var(--surface-alt);
}
```

- [ ] **Step 4: Bump cache-bust**

`?v=9` → `?v=10` w `chzt_historia.html` i `narzedzia.html`.

- [ ] **Step 5: Smoke test**

```bash
python -c "from mbr.app import create_app; create_app()"
node --check mbr/chzt/static/chzt.js
pytest tests/test_chzt.py -q
```

Manualny smoke (checklist):
- Zaloguj jako lab, wejdź w historię, klik w sesję → widać główną tabelę + sekcję "Analiza zewnętrzna — Szambiarka" z 3 polami szarymi (readonly)
- Zaloguj jako produkcja (lub admin), wejdź w tę samą sesję → pola ext edytowalne; wpisz wartość → on blur zapis → PUT się wykonuje, widać "zapisano HH:MM" w statusie

- [ ] **Step 6: Commit**

```bash
git add mbr/chzt/static/ mbr/chzt/templates/chzt_historia.html mbr/templates/technolog/narzedzia.html
git commit -m "feat(chzt): detail view ext section (szambiarka) with role-based readonly inputs"
```

---

## Task 9: UI — Narzędzia card gate + finalize etykieta

**Cel:** Rola `produkcja` widzi tylko kartę "Historia ChZT", nie widzi karty "ChZT Ścieków". Przycisk finalize zmienia etykietę na "Zakończ sesję".

**Files:**
- Modify: `mbr/templates/technolog/narzedzia.html`
- Modify: `mbr/chzt/templates/chzt_modal.html`

- [ ] **Step 1: Gate ChZT card for produkcja**

W `mbr/templates/technolog/narzedzia.html` znajdź karty ChZT:

```jinja
<div class="narz-section">
  <div class="narz-section-label">Ścieki</div>
  <div class="narz-grid">
    <div class="narz-card" onclick="openChztModal()" style="cursor:pointer;">
      ... (karta ChZT Ścieków — wprowadzanie)
    </div>
    <a href="{{ url_for('chzt.historia_page') }}" class="narz-card" ...>
      ... (karta Historia ChZT)
    </a>
  </div>
</div>
```

Zawiń kartę "ChZT Ścieków" w gate:

```jinja
{% if session.user.rola != 'produkcja' %}
<div class="narz-card" onclick="openChztModal()" style="cursor:pointer;">
  ... (istniejący markup)
</div>
{% endif %}
```

Kartę "Historia ChZT" zostaw bez gate — widoczna dla wszystkich.

- [ ] **Step 2: Update finalize button label**

W `mbr/chzt/templates/chzt_modal.html` znajdź:

```html
<button class="chzt-btn" id="chzt-save-btn" onclick="chztFinalize()">Zapisz (finalizuj)</button>
```

Zmień na:

```html
<button class="chzt-btn-primary" id="chzt-save-btn" onclick="chztFinalize()">Zakończ sesję</button>
```

(`chzt-btn` → `chzt-btn-primary` dla spójności z create-pane button.)

W JS też aktualizuj `chztFinalize` tam gdzie text jest ustawiany na "Zapisz (finalizuj)" — powinno być "Zakończ sesję":

```javascript
// W chztFinalize .then() success handler:
btn.textContent = 'Zakończ sesję';
// I w .catch():
btn.textContent = 'Zakończ sesję';
```

- [ ] **Step 3: Smoke test**

```bash
python -c "from mbr.app import create_app; create_app()"
pytest tests/test_chzt.py -q
```

Manualny smoke:
- Zaloguj jako produkcja, wejdź na `/technolog/narzedzia` → widzisz tylko "Historia ChZT", karty "ChZT Ścieków" nie ma
- Zaloguj jako lab → widzisz obie karty

- [ ] **Step 4: Bump cache-bust do `?v=11`**

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/technolog/narzedzia.html mbr/chzt/templates/chzt_modal.html mbr/chzt/static/chzt.js
git commit -m "feat(chzt): gate ChZT card for produkcja role + rename Finalizuj → Zakończ sesję"
```

---

## Task 10: E2E — crossing midnight scenario + final smoke

**Cel:** Integration test: nocna sesja startująca 22:00 day X, kończąca 06:00 day X+1 jest poprawnie obsługiwana przez UI/API.

**Files:**
- Modify: `tests/test_chzt.py`

- [ ] **Step 1: Failing test**

```python
def test_crossing_midnight_session_lifecycle(client, db):
    """Night shift: session starts 22:00 day X, finalizes 06:00 day X+1."""
    # Laborant rozpoczyna nocną sesję (backend sam ustawi dt_start=now)
    # Ręcznie nadpiszemy dt_start aby symulować start wieczorem:
    r1 = client.post("/api/chzt/session/new", json={"n_kontenery": 2})
    assert r1.status_code == 200
    sid = r1.get_json()["session"]["id"]

    db.execute(
        "UPDATE chzt_sesje SET dt_start=? WHERE id=?",
        ("2026-04-18T22:15:00", sid),
    )
    db.commit()

    # Fill all points (min required for finalize)
    r_refresh = client.get(f"/api/chzt/session/{sid}").get_json()["session"]
    for p in r_refresh["punkty"]:
        client.put(f"/api/chzt/pomiar/{p['id']}", json={
            "ph": 10, "p1": 15000, "p2": 16000
        })

    # Finalize (backend sets finalized_at=now; nadpiszemy symulując godzinę)
    r_fin = client.post(f"/api/chzt/session/{sid}/finalize")
    assert r_fin.status_code == 200
    db.execute(
        "UPDATE chzt_sesje SET finalized_at=? WHERE id=?",
        ("2026-04-19T06:05:00", sid),
    )
    db.commit()

    # /api/chzt/history → sesja widoczna, dt_start='2026-04-18T22:15:00'
    r_hist = client.get("/api/chzt/history").get_json()
    assert r_hist["sesje"][0]["id"] == sid
    assert r_hist["sesje"][0]["dt_start"].startswith("2026-04-18T22")
    assert r_hist["sesje"][0]["finalized_at"].startswith("2026-04-19T06")

    # /api/chzt/day/2026-04-18 znajduje (DATE(dt_start) = '2026-04-18')
    r_day = client.get("/api/chzt/day/2026-04-18")
    assert r_day.status_code == 200
    assert r_day.get_json()["dt_start"].startswith("2026-04-18T22")

    # /api/chzt/day/2026-04-19 NIE znajduje (sesja startowała 18, nie 19)
    r_day_next = client.get("/api/chzt/day/2026-04-19")
    assert r_day_next.status_code == 404

    # /api/chzt/session/active → None (sesja sfinalizowana)
    r_active = client.get("/api/chzt/session/active").get_json()
    assert r_active["session"] is None

    # Można utworzyć nową sesję po finalize
    r_new = client.post("/api/chzt/session/new", json={"n_kontenery": 3})
    assert r_new.status_code == 200
    assert r_new.get_json()["session"]["id"] != sid


def test_produkcja_fills_ext_after_lab_finalizes(produkcja_client, client, db):
    """Lab wypełnia pomiary + finalize. Produkcja wchodzi w historię i wypełnia ext pola."""
    # Lab tworzy i finalizuje
    r = client.post("/api/chzt/session/new", json={"n_kontenery": 0})
    sid = r.get_json()["session"]["id"]
    for p in r.get_json()["session"]["punkty"]:
        client.put(f"/api/chzt/pomiar/{p['id']}", json={"ph": 10, "p1": 100, "p2": 200})
    client.post(f"/api/chzt/session/{sid}/finalize")

    # Szambiarka
    szamb_pid = db.execute(
        "SELECT id FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa='szambiarka'", (sid,)
    ).fetchone()["id"]

    # Produkcja wypełnia ext_chzt/ext_ph/waga_kg na sfinalizowanej sesji
    resp = produkcja_client.put(f"/api/chzt/pomiar/{szamb_pid}", json={
        "ext_chzt": 13250, "ext_ph": 11, "waga_kg": 19060
    })
    assert resp.status_code == 200

    row = db.execute(
        "SELECT ext_chzt, ext_ph, waga_kg, ph FROM chzt_pomiary WHERE id=?", (szamb_pid,)
    ).fetchone()
    assert row["ext_chzt"] == 13250
    assert row["ext_ph"] == 11
    assert row["waga_kg"] == 19060
    assert row["ph"] == 10  # lab-wprowadzone, niezmienione przez produkcja

    # Audit zapisał obie zmiany (lab + produkcja)
    pomiar_events = db.execute(
        "SELECT event_type FROM audit_log WHERE event_type='chzt.pomiar.updated' AND entity_id=?",
        (szamb_pid,),
    ).fetchall()
    assert len(pomiar_events) >= 2
```

- [ ] **Step 2: Run — PASS**

Run: `pytest tests/test_chzt.py::test_crossing_midnight_session_lifecycle tests/test_chzt.py::test_produkcja_fills_ext_after_lab_finalizes -v`
Expected: 2 passed.

- [ ] **Step 3: Full suite**

Run: `pytest -q 2>&1 | tail -5`
Expected: all green.

- [ ] **Step 4: Smoke test + dev server manualnie**

```bash
python -c "from mbr.app import create_app; create_app()" && echo OK
node --check mbr/chzt/static/chzt.js && echo JS_OK
```

Manualna checklista (przed finalnym commitem):
- [ ] Zaloguj jako lab: brak aktywnej sesji → create-pane → rozpocznij → edit
- [ ] Wpisz pomiary → blur → "zapisano HH:MM"
- [ ] Zakończ sesję → banner "Ukończono"
- [ ] Ponowna próba /new z otwartą → zostaje w edit mode (nie 409 w UI bo nie ma otwartej)
- [ ] Wejdź w `/chzt/historia` → widzisz listę, kolumna "Rozpoczęto" z datetime
- [ ] Klik w wiersz → detail view z tabelą + sekcją ext (szara dla lab)
- [ ] Wyloguj, zaloguj jako produkcja (user musi być zseedowany w DB — patrz Step 5)
- [ ] `/technolog/narzedzia` → widzi tylko "Historia ChZT"
- [ ] Wejdź w tę samą sesję → sekcja ext edytowalna (teal focus), wpisz wartości → zapisują się
- [ ] Admin → obie sekcje edytowalne

- [ ] **Step 5: Seed testowego usera `produkcja`** (nie commitowane, tylko dla ręcznego smoke)

Jednorazowe polecenie do uruchomienia lokalnie przed manualnym smoke testem:

```bash
python <<'PY'
import bcrypt, sqlite3
db = sqlite3.connect("data/batch_db.sqlite")
db.execute(
    "INSERT OR IGNORE INTO mbr_users (login, password_hash, rola, imie_nazwisko) VALUES (?, ?, ?, ?)",
    ("produkcja1", bcrypt.hashpw(b"test123", bcrypt.gensalt()).decode(), "produkcja", "Jan Magazyn"),
)
db.commit()
db.close()
print("User 'produkcja1' / 'test123' seeded.")
PY
```

(Nie jest to produkcyjny seed; to tylko dla smoke testu — można usunąć po zatwierdzeniu.)

- [ ] **Step 6: Commit**

```bash
git add tests/test_chzt.py
git commit -m "test(chzt): crossing-midnight lifecycle + produkcja fills ext after lab finalizes"
```

---

## Finish

- [ ] **Final: Full suite + manualny smoke**

Run: `pytest -q`
Expected: all green.

Manualny end-to-end smoke (przed zgłoszeniem zakończenia):
- Lab flow: create → fill → finalize
- Produkcja flow: view history → open detail → edit ext fields → autosave works
- Admin: both flows work
- Crossing midnight scenario (ręcznie w DB): updated dt_start tak aby sesja przecięła północ, sprawdź że historia + /day endpoint działają

---

## Self-review — spec coverage check

| Spec section | Pokryte przez |
|---|---|
| Zmiana modelu DB: `dt_start` zamiast `data`, drop UNIQUE | Task 1 |
| Zmiana modelu DB: ext_chzt, ext_ph, waga_kg | Task 1 |
| Zmiana modelu DB: rola `produkcja` w CHECK | Task 1 |
| `get_active_session`, `create_session` | Task 2 |
| Rozszerzenie get_pomiar / update_pomiar / get_session_with_pomiary | Task 3 |
| `list_sessions_paginated` sort DESC po dt_start | Task 3 |
| Nowe endpointy `/active`, `/new`, `/<int:id>` | Task 4 |
| Usunięcie `/today`, `/<data_iso>` | Task 4 |
| ROLES_VIEW / ROLES_EDIT_INTERNAL / ROLES_EDIT_EXTERNAL | Task 4 |
| RBAC per-pole w PUT pomiar | Task 5 |
| `_allowed_fields_for_role` helper | Task 5 |
| Day endpoint DATE(dt_start) + ext fields | Task 6 |
| Modal create-pane stan | Task 7 |
| `loadActiveOrCreate` + `chztSubmitNew` | Task 7 |
| Historia kolumna "Rozpoczęto" | Task 7 |
| Detail view ext section dla szambiarki | Task 8 |
| Role-based readonly inputs | Task 8 |
| Narzędzia gate dla produkcja | Task 9 |
| "Zakończ sesję" rename | Task 9 |
| Crossing midnight E2E test | Task 10 |
| Produkcja fills ext after lab | Task 10 |

**Type consistency:**
- `get_active_session` / `create_session` — kwargs-only `created_by`/`n_kontenery` w Task 2; zgodne z użyciem w Task 4 endpoint.
- `POMIAR_FIELDS`, `POMIAR_FIELDS_INTERNAL`, `POMIAR_FIELDS_EXTERNAL` — zdefiniowane w Task 3, używane w Task 5 (`_allowed_fields_for_role`).
- `update_pomiar` — partial-update semantyka (Task 3), używane w Task 5 PUT.
- `_session.dt_start` — Task 7 renderDate + Task 7 chztShowDetail date formatting, spójne.
- `_chztUserRola` — wyłożone w template (Task 8), użyte w JS (`_canEditExt`, `_canEditInternal`).

**Placeholder scan:**
- Brak "TBD"/"TODO" w step'ach.
- Każdy step ma konkretny kod.
- Migracje idempotentne z konkretnymi warunkami wejścia.

Plan jest gotowy do wykonania.
