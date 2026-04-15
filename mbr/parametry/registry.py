"""
parametry/registry.py — Centralized parameter query module.

Replaces hardcoded parameter configs by querying:
  - parametry_analityczne  (global parameter definitions)
  - parametry_etapy        (context/product bindings with limits)
"""

import sqlite3
from typing import Optional

from mbr.etapy.config import ETAPY_ANALIZY, PRODUCT_ETAPY_MAP
from mbr.etapy.models import get_process_stages, FULL_PIPELINE_PRODUCTS


# ---------------------------------------------------------------------------
# 1. get_parametry_for_kontekst
# ---------------------------------------------------------------------------

def get_parametry_for_kontekst(
    db: sqlite3.Connection, produkt: str, kontekst: str,
    krok: Optional[int] = None
) -> list[dict]:
    """Query parametry_etapy + parametry_analityczne for a given product/context.

    Product-specific rows win over NULL (shared) rows when the same kod appears
    in both. Sorted by kolejnosc.

    Args:
        krok: optional sub-step filter. When provided, returns only rows where
              pe.krok IS NULL (applies to all sub-steps) OR pe.krok = krok.

    Returns list of dicts:
        {kod, label, typ, min, max, precision, nawazka_g, formula,
         metoda: {nazwa, formula, factor} | None}
    """
    sql = """
        SELECT
            pa.kod,
            pa.label,
            pa.skrot,
            pa.typ,
            pe.min_limit   AS min,
            pe.max_limit   AS max,
            COALESCE(pe.precision, pa.precision, 2) AS precision,
            pe.nawazka_g,
            pe.target,
            pa.formula     AS global_formula,
            pe.formula     AS binding_formula,
            pe.sa_bias,
            pa.metoda_id,
            pa.jednostka,
            pa.metoda_nazwa,
            pa.metoda_formula,
            pa.metoda_factor,
            pe.produkt,
            pe.kolejnosc,
            pe.grupa
        FROM parametry_etapy pe
        JOIN parametry_analityczne pa ON pa.id = pe.parametr_id
        WHERE pe.kontekst = ?
          AND (pe.produkt = ? OR pe.produkt IS NULL)
    """
    params: list = [kontekst, produkt]
    if krok is not None:
        sql += "  AND (pe.krok IS NULL OR pe.krok = ?)\n"
        params.append(krok)
    sql += "ORDER BY pe.kolejnosc"
    rows = db.execute(sql, params).fetchall()

    # Deduplicate: product-specific wins over NULL
    # Build ordered list preserving first occurrence of each kod at
    # the correct kolejnosc, but prefer the product-specific row.
    seen: dict[str, dict] = {}      # kod → best row dict
    order: list[str] = []           # insertion order of kody

    for row in rows:
        kod = row["kod"]
        row_produkt = row["produkt"]

        if kod not in seen:
            seen[kod] = row
            order.append(kod)
        else:
            # If current row is product-specific and stored is NULL, replace
            if row_produkt is not None and seen[kod]["produkt"] is None:
                seen[kod] = row

    result = []
    for kod in order:
        r = seen[kod]
        metoda = None
        if r["typ"] == "titracja" and r["metoda_factor"] is not None:
            metoda = {
                "nazwa": r["metoda_nazwa"],
                "formula": r["metoda_formula"],
                "factor": r["metoda_factor"],
            }

        # Resolve formula — replace sa_bias placeholder with actual value
        formula = r["binding_formula"] or r["global_formula"]
        if formula and r["sa_bias"] is not None and "sa_bias" in formula:
            formula = formula.replace("sa_bias", str(r["sa_bias"]))

        result.append({
            "kod": r["kod"],
            "label": r["label"],
            "skrot": r["skrot"],
            "typ": r["typ"],
            "min": r["min"],
            "max": r["max"],
            "precision": r["precision"],
            "nawazka_g": r["nawazka_g"],
            "formula": formula,
            "sa_bias": r["sa_bias"],
            "metoda_id": r["metoda_id"],
            "metoda": metoda,
            "target": r["target"],
            "jednostka": r["jednostka"],
            "grupa": r["grupa"] or "lab",
        })

    return result


# ---------------------------------------------------------------------------
# 2. get_etapy_config
# ---------------------------------------------------------------------------

def get_etapy_config(db: sqlite3.Connection, produkt: str) -> dict:
    """Build stage config for a product from DB + legacy korekty.

    Returns {etap_name: {"label": str, "parametry": list, "korekty": list}}

    Replaces mbr.etapy_config.get_etapy_config() for the parametry part;
    korekty are still sourced from ETAPY_ANALIZY / PRODUCT_ETAPY_MAP.
    Returns {} for products without process stages.
    """
    stages = get_process_stages(produkt)
    if not stages:
        return {}

    # Resolve label + korekty source: prefer direct match, then parent mapping
    label_source = ETAPY_ANALIZY.get(produkt)
    if label_source is None:
        parent = PRODUCT_ETAPY_MAP.get(produkt)
        if parent:
            label_source = ETAPY_ANALIZY.get(parent)

    result = {}
    for etap in stages:
        parametry = get_parametry_for_kontekst(db, produkt, etap)

        # Resolve label and korekty from legacy config
        stage_legacy = (label_source or {}).get(etap, {})
        label = stage_legacy.get("label", etap.capitalize())
        korekty = stage_legacy.get("korekty", [])

        entry = {
            "label": label,
            "parametry": parametry,
            "korekty": korekty,
        }
        kroki = stage_legacy.get("kroki")
        if kroki:
            entry["kroki"] = kroki
        if stage_legacy.get("korekta_po_fakcie"):
            entry["korekta_po_fakcie"] = True
        result[etap] = entry

    return result


# ---------------------------------------------------------------------------
# 3. get_calc_methods
# ---------------------------------------------------------------------------

def get_calc_methods(db: sqlite3.Connection) -> dict:
    """Return calc method dict for all titracja params with a metoda_factor.

    Returns {kod: {"name": label, "method": metoda_nazwa,
                   "formula": metoda_formula, "factor": metoda_factor}}
    """
    rows = db.execute(
        """
        SELECT kod, label, metoda_nazwa, metoda_formula, metoda_factor
        FROM parametry_analityczne
        WHERE typ = 'titracja'
          AND metoda_factor IS NOT NULL
        """,
    ).fetchall()

    return {
        row["kod"]: {
            "name": row["label"],
            "method": row["metoda_nazwa"],
            "formula": row["metoda_formula"],
            "factor": row["metoda_factor"],
        }
        for row in rows
    }


# ---------------------------------------------------------------------------
# 4. build_parametry_lab
# ---------------------------------------------------------------------------

def build_parametry_lab(db: sqlite3.Connection, produkt: str) -> dict:
    """Build parametry_lab JSON-compatible snapshot for a batch.

    Backward-compatible with the format used by seed_mbr.py.

    Full-pipeline products → {"analiza": ..., "dodatki": ...}
    Simple products        → {"analiza_koncowa": ...}
    """
    def _build_pole(p: dict) -> dict:
        pole = {
            "kod": p["kod"],
            "label": p["label"],
            "skrot": p.get("skrot"),
            "tag": p["kod"],
            "typ": "float",
            "min": p["min"],
            "max": p["max"],
            "precision": p["precision"],
            "measurement_type": p["typ"],
        }
        if p.get("metoda_id"):
            pole["metoda_id"] = p["metoda_id"]
        if p["typ"] == "titracja" and p["metoda"] is not None:
            m = p["metoda"]
            pole["calc_method"] = {
                "name": m["nazwa"],
                "formula": m["formula"],
                "factor": m["factor"],
                "suggested_mass": p["nawazka_g"],
            }
        if p["typ"] == "obliczeniowy" and p["formula"]:
            pole["formula"] = p["formula"]
        if p.get("target") is not None:
            pole["target"] = p["target"]
        if p.get("jednostka"):
            pole["jednostka"] = p["jednostka"]
        pole["grupa"] = p.get("grupa", "lab")
        return pole

    if produkt in FULL_PIPELINE_PRODUCTS:
        analiza_params = get_parametry_for_kontekst(db, produkt, "analiza_koncowa")
        dodatki_params = get_parametry_for_kontekst(db, produkt, "dodatki")

        return {
            "analiza": {
                "label": "Analiza",
                "pola": [_build_pole(p) for p in analiza_params],
            },
            "dodatki": {
                "label": "Dodatki standaryzacyjne",
                "pola": [_build_pole(p) for p in dodatki_params],
            },
        }
    else:
        # Simple products use analiza_koncowa section directly
        # Try product-specific bindings first, fall back to generic query
        params = get_parametry_for_kontekst(db, produkt, "analiza_koncowa")
        return {
            "analiza_koncowa": {
                "label": "Analiza końcowa",
                "pola": [_build_pole(p) for p in params],
            },
        }


# ---------------------------------------------------------------------------
# 5. get_cert_params / get_cert_variant_params
# ---------------------------------------------------------------------------

def get_cert_params(db: sqlite3.Connection, produkt: str) -> list[dict]:
    """Get certificate parameters for a product from parametry_etapy.

    Returns base params (on_cert=1, cert_variant_id IS NULL) ordered by cert_kolejnosc.
    Decoupled from kontekst — params from any grupa (lab/kj/rnd) can appear on cert.
    """
    rows = db.execute("""
        SELECT
            pa.kod, pa.label, pa.name_en, pa.method_code,
            pe.cert_requirement, pe.cert_format, pe.cert_qualitative_result,
            pe.cert_kolejnosc, pe.parametr_id, pe.kontekst, pe.grupa,
            pc.name_pl AS cert_name_pl, pc.name_en AS cert_name_en, pc.method AS cert_method
        FROM parametry_etapy pe
        JOIN parametry_analityczne pa ON pa.id = pe.parametr_id
        LEFT JOIN parametry_cert pc ON pc.produkt = pe.produkt
            AND pc.parametr_id = pe.parametr_id AND pc.variant_id IS NULL
        WHERE pe.produkt = ? AND pe.on_cert = 1 AND pe.cert_variant_id IS NULL
        ORDER BY pe.cert_kolejnosc
    """, (produkt,)).fetchall()

    return [
        {
            "kod": r["kod"],
            "parametr_id": r["parametr_id"],
            "name_pl": r["cert_name_pl"] or r["label"] or "",
            "name_en": r["cert_name_en"] if r["cert_name_en"] is not None else (r["name_en"] or ""),
            "method": r["cert_method"] or r["method_code"] or "",
            "requirement": r["cert_requirement"] or "",
            "format": r["cert_format"] or "1",
            "qualitative_result": r["cert_qualitative_result"],
        }
        for r in rows
    ]


def get_cert_variant_params(db: sqlite3.Connection, cert_variant_db_id: int) -> list[dict]:
    """Get variant-specific add_parameters from parametry_etapy."""
    rows = db.execute("""
        SELECT
            pa.kod, pa.label, pa.name_en, pa.method_code,
            pe.cert_requirement, pe.cert_format, pe.cert_qualitative_result,
            pe.cert_kolejnosc, pe.parametr_id,
            pc.name_pl AS cert_name_pl, pc.name_en AS cert_name_en, pc.method AS cert_method
        FROM parametry_etapy pe
        JOIN parametry_analityczne pa ON pa.id = pe.parametr_id
        LEFT JOIN parametry_cert pc ON pc.parametr_id = pe.parametr_id
            AND pc.variant_id = pe.cert_variant_id
        WHERE pe.kontekst = 'cert_variant' AND pe.cert_variant_id = ?
        ORDER BY pe.cert_kolejnosc
    """, (cert_variant_db_id,)).fetchall()

    return [
        {
            "kod": r["kod"],
            "parametr_id": r["parametr_id"],
            "name_pl": r["cert_name_pl"] or r["label"] or "",
            "name_en": r["cert_name_en"] if r["cert_name_en"] is not None else (r["name_en"] or ""),
            "method": r["cert_method"] or r["method_code"] or "",
            "requirement": r["cert_requirement"] or "",
            "format": r["cert_format"] or "1",
            "qualitative_result": r["cert_qualitative_result"],
        }
        for r in rows
    ]


def get_konteksty(db: sqlite3.Connection) -> list[str]:
    """Return all distinct kontekst values from parametry_etapy."""
    rows = db.execute(
        "SELECT DISTINCT kontekst FROM parametry_etapy ORDER BY kontekst"
    ).fetchall()
    return [r["kontekst"] for r in rows]
