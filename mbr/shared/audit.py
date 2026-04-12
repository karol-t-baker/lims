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
EVENT_EBR_BATCH_UPDATED = "ebr.batch.updated"
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
    """Resolve explicit worker_ids from the `workers` table.

    Used for rola='laborant' multi-actor case (shift workers pracujący w parach).
    `workers` table in this project has no login/rola columns — workers are lab
    technicians identified by imie+nazwisko+inicjaly+nickname. Since this resolver
    is only called for shift workers, we hardcode actor_rola='laborant' and use
    nickname (preferred) or inicjaly (fallback) as actor_login.

    Raises ValueError if any worker_id is missing from the DB.
    """
    if not worker_ids:
        return []
    placeholders = ",".join("?" * len(worker_ids))
    rows = db.execute(
        f"SELECT id, nickname, inicjaly FROM workers WHERE id IN ({placeholders})",
        list(worker_ids),
    ).fetchall()
    by_id = {r["id"]: r for r in rows}
    missing = [wid for wid in worker_ids if wid not in by_id]
    if missing:
        raise ValueError(f"unknown worker ids: {missing}")
    return [
        {
            "worker_id": wid,
            "actor_login": by_id[wid]["nickname"] or by_id[wid]["inicjaly"],
            "actor_rola": "laborant",
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

    if rola in ("laborant", "laborant_coa"):
        shift_ids = session.get("shift_workers") or []
        if not shift_ids:
            raise ShiftRequiredError()
        return actors_explicit(db, shift_ids)

    # Single-actor roles: laborant_kj, technolog, admin
    return [{
        "worker_id": user.get("worker_id"),
        "actor_login": user["login"],
        "actor_rola": rola,
    }]


# =========================================================================
# Write path
# =========================================================================

import json as _json
import gzip as _gzip
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path as _Path


def log_event(
    event_type: str,
    *,
    entity_type: str = None,
    entity_id: int = None,
    entity_label: str = None,
    diff: list = None,
    payload: dict = None,
    context: dict = None,
    actors: list = None,
    result: str = "ok",
    db=None,
) -> int:
    """Write one audit_log row + its actors, in the caller's DB transaction.

    Args:
        event_type: One of the EVENT_* constants defined in this module.
        entity_type: e.g. 'ebr', 'mbr', 'cert', 'worker', or None.
        entity_id: PK of the affected record, or None for non-entity events.
        entity_label: Denormalized human label (szarża number, produkt) for
            admin panel listings — spares JOINs on historical data.
        diff: List of {'pole', 'stara', 'nowa'} dicts from diff_fields().
        payload: Arbitrary event-specific context (PDF path, template name).
        context: Extra request context (ebr_id, produkt, ...) — merged with
            Flask g attributes if available.
        actors: Pre-resolved actor list. If None, resolved via
            actors_from_request(db) — requires Flask request context.
        result: 'ok' | 'error' — used by auth.login_failed etc.
        db: sqlite3.Connection to write into. REQUIRED. Write shares the
            caller's transaction; caller commits (or rolls back).

    Returns:
        audit_log.id (int) of the new row.

    Raises:
        ShiftRequiredError: if actors=None and the current user is a
            laborant with empty shift_workers.
        ValueError: if db is None or unknown worker in explicit actors.
    """
    if db is None:
        raise ValueError("log_event requires db= to share caller's transaction")

    if actors is None:
        actors = actors_from_request(db)

    # Request context (best-effort — works outside Flask for system events)
    request_id = None
    ip = None
    user_agent = None
    try:
        from flask import g, request
        try:
            request_id = getattr(g, "audit_request_id", None)
        except RuntimeError:
            request_id = None
        try:
            xff = request.headers.get("X-Forwarded-For")
            if xff:
                # nginx behind a proxy may send "client, proxy1, proxy2"
                ip = xff.split(",")[0].strip()
            else:
                ip = request.remote_addr
            user_agent = request.headers.get("User-Agent")
        except RuntimeError:
            pass
    except (RuntimeError, ImportError):
        # No Flask app / request context — e.g. migrations, startup
        pass

    dt = _dt.now(_tz.utc).isoformat()

    cur = db.execute(
        """INSERT INTO audit_log
           (dt, event_type, entity_type, entity_id, entity_label,
            diff_json, payload_json, context_json,
            request_id, ip, user_agent, result)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            dt,
            event_type,
            entity_type,
            entity_id,
            entity_label,
            _json.dumps(diff, ensure_ascii=False) if diff else None,
            _json.dumps(payload, ensure_ascii=False) if payload else None,
            _json.dumps(context, ensure_ascii=False) if context else None,
            request_id,
            ip,
            user_agent,
            result,
        ),
    )
    audit_id = cur.lastrowid

    for actor in actors:
        db.execute(
            """INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola)
               VALUES (?, ?, ?, ?)""",
            (audit_id, actor["worker_id"], actor["actor_login"], actor["actor_rola"]),
        )

    return audit_id


# =========================================================================
# Read path — query helpers for the admin panel + per-record history
# =========================================================================


def _build_where_clauses(*, dt_from=None, dt_to=None, event_type_glob=None,
                        entity_type=None, entity_id=None, worker_id=None,
                        free_text=None, request_id=None) -> tuple:
    """Translate filter args into a (where_sql, params) tuple."""
    clauses = []
    params = []
    if dt_from:
        clauses.append("dt >= ?")
        params.append(dt_from)
    if dt_to:
        # Inclusive end-of-day for date strings
        end = dt_to + "T23:59:59" if len(dt_to) == 10 else dt_to
        clauses.append("dt <= ?")
        params.append(end)
    if event_type_glob:
        if "*" in event_type_glob:
            clauses.append("event_type LIKE ?")
            params.append(event_type_glob.replace("*", "%"))
        else:
            clauses.append("event_type = ?")
            params.append(event_type_glob)
    if entity_type:
        clauses.append("entity_type = ?")
        params.append(entity_type)
    if entity_id is not None:
        clauses.append("entity_id = ?")
        params.append(int(entity_id))
    if worker_id is not None:
        clauses.append(
            "EXISTS (SELECT 1 FROM audit_log_actors a "
            "WHERE a.audit_id = audit_log.id AND a.worker_id = ?)"
        )
        params.append(int(worker_id))
    if free_text:
        # Escape LIKE metacharacters: backslash first (escape char), then % and _
        escaped = free_text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("(entity_label LIKE ? ESCAPE '\\' OR payload_json LIKE ? ESCAPE '\\')")
        like = f"%{escaped}%"
        params.extend([like, like])
    if request_id:
        clauses.append("request_id = ?")
        params.append(request_id)
    where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where_sql, params


def query_audit_log(
    db,
    *,
    dt_from: str = None,
    dt_to: str = None,
    event_type_glob: str = None,
    entity_type: str = None,
    entity_id: int = None,
    worker_id: int = None,
    free_text: str = None,
    request_id: str = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple:
    """Query the audit log with optional filters and pagination.

    Returns (rows, total_count) where rows is a list of dicts (each augmented
    with an 'actors' list) and total_count is the unpaginated row count.

    Glob behavior: event_type_glob='auth.*' becomes SQL LIKE 'auth.%'.
    Exact equality is used when no '*' is present.

    Multi-actor filter (worker_id) uses EXISTS subquery so a row matches if
    ANY of its actors equals worker_id.
    """
    where_sql, params = _build_where_clauses(
        dt_from=dt_from, dt_to=dt_to, event_type_glob=event_type_glob,
        entity_type=entity_type, entity_id=entity_id, worker_id=worker_id,
        free_text=free_text, request_id=request_id,
    )

    # Total count first (cheap, same WHERE)
    total_row = db.execute(
        f"SELECT COUNT(*) FROM audit_log{where_sql}", params
    ).fetchone()
    total = total_row[0]

    # Data page
    data_sql = (
        f"SELECT id, dt, event_type, entity_type, entity_id, entity_label, "
        f"diff_json, payload_json, context_json, request_id, ip, user_agent, result "
        f"FROM audit_log{where_sql} ORDER BY dt DESC, id DESC LIMIT ? OFFSET ?"
    )
    rows = [dict(r) for r in db.execute(data_sql, params + [limit, offset]).fetchall()]

    # Bulk-load actors for the page (avoids N+1)
    if rows:
        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" * len(ids))
        actor_rows = db.execute(
            f"SELECT audit_id, worker_id, actor_login, actor_rola "
            f"FROM audit_log_actors WHERE audit_id IN ({placeholders})",
            ids,
        ).fetchall()
        by_audit = {}
        for ar in actor_rows:
            by_audit.setdefault(ar["audit_id"], []).append(dict(ar))
        for r in rows:
            r["actors"] = by_audit.get(r["id"], [])
    return rows, total


def query_audit_history_for_entity(db, entity_type: str, entity_id: int) -> list:
    """Per-record history for entity views (EBR/MBR/cert).

    Returns rows sorted dt DESC with actors joined. No pagination —
    entity histories are bounded (a single batch typically generates <50 events).
    """
    rows, _total = query_audit_log(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=1000,  # safety cap
        offset=0,
    )
    return rows


def archive_old_entries(db, cutoff_iso: str, archive_dir) -> dict:
    """Archive audit_log entries older than cutoff_iso into a gzipped JSONL
    file, then delete them from the active DB.

    File path: {archive_dir}/audit_{cutoff_year}.jsonl.gz where cutoff_year
    is parsed from cutoff_iso. Uses gzip append mode so multiple archivals
    in the same year accumulate into one file.

    After deletion, logs a 'system.audit.archived' event with the system
    virtual actor and a payload of {count, file, cutoff}.

    All operations run in a single transaction. If the gzip write fails,
    the transaction rolls back and no rows are deleted.

    Returns: {'archived': N, 'file': str(path), 'cutoff': cutoff_iso}.
    """
    archive_dir = _Path(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    year = cutoff_iso[:4]
    archive_path = archive_dir / f"audit_{year}.jsonl.gz"

    # 1. Read rows + actors that will be archived
    where_sql = " WHERE dt < ?"
    rows_to_archive = [dict(r) for r in db.execute(
        f"SELECT id, dt, event_type, entity_type, entity_id, entity_label, "
        f"diff_json, payload_json, context_json, request_id, ip, user_agent, result "
        f"FROM audit_log{where_sql}", (cutoff_iso,),
    ).fetchall()]
    if rows_to_archive:
        ids = [r["id"] for r in rows_to_archive]
        placeholders = ",".join("?" * len(ids))
        actor_rows = db.execute(
            f"SELECT audit_id, worker_id, actor_login, actor_rola "
            f"FROM audit_log_actors WHERE audit_id IN ({placeholders})",
            ids,
        ).fetchall()
        by_audit = {}
        for ar in actor_rows:
            by_audit.setdefault(ar["audit_id"], []).append(dict(ar))
        for r in rows_to_archive:
            r["actors"] = by_audit.get(r["id"], [])

    archived_count = len(rows_to_archive)

    # 2. Append to gzipped JSONL file. If this raises, the transaction
    # rolls back and no rows are deleted.
    try:
        if rows_to_archive:
            with _gzip.open(archive_path, "at", encoding="utf-8") as f:
                for r in rows_to_archive:
                    f.write(_json.dumps(r, ensure_ascii=False, default=str) + "\n")

            # 3. Delete archived rows from the DB
            db.execute(f"DELETE FROM audit_log{where_sql}", (cutoff_iso,))

            # 4. Log the archive event itself (system actor) AFTER delete so
            # the fresh event cannot be swept by the same call.
            log_event(
                EVENT_SYSTEM_AUDIT_ARCHIVED,
                payload={
                    "count": archived_count,
                    "file": str(archive_path),
                    "cutoff": cutoff_iso,
                },
                actors=actors_system(),
                db=db,
            )

            db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "archived": archived_count,
        "file": str(archive_path) if rows_to_archive else None,
        "cutoff": cutoff_iso,
    }
