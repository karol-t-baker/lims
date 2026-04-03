# Moduł generowania świadectw — design spec

**Data:** 2026-04-03

## Kontekst

90 wzorów świadectw (.docx) w `docs/swiadectwa/`. Każdy wzór to tabela z parametrami (kolumna "Wynik" pusta) + metadane (partia, daty, TDS). Świadectwa wystawiane dla zakończonych analiz zbiorników. Jedna partia może mieć wiele świadectw (różni klienci).

## Flow

1. Laborant otwiera zakończony zbiornik → widzi przycisk "Wystaw świadectwo"
2. System filtruje wzory po produkcie zbiornika (matchowanie nazwy pliku docx po nazwie produktu)
3. Laborant wybiera wzór z listy (np. "K7 WZÓR", "K7 MB ADAM&PARTNER")
4. System auto-wypełnia:
   - Kolumna "Wynik" — wartości z `ebr_wyniki` używając `CERT_MAPPINGS`
   - Nr partii (Batch)
   - Data produkcji (dt_start)
   - Data ważności (dt_start + 1 rok)
   - Data wystawienia (dziś)
5. Generuje PDF zachowując formatowanie docx
6. Zapisuje PDF: `{rok}/{produkt}/{nazwa_wzoru}_{nr_partii}.pdf`
7. Zwraca PDF do pobrania/wyświetlenia

## Generacja PDF

1. Otwarcie wzoru docx z `docs/swiadectwa/` przez python-docx
2. Wypełnienie kolumny "Wynik" (index 3) w tabeli — wartości z analizy per `CERT_MAPPINGS`
3. Wypełnienie metadanych w paragrafach:
   - `Partia/Batch: /2026` → `Partia/Batch: {nr_partii}`
   - `Data produkcji/Production date: .2026` → data z dt_start
   - `Data ważności/Expiry date: .2027` → dt_start + 1 rok
   - Data wystawienia w stopce
4. Zapis do tymczasowego docx → konwersja na PDF przez LibreOffice CLI (`libreoffice --convert-to pdf`) lub python-docx2pdf
5. Zapis PDF do ścieżki docelowej

## Mapowanie parametrów

Gotowe w `mbr/cert_mappings.py`:
- 90 wzorów
- 408 parametrów zmapowanych do 21 kodów analizy
- Parametry jakościowe (Wygląd, Zapach) → `kod: None` (pomijane lub stałe wartości z wzoru)
- Parametry impurities (MCA, DCA, DMAPA) → `kod: None` (nie w standardowej analizie)

## Baza danych

Nowa tabela `swiadectwa`:

```sql
CREATE TABLE IF NOT EXISTS swiadectwa (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ebr_id          INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
    template_name   TEXT NOT NULL,
    nr_partii       TEXT NOT NULL,
    pdf_path        TEXT NOT NULL,
    dt_wystawienia  TEXT NOT NULL,
    wystawil        TEXT NOT NULL
);
```

## UI

### Widok zakończonego zbiornika (footer)

Gdy `ebr.status == 'completed'` i `ebr.typ == 'zbiornik'`:
- Przycisk "Wystaw świadectwo" obok "PDF"
- Klik → otwiera panel/modal z listą pasujących wzorów

### Lista wzorów

- Filtrowane po produkcie (matchowanie nazwy pliku po `short_product`)
- Wyświetlane jako lista z nazwą wzoru (bez "Świadectwo_Certificate-" prefix)
- Klik na wzór → generacja + download

### Historia świadectw

- Pod przyciskiem: lista wcześniej wystawionych świadectw dla tego zbiornika
- Każde z linkiem do PDF

## API

```
GET  /api/cert/templates?produkt=Chegina_K7  → lista pasujących wzorów
POST /api/cert/generate                      → {ebr_id, template_name} → generuje PDF, zwraca ścieżkę
GET  /api/cert/{cert_id}/pdf                 → pobierz PDF
GET  /api/cert/list?ebr_id=123               → lista świadectw dla zbiornika
```

## Ścieżka zapisu

```
data/swiadectwa/{rok}/{produkt}/{wzor}_{nr_partii}.pdf
```

Przykład: `data/swiadectwa/2026/Chegina_K7/K7_WZOR_49_2026.pdf`

## Poza zakresem

- Edycja wzorów docx z poziomu aplikacji
- Mapowanie zbiornik → dozwolone wzory (na razie po nazwie produktu)
- Podpis elektroniczny
