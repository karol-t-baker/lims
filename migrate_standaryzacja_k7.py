"""
Migrate standaryzacja stage for Chegina_K7:
1. Add nD20 parameter to etap_parametry catalog
2. Update product limits: pH 5.5–6.5, nD20 1.3922–1.3925
3. Gate conditions: only pH 10% and nD20 (remove SM, NaCl, SA from gate)

Run: python migrate_standaryzacja_k7.py
"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from mbr.db import get_db


def _rebuild_etap_warunki(db: sqlite3.Connection):
    """Rebuild etap_warunki table to add 'w_limicie' to CHECK constraint."""
    # Check if constraint already includes w_limicie
    sql = db.execute("SELECT sql FROM sqlite_master WHERE name='etap_warunki'").fetchone()[0]
    if "w_limicie" in sql:
        return False

    db.execute("ALTER TABLE etap_warunki RENAME TO _etap_warunki_old")
    db.execute("""
        CREATE TABLE etap_warunki (
            id              INTEGER PRIMARY KEY,
            etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
            parametr_id     INTEGER NOT NULL REFERENCES parametry_analityczne(id),
            operator        TEXT NOT NULL CHECK(operator IN ('<', '<=', '>=', '>', 'between', '=', 'w_limicie')),
            wartosc         REAL,
            wartosc_max     REAL,
            opis_warunku    TEXT
        )
    """)
    db.execute("""
        INSERT INTO etap_warunki (id, etap_id, parametr_id, operator, wartosc, wartosc_max, opis_warunku)
        SELECT id, etap_id, parametr_id, operator, wartosc, wartosc_max, opis_warunku
        FROM _etap_warunki_old
    """)
    db.execute("DROP TABLE _etap_warunki_old")
    db.commit()
    return True


def migrate(db: sqlite3.Connection) -> dict:
    stats = {"nd20_added": False, "limity_updated": 0, "gate_removed": 0, "gate_added": 0}

    # Rebuild table to support w_limicie operator
    rebuilt = _rebuild_etap_warunki(db)
    if rebuilt:
        print("  Rebuilt etap_warunki with w_limicie operator support")

    etap_id = db.execute(
        "SELECT id FROM etapy_analityczne WHERE kod = 'standaryzacja'"
    ).fetchone()[0]

    nd20_id = db.execute(
        "SELECT id FROM parametry_analityczne WHERE kod = 'nd20'"
    ).fetchone()[0]

    ph_id = db.execute(
        "SELECT id FROM parametry_analityczne WHERE kod = 'ph_10proc'"
    ).fetchone()[0]

    # 1. Add nD20 to etap_parametry (catalog) if not present
    exists = db.execute(
        "SELECT id FROM etap_parametry WHERE etap_id = ? AND parametr_id = ?",
        (etap_id, nd20_id),
    ).fetchone()
    if not exists:
        max_kol = db.execute(
            "SELECT COALESCE(MAX(kolejnosc), 0) FROM etap_parametry WHERE etap_id = ?",
            (etap_id,),
        ).fetchone()[0]
        db.execute(
            "INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc, precision) VALUES (?, ?, ?, ?)",
            (etap_id, nd20_id, max_kol + 1, 4),
        )
        stats["nd20_added"] = True
        print(f"  Added nD20 to etap_parametry (kolejnosc={max_kol + 1})")

    # 2. Update product limits for Chegina_K7
    # pH 10%: 5.5 – 6.5
    updated = db.execute(
        """UPDATE produkt_etap_limity
           SET min_limit = 5.5, max_limit = 6.5
           WHERE produkt = 'Chegina_K7' AND etap_id = ? AND parametr_id = ?""",
        (etap_id, ph_id),
    ).rowcount
    if updated:
        stats["limity_updated"] += 1
        print(f"  Updated pH 10% limits: 5.5 – 6.5")

    # nD20: 1.3922 – 1.3925
    existing_nd20 = db.execute(
        "SELECT id FROM produkt_etap_limity WHERE produkt = 'Chegina_K7' AND etap_id = ? AND parametr_id = ?",
        (etap_id, nd20_id),
    ).fetchone()
    if existing_nd20:
        db.execute(
            "UPDATE produkt_etap_limity SET min_limit = 1.3922, max_limit = 1.3925 WHERE id = ?",
            (existing_nd20[0],),
        )
    else:
        db.execute(
            "INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, min_limit, max_limit, precision) VALUES (?, ?, ?, ?, ?, ?)",
            ("Chegina_K7", etap_id, nd20_id, 1.3922, 1.3925, 4),
        )
    stats["limity_updated"] += 1
    print(f"  Set nD20 limits: 1.3922 – 1.3925")

    # 3. Gate conditions: remove all existing, add only pH + nD20
    # Remove old gate conditions (sm, nacl, sa, ph)
    removed = db.execute(
        "DELETE FROM etap_warunki WHERE etap_id = ?", (etap_id,)
    ).rowcount
    stats["gate_removed"] = removed
    print(f"  Removed {removed} old gate conditions")

    # Add pH 10% gate — uses "w_limicie" operator (checks product-specific limits)
    db.execute(
        "INSERT INTO etap_warunki (etap_id, parametr_id, operator, wartosc, wartosc_max, opis_warunku) VALUES (?, ?, ?, ?, ?, ?)",
        (etap_id, ph_id, "w_limicie", None, None, "pH 10% w zakresie limitów produktu"),
    )
    stats["gate_added"] += 1

    # Add nD20 gate
    db.execute(
        "INSERT INTO etap_warunki (etap_id, parametr_id, operator, wartosc, wartosc_max, opis_warunku) VALUES (?, ?, ?, ?, ?, ?)",
        (etap_id, nd20_id, "w_limicie", None, None, "nD20 w zakresie limitów produktu"),
    )
    stats["gate_added"] += 1
    print(f"  Added 2 gate conditions: pH 10%, nD20")

    # 4. Default correction targets (korekta_cele) for standaryzacja calculator
    for kod, val in [("target_nd20", 1.3922), ("target_ph", 6.0)]:
        db.execute(
            """INSERT INTO korekta_cele (etap_id, produkt, kod, wartosc)
               VALUES (?, 'Chegina_K7', ?, ?)
               ON CONFLICT(etap_id, produkt, kod) DO UPDATE SET wartosc=excluded.wartosc""",
            (etap_id, kod, val),
        )
    stats["cele_set"] = True
    print("  Set correction targets: nD20=1.3922, pH=6.0")

    # 5. Update utlenienie gate: w_limicie instead of hardcoded <= 0.1
    utl_etap_id = db.execute(
        "SELECT id FROM etapy_analityczne WHERE kod = 'utlenienie'"
    ).fetchone()
    if utl_etap_id:
        utl_etap_id = utl_etap_id[0]
        so3_id = db.execute("SELECT id FROM parametry_analityczne WHERE kod = 'so3'").fetchone()[0]
        nadt_id = db.execute("SELECT id FROM parametry_analityczne WHERE kod = 'nadtlenki'").fetchone()[0]
        db.execute("DELETE FROM etap_warunki WHERE etap_id = ?", (utl_etap_id,))
        db.execute(
            "INSERT INTO etap_warunki (etap_id, parametr_id, operator, wartosc, wartosc_max, opis_warunku) VALUES (?, ?, ?, ?, ?, ?)",
            (utl_etap_id, so3_id, "w_limicie", None, None, "SO3 w zakresie limitów produktu"),
        )
        db.execute(
            "INSERT INTO etap_warunki (etap_id, parametr_id, operator, wartosc, wartosc_max, opis_warunku) VALUES (?, ?, ?, ?, ?, ?)",
            (utl_etap_id, nadt_id, "w_limicie", None, None, "nadtlenki w zakresie limitów produktu"),
        )
        stats["utl_gate_updated"] = True
        print("  Updated utlenienie gate: w_limicie for SO3, nadtlenki")

    db.commit()
    return stats


if __name__ == "__main__":
    import json
    db = get_db()
    print("Migrating standaryzacja for Chegina_K7...")
    stats = migrate(db)
    print(f"\nResult: {json.dumps(stats, indent=2)}")

    # Verify
    etap_id = db.execute("SELECT id FROM etapy_analityczne WHERE kod='standaryzacja'").fetchone()[0]
    print("\n--- Verification ---")
    print("Params:")
    for r in db.execute("""
        SELECT pa.kod, ep.kolejnosc FROM etap_parametry ep
        JOIN parametry_analityczne pa ON pa.id = ep.parametr_id
        WHERE ep.etap_id = ? ORDER BY ep.kolejnosc
    """, (etap_id,)).fetchall():
        print(f"  {r[0]} (kol={r[1]})")

    print("Gate:")
    for r in db.execute("""
        SELECT pa.kod, w.opis_warunku FROM etap_warunki w
        JOIN parametry_analityczne pa ON pa.id = w.parametr_id
        WHERE w.etap_id = ?
    """, (etap_id,)).fetchall():
        print(f"  {r[0]}: {r[1]}")

    print("Limity K7:")
    for r in db.execute("""
        SELECT pa.kod, pel.min_limit, pel.max_limit
        FROM produkt_etap_limity pel
        JOIN parametry_analityczne pa ON pa.id = pel.parametr_id
        WHERE pel.produkt = 'Chegina_K7' AND pel.etap_id = ?
    """, (etap_id,)).fetchall():
        print(f"  {r[0]}: {r[1]} – {r[2]}")

    db.close()
