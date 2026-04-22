"""Build the schema.json dictionary for the ML export package.

Self-describing: data scientist learns parameter units, specs, formulas, and
target candidacy without needing to query the DB. Auto-generated from
parametry_analityczne + produkt_etap_limity + mbr_templates.parametry_lab +
etap_korekty_katalog.
"""
import json
import sqlite3
from datetime import datetime, timezone

EXPORT_VERSION = "1.0"

# Parameters that represent recipe doses rather than measurements. Extend as
# new recipe-level params are added. Not derived from parametry_analityczne.grupa
# because that column is dominated by 'lab' and doesn't separate cleanly.
_RECIPE_PARAMS = {"na2so3_recept_kg"}


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pipeline_etapy(db: sqlite3.Connection, produkt: str) -> list[dict]:
    rows = db.execute(
        """SELECT ea.kod, ea.nazwa, pp.kolejnosc
             FROM produkt_pipeline pp
             JOIN etapy_analityczne ea ON ea.id = pp.etap_id
            WHERE pp.produkt = ?
         ORDER BY pp.kolejnosc""",
        (produkt,),
    ).fetchall()
    return [{"kod": r["kod"], "label": r["nazwa"], "kolejnosc": r["kolejnosc"]} for r in rows]


def _target_candidates_from_parametry_lab(parametry_lab_json: str) -> set[str]:
    """Parameter codes that appear in analiza_koncowa with at least one min/max limit."""
    try:
        data = json.loads(parametry_lab_json or "{}")
    except json.JSONDecodeError:
        return set()
    ak = data.get("analiza_koncowa") or {}
    out = set()
    for p in ak.get("pola", []):
        if p.get("min_limit") is not None or p.get("max_limit") is not None:
            out.add(p.get("kod"))
    return out


def _formula_from_parametry_lab(parametry_lab_json: str) -> dict[str, str]:
    """Map param_kod -> formula string, sourced from mbr_templates.parametry_lab."""
    try:
        data = json.loads(parametry_lab_json or "{}")
    except json.JSONDecodeError:
        return {}
    out = {}
    for etap_cfg in data.values():
        for p in (etap_cfg or {}).get("pola", []):
            if p.get("formula"):
                out[p["kod"]] = p["formula"]
    return out


def _specs_per_etap(db: sqlite3.Connection, produkt: str) -> dict[str, dict[str, dict]]:
    """Return {param_kod: {etap_kod: {min, max}}} from produkt_etap_limity."""
    rows = db.execute(
        """SELECT pa.kod AS param_kod, ea.kod AS etap_kod,
                  pel.min_limit, pel.max_limit
             FROM produkt_etap_limity pel
             JOIN parametry_analityczne pa ON pa.id = pel.parametr_id
             JOIN etapy_analityczne    ea ON ea.id = pel.etap_id
            WHERE pel.produkt = ?""",
        (produkt,),
    ).fetchall()
    out: dict[str, dict[str, dict]] = {}
    for r in rows:
        if r["min_limit"] is None and r["max_limit"] is None:
            continue
        out.setdefault(r["param_kod"], {})[r["etap_kod"]] = {
            "min": r["min_limit"], "max": r["max_limit"],
        }
    return out


def _build_parametry(db: sqlite3.Connection, produkt: str) -> dict[str, dict]:
    row = db.execute(
        "SELECT parametry_lab FROM mbr_templates WHERE produkt=? ORDER BY wersja DESC LIMIT 1",
        (produkt,),
    ).fetchone()
    parametry_lab_json = row["parametry_lab"] if row else "{}"

    targets = _target_candidates_from_parametry_lab(parametry_lab_json)
    template_formulas = _formula_from_parametry_lab(parametry_lab_json)
    specs = _specs_per_etap(db, produkt)

    params = db.execute(
        "SELECT kod, label, skrot, typ, precision, formula, jednostka "
        "FROM parametry_analityczne ORDER BY id"
    ).fetchall()
    out: dict[str, dict] = {}
    for p in params:
        kod = p["kod"]
        is_calc = (p["typ"] == "obliczeniowy") or bool(p["formula"]) or kod in template_formulas
        out[kod] = {
            "kod": kod,
            "label": p["label"],
            "skrot": p["skrot"],
            "jednostka": p["jednostka"],
            "precision": p["precision"],
            "kategoria": "recipe" if kod in _RECIPE_PARAMS else "measurement",
            "typ_pomiaru": p["typ"],
            "is_calculated": is_calc,
            "formula": p["formula"] or template_formulas.get(kod),
            "is_target_candidate": kod in targets,
            "specs_per_etap": specs.get(kod, {}),
        }
    return out


def _build_substancje(db: sqlite3.Connection) -> dict[str, dict]:
    """Build substancje_korekcji dict for schema.json.

    A substancja is "formula-driven" if either:
      - etap_korekty_katalog.formula_ilosc has a non-empty value for it, OR
      - any ebr_korekta_v2.ilosc_wyliczona row references it.
    """
    rows = db.execute(
        """
        SELECT DISTINCT substancja
        FROM etap_korekty_katalog
        WHERE substancja IS NOT NULL
        """
    ).fetchall()
    from_katalog = {r["substancja"] for r in rows}

    with_formula = set()
    for r in db.execute(
        """
        SELECT DISTINCT substancja
        FROM etap_korekty_katalog
        WHERE formula_ilosc IS NOT NULL AND TRIM(formula_ilosc) <> ''
        """
    ).fetchall():
        with_formula.add(r["substancja"])

    for r in db.execute(
        """
        SELECT DISTINCT ekk.substancja
        FROM ebr_korekta_v2 ekv
        JOIN etap_korekty_katalog ekk ON ekk.id = ekv.korekta_typ_id
        WHERE ekv.ilosc_wyliczona IS NOT NULL
          AND ekk.substancja IS NOT NULL
        """
    ).fetchall():
        with_formula.add(r["substancja"])

    # Also pick up substancje that appear in ebr_korekta_v2 but not katalog.
    # (Theoretical only — ebr_korekta_v2 FKs through katalog, so this is a no-op
    # unless someone inserts a v2 row with NULL korekta_typ_id. Kept for safety.)
    for r in db.execute(
        """
        SELECT DISTINCT ekk.substancja
        FROM ebr_korekta_v2 ekv
        JOIN etap_korekty_katalog ekk ON ekk.id = ekv.korekta_typ_id
        WHERE ekk.substancja IS NOT NULL
        """
    ).fetchall():
        from_katalog.add(r["substancja"])

    return {
        s: {"is_formula_driven": s in with_formula}
        for s in sorted(from_katalog)
    }


def _table_has_column(db: sqlite3.Connection, table: str, col: str) -> bool:
    try:
        cols = [r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()]
        return col in cols
    except sqlite3.Error:
        return False


def build_schema(db: sqlite3.Connection, produkty: list[str],
                 counts: dict[str, int] | None = None) -> dict:
    """Build the schema.json dictionary. `counts` is optional — if caller already
    knows row counts, pass them; otherwise zeros are emitted."""
    produkt = produkty[0] if produkty else ""
    return {
        "export_version": EXPORT_VERSION,
        "generated_at": _iso_now(),
        "produkt_filter": list(produkty),
        "counts": counts or {"batches": 0, "sessions": 0, "measurements": 0, "corrections": 0},
        "etapy": _pipeline_etapy(db, produkt),
        "parametry": _build_parametry(db, produkt),
        "substancje_korekcji": _build_substancje(db),
    }
