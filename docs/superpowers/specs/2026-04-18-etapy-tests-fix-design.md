# Fix 7 failing etapy tests — align in-memory seed with MVP cleanup

**Data:** 2026-04-18
**Status:** zatwierdzony do pisania planu
**Zakres:** jeden plik (`mbr/models.py`) — wyrównanie seed-u `init_mbr_tables` ze stanem post-MVP workflow cleanup

## Kontekst

MVP pipeline cleanup (spec `2026-04-16-mvp-pipeline-cleanup-design.md`, commit `80ccc1d`) świadomie zawężył:

- **Chegina_K7 szarża** → 3 etapy procesowe: `sulfonowanie` → `utlenienie` → `standaryzacja`.
- **GLOL products** (K40GL, K40GLO, K40GLOL, itp.) → brak workflow procesowego, tylko `analiza_koncowa`.

Zmiana została zrealizowana przez jednorazowy skrypt `scripts/mvp_pipeline_cleanup.py`, który stawia marker `mvp_pipeline_cleanup_v1` w tabeli `_migrations` prod DB. Testy (`tests/test_etapy.py`, `tests/test_parametry_registry.py`) zostały zaktualizowane do asercji post-MVP.

**Problem:** `init_mbr_tables` (`mbr/models.py:372-399`) nadal ma **pre-MVP** seed dla `produkt_etapy` — K7 dostaje 5 etapów (amidowanie, namca, czwartorzedowanie, sulfonowanie, utlenienie), GLOL products dostają ten sam 5-etapowy zestaw. Zachowanie seed-u jest gated przez marker `mvp_pipeline_cleanup_v1` w `_migrations`, ale in-memory DB (fresh test fixture) nigdy nie ma tego markera — seed wykonuje się bezwarunkowo → testy failują.

Prod DB jest OK (migracja wykonana, marker istnieje, seed pomijany). To wyłącznie problem alignmentu in-memory test setup ↔ post-MVP design.

## Failing testy

- `tests/test_etapy.py::test_get_process_stages_k7_returns_3`
- `tests/test_etapy.py::test_get_process_stages_glol_returns_empty_after_mvp`
- `tests/test_etapy.py::test_get_process_stages_k40gl_empty_after_mvp`
- `tests/test_etapy.py::test_init_etapy_status_non_parallel_stages_start_as_pending`
- `tests/test_etapy.py::test_init_etapy_status_glol_creates_no_stages_after_mvp`
- `tests/test_parametry_registry.py::test_etapy_config_k7`
- `tests/test_parametry_registry.py::test_etapy_config_glol_empty_after_mvp`

## Rozwiązanie

Jedna zmiana w `mbr/models.py` w bloku `init_mbr_tables` seed-u `produkt_etapy` (ok. linie 372-399):

### 1. `_K7_STAGES` → 3 etapy post-MVP

**Dziś** (5 etapów pre-MVP, amidowanie/namca/czwartorzedowanie + sulfonowanie/utlenienie):

```python
_K7_STAGES = [
    ("amidowanie", 1, 1),
    ("namca", 2, 1),
    ("czwartorzedowanie", 3, 0),
    ("sulfonowanie", 4, 0),
    ("utlenienie", 5, 0),
]
```

**Docelowo** (3 etapy post-MVP, sulfonowanie/utlenienie/standaryzacja):

```python
_K7_STAGES = [
    ("sulfonowanie", 1, 0),
    ("utlenienie", 2, 0),
    ("standaryzacja", 3, 0),
]
```

### 2. Usunięcie seed-u GLOL

Blok iterujący `_GLOL_PRODUCTS` / `_GLOL_STAGES` z INSERT-ami (ok. linie 394-399) — **usunięty w całości**. Komentarz w kodzie już stwierdza, że produkty GLOL "are meant to stay simple" (tylko `analiza_koncowa`, brak procesowych etapów).

Stałe `_GLOL_PRODUCTS` i `_GLOL_STAGES` (o ile są lokalne dla seed-u i nieużywane gdzie indziej) idą do usunięcia razem z blokiem.

### 3. Usunięcie marker-check-u

Dzisiejszy warunek:

```python
if 'mvp_pipeline_cleanup_v1' not in _migrations:
    # ... seed 5-stage pipeline ...
```

Staje się zbędny po zmianie 1+2 — seed jest teraz idempotentnie-post-MVP. Warunek sprawdzający marker **usuwamy**, zostawiamy sam `INSERT OR IGNORE`. Efekt: jeden mniej guard, prostszy flow.

## Weryfikacja

1. `pytest tests/test_etapy.py tests/test_parametry_registry.py -v` — **wszystkie 7 failków zielone**.
2. `pytest tests/` — brak nowych regresji; liczba passed ≥ 606, failed = 0 (oprócz tego co już było skipped).
3. `pytest tests/test_mvp_pipeline_cleanup.py -v` — nadal zielone. Skrypt cleanup jest idempotentny — wywołany na DB z samym post-MVP seed-em nic nie zmienia (DELETE-e na etap-ach spoza MVP trafiają w pustą listę).
4. Smoke test prod-state: open `data/batch_db.sqlite` w DB browser, sprawdzić że w `produkt_etapy` dla K7 są dokładnie 3 wiersze (sulfonowanie/utlenienie/standaryzacja). **Oczekiwane: już jest tak** (migracja była wykonana).

## Ryzyka

- **Jakaś część kodu zakłada, że świeży init ma amidowanie/namca?** — Risk niski. MVP cleanup był 2 tygodnie temu, testy od tego czasu jadą na tym samym seed-zie. Pełna suita testów (606 passed) to pokryje. Jeśli jakiś test zacznie failować po zmianie, diagnozujemy i poprawiamy.
- **Stare prod DB pre-migracji** — gdyby istniała instancja z pre-MVP K7 (5-etapowym), nowy init nie wstawi amidowanie/namca/czwartorzedowanie (bo ich nie ma w `_K7_STAGES`), ale też nie usunie istniejących pre-MVP wierszy. Jeśli ta instancja istnieje — musi i tak uruchomić `scripts/mvp_pipeline_cleanup.py`, żeby dojść do post-MVP. To normalny flow. Nie regresujemy.

## Out of scope

- Refaktoring / usunięcie `scripts/mvp_pipeline_cleanup.py` — zostaje jako historyczne narzędzie czyszczące dla pre-MVP instancji.
- Usunięcie markera `mvp_pipeline_cleanup_v1` z prod `_migrations` — nietknięte (telemetria historyczna).
- Dodatkowe testy dla prod-state (cleanup script idempotency) — już istnieją w `test_mvp_pipeline_cleanup.py`.

## Kryteria akceptacji

- 7 failujących testów jest zielone.
- 606+ pozostałych testów nadal zielone.
- `git diff` jest mały — jeden plik (`mbr/models.py`), kilkanaście linii usuniętych/zmodyfikowanych.
