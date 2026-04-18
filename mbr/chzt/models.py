"""ChZT SQLite schema + helpers.

`init_chzt_tables()` commits its DDL. SQL helpers defined later do NOT commit —
callers own the transaction.
"""

from datetime import datetime


def init_chzt_tables(db):
    """Create chzt_sesje + chzt_pomiary tables. Idempotent."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS chzt_sesje (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            data         TEXT NOT NULL UNIQUE,
            n_kontenery  INTEGER NOT NULL DEFAULT 8,
            created_at   TEXT NOT NULL,
            created_by   INTEGER REFERENCES workers(id),
            finalized_at TEXT,
            finalized_by INTEGER REFERENCES workers(id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS chzt_pomiary (
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
            updated_at   TEXT NOT NULL,
            updated_by   INTEGER REFERENCES workers(id),
            UNIQUE(sesja_id, punkt_nazwa)
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_chzt_sesje_data ON chzt_sesje(data DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_chzt_pomiary_sesja ON chzt_pomiary(sesja_id)")
    db.commit()


def build_punkty_names(n_kontenery: int) -> list:
    """Return punkt_nazwa list in canonical order: hala, rura, kontener 1..N, szambiarka."""
    names = ["hala", "rura"]
    for i in range(1, n_kontenery + 1):
        names.append(f"kontener {i}")
    names.append("szambiarka")
    return names


def get_or_create_session(db, data_iso: str, *, created_by: int, n_kontenery: int = 8):
    """Return (session_id, created_bool).

    If session for `data_iso` exists, returns its id and created=False.
    Otherwise inserts a new session with n_kontenery and seeds pomiary rows
    in canonical order. `data_iso` format: YYYY-MM-DD.
    """
    row = db.execute("SELECT id FROM chzt_sesje WHERE data=?", (data_iso,)).fetchone()
    if row:
        return row["id"], False

    now = datetime.now().isoformat(timespec="seconds")
    cur = db.execute(
        "INSERT INTO chzt_sesje (data, n_kontenery, created_at, created_by) "
        "VALUES (?, ?, ?, ?)",
        (data_iso, n_kontenery, now, created_by),
    )
    session_id = cur.lastrowid

    names = build_punkty_names(n_kontenery)
    for idx, name in enumerate(names, start=1):
        db.execute(
            "INSERT INTO chzt_pomiary (sesja_id, punkt_nazwa, kolejnosc, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (session_id, name, idx, now),
        )

    return session_id, True


def compute_srednia(row: dict):
    """Return average of non-null p1..p5 if ≥2 non-null, else None."""
    vals = [row.get(k) for k in ("p1", "p2", "p3", "p4", "p5")]
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return None
    return sum(vals) / len(vals)


POMIAR_FIELDS = ("ph", "p1", "p2", "p3", "p4", "p5")


def get_pomiar(db, pomiar_id: int) -> dict:
    row = db.execute(
        "SELECT id, sesja_id, punkt_nazwa, kolejnosc, ph, p1, p2, p3, p4, p5, "
        "       srednia, updated_at, updated_by "
        "FROM chzt_pomiary WHERE id=?",
        (pomiar_id,),
    ).fetchone()
    return dict(row) if row else None


def update_pomiar(db, pomiar_id: int, new_values: dict, *, updated_by: int):
    """Write new_values to the given pomiar + recompute srednia + timestamp.

    Caller owns the transaction (no commit here). Returns the updated row dict.
    """
    srednia = compute_srednia(new_values)
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "UPDATE chzt_pomiary "
        "SET ph=?, p1=?, p2=?, p3=?, p4=?, p5=?, srednia=?, updated_at=?, updated_by=? "
        "WHERE id=?",
        (
            new_values.get("ph"),
            new_values.get("p1"),
            new_values.get("p2"),
            new_values.get("p3"),
            new_values.get("p4"),
            new_values.get("p5"),
            srednia,
            now,
            updated_by,
            pomiar_id,
        ),
    )
    return get_pomiar(db, pomiar_id)


def get_session_with_pomiary(db, session_id: int) -> dict:
    """Return {session fields..., punkty: [pomiar rows ordered by kolejnosc]}.

    Returns None if session not found.
    """
    srow = db.execute(
        "SELECT id, data, n_kontenery, created_at, created_by, "
        "       finalized_at, finalized_by FROM chzt_sesje WHERE id=?",
        (session_id,),
    ).fetchone()
    if srow is None:
        return None
    prows = db.execute(
        "SELECT id, punkt_nazwa, kolejnosc, ph, p1, p2, p3, p4, p5, srednia, "
        "       updated_at, updated_by "
        "FROM chzt_pomiary WHERE sesja_id=? ORDER BY kolejnosc",
        (session_id,),
    ).fetchall()
    return {
        **dict(srow),
        "punkty": [dict(p) for p in prows],
    }
