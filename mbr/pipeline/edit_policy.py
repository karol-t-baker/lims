"""Editability policy for pipeline sessions.

Two-tier rule (learning-phase friendly):
  - Batch open   → every sesja is editable, regardless of sesja.status.
  - Batch closed → only the last-in-pipeline sesja is editable.

Writes that hit a zamkniety sesja are legal per this policy — callers must
still audit-log them with reedit=1 so history stays traceable.
"""
from __future__ import annotations

import sqlite3


def is_sesja_editable(db: sqlite3.Connection, *, ebr_id: int, sesja_id: int) -> bool:
    """Return True if the given sesja may accept writes under the edit policy."""
    row = db.execute(
        """SELECT b.status AS batch_status, s.etap_id,
                  (SELECT m.produkt FROM mbr_templates m WHERE m.mbr_id = b.mbr_id) AS produkt
           FROM ebr_etap_sesja s
           JOIN ebr_batches b ON b.ebr_id = s.ebr_id
           WHERE s.id = ? AND s.ebr_id = ?""",
        (sesja_id, ebr_id),
    ).fetchone()
    if row is None:
        return False
    if row["batch_status"] == "open":
        return True
    # Batch closed → only the last stage (highest kolejnosc) is editable.
    last = db.execute(
        "SELECT etap_id FROM produkt_pipeline WHERE produkt = ? "
        "ORDER BY kolejnosc DESC LIMIT 1",
        (row["produkt"],),
    ).fetchone()
    return bool(last and last["etap_id"] == row["etap_id"])


def has_downstream_activity(db: sqlite3.Connection, *, ebr_id: int, etap_id: int) -> dict:
    """Summarise activity in pipeline stages placed AFTER the given etap.

    Returns {"has_downstream": bool, "stages": [{"etap_id", "nazwa", "pomiary", "korekty"}, ...]}.
    Used by the inline banner that warns the laborant when editing a stage whose
    downstream measurements or corrections may need re-evaluation.
    """
    ref = db.execute(
        """SELECT pp.kolejnosc,
                  (SELECT m.produkt FROM mbr_templates m
                   JOIN ebr_batches b ON b.mbr_id = m.mbr_id
                   WHERE b.ebr_id = ?) AS produkt
           FROM produkt_pipeline pp
           WHERE pp.etap_id = ?
             AND pp.produkt = (SELECT m.produkt FROM mbr_templates m
                               JOIN ebr_batches b ON b.mbr_id = m.mbr_id
                               WHERE b.ebr_id = ?)""",
        (ebr_id, etap_id, ebr_id),
    ).fetchone()
    if ref is None or ref["produkt"] is None:
        return {"has_downstream": False, "stages": []}

    rows = db.execute(
        """SELECT pp.etap_id, ea.nazwa,
                  (SELECT COUNT(*) FROM ebr_pomiar p
                   JOIN ebr_etap_sesja s ON s.id = p.sesja_id
                   WHERE s.ebr_id = ? AND s.etap_id = pp.etap_id
                     AND p.wartosc IS NOT NULL) AS pomiary,
                  (SELECT COUNT(*) FROM ebr_korekta_v2 k
                   JOIN ebr_etap_sesja s ON s.id = k.sesja_id
                   WHERE s.ebr_id = ? AND s.etap_id = pp.etap_id
                     AND k.ilosc IS NOT NULL) AS korekty
           FROM produkt_pipeline pp
           JOIN etapy_analityczne ea ON ea.id = pp.etap_id
           WHERE pp.produkt = ? AND pp.kolejnosc > ?
           ORDER BY pp.kolejnosc""",
        (ebr_id, ebr_id, ref["produkt"], ref["kolejnosc"]),
    ).fetchall()

    stages = [{"etap_id": r["etap_id"], "nazwa": r["nazwa"],
               "pomiary": r["pomiary"], "korekty": r["korekty"]}
              for r in rows if r["pomiary"] > 0 or r["korekty"] > 0]
    return {"has_downstream": bool(stages), "stages": stages}
