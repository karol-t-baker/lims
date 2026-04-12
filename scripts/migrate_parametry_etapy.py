"""Migrate parametry_etapy data into the new pipeline tables.

One-time, idempotent migration. Reads existing parametry_etapy rows and
populates:
  - etapy_analityczne   (one row per unique kontekst)
  - etap_parametry      (shared/global rows: produkt IS NULL)
  - produkt_pipeline    (product-specific rows: unique produkt × etap)
  - produkt_etap_limity (product-specific rows that carry non-null limit/target)

Run once:
    python scripts/migrate_parametry_etapy.py

Safe to run again — uses INSERT OR IGNORE throughout.
"""

import sqlite3

# ---------------------------------------------------------------------------
# Kontekst → display metadata
# ---------------------------------------------------------------------------

KONTEKST_META = {
    "amidowanie":        {"nazwa": "Po amidowaniu",            "typ_cyklu": "jednorazowy", "kol": 1},
    "namca":             {"nazwa": "NAMCA (SMCA)",             "typ_cyklu": "jednorazowy", "kol": 2},
    "czwartorzedowanie": {"nazwa": "Czwartorzędowanie",        "typ_cyklu": "jednorazowy", "kol": 3},
    "sulfonowanie":      {"nazwa": "Sulfonowanie",             "typ_cyklu": "cykliczny",   "kol": 4},
    "utlenienie":        {"nazwa": "Utlenienie",               "typ_cyklu": "cykliczny",   "kol": 5},
    "rozjasnianie":      {"nazwa": "Rozjaśnianie",             "typ_cyklu": "cykliczny",   "kol": 6},
    "dodatki":           {"nazwa": "Dodatki standaryzacyjne",  "typ_cyklu": "cykliczny",   "kol": 7},
    "analiza_koncowa":   {"nazwa": "Analiza końcowa",          "typ_cyklu": "jednorazowy", "kol": 8},
}

_DEFAULT_META = {"nazwa": None, "typ_cyklu": "jednorazowy", "kol": 99}


def migrate_parametry_etapy(db: sqlite3.Connection) -> dict:
    """Migrate parametry_etapy into the new pipeline tables.

    Returns a stats dict with insertion counts for each target table.
    """
    stats = {
        "etapy_analityczne": 0,
        "etap_parametry": 0,
        "produkt_pipeline": 0,
        "produkt_etap_limity": 0,
    }

    # ------------------------------------------------------------------
    # Step 1: etapy_analityczne — one row per unique kontekst
    # ------------------------------------------------------------------
    konteksty = db.execute(
        "SELECT DISTINCT kontekst FROM parametry_etapy WHERE kontekst != 'cert_variant'"
    ).fetchall()

    for (kontekst,) in konteksty:
        meta = KONTEKST_META.get(kontekst, _DEFAULT_META)
        nazwa = meta["nazwa"] if meta["nazwa"] is not None else kontekst
        typ_cyklu = meta["typ_cyklu"]
        kol = meta["kol"]

        cur = db.execute(
            """INSERT OR IGNORE INTO etapy_analityczne
               (kod, nazwa, typ_cyklu, kolejnosc_domyslna)
               VALUES (?, ?, ?, ?)""",
            (kontekst, nazwa, typ_cyklu, kol),
        )
        stats["etapy_analityczne"] += cur.rowcount

    db.commit()

    # Build a lookup: kontekst → etap_id
    etap_ids = {
        row[0]: row[1]
        for row in db.execute("SELECT kod, id FROM etapy_analityczne").fetchall()
    }

    # ------------------------------------------------------------------
    # Step 2: etap_parametry — shared rows (produkt IS NULL)
    # ------------------------------------------------------------------
    shared_rows = db.execute(
        """SELECT kontekst, parametr_id, kolejnosc, min_limit, max_limit,
                  nawazka_g, precision, target, wymagany, grupa,
                  formula, sa_bias, krok
           FROM parametry_etapy
           WHERE produkt IS NULL AND kontekst != 'cert_variant'"""
    ).fetchall()

    for row in shared_rows:
        kontekst = row[0]
        etap_id = etap_ids.get(kontekst)
        if etap_id is None:
            continue

        cur = db.execute(
            """INSERT OR IGNORE INTO etap_parametry
               (etap_id, parametr_id, kolejnosc, min_limit, max_limit,
                nawazka_g, precision, target, wymagany, grupa,
                formula, sa_bias, krok)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                etap_id,
                row[1],   # parametr_id
                row[2],   # kolejnosc
                row[3],   # min_limit
                row[4],   # max_limit
                row[5],   # nawazka_g
                row[6],   # precision
                row[7],   # target
                row[8],   # wymagany
                row[9],   # grupa
                row[10],  # formula
                row[11],  # sa_bias
                row[12],  # krok
            ),
        )
        stats["etap_parametry"] += cur.rowcount

    db.commit()

    # ------------------------------------------------------------------
    # Step 2b: etap_parametry — synthesize from product rows where no
    #          shared (NULL) rows exist. For each kontekst that has
    #          product-specific rows but no shared rows, create a global
    #          entry per unique parametr_id (with NULL limits — products
    #          will supply their own via produkt_etap_limity).
    # ------------------------------------------------------------------
    for kontekst, etap_id in etap_ids.items():
        has_shared = db.execute(
            "SELECT 1 FROM etap_parametry WHERE etap_id = ? LIMIT 1",
            (etap_id,),
        ).fetchone()
        if has_shared:
            continue

        product_params = db.execute(
            """SELECT DISTINCT parametr_id, MIN(kolejnosc) as kol,
                      grupa, formula, sa_bias, krok
               FROM parametry_etapy
               WHERE kontekst = ? AND produkt IS NOT NULL
                     AND kontekst != 'cert_variant'
               GROUP BY parametr_id""",
            (kontekst,),
        ).fetchall()

        for row in product_params:
            cur = db.execute(
                """INSERT OR IGNORE INTO etap_parametry
                   (etap_id, parametr_id, kolejnosc, grupa, formula, sa_bias, krok)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (etap_id, row[0], row[1], row[2], row[3], row[4], row[5]),
            )
            stats["etap_parametry"] += cur.rowcount

    db.commit()

    # ------------------------------------------------------------------
    # Step 3: produkt_pipeline — one row per unique (produkt, kontekst)
    # ------------------------------------------------------------------
    product_pairs = db.execute(
        """SELECT DISTINCT produkt, kontekst
           FROM parametry_etapy
           WHERE produkt IS NOT NULL AND kontekst != 'cert_variant'
           ORDER BY produkt, kontekst"""
    ).fetchall()

    # Assign a sequential kolejnosc within each product based on kol metadata
    produkt_kolejnosc: dict[str, int] = {}

    for produkt, kontekst in product_pairs:
        etap_id = etap_ids.get(kontekst)
        if etap_id is None:
            continue

        # Use the global metadata order as the default kolejnosc
        meta = KONTEKST_META.get(kontekst, _DEFAULT_META)
        kolejnosc = meta["kol"]

        cur = db.execute(
            """INSERT OR IGNORE INTO produkt_pipeline
               (produkt, etap_id, kolejnosc)
               VALUES (?, ?, ?)""",
            (produkt, etap_id, kolejnosc),
        )
        stats["produkt_pipeline"] += cur.rowcount

    db.commit()

    # ------------------------------------------------------------------
    # Step 4: produkt_etap_limity — product rows with non-null limits
    # ------------------------------------------------------------------
    product_rows = db.execute(
        """SELECT produkt, kontekst, parametr_id,
                  min_limit, max_limit, nawazka_g, precision, target
           FROM parametry_etapy
           WHERE produkt IS NOT NULL AND kontekst != 'cert_variant'
             AND (min_limit IS NOT NULL OR max_limit IS NOT NULL
                  OR nawazka_g IS NOT NULL OR precision IS NOT NULL
                  OR target IS NOT NULL)"""
    ).fetchall()

    for row in product_rows:
        produkt, kontekst = row[0], row[1]
        etap_id = etap_ids.get(kontekst)
        if etap_id is None:
            continue

        cur = db.execute(
            """INSERT OR IGNORE INTO produkt_etap_limity
               (produkt, etap_id, parametr_id, min_limit, max_limit,
                nawazka_g, precision, target)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                produkt,
                etap_id,
                row[2],   # parametr_id
                row[3],   # min_limit
                row[4],   # max_limit
                row[5],   # nawazka_g
                row[6],   # precision
                row[7],   # target
            ),
        )
        stats["produkt_etap_limity"] += cur.rowcount

    db.commit()

    return stats


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys
    import os

    # Allow running from repo root without installing the package
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from mbr.db import get_db
    from mbr.models import init_mbr_tables

    db = get_db()
    init_mbr_tables(db)
    stats = migrate_parametry_etapy(db)
    print(json.dumps(stats, indent=2))
    db.close()
