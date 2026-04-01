"""migrate_v4.py — Transform v3 batch card JSONs into v4 SQLite schema."""

import json
import sqlite3
from pathlib import Path

DDL_PATH = Path(__file__).parent / "schema_v4.sql"

STAGE_MAP = {
    "amid": "amid",
    "smca": "smca",
    "czwartorzedowanie": "czwart",
    "wybielanie": "rozjasnianie",
    "sulfonowanie": "sulfonowanie",
    "utlenienie": "utlenienie",
    "standaryzacja": "standaryzacja",
}


def create_db(db_path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(db_path))
    db.executescript(DDL_PATH.read_text())
    return db


def _make_batch_id(produkt: str, nr_partii: str) -> str:
    p = produkt.replace(" ", "_")
    n = nr_partii.replace("/", "_")
    return f"{p}__{n}"


def migrate_batch(db: sqlite3.Connection, card: dict) -> str:
    """Insert one v3 card into batch table. Returns batch_id."""
    s1 = card.get("strona1", {})
    konc = card.get("koncowa", {})
    ak = konc.get("analiza_koncowa") or {}
    pomp = konc.get("przepompowanie") or {}

    batch_id = _make_batch_id(card["produkt"], card["nr_partii"])

    pewnosci = []
    for section in [s1, card.get("proces", {}), konc]:
        _collect_pewnosc(section, pewnosci)
    ocr_mean = sum(pewnosci) / len(pewnosci) if pewnosci else None

    db.execute("""
        INSERT OR REPLACE INTO batch (
            batch_id, produkt, nr_partii, equipment_id, nr_mieszalnika,
            template_id, dt_start, dt_end, wielkosc_kg, wielkosc_receptura_kg,
            ak_datetime, ak_ph, ak_ph_10proc, ak_nd20,
            ak_procent_sm, ak_procent_nacl, ak_procent_sa, ak_procent_aa,
            ak_procent_so3, ak_procent_h2o2,
            ak_barwa_raw, ak_barwa_fau, ak_barwa_hz, ak_barwa_opis,
            ak_jakosc_ocena, ak_certyfikat_nr,
            pomp_dt_start, pomp_dt_end, pomp_temp_max_c,
            pomp_zbiornik_1, pomp_wskazanie_od_1, pomp_wskazanie_do_1,
            pomp_zbiornik_2, pomp_wskazanie_od_2, pomp_wskazanie_do_2,
            _source, _schema_version, _ocr_pewnosc_mean, _verified
        ) VALUES (
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            'ocr', '4.0', ?, 0
        )
    """, (
        batch_id, card["produkt"], card["nr_partii"],
        s1.get("nr_amidatora"), s1.get("nr_mieszalnika"),
        s1.get("template_id"),
        s1.get("data_rozpoczecia"), s1.get("data_zakonczenia"),
        s1.get("wielkosc_szarzy_kg"), s1.get("wielkosc_szarzy_recepturowa_kg"),
        ak.get("datetime"), ak.get("ph"), ak.get("ph_10proc"), ak.get("nd20"),
        ak.get("procent_sm"), ak.get("procent_nacl"), ak.get("procent_sa"),
        ak.get("procent_aa"), ak.get("procent_so3"), ak.get("procent_h2o2"),
        ak.get("barwa"), ak.get("barwa_fau"), ak.get("barwa_hz"),
        ak.get("barwa_opis"), ak.get("jakosc_ocena"), ak.get("certyfikat_nr"),
        pomp.get("datetime_start"), pomp.get("datetime_koniec"),
        pomp.get("temperatura_max_c"),
        pomp.get("zbiornik_1"), pomp.get("wskazanie_od_1"),
        pomp.get("wskazanie_do_1"),
        pomp.get("zbiornik_2"), pomp.get("wskazanie_od_2"),
        pomp.get("wskazanie_do_2"),
        ocr_mean,
    ))
    return batch_id


def migrate_materials(db: sqlite3.Connection, batch_id: str, card: dict):
    """Insert surowce + standaryzowanie from strona1 into materials."""
    s1 = card.get("strona1", {})

    for sur in s1.get("surowce", []):
        korekta_json = json.dumps(sur["korekta"]) if sur.get("korekta") else None
        db.execute("""
            INSERT INTO materials (
                batch_id, kategoria, kod, nazwa, ilosc_kg, ilosc_receptura_kg,
                nr_partii_materialu, lp, godzina, _ocr_pewnosc, _korekta
            ) VALUES (?, 'surowiec', ?, ?, ?, ?, ?, ?, NULL, ?, ?)
        """, (
            batch_id,
            sur.get("kod_surowca"),
            sur.get("nazwa_surowca"),
            sur.get("ilosc_zaladowana_kg"),
            sur.get("ilosc_recepturowa_kg"),
            sur.get("numer_partii_surowca"),
            sur.get("lp"),
            sur.get("ocr_pewnosc"),
            korekta_json,
        ))

    for dod in s1.get("standaryzowanie", []):
        korekta_json = json.dumps(dod["korekta"]) if dod.get("korekta") else None
        db.execute("""
            INSERT INTO materials (
                batch_id, kategoria, kod, nazwa, ilosc_kg, ilosc_receptura_kg,
                nr_partii_materialu, lp, godzina, _ocr_pewnosc, _korekta
            ) VALUES (?, 'dodatek', ?, ?, ?, NULL, ?, ?, ?, ?, ?)
        """, (
            batch_id,
            dod.get("kod_dodatku"),
            dod.get("nazwa_dodatku"),
            dod.get("ilosc_kg"),
            dod.get("nr_partii_dodatku"),
            dod.get("lp"),
            dod.get("godzina"),
            dod.get("ocr_pewnosc"),
            korekta_json,
        ))


# Sub-stages that are structured objects (not kroki arrays)
STRUCTURED_SUBSTAGES = {
    "amid": {
        "zaladunek_surowcow": {"event_type": "zmiana_stanu"},
        "zaladunek_dmapa": {"event_type": "zmiana_stanu"},
        "wlaczenie_reaktora": {"event_type": "zmiana_stanu"},
        "reakcja_amidowania": {"event_type": "zmiana_stanu"},
        "destylacja": {"event_type": "zmiana_stanu"},
    },
    "smca": {
        "wytworzenie_smca": {"event_type": "zmiana_stanu"},
        "analiza_smca": {"event_type": "analiza"},
    },
    "czwartorzedowanie": {
        "przeciagniecie_amidu": {"event_type": "zmiana_stanu"},
    },
}


def migrate_events(db: sqlite3.Connection, batch_id: str, card: dict):
    """Insert all process events from v3 card into events table."""
    proc = card.get("proces", {})
    konc = card.get("koncowa", {})
    equipment_id = card.get("strona1", {}).get("nr_amidatora")
    pola_watpliwe = set(proc.get("pola_watpliwe", []) + konc.get("pola_watpliwe", []))

    seq_counter = [0]

    def next_seq():
        seq_counter[0] += 1
        return seq_counter[0]

    etapy = proc.get("etapy", {})
    for etap_key, etap_data in etapy.items():
        if etap_data is None:
            continue
        stage = STAGE_MAP.get(etap_key, etap_key)

        # 1. Structured sub-stages
        substage_defs = STRUCTURED_SUBSTAGES.get(etap_key, {})
        for sub_key, sub_def in substage_defs.items():
            sub = etap_data.get(sub_key)
            if sub is None:
                continue
            _insert_structured_event(db, batch_id, equipment_id, stage,
                                     sub_key, sub, sub_def, next_seq(),
                                     pola_watpliwe)

        # 2. Kroki arrays
        for krok in etap_data.get("kroki", []):
            _insert_krok_event(db, batch_id, equipment_id, stage,
                               krok, next_seq(), pola_watpliwe)

    # 3. koncowa.standaryzacja_kontynuacja.kroki → stage = "standaryzacja"
    sk = konc.get("standaryzacja_kontynuacja") or {}
    for krok in sk.get("kroki", []):
        _insert_krok_event(db, batch_id, equipment_id, "standaryzacja",
                           krok, next_seq(), pola_watpliwe)

    # 4. koncowa.analiza_miedzyoper_standaryzowanie → analiza event
    ami = konc.get("analiza_miedzyoper_standaryzowanie")
    if ami:
        _insert_analiza_event(db, batch_id, equipment_id, "standaryzacja",
                              ami, next_seq(), pola_watpliwe,
                              opis="analiza_miedzyoperacyjna")


def _ts_precision(dt_str: str, pola_watpliwe: set, path_hint: str = "") -> str:
    for pw in pola_watpliwe:
        if path_hint and path_hint in pw:
            return "estimated"
    return "minute"


def _insert_structured_event(db, batch_id, equipment_id, stage,
                              sub_key, sub, sub_def, seq, pola_watpliwe):
    event_type = sub_def["event_type"]
    dt = sub.get("datetime_start")
    if not dt:
        return

    proznia = sub.get("proznia_ba")
    if proznia is not None and proznia in (-1, -99):
        proznia = None

    db.execute("""
        INSERT INTO events (
            batch_id, equipment_id, dt, dt_end, stage, event_type, seq,
            ilosc_kg, temperatura_c, proznia_ba,
            ph, ph_10proc, nd20,
            opis, temperatura_docelowa_c, operator_raw,
            _source, _ts_precision, _ocr_pewnosc
        ) VALUES (?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?,
                  ?, ?, ?,
                  ?, ?, ?,
                  'ocr', ?, ?)
    """, (
        batch_id, equipment_id, dt,
        sub.get("datetime_koniec") or sub.get("datetime_end"),
        stage, event_type, seq,
        sub.get("ilosc_kg") or sub.get("ilosc_naoh_kg"),
        sub.get("temperatura_c"),
        proznia,
        sub.get("ph"), sub.get("ph_10proc"), sub.get("nd20"),
        sub_key if event_type == "zmiana_stanu" else None,
        sub.get("temperatura_docelowa_c"),
        sub.get("operator_podpis_raw"),
        _ts_precision(dt, pola_watpliwe),
        sub.get("ocr_pewnosc"),
    ))


_EVENT_TYPE_NORMALIZE = {
    "adiciotion": "dodatek",
    "addition": "dodatek",
}


def _insert_krok_event(db, batch_id, equipment_id, stage, krok, seq, pola_watpliwe):
    typ = krok.get("typ", "dodatek")
    typ = _EVENT_TYPE_NORMALIZE.get(typ, typ)
    dt = krok.get("datetime_start")
    if not dt:
        return

    proznia = krok.get("proznia_ba")
    if proznia is not None and proznia in (-1, -99):
        proznia = None

    db.execute("""
        INSERT INTO events (
            batch_id, equipment_id, dt, dt_end, stage, event_type, seq,
            substancja_kod, substancja_nazwa, ilosc_kg,
            temperatura_c, proznia_ba,
            ph, ph_10proc, nd20, procent_aa, procent_sm, procent_sa,
            procent_nacl, procent_so3, procent_h2o2,
            le, lk, barwa_raw, barwa_fau, barwa_hz, barwa_opis,
            operator_raw,
            _source, _ts_precision, _ocr_pewnosc
        ) VALUES (?, ?, ?, NULL, ?, ?, ?,
                  NULL, ?, ?,
                  ?, ?,
                  ?, ?, ?, ?, ?, ?,
                  ?, ?, ?,
                  ?, ?, ?, ?, ?, ?,
                  ?,
                  'ocr', ?, ?)
    """, (
        batch_id, equipment_id, dt,
        stage, typ, seq,
        krok.get("substancja"),
        krok.get("ilosc_kg"),
        krok.get("temperatura_c"),
        proznia,
        krok.get("ph"),
        krok.get("ph_10proc"),
        krok.get("nd20"),
        krok.get("procent_aa"),
        krok.get("procent_sm"),
        krok.get("procent_sa"),
        krok.get("procent_nacl"),
        krok.get("procent_so3"),
        krok.get("procent_h2o2"),
        krok.get("le_liczba_estrowa") or krok.get("le"),
        krok.get("lk_liczba_kwasowa") or krok.get("lk"),
        krok.get("barwa"),
        krok.get("barwa_fau"),
        krok.get("barwa_hz"),
        krok.get("barwa_opis"),
        krok.get("operator_podpis_raw"),
        _ts_precision(dt, pola_watpliwe),
        krok.get("ocr_pewnosc"),
    ))


def _insert_analiza_event(db, batch_id, equipment_id, stage, ana, seq,
                           pola_watpliwe, opis=None):
    dt = ana.get("datetime") or ana.get("datetime_start")
    if not dt:
        return

    db.execute("""
        INSERT INTO events (
            batch_id, equipment_id, dt, stage, event_type, seq,
            ph, ph_10proc, nd20, procent_aa, procent_sm, procent_sa,
            procent_nacl, procent_so3, procent_h2o2,
            le, lk, barwa_raw, barwa_fau, barwa_hz, barwa_opis,
            opis, operator_raw,
            _source, _ts_precision, _ocr_pewnosc
        ) VALUES (?, ?, ?, ?, 'analiza', ?,
                  ?, ?, ?, ?, ?, ?,
                  ?, ?, ?,
                  ?, ?, ?, ?, ?, ?,
                  ?, ?,
                  'ocr', ?, ?)
    """, (
        batch_id, equipment_id, dt, stage, seq,
        ana.get("ph"), ana.get("ph_10proc"), ana.get("nd20"),
        ana.get("procent_aa"), ana.get("procent_sm"), ana.get("procent_sa"),
        ana.get("procent_nacl"), ana.get("procent_so3"), ana.get("procent_h2o2"),
        ana.get("le_liczba_kwasowa") or ana.get("le"),
        ana.get("lk_liczba_kwasowa") or ana.get("lk"),
        ana.get("barwa"), ana.get("barwa_fau"), ana.get("barwa_hz"),
        ana.get("barwa_opis"),
        opis, ana.get("operator_podpis_raw"),
        _ts_precision(dt, pola_watpliwe),
        ana.get("ocr_pewnosc"),
    ))


def link_materials(db: sqlite3.Connection, batch_id: str, card: dict):
    """Link events with standaryzowanie_idx to their material_id."""
    dodatki = db.execute("""
        SELECT id, lp FROM materials
        WHERE batch_id = ? AND kategoria = 'dodatek'
        ORDER BY lp
    """, (batch_id,)).fetchall()

    if not dodatki:
        return

    s1_stand = card.get("strona1", {}).get("standaryzowanie", [])
    idx_to_material_id = {}
    for i, _ in enumerate(s1_stand):
        if i < len(dodatki):
            idx_to_material_id[i] = dodatki[i][0]  # material.id

    all_kroki_with_idx = []
    proc = card.get("proces", {})
    for etap_data in (proc.get("etapy") or {}).values():
        if etap_data is None:
            continue
        for krok in etap_data.get("kroki", []):
            idx = krok.get("standaryzowanie_idx")
            if idx is not None and idx in idx_to_material_id:
                all_kroki_with_idx.append((
                    krok.get("datetime_start"),
                    krok.get("substancja"),
                    idx_to_material_id[idx],
                ))

    konc = card.get("koncowa", {})
    sk = konc.get("standaryzacja_kontynuacja") or {}
    for krok in sk.get("kroki", []):
        idx = krok.get("standaryzowanie_idx")
        if idx is not None and idx in idx_to_material_id:
            all_kroki_with_idx.append((
                krok.get("datetime_start"),
                krok.get("substancja"),
                idx_to_material_id[idx],
            ))

    for dt, subst, mat_id in all_kroki_with_idx:
        db.execute("""
            UPDATE events SET material_id = ?
            WHERE batch_id = ? AND dt = ? AND substancja_nazwa = ?
        """, (mat_id, batch_id, dt, subst))


def _collect_pewnosc(obj, acc: list):
    """Recursively collect all ocr_pewnosc values."""
    if isinstance(obj, dict):
        if "ocr_pewnosc" in obj and obj["ocr_pewnosc"] is not None:
            acc.append(obj["ocr_pewnosc"])
        for v in obj.values():
            _collect_pewnosc(v, acc)
    elif isinstance(obj, list):
        for item in obj:
            _collect_pewnosc(item, acc)


def migrate_card(db: sqlite3.Connection, card: dict):
    """Migrate a single v3 card (all three tables)."""
    batch_id = migrate_batch(db, card)
    migrate_materials(db, batch_id, card)
    migrate_events(db, batch_id, card)
    link_materials(db, batch_id, card)
    return batch_id


def migrate_all(input_dir: Path, db_path: Path, use_verified: bool = True):
    """Migrate all v3 JSONs from output_json/ (or verified/) into v4 database."""
    db = create_db(db_path)
    count = 0

    if use_verified:
        verified_dir = input_dir.parent / "verified"
        if verified_dir.exists():
            count += _migrate_from_verified(db, verified_dir)

    # Also process output_json for non-verified batches
    output_dir = input_dir if input_dir.name == "output_json" else input_dir / "output_json"
    if output_dir.exists():
        existing = set(r[0] for r in db.execute("SELECT batch_id FROM batch").fetchall())
        for json_path in sorted(output_dir.rglob("*.json")):
            card = json.loads(json_path.read_text())
            if "produkt" not in card:
                continue
            bid = _make_batch_id(card["produkt"], card["nr_partii"])
            if bid in existing:
                continue
            migrate_card(db, card)
            count += 1

    db.commit()
    db.close()
    return count


def _migrate_from_verified(db: sqlite3.Connection, verified_dir: Path) -> int:
    """Migrate from verified/ directory (split into _strona1, _proces, _koncowa files)."""
    count = 0
    batches = {}

    for json_path in sorted(verified_dir.rglob("*.json")):
        name = json_path.stem
        for suffix in ("_strona1", "_proces", "_koncowa"):
            if name.endswith(suffix):
                batch_key = (json_path.parent.name, name[: -len(suffix)])
                section = suffix[1:]
                batches.setdefault(batch_key, {})[section] = json.loads(
                    json_path.read_text()
                )
                break

    for (produkt_dir, nr_key), sections in batches.items():
        s1 = sections.get("strona1", {})
        produkt = s1.get("produkt", produkt_dir.replace("_", " "))
        nr_partii = s1.get("nr_partii", nr_key.replace("_", "/"))
        card = {
            "produkt": produkt,
            "nr_partii": nr_partii,
            "_schema_version": "3.0",
            "strona1": s1,
            "proces": sections.get("proces", {}),
            "koncowa": sections.get("koncowa", {}),
        }
        bid = migrate_card(db, card)
        db.execute("UPDATE batch SET _verified = 1 WHERE batch_id = ?", (bid,))
        count += 1

    return count


def migrate_sensors(db: sqlite3.Connection, v3_db_path: Path):
    """Copy sensor_readings from v3 database to v4."""
    v3 = sqlite3.connect(str(v3_db_path))
    rows = v3.execute("SELECT * FROM sensor_readings").fetchall()
    cols = [d[0] for d in v3.execute("SELECT * FROM sensor_readings LIMIT 0").description]
    v3.close()

    for row in rows:
        values = dict(zip(cols, row))
        db.execute("""
            INSERT INTO sensor_readings (
                batch_id, datetime, source, equipment,
                temp_c, temp_plaszcz_c, proznia_bar, dozownik_l, etap
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            values.get("batch_id"),
            values.get("datetime"),
            values.get("source"),
            values.get("equipment"),
            values.get("temp_c"),
            values.get("temp_plaszcz_c"),
            values.get("proznia_bar"),
            values.get("dozownik_l"),
            values.get("etap"),
        ))


def print_report(db_path: Path):
    """Print migration summary report."""
    db = sqlite3.connect(str(db_path))

    print("\n=== Schema v4 Migration Report ===\n")

    for table in ["batch", "materials", "events", "sensor_readings"]:
        n = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {n} rows")

    print("\nBatches by product:")
    for row in db.execute("SELECT produkt, COUNT(*) c FROM batch GROUP BY produkt ORDER BY c DESC"):
        print(f"  {row[0]}: {row[1]}")

    verified = db.execute("SELECT COUNT(*) FROM batch WHERE _verified = 1").fetchone()[0]
    total = db.execute("SELECT COUNT(*) FROM batch").fetchone()[0]
    print(f"\nVerified: {verified}/{total}")

    print("\nEvents by stage:")
    for row in db.execute("""
        SELECT stage, event_type, COUNT(*) c
        FROM events GROUP BY stage, event_type ORDER BY stage, event_type
    """):
        print(f"  {row[0]}.{row[1]}: {row[2]}")

    print("\nMaterials by category:")
    for row in db.execute("SELECT kategoria, COUNT(*) FROM materials GROUP BY kategoria"):
        print(f"  {row[0]}: {row[1]}")

    linked = db.execute("SELECT COUNT(*) FROM events WHERE material_id IS NOT NULL").fetchone()[0]
    total_ev = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    print(f"\nEvents with material_id: {linked}/{total_ev}")

    db.close()


if __name__ == "__main__":
    import sys

    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data")
    db_path = data_dir / "batch_db_v4.sqlite"
    v3_db_path = data_dir / "batch_db.sqlite"

    if db_path.exists():
        db_path.unlink()
        print(f"Removed existing {db_path}")

    count = migrate_all(data_dir / "output_json", db_path, use_verified=True)
    print(f"Migrated {count} batches → {db_path}")

    if v3_db_path.exists():
        db = sqlite3.connect(str(db_path))
        migrate_sensors(db, v3_db_path)
        db.commit()
        db.close()
        print("Migrated sensor_readings from v3 database")

    print_report(db_path)
