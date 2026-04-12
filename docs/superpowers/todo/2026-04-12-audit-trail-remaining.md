# TODO: Audit Trail — Remaining Phases (5+6+7)

**Data:** 2026-04-12
**Stan:** Phase 1-4 deployed na produkcji. 342 testy, 0 failów.

Poniżej pełna lista co zostało do zrobienia. Blokerów brak — centralizacje (parametry, produkty, cert-db-ssot) już wylądowały w main. Można robić w dowolnym momencie.

---

## Phase 5+6 — Instrumentacja pozostałych blueprintów

Wzorzec identyczny jak Phase 3/4: `log_event()` z explicit actors w route, model helpers refactored (remove internal commit), single `db.commit()` atomicznie.

### Priorytet A — wysoka wartość (~17 routes)

**technolog (MBR templates) — `mbr/technolog/routes.py`:**
- [ ] `POST /technolog/mbr/<id>` (mbr_edit) → `mbr.template.updated` z diff
- [ ] `POST /technolog/mbr/<id>/activate` (mbr_activate) → `mbr.template.updated` (status change)
- [ ] `POST /technolog/mbr/<id>/clone` (mbr_clone) → `mbr.template.created`

**parametry (param + produkt CRUD) — `mbr/parametry/routes.py`:**
- [ ] `POST /api/parametry` → `parametr.created`
- [ ] `PUT /api/parametry/<id>` → `parametr.updated` z diff
- [ ] `POST /api/produkty` → `produkt.created`
- [ ] `PUT /api/produkty/<id>` → `produkt.updated` z diff
- [ ] `DELETE /api/produkty/<id>` → `produkt.deleted` z snapshot

**certs — `mbr/certs/routes.py`:**
- [ ] `POST /api/cert/generate` → `cert.generated` (payload: ścieżka PDF, szablon, wariant)
- [ ] `DELETE /api/cert/<id>` → `cert.cancelled`
- [ ] `PUT /api/cert/config/product/<key>` → `cert.config.updated` z diff
- [ ] `POST /api/cert/config/product` → `cert.config.updated` (nowy produkt w config)
- [ ] `DELETE /api/cert/config/product/<key>` → `cert.config.updated` (usunięcie)

**registry — `mbr/registry/routes.py`:**
- [ ] `POST /api/registry/<id>/cancel` → `admin.batch.cancelled`

**admin — `mbr/admin/routes.py`:**
- [ ] `POST /api/admin/backup` → `admin.backup.created`
- [ ] `POST /api/settings` → `admin.settings.changed`
- [ ] `DELETE /api/admin/backup/<name>` → `admin.backup.deleted` (brak w spec EVENT_* — dodać stałą albo użyć admin.settings.changed)

### Priorytet B — średnia wartość (~8 routes)

**zbiorniki — `mbr/zbiorniki/routes.py`:**
- [ ] `POST /api/zbiorniki` → `zbiornik.created`
- [ ] `PUT /api/zbiorniki/<id>` → `zbiornik.updated` z diff
- [ ] (opcjonalnie) `POST /api/zbiornik-szarze` → `zbiornik.batch.linked` (brak w spec — dodać jeśli potrzebne)

**paliwo — `mbr/paliwo/routes.py`:**
- [ ] `POST /api/paliwo/osoby` → `paliwo.osoba.created`
- [ ] `PUT /api/paliwo/osoby/<id>` → `paliwo.osoba.updated`
- [ ] `DELETE /api/paliwo/osoby/<id>` → `paliwo.osoba.deleted`
- [ ] `POST /api/paliwo/generuj` → `paliwo.wniosek.created` (generowanie wniosku)

**registry (metody) — `mbr/registry/routes.py`:**
- [ ] `PUT /api/metody-miareczkowe/<id>/stezenia` → `metoda.updated`

### Priorytet C — niska wartość, rare config changes (~15 routes)

**parametry bindings — `mbr/parametry/routes.py`:**
- [ ] `POST /api/parametry/etapy` → parametr binding created
- [ ] `PUT /api/parametry/etapy/<id>` → parametr binding updated
- [ ] `DELETE /api/parametry/etapy/<id>` → parametr binding deleted
- [ ] `POST /api/parametry/etapy/reorder` → parametr bindings reordered
- [ ] `POST /api/parametry/cert` → cert binding created
- [ ] `PUT /api/parametry/cert/<id>` → cert binding updated
- [ ] `DELETE /api/parametry/cert/<id>` → cert binding deleted
- [ ] `POST /api/parametry/cert/reorder` → cert bindings reordered
- [ ] `POST /api/parametry/rebuild-mbr` → system action (rebuild MBR from params)
- [ ] `PUT /api/parametry/sa-bias` → SA bias updated

**zbiorniki admin — `mbr/zbiorniki/routes.py`:**
- [ ] `POST /api/substraty` → substrat created
- [ ] `PUT /api/substraty/<id>` → substrat updated
- [ ] `PUT /api/substraty/<id>/produkty` → substrat products updated
- [ ] `PUT /api/normy/<id>` → norma updated
- [ ] `PUT /api/parametry/admin/<id>` → admin param updated

### Dodatkowe z Phase 2 (odłożone):
- [ ] **Cert detail view** — include `_audit_history_section.html` partial w widoku świadectwa (Phase 2 Sub-PR 2.4 pomknięty bo nie istniał cert detail template — teraz po cert-db-ssot pewnie istnieje)

---

## Phase 7 — Cleanup + CI guard

- [ ] **Sweep test** — parametryzowany test `[(url, method, payload)]` dla każdego write endpoint. Sprawdza że udany request zostawia ≥1 wpis w `audit_log`. Nowy endpoint dodany bez `log_event` → test padnie → developer musi dodać.
- [ ] **Drop `audit_log_v1`** — stara tabela z Phase 1 migracji. Rollback safety skończone (3+ tygodnie na produkcji). `ALTER TABLE DROP` w nowym migration script.
- [ ] **Drop `ebr_uwagi_history`** — stara tabela skonsolidowana do `audit_log` w Phase 4. Rollback safety skończone. Usunąć też `CREATE TABLE IF NOT EXISTS ebr_uwagi_history` z `init_mbr_tables()`.
- [ ] **Update `CLAUDE.md`** — dodać sekcję „Audit trail" opisującą:
  - Jak dodać `log_event()` do nowego endpointa (wzorzec explicit actors + single commit)
  - Stałe `EVENT_*` w `mbr/shared/audit.py` — SSOT
  - Panel admina `/admin/audit`
  - `ShiftRequiredError` dla roli `laborant`
  - Archiwizacja > 2 lata
  - Per-record history w widokach EBR/MBR (cert TBD)
- [ ] **Usunąć quarantined tests** — 16 skipped testów z `docs/superpowers/todo/2026-04-11-quarantined-tests.md`. Decyzja domenowa (pipeline K40GLO 5 vs 6 etapów) + workflow test integration fixture.
- [ ] **Usunąć auto-deploy hooks** dla jednorazowych migracji — `migrate_audit_log_v2.py`, `backfill_audit_legacy_to_ebr.py`, `migrate_uwagi_to_audit.py` z `deploy/auto-deploy.sh` (idempotent, ale niepotrzebne obciążenie po miesiącu stabilności). Skrypty zostawiamy w repo ale auto-deploy przestaje je wywoływać.

---

## Stan na 2026-04-12

### Co jest deployed:

| Phase | Co | Tests |
|---|---|---|
| 1 | Infrastruktura: schema, helper `mbr/shared/audit.py`, migration, Flask wiring | 34 |
| 2 | Panel admina `/admin/audit`, CSV, archiwizacja, per-record history EBR/MBR | 41 |
| 3 | Auth (login/logout/password) + workers CRUD + shift enforcement | 23 |
| 4 | EBR laborant (batch lifecycle, wyniki, etapy, uwagi consolidated) | 17 |
| **Total** | **342 passed, 16 skipped, 0 failed** | |

### Co loguje się w audit trail:

| Kategoria | Event_types | Phase |
|---|---|---|
| Auth | auth.login (ok/error), auth.logout, auth.password_changed | 3 |
| Workers | worker.created/updated/deleted, shift.changed | 3 |
| Batch lifecycle | ebr.batch.created/status_changed/updated | 4 |
| Wyniki | ebr.wynik.saved/updated | 4 |
| Etapy | ebr.stage.event_added/updated | 4 |
| Uwagi | ebr.uwagi.updated | 4 |
| System | system.audit.archived | 2 |

### Co NIE loguje się jeszcze:

| Kategoria | Event_types | Phase |
|---|---|---|
| MBR templates | mbr.template.created/updated/deleted | 5 |
| Parametry | parametr.created/updated/deleted | 5 |
| Produkty | produkt.created/updated/deleted | 5 |
| Metody | metoda.created/updated/deleted | 5 |
| Zbiorniki | zbiornik.created/updated/deleted | 5 |
| Etap catalog | etap.catalog.created/updated/deleted | 5 |
| Registry | registry.entry.created/updated/deleted | 5 |
| Certs | cert.generated/cancelled/config.updated | 6 |
| Paliwo | paliwo.wniosek/osoba CRUD | 6 |
| Admin | admin.backup/batch.cancelled/settings | 6 |

### Kluczowe pliki audit trail:

| Plik | Rola |
|---|---|
| `mbr/shared/audit.py` | Helper module: stałe EVENT_*, log_event(), actors_*, diff_fields(), query_audit_log(), archive_old_entries() |
| `mbr/app.py` | Flask wiring: g.audit_request_id per request, ShiftRequiredError → 400 |
| `mbr/admin/audit_routes.py` | Panel `/admin/audit` + CSV + archiwizacja |
| `mbr/templates/admin/audit.html` | Panel template |
| `mbr/templates/_audit_history_section.html` | Reusable per-record history partial |
| `mbr/laborant/routes.py::_resolve_actor_label()` | Actor resolution helper + shift enforcement |
| `scripts/migrate_audit_log_v2.py` | Schema migration (legacy → new) |
| `scripts/backfill_audit_legacy_to_ebr.py` | Legacy entity backfill |
| `scripts/migrate_uwagi_to_audit.py` | Uwagi consolidation |
