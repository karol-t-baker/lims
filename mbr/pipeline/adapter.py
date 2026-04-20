"""
pipeline/adapter.py — Transform pipeline catalog data into the fast_entry
etapy_json + parametry_lab format consumed by _fast_entry_content.html.

This is a pure server-side adapter; the template does not need to change.
"""

import sqlite3
from mbr.pipeline.models import (
    get_produkt_pipeline,
    resolve_limity,
    get_etap,
    list_sesje,
    save_pomiar,
    evaluate_gate,
    get_etap_decyzje,
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
    Return calc_method dict for a titracja parameter.
    First tries parametry_analityczne inline fields, then falls back
    to metody_miareczkowe via metoda_id FK.
    """
    row = db.execute(
        """SELECT metoda_id, metoda_nazwa, metoda_formula, metoda_factor
           FROM parametry_analityczne
           WHERE id = ?""",
        (parametr_id,),
    ).fetchone()
    if row is None:
        return None

    nazwa = row["metoda_nazwa"]
    formula = row["metoda_formula"]
    factor = row["metoda_factor"]

    # Fallback to metody_miareczkowe if inline fields are empty
    if factor is None and row["metoda_id"]:
        mm = db.execute(
            "SELECT nazwa, formula FROM metody_miareczkowe WHERE id = ?",
            (row["metoda_id"],),
        ).fetchone()
        if mm:
            nazwa = nazwa or mm["nazwa"]
            formula = formula or mm["formula"]

    if not nazwa and not formula:
        return None

    return {
        "name":            nazwa or "",
        "formula":         formula or "",
        "factor":          factor,
        "suggested_mass":  nawazka_g,
        "method_id":       row["metoda_id"],
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
        "typ_analityczny":  typ,        # <-- raw parametry_analityczne.typ
        "measurement_type": measurement_type,
        "min":              param["min_limit"],
        "max":              param["max_limit"],
        "min_limit":        param["min_limit"],
        "max_limit":        param["max_limit"],
        "precision":        param["precision"],
        "spec_value":       param["spec_value"],
        "grupa":            param["grupa"] or "lab",
        "pe_id":            param.get("pe_id"),
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
                f = row["formula"]
                # Substitute sa_bias placeholder if we have a value
                sa_bias = param.get("sa_bias")
                if sa_bias is not None and "sa_bias" in f:
                    f = f.replace("sa_bias", str(sa_bias))
                pole["formula"] = f

    return pole



# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_pipeline_context(
    db: sqlite3.Connection, produkt: str, typ: str | None = None,
) -> dict | None:
    """
    Transform pipeline catalog data into the fast_entry template context.

    Args:
        produkt: product kod (matches ebr_batches.produkt / mbr_templates.produkt)
        typ: one of 'szarza' | 'zbiornik' | 'platkowanie' | None.
             None means no filter — union of all typy. Used for the
             completed-batch view which shows every measurement taken.

    Returns:
        {"etapy_json": list[dict], "parametry_lab": dict[str, dict]} or None
        if the product has no pipeline defined.
    """
    pipeline = get_produkt_pipeline(db, produkt)
    if not pipeline:
        return None

    etapy_json: list[dict] = []
    parametry_lab: dict[str, dict] = {}

    cykliczne = [s for s in pipeline if s["typ_cyklu"] == "cykliczny"]
    main_cykliczny_id = cykliczne[-1]["etap_id"] if cykliczne else None

    for step in pipeline:
        etap_id   = step["etap_id"]
        typ_cyklu = step["typ_cyklu"]
        nazwa     = step["nazwa"]
        nr        = step["kolejnosc"]

        etap = get_etap(db, etap_id)
        if etap is None:
            continue

        params = resolve_limity(db, produkt, etap_id)

        # Product-specific filter — restrict to parametr_ids present in
        # produkt_etap_limity for this (produkt, etap_id). When typ is set,
        # additionally require the matching dla_<typ> flag.
        if typ is None:
            filter_sql = (
                "SELECT parametr_id FROM produkt_etap_limity "
                "WHERE produkt = ? AND etap_id = ?"
            )
        else:
            flag_col = {
                "szarza":      "dla_szarzy",
                "zbiornik":    "dla_zbiornika",
                "platkowanie": "dla_platkowania",
            }.get(typ)
            if flag_col is None:
                raise ValueError(f"unknown typ: {typ!r}")
            filter_sql = (
                f"SELECT parametr_id FROM produkt_etap_limity "
                f"WHERE produkt = ? AND etap_id = ? AND {flag_col} = 1"
            )

        product_param_ids = {
            r[0] for r in db.execute(filter_sql, (produkt, etap_id)).fetchall()
        }
        params = [p for p in params if p["parametr_id"] in product_param_ids]

        # Skip etap entirely when filtering by typ and no params are visible.
        # This makes K7 zbiornik view show only analiza_koncowa (the stages
        # sulfonowanie/utlenienie/standaryzacja have dla_zbiornika=0).
        # For typ=None (completed-batch union view) keep all etapy.
        if not params and typ is not None:
            continue

        if typ_cyklu == "cykliczny" and etap_id == main_cykliczny_id:
            sekcja_key = "analiza"
        elif typ_cyklu == "cykliczny":
            sekcja_key = step["kod"]
        else:
            sekcja_key = step["kod"]

        etap_entry: dict = {
            "nr":               nr,
            "nazwa":            nazwa,
            "kod":              step["kod"],
            "read_only":        False,
            "sekcja_lab":       sekcja_key,
            "pipeline_etap_id": etap_id,
            "typ_cyklu":        typ_cyklu,
        }
        etapy_json.append(etap_entry)

        pola = [_build_pole(p, db) for p in params]
        if sekcja_key not in parametry_lab:
            parametry_lab[sekcja_key] = {"label": nazwa, "pola": pola}
        else:
            parametry_lab[sekcja_key]["pola"].extend(pola)

    for et in etapy_json:
        eid = et.get("pipeline_etap_id")
        if eid:
            et["decyzje_pass"] = get_etap_decyzje(db, eid, "pass")
            et["decyzje_fail"] = get_etap_decyzje(db, eid, "fail")
        else:
            et["decyzje_pass"] = []
            et["decyzje_fail"] = []

    return {"etapy_json": etapy_json, "parametry_lab": parametry_lab}


def pipeline_dual_write(db, ebr_id, sekcja, values, wpisal, odziedziczony_map=None):
    """Write measurements to ebr_pomiar and evaluate gate.

    Called after save_wyniki in save_entry route.
    Returns gate evaluation dict or None if no pipeline active.

    Args:
        sekcja: e.g. "analiza__1", "dodatki__1"
        values: {kod: wartosc} (already parsed floats, None for empty)
        wpisal: who wrote (actor label)
    """
    ebr = db.execute(
        """SELECT m.produkt FROM ebr_batches e
           JOIN mbr_templates m ON m.mbr_id = e.mbr_id
           WHERE e.ebr_id = ?""",
        (ebr_id,),
    ).fetchone()
    if not ebr:
        return None

    produkt = ebr["produkt"]
    pipeline = get_produkt_pipeline(db, produkt)
    if not pipeline:
        return None

    base_sekcja = sekcja.split("__")[0] if "__" in sekcja else sekcja

    # "dodatki" = corrections, no gate evaluation needed
    if base_sekcja == "dodatki" or base_sekcja.endswith("_dodatki"):
        return None

    # Find the pipeline stage that maps to this sekcja
    cykliczne = [s for s in pipeline if s["typ_cyklu"] == "cykliczny"]
    main_cykliczny_id = cykliczne[-1]["etap_id"] if cykliczne else None

    etap_id = None
    for step in pipeline:
        etap = get_etap(db, step["etap_id"])
        if not etap:
            continue
        # Main cykliczny stage uses sekcja "analiza"
        if etap["typ_cyklu"] == "cykliczny" and step["etap_id"] == main_cykliczny_id and base_sekcja == "analiza":
            etap_id = step["etap_id"]
            break
        # Other cykliczny stages use their own kod as sekcja
        if etap["typ_cyklu"] == "cykliczny" and etap["kod"] == base_sekcja:
            etap_id = step["etap_id"]
            break
        # jednorazowy stages: sekcja = stage kod
        if etap["typ_cyklu"] == "jednorazowy" and etap["kod"] == base_sekcja:
            etap_id = step["etap_id"]
            break

    if etap_id is None:
        return None

    # Find active session (latest nierozpoczety or w_trakcie for this stage)
    sesje = list_sesje(db, ebr_id, etap_id=etap_id)
    active = [s for s in sesje if s["status"] in ("nierozpoczety", "w_trakcie")]
    if not active:
        return None
    sesja = active[-1]

    # Build parametr_id + limit lookups
    resolved = resolve_limity(db, produkt, etap_id)
    kod_to_resolved = {r["kod"]: r for r in resolved}

    # Write to ebr_pomiar
    for kod, wartosc in values.items():
        r = kod_to_resolved.get(kod)
        if r is None:
            continue
        odz = 0
        if odziedziczony_map:
            odz = odziedziczony_map.get(kod, 0)
        save_pomiar(
            db, sesja["id"], r["parametr_id"],
            wartosc=wartosc,
            min_limit=r.get("min_limit"),
            max_limit=r.get("max_limit"),
            wpisal=wpisal,
            odziedziczony=odz,
        )

    # Evaluate gate
    gate = evaluate_gate(db, etap_id, sesja["id"])
    gate["sesja_id"] = sesja["id"]
    gate["etap_id"] = etap_id
    return gate


# ---------------------------------------------------------------------------
# Entry-form filtering
# ---------------------------------------------------------------------------

def filter_parametry_lab_for_entry(parametry_lab: dict) -> dict:
    """Filter a parametry_lab dict down to fields visible in the laborant entry form.

    Entry form shows only internal-lab numeric params:
      grupa == 'lab' (or missing, treated as 'lab')  AND
      typ_analityczny != 'jakosciowy'

    Sections that end up with no visible pola are dropped entirely so the UI
    doesn't render empty groups.

    The full parametry_lab snapshot is preserved in ebr_batches; this filter
    only affects what's *rendered* in the entry form. Hero view uses the
    unfiltered snapshot.
    """
    result: dict = {}
    for sekcja_key, sekcja in parametry_lab.items():
        pola = sekcja.get("pola", [])
        visible = [
            p for p in pola
            if (p.get("grupa") or "lab") == "lab"
            and p.get("typ_analityczny") != "jakosciowy"
        ]
        if visible:
            result[sekcja_key] = {**sekcja, "pola": visible}
    return result
