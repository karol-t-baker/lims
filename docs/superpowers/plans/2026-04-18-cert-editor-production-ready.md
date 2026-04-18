# Edytor świadectw — plan wdrożenia "na gotowo"

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dopiąć edytor świadectw tak, żeby mógł pracować produkcyjnie — poszerzyć tabelę w PDF, dać globalne ustawienia typografii, kopiowanie wzoru, pełny rejestr parametrów w dropdownie, dirty state + walidacja UI-side + zakładka historii + auto-refresh podglądu.

**Architecture:** Flask monolit + SQLite. Backend: nowa tabela `cert_settings` (key-value dla fontu i rozmiaru nagłówka), nowe endpointy REST w `certs_bp`, rozluźniony filtr w `parametry_bp`, DOCX template z `{{ }}` placeholderami czytanymi z cert_settings. Frontend: zmiany w `wzory_cert.html` (modal settings, button kopiuj, dirty flag, UI walidacja, historia, auto-refresh). Audyt: nowy event `CERT_SETTINGS_UPDATED`, rozszerzenie filtra `entity_label` w `query_audit_log`.

**Tech Stack:** Python 3 · Flask · sqlite3 (raw, no ORM) · docxtpl + Gotenberg · Jinja2 templates · Vanilla JS (no framework) · pytest (in-memory SQLite).

**Uwaga o umiejscowieniu:** Spec wskazywał `ustawienia.html` dla admin UI. Ten plan odchodzi — `ustawienia.html` to PER-USER settings (`user_settings` keyed by login), więc dodanie tam globalnych cert-settings mieszałoby scope. Zamiast tego: modal "Ustawienia globalne" w `wzory_cert.html` (ta sama strona, ten sam RBAC). Odnotowane.

**Uwaga o spec_blocie:** Endpoint audit-history w specu miał używać istniejącego `query_audit_history_for_entity(db, entity_type, entity_id)`, ale ten helper filtruje po `entity_id: int`. Cert config jest identyfikowany przez `entity_label` (string = produkt key). Plan dodaje `entity_label` param do `_build_where_clauses` / `query_audit_log` i sibling-helper `query_audit_history_by_label`.

---

## File Structure

### Utworzone

- `docs/superpowers/plans/2026-04-18-cert-editor-production-ready.md` — ten plan.

### Zmodyfikowane

- `mbr/models.py` — `init_mbr_tables`: migracja `cert_settings` table + seed defaultów.
- `mbr/shared/audit.py` — nowy event `EVENT_CERT_SETTINGS_UPDATED` + `entity_label` filter w `_build_where_clauses` + `query_audit_history_by_label` helper.
- `mbr/certs/generator.py` — `_load_cert_settings(db)` helper; `build_context` i `build_preview_context` wrzucają `body_font_family` + `header_font_size_pt` do context-u; `_md_to_richtext` obsługuje `|` → line break; globalne `_CERT_FONT` i `_CERT_SIZE` czytane z settings.
- `mbr/certs/routes.py` — GET/PUT `/api/cert/settings`, POST `/api/cert/config/product/<src>/copy`, GET `/api/cert/config/product/<key>/audit-history`.
- `mbr/parametry/routes.py` — `api_parametry_available` zwraca pełny rejestr z flag `in_mbr`.
- `mbr/templates/cert_master_template.docx` — geometria (marginesy 13mm, kolumny 94/38/35/17mm), `{{ }}` dla fontu i rozmiaru nagłówka. Binary file — edytowany poprzez unzip/edit/repack.
- `mbr/templates/admin/wzory_cert.html` — modal globalnych ustawień, przycisk Kopiuj na kartach, dirty flag/beforeunload/Powrót confirm, UI walidacja, dropdown z flag `in_mbr`, zakładka Historia, auto-refresh podglądu.
- `deploy/gotenberg.service` — *warunkowo* volume z `.ttf` fontu, jeśli offline Gotenberg (decyzja w Tasku 5).
- `tests/test_certs.py` — nowe testy.
- `tests/test_cert_editor_atomicity.py` — ewentualne rozszerzenia istniejących testów.

### Nietykane (explicite)

- `mbr/templates/paliwo_master*.docx` — poza zakresem.
- `mbr/templates/ustawienia.html` — per-user scope, nie mieszamy.
- `cert_config.json` — regenerowany automatycznie przez istniejący `save_cert_config_export`.

---

## Task 1: Migracja `cert_settings` table + seed

**Files:**
- Modify: `mbr/models.py:1104-1155` (w bloku migracji, obok `parametry_cert`/`cert_variants`)
- Test: `tests/test_certs.py`

- [ ] **Step 1: Napisz failing test**

Dodaj na końcu `tests/test_certs.py`:

```python
# ---------------------------------------------------------------------------
# cert_settings
# ---------------------------------------------------------------------------

def test_cert_settings_table_exists(db):
    """init_mbr_tables must create cert_settings."""
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='cert_settings'"
    ).fetchall()
    assert len(rows) == 1


def test_cert_settings_default_seed(db):
    """Defaults must be seeded on first init."""
    rows = dict(db.execute("SELECT key, value FROM cert_settings").fetchall())
    assert rows["body_font_family"] == "TeX Gyre Bonum"
    assert rows["header_font_size_pt"] == "14"


def test_cert_settings_init_idempotent(db):
    """Re-running init_mbr_tables doesn't duplicate seed rows."""
    from mbr.models import init_mbr_tables
    init_mbr_tables(db)
    init_mbr_tables(db)
    rows = db.execute("SELECT key FROM cert_settings").fetchall()
    keys = [r["key"] for r in rows]
    assert len(keys) == len(set(keys)), f"duplicate keys: {keys}"
```

- [ ] **Step 2: Uruchom test — powinien failować**

Run: `pytest tests/test_certs.py::test_cert_settings_table_exists tests/test_certs.py::test_cert_settings_default_seed tests/test_certs.py::test_cert_settings_init_idempotent -v`
Expected: FAIL — `no such table: cert_settings`.

- [ ] **Step 3: Dodaj migrację w `init_mbr_tables`**

W `mbr/models.py`, po bloku `cert_variants` (ok. linia 1141), dodaj:

```python
    # Migration: create cert_settings table (global certificate typography)
    db.execute("""
        CREATE TABLE IF NOT EXISTS cert_settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    db.commit()

    # Seed defaults (INSERT OR IGNORE — idempotent, preserves existing overrides)
    _cert_settings_defaults = [
        ("body_font_family", "TeX Gyre Bonum"),
        ("header_font_size_pt", "14"),
    ]
    for k, v in _cert_settings_defaults:
        db.execute(
            "INSERT OR IGNORE INTO cert_settings (key, value) VALUES (?, ?)",
            (k, v),
        )
    db.commit()
```

- [ ] **Step 4: Uruchom testy — powinny przechodzić**

Run: `pytest tests/test_certs.py -k cert_settings -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add mbr/models.py tests/test_certs.py
git commit -m "feat(certs): add cert_settings table for global typography"
```

---

## Task 2: Audit event `CERT_SETTINGS_UPDATED` + `entity_label` filter

**Files:**
- Modify: `mbr/shared/audit.py:66-74` (events section), `mbr/shared/audit.py:321-364` (`_build_where_clauses`), `mbr/shared/audit.py:367-426` (`query_audit_log`), dodanie nowego helper-a po `query_audit_history_for_entity`
- Test: `tests/test_audit_helper.py`

- [ ] **Step 1: Failing test na nowy event i helper**

Dodaj na końcu `tests/test_audit_helper.py`:

```python
def test_event_cert_settings_updated_exists():
    from mbr.shared import audit
    assert audit.EVENT_CERT_SETTINGS_UPDATED == "cert.settings.updated"


def test_query_audit_history_by_label_filters_on_label(db_with_audit):
    """Filter by entity_label (string key) — used for cert config history per-product."""
    from mbr.shared import audit
    # Two events for same cert but different entity_label
    audit.log_event(
        audit.EVENT_CERT_CONFIG_UPDATED,
        entity_type="cert",
        entity_label="K40GLOL",
        payload={"params_count": 12},
        actors=[{"worker_id": None, "actor_login": "admin", "actor_rola": "admin", "actor_name": "admin"}],
        db=db_with_audit,
    )
    audit.log_event(
        audit.EVENT_CERT_CONFIG_UPDATED,
        entity_type="cert",
        entity_label="GLOL40",
        payload={"params_count": 8},
        actors=[{"worker_id": None, "actor_login": "admin", "actor_rola": "admin", "actor_name": "admin"}],
        db=db_with_audit,
    )
    db_with_audit.commit()

    history = audit.query_audit_history_by_label(db_with_audit, "cert", "K40GLOL")
    assert len(history) == 1
    assert history[0]["entity_label"] == "K40GLOL"
    assert history[0]["payload_json"] and "12" in history[0]["payload_json"]
```

Jeśli `db_with_audit` fixture nie istnieje, dodaj u góry pliku:

```python
@pytest.fixture
def db_with_audit(db):
    # audit_log table is created by init_mbr_tables — the `db` fixture
    # in this file already runs it. No extra setup needed.
    return db
```

(Najpierw sprawdź nagłówek pliku — `db` fixture już tam jest.)

- [ ] **Step 2: Uruchom test — powinien failować**

Run: `pytest tests/test_audit_helper.py::test_event_cert_settings_updated_exists tests/test_audit_helper.py::test_query_audit_history_by_label_filters_on_label -v`
Expected: FAIL — `AttributeError: EVENT_CERT_SETTINGS_UPDATED` i/lub `query_audit_history_by_label`.

- [ ] **Step 3: Dodaj event constant**

W `mbr/shared/audit.py`, po linii 69 (`EVENT_CERT_CONFIG_UPDATED`):

```python
EVENT_CERT_SETTINGS_UPDATED = "cert.settings.updated"
```

- [ ] **Step 4: Rozszerz `_build_where_clauses` o `entity_label`**

W `_build_where_clauses` (ok. lina 321-364), dodaj parametr i clause:

```python
def _build_where_clauses(*, dt_from=None, dt_to=None, event_type_glob=None,
                        entity_type=None, entity_id=None, entity_label=None,
                        worker_id=None, free_text=None, request_id=None) -> tuple:
    """Translate filter args into a (where_sql, params) tuple."""
    clauses = []
    params = []
    # ... existing dt_from / dt_to / event_type_glob / entity_type handling ...
```

Po bloku `entity_type` (ok. linia 344) dodaj:

```python
    if entity_label is not None:
        clauses.append("entity_label = ?")
        params.append(entity_label)
```

- [ ] **Step 5: Przebij `entity_label` przez `query_audit_log`**

W `query_audit_log` (ok. lina 367-396), dopisz parametr do signature i przekaż niżej:

```python
def query_audit_log(
    db,
    *,
    dt_from: str = None,
    dt_to: str = None,
    event_type_glob: str = None,
    entity_type: str = None,
    entity_id: int = None,
    entity_label: str = None,
    worker_id: int = None,
    free_text: str = None,
    request_id: str = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple:
```

W wywołaniu `_build_where_clauses` (ok. lina 392):

```python
    where_sql, params = _build_where_clauses(
        dt_from=dt_from, dt_to=dt_to, event_type_glob=event_type_glob,
        entity_type=entity_type, entity_id=entity_id, entity_label=entity_label,
        worker_id=worker_id, free_text=free_text, request_id=request_id,
    )
```

- [ ] **Step 6: Dodaj `query_audit_history_by_label`**

Po `query_audit_history_for_entity` (ok. lina 443), dodaj:

```python
def query_audit_history_by_label(db, entity_type: str, entity_label: str) -> list:
    """Per-label history for non-numeric-id entities (cert config is keyed by produkt string).

    Returns rows sorted dt DESC with actors joined. No pagination — label-keyed
    histories are bounded (typical product has <100 config edits in its lifetime).
    """
    rows, _total = query_audit_log(
        db,
        entity_type=entity_type,
        entity_label=entity_label,
        limit=1000,
        offset=0,
    )
    return rows
```

- [ ] **Step 7: Testy zielone**

Run: `pytest tests/test_audit_helper.py -v`
Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add mbr/shared/audit.py tests/test_audit_helper.py
git commit -m "feat(audit): cert.settings.updated event + entity_label filter"
```

---

## Task 3: `_load_cert_settings` helper + integracja w generatorze

**Files:**
- Modify: `mbr/certs/generator.py` (dodać helper, wywołać w `build_context` + `build_preview_context`)
- Test: `tests/test_certs.py`

- [ ] **Step 1: Failing test na helper + context**

W `tests/test_certs.py` dodaj:

```python
def test_load_cert_settings_returns_seeded_defaults(db):
    from mbr.certs.generator import _load_cert_settings
    s = _load_cert_settings(db)
    assert s["body_font_family"] == "TeX Gyre Bonum"
    assert s["header_font_size_pt"] == 14  # int, parsed from "14"


def test_load_cert_settings_reads_override(db):
    db.execute("UPDATE cert_settings SET value=? WHERE key=?", ("EB Garamond", "body_font_family"))
    db.execute("UPDATE cert_settings SET value=? WHERE key=?", ("18", "header_font_size_pt"))
    db.commit()
    from mbr.certs.generator import _load_cert_settings
    s = _load_cert_settings(db)
    assert s["body_font_family"] == "EB Garamond"
    assert s["header_font_size_pt"] == 18


def test_build_preview_context_includes_typography(db):
    """build_preview_context must surface cert_settings in the render context."""
    # Minimal product JSON
    product = {
        "display_name": "Test",
        "spec_number": "P001",
        "cas_number": "",
        "expiry_months": 12,
        "opinion_pl": "",
        "opinion_en": "",
        "parameters": [],
        "variants": [{"id": "base", "label": "Test", "flags": [], "overrides": {}}],
    }
    # Needs app context / db_session for _load_cert_settings — patch
    import unittest.mock as mock
    with mock.patch("mbr.certs.generator._load_cert_settings",
                    return_value={"body_font_family": "EB Garamond", "header_font_size_pt": 18}):
        from mbr.certs.generator import build_preview_context
        ctx = build_preview_context(product, "base")
    assert ctx["body_font_family"] == "EB Garamond"
    assert ctx["header_font_size_pt"] == 18
```

- [ ] **Step 2: Uruchom test — failuje**

Run: `pytest tests/test_certs.py -k "load_cert_settings or includes_typography" -v`
Expected: FAIL — `ImportError: cannot import name '_load_cert_settings'` / `KeyError: 'body_font_family'`.

- [ ] **Step 3: Dodaj `_load_cert_settings` helper**

W `mbr/certs/generator.py`, po `_md_to_richtext` (ok. lina 50), dodaj:

```python
def _load_cert_settings(db) -> dict:
    """Load typography settings from cert_settings table.

    Returns dict with typed values:
      - body_font_family: str
      - header_font_size_pt: int

    Missing keys fall back to defaults (same as seed in init_mbr_tables).
    """
    defaults = {"body_font_family": "TeX Gyre Bonum", "header_font_size_pt": 14}
    rows = db.execute("SELECT key, value FROM cert_settings").fetchall()
    out = dict(defaults)
    for r in rows:
        k = r["key"]
        v = r["value"]
        if k == "header_font_size_pt":
            try:
                out[k] = int(v)
            except (ValueError, TypeError):
                out[k] = defaults[k]
        else:
            out[k] = v
    return out
```

- [ ] **Step 4: Wrzuć settings do `build_context`**

W `mbr/certs/generator.py::build_context` (ok. linia 172, wewnątrz `with _db_session() as db:`), na samej górze bloku `with` dodaj:

```python
        _settings = _load_cert_settings(db)
```

W zwracanym dict-u na końcu funkcji (ok. linia 340-359), dodaj dwa klucze:

```python
    return {
        "company": cfg["company"],
        # ... existing keys ...
        "wystawil": wystawil,
        "body_font_family": _settings["body_font_family"],
        "header_font_size_pt": _settings["header_font_size_pt"],
    }
```

- [ ] **Step 5: Wrzuć settings do `build_preview_context`**

`build_preview_context` nie ma własnego `db` — otwórz session. Na początku funkcji (ok. linia 374, po `cfg = load_config()`):

```python
    from mbr.db import db_session as _db_session
    with _db_session() as _db:
        _settings = _load_cert_settings(_db)
```

W dict-u zwracanym na końcu (ok. linia 459):

```python
    return {
        "company": company,
        # ... existing keys ...
        "wystawil": "Podgląd",
        "body_font_family": _settings["body_font_family"],
        "header_font_size_pt": _settings["header_font_size_pt"],
    }
```

- [ ] **Step 6: Przełącz `_CERT_FONT` i `_CERT_SIZE` (globalne stałe) na settings**

Problem: `_md_to_richtext` używa globalnych `_CERT_FONT` i `_CERT_SIZE`. Chcemy też, żeby parametry renderowały się w fontie z settings.

Refactor — `_md_to_richtext` przyjmuje `font` i `size` jako opcjonalne argumenty z domyślnymi wartościami = obecne stałe (backward-compat):

```python
def _md_to_richtext(text: str, *, font: str = None, size: int = None) -> RichText:
    """Convert a string with `^{sup}` / `_{sub}` markers into a docxtpl RichText.

    font/size default to module constants (_CERT_FONT / _CERT_SIZE) — callers
    with per-render settings should pass explicit values.
    """
    font = font or _CERT_FONT
    size = size or _CERT_SIZE
    rt = RichText()
    if not text:
        return rt
    for part in _RT_RE.split(text):
        if not part:
            continue
        if part.startswith("^{") and part.endswith("}"):
            rt.add(part[2:-1], superscript=True, font=font, size=size)
        elif part.startswith("_{") and part.endswith("}"):
            rt.add(part[2:-1], subscript=True, font=font, size=size)
        else:
            rt.add(part, font=font, size=size)
    return rt
```

Wywołania w `build_context` i `build_preview_context` — przekaż `font=_settings["body_font_family"]` (rozmiar parametrów to inna sprawa niż `header_font_size_pt` — body size zostaje dzisiejsze 22/11pt; header size wchodzi w docxtpl context tylko dla nagłówka nazwy produktu w template-cie, nie dla wierszy).

W `build_context`, w pętli tworzącej `rows`:

```python
            rows.append({
                "name_pl": _md_to_richtext(name_pl, font=_settings["body_font_family"]),
                "name_en": _md_to_richtext(f"/{name_en}", font=_settings["body_font_family"]) if name_en else None,
                "requirement": r["requirement"],
                "method": method,
                "result": result,
            })
```

W `build_preview_context` analogicznie:

```python
        rows.append({
            "name_pl": _md_to_richtext(param.get("name_pl", ""), font=_settings["body_font_family"]),
            "name_en": _md_to_richtext(f"/{_ne}", font=_settings["body_font_family"]) if _ne else None,
            "requirement": param.get("requirement", ""),
            "method": param.get("method", ""),
            "result": result,
        })
```

- [ ] **Step 7: Testy zielone**

Run: `pytest tests/test_certs.py -k "load_cert_settings or includes_typography" -v`
Expected: 3 passed.

- [ ] **Step 8: Pełna suita testów cert — sprawdź brak regresji**

Run: `pytest tests/test_certs.py tests/test_cert_editor_atomicity.py -v`
Expected: All pass.

- [ ] **Step 9: Commit**

```bash
git add mbr/certs/generator.py tests/test_certs.py
git commit -m "feat(certs): generator reads body_font from cert_settings"
```

---

## Task 4: DOCX template — geometria + placeholdery typografii

**Files:**
- Modify: `mbr/templates/cert_master_template.docx` (binary; edytowany jako zip)

> **Uwaga TDD:** DOCX-binary nie nadaje się do unit-testu pre/post na treść XML — zamiast tego robimy **integration test**: render `build_preview_context` → `_docxtpl_render` → assert że wygenerowany DOCX zawiera nowe placeholdery w spodziewanych wartościach (font name, header size). To już test z `test_includes_typography` w Tasku 3.

Dodatkowo — po podmianie DOCX robimy **smoke test przez Gotenberga**: jeśli Gotenberg działa lokalnie, generujemy PDF dla jednego produktu i wizualnie sprawdzamy. Jeśli nie, robimy tylko render DOCX i sprawdzamy assercje na XML.

- [ ] **Step 1: Rozpakuj DOCX do tymczasowego folderu**

```bash
cd /tmp && rm -rf cert_template_edit && mkdir cert_template_edit && cd cert_template_edit
unzip -q /Users/tbk/Desktop/lims-clean/mbr/templates/cert_master_template.docx
```

- [ ] **Step 2: Zmień geometrię strony w `word/document.xml`**

Edit `/tmp/cert_template_edit/word/document.xml`. Zmień:

- `<w:pgMar ... w:right="1134" ... w:left="1134" .../>` → `w:right="737"`, `w:left="737"` (marginesy 13mm)
- `<w:tblW w:w="9677" w:type="dxa"/>` → `<w:tblW w:w="10432" w:type="dxa"/>` (171mm → 184mm)
- gridCols: `<w:gridCol w:w="4471"/>` → `5330`, `<w:gridCol w:w="2127"/>` → zostaje, `<w:gridCol w:w="1984"/>` → zostaje, `<w:gridCol w:w="1095"/>` → `991` (95mm/38mm/35mm/18mm)

Docelowy gridCol: `5330 + 2127 + 1984 + 991 = 10432` — spójne z tblW.

**Wszystkie w:tcW w wierszach** też muszą się zmienić — wyszukaj `<w:tcW w:w="4471"` i zamień na `5330` globalnie w pliku, analogicznie dla `1095` → `991`. Użyj:

```bash
sed -i '' 's/w:w="4471"/w:w="5330"/g; s/w:w="1095"/w:w="991"/g' /tmp/cert_template_edit/word/document.xml
```

Sprawdź (BSD sed na macOS): brak opcji `-i ''`? Dostosuj do GNU sed w dev-env.

Marginesy i tblW edytuj ręcznie (punktowo) — `sed` może przypadkowo zamienić inne liczby.

- [ ] **Step 3: Dodaj `{{ }}` placeholdery dla fontu i nagłówka**

W `word/document.xml` znajdź fragment renderujący `{{ display_name }}` (nagłówek "Nazwa produktu" na górze). Zmień jego styl na:

- `<w:rFonts w:ascii="TeX Gyre Bonum" w:hAnsi="TeX Gyre Bonum"/>` → `<w:rFonts w:ascii="{{ body_font_family }}" w:hAnsi="{{ body_font_family }}"/>`
- `<w:sz w:val="<obecny rozmiar>"/>` → `<w:sz w:val="{{ header_font_size_pt * 2 }}"/>` (docxtpl w:sz to half-points, więc pt * 2)

**Uwaga**: w:sz musi być **liczbą**. `{{ header_font_size_pt * 2 }}` przez docxtpl powinno zadziałać — docxtpl evaluate expression w Jinja2.

Zmień analogicznie w **styles.xml** jeśli font body jest tam zdefiniowany globalnie, nie w document.xml. Sprawdź:

```bash
grep -n "TeX Gyre Bonum" /tmp/cert_template_edit/word/*.xml
```

Jeśli wystąpienia też w `styles.xml` (najpewniej), zamień globalne definicje fontu na `{{ body_font_family }}`.

- [ ] **Step 4: Repack DOCX**

```bash
cd /tmp/cert_template_edit
zip -r -X cert_master_template.docx '[Content_Types].xml' _rels customXml docProps word
cp cert_master_template.docx /Users/tbk/Desktop/lims-clean/mbr/templates/cert_master_template.docx
```

`-X` excludes extended attributes (MS Word-compatibility).

- [ ] **Step 5: Render smoke test**

Stwórz ad-hoc script / albo użyj test-u. Dodaj `tests/test_cert_template_render.py` (nowy plik):

```python
"""Smoke test — DOCX renders with current cert_settings and placeholders resolve."""
import sqlite3
import pytest
from mbr.models import init_mbr_tables
from mbr.certs.generator import build_preview_context, _docxtpl_render


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def test_docx_template_renders_without_errors(db, monkeypatch):
    """With default settings, rendering must not raise and produce bytes."""
    product = {
        "display_name": "Test Product",
        "spec_number": "P123",
        "cas_number": "",
        "expiry_months": 12,
        "opinion_pl": "OK",
        "opinion_en": "OK",
        "parameters": [
            {"id": "ph", "name_pl": "pH", "name_en": "pH", "requirement": "5-7",
             "method": "PN-EN 123", "data_field": "ph", "format": "2"},
        ],
        "variants": [{"id": "base", "label": "Test Product", "flags": [], "overrides": {}}],
    }
    ctx = build_preview_context(product, "base")
    assert "body_font_family" in ctx
    assert "header_font_size_pt" in ctx
    docx_bytes = _docxtpl_render(ctx)
    assert isinstance(docx_bytes, bytes) and len(docx_bytes) > 1000


def test_docx_template_reflects_settings(db):
    """Changing cert_settings must flow into rendered DOCX."""
    db.execute("UPDATE cert_settings SET value=? WHERE key=?", ("EB Garamond", "body_font_family"))
    db.commit()
    product = {
        "display_name": "Test", "spec_number": "P1", "cas_number": "",
        "expiry_months": 12, "opinion_pl": "", "opinion_en": "",
        "parameters": [],
        "variants": [{"id": "base", "label": "Test", "flags": [], "overrides": {}}],
    }
    ctx = build_preview_context(product, "base")
    docx_bytes = _docxtpl_render(ctx)
    # Rough sanity — font name appears in the rendered XML
    assert b"EB Garamond" in docx_bytes
```

Run: `pytest tests/test_cert_template_render.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add mbr/templates/cert_master_template.docx tests/test_cert_template_render.py
git commit -m "feat(certs): widen table geometry + parameterize typography"
```

---

## Task 5: Decyzja co do fontu + fallback dla Gotenberg offline

**Files:**
- Potencjalnie: `deploy/gotenberg.service` (jeśli offline).
- Potencjalnie: `mbr/templates/fonts/*.ttf` (jeśli offline + bundled).

> **Uwaga:** Ten task to **decyzja** + konfiguracja deploy-u, nie kod. TDD nie ma tu zastosowania.

- [ ] **Step 1: Sprawdź czy Gotenberg ma internet**

Uruchom lokalnie Gotenberg i spróbuj renderować PDF z fontem z Google Fonts. Wariant 1 — ręcznie pod `/admin/wzory-cert` po Tasku 3-4, zmień `body_font_family` na "EB Garamond" w UI (po Tasku 6+ — w tym momencie możesz zmienić przez SQL: `UPDATE cert_settings SET value='EB Garamond' WHERE key='body_font_family'`), kliknij Podgląd PDF — jeśli font się ładuje → online dostępny.

- [ ] **Step 2: Jeśli online Gotenberg — próbki i wybór**

Zrób podgląd dla 3 fontów:
- `TeX Gyre Bonum` (kontrola, dzisiejszy)
- `EB Garamond` (Google Fonts)
- `Libre Caslon Text` (Google Fonts)

Obejrzyj wygenerowane PDF. Wybierz finalny font → `UPDATE cert_settings SET value='<wybór>' WHERE key='body_font_family'` w prod-db.

**Domyślna wartość w seed** zostaje **TeX Gyre Bonum** (zmiana wyłącznie dla istniejących instalacji — admin sam zdecyduje w UI). Jeśli potrzeba zmiany defaulta w seed-ie — edytuj `mbr/models.py` (seed defaults).

- [ ] **Step 3: Jeśli offline Gotenberg — bundle `.ttf`**

Pobierz wybrany font ze https://fonts.google.com/ (zip). Skopiuj plik `.ttf` do `mbr/templates/fonts/<FontName>.ttf`.

Edytuj `deploy/gotenberg.service` — dodaj volume mount dla folderu fontów:

```
# Oryginalne wywołanie Gotenberg
ExecStart=/usr/bin/docker run --rm -p 3000:3000 \
    -v /path/to/repo/mbr/templates/fonts:/usr/share/fonts/custom:ro \
    gotenberg/gotenberg:7
```

(Dokładna ścieżka zależna od istniejącego ExecStart — nie nadpisuj ślepo, otwórz plik i ostrożnie dopisz volume.)

Restart service: `sudo systemctl daemon-reload && sudo systemctl restart gotenberg`.

- [ ] **Step 4: Commit ewentualnych zmian**

```bash
# Jeśli edytowany deploy:
git add deploy/gotenberg.service mbr/templates/fonts/
git commit -m "ops: bundle cert body font for offline gotenberg"
```

Jeśli nic się nie zmieniło — skip.

---

## Task 6: Ręczne łamanie `|` → `<w:br/>` w `_md_to_richtext`

**Files:**
- Modify: `mbr/certs/generator.py::_md_to_richtext` (ok. lina 30)
- Test: `tests/test_certs.py`

- [ ] **Step 1: Failing test**

Dodaj:

```python
def test_md_to_richtext_pipe_becomes_line_break():
    """'|' splits a parameter name into two lines in the rendered RichText."""
    from mbr.certs.generator import _md_to_richtext
    rt = _md_to_richtext("kokamido|amidoamin")
    # docxtpl RichText serializes to XML when .__str__() / .xml is called
    # Access the internal XML fragment
    xml = str(rt)
    assert "kokamido" in xml and "amidoamin" in xml
    assert "<w:br/>" in xml, f"no line break in: {xml}"


def test_md_to_richtext_pipe_combined_with_sub_super():
    """| must coexist with ^{} / _{} markers."""
    from mbr.certs.generator import _md_to_richtext
    rt = _md_to_richtext("n_{D}^{20}|value")
    xml = str(rt)
    assert "<w:br/>" in xml
    # Sub/sup markers no longer in output (they're expanded to runs)
    assert "_{" not in xml and "^{" not in xml
```

- [ ] **Step 2: Uruchom — powinien failować**

Run: `pytest tests/test_certs.py::test_md_to_richtext_pipe_becomes_line_break tests/test_certs.py::test_md_to_richtext_pipe_combined_with_sub_super -v`
Expected: FAIL.

- [ ] **Step 3: Rozszerz `_md_to_richtext`**

Pełna nowa wersja (zachowaj font/size kwargs z Taska 3):

```python
def _md_to_richtext(text: str, *, font: str = None, size: int = None) -> RichText:
    """Convert a string with `^{sup}` / `_{sub}` / `|` markers into a docxtpl RichText.

    Markers:
      - `^{X}` — superscript
      - `_{X}` — subscript
      - `|`  — manual line break (becomes <w:br/>)

    font/size default to module constants (_CERT_FONT / _CERT_SIZE) — callers
    with per-render settings should pass explicit values.
    """
    font = font or _CERT_FONT
    size = size or _CERT_SIZE
    rt = RichText()
    if not text:
        return rt
    # Split on '|' first — each segment is rendered with its sub/sup markers,
    # and we inject line_breaks=1 between segments.
    segments = text.split("|")
    for seg_idx, seg in enumerate(segments):
        for part in _RT_RE.split(seg):
            if not part:
                continue
            if part.startswith("^{") and part.endswith("}"):
                rt.add(part[2:-1], superscript=True, font=font, size=size)
            elif part.startswith("_{") and part.endswith("}"):
                rt.add(part[2:-1], subscript=True, font=font, size=size)
            else:
                rt.add(part, font=font, size=size)
        if seg_idx < len(segments) - 1:
            # Insert a line break between segments (but not after the last)
            rt.add("", font=font, size=size, line_breaks=1)
    return rt
```

> **Jeśli** docxtpl `RichText.add(..., line_breaks=1)` nie istnieje w zainstalowanej wersji (sprawdź `pip show docxtpl`), użyj explicit `\n` segment + polegaj na default wrap. Alternatywa — `rt.add("\n", font=..., size=...)` — ale `\n` często nie mapuje się na `<w:br/>` automatycznie. Jeśli brak atrybutu:
>
> ```python
> from docx.oxml.ns import qn
> from docx.oxml import OxmlElement
> # Hand-roll an <w:br/> element into rt._xml list
> br = OxmlElement('w:br')
> rt._xml.append(br)  # może wymagać adjustmentu w zależności od wersji
> ```
>
> Pierwszy wariant (`line_breaks=1`) próbuj pierwszy — jest w dokumentacji docxtpl.

- [ ] **Step 4: Uruchom testy**

Run: `pytest tests/test_certs.py::test_md_to_richtext_pipe_becomes_line_break tests/test_certs.py::test_md_to_richtext_pipe_combined_with_sub_super -v`
Expected: PASS.

Jeśli `<w:br/>` w XML nie występuje dokładnie w tej formie, dostosuj assertion do konkretnej wersji docxtpl (może być `<w:br />` lub `<w:br w:type="textWrapping"/>`).

- [ ] **Step 5: Commit**

```bash
git add mbr/certs/generator.py tests/test_certs.py
git commit -m "feat(certs): | in parameter name renders as line break"
```

---

## Task 7: Rozszerzony `/api/parametry/available`

**Files:**
- Modify: `mbr/parametry/routes.py:280-320`
- Test: `tests/test_certs.py` lub `tests/test_bindings_api.py` (jest już dla parametry)

- [ ] **Step 1: Failing test — pełny rejestr + `in_mbr` flag**

Sprawdź najpierw czy jest jakiś test dla tego endpointu:

```bash
grep -rn "parametry/available\|api_parametry_available" tests/
```

Dodaj do odpowiedniego pliku testowego (lub stwórz nowy `tests/test_parametry_available.py`):

```python
"""Tests for /api/parametry/available with in_mbr flag."""
import json
import sqlite3
import pytest
from mbr.app import create_app
from mbr.models import init_mbr_tables


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """Build Flask test client with an in-memory DB."""
    # NOTE: if create_app depends on persistent DB, adapt — use the pattern
    # from tests/test_auth.py or similar existing test.
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _setup_param(db, kod, label, name_en="", method_code=""):
    db.execute(
        "INSERT INTO parametry_analityczne (kod, label, name_en, method_code, aktywny, typ) "
        "VALUES (?, ?, ?, ?, 1, 'chem')",
        (kod, label, name_en, method_code),
    )
    db.commit()


def test_available_without_produkt_returns_full_registry(app_client):
    """Legacy behavior — no produkt arg → all active params."""
    r = app_client.get("/api/parametry/available")
    assert r.status_code == 200
    data = r.get_json()
    # Either plain list OR dict with params — check for the new dict shape
    if isinstance(data, dict):
        assert "params" in data
    else:
        assert isinstance(data, list)


def test_available_with_produkt_in_mbr_flag(app_client, monkeypatch):
    """With produkt, returns FULL registry with in_mbr flag on each row."""
    # Set up product + MBR with one param in analiza_koncowa, one not
    # (Test setup depends on how create_app wires the DB — use existing fixtures.)
    r = app_client.get("/api/parametry/available?produkt=TestProduct")
    assert r.status_code == 200
    data = r.get_json()
    assert "params" in data
    assert "no_mbr" in data
    # Each param must have in_mbr: bool
    for p in data["params"]:
        assert "in_mbr" in p and isinstance(p["in_mbr"], bool)
```

> **Uwaga** — jeśli twój pattern dla testów Flask nie działa z `create_app()` bezpośrednio (np. wymaga env/sekretu), zaadaptuj test pod istniejący wzór w `tests/test_auth.py` lub `tests/test_admin_audit.py`. Zidentyfikuj ten wzór PRZED pisaniem tego testu.

- [ ] **Step 2: Uruchom test — powinien failować na `in_mbr`**

Run: `pytest tests/test_parametry_available.py -v` (lub gdziekolwiek umieściłeś).
Expected: FAIL — `in_mbr` brak.

- [ ] **Step 3: Zmień endpoint**

Zastąp body `api_parametry_available` (w `mbr/parametry/routes.py:282-320`):

```python
@parametry_bp.route("/api/parametry/available")
@login_required
def api_parametry_available():
    """Active parameters for picker.

    Returns the FULL active registry of parametry_analityczne. If `?produkt=X`
    is given, each param carries an `in_mbr` flag indicating whether it belongs
    to the active MBR's analiza_koncowa section for that product.

    Certificate editor uses in_mbr=False to render the option with a grey dot
    (visual hint that the param isn't measured by laboranci — e.g., qualitative
    descriptor or external-lab measurement).
    """
    produkt = (request.args.get("produkt") or "").strip()
    with db_session() as db:
        all_rows = db.execute(
            "SELECT id, kod, label, skrot, typ, name_en, method_code, precision "
            "FROM parametry_analityczne WHERE aktywny=1 ORDER BY typ, kod"
        ).fetchall()
        all_params = [dict(r) for r in all_rows]

        if not produkt:
            # Legacy shape for non-cert callers — return plain list.
            return jsonify(all_params)

        from mbr.technolog.models import get_active_mbr
        mbr = get_active_mbr(db, produkt)
        no_mbr = False
        mbr_kody: set[str] = set()
        if not mbr:
            no_mbr = True
        else:
            try:
                plab = _json.loads(mbr.get("parametry_lab") or "{}")
            except Exception:
                plab = {}
            for sekcja in plab.values():
                for p in (sekcja.get("pola") or []):
                    kod = p.get("kod")
                    if kod:
                        mbr_kody.add(kod)
            if not mbr_kody:
                no_mbr = True

        for p in all_params:
            p["in_mbr"] = bool(p.get("kod") and p["kod"] in mbr_kody)

        return jsonify({"no_mbr": no_mbr, "produkt": produkt, "params": all_params})
```

(Uwaga: `_json` to alias `import json as _json` — sprawdź na górze pliku; jeśli używa `json`, dostosuj.)

- [ ] **Step 4: Testy zielone**

Run: `pytest tests/test_parametry_available.py -v`
Expected: PASS.

- [ ] **Step 5: Uruchom pełną suitę parametry**

Run: `pytest tests/test_bindings_api.py tests/test_parametry_available.py -v`
Expected: No regressions.

- [ ] **Step 6: Commit**

```bash
git add mbr/parametry/routes.py tests/test_parametry_available.py
git commit -m "feat(parametry): api/available returns full registry with in_mbr flag"
```

---

## Task 8: Dropdown w edytorze — oznaczenie `in_mbr`

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html` (JS funkcja `_codeOptions`, CSS grupowanie opcji, obsługa nowego shape-u odpowiedzi)

> **Uwaga:** UI — manualny smoke test. Brak automatu.

- [ ] **Step 1: Zmień obsługę odpowiedzi w `editProduct`**

W `mbr/templates/admin/wzory_cert.html`, znajdź funkcję `editProduct` (ok. lina 528). Fetch dla `/api/parametry/available` (lina ok. 532):

```javascript
fetch('/api/parametry/available?produkt=' + encodeURIComponent(key)).then(function(r) { return r.json(); })
```

Jest już tam obsługa `pr.no_mbr` + `pr.params`. Po Tasku 7 wszystkie parametry mają `in_mbr`. Nie ma regresji.

- [ ] **Step 2: Zmodyfikuj `_codeOptions`**

Znajdź funkcję `_codeOptions` (ok. lina 363). Zmień na grupowaną listę:

```javascript
function _codeOptions(current) {
  var inMbr = _availableCodes.filter(function(c) { return c.in_mbr; });
  var notInMbr = _availableCodes.filter(function(c) { return !c.in_mbr; });
  var html = '<option value="">— brak —</option>';
  if (inMbr.length) {
    html += '<optgroup label="W MBR (mierzone przez laborantów)">';
    inMbr.forEach(function(c) {
      var sel = (c.kod === current) ? ' selected' : '';
      html += '<option value="' + _esc(c.kod) + '"' + sel + '>● ' + _esc(c.kod) + ' — ' + _esc(c.skrot || c.label) + '</option>';
    });
    html += '</optgroup>';
  }
  if (notInMbr.length) {
    html += '<optgroup label="Poza MBR (opisowe / external lab)">';
    notInMbr.forEach(function(c) {
      var sel = (c.kod === current) ? ' selected' : '';
      html += '<option value="' + _esc(c.kod) + '"' + sel + '>○ ' + _esc(c.kod) + ' — ' + _esc(c.skrot || c.label) + '</option>';
    });
    html += '</optgroup>';
  }
  return html;
}
```

- [ ] **Step 3: Smoke test manualny**

Uruchom serwer (`python -m mbr.app`). Zaloguj się jako admin, otwórz `/admin/wzory-cert`, kliknij produkt z MBR-em, kliknij na dropdown "Powiąż z pomiarem" w dowolnym wierszu parametru. **Oczekiwane**: dwie grupy opcji z kropkami ● / ○.

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(certs): editor dropdown groups params by in_mbr flag"
```

---

## Task 9: Endpoint kopiowania produktu

**Files:**
- Modify: `mbr/certs/routes.py` (nowy handler `api_cert_config_product_copy`)
- Test: `tests/test_cert_editor_atomicity.py` albo `tests/test_certs.py`

- [ ] **Step 1: Failing test**

Dodaj do `tests/test_cert_editor_atomicity.py` (albo, jeśli tam nie pasuje, do `tests/test_certs.py`):

```python
def test_copy_product_deep_copies_parameters(app_client_with_db):
    """POST /api/cert/config/product/<src>/copy creates new product with copied parameters only."""
    db = app_client_with_db.db
    client = app_client_with_db.client

    # Set up source product with 3 base params + 1 extra variant
    _setup_product_with_params(db, key="SRC_PROD", params=[
        ("ph", "pH"),
        ("lepkosc", "Lepkość"),
        ("zapach", "Zapach"),
    ])
    _add_variant(db, produkt="SRC_PROD", variant_id="avon", label="Avon edition",
                 flags=["has_avon_code"], avon_code="AVX-001")
    db.commit()

    r = client.post(
        "/api/cert/config/product/SRC_PROD/copy",
        json={"new_display_name": "TARGET_PROD"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["key"] == "TARGET_PROD"

    # Target has 3 params in same order
    target_params = db.execute(
        "SELECT pa.kod FROM parametry_cert pc "
        "JOIN parametry_analityczne pa ON pa.id=pc.parametr_id "
        "WHERE pc.produkt='TARGET_PROD' AND pc.variant_id IS NULL ORDER BY pc.kolejnosc"
    ).fetchall()
    kods = [r["kod"] for r in target_params]
    assert kods == ["ph", "lepkosc", "zapach"]

    # Target has ONLY base variant
    variants = db.execute(
        "SELECT variant_id FROM cert_variants WHERE produkt='TARGET_PROD'"
    ).fetchall()
    assert [v["variant_id"] for v in variants] == ["base"]

    # Source is untouched
    src_variants = db.execute(
        "SELECT variant_id FROM cert_variants WHERE produkt='SRC_PROD'"
    ).fetchall()
    assert sorted(v["variant_id"] for v in src_variants) == ["avon", "base"]


def test_copy_product_duplicate_key_409(app_client_with_db):
    """Copying to an existing name returns 409."""
    db = app_client_with_db.db
    client = app_client_with_db.client
    _setup_product_with_params(db, key="EXIST", params=[("ph", "pH")])
    db.commit()
    r = client.post("/api/cert/config/product/EXIST/copy",
                    json={"new_display_name": "EXIST"})
    assert r.status_code == 409


def test_copy_product_invalid_display_name_400(app_client_with_db):
    """Invalid characters in display_name → 400."""
    db = app_client_with_db.db
    client = app_client_with_db.client
    _setup_product_with_params(db, key="SRC2", params=[])
    db.commit()
    r = client.post("/api/cert/config/product/SRC2/copy",
                    json={"new_display_name": "Name With / Slash"})
    assert r.status_code == 400


def test_copy_product_missing_src_404(app_client_with_db):
    client = app_client_with_db.client
    r = client.post("/api/cert/config/product/NOPE/copy",
                    json={"new_display_name": "NewOne"})
    assert r.status_code == 404
```

Helper-y `_setup_product_with_params` i `_add_variant` — jeśli są już w test-file, użyj; jeśli nie, napisz jako moduł-level:

```python
def _setup_product_with_params(db, key, params):
    """Create a product entry + cert_variants(base) + parametry_cert rows.

    params: list of (kod, label) tuples — each creates a parametry_analityczne
    row and a corresponding parametry_cert row (base, variant_id=NULL).
    """
    db.execute(
        "INSERT OR IGNORE INTO produkty (nazwa, display_name, spec_number, cas_number, "
        "expiry_months, opinion_pl, opinion_en) VALUES (?, ?, '', '', 12, '', '')",
        (key, key),
    )
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
        "VALUES (?, 'base', ?, '[]', 0)",
        (key, key),
    )
    for idx, (kod, label) in enumerate(params):
        row = db.execute("SELECT id FROM parametry_analityczne WHERE kod=?", (kod,)).fetchone()
        if row is None:
            cur = db.execute(
                "INSERT INTO parametry_analityczne (kod, label, aktywny, typ) VALUES (?, ?, 1, 'chem')",
                (kod, label),
            )
            param_id = cur.lastrowid
        else:
            param_id = row["id"]
        db.execute(
            "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, variant_id) "
            "VALUES (?, ?, ?, NULL)",
            (key, param_id, idx),
        )


def _add_variant(db, produkt, variant_id, label, flags=None, avon_code=None):
    import json as _json
    db.execute(
        "INSERT INTO cert_variants (produkt, variant_id, label, flags, avon_code, kolejnosc) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (produkt, variant_id, label, _json.dumps(flags or []), avon_code),
    )
```

Fixture `app_client_with_db` (Flask test client sharing a single connection z `db`) — jeśli brak, zaadaptuj z `tests/test_auth.py` lub `tests/test_admin_audit.py` (tam jest podobny setup).

- [ ] **Step 2: Uruchom — powinien failować**

Run: `pytest tests/test_cert_editor_atomicity.py -k copy -v`
Expected: FAIL (404 lub routing error).

- [ ] **Step 3: Dodaj handler**

W `mbr/certs/routes.py`, po `api_cert_config_product_create` (ok. lina 621), dodaj:

```python
@certs_bp.route("/api/cert/config/product/<src_key>/copy", methods=["POST"])
@role_required("admin", "kj")
def api_cert_config_product_copy(src_key):
    """Deep-copy parameters from source product to a new product.

    Copies:
      - all base parameters (parametry_cert with variant_id IS NULL) in order
      - a fresh 'base' variant with label = new display_name

    Does NOT copy:
      - product metadata (spec_number, cas_number, opinions, expiry_months) —
        user fills these in fresh
      - non-base variants and their add_parameters
    """
    import re
    from mbr.certs.generator import save_cert_config_export

    data = request.get_json(silent=True) or {}
    new_display_name = (data.get("new_display_name") or "").strip()
    if not new_display_name:
        return jsonify({"error": "new_display_name is required"}), 400

    new_key = new_display_name.replace(" ", "_")
    if not re.match(r'^[A-Za-z0-9_\-]+$', new_key):
        return jsonify({"error": "Nazwa zawiera niedozwolone znaki (dozwolone: litery, cyfry, _, -)"}), 400

    with db_session() as db:
        src_exists = db.execute(
            "SELECT 1 FROM cert_variants WHERE produkt = ? LIMIT 1", (src_key,)
        ).fetchone()
        if not src_exists:
            return jsonify({"error": "Source product not found"}), 404

        # Target collision check
        target_exists = db.execute(
            "SELECT 1 FROM cert_variants WHERE produkt = ? LIMIT 1", (new_key,)
        ).fetchone()
        if target_exists:
            return jsonify({"error": f"Product '{new_key}' already exists"}), 409
        # Also check produkty table alone (orphaned rows)
        existing_prod = db.execute(
            "SELECT id FROM produkty WHERE nazwa = ?", (new_key,)
        ).fetchone()

        try:
            with db:
                # 1. produkty row (if not exists)
                if not existing_prod:
                    db.execute(
                        "INSERT INTO produkty (nazwa, display_name, spec_number, cas_number, "
                        "expiry_months, opinion_pl, opinion_en) VALUES (?, ?, '', '', 12, '', '')",
                        (new_key, new_display_name),
                    )

                # 2. base variant
                db.execute(
                    "INSERT INTO cert_variants (produkt, variant_id, label, flags, kolejnosc) "
                    "VALUES (?, 'base', ?, '[]', 0)",
                    (new_key, new_display_name),
                )

                # 3. Copy base parametry_cert (variant_id IS NULL)
                src_params = db.execute(
                    "SELECT parametr_id, kolejnosc, requirement, format, qualitative_result, "
                    "name_pl, name_en, method "
                    "FROM parametry_cert "
                    "WHERE produkt = ? AND variant_id IS NULL "
                    "ORDER BY kolejnosc",
                    (src_key,),
                ).fetchall()
                for p in src_params:
                    db.execute(
                        "INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, "
                        "format, qualitative_result, name_pl, name_en, method, variant_id) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                        (new_key, p["parametr_id"], p["kolejnosc"], p["requirement"],
                         p["format"], p["qualitative_result"],
                         p["name_pl"], p["name_en"], p["method"]),
                    )

                # 4. Audit entry
                from mbr.shared import audit
                audit.log_event(
                    audit.EVENT_CERT_CONFIG_UPDATED,
                    entity_type="cert",
                    entity_label=new_key,
                    payload={
                        "copied_from": src_key,
                        "params_count": len(src_params),
                        "variants_count": 1,
                    },
                    db=db,
                )
        except Exception as e:
            return jsonify({"error": f"kopia nie powiodła się: {e}"}), 500

    save_cert_config_export()
    return jsonify({"ok": True, "key": new_key})
```

- [ ] **Step 4: Testy zielone**

Run: `pytest tests/test_cert_editor_atomicity.py -k copy -v`
Expected: All 4 copy-tests pass.

- [ ] **Step 5: Commit**

```bash
git add mbr/certs/routes.py tests/test_cert_editor_atomicity.py
git commit -m "feat(certs): POST /api/cert/config/product/<src>/copy"
```

---

## Task 10: Copy UI — przycisk na karcie + modal

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html` (HTML karty, modal, JS)

- [ ] **Step 1: Dodaj przycisk "Kopiuj" na kartę**

W `renderProductList` (ok. lina 443), zmodyfikuj blok renderujący dolną część karty (ok. lina 456):

```javascript
    '<div class="wc-card-bottom">' +
      '<button class="wc-btn wc-btn-o wc-btn-sm" onclick="event.stopPropagation();copyProduct(\'' + _esc(p.key) + '\',\'' + _esc(p.display_name) + '\')">Kopiuj</button>' +
      '<button class="wc-btn wc-btn-d" onclick="event.stopPropagation();deleteProduct(\'' + _esc(p.key) + '\',\'' + _esc(p.display_name) + '\')">Usuń</button>' +
    '</div>' +
```

Update `.wc-card-bottom` CSS (ok. lina 54) dla flex-gap:

```css
.wc-card-bottom { display: flex; justify-content: flex-end; gap: 6px; padding-top: 6px; border-top: 1px solid var(--border-subtle, #f0ece4); margin-top: 6px; }
```

- [ ] **Step 2: Dodaj modal kopiowania**

Po modal-u podglądu (ok. lina 320), przed `</div>` zamykającym stronę, dodaj:

```html
<!-- ═══ Copy Modal ═══ -->
<div class="wc-modal" id="wc-copy-modal" onclick="if(event.target===this)closeCopyModal()">
  <div class="wc-modal-box" style="max-width:420px;height:auto;">
    <div class="wc-modal-head">
      <span style="font-weight:700;">Kopiuj wzór świadectwa</span>
      <button class="wc-modal-close" onclick="closeCopyModal()">&times;</button>
    </div>
    <div style="padding:16px 20px;">
      <div style="margin-bottom:14px;color:var(--text-sec);font-size:12px;">
        Skopiuj parametry i układ ze wzoru <strong id="wc-copy-src"></strong>. Nowy produkt dostaje świeże meta (nazwa, specyfikacja, opinie) — warianty poza bazowym nie są kopiowane.
      </div>
      <label class="wc-lbl">Nazwa nowego produktu *</label>
      <input class="wc-inp" type="text" id="wc-copy-name" placeholder="np. Chegina_GLOL40">
      <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:16px;">
        <button class="wc-btn wc-btn-o" onclick="closeCopyModal()">Anuluj</button>
        <button class="wc-btn wc-btn-p" onclick="doCopyProduct()">Kopiuj</button>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Dodaj JS handlery**

Na początku sekcji `<script>`, przy state vars, dodaj:

```javascript
var _copySrcKey = null;
```

Po `deleteProduct` (ok. lina 502), dodaj:

```javascript
function copyProduct(srcKey, srcName) {
  _copySrcKey = srcKey;
  document.getElementById('wc-copy-src').textContent = srcName;
  document.getElementById('wc-copy-name').value = '';
  document.getElementById('wc-copy-modal').classList.add('show');
  setTimeout(function() { document.getElementById('wc-copy-name').focus(); }, 60);
}

function closeCopyModal() {
  document.getElementById('wc-copy-modal').classList.remove('show');
  _copySrcKey = null;
}

function doCopyProduct() {
  var name = document.getElementById('wc-copy-name').value.trim();
  if (!name) { flash('Nazwa jest wymagana', false); return; }
  if (!_copySrcKey) return;
  fetch('/api/cert/config/product/' + encodeURIComponent(_copySrcKey) + '/copy', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ new_display_name: name }),
  }).then(function(r) { return r.json().then(function(d) { return { status: r.status, data: d }; }); })
    .then(function(res) {
      if (res.data.ok) {
        flash('Skopiowano jako ' + res.data.key, true);
        closeCopyModal();
        loadProducts();
      } else {
        flash('Błąd: ' + (res.data.error || 'kopia nie powiodła się'), false);
      }
    });
}
```

Dodaj też Enter-submit w input-cie (`wc-copy-name`):

```javascript
document.addEventListener('DOMContentLoaded', function() {
  var inp = document.getElementById('wc-copy-name');
  if (inp) inp.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') doCopyProduct();
  });
});
```

- [ ] **Step 4: Smoke test manualny**

Otwórz edytor, na dowolnej karcie kliknij "Kopiuj", wpisz nazwę, zatwierdź → sprawdź że nowy produkt się pojawił na liście z parametrami źródła.

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(certs): copy-template button and modal on product cards"
```

---

## Task 11: Dirty state + beforeunload + Powrót confirm

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html` (JS state + event listeners)

- [ ] **Step 1: Dodaj state + helpery na górę sekcji `<script>`**

Przy deklaracjach state (ok. lina 324, obok `_products`, `_currentKey`):

```javascript
var _dirty = false;
var _unloadHandler = null;
```

Dodaj funkcje (np. po `_rtHtml`, lina ok. 361):

```javascript
function _setDirty(flag) {
  _dirty = !!flag;
  var title = document.getElementById('ed-title');
  if (title) {
    var txt = title.textContent.replace(/\s*\*$/, '');
    title.textContent = _dirty ? txt + ' *' : txt;
  }
  var saveBtn = document.querySelector('.wc-save .wc-btn-p');
  if (saveBtn) {
    saveBtn.style.opacity = _dirty ? '1' : '0.55';
  }
}

function _installDirtyListener() {
  // Delegated — one listener for the whole editor container
  var editor = document.getElementById('wc-editor');
  if (!editor) return;
  if (editor._dirtyInstalled) return;
  editor._dirtyInstalled = true;
  editor.addEventListener('input', function() { _setDirty(true); });
  editor.addEventListener('change', function() { _setDirty(true); });
}

function _installBeforeunload() {
  if (_unloadHandler) return;
  _unloadHandler = function(e) {
    if (!_dirty) return;
    e.preventDefault();
    e.returnValue = 'Masz niezapisane zmiany w edytorze świadectwa.';
    return e.returnValue;
  };
  window.addEventListener('beforeunload', _unloadHandler);
}
```

- [ ] **Step 2: Zainstaluj listener-y po wejściu do edytora**

W `editProduct` (ok. lina 528), po `renderEditor()` i pokazaniu `#wc-editor`, dodaj:

```javascript
    _setDirty(false);
    _installDirtyListener();
    _installBeforeunload();
```

- [ ] **Step 3: Confirm przy `backToList`**

W funkcji `backToList` (ok. lina 556) — na początku:

```javascript
function backToList() {
  if (_dirty) {
    if (!confirm('Masz niezapisane zmiany. Porzucić?')) return;
  }
  _setDirty(false);
  // ... existing body ...
```

- [ ] **Step 4: Po udanym zapisie reset dirty**

W `saveProduct` (ok. lina 901), w callback-u `.then` po sprawdzeniu `res.ok` (ok. lina 910):

```javascript
    if (res && res.ok) {
      flash('Zapisano pomyślnie', true);
      st.textContent = 'Zapisano'; st.style.color = 'var(--green)';
      _currentProduct = Object.assign(_currentProduct || {}, state);
      _setDirty(false);
      updatePreviewVariantSelect();
    } else {
```

- [ ] **Step 5: Dirty flag na akcje programowe**

W `addParameter`, `removeBaseParam`, `addVariant`, `removeCurrentVariant`, `addVariantParam` — na końcu każdej funkcji dodaj:

```javascript
  _setDirty(true);
```

(6 funkcji; znajdź każdą w pliku i dopisz wywołanie.)

- [ ] **Step 6: Smoke test**

Uruchom serwer, otwórz edytor, zmień dowolne pole → gwiazdka `*` pojawia się. Spróbuj przełączyć zakładkę/zamknąć — pyta. Kliknij Zapisz → gwiazdka znika.

- [ ] **Step 7: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(certs): editor dirty state, beforeunload, navigation guard"
```

---

## Task 12: UI walidacja przed zapisem

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html` (JS — `saveProduct` preflight)

- [ ] **Step 1: Dodaj helper walidacyjny**

Przed `saveProduct` (ok. lina 901), wstaw:

```javascript
function _validateBeforeSave(state) {
  /**
   * Return { ok: bool, errors: [ {msg, rowSelector?} ], firstRow?: Element }.
   * Collects all errors — doesn't stop at first — so the operator sees the
   * full picture. UI marks offending rows red.
   */
  var errors = [];
  var markedRows = [];

  function markRow(sel) {
    var el = document.querySelector(sel);
    if (el) { el.style.background = '#fef2f2'; markedRows.push(el); }
  }

  // Clear previous marks
  document.querySelectorAll('#wc-params-body tr, #wc-var-params tr').forEach(function(tr) {
    tr.style.background = '';
  });

  // 1. Duplicate param ids
  var seenParamIds = {};
  (state.parameters || []).forEach(function(p, idx) {
    if (seenParamIds[p.id]) {
      errors.push({ msg: 'Duplikat id parametru: ' + p.id });
      markRow('#wc-params-body tr:nth-child(' + (idx + 1) + ')');
    }
    seenParamIds[p.id] = true;
  });

  // 2. Empty name_pl
  (state.parameters || []).forEach(function(p, idx) {
    if (!p.name_pl || !p.name_pl.trim()) {
      errors.push({ msg: 'Parametr bez nazwy PL (' + (p.id || 'nowy') + ')' });
      markRow('#wc-params-body tr:nth-child(' + (idx + 1) + ')');
    }
  });

  // 3. Param needs either data_field or qualitative_result
  (state.parameters || []).forEach(function(p, idx) {
    var hasMeas = p.data_field && p.data_field.trim();
    var hasQual = p.qualitative_result && p.qualitative_result.trim();
    if (!hasMeas && !hasQual) {
      errors.push({ msg: '"' + (p.id || 'nowy') + '" musi mieć pomiar lub stałą wartość' });
      markRow('#wc-params-body tr:nth-child(' + (idx + 1) + ')');
    }
  });

  // 4. Duplicate variant ids
  var seenVariantIds = {};
  (state.variants || []).forEach(function(v) {
    if (seenVariantIds[v.id]) {
      errors.push({ msg: 'Duplikat id wariantu: ' + v.id });
    }
    seenVariantIds[v.id] = true;
  });

  // 5. Variant missing label
  (state.variants || []).forEach(function(v) {
    if (!v.label || !v.label.trim()) {
      errors.push({ msg: 'Wariant "' + v.id + '" bez nazwy' });
    }
  });

  // 6. Duplicate ids within variant add_parameters
  (state.variants || []).forEach(function(v) {
    var ap = (v.overrides || {}).add_parameters || [];
    var apSeen = {};
    ap.forEach(function(p) {
      if (!p.id) return;
      if (apSeen[p.id]) {
        errors.push({ msg: 'Wariant "' + v.id + '": duplikat id "' + p.id + '"' });
      }
      apSeen[p.id] = true;
    });
  });

  return { ok: errors.length === 0, errors: errors };
}
```

- [ ] **Step 2: Wywołaj walidację w `saveProduct`**

Zmodyfikuj `saveProduct` na samym początku po `collectEditorState()` (ok. lina 901-920):

```javascript
function saveProduct() {
  var state = collectEditorState();
  var preflight = _validateBeforeSave(state);
  if (!preflight.ok) {
    flash('Nie można zapisać: ' + preflight.errors.map(function(e) { return e.msg; }).join('; '), false);
    return;
  }
  var st = document.getElementById('wc-save-status');
  st.textContent = 'Zapisywanie...'; st.style.color = 'var(--text-dim)';
  // ... existing fetch logic ...
```

- [ ] **Step 3: Smoke test**

W edytorze:
- Zostaw dwa parametry z tym samym id → Zapisz → flash "Duplikat id parametru".
- Dodaj parametr bez `data_field` i bez `qualitative_result` → Zapisz → flash o wymogu pomiaru/stałej.
- Dodaj wariant bez nazwy → Zapisz → flash.

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(certs): editor UI-side validation before save"
```

---

## Task 13: Endpoint audit-history per produkt

**Files:**
- Modify: `mbr/certs/routes.py` (nowy handler po `cert_audit_history`)
- Test: `tests/test_certs.py` albo nowy `tests/test_cert_audit_history.py`

- [ ] **Step 1: Failing test**

Dodaj do `tests/test_cert_editor_atomicity.py` (ma już setup dla cert):

```python
def test_audit_history_per_product_filters_by_label(app_client_with_db):
    """GET /api/cert/config/product/<key>/audit-history returns only events for that product."""
    db = app_client_with_db.db
    client = app_client_with_db.client

    # Two products, events on each
    _setup_product_with_params(db, key="PROD_A", params=[("ph", "pH")])
    _setup_product_with_params(db, key="PROD_B", params=[("ph", "pH")])
    db.commit()

    # Simulate edit events
    from mbr.shared import audit
    for key, count in [("PROD_A", 1), ("PROD_B", 1), ("PROD_A", 2)]:
        audit.log_event(
            audit.EVENT_CERT_CONFIG_UPDATED,
            entity_type="cert", entity_label=key,
            payload={"params_count": count, "variants_count": 1},
            actors=[{"worker_id": None, "actor_login": "admin",
                     "actor_rola": "admin", "actor_name": "admin"}],
            db=db,
        )
    db.commit()

    r = client.get("/api/cert/config/product/PROD_A/audit-history")
    assert r.status_code == 200
    data = r.get_json()
    assert "history" in data
    # Two PROD_A events, zero PROD_B
    assert len(data["history"]) == 2
    for row in data["history"]:
        assert row["entity_label"] == "PROD_A"
```

- [ ] **Step 2: Uruchom test**

Run: `pytest tests/test_cert_editor_atomicity.py -k audit_history_per_product -v`
Expected: FAIL — 404.

- [ ] **Step 3: Dodaj handler**

W `mbr/certs/routes.py`, po `cert_audit_history` (ok. lina 776), dodaj:

```python
@certs_bp.route("/api/cert/config/product/<key>/audit-history")
@role_required("admin", "kj")
def cert_config_audit_history(key):
    """Return cert config edit history for a specific product.

    Filters audit_log on entity_type='cert' AND entity_label=key. Events
    include CERT_CONFIG_UPDATED (save, copy) and potentially future variants.
    """
    from mbr.shared import audit
    with db_session() as db:
        history = audit.query_audit_history_by_label(db, "cert", key)
    return jsonify({"history": history})
```

- [ ] **Step 4: Test zielony**

Run: `pytest tests/test_cert_editor_atomicity.py -k audit_history_per_product -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mbr/certs/routes.py tests/test_cert_editor_atomicity.py
git commit -m "feat(certs): GET /api/cert/config/product/<key>/audit-history"
```

---

## Task 14: Zakładka "Historia" w edytorze

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html`

- [ ] **Step 1: Dodaj tab "Historia" do zakładek**

W `wzory_cert.html`, w `.wc-tabs` (ok. lina 205-209):

```html
    <!-- Tabs -->
    <div class="wc-tabs">
      <button class="wc-tab active" onclick="switchEdTab('produkt',this)">Produkt</button>
      <button class="wc-tab" onclick="switchEdTab('parametry',this)">Parametry świadectwa</button>
      <button class="wc-tab" onclick="switchEdTab('warianty',this)">Warianty</button>
      <button class="wc-tab" onclick="switchEdTab('historia',this)">Historia</button>
    </div>
```

Dodaj sam panel po panelu `warianty` (ok. lina 297, przed `<!-- Save -->`):

```html
    <!-- Tab 4: Historia -->
    <div class="wc-panel" id="panel-historia" style="display:none;">
      <div style="font-size:13px;font-weight:600;margin-bottom:10px;">Historia zmian szablonu</div>
      <table class="wc-tbl">
        <thead>
          <tr>
            <th style="width:140px;">Data</th>
            <th>Kto</th>
            <th>Zmiana</th>
          </tr>
        </thead>
        <tbody id="wc-history-body">
          <tr><td colspan="3" style="text-align:center;color:var(--text-dim);padding:16px;">— kliknij zakładkę żeby załadować —</td></tr>
        </tbody>
      </table>
    </div>
```

- [ ] **Step 2: Rozszerz `switchEdTab` o ładowanie historii**

Zaktualizuj `switchEdTab` (ok. lina 425):

```javascript
function switchEdTab(which, btn) {
  ['produkt','parametry','warianty','historia'].forEach(function(t) {
    var p = document.getElementById('panel-' + t);
    if (p) p.style.display = (t === which) ? '' : 'none';
  });
  document.querySelectorAll('.wc-tab').forEach(function(b) { b.classList.remove('active'); });
  if (btn) btn.classList.add('active');
  if (which === 'historia') loadHistory();
}
```

- [ ] **Step 3: Dodaj `loadHistory`**

Po `switchEdTab` (ok. lina 432), dodaj:

```javascript
function loadHistory() {
  if (!_currentKey) return;
  var tbody = document.getElementById('wc-history-body');
  tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:var(--text-dim);padding:16px;">Ładowanie...</td></tr>';
  fetch('/api/cert/config/product/' + encodeURIComponent(_currentKey) + '/audit-history')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var hist = (data && data.history) || [];
      if (!hist.length) {
        tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:var(--text-dim);padding:16px;">Brak historii.</td></tr>';
        return;
      }
      var html = '';
      hist.forEach(function(row) {
        var actors = (row.actors || []).map(function(a) { return a.actor_name || a.actor_login; }).join(', ') || '—';
        var payload = {};
        try { payload = row.payload_json ? JSON.parse(row.payload_json) : {}; } catch (e) {}
        var summary = '';
        if (payload.copied_from) {
          summary = 'Skopiowano z <code>' + _esc(payload.copied_from) + '</code>, ' +
                    (payload.params_count || 0) + ' parametrów';
        } else {
          summary = (payload.params_count != null ? payload.params_count : '?') + ' parametrów, ' +
                    (payload.variants_count != null ? payload.variants_count : '?') + ' wariantów';
        }
        html += '<tr>' +
          '<td style="font-family:var(--mono);font-size:10px;">' + _esc(_fmtDt(row.dt)) + '</td>' +
          '<td>' + _esc(actors) + '</td>' +
          '<td>' + summary + '</td>' +
        '</tr>';
      });
      tbody.innerHTML = html;
    })
    .catch(function(e) {
      tbody.innerHTML = '<tr><td colspan="3" style="color:var(--red);padding:16px;">Błąd: ' + _esc(e.message) + '</td></tr>';
    });
}

function _fmtDt(iso) {
  if (!iso) return '';
  // "2026-04-18T14:30:15" → "18.04.2026 14:30"
  var m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!m) return iso;
  return m[3] + '.' + m[2] + '.' + m[1] + ' ' + m[4] + ':' + m[5];
}
```

- [ ] **Step 4: Smoke test**

Uruchom serwer, otwórz edytor produktu, zrób kilka zapisów (Zapisz → zmień coś → Zapisz). Kliknij zakładkę "Historia" → zobacz listę.

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(certs): history tab in editor"
```

---

## Task 15: Auto-refresh podglądu PDF (debounced 800ms)

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html`

- [ ] **Step 1: Dodaj debounced trigger**

Przy state var (ok. lina 324):

```javascript
var _prevDebounce = null;
var _prevModalOpen = false;
```

Po `_setDirty` (z Taska 11), dodaj:

```javascript
function _triggerPreviewAutoRefresh() {
  if (!_prevModalOpen) return;
  if (_prevDebounce) clearTimeout(_prevDebounce);
  _prevDebounce = setTimeout(function() { refreshPreview(); }, 800);
}
```

- [ ] **Step 2: Połącz z listener-em dirty**

W `_installDirtyListener` (z Taska 11), po istniejących listener-ach input/change:

```javascript
function _installDirtyListener() {
  var editor = document.getElementById('wc-editor');
  if (!editor || editor._dirtyInstalled) return;
  editor._dirtyInstalled = true;
  editor.addEventListener('input', function() {
    _setDirty(true);
    _triggerPreviewAutoRefresh();
  });
  editor.addEventListener('change', function() {
    _setDirty(true);
    _triggerPreviewAutoRefresh();
  });
}
```

- [ ] **Step 3: Oznacz modal otwarty/zamknięty**

Zmień `openPreview` i `closePreview` (ok. lina 931-936):

```javascript
function openPreview() {
  updatePreviewVariantSelect();
  document.getElementById('wc-modal').classList.add('show');
  _prevModalOpen = true;
  refreshPreview();  // initial render when opening
}

function closePreview() {
  document.getElementById('wc-modal').classList.remove('show');
  _prevModalOpen = false;
  if (_prevDebounce) { clearTimeout(_prevDebounce); _prevDebounce = null; }
}
```

- [ ] **Step 4: Smoke test**

Otwórz edytor z otwartym modal-em podglądu, zmień dowolne pole → po 800ms podgląd sam się odświeża. Spinner/"Generowanie..." powinien się pojawić w czasie generacji.

- [ ] **Step 5: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(certs): auto-refresh preview on editor changes"
```

---

## Task 16: Modal "Ustawienia globalne" + GET/PUT `/api/cert/settings`

**Files:**
- Modify: `mbr/certs/routes.py` (endpointy)
- Modify: `mbr/templates/admin/wzory_cert.html` (przycisk na liście + modal)
- Test: `tests/test_certs.py`

- [ ] **Step 1: Failing test**

```python
def test_cert_settings_api_get_returns_defaults(app_client_with_db):
    client = app_client_with_db.client
    r = client.get("/api/cert/settings")
    assert r.status_code == 200
    data = r.get_json()
    assert data["body_font_family"] == "TeX Gyre Bonum"
    assert data["header_font_size_pt"] == 14


def test_cert_settings_api_put_updates_and_audit(app_client_with_db):
    db = app_client_with_db.db
    client = app_client_with_db.client
    r = client.put("/api/cert/settings", json={
        "body_font_family": "EB Garamond",
        "header_font_size_pt": 18,
    })
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}
    # GET reflects update
    r2 = client.get("/api/cert/settings")
    data = r2.get_json()
    assert data["body_font_family"] == "EB Garamond"
    assert data["header_font_size_pt"] == 18
    # Audit
    audit_row = db.execute(
        "SELECT event_type, payload_json FROM audit_log WHERE event_type=?",
        ("cert.settings.updated",),
    ).fetchone()
    assert audit_row is not None


def test_cert_settings_api_put_validates_header_size(app_client_with_db):
    client = app_client_with_db.client
    r = client.put("/api/cert/settings", json={"header_font_size_pt": 500})
    assert r.status_code == 400
```

- [ ] **Step 2: Uruchom — failuje**

Run: `pytest tests/test_certs.py -k cert_settings_api -v`
Expected: FAIL — 404.

- [ ] **Step 3: Dodaj handler-y**

W `mbr/certs/routes.py`, po `api_cert_config_product_copy` (z Taska 9), dodaj:

```python
@certs_bp.route("/api/cert/settings", methods=["GET"])
@role_required("admin", "kj")
def api_cert_settings_get():
    """Return current cert_settings (typography globals)."""
    with db_session() as db:
        rows = db.execute("SELECT key, value FROM cert_settings").fetchall()
    out = {"body_font_family": "TeX Gyre Bonum", "header_font_size_pt": 14}
    for r in rows:
        k = r["key"]
        v = r["value"]
        if k == "header_font_size_pt":
            try:
                out[k] = int(v)
            except (ValueError, TypeError):
                pass
        else:
            out[k] = v
    return jsonify(out)


@certs_bp.route("/api/cert/settings", methods=["PUT"])
@role_required("admin", "kj")
def api_cert_settings_put():
    """Update cert_settings keys (font family, header font size)."""
    data = request.get_json(silent=True) or {}
    updated = {}

    if "body_font_family" in data:
        val = (data["body_font_family"] or "").strip()
        if not val or len(val) > 120:
            return jsonify({"error": "body_font_family: pusta lub za długa nazwa"}), 400
        updated["body_font_family"] = val

    if "header_font_size_pt" in data:
        try:
            n = int(data["header_font_size_pt"])
        except (ValueError, TypeError):
            return jsonify({"error": "header_font_size_pt: nieprawidłowa liczba"}), 400
        if n < 2 or n > 50:
            return jsonify({"error": "header_font_size_pt: zakres 2–50"}), 400
        updated["header_font_size_pt"] = str(n)

    if not updated:
        return jsonify({"error": "brak pól do aktualizacji"}), 400

    with db_session() as db:
        try:
            with db:
                for k, v in updated.items():
                    db.execute(
                        "INSERT INTO cert_settings (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (k, v),
                    )
                from mbr.shared import audit
                audit.log_event(
                    audit.EVENT_CERT_SETTINGS_UPDATED,
                    entity_type="cert",
                    entity_label="_settings",
                    payload={"updated": updated},
                    db=db,
                )
        except Exception as e:
            return jsonify({"error": f"zapis nie powiódł się: {e}"}), 500

    return jsonify({"ok": True})
```

- [ ] **Step 4: Testy zielone**

Run: `pytest tests/test_certs.py -k cert_settings_api -v`
Expected: 3 passed.

- [ ] **Step 5: Dodaj modal UI w `wzory_cert.html`**

Na nagłówku listy (ok. lina 167-175), dodaj trzeci przycisk:

```html
    <div class="wc-list-head">
      <div class="wc-title">Wzory świadectw</div>
      <div class="wc-head-spacer"></div>
      <div class="wc-search-wrap"> ... </div>
      <button class="wc-btn wc-btn-o wc-btn-sm" onclick="openCertSettings()" style="margin-right:10px;">Ustawienia globalne</button>
      <button class="wc-btn wc-btn-p" onclick="showNewForm()">+ Nowy produkt</button>
    </div>
```

Po modal-u copy (z Taska 10), dodaj:

```html
<!-- ═══ Cert Settings Modal ═══ -->
<div class="wc-modal" id="wc-settings-modal" onclick="if(event.target===this)closeCertSettings()">
  <div class="wc-modal-box" style="max-width:460px;height:auto;">
    <div class="wc-modal-head">
      <span style="font-weight:700;">Ustawienia globalne świadectw</span>
      <button class="wc-modal-close" onclick="closeCertSettings()">&times;</button>
    </div>
    <div style="padding:16px 20px;">
      <div style="margin-bottom:12px;color:var(--text-sec);font-size:11px;">
        Zmiany obowiązują od razu dla wszystkich generowanych świadectw. Już wydane dokumenty pozostają bez zmian.
      </div>
      <label class="wc-lbl">Font (rodzina)</label>
      <input class="wc-inp" type="text" id="wc-s-font" placeholder="np. TeX Gyre Bonum, EB Garamond">
      <div style="font-size:10px;color:var(--text-dim);margin-top:3px;">Nazwa z Google Fonts lub zainstalowanego fontu. Domyślnie: TeX Gyre Bonum.</div>

      <label class="wc-lbl" style="margin-top:14px;">Rozmiar czcionki nagłówka (nazwa produktu, pt)</label>
      <input class="wc-inp" type="number" id="wc-s-hdr" min="2" max="50" style="width:100px;">

      <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:18px;">
        <button class="wc-btn wc-btn-o" onclick="closeCertSettings()">Anuluj</button>
        <button class="wc-btn wc-btn-p" onclick="saveCertSettings()">Zapisz</button>
      </div>
    </div>
  </div>
</div>
```

JS (po `doCopyProduct`):

```javascript
function openCertSettings() {
  fetch('/api/cert/settings').then(function(r) { return r.json(); }).then(function(s) {
    document.getElementById('wc-s-font').value = s.body_font_family || '';
    document.getElementById('wc-s-hdr').value = s.header_font_size_pt || 14;
    document.getElementById('wc-settings-modal').classList.add('show');
  });
}

function closeCertSettings() {
  document.getElementById('wc-settings-modal').classList.remove('show');
}

function saveCertSettings() {
  var font = document.getElementById('wc-s-font').value.trim();
  var hdr = parseInt(document.getElementById('wc-s-hdr').value);
  if (!font) { flash('Nazwa fontu jest wymagana', false); return; }
  if (!hdr || hdr < 2 || hdr > 50) { flash('Rozmiar nagłówka 2–50 pt', false); return; }
  fetch('/api/cert/settings', {
    method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ body_font_family: font, header_font_size_pt: hdr }),
  }).then(function(r) { return r.json().then(function(d) { return { status: r.status, data: d }; }); })
    .then(function(res) {
      if (res.data.ok) {
        flash('Ustawienia zapisane', true);
        closeCertSettings();
      } else {
        flash('Błąd: ' + (res.data.error || 'nie udało się zapisać'), false);
      }
    });
}
```

- [ ] **Step 6: Smoke test**

Uruchom serwer, kliknij "Ustawienia globalne" na liście → modal otwiera się z aktualnymi wartościami. Zmień, Zapisz → flash + zamknięcie. Podgląd PDF (po Tasku 15) powinien użyć nowego fontu.

- [ ] **Step 7: Commit**

```bash
git add mbr/certs/routes.py mbr/templates/admin/wzory_cert.html tests/test_certs.py
git commit -m "feat(certs): global cert settings modal + API"
```

---

## Task 17: Regression suite + final manual pass

**Files:** (brak zmian kodowych — kontrola jakości)

- [ ] **Step 1: Uruchom pełny suite testów**

```bash
pytest -v
```

Expected: wszystkie zielone. Jeśli są regresje w innych modułach — diagnozuj PRZED zamknięciem planu.

- [ ] **Step 2: Smoke test pełnego flow edytora**

1. Otwórz `/admin/wzory-cert` → lista się ładuje.
2. Kliknij "Ustawienia globalne" → wartości default TeX Gyre Bonum / 14pt.
3. Zmień header size na 16pt, Zapisz → flash OK.
4. Wybierz istniejący produkt → edytor otwiera się.
5. Dodaj parametr bez nazwy → Zapisz → flash "bez nazwy PL".
6. Wypełnij → Zapisz → OK.
7. Zmień coś innego → gwiazdka `*`. Spróbuj "← Powrót" → confirm.
8. Otwórz podgląd PDF → widać z nowym rozmiarem nagłówka.
9. Zmień coś w edytorze z otwartym modalem podglądu → po ~800ms podgląd się odświeża.
10. Wejdź w "Historia" → widać wpisy z ostatnich zapisów.
11. Na liście: "Kopiuj" produkt → podaj nową nazwę → kopia pojawia się na liście.
12. W dropdown-ie "Powiąż z pomiarem" widać opcje z ● (MBR) i ○ (poza MBR).
13. Dodaj parametr z `qualitative_result="charakterystyczny"` bez `data_field` → Zapisz → OK.
14. Nazwa parametru z `|` (np. `kokamido|amidoamin`) → podgląd → łamanie linii.

- [ ] **Step 3: Jeśli Gotenberg w prod offline — zweryfikuj bundled font**

Sprawdź, że modyfikowany `deploy/gotenberg.service` poprawnie montuje `.ttf` (jeśli wybrano ten wariant w Task 5). Logi Gotenberga nie wskazują na brakujące fonty.

- [ ] **Step 4: Commit w formacie podsumowania**

```bash
git log --oneline cert_editor_start..HEAD
# Jeśli w trakcie powstał branch, zamień na właściwy zakres.
```

Jeżeli wszystkie kroki skonsolidowane commit-owo — przygotuj podsumowanie:

```bash
# brak dalszych edycji — opcjonalnie merge-commit w parent lub PR
```

---

## Self-review (wykonane)

**Spec coverage:**

- Pain point 1 (brak kopii) → Task 9 + 10.
- Pain point 2 (dropdown wąski) → Task 7 + 8.
- Pain point 3 (długie nazwy) → Task 4 (geometria) + Task 6 (`|`).
- Pain point 4 (brak typografii) → Task 1 + 2 + 3 + 4 + 5 + 16.
- Pain point 5 (dirty state) → Task 11.
- Pain point 6 (walidacja) → Task 12.
- Pain point 7 (historia) → Task 2 (audit filter) + Task 13 + Task 14.
- Pain point 8 (auto-refresh) → Task 15.

Wszystkie spec-owe "sekcje testów" pokryte — cert_settings, copy, audit history, `|` line break, rozszerzony dropdown. Invariant "regeneracja archiwum działa" — pokryty przez istniejące testy w `test_certs.py` + nowy test w Task 4.

**Placeholder scan:** Brak TBD/TODO w akcjach. Wszystkie code blocks mają pełną treść. Wyjątek: Task 5 jest świadomie "decyzja + configuration" — nie potrzebuje kodu do skopiowania, opisana decyzja + komendy shell.

**Type consistency:**
- `_load_cert_settings` zwraca dict z `body_font_family: str`, `header_font_size_pt: int` — spójne w Task 3, Task 16 (GET), Task 16 (PUT walidacja zakresu 2-50).
- `query_audit_history_by_label(db, entity_type, entity_label)` — spójne z call-site w Task 13.
- Kopia endpoint: body `{new_display_name}`, response `{ok, key}` — spójne między testem (Task 9) a UI (Task 10).
- `_setDirty(flag)` — spójne w Task 11 i 15.

Brak inconsistency, wszystkie ID-y funkcji/zmiennych się zgadzają.

**Scope:** 17 zadań to rozsądna ścieżka — każdy task jest self-contained, commitowalny. Jeżeli subagent-driven execution, można każdy task oddelegować do innego subagenta ze świeżym kontekstem.
