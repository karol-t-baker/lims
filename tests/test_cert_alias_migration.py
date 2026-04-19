"""Migration: cert_alias table + swiadectwa.target_produkt column added idempotently."""

import sqlite3
import pytest

from mbr.models import init_mbr_tables


def test_init_creates_cert_alias_table():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_mbr_tables(db)
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='cert_alias'"
    ).fetchone()
    assert row is not None, "cert_alias table must exist after init"

    # Column shape + PK
    cols = {r[1]: r for r in db.execute("PRAGMA table_info(cert_alias)").fetchall()}
    assert set(cols.keys()) == {"source_produkt", "target_produkt"}
    assert cols["source_produkt"][2].upper() == "TEXT"
    assert cols["target_produkt"][2].upper() == "TEXT"
    assert cols["source_produkt"][3] == 1, "source_produkt must be NOT NULL"
    assert cols["target_produkt"][3] == 1, "target_produkt must be NOT NULL"
    # Composite PK
    pk_cols = [r[1] for r in db.execute("PRAGMA table_info(cert_alias)").fetchall() if r[5] > 0]
    assert set(pk_cols) == {"source_produkt", "target_produkt"}


def test_init_adds_target_produkt_to_swiadectwa():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_mbr_tables(db)
    cols = {r[1]: r for r in db.execute("PRAGMA table_info(swiadectwa)").fetchall()}
    assert "target_produkt" in cols
    assert cols["target_produkt"][2].upper() == "TEXT"
    # Nullable (no NOT NULL constraint) so legacy rows stay valid
    assert cols["target_produkt"][3] == 0


def test_init_migrations_idempotent():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_mbr_tables(db)
    # Second call must not raise even though table/column already exist
    init_mbr_tables(db)
    # Still exactly one cert_alias table + one target_produkt column
    tbl_count = db.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='cert_alias'"
    ).fetchone()[0]
    assert tbl_count == 1
    col_names = [r[1] for r in db.execute("PRAGMA table_info(swiadectwa)").fetchall()]
    assert col_names.count("target_produkt") == 1


def test_cert_alias_primary_key_prevents_duplicates():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_mbr_tables(db)
    db.execute("INSERT INTO cert_alias (source_produkt, target_produkt) VALUES ('A', 'B')")
    db.commit()
    # Duplicate insert must raise IntegrityError
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO cert_alias (source_produkt, target_produkt) VALUES ('A', 'B')")
