# Laborant input — rozkład kwasów tłuszczowych

## Problem

Parametr `cert_qual_rozklad_kwasow` (id=59 w `parametry_analityczne`) jest pojedynczym parametrem certyfikatowym, ale jego wartość to dystrybucja procentowa wśród 9 łańcuchów: ≤C6:0, C8:0, C10:0, C12:0, C14:0, C16:0, C18:0, C18:1, C18:2.

Dziś:
- Parametr ma `typ='jakosciowy'` z pustym `opisowe_wartosci`. UI fast-entry renderuje pusty `<select>`, więc laborant praktycznie nie może wpisać wartości.
- Wartości pochodzą ze świadectwa zewnętrznego (lab GC). Laborant przepisuje je *po* zamknięciu szarży.
- Od strony świadectwa renderer już rozumie `|` w `wartosc_text` jako line break (commit `d17a08f`).

Brakuje sposobu wpisywania 9 wartości w UI laboranta tak, żeby trafiały do `ebr_wyniki.wartosc_text` jako `v1|v2|...|v9`.

## Zakres

Zmiana dotyczy **wyłącznie** parametru o `kod='cert_qual_rozklad_kwasow'`. Nie tworzymy generycznej "kompozytowej" abstrakcji. Jeśli w przyszłości pojawi się drugi taki parametr, będzie to wyraźny moment do refactoringu na strukturę osadzoną w schemacie (np. nowa kolumna JSON na `parametry_etapy`).

## Architektura

### Komponenty dotknięte

| Plik | Charakter zmiany |
|---|---|
| `mbr/templates/laborant/_fast_entry_content.html` | nowa gałąź renderująca dla `kod === ROZKLAD_KOD`, custom save/load handler |
| `tests/test_laborant_rozklad_kwasow.py` | nowy plik z 3 testami pytest |

Po stronie backendu **nic nie zmieniamy**. Istniejący flow zapisu `wartosc_text` przez endpoint laborant save działa bez ingerencji — łączymy 9 inputów w jeden string `|`-rozdzielony i wysyłamy jak każdą inną wartość jakościową.

### Stałe (top of JS module w template)

```js
const ROZKLAD_KOD = 'cert_qual_rozklad_kwasow';
const ROZKLAD_CHAINS = [
  '≤C6:0', 'C8:0', 'C10:0',
  'C12:0', 'C14:0', 'C16:0',
  'C18:0', 'C18:1', 'C18:2',
];
```

Lista łańcuchów żyje wyłącznie w JS. Nie parsujemy `name_en` ani nie dodajemy nowych kolumn.

### Widoczność

Parametr ma `typ='jakosciowy'`, więc jest filtrowany z fast-entry przez `filter_parametry_lab_for_entry()` dopóki `status != 'completed'`. Po zamknięciu szarży laborant widzi go w sekcji `analiza_koncowa` (gdzie żyje w `parametry_etapy`). Nic w tej regule nie zmieniamy — pasuje do user requirementu "wartości przepisywane ze świadectwa zewnętrznego po ukończeniu analizy".

## UI

Wiersz w fast-entry po wykryciu `pole.kod === ROZKLAD_KOD` zamiast `<select>` renderuje grid 3×3:

```
┌─────────────────────────────────────────────────────────────┐
│  Rozkład kwasów tłuszczowych [%]      [lab zewn. badge]     │
│                                                              │
│   ≤C6:0  [____]    C8:0  [____]    C10:0 [____]             │
│   C12:0  [____]    C14:0 [____]    C16:0 [____]             │
│   C18:0  [____]    C18:1 [____]    C18:2 [____]             │
└─────────────────────────────────────────────────────────────┘
```

- każdy input: `<input type="text">` (nie `inputmode=decimal`, bo wartości mogą zawierać `<`, `≤`, `n.d.`)
- klasa `.ff-rozklad-grid` na kontenerze, `.ff-rozklad-cell` na pojedynczej parze label+input
- `data-rozklad-idx="0..8"` na każdym inpucie (kolejność = `ROZKLAD_CHAINS`)
- `data-kod`, `data-sekcja` na kontenerze (do save'u)
- szerokość inputu ~80px, label ~50px
- wszystkie 9 inputów `disabled` jeżeli `isReadonly` (czyli batch nie jest completed albo brak uprawnień)

## Data flow

### Load

1. Backend wysyła `wartosc_text` w `existing.wartosc_text` (już istniejący kanał).
2. JS w gałęzi `jakosciowy + kod === ROZKLAD_KOD` parsuje:
   ```js
   const parts = (existing?.wartosc_text || '').split('|');
   while (parts.length < 9) parts.push('');
   parts.length = 9; // truncate jeśli więcej (defensywne)
   ```
3. Każdy input dostaje `value = parts[idx]`.

### Save

1. `onchange` / `onblur` na dowolnym z 9 inputów wywołuje `saveRozkladRow(container)`.
2. Funkcja zbiera 9 wartości z DOM po `data-rozklad-idx`:
   ```js
   const values = ROZKLAD_CHAINS.map((_, i) => {
     const inp = container.querySelector(`[data-rozklad-idx="${i}"]`);
     return (inp.value || '').trim();
   });
   ```
3. **Special case**: jeśli wszystkie 9 puste → `wartosc_text = ''` (nie `||||||||`).
   W przeciwnym razie → `values.join('|')` (puste segmenty zachowane, żeby alignment z label-kolumną w cert był poprawny).
4. **Custom save path** (nie reuse'ujemy `doSaveField` — patrz niżej). POST na `/laborant/ebr/{ebr_id}/save` z body:
   ```json
   {
     "sekcja": "<sekcja>",
     "values": {
       "cert_qual_rozklad_kwasow": {
         "wartosc_text": "<joined>",
         "komentarz": "<from textarea, jeśli istnieje>"
       }
     }
   }
   ```
   **Wartość musi iść w polu `wartosc_text` jawnie**, nie w `wartosc`. Backend (`mbr/laborant/models.py:678`) ma jawną gałąź dla `entry.wartosc_text`. Jeśli wyślemy tylko `wartosc: "45|22|18|..."`, backend spróbuje `float()` (line 770), zfailuje i zrobi `continue` (cichy skip — żaden write).
5. **Dlaczego nie reuse `doSaveField`**: ten helper wysyła wyłącznie `wartosc`, i polega na tym, że backend wykryje prefix `<>≤≥` żeby zapisać jako wartosc_text. Dla rozkładu pierwszy łańcuch ma czasem `<1`, ale pozostałe to czyste liczby. Złączony string `<1|45|22|...` zaczyna się od `<` — więc trafiłby do path qualitative i przeszedłby. ALE jeśli laborant wpisze samych liczb (lab raportuje 0 dla detection limit zamiast `<1`), `45|22|18|...` nie ma prefiksu → fail. Ergo: jawny `wartosc_text` jest jedynym solidnym path.
6. **Debounce 1500ms wspólny dla całej grupy** (matching istniejący `_saveTimers` w `autoSaveField`) — szybkie wpisanie 9 wartości daje 1 zapis. Implementacja: pojedynczy `setTimeout` per `(sekcja, kod)`, klucz `sekcja__kod`. Reuse'ujemy `_saveTimers` mapę z istniejącego kodu, żeby `flushPendingSaves()` (wywoływane przed `/complete`) podchwyciło i wywołało nasz handler.

### Audit

Bez zmian — istniejący `update_wartosc_text` w `mbr/laborant/models.py` loguje zmianę `wartosc_text` w `audit_log`. String `|`-rozdzielony jest dla audytu nieprzezroczysty (jeden field), ale to OK — granularność per-łańcuch nie jest wymagana.

## Edge cases

| Sytuacja | Zachowanie |
|---|---|
| Lab raportuje tylko 7/9 łańcuchów | Laborant zostawia 2 inputy puste → save = `v1\|v2\|...\|\|\|` → cert pokaże 2 puste linie wyrównane z label-kolumną. *Feature, nie bug.* |
| Wszystkie 9 puste | Save jako `''` (pusty string), nie `\|\|\|\|\|\|\|\|`. Cert pokaże puste komórki. |
| Whitespace w inpucie | `.trim()` per cell przed join. |
| Wartość zawiera `\|` (literal pipe) | Niemożliwe w praktyce (wartości lab to liczby/`<`/`≤`). Nie escape'ujemy — gdyby się trafiło, save by zniekształcił. Ryzyko akceptowalne. |
| Stored `wartosc_text` ma >9 segmentów (manualna edycja w bazie) | JS truncate'uje do 9 przy load. |
| Stored `wartosc_text` ma <9 segmentów | JS pad'uje do 9 pustymi przy load. |

## Co świadomie nie robimy

- **Walidacja numeryczna**: laborant musi móc wpisać `<1`, `≤0,5`, `n.d.` — przepisuje 1:1 z lab cert.
- **Auto-generowanie braków**: puste = puste, bez zera.
- **Per-łańcuch min/max w `Wymagania`**: kolumna requirement zostaje pojedynczym stringiem (jeśli będzie potrzeba — można `|`-rozdzielić w `parametry_cert.requirement`, ale to osobny ticket).
- **Sumowanie do 100%**: laborant nie pilnuje sumy. Przepisuje co dostał.
- **Per-input audit**: jedna pozycja w audit_log per save całej dziewiątki.

## Testy

### Automatyczne (pytest, `tests/test_laborant_rozklad_kwasow.py`)

1. **`test_rozklad_template_constants_present`** — czyta `_fast_entry_content.html`, sprawdza że zawiera `'cert_qual_rozklad_kwasow'` i wszystkie 9 chain labels (`'≤C6:0'`, `'C8:0'`, …, `'C18:2'`). Smoke test — łapie regresje gdy ktoś usunie albo zrefaktoruje hardcode.

2. **`test_wartosc_text_roundtrip_with_pipes`** — insert do `ebr_wyniki` z `wartosc_text='<1|45|22|18|10|3|1|0|0'`, read przez `get_ebr_wyniki`, sprawdź string identyczny. Pilnuje że `|` nie jest mangle'owane przez SQLite/serializację po drodze.

3. **`test_cert_renders_pipes_as_line_breaks_for_rozklad`** — render świadectwa Monamid_KO/avon z `wartosc_text` 9-elementowym dla `cert_qual_rozklad_kwasow` → XML wyniku świadectwa zawiera 8 `<w:br/>` w komórce result (i 8 w komórce name_en). Defense-in-depth dla istniejącej zmiany d17a08f.

### Manualne (test plan dla developera)

1. Stworzyć szarżę Monamid_KO lokalnie.
2. Wypełnić wymagane etapy, zamknąć szarżę (`status=completed`).
3. Otworzyć fast-entry tej szarży → sekcja `analiza_koncowa` ma wiersz "Rozkład kwasów tłuszczowych [%]" z gridem 3×3.
4. Wpisać 9 wartości testowych → odświeżyć stronę → wartości się zachowały w gridzie.
5. Wygenerować świadectwo Avon → kolumna Wynik ma 9 linii wyrównanych z 9 łańcuchami w kolumnie Nazwa.
6. Wyczyścić 2 środkowe wartości → odświeżyć → puste w gridzie. Świadectwo: 2 puste linie między wartościami.
7. Wyczyścić wszystkie 9 → świadectwo ma pustą komórkę Wynik.

## Out of scope (przyszłe iteracje)

- Generyczna kompozycja parametrów (gdyby pojawił się drugi taki przypadek)
- Walidacja sumy %
- Per-łańcuch wymagania w kolumnie `requirement` świadectwa
- Mobile layout (grid 3×3 może wymagać `grid-template-columns: repeat(3, 1fr)` z fluid widths)
