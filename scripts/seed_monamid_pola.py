"""
seed_monamid_pola.py — one-shot seed for Monamid_KO produkt_pola definitions.

Creates two scope='produkt' fields on Monamid_KO that were configured
locally during dev via DAO calls but never checked into a seed script
(hence missing on prod after the produkt_pola feature was deployed):

  - nr_zamowienia       "Nr zamówienia"
  - nr_dop_oleju        "Nr dopuszczenia oleju kokosowego"

Both visible in modal / hero / ukonczone, both aktywne=1.

Idempotent:
  - If the pole doesn't exist, creates it.
  - If it exists with aktywne=0, reactivates it.
  - If it exists with aktywne=1, no-op.

Usage:
    python scripts/seed_monamid_pola.py --db data/batch_db.sqlite [--user-id 7] [--dry-run]
"""

import argparse
import sqlite3
import sys
from pathlib import Path

PRODUKT_NAZWA = "Monamid_KO"

POLA_SPEC = [
    {
        "kod": "nr_zamowienia",
        "label_pl": "Nr zamówienia",
        "typ_danych": "text",
        "miejsca": ["modal", "hero", "ukonczone"],
        "kolejnosc": 10,
    },
    {
        "kod": "nr_dop_oleju",
        "label_pl": "Nr dopuszczenia oleju kokosowego",
        "typ_danych": "text",
        "miejsca": ["modal", "hero", "ukonczone"],
        "kolejnosc": 20,
    },
]


def run(db: sqlite3.Connection, user_id: int) -> dict:
    """Apply seed. Returns counters dict."""
    from mbr.shared.produkt_pola import create_pole, update_pole

    counts = {"created": 0, "reactivated": 0, "noop": 0}

    prod_row = db.execute(
        "SELECT id FROM produkty WHERE nazwa=?", (PRODUKT_NAZWA,)
    ).fetchone()
    if not prod_row:
        print(f"ERROR: produkt '{PRODUKT_NAZWA}' not found in DB", file=sys.stderr)
        return counts
    produkt_id = prod_row["id"]

    for spec in POLA_SPEC:
        existing = db.execute(
            "SELECT id, aktywne FROM produkt_pola "
            "WHERE scope='produkt' AND scope_id=? AND kod=?",
            (produkt_id, spec["kod"]),
        ).fetchone()

        if existing is None:
            payload = {
                "scope": "produkt",
                "scope_id": produkt_id,
                "kod": spec["kod"],
                "label_pl": spec["label_pl"],
                "typ_danych": spec["typ_danych"],
                "miejsca": spec["miejsca"],
                "kolejnosc": spec["kolejnosc"],
                "aktywne": 1,
            }
            create_pole(db, payload, user_id)
            counts["created"] += 1
            print(f"CREATED: {spec['kod']} ({spec['label_pl']})")
        elif existing["aktywne"] == 0:
            update_pole(db, existing["id"], {"aktywne": 1}, user_id)
            counts["reactivated"] += 1
            print(f"REACTIVATED: {spec['kod']}")
        else:
            counts["noop"] += 1
            print(f"NOOP (already active): {spec['kod']}")

    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Path to batch_db.sqlite")
    parser.add_argument(
        "--user-id", type=int, default=7,
        help="worker_id for audit attribution (default 7)"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Roll back instead of committing.")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: DB not found: {db_path}", file=sys.stderr)
        return 1

    # Make mbr.* importable when running from repo root.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")

    try:
        counts = run(db, args.user_id)
        if args.dry_run:
            db.rollback()
            print(f"DRY RUN — rolled back: {counts}")
        else:
            db.commit()
            print(f"DONE: {counts}")
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
