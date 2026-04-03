# Certificate Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate PDF certificates (świadectwa) for completed zbiornik analyses, auto-filling results from analysis data into docx-matching HTML templates.

**Architecture:** Parse docx templates once to extract full structure (metadata + table), render as HTML via Jinja2, convert to PDF via weasyprint. Certificate records stored in `swiadectwa` table. Parameter mapping from `cert_mappings.py` (already exists). UI: button in completed zbiornik footer → template picker → PDF download.

**Tech Stack:** Python/Flask, python-docx (parsing), weasyprint (PDF), SQLite, Jinja2, vanilla JS

**Spec:** `docs/superpowers/specs/2026-04-03-swiadectwa-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `mbr/cert_gen.py` | Create | Parse docx templates, fill values, generate PDF via weasyprint |
| `mbr/cert_mappings.py` | Exists | Parameter mappings (90 templates, 408 params) |
| `mbr/models.py` | Modify | Add `swiadectwa` table, CRUD functions |
| `mbr/app.py` | Modify | Add certificate API routes |
| `mbr/templates/pdf/swiadectwo.html` | Create | HTML/CSS template matching docx certificate layout |
| `mbr/templates/laborant/_fast_entry_content.html` | Modify | Add "Wystaw świadectwo" button + template picker |

---

### Task 1: Database — swiadectwa table + CRUD

**Files:**
- Modify: `mbr/models.py`

- [ ] **Step 1: Add swiadectwa table to init_mbr_tables**

In `mbr/models.py`, in `init_mbr_tables`, add after the `feedback` table creation:

```python
    db.execute("""
        CREATE TABLE IF NOT EXISTS swiadectwa (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ebr_id          INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
            template_name   TEXT NOT NULL,
            nr_partii       TEXT NOT NULL,
            pdf_path        TEXT NOT NULL,
            dt_wystawienia  TEXT NOT NULL,
            wystawil        TEXT NOT NULL
        )
    """)
```

- [ ] **Step 2: Add CRUD functions**

At the end of models.py (before migrations section), add:

```python
def create_swiadectwo(db, ebr_id, template_name, nr_partii, pdf_path, wystawil):
    """Create a certificate record. Returns id."""
    now = datetime.now().isoformat(timespec="seconds")
    cur = db.execute(
        "INSERT INTO swiadectwa (ebr_id, template_name, nr_partii, pdf_path, dt_wystawienia, wystawil) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ebr_id, template_name, nr_partii, pdf_path, now, wystawil),
    )
    db.commit()
    return cur.lastrowid


def list_swiadectwa(db, ebr_id):
    """List certificates for a given EBR batch."""
    rows = db.execute(
        "SELECT * FROM swiadectwa WHERE ebr_id = ? ORDER BY dt_wystawienia DESC",
        (ebr_id,),
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 3: Commit**

```bash
git add mbr/models.py
git commit -m "feat: swiadectwa table + create/list functions"
```

---

### Task 2: Certificate generator — parse docx + render HTML + PDF

**Files:**
- Create: `mbr/cert_gen.py`
- Create: `mbr/templates/pdf/swiadectwo.html`

- [ ] **Step 1: Create cert_gen.py — docx parser + PDF generator**

Create `mbr/cert_gen.py`:

```python
"""Certificate (świadectwo) PDF generation.

Parses docx template to extract metadata + table structure,
fills with analysis results, renders HTML, converts to PDF via weasyprint.
"""
import os
import re
from datetime import datetime, timedelta
from docx import Document
from flask import render_template

from mbr.cert_mappings import CERT_MAPPINGS

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "swiadectwa")


def list_templates_for_product(produkt):
    """Return list of template filenames matching a product name.
    Matches by checking if short product name appears in filename.
    """
    # Build search terms from product name
    short = produkt.replace("Chegina_", "").replace("_", " ")
    search_terms = [short]
    # Also try with original underscores replaced
    if "Chegina" in produkt:
        search_terms.append(produkt.replace("Chegina_", "Chegina "))

    results = []
    all_files = set()

    # Scan both root and wzory/ subfolder
    for dirpath in [TEMPLATES_DIR, os.path.join(TEMPLATES_DIR, "wzory")]:
        if not os.path.isdir(dirpath):
            continue
        for f in os.listdir(dirpath):
            if not f.endswith(".docx") or f.startswith("~"):
                continue
            if f in all_files:
                continue
            all_files.add(f)
            fname_lower = f.lower()
            for term in search_terms:
                if term.lower() in fname_lower:
                    # Extract display name: remove prefix and .docx
                    display = f.replace(".docx", "")
                    for prefix in ["Świadectwo_Certificate-", "Świadectwo_Certificate- ",
                                   "Świadectwo_Certificate ", "ŚwiadectwoCertificate-",
                                   "Certificate Świadectwo-", "Świadectwo-Certificate - ",
                                   "Świadectwo-Certificate -", "AVON ", "PRIME ",
                                   "LEHVOSS ", "REVADA "]:
                        display = display.replace(prefix, "")
                    results.append({"filename": f, "display": display.strip()})
                    break

    results.sort(key=lambda x: x["display"])
    return results


def _find_template_file(filename):
    """Find the docx file in templates dir or wzory/ subfolder."""
    for dirpath in [TEMPLATES_DIR, os.path.join(TEMPLATES_DIR, "wzory")]:
        path = os.path.join(dirpath, filename)
        if os.path.isfile(path):
            return path
    return None


def parse_docx_template(filename):
    """Parse a docx certificate template. Returns metadata + table rows."""
    path = _find_template_file(filename)
    if not path:
        return None

    doc = Document(path)

    # Extract metadata from paragraphs
    meta = {
        "tds": "",
        "cas": "",
        "opinion": "",
    }
    for p in doc.paragraphs:
        text = p.text.strip()
        if "TDS:" in text or "Classified on" in text:
            m = re.search(r'[PT]\d{3}', text)
            if m:
                meta["tds"] = m.group()
            m = re.search(r'CAS:\s*([\d-]+)', text)
            if m:
                meta["cas"] = m.group(1)
        if "odpowiada wymaganiom" in text or "complies with" in text:
            meta["opinion"] = text

    # Extract table
    table_rows = []
    if doc.tables:
        table = doc.tables[0]
        # Header row
        header = [c.text.strip() for c in table.rows[0].cells]
        # Data rows
        for row in table.rows[1:]:
            cells = [c.text.strip() for c in row.cells]
            table_rows.append({
                "param": cells[0] if len(cells) > 0 else "",
                "requirement": cells[1] if len(cells) > 1 else "",
                "method": cells[2] if len(cells) > 2 else "",
                "result": cells[3] if len(cells) > 3 else "",
            })

    return {"meta": meta, "header": header if doc.tables else [], "rows": table_rows}


def generate_certificate_pdf(filename, ebr, wyniki_flat):
    """Generate certificate PDF.

    filename: docx template filename
    ebr: dict with nr_partii, produkt, dt_start
    wyniki_flat: dict {kod: wartosc} — flat analysis results

    Returns PDF bytes.
    """
    from weasyprint import HTML

    # Parse template
    tmpl = parse_docx_template(filename)
    if not tmpl:
        raise ValueError(f"Template not found: {filename}")

    # Get mappings
    mappings = CERT_MAPPINGS.get(filename, [])
    kod_map = {m["row"]: m["kod"] for m in mappings}

    # Fill results
    for i, row in enumerate(tmpl["rows"]):
        kod = kod_map.get(i)
        if kod and kod in wyniki_flat:
            val = wyniki_flat[kod]
            # Format: replace . with , for Polish notation
            if isinstance(val, (int, float)):
                row["result"] = str(val).replace(".", ",")
            else:
                row["result"] = str(val).replace(".", ",") if val else ""

    # Dates
    dt_start = datetime.fromisoformat(ebr["dt_start"]) if ebr.get("dt_start") else datetime.now()
    dt_expiry = dt_start + timedelta(days=365)

    # Product display name
    produkt_display = ebr["produkt"].replace("_", " ")

    html = render_template("pdf/swiadectwo.html",
                           meta=tmpl["meta"],
                           header=tmpl["header"],
                           rows=tmpl["rows"],
                           nr_partii=ebr["nr_partii"],
                           produkt=produkt_display,
                           dt_produkcji=dt_start.strftime("%d.%m.%Y"),
                           dt_waznosci=dt_expiry.strftime("%d.%m.%Y"),
                           dt_wystawienia=datetime.now().strftime("%Y-%m-%d"),
                           )
    return HTML(string=html).write_pdf()


def save_certificate_pdf(pdf_bytes, produkt, template_filename, nr_partii):
    """Save PDF to data/swiadectwa/{year}/{product}/{name}_{nr}.pdf. Returns path."""
    year = str(datetime.now().year)
    # Clean names for filesystem
    prod_clean = produkt.replace(" ", "_")
    tmpl_clean = template_filename.replace(".docx", "").replace(" ", "_")
    nr_clean = nr_partii.replace("/", "_")

    dir_path = os.path.join("data", "swiadectwa", year, prod_clean)
    os.makedirs(dir_path, exist_ok=True)

    filename = f"{tmpl_clean}_{nr_clean}.pdf"
    filepath = os.path.join(dir_path, filename)

    with open(filepath, "wb") as f:
        f.write(pdf_bytes)

    return filepath
```

- [ ] **Step 2: Create HTML template for certificate PDF**

Create `mbr/templates/pdf/swiadectwo.html`:

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page { size: A4; margin: 20mm 18mm; }
  body { font-family: 'Times New Roman', Times, serif; font-size: 10pt; color: #000; }

  .header { text-align: center; margin-bottom: 6mm; }
  .logo-text { font-size: 14pt; font-weight: bold; letter-spacing: 1px; margin-bottom: 2mm; }
  .product-name { font-size: 16pt; font-weight: bold; margin: 4mm 0; }
  .subtitle { font-size: 9pt; color: #333; }

  .meta-table { width: 100%; margin: 4mm 0; font-size: 9pt; }
  .meta-table td { padding: 1mm 0; vertical-align: top; }
  .meta-label { width: 55%; }

  table.results {
    width: 100%; border-collapse: collapse; margin: 5mm 0;
    font-size: 9pt;
  }
  table.results th, table.results td {
    border: 0.5pt solid #000; padding: 2mm 3mm; text-align: left;
    vertical-align: top;
  }
  table.results th {
    background: #f0f0f0; font-weight: bold; font-size: 8.5pt;
  }
  table.results td:nth-child(2),
  table.results td:nth-child(4) { text-align: center; }
  table.results th:nth-child(2),
  table.results th:nth-child(4) { text-align: center; }

  .opinion { margin: 5mm 0; font-size: 10pt; }
  .footer-info { margin-top: 8mm; font-size: 9pt; }
  .signature-area { margin-top: 12mm; display: flex; justify-content: space-between; font-size: 9pt; }
  .sig-block { text-align: center; }
  .sig-line { margin-top: 15mm; border-top: 0.5pt solid #000; padding-top: 1mm; font-size: 8pt; color: #555; }
  .electronic { margin-top: 8mm; font-size: 8pt; font-style: italic; color: #666; text-align: center; }
</style>
</head>
<body>

<div class="header">
  <div class="logo-text">PCC Exol SA</div>
  <div style="font-size:11pt; margin-bottom:2mm;">Świadectwo Jakości / Quality Certificate</div>
  <div class="product-name">{{ produkt }}</div>
  {% if meta.tds or meta.cas %}
  <div class="subtitle">
    {% if meta.tds %}Klasyfikowany na podstawie specyfikacji / Classified on TDS: {{ meta.tds }}{% endif %}
    {% if meta.cas %} CAS: {{ meta.cas }}{% endif %}
  </div>
  {% endif %}
</div>

<table class="meta-table">
  <tr>
    <td class="meta-label">Partia / Batch:</td>
    <td><strong>{{ nr_partii }}</strong></td>
  </tr>
  <tr>
    <td class="meta-label">Data produkcji / Production date:</td>
    <td>{{ dt_produkcji }}</td>
  </tr>
  <tr>
    <td class="meta-label">Data ważności / Expiry date:</td>
    <td>{{ dt_waznosci }}</td>
  </tr>
  <tr>
    <td class="meta-label">Kraj pochodzenia / Country of origin:</td>
    <td>Polska / Poland</td>
  </tr>
</table>

<table class="results">
  <thead>
    <tr>
      {% for h in header %}
      <th>{{ h }}</th>
      {% endfor %}
    </tr>
  </thead>
  <tbody>
    {% for row in rows %}
    <tr>
      <td>{{ row.param }}</td>
      <td>{{ row.requirement }}</td>
      <td>{{ row.method }}</td>
      <td><strong>{{ row.result }}</strong></td>
    </tr>
    {% endfor %}
  </tbody>
</table>

{% if meta.opinion %}
<div class="opinion">
  <strong>Opinia Laboratorium KJ / Opinion of Quality Control Laboratory:</strong><br>
  {{ meta.opinion }}
</div>
{% endif %}

<div class="footer-info">
  Sobowidz, {{ dt_wystawienia }}
</div>

<div style="margin-top:10mm; font-size:9pt;">
  Wystawił / The certificate made by:<br>
  Specjalista ds. KJ / Quality Control Specialist
</div>

<div class="electronic">
  Dokument utworzony elektronicznie, nie wymaga podpisu.<br>
  The certificate is not signed as it is electronically edited.
</div>

</body>
</html>
```

- [ ] **Step 3: Commit**

```bash
git add mbr/cert_gen.py mbr/templates/pdf/swiadectwo.html
git commit -m "feat: certificate PDF generator — parse docx, fill results, render via weasyprint"
```

---

### Task 3: API routes for certificates

**Files:**
- Modify: `mbr/app.py`

- [ ] **Step 1: Add imports**

Add to imports in `mbr/app.py`:

```python
from mbr.models import create_swiadectwo, list_swiadectwa
from mbr.cert_gen import list_templates_for_product, generate_certificate_pdf, save_certificate_pdf
```

- [ ] **Step 2: Add API routes**

Add after the feedback API route:

```python
@app.route("/api/cert/templates")
@login_required
def api_cert_templates():
    produkt = request.args.get("produkt", "")
    if not produkt:
        return jsonify({"templates": []})
    from mbr.cert_gen import list_templates_for_product
    templates = list_templates_for_product(produkt)
    return jsonify({"templates": templates})


@app.route("/api/cert/generate", methods=["POST"])
@login_required
def api_cert_generate():
    data = request.get_json(silent=True) or {}
    ebr_id = data.get("ebr_id")
    template_name = data.get("template_name")
    if not ebr_id or not template_name:
        return jsonify({"error": "missing ebr_id or template_name"}), 400

    with db_session() as db:
        ebr = get_ebr(db, ebr_id)
        if not ebr:
            return jsonify({"error": "EBR not found"}), 404

        # Get flat wyniki (latest values per kod)
        wyniki_raw = get_ebr_wyniki(db, ebr_id)
        wyniki_flat = {}
        for sekcja, params in wyniki_raw.items():
            for kod, row in params.items():
                if row.get("wartosc") is not None:
                    wyniki_flat[kod] = row["wartosc"]

        # Generate PDF
        from mbr.cert_gen import generate_certificate_pdf, save_certificate_pdf
        pdf_bytes = generate_certificate_pdf(template_name, ebr, wyniki_flat)
        pdf_path = save_certificate_pdf(pdf_bytes, ebr["produkt"], template_name, ebr["nr_partii"])

        # Save record
        shift_ids = session.get("shift_workers", [])
        if shift_ids:
            workers = db.execute(
                f"SELECT inicjaly, nickname FROM workers WHERE id IN ({','.join('?' * len(shift_ids))})",
                shift_ids
            ).fetchall()
            wystawil = ", ".join(w["nickname"] or w["inicjaly"] for w in workers)
        else:
            wystawil = session["user"]["login"]

        cert_id = create_swiadectwo(db, ebr_id, template_name, ebr["nr_partii"], pdf_path, wystawil)

    return jsonify({"ok": True, "cert_id": cert_id, "pdf_path": pdf_path})


@app.route("/api/cert/<int:cert_id>/pdf")
@login_required
def api_cert_pdf(cert_id):
    with db_session() as db:
        row = db.execute("SELECT * FROM swiadectwa WHERE id = ?", (cert_id,)).fetchone()
        if not row:
            return "Not found", 404
        pdf_path = row["pdf_path"]
    if not os.path.isfile(pdf_path):
        return "PDF not found", 404
    return send_file(pdf_path, mimetype="application/pdf")


@app.route("/api/cert/list")
@login_required
def api_cert_list():
    ebr_id = request.args.get("ebr_id", type=int)
    if not ebr_id:
        return jsonify({"certs": []})
    with db_session() as db:
        certs = list_swiadectwa(db, ebr_id)
    return jsonify({"certs": certs})
```

Add `import os` and `from flask import send_file` to imports if not already present.

- [ ] **Step 3: Commit**

```bash
git add mbr/app.py
git commit -m "feat: certificate API — templates list, generate PDF, download, history"
```

---

### Task 4: UI — certificate button + template picker in completed zbiornik

**Files:**
- Modify: `mbr/templates/laborant/_fast_entry_content.html`

- [ ] **Step 1: Add "Wystaw świadectwo" button to completed footer**

Find the completed footer (around line 77):

```html
{% else %}
<div id="detail-footer" class="footer">
  <div class="f-sp"></div>
  <a href="/pdf/ebr/{{ ebr.ebr_id }}" class="btn btn-p" target="_blank">PDF</a>
</div>
{% endif %}
```

Replace with:

```html
{% else %}
<div id="detail-footer" class="footer">
  <div id="cert-history"></div>
  <div class="f-sp"></div>
  {% if ebr.typ == 'zbiornik' %}
  <button class="btn btn-o" onclick="openCertPicker()">Wystaw świadectwo</button>
  {% endif %}
  <a href="/pdf/ebr/{{ ebr.ebr_id }}" class="btn btn-p" target="_blank">PDF</a>
</div>
{% endif %}
```

- [ ] **Step 2: Add certificate picker panel and JS**

Add before the `<style>` tag in the template:

```html
<!-- Certificate template picker -->
<div class="modal-overlay" id="cert-picker" onclick="if(event.target===this)this.classList.remove('show')">
  <div class="modal" style="max-width:440px;">
    <div class="modal-head">
      <div class="modal-icon" style="background:var(--teal-bg);color:var(--teal);">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" style="width:20px;height:20px;"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
      </div>
      <div class="modal-titles">
        <div class="modal-title">Wystaw świadectwo</div>
        <div class="modal-subtitle">Wybierz wzór</div>
      </div>
      <button class="modal-close" onclick="document.getElementById('cert-picker').classList.remove('show')">&times;</button>
    </div>
    <div class="modal-body" id="cert-template-list" style="padding:0;max-height:50vh;overflow-y:auto;">
      Ładowanie...
    </div>
  </div>
</div>
```

Add JS (in the script block):

```javascript
async function openCertPicker() {
    document.getElementById('cert-picker').classList.add('show');
    var resp = await fetch('/api/cert/templates?produkt=' + encodeURIComponent('{{ ebr.produkt }}'));
    var data = await resp.json();
    var list = document.getElementById('cert-template-list');
    if (data.templates.length === 0) {
        list.innerHTML = '<div style="padding:20px;color:var(--text-dim);font-size:12px;text-align:center;">Brak wzorów dla tego produktu.</div>';
        return;
    }
    list.innerHTML = data.templates.map(function(t) {
        return '<div class="cert-opt" onclick="generateCert(\'' + t.filename.replace(/'/g, "\\'") + '\')">' +
            '<span class="cert-opt-name">' + t.display + '</span>' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="width:14px;height:14px;color:var(--text-dim);flex-shrink:0;"><path d="M5 12h14"/><path d="M12 5l7 7-7 7"/></svg>' +
        '</div>';
    }).join('');
}

async function generateCert(filename) {
    var opt = event.target.closest('.cert-opt');
    if (opt) opt.style.opacity = '0.5';
    var resp = await fetch('/api/cert/generate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ebr_id: ebrId, template_name: filename})
    });
    var data = await resp.json();
    if (data.ok) {
        document.getElementById('cert-picker').classList.remove('show');
        // Open PDF
        window.open('/api/cert/' + data.cert_id + '/pdf', '_blank');
        // Refresh history
        loadCertHistory();
    }
}

async function loadCertHistory() {
    var resp = await fetch('/api/cert/list?ebr_id=' + ebrId);
    var data = await resp.json();
    var el = document.getElementById('cert-history');
    if (!el || data.certs.length === 0) return;
    el.innerHTML = data.certs.map(function(c) {
        var name = c.template_name.replace('.docx', '').substring(0, 30);
        return '<a href="/api/cert/' + c.id + '/pdf" target="_blank" class="cert-hist-link">' + name + '</a>';
    }).join('');
}

// Load cert history on init for completed batches
if (ebrStatus === 'completed') { loadCertHistory(); }
```

- [ ] **Step 3: Add CSS**

In the `<style>` block:

```css
.cert-opt {
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px 20px; cursor: pointer; border-bottom: 1px solid var(--border-subtle, #f0ece4);
    transition: background 0.1s;
}
.cert-opt:hover { background: var(--teal-bg); }
.cert-opt:last-child { border-bottom: none; }
.cert-opt-name { font-size: 12px; font-weight: 500; }
.cert-hist-link {
    font-size: 10px; color: var(--teal); text-decoration: none;
    margin-right: 8px; padding: 2px 6px; border-radius: 4px;
    background: var(--teal-bg);
}
.cert-hist-link:hover { text-decoration: underline; }
```

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat: certificate UI — template picker modal + history links in footer"
```

---

### Task 5: Smoke test

- [ ] **Step 1: Verify app starts**

```bash
python -c "from mbr.app import app; print('OK')"
```

- [ ] **Step 2: Run seed to create tables**

```bash
python -m mbr.seed_mbr --update
```

- [ ] **Step 3: Manual test**

1. Create a zbiornik for K7, fill analysis values, complete it
2. Open completed zbiornik → "Wystaw świadectwo" button visible
3. Click → modal with K7 templates listed
4. Click template → PDF generates, opens in new tab
5. Certificate history link appears in footer
6. Check `data/swiadectwa/2026/Chegina_K7/` for saved PDF
