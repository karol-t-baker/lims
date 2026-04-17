"""Build flat ML-ready rows from K7 pipeline batch data.

Column set is generated from pipeline config + a PINNED max-rounds dict so
the schema stays stable across exports. Auto-discovery was previously used;
it caused the column list to grow when any batch introduced more rounds,
which broke CSV concatenation across time.
"""
import json
import sqlite3
from functools import lru_cache

# Products with extended pipeline
K7_PRODUCTS = {"Chegina_K7"}

# Pinned per-etap round cap. Raise these as the process evolves; the only
# cost is a few extra null columns. DO NOT switch back to auto-discovery:
# historical CSVs must concatenate cleanly.
FIXED_MAX_ROUNDS = {
    "sulfonowanie": 3,
    "utlenienie": 3,
    "standaryzacja": 3,
    "analiza_koncowa": 1,
}

# Batch statuses eligible for export. Widen via export_k7_batches(statuses=...)
# to include e.g. 'cancelled' as negative training examples.
DEFAULT_STATUSES: tuple = ("completed",)

# Substances whose ilosc_wyliczona carries a formula suggestion worth emitting
# as *_sugest_kg — the operator's deviation from the formula is the signal
# ML should learn. "Woda" is kept for legacy data (pre-rename); new inserts
# use "Woda łącznie".
_FORMULA_DRIVEN = {"Kwas cytrynowy", "Perhydrol 34%", "Woda łącznie", "Woda"}

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

# Short names for correction substances. Both "Woda" and "Woda łącznie" map
# to the same "woda" export key so pre-/post-rename data flow into one column.
_KOREKTA_SHORT = {
    "Siarczyn sodu": "na2so3", "Na2SO3": "na2so3",
    "Perhydrol 34%": "perhydrol",
    "Woda": "woda", "Woda łącznie": "woda",
    "Kwas cytrynowy": "kwas", "NaCl": "nacl",
    "NaOH": "naoh", "MCA": "mca", "HCl": "hcl",
    "DMAPA": "dmapa",
}


def _load_pipeline_schema(db: sqlite3.Connection) -> dict:
    """Load pipeline structure: stages → params + corrections.

    Returns {etap_kod: {etap_id, prefix, params: [{kod, short}], korekty: [{substancja, short}]}}
    """
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

        params = db.execute(
            """SELECT pa.kod
               FROM etap_parametry ep
               JOIN parametry_analityczne pa ON pa.id = ep.parametr_id
               WHERE ep.etap_id = ?
               ORDER BY ep.kolejnosc""",
            (etap_id,),
        ).fetchall()
        product_pids = {r[0] for r in db.execute(
            "SELECT parametr_id FROM produkt_etap_limity WHERE produkt = ? AND etap_id = ?",
            (produkt, etap_id),
        ).fetchall()}
        if product_pids:
            param_list = [{"kod": p["kod"], "short": _PARAM_SHORT.get(p["kod"], p["kod"])}
                          for p in params if db.execute(
                              "SELECT id FROM parametry_analityczne WHERE kod=?", (p["kod"],)
                          ).fetchone()["id"] in product_pids]
        else:
            param_list = [{"kod": p["kod"], "short": _PARAM_SHORT.get(p["kod"], p["kod"])} for p in params]

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


def build_columns(db: sqlite3.Connection) -> tuple[list[str], dict]:
    """Build the (stable) CSV column list.

    Returns (columns, schema). Round count is taken from FIXED_MAX_ROUNDS.
    """
    schema = _load_pipeline_schema(db)

    columns = [
        "ebr_id", "batch_id", "nr_partii", "status",
        "masa_kg", "meff_kg", "dt_start", "dt_end", "pakowanie",
    ]

    _extra_before = {"sulfonowanie": ["sulf_na2so3_recept_kg"]}

    stage_order = list(schema.keys())
    final_stage = stage_order[-1] if stage_order else "standaryzacja"

    for etap_kod, cfg in schema.items():
        prefix = cfg["prefix"]

        for extra in _extra_before.get(etap_kod, []):
            columns.append(extra)

        n_rounds = FIXED_MAX_ROUNDS.get(etap_kod, 1)
        for r in range(1, n_rounds + 1):
            columns.append(f"{prefix}_r{r}_dt_start")
            columns.append(f"{prefix}_r{r}_wpisal")
            for p in cfg["params"]:
                columns.append(f"{prefix}_r{r}_{p['short']}")
            for kor in cfg["korekty"]:
                columns.append(f"{prefix}_{kor['short']}_r{r}_kg")
                if kor["substancja"] in _FORMULA_DRIVEN:
                    columns.append(f"{prefix}_{kor['short']}_r{r}_sugest_kg")
                columns.append(f"{prefix}_{kor['short']}_r{r}_zalecil")

        columns.append(f"{prefix}_rundy")

    columns.extend(["target_ph", "target_nd20"])

    if final_stage in schema:
        for p in schema[final_stage]["params"]:
            columns.append(f"final_{p['short']}")
    columns.append("final_all_ok")

    return columns, schema


def _sesja_has_cele_column(db: sqlite3.Connection) -> bool:
    """Check whether ebr_etap_sesja has the cele_json column (defence against
    exports against DBs predating the migration)."""
    try:
        cols = [r[1] for r in db.execute("PRAGMA table_info(ebr_etap_sesja)").fetchall()]
        return "cele_json" in cols
    except Exception:
        return False


def _batch_targets(db: sqlite3.Connection, ebr_id: int, produkt: str,
                   stand_etap_id: int | None, has_cele_col: bool) -> tuple:
    """Return (target_ph, target_nd20) for a batch. Prefer the snapshot on
    the first standaryzacja sesja; fall back to current globals."""
    target_ph = None
    target_nd20 = None
    if has_cele_col and stand_etap_id:
        row = db.execute(
            "SELECT cele_json FROM ebr_etap_sesja "
            "WHERE ebr_id=? AND etap_id=? AND cele_json IS NOT NULL "
            "ORDER BY runda LIMIT 1",
            (ebr_id, stand_etap_id),
        ).fetchone()
        if row and row["cele_json"]:
            try:
                cele = json.loads(row["cele_json"])
                target_ph = cele.get("target_ph")
                target_nd20 = cele.get("target_nd20")
            except (json.JSONDecodeError, TypeError):
                pass
    if target_ph is None or target_nd20 is None:
        cele_rows = db.execute(
            "SELECT kod, wartosc FROM korekta_cele WHERE produkt = ?",
            (produkt,),
        ).fetchall()
        for c in cele_rows:
            if c["kod"] == "target_ph" and target_ph is None:
                target_ph = c["wartosc"]
            elif c["kod"] == "target_nd20" and target_nd20 is None:
                target_nd20 = c["wartosc"]
    return target_ph, target_nd20


def export_k7_batches(db: sqlite3.Connection, after_id: int = 0,
                      statuses: tuple | list = DEFAULT_STATUSES) -> list[dict]:
    """Return flat dicts for K7 batches matching `statuses`, one dict per batch.

    Rows for rounds beyond FIXED_MAX_ROUNDS are DROPPED from the output; the
    {prefix}_rundy column still reflects the true count so the caller can tell
    a batch was truncated.
    """
    columns, schema = build_columns(db)
    has_cele_col = _sesja_has_cele_column(db)

    products_placeholder = ",".join("?" for _ in K7_PRODUCTS)
    statuses = tuple(statuses)
    if not statuses:
        return []
    status_placeholder = ",".join("?" for _ in statuses)

    batches = db.execute(
        f"""SELECT e.ebr_id, e.batch_id, e.nr_partii, e.wielkosc_szarzy_kg,
                   e.nastaw, e.dt_start, e.dt_end, e.status, m.produkt
            FROM ebr_batches e
            JOIN mbr_templates m ON m.mbr_id = e.mbr_id
            WHERE e.status IN ({status_placeholder}) AND e.typ = 'szarza'
              AND m.produkt IN ({products_placeholder})
              AND e.ebr_id > ?
            ORDER BY e.ebr_id""",
        (*statuses, *K7_PRODUCTS, after_id),
    ).fetchall()

    stage_order = list(schema.keys())
    final_stage = stage_order[-1] if stage_order else None
    stand_etap_id = schema.get("standaryzacja", {}).get("etap_id")

    rows = []
    for b in batches:
        ebr_id = b["ebr_id"]
        masa = b["wielkosc_szarzy_kg"] or b["nastaw"] or 0
        meff = (masa - 1000) if masa > 6600 else (masa - 500)

        row = {col: None for col in columns}
        row["ebr_id"] = ebr_id
        row["batch_id"] = b["batch_id"]
        row["nr_partii"] = b["nr_partii"]
        row["status"] = b["status"]
        row["masa_kg"] = masa
        row["meff_kg"] = meff
        row["dt_start"] = b["dt_start"]
        row["dt_end"] = b["dt_end"]

        pak_row = db.execute(
            "SELECT pakowanie_bezposrednie FROM ebr_batches WHERE ebr_id = ?",
            (ebr_id,),
        ).fetchone()
        row["pakowanie"] = pak_row["pakowanie_bezposrednie"] if pak_row and pak_row["pakowanie_bezposrednie"] else "zbiornik"

        produkt = b["produkt"]

        tph, tnd = _batch_targets(db, ebr_id, produkt, stand_etap_id, has_cele_col)
        row["target_ph"] = tph
        row["target_nd20"] = tnd

        recept = db.execute(
            "SELECT wartosc FROM ebr_wyniki WHERE ebr_id=? AND sekcja='sulfonowanie' AND kod_parametru='na2so3_recept_kg'",
            (ebr_id,),
        ).fetchone()
        if recept:
            row["sulf_na2so3_recept_kg"] = recept["wartosc"]

        sesje_cols = "s.id, s.etap_id, s.runda, s.dt_start, s.laborant, ea.kod as etap_kod"
        sesje = db.execute(
            f"""SELECT {sesje_cols}
                FROM ebr_etap_sesja s
                JOIN etapy_analityczne ea ON ea.id = s.etap_id
                WHERE s.ebr_id = ?
                ORDER BY s.etap_id, s.runda""",
            (ebr_id,),
        ).fetchall()

        sesje_by_etap: dict[str, list] = {}
        for s in sesje:
            sesje_by_etap.setdefault(s["etap_kod"], []).append(s)

        for etap_kod, cfg in schema.items():
            prefix = cfg["prefix"]
            etap_sesje = sesje_by_etap.get(etap_kod, [])
            n_max = FIXED_MAX_ROUNDS.get(etap_kod, 1)
            row[f"{prefix}_rundy"] = len(etap_sesje)

            for s in etap_sesje:
                runda = s["runda"]
                if runda > n_max:
                    continue

                dt_col = f"{prefix}_r{runda}_dt_start"
                if dt_col in row:
                    row[dt_col] = s["dt_start"]

                pomiary = db.execute(
                    """SELECT pa.kod, ep.wartosc, ep.w_limicie, ep.wpisal
                       FROM ebr_pomiar ep
                       JOIN parametry_analityczne pa ON pa.id = ep.parametr_id
                       WHERE ep.sesja_id = ?""",
                    (s["id"],),
                ).fetchall()

                first_wpisal = None
                for p in pomiary:
                    if first_wpisal is None and p["wpisal"]:
                        first_wpisal = p["wpisal"]
                    short = _PARAM_SHORT.get(p["kod"])
                    if short:
                        col = f"{prefix}_r{runda}_{short}"
                        if col in row:
                            row[col] = p["wartosc"]

                wpisal_col = f"{prefix}_r{runda}_wpisal"
                if wpisal_col in row:
                    row[wpisal_col] = first_wpisal or s["laborant"]

                if etap_kod == final_stage and s == etap_sesje[-1]:
                    for p in pomiary:
                        short = _PARAM_SHORT.get(p["kod"])
                        if short:
                            fcol = f"final_{short}"
                            if fcol in row:
                                row[fcol] = p["wartosc"]
                                if p["w_limicie"] == 0:
                                    row["final_all_ok"] = 0

            for s in etap_sesje:
                runda = s["runda"]
                if runda > n_max:
                    continue
                korekty = db.execute(
                    """SELECT ek.substancja, k.ilosc, k.ilosc_wyliczona, k.zalecil
                       FROM ebr_korekta_v2 k
                       JOIN etap_korekty_katalog ek ON ek.id = k.korekta_typ_id
                       WHERE k.sesja_id = ?""",
                    (s["id"],),
                ).fetchall()
                for k in korekty:
                    short = _KOREKTA_SHORT.get(k["substancja"],
                                               k["substancja"].lower().replace(" ", "_"))
                    col = f"{prefix}_{short}_r{runda}_kg"
                    sugest_col = f"{prefix}_{short}_r{runda}_sugest_kg"
                    zalecil_col = f"{prefix}_{short}_r{runda}_zalecil"
                    if col in row:
                        row[col] = k["ilosc"]
                    if sugest_col in row and k["ilosc_wyliczona"] is not None:
                        row[sugest_col] = k["ilosc_wyliczona"]
                    if zalecil_col in row:
                        row[zalecil_col] = k["zalecil"]

        if row.get("final_all_ok") is None and final_stage and sesje_by_etap.get(final_stage):
            row["final_all_ok"] = 1

        rows.append(row)

    return rows


def get_csv_columns(db: sqlite3.Connection) -> list[str]:
    """Return the current (stable) CSV column list."""
    columns, _ = build_columns(db)
    return columns
