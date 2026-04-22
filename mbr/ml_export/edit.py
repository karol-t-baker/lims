"""Edit helpers for ML export inline-edit endpoints.

Provides read (detail) and write (PUT) operations for admin inline editing
of batch, session, measurement and correction records.
"""
import sqlite3
from typing import Any


# ---------------------------------------------------------------------------
# Whitelist of editable fields per table — field name → DB column
# ---------------------------------------------------------------------------

_BATCH_EDITABLE: dict[str, str] = {
    "masa_kg":                "wielkosc_szarzy_kg",
    "dt_start":               "dt_start",
    "dt_end":                 "dt_end",
    "status":                 "status",
    "pakowanie_bezposrednie": "pakowanie_bezposrednie",
    "nastaw":                 "nastaw",
}

_SESSION_EDITABLE: dict[str, str] = {
    "dt_start": "dt_start",
    "laborant":  "laborant",
}

# ebr_pomiar — has wartosc (REAL) and w_limicie (INTEGER); no wartosc_text column
_POMIAR_EDITABLE: dict[str, str] = {
    "wartosc":   "wartosc",
    "w_limicie": "w_limicie",
}

# ebr_wyniki — additionally has wartosc_text (TEXT)
_WYNIKI_EDITABLE: dict[str, str] = {
    "wartosc":       "wartosc",
    "wartosc_text":  "wartosc_text",
    "w_limicie":     "w_limicie",
}

# ebr_korekta_v2 — ilosc stored as 'kg' in API surface
_KOREKTA_EDITABLE: dict[str, str] = {
    "kg":            "ilosc",
    "status":        "status",
    "dt_wykonania":  "dt_wykonania",
}


def _audit(db: sqlite3.Connection, table: str, row_id: Any,
           field: str, old_value: Any, new_value: Any, batch_ebr_id: int) -> None:
    """Emit ml_export.value_edited audit event. Best-effort — never raises."""
    try:
        from mbr.shared import audit
        audit.log_event(
            "ml_export.value_edited",
            entity_type="ebr",
            entity_id=batch_ebr_id,
            payload={
                "table": table,
                "id": row_id,
                "field": field,
                "old_value": old_value,
                "new_value": new_value,
                "batch_ebr_id": batch_ebr_id,
            },
            db=db,
        )
    except Exception:
        pass


def update_batch(db: sqlite3.Connection, ebr_id: int,
                 fields: dict[str, Any]) -> tuple[bool, str | None]:
    """Update editable batch fields. Returns (True, None) on success or (False, error_msg)."""
    for field in fields:
        if field not in _BATCH_EDITABLE:
            return False, f"Field '{field}' is not editable"
    row = db.execute("SELECT * FROM ebr_batches WHERE ebr_id=?", (ebr_id,)).fetchone()
    if not row:
        return False, "NOT_FOUND"
    for field, value in fields.items():
        col = _BATCH_EDITABLE[field]
        old_value = row[col]
        db.execute(f"UPDATE ebr_batches SET {col}=? WHERE ebr_id=?", (value, ebr_id))
        _audit(db, "ebr_batches", ebr_id, field, old_value, value, ebr_id)
    db.commit()
    return True, None


def update_session(db: sqlite3.Connection, sesja_id: int,
                   fields: dict[str, Any]) -> tuple[bool, str | None]:
    """Update editable session fields. Returns (True, None) on success or (False, error_msg)."""
    for field in fields:
        if field not in _SESSION_EDITABLE:
            return False, f"Field '{field}' is not editable"
    row = db.execute("SELECT * FROM ebr_etap_sesja WHERE id=?", (sesja_id,)).fetchone()
    if not row:
        return False, "NOT_FOUND"
    batch_ebr_id = row["ebr_id"]
    for field, value in fields.items():
        col = _SESSION_EDITABLE[field]
        old_value = row[col]
        db.execute(f"UPDATE ebr_etap_sesja SET {col}=? WHERE id=?", (value, sesja_id))
        _audit(db, "ebr_etap_sesja", sesja_id, field, old_value, value, batch_ebr_id)
    db.commit()
    return True, None


def update_measurement(db: sqlite3.Connection, source: str, row_id: int,
                       fields: dict[str, Any]) -> tuple[bool, str | None]:
    """Update editable measurement fields in ebr_pomiar (source='pomiar') or
    ebr_wyniki (source='wyniki'). Returns (True, None) on success or (False, error_msg)."""
    if source == "pomiar":
        editable = _POMIAR_EDITABLE
        table = "ebr_pomiar"
        pk_col = "id"
    elif source == "wyniki":
        editable = _WYNIKI_EDITABLE
        table = "ebr_wyniki"
        pk_col = "wynik_id"
    else:
        return False, f"Unknown source '{source}'; must be 'pomiar' or 'wyniki'"

    for field in fields:
        if field not in editable:
            return False, f"Field '{field}' is not editable for source '{source}'"

    row = db.execute(f"SELECT * FROM {table} WHERE {pk_col}=?", (row_id,)).fetchone()
    if not row:
        return False, "NOT_FOUND"

    # Resolve ebr_id for audit: pomiar → via sesja; wyniki → direct column
    if source == "pomiar":
        sesja = db.execute(
            "SELECT ebr_id FROM ebr_etap_sesja WHERE id=?", (row["sesja_id"],)
        ).fetchone()
        batch_ebr_id = sesja["ebr_id"] if sesja else row_id
    else:
        batch_ebr_id = row["ebr_id"]

    for field, value in fields.items():
        col = editable[field]
        old_value = row[col]
        db.execute(f"UPDATE {table} SET {col}=? WHERE {pk_col}=?", (value, row_id))
        _audit(db, table, row_id, field, old_value, value, batch_ebr_id)
    db.commit()
    return True, None


def update_correction(db: sqlite3.Connection, korekta_id: int,
                      fields: dict[str, Any]) -> tuple[bool, str | None]:
    """Update editable correction fields in ebr_korekta_v2.

    API field 'kg' maps to DB column 'ilosc'.
    Returns (True, None) on success or (False, error_msg).
    """
    for field in fields:
        if field not in _KOREKTA_EDITABLE:
            return False, f"Field '{field}' is not editable"

    row = db.execute("SELECT * FROM ebr_korekta_v2 WHERE id=?", (korekta_id,)).fetchone()
    if not row:
        return False, "NOT_FOUND"

    # Resolve batch_ebr_id: ebr_korekta_v2 → ebr_etap_sesja → ebr_batches
    sesja = db.execute(
        "SELECT ebr_id FROM ebr_etap_sesja WHERE id=?", (row["sesja_id"],)
    ).fetchone()
    batch_ebr_id = sesja["ebr_id"] if sesja else korekta_id

    for field, value in fields.items():
        col = _KOREKTA_EDITABLE[field]
        old_value = row[col]
        db.execute(f"UPDATE ebr_korekta_v2 SET {col}=? WHERE id=?", (value, korekta_id))
        _audit(db, "ebr_korekta_v2", korekta_id, field, old_value, value, batch_ebr_id)
    db.commit()
    return True, None


def get_batch_detail(db: sqlite3.Connection, nr_partii: str) -> dict | None:
    """Return full editable detail for a single batch identified by nr_partii.

    Returns None if not found.
    Structure: {batch: {...}, sessions: [...], measurements: [...], corrections: [...]}
    """
    row = db.execute(
        """SELECT e.ebr_id, e.batch_id, e.nr_partii, e.wielkosc_szarzy_kg AS masa_kg,
                  e.nastaw, e.dt_start, e.dt_end, e.status,
                  e.pakowanie_bezposrednie, m.produkt
             FROM ebr_batches e
             JOIN mbr_templates m ON m.mbr_id = e.mbr_id
            WHERE e.nr_partii = ?
            LIMIT 1""",
        (nr_partii,),
    ).fetchone()
    if not row:
        return None

    ebr_id = row["ebr_id"]
    batch = dict(row)

    sessions = [
        dict(r) for r in db.execute(
            """SELECT s.id, s.ebr_id, ea.kod AS etap, s.etap_id, s.runda,
                      s.dt_start, s.laborant
                 FROM ebr_etap_sesja s
                 JOIN etapy_analityczne ea ON ea.id = s.etap_id
                WHERE s.ebr_id = ?
             ORDER BY s.etap_id, s.runda""",
            (ebr_id,),
        ).fetchall()
    ]

    # Measurements: new (ebr_pomiar) + legacy (ebr_wyniki)
    new_meas = [
        dict(r) for r in db.execute(
            """SELECT p.id, s.ebr_id, ea.kod AS etap, s.runda,
                      pa.kod AS kod_parametru, p.wartosc, p.w_limicie,
                      p.dt_wpisu, p.wpisal,
                      'pomiar' AS source
                 FROM ebr_pomiar p
                 JOIN ebr_etap_sesja s       ON s.id = p.sesja_id
                 JOIN etapy_analityczne ea   ON ea.id = s.etap_id
                 JOIN parametry_analityczne pa ON pa.id = p.parametr_id
                WHERE s.ebr_id = ?""",
            (ebr_id,),
        ).fetchall()
    ]
    leg_meas = [
        dict(r) for r in db.execute(
            """SELECT wynik_id AS id, ebr_id, sekcja AS etap, 0 AS runda,
                      kod_parametru, wartosc, wartosc_text, w_limicie,
                      dt_wpisu, wpisal,
                      'wyniki' AS source
                 FROM ebr_wyniki
                WHERE ebr_id = ?""",
            (ebr_id,),
        ).fetchall()
    ]
    measurements = new_meas + leg_meas

    corrections = [
        dict(r) for r in db.execute(
            """SELECT k.id, s.ebr_id, ea.kod AS etap, s.runda,
                      ek.substancja, k.ilosc AS kg, k.ilosc_wyliczona AS sugest_kg,
                      k.status, k.zalecil, k.dt_wykonania
                 FROM ebr_korekta_v2 k
                 JOIN ebr_etap_sesja s        ON s.id = k.sesja_id
                 JOIN etapy_analityczne ea    ON ea.id = s.etap_id
                 JOIN etap_korekty_katalog ek ON ek.id = k.korekta_typ_id
                WHERE s.ebr_id = ?""",
            (ebr_id,),
        ).fetchall()
    ]

    return {
        "batch": batch,
        "sessions": sessions,
        "measurements": measurements,
        "corrections": corrections,
    }
