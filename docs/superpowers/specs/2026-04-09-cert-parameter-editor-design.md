# Edytor wzorów świadectw — Design Spec

**Data:** 2026-04-09
**Status:** Zatwierdzony

## Cel

Pełny edytor CRUD do zarządzania wzorami świadectw (certyfikatów jakości) dla produktów. Pozwala konfigurować globalny wzór parametrów produktu, warianty z nakładkami (overrides), oraz podglądać efekt jako PDF w czasie rzeczywistym.

## Lokalizacja w aplikacji

- Osobna podstrona `/admin/wzory-cert` w panelu admina (link z `admin/panel.html`, analogicznie do "Zbiorniki magazynowe")
- Dostępna tylko dla roli admin (`@role_required`)
- Template: `mbr/templates/admin/wzory_cert.html`

## Layout

Dwie kolumny:
- **Lewa (~55%)** — CRUD: lista produktów → edycja produktu (parametry + warianty)
- **Prawa (~45%)** — podgląd PDF w `<iframe>` z przyciskiem "Odśwież" i selectem wariantu

## Lewa kolumna — widok listy produktów

Karty produktów z informacjami:
- `display_name`
- Ilość parametrów
- Ilość wariantów
- Przycisk edycji (przejście do widoku edycji)
- Przycisk usunięcia (z potwierdzeniem)

Przycisk "Nowy produkt" nad listą.

## Lewa kolumna — widok edycji produktu

### A) Nagłówek produktu (edytowalne pola)

| Pole | Typ | Wymagane |
|------|-----|----------|
| `display_name` | text | tak |
| `spec_number` | text | nie |
| `cas_number` | text | nie |
| `expiry_months` | number (default 12) | tak |
| `opinion_pl` | text | nie |
| `opinion_en` | text | nie |

Klucz produktu generowany z `display_name`: spacje → `_`.

### B) Tabela parametrów (globalny wzór)

Edytowalna tabela, każdy wiersz:

| Pole | Typ | Opis |
|------|-----|------|
| `id` | text (auto) | Unikalny identyfikator, slugify z `name_en` (lowercase, spacje → `_`), suffix `_2` przy duplikacie |
| `name_pl` | text | Nazwa PL (wymagane) |
| `name_en` | text | Nazwa EN (wymagane) |
| `requirement` | text | Wymaganie np. "max 150" (wymagane) |
| `method` | text | Metoda badawcza np. "L928" |
| `data_field` | select | Kod z `parametry_analityczne` (null dla jakościowych) |
| `format` | select | Ilość miejsc po przecinku: "0", "1", "2", "3" |
| `qualitative_result` | text | Stała wartość jakościowa np. "zgodny /right" |

Funkcje:
- **Drag-to-reorder** — kolejność = kolejność na świadectwie
- **Dodaj parametr** — dwa tryby: "analityczny" (wybór kodu z DB) lub "jakościowy" (ręczne `qualitative_result`)
- **Usuń parametr** — przycisk per wiersz

### C) Sekcja wariantów

Lista wariantów jako karty/accordiony pod parametrami. Każdy wariant:

**Pola edytowalne:**
- `id` — identyfikator (np. "base", "loreal")
- `label` — nazwa wyświetlana (np. "Chegina K40GLOL — Loreal MB")

**Flagi (checkboxy):**
- `has_rspo`
- `has_order_number`
- `has_certificate_number`
- `has_avon_code`
- `has_avon_name`

**Overrides (puste = dziedzicz z bazowego):**
- `spec_number`
- `opinion_pl`
- `opinion_en`

**Nakładka parametrów:**
- Lista bazowych parametrów z checkboxami "usuń z tego wariantu" → mapuje na `remove_parameters`
- Przycisk "dodaj parametr tylko do tego wariantu" → mapuje na `add_parameters`

**CRUD wariantów:**
- Przycisk "Dodaj wariant"
- Przycisk "Usuń wariant" per karta

### Zapis

Jeden przycisk "Zapisz" na dole lewej kolumny. PUT do API, zapisuje cały obiekt produktu do `cert_config.json`.

## Prawa kolumna — podgląd PDF

### Górny pasek
- Select "Wariant do podglądu" — lista wariantów aktualnego produktu
- Przycisk "Odśwież podgląd"

### Podgląd
- `<iframe>` wyświetlający PDF z endpointu `/api/cert/preview`
- Endpoint POST — przyjmuje aktualny stan edytora jako JSON, generuje PDF przez docxtpl + Gotenberg z danymi testowymi

### Dane testowe (generowane serwerowo)
- `nr_partii`: "1/2026"
- `dt_start`: data dzisiejsza
- Parametry z `data_field`: przykładowa wartość liczbowa (np. "12,34")
- Parametry jakościowe: ich `qualitative_result`
- `wystawil`: "Podgląd"

### Stany UI
- Przed pierwszym odświeżeniem: placeholder "Kliknij Odśwież aby wygenerować podgląd"
- Ładowanie: spinner
- Błąd Gotenberg: komunikat z treścią błędu

## Backend API

Wszystkie endpointy w `certs/routes.py`, dekorator `@role_required("admin")`.

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/api/cert/config/products` | GET | Lista produktów (key, display_name, params count, variants count) |
| `/api/cert/config/product/<key>` | GET | Pełne dane produktu |
| `/api/cert/config/product/<key>` | PUT | Zapis całego produktu (parametry + warianty + overrides) |
| `/api/cert/config/product` | POST | Nowy produkt (generuje key z display_name) |
| `/api/cert/config/product/<key>` | DELETE | Usunięcie produktu |
| `/api/cert/config/preview` | POST | Generuj PDF podgląd z danych testowych |
| `/api/cert/config/codes` | GET | Lista kodów z `parametry_analityczne` (dla selecta data_field) |

Istniejące endpointy `/api/cert/config/parameters` GET/PUT — deprecated, zastąpione przez nowe.

### Zapis do cert_config.json

PUT `/api/cert/config/product/<key>` nadpisuje cały obiekt produktu w pliku JSON. Walidacja:
- `display_name` — niepusty, unikalny
- Parametry: unikalne `id`, wymagane `name_pl` + `name_en` + `requirement`
- Warianty: unikalne `id`, wymagane `label`
- `remove_parameters` — musi referować istniejące `id` z bazowych parametrów

### Usuwanie produktu

- Confirm dialog w przeglądarce
- Serwer sprawdza czy istnieją wydane świadectwa w tabeli `swiadectwa` — jeśli tak, ostrzeżenie ale pozwalamy (dane archiwalne mają `data_json` do regeneracji)

## Dodawanie nowego produktu

- Formularz: `display_name` (wymagane), `spec_number`, `cas_number`, `expiry_months` (default 12), `opinion_pl`, `opinion_en`
- Key generowany automatycznie: spacje → `_`
- Produkt startuje z pustą listą parametrów i jednym wariantem `{"id": "base", "label": "<display_name>", "flags": []}`

## Technologia

- **Frontend:** Vanilla JS (spójne z resztą admin panelu), Jinja2 template
- **Styl:** Klasy `adm-*` z istniejącego panelu admina (rozbudowa CSS)
- **Drag-to-reorder:** Natywny HTML5 Drag & Drop API (bez bibliotek)
- **PDF podgląd:** iframe z blob URL
- **Backend:** Flask, zapis do `cert_config.json`

## Poza zakresem

- Edycja `company`/`footer`/`rspo_number` w cert_config.json (globalne, rzadko zmieniane)
- Migracja danych z `mappings.py` (legacy, osobne zadanie)
- Edycja szablonu .docx (`cert_master_template.docx`)
