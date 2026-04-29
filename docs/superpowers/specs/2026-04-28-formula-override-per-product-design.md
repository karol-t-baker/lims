# Formula Override Per Product — Design Spec

**Data:** 2026-04-28
**Autor:** Tabaka Karol + Claude (brainstorming session)
**Scope:** `/admin/parametry` Rejestr — UI do nadpisywania formuły parametru obliczeniowego/średnia per produkt + endpoint backend

## Problem

`SA` (substancja aktywna) ma globalną formułę `sm - nacl - sa_bias`. Większość produktów pasuje (ustawia tylko `sa_bias` przez `parametry_etapy.sa_bias`), ale **Cheminox_K** i **Cheminox_K35** mają strukturalnie inną sytuację:

- Mają SA i SM na `analiza_koncowa`
- **NIE mają NaCl** w `parametry_etapy` dla tego etapu
- Faktyczna formuła powinna być `SA = SM` (bez odejmowania)

Konsekwencja: laborant fast-entry → `setupComputedFields` parsuje formułę → znajduje deps `sm`, `nacl`, `sa_bias` → szuka inputów dla każdego → `nacl` nie istnieje → `recomputeField` ma `allPresent = false` → SA nigdy nie liczy się automatycznie. Laborant musi ręcznie wpisać SA = wartość SM.

Schema już wspiera per-binding override formuły (`parametry_etapy.formula`, `get_parametry_for_kontekst:101-103` preferuje binding-formula nad globalną). Brak UI do tego — tylko pośrednie wsparcie przez `/api/parametry/sa-bias` które obsługuje tylko podstawienie `sa_bias` placeholder, nie pełną zmianę formuły.

## Decyzje projektowe

### 1. Lokalizacja UI: Rejestr Konfiguracja typu

Sekcja „Override per produkt" pojawia się **w prawym detail panelu Rejestru**, pod istniejącą sekcją „Konfiguracja typu", **tylko dla parametrów typu `obliczeniowy` lub `srednia`**. Dla `bezposredni` / `titracja` / `jakosciowy` sekcja nie renderuje się.

Rationale: param-centric widok („gdzie SA różni się od globalnej formuły"). Etapy tab czeka na osobny redesign — nie chcemy tam dodawać nowego UI.

### 2. Layout sekcji

```
Konfiguracja typu (Obliczeniowy)
─────────────────────────────────
Formuła globalna: [sm - nacl - sa_bias                           ]
Tokeny: kod parametru w nawiasach klamrowych...

Override per produkt (opcjonalne)
─────────────────────────────────
[Cheminox_K     ] [sm                             ] [×]
[Cheminox_K35   ] [sm                             ] [×]

Dodaj override:
[Wpisz nazwę produktu... ↓] [+ Dodaj]
```

Każdy istniejący override = wiersz `(produkt-tag) (formula-textarea pełna szerokość) (× delete)`. Wiersze oddzielone cienką linią `border-bottom: 1px solid var(--border-subtle)`.

### 3. UX zachowania

#### Auto-save on blur (per row)
Admin edytuje formułę w textarea → blur → `PUT /api/parametry/<id>/formula-override` z `{produkt, formula}`. Status flash krótki przy wierszu „Zapisano (Cheminox_K)" przez 3s, potem fade.

Konsystencja z Etapy tab pattern (auto-save-on-blur). Override jest niezależny od głównego param-edit, więc nie batch-uje się z `Save Wszystko`.

#### Delete via × button
Klik `×` → `confirm('Usunąć override formuły dla Cheminox_K? Wróci do globalnej formuły.')` → PUT z `formula: null` → wiersz znika z listy → produkt wraca do dropdown autocomplete.

#### Add new override
Pole input z `<datalist>` autocomplete:
- Pokazuje produkty z `_rejUsageCache[paramId].mbr_products[]` filtrowane po `formula_override === null` (czyli używają parametru w MBR ale nie mają jeszcze override)
- Admin wpisuje pierwsze litery → autocomplete sugeruje
- Wybór + klik „+ Dodaj" → nowy wiersz pojawia się w liście z **pre-filled globalną formułą** (z `parametry_analityczne.formula`)
- Admin edytuje (np. usuwa „- nacl - sa_bias" zostawiając „sm") → blur zapisuje (auto-save jak w istniejących override-ach)

#### Pre-fill behavior
Decyzja: pre-fill globalną formułą przy dodawaniu nowego override-u (Q3 A.i). Admin edytuje down zamiast pisać od zera. Bezpieczniej dla nietechnicznego usera — widzi punkt startowy.

### 4. `sa_bias` zostaje separate mechanism

Decyzja: B.i — `sa_bias` to osobne mechanizm od formula override. Nie konsolidujemy.

Rationale:
- 22+ produktów ma już ustawione `sa_bias` (0.6 / 0.0) — konsolidacja wymagałaby migracji wszystkich do explicit formula
- Mental model dwóch mechanizmów: „bias dla standardowej formuły" vs „inna formuła całkowicie" — clear separation
- Backend logic w `get_parametry_for_kontekst:101-103` już rozdziela: jeśli formula ma `sa_bias` placeholder, substytucja; inaczej formula-as-is

Frontend: sekcja override formuły **pokazuje czystą formułę** (z `parametry_etapy.formula`). Jeśli formuła zawiera `sa_bias` placeholder, admin widzi go literalnie. Edycja `sa_bias` (numeryczna wartość) zostaje w istniejącym `/api/parametry/sa-bias` endpoint — out of scope tego specu.

### 5. Backend — nowy endpoint

#### `PUT /api/parametry/<int:param_id>/formula-override`

**Body**: `{produkt: "Cheminox_K", formula: "sm"}` lub `{produkt: "Cheminox_K", formula: null}` (= usuń override). Opcjonalnie `kontekst: "<etap_kod>"` — default `"analiza_koncowa"` jeśli nie podany.

**Wymaga roli**: `admin` (`@role_required("admin")`).

**Logika**:
1. `kontekst = data.get('kontekst', 'analiza_koncowa')` — backward-compat default. Frontend dziś nie wysyła kontekstu (wszystkie obliczeniowy/srednia params żyją w `analiza_koncowa`); jeśli w przyszłości admin doda taki param w innym etapie, endpoint już obsługuje.
2. Szuka istniejącego `parametry_etapy` wiersza dla `(parametr_id, produkt, kontekst)`. Jeśli brak → 404 z `{"error": "Binding not found"}` (admin nie może override-ować dla produktu który nie używa parametru w danym etapie MBR).
2. Jeśli `formula == null` LUB `formula == ""` (empty string po `.strip()`) → `UPDATE parametry_etapy SET formula = NULL WHERE id = ?` (= clear). Pusty string traktowany jako „brak override" — frontend nie powinien wysyłać empty, ale backend bezpiecznie obsługuje.
3. Jeśli `formula = "<non-empty string>"` → `UPDATE parametry_etapy SET formula = ? WHERE id = ?` (zapisuje po `.strip()`). Bez walidacji syntactic — admin odpowiedzialny.
4. **`sa_bias` field zostaje nietknięty** — separate mechanism.
5. Rebuild `mbr_templates.parametry_lab` dla tego produktu (analogicznie do istniejącego `api_parametry_sa_bias`):
   ```python
   plab = build_parametry_lab(db, produkt)
   db.execute("UPDATE mbr_templates SET parametry_lab=? WHERE produkt=? AND status='active'",
              (json.dumps(plab, ensure_ascii=False), produkt))
   ```
6. Audit: `EVENT_PARAMETR_UPDATED` z payload:
   ```json
   {
     "parametr_id": 42,
     "kod": "sa",
     "produkt": "Cheminox_K",
     "kontekst": "analiza_koncowa",
     "action": "formula_override_set",
     "formula_old": null,
     "formula_new": "sm"
   }
   ```
   `action`: `formula_override_set` lub `formula_override_cleared` (gdy `formula_new == null`).

**Response**: `{"ok": true, "produkt": "Cheminox_K", "formula": "sm"}` (lub `formula: null` po clear).

### 6. Backend — rozszerzenie `/api/parametry/<id>/usage-impact`

Każdy `mbr_products[]` element dostaje nowe pole `formula_override`:

**Przed (Phase A3)**:
```json
{
  "mbr_products": [
    {"key": "Cheminox_K", "stages": ["analiza_koncowa"]}
  ]
}
```

**Po (ten spec)**:
```json
{
  "mbr_products": [
    {"key": "Cheminox_K", "stages": ["analiza_koncowa"], "formula_override": "sm"},
    {"key": "Chegina_K7", "stages": ["analiza_koncowa", "sulfonowanie"], "formula_override": null}
  ]
}
```

Frontend używa `formula_override`:
- Render listy istniejących overrides (`formula_override !== null`)
- Filtrowanie dropdown-a autocomplete (`formula_override === null` → produkt dostępny do dodania)

Implementacja: rozszerzenie SQL w `api_parametry_usage_impact` — JOIN z `parametry_etapy` po `(parametr_id, produkt, kontekst='analiza_koncowa')` **hardcoded**, projekcja `pe.formula AS formula_override`. Jeśli wiele etapów per produkt, bierze formula z `analiza_koncowa` (gdzie obecnie żyje SA).

**Pragmatyczna decyzja**: hardcoded `analiza_koncowa` w usage-impact backend. Spójne z obecnym stanem danych (wszystkie 41 obliczeniowy/srednia bindings są w `analiza_koncowa`). Endpoint override (sekcja 5) jest już generalized przez parametr `kontekst` w body. Jeśli w przyszłości admin doda obliczeniowy param w innym kontekście, refactor usage-impact = jedna linia (`WHERE pe.kontekst = ?` z param). YAGNI dla obecnego use case.

Dla parametrów typu `bezposredni`/`titracja`/`jakosciowy` pole `formula_override` zawsze obecne ale w praktyce zawsze `null` (nie używane przez UI). Backward compat — istniejące use case A3 (Powiązania accordion) ignoruje to pole.

### 7. Frontend — JS w `mbr/templates/parametry_editor.html`

#### Nowe funkcje:

```javascript
function _rejRenderFormulaOverrides(p) { /* render sub-section */ }
function rejSetFormulaOverride(produkt, formula) { /* PUT */ }
function rejClearFormulaOverride(produkt) { /* PUT formula=null */ }
function rejAddFormulaOverrideRow() { /* + Dodaj handler */ }
function rejFlashOverride(produkt, msg, ok) { /* status flash 3s */ }
```

#### Modyfikacja `_rejRenderTypConfig`:

Dla `typ === 'obliczeniowy' || typ === 'srednia'`, po istniejącym formula textarea, dodać:

```javascript
html += _rejRenderFormulaOverrides(p);
```

`_rejRenderFormulaOverrides(p)` async-loads `_rejUsageCache[p.id]` jeśli brak, potem renderuje listę overrides + add row.

#### Auto-save on blur

Każdy formula textarea ma `onblur="rejSetFormulaOverride('<produkt>', this.value)"`. Po PUT → flash status przy wierszu.

#### Cache invalidation

Po każdym set/clear → invalidate `_rejUsageCache[p.id]` → następny render Powiązań/Override-ów refetch fresh data.

### 8. Edge cases

- **Zmiana typu parametru `obliczeniowy` → `bezposredni`**: istniejące `parametry_etapy.formula` rows stają się orphan (nieużywane bo `setupComputedFields` triggerouje tylko dla `obliczeniowy`/`srednia`). Sekcja override znika z UI (nie renderuje się). DB cleanup — out of scope; admin może SQL-em jeśli zmienia typ świadomie.
- **Walidacja formuły**: brak (backend i frontend). Regex `[a-z_]+` w `setupComputedFields` matches kody parametrów. Jeśli admin wpisze formułę z nieistniejącym kodem (np. `sm - foo`) → SA się nie obliczy bo `foo` nie znaleziony → laborant wpisuje ręcznie. Backward compat z obecnym fallback behavior.
- **`sa_bias` placeholder w override formule**: jeśli admin wpisze `sm - sa_bias` jako override, `get_parametry_for_kontekst:102-103` substytuuje `sa_bias` per existing logic. Zachowuje istniejącą funkcjonalność.
- **Concurrent edit**: dwóch adminów edytuje override tego samego produktu — ostatni wygrywa. Brak optimistic locking.
- **Variant params (cert)**: poza scope. Formula override żyje wyłącznie w `parametry_etapy` (MBR-level), nie w `parametry_cert`. Variants w cert config nie mają own formula.
- **Sort order overrides na liście**: alfabetycznie po nazwie produktu. W praktyce rzadko będzie > 5 overrides, kolejność mało istotna.
- **Empty state — parametr bez bindings MBR**: gdy `mbr_products[]` puste (parametr typu obliczeniowy/srednia ale jeszcze nieużywany), sekcja override pokazuje komunikat: „Parametr nie jest jeszcze używany w żadnym produkcie MBR — najpierw dodaj go w zakładce Etapy". Dropdown autocomplete + przycisk Dodaj nie renderują się.
- **Non-existent kod w formule override**: jeśli admin wpisze np. `sm + foo` gdzie `foo` nie istnieje w produktach bindings, `setupComputedFields` w fast-entry parsuje formułę → znajduje `sm` (existing) i `foo` (missing) → `allPresent = false` → SA stays unset. Backward-compatible z obecnym fallback behavior. Brak walidacji syntactic — admin odpowiedzialny.
- **Concurrent edit (dwóch adminów)**: brak optimistic locking. Last-writer-wins. Akceptowalne dla obecnego setupu single-admin. Audit log pokazuje obu, kto kiedy edytował.

### 9. Testy backend

#### `tests/test_formula_override.py`

```python
def test_set_formula_override():
    """PUT formula → updates parametry_etapy.formula + audit event."""

def test_clear_formula_override():
    """PUT formula=null → SET NULL + audit with action=formula_override_cleared."""

def test_formula_override_404_when_no_binding():
    """PUT for produkt without binding → 404."""

def test_formula_override_rebuilds_parametry_lab():
    """After PUT, mbr_templates.parametry_lab reflects new formula."""

def test_formula_override_audit_payload():
    """Audit includes parametr_id, kod, produkt, action, formula_old, formula_new."""

def test_formula_override_admin_only():
    """Non-admin gets 403."""
```

#### Rozszerzenie `tests/test_parametry_usage_impact_lists.py`

```python
def test_usage_impact_includes_formula_override():
    """mbr_products items have formula_override field reflecting parametry_etapy.formula."""
```

### 10. Out of scope

- Walidacja formuły (referencyjna, syntactic) — admin odpowiedzialny, behavior backward compat
- Bulk override (multi-select produktów + jedna formuła) — pojedyncze edycje wystarczają dla obecnego use case
- UI w Etapy tab (read-only display, ikona „f(x)" przy wierszu override-owanym) — czeka na Etapy redesign
- Konsolidacja `sa_bias` z formula override w jeden mechanizm — backward compat priority
- Cleanup orphan overrides przy zmianie typu — admin ręcznie SQL-em
- Variant param formula (cert) — nie dotyczy

## Architektura — ścieżka rozwoju

### PR1 — Backend
- Nowy endpoint `PUT /api/parametry/<id>/formula-override`
- Rozszerzenie `GET /api/parametry/<id>/usage-impact` o `formula_override` w `mbr_products[]`
- Audit event payload extension dla `parametr.updated` z fields per spec sekcja 5
- 6+1 testy backend

### PR2 — Frontend Rejestr
- Modyfikacja `_rejRenderTypConfig` w `mbr/templates/parametry_editor.html`
- 4 nowe funkcje (`_rejRenderFormulaOverrides`, `rejSetFormulaOverride`, `rejClearFormulaOverride`, `rejAddFormulaOverrideRow`)
- Auto-save on blur per row
- Datalist autocomplete dla dodawania nowych override-ów
- Flash status per row

### Akceptacja

- [ ] Sekcja „Override per produkt" pojawia się tylko dla obliczeniowy/srednia params
- [ ] Lista istniejących overrides widoczna z formułą edytowalną inline
- [ ] Auto-save on blur działa, status flash potwierdza zapis
- [ ] Delete `×` → confirm → clear override w DB → produkt wraca do dropdown
- [ ] Dodawanie nowego override przez autocomplete: pre-filled globalna formuła, edycja zapisuje
- [ ] Cheminox_K + Cheminox_K35 z override `sm` → laborant wprowadza SM → SA auto-recompute (bez NaCl)
- [ ] Audit log zawiera events `parametr.updated` z action='formula_override_set'/'formula_override_cleared'
- [ ] `mbr_templates.parametry_lab` rebuilt po każdym PUT
- [ ] Wszystkie istniejące testy parametry/cert nadal zielone
- [ ] `sa_bias` mechanism nietknięty — istniejące produkty z bias=0.6/0.0 nadal działają
