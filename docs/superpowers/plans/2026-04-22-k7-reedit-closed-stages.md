# K7 Reedit Closed Stages — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow laboranci to edit already-closed pipeline stages in-place while the batch card is still open, and to edit the final stage even after card closure. Reduce admin-dependency during learning phase; preserve safety by audit-logging every re-edit and warning when downstream activity exists.

**Architecture:** Single backend policy helper `is_sesja_editable(db, ebr_id, sesja_id)` codifies the two-tier rule (batch open → any sesja editable; batch closed → only last-stage sesja editable). All write endpoints call it. Frontend reads the same policy via a small JS helper derived from batch status + sidebar pipeline metadata. A new read-only endpoint `downstream-summary` feeds an inline banner warning when user edits a closed stage that already has pomiary/korekty in later stages.

**Tech Stack:** Flask + sqlite3, Jinja, plain JS (no framework); pytest for tests.

---

## File Structure

**Create:**
- `mbr/pipeline/edit_policy.py` — `is_sesja_editable()` and `has_downstream_activity()` helpers. New module so tests can import without pulling Flask.
- `tests/test_edit_policy.py` — unit tests for both helpers (4+2 scenarios).
- `tests/test_lab_routes_reedit.py` — integration tests for loosened guards + new endpoint.

**Modify:**
- `mbr/pipeline/lab_routes.py` — wire `is_sesja_editable` into POST `/pomiary`, POST `/korekta`, PUT `/korekta`; add GET `/downstream-summary`.
- `mbr/templates/laborant/szarze_list.html:~957` — sidebar readonly flag derived from batch + stage position.
- `mbr/templates/laborant/_fast_entry_content.html:~1286` — `isReadonly` uses the two-tier rule; banner injected when editing a closed sesja.
- `mbr/pipeline/models.py` — `save_pomiar` and `upsert_ebr_korekta` accept `reedit: bool` and forward it to `audit.log_event` payload.

No schema changes.

---

## Task 1: Editability policy helper

**Files:**
- Create: `mbr/pipeline/edit_policy.py`
- Test:  `tests/test_edit_policy.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_edit_policy.py
import sqlite3
import pytest

from mbr.models import init_mbr_tables
from mbr.pipeline.edit_policy import is_sesja_editable


def _seed(db):
    db.execute("INSERT INTO mbr_templates (mbr_id, produkt, wersja, active, etapy_json, surowce_json) "
               "VALUES (1, 'Chegina_K7', 1, 1, '[]', '[]')")
    db.execute("INSERT INTO ebr_batches (ebr_id, mbr_id, nr_partii, status) "
               "VALUES (100, 1, 'K7/TEST', 'open')")
    db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
               "VALUES (10, 'sulfonowanie', 'Sulfonowanie', 'cykliczny')")
    db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
               "VALUES (11, 'analiza_koncowa', 'Analiza końcowa', 'jednorazowy')")
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chegina_K7', 10, 1)")
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chegina_K7', 11, 2)")
    db.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, dt_start) "
               "VALUES (1000, 100, 10, 1, 'zamkniety', '2026-04-22T10:00:00')")
    db.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status, dt_start) "
               "VALUES (1001, 100, 11, 1, 'zamkniety', '2026-04-22T12:00:00')")
    db.commit()


@pytest.fixture
def db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_mbr_tables(c)
    _seed(c)
    yield c
    c.close()


def test_open_batch_any_closed_sesja_editable(db):
    """Batch open → closed sulfonowanie is editable."""
    assert is_sesja_editable(db, ebr_id=100, sesja_id=1000) is True


def test_open_batch_last_stage_editable(db):
    """Batch open → closed analiza_koncowa is editable."""
    assert is_sesja_editable(db, ebr_id=100, sesja_id=1001) is True


def test_closed_batch_last_stage_editable(db):
    """Batch completed → only last stage (analiza_koncowa) editable."""
    db.execute("UPDATE ebr_batches SET status='completed' WHERE ebr_id=100")
    db.commit()
    assert is_sesja_editable(db, ebr_id=100, sesja_id=1001) is True


def test_closed_batch_earlier_stage_not_editable(db):
    """Batch completed → sulfonowanie NOT editable."""
    db.execute("UPDATE ebr_batches SET status='completed' WHERE ebr_id=100")
    db.commit()
    assert is_sesja_editable(db, ebr_id=100, sesja_id=1000) is False


def test_missing_sesja_not_editable(db):
    assert is_sesja_editable(db, ebr_id=100, sesja_id=9999) is False
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_edit_policy.py -v`
Expected: FAIL — module `mbr.pipeline.edit_policy` not found.

- [ ] **Step 3: Create implementation**

```python
# mbr/pipeline/edit_policy.py
"""Editability policy for pipeline sessions.

Two-tier rule (learning-phase friendly):
  - Batch open   → every sesja is editable, regardless of sesja.status.
  - Batch closed → only the last-in-pipeline sesja is editable.

Writes that hit a zamkniety sesja are legal per this policy — callers must
still audit-log them with reedit=1 so history stays traceable.
"""
from __future__ import annotations

import sqlite3


def is_sesja_editable(db: sqlite3.Connection, *, ebr_id: int, sesja_id: int) -> bool:
    """Return True if the given sesja may accept writes under the edit policy."""
    row = db.execute(
        """SELECT b.status AS batch_status, s.etap_id,
                  (SELECT m.produkt FROM mbr_templates m WHERE m.mbr_id = b.mbr_id) AS produkt
           FROM ebr_etap_sesja s
           JOIN ebr_batches b ON b.ebr_id = s.ebr_id
           WHERE s.id = ? AND s.ebr_id = ?""",
        (sesja_id, ebr_id),
    ).fetchone()
    if row is None:
        return False
    if row["batch_status"] == "open":
        return True
    # Batch closed → only the last stage (highest kolejnosc) is editable.
    last = db.execute(
        "SELECT etap_id FROM produkt_pipeline WHERE produkt = ? "
        "ORDER BY kolejnosc DESC LIMIT 1",
        (row["produkt"],),
    ).fetchone()
    return bool(last and last["etap_id"] == row["etap_id"])
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_edit_policy.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/pipeline/edit_policy.py tests/test_edit_policy.py
git commit -m "feat(pipeline): add is_sesja_editable policy for reedit-closed-stages"
```

---

## Task 2: downstream-activity helper

**Files:**
- Modify: `mbr/pipeline/edit_policy.py`
- Modify: `tests/test_edit_policy.py`

- [ ] **Step 1: Append failing tests**

```python
# tests/test_edit_policy.py  — append after existing tests

from mbr.pipeline.edit_policy import has_downstream_activity


def test_downstream_detects_later_pomiar(db):
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (1, 'x', 'X', 'bezposredni')")
    db.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, wpisal, dt_wpisu) "
               "VALUES (1001, 1, 5.0, 'u', '2026-04-22T12:00:00')")
    db.commit()
    # Editing sulfonowanie (etap 10) while analiza_koncowa (etap 11) has a pomiar → downstream exists.
    info = has_downstream_activity(db, ebr_id=100, etap_id=10)
    assert info["has_downstream"] is True
    assert any(s["etap_id"] == 11 and s["pomiary"] >= 1 for s in info["stages"])


def test_downstream_none_for_last_stage(db):
    """Last stage never has downstream."""
    info = has_downstream_activity(db, ebr_id=100, etap_id=11)
    assert info["has_downstream"] is False
    assert info["stages"] == []
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_edit_policy.py::test_downstream_detects_later_pomiar -v`
Expected: FAIL — `has_downstream_activity` not defined.

- [ ] **Step 3: Implement helper**

Append to `mbr/pipeline/edit_policy.py`:

```python
def has_downstream_activity(db: sqlite3.Connection, *, ebr_id: int, etap_id: int) -> dict:
    """Summarise activity in pipeline stages placed AFTER the given etap.

    Returns {"has_downstream": bool, "stages": [{"etap_id", "nazwa", "pomiary", "korekty"}, ...]}.
    Used by the inline banner that warns the laborant when editing a stage whose
    downstream measurements or corrections may need re-evaluation.
    """
    ref = db.execute(
        """SELECT pp.kolejnosc,
                  (SELECT m.produkt FROM mbr_templates m
                   JOIN ebr_batches b ON b.mbr_id = m.mbr_id
                   WHERE b.ebr_id = ?) AS produkt
           FROM produkt_pipeline pp
           WHERE pp.etap_id = ?
             AND pp.produkt = (SELECT m.produkt FROM mbr_templates m
                               JOIN ebr_batches b ON b.mbr_id = m.mbr_id
                               WHERE b.ebr_id = ?)""",
        (ebr_id, etap_id, ebr_id),
    ).fetchone()
    if ref is None:
        return {"has_downstream": False, "stages": []}

    rows = db.execute(
        """SELECT pp.etap_id, ea.nazwa,
                  (SELECT COUNT(*) FROM ebr_pomiar p
                   JOIN ebr_etap_sesja s ON s.id = p.sesja_id
                   WHERE s.ebr_id = ? AND s.etap_id = pp.etap_id
                     AND p.wartosc IS NOT NULL) AS pomiary,
                  (SELECT COUNT(*) FROM ebr_korekta_v2 k
                   JOIN ebr_etap_sesja s ON s.id = k.sesja_id
                   WHERE s.ebr_id = ? AND s.etap_id = pp.etap_id
                     AND k.ilosc IS NOT NULL) AS korekty
           FROM produkt_pipeline pp
           JOIN etapy_analityczne ea ON ea.id = pp.etap_id
           WHERE pp.produkt = ? AND pp.kolejnosc > ?
           ORDER BY pp.kolejnosc""",
        (ebr_id, ebr_id, ref["produkt"], ref["kolejnosc"]),
    ).fetchall()

    stages = [{"etap_id": r["etap_id"], "nazwa": r["nazwa"],
               "pomiary": r["pomiary"], "korekty": r["korekty"]}
              for r in rows if r["pomiary"] > 0 or r["korekty"] > 0]
    return {"has_downstream": bool(stages), "stages": stages}
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_edit_policy.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/pipeline/edit_policy.py tests/test_edit_policy.py
git commit -m "feat(pipeline): has_downstream_activity summary helper"
```

---

## Task 3: Loosen PUT /korekta guard

**Files:**
- Modify: `mbr/pipeline/lab_routes.py:378-386`
- Test:  `tests/test_lab_routes_reedit.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_lab_routes_reedit.py
import json
import sqlite3
import pytest

from mbr.app import create_app
from mbr.models import init_mbr_tables


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("MBR_SECRET_KEY", "x" * 32)
    monkeypatch.setenv("MBR_DB_PATH", str(tmp_path / "test.sqlite"))
    app = create_app()
    # Seed
    with app.app_context():
        from mbr.db import get_db
        db = get_db()
        db.execute("INSERT INTO mbr_templates (mbr_id, produkt, wersja, active, etapy_json, surowce_json) "
                   "VALUES (1, 'Chegina_K7', 1, 1, '[]', '[]')")
        db.execute("INSERT INTO ebr_batches (ebr_id, mbr_id, nr_partii, status) VALUES (100, 1, 'K7/T', 'open')")
        db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
                   "VALUES (10, 'sulfonowanie', 'Sulfonowanie', 'cykliczny')")
        db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
                   "VALUES (11, 'analiza_koncowa', 'Analiza końcowa', 'jednorazowy')")
        db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chegina_K7', 10, 1)")
        db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('Chegina_K7', 11, 2)")
        db.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status) "
                   "VALUES (1000, 100, 10, 1, 'zamkniety')")
        db.execute("INSERT INTO etap_korekty_katalog (id, etap_id, substancja, jednostka) "
                   "VALUES (5, 10, 'Kwas cytrynowy', 'kg')")
        db.execute("INSERT INTO workers (login, imie, nazwisko, rola, haslo_hash, aktywny) "
                   "VALUES ('lab1', 'L', 'One', 'laborant', 'x', 1)")
        db.commit()
    yield app


@pytest.fixture
def client(app):
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["user"] = {"login": "lab1", "rola": "laborant"}
        yield c


def test_put_korekta_accepts_closed_sesja_when_batch_open(client):
    resp = client.put("/api/pipeline/lab/ebr/100/korekta",
                      json={"etap_id": 10, "substancja": "Kwas cytrynowy", "ilosc": 12.5})
    assert resp.status_code == 200, resp.get_json()
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_lab_routes_reedit.py::test_put_korekta_accepts_closed_sesja_when_batch_open -v`
Expected: FAIL — returns 400 "no active session for this etap" (old guard hits zamkniety).

- [ ] **Step 3: Replace guard in `lab_routes.py`**

Find the block at lines 378-386 matching:

```python
        sesja_row = db.execute(
            "SELECT id FROM ebr_etap_sesja "
            "WHERE ebr_id=? AND etap_id=? "
            "  AND status IN ('nierozpoczety', 'w_trakcie') "
            "ORDER BY runda DESC, id DESC LIMIT 1",
            (ebr_id, etap_id),
        ).fetchone()
        if not sesja_row:
            return jsonify({"error": "no active session for this etap"}), 400
```

Replace with:

```python
        from mbr.pipeline.edit_policy import is_sesja_editable

        # Pick the latest sesja for this etap (active first, else the most recent closed one).
        sesja_row = db.execute(
            "SELECT id FROM ebr_etap_sesja "
            "WHERE ebr_id=? AND etap_id=? "
            "ORDER BY CASE status WHEN 'w_trakcie' THEN 0 "
            "                    WHEN 'nierozpoczety' THEN 1 "
            "                    ELSE 2 END, "
            "         runda DESC, id DESC LIMIT 1",
            (ebr_id, etap_id),
        ).fetchone()
        if not sesja_row:
            return jsonify({"error": "no session for this etap"}), 400
        if not is_sesja_editable(db, ebr_id=ebr_id, sesja_id=sesja_row["id"]):
            return jsonify({"error": "sesja is locked — batch closed and this is not the last stage"}), 403
```

- [ ] **Step 4: Run test**

Run: `pytest tests/test_lab_routes_reedit.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/pipeline/lab_routes.py tests/test_lab_routes_reedit.py
git commit -m "feat(lab): allow PUT /korekta to edit closed sesja while batch open"
```

---

## Task 4: Add guard to POST /pomiary + POST /korekta

**Files:**
- Modify: `mbr/pipeline/lab_routes.py` — POST /pomiary (line ~175), POST /korekta (line ~307)
- Modify: `tests/test_lab_routes_reedit.py`

- [ ] **Step 1: Add failing tests**

```python
# append to tests/test_lab_routes_reedit.py

def test_post_pomiary_rejected_closed_batch_earlier_stage(client, app):
    with app.app_context():
        from mbr.db import get_db
        db = get_db()
        db.execute("UPDATE ebr_batches SET status='completed' WHERE ebr_id=100")
        db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (1, 'x', 'X', 'bezposredni')")
        db.commit()
    resp = client.post("/api/pipeline/lab/ebr/100/etap/10/pomiary",
                       json={"sesja_id": 1000, "pomiary": [{"parametr_id": 1, "wartosc": 5}]})
    assert resp.status_code == 403, resp.get_json()


def test_post_pomiary_accepted_open_batch(client):
    """Regression: open batch still accepts pomiary on the active stage's sesja."""
    # Reuse the open-batch fixture; insert a param first.
    with client.application.app_context():
        from mbr.db import get_db
        db = get_db()
        db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (2, 'y', 'Y', 'bezposredni')")
        db.commit()
    resp = client.post("/api/pipeline/lab/ebr/100/etap/10/pomiary",
                       json={"sesja_id": 1000, "pomiary": [{"parametr_id": 2, "wartosc": 3}]})
    assert resp.status_code == 200
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_lab_routes_reedit.py::test_post_pomiary_rejected_closed_batch_earlier_stage -v`
Expected: FAIL — current POST /pomiary has no guard, would return 200.

- [ ] **Step 3: Add guard to POST /pomiary**

In `lab_routes.py`, inside `lab_save_pomiary` just after the `ebr` existence check (after line 193), add:

```python
        from mbr.pipeline.edit_policy import is_sesja_editable
        if not is_sesja_editable(db, ebr_id=ebr_id, sesja_id=sesja_id):
            return jsonify({"error": "sesja is locked — batch closed and this is not the last stage"}), 403
```

- [ ] **Step 4: Add guard to POST /korekta**

In `lab_create_korekta` (around line 307), after resolving `sesja_id` and before `create_ebr_korekta` call, add:

```python
        from mbr.pipeline.edit_policy import is_sesja_editable
        if sesja_id and not is_sesja_editable(db, ebr_id=ebr_id, sesja_id=sesja_id):
            return jsonify({"error": "sesja is locked — batch closed and this is not the last stage"}), 403
```

- [ ] **Step 5: Run all tests**

Run: `pytest tests/test_lab_routes_reedit.py tests/test_edit_policy.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add mbr/pipeline/lab_routes.py tests/test_lab_routes_reedit.py
git commit -m "feat(lab): guard POST pomiary+korekta by edit policy"
```

---

## Task 5: Downstream summary endpoint

**Files:**
- Modify: `mbr/pipeline/lab_routes.py` (append)
- Modify: `tests/test_lab_routes_reedit.py`

- [ ] **Step 1: Failing test**

```python
def test_downstream_summary_endpoint(client, app):
    with app.app_context():
        from mbr.db import get_db
        db = get_db()
        db.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda, status) "
                   "VALUES (1001, 100, 11, 1, 'zamkniety')")
        db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (3, 'z', 'Z', 'bezposredni')")
        db.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, wpisal, dt_wpisu) "
                   "VALUES (1001, 3, 9.0, 'lab1', '2026-04-22T13:00:00')")
        db.commit()
    resp = client.get("/api/pipeline/lab/ebr/100/etap/10/downstream-summary")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["has_downstream"] is True
    assert any(s["etap_id"] == 11 for s in data["stages"])
```

- [ ] **Step 2: Run to verify 404**

Run: `pytest tests/test_lab_routes_reedit.py::test_downstream_summary_endpoint -v`
Expected: FAIL — endpoint missing (404).

- [ ] **Step 3: Add endpoint**

Append to `lab_routes.py`:

```python
# ---------------------------------------------------------------------------
# GET /api/pipeline/lab/ebr/<ebr_id>/etap/<etap_id>/downstream-summary
# Warning-banner data for reedit UX.
# ---------------------------------------------------------------------------

@pipeline_bp.route(
    "/api/pipeline/lab/ebr/<int:ebr_id>/etap/<int:etap_id>/downstream-summary",
    methods=["GET"],
)
@login_required
def lab_downstream_summary(ebr_id, etap_id):
    from mbr.pipeline.edit_policy import has_downstream_activity
    db = get_db()
    try:
        return jsonify(has_downstream_activity(db, ebr_id=ebr_id, etap_id=etap_id))
    finally:
        db.close()
```

- [ ] **Step 4: Run test**

Run: `pytest tests/test_lab_routes_reedit.py::test_downstream_summary_endpoint -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/pipeline/lab_routes.py tests/test_lab_routes_reedit.py
git commit -m "feat(lab): GET downstream-summary for reedit banner"
```

---

## Task 6: Sidebar — derive readonly from policy

**Files:**
- Modify: `mbr/templates/laborant/szarze_list.html:~957`

Context: currently `onclick="showPipelineStage(..., readonly)"` sends `readonly=true` whenever stage status is `'done'`. Under the new policy, we want `readonly=false` for all stages when batch is open, and only `false` for the last stage when batch is closed.

- [ ] **Step 1: Locate the stage-click template block**

Read lines 930-970 of `mbr/templates/laborant/szarze_list.html` first to confirm the current structure; the relevant condition is the ternary building `readonly_flag` on line ~957.

- [ ] **Step 2: Update condition**

Find in `szarze_list.html`:

```html
                 + '\', '
                 + (status === 'done' ? 'true' : 'false') + ')">'
```

Replace the `status === 'done'` check with:

```html
                 + '\', '
                 + (ebrStatus === 'open' ? 'false'
                    : (isLastStage ? 'false' : 'true')) + ')">'
```

And above this block, near where `status` is computed, add:

```javascript
                var isLastStage = (idx === stages.length - 1);
```

(`idx` is already the forEach index; `stages` is the array being rendered.)

- [ ] **Step 3: Smoke-test in browser**

```bash
MBR_SECRET_KEY=smoketest-key-32chars-padding-xxx python -m mbr.app &
```

Open `/laborant/szarze`, pick a K7 batch, click on a closed earlier stage. Expected: hero opens in EDIT mode (inputs not greyed out), not readonly.

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/szarze_list.html
git commit -m "feat(laborant): sidebar passes readonly per edit policy"
```

---

## Task 7: Hero — isReadonly uses policy

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html` (search for `isReadonly = ebrStatus !== 'open'`)

- [ ] **Step 1: Read current logic**

Locate the single line (~line 1286 per recon) that sets `isReadonly` based solely on `ebrStatus`.

- [ ] **Step 2: Replace with two-tier rule**

Find:

```javascript
var isReadonly = ebrStatus !== 'open';
```

Replace with:

```javascript
// Edit policy (see mbr/pipeline/edit_policy.py for the backend mirror).
// - batch open   → never readonly (laborant may edit any sesja)
// - batch closed → readonly everywhere except the last stage in pipeline
var isReadonly;
if (ebrStatus === 'open') {
    isReadonly = false;
} else {
    var activeKod = window._activePipelineStage;
    var lastKod = (etapy.length > 0) ? etapy[etapy.length - 1].sekcja_lab : null;
    isReadonly = !(activeKod && activeKod === lastKod);
}
```

- [ ] **Step 3: Manual verification**

Reopen the dev server, open a completed K7 batch. Navigate to earlier stages → readonly. Navigate to analiza_koncowa → editable.

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat(laborant): hero isReadonly derived from two-tier edit policy"
```

---

## Task 8: Reedit banner

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

Context: when the user opens a closed sesja in edit mode, show an amber banner at the top of the section area warning about downstream activity. The banner is dismissed on stage change.

- [ ] **Step 1: Locate `renderSections` entry point**

Search `_fast_entry_content.html` for the function that mounts section content (earlier we saw `renderSections()` being called from `showPipelineStage`).

- [ ] **Step 2: Add banner fetch + render**

At the start of the body rendering for a pipeline stage (after the header is inserted and before the first field block), insert:

```javascript
// Reedit banner: only shown when editing a zamkniety sesja.
(function renderReeditBanner() {
    var activeKod = window._activePipelineStage;
    var stage = etapy.find(function(e) { return e.sekcja_lab === activeKod; });
    if (!stage || stage.last_status !== 'zamkniety' || isReadonly) return;

    var banner = document.createElement('div');
    banner.className = 'reedit-banner';
    banner.textContent = 'Edytujesz zakończony etap. Ładowanie informacji o kolejnych etapach...';
    sectionsContainer.insertBefore(banner, sectionsContainer.firstChild);

    fetch('/api/pipeline/lab/ebr/' + ebrId + '/etap/' + stage.pipeline_etap_id + '/downstream-summary')
        .then(function(r) { return r.ok ? r.json() : null; })
        .then(function(data) {
            if (!data || !data.has_downstream) {
                banner.textContent = 'Edytujesz zakończony etap — zmiany zostaną zapisane i odnotowane w audycie.';
                return;
            }
            var parts = data.stages.map(function(s) {
                var bits = [];
                if (s.pomiary) bits.push(s.pomiary + ' pomiar.');
                if (s.korekty) bits.push(s.korekty + ' korekt.');
                return s.nazwa + ' (' + bits.join(', ') + ')';
            });
            banner.textContent = 'Edytujesz zakończony etap. Kolejne etapy już zawierają dane: '
                + parts.join('; ') + '. Nie zostaną automatycznie przeliczone.';
            banner.classList.add('reedit-banner-warn');
        });
})();
```

- [ ] **Step 3: CSS**

At the top of the `<style>` block in `_fast_entry_content.html`, add:

```css
.reedit-banner {
    margin: 8px 12px; padding: 10px 14px;
    border-left: 4px solid var(--accent, #c69a00);
    background: var(--surface-alt, #fff8e1);
    color: var(--text, #3a2f00);
    font-size: 12px; line-height: 1.4;
    border-radius: 4px;
}
.reedit-banner-warn {
    border-left-color: #c24a00;
    background: #fff1e0;
    color: #5a1d00;
}
```

- [ ] **Step 4: Smoke-test**

Browser: open K7 batch, complete sulfonowanie with a round that includes pomiary, advance to utlenienie. Go back to sulfonowanie — banner should appear with "Kolejne etapy już zawierają dane: Analiza po utlenianiu…".

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat(laborant): reedit banner warns when editing closed sesja"
```

---

## Task 9: Audit reedit writes

**Files:**
- Modify: `mbr/pipeline/models.py::save_pomiar` and `::upsert_ebr_korekta`
- Modify: `tests/test_edit_policy.py` (append audit check)

Context: pipeline `save_pomiar` and `upsert_ebr_korekta` currently do NOT audit-log at all (verified: `grep -n audit mbr/pipeline/models.py` returns nothing). To avoid broader scope creep, we log **only when** the target sesja has `status='zamkniety'` — i.e. a re-edit. First-time writes stay silent for now and can be added in a separate pass.

Use `audit.EVENT_EBR_WYNIK_UPDATED` (nearest existing constant — see `mbr/shared/audit.py:59`). `audit.log_event` needs either a Flask request context or an explicit `actors=[…]` list; since the pipeline write functions get called from routes that already have request context, we rely on that default. Tests must invoke through the Flask test client so request context is present.

- [ ] **Step 1: Failing test**

```python
# tests/test_lab_routes_reedit.py — append (test client gives Flask context)

def test_put_korekta_on_closed_sesja_emits_reedit_audit(client, app):
    resp = client.put("/api/pipeline/lab/ebr/100/korekta",
                      json={"etap_id": 10, "substancja": "Kwas cytrynowy", "ilosc": 7.5})
    assert resp.status_code == 200
    with app.app_context():
        from mbr.db import get_db
        db = get_db()
        row = db.execute(
            "SELECT payload_json FROM audit_log "
            "WHERE event_type = 'ebr.wynik.updated' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    import json as _j
    assert _j.loads(row["payload_json"]).get("reedit") == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_lab_routes_reedit.py::test_put_korekta_on_closed_sesja_emits_reedit_audit -v`
Expected: FAIL — no audit row emitted (pipeline writes currently don't log).

- [ ] **Step 3: Implement**

In `mbr/pipeline/models.py`, at top-of-file, add import (after existing imports):

```python
from mbr.shared import audit as _audit
```

Inside `save_pomiar` — at the end of the function, after the DB row is written (find the return statement or end of the logic), prepend:

```python
    _s = db.execute("SELECT ebr_id, status FROM ebr_etap_sesja WHERE id=?", (sesja_id,)).fetchone()
    if _s and _s["status"] == "zamkniety":
        _audit.log_event(
            _audit.EVENT_EBR_WYNIK_UPDATED,
            entity_type="ebr",
            entity_id=_s["ebr_id"],
            payload={"reedit": 1, "sesja_id": sesja_id,
                     "parametr_id": parametr_id, "wartosc": wartosc,
                     "source": "pipeline.save_pomiar"},
            db=db,
        )
```

Mirror the same block at the end of `upsert_ebr_korekta`, adjusted:

```python
    _s = db.execute("SELECT ebr_id, status FROM ebr_etap_sesja WHERE id=?", (sesja_id,)).fetchone()
    if _s and _s["status"] == "zamkniety":
        _audit.log_event(
            _audit.EVENT_EBR_WYNIK_UPDATED,
            entity_type="ebr",
            entity_id=_s["ebr_id"],
            payload={"reedit": 1, "sesja_id": sesja_id,
                     "korekta_typ_id": korekta_typ_id, "ilosc": ilosc,
                     "source": "pipeline.upsert_ebr_korekta"},
            db=db,
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_lab_routes_reedit.py tests/test_edit_policy.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/pipeline/models.py tests/test_lab_routes_reedit.py
git commit -m "feat(audit): log ebr.wynik.updated with reedit=1 for closed-sesja writes"
```

---

## Task 10: Full regression + smoke

- [ ] **Step 1: Run full suite**

Run: `pytest tests/ -q`
Expected: 939+ tests PASS (new tests bring total up; no existing test regresses).

- [ ] **Step 2: Manual smoke on open K7 batch**

Start a test batch, fill sulfonowanie, go to utlenienie, then back to sulfonowanie. Change a value. Expected:
- inputs not greyed out
- amber banner visible
- save succeeds; audit-history shows reedit=1

- [ ] **Step 3: Manual smoke on closed K7 batch**

Close a batch via przepompowanie. Navigate to sulfonowanie in hero. Expected:
- inputs greyed out, no banner
Navigate to analiza_koncowa. Expected:
- inputs editable, amber banner absent (no downstream for last stage)

- [ ] **Step 4: Commit**

If smoke uncovers minor CSS/UX tweaks, commit them with `chore(reedit): smoke fixes`.
