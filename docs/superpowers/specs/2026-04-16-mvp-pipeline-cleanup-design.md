# Spec — MVP pipeline cleanup + SSOT unification

**Data:** 2026-04-16
**Status:** zatwierdzony, gotowy do pisania planu implementacyjnego
**Zakres:** MVP ograniczenie multi-stage pipeline do Chegina_K7 + ujednolicenie "multi-stage?" jako jedno źródło prawdy (DB)

## Kontekst

Po PR 1-6 (parametry SSOT refactor) zostały trzy artefakty utrudniające MVP:

1. **3 źródła prawdy** dla "czy produkt ma multi-stage pipeline":
   - `produkt_pipeline` (DB, per-product analytical stages)
   - `produkt_etapy` (DB, per-product process workflow stages)
   - `FULL_PIPELINE_PRODUCTS` + `PROCESS_STAGES_K7` + `ROZJASNIANIE_PRODUCTS` (konstanty Python w `mbr/etapy/models.py`)

2. **Migracja PR 1 utworzyła multi-stage pipeline dla Chegina_K40GL/GLO/GLOL** (przez `ensure_pipeline_for_legacy` — bazując na orphanach `produkt_etap_limity`). Dla MVP te produkty mają mieć TYLKO `analiza_koncowa`.

3. **Model K7 ma artefakty**: `dodatki` jako osobny etap w `produkt_pipeline` (ale dodatki są per-etap w `etap_korekty_katalog`, nie osobnym etapem), `analiza_koncowa` w szarży (ale szarża K7 kończy się na `standaryzacji`, `analiza_koncowa` to etap zbiornikowy).

## Cele MVP

1. **Jeden SSOT dla "multi-stage":** `produkt_pipeline` w DB. Bez konstant Python.
2. **Chegina_K7 szarża ma 3 etapy workflow**: sulfonowanie → utlenienie → standaryzacja. Każdy z panelem korekt (substancje + formuły z `etap_korekty_katalog`). Pomiar → korekta (podpowiedź z formuły) → ponowny pomiar → gate.
3. **Chegina_K7 zbiornik** widzi tylko `analiza_koncowa`.
4. **Wszystkie pozostałe produkty** (szarża i zbiornik) widzą tylko `analiza_koncowa` — prosty, jednoekranowy card.
5. **Extended card = tylko gdy `pipeline_has_multi_stage(produkt)` AND szarża** (nie zbiornik).

## Non-goals

- Unifikacja `etapy_analityczne` + `etapy_procesowe` w jedną tabelę (to osobny refaktor post-MVP).
- Wywalenie `mbr_templates.parametry_lab` kolumny (wciąż pisana przez technolog flow; nieczytana po PR 2).
- Wywalenie tabeli `parametry_etapy` (rezydualne wpisy, brak czytelników krytycznych ścieżek).
- Unifikacja `produkt_pipeline` i `produkt_etapy` (są ortogonalne: co mierzę vs kiedy dzieje się w workflow).
- Przeprojektowanie technolog MBR edit UI (spot-fix jeśli format JSON parametry_lab breaking).

## Decyzje architektoniczne

### D1: `produkt_pipeline` jest jedynym SSOT dla "multi-stage"

Helper `pipeline_has_multi_stage(db, produkt) -> bool` = `SELECT COUNT(*) FROM produkt_pipeline WHERE produkt=? > 1`. Zastępuje `produkt in FULL_PIPELINE_PRODUCTS`.

### D2: Filter `build_pipeline_context` po typ flag pomija puste etapy

Dla `typ != None`: po filtrze parametrów po `dla_<typ>=1`, jeśli lista params jest pusta → skip cały etap (nie wchodzi do `etapy_json` ani `parametry_lab`). Efekt: K7 zbiornik automatycznie widzi tylko `analiza_koncowa`, bo pozostałe etapy nie mają parametrów z `dla_zbiornika=1`.

### D3: K7 szarża ma 3 etapy, nie 5

`dodatki` jako etap zostaje usunięty z `produkt_pipeline` dla K7 — jest artefakt starej architektury. Dodatki jako substancje korygujące pozostają w `etap_korekty_katalog` per-etap (niezmienione).

`analiza_koncowa` pozostaje w `produkt_pipeline` K7, ale parametry mają `dla_szarzy=0, dla_zbiornika=1`. Widoczne tylko w widoku zbiornika.

Sulfonowanie/utlenienie/standaryzacja parametry: `dla_szarzy=1, dla_zbiornika=0`.

### D4: Non-K7 Cheginy mają tylko analiza_koncowa

Dla K40GL/GLO/GLOL/K40GLOS/K40GLOL_HQ/K40GLN/GLOL40:
- `produkt_pipeline` zostaje tylko wpis dla `analiza_koncowa`
- `produkt_etapy` wszystkie wpisy usunięte (brak workflow procesowego)
- `produkt_etap_limity` orphans (etap_id nie występuje już w `produkt_pipeline`) → DELETE

### D5: `FULL_PIPELINE_PRODUCTS` i pokrewne konstanty znikają

`mbr/etapy/models.py` traci:
- `FULL_PIPELINE_PRODUCTS`
- `ROZJASNIANIE_PRODUCTS`
- `PROCESS_STAGES_K7`
- `PROCESS_STAGES_GLOL`

Callerzy migrują na DB:
- `get_process_stages(produkt)` — tylko DB (`produkt_etapy`), bez fallbacku. Brak wierszy → `[]`.
- `build_parametry_lab(db, produkt)` — używa `build_pipeline_context(db, produkt, typ=None)["parametry_lab"]`. Format JSON się zmienia: dla produktu z multi-stage struktura `{sulfonowanie: {...}, utlenienie: {...}, analiza: {...}, analiza_koncowa: {...}}`; dla single-stage `{analiza_koncowa: {...}}`.

## Komponenty zmienione

| Plik | Zmiana |
|---|---|
| `scripts/mvp_pipeline_cleanup.py` | Nowy skrypt migracji (PR 1) |
| `mbr/pipeline/models.py` | Nowy helper `pipeline_has_multi_stage()` |
| `mbr/pipeline/adapter.py` | `build_pipeline_context` skip empty etap gdy typ ≠ None |
| `mbr/etapy/models.py` | Usunięcie 4 konstant, uproszczenie `get_process_stages` |
| `mbr/parametry/registry.py` | `build_parametry_lab` przez `build_pipeline_context`, usunięcie importu `FULL_PIPELINE_PRODUCTS` |
| `tests/test_etapy.py` | Update testów `FULL_PIPELINE_PRODUCTS` na DB-driven |
| `tests/test_parametry_registry.py` | Update asercji `build_parametry_lab` (nowy format) |
| `tests/test_pipeline_adapter.py` | Dodać test: skip empty etap gdy typ ≠ None |
| `tests/test_mvp_pipeline_cleanup.py` | Nowe testy cleanup scriptu |

## Data cleanup — `scripts/mvp_pipeline_cleanup.py`

Idempotentny, z backupem, `--dry-run`, `--verify-only`. Marker w `_migrations` = `mvp_pipeline_cleanup_v1`.

### Kroki

1. **Backup** → `data/batch_db.sqlite.bak-pre-mvp-cleanup`.
2. **Whitelist MVP**: `MVP_MULTI_STAGE = {"Chegina_K7"}`.
3. **Dla każdego produktu spoza whitelisty** z wpisami multi-stage w `produkt_pipeline`:
   - DELETE wiersze `produkt_pipeline` poza `etap_id = <analiza_koncowa>`.
   - Jeśli brak wiersza dla `analiza_koncowa` → INSERT.
   - DELETE z `produkt_etapy` (wszystkie wpisy workflow procesowego).
4. **Dla K7** (whitelist):
   - DELETE wiersz `produkt_pipeline` dla `dodatki`.
   - UPDATE `produkt_etap_limity` dla K7 parametrów: sulfonowanie/utlenienie/standaryzacja → `dla_szarzy=1, dla_zbiornika=0`; analiza_koncowa → `dla_szarzy=0, dla_zbiornika=1`.
   - DELETE `produkt_etap_limity` dla K7 w `etap_id=dodatki` (4 wiersze).
   - DELETE `produkt_etapy` K7 wpisy: amidowanie, namca, czwartorzedowanie (zostają: sulfonowanie, utlenienie + dodajemy standaryzacja jeśli brak).
5. **Orphan cleanup**: DELETE `produkt_etap_limity` gdzie (produkt, etap_id) NOT IN `produkt_pipeline`.
6. **Postflight**:
   - Każdy `mbr_templates.status='active'` produkt ma ≥1 wiersz w `produkt_pipeline`.
   - Dla K7: produkt_pipeline zawiera dokładnie {sulfonowanie, utlenienie, standaryzacja, analiza_koncowa}.
   - Dla non-K7 Cheginy: produkt_pipeline zawiera tylko {analiza_koncowa}.
7. **Marker** i commit.

### Sanity — stan po uruchomieniu na real DB

| Produkt | produkt_pipeline pre | produkt_pipeline post | produkt_etapy pre | produkt_etapy post |
|---|---|---|---|---|
| Chegina_K7 | 5 | 4 (minus dodatki) | 5 | 3 (sulfon/utlen/standard) |
| Chegina_K40GL | 5 | 1 | 5 | 0 |
| Chegina_K40GLO | 5 | 1 | 6 | 0 |
| Chegina_K40GLOL | 7 | 1 | 6 | 0 |
| pozostałe | 1 | 1 | 0 | 0 |

## Ścieżki odczytu po refaktorze

```
build_pipeline_context(db, produkt, typ)
    pipeline = get_produkt_pipeline(db, produkt)
    for step in pipeline:
        params = resolve_limity(db, produkt, step.etap_id)
        params = filter_by_dla_typ(params, typ)  # istnieje od PR 2
        if not params and typ is not None:
            continue  # NOWE: skip empty etap
        etapy_json.append(step)
        parametry_lab[sekcja_key] = params
    return {etapy_json, parametry_lab}

build_parametry_lab(db, produkt)
    ctx = build_pipeline_context(db, produkt, typ=None)
    return ctx["parametry_lab"] if ctx else {}

get_process_stages(produkt)
    rows = db.execute("SELECT etap_kod FROM produkt_etapy JOIN etapy_procesowe ... WHERE produkt=?")
    return [r["etap_kod"] for r in rows]  # [] if no rows

pipeline_has_multi_stage(db, produkt)
    return db.execute("SELECT COUNT(*) FROM produkt_pipeline WHERE produkt=?").fetchone()["n"] > 1
```

## Rollout — 3 PRki

| PR | Zawartość | Ryzyko |
|---|---|---|
| **PR 1 — Data cleanup** | `scripts/mvp_pipeline_cleanup.py` + uruchomienie na real DB. Zero zmiany kodu runtime. | Niskie (backup, idempotent, dry-run) |
| **PR 2 — Filter + helper** | `pipeline_has_multi_stage()`. `build_pipeline_context` skip empty etap. Golden tests K7 + Chelamid_DK. | Średnie (render path) |
| **PR 3 — Remove constants** | Usunięcie `FULL_PIPELINE_PRODUCTS` + pokrewne. Refactor `get_process_stages`, `build_parametry_lab`. Update testów. | Średnie (wielu callerów) |

## Kryterium "gotowe"

1. `pytest -q` zielone (~548+ tests)
2. Chegina_K7 szarża → 3 etapy workflow (sulfonowanie, utlenienie, standaryzacja) z korektami
3. Chegina_K7 zbiornik → 1 etap (analiza_koncowa)
4. Chelamid_DK szarża → 1 etap (analiza_koncowa) — bez zmian vs. stan przed cleanup
5. Chegina_K40GL szarża → 1 etap (analiza_koncowa) — upraszczone z 5
6. `grep -r FULL_PIPELINE_PRODUCTS mbr/` → 0 trafień
7. Spot-check: `mvp_pipeline_cleanup_v1` marker obecny w `_migrations` na prod DB

## Ryzyko i rollback

- **`scripts/mvp_pipeline_cleanup.py` wybucha mid-run** → rollback transakcji (wszystko w jednym BEGIN/COMMIT)
- **Post-cleanup weryfikacja failuje** → rollback + raport
- **Cokolwiek innego** → restore z `data/batch_db.sqlite.bak-pre-mvp-cleanup`
- **Technolog MBR UI po PR 3 nie otwiera template** → spot fix formatu JSON lub tymczasowy adapter w `save_mbr`

## Co NIE zostało rozwiązane (tech debt na później)

- `mbr_templates.parametry_lab` kolumna (pisana przez technolog, nie czytana)
- `parametry_etapy` tabela (residualne dane)
- `etapy_procesowe` + `etapy_analityczne` dublujące się kody (sulfonowanie, utlenienie w obu) — ortogonalne role ale zagadka nazewnicza
- Technolog MBR edit UI — nie używa nowego /api/bindings, ma własny stary flow
