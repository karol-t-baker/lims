import sqlite3

import bcrypt


def create_user(
    db: sqlite3.Connection,
    login: str,
    password: str,
    rola: str,
    imie_nazwisko: str | None = None,
) -> int:
    """Create a new user with bcrypt-hashed password. Returns user_id."""
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    cur = db.execute(
        "INSERT INTO mbr_users (login, password_hash, rola, imie_nazwisko) "
        "VALUES (?, ?, ?, ?)",
        (login, password_hash, rola, imie_nazwisko),
    )
    db.commit()
    return cur.lastrowid


def verify_user(db: sqlite3.Connection, login: str, password: str) -> dict | None:
    """Verify credentials. Returns user row as dict or None."""
    row = db.execute(
        "SELECT * FROM mbr_users WHERE login = ?", (login,)
    ).fetchone()
    if row is None:
        return None
    if not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        return None
    return dict(row)


def change_password(
    db: sqlite3.Connection, user_id: int, new_password: str
) -> dict:
    """Hash and update password for an existing user.

    The caller is responsible for db.commit() — this function stages the
    UPDATE but does not commit, so the caller can wrap it in a single
    transaction together with audit logging.

    Returns dict with user_id + login + rola (no password_hash).
    Raises ValueError if user not found or password is shorter than 6 chars.
    """
    if len(new_password) < 6:
        raise ValueError("Password must be at least 6 characters")

    row = db.execute(
        "SELECT user_id, login, rola FROM mbr_users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"User {user_id} not found")

    password_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    db.execute(
        "UPDATE mbr_users SET password_hash = ? WHERE user_id = ?",
        (password_hash, user_id),
    )

    return {"user_id": row["user_id"], "login": row["login"], "rola": row["rola"]}
