def list_workers(db, aktywny=True):
    """List workers, optionally filtered by active status."""
    sql = "SELECT * FROM workers"
    if aktywny:
        sql += " WHERE aktywny = 1"
    sql += " ORDER BY nazwisko, imie"
    return [dict(r) for r in db.execute(sql).fetchall()]


def update_worker_profile(db, worker_id, nickname=None, avatar_icon=None, avatar_color=None):
    sets = []
    vals = []
    if nickname is not None:
        sets.append("nickname = ?")
        vals.append(nickname)
    if avatar_icon is not None:
        sets.append("avatar_icon = ?")
        vals.append(avatar_icon)
    if avatar_color is not None:
        sets.append("avatar_color = ?")
        vals.append(avatar_color)
    if not sets:
        return
    vals.append(worker_id)
    db.execute(f"UPDATE workers SET {', '.join(sets)} WHERE id = ?", vals)
    db.commit()


def add_worker(db, imie, nazwisko, inicjaly, nickname=''):
    cur = db.execute(
        "INSERT INTO workers (imie, nazwisko, inicjaly, nickname, aktywny) VALUES (?, ?, ?, ?, 1)",
        (imie, nazwisko, inicjaly, nickname),
    )
    db.commit()
    return cur.lastrowid


def toggle_worker_active(db, worker_id):
    row = db.execute("SELECT aktywny FROM workers WHERE id=?", (worker_id,)).fetchone()
    if not row:
        return None
    new_val = 0 if row["aktywny"] else 1
    db.execute("UPDATE workers SET aktywny=? WHERE id=?", (new_val, worker_id))
    db.commit()
    return new_val


def delete_worker(db, worker_id):
    db.execute("DELETE FROM workers WHERE id=?", (worker_id,))
    db.commit()


# Backwards compat alias
def update_worker_nickname(db, worker_id, nickname):
    update_worker_profile(db, worker_id, nickname=nickname)
