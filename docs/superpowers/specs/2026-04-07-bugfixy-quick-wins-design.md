# Sub-projekt A: Bugfixy i Quick Wins — Design Spec

## Cel

Naprawić 5 bugów/brakujących walidacji w systemie MBR, które bezpośrednio wpływają na pracę laborantów.

## Fix 1: Kalkulator miareczkowań — średnia z dwóch próbek

**Problem:** `calculator.js` funkcja `acceptCalc()` (~linia 654) zbiera wyniki z obu próbek przez `_calcState.samples.map(s => calcFn(s, method)).filter(r => r !== null)`, ale wynik końcowy wstawia wartość z pierwszej próbki zamiast średniej.

**Rozwiązanie:** W `acceptCalc()` po zebraniu `results[]`, policzyć średnią: `avg = results.reduce((a,b) => a+b, 0) / results.length`. Wstawić `avg` (nie `results[0]`) jako wynik końcowy do pola. Wyświetlić średnią z formatowaniem (przecinek, odpowiednia precyzja).

**Pliki:**
- Modify: `mbr/static/calculator.js` — funkcja `acceptCalc()`, sekcja wstawiania wyniku

## Fix 2: Kalkulator miareczkowań — przecinek jako separator dziesiętny

**Problem:** Pola input w kalkulatorze (`calculator.js`) ignorują przecinek. System `lab_common.js` robi konwersję dot↔comma w polach fast entry, ale kalkulator ma własne inputy bez tej konwersji.

**Rozwiązanie:** Na wszystkich polach liczbowych w kalkulatorze dodać obsługę przecinka:
- Event listener `input` zamieniający `,` na `.` w wartości pola (żeby parseFloat działał)
- Wynik końcowy wyświetlany z przecinkiem: `.toFixed(n).replace('.', ',')`
- Dotyczy pól: masa (nawazka), objętości (V1, V2, Vz, Vf), miana (T1)

**Pliki:**
- Modify: `mbr/static/calculator.js` — inputy w sekcjach sample (volumes, mass, titrant)

## Fix 3: DEA — kalkulator miareczkowy się nie otwiera

**Problem:** Parametr `dietanolamina` ma `metoda_id` w bazie (`parametry_analityczne.metoda_id` → `metody_miareczkowe`), ale kalkulator miareczkowy się nie otwiera na focus. `metoda_id` prawdopodobnie nie trafia do atrybutu `data-metoda-id` na elemencie input w szablonie fast entry.

**Łańcuch danych:**
1. `mbr/parametry/registry.py` (`get_parametry_for_kontekst`) — zwraca `metoda_id` w JSON
2. API `/api/parametry/config` — serwuje do frontendu
3. `mbr/templates/laborant/_fast_entry_content.html` — renderuje inputy z `data-metoda-id`
4. JS focus handler (~linia 1860) — sprawdza `data-metoda-id` i wywołuje `openCalculatorFull()`

**Rozwiązanie:** Prześledzić cały łańcuch i znaleźć gdzie `metoda_id` ginie. Prawdopodobne miejsca:
- Template nie ustawia `data-metoda-id` dla parametrów typu `titracja` z `metoda_id`
- Lub JS nie rozpoznaje kontenera `.ff.titr` dla DEA

**Pliki:**
- Debug: `mbr/parametry/registry.py`, `mbr/templates/laborant/_fast_entry_content.html`
- Fix zależy od znalezionego bugu

## Fix 4: Biały ekran na duplikat numeru szarży

**Problem:** `mbr/laborant/routes.py` funkcja `szarze_new()` (~linia 34) wywołuje `create_ebr()` bez obsługi wyjątku UNIQUE constraint. SQLite rzuca `IntegrityError`, Flask nie łapie → biały ekran 500.

**Rozwiązanie:**
- Wrap `create_ebr()` w try/except `sqlite3.IntegrityError`
- Flash message: "Szarża o numerze {nr_partii} już istnieje w systemie"
- Redirect na formularz tworzenia (nie crash)

**Pliki:**
- Modify: `mbr/laborant/routes.py` — funkcja `szarze_new()`, wrap create_ebr

## Fix 5: Walidacja numeru szarży w czasie rzeczywistym

**Problem:** Brak mechanizmu sprawdzania unikalności numeru szarży przed wysłaniem formularza. Laborant dowiaduje się o duplikacie dopiero po submicie.

**Rozwiązanie:**

**Backend:**
- Nowy endpoint `POST /api/batch-exists` w `mbr/registry/routes.py`
- Przyjmuje JSON `{"produkt": "...", "nr_partii": "..."}`
- Buduje `batch_id = f"{produkt}__{nr_partii.replace('/', '_')}"` i sprawdza w `ebr_batches`
- Zwraca `{"exists": true/false}`

**Frontend (modal tworzenia szarży):**
- `mbr/templates/laborant/_modal_nowa_szarza.html`
- Debounced (300ms) event listener na polu nr_partii
- Wywołuje `/api/batch-exists` z aktualnym produktem i numerem
- Gdy `exists: true`:
  - Pole podświetlone na czerwono (border + background)
  - Komunikat: "Ten numer szarży jest już w systemie"
  - Przycisk "Zapisz" disabled
- Gdy `exists: false` lub pole puste — stan normalny

**Pliki:**
- Modify: `mbr/registry/routes.py` — nowy endpoint
- Modify: `mbr/templates/laborant/_modal_nowa_szarza.html` — JS walidacja + style
