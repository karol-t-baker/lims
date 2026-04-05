"""Process stage analytical parameter definitions per product."""

ETAPY_ANALIZY = {
    "Chegina_K7": {
        "amidowanie": {
            "label": "Amidowanie",
            "parametry": [
                {"kod": "le", "label": "LE (liczba estrowa)", "typ": "bezposredni", "min": None, "max": None},
                {"kod": "la", "label": "LA (liczba kwasowa)", "typ": "titracja", "min": None, "max": 5.0},
                {"kod": "lk", "label": "LK (końcowa)", "typ": "titracja", "min": None, "max": 1.0},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni", "min": None, "max": None},
            ],
            "korekty": [],
        },
        "smca": {
            "label": "Wytworzenie SMCA",
            "parametry": [
                {"kod": "ph", "label": "pH roztworu", "typ": "bezposredni", "min": 3.0, "max": 4.0},
            ],
            "korekty": ["NaOH", "MCA"],
        },
        "czwartorzedowanie": {
            "label": "Czwartorzędowanie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni", "min": 11.0, "max": 12.0},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni", "min": None, "max": None},
                {"kod": "aa", "label": "%AA", "typ": "titracja", "min": None, "max": 0.50},
            ],
            "korekty": ["NaOH", "MCA"],
        },
        "sulfonowanie": {
            "label": "Sulfonowanie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni", "min": None, "max": None},
                {"kod": "so3", "label": "%SO₃²⁻", "typ": "titracja", "min": None, "max": 0.30},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni", "min": None, "max": None},
            ],
            "korekty": ["Na2SO3"],
        },
        "utlenienie": {
            "label": "Utlenienie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni", "min": None, "max": None},
                {"kod": "so3", "label": "%SO₃²⁻", "typ": "titracja", "min": None, "max": 0.000},
                {"kod": "h2o2", "label": "%H₂O₂", "typ": "titracja", "min": None, "max": 0.010},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni", "min": None, "max": None},
            ],
            "korekty": ["Perhydrol"],
        },
    },
    "Chegina_K40GLOL": {
        "amidowanie": {
            "label": "Amidowanie",
            "parametry": [
                {"kod": "le", "label": "LE", "typ": "bezposredni", "min": None, "max": None},
                {"kod": "la", "label": "LA", "typ": "titracja", "min": None, "max": 5.0},
                {"kod": "lk", "label": "LK", "typ": "titracja", "min": None, "max": 1.0},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni", "min": None, "max": None},
            ],
            "korekty": [],
        },
        "smca": {
            "label": "Wytworzenie SMCA",
            "parametry": [
                {"kod": "ph", "label": "pH roztworu", "typ": "bezposredni", "min": 3.0, "max": 4.0},
            ],
            "korekty": ["NaOH", "MCA"],
        },
        "czwartorzedowanie": {
            "label": "Czwartorzędowanie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni", "min": 11.0, "max": 12.0},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni", "min": None, "max": None},
                {"kod": "aa", "label": "%AA", "typ": "titracja", "min": None, "max": 0.30},
            ],
            "korekty": ["NaOH", "MCA"],
        },
        "sulfonowanie": {
            "label": "Sulfonowanie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni", "min": None, "max": None},
                {"kod": "so3", "label": "%SO₃²⁻", "typ": "titracja", "min": None, "max": 0.30},
                {"kod": "h2o2", "label": "%H₂O₂", "typ": "titracja", "min": None, "max": None},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni", "min": None, "max": None},
            ],
            "korekty": ["Na2SO3"],
        },
        "utlenienie": {
            "label": "Utlenienie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni", "min": None, "max": None},
                {"kod": "so3", "label": "%SO₃²⁻", "typ": "titracja", "min": None, "max": 0.030},
                {"kod": "h2o2", "label": "%H₂O₂", "typ": "titracja", "min": None, "max": 0.010},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni", "min": None, "max": None},
            ],
            "korekty": ["Kw. cytrynowy", "Perhydrol"],
        },
        "rozjasnianie": {
            "label": "Rozjaśnianie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni", "min": None, "max": None},
                {"kod": "h2o2", "label": "%H₂O₂", "typ": "titracja", "min": 0.005, "max": 0.050},
                {"kod": "barwa_fau", "label": "Barwa FAU", "typ": "bezposredni", "min": None, "max": 5},
                {"kod": "barwa_hz", "label": "Barwa Hz", "typ": "bezposredni", "min": None, "max": 150},
            ],
            "korekty": ["Perhydrol"],
        },
    },
}

# Map product variants to their parent config
PRODUCT_ETAPY_MAP = {
    "Chegina_K40GL": "Chegina_K7",
    "Chegina_K40GLO": "Chegina_K7",
    "Chegina_K7B": "Chegina_K7",
    "Chegina_K7GLO": "Chegina_K7",
    "Chegina_K40GLOS": "Chegina_K40GLOL",
    "Chegina_K40GLOL_HQ": "Chegina_K40GLOL",
    "Chegina_K40GLN": "Chegina_K40GLOL",
    "Chegina_GLOL40": "Chegina_K40GLOL",
}


def get_etapy_config(produkt: str) -> dict:
    """Get stage config for a product. Falls back to parent via PRODUCT_ETAPY_MAP."""
    if produkt in ETAPY_ANALIZY:
        return ETAPY_ANALIZY[produkt]
    parent = PRODUCT_ETAPY_MAP.get(produkt)
    if parent and parent in ETAPY_ANALIZY:
        return ETAPY_ANALIZY[parent]
    return {}


# OCR field name → LIMS kod mapping (OCR uses 'procent_aa', LIMS uses 'aa')
OCR_KOD_MAP = {
    "procent_aa": "aa",
    "procent_so3": "so3",
    "procent_h2o2": "h2o2",
    "procent_sm": "sm",
    "procent_nacl": "nacl",
    "procent_sa": "sa",
    "ph_10proc": "ph_10proc",
    "nd20": "nd20",
    "ph": "ph",
    "barwa_fau": "barwa_fau",
    "barwa_hz": "barwa_hz",
    "la_liczba_kwasowa": "la",
    "le_liczba_estrowa": "le",
    "lk_liczba_kwasowa": "lk",
}

# OCR etap name → LIMS etap name mapping
OCR_ETAP_MAP = {
    "amid": "amidowanie",
    "smca": "smca",
    "czwartorzedowanie": "czwartorzedowanie",
    "sulfonowanie": "sulfonowanie",
    "utlenienie": "utlenienie",
    "wybielanie": "rozjasnianie",
    "standaryzacja": "standaryzacja",
}
