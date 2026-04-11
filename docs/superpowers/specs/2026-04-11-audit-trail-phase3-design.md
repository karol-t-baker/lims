# Audit Trail — Phase 3 (Auth + Workers Integration + Shift Fallback Removal) — Design

**Data:** 2026-04-11
**Status:** Draft → do recenzji
**Cel:** Pierwsza prawdziwa integracja `log_event()` w blueprintach (auth + workers) plus enforcement „pusta zmiana blokuje zapis dla laboranta".
**Parent spec:** `docs/superpowers/specs/2026-04-11-audit-trail-design.md` (root)
**Prerequisites:** Phase 1 (infrastructure) + Phase 2 (admin panel) zmergowane do main, deployed na prod.

## Kontekst

Phase 1 dostarczyła infrastrukturę (`mbr/shared/audit.py`, schema, migrations). Phase 2 dostarczyła read-only UI (`/admin/audit` panel, CSV export, archiwizacja, per-record history). Po dwóch fazach **w bazie produkcyjnej istnieje 0 nowych `log_event()` calli z normalnego użycia aplikacji** — tylko zmigrowane legacy wpisy + ewentualne `system.audit.archived` z ręcznych archiwizacji.

Phase 3 zaczyna **prawdziwą integrację** od najstabilniejszych obszarów: auth (login/logout/password) i workers (CRUD + shift). Plus realizuje enforcement z głównego specu: rola `laborant` nie może wykonać żadnej akcji write bez potwierdzonej zmiany.

## Zakres

**Wewnątrz Phase 3:**

- ✅ `auth.login` (success + failure) — instrument `login()` w `mbr/auth/routes.py`
- ✅ `auth.logout` — instrument `logout()` przed `session.clear()`
- ✅ `auth.password_changed` — **nowy endpoint** `POST /api/users/<int:user_id>/password` (admin-only) + nowa funkcja modelu `change_password()` + log_event
- ✅ `worker.created/updated/deleted` — instrument 4 endpointów w `mbr/workers/routes.py`
- ✅ `shift.changed` — instrument `api_shift POST` (aktor = session user, NIE shift workers)
- ✅ **Shift fallback removal** — `_resolve_actor_label` raise `ShiftRequiredError` dla `rola='laborant'` na pustą zmianę
- ✅ Frontend: 4-5 JS handlerów laboranta dostają obsługę 400 `shift_required` → otwiera shift-modal

**Out of scope dla Phase 3:**

- Phase 4: EBR laborant integration (`ebr.batch.*`, `ebr.wynik.*`, `ebr.stage.*`, `ebr.uwagi.*`)
- Phase 5: MBR + rejestry (`mbr.template.*`, `parametr.*`, `metoda.*`, etc.)
- Phase 6: Certs + paliwo + admin
- Phase 7: Sweep test + drop `audit_log_v1`

## Decyzje brainstormingu

| # | Pytanie | Wybór | Powód |
|---|---|---|---|
| Q1 | Failed login policy | **Loguj wszystkie** | LIMS w zakładzie chemicznym, brak masy attempts; audit klienta wymaga; auto-archiwizacja > 2 lata zaopiekuje rozrostem |
| Q2 | `auth.password_changed` event | **Dodać podstawowy endpoint w Phase 3** | Daje feature przy okazji + rozgrzewa instrumentację (B z opcji) |
| Q3 | Shift fallback removal scope | **Pełny zakres — wszystkie laborant write paths** | Spec wymaga, bez tego cała legenda `actor_login='laborant'` wraca tylnymi drzwiami (A z opcji) |
| — | Frontend handler dla 400 shift_required | **Lokalne sprawdzenie w każdym JS handlerze laboranta** (B z opcji) | Najmniej inwazyjne, łatwo zorientować się czemu coś się dzieje |
| — | `auth.password_changed` payload | **Tylko `target_user_id` + `target_user_login`** | Nie logujemy żadnych metadanych hasła (długość, hash, etc.) |
| — | `worker.activated/deactivated` osobny event | **Nie — używamy `worker.updated` z `diff=[{pole:'aktywny'}]`** | Spec definiuje tylko 3 worker eventy, trzymamy się specu |

## Architektura

### Call sites

**`mbr/auth/routes.py` (3 events + nowy endpoint):**

| Endpoint | Event | Aktor | Notes |
|---|---|---|---|
| `POST /login` (success) | `auth.login` (result=ok) | session user (po set) | log_event po `session["user"] = ...`, przed redirect |
| `POST /login` (failure) | `auth.login` (result=error) | `worker_id=None, actor_login=<attempted_login>, actor_rola='unknown'` | log w gałęzi `error = ...` |
| `GET /logout` | `auth.logout` (result=ok) | session user (przed clear) | log_event przed `session.clear()` |
| `POST /api/users/<int:user_id>/password` (NEW) | `auth.password_changed` | session user (admin) | bcrypt hash, UPDATE mbr_users, log_event, payload `{target_user_id, target_user_login}` |

Nowy helper w `mbr/auth/models.py`:

```python
def change_password(db, user_id: int, new_password: str) -> dict:
    """Hash and update password for an existing user.
    Returns the user dict (without password_hash).
    Raises ValueError if user not found or password too short."""
```

Walidacja: `len(new_password) >= 6` (zgodnie z `create_user`).

**`mbr/workers/routes.py` (5 events na 5 endpointach):**

| Endpoint | Event | Diff / Payload | Aktor |
|---|---|---|---|
| `POST /api/shift` | `shift.changed` | `payload={old: [...], new: [...]}` | session user (NIE shift — bo zmiana właśnie się ustawia) |
| `POST /api/worker/<id>/profile` | `worker.updated` | `diff=[{pole, stara, nowa}]` dla nickname/avatar_icon/avatar_color (tylko zmienione) | session user |
| `POST /api/workers` (add) | `worker.created` | `payload={imie, nazwisko, inicjaly, nickname}` | session user |
| `POST /api/workers/<id>/toggle` | `worker.updated` | `diff=[{pole:'aktywny', stara: 0/1, nowa: 1/0}]` | session user |
| `DELETE /api/workers/<id>` | `worker.deleted` | `payload={<full row snapshot before delete>}` | session user |

**Co odkładamy:** `api_feedback POST` (feedback to nie audit-trail-relevant), `api_workers GET / api_workers_all GET` (read-only, no read-log per spec).

### Shift fallback removal

`mbr/laborant/routes.py::_resolve_actor_label` aktualnie ma fallback na `session["user"]["login"]` dla pustej zmiany dowolnej roli. Po zmianie, dla `rola='laborant'` raise `ShiftRequiredError`. Pozostałe role bez zmian.

```python
def _resolve_actor_label(db, override=None):
    if override and override.strip():
        return override.strip()
    shift_ids = session.get("shift_workers", []) or []
    if shift_ids:
        # ... join + return "AK, MW"
    rola = session.get("user", {}).get("rola")
    if rola == "laborant":
        from mbr.shared.audit import ShiftRequiredError
        raise ShiftRequiredError()
    return session["user"]["login"]  # fallback dla admin/technolog/laborant_kj/laborant_coa
```

Wszystkie call-site'y `_resolve_actor_label` (save_entry, save_uwagi, ewentualne inne) automatycznie dziedziczą nowe zachowanie.

Flask error handler dla `ShiftRequiredError` (dodany w Phase 1, `mbr/app.py`) zwraca:

```python
return jsonify({"error": "shift_required"}), 400
```

### Frontend handler

W każdym JS handlerze laboranta który robi write fetch (po `await fetch(...)` w `_uwagiSave`, w `save_entry` JS, w `_uwagiClear`, w complete-entry handler), dodajemy:

```javascript
if (resp.status === 400) {
  var err = await resp.json().catch(function() { return {}; });
  if (err.error === 'shift_required') {
    if (typeof openShiftModal === 'function') openShiftModal();
    return;  // abort the action
  }
  // ... existing error handling
}
```

`openShiftModal()` już istnieje w `base.html` z Phase 1.

Konkretne handlery do zmodyfikowania (lista bazuje na grep'ie call-site'ów `_resolve_actor_label`):
- `mbr/templates/laborant/_fast_entry_content.html` — `_uwagiSave`, `_uwagiClear`
- `mbr/templates/laborant/_fast_entry_content.html` — handler dla `save_entry` (POST `/laborant/ebr/<id>/save`)
- `mbr/templates/laborant/_fast_entry_content.html` — handler dla `complete_entry` (POST `/laborant/ebr/<id>/complete`) jeśli istnieje
- Ewentualnie inne write-side w `szarze_list.html`

## Sub-PR phasing

### Sub-PR 3.1 — Auth instrumentation + password change endpoint
- `mbr/auth/routes.py` instrument login/logout/new-password-route
- `mbr/auth/models.py` nowy `change_password()`
- `tests/test_audit_phase3_auth.py` 6 testów
- **Po wdrożeniu:** każde logowanie i wylogowanie loguje się. Admin może zmienić komuś hasło. **Pierwsze prawdziwe wpisy `auth.*` w bazie produkcyjnej.**
- **Czas:** ~60 min

### Sub-PR 3.2 — Workers instrumentation
- `mbr/workers/routes.py` instrument 5 endpointów
- `tests/test_audit_phase3_workers.py` 6 testów
- **Po wdrożeniu:** każda zmiana zmiany, każdy CRUD workera loguje się. Łącznie z auth: 6 typów eventów żywych w bazie.
- **Czas:** ~45 min

### Sub-PR 3.3 — Shift fallback removal + frontend handlers
- `mbr/laborant/routes.py::_resolve_actor_label` — raise ShiftRequiredError dla rola='laborant'
- 4-5 JS handlerów laboranta dostają obsługę 400 shift_required → otwiera shift-modal
- `tests/test_audit_phase3_shift_required.py` 4 testy
- **Po wdrożeniu:** **behaviour change na produkcji**. Laboranci muszą potwierdzić zmianę. Logi przestają mieć `actor_login='laborant'` i zaczynają mieć konkretne osoby (po Phase 4).
- **Czas:** ~60 min

**Total: ~3 godziny pracy, ~16 testów, 3 sub-PR-ki na branchu `audit/phase3`.**

## Plan rollback per sub-PR

| Sub-PR | Co psuje rollback | Recovery |
|---|---|---|
| 3.1 (auth) | Endpoint zmiany hasła znika. Login/logout nadal działa, audit wpisy z 3.1 zostają. | `git revert` |
| 3.2 (workers) | Workers CRUD nadal działa, audit wpisy zostają. | `git revert` |
| 3.3 (shift fallback) | **Behaviour change wraca** — laboranci znowu mogą pisać bez zmiany, fallback na login działa. Audit wpisy z laborant action mają mieszany format (część z nickname'ami, część z `actor_login='laborant'`). Niespójność, ale akceptowalna. | `git revert` |

## Testy

### Helper-level (1 modyfikacja)

1. `test_resolve_actor_label_laborant_empty_shift_raises` (modyfikacja istniejącego `test_resolve_actor_label_falls_back_to_login_when_no_shift`) — laborant + pusta zmiana → `pytest.raises(ShiftRequiredError)`. Pozostałe role nadal fallback na login.

### Auth (`tests/test_audit_phase3_auth.py`, 6 testów)

2. `test_login_success_logs_auth_login_ok` — POST /login z poprawnymi danymi → wpis `auth.login` `result='ok'`
3. `test_login_failure_logs_auth_login_error` — POST /login z złymi danymi → wpis `result='error'`, payload `{attempted_login}`, actor_login=attempted, actor_rola='unknown'
4. `test_login_failure_with_unknown_user_still_logs` — POST /login z loginem który nie istnieje → wpis (nie crash)
5. `test_logout_logs_auth_logout` — GET /logout → wpis przed czyszczeniem sesji
6. `test_change_password_logs_event` — POST /api/users/<id>/password jako admin → mbr_users zaktualizowane, wpis `auth.password_changed`, payload zawiera tylko target_user_id + target_user_login (NIE password)
7. `test_change_password_forbidden_for_non_admin` — laborant → 403, brak zmian w DB, brak audit wpisu

### Workers (`tests/test_audit_phase3_workers.py`, 6 testów)

8. `test_shift_changed_logs_event` — POST /api/shift z `worker_ids=[1,2]` → wpis `shift.changed`, payload `{old:[], new:[1,2]}`
9. `test_worker_created_logs_event` — POST /api/workers → wpis `worker.created`, entity_id = nowy worker.id
10. `test_worker_updated_profile_logs_event` — POST /api/worker/<id>/profile → wpis `worker.updated` z diff (zmienione pola)
11. `test_worker_toggled_logs_event` — POST /api/workers/<id>/toggle → wpis `worker.updated` z diff `[{pole:'aktywny', stara, nowa}]`
12. `test_worker_deleted_logs_event` — DELETE /api/workers/<id> → wpis `worker.deleted` z payload (snapshot przed delete)
13. `test_workers_routes_role_protected` — laborant POST /api/workers → 403, brak audit wpisu

### Shift fallback (`tests/test_audit_phase3_shift_required.py`, 4 testy)

14. `test_save_entry_laborant_empty_shift_returns_400` — POST /laborant/ebr/<id>/save jako laborant z pustą zmianą → HTTP 400 `{"error": "shift_required"}`, brak nowego wpisu w ebr_wyniki
15. `test_save_entry_laborant_with_shift_succeeds` — laborant z `session['shift_workers']=[1,2]` → 200 OK, wpis w ebr_wyniki
16. `test_save_uwagi_laborant_empty_shift_returns_400` — symmetric for uwagi
17. `test_save_entry_admin_empty_shift_succeeds` — admin/technolog z pustą zmianą → 200 OK (fallback na login)

**Total: ~16 nowych testów + 1 modyfikacja istniejącego.**

## Acceptance criteria

- [ ] Wszystkie 16 nowych testów zielone (+ zmodyfikowany istniejący)
- [ ] Pełna suite zielona (≈318 passed = 302 baseline + 16 new, 16 skipped, 0 failed)
- [ ] Każdy login/logout admin/laboranta/technologa produkuje wpis w `audit_log` z poprawnym aktorem
- [ ] Failed login produkuje wpis z `result='error'` i `actor_login` = wpisany login (nawet jeśli nie istnieje)
- [ ] Admin może zmienić hasło innemu userowi przez `POST /api/users/<id>/password` i widzi wpis `auth.password_changed` w `/admin/audit`
- [ ] Każda mutacja workera (add/edit/toggle/delete) i potwierdzenie zmiany loguje się
- [ ] Laborant z pustą zmianą próbujący wpisać wynik widzi shift modal i nie może zapisać
- [ ] Laborant z potwierdzoną zmianą wpisuje wyniki normalnie (audit wpis dopiero w Phase 4)
- [ ] Admin/technolog/laborant_kj/laborant_coa nie są dotknięci shift removal
- [ ] Manual smoke: zaloguj się jako admin → otwórz `/admin/audit` → zobacz świeże wpisy z każdej akcji

## Out of scope dla Phase 3

- EBR write-side (Phase 4)
- MBR templates / parametry / metody / produkty (Phase 5)
- Cert flow (Phase 6)
- Paliwo flow (Phase 6)
- Admin actions (backup, batch.cancelled, settings.changed) — Phase 6
- Read-log (kto otwierał stronę) — out of scope całego audit traila
- UI dla zmiany hasła w panelu admin — endpoint istnieje, UI later (admin może wywołać przez curl/console)

## Decision log

| Decyzja | Wybór | Alternatywy odrzucone |
|---|---|---|
| Failed login | Wszystkie loguj | Tylko z grace cooldown — za skomplikowane; tylko sukces — gubi audit value |
| `auth.password_changed` | Dodać endpoint w Phase 3 | Skip — nie ma jak zmieniać haseł dziś, dług feature; full user-management — out of scope |
| Shift fallback | Pełne usunięcie dla rola=laborant | Tylko save_entry — niespójne; soft mode — sprzeczne ze spec |
| Frontend handler | Lokalne w każdym JS handlerze | Globalny fetch wrapper — duży refaktor; HTTP redirect — kombinatoryka semantyki |
| Password change payload | Tylko target_user_id + login | + metadane (długość) — leak; + hash — security risk |
| `worker.activated/deactivated` | Nie, używać `worker.updated` z diff | Osobne eventy — niepotrzebna fragmentacja taksonomii |
