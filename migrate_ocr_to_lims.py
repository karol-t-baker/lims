"""Migrate OCR-extracted batch data into LIMS process stage tables.

Reads JSONs from data/output_json/Chegina_K7/ and Chegina_K40GLOL/,
maps process stage analyses and corrections into ebr_etapy_analizy + ebr_korekty.

Usage:
    python migrate_ocr_to_lims.py [--dry-run]
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from mbr.models import get_db, init_mbr_tables
from mbr.etapy_models import save_etap_analizy, add_korekta
from mbr.etapy_config import OCR_KOD_MAP, OCR_ETAP_MAP

OUTPUT_DIR = Path("data/output_json")
PRODUCTS = ["Chegina_K7", "Chegina_K40GLOL"]


def extract_analyses_from_kroki(kroki: list, etap_lims: str) -> tuple[list, list]:
    """Extract analyses and corrections from OCR kroki array.

    Returns:
        (analyses, corrections) where:
        analyses = [{"runda": N, "wyniki": {kod: val}}]
        corrections = [{"po_rundzie": N, "substancja": str, "ilosc_kg": float}]
    """
    analyses = []
    corrections = []
    analiza_count = 0

    for krok in kroki:
        typ = krok.get("typ")
        if typ == "analiza":
            analiza_count += 1
            wyniki = {}
            for ocr_key, lims_kod in OCR_KOD_MAP.items():
                val = krok.get(ocr_key)
                if val is not None and val != "":
                    try:
                        wyniki[lims_kod] = float(val)
                    except (ValueError, TypeError):
                        pass
            if wyniki:
                analyses.append({"runda": analiza_count, "wyniki": wyniki})

        elif typ == "korekta":
            substancja = krok.get("substancja", "")
            ilosc = krok.get("ilosc_kg")
            if substancja and ilosc is not None:
                try:
                    corrections.append({
                        "po_rundzie": analiza_count,
                        "substancja": substancja,
                        "ilosc_kg": float(ilosc),
                    })
                except (ValueError, TypeError):
                    pass

    return analyses, corrections


def extract_amid_analyses(amid_data: dict) -> list:
    """Extract analyses from amidowanie stage (special structure)."""
    analyses = []
    dest = amid_data.get("analizy_po_destylacji") or []
    for i, entry in enumerate(dest):
        wyniki = {}
        for ocr_key, lims_kod in OCR_KOD_MAP.items():
            val = entry.get(ocr_key)
            if val is not None and val != "":
                try:
                    wyniki[lims_kod] = float(val)
                except (ValueError, TypeError):
                    pass
        if wyniki:
            analyses.append({"runda": i + 1, "wyniki": wyniki})

    # Also check kroki for additional analyses
    kroki = amid_data.get("kroki") or []
    kroki_analyses, _ = extract_analyses_from_kroki(kroki, "amidowanie")
    # Offset runda numbers
    offset = len(analyses)
    for a in kroki_analyses:
        a["runda"] += offset
        analyses.append(a)

    return analyses


def extract_smca_analyses(smca_data: dict) -> list:
    """Extract analysis from SMCA stage."""
    analyses = []
    analiza = smca_data.get("analiza_smca")
    if analiza:
        wyniki = {}
        for ocr_key, lims_kod in OCR_KOD_MAP.items():
            val = analiza.get(ocr_key)
            if val is not None and val != "":
                try:
                    wyniki[lims_kod] = float(val)
                except (ValueError, TypeError):
                    pass
        if wyniki:
            analyses.append({"runda": 1, "wyniki": wyniki})
    return analyses


def find_or_create_ebr(db, produkt: str, nr_partii: str) -> int:
    """Find existing EBR by produkt + nr_partii, or create one."""
    row = db.execute(
        """SELECT eb.ebr_id FROM ebr_batches eb
           JOIN mbr_templates mt ON mt.mbr_id = eb.mbr_id
           WHERE mt.produkt = ? AND eb.nr_partii = ?""",
        (produkt, nr_partii),
    ).fetchone()
    if row:
        return row["ebr_id"]

    # Create new EBR for historical batch
    mbr = db.execute(
        "SELECT mbr_id FROM mbr_templates WHERE produkt = ? AND status = 'active'",
        (produkt,),
    ).fetchone()
    if not mbr:
        print(f"    WARNING: No active MBR for {produkt}, skipping")
        return None

    batch_id = f"{produkt}__{nr_partii.replace('/', '_')}"
    now = datetime.now().isoformat(timespec="seconds")
    cur = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, operator, typ) VALUES (?, ?, ?, ?, 'completed', 'ocr_import', 'szarza')",
        (mbr["mbr_id"], batch_id, nr_partii, now),
    )
    db.commit()
    print(f"    Created EBR {cur.lastrowid} for {produkt} {nr_partii}")
    return cur.lastrowid


def migrate_batch(db, produkt: str, json_path: Path, dry_run: bool) -> dict:
    """Migrate one batch JSON. Returns stats."""
    with open(json_path) as f:
        data = json.load(f)

    nr_partii = data.get("nr_partii", json_path.stem.replace("_", "/"))
    stats = {"analizy": 0, "korekty": 0, "skipped": False}

    if dry_run:
        ebr_id = -1
    else:
        ebr_id = find_or_create_ebr(db, produkt, nr_partii)
        if ebr_id is None:
            stats["skipped"] = True
            return stats

    proc = data.get("proces") or {}
    etapy = proc.get("etapy") or {}

    for ocr_etap, lims_etap in OCR_ETAP_MAP.items():
        if lims_etap == "standaryzacja":
            continue  # Skip — handled by existing ebr_wyniki system

        etap_data = etapy.get(ocr_etap)
        if not etap_data or etap_data is None:
            continue

        # Extract analyses
        if ocr_etap == "amid":
            analyses = extract_amid_analyses(etap_data)
            corrections = []
        elif ocr_etap == "smca":
            analyses = extract_smca_analyses(etap_data)
            corrections = []
        else:
            kroki = etap_data.get("kroki") or []
            analyses, corrections = extract_analyses_from_kroki(kroki, lims_etap)

        # Save
        for a in analyses:
            if not dry_run:
                save_etap_analizy(db, ebr_id, lims_etap, a["runda"], a["wyniki"], "ocr_import")
            stats["analizy"] += len(a["wyniki"])

        for c in corrections:
            if not dry_run:
                add_korekta(db, ebr_id, lims_etap, c["po_rundzie"], c["substancja"], c["ilosc_kg"], "ocr_import")
            stats["korekty"] += 1

    return stats


def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("=== DRY RUN — no data will be written ===\n")

    db = get_db()
    init_mbr_tables(db)

    total = {"analizy": 0, "korekty": 0, "batches": 0, "skipped": 0}

    for produkt in PRODUCTS:
        prod_dir = OUTPUT_DIR / produkt.replace(" ", "_")
        if not prod_dir.exists():
            print(f"No data for {produkt}")
            continue

        json_files = sorted(prod_dir.glob("*.json"))
        print(f"\n{produkt}: {len(json_files)} batches")

        for jf in json_files:
            print(f"  {jf.name}...", end=" ")
            stats = migrate_batch(db, produkt, jf, dry_run)
            if stats["skipped"]:
                print("SKIPPED")
                total["skipped"] += 1
            else:
                print(f"OK ({stats['analizy']} params, {stats['korekty']} corrections)")
                total["analizy"] += stats["analizy"]
                total["korekty"] += stats["korekty"]
                total["batches"] += 1

    print(f"\n{'DRY RUN ' if dry_run else ''}TOTAL: {total['batches']} batches, {total['analizy']} parameters, {total['korekty']} corrections, {total['skipped']} skipped")


if __name__ == "__main__":
    main()
