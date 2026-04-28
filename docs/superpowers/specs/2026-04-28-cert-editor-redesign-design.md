# Cert Editor Redesign — Design Spec

**Data:** 2026-04-28
**Autor:** Tabaka Karol + Claude (brainstorming session)
**Scope:** `/admin/wzory-cert` — edytor szablonów świadectw jakości (admin)

## Problem

Obecny edytor (`mbr/templates/admin/wzory_cert.html`) ma trzy bolączki:

1. **Czytelność** — tabela parametrów w jednym wierszu próbuje zmieścić: drag-handle, Nazwa PL, Nazwa EN, Wymaganie, Metoda, Powiąż z pomiarem, Precyzja, Wynik opisowy, Delete. Długie pola (Wymaganie, Metoda — np. „PN-EN ISO 5661:2002 +Ap1:2016") są wizualnie ucinane, choć dane w polach są kompletne.

2. **Brak globalnego rejestru w UX** — dane globalne istnieją w `parametry_analityczne` (`label`, `name_en`, `method_code`), a edytor je „kradnie" przy wyborze kodu i zapisuje skopiowane wartości jako per-produkt nadpisanie w `parametry_cert.name_pl/name_en/method`. Efekt: zmiana w rejestrze nie propaguje się — admin musi ręcznie poprawiać każdy produkt.

3. **Surowy markup** — nazwy parametrów używają `_{D}` `^{20}` zamiast prawdziwych indeksów. Live preview działa pod inputem, ale samo wpisywanie wymaga znajomości składni LaTeX-podobnej. Niedostępne dla nietechnicznego usera.

## Decyzje projektowe

### 1. Semantyka: rejestr jest prawdą kanoniczną

`parametry_analityczne.label / name_en / method_code` to wartości globalne — to one są źródłem prawdy. `parametry_cert.name_pl / name_en / method` istnieją wyłącznie jako jawne nadpisania per produkt. **Pusta wartość (NULL) w `parametry_cert` = dziedziczenie z rejestru.**

Cert generator (`mbr/certs/generator.py` + `mbr/parametry/registry.py:get_cert_params`) już ma fallback: `r["cert_name_pl"] or r["label"]`. Backend renderingu nie wymaga zmian.

### 2. Layout: master-detail (lewy panel listy, prawy panel edycji)

Zakładka „Parametry świadectwa" w edytorze przechodzi na układ 280px : reszta:

**Lewy panel** — lista parametrów:
- Każda pozycja: drag-handle, **renderowana nazwa** parametru (sub/sup wyświetlone wizualnie, nie surowy `_{}^{}`), tag z kodem (np. `nD20`)
- „+ Dodaj parametr" na dole
- Aktywny parametr podświetlony (lewy border teal)

**Prawy panel** — edytor jednego parametru w siatce dwóch kolumn:

| Lewa kolumna (globalne — rejestr) | Prawa kolumna (per produkt — puste = dziedzicz) |
|---|---|
| Nazwa PL | Nazwa PL (override) |
| Nazwa EN | Nazwa EN (override) |
| Metoda | Metoda (override) |

Pola jedno-kolumnowe (zawsze per produkt, nie ma sensu globalnie):
- Wymaganie
- Precyzja
- Wynik opisowy (qualitative_result)
- Powiąż z pomiarem (parametr_id binding — read-only po utworzeniu, patrz sekcja 8)

Każdy override w prawej kolumnie ma obok ikonkę `⤺` (Reset do globalnego) — pojawia się tylko gdy w polu jest wartość. Klik czyści input → save jako NULL → pole pokaże wartość globalną z lewej kolumny po reload. Ręczne czyszczenie inputu też działa (oba mechanizmy zapisują NULL).

**Banner** nad lewą kolumną: pojawia się tylko gdy admin zmodyfikował co najmniej jedno pole w lewej kolumnie. Treść zależy od edytowanego pola (live count z nowego endpointu `/api/parametry/<id>/usage-impact`):

- Edycja **`label` (Nazwa PL)** → `⚠ Edytujesz rejestr. Świadectwa: N produktów. Również widoczne w: laboratorium, MBR, kalkulator.` (bo `label` jest używane wszędzie)
- Edycja **`name_en` lub `method_code`** → `⚠ Edytujesz rejestr. Świadectwa: N produktów.` (te pola są tylko cert-related)

Endpoint `/api/parametry/<id>/usage-impact` zwraca po jednym counterze per scope (cert, mbr-laborant), żeby frontend mógł wyrenderować odpowiedni banner.

### 3. Toolbar formatowania nad polami nazwy

Nad każdym inputem nazwy (PL i EN, w obu kolumnach):

```
[X²]  [X₂]  [↲]  |  [≤]  [≥]  [÷]  [°]
```

Klik wstawia odpowiedni token w pozycji kursora:
- `[X²]` → `^{}` (kursor w środku)
- `[X₂]` → `_{}`
- `[↲]` → `|` (manual line break — `mbr/certs/generator.py` już to obsługuje przez `<w:r><w:br/></w:r>`)
- `[≤] [≥] [÷] [°]` → bezpośrednio znak Unicode

Toolbar zawsze widoczny (nie on-focus) — pokazuje od razu możliwości adminowi nietechnicznemu.

Live preview pod każdym polem nazwy (już jest w kodzie, `updateRtPreview`) — bez zmian, renderuje wstawione tokeny.

### 4. Zapisywanie

Jeden przycisk `Zapisz wszystko` na dole edytora wywołuje **dwa typy endpointów sekwencyjnie**:

1. Jeśli są zmiany w lewej kolumnie (globalne) → N równoległych `PUT /api/parametry/<id>` (`Promise.all`), jeden per zmieniony parametr. Backend `UPDATE parametry_analityczne` + audit per parametr (`EVENT_PARAMETR_UPDATED` z `diff`).
2. Tylko gdy wszystkie z kroku 1 OK → `PUT /api/cert/config/product/<key>` z cert configiem (jak teraz). Backend `UPDATE parametry_cert` z NULL gdzie puste, audyt `EVENT_CERT_CONFIG_UPDATED`.

Jeśli którykolwiek z kroku 1 zwróci błąd, krok 2 się nie wykonuje. Worst case (część kroku 1 OK, krok 2 fail): admin widzi error, klika Save jeszcze raz — kroki idempotentne (UPDATE z tymi samymi wartościami no-op'em). Brak data corruption.

Status flash po sukcesie pokazuje rozbicie: `Zapisano: 3 globalne, 2 per produkt`.

### 5. Warianty

Wariantowe parametry w `parametry_cert` (gdy `variant_id = X`) to **dodatkowe parametry występujące tylko w danym wariancie** — nie są nadpisaniami bazowych parametrów (mają inne `parametr_id` niż base). Np. parametr av-on w wariancie LV.

Zakładka „Warianty" dostaje **dokładnie ten sam dwukolumnowy układ co zakładka Parametry świadectwa**:
- Lewa kolumna = wartości globalne z rejestru (`parametry_analityczne`)
- Prawa kolumna = nadpisanie wariantu (`parametry_cert` z `variant_id = X`)

Brak konceptu „wartości efektywnej bazy" — wariantowy parametr nie ma bazowego odpowiednika.

Z perspektywy edytora wariantów, edycja globalna w lewej kolumnie zachowuje się tak samo jak w bazowych parametrach: zmienia rejestr, propaguje wszędzie. Banner usage-impact pokazuje liczbę produktów (i wariantów) używających tego parametru.

### 6. Migracja istniejących nadpisań

Jednorazowy skrypt `scripts/migrate_cert_override_cleanup.py` (uruchamiany ręcznie, idempotentny):

- Iteruje przez wszystkie wiersze `parametry_cert` (zarówno bazowe `variant_id IS NULL` jak i wariantowe)
- Dla każdego pola (`name_pl`, `name_en`, `method`):
  - JOIN z `parametry_analityczne` po `parametr_id`
  - Porównanie z normalizacją: `strip()` + collapse wielokrotnych spacji do jednej (case-sensitive). Jeśli znormalizowana wartość override == znormalizowana wartość globalna (`label / name_en / method_code`) → `SET NULL`
  - Bez normalizacji: skrót typu „PN-EN" vs „pn-en" zostaje (case ma znaczenie w domenie)
- Loguje:
  - liczbę wierszy zaktualizowanych (per pole)
  - liczbę nadpisań pozostałych jako jawne (per produkt, per pole)
  - listę produktów z największą liczbą jawnych nadpisań (top 10) — do audytu

Po uruchomieniu skryptu: ~80–90% pól będzie pustych i wyświetli się w UI jako dziedziczone z rejestru. Pozostałe to faktyczne nadpisania per produkt — admin widzi je jasno.

Skrypt nie modyfikuje `parametry_analityczne`. Skrypt nie zmienia logiki rendering — cert generator już zwraca poprawną wartość (fallback `cert_name_pl or label`).

### 7. Backend — endpointy

- **Reużycie istniejącego `PUT /api/parametry/<int:param_id>`** — endpoint już akceptuje edycję `label`, `name_en`, `method_code` przez admina (sprawdzone w `mbr/parametry/routes.py:70-153`). Trzeba **dodać audit logging** za pomocą `log_event(EVENT_PARAMETR_UPDATED, ...)` z `diff_fields()` — endpoint obecnie nie zapisuje audytu.
- Frontend wysyła N równoległych PUT-ów (jeden per zmieniony parametr) gdy save zawiera zmiany w lewej kolumnie. Każdy PUT własna transakcja, własny event audytu.
- **Nowy endpoint `GET /api/parametry/<int:param_id>/usage-impact`** — zwraca:
  ```json
  {
    "cert_products_count": 8,
    "mbr_products_count": 12
  }
  ```
  - `cert_products_count` = `SELECT COUNT(DISTINCT produkt) FROM parametry_cert WHERE parametr_id=?`
  - `mbr_products_count` = `SELECT COUNT(DISTINCT produkt) FROM parametry_etapy WHERE parametr_id=?`
  Frontend używa do bannera (sekcja 3): cert count zawsze, mbr count tylko dla edycji `label`.
- **Modyfikacja `mbr/parametry/registry.py:get_cert_params` i `get_cert_variant_params`** — zwracają teraz **dwa zestawy pól**:
  - `name_pl_global / name_en_global / method_global` — z `parametry_analityczne` (zawsze obecne, mogą być empty string)
  - `name_pl_override / name_en_override / method_override` — z `parametry_cert`, raw (mogą być NULL)
  - Istniejące pola `name_pl / name_en / method` (efektywna wartość, fallback) **zostają zachowane** dla kompatybilności z `cert_master_template.docx` rendering pipeline.
- Endpoint `/api/cert/config/product/<key>` GET (`mbr/certs/routes.py`) zwraca nowe pola automatycznie (delegate'uje do `get_cert_params`/`get_cert_variant_params`).

### 8. Dodawanie nowego parametru do świadectwa + binding read-only

Klik „+ Dodaj parametr" w lewym panelu listy:
1. Modal z `<select>` listą kodów z `_availableCodes` (jak teraz, z grupowaniem „W MBR" / „Poza MBR")
2. Po wyborze kodu — nowy wiersz w `parametry_cert` z `parametr_id = X`, wszystkie pola override = NULL
3. Edytor pokazuje od razu wartości z rejestru w lewej kolumnie, prawa kolumna pusta (`puste = dziedzicz`)
4. Admin może od razu edytować wymaganie/precyzję/wynik opisowy (per produkt) lub wpisać override w prawej kolumnie nazwy/metody

**Binding read-only po utworzeniu**: pole „Powiąż z pomiarem" (parametr_id) jest edytowalne **tylko podczas tworzenia** wiersza. Po zapisie staje się disabled. Żeby zmienić binding admin musi usunąć parametr i dodać nowy z innym kodem. To zapobiega niespójnościom (overrides wyrosły dla jednego paramu, po rebindingu odnoszą się do innego).

Dodanie zupełnie nowego parametru (nowy `kod` w rejestrze) nie odbywa się w edytorze cert — to flow w `/admin/parametry`.

### 9. Lewy panel listy — szczegóły

**Search/filter** — pole tekstowe na górze lewego panelu (`<input placeholder="Filtruj parametry...">`). Filtruje listę po prefiksie matching `kod` LUB substring matching renderowanej nazwy (case-insensitive). Bez filtra → pełna lista. Tylko frontend, brak nowego endpointu.

**Drag-and-drop** — drag-handle przy każdej pozycji listy. Reorder zmienia `kolejnosc` w `parametry_cert`. Drag nie zmienia aktywnej selekcji ani nie commituje od razu — stan `kolejnosc` trzymany w JS-state, persisted na `Save Wszystko`. Wizualny feedback: dragowany element semi-transparent (jak teraz w tabeli).

**Aktywna selekcja + dirty state** — kliknięcie innego parametru w liście:
- Bieżące edycje w prawym panelu są **zachowane w JS-state** (`_currentProduct.parameters[i]` zaktualizowane in-memory)
- Prawy panel renderuje wybrany parametr; przełączenie z powrotem pokazuje wcześniej wpisane edycje
- Jeden globalny indykator dirty (`*` w tytule, podświetlony Save) — pokazuje że są jakieś niezapisane zmiany w którymkolwiek parametrze
- Per-parametr w lewym liście dot kropka indykuje że ten konkretny ma niezapisane zmiany (drobny wskaźnik wizualny)
- Brak per-param confirm — jedna `Save Wszystko` commituje wszystkie zmiany na raz, jak teraz

### 10. Audyt zmian rejestru

Każde wywołanie `PUT /api/parametry/<id>` przez admina emituje audyt:
- `event_type`: `EVENT_PARAMETR_UPDATED` (= `"parametr.updated"`, już zdefiniowane w `mbr/shared/audit.py`)
- `entity_type`: `"parametr"`
- `entity_id`: parametr_id
- `entity_label`: kod (np. `"nD20"`)
- `diff`: wynik `diff_fields(old_row, new_row, ["label", "name_en", "method_code"])` — zwraca listę `[{"pole": ..., "stara": ..., "nowa": ...}]` tylko dla pól które się zmieniły
- Jeśli `diff` jest puste → endpoint zwraca OK ale nie emituje eventu (zmiana no-op)

Audyt widoczny w `/admin/audit` panel jak inne eventy.

### 11. Poza scope (zostaje bez zmian)

- Modal „Ustawienia globalne świadectw" (font, title/product/body sizes — `cert_settings` table)
- Panel aliasów cert (`/admin/wzory-cert` sekcja „Aliasy cert")
- Cert generator backend (`mbr/certs/generator.py`) — fallback semantyka już prawidłowa
- Lista produktów + zakładki Produkt / Historia / Podgląd PDF
- Tabela `cert_settings` i jej UI
- Per-produkt opcje wariantów (flagi, av-on, opinions overrides)

## Architektura — ścieżka rozwoju

### PR1 — Backend
- Endpoint `PUT /api/parametry/<id>/registry`
- Endpoint `GET /api/parametry/<id>/usage-impact`
- Modyfikacja `get_cert_params` / `get_cert_variant_params` (dwa zestawy pól)
- Audyt `parametry.registry.updated` w `mbr/admin/audit.py`
- Testy:
  - `tests/test_parametry_registry_edit.py` — PUT registry zmienia globalne wartości, audytowane
  - `tests/test_cert_params_dual_field.py` — get_cert_params zwraca global + override osobno
  - `tests/test_usage_impact.py` — count produktów + nadpisań

### PR2 — Frontend (Parametry)
- Master-detail layout w zakładce „Parametry świadectwa" (`mbr/templates/admin/wzory_cert.html`)
- Dwukolumnowy edytor (lewa: globalne, prawa: per produkt)
- Toolbar formatowania (X² X₂ ↲ ≤ ≥ ÷ °) nad polami nazwy
- Banner usage-impact gdy lewa kolumna zmieniona
- `Save` rozdziela zmiany do dwóch endpointów (registry + cert config)
- Live preview z istniejącym `_rtHtml` / `updateRtPreview`

### PR3 — Frontend (Warianty)
- Ten sam układ master-detail w zakładce „Warianty"
- Lewa kolumna = wartość efektywna bazy (read-only z tagiem `[rejestr]` lub `[produkt]`)
- Prawa kolumna = nadpisanie wariantu
- Link „edytuj globalnie/produktowo" przekierowuje do bazowego edytora

### PR4 — Migracja produkcyjna
- Skrypt `scripts/migrate_cert_override_cleanup.py`
- Smoke test na kopii bazy
- Uruchomienie na produkcji + log do audytu
- Krótka dokumentacja w `docs/migrations/2026-04-cert-override-cleanup.md`

## Akceptacja

- [ ] Edycja `label` w rejestrze (np. zmiana „Współczynnik załamania" na inną nazwę) propaguje się do wszystkich świadectw używających tego parametru bez ręcznej edycji każdego produktu
- [ ] Wymaganie i Metoda nigdy nie są ucinane wizualnie w edytorze
- [ ] Nazwy parametrów wyświetlają się z renderowanymi indeksami (n<sub>D</sub><sup>20</sup>) w liście parametrów po lewej i w nagłówku panelu edycji
- [ ] Przyciski sub/sup wstawiają tokeny `_{}` `^{}` w pozycji kursora bez konieczności pisania ich ręcznie
- [ ] Banner usage-impact pokazuje poprawną liczbę produktów po edycji wartości globalnej
- [ ] Po migracji `parametry_cert` ma głównie NULL-e w name_pl/name_en/method (z wyjątkiem faktycznych jawnych nadpisań); cert generator generuje identyczne PDFy jak przed migracją
- [ ] Warianty pokazują efektywną wartość bazy w lewej kolumnie i nadpisanie wariantu w prawej
- [ ] Audyt rejestruje każdą edycję rejestru jako `parametry.registry.updated`
