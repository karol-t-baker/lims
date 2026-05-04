# Elastyczny generator świadectw — Design Spec

**Date:** 2026-05-04
**Status:** Draft (post-brainstorm)
**Powiązane:** kontynuacja pod-projektu C z dekompozycji w `2026-05-01-produkt-pola-uniwersalne-design.md` (linijka 8). Pod-projekty A (uniwersalne pola) i B (korelacja raw→cert) niezależne.

## Problem

Każde nowe miejsce sprzedaży / odbiorca świadectwa = osobny rekord w `cert_variants`, mimo że treść certyfikatu (parametry, metody, wymagania, opinie, flagi) jest identyczna z istniejącym wariantem. Konkretne przykłady z produkcji (`SELECT * FROM cert_variants ORDER BY produkt`):

- `Chegina_K7`: `base`, `mb`, `nr_zam`, `adam_partner`, `dr_miele` — pierwsze dwa różnią się merytorycznie, kolejne trzy są de facto `base`/`mb` z dopisaną nazwą firmy.
- `Chegina_K40GLOL`: `base`, `loreal`, `loreal_belgia`, `loreal_wlochy`, `kosmepol` — wszystkie cztery customer-warianty bardzo prawdopodobnie identyczne z `loreal` (do weryfikacji ręcznej).
- `Chegina_K40GLO`: `base`, `mb`, `nr_zam`, `mb_nr_zam` — duplikacja wzdłuż drugiej osi (numer zamówienia jako flag).

Drugi pain point: data ważności jest na poziomie produktu (`produkty.expiry_months`), nie ma per-cert override. W praktyce dla wybranych odbiorców (np. Albania) trzeba 18 lub 24 miesięcy zamiast standardowych 12 — dziś wymaga osobnego wariantu albo ręcznej edycji.

Razem powoduje to:
- **n × m duplikację** wariantów (odbiorcy × dodatkowe wymiary jak nr_zam/MB/expiry).
- Spam w dropdownie wariantów przy generowaniu świadectwa.
- Każde nowe partnerstwo handlowe = klikanie po edytorze wzorów + ryzyko niespójnej kopii.

## Goal

Zredukować warianty do **merytorycznych** (różnią się treścią certyfikatu — parametry, opinie, flagi strukturalne) i przesunąć dane "kto / dla kogo / na jak długo" na poziom **runtime** (wpisywane w momencie wystawiania świadectwa).

Konkretnie: trzy nowe pola w formularzu generowania, dostępne zawsze niezależnie od wariantu:

1. **Nazwa zamawiającego** — free text, opcjonalna, **renderowana wyłącznie w nazwie pliku PDF**, autocomplete z historii (`SELECT DISTINCT recipient_name FROM swiadectwa`).
2. **Ważność (miesięcy)** — integer 1–30, default = `produkty.expiry_months`, override per-cert.
3. **Numer zamówienia** — free text, opcjonalny, renderowany w treści certyfikatu jeśli wpisany (template już wspiera `{% if order_number %}`).

## Non-goals

- **Rejestr "Odbiorcy"** (CRUD'owalna tabela). Autocomplete z historii starczy — kompromis spójność/koszt utrzymania świadomy. Akceptujemy że `ADAM&PARTNER` i `ADAM & PARTNER` mogą się rozjechać w historii.
- **Konsolidacja AVON wariantów** (`Alkinol_B avon`, `Chegina_KK avon` itd.). Mają strukturalne różnice (kod R-, INCI text, dodatkowe etykiety) — to merit-warianty, zostają.
- **Renderowanie nazwy odbiorcy w treści PDF.** Wyłącznie w nazwie pliku — świadoma decyzja podczas brainstormu.
- **Audit log dla niestandardowej ważności.** Snapshot w `swiadectwa.expiry_months_used` wystarczy. Ślad w istniejącym `data_json`.
- **Skrypt audytu / bulk-archive starych wariantów.** Użytkownik ma większą wiedzę domenową niż heurystyka — przejrzy ręcznie po dostarczeniu UI archive button.
- **Walidacja unikalności nazwy odbiorcy.** Jeśli ktoś chce zaznaczyć "ADAM Partner" jako alias dla "ADAM&PARTNER" — out of scope.
- **Refaktor DOCX templating engine.** Treść PDF zmienia się tylko w jednym miejscu (warunkowe renderowanie nr zamówienia już istnieje).

## Architektura

### Schema (3 zmiany, additive)

```sql
ALTER TABLE swiadectwa ADD COLUMN recipient_name TEXT;
-- NULL = brak personalizacji (cert wystawiony bez "dla kogo").
-- Wartość = string wpisany w formularzu (po sanityzacji).

ALTER TABLE swiadectwa ADD COLUMN expiry_months_used INTEGER;
-- Zawsze zapisywane (nie tylko gdy override) — snapshot rzeczywistej
-- liczby miesięcy użytej w obliczeniu daty ważności na PDF.
-- Niezbędne dla reproducibility gdy `produkty.expiry_months` zmieni się
-- w przyszłości.

ALTER TABLE cert_variants ADD COLUMN archived INTEGER DEFAULT 0;
-- archived=1 → wariant ukryty w UI dropdownach domyślnie,
-- ale FK ze starych `swiadectwa` przez `template_name` dalej działa
-- (archived nie usuwamy, soft-delete).
```

Backward-compatibility: kolumny additive. Stary kod który nie czyta nowych kolumn działa jak dziś. Stare świadectwa mają `recipient_name=NULL`, `expiry_months_used=NULL` — odczyt w UI obsługuje gracefully.

### Generator — `mbr/certs/generator.py`

#### `build_context()` zmiany

`extra_fields` zyskuje nowe klucze. `expiry_months` override podmienia źródło wartości:

```python
# Obecnie (linijka ~439):
expiry_months = _expiry_months  # z produkty

# Po zmianie:
override = (extra_fields or {}).get("expiry_months")
if override is not None and str(override).strip():
    try:
        n = int(override)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid expiry_months: {override!r}")
    if not (1 <= n <= 30):
        raise ValueError(f"expiry_months out of range 1..30: {n}")
    expiry_months = n
else:
    expiry_months = _expiry_months
```

`recipient_name` i `expiry_months_used` zwracane są z `build_context()` jako pomocnicze pola w returned dict (do zapisu w `swiadectwa`), ale **nie idą do template'u** — DOCX o nich nie wie. Realnie sygnatura zwraca extra metadata oddzielnie albo jako `_meta` sub-namespace.

#### `_cert_names()` zmiany

```python
def _cert_names(produkt, variant_label, nr_partii,
                recipient_name=None, has_order_number=False):
    # ... obecna logika ...
    parts = [product_folder]
    if variant_suffix:
        parts.append(variant_suffix)
    if recipient_name:
        sanitized = _sanitize_filename_segment(recipient_name)
        if sanitized:
            parts.append("—")  # em dash
            parts.append(sanitized)
    parts.append(nr_only)
    if has_order_number:
        parts.append("(NRZAM)")
    pdf_name = " ".join(parts) + ".pdf"
    return product_folder, pdf_name, nr_only


def _sanitize_filename_segment(s: str) -> str:
    """Strip path separators and control chars; trim to 40 chars."""
    if not s:
        return ""
    # Remove anything < 0x20, '/', '\\', ':' and trim whitespace.
    cleaned = "".join(c for c in s if ord(c) >= 0x20 and c not in ("/", "\\", ":"))
    cleaned = cleaned.strip()
    return cleaned[:40]
```

Format docelowy nazwy pliku:

| Kontekst | Nazwa pliku |
|---|---|
| Bez odbiorcy (jak dziś) | `Chegina K7 4.pdf` |
| Z odbiorcą | `Chegina K7 — ADAM&PARTNER 4.pdf` |
| Z odbiorcą + MB | `Chegina K7 MB — ADAM&PARTNER 4.pdf` |
| Z odbiorcą + nr zamówienia | `Chegina K7 — ADAM&PARTNER 4 (NRZAM).pdf` |
| Bez odbiorcy + nr zamówienia | `Chegina K7 4 (NRZAM).pdf` |

Em-dash przed nazwą odbiorcy, numer szarży, opcjonalny suffix `(NRZAM)` na końcu — utrzymujemy istniejącą konwencję "numer ostatni" (zachowuje sortowanie alfabetyczne grupujące po wariancie). Suffix `(NRZAM)` zachowuje informację że ten cert miał wpisany numer zamówienia (zastępuje stary tag `NR_ZAM` z labela wariantu `nr_zam`).

#### Kolizja nazw plików (collision-aware save)

`save_certificate_pdf` (generator.py:1112) dziś robi `full_path.write_bytes(pdf_bytes)` — bez sprawdzenia czy plik istnieje. Dwa certy z identycznymi inputami (re-issue tej samej szarży, identyczny odbiorca, identyczne pola) → second silently overwrites first. To środowisko regulowane — nadpisanie wystawionego dokumentu jest niedopuszczalne.

Nowe zachowanie:

```python
def save_certificate_pdf(pdf_bytes, produkt, variant_label, nr_partii,
                         output_dir=None, recipient_name=None,
                         has_order_number=False) -> str:
    # ... compute target_dir, base_pdf_name jak dziś ...
    full_path = target_dir / pdf_name
    if full_path.exists():
        stem = full_path.stem
        suffix = full_path.suffix
        i = 2
        while True:
            candidate = target_dir / f"{stem} ({i}){suffix}"
            if not candidate.exists():
                full_path = candidate
                break
            i += 1
    full_path.write_bytes(pdf_bytes)
    return str(full_path)
```

Pierwsza kolizja → `Chegina K7 — ADAM&PARTNER 4 (2).pdf`. Druga → `(3)`. Itd. `swiadectwa.pdf_path` zapisuje rzeczywistą ścieżkę z suffixem (a nie surową `pdf_name`). Stary kod pobierający historię świadectw po `pdf_path` działa bez zmian. `save_certificate_data` (JSON snapshot) używa identycznej logiki przyrostka.

### Routes — `mbr/certs/routes.py`

#### `api_cert_generate` (POST)

Obecne `extra_fields` rozszerzone o nowe klucze:

```jsonc
{
  "ebr_id": 123,
  "variant_id": "base",
  "target_produkt": "Chegina_K7",
  "wystawil": "Jan Kowalski",
  "extra_fields": {
    "recipient_name": "ADAM&PARTNER",      // nowy, opcjonalny
    "expiry_months": 18,                   // nowy, opcjonalny (1..30)
    "order_number": "ZAM/2026/123",        // istniejący — teraz zawsze opcjonalny w UI
    "certificate_number": "...",           // istniejący
    "avon_code": "...",                    // istniejący
    "avon_name": "..."                     // istniejący
  }
}
```

Walidacja na serwerze:
- `expiry_months`: jeśli podany, musi być integer 1..30. Inaczej 400.
- `recipient_name`: trim + sanityzacja (`_sanitize_filename_segment`); pusty po sanityzacji = traktowany jak NULL.
- Pozostałe pola: jak dziś.

`create_swiadectwo` zapisuje teraz `recipient_name` i `expiry_months_used` (= rzeczywiście użyta wartość, czyli override jeśli był, inaczej `produkty.expiry_months`).

#### Nowy endpoint: `GET /api/cert/recipient-suggestions`

```python
@certs_bp.route("/api/cert/recipient-suggestions")
@login_required
def api_cert_recipient_suggestions():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"suggestions": []})
    with db_session() as db:
        rows = db.execute(
            "SELECT DISTINCT recipient_name FROM swiadectwa "
            "WHERE recipient_name IS NOT NULL "
            "AND recipient_name LIKE ? COLLATE NOCASE "
            "ORDER BY recipient_name LIMIT 20",
            (f"%{q}%",),
        ).fetchall()
    return jsonify({"suggestions": [r["recipient_name"] for r in rows]})
```

Threshold 2 znaki — uzgodnione w brainstormie.

#### `api_cert_templates` rozszerzenie response

Każdy template zyskuje `default_expiry_months`:

```jsonc
{
  "filename": "base",
  "display": "Chegina K7",
  "flags": [],
  "owner_produkt": "Chegina_K7",
  "required_fields": [],
  "default_expiry_months": 12   // nowy — z produkty.expiry_months
}
```

Wartość czytana z `produkty.expiry_months` po stronie serwera, fallback 12.

#### Nowy endpoint: `POST /api/cert/variants/<id>/archive`

```python
@certs_bp.route("/api/cert/variants/<int:variant_id>/archive", methods=["POST"])
@role_required("admin")
def api_cert_variant_archive(variant_id):
    payload = request.get_json(silent=True) or {}
    archived = bool(payload.get("archived", True))
    backfill = payload.get("backfill_recipient")  # str | None
    event = "cert.variant.archived" if archived else "cert.variant.unarchived"
    with db_session() as db:
        # 1. Toggle archive flag.
        db.execute("UPDATE cert_variants SET archived=? WHERE id=?",
                   (1 if archived else 0, variant_id))
        log_audit(db, session.get("username"), event, {"variant_id": variant_id})
        # 2. Optional backfill (only on archive, not unarchive).
        backfill_count = 0
        if archived and backfill:
            cleaned = _sanitize_filename_segment(backfill)
            if cleaned:
                # Resolve template_name from variant_id for the WHERE clause.
                vrow = db.execute(
                    "SELECT variant_id FROM cert_variants WHERE id=?",
                    (variant_id,)).fetchone()
                if vrow:
                    cur = db.execute(
                        "UPDATE swiadectwa SET recipient_name=? "
                        "WHERE template_name=? AND recipient_name IS NULL",
                        (cleaned, vrow["variant_id"]))
                    backfill_count = cur.rowcount
                    if backfill_count > 0:
                        log_audit(db, session.get("username"),
                                  "cert.swiadectwa.recipient_backfilled",
                                  {"variant_id": variant_id,
                                   "recipient_name": cleaned,
                                   "count": backfill_count})
        db.commit()
    return jsonify({"ok": True, "archived": archived,
                    "backfill_count": backfill_count})
```

`api_cert_templates` filtruje `archived=0` chyba że `?include_archived=1`. Cert editor (admin) używa `include_archived=1` razem z togglem UI.

#### Nowy endpoint: `GET /api/cert/variants/<id>/archive-preview`

Wczytuje statystyki potrzebne do otwarcia modala backfillu (zanim user kliknie OK):

```python
@certs_bp.route("/api/cert/variants/<int:variant_id>/archive-preview")
@role_required("admin")
def api_cert_variant_archive_preview(variant_id):
    with db_session() as db:
        vrow = db.execute(
            "SELECT variant_id, label FROM cert_variants WHERE id=?",
            (variant_id,)).fetchone()
        if not vrow:
            abort(404)
        count = db.execute(
            "SELECT COUNT(*) c FROM swiadectwa "
            "WHERE template_name=? AND recipient_name IS NULL",
            (vrow["variant_id"],)).fetchone()["c"]
    # Parsuj propozycję recipient z labela: "Chegina K7 — ADAM&PARTNER" → "ADAM&PARTNER".
    suggested = ""
    if "—" in vrow["label"]:
        suggested = vrow["label"].split("—", 1)[1].strip()
    return jsonify({"swiadectwa_count": count, "suggested_recipient": suggested})
```

### UI — modal generowania (`mbr/templates/laborant/_fast_entry_content.html`)

Modal `cv-popup-overlay` przebudowa: zawsze pokazywany (nie tylko gdy `requiredFields.length > 0`), 3 stałe pola u góry + warunkowo flag-fields (AVON itp.) pod separatorem.

Layout:

```
┌─ Wystaw świadectwo ────────────────────────────────────┐
│                                                        │
│  Odbiorca (opcjonalny)                                 │
│  [ free-text z autocomplete dropdownem            ▾ ] │
│                                                        │
│  Ważność (miesięcy)                                    │
│  [ 12 ]                                                │
│                                                        │
│  Numer zamówienia (opcjonalny)                         │
│  [                                                  ]  │
│                                                        │
│  ─── Pola wymagane przez wariant ───  (jeśli są flagi)│
│  Kod AVON / AVON code *           [             ]      │
│  Nazwa AVON / AVON name *         [             ]      │
│                                                        │
│           [ Anuluj ]    [ Wystaw ]                     │
└────────────────────────────────────────────────────────┘
```

Logika pól:

- **Odbiorca**: input + ukryta lista. Po keystroke (debounce 200ms, threshold 2 znaki) → `GET /api/cert/recipient-suggestions?q=<v>` → render `<div>` z opcjami pod inputem. Klik / Enter / Tab z opcji → wpisuje wartość. Esc / klik poza → zamyka.
- **Ważność**: `<input type="number" min="1" max="30">`, prefilled `default_expiry_months`. Walidacja inline (czerwona ramka jeśli poza zakresem).
- **Numer zamówienia**: zwykły text input, brak walidacji.
- **Flag-fields**: tylko jeśli `requiredFields` zawiera odpowiednią flagę (`has_avon_code`, `has_avon_name`, `has_certificate_number`). Wymagane (czerwona ramka jeśli puste, jak dziś). `has_order_number` z `requiredFields` jest **ignorowane** w nowym UI — order_number zawsze widoczne w stałej sekcji.

JS: short-circuit `if (!requiredFields || requiredFields.length === 0) doGenerateCert(...)` w `issueCert()` znika. Modal zawsze otwierany.

### UI — edytor wzorów (`mbr/templates/admin/wzory_cert.html`)

Trzy zmiany:

1. **Info-box w tabie "Warianty"** (na górze listy):
   > *"Warianty per-odbiorca są deprecjonowane. Używaj pola 'Odbiorca' przy generowaniu świadectwa zamiast tworzenia osobnego wariantu. Definiuj warianty tylko gdy parametry / wymagania / opinie / flagi rzeczywiście się różnią."*

2. **Toggle "Pokaż archiwalne warianty"** (default off) + **button "Archiwizuj" / "Przywróć" przy każdym wariancie** — analogicznie do toggle'a "Pokaż archiwalne" w grid'zie produktów (commit `7039083`). Klik archiwizuje przez `POST /api/cert/variants/<id>/archive` (z opcjonalnym backfill recipient_name — patrz niżej). Wariant z `archived=1` ma wizualne odróżnienie (opacity .55, border dashed — jak `wc-card.archived`).

3. **Ukryć checkbox `has_order_number`** z listy flag wariantu. `order_number` jest teraz zawsze dostępne przy generowaniu, więc flaga jest no-opem. Stare warianty zachowują flagę w DB (nie ruszamy danych) — backend ją ignoruje, UI jej nie pokazuje. Pozostałe flagi (`has_rspo`, `has_avon_code`, `has_avon_name`, `has_certificate_number`) bez zmian.

#### Modal backfillu odbiorcy przy archiwizacji

Klik "Archiwizuj" przy wariancie nie wykonuje akcji od razu — otwiera modal z propozycją backfill `recipient_name` dla starych świadectw tego wariantu:

```
┌─ Archiwizuj wariant: Chegina K7 — ADAM&PARTNER ────────┐
│                                                        │
│  Znaleziono 12 świadectw wystawionych z tego wariantu  │
│  z pustym polem recipient_name.                        │
│                                                        │
│  Możesz wpisać dla nich wstecznie nazwę odbiorcy —     │
│  ułatwi to autocomplete przy przyszłych certach.       │
│                                                        │
│  Recipient (opcjonalny):                               │
│  [ ADAM&PARTNER                                    ]   │
│  ↑ propozycja sparsowana z label'a wariantu — możesz   │
│  edytować, usunąć (puste = bez backfillu) lub zatw.    │
│                                                        │
│         [ Anuluj ]  [ Archiwizuj bez backfill ]        │
│                                  [ Archiwizuj + back. ]│
└────────────────────────────────────────────────────────┘
```

Logika:
- Backend przed otwarciem modala: `SELECT COUNT(*) FROM swiadectwa WHERE template_name=<variant_id> AND recipient_name IS NULL` → `swiadectwa_count`.
- Propozycja recipient: parsing labela jak w `_cert_names` (`split("—", 1)[1].strip()`), albo NULL jeśli brak em-dasha.
- Modal: input edytowalny + 3 przyciski (Anuluj / Archiwizuj bez backfill / Archiwizuj + backfill).
- Wartość po zatwierdzeniu sanityzowana (consistent z runtime path, Pytanie 5 w grillu): server stosuje `_sanitize_filename_segment` przed UPDATE.
- Endpoint payload: `POST /api/cert/variants/<id>/archive {"archived": true, "backfill_recipient": "ADAM&PARTNER"}`. Brak klucza / null → bez backfillu. Pusty string po sanityzacji → traktowany jak null.
- SQL: `UPDATE swiadectwa SET recipient_name=? WHERE template_name=? AND recipient_name IS NULL`. Tylko stare wiersze bez wpisanego recipient (idempotent — wielokrotne archive/unarchive nie nadpisze poprawnie wpisanej historii).
- Audit: jeśli backfill > 0 wierszy, dodatkowy event `cert.swiadectwa.recipient_backfilled` z payloadem `{variant_id, recipient_name, count}`.

Brak skryptu masowego archiwizowania — użytkownik klika ręcznie po przeglądnięciu (uzgodnione w brainstormie).

## Edge cases & invariants

| Case | Behavior |
|---|---|
| Reissue starej szarży gdzie historycznie wybrany wariant jest archived | Laborant widzi tylko aktywne warianty (brak toggla po jego stronie). Aby ponownie wystawić cert używając archiwalnego wariantu, admin musi go najpierw przywrócić w `/admin/wzory-cert`. Stare PDF na dysku pozostają niezmienione — odczyt historii świadectw nie wymaga aktywnego wariantu. |
| Brak `recipient_name` | `swiadectwa.recipient_name = NULL`, filename bez sufixu. Identycznie jak dziś. |
| `recipient_name` zawiera `/` `\` `:` | Sanityzacja w `_sanitize_filename_segment` — wycinane bezpiecznie. Wartość *zapisana* w `swiadectwa.recipient_name` to wartość po sanityzacji (consistent z filename). |
| `expiry_months` < 1 lub > 30 | 400 z message. UI: czerwona ramka. |
| `expiry_months` puste | Używamy `produkty.expiry_months`. `swiadectwa.expiry_months_used` = ta wartość (snapshot). |
| Zmienia się `produkty.expiry_months` po wystawieniu certu | Nie wpływa na wystawione: `swiadectwa.expiry_months_used` ma snapshot. PDF na dysku też niezmienny. |
| Stare `swiadectwa` (sprzed migracji) — odczyt | `recipient_name=NULL`, `expiry_months_used=NULL`. UI wyświetla "—" lub puste. |
| `recipient_name` wpisany dla wariantu który ma w `cert_variants` `avon_name` ustawione | Bez kolizji — `recipient_name` to filename, `avon_name` to treść. Niezależne pola. |
| Stary kod test'owy generuje cert bez `extra_fields.recipient_name` | Działa — `recipient_name=None`, `_cert_names` daje stary format pliku. |
| Wariant ma flagę `has_order_number` ale UI pomija ją w `requiredFields` | Backend: `extra_fields.order_number` zawsze odczytywany, niezależnie od flagi. Flaga w DB pozostaje (no-op funkcjonalnie). UI edytora wzorów (`wzory_cert.html`) **ukrywa** checkbox `has_order_number` z listy flag — admin nie zaznacza nowych. |
| Re-issue tej samej szarży, identyczny odbiorca, identyczne pola → kolizja nazwy pliku | `save_certificate_pdf` wykrywa istniejący plik i dokleja przyrostek `(2)`, `(3)`, ... aż znajdzie wolny slot. Stary cert nigdy nie nadpisany. `swiadectwa.pdf_path` zapisuje rzeczywistą ścieżkę z przyrostkiem. |
| `order_number` wpisany ale `recipient_name` pusty | Filename: `Chegina K7 4 (NRZAM).pdf` — sufix `(NRZAM)` po numerze partii, bez sekcji odbiorcy. |
| Archive backfill — wariant z labelem `Chegina K7` (bez em-dasha) | `archive-preview` zwraca `suggested_recipient=""`. Modal pokazuje pusty input — admin może wpisać ręcznie albo zarchiwizować bez backfillu. |
| Archive backfill — niektóre stare certy mają już `recipient_name` (rzadkie, ale możliwe gdy ktoś częściowo backfilluje wcześniej) | `WHERE recipient_name IS NULL` chroni — backfill nie nadpisze ręcznie ustawionych wartości. |
| Unarchive wariantu → zmiana decyzji | Toggle archived back. **Backfill nie jest cofany** — `recipient_name` zostaje (działa nadal jako sugestia w autocomplete). To intencjonalne: backfill to operacja "wzbogać dane historyczne", nie "zaznacz że wariant archived". |

## Tests (TDD)

Nowe testy do dodania (lokalizacja: `tests/test_certs.py` lub nowy `tests/test_cert_flexibility.py`):

1. **expiry_months override**:
   - `build_context(extra_fields={"expiry_months": 24})` → `dt_waznosci` = `dt_produkcji + 24mc`.
   - `build_context(extra_fields={"expiry_months": 0})` → `ValueError`.
   - `build_context(extra_fields={"expiry_months": 31})` → `ValueError`.
   - `build_context(extra_fields={"expiry_months": "abc"})` → `ValueError`.
   - `build_context(extra_fields={})` → użyte `produkty.expiry_months`.
2. **recipient_name + order_number suffix w filename**:
   - `_cert_names("Chegina_K7", "Chegina K7", "4/2026", recipient_name="ADAM&PARTNER")` → `"Chegina K7 — ADAM&PARTNER 4.pdf"`.
   - `_cert_names(..., recipient_name="ADAM/Partner")` → `"Chegina K7 — ADAMPartner 4.pdf"` (slash usunięty).
   - `_cert_names(..., recipient_name=None)` → `"Chegina K7 4.pdf"` (legacy).
   - `_cert_names(..., recipient_name="   ")` → `"Chegina K7 4.pdf"` (whitespace = brak).
   - `_cert_names(..., has_order_number=True)` → `"Chegina K7 4 (NRZAM).pdf"`.
   - `_cert_names(..., recipient_name="ADAM", has_order_number=True)` → `"Chegina K7 — ADAM 4 (NRZAM).pdf"`.
2b. **Kolizja nazwy pliku → numeracja przyrostka**:
   - `save_certificate_pdf` wywołane drugi raz z identycznymi inputami → `..._4.pdf` istnieje → zapisuje jako `..._4 (2).pdf`.
   - Trzeci raz → `..._4 (3).pdf`. Sekwencja `(2), (3), ...` aż wolny.
   - `(2)` istnieje + `(4)` istnieje, `(3)` wolny → zapisuje jako `(3)` (nie szuka pierwszej luki w pełni — dolicza naturalnie). (Akceptowalne: edge case rzadki, prosty algorytm > optymalny algorytm.)
3. **`recipient_name` zapis w `swiadectwa`**:
   - Po `api_cert_generate` z `recipient_name="X"` → wiersz w `swiadectwa` ma `recipient_name="X"` i `expiry_months_used` = effective wartość.
4. **Autocomplete endpoint**:
   - `?q=A` → empty list (poniżej threshold).
   - `?q=ad` z dwoma poprzednimi wpisami "ADAM&PARTNER" i "ADAM Partner" → zwraca oba (DISTINCT case-insensitive LIKE).
   - `?q=xyz` brak match → empty list.
5. **Archive endpoint + backfill**:
   - `POST /api/cert/variants/<id>/archive` z `{"archived": true}` → 200, wiersz `archived=1`, `backfill_count=0`.
   - `POST .../archive` z `{"archived": true, "backfill_recipient": "ADAM&PARTNER"}` → UPDATE n starych `swiadectwa` z `template_name=<v>` i `recipient_name IS NULL`. Response `backfill_count=n`.
   - Backfill **nie nadpisuje** wierszy gdzie `recipient_name IS NOT NULL` (idempotent).
   - Unarchive (`archived=false`) ignoruje `backfill_recipient` (nie cofa).
   - `api_cert_templates` bez `include_archived` filtruje archived = false; z `include_archived=1` zwraca też archived.
   - `GET /api/cert/variants/<id>/archive-preview` → `{swiadectwa_count, suggested_recipient}`. Label bez em-dasha → `suggested_recipient=""`.

## Build sequence

1. **Schema** — `ALTER TABLE` x3 w `mbr/models.py` (idempotent try/except jak inne migracje). Test: świeża baza + `init_mbr_tables()` + assert kolumny istnieją.
2. **Generator** — `_sanitize_filename_segment`, `_cert_names` z parametrem, `build_context` z expiry override. TDD: testy (1)+(2) najpierw failing, potem implementacja.
3. **Routes** — `api_cert_generate` rozszerzenie + walidacja, `create_swiadectwo` zapis nowych kolumn, `api_cert_recipient_suggestions`, `api_cert_variant_archive`, `api_cert_templates` z `default_expiry_months` + `include_archived`. TDD: testy (3)+(4)+(5).
4. **UI laborant** — przebudowa `issueCert()`/`cv-popup-overlay`/`cv-popup-fields`, autocomplete dropdown, walidacja inline. Manualne testowanie w przeglądarce na przykładowej szarży.
5. **UI admin (cert editor)** — toggle "Pokaż archiwalne", button "Archiwizuj/Przywróć" przy karcie wariantu, info-box. Manualne testowanie.
6. **Manualna migracja** — użytkownik przegląda warianty, archiwizuje per-odbiorca/per-nr_zam te które nie różnią się merytorycznie. Spec tego nie automatyzuje.

## Estimat scope

- 3 ALTER TABLE
- ~5 zmian w `generator.py` (sygnatura `_cert_names`, walidacja w `build_context`, helper sanityzacji)
- ~4 zmian/nowych endpointów w `routes.py`
- ~150 linii JS w modalu laboranta (autocomplete, walidacja, restruktura)
- ~80 linii w `wzory_cert.html` (toggle, button, info-box, opacity)
- ~10 testów

Brak nowych zależności. Brak zmian w DOCX template. Brak zmian w `cert_config.json`.
