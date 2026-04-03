# Zbiorcze poprawki UI — design spec

**Data:** 2026-04-03

## 1. Rejestr ukończonych — filtr zbiornik/szarża

Dodać segmented control do nagłówka rejestru: **Szarże | Zbiorniki**. Domyślnie "Szarże" aktywne (zbiorniki ukryte).

- Filtr przekazywany w query string: `/api/registry?produkt=X&typ=szarza|zbiornik`
- Backend `list_completed_registry` filtruje po `eb.typ`
- Przycisk filtra obok istniejących tabów produktów

## 2. Zakładka "Narzędzia" w nawigacji

Nowy przycisk w railu (ikona narzędzi), widoczny **tylko dla roli kontrola jakości** (technolog). Prowadzi do panelu z kafelkami narzędzi.

### Pierwszy kafelek: Wniosek o zwrot kosztów dojazdu

Formularz:
- Data
- Trasa: skąd → dokąd
- Kilometry (km)
- Stawka za km (domyślna wartość)

Generuje PDF do druku. Osobna strona/route, nie w SPA szarż.

## 3. System zmianowy — modal operatora

### Tabela `workers`

| Kolumna | Typ | Opis |
|---------|-----|------|
| id | INTEGER PK | Auto |
| imie | TEXT | Imię |
| nazwisko | TEXT | Nazwisko |
| inicjaly | TEXT | Auto-generowane z imię+nazwisko (np. "JK") |
| nickname | TEXT | Opcjonalny, edytowalny przez pracownika |
| aktywny | INTEGER | 1=aktywny, 0=nieaktywny |

Seed z aktualnymi pracownikami. Inicjały generowane automatycznie.

### Zmiana aktywna

- W session: `shift_workers = [worker_id, worker_id]` (max 2 osoby na zmianie)
- Modal dostępny z dolnego paska (kliknięcie w inicjały/nazwiska)
- Lista pracowników z checkboxami, zaznacz kto jest na zmianie
- Po potwierdzeniu — inicjały aktywnych wyświetlane w dolnym pasku

### Przypomnienie zmianowe

Zmiany: 6:00, 14:00, 22:00.

- JS sprawdza co minutę, jeśli bieżąca godzina = 6/14/22 i nie potwierdzono → subtelny banner/toast: "Zmiana — potwierdź kto jest na zmianie"
- Klikalny → otwiera modal
- `localStorage` trzyma timestamp ostatniego potwierdzenia (per zmiana)
- Banner znika po potwierdzeniu lub po 30 minutach od godziny zmiany

### Zapis wyników

`save_wyniki` zapisuje `wpisal` = inicjały/nicknames aktywnych pracowników zmiany (zamiast loginu sesji).

## 4. Auto-zapis (debounce + blur)

Usunąć przyciski "Zapisz sekcję". Każde pole input po:
- **debounce 1.5s** od ostatniego keystroke
- **blur** (zmiana pola, kliknięcie poza pole)

wysyła `POST /laborant/ebr/{id}/save` z pojedynczą wartością: `{sekcja, values: {kod: {wartosc, komentarz}}}`.

Wizualny feedback: krótki spinner/checkmark obok pola po udanym zapisie. Subtelne — nie blokuje pracy.

Backend `save_wyniki` już obsługuje upsert — nie wymaga zmian.

## 5. Prawy panel — wartości historyczne zamiast referencji

Usunąć zakładkę "Referencje" z prawego panelu. Zostaje "Kalkulator".

Normy (min-max) już wyświetlane nad polami (`<span class="norm">`).

Placeholder pod kalkulatorem: "Wartości historyczne pojawią się po zebraniu danych." — logika wyliczania (średnia, min, max z ostatnich N szarż) dodana później.

## 6. Nastaw — usunięcie z analizy, wymagany przy tworzeniu szarży

- Usunąć `_nastaw()` z `parametry_lab.analiza` we wszystkich 4 produktach (seed_mbr.py)
- Dodać pole `nastaw` do formularza tworzenia nowej szarży (`_modal_nowa_szarza.html`) — pole wymagane
- Nowa kolumna `nastaw INTEGER` w `ebr_batches`
- `create_ebr()` przyjmuje i zapisuje nastaw
- Wartość nastaw dostępna w widoku karty szarżowej i w PDF
