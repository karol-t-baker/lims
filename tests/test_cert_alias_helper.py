"""Unit tests for get_cert_aliases helper."""

import sqlite3
import pytest

from mbr.models import init_mbr_tables


def _seed(db):
    db.execute("INSERT INTO cert_alias VALUES ('Chegina_K40GLOL', 'Chegina_GLOL40')")
    db.execute("INSERT INTO cert_alias VALUES ('Chegina_K40GLOL', 'Chegina_K40GLN')")
    db.execute("INSERT INTO cert_alias VALUES ('Chegina_K7', 'Chegina_K7B')")
    db.commit()


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    _seed(conn)
    yield conn
    conn.close()


def test_get_cert_aliases_returns_targets_for_source(db):
    from mbr.certs.generator import get_cert_aliases
    targets = get_cert_aliases(db, "Chegina_K40GLOL")
    assert sorted(targets) == ["Chegina_GLOL40", "Chegina_K40GLN"]


def test_get_cert_aliases_empty_for_unknown_source(db):
    from mbr.certs.generator import get_cert_aliases
    assert get_cert_aliases(db, "Chegina_NONEXISTENT") == []


def test_get_cert_aliases_empty_when_no_rows(db):
    from mbr.certs.generator import get_cert_aliases
    db.execute("DELETE FROM cert_alias")
    db.commit()
    assert get_cert_aliases(db, "Chegina_K40GLOL") == []
