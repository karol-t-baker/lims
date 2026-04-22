"""Remove the H2O2 (nadtlenki) gate condition from the utlenienie stage.

Background: only Chegina_K7 uses utlenienie, and laborants there routinely
skip H2O2 measurement (they only report siarczyny = 0). The global
etap_warunki row made H2O2 mandatory for the gate to pass, blocking
progression into standaryzacja. This script drops that warunek; the
nadtlenki parameter stays in produkt_etap_limity so the input field is
still available if someone wants to enter a value.

Idempotent — safe to run twice.

Run once per deploy:
    python scripts/remove_nadtlenki_gate.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mbr.db import get_db


def main():
    db = get_db()
    try:
        cur = db.execute(
            """DELETE FROM etap_warunki
               WHERE etap_id = (SELECT id FROM etapy_analityczne WHERE kod = 'utlenienie')
                 AND parametr_id = (SELECT id FROM parametry_analityczne WHERE kod = 'nadtlenki')"""
        )
        db.commit()
        print(f"deleted {cur.rowcount} row(s) from etap_warunki")
    finally:
        db.close()


if __name__ == "__main__":
    main()
