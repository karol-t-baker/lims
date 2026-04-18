# FAU `<1` quick-entry w Fast Entry

**Data:** 2026-04-18
**Zakres:** pojedynczy przycisk "<1" obok pola `metnosc_fau` w laborant Fast Entry
**Status:** zatwierdzony do pisania planu

## Kontekst

Parametr `metnosc_fau` (mętność w jednostkach Formazin Attenuation Units) ma dolny limit detekcji = 1 FAU. Gdy próbka ma mętność poniżej tego limitu, wynik zapisuje się jako "<1" — standard laboratoryjny (LLOD, Lower Limit of Detection). Dziś laborant nie ma szybkiego sposobu wpisania tego — musi wpisywać liczbowo (np. 0.5) co jest niedokładne, albo pomijać pole.

Użytkownik potwierdził: "<1" pozostaje tylko wewnątrz systemu (Fast Entry, raporty, ml_export), **NIE trafia na świadectwo**. Cert generator ignoruje wyniki jakościowe, więc rekord `<1` nie propaguje do cert-u.

## Niezmienne założenia

- **DB bez migracji** — `ebr_wyniki.wartosc_text` (TEXT) już istnieje obok `wartosc` (REAL). Wykorzystamy istniejący schemat.
- **Świadectwa nietykane** — żadne zmiany w `mbr/certs/*` ani template-ach DOCX.
- **Zakres minimalny** — tylko pole `metnosc_fau`, jeden przycisk. Generalizacja na inne parametry (<LOD, NA, bezbarwna, mętna) jest POZA zakresem tej iteracji — może trafić do pełnej karty w osobnym PR.

## Rozwiązanie

### UI — Fast Entry

W `mbr/templates/laborant/_fast_entry_content.html`, w funkcji generującej wiersz pola liczbowego (`ff` div, ok. lines 2558-2568), dla parametru o `kod === "metnosc_fau"` obok input-u pojawia się mały przycisk **"<1"**:

```
┌─────────────────────────────────────────┐
│ ●  b. FAU                   [_____] <1 │
└─────────────────────────────────────────┘
```

- Przycisk ~28px szerokości, style jak istniejące wc-btn-sm, wygląda na wcięty gdy stan aktywny
- Klik: input dostaje `value = "<1"`, staje się `readonly`, background szary
- Drugi klik: wraca do normalnego trybu, wartość wyczyszczona, input edytowalny
- Klik BEZPOŚREDNIO w input (nawet gdy readonly) też odznacza stan

### Autosave / send-to-backend

Istniejący flow autosave wysyła wartość z inputa jako string przez POST (np. `/api/ebr/<id>/wyniki`). Endpoint parsuje:
- Jeśli wartość zaczyna się od `<`, `>`, `≤`, `≥` → zapisywana jako `wartosc_text`, `wartosc = NULL`
- W przeciwnym razie próba parsowania na float → `wartosc = float`, `wartosc_text = NULL`
- `w_limicie` dla stanu jakościowego = NULL (neutralny, nie oceniamy)

Ta logika dodana w endpoint save-handler (miejsce do zidentyfikowania w kodzie — mbr/laborant/routes.py lub analog).

### Render w Fast Entry

Po załadowaniu wyników (`/api/ebr/<id>/wyniki`), backend zwraca dla każdego pola `wartosc` (number) lub `wartosc_text` (string). Frontend sprawdza:
- Jeśli `wartosc_text` nie pusta → wyświetla tekst, ustawia readonly tryb, jeśli to "<1" i kod=="metnosc_fau" → przycisk "<1" w stanie aktywnym
- Inaczej → standard flow (numeric)

### Widoczność w innych miejscach

- **Historia/audit** — `wartosc_text` widoczne jako tekst w raportach
- **ml_export** — eksport jako string "<1" (nie NaN, nie 0) — ml_export już respektuje wartosc_text (sprawdzić)
- **PDF batch card** — wyświetla `wartosc_text` gdy ustawione zamiast liczby (sprawdzić w karta_base.html)
- **Świadectwo** — NIE trafia, cert generator czyta tylko `wartosc` liczbowe (patrz generator.py line ~278)

## Komponenty zmienione

| Plik | Zmiana |
|---|---|
| `mbr/templates/laborant/_fast_entry_content.html` | `ff` div generator — dla `kod === "metnosc_fau"` dodać przycisk "<1"; JS handler toggle; render-state reading z `wartosc_text` |
| `mbr/laborant/routes.py` (albo gdzie zapis wyników) | parse-logic: prefix `<>≤≥` → `wartosc_text`, liczba → `wartosc` |
| `mbr/etapy/models.py` lub `mbr/laborant/models.py` | jeśli jest helper `save_wynik`, rozszerzyć o obsługę `wartosc_text` |
| `tests/test_laborant_fau.py` (nowy) | test zapisu "<1" → wartosc_text, "1,5" → wartosc float |

## Weryfikacja

1. W Fast Entry dla produktu z `metnosc_fau` pole ma przycisk "<1" obok input-u.
2. Kliknięcie "<1" → input readonly + wartość "<1" + szary background.
3. Autosave POST-uje "<1"; backend zapisuje do `wartosc_text = '<1'`, `wartosc = NULL`.
4. Reload strony → stan "<1" odtworzony z DB.
5. Drugi klik "<1" → input znów edytowalny, wartość pusta.
6. Zwykłe wpisanie liczby → `wartosc = float`, `wartosc_text = NULL` (stare zachowanie).
7. Świadectwo dla szarży z `metnosc_fau = "<1"` — pole rendered jako puste lub wartość domyślna (potwierdzić ręcznie w podglądzie).

## Kryteria akceptacji

- Klik "<1" → zapis jako `wartosc_text` w DB (widoczne w `SELECT wartosc, wartosc_text FROM ebr_wyniki WHERE kod_parametru='metnosc_fau'`)
- Wartość po reload odtwarza się jako "<1" w UI
- Inne parametry nie zmieniają zachowania
- Cert nie pokazuje "<1"
