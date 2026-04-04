# Design: Formularz wniosku o zwrot kosztów paliwa

Data: 2026-04-04
Status: Zatwierdzony

---

## Problem

Laboranci co miesiąc wypełniają ręcznie papierowy wniosek o zwrot kosztów używania samochodu prywatnego (ryczałt). Automatyzujemy generowanie PDF.

## Rozwiązanie

Formularz w zakładce Narzędzia. Wybór osoby, wpisanie dni urlopowych, automatyczne obliczenia, generowanie PDF przez docxtpl + Gotenberg.

---

## Dane osoby — tabela `paliwo_osoby`

```sql
CREATE TABLE IF NOT EXISTS paliwo_osoby (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    imie_nazwisko TEXT NOT NULL,
    stanowisko TEXT NOT NULL,
    nr_rejestracyjny TEXT NOT NULL,
    aktywny INTEGER DEFAULT 1,
    dt_dodania TEXT
);
```

CRUD w Narzędziach: lista osób, dodaj, edytuj, usuń (soft delete — `aktywny=0`).

## Konfiguracja globalna

Stałe w `paliwo.py` (łatwo zmienić):

```python
RYCZALT = 345.00        # zł
STAWKA_DZIENNA = 15.68  # zł (345/22)
LIMIT_KM = 300          # km
```

## Flow generowania

1. Laborant → Narzędzia → sekcja "Wniosek paliwo"
2. Wybiera osobę z dropdowna (tylko aktywne)
3. System automatycznie ustawia:
   - Miesiąc: bieżący (np. "kwiecień 2026")
   - Data wystawienia: ostatni dzień roboczy (pn-pt) bieżącego miesiąca
4. Laborant wpisuje liczbę dni nieobecności (urlop/choroba/delegacja)
5. System oblicza:
   - Potrącenie = dni × 15.68 zł
   - RAZEM potrąceń = to samo
   - Ryczałt do wypłaty = 345.00 − potrącenie
   - Kwota słownie (biblioteka `num2words`, język PL)
6. Podgląd kwot na stronie
7. Klik "Generuj PDF" → docxtpl + Gotenberg → PDF otwiera się w nowej karcie

## Obliczenia

```
potracenie = dni_urlopu * STAWKA_DZIENNA
ryczalt_do_wyplaty = RYCZALT - potracenie
```

Jeśli dni_urlopu = 0 → potrącenie = 0, ryczałt do wypłaty = 345,00 zł

## Kwota słownie

Biblioteka `num2words` z locale PL:
```python
from num2words import num2words
# 329.32 → "trzysta dwadzieścia dziewięć złotych trzydzieści dwa grosze"
```

## Data wystawienia

Ostatni dzień roboczy (pn-pt) bieżącego miesiąca:
```python
from datetime import date, timedelta
import calendar

def last_workday(year, month):
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    while last_day.weekday() >= 5:  # sobota=5, niedziela=6
        last_day -= timedelta(days=1)
    return last_day
```

## Miesiąc — nazwy polskie

```python
MIESIACE = {
    1: 'styczeń', 2: 'luty', 3: 'marzec', 4: 'kwiecień',
    5: 'maj', 6: 'czerwiec', 7: 'lipiec', 8: 'sierpień',
    9: 'wrzesień', 10: 'październik', 11: 'listopad', 12: 'grudzień'
}
```

## Master .docx — tagi

Kopia oryginału `docs/swiadectwa/paliwo.docx` z jedną stroną (oryginał ma 2 kopie — usuwamy duplikat). Tagi:

| Tag | Wartość |
|-----|---------|
| `{{imie_nazwisko}}` | Jan Kowalski |
| `{{data_wystawienia}}` | 30.04.2026 |
| `{{stanowisko}}` | Laborant KJ |
| `{{nr_rejestracyjny}}` | GDA 12345 |
| `{{miesiac}}` | kwiecień 2026 |
| `{{miesiac_ryczalt}}` | kwiecień 2026 (to samo) |
| `{{limit_km}}` | 300 |
| `{{ryczalt}}` | 345,00 |
| `{{stawka_dzienna}}` | 15,68 |
| `{{dni_urlopu}}` | 2 |
| `{{potracenie}}` | 31,36 |
| `{{ryczalt_do_wyplaty}}` | 313,64 |
| `{{kwota_slownie}}` | trzysta trzynaście złotych sześćdziesiąt cztery grosze |

## Endpointy API

| Metoda | URL | Opis |
|--------|-----|------|
| GET | `/api/paliwo/osoby` | Lista aktywnych osób |
| POST | `/api/paliwo/osoby` | Dodaj osobę |
| PUT | `/api/paliwo/osoby/<id>` | Edytuj osobę |
| DELETE | `/api/paliwo/osoby/<id>` | Soft delete |
| POST | `/api/paliwo/generuj` | Generuj PDF (osoba_id, dni_urlopu) |

## UI w Narzędziach

### Sekcja 1: Zarządzanie osobami
- Lista osób w tabeli: imię i nazwisko, stanowisko, nr rejestracyjny, przyciski edycja/usuń
- Przycisk "Dodaj osobę" → inline form lub modal
- Edycja inline

### Sekcja 2: Generuj wniosek
- Dropdown: wybierz osobę
- Auto: miesiąc (bieżący), data wystawienia (ostatni dzień roboczy)
- Input: liczba dni nieobecności (default 0)
- Live podgląd obliczeń (potrącenie, ryczałt do wypłaty, kwota słownie)
- Przycisk "Generuj PDF"

## Pliki

| Plik | Akcja | Opis |
|------|-------|------|
| `mbr/paliwo.py` | CREATE | Logika: CRUD osób, obliczenia, generowanie PDF |
| `mbr/templates/paliwo_master.docx` | CREATE | Master .docx z tagami (z oryginału, 1 strona) |
| `mbr/templates/technolog/narzedzia.html` | MODIFY | Dodaj sekcje: osoby + formularz generowania |
| `mbr/app.py` | MODIFY | Dodaj endpointy /api/paliwo/* |

## Zależności

- `num2words` — pip install num2words
- `docxtpl` — już zainstalowane
- Gotenberg — już działa na localhost:3000
