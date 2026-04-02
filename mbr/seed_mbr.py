"""
seed_mbr.py — Create MBR templates for ALL factory products + 2 seed users.

Run once:  python -m mbr.seed_mbr
Idempotent: skips products that already exist.
"""

import json
from datetime import datetime

from mbr.models import get_db, init_mbr_tables, create_user

# ---------------------------------------------------------------------------
# Etapy definitions
# ---------------------------------------------------------------------------

ETAPY_FULL = [
    {"nr": 1, "nazwa": "Amidowanie",                 "read_only": True},
    {"nr": 2, "nazwa": "Wytworzenie SMCA",           "read_only": True},
    {"nr": 3, "nazwa": "Czwartorzędowanie",           "read_only": True},
    {"nr": 4, "nazwa": "Analiza przed standaryzacją", "read_only": False, "sekcja_lab": "przed_standaryzacja"},
    {"nr": 5, "nazwa": "Standaryzacja",               "read_only": True},
    {"nr": 6, "nazwa": "Analiza końcowa",             "read_only": False, "sekcja_lab": "analiza_koncowa"},
    {"nr": 7, "nazwa": "Przepompowanie",              "read_only": True},
]

ETAPY_SIMPLE = [
    {"nr": 1, "nazwa": "Analiza końcowa",  "read_only": False, "sekcja_lab": "analiza_koncowa"},
    {"nr": 2, "nazwa": "Przepompowanie",   "instrukcja": "Przepompować produkt do zbiornika.", "read_only": True},
]

# ---------------------------------------------------------------------------
# Helper to build pola entries
# ---------------------------------------------------------------------------

def _pole(kod, label, tag, mn, mx, precision=2):
    return {"kod": kod, "label": label, "tag": tag, "typ": "float", "min": mn, "max": mx, "precision": precision}

def _nastaw():
    return {"kod": "nastaw", "label": "Nastaw", "tag": "nastaw", "typ": "float", "min": 0, "max": 9999, "precision": 0}

# ---------------------------------------------------------------------------
# GRUPA 1: Original 4 Chegina betaines (2 lab sections)
# ---------------------------------------------------------------------------

PRODUCTS = [
    # ===== GRUPA 1: Chegina betainy (ETAPY_FULL, 2 sekcje lab) =====
    {
        "produkt": "Chegina_K40GL",
        "template_id": "T111",
        "etapy": ETAPY_FULL,
        "parametry_lab": {
            "przed_standaryzacja": {
                "label": "Analiza przed standaryzacją",
                "pola": [
                    _pole("ph_10proc",   "pH 10%",    "ph_10proc",  4.0,   6.0,   2),
                    _pole("nd20",        "nd20",       "nd20",       1.39,  1.42,  3),
                    _pole("so3",         "%SO3",       "so3",        0,     0.030, 3),
                    _pole("barwa_fau",   "Barwa FAU",  "barwa_fau",  0,     200,   0),
                ],
            },
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("sm",          "S.Masa",     "sm",         44,    48,    1),
                    _pole("nacl",        "NaCl",       "nacl",       5.8,   7.3,   2),
                    _pole("ph_10proc",   "pH 10%",     "ph_10proc",  4.5,   5.5,   2),
                    _pole("sa",          "%SA",         "sa",         37,    42,    2),
                    _pole("aa",          "%AA",         "aa",         0,     0.5,   2),
                    _pole("barwa_fau",   "Barwa FAU",   "barwa_fau",  0,     200,   0),
                    _pole("barwa_hz",    "Barwa Hz",    "barwa_hz",   0,     100,   0),
                    _pole("so3",         "SO3",         "so3",        0,     0.030, 3),
                    _nastaw(),
                ],
            },
        },
    },
    {
        "produkt": "Chegina_K40GLO",
        "template_id": "T118",
        "etapy": ETAPY_FULL,
        "parametry_lab": {
            "przed_standaryzacja": {
                "label": "Analiza przed standaryzacją",
                "pola": [
                    _pole("ph_10proc",   "pH 10%",    "ph_10proc",  4.0,   7.0,   2),
                    _pole("nd20",        "nd20",       "nd20",       1.39,  1.42,  3),
                    _pole("so3",         "%SO3",       "so3",        0,     0.030, 3),
                    _pole("barwa_fau",   "Barwa FAU",  "barwa_fau",  0,     200,   0),
                ],
            },
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("sm",          "S.Masa",     "sm",         44,    48,    1),
                    _pole("nacl",        "NaCl",       "nacl",       5.8,   7.3,   2),
                    _pole("ph_10proc",   "pH 10%",     "ph_10proc",  5.0,   7.0,   2),
                    _pole("sa",          "%SA",         "sa",         37,    9999,  2),  # min 37%
                    _pole("aa",          "%AA",         "aa",         0,     0.5,   2),
                    _pole("gestosc",     "gęstość",     "gestosc",    1.05,  1.09,  3),
                    _pole("barwa_fau",   "Barwa FAU",   "barwa_fau",  0,     200,   0),
                    _pole("so3",         "SO3",         "so3",        0,     0.030, 3),
                    _nastaw(),
                ],
            },
        },
    },
    {
        "produkt": "Chegina_K40GLOL",
        "template_id": "T118",
        "etapy": ETAPY_FULL,
        "parametry_lab": {
            "przed_standaryzacja": {
                "label": "Analiza przed standaryzacją",
                "pola": [
                    _pole("ph_10proc",   "pH 10%",    "ph_10proc",  4.0,   7.0,   2),
                    _pole("nd20",        "nd20",       "nd20",       1.39,  1.42,  3),
                    _pole("so3",         "%SO3",       "so3",        0,     0.030, 3),
                    _pole("barwa_fau",   "Barwa FAU",  "barwa_fau",  0,     200,   0),
                ],
            },
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("sm",          "S.Masa",     "sm",         44,    9999,  1),  # min 44.0%
                    _pole("nacl",        "NaCl",       "nacl",       5.8,   7.3,   2),
                    _pole("ph_10proc",   "pH 10%",     "ph_10proc",  4.5,   6.5,   2),
                    _pole("sa",          "%SA",         "sa",         36,    42,    2),
                    _pole("aa",          "%AA",         "aa",         0,     0.3,   2),
                    _pole("h2o2",        "%H2O2",       "h2o2",       0,     0.010, 3),
                    _pole("so3",         "SO3",         "so3",        0,     0.030, 3),
                    _pole("barwa_fau",   "Barwa FAU",   "barwa_fau",  0,     200,   0),
                    _nastaw(),
                ],
            },
        },
    },
    {
        "produkt": "Chegina_K7",
        "template_id": "T121",
        "etapy": ETAPY_FULL,
        "parametry_lab": {
            "przed_standaryzacja": {
                "label": "Analiza przed standaryzacją",
                "pola": [
                    _pole("ph_10proc",   "pH 10%",    "ph_10proc",  4.0,   6.0,   2),
                    _pole("nd20",        "nd20",       "nd20",       1.39,  1.42,  3),
                    _pole("so3",         "%SO3",       "so3",        0,     0.030, 3),
                    _pole("barwa_fau",   "Barwa FAU",  "barwa_fau",  0,     200,   0),
                ],
            },
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("sm",          "S.Masa",     "sm",         40,    48,    1),
                    _pole("nacl",        "NaCl",       "nacl",       4.0,   8.0,   2),
                    _pole("ph_10proc",   "pH 10%",     "ph_10proc",  4.0,   6.0,   2),
                    _pole("nd20",        "nd20",       "nd20",       1.39,  1.42,  3),
                    _pole("sa",          "%SA",         "sa",         30,    42,    2),
                    _pole("barwa_fau",   "Barwa FAU",   "barwa_fau",  0,     200,   0),
                    _pole("barwa_hz",    "Barwa Hz",    "barwa_hz",   0,     100,   0),
                    _nastaw(),
                ],
            },
        },
    },

    # ===== GRUPA 2: Pozostałe Cheginy (ETAPY_SIMPLE, 1 sekcja) =====
    {
        "produkt": "Chegina_K40GLOS",
        "template_id": "P834",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("sm",          "SM",         "sm",         44.8,  9999,  1),  # min 44.8%
                    _pole("nacl",        "NaCl",       "nacl",       5.8,   7.3,   2),
                    _pole("ph_10proc",   "pH 10%",     "ph_10proc",  4.5,   6.5,   2),
                    _pole("sa",          "%SA",         "sa",         36,    42,    2),
                    _pole("aa",          "%AA",         "aa",         0,     0.5,   2),
                    _pole("barwa_fau",   "Barwa FAU",   "barwa_fau",  0,     200,   0),
                    _nastaw(),
                ],
            },
        },
    },
    {
        "produkt": "Chegina_K40GLOL_HQ",
        "template_id": "P833",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("sm",          "SM",              "sm",         44,    9999,  1),  # min 44.0%
                    _pole("woda",        "zawartość wody",  "woda",       52,    56,    1),
                    _pole("nacl",        "NaCl",            "nacl",       5.8,   7.3,   2),
                    _pole("ph_10proc",   "pH 10%",          "ph_10proc",  4.5,   6.5,   2),
                    _pole("sa",          "%SA",              "sa",         36,    42,    2),
                    _pole("so3",         "SO3",              "so3",        0,     0.030, 3),
                    _pole("barwa_fau",   "Barwa FAU",        "barwa_fau",  0,     200,   0),
                    _nastaw(),
                ],
            },
        },
    },
    {
        "produkt": "Chegina_K7GLO",
        "template_id": None,
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("sm",          "SM",         "sm",         40,    48,    1),
                    _pole("nacl",        "NaCl",       "nacl",       4.0,   8.0,   2),
                    _pole("ph_10proc",   "pH 10%",     "ph_10proc",  4.0,   7.0,   2),
                    _pole("nd20",        "nd20",       "nd20",       1.39,  1.42,  3),
                    _pole("sa",          "%SA",         "sa",         30,    42,    2),
                    _pole("barwa_fau",   "Barwa FAU",   "barwa_fau",  0,     200,   0),
                    _nastaw(),
                ],
            },
        },
    },
    {
        "produkt": "Chegina_K7B",
        "template_id": None,
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("woda",        "%H2O",       "woda",       52,    64,    1),
                    _pole("sa",          "%SA",         "sa",         29.0,  31.0,  2),
                    _pole("nacl",        "NaCl",       "nacl",       0,     5.5,   2),  # max 5.5
                    _pole("sm",          "SM",         "sm",         36,    38,    1),
                    _pole("nd20",        "nd20",       "nd20",       1.39,  1.42,  3),
                ],
            },
        },
    },
    {
        "produkt": "Chegina_KK",
        "template_id": "P818",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("sm",          "SM",         "sm",         40,    48,    1),
                    _pole("nacl",        "NaCl",       "nacl",       4.0,   8.0,   2),
                    _pole("ph_10proc",   "pH 10%",     "ph_10proc",  4.0,   6.0,   2),
                    _pole("nd20",        "nd20",       "nd20",       1.39,  1.42,  3),
                    _pole("sa",          "%SA",         "sa",         30,    42,    2),
                    _pole("aa",          "%AA",         "aa",         0,     0.5,   2),
                    _pole("barwa_fau",   "Barwa FAU",   "barwa_fau",  0,     200,   0),
                    _nastaw(),
                ],
            },
        },
    },
    {
        "produkt": "Chegina_CC",
        "template_id": None,
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("woda",          "zaw.wody",        "woda",          60.0,  64.0,  1),
                    _pole("nacl",          "NaCl",            "nacl",          4.0,   8.0,   2),
                    _pole("sa",            "%SA",              "sa",            29,    33,    2),
                    _pole("alkalicznosc",  "alkaliczność",     "alkalicznosc",  1.15,  1.30,  2),
                    _pole("sm",            "SM",              "sm",            36.0,  40.0,  1),
                    _pole("wolna_amina",   "wolna amina",     "wolna_amina",   0,     0.4,   2),
                    _pole("la",            "L.aminowa",       "la",            0,     1.0,   2),
                    _pole("lk",            "L.kwasowa",       "lk",            0,     1.0,   2),
                    _pole("nd20",          "nd20",            "nd20",          1.39,  1.42,  3),
                    _nastaw(),
                ],
            },
        },
    },
    {
        "produkt": "Chegina_CCR",
        "template_id": None,
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("sm",            "SM",            "sm",           36.0,  40.0,  1),
                    _pole("sa",            "%SA",            "sa",           29,    31.5,  2),
                    _pole("wolna_amina",   "wolna amina",   "wolna_amina",  0,     1.0,   2),
                    _pole("nacl",          "NaCl",          "nacl",         4.0,   8.0,   2),
                    _nastaw(),
                ],
            },
        },
    },
    {
        "produkt": "Chegina_L9",
        "template_id": "P817",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("lk",     "LK",     "lk",    0,     4.0,   2),
                    _pole("nacl",   "NaCl",   "nacl",  4.0,   8.0,   2),
                    _pole("nd20",   "nd20",   "nd20",  1.39,  1.42,  3),
                    _pole("sa",     "%SA",     "sa",    28.0,  31.0,  2),
                ],
            },
        },
    },
    {
        "produkt": "Chegina",
        "template_id": "P810",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("nacl",        "NaCl",       "nacl",       4.0,   8.0,   2),
                    _pole("barwa_fau",   "barwa",      "barwa_fau",  0,     200,   0),
                    _pole("sa",          "%SA",         "sa",         30,    42,    2),
                ],
            },
        },
    },

    # ===== GRUPA 3: Cheminoxy =====
    {
        "produkt": "Cheminox_K",
        "template_id": "P822",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("sm",          "SM",         "sm",         32.8,  9999,  1),  # min 32.8%
                    _pole("ph_10proc",   "pH 10%",     "ph_10proc",  5,     8,     2),
                    _pole("h2o2",        "%H2O2",      "h2o2",       0,     0.010, 3),
                    _pole("barwa_fau",   "barwa",      "barwa_fau",  0,     2,     0),
                    _pole("nd20",        "nd20",       "nd20",       1.39,  1.42,  3),
                    _pole("gestosc",     "gęstość",    "gestosc",    0.99,  1.00,  3),
                ],
            },
        },
    },
    {
        "produkt": "Cheminox_K35",
        "template_id": "P835",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("sm",          "SM",         "sm",         34,    9999,  1),  # min 34%
                    _pole("ph_10proc",   "pH 10%",     "ph_10proc",  5,     8,     2),
                    _pole("h2o2",        "%H2O2",      "h2o2",       0,     0.010, 3),
                    _pole("barwa_fau",   "barwa",      "barwa_fau",  0,     2,     0),
                    _pole("nd20",        "nd20",       "nd20",       1.39,  1.42,  3),
                    _pole("gestosc",     "gęstość",    "gestosc",    0.99,  1.00,  3),
                ],
            },
        },
    },
    {
        "produkt": "Cheminox_LA",
        "template_id": "P823",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("tlenek_aminowy", "zaw.tlenku aminowego", "tlenek_aminowy", 28,  32,    1),
                    _pole("ph_10proc",      "pH 10%",               "ph_10proc",      6,   8,     2),
                    _pole("h2o2",           "%H2O2",                "h2o2",            0,   0.010, 3),
                    _pole("barwa_fau",      "barwa",                "barwa_fau",       0,   1,     0),
                    _pole("wolna_amina",    "wolna amina",          "wolna_amina",     0,   0.5,   2),
                    _pole("nd20",           "nd20",                 "nd20",            1.39, 1.42, 3),
                ],
            },
        },
    },

    # ===== GRUPA 4: Chemipole =====
    {
        "produkt": "Chemipol_ML",
        "template_id": None,
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("sm",          "SM",              "sm",          40,   9999, 1),  # min 40%
                    _pole("lk",          "LK",              "lk",          0,    6,    2),
                    _pole("siarczynow",  "zaw.siarczynów",  "siarczynow",  0,    0.1,  3),
                    _pole("h2o2",        "H2O2",            "h2o2",        0,    0.15, 3),
                    _pole("sa",          "%SA",              "sa",          26,   9999, 2),  # min 26%
                    _pole("barwa_fau",   "barwa",           "barwa_fau",   0,    10,   0),
                ],
            },
        },
    },
    {
        "produkt": "Chemipol_OL",
        "template_id": "P812",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("sm",          "SM",              "sm",          38,   42,   1),
                    _pole("siarczynow",  "zaw.siarczynów",  "siarczynow",  0,    0.1,  3),
                    _pole("ph_10proc",   "pH 10%",          "ph_10proc",   5.5,  7,    2),
                    _pole("sa",          "%SA",              "sa",          31,   9999, 2),  # min 31%
                    _pole("barwa_fau",   "barwa",           "barwa_fau",   0,    5,    0),
                    _pole("lk",          "LK",              "lk",          0,    8,    2),
                    _pole("nd20",        "nd20",            "nd20",        1.39, 1.42, 3),
                ],
            },
        },
    },

    # ===== GRUPA 5: Monamidy =====
    {
        "produkt": "Monamid_KO",
        "template_id": "P833",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("barwa_fau",   "barwa",       "barwa_fau",  0,    6,    0),
                    _pole("wkt",         "%WKT",        "wkt",        0,    0.5,  2),
                    _pole("lk",          "LK",          "lk",         0,    1.4,  2),
                    _pole("mea",         "%MEA",        "mea",        0,    1.5,  2),
                    _pole("estry",       "%estry",      "estry",      0,    6,    2),
                    _pole("gliceryny",   "%gliceryny",  "gliceryny",  0,    10,   2),
                ],
            },
        },
    },
    {
        "produkt": "Monamid_KO_Revada",
        "template_id": "P833",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("barwa_fau",   "barwa",          "barwa_fau",  0,    8,    0),
                    _pole("wkt",         "%WKT",           "wkt",        0,    10,   2),
                    _pole("mea",         "%MEA",           "mea",        0,    5,    2),
                    _pole("estry",       "%estry",         "estry",      0,    10,   2),
                    _pole("gliceryny",   "%gliceryny",     "gliceryny",  0,    10,   2),
                    _pole("t_topn",      "T.topnienia",    "t_topn",     45,   70,   1),
                ],
            },
        },
    },
    {
        "produkt": "Monamid_K",
        "template_id": "P824",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("barwa_fau",   "barwa",          "barwa_fau",  0,     4,    0),
                    _pole("wkt",         "%WKT",           "wkt",        0,     0.5,  2),
                    _pole("mea",         "%MEA",           "mea",        0.3,   1.3,  2),
                    _pole("estry",       "estry",          "estry",      0,     6,    2),
                    _pole("lz",          "L.zmydlenia",    "lz",         0,     999,  2),
                    _pole("t_kropl",     "T.kroplenia",    "t_kropl",    45,    70,   1),
                ],
            },
        },
    },
    {
        "produkt": "Monamid_L",
        "template_id": "P814",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("lk",          "LK",             "lk",         0,     10,   2),
                    _pole("la",          "L.aminowa",      "la",         0,     200,  2),
                    _pole("wkt",         "%WKT",           "wkt",        0,     2.0,  2),
                    _pole("mea",         "%MEA",           "mea",        0,     2.0,  2),
                    _pole("t_kropl",     "T.kroplenia",    "t_kropl",    45,    70,   1),
                ],
            },
        },
    },
    {
        "produkt": "Monamid_S",
        "template_id": "P813",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("lk",          "LK",             "lk",         0,     5,    2),
                    _pole("wolna_amina", "wolna amina",    "wolna_amina", 0,    3,    2),
                    _pole("t_kropl",     "T.kroplenia",    "t_kropl",    85,    92,   1),
                    _pole("barwa_fau",   "barwa",          "barwa_fau",  0,     5,    0),
                ],
            },
        },
    },

    # ===== GRUPA 6: Distery i Monestery =====
    {
        "produkt": "Dister_E",
        "template_id": "P805",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("lk",          "LK",              "lk",    0,     6,    2),
                    _pole("wge",         "WGE",             "wge",   0,     100,  2),
                    _pole("lh",          "L.hydroksylowa",  "lh",    0,     54,   2),
                    _pole("lz",          "L.zmydlenia",     "lz",    188,   200,  2),
                    _pole("t_kropl",     "T.kroplenia",     "t_kropl", 58,  64,   1),
                    _pole("wkt",         "WKT",             "wkt",   0,     5,    2),
                ],
            },
        },
    },
    {
        "produkt": "Monester_O",
        "template_id": None,
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("lk",          "LK",              "lk",         0,     3,    2),
                    _pole("lz",          "L.zmydlenia",     "lz",         150,   170,  2),
                    _pole("li",          "L.jodowa",        "li",         63,    83,   2),
                    _pole("monoestry",   "zaw.monoestrów",  "monoestry",  30,    9999, 2),  # min 30%
                    _pole("barwa_fau",   "barwa",           "barwa_fau",  0,     10,   0),
                ],
            },
        },
    },
    {
        "produkt": "Monester_S",
        "template_id": None,
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("lk",             "LK",              "lk",             0,     3,    2),
                    _pole("t_kropl",        "T.kroplenia",     "t_kropl",        54,    60,   1),
                    _pole("lz",             "L.zmydlenia",     "lz",             145,   185,  2),
                    _pole("li",             "L.jodowa",        "li",             0,     5,    2),
                    _pole("gliceryny",      "%gliceryny",      "gliceryny",      0,     10,   2),
                    _pole("monoglicerydy",  "%monoglicerydów", "monoglicerydy",  0,     100,  2),
                    _pole("barwa_fau",      "barwa",           "barwa_fau",      0,     10,   0),
                ],
            },
        },
    },

    # ===== GRUPA 7: Alkinole i Alstermidy =====
    {
        "produkt": "Alkinol",
        "template_id": None,
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("barwa_fau",   "barwa",           "barwa_fau",  0,     2,    0),
                    _pole("lk",          "LK",              "lk",         0,     2,    2),
                    _pole("lz",          "L.zmydlenia",     "lz",         0,     2,    2),
                    _pole("t_kropl",     "T.kroplenia",     "t_kropl",    47,    55,   1),
                    _pole("lh",          "L.hydroksylowa",  "lh",         0,     300,  2),
                    _pole("li",          "L.jodowa",        "li",         0,     2,    2),
                ],
            },
        },
    },
    {
        "produkt": "Alstermid_K",
        "template_id": "P807",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("lk",          "LK",          "lk",         0,     4,    2),
                    _pole("wkt",         "WKT",         "wkt",        0,     5,    2),
                    _pole("la",          "L.aminowa",   "la",         165,   185,  2),
                    _pole("barwa_fau",   "barwa",       "barwa_fau",  0,     4,    0),
                ],
            },
        },
    },
    {
        "produkt": "Alstermid",
        "template_id": "P806",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("barwa_fau",   "barwa",          "barwa_fau",  0,     10,   0),
                    _pole("lk",          "LK",             "lk",         0,     15,   2),
                    _pole("la",          "L.aminowa",      "la",         130,   160,  2),
                    _pole("wkt",         "WKT",            "wkt",        0,     8,    2),
                    _pole("t_kropl",     "T.kroplenia",    "t_kropl",    45,    70,   1),
                ],
            },
        },
    },

    # ===== GRUPA 8: Chemale =====
    {
        "produkt": "Chemal_CS3070",
        "template_id": None,
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("lk",          "LK",              "lk",    0,     0.2,  2),
                    _pole("lz",          "L.zmydlenia",     "lz",    0,     1.2,  2),
                    _pole("li",          "L.jodowa",        "li",    0,     1.0,  2),
                    _pole("barwa_fau",   "barwa",           "barwa_fau", 0, 10,   0),
                    _pole("nd20",        "nd20",            "nd20",  1.39,  1.50, 3),
                    _pole("lh",          "L.hydroksylowa",  "lh",    210,   220,  2),
                ],
            },
        },
    },
    {
        "produkt": "Chemal_EO20",
        "template_id": "P602",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("lh",          "L.hydroksylowa",  "lh",         45,    55,   2),
                    _pole("ph_10proc",   "pH 1%",           "ph_10proc",  5,     7,    2),
                    _pole("nd20",        "nd20",            "nd20",       1.39,  1.50, 3),
                ],
            },
        },
    },
    {
        "produkt": "Chemal_SE12",
        "template_id": None,
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("lk",          "LK",              "lk",         0,     20,   2),
                    _pole("lz",          "L.zmydlenia",     "lz",         90,    100,  2),
                    _pole("lh",          "L.hydroksylowa",  "lh",         145,   160,  2),
                    _pole("ph_10proc",   "pH 20%",          "ph_10proc",  5,     8,    2),
                    _pole("t_topn",      "T.topnienia",     "t_topn",     49,    52,   1),
                ],
            },
        },
    },
    {
        "produkt": "Chemal_PC",
        "template_id": None,
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("lk",   "LK",           "lk",  0,    4,    2),
                    _pole("lz",   "L.zmydlenia",  "lz",  90,   120,  2),
                ],
            },
        },
    },

    # ===== GRUPA 9: Inne =====
    {
        "produkt": "Polcet_A",
        "template_id": None,
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("lk",          "LK",           "lk",        0,      2,     2),
                    _pole("gestosc",     "gęstość",      "gestosc",   0.960,  0.970, 3),
                    _pole("barwa_fau",   "barwa",        "barwa_fau", 0,      2,     0),
                    _pole("lz",          "L.zmydlenia",  "lz",        410,    450,   2),
                ],
            },
        },
    },
    {
        "produkt": "Chelamid_DK",
        "template_id": None,
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("dietanolamina", "%dietanolaminy", "dietanolamina", 80,  9999, 1),  # min 80%
                    _pole("gliceryny",     "%gliceryny",     "gliceryny",     0,   9.5,  2),
                ],
            },
        },
    },
    {
        "produkt": "Glikoster_P",
        "template_id": "P804",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("lk",           "LK",              "lk",          0,    3,    2),
                    _pole("wolny_glikol", "wolny glikol",    "wolny_glikol", 0,   3,    2),
                    _pole("lh",           "L.hydroksylowa",  "lh",          70,   130,  2),
                    _pole("monoestry",    "monoestry",       "monoestry",   47,   55,   2),
                ],
            },
        },
    },
    {
        "produkt": "Citrowax",
        "template_id": "P808",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("lk",       "LK",           "lk",      0,    1,    2),
                    _pole("t_kropl",  "T.kroplenia",  "t_kropl", 48,   52,   1),
                ],
            },
        },
    },
    {
        "produkt": "Kwas_stearynowy",
        "template_id": "P603",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("lk",       "LK",              "lk",       208,   212,  2),
                    _pole("t_krzep",  "T.krzepnięcia",   "t_krzep",  54,    56,   1),
                    _pole("li",       "L.jodowa",        "li",       0,     1,    2),
                ],
            },
        },
    },
    {
        "produkt": "Perlico_45",
        "template_id": None,
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("sm",          "SM",      "sm",         43,   9999, 1),  # min 43%
                    _pole("ph_10proc",   "pH 10%",  "ph_10proc",  5,    8,    2),
                ],
            },
        },
    },
    {
        "produkt": "SLES",
        "template_id": "P834",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("barwa_fau",   "barwa",   "barwa_fau",  0,     2,    0),
                    _pole("sa",          "%SA",      "sa",         25,    28,   2),
                    _pole("ph_10proc",   "pH 3%",   "ph_10proc",  6.5,   7.5,  2),
                ],
            },
        },
    },
    {
        "produkt": "HSH_CS3070",
        "template_id": None,
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _pole("lh",          "L.hydroksylowa",  "lh",        210,   220,  2),
                    _pole("lk",          "LK",              "lk",        0,     0.1,  2),
                    _pole("lz",          "L.zmydlenia",     "lz",        0,     1.0,  2),
                    _pole("li",          "L.jodowa",        "li",        0,     1.0,  2),
                    _pole("nd20",        "nd20",            "nd20",      1.39,  1.50, 3),
                ],
            },
        },
    },
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
        created = 0
        skipped = 0
        for prod in PRODUCTS:
            produkt = prod["produkt"]
            exists = db.execute(
                "SELECT 1 FROM mbr_templates WHERE produkt = ? AND wersja = 1",
                (produkt,),
            ).fetchone()
            if exists:
                print(f"  . MBR: {produkt} v1 already exists")
                skipped += 1
                continue

            etapy_json = json.dumps(prod["etapy"], ensure_ascii=False)
            parametry_json = json.dumps(prod["parametry_lab"], ensure_ascii=False)
            notatki = json.dumps(
                {"nr_aparatu": prod["template_id"]} if prod["template_id"] else {},
                ensure_ascii=False,
            )
            db.execute(
                """INSERT INTO mbr_templates
                   (produkt, wersja, status, etapy_json, parametry_lab,
                    utworzony_przez, dt_utworzenia, dt_aktywacji, notatki)
                   VALUES (?, 1, 'active', ?, ?, 'seed', ?, ?, ?)""",
                (produkt, etapy_json, parametry_json, now, now, notatki),
            )
            print(f"  + MBR: {produkt} v1 (active)")
            created += 1

        db.commit()
        print(f"\nSeed complete: {created} created, {skipped} skipped.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
