# ML Export — Long Format Refactor (PR1)

**Status:** design approved, awaiting plan
**Supersedes:** `docs/superpowers/specs/2026-04-16-ml-export-design.md`
**Follow-up:** `docs/superpowers/todo/2026-04-20-ml-export-parquet.md` (Opcja B)

## Kontekst

Obecny eksport (`mbr/ml_export/query.py`) produkuje jeden szeroki CSV z hardkodowanym schematem (`FIXED_MAX_ROUNDS = {sulfonowanie: 3, utlenienie: 3, standaryzacja: 3, analiza_koncowa: 1}`). Skutek:

- Kolumny per `etap × runda × parametr × korekta` → 60–80 kolumn, z czego typowa szarża wypełnia 20–30%.
- Rundy 2 i 3 są puste dla większości szarż → niepotrzebne NULLe komplikują trening ML.
- Schema jest utrzymywany ręcznie (hardkod) — nowy produkt / nowy etap wymaga edycji kodu.
- Wszystkie wymiary semantyczne (metadata, features, targets, korekty) w jednym CSV.
- Mieszana ścieżka: większość z `ebr_pomiar` (per-session), ale `na2so3_recept_kg` ręcznie doczytywany z `ebr_wyniki` — trudne do generalizacji.

Komentarz w kodzie uzasadnia hardkod stabilnością schematu (konkatenacja historycznych CSV-ek). Long format eliminuje ten problem bez hardkodu.

## Cele (in-scope)

1. Zastąpić wide CSV czterema tidy plikami + `schema.json`, w jednym zipie.
2. Usunąć `FIXED_MAX_ROUNDS` i wszystkie hardkodowane prefiksy / skróty (`_STAGE_PREFIX`, `_PARAM_SHORT`, `_KOREKTA_SHORT`, `_FORMULA_DRIVEN`).
3. Zachować kompatybilność z pojedynczym pobraniem z UI admina — jeden przycisk, jeden plik (zip).
4. Scalić dane z `ebr_wyniki` (legacy) i `ebr_pomiar` (new session-based) w jednym `measurements.csv`, z flagą `is_legacy`.
5. W `schema.json` zapisać słownik parametrów (jednostki, precision, formuła dla obliczeniowych, per-stage specs) tak, by data scientist nie musiał sięgać po ani jedno SQL query.

## Nie w zakresie (out-of-scope)

- Parquet, kompresja, wersjonowanie semver, rejestr eksportów w DB — Opcja B.
- Multi-produkt export z parametrem URL — kod ma być **gotowy** do wielu produktów (brak hardkodu produktu w strukturach danych), ale endpoint eksponuje tylko K7.
- Inkrementalny eksport (`after_id`) — w obecnym endpointzie jest, ale nikt go nie używa; rezygnujemy, zip zawsze pełny.
- Side-effect persistence (audit log, rejestr pobrań).

## Decyzje zatwierdzone

| # | Decyzja | Wybór |
|---|---------|-------|
| 1 | Zakres produktów | **1a** — tylko K7 w endpoint, ale kod bez hardkodu produktu (lista produktów jako argument funkcji) |
| 2 | Legacy `ebr_wyniki` | **2b** — scalać z `ebr_pomiar` w `measurements.csv` z `runda=0` i `is_legacy=1` |
| 3 | Stary endpoint `.csv` | **3a** — zastąpić (breaking change, nikt inny tego nie używa) |

## Design

### Endpoint

```
GET /api/export/ml/k7.zip?include_failed=0|1
Auth: @role_required("admin")
Response: application/zip, filename=k7_ml_export_YYYY-MM-DD.zip
```

`include_failed=1` dodaje szarże `status='cancelled'` (negatywne przykłady do trenowania klasyfikatora off-spec). Domyślnie `0` (tylko `completed`).

Stary `GET /api/export/ml/k7.csv` **usunięty** — zwraca 404.

### Zawartość zipa

```
k7_ml_export_2026-04-20.zip
├── batches.csv
├── sessions.csv
├── measurements.csv
├── corrections.csv
├── schema.json
└── README.md    # krótki opis formatu + przykład użycia w pandas
```

### `batches.csv` — 1 wiersz / szarża

| kolumna | typ | źródło | uwaga |
|---|---|---|---|
| `ebr_id` | int | `ebr_batches.ebr_id` | PK |
| `batch_id` | str | `ebr_batches.batch_id` | |
| `nr_partii` | str | `ebr_batches.nr_partii` | |
| `produkt` | str | `mbr_templates.produkt` | np. `Chegina_K7` |
| `status` | str | `ebr_batches.status` | `completed` \| `cancelled` |
| `masa_kg` | float | `ebr_batches.wielkosc_szarzy_kg` lub `nastaw` | |
| `meff_kg` | float | computed | `masa - 1000 if masa > 6600 else masa - 500` |
| `dt_start` | str | `ebr_batches.dt_start` | ISO 8601 |
| `dt_end` | str | `ebr_batches.dt_end` | ISO 8601 (null jeśli szarża nieukończona) |
| `pakowanie` | str | `ebr_batches.pakowanie_bezposrednie` lub `"zbiornik"` | |
| `target_ph` | float | `ebr_etap_sesja.cele_json` standaryzacji, fallback `korekta_cele` | |
| `target_nd20` | float | j.w. | |

### `sessions.csv` — 1 wiersz / (szarża, etap, runda)

| kolumna | typ | źródło |
|---|---|---|
| `ebr_id` | int | FK → `batches` |
| `etap` | str | `etapy_analityczne.kod` |
| `runda` | int | `ebr_etap_sesja.runda` (≥ 1) |
| `dt_start` | str | `ebr_etap_sesja.dt_start` |
| `laborant` | str | `ebr_etap_sesja.laborant` |

Nie zawiera sesji z `runda=0` (legacy nie ma sesji, tylko `measurements.csv` ma flagę legacy).

### `measurements.csv` — 1 wiersz / (szarża, etap, runda, parametr)

| kolumna | typ | źródło | uwaga |
|---|---|---|---|
| `ebr_id` | int | FK | |
| `etap` | str | `etapy_analityczne.kod` / mapowanie z `ebr_wyniki.sekcja` | |
| `runda` | int | `ebr_etap_sesja.runda` albo `0` dla legacy | |
| `param_kod` | str | `parametry_analityczne.kod` | |
| `wartosc` | float | `ebr_pomiar.wartosc` lub `ebr_wyniki.wartosc` | może być null gdy tylko `wartosc_text` |
| `wartosc_text` | str | `ebr_wyniki.wartosc_text` | np. `"<1"` dla FAU poniżej LOD |
| `w_limicie` | int | `ebr_pomiar.w_limicie` lub `ebr_wyniki.w_limicie` | 0/1/null |
| `dt_wpisu` | str | `ebr_pomiar.dt_wpisu` lub `ebr_wyniki.dt_wpisu` | |
| `wpisal` | str | j.w. | |
| `is_legacy` | int | 1 gdy źródło = `ebr_wyniki` i nie ma odpowiadającej sesji; 0 w przeciwnym razie | |

**Zasada scalania:**
1. Dla każdej szarży czytamy wszystkie `ebr_pomiar` przez `ebr_etap_sesja` → `is_legacy=0`, `runda ≥ 1`.
2. Czytamy wszystkie `ebr_wyniki` dla tej szarży. Mapujemy `sekcja` → `etap` (trivialnie, te same kody).
3. Dla każdego wiersza `(ebr_id, etap, param_kod)` z `ebr_wyniki`:
   - Jeśli istnieje **jakikolwiek** wiersz w `ebr_pomiar` dla tej samej trójki `(ebr_id, etap, param_kod)` (niezależnie od rundy) → traktujemy legacy jako szum historyczny i **nie emitujemy** (nowe dane są autorytatywne).
   - W przeciwnym razie → emitujemy z `runda=0`, `is_legacy=1`.
4. Wyjątek: `na2so3_recept_kg` (recepta, nie pomiar) zawsze wchodzi z `ebr_wyniki` jako `runda=0, is_legacy=1`, nawet gdy istnieje wiersz `ebr_pomiar` — reguła z p. 3 go nie dotyczy. W `schema.json` oznaczony `kategoria: "recipe"` (ML wie, że to feature receptury, nie wynik).

### `corrections.csv` — 1 wiersz / (szarża, etap, runda, substancja)

| kolumna | typ | źródło |
|---|---|---|
| `ebr_id` | int | FK |
| `etap` | str | `etapy_analityczne.kod` |
| `runda` | int | `ebr_etap_sesja.runda` |
| `substancja` | str | `etap_korekty_katalog.substancja` |
| `kg` | float | `ebr_korekta_v2.ilosc` |
| `sugest_kg` | float | `ebr_korekta_v2.ilosc_wyliczona` (null gdy brak formuły) |
| `status` | str | `ebr_korekta_v2.status` (`wykonana` \| `zalecona` \| `anulowana`) |
| `zalecil` | str | `ebr_korekta_v2.zalecil` |
| `dt_wykonania` | str | `ebr_korekta_v2.dt_wykonania` |

Zawieramy **wszystkie** statusy — `status` jest kolumną, klient filtruje. `anulowana` może mieć wartość edukacyjną dla modelu „co operator chciał ale wycofał".

### `schema.json`

```json
{
  "export_version": "1.0",
  "generated_at": "2026-04-20T14:32:00Z",
  "produkt_filter": ["Chegina_K7"],
  "counts": {
    "batches": 21,
    "sessions": 54,
    "measurements": 118,
    "corrections": 47
  },
  "etapy": [
    {"kod": "sulfonowanie", "kolejnosc": 1, "label": "Sulfonowanie"},
    {"kod": "utlenienie", "kolejnosc": 2, "label": "Utlenienie"},
    {"kod": "standaryzacja", "kolejnosc": 3, "label": "Standaryzacja"},
    {"kod": "analiza_koncowa", "kolejnosc": 4, "label": "Analiza końcowa"}
  ],
  "parametry": {
    "barwa_I2": {
      "kod": "barwa_I2",
      "label": "Barwa jodowa",
      "skrot": "Barwa I₂",
      "jednostka": null,
      "precision": 2,
      "kategoria": "measurement",
      "typ_pomiaru": "bezp",
      "is_calculated": false,
      "formula": null,
      "is_target_candidate": true,
      "specs_per_etap": {
        "analiza_koncowa": {"min": 0.0, "max": 200.0}
      }
    },
    "sa": {
      "kod": "sa",
      "label": "Substancja aktywna",
      "jednostka": "%",
      "precision": 1,
      "kategoria": "measurement",
      "typ_pomiaru": "obliczeniowy",
      "is_calculated": true,
      "formula": "sm - nacl - 0.6",
      "is_target_candidate": true,
      "specs_per_etap": {
        "analiza_koncowa": {"min": 30.0, "max": 42.0},
        "standaryzacja":   {"min": 30.0, "max": 42.0}
      }
    },
    "na2so3_recept_kg": {
      "kod": "na2so3_recept_kg",
      "label": "Siarczyn sodu — dawka z receptury",
      "jednostka": "kg",
      "kategoria": "recipe",
      "is_calculated": false,
      "is_target_candidate": false
    }
  },
  "substancje_korekcji": {
    "Perhydrol 34%": {"is_formula_driven": true},
    "Woda łącznie":  {"is_formula_driven": true, "aliases": ["Woda"]},
    "Kwas cytrynowy":{"is_formula_driven": true},
    "Siarczyn sodu": {"is_formula_driven": false},
    "NaCl":          {"is_formula_driven": false}
  }
}
```

**Pola wyprowadzane automatycznie (nie hardkod schematu):**
- `parametry` — z `parametry_analityczne` + `produkt_etap_limity` (per-stage specs) + `mbr_templates.parametry_lab` (dla `typ_pomiaru` i `formula`).
- `is_target_candidate` — `true` gdy parametr pojawia się w etapie `analiza_koncowa` w `mbr_templates.parametry_lab` z ustawionym `min_limit` lub `max_limit` (niezależnie od `is_calculated`, więc `sa` też wchodzi).
- `kategoria` — `"recipe"` dla zamkniętej whitelisty `{"na2so3_recept_kg"}` zdefiniowanej stałą w `schema.py`; `"measurement"` dla reszty. Whitelistę rozszerzamy gdy dojdą kolejne pola receptury. `parametry_analityczne.grupa` nie jest używana jako źródło (dziś wartości tam to głównie `"lab"` — niedostatecznie rozdzielająca).
- `substancje_korekcji.is_formula_driven` — `true` gdy w `etap_korekty_katalog.formula_ilosc` dla tej `substancja` istnieje niepusty/non-null string **lub** gdy jakikolwiek `ebr_korekta_v2` ma dla niej niepuste `ilosc_wyliczona`.

### `README.md` w zipie

Krótki (≤ 40 linii): opis każdego pliku, przykład pandas joinu na batches + pivot do wide:

```python
import pandas as pd
m = pd.read_csv("measurements.csv")
b = pd.read_csv("batches.csv")
df = m.merge(b, on="ebr_id")

# wide per (batch, stage, round) dla pojedynczego parametru:
wide = df[df.param_kod=="barwa_I2"].pivot_table(
    index="ebr_id", columns=["etap","runda"], values="wartosc"
)
```

### UI: strona `/ml-export`

Obecna strona pokazuje przewijaną tabelę z szeroką strukturą. Po zmianie nie ma sensu pokazywać jednej tabeli (cztery).

**Nowy układ** (ten sam szablon, minimalna przebudowa):
- Nagłówek: „ML Export — K7 Pipeline", jeden przycisk „Pobierz paczkę (.zip)".
- Checkbox „Włącz szarże anulowane" (steruje `include_failed`).
- Cztery karty/panele pod sobą:
  - `batches.csv` — liczba wierszy + preview 5 pierwszych
  - `sessions.csv` — j.w.
  - `measurements.csv` — j.w.
  - `corrections.csv` — j.w.
- Link „Schemat danych (JSON)" otwiera `schema.json` inline (pretty-printed, collapsible).

Preview: prosta tabela HTML z nagłówkami z CSV. Bez grupowania kolumn (żadnej logiki per-etap), bez paginacji wewnątrz panelu (tylko pierwsze 5 wierszy).

### Inline edit (admin)

Admin może edytować wartości w widoku podglądu/szczegółów dla wszystkich 4 tabel: batches, sessions, measurements, corrections.

**Wzorzec wyszukiwania P3:** Admin wpisuje `nr_partii` w polu tekstowym; backend zwraca pełny edytowalny szczegół tej jednej szarży (wszystkie powiązane sessions, measurements, corrections). Admin edytuje wartości inline; zapis po utracie fokusu (save-on-blur) przez endpoint PUT.

**Pola edytowalne per tabela:**
- **batches**: `masa_kg` (= `wielkosc_szarzy_kg`), `dt_start`, `dt_end`, `status`, `pakowanie_bezposrednie`, `nastaw`. Nieedytowalne: `ebr_id`, `batch_id`, `nr_partii`, `mbr_id` (klucze złożone / identyfikatory).
- **sessions**: `dt_start`, `laborant`. Nieedytowalne: `ebr_id`, `etap_id`, `runda`, `id`.
- **measurements**: `wartosc`, `wartosc_text`, `w_limicie`. Nieedytowalne: `ebr_id`, `kod_parametru`, `sekcja`/`etap`, `runda`, source ID.
- **corrections**: `kg`, `status`, `dt_wykonania`. Nieedytowalne: `ebr_id`, `etap`, `runda`, `substancja`, id.

**Endpointy (rola=admin):**
- `GET /api/ml-export/batch-detail?nr_partii=<str>` — zwraca `{batch: {...}, sessions: [...], measurements: [...], corrections: [...]}` dla jednej szarży.
- `PUT /api/ml-export/batch/<ebr_id>` — body: `{field: value, ...}` (tylko edytowalne pola). 400 dla nieedytowalnego pola.
- `PUT /api/ml-export/session/<sesja_id>` — body: analogiczny wzorzec.
- `PUT /api/ml-export/measurement/<source>/<id>` — `source: "pomiar" | "wyniki"`, `id: ebr_pomiar.id | ebr_wyniki.wynik_id`. Body: `{wartosc?, wartosc_text?, w_limicie?}`.
- `PUT /api/ml-export/correction/<korekta_id>` — body: `{kg?, status?, dt_wykonania?}`.

Każdy PUT emituje zdarzenie audytu `ml_export.value_edited` z payloadem `{table, id, field, old_value, new_value, batch_ebr_id}` przez istniejący `audit.log_event`.

Wszystkie endpointy zwracają `{ok: true, new_value: <updated>}` przy sukcesie; `400` przy błędzie walidacji (nieznane pole, poza zakresem, niezgodność typów); `404` gdy wiersz nie istnieje; `403` gdy nie admin.

### Diagnostyka — buffer capacity

Nowa sekcja na stronie `/ml-export` (osobna, poniżej podglądu i poniżej sekcji inline edit): „Diagnostyka modelu kwasu — K7".

Pokazuje trzy widoki diagnostyczne oraz statystyki podsumowujące w jednym zwartym panelu:

1. **Szereg czasowy**: X = `dt_start` per szarża (posortowane), Y = buffer_cap (kg/t/ΔpH). Dwie linie: `actual` (z `acid_kg / tons / delta_ph` dla ukończonych szarż) oraz `predicted` (wsteczne: ponowne uruchomienie formuły `_acidModelPredict` z `mbr/templates/laborant/_correction_panel.html:446` w Pythonie na historycznych danych wejściowych szarży).
2. **Scatter**: X = actual buffer_cap, Y = predicted. Linia diagonalna y=x dla odniesienia.
3. **Histogram residuałów**: `predicted - actual`. Pokazuje bias i rozrzut.

**Karta statystyk podsumowujących:** `n=<count>`, `MAE=<kg/t/ΔpH>`, `MAPE=<%>`, `mean_bias=<+/->`, `stdev=<>`.

**Endpoint:** `GET /api/ml-export/buffer-cap-chart?produkt=Chegina_K7` — zwraca `{stats: {...}, chart_png_b64: "<base64>"}`. Chart to jeden PNG z 3 subplotami + statystyki jako tekst przez matplotlib (wzorzec zgodny z istniejącym `acid_model.py` make_plots).

**Rola:** admin.

**Wyłącza** szarże gdzie `delta_ph <= 0.5`, `acid_kg <= 0`, lub `ph_before < 9` (ten sam filtr co acid_model.py).

## Implementacja

### Struktura plików

```
mbr/ml_export/
  __init__.py         # bp rejestracja, bez zmian
  query.py            # PRZEPISANY — patrz niżej
  routes.py           # PRZEPISANY — nowe endpointy
  schema.py           # NOWY — budowa schema.json ze słownika parametrów
```

### `query.py` — funkcje publiczne

```python
def export_ml_package(
    db: sqlite3.Connection,
    produkty: list[str] = ["Chegina_K7"],
    statuses: tuple = ("completed",),
) -> bytes:
    """Zwraca bytes zipa z batches.csv, sessions.csv, measurements.csv,
    corrections.csv, schema.json, README.md."""

def build_batches(db, produkty, statuses) -> list[dict]
def build_sessions(db, ebr_ids) -> list[dict]
def build_measurements(db, ebr_ids) -> list[dict]    # scala ebr_pomiar + ebr_wyniki legacy
def build_corrections(db, ebr_ids) -> list[dict]
```

Wszystkie `build_*` zwracają listy słowników o stałych kluczach — to te klucze stają się nagłówkami CSV. Test może porównać zestaw kluczy do stałej, żeby złapać niezamierzone zmiany schematu.

### `schema.py` — budowa słownika

```python
def build_schema(
    db: sqlite3.Connection,
    produkty: list[str],
    counts: dict[str, int],
) -> dict:
    """Buduje strukturę schema.json z parametry_analityczne, produkt_etap_limity,
    mbr_templates.parametry_lab i etap_korekty_katalog."""
```

### `routes.py`

```python
@ml_export_bp.route("/api/export/ml/k7.zip")
@role_required("admin")
def export_k7_zip():
    include_failed = request.args.get("include_failed", "0") in ("1","true","yes")
    statuses = ("completed","cancelled") if include_failed else ("completed",)
    db = get_db()
    try:
        blob = export_ml_package(db, produkty=["Chegina_K7"], statuses=statuses)
    finally:
        db.close()
    resp = Response(blob, mimetype="application/zip")
    resp.headers["Content-Disposition"] = \
        f"attachment; filename=k7_ml_export_{today}.zip"
    return resp

@ml_export_bp.route("/ml-export")
@role_required("admin")
def ml_export_page():
    # buduje po jednej liście per-table z limit 5, renderuje ml_export.html
```

Stary `export_k7_csv` i cała logika `build_columns`/`FIXED_MAX_ROUNDS`/`_PARAM_SHORT` itd. — usunięte.

### Zmiany w template

`mbr/templates/ml_export/ml_export.html` — przepisany, czterokolumnowy preview. Żadnych zmian w innych szablonach.

## Testy

Plik: `tests/test_ml_export.py` (istnieje? dopisać jeśli jest; w przeciwnym razie nowy).

Zakres:
1. **Pusta baza K7** — zip zawiera wszystkie 5 plików + README; CSV-y mają nagłówki, 0 wierszy; `schema.json` ma `counts = 0 0 0 0`.
2. **1 szarża K7, 1 sesja sulfonowania, 1 pomiar `ph_10proc`** — 1 wiersz w batches, 1 w sessions, 1 w measurements, 0 w corrections.
3. **Szarża z legacy `ebr_wyniki` tylko** — `measurements.csv` ma wiersze z `runda=0`, `is_legacy=1`. `sessions.csv` pusty.
4. **Szarża z legacy + new** dla tego samego `(etap, param)` — emituje się tylko new, legacy pominięte (reguła scalania).
5. **`na2so3_recept_kg`** — zawsze emitowane z `runda=0`, schema oznacza `kategoria="recipe"`.
6. **`sa` (calculated)** — emitowane jako pomiar, `schema.parametry.sa.is_calculated=true`, `formula="sm - nacl - 0.6"`.
7. **Status filter** — `include_failed=0` pomija `cancelled`; `=1` zawiera.
8. **Korekta `anulowana`** — emitowana, `status="anulowana"`, klient filtruje.
9. **Target snapshot vs fallback** — sesja ze `cele_json` ma `target_ph` z snapshotu; bez niego fallback do `korekta_cele`.
10. **Pandas pivot round-trip** — test bierze zip, czyta CSV, robi pivot `measurements` × `param_kod=barwa_I2`, asercja że liczba kolumn = liczba unikalnych `(etap, runda)`.
11. **Brak hardkodu produktu w strukturach** — `export_ml_package(db, produkty=["Chegina_K7B"])` działa bez modyfikacji kodu (może zwrócić 0 szarż, ale nie wyrzuca).
12. **Stary endpoint zwraca 404** — `GET /api/export/ml/k7.csv` → 404.

## Ścieżka wdrożenia

1. Zaimplementuj `schema.py`, potem `query.py` (nowe build funkcje), potem `routes.py`.
2. Usuń stary kod dopiero po tym, jak testy nowego przechodzą.
3. Przepisz template preview.
4. Uruchom cały suite `pytest` — schemat/tabele nie zmieniają się, więc tylko testy ml_export mogą się ruszyć.
5. Lokalnie sprawdź endpoint na prawdziwej bazie, porównaj liczby szarż/pomiarów z obecnym eksportem (sanity check).

Brak zmian DB, brak migracji. Rollback = git revert.

## Ryzyka i kontrolki

- **Ryzyko:** „utrata" wiersza legacy, jeśli reguła scalania źle zakwalifikuje. Mitygacja: test 4 + ręczny sanity check na K7 po wdrożeniu (porównanie liczby wierszy measurements z sumą `ebr_pomiar` + `ebr_wyniki` po odfiltrowaniu duplikatów).
- **Ryzyko:** ktoś używa `/api/export/ml/k7.csv` w skrypcie. Mitygacja: user potwierdził breaking change (decyzja 3a). Grep repo przed usunięciem, zostaw notkę w commit message.
- **Ryzyko:** `schema.json` może rozjechać się z faktycznymi kolumnami CSV, jeśli ktoś dopisze pole. Mitygacja: test porównujący klucze `build_*` ze słownikiem opisów w `schema.json` (jeśli jest).

## Co dalej (Opcja B)

Zapisane w `docs/superpowers/todo/2026-04-20-ml-export-parquet.md`. Streszczenie:
- Parquet zamiast CSV (pyarrow), ~5–10× mniejsze, typy zachowane.
- Wersjonowanie: `schema_version` (semver), nazwy plików `k7_ml_v<data>_<schema>.zip`.
- Tabela `ml_exports` w DB (rejestr pobrań: kto, kiedy, hash).
- Endpoint `/api/export/ml/history`.
- Integracja z DVC/MLflow (dokumentacja, nie kod).

Trigger: pierwszy wytrenowany model produkcyjny, albo paczka CSV > 5 MB.
