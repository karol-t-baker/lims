# Centralizacja parametrów analitycznych — Design Spec

**Data:** 2026-04-09
**Status:** Zatwierdzony

## Cel

Jedno centralne miejsce do zarządzania parametrami analitycznymi (globalny rejestr + bindingi do etapów + bindingi do świadectw). Cała aplikacja czerpie dane z tego jednego źródła. Eliminacja duplikacji między `cert_config.json` a tabelami DB.

## Kontekst problemu

Parametry analityczne są rozproszone w 6+ miejscach:
- `parametry_analityczne` (DB) — definicje globalne
- `parametry_etapy` (DB) — bindingi do etapów procesu
- `cert_config.json` — osobna kopia definicji dla świadectw
- `seed.py` — seed definicji i bindingów
- `seed_mbr.py` — inline `parametry_lab` JSON
- `calculator.js` — hardcoded fallback

Kluczowy problem: `cert_config.json` i `parametry_etapy` to dwa niezależne źródła prawdy o tym samym parametrze dla tego samego produktu.

## Architektura trzech warstw

### Warstwa 1: Globalny rejestr (`parametry_analityczne`)

Jedno źródło prawdy o tym czym jest parametr. Trzy nazwy do różnych kontekstów:
- `skrot` → panel laboranta (SM, pH, NaCl)
- `label` → pełna polska nazwa, admin, raporty
- `name_en` → świadectwa (angielska kolumna)

### Warstwa 2: Etapy procesu (`parametry_etapy`)

Parametr × produkt × kontekst → limity, naważka, kolejność, target. Kontekst `analiza_koncowa` = pełen zestaw oznaczeń per produkt (zarówno dla szarż jak i zbiorników — zbiornik może mieć więcej oznaczeń).

### Warstwa 3: Świadectwa (`parametry_cert` — nowa tabela)

Osobna warstwa definiująca co i jak pojawia się na świadectwie. Z wyników analizy końcowej bierze podzbiór parametrów, z własną kolejnością, formatem i tekstem wymagania.

Separacja warstw 2 i 3 oznacza:
- Zmiana parametru w analizie nie psuje świadectw
- Zmiana layoutu świadectwa nie wpływa na formularz laboranta
- Dodanie wariantu świadectwa = nowe bindingi w warstwie cert, zero zmian w analizie

## Model danych

### Rozszerzenie `parametry_analityczne`

Nowe kolumny (migracja ALTER TABLE):

| Kolumna | Typ | Opis |
|---------|-----|------|
| `name_en` | TEXT | Angielska nazwa parametru (dla świadectw) |
| `method_code` | TEXT | Kod metody badawczej np. "L928", "L903" |

Istniejące kolumny bez zmian: id, kod, label, skrot, typ, metoda_nazwa, metoda_formula, metoda_factor, formula, precision, aktywny, metoda_id, jednostka.

### `parametry_etapy` — bez zmian

Konteksty: amidowanie, namca, czwartorzedowanie, sulfonowanie, utlenienie, rozjasnianie, analiza_koncowa, dodatki.

### Nowa tabela `parametry_cert`

```sql
CREATE TABLE parametry_cert (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    produkt           TEXT NOT NULL,
    parametr_id       INTEGER NOT NULL REFERENCES parametry_analityczne(id),
    kolejnosc         INTEGER DEFAULT 0,
    requirement       TEXT,
    format            TEXT DEFAULT '1',
    qualitative_result TEXT,
    UNIQUE(produkt, parametr_id)
);
```

- `requirement` — tekst wymagania widoczny na świadectwie ("max 150", "5,8-7,3", "klarowna ciecz /clear liquid")
- `format` — miejsca po przecinku na świadectwie ("0", "1", "2", "3")
- `qualitative_result` — stała wartość dla parametrów jakościowych ("zgodny /right"), null = numeryczny (wartość z wyników)

## UI: Trzy zakładki w `/parametry`

Rozbudowa istniejącego edytora parametrów. Punkt startowy: kod z `stash@{0}` (zawiera CSS i JS dla dwóch zakładek).

### Zakładka "Rejestr" (globalne definicje)

Tabela CRUD na `parametry_analityczne`:

| Kolumna | Edycja | Opis |
|---------|--------|------|
| Kod | readonly | Identyfikator (sm, nacl, ph_10proc) |
| Label PL | inline input | Pełna polska nazwa |
| Name EN | inline input | Angielska nazwa |
| Skrót | inline input | Krótka nazwa (SM, NaCl) |
| Typ | select | bezposredni / titracja / obliczeniowy / binarny |
| Metoda | inline input | Kod metody badawczej (L928, L903) |
| Jednostka | inline input | %, mg KOH/g itp. |
| Precyzja | number | Miejsca po przecinku |
| Status | toggle | Aktywny / Ukryty |

Dodawanie nowego parametru: formularz na dole tabeli.

### Zakładka "Etapy" (bindingi procesowe)

Istniejący widok z stasha — bez zmian funkcjonalnych. Accordion per parametr, bindingi z `parametry_etapy` (kontekst, produkt, limity, naważka, kolejność).

### Zakładka "Świadectwa" (bindingi certyfikatowe)

Widoczna tylko dla admina.

**Górna belka:** Select produktu (filtr).

**Tabela bindingów `parametry_cert` per wybrany produkt:**

| Kolumna | Edycja | Opis |
|---------|--------|------|
| Parametr | select z aktywnych `parametry_analityczne` | Który parametr |
| Kolejność | drag-to-reorder (HTML5 DnD) | Pozycja na świadectwie |
| Requirement | inline input | Tekst wymagania |
| Format | select "0"/"1"/"2"/"3" | Miejsca po przecinku |
| Qual. result | inline input | Stała wartość jakościowa |
| Usuń | przycisk | |

Nazwy (label, name_en) i metoda (method_code) na świadectwie brane automatycznie z rejestru — nie edytuje się ich tu. Zmiana w rejestrze propaguje wszędzie.

Przycisk "Dodaj parametr" → select + pola. Nowy wiersz: kolejność = ostatni+1.

## Migracja cert_config.json → DB

### Co migruje do DB

- `products[*].parameters` → tabela `parametry_cert` (requirement, format, qualitative_result, kolejność)
- `parametry_analityczne` dostaje `name_en` i `method_code` wypełnione z cert_config

### Co zostaje w cert_config.json

- `company`, `footer`, `rspo_number` — globalne metadane firmy
- `products[*].display_name`, `spec_number`, `cas_number`, `expiry_months`, `opinion_pl/en` — metadane produktu
- `products[*].variants` — warianty z flagami i overrides

### Skrypt migracyjny

Jednorazowy Python skrypt:
1. Czyta `cert_config.json`
2. Dla każdego parametru z `data_field` → znajduje `parametr_id` w `parametry_analityczne` po kodzie
3. Tworzy rekordy w `parametry_cert`
4. Uzupełnia `name_en` i `method_code` w `parametry_analityczne`
5. Parametry jakościowe (bez `data_field`, typ "jakosciowy") → nowe wpisy w `parametry_analityczne` + binding w `parametry_cert`

### Typ "jakosciowy"

Nowy typ w `parametry_analityczne` dla parametrów takich jak zapach, wygląd. Nie mają kodu analitycznego, nie są mierzone — mają stałą wartość na świadectwie (`qualitative_result` w `parametry_cert`). Migracja: ALTER TABLE usuwa CHECK constraint na kolumnie `typ` (precedens już istnieje w `models.py:280-305` dla typu "binarny") i dodaje "jakosciowy" jako dozwoloną wartość.

## Wpływ na resztę aplikacji

### Generator świadectw (`certs/generator.py`)

- `build_context()` — zmiana źródła: `cert_config.json` parameters → query z `parametry_cert` JOIN `parametry_analityczne`
- `get_variants()` — bez zmian (warianty nadal z JSON)
- Overrides `remove_parameters`/`add_parameters` w wariantach — referują `id` parametru z `parametry_cert`

### Panel laboranta

Bez zmian — nadal czyta z `parametry_etapy` przez `registry.py`.

### Calculator.js

Bez zmian — hardcoded fallback zostaje, primary source nadal `/api/parametry/calc-methods`.

### Seed (`seed.py`)

Rozszerzenie PARAMETRY list o `name_en` i `method_code`.

### Stare endpointy

- `/api/cert/config/parameters` GET/PUT — usunięcie (zastąpione przez zakładkę "Świadectwa")

### Pliki legacy (nie ruszamy)

- `mappings.py` — legacy, nie używany przez nowy flow
- `seed_mbr.py` — legacy inline `parametry_lab`, osobny scope

## Backend API

### Rozszerzenie istniejących endpointów

- `PUT /api/parametry/admin/<id>` — obsługa nowych pól `name_en`, `method_code`
- `POST /api/parametry/admin` — obsługa nowych pól przy dodawaniu

### Nowe endpointy (`parametry_cert`)

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/api/parametry/cert/<produkt>` | GET | Lista bindingów cert per produkt |
| `/api/parametry/cert` | POST | Dodaj binding (produkt, parametr_id, requirement, format, qualitative_result) |
| `/api/parametry/cert/<id>` | PUT | Edycja bindingu |
| `/api/parametry/cert/<id>` | DELETE | Usunięcie bindingu |
| `/api/parametry/cert/reorder` | POST | Batch update kolejności |

### Routing

Endpointy cert w `parametry/routes.py` (nie w `certs/routes.py`) — to zarządzanie parametrami, nie generowanie świadectw.

## Punkt startowy: stash@{0}

Stash zawiera niedokończoną pracę, z której czerpiemy:

### Do wykorzystania
- **`parametry_editor.html`** — CSS i JS dla dwóch zakładek (pe-tabs, switchTab, loadDefinicje, renderDefTable, addParametr, toggleActive). Rozszerzamy o trzecią zakładkę "Świadectwa".
- **`parametry/routes.py`** — `is_admin` flag, admin widzi nieaktywne parametry, może edytować typ/jednostka/aktywny, `POST /api/parametry` (tworzenie parametru), `GET/POST /api/ref-values` (wartości referencyjne per produkt, tabela `product_ref_values`).

### Do rozważenia
- **`product_ref_values`** — tabela wartości referencyjnych per produkt×kontekst. Nie jest częścią core scope centralizacji, ale istnieje w stashu. Jeśli jest potrzebna — zachowujemy. Jeśli nie — pomijamy przy apply.

### Pozostałe zmiany w stashu
Stash zawiera też zmiany w: laborant/models.py, laborant/routes.py, fast_entry, szarze_list, cert_master, narzedzia_metody. Te zmiany mogą być niezwiązane z parametrami — wymagają selektywnego cherry-pick przy apply (nie stosujemy `git stash pop` na ślepo).

## Technologia

- Frontend: Vanilla JS (spójne z resztą), Jinja2 template
- Styl: klasy `pe-*` (istniejące) + `pa-*` (z stasha) + nowe `pc-*` dla zakładki cert
- Drag-to-reorder: HTML5 Drag & Drop API
- Backend: Flask, SQLite

## Poza zakresem

- Migracja wariantów świadectw z JSON do DB (osobny projekt — spec z 2026-04-09)
- Edycja `company`/`footer`/`rspo_number`
- Refactor `seed_mbr.py` inline parametry_lab
- Usunięcie `mappings.py`
- Podgląd PDF (osobny projekt — edytor wzorów świadectw)
