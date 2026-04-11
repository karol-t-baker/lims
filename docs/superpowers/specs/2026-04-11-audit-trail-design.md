# Audit Trail — Design

**Data:** 2026-04-11
**Status:** Draft → do recenzji
**Cel:** Pełny audit trail (trail log audytowy) pokrywający wszystkie operacje mutujące w LIMS K40GLO.

## Kontekst

System LIMS/MBR-EBR działa w produkcji na zakładzie chemicznym iChegina K40GLO (Flask + SQLite, laboranci pracują parami, świadectwa jakości generowane z DOCX → Gotenberg → PDF). Aktualnie w bazie istnieje tabela `audit_log` (dt, tabela, rekord_id, pole, stara_wartosc, nowa_wartosc, zmienil) używana **tylko w dwóch miejscach**:

- `mbr/laborant/models.py:481` — log zmian wyników lab
- `mbr/etapy/models.py:45` — log zmian zdarzeń etapów

Dodatkowo świeża tabela `ebr_uwagi_history` (commit `04f1a09`) loguje historię uwag końcowych szarży. `mbr/laborant/routes.py:213 get_audit_log(ebr_id)` udostępnia historię per szarża.

Reszta aplikacji (auth, workers, technolog/MBR, certs, admin, paliwo, rejestry) **nie loguje niczego**. Cel: pełne pokrycie akcji mutujących, panel admina, historia per-rekord dla EBR/MBR/certs.

## Cel regulacyjny / zakres

**Opcja B** — wewnętrzna traceability + ISO-owska dyscyplina.

- Pełne logi kto/kiedy/co/skąd
- Per-rekord historia w UI (EBR, MBR, certs)
- Panel admina z filtrami + eksport CSV
- Retencja **2 lata** w aktywnej bazie + archiwizacja do JSONL.gz
- **Bez** formalnych e-podpisów, bez hash-chain / tamper-evident, bez reason-for-change
- **Bez** logowania dostępów readonly (brak read-logu)

## Model aktora

Wielu aktorów na jedno zdarzenie — uzasadnienie: laboranci pracują parami (lub więcej) w laboratorium, oboje odpowiadają za wynik analizy.

| Rola akcji | Aktor(zy) w logu |
|---|---|
| `laborant` (wpisy wyników, zdarzenia etapów, zamknięcie szarży, uwagi, przepompowania) | **Wszyscy z `session['shift_workers']`** — potwierdzona zmiana; oboje/więcej jako współwykonawcy |
| `laborant_coa` (wystawienie świadectwa, edycja końcowa certyfikatu) | **Jedna osoba** wybrana na formularzu — `wystawil` z `certs/routes.py:62` (istniejący mechanizm) |
| `laborant_kj` (kierownik kontroli jakości — akceptacje, decyzje) | Pojedynczy — zalogowany user |
| `technolog` (MBR, rejestry słowników) | Pojedynczy — zalogowany user |
| `admin` | Pojedynczy — zalogowany user |
| `system` (migracje, archiwizacja, startup) | Wirtualny aktor `worker_id=NULL`, `actor_login='system'`, `actor_rola='system'` |

### Invariant: pusta zmiana blokuje zapis

Rola `laborant` nie może zapisywać niczego bez niepustego `session['shift_workers']`. Aktualnie `mbr/laborant/routes.py:156-166` ma fallback na zalogowanego usera — **usuwamy ten fallback**. Helper `audit.actors_from_request()` dla roli `laborant` z pustą zmianą podnosi `ShiftRequiredError` → Flask error handler zwraca `HTTP 400 {"error": "shift_required"}` → front pokazuje modal „Potwierdź zmianę".

Pozostałe role (`laborant_kj`, `laborant_coa`, `technolog`, `admin`) nie wymagają potwierdzonej zmiany — aktor pochodzi z `session['user']` lub z formularza (COA).

Konsekwencja: jeśli wpis istnieje w `audit_log` dla akcji laboranta, to zmiana była potwierdzona — nigdy nie musimy obsługiwać „shift_missing" w logu.

## Granularność: hybryda zdarzenie + diff pól

Jedna tabela `audit_log` z kolumnami zdarzeniowymi (event_type, entity, payload), a dla UPDATE-ów DB dorzucamy `diff_json` jako listę `[{pole, stara, nowa}]`. Daje dwa widoki: „co zrobił user X" + „historia pola Y rekordu Z".

JSON-blobs (`etapy_json`, `surowce_json`, `parametry_lab`) są logowane jako **jedno pole** ze starym i nowym JSON-em — bez deep-diffu (za dużo pracy za mało zysku).

## Schemat bazy

Stary `audit_log` zostaje zburzony i przebudowany; dwa istniejące call-site'y migrują na nowy helper.

```sql
CREATE TABLE audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    dt              TEXT NOT NULL,              -- ISO8601 UTC
    event_type      TEXT NOT NULL,              -- 'ebr.wynik.saved', 'auth.login', 'cert.generated'
    entity_type     TEXT,                       -- 'ebr' | 'mbr' | 'cert' | 'worker' | ... | NULL
    entity_id       INTEGER,                    -- NULL gdy nie dotyczy
    entity_label    TEXT,                       -- zdenormalizowany podpis (numer szarży, nazwa produktu) — log czytelny bez JOIN
    diff_json       TEXT,                       -- [{pole, stara, nowa}, ...] lub NULL
    payload_json    TEXT,                       -- dodatkowy kontekst akcji (ścieżka PDF, szablon, ...)
    context_json    TEXT,                       -- {ebr_id, produkt, ...} extra fields z g
    request_id      TEXT,                       -- UUID per request; korelacja wpisów z jednego submitu
    ip              TEXT,
    user_agent      TEXT,
    result          TEXT NOT NULL DEFAULT 'ok'  -- 'ok' | 'error'
);

CREATE TABLE audit_log_actors (
    audit_id        INTEGER NOT NULL REFERENCES audit_log(id) ON DELETE CASCADE,
    worker_id       INTEGER,                    -- NULL dla 'system' lub nieznanego przy auth.login_failed
    actor_login     TEXT NOT NULL,              -- snapshot username/loginu
    actor_rola      TEXT NOT NULL,              -- snapshot roli ('laborant', 'admin', 'system', ...)
    PRIMARY KEY (audit_id, actor_login)
);

CREATE INDEX idx_audit_log_dt          ON audit_log(dt DESC);
CREATE INDEX idx_audit_log_entity      ON audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_log_event_type  ON audit_log(event_type);
CREATE INDEX idx_audit_log_request     ON audit_log(request_id);
CREATE INDEX idx_audit_actors_worker   ON audit_log_actors(worker_id);
```

**Uzasadnienia:**

- `entity_label` (denormalizacja) — listingi panelu admina czytelne bez JOIN-ów do 6 tabel; szarża/produkt mogą zmienić nazwę lub zostać usunięte, log trzyma podpis z momentu akcji.
- `result = 'ok' | 'error'` — pozwala logować nieudane loginy, odrzucone zapisy z pustą zmianą, błędy generowania PDF.
- PK `(audit_id, actor_login)` — używamy `actor_login` zamiast `worker_id` w kluczu, bo `worker_id` jest NULL-owalne dla aktora `system` i SQLite traktuje NULL-e jako różne (NULL ≠ NULL w UNIQUE), co złamałoby unikalność. `actor_login` jest zawsze NOT NULL.
- Indeksy pokrywają typowe filtry panelu admina i historie per-rekord.

## Helper `mbr/shared/audit.py`

Nowy moduł, jeden punkt wejścia. Rozmiar orientacyjnie ~150–200 linii.

```python
# Stałe event_type — trzymane w module, żeby literówka nie stworzyła nowego event_type
EVENT_AUTH_LOGIN = 'auth.login'
EVENT_AUTH_LOGOUT = 'auth.logout'
EVENT_AUTH_PASSWORD_CHANGED = 'auth.password_changed'
EVENT_WORKER_CREATED = 'worker.created'
# ... (pełna lista w sekcji „Taksonomia eventów")

class ShiftRequiredError(Exception):
    """Laborant próbował zapisać bez potwierdzonej zmiany."""

def log_event(
    event_type: str,
    *,
    entity_type: str | None = None,
    entity_id: int | None = None,
    entity_label: str | None = None,
    diff: list[dict] | None = None,
    payload: dict | None = None,
    actors: list[dict] | None = None,   # jawnie podane; None → actors_from_request()
    result: str = 'ok',
    db=None,                             # użyj istniejącej transakcji
) -> int:
    """Zapisuje wpis audytu. Zwraca audit_log.id.
    Zapis w tej samej transakcji co akcja biznesowa — log commituje się razem z mutacją."""

def actors_from_request() -> list[dict]:
    """Rozstrzyga aktorów wg reguł ról:
    - 'laborant' → wszyscy z session['shift_workers']; pusty → ShiftRequiredError
    - 'laborant_kj', 'technolog', 'admin' → [session['user']]
    - 'laborant_coa' → route powinien przekazać actors= jawnie (explicit wybór z formularza)
    """

def actors_explicit(worker_ids: list[int]) -> list[dict]:
    """Dla COA i innych akcji z formularzowym wyborem wystawiającego."""

def actors_system() -> list[dict]:
    """[{worker_id: None, actor_login: 'system', actor_rola: 'system'}]"""

def diff_fields(old: dict, new: dict, keys: list[str]) -> list[dict]:
    """Zwraca listę zmienionych pól w formacie [{pole, stara, nowa}].
    Serializuje non-skalary do JSON. Zwraca [] jeśli nic się nie zmieniło."""

def query_audit_log(filters: dict, limit: int, offset: int) -> list[Row]:
    """Helper panelu admina — parametryzowany WHERE + paginacja."""
```

### Automatyczne wypełnianie kontekstu

`log_event` wypełnia automatycznie:

- `dt` = `datetime.utcnow().isoformat()`
- `request_id` = `g.audit_request_id` (UUID ustawiany w `before_request`)
- `ip` = `request.remote_addr` (uwzględniając `X-Forwarded-For` za nginx)
- `user_agent` = `request.headers.get('User-Agent')`
- `context_json` = scala `payload` + extra fields z `g` (jeśli route dodał `ebr_id`, `produkt`)

### Transakcyjność

`log_event` pisze do TEJ SAMEJ transakcji co akcja biznesowa — route przekazuje swoje `db` przez kwarg `db=`. Helper nie otwiera własnej sesji. Albo mutacja i log commitują się razem, albo nic — brak osieroconych wpisów.

### Podpięcie w `create_app()`

```python
@app.before_request
def _audit_setup():
    g.audit_request_id = str(uuid.uuid4())

@app.errorhandler(ShiftRequiredError)
def _shift_required(e):
    return jsonify({"error": "shift_required"}), 400
```

## Taksonomia event_type

Konwencja: `<domena>.<byt>.<akcja>` — lowercase, kropki, czasownik past tense.

**auth** (`mbr/auth/routes.py`): `auth.login` (ok/error), `auth.logout`, `auth.password_changed`

**workers** (`mbr/workers/routes.py`): `worker.created`, `worker.updated`, `worker.deleted`, `shift.changed`
- `shift.changed` ma specjalną regułę aktora: user z sesji, nie zmiana — bo zmiana się właśnie ustawia

**mbr/technolog/rejestry** (`mbr/technolog/`, `mbr/etapy/`, `mbr/parametry/`, `mbr/registry/`, `mbr/zbiorniki/`): `mbr.template.created/updated/deleted`, `etap.catalog.created/updated/deleted`, `parametr.created/updated/deleted`, `metoda.created/updated/deleted`, `zbiornik.created/updated/deleted`, `produkt.created/updated/deleted`, `registry.entry.created/updated/deleted`

**ebr/laborant** (`mbr/laborant/`): `ebr.batch.created`, `ebr.batch.status_changed`, `ebr.stage.event_added/updated/deleted`, `ebr.wynik.saved/updated/deleted`, `ebr.uwagi.updated`, `ebr.przepompowanie.added/updated`

**certs** (`mbr/certs/`): `cert.generated`, `cert.values.edited`, `cert.cancelled`, `cert.config.updated`

**paliwo** (`mbr/paliwo/`): `paliwo.wniosek.created/updated/deleted`, `paliwo.osoba.created/updated/deleted`

**admin** (`mbr/admin/`): `admin.backup.created`, `admin.batch.cancelled`, `admin.settings.changed`, `admin.feedback.exported`

**system**: `system.migration.applied`, `system.audit.archived`

### Relacja do istniejącego `ebr_uwagi_history`

Świeża tabela (commit `04f1a09`) ma własny widok UI i stabilny przepływ. **Nie migrujemy jej do audit_log** — audit dodatkowo loguje `ebr.uwagi.updated` jako zdarzenie (dubel logiczny), ale `ebr_uwagi_history` pozostaje jako SSOT dla widoku uwag końcowych. Powód: minimalne ryzyko regresji w świeżo wdrożonym feature.

## UI

### Panel admina — `/admin/audit`

Nowy route w `mbr/admin/routes.py`, szablon `mbr/templates/admin/audit.html`, widoczny tylko dla roli `admin`. Nowa pozycja „Audit trail" w railu admina.

**Layout:**

- Pasek filtrów: data od/do, event_type (dropdown z grupami: auth.*, ebr.*, cert.*, mbr.*, admin.*, system.*), entity_type, aktor (dropdown workers), wolny tekst, przycisk „Filtruj", „Eksport CSV"
- Tabela: kolumny `data/godz | event | byt (entity_label) | aktorzy`, klik rozwija wiersz z detalem (`diff_json` jako tabelka pole/stara/nowa, `payload_json` w `<pre>`, link „pokaż wszystkie z tego kliknięcia" filtrujący po `request_id`)
- Paginacja: 100/strona, server-side `LIMIT/OFFSET`
- Prawy górny róg: przycisk „Archiwizuj starsze niż 2 lata"

**Filtry → WHERE** w `query_audit_log(filters)`:

```python
dt BETWEEN ? AND ?
event_type LIKE ?
entity_type = ?
EXISTS (SELECT 1 FROM audit_log_actors WHERE audit_id=audit_log.id AND worker_id=?)
(entity_label LIKE ? OR payload_json LIKE ?)  -- free-text
```

**Eksport CSV** — ten sam WHERE bez LIMIT, strumień `text/csv`, kolumny: `dt, event_type, entity_type, entity_id, entity_label, actors, result, diff, payload, ip, request_id`. Diffy/payloady flattowane jako skompaktowany JSON.

**Archiwizacja** — `POST /admin/audit/archive` z modalem „Wpisów do archiwizacji: N, kontynuować?":

1. SELECT wpisów `dt < now - 2 lata`
2. Zapis do `data/audit_archive/audit_<rok>.jsonl.gz` (linia per wpis, z zagnieżdżonymi aktorami)
3. DELETE zarchiwizowanych wpisów
4. `log_event('system.audit.archived', payload={count, path, cutoff})`
5. Wszystko w jednej transakcji

### Historia per-rekord

**Widok szarży EBR** (`mbr/templates/laborant/szarze_list.html` + detal) — sekcja/zakładka „Historia" pod uwagami. Istniejący endpoint `get_audit_log(ebr_id)` w `laborant/routes.py:213` **przepisujemy** na nową tabelę: zwraca wszystkie wpisy `entity_type='ebr' AND entity_id=?` — status changes, wyniki, etapy, uwagi, przepompowania, powiązane świadectwa.

**Widok szablonu MBR w technolog** — nowa sekcja „Historia zmian" pokazująca `entity_type='mbr' AND entity_id=?`. Wartość dla audytu klienta (kto modyfikował recepturę).

**Widok świadectwa w certs** — sekcja „Historia" pokazująca `entity_type='cert' AND entity_id=?`. Pokaże wystawienie, edycje wartości, anulowania.

### Helper Jinja do aktorów

```python
# mbr/shared/filters.py
@app.template_filter('audit_actors')
def audit_actors(audit_row):
    """Renderuje listę aktorów jako 'AK, MW' (skrócone), pełne nazwy w tooltipie."""
```

## Migracja schematu

`scripts/migrate_audit_log_v2.py`, idempotentny (sprawdza `sqlite_master` przed każdym krokiem):

1. `ALTER TABLE audit_log RENAME TO audit_log_v1`
2. `CREATE TABLE audit_log` (nowa wersja) + `CREATE TABLE audit_log_actors` + indeksy
3. Backfill `audit_log_v1` → `audit_log`:
   - `event_type='legacy.field_change'`
   - `entity_type=<tabela>`, `entity_id=<rekord_id>`
   - `diff_json=[{pole, stara, nowa}]`
   - Wpis do `audit_log_actors`: resolve `zmienil` → `worker_id` jeśli się da, inaczej `worker_id=NULL, actor_login=zmienil, actor_rola='unknown'`
4. Weryfikacja: `SELECT COUNT(*)` przed/po musi się zgadzać
5. `DROP TABLE audit_log_v1` (faza 7 — po stabilizacji; wstępnie zostawiamy dla rollbacku)

## Fazowanie wdrożenia

Każda faza = osobna PR-ka, samodzielnie rollback-owalna.

### Faza 1 — Infrastruktura (niezależna)

- `scripts/migrate_audit_log_v2.py`
- `mbr/shared/audit.py` — helper + stałe event_type + `ShiftRequiredError`
- `create_app()` — `before_request` (UUID), error handler
- `tests/test_audit_helper.py` — unit testy helpera
- **Zero integracji w blueprintach.** Bezpieczne do wdrożenia.

### Faza 2 — Panel admina + archiwizacja (niezależna)

- `/admin/audit` + szablon + filtry + paginacja + eksport CSV
- `/admin/audit/archive` + modal
- Nowy rail w menu admina
- `query_audit_log()` + filtr Jinja `audit_actors`
- `tests/test_admin_audit.py` — e2e panel z fake data

### Faza 3 — Auth + workers (stabilne)

- Integracja `auth.*`, `worker.*`, `shift.changed`
- **Usunięcie fallbacka** w `laborant/routes.py:156-166` + enforcement „pusta zmiana blokuje zapis" (osobny commit w tej samej PR-ce, notatka w changelogu — behaviour change)
- Testy integracyjne endpointów

### Faza 4 — EBR laborant (core)

- `ebr.*` — wszystkie
- Migracja dwóch istniejących call-site'ów (`laborant/models.py:481`, `etapy/models.py:45`) na helper
- Przepisanie `get_audit_log(ebr_id)` na nową tabelę
- Sekcja „Historia" w widoku szarży
- **Wait-for:** faza 3

### Faza 5 — MBR + rejestry + słowniki (opóźnione)

- `mbr.template.*`, `etap.catalog.*`, `parametr.*`, `metoda.*`, `zbiornik.*`, `produkt.*`, `registry.entry.*`
- Sekcja „Historia zmian" w widoku szablonu MBR
- **Wait-for:** `parametry-centralizacja` + `produkty-centralizacja` wylądowane w main

### Faza 6 — Certs + paliwo + admin

- `cert.*` z regułą COA (istniejący `wystawil` z `certs/routes.py:62`), `paliwo.*`, `admin.*`
- Sekcja „Historia" w widoku świadectwa
- **Wait-for:** `cert-db-ssot` + `cert-parameter-editor` wylądowane w main

### Faza 7 — Czyszczenie długu

- Usunięcie `audit_log_v1` (jeśli jeszcze jest)
- **Sweep test w CI** — parametryzowany listą endpointów, sprawdza że udany submit zostawia ≥1 wpis w `audit_log`. Nowy endpoint bez `log_event` → test padnie.
- Dokumentacja w `CLAUDE.md`: sekcja „Audit trail — jak dodać log_event dla nowego endpointa"

## Retencja i archiwum

- **2 lata aktywnie** w `audit_log`
- **Ręczna archiwizacja** — przycisk w panelu admina (`/admin/audit/archive`). Powód: admin ma kontrolę, nic nie dzieje się w tle bez jego wiedzy.
- **Format archiwum:** `data/audit_archive/audit_<rok>.jsonl.gz` — linia per wpis, struktura: `{audit_log_row..., actors: [...]}`. Gzipped żeby oszczędzić miejsce, JSONL żeby dało się streamować przy odtwarzaniu.
- `data/audit_archive/` jest w zasięgu istniejącego systemd backup (`deploy/auto-deploy.sh`), więc archiwa lecą razem z resztą.

## Testy

### Unit testy helpera (faza 1)

- `log_event` zapisuje wiersz + aktorów w jednej transakcji; rollback biznesowy zabiera też log
- `actors_from_request()` dla każdej roli + edge case pusty shift → `ShiftRequiredError`
- `actors_explicit()` i `actors_system()` zwracają poprawne struktury
- `diff_fields()` ignoruje niezmienione pola, serializuje dict/list do JSON, zwraca `[]` dla identycznych
- Indeksy istnieją po migracji (odczyt `sqlite_master`)

### Testy panelu (faza 2)

- Filtry (data, event_type, entity_type, worker_id, free-text) — każdy osobno i łącznie
- Paginacja: 100/strona, offset działa
- Eksport CSV: content-type, escapowanie, diffy flattowane
- Archiwizacja: wpisy >2 lata znikają z DB, `.jsonl.gz` powstaje, `system.audit.archived` wpisany, licznik się zgadza
- Dostęp: non-admin → 403

### Testy integracyjne (fazy 3-6)

Dla każdego kluczowego endpointu własnego blueprinta:

- `audit_log` zawiera wpis o oczekiwanym `event_type`
- `audit_log_actors` ma oczekiwanych ludzi (wszystkich zmiany dla laboranta, jednego wystawiającego dla COA, zalogowanego dla admina/technologa)
- `diff_json` zawiera zmienione pola (nie zmienione — nie ma)
- `request_id` identyczny dla powiązanych wpisów z jednego submitu

### Sweep test (faza 7 — CI regression guard)

Test parametryzowany listą `[(url, method, payload)]`. Dla każdego: wyślij request, policz wpisy w `audit_log` przed/po, assert `count_after > count_before`. Nowy endpoint dodany bez `log_event` → test padnie → developer świadomie dodaje albo wyjmuje z listy.

## Out of scope

- E-podpisy / hash-chain / tamper-evident log
- Read-log (kto otworzył PDF, kto wyświetlił szarżę)
- Migracja `ebr_uwagi_history` do `audit_log`
- Zmiana mechanizmu `session['shift_workers']` — audit trail wpina się w istniejący model, nie redesigne'uje go
- Wielojęzyczność panelu audytu — interfejs po polsku, zgodnie z resztą aplikacji
- Eksport do formatów innych niż CSV w panelu + JSONL.gz w archiwum

## Decyzje zarchiwowane (dla kontekstu)

| Decyzja | Wybór | Alternatywy odrzucone |
|---|---|---|
| Cel regulacyjny | Wewnętrzna traceability (B) | GMP/21 CFR Part 11 (A) — za duży overhead; minimum (C) — za mało |
| Zakres zdarzeń | Wszystkie mutujące, bez read-logu | Read-log — zasypałby bazę |
| Granularność | Hybryda event + diff pól (C) | Pole-po-polu (A) — nie ogarnia JSON-blobów i akcji bez pól; pure event-sourced (B) — słabsze diffy |
| Retencja | 2 lata + ręczna archiwizacja | Brak retencji — OK technicznie, ale brudne; auto-archiwizacja — mniej widoczne |
| Identyfikacja aktora | worker_id + snapshot + context (C) + multi-actor | Sam username (A) — traci kontekst; primary + co-actors (C-hybryda) — multi-actor drugą klasą |
| Przechowywanie multi-actor | Tabela łącznikowa (B) | JSON column — wolniejsze filtry po aktorze |
| Gdzie żyje kod logujący | Jawny helper (A) | Dekorator (B) — słabo dla diffów; triggery SQLite (C) — nie widzą sesji |
| `ebr_uwagi_history` | Zostawiamy, dublowanie OK | Migracja do audit_log — ryzyko regresji w świeżym feature |
| Empty shift | Blokuje zapis laboranta | Fallback na login — istnieje dziś, usuwamy |
