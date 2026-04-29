# Formula Override — Naprawa propagacji do laboranta + manual edit SA

**Data:** 2026-04-29
**Autor:** Tabaka Karol + Claude (brainstorming session)
**Scope:** Naprawa endpointa `PUT /api/parametry/<id>/formula-override` (zapis do złej tabeli) + odblokowanie ręcznej edycji pola obliczeniowego (SA) w fast-entry laboranta.

## Problem

Override formuły dla parametru SA w produkcie Cheminox_K (formuła = `sm` zamiast globalnego `sm - nacl - sa_bias`) zapisuje się do DB, ale nie dociera do kalkulatora laboranta. Dodatkowo pole SA w fast-entry jest twardo `readonly`, co uniemożliwia korektę ręczną.

### Diagnoza buga propagacji

- Endpoint `PUT /api/parametry/<id>/formula-override` (commit 164a1a5 na branchu `formula-override`) zapisuje do `parametry_etapy.formula` (legacy)
- Laborant calculator czyta formułę przez ścieżkę: `mbr_templates.parametry_lab` → `build_parametry_lab` → `build_pipeline_context` → `resolve_limity` → **`produkt_etap_limity.formula`** (pipeline)
- Endpoint i konsument czytają z różnych tabel — override nigdy nie dociera

W obecnym DB worktree `formula-override`:
- `parametry_etapy.formula = "sm"` dla Cheminox_K SA ✅ (zapisane)
- `produkt_etap_limity.formula = ""` ❌ (puste)
- `mbr_templates.parametry_lab` Cheminox_K SA: `formula: "sm - nacl - 0.6"` (stara, z substytucją sa_bias)

Audit log potwierdza zapis i rebuild — ale rebuild czyta z `produkt_etap_limity` (bo `build_pipeline_context` jest pipeline-based), więc snapshot pozostaje nieświeży.

### Diagnoza read-only SA

`mbr/templates/laborant/_fast_entry_content.html`:
- Linia 2737-2738: pole obliczeniowy zawsze otrzymuje `readonly` HTML attribute
- Linia 4517: `recomputeField` ustawia `computedInput.readOnly = true` przy każdym przeliczeniu
- Linia 4482: `setupComputedFields` woła `recomputeField(computedInput)` przy każdym render — to nadpisuje wartość z DB przy F5/reload, nawet bez zmiany dependencji

## Decyzje projektowe

### 1. Endpoint pisze do `produkt_etap_limity.formula` (nie `parametry_etapy.formula`)

`produkt_etap_limity` jest tabelą używaną przez pipeline (laborant calculator). `parametry_etapy.formula` to legacy — zostawiamy w spokoju (cleanup poza scope).

Rationale: pipeline jest SSOT dla fast-entry; przepisanie endpointa to mniej zmian niż refactor `resolve_limity` żeby uwzględniał `parametry_etapy.formula` jako fallback.

### 2. Manual edit SA — model bez flagi

Wartość SA zapisywana on blur do `ebr_wyniki` jak każde inne pole. DB jest źródłem prawdy. Auto-recompute następuje **tylko reaktywnie** — gdy `input` event odpali się na zależnym polu (Cl⁻ albo SM). Wtedy nadpisuje wartość manual.

Brak osobnej flagi `is_manual` — niepotrzebna, bo:
- Persistence wartości jest standardowa (DB)
- Po reload listenery są re-attached, ale recompute nie jest odpalany initial
- Brak race condition między "manual" a "auto"

### 3. Brak initial auto-fill przy entry

Czysty model: SA pozostaje puste przy wejściu na szarżę gdzie SM jest, a SA puste. Laborant musi explicite wpisać SM (event trigger) albo wpisać SA ręcznie.

Konsekwencja: stare szarże Cheminox_K z SM ale pustym SA (powstałe przed wprowadzeniem override) NIE zostaną auto-naprawione przy reload — laborant musi ręcznie potrząsnąć SM lub wpisać SA. Akceptowalne — tych szarż jest niewiele i można je naprawić przez reentry.

### 4. Bez wizualnego rozróżnienia auto vs manual

Pole SA wygląda tak samo niezależnie czy wartość pochodzi z auto-recompute czy manual edit. DB jest źródłem prawdy, użytkownik widzi tylko wartość.

### 5. Migracja istniejących `parametry_etapy.formula`

Jednorazowy skrypt `scripts/migrate_formula_override_to_pel.py`. Idempotentny — drugi run skipuje. W praktyce migruje 1 rekord (Cheminox_K SA = `sm`). Skrypt zostaje w repo na wypadek gdyby ktoś dorzucił coś między sprawdzeniem a wdrożeniem.

`parametry_etapy.formula` po migracji NIE jest czyszczone — legacy pole nieużywane przez pipeline, cleanup wymaga osobnego refactoru SSOT.

## Architektura

### Backend — zmiana endpointa

`mbr/parametry/routes.py:471-547` (`api_parametry_formula_override`):

**Lookup binding zmienia się z:**
```sql
SELECT pe.id, pe.formula AS formula_old, pa.kod
FROM parametry_etapy pe
JOIN parametry_analityczne pa ON pa.id = pe.parametr_id
WHERE pe.parametr_id=? AND pe.produkt=? AND pe.kontekst=?
```

**Na:**
```sql
SELECT pel.id, pel.formula AS formula_old, pa.kod
FROM produkt_etap_limity pel
JOIN parametry_analityczne pa ON pa.id = pel.parametr_id
JOIN etapy_analityczne ea ON ea.id = pel.etap_id
WHERE pel.parametr_id=? AND pel.produkt=? AND ea.kod=?
```

**UPDATE zmienia się z:**
```sql
UPDATE parametry_etapy SET formula=? WHERE id=?
```

**Na:**
```sql
UPDATE produkt_etap_limity SET formula=? WHERE id=?
```

Reszta endpointa (audit payload, rebuild `mbr_templates.parametry_lab`, response shape, idempotency check) bez zmian. Domyślny `kontekst = 'analiza_koncowa'` mapuje na `etapy_analityczne.kod = 'analiza_koncowa'`.

**Edge case 404:** jeśli produkt nie ma binding w `produkt_etap_limity` dla danego etapu, zwracamy 404. Spec gwarantuje że produkt już używa parametru w MBR (lista do wyboru w UI pochodzi z `usage-impact.mbr_products[]`).

### Backend — `usage-impact`

`api_parametry_usage_impact` w `mbr/parametry/routes.py`. Dwie zmiany:

**1. `mbr_products[]` source — `produkt_etap_limity` zamiast `parametry_etapy`** (consistency z endpoint formula-override; filtruje ghost products jak Chegina_KK którego nie ma w pipeline). Obecnie:

```sql
SELECT pe.produkt AS key, pe.kontekst AS stage
FROM parametry_etapy pe
WHERE pe.parametr_id = ?
ORDER BY pe.produkt, pe.kontekst
```

Zmiana na:

```sql
SELECT pel.produkt AS key, ea.kod AS stage
FROM produkt_etap_limity pel
JOIN etapy_analityczne ea ON ea.id = pel.etap_id
WHERE pel.parametr_id = ?
ORDER BY pel.produkt, ea.kod
```

Skutek: produkty istniejące tylko w legacy (np. Chegina_KK) znikną z listy „Powiązania" i z dropdown override. Spójne z tym że laborant i tak nie ma SA dla Chegina_KK (snapshot `parametry_lab` go nie zawiera).

**2. `formula_override` extension — czytanie z `produkt_etap_limity`** (rozszerzenie z commitu 10729c7):

```sql
SELECT pel.produkt, pel.formula
FROM produkt_etap_limity pel
JOIN etapy_analityczne ea ON ea.id = pel.etap_id
WHERE pel.parametr_id = ? AND ea.kod = 'analiza_koncowa'
```

Frontend (`parametry_editor.html`) bez zmian — patrzy tylko na pole `formula_override` w response, nie wie z której tabeli.

### Migracja

`scripts/migrate_formula_override_to_pel.py`:

```python
"""One-shot migration: parametry_etapy.formula → produkt_etap_limity.formula.

Idempotent. Skips rows where pel.formula already populated.
Does NOT clear parametry_etapy.formula (legacy column, untouched).
"""

import json
import sqlite3
import sys

from mbr.parametry.registry import build_parametry_lab

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "data/batch_db.sqlite"
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")

rows = conn.execute("""
    SELECT pe.parametr_id, pe.produkt, pe.kontekst, pe.formula, pa.kod
    FROM parametry_etapy pe
    JOIN parametry_analityczne pa ON pa.id = pe.parametr_id
    WHERE pe.formula IS NOT NULL AND pe.formula != ''
""").fetchall()

migrated = 0
skipped = 0
products_to_rebuild = set()
for r in rows:
    ea = conn.execute("SELECT id FROM etapy_analityczne WHERE kod = ?", (r["kontekst"],)).fetchone()
    if not ea:
        print(f"WARN: no etap '{r['kontekst']}' for {r['kod']}/{r['produkt']}, skipping")
        skipped += 1
        continue

    pel = conn.execute(
        "SELECT id, formula FROM produkt_etap_limity WHERE produkt=? AND etap_id=? AND parametr_id=?",
        (r["produkt"], ea["id"], r["parametr_id"]),
    ).fetchone()
    if not pel:
        print(f"WARN: no pel binding for {r['kod']}/{r['produkt']}/{r['kontekst']}, skipping")
        skipped += 1
        continue

    if pel["formula"] is not None:
        print(f"SKIP: pel already has formula='{pel['formula']}' for {r['kod']}/{r['produkt']}")
        skipped += 1
        continue

    conn.execute("UPDATE produkt_etap_limity SET formula = ? WHERE id = ?", (r["formula"], pel["id"]))
    print(f"OK: {r['kod']}/{r['produkt']}/{r['kontekst']} → formula='{r['formula']}'")
    products_to_rebuild.add(r["produkt"])
    migrated += 1

# Rebuild mbr_templates.parametry_lab snapshot for affected products
for produkt in products_to_rebuild:
    plab = build_parametry_lab(conn, produkt)
    cur = conn.execute(
        "UPDATE mbr_templates SET parametry_lab=? WHERE produkt=? AND status='active'",
        (json.dumps(plab, ensure_ascii=False), produkt),
    )
    if cur.rowcount == 0:
        print(f"WARN: no active mbr_template for {produkt} — snapshot not rebuilt")
    else:
        print(f"REBUILT: parametry_lab for {produkt} ({cur.rowcount} row)")

conn.commit()
print(f"\nDone. Migrated: {migrated}, skipped: {skipped}, rebuilt snapshots: {len(products_to_rebuild)}")
```

Skrypt automatycznie rebuilduje `mbr_templates.parametry_lab` dla każdego dotkniętego produktu (idempotentny — nie-affected produkty pomijane).

### Frontend laboranta — change set

Trzy lokalne diffy w `mbr/templates/laborant/_fast_entry_content.html`:

**Diff 1 — usuń wymuszony readonly na obliczeniowy (linia 2737-2738):**

Przed:
```js
(isReadonly ? ' readonly' : '') +
(isObl && !isReadonly ? ' readonly' : '') +
```

Po:
```js
(isReadonly ? ' readonly' : '') +
```

**Diff 2 — usuń `readOnly = true` w recomputeField (linia 4517):**

Przed:
```js
var prec = parseInt(computedInput.dataset.precision || '2', 10);
var newVal = result.toFixed(prec).replace('.', ',');
computedInput.readOnly = true;
if (computedInput.value !== newVal) { ... }
```

Po:
```js
var prec = parseInt(computedInput.dataset.precision || '2', 10);
var newVal = result.toFixed(prec).replace('.', ',');
if (computedInput.value !== newVal) { ... }
```

**Diff 3 — usuń initial recompute w setupComputedFields (linia 4482):**

Przed:
```js
document.querySelectorAll('input[data-formula]').forEach(function(computedInput) {
    var formula = computedInput.dataset.formula;
    var sekcja = computedInput.dataset.sekcja;
    var deps = formula.match(/[a-z_]+/g) || [];
    deps.forEach(function(depKod) {
        var depInput = document.querySelector(...);
        if (depInput && depInput !== computedInput) {
            var handler = function() { recomputeField(computedInput); };
            ...
        }
    });
    recomputeField(computedInput);  // ← USUNĄĆ
});
```

Po: bez ostatniej linii. Listener-only.

**Diff 4 — `saveBias` / `updateBiasPreview` substytuują tylko ostatnią liczbę (zamiast hardcoded `'sm - nacl - ' + bias`):**

Stary kod (linia 4286-4289 i 4263-4264) hardcoduje formułę `'sm - nacl - ' + bias` przy zapisie biasu, co nadpisałoby override w DOM (np. `sm` → reset do `sm - nacl - 0.6`). Cheminox_K override `sm` jest bezpieczny bo bias editor nie pojawia się (regex `[a-z_]+\s*[-+]\s*([0-9.]+)\s*$` nie matchuje), ale future override z numeric tail (np. `sm - 0.5`) wyzwoliłby bug.

Przed:
```js
// updateBiasPreview (linia 4263-4264)
el.textContent = 'Formuła: sm - nacl - ' + b;

// saveBias (linia 4286-4289)
var newFormula = 'sm - nacl - ' + bias;
document.querySelectorAll('input[data-kod="' + kod + '"][data-formula]').forEach(function(saInp) {
    saInp.dataset.formula = newFormula;
    recomputeField(saInp);
    ...
});
```

Po:
```js
// updateBiasPreview — zachowaj prefix formuły, podmień ostatnią liczbę
function updateBiasPreview(val, kod) {
    var saInp = document.querySelector('input[data-kod="' + kod + '"][data-formula]');
    var oldFormula = saInp ? saInp.dataset.formula : '';
    var b = parseFloat(val) || 0;
    var preview = oldFormula.replace(/([+-]\s*)[0-9.]+\s*$/, '$1' + b);
    var el = document.getElementById('calc-bias-preview');
    if (el) el.textContent = 'Formuła: ' + preview;
}

// saveBias — analogicznie, per-input substitution
document.querySelectorAll('input[data-kod="' + kod + '"][data-formula]').forEach(function(saInp) {
    var oldFormula = saInp.dataset.formula || '';
    var newFormula = oldFormula.replace(/([+-]\s*)[0-9.]+\s*$/, '$1' + bias);
    saInp.dataset.formula = newFormula;
    recomputeField(saInp);
    ...
});
```

Działa dla:
- `sm - nacl - 0.6` → bias 0.7 → `sm - nacl - 0.7` ✅ (stara funkcjonalność zachowana)
- `sm - 0.5` → bias 0.7 → `sm - 0.7` ✅ (override z numeric tail)
- `sm` → bias editor nie pokazuje się (brak numeric tail), `saveBias` nie wywoływane ✅

### Data flow po naprawie

```
Admin edytuje override w rejestrze
  ↓ PUT /api/parametry/19/formula-override {produkt:"Cheminox_K", formula:"sm"}
Backend: UPDATE produkt_etap_limity SET formula='sm'
  WHERE produkt='Cheminox_K' AND parametr_id=19 AND etap_id=ea_analiza_koncowa
  ↓ rebuild snapshot
build_parametry_lab → build_pipeline_context → resolve_limity
  → reads pel.formula='sm' ✅
  ↓
mbr_templates.parametry_lab["Cheminox_K"]["analiza_koncowa"]["pola"][SA]["formula"]="sm"
  ↓
Laborant otwiera szarżę → fast_entry_content.html dostaje pole z data-formula="sm"
  ↓
Laborant wpisze SM = 35.5 → input event
  → setupComputedFields listener → recomputeField(SA)
  → expr="sm".replace("sm", "35.5") = "35.5" → SA = 35.5
  → on blur zapisuje do ebr_wyniki
  ↓
Laborant ręcznie zmienia SA na 36.0 → on blur zapisuje 36.0
  ↓
Laborant F5 → SA = 36.0 (z DB), brak initial recompute → wartość persystuje ✅
  ↓
Laborant zmienia SM = 35.8 → input event → recompute → SA = 35.8 (manual edit nadpisany — intent)
```

## Testy

### Backend — `tests/test_parametry_formula_override.py`

8 istniejących testów (commit 164a1a5, **na branchu `formula-override`** — nie na main) — adaptacja fixture `_seed`:

```python
def _seed(db):
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ, formula) "
               "VALUES (1, 'sa', 'SA', 'obliczeniowy', 'sm - nacl - sa_bias')")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('Cheminox_K', 'Cheminox K')")
    db.execute("INSERT INTO produkty (nazwa, display_name) VALUES ('Other', 'Other')")
    db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa) VALUES (10, 'analiza_koncowa', 'AK')")
    db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa) VALUES (11, 'sulfonowanie', 'Sulf')")
    db.execute("INSERT INTO etap_parametry (etap_id, parametr_id) VALUES (10, 1)")
    db.execute("INSERT INTO etap_parametry (etap_id, parametr_id) VALUES (11, 1)")
    db.execute("INSERT INTO produkt_etap_limity (id, produkt, etap_id, parametr_id, sa_bias) "
               "VALUES (100, 'Cheminox_K', 10, 1, 0.6)")
    db.execute("INSERT INTO produkt_etap_limity (id, produkt, etap_id, parametr_id) "
               "VALUES (101, 'Other', 11, 1)")  # Other ma SA tylko w sulfonowanie
    db.commit()
```

Asercje DB w testach: `SELECT formula FROM produkt_etap_limity WHERE id=100` zamiast `parametry_etapy WHERE id=10`. 8 testów zostaje (set / clear / clear-via-empty / 404 / kontekst override / audit set / audit clear / admin-only).

**Nowy test integracyjny:**

```python
def test_override_propagates_to_parametry_lab(monkeypatch, db):
    """End-to-end: PUT formula → rebuild widoczny w mbr_templates.parametry_lab."""
    _seed(db)
    db.execute("INSERT INTO mbr_templates (produkt, status, parametry_lab) "
               "VALUES ('Cheminox_K', 'active', '{}')")
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) "
               "VALUES ('Cheminox_K', 10, 1)")
    db.commit()
    client = _admin_client(monkeypatch, db)

    rv = client.put("/api/parametry/1/formula-override",
                    json={"produkt": "Cheminox_K", "formula": "sm"})
    assert rv.status_code == 200

    plab = json.loads(db.execute(
        "SELECT parametry_lab FROM mbr_templates WHERE produkt='Cheminox_K'"
    ).fetchone()[0])
    sa_pole = next(p for p in plab["analiza_koncowa"]["pola"] if p["kod"] == "sa")
    assert sa_pole["formula"] == "sm"
```

Ten test złapałby cały bug — write-vs-read mismatch. Bez niego sytuacja może się powtórzyć w przyszłości jeśli ktoś znów zmieni tabelę.

### Backend — `tests/test_parametry_usage_impact_lists.py`

Adaptacja **dwóch** testów (oba istnieją na branchu `formula-override`):

1. **`test_usage_impact_includes_mbr_products_list_with_stages`** — fixture seed-uje `PROD_C` tylko do `parametry_etapy`. Po zmianie źródła `mbr_products[]` na `produkt_etap_limity` (sekcja 6.1), `PROD_C` zniknie z response. Adaptacja: dodać `produkt_etap_limity` insert dla `PROD_C` w fixture.
2. **`test_usage_impact_includes_formula_override`** (commit 10729c7) — fixture pisze do `produkt_etap_limity.formula` zamiast `parametry_etapy.formula`. Asercje shape bez zmian.

> **Uwaga:** te testy istnieją tylko w worktree `.worktrees/formula-override` (commit 10729c7), nie na main. Implementacja kontynuuje ten branch, więc fixture diff jest wprost.

### Frontend — manual verify checklist (PR2)

1. **Nowa szarża Cheminox_K, świeża sesja**: wpisz SM = 35,5 → SA pojawia się natychmiast (z formuły `sm`), zapisuje się on blur
2. **Manual edit survive blur**: SA = 35,5 (auto) → zmień ręcznie na 36,0 → blur → kliknij gdzieś indziej → SA pozostaje 36,0
3. **Manual edit survive F5**: po pkt 2 reload — SA = 36,0 (z DB)
4. **Recompute nadpisuje manual przy zmianie SM**: po pkt 2 zmień SM = 35,8 → SA = 35,8, manual edit ginie
5. **Stara szarża z SM ale pustym SA**: otwórz — SA pozostaje puste do czasu manualnego ruszenia SM lub wpisania SA
6. **Czysty model — F5 z pustym SA i wypełnionym SM**: SA NIE wypełnia się automatycznie
7. **Chegina_K7 analiza_koncowa**: SM/Cl⁻/SA — formuła `sm - nacl - 0.6`, recompute działa jak dotąd. **K7 standaryzacja SA** — pole nadal manualne (laborant wpisuje ręcznie). Pre-existing: `setupComputedFields` wymaga `data-sekcja` którego process stage nie ustawia (linia 4961 — używa `data-etap`/`data-runda`). Out of scope tego fixu — naprawa wymagałaby alternatywnego query selectora w `setupComputedFields` lub dodania `data-sekcja` do process stage render
8. **Bias editor dla SA z formułą `sm - nacl - 0.6`**: panel po prawej pokazuje edytor bias, zmiana na 0.7 → preview `Formuła: sm - nacl - 0.7` → klik Zapisz → SA przelicza się z nową formułą. Działa jak dotąd (zachowana funkcjonalność)
9. **Bias editor dla Cheminox_K override `sm`**: bias editor NIE pokazuje się (regex nie matchuje braku numeric tail). Override bezpieczny ✅
10. **Pole SA edytowalne** — kursor w polu, kliknięcie → kursor pojawia się, można pisać

## Edge cases

- **Wielokrotne wywołania `setupComputedFields`** — funkcja jest wołana z 7 miejsc po `renderSections`. Po fixie żadne nie odpala initial recompute, co jest pożądane. Listener attach nadal działa.
- **Linia 4287-4298 (sa_bias change ręcznie):** zostawiamy jak jest — admin zmienia sa_bias → recompute SA na nową wartość → manual edit przepada (intent: dependency change nadpisuje manual).
- **Walidacja formuły:** brak. Nieistniejący kod (`sm + foo`) → `allPresent=false` → recompute nie odpala się → laborant wpisuje ręcznie.
- **`sa_bias` placeholder w override:** `_resolve_formula` w `mbr/pipeline/adapter.py` substytuuje `sa_bias` na faktyczną wartość. Działa po fixie.
- **Concurrent edit dwóch adminów:** last-writer-wins, audit log dokumentuje historię.
- **SA z poprzedniej rundy etapu cyklicznego:** wartość z DB widoczna przy entry. Jeśli laborant zmieni SM → recompute. Inaczej SA z poprzedniej rundy survive.
- **Normalizacja przecinek/kropka:** każdy edit SM dispatchuje `input` event, co odpala recompute. To znaczy że laborant edytujący "5,5" → "5.5" wyzwoli recompute z tą samą wartością — manual SA zostanie nadpisany identyczną liczbą. Akceptowalne (nie psuje danych, tylko trigger niepotrzebny).

## Rollout

### PR1 — backend + migracja

1. Modyfikacja `api_parametry_formula_override` — JOIN przez `produkt_etap_limity` + `etapy_analityczne`
2. Modyfikacja `api_parametry_usage_impact` — czytanie `formula_override` z `produkt_etap_limity`
3. Adaptacja `tests/test_parametry_formula_override.py` (8 testów) + dodanie `test_override_propagates_to_parametry_lab`
4. Adaptacja `tests/test_parametry_usage_impact_lists.py::test_usage_impact_includes_formula_override`
5. Skrypt `scripts/migrate_formula_override_to_pel.py` — odpalenie raz na `data/batch_db.sqlite` (oba worktree'y)
6. Po PR1: weryfikacja w worktree `formula-override` że `mbr_templates.parametry_lab` Cheminox_K SA ma `formula="sm"`

### PR2 — frontend laboranta

1. Cztery diffy w `mbr/templates/laborant/_fast_entry_content.html` (3 dla manual edit, 1 dla bias editor preserving override)
2. Manual verify checklist (10 punktów) — dev server + browser
3. Cache-bust calculator.js już istnieje (commit eb548b3 — per-startup `?v=`)

PR1 i PR2 niezależne. Branch: kontynuacja istniejącego `formula-override` worktree.

## Akceptacja

- [ ] PUT `/api/parametry/<id>/formula-override` zapisuje do `produkt_etap_limity.formula`
- [ ] Po PUT, `mbr_templates.parametry_lab["Cheminox_K"]["analiza_koncowa"]` SA pole ma `formula="sm"` (test integracyjny)
- [ ] `usage-impact.mbr_products[]` lista czyta z `produkt_etap_limity` (ghost products typu Chegina_KK znikają)
- [ ] `usage-impact` zwraca `formula_override` z `produkt_etap_limity`
- [ ] Migracja idempotentna (drugi run = no-op) i rebuilduje snapshot dla affected products
- [ ] SA pole edytowalne ręcznie
- [ ] Manual edit survive on blur, F5, switch sekcji
- [ ] Recompute odpala się tylko gdy `input` event na zależnym polu
- [ ] Cheminox_K nowa szarża: SM → SA przelicza się natychmiast z formuły `sm`
- [ ] Bias editor preserving override (substitute last numeric, no hardcoded reset)
- [ ] Chegina_K7 analiza_koncowa: recompute działa jak dotąd
- [ ] Audit zawiera `parametr.updated` z `action='formula_override_set'`/`'cleared'`

## Out of scope

- **`parametry_etapy.formula` cleanup** — pozostaje, osobny refactor SSOT
- **Walidacja formuły** — admin odpowiedzialny
- **Wizualne rozróżnienie auto vs manual SA** — wybrane: bez różnicy
- **Persistence flagi `manual`** — wybrane: czysty model bez flagi
- **Initial auto-fill SA przy entry** — wybrane: bez initial, recompute reaktywny
- **Konsolidacja `sa_bias` z formula override** — `sa_bias` osobny mechanizm
- **Bulk override** — pojedyncze edycje wystarczają
- **Formula override w cert/variant params** — osobny flow
- **Optimistic locking concurrent edits** — last-writer-wins + audit
- **K7 standaryzacja SA reactive recompute** — pre-existing brak (process stage nie ma `data-sekcja`); naprawa wymaga osobnego refactoru `setupComputedFields` z alternatywnym query selectorem
- **Naprawa danych Chegina_KK** — produkt ma SA/SM tylko w legacy `parametry_etapy`, brak w pipeline `produkt_etap_limity`; po fixie znika z UI override (bezpieczne — laborant i tak nie ma SA dla niego), ale samo wyrównanie tabel = osobny task technologa
