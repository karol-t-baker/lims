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
