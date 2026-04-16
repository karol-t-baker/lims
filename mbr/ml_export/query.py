"""Build flat ML-ready rows from K7 pipeline batch data."""
import sqlite3

# Products with sulfonowanie → utlenienie → standaryzacja pipeline
K7_PRODUCTS = {"Chegina_K7", "Chegina_K40GL", "Chegina_K40GLO", "Chegina_K40GLOL"}

# Stage parameters
_SULF_PARAMS = ["ph_10proc", "nd20", "so3", "barwa_I2"]
_UTL_PARAMS = ["ph_10proc", "nd20", "so3", "barwa_I2", "nadtlenki"]
_STAND_PARAMS = ["ph_10proc", "nd20", "sm", "nacl", "sa"]

CSV_COLUMNS = [
    # Metadata
    "ebr_id", "batch_id", "nr_partii", "masa_kg", "meff_kg", "dt_start", "dt_end",
    # Sulfonowanie
    "sulf_na2so3_recept_kg",
    "sulf_r1_ph", "sulf_r1_nd20", "sulf_r1_so3", "sulf_r1_barwa",
    "sulf_na2so3_kor_kg", "sulf_perhydrol_kg",
    "sulf_r2_ph", "sulf_r2_nd20", "sulf_r2_so3", "sulf_r2_barwa",
    "sulf_rundy",
    # Utlenienie
    "utl_r1_ph", "utl_r1_nd20", "utl_r1_so3", "utl_r1_barwa", "utl_r1_nadtlenki",
    "utl_perhydrol_r1_kg",
    "utl_r2_ph", "utl_r2_nd20", "utl_r2_so3", "utl_r2_barwa", "utl_r2_nadtlenki",
    "utl_perhydrol_r2_kg",
    "utl_woda_kg", "utl_kwas_kg", "utl_kwas_sugest_kg",
    "utl_rundy",
    # Standaryzacja
    "stand_r1_ph", "stand_r1_nd20", "stand_r1_sm", "stand_r1_nacl", "stand_r1_sa",
    "stand_woda_kg", "stand_kwas_kg", "stand_kwas_sugest_kg",
    "stand_r2_ph", "stand_r2_nd20", "stand_r2_sm", "stand_r2_nacl", "stand_r2_sa",
    "stand_rundy",
    # Final
    "final_ph", "final_nd20", "final_sm", "final_nacl", "final_sa", "final_all_ok",
]

_PARAM_COL = {
    "ph_10proc": "ph", "nd20": "nd20", "so3": "so3",
    "barwa_I2": "barwa", "nadtlenki": "nadtlenki",
    "sm": "sm", "nacl": "nacl", "sa": "sa",
}


def export_k7_batches(db: sqlite3.Connection, after_id: int = 0) -> list[dict]:
    """Return flat dicts for completed K7 batches, one dict per batch."""
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

        row = {col: None for col in CSV_COLUMNS}
        row["ebr_id"] = ebr_id
        row["batch_id"] = b["batch_id"]
        row["nr_partii"] = b["nr_partii"]
        row["masa_kg"] = masa
        row["meff_kg"] = meff
        row["dt_start"] = b["dt_start"]
        row["dt_end"] = b["dt_end"]

        # Recipe Na2SO3
        recept = db.execute(
            "SELECT wartosc FROM ebr_wyniki WHERE ebr_id=? AND sekcja='sulfonowanie' AND kod_parametru='na2so3_recept_kg'",
            (ebr_id,),
        ).fetchone()
        if recept:
            row["sulf_na2so3_recept_kg"] = recept["wartosc"]

        # Load all sessions for this batch
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

        _fill_stage(db, row, sesje_by_etap.get("sulfonowanie", []), "sulf", _SULF_PARAMS)
        _fill_stage(db, row, sesje_by_etap.get("utlenienie", []), "utl", _UTL_PARAMS)
        _fill_stage(db, row, sesje_by_etap.get("standaryzacja", []), "stand", _STAND_PARAMS)
        _fill_corrections(db, row, sesje_by_etap)
        _fill_final(db, row, sesje_by_etap)

        rows.append(row)

    return rows


def _fill_stage(db, row, sesje, prefix, param_kods):
    row[f"{prefix}_rundy"] = len(sesje)
    for s in sesje:
        runda = s["runda"]
        if runda > 2:
            continue
        pomiary = db.execute(
            """SELECT pa.kod, ep.wartosc
               FROM ebr_pomiar ep
               JOIN parametry_analityczne pa ON pa.id = ep.parametr_id
               WHERE ep.sesja_id = ?""",
            (s["id"],),
        ).fetchall()
        for p in pomiary:
            col_suffix = _PARAM_COL.get(p["kod"])
            if col_suffix and p["kod"] in param_kods:
                col = f"{prefix}_r{runda}_{col_suffix}"
                if col in row:
                    row[col] = p["wartosc"]


def _fill_corrections(db, row, sesje_by_etap):
    for s in sesje_by_etap.get("sulfonowanie", []):
        korekty = db.execute(
            """SELECT ek.substancja, k.ilosc, k.ilosc_wyliczona
               FROM ebr_korekta_v2 k
               JOIN etap_korekty_katalog ek ON ek.id = k.korekta_typ_id
               WHERE k.sesja_id = ?""",
            (s["id"],),
        ).fetchall()
        for k in korekty:
            if k["substancja"] == "Siarczyn sodu":
                row["sulf_na2so3_kor_kg"] = k["ilosc"]
            elif k["substancja"] == "Perhydrol 34%":
                row["sulf_perhydrol_kg"] = k["ilosc"]

    for s in sesje_by_etap.get("utlenienie", []):
        runda = s["runda"]
        korekty = db.execute(
            """SELECT ek.substancja, k.ilosc, k.ilosc_wyliczona
               FROM ebr_korekta_v2 k
               JOIN etap_korekty_katalog ek ON ek.id = k.korekta_typ_id
               WHERE k.sesja_id = ?""",
            (s["id"],),
        ).fetchall()
        for k in korekty:
            if k["substancja"] == "Perhydrol 34%" and runda <= 2:
                row[f"utl_perhydrol_r{runda}_kg"] = k["ilosc"]
            elif k["substancja"] == "Woda":
                row["utl_woda_kg"] = k["ilosc"]
            elif k["substancja"] == "Kwas cytrynowy":
                row["utl_kwas_kg"] = k["ilosc"]
                if k["ilosc_wyliczona"] is not None:
                    row["utl_kwas_sugest_kg"] = k["ilosc_wyliczona"]

    for s in sesje_by_etap.get("standaryzacja", []):
        korekty = db.execute(
            """SELECT ek.substancja, k.ilosc, k.ilosc_wyliczona
               FROM ebr_korekta_v2 k
               JOIN etap_korekty_katalog ek ON ek.id = k.korekta_typ_id
               WHERE k.sesja_id = ?""",
            (s["id"],),
        ).fetchall()
        for k in korekty:
            if k["substancja"] == "Woda":
                row["stand_woda_kg"] = k["ilosc"]
            elif k["substancja"] == "Kwas cytrynowy":
                row["stand_kwas_kg"] = k["ilosc"]
                if k["ilosc_wyliczona"] is not None:
                    row["stand_kwas_sugest_kg"] = k["ilosc_wyliczona"]


def _fill_final(db, row, sesje_by_etap):
    stand_sesje = sesje_by_etap.get("standaryzacja", [])
    if not stand_sesje:
        return
    last = stand_sesje[-1]
    pomiary = db.execute(
        """SELECT pa.kod, ep.wartosc, ep.w_limicie
           FROM ebr_pomiar ep
           JOIN parametry_analityczne pa ON pa.id = ep.parametr_id
           WHERE ep.sesja_id = ?""",
        (last["id"],),
    ).fetchall()
    all_ok = True
    for p in pomiary:
        col = _PARAM_COL.get(p["kod"])
        if col and p["kod"] in _STAND_PARAMS:
            row[f"final_{col}"] = p["wartosc"]
            if p["w_limicie"] == 0:
                all_ok = False
    row["final_all_ok"] = 1 if all_ok else 0
