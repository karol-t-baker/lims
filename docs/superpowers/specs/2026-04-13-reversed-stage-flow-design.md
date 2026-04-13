# Odwrocony flow etapow cyklicznych — spec

## Problem

Obecny flow: analiza → decyzja → korekta. Ale w rzeczywistosci laborant najpierw widzi dodatek (z produkcji), potem robi analize i ocenia. Cel etapu nie ma gdzie byc czytelnie wyswietlony. Sekcje "dodatki" jako companion stages komplikuja adapter i flowchart.

## Cel

Odwrocic flow: dodatek → analiza → decyzja. Kazdy etap cykliczny ma jedną sekcje z dwoma blokami. Prawy panel "Cele" pokazuje docelowe wartosci aktywnego etapu.

## Struktura sekcji cyklicznej

### Runda 1: tylko ANALIZA
Pierwszy dodatek jest procesowy — laborant dostaje probke po nim.

### Runda 2+: DODATEK → ANALIZA
Laborant wpisuje ile dodano substancji korekcyjnej, potem wyniki analizy.

### Oba: DECISION PANEL pod sekcja
Dwa przyciski:
- "Korekta {substancja} ↻" → nowa runda (dodatek + analiza)
- "Zamknij etap →" lub "{substancja} → {nastepny etap}" (jesli jest_przejscie)

## Sekcje per etap

### Sulfonowanie

Runda 1:
```
ANALIZA
  SO₃  [___]   pH 10% [___]   nD20 [___]   Barwa [___]
DECYZJA
  [Korekta Na₂SO₃ ↻]  [Perhydrol → Utlenienie]
```

Runda 2:
```
DODATEK
  Na₂SO₃  [___] kg
ANALIZA
  SO₃  [___]   pH 10% [___]   nD20 [___]   Barwa [___]
DECYZJA
  [Korekta Na₂SO₃ ↻]  [Perhydrol → Utlenienie]
```

### Utlenienie

Runda 1:
```
ANALIZA
  SO₃  [___]   H₂O₂ [___]   pH 10% [___]   nD20 [___]
DECYZJA
  [Korekta Perhydrol ↻]  [Zamknij → Standaryzacja]
```

Runda 2:
```
DODATEK
  Perhydrol 34%  [___] kg  (obliczono: X,X kg)
ANALIZA
  SO₃  [___]   H₂O₂ [___]   pH 10% [___]   nD20 [___]
DECYZJA
  [Korekta Perhydrol ↻]  [Zamknij → Standaryzacja]
```

### Standaryzacja — BEZ ZMIAN
Istniejacy flow renderCyclicSections z analiza__1/dodatki__1 round cycling. Nie dotykamy.

### Analiza koncowa — BEZ ZMIAN

## Prawy panel — zakladka "Cele"

### Zmiana
Zakladka "Wartosci typowe" → "Cele". Dynamiczna zawartosc — zmienia sie z aktywnym etapem.

### Rendering
Po zmianie aktywnego etapu (showPipelineStage lub auto-detect), aktualizuj zawartosc panelu Cele:
1. Pobierz pola aktywnego etapu z `parametry[sekcja].pola`
2. Filtruj do tych z `target != null`
3. Renderuj tabele kompaktowa: parametr | wartosc cel

### Format
```
┌──────────────────────────┐
│ CELE AKTYWNEGO ETAPU     │  ← teal header
├──────────────────────────┤
│ SO₃         0,030        │
│ H₂O₂       0,005        │
│ nD20        1,3922       │
└──────────────────────────┘
```

### Edycja
Klik na wartosc → edytowalny input → blur → PUT do produkt_etap_limity (globalne).

## Zmiany w adapterze

### build_pipeline_context
Cykliczne etapy (nie-main) NIE generuja companion "dodatki" stage. Korekty sa czescia tej samej sekcji.

Zmiana: usunac generowanie `{kod}_dodatki` etap entry i `{kod}_dodatki` sekcji w parametry_lab dla nie-main cyklicznych etapow.

Zamiast tego: pola korekty dodac do tej samej sekcji co parametry analityczne, z flagą `jest_korekta: true`.

### Adapter output (nowy)
```python
{
    "sulfonowanie": {
        "label": "Sulfonowanie",
        "pola": [
            {"kod": "so3", ..., "jest_korekta": false},
            {"kod": "ph_10proc", ..., "jest_korekta": false},
            ...
        ],
        "korekty_pola": [
            {"kod": "korekta_na2so3", "label": "Na₂SO₃ [kg]", ...}
        ]
    }
}
```

Albo prostsze: korekty nie w `pola` lecz osobny klucz `korekty_pola` w sekcji.

## Zmiany w renderPipelineSections

### Dla nie-main cyklicznych etapow (sulfonowanie, utlenienie)

Zamiast renderowac jedna sekcje przez `renderOneSection`, renderuj custom:

1. Sprawdz runda (z roundState lub z wynikow):
   - Runda 1: tylko analiza
   - Runda 2+: dodatek + analiza

2. DODATEK blok (runda 2+):
   - Naglowek "DODATEK"
   - Pola z `korekty_pola` (input na ilosc, z formula pre-fill jesli dostepna)

3. ANALIZA blok:
   - Standardowe pola parametrow (renderowane jak w renderOneSection)

4. DECISION panel:
   - renderStageDecisionPanel (juz zaimplementowany)

### Track round number per non-main cyclic stage

Dla sulfonowania/utlenienia potrzebujemy wiedziec ktora runda. Obecnie `roundState` trackuje `analiza__N/dodatki__N` (main cyclic). Dla nie-main:
- Sprawdz `wyniki` — ile kluczy `sulfonowanie__N` istnieje
- Lub: sprawdz `ebr_etap_sesja` rundy przez API

Prostsze: uzywaj sekwencyjnych kluczy sekcji — `sulfonowanie` (runda 1), `sulfonowanie__2` (runda 2), itd.

Ale to wymaga zmiany w save flow — teraz `doSaveField` zapisuje do `sekcja` ktora jest w `data-sekcja` atrybucie inputa. Musi byc dynamiczna per runda.

### Uproszczenie: NIE uzywaj round keys per non-main cyclic

Zamiast `sulfonowanie__1`, `sulfonowanie__2` — cykliczne etapy nie-main uzywaja jednego klucza `sulfonowanie`. Kazda runda nadpisuje wyniki. Historia rund jest w `ebr_etap_sesja` + `ebr_pomiar`.

To upraszcza rendering — nie trzeba trackować rund w wynikach. Decision panel operuje na sesjach pipeline (close + start).

Ale: laborant traci widok poprzednich rund w sekcji. Akceptowalne w V1 — historia rund w przyszlosci.

## Zmiany w plikach

### Backend
- `mbr/pipeline/adapter.py` — usunac companion dodatki dla nie-main cyklicznych. Dodac `korekty_pola` do sekcji.

### Frontend
- `mbr/templates/laborant/_fast_entry_content.html`:
  - `renderPipelineSections` — custom rendering dla nie-main cyklicznych z blokami DODATEK/ANALIZA
  - Prawy panel: zakladka "Cele" zamiast "Wartosci typowe"
  - `updateCelePanel(sekcja)` — renderuje cele aktywnego etapu
  - Wywolanie `updateCelePanel` z `showPipelineStage` i `renderPipelineSections`

### Nie zmieniamy
- Standaryzacja (main cykliczny) — `renderCyclicSections` bez zmian
- `renderStageDecisionPanel` — juz dziala, zostaje
- Backend modele pipeline — bez zmian
- Admin UI — bez zmian

## Zakres

### Budujemy
- Odwrocony flow: dodatek (runda 2+) → analiza → decyzja
- Jeden klucz sekcji per etap (nie round keys)
- Prawy panel "Cele" dynamiczny per etap
- Usunięcie companion dodatki stages z adaptera

### NIE budujemy
- Historia rund w UI (V2)
- Zmiana standaryzacja flow
- Round keys per nie-main cyklicznych
