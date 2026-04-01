-- schema_v4.sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE batch (
    batch_id                TEXT PRIMARY KEY,
    produkt                 TEXT NOT NULL,
    nr_partii               TEXT NOT NULL,
    equipment_id            TEXT,
    nr_mieszalnika          TEXT,
    template_id             TEXT,
    dt_start                TEXT,
    dt_end                  TEXT,
    wielkosc_kg             REAL,
    wielkosc_receptura_kg   REAL,
    ak_datetime             TEXT,
    ak_ph                   REAL,
    ak_ph_10proc            REAL,
    ak_nd20                 REAL,
    ak_procent_sm           REAL,
    ak_procent_nacl         REAL,
    ak_procent_sa           REAL,
    ak_procent_aa           REAL,
    ak_procent_so3          REAL,
    ak_procent_h2o2         REAL,
    ak_barwa_raw            TEXT,
    ak_barwa_fau            REAL,
    ak_barwa_hz             REAL,
    ak_barwa_opis           TEXT,
    ak_jakosc_ocena         TEXT,
    ak_certyfikat_nr        TEXT,
    pomp_dt_start           TEXT,
    pomp_dt_end             TEXT,
    pomp_temp_max_c         REAL,
    pomp_zbiornik_1         TEXT,
    pomp_wskazanie_od_1     REAL,
    pomp_wskazanie_do_1     REAL,
    pomp_zbiornik_2         TEXT,
    pomp_wskazanie_od_2     REAL,
    pomp_wskazanie_do_2     REAL,
    _source                 TEXT DEFAULT 'ocr',
    _schema_version         TEXT DEFAULT '4.0',
    _ocr_pewnosc_mean       REAL,
    _verified               INTEGER DEFAULT 0
);

CREATE TABLE materials (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id                TEXT NOT NULL REFERENCES batch(batch_id),
    kategoria               TEXT NOT NULL,
    kod                     TEXT NOT NULL,
    nazwa                   TEXT,
    ilosc_kg                REAL,
    ilosc_receptura_kg      REAL,
    nr_partii_materialu     TEXT,
    lp                      INTEGER,
    godzina                 TEXT,
    _ocr_pewnosc            REAL,
    _korekta                TEXT
);

CREATE TABLE events (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id                TEXT NOT NULL REFERENCES batch(batch_id),
    equipment_id            TEXT,
    dt                      TEXT NOT NULL,
    dt_end                  TEXT,
    stage                   TEXT NOT NULL,
    event_type              TEXT NOT NULL,
    seq                     INTEGER,
    substancja_kod          TEXT,
    substancja_nazwa        TEXT,
    ilosc_kg                REAL,
    temperatura_c           REAL,
    proznia_ba              REAL,
    ph                      REAL,
    ph_10proc               REAL,
    nd20                    REAL,
    procent_aa              REAL,
    procent_sm              REAL,
    procent_sa              REAL,
    procent_nacl            REAL,
    procent_so3             REAL,
    procent_h2o2            REAL,
    le                      REAL,
    lk                      REAL,
    barwa_raw               TEXT,
    barwa_fau               REAL,
    barwa_hz                REAL,
    barwa_opis              TEXT,
    opis                    TEXT,
    temperatura_docelowa_c  REAL,
    operator_raw            TEXT,
    material_id             INTEGER REFERENCES materials(id),
    uwagi                   TEXT,
    _source                 TEXT DEFAULT 'ocr',
    _ts_precision           TEXT DEFAULT 'minute',
    _ocr_pewnosc            REAL,
    _korekta                TEXT
);

CREATE TABLE sensor_readings (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id                TEXT NOT NULL REFERENCES batch(batch_id),
    datetime                TEXT NOT NULL,
    source                  TEXT,
    equipment               TEXT,
    temp_c                  REAL,
    temp_plaszcz_c          REAL,
    proznia_bar             REAL,
    dozownik_l              REAL,
    etap                    TEXT
);

CREATE INDEX idx_events_batch ON events(batch_id);
CREATE INDEX idx_events_batch_dt ON events(batch_id, dt);
CREATE INDEX idx_events_stage ON events(batch_id, stage);
CREATE INDEX idx_events_equipment_dt ON events(equipment_id, dt);
CREATE INDEX idx_materials_batch ON materials(batch_id);
CREATE INDEX idx_sensor_batch ON sensor_readings(batch_id);
CREATE INDEX idx_sensor_dt ON sensor_readings(datetime);
CREATE INDEX idx_sensor_equip_dt ON sensor_readings(equipment, datetime);
