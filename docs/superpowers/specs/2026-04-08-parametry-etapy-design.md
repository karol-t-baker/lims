# Sub-projekt C: Parametry i etapy — Design Spec

## Cel

Rozbudować system parametrów o typ binarny (OK/Nie OK), globalny edytor z admin panelu, wartości dopuszczalne z golden batch target, oraz przenieść etapy procesowe z hardkodu do bazy z admin CRUD.

## C1: Globalny edytor parametrów + typ binarny

### Zmiany w DB

**parametry_analityczne — rozszerzenie CHECK constraint + nowa kolumna:**
```sql
-- Migration: add 'binarny' to typ CHECK
-- SQLite nie obsługuje ALTER CHECK, więc: tworzymy nową tabelę, kopiujemy dane, zamieniamy
-- Alternatywnie: usunięcie CHECK (SQLite ignoruje CHECK na ALTER, ale nowe INSERT go respektują)
-- Pragmatycznie: ALTER TABLE ADD COLUMN jednostka + migracja typ via UPDATE

ALTER TABLE parametry_analityczne ADD COLUMN jednostka TEXT;
```

Typ `binarny` — dodanie przez zapis nowych parametrów z `typ='binarny'`. SQLite CHECK constraint na istniejącej tabeli wymaga migracji; pragmatycznie: usunięcie CHECK i walidacja w aplikacji.

### Admin panel — nowy rail "Parametry"

Tabela wszystkich parametrów z edycją inline:

| Kod | Label | Skrót | Typ | Jednostka | Precyzja | Status |
|-----|-------|-------|-----|-----------|----------|--------|
| ph | pH | pH | bezpośredni | — | 2 | Aktywny |
| sa | Substancja aktywna | SA | bezpośredni | % | 2 | Aktywny |
| klarownosc | Klarowność | Klar. | binarny | — | — | Aktywny |

Funkcje:
- Edycja inline: label, skrót, typ (dropdown), jednostka, precyzja
- Dodawanie nowych parametrów
- Toggle aktywny/nieaktywny
- Wyszukiwarka/filtr po typie

### Fast entry — obsługa typu binarny

Zamiast input liczbowego → dwa pill-buttony: **OK** / **Nie OK**
- Klik zapisuje do `ebr_wyniki.wartosc_text`
- Kolorowanie: OK = zielony, Nie OK = czerwony
- W limicie: OK = tak, Nie OK = nie (automatycznie)

## C2: Seed parametrów binarnych

Dwa nowe parametry w `parametry/seed.py`:
- `klarownosc` — label: "Klarowność", typ: `binarny`
- `zelowanie` — label: "Żelowanie", typ: `binarny`

Binding do kontekstu `analiza_koncowa` z `produkt=NULL` (globalne — dostępne dla wszystkich produktów).

## C3: Wartości dopuszczalne + golden batch target

### Zmiana w DB

```sql
ALTER TABLE parametry_etapy ADD COLUMN target REAL;
```

`target` = wartość idealna (golden batch). Obok istniejących `min_limit` / `max_limit`.

### Admin widok — per produkt

Widok: wybierz produkt → lista parametrów z:
- **Min** — dolna granica dopuszczalna
- **Target** — golden batch (wartość idealna)
- **Max** — górna granica dopuszczalna

Edycja inline. Zmiana → auto-save → `rebuild-mbr`.

### Fast entry — wyświetlanie

Pod polem input: `cel: 6.0 (5.5–6.5)` — target pogrubiony, zakres w nawiasie.

Kolorowanie wyniku:
- Zielony (`ok`) — wynik blisko targetu (w normie)
- Żółty/amber — wynik w normie ale daleko od targetu
- Czerwony (`err`) — poza normą

## C4: Etapy procesowe do bazy

### Nowe tabele

```sql
CREATE TABLE IF NOT EXISTS etapy_procesowe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kod TEXT UNIQUE NOT NULL,
    label TEXT NOT NULL,
    aktywny INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS produkt_etapy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    produkt TEXT NOT NULL,
    etap_kod TEXT NOT NULL,
    kolejnosc INTEGER DEFAULT 0,
    rownolegle INTEGER DEFAULT 0,
    UNIQUE(produkt, etap_kod)
);
```

### Seed

Migracja z hardkodowanych list:
- `amidowanie` → "Amidowanie"
- `smca` → **"NaMCA"** (rename!)
- `czwartorzedowanie` → "Czwartorzędowanie"
- `sulfonowanie` → "Sulfonowanie"
- `utlenienie` → "Utlenienie"
- `rozjasnianie` → "Rozjaśnianie"
- `standaryzacja` → "Standaryzacja"
- `analiza_koncowa` → "Analiza końcowa"
- `dodatki` → "Dodatki standaryzacyjne"

Produkt_etapy seed z PROCESS_STAGES_K7 i PROCESS_STAGES_GLOL (z flagą `rownolegle` dla amidowanie+NaMCA).

### Admin panel — rail "Etapy"

- Lista etapów: kod, label, aktywny
- Edycja nazw inline
- Przypisanie etapów do produktów z drag & drop kolejności
- Toggle aktywny (dezaktywacja ukrywa etap z procesu)

### Migracja kodu

`get_process_stages()` w `etapy/models.py` — czyta z `produkt_etapy` JOIN `etapy_procesowe` zamiast hardkodowanych list. Fallback na stare listy jeśli tabele puste (backward compat).

`ETAPY_ANALIZY` w `etapy/config.py` — label + korekty. Label migruje do `etapy_procesowe.label`, korekty zostają w config (na razie).

## Pliki

| Action | File | Purpose |
|--------|------|---------|
| Modify | `mbr/models.py` | Nowe tabele + migracje (jednostka, target, CHECK) |
| Create | `mbr/templates/admin/parametry.html` | Admin edytor parametrów |
| Create | `mbr/templates/admin/etapy.html` | Admin edytor etapów |
| Create | `mbr/templates/admin/normy.html` | Admin widok norm per produkt |
| Modify | `mbr/zbiorniki/routes.py` | Routes dla parametrów/etapów admin (reuse blueprint) |
| Modify | `mbr/templates/base.html` | 2 nowe raile admin (Parametry, Etapy) |
| Modify | `mbr/templates/laborant/_fast_entry_content.html` | UI binarny OK/Nie OK + target hint |
| Modify | `mbr/etapy/models.py` | get_process_stages z DB |
| Modify | `mbr/etapy/config.py` | SMCA→NaMCA w ETAPY_ANALIZY |
| Modify | `mbr/parametry/seed.py` | Seed klarowność, żelowanie, etapy |
| Modify | `mbr/parametry/registry.py` | Zwracać target + jednostka w API |

## Poza scopem

- Statystyki "wartości typowe" (przyszły feature — wymaga danych historycznych)
- Automatyczne blokowanie zatwierdzenia szarży gdy poza normą (przyszły feature)
- Drag & drop kolejności etapów per produkt (V2 — na razie ręczna kolejność)
