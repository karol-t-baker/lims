# Centralizacja produktów — Design Spec

**Data:** 2026-04-09
**Status:** Zatwierdzony

## Cel

Tabela `produkty` jako single source of truth dla wszystkich danych produktowych: nazwy, kody, typy (szarża/zbiornik/płatkownia), specyfikacje certyfikatowe. Eliminacja duplikacji między `produkty`, `mbr_templates` i `cert_config.json`.

## Kontekst problemu

Produkty istnieją w trzech miejscach:
- `produkty` (DB) — nazwa, kod, typy, aktywny. Tabela istnieje w schemacie ale brakowała w produkcyjnej bazie. Właśnie utworzona z 44 produktami.
- `mbr_templates` (DB) — DISTINCT produkt jako de facto lista produktów. Nie ma kolumny typ.
- `cert_config.json` — display_name, spec_number, cas_number, expiry_months, opinion_pl/en per produkt.

Problem: laborant wybiera typ (szarża/zbiornik/płatkownia) przy tworzeniu nowej szarży, ale filtrowanie produktów po typie nie działało bo tabela `produkty` nie istniała w DB. Teraz istnieje, ale dane certyfikatowe dalej żyją w JSON.

## Model danych

### Rozszerzenie tabeli `produkty`

Nowe kolumny (migracja ALTER TABLE):

| Kolumna | Typ | Opis |
|---------|-----|------|
| `display_name` | TEXT | Ludzka nazwa ze spacjami ("Chegina K40GLOL") |
| `spec_number` | TEXT | Numer specyfikacji ("P833") |
| `cas_number` | TEXT | Numer CAS ("147170-44-3") |
| `expiry_months` | INTEGER DEFAULT 12 | Miesiące ważności produktu |
| `opinion_pl` | TEXT | Opinia PL na świadectwie |
| `opinion_en` | TEXT | Opinia EN na świadectwie |

Istniejące kolumny bez zmian: `id`, `nazwa` (UNIQUE), `kod`, `aktywny`, `typy` (JSON array, np. `["szarza","zbiornik"]`).

### Synchronizacja z mbr_templates

Przy `init_mbr_tables()`: dla każdego DISTINCT produkt z `mbr_templates` robi `INSERT OR IGNORE` do `produkty`. Gwarantuje że każdy produkt z MBR ma wpis w `produkty`.

4 brakujące produkty (`Chemal_CS_3070`, `Chemal_CS_5050`, `HSH_CS_3070`, `Kwas_Stearynowy`) zostaną dodane automatycznie.

### Migracja danych z cert_config.json

Jednorazowy skrypt: czyta `cert_config.json`, dla każdego produktu UPDATE w tabeli `produkty` (COALESCE — nie nadpisuje istniejących wartości) z: display_name, spec_number, cas_number, expiry_months, opinion_pl, opinion_en.

## UI: Czwarta zakładka "Produkty" w `/parametry`

Widoczna tylko dla admina. Zakładki: Etapy, Rejestr, Świadectwa, **Produkty**.

### Tabela produktów

| Kolumna | Edycja | Opis |
|---------|--------|------|
| Nazwa | readonly | Klucz produktu (`Chegina_K40GLOL`) |
| Display name | inline input | "Chegina K40GLOL" |
| Kod | inline input | Krótki kod ("GLOL") |
| Spec | inline input | Numer specyfikacji |
| CAS | inline input | Numer CAS |
| Ważność | number input | Miesiące ważności |
| Szarża | checkbox | Typ dozwolony |
| Zbiornik | checkbox | Typ dozwolony |
| Płatkownia | checkbox | Typ dozwolony |
| Aktywny | toggle | Ukryj/pokaż produkt |

### Dodawanie nowego produktu

Formularz na dole tabeli: `nazwa` (wymagane), `display_name`, `kod`, checkboxy typów. `display_name` generowany automatycznie z `nazwa` (underscory → spacje) jeśli nie podany.

### Usuwanie

Nie usuwamy — ustawiamy `aktywny=0`. Produkty z istniejącymi szarżami nie powinny znikać z historii.

## Backend API

### Nowe/rozszerzone endpointy

Endpointy produktów w `parametry/routes.py` (przeniesienie logiki z `zbiorniki/routes.py`):

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/api/produkty` | GET | Lista produktów. Parametr `?typ=` filtruje po `typy` JSON. `?all=1` zwraca nieaktywne. |
| `/api/produkty` | POST | Nowy produkt (admin) |
| `/api/produkty/<int:id>` | PUT | Edycja produktu (admin). Dozwolone pola: display_name, kod, spec_number, cas_number, expiry_months, opinion_pl, opinion_en, typy, aktywny |
| `/api/produkty/<int:id>` | DELETE | Soft delete: ustawia aktywny=0 (admin) |

### Migracja istniejących endpointów

Endpointy `/api/produkty` w `zbiorniki/routes.py` — redirect lub usunięcie po przeniesieniu do `parametry/routes.py`.

## Wpływ na resztę aplikacji

### Generator świadectw (`certs/generator.py`)

`build_context()` czyta `display_name`, `spec_number`, `cas_number`, `expiry_months`, `opinion_pl`, `opinion_en` z tabeli `produkty` zamiast z `cert_config.json`. Fallback do cert_config.json jeśli produkt nie ma wpisu w DB.

### cert_config.json

Sekcja `products[*]` traci pola przeniesione do DB: `display_name`, `spec_number`, `cas_number`, `expiry_months`, `opinion_pl`, `opinion_en`. Zostaje:
- `variants` — warianty z flagami i overrides
- `parameters` — legacy fallback (stopniowo zastępowane przez `parametry_cert`)
- `company`, `footer`, `rspo_number` — globalne metadane firmy

### Modal nowej szarży

Już woła `/api/produkty?typ=...` — działa bez zmian po uzupełnieniu tabeli. Produkty z `aktywny=0` nie pojawiają się.

### Panel admina `/admin/produkty`

Istniejący template — redirect do `/parametry` (zakładka Produkty) lub usunięcie.

### Inne konsumenty

`parametry_etapy.produkt`, `parametry_cert.produkt`, `mbr_templates.produkt` — referują po nazwie (TEXT). Nie wymagają zmian strukturalnych.

## Poza zakresem

- Migracja wariantów świadectw z cert_config.json do DB
- FK constrainty na `produkt` w innych tabelach (byłoby breaking change)
- Zarządzanie substratatmi per produkt (osobny scope)
