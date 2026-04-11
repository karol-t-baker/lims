# Uwagi końcowe szarż/zbiorników — design

**Data:** 2026-04-11
**Status:** Design approved, ready for implementation plan

## Problem

Laboranci kończąc szarżę lub zbiornik czasami:
1. Dodają ręczną korektę (np. +500 kg NaOH) *bez* ponownej analizy — chcą odnotować ten fakt.
2. Akceptują parametr poza limitem licząc na wyrównanie w kolejnych szarżach/zbiornikach — chcą to gdzieś zapisać dla audytu i dla KJ.

Dziś takie informacje nie mają w systemie żadnego miejsca. `ebr_wyniki.komentarz` działa per-parametr i jest używane inaczej. `ebr_korekty` dotyczy korekt **w trakcie** etapu procesowego (dodawanie substancji podczas sulfonowania itd.), nie zamknięcia. Efekt: wiedza operacyjna ginie albo jest trzymana poza systemem.

## Rozwiązanie — streszczenie

Dodajemy **jedno proste pole tekstowe per szarża/zbiornik** (`uwagi_koncowe`), wpisywane w sekcji analizy końcowej, edytowalne również po zamknięciu (laborant / laborant_kj / laborant_coa / admin). Pełny trail log każdej zmiany w osobnej tabeli historii. Pole widoczne w hero szarży oraz jako nowa kolumna w liście szarż (truncate do 50 znaków + tooltip). **Nie** renderowane na świadectwach jakości — to wiedza wyłącznie wewnętrzna.

## Decyzje projektowe

| # | Decyzja | Wybór |
|---|---------|-------|
| 1 | Liczba notatek per szarża | **Jedna** (wolny tekst, nie ustrukturyzowana lista) |
| 2 | Kiedy wpisywana | Przy analizie końcowej + edycja po zamknięciu |
| 3 | Kto edytuje po zamknięciu | laborant, laborant_kj, laborant_coa, admin |
| 4 | Historia zmian | **Pełna** — osobna tabela `ebr_uwagi_history` |
| 5 | Limit długości | **500 znaków** |
| 6 | Renderowanie w wierszu analizy | Osobny blok pod listą parametrów (nie jako row parametru) |
| 7 | Historia w hero | **Zawsze widoczna**, nie zwinięta |
| 8 | Pokazanie na świadectwie | **Nie** |
| 9 | Typy | Wszystkie: `szarza`, `zbiornik`, `platkowanie` |
| 10 | Kolumna w liście | Truncate do 50 znaków + `title=` tooltip, we wszystkich zakładkach |
| 11 | Edycja szarży `cancelled` | **Zablokowana** |
| 12 | Filtr/wyszukiwanie po uwagach | Poza zakresem (YAGNI) |

## Model danych

### Nowa kolumna na `ebr_batches`

```sql
ALTER TABLE ebr_batches ADD COLUMN uwagi_koncowe TEXT;
```

Nullable. Walidacja długości (≤500 znaków) enforcowana w warstwie aplikacji (SQLite nie egzekwuje CHECK przy ALTER TABLE ADD COLUMN).

### Nowa tabela historii

```sql
CREATE TABLE IF NOT EXISTS ebr_uwagi_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ebr_id     INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
    tekst      TEXT,              -- poprzedni stan przed zmianą; NULL gdy action='create'
    action     TEXT NOT NULL CHECK(action IN ('create', 'update', 'delete')),
    autor      TEXT NOT NULL,     -- login z Flask session
    dt         TEXT NOT NULL      -- ISO timestamp
);

CREATE INDEX IF NOT EXISTS idx_ebr_uwagi_history_ebr
    ON ebr_uwagi_history(ebr_id, dt DESC);
```

**Semantyka `tekst`:** trzymamy *stary* stan (przed zmianą), nie nowy. To pozwala czytać aktualną wartość z `ebr_batches.uwagi_koncowe` bez JOINa. Historia jest "dziennikiem cofek" — co było przed każdą zmianą.

**Action detection przy zapisie:**

| stare `uwagi_koncowe` | nowa wartość (po `strip()`) | action | wpis w historii |
|---|---|---|---|
| NULL | `""` | (no-op) | brak |
| NULL | tekst | `create` | `{tekst: NULL, action: 'create'}` |
| tekst A | tekst B (B ≠ A) | `update` | `{tekst: A, action: 'update'}` |
| tekst A | tekst A | (no-op) | brak |
| tekst A | `""` | `delete` | `{tekst: A, action: 'delete'}` |

Po insertcie do historii następuje `UPDATE ebr_batches SET uwagi_koncowe = ?` nową wartością (lub `NULL` dla delete). Cała operacja w jednej transakcji.

### Migracja

Ad-hoc skrypt `migrate_uwagi_koncowe.py` w repo root, idempotentny:
- Sprawdza czy `uwagi_koncowe` istnieje w `ebr_batches` (via `PRAGMA table_info`) — ALTER TABLE tylko jeśli brak
- `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`
- Uruchamiany ręcznie raz na deploy

**Równolegle:** te same definicje trafiają do `init_mbr_tables()` w `mbr/models.py`, żeby świeże instancje dostawały je przy starcie aplikacji.

## Backend API

Cztery endpointy w `mbr/laborant/routes.py` (część istniejącego blueprinta `laborant`):

```
GET    /api/ebr/<int:ebr_id>/uwagi
PUT    /api/ebr/<int:ebr_id>/uwagi
DELETE /api/ebr/<int:ebr_id>/uwagi
GET    /api/ebr/<int:ebr_id>/uwagi/historia
```

### `GET /api/ebr/<id>/uwagi`

Response:
```json
{
  "tekst": "Dodano 500 kg NaOH, brak analizy",
  "dt": "2026-04-11T14:32:10",
  "autor": "kowalski",
  "historia": [
    {"id": 12, "tekst": "Wersja poprzednia", "action": "update",
     "autor": "nowak", "dt": "2026-04-11T12:15:03"},
    {"id": 7,  "tekst": null, "action": "create",
     "autor": "nowak", "dt": "2026-04-11T11:02:41"}
  ]
}
```

`dt` + `autor` na poziomie root to **aktualny** stan (z ostatniego wpisu historii lub z sesji tworzącej). Jeśli `uwagi_koncowe IS NULL` → `tekst: null`, `dt: null`, `autor: null`.

### `PUT /api/ebr/<id>/uwagi`

Dekoratory:
```python
@login_required
@role_required('laborant', 'laborant_kj', 'laborant_coa', 'admin')
```

Request: `{"tekst": "..."}`

Walidacja:
1. `ebr_id` istnieje → inaczej 404
2. Szarża nie ma `status='cancelled'` → inaczej 400 `{"error": "Nie można edytować notatki anulowanej szarży"}`
3. `len(tekst.strip()) <= 500` → inaczej 400 `{"error": "Za długie (max 500 znaków)"}`

Logika:
1. `BEGIN TRANSACTION`
2. Odczyt `SELECT uwagi_koncowe FROM ebr_batches WHERE ebr_id = ?`
3. Detekcja akcji wg tabeli wyżej
4. Jeśli `create` / `update` / `delete` → `INSERT INTO ebr_uwagi_history` ze starą wartością
5. `UPDATE ebr_batches SET uwagi_koncowe = ?` (nowa wartość lub `NULL`)
6. Bump `sync_seq` na `ebr_batches` (zgodnie z istniejącym wzorcem sync)
7. `COMMIT`
8. Response: 200 z pełnym stanem (taki sam shape jak GET)

### `DELETE /api/ebr/<id>/uwagi`

Równoważne PUT z `tekst=""`. Zwraca 200 z pustym stanem.

### `GET /api/ebr/<id>/uwagi/historia`

Pełna lista wpisów historii, posortowana `dt DESC`. Używana opcjonalnie jeśli lista historii w hero musi być pobierana osobno (może się okazać niepotrzebne — GET /uwagi zwraca już wszystko).

### Helpery w `mbr/laborant/models.py`

```python
def get_uwagi(db, ebr_id: int) -> dict:
    """Zwraca {'tekst', 'dt', 'autor', 'historia': [...]}"""

def save_uwagi(db, ebr_id: int, tekst: str, autor: str) -> dict:
    """Zapisuje z detekcją akcji. Raises ValueError dla limitu długości
    i stanu 'cancelled'. Zwraca shape jak get_uwagi."""
```

## UI — wejście (blok notatki w analizie końcowej)

**Lokalizacja:** `mbr/templates/laborant/_fast_entry_content.html`, funkcja `renderCompletedView()` oraz widok aktywnego wpisywania parametrów końcowych.

### Stan bez notatki

Nad (albo na końcu) listy parametrów końcowych, mały przycisk wzywający:

```
[📝 + Notatka]
```

Styl: `border: 1px dashed var(--border); color: var(--text-dim); padding: 4px 10px; font-size: 11px; border-radius: 6px`. Hover → border/color teal. Klik → render bloku notatki z pustą textarea w trybie edycji.

### Stan z notatką (lub po kliknięciu "+")

Osobny blok **pod** listą parametrów (oddzielony wizualnie od wierszy `.cv-param`), z nagłówkiem w stylu `cv-params-head`:

```
┌─ UWAGI KOŃCOWE ─────────────────────────────┐
│ [textarea auto-expand, min 2 linie]         │
│ "Dodano 500 kg NaOH, bez analizy końcowej;  │
│  dopuszczone do wyrównania ze szarżą 2505"  │
│                                             │
│ 89 / 500                 [Zapisz] [Wyczyść] │
├─────────────────────────────────────────────┤
│ Historia (2):                               │
│  • 2026-04-11 14:32 — kowalski              │
│    Wersja poprzednia (truncate 60 znaków…)  │
│  • 2026-04-11 11:02 — nowak [create]        │
└─────────────────────────────────────────────┘
```

### Zachowanie

- **Textarea** `auto-grow` (wysokość rośnie wraz z zawartością). Zapis:
  - Debounced `oninput` co 800 ms (podobnie jak `autoSaveField()` dla parametrów)
  - `onblur` (natychmiastowo, jeśli jest niezsynchronizowana zmiana)
- **Licznik znaków** `N / 500` pod textarea po lewej. Kolor `var(--text-dim)`; przy `N > 500` zmiana na `var(--red)` + disable przycisku Zapisz. (Akceptuje limit 500 jako hard blocker po stronie klienta — serwer też go enforcuje.)
- **Wyczyść** → confirm dialog "Na pewno usunąć notatkę?" → DELETE
- **Historia** — zawsze widoczna jako lista pod aktualnym stanem (decyzja c=2). Format wpisu: `dt (YYYY-MM-DD HH:MM) — autor | tekst (truncate 60 z `title=` dla pełnego)`. Jeśli `historia.length === 0` → sekcja w ogóle się nie renderuje.

### Tryby dostępu

- **Tryb wpisywania analizy końcowej** (szarża nadal `open`, laborant wprowadza wyniki): textarea od razu edytowalna (tak jak parametry są od razu edytowalne).
- **Tryb view** (szarża `completed`, użytkownik jest uprawniony): textarea `readonly`, `.cv-notes-actions` ukryte, mały link "edytuj" w nagłówku bloku, który przełącza w tryb edit.
- **Tryb view bez uprawnień** (np. `technolog`): textarea `readonly`, brak linku "edytuj", historia widoczna.
- **Szarża `cancelled`**: textarea `readonly` niezależnie od roli (backend nie pozwoli zapisać, klient też blokuje).

### Nowe klasy CSS

```css
.cv-notes                  /* kontener bloku */
.cv-notes-head             /* nagłówek "UWAGI KOŃCOWE" */
.cv-notes-textarea         /* textarea auto-grow */
.cv-notes-counter          /* 127/500 */
.cv-notes-counter.over     /* czerwony gdy > limit */
.cv-notes-actions          /* kontener przycisków */
.cv-notes-history          /* lista historii */
.cv-notes-history-item     /* pojedynczy wpis */
.cv-notes-add-btn          /* "+ Notatka" w stanie bez notatki */
```

Definicje trafiają do `_fast_entry_content.html` w sekcji CSS (spójnie z innymi klasami `cv-*`), bez ruszania `mbr/static/style.css`.

## UI — lista szarż

**Lokalizacja:** `mbr/templates/laborant/szarze_list.html`, renderowanie tabeli szarż. Kolumna widoczna we wszystkich zakładkach (Otwarte / Ukończone / Anulowane).

### Nowa kolumna "Uwagi końcowe"

Pozycja: przed kolumną akcji (ostatnia merytoryczna). Szerokość: `max-width: 280px`, `min-width: 180px`.

**Rendering komórki:**
- Pusty `uwagi_koncowe` → myślnik `—` w kolorze `var(--text-dim)`
- Niepusty → truncate JS-em do 50 znaków (`text.length > 50 ? text.slice(0, 47) + '…' : text`) + natywny `title=` z pełnym tekstem + `overflow: hidden; text-overflow: ellipsis; white-space: nowrap` jako CSS fallback
- Kolor tekstu: `var(--text-sec)` (lekko wycofany, żeby nie konkurował z nr partii)

**Komórka nie jest klikalna niezależnie** — klik na wiersz tak jak dotychczas otwiera szarżę.

### Query

Query listujące szarże dostaje dodatkową kolumnę:
```sql
SELECT ..., uwagi_koncowe FROM ebr_batches WHERE ... ORDER BY ...
```

Helper w `mbr/laborant/models.py::list_batches()` (lub analogiczny) dostaje `uwagi_koncowe` w row-dict.

### Poza zakresem

- **Sortowanie** po kolumnie uwag — nie
- **Filtr "tylko z notatkami"** — nie (YAGNI)
- **Pełnotekstowe wyszukiwanie** — nie

## Cache, sync

- Po zapisie notatki bumpujemy `ebr_batches.sync_seq` — to spójne z istniejącym wzorcem synchronizacji danych szarży między klientami.
- Odpowiedzi API — `Cache-Control: no-store` (już włączone globalnie w `after_request` hooku).

## Testy

Nowy plik `tests/test_uwagi.py`, używa in-memory SQLite i `init_mbr_tables`.

### Model (`mbr/laborant/models.py`)

1. `save_uwagi`: `NULL → tekst` → historia `create`, nowa wartość w batch
2. `save_uwagi`: `tekst A → tekst B` → historia `update` z `tekst=A`
3. `save_uwagi`: `tekst → ''` → historia `delete` z `tekst=stary`, batch = NULL
4. `save_uwagi`: `NULL → '   '` → no-op, brak wpisu
5. `save_uwagi`: `tekst → ten_sam_tekst` → no-op
6. `save_uwagi`: `ebr_id` nieistniejący → exception
7. `save_uwagi`: tekst > 500 znaków → `ValueError`
8. `save_uwagi`: szarża `cancelled` → `ValueError`
9. `save_uwagi`: auto-trim whitespace na obu końcach
10. `get_uwagi`: zwraca aktualny stan + historię w kolejności `dt DESC`
11. `get_uwagi`: brak notatki → `{tekst: None, historia: []}`

### Routes

1. `PUT /api/ebr/<id>/uwagi` bez sesji → redirect do loginu / 401
2. `PUT` z rolą `technolog` → 403
3. `PUT` z rolą `laborant` → 200 + poprawny state
4. `PUT` z tekstem 501 znaków → 400 + pl komunikat
5. `PUT` na cancelled batch → 400 + pl komunikat
6. `DELETE` gdy była notatka → 200, historia `delete`
7. `DELETE` gdy notatki brak → 200, no-op
8. `GET` dla szarży z notatką → zwraca dict z `historia`
9. `GET` dla szarży bez notatki → zwraca dict z `tekst=null`, `historia=[]`

### Akcje — tabela decyzyjna

Jeden parametryzowany test sprawdzający macierz `(old, new) → (action, historia_len_delta)`.

Frontend JS nie jest testowany — zgodnie z istniejącą konwencją (tylko backend w pytest).

## Ryzyka

1. **Concurrent edits.** Dwóch laborantów edytuje naraz → historia append-only zachowuje oba wpisy, ale "aktualny" wygra ten kto zapisał drugi. **Akceptowalne** dla skali użycia (kilka osób na zmianę, znikome prawdopodobieństwo kolizji w sekundach). Jeśli kiedyś problem → `If-Match` z hashem.

2. **Wzrost historii.** Miliony wpisów przez lata. SQLite radzi sobie spokojnie, indeks `(ebr_id, dt DESC)` sprawia że `get_uwagi` jest O(log N) per szarża.

3. **Kasowanie szarży.** Jeśli jest hard-delete (w `admin`), potrzebny CASCADE na FK — do ustalenia w trakcie implementacji (check jak inne FK od `ebr_batches` są skonfigurowane; jeśli bez cascade, zostawiamy zgodnie z konwencją i kasujemy historię osobno w delete-handlerze).

4. **Długie tooltipy.** Natywny `title=` przy 500 znaków pokaże długi pasek. Pragmatycznie akceptowalne; ewentualna zamiana na custom tooltip w kolejnej iteracji.

5. **Tab w textarea.** Domyślne zachowanie przeglądarki (tab focus out) — OK, nie próbujemy przechwycić.

## Poza zakresem (YAGNI)

- Pełnotekstowe wyszukiwanie po uwagach
- Eksport uwag z historią do CSV/JSON
- Notyfikacje dla KJ ("nowa notatka na szarży X")
- Szablony notatek / autocomplete fraz
- Ustrukturyzowane linki do innych szarż (jako relacje DB, nie tylko tekst)
- Timeline aktywności oparty o `ebr_uwagi_history`
- Załączniki (pliki) do notatki
- Kolorowanie wierszy listy gdy jest notatka
- Renderowanie notatki na świadectwach jakości

## Akceptacja

Design został wspólnie przebrainstormowany sekcja po sekcji. Każda z 5 sekcji została potwierdzona przez użytkownika.

Następny krok: implementacja planu przez skill `superpowers:writing-plans`.
