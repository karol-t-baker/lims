"""
Configure sulfonowanie + utlenienie stages for K40GLOL/GLO/GL/K7.

Pipeline becomes: sulfonowanie → utlenienie → standaryzacja → analiza_koncowa

Also fills correction formulas for:
- Perhydrol (utlenienie)
- Woda (standaryzacja)
- NaCl (standaryzacja)

Run: python -m scripts.setup_sulfonowanie_utlenienie
"""
import sqlite3
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mbr.db import get_db
from mbr.models import init_mbr_tables
from mbr.pipeline.models import (
    create_etap, get_etap, add_etap_parametr, list_etap_parametry,
    add_etap_warunek, list_etap_warunki, add_etap_korekta, list_etap_korekty,
    set_produkt_pipeline, get_produkt_pipeline, remove_pipeline_etap,
    set_produkt_etap_limit,
)

PRODUCTS = ["Chegina_K40GLOL", "Chegina_K40GLO", "Chegina_K40GL", "Chegina_K7"]

# Parameter IDs (from parametry_analityczne)
PARAM_IDS = {}  # filled at runtime


def _get_param_id(db, kod):
    if kod not in PARAM_IDS:
        row = db.execute("SELECT id FROM parametry_analityczne WHERE kod=?", (kod,)).fetchone()
        PARAM_IDS[kod] = row[0] if row else None
    return PARAM_IDS[kod]


def _get_or_create_etap(db, kod, nazwa, typ_cyklu, kolejnosc_domyslna):
    row = db.execute("SELECT id FROM etapy_analityczne WHERE kod=?", (kod,)).fetchone()
    if row:
        return row[0]
    return create_etap(db, kod=kod, nazwa=nazwa, typ_cyklu=typ_cyklu,
                       kolejnosc_domyslna=kolejnosc_domyslna)


def setup(db):
    stats = {"etapy": 0, "params": 0, "warunki": 0, "korekty": 0, "formuly": 0, "pipeline": 0, "limity": 0}

    # ── 1. Ensure sulfonowanie etap exists ──
    sulf_id = _get_or_create_etap(db, "sulfonowanie", "Sulfonowanie", "jednorazowy", 4)

    # Add params to sulfonowanie (if not already)
    sulf_params = [("so3", 1), ("ph_10proc", 2), ("nd20", 3), ("barwa_I2", 4)]
    existing = {p["kod"] for p in list_etap_parametry(db, sulf_id)}
    for kod, kol in sulf_params:
        pid = _get_param_id(db, kod)
        if pid and kod not in existing:
            add_etap_parametr(db, sulf_id, pid, kolejnosc=kol)
            stats["params"] += 1

    # ── 2. Configure utlenienie etap ──
    utl_id = db.execute("SELECT id FROM etapy_analityczne WHERE kod='utlenienie'").fetchone()[0]

    # Add params (so3, h2o2/nadtlenki, ph_10proc, nd20, barwa)
    utl_params = [("so3", 1), ("nadtlenki", 2), ("ph_10proc", 3), ("nd20", 4), ("barwa_I2", 5)]
    existing = {p["kod"] for p in list_etap_parametry(db, utl_id)}
    for kod, kol in utl_params:
        pid = _get_param_id(db, kod)
        if pid and kod not in existing:
            add_etap_parametr(db, utl_id, pid, kolejnosc=kol)
            stats["params"] += 1

    # Gate: SO3 <= target (target set per product in produkt_etap_limity)
    if not list_etap_warunki(db, utl_id):
        so3_pid = _get_param_id(db, "so3")
        if so3_pid:
            add_etap_warunek(db, utl_id, so3_pid, "<=", 0.1,
                             opis_warunku="SO₃²⁻ poniżej celu")
            stats["warunki"] += 1

    # Correction: Perhydrol with formula
    utl_korekty = list_etap_korekty(db, utl_id)
    perh_exists = any(k["substancja"] == "Perhydrol 34%" for k in utl_korekty)
    if not perh_exists:
        kid = add_etap_korekta(db, utl_id, "Perhydrol 34%", "kg", "produkcja", kolejnosc=1)
        stats["korekty"] += 1
    else:
        kid = next(k["id"] for k in utl_korekty if k["substancja"] == "Perhydrol 34%")

    # Set formula on perhydrol correction
    formula = "(C_so3 - target_so3) * 0.01214 * Meff + (target_nadtlenki > 0 ? target_nadtlenki * Meff / 350 : 0)"
    zmienne = json.dumps({
        "C_so3": "pomiar:so3",
        "target_so3": "target:so3",
        "target_nadtlenki": "target:nadtlenki",
        "Meff": "wielkosc_szarzy_kg > 6600 ? wielkosc_szarzy_kg - 1000 : wielkosc_szarzy_kg - 500",
    })
    db.execute("UPDATE etap_korekty_katalog SET formula_ilosc=?, formula_zmienne=? WHERE id=?",
               (formula, zmienne, kid))
    stats["formuly"] += 1

    # ── 3. Standaryzacja formulas ──
    stand_id = db.execute("SELECT id FROM etapy_analityczne WHERE kod='standaryzacja'").fetchone()[0]
    stand_korekty = list_etap_korekty(db, stand_id)

    # Woda formula
    woda_k = next((k for k in stand_korekty if k["substancja"] == "Woda"), None)
    if woda_k:
        formula_woda = "(R0 - Rk) * Meff / (Rk - 1.333)"
        zmienne_woda = json.dumps({
            "R0": "pomiar:nd20",
            "Rk": "target:nd20",
            "Meff": "wielkosc_szarzy_kg > 6600 ? wielkosc_szarzy_kg - 1000 : wielkosc_szarzy_kg - 500",
        })
        db.execute("UPDATE etap_korekty_katalog SET formula_ilosc=?, formula_zmienne=? WHERE id=?",
                   (formula_woda, zmienne_woda, woda_k["id"]))
        stats["formuly"] += 1

    # NaCl formula
    nacl_k = next((k for k in stand_korekty if k["substancja"] == "NaCl"), None)
    if nacl_k:
        formula_nacl = "(Ck / 100 * Meff - Meff * Ccl / 100) / (1 - Ck / 100)"
        zmienne_nacl = json.dumps({
            "Ccl": "pomiar:nacl",
            "Ck": "target:nacl",
            "Meff": "wielkosc_szarzy_kg > 6600 ? wielkosc_szarzy_kg - 1000 : wielkosc_szarzy_kg - 500",
        })
        db.execute("UPDATE etap_korekty_katalog SET formula_ilosc=?, formula_zmienne=? WHERE id=?",
                   (formula_nacl, zmienne_nacl, nacl_k["id"]))
        stats["formuly"] += 1

    db.commit()

    # ── 4. Update pipelines ──
    ak_id = db.execute("SELECT id FROM etapy_analityczne WHERE kod='analiza_koncowa'").fetchone()[0]

    for produkt in PRODUCTS:
        pipe = get_produkt_pipeline(db, produkt)
        kody = [p["kod"] for p in pipe]

        # Ensure order: sulfonowanie(1) → utlenienie(2) → standaryzacja(3) → analiza_koncowa(4)
        if "sulfonowanie" not in kody:
            set_produkt_pipeline(db, produkt, sulf_id, kolejnosc=1)
            stats["pipeline"] += 1
        if "utlenienie" not in kody:
            set_produkt_pipeline(db, produkt, utl_id, kolejnosc=2)
        # Reorder existing
        set_produkt_pipeline(db, produkt, sulf_id, kolejnosc=1)
        set_produkt_pipeline(db, produkt, utl_id, kolejnosc=2)
        set_produkt_pipeline(db, produkt, stand_id, kolejnosc=3)
        if "analiza_koncowa" in kody:
            set_produkt_pipeline(db, produkt, ak_id, kolejnosc=4)

        # ── 5. Product-specific limits + targets ──
        # Sulfonowanie: SO3 limits per product (no target, just measurement)
        set_produkt_etap_limit(db, produkt, sulf_id, _get_param_id(db, "so3"))
        set_produkt_etap_limit(db, produkt, sulf_id, _get_param_id(db, "ph_10proc"))
        set_produkt_etap_limit(db, produkt, sulf_id, _get_param_id(db, "nd20"))
        set_produkt_etap_limit(db, produkt, sulf_id, _get_param_id(db, "barwa_I2"))

        # Utlenienie: SO3 + nadtlenki with targets
        set_produkt_etap_limit(db, produkt, utl_id, _get_param_id(db, "so3"),
                               max_limit=0.1, target=0.03)
        set_produkt_etap_limit(db, produkt, utl_id, _get_param_id(db, "nadtlenki"),
                               max_limit=0.01, target=0.005)
        set_produkt_etap_limit(db, produkt, utl_id, _get_param_id(db, "ph_10proc"))
        set_produkt_etap_limit(db, produkt, utl_id, _get_param_id(db, "nd20"))
        set_produkt_etap_limit(db, produkt, utl_id, _get_param_id(db, "barwa_I2"))

        # Standaryzacja: ensure targets for nd20 and nacl (for formulas)
        # nd20 target per product (Rk)
        nd20_targets = {
            "Chegina_K40GLOL": 1.4070, "Chegina_K40GLO": 1.4070,
            "Chegina_K40GL": 1.4070, "Chegina_K7": 1.3922,
        }
        nacl_targets = {
            "Chegina_K40GLOL": 6.5, "Chegina_K40GLO": 6.5,
            "Chegina_K40GL": 6.5, "Chegina_K7": 6.0,
        }
        if produkt in nd20_targets:
            set_produkt_etap_limit(db, produkt, stand_id, _get_param_id(db, "nd20"),
                                   target=nd20_targets[produkt])
        if produkt in nacl_targets:
            set_produkt_etap_limit(db, produkt, stand_id, _get_param_id(db, "nacl"),
                                   target=nacl_targets[produkt])

        stats["limity"] += 1

    db.commit()
    return stats


if __name__ == "__main__":
    db = get_db()
    init_mbr_tables(db)
    stats = setup(db)
    print(json.dumps(stats, indent=2))

    for p in PRODUCTS:
        pipe = get_produkt_pipeline(db, p)
        print(f"{p}: {' → '.join(s['kod'] for s in pipe)}")

    # Show formulas
    for kod in ["utlenienie", "standaryzacja"]:
        eid = db.execute("SELECT id FROM etapy_analityczne WHERE kod=?", (kod,)).fetchone()[0]
        korekty = list_etap_korekty(db, eid)
        for k in korekty:
            if k["formula_ilosc"]:
                print(f"  {kod}/{k['substancja']}: {k['formula_ilosc']}")

    db.close()
