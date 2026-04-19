# Zbiorniki do szarży — dodawanie w trakcie

**Data:** 2026-04-18
**Status:** spec

## Cel

Obecnie zbiorniki przypisuje się do szarży tylko w jednym z dwóch momentów:
1. Przy tworzeniu (`POST /laborant/szarze/new` — pole `nr_zbiornika`, pojedynczy string, luźna metadana)
2. Przy zakończeniu (pump modal → `complete_ebr` zapisuje do `zbiornik_szarze`)

Dodać możliwość przypisania/usunięcia zbiornika **w dowolnym momencie trwania szarży**. Działa tylko dla `typ='szarza'`.

## Decyzje (brainstorming 2026-04-18)

| Pytanie | Decyzja |
|---|---|
| Gdzie w UI | Inline sekcja w widoku szarży (zawsze widoczna) |
| UI pickera przy "+ Dodaj" | Mini-modal z multi-select pigułkami (jak pump modal) |
| Konflikt (zbiornik na innej otwartej szarży) | Ignoruj — swobodny wybór, brak warningów |
| Remove mid-batch | Tak, laborant może odpinać (audit trail łapie) |
| Zakres typów | Tylko `typ='szarza'`. `zbiornik` i `platkowanie` bez zmian. |
| Masa (`masa_kg`) | Nie podaje się mid-batch. Zostaje NULL. Masa rozdysponowywana dopiero w pump modalu przy zakończeniu. |
| Integracja z pump modalem | Bez zmian — pump modal preloaduje istniejące linki (już to robi przez `GET /api/zbiornik-szarze/<ebr_id>`). |

## Architektura

### Backend — bez zmian

Endpointy już istnieją:
- `GET /api/zbiornik-szarze/<ebr_id>` — lista zbiorników przypisanych do szarży
- `POST /api/zbiornik-szarze` — link `{ebr_id, zbiornik_id, masa_kg?}` (uwaga: w mini-modal `masa_kg` pomijamy → NULL)
- `DELETE /api/zbiornik-szarze/<id>` — unlink po `zbiornik_szarze.id`
- `GET /api/zbiorniki?kod_produktu=<X>&aktywny=1` — lista dostępnych zbiorników filtrowana po produkcie

Role: `@role_required("lab", "kj", "cert", "technolog", "admin")` (już enforce'owane).

### Frontend — nowa sekcja w `_fast_entry_content.html`

**Umiejscowienie:** w górnej części widoku szczegółu szarży, pod `.cv-hero` (hero z params), przed pierwszym etapem. Tylko dla `typ='szarza'` (gate w Jinja: `{% if batch.typ == 'szarza' %}`).

**Markup (szkic):**

```html
<div class="zb-assign-section" id="zb-assign-section" data-ebr-id="{{ batch.ebr_id }}" data-kod-produktu="{{ batch.kod_produktu }}">
  <div class="zb-assign-label">Zbiorniki</div>
  <div class="zb-assign-pills" id="zb-assign-pills">
    <!-- Populated by JS: pills with × for unlink -->
  </div>
  <button class="zb-assign-add" onclick="openZbAssignModal()">+ Dodaj zbiornik</button>
</div>
```

**Stan pigułki (assigned tank):**
```html
<span class="zb-pill" data-link-id="123">
  M16 · 2000 kg
  <button class="zb-pill-remove" onclick="unlinkZbiornik(123)" title="Odepnij">×</button>
</span>
```

**Mini-modal picker** (reużyć wzór z pump modala, stripped down):
```html
<div class="pal-overlay" id="zb-assign-modal" style="display:none;">
  <div class="zb-assign-modal-body">
    <div class="zb-assign-modal-head">
      <span>Wybierz zbiorniki</span>
      <button onclick="closeZbAssignModal()">×</button>
    </div>
    <div class="zb-assign-modal-grid" id="zb-assign-grid">
      <!-- Populated by JS: tank pills (kod_produktu-filtered), toggle selection -->
    </div>
    <div class="zb-assign-modal-footer">
      <button onclick="confirmZbAssign()">Dodaj wybrane</button>
    </div>
  </div>
</div>
```

**JS functions (nowe w fast_entry_content.html):**

```javascript
var _zbAssignSelected = new Set();  // zbiornik_id currently picked in modal

async function loadZbAssignedPills() {
  var section = document.getElementById('zb-assign-section');
  if (!section) return;
  var ebrId = section.dataset.ebrId;
  var resp = await fetch('/api/zbiornik-szarze/' + ebrId);
  var data = await resp.json();  // [{id, zbiornik_id, nr_zbiornika, masa_kg, ...}]
  var container = document.getElementById('zb-assign-pills');
  if (data.length === 0) {
    container.innerHTML = '<span class="zb-assign-empty">(brak)</span>';
  } else {
    container.innerHTML = data.map(function(d) {
      var mass = d.masa_kg ? ' · ' + d.masa_kg + ' kg' : '';
      return '<span class="zb-pill" data-link-id="' + d.id + '">' +
        esc(d.nr_zbiornika) + mass +
        ' <button class="zb-pill-remove" onclick="unlinkZbiornik(' + d.id + ')" title="Odepnij">×</button>' +
      '</span>';
    }).join('');
  }
}

async function openZbAssignModal() {
  var section = document.getElementById('zb-assign-section');
  var kod = section.dataset.kodProduktu;
  var resp = await fetch('/api/zbiorniki?kod_produktu=' + encodeURIComponent(kod) + '&aktywny=1');
  var tanks = await resp.json();
  // Exclude tanks already assigned
  var assignedResp = await fetch('/api/zbiornik-szarze/' + section.dataset.ebrId);
  var assigned = await assignedResp.json();
  var assignedIds = new Set(assigned.map(function(a){ return a.zbiornik_id; }));
  var available = tanks.filter(function(t){ return !assignedIds.has(t.id); });

  _zbAssignSelected.clear();
  var grid = document.getElementById('zb-assign-grid');
  grid.innerHTML = available.map(function(t) {
    return '<button type="button" class="zb-assign-tile" data-zid="' + t.id + '" onclick="toggleZbAssign(' + t.id + ', this)">' +
      '<div class="zb-assign-tile-nr">' + esc(t.nr_zbiornika) + '</div>' +
      '<div class="zb-assign-tile-cap">' + (t.max_pojemnosc || '—') + ' kg</div>' +
    '</button>';
  }).join('');
  document.getElementById('zb-assign-modal').style.display = 'flex';
}

function toggleZbAssign(zid, btn) {
  if (_zbAssignSelected.has(zid)) { _zbAssignSelected.delete(zid); btn.classList.remove('selected'); }
  else { _zbAssignSelected.add(zid); btn.classList.add('selected'); }
}

async function confirmZbAssign() {
  var section = document.getElementById('zb-assign-section');
  var ebrId = section.dataset.ebrId;
  var promises = [];
  _zbAssignSelected.forEach(function(zid) {
    promises.push(fetch('/api/zbiornik-szarze', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ebr_id: parseInt(ebrId), zbiornik_id: zid}),  // masa_kg omitted → NULL
    }));
  });
  await Promise.all(promises);
  closeZbAssignModal();
  await loadZbAssignedPills();
}

async function unlinkZbiornik(linkId) {
  if (!confirm('Odepnąć zbiornik?')) return;
  await fetch('/api/zbiornik-szarze/' + linkId, {method: 'DELETE'});
  await loadZbAssignedPills();
}

function closeZbAssignModal() {
  document.getElementById('zb-assign-modal').style.display = 'none';
  _zbAssignSelected.clear();
}

// Call on batch load
loadZbAssignedPills();
```

**CSS (nowe reguły w `mbr/static/style.css`):**

```css
/* Inline zbiorniki section in batch detail */
.zb-assign-section {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 10px 16px;
  background: var(--surface);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  margin-bottom: 14px;
}
.zb-assign-label {
  font-size: 10px; font-weight: 700;
  color: var(--text-dim);
  text-transform: uppercase; letter-spacing: 0.5px;
}
.zb-assign-pills { display: flex; gap: 6px; flex-wrap: wrap; flex: 1; }
.zb-assign-empty { color: var(--text-dim); font-style: italic; font-size: 11px; }

.zb-pill {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--blue-bg); color: var(--blue);
  font-size: 11px; font-weight: 600; font-family: var(--mono);
}
.zb-pill-remove {
  border: none; background: none; cursor: pointer;
  color: var(--blue); font-size: 14px; line-height: 1;
  padding: 0 2px; margin-left: 2px;
  border-radius: 50%;
}
.zb-pill-remove:hover { background: rgba(0,0,0,0.08); }

.zb-assign-add {
  padding: 5px 12px;
  border: 1px dashed var(--border);
  border-radius: 6px;
  background: transparent; color: var(--text-sec);
  font-size: 11px; font-weight: 500;
  cursor: pointer; transition: all 0.12s;
}
.zb-assign-add:hover { border-color: var(--teal); color: var(--teal); border-style: solid; }

/* Mini-modal grid */
.zb-assign-modal-body {
  width: 520px; max-width: 95vw;
  background: var(--surface); border-radius: 10px;
  display: flex; flex-direction: column;
  max-height: 70vh; overflow: hidden;
}
.zb-assign-modal-head {
  padding: 14px 18px; border-bottom: 1px solid var(--border);
  display: flex; justify-content: space-between; align-items: center;
  font-weight: 600;
}
.zb-assign-modal-grid {
  padding: 16px;
  display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: 8px;
  overflow-y: auto; flex: 1;
}
.zb-assign-tile {
  padding: 10px 8px;
  border: 1.5px solid var(--border); border-radius: 8px;
  background: var(--surface); cursor: pointer;
  text-align: center; transition: all 0.12s;
}
.zb-assign-tile:hover { border-color: var(--teal); }
.zb-assign-tile.selected {
  border-color: var(--teal); background: var(--teal-bg);
}
.zb-assign-tile-nr { font-weight: 700; color: var(--teal); font-family: var(--mono); }
.zb-assign-tile-cap { font-size: 10px; color: var(--text-dim); margin-top: 2px; }

.zb-assign-modal-footer {
  padding: 12px 18px; border-top: 1px solid var(--border);
  display: flex; justify-content: flex-end;
}
```

### Audit

Opcjonalnie — rozszerzyć istniejący endpoint `POST/DELETE /api/zbiornik-szarze` o audit event (np. `ebr.zbiornik.linked` / `ebr.zbiornik.unlinked`). Poza zakresem tego spec — nie chcemy rozbudowywać zakresu. Jeśli będzie potrzeba trace'u kto kiedy co odpiął, dodamy w osobnym PR.

## Testy

`tests/test_laborant_routes.py` lub `tests/test_zbiorniki.py` (cokolwiek bliższe):

1. `test_zbiornik_assign_midbatch_links_row` — POST /api/zbiornik-szarze dla otwartej szarży tworzy wiersz w `zbiornik_szarze`.
2. `test_zbiornik_unlink_midbatch_removes_row` — DELETE usuwa wiersz.
3. `test_zbiornik_masa_kg_null_when_midbatch` — POST bez `masa_kg` zostawia NULL w DB.
4. `test_pump_modal_preloads_midbatch_assigned` — po mid-batch linkowaniu pump modal (GET /api/zbiornik-szarze/<ebr_id>) zwraca te przypisania.

## Zakres zmian

| Plik | Zmiana |
|---|---|
| `mbr/templates/laborant/_fast_entry_content.html` | Markup sekcji `.zb-assign-section` + mini-modal + JS (`loadZbAssignedPills`, `openZbAssignModal`, `toggleZbAssign`, `confirmZbAssign`, `unlinkZbiornik`, `closeZbAssignModal`). Gate `{% if batch.typ == 'szarza' %}`. Call `loadZbAssignedPills()` on batch render. |
| `mbr/static/style.css` | Styl `.zb-assign-*` (inline section + pills + mini-modal + tiles). |
| `tests/test_*.py` | 4 testy. |

**Bez zmian w:** `mbr/zbiorniki/routes.py`, `mbr/zbiorniki/models.py`, schemie DB, `laborant/routes.py`, `laborant/models.py`.

## Ryzyka

- **Konflikt ze zbiornikiem na innej szarży** — user wybrał "ignoruj". Jeżeli tank fizycznie jest jeszcze zajęty inną szarżą, nic nie pęknie — po prostu obie szarże mają link w `zbiornik_szarze`. Laborant korzysta z wiedzy fizycznej.
- **Pump modal przy zakończeniu** — preloaduje już istniejące przypisania. Laborant może dalej je modyfikować w pump modalu (tam też jest masa distribution). Brak kolizji.
- **Utrata mid-batch pinów przy cancel** — szarża `status='cancelled'` nie ma specjalnego clean-upu; linki w `zbiornik_szarze` zostają. To pre-existing behavior, nie zmieniamy.
