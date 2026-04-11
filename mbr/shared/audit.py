"""
mbr/shared/audit.py — Audit trail helper.

Single point of entry for writing audit trail events. Routes call
`log_event()` with event_type + entity info; helper resolves actors from
Flask session + shift workers, serializes diff/payload/context, and
writes atomically into the caller's DB transaction.

See docs/superpowers/specs/2026-04-11-audit-trail-design.md
"""

# =========================================================================
# Event type constants — SSOT. Never use raw string event_type in routes.
# =========================================================================

# auth
EVENT_AUTH_LOGIN = "auth.login"
EVENT_AUTH_LOGOUT = "auth.logout"
EVENT_AUTH_PASSWORD_CHANGED = "auth.password_changed"

# workers
EVENT_WORKER_CREATED = "worker.created"
EVENT_WORKER_UPDATED = "worker.updated"
EVENT_WORKER_DELETED = "worker.deleted"
EVENT_SHIFT_CHANGED = "shift.changed"

# mbr / technolog / rejestry
EVENT_MBR_TEMPLATE_CREATED = "mbr.template.created"
EVENT_MBR_TEMPLATE_UPDATED = "mbr.template.updated"
EVENT_MBR_TEMPLATE_DELETED = "mbr.template.deleted"
EVENT_ETAP_CATALOG_CREATED = "etap.catalog.created"
EVENT_ETAP_CATALOG_UPDATED = "etap.catalog.updated"
EVENT_ETAP_CATALOG_DELETED = "etap.catalog.deleted"
EVENT_PARAMETR_CREATED = "parametr.created"
EVENT_PARAMETR_UPDATED = "parametr.updated"
EVENT_PARAMETR_DELETED = "parametr.deleted"
EVENT_METODA_CREATED = "metoda.created"
EVENT_METODA_UPDATED = "metoda.updated"
EVENT_METODA_DELETED = "metoda.deleted"
EVENT_ZBIORNIK_CREATED = "zbiornik.created"
EVENT_ZBIORNIK_UPDATED = "zbiornik.updated"
EVENT_ZBIORNIK_DELETED = "zbiornik.deleted"
EVENT_PRODUKT_CREATED = "produkt.created"
EVENT_PRODUKT_UPDATED = "produkt.updated"
EVENT_PRODUKT_DELETED = "produkt.deleted"
EVENT_REGISTRY_ENTRY_CREATED = "registry.entry.created"
EVENT_REGISTRY_ENTRY_UPDATED = "registry.entry.updated"
EVENT_REGISTRY_ENTRY_DELETED = "registry.entry.deleted"

# ebr / laborant
EVENT_EBR_BATCH_CREATED = "ebr.batch.created"
EVENT_EBR_BATCH_STATUS_CHANGED = "ebr.batch.status_changed"
EVENT_EBR_STAGE_EVENT_ADDED = "ebr.stage.event_added"
EVENT_EBR_STAGE_EVENT_UPDATED = "ebr.stage.event_updated"
EVENT_EBR_STAGE_EVENT_DELETED = "ebr.stage.event_deleted"
EVENT_EBR_WYNIK_SAVED = "ebr.wynik.saved"
EVENT_EBR_WYNIK_UPDATED = "ebr.wynik.updated"
EVENT_EBR_WYNIK_DELETED = "ebr.wynik.deleted"
EVENT_EBR_UWAGI_UPDATED = "ebr.uwagi.updated"
EVENT_EBR_PRZEPOMPOWANIE_ADDED = "ebr.przepompowanie.added"
EVENT_EBR_PRZEPOMPOWANIE_UPDATED = "ebr.przepompowanie.updated"

# certs
EVENT_CERT_GENERATED = "cert.generated"
EVENT_CERT_VALUES_EDITED = "cert.values.edited"
EVENT_CERT_CANCELLED = "cert.cancelled"
EVENT_CERT_CONFIG_UPDATED = "cert.config.updated"

# paliwo
EVENT_PALIWO_WNIOSEK_CREATED = "paliwo.wniosek.created"
EVENT_PALIWO_WNIOSEK_UPDATED = "paliwo.wniosek.updated"
EVENT_PALIWO_WNIOSEK_DELETED = "paliwo.wniosek.deleted"
EVENT_PALIWO_OSOBA_CREATED = "paliwo.osoba.created"
EVENT_PALIWO_OSOBA_UPDATED = "paliwo.osoba.updated"
EVENT_PALIWO_OSOBA_DELETED = "paliwo.osoba.deleted"

# admin
EVENT_ADMIN_BACKUP_CREATED = "admin.backup.created"
EVENT_ADMIN_BATCH_CANCELLED = "admin.batch.cancelled"
EVENT_ADMIN_SETTINGS_CHANGED = "admin.settings.changed"
EVENT_ADMIN_FEEDBACK_EXPORTED = "admin.feedback.exported"

# system
EVENT_SYSTEM_MIGRATION_APPLIED = "system.migration.applied"
EVENT_SYSTEM_AUDIT_ARCHIVED = "system.audit.archived"


# =========================================================================
# Exceptions
# =========================================================================

class ShiftRequiredError(Exception):
    """Raised when a laborant tries to write without a confirmed shift.

    Mapped by Flask error handler in mbr/app.py to HTTP 400 with
    {"error": "shift_required"} — front-end shows "Potwierdź zmianę" modal.
    """

    def __init__(self, message: str = "Brak potwierdzonej zmiany (shift_required)"):
        super().__init__(message)


# =========================================================================
# Diff utility — pure function, no Flask/DB deps
# =========================================================================

def diff_fields(old: dict, new: dict, keys: list) -> list:
    """Compare two dicts on the given keys; return list of changes.

    Each entry: {'pole': key, 'stara': old_value, 'nowa': new_value}.
    Missing keys are treated as None. Returns [] when nothing changed.

    Non-scalar values (dict/list) are returned as-is; log_event() serializes
    the whole diff list with json.dumps() at write time.
    """
    changes = []
    for key in keys:
        old_val = old.get(key)
        new_val = new.get(key)
        if old_val != new_val:
            changes.append({"pole": key, "stara": old_val, "nowa": new_val})
    return changes


# =========================================================================
# Actor resolution
# =========================================================================

def actors_system() -> list:
    """Single virtual actor for migrations, archival, startup tasks."""
    return [{"worker_id": None, "actor_login": "system", "actor_rola": "system"}]


def actors_explicit(db, worker_ids: list) -> list:
    """Resolve an explicit list of worker_ids → actor dicts.

    Used by COA (certs flow) where the form asks for a specific `wystawil`.
    Snapshots login + rola at call time. Raises ValueError for unknown IDs.
    """
    if not worker_ids:
        return []
    placeholders = ",".join("?" * len(worker_ids))
    rows = db.execute(
        f"SELECT id, login, rola FROM workers WHERE id IN ({placeholders})",
        list(worker_ids),
    ).fetchall()
    by_id = {r["id"]: r for r in rows}
    missing = [wid for wid in worker_ids if wid not in by_id]
    if missing:
        raise ValueError(f"unknown worker ids: {missing}")
    return [
        {
            "worker_id": wid,
            "actor_login": by_id[wid]["login"],
            "actor_rola": by_id[wid]["rola"],
        }
        for wid in worker_ids
    ]


def actors_from_request(db) -> list:
    """Resolve actors for the current Flask request.

    Rules (per spec):
    - rola 'laborant' → all entries in session['shift_workers'];
      empty/missing → ShiftRequiredError
    - rola 'laborant_kj', 'technolog', 'admin' → single session user
    - rola 'laborant_coa' → single session user (COA-specific routes
      override this by passing actors= explicit to log_event)
    - no session user → ValueError (this should never happen for
      authenticated routes — login_required guards them)
    """
    from flask import session  # imported lazily so module works w/o app ctx

    user = session.get("user")
    if not user:
        raise ValueError("actors_from_request() called outside authenticated session")

    rola = user.get("rola")

    if rola == "laborant":
        shift_ids = session.get("shift_workers") or []
        if not shift_ids:
            raise ShiftRequiredError()
        return actors_explicit(db, shift_ids)

    # Single-actor roles: laborant_kj, laborant_coa, technolog, admin
    return [{
        "worker_id": user.get("worker_id"),
        "actor_login": user["login"],
        "actor_rola": rola,
    }]
