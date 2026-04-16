"""Build flat ML-ready rows from K7 pipeline batch data.

Columns are generated dynamically from pipeline config + actual data:
- Etapy (stages) read from produkt_pipeline + etapy_analityczne
- Parametry per etap read from etap_parametry + parametry_analityczne
- Korekty per etap read from etap_korekty_katalog
- Max rounds discovered from actual ebr_etap_sesja data
"""
import sqlite3
from functools import lru_cache

# Products with extended pipeline
K7_PRODUCTS = {"Chegina_K7"}

# Short prefixes for stage codes
_STAGE_PREFIX = {
    "sulfonowanie": "sulf", "utlenienie": "utl", "standaryzacja": "stand",
    "analiza_koncowa": "ak", "rozjasnianie": "rozj", "czwartorzedowanie": "czw",
    "amidowanie": "amid", "namca": "namca",
}

# Short suffixes for parameter codes
_PARAM_SHORT = {
    "ph_10proc": "ph", "nd20": "nd20", "so3": "so3", "barwa_I2": "barwa",
    "nadtlenki": "nadtlenki", "sm": "sm", "nacl": "nacl", "sa": "sa",
    "aa": "aa", "gestosc": "gestosc", "le_liczba_kwasowa": "le",
    "la_liczba_aminowa": "la", "barwa_hz": "barwa_hz", "metnosc_fau": "metnosc",
    "h2o2": "h2o2", "ph": "ph", "ph_1proc": "ph1",
    "barwa_gardner": "barwa_g",
}

# Short names for correction substances
_KOREKTA_SHORT = {
    "Siarczyn sodu": "na2so3", "Na2SO3": "na2so3",
    "Perhydrol 34%": "perhydrol", "Woda": "woda",
    "Kwas cytrynowy": "kwas", "NaCl": "nacl",
    "NaOH": "naoh", "MCA": "mca", "HCl": "hcl",
    "DMAPA": "dmapa",
}


def _load_pipeline_schema(db: sqlite3.Connection) -> dict:
    """Load pipeline structure: stages → params + corrections.

    Returns {etap_kod: {etap_id, prefix, params: [{kod, short}], korekty: [{substancja, short}]}}
    """
    # Use first K7 product to discover pipeline
    produkt = "Chegina_K7"
    pipeline = db.execute(
        """SELECT pp.etap_id, ea.kod, ea.nazwa
           FROM produkt_pipeline pp
           JOIN etapy_analityczne ea ON ea.id = pp.etap_id
           WHERE pp.produkt = ?
           ORDER BY pp.kolejnosc""",
        (produkt,),
    ).fetchall()

    schema = {}
    for step in pipeline:
        kod = step["kod"]
        etap_id = step["etap_id"]
        prefix = _STAGE_PREFIX.get(kod, kod[:4])

        # Parameters for this stage (filtered by product limits)
        params = db.execute(
            """SELECT pa.kod
               FROM etap_parametry ep
               JOIN parametry_analityczne pa ON pa.id = ep.parametr_id
               WHERE ep.etap_id = ?
               ORDER BY ep.kolejnosc""",
            (etap_id,),
        ).fetchall()
        # Filter to those with product limits defined
        product_pids = {r[0] for r in db.execute(
            "SELECT parametr_id FROM produkt_etap_limity WHERE produkt = ? AND etap_id = ?",
            (produkt, etap_id),
        ).fetchall()}
        if product_pids:
            param_ids_map = {r[0]: r[1] for r in db.execute(
                "SELECT id, kod FROM parametry_analityczne WHERE id IN ({})".format(
                    ",".join("?" for _ in product_pids)), list(product_pids),
            ).fetchall()}
            param_list = [{"kod": p["kod"], "short": _PARAM_SHORT.get(p["kod"], p["kod"])}
                          for p in params if db.execute(
                              "SELECT id FROM parametry_analityczne WHERE kod=?", (p["kod"],)
                          ).fetchone()["id"] in product_pids]
        else:
            param_list = [{"kod": p["kod"], "short": _PARAM_SHORT.get(p["kod"], p["kod"])} for p in params]

        # Corrections for this stage
        korekty = db.execute(
            "SELECT substancja FROM etap_korekty_katalog WHERE etap_id = ? ORDER BY kolejnosc",
            (etap_id,),
        ).fetchall()
        kor_list = [{"substancja": k["substancja"],
                     "short": _KOREKTA_SHORT.get(k["substancja"], k["substancja"].lower().replace(" ", "_"))}
                    for k in korekty]

        schema[kod] = {
            "etap_id": etap_id,
            "prefix": prefix,
            "params": param_list,
            "korekty": kor_list,
        }

    return schema


def _discover_max_rounds(db: sqlite3.Connection, after_id: int = 0) -> dict[str, int]:
    """Find max rounds per stage across all completed K7 batches."""
    products_placeholder = ",".join("?" for _ in K7_PRODUCTS)
    rows = db.execute(
        f"""SELECT ea.kod, MAX(s.runda) as max_runda
            FROM ebr_etap_sesja s
            JOIN etapy_analityczne ea ON ea.id = s.etap_id
            JOIN ebr_batches e ON e.ebr_id = s.ebr_id
            JOIN mbr_templates m ON m.mbr_id = e.mbr_id
            WHERE e.status = 'completed' AND e.typ = 'szarza'
              AND m.produkt IN ({products_placeholder})
              AND e.ebr_id > ?
            GROUP BY ea.kod""",
        (*K7_PRODUCTS, after_id),
    ).fetchall()
    result = {r["kod"]: r["max_runda"] for r in rows}
    # Ensure at least 1 round per stage
    return {k: max(v, 1) for k, v in result.items()}


def build_columns(db: sqlite3.Connection, after_id: int = 0) -> tuple[list[str], dict, dict[str, int]]:
    """Build CSV column list dynamically from pipeline config + actual data.

    Returns (columns, schema, max_rounds).
    """
    schema = _load_pipeline_schema(db)
    max_rounds = _discover_max_rounds(db, after_id)

    columns = ["ebr_id", "batch_id", "nr_partii", "masa_kg", "meff_kg", "dt_start", "dt_end", "pakowanie"]

    # Extra fields per stage
    _extra_before = {"sulfonowanie": ["sulf_na2so3_recept_kg"]}

    # Final stage (last in pipeline) provides final_* columns
    stage_order = list(schema.keys())
    final_stage = stage_order[-1] if stage_order else "standaryzacja"

    for etap_kod, cfg in schema.items():
        prefix = cfg["prefix"]

        # Extra fields before params
        for extra in _extra_before.get(etap_kod, []):
            columns.append(extra)

        # Param columns per round
        n_rounds = max_rounds.get(etap_kod, 1)
        for r in range(1, n_rounds + 1):
            for p in cfg["params"]:
                columns.append(f"{prefix}_r{r}_{p['short']}")
            # Corrections per round (only those that recur per round, like perhydrol)
            for kor in cfg["korekty"]:
                if n_rounds > 1:
                    columns.append(f"{prefix}_{kor['short']}_r{r}_kg")
                    if kor["substancja"] == "Kwas cytrynowy":
                        columns.append(f"{prefix}_{kor['short']}_r{r}_sugest_kg")

        # If single round, corrections without round suffix
        if n_rounds <= 1:
            for kor in cfg["korekty"]:
                columns.append(f"{prefix}_{kor['short']}_kg")
                if kor["substancja"] == "Kwas cytrynowy":
                    columns.append(f"{prefix}_{kor['short']}_sugest_kg")

        columns.append(f"{prefix}_rundy")

    # Targets
    columns.extend(["target_ph", "target_nd20"])

    # Final columns from last stage
    if final_stage in schema:
        for p in schema[final_stage]["params"]:
            columns.append(f"final_{p['short']}")
    columns.append("final_all_ok")

    return columns, schema, max_rounds


def export_k7_batches(db: sqlite3.Connection, after_id: int = 0) -> list[dict]:
    """Return flat dicts for completed K7 batches, one dict per batch."""
    columns, schema, max_rounds = build_columns(db, after_id)

    products_placeholder = ",".join("?" for _ in K7_PRODUCTS)
    batches = db.execute(
        f"""SELECT e.ebr_id, e.batch_id, e.nr_partii, e.wielkosc_szarzy_kg,
                   e.nastaw, e.dt_start, e.dt_end, m.produkt
            FROM ebr_batches e
            JOIN mbr_templates m ON m.mbr_id = e.mbr_id
            WHERE e.status = 'completed' AND e.typ = 'szarza'
              AND m.produkt IN ({products_placeholder})
              AND e.ebr_id > ?
            ORDER BY e.ebr_id""",
        (*K7_PRODUCTS, after_id),
    ).fetchall()

    rows = []
    for b in batches:
        ebr_id = b["ebr_id"]
        masa = b["wielkosc_szarzy_kg"] or b["nastaw"] or 0
        meff = (masa - 1000) if masa > 6600 else (masa - 500)

        row = {col: None for col in columns}
        row["ebr_id"] = ebr_id
        row["batch_id"] = b["batch_id"]
        row["nr_partii"] = b["nr_partii"]
        row["masa_kg"] = masa
        row["meff_kg"] = meff
        row["dt_start"] = b["dt_start"]
        row["dt_end"] = b["dt_end"]

        # Pakowanie type
        pak_row = db.execute(
            "SELECT pakowanie_bezposrednie FROM ebr_batches WHERE ebr_id = ?",
            (ebr_id,),
        ).fetchone()
        row["pakowanie"] = pak_row["pakowanie_bezposrednie"] if pak_row and pak_row["pakowanie_bezposrednie"] else "zbiornik"

        produkt = b["produkt"]

        # Targets from korekta_cele
        cele = db.execute(
            "SELECT kod, wartosc FROM korekta_cele WHERE produkt = ?",
            (produkt,),
        ).fetchall()
        for c in cele:
            if c["kod"] == "target_ph":
                row["target_ph"] = c["wartosc"]
            elif c["kod"] == "target_nd20":
                row["target_nd20"] = c["wartosc"]

        # Recipe Na2SO3
        recept = db.execute(
            "SELECT wartosc FROM ebr_wyniki WHERE ebr_id=? AND sekcja='sulfonowanie' AND kod_parametru='na2so3_recept_kg'",
            (ebr_id,),
        ).fetchone()
        if recept:
            row["sulf_na2so3_recept_kg"] = recept["wartosc"]

        # Load all sessions
        sesje = db.execute(
            """SELECT s.id, s.etap_id, s.runda, ea.kod as etap_kod
               FROM ebr_etap_sesja s
               JOIN etapy_analityczne ea ON ea.id = s.etap_id
               WHERE s.ebr_id = ?
               ORDER BY s.etap_id, s.runda""",
            (ebr_id,),
        ).fetchall()

        sesje_by_etap: dict[str, list] = {}
        for s in sesje:
            sesje_by_etap.setdefault(s["etap_kod"], []).append(s)

        # Fill stages dynamically
        stage_order = list(schema.keys())
        final_stage = stage_order[-1] if stage_order else None

        for etap_kod, cfg in schema.items():
            prefix = cfg["prefix"]
            etap_sesje = sesje_by_etap.get(etap_kod, [])
            n_max = max_rounds.get(etap_kod, 1)
            row[f"{prefix}_rundy"] = len(etap_sesje)

            # Measurements per round
            for s in etap_sesje:
                runda = s["runda"]
                if runda > n_max:
                    continue
                pomiary = db.execute(
                    """SELECT pa.kod, ep.wartosc, ep.w_limicie
                       FROM ebr_pomiar ep
                       JOIN parametry_analityczne pa ON pa.id = ep.parametr_id
                       WHERE ep.sesja_id = ?""",
                    (s["id"],),
                ).fetchall()
                for p in pomiary:
                    short = _PARAM_SHORT.get(p["kod"])
                    if short:
                        col = f"{prefix}_r{runda}_{short}"
                        if col in row:
                            row[col] = p["wartosc"]

                # Final columns from last stage, last round
                if etap_kod == final_stage and s == etap_sesje[-1]:
                    for p in pomiary:
                        short = _PARAM_SHORT.get(p["kod"])
                        if short:
                            fcol = f"final_{short}"
                            if fcol in row:
                                row[fcol] = p["wartosc"]
                                if p["w_limicie"] == 0:
                                    row["final_all_ok"] = 0

            # Corrections per round
            for s in etap_sesje:
                runda = s["runda"]
                korekty = db.execute(
                    """SELECT ek.substancja, k.ilosc, k.ilosc_wyliczona
                       FROM ebr_korekta_v2 k
                       JOIN etap_korekty_katalog ek ON ek.id = k.korekta_typ_id
                       WHERE k.sesja_id = ?""",
                    (s["id"],),
                ).fetchall()
                for k in korekty:
                    short = _KOREKTA_SHORT.get(k["substancja"],
                                               k["substancja"].lower().replace(" ", "_"))
                    if n_max > 1:
                        col = f"{prefix}_{short}_r{runda}_kg"
                        sugest_col = f"{prefix}_{short}_r{runda}_sugest_kg"
                    else:
                        col = f"{prefix}_{short}_kg"
                        sugest_col = f"{prefix}_{short}_sugest_kg"
                    if col in row:
                        row[col] = k["ilosc"]
                    if sugest_col in row and k["ilosc_wyliczona"] is not None:
                        row[sugest_col] = k["ilosc_wyliczona"]

        # Default final_all_ok
        if row.get("final_all_ok") is None and final_stage and sesje_by_etap.get(final_stage):
            row["final_all_ok"] = 1

        rows.append(row)

    return rows


# For backward compat with routes.py
def get_csv_columns(db: sqlite3.Connection) -> list[str]:
    """Return current CSV column list (dynamic)."""
    columns, _, _ = build_columns(db)
    return columns
