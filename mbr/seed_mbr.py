"""
seed_mbr.py — Create MBR templates for ALL factory products + 2 seed users.

Run once:  python -m mbr.seed_mbr
Update:    python -m mbr.seed_mbr --update   (updates parametry_lab in existing templates)
Idempotent: skips products that already exist (unless --update).
"""

import json
import sys
from datetime import datetime

from mbr.models import get_db, init_mbr_tables, create_user

# ---------------------------------------------------------------------------
# Etapy definitions
# ---------------------------------------------------------------------------

ETAPY_FULL = [
    {"nr": 1, "nazwa": "Amidowanie",          "read_only": True},
    {"nr": 2, "nazwa": "Wytworzenie SMCA",    "read_only": True},
    {"nr": 3, "nazwa": "Czwartorzędowanie",    "read_only": True},
    {"nr": 4, "nazwa": "Sulfonowanie",         "read_only": True},
    {"nr": 5, "nazwa": "Utlenienie",           "read_only": True},
    {"nr": 6, "nazwa": "Standaryzacja",        "read_only": False, "sekcja_lab": "standaryzacja"},
    {"nr": 7, "nazwa": "Analiza końcowa",      "read_only": False, "sekcja_lab": "analiza_koncowa"},
    {"nr": 8, "nazwa": "Przepompowanie",       "read_only": True},
]

# K40GLOL/GLOS/GLN have extra Rozjaśnianie (bleaching) stage
ETAPY_FULL_GLOL = [
    {"nr": 1, "nazwa": "Amidowanie",          "read_only": True},
    {"nr": 2, "nazwa": "Wytworzenie SMCA",    "read_only": True},
    {"nr": 3, "nazwa": "Czwartorzędowanie",    "read_only": True},
    {"nr": 4, "nazwa": "Sulfonowanie",         "read_only": True},
    {"nr": 5, "nazwa": "Utlenienie",           "read_only": True},
    {"nr": 6, "nazwa": "Rozjaśnianie",         "read_only": True},
    {"nr": 7, "nazwa": "Standaryzacja",        "read_only": False, "sekcja_lab": "standaryzacja"},
    {"nr": 8, "nazwa": "Analiza końcowa",      "read_only": False, "sekcja_lab": "analiza_koncowa"},
    {"nr": 9, "nazwa": "Przepompowanie",       "read_only": True},
]

ETAPY_SIMPLE = [
    {"nr": 1, "nazwa": "Analiza końcowa",  "read_only": False, "sekcja_lab": "analiza_koncowa"},
    {"nr": 2, "nazwa": "Przepompowanie",   "instrukcja": "Przepompować produkt do zbiornika.", "read_only": True},
]

# ---------------------------------------------------------------------------
# Helper to build pola entries with measurement_type
# ---------------------------------------------------------------------------

_CALC_METHODS_CACHE = None

def _get_calc_methods():
    """Load titration methods from parametry_analityczne DB table. Cached."""
    global _CALC_METHODS_CACHE
    if _CALC_METHODS_CACHE is not None:
        return _CALC_METHODS_CACHE
    try:
        from mbr.models import get_db
        db = get_db()
        rows = db.execute(
            "SELECT kod, metoda_nazwa, metoda_formula, metoda_factor FROM parametry_analityczne WHERE typ='titracja' AND metoda_factor IS NOT NULL"
        ).fetchall()
        _CALC_METHODS_CACHE = {
            r["kod"]: {"name": r["metoda_nazwa"], "formula": r["metoda_formula"], "factor": r["metoda_factor"]}
            for r in rows
        }
    except Exception:
        _CALC_METHODS_CACHE = {}
    return _CALC_METHODS_CACHE

_TITR_TBD = {"name": "Do uzupełnienia", "formula": "TBD", "factor": 1.0}


def _bezp(kod, label, tag, mn, mx, precision=2):
    """Direct instrument reading (bezposredni)."""
    return {"kod": kod, "label": label, "tag": tag, "typ": "float",
            "min": mn, "max": mx, "precision": precision,
            "measurement_type": "bezposredni"}


def _titr(kod, label, tag, mn, mx, precision=2, suggested_mass=None):
    """Titration parameter (titracja). Uses known calc_method or TBD placeholder."""
    cm = dict(_get_calc_methods().get(kod, _TITR_TBD))
    if suggested_mass is not None:
        cm["suggested_mass"] = suggested_mass
    entry = {"kod": kod, "label": label, "tag": tag, "typ": "float",
             "min": mn, "max": mx, "precision": precision,
             "measurement_type": "titracja",
             "calc_method": cm}
    return entry


def _obl(kod, label, tag, mn, mx, precision=2, formula=""):
    """Computed parameter (obliczeniowy)."""
    return {"kod": kod, "label": label, "tag": tag, "typ": "float",
            "min": mn, "max": mx, "precision": precision,
            "measurement_type": "obliczeniowy",
            "formula": formula}


def _nastaw():
    return {"kod": "nastaw", "label": "Nastaw", "tag": "nastaw", "typ": "float",
            "min": 0, "max": 9999, "precision": 0,
            "measurement_type": "bezposredni"}


def _dodatek(kod, label, tag):
    """Additive amount field (always 0-9999 kg)."""
    return {"kod": kod, "label": label, "tag": tag, "typ": "float",
            "min": 0, "max": 9999, "precision": 1,
            "measurement_type": "bezposredni"}

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
            "analiza": {
                "label": "Analiza",
                "pola": [
                    _bezp("sm",          "S.Masa",     "sm",         44,    48,    1),
                    _titr("nacl",        "NaCl",       "nacl",       5.8,   7.3,   2),
                    _bezp("ph_10proc",   "pH 10%",     "ph_10proc",  4.5,   5.5,   2),
                    _bezp("nd20",        "nd20",       "nd20",       1.39,  1.42,  3),
                    _obl("sa",           "%SA",         "sa",         37,    42,    2, "sm - nacl - 0.6"),
                    _titr("aa",          "%AA",         "aa",         0,     0.5,   2),
                    _bezp("barwa_fau",   "Barwa jodowa",   "barwa_fau",  0,     200,   0),
                    _bezp("barwa_hz",    "Barwa Hz",    "barwa_hz",   0,     100,   0),
                    _titr("so3",         "SO3",         "so3",        0,     0.030, 3),
                ],
            },
            "dodatki": {
                "label": "Dodatki standaryzacyjne",
                "pola": [
                    _dodatek("kwas_kg",  "Kwas [kg]",  "kwas_kg"),
                    _dodatek("woda_kg",  "Woda [kg]",  "woda_kg"),
                    _dodatek("nacl_kg",  "NaCl [kg]",  "nacl_kg"),
                ],
            },
        },
    },
    {
        "produkt": "Chegina_K40GLO",
        "template_id": "T118",
        "etapy": ETAPY_FULL,
        "parametry_lab": {
            "analiza": {
                "label": "Analiza",
                "pola": [
                    _bezp("sm",          "S.Masa",     "sm",         44,    48,    1),
                    _titr("nacl",        "NaCl",       "nacl",       5.8,   7.3,   2),
                    _bezp("ph_10proc",   "pH 10%",     "ph_10proc",  5.0,   7.0,   2),
                    _bezp("nd20",        "nd20",       "nd20",       1.39,  1.42,  3),
                    _obl("sa",           "%SA",         "sa",         37,    9999,  2, "sm - nacl - 0.6"),  # min 37%
                    _titr("aa",          "%AA",         "aa",         0,     0.5,   2),
                    _bezp("gestosc",     "gęstość",     "gestosc",    1.05,  1.09,  3),
                    _bezp("barwa_fau",   "Barwa jodowa",   "barwa_fau",  0,     200,   0),
                    _titr("so3",         "SO3",         "so3",        0,     0.030, 3),
                    _bezp("barwa_hz",    "Barwa Hz",    "barwa_hz",   0,     500,   0),
                ],
            },
            "dodatki": {
                "label": "Dodatki standaryzacyjne",
                "pola": [
                    _dodatek("kwas_kg",  "Kwas [kg]",  "kwas_kg"),
                    _dodatek("woda_kg",  "Woda [kg]",  "woda_kg"),
                    _dodatek("nacl_kg",  "NaCl [kg]",  "nacl_kg"),
                ],
            },
        },
    },
    {
        "produkt": "Chegina_K40GLOL",
        "template_id": "T118",
        "etapy": ETAPY_FULL_GLOL,
        "parametry_lab": {
            "analiza": {
                "label": "Analiza",
                "pola": [
                    _bezp("sm",          "S.Masa",     "sm",         44,    9999,  1),  # min 44.0%
                    _titr("nacl",        "NaCl",       "nacl",       5.8,   7.3,   2),
                    _bezp("ph_10proc",   "pH 10%",     "ph_10proc",  4.5,   6.5,   2),
                    _bezp("nd20",        "nd20",       "nd20",       1.39,  1.42,  3),
                    _obl("sa",           "%SA",         "sa",         36,    42,    2, "sm - nacl - 0.6"),
                    _titr("aa",          "%AA",         "aa",         0,     0.3,   2),
                    _titr("h2o2",        "%H2O2",       "h2o2",       0,     0.010, 3),
                    _titr("so3",         "SO3",         "so3",        0,     0.030, 3),
                    _bezp("barwa_fau",   "Barwa jodowa",   "barwa_fau",  0,     200,   0),
                    _bezp("barwa_hz",    "Barwa Hz",    "barwa_hz",   0,     500,   0),
                    _titr("wolna_amina", "%wolna amina", "wolna_amina", 0,   0.5,   2),
                    _bezp("h2o",         "H2O %",       "h2o",        50,    58,    1),
                ],
            },
            "dodatki": {
                "label": "Dodatki standaryzacyjne",
                "pola": [
                    _dodatek("kwas_kg",  "Kwas [kg]",  "kwas_kg"),
                    _dodatek("woda_kg",  "Woda [kg]",  "woda_kg"),
                    _dodatek("nacl_kg",  "NaCl [kg]",  "nacl_kg"),
                ],
            },
        },
    },
    {
        "produkt": "Chegina_K7",
        "template_id": "T121",
        "etapy": ETAPY_FULL,
        "parametry_lab": {
            "analiza": {
                "label": "Analiza",
                "pola": [
                    _bezp("sm",          "S.Masa",     "sm",         40,    48,    1),
                    _titr("nacl",        "NaCl",       "nacl",       4.0,   8.0,   2),
                    _bezp("ph_10proc",   "pH 10%",     "ph_10proc",  4.0,   6.0,   2),
                    _bezp("nd20",        "nd20",       "nd20",       1.39,  1.42,  3),
                    _obl("sa",           "%SA",         "sa",         30,    42,    2, "sm - nacl - 0.6"),
                    _bezp("barwa_fau",   "Barwa jodowa",   "barwa_fau",  0,     200,   0),
                    _bezp("barwa_hz",    "Barwa Hz",    "barwa_hz",   0,     100,   0),
                ],
            },
            "dodatki": {
                "label": "Dodatki standaryzacyjne",
                "pola": [
                    _dodatek("kwas_kg",  "Kwas [kg]",  "kwas_kg"),
                    _dodatek("woda_kg",  "Woda [kg]",  "woda_kg"),
                    _dodatek("nacl_kg",  "NaCl [kg]",  "nacl_kg"),
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
                    _bezp("sm",          "SM",         "sm",         44.8,  9999,  1),  # min 44.8%
                    _titr("nacl",        "NaCl",       "nacl",       5.8,   7.3,   2),
                    _bezp("ph_10proc",   "pH 10%",     "ph_10proc",  4.5,   6.5,   2),
                    _obl("sa",           "%SA",         "sa",         36,    42,    2, "sm - nacl - 0.6"),
                    _titr("aa",          "%AA",         "aa",         0,     0.5,   2),
                    _titr("wolna_amina", "%wolna amina", "wolna_amina", 0,   0.5,   2),
                    _bezp("barwa_fau",   "Barwa jodowa",   "barwa_fau",  0,     200,   0),
                    _bezp("barwa_hz",    "Barwa Hz",    "barwa_hz",   0,     500,   0),
                    _bezp("h2o",         "H2O %",       "h2o",        50,    58,    1),
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
                    _bezp("sm",          "SM",              "sm",         44,    9999,  1),  # min 44.0%
                    _bezp("h2o",         "zawartość wody",  "h2o",        52,    56,    1),
                    _titr("nacl",        "NaCl",            "nacl",       5.8,   7.3,   2),
                    _bezp("ph_10proc",   "pH 10%",          "ph_10proc",  4.5,   6.5,   2),
                    _obl("sa",           "%SA",              "sa",         36,    42,    2, "sm - nacl - 0.6"),
                    _titr("so3",         "SO3",              "so3",        0,     0.030, 3),
                    _bezp("barwa_fau",   "Barwa jodowa",        "barwa_fau",  0,     200,   0),
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
                    _bezp("sm",          "SM",         "sm",         40,    48,    1),
                    _titr("nacl",        "NaCl",       "nacl",       4.0,   8.0,   2),
                    _bezp("ph_10proc",   "pH 10%",     "ph_10proc",  4.0,   7.0,   2),
                    _bezp("nd20",        "nd20",       "nd20",       1.39,  1.42,  3),
                    _obl("sa",           "%SA",         "sa",         30,    42,    2, "sm - nacl - 0.6"),
                    _bezp("barwa_fau",   "Barwa jodowa",   "barwa_fau",  0,     200,   0),
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
                    _bezp("h2o",         "%H2O",       "h2o",        52,    64,    1),
                    _obl("sa",           "%SA",         "sa",         29.0,  31.0,  2, "sm - nacl - 0.6"),
                    _titr("nacl",        "NaCl",       "nacl",       0,     5.5,   2),  # max 5.5
                    _bezp("sm",          "SM",         "sm",         36,    38,    1),
                    _bezp("nd20",        "nd20",       "nd20",       1.39,  1.42,  3),
                    _bezp("barwa_hz",    "Barwa Hz",    "barwa_hz",   0,     500,   0),
                    _bezp("barwa_fau",   "Barwa jodowa",   "barwa_fau",  0,     200,   0),
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
                    _bezp("sm",          "SM",         "sm",         40,    48,    1),
                    _titr("nacl",        "NaCl",       "nacl",       4.0,   8.0,   2),
                    _bezp("ph_10proc",   "pH 10%",     "ph_10proc",  4.0,   6.0,   2),
                    _bezp("nd20",        "nd20",       "nd20",       1.39,  1.42,  3),
                    _obl("sa",           "%SA",         "sa",         30,    42,    2, "sm - nacl - 0.6"),
                    _titr("aa",          "%AA",         "aa",         0,     0.5,   2),
                    _titr("wolna_amina", "%wolna amina", "wolna_amina", 0,   0.5,   2),
                    _bezp("barwa_fau",   "Barwa jodowa",   "barwa_fau",  0,     200,   0),
                    _bezp("barwa_hz",    "Barwa Hz",    "barwa_hz",   0,     500,   0),
                    _bezp("mca",         "MCA [ppm]",   "mca",        0,     3000,  0),
                    _bezp("dca",         "DCA [ppm]",   "dca",        0,     400,   0),
                    _bezp("dmapa",       "DMAPA [ppm]", "dmapa",      0,     100,   0),
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
                    _bezp("h2o",           "zaw.wody",        "h2o",           60.0,  64.0,  1),
                    _titr("nacl",          "NaCl",            "nacl",          4.0,   8.0,   2),
                    _obl("sa",             "%SA",              "sa",            29,    33,    2, "sm - nacl - 0.6"),
                    _titr("alkalicznosc",  "alkaliczność",     "alkalicznosc",  1.15,  1.30,  2),
                    _bezp("sm",            "SM",              "sm",            36.0,  40.0,  1),
                    _titr("wolna_amina",   "wolna amina",     "wolna_amina",   0,     0.4,   2),
                    _titr("la",            "L.aminowa",       "la",            0,     1.0,   2),
                    _titr("lk",            "L.kwasowa",       "lk",            0,     1.0,   2),
                    _bezp("nd20",          "nd20",            "nd20",          1.39,  1.42,  3),
                    _bezp("barwa_hz",      "Barwa Hz",        "barwa_hz",      0,     500,   0),
                    _bezp("barwa_fau",     "Barwa jodowa",           "barwa_fau",     0,     10,    0),
                    _bezp("ph_10proc",     "pH 5%",           "ph_10proc",     6.0,   8.0,   2),
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
                    _bezp("sm",            "SM",            "sm",           36.0,  40.0,  1),
                    _obl("sa",             "%SA",            "sa",           29,    31.5,  2, "sm - nacl - 0.6"),
                    _titr("wolna_amina",   "wolna amina",   "wolna_amina",  0,     1.0,   2),
                    _titr("nacl",          "NaCl",          "nacl",         4.0,   8.0,   2),
                    _bezp("barwa_hz",      "Barwa Hz",      "barwa_hz",     0,     500,   0),
                    _bezp("barwa_fau",     "Barwa jodowa",         "barwa_fau",    0,     10,    0),
                    _bezp("ph_10proc",     "pH 5%",         "ph_10proc",    6.0,   8.0,   2),
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
                    _titr("lk",     "LK",     "lk",    0,     4.0,   2),
                    _titr("nacl",   "NaCl",   "nacl",  4.0,   8.0,   2),
                    _bezp("nd20",   "nd20",   "nd20",  1.39,  1.42,  3),
                    _obl("sa",      "%SA",     "sa",    28.0,  31.0,  2, "sm - nacl - 0.6"),
                    _bezp("barwa_fau", "Barwa jodowa", "barwa_fau", 0, 10, 0),
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
                    _titr("nacl",        "NaCl",       "nacl",       4.0,   8.0,   2),
                    _bezp("barwa_fau",   "Barwa jodowa",      "barwa_fau",  0,     200,   0),
                    _obl("sa",           "%SA",         "sa",         30,    42,    2, "sm - nacl - 0.6"),
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
                    _bezp("sm",          "SM",         "sm",         32.8,  9999,  1),  # min 32.8%
                    _bezp("ph_10proc",   "pH 10%",     "ph_10proc",  5,     8,     2),
                    _titr("h2o2",        "%H2O2",      "h2o2",       0,     0.010, 3),
                    _bezp("barwa_fau",   "Barwa jodowa",      "barwa_fau",  0,     2,     0),
                    _bezp("barwa_hz",    "Barwa Hz",   "barwa_hz",   0,     500,   0),
                    _bezp("nd20",        "nd20",       "nd20",       1.39,  1.42,  3),
                    _bezp("gestosc",     "gęstość",    "gestosc",    0.99,  1.00,  3),
                    _obl("sa",           "%SA",        "sa",         30,    35,    1, "sm"),
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
                    _bezp("sm",          "SM",         "sm",         34,    9999,  1),  # min 34%
                    _bezp("ph_10proc",   "pH 10%",     "ph_10proc",  5,     8,     2),
                    _titr("h2o2",        "%H2O2",      "h2o2",       0,     0.010, 3),
                    _bezp("barwa_fau",   "Barwa jodowa",      "barwa_fau",  0,     2,     0),
                    _bezp("barwa_hz",    "Barwa Hz",   "barwa_hz",   0,     500,   0),
                    _bezp("nd20",        "nd20",       "nd20",       1.39,  1.42,  3),
                    _bezp("gestosc",     "gęstość",    "gestosc",    0.99,  1.00,  3),
                    _obl("sa",           "%SA",        "sa",         34,    36,    1, "sm"),
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
                    _titr("tlenek_aminowy", "zaw.tlenku aminowego", "tlenek_aminowy", 28,  32,    1),
                    _bezp("ph_10proc",      "pH 10%",               "ph_10proc",      6,   8,     2),
                    _titr("h2o2",           "%H2O2",                "h2o2",            0,   0.010, 3),
                    _bezp("barwa_fau",      "Barwa jodowa",                "barwa_fau",       0,   1,     0),
                    _titr("wolna_amina",    "wolna amina",          "wolna_amina",     0,   0.5,   2),
                    _bezp("nd20",           "nd20",                 "nd20",            1.39, 1.42, 3),
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
                    _bezp("sm",          "SM",              "sm",          40,   9999, 1),  # min 40%
                    _titr("lk",          "LK",              "lk",          0,    6,    2),
                    _titr("so3",         "zaw.siarczynów",  "so3",         0,    0.1,  3),
                    _titr("h2o2",        "H2O2",            "h2o2",        0,    0.15, 3),
                    _obl("sa",           "%SA",              "sa",          26,   9999, 2, "sm - nacl - 0.6"),  # min 26%
                    _bezp("barwa_fau",   "Barwa jodowa",           "barwa_fau",   0,    10,   0),
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
                    _bezp("sm",          "SM",              "sm",          38,   42,   1),
                    _titr("so3",         "zaw.siarczynów",  "so3",         0,    0.1,  3),
                    _bezp("ph_10proc",   "pH 10%",          "ph_10proc",   5.5,  7,    2),
                    _obl("sa",           "%SA",              "sa",          31,   9999, 2, "sm - nacl - 0.6"),  # min 31%
                    _bezp("barwa_fau",   "Barwa jodowa",           "barwa_fau",   0,    5,    0),
                    _titr("lk",          "LK",              "lk",          0,    8,    2),
                    _bezp("nd20",        "nd20",            "nd20",        1.39, 1.42, 3),
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
                    _bezp("barwa_fau",   "Barwa jodowa",       "barwa_fau",  0,    6,    0),
                    _titr("wkt",         "%WKT",        "wkt",        0,    0.5,  2),
                    _titr("lk",          "LK",          "lk",         0,    1.4,  2),
                    _titr("mea",         "%MEA",        "mea",        0,    1.5,  2),
                    _titr("estry",       "%estry",      "estry",      0,    6,    2),
                    _bezp("gliceryny",   "%gliceryny",  "gliceryny",  0,    10,   2),
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
                    _bezp("barwa_fau",   "Barwa jodowa",          "barwa_fau",  0,    8,    0),
                    _titr("wkt",         "%WKT",           "wkt",        0,    10,   2),
                    _titr("mea",         "%MEA",           "mea",        0,    5,    2),
                    _titr("estry",       "%estry",         "estry",      0,    10,   2),
                    _bezp("gliceryny",   "%gliceryny",     "gliceryny",  0,    10,   2),
                    _bezp("t_topn",      "T.topnienia",    "t_topn",     45,   70,   1),
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
                    _bezp("barwa_fau",   "Barwa jodowa",          "barwa_fau",  0,     4,    0),
                    _titr("wkt",         "%WKT",           "wkt",        0,     0.5,  2),
                    _titr("mea",         "%MEA",           "mea",        0.3,   1.3,  2),
                    _titr("estry",       "estry",          "estry",      0,     6,    2),
                    _titr("lz",          "L.zmydlenia",    "lz",         0,     999,  2),
                    _bezp("t_kropl",     "T.kroplenia",    "t_kropl",    45,    70,   1),
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
                    _titr("lk",          "LK",             "lk",         0,     10,   2),
                    _titr("la",          "L.aminowa",      "la",         0,     200,  2),
                    _titr("wkt",         "%WKT",           "wkt",        0,     2.0,  2),
                    _titr("mea",         "%MEA",           "mea",        0,     2.0,  2),
                    _bezp("t_kropl",     "T.kroplenia",    "t_kropl",    45,    70,   1),
                    _bezp("barwa_fau",   "Barwa jodowa",          "barwa_fau",  0,     10,   0),
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
                    _titr("lk",          "LK",             "lk",         0,     5,    2),
                    _titr("wolna_amina", "wolna amina",    "wolna_amina", 0,    3,    2),
                    _bezp("t_kropl",     "T.kroplenia",    "t_kropl",    85,    92,   1),
                    _bezp("barwa_fau",   "Barwa jodowa",          "barwa_fau",  0,     5,    0),
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
                    _titr("lk",          "LK",              "lk",    0,     6,    2),
                    _titr("wge",         "WGE",             "wge",   0,     100,  2),
                    _titr("lh",          "L.hydroksylowa",  "lh",    0,     54,   2),
                    _titr("lz",          "L.zmydlenia",     "lz",    188,   200,  2),
                    _bezp("t_kropl",     "T.kroplenia",     "t_kropl", 58,  64,   1),
                    _titr("wkt",         "WKT",             "wkt",   0,     5,    2),
                    _bezp("t_topn",      "T.topnienia",     "t_topn", 58,   64,   1),
                    _bezp("wolny_glikol", "Wolny glikol %", "wolny_glikol", 0, 1, 2),
                    _bezp("barwa_fau",    "Barwa jodowa",          "barwa_fau",    0, 10, 0),
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
                    _titr("lk",          "LK",              "lk",         0,     3,    2),
                    _titr("lz",          "L.zmydlenia",     "lz",         150,   170,  2),
                    _titr("li",          "L.jodowa",        "li",         63,    83,   2),
                    _titr("monoestry",   "zaw.monoestrów",  "monoestry",  30,    9999, 2),  # min 30%
                    _bezp("barwa_fau",   "Barwa jodowa",           "barwa_fau",  0,     10,   0),
                    _bezp("nd20",        "nd20",            "nd20",       1.468, 1.473, 4),
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
                    _titr("lk",             "LK",              "lk",             0,     3,    2),
                    _bezp("t_kropl",        "T.kroplenia",     "t_kropl",        54,    60,   1),
                    _titr("lz",             "L.zmydlenia",     "lz",             145,   185,  2),
                    _titr("li",             "L.jodowa",        "li",             0,     5,    2),
                    _bezp("gliceryny",      "%gliceryny",      "gliceryny",      0,     10,   2),
                    _titr("monoglicerydy",  "%monoglicerydów", "monoglicerydy",  0,     100,  2),
                    _bezp("barwa_fau",      "Barwa jodowa",           "barwa_fau",      0,     10,   0),
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
                    _bezp("barwa_fau",   "Barwa jodowa",           "barwa_fau",  0,     2,    0),
                    _titr("lk",          "LK",              "lk",         0,     2,    2),
                    _titr("lz",          "L.zmydlenia",     "lz",         0,     2,    2),
                    _bezp("t_kropl",     "T.kroplenia",     "t_kropl",    47,    55,   1),
                    _titr("lh",          "L.hydroksylowa",  "lh",         0,     300,  2),
                    _titr("li",          "L.jodowa",        "li",         0,     2,    2),
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
                    _titr("lk",          "LK",          "lk",         0,     4,    2),
                    _titr("wkt",         "WKT",         "wkt",        0,     5,    2),
                    _titr("la",          "L.aminowa",   "la",         165,   185,  2),
                    _bezp("barwa_fau",   "Barwa jodowa",       "barwa_fau",  0,     4,    0),
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
                    _bezp("barwa_fau",   "Barwa jodowa",          "barwa_fau",  0,     10,   0),
                    _titr("lk",          "LK",             "lk",         0,     15,   2),
                    _titr("la",          "L.aminowa",      "la",         130,   160,  2),
                    _titr("wkt",         "WKT",            "wkt",        0,     8,    2),
                    _bezp("t_kropl",     "T.kroplenia",    "t_kropl",    45,    70,   1),
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
                    _titr("lk",          "LK",              "lk",    0,     0.2,  2),
                    _titr("lz",          "L.zmydlenia",     "lz",    0,     1.2,  2),
                    _titr("li",          "L.jodowa",        "li",    0,     1.0,  2),
                    _bezp("barwa_fau",   "Barwa jodowa",           "barwa_fau", 0, 10,   0),
                    _bezp("nd20",        "nd20",            "nd20",  1.39,  1.50, 3),
                    _titr("lh",          "L.hydroksylowa",  "lh",    210,   220,  2),
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
                    _titr("lh",          "L.hydroksylowa",  "lh",         45,    55,   2),
                    _bezp("ph_10proc",   "pH 1%",           "ph_10proc",  5,     7,    2),
                    _bezp("nd20",        "nd20",            "nd20",       1.39,  1.50, 3),
                    _bezp("barwa_fau",   "Barwa jodowa",           "barwa_fau",  0,     10,   0),
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
                    _titr("lk",          "LK",              "lk",         0,     20,   2),
                    _titr("lz",          "L.zmydlenia",     "lz",         90,    100,  2),
                    _titr("lh",          "L.hydroksylowa",  "lh",         145,   160,  2),
                    _bezp("ph_10proc",   "pH 20%",          "ph_10proc",  5,     8,    2),
                    _bezp("t_topn",      "T.topnienia",     "t_topn",     49,    52,   1),
                    _bezp("barwa_fau",   "Barwa jodowa",           "barwa_fau",  0,     10,   0),
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
                    _titr("lk",   "LK",           "lk",  0,    4,    2),
                    _titr("lz",   "L.zmydlenia",  "lz",  90,   120,  2),
                    _bezp("barwa_fau", "Barwa jodowa", "barwa_fau", 0, 10, 0),
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
                    _titr("lk",          "LK",           "lk",        0,      2,     2),
                    _bezp("gestosc",     "gęstość",      "gestosc",   0.960,  0.970, 3),
                    _bezp("barwa_fau",   "Barwa jodowa",        "barwa_fau", 0,      2,     0),
                    _titr("lz",          "L.zmydlenia",  "lz",        410,    450,   2),
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
                    _titr("dietanolamina", "%dietanolaminy", "dietanolamina", 80,  9999, 1),  # min 80%
                    _bezp("gliceryny",     "%gliceryny",     "gliceryny",     0,   9.5,  2),
                    _bezp("dietanolamina", "DEA %",          "dietanolamina",  0,   3,    2),
                    _bezp("barwa_fau",     "Barwa jodowa",          "barwa_fau",     0,   10,   0),
                    _bezp("ph_10proc",     "pH 1%",          "ph_10proc",     0,   11,   2),
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
                    _titr("lk",           "LK",              "lk",          0,    3,    2),
                    _titr("wolny_glikol", "wolny glikol",    "wolny_glikol", 0,   3,    2),
                    _titr("lh",           "L.hydroksylowa",  "lh",          70,   130,  2),
                    _titr("monoestry",    "monoestry",       "monoestry",   47,   55,   2),
                    _bezp("barwa_fau",    "Barwa jodowa",           "barwa_fau",   0,    4,    0),
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
                    _titr("lk",       "LK",           "lk",      0,    1,    2),
                    _bezp("t_kropl",  "T.kroplenia",  "t_kropl", 48,   52,   1),
                    _bezp("barwa_fau", "Barwa jodowa", "barwa_fau", 0, 10, 0),
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
                    _titr("lk",       "LK",              "lk",       208,   212,  2),
                    _bezp("t_krzep",  "T.krzepnięcia",   "t_krzep",  54,    56,   1),
                    _titr("li",       "L.jodowa",        "li",       0,     1,    2),
                    _bezp("barwa_fau", "Barwa jodowa", "barwa_fau", 0, 10, 0),
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
                    _bezp("sm",          "SM",      "sm",         43,   9999, 1),  # min 43%
                    _bezp("ph_10proc",   "pH 10%",  "ph_10proc",  5,    8,    2),
                    _bezp("barwa_fau",   "Barwa jodowa",   "barwa_fau",  0,    10,   0),
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
                    _bezp("barwa_fau",   "Barwa jodowa",   "barwa_fau",  0,     2,    0),
                    _obl("sa",           "%SA",      "sa",         25,    28,   2, "sm - nacl - 0.6"),
                    _bezp("ph_10proc",   "pH 3%",   "ph_10proc",  6.5,   7.5,  2),
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
                    _titr("lh",          "L.hydroksylowa",  "lh",        210,   220,  2),
                    _titr("lk",          "LK",              "lk",        0,     0.1,  2),
                    _titr("lz",          "L.zmydlenia",     "lz",        0,     1.0,  2),
                    _titr("li",          "L.jodowa",        "li",        0,     1.0,  2),
                    _bezp("nd20",        "nd20",            "nd20",      1.39,  1.50, 3),
                    _bezp("barwa_fau",   "Barwa jodowa",           "barwa_fau", 0,     10,   0),
                ],
            },
        },
    },

    # ===== GRUPA 10: Nowe produkty =====
    {
        "produkt": "Chegina_K40GLN",
        "template_id": "T-K40GLN",
        "etapy": ETAPY_FULL_GLOL,
        "parametry_lab": {
            "analiza": {
                "label": "Analiza",
                "pola": [
                    _bezp("sm",          "S.Masa",       "sm",         44,    48,    1),
                    _titr("nacl",        "NaCl",         "nacl",       5.8,   7.3,   2),
                    _bezp("ph_10proc",   "pH 20°C",     "ph_10proc",  4.5,   5.5,   2),
                    _bezp("barwa_hz",    "Barwa Hz",     "barwa_hz",   0,     500,   0),
                    _bezp("barwa_fau",   "Barwa jodowa",        "barwa_fau",  0,     10,    0),
                    _obl("sa",           "%SA",           "sa",         37.6,  40,    2, "sm - nacl - 0.6"),
                    _titr("wolna_amina", "%wolna amina", "wolna_amina", 0,    0.3,   2),
                    _bezp("h2o",         "H2O %",        "h2o",        0,     56,    1),
                ],
            },
        },
    },
    {
        "produkt": "Chegina_GLOL40",
        "template_id": "T-GLOL40",
        "etapy": ETAPY_FULL_GLOL,
        "parametry_lab": {
            "analiza": {
                "label": "Analiza",
                "pola": [
                    _bezp("sm",          "S.Masa",       "sm",         44,    48,    1),
                    _titr("nacl",        "NaCl",         "nacl",       5.8,   7.3,   2),
                    _bezp("ph_10proc",   "pH",           "ph_10proc",  4.5,   5.5,   2),
                    _obl("sa",           "%SA",           "sa",         37,    42,    1, "sm - nacl - 0.6"),
                    _titr("wolna_amina", "%wolna amina", "wolna_amina", 0,    0.3,   2),
                    _bezp("barwa_fau",   "Barwa jodowa",        "barwa_fau",  0,     10,    0),
                ],
            },
        },
    },
    {
        "produkt": "Alkinol_B",
        "template_id": "T-ALKINOLB",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _bezp("barwa_fau",   "Barwa jodowa",           "barwa_fau",  0,     4,    0),
                    _titr("lk",          "L.kwasowa",       "lk",         0,     2,    2),
                    _titr("lz",          "L.zmydlania",     "lz",         0,     2,    2),
                    _bezp("t_kropl",     "T.kroplenia",     "t_kropl",    47,    55,   1),
                    _bezp("lh",          "L.hydroksylowa",  "lh",         155,   180,  0),
                    _titr("li",          "L.jodowa",        "li",         0,     2,    2),
                ],
            },
        },
    },
    {
        "produkt": "Chemal_CS_3070",
        "template_id": "T-CS3070",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _bezp("lh",          "L.hydroksylowa",  "lh",    210,   220,  0),
                    _titr("lk",          "L.kwasowa",       "lk",    0,     0.2,  1),
                    _titr("lz",          "L.zmydlenia",     "lz",    0,     1.2,  1),
                    _titr("li",          "L.jodowa",        "li",    0,     1.0,  1),
                    _bezp("barwa_fau",   "Barwa jodowa",           "barwa_fau", 0,    10,   0),
                ],
            },
        },
    },
    {
        "produkt": "Chemal_CS_5050",
        "template_id": "T-CS5050",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _bezp("lh",          "L.hydroksylowa",  "lh",    210,   225,  0),
                    _titr("lk",          "L.kwasowa",       "lk",    0,     0.2,  1),
                    _titr("lz",          "L.zmydlenia",     "lz",    0,     1.2,  1),
                    _titr("li",          "L.jodowa",        "li",    0,     1.0,  1),
                    _bezp("barwa_fau",   "Barwa jodowa",           "barwa_fau", 0,    10,   0),
                ],
            },
        },
    },
    {
        "produkt": "HSH_CS_3070",
        "template_id": "T-HSH3070",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _bezp("lh",          "L.hydroksylowa",  "lh",    210,   220,  0),
                    _titr("lk",          "L.kwasowa",       "lk",    0,     0.1,  1),
                    _titr("lz",          "L.zmydlenia",     "lz",    0,     1.0,  1),
                    _titr("li",          "L.jodowa",        "li",    0,     1.0,  1),
                    _bezp("barwa_fau",   "Barwa jodowa",           "barwa_fau", 0,    10,   0),
                ],
            },
        },
    },
    {
        "produkt": "Kwas_Stearynowy",
        "template_id": "T-KWST",
        "etapy": ETAPY_SIMPLE,
        "parametry_lab": {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [
                    _titr("lk",       "L.kwasowa",    "lk",      206,   212,  0),
                    _bezp("t_kropl",  "T.kroplenia",  "t_kropl", 54,    56.5, 1),
                    _titr("li",       "L.jodowa",     "li",      0,     0.5,  2),
                    _bezp("barwa_fau", "Barwa jodowa", "barwa_fau", 0, 10, 0),
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
    {"login": "lab",       "password": "lab",     "rola": "lab",       "imie_nazwisko": "Laborant KJ"},
    {"login": "cert",      "password": "cert",    "rola": "cert",      "imie_nazwisko": "Świadectwa KJ"},
]


def seed(update=False):
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
        updated = 0
        for prod in PRODUCTS:
            produkt = prod["produkt"]
            exists = db.execute(
                "SELECT 1 FROM mbr_templates WHERE produkt = ? AND wersja = 1",
                (produkt,),
            ).fetchone()

            etapy_json = json.dumps(prod["etapy"], ensure_ascii=False)
            parametry_json = json.dumps(prod["parametry_lab"], ensure_ascii=False)
            notatki = json.dumps(
                {"nr_aparatu": prod["template_id"]} if prod["template_id"] else {},
                ensure_ascii=False,
            )

            if exists and update:
                db.execute(
                    """UPDATE mbr_templates
                       SET parametry_lab = ?, etapy_json = ?
                       WHERE produkt = ? AND wersja = 1""",
                    (parametry_json, etapy_json, produkt),
                )
                print(f"  ~ MBR: {produkt} v1 updated (parametry_lab + etapy)")
                updated += 1
            elif exists:
                print(f"  . MBR: {produkt} v1 already exists")
                skipped += 1
            else:
                db.execute(
                    """INSERT INTO mbr_templates
                       (produkt, wersja, status, etapy_json, parametry_lab,
                        utworzony_przez, dt_utworzenia, dt_aktywacji, notatki)
                       VALUES (?, 1, 'active', ?, ?, 'seed', ?, ?, ?)""",
                    (produkt, etapy_json, parametry_json, now, now, notatki),
                )
                print(f"  + MBR: {produkt} v1 (active)")
                created += 1

        # --- Workers (synthetic test data) ---
        existing_workers = db.execute("SELECT COUNT(*) FROM workers").fetchone()[0]
        if existing_workers == 0:
            test_workers = [
                ("Anna",    "Kowalska",   "AK"),
                ("Marta",   "Nowak",      "MN"),
                ("Katarzyna", "Wiśniewska", "KW"),
                ("Joanna",  "Wójcik",     "JW"),
                ("Ewa",     "Kamińska",   "EK"),
                ("Tomasz",  "Zieliński",  "TZ"),
            ]
            for imie, nazwisko, inicjaly in test_workers:
                db.execute(
                    "INSERT INTO workers (imie, nazwisko, inicjaly) VALUES (?, ?, ?)",
                    (imie, nazwisko, inicjaly),
                )
            print(f"  + {len(test_workers)} workers seeded")
        else:
            print(f"  . {existing_workers} workers already exist")

        db.commit()
        print(f"\nSeed complete: {created} created, {updated} updated, {skipped} skipped.")
    finally:
        db.close()


if __name__ == "__main__":
    do_update = "--update" in sys.argv
    seed(update=do_update)
