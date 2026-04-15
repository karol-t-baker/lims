# Formularz ChZT Ścieków — Design

**Data:** 2026-04-15

## Cel

Formularz w Narzędziach do oznaczania ChZT (Chemiczne Zapotrzebowanie na Tlen) ścieków. Laborant wpisuje pH i 5 pomiarów ChZT dla każdego punktu poboru, system liczy średnią i wysyła dane.

## Zakres

Tylko formularz UI + endpoint zapisu. Skrypt uzupełniający Excel — osobny etap.

## Flow

1. Laborant otwiera Narzędzia → "ChZT Ścieków"
2. Wpisuje liczbę kontenerów (np. 8)
3. System generuje sekcje: hala, rura, kontener 1..N, szambiarka
4. Per sekcja: 1 pole pH + 5 pól ChZT
5. System liczy średnią ChZT na bieżąco
6. Laborant klika "Zapisz" → dane zapisane z datą bieżącą

## Punkty pomiarowe

| Punkt | Stały | Kolejność |
|-------|-------|-----------|
| Hala | tak | 1 |
| Rura | tak | 2 |
| Kontener 1..N | dynamiczny | 3..N+2 |
| Szambiarka | tak | ostatni |

## Pola per punkt

| Pole | Typ | Wymagane |
|------|-----|----------|
| pH | number (0-14, step 1) | tak |
| ChZT próbka 1 | number (mg O₂/l) | tak |
| ChZT próbka 2 | number | tak |
| ChZT próbka 3 | number | nie |
| ChZT próbka 4 | number | nie |
| ChZT próbka 5 | number | nie |
| **Średnia ChZT** | auto-calc | — |

Średnia liczona z wypełnionych pól (min 2 próbki).

## Dane wyjściowe

JSON do API:

```json
{
  "data": "2026-04-15",
  "punkty": [
    {"nazwa": "hala", "ph": 10, "chzt_probki": [25842, 24500, 26100, null, null], "chzt_srednia": 25480.7},
    {"nazwa": "rura", "ph": 10, "chzt_probki": [18310, 17800, 18900, null, null], "chzt_srednia": 18336.7},
    {"nazwa": "kontener 1", "ph": 11, "chzt_probki": [11168, 10900, 11400, 11200, null], "chzt_srednia": 11167.0},
    ...
    {"nazwa": "szambiarka", "ph": 10, "chzt_probki": [15314, 14800, 15600, null, null], "chzt_srednia": 15238.0}
  ]
}
```

## UI

- Modal w narzędziach (jak paliwo) LUB osobna strona
- Nagłówek: "ChZT Ścieków" + data bieżąca
- Pole "Liczba kontenerów" z przyciskiem "Generuj"
- Sekcje w formie kompaktowej tabeli: punkt | pH | P1 | P2 | P3 | P4 | P5 | Średnia
- Wiersz hala, rura, kontener 1..N, szambiarka
- Średnia aktualizuje się live (oninput)
- Przycisk "Zapisz" na dole
- Walidacja: min 2 próbki ChZT per punkt, pH wymagane

## Backend

- `POST /api/chzt/save` — zapisuje JSON do `data/chzt/` jako plik `chzt_2026-04-15.json`
- Odpowiedź: `{"ok": true, "file": "chzt_2026-04-15.json"}`

## Pliki

| Plik | Zmiana |
|------|--------|
| `mbr/templates/technolog/narzedzia.html` | Dodać kartę "ChZT Ścieków" + modal/formularz |
| `mbr/registry/routes.py` | Dodać `POST /api/chzt/save` |
