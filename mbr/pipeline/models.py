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
