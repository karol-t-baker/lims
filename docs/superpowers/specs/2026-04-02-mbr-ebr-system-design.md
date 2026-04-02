# MBR/EBR System — Cyfryzacja Kart Szarżowych

**Data:** 2026-04-02
**Status:** Approved

## 1. Cel systemu

Narzędzie do zarządzania 4 wzorcami kart szarżowych (MBR) dla produktów K7, GL, GLO, GLOL, z możliwością generowania aktywnych szarż (EBR) oraz podglądu i wydruku pełnej karty w formacie papierowym.

**Nadrzędny cel:** zbieranie ustrukturyzowanych danych analitycznych do treningu soft sensorów i modeli ML. MBR/EBR to kanał zbierania danych, a PDF i workflow to "opakowanie" dla użytkowników.

### Przepływ

```
Technolog (Tworzy MBR: etapy, limity, instrukcje)
    ↓
System (Generuje EBR na konkretny dzień/szarżę)
    ↓
Laborant (Widzi pełną kartę — 2 etapy odblokowane, reszta zablokowana)
    ↓
Raport PDF (System łączy dane z MBR i wpisy Laboranta w widok papierowej karty)
```

### Relacja z istniejącym systemem

MBR/EBR **zastępuje** papierowe karty. Dane z EBR trafiają do tego samego schematu v4 co dane OCR (`_source = "digital"` vs `_source = "ocr"`), tworząc jeden spójny dataset do ML.

## 2. Model danych

### Tabela `mbr_templates`

Jeden rekord = jeden MBR dla jednego produktu w jednej wersji.

| Kolumna | Typ | Opis |
|---------|-----|------|
| `mbr_id` | INTEGER PK | Auto-increment |
| `produkt` | TEXT | "Chegina_K7", "Chegina_K40GL", "Chegina_K40GLO", "Chegina_K40GLOL" |
| `wersja` | INTEGER | 1, 2, 3... per produkt |
| `status` | TEXT | "draft", "active", "archived" |
| `etapy_json` | TEXT (JSON) | Opis etapów procesu — read-only treść wyświetlana w EBR i PDF |
| `parametry_lab` | TEXT (JSON) | Definicja pól laboranckich + limity |
| `utworzony_przez` | TEXT | Login technologa |
| `dt_utworzenia` | DATETIME | |
| `dt_aktywacji` | DATETIME | Kiedy przeszedł draft → active |
| `notatki` | TEXT | Komentarz technologa do wersji |

**Reguła:** Tylko jeden MBR per produkt może mieć `status = "active"`. Nowa aktywacja → stary przechodzi do "archived".

### Struktura `etapy_json`

```json
[
  {"nr": 1, "nazwa": "Amidowanie", "instrukcja": "Załadować surowce wg receptury...", "read_only": true},
  {"nr": 2, "nazwa": "Wytworzenie SMCA", "instrukcja": "Rozpuścić MCA...", "read_only": true},
  {"nr": 3, "nazwa": "Czwartorzędowanie", "instrukcja": "...", "read_only": true},
  {"nr": 4, "nazwa": "[Analiza przed standaryzacją — nazwa TBD]", "instrukcja": "Pobrać próbkę...", "read_only": false, "sekcja_lab": "przed_standaryzacja"},
  {"nr": 5, "nazwa": "Standaryzacja", "instrukcja": "...", "read_only": true},
  {"nr": 6, "nazwa": "Analiza końcowa", "instrukcja": "...", "read_only": false, "sekcja_lab": "analiza_koncowa"},
  {"nr": 7, "nazwa": "Przepompowanie", "instrukcja": "...", "read_only": true}
]
```

`read_only: false` + `sekcja_lab` = edytowalny etap z polami z `parametry_lab`.

### Struktura `parametry_lab`

```json
{
  "przed_standaryzacja": {
    "label": "Analiza przed standaryzacją",
    "pola": [
      {
        "kod": "ph_10proc",
        "label": "pH 10%",
        "tag": "ph_10proc",
        "typ": "float",
        "min": 5.0,
        "max": 7.5,
        "precision": 1
      }
    ]
  },
  "analiza_koncowa": {
    "label": "Analiza końcowa",
    "pola": [
      {
        "kod": "ph",
        "label": "pH",
        "tag": "ph",
        "typ": "float",
        "min": 4.5,
        "max": 6.5,
        "precision": 1
      }
    ]
  }
}
```

Trzy identyfikatory per pole:
- **`label`** — wyświetlany w UI/PDF, technolog zmienia dowolnie
- **`kod`** — klucz wewnętrzny formularza
- **`tag`** — stały identyfikator analityczny dla ML pipeline, mapuje 1:1 na kolumny v4 `events`

### Tabela `ebr_batches`

| Kolumna | Typ | Opis |
|---------|-----|------|
| `ebr_id` | INTEGER PK | |
| `mbr_id` | INTEGER FK | Referencja do MBR (zamrożona wersja) |
| `batch_id` | TEXT UNIQUE | "Chegina_K7__55_2026" — zgodny z v4 |
| `nr_partii` | TEXT | "55/2026" |
| `nr_amidatora` | TEXT | |
| `nr_mieszalnika` | TEXT | |
| `wielkosc_szarzy_kg` | REAL | |
| `surowce_json` | TEXT (JSON) | Nullable — miejsce na dane surowcowe (przyszłość, wpływ na soft sensory) |
| `dt_start` | DATETIME | |
| `dt_end` | DATETIME | NULL dopóki otwarta |
| `status` | TEXT | "open", "completed", "cancelled" |
| `operator` | TEXT | Kto uruchomił szarżę |

### Tabela `ebr_wyniki`

| Kolumna | Typ | Opis |
|---------|-----|------|
| `wynik_id` | INTEGER PK | |
| `ebr_id` | INTEGER FK | |
| `sekcja` | TEXT | "przed_standaryzacja" / "analiza_koncowa" |
| `kod_parametru` | TEXT | "ph", "nd20", "procent_sa"... |
| `tag` | TEXT | Stały tag analityczny z MBR |
| `wartosc` | REAL | Wpisana wartość |
| `min_limit` | REAL | Skopiowany z MBR w momencie wpisu |
| `max_limit` | REAL | Skopiowany z MBR w momencie wpisu |
| `w_limicie` | BOOLEAN | Auto: min ≤ wartość ≤ max |
| `komentarz` | TEXT | Kontekst od laboranta (nullable) — kluczowe dla outlierów ML |
| `is_manual` | BOOLEAN | TRUE = ręczny, FALSE = sensor/IoT (default TRUE) |
| `dt_wpisu` | DATETIME | Auto-timestamp |
| `wpisal` | TEXT | Login laboranta |

**Kluczowe:** `min_limit`/`max_limit` kopiowane z MBR do wyniku — historyczne wyniki zachowują oryginalne limity nawet po zmianie MBR.

### Tabela `mbr_users`

| Kolumna | Typ | Opis |
|---------|-----|------|
| `user_id` | INTEGER PK | |
| `login` | TEXT UNIQUE | |
| `password_hash` | TEXT | bcrypt |
| `rola` | TEXT | "technolog" / "laborant" |
| `imie_nazwisko` | TEXT | |

### Synchronizacja z v4

Przy zapisie `ebr_wyniki` → automatyczny INSERT do `events`:
- `batch_id` = `ebr_batches.batch_id`
- `stage` = mapowanie z `sekcja` ("przed_standaryzacja" → "standaryzacja", "analiza_koncowa" → "analiza_koncowa")
- `event_type` = "analiza"
- `_source` = "digital"
- Parametry numeryczne mapowane po `tag`

Przy zamknięciu szarży → UPDATE `batch` (pola `ak_*` z analiza_koncowa).

## 3. UI — Panel Technologa

### 3.1 Zarządzanie MBR

**Ekran: Lista MBR**

Tabela: Produkt | Wersja | Status | Data aktywacji | Akcje

Akcje:
- **Edytuj** (tylko draft)
- **Aktywuj** (draft → active, archiwizuje poprzednią)
- **Klonuj** — nowy draft z kopią danych (model "Klonuj i Edytuj")
- **Podgląd PDF** — generuje widok papierowej karty

**Ekran: Edytor MBR**

Dwie zakładki:

*Zakładka 1: Etapy procesu*
- Lista etapów (kolejność)
- Per etap: nazwa, instrukcja (textarea), checkbox "Sekcja laboratoryjna"
- Jeśli lab → link do zakładki 2

*Zakładka 2: Parametry laboratoryjne*
- Per sekcja lab:
  - Tabela pól: Kod | Tag | Label | Min | Max | Precyzja
  - Przyciski: dodaj/usuń pole
  - Walidacja: min < max, precyzja 0-4

### 3.2 Dashboard Technologa

**Widok Live — Aktywne szarże:**
- Tabela: Nr partii | Produkt | Amidator | Start | Status | Ostatni wpis
- Status kolorowy: `open` (zielony), `oczekuje na analizę` (żółty), `poza limitem` (czerwony)
- Klik → podgląd EBR read-only

**Widok Historia — Zamknięte szarże:**
- Filtrowanie: produkt, zakres dat, w/poza limitem
- Tabela wyników z kolorowym oznaczeniem limitów
- Link do PDF per szarża
- **Eksport CSV** — dane do analizy / ML

## 4. UI — Panel Laboranta

### Layout

Zgodny z wybranymi UI concepts (`layout_split_sidebar.html` + `styl_warm_teal.html`):
- **Nav rail** (54px, teal-dark) — ikony: Analizy, Historia, Raporty + avatar
- **Sidebar** (228px) — toggle: Etapy | Szarże | Zbiorniki
- **Main** — topbar + workspace (formularz + prawy panel)
- **Footer** — Zapisz + Zatwierdź

### Sidebar — tryb "Etapy"

Dropdown wyboru szarży + meta (amidator, mieszalnik, kg, data start) + progress bar.

7 etapów widocznych:
- **5 zablokowanych** — szare, ikona kłódki, nieklikalne (Amidowanie, SMCA, Czwart, Sulfonowanie, Utlenienie/Standaryzacja)
- **2 odblokowane** — Analiza przed standaryzacją + Analiza końcowa

### Formularz — main area

Wzorowany na `koncowa_right_panel_calc.html`:
- Pola generowane dynamicznie z `parametry_lab` w MBR
- Normy inline przy każdym polu: `pH 10% [4.0–6.0]`
- Walidacja na żywo: w limicie → zielona ramka, poza → czerwona + komentarz się rozwija
- Pola titracyjne (⚗) → klik otwiera kalkulator w prawym panelu
- Sekcje: Barwa (FAU, Hazen, Opis), Ocena jakości (dropdown), Przepompowanie

### Prawy panel (280px)

Dwie zakładki: **Referencje | Kalkulator ⚗**
- **Referencje:** poprzednia analiza + normy z MBR
- **Kalkulator:** dynamiczny per parametr (Epton, Mohr, alkacymetria, jodometria, manganometria) — naważki, objętość titranta, auto-średnia, zbieżność, "Zatwierdź wynik →"

### Uruchomienie nowej szarży

Modal: wybór produktu → nr partii → nr amidatora → nr mieszalnika → wielkość szarży → Start.
System generuje EBR z aktualnego aktywnego MBR.

### Zachowanie formularza

- Zapis per sekcja — można wypełnić jedną teraz, drugą za kilka godzin
- Edycja po zapisie — możliwa, loguje: stary→nowy + wymaga komentarza (audit)
- Auto-timestamp `dt_wpisu`, auto-user `wpisal`
- Poza limitem bez komentarza → ostrzeżenie (nie blokuje)

### Workflow etapów

- Hybryda: główne etapy w kolejności, wewnątrz etapu pola dowolnie
- AMID + SMCA mogą iść równolegle na starcie
- Bramki między etapami (docelowo, gdy kolejne etapy się otworzą)

## 5. Generowanie PDF

### Zasada: wierny klon papierowej karty

PDF jest cyfrową reprodukcją istniejącego formularza papierowego, 1:1 z fizyczną kartą szarżową. Format A4, 4 strony.

### Struktura (4 strony, jak oryginał)

**Strona 1:**
- Nagłówek: logo CHEMCO, "KARTA SZARŻOWA nr...", nr technologii (T111/T118/T121), wydanie, data
- Dane szarży: nr aparatu, nr partii, daty, wielkość
- Tabela "ZAŁADUNEK SUROWCÓW" — lp, nazwa, ilość recepturowa, załadowana, nr partii, pulpa
- Tabela "STANDARYZOWANIE PRODUKTU" — dodatek, ilość, data/godzina, nr partii

**Strony 2-3:**
- "PRZEBIEG I PARAMETRY PROCESU"
- Tabela: Operacja | Data | Temperatura | Próżnia | Pulpa | Uwagi
- Wyniki analiz międzyoperacyjnych

**Strona 4:**
- Analiza międzyoperacyjna (przed standaryzacją) — wartości z EBR
- Analiza końcowa — wyniki z EBR + limity z MBR
- Przepompowanie — dane z EBR
- Pola na podpisy

### Źródło danych per strona

| Strona | MVP (teraz) | Docelowo |
|--------|-------------|----------|
| 1 | Struktura z MBR, surowce puste lub z `surowce_json` | EBR pełne |
| 2-3 | Struktura z MBR, pola puste | EBR z wpisami operatora |
| 4 | Analiza przed stand. + końcowa z EBR | Pełne z EBR |

### Technologia

- Jinja2 HTML template stylizowany na papierowy formularz (czarne linie, serif, A4)
- WeasyPrint → PDF z `@page` rules, page breaks, nagłówki/stopki
- Osobny template per typ technologii (T111, T118, T121)

### Dostęp

- Technolog: "Podgląd PDF" w panelu MBR (pusta karta = formularz do wydruku)
- Laborant: "PDF" przy zamkniętej szarży (wypełniona karta)

## 6. Architektura techniczna

### Stack

| Warstwa | Technologia |
|---------|------------|
| Backend | Flask (Python) |
| Baza | SQLite — `batch_db_v4.sqlite`, nowe tabele obok istniejących |
| Frontend | Jinja2 templates + vanilla JS |
| Style | CSS variables — warm teal design system |
| PDF | WeasyPrint |
| Auth | bcrypt + Flask session + role (technolog/laborant) |

### Struktura plików

```
mbr/
├── app.py              # Flask app — routing, auth
├── models.py           # SQLite DAL — MBR, EBR, wyniki
├── pdf_gen.py          # Jinja2 → WeasyPrint → PDF
├── templates/
│   ├── base.html       # Layout: rail + sidebar + main
│   ├── login.html
│   ├── technolog/
│   │   ├── mbr_list.html
│   │   ├── mbr_edit.html
│   │   ├── dashboard.html
│   │   └── export.html
│   ├── laborant/
│   │   ├── szarze_list.html
│   │   ├── fast_entry.html
│   │   └── nowa_szarza.html
│   └── pdf/
│       ├── karta_k40gl.html
│       ├── karta_k40glo.html
│       ├── karta_k40glol.html
│       └── karta_k7.html
├── static/
│   ├── style.css       # Warm teal design system
│   └── calculator.js   # Kalkulator titracyjny
└── seed_mbr.py         # Inicjalizacja 4 MBR z danych kart
```

### Bezpieczeństwo (MVP)

- Hasła hashowane bcrypt
- Sesja Flask z `secret_key`
- Role-based access (decorator): technolog widzi edytor MBR, laborant nie
- Reszta (HTTPS, CSRF, rate limiting, audit log podpisów) — przyszłe iteracje

## 7. Roadmapa

| Krok | Co | Rezultat |
|------|-----|---------|
| **01** | Baza MBR + seed 4 produktów + edytor technologa | 4 MBR w bazie, technolog edytuje limity i etapy |
| **02** | Silnik PDF | Podgląd/wydruk karty papierowej z MBR |
| **03** | Moduł laboranta | Fast-entry 2 etapów + kalkulator + walidacja + sync v4 |
| **04** | Skalowanie | Odblokowanie kolejnych etapów, nowe produkty |

## 8. Poza scope (świadomie)

- Podpis elektroniczny
- Sensory IoT (pole `is_manual` gotowe)
- Workflow zatwierdzania (technolog → kierownik)
- Powiadomienia push
- Multi-language
- HTTPS / CSRF / rate limiting (wewnętrzna sieć zakładowa)

## 9. Otwarte kwestie

- [ ] Nazwa etapu "Analiza przed standaryzacją" — do doprecyzowania
- [ ] Parametry i limity per produkt — user dostarczy z osobnego pliku
- [ ] Nr technologii per produkt (T111, T118, T121) — mapowanie do potwierdzenia
