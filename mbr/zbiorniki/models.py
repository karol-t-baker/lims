"""zbiorniki/models.py — CRUD for tanks and batch-tank links."""

import sqlite3
from datetime import datetime

from mbr.shared.timezone import app_now_iso


def list_zbiorniki(db: sqlite3.Connection, include_inactive: bool = False) -> list[dict]:
    sql = "SELECT * FROM zbiorniki"
    if not include_inactive:
        sql += " WHERE aktywny = 1"
    sql += " ORDER BY CAST(SUBSTR(nr_zbiornika, 2) AS INTEGER)"
    return [dict(r) for r in db.execute(sql).fetchall()]


def create_zbiornik(db: sqlite3.Connection, nr_zbiornika: str, max_pojemnosc: float, produkt: str) -> int:
    cur = db.execute(
        "INSERT INTO zbiorniki (nr_zbiornika, max_pojemnosc, produkt) VALUES (?, ?, ?)",
        (nr_zbiornika, max_pojemnosc, produkt),
    )
    db.commit()
    return cur.lastrowid


def update_zbiornik(db: sqlite3.Connection, zbiornik_id: int, **fields) -> None:
    allowed = {"max_pojemnosc", "produkt", "aktywny", "nr_zbiornika", "kod_produktu"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    db.execute(f"UPDATE zbiorniki SET {set_clause} WHERE id = ?", [*updates.values(), zbiornik_id])
    db.commit()


def link_szarza(db: sqlite3.Connection, ebr_id: int, zbiornik_id: int, masa_kg: float | None = None) -> int:
    now = app_now_iso()
    cur = db.execute(
        "INSERT OR REPLACE INTO zbiornik_szarze (ebr_id, zbiornik_id, masa_kg, dt_dodania) VALUES (?, ?, ?, ?)",
        (ebr_id, zbiornik_id, masa_kg, now),
    )
    db.commit()
    return cur.lastrowid


def unlink_szarza(db: sqlite3.Connection, link_id: int) -> None:
    db.execute("DELETE FROM zbiornik_szarze WHERE id = ?", (link_id,))
    db.commit()


def get_links_for_ebr(db: sqlite3.Connection, ebr_id: int) -> list[dict]:
    rows = db.execute("""
        SELECT zs.id, zs.ebr_id, zs.zbiornik_id, zs.masa_kg, zs.dt_dodania,
               z.nr_zbiornika, z.max_pojemnosc, z.produkt
        FROM zbiornik_szarze zs
        JOIN zbiorniki z ON z.id = zs.zbiornik_id
        WHERE zs.ebr_id = ?
        ORDER BY z.nr_zbiornika
    """, (ebr_id,)).fetchall()
    return [dict(r) for r in rows]


def get_zbiorniki_for_batch_ids(db: sqlite3.Connection, ebr_ids: list[int]) -> dict[int, list[str]]:
    """Return {ebr_id: [nr_zbiornika, ...]} for a list of batch IDs."""
    if not ebr_ids:
        return {}
    placeholders = ",".join("?" * len(ebr_ids))
    rows = db.execute(f"""
        SELECT zs.ebr_id, z.nr_zbiornika
        FROM zbiornik_szarze zs
        JOIN zbiorniki z ON z.id = zs.zbiornik_id
        WHERE zs.ebr_id IN ({placeholders})
        ORDER BY z.nr_zbiornika
    """, ebr_ids).fetchall()
    result: dict[int, list[str]] = {}
    for r in rows:
        result.setdefault(r["ebr_id"], []).append(r["nr_zbiornika"])
    return result
