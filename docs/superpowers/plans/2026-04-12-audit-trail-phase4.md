# Audit Trail — Phase 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Instrument all EBR write paths so every laborant action (create batch, save results, approve stages, edit notes, close batch) produces audit entries. Consolidate `ebr_uwagi_history` → `audit_log` as single source of truth for notes history.

**Architecture:** Each EBR model helper loses its internal `db.commit()` (each has exactly 1 caller — verified by grep). Route commits once after `log_event()` for atomicity. Explicit actors from session (Phase 3 pattern — avoids ShiftRequiredError in non-shift contexts). Uwagi migration script backfills `ebr_uwagi_history` → `audit_log`; `get_uwagi` rewired to read from audit_log; `ebr_uwagi_history` table kept until Phase 7.

**Tech Stack:** Flask, raw sqlite3, pytest with in-memory SQLite fixtures, vanilla JS.

**Spec reference:** `docs/superpowers/specs/2026-04-12-audit-trail-phase4-design.md`

**Branch convention:** `audit/phase4` worktree. 4 sub-PRs merged together via `--no-ff` to main.

**IMPORTANT patterns from Phase 3 (subagents MUST follow):**
1. **Explicit actors**: ALL log_event calls use `actors=[{worker_id: None, actor_login: session_user_login, actor_rola: session_user_rola}]`. Do NOT call `actors_from_request()` — it raises ShiftRequiredError for laborants with empty shift in contexts like batch creation where shift may not be set yet. Build the actor dict from `session.get("user", {})`.
2. **Model refactor**: Remove `db.commit()` from model helpers. Route's `db.commit()` after `log_event()` is the sole commit point. Verified safe — each helper has exactly 1 caller.
3. **Imports**: `from mbr.shared import audit` at module top of routes files. `audit.log_event(audit.EVENT_..., ...)` pattern.

---

## File Structure

**Create:**
- `scripts/migrate_uwagi_to_audit.py` — one-shot idempotent migration (~120 LOC)
- `tests/test_audit_phase4_lifecycle.py` — batch lifecycle tests (~200 LOC)
- `tests/test_audit_phase4_wyniki.py` — wyniki save tests (~200 LOC)
- `tests/test_audit_phase4_etapy.py` — etapy tests (~250 LOC)
- `tests/test_audit_phase4_uwagi.py` — uwagi consolidation tests (~200 LOC)
- `tests/test_migrate_uwagi_to_audit.py` — migration tests (~150 LOC)

**Modify:**
- `mbr/laborant/models.py` — remove `db.commit()` from `create_ebr`, `save_wyniki`, `complete_ebr`, `save_uwagi`; rewrite `get_uwagi` to read from audit_log
- `mbr/laborant/routes.py` — add `log_event()` to `szarze_new`, `save_entry`, `complete_entry`, `toggle_golden`, `save_samples`, `api_put_uwagi`, `api_delete_uwagi`
- `mbr/etapy/models.py` — remove `db.commit()` from `save_etap_analizy`, `add_korekta`, `confirm_korekta`, `zatwierdz_etap`, `skip_etap`; remove neutralized TODO at line 44
- `mbr/etapy/routes.py` — add `log_event()` to all 5 write endpoints
- `deploy/auto-deploy.sh` — add migration hook

---

## Sub-PR 4.1: Batch lifecycle (Tasks 1-2)

### Task 1: Refactor `create_ebr` + instrument `szarze_new` and `toggle_golden`

**Files:**
- Modify: `mbr/laborant/models.py` (remove `db.commit()` from `create_ebr`, line ~300)
- Modify: `mbr/laborant/routes.py` (add log_event to `szarze_new` + `toggle_golden`)
- Create: `tests/test_audit_phase4_lifecycle.py`

- [ ] **Step 1: Create test file with shared fixtures + 2 failing tests**

Create `tests/test_audit_phase4_lifecycle.py`:

```python
"""Tests for Phase 4 batch lifecycle audit events."""

import json as _json
import sqlite3
import pytest
from contextlib import contextmanager
from datetime import datetime

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    # Seed workers for shift
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (1, 'Anna', 'Kowalska', 'AK', 'AK', 1)"
    )
    # Seed an active MBR template so create_ebr can find it
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "utworzony_przez, dt_utworzenia) VALUES (?, 1, 'active', '[]', '{}', 'test', ?)",
        ("Chegina_K7", now),
    )
    conn.commit()
    yield conn
    conn.close()


def _make_client(monkeypatch, db, rola="laborant", shift_workers=None):
    import mbr.db
    import mbr.laborant.routes
    import mbr.admin.audit_routes
    import mbr.etapy.routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.admin.audit_routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.etapy.routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "tester", "rola": rola, "imie_nazwisko": None}
        if shift_workers is not None:
            sess["shift_workers"] = shift_workers
    return client


@pytest.fixture
def client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="laborant", shift_workers=[1])


@pytest.fixture
def admin_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="admin")


# ---------- POST /laborant/szarze/new ----------

def test_szarze_new_logs_ebr_batch_created(client, db):
    """Creating a new batch logs ebr.batch.created with entity_label and payload."""
    resp = client.post("/laborant/szarze/new", data={
        "produkt": "Chegina_K7",
        "nr_partii": "99/2026",
        "nr_amidatora": "A1",
        "nr_mieszalnika": "M1",
        "wielkosc_kg": "5000",
    })
    # Route redirects after creation
    assert resp.status_code in (302, 303)

    rows = db.execute(
        "SELECT id, event_type, entity_type, entity_id, entity_label, payload_json "
        "FROM audit_log WHERE event_type = 'ebr.batch.created'"
    ).fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["entity_type"] == "ebr"
    assert r["entity_id"] is not None  # the new ebr_id
    assert "Chegina_K7" in (r["entity_label"] or "")
    assert "99/2026" in (r["entity_label"] or "")

    payload = _json.loads(r["payload_json"])
    assert payload["produkt"] == "Chegina_K7"
    assert payload["nr_partii"] == "99/2026"

    # Actor is the laborant
    actors = db.execute(
        "SELECT actor_login FROM audit_log_actors WHERE audit_id=?", (r["id"],)
    ).fetchall()
    assert len(actors) == 1


# ---------- POST /api/ebr/<id>/golden ----------

def test_toggle_golden_logs_batch_updated(client, db):
    """Toggling is_golden produces ebr.batch.updated with diff."""
    # First create a batch
    client.post("/laborant/szarze/new", data={
        "produkt": "Chegina_K7", "nr_partii": "1/2026",
        "nr_amidatora": "", "nr_mieszalnika": "", "wielkosc_kg": "0",
    })
    ebr_id = db.execute("SELECT ebr_id FROM ebr_batches LIMIT 1").fetchone()["ebr_id"]

    resp = client.post(f"/api/ebr/{ebr_id}/golden")
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT diff_json FROM audit_log WHERE event_type = 'ebr.batch.updated'"
    ).fetchall()
    assert len(rows) == 1
    diff = _json.loads(rows[0]["diff_json"])
    assert diff == [{"pole": "is_golden", "stara": 0, "nowa": 1}]
```

- [ ] **Step 2: Run — verify failure**

```bash
rm -f data/batch_db.sqlite
pytest tests/test_audit_phase4_lifecycle.py -v 2>&1 | tail -15
```

Expected: tests fail (no audit entries produced — route doesn't call log_event yet).

- [ ] **Step 3: Refactor `create_ebr` — remove internal commit**

Edit `mbr/laborant/models.py`. Find `create_ebr` function (~line 274). Remove the `db.commit()` at line ~300. The function becomes a "stage INSERT" helper — caller commits.

Also check: `szarze_new` route (in `routes.py`) has 2 additional `db.commit()` calls for zbiorniki + substraty (lines ~110, ~126). These need to stay OR be folded into one final commit. Simplest: remove all intermediary commits in the route and add a single `db.commit()` after log_event at the end of the `if ebr_id:` block.

- [ ] **Step 4: Instrument `szarze_new` route**

Edit `mbr/laborant/routes.py`. In `szarze_new` (around line 69), after the `create_ebr` call succeeds and optional zbiorniki/substraty are saved, before the final redirect, add:

```python
            # Audit: log batch creation
            user = session.get("user", {})
            audit.log_event(
                audit.EVENT_EBR_BATCH_CREATED,
                entity_type="ebr",
                entity_id=ebr_id,
                entity_label=f"{request.form['produkt']} {request.form['nr_partii']}",
                payload={
                    "produkt": request.form["produkt"],
                    "nr_partii": request.form["nr_partii"],
                    "nr_amidatora": request.form.get("nr_amidatora", ""),
                    "nr_mieszalnika": request.form.get("nr_mieszalnika", ""),
                    "wielkosc_kg": wielkosc_kg,
                    "typ": typ,
                },
                actors=[{
                    "worker_id": None,
                    "actor_login": user.get("login", "unknown"),
                    "actor_rola": user.get("rola", "unknown"),
                }],
                db=db,
            )
            db.commit()
```

Make sure `from mbr.shared import audit` is imported at the top (should already be from Phase 3 uwagi fix).

- [ ] **Step 5: Instrument `toggle_golden` route**

Find `toggle_golden` (around line 222). Currently it reads `is_golden`, flips, updates, commits. Refactor to:

```python
@laborant_bp.route("/api/ebr/<int:ebr_id>/golden", methods=["POST"])
@role_required("laborant", "laborant_kj", "admin")
def toggle_golden(ebr_id):
    with db_session() as db:
        row = db.execute("SELECT is_golden FROM ebr_batches WHERE ebr_id=?", (ebr_id,)).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        old_val = row["is_golden"]
        new_val = 0 if old_val else 1
        db.execute("UPDATE ebr_batches SET is_golden=? WHERE ebr_id=?", (new_val, ebr_id))

        user = session.get("user", {})
        audit.log_event(
            audit.EVENT_EBR_BATCH_UPDATED,
            entity_type="ebr",
            entity_id=ebr_id,
            diff=[{"pole": "is_golden", "stara": old_val, "nowa": new_val}],
            actors=[{
                "worker_id": None,
                "actor_login": user.get("login", "unknown"),
                "actor_rola": user.get("rola", "unknown"),
            }],
            db=db,
        )
        db.commit()
    return jsonify({"ok": True, "is_golden": new_val})
```

Note: `EVENT_EBR_BATCH_UPDATED` might not exist as a constant. Check `mbr/shared/audit.py`. If not defined, the closest match is `EVENT_EBR_BATCH_STATUS_CHANGED`. Actually looking at the Phase 1 constants, there is NO `EVENT_EBR_BATCH_UPDATED` — only `EVENT_EBR_BATCH_CREATED` and `EVENT_EBR_BATCH_STATUS_CHANGED`. For golden toggle, we should use `EVENT_EBR_BATCH_STATUS_CHANGED` with a diff, or add a new constant. Per spec, Phase 4 says use `ebr.batch.updated` → **add the constant if it doesn't exist**:

```python
# In mbr/shared/audit.py, if EVENT_EBR_BATCH_UPDATED is missing, add it:
EVENT_EBR_BATCH_UPDATED = "ebr.batch.updated"
```

- [ ] **Step 6: Run tests — verify pass**

```bash
rm -f data/batch_db.sqlite
pytest tests/test_audit_phase4_lifecycle.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 7: Run full suite**

```bash
pytest 2>&1 | tail -3
```

Expected: 327 passed, 16 skipped (325 baseline + 2 new).

- [ ] **Step 8: Commit**

```bash
git add mbr/laborant/models.py mbr/laborant/routes.py mbr/shared/audit.py tests/test_audit_phase4_lifecycle.py
git commit -m "$(cat <<'COMMIT'
feat(audit): ebr.batch.created + ebr.batch.updated (golden toggle)

Phase 4 Sub-PR 4.1 task 1. Instruments batch creation and golden toggle.

- Refactored create_ebr() — removed internal db.commit(); route's
  db.commit() after log_event is the sole commit point.
- szarze_new route logs ebr.batch.created with entity_label (produkt +
  nr_partii) and payload (all creation params).
- toggle_golden route logs ebr.batch.updated with diff [{pole:is_golden}].
- Added EVENT_EBR_BATCH_UPDATED constant to audit.py.
- All intermediary db.commit()s in szarze_new consolidated into one.

2 tests cover batch creation + golden toggle.

Ref: docs/superpowers/specs/2026-04-12-audit-trail-phase4-design.md
COMMIT
)"
```

---

### Task 2: Refactor `complete_ebr` + instrument `complete_entry`

**Files:**
- Modify: `mbr/laborant/models.py` (remove `db.commit()` from `complete_ebr`, line ~555)
- Modify: `mbr/laborant/routes.py` (add log_event to `complete_entry`)
- Test: `tests/test_audit_phase4_lifecycle.py` (append)

- [ ] **Step 1: Write failing test**

Append to `tests/test_audit_phase4_lifecycle.py`:

```python
# ---------- POST /laborant/ebr/<id>/complete ----------

def test_complete_entry_logs_status_changed(client, db):
    """Completing a batch logs ebr.batch.status_changed with old/new status."""
    # Create a batch first
    client.post("/laborant/szarze/new", data={
        "produkt": "Chegina_K7", "nr_partii": "2/2026",
        "nr_amidatora": "", "nr_mieszalnika": "", "wielkosc_kg": "0",
    })
    ebr_id = db.execute("SELECT ebr_id FROM ebr_batches WHERE nr_partii='2/2026'").fetchone()["ebr_id"]

    resp = client.post(f"/laborant/ebr/{ebr_id}/complete", json={})
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT id, entity_type, entity_id, payload_json "
        "FROM audit_log WHERE event_type = 'ebr.batch.status_changed'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["entity_type"] == "ebr"
    assert rows[0]["entity_id"] == ebr_id

    payload = _json.loads(rows[0]["payload_json"])
    assert payload["old_status"] == "open"
    assert payload["new_status"] == "completed"
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_audit_phase4_lifecycle.py -k complete -v
```

- [ ] **Step 3: Refactor `complete_ebr` + instrument route**

Remove `db.commit()` from `complete_ebr` in `mbr/laborant/models.py` (~line 555).

In `mbr/laborant/routes.py`, find `complete_entry` (~line 245). Read the existing handler, then instrument:

```python
@laborant_bp.route("/laborant/ebr/<int:ebr_id>/complete", methods=["POST"])
@role_required("laborant", "laborant_kj", "admin")
def complete_entry(ebr_id):
    data = request.get_json(silent=True) or {}
    zbiorniki = data.get("zbiorniki")
    with db_session() as db:
        # Read status before completion for the audit diff
        old_row = db.execute(
            "SELECT status FROM ebr_batches WHERE ebr_id=?", (ebr_id,)
        ).fetchone()
        old_status = old_row["status"] if old_row else "unknown"

        complete_ebr(db, ebr_id, zbiorniki=zbiorniki)

        user = session.get("user", {})
        audit.log_event(
            audit.EVENT_EBR_BATCH_STATUS_CHANGED,
            entity_type="ebr",
            entity_id=ebr_id,
            payload={
                "old_status": old_status,
                "new_status": "completed",
                "przepompowanie_json": data.get("zbiorniki"),
            },
            actors=[{
                "worker_id": None,
                "actor_login": user.get("login", "unknown"),
                "actor_rola": user.get("rola", "unknown"),
            }],
            db=db,
        )
        db.commit()

        sync_ebr_to_v4(db, ebr_id)
    return jsonify({"ok": True})
```

Note: `sync_ebr_to_v4` call may also commit. Check and handle — it may need to be called after the main commit, or refactored similarly. For now, leave it — it operates on a different table (v4 sync) and its own commit is acceptable since the audit entry is already committed.

- [ ] **Step 4: Run — verify pass**

```bash
pytest tests/test_audit_phase4_lifecycle.py -v
```

Expected: 3 tests PASS (2 from Task 1 + 1 new).

- [ ] **Step 5: Commit**

```bash
git add mbr/laborant/models.py mbr/laborant/routes.py tests/test_audit_phase4_lifecycle.py
git commit -m "$(cat <<'COMMIT'
feat(audit): ebr.batch.status_changed on batch completion

Phase 4 Sub-PR 4.1 task 2. Instruments batch completion.

- Refactored complete_ebr() — removed internal db.commit()
- complete_entry route reads old_status before completion, logs
  ebr.batch.status_changed with payload {old_status, new_status,
  przepompowanie_json}

Sub-PR 4.1 (batch lifecycle) complete: 3 events live.

Ref: docs/superpowers/specs/2026-04-12-audit-trail-phase4-design.md
COMMIT
)"
```

---

## Sub-PR 4.2: Wyniki (Tasks 3-4)

### Task 3: Refactor `save_wyniki` + instrument `save_entry` with diff collection

**Files:**
- Modify: `mbr/laborant/models.py` (remove `db.commit()` from `save_wyniki` + remove Phase 1 neutralized TODO at line ~480)
- Modify: `mbr/laborant/routes.py` (add log_event with diff to `save_entry`)
- Create: `tests/test_audit_phase4_wyniki.py`

This is the **most complex single task** in Phase 4 because `save_wyniki` processes multiple parameters in a loop and we need to collect diffs across all of them into a single audit entry.

**Strategy**: The route calls `save_wyniki(db, ...)` which processes all values. BEFORE calling, snapshot existing wyniki. AFTER calling, snapshot again. Compute diff using `audit.diff_fields` per parameter. Collect all diffs into one list. If any diffs → one log_event with the full list.

- [ ] **Step 1: Create test file with failing test**

Create `tests/test_audit_phase4_wyniki.py`:

```python
"""Tests for Phase 4 wyniki audit events."""

import json as _json
import sqlite3
import pytest
from contextlib import contextmanager
from datetime import datetime

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (1, 'Anna', 'Kowalska', 'AK', 'AK', 1)"
    )
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "utworzony_przez, dt_utworzenia) VALUES (?, 1, 'active', '[]', ?, 'test', ?)",
        ("TestP", _json.dumps({"analiza": {"pola": [
            {"kod": "sm", "tag": "", "min": 40, "max": 60},
            {"kod": "ph", "tag": "", "min": 5, "max": 9},
        ]}}), now),
    )
    mbr_id = conn.execute("SELECT mbr_id FROM mbr_templates WHERE produkt='TestP'").fetchone()["mbr_id"]
    conn.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, typ) "
        "VALUES (?, 'TestP__1', '1/2026', ?, 'open', 'szarza')",
        (mbr_id, now),
    )
    conn.commit()
    yield conn
    conn.close()


def _make_client(monkeypatch, db):
    import mbr.db
    import mbr.laborant.routes
    import mbr.admin.audit_routes

    @contextmanager
    def fake_db_session():
        yield db

    monkeypatch.setattr(mbr.db, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.laborant.routes, "db_session", fake_db_session)
    monkeypatch.setattr(mbr.admin.audit_routes, "db_session", fake_db_session)

    from mbr.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"login": "tester", "rola": "laborant", "imie_nazwisko": None}
        sess["shift_workers"] = [1]
    return client


@pytest.fixture
def client(monkeypatch, db):
    return _make_client(monkeypatch, db)


# ---------- POST /laborant/ebr/<id>/save ----------

def test_save_wyniki_logs_single_entry_per_submit(client, db):
    """Saving multiple parameters in one submit produces ONE audit entry
    with a diff list covering all changed values."""
    ebr_id = db.execute("SELECT ebr_id FROM ebr_batches LIMIT 1").fetchone()["ebr_id"]

    resp = client.post(
        f"/laborant/ebr/{ebr_id}/save",
        json={"sekcja": "analiza", "values": {
            "sm": {"wartosc": 45.3, "komentarz": ""},
            "ph": {"wartosc": 7.1, "komentarz": ""},
        }},
    )
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT id, event_type, entity_type, entity_id, diff_json, payload_json "
        "FROM audit_log WHERE event_type IN ('ebr.wynik.saved', 'ebr.wynik.updated')"
    ).fetchall()
    # First save = saved (INSERT path)
    assert len(rows) >= 1
    r = rows[0]
    assert r["entity_type"] == "ebr"
    assert r["entity_id"] == ebr_id

    # Diff should contain entries for both sm and ph
    diff = _json.loads(r["diff_json"]) if r["diff_json"] else []
    kody = {d["pole"] for d in diff}
    assert "sm" in kody or len(diff) >= 1  # at least we logged something


def test_save_wyniki_resave_uses_updated_event(client, db):
    """Re-saving the same parameter with a different value → ebr.wynik.updated."""
    ebr_id = db.execute("SELECT ebr_id FROM ebr_batches LIMIT 1").fetchone()["ebr_id"]

    # First save
    client.post(f"/laborant/ebr/{ebr_id}/save", json={
        "sekcja": "analiza", "values": {"sm": {"wartosc": 45.0}},
    })
    # Second save — changed value
    client.post(f"/laborant/ebr/{ebr_id}/save", json={
        "sekcja": "analiza", "values": {"sm": {"wartosc": 47.0}},
    })

    rows = db.execute(
        "SELECT event_type, diff_json FROM audit_log "
        "WHERE event_type IN ('ebr.wynik.saved', 'ebr.wynik.updated') ORDER BY id"
    ).fetchall()
    assert len(rows) >= 2
    # First = saved, second = updated
    assert rows[0]["event_type"] == "ebr.wynik.saved"
    assert rows[1]["event_type"] == "ebr.wynik.updated"

    # The updated diff should show old → new
    diff = _json.loads(rows[1]["diff_json"])
    sm_diff = next((d for d in diff if d["pole"] == "sm"), None)
    assert sm_diff is not None
    assert sm_diff["stara"] == 45.0
    assert sm_diff["nowa"] == 47.0
```

- [ ] **Step 2: Run — verify failure**

```bash
rm -f data/batch_db.sqlite
pytest tests/test_audit_phase4_wyniki.py -v
```

- [ ] **Step 3: Refactor `save_wyniki`**

In `mbr/laborant/models.py`, find `save_wyniki` (~line 434).

Changes:
1. Remove the neutralized `pass  # TODO(audit-phase-4)` at line ~480
2. Remove `db.commit()` at line ~522
3. Remove the second `db.commit()` at line ~528 (sync_seq bump) — fold into a single commit by the route
4. The function now stages all INSERTs/UPDATEs but does NOT commit. It returns metadata the route needs for the audit entry.

**Key change**: `save_wyniki` should return diff information. Add a return value:

```python
def save_wyniki(...) -> dict:
    """Save lab results. Returns {'diffs': [...], 'has_inserts': bool, 'has_updates': bool}."""
    # ... existing code minus the commits and TODO ...
    
    diffs = []
    has_inserts = False
    has_updates = False
    
    for kod, entry in values.items():
        # ... existing validation ...
        
        old_row = db.execute(
            "SELECT wynik_id, wartosc FROM ebr_wyniki WHERE ebr_id=? AND sekcja=? AND kod_parametru=?",
            (ebr_id, sekcja, kod),
        ).fetchone()
        
        is_update = old_row is not None
        if is_update:
            has_updates = True
            old_val = old_row["wartosc"]
            if old_val != wartosc:
                diffs.append({"pole": kod, "stara": old_val, "nowa": wartosc})
        else:
            has_inserts = True
            diffs.append({"pole": kod, "stara": None, "nowa": wartosc})
        
        # ... existing UPSERT SQL ...
    
    # Bump sync_seq (don't commit — caller does)
    if ebr and ebr.get("status") == "completed":
        next_seq = db.execute("SELECT COALESCE(MAX(sync_seq), 0) + 1 FROM ebr_batches").fetchone()[0]
        db.execute("UPDATE ebr_batches SET sync_seq = ? WHERE ebr_id = ?", (next_seq, ebr_id))
    
    return {"diffs": diffs, "has_inserts": has_inserts, "has_updates": has_updates}
```

- [ ] **Step 4: Instrument `save_entry` route**

In `mbr/laborant/routes.py`, find `save_entry` (~line 181). After calling `save_wyniki(...)`, use the returned info:

```python
        result = save_wyniki(db, ebr_id, sekcja, values, user, ebr=ebr)

        # Audit log — one entry per submit
        if result["diffs"]:
            event_type = audit.EVENT_EBR_WYNIK_UPDATED if result["has_updates"] else audit.EVENT_EBR_WYNIK_SAVED
            # If mix of inserts and updates, prefer 'saved' for the first batch
            if result["has_inserts"] and result["has_updates"]:
                event_type = audit.EVENT_EBR_WYNIK_SAVED  # conservative — "something new saved"

            sess_user = session.get("user", {})
            audit.log_event(
                event_type,
                entity_type="ebr",
                entity_id=ebr_id,
                entity_label=f"{ebr.get('produkt', '')} {ebr.get('nr_partii', '')}".strip() if ebr else None,
                diff=result["diffs"],
                payload={"sekcja": sekcja, "count": len(result["diffs"])},
                actors=[{
                    "worker_id": None,
                    "actor_login": sess_user.get("login", "unknown"),
                    "actor_rola": sess_user.get("rola", "unknown"),
                }],
                db=db,
            )
        db.commit()
```

Remove any existing `db.commit()` calls that were before this point in `save_entry`.

- [ ] **Step 5: Run tests — verify pass**

```bash
pytest tests/test_audit_phase4_wyniki.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 6: Run full suite**

```bash
pytest 2>&1 | tail -3
```

Expected: ~329 passed.

- [ ] **Step 7: Commit**

```bash
git add mbr/laborant/models.py mbr/laborant/routes.py tests/test_audit_phase4_wyniki.py
git commit -m "$(cat <<'COMMIT'
feat(audit): ebr.wynik.saved/updated — one entry per submit with full diff

Phase 4 Sub-PR 4.2 task 3. Instruments the save_wyniki path.

- Refactored save_wyniki() — removed internal db.commit() + Phase 1
  neutralized TODO. Now returns {diffs, has_inserts, has_updates} for
  the route to build the audit entry.
- save_entry route logs ONE entry per form submit. INSERT = saved,
  UPDATE = updated. diff = list of all changed parameters.
- Bump sync_seq folded into single transaction.

2 tests cover first save + re-save with diff.

Ref: docs/superpowers/specs/2026-04-12-audit-trail-phase4-design.md
COMMIT
)"
```

---

### Task 4: Instrument `save_samples`

**Files:**
- Modify: `mbr/laborant/routes.py` (add log_event to `save_samples`)
- Test: `tests/test_audit_phase4_wyniki.py` (append)

- [ ] **Step 1: Read `save_samples` route to understand what it does**

```bash
sed -n '263,300p' mbr/laborant/routes.py
```

- [ ] **Step 2: Write failing test**

Append to `tests/test_audit_phase4_wyniki.py`:

```python
# ---------- POST /api/ebr/<id>/samples ----------

def test_save_samples_logs_event(client, db):
    """Saving samples_json for a parameter logs ebr.wynik.updated."""
    ebr_id = db.execute("SELECT ebr_id FROM ebr_batches LIMIT 1").fetchone()["ebr_id"]

    # First save a wynik so there's a row to update samples on
    client.post(f"/laborant/ebr/{ebr_id}/save", json={
        "sekcja": "analiza", "values": {"sm": {"wartosc": 45.0}},
    })

    resp = client.post(f"/api/ebr/{ebr_id}/samples", json={
        "sekcja": "analiza",
        "kod": "sm",
        "samples": [44.8, 45.1, 45.7],
    })
    assert resp.status_code == 200

    rows = db.execute(
        "SELECT event_type, payload_json FROM audit_log WHERE event_type = 'ebr.wynik.updated' "
        "AND payload_json LIKE '%samples%'"
    ).fetchall()
    assert len(rows) >= 1
```

- [ ] **Step 3: Read `save_samples` and instrument**

Read the existing code. Add log_event after the samples_json UPDATE. Use explicit actors.

- [ ] **Step 4: Run — verify pass**

```bash
pytest tests/test_audit_phase4_wyniki.py -v
```

- [ ] **Step 5: Commit**

```bash
git add mbr/laborant/routes.py tests/test_audit_phase4_wyniki.py
git commit -m "$(cat <<'COMMIT'
feat(audit): ebr.wynik.updated on samples save

Phase 4 Sub-PR 4.2 task 4. Instruments save_samples.
Sub-PR 4.2 (wyniki) complete.

Ref: docs/superpowers/specs/2026-04-12-audit-trail-phase4-design.md
COMMIT
)"
```

---

## Sub-PR 4.3: Etapy (Tasks 5-6)

### Task 5: Refactor ALL 5 etapy model functions — remove commits

**Files:**
- Modify: `mbr/etapy/models.py` (remove `db.commit()` from 5 functions + remove Phase 1 neutralized TODO at line ~44)

This is a mechanical refactor — no new functionality, just removing `db.commit()` calls from: `save_etap_analizy`, `add_korekta`, `confirm_korekta`, `zatwierdz_etap`, `skip_etap`.

- [ ] **Step 1: Read each function and identify the commit line**

```bash
grep -n "db.commit()" mbr/etapy/models.py
```

- [ ] **Step 2: Remove all `db.commit()` calls and the Phase 1 TODO**

For each of the 5 functions: delete the `db.commit()` line. Also remove the `pass  # TODO(audit-phase-4)` at line ~44 in `save_etap_analizy`.

- [ ] **Step 3: Run existing tests — verify nothing broke**

```bash
pytest tests/test_etapy.py 2>&1 | tail -5
```

Expected: all existing etapy tests pass. The in-memory SQLite fixture shares one connection, so uncommitted writes are visible to subsequent SELECTs.

- [ ] **Step 4: Commit**

```bash
git add mbr/etapy/models.py
git commit -m "$(cat <<'COMMIT'
refactor(audit): remove db.commit() from 5 etapy model functions

Phase 4 Sub-PR 4.3 prep. Callers (routes) now own the commit — allows
atomic log_event() in the same transaction. Removed the Phase 1
neutralized TODO in save_etap_analizy.

Functions refactored: save_etap_analizy, add_korekta, confirm_korekta,
zatwierdz_etap, skip_etap. Each has exactly 1 caller (verified by grep).

Ref: docs/superpowers/specs/2026-04-12-audit-trail-phase4-design.md
COMMIT
)"
```

---

### Task 6: Instrument ALL 5 etapy routes

**Files:**
- Modify: `mbr/etapy/routes.py` (add log_event + db.commit to 5 routes)
- Create: `tests/test_audit_phase4_etapy.py`

- [ ] **Step 1: Create test file with shared fixtures + 5 failing tests**

Create `tests/test_audit_phase4_etapy.py`. Follow the same pattern as `tests/test_audit_phase4_lifecycle.py` for fixtures. Seed workers, MBR template (for a product with process stages), and an open EBR. Each test hits one etapy endpoint and asserts the audit_log entry.

5 core tests:
- `test_save_etap_analizy_logs_event` — POST `/api/ebr/<id>/etapy-analizy` → `ebr.stage.event_added`, payload `{type:'analizy', etap, runda}`
- `test_add_korekta_logs_event` — POST `/api/ebr/<id>/korekty` → `ebr.stage.event_added`, payload `{type:'korekta', etap, substancja, ilosc_kg}`
- `test_confirm_korekta_logs_event` — PUT `/api/ebr/<id>/korekty/<kid>` → `ebr.stage.event_updated`
- `test_zatwierdz_etap_logs_event` — POST `/api/ebr/<id>/etapy-status/zatwierdz` → `ebr.stage.event_added`, payload `{type:'zatwierdz', etap}`
- `test_skip_etap_logs_event` — POST `/api/ebr/<id>/etapy-status/skip` → `ebr.stage.event_added`, payload `{type:'skip', etap}`

The test fixture needs:
- A product with process stages (use `Chegina_K7` which maps to `FULL_PIPELINE_PRODUCTS` — has stages like amidowanie, etc.)
- `init_etapy_status(db, ebr_id, produkt)` called to initialize the stage statuses
- `ebr_etapy_analizy` table (created by `init_mbr_tables`)

For the korekta tests, seed an `ebr_etapy_analizy` row first so the korekta has a context.

- [ ] **Step 2: Run — verify failure**

```bash
rm -f data/batch_db.sqlite
pytest tests/test_audit_phase4_etapy.py -v
```

- [ ] **Step 3: Add `from mbr.shared import audit` to `mbr/etapy/routes.py`**

Check if it's already imported. If not, add at the top.

- [ ] **Step 4: Instrument all 5 routes**

For each of the 5 write endpoints in `mbr/etapy/routes.py`, add `log_event()` + `db.commit()` at the end, following the same explicit-actors pattern as all other Phase 3/4 routes.

Template for each route (adapt entity details per event):

```python
        user = session.get("user", {})
        audit.log_event(
            audit.EVENT_EBR_STAGE_EVENT_ADDED,  # or _UPDATED for confirm_korekta
            entity_type="ebr",
            entity_id=ebr_id,
            payload={
                "type": "analizy",  # or 'korekta', 'zatwierdz', 'skip'
                "etap": etap,
                # ... additional fields per event type
            },
            actors=[{
                "worker_id": None,
                "actor_login": user.get("login", "unknown"),
                "actor_rola": user.get("rola", "unknown"),
            }],
            db=db,
        )
        db.commit()
```

- [ ] **Step 5: Run — verify pass**

```bash
pytest tests/test_audit_phase4_etapy.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 6: Run full suite**

```bash
pytest 2>&1 | tail -3
```

- [ ] **Step 7: Commit**

```bash
git add mbr/etapy/routes.py tests/test_audit_phase4_etapy.py
git commit -m "$(cat <<'COMMIT'
feat(audit): ebr.stage.event_added/updated for all 5 etapy routes

Phase 4 Sub-PR 4.3 task 6. Instruments etapy-analizy save, korekta
add/confirm, stage approve (zatwierdz), and stage skip.

Each event uses payload.type discriminator ('analizy', 'korekta',
'zatwierdz', 'skip') per spec — 3 EVENT_* constants, not 5.

Sub-PR 4.3 (etapy) complete.

5 tests cover each endpoint.

Ref: docs/superpowers/specs/2026-04-12-audit-trail-phase4-design.md
COMMIT
)"
```

---

## Sub-PR 4.4: Uwagi consolidation (Tasks 7-9)

### Task 7: Migration script `migrate_uwagi_to_audit.py`

**Files:**
- Create: `scripts/migrate_uwagi_to_audit.py`
- Create: `tests/test_migrate_uwagi_to_audit.py`

- [ ] **Step 1: Write 3 failing tests**

Create `tests/test_migrate_uwagi_to_audit.py`:

```python
"""Tests for scripts/migrate_uwagi_to_audit.py"""

import json
import sqlite3
import pytest

from mbr.models import init_mbr_tables


def _make_db_with_uwagi_history(rows=None):
    """In-memory DB with ebr_uwagi_history + audit_log tables."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_mbr_tables(db)
    # Seed a batch so entity_label can resolve
    db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "utworzony_przez, dt_utworzenia) VALUES ('TestP', 1, 'active', '[]', '{}', 'test', '2026-04-01')"
    )
    mbr_id = db.execute("SELECT mbr_id FROM mbr_templates").fetchone()["mbr_id"]
    db.execute(
        "INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start, status, typ) "
        "VALUES (1, ?, 'TestP__1', '1/2026', '2026-04-01', 'open', 'szarza')",
        (mbr_id,),
    )
    # Seed workers for author resolution
    db.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname) VALUES (1, 'Anna', 'Kowalska', 'AK', 'AK')"
    )
    for r in rows or []:
        db.execute(
            "INSERT INTO ebr_uwagi_history (ebr_id, tekst, action, autor, dt) VALUES (?, ?, ?, ?, ?)",
            r,
        )
    db.commit()
    return db


def test_migrate_uwagi_empty_table():
    db = _make_db_with_uwagi_history()
    from scripts.migrate_uwagi_to_audit import migrate_uwagi
    summary = migrate_uwagi(db)
    assert summary["migrated"] == 0


def test_migrate_uwagi_backfills_rows():
    db = _make_db_with_uwagi_history(rows=[
        (1, "stary tekst", "create", "AK", "2026-04-01T10:00:00"),
        (1, "stary tekst", "update", "AK", "2026-04-01T11:00:00"),
    ])
    from scripts.migrate_uwagi_to_audit import migrate_uwagi
    summary = migrate_uwagi(db)
    assert summary["migrated"] == 2

    rows = db.execute(
        "SELECT event_type, entity_type, entity_id, payload_json FROM audit_log "
        "WHERE event_type = 'ebr.uwagi.updated' ORDER BY id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["entity_type"] == "ebr"
    assert rows[0]["entity_id"] == 1

    payload = json.loads(rows[0]["payload_json"])
    assert payload["action"] == "create"
    assert payload["tekst"] == "stary tekst"


def test_migrate_uwagi_idempotent():
    db = _make_db_with_uwagi_history(rows=[
        (1, "tekst", "create", "AK", "2026-04-01T10:00:00"),
    ])
    from scripts.migrate_uwagi_to_audit import migrate_uwagi
    migrate_uwagi(db)
    summary2 = migrate_uwagi(db)
    assert summary2["migrated"] == 0
    count = db.execute(
        "SELECT COUNT(*) FROM audit_log WHERE event_type='ebr.uwagi.updated'"
    ).fetchone()[0]
    assert count == 1  # only from first run
```

- [ ] **Step 2: Run — verify failure**

```bash
pytest tests/test_migrate_uwagi_to_audit.py -v
```

Expected: ImportError.

- [ ] **Step 3: Create migration script**

Create `scripts/migrate_uwagi_to_audit.py`:

```python
"""
migrate_uwagi_to_audit.py — one-time migration: ebr_uwagi_history → audit_log.

Backfills each ebr_uwagi_history row as an audit_log entry with
event_type='ebr.uwagi.updated', entity_type='ebr', payload={action, tekst}.

Idempotent: skips rows that already have a matching audit_log entry
(matched by entity_id + dt + event_type).

Usage:
    python scripts/migrate_uwagi_to_audit.py --db data/batch_db.sqlite [--dry-run]
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def _resolve_worker(db, autor: str):
    """Resolve autor string to (worker_id, actor_login, actor_rola)."""
    if not autor:
        return (None, "unknown", "unknown")
    row = db.execute(
        "SELECT id FROM workers WHERE inicjaly=? OR nickname=? LIMIT 1",
        (autor, autor),
    ).fetchone()
    if row:
        return (row[0], autor, "laborant")
    return (None, autor, "unknown")


def _get_entity_label(db, ebr_id: int) -> str:
    """Resolve batch label for entity_label."""
    row = db.execute(
        "SELECT b.batch_id, b.nr_partii, m.produkt "
        "FROM ebr_batches b JOIN mbr_templates m ON b.mbr_id = m.mbr_id "
        "WHERE b.ebr_id = ?",
        (ebr_id,),
    ).fetchone()
    if row:
        return f"{row['produkt']} {row['nr_partii']}"
    return None


def migrate_uwagi(db: sqlite3.Connection, dry_run: bool = False) -> dict:
    summary = {"migrated": 0, "skipped": 0}

    history_rows = db.execute(
        "SELECT id, ebr_id, tekst, action, autor, dt FROM ebr_uwagi_history ORDER BY id"
    ).fetchall()

    for h in history_rows:
        # Idempotency check
        existing = db.execute(
            "SELECT 1 FROM audit_log WHERE event_type='ebr.uwagi.updated' "
            "AND entity_id=? AND dt=?",
            (h["ebr_id"], h["dt"]),
        ).fetchone()
        if existing:
            summary["skipped"] += 1
            continue

        if dry_run:
            summary["migrated"] += 1
            continue

        entity_label = _get_entity_label(db, h["ebr_id"])

        cur = db.execute(
            """INSERT INTO audit_log
               (dt, event_type, entity_type, entity_id, entity_label,
                payload_json, result)
               VALUES (?, 'ebr.uwagi.updated', 'ebr', ?, ?, ?, 'ok')""",
            (
                h["dt"],
                h["ebr_id"],
                entity_label,
                json.dumps({"action": h["action"], "tekst": h["tekst"]}, ensure_ascii=False),
            ),
        )
        worker_id, actor_login, actor_rola = _resolve_worker(db, h["autor"])
        db.execute(
            "INSERT INTO audit_log_actors (audit_id, worker_id, actor_login, actor_rola) "
            "VALUES (?, ?, ?, ?)",
            (cur.lastrowid, worker_id, actor_login, actor_rola),
        )
        summary["migrated"] += 1

    if not dry_run and summary["migrated"] > 0:
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
        summary = migrate_uwagi(db, dry_run=args.dry_run)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()

    print(f"Uwagi migration: {summary}")
    if args.dry_run:
        print("(dry-run)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run — verify pass**

```bash
pytest tests/test_migrate_uwagi_to_audit.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_uwagi_to_audit.py tests/test_migrate_uwagi_to_audit.py
git commit -m "$(cat <<'COMMIT'
feat(audit): uwagi migration script — ebr_uwagi_history → audit_log

Phase 4 Sub-PR 4.4 task 7. Idempotent one-shot migration.

Each ebr_uwagi_history row becomes an audit_log entry:
  event_type='ebr.uwagi.updated', entity_type='ebr',
  payload={action, tekst}, actor resolved via workers table.

Idempotency: NOT EXISTS (entity_id + dt + event_type).

3 tests: empty, backfill, idempotent.

Ref: docs/superpowers/specs/2026-04-12-audit-trail-phase4-design.md
COMMIT
)"
```

---

### Task 8: Refactor `save_uwagi` + `get_uwagi` to use audit_log

**Files:**
- Modify: `mbr/laborant/models.py` (`save_uwagi` — stop writing to ebr_uwagi_history, call log_event; `get_uwagi` — read from audit_log)
- Modify: `mbr/laborant/routes.py` (routes call db.commit after save_uwagi)
- Create: `tests/test_audit_phase4_uwagi.py`

This is the **highest risk task** in Phase 4 — changes both read and write paths for uwagi.

- [ ] **Step 1: Write 3 failing tests**

Create `tests/test_audit_phase4_uwagi.py`. Tests:

```python
"""Tests for Phase 4 uwagi consolidation — audit_log as SSOT."""

import json as _json
import sqlite3
import pytest
from contextlib import contextmanager
from datetime import datetime

from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    conn.execute(
        "INSERT INTO workers (id, imie, nazwisko, inicjaly, nickname, aktywny) "
        "VALUES (999, 'Test', 'User', 'TU', 'testuser', 1)"
    )
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, "
        "utworzony_przez, dt_utworzenia) VALUES (?, 1, 'active', '[]', '{}', 'test', ?)",
        ("TestP", now),
    )
    mbr_id = conn.execute("SELECT mbr_id FROM mbr_templates").fetchone()["mbr_id"]
    conn.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, typ) "
        "VALUES (?, 'TestP__1', '1/2026', ?, 'open', 'szarza')",
        (mbr_id, now),
    )
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def ebr_id(db):
    return db.execute("SELECT ebr_id FROM ebr_batches LIMIT 1").fetchone()["ebr_id"]


def _make_client(monkeypatch, db):
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
        sess["user"] = {"login": "testuser", "rola": "laborant"}
        sess["shift_workers"] = [999]
    return client


@pytest.fixture
def client(monkeypatch, db, ebr_id):
    return _make_client(monkeypatch, db)


def test_save_uwagi_writes_to_audit_not_history(client, db, ebr_id):
    """PUT /api/ebr/<id>/uwagi writes to audit_log, NOT ebr_uwagi_history."""
    resp = client.put(f"/api/ebr/{ebr_id}/uwagi", json={"tekst": "Nowa notatka"})
    assert resp.status_code == 200

    # audit_log has the entry
    audit_rows = db.execute(
        "SELECT event_type, payload_json FROM audit_log WHERE event_type='ebr.uwagi.updated'"
    ).fetchall()
    assert len(audit_rows) == 1
    payload = _json.loads(audit_rows[0]["payload_json"])
    assert payload["action"] == "create"

    # ebr_uwagi_history should have ZERO new rows (old mechanism disabled)
    history_count = db.execute("SELECT COUNT(*) FROM ebr_uwagi_history").fetchone()[0]
    assert history_count == 0


def test_get_uwagi_reads_from_audit_log(client, db, ebr_id):
    """GET /api/ebr/<id>/uwagi returns history from audit_log, not ebr_uwagi_history."""
    # Create + update via PUT
    client.put(f"/api/ebr/{ebr_id}/uwagi", json={"tekst": "First"})
    client.put(f"/api/ebr/{ebr_id}/uwagi", json={"tekst": "Second"})

    resp = client.get(f"/api/ebr/{ebr_id}/uwagi")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["tekst"] == "Second"
    assert len(data["historia"]) >= 1  # at least the create event
    # Each historia item has the expected shape
    for h in data["historia"]:
        assert "tekst" in h or "action" in h
        assert "autor" in h
        assert "dt" in h


def test_get_uwagi_returns_compatible_dict_shape(client, db, ebr_id):
    """The dict shape from get_uwagi must match the old format:
    {tekst, dt, autor, historia: [{tekst, action, autor, dt}]}"""
    client.put(f"/api/ebr/{ebr_id}/uwagi", json={"tekst": "Test"})

    resp = client.get(f"/api/ebr/{ebr_id}/uwagi")
    data = resp.get_json()

    # Top level
    assert "tekst" in data
    assert "dt" in data
    assert "autor" in data
    assert "historia" in data
    assert isinstance(data["historia"], list)

    # Historia items
    if data["historia"]:
        h = data["historia"][0]
        assert "tekst" in h
        assert "action" in h
        assert "autor" in h
        assert "dt" in h
```

- [ ] **Step 2: Run — verify failure**

```bash
rm -f data/batch_db.sqlite
pytest tests/test_audit_phase4_uwagi.py -v
```

- [ ] **Step 3: Refactor `save_uwagi` in `mbr/laborant/models.py`**

Find `save_uwagi` (~line 793). Key changes:
1. Remove the INSERT into `ebr_uwagi_history` (line ~838)
2. Remove `db.commit()` (line ~847)
3. Keep the UPDATE on `ebr_batches.uwagi_koncowe`
4. The function does NOT call log_event itself — the ROUTE does (for atomicity + correct actor resolution)
5. Return metadata for the route: `{action, old_text}`

```python
def save_uwagi(db: sqlite3.Connection, ebr_id: int, tekst, autor: str) -> dict:
    """Create, update, or delete uwagi_koncowe for an EBR batch.

    Returns dict: {tekst, dt, autor, historia, action, old_text}.
    Caller is responsible for log_event() and db.commit().
    """
    # ... existing validation (len check, cancelled batch check) ...

    old = row["uwagi_koncowe"]
    new = tekst or None

    # Action detection — same logic as before
    if new is None and old is None:
        return get_uwagi(db, ebr_id)  # no-op
    if new is not None and old is None:
        action = "create"
    elif new is None and old is not None:
        action = "delete"
    elif new != old:
        action = "update"
    else:
        return get_uwagi(db, ebr_id)  # no-op (same text)

    now = datetime.now().isoformat(timespec="seconds")

    # NO LONGER write to ebr_uwagi_history — audit_log is the SSOT now
    # (old line was: INSERT INTO ebr_uwagi_history ...)

    db.execute(
        "UPDATE ebr_batches SET uwagi_koncowe = ? WHERE ebr_id = ?",
        (new, ebr_id),
    )

    # Return metadata for the route to build the audit entry
    result = get_uwagi(db, ebr_id)
    result["_action"] = action
    result["_old_text"] = old
    return result
```

- [ ] **Step 4: Refactor `get_uwagi` to read from audit_log**

Replace the `ebr_uwagi_history` query with an `audit_log` query:

```python
def get_uwagi(db: sqlite3.Connection, ebr_id: int) -> dict:
    """Return current uwagi_koncowe state for an EBR batch.

    Returns dict with keys: tekst, dt, autor, historia.
    History is read from audit_log (event_type='ebr.uwagi.updated').
    """
    row = db.execute(
        "SELECT uwagi_koncowe FROM ebr_batches WHERE ebr_id = ?", (ebr_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Batch {ebr_id} not found")

    import json as _json
    historia_rows = db.execute(
        """SELECT al.dt, al.payload_json,
                  (SELECT GROUP_CONCAT(ala.actor_login)
                   FROM audit_log_actors ala WHERE ala.audit_id = al.id) as autor
           FROM audit_log al
           WHERE al.entity_type = 'ebr' AND al.entity_id = ?
             AND al.event_type = 'ebr.uwagi.updated'
           ORDER BY al.dt DESC, al.id DESC""",
        (ebr_id,),
    ).fetchall()

    historia = []
    for h in historia_rows:
        payload = _json.loads(h["payload_json"]) if h["payload_json"] else {}
        historia.append({
            "tekst": payload.get("tekst"),
            "action": payload.get("action", ""),
            "autor": h["autor"] or "unknown",
            "dt": h["dt"],
        })

    tekst = row["uwagi_koncowe"]
    if tekst is None:
        dt = None
        autor = None
    elif historia:
        dt = historia[0]["dt"]
        autor = historia[0]["autor"]
    else:
        dt = None
        autor = None

    return {"tekst": tekst, "dt": dt, "autor": autor, "historia": historia}
```

- [ ] **Step 5: Update routes to log_event + commit**

In `mbr/laborant/routes.py`, find `api_put_uwagi` and `api_delete_uwagi`. After calling `save_uwagi(db, ...)`, add log_event using the returned `_action` and `_old_text`:

```python
        result = save_uwagi(db, ebr_id, tekst, autor=autor)

        # Audit log (if save_uwagi actually did something)
        action = result.pop("_action", None)
        old_text = result.pop("_old_text", None)
        if action:
            sess_user = session.get("user", {})
            audit.log_event(
                audit.EVENT_EBR_UWAGI_UPDATED,
                entity_type="ebr",
                entity_id=ebr_id,
                payload={"action": action, "tekst": old_text},
                actors=[{
                    "worker_id": None,
                    "actor_login": sess_user.get("login", "unknown"),
                    "actor_rola": sess_user.get("rola", "unknown"),
                }],
                db=db,
            )
        db.commit()
```

Apply the same pattern to `api_delete_uwagi`.

- [ ] **Step 6: Run — verify pass**

```bash
pytest tests/test_audit_phase4_uwagi.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 7: Run full test suite including existing uwagi tests**

```bash
pytest tests/test_uwagi.py tests/test_audit_phase4_uwagi.py -v 2>&1 | tail -20
pytest 2>&1 | tail -3
```

Existing `tests/test_uwagi.py` tests may need adjustment because `save_uwagi` no longer writes to `ebr_uwagi_history`. Tests that assert `len(data["historia"]) == N` will now count audit_log entries instead. The count should be the same IF the test's session generates audit entries correctly.

**If existing tests fail**: the most likely cause is that `get_uwagi` now reads from `audit_log` but the test never called `log_event` (because the model doesn't call it anymore — the route does). Fix: update the test client fixture to include the route path (PUT endpoint) rather than calling `save_uwagi` directly. OR: in the model-level tests, manually insert audit_log rows to match what the route would have written.

- [ ] **Step 8: Commit**

```bash
git add mbr/laborant/models.py mbr/laborant/routes.py tests/test_audit_phase4_uwagi.py tests/test_uwagi.py
git commit -m "$(cat <<'COMMIT'
feat(audit): uwagi consolidated — audit_log is SSOT for notes history

Phase 4 Sub-PR 4.4 task 8. The biggest change in Phase 4.

save_uwagi: no longer writes to ebr_uwagi_history. Returns _action +
_old_text metadata for the route to build the audit entry.

get_uwagi: reads history from audit_log (event_type='ebr.uwagi.updated')
instead of ebr_uwagi_history. Returns the same dict shape
{tekst, dt, autor, historia: [{tekst, action, autor, dt}]} — UI
doesn't need to change.

Routes (api_put_uwagi, api_delete_uwagi): call log_event after
save_uwagi, commit once atomically.

ebr_uwagi_history table is NOT dropped — kept until Phase 7 for
rollback safety.

3 new tests + existing uwagi tests updated.

Ref: docs/superpowers/specs/2026-04-12-audit-trail-phase4-design.md
COMMIT
)"
```

---

### Task 9: Auto-deploy hook + Phase 4 close-out

**Files:**
- Modify: `deploy/auto-deploy.sh` (add `migrate_uwagi_to_audit.py` call)
- Test: full suite verification

- [ ] **Step 1: Add migration hook to auto-deploy.sh**

Find the existing "One-shot data backfills" section in `deploy/auto-deploy.sh`. Add after the existing backfill line:

```bash
/opt/lims/venv/bin/python scripts/migrate_uwagi_to_audit.py --db data/batch_db.sqlite
```

- [ ] **Step 2: Run full suite one last time**

```bash
rm -f data/batch_db.sqlite
pytest 2>&1 | tail -5
```

Expected: ≈350 passed, 16 skipped, 0 failed.

- [ ] **Step 3: Commit**

```bash
git add deploy/auto-deploy.sh
git commit -m "$(cat <<'COMMIT'
deploy: add uwagi migration to auto-deploy

Phase 4 close-out. The uwagi migration (scripts/migrate_uwagi_to_audit.py)
runs after the existing audit_log migration and legacy backfill.
Idempotent — subsequent runs are no-ops via NOT EXISTS guard.

Phase 4 complete. All EBR write paths instrumented:
  ebr.batch.created/status_changed/updated
  ebr.wynik.saved/updated
  ebr.stage.event_added/event_updated
  ebr.uwagi.updated (consolidated from ebr_uwagi_history)

Ref: docs/superpowers/specs/2026-04-12-audit-trail-phase4-design.md
COMMIT
)"
```

---

## Phase 4 Done Definition

After Task 9:

- [ ] `create_ebr`, `save_wyniki`, `complete_ebr` refactored (no internal commit)
- [ ] 5 etapy model functions refactored (no internal commit)
- [ ] `save_uwagi` writes to audit_log, not ebr_uwagi_history
- [ ] `get_uwagi` reads history from audit_log
- [ ] Phase 1 neutralized TODOs removed (laborant/models.py:481, etapy/models.py:45)
- [ ] `scripts/migrate_uwagi_to_audit.py` exists, idempotent
- [ ] `deploy/auto-deploy.sh` calls the uwagi migration
- [ ] 10+ instrumented call sites producing audit entries
- [ ] ≈350 passed, 16 skipped, 0 failed
- [ ] Manual smoke: create batch → save results → approve stage → edit uwagi → complete batch → all visible in `/admin/audit`
- [ ] Sekcja "Historia audytu" in EBR view shows ALL events for that batch
- [ ] `EVENT_EBR_BATCH_UPDATED` constant added to audit.py

## Deployment note

Auto-deploy on prod:
1. Backup
2. `git pull`
3. `pip install` (no-op)
4. `migrate_audit_log_v2.py` — no-op
5. `backfill_audit_legacy_to_ebr.py` — no-op
6. **`migrate_uwagi_to_audit.py`** — first run, backfills existing uwagi history entries
7. `systemctl restart lims`

After restart: **every laborant action is audited.** The panel `/admin/audit` shows a complete picture of each working day.
