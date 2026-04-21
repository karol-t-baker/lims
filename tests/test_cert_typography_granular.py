"""Granular cert typography: migration + _load_cert_settings + overrides."""

import sqlite3
from io import BytesIO
from zipfile import ZipFile

import pytest

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _get_setting(db, key):
    row = db.execute("SELECT value FROM cert_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def test_migration_seeds_three_new_keys_on_fresh_db(db):
    assert _get_setting(db, "title_font_size_pt") == "12"
    assert _get_setting(db, "product_name_font_size_pt") == "16"
    assert _get_setting(db, "body_font_size_pt") == "11"


def test_migration_copies_legacy_header_font_size_pt_into_title_and_product():
    """Existing prod DB with only header_font_size_pt=12 (and no title/product
    keys) must end up with title=12 and product=12 after migration — no
    visual regression for users who had the old setting in place."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # Simulate "legacy DB" — seed cert_settings with only the old key first.
    conn.execute("""
        CREATE TABLE cert_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)
    """)
    conn.execute("INSERT INTO cert_settings (key, value) VALUES ('header_font_size_pt', '12')")
    conn.commit()
    # Now run init_mbr_tables — migration should pick up the existing value.
    init_mbr_tables(conn)
    rows = dict(conn.execute("SELECT key, value FROM cert_settings").fetchall())
    assert rows["title_font_size_pt"] == "12"
    assert rows["product_name_font_size_pt"] == "12"
    assert rows["body_font_size_pt"] == "11"
    conn.close()


def test_migration_is_idempotent():
    """Running init_mbr_tables twice leaves cert_settings unchanged."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    # Tweak a value between runs — migration must NOT clobber it.
    conn.execute(
        "UPDATE cert_settings SET value=? WHERE key=?", ("22", "title_font_size_pt")
    )
    conn.commit()
    init_mbr_tables(conn)
    row = conn.execute(
        "SELECT value FROM cert_settings WHERE key='title_font_size_pt'"
    ).fetchone()
    assert row["value"] == "22"
    conn.close()
