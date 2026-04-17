# Korekty persistence + sum field fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Per-field auto-save for correction panel values in Chegina_K7 szarża, plus readonly derived sum field. Manual overrides persist to `ebr_korekta_v2` immediately on blur; `woda + kwas = woda_całkowita` always reflects current components.

**Architecture:** Backend — new `upsert_ebr_korekta()` helper (manual SELECT → UPDATE-or-INSERT, no schema change) and new `PUT /api/pipeline/lab/ebr/<ebr_id>/korekta` endpoint. Frontend — replace sessionStorage-based FD system for correction fields with `onblur` auto-save to the new endpoint; `_pendingKorektaSaves` flushed before batch switches; sum field becomes `readonly`, always recomputed from components without guards.

**Tech Stack:** Flask + vanilla JS, SQLite, pytest with in-memory DB fixtures (pattern from `tests/test_pipeline_lab.py` + `tests/test_pipeline_models.py`).

**Dependencies:** All prior parametry SSOT + MVP PRs merged. `ebr_korekta_v2` table exists (no UNIQUE constraint on sesja_id+korekta_typ_id; we handle deduplication in the upsert function).

---

## File Structure

**Modify:**
- `mbr/pipeline/models.py` — add `upsert_ebr_korekta(db, sesja_id, korekta_typ_id, ilosc, ilosc_wyliczona, zalecil)`. Returns binding id. SELECT → UPDATE-or-INSERT based on (sesja_id, korekta_typ_id).
- `mbr/pipeline/lab_routes.py` — add `PUT /api/pipeline/lab/ebr/<int:ebr_id>/korekta` endpoint calling the helper. Resolves active sesja and korekta_typ_id server-side.
- `mbr/templates/laborant/_correction_panel.html` — replace FD for correction fields with `saveKorektaField(input)` on blur; sum field becomes `readonly`; simplify `recomputeStandTotal` (no guards, no FD).
- `mbr/templates/laborant/_fast_entry_content.html` — `loadBatch()` awaits pending korekta saves before fetching new batch data.

**Test:**
- `tests/test_pipeline_models.py` — add 4 tests for `upsert_ebr_korekta`.
- `tests/test_pipeline_lab.py` — add 6 tests for the PUT endpoint.

**Not touched:**
- `ebr_korekta_v2` schema — no migration. Deduplication is function-level via SELECT-then-UPDATE.
- Measurement save path (pomiary) — separate flow, unaffected.
- Formula evaluation (`resolve_formula_zmienne`) — unchanged.
- `FD` system as a whole — only removed for correction fields; pomiary may still use it.

---

## Spec reference

Full design: `docs/superpowers/specs/2026-04-17-korekty-persist-design.md`. This plan implements that design end-to-end.

---

## Task 1: Backend helper `upsert_ebr_korekta` — failing tests

**Files:**
- Modify: `tests/test_pipeline_models.py`

- [ ] **Step 1: Append tests**

Add to the end of `/Users/tbk/Desktop/lims-clean/tests/test_pipeline_models.py`:

```python


# ---------------------------------------------------------------------------
# upsert_ebr_korekta — auto-save persistent correction values
# ---------------------------------------------------------------------------

def _seed_korekta_fixture(db):
    """Seed a minimal K7-like pipeline with one etap + one korekta_typ + one open sesja."""
    db.execute(
        "INSERT OR IGNORE INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
        "VALUES (904, 'sulfonowanie_t', 'Sulfonowanie (test)', 'cykliczny')"
    )
    db.execute(
        "INSERT INTO etap_korekty_katalog "
        "(id, etap_id, substancja, jednostka, wykonawca, kolejnosc) "
        "VALUES (901, 904, 'Perhydrol 34%', 'kg', 'produkcja', 1)"
    )
    db.execute(
        "INSERT INTO etap_korekty_katalog "
        "(id, etap_id, substancja, jednostka, wykonawca, kolejnosc) "
        "VALUES (902, 904, 'Woda', 'kg', 'produkcja', 2)"
    )
    # Need an ebr_batch for FK on ebr_etap_sesja. Use existing mbr_templates.
    mbr_id = db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status) "
        "VALUES ('TESTPROD', 1, 'active') RETURNING mbr_id"
    ).fetchone()["mbr_id"]
    ebr_id = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, typ) "
        "VALUES (?, 'B-TEST-1', '1/TEST', datetime('now'), 'szarza') "
        "RETURNING ebr_id",
        (mbr_id,),
    ).fetchone()["ebr_id"]
    from mbr.pipeline.models import create_sesja
    sesja_id = create_sesja(db, ebr_id, 904, runda=1, laborant="lab1")
    db.commit()
    return {"ebr_id": ebr_id, "etap_id": 904, "sesja_id": sesja_id,
            "perhydrol_typ_id": 901, "woda_typ_id": 902}


def test_upsert_korekta_inserts_when_missing(db):
    from mbr.pipeline.models import upsert_ebr_korekta, list_ebr_korekty
    s = _seed_korekta_fixture(db)
    kid = upsert_ebr_korekta(
        db, sesja_id=s["sesja_id"], korekta_typ_id=s["perhydrol_typ_id"],
        ilosc=12.5, ilosc_wyliczona=11.8, zalecil="lab1",
    )
    assert isinstance(kid, int) and kid > 0
    rows = list_ebr_korekty(db, s["sesja_id"])
    perhydrol = [r for r in rows if r["korekta_typ_id"] == s["perhydrol_typ_id"]]
    assert len(perhydrol) == 1
    assert perhydrol[0]["ilosc"] == 12.5


def test_upsert_korekta_updates_when_present(db):
    """Calling twice for the same (sesja, korekta_typ) must not duplicate rows."""
    from mbr.pipeline.models import upsert_ebr_korekta
    s = _seed_korekta_fixture(db)
    kid1 = upsert_ebr_korekta(db, s["sesja_id"], s["perhydrol_typ_id"], 10.0, 11.8, "lab1")
    kid2 = upsert_ebr_korekta(db, s["sesja_id"], s["perhydrol_typ_id"], 15.5, 11.8, "lab1")
    # Same row id returned; count stays at 1
    assert kid1 == kid2
    n = db.execute(
        "SELECT COUNT(*) AS n FROM ebr_korekta_v2 "
        "WHERE sesja_id=? AND korekta_typ_id=?",
        (s["sesja_id"], s["perhydrol_typ_id"]),
    ).fetchone()["n"]
    assert n == 1
    # Second value wins
    row = db.execute(
        "SELECT ilosc FROM ebr_korekta_v2 WHERE id=?", (kid1,)
    ).fetchone()
    assert row["ilosc"] == 15.5


def test_upsert_korekta_ilosc_none_clears_manual(db):
    """Passing ilosc=None after a value sets ilosc back to NULL (formula wins again)."""
    from mbr.pipeline.models import upsert_ebr_korekta
    s = _seed_korekta_fixture(db)
    upsert_ebr_korekta(db, s["sesja_id"], s["perhydrol_typ_id"], 12.5, 11.8, "lab1")
    upsert_ebr_korekta(db, s["sesja_id"], s["perhydrol_typ_id"], None, 11.8, "lab1")
    row = db.execute(
        "SELECT ilosc, ilosc_wyliczona FROM ebr_korekta_v2 "
        "WHERE sesja_id=? AND korekta_typ_id=?",
        (s["sesja_id"], s["perhydrol_typ_id"]),
    ).fetchone()
    assert row["ilosc"] is None
    assert row["ilosc_wyliczona"] == 11.8


def test_upsert_korekta_different_sesje_separate_rows(db):
    """Two sesje for the same etap → two separate korekta rows (one per sesja)."""
    from mbr.pipeline.models import upsert_ebr_korekta, create_sesja
    s = _seed_korekta_fixture(db)
    sesja2_id = create_sesja(db, s["ebr_id"], s["etap_id"], runda=2, laborant="lab1")
    db.commit()
    upsert_ebr_korekta(db, s["sesja_id"], s["perhydrol_typ_id"], 10.0, None, "lab1")
    upsert_ebr_korekta(db, sesja2_id, s["perhydrol_typ_id"], 15.0, None, "lab1")
    rows = db.execute(
        "SELECT sesja_id, ilosc FROM ebr_korekta_v2 "
        "WHERE korekta_typ_id=? ORDER BY sesja_id",
        (s["perhydrol_typ_id"],),
    ).fetchall()
    assert len(rows) == 2
    vals = {r["sesja_id"]: r["ilosc"] for r in rows}
    assert vals[s["sesja_id"]] == 10.0
    assert vals[sesja2_id] == 15.0
```

- [ ] **Step 2: Run, expect fail**

Run: `pytest tests/test_pipeline_models.py::test_upsert_korekta_inserts_when_missing -v`
Expected: FAIL — `ImportError: cannot import name 'upsert_ebr_korekta' from 'mbr.pipeline.models'`.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_pipeline_models.py
git commit -m "test: upsert_ebr_korekta — persist manual correction values (failing)"
```

---

## Task 2: Implement `upsert_ebr_korekta`

**Files:**
- Modify: `mbr/pipeline/models.py` — add function below `create_ebr_korekta`.

- [ ] **Step 1: Add function**

Open `/Users/tbk/Desktop/lims-clean/mbr/pipeline/models.py`. Find the `create_ebr_korekta` function (around line 667-683). Add immediately AFTER it, BEFORE `list_ebr_korekty` (around line 686):

```python
def upsert_ebr_korekta(
    db: sqlite3.Connection,
    sesja_id: int,
    korekta_typ_id: int,
    ilosc: float | None,
    ilosc_wyliczona: float | None,
    zalecil: str | None,
) -> int:
    """Insert-or-update a correction value for (sesja_id, korekta_typ_id).

    Used by the per-field auto-save flow: each blur-triggered save in the
    correction panel calls this. Idempotent for the same pair — second call
    updates the existing row rather than inserting a duplicate.

    ilosc = None is an explicit "clear manual override" signal (formula
    suggestion can show again in the UI). ilosc_wyliczona is always written
    so we retain a record of what the formula suggested at each save.
    """
    now = datetime.now().isoformat(timespec="seconds")
    existing = db.execute(
        "SELECT id FROM ebr_korekta_v2 "
        "WHERE sesja_id=? AND korekta_typ_id=? "
        "ORDER BY id DESC LIMIT 1",
        (sesja_id, korekta_typ_id),
    ).fetchone()
    if existing:
        db.execute(
            "UPDATE ebr_korekta_v2 "
            "SET ilosc=?, ilosc_wyliczona=?, zalecil=?, dt_zalecenia=? "
            "WHERE id=?",
            (ilosc, ilosc_wyliczona, zalecil, now, existing["id"]),
        )
        return existing["id"]
    cur = db.execute(
        """INSERT INTO ebr_korekta_v2
               (sesja_id, korekta_typ_id, ilosc, ilosc_wyliczona, zalecil, dt_zalecenia)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (sesja_id, korekta_typ_id, ilosc, ilosc_wyliczona, zalecil, now),
    )
    return cur.lastrowid
```

- [ ] **Step 2: Run tests, expect pass**

Run: `pytest tests/test_pipeline_models.py -k upsert_korekta -v`
Expected: all 4 tests PASS.

- [ ] **Step 3: Full suite**

Run: `pytest -q`
Expected: baseline + 4 new = 577 passed (or current+4), zero regressions.

- [ ] **Step 4: Commit**

```bash
git add mbr/pipeline/models.py
git commit -m "feat(pipeline): upsert_ebr_korekta for per-field auto-save"
```

---

## Task 3: PUT endpoint — failing tests

**Files:**
- Modify: `tests/test_pipeline_lab.py`

- [ ] **Step 1: Check existing test fixture pattern**

Inspect the top of `/Users/tbk/Desktop/lims-clean/tests/test_pipeline_lab.py` to understand fixtures (`db` fixture, monkeypatched `db_session` for Flask). The pattern matches `tests/test_pipeline_models.py` plus a `client` fixture via `create_app()`.

- [ ] **Step 2: Append tests**

Add at the end of `/Users/tbk/Desktop/lims-clean/tests/test_pipeline_lab.py`:

```python


# ---------------------------------------------------------------------------
# PUT /api/pipeline/lab/ebr/<ebr_id>/korekta — per-field auto-save
# ---------------------------------------------------------------------------

def _seed_pipeline_fixture_for_korekta(db):
    """Seed etap + korekta catalog + mbr + ebr + open sesja.
    Returns dict with ids used by the tests."""
    db.execute(
        "INSERT OR IGNORE INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
        "VALUES (910, 'sulfon_lab_t', 'Sulfonowanie (test)', 'cykliczny')"
    )
    db.execute(
        "INSERT INTO etap_korekty_katalog "
        "(id, etap_id, substancja, jednostka, wykonawca, kolejnosc) "
        "VALUES (910, 910, 'Perhydrol 34%', 'kg', 'produkcja', 1)"
    )
    mbr_id = db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status) "
        "VALUES ('TESTPROD', 1, 'active') RETURNING mbr_id"
    ).fetchone()["mbr_id"]
    ebr_id = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, typ) "
        "VALUES (?, 'B-KOR-1', '1/KOR', datetime('now'), 'szarza') "
        "RETURNING ebr_id",
        (mbr_id,),
    ).fetchone()["ebr_id"]
    from mbr.pipeline.models import create_sesja
    sesja_id = create_sesja(db, ebr_id, 910, runda=1, laborant="lab1")
    db.commit()
    return {"ebr_id": ebr_id, "etap_id": 910, "sesja_id": sesja_id,
            "perhydrol_typ_id": 910}


def test_put_korekta_creates_new_row(client, db):
    s = _seed_pipeline_fixture_for_korekta(db)
    resp = client.put(
        f"/api/pipeline/lab/ebr/{s['ebr_id']}/korekta",
        json={"etap_id": s["etap_id"], "substancja": "Perhydrol 34%",
              "ilosc": 12.5, "ilosc_wyliczona": 11.8},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["sesja_id"] == s["sesja_id"]
    assert data["korekta_typ_id"] == s["perhydrol_typ_id"]
    assert data["ilosc"] == 12.5
    assert data["ilosc_wyliczona"] == 11.8


def test_put_korekta_updates_existing(client, db):
    s = _seed_pipeline_fixture_for_korekta(db)
    url = f"/api/pipeline/lab/ebr/{s['ebr_id']}/korekta"
    body = {"etap_id": s["etap_id"], "substancja": "Perhydrol 34%",
            "ilosc_wyliczona": 11.8}
    client.put(url, json={**body, "ilosc": 10.0})
    client.put(url, json={**body, "ilosc": 15.5})
    n = db.execute(
        "SELECT COUNT(*) AS n FROM ebr_korekta_v2 "
        "WHERE sesja_id=? AND korekta_typ_id=?",
        (s["sesja_id"], s["perhydrol_typ_id"]),
    ).fetchone()["n"]
    assert n == 1


def test_put_korekta_ilosc_null_clears_manual(client, db):
    s = _seed_pipeline_fixture_for_korekta(db)
    url = f"/api/pipeline/lab/ebr/{s['ebr_id']}/korekta"
    body = {"etap_id": s["etap_id"], "substancja": "Perhydrol 34%",
            "ilosc_wyliczona": 11.8}
    client.put(url, json={**body, "ilosc": 12.5})
    client.put(url, json={**body, "ilosc": None})
    row = db.execute(
        "SELECT ilosc FROM ebr_korekta_v2 "
        "WHERE sesja_id=? AND korekta_typ_id=?",
        (s["sesja_id"], s["perhydrol_typ_id"]),
    ).fetchone()
    assert row["ilosc"] is None


def test_put_korekta_unknown_substancja_returns_404(client, db):
    s = _seed_pipeline_fixture_for_korekta(db)
    resp = client.put(
        f"/api/pipeline/lab/ebr/{s['ebr_id']}/korekta",
        json={"etap_id": s["etap_id"], "substancja": "NieMaTakiej",
              "ilosc": 1.0},
    )
    assert resp.status_code == 404


def test_put_korekta_missing_fields_returns_400(client, db):
    s = _seed_pipeline_fixture_for_korekta(db)
    resp = client.put(
        f"/api/pipeline/lab/ebr/{s['ebr_id']}/korekta",
        json={"etap_id": s["etap_id"]},  # substancja + ilosc missing
    )
    assert resp.status_code == 400


def test_put_korekta_attribution_per_batch(client, db):
    """Two batches — save for batch 1, no row appears for batch 2."""
    s1 = _seed_pipeline_fixture_for_korekta(db)
    # Second batch sharing the same etap+substancja catalog
    mbr2_id = db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status) "
        "VALUES ('TESTPROD2', 1, 'active') RETURNING mbr_id"
    ).fetchone()["mbr_id"]
    ebr2_id = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, typ) "
        "VALUES (?, 'B-KOR-2', '2/KOR', datetime('now'), 'szarza') "
        "RETURNING ebr_id",
        (mbr2_id,),
    ).fetchone()["ebr_id"]
    from mbr.pipeline.models import create_sesja
    sesja2_id = create_sesja(db, ebr2_id, s1["etap_id"], runda=1, laborant="lab1")
    db.commit()

    client.put(
        f"/api/pipeline/lab/ebr/{s1['ebr_id']}/korekta",
        json={"etap_id": s1["etap_id"], "substancja": "Perhydrol 34%",
              "ilosc": 42.0, "ilosc_wyliczona": 40.0},
    )
    # Batch 1 has row, batch 2 does not
    b1 = db.execute(
        "SELECT ilosc FROM ebr_korekta_v2 WHERE sesja_id=?", (s1["sesja_id"],)
    ).fetchone()
    b2 = db.execute(
        "SELECT ilosc FROM ebr_korekta_v2 WHERE sesja_id=?", (sesja2_id,)
    ).fetchone()
    assert b1 is not None
    assert b1["ilosc"] == 42.0
    assert b2 is None
```

- [ ] **Step 3: Run, expect fail**

Run: `pytest tests/test_pipeline_lab.py -k put_korekta -v`
Expected: all 6 tests FAIL with `404 Not Found` (endpoint doesn't exist yet).

- [ ] **Step 4: Commit failing tests**

```bash
git add tests/test_pipeline_lab.py
git commit -m "test: PUT /api/pipeline/lab/ebr/<id>/korekta (failing)"
```

---

## Task 4: Implement PUT endpoint

**Files:**
- Modify: `mbr/pipeline/lab_routes.py`

- [ ] **Step 1: Read existing POST handler to match conventions**

Read `/Users/tbk/Desktop/lims-clean/mbr/pipeline/lab_routes.py` lines 300-345 — the existing `POST /api/pipeline/lab/ebr/<ebr_id>/korekta` endpoint. Note the session-resolution logic, auth decorator, error shapes.

- [ ] **Step 2: Add PUT endpoint**

In `/Users/tbk/Desktop/lims-clean/mbr/pipeline/lab_routes.py`, add the following new route. Place it immediately after the existing `POST /api/pipeline/lab/ebr/<ebr_id>/korekta` handler (so related endpoints stay adjacent):

```python
@pipeline_bp.route("/api/pipeline/lab/ebr/<int:ebr_id>/korekta", methods=["PUT"])
@login_required
def lab_upsert_ebr_korekta(ebr_id):
    """Per-field auto-save for correction values.

    Body: {etap_id, substancja, ilosc, ilosc_wyliczona?}.
    Resolves the active sesja and the korekta_typ_id, then calls
    pm.upsert_ebr_korekta.
    """
    data = request.get_json(silent=True) or {}
    etap_id = data.get("etap_id")
    substancja = (data.get("substancja") or "").strip()
    if not etap_id or not substancja or "ilosc" not in data:
        return jsonify({"error": "etap_id, substancja, ilosc are required"}), 400

    ilosc = data.get("ilosc")
    ilosc_wyliczona = data.get("ilosc_wyliczona")
    zalecil = session.get("user", {}).get("login")

    db = get_db()
    try:
        # Find active session (nierozpoczety / w_trakcie) for (ebr_id, etap_id) — latest runda
        sesja_row = db.execute(
            "SELECT id FROM ebr_etap_sesja "
            "WHERE ebr_id=? AND etap_id=? "
            "  AND status IN ('nierozpoczety', 'w_trakcie') "
            "ORDER BY runda DESC, id DESC LIMIT 1",
            (ebr_id, etap_id),
        ).fetchone()
        if not sesja_row:
            return jsonify({"error": "no active session for this etap"}), 400

        # Resolve korekta_typ_id from etap_korekty_katalog
        katalog_row = db.execute(
            "SELECT id FROM etap_korekty_katalog "
            "WHERE etap_id=? AND substancja=?",
            (etap_id, substancja),
        ).fetchone()
        if not katalog_row:
            return jsonify({
                "error": f"substancja '{substancja}' not in korekty catalog for etap {etap_id}"
            }), 404

        kid = pm.upsert_ebr_korekta(
            db,
            sesja_id=sesja_row["id"],
            korekta_typ_id=katalog_row["id"],
            ilosc=ilosc,
            ilosc_wyliczona=ilosc_wyliczona,
            zalecil=zalecil,
        )
        db.commit()

        row = db.execute(
            "SELECT id, sesja_id, korekta_typ_id, ilosc, ilosc_wyliczona "
            "FROM ebr_korekta_v2 WHERE id=?",
            (kid,),
        ).fetchone()
        return jsonify({
            "ok": True,
            "id": row["id"],
            "sesja_id": row["sesja_id"],
            "korekta_typ_id": row["korekta_typ_id"],
            "ilosc": row["ilosc"],
            "ilosc_wyliczona": row["ilosc_wyliczona"],
        })
    finally:
        db.close()
```

Confirm `pm` is already the imported alias for `mbr.pipeline.models` at the top of the file (grep the file for `import.*models as pm`). If not aliased, adapt to the import style in use.

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_pipeline_lab.py -k put_korekta -v`
Expected: all 6 tests PASS.

Run: `pytest -q`
Expected: full suite green, +6 from baseline.

- [ ] **Step 4: Commit**

```bash
git add mbr/pipeline/lab_routes.py
git commit -m "feat(lab-routes): PUT /api/pipeline/lab/ebr/<id>/korekta for auto-save"
```

---

## Task 5: Frontend `saveKorektaField` + removal of FD for correction fields

**Files:**
- Modify: `mbr/templates/laborant/_correction_panel.html`

- [ ] **Step 1: Survey current FD usage for corrections**

Run:
```bash
grep -n "FD\.\(set\|get\|fill\|clear\|del\)" mbr/templates/laborant/_correction_panel.html | head -40
```
Note which lines reference `corr-manual-*`, `corr-total-*`, and related correction-field ids. Our changes touch only those.

- [ ] **Step 2: Add `saveKorektaField` + `_pendingKorektaSaves` state**

In `/Users/tbk/Desktop/lims-clean/mbr/templates/laborant/_correction_panel.html`, find the `<script>` block near the top of the JS (search for the declaration of `FD` object — the first `function FD` or `var FD`). **Immediately after** the FD declaration, insert:

```javascript
// ═══ Per-field auto-save for correction values ═══
// Pending fetches (Promise objects). loadBatch() awaits these before
// switching batches to prevent lost in-flight saves.
window._pendingKorektaSaves = window._pendingKorektaSaves || [];

function saveKorektaField(input) {
  var ebrId = parseInt(input.dataset.ebrId, 10);
  var etapId = parseInt(input.dataset.etapId, 10);
  var substancja = input.dataset.substancja;
  if (!ebrId || !etapId || !substancja) {
    console.warn('saveKorektaField: missing data attrs on input', input);
    return Promise.resolve();
  }

  var raw = (input.value || '').trim().replace(',', '.');
  var ilosc = raw === '' ? null : parseFloat(raw);
  if (ilosc !== null && isNaN(ilosc)) {
    // unparseable input — ignore for now, don't save garbage
    return Promise.resolve();
  }
  var suggested = parseFloat(input.dataset.suggested);
  var ilosc_wyliczona = isFinite(suggested) ? suggested : null;

  input.classList.remove('corr-error', 'corr-saved');
  input.classList.add('corr-saving');

  var promise = fetch('/api/pipeline/lab/ebr/' + ebrId + '/korekta', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      etap_id: etapId,
      substancja: substancja,
      ilosc: ilosc,
      ilosc_wyliczona: ilosc_wyliczona,
    }),
  }).then(function(r) {
    input.classList.remove('corr-saving');
    if (!r.ok) {
      input.classList.add('corr-error');
      throw new Error('save failed: ' + r.status);
    }
    input.classList.add('corr-saved');
    setTimeout(function() { input.classList.remove('corr-saved'); }, 800);
    return r.json();
  }).catch(function(e) {
    input.classList.remove('corr-saving');
    input.classList.add('corr-error');
    console.error('saveKorektaField error:', e);
  });

  window._pendingKorektaSaves.push(promise);
  var cleanup = function() {
    var idx = window._pendingKorektaSaves.indexOf(promise);
    if (idx >= 0) window._pendingKorektaSaves.splice(idx, 1);
  };
  promise.then(cleanup, cleanup);
  return promise;
}
```

- [ ] **Step 3: Add CSS for visual feedback**

At the end of the `<style>` block in `_correction_panel.html` (search for the existing `corr-*` styles; append a new rule block):

```css
/* Auto-save feedback */
.corr-field-input.corr-saving { outline: 2px solid var(--orange, #f59e0b); }
.corr-field-input.corr-saved { outline: 2px solid var(--green, #16a34a); transition: outline-color 0.4s ease-out; }
.corr-field-input.corr-error { outline: 2px solid var(--red, #dc2626); }
```

If the template does not have a dedicated `<style>` block, add a `<style>` block at the top of the file with just these rules.

- [ ] **Step 4: Wire inputs to saveKorektaField + remove FD for correction fields**

Find the render code for the correction inputs (search for `corr-manual-woda` / `corr-manual-kwas` / `corr-manual-perhydrol` and the `FD.set` calls in their `oninput` / `onblur`). There are two patterns to update:

**Pattern A — manual-override fields (Woda, Kwas, Perhydrol, Siarczyn, …):**

Before (search for this shape, current lines ~180-189 and ~700-710):

```javascript
'<input id="corr-manual-' + subst + '-' + sekcja + '" ' +
'class="corr-field-input" type="text" inputmode="decimal"' +
' data-sekcja="' + sekcja + '"' +
' oninput="FD.set(this.id,this.value);FD.del(\\"corr-total-woda-' + sekcja + '\\");recomputeStandTotal(\\"' + sekcja + '\\")">'
```

After — add ebr/etap/substancja data-attrs, drop FD.set and the FD.del helper, add `onblur="saveKorektaField(this)"`. The recomputeStandTotal call stays on `oninput` so the sum field updates live; the save happens on blur.

```javascript
'<input id="corr-manual-' + subst + '-' + sekcja + '" ' +
'class="corr-field-input" type="text" inputmode="decimal"' +
' data-sekcja="' + sekcja + '"' +
' data-ebr-id="' + ebrId + '"' +
' data-etap-id="' + etapId + '"' +
' data-substancja="' + esc(substOryginal) + '"' +
' data-suggested="' + (suggestedVal != null ? suggestedVal : '') + '"' +
' oninput="recomputeStandTotal(\\"' + sekcja + '\\")"' +
' onblur="saveKorektaField(this)">'
```

Where `ebrId`, `etapId`, `substOryginal`, and `suggestedVal` are already available in the surrounding render context (verify by reading the function containing these lines — if variable names differ, adapt to match the code you find).

**Pattern B — any `FD.fill(...)` calls targeting `corr-manual-*` or `corr-total-*` inputs in the render/recompute functions:**

These previously restored drafts from sessionStorage. Now the DB is authoritative — the backend render path (which populates `input.value` from `ebr_korekta_v2.ilosc` when present, else formula suggestion) replaces this. Delete the `FD.fill(wodaManEl.id, …)`, `FD.fill(kwasManEl.id, …)`, and similar calls that target `corr-manual-*` or `corr-total-*`. Leave FD alone for non-correction fields if any.

Confirmation grep after edits:
```bash
grep -n "FD\.\(set\|get\|fill\|del\).*corr-\(manual\|total\)" mbr/templates/laborant/_correction_panel.html
```
Expected: zero matches.

- [ ] **Step 5: Template parse + full suite**

Run: `python3 -c "from mbr.app import create_app; create_app(); print('OK')"` → expect `OK`.
Run: `pytest -q` → expect full suite still green (template-only change, no test changes).

- [ ] **Step 6: Commit**

```bash
git add mbr/templates/laborant/_correction_panel.html
git commit -m "feat(corrections): per-field auto-save on blur (PUT /api/pipeline/lab/.../korekta)"
```

---

## Task 6: Sum field readonly + simplify `recomputeStandTotal`

**Files:**
- Modify: `mbr/templates/laborant/_correction_panel.html`

- [ ] **Step 1: Make total input readonly**

Find the total input render (search for `corr-total-woda`). Current shape (current line ~187):

```javascript
'<input id="corr-total-woda-' + sekcja + '" class="corr-field-input" type="text" inputmode="decimal"' +
' oninput="FD.set(this.id,this.value);">'
```

Replace with:

```javascript
'<input id="corr-total-woda-' + sekcja + '" class="corr-field-input corr-total-derived" ' +
'type="text" readonly tabindex="-1" title="Suma Woda + Kwas cytrynowy (tylko odczyt)">'
```

`readonly` disables typing. `tabindex="-1"` removes from tab order. Hover tooltip explains why.

- [ ] **Step 2: Add CSS marker for readonly total**

Append to the correction-panel `<style>` block:

```css
.corr-field-input.corr-total-derived { background: var(--surface-alt, #f7f7f7); color: var(--text-dim, #666); cursor: not-allowed; }
```

- [ ] **Step 3: Simplify `recomputeStandTotal`**

Find `function recomputeStandTotal(sekcja)` (around line 293). Replace the entire function body with:

```javascript
function recomputeStandTotal(sekcja) {
  var wodaEl = document.getElementById('corr-manual-woda-' + sekcja);
  var kwasEl = document.getElementById('corr-manual-kwas-' + sekcja);
  var totalEl = document.getElementById('corr-total-woda-' + sekcja);
  if (!totalEl) return;
  function parseNum(el) {
    if (!el) return 0;
    var raw = (el.value || '').trim().replace(',', '.');
    var n = parseFloat(raw);
    return isFinite(n) ? n : 0;
  }
  var total = parseNum(wodaEl) + parseNum(kwasEl);
  totalEl.value = total > 0 ? total.toFixed(1).replace('.', ',') : '';
}
```

No guard (`if (FD.get(totalEl.id) !== null) return;`). No FD usage. No partial recompute logic. Always writes the fresh sum.

- [ ] **Step 4: Verify no stale FD calls remain for totals**

Run:
```bash
grep -n "FD\.\(set\|get\|del\|fill\).*corr-total-woda" mbr/templates/laborant/_correction_panel.html
```
Expected: zero matches.

- [ ] **Step 5: Verify template + tests**

Run: `python3 -c "from mbr.app import create_app; create_app(); print('OK')"` → `OK`.
Run: `pytest -q` → green.

- [ ] **Step 6: Commit**

```bash
git add mbr/templates/laborant/_correction_panel.html
git commit -m "feat(corrections): sum field (woda całkowita) readonly + guard-free recompute"
```

---

## Task 7: `loadBatch` flushes pending korekta saves

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Find `loadBatch` function**

In `/Users/tbk/Desktop/lims-clean/mbr/templates/laborant/_fast_entry_content.html`, search:
```bash
grep -n "^function loadBatch\|^async function loadBatch" mbr/templates/laborant/_fast_entry_content.html
```

- [ ] **Step 2: Prepend flush-pending block**

At the VERY TOP of the `loadBatch(ebrId, ...)` function body (before any existing code), insert:

```javascript
  // Flush any in-flight correction-field saves before we swap batches.
  // Ensures every saveKorektaField PUT lands in the DB for the CURRENT batch
  // before the UI renders another batch's data.
  if (window._pendingKorektaSaves && window._pendingKorektaSaves.length > 0) {
    try { await Promise.allSettled(window._pendingKorektaSaves.slice()); } catch (e) { /* ignore */ }
  }
```

If `loadBatch` is declared as `function loadBatch(` (synchronous), change it to `async function loadBatch(` so the `await` works. Double-check all callers of `loadBatch` still work — the common pattern (`loadBatch(id)`, `loadBatch(id).then(...)`, `if (typeof loadBatch === 'function') loadBatch(ebrId)`) remains compatible because `async function` returns a Promise.

- [ ] **Step 3: Verify template + tests**

Run: `python3 -c "from mbr.app import create_app; create_app(); print('OK')"` → `OK`.
Run: `pytest -q` → green.

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat(corrections): loadBatch awaits pending korekta saves before switch"
```

---

## Task 8: Manual smoke-test on real app

**Files:**
- No code changes.

- [ ] **Step 1: Restart dev server**

```bash
pkill -f "python -m mbr.app" 2>/dev/null || true
python -m mbr.app &
sleep 2
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:5001/
```

Expected: `HTTP 302` (redirect to login).

- [ ] **Step 2: Walk the smoke checklist**

Log in as lab role, open or create a Chegina_K7 szarża. Walk through:

1. Enter a measurement that feeds a formula (e.g. `so3` in sulfonowanie) → formula suggests Perhydrol 34% value.
2. In the correction panel, change the Perhydrol input from the suggested value to a custom number → tab out or click away (blur) → orange outline flashes, then green `corr-saved` flash for ~800ms.
3. Hit **F5** in the browser → after reload, the correction field shows your custom value (not the formula suggestion).
4. Navigate to another batch from the sidebar → return → custom value still displayed.
5. In standaryzacja etap: enter Woda = 10, Kwas = 5 → `corr-total-woda-*` shows 15.0 immediately.
6. Change Woda to 12 → total immediately becomes 17.0.
7. Change Kwas to 3 → total immediately becomes 15.0.
8. Try typing into the total input → nothing happens (readonly, not-allowed cursor).
9. Click "Nowa runda" on standaryzacja → fresh sesja, Woda/Kwas fields empty (not copied from previous round); formula generates fresh suggestions.
10. With DevTools network tab open during step 2: verify the PUT request to `/api/pipeline/lab/ebr/<id>/korekta` and a 200 response.

If any step fails, STOP and investigate. The most likely causes are (a) data-attrs not populated in Pattern A of Task 5 — verify `data-ebr-id`, `data-etap-id`, `data-substancja` in the rendered DOM; (b) no active sesja (button "Nowa runda" not yet pressed for this etap) — endpoint returns 400.

- [ ] **Step 3: No commit**

This task is operational. If you discover a small bug and fix it during smoke, commit that fix as its own commit.

---

## Task 9: Memory update + push + PR

**Files:**
- Memory file update.

- [ ] **Step 1: Update project memory**

Append or edit in `/Users/tbk/.claude/projects/-Users-tbk-Desktop-lims-clean/memory/project_parametry_ssot.md`, under the most recent section:

```markdown
**Korekty auto-save (Chegina_K7 szarża) — DONE 2026-04-17:**
- New helper `mbr.pipeline.models.upsert_ebr_korekta(db, sesja_id, korekta_typ_id, ilosc, ilosc_wyliczona, zalecil)` — SELECT-then-UPDATE-or-INSERT against `ebr_korekta_v2` (no UNIQUE constraint needed).
- New endpoint `PUT /api/pipeline/lab/ebr/<ebr_id>/korekta` — per-field auto-save on blur, resolves active session server-side.
- `_correction_panel.html`: replaced sessionStorage-based FD for `corr-manual-*` / `corr-total-*` with `onblur="saveKorektaField(this)"` + `_pendingKorektaSaves` queue. Sum field (`corr-total-woda-*`) is now `readonly` and always recomputed from components (no guards, no FD).
- `_fast_entry_content.html` `loadBatch()` is now async and awaits `_pendingKorektaSaves` before swapping batches.
- Branch: `feature/korekty-persist`.
```

- [ ] **Step 2: Push branch**

```bash
git log --oneline main..HEAD    # review commits
git push -u origin feature/korekty-persist
```

- [ ] **Step 3: Suggest PR**

Print the GitHub PR URL the remote returned. Propose title:

> `feat: korekty persist on blur + sum field readonly (Chegina_K7 szarża)`

---

## Self-review (controller checklist)

**Spec coverage:**
- D1 per-field auto-save → Tasks 5, 6, 7 (frontend) + Tasks 1-4 (backend)
- D2 readonly sum → Task 6
- D3 UPSERT with ebr_id in URL → Tasks 3, 4
- D4 flush pending before loadBatch → Task 7
- D5 formula-vs-manual unchanged → not modified (render path continues to prefer `ilosc` over `ilosc_wyliczona`)
- Testing: backend via pytest Tasks 1-4; frontend via manual smoke Task 8

**No placeholders:**
- Every step has exact file paths, exact code, exact commands.
- No "handle edge cases" — edge cases covered by specific tests (null ilosc, unknown substancja, no active sesja, attribution per batch).

**Type consistency:**
- `upsert_ebr_korekta(db, sesja_id, korekta_typ_id, ilosc, ilosc_wyliczona, zalecil)` — same param names used in Tasks 1, 2, and 4.
- `PUT /api/pipeline/lab/ebr/<int:ebr_id>/korekta` path matches in Tasks 3 and 4.
- `_pendingKorektaSaves` array name used consistently in Tasks 5 and 7.
- `saveKorektaField` function name matches in Tasks 5 and 7.

**Risks:**
- Task 5 Pattern A assumes certain local variable names (`ebrId`, `etapId`, etc.) are in scope in the render function — implementer must verify by reading the template and adapt if names differ.
- `loadBatch` may be called from code that doesn't `await` it — async conversion is compatible (still returns a Promise) but verify no caller depends on synchronous side-effects during the flush window (should be rare).

**Out of scope (documented in spec):**
- `ebr_korekta_v2` UNIQUE constraint — avoided. If future audits show rogue duplicates, add a dedup migration.
- Pomiary auto-save refactor — separate flow.
