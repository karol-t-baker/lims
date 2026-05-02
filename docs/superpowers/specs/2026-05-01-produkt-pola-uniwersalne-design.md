# Uniwersalne pola produktu — Design Spec (pod-projekt A)

**Date:** 2026-05-01
**Status:** Draft (post-brainstorm)
**Scope:** Pod-projekt A z dekompozycji 3-projektowej:
- **A** *(ten spec)*: deklaratywne pola dodatkowe per produkt / per wariant świadectwa.
- **B**: korelacja raw → cert dla parametrów (Chelamid DK/DEA) — osobny spec.
- **C**: elastyczny generator świadectw + nietypowa data ważności (>12 miesięcy) — odłożone, czeka na przejście z DOCX-per-wariant na bardziej deklaratywny model.

## Problem

System dziś hardkoduje pola "metadanych" per produkt:
- `ebr_batches.nr_zbiornika` (TEXT) jako dedykowana kolumna,
- pola laborantowe pojawiające się w modalu/Hero są stałe per cały system, niezależnie od produktu.

Każde nowe pole wymaga: migracji DDL → modyfikacji modalu → modyfikacji Hero → modyfikacji widoku Ukończone → modyfikacji generatora świadectw. Kosztowne i podatne na regresję.

Konkretne zaległe wymagania:

1. **Monamid KO**: pola "Nr zamówienia" i "Nr dopuszczenia oleju kokosowego" — nieobligatoryjne, wpisywane w modalu lub uzupełniane post-creation w Hero, widoczne jako kolumny w widoku Ukończone, **nie** na świadectwie.
2. **Chegina KK**: pole "Ilość konserwantuna" — uzupełniane w Hero zbiornika (tylko dla typu rejestracji `zbiornik`), widoczne w Ukończonych. Nie pojawia się dla zwykłych szarż tego samego produktu.
3. **Chegina K40GLOLMB → Kosmepol**: stały numer zamówienia per wariant świadectwa. Wartość ustawiana raz przez admina, podstawiana automatycznie na każde wygenerowane świadectwo z tego wariantu.

## Goal

Wprowadzić **deklaratywny mechanizm pól dodatkowych** per produkt lub per wariant świadectwa, w którym:
- definicja pola jest danymi (rekord w `produkt_pola`), nie kodem,
- nowe pole nie wymaga zmiany kodu modala/Hero/widoku/generatora,
- wartości per szarża są normalized (osobna tabela, zgodne z polityką ML/DL — memory: `project_ml_goal`),
- zachowana audytowalność (kto/kiedy ustawił/zmienił).

## Non-goals

- **Migracja istniejących pól** (`ebr_batches.nr_zbiornika`, podobne) do nowego mechanizmu. Pozostają jak są. Osobny refactor jeśli zajdzie potrzeba.
- **Pola scope=produkt z miejscem `cert`.** Schemat to umożliwia (`miejsca` może zawierać `cert`), ale w tym wydaniu nie używamy. Wszystkie aktualne use-case'y scope=produkt to Hero/Ukończone, scope=cert_variant to świadectwa.
- **Pola obliczane / formuły.** Wartość pola jest wpisana ręcznie albo stała.
- **Conditional fields** (pole pokazuje się gdy inne ma wartość X). Premature complexity.
- **Multi-value pola** (lista wartości). Premature.
- **Internacjonalizacja** `label_en`. Tylko polski tutaj.
- **Korelacje raw → cert** (Chelamid DK/DEA). To pod-projekt B.
- **Nietypowa data ważności** (>12 miesięcy, override per szarża). Pod-projekt C.
- **Zmiana modelu DOCX-per-wariant** na coś bardziej dynamicznego. Pod-projekt C.

## Architektura

**One-liner:** dwie nowe tabele (`produkt_pola` definicje, `ebr_pola_wartosci` wartości) + integracja w 4 punktach (modal tworzenia / Hero / widok Ukończone / generator certów) + UI definicji w Technolog (per produkt) i Admin (per wariant świadectwa).

### Schema

#### `produkt_pola` (definicje)

| kolumna | typ | uwagi |
|---|---|---|
| `id` | INTEGER PK | |
| `scope` | TEXT NOT NULL | `'produkt'` lub `'cert_variant'` (CHECK constraint) |
| `scope_id` | INTEGER NOT NULL | logiczny FK → `produkty.id` lub `cert_variants.id` (zależnie od `scope`); SQLite nie egzekwuje, walidacja w warstwie aplikacji |
| `kod` | TEXT NOT NULL | snake_case, np. `nr_zamowienia` |
| `label_pl` | TEXT NOT NULL | etykieta wyświetlana użytkownikowi |
| `typ_danych` | TEXT NOT NULL DEFAULT `'text'` | `'text'`, `'number'`, `'date'` (whitelist w aplikacji). Dla scope=cert_variant **zawsze `'text'`** (wymuszane backendem); UI admina nie eksponuje wyboru typu. |
| `jednostka` | TEXT | NULL lub np. `'kg'`, `'%'` (relewantne dla `typ_danych='number'`) |
| `wartosc_stala` | TEXT | tylko dla scope=cert_variant — stała wartość propagowana na świadectwo. Dla scope=produkt zawsze NULL (pole startuje puste). |
| `obowiazkowe` | INTEGER NOT NULL DEFAULT 0 | 0/1; **tylko UI hint** (gwiazdka + czerwona ramka jeśli puste). Niczego nie blokuje — ani modalu, ani zatwierdzania szarży, ani generacji świadectwa. Ignorowane dla scope=cert_variant. |
| `miejsca` | TEXT NOT NULL DEFAULT `'[]'` | JSON array, subset `['modal','hero','ukonczone','cert']`. Ignorowane dla scope=cert_variant. |
| `typy_rejestracji` | TEXT | NULL = wszystkie typy; lub JSON array, subset `['szarza','zbiornik','platkowanie']`. Ignorowane dla scope=cert_variant. |
| `kolejnosc` | INTEGER NOT NULL DEFAULT 0 | sortowanie w UI |
| `aktywne` | INTEGER NOT NULL DEFAULT 1 | soft-disable; wartości historyczne pozostają w bazie |
| `created_at` | DATETIME DEFAULT CURRENT_TIMESTAMP | |
| `created_by` | INTEGER | FK → `workers.id` (logiczne) |
| `updated_at` | DATETIME | |
| `updated_by` | INTEGER | |

Indeksy:
- `UNIQUE(scope, scope_id, kod)` — kod unikalny w obrębie scope+scope_id
- `INDEX(scope, scope_id, aktywne)` — typowe query

#### `ebr_pola_wartosci` (wartości per szarża)

| kolumna | typ | uwagi |
|---|---|---|
| `id` | INTEGER PK | |
| `ebr_id` | INTEGER NOT NULL | FK → `ebr_batches.id` ON DELETE CASCADE |
| `pole_id` | INTEGER NOT NULL | FK → `produkt_pola.id` ON DELETE CASCADE |
| `wartosc` | TEXT | NULL = pole nie uzupełnione; parsowane wg `typ_danych` w warstwie aplikacji |
| `created_at` | DATETIME DEFAULT CURRENT_TIMESTAMP | kto pierwszy uzupełnił |
| `created_by` | INTEGER | |
| `updated_at` | DATETIME | |
| `updated_by` | INTEGER | |

Indeksy:
- `UNIQUE(ebr_id, pole_id)` — jedna wartość per (szarża, pole)
- `INDEX(ebr_id)` — listing wartości szarży

### Komponenty

#### 1. DAO — `mbr/shared/produkt_pola.py` (nowy)

Funkcje:
- `list_pola_for_produkt(db, produkt_id, *, miejsce=None, typ_rejestracji=None, only_active=True) -> list[dict]`
  Pobiera definicje `scope='produkt'`, opcjonalnie filtrowane: `miejsce in miejsca`, `typ_rejestracji in typy_rejestracji or typy_rejestracji is NULL`.
- `list_pola_for_cert_variant(db, variant_id, *, only_active=True) -> list[dict]` — analogicznie.
- `get_wartosci_for_ebr(db, ebr_id) -> dict[str, str]` — zwraca słownik `kod → wartosc` (LEFT JOIN po `pole_id`, tylko aktywne pola scope=produkt produktu szarży).
- `set_wartosc(db, ebr_id, pole_id, wartosc, user_id) -> None` — UPSERT z auditem (`audit` event `ebr_pola.value_set` z before/after).
- `create_pole(db, payload, user_id)`, `update_pole(db, pole_id, payload, user_id)`, `deactivate_pole(db, pole_id, user_id)` — CRUD definicji z auditem.
- (brak `validate_required_fields` — `obowiazkowe` jest UI hintem, nie gate'em; patrz schema).

DAO walidują `typ_danych` przy `set_wartosc()`:
- `number` — akceptujemy zarówno kropkę jak przecinek (polski separator dziesiętny). Walidacja: replace `,` → `.`, próba `float(...)`. Jeśli OK, **zapisujemy z powrotem z przecinkiem** (polska konwencja wyświetlania); jeśli `float` rzuca → `ValueError`. Pusty string / NULL → zapisujemy NULL.
- `date` — akceptujemy ISO `YYYY-MM-DD` lub formaty rozpoznawalne (np. `01-04-2026`, `1.4.2026`); normalizujemy do ISO `YYYY-MM-DD` w bazie. Niezgodny → `ValueError`.
- `text` — bez ograniczenia, zapisujemy raw.

**Konsekwencja dla eksportu ML** (`ml_export_long_format`): przy ekstrakcji wartości typu `number` z `ebr_pola_wartosci` należy zamienić przecinek na kropkę przed cast'em do float. To jest do dopisania w pipeline eksportu (lub w helperze `coerce_number()` współdzielonym między `set_wartosc()` a eksportem).

#### 2. Schema migration

**File:** `mbr/models.py::init_mbr_tables`. Dodajemy idempotentne `CREATE TABLE IF NOT EXISTS` dla obu tabel + indeksy. Brak danych do migracji.

#### 3. Backend — API

**Nowy moduł:** `mbr/produkt_pola/` z `__init__.py` (bp), `routes.py`. Bp rejestrowany w `mbr/app.py::create_app`.

Endpointy definicji (rola `technolog` lub `admin`):
- `GET /api/produkt-pola?scope=<>&scope_id=<>` — lista pól dla scope.
- `POST /api/produkt-pola` — utworzenie. Body: `{scope, scope_id, kod, label_pl, typ_danych, jednostka?, wartosc_stala?, obowiazkowe?, miejsca, typy_rejestracji?, kolejnosc?}`. `wartosc_stala` ignorowane dla scope=produkt; wymagane (NOT NULL) dla scope=cert_variant.
- `PUT /api/produkt-pola/<id>` — edycja (uwaga: `kod` nie jest edytowalny po utworzeniu — patrz Edge cases).
- `DELETE /api/produkt-pola/<id>` — soft-delete (`aktywne=0`).
- `GET /api/produkt-pola/<id>/audit` — historia zmian definicji (z `audit`).

Endpointy wartości (rola `lab`, `kj`, lub `admin`):
- `GET /api/ebr/<ebr_id>/pola` — wszystkie wartości aktywnych pól dla szarży.
- `PUT /api/ebr/<ebr_id>/pola/<pole_id>` — ustawienie/zmiana wartości. Body: `{wartosc: string|null}`.

Walidacja w API:
- `scope ∈ {produkt, cert_variant}`.
- `scope_id` istnieje w odpowiedniej tabeli (`produkty` / `cert_variants`).
- `kod` zgodny z regexem `^[a-z][a-z0-9_]*$`.
- `kod` unikalny w obrębie (scope, scope_id) (DB constraint + 409 z czytelnym message).
- `kod` zgodny z regexem `^[a-z][a-z0-9_]*$` — wystarczy. Dzięki sub-namespace `pola.<kod>` (patrz §8 Generator) **nie ma potrzeby** utrzymywać blacklist reserved keys ani Jinja keywords; każde poprawne snake_case jest bezpieczne.
- `typ_danych ∈ {text, number, date}`.
- `miejsca` — JSON array, każdy element ∈ `{modal, hero, ukonczone, cert}`.
- `typy_rejestracji` — JSON array lub null; każdy element ∈ `{szarza, zbiornik, platkowanie}`.

#### 4. UI — edycja definicji pól

**a) Pola scope=produkt** — nowa zakładka "Pola dodatkowe" w edytorze produktu.

- **Lokalizacja:** dziś `/admin/produkty` redirectuje do `parametry.parametry_editor` → template `mbr/templates/parametry_editor.html`. Dodajemy tam nową zakładkę / sekcję "Pola dodatkowe" w widoku produktu (analogicznie do istniejących zakładek w tym edytorze). Rola: `admin` lub `technolog` zgodnie z istniejącym schematem `parametry_editor`.
- Tabela istniejących pól + przyciski "Dodaj" / "Edytuj" / "Wyłącz".
- Modal formularza: pełen schemat. Widget `miejsca` i `typy_rejestracji` to multi-select checkboxowy.

**b) Pola scope=cert_variant** — nowa zakładka "Stałe pola" w edytorze wariantu świadectwa.

- **File:** `mbr/templates/admin/wzory_cert.html` (istniejący edytor wariantów). Dodajemy panel "Stałe pola" obok istniejących paneli per wariant.
- Modal CRUD ze zredukowanym formularzem: `kod`, `label_pl`, `wartosc_stala` (faktyczna wartość stała, zawsze tekst), `kolejnosc`, `aktywne`. Pola `typ_danych`, `jednostka`, `obowiazkowe`, `miejsca`, `typy_rejestracji` ukryte — backend wymusza `typ_danych='text'`, resztę domyślnymi.

#### 5. Integracja — modal tworzenia EBR

**Files:** `mbr/templates/laborant/_modal_nowa_szarza.html` + endpoint creating EBR (`mbr/laborant/routes.py` lub `mbr/laborant/models.py::create_ebr`).

Frontend:
- Po wybraniu produktu i typu rejestracji JS pobiera definicje: `GET /api/produkt-pola?scope=produkt&scope_id=<produkt_id>` przy **każdym otwarciu modalu** (bez cache — request lekki, modal otwierany rzadko).
- Filtruje po stronie JS: `aktywne=1 AND 'modal' in miejsca AND (typy_rejestracji is null or typ in typy_rejestracji)`.
- Renderuje pola w sekcji "Pola dodatkowe" pod istniejącymi polami modalu, sortowane po `kolejnosc`.
- Każde pole renderowane wg `typ_danych` (`<input type="text|number|date">`). **Bez pre-fill** — pole zawsze startuje puste, laborant albo wpisuje wartość, albo zostawia puste.
- `obowiazkowe=1` → wizualna gwiazdka + czerwona ramka jeśli puste. Niczego nie blokuje (ani submisji modalu, ani późniejszego flow). To tylko UI hint dla laboranta.

Backend:
- Endpoint create EBR przyjmuje opcjonalne `pola: {<pole_id>: <wartosc>}` w body.
- Po utworzeniu szarży, dla każdej pary nie-pustej wstawia rekord przez `set_wartosc()`.

#### 6. Integracja — Hero (widok szarży/zbiornika)

**Files:** Hero żyje w `mbr/templates/laborant/szarze_list.html` (sekcja `_heroObserver` ~linie 638+) wraz z `mbr/templates/laborant/_fast_entry_content.html` (sekcja `cv-hero` ~linie 414+). Dodajemy renderowanie sekcji "Pola dodatkowe" do widoku Hero. Endpoint PUT wartości — patrz §3.

- Sekcja "Pola dodatkowe" z polami filtrowanymi: `aktywne=1 AND 'hero' in miejsca AND (typy_rejestracji is null or typ in typy_rejestracji)` dla produktu szarży, sortowane po `kolejnosc`.
- Każde pole edytowalne inline (klik → input → blur/save). Save → `PUT /api/ebr/<ebr_id>/pola/<pole_id>`.
- Render: aktualna wartość z `ebr_pola_wartosci` lub puste (NULL → "—" w trybie odczytu, pusty input w trybie edycji). Brak pre-fill / podpowiedzi.
- Read-only zgodnie z istniejącą logiką Hero (rola, status szarży).

#### 7. Integracja — widok Ukończone

**Files:** `mbr/registry/models.py::list_completed_registry()` + `get_registry_columns()` + template tabeli rejestru.

Zmiana w `list_completed_registry()`:
- Dla każdej szarży dołącza `d["pola"] = {kod: wartosc, ...}` (filtrowane po `aktywne=1 AND 'ukonczone' in miejsca` definicji + LEFT JOIN po `ebr_pola_wartosci`).

Zmiana w `get_registry_columns()`:
- Dla zbioru produktów występujących w wynikach, agregujemy unikalne pola spełniające `aktywne=1 AND 'ukonczone' in miejsca`.
- Każda kolumna: `key = "pola." + kod` (prefix odróżnia od istniejących wyników/skrótów parametrów). Nagłówek = `label_pl` + (jeśli `jednostka` niepusta) ` [` + `jednostka` + `]` (spójne z istniejącymi kolumnami parametrów typu "Skrót [%]").

Zmiana w template tabeli rejestru:
- Render path `pola.<kod>` analogicznie do istniejących dynamicznych kolumn (np. `__surowce__`).

Edge case: pole skonfigurowane dla produktu A, w wynikach też produkt B bez tego pola → komórka B pusta. Akceptowalne (kolumny to union of all products).

#### 8. Integracja — generator świadectw

**File:** `mbr/certs/generator.py::build_context`.

Po zbudowaniu standardowego kontekstu:
- Czytamy `produkt_pola` dla `scope='cert_variant' AND scope_id=<aktywny variant_id> AND aktywne=1`.
- Dodajemy do kontekstu sub-namespace: `context["pola"] = {kod: wartosc_stala for ...}`.
- **Klucze są dodawane TYLKO dla aktywnego wariantu**. Dla pozostałych wariantów `context["pola"]` zawiera inny zestaw kluczy (lub jest pusty, jeśli wariant nie ma żadnego pola).

**Namespace `pola.<kod>` w master DOCX:** szablon `cert_master_template.docx` jest jeden, wspólny dla wszystkich wariantów. Admin wkleja placeholdery wewnątrz `{% if %}` block z prefiksem `pola.`:

```jinja
{% if pola.nr_zamowienia_kosmepol %}Nr zamówienia: {{ pola.nr_zamowienia_kosmepol }}{% endif %}
```

Dla wariantów bez tego pola klucz nie istnieje w `pola` → conditional jest fałszywe → blok pomijany → PDF nic nie zawiera. Dla wariantu Kosmepol klucz ma wartość → blok się renderuje.

**Dlaczego sub-namespace `pola.` zamiast top-level:** unika kolizji z istniejącymi top-level kluczami generatora (`produkt`, `szarza`, `expiry`, `avon_code` itd.) oraz z Jinja keywords (`if`, `for`, `in`, `not`...). Eliminuje potrzebę utrzymywania `CONTEXT_RESERVED_KEYS` blacklist. Jest też spójny z prefiksem `pola.<kod>` używanym w widoku Ukończone (kolumny). Walidacja `kod` ogranicza się do regexu `^[a-z][a-z0-9_]*$` — dowolne snake_case słowo jest OK.

**Dezaktywacja pola scope=cert_variant** → klucz znika z `pola` → conditional pomija blok → PDF nic nie zawiera. Nie ma "pustej linii", nie ma literalnego `{{ pola.kod }}` w wyrenderowanym PDF.

**Out-of-scope (na przyszłość):** migracja istniejących Avon-kolumn (`avon_code`, `avon_name`) do `produkt_pola scope=cert_variant`. Ten sam mechanizm jest tam zastosowalny — można pozbyć się dedykowanych kolumn i flag `has_avon_code`/`has_avon_name`. Wymaga jednorazowej zmiany placeholderów w master DOCX (z `{{ avon_code }}` na `{{ pola.avon_code }}`). Osobny spec.

#### 9. Audit

`mbr/shared/audit.py` (istniejący) dostaje nowe eventy:
- `produkt_pola.created`, `produkt_pola.updated`, `produkt_pola.deactivated` — `details_json` zawiera before/after.
- `ebr_pola.value_set` — `details_json: {pole_id, kod, before, after}`.

Spójne ze wzorcem `cert_settings.updated`.

## Data flow — przykład Monamid KO

1. **Technolog** otwiera edytor produktu Monamid KO, zakładka "Pola dodatkowe":
   - Pole 1: `kod=nr_zamowienia, label_pl="Nr zamówienia", typ_danych=text, miejsca=[modal,hero,ukonczone], typy_rejestracji=null, obowiazkowe=0, kolejnosc=10`.
   - Pole 2: `kod=nr_dop_oleju, label_pl="Nr dopuszczenia oleju kokosowego", typ_danych=text, miejsca=[modal,hero,ukonczone], kolejnosc=20`.
2. **Laborant** otwiera modal "Nowa szarża", wybiera Monamid KO, typ=`szarza`. JS dociąga 2 pola, renderuje pod istniejącymi polami modalu. Laborant wpisuje `nr_zamowienia=ZAM/123/2026` i pomija `nr_dop_oleju`. Submit.
3. Backend tworzy szarżę, wstawia `ebr_pola_wartosci(ebr_id, pole_id=<nr_zam_id>, wartosc='ZAM/123/2026')`. Audit: `ebr_pola.value_set`.
4. **Laborant** otwiera Hero szarży, widzi sekcję "Pola dodatkowe": `nr_zamowienia='ZAM/123/2026'` i puste `nr_dop_oleju`. Klika, wpisuje `OL/2026/04/15`, blur. PUT zapisuje wartość.
5. **Po zatwierdzeniu** szarża pojawia się w `/registry/ukonczone`. Tabela ma 2 nowe kolumny ("Nr zamówienia", "Nr dopuszczenia oleju kokosowego") z wartościami.

## Data flow — przykład Chegina KK / zbiornik

1. **Technolog** dla produktu Chegina KK dodaje pole: `kod=ilosc_konserwantuna, label_pl="Ilość konserwantuna", typ_danych=number, jednostka=kg, miejsca=[hero,ukonczone], typy_rejestracji=[zbiornik], kolejnosc=10`.
2. **Laborant** tworzy szarżę typu `szarza` Chegina KK — modal NIE pokazuje pola (filter `'modal' in miejsca` daje false; dodatkowo `typy_rejestracji=[zbiornik]` filtruje).
3. **Laborant** tworzy zbiornik Chegina KK — Hero zbiornika pokazuje pole "Ilość konserwantuna [kg]". Wpisuje `12.5`.
4. Widok Ukończone pokazuje kolumnę dla zbiorników z tą wartością. Dla zwykłych szarż Chegina KK kolumna istnieje (union products), ale komórka pusta.

## Data flow — przykład Kosmepol stały nr zamówienia

1. **Admin** w `/admin/wzory-cert/<variant_id_kosmepol>`, zakładka "Stałe pola" dodaje: `kod=nr_zamowienia_kosmepol, label_pl="Nr zamówienia (Kosmepol)", typ_danych=text, wartosc_stala="KSM/2026/STALY/001"`.
2. **Admin** edytuje master DOCX `cert_master_template.docx` (jeden szablon dla wszystkich wariantów), wstawia w nagłówku conditional: `{% if pola.nr_zamowienia_kosmepol %}Nr zamówienia: {{ pola.nr_zamowienia_kosmepol }}{% endif %}`. Dla wariantów innych niż Kosmepol klucz nie istnieje w `pola`, blok się nie renderuje.
3. **Laborant** generuje świadectwo dla szarży Chegina K40GLOLMB z wybranym wariantem "Kosmepol". Generator dodaje do kontekstu `nr_zamowienia_kosmepol="KSM/2026/STALY/001"`. Renderowane PDF zawiera wartość w nagłówku.
4. Zmiana wartości → admin edytuje `wartosc_stala`, kolejne generacje używają nowej wartości. Historyczne PDF-y pozostają (są na dysku).

## Edge cases

- **Pole zdefiniowane po istniejących szarżach**: brak rekordu w `ebr_pola_wartosci` → komórka w Ukończonych pusta ("—"). Hero pokazuje pole edytowalne, wartość pusta. Akceptowalne.
- **Pole dezaktywowane (`aktywne=0`)**: nie renderowane w nowych formularzach (modal/Hero/Ukończone). Historyczne wartości pozostają w `ebr_pola_wartosci`. Ponowna aktywacja przywraca pole z historycznymi wartościami.
- **Zmiana `typ_danych` po wpisaniu wartości**: ostrzeżenie w UI ("Zmiana typu może spowodować błędy walidacji historycznych wartości"). Wartości NIE są re-walidowane retroaktywnie. Render w UI używa aktualnego `typ_danych` — niezgodne wartości historyczne wyświetlamy raw text z badge "⚠ niezgodne".
- **Zmiana `kod`**: zabronione. Kod jest stabilnym identyfikatorem (klucz placeholderów DOCX, klucz `pola.<kod>` w widoku Ukończone). UI nie pozwala edytować po utworzeniu. Workaround: dezaktywuj stare, utwórz nowe.
- **Pole `obowiazkowe=1` dodane retroaktywnie**: nie blokuje niczego (UI hint only). Stare szarże pokazują pustą czerwoną ramkę w Hero, ale nie wymuszają wpisu.
- **Kolizja `kod` z innymi nazwami w systemie**: nie jest problemem dzięki sub-namespace `pola.<kod>` w kontekście DOCX (patrz §8). Walidacja sprowadza się do regexu snake_case + UNIQUE per `(scope, scope_id)`.
- **Hard-delete produktu / cert_variant**: nie kasujemy `produkt_pola` ani `ebr_pola_wartosci`. Rekordy zostają jako sieroty bez logicznej referencji — niewidoczne w UI (widoki Ukończone / modal / Hero filtrują po produkcie aktywnej szarży, więc sierot nie zobaczą). Wartości pozostają dla compliance/audytu. Zaleta: zero modyfikacji istniejących endpointów kasujących produkt/cert_variant. Wada: drobne "śmieci" w bazie po rzadkim hard-delete — pomijalne.
- **Wpis tej samej wartości pola dla zbiornika i jego szarży źródłowej**: model nie ma relacji szarża↔zbiornik na poziomie pól. Każda szarża/zbiornik ma własne `ebr_id` i własne wartości. Konfiguracja `typy_rejestracji=[zbiornik]` ogranicza pole do zbiorników; `typy_rejestracji=null` pokazuje wszędzie (ale wartości i tak są niezależne per `ebr_id`).
- **Pole scope=cert_variant z `wartosc_stala=NULL` lub pustym**: walidacja przy `create_pole`/`update_pole` dla scope=cert_variant z `aktywne=1` **wymusza** niepustą `wartosc_stala` (NOT NULL + length>0). Z `aktywne=0` wartość nie ma znaczenia — i tak klucz nie trafia do kontekstu generatora.
- **Dezaktywacja pola scope=cert_variant + placeholder `{% if kod %}` w DOCX zostaje**: klucz nie trafia do kontekstu, conditional pomija blok, PDF czysty. Admin może bezpiecznie zostawić nieużywany conditional w DOCX.

## Tests

`tests/test_produkt_pola_dao.py`:
- CRUD definicji.
- UNIQUE `(scope, scope_id, kod)`.
- Walidacja `typ_danych` przy `set_wartosc()` (`number`, `date`).
- Filtry `list_pola_for_produkt(miejsce='modal', typ_rejestracji='zbiornik')` zwracają tylko pasujące.
- `validate_required_fields()` zwraca listę pustych obowiązkowych.
- Audit eventy emitowane.

`tests/test_produkt_pola_api.py`:
- POST `/api/produkt-pola` — happy path, walidacja kodu (regex `^[a-z][a-z0-9_]*$`), walidacja unique.
- PUT — happy path, brak edycji `kod`.
- DELETE — soft-delete.
- PUT `/api/ebr/<ebr_id>/pola/<pole_id>` — happy path + walidacja wartości wg `typ_danych`.

`tests/test_registry_pola_columns.py`:
- `get_registry_columns()` zawiera dynamiczne kolumny dla pól z `'ukonczone' in miejsca`.
- `list_completed_registry()` zwraca wartości w `d["pola"][kod]`.
- Pole nieaktywne nie pojawia się w kolumnach (ale jeśli było wcześniej aktywne, historyczne wartości pozostają w bazie).

`tests/test_certs_pola_variant.py`:
- `build_context()` dla wariantu Kosmepol zawiera klucze pól scope=cert_variant.
- Stała wartość `wartosc_stala` propaguje się do kontekstu.
- `context["pola"]` zawiera tylko klucze z aktywnego wariantu (inne warianty dają inny `context["pola"]`).

Smoke test ręczny:
- Modal Monamid KO → wpis pól → szarża → Hero edycja → Ukończone widok → kolumny.
- Chegina KK zbiornik → Hero "Ilość konserwantuna" → Ukończone.
- Kosmepol wariant: dodanie pola, edycja DOCX z placeholderem, generacja PDF.

## Sequence of implementation

1. Schema migration (idempotent CREATE TABLE) — `mbr/models.py`.
2. DAO `mbr/shared/produkt_pola.py` + `tests/test_produkt_pola_dao.py`.
3. API endpointy `mbr/produkt_pola/routes.py` + bp registration + `tests/test_produkt_pola_api.py`.
4. UI definicji w Technolog (scope=produkt) — formularze + smoke test.
5. UI definicji w Admin (scope=cert_variant) — formularze + smoke test.
6. Integracja z modalem tworzenia EBR (frontend + backend create_ebr).
7. Integracja z Hero (frontend dynamic fields + endpoint PUT wartości).
8. Integracja z `registry` (kolumny dynamiczne) + `tests/test_registry_pola_columns.py`.
9. Integracja z generatorem certów + `tests/test_certs_pola_variant.py`.
10. Audit eventy podpięte we wszystkich punktach + manualny smoke test E2E (Monamid KO, Chegina KK, Kosmepol).
11. Krótka notka w `CLAUDE.md` (sekcja "Conventions" lub "Architecture") opisująca mechanizm.

Każdy krok osobny commit. Kroki 6–9 mogą iść równolegle po zakończeniu 1–3.

## Zgodność z obecną architekturą

- Wzorzec `cert_variants` (definicje w bazie + edytor w UI) — analogiczny.
- Wzorzec `parametry_etapy` (definicje per produkt + filtrowanie w listingu) — analogiczny.
- Wzorzec `cert_settings` (key-value z auditem) — częściowo analogiczny.
- ML/DL roadmapa (memory: `project_ml_goal`): pola normalized → eksport łatwy. Spójne z `ml_export_long_format`.
- Parametry SSOT refactor (memory: `project_parametry_ssot`): nie koliduje. Parametry to dane pomiarowe (`parametry_analityczne`/`ebr_wyniki`), pola dodatkowe to metadane szarży/wariantu (`produkt_pola`/`ebr_pola_wartosci`). Osobne tabele, osobny model, osobne UI.

## Zależność od pod-projektu B i C

- **B (korelacje raw→cert)**: niezależny. B operuje na `parametry_analityczne` / `ebr_wyniki`, A na nowych tabelach. Można wdrażać równolegle.
- **C (deklaratywny generator + nietypowe daty ważności)**: A wprowadza tylko nowe placeholdery DOCX dla scope=cert_variant. Gdy C zastąpi DOCX, pola scope=cert_variant migrują się naturalnie (ten sam dict kontekstu, tylko inny silnik renderujący).
