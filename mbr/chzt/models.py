"""ChZT SQLite schema + helpers.

`init_chzt_tables()` commits its DDL. SQL helpers defined later do NOT commit —
callers own the transaction.
"""


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
