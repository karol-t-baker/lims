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
    db: sqlite3.Connection, produkt: str, kontekst: str
) -> list[dict]:
    """Query parametry_etapy + parametry_analityczne for a given product/context.

    Product-specific rows win over NULL (shared) rows when the same kod appears
    in both. Sorted by kolejnosc.

    Returns list of dicts:
        {kod, label, typ, min, max, precision, nawazka_g, formula,
         metoda: {nazwa, formula, factor} | None}
    """
    rows = db.execute(
        """
        SELECT
            pa.kod,
            pa.label,
            pa.skrot,
            pa.typ,
            pe.min_limit   AS min,
            pe.max_limit   AS max,
            pa.precision,
            pe.nawazka_g,
            pa.formula     AS global_formula,
            pe.formula     AS binding_formula,
            pa.metoda_id,
            pa.metoda_nazwa,
            pa.metoda_formula,
            pa.metoda_factor,
            pe.produkt,
            pe.kolejnosc
        FROM parametry_etapy pe
        JOIN parametry_analityczne pa ON pa.id = pe.parametr_id
        WHERE pe.kontekst = ?
          AND (pe.produkt = ? OR pe.produkt IS NULL)
        ORDER BY pe.kolejnosc
        """,
        (kontekst, produkt),
    ).fetchall()

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

        result.append({
            "kod": r["kod"],
            "label": r["label"],
            "skrot": r["skrot"],
            "typ": r["typ"],
            "min": r["min"],
            "max": r["max"],
            "precision": r["precision"],
            "nawazka_g": r["nawazka_g"],
            "formula": r["binding_formula"] or r["global_formula"],
            "metoda_id": r["metoda_id"],
            "metoda": metoda,
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

        result[etap] = {
            "label": label,
            "parametry": parametry,
            "korekty": korekty,
        }

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


def get_konteksty(db: sqlite3.Connection) -> list[str]:
    """Return all distinct kontekst values from parametry_etapy."""
    rows = db.execute(
        "SELECT DISTINCT kontekst FROM parametry_etapy ORDER BY kontekst"
    ).fetchall()
    return [r["kontekst"] for r in rows]
