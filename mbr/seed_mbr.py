"""
seed_mbr.py — Create 4 MBR templates (one per product) and 2 seed users.

Run once:  python -m mbr.seed_mbr
"""

import json
from datetime import datetime

from mbr.models import get_db, init_mbr_tables, create_user

# ---------------------------------------------------------------------------
# Shared etapy definition
# ---------------------------------------------------------------------------

ETAPY = [
    {"nr": 1, "nazwa": "Amidowanie",                      "read_only": True},
    {"nr": 2, "nazwa": "Wytworzenie SMCA",                "read_only": True},
    {"nr": 3, "nazwa": "Czwartorzędowanie",                "read_only": True},
    {"nr": 4, "nazwa": "Analiza przed standaryzacją",      "read_only": False, "sekcja_lab": "przed_standaryzacja"},
    {"nr": 5, "nazwa": "Standaryzacja",                    "read_only": True},
    {"nr": 6, "nazwa": "Analiza końcowa",                  "read_only": False, "sekcja_lab": "analiza_koncowa"},
    {"nr": 7, "nazwa": "Przepompowanie",                   "read_only": True},
]

# ---------------------------------------------------------------------------
# parametry_lab — shared across all products (placeholder limits)
# ---------------------------------------------------------------------------

PARAMETRY_LAB = {
    "przed_standaryzacja": {
        "pola": [
            {"kod": "ph_10proc",    "label": "pH 10%",    "tag": "pH",    "typ": "float", "min": 4.0,  "max": 6.0,   "precision": 2},
            {"kod": "nd20",         "label": "nd20",      "tag": "nd20",  "typ": "float", "min": 1.39, "max": 1.42,  "precision": 3},
            {"kod": "procent_so3",  "label": "%SO3",      "tag": "%SO3",  "typ": "float", "min": 0.0,  "max": 0.03,  "precision": 3},
            {"kod": "barwa_fau",    "label": "Barwa FAU", "tag": "FAU",   "typ": "float", "min": 0.0,  "max": 200.0, "precision": 0},
        ]
    },
    "analiza_koncowa": {
        "pola": [
            {"kod": "ph_10proc",         "label": "pH 10%",    "tag": "pH",     "typ": "float", "min": 4.0,  "max": 6.0,    "precision": 2},
            {"kod": "nd20",              "label": "nd20",      "tag": "nd20",   "typ": "float", "min": 1.39, "max": 1.42,   "precision": 3},
            {"kod": "procent_sm",        "label": "%SM",       "tag": "%SM",    "typ": "float", "min": 40.0, "max": 50.0,   "precision": 1},
            {"kod": "procent_sa",        "label": "%SA",       "tag": "%SA",    "typ": "float", "min": 30.0, "max": 45.0,   "precision": 2},
            {"kod": "procent_nacl",      "label": "%NaCl",     "tag": "%NaCl",  "typ": "float", "min": 4.0,  "max": 8.0,    "precision": 2},
            {"kod": "procent_aa",        "label": "%AA",       "tag": "%AA",    "typ": "float", "min": 0.0,  "max": 0.5,    "precision": 2},
            {"kod": "procent_so3",       "label": "%SO3",      "tag": "%SO3",   "typ": "float", "min": 0.0,  "max": 0.03,   "precision": 3},
            {"kod": "procent_h2o2",      "label": "%H2O2",     "tag": "%H2O2",  "typ": "float", "min": 0.0,  "max": 0.01,   "precision": 3},
            {"kod": "le_liczba_kwasowa", "label": "LK=",       "tag": "LK",     "typ": "float", "min": 1.0,  "max": 10.0,   "precision": 2},
            {"kod": "barwa_fau",         "label": "Barwa FAU", "tag": "FAU",    "typ": "float", "min": 0.0,  "max": 200.0,  "precision": 0},
            {"kod": "barwa_hz",          "label": "Barwa Hz",  "tag": "Hz",     "typ": "float", "min": 0.0,  "max": 100.0,  "precision": 0},
        ]
    },
}

# ---------------------------------------------------------------------------
# Products: (produkt, nr_aparatu)
# ---------------------------------------------------------------------------

PRODUCTS = [
    ("Chegina_K7",       "T121"),
    ("Chegina_K40GL",    "T111"),
    ("Chegina_K40GLO",   "T118"),
    ("Chegina_K40GLOL",  "T118"),
]

# ---------------------------------------------------------------------------
# Seed users
# ---------------------------------------------------------------------------

SEED_USERS = [
    {"login": "technolog", "password": "tech123", "rola": "technolog", "imie_nazwisko": "Jan Technolog"},
    {"login": "laborant",  "password": "lab123",  "rola": "laborant",  "imie_nazwisko": "Anna Laborant"},
]


def seed():
    db = get_db()
    try:
        init_mbr_tables(db)
        now = datetime.now().isoformat(timespec="seconds")

        # --- Users ---
        for u in SEED_USERS:
            exists = db.execute(
                "SELECT 1 FROM mbr_users WHERE login = ?", (u["login"],)
            ).fetchone()
            if not exists:
                create_user(db, u["login"], u["password"], u["rola"], u["imie_nazwisko"])
                print(f"  + user: {u['login']} ({u['rola']})")
            else:
                print(f"  . user: {u['login']} already exists")

        # --- MBR templates ---
        etapy_json = json.dumps(ETAPY, ensure_ascii=False)
        parametry_json = json.dumps(PARAMETRY_LAB, ensure_ascii=False)

        for produkt, nr_aparatu in PRODUCTS:
            exists = db.execute(
                "SELECT 1 FROM mbr_templates WHERE produkt = ? AND wersja = 1",
                (produkt,),
            ).fetchone()
            if exists:
                print(f"  . MBR: {produkt} v1 already exists")
                continue

            notatki = json.dumps({"nr_aparatu": nr_aparatu}, ensure_ascii=False)
            db.execute(
                """INSERT INTO mbr_templates
                   (produkt, wersja, status, etapy_json, parametry_lab,
                    utworzony_przez, dt_utworzenia, dt_aktywacji, notatki)
                   VALUES (?, 1, 'active', ?, ?, 'seed', ?, ?, ?)""",
                (produkt, etapy_json, parametry_json, now, now, notatki),
            )
            print(f"  + MBR: {produkt} v1 (active)")

        db.commit()
        print("Seed complete.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
