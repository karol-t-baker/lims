# Parametry opisowe (jakościowe) — rozszerzenie flow laboranckiego — Design Spec

**Date:** 2026-04-20
**Status:** Approved for implementation; decomposed into 3 PRs
**Scope:** Średnie feature — 3 sekwencyjne PR, każdy 1–3 dni pracy.
**Related:** Bazuje na `2026-04-19-external-lab-params-design.md` (`grupa='zewn'` już częściowo zaimplementowane).

## Problem

W świadectwach (świadectwach jakości / certyfikatach) są trzy kategorie parametrów z różnymi cyklami życia, **które wynikają z kombinacji istniejących kolumn** `parametry_analityczne.typ` i `parametry_analityczne.grupa` — nie wymagają nowego enuma:

| Rodzaj | Identyfikacja w schemacie | Cykl życia |
|---|---|---|
| Wewn. lab numeryczny | `grupa='lab'` + `typ ∈ {bezposredni, titracja, obliczeniowy, binarny}` | Laborant wpisuje wynik przy ukończeniu partii (dzisiejszy domyślny flow). |
| Lab zewnętrzny numeryczny | `grupa='zewn'` (i zwykle `typ='bezposredni'`) | Wartość przychodzi dni po ukończeniu partii. Wpisuje KJ/laborant w hero. Częściowa obsługa (spec 2026-04-19), brak widgetu edycji. |
| Opisowy (jakościowy) | `typ='jakosciowy'` (dowolny `grupa`) | Wartość = krótki tekst z predefiniowanej listy (np. "bezbarwna ciecz", "charakterystyczny"). Dziś obsługiwany tylko statycznie — `parametry_etapy.cert_qualitative_result` trzyma jedną wartość per produkt, niezależną od partii. Brak listy dozwolonych wartości, brak per-partia wartości. |

Braki:

- Laborant w formularzu wejściowym widzi **wszystkie** parametry, w tym te, których nie oznacza (zewn oraz jakościowe wypełniane poza tym formularzem). Mylące, zaśmiecony formularz.
- Dla `typ='jakosciowy'` nie ma mechanizmu: (a) definiowania listy dozwolonych wartości per parametr, (b) zmienienia wartości per partia, (c) dropdownu zamiast free-text dla admina.
- `grupa='zewn'` nie ma widgetu w hero/rejestrze ukończonych pozwalającego KJ na późne uzupełnienie wartości.

## Goal

Pełen flow:

1. Admin w rejestrze parametrów:
   - Oznacza parametr jako `typ='jakosciowy'` (już dziś możliwe) **oraz** konfiguruje listę dozwolonych wartości dropdownu (nowe pole JSON).
   - Wybiera domyślną wartość per produkt w `/admin/wzory-cert` (reuse istniejącego `cert_qualitative_result`, podmieniony z free-text na `<select>` dla jakościowych).
2. Laborant w formularzu wejściowym (przed ukończeniem partii) widzi **tylko parametry z `grupa='lab'` AND `typ ≠ 'jakosciowy'`**. Opisowe (jakościowe) są auto-wypełnione wartością domyślną przy utworzeniu partii; zewn czekają puste.
3. W hero (widok szczegółowy partii po ukończeniu) i po kliknięciu wiersza w Rejestrze Ukończonych — wszystkie parametry widoczne, edytowalne. `typ='jakosciowy'` ma dropdown z listy; `grupa='zewn'` ma numeric input z wizualnym oznaczeniem "lab zewn.".
4. Świadectwo renderuje się per-partia: `typ='jakosciowy'` bierze wartość z `ebr_wyniki.wartosc_text` konkretnej partii (fallback na `cert_qualitative_result` jeśli puste); `zewn` pusty → myślnik w Wyniku.

## Non-goals

- **Nowe wartości enumów.** `grupa` zostaje `{lab, zewn}`; `typ` ma istniejącą wartość `jakosciowy`. Nie tworzymy `grupa='opisowy'` ani nowej wartości `typ='opisowy'`.
- **Nowe tabele.** Jedyne rozszerzenie schematu: jedna kolumna JSON `opisowe_wartosci` na `parametry_analityczne`.
- **Role-based UI.** Wszystkie role laboranckie (`lab`, `kj`, `coa`, `admin`) mogą edytować wszystkie typy w hero. Bez rozgałęzień.
- **Blokada generacji świadectwa** przy pustym `zewn`. Świadectwo jest zawsze generowalne; puste zewn renderuje się jako myślnik `−` bez etykiety "pending".
- **Wizualny podział sekcji** w hero (np. "Lab wewnętrzny" / "Lab zewnętrzny" / "Opisowe" jako osobne grupy). Jedna lista jak dziś, tylko widget zależy od `typ`/`grupa`.
- **Shared vocabulary** dla wartości opisowych. Lista dozwolonych wartości jest per-parametr (admin duplikuje wpisy typu "zgodny" jeśli pasują do wielu parametrów — akceptowalne, trzymane w JSON jednego parametru).
- **Wolny tekst** przy `typ='jakosciowy'` w hero. Laborant wybiera wyłącznie z dropdownu; wartości historyczne spoza listy są wyświetlane z oznaczeniem "(historyczna)" ale nie można ich wpisać na nowo.
- **Auto-regeneracja świadectwa** po edycji w hero. Ręczna regeneracja, jak dla zewn w spec 2026-04-19.
- **Migracja innych typów (`bezposredni`, `titracja`, …) na dropdown.** Dropdown dotyczy wyłącznie `typ='jakosciowy'`.

## Architecture

**One-liner:** Istniejące `typ='jakosciowy'` + `grupa='zewn'` już niosą pełną informację o "to parametr opisowy" i "to parametr z labu zewnętrznego". Brakuje tylko jednej kolumny (lista dozwolonych wartości), filtra w formularzu wejściowym, rozszerzenia widgetów w hero i prostego fallbacku w cert render.

Feature zdekomponowany na **3 sekwencyjne PR** — każdy dostanie własny plan.

---

## Components

### 1. Schema

**File:** `mbr/models.py` (inside `init_mbr_tables`).

#### Migracja — idempotentna

```python
try:
    db.execute("ALTER TABLE parametry_analityczne ADD COLUMN opisowe_wartosci TEXT DEFAULT NULL")
    db.commit()
except Exception:
    pass  # column already exists
```

**Brak zmian w whitelist `grupa`** — zostaje `{'lab', 'zewn'}`.
**Brak zmian w `typ`** — istniejąca wartość `jakosciowy` jest używana bez modyfikacji.

#### Format `opisowe_wartosci`

JSON array of strings:

```json
["bezbarwna ciecz / colorless liquid", "żółta ciecz / yellow liquid", "brunatna ciecz / brown liquid"]
```

- NULL dla parametrów `typ ≠ 'jakosciowy'`.
- Wymagana niepusta lista dla `typ='jakosciowy'` (walidacja na POST/PUT parametru).
- Kolejność w arrayu = kolejność w dropdownie.

#### Reuse istniejących pól

- `parametry_etapy.cert_qualitative_result` — **default per produkt** (co admin wybrał w `/admin/wzory-cert` jako "typową" wartość).
- `ebr_wyniki.wartosc_text` — **wartość per partia** dla parametrów `typ='jakosciowy'` (numeric `wartosc` zostaje NULL).
- `parametry_analityczne.typ` — **już odróżnia** jakościowy od numerycznego. Używamy bez zmian.
- `parametry_analityczne.grupa` — **już odróżnia** lab wewnętrzny od zewnętrznego. Używamy bez zmian.

### 2. Auto-fill wartości jakościowych przy tworzeniu EBR

**File:** `mbr/laborant/models.py` (lub `mbr/pipeline/models.py`, tam gdzie tworzy się snapshot `parametry_lab` / inicjalny zestaw `ebr_wyniki`).

Przy utworzeniu nowej partii EBR, dla każdego parametru w snapshot-owanych `parametry_lab` z `typ='jakosciowy'`:

1. Sprawdź `parametry_etapy.cert_qualitative_result` dla (produkt, parametr_id).
2. Jeśli niepuste → INSERT do `ebr_wyniki` (ebr_id, parametr_id, wartosc=NULL, wartosc_text=cert_qualitative_result).
3. Jeśli puste → nie rób nic (laborant/KJ uzupełni w hero).

### 3. Backfill dla istniejących otwartych partii

**New file:** `scripts/backfill_jakosciowe_values.py` (idempotentny, wzorowany na `scripts/backfill_*` w `auto-deploy.sh`).

Dla każdej otwartej partii (EBR), dla każdego parametru `typ='jakosciowy'` w jej snapshot `parametry_lab`:

- Jeśli nie istnieje wiersz w `ebr_wyniki` dla (ebr_id, parametr_id) → INSERT z `wartosc_text = cert_qualitative_result` (z `parametry_etapy` dla produktu partii).
- Jeśli istnieje, zostaw.

Guard: `WHERE NOT EXISTS (SELECT 1 FROM ebr_wyniki WHERE ebr_id=? AND parametr_id=?)`. Script dodany do `auto-deploy.sh` jako step przed restartem (jak inne backfille).

### 4. Admin UI — Parametry editor

**File:** `mbr/templates/parametry_editor.html`.

#### Warunkowy edytor listy wartości

Gdy wybrany `typ='jakosciowy'` → pokazuje się dodatkowy panel "Dozwolone wartości" (ukryty dla innych typów). UI:

- Sortowalna lista wierszy (każdy = jedna wartość tekstowa).
- Przyciski: "Dodaj", "Usuń", drag-reorder (lub strzałki góra/dół).
- Zapis przez PUT `/api/parametry/<id>` z polem `opisowe_wartosci` jako JSON array.

**Brak nowego dropdownu `grupa='opisowy'`** — dropdown `grupa` zostaje jak dziś (po PR z 2026-04-19) z wartościami `{lab, zewn}`.

#### Walidacja backendowa

W `mbr/parametry/routes.py` POST/PUT:

- Jeśli `typ='jakosciowy'` w body → `opisowe_wartosci` musi być niepustą listą stringów (po deserializacji JSON). Inaczej 400.
- Jeśli `typ ≠ 'jakosciowy'` → ignoruj/wyzeruj `opisowe_wartosci`.
- **Guard zmiany typu historycznego parametru:** jeśli parametr ma wartości w `ebr_wyniki` niezgodne z nowym typem (np. `jakosciowy` → `bezposredni`, a są niepuste `wartosc_text` bez `wartosc`) → 409 z komunikatem "Nie można zmienić typu parametru z historycznymi wartościami niezgodnymi". Ten sam guard pasuje zmianie `grupa` (już wymagane po 2026-04-19).

### 5. Admin UI — Wzory cert (`/admin/wzory-cert`)

**File:** `mbr/templates/admin/wzory_cert.html` + `mbr/certs/routes.py`.

Dziś dla każdego parametru w wariancie jest `<input data-field="qualitative_result">` (text). Rozszerzamy:

- Jeśli parametr ma `typ='jakosciowy'` i niepustą `opisowe_wartosci` → podmiana `<input>` na `<select>` z opcjami z listy.
- W innych przypadkach — bez zmian (dalej free-text, jak dziś; zachowuje backward compat dla parametrów, których admin jeszcze nie skonfigurował z listą).

#### Walidacja po stronie backendu

W `PUT /api/cert/config/product/<key>`:

- Dla parametrów `typ='jakosciowy'` — `qualitative_result` musi być jedną z `opisowe_wartosci` (albo pusta). W przeciwnym razie 400.
- Dla innych typów — bez zmian.

Audit (`cert.config.updated`) już istnieje, automatycznie loguje.

### 6. Laborant UI — Entry form filter

**File:** `mbr/laborant/models.py` (`build_pipeline_context()` lub najbliższy krok budowy listy pól do renderu), `mbr/templates/laborant/_fast_entry_content.html`.

**Strategy:** filtr w runtime na liście pól rendererowanych do formularza wejściowego.

```python
# W build_pipeline_context lub jego caller dla trybu entry
def _is_entry_visible(field):
    grupa = field.get('grupa') or 'lab'
    typ = field.get('typ')
    return grupa == 'lab' and typ != 'jakosciowy'

visible_fields = [f for f in all_fields if _is_entry_visible(f)]
```

Parametry z `grupa='zewn'` **lub** `typ='jakosciowy'` dalej są w snapshot `parametry_lab` partii (dla zachowania historii), ale niewidoczne w formularzu wejściowym.

**Tryb hero** (partia ukończona) → **nie filtruje**, pokazuje wszystkie.

**Discriminator entry vs hero:** parametr do `build_pipeline_context()` albo dedykowany flag backendowy (do wyboru przy implementacji — preferowany backend żeby frontend pozostał prosty).

### 7. Laborant UI — Hero z rozszerzoną edycją

**File:** `mbr/templates/laborant/_fast_entry_content.html` (JS `buildRoundFormRender` + template paragrafów pól).

W trybie hero (ukończona partia):

#### Widgety per typ/grupa

- **`typ='jakosciowy'`** — `<select>` z opcjami z `parametry_analityczne.opisowe_wartosci`. Pre-selected = aktualna `ebr_wyniki.wartosc_text` tej partii.
  - Jeśli wartość partii nie występuje w aktualnej `opisowe_wartosci` (lista zmieniona po zapisaniu) → dodaj ją jako pierwszą opcję z suffixem `(historyczna)`.
  - Null-option "—" (puste) jako pierwsza opcja, jeśli parametr jest niewymagany.
- **`grupa='zewn'` (i `typ ≠ 'jakosciowy'`)** — `<input type="number">` + wizualne oznaczenie obok nazwy pola (badge CSS np. `[lab zewn.]`, bez nowej ikony). Pusta wartość dozwolona.
- **Pozostałe (`grupa='lab'`, `typ ≠ 'jakosciowy'`)** — istniejący `<input type="number">`. Bez zmian.

#### Dostęp

Route `/laborant/ebr/<id>/save` już ma `@role_required("lab", "cert", "kj", "admin")`. Wszystkie role laboranckie edytują.

### 8. Backend — `save_wyniki` rozszerzenie

**File:** `mbr/laborant/models.py::save_wyniki`.

Dziś zapisuje `ebr_wyniki.wartosc` (numeric) + auto `w_limicie`. Rozszerzamy:

- **Request body:** każdy wiersz wyniku ma `typ` i `grupa` (albo resolve przez JOIN z `parametry_analityczne` w handlerze — do wyboru, ale czytelniej w POST).
- **Dla `typ='jakosciowy'`:** pisz `wartosc_text` (string z dropdownu), `wartosc=NULL`. `w_limicie` = `1` jeśli wartość jest w `opisowe_wartosci`, `0` jeśli historyczna / spoza listy.
- **Dla `grupa='zewn'` (numeric):** jak `lab` (numeric). Różnica tylko audit: event log z `source='zewn'` żeby widać było że KJ/ktoś uzupełnił późno.
- **Dla pozostałych:** bez zmian.

#### Walidacja

- `typ='jakosciowy'`: `wartosc_text` musi być niepusta (jeśli field required) i dozwolony allowed-values lub ""; jeśli spoza — zapis OK ale z flagą `w_limicie=0` i wpisem audit "wartość historyczna/spoza listy".
- `grupa='zewn'`: jak `lab` — walidacja min/max jeśli ustawione.

### 9. Cert render

**File:** `mbr/certs/generator.py::build_context` (okolice linii 347–359).

Dziś:

```python
if qualitative_result:
    row.result = qualitative_result
elif data_field:
    row.result = fetch_from_ebr_wyniki(...)  # numeric
else:
    row.result = ''
```

Zmiana dla `typ='jakosciowy'`:

```python
# Dla typ='jakosciowy':
row.result = (fetch_wartosc_text(ebr_id, parametr_id)
              or qualitative_result
              or '')
```

Dla `grupa='zewn'` (numeric): jeśli `wartosc` jest NULL → `row.result = '−'` (U+2212 minus sign, nie hyphen).

Dla pozostałych: bez zmian.

### 10. Preview w edytorze wzorów

**File:** `mbr/certs/generator.py::build_preview_context`.

- Dla `typ='jakosciowy'` → używa `qualitative_result` (bo preview nie ma konkretnej partii — jak dziś).
- Dla `grupa='zewn'` → placeholder `"1,0000"` jak dziś dla liczbowych (numeric preview).
- Dla pozostałych → bez zmian.

Preview nie musi się zmieniać — naturalnie używa admin-configured defaults.

### 11. Audit

**File:** `mbr/laborant/routes.py::save` + istniejący audit helper.

Dziś audit loguje zmiany wyników generycznie. Rozszerzamy payload:

```python
log_audit(
    event='ebr.wynik.updated',
    entity_id=ebr_id,
    details={
        'parametr_id': pid,
        'typ': 'jakosciowy',       # albo inny typ
        'grupa': 'zewn',           # albo 'lab'
        'field': 'wartosc_text',   # albo 'wartosc'
        'old_value': old,
        'new_value': new,
        'source': 'hero_edit',
    }
)
```

Dla `zewn`/`jakosciowy` edytowanych w hero — **pełna historia** kto/kiedy/co. Istotne dla compliance (bo partia już była "ukończona" gdy edytowano).

### 12. Testy

**New files / additions:**

- `tests/test_parametry_jakosciowe.py`:
  - POST/PUT `/api/parametry` z `typ='jakosciowy'` + `opisowe_wartosci` → zapis + odczyt.
  - Walidacja: pusta lista przy `jakosciowy` → 400.
  - Zmiana `typ` parametru z historycznymi niekompatybilnymi wartościami → 409.

- `tests/test_laborant_entry_filter.py`:
  - Formularz entry pokazuje tylko `grupa='lab' AND typ != 'jakosciowy'`.
  - Hero pokazuje wszystkie.

- `tests/test_ebr_jakosciowe_autofill.py`:
  - Przy tworzeniu EBR: `jakosciowy` parametry dostają auto-fill `wartosc_text = cert_qualitative_result`.
  - Jeśli `cert_qualitative_result` puste → nie ma auto-fill.

- `tests/test_cert_jakosciowe_rendering.py`:
  - Cert dla partii z wypełnionym `wartosc_text` pokazuje per-partia wartość.
  - Pusty `wartosc_text` + wypełnione `cert_qualitative_result` → fallback.
  - Pusty `zewn.wartosc` → myślnik `−` w renderze.

- `tests/test_save_wyniki_jakosciowe.py`:
  - Zapis `wartosc_text` dla `jakosciowy`, `w_limicie` flag.

- `tests/test_wzory_cert_jakosciowe.py`:
  - PUT cert config dla parametru `jakosciowy` akceptuje wartość z allowed list, odrzuca spoza.

---

## Rollout — 3 PR sekwencyjne

### PR1 — Schema + Admin UI (fundament)

**Touches:** `mbr/models.py`, `mbr/parametry/routes.py`, `mbr/templates/parametry_editor.html`, `mbr/templates/admin/wzory_cert.html`, `mbr/certs/routes.py`.

**Delivers:**
- Migracja: dodanie kolumny `opisowe_wartosci` na `parametry_analityczne`.
- Parametry editor: edytor listy dozwolonych wartości (pokazywany tylko dla `typ='jakosciowy'`).
- Wzory cert: `<select>` zamiast `<input>` dla qualitative_result parametrów `jakosciowy`.
- Walidacja backend + testy.

**Stan po deployu:** admin może skonfigurować istniejące parametry `typ='jakosciowy'` z listą dozwolonych wartości. Laborant flow nie zmieniony (dalej widzi wszystko, wszystko edytowalne jak dziś). Zero breakage.

**Duration:** 1–2 dni.

### PR2 — Laborant: entry filter + auto-fill + backfill

**Touches:** `mbr/laborant/models.py`, `mbr/pipeline/models.py` (EBR creation path), `mbr/templates/laborant/_fast_entry_content.html`, nowy `scripts/backfill_jakosciowe_values.py`, `deploy/auto-deploy.sh`.

**Delivers:**
- Filtr formularza wejściowego: `grupa='lab' AND typ != 'jakosciowy'`.
- Auto-insert `ebr_wyniki.wartosc_text` dla `typ='jakosciowy'` przy tworzeniu EBR.
- Backfill jednorazowy dla istniejących otwartych partii.

**Stan po deployu:** laborant w entry widzi tylko swoje numeryczne pola. Jakościowe auto-wypełnione defaultem. Zewn/jakościowy dalej nieedytowalne dla końcowego użytkownika (nie ma jeszcze widgetu hero). Świadectwo: dalej używa `cert_qualitative_result` (PR3 zmienia).

**Duration:** 1 dzień.

### PR3 — Hero/rejestr edit + cert integration

**Touches:** `mbr/templates/laborant/_fast_entry_content.html` (hero JS), `mbr/laborant/models.py::save_wyniki`, `mbr/certs/generator.py`, audit payload.

**Delivers:**
- Hero: dropdown dla `typ='jakosciowy'`, numeric input z badge dla `grupa='zewn'`, pełna edycja dla wszystkich ról laboranckich.
- `save_wyniki` przyjmuje `wartosc_text`, audit trail.
- Cert: per-partia `wartosc_text` z fallbackiem na `cert_qualitative_result`; pusty zewn → myślnik.

**Stan po deployu:** pełen flow działa — laborant/KJ edytuje wszystkie typy w hero, świadectwo reflektuje per-partia wartości, pusty zewn = myślnik.

**Duration:** 2–3 dni.

### Kolejność
PR1 → deploy → admin konfiguruje parametry jakościowe → PR2 → deploy (laborant flow clean) → PR3 → deploy (pełne).

Każdy PR można testować niezależnie i rollbackować bez łamania następnego.

---

## Open Questions (do rozstrzygnięcia przed każdym PR)

- **PR1:** format UI listy wartości — tekstarea (każda linia = 1 wartość) czy sortowalna lista? Rekomendacja: sortowalna lista z explicit add/remove (czystszy UX, zapis do JSON-a trywialny).
- **PR2:** filtr w backendzie (`build_pipeline_context()`) czy frontendzie (JS w `_fast_entry_content.html`)? Rekomendacja: backend — jedno miejsce prawdy, mniej JS.
- **PR3:** historyczne wartości spoza aktualnej listy (`opisowe_wartosci` zmienione) — wyświetlane z suffixem "(historyczna)" i **nieusuwalne** (tylko readonly) czy usuwalne (laborant może wyczyścić)? Rekomendacja: readonly display, ale dropdown pozwala zmienić na dowolną aktualną wartość.

## References

- Brainstorming skill session 2026-04-20: 5 pytań zatwierdzonych (model A, dropdown B, entry filter A, edit role A, completion C), następnie rewizja — `opisowy` zmapowany na istniejący `typ='jakosciowy'` + `grupa='zewn'` zamiast tworzenia nowej wartości `grupa='opisowy'` (user directive: "nie mnożyć bytów").
- Existing spec: `2026-04-19-external-lab-params-design.md` (fundament dla `grupa='zewn'`).
- Existing spec: `2026-04-16-parametry-ssot-design.md` (PR1 done, `parametry_etapy.grupa` already exists).
- Cert SSOT: `2026-04-09-cert-db-ssot-design.md` (DB nadrzędne nad `cert_config.json`).
