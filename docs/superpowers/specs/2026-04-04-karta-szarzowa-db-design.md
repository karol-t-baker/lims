# Design: Model danych procesowych — pełna karta szarżowa (K7 + K40GLOL)

Data: 2026-04-04
Status: Zatwierdzony
Pod-projekt: 1 z 3 (Baza danych + model)

---

## Problem

LIMS rejestruje tylko standaryzację i analizę końcową. Etapy procesowe (amidowanie, czwartorzędowanie, sulfonowanie, utlenienie) są widoczne w pipeline ale bez danych analitycznych. Laboranci nie mają gdzie wpisać wyników analiz pośrednich ani zaleceń korekt.

## Cel

Jednolity format danych dla:
- **Live LIMS** — laborant wpisuje wyniki analiz na każdym etapie produkcyjnym
- **Historyczny OCR** — migracja danych z extracted JSONów do tego samego formatu

Kompatybilność obu źródeł umożliwi w przyszłości budowanie wektorów treningowych ML.

## Decyzje projektowe

- **Laborant wpisuje ręcznie** wyniki analiz po zakończeniu każdego etapu
- **Szarże trwają 24-48h** — kolejne zmiany kontynuują wypełnianie
- **Poziom szczegółowości: tylko analizy** — bez danych operacyjnych (czasy, temperatury, ciśnienia)
- **Korekty: laborant zaleca i rejestruje** — wpisuje co zaleca, po wykonaniu potwierdza
- **Standaryzacja zostaje w `ebr_wyniki`** — bez zmian, obecny cykliczny mechanizm działa

---

## Nowe tabele

### `ebr_etapy_analizy`

Wynik pojedynczego pomiaru analitycznego na etapie procesowym.

```sql
CREATE TABLE IF NOT EXISTS ebr_etapy_analizy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ebr_id INTEGER NOT NULL,
    etap TEXT NOT NULL,
    runda INTEGER DEFAULT 1,
    kod_parametru TEXT NOT NULL,
    wartosc REAL,
    dt_wpisu TEXT,
    wpisal TEXT,
    UNIQUE(ebr_id, etap, runda, kod_parametru)
);
```

| Kolumna | Typ | Opis |
|---------|-----|------|
| ebr_id | INTEGER | FK do ebr_batches |
| etap | TEXT | 'amidowanie', 'smca', 'czwartorzedowanie', 'sulfonowanie', 'utlenienie', 'rozjasnianie' |
| runda | INTEGER | Nr analizy w danym etapie (1, 2, 3...) — np. 3 analizy w trakcie czwartorzędowania |
| kod_parametru | TEXT | 'ph_10proc', 'nd20', 'aa', 'so3', 'h2o2', 'le', 'la', 'lk', 'barwa_fau', 'barwa_hz' |
| wartosc | REAL | Wartość pomiaru |
| dt_wpisu | TEXT | ISO timestamp |
| wpisal | TEXT | Kto wprowadził (login lub nickname) |

UNIQUE constraint zapobiega duplikatom — jeden pomiar per (szarża, etap, runda, parametr). UPDATE ON CONFLICT do nadpisywania.

### `ebr_korekty`

Korekta zalecona przez laboranta i (opcjonalnie) potwierdzona po wykonaniu.

```sql
CREATE TABLE IF NOT EXISTS ebr_korekty (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ebr_id INTEGER NOT NULL,
    etap TEXT NOT NULL,
    po_rundzie INTEGER,
    substancja TEXT NOT NULL,
    ilosc_kg REAL,
    zalecil TEXT,
    wykonano INTEGER DEFAULT 0,
    dt_zalecenia TEXT,
    dt_wykonania TEXT
);
```

| Kolumna | Typ | Opis |
|---------|-----|------|
| ebr_id | INTEGER | FK do ebr_batches |
| etap | TEXT | Na którym etapie |
| po_rundzie | INTEGER | Po której rundzie analizy (np. po rundzie 1 → korekta → runda 2) |
| substancja | TEXT | 'NaOH', 'MCA', 'Perhydrol', 'Kw. cytrynowy', 'Na2SO3', 'Woda', 'NaCl' |
| ilosc_kg | REAL | Ilość w kg |
| zalecil | TEXT | Kto zalecił korektę |
| wykonano | INTEGER | 0=zalecone, 1=wykonane |
| dt_zalecenia | TEXT | Kiedy zalecono |
| dt_wykonania | TEXT | Kiedy potwierdzono wykonanie |

---

## Bez zmian

| Tabela | Rola | Status |
|--------|------|--------|
| `ebr_batches` | Rekord szarży | Bez zmian |
| `ebr_wyniki` | Standaryzacja (cykliczna) + analiza końcowa + zbiorniki | Bez zmian |
| `mbr_templates` | Szablony MBR z parametry_lab | Bez zmian |

---

## Parametry per etap — konfiguracja

### Nowy plik: `mbr/etapy_config.py`

Definiuje jakie parametry są mierzone na którym etapie, dla jakiego produktu.

```python
ETAPY_ANALIZY = {
    "Chegina_K7": {
        "amidowanie": {
            "label": "Amidowanie",
            "parametry": [
                {"kod": "le", "label": "LE (liczba estrowa)", "typ": "bezposredni", "info": "monitorowanie postępu"},
                {"kod": "la", "label": "LA (liczba kwasowa)", "typ": "titracja", "info": "po destylacji, < 5.0"},
                {"kod": "lk", "label": "LK (końcowa)", "typ": "titracja", "info": "< 1.0 mg KOH/g"},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni", "info": "orientacyjnie ~1.46"},
            ],
            "korekty": [],
        },
        "smca": {
            "label": "Wytworzenie SMCA",
            "parametry": [
                {"kod": "ph", "label": "pH roztworu", "typ": "bezposredni", "info": "3.0-4.0"},
            ],
            "korekty": ["NaOH", "MCA"],
        },
        "czwartorzedowanie": {
            "label": "Czwartorzędowanie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni", "info": "cel: 11.0-12.0"},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni", "info": "monitorowanie"},
                {"kod": "aa", "label": "%AA", "typ": "titracja", "info": "< 0.50%"},
            ],
            "korekty": ["NaOH", "MCA"],
        },
        "sulfonowanie": {
            "label": "Sulfonowanie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni"},
                {"kod": "so3", "label": "%SO₃²⁻", "typ": "titracja", "info": "< 0.30%"},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni"},
            ],
            "korekty": ["Na2SO3"],
        },
        "utlenienie": {
            "label": "Utlenienie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni"},
                {"kod": "so3", "label": "%SO₃²⁻", "typ": "titracja", "info": "= 0.000%"},
                {"kod": "h2o2", "label": "%H₂O₂", "typ": "titracja", "info": "< 0.010%"},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni"},
            ],
            "korekty": ["Perhydrol"],
        },
    },
    "Chegina_K40GLOL": {
        "amidowanie": {
            "label": "Amidowanie",
            "parametry": [
                {"kod": "le", "label": "LE", "typ": "bezposredni"},
                {"kod": "la", "label": "LA", "typ": "titracja"},
                {"kod": "lk", "label": "LK", "typ": "titracja", "info": "< 1.0"},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni"},
            ],
            "korekty": [],
        },
        "smca": {
            "label": "Wytworzenie SMCA",
            "parametry": [
                {"kod": "ph", "label": "pH roztworu", "typ": "bezposredni", "info": "3.0-4.0"},
            ],
            "korekty": ["NaOH", "MCA"],
        },
        "czwartorzedowanie": {
            "label": "Czwartorzędowanie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni", "info": "cel: 11.0-12.0"},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni"},
                {"kod": "aa", "label": "%AA", "typ": "titracja", "info": "< 0.30%"},
            ],
            "korekty": ["NaOH", "MCA"],
        },
        "sulfonowanie": {
            "label": "Sulfonowanie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni"},
                {"kod": "so3", "label": "%SO₃²⁻", "typ": "titracja", "info": "< 0.30%"},
                {"kod": "h2o2", "label": "%H₂O₂", "typ": "titracja"},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni"},
            ],
            "korekty": ["Na2SO3"],
        },
        "utlenienie": {
            "label": "Utlenienie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni"},
                {"kod": "so3", "label": "%SO₃²⁻", "typ": "titracja", "info": "< 0.030%"},
                {"kod": "h2o2", "label": "%H₂O₂", "typ": "titracja", "info": "< 0.010%"},
                {"kod": "nd20", "label": "nD20", "typ": "bezposredni"},
            ],
            "korekty": ["Kw. cytrynowy", "Perhydrol"],
        },
        "rozjasnianie": {
            "label": "Rozjaśnianie",
            "parametry": [
                {"kod": "ph_10proc", "label": "pH 10%", "typ": "bezposredni"},
                {"kod": "h2o2", "label": "%H₂O₂", "typ": "titracja", "info": "0.005-0.050%"},
                {"kod": "barwa_fau", "label": "Barwa FAU", "typ": "bezposredni", "info": "< 5"},
                {"kod": "barwa_hz", "label": "Barwa Hz", "typ": "bezposredni", "info": "< 150"},
            ],
            "korekty": ["Perhydrol"],
        },
    },
}
```

Inne produkty (K40GLO, K40GL, K7B etc.) dziedziczą konfigurację z K7 lub K40GLOL — mapowanie w configu.

---

## Endpointy API

| Metoda | URL | Opis |
|--------|-----|------|
| GET | `/api/ebr/<id>/etapy-analizy` | Wszystkie analizy procesowe dla szarży |
| POST | `/api/ebr/<id>/etapy-analizy` | Zapisz wyniki analizy (etap, runda, parametry) |
| GET | `/api/ebr/<id>/korekty` | Wszystkie korekty dla szarży |
| POST | `/api/ebr/<id>/korekty` | Zalecenie korekty |
| PUT | `/api/ebr/<id>/korekty/<kid>` | Potwierdzenie wykonania korekty |
| GET | `/api/etapy-config/<produkt>` | Konfiguracja etapów analitycznych dla produktu |

### POST `/api/ebr/<id>/etapy-analizy` — body:
```json
{
    "etap": "czwartorzedowanie",
    "runda": 2,
    "wyniki": {
        "ph_10proc": 11.76,
        "nd20": 1.3952,
        "aa": 0.08
    }
}
```

### POST `/api/ebr/<id>/korekty` — body:
```json
{
    "etap": "czwartorzedowanie",
    "po_rundzie": 1,
    "substancja": "NaOH",
    "ilosc_kg": 10.0
}
```

---

## Migracja OCR → nowe tabele

### Skrypt: `migrate_ocr_to_lims.py`

Czyta JSONy z `data/output_json/Chegina_K7/` i `Chegina_K40GLOL/`, mapuje na `ebr_etapy_analizy` i `ebr_korekty`.

Mapowanie OCR → tabela:
| OCR ścieżka | → tabela | etap | runda |
|-------------|----------|------|-------|
| `proces.etapy.amidowanie.analizy_po_destylacji[0]` | ebr_etapy_analizy | amidowanie | 1 |
| `proces.etapy.amidowanie.analizy_po_destylacji[1]` | ebr_etapy_analizy | amidowanie | 2 |
| `proces.etapy.smca.analiza_smca` | ebr_etapy_analizy | smca | 1 |
| `proces.etapy.czwartorzedowanie.kroki[typ=analiza][0]` | ebr_etapy_analizy | czwartorzedowanie | 1 |
| `proces.etapy.czwartorzedowanie.kroki[typ=analiza][1]` | ebr_etapy_analizy | czwartorzedowanie | 2 |
| `proces.etapy.czwartorzedowanie.kroki[typ=korekta][0]` | ebr_korekty | czwartorzedowanie | po_rundzie=1 |
| `proces.etapy.sulfonowanie.kroki[typ=analiza][0]` | ebr_etapy_analizy | sulfonowanie | 1 |
| `proces.etapy.utlenienie.kroki[typ=analiza][0]` | ebr_etapy_analizy | utlenienie | 1 |
| `proces.etapy.utlenienie.kroki[typ=korekta][0]` | ebr_korekty | utlenienie | — |
| `proces.etapy.wybielanie.kroki[typ=analiza][0]` | ebr_etapy_analizy | rozjasnianie | 1 |

Szarże OCR dostają `ebr_id` z istniejących rekordów w `ebr_batches` (match po `batch_id` lub `nr_partii` + `produkt`). Jeśli nie istnieją — tworzy nowe rekordy z `status='completed'` i `typ='szarza'`.

---

## Pliki do stworzenia / zmodyfikowania

| Plik | Akcja | Opis |
|------|-------|------|
| `mbr/etapy_config.py` | CREATE | Konfiguracja parametrów per etap per produkt |
| `mbr/etapy_models.py` | CREATE | CRUD dla ebr_etapy_analizy + ebr_korekty |
| `mbr/app.py` | MODIFY | Nowe endpointy API |
| `mbr/models.py` | MODIFY | init_mbr_tables — dodanie CREATE TABLE |
| `migrate_ocr_to_lims.py` | CREATE | Skrypt migracji OCR → nowe tabele |

---

## Kompatybilność danych

Po wdrożeniu każda szarża K7/K40GLOL będzie miała dane w dwóch miejscach:
- `ebr_wyniki` — standaryzacja (cykliczna) + analiza końcowa
- `ebr_etapy_analizy` + `ebr_korekty` — etapy procesowe

Dane historyczne (OCR) i bieżące (LIMS) w identycznym formacie. Zapytanie "wszystkie pomiary pH na etapie czwartorzędowania dla K7" zwraca dane z obu źródeł w jednej tabeli.
