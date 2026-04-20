"""Backfill: seed ebr_wyniki.wartosc_text for existing open batches' jakosciowy params.

Idempotent — uses INSERT OR IGNORE guarded by UNIQUE(ebr_id, sekcja, kod_parametru).
Skips completed batches (status='completed') and rows already present.

Run via auto-deploy.sh or manually:
    python -m scripts.backfill_jakosciowe_values --db data/batch_db.sqlite
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def run(db_path: str) -> int:
    """Run backfill on db at db_path. Returns number of rows inserted."""
    if not Path(db_path).exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 0
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    inserted = 0
    now = datetime.now().isoformat(timespec="seconds")
    # Open batches — rebuild parametry_lab fresh per batch so typ_analityczny
    # is present even when the stored snapshot predates PR2.
    from mbr.parametry.registry import build_parametry_lab
    rows = conn.execute("""
        SELECT eb.ebr_id, eb.operator, mt.produkt
          FROM ebr_batches eb
          JOIN mbr_templates mt ON mt.mbr_id = eb.mbr_id
         WHERE COALESCE(eb.status, '') != 'completed'
    """).fetchall()
    for row in rows:
        parametry_lab = build_parametry_lab(conn, row["produkt"]) or {}
        for sekcja_key, sekcja in parametry_lab.items():
            for pole in sekcja.get("pola", []):
                if pole.get("typ_analityczny") != "jakosciowy":
                    continue
                kod = pole.get("kod")
                if not kod:
                    continue
                default_row = conn.execute(
                    """SELECT pe.cert_qualitative_result
                         FROM parametry_analityczne pa
                         JOIN parametry_etapy pe ON pe.parametr_id = pa.id
                        WHERE pa.kod = ? AND pe.produkt = ?
                        LIMIT 1""",
                    (kod, row["produkt"]),
                ).fetchone()
                default = default_row["cert_qualitative_result"] if default_row else None
                if not default:
                    continue
                cur = conn.execute(
                    """INSERT OR IGNORE INTO ebr_wyniki
                       (ebr_id, sekcja, kod_parametru, tag, wartosc, wartosc_text,
                        is_manual, dt_wpisu, wpisal)
                       VALUES (?, ?, ?, ?, NULL, ?, 0, ?, ?)""",
                    (row["ebr_id"], sekcja_key, kod, pole.get("tag") or kod,
                     default, now, row["operator"] or "backfill"),
                )
                if cur.rowcount > 0:
                    inserted += 1
    conn.commit()
    conn.close()
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/batch_db.sqlite",
                        help="Path to SQLite DB (default: data/batch_db.sqlite)")
    args = parser.parse_args()
    n = run(args.db)
    print(f"backfill_jakosciowe_values: inserted {n} ebr_wyniki rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
