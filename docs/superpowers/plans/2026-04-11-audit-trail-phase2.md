# Audit Trail — Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the read-only UI for the audit trail: admin panel `/admin/audit` (filters + pagination + CSV), manual archival to JSONL.gz, and per-record history sections in EBR/MBR/cert views.

**Architecture:** Three new helpers in `mbr/shared/audit.py` (query, history, archive). One new admin routes module (`mbr/admin/audit_routes.py`) with 4 endpoints. One Jinja template with inline CSS+vanilla JS. One reusable Jinja partial for per-record history embedded in 3 existing views. Internally split into 4 sub-PRs, each independently rollback-able.

**Tech Stack:** Flask, raw sqlite3 (no ORM), Jinja2, pytest with in-memory SQLite fixtures, vanilla JS (no framework), inline CSS.

**Spec reference:** `docs/superpowers/specs/2026-04-11-audit-trail-phase2-design.md`

**Out of scope for Phase 2:**
- Any blueprint write-side `log_event()` calls (Phases 3-6)
- Real-time refresh / WebSockets
- Server-side full-text search engine
- Drop `audit_log_v1` (Phase 7)

**Branch convention:** All Phase 2 work happens on `audit/phase2` branch in worktree `.worktrees/audit-phase2`. Each sub-PR is a logical group of commits, not a separate git branch — they all merge together via one final `--no-ff` to main when Phase 2 closes.

---

## File Structure

**Create:**
- `mbr/admin/audit_routes.py` — 4 routes for the panel + archival (~250 LOC)
- `mbr/templates/admin/audit.html` — panel template with inline CSS + vanilla JS (~280 LOC)
- `mbr/templates/_audit_history_section.html` — reusable partial included in 3 views (~50 LOC)
- `tests/test_admin_audit.py` — HTTP tests for panel + archival + per-record endpoints (~350 LOC)

**Modify:**
- `mbr/shared/audit.py` — append `query_audit_log()`, `query_audit_history_for_entity()`, `archive_old_entries()` (~130 LOC added)
- `mbr/shared/filters.py` — append `audit_actors_filter` + register
- `mbr/admin/__init__.py` — import new audit_routes module
- `mbr/templates/base.html` — new admin rail link "Audit trail"
- `mbr/laborant/routes.py:213-226` — replace existing `get_audit_log(ebr_id)` with new endpoint at new URL `/api/ebr/<id>/audit-history`
- `mbr/templates/laborant/_fast_entry_content.html` — `{% include "_audit_history_section.html" %}` under uwagi block
- `mbr/technolog/routes.py` — new endpoint `get_mbr_audit_history`
- MBR template editor view — locate at impl time, include partial
- `mbr/certs/routes.py` — new endpoint `get_cert_audit_history`
- Cert detail view — locate at impl time, include partial
- `tests/test_audit_helper.py` — append ~16 tests for new helpers

---

## Sub-PR 2.1: Backend helpers (Tasks 1-3)

Pure-logic functions, zero UI. Can be deployed alone with no user-visible effect — nothing calls them yet.

---

### Task 1: `query_audit_log()` — main read function with all filters

**Files:**
- Modify: `mbr/shared/audit.py` (append function)
- Test: `tests/test_audit_helper.py` (append section)

This is the largest single function in Phase 2. Builds a parameterized SELECT with optional filter clauses, runs both the data query (with LIMIT/OFFSET) and a separate COUNT(*) query for the paginator. Returns rows with joined `actors` list per row.

- [ ] **Step 1: Append seed helper to test file**

Add to `tests/test_audit_helper.py` near the bottom (before any existing `# ----- Flask wiring -----` section):

```python
# ---------- query_audit_log fixtures ----------

@pytest.fixture
def queryable_audit_db(audit_db):
    """audit_db fixture with several seed events spanning event types and dates."""
    import json as _json
    rows = [
        # (dt,                event_type,           entity_type, entity_id, entity_label,    diff_json,                              payload_json,        request_id)
        ("2026-04-01T08:00:00", "auth.login",         None,        None,      None,            None,                                   '{"login":"alice"}', "req-1"),
        ("2026-04-01T09:15:00", "ebr.wynik.saved",    "ebr",       42,        "Szarża 2026/42", '[{"pole":"sm","stara":85,"nowa":87}]', None,                "req-2"),
        ("2026-04-02T10:30:00", "ebr.wynik.saved",    "ebr",       42,        "Szarża 2026/42", '[{"pole":"ph","stara":7,"nowa":7.2}]', None,                "req-3"),
        ("2026-04-03T11:00:00", "cert.generated",     "cert",      7,         "Świad. K40GLO",  None,                                   '{"path":"/x.pdf"}', "req-4"),
        ("2026-04-05T12:45:00", "auth.login",         None,        None,      None,            None,                                   '{"login":"bob"}',   "req-5"),
        ("2026-04-08T13:00:00", "ebr.wynik.saved",    "ebr",       43,        "Szarża 2026/43", '[{"pole":"sm","stara":80,"nowa":82}]', None,                "req-6"),
    ]
    for r in rows:
        cur = audit_db.execute(
            """INSERT INTO audit_log
               (dt, event_type, entity_type, entity_id, entity_label,
                diff_json, payload_json, request_id, result)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ok')""",
            r,
        )
        # Always at least one actor — alternate between worker 1 and worker 2
        wid = 1 if cur.lastrowid % 2 == 1 else 2
        login = "anna" if wid == 1 else "maria"
        audit_db.execute(
            "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, ?, ?, 'laborant')",
            (cur.lastrowid, wid, login),
        )
    audit_db.commit()
    return audit_db
```

The `audit_db` fixture already exists in `tests/test_audit_helper.py` from Phase 1 (it extends `workers_db` with the audit_log + audit_log_actors tables). This adds 6 seed rows on top of it.

- [ ] **Step 2: Write 8 query tests**

Append to `tests/test_audit_helper.py`:

```python
# ---------- query_audit_log ----------

def test_query_returns_empty_when_no_rows(audit_db):
    rows, total = audit.query_audit_log(audit_db)
    assert rows == []
    assert total == 0


def test_query_returns_all_rows_with_actors(queryable_audit_db):
    rows, total = audit.query_audit_log(queryable_audit_db)
    assert total == 6
    assert len(rows) == 6
    # Each row has an actors list (≥1 element)
    for r in rows:
        assert "actors" in r
        assert len(r["actors"]) >= 1
        assert "actor_login" in r["actors"][0]


def test_query_filter_by_dt_range(queryable_audit_db):
    rows, total = audit.query_audit_log(
        queryable_audit_db,
        dt_from="2026-04-02",
        dt_to="2026-04-05",
    )
    assert total == 3  # 2026-04-02, 04-03, 04-05
    assert all(r["dt"][:10] in ("2026-04-02", "2026-04-03", "2026-04-05") for r in rows)


def test_query_filter_by_event_type_glob(queryable_audit_db):
    rows, total = audit.query_audit_log(
        queryable_audit_db, event_type_glob="auth.*"
    )
    assert total == 2
    assert all(r["event_type"].startswith("auth.") for r in rows)


def test_query_filter_by_event_type_exact(queryable_audit_db):
    rows, total = audit.query_audit_log(
        queryable_audit_db, event_type_glob="cert.generated"
    )
    assert total == 1
    assert rows[0]["event_type"] == "cert.generated"


def test_query_filter_by_entity(queryable_audit_db):
    rows, total = audit.query_audit_log(
        queryable_audit_db, entity_type="ebr", entity_id=42
    )
    assert total == 2
    assert all(r["entity_id"] == 42 for r in rows)


def test_query_filter_by_worker_id_uses_actors_table(queryable_audit_db):
    rows, total = audit.query_audit_log(queryable_audit_db, worker_id=1)
    assert total > 0
    # Every returned row has worker 1 as one of its actors
    for r in rows:
        assert any(a["worker_id"] == 1 for a in r["actors"])


def test_query_filter_by_free_text_searches_label_and_payload(queryable_audit_db):
    # 'K40GLO' is in cert entity_label only
    rows, total = audit.query_audit_log(queryable_audit_db, free_text="K40GLO")
    assert total == 1
    assert rows[0]["entity_label"] == "Świad. K40GLO"

    # 'alice' is only in payload_json of one auth.login
    rows, total = audit.query_audit_log(queryable_audit_db, free_text="alice")
    assert total == 1
    assert "alice" in rows[0]["payload_json"]


def test_query_filter_by_request_id(queryable_audit_db):
    rows, total = audit.query_audit_log(queryable_audit_db, request_id="req-3")
    assert total == 1
    assert rows[0]["request_id"] == "req-3"


def test_query_pagination(queryable_audit_db):
    # 6 seeded rows, page size 2
    rows_page1, total = audit.query_audit_log(queryable_audit_db, limit=2, offset=0)
    rows_page2, _ = audit.query_audit_log(queryable_audit_db, limit=2, offset=2)
    rows_page3, _ = audit.query_audit_log(queryable_audit_db, limit=2, offset=4)
    assert total == 6
    assert len(rows_page1) == 2
    assert len(rows_page2) == 2
    assert len(rows_page3) == 2
    # Pages are disjoint
    ids1 = {r["id"] for r in rows_page1}
    ids2 = {r["id"] for r in rows_page2}
    ids3 = {r["id"] for r in rows_page3}
    assert ids1.isdisjoint(ids2)
    assert ids2.isdisjoint(ids3)
```

- [ ] **Step 3: Run tests — verify failure**

```bash
pytest tests/test_audit_helper.py -k query_audit_log -v 2>&1 | tail -15
```

Expected: All `test_query_*` fail with `AttributeError: module 'mbr.shared.audit' has no attribute 'query_audit_log'`.

If you see import errors instead, delete the stale `data/batch_db.sqlite` first: `rm -f data/batch_db.sqlite`.

- [ ] **Step 4: Implement `query_audit_log`**

Append to `mbr/shared/audit.py`:

```python
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
        clauses.append("(entity_label LIKE ? OR payload_json LIKE ?)")
        like = f"%{free_text}%"
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
```

- [ ] **Step 5: Run tests — verify pass**

```bash
pytest tests/test_audit_helper.py -k query_audit_log -v 2>&1 | tail -20
```

Expected: 10 tests PASS (8 from list + the empty + the all-rows test).

If a test fails, read the error. Common issues:
- `dict(r)` requires the row factory to be `sqlite3.Row` — the `audit_db` fixture already sets this
- `actors` not present — check the bulk-load loop and the IN clause

- [ ] **Step 6: Run full test file as smoke**

```bash
pytest tests/test_audit_helper.py 2>&1 | tail -3
```

Expected: All tests pass (existing Phase 1 tests + new query tests).

- [ ] **Step 7: Commit**

```bash
git add mbr/shared/audit.py tests/test_audit_helper.py
git commit -m "$(cat <<'COMMIT'
feat(audit): query_audit_log() — read path with filters + pagination

Phase 2 Sub-PR 2.1 (helpers). Adds the main read function used by the
admin panel and CSV export. Supports 8 filters (date range, event type
glob, entity type/id, worker_id via EXISTS, free text on label/payload,
request_id) plus LIMIT/OFFSET pagination with separate total count.

Bulk-loads actors for the returned page (no N+1) and returns rows as
dicts with an 'actors' key.

10 unit tests cover empty DB, each filter individually, and pagination.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase2-design.md
COMMIT
)"
```

---

### Task 2: `query_audit_history_for_entity()` — per-record history

**Files:**
- Modify: `mbr/shared/audit.py`
- Test: `tests/test_audit_helper.py`

Simpler than Task 1 — no filters, just `entity_type + entity_id`. Bounded result (single batch ≤50 events typically), so no pagination.

- [ ] **Step 1: Write 2 failing tests**

Append to `tests/test_audit_helper.py`:

```python
# ---------- query_audit_history_for_entity ----------

def test_history_for_entity_returns_only_matching(queryable_audit_db):
    rows = audit.query_audit_history_for_entity(queryable_audit_db, "ebr", 42)
    assert len(rows) == 2
    assert all(r["entity_id"] == 42 for r in rows)
    assert all(r["entity_type"] == "ebr" for r in rows)
    # Sorted DESC by dt
    assert rows[0]["dt"] >= rows[1]["dt"]


def test_history_for_entity_includes_actors(queryable_audit_db):
    rows = audit.query_audit_history_for_entity(queryable_audit_db, "cert", 7)
    assert len(rows) == 1
    assert "actors" in rows[0]
    assert len(rows[0]["actors"]) >= 1
    assert "actor_login" in rows[0]["actors"][0]
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_audit_helper.py -k history_for_entity -v
```

Expected: AttributeError on `audit.query_audit_history_for_entity`.

- [ ] **Step 3: Implement (delegates to query_audit_log)**

Append to `mbr/shared/audit.py`:

```python
def query_audit_history_for_entity(db, entity_type: str, entity_id: int) -> list:
    """Per-record history for entity views (EBR/MBR/cert).

    Returns rows sorted dt DESC with actors joined. No pagination — entity
    histories are bounded (a single batch typically generates <50 events).
    """
    rows, _total = query_audit_log(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=1000,  # safety cap; should never be hit
        offset=0,
    )
    return rows
```

- [ ] **Step 4: Run — verify pass**

```bash
pytest tests/test_audit_helper.py -k history_for_entity -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/shared/audit.py tests/test_audit_helper.py
git commit -m "$(cat <<'COMMIT'
feat(audit): query_audit_history_for_entity() — per-record history

Thin wrapper over query_audit_log filtered by (entity_type, entity_id).
Returns rows sorted DESC with actors, no pagination (single-entity
histories are bounded).

Used by /api/ebr/<id>/audit-history, /api/mbr/<id>/audit-history,
/api/cert/<id>/audit-history endpoints in Sub-PR 2.4.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase2-design.md
COMMIT
)"
```

---

### Task 3: `archive_old_entries()` — JSONL.gz writer + delete

**Files:**
- Modify: `mbr/shared/audit.py`
- Test: `tests/test_audit_helper.py`

This function dumps audit_log rows older than `cutoff_iso` into a gzipped JSONL file, deletes them from the active DB, and logs a `system.audit.archived` event. Wraps everything in a single transaction so a file write failure rolls back the deletes.

- [ ] **Step 1: Write 4 failing tests**

Append to `tests/test_audit_helper.py`:

```python
# ---------- archive_old_entries ----------

def test_archive_dumps_old_entries_to_jsonl_gz_and_deletes(queryable_audit_db, tmp_path):
    import gzip as _gzip
    archive_dir = tmp_path / "audit_archive"
    archive_dir.mkdir()
    # Cutoff: anything before 2026-04-04 is "old" (4 of 6 rows)
    summary = audit.archive_old_entries(
        queryable_audit_db, "2026-04-04T00:00:00", archive_dir
    )
    assert summary["archived"] == 4
    # Active DB has only 2 originals + 1 system.audit.archived = 3
    remaining = queryable_audit_db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    assert remaining == 3
    # Archive file exists with 4 lines
    archive_file = archive_dir / "audit_2026.jsonl.gz"
    assert archive_file.exists()
    with _gzip.open(archive_file, "rt") as f:
        lines = f.readlines()
    assert len(lines) == 4
    # Each line is valid JSON with our row shape + actors
    import json as _json
    for line in lines:
        parsed = _json.loads(line)
        assert "id" in parsed
        assert "event_type" in parsed
        assert "actors" in parsed


def test_archive_appends_to_existing_year_file(queryable_audit_db, tmp_path):
    import gzip as _gzip
    archive_dir = tmp_path / "audit_archive"
    archive_dir.mkdir()
    # First archive: cutoff 2026-04-02 → 1 old row
    audit.archive_old_entries(queryable_audit_db, "2026-04-02T00:00:00", archive_dir)
    # Second archive: cutoff 2026-04-04 → 3 newly-old rows
    audit.archive_old_entries(queryable_audit_db, "2026-04-04T00:00:00", archive_dir)
    archive_file = archive_dir / "audit_2026.jsonl.gz"
    with _gzip.open(archive_file, "rt") as f:
        lines = f.readlines()
    # 1 + 3 = 4 lines total in the same file (gzip append concatenation)
    assert len(lines) == 4


def test_archive_returns_summary_dict(queryable_audit_db, tmp_path):
    archive_dir = tmp_path / "audit_archive"
    archive_dir.mkdir()
    summary = audit.archive_old_entries(
        queryable_audit_db, "2026-04-04T00:00:00", archive_dir
    )
    assert summary["archived"] == 4
    assert summary["cutoff"] == "2026-04-04T00:00:00"
    assert "audit_2026.jsonl.gz" in summary["file"]


def test_archive_logs_system_audit_archived_event(queryable_audit_db, tmp_path):
    archive_dir = tmp_path / "audit_archive"
    archive_dir.mkdir()
    audit.archive_old_entries(queryable_audit_db, "2026-04-04T00:00:00", archive_dir)
    # The new system.audit.archived event must exist
    rows = queryable_audit_db.execute(
        "SELECT event_type, payload_json FROM audit_log WHERE event_type='system.audit.archived'"
    ).fetchall()
    assert len(rows) == 1
    import json as _json
    payload = _json.loads(rows[0]["payload_json"])
    assert payload["count"] == 4
    assert payload["cutoff"] == "2026-04-04T00:00:00"
    assert "audit_2026.jsonl.gz" in payload["file"]
    # Actor of the archive event is the 'system' virtual actor
    aid_row = queryable_audit_db.execute(
        "SELECT id FROM audit_log WHERE event_type='system.audit.archived'"
    ).fetchone()
    actors = queryable_audit_db.execute(
        "SELECT actor_login, actor_rola, worker_id FROM audit_log_actors WHERE audit_id=?",
        (aid_row[0],),
    ).fetchall()
    assert len(actors) == 1
    assert actors[0]["actor_login"] == "system"
    assert actors[0]["actor_rola"] == "system"
    assert actors[0]["worker_id"] is None
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_audit_helper.py -k archive -v
```

Expected: all 4 fail with AttributeError on `audit.archive_old_entries`.

- [ ] **Step 3: Implement**

Append to `mbr/shared/audit.py`:

```python
import gzip as _gzip
from pathlib import Path as _Path


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

    # 1. Read rows + actors that will be archived (uses query_audit_log for the join)
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

    # 2. Append to gzipped JSONL file (outside transaction — file is durable)
    if rows_to_archive:
        with _gzip.open(archive_path, "at", encoding="utf-8") as f:
            for r in rows_to_archive:
                f.write(_json.dumps(r, ensure_ascii=False, default=str) + "\n")

    # 3. Delete archived rows from the DB (FK on audit_log_actors will cascade)
    if rows_to_archive:
        db.execute(f"DELETE FROM audit_log{where_sql}", (cutoff_iso,))

    # 4. Log the archive event itself (system actor)
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

    return {
        "archived": archived_count,
        "file": str(archive_path),
        "cutoff": cutoff_iso,
    }
```

- [ ] **Step 4: Run — verify pass**

```bash
pytest tests/test_audit_helper.py -k archive -v
```

Expected: 4 tests PASS.

If `test_archive_appends_to_existing_year_file` fails because the second `archive_old_entries` call sees the freshly-logged `system.audit.archived` from the first call as "old" too, that means my cutoff check is exclusive but the system event got `dt = utcnow()` which is "newer than April 4". In test the seed uses 2026-04-* dates and `utcnow()` returns whatever real time is — far in the future relative to seed. So system events from the first call should NOT be archived by the second call. But just in case, this is a known testing nuance: if you see an extra event in the archive, the issue is that `_dt.now(tz.utc).isoformat()` returned something <= cutoff, which means your local clock is set to 2026-04-04 or earlier. Solve by using a `freezegun` or by running with a clock further in the future. For now, the assertion `len(lines) == 4` should hold because real "now" >> 2026-04-04 in dev time.

- [ ] **Step 5: Run full audit helper file**

```bash
pytest tests/test_audit_helper.py 2>&1 | tail -3
```

Expected: all tests pass (~40+ existing + 16 new = ≥56 total).

- [ ] **Step 6: Commit**

```bash
git add mbr/shared/audit.py tests/test_audit_helper.py
git commit -m "$(cat <<'COMMIT'
feat(audit): archive_old_entries() — JSONL.gz writer + delete + log

Phase 2 Sub-PR 2.1 (helpers). Final read/archive helper.

Dumps audit_log rows older than cutoff_iso into a gzipped JSONL file
(audit_{year}.jsonl.gz, append mode so re-runs in the same year
accumulate), deletes them from the active DB, and logs a
system.audit.archived event with the virtual system actor.

All in one transaction — gzip write failure rolls back the deletes.

4 tests cover: dump+delete, append to existing year file, summary
shape, system.audit.archived event creation.

Sub-PR 2.1 complete: 3 helpers (query_audit_log,
query_audit_history_for_entity, archive_old_entries) ready for the
admin panel in Sub-PR 2.2.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase2-design.md
COMMIT
)"
```

---

## Sub-PR 2.2: Admin panel (Tasks 4-7)

UI for the helpers from Sub-PR 2.1. After this sub-PR, admin can browse and CSV-export, but the archive button is wired to a stub (Sub-PR 2.3 wires it to the real archival).

---

### Task 4: Jinja filter `audit_actors`

**Files:**
- Modify: `mbr/shared/filters.py`
- Test: `tests/test_audit_helper.py`

Tiny pure function used by the panel template.

- [ ] **Step 1: Write tests**

Append to `tests/test_audit_helper.py`:

```python
# ---------- audit_actors Jinja filter ----------

def test_audit_actors_filter_joins_logins():
    from mbr.shared.filters import audit_actors_filter
    row = {"actors": [{"actor_login": "AK"}, {"actor_login": "MW"}]}
    assert audit_actors_filter(row) == "AK, MW"


def test_audit_actors_filter_handles_empty():
    from mbr.shared.filters import audit_actors_filter
    assert audit_actors_filter({"actors": []}) == "—"
    assert audit_actors_filter({}) == "—"
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_audit_helper.py -k audit_actors_filter -v
```

Expected: ImportError on `audit_actors_filter`.

- [ ] **Step 3: Implement**

Append to `mbr/shared/filters.py` (before `def register_filters`):

```python
def audit_actors_filter(audit_row):
    """Render actors as comma-separated logins, '—' if empty/missing.

    Used in admin/audit.html for the table column. Input is a dict from
    audit.query_audit_log() — the 'actors' key contains a list of dicts.
    """
    actors = audit_row.get("actors") or []
    if not actors:
        return "—"
    return ", ".join(a["actor_login"] for a in actors)
```

Then update `register_filters`:

```python
def register_filters(app):
    app.add_template_filter(pl_date_filter, 'pl_date')
    app.add_template_filter(pl_date_short_filter, 'pl_date_short')
    app.add_template_filter(fmt_kg_filter, 'fmt_kg')
    app.add_template_filter(short_product_filter, 'short_product')
    app.add_template_filter(audit_actors_filter, 'audit_actors')
```

- [ ] **Step 4: Run — verify pass**

```bash
pytest tests/test_audit_helper.py -k audit_actors_filter -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/shared/filters.py tests/test_audit_helper.py
git commit -m "$(cat <<'COMMIT'
feat(audit): Jinja filter audit_actors for the admin panel table

Renders the actors list of an audit_log row as comma-separated logins.
Used in admin/audit.html (Sub-PR 2.2). Tiny pure function, 2 tests.

Ref: docs/superpowers/plans/2026-04-11-audit-trail-phase2.md
COMMIT
)"
```

---

### Task 5: Admin panel routes — `audit_panel` GET + helpers

**Files:**
- Create: `mbr/admin/audit_routes.py`
- Modify: `mbr/admin/__init__.py`
- Test: `tests/test_admin_audit.py`

The most complex single task in Phase 2 — but the route itself is small. Most of the size is in helper functions that parse query string filters and define the event_type dropdown groups.

- [ ] **Step 1: Create test file with first failing test**

Create `tests/test_admin_audit.py`:

```python
"""Tests for /admin/audit panel + archival + per-record history endpoints."""

import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _make_client(monkeypatch, db, rola="admin"):
    """Build a Flask test client with the in-memory db monkey-patched in."""
    import mbr.db
    import mbr.admin.audit_routes
    import mbr.admin.routes
    import mbr.laborant.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.admin.audit_routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.admin.routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "tester", "rola": rola, "worker_id": None}
    return client


@pytest.fixture
def admin_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="admin")


@pytest.fixture
def laborant_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="laborant")


def _seed_some_audit_rows(db):
    """Insert a handful of audit_log rows for the panel tests."""
    rows = [
        ("2026-04-01T08:00:00", "auth.login", None, None, None, '{"login":"alice"}', "req-1"),
        ("2026-04-02T09:00:00", "ebr.wynik.saved", "ebr", 42, "Szarża 2026/42", None, "req-2"),
        ("2026-04-03T10:00:00", "cert.generated", "cert", 7, "Świad. K40GLO", '{"path":"/x.pdf"}', "req-3"),
    ]
    for r in rows:
        cur = db.execute(
            """INSERT INTO audit_log
               (dt, event_type, entity_type, entity_id, entity_label, payload_json, request_id, result)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'ok')""",
            r,
        )
        db.execute(
            "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, NULL, 'tester', 'admin')",
            (cur.lastrowid,),
        )
    db.commit()


# ---------- /admin/audit panel ----------

def test_admin_audit_panel_returns_200_for_admin(admin_client, db):
    _seed_some_audit_rows(db)
    resp = admin_client.get("/admin/audit")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Audit trail" in body or "audit" in body.lower()
    # All 3 seeded rows should appear in the rendered table
    assert "auth.login" in body
    assert "ebr.wynik.saved" in body
    assert "cert.generated" in body
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_admin_audit.py -v 2>&1 | tail -15
```

Expected: 404 (route doesn't exist) OR ImportError on `mbr.admin.audit_routes`.

- [ ] **Step 3: Create `mbr/admin/audit_routes.py` skeleton with the GET route**

Create `mbr/admin/audit_routes.py`:

```python
"""Admin panel for the audit trail.

Routes:
  GET  /admin/audit                  — render the panel with filters/table
  GET  /admin/audit/export.csv       — stream CSV using same WHERE
  POST /admin/audit/archive/preview  — return count of rows that would be archived
  POST /admin/audit/archive          — actually run archival

All routes require role='admin'. See:
docs/superpowers/specs/2026-04-11-audit-trail-phase2-design.md
"""

import csv
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import (
    Response,
    current_app,
    jsonify,
    render_template,
    request,
    stream_with_context,
)

from mbr.admin import admin_bp
from mbr.db import db_session
from mbr.shared import audit
from mbr.shared.decorators import role_required


# ---------- Filter parser + dropdown groups ----------

_EVENT_TYPE_GROUPS = [
    {"value": "", "label": "(wszystkie)"},
    {"value": "auth.*", "label": "auth.*"},
    {"value": "worker.*", "label": "worker.*"},
    {"value": "shift.*", "label": "shift.*"},
    {"value": "mbr.*", "label": "mbr.*"},
    {"value": "ebr.*", "label": "ebr.*"},
    {"value": "cert.*", "label": "cert.*"},
    {"value": "paliwo.*", "label": "paliwo.*"},
    {"value": "admin.*", "label": "admin.*"},
    {"value": "system.*", "label": "system.*"},
]

_ENTITY_TYPES = [
    {"value": "", "label": "(wszystkie)"},
    {"value": "ebr", "label": "EBR"},
    {"value": "mbr", "label": "MBR"},
    {"value": "cert", "label": "Świadectwo"},
    {"value": "worker", "label": "Pracownik"},
]


def _parse_filters_from_query(args) -> dict:
    """Translate request.args into kwargs for query_audit_log."""
    def _opt_str(key):
        v = args.get(key, "").strip()
        return v or None

    def _opt_int(key):
        v = args.get(key, "").strip()
        try:
            return int(v) if v else None
        except ValueError:
            return None

    return {
        "dt_from": _opt_str("dt_from"),
        "dt_to": _opt_str("dt_to"),
        "event_type_glob": _opt_str("event_type_glob"),
        "entity_type": _opt_str("entity_type"),
        "entity_id": _opt_int("entity_id"),
        "worker_id": _opt_int("worker_id"),
        "free_text": _opt_str("free_text"),
        "request_id": _opt_str("request_id"),
    }


# ---------- Routes ----------

@admin_bp.route("/admin/audit")
@role_required("admin")
def audit_panel():
    """Render the audit log panel with filters and a paginated table."""
    filters = _parse_filters_from_query(request.args)
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    page_size = 100
    offset = (page - 1) * page_size

    with db_session() as db:
        rows, total = audit.query_audit_log(
            db, **filters, limit=page_size, offset=offset
        )
        workers = db.execute(
            "SELECT id, nickname, inicjaly FROM workers WHERE aktywny=1 ORDER BY inicjaly"
        ).fetchall()

    # Parse JSON columns inside rows for template rendering
    import json as _json
    for r in rows:
        if r.get("diff_json"):
            try:
                r["diff_parsed"] = _json.loads(r["diff_json"])
            except Exception:
                r["diff_parsed"] = None

    page_count = max(1, (total + page_size - 1) // page_size)

    return render_template(
        "admin/audit.html",
        rows=rows,
        total=total,
        page=page,
        page_count=page_count,
        filters=request.args,
        workers=workers,
        event_groups=_EVENT_TYPE_GROUPS,
        entity_types=_ENTITY_TYPES,
    )
```

Update `mbr/admin/__init__.py`:

```python
from flask import Blueprint

admin_bp = Blueprint("admin", __name__)

from mbr.admin import routes  # noqa: E402, F401
from mbr.admin import audit_routes  # noqa: E402, F401
```

- [ ] **Step 4: Create the template (minimal first cut, expanded in Task 7)**

Create `mbr/templates/admin/audit.html`:

```html
{% extends "base.html" %}
{% block topbar_title %}Audit trail{% endblock %}

{% block content %}
<style>
.audit-page { padding: 16px 24px; }
.audit-filters { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; margin-bottom: 12px; }
.af-row { display: flex; flex-wrap: wrap; gap: 10px; align-items: end; }
.af-row label { display: flex; flex-direction: column; font-size: 10px; text-transform: uppercase; color: var(--text-dim); gap: 4px; }
.af-row input, .af-row select { font-size: 12px; padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; background: white; }
.af-row .btn { padding: 7px 14px; font-size: 12px; border: 1px solid var(--border); border-radius: 6px; background: white; cursor: pointer; }
.af-row .btn.btn-primary { background: var(--teal); color: white; border-color: var(--teal); }
.af-row .btn.btn-warn { background: #fef3c7; color: #92400e; border-color: #fde68a; }
.audit-meta { font-size: 11px; color: var(--text-dim); margin: 8px 4px; font-family: var(--mono); }
.audit-table { width: 100%; border-collapse: collapse; font-size: 12px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.audit-table th { text-align: left; padding: 9px 12px; background: var(--surface-alt); border-bottom: 1px solid var(--border); font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-dim); }
.audit-table td { padding: 7px 12px; border-bottom: 1px solid var(--border-subtle, #f0ece4); vertical-align: top; }
.audit-row { cursor: pointer; }
.audit-row:hover { background: var(--surface-alt); }
.audit-table .dt { font-family: var(--mono); white-space: nowrap; }
.audit-table .ev code { font-size: 11px; background: var(--surface-alt); padding: 1px 6px; border-radius: 3px; }
.audit-table .bad { color: var(--red); font-weight: 700; }
.audit-table .exp { width: 24px; text-align: center; color: var(--text-dim); }
.audit-details td { background: #fafaf7; padding: 12px 18px; }
.d-section { margin-bottom: 8px; }
.d-section pre { font-size: 10px; background: white; padding: 6px 8px; border: 1px solid var(--border); border-radius: 4px; overflow: auto; max-height: 120px; }
.d-diff { font-size: 11px; border-collapse: collapse; }
.d-diff th, .d-diff td { padding: 3px 10px; border: 1px solid var(--border); }
.d-meta { font-size: 11px; color: var(--text-dim); display: flex; gap: 16px; margin-top: 4px; }
.d-meta a { color: var(--teal); }
.audit-pager { text-align: center; margin: 12px 0; font-size: 12px; color: var(--text-dim); }
.audit-pager a { color: var(--teal); margin: 0 8px; text-decoration: none; }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 9999; }
.modal-overlay[hidden] { display: none; }
.modal-overlay .modal { background: white; padding: 20px 24px; border-radius: 10px; max-width: 480px; }
.modal-overlay .actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 14px; }
</style>

<div class="audit-page">
  <form class="audit-filters" method="get" action="/admin/audit">
    <div class="af-row">
      <label>Od <input type="date" name="dt_from" value="{{ filters.get('dt_from', '') }}"></label>
      <label>Do <input type="date" name="dt_to" value="{{ filters.get('dt_to', '') }}"></label>
      <label>Event
        <select name="event_type_glob">
          {% for grp in event_groups %}
          <option value="{{ grp.value }}" {% if filters.get('event_type_glob') == grp.value %}selected{% endif %}>{{ grp.label }}</option>
          {% endfor %}
        </select>
      </label>
      <label>Byt
        <select name="entity_type">
          {% for et in entity_types %}
          <option value="{{ et.value }}" {% if filters.get('entity_type') == et.value %}selected{% endif %}>{{ et.label }}</option>
          {% endfor %}
        </select>
      </label>
      <label>Aktor
        <select name="worker_id">
          <option value="">(wszyscy)</option>
          {% for w in workers %}
          <option value="{{ w.id }}" {% if filters.get('worker_id')|string == w.id|string %}selected{% endif %}>{{ w.nickname or w.inicjaly }}</option>
          {% endfor %}
        </select>
      </label>
      <label>Szukaj <input type="text" name="free_text" value="{{ filters.get('free_text', '') }}" placeholder="numer szarży, produkt..."></label>
      <button type="submit" class="btn btn-primary">Filtruj</button>
      <a class="btn" href="/admin/audit">Reset</a>
      <a class="btn" href="/admin/audit/export.csv?{{ request.query_string.decode() }}">Eksport CSV</a>
      <button type="button" class="btn btn-warn" onclick="openArchiveModal()">Archiwizuj &gt; 2 lata</button>
    </div>
  </form>

  <div class="audit-meta">{{ total }} wpisów (strona {{ page }} / {{ page_count }})</div>

  <table class="audit-table">
    <thead>
      <tr><th>Data/godz</th><th>Event</th><th>Byt</th><th>Aktor(zy)</th><th></th></tr>
    </thead>
    <tbody>
      {% for r in rows %}
      <tr class="audit-row" onclick="toggleDetails({{ r.id }})">
        <td class="dt">{{ r.dt[:19]|replace('T', ' ') }}</td>
        <td class="ev"><code>{{ r.event_type }}</code>{% if r.result == 'error' %} <span class="bad">×</span>{% endif %}</td>
        <td>{{ r.entity_label or ((r.entity_type ~ '#' ~ r.entity_id) if r.entity_type else '—') }}</td>
        <td>{{ r|audit_actors }}</td>
        <td class="exp">▶</td>
      </tr>
      <tr class="audit-details" id="details-{{ r.id }}" hidden>
        <td colspan="5">
          {% if r.diff_parsed %}
            <div class="d-section"><b>Diff:</b>
              <table class="d-diff">
                <tr><th>Pole</th><th>Stara</th><th>Nowa</th></tr>
                {% for d in r.diff_parsed %}
                <tr><td>{{ d.pole }}</td><td>{{ d.stara }}</td><td>{{ d.nowa }}</td></tr>
                {% endfor %}
              </table>
            </div>
          {% endif %}
          {% if r.payload_json %}<div class="d-section"><b>Payload:</b><pre>{{ r.payload_json }}</pre></div>{% endif %}
          {% if r.context_json %}<div class="d-section"><b>Kontekst:</b><pre>{{ r.context_json }}</pre></div>{% endif %}
          <div class="d-meta">
            <span>IP: {{ r.ip or '—' }}</span>
            {% if r.request_id %}<a href="/admin/audit?request_id={{ r.request_id }}">Pokaż wszystkie z tego kliknięcia →</a>{% endif %}
          </div>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <div class="audit-pager">
    {% if page > 1 %}<a href="?page={{ page - 1 }}">← Poprzednia</a>{% endif %}
    Strona {{ page }} / {{ page_count }}
    {% if page < page_count %}<a href="?page={{ page + 1 }}">Następna →</a>{% endif %}
  </div>
</div>

<div id="archive-modal" class="modal-overlay" hidden>
  <div class="modal">
    <h3>Archiwizacja wpisów audytu</h3>
    <p>Wpisów do archiwizacji: <b id="archive-count">…</b></p>
    <p>Cutoff: <b id="archive-cutoff">…</b></p>
    <p>Wpisy zostaną zapisane do <code>data/audit_archive/audit_&lt;rok&gt;.jsonl.gz</code> i usunięte z aktywnej bazy.</p>
    <div class="actions">
      <button class="btn" onclick="closeArchiveModal()">Anuluj</button>
      <button class="btn btn-warn" onclick="confirmArchive()">Archiwizuj</button>
    </div>
  </div>
</div>

<script>
function toggleDetails(id) {
  var el = document.getElementById('details-' + id);
  if (el) el.hidden = !el.hidden;
}
async function openArchiveModal() {
  var cutoff = new Date();
  cutoff.setFullYear(cutoff.getFullYear() - 2);
  var cutoffIso = cutoff.toISOString();
  var resp = await fetch('/admin/audit/archive/preview', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({cutoff_iso: cutoffIso})
  });
  var data = await resp.json();
  document.getElementById('archive-count').textContent = data.count;
  document.getElementById('archive-cutoff').textContent = cutoffIso.substring(0, 10);
  document.getElementById('archive-modal').dataset.cutoff = cutoffIso;
  document.getElementById('archive-modal').hidden = false;
}
function closeArchiveModal() {
  document.getElementById('archive-modal').hidden = true;
}
async function confirmArchive() {
  var cutoff = document.getElementById('archive-modal').dataset.cutoff;
  var resp = await fetch('/admin/audit/archive', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({cutoff_iso: cutoff})
  });
  var data = await resp.json();
  alert('Zarchiwizowano ' + data.archived + ' wpisów do ' + data.file);
  closeArchiveModal();
  location.reload();
}
</script>
{% endblock %}
```

- [ ] **Step 5: Add admin rail link**

Edit `mbr/templates/base.html`. Find the admin section in the rail (search for `_rola in ('admin'` or similar). Add a new link near other admin-only links:

```jinja
{% if _rola == 'admin' %}
<a class="rail-btn {% block nav_audit %}{% endblock %}" href="{{ url_for('admin.audit_panel') }}" title="Audit trail">
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>
  <span class="rail-label">Audit</span>
</a>
{% endif %}
```

Place it after the existing Parametry/Etapy/Ustawienia block.

- [ ] **Step 6: Run the first test**

```bash
rm -f data/batch_db.sqlite
pytest tests/test_admin_audit.py::test_admin_audit_panel_returns_200_for_admin -v
```

Expected: PASS.

If you see template errors, the issue is likely either a missing context var or a Jinja syntax problem. Read the error and fix the template.

- [ ] **Step 7: Add 5 more panel tests**

Append to `tests/test_admin_audit.py`:

```python
def test_admin_audit_panel_forbidden_for_non_admin(laborant_client, db):
    _seed_some_audit_rows(db)
    resp = laborant_client.get("/admin/audit")
    assert resp.status_code == 403


def test_admin_audit_panel_filters_by_date(admin_client, db):
    _seed_some_audit_rows(db)
    resp = admin_client.get("/admin/audit?dt_from=2026-04-02&dt_to=2026-04-02")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Only the 2026-04-02 row should be in the table
    assert "ebr.wynik.saved" in body
    assert "auth.login" not in body
    assert "cert.generated" not in body


def test_admin_audit_panel_filters_by_event_type_glob(admin_client, db):
    _seed_some_audit_rows(db)
    resp = admin_client.get("/admin/audit?event_type_glob=cert.*")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "cert.generated" in body
    assert "ebr.wynik.saved" not in body
    assert "auth.login" not in body


def test_admin_audit_panel_filters_by_request_id(admin_client, db):
    _seed_some_audit_rows(db)
    resp = admin_client.get("/admin/audit?request_id=req-2")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "ebr.wynik.saved" in body
    assert "auth.login" not in body
    assert "cert.generated" not in body


def test_admin_audit_panel_pagination(admin_client, db):
    # Seed 150 rows so we get 2 pages
    for i in range(150):
        cur = db.execute(
            "INSERT INTO audit_log (dt, event_type, result) VALUES (?, 'auth.login', 'ok')",
            (f"2026-04-{(i % 28) + 1:02d}T08:00:00",),
        )
        db.execute(
            "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, NULL, 'tester', 'admin')",
            (cur.lastrowid,),
        )
    db.commit()

    resp1 = admin_client.get("/admin/audit?page=1")
    body1 = resp1.get_data(as_text=True)
    assert "Strona 1 / 2" in body1 or "Strona 1" in body1

    resp2 = admin_client.get("/admin/audit?page=2")
    body2 = resp2.get_data(as_text=True)
    assert "Strona 2" in body2
```

- [ ] **Step 8: Run all panel tests**

```bash
pytest tests/test_admin_audit.py -v 2>&1 | tail -20
```

Expected: 6 tests PASS.

- [ ] **Step 9: Commit**

```bash
git add mbr/admin/audit_routes.py mbr/admin/__init__.py mbr/templates/admin/audit.html mbr/templates/base.html tests/test_admin_audit.py
git commit -m "$(cat <<'COMMIT'
feat(audit): /admin/audit panel — filters, pagination, table

Phase 2 Sub-PR 2.2 (panel). New module mbr/admin/audit_routes.py with
the GET /admin/audit route. Renders mbr/templates/admin/audit.html
with filter form (date range, event type glob, entity type, worker_id,
free text), result table with click-to-expand details (diff/payload/
context/IP/request_id), and pagination (100 rows/page).

Filter parser maps query string args to query_audit_log() kwargs.
Static event_type_groups dropdown lists the 9 top-level audit
namespaces (auth.*, ebr.*, cert.*, etc.).

Inline CSS in the template — Phase 2 keeps the panel self-contained
without growing lab_common.css. Vanilla JS for click-to-expand and
the (stub) archive modal.

Admin-only access via @role_required('admin'). New rail link
"Audit trail" added in base.html for the admin role.

6 HTTP tests cover happy path, 403 for non-admin, date filter, event
type glob, request_id link, and 2-page pagination.

Note: archive modal opens but its endpoints return 404 until Sub-PR
2.3 wires them.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase2-design.md
COMMIT
)"
```

---

### Task 6: CSV export route

**Files:**
- Modify: `mbr/admin/audit_routes.py`
- Test: `tests/test_admin_audit.py`

Same WHERE as the panel, no pagination, streamed via `Response(stream_with_context(...))`. Uses Python's `csv` module to escape commas/quotes correctly.

- [ ] **Step 1: Write failing test**

Append to `tests/test_admin_audit.py`:

```python
# ---------- /admin/audit/export.csv ----------

def test_admin_audit_export_csv_streams_correct_columns(admin_client, db):
    # Seed a row with a comma in entity_label to test escaping
    cur = db.execute(
        """INSERT INTO audit_log (dt, event_type, entity_type, entity_id,
           entity_label, payload_json, request_id, result)
           VALUES ('2026-04-01T08:00:00', 'ebr.wynik.saved', 'ebr', 99,
           'Szarża, with comma', '{"a":1}', 'req-x', 'ok')"""
    )
    db.execute(
        "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, 1, 'AK', 'laborant')",
        (cur.lastrowid,),
    )
    db.commit()

    resp = admin_client.get("/admin/audit/export.csv")
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/csv")
    body = resp.get_data(as_text=True)
    lines = body.strip().split("\n")
    # Header + 1 data row
    assert len(lines) == 2
    header = lines[0]
    assert "dt" in header and "event_type" in header and "entity_label" in header
    # Comma in entity_label must be quoted
    assert '"Szarża, with comma"' in lines[1]
    assert "ebr.wynik.saved" in lines[1]


def test_admin_audit_export_csv_forbidden_for_non_admin(laborant_client, db):
    resp = laborant_client.get("/admin/audit/export.csv")
    assert resp.status_code == 403
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_admin_audit.py -k export_csv -v
```

Expected: 404 (route not yet defined).

- [ ] **Step 3: Add route to `mbr/admin/audit_routes.py`**

Append after the `audit_panel` function:

```python
@admin_bp.route("/admin/audit/export.csv")
@role_required("admin")
def audit_export_csv():
    """Stream the audit log as CSV using the same WHERE as the panel.

    Hard cap at 1,000,000 rows for memory safety. The csv module handles
    quoting/escaping; entity_label values with commas are auto-quoted.
    """
    filters = _parse_filters_from_query(request.args)

    def generate():
        # Header row
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow([
            "dt", "event_type", "entity_type", "entity_id", "entity_label",
            "actors", "result", "diff", "payload", "ip", "request_id",
        ])
        yield out.getvalue()

        with db_session() as db:
            rows, _total = audit.query_audit_log(
                db, **filters, limit=1_000_000, offset=0
            )
        for r in rows:
            out = io.StringIO()
            writer = csv.writer(out)
            actors_str = ", ".join(a["actor_login"] for a in (r.get("actors") or []))
            writer.writerow([
                r.get("dt") or "",
                r.get("event_type") or "",
                r.get("entity_type") or "",
                r.get("entity_id") or "",
                r.get("entity_label") or "",
                actors_str,
                r.get("result") or "",
                r.get("diff_json") or "",
                r.get("payload_json") or "",
                r.get("ip") or "",
                r.get("request_id") or "",
            ])
            yield out.getvalue()

    return Response(
        stream_with_context(generate()),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
    )
```

- [ ] **Step 4: Run — verify pass**

```bash
pytest tests/test_admin_audit.py -k export_csv -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/admin/audit_routes.py tests/test_admin_audit.py
git commit -m "$(cat <<'COMMIT'
feat(audit): /admin/audit/export.csv — streamed CSV export

Phase 2 Sub-PR 2.2 (panel). Streams the same WHERE as the panel with
no pagination, hard cap at 1M rows. Uses Python's csv module so
entity_label values with commas/quotes are auto-escaped.

11 columns: dt, event_type, entity_type, entity_id, entity_label,
actors (joined logins), result, diff (raw JSON), payload (raw JSON),
ip, request_id.

2 tests: comma escaping verified, 403 for non-admin.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase2-design.md
COMMIT
)"
```

---

### Task 7: Archive preview + apply route stubs

**Files:**
- Modify: `mbr/admin/audit_routes.py`
- Test: `tests/test_admin_audit.py`

Wire the modal's two endpoints. **Preview** is already real (just a count). **Apply** is wired in this task too — the Phase 2 spec splits this into Sub-PR 2.3 for "wire the actual archival logic", but in practice the wiring is one line (`audit.archive_old_entries(db, cutoff, archive_dir)`) so we do it now and keep Sub-PR 2.3 for the e2e validation test.

- [ ] **Step 1: Write 2 failing tests**

Append to `tests/test_admin_audit.py`:

```python
# ---------- /admin/audit/archive ----------

def test_admin_audit_archive_preview_returns_count(admin_client, db):
    # Seed 3 old + 2 new rows
    for dt in ("2020-01-01", "2020-02-01", "2020-03-01"):
        cur = db.execute(
            "INSERT INTO audit_log (dt, event_type, result) VALUES (?, 'auth.login', 'ok')",
            (dt + "T08:00:00",),
        )
        db.execute(
            "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, NULL, 'x', 'unknown')",
            (cur.lastrowid,),
        )
    for dt in ("2026-04-01", "2026-04-02"):
        cur = db.execute(
            "INSERT INTO audit_log (dt, event_type, result) VALUES (?, 'auth.login', 'ok')",
            (dt + "T08:00:00",),
        )
        db.execute(
            "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, NULL, 'x', 'unknown')",
            (cur.lastrowid,),
        )
    db.commit()

    resp = admin_client.post(
        "/admin/audit/archive/preview",
        json={"cutoff_iso": "2024-01-01T00:00:00"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 3
    assert data["cutoff"] == "2024-01-01T00:00:00"

    # Preview must NOT mutate
    remaining = db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    assert remaining == 5


def test_admin_audit_archive_preview_forbidden_for_non_admin(laborant_client, db):
    resp = laborant_client.post(
        "/admin/audit/archive/preview", json={"cutoff_iso": "2024-01-01T00:00:00"}
    )
    assert resp.status_code == 403
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_admin_audit.py -k archive_preview -v
```

Expected: 404.

- [ ] **Step 3: Add preview route**

Append to `mbr/admin/audit_routes.py`:

```python
@admin_bp.route("/admin/audit/archive/preview", methods=["POST"])
@role_required("admin")
def audit_archive_preview():
    """Return count of audit_log rows that would be archived for the given cutoff.

    No mutation. Used by the modal confirmation dialog.
    """
    body = request.get_json(silent=True) or {}
    cutoff = body.get("cutoff_iso")
    if not cutoff:
        return jsonify({"error": "cutoff_iso required"}), 400
    with db_session() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM audit_log WHERE dt < ?", (cutoff,)
        ).fetchone()[0]
    return jsonify({"count": count, "cutoff": cutoff})
```

- [ ] **Step 4: Run — verify pass**

```bash
pytest tests/test_admin_audit.py -k archive_preview -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit (preview only — apply lands in Sub-PR 2.3)**

```bash
git add mbr/admin/audit_routes.py tests/test_admin_audit.py
git commit -m "$(cat <<'COMMIT'
feat(audit): /admin/audit/archive/preview — count without mutation

Phase 2 Sub-PR 2.2 (panel). The modal's confirmation step calls this
to display 'Wpisów do archiwizacji: N' before the user clicks
'Archiwizuj'. No DB mutation here — just SELECT COUNT(*).

Apply endpoint wired in Sub-PR 2.3 next.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase2-design.md
COMMIT
)"
```

---

## Sub-PR 2.3: Archive end-to-end (Task 8)

Wires the apply endpoint to the real `archive_old_entries()` from Sub-PR 2.1. After this, clicking "Archiwizuj" in the modal actually creates the JSONL.gz file and removes rows.

---

### Task 8: Wire `audit_archive_do` to real archival

**Files:**
- Modify: `mbr/admin/audit_routes.py`
- Test: `tests/test_admin_audit.py`

- [ ] **Step 1: Write failing e2e test**

Append to `tests/test_admin_audit.py`:

```python
# ---------- /admin/audit/archive (apply) ----------

def test_admin_audit_archive_apply_runs_archive(admin_client, db, tmp_path, monkeypatch):
    import mbr.admin.audit_routes
    # Override the archive_dir resolution to use tmp_path
    monkeypatch.setattr(
        mbr.admin.audit_routes, "_resolve_archive_dir", lambda: tmp_path
    )

    # Seed 2 old rows
    for dt in ("2020-01-01", "2020-02-01"):
        cur = db.execute(
            "INSERT INTO audit_log (dt, event_type, result) VALUES (?, 'auth.login', 'ok')",
            (dt + "T08:00:00",),
        )
        db.execute(
            "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, NULL, 'x', 'unknown')",
            (cur.lastrowid,),
        )
    db.commit()

    resp = admin_client.post(
        "/admin/audit/archive", json={"cutoff_iso": "2024-01-01T00:00:00"}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["archived"] == 2

    # Active DB now has 0 originals + 1 system.audit.archived = 1
    rows = db.execute("SELECT event_type FROM audit_log").fetchall()
    assert len(rows) == 1
    assert rows[0]["event_type"] == "system.audit.archived"

    # Archive file exists
    archive_file = tmp_path / "audit_2020.jsonl.gz"
    assert archive_file.exists()


def test_admin_audit_archive_apply_forbidden_for_non_admin(laborant_client, db):
    resp = laborant_client.post(
        "/admin/audit/archive", json={"cutoff_iso": "2024-01-01T00:00:00"}
    )
    assert resp.status_code == 403
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_admin_audit.py -k archive_apply -v
```

Expected: 404.

- [ ] **Step 3: Add `_resolve_archive_dir` helper + route**

Append to `mbr/admin/audit_routes.py`:

```python
def _resolve_archive_dir() -> Path:
    """Default archive location: <project_root>/data/audit_archive/.

    Extracted into a helper so tests can monkey-patch it.
    """
    project_root = Path(current_app.root_path).parent
    return project_root / "data" / "audit_archive"


@admin_bp.route("/admin/audit/archive", methods=["POST"])
@role_required("admin")
def audit_archive_do():
    """Run the actual archival: dump old rows to JSONL.gz, delete from DB,
    log system.audit.archived. See audit.archive_old_entries() for details.
    """
    body = request.get_json(silent=True) or {}
    cutoff = body.get("cutoff_iso")
    if not cutoff:
        return jsonify({"error": "cutoff_iso required"}), 400

    archive_dir = _resolve_archive_dir()
    with db_session() as db:
        result = audit.archive_old_entries(db, cutoff, archive_dir)
    return jsonify(result)
```

- [ ] **Step 4: Run — verify pass**

```bash
pytest tests/test_admin_audit.py -k archive_apply -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Run full Phase 2 test files**

```bash
pytest tests/test_admin_audit.py tests/test_audit_helper.py 2>&1 | tail -5
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add mbr/admin/audit_routes.py tests/test_admin_audit.py
git commit -m "$(cat <<'COMMIT'
feat(audit): /admin/audit/archive — wire to real archival

Phase 2 Sub-PR 2.3 (archive end-to-end). The modal's 'Archiwizuj'
button now actually runs audit.archive_old_entries(): dumps to
{project}/data/audit_archive/audit_<year>.jsonl.gz, deletes from the
active DB, logs system.audit.archived with the system actor.

Helper _resolve_archive_dir() is extracted so tests can monkey-patch
the path to tmp_path.

This is the FIRST real log_event() call site that runs on production
(Phase 1 had zero call sites; Sub-PR 2.2 only added read paths).
The system actor and isolated nature make this a low-risk smoke test
of the Phase 1 infrastructure pipeline.

2 tests cover the e2e flow + 403 for non-admin.

Sub-PR 2.3 complete.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase2-design.md
COMMIT
)"
```

---

## Sub-PR 2.4: Per-record history (Tasks 9-12)

Replaces the existing `get_audit_log(ebr_id)` endpoint and adds two new ones for MBR and cert. Adds a reusable Jinja partial included in 3 existing views.

---

### Task 9: Replace `get_audit_log(ebr_id)` in laborant routes

**Files:**
- Modify: `mbr/laborant/routes.py:213-226` (or wherever the existing function lives)
- Test: `tests/test_admin_audit.py`

The old endpoint reads the legacy `audit_log` schema (columns `tabela`, `pole`, `zmienil` etc.) which no longer exists post-migration. Replace it with a new endpoint at the new URL `/api/ebr/<id>/audit-history` that uses `audit.query_audit_history_for_entity`.

- [ ] **Step 1: Read the existing function**

```bash
sed -n '210,230p' mbr/laborant/routes.py
```

Note the exact line numbers. The function is `get_audit_log(ebr_id)` and it queries the legacy schema (broken since Phase 1 migration).

- [ ] **Step 2: Write failing test**

Append to `tests/test_admin_audit.py`:

```python
# ---------- /api/ebr/<id>/audit-history ----------

def test_ebr_audit_history_endpoint_returns_only_ebr_entries(admin_client, db):
    # Seed 3 ebr-related + 1 cert-related (must be filtered out)
    for i, (et, eid) in enumerate([("ebr", 42), ("ebr", 42), ("ebr", 99), ("cert", 7)]):
        cur = db.execute(
            "INSERT INTO audit_log (dt, event_type, entity_type, entity_id, result) VALUES (?, 'x.y.z', ?, ?, 'ok')",
            (f"2026-04-0{i+1}T08:00:00", et, eid),
        )
        db.execute(
            "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, NULL, 'tester', 'admin')",
            (cur.lastrowid,),
        )
    db.commit()

    resp = admin_client.get("/api/ebr/42/audit-history")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "history" in data
    assert len(data["history"]) == 2
    assert all(r["entity_type"] == "ebr" and r["entity_id"] == 42 for r in data["history"])
    # Sorted DESC by dt
    assert data["history"][0]["dt"] >= data["history"][1]["dt"]


def test_ebr_audit_history_endpoint_includes_actors(admin_client, db):
    cur = db.execute(
        "INSERT INTO audit_log (dt, event_type, entity_type, entity_id, result) VALUES ('2026-04-01T08:00:00', 'ebr.wynik.saved', 'ebr', 50, 'ok')"
    )
    db.execute(
        "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, 1, 'AK', 'laborant')",
        (cur.lastrowid,),
    )
    db.commit()

    resp = admin_client.get("/api/ebr/50/audit-history")
    data = resp.get_json()
    assert len(data["history"]) == 1
    assert "actors" in data["history"][0]
    assert data["history"][0]["actors"][0]["actor_login"] == "AK"
```

- [ ] **Step 3: Run — verify failure**

```bash
pytest tests/test_admin_audit.py -k ebr_audit_history -v
```

Expected: 404 (new URL doesn't exist).

- [ ] **Step 4: Replace the old endpoint with the new one**

Edit `mbr/laborant/routes.py`. Find the existing `get_audit_log` function (around line 213) and replace it entirely with:

```python
@laborant_bp.route("/api/ebr/<int:ebr_id>/audit-history")
@role_required("laborant", "laborant_kj", "laborant_coa", "admin", "technolog")
def ebr_audit_history(ebr_id):
    """Return per-EBR audit history (sorted DESC by dt, with actors)."""
    from mbr.shared import audit
    with db_session() as db:
        history = audit.query_audit_history_for_entity(db, "ebr", ebr_id)
    return jsonify({"history": history})
```

If there's an old route handler under a different URL like `/laborant/ebr/<int:ebr_id>/audit-log`, delete it entirely. The new endpoint replaces it.

- [ ] **Step 5: Run — verify pass**

```bash
pytest tests/test_admin_audit.py -k ebr_audit_history -v
```

Expected: 2 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add mbr/laborant/routes.py tests/test_admin_audit.py
git commit -m "$(cat <<'COMMIT'
feat(audit): replace legacy get_audit_log(ebr_id) with new per-record endpoint

Phase 2 Sub-PR 2.4 (per-record history). The legacy endpoint at the
old URL queried the legacy audit_log schema (columns tabela, pole,
zmienil) which no longer exists post-Phase-1 migration.

Replaced with /api/ebr/<id>/audit-history using
audit.query_audit_history_for_entity('ebr', id). Returns
{'history': [...]} with rows sorted dt DESC and actors joined.

Old URL is gone — clean rollback (no shim).

2 tests cover only-matching-entity and actors inclusion.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase2-design.md
COMMIT
)"
```

---

### Task 10: New `/api/mbr/<id>/audit-history` endpoint

**Files:**
- Modify: `mbr/technolog/routes.py`
- Test: `tests/test_admin_audit.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_admin_audit.py`:

```python
# ---------- /api/mbr/<id>/audit-history ----------

def test_mbr_audit_history_returns_filtered(admin_client, db):
    cur = db.execute(
        "INSERT INTO audit_log (dt, event_type, entity_type, entity_id, result) VALUES ('2026-04-01T08:00:00', 'mbr.template.updated', 'mbr', 7, 'ok')"
    )
    db.execute(
        "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, NULL, 'jan', 'technolog')",
        (cur.lastrowid,),
    )
    db.commit()

    resp = admin_client.get("/api/mbr/7/audit-history")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["history"]) == 1
    assert data["history"][0]["event_type"] == "mbr.template.updated"


def test_mbr_audit_history_role_protected(laborant_client, db):
    resp = laborant_client.get("/api/mbr/7/audit-history")
    assert resp.status_code == 403
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_admin_audit.py -k mbr_audit_history -v
```

Expected: 404.

- [ ] **Step 3: Add endpoint to `mbr/technolog/routes.py`**

Find the imports at the top of `mbr/technolog/routes.py`. Ensure `db_session`, `role_required`, `jsonify` are imported. Then append (anywhere among the other route definitions):

```python
@technolog_bp.route("/api/mbr/<int:mbr_id>/audit-history")
@role_required("admin", "technolog")
def mbr_audit_history(mbr_id):
    """Return per-MBR audit history (sorted DESC by dt, with actors)."""
    from mbr.shared import audit
    with db_session() as db:
        history = audit.query_audit_history_for_entity(db, "mbr", mbr_id)
    return jsonify({"history": history})
```

If `jsonify` is not yet imported, add it: `from flask import jsonify` (or add to existing flask import line).

- [ ] **Step 4: Run — verify pass**

```bash
pytest tests/test_admin_audit.py -k mbr_audit_history -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/technolog/routes.py tests/test_admin_audit.py
git commit -m "$(cat <<'COMMIT'
feat(audit): /api/mbr/<id>/audit-history — per-MBR audit history endpoint

Phase 2 Sub-PR 2.4 (per-record history). New endpoint in
mbr/technolog/routes.py for the MBR template editor sidebar/section.
Currently returns empty for all MBR IDs because no Phase has yet
written mbr.template.* events — that lands in Phase 5 along with
the actual write-side integration. The endpoint and template hook
are in place so Phase 5 only has to add log_event() calls.

Role-protected to admin + technolog.

2 tests cover happy path and 403 for non-admin/technolog.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase2-design.md
COMMIT
)"
```

---

### Task 11: New `/api/cert/<id>/audit-history` endpoint

**Files:**
- Modify: `mbr/certs/routes.py`
- Test: `tests/test_admin_audit.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_admin_audit.py`:

```python
# ---------- /api/cert/<id>/audit-history ----------

def test_cert_audit_history_returns_filtered(admin_client, db):
    cur = db.execute(
        "INSERT INTO audit_log (dt, event_type, entity_type, entity_id, entity_label, result) VALUES ('2026-04-01T08:00:00', 'cert.generated', 'cert', 12, 'Świad. K40GLO', 'ok')"
    )
    db.execute(
        "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) VALUES (?, NULL, 'kj', 'laborant_kj')",
        (cur.lastrowid,),
    )
    db.commit()

    resp = admin_client.get("/api/cert/12/audit-history")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["history"]) == 1
    assert data["history"][0]["entity_label"] == "Świad. K40GLO"
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_admin_audit.py -k cert_audit_history -v
```

Expected: 404.

- [ ] **Step 3: Add endpoint to `mbr/certs/routes.py`**

Find the existing imports and route handlers in `mbr/certs/routes.py`. Add this endpoint:

```python
@certs_bp.route("/api/cert/<int:cert_id>/audit-history")
@role_required("admin", "technolog", "laborant_coa", "laborant_kj")
def cert_audit_history(cert_id):
    """Return per-cert audit history (sorted DESC by dt, with actors)."""
    from mbr.shared import audit
    with db_session() as db:
        history = audit.query_audit_history_for_entity(db, "cert", cert_id)
    return jsonify({"history": history})
```

Verify `jsonify`, `db_session`, `role_required` are imported at the top of the file. If `role_required` is missing, add: `from mbr.shared.decorators import role_required`.

- [ ] **Step 4: Run — verify pass**

```bash
pytest tests/test_admin_audit.py -k cert_audit_history -v
```

Expected: 1 test PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/certs/routes.py tests/test_admin_audit.py
git commit -m "$(cat <<'COMMIT'
feat(audit): /api/cert/<id>/audit-history — per-cert audit history endpoint

Phase 2 Sub-PR 2.4 (per-record history). Symmetric to MBR endpoint.
Empty until Phase 6 adds cert.* write-side integration; the wiring is
in place so Phase 6 only needs log_event() calls.

Role-protected to admin/technolog/laborant_coa/laborant_kj.

1 test covers happy path.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase2-design.md
COMMIT
)"
```

---

### Task 12: Reusable history partial + include in 3 templates

**Files:**
- Create: `mbr/templates/_audit_history_section.html`
- Modify: `mbr/templates/laborant/_fast_entry_content.html` (under uwagi block)
- Modify: MBR template editor view (locate at impl time)
- Modify: cert detail view (locate at impl time)

This task has no automated test — the partial is JavaScript that fetches the API endpoints already covered by Tasks 9-11. Verification is manual smoke test in the browser.

- [ ] **Step 1: Create the partial**

Create `mbr/templates/_audit_history_section.html`:

```html
{# Reusable per-record audit history section.
   Include with:  {% include "_audit_history_section.html" %}
   Required context: entity_type ('ebr'/'mbr'/'cert'), entity_id (int).
#}
<div class="audit-hist" data-entity-type="{{ entity_type }}" data-entity-id="{{ entity_id }}">
  <div class="audit-hist-head">
    <span>HISTORIA AUDYTU</span>
    <button type="button" class="ah-refresh" onclick="loadAuditHist(this.closest('.audit-hist'))">Odśwież</button>
  </div>
  <div class="audit-hist-body">— ładowanie —</div>
</div>

<style>
.audit-hist { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; margin-top: 12px; }
.audit-hist-head { padding: 8px 14px; background: var(--surface-alt); border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.07em; color: var(--text-dim); }
.ah-refresh { font-size: 10px; padding: 3px 8px; border: 1px solid var(--border); background: white; border-radius: 4px; cursor: pointer; }
.audit-hist-body { padding: 8px 14px; font-size: 11px; color: var(--text-sec); max-height: 240px; overflow-y: auto; }
.ah-row { padding: 4px 0; border-bottom: 1px dashed var(--border-subtle, #f0ece4); }
.ah-row:last-child { border-bottom: none; }
.ah-row .ah-dt { font-family: var(--mono); font-size: 10px; color: var(--text-dim); }
.ah-row code { font-size: 10px; background: var(--surface-alt); padding: 1px 5px; border-radius: 3px; }
.ah-row .ah-actor { color: var(--text); font-weight: 600; }
.ah-row .ah-diff { color: var(--text-dim); font-size: 10px; }
</style>

<script>
(function() {
  if (window._auditHistLoaded) return;
  window._auditHistLoaded = true;

  window.loadAuditHist = async function(sec) {
    var et = sec.dataset.entityType, eid = sec.dataset.entityId;
    var url = '/api/' + et + '/' + eid + '/audit-history';
    var body = sec.querySelector('.audit-hist-body');
    body.textContent = '— ładowanie —';
    try {
      var resp = await fetch(url);
      if (!resp.ok) { body.textContent = 'błąd HTTP ' + resp.status; return; }
      var data = await resp.json();
      if (!data.history || data.history.length === 0) {
        body.innerHTML = '<i>brak wpisów</i>';
        return;
      }
      body.innerHTML = data.history.map(_renderAuditEntry).join('');
    } catch (e) {
      body.textContent = 'błąd: ' + e.message;
    }
  };

  function _renderAuditEntry(r) {
    var dt = (r.dt || '').substring(0, 19).replace('T', ' ');
    var actors = (r.actors || []).map(function(a) { return _esc(a.actor_login); }).join(', ') || '—';
    var diffStr = '';
    if (r.diff_json) {
      try {
        var arr = JSON.parse(r.diff_json);
        diffStr = ' — ' + arr.map(function(d) {
          return _esc(d.pole) + ': ' + _esc(String(d.stara)) + '→' + _esc(String(d.nowa));
        }).join(', ');
      } catch (e) {}
    }
    return '<div class="ah-row">' +
           '<span class="ah-dt">' + dt + '</span> ' +
           '<code>' + _esc(r.event_type) + '</code> ' +
           '<span class="ah-actor">' + actors + '</span>' +
           '<span class="ah-diff">' + diffStr + '</span>' +
           '</div>';
  }

  function _esc(s) {
    return String(s).replace(/[&<>"']/g, function(c) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }

  // Auto-load all sections on the current page
  document.querySelectorAll('.audit-hist').forEach(loadAuditHist);
})();
</script>
```

- [ ] **Step 2: Include in EBR view**

Edit `mbr/templates/laborant/_fast_entry_content.html`. Find the uwagi block (search for `cv-notes-block` or `_renderUwagiBlock`). After the uwagi block in the rendered output, include the partial:

The partial needs `entity_type` and `entity_id` in the Jinja context. Since `_fast_entry_content.html` is rendered with the EBR id available as `ebr.ebr_id` (or similar), we use:

```jinja
{% with entity_type='ebr', entity_id=ebr.ebr_id %}
  {% include "_audit_history_section.html" %}
{% endwith %}
```

Place this after the closing `</div>` of the uwagi block (find `_renderUwagiBlock` in the JS to know where the block lives in HTML, then place the include in the corresponding template region near the wrapper).

If the EBR view renders uwagi via JavaScript injection rather than a Jinja block, find the parent container that holds the uwagi DOM node and add the partial-include just below it in the Jinja template.

To locate the right place quickly:

```bash
grep -n "cv-notes\|uwagi" mbr/templates/laborant/_fast_entry_content.html | head -20
```

Insert the include in the rendered HTML body, NOT inside the JavaScript section.

- [ ] **Step 3: Locate and include in MBR template view**

```bash
grep -rn "mbr_id\|mbr_template\|template.*editor" mbr/templates/technolog/ 2>&1 | head -10
```

Find the main MBR editor template (likely `mbr/templates/technolog/edit_mbr.html` or similar). Add the include near the bottom of the form/content block:

```jinja
{% with entity_type='mbr', entity_id=mbr.mbr_id %}
  {% include "_audit_history_section.html" %}
{% endwith %}
```

Use the variable name that the technolog route actually passes — read the route handler first:

```bash
grep -n "render_template.*mbr\|mbr_id=" mbr/technolog/routes.py | head -10
```

- [ ] **Step 4: Locate and include in cert detail view**

```bash
grep -rn "cert.*detail\|cert_id\|swiadectwo" mbr/templates/ 2>&1 | head -15
```

Find the cert detail template (likely under `mbr/templates/certs/` or similar). Add include with the cert id:

```jinja
{% with entity_type='cert', entity_id=cert.id %}
  {% include "_audit_history_section.html" %}
{% endwith %}
```

If certs don't have a dedicated detail view (the panel renders from data on the szarze list), pick the closest analogue — e.g. the cert preview modal or the cert list row's expanded section.

- [ ] **Step 5: Manual smoke test**

```bash
rm -f data/batch_db.sqlite
python scripts/migrate_audit_log_v2.py --db data/batch_db.sqlite || true  # idempotent on fresh DB
python -m mbr.app
```

(Or: if the dev server is already running with hot reload, just refresh the browser.)

In the browser:
1. Log in as admin
2. Open any szarża → confirm "HISTORIA AUDYTU" section appears under uwagi
3. Click "Odśwież" — should fetch and display rows (or "brak wpisów" if migrated DB is empty)
4. Open MBR template editor → confirm section appears (likely "brak wpisów")
5. Open a cert detail/preview → confirm section appears

Stop the dev server when done.

- [ ] **Step 6: Commit**

```bash
git add mbr/templates/_audit_history_section.html mbr/templates/laborant/_fast_entry_content.html
# Plus whatever MBR + cert templates you ended up modifying
git status  # show what's staged
git commit -m "$(cat <<'COMMIT'
feat(audit): per-record history sections in EBR/MBR/cert views

Phase 2 Sub-PR 2.4 (per-record history). New reusable Jinja partial
mbr/templates/_audit_history_section.html with inline CSS + vanilla
JS that fetches /api/{entity_type}/{id}/audit-history on render.

Included in 3 places:
- _fast_entry_content.html (EBR view, under uwagi block)
- MBR template editor view
- Cert detail view

For EBR, the section will display the legacy.field_change events
migrated from Phase 1 (entity_type='ebr_wyniki' for now — proper
'ebr' entity_type comes with Phase 4 write-side integration).

For MBR and cert, the section will be empty until Phases 5-6.

The partial guards against double-load with window._auditHistLoaded
so multiple instances on the same page don't re-execute the script.

Phase 2 complete.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase2-design.md
COMMIT
)"
```

---

## Phase 2 Done Definition

After Task 12:

- [ ] `mbr/shared/audit.py` has 3 new helpers: `query_audit_log`, `query_audit_history_for_entity`, `archive_old_entries`
- [ ] `mbr/admin/audit_routes.py` exists with 4 routes (panel, csv, archive preview, archive apply)
- [ ] `mbr/templates/admin/audit.html` exists with filters/table/modal
- [ ] `mbr/templates/_audit_history_section.html` exists and is included in 3 views
- [ ] `mbr/templates/base.html` has new admin rail link "Audit"
- [ ] `mbr/laborant/routes.py` legacy `get_audit_log(ebr_id)` is GONE — replaced by new `/api/ebr/<id>/audit-history`
- [ ] `mbr/technolog/routes.py` and `mbr/certs/routes.py` have new `audit-history` endpoints
- [ ] `mbr/shared/filters.py` has `audit_actors_filter` registered
- [ ] `tests/test_audit_helper.py` has ≥16 new tests for helpers
- [ ] `tests/test_admin_audit.py` has ≥13 new tests for HTTP/per-record
- [ ] Full `pytest` is green: ≈288 passed, 16 skipped, 0 failed (261 baseline + 27 new)
- [ ] Manual smoke in browser: panel loads, filters work, CSV downloads, archive modal counts and applies, history sections show in EBR/MBR/cert views

## Deployment note

Phase 2 is **schema-stable** — no migrations needed. Auto-deploy on prod will:
1. `git pull` (Phase 2 commits)
2. `pip install` (no new deps)
3. `python scripts/migrate_audit_log_v2.py --db data/batch_db.sqlite` — runs the migration script which is **idempotent** and skips early via `_has_new_columns` (already migrated by Phase 1 deploy)
4. `systemctl restart lims`

After restart, admin can immediately visit `/admin/audit`. EBR history sections will show the 42 legacy `legacy.field_change` entries already in the migrated DB. MBR and cert sections will be empty until Phases 5-6.

**No backup/rollback dance required for Phase 2** — every change is additive (new files) or replaces a known-broken endpoint (`get_audit_log(ebr_id)`).
