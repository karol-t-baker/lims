"""Remove pipeline stages for K40GL/GLO/GLOL — only K7 gets full pipeline.

The other 3 products should only show analiza_koncowa (like zbiorniki).
etap_decyzje references etapy_analityczne (not produkt_pipeline) but has a
produkt TEXT column, so we delete by produkt name.

Usage:
    python migrate_k7_only_pipeline.py
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "batch_db.sqlite"

REMOVE_PRODUCTS_SHORT = ("K40GL", "K40GLO", "K40GLOL")
PIPELINE_STAGES = ("sulfonowanie", "utlenienie", "standaryzacja")


def main():
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # ── 1. Show current state ─────────────────────────────────
    products = [r[0] for r in conn.execute(
        "SELECT DISTINCT produkt FROM produkt_pipeline"
    ).fetchall()]
    print(f"All products in produkt_pipeline: {len(products)}")

    # Find non-K7 pipeline rows (any stage except analiza_koncowa)
    rows = conn.execute("""
        SELECT pp.id, pp.produkt, ea.kod
        FROM produkt_pipeline pp
        JOIN etapy_analityczne ea ON ea.id = pp.etap_id
        WHERE ea.kod != 'analiza_koncowa'
          AND pp.produkt NOT LIKE '%K7'
    """).fetchall()

    if not rows:
        print("No non-K7 pipeline stages to remove — already clean.")
        conn.close()
        return

    print(f"\nRemoving {len(rows)} produkt_pipeline entries:")
    for r in rows:
        print(f"  pp.id={r['id']:3d}  {r['produkt']:25s}  {r['kod']}")

    pp_ids = [r["id"] for r in rows]

    # ── 2. Delete from produkt_pipeline ───────────────────────
    placeholders = ",".join("?" for _ in pp_ids)
    conn.execute(
        f"DELETE FROM produkt_pipeline WHERE id IN ({placeholders})",
        pp_ids,
    )
    print(f"\nDeleted {len(pp_ids)} produkt_pipeline rows.")

    # ── 3. Delete etap_decyzje for non-K7 products ───────────
    # etap_decyzje has a `produkt` TEXT column (short names like 'K40GL')
    dec_rows = conn.execute("""
        SELECT id, produkt, kod
        FROM etap_decyzje
        WHERE produkt IN ('K40GL','K40GLO','K40GLOL')
    """).fetchall()

    if dec_rows:
        dec_ids = [r["id"] for r in dec_rows]
        placeholders2 = ",".join("?" for _ in dec_ids)
        conn.execute(
            f"DELETE FROM etap_decyzje WHERE id IN ({placeholders2})",
            dec_ids,
        )
        print(f"Deleted {len(dec_ids)} etap_decyzje rows for non-K7 products.")
    else:
        print("No etap_decyzje rows to remove (already clean).")

    conn.commit()

    # ── 4. Verify ─────────────────────────────────────────────
    remaining = conn.execute("""
        SELECT pp.produkt, ea.kod
        FROM produkt_pipeline pp
        JOIN etapy_analityczne ea ON ea.id = pp.etap_id
        WHERE ea.kod != 'analiza_koncowa'
        ORDER BY pp.produkt, pp.kolejnosc
    """).fetchall()

    print(f"\nRemaining pipeline stages (should be K7 only):")
    for r in remaining:
        print(f"  {r['produkt']:25s}  {r['kod']}")

    remaining_dec = conn.execute("""
        SELECT produkt, kod FROM etap_decyzje ORDER BY produkt, kolejnosc
    """).fetchall()
    print(f"\nRemaining etap_decyzje ({len(remaining_dec)} rows):")
    for r in remaining_dec:
        print(f"  {r['produkt']:10s}  {r['kod']}")

    conn.close()
    print("\nDone — only Chegina_K7 has full pipeline now.")


if __name__ == "__main__":
    main()
