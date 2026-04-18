# Auto-adnotacja pakowania w uwagach ukończonych szarż

**Data:** 2026-04-18
**Zakres:** przy kończeniu szarży, jeśli `pakowanie_bezposrednie IN ('IBC','Beczki')`, dopisuj krótką adnotację do `uwagi_koncowe`
**Status:** zatwierdzony do pisania planu

## Kontekst

Część szarż jest pakowana bezpośrednio do pojemników — IBC (1000L containers) albo beczek — zamiast zwykłego zbiornika. Kolumna `ebr_batches.pakowanie_bezposrednie` (TEXT) trzyma tę informację ('IBC', 'Beczki', lub NULL dla standardu). Na widoku ukończonych szarż ("Rejestr ukończonych") ten atrybut nie jest widoczny — operator musiałby otworzyć szczegóły szarży żeby go dostrzec. Chcemy oznaczyć te szarże tekstowo w kolumnie Uwagi.

Per decyzje w brainstormie:
- **Tekst:** krótka forma — dosłownie `IBC` albo `Beczki`
- **Pozycja:** append (za istniejącym tekstem uwag)
- **Zakres:** tylko nowe — od wdrożenia, przy kończeniu szarży. Retroaktywna migracja starych ukończonych szarż NIE jest w zakresie.

## Niezmienne założenia

- Żadnych zmian w schemacie DB — `pakowanie_bezposrednie` i `uwagi_koncowe` już istnieją.
- Widok ukończonych (`szarze_list.html`) nie jest modyfikowany — adnotacja przychodzi naturalnie jako część pola `uwagi_koncowe` z DB.
- Certyfikaty i PDF karta nietknięte.
- Idempotentne — jeśli laborant wpisał "IBC" / "Beczki" ręcznie w uwagach, system nie duplikuje.

## Rozwiązanie

### Lokalizacja logiki

Endpoint kończenia szarży — `complete_ebr()` w `mbr/laborant/models.py` albo handler `/laborant/ebr/<id>/complete` w `mbr/laborant/routes.py`. Adnotacja dodawana w tej samej transakcji co zmiana statusu na `completed`.

### Algorytm

```python
# Po UPDATE ebr_batches SET status='completed':
row = db.execute(
    "SELECT pakowanie_bezposrednie, uwagi_koncowe FROM ebr_batches WHERE ebr_id=?",
    (ebr_id,),
).fetchone()
pak = (row["pakowanie_bezposrednie"] or "").strip()
if pak in ("IBC", "Beczki"):
    uwagi = (row["uwagi_koncowe"] or "").strip()
    # Idempotent check — word-boundary match, case-insensitive.
    # Regex uses the literal label ('IBC' or 'Beczki') — re.escape is
    # defensive against future values but both current labels are
    # alphanumeric so no escaping needed.
    word_re = re.compile(rf"\b{re.escape(pak)}\b", re.IGNORECASE)
    if not word_re.search(uwagi):
        new_uwagi = f"{uwagi}\n{pak}" if uwagi else pak
        db.execute(
            "UPDATE ebr_batches SET uwagi_koncowe=? WHERE ebr_id=?",
            (new_uwagi, ebr_id),
        )
```

### Separator

Znak nowej linii (`\n`). Gdy uwagi są puste → po prostu `IBC` / `Beczki`. Gdy uwagi już coś zawierają → `{existing}\n{pak}`.

Newline, nie spacja ani przecinek — chcemy wyraźnego oddzielenia, bo uwagi potrafią być zdaniowe ("Lepkość niska, dodano wody"). `\n` w widoku tabeli Uwagi pokazuje się jako separator (komórka ma `white-space:nowrap + title="..."` — pełna treść w tooltipie).

### Idempotencja

Regex `\bIBC\b` / `\bBeczki\b` (case-insensitive) — szukamy słowa jako niezależnego tokenu. Zapobiega:
- dwukrotnemu dopisaniu gdy endpoint complete jest wywołany dwa razy na tej samej szarży
- dopisaniu gdy laborant sam wpisał "IBC" w uwagach wcześniej
- false-positive-ów jak "podbicie" (inside "ib" ≠ IBC because word boundaries)

### Co NIE jest zmieniane

- Widok `szarze_list.html` — zero zmian
- Widok szczegółów szarży — zero zmian
- Migracje DB — zero zmian
- Skrypt retroaktywny dla starych szarż — poza zakresem (per decyzja)

## Komponenty zmienione

| Plik | Zmiana |
|---|---|
| `mbr/laborant/models.py` (funkcja `complete_ebr` albo gdzie status='completed') | Po UPDATE statusu dodać blok adnotacji |
| `tests/test_pakowanie_annotation.py` (nowy) | Testy happy-path + idempotencja + NULL pakowanie |

## Weryfikacja

1. Complete szarża z `pakowanie_bezposrednie='IBC'` i pustymi `uwagi_koncowe` → po completion `uwagi_koncowe == 'IBC'`.
2. Complete z `pakowanie_bezposrednie='Beczki'` i `uwagi_koncowe='Lepkość 2,5'` → po completion `'Lepkość 2,5\nBeczki'`.
3. Complete dwukrotnie tę samą szarżę → uwagi_koncowe nie dublują się (`'Lepkość 2,5\nBeczki'`, nie `'Lepkość 2,5\nBeczki\nBeczki'`).
4. Complete z `pakowanie_bezposrednie='IBC'` i uwagami `'już wpisałem ibc ręcznie'` → bez zmian (word-boundary match, case-insensitive).
5. Complete z `pakowanie_bezposrednie=NULL` → `uwagi_koncowe` bez zmian.
6. Complete z `pakowanie_bezposrednie='xyz'` (nie-IBC, nie-Beczki) → bez zmian (tylko dwie whitelistowane wartości propagują).

## Kryteria akceptacji

- Po zakończeniu szarży IBC/Beczki widoczne w kolumnie Uwagi w widoku ukończonych, bez akcji laboranta.
- Ponowne kliknięcie "Zakończ" (albo uruchomienie endpointu idempotentnie) nie powoduje duplikatu.
- Ręcznie wpisana adnotacja ("IBC" w uwagach) jest respektowana — system nie dopisuje drugiej.
- Szarże z NULL lub nie-whitelistowaną wartością — bez zmian.
