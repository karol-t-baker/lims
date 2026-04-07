# B2: Zbiorniki jako encja — Design Spec

## Cel

Stworzyć globalne źródło prawdy dla zbiorników magazynowych (M1-M19), umożliwić powiązanie szarża→zbiornik z masą, wyświetlać stickery zbiorników w registry, dać adminowi panel CRUD.

## Baza danych

### Tabela `zbiorniki`

```sql
CREATE TABLE IF NOT EXISTS zbiorniki (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nr_zbiornika TEXT UNIQUE NOT NULL,
    max_pojemnosc REAL,
    produkt TEXT,
    aktywny INTEGER DEFAULT 1
);
```

### Tabela `zbiornik_szarze`

Powiązanie szarża → zbiornik (many-to-many z masą):

```sql
CREATE TABLE IF NOT EXISTS zbiornik_szarze (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ebr_id INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
    zbiornik_id INTEGER NOT NULL REFERENCES zbiorniki(id),
    masa_kg REAL,
    dt_dodania TEXT,
    UNIQUE(ebr_id, zbiornik_id)
);
```

Szarża może trafić do wielu zbiorników. Zbiornik akumuluje wiele szarż (mieszanie).

## Seed

19 zbiorników wstawianych w `init_mbr_tables()` jako `INSERT OR IGNORE`:

```
M1  30t Cheginy GLOL    M8  25t Olej palmowy     M15 42t Cheginy K7
M2  30t Cheginy GLO     M9  22t Cheginy          M16 25t Cheginy GL
M3  35t Cheginy GLOL    M10 33t Chelamid          M17 25t Cheginy GLO
M4  20t Alkohole Ceto.  M11 30t Kwasy kokosowe    M18 27t Chelamid DK
M5  27t DEA             M12 30t DMAPA             M19 25t Kwasy kokosowe
M6  25t Chelamid DK     M13 25t Olej kokosowy
M7  12t Olej palmowy    M14 48t Cheginy KK
```

## API

### Zbiorniki CRUD (admin)

- `GET /api/zbiorniki` — lista aktywnych zbiorników (+ `?all=1` dla nieaktywnych)
- `POST /api/zbiorniki` — dodaj zbiornik `{nr_zbiornika, max_pojemnosc, produkt}`
- `PUT /api/zbiorniki/<id>` — edytuj `{max_pojemnosc?, produkt?, aktywny?}`

### Powiązania szarża↔zbiornik

- `GET /api/zbiornik-szarze/<ebr_id>` — lista zbiorników przypisanych do szarży
- `POST /api/zbiornik-szarze` — powiąż `{ebr_id, zbiornik_id, masa_kg}`
- `DELETE /api/zbiornik-szarze/<id>` — usuń powiązanie

## Admin panel — rail "Zbiorniki"

Nowy widok w panelu admina. Tabela:

| Nr | Pojemność [t] | Produkt | Aktywny |
|----|:------------:|---------|:-------:|
| M1 | 30 | Cheginy GLOL | ✓ |
| ... | ... | ... | ... |

Funkcje:
- Edycja inline — klik na pojemność lub produkt → edycja → auto-save
- Przycisk "Dodaj zbiornik" — formularz z nr, pojemność, produkt
- Toggle aktywny/nieaktywny (soft-delete, nie usuwamy fizycznie)

## UI — sekcja "Zbiorniki docelowe" w fast entry

W karcie szarży (pod analizą końcową lub w sekcji przepompowania), sekcja:

```
Zbiorniki docelowe
┌─────────────────────────────────────────────┐
│ [Dropdown: M1 - M19]  [Masa: ___ kg]  [+]  │
│                                             │
│  M1 (Cheginy GLOL) — 12 500 kg    [✕]      │
│  M3 (Cheginy GLOL) — 8 200 kg     [✕]      │
└─────────────────────────────────────────────┘
```

- Dropdown filtrowany po aktywnych zbiornikach
- Pole masa_kg (opcjonalne — można dodać później)
- Lista przypisanych z możliwością usunięcia
- Widoczne zarówno przy otwartej jak i ukończonej szarży
- Auto-save po dodaniu/usunięciu (fetch do API)

## Stickery w registry

W `_buildRegistryRow()` — po numerze szarży, wyświetlić badge'y zbiorników:

```
2/2026  [M1] [M3]  CoA  |  12.04  |  pH 6.2  |  ...
```

Styl: małe szare/niebieskie badge'y, font-size 9px. Dane z `zbiornik_szarze` dołączane JOIN-em w `list_completed_registry()`.

## Pliki

| Action | File | Purpose |
|--------|------|---------|
| Create | `mbr/zbiorniki/__init__.py` | Blueprint definition |
| Create | `mbr/zbiorniki/models.py` | CRUD functions: list, create, update, get_for_ebr, link, unlink |
| Create | `mbr/zbiorniki/routes.py` | API endpoints |
| Create | `mbr/templates/admin/zbiorniki.html` | Admin CRUD panel |
| Modify | `mbr/models.py` | Nowe tabele + seed w `init_mbr_tables()` |
| Modify | `mbr/app.py` | Register zbiorniki blueprint |
| Modify | `mbr/templates/laborant/_fast_entry_content.html` | Sekcja "Zbiorniki docelowe" |
| Modify | `mbr/templates/laborant/szarze_list.html` | Stickery zbiorników w registry |
| Modify | `mbr/registry/models.py` | JOIN zbiornik_szarze w registry query |

## Poza scopem (na później — sub-projekt D)

- Edycja powiązań po ukończeniu szarży
- Automatyczne wyliczenie masy ostatniego zbiornika
- Bilans masowy / szacowanie parametrów po zmieszaniu
- Precyzyjne rozlewanie z masami per zbiornik
