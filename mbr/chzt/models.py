"""ChZT SQLite schema + helpers.

`init_chzt_tables()` commits its DDL. SQL helpers defined later do NOT commit —
callers own the transaction.
"""

from datetime import datetime


def init_chzt_tables(db):
    """Create/migrate chzt_sesje + chzt_pomiary. Idempotent.

    Nowy schemat (v2):
      chzt_sesje.dt_start (TEXT, zastępuje UNIQUE(data))
      chzt_pomiary + ext_chzt, ext_ph, waga_kg (nullable)

    Migracja ze starego:
      - Jeśli chzt_sesje ma kolumnę `data` → rebuild bez UNIQUE
      - Jeśli chzt_pomiary nie ma ext_chzt → ALTER TABLE ADD COLUMN × 3
    """
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
            # Disable FK at connection level — otherwise DROP TABLE would
            # CASCADE-delete chzt_pomiary rows that still point to old id space.
            db.execute("PRAGMA foreign_keys=OFF")
            try:
                db.execute("BEGIN")
                db.execute("""
                    CREATE TABLE chzt_sesje_v2 (
                        id           INTEGER PRIMARY KEY AUTOINCREMENT,
                        dt_start     TEXT NOT NULL,
                        n_kontenery  INTEGER NOT NULL DEFAULT 8,
                        created_at   TEXT NOT NULL,
                        created_by   INTEGER REFERENCES workers(id),
                        finalized_at TEXT,
                        finalized_by INTEGER REFERENCES workers(id)
                    )
                """)
                db.execute("""
                    INSERT INTO chzt_sesje_v2 (id, dt_start, n_kontenery, created_at, created_by, finalized_at, finalized_by)
                    SELECT id,
                           CASE WHEN length(data) = 10 THEN data || 'T00:00:00' ELSE data END AS dt_start,
                           n_kontenery, created_at, created_by, finalized_at, finalized_by
                    FROM chzt_sesje
                """)
                db.execute("DROP TABLE chzt_sesje")
                db.execute("ALTER TABLE chzt_sesje_v2 RENAME TO chzt_sesje")
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                db.execute("PRAGMA foreign_keys=ON")
                raise
            db.execute("PRAGMA foreign_keys=ON")

    db.execute("DROP INDEX IF EXISTS idx_chzt_sesje_data")
    db.execute("CREATE INDEX IF NOT EXISTS idx_chzt_sesje_dt_start ON chzt_sesje(dt_start DESC)")

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


def build_punkty_names(n_kontenery: int) -> list:
    """Return punkt_nazwa list in canonical order: hala, rura, kontener 1..N, szambiarka."""
    names = ["hala", "rura"]
    for i in range(1, n_kontenery + 1):
        names.append(f"kontener {i}")
    names.append("szambiarka")
    return names


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


def compute_srednia(row: dict):
    """Return average of non-null p1..p5 if ≥2 non-null, else None."""
    vals = [row.get(k) for k in ("p1", "p2", "p3", "p4", "p5")]
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return None
    return sum(vals) / len(vals)


POMIAR_FIELDS_INTERNAL = ("ph", "p1", "p2", "p3", "p4", "p5")
POMIAR_FIELDS_EXTERNAL = ("ext_chzt", "ext_ph", "waga_kg")
POMIAR_FIELDS = POMIAR_FIELDS_INTERNAL + POMIAR_FIELDS_EXTERNAL


def get_pomiar(db, pomiar_id: int) -> dict:
    row = db.execute(
        "SELECT id, sesja_id, punkt_nazwa, kolejnosc, ph, p1, p2, p3, p4, p5, "
        "       srednia, ext_chzt, ext_ph, waga_kg, updated_at, updated_by "
        "FROM chzt_pomiary WHERE id=?",
        (pomiar_id,),
    ).fetchone()
    return dict(row) if row else None


def update_pomiar(db, pomiar_id: int, new_values: dict, *, updated_by: int):
    """Update the subset of fields present in new_values. Recompute srednia
    from resulting p1..p5 state. Caller owns the transaction.

    Returns the updated row dict. Raises ValueError if pomiar_id not found.
    """
    existing = get_pomiar(db, pomiar_id)
    if existing is None:
        raise ValueError(f"pomiar {pomiar_id} not found")

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


def resize_kontenery(db, session_id: int, *, new_n: int):
    """Change n_kontenery — add missing kontener rows or delete trailing empty ones.

    Raises ValueError listing rejected punkt_nazwa values if shrinking would
    delete rows with any non-null data (ph, p1..p5).
    """
    srow = db.execute("SELECT n_kontenery FROM chzt_sesje WHERE id=?", (session_id,)).fetchone()
    if srow is None:
        raise ValueError(f"session {session_id} not found")
    old_n = srow["n_kontenery"]

    if new_n == old_n:
        return

    now = datetime.now().isoformat(timespec="seconds")

    if new_n > old_n:
        # Add kontener (old_n+1)..new_n. Shift szambiarka kolejnosc.
        db.execute(
            "UPDATE chzt_pomiary SET kolejnosc=? WHERE sesja_id=? AND punkt_nazwa='szambiarka'",
            (new_n + 3, session_id),
        )
        for i in range(old_n + 1, new_n + 1):
            db.execute(
                "INSERT INTO chzt_pomiary (sesja_id, punkt_nazwa, kolejnosc, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (session_id, f"kontener {i}", i + 2, now),
            )
    else:
        # Shrink — check kontener (new_n+1)..old_n have no data
        to_delete = [f"kontener {i}" for i in range(new_n + 1, old_n + 1)]
        placeholders = ",".join("?" * len(to_delete))
        rows_with_data = db.execute(
            f"SELECT punkt_nazwa FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa IN ({placeholders}) "
            f"AND (ph IS NOT NULL OR p1 IS NOT NULL OR p2 IS NOT NULL OR p3 IS NOT NULL "
            f"     OR p4 IS NOT NULL OR p5 IS NOT NULL)",
            (session_id, *to_delete),
        ).fetchall()
        if rows_with_data:
            names = [r["punkt_nazwa"] for r in rows_with_data]
            raise ValueError(f"Kontenery z danymi: {', '.join(names)}")

        db.execute(
            f"DELETE FROM chzt_pomiary WHERE sesja_id=? AND punkt_nazwa IN ({placeholders})",
            (session_id, *to_delete),
        )
        db.execute(
            "UPDATE chzt_pomiary SET kolejnosc=? WHERE sesja_id=? AND punkt_nazwa='szambiarka'",
            (new_n + 3, session_id),
        )

    db.execute(
        "UPDATE chzt_sesje SET n_kontenery=? WHERE id=?",
        (new_n, session_id),
    )


def validate_for_finalize(db, session_id: int) -> list:
    """Return list of errors [{punkt_nazwa, reason}]; empty list = OK."""
    rows = db.execute(
        "SELECT punkt_nazwa, ph, p1, p2, p3, p4, p5 "
        "FROM chzt_pomiary WHERE sesja_id=? ORDER BY kolejnosc",
        (session_id,),
    ).fetchall()
    errors = []
    for r in rows:
        if r["ph"] is None:
            errors.append({"punkt_nazwa": r["punkt_nazwa"], "reason": "brak ph"})
            continue
        nonnull = sum(1 for k in ("p1", "p2", "p3", "p4", "p5") if r[k] is not None)
        if nonnull < 2:
            errors.append({"punkt_nazwa": r["punkt_nazwa"], "reason": "min. 2 pomiary"})
    return errors


def finalize_session(db, session_id: int, *, finalized_by: int):
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "UPDATE chzt_sesje SET finalized_at=?, finalized_by=? WHERE id=?",
        (now, finalized_by, session_id),
    )


def unfinalize_session(db, session_id: int):
    db.execute(
        "UPDATE chzt_sesje SET finalized_at=NULL, finalized_by=NULL WHERE id=?",
        (session_id,),
    )


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


def get_session_with_pomiary(db, session_id: int) -> dict:
    """Return {session fields..., punkty: [pomiar rows ordered by kolejnosc]}.

    Returns None if session not found.
    """
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
