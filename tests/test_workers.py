"""
test_workers.py — Tests for mbr/workers/models.py worker CRUD.
"""

import sqlite3
import pytest

from mbr.workers.models import list_workers, update_worker_profile, update_worker_nickname


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS workers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            imie        TEXT NOT NULL,
            nazwisko    TEXT NOT NULL,
            inicjaly    TEXT NOT NULL,
            nickname    TEXT DEFAULT '',
            avatar_icon INTEGER DEFAULT 0,
            avatar_color INTEGER DEFAULT 0,
            aktywny     INTEGER NOT NULL DEFAULT 1
        );
    """)
    conn.commit()
    # Insert test workers
    conn.executemany(
        "INSERT INTO workers (imie, nazwisko, inicjaly, nickname, aktywny) VALUES (?, ?, ?, ?, ?)",
        [
            ("Jan", "Kowalski", "JK", "janek", 1),
            ("Anna", "Nowak", "AN", "anka", 1),
            ("Piotr", "Wiśniewski", "PW", "", 0),
        ],
    )
    conn.commit()
    yield conn
    conn.close()


def test_list_workers_returns_active_by_default(db):
    """list_workers() returns only active workers by default."""
    result = list_workers(db)
    assert len(result) == 2
    for w in result:
        assert w["aktywny"] == 1


def test_list_workers_returns_list_of_dicts(db):
    """list_workers() returns a list of dicts."""
    result = list_workers(db)
    assert isinstance(result, list)
    for item in result:
        assert isinstance(item, dict)


def test_list_workers_contains_expected_fields(db):
    """list_workers() dicts contain expected worker fields."""
    result = list_workers(db)
    assert len(result) > 0
    w = result[0]
    for field in ("id", "imie", "nazwisko", "inicjaly", "nickname", "aktywny"):
        assert field in w


def test_list_workers_ordered_by_nazwisko_imie(db):
    """list_workers() returns workers ordered by nazwisko then imie."""
    result = list_workers(db)
    # Active workers: Kowalski Jan, Nowak Anna → Kowalski comes before Nowak
    assert result[0]["nazwisko"] == "Kowalski"
    assert result[1]["nazwisko"] == "Nowak"


def test_list_workers_aktywny_false_returns_all(db):
    """list_workers(aktywny=False) returns all workers including inactive."""
    result = list_workers(db, aktywny=False)
    assert len(result) == 3


def test_list_workers_aktywny_false_includes_inactive(db):
    """list_workers(aktywny=False) includes workers with aktywny=0."""
    result = list_workers(db, aktywny=False)
    inactive = [w for w in result if w["aktywny"] == 0]
    assert len(inactive) == 1
    assert inactive[0]["nazwisko"] == "Wiśniewski"


def test_update_worker_profile_nickname(db):
    """update_worker_profile() updates the nickname field."""
    worker_id = db.execute("SELECT id FROM workers WHERE inicjaly = 'JK'").fetchone()["id"]
    update_worker_profile(db, worker_id, nickname="janek_nowy")
    row = db.execute("SELECT nickname FROM workers WHERE id = ?", (worker_id,)).fetchone()
    assert row["nickname"] == "janek_nowy"


def test_update_worker_profile_avatar_icon(db):
    """update_worker_profile() updates the avatar_icon field."""
    worker_id = db.execute("SELECT id FROM workers WHERE inicjaly = 'AN'").fetchone()["id"]
    update_worker_profile(db, worker_id, avatar_icon=5)
    row = db.execute("SELECT avatar_icon FROM workers WHERE id = ?", (worker_id,)).fetchone()
    assert row["avatar_icon"] == 5


def test_update_worker_profile_avatar_color(db):
    """update_worker_profile() updates the avatar_color field."""
    worker_id = db.execute("SELECT id FROM workers WHERE inicjaly = 'JK'").fetchone()["id"]
    update_worker_profile(db, worker_id, avatar_color=3)
    row = db.execute("SELECT avatar_color FROM workers WHERE id = ?", (worker_id,)).fetchone()
    assert row["avatar_color"] == 3


def test_update_worker_profile_multiple_fields(db):
    """update_worker_profile() can update multiple fields at once."""
    worker_id = db.execute("SELECT id FROM workers WHERE inicjaly = 'AN'").fetchone()["id"]
    update_worker_profile(db, worker_id, nickname="anna_new", avatar_icon=2, avatar_color=7)
    row = db.execute("SELECT nickname, avatar_icon, avatar_color FROM workers WHERE id = ?", (worker_id,)).fetchone()
    assert row["nickname"] == "anna_new"
    assert row["avatar_icon"] == 2
    assert row["avatar_color"] == 7


def test_update_worker_profile_no_args_is_noop(db):
    """update_worker_profile() with no optional args does not raise and does not change anything."""
    worker_id = db.execute("SELECT id FROM workers WHERE inicjaly = 'JK'").fetchone()["id"]
    before = dict(db.execute("SELECT * FROM workers WHERE id = ?", (worker_id,)).fetchone())
    update_worker_profile(db, worker_id)  # no changes
    after = dict(db.execute("SELECT * FROM workers WHERE id = ?", (worker_id,)).fetchone())
    assert before == after


def test_update_worker_nickname_alias(db):
    """update_worker_nickname() is a backwards-compat alias for update_worker_profile."""
    worker_id = db.execute("SELECT id FROM workers WHERE inicjaly = 'PW'").fetchone()["id"]
    update_worker_nickname(db, worker_id, "piotrek")
    row = db.execute("SELECT nickname FROM workers WHERE id = ?", (worker_id,)).fetchone()
    assert row["nickname"] == "piotrek"
