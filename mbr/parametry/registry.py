"""
parametry/registry.py — Centralized parameter query module.

Replaces hardcoded parameter configs by querying:
  - parametry_analityczne  (global parameter definitions)
  - parametry_etapy        (context/product bindings with limits)
"""

import sqlite3
from typing import Optional

from mbr.etapy.config import ETAPY_ANALIZY, PRODUCT_ETAPY_MAP
from mbr.etapy.models import get_process_stages


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

    Thin wrapper over build_pipeline_context(typ=None) — returns the union
    of all typy's parameters, keyed by sekcja_key (e.g. "analiza_koncowa"
    for simple products; "sulfonowanie"/"utlenienie"/"analiza" for K7).

    Post MVP 2026-04-16: this function's "analiza"+"dodatki" two-section
    format for FULL_PIPELINE_PRODUCTS is gone — shape now mirrors what the
    render path actually uses. Called from parametry/routes.py to refresh
    mbr_templates.parametry_lab snapshot after param/binding edits.
    """
    from mbr.pipeline.adapter import build_pipeline_context
    ctx = build_pipeline_context(db, produkt, typ=None)
    if ctx is None:
        return {}
    return ctx["parametry_lab"]


# ---------------------------------------------------------------------------
# 5. get_cert_params / get_cert_variant_params
# ---------------------------------------------------------------------------

def get_cert_params(db: sqlite3.Connection, produkt: str) -> list[dict]:
    """Get base certificate parameters for a product from parametry_cert.

    Returns rows with variant_id IS NULL (base cert, not variant-specific),
    ordered by kolejnosc. Parameter metadata (kod, label, name_en, method_code)
    is joined from parametry_analityczne; cert-specific overrides (name_pl,
    name_en, method) come from parametry_cert itself.
    """
    rows = db.execute("""
        SELECT
            pa.kod, pa.label, pa.name_en, pa.method_code,
            pa.typ, pa.grupa,
            pc.requirement, pc.format, pc.qualitative_result,
            pc.kolejnosc, pc.parametr_id,
            pc.name_pl AS cert_name_pl, pc.name_en AS cert_name_en, pc.method AS cert_method
        FROM parametry_cert pc
        JOIN parametry_analityczne pa ON pa.id = pc.parametr_id
        WHERE pc.produkt = ? AND pc.variant_id IS NULL
        ORDER BY pc.kolejnosc
    """, (produkt,)).fetchall()

    return [
        {
            "kod": r["kod"],
            "parametr_id": r["parametr_id"],
            "typ": r["typ"],
            "grupa": r["grupa"],
            "name_pl": r["cert_name_pl"] or r["label"] or "",
            "name_en": r["cert_name_en"] if r["cert_name_en"] is not None else (r["name_en"] or ""),
            "method": r["cert_method"] or r["method_code"] or "",
            "requirement": r["requirement"] or "",
            "format": r["format"] or "1",
            "qualitative_result": r["qualitative_result"],
        }
        for r in rows
    ]


def get_cert_variant_params(db: sqlite3.Connection, cert_variant_db_id: int) -> list[dict]:
    """Get variant-specific add_parameters from parametry_cert."""
    rows = db.execute("""
        SELECT
            pa.kod, pa.label, pa.name_en, pa.method_code,
            pa.typ, pa.grupa,
            pc.requirement, pc.format, pc.qualitative_result,
            pc.kolejnosc, pc.parametr_id,
            pc.name_pl AS cert_name_pl, pc.name_en AS cert_name_en, pc.method AS cert_method
        FROM parametry_cert pc
        JOIN parametry_analityczne pa ON pa.id = pc.parametr_id
        WHERE pc.variant_id = ?
        ORDER BY pc.kolejnosc
    """, (cert_variant_db_id,)).fetchall()

    return [
        {
            "kod": r["kod"],
            "parametr_id": r["parametr_id"],
            "typ": r["typ"],
            "grupa": r["grupa"],
            "name_pl": r["cert_name_pl"] or r["label"] or "",
            "name_en": r["cert_name_en"] if r["cert_name_en"] is not None else (r["name_en"] or ""),
            "method": r["cert_method"] or r["method_code"] or "",
            "requirement": r["requirement"] or "",
            "format": r["format"] or "1",
            "qualitative_result": r["qualitative_result"],
        }
        for r in rows
    ]


def get_konteksty(db: sqlite3.Connection) -> list[str]:
    """Return all distinct kontekst values from parametry_etapy."""
    rows = db.execute(
        "SELECT DISTINCT kontekst FROM parametry_etapy ORDER BY kontekst"
    ).fetchall()
    return [r["kontekst"] for r in rows]
