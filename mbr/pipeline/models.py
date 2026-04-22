"""
pipeline/models.py — CRUD for analytical pipeline catalog and product pipeline.

Tables:
  etapy_analityczne     — analytical stage catalog
  etap_parametry        — parameters per catalog stage (with limits/options)
  etap_warunki          — pass/fail gate conditions per stage
  etap_korekty_katalog  — correction substance catalog per stage
  produkt_pipeline      — ordered stages assigned to a product
  produkt_etap_limity   — product-specific limit overrides per stage+parameter
"""

import json as _json
import re as _re
import sqlite3
from datetime import datetime

from mbr.shared.timezone import app_now_iso
from mbr.shared import audit as _audit


# ---------------------------------------------------------------------------
# etapy_analityczne CRUD
# ---------------------------------------------------------------------------

def create_etap(
    db: sqlite3.Connection,
    *,
    kod: str,
    nazwa: str,
    typ_cyklu: str = "jednorazowy",
    opis: str | None = None,
    kolejnosc_domyslna: int = 0,
) -> int:
    """Insert a new analytical stage. Returns new id."""
    cur = db.execute(
        """INSERT INTO etapy_analityczne (kod, nazwa, typ_cyklu, opis, kolejnosc_domyslna)
           VALUES (?, ?, ?, ?, ?)""",
        (kod, nazwa, typ_cyklu, opis, kolejnosc_domyslna),
    )
    return cur.lastrowid


def list_etapy(db: sqlite3.Connection, *, only_active: bool = False) -> list[dict]:
    """Return all stages ordered by kolejnosc_domyslna, then id."""
    sql = "SELECT * FROM etapy_analityczne"
    if only_active:
        sql += " WHERE aktywny = 1"
    sql += " ORDER BY kolejnosc_domyslna, id"
    return [dict(r) for r in db.execute(sql).fetchall()]


def get_etap(db: sqlite3.Connection, etap_id: int) -> dict | None:
    row = db.execute("SELECT * FROM etapy_analityczne WHERE id = ?", (etap_id,)).fetchone()
    return dict(row) if row else None


_ETAP_ALLOWED_FIELDS = {"nazwa", "opis", "typ_cyklu", "kolejnosc_domyslna"}


def update_etap(db: sqlite3.Connection, etap_id: int, **fields) -> None:
    """Update allowed fields on an analytical stage."""
    to_update = {k: v for k, v in fields.items() if k in _ETAP_ALLOWED_FIELDS}
    if not to_update:
        return
    set_clause = ", ".join(f"{k} = ?" for k in to_update)
    values = list(to_update.values()) + [etap_id]
    db.execute(f"UPDATE etapy_analityczne SET {set_clause} WHERE id = ?", values)


def deactivate_etap(db: sqlite3.Connection, etap_id: int) -> None:
    db.execute("UPDATE etapy_analityczne SET aktywny = 0 WHERE id = ?", (etap_id,))


# ---------------------------------------------------------------------------
# etap_parametry CRUD
# ---------------------------------------------------------------------------

_EP_ALLOWED_FIELDS = {
    "kolejnosc", "min_limit", "max_limit", "nawazka_g", "precision",
    "spec_value", "wymagany", "grupa", "formula", "sa_bias", "krok",
}


def add_etap_parametr(
    db: sqlite3.Connection,
    etap_id: int,
    parametr_id: int,
    kolejnosc: int = 0,
    **kwargs,
) -> int:
    """Add a parameter to a stage. Returns new id."""
    cols = ["etap_id", "parametr_id", "kolejnosc"]
    vals: list = [etap_id, parametr_id, kolejnosc]
    for key, val in kwargs.items():
        if key in _EP_ALLOWED_FIELDS:
            cols.append(key)
            vals.append(val)
    placeholders = ", ".join("?" * len(cols))
    col_clause = ", ".join(cols)
    cur = db.execute(
        f"INSERT INTO etap_parametry ({col_clause}) VALUES ({placeholders})",
        vals,
    )
    return cur.lastrowid


def list_etap_parametry(db: sqlite3.Connection, etap_id: int) -> list[dict]:
    """List parameters for a stage, JOINed with parametry_analityczne. ORDER BY kolejnosc."""
    rows = db.execute(
        """
        SELECT
            ep.id, ep.etap_id, ep.parametr_id, ep.kolejnosc,
            ep.min_limit, ep.max_limit, ep.nawazka_g, ep.precision,
            ep.spec_value, ep.wymagany, ep.grupa, ep.formula, ep.sa_bias, ep.krok,
            pa.kod, pa.label, pa.typ, pa.skrot, pa.jednostka,
            pa.metoda_id, pa.metoda_nazwa, pa.metoda_formula, pa.metoda_factor
        FROM etap_parametry ep
        JOIN parametry_analityczne pa ON pa.id = ep.parametr_id
        WHERE ep.etap_id = ?
        ORDER BY ep.kolejnosc
        """,
        (etap_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def update_etap_parametr(db: sqlite3.Connection, ep_id: int, **fields) -> None:
    to_update = {k: v for k, v in fields.items() if k in _EP_ALLOWED_FIELDS}
    if not to_update:
        return
    set_clause = ", ".join(f"{k} = ?" for k in to_update)
    values = list(to_update.values()) + [ep_id]
    db.execute(f"UPDATE etap_parametry SET {set_clause} WHERE id = ?", values)


def remove_etap_parametr(db: sqlite3.Connection, ep_id: int) -> None:
    db.execute("DELETE FROM etap_parametry WHERE id = ?", (ep_id,))


# ---------------------------------------------------------------------------
# etap_warunki CRUD
# ---------------------------------------------------------------------------

def add_etap_warunek(
    db: sqlite3.Connection,
    etap_id: int,
    parametr_id: int,
    operator: str,
    wartosc: float,
    wartosc_max: float | None = None,
    opis_warunku: str | None = None,
) -> int:
    cur = db.execute(
        """INSERT INTO etap_warunki
               (etap_id, parametr_id, operator, wartosc, wartosc_max, opis_warunku)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (etap_id, parametr_id, operator, wartosc, wartosc_max, opis_warunku),
    )
    return cur.lastrowid


def list_etap_warunki(db: sqlite3.Connection, etap_id: int) -> list[dict]:
    """List gate conditions for a stage, JOINed with parametry_analityczne."""
    rows = db.execute(
        """
        SELECT
            ew.id, ew.etap_id, ew.parametr_id, ew.operator,
            ew.wartosc, ew.wartosc_max, ew.opis_warunku,
            pa.kod, pa.label, pa.skrot
        FROM etap_warunki ew
        JOIN parametry_analityczne pa ON pa.id = ew.parametr_id
        WHERE ew.etap_id = ?
        ORDER BY ew.id
        """,
        (etap_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_etap_decyzje(
    db: sqlite3.Connection,
    etap_id: int,
    typ: str,
) -> list[dict]:
    """Return decision options for a pipeline stage, filtered by pass/fail type."""
    rows = db.execute("""
        SELECT id, etap_id, typ, kod, label, akcja, wymaga_komentarza, kolejnosc
        FROM etap_decyzje
        WHERE etap_id = ? AND typ = ?
        ORDER BY kolejnosc
    """, (etap_id, typ)).fetchall()
    return [dict(r) for r in rows]


def remove_etap_warunek(db: sqlite3.Connection, warunek_id: int) -> None:
    db.execute("DELETE FROM etap_warunki WHERE id = ?", (warunek_id,))


# ---------------------------------------------------------------------------
# etap_korekty_katalog CRUD
# ---------------------------------------------------------------------------

def add_etap_korekta(
    db: sqlite3.Connection,
    etap_id: int,
    substancja: str,
    jednostka: str = "kg",
    wykonawca: str = "produkcja",
    kolejnosc: int = 0,
) -> int:
    cur = db.execute(
        """INSERT INTO etap_korekty_katalog
               (etap_id, substancja, jednostka, wykonawca, kolejnosc)
           VALUES (?, ?, ?, ?, ?)""",
        (etap_id, substancja, jednostka, wykonawca, kolejnosc),
    )
    return cur.lastrowid


def list_etap_korekty(db: sqlite3.Connection, etap_id: int) -> list[dict]:
    """List correction substances for a stage. ORDER BY kolejnosc."""
    rows = db.execute(
        "SELECT * FROM etap_korekty_katalog WHERE etap_id = ? ORDER BY kolejnosc",
        (etap_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def remove_etap_korekta(db: sqlite3.Connection, korekta_id: int) -> None:
    db.execute("DELETE FROM etap_korekty_katalog WHERE id = ?", (korekta_id,))


# ---------------------------------------------------------------------------
# Task 3: produkt_pipeline CRUD
# ---------------------------------------------------------------------------

def set_produkt_pipeline(
    db: sqlite3.Connection,
    produkt: str,
    etap_id: int,
    kolejnosc: int,
) -> int:
    """Assign (or update kolejnosc for) a stage in a product's pipeline. Returns row id."""
    cur = db.execute(
        """INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc)
           VALUES (?, ?, ?)
           ON CONFLICT(produkt, etap_id) DO UPDATE SET kolejnosc = excluded.kolejnosc""",
        (produkt, etap_id, kolejnosc),
    )
    return cur.lastrowid


def get_produkt_pipeline(db: sqlite3.Connection, produkt: str) -> list[dict]:
    """Return ordered pipeline stages for a product, JOINed with etapy_analityczne."""
    rows = db.execute(
        """
        SELECT
            pp.id, pp.produkt, pp.etap_id, pp.kolejnosc,
            ea.kod, ea.nazwa, ea.typ_cyklu
        FROM produkt_pipeline pp
        JOIN etapy_analityczne ea ON ea.id = pp.etap_id
        WHERE pp.produkt = ?
        ORDER BY pp.kolejnosc
        """,
        (produkt,),
    ).fetchall()
    return [dict(r) for r in rows]


def pipeline_has_multi_stage(db: sqlite3.Connection, produkt: str) -> bool:
    """True iff produkt_pipeline has >1 row for this product.

    Single source of truth for "does this product use the extended batch card?"
    Replaces the legacy FULL_PIPELINE_PRODUCTS hardcoded set.
    """
    row = db.execute(
        "SELECT COUNT(*) AS n FROM produkt_pipeline WHERE produkt = ?",
        (produkt,),
    ).fetchone()
    return row["n"] > 1


def remove_pipeline_etap(db: sqlite3.Connection, produkt: str, etap_id: int) -> None:
    db.execute(
        "DELETE FROM produkt_pipeline WHERE produkt = ? AND etap_id = ?",
        (produkt, etap_id),
    )


def reorder_pipeline(db: sqlite3.Connection, produkt: str, etap_ids: list[int]) -> None:
    """Set kolejnosc = position (1-indexed) for each etap_id in etap_ids."""
    for i, etap_id in enumerate(etap_ids, start=1):
        db.execute(
            "UPDATE produkt_pipeline SET kolejnosc = ? WHERE produkt = ? AND etap_id = ?",
            (i, produkt, etap_id),
        )


# ---------------------------------------------------------------------------
# Task 3: produkt_etap_limity CRUD
# ---------------------------------------------------------------------------

_PEL_ALLOWED_FIELDS = {"min_limit", "max_limit", "nawazka_g", "precision", "spec_value", "grupa"}


def set_produkt_etap_limit(
    db: sqlite3.Connection,
    produkt: str,
    etap_id: int,
    parametr_id: int,
    **kwargs,
) -> int:
    """INSERT or UPDATE product-level limit overrides for a stage+parameter."""
    # Collect known fields
    data = {k: v for k, v in kwargs.items() if k in _PEL_ALLOWED_FIELDS}

    if not data:
        # Just ensure the row exists with nulls
        cur = db.execute(
            """INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id)
               VALUES (?, ?, ?)
               ON CONFLICT(produkt, etap_id, parametr_id) DO NOTHING""",
            (produkt, etap_id, parametr_id),
        )
        return cur.lastrowid or 0

    cols = ["produkt", "etap_id", "parametr_id"] + list(data.keys())
    vals = [produkt, etap_id, parametr_id] + list(data.values())
    placeholders = ", ".join("?" * len(cols))
    col_clause = ", ".join(cols)
    set_clause = ", ".join(f"{k} = excluded.{k}" for k in data.keys())

    cur = db.execute(
        f"""INSERT INTO produkt_etap_limity ({col_clause})
               VALUES ({placeholders})
               ON CONFLICT(produkt, etap_id, parametr_id)
               DO UPDATE SET {set_clause}""",
        vals,
    )
    return cur.lastrowid


def get_produkt_etap_limity(
    db: sqlite3.Connection, produkt: str, etap_id: int
) -> list[dict]:
    """Return product-level limit overrides, JOINed with parametry_analityczne."""
    rows = db.execute(
        """
        SELECT
            pel.id, pel.produkt, pel.etap_id, pel.parametr_id,
            pel.min_limit, pel.max_limit, pel.nawazka_g, pel.precision, pel.spec_value,
            pa.kod, pa.label
        FROM produkt_etap_limity pel
        JOIN parametry_analityczne pa ON pa.id = pel.parametr_id
        WHERE pel.produkt = ? AND pel.etap_id = ?
        ORDER BY pel.id
        """,
        (produkt, etap_id),
    ).fetchall()
    return [dict(r) for r in rows]


def remove_produkt_etap_limit(
    db: sqlite3.Connection, produkt: str, etap_id: int, parametr_id: int
) -> None:
    db.execute(
        "DELETE FROM produkt_etap_limity WHERE produkt = ? AND etap_id = ? AND parametr_id = ?",
        (produkt, etap_id, parametr_id),
    )


# ---------------------------------------------------------------------------
# Task 4: ebr_etap_sesja — analysis sessions/rounds
# ---------------------------------------------------------------------------

def create_sesja(
    db: sqlite3.Connection,
    ebr_id: int,
    etap_id: int,
    runda: int = 1,
    laborant: str | None = None,
) -> int:
    """Insert a new analysis session. Returns new id.

    Snapshots `korekta_cele` for this (produkt, etap) into `cele_json` so the
    ML export can later reconstruct the targets the operator was aiming at —
    globals may drift over time as formulas get retuned.
    """
    import json as _json
    now = app_now_iso()

    cele_json = None
    try:
        produkt_row = db.execute(
            """SELECT m.produkt FROM ebr_batches e
               JOIN mbr_templates m ON m.mbr_id = e.mbr_id
               WHERE e.ebr_id = ?""",
            (ebr_id,),
        ).fetchone()
        if produkt_row:
            produkt = produkt_row["produkt"]
            cele_rows = db.execute(
                "SELECT kod, wartosc FROM korekta_cele "
                "WHERE produkt=? AND (etap_id=? OR etap_id IS NULL)",
                (produkt, etap_id),
            ).fetchall()
            if cele_rows:
                cele_json = _json.dumps(
                    {r["kod"]: r["wartosc"] for r in cele_rows},
                    ensure_ascii=False,
                )
    except Exception:
        cele_json = None

    cur = db.execute(
        """INSERT INTO ebr_etap_sesja (ebr_id, etap_id, runda, laborant, dt_start, cele_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (ebr_id, etap_id, runda, laborant, now, cele_json),
    )
    return cur.lastrowid


def create_round_with_inheritance(
    db: sqlite3.Connection,
    ebr_id: int,
    etap_id: int,
    prev_sesja_id: int,
    laborant: str | None = None,
) -> int:
    """Create next round, copying OK / no-limit measurements from previous session.

    Measurements with w_limicie = 0 (out of limit) are NOT copied.
    Copied rows get odziedziczony = 1, is_manual = 1, dt_wpisu = now.
    """
    # 1. Determine next runda
    prev = db.execute(
        "SELECT runda FROM ebr_etap_sesja WHERE id = ?", (prev_sesja_id,)
    ).fetchone()
    if prev is None:
        raise ValueError(f"Previous session {prev_sesja_id} not found")
    next_runda = prev["runda"] + 1

    # 2. Create new session
    new_sesja_id = create_sesja(db, ebr_id, etap_id, runda=next_runda, laborant=laborant)

    # 3. Copy measurements where w_limicie = 1 (OK) or w_limicie IS NULL (no limit)
    now = app_now_iso()
    db.execute(
        """INSERT INTO ebr_pomiar
               (sesja_id, parametr_id, wartosc, min_limit, max_limit,
                w_limicie, is_manual, dt_wpisu, wpisal, odziedziczony)
           SELECT ?, parametr_id, wartosc, min_limit, max_limit,
                  w_limicie, 1, ?, wpisal, 1
           FROM ebr_pomiar
           WHERE sesja_id = ?
             AND (w_limicie = 1 OR w_limicie IS NULL)""",
        (new_sesja_id, now, prev_sesja_id),
    )

    db.commit()
    return new_sesja_id


def get_sesja(db: sqlite3.Connection, sesja_id: int) -> dict | None:
    row = db.execute(
        "SELECT * FROM ebr_etap_sesja WHERE id = ?", (sesja_id,)
    ).fetchone()
    return dict(row) if row else None


def list_sesje(
    db: sqlite3.Connection,
    ebr_id: int,
    etap_id: int | None = None,
) -> list[dict]:
    """Return sessions for an EBR, ordered by etap_id, runda. Optionally filter by etap_id."""
    if etap_id is not None:
        rows = db.execute(
            """SELECT * FROM ebr_etap_sesja
               WHERE ebr_id = ? AND etap_id = ?
               ORDER BY etap_id, runda""",
            (ebr_id, etap_id),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT * FROM ebr_etap_sesja
               WHERE ebr_id = ?
               ORDER BY etap_id, runda""",
            (ebr_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def close_sesja(db: sqlite3.Connection, sesja_id: int, decyzja: str,
                komentarz: str = None) -> None:
    """Close (or reopen) a session.

    decyzja:
      'reopen_etap'   => status='w_trakcie' (operator re-opens the stage)
      Any other code   => status='zamkniety', komentarz stored in komentarz_decyzji
        ('zamknij_etap', 'przejscie', 'new_round', 'release_comment',
         'close_note', 'skip_to_next')
    """
    now = app_now_iso()
    if decyzja == "reopen_etap":
        db.execute(
            """UPDATE ebr_etap_sesja
               SET status = 'w_trakcie', decyzja = ?, dt_end = ?,
                   komentarz = COALESCE(?, komentarz)
               WHERE id = ?""",
            (decyzja, now, komentarz, sesja_id),
        )
    else:
        db.execute(
            """UPDATE ebr_etap_sesja
               SET status = 'zamkniety', decyzja = ?, dt_end = ?,
                   komentarz_decyzji = ?
               WHERE id = ?""",
            (decyzja, now, komentarz, sesja_id),
        )


def init_pipeline_sesje(
    db: sqlite3.Connection,
    ebr_id: int,
    produkt: str,
    laborant: str | None = None,
) -> int | None:
    """Create a session for the first pipeline stage of the product. Returns sesja_id or None."""
    pipeline = get_produkt_pipeline(db, produkt)
    if not pipeline:
        return None
    first_etap_id = pipeline[0]["etap_id"]
    return create_sesja(db, ebr_id, first_etap_id, runda=1, laborant=laborant)


# ---------------------------------------------------------------------------
# Task 4: ebr_pomiar — measurements
# ---------------------------------------------------------------------------

def _compute_w_limicie(
    wartosc: float | None,
    min_limit: float | None,
    max_limit: float | None,
) -> int | None:
    """Return 1 if in range, 0 if out, None if no limits or no value."""
    if wartosc is None:
        return None
    if min_limit is None and max_limit is None:
        return None
    if min_limit is not None and wartosc < min_limit:
        return 0
    if max_limit is not None and wartosc > max_limit:
        return 0
    return 1


def save_pomiar(
    db: sqlite3.Connection,
    sesja_id: int,
    parametr_id: int,
    wartosc: float | None,
    min_limit: float | None,
    max_limit: float | None,
    wpisal: str,
    is_manual: int = 1,
    odziedziczony: int = 0,
) -> int:
    """Upsert a measurement for (sesja_id, parametr_id). Returns row id."""
    now = app_now_iso()
    w_limicie = _compute_w_limicie(wartosc, min_limit, max_limit)
    cur = db.execute(
        """INSERT INTO ebr_pomiar
               (sesja_id, parametr_id, wartosc, min_limit, max_limit,
                w_limicie, is_manual, odziedziczony, dt_wpisu, wpisal)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(sesja_id, parametr_id) DO UPDATE SET
               wartosc       = excluded.wartosc,
               min_limit     = excluded.min_limit,
               max_limit     = excluded.max_limit,
               w_limicie     = excluded.w_limicie,
               is_manual     = excluded.is_manual,
               odziedziczony = excluded.odziedziczony,
               dt_wpisu      = excluded.dt_wpisu,
               wpisal        = excluded.wpisal""",
        (sesja_id, parametr_id, wartosc, min_limit, max_limit,
         w_limicie, is_manual, odziedziczony, now, wpisal),
    )
    _s = db.execute("SELECT ebr_id, status FROM ebr_etap_sesja WHERE id=?", (sesja_id,)).fetchone()
    if _s and _s["status"] == "zamkniety":
        _audit.log_event(
            _audit.EVENT_EBR_WYNIK_UPDATED,
            entity_type="ebr",
            entity_id=_s["ebr_id"],
            payload={"reedit": 1, "sesja_id": sesja_id,
                     "parametr_id": parametr_id, "wartosc": wartosc,
                     "source": "pipeline.save_pomiar"},
            db=db,
        )
    return cur.lastrowid


def get_pomiary(db: sqlite3.Connection, sesja_id: int) -> list[dict]:
    """Return measurements for a session, JOINed with parametry_analityczne. ORDER BY id."""
    rows = db.execute(
        """
        SELECT
            ep.id, ep.sesja_id, ep.parametr_id,
            ep.wartosc, ep.min_limit, ep.max_limit, ep.w_limicie,
            ep.is_manual, ep.odziedziczony, ep.dt_wpisu, ep.wpisal,
            pa.kod, pa.label, pa.typ, pa.skrot
        FROM ebr_pomiar ep
        JOIN parametry_analityczne pa ON pa.id = ep.parametr_id
        WHERE ep.sesja_id = ?
        ORDER BY ep.id
        """,
        (sesja_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Task 4: gate evaluation
# ---------------------------------------------------------------------------

_GATE_OPERATORS = {
    "<": lambda v, w, wmax: v < w,
    "<=": lambda v, w, wmax: v <= w,
    ">": lambda v, w, wmax: v > w,
    ">=": lambda v, w, wmax: v >= w,
    "=": lambda v, w, wmax: v == w,
    "between": lambda v, w, wmax: (wmax is not None) and (w <= v <= wmax),
    "w_limicie": lambda v, w, wmax: True,  # checked via pomiar.w_limicie below
}


def evaluate_gate(
    db: sqlite3.Connection,
    etap_id: int,
    sesja_id: int,
) -> dict:
    """Evaluate gate conditions for a stage against measurements in a session.

    Returns {"passed": bool, "failures": list[dict]}.
    Each failure has keys: kod, reason, warunek (dict with operator/wartosc/wartosc_max).
    """
    warunki = list_etap_warunki(db, etap_id)
    if not warunki:
        return {"passed": True, "failures": []}

    # Build pomiar lookup: parametr_id -> wartosc
    pomiary = {p["parametr_id"]: p for p in get_pomiary(db, sesja_id)}

    failures = []
    for w in warunki:
        pid = w["parametr_id"]
        if pid not in pomiary:
            failures.append({
                "kod": w["kod"],
                "reason": "brak_pomiaru",
                "warunek": {
                    "operator": w["operator"],
                    "wartosc": w["wartosc"],
                    "wartosc_max": w["wartosc_max"],
                    "opis_warunku": w["opis_warunku"],
                },
            })
            continue

        wartosc = pomiary[pid]["wartosc"]
        if wartosc is None:
            failures.append({
                "kod": w["kod"],
                "reason": "brak_wartosci",
                "warunek": {
                    "operator": w["operator"],
                    "wartosc": w["wartosc"],
                    "wartosc_max": w["wartosc_max"],
                    "opis_warunku": w["opis_warunku"],
                },
            })
            continue

        # "w_limicie" operator: use the pre-computed w_limicie flag from pomiar
        # (already evaluated against product-specific limits during save_pomiar)
        if w["operator"] == "w_limicie":
            ok = pomiary[pid].get("w_limicie") in (1, None)  # NULL = no limits = pass
        else:
            op_fn = _GATE_OPERATORS.get(w["operator"])
            ok = op_fn(wartosc, w["wartosc"], w["wartosc_max"]) if op_fn else True
        if not ok:
            failures.append({
                "kod": w["kod"],
                "reason": f"warunek_niespelniony: {wartosc} {w['operator']} {w['wartosc']}",
                "warunek": {
                    "operator": w["operator"],
                    "wartosc": w["wartosc"],
                    "wartosc_max": w["wartosc_max"],
                    "opis_warunku": w["opis_warunku"],
                },
            })

    return {"passed": len(failures) == 0, "failures": failures}


# ---------------------------------------------------------------------------
# Task 4: ebr_korekta_v2 — corrections
# ---------------------------------------------------------------------------

def create_ebr_korekta(
    db: sqlite3.Connection,
    sesja_id: int,
    korekta_typ_id: int,
    ilosc: float | None,
    zalecil: str | None,
    ilosc_wyliczona: float | None = None,
) -> int:
    """Insert a correction recommendation. Returns new id."""
    now = app_now_iso()
    cur = db.execute(
        """INSERT INTO ebr_korekta_v2
               (sesja_id, korekta_typ_id, ilosc, ilosc_wyliczona, zalecil, dt_zalecenia)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (sesja_id, korekta_typ_id, ilosc, ilosc_wyliczona, zalecil, now),
    )
    return cur.lastrowid


def upsert_ebr_korekta(
    db: sqlite3.Connection,
    sesja_id: int,
    korekta_typ_id: int,
    ilosc: float | None,
    ilosc_wyliczona: float | None,
    zalecil: str | None,
) -> int:
    """Insert-or-update a correction value for (sesja_id, korekta_typ_id).

    Used by the per-field auto-save flow: each blur-triggered save in the
    correction panel calls this. Idempotent for the same pair — second call
    updates the existing row rather than inserting a duplicate.

    ilosc = None is an explicit "clear manual override" signal (formula
    suggestion can show again in the UI). ilosc_wyliczona is always written
    so we retain a record of what the formula suggested at each save.
    """
    now = app_now_iso()
    existing = db.execute(
        "SELECT id FROM ebr_korekta_v2 "
        "WHERE sesja_id=? AND korekta_typ_id=? "
        "ORDER BY id DESC LIMIT 1",
        (sesja_id, korekta_typ_id),
    ).fetchone()
    if existing:
        db.execute(
            "UPDATE ebr_korekta_v2 "
            "SET ilosc=?, ilosc_wyliczona=?, zalecil=?, dt_zalecenia=? "
            "WHERE id=?",
            (ilosc, ilosc_wyliczona, zalecil, now, existing["id"]),
        )
        result_id = existing["id"]
    else:
        cur = db.execute(
            """INSERT INTO ebr_korekta_v2
                   (sesja_id, korekta_typ_id, ilosc, ilosc_wyliczona, zalecil, dt_zalecenia)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (sesja_id, korekta_typ_id, ilosc, ilosc_wyliczona, zalecil, now),
        )
        result_id = cur.lastrowid
    _s = db.execute("SELECT ebr_id, status FROM ebr_etap_sesja WHERE id=?", (sesja_id,)).fetchone()
    if _s and _s["status"] == "zamkniety":
        _audit.log_event(
            _audit.EVENT_EBR_WYNIK_UPDATED,
            entity_type="ebr",
            entity_id=_s["ebr_id"],
            payload={"reedit": 1, "sesja_id": sesja_id,
                     "korekta_typ_id": korekta_typ_id, "ilosc": ilosc,
                     "source": "pipeline.upsert_ebr_korekta"},
            db=db,
        )
    return result_id


def list_ebr_korekty(db: sqlite3.Connection, sesja_id: int) -> list[dict]:
    """Return corrections for a session, JOINed with etap_korekty_katalog."""
    rows = db.execute(
        """
        SELECT
            k.id, k.sesja_id, k.korekta_typ_id, k.ilosc, k.zalecil,
            k.wykonawca_info, k.dt_zalecenia, k.dt_wykonania, k.status,
            ek.substancja, ek.jednostka, ek.wykonawca
        FROM ebr_korekta_v2 k
        JOIN etap_korekty_katalog ek ON ek.id = k.korekta_typ_id
        WHERE k.sesja_id = ?
        ORDER BY k.id
        """,
        (sesja_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def update_ebr_korekta_status(
    db: sqlite3.Connection,
    korekta_id: int,
    status: str,
    wykonawca_info: str | None = None,
) -> None:
    """Update correction status and optionally record executor info. Sets dt_wykonania=now."""
    now = app_now_iso()
    db.execute(
        """UPDATE ebr_korekta_v2
           SET status = ?, wykonawca_info = ?, dt_wykonania = ?
           WHERE id = ?""",
        (status, wykonawca_info, now, korekta_id),
    )


# ---------------------------------------------------------------------------
# Task 5: ebr_korekta_zlecenie — multi-substance correction orders
# ---------------------------------------------------------------------------

def create_zlecenie_korekty(
    db: sqlite3.Connection,
    sesja_id: int,
    items: list[dict],
    zalecil: str,
    komentarz: str | None = None,
) -> int:
    cur = db.execute(
        "INSERT INTO ebr_korekta_zlecenie (sesja_id, zalecil, dt_zalecenia, komentarz) VALUES (?,?,datetime('now'),?)",
        (sesja_id, zalecil, komentarz),
    )
    zlecenie_id = cur.lastrowid
    for item in items:
        db.execute(
            """INSERT INTO ebr_korekta_v2
               (sesja_id, korekta_typ_id, ilosc, ilosc_wyliczona, zlecenie_id, zalecil, dt_zalecenia, status)
               VALUES (?,?,?,?,?,?, datetime('now'), 'zalecona')""",
            (sesja_id, item["korekta_typ_id"], item["ilosc"],
             item.get("ilosc_wyliczona"), zlecenie_id, zalecil),
        )
    return zlecenie_id


def get_zlecenie(db: sqlite3.Connection, zlecenie_id: int) -> dict | None:
    row = db.execute(
        "SELECT * FROM ebr_korekta_zlecenie WHERE id=?", (zlecenie_id,)
    ).fetchone()
    if not row:
        return None
    items = db.execute(
        """SELECT kv.*, ek.substancja, ek.jednostka
           FROM ebr_korekta_v2 kv
           JOIN etap_korekty_katalog ek ON ek.id = kv.korekta_typ_id
           WHERE kv.zlecenie_id=?""",
        (zlecenie_id,),
    ).fetchall()
    return {**dict(row), "items": [dict(i) for i in items]}


def wykonaj_zlecenie(db: sqlite3.Connection, zlecenie_id: int) -> int:
    zlecenie = db.execute(
        "SELECT * FROM ebr_korekta_zlecenie WHERE id=?", (zlecenie_id,)
    ).fetchone()
    db.execute(
        "UPDATE ebr_korekta_zlecenie SET status='wykonana', dt_wykonania=datetime('now') WHERE id=?",
        (zlecenie_id,),
    )
    db.execute(
        "UPDATE ebr_korekta_v2 SET status='wykonana', dt_wykonania=datetime('now') WHERE zlecenie_id=?",
        (zlecenie_id,),
    )
    sesja = db.execute(
        "SELECT * FROM ebr_etap_sesja WHERE id=?", (zlecenie["sesja_id"],)
    ).fetchone()
    new_runda = sesja["runda"] + 1
    cur = db.execute(
        """INSERT INTO ebr_etap_sesja (ebr_id, etap_id, runda, status, dt_start, laborant)
           VALUES (?,?,?,'w_trakcie', datetime('now'),?)""",
        (sesja["ebr_id"], sesja["etap_id"], new_runda, sesja["laborant"]),
    )
    return cur.lastrowid


def list_zlecenia_for_sesja(db: sqlite3.Connection, sesja_id: int) -> list[dict]:
    rows = db.execute(
        "SELECT * FROM ebr_korekta_zlecenie WHERE sesja_id=? ORDER BY dt_zalecenia",
        (sesja_id,),
    ).fetchall()
    result = []
    for row in rows:
        items = db.execute(
            """SELECT kv.*, ek.substancja, ek.jednostka
               FROM ebr_korekta_v2 kv
               JOIN etap_korekty_katalog ek ON ek.id = kv.korekta_typ_id
               WHERE kv.zlecenie_id=?""",
            (row["id"],),
        ).fetchall()
        result.append({**dict(row), "items": [dict(i) for i in items]})
    return result


# ---------------------------------------------------------------------------
# Task 6: formula hint computation
# ---------------------------------------------------------------------------

def _resolve_ovr(ovr, cat):
    """Resolve product override vs catalog value for a limit field.

    Convention: empty string '' in override means 'explicitly no limit'
    (one-sided range). NULL in override means 'no override, use catalog'.
    """
    if ovr is None:
        return cat
    if ovr == '':
        return None
    return ovr


def resolve_limity(db: sqlite3.Connection, produkt: str, etap_id: int) -> list[dict]:
    """Merge catalog limits with product-level overrides.

    For each parameter in the stage catalog (etap_parametry), overlay
    produkt_etap_limity for (produkt, etap_id, parametr_id).
    Product-specific value wins when it is non-NULL; catalog value is fallback.

    Returns list[dict] ordered by ep.kolejnosc.
    """
    rows = db.execute(
        """
        SELECT
            ep.id AS ep_id, ep.parametr_id,
            COALESCE(pel.kolejnosc, ep.kolejnosc) AS kolejnosc,
            ep.min_limit  AS cat_min, ep.max_limit  AS cat_max,
            ep.nawazka_g  AS cat_nawazka, ep.precision AS cat_precision,
            ep.spec_value AS cat_spec_value,
            ep.wymagany, ep.grupa AS cat_grupa,
            ep.formula  AS cat_formula,
            ep.sa_bias  AS cat_sa_bias,
            ep.krok,
            pa.kod, pa.label, pa.typ, pa.skrot, pa.jednostka,
            pa.precision AS global_precision,
            pel.min_limit  AS ovr_min, pel.max_limit  AS ovr_max,
            pel.nawazka_g  AS ovr_nawazka, pel.precision AS ovr_precision,
            pel.spec_value AS ovr_spec_value,
            pel.formula    AS ovr_formula,
            pel.sa_bias    AS ovr_sa_bias,
            pel.grupa      AS ovr_grupa
        FROM etap_parametry ep
        JOIN parametry_analityczne pa ON pa.id = ep.parametr_id
        LEFT JOIN produkt_etap_limity pel
               ON pel.produkt = ?
              AND pel.etap_id = ep.etap_id
              AND pel.parametr_id = ep.parametr_id
        WHERE ep.etap_id = ?
        ORDER BY COALESCE(pel.kolejnosc, ep.kolejnosc), pa.kod
        """,
        (produkt, etap_id),
    ).fetchall()

    result = []
    for r in rows:
        result.append({
            "ep_id": r["ep_id"],
            "pe_id": r["ep_id"],
            "parametr_id": r["parametr_id"],
            "kolejnosc": r["kolejnosc"],
            "kod": r["kod"],
            "label": r["label"],
            "typ": r["typ"],
            "skrot": r["skrot"],
            "jednostka": r["jednostka"],
            "min_limit": _resolve_ovr(r["ovr_min"], r["cat_min"]),
            "max_limit": _resolve_ovr(r["ovr_max"], r["cat_max"]),
            "nawazka_g": r["ovr_nawazka"] if r["ovr_nawazka"] is not None else r["cat_nawazka"],
            "precision": (
                r["ovr_precision"] if r["ovr_precision"] is not None
                else r["cat_precision"] if r["cat_precision"] is not None
                else r["global_precision"] if r["global_precision"] is not None
                else 2
            ),
            "spec_value": r["ovr_spec_value"] if r["ovr_spec_value"] is not None else r["cat_spec_value"],
            "wymagany": r["wymagany"],
            "grupa": r["ovr_grupa"] if r["ovr_grupa"] is not None else r["cat_grupa"],
            # Per-produkt formula/sa_bias override wins; catalog value is fallback
            "formula": r["ovr_formula"] if r["ovr_formula"] is not None else r["cat_formula"],
            "sa_bias": r["ovr_sa_bias"] if r["ovr_sa_bias"] is not None else r["cat_sa_bias"],
            "krok": r["krok"],
        })
    return result


# ---------------------------------------------------------------------------
# Task 1: resolve_formula_zmienne — auto-resolve formula variables from DB
# ---------------------------------------------------------------------------

VARIABLE_LABELS = {
    "wielkosc_szarzy_kg": "Masa szarży",
    "redukcja": "Redukcja",
    "Meff": "Masa efektywna",
}


def _js_ternary_to_python(expr: str) -> str:
    """Convert a simple JS-style ternary (cond ? a : b) to Python (a if cond else b).

    Only handles single-level ternaries with no nested ?/: in the branches.
    """
    m = _re.match(r"^(.+?)\s*\?\s*(.+?)\s*:\s*(.+)$", expr.strip())
    if m:
        cond, then_, else_ = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        return f"({then_}) if ({cond}) else ({else_})"
    return expr


def _resolve_single_variable(db, var_name, var_ref, ebr_id, etap_id, sesja_id, produkt):
    """Resolve a single formula variable reference. Returns (value, label)."""
    # Handle pomiar:{kod}
    if var_ref.startswith("pomiar:"):
        kod = var_ref.split(":", 1)[1]
        pa = db.execute(
            "SELECT id, label FROM parametry_analityczne WHERE kod=?", (kod,)
        ).fetchone()
        if not pa:
            return None, f"Pomiar {kod}"
        # Try current session
        row = db.execute(
            "SELECT wartosc FROM ebr_pomiar WHERE sesja_id=? AND parametr_id=?",
            (sesja_id, pa["id"]),
        ).fetchone()
        if row and row["wartosc"] is not None:
            return row["wartosc"], f"Pomiar {pa['label']}"
        # Walk backwards through pipeline stages
        pipeline = db.execute(
            "SELECT etap_id FROM produkt_pipeline WHERE produkt=? ORDER BY kolejnosc DESC",
            (produkt,),
        ).fetchall()
        for step in pipeline:
            if step["etap_id"] == etap_id:
                continue
            sesje = db.execute(
                "SELECT id FROM ebr_etap_sesja WHERE ebr_id=? AND etap_id=? ORDER BY runda DESC LIMIT 1",
                (ebr_id, step["etap_id"]),
            ).fetchone()
            if not sesje:
                continue
            row = db.execute(
                "SELECT wartosc FROM ebr_pomiar WHERE sesja_id=? AND parametr_id=?",
                (sesje["id"], pa["id"]),
            ).fetchone()
            if row and row["wartosc"] is not None:
                return row["wartosc"], f"Pomiar {pa['label']}"
        return None, f"Pomiar {pa['label']}"

    # Handle target:{kod}
    if var_ref.startswith("target:"):
        kod = var_ref.split(":", 1)[1]
        pa = db.execute(
            "SELECT id, label FROM parametry_analityczne WHERE kod=?", (kod,)
        ).fetchone()
        if not pa:
            return None, f"Spec {kod}"
        limity = resolve_limity(db, produkt, etap_id)
        for lim in limity:
            if lim["parametr_id"] == pa["id"]:
                return lim.get("spec_value"), f"Spec {pa['label']}"
        return None, f"Spec {pa['label']}"

    # Handle wielkosc_szarzy_kg
    if var_ref == "wielkosc_szarzy_kg":
        row = db.execute(
            "SELECT wielkosc_szarzy_kg FROM ebr_batches WHERE ebr_id=?", (ebr_id,)
        ).fetchone()
        return (row["wielkosc_szarzy_kg"] if row else None), "Masa szarży"

    # Expression or numeric — return as-is for later eval
    return var_ref, VARIABLE_LABELS.get(var_name, var_name)


def resolve_formula_zmienne(db, korekta_typ_id, etap_id, sesja_id, ebr_id, redukcja_override=None):
    """Auto-resolve formula variables from DB data.

    Returns dict with keys: ok, wynik, zmienne, labels.
    """
    row = db.execute(
        "SELECT formula_ilosc, formula_zmienne, etap_id AS kor_etap_id FROM etap_korekty_katalog WHERE id=?",
        (korekta_typ_id,),
    ).fetchone()
    if not row or not row["formula_ilosc"]:
        return {"ok": False, "wynik": None, "zmienne": {}, "labels": {}}

    ebr = db.execute(
        "SELECT m.produkt, e.wielkosc_szarzy_kg FROM ebr_batches e JOIN mbr_templates m ON m.mbr_id = e.mbr_id WHERE e.ebr_id = ?",
        (ebr_id,),
    ).fetchone()
    produkt = ebr["produkt"] if ebr else ""
    masa = ebr["wielkosc_szarzy_kg"] if ebr else None

    zmienne_def = _json.loads(row["formula_zmienne"]) if row["formula_zmienne"] else {}
    resolved = {}
    labels = {}

    resolved["wielkosc_szarzy_kg"] = masa
    labels["wielkosc_szarzy_kg"] = "Masa szarży"

    meff_expression = None
    for var_name, var_ref in zmienne_def.items():
        if var_name == "Meff":
            meff_expression = var_ref
            continue
        val, lbl = _resolve_single_variable(
            db, var_name, var_ref, ebr_id, etap_id, sesja_id, produkt
        )
        resolved[var_name] = val
        labels[var_name] = lbl

    # Meff with optional override
    if redukcja_override is not None and masa is not None:
        resolved["Meff"] = masa - redukcja_override
        resolved["redukcja"] = redukcja_override
    elif meff_expression and masa is not None:
        meff_expr = str(meff_expression).replace(
            "wielkosc_szarzy_kg", str(float(masa))
        )
        meff_expr = _js_ternary_to_python(meff_expr)
        try:
            meff_val = eval(meff_expr, {"__builtins__": {}})
            resolved["Meff"] = meff_val
            resolved["redukcja"] = masa - meff_val
        except Exception:
            resolved["Meff"] = None
            resolved["redukcja"] = None
    elif masa is not None:
        resolved["Meff"] = masa
        resolved["redukcja"] = 0

    labels["Meff"] = "Masa efektywna"
    labels["redukcja"] = "Redukcja"

    # Evaluate main formula
    formula = row["formula_ilosc"]
    for key, val in resolved.items():
        if val is not None and key != "wielkosc_szarzy_kg" and key != "redukcja":
            formula = formula.replace(f":{key}", str(float(val)))
    if masa is not None:
        formula = formula.replace("wielkosc_szarzy_kg", str(float(masa)))

    try:
        wynik = eval(formula, {"__builtins__": {}})
    except Exception:
        wynik = None

    return {"ok": True, "wynik": wynik, "zmienne": resolved, "labels": labels}


# ---------------------------------------------------------------------------
# Global Edit — patch parametry_etapy binding
# ---------------------------------------------------------------------------

def patch_parametry_etapy(
    db: sqlite3.Connection,
    pe_id: int,
    updates: dict,
    user_id: int | None = None,
) -> dict:
    """Update parameter limits via Global Edit.

    pe_id is an etap_parametry.id (from resolve_limity).  We resolve it
    to the matching produkt_etap_limity row (or parametry_etapy fallback
    for non-pipeline products) and upsert the new values.

    Returns {"ok": True, "updated": [...]} on success,
    or {"ok": False, "error": "..."} on validation failure / not found.
    """
    allowed = {"min_limit", "max_limit", "target", "formula", "sa_bias", "nawazka_g", "precision"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return {"ok": False, "error": "no_valid_fields"}

    # "target" maps to "spec_value" in produkt_etap_limity
    if "target" in filtered:
        filtered["spec_value"] = filtered.pop("target")

    # Try etap_parametry first to get context
    ep = db.execute(
        "SELECT id, etap_id, parametr_id FROM etap_parametry WHERE id = ?",
        (pe_id,),
    ).fetchone()

    if not ep:
        # Fallback: try parametry_etapy (non-pipeline products)
        row = db.execute("SELECT id FROM parametry_etapy WHERE id = ?", (pe_id,)).fetchone()
        if not row:
            return {"ok": False, "error": "not_found"}
        # Remap spec_value back to target for parametry_etapy
        if "spec_value" in filtered:
            filtered["target"] = filtered.pop("spec_value")
        sets = ", ".join(f"{k} = ?" for k in filtered)
        vals = list(filtered.values())
        now = app_now_iso()
        sets += ", dt_modified = ?, modified_by = ?"
        vals.extend([now, user_id])
        vals.append(pe_id)
        db.execute(f"UPDATE parametry_etapy SET {sets} WHERE id = ?", vals)
        db.commit()
        return {"ok": True, "updated": list(filtered.keys())}

    # Pipeline path: upsert produkt_etap_limity
    # We need the produkt — get it from the route context (passed via request)
    # or from the first matching row
    from flask import request as _req
    produkt = (_req.get_json(silent=True) or {}).get("produkt")

    if not produkt:
        # Find from existing produkt_etap_limity row
        pel = db.execute(
            "SELECT produkt FROM produkt_etap_limity WHERE etap_id = ? AND parametr_id = ? LIMIT 1",
            (ep["etap_id"], ep["parametr_id"]),
        ).fetchone()
        if pel:
            produkt = pel["produkt"]

    if not produkt:
        return {"ok": False, "error": "no_produkt_context"}

    # Check if row exists
    existing = db.execute(
        "SELECT id FROM produkt_etap_limity WHERE produkt = ? AND etap_id = ? AND parametr_id = ?",
        (produkt, ep["etap_id"], ep["parametr_id"]),
    ).fetchone()

    pel_allowed = {"min_limit", "max_limit", "spec_value", "nawazka_g", "precision"}
    pel_filtered = {k: v for k, v in filtered.items() if k in pel_allowed}

    if existing:
        sets = ", ".join(f"{k} = ?" for k in pel_filtered)
        vals = list(pel_filtered.values()) + [existing["id"]]
        db.execute(f"UPDATE produkt_etap_limity SET {sets} WHERE id = ?", vals)
    else:
        pel_filtered["produkt"] = produkt
        pel_filtered["etap_id"] = ep["etap_id"]
        pel_filtered["parametr_id"] = ep["parametr_id"]
        cols = ", ".join(pel_filtered.keys())
        placeholders = ", ".join("?" for _ in pel_filtered)
        db.execute(
            f"INSERT INTO produkt_etap_limity ({cols}) VALUES ({placeholders})",
            list(pel_filtered.values()),
        )

    db.commit()
    return {"ok": True, "updated": list(filtered.keys())}
