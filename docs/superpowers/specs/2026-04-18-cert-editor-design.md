# Edytor świadectw — dopięcie do stanu produkcyjnego

**Data:** 2026-04-18
**Autor:** Karol Tabaka (brainstorm z Claude)
**Zakres:** edytor szablonów świadectw pod `/admin/wzory-cert` — domknięcie luk UX + poszerzenie tabeli + kopiowanie wzoru + globalne ustawienia typografii

## Cel

Edytor działa dziś, ale ma luki, które przeszkadzają we wdrożeniu produkcyjnym. Ta zmiana zamyka je w jednym przebiegu tak, żeby można było przejąć system jako podstawowe narzędzie do zarządzania wzorami świadectw jakości.

Kierunek: **jakość operatora** — edytor ma być wygodny, nie gubić zmian, dobrze komunikować błędy, pozwalać kopiować istniejące wzory, a wygenerowane PDF-y mają być ładne w skrajnych przypadkach (długie nazwy jak "kokamidoamidoamin").

## Pain pointy (ze stanu obecnego)

1. **Brak kopiowania wzoru.** Produkty typu K40GLOL i GLOL40 (ten sam produkt, różni klienci) wymagają pełnej ręcznej rekonfiguracji.
2. **Dropdown parametrów za wąski.** `/api/parametry/available` filtruje po MBR `analiza_koncowa`, przez co nie da się dodać na świadectwo parametrów opisowych (zapach, wygląd, kolor) ani parametrów mierzonych przez zewnętrzne laboratorium.
3. **Długie nazwy parametrów zawijają się brzydko w PDF.** Przykład: "kokamidoamidoamin".
4. **Brak kontroli nad typografią.** Font jest zaszyty w template (TeX Gyre Bonum), rozmiar nagłówka jest stały, brak admin UI.
5. **Brak wskaźnika niezapisanych zmian.** Można zgubić edycję przez przełączenie zakładki/zamknięcie karty.
6. **Walidacja tylko server-side.** Duplikat id lub pusta nazwa wychodzą dopiero po kliknięciu "Zapisz".
7. **Brak widoku historii zmian w edytorze.** Audit event `CERT_CONFIG_UPDATED` jest logowany, ale niewidoczny dla operatora.
8. **Podgląd PDF tylko ręcznie** — nawet przy drobnej zmianie trzeba klikać "Odśwież".

## Rozwiązanie w skrócie

- **Poszerzenie tabeli** w DOCX: marginesy 20→13 mm, kolumna nazwy 79→~94 mm.
- **Ręczne łamanie** w nazwie parametru przez znak `|` → `<w:br/>`.
- **Globalne ustawienia typografii** w nowej tabeli `cert_settings` (font family, rozmiar nagłówka nazwy produktu) sterowane z admin panelu. Marginesy i szerokość kolumny nazwy to **jednorazowa poprawka geometrii** w samym DOCX (nie dynamiczna — tej skali zmiana nie jest potrzebna runtime-owo).
- **Font**: rodzina bookman-like z Google Fonts (wybór z próbek na etapie implementacji), domyślny fallback TeX Gyre Bonum (to co dziś).
- **Kopiowanie**: endpoint `POST /api/cert/config/product/<src>/copy` robiący głęboką kopię parametrów i bazowego wariantu; nowa meta wpisywana od zera.
- **Dropdown**: rozluźnienie filtra — pełny rejestr `parametry_analityczne` z flagą `in_mbr`.
- **Edytor UX**: dirty flag, `beforeunload`, walidacja UI-side, czwarta zakładka "Historia", auto-refresh podglądu.

## Niezmienne założenia (ryzyka odrzucone)

- **Archiwum zachowuje swoje dane wejściowe.** `swiadectwa.data_json` trzyma produkt, variant, nr partii, `wyniki_flat`, `extra_fields`, wystawił. **Nie** snapshotuje cert_config z momentu wydania. Regeneracja z `data_json` łączy te dane wejściowe z **bieżącym** cert_config i **bieżącym** template. Jeśli od wydania zmienił się cert_config (dodano/usunięto parametr) lub template-u (geometria, font), regenerowany PDF może różnić się layoutem i listą wierszy od oryginału. To jest **świadoma decyzja** — regeneracja jest rzadkim corner case-em awaryjnym, nie governance contract. Dodanie snapshotowania `cert_config` do `data_json` byłoby rozszerzeniem zakresu; odłożone.
- **Walidacja server-side zostaje** — UI-side validation to wygoda, a nie zabezpieczenie.
- **Obsługa paliwowych template'ów (`paliwo_master*.docx`) jest poza zakresem** tej zmiany.

---

## Model danych

### Zmiana 1: rozluźnienie filtra dropdown — bez zmiany schematu

`parametry_cert.parametr_id` zostaje NOT NULL. Wszystkie parametry idące na świadectwo muszą być w `parametry_analityczne` (rejestr SSOT parametrów). Rozluźniamy tylko filtr odczytu — endpoint `/api/parametry/available` przestaje przycinać do MBR-owego `analiza_koncowa`.

Parametry opisowe (zapach, wygląd, kolor) korzystają z istniejącego `parametry_cert.qualitative_result` — przy renderze fiksowana wartość zastępuje wynik pomiaru.

Parametry external-lab: wartość pozostaje do wprowadzenia przy generowaniu świadectwa przez `extra_fields` (już istnieje w `/api/cert/generate`).

### Zmiana 2: nowa tabela `cert_settings`

```sql
CREATE TABLE IF NOT EXISTS cert_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

Domyślne wiersze (seed przy `init_mbr_tables`):

| key | value | uwagi |
|---|---|---|
| `body_font_family` | `TeX Gyre Bonum` | zachowujemy zachowanie sprzed zmiany — to jest to, co działa dziś |
| `header_font_size_pt` | `14` | wartość wyjściowa zmierzona z obecnego template-u jako pierwszy krok implementacji i zapisana tu; jeśli pomiar pokaże inną wartość, startujemy od niej |

Tylko dwa klucze — bo tylko te dwie rzeczy user chce regulować runtime-owo. Margines strony i szerokość kolumny nazwy są zapisane bezpośrednio w DOCX (jednorazowa zmiana geometrii, patrz sekcja "Szablon DOCX").

Dlaczego osobna tabela, a nie klucze w istniejącej konfiguracji: trzymanie settingów specyficznych dla cert w dedykowanej tabeli:

- jest odkrywalne (kto szuka konfiguracji świadectw, nie zgaduje po kluczach),
- ma wąski RBAC (`admin` + `kj`),
- pozwala bez ryzyka na dedicated audit event (`CERT_SETTINGS_UPDATED`).

### Zmiana 3: nowy event audit

`EVENT_CERT_SETTINGS_UPDATED` w `mbr/shared/audit.py`. Logowany po każdym udanym `PUT /api/cert/settings`. Payload: zmienione klucze z wartością (diff vs poprzedni stan nie jest wymagany — admin panel ma jedno pole na klucz).

### Czego NIE zmieniamy

- `cert_variants`, `swiadectwa`, `produkty` — bez zmian schematu.
- `cert_config.json` (SSOT export) — regenerowany po PUT/copy jak dziś.
- Mechanizm variantów, `remove_parameters`, `add_parameters`, kaskadowe usuwanie base param — bez zmian.

---

## Szablon DOCX (`mbr/templates/cert_master_template.docx`)

### Geometria (jednorazowa zmiana w pliku DOCX)

| Element | Dziś | Docelowo |
|---|---|---|
| Margines lewy/prawy | 20 mm (1134 dxa) | **13 mm (737 dxa)** |
| Margines góra/dół | 17 mm | bez zmian |
| Szerokość tabeli | 171 mm | **~184 mm** |
| Kol. Nazwa | 79 mm (46%) | **~94 mm (51%)** |
| Kol. Wymaganie | 38 mm (22%) | 38 mm (21%) |
| Kol. Wynik | 35 mm (21%) | 35 mm (19%) |
| Kol. Metoda | 19 mm (11%) | **17 mm (9%)** |

Zmiana jest jednorazowa i commitowana w pliku DOCX. Implementacja: unzip → edit `word/document.xml` (`w:pgMar`, `w:tblW`, `w:gridCol` oraz `w:tcW` w wierszach nagłówka i wierszach danych tabeli — trzeba zaktualizować wszystkie wystąpienia, a nie tylko gridCol) → repack. Nie ma migracji DB. Wartości są teraz w geometrii pliku, nie w `cert_settings`.

### Typografia przez context

`generator.py::build_context()` i `build_preview_context()` ładują `cert_settings` raz na render i wstawiają do context'u:

```python
ctx["header_font_size_pt"] = settings["header_font_size_pt"]
ctx["body_font_family"]    = settings["body_font_family"]
```

Template używa tych zmiennych w odpowiednich miejscach (właściwość rozmiaru fontu nagłówka w `w:sz`, rodzina fontu w stylach XML).

### Ręczne łamanie `|` → `<w:br/>`

W `build_context`/`build_preview_context` każde wystąpienie `|` w `name_pl`/`name_en` konwertowane jest na RichText break (analogicznie do istniejącej konwersji super/sub-script z commit 1b521bb). Operator ustawia "kokamido|amidoamin" w edytorze — renderuje się w dwóch liniach.

### Google Fonts w Gotenberg

Gotenberg pobiera font z CSS podczas renderowania. Wymaga internetu w kontenerze. **Plan B (offline)**: bundlujemy `.ttf` jako volume mount w `deploy/gotenberg.service`. Decyzja podejmowana przy kroku 3 implementacji po weryfikacji środowiska prod.

Defaultem zostaje TeX Gyre Bonum — istniejący, offline-friendly, działa dziś.

---

## API

### Nowe endpointy

```
POST /api/cert/config/product/<src_key>/copy
Body: { "new_display_name": "GLOL40" }
Auth: admin, kj
Response: { "ok": true, "key": "GLOL40" } | 400 | 409 | 404
```

Walidacja: unikalność wygenerowanego klucza (taki sam regex jak w `create_product`), nazwa nie pusta. Transakcja:

1. SELECT meta + parametry bazowe ze źródła.
2. INSERT do `produkty` (display_name = new, reszta domyślna jak w nowym produkcie — user uzupełnia po utworzeniu).
3. INSERT do `cert_variants` — tylko base, label = new display_name.
4. INSERT do `parametry_cert` — wszystkie parametry bazowe źródła (`variant_id = NULL`), zachowana `kolejnosc`.
5. `save_cert_config_export()`.
6. `audit.log_event(CERT_CONFIG_UPDATED, entity_label=new_key, payload={"copied_from": src_key})`.

**Warianty nie są kopiowane.** Warianty dotyczą klientów — `base` dla nowego produktu tworzymy pusty.

```
GET  /api/cert/settings
Auth: admin, kj
Response: { "body_font_family": ..., "header_font_size_pt": ..., "page_margin_mm": ..., "name_column_width_mm": ... }
```

```
PUT /api/cert/settings
Auth: admin, kj
Body: { ...klucze do aktualizacji... }
Response: { "ok": true }
```

UPSERT do `cert_settings`, po zapisie `audit.log_event(CERT_SETTINGS_UPDATED, payload=updated_keys)`.

```
GET /api/cert/config/product/<key>/audit-history
Auth: admin, kj
Response: { "history": [ { "dt": ..., "actor": ..., "payload": {...} }, ... ] }
```

Używa `audit.query_audit_history_for_entity` lub siostrzanego helpera filtrującego po `entity_label = key` (trzeba sprawdzić czy istniejący helper to umie — jeśli nie, dodajemy `query_audit_history_by_label`).

### Zmienione endpointy

**`/api/parametry/available?produkt=...`** — dziś zwraca przycięte do MBR `analiza_koncowa`. Zmiana:

```json
{
  "params": [
    { "kod": "...", "label": "...", "name_en": "...", "method_code": "...", "precision": 2, "in_mbr": true },
    { "kod": "...", "label": "...", "name_en": "...", "method_code": "...", "precision": null, "in_mbr": false }
  ]
}
```

Flag `no_mbr: true` (dla produktów bez aktywnego MBR) zachowany — ale lista jest pełna, po prostu wszystkie `in_mbr: false`.

### Bez zmian

- `PUT /api/cert/config/product/<key>` — walidacja + atomic write.
- `POST /api/cert/config/preview` — czyta `cert_settings` przez generator.
- `POST /api/cert/generate`, `/api/cert/<id>/pdf`, `/api/cert/<id>` (DELETE), `/api/cert/list`, `/api/cert/<id>/audit-history` — bez zmian.

---

## Edytor UI (`mbr/templates/admin/wzory_cert.html`)

### Lista produktów

Nowy przycisk **"Kopiuj"** obok "Usuń" na każdej karcie produktu. Kliknięcie → modal z polem "Nazwa nowego produktu" (walidacja: dozwolone znaki, unikalność). Po zatwierdzeniu → POST do `/copy` → flash "Skopiowano" + powrót do listy.

### Edytor — dirty state

- **Gwiazdka `*`** obok `#ed-title` gdy są niezapisane zmiany.
- Dirty flag ustawiany przez delegated listener na `change`/`input` w całym edytorze (tabela parametrów, warianty, meta) + przez `addParameter`, `removeBaseParam`, `addVariant`, `removeCurrentVariant`, `addVariantParam`.
- **`beforeunload`** zwraca warning string jeśli dirty.
- **"← Powrót do listy"** → confirm "Masz niezapisane zmiany. Porzucić?" jeśli dirty.
- Przycisk **"Zapisz"**: teal (primary) gdy dirty, wygaszony gdy clean.
- Po udanym zapisie → dirty = false, status "Zapisano" (jak dziś).

### Edytor — walidacja UI-side

Przed POST-em `collectEditorState()` robi lokalny preflight. Jeśli nie przejdzie — nie wysyłamy PUT-a.

- **Duplikat id parametru** → podświetl wiersze na czerwono, flash.
- **Pusty `name_pl`** → podświetl, flash.
- **Parametr bez `data_field` i bez `qualitative_result`** → podświetl, flash "Parametr musi mieć pomiar lub stałą wartość".
- **Duplikat id wariantu** → flash.
- **Wariant bez labelu** → flash.
- **Duplikat id w `add_parameters`** → flash.

Server-side validation zostaje jako defence in depth.

### Edytor — zakładka "Historia"

Czwarta zakładka obok Produkt/Parametry/Warianty. Ładowana na żądanie (klik zakładki) przez GET `/api/cert/config/product/<key>/audit-history`.

Kolumny: data (lokalny czas), kto (actor), summary (`params_count` + `variants_count`), ewentualnie `copied_from` jeśli z copy.

Bez rollback — tylko widok.

### Edytor — dropdown parametrów

Opcje grupowane: najpierw "W MBR" (zielona kropka `●` przed kodem), potem "Poza MBR" (szara kropka `○`).

Wybór parametru "poza MBR" nie blokuje zapisu — generuje warning (już jest na backend).

### Podgląd PDF

- Auto-refresh po znaczących zmianach (debounced 800 ms). Trigger: change w parametrach/wariantach/meta/`cert_settings` (jeśli modal otwarty i przełożony do panel ustawień — raczej rzadko w trakcie jednej sesji).
- Przycisk "Odśwież" zostaje jako awaryjny.
- Spinner/licznik w headerze podczas generowania.

### Admin panel (`ustawienia.html`)

Nowa sekcja **"Świadectwa jakości"**:

- Font family — input text (nazwa fontu jak na Google Fonts, np. "EB Garamond", "TeX Gyre Bonum"). Placeholder z przykładem, podpowiedź o źródle.
- Rozmiar nagłówka nazwy produktu — number input, pt (2-50, walidacja).

Przycisk "Zapisz" → PUT `/api/cert/settings` → flash + audit entry.

---

## Testy

Miejsce: `tests/test_certs.py` (istnieje, in-memory SQLite).

### Kopiowanie produktu

- Happy path: kopia zawiera wszystkie parametry w tej samej kolejności, tylko bazowy wariant, świeże meta (`display_name` z requesta, reszta domyślna).
- Source niezmieniony po kopii.
- Duplicate key → 409.
- Invalid znaki w display_name → 400.
- Copy z produktu z wieloma wariantami → warianty dodatkowe NIE są kopiowane.

### Rozszerzony dropdown

- `/api/parametry/available` dla produktu bez MBR zwraca pełny rejestr z `in_mbr: false` (i flag `no_mbr: true`).
- Dla produktu z MBR — poprawne rozróżnienie `in_mbr: true/false`.
- Zapis cert-u z parametrem `in_mbr: false` → warning, nie 400.

### Cert settings

- GET po `init_mbr_tables` zwraca domyślne: `body_font_family = "TeX Gyre Bonum"`, `header_font_size_pt = 14`.
- PUT z `body_font_family = "EB Garamond"` zapisuje, GET odczytuje, historia audit ma wpis.
- `build_context`/`build_preview_context` czyta `cert_settings` i wrzuca do context-u — mock na DB lub integration test.
- PUT z niepoprawnym rozmiarem fontu (np. `header_font_size_pt = 500`) → 400.

### Audit history per produkt

- Po PUT `/api/cert/config/product/<key>` → `audit-history` zwraca wpis z payloadem.
- Po copy → target history ma wpis `copied_from`.

### Ręczne łamanie `|` → `<w:br/>`

- `build_context` konwertuje `name_pl = "kokamido|amidoamin"` na richtext z break-em.
- Test przeciw wygenerowanemu XML (bez Gotenberga — tylko DOCX bytes): zawiera `<w:br/>` wewnątrz komórki nazwy.

### Regeneracja archiwum — invariant kontraktu danych

- Wydaj cert (test fixture na wyniki + extra_fields).
- Zmień cert_config (zmień opinię, header_font_size, geometria).
- Zregeneruj cert po `data_json` (`/api/cert/<id>/pdf`).
- **Weryfikacja**: regeneracja zwraca 200, nie crashuje. `data_json` jest czytane bez modyfikacji — to zachowujemy.

**Nie** oczekujemy pixel-identyczności PDF. Po zmianie cert_config/template layout regenerowanego PDF-u może się różnić od oryginału (patrz Niezmienne założenia). Test pilnuje, że regeneracja **nadal działa** — nie że zwraca identyczny bitstream.

Drugi test — dotyczy wyników, nie config-u:

- Wydaj cert, archiwizuj `wyniki_flat`.
- Po wydaniu zmień `ebr_wyniki` w bazie (symulacja re-measurement).
- Zregeneruj z `data_json`.
- **Weryfikacja**: używa archived `wyniki_flat`, **nie** bieżących z bazy. To twardy invariant — wartości raz wydrukowane na świadectwie nie mogą nigdy zmienić swojej wartości przy regeneracji.

### Manualne (po implementacji)

- Otwieram edytor, zmieniam coś, zamykam tab → ostrzeżenie pojawia się.
- Podgląd PDF z ręcznym łamaniem `|` — wizualnie sprawdzam łamanie.
- Google Fonts w Gotenberg — czy font się ładuje (jeśli nie, fallback na bundled `.ttf`).
- Kopia K40GLOL → GLOL40 — parametry kopiowane, warianty nie, edytor otwiera się od razu na nowym produkcie z poprawnymi meta.

---

## Kolejność budowania

Każdy krok commitowalny niezależnie.

1. **Tabela `cert_settings` + endpointy GET/PUT + integracja w generatorze** — template docelowo czyta `body_font_family` i `header_font_size_pt` z context-u Jinja/docxtpl. Admin UI w `ustawienia.html`.
2. **DOCX template — geometry + parametryzacja typografii** — edycja `word/document.xml` (marginesy 13mm, kolumny 94/38/35/17mm) + podpinamy `{{ body_font_family }}` i `{{ header_font_size_pt }}` w stylach nagłówka i body. Jeden commit = spójna zmiana pliku.
3. **Font — próbki i wybór** — 3-4 warianty z Google Fonts rendered (w tym bieżący TeX Gyre Bonum jako kontrola), decyzja, ustawiamy jako default `body_font_family` w seed-ie `cert_settings`. Jeśli offline Gotenberg → bundle `.ttf` jako volume w `deploy/gotenberg.service`.
4. **Ręczne łamanie `|` → `<w:br/>`** — w `build_context`/`build_preview_context` (analogicznie do konwersji super/sub-script z 1b521bb).
5. **Rozszerzony dropdown** — endpoint `/api/parametry/available`, UI `_codeOptions` z oznaczeniem `in_mbr`.
6. **Kopiowanie produktu** — endpoint + przycisk na karcie + modal.
7. **Dirty state + beforeunload + UI validation** — `wzory_cert.html` JS.
8. **Zakładka Historia** — endpoint + UI.
9. **Auto-refresh podglądu PDF** — debounced 800 ms.

## Ryzyka

- **Gotenberg + Google Fonts offline** — weryfikacja przy kroku 3, fallback bundled `.ttf` w razie potrzeby.
- **Regeneracja wydanych świadectw** po zmianie template-u — layout może być lekko inny, kontrakt danych stabilny. **Nie jest ryzykiem** — jest świadomą decyzją.
- **Kolizje równoległej edycji** — jeden user, single-tab, nie chronimy.

## Poza zakresem

- Rollback do poprzedniej wersji szablonu.
- Diff dwóch wersji szablonu.
- Wersjonowanie `cert_config` (każdy PUT = nowa wersja).
- Spinning `save_cert_config_export()` do background thread.
- Paliwowe templates (`paliwo_master*.docx`).
- Alias / dziedziczenie między produktami.

---

## Kryteria akceptacji ("na gotowo")

- Kopia K40GLOL → GLOL40 działa w ~3 klikach, ostrzega o kolizji, user uzupełnia meta i od razu ma parametry.
- Parametr "zapach" z stałą wartością "charakterystyczny" da się dodać na świadectwo bez edycji MBR.
- "kokamidoamidoamin" mieści się w jednej linii w wygenerowanym PDF; jeśli kiedyś trafi się dłuższa nazwa — operator może wstawić `|` dla ręcznego łamania.
- Admin może zmienić font i rozmiar nagłówka z UI bez dotykania kodu.
- Zmiana w edytorze jest widoczna (gwiazdka), próba utraty — ostrzega, walidacja biegnie lokalnie przed POST-em.
- Zakładka Historia pokazuje kto i kiedy zmienił szablon.
- Podgląd PDF odświeża się sam przy drobnych zmianach.
- Wydane świadectwa regenerują się 1:1 z `data_json` (test zielony).
