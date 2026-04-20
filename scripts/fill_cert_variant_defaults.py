"""Fill static avon_code/avon_name on cert_variants and swap has_certificate_number -> has_rspo.

Rationale: audit of WZÓR DOCX templates shows that (a) AVON variants carry product-specific
AVON codes that never change between issuances, and (b) every 'has_certificate_number' variant
actually just uses the global RSPO number. After this migration, the issuance modal only prompts
for order_number.

Idempotent: re-running is safe.
"""
import json
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "batch_db.sqlite"

AVON_DEFAULTS = [
    ("Alkinol_B",  ["avon"],                     "R05750", "CETEARYL ALCOHOL / CETEARETH-20"),
    ("Chegina_KK", ["avon", "lehvoss", "prime"], "R26010", "COCAMIDOPROPYL BETAINE (LOW COLOR) - KATHON"),
    ("Glikoster_P",["avon"],                     "R05730", "PROPYLENE GLYCOL MONOSTEARATE"),
    ("Monamid_KO", ["avon"],                     "R08310", "COCAMIDE MEA 100 %"),
]


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    filled = 0
    for produkt, variants, code, name in AVON_DEFAULTS:
        for vid in variants:
            cur.execute(
                "UPDATE cert_variants SET avon_code=?, avon_name=? WHERE produkt=? AND variant_id=?",
                (code, name, produkt, vid),
            )
            filled += cur.rowcount

    swapped = 0
    cur.execute("SELECT id, produkt, variant_id, flags FROM cert_variants")
    for row in cur.fetchall():
        flags = json.loads(row["flags"] or "[]")
        if "has_certificate_number" not in flags:
            continue
        new = [f for f in flags if f != "has_certificate_number"]
        if "has_rspo" not in new:
            new.append("has_rspo")
        cur.execute("UPDATE cert_variants SET flags=? WHERE id=?", (json.dumps(new), row["id"]))
        swapped += 1
        print(f"  [{row['produkt']}/{row['variant_id']}] {flags} -> {new}")

    conn.commit()
    conn.close()
    print(f"\nDone. AVON defaults set: {filled}  |  flags swapped: {swapped}")


if __name__ == "__main__":
    main()
