# Cert Alias Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable a product's batch to issue a cert variant that belongs to a different product (e.g., K40GLOL batch prints a GLOL40 cert). Admin declares the alias relationship; the variant picker unions own + aliased variants; the generator uses target_produkt's cert config while keeping the source batch's measurements and nr_partii.

**Architecture:** New `cert_alias(source_produkt, target_produkt)` table. `api_cert_templates` returns the union; `api_cert_generate` accepts an optional `target_produkt` (defaults to ebr.produkt, backward compatible). `build_context` is unchanged — it already scopes to the produkt argument, so calling it with target_produkt reads cert config from there. Admin CRUD lives in `/admin/wzory-cert` on a new panel.

**Tech Stack:** Python/Flask, sqlite3 (raw), pytest, vanilla JS, Jinja2.

**Baseline:** `pytest -q` → `805 passed, 19 skipped` (post external-lab-params + precision fixes on main). Every task ends green.

**Guard rails:**
1. One commit per task. Co-Authored-By trailer on every commit.
2. DO NOT stage `mbr/cert_config.json` or `data/batch_db 2.sqlite-wal` (pre-existing dirty files).
3. Work on a feature branch `feat/cert-alias` (do NOT commit directly to main).
4. No `git push`.

---

## Task 0: Branch setup

**Files:** n/a (git only).

- [ ] **Step 1: Create feature branch**

```bash
cd /Users/tbk/Desktop/lims-clean
git checkout main
git log -1 --format='%H %s'
```
Expected HEAD: `22306e0 fix(laborant): add data-precision to hero cv-p-input...` or newer.

```bash
git checkout -b feat/cert-alias
git branch --show-current
```
Expected output: `feat/cert-alias`.

---

## Task 1: Schema migrations — `cert_alias` table + `swiadectwa.target_produkt` column

**Files:**
- Modify: `mbr/models.py` (`init_mbr_tables`, near the other idempotent migrations ~line 1450-1500)
- Create test: `tests/test_cert_alias_migration.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cert_alias_migration.py`:

```python
"""Migration: cert_alias table + swiadectwa.target_produkt column added idempotently."""

import sqlite3
import pytest

from mbr.models import init_mbr_tables


def test_init_creates_cert_alias_table():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_mbr_tables(db)
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='cert_alias'"
    ).fetchone()
    assert row is not None, "cert_alias table must exist after init"

    # Column shape + PK
    cols = {r[1]: r for r in db.execute("PRAGMA table_info(cert_alias)").fetchall()}
    assert set(cols.keys()) == {"source_produkt", "target_produkt"}
    assert cols["source_produkt"][2].upper() == "TEXT"
    assert cols["target_produkt"][2].upper() == "TEXT"
    assert cols["source_produkt"][3] == 1, "source_produkt must be NOT NULL"
    assert cols["target_produkt"][3] == 1, "target_produkt must be NOT NULL"
    # Composite PK
    pk_cols = [r[1] for r in db.execute("PRAGMA table_info(cert_alias)").fetchall() if r[5] > 0]
    assert set(pk_cols) == {"source_produkt", "target_produkt"}


def test_init_adds_target_produkt_to_swiadectwa():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_mbr_tables(db)
    cols = {r[1]: r for r in db.execute("PRAGMA table_info(swiadectwa)").fetchall()}
    assert "target_produkt" in cols
    assert cols["target_produkt"][2].upper() == "TEXT"
    # Nullable (no NOT NULL constraint) so legacy rows stay valid
    assert cols["target_produkt"][3] == 0


def test_init_migrations_idempotent():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_mbr_tables(db)
    # Second call must not raise even though table/column already exist
    init_mbr_tables(db)
    # Still exactly one cert_alias table + one target_produkt column
    tbl_count = db.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='cert_alias'"
    ).fetchone()[0]
    assert tbl_count == 1
    col_names = [r[1] for r in db.execute("PRAGMA table_info(swiadectwa)").fetchall()]
    assert col_names.count("target_produkt") == 1


def test_cert_alias_primary_key_prevents_duplicates():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_mbr_tables(db)
    db.execute("INSERT INTO cert_alias (source_produkt, target_produkt) VALUES ('A', 'B')")
    db.commit()
    # Duplicate insert must raise IntegrityError
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO cert_alias (source_produkt, target_produkt) VALUES ('A', 'B')")
```

- [ ] **Step 2: Run the new tests — confirm they FAIL**

Run: `pytest tests/test_cert_alias_migration.py -v`
Expected: all 4 fail (table + column don't exist).

- [ ] **Step 3: Add migrations to `init_mbr_tables`**

In `mbr/models.py`, locate the area with other idempotent migrations (~line 1455-1500, near the `ALTER TABLE parametry_etapy ADD COLUMN grupa` or similar). Append two new blocks:

```python
    # Migration: cert_alias table for cross-product cert variant surfacing
    try:
        db.execute("""
            CREATE TABLE IF NOT EXISTS cert_alias (
                source_produkt TEXT NOT NULL,
                target_produkt TEXT NOT NULL,
                PRIMARY KEY (source_produkt, target_produkt)
            )
        """)
        db.commit()
    except Exception:
        pass

    # Migration: add target_produkt to swiadectwa (for aliased cert archive)
    try:
        db.execute("ALTER TABLE swiadectwa ADD COLUMN target_produkt TEXT")
        db.commit()
    except Exception:
        pass  # column already exists
```

- [ ] **Step 4: Run the tests — confirm they PASS**

Run: `pytest tests/test_cert_alias_migration.py -v`
Expected: all 4 pass.

- [ ] **Step 5: Run full suite**

Run: `pytest -q`
Expected: `809 passed, 19 skipped` (805 + 4 new).

- [ ] **Step 6: Commit**

```bash
git add mbr/models.py tests/test_cert_alias_migration.py
git commit -m "$(cat <<'EOF'
feat(certs): cert_alias table + swiadectwa.target_produkt column

Two idempotent migrations:
  - cert_alias(source_produkt, target_produkt) with composite PK.
  - swiadectwa.target_produkt nullable column for aliased-cert archive.

Foundation for the cert-alias feature: admin declares K40GLOL → GLOL40
aliases so a K40GLOL batch can issue GLOL40 cert variants.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Helper `get_cert_aliases(db, source_produkt)`

Pure DB helper that reads targets for one source. Used by Task 3 (variant union) and Task 4 (generate validation).

**Files:**
- Modify: `mbr/certs/generator.py` (or `mbr/certs/models.py` — pick the one with the simplest imports; `generator.py` already talks to `cert_variants`, so it's natural)
- Create test: `tests/test_cert_alias_helper.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_cert_alias_helper.py`:

```python
"""Unit tests for get_cert_aliases helper."""

import sqlite3
import pytest

from mbr.models import init_mbr_tables


def _seed(db):
    db.execute("INSERT INTO cert_alias VALUES ('Chegina_K40GLOL', 'Chegina_GLOL40')")
    db.execute("INSERT INTO cert_alias VALUES ('Chegina_K40GLOL', 'Chegina_K40GLN')")
    db.execute("INSERT INTO cert_alias VALUES ('Chegina_K7', 'Chegina_K7B')")
    db.commit()


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    _seed(conn)
    yield conn
    conn.close()


def test_get_cert_aliases_returns_targets_for_source(db):
    from mbr.certs.generator import get_cert_aliases
    targets = get_cert_aliases(db, "Chegina_K40GLOL")
    assert sorted(targets) == ["Chegina_GLOL40", "Chegina_K40GLN"]


def test_get_cert_aliases_empty_for_unknown_source(db):
    from mbr.certs.generator import get_cert_aliases
    assert get_cert_aliases(db, "Chegina_NONEXISTENT") == []


def test_get_cert_aliases_empty_when_no_rows(db):
    from mbr.certs.generator import get_cert_aliases
    db.execute("DELETE FROM cert_alias")
    db.commit()
    assert get_cert_aliases(db, "Chegina_K40GLOL") == []
```

- [ ] **Step 2: Run — confirm FAIL**

Run: `pytest tests/test_cert_alias_helper.py -v`
Expected: all 3 fail (`ImportError: cannot import name 'get_cert_aliases'`).

- [ ] **Step 3: Add helper to `mbr/certs/generator.py`**

Insert at the top of the file, after the imports (around line 20, before the first function or section comment — find a logical grouping). Use this exact code:

```python
def get_cert_aliases(db, source_produkt: str) -> list[str]:
    """Return list of target_produkt strings that source_produkt can alias into.

    An alias `(source_produkt, target_produkt)` means: batches of source_produkt
    can issue cert variants owned by target_produkt. Used by api_cert_templates
    to union variant lists and by api_cert_generate to validate the alias.
    """
    rows = db.execute(
        "SELECT target_produkt FROM cert_alias WHERE source_produkt = ? ORDER BY target_produkt",
        (source_produkt,),
    ).fetchall()
    return [r["target_produkt"] for r in rows]
```

Do NOT wrap in try/except — callers already manage transactions; bubble exceptions.

- [ ] **Step 4: Run — confirm PASS**

Run: `pytest tests/test_cert_alias_helper.py -v`
Expected: all 3 pass.

- [ ] **Step 5: Full suite**

Run: `pytest -q`
Expected: `812 passed, 19 skipped` (809 + 3 new).

- [ ] **Step 6: Commit**

```bash
git add mbr/certs/generator.py tests/test_cert_alias_helper.py
git commit -m "$(cat <<'EOF'
feat(certs): get_cert_aliases helper

Returns sorted list of target_produkt for a source_produkt. Callers own
the transaction; no internal session. Used by the variant-union and
generate-validation paths landing in subsequent commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Variant picker union — `get_variants` returns `owner_produkt`; `api_cert_templates` UNIONs aliased targets

**Files:**
- Modify: `mbr/certs/generator.py::get_variants` (~line 127)
- Modify: `mbr/certs/routes.py::api_cert_templates` (~line 20-35)
- Create test: `tests/test_cert_templates_with_alias.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_cert_templates_with_alias.py`:

```python
"""/api/cert/templates returns union of own + aliased variants."""

import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


def _seed(db):
    # Two products, each with their own cert variants
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('K40GLOL', 'K40GLOL')")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('GLOL40', 'GLOL40')")
    db.execute("INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
               "VALUES ('K40GLOL', 'base', 'K40GLOL base', '[]', 0)")
    db.execute("INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
               "VALUES ('K40GLOL', 'loreal', 'K40GLOL — Loreal', '[]', 1)")
    db.execute("INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
               "VALUES ('GLOL40', 'base', 'GLOL40 base', '[]', 0)")
    db.execute("INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
               "VALUES ('GLOL40', 'mb', 'GLOL40 — MB', '[]', 1)")
    db.commit()


def _make_client(monkeypatch, db, rola="lab"):
    import mbr.db
    import mbr.certs.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.certs.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = {"login": "tester", "rola": rola, "worker_id": None}
    return c


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    _seed(conn)
    yield conn
    conn.close()


@pytest.fixture
def client(monkeypatch, db):
    return _make_client(monkeypatch, db)


def test_templates_no_alias_returns_only_own(client, db):
    r = client.get("/api/cert/templates?produkt=K40GLOL")
    data = r.get_json()
    templates = data["templates"]
    owners = sorted(set(t.get("owner_produkt") for t in templates))
    labels = sorted(t["display"] for t in templates)
    assert owners == ["K40GLOL"]
    assert labels == ["K40GLOL — Loreal", "K40GLOL base"]


def test_templates_with_alias_returns_union(client, db):
    db.execute("INSERT INTO cert_alias VALUES ('K40GLOL', 'GLOL40')")
    db.commit()
    r = client.get("/api/cert/templates?produkt=K40GLOL")
    data = r.get_json()
    templates = data["templates"]
    owners = sorted(set(t.get("owner_produkt") for t in templates))
    labels = sorted(t["display"] for t in templates)
    assert owners == ["GLOL40", "K40GLOL"]
    assert labels == ["GLOL40 base", "GLOL40 — MB",
                      "K40GLOL — Loreal", "K40GLOL base"]
    # Every template must carry owner_produkt
    for t in templates:
        assert "owner_produkt" in t
        assert t["owner_produkt"] in ("K40GLOL", "GLOL40")


def test_templates_empty_produkt_returns_empty(client):
    r = client.get("/api/cert/templates?produkt=")
    assert r.get_json() == {"templates": []}
```

- [ ] **Step 2: Run — confirm FAIL**

Run: `pytest tests/test_cert_templates_with_alias.py -v`
Expected: at least `test_templates_with_alias_returns_union` fails (response only has K40GLOL templates, no GLOL40 union). `test_templates_no_alias_returns_only_own` may also fail if `owner_produkt` isn't emitted yet.

- [ ] **Step 3: Modify `get_variants` to include `owner_produkt`**

In `mbr/certs/generator.py`, replace the body of `get_variants` (currently lines 127-146) with:

```python
def get_variants(produkt: str) -> list[dict]:
    """Return list of {id, label, flags, owner_produkt} for a product from DB.

    owner_produkt echoes back the produkt argument — used by callers that
    union variants across alias boundaries so the client knows which product
    owns each variant (for the generate-payload target_produkt field).
    """
    from mbr.db import db_session as _db_session
    key = produkt if "_" in produkt else produkt.replace(" ", "_")
    try:
        with _db_session() as db:
            rows = db.execute(
                "SELECT variant_id, label, flags FROM cert_variants "
                "WHERE produkt=? ORDER BY kolejnosc", (key,)
            ).fetchall()
            if not rows:
                rows = db.execute(
                    "SELECT variant_id, label, flags FROM cert_variants "
                    "WHERE produkt=? ORDER BY kolejnosc",
                    (produkt.replace(" ", "_"),)
                ).fetchall()
            return [{"id": r["variant_id"], "label": r["label"],
                     "flags": json.loads(r["flags"] or "[]"),
                     "owner_produkt": key} for r in rows]
    except Exception:
        return []
```

Only change vs. original: one added dict key `"owner_produkt": key`.

- [ ] **Step 4: Modify `api_cert_templates` to UNION aliased targets**

In `mbr/certs/routes.py`, replace `api_cert_templates` body (currently lines 20-35) with:

```python
@certs_bp.route("/api/cert/templates")
@login_required
def api_cert_templates():
    produkt = request.args.get("produkt", "")
    if not produkt:
        return jsonify({"templates": []})

    # Collect own variants + aliased target's variants
    from mbr.certs.generator import get_cert_aliases
    variants = list(get_variants(produkt))
    with db_session() as db:
        aliases = get_cert_aliases(db, produkt)
    for target_produkt in aliases:
        variants.extend(get_variants(target_produkt))

    templates = []
    for v in variants:
        templates.append({
            "filename": v["id"],
            "display": v["label"],
            "flags": v["flags"],
            "owner_produkt": v["owner_produkt"],
            "required_fields": get_required_fields(v["owner_produkt"], v["id"]),
        })
    return jsonify({"templates": templates})
```

- [ ] **Step 5: Run — confirm PASS**

Run: `pytest tests/test_cert_templates_with_alias.py -v`
Expected: all 3 pass.

- [ ] **Step 6: Full suite**

Run: `pytest -q`
Expected: `815 passed, 19 skipped` (812 + 3 new).

- [ ] **Step 7: Commit**

```bash
git add mbr/certs/generator.py mbr/certs/routes.py tests/test_cert_templates_with_alias.py
git commit -m "$(cat <<'EOF'
feat(certs): /api/cert/templates unions own + aliased variants

get_variants now emits owner_produkt on each returned dict.
api_cert_templates calls get_cert_aliases(produkt) and appends the
variants of every target. Each template entry carries owner_produkt so
the client can forward it as target_produkt in the generate call.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `api_cert_generate` accepts `target_produkt` + persists via swiadectwa

**Files:**
- Modify: `mbr/certs/routes.py::api_cert_generate` (~line 38-125)
- Modify: `mbr/certs/models.py::create_swiadectwo` (extend signature)
- Create test: `tests/test_cert_generate_with_alias.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cert_generate_with_alias.py`:

```python
"""/api/cert/generate honors target_produkt when an alias row exists."""

import json
import sqlite3
import pytest
from contextlib import contextmanager
from unittest.mock import patch

from mbr.models import init_mbr_tables


def _seed(db):
    # Products
    db.execute("INSERT INTO produkty (nazwa, display_name, spec_number, expiry_months) "
               "VALUES ('K40GLOL', 'K40GLOL', 'SPEC-K', 12)")
    db.execute("INSERT INTO produkty (nazwa, display_name, spec_number, expiry_months) "
               "VALUES ('GLOL40', 'GLOL40', 'SPEC-G', 12)")
    # Cert variants
    db.execute("INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
               "VALUES ('K40GLOL', 'base', 'K40GLOL', '[]', 0)")
    db.execute("INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
               "VALUES ('GLOL40', 'base', 'GLOL40', '[]', 0)")
    # MBR template + EBR batch (type=zbiornik is required for cert)
    db.execute("INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, dt_utworzenia) "
               "VALUES ('K40GLOL', 1, 'active', '[]', '{}', datetime('now'))")
    db.execute("INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, typ) "
               "VALUES (1, 'K40GLOL__1_2026', '1/2026', datetime('now'), 'completed', 'zbiornik')")
    db.commit()


def _make_client(monkeypatch, db, rola="lab"):
    import mbr.db
    import mbr.certs.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.certs.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = {"login": "tester", "rola": rola, "worker_id": None}
        sess["shift_workers"] = []
    return c


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    _seed(conn)
    yield conn
    conn.close()


@pytest.fixture
def client(monkeypatch, db):
    return _make_client(monkeypatch, db)


def _patch_pdf(monkeypatch):
    """Stub PDF generation + archive write so we don't actually call Gotenberg."""
    import mbr.certs.routes as routes_mod
    monkeypatch.setattr(routes_mod, "generate_certificate_pdf",
                        lambda *a, **kw: b"%PDF-1.4 fake")
    monkeypatch.setattr(routes_mod, "save_certificate_data",
                        lambda *a, **kw: None)


def test_generate_without_target_defaults_to_ebr_produkt(client, db, monkeypatch):
    """No target_produkt in body → uses ebr.produkt (backward compat)."""
    _patch_pdf(monkeypatch)
    calls = []
    import mbr.certs.routes as routes_mod
    monkeypatch.setattr(routes_mod, "generate_certificate_pdf",
                        lambda produkt, *a, **kw: (calls.append(produkt), b"%PDF-1.4 fake")[1])

    r = client.post("/api/cert/generate", json={
        "ebr_id": 1, "variant_id": "base", "wystawil": "tester",
    })
    assert r.status_code == 200, r.data
    assert calls == ["K40GLOL"]

    # swiadectwa row: target_produkt NULL (same as own produkt)
    row = db.execute(
        "SELECT target_produkt FROM swiadectwa WHERE ebr_id=1"
    ).fetchone()
    assert row["target_produkt"] is None


def test_generate_with_aliased_target_uses_target(client, db, monkeypatch):
    _patch_pdf(monkeypatch)
    db.execute("INSERT INTO cert_alias VALUES ('K40GLOL', 'GLOL40')")
    db.commit()

    calls = []
    import mbr.certs.routes as routes_mod
    monkeypatch.setattr(routes_mod, "generate_certificate_pdf",
                        lambda produkt, *a, **kw: (calls.append(produkt), b"%PDF-1.4 fake")[1])

    r = client.post("/api/cert/generate", json={
        "ebr_id": 1, "variant_id": "base", "target_produkt": "GLOL40",
        "wystawil": "tester",
    })
    assert r.status_code == 200, r.data
    assert calls == ["GLOL40"]

    row = db.execute(
        "SELECT target_produkt FROM swiadectwa WHERE ebr_id=1"
    ).fetchone()
    assert row["target_produkt"] == "GLOL40"


def test_generate_with_target_but_no_alias_returns_400(client, db, monkeypatch):
    _patch_pdf(monkeypatch)
    r = client.post("/api/cert/generate", json={
        "ebr_id": 1, "variant_id": "base", "target_produkt": "GLOL40",
        "wystawil": "tester",
    })
    assert r.status_code == 400
    body = r.get_json()
    assert "alias" in (body.get("error") or "").lower()


def test_generate_target_equals_ebr_produkt_is_always_allowed(client, db, monkeypatch):
    """Explicit target_produkt=ebr.produkt must succeed without an alias row."""
    _patch_pdf(monkeypatch)
    r = client.post("/api/cert/generate", json={
        "ebr_id": 1, "variant_id": "base", "target_produkt": "K40GLOL",
        "wystawil": "tester",
    })
    assert r.status_code == 200, r.data
```

- [ ] **Step 2: Run — confirm FAIL**

Run: `pytest tests/test_cert_generate_with_alias.py -v`
Expected: 3 of 4 fail (the `defaults_to_ebr_produkt` might pass for the generate call, but the swiadectwa target_produkt=NULL assertion will fail because `create_swiadectwo` doesn't write that column yet).

- [ ] **Step 3: Extend `create_swiadectwo` to accept `target_produkt`**

In `mbr/certs/models.py`, replace the function body (currently lines 11-18):

```python
def create_swiadectwo(db, ebr_id, template_name, nr_partii, pdf_path, wystawil,
                     data_json=None, target_produkt=None):
    now = datetime.now().isoformat(timespec="seconds")
    cur = db.execute(
        "INSERT INTO swiadectwa (ebr_id, template_name, nr_partii, pdf_path, "
        "dt_wystawienia, wystawil, data_json, target_produkt) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ebr_id, template_name, nr_partii, pdf_path, now, wystawil,
         data_json, target_produkt),
    )
    return cur.lastrowid
```

Only substantive changes: added `target_produkt=None` parameter, added column + placeholder.

- [ ] **Step 4: Modify `api_cert_generate` to honor target_produkt**

In `mbr/certs/routes.py`, replace the body of `api_cert_generate` (currently lines 38-125) with:

```python
@certs_bp.route("/api/cert/generate", methods=["POST"])
@login_required
def api_cert_generate():
    data = request.get_json(silent=True) or {}
    ebr_id = data.get("ebr_id")
    variant_id = data.get("variant_id") or data.get("template_name")
    extra_fields = data.get("extra_fields", {})

    if not ebr_id or not variant_id:
        return jsonify({"ok": False, "error": "Missing ebr_id or variant_id"}), 400

    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        if not ebr:
            return jsonify({"ok": False, "error": "EBR not found"}), 404
        if ebr.get("typ") not in ("zbiornik", "platkowanie"):
            return jsonify({"ok": False, "error": "Świadectwa tylko dla zbiorników i płatkowania"}), 400

        # Resolve target_produkt (defaults to ebr.produkt for backward compat)
        requested_target = data.get("target_produkt") or ebr["produkt"]
        if requested_target != ebr["produkt"]:
            from mbr.certs.generator import get_cert_aliases
            if requested_target not in get_cert_aliases(db, ebr["produkt"]):
                return jsonify({"ok": False,
                                "error": f"no cert alias configured: "
                                         f"{ebr['produkt']}→{requested_target}"}), 400
        target_produkt = requested_target

        wyniki = get_ebr_wyniki(db, ebr_id)
        wyniki_flat = {}
        for sekcja_data in wyniki.values():
            for kod, row in sekcja_data.items():
                wyniki_flat[kod] = row

        # Resolve wystawil — prefer explicit from request, fallback to shift/session
        wystawil = (data.get("wystawil") or "").strip()
        if not wystawil:
            shift_ids = session.get("shift_workers", [])
            if shift_ids:
                workers = []
                for wid in shift_ids:
                    w = db.execute("SELECT imie, nazwisko FROM workers WHERE id=?", (wid,)).fetchone()
                    if w:
                        workers.append(w["imie"] + " " + w["nazwisko"])
                wystawil = ", ".join(workers) if workers else session["user"]["login"]
            else:
                wystawil = session["user"]["login"]

        # Find variant label for filename — look up in target_produkt's variants
        variants = get_variants(target_produkt)
        variant_label = variant_id
        for v in variants:
            if v["id"] == variant_id:
                variant_label = v["label"]
                break

        try:
            pdf_bytes = generate_certificate_pdf(
                target_produkt, variant_id, ebr["nr_partii"],
                ebr.get("dt_start"), wyniki_flat, extra_fields,
                wystawil=wystawil,
            )
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

        # Save generation data to archive (for regeneration)
        import json as _json
        generation_data = {
            "produkt": ebr["produkt"],
            "target_produkt": target_produkt,
            "variant_id": variant_id,
            "variant_label": variant_label,
            "nr_partii": ebr["nr_partii"],
            "dt_start": ebr.get("dt_start"),
            "wyniki_flat": {k: {"wartosc": v.get("wartosc"), "w_limicie": v.get("w_limicie")} for k, v in wyniki_flat.items()},
            "extra_fields": extra_fields,
            "wystawil": wystawil,
        }
        save_certificate_data(target_produkt, variant_label, ebr["nr_partii"], generation_data)

        # Persist target_produkt ONLY when it differs from ebr.produkt — NULL otherwise
        persist_target = target_produkt if target_produkt != ebr["produkt"] else None
        cert_id = create_swiadectwo(
            db, ebr_id, variant_label, ebr["nr_partii"], "regenerate", wystawil,
            data_json=_json.dumps(generation_data, ensure_ascii=False),
            target_produkt=persist_target,
        )
        db.commit()

    # Return PDF as download
    nr_only = ebr['nr_partii'].split('/')[0].strip()
    filename = f"{variant_label} {nr_only}.pdf"
    # Content-Disposition filename must be ASCII-safe (HTTP latin-1 limit)
    import unicodedata
    fn_safe = filename.replace('\u2014', '-').replace('\u2013', '-')
    filename_ascii = unicodedata.normalize('NFKD', fn_safe).encode('ascii', 'ignore').decode('ascii')
    from urllib.parse import quote
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename_ascii}\"; filename*=UTF-8''{quote(filename)}",
            "X-Cert-Id": str(cert_id),
        },
    )
```

Substantive changes vs. original:
1. Resolve `target_produkt` from body, default to `ebr["produkt"]`.
2. When they differ, validate via `get_cert_aliases`; 400 on mismatch.
3. Pass `target_produkt` (not `ebr["produkt"]`) to `generate_certificate_pdf` + `save_certificate_data` + `get_variants` (for label lookup).
4. Pass `target_produkt=persist_target` to `create_swiadectwo` (NULL when unchanged from ebr.produkt for backward compat).
5. `generation_data` dict gains a `target_produkt` key for regen fidelity.

- [ ] **Step 5: Run — confirm PASS**

Run: `pytest tests/test_cert_generate_with_alias.py -v`
Expected: all 4 pass.

- [ ] **Step 6: Full suite**

Run: `pytest -q`
Expected: `819 passed, 19 skipped` (815 + 4 new).

- [ ] **Step 7: Commit**

```bash
git add mbr/certs/routes.py mbr/certs/models.py tests/test_cert_generate_with_alias.py
git commit -m "$(cat <<'EOF'
feat(certs): /api/cert/generate routes by target_produkt when aliased

api_cert_generate reads optional target_produkt from body. If different
from ebr.produkt, validates via cert_alias. PDF generator, variant label
lookup, archive JSON, and swiadectwa row all receive target_produkt
instead of ebr.produkt for aliased certs. Unchanged behavior when
target is omitted or equals ebr.produkt. swiadectwa.target_produkt
stores NULL for non-aliased rows to preserve backward compatibility
with archive listings that don't know about the column yet.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Admin alias CRUD endpoints

**Files:**
- Modify: `mbr/certs/routes.py` (add three new endpoints, adjacent to existing `/api/cert/config/*` routes)
- Create test: `tests/test_cert_alias_api.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cert_alias_api.py`:

```python
"""Admin CRUD for cert_alias: GET / POST / DELETE /api/cert/aliases."""

import sqlite3
import pytest
from contextlib import contextmanager

from mbr.models import init_mbr_tables


def _seed(db):
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('K40GLOL', 'K40GLOL')")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('GLOL40', 'GLOL40')")
    db.commit()


def _make_client(monkeypatch, db, rola="admin"):
    import mbr.db
    import mbr.certs.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.certs.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = {"login": "tester", "rola": rola, "worker_id": None}
    return c


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    _seed(conn)
    yield conn
    conn.close()


@pytest.fixture
def admin_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="admin")


@pytest.fixture
def lab_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="lab")


def test_post_alias_persists(admin_client, db):
    r = admin_client.post("/api/cert/aliases", json={
        "source_produkt": "K40GLOL", "target_produkt": "GLOL40",
    })
    assert r.status_code == 200, r.get_json()
    row = db.execute(
        "SELECT * FROM cert_alias WHERE source_produkt='K40GLOL' AND target_produkt='GLOL40'"
    ).fetchone()
    assert row is not None


def test_post_alias_rejects_self(admin_client):
    r = admin_client.post("/api/cert/aliases", json={
        "source_produkt": "K40GLOL", "target_produkt": "K40GLOL",
    })
    assert r.status_code == 400
    assert "self" in (r.get_json().get("error") or "").lower()


def test_post_alias_rejects_unknown_target(admin_client):
    r = admin_client.post("/api/cert/aliases", json={
        "source_produkt": "K40GLOL", "target_produkt": "NONEXISTENT",
    })
    assert r.status_code == 404
    assert "target" in (r.get_json().get("error") or "").lower()


def test_post_alias_duplicate_is_idempotent(admin_client, db):
    admin_client.post("/api/cert/aliases", json={
        "source_produkt": "K40GLOL", "target_produkt": "GLOL40",
    })
    r = admin_client.post("/api/cert/aliases", json={
        "source_produkt": "K40GLOL", "target_produkt": "GLOL40",
    })
    assert r.status_code == 200
    count = db.execute(
        "SELECT COUNT(*) FROM cert_alias WHERE source_produkt='K40GLOL' AND target_produkt='GLOL40'"
    ).fetchone()[0]
    assert count == 1


def test_get_aliases_returns_all(admin_client, db):
    db.execute("INSERT INTO cert_alias VALUES ('K40GLOL', 'GLOL40')")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('K7', 'K7')")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('K7B', 'K7B')")
    db.execute("INSERT INTO cert_alias VALUES ('K7', 'K7B')")
    db.commit()
    r = admin_client.get("/api/cert/aliases")
    data = r.get_json()
    pairs = sorted((a["source_produkt"], a["target_produkt"]) for a in data["aliases"])
    assert pairs == [("K40GLOL", "GLOL40"), ("K7", "K7B")]


def test_delete_alias_removes(admin_client, db):
    db.execute("INSERT INTO cert_alias VALUES ('K40GLOL', 'GLOL40')")
    db.commit()
    r = admin_client.delete("/api/cert/aliases/K40GLOL/GLOL40")
    assert r.status_code == 200
    row = db.execute(
        "SELECT * FROM cert_alias WHERE source_produkt='K40GLOL'"
    ).fetchone()
    assert row is None


def test_delete_nonexistent_alias_is_idempotent(admin_client):
    r = admin_client.delete("/api/cert/aliases/K40GLOL/GLOL40")
    assert r.status_code == 200


def test_post_alias_requires_admin(lab_client):
    r = lab_client.post("/api/cert/aliases", json={
        "source_produkt": "K40GLOL", "target_produkt": "GLOL40",
    })
    assert r.status_code == 403
```

- [ ] **Step 2: Run — confirm FAIL**

Run: `pytest tests/test_cert_alias_api.py -v`
Expected: all 8 fail with 404 Not Found on the route (endpoints don't exist yet).

- [ ] **Step 3: Add the three endpoints**

In `mbr/certs/routes.py`, immediately after the existing `/api/cert/config/products` route (around line 226), insert:

```python
# ---------------------------------------------------------------------------
# Cert alias CRUD (admin only)
# ---------------------------------------------------------------------------


@certs_bp.route("/api/cert/aliases", methods=["GET"])
@role_required("admin")
def api_cert_aliases_list():
    """List all cert-alias pairs."""
    with db_session() as db:
        rows = db.execute(
            "SELECT source_produkt, target_produkt FROM cert_alias "
            "ORDER BY source_produkt, target_produkt"
        ).fetchall()
    return jsonify({"aliases": [dict(r) for r in rows]})


@certs_bp.route("/api/cert/aliases", methods=["POST"])
@role_required("admin")
def api_cert_aliases_create():
    """Create a cert alias. Idempotent (INSERT OR IGNORE)."""
    data = request.get_json(silent=True) or {}
    source = (data.get("source_produkt") or "").strip()
    target = (data.get("target_produkt") or "").strip()
    if not source or not target:
        return jsonify({"error": "source_produkt and target_produkt required"}), 400
    if source == target:
        return jsonify({"error": "self-alias not allowed"}), 400
    with db_session() as db:
        target_row = db.execute(
            "SELECT 1 FROM produkty WHERE nazwa=?", (target,)
        ).fetchone()
        if not target_row:
            return jsonify({"error": f"target produkt not found: {target}"}), 404
        db.execute(
            "INSERT OR IGNORE INTO cert_alias (source_produkt, target_produkt) VALUES (?, ?)",
            (source, target),
        )
        db.commit()
    return jsonify({"ok": True})


@certs_bp.route("/api/cert/aliases/<source_produkt>/<target_produkt>", methods=["DELETE"])
@role_required("admin")
def api_cert_aliases_delete(source_produkt, target_produkt):
    """Delete a cert alias. Idempotent (no error if the row didn't exist)."""
    with db_session() as db:
        db.execute(
            "DELETE FROM cert_alias WHERE source_produkt=? AND target_produkt=?",
            (source_produkt, target_produkt),
        )
        db.commit()
    return jsonify({"ok": True})
```

- [ ] **Step 4: Run — confirm PASS**

Run: `pytest tests/test_cert_alias_api.py -v`
Expected: all 8 pass.

- [ ] **Step 5: Full suite**

Run: `pytest -q`
Expected: `827 passed, 19 skipped` (819 + 8 new).

- [ ] **Step 6: Commit**

```bash
git add mbr/certs/routes.py tests/test_cert_alias_api.py
git commit -m "$(cat <<'EOF'
feat(certs): admin CRUD for cert aliases

Three endpoints under /api/cert/aliases, admin-only:
- GET      → list all pairs
- POST     → create (idempotent via INSERT OR IGNORE; 400 self-alias,
             404 target not in produkty)
- DELETE   → remove (idempotent — no error if missing)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Frontend — cert picker forwards `target_produkt`

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html` (~lines 1940-2157)

**Note:** JS-only. No automated test; verify backend suite stays green.

- [ ] **Step 1: Modify `issueCert` signature + `doGenerateCert` payload**

Current `loadCompletedCerts` emits each template row as:

```javascript
html += '<div class="cv-row cv-row-tmpl">' +
    '<div class="cv-row-dot tmpl"></div>' +
    '<span class="cv-row-name">' + t.display + '</span>' +
    '<button class="cv-row-btn-issue" onclick=\'issueCert(this,"' + t.filename.replace(/"/g, '\\"') + '",' + rf + ')\'>+ Wystaw</button>' +
'</div>';
```

`t.owner_produkt` is now in the API response (Task 3). Pass it through.

Edit `mbr/templates/laborant/_fast_entry_content.html`:

Replace the block above (around lines 1991-1998) with:

```javascript
        tmplData.templates.forEach(function(t) {
            var rf = JSON.stringify(t.required_fields || []);
            var ownerEsc = (t.owner_produkt || '').replace(/"/g, '\\"');
            html += '<div class="cv-row cv-row-tmpl">' +
                '<div class="cv-row-dot tmpl"></div>' +
                '<span class="cv-row-name">' + t.display + '</span>' +
                '<button class="cv-row-btn-issue" onclick=\'issueCert(this,"' + t.filename.replace(/"/g, '\\"') + '","' + ownerEsc + '",' + rf + ')\'>+ Wystaw</button>' +
            '</div>';
        });
```

Then update `issueCert` (~line 2062) to accept + pass the extra argument. Replace:

```javascript
var _pendingCert = {btn: null, variantId: null};

function issueCert(btn, variantId, requiredFields) {
    if (!requiredFields || requiredFields.length === 0) {
        doGenerateCert(btn, variantId, {});
        return;
    }
    _pendingCert = {btn: btn, variantId: variantId};
```

with:

```javascript
var _pendingCert = {btn: null, variantId: null, targetProdukt: null};

function issueCert(btn, variantId, targetProdukt, requiredFields) {
    if (!requiredFields || requiredFields.length === 0) {
        doGenerateCert(btn, variantId, targetProdukt, {});
        return;
    }
    _pendingCert = {btn: btn, variantId: variantId, targetProdukt: targetProdukt};
```

Update `confirmCertPopup` (~line 2095) to pass it through. Replace:

```javascript
    // Save refs before closing (closeCertPopup resets _pendingCert)
    var btn = _pendingCert.btn;
    var variantId = _pendingCert.variantId;
    closeCertPopup();
    doGenerateCert(btn, variantId, extra);
```

with:

```javascript
    // Save refs before closing (closeCertPopup resets _pendingCert)
    var btn = _pendingCert.btn;
    var variantId = _pendingCert.variantId;
    var targetProdukt = _pendingCert.targetProdukt;
    closeCertPopup();
    doGenerateCert(btn, variantId, targetProdukt, extra);
```

Update `closeCertPopup` to clear the new field too. Replace:

```javascript
function closeCertPopup() {
    document.getElementById('cv-popup-overlay').classList.remove('active');
    _pendingCert = {btn: null, variantId: null};
}
```

with:

```javascript
function closeCertPopup() {
    document.getElementById('cv-popup-overlay').classList.remove('active');
    _pendingCert = {btn: null, variantId: null, targetProdukt: null};
}
```

Update `doGenerateCert` signature + payload (~line 2114). Replace:

```javascript
var _certGenerating = false;
async function doGenerateCert(btn, variantId, extraFields) {
    if (_certGenerating) return;
    _certGenerating = true;
    btn.disabled = true;
    btn.style.opacity = '0.5';
    btn.innerHTML = '<span>Generowanie...</span>';
    try {
        var resp = await fetch('/api/cert/generate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ebr_id: ebrId, variant_id: variantId, extra_fields: extraFields, wystawil: (document.getElementById('cv-issuer-select') || {}).value || ''})
        });
```

with:

```javascript
var _certGenerating = false;
async function doGenerateCert(btn, variantId, targetProdukt, extraFields) {
    if (_certGenerating) return;
    _certGenerating = true;
    btn.disabled = true;
    btn.style.opacity = '0.5';
    btn.innerHTML = '<span>Generowanie...</span>';
    try {
        var resp = await fetch('/api/cert/generate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                ebr_id: ebrId,
                variant_id: variantId,
                target_produkt: targetProdukt || null,
                extra_fields: extraFields,
                wystawil: (document.getElementById('cv-issuer-select') || {}).value || ''
            })
        });
```

- [ ] **Step 2: Sanity check — Jinja parses**

```bash
python3 -c "import jinja2; jinja2.Environment().parse(open('mbr/templates/laborant/_fast_entry_content.html').read())"
```

Expected: no output, exit 0.

- [ ] **Step 3: Full suite (no regressions)**

Run: `pytest -q`
Expected: `827 passed, 19 skipped` — unchanged (backend untouched).

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "$(cat <<'EOF'
feat(certs): cert picker forwards owner_produkt as target_produkt

issueCert/doGenerateCert accept targetProdukt threaded through from the
template.owner_produkt field the API now returns. POST body includes
target_produkt (or null for own-product certs). _pendingCert state
carries it across the required-fields popup round-trip.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Admin UI — "Aliasy cert" panel in `/admin/wzory-cert`

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html`

**Note:** JS/HTML only. Manual smoke + backend suite unchanged.

- [ ] **Step 1: Locate insertion point**

Run:
```bash
grep -n 'wc-page\|wc-list-head\|wc-grid-cards' mbr/templates/admin/wzory_cert.html | head -10
```

Find the main `<div class="wc-page">` body where the product grid is rendered. We'll add a new panel below it.

Also run:
```bash
grep -n 'api/cert/config/products\|loadProducts\|renderProductGrid' mbr/templates/admin/wzory_cert.html | head -10
```

Take notes on:
- The JS function name that loads `/api/cert/config/products` (we'll reuse its output for the alias source/target dropdowns).
- Where the DOM ready / init happens.

- [ ] **Step 2: Add the alias panel HTML**

Inside the `{% block content %}` (or equivalent main block — identify from the grep above), at the bottom of the page content, insert:

```html
<!-- Cert alias panel -->
<div class="wc-alias-panel" style="margin-top:28px;border-top:1px solid var(--border);padding-top:20px;">
  <div class="wc-title" style="margin-bottom:12px;">Aliasy cert</div>
  <div style="color:var(--text-sec);font-size:12px;margin-bottom:10px;">
    Gdy produkt „źródłowy" ma wpisany alias do produktu „docelowego",
    jego szarże mogą wystawiać świadectwa z wariantami produktu docelowego.
  </div>

  <div class="wc-alias-add" style="display:flex;gap:8px;align-items:center;margin-bottom:14px;">
    <select id="wc-alias-src" style="padding:6px 10px;border:1px solid var(--border);border-radius:5px;min-width:200px;"></select>
    <span style="color:var(--text-sec);">→</span>
    <select id="wc-alias-tgt" style="padding:6px 10px;border:1px solid var(--border);border-radius:5px;min-width:200px;"></select>
    <button id="wc-alias-add-btn" style="padding:6px 14px;background:var(--teal);color:#fff;border:none;border-radius:5px;cursor:pointer;">Dodaj</button>
  </div>

  <div id="wc-alias-list" style="border:1px solid var(--border);border-radius:6px;background:var(--surface);"></div>
</div>
```

- [ ] **Step 3: Add the JS loader**

Find the existing script block (look for `async function loadProducts` or similar). After the existing `loadProducts`-equivalent, add these two functions:

```javascript
async function wcAliasLoad() {
    var [aliasResp, prodResp] = await Promise.all([
        fetch('/api/cert/aliases'),
        fetch('/api/cert/config/products'),
    ]);
    var aliasData = await aliasResp.json();
    var prodData = await prodResp.json();

    // Populate dropdowns from the product list
    var prods = prodData.products || [];
    var optsHtml = '<option value="">—</option>' +
        prods.map(function(p) {
            return '<option value="' + p.key + '">' +
                (p.display_name || p.key).replace(/&/g, '&amp;').replace(/</g, '&lt;') +
                '</option>';
        }).join('');
    document.getElementById('wc-alias-src').innerHTML = optsHtml;
    document.getElementById('wc-alias-tgt').innerHTML = optsHtml;

    // Render alias list
    var list = aliasData.aliases || [];
    var listEl = document.getElementById('wc-alias-list');
    if (!list.length) {
        listEl.innerHTML = '<div style="padding:14px;color:var(--text-dim);font-size:12px;">Brak aliasów.</div>';
        return;
    }
    var rowsHtml = list.map(function(a) {
        return '<div style="display:flex;align-items:center;padding:8px 12px;border-bottom:1px solid var(--border);font-size:12px;">' +
            '<span style="flex:1;"><b>' + (a.source_produkt || '').replace(/</g, '&lt;') + '</b>' +
            ' <span style="color:var(--text-sec);">→</span> ' +
            '<b>' + (a.target_produkt || '').replace(/</g, '&lt;') + '</b></span>' +
            '<button class="wc-alias-del" data-src="' + (a.source_produkt || '').replace(/"/g, '&quot;') +
            '" data-tgt="' + (a.target_produkt || '').replace(/"/g, '&quot;') +
            '" style="padding:4px 10px;background:var(--red);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:11px;">Usuń</button>' +
            '</div>';
    }).join('');
    listEl.innerHTML = rowsHtml;
    // Attach delete handlers
    listEl.querySelectorAll('.wc-alias-del').forEach(function(btn) {
        btn.addEventListener('click', async function() {
            var src = btn.dataset.src;
            var tgt = btn.dataset.tgt;
            if (!confirm('Usunąć alias ' + src + ' → ' + tgt + '?')) return;
            await fetch('/api/cert/aliases/' + encodeURIComponent(src) + '/' + encodeURIComponent(tgt), {method: 'DELETE'});
            wcAliasLoad();
        });
    });
}

async function wcAliasAdd() {
    var src = document.getElementById('wc-alias-src').value;
    var tgt = document.getElementById('wc-alias-tgt').value;
    if (!src || !tgt) { alert('Wybierz oba produkty'); return; }
    if (src === tgt) { alert('Source i target muszą być różne'); return; }
    var resp = await fetch('/api/cert/aliases', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({source_produkt: src, target_produkt: tgt}),
    });
    if (!resp.ok) {
        var body = await resp.json().catch(function() { return {}; });
        alert('Błąd: ' + (body.error || resp.status));
        return;
    }
    document.getElementById('wc-alias-src').value = '';
    document.getElementById('wc-alias-tgt').value = '';
    wcAliasLoad();
}

document.getElementById('wc-alias-add-btn').addEventListener('click', wcAliasAdd);
wcAliasLoad();
```

Place the three statements (`document.getElementById('wc-alias-add-btn').addEventListener(...)`, and the initial `wcAliasLoad()` call) at the BOTTOM of the existing IIFE or script block — alongside the existing initial `loadProducts()`-style call. This guarantees the DOM is ready.

- [ ] **Step 4: Sanity checks**

```bash
python3 -c "import jinja2; jinja2.Environment().parse(open('mbr/templates/admin/wzory_cert.html').read())"
```

Expected: no output.

```bash
grep -c wcAliasLoad mbr/templates/admin/wzory_cert.html
```

Expected: `3` (one declaration + one internal call + one init call).

- [ ] **Step 5: Full suite (no regressions)**

Run: `pytest -q`
Expected: `827 passed, 19 skipped` — unchanged.

- [ ] **Step 6: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "$(cat <<'EOF'
feat(certs): admin UI — cert alias panel in /admin/wzory-cert

Panel below the product grid. Two dropdowns (source/target) populated
from /api/cert/config/products + Dodaj button. List of existing aliases
with Usuń buttons. No new CSS classes — uses existing wc-title and
inline styles tied to CSS variables.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Final regression sweep

**Files:** n/a (verification only).

- [ ] **Step 1: Full test suite**

```bash
pytest -q
```
Expected: `827 passed, 19 skipped` (805 baseline + 22 new tests from Tasks 1, 2, 3, 4, 5).

- [ ] **Step 2: Branch log**

```bash
git log --oneline main..HEAD
```

Expected: 8 commits (Task 0 has no commit; Tasks 1–7 each one; Task 8 no commit):

```
<sha> feat(certs): admin UI — cert alias panel in /admin/wzory-cert
<sha> feat(certs): cert picker forwards owner_produkt as target_produkt
<sha> feat(certs): admin CRUD for cert aliases
<sha> feat(certs): /api/cert/generate routes by target_produkt when aliased
<sha> feat(certs): /api/cert/templates unions own + aliased variants
<sha> feat(certs): get_cert_aliases helper
<sha> feat(certs): cert_alias table + swiadectwa.target_produkt column
```

- [ ] **Step 3: Manual smoke (not automated — documented steps)**

Start server:
```bash
python -m mbr.app &
SERVER_PID=$!
sleep 2
```

As admin at `http://localhost:5001/admin/wzory-cert`:
1. Scroll to "Aliasy cert" panel.
2. Pick source `Chegina_K40GLOL`, target `Chegina_GLOL40`, click Dodaj.
3. Confirm the pair appears in the list.

DB inspect:
```bash
sqlite3 data/batch_db.sqlite "SELECT * FROM cert_alias;"
```
Expected row: `Chegina_K40GLOL|Chegina_GLOL40`.

As any laborant:
4. Open any completed K40GLOL szarża.
5. In the cert picker, verify you now see K40GLOL variants + GLOL40 variants (total should be 9: 5 K40GLOL + 4 GLOL40).
6. Click "+ Wystaw" on `Chegina GLOL40 — MB`.
7. Confirm PDF downloads with GLOL40 branding but K40GLOL batch's nr_partii.

DB inspect:
```bash
sqlite3 data/batch_db.sqlite "SELECT id, template_name, nr_partii, target_produkt FROM swiadectwa ORDER BY id DESC LIMIT 3;"
```
Expected: the newest row has `target_produkt='Chegina_GLOL40'` and template_name is the GLOL40 variant label.

As admin:
8. Delete the alias via the Usuń button.
9. Reload a K40GLOL szarża → picker now shows only 5 K40GLOL variants.

Kill server:
```bash
kill $SERVER_PID
```

- [ ] **Step 4: Leave the branch ready — no push**

No commits in this task. Branch `feat/cert-alias` is ready for the user to choose merge/PR/keep via `superpowers:finishing-a-development-branch`.

---

## Self-Review

**Spec coverage:**
- Schema `cert_alias` + `swiadectwa.target_produkt` (spec §Components 1, 5) → Task 1 ✓
- Helper `get_cert_aliases` (implied by spec §Components 2, 4) → Task 2 ✓
- Variant picker union (spec §Components 3) → Task 3 ✓
- `api_cert_generate` with target_produkt (spec §Components 4) → Task 4 ✓
- Admin CRUD endpoints (spec §Components 2) → Task 5 ✓
- Frontend forwarding (spec §Components 6) → Task 6 ✓
- Admin UI panel (spec §Components 7) → Task 7 ✓
- Error handling table (spec §Error handling) — each row mapped to a test assertion in Tasks 4–5
- Archive (spec §Components 5) — covered by Task 1 schema + Task 4 wiring

All spec sections covered.

**Placeholder scan:** No TBD / TODO / "add validation" / "similar to Task N" strings. Each step shows exact code or exact command.

**Type consistency:**
- `cert_alias` columns: `source_produkt`, `target_produkt` — consistent across Tasks 1, 2, 4, 5, 7.
- `get_cert_aliases(db, source_produkt) → list[str]` — consistent call shape across Tasks 3, 4.
- `get_variants()` now returns dicts with `owner_produkt` — Task 3 defines, Task 3 consumes (api_cert_templates), Task 4 consumes (label lookup).
- `create_swiadectwo(..., target_produkt=None)` — Task 4 defines, Task 4 consumes.
- `swiadectwa.target_produkt` — Task 1 creates, Task 4 writes, Task 8 smoke reads.
- POST body field `target_produkt` — Task 4 reads, Task 6 sends, Task 7 admin UI uses `source_produkt`/`target_produkt` in its own body (aliases CRUD, separate path).
- Frontend function signatures: `issueCert(btn, variantId, targetProdukt, requiredFields)` + `doGenerateCert(btn, variantId, targetProdukt, extraFields)` — consistent across caller/callee in Task 6.

**Risk of breaking existing tests (805 baseline):**
- Task 1 adds a table + column. Existing schema tests that enumerate tables/columns may be surprised — check: the only such tests are in `test_db.py` and our new migration tests. Verified earlier DB audits don't hard-code table list.
- Task 3 modifies `get_variants` return shape. Existing callers: `api_cert_generate` (updated in Task 4), `api_cert_templates` (updated in Task 3), tests in `test_certs.py`. If any existing cert test inspects the dict returned by `get_variants` and fails on the new key, the added `owner_produkt` is additive — `.get("id")` / `.get("label")` keep working. `.keys()` would break but nothing checks that.
- Task 4 changes `create_swiadectwo` signature (adds kwarg with default). All existing callers keep working because of the default.
- Task 6 JS changes are isolated to cert picker flow; no automated tests depend on it.
- Task 7 adds a new admin panel; no existing tests touch the template.
- Risk overall: LOW.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-19-cert-alias.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, spec + code-quality review between tasks. 7 tasks + 1 verification → ~1.5–2 hours.
2. **Inline Execution** — tasks in this session via `superpowers:executing-plans`, checkpoints every 2–3 tasks.

Which approach?
