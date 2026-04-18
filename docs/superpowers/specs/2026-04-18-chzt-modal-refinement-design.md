# ChZT Modal — Dopracowanie (DB, autosave, historia, UX)

**Data:** 2026-04-18
**Status:** spec do zatwierdzenia
**Bazuje na:** `docs/superpowers/specs/2026-04-15-chzt-formularz-design.md` (pierwsza iteracja, JSON files)

## Cel

Przenieść modal ChZT Ścieków z zapisu do plików JSON (obecny stan, `data/chzt/*.json`) na zapis do SQLite, dorzucić autosave draftu per wiersz (odporny na reload/crash/cross-device), stronę historii z 10 ostatnich sesji, oraz poprawić UX wpisywania (większe pola, bez spinnerów, inline walidacja, wskaźnik autosave'a, Enter-navigation).

## Zakres

- Nowy blueprint `mbr/chzt/` z dwiema tabelami DB.
- REST API dla autosave'u per wiersz + finalizacji sesji + historii.
- Podstrona `/chzt/historia` z paginacją (10/strona).
- Refactor UI modala w `narzedzia.html` — migracja do `mbr/chzt/templates/chzt_modal.html` include'owanego tam gdzie trzeba.
- Integracja z istniejącym audit log (`mbr.shared.audit`).
- Endpoint `GET /api/chzt/day/<data>` pod zewnętrzny skrypt uzupełniający Excel (transfer dataframe = **poza zakresem** tej iteracji, zostanie zaprojektowany osobno).

## Decyzje (z brainstorming sesji 2026-04-18)

| Pytanie | Decyzja |
|---|---|
| Scope autosave'a | Draft odporny na zamknięcie modala, F5, zamknięcie karty, restart — aż do explicite Clear (D). |
| Per-device vs cross-device | Cross-device przez DB draft (B) — wzorem miareczkowania (`mbr/static/calculator.js`). |
| Liczba sesji dziennie | Max jedna (A). Klucz `chzt_sesje.data UNIQUE`. |
| Semantyka "Zapisz" | Soft checkpoint (B). Finalizacja wystawia `finalized_at/by` jako marker; edycja po finalize nadal możliwa, logowana do audit. |
| Widoczność i edycja | Wszyscy edytują wszystko, zmiany audit-logowane (C). |
| Historia — gdzie | Osobna podstrona `/chzt/historia` (A). |
| Historia — ile | 10 ostatnich + paginacja. |
| Historia — kształt | Średnie i pH per punkt widoczne zwinięte; P1–P5 i audit per sesja na żądanie (expand). |
| Eksport | W tej iteracji: endpoint `GET /api/chzt/day/<data>`. Mechanizm transferu do drugiego kompa — osobna iteracja. |
| Autosave granularność | `debounce 400ms` po każdym keystroke (i). |
| Kształt tabel | Dwie tabele: `chzt_sesje` + `chzt_pomiary` (ii). |
| Focus flow | Enter w pH → P1; P1..P4 → następny P; P5 → pH następnego wiersza; P5 ostatniego → Zapisz. |

Jawnie **nie** wchodzi w zakres:
- pamiętanie `n_kontenery` per laborant (zawsze default 8),
- "zastosuj pH do wszystkich",
- status dnia w nagłówku karty przed otwarciem modala,
- push transfer dataframe (webhook/file drop).

## Architektura

Nowy blueprint `mbr/chzt/` wzorem istniejących (`paliwo`, `certs`, `registry`):

```
mbr/chzt/
  __init__.py          # chzt_bp = Blueprint("chzt", __name__)
  routes.py            # Flask handlers
  models.py            # sqlite3 helpers + init_chzt_tables()
  templates/
    chzt_modal.html    # modal (include'owany w narzedzia.html)
    chzt_historia.html # podstrona historii
```

Rejestracja w `mbr/app.py` razem z `init_chzt_tables()` wołanym z `create_app()`.

## Schemat DB

```sql
CREATE TABLE IF NOT EXISTS chzt_sesje (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    data         TEXT NOT NULL UNIQUE,        -- YYYY-MM-DD
    n_kontenery  INTEGER NOT NULL DEFAULT 8,
    created_at   TEXT NOT NULL,               -- ISO datetime
    created_by   INTEGER REFERENCES workers(id),
    finalized_at TEXT,                        -- NULL = draft
    finalized_by INTEGER REFERENCES workers(id)
);

CREATE TABLE IF NOT EXISTS chzt_pomiary (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sesja_id     INTEGER NOT NULL REFERENCES chzt_sesje(id) ON DELETE CASCADE,
    punkt_nazwa  TEXT NOT NULL,               -- "hala" | "rura" | "kontener N" | "szambiarka"
    kolejnosc    INTEGER NOT NULL,            -- 1..N+3 (hala=1, rura=2, kontenery=3..N+2, szambiarka=N+3)
    ph           REAL,
    p1           REAL,
    p2           REAL,
    p3           REAL,
    p4           REAL,
    p5           REAL,
    srednia      REAL,                        -- cache liczone backendem z niepustych pN (min 2)
    updated_at   TEXT NOT NULL,
    updated_by   INTEGER REFERENCES workers(id),
    UNIQUE(sesja_id, punkt_nazwa)
);

CREATE INDEX IF NOT EXISTS idx_chzt_sesje_data ON chzt_sesje(data DESC);
CREATE INDEX IF NOT EXISTS idx_chzt_pomiary_sesja ON chzt_pomiary(sesja_id);
```

Uwagi:
- `p1..p5` jako osobne kolumny (filtrowalne, zgodne ze stylem `raw sqlite3 / no ORM` projektu).
- `srednia` cache'owana na zapisie — historia czyta bez rachowania. Liczona jako średnia arytmetyczna niepustych pN, zaokrąglona do `REAL` (bez zaokrąglenia client-side — frontend formatuje `Math.round(...)`).
- `finalized_at = NULL` = draft. Po finalize dane pozostają edytowalne; kolejna edycja nie zeruje `finalized_at`, tylko loguje audit.
- Istniejące pliki `data/chzt/*.json` — **nie migrujemy**. Zostają jako archiwum. Nowy zapis idzie tylko do DB. (Jeśli w trakcie implementacji okaże się że warto — jednorazowy skrypt importujący to dodatkowa `scripts/import_chzt_jsons.py`.)

## Backend API

Wszystkie endpointy pod `@login_required` + `@role_required("laborant", "laborant_kj", "laborant_coa", "technolog", "admin")`, chyba że zaznaczono inaczej.

| Metoda | Path | Opis |
|---|---|---|
| `GET` | `/chzt/historia` | Podstrona historii (template, serwer-side render paginacji). Query: `?page=N` (default 1). |
| `GET` | `/api/chzt/session/today` | Zwraca dzisiejszą sesję; tworzy jeśli brak (z `n_kontenery=8` i wierszami hala, rura, kontener 1..8, szambiarka). |
| `GET` | `/api/chzt/session/<data>` | Konkretna data (YYYY-MM-DD). 404 jeśli brak. |
| `PATCH` | `/api/chzt/session/<id>` | Zmiana `n_kontenery`. Body: `{n_kontenery: int}`. Backend dosypuje/usuwa wiersze kontenerów. **Odrzuca usuwanie kontenerów z danymi** — 409 z listą nazw. |
| `PUT` | `/api/chzt/pomiar/<id>` | **Autosave wiersza**. Body: `{ph, p1, p2, p3, p4, p5}` (wszystkie pola opcjonalne — `null` znaczy puste). Backend: liczy `srednia`, zapisuje `updated_at/by`, loguje audit `chzt.pomiar.updated` z `diff_fields` (stare vs nowe). |
| `POST` | `/api/chzt/session/<id>/finalize` | Ustawia `finalized_at = now`, `finalized_by = current_user`. Walidacja: każdy wiersz ma pH i ≥2 niepuste pN. Błąd → 400 z listą wadliwych punktów. |
| `POST` | `/api/chzt/session/<id>/unfinalize` | **admin only.** Zeruje `finalized_at/by`. Loguje audit. |
| `GET` | `/api/chzt/day/<data>` | **Export frame** dla zewnętrznego skryptu. Odpowiedź: `{data, punkty: [{nazwa, ph, srednia}]}`. Tylko z sesji finalized — draft dostaje 404 (skrypt nie powinien brać niedokończonych). |
| `GET` | `/api/chzt/history?page=1` | Lista sesji DESC po `data`. 10/strona. Odpowiedź: `{sesje: [{id, data, n_kontenery, finalized_at, finalized_by_name, updated_at}], total, page, pages}`. |
| `GET` | `/api/chzt/session/<id>/audit-history` | Audit trail sesji (wszystkie `chzt.pomiar.updated` + `chzt.session.*` events) — dla tabu "Pokaż audit" w historii. |

### Audit events (via `mbr.shared.audit.log_event`)

| Event | Kiedy | Pola diff |
|---|---|---|
| `chzt.session.created` | Utworzenie nowej sesji (automatyczne przy pierwszym `GET /api/chzt/session/today`) | — |
| `chzt.pomiar.updated` | Każdy `PUT /api/chzt/pomiar/<id>` który rzeczywiście coś zmienił | `ph, p1, p2, p3, p4, p5` (via `diff_fields`) |
| `chzt.session.finalized` | `POST .../finalize` | — |
| `chzt.session.unfinalized` | `POST .../unfinalize` | — |
| `chzt.session.n_kontenery_changed` | `PATCH .../session/<id>` | `n_kontenery` |

Entity: `chzt_sesje` (id = sesja_id) dla session events; `chzt_pomiary` (id = pomiar_id) dla pomiar events.

## Autosave lifecycle

### Przy otwarciu modala

1. Frontend: `GET /api/chzt/session/today` (albo `/<data>` jeśli modal otwarty z historii z `?date=...`).
2. Backend: znajduje albo tworzy sesję. Przy tworzeniu seeduje `N+3` wierszy `chzt_pomiary` z pustymi polami.
3. Frontend renderuje tabelę wypełniając wartościami z `session.punkty`.
4. Nagłówek ustawia status:
   - `⚪ Nowa sesja` — jeśli wszystkie pola null.
   - `🟡 Draft · edytowano HH:MM` — jeśli cokolwiek wpisane, `finalized_at = NULL`.
   - `✓ Sfinalizowano HH:MM przez [name]` — jeśli `finalized_at ≠ NULL`.

### Podczas edycji

1. Laborant wpisuje liczbę → `oninput` debounce 400ms per-pole.
2. Po 400ms ciszy → `PUT /api/chzt/pomiar/<id>` z obecnym stanem całego wiersza (wszystkie pola `ph, p1..p5`).
3. UI wskaźnik w nagłówku:
   - `🟡 zapisywanie…` (od momentu keystroke do odpowiedzi)
   - `🟢 zapisano · HH:MM` (po udanym PUT, pokazywany `updated_at` z odpowiedzi)
   - `🔴 błąd połączenia — retry…` (po 1 failu — retry 3× co 1s, potem disable edycji + komunikat).
4. Każde pole ma własny timer — edycja wielu pól równocześnie = wiele niezależnych PUT-ów. Wyścigów nie ma, bo każdy PUT obejmuje cały wiersz (endpoint per pomiar_id).
5. Odpowiedź z PUT zawiera `srednia` — frontend renderuje na kolumnie "Średnia" natychmiast (kolor teal do 40 000, red powyżej — zachowane).

### Zmiana liczby kontenerów

1. Laborant zmienia "Kontenery" → klika "Generuj" → `PATCH /api/chzt/session/<id>` z `{n_kontenery: N}`.
2. Backend porównuje stare N vs nowe:
   - **Nowe > stare** — dorzuca wiersze `kontener (stare+1)..N` z pustymi polami. Aktualizuje `kolejnosc` szambiarki.
   - **Nowe < stare** — sprawdza czy kontenery `(nowe+1)..stare` mają cokolwiek poza null (`ph IS NOT NULL OR p1 IS NOT NULL OR ... OR p5 IS NOT NULL`). Jeśli tak → `409 Conflict` z listą nazw. Jeśli nie → usuwa. Aktualizuje kolejnosc szambiarki.
3. Po odpowiedzi frontend re-renderuje tabelę.
4. Przy 409: tooltip pod inputem "Kontener X ma wpisane dane. Wyczyść aby zmniejszyć."

### Finalize

1. Client-side walidacja: każdy wiersz ma pH (≠null) i ≥2 niepuste pN.
2. Wady → czerwona lewa krawędź wiersza + komunikat "min. 2 pomiary" / "brak pH" pod wierszem. Przycisk "Zapisz" disabled.
3. OK → `POST /api/chzt/session/<id>/finalize`.
4. Backend dubluje walidację (defense in depth); zwraca 400 jeśli wadliwe (sync'owane z client-side).
5. Po OK: nagłówek przełącza się na `✓ Sfinalizowano HH:MM`. Przycisk "Zapisz" znika, pojawia się info `✓ Zakończono · edycja nadal aktywna · audit: X zmian`.
6. Autosave dalej działa identycznie — każda zmiana `PUT /api/chzt/pomiar/<id>` idzie jak zwykle, dokłada audit event, NIE zeruje `finalized_at`.

### Crash/reload recovery

DB jest SSOT. Nic dodatkowego — otwarcie modala zawsze robi `GET /api/chzt/session/today` i odtwarza stan. Brak `localStorage`.

## UX modala — szczegóły

### Inputy (główny pain point)

- `type="text"` + `inputmode="decimal"` + `pattern="[0-9]*[.,]?[0-9]*"` → **znika spinner** (strzałki), znika problem z przecinkiem na mobile.
- Walidacja regex client-side + `parseFloat(val.replace(',', '.'))` przed PUT.
- Rozmiar: `width: 88px; height: 34px; font-size: 14px; padding: 6px 8px;` (było `58×~24px, 11px`). pH zostaje węższy: `width: 64px`.
- Font: `var(--mono)` zostaje.
- Focus: teal border + glow (bez zmian).
- Invalid: czerwona ramka `1.5px solid var(--red)`, subtelny shake 200ms przy blur z błędną wartością (regex fail).

### Tabela

- Modal szerokości ~880px bez zmian.
- Kolumny: `PUNKT · pH · P1 · P2 · P3 · P4 · P5 · ŚREDNIA` bez zmian.
- Wiersz invalid (przy próbie finalize): czerwona lewa krawędź + komunikat pod wierszem.

### Nagłówek modala

```
ChZT Ścieków · 18.04.2026     [status-pill]               ×
[opcjonalna druga linia: ✓ Sfinalizowano ... przez ...]
```

- `status-pill` po prawej od tytułu (przed close):
  - `⚪ Nowa sesja`
  - `🟡 zapisywanie…`
  - `🟢 zapisano · HH:MM`
  - `🔴 błąd połączenia`
- Druga linia (jeśli finalized): `✓ Sfinalizowano HH:MM przez Jan K. — edycja możliwa, logowana`.

### Toolbar

- Bez zmian wizualnie. "Generuj" wywołuje teraz `PATCH`, nie tylko re-render.
- Tooltip błędu przy odrzuceniu.

### Footer

- `finalized_at = NULL`: przycisk `Zapisz (finalizuj)` po prawej.
- `finalized_at ≠ NULL`: info `✓ Zakończono HH:MM · edycja aktywna · X zmian w audit` po prawej.

### Focus flow (z decyzji 10b)

- `Tab` — default (wierszami).
- `Enter`:
  - w pH → P1 tego samego wiersza.
  - w P1..P4 → następny P.
  - w P5 → pH następnego wiersza.
  - w P5 ostatniego wiersza → przycisk "Zapisz".

## UX historii — szczegóły

### `/chzt/historia`

Template `chzt_historia.html`, rozszerza `base.html`.

**Nagłówek strony:**
```
ChZT Ścieków — Historia                    [Nowy pomiar →]
10 ostatnich sesji · strona 1/3
```

**Karta per sesja:**

```
┌──────────────────────────────────────────────────────────┐
│ 18.04.2026 · piątek            ✓ Sfinalizowano · Jan K.  │
│ 10 punktów · 8 kontenerów                                 │
├──────────────────────────────────────────────────────────┤
│  PUNKT          pH    ŚREDNIA ChZT                        │
│  hala           10      25 481                            │
│  rura           10      18 337                            │
│  kontener 1     11      11 167                            │
│  ...                                                       │
│  szambiarka     10      15 238                            │
│                                                            │
│  [Pokaż pomiary P1–P5]  [Pokaż audit]  [Edytuj]          │
└──────────────────────────────────────────────────────────┘
```

- Zwinięta: średnie + pH per punkt, bez klikania.
- `[Pokaż pomiary P1–P5]` — expand in-place, dodaje kolumny P1–P5 read-only.
- `[Pokaż audit]` — expand z listą zmian (`chzt.pomiar.updated` + `chzt.session.*` events) via `query_audit_history_for_entity(db, 'chzt_sesje', id)` + podobnie dla pomiarów.
- `[Edytuj]` — otwiera modal ChZT z `?date=<data>` (modal obsługuje param — ładuje `GET /api/chzt/session/<data>` zamiast `/today`).

**Status markery w nagłówku karty:**
- Draft: `🟡 Draft · ostatnia zmiana 14:23`.
- Finalized: `✓ Sfinalizowano · [imie_nazwisko] · 15:10`.

**Paginacja:** `← Nowsze | 1 2 3 ... 8 | Starsze →`, 10/strona.

**Pusty stan:** `Brak zapisanych pomiarów ChZT. [Zacznij nową sesję]`.

**Link z Narzędzi:** w `narzedzia.html` dodajemy drugą kartę obok "ChZT Ścieków" — "Historia ChZT" (osobna `narz-card`).

## Export endpoint

`GET /api/chzt/day/<data>` — dla zewnętrznego skryptu uzupełniającego Excel.

Odpowiedź:
```json
{
  "data": "2026-04-18",
  "finalized_at": "2026-04-18T15:10:22",
  "punkty": [
    {"nazwa": "hala", "ph": 10, "srednia": 25481},
    {"nazwa": "rura", "ph": 10, "srednia": 18337},
    {"nazwa": "kontener 1", "ph": 11, "srednia": 11167},
    ...
  ]
}
```

- Tylko sesje z `finalized_at ≠ NULL`. Draft → 404 `{error: "Sesja nie sfinalizowana"}`.
- Autoryzacja: `@login_required`. Skrypt na drugim kompie na razie loguje się jak laborant (sesja ciasteczkowa). API token = osobna iteracja.
- Mechanizm transferu dataframe do drugiego kompa (push webhook / file drop / cron pull) = **osobna iteracja**, zaprojektowana gdy temat dojrzeje.

## Pliki — lista zmian

### Nowe

| Plik | Zawartość |
|---|---|
| `mbr/chzt/__init__.py` | `chzt_bp = Blueprint("chzt", __name__)` |
| `mbr/chzt/routes.py` | Wszystkie endpointy powyżej |
| `mbr/chzt/models.py` | `init_chzt_tables()`, helpery SQL (`get_or_create_today_session`, `get_session_by_date`, `update_pomiar`, `finalize_session`, `list_sessions_paginated`, ...) |
| `mbr/chzt/templates/chzt_modal.html` | Markup modala (migracja z `narzedzia.html`) |
| `mbr/chzt/templates/chzt_historia.html` | Strona historii |
| `mbr/chzt/static/chzt.js` | Logika JS modala + historii (migracja + rewrite z `narzedzia.html`) |
| `mbr/chzt/static/chzt.css` | Style (migracja z inline `<style>` w `narzedzia.html`) |
| `tests/test_chzt.py` | Testy endpointów + autosave flow + finalize walidacja |

### Modyfikowane

| Plik | Zmiana |
|---|---|
| `mbr/app.py` | Rejestracja `chzt_bp`, wywołanie `init_chzt_tables()` w `create_app()` |
| `mbr/templates/technolog/narzedzia.html` | Usunięcie inline markup/JS/CSS modala; zamiast tego `{% include "chzt/chzt_modal.html" %}` + `<script src="{{ url_for('chzt.static', filename='chzt.js') }}?v=1">`. Druga karta "Historia ChZT". |
| `mbr/registry/routes.py` | Usunięcie starego endpointu `POST /api/chzt/save` (migracja zerwana — nowy modal używa nowego API). |

### Nie ruszamy

- `data/chzt/*.json` — archiwum, zostaje na dysku.
- `mbr/shared/audit.py` — używamy istniejących funkcji (`log_event`, `diff_fields`, `query_audit_history_for_entity`).

## Testy

`tests/test_chzt.py` — scenariusze:

1. **Create today's session** — `GET /api/chzt/session/today` tworzy sesję jeśli brak, zwraca istniejącą jeśli jest. Audit `chzt.session.created` emitowany raz.
2. **Autosave pomiar** — `PUT /api/chzt/pomiar/<id>` zapisuje pola, liczy średnią, loguje audit diff.
3. **Concurrent autosaves** — dwa równoczesne PUT-y na różne pomiary nie krzyżują się.
4. **Change n_kontenery up** — `PATCH` dodaje wiersze.
5. **Change n_kontenery down, no data** — `PATCH` usuwa wiersze.
6. **Change n_kontenery down, with data** — `PATCH` → 409 z listą.
7. **Finalize valid** — `POST .../finalize` przechodzi, ustawia timestamp+user, audit event.
8. **Finalize invalid** (brak pH / <2 pN) — 400 z listą wadliwych punktów.
9. **Edit after finalize** — PUT na pomiar działa, audit event, `finalized_at` nie zerowane.
10. **Unfinalize admin-only** — laborant dostaje 403, admin OK.
11. **Export endpoint (finalized)** — `GET /api/chzt/day/<data>` zwraca payload.
12. **Export endpoint (draft)** — 404.
13. **History pagination** — 10/strona, DESC po dacie, poprawne `total/pages`.
14. **Audit history dla sesji** — zwraca wszystkie eventy tej sesji.

Wzorem `tests/test_parametry_registry.py` i `tests/test_audit_phase4_wyniki.py` — fixture'y z in-memory sqlite, `init_mbr_tables()` + `init_chzt_tables()`.

## Nie w zakresie tej iteracji

- Push dataframe do zewnętrznego kompa (webhook / file drop / cron pull) — osobny spec gdy temat wejdzie.
- API token dla skryptu (zamiast sesji ciasteczkowej) — gdy transfer mechanism dojrzeje.
- Migracja istniejących `data/chzt/*.json` do DB — jeśli się okaże potrzebne, to jednorazowy skrypt `scripts/import_chzt_jsons.py`.
- Pamiętanie `n_kontenery` per laborant.
- "Zastosuj pH do wszystkich".
- Status dnia w nagłówku karty w Narzędziach przed otwarciem modala.
- Eksport CSV/XLSX z podstrony historii (tylko JSON endpoint).

## Ryzyka i otwarte kwestie

- **Race przy tworzeniu dzisiejszej sesji** — dwóch laborantów otwierających modal jednocześnie przed 1. użyciem dziś. Rozwiązanie: `INSERT OR IGNORE` + follow-up SELECT; sesja z `UNIQUE(data)` gwarantuje że będzie jedna. Audit event `chzt.session.created` emitujemy tylko z wygranej INSERT.
- **Audit log volume** — przy aktywnym wpisywaniu 1 PUT = 1 audit event. Przy 10 punktach × 6 pól × 50 keystroke'ów można narobić. Mitygacja: `log_event` wywołujemy tylko gdy `diff_fields` zwróci niepustą listę (tj. wartość się zmieniła per commit). Przy debounce 400ms i stabilnych wartościach będzie ~6 eventów per wiersz na sesję.
- **Eksport skrypt wymaga ciasteczka sesji** — trzeba dać skryptowi fakturę logowania (np. dedykowany konto `skrypt_chzt` + `.netrc`). Zrobimy gdy dojdzie do transferu.
