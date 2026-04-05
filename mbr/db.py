"""
db.py — Database connection helpers for MBR/EBR webapp.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "batch_db.sqlite"


def get_db() -> sqlite3.Connection:
    """Return sqlite3 connection with Row factory and foreign_keys=ON."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


@contextmanager
def db_session():
    db = get_db()
    try:
        yield db
    finally:
        db.close()
