# Spec — Konsolidacja SSOT parametrów (produkt × etap × parametr)

**Data:** 2026-04-16
**Status:** zatwierdzony, gotowy do pisania planu implementacyjnego
**Zakres:** refaktor warstwy danych dla definicji parametrów pomiarowych per produkt/etap/typ

## Kontekst i problem

Dzisiaj dane o tym "jakie parametry mierzymy dla produktu X, z jakimi limitami, z jaką naważką, w jakim zakresie precyzji" są rozsmarowane po **dwóch równoległych systemach** które nie są aktywnie synchronizowane:

- **Legacy:** `parametry_etapy (produkt, kontekst, parametr_id, min_limit, max_limit, nawazka_g, precision, target, sa_bias, formula, kolejnosc, cert_*)` — 465 wierszy, trzyma też metadane certyfikatu
- **Pipeline:** `etap_parametry (etap_id, parametr_id, ...)` + `produkt_etap_limity (produkt, etap_id, parametr_id, ...)` — globalny katalog etap→param plus per-product overrides, łącznie 511 wierszy

Dodatkowo istnieje `mbr_templates.parametry_lab` — JSON-owy snapshot, rebuildowany niespójnie (tylko z legacy, pipeline go nie używa przy renderowaniu).

Rozgałęzienia w kodzie (`if pipeline: ... else: ...`) występują w:
- `mbr/parametry/routes.py` (POST, PUT, DELETE dla bindingów)
- `mbr/laborant/routes.py` (zbiornik skip-pipeline branch)
- `mbr/parametry/registry.py` (build_parametry_lab vs build_pipeline_context)

**Konsekwencje praktyczne:**
- Edycja w jednym UI nie widać w drugim — zgłoszony bug dla Chelamid_DK
- sa_bias trzymany w `etap_parametry` (globalnie na etap, nie per produkt) — zmiana dla jednego produktu nakłada się na wszystkie używające tego etapu
- 3 produkty (Chegina_K40GL, K40GLO, K40GLOL) nie mają `produkt_pipeline` i są niewidoczne przez pipeline ścieżkę
- Nowy wymiar — różne parametry dla szarży vs zbiornika tego samego produktu — niemożliwy do wyrażenia czysto; wymaga nowej wymiarowości

## Cele

1. **Jeden SSOT dla parametrów pomiarowych per (produkt, etap, parametr)**: jedna tabela, bez dualnych ścieżek, bez snapshotów.
2. **Wsparcie wymiarowości typu szarży** (szarza/zbiornik/platkowanie) w definicji parametrów: ten sam produkt może mieć inny zestaw parametrów w zależności od typu.
3. **Łatwy debug:** jedno zapytanie SQL odpowiada na pytanie "co laborant widzi otwierając produkt X jako Y".
4. **Dwa istniejące UI zachowane:** panel admina (`/parametry`) i modal CRUD laboranta w karcie szarży — oba na wspólnym, prostym zestawie endpointów.
5. **Zero zmian zachowania dla laboranta** w codziennym użyciu (backward-compatible defaults w migracji).

## Non-goals

- Konsolidacja `ebr_wyniki` vs `ebr_pomiar` (dwa SSOT dla pomiarów) — osobny refaktor
- Refaktor `seed_mbr.py` — osobny ticket
- Zmiana uprawnień (kto może CRUD parametrów) — dziś laborant ma pełne CRUD w zakresie karty szarży, zostaje tak
- Zmiana generatora certyfikatów DOCX — tylko źródło danych (`parametry_cert` zamiast `parametry_etapy`)
- UI-owe rewolucje w panelu admina — to samo tabelaryczne podejście, z dodanymi kolumnami flag

## Schemat docelowy

### Tabele zostające jako SSOT

| Tabela | Rola |
|---|---|
| `parametry_analityczne` | Globalny katalog kodów parametrów (kod, label, typ, metoda_id, precision, jednostka) |
| `etapy_analityczne` | Globalny katalog etapów (kod, nazwa, typ_cyklu) |
| `produkt_pipeline` | `(produkt, etap_id, kolejnosc)` — jakie etapy ma dany produkt |
| `parametry_cert` | `(produkt, variant_id, parametr_id, name_pl, name_en, method, requirement, format, qualitative_result, kolejnosc)` — metadane certyfikatu |

### Tabela docelowa `produkt_etap_limity`

```sql
CREATE TABLE produkt_etap_limity (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    produkt         TEXT    NOT NULL,
    etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
    parametr_id     INTEGER NOT NULL REFERENCES parametry_analityczne(id),
    kolejnosc       INTEGER NOT NULL DEFAULT 0,

    -- limity wspólne dla wszystkich typów szarży
    min_limit       REAL,
    max_limit       REAL,
    precision       INTEGER,
    nawazka_g       REAL,
    spec_value      REAL,
    formula         TEXT,        -- override nad parametry_analityczne.formula
    sa_bias         REAL,        -- per produkt
    krok            INTEGER,
    wymagany        INTEGER NOT NULL DEFAULT 0 CHECK(wymagany IN (0,1)),
    grupa           TEXT    NOT NULL DEFAULT 'lab',

    -- filtry widoczności per typ szarży (ebr_batches.typ)
    dla_szarzy      INTEGER NOT NULL DEFAULT 1 CHECK(dla_szarzy IN (0,1)),
    dla_zbiornika   INTEGER NOT NULL DEFAULT 1 CHECK(dla_zbiornika IN (0,1)),
    dla_platkowania INTEGER NOT NULL DEFAULT 0 CHECK(dla_platkowania IN (0,1)),

    UNIQUE(produkt, etap_id, parametr_id)
);
```

### Tabele do skasowania

- `parametry_etapy` — limity → `produkt_etap_limity`; cert fields → `parametry_cert`
- `etap_parametry` — fields per-produkt → `produkt_etap_limity`
- `mbr_templates.parametry_lab` (kolumna, nie tabela) — nikt nie czyta po refaktorze

## Ścieżki odczytu

Jedna funkcja SSOT: `build_pipeline_context(db, produkt, typ=None)` w `mbr/pipeline/adapter.py`.

| Widok | Wywołanie | Filtr SQL na `produkt_etap_limity` |
|---|---|---|
| Karta edycji szarży (`fast_entry_partial` dla `typ='szarza'`) | `build_pipeline_context(db, produkt, typ='szarza')` | `WHERE dla_szarzy=1` |
| Karta edycji zbiornika | `build_pipeline_context(db, produkt, typ='zbiornik')` | `WHERE dla_zbiornika=1` |
| Karta edycji płatkowania | `build_pipeline_context(db, produkt, typ='platkowanie')` | `WHERE dla_platkowania=1` |
| Widok "ukończone" (unia wszystkich pomiarów) | `build_pipeline_context(db, produkt, typ=None)` | brak filtra na flagi |
| Generator cert DOCX | `get_cert_params(db, produkt, variant_id)` | z `parametry_cert`, nie dotyka `produkt_etap_limity` |

**Wstrzykiwanie do templata:**
W `fast_entry_partial` ładujemy dwa konteksty:
- `pipeline_ctx_typ` — z filtrem na bieżący `ebr.typ`, do karty edycji
- `pipeline_ctx_all` — z `typ=None`, do widoku "ukończone"

Obie struktury przekazywane do templata jako osobne JSON-y. Brak dodatkowego roundtripa.

**Modyfikacje w kodzie:**
- `mbr/laborant/routes.py:207` — usuwamy warunek `if ebr.get("typ") != "zbiornik"`, zawsze wołamy `build_pipeline_context` z parametrem `typ`
- `mbr/laborant/routes.py:265` — to samo w `save_entry`
- `mbr/templates/laborant/_fast_entry_content.html` — widok "ukończone" czyta z `pipeline_ctx_all`, nie z `ebr.parametry_lab`

## Ścieżki zapisu i endpointy

Wszystkie mutacje piszą do **jednej tabeli** `produkt_etap_limity`. Zero rozgałęzień pipeline/legacy.

### Nowe endpointy

| Endpoint | Rola | Payload | Efekt |
|---|---|---|---|
| `GET /api/bindings?produkt=X&etap_id=Y` | `login_required` | — | lista wszystkich wierszy dla (produkt, etap) z limitami i flagami |
| `POST /api/bindings` | `login_required` | `{produkt, etap_id, parametr_id, dla_szarzy, dla_zbiornika, dla_platkowania, min_limit, max_limit, precision, nawazka_g, spec_value, kolejnosc, grupa, formula, sa_bias, krok, wymagany}` | INSERT |
| `PUT /api/bindings/<id>` | `login_required` | partial update dowolnego pola z wyżej | UPDATE; jeśli wszystkie flagi = 0 po update → auto-DELETE |
| `DELETE /api/bindings/<id>` | `login_required` | — | hard DELETE |
| `GET /api/parametry/catalog` | `login_required` | — | lista wszystkich `parametry_analityczne.aktywny=1` do pickera |

### Autocleanup pustych bindingów

W `PUT /api/bindings/<id>`: jeśli po update wszystkie trzy flagi (`dla_szarzy`, `dla_zbiornika`, `dla_platkowania`) = 0 → backend automatycznie robi DELETE. Binding niewidoczny dla żadnego typu = nieużywany.

### Endpointy znikające (PR 7)

- `POST /api/parametry/etapy`
- `PUT /api/parametry/etapy/<id>`
- `DELETE /api/parametry/etapy/<id>`
- `GET /api/parametry/etapy/<produkt>/<kontekst>`
- `POST /api/parametry/etapy/reorder`
- `POST /api/parametry/rebuild-mbr`
- `PUT /api/parametry/sa-bias` — jeśli używany, migruje do `PUT /api/bindings/<id>` (sa_bias już tam obsługiwany)

### UI 1 — Panel admina (`/parametry`)

Widok tabelaryczny, jedna płaska lista z filtrami:

```
[Produkt▾] [Etap▾] [Typ▾] [Grupa▾] [+ Dodaj]
─────────────────────────────────────────────────────────────
☐ Produkt │ Etap │ Kod │ Nazwa │ Typ │ Min │ Max │ Prec │ Nawazka │ Sz │ Zb │ Pl │ ⋯
```

- Kolumny `Sz/Zb/Pl` — checkboxy flag typów
- Limity edytowalne inline (debounced PUT)
- Drag-drop dla `kolejnosc` w obrębie (produkt, etap)
- `+ Dodaj binding` otwiera modal z pickerem parametru z `/api/parametry/catalog`

Role: `role_required("admin", "technolog")` na widoku `/parametry`, endpointy używają `login_required`.

### UI 2 — Modal CRUD w karcie szarży (`openParamEditor`)

Zachowuje obecną funkcjonalność. Zmiany:
- Scope: bieżący `(produkt, etap_id, typ)` — wiemy z `ebr` batcha
- Checkbox "parametr pokazywany w mojej karcie" = flaga `dla_<mytyp>`
  - Zaznaczenie + brak wiersza → `POST /api/bindings` z odpowiednią flagą = 1
  - Zaznaczenie + wiersz istnieje → `PUT /api/bindings/<id>` `{dla_<mytyp>: 1}`
  - Odznaczenie → `PUT` `{dla_<mytyp>: 0}`. Backend auto-DELETE jeśli wszystkie flagi = 0
- Edycja limitów/precyzji/naważki → `PUT /api/bindings/<id>`
- Drag-drop → `PUT` z `kolejnosc`
- **Fix przy okazji:** po add/delete wołamy `loadBatch(ebrId)` — dziś nie jest wołane, stąd wrażenie że zmiana "się nie zapisała"

## Migracja danych

Skrypt: `scripts/migrate_parametry_ssot.py`. Idempotentny, atomowy, z flagą `--dry-run`.

### Kroki

1. **Backup** — kopia `data/batch_db.sqlite` → `data/batch_db.sqlite.bak-pre-parametry-ssot`. Bez tego STOP.
2. **Walidacja pre-flight:**
   - Zrzut liczników `parametry_etapy`, `etap_parametry`, `produkt_etap_limity`
   - Lista produktów bez `produkt_pipeline` (oczekiwane: Chegina_K40GL, K40GLO, K40GLOL)
   - Wiersze `parametry_etapy.produkt IS NULL` (shared) — jeśli są, STOP z raportem; wymagają decyzji ręcznej
3. **ALTER TABLE `produkt_etap_limity`** — dodanie kolumn: `kolejnosc`, `formula`, `sa_bias`, `krok`, `wymagany`, `grupa`, `dla_szarzy`, `dla_zbiornika`, `dla_platkowania`. Dla CHECK constraint w SQLite — wzorzec "create new + insert select + drop + rename" jeśli ALTER ADD nie obsłuży inline.
4. **Tworzenie `produkt_pipeline`** dla 3 legacy-only produktów: mapowanie `parametry_etapy.kontekst` → `etapy_analityczne.kod`.
5. **Migracja limitów** `parametry_etapy` → `produkt_etap_limity`:
   - Dla każdego wiersza `parametry_etapy`: `etap_id = lookup(produkt, kontekst)`; UPSERT do `produkt_etap_limity` z kopią: `min_limit, max_limit, nawazka_g, precision, spec_value=target, kolejnosc, formula, sa_bias, krok, wymagany, grupa`; flagi defaultowe: `dla_szarzy=1, dla_zbiornika=1, dla_platkowania=0`.
6. **Migracja sa_bias** z `etap_parametry` → `produkt_etap_limity`:
   - Dla każdego `etap_parametry.sa_bias IS NOT NULL` → kopia do wszystkich `produkt_etap_limity` z pasującym `(etap_id, parametr_id)`. Per-produkt `sa_bias` z `parametry_etapy` wygrywa, jeśli był już ustawiony.
7. **Migracja metadanych cert** z `parametry_etapy` (pola `on_cert=1` + `cert_*`) → `parametry_cert`:
   - UPSERT `parametry_cert (produkt, parametr_id, variant_id=cert_variant_id)` z: `requirement=cert_requirement, format=cert_format, qualitative_result=cert_qualitative_result, kolejnosc=cert_kolejnosc`.
8. **Walidacja post-flight:**
   - Każdy `mbr_templates.status='active'` produkt ma ≥ 1 wiersz w `produkt_etap_limity` z jakąś flagą = 1
   - Golden snapshot dla Chelamid_DK + Chegina_K40GL + Chegina_K7 — lista (kod, limity, naważka) pre/post identyczna
   - Licznik `parametry_cert` post >= licznik `parametry_etapy.on_cert=1` pre
   - Brak osieroconych `produkt_etap_limity` (etap_id jest w `produkt_pipeline` produktu)
9. **DROP `parametry_etapy`, DROP `etap_parametry`** — dopiero po zielonej walidacji i po refaktorze kodu (PR 6, nie PR 1).

### Ryzyka

- Skrypt wywala się → rollback transakcji, zero zmian
- Walidacja post-flight fail → rollback + raport
- Awaria w międzyczasie → restore z `.bak-pre-parametry-ssot`

## Kolejność pracy (PR-y)

| PR | Zawartość | Bezpieczeństwo |
|---|---|---|
| **PR 1 — Etap A** | Skrypt migracji, ALTER TABLE, kopia danych do rozszerzonego `produkt_etap_limity`. Stary kod nadal działa (czyta z `parametry_etapy`). Snapshot fixtures. | Kod niezmieniony. Dane zsynchronizowane w obu miejscach. Zero ryzyka runtime. |
| **PR 2 — Etap B.1** | `build_pipeline_context` przyjmuje `typ`. Filtr po flagach. `fast_entry_partial` + `save_entry` przekazują `typ`. Renderer "ukończone" ładuje drugi kontekst z `typ=None`. Usunięcie warunku `typ != zbiornik`. | Golden-snapshot testy zielone. |
| **PR 3 — Etap B.2** | Nowe endpointy `/api/bindings/*`. Panel admina `/parametry` przepisany na nowe endpointy + kolumny flag. | Laborant modal jeszcze na starych, ale dual-path działa. |
| **PR 4 — Etap B.3** | Laborant modal `openParamEditor` na nowe endpointy. Fix "po add/delete karta się odświeża" (`loadBatch` po `peToggle`). | Oba UI na nowym modelu. |
| **PR 5 — Etap B.4** | Cert generator + `get_cert_params` → `parametry_cert` zamiast `parametry_etapy`. Porównanie DOCX byte-by-byte. | Świadectwa generują się identycznie. |
| **PR 6 — Etap C** | DROP `parametry_etapy`, DROP `etap_parametry`, DROP kolumny `mbr_templates.parametry_lab`. Aktualizacja `schema_v4.sql`. | Tylko DDL. Kod już nie czyta. |
| **PR 7 — Etap D** | Sprzątanie martwego kodu (lista niżej). | Grep-based, mechaniczne. |

## Martwy kod do usunięcia w PR 7

### `mbr/parametry/registry.py`
- `get_parametry_for_kontekst()` — zastąpione filtrem w `build_pipeline_context`
- `build_parametry_lab()` — nikt nie czyta snapshota
- `FULL_PIPELINE_PRODUCTS` — wszystkie produkty są teraz pipeline, konstanta zbędna

### `mbr/parametry/routes.py`
- Wszystkie endpointy `/api/parametry/etapy/*`
- `/api/parametry/rebuild-mbr`
- `/api/parametry/sa-bias` (jeśli niemigrowany; inaczej alias do `/api/bindings/<id>` PUT)
- Helper `_list_pipeline_bindings`

### `mbr/laborant/routes.py`
- Warunek `if ebr.get("typ") != "zbiornik"` przy `build_pipeline_context`

### `mbr/app.py`
- Startup fixup dla `metoda_id` — weryfikacja na produkcji czy potrzebny; jeśli migracja rozwiązała, usuwamy

## Testy

### Pre-migracja (snapshots)

`tests/test_parametry_ssot_migration.py`:
- Dla każdego aktywnego produktu — zrzut listy `(kod, label, min, max, precision, nawazka_g, kolejnosc)` z dzisiejszej ścieżki → JSON fixture
- Po refaktorze (PR 2+) — ta sama funkcja zwraca identyczny JSON
- Testowane jawnie: Chelamid_DK, Chegina_K40GL, Chegina_K40GLO, Chegina_K40GLOL, Chegina_K7

### Nowe testy (po refaktorze)

- `test_bindings_api.py` — CRUD round-trip dla `/api/bindings` z różnymi kombinacjami flag
- `test_render_typ.py` — `build_pipeline_context` z `typ='szarza'` / `'zbiornik'` / `None` zwraca różne zestawy param
- `test_autocleanup.py` — PUT z `dla_szarzy=0` na wierszu z tylko tą flagą → auto-DELETE
- `test_completed_view.py` — widok "ukończone" widzi unię param z obu typów

### Kryterium "gotowe"

1. Staging: laborant otwiera Chelamid_DK szarżę, widzi te same 7 parametrów co dziś, z tymi samymi limitami, zapis działa
2. Staging: admin w `/parametry` dodaje parametr z `dla_zbiornika=1 only` — laborant widzi go w zbiorniku, nie widzi w szarży
3. CI: wszystkie testy zielone (istniejące + nowe)
4. `grep -r parametry_etapy mbr/` — 0 trafień
5. `sqlite3 data/batch_db.sqlite ".tables"` — brak `parametry_etapy`, `etap_parametry`
6. Generator certyfikatów DOCX — porównanie pre/post dla ≥ 3 produktów identyczne

## Co poza zakresem

- Konsolidacja `ebr_wyniki_old` vs `ebr_pomiar` (dwa SSOT dla pomiarów) — osobny refaktor, podobna patologia
- `seed_mbr.py` — używany w dev, osobny ticket żeby go przepisać pod nowy model
- Kontekst `dodatki` (full-pipeline products jak Chegina_K7) — mapuje się naturalnie na osobny etap w pipeline, zachowany
- Per-typ limity (np. zbiornik miałby węższe pH) — nie wymagane; gdy zajdzie potrzeba, dodajemy kolumny `max_limit_zbiornika REAL NULL` z fallbackiem na `max_limit`
- Rewolucja UI admin panelu — zostaje tabelaryczny, tylko podmiana źródła i dodanie kolumn flag

## Decyzje architektoniczne

### Dlaczego flagi boolean zamiast listy stringów czy osobnej tabeli join

- **Łatwy debug** — `SELECT *` pokazuje wszystkie flagi w jednym wierszu
- SQL trywialny: `WHERE dla_zbiornika=1`, bez `LIKE '%zbiornik%'` ani `json_each`
- Indeksy działają
- CHECK constraint gwarantuje 0/1
- Koszt: 3 kolumny INTEGER — pomijalny

### Dlaczego jedna tabela (`produkt_etap_limity`) zamiast zachowania `parametry_etapy` tylko dla cert fields

- Dwa półużywane tabele = dwa miejsca do mylenia
- `parametry_cert` już istnieje i pełni rolę cert SSOT — pełna konsolidacja tam jest naturalna
- Cel "łatwy debug" wymaga jednego miejsca na pomiary, jednego na cert, zero overlap

### Dlaczego zostawiamy `mbr_templates.parametry_lab` kolumnę na okres przejściowy

- Pozwala rollback kodu bez utraty danych (Etap A)
- Drop w PR 6 po weryfikacji że nikt nie czyta
