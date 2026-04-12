"""Migrate parametry_cert data into parametry_etapy cert columns.
Idempotent — skips rows already migrated (on_cert=1 for base params,
existing cert_variant rows for variant params).
"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "batch_db.sqlite"


def migrate(db=None):
    own_conn = db is None
    if own_conn:
        db = sqlite3.connect(str(DB))
        db.row_factory = sqlite3.Row

    updated = 0
    inserted = 0
    var_inserted = 0

    # -----------------------------------------------------------------------
    # 1. Base cert params — parametry_cert WHERE variant_id IS NULL
    # -----------------------------------------------------------------------
    base_rows = db.execute(
        "SELECT produkt, parametr_id, kolejnosc, requirement, format, qualitative_result "
        "FROM parametry_cert WHERE variant_id IS NULL"
    ).fetchall()

    for row in base_rows:
        produkt = row["produkt"]
        parametr_id = row["parametr_id"]

        existing = db.execute(
            "SELECT id, on_cert FROM parametry_etapy "
            "WHERE produkt=? AND parametr_id=? AND kontekst='analiza_koncowa' AND cert_variant_id IS NULL",
            (produkt, parametr_id),
        ).fetchone()

        if existing:
            if existing["on_cert"] != 1:
                db.execute(
                    "UPDATE parametry_etapy SET on_cert=1, cert_requirement=?, cert_format=?, "
                    "cert_qualitative_result=?, cert_kolejnosc=? WHERE id=?",
                    (
                        row["requirement"],
                        row["format"],
                        row["qualitative_result"],
                        row["kolejnosc"],
                        existing["id"],
                    ),
                )
                updated += 1
        else:
            cursor = db.execute(
                "INSERT OR IGNORE INTO parametry_etapy "
                "(produkt, kontekst, parametr_id, kolejnosc, min_limit, max_limit, "
                "on_cert, cert_requirement, cert_format, cert_qualitative_result, cert_kolejnosc) "
                "VALUES (?, 'analiza_koncowa', ?, 0, 0, NULL, 1, ?, ?, ?, ?)",
                (
                    produkt,
                    parametr_id,
                    row["requirement"],
                    row["format"],
                    row["qualitative_result"],
                    row["kolejnosc"],
                ),
            )
            if cursor.rowcount:
                inserted += 1

    # -----------------------------------------------------------------------
    # 2. Variant add_parameters — parametry_cert WHERE variant_id IS NOT NULL
    # -----------------------------------------------------------------------
    variant_rows = db.execute(
        "SELECT produkt, parametr_id, kolejnosc, requirement, format, qualitative_result, variant_id "
        "FROM parametry_cert WHERE variant_id IS NOT NULL"
    ).fetchall()

    for row in variant_rows:
        produkt = row["produkt"]
        parametr_id = row["parametr_id"]
        variant_id = row["variant_id"]

        already = db.execute(
            "SELECT id FROM parametry_etapy "
            "WHERE produkt=? AND parametr_id=? AND kontekst='cert_variant' AND cert_variant_id=?",
            (produkt, parametr_id, variant_id),
        ).fetchone()

        if not already:
            cursor = db.execute(
                "INSERT OR IGNORE INTO parametry_etapy "
                "(produkt, kontekst, parametr_id, kolejnosc, min_limit, max_limit, "
                "on_cert, cert_requirement, cert_format, cert_qualitative_result, cert_kolejnosc, cert_variant_id) "
                "VALUES (?, 'cert_variant', ?, 0, 0, NULL, 1, ?, ?, ?, ?, ?)",
                (
                    produkt,
                    parametr_id,
                    row["requirement"],
                    row["format"],
                    row["qualitative_result"],
                    row["kolejnosc"],
                    variant_id,
                ),
            )
            if cursor.rowcount:
                var_inserted += 1

    db.commit()
    print(
        f"migrate_cert_to_etapy: {updated} updated, {inserted} inserted (base), "
        f"{var_inserted} inserted (variant)"
    )

    if own_conn:
        db.close()


if __name__ == "__main__":
    migrate()
