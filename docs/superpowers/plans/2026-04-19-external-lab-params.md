# External-Lab Params Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable admins to mark an analytical parameter as `grupa='zewn'` (external lab) via the admin UI; the value propagates into new bindings and all downstream views render it transparently. KJ enters late-arriving values via existing completed-batch edit flow.

**Architecture:** Add `grupa` column to `parametry_analityczne` (global). Admin UI gets a dropdown. `POST/PUT /api/parametry` accept/validate it. `POST /api/parametry/etapy` (both pipeline and legacy paths) inherits from `parametry_analityczne.grupa` when creating a binding. Rendering pipeline is already grupa-agnostic — only regression tests needed.

**Tech Stack:** Python/Flask, sqlite3 (raw), pytest, Jinja2 templates, vanilla JS.

**Baseline:** `pytest -q` → `783 passed, 19 skipped`. Every task ends with that OR that + the tests added in the task, no regressions.

**Guard rails:**

1. One commit per task. Co-Authored-By trailer on every commit.
2. DO NOT stage `mbr/cert_config.json` or `data/batch_db 2.sqlite-wal` (pre-existing dirty files).
3. Work on a feature branch `feat/external-lab-params` (do NOT commit directly to main).
4. No `git push`.

---

## Task 0: Branch setup

**Files:** n/a (git only)

- [ ] **Step 1: Create feature branch**

Run:
```bash
cd /Users/tbk/Desktop/lims-clean
git checkout main
git log -1 --format='%H %s'
```
Expected HEAD: `c3bd688 docs(spec): correct external-lab spec...` or newer.

```bash
git checkout -b feat/external-lab-params
git branch --show-current
```
Expected output: `feat/external-lab-params`.

---

## Task 1: Schema migration — add `grupa` to `parametry_analityczne`

**Files:**
- Modify: `mbr/models.py` (inside `init_mbr_tables`, near the other idempotent ALTER blocks ~line 1455-1470)
- Create test: `tests/test_parametry_grupa_migration.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_parametry_grupa_migration.py`:

```python
"""Regression: parametry_analityczne.grupa column added idempotently by init_mbr_tables."""

import sqlite3
import pytest

from mbr.models import init_mbr_tables


def _cols(db, table):
    return {r[1]: r for r in db.execute(f"PRAGMA table_info({table})").fetchall()}


def test_init_adds_grupa_column():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_mbr_tables(db)
    cols = _cols(db, "parametry_analityczne")
    assert "grupa" in cols, "grupa column must exist after init"
    # PRAGMA table_info columns: (cid, name, type, notnull, dflt_value, pk)
    assert cols["grupa"][2].upper() == "TEXT"
    assert cols["grupa"][4] == "'lab'", f"default must be 'lab', got {cols['grupa'][4]!r}"


def test_init_is_idempotent_on_grupa():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_mbr_tables(db)
    # Second call must not raise even though column already exists
    init_mbr_tables(db)
    cols = _cols(db, "parametry_analityczne")
    # Still exactly one 'grupa' column
    names = [r[1] for r in db.execute("PRAGMA table_info(parametry_analityczne)").fetchall()]
    assert names.count("grupa") == 1


def test_existing_rows_get_default_grupa():
    """Rows inserted BEFORE the migration ran should get 'lab' as grupa."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    # Seed parametry_analityczne WITHOUT grupa column (simulate pre-migration state)
    db.executescript("""
        CREATE TABLE parametry_analityczne (
            id INTEGER PRIMARY KEY, kod TEXT UNIQUE, label TEXT, typ TEXT,
            skrot TEXT, precision INTEGER, jednostka TEXT,
            metoda_nazwa TEXT, formula TEXT, aktywny INTEGER DEFAULT 1,
            metoda_formula TEXT, metoda_factor REAL, metoda_id INTEGER,
            name_en TEXT, method_code TEXT
        );
        INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (1, 'ph', 'pH', 'bezposredni');
    """)
    db.commit()

    # Now run the migration
    init_mbr_tables(db)

    row = db.execute("SELECT grupa FROM parametry_analityczne WHERE id=1").fetchone()
    assert row["grupa"] == "lab"
```

- [ ] **Step 2: Run the new tests — confirm they FAIL**

Run: `pytest tests/test_parametry_grupa_migration.py -v`

Expected: `test_init_adds_grupa_column` FAILS (column not in PRAGMA output). `test_existing_rows_get_default_grupa` FAILS (no such column). `test_init_is_idempotent_on_grupa` may pass trivially (column doesn't exist either way).

- [ ] **Step 3: Add the migration to `init_mbr_tables`**

In `mbr/models.py`, locate the block near line 1455-1470 that has `ALTER TABLE parametry_etapy ADD COLUMN grupa TEXT DEFAULT 'lab'` (or similar `grupa`-adjacent ALTERs). Immediately after the last such block, add:

```python
    # Migration: add grupa to parametry_analityczne (global per-parameter default)
    try:
        db.execute("ALTER TABLE parametry_analityczne ADD COLUMN grupa TEXT DEFAULT 'lab'")
        db.commit()
    except Exception:
        pass  # column already exists
```

- [ ] **Step 4: Run the tests — confirm they PASS**

Run: `pytest tests/test_parametry_grupa_migration.py -v`
Expected: all 3 pass.

- [ ] **Step 5: Run full suite**

Run: `pytest -q`
Expected: `786 passed, 19 skipped` (baseline 783 + 3 new).

- [ ] **Step 6: Commit**

```bash
git add mbr/models.py tests/test_parametry_grupa_migration.py
git commit -m "$(cat <<'EOF'
feat(parametry): add grupa column to parametry_analityczne

Idempotent migration in init_mbr_tables. Default 'lab' for all existing
rows. First step toward allowing params to be flagged as external-lab
('zewn') so they can be tracked separately on certificates.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `POST /api/parametry` accepts + validates `grupa`

**Files:**
- Modify: `mbr/parametry/routes.py` (top — add `ALLOWED_GRUPY` constant; modify `api_parametry_create` at ~line 102-123)
- Create test: `tests/test_parametry_grupa_api.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_parametry_grupa_api.py`:

```python
"""Tests for grupa field on /api/parametry endpoints."""

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
    import mbr.db
    import mbr.parametry.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.parametry.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = {"login": "tester", "rola": rola, "worker_id": None}
    return c


@pytest.fixture
def client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="admin")


def test_post_parametry_with_grupa_zewn_persists(client, db):
    r = client.post("/api/parametry", json={
        "kod": "tpc", "label": "Total plate count", "typ": "bezposredni", "grupa": "zewn",
    })
    assert r.status_code == 200, r.get_json()
    row = db.execute("SELECT grupa FROM parametry_analityczne WHERE kod='tpc'").fetchone()
    assert row["grupa"] == "zewn"


def test_post_parametry_without_grupa_defaults_lab(client, db):
    r = client.post("/api/parametry", json={"kod": "x", "label": "X", "typ": "bezposredni"})
    assert r.status_code == 200
    row = db.execute("SELECT grupa FROM parametry_analityczne WHERE kod='x'").fetchone()
    assert row["grupa"] == "lab"


def test_post_parametry_rejects_unknown_grupa(client, db):
    r = client.post("/api/parametry", json={
        "kod": "x", "label": "X", "typ": "bezposredni", "grupa": "mikrobio",
    })
    assert r.status_code == 400
    assert "grupa" in (r.get_json().get("error") or "").lower()
    # Must not have created the row
    assert db.execute("SELECT COUNT(*) FROM parametry_analityczne WHERE kod='x'").fetchone()[0] == 0
```

- [ ] **Step 2: Run the new tests — confirm they FAIL**

Run: `pytest tests/test_parametry_grupa_api.py -v`
Expected: all 3 fail. `test_post_parametry_with_grupa_zewn_persists` fails because INSERT ignores grupa. `test_post_parametry_rejects_unknown_grupa` fails because no validation — the "mikrobio" string would be silently dropped (row still created with default 'lab'), so `status_code == 400` assertion fails.

- [ ] **Step 3: Add `ALLOWED_GRUPY` constant + modify `api_parametry_create`**

In `mbr/parametry/routes.py`:

Near the top, after the imports (around line 9), add:

```python
ALLOWED_GRUPY = {"lab", "zewn"}
```

Replace the body of `api_parametry_create` (currently lines 102-123) with:

```python
@parametry_bp.route("/api/parametry", methods=["POST"])
@role_required("admin")
def api_parametry_create():
    """Create a new analytical parameter (admin only)."""
    data = request.get_json(silent=True) or {}
    kod = (data.get("kod") or "").strip()
    label = (data.get("label") or "").strip()
    typ = data.get("typ", "bezposredni")
    grupa = data.get("grupa", "lab")
    if not kod or not label:
        return jsonify({"error": "kod and label required"}), 400
    if grupa not in ALLOWED_GRUPY:
        return jsonify({"error": f"grupa must be one of: {', '.join(sorted(ALLOWED_GRUPY))}"}), 400
    with db_session() as db:
        try:
            cur = db.execute(
                "INSERT INTO parametry_analityczne (kod, label, skrot, typ, jednostka, precision, name_en, method_code, grupa) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kod, label, data.get("skrot", ""), typ, data.get("jednostka", ""),
                 data.get("precision", 2), data.get("name_en", ""), data.get("method_code", ""),
                 grupa),
            )
            db.commit()
        except Exception:
            return jsonify({"error": "Parametr already exists"}), 409
    return jsonify({"ok": True, "id": cur.lastrowid})
```

- [ ] **Step 4: Run the new tests — confirm they PASS**

Run: `pytest tests/test_parametry_grupa_api.py -v`
Expected: all 3 pass.

- [ ] **Step 5: Run full suite**

Run: `pytest -q`
Expected: `789 passed, 19 skipped` (786 + 3 new).

- [ ] **Step 6: Commit**

```bash
git add mbr/parametry/routes.py tests/test_parametry_grupa_api.py
git commit -m "$(cat <<'EOF'
feat(parametry): POST /api/parametry accepts and validates grupa

Adds ALLOWED_GRUPY whitelist {lab, zewn}. Unknown values return 400.
Default is 'lab' when not provided. Enables admin to create a
new parameter flagged as external-lab.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `PUT /api/parametry/<id>` accepts + validates `grupa`

**Files:**
- Modify: `mbr/parametry/routes.py::api_parametry_update` (~line 68-99)
- Extend test: `tests/test_parametry_grupa_api.py`

- [ ] **Step 1: Add failing tests to the existing file**

Append to `tests/test_parametry_grupa_api.py`:

```python
@pytest.fixture
def client_non_admin(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="lab")


def _seed_param(db, kod="sm", grupa="lab"):
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, typ, grupa) VALUES (?, ?, 'bezposredni', ?)",
        (kod, kod.upper(), grupa),
    )
    db.commit()
    return db.execute("SELECT id FROM parametry_analityczne WHERE kod=?", (kod,)).fetchone()["id"]


def test_put_parametry_admin_can_change_grupa(client, db):
    pid = _seed_param(db, "tpc", "lab")
    r = client.put(f"/api/parametry/{pid}", json={"grupa": "zewn"})
    assert r.status_code == 200
    row = db.execute("SELECT grupa FROM parametry_analityczne WHERE id=?", (pid,)).fetchone()
    assert row["grupa"] == "zewn"


def test_put_parametry_rejects_unknown_grupa(client, db):
    pid = _seed_param(db, "tpc", "lab")
    r = client.put(f"/api/parametry/{pid}", json={"grupa": "nonsense"})
    assert r.status_code == 400
    # DB unchanged
    row = db.execute("SELECT grupa FROM parametry_analityczne WHERE id=?", (pid,)).fetchone()
    assert row["grupa"] == "lab"


def test_put_parametry_non_admin_cannot_change_grupa(client_non_admin, db):
    """Grupa is admin-only, like typ/aktywny. Non-admin PUT with grupa: ignored (silently dropped from allowed set).
    The response may succeed (200) or reject (400 'No valid fields') depending on whether other fields are also sent.
    Key invariant: DB row's grupa must NOT change."""
    pid = _seed_param(db, "tpc", "lab")
    r = client_non_admin.put(f"/api/parametry/{pid}", json={"grupa": "zewn", "label": "new label"})
    # label IS allowed for non-admin, so request returns 200, grupa silently dropped
    assert r.status_code == 200
    row = db.execute("SELECT grupa, label FROM parametry_analityczne WHERE id=?", (pid,)).fetchone()
    assert row["grupa"] == "lab"
    assert row["label"] == "new label"


def test_put_parametry_grupa_only_non_admin_rejected(client_non_admin, db):
    pid = _seed_param(db, "tpc", "lab")
    r = client_non_admin.put(f"/api/parametry/{pid}", json={"grupa": "zewn"})
    # No valid fields for non-admin to update
    assert r.status_code == 400
    row = db.execute("SELECT grupa FROM parametry_analityczne WHERE id=?", (pid,)).fetchone()
    assert row["grupa"] == "lab"
```

- [ ] **Step 2: Run the new tests — confirm they FAIL**

Run: `pytest tests/test_parametry_grupa_api.py -v -k put_parametry`
Expected: all 4 fail. `test_put_parametry_admin_can_change_grupa` fails because `grupa` not in `allowed` set (ignored). `test_put_parametry_rejects_unknown_grupa` fails because invalid grupa silently dropped → `status_code==400` expectation fails (will get 400 for "No valid fields" though, which happens to match — verify output carefully; if test passes for wrong reason, assert explicit message).

- [ ] **Step 3: Add grupa to admin-only allowed set + validate**

In `mbr/parametry/routes.py`, replace the body of `api_parametry_update` (currently lines 68-99) with:

```python
@parametry_bp.route("/api/parametry/<int:param_id>", methods=["PUT"])
@login_required
def api_parametry_update(param_id):
    """Update global parameter fields. Admin can edit additional fields."""
    data = request.get_json(silent=True) or {}
    rola = session.get("user", {}).get("rola", "")
    allowed = {"label", "skrot", "formula", "metoda_nazwa", "metoda_formula", "metoda_factor", "precision"}
    if rola == "admin":
        allowed |= {"typ", "jednostka", "aktywny", "name_en", "method_code", "grupa"}
    if "grupa" in data and data["grupa"] not in ALLOWED_GRUPY:
        return jsonify({"error": f"grupa must be one of: {', '.join(sorted(ALLOWED_GRUPY))}"}), 400
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "No valid fields"}), 400
    sets = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [param_id]
    with db_session() as db:
        db.execute(f"UPDATE parametry_analityczne SET {sets} WHERE id=?", vals)
        # Rebuild parametry_lab for all active templates that use this parameter
        affected = db.execute(
            """SELECT DISTINCT mt.produkt
               FROM mbr_templates mt
               JOIN parametry_etapy pe ON pe.produkt = mt.produkt
               WHERE pe.parametr_id = ? AND mt.status = 'active'""",
            (param_id,),
        ).fetchall()
        for row in affected:
            plab = build_parametry_lab(db, row["produkt"])
            db.execute(
                "UPDATE mbr_templates SET parametry_lab=? WHERE produkt=? AND status='active'",
                (_json.dumps(plab, ensure_ascii=False), row["produkt"]),
            )
        db.commit()
    return jsonify({"ok": True})
```

Only two substantive changes vs. the original: `"grupa"` added to the admin-only set, and a grupa-specific whitelist check that runs BEFORE the `updates` filter (so an invalid grupa from ANY role returns 400 rather than being silently dropped).

- [ ] **Step 4: Run the new tests — confirm they PASS**

Run: `pytest tests/test_parametry_grupa_api.py -v -k put_parametry`
Expected: all 4 pass.

- [ ] **Step 5: Run full suite**

Run: `pytest -q`
Expected: `793 passed, 19 skipped` (789 + 4 new).

- [ ] **Step 6: Commit**

```bash
git add mbr/parametry/routes.py tests/test_parametry_grupa_api.py
git commit -m "$(cat <<'EOF'
feat(parametry): PUT /api/parametry/<id> admin can change grupa

Admin role gains 'grupa' in the allowed-fields set. Whitelist validation
runs before the role filter so invalid values return 400 regardless of
role (rather than being silently dropped and producing 'No valid fields').

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Binding inheritance on `POST /api/parametry/etapy` — legacy path

**Context:** `api_parametry_etapy_create` has two code paths. The legacy one (line 170-184 in current code, writes to `parametry_etapy`) already uses `grupa` with default `"lab"`. Change it to default to `parametry_analityczne.grupa` instead.

**Files:**
- Modify: `mbr/parametry/routes.py::api_parametry_etapy_create` (legacy branch, ~line 170-184)
- Extend test: `tests/test_parametry_grupa_api.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_parametry_grupa_api.py`:

```python
def test_binding_legacy_inherits_grupa_from_parametr(client, db):
    """Binding created via POST /api/parametry/etapy on a NON-pipeline product
    (legacy path → parametry_etapy) inherits grupa from parametry_analityczne."""
    pid = _seed_param(db, "tpc", "zewn")
    r = client.post("/api/parametry/etapy", json={
        "parametr_id": pid, "kontekst": "analiza_koncowa",
        "produkt": "TEST_LEGACY",  # no pipeline row in the fixture → legacy branch
        "min_limit": 0, "max_limit": 100,
    })
    assert r.status_code == 200, r.get_json()
    row = db.execute(
        "SELECT grupa FROM parametry_etapy WHERE parametr_id=? AND produkt='TEST_LEGACY'",
        (pid,),
    ).fetchone()
    assert row is not None
    assert row["grupa"] == "zewn"


def test_binding_legacy_honors_explicit_grupa_override(client, db):
    """Explicit 'grupa' in request body overrides the global default."""
    pid = _seed_param(db, "tpc", "zewn")  # global grupa='zewn'
    r = client.post("/api/parametry/etapy", json={
        "parametr_id": pid, "kontekst": "analiza_koncowa", "produkt": "TEST_LEGACY",
        "grupa": "lab",  # admin wants this particular binding to be 'lab' anyway
        "min_limit": 0, "max_limit": 100,
    })
    assert r.status_code == 200
    row = db.execute(
        "SELECT grupa FROM parametry_etapy WHERE parametr_id=? AND produkt='TEST_LEGACY'",
        (pid,),
    ).fetchone()
    assert row["grupa"] == "lab"


def test_binding_legacy_rejects_invalid_grupa(client, db):
    pid = _seed_param(db, "tpc", "lab")
    r = client.post("/api/parametry/etapy", json={
        "parametr_id": pid, "kontekst": "analiza_koncowa", "produkt": "TEST_LEGACY",
        "grupa": "mikrobio",
    })
    assert r.status_code == 400
    assert "grupa" in (r.get_json().get("error") or "").lower()
```

- [ ] **Step 2: Run tests — confirm they FAIL**

Run: `pytest tests/test_parametry_grupa_api.py -v -k binding_legacy`
Expected: `test_binding_legacy_inherits_grupa_from_parametr` fails (default hardcoded to 'lab', not inheriting). `test_binding_legacy_honors_explicit_grupa_override` may pass already (it already accepts grupa from body). `test_binding_legacy_rejects_invalid_grupa` fails (no validation).

- [ ] **Step 3: Modify legacy branch**

In `mbr/parametry/routes.py::api_parametry_etapy_create`, locate the legacy branch (currently lines 170-184 — the code after the `# Legacy path` comment). Replace the block from `existing = db.execute(...)` through `return jsonify({"ok": True, "id": new_id})` (inclusive) with:

```python
        # Legacy path
        existing = db.execute(
            "SELECT id FROM parametry_etapy WHERE parametr_id=? AND kontekst=? AND produkt IS ?",
            (parametr_id, kontekst, produkt),
        ).fetchone()
        if existing:
            return jsonify({"error": "Duplicate binding"}), 409
        if "grupa" in data:
            grupa = data["grupa"]
        else:
            gr_row = db.execute(
                "SELECT grupa FROM parametry_analityczne WHERE id=?", (parametr_id,)
            ).fetchone()
            grupa = (gr_row["grupa"] if gr_row and gr_row["grupa"] else "lab")
        if grupa not in ALLOWED_GRUPY:
            return jsonify({"error": f"grupa must be one of: {', '.join(sorted(ALLOWED_GRUPY))}"}), 400
        cur = db.execute(
            """INSERT INTO parametry_etapy (parametr_id, kontekst, produkt, nawazka_g, min_limit, max_limit, grupa)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (parametr_id, kontekst, produkt, nawazka, mn, mx, grupa),
        )
        db.commit()
        new_id = cur.lastrowid
    return jsonify({"ok": True, "id": new_id})
```

- [ ] **Step 4: Run tests — confirm they PASS**

Run: `pytest tests/test_parametry_grupa_api.py -v -k binding_legacy`
Expected: all 3 pass.

- [ ] **Step 5: Run full suite**

Run: `pytest -q`
Expected: `796 passed, 19 skipped` (793 + 3 new).

- [ ] **Step 6: Commit**

```bash
git add mbr/parametry/routes.py tests/test_parametry_grupa_api.py
git commit -m "$(cat <<'EOF'
feat(parametry): new legacy-path binding inherits grupa from parametry_analityczne

POST /api/parametry/etapy legacy branch (non-pipeline products, writes to
parametry_etapy) now defaults grupa to parametry_analityczne.grupa when
the request body omits it. Explicit grupa in body still honored. Whitelist
validation applied.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Binding inheritance on `POST /api/parametry/etapy` — pipeline path

**Context:** The pipeline branch (line 142-167 in current code) calls `set_produkt_etap_limit(db, produkt, etap_id, parametr_id, **kwargs)`. The helper's `_PEL_ALLOWED_FIELDS` whitelist does NOT include `grupa`, so even if we pass it, it'd be dropped. Need to (a) add `grupa` to the whitelist and (b) pass it from the route.

**Files:**
- Modify: `mbr/pipeline/models.py` (`_PEL_ALLOWED_FIELDS` at ~line 301)
- Modify: `mbr/parametry/routes.py::api_parametry_etapy_create` (pipeline branch, ~line 142-167)
- Extend test: `tests/test_parametry_grupa_api.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_parametry_grupa_api.py`:

```python
def _seed_pipeline_product(db, produkt="TEST_PIPE"):
    """Set up minimal pipeline so the route takes the pipeline branch."""
    db.execute("INSERT OR IGNORE INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
               "VALUES (6, 'analiza_koncowa', 'Analiza końcowa', 'jednorazowy')")
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES (?, 6, 1)",
               (produkt,))
    db.commit()


def test_binding_pipeline_inherits_grupa_from_parametr(client, db):
    """POST /api/parametry/etapy for a PIPELINE product (writes to produkt_etap_limity)
    inherits grupa from parametry_analityczne."""
    pid = _seed_param(db, "tpc", "zewn")
    _seed_pipeline_product(db, "TEST_PIPE")
    r = client.post("/api/parametry/etapy", json={
        "parametr_id": pid, "kontekst": "analiza_koncowa", "produkt": "TEST_PIPE",
        "min_limit": 0, "max_limit": 100,
    })
    assert r.status_code == 200, r.get_json()
    row = db.execute(
        "SELECT grupa FROM produkt_etap_limity WHERE produkt='TEST_PIPE' AND parametr_id=?",
        (pid,),
    ).fetchone()
    assert row is not None
    assert row["grupa"] == "zewn"


def test_binding_pipeline_honors_explicit_grupa_override(client, db):
    pid = _seed_param(db, "tpc", "zewn")
    _seed_pipeline_product(db, "TEST_PIPE")
    r = client.post("/api/parametry/etapy", json={
        "parametr_id": pid, "kontekst": "analiza_koncowa", "produkt": "TEST_PIPE",
        "grupa": "lab",
        "min_limit": 0, "max_limit": 100,
    })
    assert r.status_code == 200
    row = db.execute(
        "SELECT grupa FROM produkt_etap_limity WHERE produkt='TEST_PIPE' AND parametr_id=?",
        (pid,),
    ).fetchone()
    assert row["grupa"] == "lab"


def test_binding_pipeline_rejects_invalid_grupa(client, db):
    pid = _seed_param(db, "tpc", "lab")
    _seed_pipeline_product(db, "TEST_PIPE")
    r = client.post("/api/parametry/etapy", json={
        "parametr_id": pid, "kontekst": "analiza_koncowa", "produkt": "TEST_PIPE",
        "grupa": "nonsense",
    })
    assert r.status_code == 400
```

- [ ] **Step 2: Run tests — confirm they FAIL**

Run: `pytest tests/test_parametry_grupa_api.py -v -k binding_pipeline`
Expected: inherit test fails (grupa not passed / not in whitelist → default 'lab' winds up in produkt_etap_limity). Others fail too.

- [ ] **Step 3: Add `grupa` to `_PEL_ALLOWED_FIELDS`**

In `mbr/pipeline/models.py`, line 301:

```python
_PEL_ALLOWED_FIELDS = {"min_limit", "max_limit", "nawazka_g", "precision", "spec_value"}
```

Replace with:

```python
_PEL_ALLOWED_FIELDS = {"min_limit", "max_limit", "nawazka_g", "precision", "spec_value", "grupa"}
```

- [ ] **Step 4: Thread `grupa` through the pipeline branch**

In `mbr/parametry/routes.py::api_parametry_etapy_create`, replace the pipeline branch body (the block starting with `# Check if product has pipeline` at ~line 141, through the `return jsonify({"ok": True, "id": pel["id"] if pel else 0})` at ~line 167) with:

```python
        # Check if product has pipeline
        if produkt:
            from mbr.pipeline.models import get_produkt_pipeline, set_produkt_etap_limit, add_etap_parametr
            pipeline = get_produkt_pipeline(db, produkt)
            if pipeline:
                etap_id = _find_pipeline_etap_id(db, produkt, kontekst, pipeline)
                if etap_id:
                    # Resolve grupa: explicit body value → else inherit from parametry_analityczne → else 'lab'
                    if "grupa" in data:
                        grupa_val = data["grupa"]
                    else:
                        gr_row = db.execute(
                            "SELECT grupa FROM parametry_analityczne WHERE id=?", (parametr_id,)
                        ).fetchone()
                        grupa_val = (gr_row["grupa"] if gr_row and gr_row["grupa"] else "lab")
                    if grupa_val not in ALLOWED_GRUPY:
                        return jsonify({"error": f"grupa must be one of: {', '.join(sorted(ALLOWED_GRUPY))}"}), 400
                    # Ensure param exists in global etap_parametry
                    existing_ep = db.execute(
                        "SELECT id FROM etap_parametry WHERE etap_id=? AND parametr_id=?",
                        (etap_id, parametr_id),
                    ).fetchone()
                    max_kol = db.execute(
                        "SELECT MAX(kolejnosc) FROM etap_parametry WHERE etap_id=?",
                        (etap_id,),
                    ).fetchone()[0] or 0
                    if not existing_ep:
                        add_etap_parametr(db, etap_id, parametr_id, kolejnosc=max_kol + 1)
                    # Set product limit — include grupa
                    set_produkt_etap_limit(db, produkt, etap_id, parametr_id,
                                          min_limit=mn, max_limit=mx, nawazka_g=nawazka,
                                          grupa=grupa_val)
                    pel = db.execute(
                        "SELECT id FROM produkt_etap_limity WHERE produkt=? AND etap_id=? AND parametr_id=?",
                        (produkt, etap_id, parametr_id),
                    ).fetchone()
                    db.commit()
                    return jsonify({"ok": True, "id": pel["id"] if pel else 0})
```

- [ ] **Step 5: Run tests — confirm they PASS**

Run: `pytest tests/test_parametry_grupa_api.py -v -k binding_pipeline`
Expected: all 3 pass.

- [ ] **Step 6: Run full suite**

Run: `pytest -q`
Expected: `799 passed, 19 skipped` (796 + 3 new).

- [ ] **Step 7: Commit**

```bash
git add mbr/pipeline/models.py mbr/parametry/routes.py tests/test_parametry_grupa_api.py
git commit -m "$(cat <<'EOF'
feat(parametry): new pipeline-path binding inherits grupa from parametry_analityczne

Adds 'grupa' to _PEL_ALLOWED_FIELDS so set_produkt_etap_limit can persist
it. Pipeline branch of POST /api/parametry/etapy resolves grupa the same
way as the legacy branch (explicit body → inherit → 'lab' fallback) and
whitelist-validates before writing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Admin UI — grupa dropdown in Rejestr tab

**Files:**
- Modify: `mbr/templates/parametry_editor.html` (Rejestr tab — create form + edit form + list column)

**Note:** This task is JS/HTML only. No pytest tests (JS not covered by backend suite). Verify via manual smoke + backend tests still green.

- [ ] **Step 1: Find the Rejestr tab create form**

Run:
```bash
grep -n "api/parametry" mbr/templates/parametry_editor.html | head -20
grep -n "typ.*select\|<select.*typ" mbr/templates/parametry_editor.html | head -10
```

Identify (a) the POST submit JS function, (b) the typ `<select>` element that serves as a styling template.

- [ ] **Step 2: Add grupa field to the create form**

In `mbr/templates/parametry_editor.html`, in the Rejestr tab's create/new-parametr form section, immediately after the existing `typ` `<select>` element (where options `bezposredni / obliczeniowy / titracja / jakosciowy / binarny` are listed), add a new form field:

```html
<label>Grupa
  <select id="new-grupa">
    <option value="lab" selected>Lab (wewnętrzny)</option>
    <option value="zewn">Zewn. lab</option>
  </select>
</label>
```

- [ ] **Step 3: Include `grupa` in the create POST payload**

Find the JS function that POSTs to `/api/parametry` (name varies — likely `createParametr()` or `submitNewParam()`). In the `body: JSON.stringify({...})` call, add `grupa: document.getElementById('new-grupa').value`.

Example — the old body might be:

```javascript
body: JSON.stringify({
  kod: kod, label: label, typ: typ, skrot: skrot, precision: precision,
  jednostka: jednostka, name_en: name_en, method_code: method_code,
})
```

Change to:

```javascript
body: JSON.stringify({
  kod: kod, label: label, typ: typ, skrot: skrot, precision: precision,
  jednostka: jednostka, name_en: name_en, method_code: method_code,
  grupa: document.getElementById('new-grupa').value,
})
```

- [ ] **Step 4: Add grupa column to the Rejestr list table**

Find the Rejestr tab's parametr list table render function (likely `renderParametryList()` or similar, building a `<tr>` per param). Add a `<th>Grupa</th>` header cell next to the `Typ` header, and a `<td>` in each row rendering `p.grupa || 'lab'`:

Example snippet to insert after the `typ` cell in the row builder:

```javascript
html += '<td>' + (p.grupa || 'lab') + '</td>';
```

And in the thead row, after `<th>Typ</th>`:

```html
<th>Grupa</th>
```

- [ ] **Step 5: Add grupa to the edit-in-place UX (if Rejestr tab has inline edit)**

If the Rejestr tab allows editing typ via a `<select>` that fires PUT /api/parametry/<id> onChange — add a parallel `<select>` for grupa with the two options. Structure mirrors the typ edit.

If no inline-edit exists for typ (grep: `PUT.*parametry` with `onChange` handler in the template), skip this step — edits go through the create form re-submitting.

- [ ] **Step 6: Manual smoke test**

Start dev server:
```bash
python -m mbr.app &
SERVER_PID=$!
sleep 2
```

Open `http://localhost:5001/parametry` in a browser, log in as admin.

1. Rejestr tab: verify the "Grupa" column shows in the list with 'lab' for all existing params.
2. Create new param: fill in kod/label/typ, pick `Zewn. lab` in grupa dropdown, submit.
3. Refresh list — new param shows with `zewn` in the Grupa column.
4. If inline edit exists: change grupa for existing param, refresh, verify persisted.

Then:
```bash
kill $SERVER_PID
```

Document what you observed in the commit message (e.g., "tested: create as lab + create as zewn, both persist correctly").

- [ ] **Step 7: Run backend test suite**

Run: `pytest -q`
Expected: `799 passed, 19 skipped` — unchanged (no backend changes in this task).

- [ ] **Step 8: Commit**

```bash
git add mbr/templates/parametry_editor.html
git commit -m "$(cat <<'EOF'
feat(parametry): grupa dropdown in Rejestr tab admin UI

Create form gains a 'Grupa' select (lab / zewn). Rejestr list table
shows a Grupa column. Value is posted to /api/parametry and persisted.

Smoke tested: [note what you tested — e.g., created a 'tpc' param
with grupa='zewn', verified persists in DB].

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Regression test — completed-batches list shows `grupa='zewn'` column

**Files:**
- Create test: `tests/test_registry_grupa.py`

- [ ] **Step 1: Write the test**

Create `tests/test_registry_grupa.py`:

```python
"""Regression: completed-batches registry columns include grupa='zewn' params (no filter)."""

import sqlite3
import json
import pytest

from mbr.models import init_mbr_tables
from mbr.registry.models import get_registry_columns


def _seed_with_zewn_param(db):
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ, skrot, precision, grupa) "
               "VALUES (100, 'tpc', 'Total plate count', 'bezposredni', 'TPC', 0, 'zewn')")
    db.execute("INSERT OR IGNORE INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
               "VALUES (6, 'analiza_koncowa', 'Analiza końcowa', 'jednorazowy')")
    db.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (6, 100, 1)")
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('TEST_PROD', 6, 1)")
    db.execute("INSERT INTO produkt_etap_limity (produkt, etap_id, parametr_id, grupa, dla_szarzy, dla_zbiornika, dla_platkowania) "
               "VALUES ('TEST_PROD', 6, 100, 'zewn', 1, 1, 0)")
    # Minimal MBR template so get_registry_columns has something to reference
    db.execute("INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, dt_utworzenia) "
               "VALUES ('TEST_PROD', 1, 'active', '[]', '{}', datetime('now'))")
    db.commit()


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    _seed_with_zewn_param(conn)
    yield conn
    conn.close()


def test_registry_columns_include_zewn_parametr(db):
    cols = get_registry_columns(db, "TEST_PROD")
    kods = [c["kod"] for c in cols if "kod" in c]
    assert "tpc" in kods, f"zewn param must appear in registry columns, got: {kods}"


def test_registry_column_has_grupa_metadata(db):
    cols = get_registry_columns(db, "TEST_PROD")
    tpc_col = next((c for c in cols if c.get("kod") == "tpc"), None)
    assert tpc_col is not None
    # Grupa metadata flows through if present in the column dict
    assert tpc_col.get("grupa") == "zewn" or "grupa" not in tpc_col, (
        "If grupa is exposed on columns, it must be 'zewn' (not filtered)"
    )
```

- [ ] **Step 2: Run — confirm it PASSES**

Run: `pytest tests/test_registry_grupa.py -v`
Expected: both pass (the current render pipeline is already grupa-agnostic, so this is a PROTECTIVE test that locks in current correct behavior).

If either test FAILS: investigate immediately. That means there's a grupa filter somewhere that the spec missed.

- [ ] **Step 3: Run full suite**

Run: `pytest -q`
Expected: `801 passed, 19 skipped` (799 + 2 new).

- [ ] **Step 4: Commit**

```bash
git add tests/test_registry_grupa.py
git commit -m "$(cat <<'EOF'
test(registry): completed-batches columns include grupa='zewn' params

Regression guard: lock in that get_registry_columns does NOT filter
by grupa. Protects against future filters silently hiding external-lab
params.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Regression test — cert generation renders value for `grupa='zewn'` param

**Files:**
- Create test: `tests/test_certs_grupa.py`

- [ ] **Step 1: Write the test**

Create `tests/test_certs_grupa.py`:

```python
"""Regression: cert generation includes grupa='zewn' params when on_cert=1 and value exists."""

import sqlite3
import pytest

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def _seed_zewn_cert(db, produkt="TEST_CERT_PROD"):
    # Param with grupa='zewn'
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ, skrot, precision, grupa) "
               "VALUES (200, 'tpc', 'Total plate count', 'bezposredni', 'TPC', 0, 'zewn')")
    # produkty row so build_context doesn't fail
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES (?, ?)",
               (produkt, "Test Cert Product"))
    # cert_variants row
    cv_id = db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label) VALUES (?, 'base', 'Base')",
        (produkt,),
    ).lastrowid
    # parametry_cert so get_cert_params returns this param for the product
    db.execute(
        """INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format)
           VALUES (?, 200, 1, '<100 CFU/g', '1')""",
        (produkt,),
    )
    db.commit()
    return cv_id


def test_build_context_renders_zewn_value(db):
    from mbr.certs.generator import build_context

    _seed_zewn_cert(db, produkt="TEST_CERT_PROD")

    # Simulated wyniki_flat as cert routes.py would pass — keyed by kod
    wyniki_flat = {"tpc": {"wartosc": 45.0}}

    ctx = build_context(
        produkt="TEST_CERT_PROD",
        variant_id="base",
        nr_partii="1/2026",
        dt_start="2026-04-19",
        wyniki_flat=wyniki_flat,
        extra_fields={},
        wystawil="tester",
    )

    # Context must contain a row whose result is '45' (format='1' → integer)
    rows = ctx.get("rows") or []
    tpc_rows = [r for r in rows if "Total plate count" in str(r.get("name_pl", ""))]
    assert tpc_rows, f"tpc row not found in cert rows, got: {[str(r.get('name_pl'))[:40] for r in rows]}"
    assert "45" in str(tpc_rows[0].get("result", "")), (
        f"tpc value missing from result: {tpc_rows[0].get('result')!r}"
    )


def test_build_context_empty_value_for_zewn_param(db):
    """When the external-lab value hasn't been entered yet, cert renders an empty result row."""
    from mbr.certs.generator import build_context

    _seed_zewn_cert(db, produkt="TEST_CERT_PROD")

    ctx = build_context(
        produkt="TEST_CERT_PROD",
        variant_id="base",
        nr_partii="1/2026",
        dt_start="2026-04-19",
        wyniki_flat={},  # KJ hasn't entered anything yet
        extra_fields={},
        wystawil="tester",
    )
    rows = ctx.get("rows") or []
    tpc_rows = [r for r in rows if "Total plate count" in str(r.get("name_pl", ""))]
    assert tpc_rows, "tpc row must still appear on cert even without value"
    assert str(tpc_rows[0].get("result", "")) == "", (
        f"Expected empty result, got: {tpc_rows[0].get('result')!r}"
    )
```

- [ ] **Step 2: Run — confirm it PASSES**

Run: `pytest tests/test_certs_grupa.py -v`
Expected: both pass. Cert generation is already grupa-agnostic so this locks in current behavior.

If either fails: investigate. Possible cause: missing columns on `produkty` or other seed tables — read the error, fix the fixture if needed. Do NOT change `build_context` — the rendering code should not need grupa awareness.

- [ ] **Step 3: Run full suite**

Run: `pytest -q`
Expected: `803 passed, 19 skipped` (801 + 2 new).

- [ ] **Step 4: Commit**

```bash
git add tests/test_certs_grupa.py
git commit -m "$(cat <<'EOF'
test(certs): cert renders grupa='zewn' param value when present + empty when absent

Regression guard: lock in that build_context does NOT filter by grupa;
confirms empty-value case renders the row (laborant generates cert early,
KJ fills value later, cert is regenerated manually).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Final verification + PR prep

**Files:** n/a

- [ ] **Step 1: Full test suite**

Run: `pytest -q`
Expected: `803 passed, 19 skipped`.

- [ ] **Step 2: Manual end-to-end smoke (optional but recommended)**

Start server:
```bash
python -m mbr.app &
SERVER_PID=$!
sleep 2
```

As admin:
1. `/parametry` → Rejestr tab → create param `tpc_manual` with `grupa='zewn'`, typ='bezposredni'.
2. `/parametry` → Etapy tab → bind `tpc_manual` to a test product + `analiza_koncowa` sekcja.
3. DB inspect: `sqlite3 data/batch_db.sqlite "SELECT grupa FROM parametry_analityczne WHERE kod='tpc_manual'; SELECT grupa FROM parametry_etapy WHERE parametr_id=(SELECT id FROM parametry_analityczne WHERE kod='tpc_manual') LIMIT 1;"` — both should show `zewn`.
4. Clean up: `sqlite3 data/batch_db.sqlite "DELETE FROM parametry_etapy WHERE parametr_id=(SELECT id FROM parametry_analityczne WHERE kod='tpc_manual'); DELETE FROM parametry_analityczne WHERE kod='tpc_manual';"`.

Kill server: `kill $SERVER_PID`.

- [ ] **Step 3: Branch log review**

Run:
```bash
git log --oneline main..HEAD
```
Expected: ~8 commits (one per task, plus Task 0 which has no commit).

- [ ] **Step 4: Leave the branch ready — no push**

No additional commits. Branch `feat/external-lab-params` is ready for merge review by the user through the `superpowers:finishing-a-development-branch` skill when they're ready.

---

## Self-Review

**Spec coverage:**
- Schema change (spec §Components 1) → Task 1 ✓
- `POST /api/parametry` grupa (spec §Components 2) → Task 2 ✓
- `PUT /api/parametry/<id>` grupa (spec §Components 2) → Task 3 ✓
- Binding inheritance legacy (spec §Components 3) → Task 4 ✓
- Binding inheritance pipeline (spec §Components 3) → Task 5 ✓
- Admin UI Rejestr tab (spec §Components 4) → Task 6 ✓
- Grupa-agnostic completed-list verification (spec §Components 5) → Task 7 ✓
- Grupa-agnostic cert verification (spec §Components 5) → Task 8 ✓
- Role access unchanged (spec §Components 6) — no task needed, verified in Task 5 tests
- Error handling table (spec §Error handling) — each row mapped to a validation test in Tasks 2-5

All spec sections covered.

**Placeholder scan:** No TBD/TODO/"add validation"/"similar to Task N" strings. Each step has exact code or exact command.

**Type consistency:**
- `ALLOWED_GRUPY` is defined in Task 2 (top of `mbr/parametry/routes.py`) and referenced in Tasks 3, 4, 5. Same name.
- `grupa` field name consistent across all tasks.
- Test file names: all lowercase snake_case, matching existing tests convention.
- Column name `grupa` consistent across all tables (`parametry_analityczne`, `parametry_etapy`, `produkt_etap_limity`) — confirmed against real DB schema.
- `_PEL_ALLOWED_FIELDS` set extended in Task 5; `set_produkt_etap_limit` signature unchanged (just accepts more kwargs).

**Risk of breaking existing tests (803 expected):**
- Task 1 adds a column to `parametry_analityczne` — existing tests that don't mention `grupa` continue to work (column has DEFAULT). Low risk.
- Task 2 modifies `api_parametry_create` — tests that already POST /api/parametry must still work. Default grupa=`'lab'` when not provided preserves old behavior.
- Task 3 modifies `api_parametry_update` — whitelist check for `grupa` returns 400 only when `grupa` is explicitly in body with invalid value. Old requests without `grupa` unaffected.
- Task 4/5 modify binding creation. Risk: any existing test that POSTs `/api/parametry/etapy` with grupa='something weird' would now fail. Need to check — but existing tests in `tests/test_bindings_api.py` only use valid 'lab' values (grep confirmed). Low risk.
- Tasks 6-8 are additive (new UI + new tests). No risk to existing.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-19-external-lab-params.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, spec + code-quality review between tasks. Fast iteration. 8 tasks → ~1.5–2 hours of driven work.
2. **Inline Execution** — execute tasks in this session via `superpowers:executing-plans`, checkpoints every 2–3 tasks.

Which approach?
