"""CRUD for process stage analyses and corrections."""

import sqlite3
from datetime import datetime


def save_etap_analizy(
    db: sqlite3.Connection, ebr_id: int, etap: str, runda: int,
    wyniki: dict, user: str
) -> None:
    """Save analytical results for a process stage round.

    Args:
        ebr_id: batch ID
        etap: stage name ('amidowanie', 'czwartorzedowanie', etc.)
        runda: round number (1, 2, 3...)
        wyniki: {kod: value} e.g. {"ph_10proc": 11.76, "nd20": 1.3952}
        user: who entered the data
    """
    now = datetime.now().isoformat(timespec="seconds")
    for kod, value in wyniki.items():
        if value is None or value == "":
            continue
        # Support hybrid: numeric or text (mętność)
        val = None
        val_text = None
        try:
            val = float(value)
        except (ValueError, TypeError):
            val_text = str(value).strip()
            if not val_text:
                continue

        # Audit: log old value before overwrite
        old = db.execute(
            "SELECT id, wartosc, wartosc_text FROM ebr_etapy_analizy WHERE ebr_id=? AND etap=? AND runda=? AND kod_parametru=?",
            (ebr_id, etap, runda, kod),
        ).fetchone()
        if old:
            old_val = str(old["wartosc"]) if old["wartosc"] is not None else old["wartosc_text"] or ""
            new_val = str(val) if val is not None else val_text or ""
            if old_val != new_val:
                db.execute(
                    "INSERT INTO audit_log (dt, tabela, rekord_id, pole, stara_wartosc, nowa_wartosc, zmienil) VALUES (?,?,?,?,?,?,?)",
                    (now, "ebr_etapy_analizy", old["id"], kod, old_val, new_val, user),
                )

        db.execute(
            """INSERT INTO ebr_etapy_analizy (ebr_id, etap, runda, kod_parametru, wartosc, wartosc_text, dt_wpisu, wpisal)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(ebr_id, etap, runda, kod_parametru)
               DO UPDATE SET wartosc=excluded.wartosc, wartosc_text=excluded.wartosc_text, dt_wpisu=excluded.dt_wpisu, wpisal=excluded.wpisal""",
            (ebr_id, etap, runda, kod, val, val_text, now, user),
        )
    db.commit()


def get_etap_analizy(db: sqlite3.Connection, ebr_id: int, etap: str = None) -> dict:
    """Get all analyses for a batch, optionally filtered by stage.

    Returns:
        {etap: {runda: {kod: wartosc}}}
    """
    sql = "SELECT etap, runda, kod_parametru, wartosc, dt_wpisu, wpisal FROM ebr_etapy_analizy WHERE ebr_id = ?"
    params = [ebr_id]
    if etap:
        sql += " AND etap = ?"
        params.append(etap)
    sql += " ORDER BY etap, runda, kod_parametru"

    result = {}
    for row in db.execute(sql, params).fetchall():
        e, r, kod, val, dt, who = row
        if e not in result:
            result[e] = {}
        if r not in result[e]:
            result[e][r] = {}
        result[e][r][kod] = {"wartosc": val, "dt_wpisu": dt, "wpisal": who}
    return result


def get_all_etapy_analizy(db: sqlite3.Connection, ebr_id: int) -> list[dict]:
    """Get all analyses as flat list of dicts (for API response)."""
    rows = db.execute(
        "SELECT id, etap, runda, kod_parametru, wartosc, dt_wpisu, wpisal FROM ebr_etapy_analizy WHERE ebr_id = ? ORDER BY etap, runda",
        (ebr_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_korekta(
    db: sqlite3.Connection, ebr_id: int, etap: str, po_rundzie: int,
    substancja: str, ilosc_kg: float, user: str
) -> int:
    """Add a correction recommendation. Returns korekta ID."""
    now = datetime.now().isoformat(timespec="seconds")
    cur = db.execute(
        """INSERT INTO ebr_korekty (ebr_id, etap, po_rundzie, substancja, ilosc_kg, zalecil, dt_zalecenia)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (ebr_id, etap, po_rundzie, substancja, ilosc_kg, user, now),
    )
    db.commit()
    return cur.lastrowid


def confirm_korekta(db: sqlite3.Connection, korekta_id: int) -> None:
    """Mark a correction as executed."""
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "UPDATE ebr_korekty SET wykonano = 1, dt_wykonania = ? WHERE id = ?",
        (now, korekta_id),
    )
    db.commit()


def get_korekty(db: sqlite3.Connection, ebr_id: int, etap: str = None) -> list[dict]:
    """Get all corrections for a batch."""
    sql = "SELECT * FROM ebr_korekty WHERE ebr_id = ?"
    params = [ebr_id]
    if etap:
        sql += " AND etap = ?"
        params.append(etap)
    sql += " ORDER BY etap, po_rundzie, id"
    return [dict(r) for r in db.execute(sql, params).fetchall()]


# ---------------------------------------------------------------------------
# Stage status tracking
# ---------------------------------------------------------------------------

# Process stages that get tracked (before standaryzacja)
PROCESS_STAGES_K7 = ["amidowanie", "smca", "czwartorzedowanie", "sulfonowanie", "utlenienie"]
PROCESS_STAGES_GLOL = ["amidowanie", "smca", "czwartorzedowanie", "sulfonowanie", "utlenienie", "rozjasnianie"]

GLOL_PRODUCTS = {"Chegina_K40GLOL", "Chegina_K40GLOS", "Chegina_K40GLOL_HQ", "Chegina_K40GLN", "Chegina_GLOL40"}

# Products that have full process pipeline (ETAPY_FULL or ETAPY_FULL_GLOL)
FULL_PIPELINE_PRODUCTS = {
    "Chegina_K7", "Chegina_K40GL", "Chegina_K40GLO",
    "Chegina_K40GLOL", "Chegina_K40GLOS", "Chegina_K40GLOL_HQ", "Chegina_K40GLN", "Chegina_GLOL40",
}


def get_process_stages(produkt: str) -> list[str]:
    """Return ordered list of process stage names for a product.
    Returns empty list for products without full pipeline (ETAPY_SIMPLE)."""
    if produkt not in FULL_PIPELINE_PRODUCTS:
        return []
    if produkt in GLOL_PRODUCTS:
        return list(PROCESS_STAGES_GLOL)
    return list(PROCESS_STAGES_K7)


PARALLEL_STAGES = {"amidowanie", "smca"}


def init_etapy_status(db: sqlite3.Connection, ebr_id: int, produkt: str) -> None:
    """Initialize stage status records for a new szarża.
    Parallel stages (amidowanie + smca) both start as in_progress."""
    stages = get_process_stages(produkt)
    if not stages:
        return
    now = datetime.now().isoformat(timespec="seconds")
    for etap in stages:
        is_parallel = etap in PARALLEL_STAGES
        status = "in_progress" if is_parallel else "pending"
        dt_start = now if is_parallel else None
        db.execute(
            """INSERT OR IGNORE INTO ebr_etapy_status (ebr_id, etap, status, dt_start)
               VALUES (?, ?, ?, ?)""",
            (ebr_id, etap, status, dt_start),
        )
    db.commit()


def get_etapy_status(db: sqlite3.Connection, ebr_id: int) -> list[dict]:
    """Get status of all process stages for a batch. Returns ordered list."""
    rows = db.execute(
        "SELECT * FROM ebr_etapy_status WHERE ebr_id = ? ORDER BY id",
        (ebr_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_aktualny_etap(db: sqlite3.Connection, ebr_id: int) -> str | None:
    """Get the name of the current (in_progress) process stage, or None if all done."""
    row = db.execute(
        "SELECT etap FROM ebr_etapy_status WHERE ebr_id = ? AND status = 'in_progress'",
        (ebr_id,),
    ).fetchone()
    return row["etap"] if row else None


def zatwierdz_etap(db: sqlite3.Connection, ebr_id: int, etap: str, user: str, produkt: str) -> str | None:
    """Approve current stage, advance to next. Returns next stage name or None if last.
    For parallel stages (amid/smca): czwartorzedowanie activates only when BOTH are done."""
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "UPDATE ebr_etapy_status SET status='done', dt_end=?, zatwierdzil=? WHERE ebr_id=? AND etap=?",
        (now, user, ebr_id, etap),
    )

    # If approving a parallel stage, check if the other parallel stage is also done
    if etap in PARALLEL_STAGES:
        other_parallel = PARALLEL_STAGES - {etap}
        all_parallel_done = True
        for other in other_parallel:
            row = db.execute(
                "SELECT status FROM ebr_etapy_status WHERE ebr_id=? AND etap=?",
                (ebr_id, other),
            ).fetchone()
            if row and row["status"] != "done":
                all_parallel_done = False
                break
        if not all_parallel_done:
            # Other parallel stage still active — don't advance yet
            db.commit()
            # Return the other parallel stage that's still in progress
            for other in other_parallel:
                row = db.execute(
                    "SELECT etap FROM ebr_etapy_status WHERE ebr_id=? AND etap=? AND status='in_progress'",
                    (ebr_id, other),
                ).fetchone()
                if row:
                    return row["etap"]
            return None
        # Both parallel done — activate czwartorzedowanie (first non-parallel stage)
        stages = get_process_stages(produkt)
        for s in stages:
            if s not in PARALLEL_STAGES:
                db.execute(
                    "UPDATE ebr_etapy_status SET status='in_progress', dt_start=? WHERE ebr_id=? AND etap=? AND status='pending'",
                    (now, ebr_id, s),
                )
                db.commit()
                return s
        db.commit()
        return None

    # Sequential stage — find next pending
    stages = get_process_stages(produkt)
    try:
        idx = stages.index(etap)
        if idx + 1 < len(stages):
            next_etap = stages[idx + 1]
            db.execute(
                "UPDATE ebr_etapy_status SET status='in_progress', dt_start=? WHERE ebr_id=? AND etap=? AND status='pending'",
                (now, ebr_id, next_etap),
            )
            db.commit()
            return next_etap
    except ValueError:
        pass
    db.commit()
    return None  # All process stages done → standaryzacja next
