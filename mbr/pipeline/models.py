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

import sqlite3
from datetime import datetime


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
    "target", "wymagany", "grupa", "formula", "sa_bias", "krok",
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
            ep.target, ep.wymagany, ep.grupa, ep.formula, ep.sa_bias, ep.krok,
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

_PEL_ALLOWED_FIELDS = {"min_limit", "max_limit", "nawazka_g", "precision", "target"}


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
            pel.min_limit, pel.max_limit, pel.nawazka_g, pel.precision, pel.target,
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
    """Insert a new analysis session. Returns new id."""
    now = datetime.now().isoformat(timespec="seconds")
    cur = db.execute(
        """INSERT INTO ebr_etap_sesja (ebr_id, etap_id, runda, laborant, dt_start)
           VALUES (?, ?, ?, ?, ?)""",
        (ebr_id, etap_id, runda, laborant, now),
    )
    return cur.lastrowid


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
    """Close a session.

    decyzja:
      'przejscie'            => status='ok' (gate passed, move to next stage)
      'korekta'              => status='oczekuje_korekty' (needs correction + re-analysis)
      'korekta_i_przejscie'  => status='ok' (small correction, no re-analysis, note in komentarz)
    """
    now = datetime.now().isoformat(timespec="seconds")
    status = "ok" if decyzja in ("przejscie", "korekta_i_przejscie") else "oczekuje_korekty"
    db.execute(
        """UPDATE ebr_etap_sesja
           SET status = ?, decyzja = ?, dt_end = ?, komentarz = COALESCE(?, komentarz)
           WHERE id = ?""",
        (status, decyzja, now, komentarz, sesja_id),
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
) -> int:
    """Upsert a measurement for (sesja_id, parametr_id). Returns row id."""
    now = datetime.now().isoformat(timespec="seconds")
    w_limicie = _compute_w_limicie(wartosc, min_limit, max_limit)
    cur = db.execute(
        """INSERT INTO ebr_pomiar
               (sesja_id, parametr_id, wartosc, min_limit, max_limit,
                w_limicie, is_manual, dt_wpisu, wpisal)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(sesja_id, parametr_id) DO UPDATE SET
               wartosc    = excluded.wartosc,
               min_limit  = excluded.min_limit,
               max_limit  = excluded.max_limit,
               w_limicie  = excluded.w_limicie,
               is_manual  = excluded.is_manual,
               dt_wpisu   = excluded.dt_wpisu,
               wpisal     = excluded.wpisal""",
        (sesja_id, parametr_id, wartosc, min_limit, max_limit,
         w_limicie, is_manual, now, wpisal),
    )
    return cur.lastrowid


def get_pomiary(db: sqlite3.Connection, sesja_id: int) -> list[dict]:
    """Return measurements for a session, JOINed with parametry_analityczne. ORDER BY id."""
    rows = db.execute(
        """
        SELECT
            ep.id, ep.sesja_id, ep.parametr_id,
            ep.wartosc, ep.min_limit, ep.max_limit, ep.w_limicie,
            ep.is_manual, ep.dt_wpisu, ep.wpisal,
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
) -> int:
    """Insert a correction recommendation. Returns new id."""
    now = datetime.now().isoformat(timespec="seconds")
    cur = db.execute(
        """INSERT INTO ebr_korekta_v2
               (sesja_id, korekta_typ_id, ilosc, zalecil, dt_zalecenia)
           VALUES (?, ?, ?, ?, ?)""",
        (sesja_id, korekta_typ_id, ilosc, zalecil, now),
    )
    return cur.lastrowid


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
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        """UPDATE ebr_korekta_v2
           SET status = ?, wykonawca_info = ?, dt_wykonania = ?
           WHERE id = ?""",
        (status, wykonawca_info, now, korekta_id),
    )


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
            ep.id AS ep_id, ep.parametr_id, ep.kolejnosc,
            ep.min_limit  AS cat_min, ep.max_limit  AS cat_max,
            ep.nawazka_g  AS cat_nawazka, ep.precision AS cat_precision,
            ep.target     AS cat_target,
            ep.wymagany, ep.grupa, ep.formula, ep.sa_bias, ep.krok,
            pa.kod, pa.label, pa.typ, pa.skrot, pa.jednostka,
            pel.min_limit  AS ovr_min, pel.max_limit  AS ovr_max,
            pel.nawazka_g  AS ovr_nawazka, pel.precision AS ovr_precision,
            pel.target     AS ovr_target
        FROM etap_parametry ep
        JOIN parametry_analityczne pa ON pa.id = ep.parametr_id
        LEFT JOIN produkt_etap_limity pel
               ON pel.produkt = ?
              AND pel.etap_id = ep.etap_id
              AND pel.parametr_id = ep.parametr_id
        WHERE ep.etap_id = ?
        ORDER BY ep.kolejnosc
        """,
        (produkt, etap_id),
    ).fetchall()

    result = []
    for r in rows:
        result.append({
            "ep_id": r["ep_id"],
            "parametr_id": r["parametr_id"],
            "kolejnosc": r["kolejnosc"],
            "kod": r["kod"],
            "label": r["label"],
            "typ": r["typ"],
            "skrot": r["skrot"],
            "jednostka": r["jednostka"],
            "min_limit": r["ovr_min"] if r["ovr_min"] is not None else r["cat_min"],
            "max_limit": r["ovr_max"] if r["ovr_max"] is not None else r["cat_max"],
            "nawazka_g": r["ovr_nawazka"] if r["ovr_nawazka"] is not None else r["cat_nawazka"],
            "precision": r["ovr_precision"] if r["ovr_precision"] is not None else r["cat_precision"],
            "target": r["ovr_target"] if r["ovr_target"] is not None else r["cat_target"],
            "wymagany": r["wymagany"],
            "grupa": r["grupa"],
            "formula": r["formula"],
            "sa_bias": r["sa_bias"],
            "krok": r["krok"],
        })
    return result
