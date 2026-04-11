"""
test_auth.py — Tests for mbr/auth/models.py user CRUD.
"""

import sqlite3
import pytest

from mbr.auth.models import create_user, verify_user


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS mbr_users (
            user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            login           TEXT UNIQUE NOT NULL,
            password_hash   TEXT NOT NULL,
            rola            TEXT NOT NULL CHECK(rola IN ('technolog', 'laborant')),
            imie_nazwisko   TEXT
        );
    """)
    conn.commit()
    yield conn
    conn.close()


def test_create_user_returns_user_id(db):
    """create_user() returns an integer user_id."""
    user_id = create_user(db, login="jan", password="secret", rola="technolog")
    assert isinstance(user_id, int)
    assert user_id > 0


def test_create_user_stores_bcrypt_hash(db):
    """create_user() stores a bcrypt hash, not the plain password."""
    create_user(db, login="jan", password="secret", rola="technolog")
    row = db.execute("SELECT password_hash FROM mbr_users WHERE login = ?", ("jan",)).fetchone()
    assert row is not None
    # bcrypt hashes start with $2b$ or $2a$
    assert row["password_hash"].startswith("$2")
    assert "secret" not in row["password_hash"]


def test_create_user_with_imie_nazwisko(db):
    """create_user() stores imie_nazwisko when provided."""
    user_id = create_user(db, login="anna", password="pass", rola="laborant", imie_nazwisko="Anna Kowalska")
    row = db.execute("SELECT imie_nazwisko FROM mbr_users WHERE user_id = ?", (user_id,)).fetchone()
    assert row["imie_nazwisko"] == "Anna Kowalska"


def test_create_user_without_imie_nazwisko(db):
    """create_user() sets imie_nazwisko to None when not provided."""
    user_id = create_user(db, login="piotr", password="pass", rola="technolog")
    row = db.execute("SELECT imie_nazwisko FROM mbr_users WHERE user_id = ?", (user_id,)).fetchone()
    assert row["imie_nazwisko"] is None


def test_verify_user_correct_password_returns_dict(db):
    """verify_user() returns a dict when credentials are correct."""
    create_user(db, login="jan", password="secret", rola="technolog")
    result = verify_user(db, login="jan", password="secret")
    assert result is not None
    assert isinstance(result, dict)


def test_verify_user_correct_password_contains_user_fields(db):
    """verify_user() dict contains expected user fields."""
    create_user(db, login="jan", password="secret", rola="technolog", imie_nazwisko="Jan Nowak")
    result = verify_user(db, login="jan", password="secret")
    assert result["login"] == "jan"
    assert result["rola"] == "technolog"
    assert result["imie_nazwisko"] == "Jan Nowak"


def test_verify_user_wrong_password_returns_none(db):
    """verify_user() returns None when password is incorrect."""
    create_user(db, login="jan", password="secret", rola="technolog")
    result = verify_user(db, login="jan", password="wrongpassword")
    assert result is None


def test_verify_user_nonexistent_login_returns_none(db):
    """verify_user() returns None when login does not exist."""
    result = verify_user(db, login="nobody", password="anything")
    assert result is None


def test_verify_user_empty_password_returns_none(db):
    """verify_user() returns None for empty password against a real user."""
    create_user(db, login="jan", password="secret", rola="technolog")
    result = verify_user(db, login="jan", password="")
    assert result is None


def test_create_multiple_users_unique_ids(db):
    """create_user() assigns distinct user_ids to different users."""
    id1 = create_user(db, login="user1", password="pass1", rola="technolog")
    id2 = create_user(db, login="user2", password="pass2", rola="laborant")
    assert id1 != id2


def test_change_password_updates_hash(db):
    """change_password() updates the hash so verify_user works with the new password."""
    from mbr.auth.models import change_password
    user_id = create_user(db, login="kowalski", password="oldpass1", rola="laborant")
    result = change_password(db, user_id, "newpass2")
    assert result["user_id"] == user_id
    assert result["login"] == "kowalski"
    assert verify_user(db, "kowalski", "newpass2") is not None
    assert verify_user(db, "kowalski", "oldpass1") is None


def test_change_password_rejects_short(db):
    """Password shorter than 6 chars raises ValueError."""
    from mbr.auth.models import change_password
    user_id = create_user(db, login="kowalski", password="oldpass1", rola="laborant")
    import pytest as _pytest
    with _pytest.raises(ValueError, match="6"):
        change_password(db, user_id, "short")


def test_change_password_unknown_user_raises(db):
    """Non-existent user_id raises ValueError."""
    from mbr.auth.models import change_password
    import pytest as _pytest
    with _pytest.raises(ValueError, match="not found"):
        change_password(db, 9999, "validpass")
