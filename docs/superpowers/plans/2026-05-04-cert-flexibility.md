# Cert Flexibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate `cert_variants` duplication along recipient and `nr_zam` axes by introducing 3 ad-hoc runtime fields (`recipient_name`, `expiry_months`, `order_number`) at cert generation time, with collision-aware filename, autocomplete from history, and admin-controlled archiving with optional backfill.

**Architecture:** Schema additive (3 ALTER COLUMN). Generator gains `_sanitize_filename_segment` helper, `_cert_names` extended with `recipient_name` + `has_order_number`, `save_certificate_pdf`/`save_certificate_data` get collision-aware suffix logic, `build_context` reads `expiry_months` override from `extra_fields`. Routes propagate runtime fields to all save sites. Two new endpoints (`recipient-suggestions`, `variants/<id>/archive` + `archive-preview`). UI laborant: modal restructure + autocomplete. UI admin: archive button + backfill modal + hide deprecated checkbox.

**Tech Stack:** Python 3 / Flask / sqlite3 (no ORM) / docxtpl / vanilla JS / Jinja2 templates. Tests: pytest with in-memory SQLite + monkeypatched `db_session`.

**Spec:** `docs/superpowers/specs/2026-05-04-cert-flexibility-design.md`

---

## File Map

| File | What changes |
|---|---|
| `mbr/models.py` | Add 3 ALTER TABLE migrations (idempotent try/except pattern) |
| `mbr/shared/audit.py` | Add 3 EVENT_* constants for archive / unarchive / recipient backfill |
| `mbr/certs/generator.py` | New `_sanitize_filename_segment`; `_cert_names` extended; `save_certificate_pdf` collision-aware; `save_certificate_data` collision-aware; `build_context` reads expiry_months override |
| `mbr/certs/models.py` | `create_swiadectwo` accepts `recipient_name`, `expiry_months_used` |
| `mbr/certs/routes.py` | `api_cert_generate` validation + propagation; new `api_cert_recipient_suggestions`; `api_cert_templates` extension; new `api_cert_variant_archive` + `api_cert_variant_archive_preview` |
| `mbr/templates/laborant/_fast_entry_content.html` | Modal `cv-popup-overlay` always opens; 3 stałe pola top + autocomplete dropdown + inline expiry validation; new flag handling |
| `mbr/templates/admin/wzory_cert.html` | Info-box; toggle archived; archive/unarchive button per variant card; backfill modal; hide `has_order_number` checkbox |
| `tests/test_cert_flexibility.py` | NEW — all unit + integration tests for backend changes |

---

## Task 1: Schema migrations (3 ALTER TABLE)

**Files:**
- Modify: `mbr/models.py:1619` (extend the existing migration block at end of `init_mbr_tables`)
- Test: `tests/test_cert_flexibility.py` (NEW)

- [ ] **Step 1: Write the failing test**

Create `tests/test_cert_flexibility.py` with this content:

```python
"""Cert flexibility — schema migrations + helpers + endpoints."""

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


# ===========================================================================
# Task 1: schema migrations
# ===========================================================================

def test_schema_swiadectwa_has_recipient_name(db):
    cols = {r["name"] for r in db.execute("PRAGMA table_info(swiadectwa)").fetchall()}
    assert "recipient_name" in cols


def test_schema_swiadectwa_has_expiry_months_used(db):
    cols = {r["name"] for r in db.execute("PRAGMA table_info(swiadectwa)").fetchall()}
    assert "expiry_months_used" in cols


def test_schema_cert_variants_has_archived(db):
    cols = {r["name"] for r in db.execute("PRAGMA table_info(cert_variants)").fetchall()}
    assert "archived" in cols


def test_schema_cert_variants_archived_default_zero(db):
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label) VALUES (?, ?, ?)",
        ("TestProd", "base", "TestProd"),
    )
    db.commit()
    row = db.execute("SELECT archived FROM cert_variants WHERE produkt='TestProd'").fetchone()
    assert row["archived"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cert_flexibility.py -v`
Expected: 4 tests FAIL with `AssertionError: assert 'recipient_name' in {...}` (and similar for the other two columns).

- [ ] **Step 3: Add migrations to `init_mbr_tables`**

In `mbr/models.py`, find the existing migration block ending around line 1634 (`# Migration: add target_produkt to swiadectwa`). Add immediately after it (before the `# ---` separator that follows):

```python
    # Migration: add recipient_name to swiadectwa (cert flexibility — runtime field)
    try:
        db.execute("ALTER TABLE swiadectwa ADD COLUMN recipient_name TEXT")
        db.commit()
    except Exception:
        pass  # column already exists

    # Migration: add expiry_months_used to swiadectwa (snapshot of effective expiry)
    try:
        db.execute("ALTER TABLE swiadectwa ADD COLUMN expiry_months_used INTEGER")
        db.commit()
    except Exception:
        pass  # column already exists

    # Migration: add archived to cert_variants (soft-archive for deprecated variants)
    try:
        db.execute("ALTER TABLE cert_variants ADD COLUMN archived INTEGER DEFAULT 0")
        db.commit()
    except Exception:
        pass  # column already exists
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cert_flexibility.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Run full test suite (no regressions)**

Run: `pytest`
Expected: all green (existing tests unaffected — additive schema).

- [ ] **Step 6: Commit**

```bash
git add mbr/models.py tests/test_cert_flexibility.py
git commit -m "feat(cert): schema additive — recipient_name, expiry_months_used, archived"
```

---

## Task 2: New audit event constants

**Files:**
- Modify: `mbr/shared/audit.py:74` (after existing cert events)

- [ ] **Step 1: Edit the constants block**

Find lines 70-74 in `mbr/shared/audit.py`:

```python
EVENT_CERT_GENERATED = "cert.generated"
EVENT_CERT_VALUES_EDITED = "cert.values.edited"
EVENT_CERT_CANCELLED = "cert.cancelled"
EVENT_CERT_CONFIG_UPDATED = "cert.config.updated"
EVENT_CERT_SETTINGS_UPDATED = "cert.settings.updated"
```

Add after line 74:

```python
EVENT_CERT_VARIANT_ARCHIVED = "cert.variant.archived"
EVENT_CERT_VARIANT_UNARCHIVED = "cert.variant.unarchived"
EVENT_CERT_RECIPIENT_BACKFILLED = "cert.swiadectwa.recipient_backfilled"
```

- [ ] **Step 2: Verify import works**

Run: `python -c "from mbr.shared.audit import EVENT_CERT_VARIANT_ARCHIVED, EVENT_CERT_VARIANT_UNARCHIVED, EVENT_CERT_RECIPIENT_BACKFILLED; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add mbr/shared/audit.py
git commit -m "feat(audit): event constants for cert variant archive/unarchive/backfill"
```

---

## Task 3: `_sanitize_filename_segment` helper

**Files:**
- Modify: `mbr/certs/generator.py` (insert helper before `_cert_names`, around line 1054)
- Test: `tests/test_cert_flexibility.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cert_flexibility.py`:

```python
# ===========================================================================
# Task 3: _sanitize_filename_segment
# ===========================================================================

def test_sanitize_passes_normal_text():
    from mbr.certs.generator import _sanitize_filename_segment
    assert _sanitize_filename_segment("ADAM&PARTNER") == "ADAM&PARTNER"


def test_sanitize_strips_path_separators():
    from mbr.certs.generator import _sanitize_filename_segment
    assert _sanitize_filename_segment("ADAM/PARTNER") == "ADAMPARTNER"
    assert _sanitize_filename_segment("ADAM\\PARTNER") == "ADAMPARTNER"
    assert _sanitize_filename_segment("ADAM:PARTNER") == "ADAMPARTNER"


def test_sanitize_strips_control_chars():
    from mbr.certs.generator import _sanitize_filename_segment
    assert _sanitize_filename_segment("ADAM\x00\x01PARTNER") == "ADAMPARTNER"


def test_sanitize_trims_whitespace():
    from mbr.certs.generator import _sanitize_filename_segment
    assert _sanitize_filename_segment("  ADAM  ") == "ADAM"


def test_sanitize_max_40_chars():
    from mbr.certs.generator import _sanitize_filename_segment
    long_name = "A" * 100
    assert _sanitize_filename_segment(long_name) == "A" * 40


def test_sanitize_empty_returns_empty():
    from mbr.certs.generator import _sanitize_filename_segment
    assert _sanitize_filename_segment("") == ""
    assert _sanitize_filename_segment("   ") == ""
    assert _sanitize_filename_segment(None) == ""


def test_sanitize_keeps_polish_chars_and_ampersand():
    from mbr.certs.generator import _sanitize_filename_segment
    assert _sanitize_filename_segment("Łódź & Co.") == "Łódź & Co."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cert_flexibility.py::test_sanitize_passes_normal_text -v`
Expected: FAIL with `ImportError` (`_sanitize_filename_segment` not yet defined).

- [ ] **Step 3: Add the helper to `mbr/certs/generator.py`**

Insert this block immediately before `def _cert_names` (currently line 1054):

```python
def _sanitize_filename_segment(s: str | None) -> str:
    """Strip path separators and control chars from a filename segment.

    Used for runtime-entered values (e.g. recipient_name) that flow into
    file paths. Removes anything < 0x20, '/', '\\\\', ':' and trims whitespace.
    Truncates to 40 chars to keep filenames bounded.

    Returns "" for None / empty / whitespace-only input.
    """
    if not s:
        return ""
    cleaned = "".join(c for c in s if ord(c) >= 0x20 and c not in ("/", "\\", ":"))
    cleaned = cleaned.strip()
    return cleaned[:40]
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `pytest tests/test_cert_flexibility.py -k sanitize -v`
Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/certs/generator.py tests/test_cert_flexibility.py
git commit -m "feat(cert): _sanitize_filename_segment helper for runtime values"
```

---

## Task 4: `_cert_names` extension (recipient_name + has_order_number)

**Files:**
- Modify: `mbr/certs/generator.py:1054-1084` (extend `_cert_names`)
- Test: `tests/test_cert_flexibility.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cert_flexibility.py`:

```python
# ===========================================================================
# Task 4: _cert_names with recipient + has_order_number
# ===========================================================================

def test_cert_names_baseline_unchanged():
    """Old signature still works (legacy callers)."""
    from mbr.certs.generator import _cert_names
    folder, pdf, nr = _cert_names("Chegina_K7", "Chegina K7", "4/2026")
    assert folder == "Chegina K7"
    assert pdf == "Chegina K7 4.pdf"
    assert nr == "4"


def test_cert_names_with_recipient():
    from mbr.certs.generator import _cert_names
    _, pdf, _ = _cert_names("Chegina_K7", "Chegina K7", "4/2026",
                            recipient_name="ADAM&PARTNER")
    assert pdf == "Chegina K7 — ADAM&PARTNER 4.pdf"


def test_cert_names_with_recipient_and_mb_variant():
    from mbr.certs.generator import _cert_names
    _, pdf, _ = _cert_names("Chegina_K7", "Chegina K7 — MB", "4/2026",
                            recipient_name="ADAM&PARTNER")
    assert pdf == "Chegina K7 MB — ADAM&PARTNER 4.pdf"


def test_cert_names_recipient_with_slash_sanitized():
    from mbr.certs.generator import _cert_names
    _, pdf, _ = _cert_names("Chegina_K7", "Chegina K7", "4/2026",
                            recipient_name="ADAM/Partner")
    assert pdf == "Chegina K7 — ADAMPartner 4.pdf"


def test_cert_names_empty_recipient_omitted():
    from mbr.certs.generator import _cert_names
    _, pdf, _ = _cert_names("Chegina_K7", "Chegina K7", "4/2026", recipient_name="   ")
    assert pdf == "Chegina K7 4.pdf"


def test_cert_names_with_order_number_suffix():
    from mbr.certs.generator import _cert_names
    _, pdf, _ = _cert_names("Chegina_K7", "Chegina K7", "4/2026",
                            has_order_number=True)
    assert pdf == "Chegina K7 4 (NRZAM).pdf"


def test_cert_names_with_recipient_and_order_number():
    from mbr.certs.generator import _cert_names
    _, pdf, _ = _cert_names("Chegina_K7", "Chegina K7", "4/2026",
                            recipient_name="ADAM", has_order_number=True)
    assert pdf == "Chegina K7 — ADAM 4 (NRZAM).pdf"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cert_flexibility.py -k cert_names -v`
Expected: All but `test_cert_names_baseline_unchanged` FAIL with `TypeError: _cert_names() got an unexpected keyword argument 'recipient_name'`.

- [ ] **Step 3: Extend `_cert_names`**

Replace the current `_cert_names` (generator.py:1054-1084) with:

```python
def _cert_names(
    produkt: str,
    variant_label: str,
    nr_partii: str,
    recipient_name: str | None = None,
    has_order_number: bool = False,
) -> tuple[str, str, str]:
    """Derive product folder name, PDF filename, and batch number from inputs.

    variant_label examples: "Chegina K40GL", "Chegina K40GL — MB"
    nr_partii examples: "4/2026", "124/2026"
    recipient_name: free-text customer name (sanitized before use).
    has_order_number: if True, append "(NRZAM)" suffix.

    Returns:
        (product_folder, pdf_name, nr_only)
        e.g. ("Chegina K40GL", "Chegina K40GL MB — ADAM 4 (NRZAM).pdf", "4")
    """
    product_folder = produkt.replace("_", " ")

    variant_suffix = ""
    if "—" in variant_label:  # em dash
        variant_suffix = variant_label.split("—", 1)[1].strip()
    elif " - " in variant_label:
        variant_suffix = variant_label.split(" - ", 1)[1].strip()

    nr_only = nr_partii.split("/")[0].strip()

    parts = [product_folder]
    if variant_suffix:
        parts.append(variant_suffix)
    if recipient_name:
        sanitized = _sanitize_filename_segment(recipient_name)
        if sanitized:
            parts.append("—")  # em dash
            parts.append(sanitized)
    parts.append(nr_only)
    if has_order_number:
        parts.append("(NRZAM)")
    pdf_name = " ".join(parts) + ".pdf"

    return product_folder, pdf_name, nr_only
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `pytest tests/test_cert_flexibility.py -k cert_names -v`
Expected: 7 tests PASS.

- [ ] **Step 5: Run full suite to detect regressions in callers**

Run: `pytest`
Expected: all green. (Old callers pass `recipient_name=None` by default.)

- [ ] **Step 6: Commit**

```bash
git add mbr/certs/generator.py tests/test_cert_flexibility.py
git commit -m "feat(cert): _cert_names accepts recipient_name + has_order_number"
```

---

## Task 5: `save_certificate_pdf` collision-aware + recipient/has_order_number

**Files:**
- Modify: `mbr/certs/generator.py:1112-1136` (extend `save_certificate_pdf`)
- Test: `tests/test_cert_flexibility.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cert_flexibility.py`:

```python
# ===========================================================================
# Task 5: save_certificate_pdf collision-aware + new params
# ===========================================================================

def test_save_pdf_first_call_no_suffix(tmp_path):
    from mbr.certs.generator import save_certificate_pdf
    path = save_certificate_pdf(
        b"PDF1", "Chegina_K7", "Chegina K7", "4/2026",
        output_dir=str(tmp_path),
    )
    from pathlib import Path
    p = Path(path)
    assert p.name == "Chegina K7 4.pdf"
    assert p.read_bytes() == b"PDF1"


def test_save_pdf_collision_appends_suffix(tmp_path):
    from mbr.certs.generator import save_certificate_pdf
    p1 = save_certificate_pdf(b"PDF1", "Chegina_K7", "Chegina K7", "4/2026",
                              output_dir=str(tmp_path))
    p2 = save_certificate_pdf(b"PDF2", "Chegina_K7", "Chegina K7", "4/2026",
                              output_dir=str(tmp_path))
    p3 = save_certificate_pdf(b"PDF3", "Chegina_K7", "Chegina K7", "4/2026",
                              output_dir=str(tmp_path))
    from pathlib import Path
    assert Path(p1).name == "Chegina K7 4.pdf"
    assert Path(p2).name == "Chegina K7 4 (2).pdf"
    assert Path(p3).name == "Chegina K7 4 (3).pdf"
    # Original is preserved.
    assert Path(p1).read_bytes() == b"PDF1"
    assert Path(p2).read_bytes() == b"PDF2"


def test_save_pdf_with_recipient_in_filename(tmp_path):
    from mbr.certs.generator import save_certificate_pdf
    path = save_certificate_pdf(
        b"PDF", "Chegina_K7", "Chegina K7", "4/2026",
        output_dir=str(tmp_path), recipient_name="ADAM&PARTNER",
    )
    from pathlib import Path
    assert Path(path).name == "Chegina K7 — ADAM&PARTNER 4.pdf"


def test_save_pdf_with_order_number_suffix(tmp_path):
    from mbr.certs.generator import save_certificate_pdf
    path = save_certificate_pdf(
        b"PDF", "Chegina_K7", "Chegina K7", "4/2026",
        output_dir=str(tmp_path), has_order_number=True,
    )
    from pathlib import Path
    assert Path(path).name == "Chegina K7 4 (NRZAM).pdf"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cert_flexibility.py -k save_pdf -v`
Expected: collision and recipient/order-number tests FAIL with `TypeError` (kwargs not accepted) or `AssertionError` (collision overwrites).

- [ ] **Step 3: Replace `save_certificate_pdf`**

Replace the entire function body (generator.py:1112-1136) with:

```python
def save_certificate_pdf(
    pdf_bytes: bytes,
    produkt: str,
    variant_label: str,
    nr_partii: str,
    output_dir: str | None = None,
    recipient_name: str | None = None,
    has_order_number: bool = False,
) -> str:
    """Save PDF to user-configured path, with collision-aware suffix.

    Structure: {output_dir}/{year}/{product_folder}/{pdf_name}
    Fallback: ~/Desktop/{year}/{product_folder}/{pdf_name}

    Collision: if filename exists, append " (2)", " (3)", ... before .pdf
    until a free slot is found. Original files NEVER overwritten.

    Returns: absolute path to saved PDF.
    """
    year = date.today().year
    product_folder, pdf_name, _ = _cert_names(
        produkt, variant_label, nr_partii,
        recipient_name=recipient_name, has_order_number=has_order_number,
    )

    base_dir = Path(output_dir) if output_dir else Path.home() / "Desktop"
    target_dir = base_dir / str(year) / product_folder
    target_dir.mkdir(parents=True, exist_ok=True)

    full_path = target_dir / pdf_name
    if full_path.exists():
        stem = full_path.stem
        suffix = full_path.suffix
        i = 2
        while True:
            candidate = target_dir / f"{stem} ({i}){suffix}"
            if not candidate.exists():
                full_path = candidate
                break
            i += 1

    full_path.write_bytes(pdf_bytes)
    return str(full_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cert_flexibility.py -k save_pdf -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/certs/generator.py tests/test_cert_flexibility.py
git commit -m "feat(cert): save_certificate_pdf collision-aware + recipient/has_order_number"
```

---

## Task 6: `save_certificate_data` collision-aware + new params

**Files:**
- Modify: `mbr/certs/generator.py:1087-1109` (extend `save_certificate_data`)
- Test: `tests/test_cert_flexibility.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cert_flexibility.py`:

```python
# ===========================================================================
# Task 6: save_certificate_data collision + new params
# ===========================================================================

def test_save_data_with_recipient_filename(tmp_path, monkeypatch):
    from mbr.certs import generator
    monkeypatch.setattr(generator, "OUTPUT_DIR", tmp_path)
    path = generator.save_certificate_data(
        "Chegina_K7", "Chegina K7", "4/2026",
        {"foo": "bar"},
        recipient_name="ADAM",
    )
    from pathlib import Path
    assert Path(path).name == "Chegina K7 — ADAM 4.json"


def test_save_data_collision_appends_suffix(tmp_path, monkeypatch):
    from mbr.certs import generator
    monkeypatch.setattr(generator, "OUTPUT_DIR", tmp_path)
    p1 = generator.save_certificate_data("Chegina_K7", "Chegina K7", "4/2026",
                                         {"id": 1})
    p2 = generator.save_certificate_data("Chegina_K7", "Chegina K7", "4/2026",
                                         {"id": 2})
    from pathlib import Path
    assert Path(p1).name == "Chegina K7 4.json"
    assert Path(p2).name == "Chegina K7 4 (2).json"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cert_flexibility.py -k save_data -v`
Expected: FAIL — `recipient_name` kwarg not accepted; collision overwrites JSON.

- [ ] **Step 3: Replace `save_certificate_data`**

Replace the function (generator.py:1087-1109) with:

```python
def save_certificate_data(
    produkt: str,
    variant_label: str,
    nr_partii: str,
    generation_data: dict,
    recipient_name: str | None = None,
    has_order_number: bool = False,
) -> str:
    """Save generation inputs as JSON to data/swiadectwa/ archive.

    Structure: data/swiadectwa/{year}/{product_folder}/{name}.json
    Collision: if filename exists, append " (2)", " (3)", ... before .json.

    Returns: path relative to project root.
    """
    year = date.today().year
    product_folder, pdf_name, _ = _cert_names(
        produkt, variant_label, nr_partii,
        recipient_name=recipient_name, has_order_number=has_order_number,
    )
    json_name = pdf_name.replace(".pdf", ".json")

    out_dir = OUTPUT_DIR / str(year) / product_folder
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / json_name
    if json_path.exists():
        stem = json_path.stem
        suffix = json_path.suffix
        i = 2
        while True:
            candidate = out_dir / f"{stem} ({i}){suffix}"
            if not candidate.exists():
                json_path = candidate
                break
            i += 1

    import json
    json_path.write_text(json.dumps(generation_data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return str(json_path.relative_to(_PROJECT_ROOT))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cert_flexibility.py -k save_data -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/certs/generator.py tests/test_cert_flexibility.py
git commit -m "feat(cert): save_certificate_data collision-aware + new params"
```

---

## Task 7: `build_context` expiry override

**Files:**
- Modify: `mbr/certs/generator.py:439-444` (replace expiry computation)
- Test: `tests/test_cert_flexibility.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cert_flexibility.py`:

```python
# ===========================================================================
# Task 7: build_context expiry_months override
# ===========================================================================

def _seed_minimal_product(db, key="TestProd", expiry_months=12):
    """Insert minimal data for build_context to succeed."""
    db.execute(
        "INSERT INTO produkty (nazwa, display_name, expiry_months) VALUES (?, ?, ?)",
        (key, key, expiry_months),
    )
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label) VALUES (?, ?, ?)",
        (key, "base", key),
    )
    db.commit()


def test_build_context_default_expiry_from_product(db, monkeypatch):
    import mbr.certs.generator as gen
    @contextmanager
    def fake_db_session():
        yield db
    monkeypatch.setattr(gen, "_db_session", fake_db_session, raising=False)
    monkeypatch.setattr("mbr.db.db_session", fake_db_session)
    _seed_minimal_product(db, expiry_months=12)
    from datetime import date
    ctx = gen.build_context("TestProd", "base", "1/2026", date(2026, 1, 1),
                            wyniki_flat={}, extra_fields={})
    assert ctx["dt_waznosci"] == "01.01.2027"  # +12mc


def test_build_context_override_expiry_24mc(db, monkeypatch):
    import mbr.certs.generator as gen
    @contextmanager
    def fake_db_session():
        yield db
    monkeypatch.setattr("mbr.db.db_session", fake_db_session)
    _seed_minimal_product(db, expiry_months=12)
    from datetime import date
    ctx = gen.build_context("TestProd", "base", "1/2026", date(2026, 1, 1),
                            wyniki_flat={}, extra_fields={"expiry_months": 24})
    assert ctx["dt_waznosci"] == "01.01.2028"  # +24mc


def test_build_context_override_zero_raises(db, monkeypatch):
    import mbr.certs.generator as gen
    @contextmanager
    def fake_db_session():
        yield db
    monkeypatch.setattr("mbr.db.db_session", fake_db_session)
    _seed_minimal_product(db)
    from datetime import date
    with pytest.raises(ValueError, match="out of range"):
        gen.build_context("TestProd", "base", "1/2026", date(2026, 1, 1),
                          wyniki_flat={}, extra_fields={"expiry_months": 0})


def test_build_context_override_too_high_raises(db, monkeypatch):
    import mbr.certs.generator as gen
    @contextmanager
    def fake_db_session():
        yield db
    monkeypatch.setattr("mbr.db.db_session", fake_db_session)
    _seed_minimal_product(db)
    from datetime import date
    with pytest.raises(ValueError, match="out of range"):
        gen.build_context("TestProd", "base", "1/2026", date(2026, 1, 1),
                          wyniki_flat={}, extra_fields={"expiry_months": 31})


def test_build_context_override_non_numeric_raises(db, monkeypatch):
    import mbr.certs.generator as gen
    @contextmanager
    def fake_db_session():
        yield db
    monkeypatch.setattr("mbr.db.db_session", fake_db_session)
    _seed_minimal_product(db)
    from datetime import date
    with pytest.raises(ValueError, match="Invalid expiry_months"):
        gen.build_context("TestProd", "base", "1/2026", date(2026, 1, 1),
                          wyniki_flat={}, extra_fields={"expiry_months": "abc"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cert_flexibility.py -k build_context -v`
Expected: FAIL — override is currently ignored, dt_waznosci computed from `produkty.expiry_months` only.

- [ ] **Step 3: Replace expiry computation in `build_context`**

In `mbr/certs/generator.py`, find the block around line 439:

```python
    if dt_obj:
        dt_produkcji = dt_obj.strftime("%d.%m.%Y")
        expiry_months = _expiry_months
        # Add expiry_months
```

Replace it with:

```python
    if dt_obj:
        dt_produkcji = dt_obj.strftime("%d.%m.%Y")
        # Resolve expiry: extra_fields override (if valid) > produkty.expiry_months.
        override = (extra_fields or {}).get("expiry_months")
        if override is not None and str(override).strip():
            try:
                expiry_months = int(override)
            except (ValueError, TypeError):
                raise ValueError(f"Invalid expiry_months: {override!r}")
            if not (1 <= expiry_months <= 30):
                raise ValueError(
                    f"expiry_months out of range 1..30: {expiry_months}"
                )
        else:
            expiry_months = _expiry_months
        # Add expiry_months
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cert_flexibility.py -k build_context -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Run full suite (regression check)**

Run: `pytest`
Expected: all green. Existing tests use `extra_fields={}` or none → default branch unchanged.

- [ ] **Step 6: Commit**

```bash
git add mbr/certs/generator.py tests/test_cert_flexibility.py
git commit -m "feat(cert): build_context honors extra_fields.expiry_months override (1..30)"
```

---

## Task 8: `create_swiadectwo` accepts new columns

**Files:**
- Modify: `mbr/certs/models.py:13-23` (extend `create_swiadectwo`)
- Test: `tests/test_cert_flexibility.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cert_flexibility.py`:

```python
# ===========================================================================
# Task 8: create_swiadectwo persists recipient_name + expiry_months_used
# ===========================================================================

def _seed_ebr(db, produkt="TestProd", nr_partii="1/2026"):
    db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, dt_utworzenia) "
        "VALUES (?, 1, 'active', '[]', '{}', datetime('now'))",
        (produkt,),
    )
    mbr_id = db.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status) "
        "VALUES (?, 'B001', ?, datetime('now'), 'completed')",
        (mbr_id, nr_partii),
    )
    return db.execute("SELECT last_insert_rowid() id").fetchone()["id"]


def test_create_swiadectwo_with_recipient_and_expiry(db):
    from mbr.certs.models import create_swiadectwo
    ebr_id = _seed_ebr(db)
    cert_id = create_swiadectwo(
        db, ebr_id, "TestProd", "1/2026", "/tmp/x.pdf", "tester",
        data_json="{}", recipient_name="ADAM&PARTNER", expiry_months_used=18,
    )
    db.commit()
    row = db.execute(
        "SELECT recipient_name, expiry_months_used FROM swiadectwa WHERE id=?",
        (cert_id,),
    ).fetchone()
    assert row["recipient_name"] == "ADAM&PARTNER"
    assert row["expiry_months_used"] == 18


def test_create_swiadectwo_without_new_fields_legacy(db):
    """Legacy callers without new kwargs still work (NULL columns)."""
    from mbr.certs.models import create_swiadectwo
    ebr_id = _seed_ebr(db)
    cert_id = create_swiadectwo(
        db, ebr_id, "TestProd", "1/2026", "/tmp/x.pdf", "tester",
        data_json="{}",
    )
    db.commit()
    row = db.execute(
        "SELECT recipient_name, expiry_months_used FROM swiadectwa WHERE id=?",
        (cert_id,),
    ).fetchone()
    assert row["recipient_name"] is None
    assert row["expiry_months_used"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cert_flexibility.py -k create_swiadectwo -v`
Expected: first test FAILs with `TypeError: create_swiadectwo() got an unexpected keyword argument 'recipient_name'`.

- [ ] **Step 3: Extend `create_swiadectwo`**

Replace `mbr/certs/models.py:13-23` with:

```python
def create_swiadectwo(db, ebr_id, template_name, nr_partii, pdf_path, wystawil,
                     data_json=None, target_produkt=None,
                     recipient_name=None, expiry_months_used=None):
    now = app_now_iso()
    cur = db.execute(
        "INSERT INTO swiadectwa (ebr_id, template_name, nr_partii, pdf_path, "
        "dt_wystawienia, wystawil, data_json, target_produkt, "
        "recipient_name, expiry_months_used) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ebr_id, template_name, nr_partii, pdf_path, now, wystawil,
         data_json, target_produkt, recipient_name, expiry_months_used),
    )
    return cur.lastrowid
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `pytest tests/test_cert_flexibility.py -k create_swiadectwo -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Run full suite (regression check)**

Run: `pytest`
Expected: all green. Existing callers don't pass new kwargs → defaults to NULL.

- [ ] **Step 6: Commit**

```bash
git add mbr/certs/models.py tests/test_cert_flexibility.py
git commit -m "feat(cert): create_swiadectwo persists recipient_name + expiry_months_used"
```

---

## Task 9: `api_cert_recipient_suggestions` endpoint

**Files:**
- Modify: `mbr/certs/routes.py` (add new endpoint after the existing route block, around line 100)
- Test: `tests/test_cert_flexibility.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cert_flexibility.py`:

```python
# ===========================================================================
# Task 9: GET /api/cert/recipient-suggestions
# ===========================================================================

def _make_client(monkeypatch, db, rola="lab"):
    """Test client with fake db_session and pre-set session user."""
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


def _seed_swiadectwa_recipients(db, recipients):
    """Create one cert row per recipient name (or NULL)."""
    db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, dt_utworzenia) "
        "VALUES ('TestProd', 1, 'active', '[]', '{}', datetime('now'))"
    )
    db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status) "
        "VALUES (1, 'B001', '1/2026', datetime('now'), 'completed')"
    )
    for r in recipients:
        db.execute(
            "INSERT INTO swiadectwa (ebr_id, template_name, nr_partii, pdf_path, "
            "dt_wystawienia, wystawil, recipient_name) "
            "VALUES (1, 'base', '1/2026', '/x.pdf', datetime('now'), 't', ?)",
            (r,),
        )
    db.commit()


def test_recipient_suggestions_below_threshold(monkeypatch, db):
    c = _make_client(monkeypatch, db)
    _seed_swiadectwa_recipients(db, ["ADAM&PARTNER", "ADAM Partner"])
    r = c.get("/api/cert/recipient-suggestions?q=A")
    assert r.status_code == 200
    assert r.get_json() == {"suggestions": []}


def test_recipient_suggestions_returns_distinct_matches(monkeypatch, db):
    c = _make_client(monkeypatch, db)
    _seed_swiadectwa_recipients(db, [
        "ADAM&PARTNER", "ADAM&PARTNER", "ADAM Partner", "Loreal",
    ])
    r = c.get("/api/cert/recipient-suggestions?q=ad")
    out = r.get_json()["suggestions"]
    assert sorted(out) == ["ADAM Partner", "ADAM&PARTNER"]


def test_recipient_suggestions_no_match(monkeypatch, db):
    c = _make_client(monkeypatch, db)
    _seed_swiadectwa_recipients(db, ["ADAM&PARTNER"])
    r = c.get("/api/cert/recipient-suggestions?q=xyz")
    assert r.get_json() == {"suggestions": []}


def test_recipient_suggestions_excludes_null(monkeypatch, db):
    c = _make_client(monkeypatch, db)
    _seed_swiadectwa_recipients(db, ["ADAM&PARTNER", None, None])
    r = c.get("/api/cert/recipient-suggestions?q=ad")
    assert r.get_json()["suggestions"] == ["ADAM&PARTNER"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cert_flexibility.py -k recipient_suggestions -v`
Expected: FAIL with `404 Not Found` (endpoint doesn't exist yet).

- [ ] **Step 3: Add endpoint to `mbr/certs/routes.py`**

Find the imports block at top of `mbr/certs/routes.py:1-13` and confirm `request, jsonify` are imported. Then add this function after `api_cert_templates` (around line 45):

```python
@certs_bp.route("/api/cert/recipient-suggestions")
@login_required
def api_cert_recipient_suggestions():
    """Autocomplete source for recipient_name field in cert generate modal.

    Threshold: 2 chars to avoid noisy short queries. Case-insensitive LIKE,
    distinct values, ordered alphabetically, capped at 20.
    """
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"suggestions": []})
    with db_session() as db:
        rows = db.execute(
            "SELECT DISTINCT recipient_name FROM swiadectwa "
            "WHERE recipient_name IS NOT NULL "
            "AND recipient_name LIKE ? COLLATE NOCASE "
            "ORDER BY recipient_name LIMIT 20",
            (f"%{q}%",),
        ).fetchall()
    return jsonify({"suggestions": [r["recipient_name"] for r in rows]})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cert_flexibility.py -k recipient_suggestions -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/certs/routes.py tests/test_cert_flexibility.py
git commit -m "feat(cert): GET /api/cert/recipient-suggestions endpoint"
```

---

## Task 10: `api_cert_templates` extensions (`default_expiry_months` + `include_archived`)

**Files:**
- Modify: `mbr/certs/routes.py:20-44` (extend `api_cert_templates`)
- Modify: `mbr/certs/generator.py:157-182` (extend `get_variants` to filter archived)
- Test: `tests/test_cert_flexibility.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cert_flexibility.py`:

```python
# ===========================================================================
# Task 10: api_cert_templates default_expiry_months + include_archived
# ===========================================================================

def _seed_product_with_variants(db, produkt="TestProd", expiry_months=12,
                                 variants=(("base", "TestProd", 0),
                                          ("mb", "TestProd MB", 0))):
    """Variants: tuples of (variant_id, label, archived)."""
    db.execute(
        "INSERT INTO produkty (nazwa, display_name, expiry_months) VALUES (?, ?, ?)",
        (produkt, produkt, expiry_months),
    )
    for vid, label, arch in variants:
        db.execute(
            "INSERT INTO cert_variants (produkt, variant_id, label, archived) "
            "VALUES (?, ?, ?, ?)",
            (produkt, vid, label, arch),
        )
    db.commit()


def test_templates_returns_default_expiry_months(monkeypatch, db):
    c = _make_client(monkeypatch, db)
    _seed_product_with_variants(db, expiry_months=18)
    r = c.get("/api/cert/templates?produkt=TestProd")
    out = r.get_json()["templates"]
    assert all(t["default_expiry_months"] == 18 for t in out)


def test_templates_default_expiry_fallback_when_null(monkeypatch, db):
    c = _make_client(monkeypatch, db)
    db.execute("INSERT INTO produkty (nazwa, display_name, expiry_months) VALUES ('X', 'X', NULL)")
    db.execute("INSERT INTO cert_variants (produkt, variant_id, label) VALUES ('X', 'base', 'X')")
    db.commit()
    r = c.get("/api/cert/templates?produkt=X")
    assert r.get_json()["templates"][0]["default_expiry_months"] == 12


def test_templates_filters_archived_by_default(monkeypatch, db):
    c = _make_client(monkeypatch, db)
    _seed_product_with_variants(db, variants=(
        ("base", "TestProd", 0),
        ("legacy", "TestProd — LEGACY", 1),  # archived
    ))
    r = c.get("/api/cert/templates?produkt=TestProd")
    ids = [t["filename"] for t in r.get_json()["templates"]]
    assert "base" in ids
    assert "legacy" not in ids


def test_templates_include_archived_param(monkeypatch, db):
    c = _make_client(monkeypatch, db)
    _seed_product_with_variants(db, variants=(
        ("base", "TestProd", 0),
        ("legacy", "TestProd — LEGACY", 1),
    ))
    r = c.get("/api/cert/templates?produkt=TestProd&include_archived=1")
    ids = [t["filename"] for t in r.get_json()["templates"]]
    assert "base" in ids
    assert "legacy" in ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cert_flexibility.py -k templates -v`
Expected: 4 tests FAIL — `default_expiry_months` missing, archived not filtered.

- [ ] **Step 3: Extend `get_variants` to support archived filter**

In `mbr/certs/generator.py`, replace the `get_variants` function (lines 157-182) with:

```python
def get_variants(produkt: str, *, include_archived: bool = False) -> list[dict]:
    """Return list of {id, label, flags, owner_produkt} for a product from DB.

    By default filters archived=0 (active variants only). Pass
    include_archived=True to fetch all (used by admin UI editor).

    owner_produkt echoes back the produkt argument.
    """
    from mbr.db import db_session as _db_session
    key = produkt if "_" in produkt else produkt.replace(" ", "_")
    sql_filter = "" if include_archived else "AND COALESCE(archived,0)=0"
    try:
        with _db_session() as db:
            rows = db.execute(
                f"SELECT variant_id, label, flags FROM cert_variants "
                f"WHERE produkt=? {sql_filter} ORDER BY kolejnosc", (key,)
            ).fetchall()
            if not rows:
                rows = db.execute(
                    f"SELECT variant_id, label, flags FROM cert_variants "
                    f"WHERE produkt=? {sql_filter} ORDER BY kolejnosc",
                    (produkt.replace(" ", "_"),)
                ).fetchall()
            return [{"id": r["variant_id"], "label": r["label"],
                     "flags": json.loads(r["flags"] or "[]"),
                     "owner_produkt": key} for r in rows]
    except Exception:
        return []
```

- [ ] **Step 4: Extend `api_cert_templates` route**

In `mbr/certs/routes.py`, replace `api_cert_templates` (lines 20-44) with:

```python
@certs_bp.route("/api/cert/templates")
@login_required
def api_cert_templates():
    produkt = request.args.get("produkt", "")
    include_archived = request.args.get("include_archived") == "1"
    if not produkt:
        return jsonify({"templates": []})

    from mbr.certs.generator import get_cert_aliases
    variants = list(get_variants(produkt, include_archived=include_archived))
    with db_session() as db:
        aliases = get_cert_aliases(db, produkt)
        # Resolve default_expiry_months once per owner_produkt.
        expiry_cache: dict = {}
        def _expiry_for(p: str) -> int:
            if p in expiry_cache:
                return expiry_cache[p]
            row = db.execute(
                "SELECT expiry_months FROM produkty WHERE nazwa=?", (p,)
            ).fetchone()
            val = (row["expiry_months"] if row else None) or 12
            expiry_cache[p] = val
            return val

    for target_produkt in aliases:
        variants.extend(get_variants(target_produkt, include_archived=include_archived))

    templates = []
    for v in variants:
        templates.append({
            "filename": v["id"],
            "display": v["label"],
            "flags": v["flags"],
            "owner_produkt": v["owner_produkt"],
            "required_fields": get_required_fields(v["owner_produkt"], v["id"]),
            "default_expiry_months": _expiry_for(v["owner_produkt"]),
        })
    return jsonify({"templates": templates})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_cert_flexibility.py -k templates -v`
Expected: 4 tests PASS.

- [ ] **Step 6: Run full suite (regression check)**

Run: `pytest`
Expected: all green. `get_variants` defaulted to `include_archived=False` — previously archived column didn't exist, all values default to 0, so existing tests unaffected.

- [ ] **Step 7: Commit**

```bash
git add mbr/certs/routes.py mbr/certs/generator.py tests/test_cert_flexibility.py
git commit -m "feat(cert): api_cert_templates returns default_expiry_months + supports include_archived"
```

---

## Task 11: `api_cert_variant_archive_preview` endpoint

**Files:**
- Modify: `mbr/certs/routes.py` (add endpoint after `api_cert_recipient_suggestions`)
- Test: `tests/test_cert_flexibility.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cert_flexibility.py`:

```python
# ===========================================================================
# Task 11: GET /api/cert/variants/<id>/archive-preview
# ===========================================================================

def _seed_variant_with_history(db, produkt="TestProd",
                                variant_id="adam_partner",
                                label="TestProd — ADAM&PARTNER",
                                cert_count=3, with_recipient=False):
    """Insert a variant and N swiadectwa rows for it."""
    db.execute(
        "INSERT INTO produkty (nazwa, display_name, expiry_months) VALUES (?, ?, 12)",
        (produkt,),
    )
    cur = db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label) VALUES (?, ?, ?)",
        (produkt, variant_id, label),
    )
    cv_id = cur.lastrowid
    db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, dt_utworzenia) "
        "VALUES (?, 1, 'active', '[]', '{}', datetime('now'))",
        (produkt,),
    )
    db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status) "
        "VALUES (1, 'B', '1/2026', datetime('now'), 'completed')"
    )
    for i in range(cert_count):
        db.execute(
            "INSERT INTO swiadectwa (ebr_id, template_name, nr_partii, pdf_path, "
            "dt_wystawienia, wystawil, recipient_name) "
            "VALUES (1, ?, '1/2026', '/x.pdf', datetime('now'), 't', ?)",
            (variant_id, "Pre-existing" if with_recipient else None),
        )
    db.commit()
    return cv_id


def test_archive_preview_counts_null_recipient_certs(monkeypatch, db):
    c = _make_client(monkeypatch, db, rola="admin")
    cv_id = _seed_variant_with_history(db, cert_count=5)
    r = c.get(f"/api/cert/variants/{cv_id}/archive-preview")
    assert r.status_code == 200
    out = r.get_json()
    assert out["swiadectwa_count"] == 5
    assert out["suggested_recipient"] == "ADAM&PARTNER"


def test_archive_preview_label_no_emdash_returns_empty_suggested(monkeypatch, db):
    c = _make_client(monkeypatch, db, rola="admin")
    cv_id = _seed_variant_with_history(db, label="TestProd")
    r = c.get(f"/api/cert/variants/{cv_id}/archive-preview")
    assert r.get_json()["suggested_recipient"] == ""


def test_archive_preview_excludes_certs_with_recipient(monkeypatch, db):
    c = _make_client(monkeypatch, db, rola="admin")
    cv_id = _seed_variant_with_history(db, cert_count=3, with_recipient=True)
    r = c.get(f"/api/cert/variants/{cv_id}/archive-preview")
    assert r.get_json()["swiadectwa_count"] == 0


def test_archive_preview_404_for_missing_variant(monkeypatch, db):
    c = _make_client(monkeypatch, db, rola="admin")
    r = c.get("/api/cert/variants/9999/archive-preview")
    assert r.status_code == 404


def test_archive_preview_requires_admin(monkeypatch, db):
    c = _make_client(monkeypatch, db, rola="lab")
    cv_id = _seed_variant_with_history(db)
    r = c.get(f"/api/cert/variants/{cv_id}/archive-preview")
    assert r.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cert_flexibility.py -k archive_preview -v`
Expected: FAIL with `404` (endpoint not yet defined).

- [ ] **Step 3: Add endpoint to `mbr/certs/routes.py`**

Insert after `api_cert_recipient_suggestions` (added in Task 9). Add `from flask import abort` to imports if not already there.

```python
@certs_bp.route("/api/cert/variants/<int:variant_id>/archive-preview")
@role_required("admin")
def api_cert_variant_archive_preview(variant_id):
    """Stats for the archive-with-backfill modal in cert editor.

    Returns count of swiadectwa rows that would be touched by backfill
    (those with template_name=variant_id AND recipient_name IS NULL),
    plus a parsed suggestion derived from the variant label after em-dash.
    """
    with db_session() as db:
        vrow = db.execute(
            "SELECT variant_id, label FROM cert_variants WHERE id=?",
            (variant_id,)).fetchone()
        if not vrow:
            abort(404)
        count = db.execute(
            "SELECT COUNT(*) c FROM swiadectwa "
            "WHERE template_name=? AND recipient_name IS NULL",
            (vrow["variant_id"],)).fetchone()["c"]
    suggested = ""
    if "—" in (vrow["label"] or ""):
        suggested = vrow["label"].split("—", 1)[1].strip()
    return jsonify({"swiadectwa_count": count, "suggested_recipient": suggested})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cert_flexibility.py -k archive_preview -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/certs/routes.py tests/test_cert_flexibility.py
git commit -m "feat(cert): GET /api/cert/variants/<id>/archive-preview endpoint"
```

---

## Task 12: `api_cert_variant_archive` endpoint with backfill

**Files:**
- Modify: `mbr/certs/routes.py` (add endpoint after `archive-preview`)
- Test: `tests/test_cert_flexibility.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cert_flexibility.py`:

```python
# ===========================================================================
# Task 12: POST /api/cert/variants/<id>/archive
# ===========================================================================

def test_archive_sets_archived_flag(monkeypatch, db):
    c = _make_client(monkeypatch, db, rola="admin")
    cv_id = _seed_variant_with_history(db, cert_count=0)
    r = c.post(f"/api/cert/variants/{cv_id}/archive", json={"archived": True})
    assert r.status_code == 200
    assert r.get_json()["archived"] is True
    row = db.execute("SELECT archived FROM cert_variants WHERE id=?", (cv_id,)).fetchone()
    assert row["archived"] == 1


def test_unarchive_clears_archived_flag(monkeypatch, db):
    c = _make_client(monkeypatch, db, rola="admin")
    cv_id = _seed_variant_with_history(db, cert_count=0)
    db.execute("UPDATE cert_variants SET archived=1 WHERE id=?", (cv_id,))
    db.commit()
    r = c.post(f"/api/cert/variants/{cv_id}/archive", json={"archived": False})
    assert r.get_json()["archived"] is False
    row = db.execute("SELECT archived FROM cert_variants WHERE id=?", (cv_id,)).fetchone()
    assert row["archived"] == 0


def test_archive_with_backfill_updates_old_certs(monkeypatch, db):
    c = _make_client(monkeypatch, db, rola="admin")
    cv_id = _seed_variant_with_history(db, cert_count=3)
    r = c.post(f"/api/cert/variants/{cv_id}/archive",
               json={"archived": True, "backfill_recipient": "ADAM&PARTNER"})
    assert r.get_json()["backfill_count"] == 3
    rows = db.execute(
        "SELECT recipient_name FROM swiadectwa WHERE template_name='adam_partner'"
    ).fetchall()
    assert all(r["recipient_name"] == "ADAM&PARTNER" for r in rows)


def test_archive_backfill_skips_already_set(monkeypatch, db):
    c = _make_client(monkeypatch, db, rola="admin")
    cv_id = _seed_variant_with_history(db, cert_count=3, with_recipient=True)
    r = c.post(f"/api/cert/variants/{cv_id}/archive",
               json={"archived": True, "backfill_recipient": "NEW"})
    assert r.get_json()["backfill_count"] == 0
    rows = db.execute(
        "SELECT recipient_name FROM swiadectwa WHERE template_name='adam_partner'"
    ).fetchall()
    assert all(r["recipient_name"] == "Pre-existing" for r in rows)


def test_archive_sanitizes_backfill_value(monkeypatch, db):
    c = _make_client(monkeypatch, db, rola="admin")
    cv_id = _seed_variant_with_history(db, cert_count=2)
    r = c.post(f"/api/cert/variants/{cv_id}/archive",
               json={"archived": True, "backfill_recipient": "AB/CD"})
    assert r.get_json()["backfill_count"] == 2
    rows = db.execute(
        "SELECT recipient_name FROM swiadectwa WHERE template_name='adam_partner'"
    ).fetchall()
    assert all(r["recipient_name"] == "ABCD" for r in rows)


def test_unarchive_ignores_backfill_param(monkeypatch, db):
    c = _make_client(monkeypatch, db, rola="admin")
    cv_id = _seed_variant_with_history(db, cert_count=3)
    db.execute("UPDATE cert_variants SET archived=1 WHERE id=?", (cv_id,))
    db.commit()
    r = c.post(f"/api/cert/variants/{cv_id}/archive",
               json={"archived": False, "backfill_recipient": "SHOULD_NOT_APPLY"})
    assert r.get_json()["backfill_count"] == 0
    rows = db.execute(
        "SELECT recipient_name FROM swiadectwa WHERE template_name='adam_partner'"
    ).fetchall()
    assert all(r["recipient_name"] is None for r in rows)


def test_archive_requires_admin_role(monkeypatch, db):
    c = _make_client(monkeypatch, db, rola="lab")
    cv_id = _seed_variant_with_history(db, cert_count=0)
    r = c.post(f"/api/cert/variants/{cv_id}/archive", json={"archived": True})
    assert r.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cert_flexibility.py -k "archive and not archive_preview" -v`
Expected: FAIL with 404 — endpoint missing.

- [ ] **Step 3: Add endpoint to `mbr/certs/routes.py`**

Insert after `api_cert_variant_archive_preview`. Make sure these imports exist at top: `from flask import session` and `from mbr.shared import audit` and `from mbr.certs.generator import _sanitize_filename_segment`.

```python
@certs_bp.route("/api/cert/variants/<int:variant_id>/archive", methods=["POST"])
@role_required("admin")
def api_cert_variant_archive(variant_id):
    """Soft-archive a cert variant; optionally backfill recipient_name on old certs.

    Payload:
        archived: bool (true → archive, false → unarchive)
        backfill_recipient: str | null (only honored when archived=true;
            sanitized via _sanitize_filename_segment before UPDATE)

    Idempotent: backfill UPDATEs rows WHERE recipient_name IS NULL only,
    so existing non-null values are never overwritten.
    """
    from mbr.shared import audit
    from mbr.certs.generator import _sanitize_filename_segment as _sanitize

    payload = request.get_json(silent=True) or {}
    archived = bool(payload.get("archived", True))
    backfill = payload.get("backfill_recipient")

    backfill_count = 0
    with db_session() as db:
        vrow = db.execute(
            "SELECT variant_id, label FROM cert_variants WHERE id=?",
            (variant_id,)).fetchone()
        if not vrow:
            abort(404)

        db.execute("UPDATE cert_variants SET archived=? WHERE id=?",
                   (1 if archived else 0, variant_id))
        audit.log_event(
            audit.EVENT_CERT_VARIANT_ARCHIVED if archived else audit.EVENT_CERT_VARIANT_UNARCHIVED,
            entity_type="cert_variant",
            entity_id=variant_id,
            entity_label=vrow["label"],
            payload={"variant_id": vrow["variant_id"]},
            db=db,
        )

        if archived and backfill:
            cleaned = _sanitize(backfill)
            if cleaned:
                cur = db.execute(
                    "UPDATE swiadectwa SET recipient_name=? "
                    "WHERE template_name=? AND recipient_name IS NULL",
                    (cleaned, vrow["variant_id"]))
                backfill_count = cur.rowcount
                if backfill_count > 0:
                    audit.log_event(
                        audit.EVENT_CERT_RECIPIENT_BACKFILLED,
                        entity_type="cert_variant",
                        entity_id=variant_id,
                        entity_label=vrow["label"],
                        payload={
                            "variant_id": vrow["variant_id"],
                            "recipient_name": cleaned,
                            "count": backfill_count,
                        },
                        db=db,
                    )
        db.commit()

    return jsonify({"ok": True, "archived": archived,
                    "backfill_count": backfill_count})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cert_flexibility.py -k "archive and not archive_preview" -v`
Expected: 7 tests PASS.

- [ ] **Step 5: Run full suite (regression check)**

Run: `pytest`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add mbr/certs/routes.py tests/test_cert_flexibility.py
git commit -m "feat(cert): POST /api/cert/variants/<id>/archive with optional recipient backfill"
```

---

## Task 13: `api_cert_generate` propagation of new fields

**Files:**
- Modify: `mbr/certs/routes.py:47-160` (extend `api_cert_generate`)
- Test: `tests/test_cert_flexibility.py` (extend)

This task threads `recipient_name`, `expiry_months_used`, and `has_order_number` through to all save sites: `generate_certificate_pdf` (which calls `build_context`), `save_certificate_pdf`, `save_certificate_data`, `create_swiadectwo`. Validation of `expiry_months` happens in `build_context` (already done in Task 7); route catches `ValueError` for proper 400 response.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cert_flexibility.py`:

```python
# ===========================================================================
# Task 13: api_cert_generate propagation
# ===========================================================================

def _seed_minimal_for_generate(db, produkt="TestProd"):
    """Seed product + variant + mbr_template + ebr (typ='zbiornik' so route allows cert).

    Note: produkt is on mbr_templates, NOT ebr_batches. get_ebr() resolves it
    via JOIN. This won't produce a valid PDF (no Gotenberg in tests), so the
    docx/gotenberg pipeline is monkeypatched in _patch_pdf_pipeline.
    """
    db.execute(
        "INSERT INTO produkty (nazwa, display_name, expiry_months) VALUES (?, ?, 12)",
        (produkt,),
    )
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label) VALUES (?, ?, ?)",
        (produkt, "base", produkt),
    )
    db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status, etapy_json, parametry_lab, dt_utworzenia) "
        "VALUES (?, 1, 'active', '[]', '{}', datetime('now'))",
        (produkt,),
    )
    db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, typ) "
        "VALUES (1, 'B001', '1/2026', datetime('now'), 'completed', 'zbiornik')"
    )
    db.commit()


def _patch_pdf_pipeline(monkeypatch, tmp_path):
    """Replace docxtpl/Gotenberg with stubs and redirect output to tmp_path."""
    import mbr.certs.generator as gen
    monkeypatch.setattr(gen, "_docxtpl_render", lambda ctx: b"DOCXBYTES")
    monkeypatch.setattr(gen, "_gotenberg_convert", lambda b: b"PDFBYTES")
    monkeypatch.setattr(gen, "OUTPUT_DIR", tmp_path / "data" / "swiadectwa")
    # Route uses Path.home() / "Desktop" if no output_dir is set; redirect.
    monkeypatch.setenv("HOME", str(tmp_path))


def test_generate_persists_recipient_and_expiry(monkeypatch, db, tmp_path):
    c = _make_client(monkeypatch, db)
    _seed_minimal_for_generate(db)
    _patch_pdf_pipeline(monkeypatch, tmp_path)
    r = c.post("/api/cert/generate", json={
        "ebr_id": 1, "variant_id": "base", "wystawil": "tester",
        "extra_fields": {"recipient_name": "ADAM&PARTNER", "expiry_months": 18},
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    row = db.execute(
        "SELECT recipient_name, expiry_months_used FROM swiadectwa "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["recipient_name"] == "ADAM&PARTNER"
    assert row["expiry_months_used"] == 18


def test_generate_default_expiry_when_no_override(monkeypatch, db, tmp_path):
    c = _make_client(monkeypatch, db)
    _seed_minimal_for_generate(db)
    _patch_pdf_pipeline(monkeypatch, tmp_path)
    r = c.post("/api/cert/generate", json={
        "ebr_id": 1, "variant_id": "base", "wystawil": "t",
        "extra_fields": {},
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    row = db.execute(
        "SELECT expiry_months_used FROM swiadectwa ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["expiry_months_used"] == 12  # from produkty.expiry_months


def test_generate_400_on_invalid_expiry(monkeypatch, db, tmp_path):
    c = _make_client(monkeypatch, db)
    _seed_minimal_for_generate(db)
    _patch_pdf_pipeline(monkeypatch, tmp_path)
    r = c.post("/api/cert/generate", json={
        "ebr_id": 1, "variant_id": "base", "wystawil": "t",
        "extra_fields": {"expiry_months": 50},
    })
    assert r.status_code == 400


def test_generate_recipient_sanitized_in_db(monkeypatch, db, tmp_path):
    c = _make_client(monkeypatch, db)
    _seed_minimal_for_generate(db)
    _patch_pdf_pipeline(monkeypatch, tmp_path)
    r = c.post("/api/cert/generate", json={
        "ebr_id": 1, "variant_id": "base", "wystawil": "t",
        "extra_fields": {"recipient_name": "AB/CD"},
    })
    assert r.status_code == 200
    row = db.execute(
        "SELECT recipient_name FROM swiadectwa ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["recipient_name"] == "ABCD"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cert_flexibility.py -k generate -v`
Expected: FAIL — `recipient_name`/`expiry_months_used` columns are NULL because route doesn't yet persist them.

- [ ] **Step 3: Modify `api_cert_generate`**

In `mbr/certs/routes.py`, find `api_cert_generate` (starts ~line 47). Locate the section that calls `generate_certificate_pdf` and `save_certificate_data` and `create_swiadectwo` (currently lines ~107-138). Restructure that section:

Replace the block from `try: pdf_bytes = generate_certificate_pdf(...)` through the `db.commit()` (currently lines 107-138) with:

```python
        # --- Resolve & sanitize runtime fields. ---
        from mbr.certs.generator import _sanitize_filename_segment
        recipient_raw = (extra_fields or {}).get("recipient_name", "")
        recipient_clean = _sanitize_filename_segment(recipient_raw) or None

        # Effective expiry: override (validated by build_context) or product default.
        expiry_override = (extra_fields or {}).get("expiry_months")
        if expiry_override is not None and str(expiry_override).strip():
            try:
                effective_expiry = int(expiry_override)
                if not (1 <= effective_expiry <= 30):
                    return jsonify({"ok": False,
                                    "error": f"expiry_months out of range 1..30"}), 400
            except (ValueError, TypeError):
                return jsonify({"ok": False,
                                "error": f"invalid expiry_months: {expiry_override!r}"}), 400
        else:
            prod_row = db.execute(
                "SELECT expiry_months FROM produkty WHERE nazwa=?", (target_produkt,)
            ).fetchone()
            effective_expiry = (prod_row["expiry_months"] if prod_row else None) or 12

        order_number = (extra_fields or {}).get("order_number", "") or ""
        has_order_number = bool(order_number.strip())

        # Mirror sanitized recipient back into extra_fields so build_context /
        # generate_certificate_pdf get the cleaned value (no template uses it,
        # but downstream snapshot in data_json does).
        if extra_fields is None:
            extra_fields = {}
        extra_fields["recipient_name"] = recipient_clean or ""

        try:
            pdf_bytes = generate_certificate_pdf(
                target_produkt, variant_id, ebr["nr_partii"],
                ebr.get("dt_start"), wyniki_flat, extra_fields,
                wystawil=wystawil,
            )
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
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
            "wyniki_flat": {k: {"wartosc": v.get("wartosc"),
                                "wartosc_text": v.get("wartosc_text"),
                                "w_limicie": v.get("w_limicie")}
                            for k, v in wyniki_flat.items()},
            "extra_fields": extra_fields,
            "wystawil": wystawil,
            "recipient_name": recipient_clean,
            "expiry_months_used": effective_expiry,
        }
        save_certificate_data(
            target_produkt, variant_label, ebr["nr_partii"], generation_data,
            recipient_name=recipient_clean, has_order_number=has_order_number,
        )

        # Persist target_produkt ONLY when it differs from ebr.produkt — NULL otherwise
        persist_target = target_produkt if target_produkt != ebr["produkt"] else None
        cert_id = create_swiadectwo(
            db, ebr_id, variant_label, ebr["nr_partii"], "regenerate", wystawil,
            data_json=_json.dumps(generation_data, ensure_ascii=False),
            target_produkt=persist_target,
            recipient_name=recipient_clean,
            expiry_months_used=effective_expiry,
        )
        db.commit()
```

Then locate the section further down in `api_cert_generate` where `save_certificate_pdf` is called (search for `save_certificate_pdf`). Pass new kwargs there too — find the call and replace with:

```python
        full_path = save_certificate_pdf(
            pdf_bytes, target_produkt, variant_label, ebr["nr_partii"],
            output_dir=output_dir,
            recipient_name=recipient_clean,
            has_order_number=has_order_number,
        )
```

(Locate the actual existing `save_certificate_pdf(...)` call in the route and add only the two new kwargs `recipient_name` and `has_order_number`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cert_flexibility.py -k generate -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Run full suite (regression check)**

Run: `pytest`
Expected: all green. Existing cert tests use `extra_fields={}` → recipient/expiry default branches.

- [ ] **Step 6: Commit**

```bash
git add mbr/certs/routes.py tests/test_cert_flexibility.py
git commit -m "feat(cert): api_cert_generate threads recipient/expiry/order_number to save sites"
```

---

## Task 14: UI laborant — modal restructure (3 stałe pola, always opens)

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html` (modal HTML + `issueCert()` JS)

This is a UI task — manually testable via browser. Code blocks below show exact HTML + JS to modify.

- [ ] **Step 1: Locate the cert popup HTML structure**

Run: `grep -n "cv-popup-overlay\|cv-popup-fields" mbr/templates/laborant/_fast_entry_content.html | head`

Expect: `cv-popup-overlay` div is the modal container; `cv-popup-fields` is the dynamic-fields container that today is populated by `issueCert()` based on `requiredFields`.

- [ ] **Step 2: Replace the modal HTML structure**

Find the `cv-popup-overlay` container (search for `cv-popup-overlay`) and locate the `cv-popup-fields` div inside it. Replace the inner content of the popup body so it has TWO sections — a static section (always visible) and a dynamic flag-fields section (conditional).

The new structure inside `cv-popup-overlay`:

```html
<div class="cv-popup-card">
  <h3>Wystaw świadectwo</h3>

  <!-- Always-visible runtime fields -->
  <div class="cv-popup-section">
    <div class="cv-popup-field">
      <label>Odbiorca (opcjonalny)</label>
      <div class="cv-recipient-wrap" style="position:relative;">
        <input type="text" id="cv-field-recipient_name" data-key="recipient_name"
               autocomplete="off" placeholder="Wpisz aby wyszukać poprzednie...">
        <div id="cv-recipient-suggestions" class="cv-suggestions"
             style="display:none; position:absolute; left:0; right:0; top:100%;
                    background:#fff; border:1px solid #ccc; max-height:200px;
                    overflow-y:auto; z-index:100;"></div>
      </div>
    </div>
    <div class="cv-popup-field">
      <label>Ważność (miesięcy)</label>
      <input type="number" id="cv-field-expiry_months" data-key="expiry_months"
             min="1" max="30" step="1">
    </div>
    <div class="cv-popup-field">
      <label>Numer zamówienia (opcjonalny)</label>
      <input type="text" id="cv-field-order_number" data-key="order_number">
    </div>
  </div>

  <!-- Variant-driven flag fields (rendered dynamically by issueCert) -->
  <div id="cv-popup-flag-fields-wrap" style="border-top:1px solid #eee;
       margin-top:10px; padding-top:10px; display:none;">
    <div style="font-size:11px; color:#888; margin-bottom:6px;">
      Pola wymagane przez wariant
    </div>
    <div id="cv-popup-fields"><!-- dynamic --></div>
  </div>

  <div class="cv-popup-actions">
    <button onclick="closeCertPopup()">Anuluj</button>
    <button onclick="confirmCertPopup()" class="primary">Wystaw</button>
  </div>
</div>
```

(Keep your existing CSS classes; the structural change is splitting into two sections.)

- [ ] **Step 3: Modify `issueCert()` to always open the modal**

In the same file, find the `issueCert(btn, variantId, targetProdukt, requiredFields)` function (around line 2572). Replace its body with:

```javascript
function issueCert(btn, variantId, targetProdukt, requiredFields, defaultExpiryMonths) {
    _pendingCert = {btn: btn, variantId: variantId, targetProdukt: targetProdukt};

    // Reset always-visible fields.
    document.getElementById('cv-field-recipient_name').value = '';
    document.getElementById('cv-field-expiry_months').value =
        (defaultExpiryMonths != null) ? defaultExpiryMonths : 12;
    document.getElementById('cv-field-order_number').value = '';
    document.getElementById('cv-recipient-suggestions').style.display = 'none';

    // Render variant-driven flag fields (excluding has_order_number — now always-on).
    var fieldsHtml = '';
    var fieldDefs = {
        'has_certificate_number': {label: 'Numer certyfikatu / Certificate No.', key: 'certificate_number'},
        'has_avon_code': {label: 'Kod AVON / AVON code', key: 'avon_code'},
        'has_avon_name': {label: 'Nazwa AVON / AVON name (INCI)', key: 'avon_name'},
    };
    var hasAny = false;
    (requiredFields || []).forEach(function(flag) {
        var def = fieldDefs[flag];
        if (def) {
            hasAny = true;
            fieldsHtml += '<div class="cv-popup-field">' +
                '<label>' + def.label + ' *</label>' +
                '<input type="text" id="cv-field-' + def.key + '" data-key="' + def.key + '">' +
                '</div>';
        }
    });
    document.getElementById('cv-popup-fields').innerHTML = fieldsHtml;
    document.getElementById('cv-popup-flag-fields-wrap').style.display =
        hasAny ? 'block' : 'none';

    document.getElementById('cv-popup-overlay').classList.add('active');
    setTimeout(function() {
        document.getElementById('cv-field-recipient_name').focus();
    }, 100);
}
```

- [ ] **Step 4: Update `confirmCertPopup` to read 3 always-fields + flag fields, validate expiry**

Replace the existing `confirmCertPopup` body with:

```javascript
function confirmCertPopup() {
    var extra = {};
    var valid = true;

    // Always-visible fields.
    var rec = document.getElementById('cv-field-recipient_name').value.trim();
    if (rec) extra.recipient_name = rec;

    var expEl = document.getElementById('cv-field-expiry_months');
    var expVal = parseInt(expEl.value, 10);
    if (!Number.isFinite(expVal) || expVal < 1 || expVal > 30) {
        expEl.style.borderColor = '#ef4444';
        valid = false;
    } else {
        expEl.style.borderColor = '';
        extra.expiry_months = expVal;
    }

    var ord = document.getElementById('cv-field-order_number').value.trim();
    if (ord) extra.order_number = ord;

    // Required (flag-driven) fields.
    var flagInputs = document.querySelectorAll('#cv-popup-fields input');
    flagInputs.forEach(function(inp) {
        var v = inp.value.trim();
        if (!v) { inp.style.borderColor = '#ef4444'; valid = false; }
        else { inp.style.borderColor = ''; extra[inp.dataset.key] = v; }
    });

    if (!valid) return;

    var btn = _pendingCert.btn;
    var variantId = _pendingCert.variantId;
    var targetProdukt = _pendingCert.targetProdukt;
    closeCertPopup();
    doGenerateCert(btn, variantId, targetProdukt, extra);
}
```

- [ ] **Step 5: Update the call site of `issueCert` to pass `defaultExpiryMonths`**

Run: `grep -n "issueCert(" mbr/templates/laborant/_fast_entry_content.html`

Find the call (one location, where buttons are dynamically rendered) and add `t.default_expiry_months` (the field returned by `api_cert_templates`) as the new last argument. Example:

Before:
```javascript
'<button class="cv-btn" onclick="issueCert(this, \'' + t.filename + '\', \'' + t.owner_produkt + '\', ' + rf + ')">…'
```

After:
```javascript
'<button class="cv-btn" onclick="issueCert(this, \'' + t.filename + '\', \'' + t.owner_produkt + '\', ' + rf + ', ' + (t.default_expiry_months || 12) + ')">…'
```

- [ ] **Step 6: Manual test**

Start the dev server: `python -m mbr.app`. In the browser:
1. Navigate to laborant fast-entry view of a completed szarża.
2. Click "Wystaw świadectwo" — modal must open every time, even for variants with no flag-required fields.
3. Confirm 3 always-visible fields appear: Odbiorca, Ważność (prefilled with product's expiry_months value), Numer zamówienia.
4. Confirm AVON variant still shows Kod AVON / Nazwa AVON below.
5. Confirm `has_order_number` no longer appears as a flag field (variants `nr_zam` show only the static order_number input).
6. Try invalid expiry (`0` or `99`) → red border, "Wystaw" doesn't fire.

- [ ] **Step 7: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat(laborant): cert modal always-open with recipient/expiry/order_number fields"
```

---

## Task 15: UI laborant — recipient autocomplete dropdown

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html` (add JS for autocomplete behavior)

- [ ] **Step 1: Add autocomplete script**

After `confirmCertPopup`, append this script block:

```javascript
(function() {
    var input = document.getElementById('cv-field-recipient_name');
    var dropdown = document.getElementById('cv-recipient-suggestions');
    if (!input || !dropdown) return;

    var debounceTimer = null;
    var lastQuery = '';

    function fetchSuggestions(q) {
        if (q.length < 2) {
            dropdown.style.display = 'none';
            return;
        }
        if (q === lastQuery) return;
        lastQuery = q;
        fetch('/api/cert/recipient-suggestions?q=' + encodeURIComponent(q))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (input.value.trim() !== q) return;  // user moved on
                renderDropdown(data.suggestions || []);
            })
            .catch(function() { dropdown.style.display = 'none'; });
    }

    function renderDropdown(suggestions) {
        if (!suggestions.length) {
            dropdown.style.display = 'none';
            return;
        }
        dropdown.innerHTML = suggestions.map(function(s) {
            var safe = s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            return '<div class="cv-suggestion-item" style="padding:6px 10px; cursor:pointer;"' +
                   ' onmouseover="this.style.background=\'#f0f0f0\';"' +
                   ' onmouseout="this.style.background=\'\';"' +
                   ' onclick="document.getElementById(\'cv-field-recipient_name\').value=' +
                   JSON.stringify(s) + '; document.getElementById(\'cv-recipient-suggestions\').style.display=\'none\';"' +
                   '>' + safe + '</div>';
        }).join('');
        dropdown.style.display = 'block';
    }

    input.addEventListener('input', function() {
        clearTimeout(debounceTimer);
        var q = input.value.trim();
        debounceTimer = setTimeout(function() { fetchSuggestions(q); }, 200);
    });

    input.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            dropdown.style.display = 'none';
        }
    });

    document.addEventListener('click', function(e) {
        if (!input.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.style.display = 'none';
        }
    });
})();
```

- [ ] **Step 2: Manual test**

Reload the page in browser. Open cert modal for any szarża. In Odbiorca:
1. Type 1 char → no fetch (threshold).
2. Type 2 chars → fetch fires after 200ms debounce; if any matches in DB, dropdown appears.
3. Click a suggestion → input populated, dropdown closes.
4. Esc → dropdown closes without selecting.
5. Click outside → dropdown closes.

To create test data quickly: generate a few certs with manually-typed recipients (e.g., "TESTOWY"), then revisit modal — typing "te" should suggest "TESTOWY".

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat(laborant): cert modal recipient autocomplete (debounce 200ms, threshold 2)"
```

---

## Task 16: UI admin — info-box, hide `has_order_number` checkbox, archived toggle

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html`

- [ ] **Step 1: Add deprecation info-box at top of Variants tab**

Run: `grep -n 'wc-tab\|Warianty\|tab-warianty\|wc-variants' mbr/templates/admin/wzory_cert.html | head`

Find the Variants tab content container. At the very top of the variants list section, insert:

```html
<div class="wc-info-box" style="margin-bottom:14px; padding:10px 14px;
     background:#fef9e7; border:1px solid #f5d76e; border-radius:6px;
     font-size:12px; color:#7e6500;">
  <strong>Warianty per-odbiorca są deprecjonowane.</strong>
  Używaj pola "Odbiorca" przy generowaniu świadectwa zamiast tworzenia
  osobnego wariantu. Definiuj warianty tylko gdy parametry / wymagania /
  opinie / flagi rzeczywiście się różnią.
</div>
```

- [ ] **Step 2: Hide `has_order_number` checkbox from variant flags UI**

Run: `grep -n "has_order_number" mbr/templates/admin/wzory_cert.html`

Find each location where the `has_order_number` checkbox is rendered (typically in HTML or inside JS variant-card builder). Comment out or remove the rendering for **just** this flag (other flags `has_rspo`, `has_avon_code`, `has_avon_name`, `has_certificate_number` stay). Look for code like:

```html
<label class="wc-flag">
  <input type="checkbox" data-flag="has_order_number"> Numer zamówienia
</label>
```

Wrap it in a comment or delete the entire `<label class="wc-flag">` block. If the flag is rendered from a JS array, remove the `'has_order_number'` entry from that array.

To verify all rendering paths covered, search again: `grep -n "has_order_number" mbr/templates/admin/wzory_cert.html` — ideally the only remaining references are reading the flag from incoming JSON (don't break those — backend still has the flag in `flags` array of legacy variants).

- [ ] **Step 3: Add "Pokaż archiwalne warianty" toggle**

Above the variants list (next to or just under the info-box), add:

```html
<label style="display:inline-flex; gap:6px; align-items:center;
       font-size:12px; cursor:pointer; margin-bottom:10px;">
  <input type="checkbox" id="wc-show-archived-variants" onchange="reloadVariantList()">
  Pokaż archiwalne warianty
</label>
```

Then update the existing variant-list reload function (search for the function that loads variants — typically calls `/api/cert/templates` or similar admin-specific endpoint). Wherever `variants` are fetched, conditionally append `?include_archived=1` when the checkbox is on.

For example, if the existing fetch is:

```javascript
fetch('/api/cert/templates?produkt=' + key)
```

Change to:

```javascript
var includeArchived = document.getElementById('wc-show-archived-variants').checked ? '&include_archived=1' : '';
fetch('/api/cert/templates?produkt=' + key + includeArchived)
```

(If the admin editor uses a different endpoint to load variant list, search for the actual fetch URL and add `include_archived=1` analogously.)

- [ ] **Step 4: Style archived variants visually**

In the variant card render path (search for `wc-vcard` class), conditionally add an `archived` class when `variant.archived === 1` or similar property comes back from the API. Add CSS:

```css
.wc-vcard.archived {
    opacity: 0.55;
    border-style: dashed;
}
.wc-vcard.archived .wc-vtitle::after {
    content: ' (archiwalny)';
    font-weight: 400;
    color: var(--text-dim);
    font-size: 11px;
}
```

- [ ] **Step 5: Manual test**

Start dev server, open `/admin/wzory-cert`. Pick any product. In Warianty tab:
1. Info-box visible at top.
2. Variant flag list — confirm `has_order_number` checkbox NOT shown (other flags still there).
3. Archive a variant via button (will be added in Task 17). Toggle "Pokaż archiwalne" — archived variants appear with dashed border, faded.

- [ ] **Step 6: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(wzory-cert): info-box + hide has_order_number flag + archived toggle"
```

---

## Task 17: UI admin — archive button + backfill modal

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html`

- [ ] **Step 1: Add Archive/Unarchive button to variant card**

In the variant card render path (where the existing per-variant buttons live, e.g. delete/edit), add a new button:

```html
<button class="wc-btn wc-btn-sm" onclick="openArchiveModal({{ variant.id }}, '{{ variant.label|e }}')">
  Archiwizuj
</button>
```

(Or if archived: button reads "Przywróć" and calls a different handler.)

If the variant is rendered from JS:

```javascript
var btnHtml = variant.archived
    ? '<button class="wc-btn wc-btn-sm" onclick="unarchiveVariant(' + variant.id + ')">Przywróć</button>'
    : '<button class="wc-btn wc-btn-sm" onclick="openArchiveModal(' + variant.id + ', ' + JSON.stringify(variant.label) + ')">Archiwizuj</button>';
```

- [ ] **Step 2: Add backfill modal HTML structure**

At the end of the wzory_cert template body (before closing `{% endblock %}`), insert:

```html
<div id="wc-archive-modal" style="display:none; position:fixed; inset:0;
     background:rgba(0,0,0,0.45); z-index:1000; align-items:center;
     justify-content:center;">
  <div style="background:#fff; padding:24px 28px; border-radius:10px;
       max-width:520px; width:90%; box-shadow:0 10px 40px rgba(0,0,0,0.2);">
    <h3 id="wc-archive-modal-title" style="margin:0 0 14px; font-size:15px;">
      Archiwizuj wariant
    </h3>
    <p id="wc-archive-modal-count" style="font-size:12px; color:#555; margin:0 0 12px;"></p>
    <p style="font-size:12px; color:#555; margin:0 0 6px;">
      Możesz wpisać nazwę odbiorcy by uzupełnić ją wstecznie w starych
      świadectwach tego wariantu — ułatwi to autocomplete przy przyszłych
      certach.
    </p>
    <label style="display:block; font-size:11px; color:#888; margin-bottom:4px;">
      Recipient (opcjonalny):
    </label>
    <input type="text" id="wc-archive-modal-recipient" autocomplete="off"
           style="width:100%; padding:7px 10px; border:1.5px solid #ccc;
                  border-radius:6px; font-size:12px; box-sizing:border-box;">
    <p style="font-size:10px; color:#888; margin-top:4px;">
      Propozycja sparsowana z label'a wariantu — możesz edytować lub usunąć.
    </p>
    <div style="display:flex; gap:10px; justify-content:flex-end; margin-top:18px;">
      <button class="wc-btn wc-btn-o" onclick="closeArchiveModal()">Anuluj</button>
      <button class="wc-btn wc-btn-o" onclick="submitArchive(false)">Archiwizuj bez backfill</button>
      <button class="wc-btn wc-btn-p" onclick="submitArchive(true)">Archiwizuj + backfill</button>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Add modal logic JS**

Append script:

```javascript
var _archivePending = {variantId: null};

function openArchiveModal(variantId, label) {
    _archivePending.variantId = variantId;
    fetch('/api/cert/variants/' + variantId + '/archive-preview')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            document.getElementById('wc-archive-modal-title').textContent =
                'Archiwizuj wariant: ' + label;
            document.getElementById('wc-archive-modal-count').textContent =
                'Znaleziono ' + data.swiadectwa_count +
                ' świadectw wystawionych z tego wariantu z pustym polem recipient_name.';
            document.getElementById('wc-archive-modal-recipient').value =
                data.suggested_recipient || '';
            document.getElementById('wc-archive-modal').style.display = 'flex';
        });
}

function closeArchiveModal() {
    document.getElementById('wc-archive-modal').style.display = 'none';
    _archivePending.variantId = null;
}

function submitArchive(withBackfill) {
    var variantId = _archivePending.variantId;
    if (!variantId) return;
    var body = {archived: true};
    if (withBackfill) {
        var rec = document.getElementById('wc-archive-modal-recipient').value.trim();
        if (rec) body.backfill_recipient = rec;
    }
    fetch('/api/cert/variants/' + variantId + '/archive', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        closeArchiveModal();
        reloadVariantList();
    })
    .catch(function(e) { alert('Błąd archiwizacji: ' + e); });
}

function unarchiveVariant(variantId) {
    fetch('/api/cert/variants/' + variantId + '/archive', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({archived: false}),
    })
    .then(function() { reloadVariantList(); });
}
```

(`reloadVariantList` is the existing function — adjust the name if the file uses something else like `loadVariants()`.)

- [ ] **Step 4: Manual test**

In `/admin/wzory-cert`, pick a product with multiple variants:
1. Click "Archiwizuj" on a variant with em-dash label like `Chegina K7 — ADAM&PARTNER` → modal opens. Count of certs shown. Recipient input prefilled with "ADAM&PARTNER".
2. Click "Archiwizuj + backfill" → modal closes, variant list refreshes, that variant disappears (or shows dashed if "Pokaż archiwalne" is on).
3. Verify in DB:
   ```bash
   sqlite3 data/batch_db.sqlite "SELECT recipient_name FROM swiadectwa WHERE template_name='adam_partner' LIMIT 3"
   ```
   Should show `ADAM&PARTNER` for previously NULL rows.
4. Toggle "Pokaż archiwalne" on → archived variant appears dashed/faded with "Przywróć" button.
5. Click "Przywróć" → variant unarchived; backfilled `recipient_name` values stay (intentional).
6. Try archive on variant without em-dash label → modal opens with empty Recipient field; user can type or skip.

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(wzory-cert): archive button + backfill modal for variant deprecation"
```

---

## Task 18: Final integration test + smoke run

**Files:**
- (no code changes — verification only)

- [ ] **Step 1: Run full test suite**

Run: `pytest`
Expected: all tests PASS, no warnings, no skipped tests related to this feature.

- [ ] **Step 2: Smoke test end-to-end in browser**

Start dev server: `python -m mbr.app` (port 5001). Walk through:

1. **As laborant**: open a completed szarża, click "Wystaw świadectwo" on a `base` variant.
   - Modal opens with 3 fields visible: Odbiorca (empty), Ważność (prefilled e.g. 12), Numer zamówienia (empty).
   - Type "TEST RECIPIENT" in Odbiorca, change Ważność to 18, type "ZAM-001" in Numer zamówienia.
   - Click "Wystaw". PDF downloads. Filename: `<Produkt> — TEST RECIPIENT 4 (NRZAM).pdf`.
2. **Verify DB**:
   ```bash
   sqlite3 data/batch_db.sqlite "SELECT recipient_name, expiry_months_used FROM swiadectwa ORDER BY id DESC LIMIT 1"
   ```
   Should show: `TEST RECIPIENT|18`.
3. **Repeat the same generate** with same inputs (re-issue) → second PDF saved as `<Produkt> — TEST RECIPIENT 4 (NRZAM) (2).pdf`. First file preserved.
4. **As admin** (`/admin/wzory-cert`): pick the same product, archive a customer-name variant via button + backfill modal. Verify:
   - Variant disappears from default view.
   - Toggle "Pokaż archiwalne" → reappears, dashed/faded, "Przywróć" button.
   - DB: `swiadectwa.recipient_name` for old certs of that variant updated (or NULL where IS NOT NULL was already set).
5. **Autocomplete**: in laborant cert modal, type 2+ chars matching the recipient you just entered → suggestion appears in dropdown.

- [ ] **Step 3: Commit (if any cleanup needed)**

```bash
# If smoke test surfaced no issues, just confirm clean working tree:
git status
# Expected: clean (no uncommitted changes).
```

If smoke test surfaced issues, fix them and commit:

```bash
git add <files>
git commit -m "fix(cert): <specific fix from smoke test>"
```

---

## Done

After Task 18 passes cleanly:

- ✅ Schema migrations live (`recipient_name`, `expiry_months_used`, `archived`).
- ✅ Generator handles new runtime fields end-to-end.
- ✅ Routes propagate, validate, and persist all 3 new fields.
- ✅ Laborant modal — always-on 3 fields + autocomplete + inline expiry validation.
- ✅ Admin editor — info-box + archive button + backfill modal + archived toggle + hidden `has_order_number` checkbox.
- ✅ Tests green, manual smoke test passing.

**User does manually (out of plan scope):** Review existing `cert_variants` rows and archive customer-name / `nr_zam` duplicates with appropriate backfill values via the new admin UI. No automation — explicit user decision per the spec's non-goals.
