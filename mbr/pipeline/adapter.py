"""
pipeline/adapter.py — Transform pipeline catalog data into the fast_entry
etapy_json + parametry_lab format consumed by _fast_entry_content.html.

This is a pure server-side adapter; the template does not need to change.
"""

import sqlite3
from mbr.pipeline.models import (
    get_produkt_pipeline,
    resolve_limity,
    list_etap_korekty,
    get_etap,
)


# ---------------------------------------------------------------------------
# Type mapping: parametry_analityczne.typ -> measurement_type token
# ---------------------------------------------------------------------------

_TYP_MAP: dict[str, str] = {
    "bezposredni": "bezp",
    "titracja":    "titracja",
    "obliczeniowy": "obliczeniowy",
    "binarny":     "binarny",
    "jakosciowy":  "bezp",
}

# Types that need a numeric float input in the UI
_FLOAT_TYPY = {"bezposredni", "titracja", "obliczeniowy", "jakosciowy"}


def _measurement_type(typ: str) -> str:
    return _TYP_MAP.get(typ, "bezp")


def _pole_typ(typ: str) -> str:
    """Return the JSON 'typ' field for a parameter (float / bool)."""
    if typ == "binarny":
        return "bool"
    return "float"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_calc_method(
    db: sqlite3.Connection, parametr_id: int, nawazka_g: float | None = None
) -> dict | None:
    """
    Return calc_method dict for a titracja parameter by querying
    parametry_analityczne for metoda_nazwa/formula/factor.
    nawazka_g comes from etap_parametry (passed by caller).
    Returns None if no metoda_factor is set.
    """
    row = db.execute(
        """SELECT metoda_nazwa, metoda_formula, metoda_factor
           FROM parametry_analityczne
           WHERE id = ?""",
        (parametr_id,),
    ).fetchone()
    if row is None or row["metoda_factor"] is None:
        return None
    return {
        "name":            row["metoda_nazwa"] or "",
        "formula":         row["metoda_formula"] or "",
        "factor":          row["metoda_factor"],
        "suggested_mass":  nawazka_g,
    }


def _resolve_formula(param: dict) -> str | None:
    """
    Return formula for obliczeniowy parameter.
    Uses etap_parametry.formula (param["formula"]) first,
    then falls back to parametry_analityczne.formula (fetched inline).
    Substitutes literal 'sa_bias' with the actual sa_bias value if present.
    """
    formula = param.get("formula")
    if not formula:
        return None
    sa_bias = param.get("sa_bias")
    if sa_bias is not None:
        formula = formula.replace("sa_bias", str(sa_bias))
    return formula


def _build_pole(param: dict, db: sqlite3.Connection) -> dict:
    """
    Convert a resolved-limits row (from resolve_limity) into a pole dict
    suitable for parametry_lab["sekcja"]["pola"].
    """
    typ = param["typ"]
    measurement_type = _measurement_type(typ)

    pole: dict = {
        "kod":              param["kod"],
        "label":            param["label"],
        "skrot":            param["skrot"] or param["kod"],
        "tag":              param["kod"],
        "typ":              _pole_typ(typ),
        "measurement_type": measurement_type,
        "min":              param["min_limit"],
        "max":              param["max_limit"],
        "min_limit":        param["min_limit"],
        "max_limit":        param["max_limit"],
        "precision":        param["precision"],
        "target":           param["target"],
        "grupa":            param["grupa"] or "lab",
    }

    if measurement_type == "titracja":
        # Pull calc_method from parametry_analityczne
        parametr_id = param.get("parametr_id")
        if parametr_id:
            cm = _fetch_calc_method(db, parametr_id, nawazka_g=param.get("nawazka_g"))
            if cm:
                pole["metoda_id"] = db.execute(
                    "SELECT metoda_id FROM parametry_analityczne WHERE id = ?",
                    (parametr_id,),
                ).fetchone()["metoda_id"]
                pole["calc_method"] = cm

    elif measurement_type == "obliczeniowy":
        formula = _resolve_formula(param)
        if formula:
            pole["formula"] = formula
        else:
            # fallback: read formula from parametry_analityczne
            row = db.execute(
                "SELECT formula FROM parametry_analityczne WHERE id = ?",
                (param.get("parametr_id"),),
            ).fetchone()
            if row and row["formula"]:
                pole["formula"] = row["formula"]

    return pole


def _build_korekty_pola(korekty: list[dict]) -> list[dict]:
    """
    Convert etap_korekty_katalog rows into additional-input 'pola' for the
    'dodatki' section (one correction substance → one float field).
    """
    pola = []
    for k in korekty:
        subst = k["substancja"]
        pola.append({
            "kod":              subst,
            "label":            f"{subst.replace('_', ' ').title()} [{k['jednostka']}]",
            "skrot":            subst,
            "tag":              subst,
            "typ":              "float",
            "measurement_type": "bezp",
            "min":              0,
            "max":              None,
            "min_limit":        None,
            "max_limit":        None,
            "precision":        1,
            "target":           None,
            "grupa":            "lab",
        })
    return pola


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_pipeline_context(
    db: sqlite3.Connection, produkt: str
) -> dict | None:
    """
    Transform pipeline catalog data into the fast_entry template context.

    Returns:
        {
            "etapy_json":    list[dict],
            "parametry_lab": dict[str, dict],
        }
    or None if the product has no pipeline defined.

    The returned structure is directly compatible with the existing
    _fast_entry_content.html / JavaScript round-cycling logic:
      - cykliczny stages use sekcja key "analiza" + companion "dodatki"
      - jednorazowy stages use sekcja key = stage kod
    """
    pipeline = get_produkt_pipeline(db, produkt)
    if not pipeline:
        return None

    etapy_json: list[dict] = []
    parametry_lab: dict[str, dict] = {}

    for step in pipeline:
        etap_id  = step["etap_id"]
        typ_cyklu = step["typ_cyklu"]
        nazwa    = step["nazwa"]
        nr       = step["kolejnosc"]

        etap = get_etap(db, etap_id)
        if etap is None:
            continue

        params = resolve_limity(db, produkt, etap_id)

        if typ_cyklu == "cykliczny":
            sekcja_key = "analiza"
        else:
            sekcja_key = step["kod"]

        # --- primary etap entry ---
        etap_entry: dict = {
            "nr":               nr,
            "nazwa":            nazwa,
            "read_only":        False,
            "sekcja_lab":       sekcja_key,
            "pipeline_etap_id": etap_id,
            "typ_cyklu":        typ_cyklu,
        }
        etapy_json.append(etap_entry)

        # --- parametry_lab section ---
        pola = [_build_pole(p, db) for p in params]

        if sekcja_key not in parametry_lab:
            parametry_lab[sekcja_key] = {
                "label": nazwa,
                "pola":  pola,
            }
        else:
            # Merge pola if sekcja already populated (multiple stages →
            # same key, which shouldn't happen in practice but handle it)
            parametry_lab[sekcja_key]["pola"].extend(pola)

        # --- cykliczny: add companion "dodatki" entry ---
        if typ_cyklu == "cykliczny":
            korekty = list_etap_korekty(db, etap_id)
            korekty_pola = _build_korekty_pola(korekty)

            dodatki_entry: dict = {
                "nr":         nr + 0.5,
                "nazwa":      f"Dodatki {nazwa.lower()}",
                "read_only":  False,
                "sekcja_lab": "dodatki",
            }
            etapy_json.append(dodatki_entry)

            if "dodatki" not in parametry_lab:
                parametry_lab["dodatki"] = {
                    "label": f"Dodatki {nazwa.lower()}",
                    "pola":  korekty_pola,
                }

    return {
        "etapy_json":    etapy_json,
        "parametry_lab": parametry_lab,
    }
