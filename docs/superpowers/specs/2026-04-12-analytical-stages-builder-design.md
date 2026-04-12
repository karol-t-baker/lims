# Builder etapow analitycznych — spec V1

## Cel

Modul do projektowania szablonow etapow analitycznych (MBR) przez admina. Globalny katalog etapow z parametrami, warunkami bramkowymi i korektami, przypisywany do produktow jako pipeline. Laborant wykonuje analizy w sekwencji etapow z automatyczna ocena bramek.

Nadrzedny cel: zbieranie w pelni znormalizowanych danych analitycznych pod przyszle modele ML/DL.

## Uzytkownicy

- **Admin** (V1) — tworzy katalog etapow, definiuje pipeline per produkt
- **Laborant** — wykonuje analizy w fast entry, widzi bramki, zaleca korekty

## Model danych

### Tabele definicji (admin/technolog)

#### parametry_analityczne — BEZ ZMIAN
Istniejaca tabela z 55+ parametrami. Nietykalna.

#### etapy_analityczne (NOWA — globalny katalog)
```sql
CREATE TABLE etapy_analityczne (
    id                  INTEGER PRIMARY KEY,
    kod                 TEXT NOT NULL UNIQUE,
    nazwa               TEXT NOT NULL,
    opis                TEXT,
    typ_cyklu           TEXT NOT NULL DEFAULT 'jednorazowy'
                        CHECK(typ_cyklu IN ('jednorazowy', 'cykliczny')),
    aktywny             INTEGER DEFAULT 1,
    kolejnosc_domyslna  INTEGER DEFAULT 0
);
```
- `jednorazowy` — jedna runda analiz, sprawdz bramke, idz dalej
- `cykliczny` — analiza -> korekta -> ponowna analiza (n rund az bramka OK)

#### etap_parametry (NOWA — zastepuje parametry_etapy)
```sql
CREATE TABLE etap_parametry (
    id              INTEGER PRIMARY KEY,
    etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
    parametr_id     INTEGER NOT NULL REFERENCES parametry_analityczne(id),
    kolejnosc       INTEGER DEFAULT 0,
    min_limit       REAL,
    max_limit       REAL,
    nawazka_g       REAL,
    precision       INTEGER,
    target          REAL,
    wymagany        INTEGER DEFAULT 0,
    grupa           TEXT DEFAULT 'lab',
    formula         TEXT,
    sa_bias         REAL,
    krok            INTEGER,
    UNIQUE(etap_id, parametr_id)
);
```

#### produkt_pipeline (NOWA — etapy per produkt z kolejnoscia)
```sql
CREATE TABLE produkt_pipeline (
    id              INTEGER PRIMARY KEY,
    produkt         TEXT NOT NULL,
    etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
    kolejnosc       INTEGER NOT NULL,
    UNIQUE(produkt, etap_id)
);
```

#### produkt_etap_limity (NOWA — nadpisania limitow per produkt x etap x parametr)
```sql
CREATE TABLE produkt_etap_limity (
    id              INTEGER PRIMARY KEY,
    produkt         TEXT NOT NULL,
    etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
    parametr_id     INTEGER NOT NULL REFERENCES parametry_analityczne(id),
    min_limit       REAL,
    max_limit       REAL,
    nawazka_g       REAL,
    precision       INTEGER,
    target          REAL,
    UNIQUE(produkt, etap_id, parametr_id)
);
```

#### etap_warunki (NOWA — warunki bramkowe)
```sql
CREATE TABLE etap_warunki (
    id              INTEGER PRIMARY KEY,
    etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
    parametr_id     INTEGER NOT NULL REFERENCES parametry_analityczne(id),
    operator        TEXT NOT NULL CHECK(operator IN ('<', '<=', '>=', '>', 'between', '=')),
    wartosc         REAL,
    wartosc_max     REAL,
    opis_warunku     TEXT
);
```

#### etap_korekty_katalog (NOWA — dozwolone korekty per etap)
```sql
CREATE TABLE etap_korekty_katalog (
    id              INTEGER PRIMARY KEY,
    etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
    substancja      TEXT NOT NULL,
    jednostka       TEXT DEFAULT 'kg',
    wykonawca       TEXT NOT NULL DEFAULT 'produkcja'
                    CHECK(wykonawca IN ('laborant', 'produkcja')),
    kolejnosc       INTEGER DEFAULT 0,
    formula_ilosc   TEXT,
    formula_zmienne TEXT,
    formula_opis    TEXT
);
```
Kolumny `formula_*` przygotowane pod V2 (automatyczne obliczanie korekt). W V1 puste.

### Tabele wykonania (EBR — dane szarzowe)

#### ebr_etap_sesja (NOWA — jedna runda analizy w etapie)
```sql
CREATE TABLE ebr_etap_sesja (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ebr_id          INTEGER NOT NULL REFERENCES ebr_batches(ebr_id),
    etap_id         INTEGER NOT NULL REFERENCES etapy_analityczne(id),
    runda           INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'w_trakcie'
                    CHECK(status IN ('w_trakcie', 'ok', 'poza_limitem', 'oczekuje_korekty')),
    dt_start        TEXT,
    dt_end          TEXT,
    laborant        TEXT,
    decyzja         TEXT CHECK(decyzja IN ('przejscie', 'korekta')),
    komentarz       TEXT,
    UNIQUE(ebr_id, etap_id, runda)
);
```

#### ebr_pomiar (NOWA — jeden pomiar = jeden wiersz)
```sql
CREATE TABLE ebr_pomiar (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sesja_id        INTEGER NOT NULL REFERENCES ebr_etap_sesja(id),
    parametr_id     INTEGER NOT NULL REFERENCES parametry_analityczne(id),
    wartosc         REAL,
    min_limit       REAL,
    max_limit       REAL,
    w_limicie       INTEGER,
    is_manual       INTEGER NOT NULL DEFAULT 1,
    dt_wpisu        TEXT NOT NULL,
    wpisal          TEXT NOT NULL,
    UNIQUE(sesja_id, parametr_id)
);
```
`min_limit`, `max_limit` — snapshot limitu w momencie pomiaru (jesli technolog pozniej zmieni limity, historyczne dane zachowuja kontekst).

#### ebr_korekta (NOWA — przebudowana)
```sql
CREATE TABLE ebr_korekta (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sesja_id        INTEGER NOT NULL REFERENCES ebr_etap_sesja(id),
    korekta_typ_id  INTEGER NOT NULL REFERENCES etap_korekty_katalog(id),
    ilosc           REAL,
    zalecil         TEXT,
    wykonawca_info  TEXT,
    dt_zalecenia    TEXT,
    dt_wykonania    TEXT,
    status          TEXT NOT NULL DEFAULT 'zalecona'
                    CHECK(status IN ('zalecona', 'wykonana', 'anulowana'))
);
```

### Tabela certyfikatowa (wyniesiena z parametry_etapy)

Kolumny `on_cert`, `cert_requirement`, `cert_format`, `cert_qualitative_result`, `cert_kolejnosc`, `cert_variant_id` przenoszone do istniejacej tabeli `parametry_cert`.

### Resolucja limitow (trojpoziomowa)

1. `etap_parametry.min_limit/max_limit` — domyslne globalne per etap
2. `produkt_etap_limity.min_limit/max_limit` — nadpisanie per produkt (jesli wiersz istnieje, wygrywa)
3. Snapshot do `ebr_pomiar.min_limit/max_limit` w momencie zapisu

## UI Builder (admin)

### 3.1 Katalog etapow (`/admin/etapy-analityczne`)

Lista globalnych etapow. CRUD: dodaj, edytuj, dezaktywuj (nie usuwaj).

Edycja etapu — trzy panele:
- **Parametry domyslne** — tabela: parametr (dropdown z parametry_analityczne), min, max, nawazka, bramkowy?
- **Warunki przejscia** — lista warunkow bramkowych z operatorem i wartoscia
- **Dozwolone korekty** — tabela: substancja, jednostka, wykonawca (laborant/produkcja)

### 3.2 Pipeline produktu (`/admin/produkt/<produkt>/pipeline`)

Sekwencja etapow z katalogu przypisana do produktu. Przyciski gora/dol do zmiany kolejnosci.

Klik na edycje etapu w kontekscie produktu otwiera panel nadpisywania limitow:
- Pokazuje domyslne limity z katalogu
- Pozwala nadpisac min/max/nawazka/target per produkt
- Puste pole = bierz domyslne

## Flow laboranta (fast entry v2)

### Sekwencja pracy

1. Laborant otwiera szarze -> system buduje formularz z `produkt_pipeline`
2. Sidebar: lista etapow ze statusem (checkmark/dot/circle)
3. Laborant wchodzi w biezacy etap -> widzi parametry do pomiaru
4. Wpisuje wyniki — auto-save AJAX na blur (jak dzis)
5. System sprawdza warunki bramkowe automatycznie
6. **Warunek OK** -> przycisk "Zatwierdz etap" -> etap zamkniety, nastepny aktywny
7. **Warunek NIE OK** -> system pokazuje dostepne korekty z katalogu
8. Laborant wpisuje zalecana ilosc, klika "Zalec korekte" -> `ebr_korekta(status='zalecona')`
9. Probka wraca po korekcie -> laborant klika "Nowa runda" -> `ebr_etap_sesja(runda=2)`
10. Nowe pomiary -> ponowne sprawdzenie bramki
11. Cykl powtarza sie az warunek spelniony

### Co sie nie zmienia
- Auto-save na blur
- Kalkulator miareczkowy (modal)
- Formatowanie polskie (przecinek)
- Kolorowanie limitow (czerwone/zielone)

### Co sie zmienia
- Sidebar z lista etapow zamiast zakladek sekcji
- Jawne rundy zamiast ukrytego `analiza__1`, `analiza__2`
- Automatyczna ocena bramki zamiast recznego decydowania
- Korekty z katalogu zamiast wolnego tekstu

## ML/DL — sciezka danych

Jeden flat query daje caly dataset:
```sql
SELECT
    b.produkt, b.nr_partii, b.wielkosc_szarzy_kg,
    ea.kod AS etap, s.runda,
    pa.kod AS parametr, p.wartosc, p.min_limit, p.max_limit, p.w_limicie,
    s.decyzja,
    k.ilosc AS korekta_ilosc, ek.substancja AS korekta_substancja
FROM ebr_pomiar p
JOIN ebr_etap_sesja s ON s.id = p.sesja_id
JOIN ebr_batches b ON b.ebr_id = s.ebr_id
JOIN etapy_analityczne ea ON ea.id = s.etap_id
JOIN parametry_analityczne pa ON pa.id = p.parametr_id
LEFT JOIN ebr_korekta k ON k.sesja_id = s.id
LEFT JOIN etap_korekty_katalog ek ON ek.id = k.korekta_typ_id;
```

## Przygotowanie pod V2

- `etap_korekty_katalog.formula_*` — pola na formuly obliczania korekt (V1: puste, V2: technolog definiuje formuly, system podpowiada laborantowi)
- `etap_parametry.target` — wartosc docelowa, wchodzi do formul korekcyjnych
- Przyszly ML moze zastapic reczne formuly predykcjami: "przy SM=42% i szarzy 12000kg, optymalna korekta woda = X kg"

## Zakres V1

### Budujemy:
1. Nowe tabele (schema + init w `models.py`)
2. Skrypt migracyjny: `parametry_etapy` -> nowe tabele
3. UI builder (admin): katalog etapow + pipeline produktu
4. Fast entry v2: sidebar etapow, bramki, korekty, rundy
5. Seed: dane z istniejacego `parametry_etapy`

### NIE budujemy:
- Drag-and-drop (gora/dol wystarczy)
- Formuly korekt (pola istnieja, UI w V2)
- Generowanie PDF karty szarzowej (osobny projekt)
- Etapy procesowe (zostaja w starym modelu)
- Wersjonowanie pipeline'u

### Kompatybilnosc wsteczna
W V1 nowe szarze nadal tworza MBR z `parametry_lab` generowanym automatycznie z pipeline'u. W V2 fast_entry czyta bezposrednio z pipeline'u i JSON-y odchodza.

### Migracja
Jednorazowy skrypt:
- unikalne `kontekst` z `parametry_etapy` -> wiersze w `etapy_analityczne`
- wiazania parametr x kontekst -> `etap_parametry`
- wiazania produkt x kontekst -> `produkt_pipeline` + `produkt_etap_limity`
- kolumny cert -> `parametry_cert`
- `parametry_etapy` zostaje read-only jako backup
