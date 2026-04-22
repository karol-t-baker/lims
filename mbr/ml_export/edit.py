"""Edit helpers for ML export inline-edit endpoints.

Provides read (detail) and write (PUT) operations for admin inline editing
of batch, session, measurement and correction records.
"""
import sqlite3
from typing import Any


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
