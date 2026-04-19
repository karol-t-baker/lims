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
        SELECT eb.ebr_id, eb.batch_id, eb.nr_partii, mt.produkt, eb.dt_end, eb.typ, eb.nr_zbiornika, eb.uwagi_koncowe, eb.pakowanie_bezposrednie
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
            "SELECT kod_parametru, sekcja, tag, wartosc, w_limicie FROM ebr_wyniki WHERE ebr_id = ? ORDER BY sekcja",
            (d["ebr_id"],)
        ).fetchall()
        # For pipeline products: prefer 'analiza' (standaryzacja) results over earlier stages
        # Dict comprehension: later sekcje override earlier for same kod
        # ORDER BY sekcja puts 'analiza' first alphabetically, so re-sort to put it last
        sorted_wyniki = sorted(wyniki, key=lambda w: (0 if w["sekcja"] not in ("analiza", "analiza_koncowa") else 1, w["sekcja"] or ""))
        d["wyniki"] = {w["kod_parametru"]: dict(w) for w in sorted_wyniki}
        cert = db.execute(
            "SELECT COUNT(*) as cnt FROM swiadectwa WHERE ebr_id = ? AND nieaktualne = 0",
            (d["ebr_id"],)
        ).fetchone()
        d["cert_count"] = cert["cnt"] if cert else 0
        result.append(d)

    # Attach zbiorniki links
    if result:
        from mbr.zbiorniki.models import get_zbiorniki_for_batch_ids
        ebr_ids = [r["ebr_id"] for r in result]
        zb_map = get_zbiorniki_for_batch_ids(db, ebr_ids)
        for r in result:
            r["zbiorniki"] = zb_map.get(r["ebr_id"], [])

    # Attach surowce (raw-material batch numbers) per batch — from platkowanie_substraty.
    # Each row = one (substrat, nr_partii) entry; same substrat can appear multiple
    # times (different partii). Frontend renders one line per row.
    if result:
        placeholders = ",".join("?" * len(ebr_ids))
        sur_rows = db.execute(
            f"SELECT ps.ebr_id, s.nazwa, s.skrot, ps.nr_partii_substratu AS nr_partii "
            f"FROM platkowanie_substraty ps JOIN substraty s ON s.id = ps.substrat_id "
            f"WHERE ps.ebr_id IN ({placeholders}) "
            f"ORDER BY s.nazwa, ps.id",
            ebr_ids,
        ).fetchall()
        sur_map: dict = {}
        for sr in sur_rows:
            sur_map.setdefault(sr["ebr_id"], []).append({
                "nazwa": sr["nazwa"],
                "skrot": sr["skrot"],
                "nr_partii": sr["nr_partii"],
            })
        for r in result:
            r["surowce"] = sur_map.get(r["ebr_id"], [])

    # Attach "who approved" from audit_log
    if result:
        placeholders = ",".join("?" * len(ebr_ids))
        approval_rows = db.execute(f"""
            SELECT al.entity_id,
                   GROUP_CONCAT(COALESCE(w.inicjaly, aa.actor_login), '/') AS zatwierdzil_short,
                   GROUP_CONCAT(COALESCE(aa.actor_name, aa.actor_login), ', ') AS zatwierdzil_full
            FROM audit_log al
            JOIN audit_log_actors aa ON aa.audit_id = al.id
            LEFT JOIN workers w ON w.id = aa.worker_id
            WHERE al.event_type = 'ebr.batch.status_changed'
              AND al.entity_id IN ({placeholders})
            GROUP BY al.entity_id
        """, ebr_ids).fetchall()
        approval_map = {r["entity_id"]: {"short": r["zatwierdzil_short"], "full": r["zatwierdzil_full"]} for r in approval_rows}
        for r in result:
            ap = approval_map.get(r["ebr_id"], {})
            r["zatwierdzil_short"] = ap.get("short", "")
            r["zatwierdzil_full"] = ap.get("full", "")

    return result


def get_registry_columns(db: sqlite3.Connection, produkt: str) -> list:
    """Get column definitions (parameter names + limits) for a product's registry table.

    Reads directly from produkt_etap_limity (SSOT) via build_pipeline_context.
    Rule matches the completed batch card: analiza_koncowa (jednorazowy) +
    last cykliczny etap (for K7 that's standaryzacja).

    Uses skrot from parametry_analityczne as label where available.
    """
    from mbr.pipeline.adapter import build_pipeline_context
    ctx = build_pipeline_context(db, produkt, typ=None)
    pola: list = []
    if ctx is None:
        # No pipeline, but virtual columns (e.g. surowce) may still apply — fall through.
        sekcje = {}
        etapy_json = []
    else:
        sekcje = ctx.get("parametry_lab", {})
        etapy_json = ctx.get("etapy_json", [])

    # 1. Jednorazowy etapy → include their sekcja's pola (typically analiza_koncowa)
    # 2. Last cykliczny etap → include its sekcja_lab (e.g. "analiza" for K7 standaryzacja)
    wanted_keys = []
    for e in etapy_json:
        if e.get("typ_cyklu") == "jednorazowy":
            wanted_keys.append(e.get("sekcja_lab"))
    cykliczne = [e for e in etapy_json if e.get("typ_cyklu") == "cykliczny"]
    if cykliczne:
        wanted_keys.append(cykliczne[-1].get("sekcja_lab"))

    # Fallback for products with no pipeline at all (shouldn't happen post-MVP,
    # but defensive): try plain "analiza_koncowa" if sekcje has it.
    if not wanted_keys and "analiza_koncowa" in sekcje:
        wanted_keys = ["analiza_koncowa"]

    seen_kodу: set = set()
    for key in wanted_keys:
        if key is None or key not in sekcje:
            continue
        for pole in sekcje[key].get("pola", []):
            kod = pole.get("kod")
            if kod and kod not in seen_kodу:
                pola.append(dict(pole))
                seen_kodу.add(kod)

    # Replace labels with skroty
    skroty: dict = {}
    try:
        rows = db.execute(
            "SELECT kod, skrot FROM parametry_analityczne "
            "WHERE aktywny=1 AND skrot IS NOT NULL AND skrot != ''"
        ).fetchall()
        skroty = {r["kod"]: r["skrot"] for r in rows}
    except Exception:
        pass
    for pole in pola:
        if pole.get("kod") in skroty:
            pole["label"] = skroty[pole["kod"]]

    # Append Surowce virtual column if product uses raw-material batch tracking
    # (defined in substrat_produkty). Currently: Alkinol, Alkinol_B.
    try:
        has_surowce = db.execute(
            "SELECT 1 FROM substrat_produkty WHERE produkt=? LIMIT 1", (produkt,)
        ).fetchone() is not None
        if has_surowce:
            pola.append({"kod": "__surowce__", "label": "Surowce", "is_surowce": True})
    except Exception:
        pass

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
