# Parametry: rejestr jako SSOT dla nazw i metod na świadectwach

**Data:** 2026-04-25
**Status:** spec — do akceptacji
**Kontekst poprzedni:** [Parametry SSOT refactor (PR 1–7, 2026-04-16)](2026-04-16-parametry-ssot-design.md)

## Problem

Obecny model trzyma nazwy parametrów i numery metod w **dwóch warstwach**:

1. **Rejestr** (`parametry_analityczne`) — pola `label`, `name_en`, `method_code`, `skrot`, `jednostka`. Edytowany w `/parametry` (panel admina).
2. **Override per-cert** (`parametry_cert`) — pola `name_pl`, `name_en`, `method`. Edytowany w `/admin/wzory-cert`.

Generator certu (`get_cert_params` w `mbr/parametry/registry.py`) używa `COALESCE(override, registry)` — override wygrywa.

**Stan rzeczywisty w produkcji** (sprawdzone 2026-04-25):
- 319 wierszy `parametry_cert`
- 91% ma override `name_en`
- 91% ma override `method`
- 61% ma override `name_pl`

**Konsekwencja:** zmiana w rejestrze (np. nowy numer normy `L914 → L914-rev2`) **nie propaguje się** do świadectw — admin musi ręcznie edytować ten sam parametr na każdym świadectwie z osobna. To jest pain point operacyjny i ML-unfriendly (rozproszone, niespójne dane).

## Cel

Rejestr `parametry_analityczne` staje się **jedynym źródłem prawdy** dla nazw i metod. Cert editor zapisuje wyłącznie selekcję parametrów (`parametr_id`, `kolejnosc`, `requirement`, `format`, `qualitative_result`, `variant_id`). Edycja w jednym miejscu propaguje się do wszystkich świadectw.

**Constraint zgłoszony przez użytkownika:** bez przebudowy schematu DB. Wykorzystujemy istniejące pola rejestru.

## Zakres

### W zakresie

- Migracja danych z `parametry_cert.name_pl/en/method` do `parametry_analityczne.label/name_en/method_code` (algorytm K3 — najczęstszy override jako kanoniczny).
- Modyfikacja generatora — odczyt wprost z rejestru gdy flaga włączona.
- UI cert editora — usunięcie pól tekstowych (nazwa/metoda) gdy flaga włączona, dodanie linku do rejestru.
- Globalny toggle `use_registry_only` w `cert_settings`.
- Raport konfliktów (`migration_report.md`) dla parametrów z wieloma wariantami override.
- Audit log zmian w rejestrze (event `parametry.registry.updated`).

### Poza zakresem

- ALTER TABLE / nowe kolumny.
- Per-cert override dla wariantów (`variant_id`) — ten sam parametr na różnych wariantach tego samego produktu ma identyczną nazwę.
- Rozbicie konfliktowych parametrów (np. pH × różne stężenia) na osobne wpisy w rejestrze — to jest decyzja **operacyjna po migracji**, podejmowana ręcznie przez admina na podstawie raportu.
- Snapshot historycznych świadectw (re-render starego PDF używa aktualnego stanu rejestru).
- Per-parametr historia zmian w UI (`/parametry`) — follow-up.

## Architektura

### Stan obecny

```
cert editor (/admin/wzory-cert)
    └─ PUT /api/cert/config/product/<key>
         └─ zapis do parametry_cert (z polami name_pl, name_en, method)

generator (DOCX render)
    └─ get_cert_params()
         └─ SELECT pc.*, pa.*
            FROM parametry_cert pc JOIN parametry_analityczne pa
            ORDER BY kolejnosc
         └─ COALESCE(NULLIF(pc.name_pl, ''), pa.label)
            COALESCE(NULLIF(pc.name_en, ''), pa.name_en)
            COALESCE(NULLIF(pc.method,  ''), pa.method_code)
```

### Stan docelowy (flaga ON)

```
panel /parametry  ─── edytuje parametry_analityczne (SSOT)
                        │
                        ▼ propagacja natychmiastowa
cert editor       ─── zapisuje TYLKO selekcję
    └─ PUT /api/cert/config/product/<key>
         └─ ignore name_pl/en/method (NULL'uje gdy flaga ON)

generator
    └─ get_cert_params()
         └─ jeśli use_registry_only=ON:
              SELECT pa.label, pa.name_en, pa.method_code WPROST z rejestru
            else:
              zachowanie po staremu (legacy COALESCE)
```

### Flaga: `cert_settings('use_registry_only', '0'|'1')`

- Przechowywana w istniejącej tabeli `cert_settings` (key/value).
- Czytana **per żądanie** w `get_cert_params` i w `GET /api/cert/config/product/<key>`.
- **Skrypt migracyjny NIE włącza flagi automatycznie** — domyślna wartość po migracji to `'0'` (OFF, legacy COALESCE). Admin włącza ręcznie po smoke teście render kilku świadectw.
- Rollback flagi bez deployu kodu — admin zmienia wartość na `'0'` przez globalny toggle w `/admin/wzory-cert`.

## Model danych (bez ALTER)

### `parametry_analityczne` (rejestr — SSOT)

Pola używane jako źródło prawdy:

| pole | rola | przykład |
|---|---|---|
| `label` | nazwa PL na świadectwie i w MBR/kartach | `Liczba kwasowa [mg KOH/g]` |
| `name_en` | nazwa EN na świadectwie | `Acid value [mg KOH/g]` |
| `method_code` | numer metody / norma | `L914` lub `PN-EN ISO 660:2021-03` |
| `skrot` | skrót dla compact UI laboranta | `LK` |
| `jednostka` | jednostka (osobna kolumna w karcie/cercie lub inline w `label`) | `mg KOH/g` |

### `parametry_cert` (selekcja per produkt/wariant)

Po migracji:

| pole | rola | uwaga |
|---|---|---|
| `produkt`, `variant_id`, `parametr_id` | klucz selekcji | bez zmian |
| `kolejnosc` | kolejność na świadectwie | bez zmian |
| `requirement` | wymaganie / specyfikacja | bez zmian |
| `format` | format wyświetlania wartości | bez zmian |
| `qualitative_result` | dla parametrów jakościowych | bez zmian |
| `name_pl`, `name_en`, `method` | **NULL po migracji**, ignorowane przez generator | pozostają w schemacie do ewentualnego rollbacku |

## Migracja danych — algorytm K3

### Skrypt

`scripts/migrate_cert_overrides_to_registry.py`

Flagi: `--dry-run` (default), `--apply`, `--force` (pomiń check `_migrations` markera), `--verify-only` (sprawdź spójność po migracji).

Backup: `data/batch_db.sqlite.bak-pre-cert-ssot` (auto przed `--apply`).

Marker w `_migrations`: `cert_overrides_to_registry_v1`.

### Algorytm (per `parametr_id`)

1. Zbierz wszystkie wiersze `parametry_cert` dla danego `parametr_id`.
2. Dla każdego z trzech pól (`name_pl`, `name_en`, `method`) policz **mode** — najczęściej występującą niepustą wartość (NULL/empty pomijane).
3. Heurystyka aktualizacji rejestru: nadpisz `parametry_analityczne.label` mode'em **tylko jeśli** obecna wartość rejestru jest pusta lub krótsza (cert-grade tekst zwykle pełniejszy, np. `"Liczba kwasowa [mg KOH/g]"` > `"Liczba kwasowa końcowa"`). Analogicznie `name_en`, `method_code`.
4. Wyzeruj `parametry_cert.name_pl/en/method` na NULL.
5. Wpisz wpis do `audit` z eventem `parametry.registry.migrated_from_cert_overrides`.

### Raport konfliktów (`migration_report.md`)

Dla każdego `parametr_id` z >1 unikalnym overridem (po deduplikacji NULL/whitespace):

```markdown
## parametr_id=2 (kod=ph_10proc, label=pH roztworu 10%)

### Konflikt: name_en (8 wariantów)
- `pH (5%, aq, 25°C)` — produkty: Chegina_CC (2 warianty)
- `pH (10%, aq, 25°C)` — produkty: Alstermid_K, Chegina_K40GL, Chegina_K40GLO, ...
- `pH (1%, aq, 25°C)` — produkty: ...
- ...

### Wybrana wartość kanoniczna (K3 mode): `pH (10%, aq, 25°C)`
### Sugestia: rozważ rozbicie na osobne wpisy w rejestrze (analogicznie do dotychczasowego rozbicia pH × 3).
```

Plik commitowany do `docs/superpowers/migration-reports/2026-XX-XX-cert-overrides.md` jako ścieżka audytu.

### Spodziewane konflikty

Z bazy 2026-04-25:

| parametr_id | kod | n wariantów | pole konfliktowe |
|---|---|---|---|
| 2 | ph_10proc | 8 | name_en |
| 53 | cert_qual_appearance | 4 | method |
| 40 | li | 4 | method |
| 39 | wolny_glikol | 3 | method/name_en |
| 30 | wkt | 3 | name_en |
| 3 | nd20 | 3 | name_en |
| 52 | cert_qual_odour | 2 | mix |
| 49 | barwa_I2 | 2 | mix |
| 43 | dietanolamina | 2 | mix |
| 38 | lh | 2 | mix |
| 36 | t_kropl | 2 | mix |
| 35 | lz | 2 | mix |
| 19 | sa | 2 | mix |
| 12 | lk | 2 | mix |
| 57 | cert_qual_c18 | 2 | mix |
| 56 | cert_qual_c16 | 2 | mix |

Łącznie: 16 parametrów wymaga ręcznej decyzji po migracji.

### Decyzje operacyjne post-migracja (manualne, poza scope skryptu)

Dla każdego parametru w raporcie admin decyduje:

- **Rozbij** na osobne wpisy w rejestrze (jak pH × 3) i przepnij `parametry_cert.parametr_id` na nowe id-y. (Wymaga ręcznych UPDATE-ów + ewentualnie nowego skryptu.)
- **Zaakceptuj kanoniczną** (mode wybrany przez K3) i pozwól na ujednolicenie świadectw.

## Komponenty do zmiany

### Backend

- `mbr/parametry/registry.py`:
  - Nowa funkcja `_use_registry_only(db)` — czyta `cert_settings('use_registry_only', '0')`.
  - `get_cert_params(db, produkt, variant_id=None)` — gałąź `if _use_registry_only(db)` z SELECT-em wprost z rejestru.
  - `get_cert_variant_params(...)` — analogicznie.

- `mbr/certs/routes.py` (lub gdzie jest `PUT /api/cert/config/product/<key>`):
  - Gdy flaga ON: w sekcji upsert do `parametry_cert` ignoruj pola `name_pl/name_en/method` (zapisuj NULL).

- `mbr/certs/routes.py`: nowy endpoint `GET/PUT /api/cert/settings/use-registry-only` (boolean) lub rozszerzenie istniejącego endpointu globalnych ustawień.

- `mbr/parametry/routes.py`:
  - `PUT /api/parametry/<id>` — dodać event `parametry.registry.updated` w `audit` (kto/kiedy/przed/po) gdy zmienia się `label`, `name_en`, `method_code`.

### Frontend

- `mbr/templates/admin/wzory_cert.html`:
  - Modal edycji parametru: gdy `use_registry_only === true`, pola `name_pl`, `name_en`, `method` renderowane jako `<input readonly>` z wartością z rejestru + ikonka linku `[edytuj w rejestrze →]` z `href="/parametry#param-{id}"`.
  - W "Ustawieniach globalnych" (sekcja istniejąca dla typografii) checkbox **"Używaj rejestru jako jedynego źródła nazw/metod (SSOT)"** — PUT do `cert_settings`.

- `mbr/templates/parametry*.html` (panel admina):
  - Anchor scroll: każdy wiersz parametru ma `id="param-<id>"` żeby link z cert editora przewinął do właściwego rekordu.

## Testowanie

### Migracja

`tests/test_migrate_cert_overrides.py` (6 testów):

1. `test_dry_run_no_changes` — `--dry-run` nie modyfikuje DB.
2. `test_k3_picks_mode` — 3 produkty z `"L914"` + 1 z `"L914-rev"` → kanoniczne `"L914"`.
3. `test_overwrite_when_registry_shorter` — registry `"Liczba kwasowa końcowa"` + cert mode `"Liczba kwasowa [mg KOH/g]"` → registry zostaje nadpisany.
4. `test_no_overwrite_when_registry_equal_or_longer` — registry pełniejszy niż cert → registry zachowany.
5. `test_conflict_report_lists_multivariant` — `parametr_id` z 3 różnymi overridami trafia do raportu z listą produktów.
6. `test_idempotent` — drugi run = no-op (sprawdza marker w `_migrations`).

### Generator + flaga

`tests/test_cert_params_use_registry_only.py` (4 testy):

1. `test_flag_off_legacy_coalesce` — flag=`'0'` → COALESCE zachowanie po staremu.
2. `test_flag_on_reads_registry` — flag=`'1'` → wartości z rejestru.
3. `test_flag_on_ignores_lingering_overrides` — flag=`'1'` + override `name_pl="X"` w DB → wynik z rejestru (nie `"X"`).
4. `test_unit_always_from_registry` — sanity check: `jednostka` zawsze z rejestru, niezależnie od flagi.

### Cert editor UI / API

`tests/test_cert_editor_flag.py` (3 testy):

1. `test_get_config_returns_flag` — odpowiedź zawiera `use_registry_only: true/false`.
2. `test_put_config_with_flag_on_drops_text_fields` — PUT z `name_pl="X"` przy fladze ON → DB ma NULL.
3. `test_settings_endpoint_roundtrip` — PUT flagi → GET zwraca nową wartość.

### Pełna suite

Zachować zielony stan: 583 passed, 19 skipped → po migracji ~596 passed.

## Edge cases i ryzyka

- **Re-render starego świadectwa** używa aktualnego rejestru, nie wartości historycznych. Akceptowalne, bo zachowane PDF-y w archiwum nie są ruszane. Snapshot historyczny → osobny temat.
- **Wariant `variant_id`** — bez zmian. Selekcja parametrów per wariant zostaje, nazwy ZAWSZE z rejestru. Jeśli kiedyś będzie potrzeba różnej nazwy per wariant — osobny refactor.
- **Migracja konfliktów (~15 parametr_id z różnymi overridami)** — skrypt wybiera mode automatycznie, raport oznacza je do ręcznego review. Admin decyduje stopniowo (nie blokuje merge'a).
- **Rollback dwupoziomowy:**
  - **Poziom 1 — przełączenie flagi** (`cert_settings.use_registry_only` na `'0'`). Generator wraca do COALESCE, ale ponieważ `parametry_cert.name_pl/en/method` są NULL po migracji, COALESCE i tak zwróci wartości z rejestru. Czyli sama flaga nie wraca do "stanu przed". Skuteczne tylko jeśli problem leży w gałęzi kodu (rzadkie).
  - **Poziom 2 — pełny rollback** wymaga restore z `data/batch_db.sqlite.bak-pre-cert-ssot`. Przywraca overridy w `parametry_cert` + flaga = `'0'` → stan sprzed migracji.
- **Defensywny PUT cert config** — gdy flaga ON, route ignoruje `name_pl/en/method` w żądaniu. Zapobiega zapisom z starych klientów / cache UI.

## Kryteria akceptacji

- [ ] Skrypt migracyjny przechodzi w `--dry-run` i `--apply` na kopii produkcyjnej DB bez błędów.
- [ ] Raport konfliktów wygenerowany i zacommitowany.
- [ ] Pełna suite testów zielona po migracji.
- [ ] Smoke test: render świadectwa dla 3 produktów (Chegina_CC, Alstermid_K, Chegina_K40GLO) przed włączeniem flagi → po włączeniu flagi → manualne porównanie PDF-ów (różnice tylko w polach gdzie K3 wybrał inną wersję niż obecny override).
- [ ] Edycja parametru w `/parametry` (zmiana `method_code`) propaguje się do wszystkich świadectw używających tego parametru po następnym renderze.
- [ ] Rollback flagi działa (przełączenie `cert_settings.use_registry_only` na `'0'` + restore DB z backupu = stan sprzed migracji).

## Plan wdrożenia

1. **PR 1** — skrypt migracyjny + testy. Run na staging DB. Generuje raport konfliktów do review.
2. **PR 2** — generator (gałąź flagi) + testy.
3. **PR 3** — cert editor UI (flaga ON tryb read-only + link do rejestru) + globalny toggle.
4. **PR 4** — audit event `parametry.registry.updated` w `/parametry` PUT.
5. **Deploy migracji** — backup DB, run skryptu, weryfikacja raportu konfliktów. Flaga zostaje OFF.
6. **Smoke test** — render świadectw dla 3 produktów (Chegina_CC, Alstermid_K, Chegina_K40GLO) z flagą OFF (legacy) i ON (nowa ścieżka), porównanie PDF-ów.
7. **Włączenie flagi** — toggle w `/admin/wzory-cert` na ON dla całej instalacji.
8. **Post-deploy** — review raportu konfliktów, decyzje per-parametr (rozbij vs zaakceptuj kanoniczną).

Dekompozycja na PR-y zostanie doprecyzowana w planie implementacyjnym (writing-plans).
