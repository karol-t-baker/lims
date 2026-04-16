"""
Setup standaryzacja stage for K40GLOL, K40GLO, K40GL, K7.

Creates the "Standaryzacja" analytical stage with:
- Parameters: SM, pH 10%, NaCl, SA (measurement params)
- Gate conditions: all 4 must be within product limits
- Corrections: woda, NaCl, kwas cytrynowy (ordered by production)

Updates pipeline for 4 products:
  ... existing stages ... → utlenienie → standaryzacja → (no separate analiza_koncowa)

For all other products: pipeline unchanged (analiza_koncowa remains).

Run: python -m scripts.setup_standaryzacja
"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mbr.db import get_db
from mbr.models import init_mbr_tables
from mbr.pipeline.models import (
    create_etap, get_etap, add_etap_parametr, list_etap_parametry,
    add_etap_warunek, add_etap_korekta, list_etap_korekty,
    set_produkt_pipeline, get_produkt_pipeline, remove_pipeline_etap,
    set_produkt_etap_limit,
)

FULL_PIPELINE_PRODUCTS = [
    "Chegina_K40GLOL", "Chegina_K40GLO", "Chegina_K40GL", "Chegina_K7",
]

STANDARYZACJA_PARAMS = ["sm", "ph_10proc", "nacl", "sa"]

STANDARYZACJA_KOREKTY = [
    {"substancja": "Woda", "jednostka": "kg", "wykonawca": "produkcja"},
    {"substancja": "NaCl", "jednostka": "kg", "wykonawca": "produkcja"},
    {"substancja": "Kwas cytrynowy", "jednostka": "kg", "wykonawca": "produkcja"},
]

PRODUCT_LIMITS = {
    "Chegina_K40GLOL": {
        "sm":        {"min_limit": 44.0, "max_limit": 48.0, "target": 46.0},
        "ph_10proc": {"min_limit": 4.5,  "max_limit": 6.5},
        "nacl":      {"min_limit": 5.8,  "max_limit": 7.3},
        "sa":        {"min_limit": 36.0, "max_limit": 42.0},
    },
    "Chegina_K40GLO": {
        "sm":        {"min_limit": 44.0, "max_limit": 48.0, "target": 46.0},
        "ph_10proc": {"min_limit": 5.0,  "max_limit": 7.0},
        "nacl":      {"min_limit": 5.8,  "max_limit": 7.3},
        "sa":        {"min_limit": 37.0, "max_limit": 42.0},
    },
    "Chegina_K40GL": {
        "sm":        {"min_limit": 44.0, "max_limit": 48.0, "target": 46.0},
        "ph_10proc": {"min_limit": 4.5,  "max_limit": 5.5},
        "nacl":      {"min_limit": 5.8,  "max_limit": 7.3},
        "sa":        {"min_limit": 37.0, "max_limit": 42.0},
    },
    "Chegina_K7": {
        "sm":        {"min_limit": 40.0, "max_limit": 48.0, "target": 44.0},
        "ph_10proc": {"min_limit": 4.0,  "max_limit": 6.0},
        "nacl":      {"min_limit": 4.0,  "max_limit": 8.0},
        "sa":        {"min_limit": 30.0, "max_limit": 42.0},
    },
}


def setup_standaryzacja(db: sqlite3.Connection) -> dict:
    stats = {"etap_created": False, "params": 0, "warunki": 0, "korekty": 0, "pipelines": 0, "limity": 0}

    # 1. Create or find Standaryzacja etap
    existing = db.execute(
        "SELECT id FROM etapy_analityczne WHERE kod = 'standaryzacja'"
    ).fetchone()

    if existing:
        etap_id = existing[0]
    else:
        etap_id = create_etap(
            db, kod="standaryzacja", nazwa="Standaryzacja",
            typ_cyklu="cykliczny", opis="Regulacja SM, pH, NaCl. Ostatnia runda = analiza końcowa.",
            kolejnosc_domyslna=9,
        )
        stats["etap_created"] = True

    # 2. Add default parameters (no limits — products supply their own)
    existing_params = {p["kod"] for p in list_etap_parametry(db, etap_id)}
    param_rows = db.execute(
        "SELECT id, kod FROM parametry_analityczne WHERE kod IN ({})".format(
            ",".join("?" for _ in STANDARYZACJA_PARAMS)
        ),
        STANDARYZACJA_PARAMS,
    ).fetchall()
    param_id_map = {r["kod"]: r["id"] for r in param_rows}

    for idx, kod in enumerate(STANDARYZACJA_PARAMS):
        if kod in existing_params:
            continue
        pid = param_id_map.get(kod)
        if pid is None:
            continue
        extra = {}
        if kod == "sa":
            extra["sa_bias"] = 0.6
        add_etap_parametr(db, etap_id, pid, kolejnosc=idx + 1, **extra)
        stats["params"] += 1

    # 3. Add gate conditions (all 4 params must be within limits)
    existing_warunki = db.execute(
        "SELECT parametr_id FROM etap_warunki WHERE etap_id = ?", (etap_id,)
    ).fetchall()
    existing_warunki_pids = {r[0] for r in existing_warunki}

    for kod in STANDARYZACJA_PARAMS:
        pid = param_id_map.get(kod)
        if pid is None or pid in existing_warunki_pids:
            continue
        add_etap_warunek(
            db, etap_id, pid, "w_limicie", None,
            opis_warunku=f"{kod} w zakresie limitów produktu",
        )
        stats["warunki"] += 1

    # 4. Add corrections
    existing_kor = {k["substancja"] for k in list_etap_korekty(db, etap_id)}
    for idx, kor in enumerate(STANDARYZACJA_KOREKTY):
        if kor["substancja"] in existing_kor:
            continue
        add_etap_korekta(
            db, etap_id, kor["substancja"], kor["jednostka"], kor["wykonawca"],
            kolejnosc=idx + 1,
        )
        stats["korekty"] += 1

    db.commit()

    # 5. Update pipelines for 4 products
    for produkt in FULL_PIPELINE_PRODUCTS:
        pipeline = get_produkt_pipeline(db, produkt)
        etap_kody = [p["kod"] for p in pipeline]

        # Remove analiza_koncowa and dodatki if present (standaryzacja replaces them)
        ak_id = db.execute("SELECT id FROM etapy_analityczne WHERE kod='analiza_koncowa'").fetchone()
        dod_id = db.execute("SELECT id FROM etapy_analityczne WHERE kod='dodatki'").fetchone()
        if ak_id:
            remove_pipeline_etap(db, produkt, ak_id[0])
        if dod_id:
            remove_pipeline_etap(db, produkt, dod_id[0])

        # Ensure utlenienie is in pipeline
        utl_id = db.execute("SELECT id FROM etapy_analityczne WHERE kod='utlenienie'").fetchone()
        pipeline = get_produkt_pipeline(db, produkt)
        etap_kody = [p["kod"] for p in pipeline]
        if utl_id and "utlenienie" not in etap_kody:
            max_kol = max((p["kolejnosc"] for p in pipeline), default=0)
            set_produkt_pipeline(db, produkt, utl_id[0], kolejnosc=max_kol + 1)

        # Add standaryzacja at the end if not present
        pipeline = get_produkt_pipeline(db, produkt)
        etap_kody = [p["kod"] for p in pipeline]
        if "standaryzacja" not in etap_kody:
            max_kol = max((p["kolejnosc"] for p in pipeline), default=0)
            set_produkt_pipeline(db, produkt, etap_id, kolejnosc=max_kol + 1)
            stats["pipelines"] += 1

        # 6. Set product-specific limits
        limits = PRODUCT_LIMITS.get(produkt, {})
        for kod, lim in limits.items():
            pid = param_id_map.get(kod)
            if pid is None:
                continue
            set_produkt_etap_limit(db, produkt, etap_id, pid, **lim)
            stats["limity"] += 1

    db.commit()
    return stats


if __name__ == "__main__":
    import json
    db = get_db()
    init_mbr_tables(db)
    stats = setup_standaryzacja(db)
    print(json.dumps(stats, indent=2))

    # Verify
    for p in FULL_PIPELINE_PRODUCTS:
        pipe = db.execute("""
            SELECT ea.kod FROM produkt_pipeline pp
            JOIN etapy_analityczne ea ON ea.id = pp.etap_id
            WHERE pp.produkt = ? ORDER BY pp.kolejnosc
        """, (p,)).fetchall()
        print(f"{p}: {' → '.join(r[0] for r in pipe)}")

    db.close()
