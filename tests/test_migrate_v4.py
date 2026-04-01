import json
import sqlite3
import pytest
from pathlib import Path

SAMPLE_V3 = {
    "produkt": "Chegina K40GL",
    "nr_partii": "1/2026",
    "_schema_version": "3.0",
    "strona1": {
        "produkt": "Chegina K40GL",
        "template_id": "T111",
        "nr_partii": "1/2026",
        "nr_amidatora": "8",
        "nr_mieszalnika": "25",
        "data_rozpoczecia": "2026-01-07",
        "data_zakonczenia": "2026-01-08",
        "wielkosc_szarzy_kg": 11310,
        "wielkosc_szarzy_recepturowa_kg": 10900,
        "surowce": [
            {
                "lp": 1,
                "nazwa_surowca": "Kwasy tłuszczowe C12-18",
                "kod_surowca": "kwasy_c1218",
                "ilosc_recepturowa_kg": 2240,
                "ilosc_zaladowana_kg": 2240,
                "numer_partii_surowca": "531/25",
                "ocr_pewnosc": 0.85,
                "korekta": None
            }
        ],
        "standaryzowanie": [
            {
                "nazwa_dodatku": "Kwas cytrynowy jednowodny",
                "kod_dodatku": "kw_cytrynowy",
                "ilosc_kg": 125,
                "godzina": "20:15",
                "nr_partii_dodatku": "516/26",
                "ocr_pewnosc": 0.8
            }
        ],
        "pola_watpliwe": []
    },
    "proces": {
        "etapy": {
            "amid": {
                "wlaczenie_reaktora": {
                    "datetime_start": "2026-01-07T10:45",
                    "temperatura_docelowa_c": 170,
                    "datetime_osiagniecia_temp": "2026-01-07T12:30",
                    "ocr_pewnosc": 0.8
                },
                "kroki": [
                    {
                        "typ": "analiza",
                        "datetime_start": "2026-01-08T03:55",
                        "lk_liczba_kwasowa": 11.78,
                        "le_liczba_estrowa": None,
                        "la_liczba_kwasowa": None,
                        "barwa": None, "barwa_fau": None, "barwa_hz": None, "barwa_opis": None,
                        "ocr_pewnosc": 0.8
                    },
                    {
                        "typ": "dodatek",
                        "datetime_start": "2026-01-08T04:05",
                        "substancja": "DMAPA",
                        "ilosc_kg": 30,
                        "temperatura_c": None,
                        "standaryzowanie_idx": None,
                        "ocr_pewnosc": 0.8
                    }
                ]
            },
            "smca": {
                "wytworzenie_smca": {
                    "datetime_start": "2026-01-07T14:00",
                    "datetime_koniec": "2026-01-07T14:30",
                    "ilosc_naoh_kg": 232,
                    "temperatura_c": 45,
                    "ocr_pewnosc": 0.8
                },
                "analiza_smca": {
                    "datetime_start": "2026-01-07T14:35",
                    "ph": 8.5,
                    "ocr_pewnosc": 0.9
                }
            },
            "czwartorzedowanie": {
                "przeciagniecie_amidu": {
                    "datetime_start": "2026-01-08T08:00",
                    "temperatura_c": 85,
                    "ocr_pewnosc": 0.8
                },
                "kroki": [
                    {
                        "typ": "dodatek",
                        "datetime_start": "2026-01-08T09:30",
                        "substancja": "NaOH",
                        "ilosc_kg": 232,
                        "temperatura_c": 87.5,
                        "ocr_pewnosc": 0.8
                    },
                    {
                        "typ": "analiza",
                        "datetime_start": "2026-01-08T10:03",
                        "ph_10proc": 6.0,
                        "nd20": 1.4098,
                        "ocr_pewnosc": 0.7
                    }
                ]
            },
            "wybielanie": None,
            "sulfonowanie": {"kroki": []},
            "utlenienie": {"kroki": []},
            "standaryzacja": {
                "kroki": [
                    {
                        "typ": "dodatek",
                        "datetime_start": "2026-01-08T20:15",
                        "substancja": "Kw. cytrynowy",
                        "ilosc_kg": 125,
                        "standaryzowanie_idx": 0,
                        "ocr_pewnosc": 0.8
                    }
                ]
            }
        },
        "pola_watpliwe": ["etapy.czwartorzedowanie.kroki[1].datetime_start"]
    },
    "koncowa": {
        "standaryzacja_kontynuacja": {
            "kroki": [
                {
                    "typ": "dodatek",
                    "datetime_start": "2026-01-08T21:09",
                    "substancja": "Woda",
                    "ilosc_kg": 540,
                    "operator_podpis_raw": "MG",
                    "ocr_pewnosc": 0.8
                }
            ]
        },
        "analiza_miedzyoper_standaryzowanie": None,
        "analiza_koncowa": {
            "datetime": "2026-01-08T21:09",
            "ph": None,
            "ph_10proc": 4.69,
            "nd20": 1.407,
            "procent_sm": 45,
            "procent_nacl": 6.1,
            "procent_sa": 38.3,
            "procent_aa": None,
            "procent_so3": 0.007,
            "procent_h2o2": None,
            "le_liczba_kwasowa": None,
            "barwa": "0,54",
            "barwa_fau": None,
            "barwa_hz": 40,
            "barwa_opis": "400u",
            "jakosc_ocena": "zgodna",
            "certyfikat_nr": None,
            "ocr_pewnosc": 0.8
        },
        "przepompowanie": {
            "datetime_start": "2026-01-08T22:20",
            "datetime_koniec": "2026-01-08T22:20",
            "temperatura_max_c": 50,
            "zbiornik_1": "M16",
            "wskazanie_od_1": 3.01,
            "wskazanie_do_1": 19.32,
            "zbiornik_2": None,
            "wskazanie_od_2": None,
            "wskazanie_do_2": None,
            "operator_podpis_raw": "GS",
            "ocr_pewnosc": 0.8
        },
        "pola_watpliwe": []
    }
}


@pytest.fixture
def v4_db(tmp_path):
    """Create an empty v4 database."""
    db_path = tmp_path / "batch_db_v4.sqlite"
    from migrate_v4 import create_db
    create_db(db_path)
    return db_path


def test_batch_migration(v4_db):
    from migrate_v4 import migrate_batch

    db = sqlite3.connect(str(v4_db))
    db.row_factory = sqlite3.Row
    migrate_batch(db, SAMPLE_V3)
    db.commit()

    row = db.execute("SELECT * FROM batch WHERE batch_id = 'Chegina_K40GL__1_2026'").fetchone()
    assert row is not None
    assert row["produkt"] == "Chegina K40GL"
    assert row["nr_partii"] == "1/2026"
    assert row["equipment_id"] == "8"
    assert row["wielkosc_kg"] == 11310
    assert row["wielkosc_receptura_kg"] == 10900
    assert row["dt_start"] == "2026-01-07"
    assert row["dt_end"] == "2026-01-08"
    assert row["ak_ph_10proc"] == 4.69
    assert row["ak_nd20"] == 1.407
    assert row["ak_procent_sa"] == 38.3
    assert row["ak_jakosc_ocena"] == "zgodna"
    assert row["ak_barwa_hz"] == 40
    assert row["pomp_zbiornik_1"] == "M16"
    assert row["pomp_wskazanie_od_1"] == 3.01
    assert row["pomp_wskazanie_do_1"] == 19.32
    assert row["_source"] == "ocr"
    assert row["_schema_version"] == "4.0"
    db.close()


def test_materials_migration(v4_db):
    from migrate_v4 import migrate_batch, migrate_materials

    db = sqlite3.connect(str(v4_db))
    db.row_factory = sqlite3.Row
    batch_id = migrate_batch(db, SAMPLE_V3)
    migrate_materials(db, batch_id, SAMPLE_V3)
    db.commit()

    rows = db.execute(
        "SELECT * FROM materials WHERE batch_id = ? ORDER BY kategoria, lp",
        (batch_id,)
    ).fetchall()

    # 1 surowiec + 1 dodatek in SAMPLE_V3
    assert len(rows) == 2

    sur = rows[1]  # surowiec sorts after dodatek
    assert sur["kategoria"] == "surowiec"
    assert sur["kod"] == "kwasy_c1218"
    assert sur["ilosc_kg"] == 2240
    assert sur["ilosc_receptura_kg"] == 2240
    assert sur["nr_partii_materialu"] == "531/25"
    assert sur["lp"] == 1

    dod = rows[0]  # dodatek
    assert dod["kategoria"] == "dodatek"
    assert dod["kod"] == "kw_cytrynowy"
    assert dod["ilosc_kg"] == 125
    assert dod["ilosc_receptura_kg"] is None
    assert dod["godzina"] == "20:15"
    assert dod["_ocr_pewnosc"] == 0.8
    db.close()
