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
