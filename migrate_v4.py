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
