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
