"""
migrate_rozklad_kwasow_seed.py — one-shot migration for parametr 59
(cert_qual_rozklad_kwasow / Rozkład kwasów tłuszczowych).

Performs four idempotent operations:

  1. Clear stale parametry_etapy.cert_qualitative_result='≤1,0' (relict of
     the old single-value jakosciowy semantics — now obsolete since the
     parameter became a 9-chain composite).
  2. Flip parametry_analityczne.grupa from 'lab' to 'zewn' (semantic
     correction — values come from external lab certificates).
  3. Flip parametry_etapy.grupa from 'lab' to 'zewn' for all rows
     referencing parametr_id=59.
  4. Purge ebr_wyniki rows where wartosc_text='≤1,0' AND wartosc_text NOT
     LIKE '%|%' (= seed-only rows, never edited by laborant). Pipe-bearing
     rows are LEFT UNTOUCHED.

Idempotent: each operation has a guard such that re-running yields zero
mutations after the first successful application.

Usage:
    python scripts/migrate_rozklad_kwasow_seed.py --db data/batch_db.sqlite [--dry-run]
"""

import argparse
import sqlite3
import sys
from pathlib import Path


PARAMETR_ID = 59
KOD = "cert_qual_rozklad_kwasow"
SEED_VALUE = "≤1,0"


def run_migration(db: sqlite3.Connection) -> dict:
    """Apply the four migration operations. Returns counters dict."""
    counts = {"cert_qr_cleared": 0, "pa_grupa": 0, "pe_grupa": 0, "ebr_purged": 0}

    cur = db.execute(
        "UPDATE parametry_etapy SET cert_qualitative_result=NULL "
        "WHERE parametr_id=? AND cert_qualitative_result=?",
        (PARAMETR_ID, SEED_VALUE),
    )
    counts["cert_qr_cleared"] = cur.rowcount

    cur = db.execute(
        "UPDATE parametry_analityczne SET grupa='zewn' "
        "WHERE id=? AND grupa='lab'",
        (PARAMETR_ID,),
    )
    counts["pa_grupa"] = cur.rowcount

    cur = db.execute(
        "UPDATE parametry_etapy SET grupa='zewn' "
        "WHERE parametr_id=? AND grupa='lab'",
        (PARAMETR_ID,),
    )
    counts["pe_grupa"] = cur.rowcount

    cur = db.execute(
        "DELETE FROM ebr_wyniki "
        "WHERE kod_parametru=? AND wartosc_text=? AND wartosc_text NOT LIKE '%|%'",
        (KOD, SEED_VALUE),
    )
    counts["ebr_purged"] = cur.rowcount

    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Path to batch_db.sqlite")
    parser.add_argument("--dry-run", action="store_true", help="Report counts but rollback")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: DB not found: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        counts = run_migration(conn)
        if args.dry_run:
            conn.rollback()
            suffix = " (dry-run, rolled back)"
        else:
            conn.commit()
            suffix = ""
        print(
            f"cert_qr_cleared={counts['cert_qr_cleared']}, "
            f"pa_grupa={counts['pa_grupa']}, "
            f"pe_grupa={counts['pe_grupa']}, "
            f"ebr_purged={counts['ebr_purged']}"
            + suffix
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
