# Design: UI karty szarżowej — etapy procesowe (K7 + K40GLOL)

Data: 2026-04-05
Status: Zatwierdzony
Pod-projekt: 2 z 3 (UI karty szarżowej)
Dotyczy produktów: Chegina K7 (ETAPY_FULL, 8 etapów) i Chegina K40GLOL (ETAPY_FULL_GLOL, 9 etapów)

---

## Problem

Pipeline w sidebarze pokazuje etapy procesowe (Amidowanie → Utlenienie) ale są nieklikalne i bez danych. Laborant może wpisywać wyniki tylko w Standaryzacji i Analizie końcowej. Brak sekwencyjnego prowadzenia przez proces.

## Cel

Rozszerzyć istniejący UI o formularze analityczne na etapach procesowych. System prowadzi laboranta sekwencyjnie — otwiera aktualny etap, pozwala wpisać wyniki, zalecić korektę (dodatkowa runda), zatwierdzić i przejść dalej.

## Zakres

Tylko produkty z ETAPY_FULL / ETAPY_FULL_GLOL:
- Chegina K7, K40GL, K40GLO (ETAPY_FULL — 8 etapów)
- Chegina K40GLOL, K40GLOS, K40GLOL_HQ, K40GLN, GLOL40 (ETAPY_FULL_GLOL — 9 etapów)

Produkty z ETAPY_SIMPLE (zbiorniki, Chelamid, Monamid etc.) — bez zmian.

---

## Nowa tabela: `ebr_etapy_status`

Śledzi stan każdego etapu procesowego per szarża.

```sql
CREATE TABLE IF NOT EXISTS ebr_etapy_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ebr_id INTEGER NOT NULL,
    etap TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    dt_start TEXT,
    dt_end TEXT,
    zatwierdzil TEXT,
    UNIQUE(ebr_id, etap)
);
```

| status | Znaczenie |
|--------|-----------|
| `pending` | Etap jeszcze nie rozpoczęty |
| `in_progress` | Aktualny etap — laborant tu pracuje |
| `done` | Zatwierdzony — laborant kliknął "Zatwierdź etap" |

### Inicjalizacja przy tworzeniu szarży

Gdy tworzona jest nowa szarża K7/K40GLOL:
1. System odczytuje listę etapów z ETAPY_FULL/ETAPY_FULL_GLOL
2. Dla każdego etapu procesowego (read_only=True, PRZED standaryzacją) tworzy rekord w `ebr_etapy_status` z `status='pending'`
3. Pierwszy etap (`amidowanie`) ustawia na `status='in_progress'`

Etapy lab (standaryzacja, analiza końcowa) NIE trafiają do `ebr_etapy_status` — mają swój istniejący mechanizm w `ebr_wyniki`.

---

## Flow laboranta

```
Otwiera kartę szarży
    ↓
System otwiera aktualny etap (pierwszy z status='in_progress')
    ↓
Laborant widzi formularz z polami per parametr
    ↓
Wpisuje wyniki analizy (auto-save per pole)
    ↓
┌─ Wyniki OK ──────────────────────────────┐
│  Klika "Zatwierdź etap →"                │
│  → etap.status = 'done'                  │
│  → następny etap.status = 'in_progress'  │
│  → jeśli następny = Standaryzacja:       │
│    przejście do istniejącego flow         │
└──────────────────────────────────────────┘
    lub
┌─ Wymaga korekty ────────────────────────┐
│  Wpisuje: substancja + ilość kg         │
│  Klika "Zaleć korektę"                  │
│  → zapisuje do ebr_korekty              │
│  → runda++ (nowy zestaw pól)            │
│  → po korekcie wpisuje wyniki ponownie  │
│  → (może tylko część parametrów)        │
│  → ocenia ponownie: OK lub kolejna      │
│    korekta                              │
└──────────────────────────────────────────┘
```

---

## UI formularza etapu procesowego

### Widok aktywnego etapu (in_progress)

```
┌─────────────────────────────────────────┐
│ CZWARTORZĘDOWANIE           Runda 2     │
├─────────────────────────────────────────┤
│                                         │
│ ┌─ Wyniki analizy (runda 2) ────────┐  │
│ │  ● pH 10%     [11.76    ]         │  │
│ │  ● nD20       [1.3952   ]         │  │
│ │  ● %AA        [0.08     ]         │  │
│ └────────────────────────────────────┘  │
│                                         │
│ ┌─ Historia korekt ─────────────────┐  │
│ │  R1 → NaOH 10.0 kg  (zalecono)   │  │
│ └────────────────────────────────────┘  │
│                                         │
│ ┌─ Zalecenie korekty ───────────────┐  │
│ │  Substancja: [NaOH    ▼]         │  │
│ │  Ilość:      [____] kg            │  │
│ │         [+ Zaleć korektę]         │  │
│ └────────────────────────────────────┘  │
│                                         │
│           [Zatwierdź etap →]            │
└─────────────────────────────────────────┘
```

### Widok zatwierdzonego etapu (done) — read-only

Ten sam layout ale:
- Pola inputów read-only
- Brak sekcji "Zalecenie korekty"
- Brak przycisku "Zatwierdź"
- Badge "Zatwierdzony ✓" + data + kto

### Widok przyszłego etapu (pending)

- Szary, puste pola
- Komunikat: "Etap będzie dostępny po zatwierdzeniu [nazwa poprzedniego etapu]"

---

## Pipeline sidebar — zmiana zachowania

### Obecne
- Etapy read_only: szare, nieklikalne
- Standaryzacja/AK: kolorowe, klikalne

### Po zmianie
- Etapy procesowe z `status='done'`: ✓ zielone, klikalne (read-only)
- Etap z `status='in_progress'`: ● aktywny (teal/amber), kliknięty domyślnie
- Etapy z `status='pending'`: ○ szare, klikalne ale pokazują "niedostępny"
- Standaryzacja: jak teraz (cykliczny flow), aktywna po zatwierdzeniu ostatniego etapu procesowego
- AK: jak teraz

### Auto-otwarcie
Przy ładowaniu karty szarży → system automatycznie otwiera etap z `status='in_progress'`.

---

## Styl formularza

Taki sam jak standaryzacja:
- Pola inputów z auto-save (oninput → debounce → POST)
- `type="text" inputmode="decimal"` (przecinek/kropka)
- Dot statusu (zielony OK / czerwony poza normą) — orientacyjny, bez blokowania
- Wartości wyświetlane z przecinkiem

### Korekty
- Dropdown z dozwolonymi substancjami (z `etapy_config.py` → pole `korekty`)
- Input na ilość kg
- Przycisk "Zaleć korektę" → POST `/api/ebr/{id}/korekty`
- Lista dotychczasowych korekt per runda (read-only)

---

## Endpointy API (nowe/zmienione)

| Metoda | URL | Opis |
|--------|-----|------|
| GET | `/api/ebr/<id>/etapy-status` | Status wszystkich etapów |
| POST | `/api/ebr/<id>/etapy-status/zatwierdz` | Zatwierdź aktualny etap → przejdź dalej |
| GET | `/api/ebr/<id>/etapy-analizy` | Już istnieje (Task 4 z pod-projektu 1) |
| POST | `/api/ebr/<id>/etapy-analizy` | Już istnieje |
| GET/POST | `/api/ebr/<id>/korekty` | Już istnieje |

### POST `/api/ebr/<id>/etapy-status/zatwierdz` — body:
```json
{
    "etap": "czwartorzedowanie"
}
```
Efekt: ustawia `czwartorzedowanie.status='done'`, `sulfonowanie.status='in_progress'`.

---

## Pliki do zmiany

| Plik | Akcja | Opis |
|------|-------|------|
| `mbr/models.py` | MODIFY | CREATE TABLE ebr_etapy_status |
| `mbr/etapy_models.py` | MODIFY | init_etapy_status(), get_etapy_status(), zatwierdz_etap() |
| `mbr/app.py` | MODIFY | 2 nowe endpointy (get status, zatwierdz) + init przy tworzeniu EBR |
| `mbr/templates/laborant/_fast_entry_content.html` | MODIFY | Formularz etapu procesowego (renderowany w JS) |
| `mbr/templates/laborant/szarze_list.html` | MODIFY | Pipeline sidebar — klikalne etapy procesowe |

---

## Czego NIE zmieniamy

- Standaryzacja — istniejący cykliczny flow (analiza__1 → dodatki__1 → analiza__2)
- Analiza końcowa — istniejący flow
- Zbiorniki — bez zmian (ETAPY_SIMPLE)
- Produkty bez ETAPY_FULL — bez zmian
