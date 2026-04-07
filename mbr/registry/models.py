"""
registry/models.py — Model functions for completed batch registry, export, and product listing.
"""

import json
import sqlite3


def list_completed_registry(
    db: sqlite3.Connection, produkt: str | None = None, limit: int = 50, typ: str | None = None, offset: int = 0
) -> list[dict]:
    """Get completed batches with all wyniki for registry table view."""
    sql = """
        SELECT eb.ebr_id, eb.batch_id, eb.nr_partii, mt.produkt, eb.dt_end, eb.typ, eb.nr_zbiornika
        FROM ebr_batches eb
        JOIN mbr_templates mt ON mt.mbr_id = eb.mbr_id
        WHERE eb.status = 'completed'
    """
    params: list = []
    if produkt:
        sql += " AND mt.produkt = ?"
        params.append(produkt)
    if typ:
        sql += " AND eb.typ = ?"
        params.append(typ)
    sql += " ORDER BY eb.dt_end DESC LIMIT ? OFFSET ?"
    params.append(limit)
    params.append(offset)
    rows = db.execute(sql, params).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        wyniki = db.execute(
            "SELECT kod_parametru, tag, wartosc, w_limicie FROM ebr_wyniki WHERE ebr_id = ?",
            (d["ebr_id"],)
        ).fetchall()
        d["wyniki"] = {w["kod_parametru"]: dict(w) for w in wyniki}
        cert = db.execute(
            "SELECT COUNT(*) as cnt FROM swiadectwa WHERE ebr_id = ? AND nieaktualne = 0",
            (d["ebr_id"],)
        ).fetchone()
        d["cert_count"] = cert["cnt"] if cert else 0
        result.append(d)
    return result


def get_registry_columns(db: sqlite3.Connection, produkt: str) -> list:
    """Get column definitions (parameter names + limits) for a product's registry table."""
    mbr = db.execute(
        "SELECT parametry_lab FROM mbr_templates WHERE produkt = ? AND status = 'active'",
        (produkt,)
    ).fetchone()
    if not mbr:
        return []
    parametry = json.loads(mbr["parametry_lab"]) if isinstance(mbr["parametry_lab"], str) else mbr["parametry_lab"]
    # New cyclic schema uses "analiza", legacy uses "analiza_koncowa"
    sekcja = parametry.get("analiza") or parametry.get("analiza_koncowa", {})
    pola = sekcja.get("pola", sekcja) if isinstance(sekcja, dict) else sekcja
    if not isinstance(pola, list):
        return []
    return pola


def list_completed_products(db: sqlite3.Connection) -> list[str]:
    """Get list of all products that have at least one completed batch."""
    rows = db.execute("""
        SELECT DISTINCT mt.produkt
        FROM ebr_batches eb
        JOIN mbr_templates mt ON mt.mbr_id = eb.mbr_id
        WHERE eb.status = 'completed'
        ORDER BY mt.produkt
    """).fetchall()
    return [r["produkt"] for r in rows]


def export_wyniki_csv(
    db: sqlite3.Connection, produkt: str | None = None
) -> list[dict]:
    """Export all completed EBR wyniki for CSV download."""
    sql = """
        SELECT
            eb.batch_id,
            mt.produkt,
            eb.nr_partii,
            ew.sekcja,
            ew.kod_parametru,
            ew.tag,
            ew.wartosc,
            ew.min_limit,
            ew.max_limit,
            ew.w_limicie,
            ew.komentarz,
            ew.is_manual,
            ew.dt_wpisu,
            ew.wpisal
        FROM ebr_wyniki ew
        JOIN ebr_batches eb ON eb.ebr_id = ew.ebr_id
        JOIN mbr_templates mt ON mt.mbr_id = eb.mbr_id
        WHERE eb.status = 'completed'
    """
    params: list = []
    if produkt:
        sql += " AND mt.produkt = ?"
        params.append(produkt)
    sql += " ORDER BY eb.batch_id, ew.sekcja, ew.kod_parametru"
    rows = db.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
