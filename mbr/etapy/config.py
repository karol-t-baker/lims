"""Process stage analytical parameter definitions per product."""

ETAPY_ANALIZY = {
    "Chegina_K7": {
        "amidowanie":        {"label": "Amidowanie",        "korekty": ["DMAPA", "Wydłużenie czasu"]},
        "smca":              {"label": "Wytworzenie SMCA",  "korekty": ["NaOH", "MCA"]},
        "czwartorzedowanie": {"label": "Czwartorzędowanie", "korekty": ["NaOH", "MCA"]},
        "sulfonowanie":      {"label": "Sulfonowanie",      "korekty": ["Na2SO3"]},
        "utlenienie":        {"label": "Utlenienie",        "korekty": ["Perhydrol"]},
    },
    "Chegina_K40GLOL": {
        "amidowanie":        {"label": "Amidowanie",        "korekty": ["DMAPA", "Wydłużenie czasu"]},
        "smca":              {"label": "Wytworzenie SMCA",  "korekty": ["NaOH", "MCA"]},
        "czwartorzedowanie": {"label": "Czwartorzędowanie", "korekty": ["NaOH", "MCA"]},
        "sulfonowanie":      {"label": "Sulfonowanie",      "korekty": ["Na2SO3"]},
        "utlenienie":        {"label": "Utlenienie",        "korekty": ["Kw. cytrynowy", "Perhydrol"]},
        "rozjasnianie":      {"label": "Rozjaśnianie",      "korekty": ["Perhydrol"]},
    },
    "Chegina_K40GLO": {
        "amidowanie": {
            "label": "Amidowanie",
            "korekty": ["DMAPA", "Wydłużenie czasu"],
            "kroki": [
                {"nr": 1, "label": "Synteza (po 7h)", "parametry": ["le", "barwa_fau"]},
                {"nr": 2, "label": "Zakończenie destylacji", "parametry": ["la", "barwa_fau"]},
            ],
        },
        "smca": {"label": "Wytworzenie SMCA", "korekty": ["NaOH", "MCA"]},
        "czwartorzedowanie": {
            "label": "Czwartorzędowanie",
            "korekty": ["NaOH", "MCA"],
            "kroki": [
                {"nr": 1, "label": "Po 1. porcji ługu", "parametry": ["ph_10proc", "nd20", "barwa_fau", "barwa_hz", "metnosc"]},
                {"nr": 2, "label": "Po 2. porcji ługu", "parametry": ["ph_10proc", "nd20", "aa", "barwa_fau", "barwa_hz", "metnosc"]},
            ],
        },
        "sulfonowanie": {"label": "Sulfonowanie", "korekty": ["Na2SO3"]},
        "utlenienie": {
            "label": "Utlenienie",
            "korekty": ["Kw. cytrynowy", "Perhydrol"],
            "kroki": [
                {"nr": 1, "label": "Obniżenie pH", "parametry": ["ph_10proc", "nd20", "barwa_fau", "barwa_hz", "metnosc", "so3"]},
                {"nr": 2, "label": "Utlenianie perhydrolem", "parametry": ["ph_10proc", "nd20", "barwa_fau", "barwa_hz", "metnosc", "so3", "nacl"]},
            ],
        },
        "rozjasnianie": {"label": "Rozjaśnianie", "korekty": ["Perhydrol"]},
    },
}

# Map product variants to their parent config
PRODUCT_ETAPY_MAP = {
    "Chegina_K40GL": "Chegina_K7",
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
