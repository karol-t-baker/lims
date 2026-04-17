"""MVP pipeline cleanup — narrow multi-stage pipeline to Chegina_K7 only,
strip dodatki stage from K7, set K7 typ flags per spec.

See docs/superpowers/specs/2026-04-16-mvp-pipeline-cleanup-design.md

Usage:
    python -m scripts.mvp_pipeline_cleanup [--db PATH] [--dry-run] [--verify-only] [--force]
"""

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


MIGRATION_NAME = "mvp_pipeline_cleanup_v1"
MVP_MULTI_STAGE = {"Chegina_K7"}


def _analiza_koncowa_etap_id(db: sqlite3.Connection) -> int:
    row = db.execute(
        "SELECT id FROM etapy_analityczne WHERE kod='analiza_koncowa'"
    ).fetchone()
    if not row:
        raise RuntimeError("etapy_analityczne has no 'analiza_koncowa' row")
    return row["id"]


def strip_non_k7_pipeline(db: sqlite3.Connection) -> dict:
    """For every product not in MVP_MULTI_STAGE: remove all produkt_pipeline
    entries except analiza_koncowa; remove all produkt_etapy entries.

    Returns counts: {'pipeline_deleted': N, 'pipeline_inserted': N, 'etapy_deleted': N}.
    """
    ak_id = _analiza_koncowa_etap_id(db)
    counts = {"pipeline_deleted": 0, "pipeline_inserted": 0, "etapy_deleted": 0}

    # All products with pipeline entries, outside the whitelist.
    produkty = db.execute(
        "SELECT DISTINCT produkt FROM produkt_pipeline"
    ).fetchall()
    for row in produkty:
        produkt = row["produkt"]
        if produkt in MVP_MULTI_STAGE:
            continue
        # Delete non-analiza_koncowa pipeline rows
        cur = db.execute(
            "DELETE FROM produkt_pipeline WHERE produkt=? AND etap_id != ?",
            (produkt, ak_id),
        )
        counts["pipeline_deleted"] += cur.rowcount
        # Ensure analiza_koncowa row exists
        exists = db.execute(
            "SELECT 1 FROM produkt_pipeline WHERE produkt=? AND etap_id=?",
            (produkt, ak_id),
        ).fetchone()
        if not exists:
            db.execute(
                "INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES (?, ?, 1)",
                (produkt, ak_id),
            )
            counts["pipeline_inserted"] += 1

    # Delete ALL produkt_etapy for non-K7 products (process workflow)
    produkty = db.execute(
        "SELECT DISTINCT produkt FROM produkt_etapy"
    ).fetchall()
    for row in produkty:
        produkt = row["produkt"]
        if produkt in MVP_MULTI_STAGE:
            continue
        cur = db.execute("DELETE FROM produkt_etapy WHERE produkt=?", (produkt,))
        counts["etapy_deleted"] += cur.rowcount

    return counts


_K7_SZARZA_STAGES = ("sulfonowanie", "utlenienie", "standaryzacja")
_K7_DROP_PROCESS_KODY = ("amidowanie", "namca", "czwartorzedowanie")


def _etap_ids_by_kod(db: sqlite3.Connection, kody) -> dict:
    rows = db.execute(
        f"SELECT id, kod FROM etapy_analityczne WHERE kod IN ({','.join('?' * len(kody))})",
        tuple(kody),
    ).fetchall()
    return {r["kod"]: r["id"] for r in rows}


def fixup_chegina_k7(db: sqlite3.Connection) -> dict:
    """Apply K7-specific normalisation:
      - drop dodatki stage (from produkt_pipeline + produkt_etap_limity)
      - set dla_szarzy=1 dla_zbiornika=0 on sulfonowanie/utlenienie/standaryzacja params
      - set dla_szarzy=0 dla_zbiornika=1 on analiza_koncowa params
      - trim produkt_etapy to {sulfonowanie, utlenienie, standaryzacja}
    """
    counts = {
        "pipeline_dodatki_dropped": 0,
        "limity_dodatki_dropped": 0,
        "szarza_params_set": 0,
        "zbiornik_params_set": 0,
        "process_etapy_deleted": 0,
        "process_etapy_inserted": 0,
    }
    etap_ids = _etap_ids_by_kod(db, ["dodatki", "analiza_koncowa",
                                     "sulfonowanie", "utlenienie", "standaryzacja"])
    dodatki_id = etap_ids.get("dodatki")
    ak_id = etap_ids["analiza_koncowa"]
    szarza_ids = [etap_ids["sulfonowanie"], etap_ids["utlenienie"], etap_ids["standaryzacja"]]

    # 1. Drop dodatki from produkt_pipeline for K7
    if dodatki_id is not None:
        cur = db.execute(
            "DELETE FROM produkt_pipeline WHERE produkt='Chegina_K7' AND etap_id=?",
            (dodatki_id,),
        )
        counts["pipeline_dodatki_dropped"] = cur.rowcount
        cur = db.execute(
            "DELETE FROM produkt_etap_limity WHERE produkt='Chegina_K7' AND etap_id=?",
            (dodatki_id,),
        )
        counts["limity_dodatki_dropped"] = cur.rowcount

    # 2. Set szarza flags on process-stage params
    placeholders = ",".join("?" * len(szarza_ids))
    cur = db.execute(
        f"UPDATE produkt_etap_limity SET dla_szarzy=1, dla_zbiornika=0 "
        f"WHERE produkt='Chegina_K7' AND etap_id IN ({placeholders})",
        szarza_ids,
    )
    counts["szarza_params_set"] = cur.rowcount

    # 3. Set zbiornik flags on analiza_koncowa params
    cur = db.execute(
        "UPDATE produkt_etap_limity SET dla_szarzy=0, dla_zbiornika=1 "
        "WHERE produkt='Chegina_K7' AND etap_id=?",
        (ak_id,),
    )
    counts["zbiornik_params_set"] = cur.rowcount

    # 4. Trim produkt_etapy
    if _K7_DROP_PROCESS_KODY:
        placeholders = ",".join("?" * len(_K7_DROP_PROCESS_KODY))
        cur = db.execute(
            f"DELETE FROM produkt_etapy WHERE produkt='Chegina_K7' "
            f"AND etap_kod IN ({placeholders})",
            _K7_DROP_PROCESS_KODY,
        )
        counts["process_etapy_deleted"] = cur.rowcount
    exists = db.execute(
        "SELECT 1 FROM produkt_etapy WHERE produkt='Chegina_K7' AND etap_kod='standaryzacja'"
    ).fetchone()
    if not exists:
        max_kol = db.execute(
            "SELECT COALESCE(MAX(kolejnosc), 0) AS k FROM produkt_etapy WHERE produkt='Chegina_K7'"
        ).fetchone()["k"]
        db.execute(
            "INSERT INTO produkt_etapy (produkt, etap_kod, kolejnosc) "
            "VALUES ('Chegina_K7', 'standaryzacja', ?)",
            (max_kol + 1,),
        )
        counts["process_etapy_inserted"] = 1

    return counts


def backup(db_path: str) -> str:
    src = Path(db_path)
    if not src.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")
    dst = src.with_suffix(src.suffix + ".bak-pre-mvp-cleanup")
    shutil.copy2(src, dst)
    return str(dst)


def already_applied(db: sqlite3.Connection) -> bool:
    db.execute(
        "CREATE TABLE IF NOT EXISTS _migrations ("
        " name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    row = db.execute(
        "SELECT 1 FROM _migrations WHERE name=?", (MIGRATION_NAME,)
    ).fetchone()
    return row is not None


def mark_applied(db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO _migrations (name, applied_at) VALUES (?, ?)",
        (MIGRATION_NAME, datetime.now().isoformat(timespec="seconds")),
    )


def migrate(db: sqlite3.Connection, dry_run: bool = False) -> None:
    if already_applied(db):
        print(f"Migration {MIGRATION_NAME} already applied — skipping.")
        return

    if dry_run:
        print("Dry run — no changes will be committed.")

    counts1 = strip_non_k7_pipeline(db)
    if any(counts1.values()):
        print(
            f"Stripped non-K7 pipeline: deleted {counts1['pipeline_deleted']} pipeline rows, "
            f"inserted {counts1['pipeline_inserted']} analiza_koncowa rows, "
            f"deleted {counts1['etapy_deleted']} produkt_etapy rows."
        )

    counts2 = fixup_chegina_k7(db)
    if any(counts2.values()):
        print(
            f"K7 fixup: dropped dodatki stage ({counts2['pipeline_dodatki_dropped']} pipeline, "
            f"{counts2['limity_dodatki_dropped']} limity), "
            f"set szarza flags on {counts2['szarza_params_set']} params, "
            f"zbiornik flags on {counts2['zbiornik_params_set']} params, "
            f"deleted {counts2['process_etapy_deleted']} process etapy, "
            f"inserted {counts2['process_etapy_inserted']} standaryzacja."
        )

    errors = postflight(db)
    if errors:
        print("Post-flight validation failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        raise SystemExit(2)

    if dry_run:
        db.rollback()
        print("Dry run complete — rolled back.")
    else:
        mark_applied(db)
        db.commit()
        print(f"Migration {MIGRATION_NAME} committed.")


def postflight(db: sqlite3.Connection) -> list[str]:
    """Return list of post-migration validation errors. Empty list = OK."""
    return []  # filled in later tasks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/batch_db.sqlite")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not args.verify_only:
        bkp = backup(args.db)
        print(f"Backup: {bkp}")

    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")

    try:
        if args.verify_only:
            errors = postflight(db)
            if errors:
                for e in errors:
                    print(f"  - {e}")
                raise SystemExit(2)
            print("Verification OK.")
        else:
            if args.force:
                db.execute("DELETE FROM _migrations WHERE name=?", (MIGRATION_NAME,))
            migrate(db, dry_run=args.dry_run)
    finally:
        db.close()


if __name__ == "__main__":
    main()
