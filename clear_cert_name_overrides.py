"""
Clear all per-product / per-variant name_pl + name_en overrides on parametry_cert.

After this script runs every cert row falls back to the registry values
(parametry_analityczne.label / .name_en). 9 params have empty registry EN
— so3, aa, ph, gliceryny, wge, tlenek_aminowy, t_krzep, monoglicerydy,
kwas_hcl — and their certs will render with blank EN until the registry is
backfilled. User accepted that trade-off.

method_* and format_* overrides are NOT touched.

Idempotent: prints "no overrides to clear" when re-run on a clean DB.
Audit: one cert.config.updated event per distinct (produkt, variant_id).

Run: python clear_cert_name_overrides.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from mbr.db import get_db
from mbr.shared import audit
from mbr.certs.generator import save_cert_config_export


def main() -> int:
    db = get_db()

    rows = db.execute(
        """SELECT id, produkt, variant_id, name_pl, name_en
             FROM parametry_cert
            WHERE name_pl IS NOT NULL OR name_en IS NOT NULL""",
    ).fetchall()

    if not rows:
        print("Already clean — no name_pl / name_en overrides on parametry_cert.")
        return 0

    n_pl = sum(1 for r in rows if r["name_pl"] is not None)
    n_en = sum(1 for r in rows if r["name_en"] is not None)
    print(f"Clearing {len(rows)} rows ({n_pl} name_pl + {n_en} name_en overrides)…")

    db.execute(
        "UPDATE parametry_cert SET name_pl = NULL, name_en = NULL "
        "WHERE name_pl IS NOT NULL OR name_en IS NOT NULL",
    )

    affected = {(r["produkt"], r["variant_id"]) for r in rows}
    for produkt, variant_id in sorted(affected, key=lambda t: (t[0], t[1] or 0)):
        scope_rows = [r for r in rows if r["produkt"] == produkt and r["variant_id"] == variant_id]
        audit.log_event(
            audit.EVENT_CERT_CONFIG_UPDATED,
            entity_type="cert",
            entity_label=produkt if variant_id is None else f"{produkt}#variant={variant_id}",
            payload={
                "produkt": produkt,
                "variant_id": variant_id,
                "action": "name_overrides_cleared",
                "rows_cleared": len(scope_rows),
                "name_pl_cleared": sum(1 for r in scope_rows if r["name_pl"] is not None),
                "name_en_cleared": sum(1 for r in scope_rows if r["name_en"] is not None),
                "reason": "bulk reset — registry becomes SSOT for parameter names",
            },
            actors=audit.actors_system(),
            db=db,
        )

    db.commit()
    print(f"Cleared overrides — {len(affected)} (produkt, variant) scopes audited.")

    save_cert_config_export()
    print("Re-exported mbr/cert_config.json from DB.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
