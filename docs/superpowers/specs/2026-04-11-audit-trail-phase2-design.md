# Audit Trail — Phase 2 (Admin Panel + Archival + Per-Record History) — Design

**Data:** 2026-04-11
**Status:** Draft → do recenzji
**Cel:** Read-only UI dla audit trail (panel admina, eksport CSV, archiwizacja, sekcje historii w widokach EBR/MBR/cert).
**Parent spec:** `docs/superpowers/specs/2026-04-11-audit-trail-design.md` (Phase 1)
**Parent plan:** `docs/superpowers/plans/2026-04-11-audit-trail-phase1.md`

## Kontekst

Phase 1 wdrożyła infrastrukturę audit trail: tabele `audit_log` + `audit_log_actors`, helper `mbr/shared/audit.py` z `log_event()`, integrację Flask (`g.audit_request_id` per request), migrację legacy `audit_log` do nowego schematu (42 wpisy zmigrowane jako `event_type='legacy.field_change'`), auto-deploy z idempotentną migracją. Wszystkie testy zielone (261/16/0). Zero call-site'ów `log_event()` w blueprintach — Phase 1 to czysta infrastruktura.

Phase 2 daje **wizualny dostęp** do tej infrastruktury:
- Admin może w UI zobaczyć każdy zmigrowany wpis i każdy przyszły wpis z Phases 3-6
- Eksport CSV dla auditu zewnętrznego/backup-u
- Ręczna archiwizacja > 2 lata do `data/audit_archive/audit_<rok>.jsonl.gz` (pierwszy real `log_event()` call site na produkcji — system actor, niski risk)
- Sekcje „Historia" per-rekord w widokach szarży / szablonu MBR / świadectwa

Phase 2 jest **read-only z punktu widzenia istniejących flow** — żaden write-side endpoint nie zostaje zmieniony. Jedyna nowa pisemna ścieżka to archiwizacja, która operuje wyłącznie na `audit_log` + nowych plikach archiwalnych.

## Zakres

Wszystko poniżej w Phase 2:
- ✅ Panel admina `/admin/audit` z filtrami + paginacja + eksport CSV
- ✅ Archiwizacja wpisów > 2 lata (przycisk + modal + endpoint + writer JSONL.gz)
- ✅ Per-record sekcje historii w **trzech** widokach: EBR (szarża), MBR (szablon), świadectwo

Out of scope dla Phase 2:
- Phase 3: integracja write-side w auth + workers (pierwsze prawdziwe `log_event()` w blueprintach poza systemem)
- Phase 4-6: pozostałe blueprints
- Phase 7: sweep test + drop `audit_log_v1`

## Decyzje brainstormingu

| # | Pytanie | Wybór | Powód |
|---|---|---|---|
| Q1 | Eksport CSV w fazie 2? | **Tak** | Wartość natychmiastowa, ~40 LOC, spójne z panelem |
| Q2 | Archiwizacja w fazie 2? | **Tak** | Pierwszy real `log_event()` jako bezpieczny smoke test infrastruktury |
| Q3 | Per-record history w fazie 2? | **Wszystkie 3 widoki** (EBR + MBR + cert) | Komplet UI surfaces od razu, użytkownik widział całość |
| — | Plik routes admina | **Nowy `mbr/admin/audit_routes.py`** | Istniejący `mbr/admin/routes.py` ma 425 linii, dodanie 250 zrobiłoby 650+ |
| — | Panel: real-time refresh | **Nie** | Page reload przy zmianie filtra wystarcza |
| — | Domyślny cutoff archiwum | **2 lata** (now − 2 years) | Z parent spec |
| — | CSV: limit bezpieczeństwa | **1 000 000** wierszy | Pamięć zawsze pod kontrolą |
| — | Archive endpoint: 1 czy 2 calls | **2 calls** (preview + apply) | Admin musi widzieć liczbę przed kliknięciem |
| — | Reusable partial historii | **Tak**, jeden `_audit_history_section.html` | DRY, jeden punkt zmiany |
| — | Auto-load historii | **Tak**, fetch przy renderze sekcji | Jedno żądanie więcej, ale UX bez kliku |
| — | CSS panelu | **Inline w `audit.html`** | Phase 2 samowystarczalne, nie rozdmuchujemy `lab_common.css` |

## Architektura

### Struktura plików

**Tworzymy:**
- `mbr/admin/audit_routes.py` — routes panelu (~250 LOC)
- `mbr/templates/admin/audit.html` — szablon panelu z inline CSS + vanilla JS (~250 LOC)
- `mbr/templates/_audit_history_section.html` — partial reusable dla sekcji historii w widokach (~50 LOC)
- `tests/test_admin_audit.py` — testy panelu, archiwizacji, per-record endpoints (~300 LOC, ~13 testów)

**Modyfikujemy:**
- `mbr/shared/audit.py` — dorzucamy 3 nowe funkcje read/archive (~120 LOC)
- `mbr/admin/__init__.py` — import nowego modułu routes
- `mbr/templates/base.html` — nowa pozycja w railu admina (1 linia + ikona SVG)
- `mbr/laborant/routes.py:213` — przepisanie istniejącego `get_audit_log(ebr_id)` na nowy URL `/api/ebr/<id>/audit-history` używający `query_audit_history_for_entity`
- `mbr/templates/laborant/_fast_entry_content.html` — `{% include "_audit_history_section.html" %}` pod sekcją uwag
- `mbr/technolog/routes.py` — nowy endpoint `get_mbr_audit_history`
- Szablon edycji szablonu MBR (zlokalizowany przy implementacji) — include partial
- `mbr/certs/routes.py` — nowy endpoint `get_cert_audit_history`
- Szablon widoku świadectwa (zlokalizowany przy implementacji) — include partial
- `mbr/shared/filters.py` — Jinja filter `audit_actors`
- `tests/test_audit_helper.py` — append testy dla nowych helperów (~10 testów)

### Backend: nowe funkcje w `mbr/shared/audit.py`

```python
def query_audit_log(
    db,
    *,
    dt_from: str = None,           # ISO date 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS'
    dt_to: str = None,
    event_type_glob: str = None,   # 'auth.*', 'ebr.*', or exact 'auth.login'
    entity_type: str = None,
    entity_id: int = None,
    worker_id: int = None,         # filter via audit_log_actors join
    free_text: str = None,         # LIKE on entity_label OR payload_json
    request_id: str = None,        # for "show all from this submit" links
    limit: int = 100,
    offset: int = 0,
) -> tuple[list, int]:
    """Returns (rows, total_count). Each row is dict with audit_log columns plus
    'actors' (list of {worker_id, actor_login, actor_rola}).

    Glob behavior: if event_type_glob contains '*', translate to SQL LIKE
    (e.g. 'auth.*' -> 'auth.%'). Otherwise exact equality.

    For multi-actor filter (worker_id), uses EXISTS subquery on
    audit_log_actors so a row matches if ANY of its actors equals worker_id.

    total_count is unpaginated — single round-trip extra SELECT COUNT(*)
    with the same WHERE.
    """

def query_audit_history_for_entity(db, entity_type: str, entity_id: int) -> list:
    """Per-record history. Returns rows with actors, sorted dt DESC.
    No pagination — entity histories are bounded (single batch ~50 events max).
    """

def archive_old_entries(db, cutoff_iso: str, archive_dir: Path) -> dict:
    """Move audit_log entries with dt < cutoff_iso into a .jsonl.gz archive
    file, then DELETE them from the active DB.

    File path: archive_dir / f'audit_{cutoff_year}.jsonl.gz' where cutoff_year
    is parsed from cutoff_iso. Uses gzip.open(path, 'at') so multiple
    archivals in the same year append to one file.

    Each line is a JSON object: {audit_log_row..., actors: [...]}.

    After deletion, calls log_event('system.audit.archived',
    payload={count, file, cutoff}, actors=actors_system(), db=db).

    Returns: {'archived': N, 'file': str(path), 'cutoff': cutoff_iso}.
    Wraps everything in a single transaction; rollback on file write error.
    """
```

### Routes w `mbr/admin/audit_routes.py`

| Method | URL | Role | Purpose |
|---|---|---|---|
| GET | `/admin/audit` | admin | Render panel with filters + paginated table |
| GET | `/admin/audit/export.csv` | admin | Stream CSV using same WHERE as panel, no pagination |
| POST | `/admin/audit/archive/preview` | admin | Return count of rows that would be archived (no mutation) |
| POST | `/admin/audit/archive` | admin | Run archival, return summary dict |

Wszystkie chronione `@role_required("admin")`. Panel akceptuje wszystkie filtry przez `request.args` i przekazuje do `query_audit_log` przez helper `_parse_filters_from_query`. Eksport używa tego samego helpera, więc URL filtrów panelu z dopiskiem `&format=csv` dawały by ten sam zestaw — w pratyce front renderuje przycisk „Eksport CSV" z aktualnym query stringiem.

### Per-record history endpoints

| Method | URL | Role | Implemented in |
|---|---|---|---|
| GET | `/api/ebr/<id>/audit-history` | laborant, laborant_kj, admin, technolog | `mbr/laborant/routes.py` (replaces existing `get_audit_log`) |
| GET | `/api/mbr/<id>/audit-history` | admin, technolog | `mbr/technolog/routes.py` (new) |
| GET | `/api/cert/<id>/audit-history` | admin, technolog, laborant_coa, laborant_kj | `mbr/certs/routes.py` (new) |

Wszystkie zwracają `{"history": [...]}`. Front jednolicie renderuje przez `_audit_history_section.html` partial.

### Frontend: panel `mbr/templates/admin/audit.html`

Layout (vanilla HTML + inline CSS, brak JS framework):

```
┌─ Filtry ────────────────────────────────────────────────────────────────┐
│ [Od __] [Do __] [Event ▾] [Byt ▾] [Aktor ▾] [Szukaj __] [Filtruj] [CSV] │
│                                                       [Archiwizuj > 2L] │
└──────────────────────────────────────────────────────────────────────────┘

N wpisów (strona X z Y)

┌─ Tabela ────────────────────────────────────────────────────────────────┐
│ Data/godz       │ Event               │ Byt            │ Aktor(zy) │ ▶ │
├─────────────────┼─────────────────────┼────────────────┼───────────┼───┤
│ 2026-04-11 14:23│ ebr.wynik.saved     │ Szarża 2026/42 │ AK, MW    │ ▶ │
│   ↳ rozwinięty wiersz: diff table + payload <pre> + IP + request_id link│
└──────────────────────────────────────────────────────────────────────────┘

         [← Poprzednia]  Strona 1 / 12  [Następna →]
```

Klik wiersza → toggle `<tr class="audit-details" hidden>` z pod-wierszem rozwijanym. Dropdown event_type pokazuje grupy `(wszystkie)`, `auth.*`, `ebr.*`, `mbr.*`, `cert.*`, `admin.*`, `system.*`.

Modal archiwizacji jest osobnym `<div id="archive-modal">` ukrytym domyślnie, otwieranym przez `openArchiveModal()`. Modal wywołuje preview, wyświetla liczbę i cutoff, na potwierdzenie wywołuje apply, refreshuje stronę.

### Frontend: per-record partial `mbr/templates/_audit_history_section.html`

```html
<div class="audit-hist" data-entity-type="{{ entity_type }}" data-entity-id="{{ entity_id }}">
  <div class="audit-hist-head">HISTORIA AUDYTU
    <button onclick="loadAuditHist(this)">Odśwież</button>
  </div>
  <div class="audit-hist-body">— ładowanie —</div>
</div>
<script>
async function loadAuditHist(btn) { /* fetch + render */ }
function renderAuditEntry(r) { /* dt + event_type + actors + diff inline */ }
document.querySelectorAll('.audit-hist').forEach(s => loadAuditHist(s.querySelector('button')));
</script>
```

Auto-load przy renderze. Każdy wpis to jedna linia: `dt | event_type | actors — diff_inline`.

### Jinja filter `audit_actors`

```python
def audit_actors(audit_row) -> str:
    """Render actors as 'AK, MW' joined logins, or '—' if empty."""
    actors = audit_row.get("actors") or []
    if not actors:
        return "—"
    return ", ".join(a["actor_login"] for a in actors)
```

Rejestracja w `register_filters(app)`.

## Wewnętrzne fazowanie (4 sub-PR-ki)

### Sub-PR 2.1 — Backend helpers (czysta logika, zero UI)
- `query_audit_log`, `query_audit_history_for_entity`, `archive_old_entries` w `mbr/shared/audit.py`
- 14 unit testów w `tests/test_audit_helper.py`
- **Po wdrożeniu**: funkcje istnieją, nikt jeszcze nie woła. Bezpieczne osobno.
- **Czas**: ~45 min

### Sub-PR 2.2 — Panel admina (route + szablon + filtry + CSV)
- `mbr/admin/audit_routes.py` z 4 routes (panel, csv, archive preview/apply)
- `mbr/admin/__init__.py` — register
- `mbr/templates/admin/audit.html` z filtrami, tabelą, modalem (szkielet), JS
- `mbr/templates/base.html` — nowy rail link „Audit trail" tylko admin
- `mbr/shared/filters.py` — filter `audit_actors`
- 8 HTTP testów panelu
- **Po wdrożeniu**: admin widzi `/admin/audit`, filtruje, eksportuje CSV. Modal archiwizacji jeszcze nie działa (Sub-PR 2.3).
- **Czas**: ~75 min

### Sub-PR 2.3 — Archiwizacja end-to-end
- Modal w `audit.html` zaczyna realnie wywoływać `audit_archive_preview` + `audit_archive_do`
- 1 e2e test przez Flask client
- **Po wdrożeniu**: archiwizacja działa. **Pierwszy real `log_event()` call site na produkcji.** Sympatyczny smoke test infrastruktury Phase 1.
- **Czas**: ~30 min

### Sub-PR 2.4 — Per-record history sekcje
- `mbr/templates/_audit_history_section.html` partial reusable
- Przepisanie istniejącego `get_audit_log(ebr_id)` w `mbr/laborant/routes.py:213` na **nowy URL** `/api/ebr/<id>/audit-history` używający `query_audit_history_for_entity` (stary URL znika — czysty rollback)
- `_fast_entry_content.html` — `{% include "_audit_history_section.html" %}` z `entity_type='ebr'`
- `mbr/technolog/routes.py` — nowy endpoint `get_mbr_audit_history` + lokalizacja szablonu MBR + include
- `mbr/certs/routes.py` — nowy endpoint `get_cert_audit_history` + lokalizacja szablonu cert + include
- 5 testów (3 endpoint + 2 filter)
- **Po wdrożeniu**: 3 sekcje historii widoczne. EBR pokaże legacy wpisy zmigrowane z Phase 1. MBR i cert sekcje będą puste (oczekują real data z Phases 5/6).
- **Czas**: ~45 min

**Total: ~3-4 godziny, ~27 testów, 4 sub-PR-ki na branchu `audit/phase2`.**

## Plan rollback

| Sub-PR | Co psuje rollback | Recovery |
|---|---|---|
| 2.1 (helpers) | Nic — funkcje nieużywane | `git revert` |
| 2.2 (panel) | Rail link „Audit trail" znika, `/admin/audit` → 404. Reszta nietknięta. | `git revert` |
| 2.3 (archiwizacja) | Modal pokazuje liczbę 0 lub error. Aktywne dane bezpieczne (transakcyjne). | `git revert`. Już zarchiwizowane wpisy zostają w `data/audit_archive/audit_<rok>.jsonl.gz` — nie wracają do bazy automatycznie. |
| 2.4 (per-record) | Sekcje historii znikają. Stary URL `get_audit_log` został usunięty świadomie — nie ma czego cofać. | `git revert` |

Sub-PR 2.4 jest jedynym z kompleksem zależności (przepisanie istniejącego endpointa). Mitygacja: usuwamy stary endpoint zupełnie zamiast zostawiać oba — wtedy rollback nie cofa do złamanej wersji, tylko zwraca 404 dla nieużywanego URL-a.

## Testy

### Helper-level (14 testów, in-memory DB)

1. `test_query_returns_empty_when_no_rows`
2. `test_query_filter_by_dt_range`
3. `test_query_filter_by_event_type_glob` (`auth.*`)
4. `test_query_filter_by_event_type_exact` (`auth.login`)
5. `test_query_filter_by_entity_type_and_id`
6. `test_query_filter_by_worker_id_uses_actors_table`
7. `test_query_filter_by_free_text_searches_label_and_payload`
8. `test_query_pagination` (250 wpisów, offset/limit)
9. `test_history_for_entity_returns_only_matching` (sortuje DESC)
10. `test_history_for_entity_includes_actors`
11. `test_archive_dumps_old_entries_to_jsonl_gz_and_deletes`
12. `test_archive_appends_to_existing_year_file`
13. `test_archive_returns_summary_with_count_and_path`
14. `test_archive_logs_system_audit_archived_event`

### HTTP-level (8 testów, Flask test client)

15. `test_admin_audit_panel_returns_200_for_admin`
16. `test_admin_audit_panel_forbidden_for_non_admin` (403)
17. `test_admin_audit_panel_filters_by_date`
18. `test_admin_audit_panel_pagination_links` (150 wpisów, page=2)
19. `test_admin_audit_export_csv_streams_correct_columns` (z escapowaniem przecinków)
20. `test_admin_audit_archive_preview_returns_count` (no mutation)
21. `test_admin_audit_archive_apply_runs_archive` (e2e)
22. `test_admin_audit_panel_request_id_link_filters`

### Per-record endpoints (3 testy)

23. `test_ebr_audit_history_endpoint_returns_only_ebr_entries`
24. `test_mbr_audit_history_endpoint_role_protected` (laborant 403, technolog 200)
25. `test_cert_audit_history_endpoint_returns_actors`

### Jinja filter (2 testy)

26. `test_audit_actors_filter_joins_logins`
27. `test_audit_actors_filter_handles_empty`

**Total: 27 nowych testów.**

## Out of scope dla Phase 2

- Real-time refresh / WebSocket (page reload wystarcza)
- Server-side full-text search engine (LIKE wystarcza dla setek tysięcy wpisów)
- Customizable saved filter views (URL params wystarczają jako bookmarks)
- Audit log integrity verification (Phase 7 sweep test)
- Drop `audit_log_v1` (Phase 7)
- Removing pre-existing legacy junk tables `_ebr_wyniki_old` etc. (orphan FK — pre-existing tech debt nie związany z audit trailem)
- Per-record history dla innych entity_type (worker, paliwo, registry) — dodajemy przy okazji integracji write-side w Phases 3-6

## Acceptance criteria

Phase 2 jest gotowa do merge gdy:

- [ ] Wszystkie 27 nowych testów zielone
- [ ] Pełna suite zielona (≈288 passed, 16 skipped, 0 failed po Phase 2 — 261 baseline + 27 nowych)
- [ ] Admin może wejść `/admin/audit`, zobaczyć 42 zmigrowane wpisy, filtrować i eksportować CSV
- [ ] Modal archiwizacji działa: preview pokazuje liczbę, apply tworzy plik `data/audit_archive/audit_<rok>.jsonl.gz` i usuwa wpisy z bazy
- [ ] Po archiwizacji w `audit_log` pojawia się nowy wpis `event_type='system.audit.archived'`
- [ ] Sekcja „Historia audytu" widoczna w widoku szarży (legacy wpisy `legacy.field_change`)
- [ ] Sekcja „Historia audytu" widoczna w widoku szablonu MBR (pusta, oczekiwane)
- [ ] Sekcja „Historia audytu" widoczna w widoku świadectwa (pusta, oczekiwane)
- [ ] Manual smoke test w przeglądarce: filtrowanie, paginacja, klik wiersza rozwija detale, klik request_id zwęża listę
- [ ] Code review: każdy sub-PR przeszedł dwuetapowy review (spec compliance + code quality)

## Decision log (zarchiwowane)

| Decyzja | Wybór | Alternatywy odrzucone |
|---|---|---|
| Eksport CSV | W Phase 2 | Phase 7 — wartość użytkownika za odległa |
| Archiwizacja | W Phase 2 | Phase 7 — chcemy pierwszy real `log_event()` smoke test wcześniej |
| Per-record history scope | Wszystkie 3 (EBR + MBR + cert) | Tylko EBR — user wybrał komplet UI surfaces od razu |
| Plik routes | Nowy `audit_routes.py` | Append do `routes.py` — 425 → 650+ za duże |
| Reusable partial | Tak | 3 osobne snipety — DRY violation |
| Auto-load historii | Tak | Przycisk „Załaduj" — niepotrzebny klik |
| CSS panelu | Inline w szablonie | Globalny `lab_common.css` — Phase 2 samowystarczalne |
| Archive endpoint | 2 calls (preview + apply) | 1 call z `confirm: true` — admin musi widzieć liczbę |
| Domyślny cutoff | 2 lata | 1/3/5 lat — z parent spec |
| CSV limit bezp. | 1 000 000 | Bez limitu — pamięć |
| Sub-PR count | 4 | 3 (zlanie 2.2+2.3) — user wolał granularność |
| Stary `get_audit_log(ebr_id)` | Usunięty, nowy URL `/api/ebr/<id>/audit-history` | Zostawić oba — niepotrzebny dług |
