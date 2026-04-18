# Fix 7 failing etapy tests — align in-memory seed with MVP cleanup

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zmienić seed `produkt_etapy` w `init_mbr_tables` tak, żeby odpowiadał stanowi post-MVP cleanup — 3 etapy dla Chegina_K7, brak workflow dla produktów GLOL.

**Architecture:** Jedna zmiana w `mbr/models.py` (linie 372-399): zastąpić `_K7_STAGES` trzy-etapowym zestawem (sulfonowanie/utlenienie/standaryzacja), usunąć blok seed GLOL, usunąć warunek marker-check (po zmianie jest zbędny).

**Tech Stack:** Python 3 · sqlite3 · pytest.

---

## File Structure

### Modyfikowane

- `mbr/models.py:372-399` — fragment seedujący `produkt_etapy` w `init_mbr_tables`.

### Nietykane (explicite)

- `scripts/mvp_pipeline_cleanup.py` — historyczne narzędzie do czyszczenia pre-MVP instancji, zostawiamy.
- `tests/test_etapy.py`, `tests/test_parametry_registry.py` — testy asertują post-MVP stan i po fixie przechodzą BEZ ich modyfikacji.
- `tests/test_mvp_pipeline_cleanup.py` — nadal zielony po fixie (skrypt cleanup jest idempotentny).

---

## Task 1: Baseline — potwierdzić 7 failujących testów

**Files:** (brak zmian)

- [ ] **Step 1: Run the failing tests**

Run: `pytest tests/test_etapy.py tests/test_parametry_registry.py -v --no-header`
Expected:
- FAILED `tests/test_etapy.py::test_get_process_stages_k7_returns_3`
- FAILED `tests/test_etapy.py::test_get_process_stages_glol_returns_empty_after_mvp`
- FAILED `tests/test_etapy.py::test_get_process_stages_k40gl_empty_after_mvp`
- FAILED `tests/test_etapy.py::test_init_etapy_status_non_parallel_stages_start_as_pending`
- FAILED `tests/test_etapy.py::test_init_etapy_status_glol_creates_no_stages_after_mvp`
- FAILED `tests/test_parametry_registry.py::test_etapy_config_k7`
- FAILED `tests/test_parametry_registry.py::test_etapy_config_glol_empty_after_mvp`

Wszystkie 7 MUSZĄ być czerwone przed zmianą. Jeśli któryś już jest zielony — STOP i wyjaśnij (coś jest nie tak z assumptions).

---

## Task 2: Zmień seed w `init_mbr_tables` na post-MVP

**Files:**
- Modify: `mbr/models.py:372-399`

- [ ] **Step 1: Zamień cały blok seedowania `produkt_etapy`**

Obecny blok (linie 372-399):

```python
    # Seed produkt_etapy for K7 + GLOL products — skipped if MVP pipeline
    # cleanup has been applied (marker `mvp_pipeline_cleanup_v1` in _migrations).
    # Post-MVP, produkt_etapy is managed by the migration + admin UI only;
    # hardcoded seeding here would resurrect the old multi-stage workflow for
    # products meant to stay simple.
    try:
        mvp_applied = db.execute(
            "SELECT 1 FROM _migrations WHERE name='mvp_pipeline_cleanup_v1'"
        ).fetchone() is not None
    except Exception:
        mvp_applied = False  # _migrations table missing → fresh DB, seed freely

    if not mvp_applied:
        _K7_PRODUCTS = ["Chegina_K7", "Chegina_K40GL"]
        _K7_STAGES = [("amidowanie", 1, 1), ("namca", 2, 1), ("czwartorzedowanie", 3, 0),
                      ("sulfonowanie", 4, 0), ("utlenienie", 5, 0)]
        for prod in _K7_PRODUCTS:
            for etap, kolej, rown in _K7_STAGES:
                db.execute("INSERT OR IGNORE INTO produkt_etapy (produkt, etap_kod, kolejnosc, rownolegle) VALUES (?,?,?,?)",
                           (prod, etap, kolej, rown))

        _GLOL_PRODUCTS = ["Chegina_K40GLO", "Chegina_K40GLOL", "Chegina_K40GLOS",
                          "Chegina_K40GLOL_HQ", "Chegina_K40GLN", "Chegina_GLOL40"]
        _GLOL_STAGES = _K7_STAGES + [("rozjasnianie", 6, 0)]
        for prod in _GLOL_PRODUCTS:
            for etap, kolej, rown in _GLOL_STAGES:
                db.execute("INSERT OR IGNORE INTO produkt_etapy (produkt, etap_kod, kolejnosc, rownolegle) VALUES (?,?,?,?)",
                           (prod, etap, kolej, rown))
```

Zastąp docelowym (post-MVP):

```python
    # Seed produkt_etapy for Chegina_K7 (post-MVP: 3 process stages).
    # MVP cleanup (2026-04-16, spec 2026-04-16-mvp-pipeline-cleanup-design.md)
    # narrowed K7 szarża workflow to sulfonowanie → utlenienie → standaryzacja
    # and removed workflow entirely for GLOL products (only analiza_koncowa).
    # Seed is idempotent (INSERT OR IGNORE) — won't disturb existing prod rows.
    _K7_STAGES = [
        ("sulfonowanie", 1, 0),
        ("utlenienie", 2, 0),
        ("standaryzacja", 3, 0),
    ]
    for etap, kolej, rown in _K7_STAGES:
        db.execute(
            "INSERT OR IGNORE INTO produkt_etapy (produkt, etap_kod, kolejnosc, rownolegle) "
            "VALUES (?, ?, ?, ?)",
            ("Chegina_K7", etap, kolej, rown),
        )
```

Zmiany:
1. Usunięty marker-check (`_migrations` SELECT) — niepotrzebny po tym, że seed ≡ post-MVP.
2. `_K7_STAGES` trzy-etapowy (sulfonowanie/utlenienie/standaryzacja) zamiast pięciu pre-MVP.
3. `_K7_PRODUCTS` zawiera tylko `Chegina_K7` (bez `Chegina_K40GL` — ten należy do MVP-no-workflow tak jak GLOL). Inline jako jedna pętla dla jednego produktu.
4. Blok `_GLOL_PRODUCTS` / `_GLOL_STAGES` — usunięty.
5. Komentarz uzupełniony o referencję do spec-u MVP cleanup.

- [ ] **Step 2: Run 7 formerly-failing testów**

Run: `pytest tests/test_etapy.py::test_get_process_stages_k7_returns_3 tests/test_etapy.py::test_get_process_stages_glol_returns_empty_after_mvp tests/test_etapy.py::test_get_process_stages_k40gl_empty_after_mvp tests/test_etapy.py::test_init_etapy_status_non_parallel_stages_start_as_pending tests/test_etapy.py::test_init_etapy_status_glol_creates_no_stages_after_mvp tests/test_parametry_registry.py::test_etapy_config_k7 tests/test_parametry_registry.py::test_etapy_config_glol_empty_after_mvp -v --no-header`
Expected: **7 passed, 0 failed.**

- [ ] **Step 3: Run pełna suita — sprawdź brak regresji**

Run: `pytest -q 2>&1 | tail -3`
Expected:
- Liczba `passed` = 613 (606 + 7 naprawionych) lub wyższa.
- `0 failed`.
- `skipped` ≤ 23 (pozostaje nie-zmienione lub mniej).

Jeśli jakiś inny test zacznie failować po zmianie — STOP i diagnozuj. To nie może się stać zgodnie ze spec-em ("Risk niski" — ale jeśli się stanie, jest to istotne odkrycie).

- [ ] **Step 4: Run test MVP cleanup scriptu osobno (weryfikacja idempotentności)**

Run: `pytest tests/test_mvp_pipeline_cleanup.py -v --no-header 2>&1 | tail -20`
Expected: wszystkie testy w tym pliku passed. Skrypt cleanup działający na DB z nowym (już post-MVP) seed-em nie crashuje i jest no-op na K7 (brak amidowanie/namca/czwartorzedowanie do usunięcia) + no-op na GLOL (już brak wierszy do usunięcia).

- [ ] **Step 5: Commit**

```bash
git add mbr/models.py
git commit -m "$(cat <<'EOF'
fix(models): align init_mbr_tables seed with MVP pipeline cleanup

init_mbr_tables still seeded pre-MVP 5-stage pipeline for K7 + GLOL
products (amidowanie/namca/czwartorzedowanie/sulfonowanie/utlenienie),
gated by a marker check that is absent from in-memory test DBs. Tests
asserting post-MVP state (K7 has 3 stages: sulfonowanie/utlenienie/
standaryzacja; GLOL has no workflow) were failing as a result.

Seed is now unconditionally post-MVP — matches the MVP cleanup script
end state. Existing prod rows unaffected (INSERT OR IGNORE), and the
cleanup script remains idempotent for any legacy pre-MVP instances.

Fixes 7 tests in test_etapy.py and test_parametry_registry.py.
EOF
)"
```

---

## Self-review (wykonane)

**Spec coverage:**

- Sekcja spec-u "Rozwiązanie → 1. `_K7_STAGES` → 3 etapy post-MVP" → Task 2 Step 1 (zmiana listy `_K7_STAGES`).
- Sekcja spec-u "Rozwiązanie → 2. Usunięcie seed-u GLOL" → Task 2 Step 1 (usunięty blok).
- Sekcja spec-u "Rozwiązanie → 3. Usunięcie marker-check-u" → Task 2 Step 1 (usunięty `try/except` + `if not mvp_applied`).
- Sekcja spec-u "Weryfikacja punkt 1" (7 testów zielone) → Task 2 Step 2.
- Sekcja spec-u "Weryfikacja punkt 2" (brak regresji) → Task 2 Step 3.
- Sekcja spec-u "Weryfikacja punkt 3" (MVP cleanup idempotent) → Task 2 Step 4.
- Sekcja spec-u "Weryfikacja punkt 4" (smoke test prod DB) — POZA tym planem implementacyjnym. Plan kończy się zmianą kodu + testami. Weryfikacja prod odbywa się przy deploy-u (`auto-deploy.service` rolluje zmianę, operator sprawdza prod).

Jeden drobny punkt — spec wspominał w Rozwiązaniu "Stałe `_GLOL_PRODUCTS` i `_GLOL_STAGES` (o ile są lokalne dla seed-u i nieużywane gdzie indziej) idą do usunięcia razem z blokiem" — w tym pliku te stałe są zdefiniowane LOKALNIE w funkcji (widać w Read'zie), nie globalne. Task 2 Step 1 usuwa je przy okazji usuwania bloku. OK.

**Placeholder scan:** Brak TBD/TODO. Każdy step ma pełny kod lub komendę z expected output. Commit message ma konkretną treść.

**Type consistency:** N/A — to pojedyncza zmiana wewnątrz istniejącej funkcji, bez nowych typów/API.

Plan jest minimalny i kompletny.

---

## Task 3: Baseline sanity check dla cert-editor branch

**Files:** (brak zmian)

- [ ] **Step 1: Po zielonych testach — confirm że worktree jest gotowy do dalszej pracy**

Run: `git log --oneline -3`
Expected:
- HEAD: `fix(models): align init_mbr_tables seed with MVP pipeline cleanup`
- parent: `docs(spec): fix 7 stale etapy tests by aligning seed with MVP cleanup`
- grandparent: `docs(plan): cert editor production-ready implementation plan`

Run: `git status`
Expected: `nothing to commit, working tree clean`.

Run: `pytest -q 2>&1 | tail -2`
Expected: `613 passed, 23 skipped` (lub wyżej) w kilkudziesięciu sekundach.

- [ ] **Step 2: Brak dodatkowego commit-a**

Ten task jest weryfikacją stanu — nic się nie commitujue.

---

Koniec planu. Po Task 3 baseline jest czysty i można ruszać z implementacją cert-editora wg `docs/superpowers/plans/2026-04-18-cert-editor-production-ready.md`.
