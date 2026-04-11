# Audit Trail — Phase 1 (Infrastructure) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the audit trail infrastructure (DB schema, helper module, Flask wiring, migration script, unit tests) with zero integration in existing blueprints. After Phase 1 the system has a working `log_event()` API that nobody calls yet — safe, rollback-able, testable.

**Architecture:** Single helper module `mbr/shared/audit.py` exposes `log_event()` + actor-resolution helpers. Two new tables: `audit_log` (event + entity + diff + payload + context) and `audit_log_actors` (multi-actor junction). Flask gains `before_request` for `request_id` and error handler for `ShiftRequiredError`. Existing `audit_log` table (old shape) is renamed + backfilled by an idempotent migration script.

**Tech Stack:** Flask, sqlite3 (raw, no ORM), pytest with in-memory SQLite fixtures, Python 3.12.

**Spec reference:** `docs/superpowers/specs/2026-04-11-audit-trail-design.md`

**Out of scope for Phase 1:**
- Any `log_event()` call in existing routes (that's Phases 3–6)
- Admin panel UI `/admin/audit` (Phase 2)
- Archive/retention logic (Phase 2)
- Removing shift fallback in `laborant/routes.py` (Phase 3 — part of behaviour change)

---

## File Structure

**Create:**
- `mbr/shared/audit.py` — helper module (~200 LOC). One responsibility: provide `log_event()` + actor resolution + diff utility. No Flask imports at module top — all `from flask import ...` inside functions that need request/session, so unit tests can import without app context.
- `scripts/migrate_audit_log_v2.py` — standalone migration script. Idempotent, reads `data/batch_db.sqlite`, renames old `audit_log` → `audit_log_v1`, creates new tables, backfills. Follows existing `scripts/migrate_*.py` pattern (argparse, dry-run flag).
- `tests/test_audit_helper.py` — unit tests for helper with in-memory SQLite fixture (mirrors `tests/test_auth.py` style).
- `tests/test_migrate_audit_log_v2.py` — migration script tests with in-memory DB.

**Modify:**
- `mbr/models.py:488-499` — replace old `audit_log` schema with new `audit_log` + `audit_log_actors` + indexes (for fresh installs via `init_mbr_tables`). Existing installs get migration from the script.
- `mbr/app.py:9-78` — add `before_request` setting `g.audit_request_id`, add `errorhandler` for `ShiftRequiredError`.

**Not touching yet:**
- `mbr/auth/`, `mbr/workers/`, `mbr/laborant/`, `mbr/technolog/`, `mbr/certs/`, `mbr/admin/`, etc. — Phase 1 is infrastructure-only.

---

## Task 1: New schema in `init_mbr_tables()`

**Files:**
- Modify: `mbr/models.py:488-499` (current `audit_log CREATE TABLE` block)

The existing block creates the old audit_log shape. We replace it with the new two-table schema. This ensures fresh installs get the new structure directly; existing installs run the migration script (Task 2).

- [ ] **Step 1: Read current schema block**

Run: Read `mbr/models.py` lines 485-510 to see exact context.

Expected: block from line 488 creating old `audit_log` with columns `dt, tabela, rekord_id, pole, stara_wartosc, nowa_wartosc, zmienil`.

- [ ] **Step 2: Replace schema block**

Edit `mbr/models.py`. Replace:

```python
    db.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            dt          TEXT NOT NULL,
            tabela      TEXT NOT NULL,
            rekord_id   INTEGER NOT NULL,
            pole        TEXT NOT NULL,
            stara_wartosc TEXT,
            nowa_wartosc  TEXT,
            zmienil     TEXT NOT NULL
        )
    """)
```

With:

```python
    db.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            dt              TEXT NOT NULL,
            event_type      TEXT NOT NULL,
            entity_type     TEXT,
            entity_id       INTEGER,
            entity_label    TEXT,
            diff_json       TEXT,
            payload_json    TEXT,
            context_json    TEXT,
            request_id      TEXT,
            ip              TEXT,
            user_agent      TEXT,
            result          TEXT NOT NULL DEFAULT 'ok'
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS audit_log_actors (
            audit_id        INTEGER NOT NULL REFERENCES audit_log(id) ON DELETE CASCADE,
            worker_id       INTEGER,
            actor_login     TEXT NOT NULL,
            actor_rola      TEXT NOT NULL,
            PRIMARY KEY (audit_id, actor_login)
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_dt ON audit_log(dt DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_event_type ON audit_log(event_type)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_request ON audit_log(request_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_audit_actors_worker ON audit_log_actors(worker_id)")
```

**Note:** `CREATE TABLE IF NOT EXISTS` means this is a no-op on existing installs where `audit_log` already has the old shape — those go through Task 2 (migration script). Fresh installs get the new shape straight away.

- [ ] **Step 3: Run existing tests to verify nothing broke**

Run: `pytest -x 2>&1 | tail -30`

Expected: All tests pass. The old `audit_log` shape is no longer used by any test directly (the two call sites in `laborant/models.py:481` and `etapy/models.py:45` still reference old columns — **do NOT fix them in Phase 1**, they're part of Phase 3/4 integration).

**If those tests fail** because of legacy call sites: check which tests, and note in the failure. Two possibilities:
- a) Test hits the legacy call site on fresh schema → the legacy `INSERT INTO audit_log (dt, tabela, ...)` fails because columns don't exist → legitimate breakage
- b) Something else

For case (a): the fix is to **skip legacy call sites in Phase 1** by guarding them. Temporary patch — convert the two legacy `INSERT`s to a no-op comment with `# TODO(audit-phase-3): migrate to log_event`. This is acceptable because:
- Both call sites are currently logging to a table nobody reads programmatically
- Phase 3/4 will replace them with `log_event()`
- Losing ~days of legacy logs during transition is acceptable per spec (opt B — internal traceability, not GMP)

Concretely, if tests fail, add this step:

  Edit `mbr/laborant/models.py:481` — comment out the `INSERT INTO audit_log ...` line, replace with `pass  # TODO(audit-phase-4): replace with log_event('ebr.wynik.updated', ...)`. Same for `mbr/etapy/models.py:45`.

- [ ] **Step 4: Commit**

```bash
git add mbr/models.py mbr/laborant/models.py mbr/etapy/models.py
git commit -m "feat(audit): new audit_log + audit_log_actors schema in init_mbr_tables

Replace old single-table audit_log with event-based schema:
- audit_log: event_type, entity, diff_json, payload, context, request_id
- audit_log_actors: multi-actor junction (laboranci w parach)
- Indexes on dt, entity, event_type, request_id, actor

Fresh installs get new schema via init_mbr_tables; existing installs
use scripts/migrate_audit_log_v2.py (next task).

Legacy audit_log call sites in laborant/models.py and etapy/models.py
neutralized with TODO — will be replaced with log_event() in Phase 4.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-design.md"
```

---

## Task 2: Migration script `scripts/migrate_audit_log_v2.py`

**Files:**
- Create: `scripts/migrate_audit_log_v2.py`
- Test: `tests/test_migrate_audit_log_v2.py`

Script handles existing installs: renames old table, creates new, backfills legacy rows as `event_type='legacy.field_change'`. Idempotent — rerunning is a no-op.

- [ ] **Step 1: Write failing test — fresh DB (no old audit_log)**

Create `tests/test_migrate_audit_log_v2.py`:

```python
"""Tests for scripts/migrate_audit_log_v2.py"""

import sqlite3
import pytest

from scripts.migrate_audit_log_v2 import migrate


def _make_db_with_old_schema(rows=None):
    """Build in-memory DB matching pre-migration state: old audit_log + workers."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("""
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dt TEXT NOT NULL,
            tabela TEXT NOT NULL,
            rekord_id INTEGER NOT NULL,
            pole TEXT NOT NULL,
            stara_wartosc TEXT,
            nowa_wartosc TEXT,
            zmienil TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            imie TEXT, nazwisko TEXT, nickname TEXT, inicjaly TEXT,
            login TEXT, rola TEXT
        )
    """)
    for r in rows or []:
        db.execute(
            "INSERT INTO audit_log (dt, tabela, rekord_id, pole, stara_wartosc, nowa_wartosc, zmienil) VALUES (?,?,?,?,?,?,?)",
            r,
        )
    db.commit()
    return db


def test_migrate_fresh_db_no_old_table_is_noop():
    """Running migration on DB without audit_log (truly fresh) is a no-op that exits cleanly."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    summary = migrate(db)
    assert summary["backfilled"] == 0
    assert summary["renamed"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_migrate_audit_log_v2.py::test_migrate_fresh_db_no_old_table_is_noop -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.migrate_audit_log_v2'`.

- [ ] **Step 3: Create skeleton `scripts/migrate_audit_log_v2.py`**

Create file with:

```python
"""
migrate_audit_log_v2.py — one-time migration for existing installs.

Transforms legacy audit_log (dt, tabela, rekord_id, pole, stara_wartosc,
nowa_wartosc, zmienil) into the new event-based schema + audit_log_actors
junction. Idempotent — rerunning is safe.

Steps:
  1. If audit_log has NEW columns already (event_type exists), exit — already migrated.
  2. Else rename old table to audit_log_v1.
  3. Create new audit_log + audit_log_actors + indexes.
  4. Backfill audit_log_v1 → audit_log as event_type='legacy.field_change',
     resolving `zmienil` string → worker_id when possible (JOIN on workers.inicjaly
     or workers.nickname or workers.login).
  5. Verify counts match; leave audit_log_v1 in place for rollback (drop in Phase 7).

Usage:
    python scripts/migrate_audit_log_v2.py --db data/batch_db.sqlite [--dry-run]
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path


_NEW_AUDIT_LOG_DDL = """
CREATE TABLE audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    dt              TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    entity_type     TEXT,
    entity_id       INTEGER,
    entity_label    TEXT,
    diff_json       TEXT,
    payload_json    TEXT,
    context_json    TEXT,
    request_id      TEXT,
    ip              TEXT,
    user_agent      TEXT,
    result          TEXT NOT NULL DEFAULT 'ok'
)
"""

_NEW_AUDIT_ACTORS_DDL = """
CREATE TABLE audit_log_actors (
    audit_id        INTEGER NOT NULL REFERENCES audit_log(id) ON DELETE CASCADE,
    worker_id       INTEGER,
    actor_login     TEXT NOT NULL,
    actor_rola      TEXT NOT NULL,
    PRIMARY KEY (audit_id, worker_id, actor_login)
)
"""

_INDEXES = [
    "CREATE INDEX idx_audit_log_dt ON audit_log(dt DESC)",
    "CREATE INDEX idx_audit_log_entity ON audit_log(entity_type, entity_id)",
    "CREATE INDEX idx_audit_log_event_type ON audit_log(event_type)",
    "CREATE INDEX idx_audit_log_request ON audit_log(request_id)",
    "CREATE INDEX idx_audit_actors_worker ON audit_log_actors(worker_id)",
]


def _table_exists(db: sqlite3.Connection, name: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _has_new_columns(db: sqlite3.Connection) -> bool:
    """Return True if audit_log already has the new 'event_type' column."""
    cols = [r[1] for r in db.execute("PRAGMA table_info(audit_log)").fetchall()]
    return "event_type" in cols


def _resolve_worker(db: sqlite3.Connection, zmienil: str):
    """Try to find workers.id for a legacy `zmienil` string.
    Returns (worker_id or None, actor_login, actor_rola)."""
    if not _table_exists(db, "workers"):
        return (None, zmienil, "unknown")
    row = db.execute(
        """SELECT id, COALESCE(rola, 'unknown') AS rola FROM workers
           WHERE inicjaly=? OR nickname=? OR login=?
           LIMIT 1""",
        (zmienil, zmienil, zmienil),
    ).fetchone()
    if row:
        return (row[0], zmienil, row[1])
    return (None, zmienil, "unknown")


def migrate(db: sqlite3.Connection, dry_run: bool = False) -> dict:
    summary = {"renamed": False, "backfilled": 0, "skipped_already_migrated": False}

    if not _table_exists(db, "audit_log"):
        return summary

    if _has_new_columns(db):
        summary["skipped_already_migrated"] = True
        return summary

    if dry_run:
        count = db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        summary["backfilled"] = count
        summary["renamed"] = True  # would be
        return summary

    db.execute("ALTER TABLE audit_log RENAME TO audit_log_v1")
    summary["renamed"] = True

    db.execute(_NEW_AUDIT_LOG_DDL)
    db.execute(_NEW_AUDIT_ACTORS_DDL)
    for ddl in _INDEXES:
        db.execute(ddl)

    old_rows = db.execute(
        "SELECT id, dt, tabela, rekord_id, pole, stara_wartosc, nowa_wartosc, zmienil FROM audit_log_v1"
    ).fetchall()

    for old in old_rows:
        diff = [{"pole": old[4], "stara": old[5], "nowa": old[6]}]
        cur = db.execute(
            """INSERT INTO audit_log
               (dt, event_type, entity_type, entity_id, diff_json, result)
               VALUES (?, 'legacy.field_change', ?, ?, ?, 'ok')""",
            (old[1], old[2], old[3], json.dumps(diff, ensure_ascii=False)),
        )
        new_id = cur.lastrowid
        worker_id, actor_login, actor_rola = _resolve_worker(db, old[7])
        db.execute(
            "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, ?, ?, ?)",
            (new_id, worker_id, actor_login, actor_rola),
        )
        summary["backfilled"] += 1

    old_count = db.execute("SELECT COUNT(*) FROM audit_log_v1").fetchone()[0]
    new_count = db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    if old_count != new_count:
        raise RuntimeError(
            f"Backfill count mismatch: old={old_count}, new={new_count}"
        )

    db.commit()
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/batch_db.sqlite")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: {db_path} not found", file=sys.stderr)
        sys.exit(1)

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        summary = migrate(db, dry_run=args.dry_run)
    finally:
        db.close()

    print(f"Migration summary: {summary}")
    if args.dry_run:
        print("(dry-run — no changes committed)")


if __name__ == "__main__":
    main()
```

Also create `scripts/__init__.py` if it doesn't exist (so pytest can import `scripts.migrate_audit_log_v2`). Check first with `ls scripts/__init__.py`; if absent, create empty file.

- [ ] **Step 4: Run first test to verify it passes**

Run: `pytest tests/test_migrate_audit_log_v2.py::test_migrate_fresh_db_no_old_table_is_noop -v`

Expected: PASS.

- [ ] **Step 5: Add test — old DB with rows gets backfilled**

Append to `tests/test_migrate_audit_log_v2.py`:

```python
def test_migrate_old_audit_log_backfills_rows():
    """Legacy rows migrate as event_type='legacy.field_change'."""
    db = _make_db_with_old_schema(rows=[
        ("2026-04-01T10:00:00", "ebr_wyniki", 42, "temperatura", "85", "87", "AK"),
        ("2026-04-01T11:00:00", "ebr_stages", 17, "status", "open", "done", "MW"),
    ])
    # Add workers so resolve_worker can match
    db.execute(
        "INSERT INTO workers (id, imie, nazwisko, nickname, inicjaly, rola) VALUES (1,'Anna','Kowalska','AK','AK','laborant')"
    )
    db.execute(
        "INSERT INTO workers (id, imie, nazwisko, nickname, inicjaly, rola) VALUES (2,'Maria','Wójcik','MW','MW','laborant')"
    )
    db.commit()

    summary = migrate(db)

    assert summary["renamed"] is True
    assert summary["backfilled"] == 2

    new_rows = db.execute(
        "SELECT event_type, entity_type, entity_id, diff_json FROM audit_log ORDER BY id"
    ).fetchall()
    assert len(new_rows) == 2
    assert new_rows[0]["event_type"] == "legacy.field_change"
    assert new_rows[0]["entity_type"] == "ebr_wyniki"
    assert new_rows[0]["entity_id"] == 42
    diff = json.loads(new_rows[0]["diff_json"])
    assert diff == [{"pole": "temperatura", "stara": "85", "nowa": "87"}]

    actors = db.execute(
        "SELECT audit_id, worker_id, actor_login, actor_rola FROM audit_log_actors ORDER BY audit_id"
    ).fetchall()
    assert len(actors) == 2
    assert actors[0]["worker_id"] == 1
    assert actors[0]["actor_login"] == "AK"
    assert actors[0]["actor_rola"] == "laborant"


def test_migrate_unknown_zmienil_stores_null_worker_id():
    """When `zmienil` can't be resolved to a worker, store NULL worker_id + 'unknown' rola."""
    db = _make_db_with_old_schema(rows=[
        ("2026-04-01T10:00:00", "x", 1, "pole", "a", "b", "ghost_user"),
    ])
    migrate(db)
    actor = db.execute("SELECT worker_id, actor_login, actor_rola FROM audit_log_actors").fetchone()
    assert actor["worker_id"] is None
    assert actor["actor_login"] == "ghost_user"
    assert actor["actor_rola"] == "unknown"


def test_migrate_is_idempotent():
    """Running twice is a no-op on the second run."""
    db = _make_db_with_old_schema(rows=[
        ("2026-04-01T10:00:00", "x", 1, "p", "a", "b", "AK"),
    ])
    migrate(db)
    summary_second = migrate(db)
    assert summary_second["skipped_already_migrated"] is True
    assert summary_second["backfilled"] == 0
    # Sanity: new audit_log still has exactly 1 row
    count = db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    assert count == 1


def test_migrate_dry_run_does_not_mutate():
    """--dry-run reports what would happen without changing the DB."""
    db = _make_db_with_old_schema(rows=[
        ("2026-04-01T10:00:00", "x", 1, "p", "a", "b", "AK"),
    ])
    summary = migrate(db, dry_run=True)
    assert summary["backfilled"] == 1
    # Old table still exists, new table does NOT
    assert db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'"
    ).fetchone() is not None
    assert db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log_v1'"
    ).fetchone() is None
    # event_type column should still NOT exist
    cols = [r[1] for r in db.execute("PRAGMA table_info(audit_log)").fetchall()]
    assert "event_type" not in cols
```

- [ ] **Step 6: Run all migration tests**

Run: `pytest tests/test_migrate_audit_log_v2.py -v`

Expected: 5 tests PASS. If any fail, read the failure — most likely the resolve_worker query needs schema adjustment. Fix inline in `scripts/migrate_audit_log_v2.py`.

- [ ] **Step 7: Commit**

```bash
git add scripts/migrate_audit_log_v2.py scripts/__init__.py tests/test_migrate_audit_log_v2.py
git commit -m "feat(audit): idempotent migration script for legacy audit_log

scripts/migrate_audit_log_v2.py handles existing installs:
- Rename audit_log → audit_log_v1 (rollback safety)
- Create new audit_log + audit_log_actors + indexes
- Backfill legacy rows as event_type='legacy.field_change' with
  diff_json=[{pole, stara, nowa}] and resolved worker_id
- Idempotent — second run is no-op
- Dry-run mode for safe inspection

Tests: 5 cases covering fresh DB, backfill, unknown user, idempotency, dry-run.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-design.md"
```

---

## Task 3: Helper module skeleton + constants + `ShiftRequiredError`

**Files:**
- Create: `mbr/shared/audit.py`
- Test: `tests/test_audit_helper.py`

Build bottom-up. Start with the lightweight pieces (constants + exception class) — they have no dependencies and let later tasks import cleanly.

- [ ] **Step 1: Write failing test for event_type constants**

Create `tests/test_audit_helper.py`:

```python
"""Tests for mbr/shared/audit.py"""

import json
import sqlite3
import pytest

from mbr.shared import audit


def test_event_type_constants_follow_naming_convention():
    """All event_type constants are lowercase dot-separated strings."""
    names = [
        audit.EVENT_AUTH_LOGIN,
        audit.EVENT_AUTH_LOGOUT,
        audit.EVENT_WORKER_CREATED,
        audit.EVENT_EBR_WYNIK_SAVED,
        audit.EVENT_CERT_GENERATED,
        audit.EVENT_MBR_TEMPLATE_UPDATED,
        audit.EVENT_SYSTEM_MIGRATION_APPLIED,
    ]
    for name in names:
        assert name == name.lower()
        assert "." in name
        assert " " not in name


def test_shift_required_error_is_exception():
    """ShiftRequiredError is an Exception subclass with a default message."""
    err = audit.ShiftRequiredError()
    assert isinstance(err, Exception)
    assert "shift" in str(err).lower() or "zmiana" in str(err).lower()
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_audit_helper.py::test_event_type_constants_follow_naming_convention -v`

Expected: FAIL with `ModuleNotFoundError` or `AttributeError`.

- [ ] **Step 3: Create `mbr/shared/audit.py` skeleton**

```python
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
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_audit_helper.py -v`

Expected: Both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/shared/audit.py tests/test_audit_helper.py
git commit -m "feat(audit): helper skeleton — event_type constants + ShiftRequiredError

mbr/shared/audit.py exposes:
- ~50 event_type string constants (SSOT for audit event taxonomy)
- ShiftRequiredError exception class

No Flask imports yet — pure data. Rest of helper (log_event, actors_*,
diff_fields) lands in following tasks.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-design.md"
```

---

## Task 4: `diff_fields()` utility

**Files:**
- Modify: `mbr/shared/audit.py` (append function)
- Test: `tests/test_audit_helper.py` (append tests)

Pure function — no Flask, no DB. Easy to test.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_audit_helper.py`:

```python
# ---------- diff_fields ----------

def test_diff_fields_returns_empty_when_no_changes():
    old = {"a": 1, "b": 2, "c": 3}
    new = {"a": 1, "b": 2, "c": 3}
    assert audit.diff_fields(old, new, ["a", "b", "c"]) == []


def test_diff_fields_only_reports_keys_in_keys_list():
    old = {"a": 1, "b": 2, "ignored": "old"}
    new = {"a": 1, "b": 99, "ignored": "new"}
    result = audit.diff_fields(old, new, ["a", "b"])
    assert result == [{"pole": "b", "stara": 2, "nowa": 99}]


def test_diff_fields_reports_multiple_changes_in_order_of_keys():
    old = {"a": 1, "b": 2, "c": 3}
    new = {"a": 10, "b": 2, "c": 30}
    result = audit.diff_fields(old, new, ["a", "b", "c"])
    assert result == [
        {"pole": "a", "stara": 1, "nowa": 10},
        {"pole": "c", "stara": 3, "nowa": 30},
    ]


def test_diff_fields_serializes_non_scalars_to_json():
    old = {"etapy_json": [{"s": 1}]}
    new = {"etapy_json": [{"s": 1}, {"s": 2}]}
    result = audit.diff_fields(old, new, ["etapy_json"])
    assert len(result) == 1
    assert result[0]["pole"] == "etapy_json"
    # Non-scalars are kept as-is in the returned dict (caller/log_event serializes to JSON).
    assert result[0]["stara"] == [{"s": 1}]
    assert result[0]["nowa"] == [{"s": 1}, {"s": 2}]


def test_diff_fields_handles_none_values():
    old = {"note": None}
    new = {"note": "hello"}
    assert audit.diff_fields(old, new, ["note"]) == [
        {"pole": "note", "stara": None, "nowa": "hello"}
    ]


def test_diff_fields_missing_keys_treated_as_none():
    old = {}
    new = {"a": 1}
    assert audit.diff_fields(old, new, ["a"]) == [
        {"pole": "a", "stara": None, "nowa": 1}
    ]
```

- [ ] **Step 2: Run tests — verify failure**

Run: `pytest tests/test_audit_helper.py -k diff_fields -v`

Expected: FAIL — `AttributeError: module ... has no attribute 'diff_fields'`.

- [ ] **Step 3: Implement `diff_fields`**

Append to `mbr/shared/audit.py`:

```python
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
```

- [ ] **Step 4: Run tests — verify pass**

Run: `pytest tests/test_audit_helper.py -k diff_fields -v`

Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/shared/audit.py tests/test_audit_helper.py
git commit -m "feat(audit): diff_fields utility + unit tests

Pure function comparing old/new dicts on a given key list. Missing keys
treated as None. Non-scalars returned as-is (log_event serializes JSON
at write time). Returns [] when nothing changed.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-design.md"
```

---

## Task 5: Actor resolution — `actors_system()`, `actors_explicit()`, `actors_from_request()`

**Files:**
- Modify: `mbr/shared/audit.py`
- Test: `tests/test_audit_helper.py`

`actors_from_request()` imports Flask `session` inside the function — unit tests push a fake session via `app.test_request_context()`. `actors_explicit` and `actors_system` are pure.

- [ ] **Step 1: Write failing tests for `actors_system` and `actors_explicit`**

Append to `tests/test_audit_helper.py`:

```python
# ---------- actors_system / actors_explicit ----------

def test_actors_system_returns_single_system_actor():
    result = audit.actors_system()
    assert result == [
        {"worker_id": None, "actor_login": "system", "actor_rola": "system"}
    ]


@pytest.fixture
def workers_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            imie TEXT, nazwisko TEXT, nickname TEXT, inicjaly TEXT,
            login TEXT, rola TEXT
        )
    """)
    db.executemany(
        "INSERT INTO workers (id, imie, nazwisko, nickname, inicjaly, login, rola) VALUES (?,?,?,?,?,?,?)",
        [
            (1, "Anna",  "Kowalska", "AK", "AK", "anna",  "laborant_coa"),
            (2, "Maria", "Wójcik",   "MW", "MW", "maria", "laborant"),
            (3, "Jan",   "Nowak",    "JN", "JN", "jan",   "technolog"),
        ],
    )
    db.commit()
    yield db
    db.close()


def test_actors_explicit_resolves_worker_rows_from_db(workers_db):
    result = audit.actors_explicit(workers_db, [1, 3])
    assert result == [
        {"worker_id": 1, "actor_login": "anna", "actor_rola": "laborant_coa"},
        {"worker_id": 3, "actor_login": "jan",  "actor_rola": "technolog"},
    ]


def test_actors_explicit_raises_on_unknown_worker_id(workers_db):
    with pytest.raises(ValueError, match="unknown worker"):
        audit.actors_explicit(workers_db, [999])


def test_actors_explicit_empty_list_returns_empty():
    db = sqlite3.connect(":memory:")
    assert audit.actors_explicit(db, []) == []
    db.close()
```

- [ ] **Step 2: Run tests — verify failure**

Run: `pytest tests/test_audit_helper.py -k "actors_system or actors_explicit" -v`

Expected: FAIL — AttributeError on `audit.actors_system` / `audit.actors_explicit`.

- [ ] **Step 3: Implement `actors_system` and `actors_explicit`**

Append to `mbr/shared/audit.py`:

```python
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
```

- [ ] **Step 4: Run tests — verify pass**

Run: `pytest tests/test_audit_helper.py -k "actors_system or actors_explicit" -v`

Expected: 4 tests PASS.

- [ ] **Step 5: Write failing tests for `actors_from_request`**

Append to `tests/test_audit_helper.py`:

```python
# ---------- actors_from_request ----------

from flask import Flask


@pytest.fixture
def app_with_workers(workers_db):
    """Flask app with a test request context — workers DB available via g."""
    app = Flask(__name__)
    app.secret_key = "test"
    return app


def test_actors_from_request_admin_returns_single_session_user(app_with_workers, workers_db):
    with app_with_workers.test_request_context():
        from flask import session
        session["user"] = {"login": "jan", "rola": "technolog", "worker_id": 3}
        result = audit.actors_from_request(workers_db)
    assert result == [{"worker_id": 3, "actor_login": "jan", "actor_rola": "technolog"}]


def test_actors_from_request_technolog_ignores_shift(app_with_workers, workers_db):
    with app_with_workers.test_request_context():
        from flask import session
        session["user"] = {"login": "jan", "rola": "technolog", "worker_id": 3}
        session["shift_workers"] = [1, 2]  # should be ignored for technolog
        result = audit.actors_from_request(workers_db)
    assert len(result) == 1
    assert result[0]["worker_id"] == 3


def test_actors_from_request_laborant_returns_all_shift_workers(app_with_workers, workers_db):
    with app_with_workers.test_request_context():
        from flask import session
        session["user"] = {"login": "anna", "rola": "laborant", "worker_id": 1}
        session["shift_workers"] = [1, 2]
        result = audit.actors_from_request(workers_db)
    assert len(result) == 2
    assert {a["worker_id"] for a in result} == {1, 2}


def test_actors_from_request_laborant_with_empty_shift_raises(app_with_workers, workers_db):
    with app_with_workers.test_request_context():
        from flask import session
        session["user"] = {"login": "anna", "rola": "laborant", "worker_id": 1}
        session["shift_workers"] = []
        with pytest.raises(audit.ShiftRequiredError):
            audit.actors_from_request(workers_db)


def test_actors_from_request_laborant_with_missing_shift_key_raises(app_with_workers, workers_db):
    with app_with_workers.test_request_context():
        from flask import session
        session["user"] = {"login": "anna", "rola": "laborant", "worker_id": 1}
        # No shift_workers in session at all
        with pytest.raises(audit.ShiftRequiredError):
            audit.actors_from_request(workers_db)


def test_actors_from_request_laborant_kj_ignores_shift_returns_single(app_with_workers, workers_db):
    with app_with_workers.test_request_context():
        from flask import session
        session["user"] = {"login": "anna", "rola": "laborant_kj", "worker_id": 1}
        session["shift_workers"] = [1, 2, 3]
        result = audit.actors_from_request(workers_db)
    assert len(result) == 1
    assert result[0]["worker_id"] == 1
    assert result[0]["actor_rola"] == "laborant_kj"
```

- [ ] **Step 6: Run tests — verify failure**

Run: `pytest tests/test_audit_helper.py -k actors_from_request -v`

Expected: FAIL — `AttributeError: module ... has no attribute 'actors_from_request'`.

- [ ] **Step 7: Implement `actors_from_request`**

Append to `mbr/shared/audit.py`:

```python
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
```

- [ ] **Step 8: Run all actor tests — verify pass**

Run: `pytest tests/test_audit_helper.py -k actors -v`

Expected: 10 tests PASS.

- [ ] **Step 9: Commit**

```bash
git add mbr/shared/audit.py tests/test_audit_helper.py
git commit -m "feat(audit): actor resolution (system, explicit, from_request)

Three actor resolvers:
- actors_system(): virtual 'system' actor for migrations/archival
- actors_explicit(db, ids): snapshot login+rola from workers table;
  used by COA flow where form picks wystawil explicitly
- actors_from_request(db): reads Flask session; for rola='laborant'
  returns ALL shift_workers (laboranci w parach), raises
  ShiftRequiredError on empty shift; other roles return single session user

10 unit tests cover all role branches + shift edge cases.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-design.md"
```

---

## Task 6: `log_event()` — write path

**Files:**
- Modify: `mbr/shared/audit.py`
- Test: `tests/test_audit_helper.py`

Core write function. Accepts pre-resolved actors OR resolves from request. Writes audit_log row + audit_log_actors in same transaction.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_audit_helper.py`:

```python
# ---------- log_event ----------

@pytest.fixture
def audit_db(workers_db):
    """Extend workers_db with audit_log + audit_log_actors tables."""
    workers_db.executescript("""
        CREATE TABLE audit_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            dt              TEXT NOT NULL,
            event_type      TEXT NOT NULL,
            entity_type     TEXT,
            entity_id       INTEGER,
            entity_label    TEXT,
            diff_json       TEXT,
            payload_json    TEXT,
            context_json    TEXT,
            request_id      TEXT,
            ip              TEXT,
            user_agent      TEXT,
            result          TEXT NOT NULL DEFAULT 'ok'
        );
        CREATE TABLE audit_log_actors (
            audit_id        INTEGER NOT NULL REFERENCES audit_log(id) ON DELETE CASCADE,
            worker_id       INTEGER,
            actor_login     TEXT NOT NULL,
            actor_rola      TEXT NOT NULL,
            PRIMARY KEY (audit_id, worker_id, actor_login)
        );
    """)
    workers_db.commit()
    return workers_db


def test_log_event_writes_row_with_system_actor(audit_db):
    audit_id = audit.log_event(
        audit.EVENT_SYSTEM_MIGRATION_APPLIED,
        entity_type=None,
        entity_id=None,
        payload={"migration": "audit_log_v2"},
        actors=audit.actors_system(),
        db=audit_db,
    )
    assert isinstance(audit_id, int)
    assert audit_id > 0

    row = audit_db.execute("SELECT * FROM audit_log WHERE id=?", (audit_id,)).fetchone()
    assert row["event_type"] == "system.migration.applied"
    assert row["entity_type"] is None
    assert row["result"] == "ok"
    assert row["dt"] is not None
    assert json.loads(row["payload_json"])["migration"] == "audit_log_v2"

    actors = audit_db.execute(
        "SELECT worker_id, actor_login, actor_rola FROM audit_log_actors WHERE audit_id=?",
        (audit_id,)
    ).fetchall()
    assert len(actors) == 1
    assert actors[0]["worker_id"] is None
    assert actors[0]["actor_login"] == "system"


def test_log_event_writes_multiple_actors(audit_db):
    audit_id = audit.log_event(
        audit.EVENT_EBR_WYNIK_SAVED,
        entity_type="ebr",
        entity_id=42,
        entity_label="Szarża 2026/42",
        diff=[{"pole": "temperatura", "stara": 85, "nowa": 87}],
        actors=[
            {"worker_id": 1, "actor_login": "anna", "actor_rola": "laborant"},
            {"worker_id": 2, "actor_login": "maria", "actor_rola": "laborant"},
        ],
        db=audit_db,
    )
    actors = audit_db.execute(
        "SELECT worker_id FROM audit_log_actors WHERE audit_id=? ORDER BY worker_id",
        (audit_id,),
    ).fetchall()
    assert [a["worker_id"] for a in actors] == [1, 2]


def test_log_event_serializes_diff_and_payload_as_json(audit_db):
    audit_id = audit.log_event(
        audit.EVENT_MBR_TEMPLATE_UPDATED,
        entity_type="mbr",
        entity_id=7,
        diff=[{"pole": "etapy_json", "stara": [{"s": 1}], "nowa": [{"s": 2}]}],
        payload={"reason": "recipe fix"},
        actors=audit.actors_system(),
        db=audit_db,
    )
    row = audit_db.execute(
        "SELECT diff_json, payload_json FROM audit_log WHERE id=?", (audit_id,)
    ).fetchone()
    diff = json.loads(row["diff_json"])
    assert diff[0]["nowa"] == [{"s": 2}]
    payload = json.loads(row["payload_json"])
    assert payload["reason"] == "recipe fix"


def test_log_event_accepts_result_error(audit_db):
    """auth.login with result='error' for failed login attempts."""
    audit_id = audit.log_event(
        audit.EVENT_AUTH_LOGIN,
        payload={"attempted_login": "ghost"},
        result="error",
        actors=[{"worker_id": None, "actor_login": "ghost", "actor_rola": "unknown"}],
        db=audit_db,
    )
    row = audit_db.execute("SELECT result FROM audit_log WHERE id=?", (audit_id,)).fetchone()
    assert row["result"] == "error"


def test_log_event_resolves_actors_from_request_when_not_provided(audit_db):
    """If `actors=` not passed, helper resolves from Flask session."""
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context():
        from flask import session, g
        session["user"] = {"login": "jan", "rola": "technolog", "worker_id": 3}
        g.audit_request_id = "req-abc-123"

        audit_id = audit.log_event(
            audit.EVENT_MBR_TEMPLATE_CREATED,
            entity_type="mbr",
            entity_id=1,
            db=audit_db,
        )

    row = audit_db.execute(
        "SELECT request_id FROM audit_log WHERE id=?", (audit_id,)
    ).fetchone()
    assert row["request_id"] == "req-abc-123"

    actors = audit_db.execute(
        "SELECT worker_id, actor_login FROM audit_log_actors WHERE audit_id=?",
        (audit_id,),
    ).fetchall()
    assert len(actors) == 1
    assert actors[0]["worker_id"] == 3


def test_log_event_writes_in_caller_transaction_rollback_removes_both(audit_db):
    """If caller rolls back, audit row AND actor row must also roll back."""
    audit_db.execute("BEGIN")
    audit_id = audit.log_event(
        audit.EVENT_WORKER_CREATED,
        entity_type="worker",
        entity_id=999,
        actors=audit.actors_system(),
        db=audit_db,
    )
    # Simulate business-logic failure → rollback
    audit_db.rollback()

    rows = audit_db.execute(
        "SELECT COUNT(*) FROM audit_log WHERE id=?", (audit_id,)
    ).fetchone()[0]
    actors = audit_db.execute(
        "SELECT COUNT(*) FROM audit_log_actors WHERE audit_id=?", (audit_id,)
    ).fetchone()[0]
    assert rows == 0
    assert actors == 0
```

- [ ] **Step 2: Run tests — verify failure**

Run: `pytest tests/test_audit_helper.py -k log_event -v`

Expected: FAIL — `AttributeError: module ... has no attribute 'log_event'`.

- [ ] **Step 3: Implement `log_event`**

Append to `mbr/shared/audit.py`:

```python
# =========================================================================
# Write path
# =========================================================================

import json as _json
from datetime import datetime as _dt


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
        request_id = getattr(g, "audit_request_id", None)
        ip = request.headers.get("X-Forwarded-For", request.remote_addr) if request else None
        if ip and "," in ip:
            ip = ip.split(",")[0].strip()
        user_agent = request.headers.get("User-Agent") if request else None
    except (RuntimeError, ImportError):
        # No Flask app / request context — e.g. migrations, startup
        pass

    dt = _dt.utcnow().isoformat()

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
```

- [ ] **Step 4: Run tests — verify pass**

Run: `pytest tests/test_audit_helper.py -k log_event -v`

Expected: 6 tests PASS.

- [ ] **Step 5: Run entire audit helper test file**

Run: `pytest tests/test_audit_helper.py -v`

Expected: All tests (all 6+4+10+6 ≈ 26) PASS.

- [ ] **Step 6: Commit**

```bash
git add mbr/shared/audit.py tests/test_audit_helper.py
git commit -m "feat(audit): log_event() write path + full unit test coverage

log_event() writes one audit_log row + N audit_log_actors rows atomically
in the caller's transaction. Auto-resolves actors from Flask session if
not passed explicitly. Picks up request_id/ip/user_agent from Flask g
and request when available; gracefully degrades outside request context
(for migrations/startup).

Tests cover:
- system actor, multi-actor, JSON serialization of diff/payload
- result='error' (failed login), actor auto-resolution from session
- transaction semantics — caller rollback removes audit row AND actors

Ref: docs/superpowers/specs/2026-04-11-audit-trail-design.md"
```

---

## Task 7: Flask wiring — `before_request` + `errorhandler`

**Files:**
- Modify: `mbr/app.py` (inside `create_app()`)
- Test: `tests/test_audit_helper.py` (integration test with real Flask app)

Wire the helper into the app: each request gets a UUID in `g.audit_request_id`, and `ShiftRequiredError` maps to HTTP 400 JSON.

- [ ] **Step 1: Write failing integration test**

Append to `tests/test_audit_helper.py`:

```python
# ---------- Flask wiring ----------

def test_before_request_sets_unique_audit_request_id(monkeypatch, tmp_path):
    """Each Flask request gets its own UUID in g.audit_request_id."""
    # Point DB to a temp file so create_app() can init tables without clobbering real data
    import mbr.db as mbr_db
    monkeypatch.setattr(mbr_db, "DB_PATH", tmp_path / "test.sqlite")

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True

    captured = []
    @app.route("/__probe__")
    def _probe():
        from flask import g
        captured.append(g.audit_request_id)
        return "ok"

    client = app.test_client()
    client.get("/__probe__")
    client.get("/__probe__")

    assert len(captured) == 2
    assert captured[0] is not None
    assert captured[1] is not None
    assert captured[0] != captured[1]  # unique per request


def test_shift_required_error_returns_http_400_json(monkeypatch, tmp_path):
    """ShiftRequiredError raised in a route → HTTP 400 with {"error": "shift_required"}."""
    import mbr.db as mbr_db
    monkeypatch.setattr(mbr_db, "DB_PATH", tmp_path / "test.sqlite")

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True

    @app.route("/__probe_shift__")
    def _probe_shift():
        raise audit.ShiftRequiredError()

    client = app.test_client()
    resp = client.get("/__probe_shift__")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body == {"error": "shift_required"}
```

- [ ] **Step 2: Run tests — verify failure**

Run: `pytest tests/test_audit_helper.py -k "before_request or shift_required_error_returns" -v`

Expected: FAIL. `test_before_request_sets_unique_audit_request_id` will fail with `AttributeError: '_AppCtxGlobals' object has no attribute 'audit_request_id'`; `test_shift_required_error_returns_http_400_json` will fail because the unhandled exception returns a 500 HTML page instead of JSON 400.

- [ ] **Step 3: Wire `before_request` + `errorhandler` in `mbr/app.py`**

Edit `mbr/app.py`. After the `cache_control` after_request block (around line 24), add:

```python
    # Audit trail: per-request UUID + ShiftRequiredError → 400 JSON
    import uuid
    from flask import g, jsonify as _jsonify
    from mbr.shared.audit import ShiftRequiredError

    @app.before_request
    def _audit_request_id():
        g.audit_request_id = str(uuid.uuid4())

    @app.errorhandler(ShiftRequiredError)
    def _audit_shift_required(e):
        return _jsonify({"error": "shift_required"}), 400
```

Place these lines immediately after the existing `cache_control` function and before the `# Shared: filters, context processor` comment.

- [ ] **Step 4: Run tests — verify pass**

Run: `pytest tests/test_audit_helper.py -k "before_request or shift_required_error_returns" -v`

Expected: 2 tests PASS.

- [ ] **Step 5: Run whole test file once more to catch regressions**

Run: `pytest tests/test_audit_helper.py -v`

Expected: All tests PASS.

- [ ] **Step 6: Run full test suite — nothing else broke**

Run: `pytest 2>&1 | tail -20`

Expected: All tests pass. (If test_app.py or similar already checks something about `create_app()`, they should still work.)

- [ ] **Step 7: Commit**

```bash
git add mbr/app.py tests/test_audit_helper.py
git commit -m "feat(audit): wire helper into Flask app factory

create_app() gains:
- before_request hook setting g.audit_request_id (UUID per request)
  — so log_event() can correlate entries from one submit
- errorhandler for ShiftRequiredError → HTTP 400 {'error':'shift_required'}
  — front-end shows 'Potwierdź zmianę' modal

Integration tests verify unique request IDs and 400 mapping with a
temp DB so create_app() can initialize tables safely.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-design.md"
```

---

## Task 8: End-to-end smoke test + Phase 1 close-out

**Files:**
- Test: `tests/test_audit_helper.py`

One test that exercises the full write path through a real Flask route: session user → `log_event()` via `actors_from_request` → DB write → read back.

- [ ] **Step 1: Write the smoke test**

Append to `tests/test_audit_helper.py`:

```python
# ---------- Smoke test: full write path through a real Flask route ----------

def test_smoke_log_event_through_flask_route(monkeypatch, tmp_path):
    """Real Flask route calls log_event(); verify row landed with correct
    request_id, actors, and serialized payload."""
    import mbr.db as mbr_db
    db_path = tmp_path / "smoke.sqlite"
    monkeypatch.setattr(mbr_db, "DB_PATH", db_path)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True

    # Seed one worker so actors_from_request can resolve the session user.
    with mbr_db.db_session() as db:
        db.execute(
            "INSERT INTO workers (imie, nazwisko, nickname, inicjaly, login, rola) VALUES (?,?,?,?,?,?)",
            ("Test", "User", "TU", "TU", "tu", "technolog"),
        )
        db.commit()
        worker_id = db.execute("SELECT id FROM workers WHERE login='tu'").fetchone()[0]

    @app.route("/__probe_log__", methods=["POST"])
    def _probe_log():
        from flask import session
        from mbr.db import db_session as _ds
        session["user"] = {"login": "tu", "rola": "technolog", "worker_id": worker_id}
        with _ds() as db:
            aid = audit.log_event(
                audit.EVENT_MBR_TEMPLATE_UPDATED,
                entity_type="mbr",
                entity_id=123,
                entity_label="K40GLO v3",
                diff=[{"pole": "etapy_json", "stara": "old", "nowa": "new"}],
                db=db,
            )
            db.commit()
        return {"id": aid}

    client = app.test_client()
    resp = client.post("/__probe_log__")
    assert resp.status_code == 200
    audit_id = resp.get_json()["id"]

    with mbr_db.db_session() as db:
        row = db.execute(
            "SELECT event_type, entity_type, entity_id, entity_label, request_id FROM audit_log WHERE id=?",
            (audit_id,),
        ).fetchone()
        assert row["event_type"] == "mbr.template.updated"
        assert row["entity_type"] == "mbr"
        assert row["entity_id"] == 123
        assert row["entity_label"] == "K40GLO v3"
        assert row["request_id"] is not None

        actors = db.execute(
            "SELECT worker_id, actor_login, actor_rola FROM audit_log_actors WHERE audit_id=?",
            (audit_id,),
        ).fetchall()
        assert len(actors) == 1
        assert actors[0]["worker_id"] == worker_id
        assert actors[0]["actor_login"] == "tu"
        assert actors[0]["actor_rola"] == "technolog"
```

- [ ] **Step 2: Run the smoke test**

Run: `pytest tests/test_audit_helper.py::test_smoke_log_event_through_flask_route -v`

Expected: PASS. If it fails, most likely causes:
- `init_mbr_tables()` didn't create the new schema → check Task 1 landed correctly
- `login` column missing on fresh workers table → check `mbr/models.py` workers DDL includes it
- Session cookie not persisted — Flask test client handles this automatically, but if the `session["user"]` set inside the route doesn't propagate, switch to `client.session_transaction()` to set it before `client.post(...)`.

- [ ] **Step 3: Run entire project test suite**

Run: `pytest 2>&1 | tail -30`

Expected: All tests pass across `tests/` (existing + new). If any pre-existing test failed because of the schema change, this is the moment to fix it.

- [ ] **Step 4: Manual verification on real DB (optional but recommended)**

Run against a copy of the real DB (never touch `data/batch_db.sqlite` directly):

```bash
cp data/batch_db.sqlite /tmp/audit_migration_test.sqlite
python scripts/migrate_audit_log_v2.py --db /tmp/audit_migration_test.sqlite --dry-run
python scripts/migrate_audit_log_v2.py --db /tmp/audit_migration_test.sqlite
sqlite3 /tmp/audit_migration_test.sqlite "SELECT COUNT(*) FROM audit_log; SELECT COUNT(*) FROM audit_log_v1; SELECT COUNT(*) FROM audit_log_actors;"
```

Expected: `audit_log` count matches `audit_log_v1` count (backfill preserved all rows), `audit_log_actors` count ≥ `audit_log` count.

If migration fails, read the error, fix the script, re-run the test suite, commit fix.

- [ ] **Step 5: Commit smoke test**

```bash
git add tests/test_audit_helper.py
git commit -m "test(audit): smoke test — full write path through Flask route

End-to-end verification: real app factory + real DB + POST request →
log_event() via session-resolved actors → row lands with request_id,
entity fields, serialized diff, and actor snapshot.

Phase 1 (infrastructure) complete. No integration in blueprints yet;
that's Phases 3-6.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-design.md"
```

- [ ] **Step 6: Write Phase 1 summary in spec document**

Append a section to `docs/superpowers/specs/2026-04-11-audit-trail-design.md`:

```markdown

---

## Phase 1 Status (implementation)

**Completed:** 2026-04-11

- Schema: `audit_log` + `audit_log_actors` + 5 indexes in `init_mbr_tables()`
- Migration script: `scripts/migrate_audit_log_v2.py` — idempotent, dry-run, backfill legacy rows
- Helper: `mbr/shared/audit.py` — 50 event_type constants, `ShiftRequiredError`, `diff_fields()`, `actors_system/_explicit/_from_request()`, `log_event()`
- Flask wiring: `before_request` → `g.audit_request_id`, `errorhandler(ShiftRequiredError)` → 400 JSON
- Tests: `tests/test_audit_helper.py` (unit + integration + smoke), `tests/test_migrate_audit_log_v2.py` (migration)

**Not yet integrated:** Zero call sites in blueprints. Next: Phase 2 (admin panel) or Phase 3 (auth + workers integration).
```

- [ ] **Step 7: Commit spec update**

```bash
git add docs/superpowers/specs/2026-04-11-audit-trail-design.md
git commit -m "docs(audit): mark Phase 1 (infrastructure) complete

Ref: docs/superpowers/plans/2026-04-11-audit-trail-phase1.md"
```

---

## Phase 1 Done Definition

After Task 8:

- [ ] `mbr/shared/audit.py` exists with event constants, exception, diff_fields, actors_*, log_event
- [ ] `mbr/app.py` sets `g.audit_request_id` per request and handles `ShiftRequiredError` → 400 JSON
- [ ] `mbr/models.py::init_mbr_tables()` creates new `audit_log` + `audit_log_actors` + indexes on fresh installs
- [ ] `scripts/migrate_audit_log_v2.py` exists, idempotent, dry-run support, tests pass
- [ ] `tests/test_audit_helper.py` has ≥25 passing tests covering unit + integration + smoke
- [ ] `tests/test_migrate_audit_log_v2.py` has ≥5 passing tests
- [ ] Full `pytest` run is green
- [ ] **No** `log_event()` call in any existing blueprint route (Phase 1 is infra-only)
- [ ] Legacy call sites in `laborant/models.py:481` and `etapy/models.py:45` neutralized with TODO comments (or left untouched if Task 1 Step 3 found they didn't block tests)

## Deployment note

Before running Phase 1 on production:

1. `sudo systemctl stop lims`
2. Backup: `cp data/batch_db.sqlite data/batch_db.sqlite.bak-phase1-$(date +%F)`
3. Dry-run: `python scripts/migrate_audit_log_v2.py --db data/batch_db.sqlite --dry-run`
4. Inspect summary, proceed if numbers look sane
5. Real run: `python scripts/migrate_audit_log_v2.py --db data/batch_db.sqlite`
6. Verify: `sqlite3 data/batch_db.sqlite "SELECT COUNT(*) FROM audit_log; SELECT COUNT(*) FROM audit_log_v1;"` — counts should match
7. `sudo systemctl start lims`
8. Smoke test: hit a non-mutating endpoint, verify app comes up without errors
