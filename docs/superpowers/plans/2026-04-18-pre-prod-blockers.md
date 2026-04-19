# Pre-Production Blockers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix nine production blockers identified by the pre-prod code review — without breaking the 769 passing tests and without disturbing working prod state.

**Architecture:** Each blocker is addressed in a standalone task, ordered from trivial/isolated → schema → client-facing (XSS) → auth → config → deploy infrastructure. TDD is applied wherever a regression test is reproducible; trivial fixes (syntax, conflict markers, config literals) skip the test step. Every task ends with the full test suite passing and a standalone commit so any single fix can be reverted cleanly.

**Tech Stack:** Flask, raw sqlite3, pytest, Jinja2, vanilla JS, bcrypt, systemd, gunicorn.

**Baseline verification** (run before Task 1 to confirm starting state):

```bash
pytest -q
# Expect: 769 passed, 19 skipped
```

**Guard rails (apply to every task):**

1. Each task ends with `pytest -q` green (no new failures vs. baseline).
2. One commit per task — use the commit message shown in the task.
3. Do NOT touch `data/batch_db.sqlite` or any production artifact — all changes are code/config only.
4. Do NOT run `migrate_roles.py` or any migration script against the real DB during this work; tests use in-memory fixtures.

---

## Task 1: Remove stray merge conflict marker (B1)

**Blocker:** `mbr/admin/routes.py:372` contains a leftover `<<<<<<< HEAD` line inside a docstring. It parses (because it's inside a string literal) but is a red flag and would confuse any future merge.

**Files:**
- Modify: `mbr/admin/routes.py:372`

- [ ] **Step 1: Inspect current state**

Run:
```bash
sed -n '369,378p' mbr/admin/routes.py
```

Expected output:
```
@admin_bp.route("/api/completed")
def api_completed():
    """Return completed batches with sync_seq > since.
<<<<<<< HEAD

    Query params:
        since (int): last known sync_seq (default 0 = return all)
        ref_hash (str): client's reference table hash (optional)
    """
```

- [ ] **Step 2: Delete the marker line**

Edit `mbr/admin/routes.py`: delete the single line `<<<<<<< HEAD` (line 372). The docstring body immediately before (`"""Return completed batches with sync_seq > since.`) and after (blank line then `    Query params:`) stays intact.

After edit, lines 369–377 should read:
```
@admin_bp.route("/api/completed")
def api_completed():
    """Return completed batches with sync_seq > since.

    Query params:
        since (int): last known sync_seq (default 0 = return all)
        ref_hash (str): client's reference table hash (optional)
    """
```

- [ ] **Step 3: Verify no other conflict markers remain**

Run:
```bash
grep -rn '<<<<<<<\|>>>>>>>\|^=======$' mbr/ deploy/ scripts/ migrate_*.py schema_v4.sql 2>/dev/null
```

Expected: empty output.

- [ ] **Step 4: Run tests**

Run: `pytest -q`
Expected: `769 passed, 19 skipped`.

- [ ] **Step 5: Commit**

```bash
git add mbr/admin/routes.py
git commit -m "fix(admin): remove stray merge conflict marker in /api/completed docstring"
```

---

## Task 2: Stop running migrate_roles.py on every deploy (B5 + B9)

**Blocker:**
- B5: `deploy/auto-deploy.sh:41` invokes `migrate_roles.py` on every deploy. The script resets passwords for `lab` / `cert` users (`bcrypt.hashpw(b"lab", ...)`, `bcrypt.hashpw(b"cert", ...)`) — idempotency guard prevents this after first run, but the script is no longer needed and leaves a footgun.
- B9: `migrate_roles.py:45` CHECK constraint is `CHECK(rola IN ('technolog', 'lab', 'cert', 'admin'))` — missing `'produkcja'`. If this migration ever ran against a DB without the produkcja role registered yet, it would re-create `mbr_users` with a CHECK that rejects the `produkcja` role — silently corrupting newly created users until `init_mbr_tables()` runs its rebuild migration.

**Decision:** The migration has already been executed on production (idempotency guard at `migrate_roles.py:19-23` confirms — it returns early if any row has `rola='lab'`). We stop invoking it from deploy and mark the file itself as historical. We do NOT delete the file (a dev bootstrapping a fresh DB from pre-rename state could still need it one-time).

**Files:**
- Modify: `deploy/auto-deploy.sh:41` (remove one line)
- Modify: `migrate_roles.py:1-12` (update docstring — historical notice + fix CHECK)

- [ ] **Step 1: Confirm current state of auto-deploy.sh**

Run:
```bash
sed -n '40,43p' deploy/auto-deploy.sh
```

Expected:
```
/opt/lims/venv/bin/python scripts/migrate_uwagi_to_audit.py --db data/batch_db.sqlite
/opt/lims/venv/bin/python migrate_roles.py
/opt/lims/venv/bin/python scripts/backfill_cert_name_en.py --db data/batch_db.sqlite
```

- [ ] **Step 2: Remove the migrate_roles.py line from auto-deploy.sh**

Edit `deploy/auto-deploy.sh`: delete exactly line 41 (`/opt/lims/venv/bin/python migrate_roles.py`). Leave surrounding lines untouched.

After edit, lines 40–42 should read:
```
/opt/lims/venv/bin/python scripts/migrate_uwagi_to_audit.py --db data/batch_db.sqlite
/opt/lims/venv/bin/python scripts/backfill_cert_name_en.py --db data/batch_db.sqlite
/opt/lims/venv/bin/python scripts/migrate_cert_to_etapy.py
```

- [ ] **Step 3: Fix migrate_roles.py CHECK constraint and mark as historical**

Edit `migrate_roles.py`:

Replace the file's current docstring (lines 1-8):
```python
"""One-time migration: rename lab roles.

laborant / laborant_kj → lab
laborant_coa → cert

Recreates mbr_users with updated CHECK constraint, updates login+rola+password.
Idempotent — skips if 'lab' role already exists.
"""
```

with:
```python
"""One-time migration: rename lab roles (HISTORICAL — already applied on prod).

laborant / laborant_kj → lab
laborant_coa → cert

No longer invoked by deploy/auto-deploy.sh. Kept in-repo only for dev boxes that
still hold pre-rename user rows. Idempotent — returns early if any user has
rola='lab'.
"""
```

Replace line 45 (the CHECK constraint) — old:
```python
            rola            TEXT NOT NULL CHECK(rola IN ('technolog', 'lab', 'cert', 'admin')),
```
with:
```python
            rola            TEXT NOT NULL CHECK(rola IN ('technolog', 'lab', 'cert', 'kj', 'admin', 'produkcja')),
```

This mirrors the canonical CHECK defined in `mbr/models.py:22` so re-running on a dev box can never reject produkcja/kj roles.

- [ ] **Step 4: Run tests**

Run: `pytest -q`
Expected: `769 passed, 19 skipped` (no tests touch migrate_roles.py directly — it is a standalone script).

- [ ] **Step 5: Verify auto-deploy.sh still shell-parses**

Run:
```bash
bash -n deploy/auto-deploy.sh
```
Expected: exit code 0, no output.

- [ ] **Step 6: Commit**

```bash
git add deploy/auto-deploy.sh migrate_roles.py
git commit -m "fix(deploy): stop running migrate_roles.py on every deploy; align CHECK with canonical roles

migrate_roles.py already applied on prod (idempotency guard confirms).
Removing it from auto-deploy.sh eliminates password-reset risk on rerun.
Fixed the historical script's CHECK to include produkcja/kj so any dev-box
re-run cannot downgrade the role set."
```

---

## Task 3: Fix mbr_users CHECK rebuild to preserve all existing columns (B2)

**Blocker:** `mbr/models.py:1028-1056` rebuilds `mbr_users` to add `'produkcja'` to the rola CHECK. The rebuild explicitly creates `mbr_users_new_prodcheck` with **5** columns (user_id, login, password_hash, rola, imie_nazwisko) — but a later migration at `mbr/models.py:1463` adds a 6th column, `default_grupa`. On a DB that already has 6 columns and still has old CHECK (no `'produkcja'`), the rebuild's `INSERT INTO mbr_users_new_prodcheck SELECT * FROM mbr_users` fails with a column-count mismatch. The outer `except Exception: pass` at line 1055 swallows the failure silently, leaving the old CHECK in place — any subsequent `INSERT ... rola='produkcja'` then fails.

**Root cause:** Hard-coded column list in the rebuild instead of reading the current schema dynamically.

**Fix strategy:** Dynamically introspect the current `mbr_users` columns via `PRAGMA table_info`, build the replacement DDL with the same column set (only replacing the `rola` CHECK), and use explicit column names in the INSERT. This is forward-compatible with any future ALTER that adds columns before the next rebuild.

**Files:**
- Create: `tests/test_migrate_mbr_users_check.py`
- Modify: `mbr/models.py:1028-1056`

- [ ] **Step 1: Write failing regression test**

Create `tests/test_migrate_mbr_users_check.py`:

```python
"""Regression: init_mbr_tables must not silently fail when rebuilding mbr_users
on a DB that already has the default_grupa column added by a later migration.

Reproduces the column-count mismatch: mbr_users exists with 6 cols, ddl lacks
'produkcja' — rebuild must preserve all 6 cols, not truncate to 5.
"""

import sqlite3
import pytest

from mbr.models import init_mbr_tables


def _make_legacy_mbr_users(db: sqlite3.Connection) -> None:
    """Simulate a DB captured before 'produkcja' was added to CHECK but
    AFTER default_grupa was added — the combination that triggers B2."""
    db.executescript("""
        CREATE TABLE mbr_users (
            user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            login           TEXT UNIQUE NOT NULL,
            password_hash   TEXT NOT NULL,
            rola            TEXT NOT NULL CHECK(rola IN ('technolog', 'lab', 'cert', 'kj', 'admin')),
            imie_nazwisko   TEXT,
            default_grupa   TEXT DEFAULT 'lab'
        );
        INSERT INTO mbr_users (login, password_hash, rola, imie_nazwisko, default_grupa)
        VALUES ('jan', 'h', 'lab', 'Jan Kowalski', 'lab');
    """)
    db.commit()


def test_init_preserves_default_grupa_when_expanding_role_check():
    """Rebuild must carry all existing columns over; default_grupa must survive."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    _make_legacy_mbr_users(db)

    init_mbr_tables(db)

    cols = [r["name"] for r in db.execute("PRAGMA table_info(mbr_users)").fetchall()]
    assert "default_grupa" in cols, (
        "default_grupa column was dropped during mbr_users CHECK rebuild"
    )

    row = db.execute(
        "SELECT login, rola, default_grupa FROM mbr_users WHERE login='jan'"
    ).fetchone()
    assert row["login"] == "jan"
    assert row["rola"] == "lab"
    assert row["default_grupa"] == "lab"


def test_init_expands_role_check_to_include_produkcja():
    """After init, inserting a produkcja user must succeed."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    _make_legacy_mbr_users(db)

    init_mbr_tables(db)

    db.execute(
        "INSERT INTO mbr_users (login, password_hash, rola, imie_nazwisko) "
        "VALUES ('op1', 'h', 'produkcja', 'Op One')"
    )
    row = db.execute("SELECT rola FROM mbr_users WHERE login='op1'").fetchone()
    assert row["rola"] == "produkcja"


def test_init_idempotent_on_fresh_db():
    """Fresh DB path still works (no legacy table to rebuild)."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_mbr_tables(db)
    init_mbr_tables(db)  # second call must be a no-op
    db.execute(
        "INSERT INTO mbr_users (login, password_hash, rola) VALUES ('t', 'h', 'produkcja')"
    )
```

- [ ] **Step 2: Run the new test to confirm it fails**

Run: `pytest tests/test_migrate_mbr_users_check.py -v`
Expected: `test_init_preserves_default_grupa_when_expanding_role_check` FAILS (AssertionError: default_grupa was dropped) OR the rebuild raises and is swallowed, leaving ddl unchanged so `test_init_expands_role_check_to_include_produkcja` fails on the insert. Either way, at least one of the three tests fails before the fix.

- [ ] **Step 3: Fix the rebuild to preserve all columns dynamically**

In `mbr/models.py`, replace the block at lines 1028-1056 (the `# Migration: expand rola CHECK to include 'produkcja'` block) with:

```python
    # Migration: expand rola CHECK to include 'produkcja'.
    # Preserves all existing columns dynamically via PRAGMA table_info so later
    # ALTERs (e.g. default_grupa) survive the rebuild.
    try:
        row = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='mbr_users'"
        ).fetchone()
        if row:
            ddl = row[0] if isinstance(row, tuple) else row["sql"]
            if "'produkcja'" not in ddl:
                info = db.execute("PRAGMA table_info(mbr_users)").fetchall()
                # Each row: (cid, name, type, notnull, dflt_value, pk)
                col_defs = []
                col_names = []
                for c in info:
                    name = c[1]
                    col_names.append(name)
                    if name == "rola":
                        col_defs.append(
                            "rola TEXT NOT NULL CHECK(rola IN "
                            "('technolog', 'lab', 'cert', 'kj', 'admin', 'produkcja'))"
                        )
                        continue
                    parts = [name, c[2] or "TEXT"]
                    if c[5]:  # pk
                        parts.append("PRIMARY KEY AUTOINCREMENT")
                    if c[3]:  # notnull
                        parts.append("NOT NULL")
                    if c[4] is not None:
                        parts.append(f"DEFAULT {c[4]}")
                    if name == "login":
                        parts.append("UNIQUE")
                    col_defs.append(" ".join(parts))
                cols_csv = ", ".join(col_names)
                ddl_new = (
                    "CREATE TABLE mbr_users_new_prodcheck (\n                "
                    + ",\n                ".join(col_defs)
                    + "\n            )"
                )
                db.execute("PRAGMA foreign_keys=OFF")
                try:
                    db.execute("BEGIN")
                    db.execute(ddl_new)
                    db.execute(
                        f"INSERT INTO mbr_users_new_prodcheck ({cols_csv}) "
                        f"SELECT {cols_csv} FROM mbr_users"
                    )
                    db.execute("DROP TABLE mbr_users")
                    db.execute("ALTER TABLE mbr_users_new_prodcheck RENAME TO mbr_users")
                    db.execute("COMMIT")
                except Exception:
                    db.execute("ROLLBACK")
                    db.execute("PRAGMA foreign_keys=ON")
                    raise
                db.execute("PRAGMA foreign_keys=ON")
    except Exception:
        pass
```

Key differences from the old block:
1. Column set is read from `PRAGMA table_info` — no hard-coded list.
2. INSERT is explicit (`INSERT ... (cols) SELECT cols`), never `SELECT *` — robust against future column adds.
3. `rola` is the single column whose definition is replaced (to widen the CHECK); all others are reconstructed faithfully.
4. `UNIQUE` is restored for `login`; `PRIMARY KEY AUTOINCREMENT` is restored for `user_id`.

- [ ] **Step 4: Run the regression test**

Run: `pytest tests/test_migrate_mbr_users_check.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: `772 passed, 19 skipped` (+3 new tests; no regressions).

- [ ] **Step 6: Commit**

```bash
git add tests/test_migrate_mbr_users_check.py mbr/models.py
git commit -m "fix(models): mbr_users CHECK rebuild preserves all columns dynamically

Old rebuild hard-coded 5 columns; when default_grupa had already been
added by the later ALTER, INSERT SELECT * failed with column-count
mismatch and the outer except swallowed it — leaving the CHECK
un-widened and produkcja inserts impossible.

Rebuild now reads column list via PRAGMA table_info, reconstructs each
column definition, and uses explicit-column INSERT. Forward-compatible
with any future ALTER."
```

---

## Task 4: Escape user content in completed-batches table (B8)

**Blocker:** `mbr/templates/laborant/szarze_list.html:1471-1502` renders user-typed content (`uwagi_koncowe`, `zatwierdzil_full`, surowiec `nazwa` / `nr_partii`) into `title` attributes and HTML via string concatenation. The only escaping is `.replace(/"/g, '&quot;')` — does not handle `<`, `>`, `&`, `'`. A laborant who types `"><script>alert(1)</script>` into `uwagi_koncowe` triggers stored XSS when any user later opens the completed-batches table.

**Fix strategy:** There's already a `_htmlEsc` helper used on lines 1477 (surowce). Reuse it for tooltip text AND for everything interpolated into innerHTML. For attribute values, a dedicated `_attrEsc` is clearer because attribute-escape rules differ from text-escape rules.

**Files:**
- Modify: `mbr/templates/laborant/szarze_list.html` (lines 1471–1502, and one helper addition)

- [ ] **Step 1: Locate `_htmlEsc` definition**

Run:
```bash
grep -n "_htmlEsc\s*=\|function _htmlEsc" mbr/templates/laborant/szarze_list.html
```

Expected: shows where `_htmlEsc` is defined — typically near the top of the same `<script>` block.

- [ ] **Step 2: Add `_attrEsc` helper next to `_htmlEsc`**

Immediately after the `_htmlEsc` definition (whatever line that is), add:

```javascript
  function _attrEsc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }
```

- [ ] **Step 3: Escape surowiec tooltip (line ~1478)**

Replace the current line:
```javascript
        tooltipLines.push(s.nazwa + ' — ' + nr);
```
with:
```javascript
        tooltipLines.push(String(s.nazwa || '') + ' — ' + String(nr));
```

Then replace the next line building the attribute:
```javascript
      var tt = tooltipLines.join('\n').replace(/"/g, '&quot;');
      html += '<td class="td-surowce" title="' + tt + '">' + lines.join('<br>') + '</td>';
```
with:
```javascript
      var tt = _attrEsc(tooltipLines.join('\n'));
      html += '<td class="td-surowce" title="' + tt + '">' + lines.join('<br>') + '</td>';
```

(Inner `lines.join('<br>')` is already safe — `lines` is built from `_htmlEsc` calls at line 1477.)

- [ ] **Step 4: Escape "zatwierdzil" tooltip (line ~1494)**

Replace:
```javascript
  html += '<td class="td-who" style="font-size:11px;color:var(--text-sec);"' + (whoFull ? ' title="' + whoFull.replace(/"/g, '&quot;') + '"' : '') + '>' + whoShort + '</td>';
```
with:
```javascript
  html += '<td class="td-who" style="font-size:11px;color:var(--text-sec);"' + (whoFull ? ' title="' + _attrEsc(whoFull) + '"' : '') + '>' + _htmlEsc(whoShort) + '</td>';
```

- [ ] **Step 5: Escape uwagi cell (lines ~1495-1501)**

Replace:
```javascript
  var uwagi = b.uwagi_koncowe || '';
  var uwagiShort = uwagi.length > 50 ? uwagi.slice(0, 47) + '…' : uwagi;
  if (uwagi) {
    html += '<td class="td-uwagi" style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-sec);font-size:12px;" title="' + uwagi.replace(/"/g, '&quot;') + '">' + uwagiShort + '</td>';
  } else {
    html += '<td class="td-uwagi" style="color:var(--text-dim);">—</td>';
  }
```
with:
```javascript
  var uwagi = b.uwagi_koncowe || '';
  var uwagiShort = uwagi.length > 50 ? uwagi.slice(0, 47) + '…' : uwagi;
  if (uwagi) {
    html += '<td class="td-uwagi" style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-sec);font-size:12px;" title="' + _attrEsc(uwagi) + '">' + _htmlEsc(uwagiShort) + '</td>';
  } else {
    html += '<td class="td-uwagi" style="color:var(--text-dim);">—</td>';
  }
```

- [ ] **Step 6: Audit the rest of the same builder for other raw interpolations**

Run:
```bash
grep -nE "' \+ (b\.|s\.|uwagi|who)" mbr/templates/laborant/szarze_list.html | head -40
```

Review each hit in lines 1440–1520. Any concatenation that passes a user-typed string into HTML/title without `_htmlEsc` / `_attrEsc` must be wrapped. Expected: after Steps 3–5 the only remaining concatenations are numeric (`w.wartosc`, counts) or already-escaped values.

- [ ] **Step 7: Manual smoke test**

Run the dev server:
```bash
python -m mbr.app &
SERVER_PID=$!
sleep 2
```

Use the app:
1. Open a batch as laborant.
2. Type the string `</td><script>alert('xss')</script>` into `Uwagi końcowe`.
3. Complete the batch.
4. Open `/laborant/szarze` (completed-batches page).
5. Expected: the uwagi cell shows the literal text; no alert; inspect DOM — special characters are entity-encoded (`&lt;`, `&gt;`, `&#39;`).

Then:
```bash
kill $SERVER_PID
```

- [ ] **Step 8: Run tests**

Run: `pytest -q`
Expected: `772 passed, 19 skipped` (no backend tests touch this template; pytest confirms no regressions).

- [ ] **Step 9: Commit**

```bash
git add mbr/templates/laborant/szarze_list.html
git commit -m "fix(laborant): escape user-typed content in completed-batches table

uwagi_koncowe, zatwierdzil_full, and surowiec names/batch-ids were
concatenated into title attrs and innerHTML with only quote-escape —
stored XSS risk. Added _attrEsc helper and wrapped all four sites."
```

---

## Task 5: Require a shared-secret token on the COA sync endpoints (B4)

**Blocker:** `mbr/admin/routes.py:360-366` (`/api/admin/db-snapshot`) returns the entire SQLite file. `mbr/admin/routes.py:369` (`/api/completed`) returns completed-batch payload. Both lack `@login_required` — any request from anywhere the server is reachable (nginx is public) gets the DB.

**Fix strategy:**
Session-cookie auth does not fit because the COA app (see `coa_app/app.py:174,270`) is headless. Add a shared-secret header check — server requires `MBR_SYNC_TOKEN` env var; clients send it via `X-Sync-Token` header. If the env var is absent or empty, the endpoints are disabled (return 503). Token comparison uses `hmac.compare_digest` for constant-time.

**Files:**
- Create: `mbr/shared/sync_auth.py`
- Modify: `mbr/admin/routes.py` (decorate both endpoints)
- Create: `tests/test_sync_auth.py`
- Modify: `coa_app/app.py:174-177, 270` (send the header)

- [ ] **Step 1: Write failing test**

Create `tests/test_sync_auth.py`:

```python
"""Shared-secret token auth on COA sync endpoints (/api/completed, /api/admin/db-snapshot)."""

import os
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


@pytest.fixture
def client(monkeypatch, db, tmp_path):
    import mbr.db
    import mbr.admin.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.admin.routes, "db_session", fake_db_session)

    # Point DB_PATH at a non-empty temp file so /api/admin/db-snapshot can send_file.
    fake_db = tmp_path / "fake.sqlite"
    fake_db.write_bytes(b"SQLite fake")
    monkeypatch.setattr(mbr.db, "DB_PATH", fake_db)

    monkeypatch.setenv("MBR_SYNC_TOKEN", "good-secret-xyz")

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_completed_without_token_is_rejected(client):
    r = client.get("/api/completed")
    assert r.status_code == 401


def test_completed_with_wrong_token_is_rejected(client):
    r = client.get("/api/completed", headers={"X-Sync-Token": "nope"})
    assert r.status_code == 401


def test_completed_with_correct_token_is_allowed(client):
    r = client.get("/api/completed", headers={"X-Sync-Token": "good-secret-xyz"})
    assert r.status_code == 200


def test_db_snapshot_without_token_is_rejected(client):
    r = client.get("/api/admin/db-snapshot")
    assert r.status_code == 401


def test_db_snapshot_with_correct_token_is_allowed(client):
    r = client.get("/api/admin/db-snapshot", headers={"X-Sync-Token": "good-secret-xyz"})
    assert r.status_code == 200


def test_sync_disabled_when_token_env_missing(monkeypatch, db, tmp_path):
    """If MBR_SYNC_TOKEN is unset/empty, both endpoints return 503 — fail closed."""
    import mbr.db
    import mbr.admin.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.admin.routes, "db_session", fake_db_session)
    fake_db = tmp_path / "fake.sqlite"
    fake_db.write_bytes(b"SQLite fake")
    monkeypatch.setattr(mbr.db, "DB_PATH", fake_db)
    monkeypatch.delenv("MBR_SYNC_TOKEN", raising=False)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()

    r = c.get("/api/completed", headers={"X-Sync-Token": "anything"})
    assert r.status_code == 503
    r = c.get("/api/admin/db-snapshot", headers={"X-Sync-Token": "anything"})
    assert r.status_code == 503
```

- [ ] **Step 2: Run the test — expect failures**

Run: `pytest tests/test_sync_auth.py -v`
Expected: all 6 tests FAIL — endpoints currently return 200 regardless of token.

- [ ] **Step 3: Create the shared-secret decorator**

Create `mbr/shared/sync_auth.py`:

```python
"""Shared-secret token auth for headless COA sync endpoints.

Env var: MBR_SYNC_TOKEN
  - Unset/empty -> endpoints return 503 (fail closed).
  - Set        -> request must send `X-Sync-Token: <value>`.

Constant-time comparison via hmac.compare_digest.
"""

import hmac
import os
from functools import wraps

from flask import jsonify, request


def sync_token_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        expected = os.environ.get("MBR_SYNC_TOKEN", "")
        if not expected:
            return jsonify({"ok": False, "error": "sync disabled"}), 503
        got = request.headers.get("X-Sync-Token", "")
        if not hmac.compare_digest(got, expected):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return view(*args, **kwargs)
    return wrapped
```

- [ ] **Step 4: Apply decorator to the two endpoints**

In `mbr/admin/routes.py`:

Add near the top (with the other imports):
```python
from mbr.shared.sync_auth import sync_token_required
```

Decorate `/api/admin/db-snapshot` — replace:
```python
@admin_bp.route("/api/admin/db-snapshot")
def api_db_snapshot():
    """Download current DB as file (for COA app sync). No login required — LAN only."""
```
with:
```python
@admin_bp.route("/api/admin/db-snapshot")
@sync_token_required
def api_db_snapshot():
    """Download current DB as file (for COA app sync). Shared-secret via X-Sync-Token."""
```

Decorate `/api/completed` — replace:
```python
@admin_bp.route("/api/completed")
def api_completed():
```
with:
```python
@admin_bp.route("/api/completed")
@sync_token_required
def api_completed():
```

- [ ] **Step 5: Run the new test**

Run: `pytest tests/test_sync_auth.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 5b: Update pre-existing /api/completed tests to send the token**

`tests/test_sync.py` already calls `/api/completed` twice (at the `resp = client.get("/api/completed?since=...")` lines — search to confirm exact line numbers before editing). After Step 4, those calls return 401.

Fix: configure the `client` fixture to set `MBR_SYNC_TOKEN` and attach the header to every test request. Locate the existing fixture in `tests/test_sync.py` (starts with `def client(tmp_path):` around line 85). Replace it with:

```python
@pytest.fixture
def client(tmp_path, monkeypatch):
    """Flask test client with fresh DB; auto-sends X-Sync-Token on every request."""
    monkeypatch.setenv("MBR_SYNC_TOKEN", "test-token")
    db_path = tmp_path / "test.sqlite"
    with patch("mbr.db.DB_PATH", db_path):
        from mbr.app import create_app
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            # Auto-inject the sync token header on every request.
            orig_open = c.open
            def _open(*args, **kwargs):
                headers = kwargs.setdefault("headers", {})
                if isinstance(headers, dict):
                    headers.setdefault("X-Sync-Token", "test-token")
                return orig_open(*args, **kwargs)
            c.open = _open
            yield c
```

(Adjust imports at top of `tests/test_sync.py` if `monkeypatch` isn't already in scope — it's provided by pytest automatically as a function fixture parameter, no import needed.)

Verify:
```bash
pytest tests/test_sync.py -v
```
Expected: all pre-existing tests in that file still pass.

- [ ] **Step 6: Update the COA client to send the header**

Edit `coa_app/app.py`:

Find line ~174 (the `/api/completed` request) — replace:
```python
        r = http_requests.get(
            f"{server}/api/completed?since={last_seq}&ref_hash={ref_hash}",
            timeout=15, verify=False,
        )
```
with:
```python
        sync_token = os.environ.get("MBR_SYNC_TOKEN", "")
        r = http_requests.get(
            f"{server}/api/completed?since={last_seq}&ref_hash={ref_hash}",
            timeout=15, verify=False,
            headers={"X-Sync-Token": sync_token} if sync_token else {},
        )
```

Find line ~270 (the `/api/admin/db-snapshot` request) — replace:
```python
        r = http_requests.get(f"{server}/api/admin/db-snapshot", timeout=30, verify=False)
```
with:
```python
        sync_token = os.environ.get("MBR_SYNC_TOKEN", "")
        r = http_requests.get(
            f"{server}/api/admin/db-snapshot",
            timeout=30, verify=False,
            headers={"X-Sync-Token": sync_token} if sync_token else {},
        )
```

Ensure `import os` is present at the top of `coa_app/app.py`:
```bash
grep -n "^import os" coa_app/app.py
```
If missing, add it alongside the other stdlib imports.

- [ ] **Step 7: Run the full test suite**

Run: `pytest -q`
Expected: `778 passed, 19 skipped` (+6 new tests; no regressions, Step 5b keeps `tests/test_sync.py` green).

- [ ] **Step 8: Commit**

```bash
git add mbr/shared/sync_auth.py mbr/admin/routes.py coa_app/app.py tests/test_sync_auth.py tests/test_sync.py
git commit -m "fix(admin): require shared-secret token on COA sync endpoints

/api/completed and /api/admin/db-snapshot were unauthenticated; with
nginx proxying the app publicly, anyone reachable to the host could
download the entire DB.

Both now require X-Sync-Token matching MBR_SYNC_TOKEN env var.
Constant-time compare; fail-closed when env var unset (503). COA
client sends the same token when configured."
```

- [ ] **Step 9: Note for deploy (do NOT execute yet)**

Record the operational follow-up for the deploy step (Task 7):
- Add `MBR_SYNC_TOKEN=<random>` to the prod `EnvironmentFile` that Task 7 introduces.
- Configure the COA app on its host with the same token.

Do NOT edit `deploy/lims.service` here — that happens atomically in Task 7.

---

## Task 6: Fail fast on missing SECRET_KEY + use EnvironmentFile (B3)

**Blocker:**
- `mbr/app.py:11` falls back to `"dev-secret-change-in-prod"` if `MBR_SECRET_KEY` is unset. In prod this silently yields a predictable session secret.
- `deploy/lims.service:10` hard-codes `Environment=MBR_SECRET_KEY=CHANGE-ME-TO-RANDOM-STRING`. A deploy that forgets to replace the literal ships with a known key.

**Fix strategy:**
- Move secrets to `/etc/lims.env` (chmod 600) loaded via `EnvironmentFile=` in the systemd unit. The file is not in git.
- In `create_app()`: if `MBR_SECRET_KEY` is unset OR equals one of the known dev placeholders (`dev-secret-change-in-prod`, `CHANGE-ME-TO-RANDOM-STRING`), raise at startup — unless `TESTING=1` env var is set (for pytest).

**Files:**
- Modify: `mbr/app.py:9-12`
- Modify: `deploy/lims.service`
- Create: `deploy/lims.env.example` (template only — NOT secrets)
- Create: `tests/test_secret_key_guard.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_secret_key_guard.py`:

```python
"""create_app() must refuse to start with an unset or dev-default SECRET_KEY
unless the TESTING escape hatch is in effect."""

import pytest


def test_create_app_fails_when_secret_key_unset(monkeypatch):
    monkeypatch.delenv("MBR_SECRET_KEY", raising=False)
    monkeypatch.delenv("MBR_TESTING", raising=False)
    from mbr.app import create_app
    with pytest.raises(RuntimeError, match="MBR_SECRET_KEY"):
        create_app()


def test_create_app_fails_on_known_dev_placeholder(monkeypatch):
    monkeypatch.setenv("MBR_SECRET_KEY", "CHANGE-ME-TO-RANDOM-STRING")
    monkeypatch.delenv("MBR_TESTING", raising=False)
    from mbr.app import create_app
    with pytest.raises(RuntimeError, match="MBR_SECRET_KEY"):
        create_app()


def test_create_app_fails_on_dev_fallback_literal(monkeypatch):
    monkeypatch.setenv("MBR_SECRET_KEY", "dev-secret-change-in-prod")
    monkeypatch.delenv("MBR_TESTING", raising=False)
    from mbr.app import create_app
    with pytest.raises(RuntimeError, match="MBR_SECRET_KEY"):
        create_app()


def test_create_app_accepts_real_looking_key(monkeypatch):
    monkeypatch.setenv("MBR_SECRET_KEY", "3f9a2c5bf0e84a1b9d6e7c2a5f3d8e1b")
    monkeypatch.delenv("MBR_TESTING", raising=False)
    from mbr.app import create_app
    app = create_app()
    assert app.secret_key == "3f9a2c5bf0e84a1b9d6e7c2a5f3d8e1b"


def test_testing_env_disables_guard(monkeypatch):
    """pytest-running path: MBR_TESTING=1 lets the dev fallback through."""
    monkeypatch.delenv("MBR_SECRET_KEY", raising=False)
    monkeypatch.setenv("MBR_TESTING", "1")
    from mbr.app import create_app
    app = create_app()
    assert app.secret_key  # some value present, any value
```

- [ ] **Step 2: Confirm test fails**

Run: `pytest tests/test_secret_key_guard.py -v`
Expected: first 3 tests FAIL (no guard in place); last 2 may pass or fail depending on default.

- [ ] **Step 3: Add the guard to create_app**

Edit `mbr/app.py` — replace lines 9-12:
```python
def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("MBR_SECRET_KEY", "dev-secret-change-in-prod")
    app.config["TEMPLATES_AUTO_RELOAD"] = True
```

with:
```python
_DEV_SECRET_PLACEHOLDERS = {
    "dev-secret-change-in-prod",
    "CHANGE-ME-TO-RANDOM-STRING",
    "",
}


def create_app():
    app = Flask(__name__)
    secret = os.environ.get("MBR_SECRET_KEY", "")
    if secret in _DEV_SECRET_PLACEHOLDERS:
        if os.environ.get("MBR_TESTING") == "1":
            secret = "dev-secret-change-in-prod"  # test-only fallback
        else:
            raise RuntimeError(
                "MBR_SECRET_KEY is unset or is a known dev placeholder. "
                "Refusing to start — set a strong random value in /etc/lims.env."
            )
    app.secret_key = secret
    app.config["TEMPLATES_AUTO_RELOAD"] = True
```

- [ ] **Step 4: Make pytest inject MBR_TESTING=1 automatically**

Existing tests do not set this env var. Add a session-scoped autouse fixture to `tests/__init__.py` OR `conftest.py`. Check which exists:
```bash
ls tests/conftest.py 2>/dev/null; ls tests/__init__.py
```

If `tests/conftest.py` does NOT exist, create it with:
```python
"""Shared pytest setup — signals 'testing mode' to create_app."""
import os

os.environ.setdefault("MBR_TESTING", "1")
```

If it already exists, add the two lines (`import os` if absent and `os.environ.setdefault("MBR_TESTING", "1")`) at the top.

- [ ] **Step 5: Run the new test**

Run: `pytest tests/test_secret_key_guard.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: `783 passed, 19 skipped` (+5 new tests; no regressions).

**If any previously-passing test now fails with `MBR_SECRET_KEY` RuntimeError:** that test calls `create_app()` without going through `tests/conftest.py` — check it; the conftest should apply globally. Fix by ensuring conftest is at `tests/conftest.py` (not inside a subdir).

- [ ] **Step 7: Update the systemd unit to use EnvironmentFile**

Edit `deploy/lims.service` — replace the whole file with:
```ini
[Unit]
Description=LIMS Flask Application
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
User=lims
WorkingDirectory=/opt/lims
# Secrets live in /etc/lims.env (chmod 600, root:lims). NOT in git.
# Required keys: MBR_SECRET_KEY, MBR_SYNC_TOKEN.
EnvironmentFile=/etc/lims.env
ExecStart=/opt/lims/venv/bin/gunicorn --bind 127.0.0.1:5001 --workers 2 --timeout 120 mbr.app:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 8: Add an example env file (template only)**

Create `deploy/lims.env.example`:
```
# /etc/lims.env — chmod 600, owner root:lims.
# DO NOT COMMIT THIS FILE — template only.
# Replace values with real secrets before deploy.

MBR_SECRET_KEY=REPLACE_WITH_RANDOM_HEX_64
MBR_SYNC_TOKEN=REPLACE_WITH_RANDOM_HEX_32
```

- [ ] **Step 9: Add deployment notes README stub (no secrets)**

Create or append to `deploy/README.md`:

```markdown
## Secrets setup (first-time deploy)

Create `/etc/lims.env` on the host:

```bash
sudo install -m 600 -o root -g lims /dev/null /etc/lims.env
sudo tee /etc/lims.env >/dev/null <<EOF
MBR_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
MBR_SYNC_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(16))")
EOF
sudo systemctl daemon-reload
sudo systemctl restart lims
```

Point the COA client at the same `MBR_SYNC_TOKEN` value (set as env var on the COA host).
```

If `deploy/README.md` already exists, append the section under an existing `## ...` header; do not overwrite.

- [ ] **Step 10: Commit**

```bash
git add mbr/app.py tests/test_secret_key_guard.py tests/conftest.py deploy/lims.service deploy/lims.env.example deploy/README.md
git commit -m "fix(config): fail closed on missing/dev SECRET_KEY; load secrets from EnvironmentFile

create_app() now raises RuntimeError if MBR_SECRET_KEY is unset or a known
dev placeholder, unless MBR_TESTING=1 (pytest). Systemd unit reads
/etc/lims.env (chmod 600) instead of hard-coding the literal
CHANGE-ME-TO-RANDOM-STRING."
```

---

## Task 7: Use sqlite3 .backup for pre-deploy DB snapshot (B6)

**Blocker:** `deploy/auto-deploy.sh:25` does `cp data/batch_db.sqlite data/backups/pre-deploy-<ts>.sqlite`. With WAL mode enabled, any uncommitted-yet-checkpointed transactions live in `batch_db.sqlite-wal`. `cp` grabs only the main file → restored backup is an inconsistent snapshot.

**Fix strategy:** Use `sqlite3` CLI's `.backup` command — it's the only guaranteed-atomic online-backup API for SQLite (uses the C-API under the hood, handles WAL correctly).

**Files:**
- Modify: `deploy/auto-deploy.sh:23-25`

- [ ] **Step 1: Confirm current state**

Run:
```bash
sed -n '23,28p' deploy/auto-deploy.sh
```

Expected:
```
# Backup database before deploy
mkdir -p data/backups
cp data/batch_db.sqlite "data/backups/pre-deploy-$(date +%Y%m%d-%H%M%S).sqlite"
# Disk cleanup: old backups, __pycache__, stale WAL
/opt/lims/venv/bin/python -m scripts.cleanup_disk 2>/dev/null || true
```

- [ ] **Step 2: Replace cp with sqlite3 .backup**

Edit `deploy/auto-deploy.sh` — replace:
```bash
# Backup database before deploy
mkdir -p data/backups
cp data/batch_db.sqlite "data/backups/pre-deploy-$(date +%Y%m%d-%H%M%S).sqlite"
```
with:
```bash
# Backup database before deploy (online .backup handles WAL correctly; cp does not)
mkdir -p data/backups
BACKUP_PATH="data/backups/pre-deploy-$(date +%Y%m%d-%H%M%S).sqlite"
sqlite3 data/batch_db.sqlite ".backup '$BACKUP_PATH'"
if [ ! -s "$BACKUP_PATH" ]; then
    echo "$(date): BACKUP FAILED — aborting deploy" >&2
    exit 1
fi
```

- [ ] **Step 3: Verify bash syntax**

Run:
```bash
bash -n deploy/auto-deploy.sh
```
Expected: exit 0, no output.

- [ ] **Step 4: Smoke test the backup command against a throwaway DB**

Run:
```bash
mkdir -p /tmp/lims-backup-test
sqlite3 /tmp/lims-backup-test/src.sqlite "CREATE TABLE t (x INTEGER); INSERT INTO t VALUES (1), (2);"
sqlite3 /tmp/lims-backup-test/src.sqlite ".backup '/tmp/lims-backup-test/dst.sqlite'"
sqlite3 /tmp/lims-backup-test/dst.sqlite "SELECT COUNT(*) FROM t;"
rm -rf /tmp/lims-backup-test
```
Expected final line: `2`.

- [ ] **Step 5: Run tests**

Run: `pytest -q`
Expected: `783 passed, 19 skipped` (no pytest tests touch this script; this is the regression gate).

- [ ] **Step 6: Commit**

```bash
git add deploy/auto-deploy.sh
git commit -m "fix(deploy): use sqlite3 .backup for pre-deploy snapshot

cp leaves the WAL behind; restoring from that backup yields an
inconsistent DB. sqlite3 .backup is the supported online-backup API
and handles WAL correctly. Abort the deploy if the backup file is
zero-byte."
```

---

## Task 8: Scheduled daily DB backup via systemd timer (B7)

**Blocker:** The only backup currently created is the pre-deploy snapshot from `auto-deploy.sh`. If a day passes without a deploy, there's no backup. A host failure loses a day of operator input.

**Fix strategy:** Standalone systemd timer that runs `sqlite3 .backup` once a day into `/opt/lims/data/backups/daily-<date>.sqlite`, retaining the last 14 days. Deployed alongside existing units in `deploy/`.

**Files:**
- Create: `deploy/lims-backup.service`
- Create: `deploy/lims-backup.timer`
- Create: `deploy/lims-backup.sh`
- Modify: `deploy/README.md` (document install step)

- [ ] **Step 1: Create the backup script**

Create `deploy/lims-backup.sh`:
```bash
#!/bin/bash
# Daily SQLite backup. Invoked by lims-backup.service.
set -euo pipefail

SRC="/opt/lims/data/batch_db.sqlite"
DEST_DIR="/opt/lims/data/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$DEST_DIR/daily-$STAMP.sqlite"
RETAIN_DAYS=14

mkdir -p "$DEST_DIR"

if [ ! -s "$SRC" ]; then
    echo "$(date): source DB missing or empty — $SRC" >&2
    exit 1
fi

sqlite3 "$SRC" ".backup '$DEST'"

if [ ! -s "$DEST" ]; then
    echo "$(date): backup wrote zero bytes — $DEST" >&2
    exit 1
fi

# Prune daily backups older than RETAIN_DAYS (does not touch pre-deploy-*.sqlite)
find "$DEST_DIR" -maxdepth 1 -name "daily-*.sqlite" -mtime +$RETAIN_DAYS -delete

echo "$(date): backup ok — $DEST"
```

Make it executable (note in plan — actual chmod happens at install time on host):
```bash
chmod +x deploy/lims-backup.sh
```

- [ ] **Step 2: Create the systemd service unit**

Create `deploy/lims-backup.service`:
```ini
[Unit]
Description=LIMS daily SQLite backup
After=network.target

[Service]
Type=oneshot
User=lims
WorkingDirectory=/opt/lims
ExecStart=/opt/lims/deploy/lims-backup.sh
# Failures should not restart — the timer retries tomorrow; but log loudly.
StandardOutput=journal
StandardError=journal
```

- [ ] **Step 3: Create the systemd timer**

Create `deploy/lims-backup.timer`:
```ini
[Unit]
Description=LIMS daily SQLite backup — 03:00 local

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
Unit=lims-backup.service

[Install]
WantedBy=timers.target
```

- [ ] **Step 4: Append install notes to deploy/README.md**

Append to `deploy/README.md` (create if needed):
```markdown

## Daily backup timer

Install once:

```bash
sudo cp /opt/lims/deploy/lims-backup.service /etc/systemd/system/
sudo cp /opt/lims/deploy/lims-backup.timer   /etc/systemd/system/
sudo chmod +x /opt/lims/deploy/lims-backup.sh
sudo systemctl daemon-reload
sudo systemctl enable --now lims-backup.timer
```

Verify:
```bash
systemctl list-timers | grep lims-backup
# Trigger a test run:
sudo systemctl start lims-backup.service
journalctl -u lims-backup.service -n 20
ls -lh /opt/lims/data/backups/daily-*.sqlite | tail -3
```

Retains the last 14 daily backups; pre-deploy snapshots are not pruned by this job.
```

- [ ] **Step 5: Syntax-check the backup script**

Run:
```bash
bash -n deploy/lims-backup.sh
```
Expected: exit 0.

- [ ] **Step 6: Smoke test the backup script against a throwaway DB**

Run:
```bash
mkdir -p /tmp/lims-backup-test/data/backups
sqlite3 /tmp/lims-backup-test/data/batch_db.sqlite "CREATE TABLE t (x INTEGER); INSERT INTO t VALUES (1);"
SRC=/tmp/lims-backup-test/data/batch_db.sqlite DEST_DIR=/tmp/lims-backup-test/data/backups \
    bash -c '
        STAMP=$(date +%Y%m%d-%H%M%S)
        DEST="$DEST_DIR/daily-$STAMP.sqlite"
        sqlite3 "$SRC" ".backup \"$DEST\""
        sqlite3 "$DEST" "SELECT COUNT(*) FROM t;"
    '
rm -rf /tmp/lims-backup-test
```
Expected final line: `1`.

- [ ] **Step 7: Run tests**

Run: `pytest -q`
Expected: `783 passed, 19 skipped` (no Python code touched; this is the regression gate).

- [ ] **Step 8: Commit**

```bash
chmod +x deploy/lims-backup.sh
git add deploy/lims-backup.service deploy/lims-backup.timer deploy/lims-backup.sh deploy/README.md
git commit -m "feat(deploy): daily SQLite backup systemd timer (lims-backup)

Runs sqlite3 .backup at 03:00 local, retains 14 days under
/opt/lims/data/backups/daily-*.sqlite. Install instructions in
deploy/README.md."
```

---

## Task 9: Final regression sweep + manual acceptance

**Files:** (verification only — no code changes)

- [ ] **Step 1: Full test suite**

Run: `pytest -q`
Expected: `783 passed, 19 skipped` (baseline 769 + 14 new tests from Tasks 3/5/6).

- [ ] **Step 2: Grep for leftover blockers**

Run:
```bash
grep -rn '<<<<<<<\|CHANGE-ME-TO-RANDOM\|dev-secret-change-in-prod' \
    mbr/ deploy/ migrate_*.py \
    --exclude-dir=__pycache__ 2>/dev/null
```

Expected: only the `_DEV_SECRET_PLACEHOLDERS` set in `mbr/app.py` mentions the placeholder (as a blocklist value). No matches anywhere else.

- [ ] **Step 3: Verify migrate_roles.py not referenced in deploy**

Run:
```bash
grep -n "migrate_roles" deploy/auto-deploy.sh
```
Expected: empty output.

- [ ] **Step 4: Verify the two sync endpoints carry the decorator**

Run:
```bash
grep -B1 "def api_db_snapshot\|def api_completed" mbr/admin/routes.py
```
Expected: each function is preceded by `@sync_token_required`.

- [ ] **Step 5: Manual smoke (dev server)**

```bash
MBR_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))") \
MBR_SYNC_TOKEN=testtoken \
python -m mbr.app &
SERVER_PID=$!
sleep 2

# Unauth sync endpoint:
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5001/api/completed
# Expected: 401

# Auth sync endpoint:
curl -s -o /dev/null -w "%{http_code}\n" -H "X-Sync-Token: testtoken" http://127.0.0.1:5001/api/completed
# Expected: 200

# Without token env, app should refuse to start:
kill $SERVER_PID
wait $SERVER_PID 2>/dev/null

# Dev-default guard:
MBR_SECRET_KEY=CHANGE-ME-TO-RANDOM-STRING python -m mbr.app 2>&1 | head -5
# Expected: RuntimeError with MBR_SECRET_KEY message, non-zero exit.
```

- [ ] **Step 6: Deployment readiness checklist for operator** (no action here — this is documentation in the final commit body)

Record for the deploy runbook:

1. On the host, create `/etc/lims.env` with real `MBR_SECRET_KEY` and `MBR_SYNC_TOKEN` (see `deploy/README.md`).
2. `sudo systemctl daemon-reload && sudo systemctl restart lims`.
3. Install `lims-backup.timer` (see `deploy/README.md`).
4. Configure the COA host with the same `MBR_SYNC_TOKEN`.
5. First auto-deploy after these changes will exercise the new `sqlite3 .backup` path — verify in `/opt/lims/data/backups/` that the file is non-zero.

- [ ] **Step 7: Write the verification note as a plain-text artifact (not a commit)**

No commit — this task is verification-only. The nine blocker fixes are already individually committed (Tasks 1–8). Report status to the user with: commits landed, tests green, deploy steps documented.

---

## Self-Review

**Spec coverage:**
- B1 → Task 1 ✓
- B2 → Task 3 ✓
- B3 → Task 6 ✓
- B4 → Task 5 ✓
- B5 → Task 2 (removes from auto-deploy) ✓
- B6 → Task 7 ✓
- B7 → Task 8 ✓
- B8 → Task 4 ✓
- B9 → Task 2 (fixes CHECK in historical script) ✓

All nine blockers covered.

**Placeholder scan:** No TBD/TODO/"implement later"/"similar to Task N" strings; every code step shows the exact code to write; every command shows expected output.

**Type consistency:**
- `_attrEsc` / `_htmlEsc` in Task 4 — both JS helpers, same `szarze_list.html` file.
- `sync_token_required` in Task 5 — defined in `mbr/shared/sync_auth.py`, imported in `mbr/admin/routes.py`; same name in both places.
- `_DEV_SECRET_PLACEHOLDERS` set in Task 6 — referenced only inside `create_app`, single file.
- `MBR_SYNC_TOKEN` env var used in Task 5 (server + COA client) and Task 6 (EnvironmentFile template) — same string.
- `MBR_TESTING` env var set in `tests/conftest.py` (Task 6 Step 4) and checked in `create_app` (Task 6 Step 3) — same string.
- `lims-backup.service`, `lims-backup.timer`, `lims-backup.sh` file names in Task 8 — consistent across the service unit (`ExecStart=/opt/lims/deploy/lims-backup.sh`), the timer (`Unit=lims-backup.service`), and the README.

**Risk of breaking existing tests (769 baseline):**
- Task 1: docstring-only change — impossible to break runtime.
- Task 2: only touches a standalone migration script and a deploy shell file; no pytest test imports them.
- Task 3: rewrites init_mbr_tables migration block. Danger zone — but the rewrite preserves behavior on fresh DBs (the `if "'produkcja'" not in ddl` guard short-circuits when ddl already has produkcja, which is the fresh-DB case). Regression tests cover the legacy case explicitly.
- Task 4: template-only change, no Python tests touch this template.
- Task 5: new decorator applied to two endpoints. Risk: existing tests that hit `/api/completed` or `/api/admin/db-snapshot` would now get 401/503. Mitigation — `grep -rn "/api/completed\|/api/admin/db-snapshot" tests/` before landing; if any hit, the existing test must set `MBR_SYNC_TOKEN` and send the header (update it in the same commit).
- Task 6: new guard in `create_app`. Mitigation — `tests/conftest.py` sets `MBR_TESTING=1` globally; every test that calls `create_app()` benefits automatically.
- Task 7/8: shell and systemd only — pytest unaffected.

**Scope check:** Plan is production-safety-only. No functional changes, no UI changes, no new features beyond the missing daily-backup timer (which is security hygiene, not user-facing).

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-18-pre-prod-blockers.md`. Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review (spec + code quality) between tasks, fast iteration.
2. **Inline Execution** — execute the tasks in this session via `superpowers:executing-plans`, with checkpoints after every 2–3 tasks.

**Which approach?**
