# Płatkowanie — trzeci typ rejestracji EBR

## Kontekst

System MBR/EBR obsługuje dwa typy rejestracji: **szarża produkcyjna** (pełny proces) i **analiza zbiornika** (uproszczona, analiza końcowa). Dodajemy trzeci typ: **płatkowanie** — uproszczony jak zbiornik, ale bez wyboru zbiornika, z opcjonalnym podaniem substratów.

Jednocześnie dodajemy kolumnę `typy` do tabeli `produkty`, by każdy produkt miał przypisane dozwolone typy rejestracji. Frontend filtruje dropdown produktów na podstawie wybranego typu.

## Zmiany w bazie danych

### 1. Kolumna `typy` w tabeli `produkty`

```sql
ALTER TABLE produkty ADD COLUMN typy TEXT DEFAULT '["szarza"]';
```

JSON array dozwolonych typów. Wartości: `"szarza"`, `"zbiornik"`, `"platkowanie"`.
Seed: Cheginy (K40GL, K40GLO, K40GLOL, K7) dostają wszystkie 3 typy. Reszta: `["szarza"]`. Admin może zmieniać przez panel.

### 2. Nowa tabela `substraty`

```sql
CREATE TABLE IF NOT EXISTS substraty (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazwa TEXT UNIQUE NOT NULL,
    aktywny INTEGER DEFAULT 1
);
```

Globalna lista substratów (np. "Olej kokosowy", "Betaina").

### 3. Nowa tabela `substrat_produkty`

```sql
CREATE TABLE IF NOT EXISTS substrat_produkty (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    substrat_id INTEGER NOT NULL REFERENCES substraty(id),
    produkt TEXT NOT NULL
);
```

Powiązanie substrat↔produkt. Substrat bez wpisów w tej tabeli jest "uniwersalny" — dostępny dla wszystkich produktów.

### 4. Nowa tabela `platkowanie_substraty`

```sql
CREATE TABLE IF NOT EXISTS platkowanie_substraty (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ebr_id INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
    substrat_id INTEGER NOT NULL REFERENCES substraty(id),
    nr_partii_substratu TEXT
);
```

Junction table: EBR płatkowania ↔ użyte substraty z numerami partii.

## Backend

### Route `POST /laborant/szarze/new` — rozszerzenie

Dodajemy obsługę `typ='platkowanie'`:
- Wymagane: `produkt`, `nr_partii`
- Opcjonalne: substraty jako JSON array `[{"substrat_id": 1, "nr_partii": "12/2026"}, ...]`
- Walidacja: produkt musi mieć `"platkowanie"` w kolumnie `typy`
- Po `create_ebr(typ='platkowanie')` → insert do `platkowanie_substraty`

### Nowe endpointy API

**`GET /api/substraty?produkt=X`** — zwraca aktywne substraty. Jeśli podano `produkt`, zwraca substraty powiązane z tym produktem + uniwersalne (bez wpisów w `substrat_produkty`).

**`GET /api/produkty?typ=platkowanie`** — zwraca produkty z danym typem w kolumnie `typy`. Używany przez frontend po kliknięciu kafelka w step 1.

### CRUD substratów (panel admina)

Endpointy w module admina:
- `GET /admin/substraty` — lista z UI do zarządzania
- `POST /admin/substraty` — dodaj/edytuj substrat
- `POST /admin/substraty/<id>/toggle` — aktywuj/dezaktywuj
- `POST /admin/substraty/<id>/produkty` — przypisz produkty do substratu

### Edycja typów produktu (panel admina)

W istniejącym widoku produktów w panelu admina — checkboxy `[x] szarza [x] zbiornik [x] platkowanie` przy każdym produkcie. Endpoint: `POST /admin/produkty/<id>/typy`.

### Model `create_ebr`

Bez zmian w sygnaturze. `typ='platkowanie'` zachowuje się jak `zbiornik` (workflow: analiza końcowa), ale bez `nr_zbiornika`.

## Frontend

### Step 1 — trzeci kafelek

Trzecia karta w `.type-grid`: "Płatkowanie". `selectTyp('platkowanie')` → ustawia `typ-input`, pokazuje `step-2c`. Ikona SVG dopasowana stylistycznie do istniejących dwóch (szarża = kolba, zbiornik = tank). Wszystkie 3 ikony zostaną zastąpione lepiej dopasowanymi SVG.

### Step 2c — formularz płatkowania

- **Wybór produktu**: quick-pick + search dropdown. Lista ładowana dynamicznie z `/api/produkty?typ=platkowanie` (nie statyczny `PRODUCTS`). Quick-pick buttony generowane z tej samej filtrowanej listy (pierwsze 4 produkty, lub mniej jeśli mniej ma ten typ).
- **Nr partii**: auto-generowany przez `fetchAutoNr()`, z opcją ręcznej zmiany.
- **Substraty (opcjonalne)**: po wyborze produktu → fetch `/api/substraty?produkt=X`. Sekcja z dynamicznymi wierszami:
  - Każdy wiersz: select (substrat z listy) + input text (nr partii substratu)
  - Przycisk "+" dodaje kolejny wiersz
  - Przycisk "×" usuwa wiersz

### Filtrowanie produktów w step-2a i step-2b

Po kliknięciu kafelka w step 1, dropdown produktów ładowany dynamicznie z `/api/produkty?typ=<wybrany_typ>` zamiast statycznego `PRODUCTS`. Dotyczy wszystkich trzech stepów.

### Panel admina — zarządzanie substratami

Nowa sekcja w panelu admina (analogicznie do zbiorników):
- Tabela substratów: nazwa, aktywny, powiązane produkty
- Formularz dodawania/edycji
- Multi-select checkboxy do przypisywania produktów

### Panel admina — edycja typów produktu

W widoku produktów: checkboxy typów przy każdym produkcie. Zapis przez AJAX.

## Ikony SVG

Trzy nowe ikony SVG (outline/stroke, spójny styl) zastępujące obecne w step 1:
- **Szarża produkcyjna**: ikona reaktora/kolby chemicznej
- **Płatkowanie**: ikona płatków/warstw
- **Analiza zbiornika**: ikona zbiornika z lupą/pomiarem

Konkretne SVG zostaną dobrane z otwartych bibliotek ikon (Lucide/Tabler/Phosphor).
