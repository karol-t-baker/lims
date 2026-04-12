# Bramki i decyzje w UI — spec

## Problem

Backend pipeline ma bramki (etap_warunki, evaluate_gate) i decyzje (close_sesja z 3 opcjami), ale UI laboranta nie pokazuje wyniku bramki ani nie oferuje przyciskow decyzji. Dual-write juz zwraca `gate` w response save_entry — trzeba to wyswietlic i obsluzyc.

## Cel

Po kazdym auto-save w pipeline etapie, wyswietlic wynik bramki (pass/fail) z odpowiednimi przyciskami decyzji lub panelem korekty.

## Flow

### Gate pass (zielony banner)

Po save, response zawiera `gate.passed === true`:
- Banner: "Warunek spelniony"
- Etapy cykliczne (standaryzacja): przyciski "Przepompuj na zbiornik" + "Mala korekta + przepompuj"
- Etapy jednorazowe (utlenienie): przycisk "Zatwierdz etap"

### Gate fail (czerwony banner + panel korekty)

Po save, response zawiera `gate.passed === false`:
- Banner: "Warunek niespelniony: [lista failures]"
- Automatycznie pod bannerem: panel korekty
  - Lista substancji z `etap_korekty_katalog` (fetch z `/api/pipeline/lab/ebr/<id>/etap/<etap_id>`)
  - Kazda substancja: nazwa, jednostka, wykonawca badge, input na ilosc
  - Przycisk "Zalec korekte" → POST korekty + close_sesja(korekta) → komunikat "Oczekuje na nowa probke"
  - Przycisk "Nowa runda" (pojawia sie po zaleceniu korekty) → POST start_sesja + kopiowanie OK wartosci do nowej rundy + re-render

### Gate brak (etap bez warunkow)

Jesli etap nie ma warunkow bramkowych → gate nie jest zwracany w response → brak bannera, standardowy flow.

## Przyciski decyzji — szczegoly

### Etap jednorazowy (np. utlenienie) — gate pass
- **"Zatwierdz etap →"** → `POST /api/pipeline/lab/ebr/<id>/etap/<etap_id>/close` z `{sesja_id, decyzja: 'przejscie'}` → `showPipelineStage(nastepny_etap)` → aktualizacja flowcharta

### Etap cykliczny (standaryzacja) — gate pass
- **"Przepompuj na zbiornik"** → otwiera istniejacy completion modal (completePompuj / openPumpModal) → standardowy flow zakonczenia szarzy
- **"Mala korekta + przepompuj"** → dialog z polem na uwagi + lista korekt z katalogu (ilosc) → `POST /api/pipeline/lab/ebr/<id>/korekta` (kazda korekta z iloscia) + `POST .../close` z `{decyzja: 'korekta_i_przejscie', komentarz: tekst_uwagi}` → completion modal

### Etap cykliczny — gate fail
- Panel korekty automatycznie
- **"Zalec korekte"** → POST korekty do API + `POST .../close` z `{decyzja: 'korekta'}` → disable inputy, pokaz komunikat
- **"Nowa runda"** (po korekcie) → `POST .../start` → kopiowanie wartosci OK z poprzedniej rundy → re-render sekcji

## Kopiowanie wartosci przy nowej rundzie

Istniejaca logika w `repeatAnalizaCyclic()` kopiuje wartosci w_limicie===1 z ostatniej analizy do nowej sekcji. Ta sama logika dla pipeline:
- Poprzednia runda: `analiza__N` → nowa runda: `analiza__N+1`
- Kopiuj tylko wartosci gdzie `w_limicie === 1`
- Auto-save skopiowane wartosci na serwer

## Pobieranie danych korekty

Lazy fetch — JS pobiera liste korekt z `/api/pipeline/lab/ebr/<id>/etap/<etap_id>` dopiero gdy gate fail. Response zawiera `korekty_katalog` z substancjami, jednostkami, wykonawcami.

## Identyfikacja aktywnego etapu pipeline

JS musi wiedziec ktory `etap_id` i `sesja_id` sa aktywne. Zrodla:
- `etap_id`: z `etapy` array, pole `pipeline_etap_id` dla aktywnego etapu
- `sesja_id`: z response dual-write (dodac do response) LUB fetch z lab API

Zmiana w backendzie: `pipeline_dual_write` zwraca `sesja_id` obok `gate`.

## Zmiany w plikach

### Backend (minimalne)

`mbr/pipeline/adapter.py` — `pipeline_dual_write` zwraca `{gate, sesja_id, etap_id}` zamiast samego gate dict.

`mbr/laborant/routes.py` — `save_entry` przekazuje rozszerzony wynik do response.

### Frontend

`mbr/templates/laborant/_fast_entry_content.html`:
- `renderGateBanner(gateResult)` — renderuje banner pass/fail pod sekcja
- `renderDecisionPipeline(gateResult)` — przyciski decyzji dla pass
- `renderCorrectionPanel(gateResult)` — panel korekty dla fail
- Modyfikacja auto-save handlera — po response z gate, wywolaj renderGateBanner
- `startNewPipelineRound()` — kopiuje OK wartosci, startuje sesje, re-renderuje
- `closePipelineStage(decyzja, komentarz)` — zamyka sesje, przechodzi do nastepnego etapu

`mbr/templates/laborant/szarze_list.html`:
- `renderPipelineFlowchart` — aktualizacja statusow po zatwierdzeniu etapu (juz dziala przez re-render)

## Zakres

### Budujemy
- Gate banner (pass/fail) po auto-save
- Przyciski decyzji per typ etapu
- Panel korekty z substancjami z katalogu
- Nowa runda z kopiowaniem OK wartosci
- Rozszerzenie dual-write response o sesja_id/etap_id

### NIE budujemy
- Formuly obliczania korekt (V2)
- Zmiana completion flow (istniejacy przepompuj dziala)
- UI edycji warunkow bramkowych (juz jest w admin)
