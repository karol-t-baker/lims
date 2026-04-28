# Parametry Editor — Rejestr Redesign Design Spec

**Data:** 2026-04-28
**Autor:** Tabaka Karol + Claude (brainstorming session)
**Scope:** `/admin/parametry` — zakładka **Rejestr** (admin-only, globalne definicje parametrów)

## Problem

Obecny edytor parametrów (`mbr/templates/parametry_editor.html`) ma trzy zakładki: **Etapy**, **Rejestr**, **Produkty**. Zakładka **Rejestr** używa 10-kolumnowej tabeli z auto-save-on-blur na każdym polu. Bolączki:

1. **Czytelność** — 10 kolumn (Kod, Label PL, Name EN, Skrót, Typ, Grupa, Metoda, Jednostka, Precyzja, Status) walczy o miejsce. Długie pola (Label PL, Method) ucinane wizualnie.
2. **Brak cross-cutting view** — admin nie widzi „w jakich produktach/etapach jest używany ten parametr". Decyzje typu „czy mogę usunąć" / „co się stanie jak zmienię nazwę" są ślepe.
3. **`format` (precyzja na cert) niezsynchronizowany z rejestrem** — `parametry_analityczne.precision` to globalny default; `parametry_cert.format` to per-produkt cert override; przy tworzeniu wiersza w cert editorze precyzja jest **kopiowana** z rejestru ale potem nie propaguje. Ten sam pattern co `name_pl/name_en/method` przed Phase A redesignu cert editora — jest do tego samego rozwiązania.
4. **Konfiguracja typu** — pola specyficzne dla typu (`titracja` ma factor, `jakosciowy` ma opisowe_wartosci) ukryte w expand-rows, łatwe do przeoczenia.

## Decyzje projektowe

### 1. Layout master-detail (jak cert editor)

Zakładka **Rejestr** przechodzi z tabeli na układ 280px : reszta:

**Lewy panel — lista parametrów:**
- Pole filtru tekstowego (filtruje po `kod` + `label`, case-insensitive)
- Pillsy filtra typu nad listą: `[Wszystkie] [Bezpośredni] [Titracja] [Obliczeniowy] [Jakościowy] [Średnia]` — multi-select toggle. Semantyka:
  - Brak zaznaczonych pillsów = pokaż wszystkie (implicit „all"). `[Wszystkie]` to fast-path reset (klik czyści wszystkie inne pillsy).
  - Aktywny parametr w detail panelu zawsze widoczny w liście (z visual marker `opacity: .7` jeśli nie pasuje do filtru) — żeby admin nie zgubił selekcji
- Lista parametrów posortowana **alfabetycznie po `kod`** (case-insensitive ze względu na uppercase outlier `barwa_I2`), każda pozycja:
  - Renderowana nazwa (`label` z sub/sup) — `_rtHtml`
  - Kod jako mono pillsa
  - Małe etykiety typu i grupy: `[titracja] [zewn]` (etykieta typu kolorowana subtelnie wg typu, etykieta grupy `lab`/`zewn` neutralna)
- Aktywny parametr — gradient teal-bg + inset shadow (jak w cert editor)
- „+ Dodaj parametr" na dole listy → otwiera modal (sekcja 5)

**Prawy panel — detail editor:**
Sekcje pionowo (single column), każda z subtelnym dividerem.

### 2. Sekcje detail panelu

#### Tożsamość
- `Kod` — mono input, **read-only po utworzeniu** (notka „read-only po utworzeniu — przemyśl dobrze przy create"). Read-only chroni stabilność audytów (entity_label = kod, ale historyczne logi mają stary kod jeśli kod zmieni się).
- `Label PL` (`label`) — text input z toolbar formatowania nad nim (X² X₂ ↲ ≤ ≥ ÷ °) + live preview poniżej (jak w cert editor)
- `Label EN` (`name_en`) — text input z toolbar + preview
- `Skrót` (`skrot`) — krótki alias

#### Klasyfikacja
- `Typ` — dropdown (5 opcji). Zmiana typu **dynamicznie aktualizuje sekcję „Konfiguracja typu"**. Guard już istnieje: zmiana typu z historycznymi `ebr_wyniki` zwraca 409 (z wyjątkiem safe swap `bezposredni ↔ srednia`).
- `Grupa` — toggle `lab` / `zewn`
- `Aktywny` — toggle on/off

#### Pomiar
- `Jednostka` (`jednostka`) — text input + toolbar `≤ ≥ ÷ °` (np. „mm²/s", „mg KOH/g")
- `Precyzja` (`precision`) — number 0-6
- `Metoda (kod)` (`method_code`) — text input + toolbar `≤ ≥ ÷ °`

#### Konfiguracja typu (dynamic — zależnie od `typ`)
- `bezposredni` → notka „Brak dodatkowej konfiguracji — wynik wpisywany ręcznie"
- `srednia` → notka „Brak dodatkowej konfiguracji — UI laboranta liczy średnią z 2 pomiarów" (typ nie ma własnych pól, różni się tylko widgetem laboranta)
- `titracja` → 3 pola: `metoda_nazwa`, `metoda_formula`, `metoda_factor` (number)
- `obliczeniowy` → `formula` (textarea, wsparcie tokenów `{{kod}}` — autocomplete z istniejących kodów *opcjonalnie*, MVP: free text)
- `jakosciowy` → editor `opisowe_wartosci`:
  - Lista chip-ów z wartościami opisowymi
  - Klik chipa → inline edit (input zastępuje tekst, blur zapisuje, ESC anuluje)
  - Klik `×` na chipie → usuwa (minimum 1 wartość — przycisk × disabled gdy chip jest ostatni)
  - Drag-and-drop reorder chip-ów — kolejność = kolejność opcji w dropdown na cert
  - Pole `+ Dodaj wartość` na końcu listy (input + Enter dodaje + clear)
  - Walidacja: minimum 1 wartość non-empty, brak duplikatów (case-sensitive trim).

#### Powiązania (accordion read-only)
- `▼ Świadectwa: N produktów` — rozwija listę chip-ów produktów (read-only, no link). Pokazuje admin'owi gdzie parametr jest używany — informacja do decyzji „czy mogę zmienić nazwę / deaktywować".
- `▼ Etapy MBR: M produktów × K bindings` — rozwija listę grupowaną produkt → etapy (read-only chip-y).
- Brak URL preselect / nawigacji między edytorami — admin świadomie otwiera `/admin/wzory-cert` lub Etapy tab gdy chce edytować w innym kontekście. Edycja w Rejestrze zmienia globalnie wszędzie; edycja `*_global` w cert editor pisze do tego samego rejestru — oba edytory są symetryczne, nie ma „preferowanego punktu wejścia".
- Dane pochodzą z rozszerzenia istniejącego `/api/parametry/<id>/usage-impact` (sekcja 6 — Backend).

#### Banner usage-impact (jak cert editor)
Pojawia się **tylko** gdy admin zmodyfikował co najmniej jedno z **4 pól z cross-editor scope**: `label`, `name_en`, `method_code`, `precision`. Pozostałe pola (`skrot`, `typ`, `grupa`, `aktywny`, `formula`, `metoda_*`, `jednostka`, `opisowe_wartosci`) zapisują się normalnie bez bannera — są albo dyskretne (skrot, jednostka — głównie display label w laborant UI), albo strukturalne z własnym guard'em w backend (typ z 409 dla historical data), albo categorization-only (grupa, aktywny).

Field-specific message:
- `label` → `⚠ Edytujesz rejestr. Świadectwa: N produktów. Również widoczne w: laboratorium, MBR, kalkulator (M produktów).`
- `name_en` lub `method_code` → `⚠ Edytujesz rejestr. Świadectwa: N produktów.`
- `precision` → `⚠ Edytujesz rejestr. Świadectwa: N produktów + MBR: M produktów.` (`precision` ma scope cert + MBR przez COALESCE w `parametry_etapy`)

### 3. Zapis
**Save Wszystko** na dole detail panelu — dirty-tracking, banner pojawia się przy zmianach pól rejestru-globalnych, jeden klik commituje całość. Backend: istniejący `PUT /api/parametry/<id>` już akceptuje wszystkie pola (label, name_en, method_code, skrot, typ, grupa, aktywny, jednostka, precision, formula, metoda_*, opisowe_wartosci) — żadne nowe endpointy nie są wymagane. Audit już dodany w cert editor Phase A (`EVENT_PARAMETR_UPDATED`).

Status flash: `Zapisano parametr nD20`.

### 4. Add Parameter — modal
Klik „+ Dodaj parametr" → modal z minimalnymi polami:
- `Kod` — wymagane, unique (case-sensitive), mono input
- `Label PL` — wymagane, non-empty
- `Typ` — dropdown (5 opcji), domyślnie `bezposredni`
Plus opcjonalnie: `Grupa` (default `lab`), `Skrót`.

Po Dodaj → POST do istniejącego `POST /api/parametry`, response zawiera `id`. Frontend dodaje do listy + selectuje w detail panelu (z resztą pól pustych do uzupełnienia).

Walidacje frontend:
- Kod: regex `^[a-zA-Z0-9_]+$` (litery dużej i małej + cyfra + podkreślnik), maks 30 znaków. Uppercase dozwolony bo skróty chemiczne (`nD`, `pH`, `CO2`, `H2O`) używają uppercase celowo, plus historycznie istnieje `barwa_I2` w danych.
- Label: trim non-empty, maks 200 znaków
- Konflikt kodu: walidacja po stronie serwera (409 → flash error)

### 5. Deaktywacja (soft delete) — z impact info

Hard delete jest ryzykowny: regeneracja cert dla historycznych szarży faila, gdy `parametry_cert` jest pusta. Schema już ma flag `aktywny` — używamy soft delete.

Klik „Deaktywuj parametr" w detail header → modal:
- Preflight: GET `/api/parametry/<id>/usage-impact` — pobiera count cert + MBR products
- Treść modala: `Deaktywować parametr nD20? Parametr jest używany w 8 świadectwach + 12 produktach MBR. Po deaktywacji: ✓ historyczne szarże nadal generują się poprawnie, ✓ nowe konfiguracje nie będą widziały tego parametru, ✓ deaktywacja jest odwracalna (Reaktywuj).` + zwykły OK/Anuluj
- Klik OK → PUT `/api/parametry/<id>` z `{aktywny: 0}` (już istniejący endpoint, audit `parametr.updated`)
- Po deaktywacji: parametr ZNIKA z lewej listy (lista pokazuje tylko `aktywny=1`), ale szczegóły dostępne przez „Pokaż nieaktywne" toggle nad listą (admin tylko)

**Reaktywacja**: toggle „Pokaż nieaktywne" w lewym panelu → lista zawiera nieaktywne (z visual marker — opacity .5 + tag `[deakt.]`). Klik → detail panel pokazuje parametr z disabled fields (read-only) + przycisk **„Reaktywuj"** zamiast „Deaktywuj". Klik Reaktywuj → PUT `aktywny=1`, parametr wraca do normalnej listy.

**Hard delete** (DROP z DB) **poza scope** — gdy admin naprawdę chce przeczyścić, robi to przez SQL ręcznie. W praktyce 99% przypadków to deaktywacja.

### 6. Backend changes

#### Soft delete przez istniejący `PUT /api/parametry/<int:param_id>`
Wybraliśmy soft delete (toggle `aktywny`) zamiast hard delete (sekcja 5) — endpoint **nie wymaga zmian**. Frontend wysyła `{aktywny: 0}` lub `{aktywny: 1}`, audit `EVENT_PARAMETR_UPDATED` z diff zawiera zmianę. Wymóg: w `api_parametry_update` rozszerzyć `diff_fields()` o klucz `aktywny`, żeby toggle były audytowane (obecnie audit tylko dla label/name_en/method_code).

Hard delete `/api/parametry/<id>` **NIE jest dodawany w tym scope** — operacja czyszczenia robiona przez SQL ręcznie w razie potrzeby.

#### Rozszerzenie `GET /api/parametry/<int:param_id>/usage-impact`
Obecna response:
```json
{ "cert_products_count": 8, "mbr_products_count": 12 }
```

Rozszerzona response (dodaje listy szczegółowe — frontend potrzebuje do accordionu Powiązania):
```json
{
  "cert_products_count": 8,
  "cert_products": [
    {"key": "Chegina_K40GLOL", "display_name": "Chegina K40 GLOL"},
    ...
  ],
  "mbr_products_count": 12,
  "mbr_bindings_count": 18,
  "mbr_products": [
    {"key": "Chegina_K40GLOL", "stages": ["analiza_koncowa", "sulfonowanie"]},
    ...
  ]
}
```

Dodanie list per-produkt do response. Frontend renderuje counts dla bannera + pełne listy dla accordionu.

#### Format dual-field — extension cert editor (sekcja 7)

Wymaga modyfikacji `get_cert_params` / `get_cert_variant_params` z dodaniem `format_global` i `format_override` analogicznie do `name_pl_global/override`. Plus extension migracji cleanup (sekcja 9).

### 7. Format dual-field — extension cert editor

Spójność z `name_pl/name_en/method` dual-field:

**Backend:**
- `get_cert_params` / `get_cert_variant_params` zwracają nowe pola:
  - `format_global` ← `parametry_analityczne.precision` (zawsze obecne, fallback `""` gdy NULL)
  - `format_override` ← `parametry_cert.format` raw (None = inherit)
  - `format` (legacy effective) — bez zmian: `pc.format or pa.precision or "1"`
- `api_cert_config_product_get` w `mbr/certs/routes.py` dodaje 2 nowe pola do response per parametr (analogicznie do `*_global`/`*_override` w A4).

**Frontend cert editor:**
- `_dualRow` w `wzory_cert.html` — dodać 4-ty wiersz dla `format`. Widget: dropdown z labelami pokazującymi przykład wartości (`0 (123)` / `1 (123,4)` / `2 (123,45)` / `3 (123,456)` / `4 (123,4567)` / `5 (123,45678)` / `6 (123,456789)`) — self-documenting dla nietechnicznego usera. Zastąpić istniejący `_fmtOptions` helper (plain numeric labels) nową wersją lub stworzyć `_precisionOptionsWithExamples` — używać tego samego helpera w cert editor + rejestr editor.
- Reset-to-global ⤺ jak inne override pola.
- `_buildCertConfigPayload` — dodać `format_override` analogicznie do innych override fields.
- Server PUT `/api/cert/config/product/<key>` już obsługuje pole `format` w payloadzie (per `mbr/certs/routes.py:666`) — frontend tylko zmienia z effective na raw override.

**Banner registry-edit** (Rejestr) — przy edycji `precision` w Rejestrze pokazuje cert + MBR scope (per sekcja 2 banner spec). Cert editor Banner przy edycji `format_override` pokazuje tylko per-produkt scope (override zostaje lokalny — bez wpływu na innych).

### 8. Frontend — szczegóły implementacji

**Plik główny:** `mbr/templates/parametry_editor.html` — sekcja **Rejestr** zostaje przepisana, sekcje Etapy + Produkty zostają nietknięte.

**Kompozycja CSS:**
- Reuse istniejących CSS variables (`--teal`, `--surface-alt`, `--border`, etc.) — zgodnie z polish-em po cert editor
- Reuse master-detail CSS classes (`.wc-md`, `.wc-md-list`, `.wc-md-detail`, `.wc-md-toolbar`, `.wc-md-banner`) — z prefixem przemianowanym na `.pe-md-*` żeby uniknąć konfliktów (lub trzymać `wc-md` jeśli style są identyczne)

**JS state:**
- `_paramsList` — wszystkie parametry (cached po pierwszym fetch)
- `_selectedParamId` — id aktualnie wybranego
- `_paramFilter` — text filter
- `_typFilter` — set aktywnych typów (multi-select pillsy)
- `_paramDirty` — czy są niezapisane edycje
- `_originalParam` — snapshot dla detection registry-impacting changes (banner)

### 9. Migracja istniejących nadpisań `format`

Skrypt `scripts/migrate_cert_override_cleanup.py` (już istnieje dla `name_pl/name_en/method`) — **rozszerzyć** o 4-ty pole:

- Dla każdego wiersza `parametry_cert.format`:
  - JOIN z `parametry_analityczne.precision`
  - Konwersja `format` (string TEXT w schema) na int (np. `"4"` → `4`); jeśli string non-numeric (np. malformed data) → skip, nie tykaj
  - Konwersja `precision` (INTEGER w schema) na int; jeśli NULL → traktuj jako 2 (legacy default w `get_parametry_for_kontekst` — `COALESCE(pe.precision, pa.precision, 2)`)
  - Jeśli zint(format) == zint(precision) → `SET format = NULL` (= dziedzicz)
- Domyślny `format` w schema to `"1"` przy INSERT bez podania (per `mbr/certs/routes.py:666` — `p.get("format", "1")`). Jeśli `precision = 1` w rejestrze i `format = "1"` w cert → to legitymny match (oba mówią „1"), NULL-uje się jako pseudo-override. Nie próbujemy zgadywać intencji — zaufaj danym.
- Dodać 2 testy do `tests/test_migrate_cert_override_cleanup.py`:
  - format match → NULL (np. `format="4"`, `precision=4` → NULL)
  - format mismatch → preserved (np. `format="2"`, `precision=4` → zostaje)

### 10. Audit

Reuse istniejących eventów:
- `EVENT_PARAMETR_UPDATED` (`parametr.updated`) — już emitowane przez `PUT /api/parametry/<id>` (Phase A1). Rozszerzyć `diff_fields()` keys w endpoincie o `precision` i `aktywny` (obecnie tylko `label/name_en/method_code`). Toggle aktywności wpadnie tam jako audit z diff `{pole: 'aktywny', stara: 1, nowa: 0}`.
- `EVENT_PARAMETR_CREATED` (`parametr.created`) — wymaga audit dodania w `POST /api/parametry` (obecnie nie emituje audytu)
- `EVENT_PARAMETR_DELETED` (`parametr.deleted`) — **nie używany** w tym scope (soft delete idzie przez UPDATE).

### 11. Out of scope

- Zakładka **Etapy** (osobny redesign — wymaga cross-cutting widoku, więcej design-thinking)
- Zakładka **Produkty** (rzadko edytowane, tabelaryczny układ wystarcza)
- Live preview formuły dla `obliczeniowy` (wymaga ewaluacji bezpiecznej — osobny ticket)
- Autocomplete tokenów `{{kod}}` w textarea formuły (nice-to-have, MVP: free text)
- Drag-and-drop reorder w liście (sortowanie alfabetyczne po kodzie wystarczy)
- Bulk operations (select multi + delete/edit) — pojedyncze edycje wystarczają

## Architektura — ścieżka rozwoju

### PR1 — Backend rozszerzenia
- Rozszerzenie `GET /api/parametry/<id>/usage-impact` o listy per-produkt
- Nowy `DELETE /api/parametry/<id>` z impact preflight
- Audit `EVENT_PARAMETR_CREATED` w `POST /api/parametry`
- `get_cert_params` / `get_cert_variant_params` zwracają `format_global` / `format_override`
- `api_cert_config_product_get` przepuszcza nowe pola
- Testy

### PR2 — Frontend Rejestr master-detail
- Replace tabular Rejestr z master-detail layout
- Lewy panel: filtr + pillsy + lista
- Prawy panel: sekcje (Tożsamość, Klasyfikacja, Pomiar, Konfiguracja typu, Powiązania) + toolbar formatowania + banner
- Save flow: dirty tracking + Save Wszystko
- Modal Add Parameter
- Modal Delete z impact warning + typed-confirm

### PR3 — Cert editor format dual-field
- Dodanie 4-tego dual-row w cert editor (`format`)
- Reset-to-global dla format
- Banner uwzględnia `format_override` jako per-produkt (ale `precision` global przez Rejestr → cert + MBR scope)
- Frontend payload: dodać `format_override`

### PR4 — Migration extension
- Rozszerzenie `migrate_cert_override_cleanup.py` o `format`
- Test dla `format` scenarios
- Update runbook

## Akceptacja

- [ ] Zakładka Rejestr wyświetla parametry w master-detail layout (lewy filtr + lista, prawy detail editor)
- [ ] Filtr tekstowy + pillsy typu działają niezależnie i razem
- [ ] Edycja `label`, `name_en`, `method_code`, `precision` pokazuje banner field-specific z liczbą produktów dotkniętych zmianą
- [ ] Sekcja „Konfiguracja typu" dynamicznie pokazuje pola dla wybranego typu
- [ ] Sekcja „Powiązania" rozwijana pokazuje listy produktów (klikalne chip-y → otwierają cert editor / etapy z preselekcją)
- [ ] Save Wszystko commituje atomowo, audit emitowany
- [ ] Add Parameter modal tworzy parametr z wymaganymi polami; po utworzeniu admin ląduje w detail panelu
- [ ] Delete z preflight pokazuje impact, wymaga wpisania `usuń`, emit audit event
- [ ] Cert editor pokazuje `format` jako 4-ty dual-row (globalne | per produkt) z reset-to-global
- [ ] Migracja cleanup zNULLuje `format` overrides równe `precision` rejestru
- [ ] Edycja `precision` w Rejestrze propaguje do nowo generowanych świadectw produktów bez override
- [ ] Wszystkie istniejące testy parametry/cert nadal zielone
- [ ] Polish charset wszędzie (ąćęłńóśźż) renderowany poprawnie w toolbarze i preview
