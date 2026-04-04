# Batch Card Database Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add database tables and API endpoints for recording process-stage analytical data (amidowanie → utlenienie) + corrections, and migrate historical OCR data into the same format.

**Architecture:** Two new tables (`ebr_etapy_analizy`, `ebr_korekty`) alongside existing `ebr_wyniki`. New `etapy_config.py` defines parameters per stage per product. New `etapy_models.py` provides CRUD. Flask endpoints in `app.py`. Migration script reads OCR JSONs and inserts into new tables.

**Tech Stack:** Python 3, Flask, SQLite3, existing LIMS codebase

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `mbr/etapy_config.py` | CREATE | Stage-parameter definitions per product |
| `mbr/etapy_models.py` | CREATE | CRUD: save/get analyses + corrections |
| `mbr/models.py` | MODIFY | Add CREATE TABLE statements |
| `mbr/app.py` | MODIFY | Add API endpoints |
| `migrate_ocr_to_lims.py` | CREATE | OCR JSON → new tables migration |

---

### Task 1: Create etapy_config.py — Stage Parameter Definitions

**Files:**
- Create: `mbr/etapy_config.py`

- [ ] **Step 1: Create the configuration file**

Create `mbr/etapy_config.py` with the full `ETAPY_ANALIZY` dict from the spec. Include both K7 and K40GLOL configs plus a `PRODUCT_ETAPY_MAP` that maps other products to their parent config:

```python
"""Process stage analytical parameter definitions per product."""

ETAPY_ANALIZY = {
    "Chegina_K7": {
        "amidowanie": {
            "label": "Amidowanie",
            "parametry": [
                {"kod": "le", "label": "LE (liczba estrowa)", "typ": "bezposredni"},
                {"kod": "la", "label": "LA (liczba kwasowa)", "typ": "titracja"},
                {"kod": "lk", "label": "LK (końcowa)", "typ": "titracja"},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni"},
            ],
            "korekty": [],
        },
        "smca": {
            "label": "Wytworzenie SMCA",
            "parametry": [
                {"kod": "ph", "label": "pH roztworu", "typ": "bezposredni"},
            ],
            "korekty": ["NaOH", "MCA"],
        },
        "czwartorzedowanie": {
            "label": "Czwartorzędowanie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni"},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni"},
                {"kod": "aa", "label": "%AA", "typ": "titracja"},
            ],
            "korekty": ["NaOH", "MCA"],
        },
        "sulfonowanie": {
            "label": "Sulfonowanie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni"},
                {"kod": "so3", "label": "%SO₃²⁻", "typ": "titracja"},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni"},
            ],
            "korekty": ["Na2SO3"],
        },
        "utlenienie": {
            "label": "Utlenienie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni"},
                {"kod": "so3", "label": "%SO₃²⁻", "typ": "titracja"},
                {"kod": "h2o2", "label": "%H₂O₂", "typ": "titracja"},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni"},
            ],
            "korekty": ["Perhydrol"],
        },
    },
    "Chegina_K40GLOL": {
        "amidowanie": {
            "label": "Amidowanie",
            "parametry": [
                {"kod": "le", "label": "LE", "typ": "bezposredni"},
                {"kod": "la", "label": "LA", "typ": "titracja"},
                {"kod": "lk", "label": "LK", "typ": "titracja"},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni"},
            ],
            "korekty": [],
        },
        "smca": {
            "label": "Wytworzenie SMCA",
            "parametry": [
                {"kod": "ph", "label": "pH roztworu", "typ": "bezposredni"},
            ],
            "korekty": ["NaOH", "MCA"],
        },
        "czwartorzedowanie": {
            "label": "Czwartorzędowanie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni"},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni"},
                {"kod": "aa", "label": "%AA", "typ": "titracja"},
            ],
            "korekty": ["NaOH", "MCA"],
        },
        "sulfonowanie": {
            "label": "Sulfonowanie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni"},
                {"kod": "so3", "label": "%SO₃²⁻", "typ": "titracja"},
                {"kod": "h2o2", "label": "%H₂O₂", "typ": "titracja"},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni"},
            ],
            "korekty": ["Na2SO3"],
        },
        "utlenienie": {
            "label": "Utlenienie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni"},
                {"kod": "so3", "label": "%SO₃²⁻", "typ": "titracja"},
                {"kod": "h2o2", "label": "%H₂O₂", "typ": "titracja"},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni"},
            ],
            "korekty": ["Kw. cytrynowy", "Perhydrol"],
        },
        "rozjasnianie": {
            "label": "Rozjaśnianie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni"},
                {"kod": "h2o2", "label": "%H₂O₂", "typ": "titracja"},
                {"kod": "barwa_fau", "label": "Barwa FAU", "typ": "bezposredni"},
                {"kod": "barwa_hz", "label": "Barwa Hz", "typ": "bezposredni"},
            ],
            "korekty": ["Perhydrol"],
        },
    },
}

# Map product variants to their parent config
PRODUCT_ETAPY_MAP = {
    "Chegina_K40GL": "Chegina_K7",
    "Chegina_K40GLO": "Chegina_K7",
    "Chegina_K7B": "Chegina_K7",
    "Chegina_K7GLO": "Chegina_K7",
    "Chegina_K40GLOS": "Chegina_K40GLOL",
    "Chegina_K40GLOL_HQ": "Chegina_K40GLOL",
    "Chegina_K40GLN": "Chegina_K40GLOL",
    "Chegina_GLOL40": "Chegina_K40GLOL",
}


def get_etapy_config(produkt: str) -> dict:
    """Get stage config for a product. Falls back to parent via PRODUCT_ETAPY_MAP."""
    if produkt in ETAPY_ANALIZY:
        return ETAPY_ANALIZY[produkt]
    parent = PRODUCT_ETAPY_MAP.get(produkt)
    if parent and parent in ETAPY_ANALIZY:
        return ETAPY_ANALIZY[parent]
    return {}


# OCR field name → LIMS kod mapping (OCR uses 'procent_aa', LIMS uses 'aa')
OCR_KOD_MAP = {
    "procent_aa": "aa",
    "procent_so3": "so3",
    "procent_h2o2": "h2o2",
    "procent_sm": "sm",
    "procent_nacl": "nacl",
    "procent_sa": "sa",
    "ph_10proc": "ph_10proc",
    "nd20": "nd20",
    "ph": "ph",
    "barwa_fau": "barwa_fau",
    "barwa_hz": "barwa_hz",
    "la_liczba_kwasowa": "la",
    "le_liczba_estrowa": "le",
    "lk_liczba_kwasowa": "lk",
}

# OCR etap name → LIMS etap name mapping
OCR_ETAP_MAP = {
    "amid": "amidowanie",
    "smca": "smca",
    "czwartorzedowanie": "czwartorzedowanie",
    "sulfonowanie": "sulfonowanie",
    "utlenienie": "utlenienie",
    "wybielanie": "rozjasnianie",
    "standaryzacja": "standaryzacja",
}
```

- [ ] **Step 2: Verify module loads**

Run:
```bash
python3 -c "from mbr.etapy_config import get_etapy_config, ETAPY_ANALIZY; cfg = get_etapy_config('Chegina_K7'); print(f'K7 stages: {list(cfg.keys())}'); cfg2 = get_etapy_config('Chegina_K40GL'); print(f'K40GL → {list(cfg2.keys())}')"
```

Expected:
```
K7 stages: ['amidowanie', 'smca', 'czwartorzedowanie', 'sulfonowanie', 'utlenienie']
K40GL → ['amidowanie', 'smca', 'czwartorzedowanie', 'sulfonowanie', 'utlenienie']
```

- [ ] **Step 3: Commit**

```bash
git add mbr/etapy_config.py
git commit -m "feat: add etapy_config.py — stage parameter definitions per product"
```

---

### Task 2: Add Database Tables

**Files:**
- Modify: `mbr/models.py`

- [ ] **Step 1: Add CREATE TABLE statements to init_mbr_tables**

In `mbr/models.py`, find the `init_mbr_tables` function and add the two new CREATE TABLE statements at the end of the `db.executescript(...)` block, before the closing `""")`:

```sql
CREATE TABLE IF NOT EXISTS ebr_etapy_analizy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ebr_id INTEGER NOT NULL,
    etap TEXT NOT NULL,
    runda INTEGER DEFAULT 1,
    kod_parametru TEXT NOT NULL,
    wartosc REAL,
    dt_wpisu TEXT,
    wpisal TEXT,
    UNIQUE(ebr_id, etap, runda, kod_parametru)
);

CREATE TABLE IF NOT EXISTS ebr_korekty (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ebr_id INTEGER NOT NULL,
    etap TEXT NOT NULL,
    po_rundzie INTEGER,
    substancja TEXT NOT NULL,
    ilosc_kg REAL,
    zalecil TEXT,
    wykonano INTEGER DEFAULT 0,
    dt_zalecenia TEXT,
    dt_wykonania TEXT
);
```

- [ ] **Step 2: Verify tables are created**

Run:
```bash
python3 -c "
from mbr.models import get_db, init_mbr_tables
db = get_db()
init_mbr_tables(db)
tables = [r[0] for r in db.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
print('ebr_etapy_analizy:', 'ebr_etapy_analizy' in tables)
print('ebr_korekty:', 'ebr_korekty' in tables)
cols_ea = [r[1] for r in db.execute('PRAGMA table_info(ebr_etapy_analizy)').fetchall()]
cols_ek = [r[1] for r in db.execute('PRAGMA table_info(ebr_korekty)').fetchall()]
print('EA cols:', cols_ea)
print('EK cols:', cols_ek)
"
```

Expected: Both tables exist with correct columns.

- [ ] **Step 3: Commit**

```bash
git add mbr/models.py
git commit -m "feat: add ebr_etapy_analizy + ebr_korekty tables"
```

---

### Task 3: Create etapy_models.py — CRUD Functions

**Files:**
- Create: `mbr/etapy_models.py`

- [ ] **Step 1: Create CRUD module**

Create `mbr/etapy_models.py`:

```python
"""CRUD for process stage analyses and corrections."""

import sqlite3
from datetime import datetime


def save_etap_analizy(
    db: sqlite3.Connection, ebr_id: int, etap: str, runda: int,
    wyniki: dict, user: str
) -> None:
    """Save analytical results for a process stage round.

    Args:
        ebr_id: batch ID
        etap: stage name ('amidowanie', 'czwartorzedowanie', etc.)
        runda: round number (1, 2, 3...)
        wyniki: {kod: value} e.g. {"ph_10proc": 11.76, "nd20": 1.3952}
        user: who entered the data
    """
    now = datetime.now().isoformat(timespec="seconds")
    for kod, value in wyniki.items():
        if value is None or value == "":
            continue
        try:
            val = float(value)
        except (ValueError, TypeError):
            continue
        db.execute(
            """INSERT INTO ebr_etapy_analizy (ebr_id, etap, runda, kod_parametru, wartosc, dt_wpisu, wpisal)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(ebr_id, etap, runda, kod_parametru)
               DO UPDATE SET wartosc=excluded.wartosc, dt_wpisu=excluded.dt_wpisu, wpisal=excluded.wpisal""",
            (ebr_id, etap, runda, kod, val, now, user),
        )
    db.commit()


def get_etap_analizy(db: sqlite3.Connection, ebr_id: int, etap: str = None) -> dict:
    """Get all analyses for a batch, optionally filtered by stage.

    Returns:
        {etap: {runda: {kod: wartosc}}}
    """
    sql = "SELECT etap, runda, kod_parametru, wartosc, dt_wpisu, wpisal FROM ebr_etapy_analizy WHERE ebr_id = ?"
    params = [ebr_id]
    if etap:
        sql += " AND etap = ?"
        params.append(etap)
    sql += " ORDER BY etap, runda, kod_parametru"

    result = {}
    for row in db.execute(sql, params).fetchall():
        e, r, kod, val, dt, who = row
        if e not in result:
            result[e] = {}
        if r not in result[e]:
            result[e][r] = {}
        result[e][r][kod] = {"wartosc": val, "dt_wpisu": dt, "wpisal": who}
    return result


def get_all_etapy_analizy(db: sqlite3.Connection, ebr_id: int) -> list[dict]:
    """Get all analyses as flat list of dicts (for API response)."""
    rows = db.execute(
        "SELECT id, etap, runda, kod_parametru, wartosc, dt_wpisu, wpisal FROM ebr_etapy_analizy WHERE ebr_id = ? ORDER BY etap, runda",
        (ebr_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_korekta(
    db: sqlite3.Connection, ebr_id: int, etap: str, po_rundzie: int,
    substancja: str, ilosc_kg: float, user: str
) -> int:
    """Add a correction recommendation. Returns korekta ID."""
    now = datetime.now().isoformat(timespec="seconds")
    cur = db.execute(
        """INSERT INTO ebr_korekty (ebr_id, etap, po_rundzie, substancja, ilosc_kg, zalecil, dt_zalecenia)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (ebr_id, etap, po_rundzie, substancja, ilosc_kg, user, now),
    )
    db.commit()
    return cur.lastrowid


def confirm_korekta(db: sqlite3.Connection, korekta_id: int) -> None:
    """Mark a correction as executed."""
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "UPDATE ebr_korekty SET wykonano = 1, dt_wykonania = ? WHERE id = ?",
        (now, korekta_id),
    )
    db.commit()


def get_korekty(db: sqlite3.Connection, ebr_id: int, etap: str = None) -> list[dict]:
    """Get all corrections for a batch."""
    sql = "SELECT * FROM ebr_korekty WHERE ebr_id = ?"
    params = [ebr_id]
    if etap:
        sql += " AND etap = ?"
        params.append(etap)
    sql += " ORDER BY etap, po_rundzie, id"
    return [dict(r) for r in db.execute(sql, params).fetchall()]
```

- [ ] **Step 2: Verify module loads**

Run:
```bash
python3 -c "from mbr.etapy_models import save_etap_analizy, get_etap_analizy, add_korekta, confirm_korekta, get_korekty; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add mbr/etapy_models.py
git commit -m "feat: add etapy_models.py — CRUD for process stage data"
```

---

### Task 4: Add API Endpoints

**Files:**
- Modify: `mbr/app.py`

- [ ] **Step 1: Add endpoints**

Add these routes to `mbr/app.py` (before the certificate endpoints section):

```python
# ---------------------------------------------------------------------------
# Process stage analyses + corrections
# ---------------------------------------------------------------------------

@app.route("/api/etapy-config/<produkt>")
@login_required
def api_etapy_config(produkt):
    from mbr.etapy_config import get_etapy_config
    cfg = get_etapy_config(produkt)
    return jsonify({"config": cfg, "produkt": produkt})


@app.route("/api/ebr/<int:ebr_id>/etapy-analizy")
@login_required
def api_etapy_analizy_get(ebr_id):
    from mbr.etapy_models import get_all_etapy_analizy
    with db_session() as db:
        data = get_all_etapy_analizy(db, ebr_id)
    return jsonify({"analizy": data})


@app.route("/api/ebr/<int:ebr_id>/etapy-analizy", methods=["POST"])
@login_required
def api_etapy_analizy_save(ebr_id):
    from mbr.etapy_models import save_etap_analizy
    data = request.get_json(silent=True) or {}
    etap = data.get("etap")
    runda = int(data.get("runda", 1))
    wyniki = data.get("wyniki", {})
    if not etap or not wyniki:
        return jsonify({"ok": False, "error": "Missing etap or wyniki"}), 400
    user = session.get("user", {}).get("login", "unknown")
    with db_session() as db:
        save_etap_analizy(db, ebr_id, etap, runda, wyniki, user)
    return jsonify({"ok": True})


@app.route("/api/ebr/<int:ebr_id>/korekty")
@login_required
def api_korekty_get(ebr_id):
    from mbr.etapy_models import get_korekty
    etap = request.args.get("etap")
    with db_session() as db:
        data = get_korekty(db, ebr_id, etap=etap)
    return jsonify({"korekty": data})


@app.route("/api/ebr/<int:ebr_id>/korekty", methods=["POST"])
@login_required
def api_korekty_add(ebr_id):
    from mbr.etapy_models import add_korekta
    data = request.get_json(silent=True) or {}
    etap = data.get("etap")
    substancja = data.get("substancja")
    ilosc_kg = float(data.get("ilosc_kg", 0))
    po_rundzie = int(data.get("po_rundzie", 0))
    if not etap or not substancja:
        return jsonify({"ok": False, "error": "Missing etap or substancja"}), 400
    user = session.get("user", {}).get("login", "unknown")
    with db_session() as db:
        kid = add_korekta(db, ebr_id, etap, po_rundzie, substancja, ilosc_kg, user)
    return jsonify({"ok": True, "id": kid})


@app.route("/api/ebr/<int:ebr_id>/korekty/<int:kid>", methods=["PUT"])
@login_required
def api_korekty_confirm(ebr_id, kid):
    from mbr.etapy_models import confirm_korekta
    with db_session() as db:
        confirm_korekta(db, kid)
    return jsonify({"ok": True})
```

- [ ] **Step 2: Verify endpoints load without errors**

Run:
```bash
python3 -c "from mbr.app import app; print('App loads OK')"
```

- [ ] **Step 3: Commit**

```bash
git add mbr/app.py
git commit -m "feat: add API endpoints for process stage analyses + corrections"
```

---

### Task 5: Create OCR Migration Script

**Files:**
- Create: `migrate_ocr_to_lims.py`

- [ ] **Step 1: Create migration script**

Create `migrate_ocr_to_lims.py` in the project root:

```python
"""Migrate OCR-extracted batch data into LIMS process stage tables.

Reads JSONs from data/output_json/Chegina_K7/ and Chegina_K40GLOL/,
maps process stage analyses and corrections into ebr_etapy_analizy + ebr_korekty.

Usage:
    python migrate_ocr_to_lims.py [--dry-run]
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from mbr.models import get_db, init_mbr_tables
from mbr.etapy_models import save_etap_analizy, add_korekta
from mbr.etapy_config import OCR_KOD_MAP, OCR_ETAP_MAP

OUTPUT_DIR = Path("data/output_json")
PRODUCTS = ["Chegina_K7", "Chegina_K40GLOL"]


def extract_analyses_from_kroki(kroki: list, etap_lims: str) -> tuple[list, list]:
    """Extract analyses and corrections from OCR kroki array.

    Returns:
        (analyses, corrections) where:
        analyses = [{"runda": N, "wyniki": {kod: val}}]
        corrections = [{"po_rundzie": N, "substancja": str, "ilosc_kg": float}]
    """
    analyses = []
    corrections = []
    analiza_count = 0

    for krok in kroki:
        typ = krok.get("typ")
        if typ == "analiza":
            analiza_count += 1
            wyniki = {}
            for ocr_key, lims_kod in OCR_KOD_MAP.items():
                val = krok.get(ocr_key)
                if val is not None and val != "":
                    try:
                        wyniki[lims_kod] = float(val)
                    except (ValueError, TypeError):
                        pass
            if wyniki:
                analyses.append({"runda": analiza_count, "wyniki": wyniki})

        elif typ == "korekta":
            substancja = krok.get("substancja", "")
            ilosc = krok.get("ilosc_kg")
            if substancja and ilosc is not None:
                try:
                    corrections.append({
                        "po_rundzie": analiza_count,
                        "substancja": substancja,
                        "ilosc_kg": float(ilosc),
                    })
                except (ValueError, TypeError):
                    pass

    return analyses, corrections


def extract_amid_analyses(amid_data: dict) -> list:
    """Extract analyses from amidowanie stage (special structure)."""
    analyses = []
    dest = amid_data.get("analizy_po_destylacji") or []
    for i, entry in enumerate(dest):
        wyniki = {}
        for ocr_key, lims_kod in OCR_KOD_MAP.items():
            val = entry.get(ocr_key)
            if val is not None and val != "":
                try:
                    wyniki[lims_kod] = float(val)
                except (ValueError, TypeError):
                    pass
        if wyniki:
            analyses.append({"runda": i + 1, "wyniki": wyniki})

    # Also check kroki for additional analyses
    kroki = amid_data.get("kroki") or []
    kroki_analyses, _ = extract_analyses_from_kroki(kroki, "amidowanie")
    # Offset runda numbers
    offset = len(analyses)
    for a in kroki_analyses:
        a["runda"] += offset
        analyses.append(a)

    return analyses


def extract_smca_analyses(smca_data: dict) -> list:
    """Extract analysis from SMCA stage."""
    analyses = []
    analiza = smca_data.get("analiza_smca")
    if analiza:
        wyniki = {}
        for ocr_key, lims_kod in OCR_KOD_MAP.items():
            val = analiza.get(ocr_key)
            if val is not None and val != "":
                try:
                    wyniki[lims_kod] = float(val)
                except (ValueError, TypeError):
                    pass
        if wyniki:
            analyses.append({"runda": 1, "wyniki": wyniki})
    return analyses


def find_or_create_ebr(db, produkt: str, nr_partii: str) -> int:
    """Find existing EBR by produkt + nr_partii, or create one."""
    row = db.execute(
        """SELECT eb.ebr_id FROM ebr_batches eb
           JOIN mbr_templates mt ON mt.mbr_id = eb.mbr_id
           WHERE mt.produkt = ? AND eb.nr_partii = ?""",
        (produkt, nr_partii),
    ).fetchone()
    if row:
        return row["ebr_id"]

    # Create new EBR for historical batch
    mbr = db.execute(
        "SELECT mbr_id FROM mbr_templates WHERE produkt = ? AND status = 'active'",
        (produkt,),
    ).fetchone()
    if not mbr:
        print(f"    WARNING: No active MBR for {produkt}, skipping")
        return None

    batch_id = f"{produkt}__{nr_partii.replace('/', '_')}"
    now = datetime.now().isoformat(timespec="seconds")
    cur = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, status, operator, typ) VALUES (?, ?, ?, ?, 'completed', 'ocr_import', 'szarza')",
        (mbr["mbr_id"], batch_id, nr_partii, now),
    )
    db.commit()
    print(f"    Created EBR {cur.lastrowid} for {produkt} {nr_partii}")
    return cur.lastrowid


def migrate_batch(db, produkt: str, json_path: Path, dry_run: bool) -> dict:
    """Migrate one batch JSON. Returns stats."""
    with open(json_path) as f:
        data = json.load(f)

    nr_partii = data.get("nr_partii", json_path.stem.replace("_", "/"))
    stats = {"analizy": 0, "korekty": 0, "skipped": False}

    if dry_run:
        ebr_id = -1
    else:
        ebr_id = find_or_create_ebr(db, produkt, nr_partii)
        if ebr_id is None:
            stats["skipped"] = True
            return stats

    proc = data.get("proces") or {}
    etapy = proc.get("etapy") or {}

    for ocr_etap, lims_etap in OCR_ETAP_MAP.items():
        if lims_etap == "standaryzacja":
            continue  # Skip — handled by existing ebr_wyniki system

        etap_data = etapy.get(ocr_etap)
        if not etap_data or etap_data is None:
            continue

        # Extract analyses
        if ocr_etap == "amid":
            analyses = extract_amid_analyses(etap_data)
            corrections = []
        elif ocr_etap == "smca":
            analyses = extract_smca_analyses(etap_data)
            corrections = []
        else:
            kroki = etap_data.get("kroki") or []
            analyses, corrections = extract_analyses_from_kroki(kroki, lims_etap)

        # Save
        for a in analyses:
            if not dry_run:
                save_etap_analizy(db, ebr_id, lims_etap, a["runda"], a["wyniki"], "ocr_import")
            stats["analizy"] += len(a["wyniki"])

        for c in corrections:
            if not dry_run:
                add_korekta(db, ebr_id, lims_etap, c["po_rundzie"], c["substancja"], c["ilosc_kg"], "ocr_import")
            stats["korekty"] += 1

    return stats


def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("=== DRY RUN — no data will be written ===\n")

    db = get_db()
    init_mbr_tables(db)

    total = {"analizy": 0, "korekty": 0, "batches": 0, "skipped": 0}

    for produkt in PRODUCTS:
        prod_dir = OUTPUT_DIR / produkt.replace(" ", "_")
        if not prod_dir.exists():
            print(f"No data for {produkt}")
            continue

        json_files = sorted(prod_dir.glob("*.json"))
        print(f"\n{produkt}: {len(json_files)} batches")

        for jf in json_files:
            print(f"  {jf.name}...", end=" ")
            stats = migrate_batch(db, produkt, jf, dry_run)
            if stats["skipped"]:
                print("SKIPPED")
                total["skipped"] += 1
            else:
                print(f"OK ({stats['analizy']} params, {stats['korekty']} corrections)")
                total["analizy"] += stats["analizy"]
                total["korekty"] += stats["korekty"]
                total["batches"] += 1

    print(f"\n{'DRY RUN ' if dry_run else ''}TOTAL: {total['batches']} batches, {total['analizy']} parameters, {total['korekty']} corrections, {total['skipped']} skipped")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test with dry run**

Run:
```bash
python3 migrate_ocr_to_lims.py --dry-run
```

Expected: Lists all batches with parameter/correction counts, no data written.

- [ ] **Step 3: Run actual migration**

Run:
```bash
python3 migrate_ocr_to_lims.py
```

Expected: Migrates all OCR data. Verify:
```bash
python3 -c "
from mbr.models import get_db
db = get_db()
ea = db.execute('SELECT COUNT(*) FROM ebr_etapy_analizy').fetchone()[0]
ek = db.execute('SELECT COUNT(*) FROM ebr_korekty').fetchone()[0]
print(f'Analizy: {ea}, Korekty: {ek}')
# Sample data
rows = db.execute('SELECT etap, runda, kod_parametru, wartosc FROM ebr_etapy_analizy LIMIT 5').fetchall()
for r in rows: print(f'  {r[0]}/{r[1]}: {r[2]}={r[3]}')
"
```

- [ ] **Step 4: Commit**

```bash
git add migrate_ocr_to_lims.py
git commit -m "feat: add OCR → LIMS migration script for process stage data"
```

---

### Task 6: Integration Verification

- [ ] **Step 1: Test API endpoints end-to-end**

Start Flask app and test with curl (or python):
```bash
python3 -c "
import requests, json

BASE = 'http://localhost:5001'

# Login
s = requests.Session()
s.post(f'{BASE}/login', data={'login': 'laborant', 'password': 'laborant'})

# Get etapy config for K7
r = s.get(f'{BASE}/api/etapy-config/Chegina_K7')
cfg = r.json()
print('K7 stages:', list(cfg['config'].keys()))

# Find an EBR
from mbr.models import get_db
db = get_db()
ebr = db.execute(\"SELECT ebr_id FROM ebr_batches WHERE typ='szarza' LIMIT 1\").fetchone()
eid = ebr['ebr_id']
print(f'Testing with EBR {eid}')

# Get analyses
r = s.get(f'{BASE}/api/ebr/{eid}/etapy-analizy')
print(f'Analizy: {len(r.json()[\"analizy\"])} records')

# Get corrections
r = s.get(f'{BASE}/api/ebr/{eid}/korekty')
print(f'Korekty: {len(r.json()[\"korekty\"])} records')

print('All OK')
"
```

- [ ] **Step 2: Verify migrated data is accessible**

```bash
python3 -c "
from mbr.models import get_db
from mbr.etapy_models import get_etap_analizy, get_korekty

db = get_db()
# Find a migrated K7 batch
row = db.execute(\"SELECT eb.ebr_id, mt.produkt, eb.nr_partii FROM ebr_batches eb JOIN mbr_templates mt ON mt.mbr_id=eb.mbr_id WHERE mt.produkt='Chegina_K7' AND eb.status='completed' LIMIT 1\").fetchone()
if row:
    eid = row['ebr_id']
    print(f'Batch: {row[\"produkt\"]} {row[\"nr_partii\"]}')
    data = get_etap_analizy(db, eid)
    for etap, rundas in data.items():
        for runda, params in rundas.items():
            print(f'  {etap}/r{runda}: {list(params.keys())}')
    kors = get_korekty(db, eid)
    for k in kors:
        print(f'  KOREKTA: {k[\"etap\"]} → {k[\"substancja\"]} {k[\"ilosc_kg\"]}kg')
else:
    print('No K7 batches found')
"
```

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete batch card database model — tables, CRUD, API, OCR migration

New tables: ebr_etapy_analizy + ebr_korekty for process stage data.
etapy_config.py: parameter definitions per stage per product (K7 + K40GLOL).
etapy_models.py: save/get analyses, add/confirm corrections.
API: 6 new endpoints for stage data + config.
migrate_ocr_to_lims.py: imports historical OCR data into same format."
```
