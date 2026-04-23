"""Certificate (Świadectwa) database helpers.

Neither helper commits — callers own the transaction. Internal commit here
used to split the caller's transaction mid-flow, so a subsequent failure
couldn't roll back the cert row.
"""

from datetime import datetime

from mbr.shared.timezone import app_now_iso


def create_swiadectwo(db, ebr_id, template_name, nr_partii, pdf_path, wystawil,
                     data_json=None, target_produkt=None):
    now = app_now_iso()
    cur = db.execute(
        "INSERT INTO swiadectwa (ebr_id, template_name, nr_partii, pdf_path, "
        "dt_wystawienia, wystawil, data_json, target_produkt) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ebr_id, template_name, nr_partii, pdf_path, now, wystawil,
         data_json, target_produkt),
    )
    return cur.lastrowid


def mark_swiadectwa_outdated(db, ebr_id):
    """Mark all certificates for this EBR as outdated (parameters changed)."""
    db.execute(
        "UPDATE swiadectwa SET nieaktualne = 1 WHERE ebr_id = ? AND (nieaktualne IS NULL OR nieaktualne = 0)",
        (ebr_id,),
    )


def list_swiadectwa(db, ebr_id):
    rows = db.execute(
        "SELECT * FROM swiadectwa WHERE ebr_id = ? ORDER BY dt_wystawienia DESC",
        (ebr_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_pipeline_wyniki_flat(db, ebr_id: int) -> dict:
    """Return {kod: row} from ebr_pomiar — latest non-null per parametr.

    Provides the same shape as the ebr_wyniki-flattened dict that the cert
    generator consumes, so certs for pipeline-era szarże (which skip the
    legacy ebr_wyniki path) work without a separate downstream code branch.
    """
    rows = db.execute(
        """SELECT pa.kod,
                  p.wartosc,
                  p.wpisal,
                  p.dt_wpisu,
                  p.w_limicie,
                  p.min_limit,
                  p.max_limit
           FROM ebr_pomiar p
           JOIN ebr_etap_sesja s ON s.id = p.sesja_id
           JOIN parametry_analityczne pa ON pa.id = p.parametr_id
           WHERE s.ebr_id = ? AND p.wartosc IS NOT NULL
           ORDER BY p.dt_wpisu DESC, p.id DESC""",
        (ebr_id,),
    ).fetchall()
    flat: dict = {}
    for r in rows:
        kod = r["kod"]
        if kod not in flat:
            flat[kod] = dict(r)
    return flat
