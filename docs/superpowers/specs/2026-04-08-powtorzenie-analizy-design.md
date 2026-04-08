# D: Powtórzenie analizy + edycja zbiorników — Design Spec

## D1: Powtórzenie analizy końcowej

### Problem
Brak możliwości powtórzenia analizy końcowej gdy wynik jest poza normą. Laborant musi mieć przycisk "Powtórz analizę" który otwiera nową rundę.

### Jak działa system rund (obecny)
Produkty z pełnym pipeline (Cheginy) mają cykl: `analiza__1 → dodatki__1 → analiza__2 → ...`
- `get_round_state()` śledzi rundy i decyduje co jest następne
- Stare rundy renderowane jako readonly z opacity 0.65
- Nowa runda otwiera się po "Korekta"

### Co trzeba dodać

**Dla WSZYSTKICH produktów** (prostych i pełnych):

1. **Przycisk "Powtórz analizę"** — pojawia się pod sekcją analiza_koncowa gdy ma wyniki
2. **Klik** → obecna sekcja zwija się w accordion (jak etapy procesowe — `ps-accordion`)
3. **Nowa sekcja** otwiera się: `analiza_koncowa__2`, `analiza_koncowa__3`...
4. **Podsumowanie** na zwiniętym pasku — lista parametrów z wartościami (kolorowane OK/err)

### Backend

**Zmiana w `get_round_state()`** — obsługa rund `analiza_koncowa__N`:
- Parsować sekcje `analiza_koncowa__N` z wyników
- Zwracać `last_ak` (ostatnia runda AK) i `next_ak_sekcja`

**Zmiana w `save_wyniki()`** — już obsługuje suffix `__N` (split na `__`). Bez zmian.

### Frontend

**Rendering rund AK:**
- Sprawdzić wyniki na klucze `analiza_koncowa`, `analiza_koncowa__2`, `analiza_koncowa__3`...
- Runda 1 = sekcja `analiza_koncowa` (bez suffixu, backward compat)
- Runda N = sekcja `analiza_koncowa__N`
- Stare rundy: accordion zwinięty z podsumowaniem
- Nowa runda: otwarta z pustymi polami

**Przycisk "Powtórz analizę":**
- Pod ostatnią sekcją AK
- `onclick` → POST do endpointu lub po prostu reload (jak startKorekta)
- Po reload backend widzi nową rundę i renderuje kolejną sekcję

## D2: Edycja zbiorników po ukończeniu

Na ukończonej szarży (status=completed):
- Wyświetlić przypisane zbiorniki z badge'ami
- Przycisk "Edytuj" → otwiera pump modal w trybie edycji
- Modal pre-selectuje istniejące zbiorniki (już zaimplementowane)
- Dodawanie/usuwanie przez API zbiornik-szarze

### Pliki

| Action | File | Purpose |
|--------|------|---------|
| Modify | `mbr/laborant/models.py` | Rozszerzenie get_round_state o rundy AK |
| Modify | `mbr/templates/laborant/_fast_entry_content.html` | Accordion rundy AK + przycisk "Powtórz" + edycja zbiorników |
