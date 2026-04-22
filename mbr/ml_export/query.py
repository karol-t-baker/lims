"""Build long-format rows for the ML export package.

Public API:
    build_batches(db, produkty, statuses) -> list[dict]   # one row per batch
    build_sessions(db, ebr_ids)          -> list[dict]   # one row per (batch, etap, runda)
    build_measurements(db, ebr_ids)      -> list[dict]   # pomiary + legacy, long
    build_corrections(db, ebr_ids)       -> list[dict]   # one row per correction
    export_ml_package(db, produkty, statuses) -> bytes   # zip of 4 CSVs + schema + README
"""
import csv
import io
import json
import sqlite3
import zipfile
from datetime import datetime

from mbr.ml_export.schema import build_schema

DEFAULT_PRODUKTY = ["Chegina_K7"]


def _meff(masa: float) -> float:
    return masa - 1000 if masa > 6600 else masa - 500


def _batch_target(db: sqlite3.Connection, ebr_id: int, produkt: str) -> tuple[float | None, float | None]:
    """Return (target_ph, target_nd20). Prefer cele_json snapshot on any
    standaryzacja session; fall back to korekta_cele globals for the produkt."""
    tph = tnd = None
    try:
        row = db.execute(
            """SELECT s.cele_json
                 FROM ebr_etap_sesja s
                 JOIN etapy_analityczne ea ON ea.id = s.etap_id
                WHERE s.ebr_id = ? AND ea.kod = 'standaryzacja'
                  AND s.cele_json IS NOT NULL
             ORDER BY s.runda
                LIMIT 1""",
            (ebr_id,),
        ).fetchone()
    except sqlite3.Error:
        row = None
    if row and row["cele_json"]:
        try:
            cele = json.loads(row["cele_json"])
            tph = cele.get("target_ph")
            tnd = cele.get("target_nd20")
        except json.JSONDecodeError:
            pass
    if tph is None or tnd is None:
        globals_ = db.execute(
            "SELECT kod, wartosc FROM korekta_cele WHERE produkt = ?",
            (produkt,),
        ).fetchall()
        for g in globals_:
            if g["kod"] == "target_ph" and tph is None:
                tph = g["wartosc"]
            elif g["kod"] == "target_nd20" and tnd is None:
                tnd = g["wartosc"]
    return tph, tnd


def build_batches(db: sqlite3.Connection, produkty: list[str],
                  statuses: tuple[str, ...]) -> list[dict]:
    if not produkty or not statuses:
        return []
    prod_q = ",".join("?" for _ in produkty)
    stat_q = ",".join("?" for _ in statuses)
    rows = db.execute(
        f"""SELECT e.ebr_id, e.batch_id, e.nr_partii, e.wielkosc_szarzy_kg, e.nastaw,
                   e.dt_start, e.dt_end, e.status, e.pakowanie_bezposrednie,
                   m.produkt
              FROM ebr_batches e
              JOIN mbr_templates m ON m.mbr_id = e.mbr_id
             WHERE e.status IN ({stat_q}) AND e.typ = 'szarza'
               AND m.produkt IN ({prod_q})
          ORDER BY e.ebr_id""",
        (*statuses, *produkty),
    ).fetchall()

    out = []
    for b in rows:
        masa = b["wielkosc_szarzy_kg"] or b["nastaw"] or 0
        tph, tnd = _batch_target(db, b["ebr_id"], b["produkt"])
        out.append({
            "ebr_id":      b["ebr_id"],
            "batch_id":    b["batch_id"],
            "nr_partii":   b["nr_partii"],
            "produkt":     b["produkt"],
            "status":      b["status"],
            "masa_kg":     float(masa) if masa else 0.0,
            "meff_kg":     float(_meff(masa)) if masa else 0.0,
            "dt_start":    b["dt_start"],
            "dt_end":      b["dt_end"],
            "pakowanie":   b["pakowanie_bezposrednie"] or "zbiornik",
            "target_ph":   tph,
            "target_nd20": tnd,
        })
    return out


# ── Legacy wide-CSV shims (used by routes.py until Task 8 replaces the route) ─

def export_k7_batches(db: sqlite3.Connection, after_id: int = 0,
                      statuses: tuple = ("completed",)) -> list[dict]:
    """Thin wrapper kept for backward compat with routes.py until Task 8."""
    return build_batches(db, produkty=DEFAULT_PRODUKTY, statuses=tuple(statuses))


def get_csv_columns(db: sqlite3.Connection) -> list[str]:
    """Thin wrapper kept for backward compat with routes.py until Task 8."""
    rows = build_batches(db, produkty=DEFAULT_PRODUKTY, statuses=("completed",))
    if rows:
        return list(rows[0].keys())
    return list({
        "ebr_id", "batch_id", "nr_partii", "produkt", "status",
        "masa_kg", "meff_kg", "dt_start", "dt_end", "pakowanie",
        "target_ph", "target_nd20",
    })
