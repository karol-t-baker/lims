"""Certificate (Świadectwa) database helpers."""

from datetime import datetime


def create_swiadectwo(db, ebr_id, template_name, nr_partii, pdf_path, wystawil, data_json=None):
    now = datetime.now().isoformat(timespec="seconds")
    cur = db.execute(
        "INSERT INTO swiadectwa (ebr_id, template_name, nr_partii, pdf_path, dt_wystawienia, wystawil, data_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ebr_id, template_name, nr_partii, pdf_path, now, wystawil, data_json),
    )
    db.commit()
    return cur.lastrowid


def mark_swiadectwa_outdated(db, ebr_id):
    """Mark all certificates for this EBR as outdated (parameters changed)."""
    db.execute(
        "UPDATE swiadectwa SET nieaktualne = 1 WHERE ebr_id = ? AND (nieaktualne IS NULL OR nieaktualne = 0)",
        (ebr_id,),
    )
    db.commit()


def list_swiadectwa(db, ebr_id):
    rows = db.execute(
        "SELECT * FROM swiadectwa WHERE ebr_id = ? ORDER BY dt_wystawienia DESC",
        (ebr_id,),
    ).fetchall()
    return [dict(r) for r in rows]
