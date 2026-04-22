"""Build long-format rows for the ML export package.

Public API:
    build_batches(db, produkty, statuses) -> list[dict]   # one row per batch
    build_sessions(db, ebr_ids)          -> list[dict]   # one row per (batch, etap, runda)
    build_measurements(db, ebr_ids)      -> list[dict]   # pomiary + legacy, long
    build_corrections(db, ebr_ids)       -> list[dict]   # one row per correction
    export_ml_package(db, produkty, statuses) -> bytes   # zip of 4 CSVs + schema + README
"""
import csv
import io
import json
import sqlite3
import zipfile
from datetime import datetime

from mbr.ml_export.schema import build_schema

DEFAULT_PRODUKTY = ["Chegina_K7"]


def _meff(masa: float) -> float:
    return masa - 1000 if masa > 6600 else masa - 500


def _batch_target(db: sqlite3.Connection, ebr_id: int, produkt: str) -> tuple[float | None, float | None]:
    """Return (target_ph, target_nd20). Prefer cele_json snapshot on any
    standaryzacja session; fall back to korekta_cele globals for the produkt."""
    tph = tnd = None
    try:
        row = db.execute(
            """SELECT s.cele_json
                 FROM ebr_etap_sesja s
                 JOIN etapy_analityczne ea ON ea.id = s.etap_id
                WHERE s.ebr_id = ? AND ea.kod = 'standaryzacja'
                  AND s.cele_json IS NOT NULL
             ORDER BY s.runda
                LIMIT 1""",
            (ebr_id,),
        ).fetchone()
    except sqlite3.Error:
        row = None
    if row and row["cele_json"]:
        try:
            cele = json.loads(row["cele_json"])
            tph = cele.get("target_ph")
            tnd = cele.get("target_nd20")
        except json.JSONDecodeError:
            pass
    if tph is None or tnd is None:
        globals_ = db.execute(
            "SELECT kod, wartosc FROM korekta_cele WHERE produkt = ?",
            (produkt,),
        ).fetchall()
        for g in globals_:
            if g["kod"] == "target_ph" and tph is None:
                tph = g["wartosc"]
            elif g["kod"] == "target_nd20" and tnd is None:
                tnd = g["wartosc"]
    return tph, tnd


def build_batches(db: sqlite3.Connection, produkty: list[str],
                  statuses: tuple[str, ...]) -> list[dict]:
    if not produkty or not statuses:
        return []
    prod_q = ",".join("?" for _ in produkty)
    stat_q = ",".join("?" for _ in statuses)
    rows = db.execute(
        f"""SELECT e.ebr_id, e.batch_id, e.nr_partii, e.wielkosc_szarzy_kg, e.nastaw,
                   e.dt_start, e.dt_end, e.status, e.pakowanie_bezposrednie,
                   m.produkt
              FROM ebr_batches e
              JOIN mbr_templates m ON m.mbr_id = e.mbr_id
             WHERE e.status IN ({stat_q}) AND e.typ = 'szarza'
               AND m.produkt IN ({prod_q})
          ORDER BY e.ebr_id""",
        (*statuses, *produkty),
    ).fetchall()

    out = []
    for b in rows:
        masa = b["wielkosc_szarzy_kg"] or b["nastaw"] or 0
        tph, tnd = _batch_target(db, b["ebr_id"], b["produkt"])
        out.append({
            "ebr_id":      b["ebr_id"],
            "batch_id":    b["batch_id"],
            "nr_partii":   b["nr_partii"],
            "produkt":     b["produkt"],
            "status":      b["status"],
            "masa_kg":     float(masa) if masa else 0.0,
            "meff_kg":     float(_meff(masa)) if masa else 0.0,
            "dt_start":    b["dt_start"],
            "dt_end":      b["dt_end"],
            "pakowanie":   b["pakowanie_bezposrednie"] or "zbiornik",
            "target_ph":   tph,
            "target_nd20": tnd,
        })
    return out


def build_sessions(db: sqlite3.Connection, ebr_ids: list[int]) -> list[dict]:
    if not ebr_ids:
        return []
    ids_q = ",".join("?" for _ in ebr_ids)
    rows = db.execute(
        f"""SELECT s.ebr_id, ea.kod AS etap, s.runda, s.dt_start, s.laborant,
                   pp.kolejnosc AS pipeline_order
              FROM ebr_etap_sesja s
              JOIN etapy_analityczne ea ON ea.id = s.etap_id
              JOIN ebr_batches e        ON e.ebr_id = s.ebr_id
              JOIN mbr_templates m      ON m.mbr_id = e.mbr_id
              LEFT JOIN produkt_pipeline pp
                     ON pp.produkt = m.produkt AND pp.etap_id = s.etap_id
             WHERE s.ebr_id IN ({ids_q})
          ORDER BY s.ebr_id, pp.kolejnosc, s.runda""",
        ebr_ids,
    ).fetchall()
    return [
        {
            "ebr_id":   r["ebr_id"],
            "etap":     r["etap"],
            "runda":    r["runda"],
            "dt_start": r["dt_start"],
            "laborant": r["laborant"],
        }
        for r in rows
    ]


_RECIPE_PARAMS = {"na2so3_recept_kg"}


def build_measurements(db: sqlite3.Connection, ebr_ids: list[int]) -> list[dict]:
    """Merge ebr_pomiar (per-session, is_legacy=0) with ebr_wyniki (per-batch, is_legacy=1).

    Rules:
    1. New (ebr_pomiar) is authoritative — emit all.
    2. For each legacy (ebr_id, etap, param) in ebr_wyniki: emit only if no matching
       new row exists for the same triple. Round = 0 for legacy.
    3. Recipe params (_RECIPE_PARAMS) are exempt from rule 2 — always emitted from
       legacy with runda=0. They aren't measurements, they're dosage history.
    """
    if not ebr_ids:
        return []
    ids_q = ",".join("?" for _ in ebr_ids)

    new_rows = db.execute(
        f"""SELECT s.ebr_id, ea.kod AS etap, s.runda,
                   pa.kod AS param_kod, p.wartosc, p.w_limicie,
                   p.dt_wpisu, p.wpisal
              FROM ebr_pomiar p
              JOIN ebr_etap_sesja s       ON s.id = p.sesja_id
              JOIN etapy_analityczne ea   ON ea.id = s.etap_id
              JOIN parametry_analityczne pa ON pa.id = p.parametr_id
             WHERE s.ebr_id IN ({ids_q})
          ORDER BY s.ebr_id, s.etap_id, s.runda, pa.id""",
        ebr_ids,
    ).fetchall()

    out: list[dict] = []
    new_triples: set[tuple[int, str, str]] = set()
    for r in new_rows:
        out.append({
            "ebr_id":       r["ebr_id"],
            "etap":         r["etap"],
            "runda":        r["runda"],
            "param_kod":    r["param_kod"],
            "wartosc":      r["wartosc"],
            "wartosc_text": None,
            "w_limicie":    r["w_limicie"],
            "dt_wpisu":     r["dt_wpisu"],
            "wpisal":       r["wpisal"],
            "is_legacy":    0,
        })
        new_triples.add((r["ebr_id"], r["etap"], r["param_kod"]))

    legacy_rows = db.execute(
        f"""SELECT ebr_id, sekcja AS etap, kod_parametru AS param_kod,
                   wartosc, wartosc_text, w_limicie, dt_wpisu, wpisal
              FROM ebr_wyniki
             WHERE ebr_id IN ({ids_q})
          ORDER BY ebr_id, sekcja, kod_parametru""",
        ebr_ids,
    ).fetchall()

    for r in legacy_rows:
        triple = (r["ebr_id"], r["etap"], r["param_kod"])
        if r["param_kod"] not in _RECIPE_PARAMS and triple in new_triples:
            continue  # new value authoritative, legacy suppressed
        out.append({
            "ebr_id":       r["ebr_id"],
            "etap":         r["etap"],
            "runda":        0,
            "param_kod":    r["param_kod"],
            "wartosc":      r["wartosc"],
            "wartosc_text": r["wartosc_text"],
            "w_limicie":    r["w_limicie"],
            "dt_wpisu":     r["dt_wpisu"],
            "wpisal":       r["wpisal"],
            "is_legacy":    1,
        })
    return out


def build_corrections(db: sqlite3.Connection, ebr_ids: list[int]) -> list[dict]:
    if not ebr_ids:
        return []
    ids_q = ",".join("?" for _ in ebr_ids)
    rows = db.execute(
        f"""SELECT s.ebr_id, ea.kod AS etap, s.runda,
                   ek.substancja, k.ilosc, k.ilosc_wyliczona,
                   k.status, k.zalecil, k.dt_wykonania
              FROM ebr_korekta_v2 k
              JOIN ebr_etap_sesja s          ON s.id = k.sesja_id
              JOIN etapy_analityczne ea      ON ea.id = s.etap_id
              JOIN etap_korekty_katalog ek   ON ek.id = k.korekta_typ_id
             WHERE s.ebr_id IN ({ids_q})
          ORDER BY s.ebr_id, s.etap_id, s.runda, ek.kolejnosc""",
        ebr_ids,
    ).fetchall()
    return [
        {
            "ebr_id":        r["ebr_id"],
            "etap":          r["etap"],
            "runda":         r["runda"],
            "substancja":    r["substancja"],
            "kg":            r["ilosc"],
            "sugest_kg":     r["ilosc_wyliczona"],
            "status":        r["status"],
            "zalecil":       r["zalecil"],
            "dt_wykonania":  r["dt_wykonania"],
        }
        for r in rows
    ]


_README = """# K7 ML Export — Long Format

Cztery pliki CSV w formacie tidy + `schema.json` z metadanymi.

## Pliki

| Plik | Ziarnistość | Użycie |
|---|---|---|
| `batches.csv`      | 1 wiersz / szarża | metadata, target, mass |
| `sessions.csv`     | 1 / (szarża, etap, runda) | kiedy / kto przeprowadził etap |
| `measurements.csv` | 1 / (szarża, etap, runda, parametr) | pomiary (sesje + legacy) |
| `corrections.csv`  | 1 / (szarża, etap, runda, substancja) | dozowanie |
| `schema.json`      | słownik | jednostki, specs, formuły, target candidates |

## Uwaga o legacy

Pomiary z `ebr_wyniki` (przed wprowadzeniem sesji) mają `runda=0` i `is_legacy=1`.
Jeśli ten sam `(batch, etap, parametr)` ma wpis w obu źródłach, emitowany jest
tylko nowy (session-based). Wyjątek: `na2so3_recept_kg` (recepta) — zawsze legacy.

## Przykład użycia w pandas

```python
import pandas as pd
import zipfile

zf = zipfile.ZipFile("k7_ml_export_2026-04-20.zip")
b = pd.read_csv(zf.open("batches.csv"))
m = pd.read_csv(zf.open("measurements.csv"))
df = m.merge(b, on="ebr_id")

# wide per (batch, stage, round) dla pojedynczego parametru:
wide = df[df.param_kod == "barwa_I2"].pivot_table(
    index="ebr_id", columns=["etap", "runda"], values="wartosc"
)
```
"""


def _csv_bytes(rows: list[dict], columns: list[str]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


_BATCH_COLS = ["ebr_id", "batch_id", "nr_partii", "produkt", "status",
               "masa_kg", "meff_kg", "dt_start", "dt_end", "pakowanie",
               "target_ph", "target_nd20"]
_SESS_COLS  = ["ebr_id", "etap", "runda", "dt_start", "laborant"]
_MEAS_COLS  = ["ebr_id", "etap", "runda", "param_kod",
               "wartosc", "wartosc_text", "w_limicie",
               "dt_wpisu", "wpisal", "is_legacy"]
_CORR_COLS  = ["ebr_id", "etap", "runda", "substancja",
               "kg", "sugest_kg", "status", "zalecil", "dt_wykonania"]


def export_ml_package(db: sqlite3.Connection,
                      produkty: list[str] | None = None,
                      statuses: tuple[str, ...] = ("completed",)) -> bytes:
    """Build the full zip bytes: 4 CSVs + schema.json + README.md."""
    produkty = produkty or list(DEFAULT_PRODUKTY)
    batches = build_batches(db, produkty, statuses)
    ebr_ids = [b["ebr_id"] for b in batches]
    sessions     = build_sessions(db, ebr_ids)
    measurements = build_measurements(db, ebr_ids)
    corrections  = build_corrections(db, ebr_ids)

    counts = {
        "batches":      len(batches),
        "sessions":     len(sessions),
        "measurements": len(measurements),
        "corrections":  len(corrections),
    }
    schema = build_schema(db, produkty, counts=counts)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("batches.csv",      _csv_bytes(batches,      _BATCH_COLS))
        zf.writestr("sessions.csv",     _csv_bytes(sessions,     _SESS_COLS))
        zf.writestr("measurements.csv", _csv_bytes(measurements, _MEAS_COLS))
        zf.writestr("corrections.csv",  _csv_bytes(corrections,  _CORR_COLS))
        zf.writestr("schema.json",      json.dumps(schema, ensure_ascii=False, indent=2).encode("utf-8"))
        zf.writestr("README.md",        _README.encode("utf-8"))
    return buf.getvalue()

