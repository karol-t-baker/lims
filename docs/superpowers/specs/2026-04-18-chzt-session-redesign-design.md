# ChZT — Redesign sesji + pola szambiarki + rola produkcja

**Data:** 2026-04-18
**Status:** spec do zatwierdzenia
**Bazuje na:** `docs/superpowers/specs/2026-04-18-chzt-modal-refinement-design.md` (pierwsza iteracja — session-per-date, only-lab)
**Dane referencyjne:** `/Users/tbk/Desktop/ChZT Ścieków.xls`, arkusz `2026` (229 wierszy, 18 sesji 2026)

## Cel

Trzy przeplatane zmiany w ChZT:

1. **Sesja na żądanie** — obecnie jedna sesja per data kalendarzowa (UNIQUE(data)). Nocne zmiany crossing midnight (22:00–06:00) tego nie obsługują. Przechodzimy na sesję tworzoną ręcznie przyciskiem, identyfikowaną przez `dt_start` (datetime).
2. **Pola szambiarki wypełniane przez produkcję** — obok wewnętrznych pomiarów lab (pH + p1–p5), szambiarka dostaje zewnętrzny wynik z certyfikowanego laba (ext_chzt, ext_ph) + wagę beczki (waga_kg). Te wypełnia produkcja/magazyn (otrzymują wyniki po kilku dniach od dostawy).
3. **Nowa rola `produkcja`** — dostęp do historii ChZT + edycja pól zewnętrznych szambiarki. Nie widzi modala nowej sesji (to robota laba).

## Kontekst — analiza arkusza 2026

| Col | Header | Kto | Widoczność |
|---|---|---|---|
| A | Lp. | auto | Inkrementuje 2× per sesja (hala=N, szambiarka=N+1) |
| B | Data | lab | |
| C | ChZT Wynik zewnętrzny | **produkcja** | Tylko szambiarka (13/14 przypadków 2026) |
| D | pH (wynik zewnętrzny) | **produkcja** | Tylko szambiarka |
| E | CHZT [mg O₂/l] | lab | Wszystkie punkty |
| F | pH | lab | Wszystkie punkty |
| G | Waga [kg] | **produkcja** | Tylko szambiarka |
| H | Uwagi / punkt | auto | hala, rura, kontener N, szambiarka |

**Obserwacje:**
- Liczba kontenerów zmienia się dynamicznie (2026: od 8 do 12) — potwierdza potrzebę pickera przy tworzeniu sesji.
- Szambiarka jest kategorycznie inna (tanker truck, ważona, idzie do zewn. laba) — uzasadnia osobną sekcję UI w widoku szczegółowym.
- Częstotliwość 2026: ~18 sesji / 104 dni robocze ≈ 1 raz na tydzień.

## Decyzje (z brainstorming 2026-04-18)

| Pytanie | Decyzja |
|---|---|
| Trigger nowej sesji | Ręczny przycisk laboranta (A) |
| Max otwartych jednocześnie | Jedna (i) — enforcowane w backend |
| Identyfikacja w liście | `Rozpoczęto` (datetime) (A1) |
| Karta w Narzędziach | Jedna, adaptacyjny modal (B1) |
| Wybór liczby kontenerów | W modalu "brak aktywnej" (picker przed "Rozpocznij") |
| Widoczność pól ext/waga | Modal (tryb edycji) — **zostaje bez zmian**, tylko lab-owned. Rozszerzona tylko **historia detail view** — z mini-sekcją "Szambiarka — analiza zewnętrzna" pod tabelą |
| Dostęp produkcji | Tylko karta "Historia ChZT" w Narzędziach + edycja pól ext/waga w detail view |
| Endpoint `/api/chzt/day/<data>` | (y) Najnowsza sfinalizowana `LIMIT 1`. Max 1/dzień gwarantowane policy |
| Częstotliwość sesji | ~1/tydzień — optymalizacje wydajności nieistotne |

Jawnie NIE w zakresie:
- Migracja eksportu do Excela (skrypt zewnętrzny poza zakresem).
- Lp / numeracja sesji w UI (tylko `dt_start` identyfikuje).
- Osobny picker sesji (skoro jedna otwarta — nie ma co wybierać).

## Architektura

### Zmiany modelu DB

**Tabela `chzt_sesje`** — rebuild (SQLite nie drop'uje UNIQUE inline):

```sql
CREATE TABLE chzt_sesje_v2 (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    dt_start     TEXT NOT NULL,               -- ISO datetime, zastępuje `data`
    n_kontenery  INTEGER NOT NULL DEFAULT 8,
    created_at   TEXT NOT NULL,
    created_by   INTEGER REFERENCES workers(id),
    finalized_at TEXT,                         -- == dt_end, NULL = otwarta
    finalized_by INTEGER REFERENCES workers(id)
);
CREATE INDEX idx_chzt_sesje_dt_start ON chzt_sesje_v2(dt_start DESC);
```

Usunięte: kolumna `data`, `UNIQUE(data)`, index `idx_chzt_sesje_data`.

**Migracja** (w `init_chzt_tables()`, idempotentna):
1. Check czy stara struktura ma kolumnę `data` (via `PRAGMA table_info`).
2. Jeśli tak: `BEGIN → CREATE chzt_sesje_v2 → INSERT ... SELECT id, data||'T00:00:00' AS dt_start, n_kontenery, ... FROM chzt_sesje → DROP chzt_sesje → ALTER TABLE chzt_sesje_v2 RENAME TO chzt_sesje → CREATE INDEX → COMMIT`.
3. FK z `chzt_pomiary` pozostaje spójny (id się nie zmienia).

**Inwariant "max jedna otwarta"** — SQLite nie ma partial UNIQUE; enforcowany w `mbr.chzt.models.create_session`:
```python
if db.execute("SELECT 1 FROM chzt_sesje WHERE finalized_at IS NULL").fetchone():
    raise ValueError("already_open")
```
→ endpoint zwraca 409. Nie ma race'u bo w trybie "default" SQLite serializuje transakcje.

**Tabela `chzt_pomiary`** — dodaj 3 nowe kolumny:

```sql
ALTER TABLE chzt_pomiary ADD COLUMN ext_chzt REAL;
ALTER TABLE chzt_pomiary ADD COLUMN ext_ph REAL;
ALTER TABLE chzt_pomiary ADD COLUMN waga_kg REAL;
```

Migracja idempotentna: check via `PRAGMA table_info` przed ALTER.

W praktyce nullable dla wszystkich punktów; użycie realne tylko dla szambiarki (policy, nie enforcement).

### Nowa rola `produkcja`

Dodanie do systemu RBAC:

- `mbr_users.rola` — nowy możliwy string. Admin może wybrać w workers panel (nowa opcja w dropdown).
- Nowa konstanta w `mbr/chzt/routes.py`: `ROLES_VIEW = ("lab", "kj", "cert", "technolog", "admin", "produkcja")` (read + produkcja view).
- `ROLES_EDIT_INTERNAL = ("lab", "kj", "cert", "technolog", "admin")` — edycja pH + p1..p5.
- `ROLES_EDIT_EXTERNAL = ("produkcja", "technolog", "admin")` — edycja ext_chzt + ext_ph + waga_kg.
- `produkcja` w Narzędziach widzi **tylko kartę "Historia ChZT"**. Gate w `narzedzia.html`: `{% if session.user.rola != 'produkcja' %}` dla karty ChZT (nowa sesja); kartę Historia zostaje widoczna dla wszystkich z `ROLES_VIEW`.
- `produkcja` przy próbie otwarcia modala "nowa sesja" — `POST /api/chzt/session/new` zwraca 403 (nie ma roli w `ROLES_EDIT_INTERNAL`).

### Zmiany API

| Metoda | Path | Rola | Opis |
|---|---|---|---|
| **Usunięte:** | | | |
| `GET` | `/api/chzt/session/today` | — | Obsolete |
| `GET` | `/api/chzt/session/<data_iso>` | — | Obsolete |
| **Nowe:** | | | |
| `GET` | `/api/chzt/session/active` | `ROLES_VIEW` | Zwraca `{session: {...}}` lub `{session: null}` |
| `POST` | `/api/chzt/session/new` | `ROLES_EDIT_INTERNAL` | Body: `{n_kontenery: int}`. Tworzy sesję + seeduje `hala/rura/kontener 1..N/szambiarka` pomiary. 409 jeśli jest inna otwarta. 403 dla `produkcja` |
| `GET` | `/api/chzt/session/<int:id>` | `ROLES_VIEW` | Po numerycznym id. 404 jeśli brak |
| **Zmienione semantycznie:** | | | |
| `PUT` | `/api/chzt/pomiar/<id>` | `ROLES_VIEW` | Backend filtruje pola per rola: lab → tylko `ph/p1..p5`; produkcja → tylko `ext_chzt/ext_ph/waga_kg`; admin/technolog → wszystko. Próba zapisu cudzego pola — silent drop (field nie jest w nowym zapisie) albo 403 przy całym requeście jeśli pusty poprawny subset. Audit zapisuje tylko rzeczywiste zmiany. |
| `GET` | `/api/chzt/day/<data>` | `ROLES_VIEW` | `WHERE DATE(dt_start) = data AND finalized_at IS NOT NULL ORDER BY dt_start DESC LIMIT 1`. Response `{data, dt_start, finalized_at, punkty: [{nazwa, ph, srednia, ext_chzt, ext_ph, waga_kg}]}` — dla skryptu excel eksportu. |
| `GET` | `/api/chzt/history` | `ROLES_VIEW` | Pagination po `dt_start DESC`. Zwraca listę sesji (w tym otwartą). Produkcja widzi wszystkie tak samo. |
| **Bez zmian (tylko rola):** | | | |
| `PATCH` | `/api/chzt/session/<id>` | `ROLES_EDIT_INTERNAL` | n_kontenery resize. Produkcja nie może. |
| `POST` | `/api/chzt/session/<id>/finalize` | `ROLES_EDIT_INTERNAL` | Finalize (zamyka sesję). Produkcja nie może. |
| `POST` | `/api/chzt/session/<id>/unfinalize` | `admin` | Bez zmian |
| `GET` | `/chzt/historia` | `ROLES_VIEW` | Strona historii |

**Implementacja RBAC w PUT pomiar:**

```python
_LAB_FIELDS = ("ph", "p1", "p2", "p3", "p4", "p5")
_EXT_FIELDS = ("ext_chzt", "ext_ph", "waga_kg")

def _allowed_fields_for_role(rola):
    if rola in ("admin", "technolog"):
        return _LAB_FIELDS + _EXT_FIELDS
    if rola in ("lab", "kj", "cert"):
        return _LAB_FIELDS
    if rola == "produkcja":
        return _EXT_FIELDS
    return ()

@chzt_bp.route("/api/chzt/pomiar/<int:pomiar_id>", methods=["PUT"])
@role_required(*ROLES_VIEW)
def api_pomiar_update(pomiar_id):
    payload = request.get_json(force=True) or {}
    allowed = _allowed_fields_for_role(session["user"]["rola"])
    new_values = {k: _coerce_float(payload.get(k)) for k in allowed}
    # ... merge z istniejącym row (tylko pola które użytkownik może dotknąć zostają nadpisane)
```

Kluczowe: niedozwolone pola są po prostu **nie brane z payloadu** — wartości w DB zostają nietknięte. Nie trzeba 403 dla częściowych payloadów.

### Zmiany UI

#### Karta w Narzędziach (`mbr/templates/technolog/narzedzia.html`)

```jinja
{% set rola = session.user.rola %}
{% if rola != 'produkcja' %}
  <!-- Karta "ChZT Ścieków" — lab+ -->
{% endif %}
<!-- Karta "Historia ChZT" — wszyscy z ROLES_VIEW -->
```

#### Modal — dwa stany

**Stan A: brak aktywnej sesji** (rola ∈ ROLES_EDIT_INTERNAL):
```
┌─────────────────────────────────────┐
│ ChZT Ścieków                    ×   │
├─────────────────────────────────────┤
│                                     │
│   Rozpocznij nową sesję pomiarową   │
│                                     │
│   Liczba kontenerów: [  8  ]        │
│                                     │
│         [ Rozpocznij sesję ]        │
│                                     │
└─────────────────────────────────────┘
```
- Klik → `POST /api/chzt/session/new {n_kontenery}` → odpowiedź zawiera utworzoną sesję → modal przełącza się w Stan B.

**Stan B: aktywna sesja** (jak obecnie, bez zmian):
- Tabela punktów z edytowalnymi pH + p1–p5
- Toolbar z n_kontenery + Generuj
- Footer z "Zakończ sesję"
- Autosave on blur

**Stan C: produkcja otwiera modal** — nie powinno się zdarzyć (produkcja nie widzi karty). Defensywnie: modal pokazuje "Brak uprawnień" jeśli JS się jakoś zapodział.

#### Widok historii (`/chzt/historia`)

Lista (bez zmian strukturalnych, tylko kolumny):
- `Rozpoczęto` (było `Data`) — format `18.04.2026 22:18`, mono
- Reszta kolumn (Kontenery, Śr. ChZT, Min, Max, Rozstęp, Przekroczeń >40k, Śr. pH, Status, Sfinalizował) bez zmian.

**Detail view po kliknięciu wiersza** — **kluczowa zmiana**:

Górna część (bez zmian — tabela próbki):
```
┌─ POMIARY LAB ─────────────────────────────┐
│ Punkt   pH   P1   P2   P3   P4   P5  Śr. │
│ Hala    9,2  ...                          │
│ Rura    ...                                │
│ Kontener 1..N ...                          │
│ Szambiarka ...                             │
└────────────────────────────────────────────┘
```
- Edytowalne dla ROLES_EDIT_INTERNAL; readonly dla `produkcja`.

Dolna nowa sekcja:
```
┌─ ANALIZA ZEWNĘTRZNA — SZAMBIARKA ─────────┐
│                                            │
│  pH zewnętrzne:     [ 11    ]             │
│  ChZT zewnętrzne:   [ 13250 ] mg O₂/l     │
│  Waga beczki:       [ 19060 ] kg          │
│                                            │
└────────────────────────────────────────────┘
```
- Edytowalne dla ROLES_EDIT_EXTERNAL; readonly dla `lab`/`kj`/`cert`.
- Autosave on blur (ten sam mechanizm PUT /api/chzt/pomiar/<szambiarka_id>).
- Wizualnie: osobny card `.chzt-ext-section` pod główną tabelą, z etykietą sekcji, 3 pola w grid layout.

#### Kolor/affordance

- Pola edytowalne: teal focus ring (jak teraz)
- Pola readonly (cudza rola): szare tło `var(--surface-alt)` + `disabled` attribute + brak hover/focus state
- Status roli u góry detail view (opcjonalnie): `Lab (odczyt) · Produkcja: można edytować ext`

### Pliki — lista zmian

#### Modyfikowane

| Plik | Zmiana |
|---|---|
| `mbr/chzt/models.py` | Migracja w `init_chzt_tables` (rebuild sesje + ALTER pomiary). Zastąpić `get_or_create_session` przez `get_active_session` + `create_session`. Rozszerzyć `get_pomiar`/`update_pomiar`/`get_session_with_pomiary` o nowe pola. |
| `mbr/chzt/routes.py` | Usunąć `api_session_today`, `api_session_by_date`. Dodać `api_session_active`, `api_session_create`, `api_session_by_id`. Zaktualizować `api_pomiar_update` o RBAC per-pole. Dodać `ROLES_VIEW`, `ROLES_EDIT_INTERNAL`, `ROLES_EDIT_EXTERNAL`. |
| `mbr/chzt/static/chzt.js` | Dodać stan "create new session" w modalu + przycisk Rozpocznij → POST /new. Zmienić `loadSession('today')` na `loadActiveSession()`. W detail view: renderować sekcję ext-szambiarka (edit lub readonly per rola). Rozszerzyć autosave handlers o pola ext_chzt/ext_ph/waga_kg. |
| `mbr/chzt/static/chzt.css` | Dodać styl `.chzt-create-pane` (nowa sesja state) i `.chzt-ext-section` (szambiarka sekcja zewn.). `.chzt-inp.readonly` (szare tło, disabled look). |
| `mbr/chzt/templates/chzt_modal.html` | Dodać `<div class="chzt-create-pane">` (hidden initially) + przyciski. |
| `mbr/chzt/templates/chzt_historia.html` | Kolumna `Data` → `Rozpoczęto`, format datetime. Dodać sekcję "Analiza zewnętrzna" w obsłudze detail view (generowana JS'em, ale CSS gotowy). |
| `mbr/templates/technolog/narzedzia.html` | Gate karty ChZT (bez produkcji). Karta historii dla wszystkich ROLES_VIEW. |
| `mbr/workers/routes.py` (admin workers panel) | Dodać `produkcja` do dropdown ról. |
| `tests/test_chzt.py` | Istniejące testy — zmienić `/today` → `/active`, daty → datetime, usunąć `get_or_create_session`. Dodać: test nowych endpointów, test RBAC per-pole, test migracji (nie potrzebne — init idempotentna), test nocnej sesji crossing midnight. |

#### Nowe

Brak — wszystko rozszerzenie istniejących.

### Audit

Istniejące eventy zostają. Dodać jeden nowy:
- `EVENT_CHZT_SESSION_CREATED` (już jest, ale teraz fire'uje z POST /new zamiast GET /today).

Pola `ext_chzt`, `ext_ph`, `waga_kg` są w `diff_fields` zakresie dla pomiarów — `chzt.pomiar.updated` event pokaże kto zmienił (produkcja vs lab) dzięki `actors_from_request`.

## Testy

Nowe scenariusze w `tests/test_chzt.py`:

1. **Migracja** — tabela z kolumną `data` po `init_chzt_tables` ma kolumnę `dt_start` i dane zachowane; UNIQUE na `data` usunięte.
2. **`POST /api/chzt/session/new`** — tworzy sesję, seeduje N+3 pomiary.
3. **Druga `POST /new` z otwartą** — 409.
4. **Finalize → następna `POST /new`** — OK, nie 409.
5. **Nocna sesja crossing midnight** — sesja z `dt_start='2026-04-18T22:00:00'` i `finalized_at='2026-04-19T06:00:00'` jest widoczna w `/api/chzt/history` i dostępna przez `GET /api/chzt/day/2026-04-18`.
6. **RBAC `lab` PUT pomiar** — próba zapisu `ext_chzt` w payloadzie ignorowana (DB nie zmienione).
7. **RBAC `produkcja` PUT pomiar** — może zapisać `ext_chzt`/`ext_ph`/`waga_kg`, próba zapisu `ph` ignorowana.
8. **RBAC `produkcja` POST /new** — 403.
9. **RBAC `produkcja` PATCH session** — 403 (n_kontenery nie dla nich).
10. **`GET /api/chzt/day/<data>` z nocną sesją** — wyszukuje po `DATE(dt_start)`, zwraca ostatnią sfinalizowaną LIMIT 1.

Role fixture:
```python
@pytest.fixture
def produkcja_client(monkeypatch, db):
    return _make_client(monkeypatch, db, rola="produkcja", shift_workers=None)
```

## Plan migracji

**Kroki runtime (przy starcie app z nowym kodem):**

1. `init_chzt_tables(db)` detektuje stary schemat przez `PRAGMA table_info(chzt_sesje)`:
   - Jeśli jest kolumna `data` → rebuild sesje (transakcja: create v2, copy, drop, rename).
   - Jeśli w `chzt_pomiary` brakuje `ext_chzt` → trzy ALTER TABLE ADD COLUMN.
2. `mbr_users` — nie wymaga migracji (pole `rola` jest TEXT, nowa wartość `produkcja` zgodna).

**Kroki manualne:**
- Admin otwiera workers panel i zmienia rolę pracowników magazynu/produkcji na `produkcja`.

**Rollback:**
- Stary kod nie zadziała z nowym schematem (brak `data` w `chzt_sesje`). Backup DB przed deployem (`data/batch_db.sqlite.backup`).

## Ryzyka i otwarte kwestie

- **Race przy POST /new**: dwóch laborantów jednocześnie — ochrona przez check pod transakcją (SQLite serializes writes). Pierwszy INSERT wygrywa, drugi widzi już otwartą → 409. W praktyce sesje są rzadkie (1/tydz).
- **Nocna sesja w `/chzt/day/<data>`**: sesja startująca 2026-04-18 22:00 i kończąca 2026-04-19 06:00 jest szukana po `DATE(dt_start) = 2026-04-18`. Produkcja pyta o dzień startu, nie zakończenia. Jeśli ktoś pyta po `2026-04-19` → 404. Akceptowalne bo policy "max 1/dzień".
- **Produkcja widzi otwarte sesje w historii**: tak, widzi również draft (otwartą). Ale nie może jej edytować ext pól bo sesja nie jest finalized → wręcz może. Decyzja: mogą edytować też w drafcie, to ich wartość — nie blokujemy.
- **Eksport Excel** — skrypt zewnętrzny potrzebuje teraz odczytywać ext_chzt/ext_ph/waga_kg. Endpoint `/api/chzt/day/<data>` zwraca je. Jeśli skrypt już działa, trzeba go zaktualizować. Poza zakresem.
