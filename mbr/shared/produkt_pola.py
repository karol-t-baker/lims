"""DAO for produkt_pola — declarative metadata fields per produkt / cert_variant.

See docs/superpowers/specs/2026-05-01-produkt-pola-uniwersalne-design.md

Pure-Python module — no Flask imports. Caller commits the transaction.
Audit events are emitted within the caller's transaction via
``mbr.shared.audit.log_event``. Actors are resolved from ``user_id``
through the ``workers`` table when possible (so tests without a Flask
request context still work); rola defaults to ``"system"`` when the
worker cannot be matched (e.g. ``user_id=None`` or unknown id).
"""

import json
import re
from datetime import datetime
from typing import Any

from mbr.shared import audit
from mbr.shared.timezone import app_now_iso

_KOD_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_VALID_SCOPES = {"produkt", "cert_variant"}
_VALID_TYP_DANYCH = {"text", "number", "date"}
_VALID_MIEJSCA = {"modal", "hero", "ukonczone", "cert"}
_VALID_TYPY_REJESTRACJI = {"szarza", "zbiornik", "platkowanie"}


def _validate_kod(kod: str) -> None:
    if not _KOD_RE.match(kod or ""):
        raise ValueError(
            f"kod must match {_KOD_RE.pattern}, got: {kod!r}"
        )


def _validate_payload(payload: dict, *, is_create: bool) -> None:
    """Validate a create/update payload. ``is_create`` toggles required fields."""
    if is_create:
        if payload.get("scope") not in _VALID_SCOPES:
            raise ValueError(f"scope must be one of {_VALID_SCOPES}")
        _validate_kod(payload.get("kod", ""))
        if not payload.get("label_pl"):
            raise ValueError("label_pl required")

    typ = payload.get("typ_danych")
    if typ is not None and typ not in _VALID_TYP_DANYCH:
        raise ValueError(f"typ_danych must be one of {_VALID_TYP_DANYCH}")

    miejsca = payload.get("miejsca")
    if miejsca is not None:
        if not isinstance(miejsca, list) or not set(miejsca).issubset(_VALID_MIEJSCA):
            raise ValueError(f"miejsca must be subset of {_VALID_MIEJSCA}")

    typy = payload.get("typy_rejestracji")
    if typy is not None and typy != []:
        if not isinstance(typy, list) or not set(typy).issubset(_VALID_TYPY_REJESTRACJI):
            raise ValueError(
                f"typy_rejestracji must be subset of {_VALID_TYPY_REJESTRACJI}"
            )

    # cert_variant requires text type and non-empty wartosc_stala when active.
    scope = payload.get("scope")
    if scope == "cert_variant":
        if (payload.get("typ_danych") or "text") != "text":
            raise ValueError("scope=cert_variant requires typ_danych='text'")
        is_active = payload.get("aktywne", 1)
        ws = payload.get("wartosc_stala")
        if is_active and (ws is None or ws == ""):
            raise ValueError(
                "scope=cert_variant with aktywne=1 requires non-empty wartosc_stala"
            )


def _resolve_actors(db, user_id: int | None) -> list:
    """Build an explicit actors list for ``audit.log_event``.

    DAOs are called both from Flask routes (where ``actors_from_request``
    would normally resolve actors from the session) and from tests / CLI
    scripts where no request context exists. To keep the DAO portable we
    look up the worker by ``user_id`` directly. If the worker can't be
    resolved we fall back to a ``system`` actor — never raising — so that
    audit emission cannot block the underlying write.
    """
    if user_id is None:
        return audit.actors_system()
    row = db.execute(
        "SELECT id, imie, nazwisko, nickname, inicjaly FROM workers WHERE id=?",
        (user_id,),
    ).fetchone()
    if row is None:
        return [{
            "worker_id": user_id,
            "actor_login": f"user_{user_id}",
            "actor_name": None,
            "actor_rola": "system",
        }]
    login = row["nickname"] or row["inicjaly"] or f"worker_{row['id']}"
    return [{
        "worker_id": row["id"],
        "actor_login": login,
        "actor_name": f"{row['imie']} {row['nazwisko']}",
        "actor_rola": "system",
    }]


def _now_iso() -> str:
    """Project-policy: Europe/Warsaw, naive ISO string. See mbr.shared.timezone."""
    return app_now_iso()


def create_pole(db, payload: dict, user_id: int) -> int:
    """Create a produkt_pola row. Validates payload, emits audit event.

    Returns the new row id. Caller is responsible for committing.
    """
    _validate_payload(payload, is_create=True)
    miejsca_json = json.dumps(payload.get("miejsca", []))
    typy = payload.get("typy_rejestracji")
    typy_json = json.dumps(typy) if typy else None
    now = _now_iso()
    cur = db.execute(
        """
        INSERT INTO produkt_pola
        (scope, scope_id, kod, label_pl, typ_danych, jednostka, wartosc_stala,
         obowiazkowe, miejsca, typy_rejestracji, kolejnosc, aktywne,
         created_at, created_by, updated_at, updated_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["scope"],
            payload["scope_id"],
            payload["kod"],
            payload["label_pl"],
            payload.get("typ_danych", "text"),
            payload.get("jednostka"),
            payload.get("wartosc_stala"),
            1 if payload.get("obowiazkowe") else 0,
            miejsca_json,
            typy_json,
            payload.get("kolejnosc", 0),
            1 if payload.get("aktywne", 1) else 0,
            now, user_id, now, user_id,
        ),
    )
    pole_id = cur.lastrowid

    actors = _resolve_actors(db, user_id)
    audit.log_event(
        audit.EVENT_PRODUKT_POLA_CREATED,
        entity_type="produkt_pola",
        entity_id=pole_id,
        entity_label=payload["kod"],
        payload={k: payload.get(k) for k in (
            "scope", "scope_id", "kod", "label_pl", "typ_danych",
            "wartosc_stala", "miejsca", "typy_rejestracji",
        )},
        actors=actors,
        db=db,
    )
    return pole_id


def update_pole(db, pole_id: int, patch: dict, user_id: int) -> None:
    """Update editable fields. ``kod``, ``scope``, ``scope_id`` are immutable."""
    if "kod" in patch:
        raise ValueError("kod is immutable after creation")
    if "scope" in patch or "scope_id" in patch:
        raise ValueError("scope/scope_id are immutable after creation")

    row = db.execute("SELECT * FROM produkt_pola WHERE id=?", (pole_id,)).fetchone()
    if row is None:
        raise ValueError(f"produkt_pola id={pole_id} not found")

    # Merge for validation: full picture must remain valid.
    merged: dict = {k: row[k] for k in row.keys()}
    merged["miejsca"] = json.loads(row["miejsca"] or "[]")
    merged["typy_rejestracji"] = (
        json.loads(row["typy_rejestracji"]) if row["typy_rejestracji"] else None
    )
    merged.update(patch)
    _validate_payload(merged, is_create=False)

    sets: list[str] = []
    vals: list[Any] = []
    for k in (
        "label_pl", "typ_danych", "jednostka", "wartosc_stala",
        "obowiazkowe", "kolejnosc", "aktywne",
    ):
        if k in patch:
            sets.append(f"{k}=?")
            v = patch[k]
            if k in ("obowiazkowe", "aktywne"):
                v = 1 if v else 0
            vals.append(v)
    if "miejsca" in patch:
        sets.append("miejsca=?")
        vals.append(json.dumps(patch["miejsca"]))
    if "typy_rejestracji" in patch:
        sets.append("typy_rejestracji=?")
        vals.append(
            json.dumps(patch["typy_rejestracji"])
            if patch["typy_rejestracji"] else None
        )

    if not sets:
        # Nothing actually changed → no UPDATE, no audit event.
        return

    sets.extend(["updated_at=?", "updated_by=?"])
    vals.extend([_now_iso(), user_id])
    vals.append(pole_id)
    db.execute(
        f"UPDATE produkt_pola SET {', '.join(sets)} WHERE id=?",
        vals,
    )

    actors = _resolve_actors(db, user_id)
    diff = []
    row_keys = set(row.keys())
    for k, v in patch.items():
        if k in row_keys:
            diff.append({"pole": k, "stara": row[k], "nowa": v})
    audit.log_event(
        audit.EVENT_PRODUKT_POLA_UPDATED,
        entity_type="produkt_pola",
        entity_id=pole_id,
        entity_label=row["kod"],
        diff=diff,
        actors=actors,
        db=db,
    )


def deactivate_pole(db, pole_id: int, user_id: int) -> None:
    """Soft-delete (``aktywne=0``). Historical values preserved."""
    row = db.execute(
        "SELECT kod FROM produkt_pola WHERE id=?", (pole_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"produkt_pola id={pole_id} not found")

    db.execute(
        "UPDATE produkt_pola SET aktywne=0, updated_at=?, updated_by=? WHERE id=?",
        (_now_iso(), user_id, pole_id),
    )

    actors = _resolve_actors(db, user_id)
    audit.log_event(
        audit.EVENT_PRODUKT_POLA_DEACTIVATED,
        entity_type="produkt_pola",
        entity_id=pole_id,
        entity_label=row["kod"],
        actors=actors,
        db=db,
    )


# ---------------------------------------------------------------------------
# Wartości (ebr_pola_wartosci) — set / get
# ---------------------------------------------------------------------------


def _coerce_value(typ_danych: str, raw) -> str | None:
    """Validate & normalize a value according to ``typ_danych``.

    NULL or empty-string input → ``None`` (clears the field).

    - ``text``: returned as-is.
    - ``number``: accepts dot or comma decimal separator, validates via
      ``float()``, stores in Polish convention with comma.
    - ``date``: accepts ``YYYY-MM-DD``, ``DD-MM-YYYY``, ``D.M.YYYY`` and
      normalizes to ISO ``YYYY-MM-DD``.
    """
    if raw is None or raw == "":
        return None
    if typ_danych == "text":
        return raw
    if typ_danych == "number":
        normalized = raw.replace(",", ".")
        try:
            float(normalized)
        except ValueError:
            raise ValueError(f"invalid number: {raw!r}")
        # Storage convention: Polish comma
        return normalized.replace(".", ",")
    if typ_danych == "date":
        # Accept ISO YYYY-MM-DD or DD-MM-YYYY / D.M.YYYY → normalize to ISO.
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
            try:
                d = datetime.strptime(raw, fmt)
                return d.strftime("%Y-%m-%d")
            except ValueError:
                continue
        raise ValueError(f"invalid date (use YYYY-MM-DD): {raw!r}")
    raise ValueError(f"unknown typ_danych: {typ_danych}")


def set_wartosc(db, ebr_id: int, pole_id: int, wartosc, user_id: int) -> None:
    """Upsert value for ``(ebr_id, pole_id)``.

    Validates the input against the pole's ``typ_danych`` and emits an
    audit event with before/after diff. Caller is responsible for
    committing the transaction.
    """
    pole = db.execute(
        "SELECT kod, typ_danych FROM produkt_pola WHERE id=?", (pole_id,)
    ).fetchone()
    if pole is None:
        raise ValueError(f"pole id={pole_id} not found")
    coerced = _coerce_value(pole["typ_danych"], wartosc)
    existing = db.execute(
        "SELECT wartosc FROM ebr_pola_wartosci WHERE ebr_id=? AND pole_id=?",
        (ebr_id, pole_id),
    ).fetchone()
    before = existing["wartosc"] if existing else None
    now = _now_iso()
    if existing is None:
        db.execute(
            """
            INSERT INTO ebr_pola_wartosci
            (ebr_id, pole_id, wartosc, created_at, created_by, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (ebr_id, pole_id, coerced, now, user_id, now, user_id),
        )
    else:
        db.execute(
            """
            UPDATE ebr_pola_wartosci SET wartosc=?, updated_at=?, updated_by=?
            WHERE ebr_id=? AND pole_id=?
            """,
            (coerced, now, user_id, ebr_id, pole_id),
        )

    actors = _resolve_actors(db, user_id)
    audit.log_event(
        audit.EVENT_EBR_POLA_VALUE_SET,
        entity_type="ebr_pola",
        entity_id=ebr_id,
        diff=[{"pole": pole["kod"], "stara": before, "nowa": coerced}],
        context={"ebr_id": ebr_id, "pole_id": pole_id, "kod": pole["kod"]},
        actors=actors,
        db=db,
    )


def _row_to_dict(row) -> dict:
    d = {k: row[k] for k in row.keys()}
    d["miejsca"] = json.loads(d.get("miejsca") or "[]")
    if d.get("typy_rejestracji"):
        d["typy_rejestracji"] = json.loads(d["typy_rejestracji"])
    else:
        d["typy_rejestracji"] = None
    d["obowiazkowe"] = bool(d.get("obowiazkowe"))
    d["aktywne"] = bool(d.get("aktywne"))
    return d


def list_pola_for_produkt(db, produkt_id: int, *,
                           miejsce: str | None = None,
                           typ_rejestracji: str | None = None,
                           only_active: bool = True) -> list[dict]:
    """List pola scope='produkt'. Filtruje po miejscu / typie rejestracji."""
    sql = "SELECT * FROM produkt_pola WHERE scope='produkt' AND scope_id=?"
    params: list = [produkt_id]
    if only_active:
        sql += " AND aktywne=1"
    sql += " ORDER BY kolejnosc, id"
    rows = [_row_to_dict(r) for r in db.execute(sql, params).fetchall()]
    if miejsce is not None:
        rows = [r for r in rows if miejsce in r["miejsca"]]
    if typ_rejestracji is not None:
        rows = [r for r in rows
                if r["typy_rejestracji"] is None or typ_rejestracji in r["typy_rejestracji"]]
    return rows


def list_pola_for_cert_variant(db, variant_id: int, *,
                                only_active: bool = True) -> list[dict]:
    """List pola scope='cert_variant'."""
    sql = "SELECT * FROM produkt_pola WHERE scope='cert_variant' AND scope_id=?"
    params: list = [variant_id]
    if only_active:
        sql += " AND aktywne=1"
    sql += " ORDER BY kolejnosc, id"
    return [_row_to_dict(r) for r in db.execute(sql, params).fetchall()]


def get_wartosci_for_ebr(db, ebr_id: int, produkt_id: int) -> dict:
    """Return ``{kod: wartosc}`` for all active produkt-scoped pola.

    Only fields ``scope='produkt'`` and ``scope_id=produkt_id`` with
    ``aktywne=1`` are returned. Fields without a stored value (or with
    ``NULL`` value) are skipped.
    """
    rows = db.execute(
        """
        SELECT pp.kod, ev.wartosc
        FROM produkt_pola pp
        LEFT JOIN ebr_pola_wartosci ev ON ev.pole_id = pp.id AND ev.ebr_id = ?
        WHERE pp.scope='produkt' AND pp.scope_id=? AND pp.aktywne=1
        """,
        (ebr_id, produkt_id),
    ).fetchall()
    return {r["kod"]: r["wartosc"] for r in rows if r["wartosc"] is not None}
