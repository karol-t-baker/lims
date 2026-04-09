# Edytor wzorów świadectw — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Full CRUD editor at `/admin/wzory-cert` for managing certificate templates — products, parameters, variants with overrides, and live PDF preview.

**Architecture:** New admin page in `certs` blueprint. Backend: 6 REST endpoints in `certs/routes.py` reading/writing `cert_config.json` + reusing `PUT /api/produkty/<pid>` for metadata. Frontend: single Jinja2 template with vanilla JS, two-column layout (editor left, PDF preview right). Preview builds context directly from POST payload, bypassing `build_context()`.

**Tech Stack:** Flask, vanilla JS, HTML5 Drag & Drop, docxtpl + Gotenberg (PDF preview), existing `adm-*`/`wc-*` CSS patterns.

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `mbr/templates/admin/wzory_cert.html` | Full page: CSS + HTML + JS for editor UI |
| Modify | `mbr/certs/routes.py` | Add 7 endpoints: page route + 6 API endpoints |
| Modify | `mbr/certs/generator.py` | Add `build_preview_context()` function |
| Modify | `mbr/templates/base.html` | Add nav link for "Wzory świadectw" |
| Modify | `mbr/templates/laborant/_fast_entry_content.html` | Fix broken `/api/cert/config/parameters` calls |

---

## Task 1: Backend — Product CRUD API endpoints

**Files:**
- Modify: `mbr/certs/routes.py` (add after line 194)

- [ ] **Step 1: Add imports and helper**

At top of `mbr/certs/routes.py`, add `role_required` import. Add JSON read/write helper:

```python
from mbr.shared.decorators import role_required

# ... existing imports ...

def _read_config():
    """Read cert_config.json (fresh, no cache)."""
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return _json.load(f)

def _write_config(cfg):
    """Write cert_config.json atomically."""
    tmp = str(_CONFIG_PATH) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump(cfg, f, ensure_ascii=False, indent=2)
    import os
    os.replace(tmp, str(_CONFIG_PATH))
    # Invalidate generator cache
    from mbr.certs import generator
    generator._cached_config = None
```

- [ ] **Step 2: Add page route**

```python
@certs_bp.route("/admin/wzory-cert")
@role_required("admin")
def admin_wzory_cert():
    return render_template("admin/wzory_cert.html")
```

Add `render_template` to the Flask import at line 6 if not already there (it's already imported).

- [ ] **Step 3: Add GET /api/cert/config/products**

```python
@certs_bp.route("/api/cert/config/products")
@role_required("admin")
def api_cert_config_products():
    """List all products with summary info."""
    cfg = _read_config()
    products = []
    for key, prod in cfg.get("products", {}).items():
        products.append({
            "key": key,
            "display_name": prod.get("display_name", key),
            "params_count": len(prod.get("parameters", [])),
            "variants_count": len(prod.get("variants", [])),
        })
    return jsonify({"products": products})
```

- [ ] **Step 4: Add GET /api/cert/config/product/<key>**

```python
@certs_bp.route("/api/cert/config/product/<key>")
@role_required("admin")
def api_cert_config_product_get(key):
    """Full product data for editor."""
    cfg = _read_config()
    prod = cfg.get("products", {}).get(key)
    if not prod:
        return jsonify({"error": "Product not found"}), 404
    # Enrich with produkty DB metadata
    with db_session() as db:
        row = db.execute(
            "SELECT id, display_name, spec_number, cas_number, expiry_months, "
            "opinion_pl, opinion_en FROM produkty WHERE nazwa = ?", (key,)
        ).fetchone()
    db_meta = dict(row) if row else None
    return jsonify({"key": key, "product": prod, "db_meta": db_meta})
```

- [ ] **Step 5: Add PUT /api/cert/config/product/<key>**

```python
@certs_bp.route("/api/cert/config/product/<key>", methods=["PUT"])
@role_required("admin")
def api_cert_config_product_put(key):
    """Save product parameters + variants to cert_config.json."""
    data = request.get_json(silent=True) or {}
    cfg = _read_config()

    if key not in cfg.get("products", {}):
        return jsonify({"error": "Product not found"}), 404

    # Validate parameters
    params = data.get("parameters", [])
    seen_ids = set()
    for p in params:
        if not p.get("name_pl") or not p.get("name_en") or not p.get("requirement"):
            return jsonify({"error": f"Parameter '{p.get('id','')}': name_pl, name_en, requirement required"}), 400
        if p.get("id") in seen_ids:
            return jsonify({"error": f"Duplicate parameter id: {p['id']}"}), 400
        seen_ids.add(p.get("id"))

    # Validate variants
    variants = data.get("variants", [])
    seen_vids = set()
    for v in variants:
        if not v.get("id") or not v.get("label"):
            return jsonify({"error": "Variant id and label required"}), 400
        if v["id"] in seen_vids:
            return jsonify({"error": f"Duplicate variant id: {v['id']}"}), 400
        seen_vids.add(v["id"])
        # Validate remove_parameters reference existing base params
        overrides = v.get("overrides", {})
        for rid in overrides.get("remove_parameters", []):
            if rid not in seen_ids:
                return jsonify({"error": f"Variant '{v['id']}' removes unknown param '{rid}'"}), 400

    # Update product in config (preserve display_name etc from JSON for backwards compat)
    prod = cfg["products"][key]
    prod["parameters"] = params
    prod["variants"] = variants
    # Also sync display_name/meta from payload if provided
    for field in ("display_name", "spec_number", "cas_number", "expiry_months", "opinion_pl", "opinion_en"):
        if field in data:
            prod[field] = data[field]

    _write_config(cfg)
    return jsonify({"ok": True})
```

- [ ] **Step 6: Add POST /api/cert/config/product (create new)**

```python
@certs_bp.route("/api/cert/config/product", methods=["POST"])
@role_required("admin")
def api_cert_config_product_create():
    """Create new product."""
    data = request.get_json(silent=True) or {}
    display_name = (data.get("display_name") or "").strip()
    if not display_name:
        return jsonify({"error": "display_name required"}), 400

    key = display_name.replace(" ", "_")
    cfg = _read_config()

    if key in cfg.get("products", {}):
        return jsonify({"error": f"Product '{key}' already exists"}), 409

    new_product = {
        "display_name": display_name,
        "spec_number": data.get("spec_number", ""),
        "cas_number": data.get("cas_number", ""),
        "expiry_months": data.get("expiry_months", 12),
        "opinion_pl": data.get("opinion_pl", ""),
        "opinion_en": data.get("opinion_en", ""),
        "parameters": [],
        "variants": [{"id": "base", "label": display_name, "flags": []}],
    }

    cfg.setdefault("products", {})[key] = new_product
    _write_config(cfg)

    # Also create in produkty DB table
    with db_session() as db:
        existing = db.execute("SELECT id FROM produkty WHERE nazwa=?", (key,)).fetchone()
        if not existing:
            db.execute(
                "INSERT INTO produkty (nazwa, display_name, spec_number, cas_number, expiry_months, opinion_pl, opinion_en) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (key, display_name, data.get("spec_number", ""), data.get("cas_number", ""),
                 data.get("expiry_months", 12), data.get("opinion_pl", ""), data.get("opinion_en", "")),
            )
            db.commit()

    return jsonify({"ok": True, "key": key})
```

- [ ] **Step 7: Add DELETE /api/cert/config/product/<key>**

```python
@certs_bp.route("/api/cert/config/product/<key>", methods=["DELETE"])
@role_required("admin")
def api_cert_config_product_delete(key):
    """Delete product from cert_config.json."""
    cfg = _read_config()
    if key not in cfg.get("products", {}):
        return jsonify({"error": "Product not found"}), 404

    # Check for issued certificates
    warning = None
    with db_session() as db:
        count = db.execute(
            "SELECT COUNT(*) as c FROM swiadectwa WHERE variant_label LIKE ?",
            (f"%{cfg['products'][key].get('display_name', key)}%",),
        ).fetchone()["c"]
        if count > 0:
            warning = f"Istnieje {count} wydanych świadectw dla tego produktu. Dane archiwalne pozostają nienaruszone."

    del cfg["products"][key]
    _write_config(cfg)
    return jsonify({"ok": True, "warning": warning})
```

- [ ] **Step 8: Commit**

```bash
git add mbr/certs/routes.py
git commit -m "feat(cert-editor): add product CRUD API endpoints for cert config"
```

---

## Task 2: Backend — Preview endpoint

**Files:**
- Modify: `mbr/certs/generator.py` (add new function)
- Modify: `mbr/certs/routes.py` (add preview endpoint)

- [ ] **Step 1: Add `build_preview_context()` to generator.py**

Add after `build_context()` function (after line 402):

```python
def build_preview_context(product_json: dict, variant_id: str) -> dict:
    """Build preview context directly from editor payload — bypasses DB and config file.

    Args:
        product_json: Full product object from editor (display_name, parameters, variants, etc.)
        variant_id: Which variant to preview.

    Returns:
        Context dict ready for template rendering with test data.
    """
    cfg = load_config()  # Only for company/footer/rspo

    display_name = product_json.get("display_name", "Produkt")
    spec_number = product_json.get("spec_number", "")
    opinion_pl = product_json.get("opinion_pl", "")
    opinion_en = product_json.get("opinion_en", "")
    cas_number = product_json.get("cas_number", "")
    expiry_months = product_json.get("expiry_months", 12)

    parameters = copy.deepcopy(product_json.get("parameters", []))

    # Find variant
    variant = None
    for v in product_json.get("variants", []):
        if v["id"] == variant_id:
            variant = v
            break
    if variant is None and product_json.get("variants"):
        variant = product_json["variants"][0]
    if variant is None:
        variant = {"id": "base", "label": display_name, "flags": [], "overrides": {}}

    overrides = variant.get("overrides", {})
    flags = set(variant.get("flags", []))

    # Apply variant overrides
    if overrides.get("spec_number"):
        spec_number = overrides["spec_number"]
    if overrides.get("opinion_pl"):
        opinion_pl = overrides["opinion_pl"]
    if overrides.get("opinion_en"):
        opinion_en = overrides["opinion_en"]

    # Remove parameters
    remove_ids = set(overrides.get("remove_parameters", []))
    if remove_ids:
        parameters = [p for p in parameters if p["id"] not in remove_ids]

    # Add parameters
    add_params = overrides.get("add_parameters", [])
    if add_params:
        parameters.extend(copy.deepcopy(add_params))

    # Build rows with test data
    rows = []
    for param in parameters:
        if param.get("qualitative_result"):
            result = param["qualitative_result"]
        elif param.get("data_field"):
            # Generate example numeric value
            fmt = param.get("format", "1")
            result = _format_value(12.34, fmt)
        else:
            result = ""
        rows.append({
            "name_pl": param.get("name_pl", ""),
            "name_en": param.get("name_en", ""),
            "requirement": param.get("requirement", ""),
            "method": param.get("method", ""),
            "result": result,
        })

    # Test dates
    today = date.today()
    dt_produkcji = today.strftime("%d.%m.%Y")
    year = today.year + (today.month - 1 + expiry_months) // 12
    month = (today.month - 1 + expiry_months) % 12 + 1
    day = min(today.day, _days_in_month(year, month))
    dt_waznosci = date(year, month, day).strftime("%d.%m.%Y")

    has_rspo = "has_rspo" in flags
    rspo_number = cfg.get("rspo_number", "")
    rspo_text = rspo_number if has_rspo else ""
    certificate_number = ""
    if has_rspo and "has_certificate_number" not in flags:
        certificate_number = rspo_text
        rspo_text = ""

    return {
        "company": cfg["company"],
        "footer": cfg["footer"],
        "display_name": display_name + (" MB" if has_rspo else ""),
        "spec_number": spec_number,
        "cas_number": cas_number,
        "nr_partii": "1/2026",
        "dt_produkcji": dt_produkcji,
        "dt_waznosci": dt_waznosci,
        "dt_wystawienia": today.strftime("%d.%m.%Y"),
        "opinion_pl": opinion_pl,
        "opinion_en": opinion_en,
        "rows": rows,
        "order_number": "TEST-ORDER-001" if "has_order_number" in flags else "",
        "certificate_number": certificate_number or ("CERT-001" if "has_certificate_number" in flags else ""),
        "rspo_text": rspo_text,
        "avon_code": overrides.get("avon_code", "AVON-CODE") if "has_avon_code" in flags else "",
        "avon_name": overrides.get("avon_name", "AVON-NAME") if "has_avon_name" in flags else "",
        "wystawil": "Podgląd",
    }
```

- [ ] **Step 2: Add preview endpoint to routes.py**

```python
from mbr.certs.generator import (
    generate_certificate_pdf, get_required_fields, get_variants,
    save_certificate_data, load_config, _CONFIG_PATH,
    build_preview_context, _docxtpl_render, _gotenberg_convert,  # add these
)

# ... then add the endpoint:

@certs_bp.route("/api/cert/config/preview", methods=["POST"])
@role_required("admin")
def api_cert_config_preview():
    """Generate PDF preview from editor state (not saved data)."""
    data = request.get_json(silent=True) or {}
    product_json = data.get("product")
    variant_id = data.get("variant_id", "base")

    if not product_json:
        return jsonify({"error": "product payload required"}), 400

    try:
        ctx = build_preview_context(product_json, variant_id)
        docx_bytes = _docxtpl_render(ctx)
        pdf_bytes = _gotenberg_convert(docx_bytes)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return Response(pdf_bytes, mimetype="application/pdf")
```

- [ ] **Step 3: Commit**

```bash
git add mbr/certs/generator.py mbr/certs/routes.py
git commit -m "feat(cert-editor): add preview endpoint with direct context building"
```

---

## Task 3: Frontend — Template scaffold and product list view

**Files:**
- Create: `mbr/templates/admin/wzory_cert.html`

- [ ] **Step 1: Create base template with CSS and product list**

Create `mbr/templates/admin/wzory_cert.html`:

```html
{% extends "base.html" %}
{% block title %}Wzory świadectw{% endblock %}
{% block nav_admin %}active{% endblock %}

{% block topbar_title %}
  <span style="font-weight:700;">Wzory świadectw</span>
{% endblock %}

{% block head %}
<style>
/* ═══ wc- prefix for wzory cert ═══ */
.wc-wrap { display: flex; height: calc(100vh - 52px); overflow: hidden; }
.wc-left { flex: 0 0 55%; padding: 24px 28px; overflow-y: auto; border-right: 1px solid var(--border); }
.wc-right { flex: 1; padding: 24px; display: flex; flex-direction: column; overflow: hidden; }

/* Product list cards */
.wc-cards { display: flex; flex-direction: column; gap: 10px; }
.wc-card {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 18px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  cursor: pointer;
  transition: border-color 0.15s;
}
.wc-card:hover { border-color: var(--teal); }
.wc-card-name { font-weight: 700; font-size: 13px; flex: 1; }
.wc-card-meta { font-size: 10px; color: var(--text-dim); display: flex; gap: 12px; }
.wc-card-actions { display: flex; gap: 6px; }

/* Buttons */
.wc-btn {
  padding: 7px 16px; border: none; border-radius: 8px;
  font-size: 11px; font-weight: 600; cursor: pointer;
}
.wc-btn-primary { background: var(--teal); color: #fff; }
.wc-btn-primary:hover { opacity: 0.9; }
.wc-btn-danger { background: var(--red-bg, #fef2f2); color: var(--red, #dc2626); }
.wc-btn-danger:hover { opacity: 0.8; }
.wc-btn-secondary { background: var(--surface-alt); color: var(--text); border: 1px solid var(--border); }

/* Editor section */
.wc-editor { display: none; }
.wc-editor.active { display: block; }
.wc-field-group { margin-bottom: 16px; }
.wc-field-group label { display: block; font-size: 10px; font-weight: 700; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
.wc-input {
  width: 100%; padding: 8px 12px;
  border: 1.5px solid var(--border); border-radius: 8px;
  font-size: 12px; font-family: inherit; background: #fff;
}
.wc-input:focus { border-color: var(--teal); outline: none; }
.wc-input-sm { width: 80px; }

/* Parameters table */
.wc-params-table { width: 100%; border-collapse: collapse; font-size: 11px; margin-top: 8px; }
.wc-params-table th {
  text-align: left; padding: 8px 6px; font-size: 9px; font-weight: 700;
  color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px;
  border-bottom: 2px solid var(--border);
}
.wc-params-table td { padding: 6px; border-bottom: 1px solid var(--border-subtle); }
.wc-params-table tr:hover { background: var(--surface-alt); }
.wc-params-table input, .wc-params-table select {
  border: 1px solid transparent; background: transparent;
  padding: 4px 6px; border-radius: 4px; font-size: 11px; width: 100%; font-family: inherit;
}
.wc-params-table input:hover, .wc-params-table select:hover { border-color: var(--border); }
.wc-params-table input:focus, .wc-params-table select:focus { border-color: var(--teal); outline: none; background: var(--surface); }
.wc-drag-handle { cursor: grab; color: var(--text-dim); font-size: 14px; user-select: none; }
.wc-drag-handle:active { cursor: grabbing; }
tr.wc-dragging { opacity: 0.4; }

/* Variants */
.wc-variant {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 12px;
  overflow: hidden;
}
.wc-variant-head {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 16px;
  background: var(--surface-alt);
  cursor: pointer;
  font-size: 12px; font-weight: 600;
}
.wc-variant-head .arrow { transition: transform 0.2s; font-size: 10px; }
.wc-variant-head.open .arrow { transform: rotate(90deg); }
.wc-variant-body { padding: 16px; display: none; }
.wc-variant-body.open { display: block; }
.wc-checks { display: flex; flex-wrap: wrap; gap: 12px; margin: 8px 0; }
.wc-checks label { font-size: 11px; display: flex; align-items: center; gap: 4px; cursor: pointer; text-transform: none; font-weight: 400; color: var(--text); }
.wc-overrides { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 8px; }

/* Section headers */
.wc-section-title {
  font-size: 12px; font-weight: 700; color: var(--text);
  margin: 20px 0 8px; padding-bottom: 6px;
  border-bottom: 2px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
}

/* Preview */
.wc-preview-bar { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }
.wc-preview-bar select { flex: 1; }
.wc-preview-frame {
  flex: 1; border: 1px solid var(--border); border-radius: var(--radius);
  background: #f8f8f8;
}
.wc-preview-placeholder {
  display: flex; align-items: center; justify-content: center;
  height: 100%; color: var(--text-dim); font-size: 12px;
}

/* Back link */
.wc-back { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; color: var(--text-dim); cursor: pointer; margin-bottom: 16px; }
.wc-back:hover { color: var(--teal); }

/* Flash */
.wc-flash { padding: 10px 16px; border-radius: 8px; font-size: 12px; margin-bottom: 12px; display: none; }
.wc-flash-ok { display: block; background: var(--green-bg, #dcfce7); color: var(--green, #16a34a); }
.wc-flash-err { display: block; background: var(--red-bg, #fef2f2); color: var(--red, #dc2626); }
</style>
{% endblock %}

{% block content %}
<div class="wc-wrap">
  <!-- ═══ LEFT COLUMN ═══ -->
  <div class="wc-left" id="wc-left">
    <div id="wc-flash" class="wc-flash"></div>

    <!-- Product list view -->
    <div id="wc-list-view">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
        <span style="font-size:14px;font-weight:700;">Produkty</span>
        <button class="wc-btn wc-btn-primary" onclick="showNewProductForm()">+ Nowy produkt</button>
      </div>
      <div id="wc-product-cards" class="wc-cards"></div>
    </div>

    <!-- New product form (hidden) -->
    <div id="wc-new-form" style="display:none;">
      <div class="wc-back" onclick="hideNewProductForm()">← Powrót do listy</div>
      <div style="font-size:14px;font-weight:700;margin-bottom:16px;">Nowy produkt</div>
      <div class="wc-field-group"><label>Nazwa wyświetlana *</label><input class="wc-input" id="new-display-name"></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
        <div class="wc-field-group"><label>Nr specyfikacji</label><input class="wc-input" id="new-spec-number"></div>
        <div class="wc-field-group"><label>Nr CAS</label><input class="wc-input" id="new-cas-number"></div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">
        <div class="wc-field-group"><label>Ważność (mies.)</label><input class="wc-input" type="number" id="new-expiry" value="12"></div>
      </div>
      <div class="wc-field-group"><label>Opinia PL</label><input class="wc-input" id="new-opinion-pl"></div>
      <div class="wc-field-group"><label>Opinia EN</label><input class="wc-input" id="new-opinion-en"></div>
      <button class="wc-btn wc-btn-primary" style="margin-top:12px;" onclick="createProduct()">Utwórz produkt</button>
    </div>

    <!-- Editor view (hidden) -->
    <div id="wc-editor-view" class="wc-editor"></div>
  </div>

  <!-- ═══ RIGHT COLUMN ═══ -->
  <div class="wc-right">
    <div class="wc-preview-bar">
      <select class="wc-input" id="wc-preview-variant" style="flex:1;"></select>
      <button class="wc-btn wc-btn-secondary" onclick="refreshPreview()">Odśwież podgląd</button>
    </div>
    <div class="wc-preview-frame" id="wc-preview-frame">
      <div class="wc-preview-placeholder" id="wc-preview-placeholder">Kliknij „Odśwież" aby wygenerować podgląd</div>
      <iframe id="wc-preview-iframe" style="width:100%;height:100%;border:none;display:none;"></iframe>
    </div>
  </div>
</div>

<script>
/* ═══════════════════════════════════════════════════════════════
   Wzory Cert Editor — state & helpers
   ═══════════════════════════════════════════════════════════════ */
var _products = [];          // [{key, display_name, params_count, variants_count}]
var _currentKey = null;      // product key being edited
var _currentProduct = null;  // full product object
var _dbMeta = null;          // {id, display_name, ...} from produkty table
var _availableCodes = [];    // [{id, kod, label, skrot, typ}] from parametry_analityczne

// ── Flash messages ──
function flash(msg, ok) {
  var el = document.getElementById('wc-flash');
  el.textContent = msg;
  el.className = 'wc-flash ' + (ok ? 'wc-flash-ok' : 'wc-flash-err');
  setTimeout(function() { el.className = 'wc-flash'; }, 4000);
}

// ── Load available codes (once) ──
async function loadCodes() {
  var resp = await fetch('/api/parametry/available');
  _availableCodes = await resp.json();
}

// ═══ PRODUCT LIST ═══
async function loadProducts() {
  var resp = await fetch('/api/cert/config/products');
  var data = await resp.json();
  _products = data.products || [];
  renderProductList();
}

function renderProductList() {
  var html = '';
  _products.forEach(function(p) {
    html += '<div class="wc-card" onclick="editProduct(\'' + p.key + '\')">' +
      '<div class="wc-card-name">' + p.display_name + '</div>' +
      '<div class="wc-card-meta">' +
        '<span>' + p.params_count + ' param.</span>' +
        '<span>' + p.variants_count + ' war.</span>' +
      '</div>' +
      '<div class="wc-card-actions">' +
        '<button class="wc-btn wc-btn-danger" onclick="event.stopPropagation();deleteProduct(\'' + p.key + '\',\'' + p.display_name + '\')">Usuń</button>' +
      '</div>' +
    '</div>';
  });
  document.getElementById('wc-product-cards').innerHTML = html || '<div style="color:var(--text-dim);font-size:12px;">Brak produktów</div>';
}

// ── New product form ──
function showNewProductForm() {
  document.getElementById('wc-list-view').style.display = 'none';
  document.getElementById('wc-new-form').style.display = 'block';
}
function hideNewProductForm() {
  document.getElementById('wc-new-form').style.display = 'none';
  document.getElementById('wc-list-view').style.display = 'block';
}

async function createProduct() {
  var name = document.getElementById('new-display-name').value.trim();
  if (!name) { flash('Nazwa wymagana', false); return; }
  var resp = await fetch('/api/cert/config/product', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      display_name: name,
      spec_number: document.getElementById('new-spec-number').value.trim(),
      cas_number: document.getElementById('new-cas-number').value.trim(),
      expiry_months: parseInt(document.getElementById('new-expiry').value) || 12,
      opinion_pl: document.getElementById('new-opinion-pl').value.trim(),
      opinion_en: document.getElementById('new-opinion-en').value.trim(),
    })
  });
  var data = await resp.json();
  if (!resp.ok) { flash(data.error || 'Błąd', false); return; }
  hideNewProductForm();
  // Clear inputs
  ['new-display-name','new-spec-number','new-cas-number','new-opinion-pl','new-opinion-en'].forEach(function(id) {
    document.getElementById(id).value = '';
  });
  document.getElementById('new-expiry').value = '12';
  loadProducts();
  flash('Produkt utworzony', true);
}

async function deleteProduct(key, name) {
  if (!confirm('Usunąć produkt "' + name + '"? Dane archiwalne świadectw pozostaną.')) return;
  var resp = await fetch('/api/cert/config/product/' + encodeURIComponent(key), {method: 'DELETE'});
  var data = await resp.json();
  if (data.warning) alert(data.warning);
  loadProducts();
  if (_currentKey === key) backToList();
}

// ═══ INITIALIZATION ═══
loadCodes();
loadProducts();
</script>
{% endblock %}
```

- [ ] **Step 2: Verify product list loads**

Start the app, navigate to `/admin/wzory-cert`. Verify:
- Product cards render with display_name, param count, variant count
- "Nowy produkt" form works
- Delete with confirmation works

- [ ] **Step 3: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(cert-editor): product list view with create/delete"
```

---

## Task 4: Frontend — Product editor (header + parameters table)

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html` (add JS functions inside `<script>`)

- [ ] **Step 1: Add editProduct, backToList, and header rendering**

Add to the `<script>` section:

```javascript
// ═══ EDITOR VIEW ═══
async function editProduct(key) {
  var resp = await fetch('/api/cert/config/product/' + encodeURIComponent(key));
  var data = await resp.json();
  if (!resp.ok) { flash(data.error || 'Błąd', false); return; }

  _currentKey = key;
  _currentProduct = data.product;
  _dbMeta = data.db_meta;

  document.getElementById('wc-list-view').style.display = 'none';
  document.getElementById('wc-new-form').style.display = 'none';
  var editor = document.getElementById('wc-editor-view');
  editor.className = 'wc-editor active';
  renderEditor();
  updatePreviewVariantSelect();
}

function backToList() {
  _currentKey = null;
  _currentProduct = null;
  _dbMeta = null;
  document.getElementById('wc-editor-view').className = 'wc-editor';
  document.getElementById('wc-list-view').style.display = 'block';
  // Reset preview
  document.getElementById('wc-preview-iframe').style.display = 'none';
  document.getElementById('wc-preview-placeholder').style.display = 'flex';
  document.getElementById('wc-preview-variant').innerHTML = '';
  loadProducts();
}

function renderEditor() {
  var p = _currentProduct;
  var meta = _dbMeta || {};

  var html = '<div class="wc-back" onclick="backToList()">← Powrót do listy</div>';

  // ── Header fields ──
  html += '<div class="wc-section-title">Nagłówek produktu</div>';
  html += '<div class="wc-field-group"><label>Nazwa wyświetlana *</label>' +
    '<input class="wc-input" id="ed-display-name" value="' + _esc(meta.display_name || p.display_name || '') + '"></div>';

  html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">' +
    '<div class="wc-field-group"><label>Nr specyfikacji</label><input class="wc-input" id="ed-spec-number" value="' + _esc(meta.spec_number || p.spec_number || '') + '"></div>' +
    '<div class="wc-field-group"><label>Nr CAS</label><input class="wc-input" id="ed-cas-number" value="' + _esc(meta.cas_number || p.cas_number || '') + '"></div>' +
  '</div>';

  html += '<div style="display:grid;grid-template-columns:1fr 2fr 2fr;gap:8px;">' +
    '<div class="wc-field-group"><label>Ważność (mies.)</label><input class="wc-input" type="number" id="ed-expiry" value="' + (meta.expiry_months || p.expiry_months || 12) + '"></div>' +
    '<div class="wc-field-group"><label>Opinia PL</label><input class="wc-input" id="ed-opinion-pl" value="' + _esc(meta.opinion_pl || p.opinion_pl || '') + '"></div>' +
    '<div class="wc-field-group"><label>Opinia EN</label><input class="wc-input" id="ed-opinion-en" value="' + _esc(meta.opinion_en || p.opinion_en || '') + '"></div>' +
  '</div>';

  // ── Parameters table ──
  html += '<div class="wc-section-title">Parametry <button class="wc-btn wc-btn-secondary" onclick="addParameter()">+ Dodaj parametr</button></div>';
  html += renderParamsTable(p.parameters || []);

  // ── Variants ──
  html += '<div class="wc-section-title">Warianty <button class="wc-btn wc-btn-secondary" onclick="addVariant()">+ Dodaj wariant</button></div>';
  (p.variants || []).forEach(function(v, vi) {
    html += renderVariant(v, vi);
  });

  // ── Save button ──
  html += '<div style="margin-top:24px;display:flex;gap:8px;">' +
    '<button class="wc-btn wc-btn-primary" style="padding:10px 32px;font-size:13px;" onclick="saveProduct()">Zapisz</button>' +
    '<button class="wc-btn wc-btn-secondary" onclick="backToList()">Anuluj</button>' +
  '</div>';

  document.getElementById('wc-editor-view').innerHTML = html;
  initDragAndDrop();
}

function _esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _codeOptions(current) {
  var html = '<option value="">(jakościowy)</option>';
  _availableCodes.forEach(function(c) {
    var sel = c.kod === current ? ' selected' : '';
    html += '<option value="' + c.kod + '"' + sel + '>' + c.kod + ' — ' + _esc(c.label) + '</option>';
  });
  return html;
}

function _formatOptions(current) {
  var vals = ['0','1','2','3'];
  var html = '';
  vals.forEach(function(v) {
    html += '<option value="' + v + '"' + (v === (current||'1') ? ' selected' : '') + '>' + v + ' m.p.</option>';
  });
  return html;
}
```

- [ ] **Step 2: Add parameters table rendering**

```javascript
function renderParamsTable(params) {
  var html = '<table class="wc-params-table" id="wc-params-table"><thead><tr>' +
    '<th style="width:28px;"></th>' +
    '<th>ID</th><th>Nazwa PL</th><th>Nazwa EN</th><th>Wymaganie</th>' +
    '<th>Metoda</th><th>Kod danych</th><th>Format</th><th>Wynik jakościowy</th><th style="width:30px;"></th>' +
  '</tr></thead><tbody id="wc-params-body">';

  params.forEach(function(p, i) {
    html += '<tr draggable="true" data-idx="' + i + '">' +
      '<td class="wc-drag-handle">⠿</td>' +
      '<td><input data-field="id" value="' + _esc(p.id || '') + '" style="font-family:var(--mono);font-size:10px;width:90px;" readonly tabindex="-1"></td>' +
      '<td><input data-field="name_pl" value="' + _esc(p.name_pl || '') + '"></td>' +
      '<td><input data-field="name_en" value="' + _esc(p.name_en || '') + '" onchange="autoId(this)"></td>' +
      '<td><input data-field="requirement" value="' + _esc(p.requirement || '') + '"></td>' +
      '<td><input data-field="method" value="' + _esc(p.method || '') + '" style="width:70px;"></td>' +
      '<td><select data-field="data_field">' + _codeOptions(p.data_field || '') + '</select></td>' +
      '<td><select data-field="format" style="width:60px;">' + _formatOptions(p.format) + '</select></td>' +
      '<td><input data-field="qualitative_result" value="' + _esc(p.qualitative_result || '') + '"></td>' +
      '<td><button class="wc-btn wc-btn-danger" style="padding:2px 8px;font-size:10px;" onclick="removeParam(this)">✕</button></td>' +
    '</tr>';
  });

  html += '</tbody></table>';
  return html;
}

function autoId(input) {
  // Auto-generate id from name_en
  var tr = input.closest('tr');
  var idInput = tr.querySelector('[data-field="id"]');
  if (idInput.value) return; // Don't overwrite manual ids
  var slug = input.value.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/(^_|_$)/g, '');
  // Check uniqueness
  var existing = new Set();
  document.querySelectorAll('#wc-params-body [data-field="id"]').forEach(function(el) {
    if (el !== idInput) existing.add(el.value);
  });
  var base = slug;
  var n = 2;
  while (existing.has(slug)) { slug = base + '_' + n; n++; }
  idInput.value = slug;
}

function addParameter() {
  var tbody = document.getElementById('wc-params-body');
  var idx = tbody.children.length;
  var tr = document.createElement('tr');
  tr.draggable = true;
  tr.dataset.idx = idx;
  tr.innerHTML =
    '<td class="wc-drag-handle">⠿</td>' +
    '<td><input data-field="id" value="" style="font-family:var(--mono);font-size:10px;width:90px;" readonly tabindex="-1"></td>' +
    '<td><input data-field="name_pl" value=""></td>' +
    '<td><input data-field="name_en" value="" onchange="autoId(this)"></td>' +
    '<td><input data-field="requirement" value=""></td>' +
    '<td><input data-field="method" value="" style="width:70px;"></td>' +
    '<td><select data-field="data_field">' + _codeOptions('') + '</select></td>' +
    '<td><select data-field="format" style="width:60px;">' + _formatOptions('1') + '</select></td>' +
    '<td><input data-field="qualitative_result" value=""></td>' +
    '<td><button class="wc-btn wc-btn-danger" style="padding:2px 8px;font-size:10px;" onclick="removeParam(this)">✕</button></td>';
  tbody.appendChild(tr);
  initDragAndDrop();
  tr.querySelector('[data-field="name_pl"]').focus();
}

function removeParam(btn) {
  btn.closest('tr').remove();
}
```

- [ ] **Step 3: Add drag-and-drop for parameter reordering**

```javascript
// ═══ DRAG & DROP ═══
var _dragSrcRow = null;

function initDragAndDrop() {
  var tbody = document.getElementById('wc-params-body');
  if (!tbody) return;
  Array.from(tbody.children).forEach(function(tr) {
    tr.addEventListener('dragstart', handleDragStart);
    tr.addEventListener('dragover', handleDragOver);
    tr.addEventListener('drop', handleDrop);
    tr.addEventListener('dragend', handleDragEnd);
  });
}

function handleDragStart(e) {
  _dragSrcRow = this;
  this.classList.add('wc-dragging');
  e.dataTransfer.effectAllowed = 'move';
}

function handleDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  var tbody = document.getElementById('wc-params-body');
  var rows = Array.from(tbody.children);
  var afterEl = null;
  var y = e.clientY;
  rows.forEach(function(row) {
    var box = row.getBoundingClientRect();
    if (y > box.top + box.height / 2) afterEl = row;
  });
  if (afterEl) {
    tbody.insertBefore(_dragSrcRow, afterEl.nextSibling);
  } else {
    tbody.insertBefore(_dragSrcRow, tbody.firstChild);
  }
}

function handleDrop(e) {
  e.preventDefault();
}

function handleDragEnd() {
  this.classList.remove('wc-dragging');
  _dragSrcRow = null;
}
```

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(cert-editor): product editor with parameters table and drag-to-reorder"
```

---

## Task 5: Frontend — Variants editor

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html` (add JS functions)

- [ ] **Step 1: Add variant rendering**

```javascript
// ═══ VARIANTS ═══
function renderVariant(v, vi) {
  var overrides = v.overrides || {};
  var flags = v.flags || [];
  var hasAvonCode = flags.indexOf('has_avon_code') >= 0;
  var hasAvonName = flags.indexOf('has_avon_name') >= 0;

  var html = '<div class="wc-variant" data-vi="' + vi + '">';

  // Header (accordion toggle)
  html += '<div class="wc-variant-head" onclick="toggleVariant(this)">' +
    '<span class="arrow">▶</span> ' +
    '<span>' + _esc(v.label || v.id) + '</span>' +
    '<span style="margin-left:auto;font-size:10px;color:var(--text-dim);">' + v.id + '</span>' +
    (vi > 0 ? '<button class="wc-btn wc-btn-danger" style="padding:2px 8px;font-size:10px;margin-left:8px;" onclick="event.stopPropagation();removeVariant(' + vi + ')">Usuń</button>' : '') +
  '</div>';

  // Body
  html += '<div class="wc-variant-body" data-vi="' + vi + '">';

  // ID + Label
  html += '<div style="display:grid;grid-template-columns:120px 1fr;gap:8px;margin-bottom:12px;">' +
    '<div class="wc-field-group"><label>ID</label><input class="wc-input" data-vfield="id" value="' + _esc(v.id) + '"' + (vi === 0 ? ' readonly' : '') + '></div>' +
    '<div class="wc-field-group"><label>Label</label><input class="wc-input" data-vfield="label" value="' + _esc(v.label) + '"></div>' +
  '</div>';

  // Flags
  html += '<div class="wc-field-group"><label>Flagi</label><div class="wc-checks">';
  ['has_rspo','has_order_number','has_certificate_number','has_avon_code','has_avon_name'].forEach(function(f) {
    var checked = flags.indexOf(f) >= 0 ? ' checked' : '';
    html += '<label><input type="checkbox" data-flag="' + f + '" data-vi="' + vi + '"' + checked +
      ' onchange="onFlagChange(this)">' + f.replace('has_','') + '</label>';
  });
  html += '</div></div>';

  // Avon override fields (conditionally visible)
  html += '<div class="wc-avon-fields" data-vi="' + vi + '" style="display:' + (hasAvonCode || hasAvonName ? 'grid' : 'none') + ';grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px;">' +
    '<div class="wc-field-group" style="display:' + (hasAvonCode ? 'block' : 'none') + ';" data-avon-code-wrap="' + vi + '"><label>Avon code</label><input class="wc-input" data-voverride="avon_code" value="' + _esc(overrides.avon_code || '') + '"></div>' +
    '<div class="wc-field-group" style="display:' + (hasAvonName ? 'block' : 'none') + ';" data-avon-name-wrap="' + vi + '"><label>Avon name</label><input class="wc-input" data-voverride="avon_name" value="' + _esc(overrides.avon_name || '') + '"></div>' +
  '</div>';

  // Overrides
  html += '<div class="wc-field-group"><label>Overrides (puste = dziedzicz)</label>' +
    '<div class="wc-overrides">' +
      '<div><label style="font-size:10px;">spec_number</label><input class="wc-input" data-voverride="spec_number" value="' + _esc(overrides.spec_number || '') + '"></div>' +
      '<div><label style="font-size:10px;">opinion_pl</label><input class="wc-input" data-voverride="opinion_pl" value="' + _esc(overrides.opinion_pl || '') + '"></div>' +
      '<div><label style="font-size:10px;">opinion_en</label><input class="wc-input" data-voverride="opinion_en" value="' + _esc(overrides.opinion_en || '') + '"></div>' +
    '</div></div>';

  // Remove parameters (checkboxes from base params)
  var baseParams = _currentProduct.parameters || [];
  var removeSet = new Set(overrides.remove_parameters || []);
  html += '<div class="wc-field-group"><label>Usuń parametry z tego wariantu</label><div class="wc-checks">';
  baseParams.forEach(function(bp) {
    var checked = removeSet.has(bp.id) ? ' checked' : '';
    html += '<label><input type="checkbox" data-remove-param="' + bp.id + '"' + checked + '>' + _esc(bp.name_pl || bp.id) + '</label>';
  });
  html += '</div></div>';

  // Add parameters (variant-specific)
  var addParams = overrides.add_parameters || [];
  html += '<div class="wc-field-group"><label>Dodatkowe parametry (tylko ten wariant)' +
    ' <button class="wc-btn wc-btn-secondary" style="font-size:9px;padding:2px 8px;" onclick="addVariantParam(' + vi + ')">+</button></label>';
  html += '<div id="wc-add-params-' + vi + '">';
  addParams.forEach(function(ap, api) {
    html += renderVariantAddParam(vi, api, ap);
  });
  html += '</div></div>';

  html += '</div>'; // variant-body
  html += '</div>'; // variant
  return html;
}

function renderVariantAddParam(vi, api, ap) {
  return '<div class="wc-variant-add-param" data-vi="' + vi + '" data-api="' + api + '" style="display:grid;grid-template-columns:1fr 1fr 1fr 80px 70px 30px;gap:4px;margin-bottom:4px;font-size:10px;">' +
    '<input class="wc-input" data-ap="name_pl" value="' + _esc(ap.name_pl || '') + '" placeholder="Nazwa PL">' +
    '<input class="wc-input" data-ap="name_en" value="' + _esc(ap.name_en || '') + '" placeholder="Nazwa EN">' +
    '<input class="wc-input" data-ap="requirement" value="' + _esc(ap.requirement || '') + '" placeholder="Wymaganie">' +
    '<input class="wc-input" data-ap="method" value="' + _esc(ap.method || '') + '" placeholder="Metoda">' +
    '<select class="wc-input" data-ap="data_field">' + _codeOptions(ap.data_field || '') + '</select>' +
    '<button class="wc-btn wc-btn-danger" style="padding:2px 6px;font-size:9px;" onclick="this.parentElement.remove()">✕</button>' +
  '</div>';
}

function toggleVariant(head) {
  head.classList.toggle('open');
  var body = head.nextElementSibling;
  body.classList.toggle('open');
}

function onFlagChange(cb) {
  var vi = cb.dataset.vi;
  var flag = cb.dataset.flag;
  // Toggle avon field visibility
  if (flag === 'has_avon_code') {
    var wrap = document.querySelector('[data-avon-code-wrap="' + vi + '"]');
    if (wrap) wrap.style.display = cb.checked ? 'block' : 'none';
    var container = document.querySelector('.wc-avon-fields[data-vi="' + vi + '"]');
    if (container) {
      var anyAvon = cb.checked || document.querySelector('[data-flag="has_avon_name"][data-vi="' + vi + '"]').checked;
      container.style.display = anyAvon ? 'grid' : 'none';
    }
  }
  if (flag === 'has_avon_name') {
    var wrap = document.querySelector('[data-avon-name-wrap="' + vi + '"]');
    if (wrap) wrap.style.display = cb.checked ? 'block' : 'none';
    var container = document.querySelector('.wc-avon-fields[data-vi="' + vi + '"]');
    if (container) {
      var anyAvon = cb.checked || document.querySelector('[data-flag="has_avon_code"][data-vi="' + vi + '"]').checked;
      container.style.display = anyAvon ? 'grid' : 'none';
    }
  }
}

function addVariant() {
  var variants = _currentProduct.variants || [];
  var newId = 'nowy_' + (variants.length + 1);
  variants.push({id: newId, label: 'Nowy wariant', flags: [], overrides: {}});
  _currentProduct.variants = variants;
  renderEditor();
}

function removeVariant(vi) {
  if (!confirm('Usunąć wariant?')) return;
  _currentProduct.variants.splice(vi, 1);
  renderEditor();
}

function addVariantParam(vi) {
  var container = document.getElementById('wc-add-params-' + vi);
  var api = container.children.length;
  var div = document.createElement('div');
  div.innerHTML = renderVariantAddParam(vi, api, {});
  container.appendChild(div.firstElementChild);
}
```

- [ ] **Step 2: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(cert-editor): variant editor with flags, overrides, and add/remove params"
```

---

## Task 6: Frontend — Save and preview

**Files:**
- Modify: `mbr/templates/admin/wzory_cert.html` (add JS functions)

- [ ] **Step 1: Add collectEditorState() to gather all form data**

```javascript
// ═══ COLLECT STATE ═══
function collectEditorState() {
  // Header
  var display_name = document.getElementById('ed-display-name').value.trim();
  var spec_number = document.getElementById('ed-spec-number').value.trim();
  var cas_number = document.getElementById('ed-cas-number').value.trim();
  var expiry_months = parseInt(document.getElementById('ed-expiry').value) || 12;
  var opinion_pl = document.getElementById('ed-opinion-pl').value.trim();
  var opinion_en = document.getElementById('ed-opinion-en').value.trim();

  // Parameters from table
  var parameters = [];
  var rows = document.querySelectorAll('#wc-params-body tr');
  rows.forEach(function(tr) {
    var p = {};
    tr.querySelectorAll('[data-field]').forEach(function(el) {
      p[el.dataset.field] = el.value;
    });
    // Normalize: null instead of empty for data_field
    if (!p.data_field) p.data_field = null;
    if (!p.qualitative_result) delete p.qualitative_result;
    parameters.push(p);
  });

  // Variants
  var variants = [];
  document.querySelectorAll('.wc-variant').forEach(function(vEl) {
    var vi = vEl.dataset.vi;
    var body = vEl.querySelector('.wc-variant-body');

    var v = {
      id: (body.querySelector('[data-vfield="id"]') || {}).value || '',
      label: (body.querySelector('[data-vfield="label"]') || {}).value || '',
      flags: [],
      overrides: {},
    };

    // Flags
    body.querySelectorAll('[data-flag]').forEach(function(cb) {
      if (cb.checked) v.flags.push(cb.dataset.flag);
    });

    // Overrides
    body.querySelectorAll('[data-voverride]').forEach(function(el) {
      var val = el.value.trim();
      if (val) v.overrides[el.dataset.voverride] = val;
    });

    // Remove parameters
    var removeParams = [];
    body.querySelectorAll('[data-remove-param]').forEach(function(cb) {
      if (cb.checked) removeParams.push(cb.dataset.removeParam);
    });
    if (removeParams.length) v.overrides.remove_parameters = removeParams;

    // Add parameters
    var addParams = [];
    body.querySelectorAll('.wc-variant-add-param').forEach(function(apEl) {
      var ap = {};
      apEl.querySelectorAll('[data-ap]').forEach(function(el) {
        ap[el.dataset.ap] = el.value;
      });
      if (ap.name_pl || ap.name_en) {
        // Auto-generate id
        ap.id = (ap.name_en || ap.name_pl || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/(^_|_$)/g, '');
        if (!ap.data_field) ap.data_field = null;
        ap.format = ap.format || '1';
        addParams.push(ap);
      }
    });
    if (addParams.length) v.overrides.add_parameters = addParams;

    variants.push(v);
  });

  return {
    display_name: display_name,
    spec_number: spec_number,
    cas_number: cas_number,
    expiry_months: expiry_months,
    opinion_pl: opinion_pl,
    opinion_en: opinion_en,
    parameters: parameters,
    variants: variants,
  };
}
```

- [ ] **Step 2: Add saveProduct() with dual-phase save**

```javascript
// ═══ SAVE ═══
async function saveProduct() {
  var state = collectEditorState();
  if (!state.display_name) { flash('Nazwa wymagana', false); return; }

  // Phase 1: Save metadata to produkty DB (if db_meta exists)
  if (_dbMeta && _dbMeta.id) {
    var metaResp = await fetch('/api/produkty/' + _dbMeta.id, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        display_name: state.display_name,
        spec_number: state.spec_number,
        cas_number: state.cas_number,
        expiry_months: state.expiry_months,
        opinion_pl: state.opinion_pl,
        opinion_en: state.opinion_en,
      })
    });
    if (!metaResp.ok) {
      var err = await metaResp.json();
      flash('Błąd zapisu metadanych: ' + (err.error || 'nieznany'), false);
      return;
    }
  }

  // Phase 2: Save parameters + variants to cert_config.json
  var resp = await fetch('/api/cert/config/product/' + encodeURIComponent(_currentKey), {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(state)
  });
  var data = await resp.json();
  if (!resp.ok) { flash(data.error || 'Błąd zapisu', false); return; }

  flash('Zapisano', true);
  // Refresh product data
  editProduct(_currentKey);
}
```

- [ ] **Step 3: Add preview functionality**

```javascript
// ═══ PREVIEW ═══
function updatePreviewVariantSelect() {
  var sel = document.getElementById('wc-preview-variant');
  sel.innerHTML = '';
  if (!_currentProduct) return;
  (_currentProduct.variants || []).forEach(function(v) {
    var opt = document.createElement('option');
    opt.value = v.id;
    opt.textContent = v.label;
    sel.appendChild(opt);
  });
}

async function refreshPreview() {
  if (!_currentKey) return;

  var state = collectEditorState();
  var variantId = document.getElementById('wc-preview-variant').value || 'base';

  var iframe = document.getElementById('wc-preview-iframe');
  var placeholder = document.getElementById('wc-preview-placeholder');

  placeholder.textContent = 'Generowanie podglądu...';
  placeholder.style.display = 'flex';
  iframe.style.display = 'none';

  try {
    var resp = await fetch('/api/cert/config/preview', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({product: state, variant_id: variantId})
    });

    if (!resp.ok) {
      var err = await resp.json();
      placeholder.textContent = 'Błąd: ' + (err.error || resp.statusText);
      return;
    }

    var blob = await resp.blob();
    var url = URL.createObjectURL(blob);

    // Revoke previous blob URL
    if (iframe.dataset.blobUrl) URL.revokeObjectURL(iframe.dataset.blobUrl);
    iframe.dataset.blobUrl = url;
    iframe.src = url;
    iframe.style.display = 'block';
    placeholder.style.display = 'none';
  } catch (e) {
    placeholder.textContent = 'Błąd połączenia: ' + e.message;
  }
}
```

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/admin/wzory_cert.html
git commit -m "feat(cert-editor): save (dual-phase) and PDF preview functionality"
```

---

## Task 7: Navigation link + fast_entry bugfix

**Files:**
- Modify: `mbr/templates/base.html` (~line 31, after zbiorniki nav link)
- Modify: `mbr/templates/laborant/_fast_entry_content.html` (~lines 3616, 3720)

- [ ] **Step 1: Add nav link in base.html**

After the Zbiorniki nav link (line 31), add:

```html
  <a class="rail-btn {% block nav_wzory_cert %}{% endblock %}" href="{{ url_for('certs.admin_wzory_cert') }}" title="Wzory świadectw"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg><span class="rail-label">Świadectwa</span></a>
```

- [ ] **Step 2: Fix broken endpoint in _fast_entry_content.html**

Find the GET call (~line 3616):
```javascript
// OLD:
fetch('/api/cert/config/parameters?produkt=' + encodeURIComponent(window._batchProdukt))
```
Replace with:
```javascript
// NEW:
fetch('/api/parametry/cert/' + encodeURIComponent(window._batchProdukt))
```

Find the PUT call (~line 3720):
```javascript
// OLD:
fetch('/api/cert/config/parameters', {
    method: 'PUT',
```

This PUT endpoint was for saving cert parameter bindings. The new equivalent uses individual POST/PUT/DELETE per binding via `/api/parametry/cert/*`. Since the full cert mapping editor UI is being replaced by the new wzory_cert page, the simplest fix is to redirect users:

Replace the `saveCertMappings()` function body with a message that the old editor has moved:
```javascript
// Replace the save function to point to new editor:
flash('Edytor parametrów świadectw przeniesiony do Admin → Wzory świadectw', false);
return;
```

Or if the cert mapping editor in _fast_entry is still needed as a quick-edit, adapt the PUT to use the new per-binding endpoints. Depends on whether this old editor should remain functional — **ask user during implementation**.

- [ ] **Step 3: Update wzory_cert.html nav block**

In `wzory_cert.html`, change the nav block to mark this page as active:
```html
{% block nav_wzory_cert %}active{% endblock %}
```
(Replace `{% block nav_admin %}active{% endblock %}`)

- [ ] **Step 4: Commit**

```bash
git add mbr/templates/base.html mbr/templates/admin/wzory_cert.html mbr/templates/laborant/_fast_entry_content.html
git commit -m "feat(cert-editor): add nav link, fix broken cert config endpoint calls"
```

---

## Task 8: Manual integration test

- [ ] **Step 1: Test product list**

1. Start app: `python -m mbr`
2. Login as admin
3. Navigate to `/admin/wzory-cert`
4. Verify all products from cert_config.json appear as cards
5. Verify param count and variant count are correct

- [ ] **Step 2: Test product editing**

1. Click on "Chegina K40GLOL" card
2. Verify header fields populated from DB metadata
3. Verify 9 parameters in table
4. Verify 4 variants (base, loreal, loreal_belgia, loreal_wlochy, kosmepol)
5. Open "loreal" variant — verify `has_rspo` checked, `remove_parameters` has dry_matter + h2o checked
6. Drag parameter "Barwa" to different position, verify reorder works

- [ ] **Step 3: Test save**

1. Change spec_number to "P833-TEST"
2. Click "Zapisz"
3. Verify flash "Zapisano"
4. Check DB: `SELECT spec_number FROM produkty WHERE nazwa='Chegina_K40GLOL'` → "P833-TEST"
5. Check cert_config.json has updated spec_number
6. Revert the test change

- [ ] **Step 4: Test PDF preview**

1. Select "Chegina K40GLOL — Loreal MB" in preview variant dropdown
2. Click "Odśwież podgląd"
3. Verify PDF renders in iframe (requires Gotenberg running at localhost:3000)
4. Verify test data appears (nr_partii: 1/2026, numeric values: 12,34)
5. Verify dry_matter and h2o NOT in certificate (removed by variant)

- [ ] **Step 5: Test create/delete**

1. Click "Nowy produkt" → enter "Test Product" → Utwórz
2. Verify card appears in list
3. Click delete on "Test Product" → confirm → verify removed

- [ ] **Step 6: Test variant with avon fields**

1. Edit a product, add variant with `has_avon_code` flag
2. Verify avon_code input appears
3. Enter value, save, reload — verify persisted

- [ ] **Step 7: Commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix(cert-editor): integration test fixes"
```
