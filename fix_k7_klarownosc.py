"""
Fix: Chegina_K7 szarże see an extra "Analiza końcowa" stage.

Root cause: produkt_etap_limity has a single row for klarownosc bound to
(Chegina_K7, analiza_koncowa) with dla_szarzy=1. Every other param at that
stage has dla_szarzy=0, so this lone row prevents pipeline-adapter from
filtering the whole stage out for szarża view.

User decision: remove klarownosc binding entirely (option B). The parameter
has no historical measurements and no other product bindings, so the row
is safe to drop. The parametry_analityczne row stays — only the binding
is removed.

After deleting the row, rebuilds mbr_templates.parametry_lab for Chegina_K7
so the next batch (and any open batch refresh) sees the correct shape.

Idempotent: skips when the binding is already gone.

Run: python fix_k7_klarownosc.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from mbr.db import get_db
from mbr.parametry.registry import build_parametry_lab
from mbr.shared import audit
import json


def main() -> int:
    db = get_db()

    row = db.execute(
        """SELECT pel.id
             FROM produkt_etap_limity pel
             JOIN parametry_analityczne pa ON pa.id = pel.parametr_id
             JOIN etapy_analityczne ea     ON ea.id = pel.etap_id
            WHERE pel.produkt = 'Chegina_K7'
              AND pa.kod = 'klarownosc'
              AND ea.kod = 'analiza_koncowa'""",
    ).fetchone()

    if row is None:
        print("Already fixed — no klarownosc binding for Chegina_K7/analiza_koncowa.")
        return 0

    db.execute("DELETE FROM produkt_etap_limity WHERE id = ?", (row["id"],))

    plab = build_parametry_lab(db, "Chegina_K7")
    db.execute(
        "UPDATE mbr_templates SET parametry_lab = ? WHERE produkt = 'Chegina_K7' AND status = 'active'",
        (json.dumps(plab, ensure_ascii=False),),
    )

    audit.log_event(
        audit.EVENT_PARAMETR_UPDATED,
        entity_type="produkt_etap_limity",
        entity_id=row["id"],
        entity_label="Chegina_K7/analiza_koncowa/klarownosc",
        payload={
            "produkt": "Chegina_K7",
            "etap": "analiza_koncowa",
            "parametr": "klarownosc",
            "action": "binding_removed",
            "reason": "spurious dla_szarzy=1 caused 4th stage to appear in szarża view",
        },
        actors=audit.actors_system(),
        db=db,
    )

    db.commit()
    print(f"Deleted produkt_etap_limity row id={row['id']}.")
    print(f"Rebuilt parametry_lab — sections: {sorted(plab.keys())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
