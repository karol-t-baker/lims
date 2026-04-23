"""One-time: sync `etapy_analityczne.nazwa` to current KONTEKST_META values.

Background: `migrate_parametry_etapy.py` is idempotent via `INSERT OR IGNORE`,
which leaves existing rows' `nazwa` alone. When we later renamed three K7
stages (sulfonowanie → "Analiza po sulfonowaniu" etc.), local DBs were
recreated and picked up the new names, but production never saw the update.

This script UPDATEs each row where the stored `nazwa` differs from the
KONTEKST_META value for the same `kod`. Safe to re-run — only touches rows
that drift from the SSOT.

Run once per deploy (prod):
    python scripts/sync_etap_nazwa.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mbr.db import get_db
from scripts.migrate_parametry_etapy import KONTEKST_META


def main() -> None:
    db = get_db()
    try:
        updated = 0
        for kod, meta in KONTEKST_META.items():
            target_nazwa = meta["nazwa"] if meta["nazwa"] is not None else kod
            cur = db.execute(
                "UPDATE etapy_analityczne SET nazwa = ? "
                "WHERE kod = ? AND nazwa IS NOT ?",
                (target_nazwa, kod, target_nazwa),
            )
            if cur.rowcount:
                print(f"  {kod}: -> {target_nazwa!r}")
                updated += cur.rowcount
        db.commit()
        print(f"updated {updated} row(s)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
