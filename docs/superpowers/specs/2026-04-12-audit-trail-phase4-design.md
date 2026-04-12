# Audit Trail — Phase 4 (EBR Laborant Integration) — Design

**Data:** 2026-04-12
**Status:** Draft → do recenzji
**Cel:** Instrumentacja wszystkich EBR write paths — codzienne operacje laboranta (wpisy wyników, etapy, uwagi, lifecycle szarży) logują się w audit trail. Plus konsolidacja `ebr_uwagi_history` → single source of truth w `audit_log`.
**Parent spec:** `docs/superpowers/specs/2026-04-11-audit-trail-design.md`
**Prerequisites:** Phase 1 (infra) + Phase 2 (panel) + Phase 3 (auth + workers + shift enforcement)

## Kontekst

Phase 3 wdrożyła instrumentację auth (login/logout/password) + workers (CRUD + shift) + shift fallback removal. Po Phase 3 panel admina pokazuje meta-akcje (kto się zalogował, kto zmienił zmianę), ale **zero z codziennej pracy laboranta** — wpisywanie wyników, zatwierdzanie etapów, edycja uwag, zamykanie szarży. Te najczęstsze operacje nie generują jeszcze wpisów.

Phase 4 zamyka tę lukę: **każda mutacja na EBR produkuje audit entry.**

## Zakres

### Wewnątrz Phase 4 — 4 sub-PR-ki

**Sub-PR 4.1 — Batch lifecycle (3 events, 3 call-sites):**
- `ebr.batch.created` — `POST /laborant/szarze/new` → `create_ebr`
- `ebr.batch.status_changed` — `POST /laborant/ebr/<id>/complete` → `complete_ebr`, payload `{old_status, new_status, przepompowanie_json}`
- `ebr.batch.updated` — `POST /api/ebr/<id>/golden`, diff `[{pole:'is_golden', stara, nowa}]`

**Sub-PR 4.2 — Wyniki (2 events, 2 call-sites):**
- `ebr.wynik.saved` (INSERT nowego wyniku) / `ebr.wynik.updated` (UPDATE istniejącego) — `POST /laborant/ebr/<id>/save` → `save_wyniki`. **Jeden wpis per submit, diff = lista wszystkich zmian.** Insert = `saved`, update = `updated`. Mix w jednym submit → 2 wpisy (jeden per typ) z tym samym `request_id`.
- `ebr.wynik.updated` — `POST /api/ebr/<id>/samples` (edycja samples_json)
- **Zastępuje neutralized call-site** w `mbr/laborant/models.py:481`

**Sub-PR 4.3 — Etapy (3 events, 5 call-sites):**
- `ebr.stage.event_added` — save_etap_analizy, add_korekta, zatwierdz_etap, skip_etap. Discriminator w `payload.type`: `'analizy'` / `'korekta'` / `'zatwierdz'` / `'skip'`
- `ebr.stage.event_updated` — confirm_korekta
- **Zastępuje neutralized call-site** w `mbr/etapy/models.py:45`

**Sub-PR 4.4 — Uwagi konsolidacja (1 event + migration):**
- `ebr.uwagi.updated` — `save_uwagi` pisze do `audit_log` zamiast `ebr_uwagi_history`
- `get_uwagi` czyta history z `audit_log` (zwraca identyczną strukturę dict jak dotąd)
- Migration script `scripts/migrate_uwagi_to_audit.py` (one-shot idempotent)
- Hook w `auto-deploy.sh`
- `ebr_uwagi_history` table zostawiamy do Phase 7 (rollback safety)

### Out of scope

- Phase 5: MBR templates + rejestry (czeka na centralizacje)
- Phase 6: Certs + paliwo + admin actions
- Phase 7: sweep test + drop `audit_log_v1` + drop `ebr_uwagi_history`
- `ebr.wynik.deleted` — nie istnieje endpoint usuwania wyników (jeśli powstanie, dorzuci się wtedy)

## Decyzje brainstormingu

| # | Pytanie | Wybór | Powód |
|---|---|---|---|
| Q1 | Scope Phase 4 | **Pełna** — wszystkie 14 instrumentacji | Spec zaplanował, Phase 5/6 zablokowane, robimy Phase 4 w całości |
| Q2 | Granularność diff dla wyników | **Jeden wpis per submit** z listą zmian | Mniejsza objętość logu, czytelność panelu, insert=saved/update=updated |
| Q3 | Uwagi konsolidacja | **B — audit_log jako SSOT**, drop `ebr_uwagi_history` | Jedno źródło prawdy, brak duplikacji |
| — | Stage events naming | **3 event_type + `payload.type` discriminator** | 3 stałe z Phase 1 (event_added/updated/deleted) + rozróżnianie w payload |
| — | Drop `ebr_uwagi_history` timing | **Phase 7** (rollback safety) | Jeśli migracja ma problem, mamy oryginalne dane |
| — | Model helpers atomicity | **B — refactor (remove internal commit)** | Każdy helper ma 1 callera; caller commituje atomicznie z log_event |
| — | `przepompowanie_json` eventy | **Brak osobnych** — wchodzą w payload `ebr.batch.status_changed` | Nie ma osobnego endpointa, ustawiane wewnątrz complete_ebr |

## Architektura: model refactor

7 model helpers tracą wewnętrzne `db.commit()`. Route commituje raz po `log_event`. Taki sam pattern jak `change_password` w Phase 3 (commit `1d6a7e6`).

| Funkcja | Plik | Caller route |
|---|---|---|
| `create_ebr` | `mbr/laborant/models.py` | `szarze_new` |
| `save_wyniki` | `mbr/laborant/models.py` | `save_entry` |
| `complete_ebr` | `mbr/laborant/models.py` | `complete_entry` |
| `save_uwagi` | `mbr/laborant/models.py` | `api_put_uwagi`, `api_delete_uwagi` |
| `save_etap_analizy` | `mbr/etapy/models.py` | `api_etapy_analizy_save` |
| `add_korekta` | `mbr/etapy/models.py` | `api_korekty_add` |
| `confirm_korekta` | `mbr/etapy/models.py` | `api_korekty_confirm` |
| `zatwierdz_etap` | `mbr/etapy/models.py` | `api_etapy_zatwierdz` |
| `skip_etap` | `mbr/etapy/models.py` | `api_etapy_skip` |

Każdy helper ma **dokładnie 1 callera** — zweryfikowane grep'em. Brak cross-blueprint usage. Refactor bezpieczny.

## Architektura: uwagi konsolidacja

### Migration `scripts/migrate_uwagi_to_audit.py`

Existing `ebr_uwagi_history` schema: `id, ebr_id, tekst (=old value before change), action (create/update/delete), autor, dt`.

Each history row maps to:
```
audit_log:
  dt = history.dt
  event_type = 'ebr.uwagi.updated'
  entity_type = 'ebr'
  entity_id = history.ebr_id
  entity_label = batch_id from ebr_batches JOIN (or NULL if batch missing)
  payload_json = {"action": history.action, "tekst": history.tekst}
  result = 'ok'

audit_log_actors:
  actor_login = history.autor
  actor_rola = 'laborant' (hardcoded — same convention as backfill_audit_legacy_to_ebr.py)
  worker_id = resolve via inicjaly/nickname from workers table (NULL if unresolved)
```

Idempotency guard: `WHERE NOT EXISTS (SELECT 1 FROM audit_log WHERE event_type='ebr.uwagi.updated' AND entity_id=history.ebr_id AND dt=history.dt)`.

### Refactored `save_uwagi` flow

Before (current):
1. INSERT into `ebr_uwagi_history`
2. UPDATE `ebr_batches.uwagi_koncowe`
3. `db.commit()`

After (Phase 4):
1. UPDATE `ebr_batches.uwagi_koncowe`
2. `log_event(EVENT_EBR_UWAGI_UPDATED, entity_type='ebr', entity_id=ebr_id, payload={action, tekst: old})`
3. (caller route does `db.commit()`)

### Refactored `get_uwagi` flow

Before: `SELECT ... FROM ebr_uwagi_history WHERE ebr_id=? ORDER BY dt DESC`

After:
```python
historia_rows = db.execute("""
    SELECT al.dt, al.payload_json,
           (SELECT GROUP_CONCAT(ala.actor_login) FROM audit_log_actors ala WHERE ala.audit_id = al.id) as autor
    FROM audit_log al
    WHERE al.entity_type = 'ebr' AND al.entity_id = ? AND al.event_type = 'ebr.uwagi.updated'
    ORDER BY al.dt DESC, al.id DESC
""", (ebr_id,)).fetchall()
```

Parse `payload_json` to extract `action` and `tekst`. Build the same dict shape `{tekst, dt, autor, historia: [{tekst, action, autor, dt}]}` for backward compat with existing UI code.

## Sub-PR phasing

### Sub-PR 4.1 — Batch lifecycle (~60 min)
- Refactor `create_ebr`, `complete_ebr` (remove internal commit)
- Instrument `szarze_new`, `complete_entry`, `toggle_golden` routes
- 6 tests in `tests/test_audit_phase4_lifecycle.py`
- **Per spec**: explicit actors (same Phase 3 pattern — avoid ShiftRequiredError on batch creation when laborant is the one creating)

### Sub-PR 4.2 — Wyniki (~60 min)
- Refactor `save_wyniki` (remove internal commit)
- Instrument `save_entry` route — 1 wpis per submit, diff = all changes, insert=saved/update=updated
- Remove Phase 1 neutralized comment at `mbr/laborant/models.py:481`
- Instrument `save_samples` route
- 6 tests in `tests/test_audit_phase4_wyniki.py`

### Sub-PR 4.3 — Etapy (~75 min)
- Refactor `save_etap_analizy`, `add_korekta`, `confirm_korekta`, `zatwierdz_etap`, `skip_etap`
- Instrument 5 etapy routes
- Remove Phase 1 neutralized comment at `mbr/etapy/models.py:45`
- 7 tests in `tests/test_audit_phase4_etapy.py`

### Sub-PR 4.4 — Uwagi konsolidacja (~90 min)
- `scripts/migrate_uwagi_to_audit.py` + tests
- Refactor `save_uwagi` + `get_uwagi`
- `deploy/auto-deploy.sh` hook
- 6 tests in `tests/test_audit_phase4_uwagi.py` + `tests/test_migrate_uwagi_to_audit.py`
- **Rollback risk**: highest in Phase 4. Zostawiamy `ebr_uwagi_history` table do Phase 7.

**Total: ~5h pracy, ~25 testów, 4 sub-PR-ki.**

## Rollback per sub-PR

| Sub-PR | Blast radius przy rollback | Recovery |
|---|---|---|
| 4.1 | `ebr.batch.*` eventy znikają. Lifecycle szarży nadal działa. | `git revert` |
| 4.2 | `ebr.wynik.*` eventy znikają. Wpisy nadal działają. Re-introduce neutralized comment. | `git revert` |
| 4.3 | `ebr.stage.*` eventy znikają. Etapy nadal działają. | `git revert` |
| 4.4 | **Largest blast**: `save_uwagi`/`get_uwagi` crashują (read/write z audit_log). | `git revert` + ewentualny script restoring `ebr_uwagi_history` reads. Dlatego table zostaje do Phase 7. |

## Testy

25 nowych testów w 4+1 plikach:
- `tests/test_audit_phase4_lifecycle.py` — 6 (batch created, status_changed, golden_toggle, atomicity, zbiorniki payload, role)
- `tests/test_audit_phase4_wyniki.py` — 6 (single entry per submit, diff format, saved vs updated, samples, atomicity)
- `tests/test_audit_phase4_etapy.py` — 7 (analizy, korekta add/confirm, zatwierdz, skip, atomicity, role protection)
- `tests/test_audit_phase4_uwagi.py` — 3 (save to audit, get from audit, same dict shape)
- `tests/test_migrate_uwagi_to_audit.py` — 3 (empty, backfill rows, idempotent)

## Decision log

| Decyzja | Wybór | Alternatywy odrzucone |
|---|---|---|
| Scope | Pełna Phase 4 (14 call-sites) | Subset wyniki-only — za mało wartości; minimum 1 save — za małe |
| Wynik granularność | 1 wpis per submit z listą zmian | 1 per parametr — 10× większy log; hybryda — niepotrzebna złożoność |
| Uwagi | Konsolidacja na audit_log (B) | Dual-log (A) — duplikacja; skip (C) — niespójność |
| Stage events | 3 typy + payload.type | Osobne event_types per action — fragmentacja taksonomii |
| Drop ebr_uwagi_history | Phase 7 | Phase 4 — za duże ryzyko rollback |
| Model atomicity | Refactor remove commit (B) | Inline SQL (A) — duplikacja; *_atomic helpers (C) — nadmiarowe |
| Przepompowanie | W payload status_changed | Osobne eventy — brak endpointu, sztuczny podział |
