# Parametry: Precision per produkt + Modal dodawania + Auto-zaokrąglanie

## Problem

1. Dodawanie parametrów do analizy końcowej odbywa się przez dropdown — nieczytelne przy wielu parametrach.
2. Brak możliwości ustawienia precyzji (liczby miejsc po przecinku) per produkt — pole `precision` w `parametry_analityczne` istnieje, ale nie jest aktywnie wykorzystywane.
3. Kalkulator miareczkowy zawsze używa `.toFixed(4)` niezależnie od parametru.
4. Wartości nie są zaokrąglane przy wprowadzaniu ani zapisie.

## Rozwiązanie

### 1. Baza danych

**ALTER TABLE `parametry_etapy`:** dodanie kolumny `precision INTEGER DEFAULT NULL`.

Kaskada rozwiązywania precyzji:
1. `parametry_etapy.precision` (per produkt) — najwyższy priorytet
2. `parametry_analityczne.precision` (globalna) — fallback
3. Domyślnie `2` — jeśli obie NULL

SQL resolve: `COALESCE(pe.precision, pa.precision, 2)`

**`build_parametry_lab()`** w `registry.py` — przy budowaniu pola, bierze resolved precision i wpisuje do JSON snapshotu `parametry_lab`. Nowe EBR dziedziczą tę wartość. Istniejące otwarte partie nie są zmieniane.

Globalna edycja precyzji — przez istniejący `PUT /api/parametry/<id>` (pole `precision`). Nie wymaga nowego UI.

### 2. Modal dodawania/zarządzania parametrami

**Trigger:** Przycisk przy sekcji "Analiza końcowa" w widoku fast_entry. Dostępny dla roli `laborant`.

**Zawartość — tabela:**

| Kolumna | Opis |
|---------|------|
| Checkbox | Zaznaczony = parametr przypisany do produktu |
| Nazwa | `label` z `parametry_analityczne` |
| Kod | `kod` z `parametry_analityczne` |
| Typ | bezpośredni / titracja / obliczeniowy / binarny |
| Jednostka | `jednostka` z `parametry_analityczne` |
| Precyzja | Edytowalny input (number). Domyślnie wyszarzony placeholder z wartością globalną. Po wpisaniu = override per produkt |
| Kolejność | Edytowalny input (number) |

**Filtrowanie:** Pole tekstowe u góry modala, filtruje po nazwie i kodzie w locie (JS, client-side).

**Zachowanie:**
- Odznaczenie checkboxa → `DELETE /api/parametry/etapy/<binding_id>`
- Zaznaczenie → `POST` tworzenie nowego bindingu z domyślnymi wartościami
- Zmiana precyzji → `PUT /api/parametry/etapy/<binding_id>` (wymaga rozszerzenia allowed fields o `precision`)
- Zmiana kolejności → `PUT /api/parametry/etapy/<binding_id>`

**Po zamknięciu modala:** Automatyczny rebuild `parametry_lab` dla aktywnego MBR tego produktu (POST `/api/parametry/rebuild-mbr`).

### 3. Auto-zaokrąglanie wartości

#### Frontend — formularz (fast_entry), na blur

Gdy operator wychodzi z pola input, JS:
1. Czyta `precision` z danych parametru (atrybut `data-precision` na inpucie, źródło: `parametry_lab` JSON).
2. Zaokrągla wartość: `parseFloat(val).toFixed(precision)`.
3. Wpisuje zaokrągloną wartość z powrotem do inputa.

Przykład: wpisano `12.456`, precision=1 → pole pokazuje `12.5`.

#### Frontend — kalkulator miareczkowy, przy zatwierdzaniu wyniku

Zmiana w `calculator.js`:
- Obecne: `.toFixed(4)` (hardcoded, linia ~684).
- Po zmianie: `.toFixed(precision)` — precision pobierane z `data-precision` pola docelowego.
- Wyświetlanie pośrednie (pojedyncze próbki: `.toFixed(3)`, statystyki RSD/RSM) — bez zmian, żeby laborant widział pełne dane przed zaokrągleniem.

#### Backend — przy zapisie

W `save_wyniki()` (`laborant/models.py`):
1. Pobiera resolved precision dla parametru (z `parametry_etapy` → `parametry_analityczne` → default 2).
2. `wartosc = round(wartosc, precision)` przed insertem do `ebr_wyniki`.
3. Walidacja limitów (`w_limicie`) odbywa się na zaokrąglonej wartości.

## Scope

- Dotyczy kontekstu `analiza_koncowa` (i analogicznie innych kontekstów korzystających z tego samego flow).
- Rola: `laborant` (modal, edycja precyzji per produkt).
- Globalna precyzja: edycja przez istniejący endpoint (admin/technolog).
- Wpływ na istniejące dane: brak — zmiany dotyczą tylko nowych partii (nowych EBR po rebuild MBR).

## Pliki do modyfikacji

| Plik | Zmiana |
|------|--------|
| `mbr/models.py` | ALTER TABLE `parametry_etapy` ADD `precision` |
| `mbr/parametry/routes.py` | Dodanie `precision` do allowed fields w PUT etapy; nowy endpoint POST tworzenia bindingu |
| `mbr/parametry/registry.py` | `build_parametry_lab()` — resolve precision z kaskady |
| `mbr/laborant/models.py` | `save_wyniki()` — round przed zapisem |
| `mbr/templates/laborant/fast_entry.html` | Przycisk otwierający modal; `data-precision` na inputach; blur handler |
| `mbr/static/calculator.js` | `.toFixed(precision)` zamiast `.toFixed(4)` przy zatwierdzaniu |
| Nowy: `mbr/templates/laborant/_parametry_modal.html` | Szablon modala z tabelą parametrów |
