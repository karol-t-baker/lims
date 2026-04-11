# Audit Trail — Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** First real `log_event()` call sites in production blueprints (auth + workers) plus enforce "pusta zmiana blokuje zapis dla laboranta" via `ShiftRequiredError`.

**Architecture:** Each existing route gets a single `log_event()` call right before its return. New `change_password()` model + new POST `/api/users/<id>/password` admin-only endpoint. `_resolve_actor_label` (in `mbr/laborant/routes.py`) raises `ShiftRequiredError` for `rola='laborant'` on empty shift instead of falling back to login. Frontend JS handlers gain `if status===400 && error==='shift_required' → openShiftModal()`.

**Tech Stack:** Flask, raw sqlite3, bcrypt, pytest with in-memory SQLite fixtures, vanilla JS.

**Spec reference:** `docs/superpowers/specs/2026-04-11-audit-trail-phase3-design.md`

**Out of scope for Phase 3:**
- EBR/MBR/cert blueprint instrumentation (Phases 4-6)
- Read-log
- UI for password change in admin panel — endpoint only (UI later)
- Tightening role guards in workers blueprint (currently `@login_required` not `@role_required` — pre-existing gap, not part of Phase 3)

**Branch convention:** All Phase 3 work happens on `audit/phase3` branch in worktree `.worktrees/audit-phase3`. 3 sub-PRs (3.1 auth, 3.2 workers, 3.3 shift fallback) merged together via single `--no-ff` to main when done.

---

## File Structure

**Modify:**
- `mbr/auth/models.py` — append `change_password(db, user_id, new_password)` (~25 LOC)
- `mbr/auth/routes.py` — add imports for `audit`, `role_required`; instrument `login()` (success + failure), `logout()`; add new `api_change_password(user_id)` route (~80 LOC added)
- `mbr/workers/routes.py` — add imports; instrument 5 endpoints (api_shift, api_worker_profile, api_add_worker, api_toggle_worker, api_delete_worker) (~100 LOC added)
- `mbr/laborant/routes.py` — modify `_resolve_actor_label()` to raise `ShiftRequiredError` for `rola='laborant'` (~5 LOC change)
- `mbr/templates/laborant/_fast_entry_content.html` — add `shift_required` handler to JS write handlers (~20 LOC across 3-5 handlers)
- `tests/test_uwagi.py` — modify `test_resolve_actor_label_falls_back_to_login_when_no_shift` to verify the new role-specific behaviour
- (Optionally) other JS handlers in `_fast_entry_content.html` or `szarze_list.html` if grep finds more write paths

**Create:**
- `tests/test_audit_phase3_auth.py` — 6 tests for auth instrumentation (~250 LOC)
- `tests/test_audit_phase3_workers.py` — 6 tests for workers instrumentation (~250 LOC)
- `tests/test_audit_phase3_shift_required.py` — 4 tests for shift fallback enforcement (~180 LOC)

---

## Sub-PR 3.1: Auth instrumentation (Tasks 1-4)

---

### Task 1: `change_password()` model function

**Files:**
- Modify: `mbr/auth/models.py`
- Test: `tests/test_auth.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_auth.py`:

```python
def test_change_password_updates_hash(db):
    """change_password() updates the hash so verify_user works with the new password."""
    from mbr.auth.models import change_password
    user_id = create_user(db, login="kowalski", password="oldpass1", rola="laborant")
    result = change_password(db, user_id, "newpass2")
    assert result["user_id"] == user_id
    assert result["login"] == "kowalski"
    assert verify_user(db, "kowalski", "newpass2") is not None
    assert verify_user(db, "kowalski", "oldpass1") is None


def test_change_password_rejects_short(db):
    """Password shorter than 6 chars raises ValueError."""
    from mbr.auth.models import change_password
    user_id = create_user(db, login="kowalski", password="oldpass1", rola="laborant")
    import pytest as _pytest
    with _pytest.raises(ValueError, match="6"):
        change_password(db, user_id, "short")


def test_change_password_unknown_user_raises(db):
    """Non-existent user_id raises ValueError."""
    from mbr.auth.models import change_password
    import pytest as _pytest
    with _pytest.raises(ValueError, match="not found"):
        change_password(db, 9999, "validpass")
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_auth.py -k change_password -v
```

Expected: 3 tests fail with `ImportError: cannot import name 'change_password'`.

- [ ] **Step 3: Implement `change_password()`**

Append to `mbr/auth/models.py`:

```python
def change_password(db: sqlite3.Connection, user_id: int, new_password: str) -> dict:
    """Hash and update password for an existing user.

    Returns dict with user_id + login (no password_hash).
    Raises ValueError if user not found or password is shorter than 6 chars.
    """
    if len(new_password) < 6:
        raise ValueError("Password must be at least 6 characters")

    row = db.execute(
        "SELECT user_id, login, rola FROM mbr_users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"User {user_id} not found")

    password_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    db.execute(
        "UPDATE mbr_users SET password_hash = ? WHERE user_id = ?",
        (password_hash, user_id),
    )
    db.commit()

    return {"user_id": row["user_id"], "login": row["login"], "rola": row["rola"]}
```

- [ ] **Step 4: Run — verify pass**

```bash
pytest tests/test_auth.py -k change_password -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Run full test_auth.py**

```bash
pytest tests/test_auth.py 2>&1 | tail -5
```

Expected: All existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add mbr/auth/models.py tests/test_auth.py
git commit -m "$(cat <<'COMMIT'
feat(auth): change_password() — bcrypt hash + update + validation

Phase 3 Sub-PR 3.1 prep. New model function used by the upcoming
POST /api/users/<id>/password endpoint. Validates length >=6 (matching
create_user convention), raises ValueError for missing user.

3 unit tests cover happy path, length validation, missing user.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase3-design.md
COMMIT
)"
```

---

### Task 2: `POST /api/users/<id>/password` endpoint with audit log

**Files:**
- Modify: `mbr/auth/routes.py`
- Test: `tests/test_audit_phase3_auth.py` (new file)

- [ ] **Step 1: Create test file with first failing test**

Create `tests/test_audit_phase3_auth.py`:

```python
"""Tests for Phase 3 auth instrumentation: login/logout/password_changed."""

import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables
from mbr.auth.models import create_user


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _make_client(monkeypatch, db, rola="admin"):
    """Build a Flask test client with the in-memory db patched in."""
    import mbr.db
    import mbr.auth.routes
    import mbr.admin.routes
    import mbr.admin.audit_routes
    import mbr.laborant.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.auth.routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.admin.routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.admin.audit_routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True

    client = app.test_client()
    if rola is not None:
        with client.session_transaction() as sess:
            sess["user"] = {"login": "tester", "rola": rola, "imie_nazwisko": None}
    return client


@pytest.fixture
def admin_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="admin")


@pytest.fixture
def laborant_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="laborant")


@pytest.fixture
def anon_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola=None)


# ---------- POST /api/users/<id>/password ----------

def test_change_password_logs_event(admin_client, db):
    """Admin changes another user's password → audit_log entry exists with
    target_user_id + target_user_login in payload (NOT the password)."""
    target_id = create_user(db, login="kowalski", password="oldpass1", rola="laborant")

    resp = admin_client.post(
        f"/api/users/{target_id}/password",
        json={"new_password": "newpass2"},
    )
    assert resp.status_code == 200

    # Verify password actually changed
    from mbr.auth.models import verify_user
    assert verify_user(db, "kowalski", "newpass2") is not None
    assert verify_user(db, "kowalski", "oldpass1") is None

    # Audit entry exists
    rows = db.execute(
        "SELECT event_type, entity_type, entity_id, entity_label, payload_json "
        "FROM audit_log WHERE event_type='auth.password_changed'"
    ).fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["entity_type"] == "user"
    assert r["entity_id"] == target_id
    assert r["entity_label"] == "kowalski"

    import json as _json
    payload = _json.loads(r["payload_json"])
    assert payload["target_user_id"] == target_id
    assert payload["target_user_login"] == "kowalski"
    # CRITICAL: no password material in payload
    assert "password" not in str(payload).lower() or "newpass" not in str(payload)
    assert "newpass2" not in r["payload_json"]
    assert "oldpass1" not in r["payload_json"]


def test_change_password_forbidden_for_non_admin(laborant_client, db):
    target_id = create_user(db, login="kowalski", password="oldpass1", rola="laborant")
    resp = laborant_client.post(
        f"/api/users/{target_id}/password", json={"new_password": "newpass2"}
    )
    assert resp.status_code == 403
    # Password unchanged
    from mbr.auth.models import verify_user
    assert verify_user(db, "kowalski", "oldpass1") is not None
    # No audit entry
    count = db.execute(
        "SELECT COUNT(*) FROM audit_log WHERE event_type='auth.password_changed'"
    ).fetchone()[0]
    assert count == 0
```

- [ ] **Step 2: Run — verify failure**

```bash
rm -f data/batch_db.sqlite
pytest tests/test_audit_phase3_auth.py -k change_password -v
```

Expected: 404 (route doesn't exist).

- [ ] **Step 3: Add the route to `mbr/auth/routes.py`**

Edit `mbr/auth/routes.py`. Update imports at the top:

```python
from flask import redirect, url_for, request, session, render_template, jsonify

from mbr.auth import auth_bp
from mbr.shared.decorators import login_required, role_required
from mbr.db import db_session
from mbr.auth.models import verify_user, change_password
from mbr.shared import audit
```

Append the new route at the end of the file:

```python
@auth_bp.route("/api/users/<int:user_id>/password", methods=["POST"])
@role_required("admin")
def api_change_password(user_id):
    """Admin changes another user's password.

    Body: {"new_password": "..."} (min 6 chars)
    Logs auth.password_changed with target user info — never the password itself.
    """
    body = request.get_json(silent=True) or {}
    new_password = body.get("new_password", "")
    if len(new_password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    with db_session() as db:
        try:
            user = change_password(db, user_id, new_password)
        except ValueError as e:
            msg = str(e)
            status = 404 if "not found" in msg else 400
            return jsonify({"error": msg}), status

        audit.log_event(
            audit.EVENT_AUTH_PASSWORD_CHANGED,
            entity_type="user",
            entity_id=user_id,
            entity_label=user["login"],
            payload={
                "target_user_id": user_id,
                "target_user_login": user["login"],
            },
            db=db,
        )
        db.commit()

    return jsonify({"ok": True})
```

- [ ] **Step 4: Run — verify pass**

```bash
pytest tests/test_audit_phase3_auth.py -k change_password -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Run full suite — sanity**

```bash
pytest 2>&1 | tail -3
```

Expected: 304 passed, 16 skipped (302 baseline + 2 new). Delete `data/batch_db.sqlite` first if needed.

- [ ] **Step 6: Commit**

```bash
git add mbr/auth/routes.py tests/test_audit_phase3_auth.py
git commit -m "$(cat <<'COMMIT'
feat(audit): POST /api/users/<id>/password — admin password change + audit

Phase 3 Sub-PR 3.1 task 2. New admin-only endpoint for changing another
user's password. Validates length >=6, calls change_password() model,
then logs auth.password_changed with payload {target_user_id,
target_user_login} — never the password itself.

This is the second real log_event() call site after archive_old_entries
(Phase 2 Sub-PR 2.3), and the first that records actual user actor
(session admin) as opposed to the system actor.

2 tests cover happy path (password changed, audit entry exists, no
password material in payload) and 403 for non-admin.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase3-design.md
COMMIT
)"
```

---

### Task 3: Instrument `login()` (success + failure)

**Files:**
- Modify: `mbr/auth/routes.py`
- Test: `tests/test_audit_phase3_auth.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_audit_phase3_auth.py`:

```python
# ---------- POST /login ----------

def test_login_success_logs_auth_login_ok(anon_client, db):
    """Successful login → audit entry with result='ok' and session user as actor."""
    create_user(db, login="anna", password="goodpass", rola="laborant")

    resp = anon_client.post("/login", data={"login": "anna", "password": "goodpass"})
    assert resp.status_code in (302, 303)  # redirect after successful login

    rows = db.execute(
        "SELECT id, event_type, result, payload_json FROM audit_log WHERE event_type='auth.login'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["result"] == "ok"

    actors = db.execute(
        "SELECT actor_login, actor_rola FROM audit_log_actors WHERE audit_id=?",
        (rows[0]["id"],),
    ).fetchall()
    assert len(actors) == 1
    assert actors[0]["actor_login"] == "anna"
    assert actors[0]["actor_rola"] == "laborant"


def test_login_failure_logs_auth_login_error(anon_client, db):
    """Failed login → audit entry with result='error', actor_login='attempted',
    actor_rola='unknown', payload contains attempted_login."""
    create_user(db, login="anna", password="goodpass", rola="laborant")

    resp = anon_client.post("/login", data={"login": "anna", "password": "wrongpass"})
    # Login page re-renders on failure, no redirect
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT id, event_type, result, payload_json FROM audit_log WHERE event_type='auth.login'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["result"] == "error"

    import json as _json
    payload = _json.loads(rows[0]["payload_json"])
    assert payload["attempted_login"] == "anna"

    actors = db.execute(
        "SELECT worker_id, actor_login, actor_rola FROM audit_log_actors WHERE audit_id=?",
        (rows[0]["id"],),
    ).fetchall()
    assert len(actors) == 1
    assert actors[0]["worker_id"] is None
    assert actors[0]["actor_login"] == "anna"
    assert actors[0]["actor_rola"] == "unknown"


def test_login_failure_with_unknown_user_still_logs(anon_client, db):
    """Login attempt with completely unknown login → still produces an audit
    entry (result=error). Doesn't crash."""
    resp = anon_client.post(
        "/login", data={"login": "ghost_user", "password": "anything"}
    )
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT id, payload_json FROM audit_log WHERE event_type='auth.login'"
    ).fetchall()
    assert len(rows) == 1

    import json as _json
    payload = _json.loads(rows[0]["payload_json"])
    assert payload["attempted_login"] == "ghost_user"
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_audit_phase3_auth.py -k login -v
```

Expected: 3 tests fail (no audit entries get written; rows count is 0).

- [ ] **Step 3: Instrument `login()` route**

Edit `mbr/auth/routes.py`. Replace the existing `login()` function with:

```python
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        login_val = request.form.get("login", "")
        password = request.form.get("password", "")
        with db_session() as db:
            user = verify_user(db, login_val, password)
            if user:
                session["user"] = {
                    "login": user["login"],
                    "rola": user["rola"],
                    "imie_nazwisko": user.get("imie_nazwisko"),
                }
                audit.log_event(
                    audit.EVENT_AUTH_LOGIN,
                    payload={"attempted_login": login_val},
                    db=db,
                )
                db.commit()
                return redirect(url_for("auth.index"))

            # Failure path: log with explicit unknown actor
            audit.log_event(
                audit.EVENT_AUTH_LOGIN,
                payload={"attempted_login": login_val},
                actors=[{
                    "worker_id": None,
                    "actor_login": login_val,
                    "actor_rola": "unknown",
                }],
                result="error",
                db=db,
            )
            db.commit()
        error = "Nieprawidłowy login lub hasło"
    return render_template("login.html", error=error)
```

Notes on the change:
- `db_session()` is moved to wrap BOTH success and failure paths so a single connection handles `verify_user` AND the `log_event` call
- Success path: `session["user"] = ...` is set BEFORE `log_event` so `actors_from_request()` (called inside `log_event`) finds the user
- Failure path: `actors=` is passed explicitly so `log_event` doesn't try to read from session (which has no user)
- Both paths commit the audit entry inside the same transaction as the verification

- [ ] **Step 4: Run — verify pass**

```bash
pytest tests/test_audit_phase3_auth.py -k login -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Run full suite**

```bash
pytest 2>&1 | tail -3
```

Expected: 307 passed, 16 skipped (304 baseline + 3 new). Delete `data/batch_db.sqlite` first if needed.

- [ ] **Step 6: Commit**

```bash
git add mbr/auth/routes.py tests/test_audit_phase3_auth.py
git commit -m "$(cat <<'COMMIT'
feat(audit): instrument /login — auth.login (ok + error) events

Phase 3 Sub-PR 3.1 task 3. Both success and failure branches of /login
now produce an audit_log entry. Success uses session-based actor
resolution (after session['user'] is set). Failure uses explicit actors
list with worker_id=None, actor_login=<attempted>, actor_rola='unknown',
result='error', and payload={attempted_login}.

Failed login attempts with completely unknown loginy still produce
entries — useful for spotting brute-force or typo patterns.

3 tests cover success, failure with valid login + wrong password,
failure with completely unknown login.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase3-design.md
COMMIT
)"
```

---

### Task 4: Instrument `logout()`

**Files:**
- Modify: `mbr/auth/routes.py`
- Test: `tests/test_audit_phase3_auth.py`

- [ ] **Step 1: Append failing test**

Append to `tests/test_audit_phase3_auth.py`:

```python
# ---------- /logout ----------

def test_logout_logs_auth_logout(monkeypatch, db):
    """Logout produces an audit entry with the user being logged out as actor.
    Entry must be written BEFORE session.clear()."""
    create_user(db, login="anna", password="goodpass", rola="laborant")

    client = _make_client(monkeypatch, db, rola=None)
    # Manually set the session as if anna had logged in
    with client.session_transaction() as sess:
        sess["user"] = {"login": "anna", "rola": "laborant", "imie_nazwisko": "Anna K."}

    resp = client.get("/logout")
    assert resp.status_code in (302, 303)  # redirect to login

    rows = db.execute(
        "SELECT id FROM audit_log WHERE event_type='auth.logout'"
    ).fetchall()
    assert len(rows) == 1

    actors = db.execute(
        "SELECT actor_login, actor_rola FROM audit_log_actors WHERE audit_id=?",
        (rows[0]["id"],),
    ).fetchall()
    assert len(actors) == 1
    assert actors[0]["actor_login"] == "anna"
    assert actors[0]["actor_rola"] == "laborant"
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_audit_phase3_auth.py -k logout -v
```

Expected: fail — no audit entry produced by logout.

- [ ] **Step 3: Instrument `logout()`**

Edit `mbr/auth/routes.py`. Replace the existing `logout()`:

```python
@auth_bp.route("/logout")
def logout():
    if "user" in session:
        with db_session() as db:
            audit.log_event(
                audit.EVENT_AUTH_LOGOUT,
                db=db,
            )
            db.commit()
    session.clear()
    return redirect(url_for("auth.login"))
```

Notes:
- Guarded by `if "user" in session` because `actors_from_request()` raises `ValueError` if there's no session user. A logout call without a session is a no-op.
- `log_event` happens BEFORE `session.clear()` so `actors_from_request()` can read the user.

- [ ] **Step 4: Run — verify pass**

```bash
pytest tests/test_audit_phase3_auth.py -k logout -v
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

```bash
pytest 2>&1 | tail -3
```

Expected: 308 passed, 16 skipped.

- [ ] **Step 6: Commit**

```bash
git add mbr/auth/routes.py tests/test_audit_phase3_auth.py
git commit -m "$(cat <<'COMMIT'
feat(audit): instrument /logout — auth.logout event

Phase 3 Sub-PR 3.1 task 4. logout() now writes an auth.logout entry
BEFORE session.clear() so actors_from_request() can read the user
being logged out. Guarded with 'if user in session' so a logout call
without a session is a no-op (won't crash).

Sub-PR 3.1 complete: auth instrumentation lives. Login (success +
failure), logout, and admin password change all produce audit entries.

1 test covers the happy path; logged-out-without-session is implicit
(no entry produced because the guard skips).

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase3-design.md
COMMIT
)"
```

---

## Sub-PR 3.2: Workers instrumentation (Tasks 5-9)

---

### Task 5: Instrument `api_shift POST` — `shift.changed`

**Files:**
- Modify: `mbr/workers/routes.py`
- Test: `tests/test_audit_phase3_workers.py` (new file)

- [ ] **Step 1: Create test file with first failing test**

Create `tests/test_audit_phase3_workers.py`:

```python
"""Tests for Phase 3 workers instrumentation."""

import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    # Seed two workers so we can target them
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (1, 'Anna', 'Kowalska', 'AK', 'AK', 1)"
    )
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (2, 'Maria', 'Wojcik', 'MW', 'MW', 1)"
    )
    conn.commit()
    yield conn
    conn.close()


def _make_client(monkeypatch, db, rola="admin"):
    import mbr.db
    import mbr.workers.routes
    import mbr.admin.audit_routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.workers.routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.admin.audit_routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "tester", "rola": rola, "imie_nazwisko": None}
    return client


@pytest.fixture
def admin_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="admin")


@pytest.fixture
def laborant_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="laborant")


# ---------- POST /api/shift ----------

def test_shift_changed_logs_event(admin_client, db):
    """POST /api/shift produces shift.changed entry with payload={old, new},
    actor = session user (admin), NOT the new shift workers."""
    resp = admin_client.post("/api/shift", json={"worker_ids": [1, 2]})
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT id, event_type, payload_json FROM audit_log WHERE event_type='shift.changed'"
    ).fetchall()
    assert len(rows) == 1

    import json as _json
    payload = _json.loads(rows[0]["payload_json"])
    assert payload["old"] == []  # empty before
    assert payload["new"] == [1, 2]

    # Actor is the admin who made the change, NOT the new shift workers
    actors = db.execute(
        "SELECT actor_login, actor_rola FROM audit_log_actors WHERE audit_id=?",
        (rows[0]["id"],),
    ).fetchall()
    assert len(actors) == 1
    assert actors[0]["actor_login"] == "tester"
    assert actors[0]["actor_rola"] == "admin"


def test_shift_changed_records_old_value(admin_client, db):
    """A second POST captures the old value from the previous POST."""
    admin_client.post("/api/shift", json={"worker_ids": [1]})
    admin_client.post("/api/shift", json={"worker_ids": [1, 2]})

    rows = db.execute(
        "SELECT payload_json FROM audit_log WHERE event_type='shift.changed' ORDER BY id"
    ).fetchall()
    assert len(rows) == 2

    import json as _json
    p2 = _json.loads(rows[1]["payload_json"])
    assert p2["old"] == [1]
    assert p2["new"] == [1, 2]
```

- [ ] **Step 2: Run — verify failure**

```bash
rm -f data/batch_db.sqlite
pytest tests/test_audit_phase3_workers.py -k shift_changed -v
```

Expected: fail — no audit entries.

- [ ] **Step 3: Instrument `api_shift POST`**

Edit `mbr/workers/routes.py`. Update imports at top:

```python
from datetime import datetime

from flask import request, session, jsonify

from mbr.workers import workers_bp
from mbr.shared.decorators import login_required
from mbr.db import db_session
from mbr.workers.models import list_workers, update_worker_profile
from mbr.shared import audit
```

Replace the `api_shift` function with:

```python
@workers_bp.route("/api/shift", methods=["GET", "POST"])
@login_required
def api_shift():
    """Shift workers — shared globally via DB (same shift across all devices)."""
    import json as _json
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        worker_ids = [int(x) for x in data.get("worker_ids", []) if isinstance(x, (int, float))]
        with db_session() as db:
            # Read old value for the audit diff
            old_row = db.execute(
                "SELECT value FROM user_settings WHERE login='_system_' AND key='current_shift'"
            ).fetchone()
            old_ids = _json.loads(old_row["value"]) if old_row and old_row["value"] else []

            session["shift_workers"] = worker_ids
            db.execute(
                """INSERT INTO user_settings (login, key, value) VALUES ('_system_', 'current_shift', ?)
                   ON CONFLICT(login, key) DO UPDATE SET value=excluded.value""",
                (_json.dumps(worker_ids),),
            )
            audit.log_event(
                audit.EVENT_SHIFT_CHANGED,
                entity_type="shift",
                payload={"old": old_ids, "new": worker_ids},
                db=db,
            )
            db.commit()
        return jsonify({"ok": True})
    # GET: read from DB (shared), sync to session
    with db_session() as db:
        row = db.execute(
            "SELECT value FROM user_settings WHERE login='_system_' AND key='current_shift'"
        ).fetchone()
    if row and row["value"]:
        worker_ids = _json.loads(row["value"])
        session["shift_workers"] = worker_ids
        return jsonify({"worker_ids": worker_ids})
    return jsonify({"worker_ids": session.get("shift_workers", [])})
```

- [ ] **Step 4: Run — verify pass**

```bash
pytest tests/test_audit_phase3_workers.py -k shift_changed -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/workers/routes.py tests/test_audit_phase3_workers.py
git commit -m "$(cat <<'COMMIT'
feat(audit): instrument /api/shift POST — shift.changed event

Phase 3 Sub-PR 3.2 task 5. Reads the previous shift composition from
user_settings BEFORE the upsert, then logs shift.changed with
payload={old: [...], new: [...]}.

Per spec, the actor is the session user (admin/technolog/laborant
making the change), NOT the new shift workers — because the shift is
being SET, not used.

2 tests cover first set (old=[]) and update (old=previous).

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase3-design.md
COMMIT
)"
```

---

### Task 6: Instrument `api_worker_profile` — `worker.updated` with diff

**Files:**
- Modify: `mbr/workers/routes.py`
- Test: `tests/test_audit_phase3_workers.py`

- [ ] **Step 1: Append failing test**

Append to `tests/test_audit_phase3_workers.py`:

```python
# ---------- POST /api/worker/<id>/profile ----------

def test_worker_updated_profile_logs_event(admin_client, db):
    """Profile update produces worker.updated with diff of changed fields only."""
    resp = admin_client.post(
        "/api/worker/1/profile",
        json={"nickname": "AKowalska", "avatar_icon": 5, "avatar_color": 3},
    )
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT id, event_type, entity_type, entity_id, entity_label, diff_json "
        "FROM audit_log WHERE event_type='worker.updated'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["entity_type"] == "worker"
    assert rows[0]["entity_id"] == 1
    assert rows[0]["entity_label"] == "Anna Kowalska"

    import json as _json
    diff = _json.loads(rows[0]["diff_json"])
    fields = {d["pole"]: d for d in diff}
    assert fields["nickname"]["stara"] == "AK"
    assert fields["nickname"]["nowa"] == "AKowalska"
    assert fields["avatar_icon"]["stara"] == 0
    assert fields["avatar_icon"]["nowa"] == 5
    assert fields["avatar_color"]["stara"] == 0
    assert fields["avatar_color"]["nowa"] == 3


def test_worker_profile_no_change_no_log(admin_client, db):
    """If POST sends the same values that already exist, no audit entry."""
    # First call sets nickname to AKowalska
    admin_client.post("/api/worker/1/profile", json={"nickname": "AKowalska"})
    # Second call sends the same value
    admin_client.post("/api/worker/1/profile", json={"nickname": "AKowalska"})

    count = db.execute(
        "SELECT COUNT(*) FROM audit_log WHERE event_type='worker.updated'"
    ).fetchone()[0]
    # Only the first call produced an entry
    assert count == 1
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_audit_phase3_workers.py -k worker_updated -v
```

Expected: fail — no entries.

- [ ] **Step 3: Instrument `api_worker_profile`**

Edit `mbr/workers/routes.py`. Replace `api_worker_profile`:

```python
@workers_bp.route("/api/worker/<int:worker_id>/profile", methods=["POST"])
@login_required
def api_worker_profile(worker_id):
    data = request.get_json(silent=True) or {}
    with db_session() as db:
        # Snapshot before for the diff
        old_row = db.execute(
            "SELECT imie, nazwisko, nickname, avatar_icon, avatar_color FROM workers WHERE id=?",
            (worker_id,),
        ).fetchone()
        if old_row is None:
            return jsonify({"error": "not found"}), 404
        old = dict(old_row)

        update_worker_profile(db, worker_id,
            nickname=data.get("nickname"),
            avatar_icon=data.get("avatar_icon"),
            avatar_color=data.get("avatar_color"))

        # Snapshot after
        new_row = db.execute(
            "SELECT nickname, avatar_icon, avatar_color FROM workers WHERE id=?",
            (worker_id,),
        ).fetchone()
        new = dict(new_row)

        diff = audit.diff_fields(old, new, ["nickname", "avatar_icon", "avatar_color"])
        if diff:
            audit.log_event(
                audit.EVENT_WORKER_UPDATED,
                entity_type="worker",
                entity_id=worker_id,
                entity_label=f"{old['imie']} {old['nazwisko']}",
                diff=diff,
                db=db,
            )
            db.commit()
    return jsonify({"ok": True})
```

- [ ] **Step 4: Run — verify pass**

```bash
pytest tests/test_audit_phase3_workers.py -k worker_updated -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/workers/routes.py tests/test_audit_phase3_workers.py
git commit -m "$(cat <<'COMMIT'
feat(audit): instrument worker profile update — worker.updated with diff

Phase 3 Sub-PR 3.2 task 6. Snapshots the worker row before + after the
profile update and uses audit.diff_fields() to capture only the
changed fields. No diff → no audit entry (no-op writes don't pollute
the log).

2 tests cover diff content + no-op skip.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase3-design.md
COMMIT
)"
```

---

### Task 7: Instrument `api_add_worker` — `worker.created`

**Files:**
- Modify: `mbr/workers/routes.py`
- Test: `tests/test_audit_phase3_workers.py`

- [ ] **Step 1: Append failing test**

Append to `tests/test_audit_phase3_workers.py`:

```python
# ---------- POST /api/workers (add) ----------

def test_worker_created_logs_event(admin_client, db):
    resp = admin_client.post(
        "/api/workers",
        json={"imie": "Jan", "nazwisko": "Nowak", "nickname": "Janek"},
    )
    assert resp.status_code == 200
    new_id = resp.get_json()["id"]

    rows = db.execute(
        "SELECT id, entity_type, entity_id, entity_label, payload_json FROM audit_log "
        "WHERE event_type='worker.created'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["entity_type"] == "worker"
    assert rows[0]["entity_id"] == new_id
    assert rows[0]["entity_label"] == "Jan Nowak"

    import json as _json
    payload = _json.loads(rows[0]["payload_json"])
    assert payload["imie"] == "Jan"
    assert payload["nazwisko"] == "Nowak"
    assert payload["inicjaly"] == "JN"
    assert payload["nickname"] == "Janek"
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_audit_phase3_workers.py -k worker_created -v
```

- [ ] **Step 3: Instrument `api_add_worker`**

Replace in `mbr/workers/routes.py`:

```python
@workers_bp.route("/api/workers", methods=["POST"])
@login_required
def api_add_worker():
    from mbr.workers.models import add_worker
    data = request.get_json(silent=True) or {}
    imie = (data.get("imie") or "").strip()
    nazwisko = (data.get("nazwisko") or "").strip()
    if not imie or not nazwisko:
        return jsonify({"error": "imie and nazwisko required"}), 400
    inicjaly = (imie[0] + nazwisko[0]).upper()
    nickname = (data.get("nickname") or "").strip()
    with db_session() as db:
        wid = add_worker(db, imie, nazwisko, inicjaly, nickname)
        audit.log_event(
            audit.EVENT_WORKER_CREATED,
            entity_type="worker",
            entity_id=wid,
            entity_label=f"{imie} {nazwisko}",
            payload={
                "imie": imie,
                "nazwisko": nazwisko,
                "inicjaly": inicjaly,
                "nickname": nickname,
            },
            db=db,
        )
        db.commit()
    return jsonify({"ok": True, "id": wid})
```

- [ ] **Step 4: Run — verify pass**

```bash
pytest tests/test_audit_phase3_workers.py -k worker_created -v
```

- [ ] **Step 5: Commit**

```bash
git add mbr/workers/routes.py tests/test_audit_phase3_workers.py
git commit -m "$(cat <<'COMMIT'
feat(audit): instrument worker creation — worker.created event

Phase 3 Sub-PR 3.2 task 7. Logs worker.created with payload containing
the seed fields (imie, nazwisko, inicjaly, nickname). entity_id is
the new worker's primary key.

1 test covers the happy path.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase3-design.md
COMMIT
)"
```

---

### Task 8: Instrument `api_toggle_worker` — `worker.updated` (aktywny diff)

**Files:**
- Modify: `mbr/workers/routes.py`
- Test: `tests/test_audit_phase3_workers.py`

- [ ] **Step 1: Append failing test**

Append to `tests/test_audit_phase3_workers.py`:

```python
# ---------- POST /api/workers/<id>/toggle ----------

def test_worker_toggled_logs_event(admin_client, db):
    resp = admin_client.post("/api/workers/1/toggle")
    assert resp.status_code == 200
    new_val = resp.get_json()["aktywny"]
    assert new_val == 0  # was 1, now 0

    rows = db.execute(
        "SELECT id, entity_type, entity_id, entity_label, diff_json FROM audit_log "
        "WHERE event_type='worker.updated' AND entity_id=1"
    ).fetchall()
    assert len(rows) == 1

    import json as _json
    diff = _json.loads(rows[0]["diff_json"])
    assert diff == [{"pole": "aktywny", "stara": 1, "nowa": 0}]


def test_worker_toggled_unknown_returns_404_no_log(admin_client, db):
    resp = admin_client.post("/api/workers/999/toggle")
    assert resp.status_code == 404
    count = db.execute(
        "SELECT COUNT(*) FROM audit_log WHERE event_type='worker.updated'"
    ).fetchone()[0]
    assert count == 0
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_audit_phase3_workers.py -k worker_toggled -v
```

- [ ] **Step 3: Instrument `api_toggle_worker`**

Replace in `mbr/workers/routes.py`:

```python
@workers_bp.route("/api/workers/<int:worker_id>/toggle", methods=["POST"])
@login_required
def api_toggle_worker(worker_id):
    from mbr.workers.models import toggle_worker_active
    with db_session() as db:
        # Snapshot before for the audit entry (label + diff)
        before_row = db.execute(
            "SELECT imie, nazwisko, aktywny FROM workers WHERE id=?",
            (worker_id,),
        ).fetchone()
        if before_row is None:
            return jsonify({"error": "not found"}), 404
        old_aktywny = before_row["aktywny"]

        new_val = toggle_worker_active(db, worker_id)
        if new_val is None:
            return jsonify({"error": "not found"}), 404

        audit.log_event(
            audit.EVENT_WORKER_UPDATED,
            entity_type="worker",
            entity_id=worker_id,
            entity_label=f"{before_row['imie']} {before_row['nazwisko']}",
            diff=[{"pole": "aktywny", "stara": old_aktywny, "nowa": new_val}],
            db=db,
        )
        db.commit()
    return jsonify({"ok": True, "aktywny": new_val})
```

- [ ] **Step 4: Run — verify pass**

```bash
pytest tests/test_audit_phase3_workers.py -k worker_toggled -v
```

- [ ] **Step 5: Commit**

```bash
git add mbr/workers/routes.py tests/test_audit_phase3_workers.py
git commit -m "$(cat <<'COMMIT'
feat(audit): instrument worker toggle — worker.updated (aktywny diff)

Phase 3 Sub-PR 3.2 task 8. Reads aktywny BEFORE the toggle so the
diff contains both old and new values. Uses worker.updated event_type
(per spec — no separate worker.activated/deactivated events).

2 tests cover happy path and 404 (no audit entry on missing worker).

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase3-design.md
COMMIT
)"
```

---

### Task 9: Instrument `api_delete_worker` — `worker.deleted`

**Files:**
- Modify: `mbr/workers/routes.py`
- Test: `tests/test_audit_phase3_workers.py`

- [ ] **Step 1: Append failing test**

Append to `tests/test_audit_phase3_workers.py`:

```python
# ---------- DELETE /api/workers/<id> ----------

def test_worker_deleted_logs_event_with_snapshot(admin_client, db):
    resp = admin_client.delete("/api/workers/1")
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT id, entity_type, entity_id, entity_label, payload_json FROM audit_log "
        "WHERE event_type='worker.deleted'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["entity_type"] == "worker"
    assert rows[0]["entity_id"] == 1
    assert rows[0]["entity_label"] == "Anna Kowalska"

    import json as _json
    payload = _json.loads(rows[0]["payload_json"])
    # Snapshot of the deleted row
    assert payload["imie"] == "Anna"
    assert payload["nazwisko"] == "Kowalska"
    assert payload["inicjaly"] == "AK"


def test_worker_delete_unknown_no_log(admin_client, db):
    """Deleting a non-existent worker is idempotent (delete_worker doesn't
    raise) but produces no audit entry."""
    resp = admin_client.delete("/api/workers/999")
    assert resp.status_code == 200  # current model is idempotent
    count = db.execute(
        "SELECT COUNT(*) FROM audit_log WHERE event_type='worker.deleted'"
    ).fetchone()[0]
    assert count == 0
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_audit_phase3_workers.py -k worker_deleted -v
```

- [ ] **Step 3: Instrument `api_delete_worker`**

Replace in `mbr/workers/routes.py`:

```python
@workers_bp.route("/api/workers/<int:worker_id>", methods=["DELETE"])
@login_required
def api_delete_worker(worker_id):
    from mbr.workers.models import delete_worker
    with db_session() as db:
        # Snapshot before delete for the audit payload
        snapshot_row = db.execute(
            "SELECT imie, nazwisko, inicjaly, nickname, avatar_icon, avatar_color, aktywny "
            "FROM workers WHERE id=?",
            (worker_id,),
        ).fetchone()

        delete_worker(db, worker_id)

        if snapshot_row is not None:
            snapshot = dict(snapshot_row)
            audit.log_event(
                audit.EVENT_WORKER_DELETED,
                entity_type="worker",
                entity_id=worker_id,
                entity_label=f"{snapshot['imie']} {snapshot['nazwisko']}",
                payload=snapshot,
                db=db,
            )
            db.commit()
    return jsonify({"ok": True})
```

- [ ] **Step 4: Run — verify pass**

```bash
pytest tests/test_audit_phase3_workers.py -k worker_deleted -v
```

- [ ] **Step 5: Run full Sub-PR 3.2 tests + full suite**

```bash
pytest tests/test_audit_phase3_workers.py 2>&1 | tail -3
pytest 2>&1 | tail -3
```

Expected: 8 phase3_workers tests pass (2 shift + 2 profile + 1 created + 2 toggled + 2 deleted = 9? Let me count). Actually 9 tests in the workers file. Full suite: 308 baseline + 9 new = 317 passed.

- [ ] **Step 6: Commit**

```bash
git add mbr/workers/routes.py tests/test_audit_phase3_workers.py
git commit -m "$(cat <<'COMMIT'
feat(audit): instrument worker delete — worker.deleted with snapshot

Phase 3 Sub-PR 3.2 task 9. Snapshots the worker row BEFORE the delete
so the audit payload preserves all fields for forensic recovery.
delete_worker model is idempotent (no error on missing row), so the
route only logs when the snapshot exists.

Sub-PR 3.2 complete: workers instrumentation lives. shift.changed,
worker.created, worker.updated (profile + toggle), worker.deleted —
5 events across 5 endpoints all produce audit entries.

2 tests cover happy path with snapshot + no-op delete (no entry).

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase3-design.md
COMMIT
)"
```

---

## Sub-PR 3.3: Shift fallback removal (Tasks 10-11)

---

### Task 10: `_resolve_actor_label` raises `ShiftRequiredError` for laborant

**Files:**
- Modify: `mbr/laborant/routes.py` (~5 LOC change in `_resolve_actor_label`)
- Modify: `tests/test_uwagi.py` (existing helper test needs update)
- Test: `tests/test_audit_phase3_shift_required.py` (new file)

- [ ] **Step 1: Update existing helper test**

Find `test_resolve_actor_label_falls_back_to_login_when_no_shift` in `tests/test_uwagi.py` (around line 380). Replace it with:

```python
def test_resolve_actor_label_falls_back_to_login_for_non_laborant_roles(db):
    """Empty shift_workers → autor = session login for admin/technolog/laborant_kj/laborant_coa.
    For role 'laborant', see test_resolve_actor_label_laborant_empty_shift_raises."""
    from flask import Flask
    from mbr.laborant.routes import _resolve_actor_label
    app = Flask(__name__)
    app.secret_key = "test"
    for rola in ("admin", "technolog", "laborant_kj", "laborant_coa"):
        with app.test_request_context():
            from flask import session
            session["user"] = {"login": "shared_lab", "rola": rola}
            assert _resolve_actor_label(db) == "shared_lab"


def test_resolve_actor_label_laborant_empty_shift_raises(db):
    """Empty shift_workers + role='laborant' → ShiftRequiredError (Phase 3 enforcement)."""
    from flask import Flask
    from mbr.laborant.routes import _resolve_actor_label
    from mbr.shared.audit import ShiftRequiredError
    import pytest as _pytest
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context():
        from flask import session
        session["user"] = {"login": "shared_lab", "rola": "laborant"}
        with _pytest.raises(ShiftRequiredError):
            _resolve_actor_label(db)
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_uwagi.py -k "resolve_actor_label_laborant_empty_shift_raises or resolve_actor_label_falls_back_to_login_for_non_laborant_roles" -v
```

Expected: `test_resolve_actor_label_laborant_empty_shift_raises` fails (no exception raised — current behavior is fallback to login).

- [ ] **Step 3: Modify `_resolve_actor_label`**

Find `_resolve_actor_label` in `mbr/laborant/routes.py` (around line 22 from the uwagi-fix commit). Replace the function with:

```python
def _resolve_actor_label(db, override: str = None) -> str:
    """Resolve a human-readable actor string for write operations.

    Resolution order:
      1. `override` if non-empty (form/body explicit pick — e.g. uwagi picker)
      2. session['shift_workers'] joined by ', ' using nickname || inicjaly
      3. For role 'laborant' with empty shift → ShiftRequiredError (Phase 3
         enforcement: laborant cannot write without a confirmed shift).
      4. For other roles (admin/technolog/laborant_kj/laborant_coa) with empty
         shift → fallback to session['user']['login'].
    """
    if override:
        cleaned = override.strip()
        if cleaned:
            return cleaned

    shift_ids = session.get("shift_workers", []) or []
    if shift_ids:
        placeholders = ",".join("?" * len(shift_ids))
        rows = db.execute(
            f"SELECT inicjaly, nickname FROM workers WHERE id IN ({placeholders})",
            shift_ids,
        ).fetchall()
        if rows:
            return ", ".join((r["nickname"] or r["inicjaly"]) for r in rows)

    rola = session.get("user", {}).get("rola")
    if rola == "laborant":
        from mbr.shared.audit import ShiftRequiredError
        raise ShiftRequiredError()

    return session["user"]["login"]
```

- [ ] **Step 4: Run helper tests — verify pass**

```bash
pytest tests/test_uwagi.py -k "resolve_actor_label_laborant_empty_shift_raises or resolve_actor_label_falls_back_to_login_for_non_laborant_roles" -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Create integration test file**

Create `tests/test_audit_phase3_shift_required.py`:

```python
"""Tests for Phase 3 enforcement: laborant write paths must have confirmed shift."""

import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    # Seed two workers for the shift_workers reference
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (1, 'Anna', 'Kowalska', 'AK', 'AK', 1)"
    )
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (2, 'Maria', 'Wojcik', 'MW', 'MW', 1)"
    )
    # Seed an MBR template + open EBR for the save_entry test
    from datetime import datetime
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "utworzony_przez, dt_utworzenia) VALUES (?, 1, 'active', '[]', '{}', 'test', ?)",
        ("TestProduct", now),
    )
    mbr_id = conn.execute(
        "SELECT mbr_id FROM mbr_templates WHERE produkt='TestProduct'"
    ).fetchone()["mbr_id"]
    conn.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, typ) "
        "VALUES (?, ?, ?, ?, 'open', 'szarza')",
        (mbr_id, "TestProduct__1", "1/2026", now),
    )
    conn.commit()
    yield conn
    conn.close()


def _make_client(monkeypatch, db, rola="laborant", shift_workers=None):
    import mbr.db
    import mbr.laborant.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "shared_lab", "rola": rola}
        if shift_workers is not None:
            sess["shift_workers"] = shift_workers
    return client


# ---------- save_entry shift enforcement ----------

def test_save_entry_laborant_empty_shift_returns_400(monkeypatch, db):
    """Laborant POST /laborant/ebr/<id>/save with no shift → 400 shift_required,
    no row written to ebr_wyniki."""
    client = _make_client(monkeypatch, db, rola="laborant", shift_workers=[])
    resp = client.post(
        "/laborant/ebr/1/save",
        json={"sekcja": "analiza", "values": {"sm": 87}},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body == {"error": "shift_required"}

    # No row in ebr_wyniki
    count = db.execute("SELECT COUNT(*) FROM ebr_wyniki").fetchone()[0]
    assert count == 0


def test_save_entry_laborant_with_shift_succeeds(monkeypatch, db):
    """Laborant with confirmed shift can save normally."""
    client = _make_client(monkeypatch, db, rola="laborant", shift_workers=[1, 2])
    resp = client.post(
        "/laborant/ebr/1/save",
        json={"sekcja": "analiza", "values": {"sm": 87}},
    )
    assert resp.status_code == 200


# ---------- save_uwagi shift enforcement (symmetric) ----------

def test_save_uwagi_laborant_empty_shift_returns_400(monkeypatch, db):
    client = _make_client(monkeypatch, db, rola="laborant", shift_workers=[])
    resp = client.put("/api/ebr/1/uwagi", json={"tekst": "Test note"})
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "shift_required"}
    # No row in ebr_uwagi_history
    count = db.execute("SELECT COUNT(*) FROM ebr_uwagi_history").fetchone()[0]
    assert count == 0


# ---------- non-laborant roles still fall back to login ----------

def test_save_entry_admin_empty_shift_succeeds(monkeypatch, db):
    """Admin/technolog/laborant_kj/laborant_coa keep the login fallback when
    shift is empty — only role='laborant' is enforced."""
    client = _make_client(monkeypatch, db, rola="admin", shift_workers=[])
    resp = client.post(
        "/laborant/ebr/1/save",
        json={"sekcja": "analiza", "values": {"sm": 87}},
    )
    assert resp.status_code == 200
```

- [ ] **Step 6: Run integration tests — verify pass**

```bash
rm -f data/batch_db.sqlite
pytest tests/test_audit_phase3_shift_required.py -v
```

Expected: 4 tests PASS.

If `test_save_entry_admin_empty_shift_succeeds` fails because the shift_required handler intercepts even admin requests, that's a bug in `_resolve_actor_label` — verify the `if rola == 'laborant':` check is BEFORE the fallback `return session["user"]["login"]`.

- [ ] **Step 7: Run full suite**

```bash
pytest 2>&1 | tail -3
```

Expected: 321 passed, 16 skipped (317 baseline + 4 new — but actually only +3 new because one of the tests is the modified existing one in test_uwagi.py, so net +3 to that file too — count check after run).

Actually count: phase3_auth (6 tests) + phase3_workers (9 tests) + phase3_shift_required (4 tests) + 1 modification (test_uwagi.py: replaced 1 test with 2) = 6 + 9 + 4 + (+1) = 20 new tests total. Baseline 302 + 20 = 322. The actual number depends on how many tests were in the existing test_uwagi.py file before the change.

- [ ] **Step 8: Commit**

```bash
git add mbr/laborant/routes.py tests/test_uwagi.py tests/test_audit_phase3_shift_required.py
git commit -m "$(cat <<'COMMIT'
fix(audit): _resolve_actor_label raises ShiftRequiredError for laborant

Phase 3 Sub-PR 3.3 task 10. Behaviour change: rola='laborant' with
empty session['shift_workers'] no longer falls back to
session['user']['login']. Instead it raises ShiftRequiredError, which
the Flask error handler (added in Phase 1) translates to HTTP 400
{'error': 'shift_required'}.

Other roles (admin/technolog/laborant_kj/laborant_coa) keep the login
fallback — only laborant write paths are enforced, because only
laboranci share a kiosk login and need shift confirmation to know
who actually wrote the entry.

Tests:
- Existing helper test split into two: non-laborant fallback +
  laborant raises (replaces test_resolve_actor_label_falls_back_to_
  login_when_no_shift in test_uwagi.py)
- New integration tests in test_audit_phase3_shift_required.py:
  save_entry blocked for laborant with empty shift, save_entry succeeds
  for laborant with shift, save_uwagi blocked for laborant with empty
  shift, save_entry succeeds for admin with empty shift.

Frontend handlers wired in next task.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase3-design.md
COMMIT
)"
```

---

### Task 11: Frontend handlers for `shift_required`

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html` (3-5 JS handlers get the shift_required check)

**No automated tests for this task** — the partial is JS that calls endpoints already covered by Task 10's integration tests. Manual smoke verifies the modal opens.

- [ ] **Step 1: Find all JS handlers that POST to `/laborant/ebr/...` or `/api/ebr/.../uwagi`**

Run:

```bash
grep -n "fetch.*'/laborant/ebr\|fetch.*'/api/ebr.*uwagi\|/laborant/ebr.*save\|/laborant/ebr.*complete\|method.*['\"]POST" mbr/templates/laborant/_fast_entry_content.html | head -30
```

Look for `await fetch(...)` calls inside `_uwagiSave`, `_uwagiClear`, save handlers, complete handlers.

- [ ] **Step 2: Define a helper function and use it in each write handler**

Near the top of the existing `<script>` block in `_fast_entry_content.html` (after `var _uwagiState = null;` declarations), add a global helper:

```javascript
// Phase 3: shift_required handler — opens shift modal when backend rejects
// laborant write because no shift is confirmed.
async function _handleShiftRequired(resp) {
    if (resp.status !== 400) return false;
    var body = await resp.clone().json().catch(function() { return {}; });
    if (body.error !== 'shift_required') return false;
    if (typeof openShiftModal === 'function') {
        openShiftModal();
    } else {
        alert('Wymagana potwierdzona zmiana przed zapisem. Otwórz modal Zmiana w nagłówku.');
    }
    return true;
}
```

- [ ] **Step 3: Update `_uwagiSave` handler**

Find the existing `async function _uwagiSave()` and add the shift_required check right after the `fetch` call (before the existing 4xx handling):

```javascript
async function _uwagiSave() {
    var ta = document.getElementById('cv-notes-text');
    if (!ta || !_uwagiCurrentEbrId) return;
    var tekst = ta.value;
    if (tekst.length > 500) return;
    var body = { tekst: tekst };
    var autorOverride = _uwagiAutorOverrideString();
    if (autorOverride) body.autor = autorOverride;
    try {
        var resp = await fetch('/api/ebr/' + _uwagiCurrentEbrId + '/uwagi', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (await _handleShiftRequired(resp)) return;
        if (!resp.ok) {
            var err = await resp.json().catch(function() { return { error: 'błąd' }; });
            alert(err.error || 'Błąd zapisu notatki');
            return;
        }
        _uwagiState = await resp.json();
        _uwagiEditMode = false;
        _uwagiAutorOverride = null;
        var block = document.getElementById('cv-notes-block');
        if (block) block.outerHTML = _renderUwagiBlock(typeof userRola !== 'undefined' && userRola !== 'technolog');
    } catch (e) {
        alert('Błąd zapisu: ' + e.message);
    }
}
```

- [ ] **Step 4: Update `_uwagiClear` handler**

Find `async function _uwagiClear()` and add the same check:

```javascript
async function _uwagiClear() {
    if (!_uwagiCurrentEbrId) return;
    if (!confirm('Na pewno usunąć notatkę?')) return;
    try {
        var resp = await fetch('/api/ebr/' + _uwagiCurrentEbrId + '/uwagi', { method: 'DELETE' });
        if (await _handleShiftRequired(resp)) return;
        if (!resp.ok) {
            var err = await resp.json().catch(function() { return { error: 'błąd' }; });
            alert(err.error || 'Błąd usuwania');
            return;
        }
        _uwagiState = await resp.json();
        // ... rest unchanged
```

- [ ] **Step 5: Update the `save_entry` (results) handler**

Find the JS handler that POSTs to `/laborant/ebr/<id>/save` (likely named something like `saveEntry`, `_saveResults`, or inside a button onclick). Add the same check after its `await fetch(...)`:

```javascript
var resp = await fetch('/laborant/ebr/' + ebrId + '/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sekcja: sekcja, values: values }),
});
if (await _handleShiftRequired(resp)) return;
// ... existing handling
```

If you find more than one save-style handler, apply to each.

- [ ] **Step 6: Update the `complete_entry` handler if it exists**

Find any JS that POSTs to `/laborant/ebr/<id>/complete` and add the same check.

- [ ] **Step 7: Manual smoke test**

The dev server should be running with hot reload (or restart it):

```bash
python -c "
from mbr.app import create_app
app = create_app()
client = app.test_client()
# Simulate a laborant with empty shift trying to save uwagi
with client.session_transaction() as sess:
    sess['user'] = {'login': 'shared_lab', 'rola': 'laborant'}
    sess['shift_workers'] = []
# This will return 400 shift_required
import json
# (Can't test the modal opening here — that's a browser interaction.)
print('Verified setup works without crashes')
"
```

In a real browser:
1. Log in as a laborant test account
2. Make sure shift is NOT confirmed (open shift modal, cancel without picking)
3. Open any szarża, try to save uwagi → shift modal should auto-open
4. Confirm shift, save uwagi again → should work normally

- [ ] **Step 8: Run full pytest one last time — sanity**

```bash
rm -f data/batch_db.sqlite
pytest 2>&1 | tail -3
```

Expected: All tests still pass (no test changes in this task — just JS).

- [ ] **Step 9: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "$(cat <<'COMMIT'
feat(audit): frontend handlers for shift_required → openShiftModal

Phase 3 Sub-PR 3.3 task 11. Adds _handleShiftRequired() helper to the
laborant fast-entry template and wires it into all write handlers
(_uwagiSave, _uwagiClear, save_entry, complete_entry where present).

When backend returns 400 with body {error: 'shift_required'} (which
happens when role='laborant' and shift_workers is empty), the helper
opens the shift modal automatically, prompting the laborant to
confirm who is on shift before retrying the action.

No automated tests for this task — Task 10 already covers the
backend 400 response. Frontend behaviour verified by manual smoke
test (open szarża as laborant with empty shift, try to save uwagi,
shift modal pops up).

Sub-PR 3.3 complete. Phase 3 done — auth + workers integrated,
laborant write enforcement live.

Ref: docs/superpowers/specs/2026-04-11-audit-trail-phase3-design.md
COMMIT
)"
```

---

## Phase 3 Done Definition

After Task 11:

- [ ] `mbr/auth/models.py::change_password()` exists with bcrypt + length validation
- [ ] `mbr/auth/routes.py` has `POST /api/users/<id>/password` admin-only + audit
- [ ] `mbr/auth/routes.py::login()` logs `auth.login` (ok + error) on every attempt
- [ ] `mbr/auth/routes.py::logout()` logs `auth.logout` before clearing session
- [ ] `mbr/workers/routes.py` 5 endpoints all log their respective events
- [ ] `mbr/laborant/routes.py::_resolve_actor_label` raises `ShiftRequiredError` for `rola='laborant'` on empty shift
- [ ] Frontend handlers in `_fast_entry_content.html` open shift modal on 400 shift_required
- [ ] `tests/test_audit_phase3_auth.py` has 6 passing tests
- [ ] `tests/test_audit_phase3_workers.py` has 9 passing tests
- [ ] `tests/test_audit_phase3_shift_required.py` has 4 passing tests
- [ ] `tests/test_uwagi.py` updated helper test (replaced 1 with 2)
- [ ] Full `pytest` is green: ≈325 passed, 16 skipped, 0 failed (302 baseline + ~23 new tests)
- [ ] Manual smoke: log in/out as admin, change password, edit worker, toggle worker, delete worker, set shift — all show in `/admin/audit`
- [ ] Manual smoke: laborant tries to save uwagi without shift → shift modal pops up automatically
- [ ] Manual smoke: laborant with shift confirms uwagi → save works normally

## Deployment note

Phase 3 is **schema-stable** — no DB migration. Auto-deploy on prod will:
1. `git pull` (Phase 3 commits)
2. `pip install` (no new deps)
3. `migrate_audit_log_v2.py` — no-op (already migrated)
4. `backfill_audit_legacy_to_ebr.py` — no-op (already backfilled)
5. `systemctl restart lims`

After restart, **behaviour change is live**:
- Every login/logout logs to audit_log
- Workers operations log
- Laboranci must confirm shift before any save action — they will see the shift modal pop up the first time they try to save without a confirmed shift

**Communication needed to laboranci**: brief notice "od dziś każdy zapis wymaga potwierdzonej zmiany — system sam pokaże modal, klikajcie odpowiednie osoby". The shift confirmation flow already exists from earlier features (shift modal in `base.html`) — Phase 3 just makes it mandatory for laborant writes.
