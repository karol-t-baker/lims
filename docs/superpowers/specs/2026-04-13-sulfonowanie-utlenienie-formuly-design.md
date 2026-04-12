# Etap sulfonowania/utlenienia + formuly korekt — spec

## Cel

Rozszerzyc pipeline 4 produktow (K40GLOL/GLO/GL/K7) o etapy sulfonowanie i utlenienie z automatycznym obliczaniem dawki perhydrolu. Dodac formuly korekt (woda, NaCl) do standaryzacji. Odblokowac edycje parametrow dla laboranta we wszystkich etapach pipeline.

## Pipeline 4 produktow (docelowy)

1. Sulfonowanie (jednorazowy) — odnotowanie wynikow po sulfonowaniu
2. Utlenienie (cykliczny) — dawka perhydrolu, bramka SO3 < cel
3. Standaryzacja (cykliczny) — korekty woda/NaCl z formulami
4. Analiza koncowa (jednorazowy) — pelny panel

## Nowe etapy

### Sulfonowanie

- Typ: jednorazowy
- Parametry: SO3, pH 10%, nD20, Barwa
- Bramka: brak (informacyjny)
- Korekty: brak (korekty ida w utlenieniu)

### Utlenienie

- Typ: cykliczny
- Parametry: SO3, H2O2, pH 10%, nD20, Barwa
- Bramka: SO3 <= target (z produkt_etap_limity.target)
- Korekty: Perhydrol 34% (z formula)
- Target per produkt: SO3 cel (np. 0.03), H2O2 cel (np. 0.005)

## Formuly korekt

### Masa efektywna (wspolna)

```
Meff = wielkosc_szarzy_kg > 6600 ? wielkosc_szarzy_kg - 1000 : wielkosc_szarzy_kg - 500
```

### Perhydrol (utlenienie)

```
dawka_sulf = (C_so3 - target_so3) * 0.01214 * Meff
dawka_nadtl = target_h2o2 > 0 ? target_h2o2 * Meff / 350 : 0
dawka = dawka_sulf + dawka_nadtl
```

Zmienne:
- C_so3 = biezacy pomiar SO3 (z wynikow rundy)
- target_so3 = cel SO3 (z produkt_etap_limity.target dla parametru so3)
- target_h2o2 = cel H2O2 (z produkt_etap_limity.target dla parametru h2o2, 0 jesli brak)
- Meff = masa efektywna szarzy

### Woda (standaryzacja)

```
dawka = (R0 - Rk) * Meff / (Rk - 1.333)
```

Zmienne:
- R0 = biezacy pomiar nD20 (z wynikow)
- Rk = target nD20 (z produkt_etap_limity.target dla nd20)
- Meff = masa efektywna

### NaCl (standaryzacja)

```
dawka = (Ck / 100 * Mc - Meff * Ccl / 100) / (1 - Ck / 100)
```

Zmienne:
- Ccl = biezacy pomiar NaCl % (z wynikow)
- Ck = target NaCl % (z produkt_etap_limity.target dla nacl)
- Meff = masa efektywna
- Mc = Meff + woda_korekta (masa po korekcie woda, 0 jesli brak korekty wody w tej rundzie)

## Przechowywanie formul

Kolumny `formula_ilosc` i `formula_zmienne` w `etap_korekty_katalog` (juz istnieja, puste).

`formula_ilosc` — wyrazenie JS (ewaluowane przez `new Function()` po podstawieniu zmiennych)
`formula_zmienne` — JSON opisujacy zrodla zmiennych (dokumentacyjne, nie parsowane automatycznie)

Formuly sa konfigurowane w setup skrypcie, nie w UI (na razie).

## Ewaluacja formul w JS

W panelu korekty (`loadCorrectionPanel`), jesli korekta ma `formula_ilosc`:

1. Zbierz zmienne:
   - Pomiary biezacej rundy: `wyniki[sekcja][kod].wartosc`
   - Targety: z `pola` array (adapter przekazuje `target` per parametr)
   - Masa szarzy: z `ebr.wielkosc_szarzy_kg` (dostepne w JS)
2. Podstaw zmienne do formuly
3. Oblicz `new Function(zmienne, 'return ' + formula)(wartosci)`
4. Wyswietl jako pre-filled wartosc w inpucie korekty (laborant moze nadpisac)

## Adapter — zmiany

`build_pipeline_context` juz przekazuje `target` w polach. Sprawdzic czy `formula_ilosc` i `formula_zmienne` sa w response `korekty_katalog` z lab API.

Lab API endpoint `GET /api/pipeline/lab/ebr/<id>/etap/<etap_id>` zwraca `korekty_katalog` z `list_etap_korekty()`. Ta funkcja zwraca wszystkie kolumny w tym `formula_ilosc`, `formula_zmienne`. Wiec dane juz sa dostepne — potrzeba tylko JS do ewaluacji.

## Edycja parametrow laboranta — odblokowanie

### Problem

`renderOneSection` w `_fast_entry_content.html` (linia ~2360) pokazuje przycisk edycji (olowek) tylko dla `sekcja === 'analiza_koncowa'`:

```javascript
if (sekcja === 'analiza_koncowa' && userRola !== 'cert' && !isReadonly) {
    editBtn = '...';
}
```

### Rozwiazanie

Zmienic warunek na: pokaz olowek dla kazdej sekcji pipeline (nie tylko analiza_koncowa):

```javascript
var isPipelineSection = etapy.some(function(e) { return e.pipeline_etap_id && e.sekcja_lab === baseSekcja; });
if ((sekcja === 'analiza_koncowa' || isPipelineSection) && userRola !== 'cert' && !isReadonly) {
    editBtn = '...';
}
```

### openParamEditor — kontekst sekcji

Istniejacy `openParamEditor()` fetchuje bindingi z `/api/parametry/etapy/<produkt>/analiza_koncowa`. Dla pipeline sekcji musi uzywac odpowiedniego kontekstu.

Zmiana: `openParamEditor(kontekst)` — parametr kontekstu, domyslnie 'analiza_koncowa' dla backward compat.

Przycisk olowek wywoluje `openParamEditor('standaryzacja')` zamiast `openParamEditor()`.

Endpoint `/api/parametry/etapy/<produkt>/<kontekst>` juz obsluguje pipeline (zrobione wczesniej) — mapuje kontekst na etap_id i zwraca dane z `produkt_etap_limity`.

## Zmiany w plikach

### Backend
- `scripts/setup_sulfonowanie_utlenienie.py` — nowy skrypt: tworzy etapy, dodaje do pipeline, wypelnia formuly
- `mbr/pipeline/models.py` — `list_etap_korekty` juz zwraca `formula_ilosc`/`formula_zmienne` — sprawdzic

### Frontend
- `_fast_entry_content.html`:
  - Odblokowanie olowka edycji dla wszystkich sekcji pipeline
  - `openParamEditor(kontekst)` — parametr kontekstu
  - `loadCorrectionPanel` — ewaluacja formul, pre-fill inputow
  - Dostep do `wielkosc_szarzy_kg` w JS (sprawdzic czy jest w kontekscie)

### Admin UI
- `pipeline_edit.html` — kolumna Target w panelu limitow (juz jest)

## Zakres

### Budujemy
- Etapy sulfonowanie + utlenienie w pipeline 4 produktow
- Formuly korekt: perhydrol, woda, NaCl
- Pre-fill korekty z obliczona dawka (edytowalny)
- Olowek edycji parametrow we wszystkich sekcjach pipeline
- Targety per produkt w produkt_etap_limity

### NIE budujemy
- Formula kwasu cytrynowego (pozniej)
- UI edycji formul w admin (formuly w skrypcie setup)
- Automatyczne przeliczanie Mc (woda+kwas) w formule NaCl (uproszczenie: Mc = Meff)
