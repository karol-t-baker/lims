"""
parametry/seed.py — Seed parametry_analityczne + parametry_etapy tables.

Populates centralized analytical parameter definitions extracted from:
  - etapy_config.py  (process stage limits per product)
  - seed_mbr.py      (analiza_koncowa limits per product, titration factors)

Run once:  python -m mbr.parametry.seed
Idempotent: INSERT OR IGNORE, safe to re-run.
"""

from mbr.models import get_db, init_mbr_tables

# ---------------------------------------------------------------------------
# 1. PARAMETRY — all unique analytical parameters
# ---------------------------------------------------------------------------

# Format: dict with keys matching parametry_analityczne columns.
# Required: kod, label, typ
# titracja also needs: metoda_nazwa, metoda_formula, metoda_factor
# obliczeniowy also needs: formula

PARAMETRY = [
    # --- bezposredni ---
    {"kod": "ph",         "label": "pH roztworu",          "skrot": "pH",       "typ": "bezposredni", "precision": 2},
    {"kod": "ph_10proc",  "label": "pH roztworu 10%",      "skrot": "pH 10%",   "typ": "bezposredni", "precision": 2},
    {"kod": "nd20",       "label": "Współczynnik załamania nD20", "skrot": "nD20", "typ": "bezposredni", "precision": 4},
    {"kod": "sm",         "label": "Sucha masa",           "skrot": "SM",       "typ": "bezposredni", "precision": 1},
    {"kod": "le",         "label": "Liczba estrowa",       "skrot": "LE",       "typ": "bezposredni", "precision": 2},
    {"kod": "barwa_fau",  "label": "Barwa jodowa FAU",     "skrot": "Barwa FAU","typ": "bezposredni", "precision": 0},
    {"kod": "barwa_hz",   "label": "Barwa wg Hazen",       "skrot": "Barwa Hz", "typ": "bezposredni", "precision": 0},
    {"kod": "gestosc",    "label": "Gęstość",              "skrot": "d",        "typ": "bezposredni", "precision": 3},
    {"kod": "h2o",        "label": "Zawartość wody",       "skrot": "H₂O",     "typ": "bezposredni", "precision": 1},
    {"kod": "woda",       "label": "Zawartość wody",       "skrot": "Woda",     "typ": "bezposredni", "precision": 1},

    # --- titracja ---
    {"kod": "la",
     "label": "Liczba kwasowa",  "skrot": "LA",
     "typ": "titracja",
     "metoda_nazwa": "Alkacymetria KOH",
     "metoda_formula": "LA = (V * C * 56.1) / m",
     "metoda_factor": 5.61,
     "precision": 2},
    {"kod": "lk",
     "label": "Liczba kwasowa końcowa",  "skrot": "LK",
     "typ": "titracja",
     "metoda_nazwa": "Alkacymetria KOH",
     "metoda_formula": "LK = (V * C * 56.1) / m",
     "metoda_factor": 5.61,
     "precision": 2},
    {"kod": "nacl",
     "label": "Chlorek sodu",  "skrot": "NaCl",
     "typ": "titracja",
     "metoda_nazwa": "Argentometryczna Mohr",
     "metoda_formula": "% = (V * 0.00585 * 100) / m",
     "metoda_factor": 0.585,
     "precision": 2},
    {"kod": "aa",
     "label": "Amina aminowa",  "skrot": "%AA",
     "typ": "titracja",
     "metoda_nazwa": "Alkacymetria",
     "metoda_formula": "% = (V * C * M) / (m * 10)",
     "metoda_factor": 3.015,
     "precision": 2},
    {"kod": "so3",
     "label": "Siarczyny",  "skrot": "%SO₃²⁻",
     "typ": "titracja",
     "metoda_nazwa": "Jodometryczna",
     "metoda_formula": "% = (V * 0.004 * 100) / m",
     "metoda_factor": 0.4,
     "precision": 3},
    {"kod": "h2o2",
     "label": "Nadtlenek wodoru",  "skrot": "%H₂O₂",
     "typ": "titracja",
     "metoda_nazwa": "Manganometryczna",
     "metoda_formula": "% = (V * 0.0017 * 100) / m",
     "metoda_factor": 0.17,
     "precision": 3},
    {"kod": "wolna_amina",
     "label": "Wolna amina",  "skrot": "%WA",
     "typ": "titracja",
     "metoda_nazwa": "Alkacymetria",
     "metoda_formula": "% = (V * C * M) / (m * 10)",
     "metoda_factor": 3.015,
     "precision": 2},
    {"kod": "sa_epton",
     "label": "Substancja aktywna (Epton)",  "skrot": "%SA",
     "typ": "titracja",
     "metoda_nazwa": "Dwufazowa Epton",
     "metoda_formula": "% = (V * f * M) / m",
     "metoda_factor": 3.261,
     "precision": 2},

    # --- obliczeniowy ---
    {"kod": "sa",
     "label": "Substancja aktywna",  "skrot": "%SA",
     "typ": "obliczeniowy",
     "formula": "sm - nacl - 0.6",
     "precision": 2},

    # --- dodatki (bezposredni) ---
    {"kod": "kwas_kg",  "label": "Dodatek kwasu",       "skrot": "Kwas",  "typ": "bezposredni", "precision": 1},
    {"kod": "woda_kg",  "label": "Dodatek wody",        "skrot": "Woda",  "typ": "bezposredni", "precision": 1},
    {"kod": "nacl_kg",  "label": "Dodatek NaCl",        "skrot": "NaCl",  "typ": "bezposredni", "precision": 1},
    {"kod": "nastaw",   "label": "Nastaw",               "skrot": "Nastaw","typ": "bezposredni", "precision": 0},
]

# ---------------------------------------------------------------------------
# 2. ETAPY_BINDINGS — (produkt, kontekst, kod, kolejnosc, min, max, nawazka_g)
#
# Rules:
#   produkt=None  → shared default (applies to all products unless overridden)
#   produkt=str   → product-specific override
#
# Process stages: amidowanie, smca, czwartorzedowanie, sulfonowanie,
#                 utlenienie, rozjasnianie
# Finish stages:  analiza_koncowa, dodatki
#
# nawazka_g defaults for titracja:
#   nacl: 2.0, aa: 5.0, so3: 10.0, h2o2: 10.0, lk: 2.0, la: 2.0,
#   wolna_amina: 5.0
# ---------------------------------------------------------------------------

_NAWAZKA = {
    "nacl": 2.0,
    "aa":   5.0,
    "so3":  10.0,
    "h2o2": 10.0,
    "lk":   2.0,
    "la":   2.0,
    "wolna_amina": 5.0,
}


def _b(produkt, kontekst, kod, kolejnosc, mn, mx, nawazka=None):
    """Helper: build a binding tuple dict."""
    return {
        "produkt": produkt,
        "kontekst": kontekst,
        "kod": kod,
        "kolejnosc": kolejnosc,
        "min_limit": mn,
        "max_limit": mx,
        "nawazka_g": nawazka if nawazka is not None else _NAWAZKA.get(kod),
    }


ETAPY_BINDINGS = [
    # =========================================================
    # PROCESS STAGES — shared defaults (produkt=None) from K7
    # =========================================================

    # amidowanie (shared — same limits for K7 and K40GLOL)
    _b(None, "amidowanie", "le",   1, None, None),
    _b(None, "amidowanie", "la",   2, None, 5.0),
    _b(None, "amidowanie", "lk",   3, None, 1.0),
    _b(None, "amidowanie", "nd20", 4, None, None),

    # smca (shared — same limits)
    _b(None, "smca", "ph", 1, 3.0, 4.0),

    # czwartorzedowanie — K7 default (aa max=0.50)
    _b(None, "czwartorzedowanie", "ph_10proc", 1, 11.0, 12.0),
    _b(None, "czwartorzedowanie", "nd20",      2, None, None),
    _b(None, "czwartorzedowanie", "aa",        3, None, 0.50),

    # K40GLOL override: aa max=0.30
    _b("Chegina_K40GLOL", "czwartorzedowanie", "ph_10proc", 1, 11.0, 12.0),
    _b("Chegina_K40GLOL", "czwartorzedowanie", "nd20",      2, None, None),
    _b("Chegina_K40GLOL", "czwartorzedowanie", "aa",        3, None, 0.30),

    # sulfonowanie — K7 default (no h2o2)
    _b(None, "sulfonowanie", "ph_10proc", 1, None, None),
    _b(None, "sulfonowanie", "so3",       2, None, 0.30),
    _b(None, "sulfonowanie", "nd20",      3, None, None),

    # K40GLOL override: adds h2o2 (no limit)
    _b("Chegina_K40GLOL", "sulfonowanie", "ph_10proc", 1, None, None),
    _b("Chegina_K40GLOL", "sulfonowanie", "so3",       2, None, 0.30),
    _b("Chegina_K40GLOL", "sulfonowanie", "h2o2",      3, None, None),
    _b("Chegina_K40GLOL", "sulfonowanie", "nd20",      4, None, None),

    # utlenienie — K7 default (so3 max=0.000)
    _b(None, "utlenienie", "ph_10proc", 1, None, None),
    _b(None, "utlenienie", "so3",       2, None, 0.000),
    _b(None, "utlenienie", "h2o2",      3, None, 0.010),
    _b(None, "utlenienie", "nd20",      4, None, None),

    # K40GLOL override: so3 max=0.030
    _b("Chegina_K40GLOL", "utlenienie", "ph_10proc", 1, None, None),
    _b("Chegina_K40GLOL", "utlenienie", "so3",       2, None, 0.030),
    _b("Chegina_K40GLOL", "utlenienie", "h2o2",      3, None, 0.010),
    _b("Chegina_K40GLOL", "utlenienie", "nd20",      4, None, None),

    # rozjasnianie — K40GLOL only
    _b("Chegina_K40GLOL", "rozjasnianie", "ph_10proc",  1, None,  None),
    _b("Chegina_K40GLOL", "rozjasnianie", "h2o2",       2, 0.005, 0.050),
    _b("Chegina_K40GLOL", "rozjasnianie", "barwa_fau",  3, None,  5),
    _b("Chegina_K40GLOL", "rozjasnianie", "barwa_hz",   4, None,  150),

    # =========================================================
    # analiza_koncowa — per product (from seed_mbr.py)
    # =========================================================

    # Chegina_K40GL
    _b("Chegina_K40GL", "analiza_koncowa", "sm",        1,  44,    48),
    _b("Chegina_K40GL", "analiza_koncowa", "nacl",      2,  5.8,   7.3),
    _b("Chegina_K40GL", "analiza_koncowa", "ph_10proc", 3,  4.5,   5.5),
    _b("Chegina_K40GL", "analiza_koncowa", "nd20",      4,  1.39,  1.42),
    _b("Chegina_K40GL", "analiza_koncowa", "sa",        5,  37,    42),
    _b("Chegina_K40GL", "analiza_koncowa", "aa",        6,  0,     0.5),
    _b("Chegina_K40GL", "analiza_koncowa", "barwa_fau", 7,  0,     200),
    _b("Chegina_K40GL", "analiza_koncowa", "barwa_hz",  8,  0,     100),
    _b("Chegina_K40GL", "analiza_koncowa", "so3",       9,  0,     0.030),

    # Chegina_K40GLO
    _b("Chegina_K40GLO", "analiza_koncowa", "sm",        1,  44,    48),
    _b("Chegina_K40GLO", "analiza_koncowa", "nacl",      2,  5.8,   7.3),
    _b("Chegina_K40GLO", "analiza_koncowa", "ph_10proc", 3,  5.0,   7.0),
    _b("Chegina_K40GLO", "analiza_koncowa", "nd20",      4,  1.39,  1.42),
    _b("Chegina_K40GLO", "analiza_koncowa", "sa",        5,  37,    9999),
    _b("Chegina_K40GLO", "analiza_koncowa", "aa",        6,  0,     0.5),
    _b("Chegina_K40GLO", "analiza_koncowa", "gestosc",   7,  1.05,  1.09),
    _b("Chegina_K40GLO", "analiza_koncowa", "barwa_fau", 8,  0,     200),
    _b("Chegina_K40GLO", "analiza_koncowa", "so3",       9,  0,     0.030),
    _b("Chegina_K40GLO", "analiza_koncowa", "barwa_hz",  10, 0,     500),

    # Chegina_K40GLOL
    _b("Chegina_K40GLOL", "analiza_koncowa", "sm",          1,  44,    9999),
    _b("Chegina_K40GLOL", "analiza_koncowa", "nacl",        2,  5.8,   7.3),
    _b("Chegina_K40GLOL", "analiza_koncowa", "ph_10proc",   3,  4.5,   6.5),
    _b("Chegina_K40GLOL", "analiza_koncowa", "nd20",        4,  1.39,  1.42),
    _b("Chegina_K40GLOL", "analiza_koncowa", "sa",          5,  36,    42),
    _b("Chegina_K40GLOL", "analiza_koncowa", "aa",          6,  0,     0.3),
    _b("Chegina_K40GLOL", "analiza_koncowa", "h2o2",        7,  0,     0.010),
    _b("Chegina_K40GLOL", "analiza_koncowa", "so3",         8,  0,     0.030),
    _b("Chegina_K40GLOL", "analiza_koncowa", "barwa_fau",   9,  0,     200),
    _b("Chegina_K40GLOL", "analiza_koncowa", "barwa_hz",    10, 0,     500),
    _b("Chegina_K40GLOL", "analiza_koncowa", "wolna_amina", 11, 0,     0.5),
    _b("Chegina_K40GLOL", "analiza_koncowa", "h2o",         12, 50,    58),

    # Chegina_K7
    _b("Chegina_K7", "analiza_koncowa", "sm",        1,  40,    48),
    _b("Chegina_K7", "analiza_koncowa", "nacl",      2,  4.0,   8.0),
    _b("Chegina_K7", "analiza_koncowa", "ph_10proc", 3,  4.0,   6.0),
    _b("Chegina_K7", "analiza_koncowa", "nd20",      4,  1.39,  1.42),
    _b("Chegina_K7", "analiza_koncowa", "sa",        5,  30,    42),
    _b("Chegina_K7", "analiza_koncowa", "barwa_fau", 6,  0,     200),
    _b("Chegina_K7", "analiza_koncowa", "barwa_hz",  7,  0,     100),

    # =========================================================
    # dodatki — all 4 core products
    # =========================================================
    *[
        _b(prod, "dodatki", "kwas_kg", 1, 0, 9999)
        for prod in ("Chegina_K40GL", "Chegina_K40GLO", "Chegina_K40GLOL", "Chegina_K7")
    ],
    *[
        _b(prod, "dodatki", "woda_kg", 2, 0, 9999)
        for prod in ("Chegina_K40GL", "Chegina_K40GLO", "Chegina_K40GLOL", "Chegina_K7")
    ],
    *[
        _b(prod, "dodatki", "nacl_kg", 3, 0, 9999)
        for prod in ("Chegina_K40GL", "Chegina_K40GLO", "Chegina_K40GLOL", "Chegina_K7")
    ],
]

# ---------------------------------------------------------------------------
# 3. seed() — INSERT OR IGNORE into both tables
# ---------------------------------------------------------------------------


def seed(db):
    # --- parametry_analityczne ---
    pa_rows = 0
    for p in PARAMETRY:
        db.execute(
            """
            INSERT OR IGNORE INTO parametry_analityczne
                (kod, label, typ, metoda_nazwa, metoda_formula, metoda_factor,
                 formula, precision, skrot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p["kod"],
                p["label"],
                p["typ"],
                p.get("metoda_nazwa"),
                p.get("metoda_formula"),
                p.get("metoda_factor"),
                p.get("formula"),
                p.get("precision", 2),
                p.get("skrot"),
            ),
        )
        # Update skrot + label on existing rows (INSERT OR IGNORE skips them)
        if p.get("skrot"):
            db.execute(
                "UPDATE parametry_analityczne SET skrot=?, label=? WHERE kod=? AND (skrot IS NULL OR skrot != ?)",
                (p["skrot"], p["label"], p["kod"], p["skrot"]),
            )
        if db.execute("SELECT changes()").fetchone()[0]:
            pa_rows += 1

    db.commit()

    # Build kod→id lookup
    kod_to_id = {
        row[0]: row[1]
        for row in db.execute("SELECT kod, id FROM parametry_analityczne").fetchall()
    }

    # --- parametry_etapy ---
    pe_rows = 0
    skipped = 0
    for b in ETAPY_BINDINGS:
        param_id = kod_to_id.get(b["kod"])
        if param_id is None:
            print(f"  WARNING: kod '{b['kod']}' not found in parametry_analityczne — skipping")
            skipped += 1
            continue
        db.execute(
            """
            INSERT OR IGNORE INTO parametry_etapy
                (produkt, kontekst, parametr_id, kolejnosc,
                 min_limit, max_limit, nawazka_g)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                b["produkt"],
                b["kontekst"],
                param_id,
                b["kolejnosc"],
                b["min_limit"],
                b["max_limit"],
                b["nawazka_g"],
            ),
        )
        if db.execute("SELECT changes()").fetchone()[0]:
            pe_rows += 1

    db.commit()

    total_pa = db.execute("SELECT COUNT(*) FROM parametry_analityczne").fetchone()[0]
    total_pe = db.execute("SELECT COUNT(*) FROM parametry_etapy").fetchone()[0]
    print(f"Seeded: {pa_rows} parameters inserted ({total_pa} total), "
          f"{pe_rows} bindings inserted ({total_pe} total)"
          + (f", {skipped} skipped" if skipped else ""))


# ---------------------------------------------------------------------------
# 4. seed_from_seed_mbr() — auto-seed remaining products from seed_mbr.PRODUCTS
# ---------------------------------------------------------------------------


def seed_from_seed_mbr(db):
    """Read seed_mbr.PRODUCTS and seed analiza_koncowa/dodatki bindings
    for all products not yet covered by ETAPY_BINDINGS."""
    from mbr.seed_mbr import PRODUCTS as MBR_PRODUCTS

    # Build kod → id map
    kod_to_id = {}
    for row in db.execute("SELECT id, kod FROM parametry_analityczne").fetchall():
        kid = row[0] if isinstance(row, tuple) else row["id"]
        kkod = row[1] if isinstance(row, tuple) else row["kod"]
        kod_to_id[kkod] = kid

    # Track which product+kontekst combos already seeded
    existing = set()
    for row in db.execute("SELECT produkt, kontekst FROM parametry_etapy WHERE produkt IS NOT NULL").fetchall():
        p = row[0] if isinstance(row, tuple) else row["produkt"]
        k = row[1] if isinstance(row, tuple) else row["kontekst"]
        existing.add((p, k))

    added = 0
    for prod_def in MBR_PRODUCTS:
        produkt = prod_def["produkt"]
        plab = prod_def.get("parametry_lab", {})
        for sekcja_key, sekcja_def in plab.items():
            kontekst = sekcja_key
            if kontekst == "analiza":
                kontekst = "analiza_koncowa"

            if (produkt, kontekst) in existing:
                continue

            pola = sekcja_def.get("pola", [])
            for i, pole in enumerate(pola):
                kod = pole["kod"]
                if kod not in kod_to_id:
                    mt = pole.get("measurement_type", "bezposredni")
                    db.execute(
                        """INSERT OR IGNORE INTO parametry_analityczne
                           (kod, label, typ, precision)
                           VALUES (?, ?, ?, ?)""",
                        (kod, pole.get("label", kod), mt, pole.get("precision", 2)),
                    )
                    db.commit()
                    row = db.execute("SELECT id FROM parametry_analityczne WHERE kod=?", (kod,)).fetchone()
                    new_id = row[0] if isinstance(row, tuple) else row["id"]
                    kod_to_id[kod] = new_id

                pid = kod_to_id[kod]
                mn = pole.get("min")
                mx = pole.get("max")
                nawazka = None
                cm = pole.get("calc_method")
                if cm:
                    nawazka = cm.get("suggested_mass")

                db.execute(
                    """INSERT OR IGNORE INTO parametry_etapy
                       (produkt, kontekst, parametr_id, kolejnosc, min_limit, max_limit, nawazka_g)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (produkt, kontekst, pid, i + 1, mn, mx, nawazka),
                )
                added += 1

    db.commit()
    print(f"Auto-seeded {added} additional bindings from seed_mbr.py")


# ---------------------------------------------------------------------------
# 5. seed_metody — INSERT OR IGNORE titration methods from old server
# ---------------------------------------------------------------------------

import json as _json

METODY = [
    {
        "nazwa": "DMAPA [%]",
        "formula": "(V1 * 5.109 * T1) / M",
        "mass_required": 1,
        "volumes_json": [{"label": "VHCl [ml]", "titrant": "T1"}],
        "titrants_json": [{"id": "T1", "label": "C(HCl)", "default": 0.1}],
    },
    {
        "nazwa": "KATALIZATOR KOH/GP",
        "formula": "(V1 * T1 * 56.1) / (M * 10)",
        "mass_required": 1,
        "volumes_json": [{"label": "VHCl [ml]", "titrant": "T1"}],
        "titrants_json": [{"id": "T1", "label": "C(HCl)", "default": 0.1}],
    },
    {
        "nazwa": "Perhydrol [%]",
        "formula": "(V1 * T1 * 1.704 * 250) / (M * 15)",
        "mass_required": 1,
        "volumes_json": [{"label": "VCe [ml]", "titrant": "T1"}],
        "titrants_json": [{"id": "T1", "label": "C(Ce)", "default": 0.1}],
    },
    {
        "nazwa": "Nadtlenki [%]",
        "formula": "(V1 * T1 * 1.704) / M",
        "mass_required": 1,
        "volumes_json": [{"label": "VCe [ml]", "titrant": "T1"}],
        "titrants_json": [{"id": "T1", "label": "C(Ce)", "default": 0.1}],
    },
    {
        "nazwa": "DEA [%]",
        "formula": "((V1 - V2) * T1 * 10.5) / M",
        "mass_required": 1,
        "volumes_json": [
            {"label": "Vz [ml]", "titrant": "T1"},
            {"label": "Vf [ml]", "titrant": "T1"},
        ],
        "titrants_json": [{"id": "T1", "label": "C(HCl)", "default": 0.1}],
    },
    {
        "nazwa": "MEA [%]",
        "formula": "(V1 * T1 * 6.1) / M",
        "mass_required": 1,
        "volumes_json": [{"label": "VHCl [ml]", "titrant": "T1"}],
        "titrants_json": [{"id": "T1", "label": "C(HCl)", "default": 0.1}],
    },
    {
        "nazwa": "GP [%]",
        "formula": "((V1 - V2) * T1 * 76.09) / (20 * M)",
        "mass_required": 1,
        "volumes_json": [
            {"label": "Vs [ml]", "titrant": "T1"},
            {"label": "V [ml]", "titrant": "T1"},
        ],
        "titrants_json": [{"id": "T1", "label": "C(Na\u2082S\u2082O\u2083)", "default": 0.1}],
    },
    {
        "nazwa": "Siarczyny [%]",
        "formula": "(V1 * T1 * 8) / M",
        "mass_required": 1,
        "volumes_json": [{"label": "VJ [ml]", "titrant": "T1"}],
        "titrants_json": [{"id": "T1", "label": "C(J\u2082)", "default": 0.1}],
    },
    {
        "nazwa": "Chlorki [%]",
        "formula": "((V1 - V2) * T1 * 58.5) / (M * 10)",
        "mass_required": 1,
        "volumes_json": [
            {"label": "V(AgNO\u2083) [ml]", "titrant": "T1"},
            {"label": "V(SCN) [ml]", "titrant": "T1"},
        ],
        "titrants_json": [{"id": "T1", "label": "C(AgNO\u2083)", "default": 0.1}],
    },
    {
        "nazwa": "Liczba Kwasowa (LK)",
        "formula": "(V1 * T1 * 56.1) / M",
        "mass_required": 1,
        "volumes_json": [{"label": "V(KOH) [ml]", "titrant": "T1"}],
        "titrants_json": [{"id": "T1", "label": "C(KOH)", "default": 0.1}],
    },
    {
        "nazwa": "Wolne kwasy t\u0142uszczowe [%]",
        "formula": "(V1 * T1) / 56.1",
        "mass_required": 0,
        "volumes_json": [{"label": "LK [mg KOH/g]", "titrant": None}],
        "titrants_json": [{"id": "T1", "label": "A \u2014 masa mol. kwasu [g/mol]", "default": 282.5}],
    },
    {
        "nazwa": "Amidoestry (%AE)",
        "formula": "(V1 - V2) * T1 / (56.1 * 10)",
        "mass_required": 0,
        "volumes_json": [
            {"label": "Lz", "titrant": "T1"},
            {"label": "Lk", "titrant": "T1"},
        ],
        "titrants_json": [{"id": "T1", "label": "M amidoestru [g/mol]", "default": 459.08}],
    },
    {
        "nazwa": "Na\u2082SO\u2083 20% [%]",
        "formula": "(V1 * 12.6 * T1) / M",
        "mass_required": 1,
        "volumes_json": [{"label": "V(Na\u2082SO\u2083) [ml]", "titrant": "T1"}],
        "titrants_json": [{"id": "T1", "label": "C(jodu)", "default": 0.1}],
    },
    {
        "nazwa": "CHEGINY %AA",
        "formula": "(V1 * T1 * T2) / (M * 10)",
        "mass_required": 1,
        "volumes_json": [{"label": "V(HCl) [ml]", "titrant": "T1"}],
        "titrants_json": [
            {"id": "T1", "label": "C(HCl)", "default": 0.5},
            {
                "id": "T2",
                "label": "PRODUKT",
                "default": 307.0,
                "options": [
                    {"label": "K7 / KK / GL", "value": 307.0},
                    {"label": "GLO / GLOL / GLOS", "value": 300.0},
                    {"label": "Chegina", "value": 284.0},
                ],
            },
        ],
    },
]

_PARAM_METHOD_MAP = {
    "nacl": "Chlorki [%]",
    "aa": "CHEGINY %AA",
    "so3": "Siarczyny [%]",
    "h2o2": "Perhydrol [%]",
    "lk": "Liczba Kwasowa (LK)",
    "la": "Liczba Kwasowa (LK)",
    "wolna_amina": "DMAPA [%]",
}


def seed_metody(db):
    """INSERT OR IGNORE all titration methods, then link parametry_analityczne."""
    inserted = 0
    for m in METODY:
        db.execute(
            """
            INSERT OR IGNORE INTO metody_miareczkowe
                (nazwa, formula, mass_required, volumes_json, titrants_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                m["nazwa"],
                m["formula"],
                m["mass_required"],
                _json.dumps(m["volumes_json"], ensure_ascii=False),
                _json.dumps(m["titrants_json"], ensure_ascii=False),
            ),
        )
        if db.execute("SELECT changes()").fetchone()[0]:
            inserted += 1
    db.commit()

    # Build nazwa->id lookup
    nazwa_to_id = {
        row[0]: row[1]
        for row in db.execute("SELECT nazwa, id FROM metody_miareczkowe").fetchall()
    }

    linked = 0
    for kod, nazwa in _PARAM_METHOD_MAP.items():
        metoda_id = nazwa_to_id.get(nazwa)
        if metoda_id is None:
            print(f"  WARNING: method '{nazwa}' not found — skipping link for kod='{kod}'")
            continue
        db.execute(
            "UPDATE parametry_analityczne SET metoda_id=? WHERE kod=? AND metoda_id IS NULL",
            (metoda_id, kod),
        )
        if db.execute("SELECT changes()").fetchone()[0]:
            linked += 1
    db.commit()

    total = db.execute("SELECT COUNT(*) FROM metody_miareczkowe").fetchone()[0]
    print(f"seed_metody: {inserted} methods inserted ({total} total), {linked} parameter links updated")


# ---------------------------------------------------------------------------
# 6. __main__
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    db = get_db()
    init_mbr_tables(db)
    seed(db)
    seed_metody(db)
    seed_from_seed_mbr(db)
    db.close()
