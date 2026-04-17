# Spec — Persistencja korekt + sum field fix (Chegina_K7 szarża)

**Data:** 2026-04-17
**Status:** zatwierdzony, gotowy do pisania planu implementacyjnego
**Zakres:** naprawa dwóch bugów w panelu korekt/dodatków Chegina_K7 szarża. Tylko ten produkt ma multi-stage workflow (sulfonowanie → utlenienie → standaryzacja) i tylko tam występują korekty z podpowiedziami.

## Kontekst i problemy

**Bug 1 — drafty korekt nie są trwałe:**
- Manualne wpisy laboranta w polach korekt (np. override sugerowanej wartości Perhydrol 34%) są zapisywane tylko do `sessionStorage` (FD — Form Drafts system)
- Po `FD.clear()` (wywołanym przy submit "Nowa runda"), refresh F5, albo zmianie widoku → draft znika
- Przelicz formuły (`recomputeStandV2`) generuje sugestię; `FD.fill` próbuje przywrócić draft, ale go już nie ma → pole wraca do sugerowanej wartości albo jest puste
- Manualne wartości **nigdy nie trafiają do bazy** zanim laborant nie kliknie explicit przycisku. Zmiana trybu pracy (szarża A → inna szarża → F5 → powrót do A) traci wszystkie niezatwierdzone edycje

**Bug 2 — sum field (woda całkowita) nie przelicza się:**
- Pole `corr-total-woda-<sekcja>` ma być sumą `Woda` + `Kwas cytrynowy`
- Funkcja `recomputeStandTotal()` linia 299 w `_correction_panel.html` ma guard `if (FD.get(totalEl.id) !== null) return;` — jak draft totalu istnieje, recalc nie działa
- Gdy laborant zmienia Woda lub Kwas, partial mitigation (`FD.del("corr-total-woda")`) jest niedeterministyczna — raz działa, raz nie
- Efekt: po wstępnej sugestii total zastyga; zmiany komponentów go nie ruszają

## Cele

1. **Każda zmiana wartości korekty → trwała w bazie od razu** (per-field auto-save, podobnie jak pomiary)
2. **Sum field zawsze odzwierciedla aktualną sumę komponentów** (readonly, zero drafty, zero guardy)
3. **Atrybucja per-szarża jest solidna** — laborant może przełączać szarże, odświeżać stronę, zamykać/otwierać przeglądarkę — wartości zawsze należą do konkretnej szarży w bazie
4. **Zero utraconych danych** przy przełączeniach — pending saves są flushed przed `loadBatch(nowyEbrId)`

## Non-goals

- Refaktor całego panelu korekt — tylko persistencja + sum
- Zmiana modelu `etap_korekty_katalog` — formuły zostają jak są
- Migracja istniejących batchy — K7 szarże pre-fix nie mają draftów do zapisania (bo draft był tylko w sessionStorage)
- Korekty dla innych produktów — K7 jest jedynym produktem multi-stage po MVP cleanup

## Decyzje architektoniczne

### D1: Auto-save per-field, bez FD dla pól korekt

Pole korekty na `onblur` → `saveKorektaField(this)` → PUT do `/api/pipeline/lab/ebr/<ebr_id>/korekta`. Natychmiastowa persystencja.

Usuwamy użycie `FD` (sessionStorage) dla pól korekt. FD zostaje dla pomiarów jeśli tam jest obecnie używane — nie ruszamy.

### D2: Sum field jest readonly, derived w JS

`corr-total-woda-<sekcja>` dostaje atrybut `readonly`. Nigdy nie trafia do bazy. `recomputeStandTotal()` po prostu: `totalEl.value = woda + kwas`. Bez guardów, bez FD.get/set dla totalu, bez mitigation. Na każde `oninput` Woda/Kwas → wywołanie `recomputeStandTotal`.

### D3: UPSERT endpoint z explicit ebr_id w URL

Jedna metoda `PUT /api/pipeline/lab/ebr/<ebr_id>/korekta`:
- ebr_id jest w ścieżce URL — każdy zapis niezawodnie przypisany do konkretnej szarży
- Body: `{etap_id, substancja, ilosc, ilosc_wyliczona}`
- Backend resolvuje aktywną sesję dla (ebr_id, etap_id), UPSERT do `ebr_korekta_v2`
- `ilosc = null` → UPDATE na NULL (laborant wyczyścił pole, formuła może znów suggestować)

### D4: Flush pending saves przed zmianą szarży

`loadBatch(nowyEbrId)` awaituje `Promise.allSettled(_pendingKorektaSaves)` zanim fetchuje dane nowej szarży. Gwarancja że każdy niedokończony save dla starej szarży doleci do bazy zanim przełączymy UI.

### D5: Formuła vs manualne — bez zmian w UX

Dziedziczymy obecne zachowanie:
- Na render: jeśli `ebr_korekta_v2.ilosc` IS NOT NULL → tę wartość wpisujemy w pole (manualne wygrywa)
- Jeśli `ilosc IS NULL` → wpisujemy `ilosc_wyliczona` (sugestia z formuły)
- Gdy laborant zmienia pomiar-źródło formuły → `ilosc_wyliczona` aktualizowana, ale `ilosc` manualne nie ruszane (sticky override)

## Komponenty zmienione

| Plik | Zmiana |
|---|---|
| `mbr/pipeline/models.py` | Nowa funkcja `upsert_ebr_korekta(db, ebr_id, etap_id, substancja, ilosc, ilosc_wyliczona)` |
| `mbr/pipeline/lab_routes.py` | Nowy endpoint `PUT /api/pipeline/lab/ebr/<ebr_id>/korekta` |
| `mbr/templates/laborant/_correction_panel.html` | Usunięcie FD dla pól korekt, dodanie `saveKorektaField()` + `_pendingKorektaSaves` state, zmiana sum field na readonly, uproszczenie `recomputeStandTotal` (bez guardów) |
| `mbr/templates/laborant/_fast_entry_content.html` | `loadBatch()` awaituje pending korekta saves |
| `tests/test_pipeline_lab.py` | Testy UPSERT endpointa |

## Endpoint contract

```
PUT /api/pipeline/lab/ebr/<int:ebr_id>/korekta
@login_required (lab, admin, cert, kj)

Body: {
  "etap_id":        int,     # required
  "substancja":     str,     # required — looked up in etap_korekty_katalog
  "ilosc":          float | null,  # required; null = usunąć manualny override
  "ilosc_wyliczona": float | null  # optional — ostatnia sugestia z formuły
}

Response 200: {
  "ok": true,
  "id":   int,    # ebr_korekta_v2.id
  "sesja_id": int,
  "korekta_typ_id": int,
  "ilosc":  float | null,
  "ilosc_wyliczona": float | null
}

Response 400: no active sesja for (ebr_id, etap_id)
Response 404: substancja nie istnieje w etap_korekty_katalog dla etapu
Response 403: user nie ma uprawnień (@login_required + role check)
```

UPSERT logic:
- Find `ebr_etap_sesja` where `ebr_id=? AND etap_id=? AND status IN ('nierozpoczety', 'w_trakcie')` — latest by `runda`
- If none → 400 error "No active session — can't save correction to closed sesja"
- Find `etap_korekty_katalog.id` where `etap_id=? AND substancja=?` → korekta_typ_id (or accept korekta_typ_id directly in body)
- INSERT OR UPDATE `ebr_korekta_v2` on UNIQUE(sesja_id, korekta_typ_id)

## Frontend flow

**Render korekt** (w `recomputeStandV2` / `recomputePerhydrol`):
```
for each korekta_field:
    row = backend_data.sesje_korekty[sesja_id][korekta_typ_id]  # z lab_get_etap_form
    if row and row.ilosc != null:
        field.value = format(row.ilosc)      # manualne DB wins
        field.classList.add('corr-manual')   # visual marker
    else:
        suggested = compute_from_formula()    # z etap_korekty_katalog + aktualne pomiary
        field.value = format(suggested)
        field.dataset.suggested = suggested
        field.classList.add('corr-suggested')
```

**Save handler** (onblur):
```
saveKorektaField(input):
    ebr_id = input.dataset.ebrId
    etap_id = input.dataset.etapId
    substancja = input.dataset.substancja
    ilosc = parse_decimal(input.value)  # null if empty
    suggested = parse(input.dataset.suggested)
    
    input.classList.add('corr-saving')
    promise = fetch('PUT /api/pipeline/lab/ebr/{ebr_id}/korekta',
                    body={etap_id, substancja, ilosc, ilosc_wyliczona: suggested})
        .then(ok): flash corr-saved for 800ms
        .catch: corr-error outline
    
    _pendingKorektaSaves.push(promise)
    promise.finally: remove from _pendingKorektaSaves
    return promise
```

**Sum field**:
```html
<input id="corr-total-woda-<sekcja>" type="text" readonly class="corr-total-derived">
```
```javascript
function recomputeStandTotal(sekcja) {
  var woda = parseDecimal('#corr-manual-woda-' + sekcja) || 0;
  var kwas = parseDecimal('#corr-manual-kwas-' + sekcja) || 0;
  document.getElementById('corr-total-woda-' + sekcja).value =
    (woda + kwas > 0) ? fmt(woda + kwas) : '';
}
```
Wywoływane z `oninput` Woda i Kwas. Bez guardów, bez FD.

**Flush przed zmianą szarży**:
```javascript
async function loadBatch(ebrId, ...) {
  if (_pendingKorektaSaves.length > 0) {
    await Promise.allSettled(_pendingKorektaSaves.slice());
  }
  // ... rest of loadBatch
}
```

**Usunięte zachowania**:
- `FD.set/get/fill/clear/del` dla `corr-manual-*` i `corr-total-*` pól
- Guard `if (FD.get(totalEl.id) !== null) return;` w `recomputeStandTotal`
- Mitigation `FD.del("corr-total-woda-...")` w `oninput` Woda/Kwas

## Testy

**Backend (`tests/test_pipeline_lab.py`):**

```python
def test_upsert_korekta_creates_new_row(client, seeded):
    # Zapis dla świeżej sesji — INSERT
    
def test_upsert_korekta_updates_existing(client, seeded):
    # Dwukrotny zapis tej samej (sesja, korekta_typ) — tylko UPDATE, count=1
    
def test_upsert_korekta_ilosc_none_clears_manual(client, seeded):
    # ilosc=null → UPDATE SET ilosc=NULL
    
def test_upsert_korekta_persists_ilosc_wyliczona(client, seeded):
    # ilosc_wyliczona zapisana do kolumny

def test_upsert_korekta_requires_active_sesja(client, seeded_closed_sesja):
    # Sesja zamknięta → 400

def test_upsert_korekta_unknown_substancja_returns_404(client, seeded):
    # "NieMaTakiejSubstancji" → 404

def test_upsert_korekta_attribution_per_batch(client, two_seeded_batches):
    # Zapis dla ebr=40, read dla ebr=55 — nie widzi danych 40

def test_upsert_korekta_different_sesje_different_rows(client, seeded_2_sesje):
    # Runda 1 + runda 2 = 2 rekordy, każda runda osobno
```

**Frontend — manual smoke checklist (brak testów JS):**

1. K7 szarża: wpisz pomiar so3 w sulfonowanie → formuła generuje Perhydrol sugestia
2. Override Perhydrol wartością manualną → opuść pole → zielony flash "zapisane"
3. **F5 → manualna wartość Perhydrol widoczna** (nie sugerowana)
4. Zmień widok na inną szarżę → powrót → manualna wartość dalej widoczna
5. Restart serwera `python -m mbr.app` → F5 → manualna wartość widoczna
6. Standaryzacja: wpisz Woda=10, Kwas=5 → total Woda całkowita=15 natychmiast
7. Zmień Woda na 12 → total natychmiast 17
8. Zmień Kwas na 3 → total natychmiast 15
9. Total field jest readonly — klik niczego nie robi
10. "Nowa runda" na standaryzacji → fresh sesja, pola korekt puste (bez kopiowania z poprzedniej rundy), formuła generuje nowe sugestie

## Rollout

Jeden PR, ~4 commity:

| Commit | Treść | Test |
|---|---|---|
| 1 | Backend test `test_upsert_korekta_*` (failing) | pytest -k korekta → FAIL |
| 2 | Backend impl `upsert_ebr_korekta()` + PUT endpoint | pytest -k korekta → PASS |
| 3 | Frontend `_correction_panel.html` — saveKorektaField, usunięcie FD dla korekt, readonly total | pytest zielone, manual smoke |
| 4 | Frontend `_fast_entry_content.html` — flush pending przed loadBatch | manual smoke |

## Kryterium gotowe

1. `pytest -q` zielone (nowe testy + żadnych regresji)
2. Manual smoke 1-10 z checklisty przechodzi na K7 szarży na real DB
3. Grep po `FD.set.*corr-manual\|FD.get.*corr-total\|FD.del.*corr-total` w `_correction_panel.html` — 0 trafień (FD zniknęła z pól korekt)
4. Sum field `corr-total-woda-*` ma atrybut `readonly` w HTML generowanym

## Ryzyko i mitigation

- **Race: save w locie a zmiana szarży** → flush pending + każdy save ma ebr_id w URL (attribution solidna)
- **Brak aktywnej sesji** → endpoint zwraca 400, frontend pokazuje corr-error, laborant rozumie że musi zamknąć poprzednią rundę lub zrestartować
- **Formula re-suggests overwrites manual** — nie ruszamy: `ilosc_wyliczona` update'owana, `ilosc` sticky
- **Network down** → `corr-error` outline, laborant widzi problem i może retry (blur znowu), dane NIE są stracone w DOM dopóki nie F5

## Out of scope (debt na później)

- Integracja auto-save pomiarów pod ten sam wzorzec (pomiary mają własny flow)
- "Bulk save" dla korekt (wszystkie naraz) — YAGNI
- Wizualizacja historii korekt (kto zmienił, kiedy) — YAGNI
- Korekty dla innych produktów — jedyny multi-stage po MVP to K7
