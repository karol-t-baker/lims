# Migracja świadectw do DB jako Single Source of Truth — Design Spec

**Data:** 2026-04-09
**Status:** Zatwierdzony

## Cel

Wyeliminować dualizm cert_config.json ↔ DB. Wszystkie dane certyfikatów (parametry, warianty, metadane produktów) czytane wyłącznie z bazy danych. cert_config.json zostaje jako read-only export/backup generowany automatycznie z DB.

## Decyzje architektoniczne

- **SSOT:** Baza danych (tabele: `produkty`, `parametry_cert`, `cert_variants`, `parametry_analityczne`)
- **cert_config.json:** Read-only export, regenerowany po każdym zapisie
- **Generator:** Czyta wyłącznie z DB, brak fallbacku na JSON
- **Edytor UI:** Frontend bez zmian, backend przepisany na DB
- **Warianty:** Hybrid schema — skalary + JSON kolumny

## Nowe/zmodyfikowane tabele

### `cert_variants` (nowa)

```sql
CREATE TABLE IF NOT EXISTS cert_variants (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    produkt       TEXT NOT NULL,
    variant_id    TEXT NOT NULL,
    label         TEXT NOT NULL,
    flags         TEXT DEFAULT '[]',
    spec_number   TEXT,
    opinion_pl    TEXT,
    opinion_en    TEXT,
    avon_code     TEXT,
    avon_name     TEXT,
    remove_params TEXT DEFAULT '[]',
    kolejnosc     INTEGER DEFAULT 0,
    UNIQUE(produkt, variant_id)
)
```

| Kolumna | Typ | Opis |
|---------|-----|------|
| `id` | INTEGER PK | auto-increment |
| `produkt` | TEXT NOT NULL | klucz produktu (np. "Chegina_K40GLOL") |
| `variant_id` | TEXT NOT NULL | identyfikator wariantu (np. "base", "loreal", "avon") |
| `label` | TEXT NOT NULL | nazwa wyświetlana (np. "Chegina K40GLOL — Loreal MB") |
| `flags` | TEXT | JSON array: `["has_rspo", "has_order_number", ...]` |
| `spec_number` | TEXT | override spec_number (NULL = dziedzicz z produkty) |
| `opinion_pl` | TEXT | override (NULL = dziedzicz) |
| `opinion_en` | TEXT | override (NULL = dziedzicz) |
| `avon_code` | TEXT | statyczna wartość kodu Avon |
| `avon_name` | TEXT | statyczna nazwa Avon |
| `remove_params` | TEXT | JSON array parametr_id do usunięcia z bazowych: `[5, 12]` |
| `kolejnosc` | INTEGER | kolejność sortowania wariantów |

### `parametry_cert` (rozszerzenie — 3 nowe kolumny + 1 zmiana)

Istniejące kolumny bez zmian: `id`, `produkt`, `parametr_id`, `kolejnosc`, `requirement`, `format`, `qualitative_result`.

Nowe kolumny:

| Kolumna | Typ | Opis |
|---------|-----|------|
| `variant_id` | INTEGER DEFAULT NULL | NULL = parametr bazowy produktu. NOT NULL = FK → `cert_variants.id` (add_parameter dla wariantu) |
| `name_pl` | TEXT | Override nazwy PL na świadectwie. NULL = bierz `parametry_analityczne.label` |
| `name_en` | TEXT | Override nazwy EN na świadectwie. NULL = bierz `parametry_analityczne.name_en` |
| `method` | TEXT | Override metody badawczej. NULL = bierz `parametry_analityczne.method_code` |

Zmiana constraintu UNIQUE:

```sql
-- stary: UNIQUE(produkt, parametr_id)
-- nowy:  UNIQUE(produkt, parametr_id, variant_id)
```

Gdzie `variant_id IS NULL` traktowane jako osobna wartość (SQLite tak działa — NULL != NULL w UNIQUE).

### `produkty` — bez zmian

Już jest SSOT dla: `display_name`, `spec_number`, `cas_number`, `expiry_months`, `opinion_pl`, `opinion_en`.

### `parametry_analityczne` — bez zmian

Dostarcza defaults: `label` (nazwa PL), `name_en`, `method_code`, `precision`.

## Przepływ danych — generowanie certyfikatu

```
build_context(produkt, variant_id, ...) {
  1. Metadane produktu     ← SELECT FROM produkty WHERE nazwa = ?
  2. Bazowe parametry      ← SELECT FROM parametry_cert pc
                              JOIN parametry_analityczne pa ON pa.id = pc.parametr_id
                              WHERE pc.produkt = ? AND pc.variant_id IS NULL
                              ORDER BY pc.kolejnosc
  3. Wariant               ← SELECT FROM cert_variants
                              WHERE produkt = ? AND variant_id = ?
  4. Apply remove_params   ← filtruj bazowe parametry wg cert_variants.remove_params
  5. Add variant params    ← SELECT FROM parametry_cert pc
                              JOIN parametry_analityczne pa ON pa.id = pc.parametr_id
                              WHERE pc.variant_id = <cert_variants.id>
                              ORDER BY pc.kolejnosc
  6. Nazwy na certyfikat   ← COALESCE(pc.name_pl, pa.label)
                              COALESCE(pc.name_en, pa.name_en)
                              COALESCE(pc.method, pa.method_code)
  7. Flagi wariantu        ← cert_variants.flags → has_rspo, has_order_number, etc.
  8. Overrides wariantu    ← cert_variants.spec_number || produkty.spec_number
                              cert_variants.opinion_pl || produkty.opinion_pl
}
```

**Brak fallbacku na cert_config.json.** Jeśli produkt nie ma danych w DB → błąd (ValueError), nie cichy fallback.

## Przepływ danych — edytor (`/admin/wzory-cert`)

### GET /api/cert/config/product/<key>

Czyta z DB:
- `produkty` → metadane
- `parametry_cert WHERE variant_id IS NULL` → bazowe parametry (JOIN parametry_analityczne)
- `cert_variants` → warianty
- `parametry_cert WHERE variant_id IS NOT NULL` → add_parameters per wariant

Zwraca ten sam kształt JSON co teraz (kompatybilność z frontendem).

### PUT /api/cert/config/product/<key>

Zapisuje do DB w transakcji:
1. `UPDATE produkty SET display_name=?, spec_number=?, ...` — metadane
2. `DELETE FROM parametry_cert WHERE produkt=? AND variant_id IS NULL` — usuń stare bazowe
3. `INSERT INTO parametry_cert (produkt, parametr_id, kolejnosc, requirement, format, qualitative_result, name_pl, name_en, method)` — nowe bazowe
4. `DELETE FROM cert_variants WHERE produkt=?` — usuń stare warianty
5. `INSERT INTO cert_variants (...)` — nowe warianty
6. `DELETE FROM parametry_cert WHERE produkt=? AND variant_id IS NOT NULL` — usuń stare add_params
7. `INSERT INTO parametry_cert (..., variant_id=<new_variant_id>)` — nowe add_params
8. Po COMMIT: regeneruj cert_config.json export

Całość w jednej transakcji SQLite — atomowy zapis.

### POST /api/cert/config/product

1. `INSERT INTO produkty` — nowy produkt
2. `INSERT INTO cert_variants (produkt, variant_id='base', label=display_name)` — domyślny wariant
3. Regeneruj export

### DELETE /api/cert/config/product/<key>

1. `DELETE FROM parametry_cert WHERE produkt=?`
2. `DELETE FROM cert_variants WHERE produkt=?`
3. Opcjonalnie: `DELETE FROM produkty WHERE nazwa=?` (lub zostaw, oznaczyć jako nieaktywny)
4. Regeneruj export

## Preview endpoint

`build_preview_context()` — bez zmian koncepcyjnych, ale zamiast czytać z przekazanego JSON payloadu bezpośrednio, buduje tymczasowe struktury identyczne z DB path. Nadal omija zapisany stan DB (preview = unsaved editor state).

## cert_config.json jako export

### Funkcja `export_cert_config(db) → dict`

Generuje pełny JSON w obecnym formacie cert_config.json:
- Czyta `company`/`footer`/`rspo_number` z dedykowanej tabeli `cert_settings` (lub hardcode jak dotąd)
- Iteruje `produkty` → dla każdego czyta `parametry_cert` + `cert_variants`
- Buduje identyczną strukturę JSON

### Kiedy regenerować

- Po każdym PUT/POST/DELETE w edytorze świadectw
- Na żądanie: `GET /api/cert/config/export` → zwraca JSON + zapisuje do `mbr/cert_config.json`

### Globalne ustawienia (company, footer, rspo_number)

Obecnie w cert_config.json. Opcje:
- **Prostsze:** Zostawić w cert_config.json jako jedyne pole czytane z pliku (company/footer nie są edytowane w edytorze)
- **Czyściej:** Nowa tabela `cert_settings` z key-value

Rekomendacja: zostawić company/footer w pliku — rzadko zmieniane, nie wchodzą w konflikty. Export je kopiuje.

## Migracja

Jednorazowy skrypt `scripts/migrate_cert_to_db.py`:

1. Czyta `cert_config.json`
2. Dla każdego produktu:
   a. Upewnia się że `produkty` ma wiersz z metadanymi
   b. Dla każdego parametru → `INSERT INTO parametry_cert` (variant_id=NULL, z name_pl/name_en/method overrides)
   c. Dla każdego wariantu → `INSERT INTO cert_variants`
   d. Dla add_parameters → `INSERT INTO parametry_cert` (variant_id=<new_variant.id>)
3. Weryfikacja: dla każdego produktu+wariantu, porównaj output build_context (DB) z build_context (stary config path)
4. Generuj cert_config.json export i porównaj z oryginałem

### Mapowanie parametr → parametry_analityczne

Istniejące `parametry_cert` wiersze (156 rekordów) mają `parametr_id` → gotowe.
Nowe z cert_config.json: mapuj `data_field` → `parametry_analityczne.kod` → `id`.

## Co usunąć po migracji

- `generator.py`: usunąć fallback path (config-based logic, linie ~303-338)
- `generator.py`: usunąć `load_config()` i `_cached_config` (niepotrzebne w generator)
- `routes.py`: GET/PUT/POST/DELETE endpointy → przepisać na DB
- `_CONFIG_PATH` import w routes.py → zastąpić export path

## Poza zakresem

- Edycja company/footer/rspo_number (zostają w pliku, rzadko zmieniane)
- Migracja `parametry_etapy` (osobny system, nie dotyczy świadectw)
- Zmiana frontendu edytora (backend zmienia się transparentnie)
