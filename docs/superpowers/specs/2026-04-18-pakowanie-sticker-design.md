# Sticker IBC/Beczki w rejestrze ukończonych

**Data:** 2026-04-18
**Zakres:** mała inline etykieta dla szarż z `pakowanie_bezposrednie` w tabeli Rejestr ukończonych (analogicznie do `td-cert-badge` "CoA" i `td-zb-sticker` numer zbiornika)
**Status:** zatwierdzony do pisania planu

## Kontekst

Kolumna "Nr partii" w rejestrze ukończonych (`szarze_list.html:1440`) pokazuje obok numeru dwa stickery:
- `td-cert-badge` — zielony "CoA", gdy wydano świadectwo
- `td-zb-sticker` — niebieski numer zbiornika, dla każdego powiązanego zbiornika

Szarże z `pakowanie_bezposrednie IN ('IBC','Beczki')` to nietypowe przypadki (bezpośrednie pakowanie zamiast pompowania do zbiornika). Użytkownik chce trzeci sticker analogicznie do pozostałych, żeby te szarże były widoczne w skanowaniu wzrokiem listy.

## Niezmienne założenia

- Jeden sticker per szarża (max jedna wartość `pakowanie_bezposrednie`), tekst to dokładnie `IBC` albo `Beczki`
- Żadnych zmian w schemacie DB (`pakowanie_bezposrednie` już istnieje)
- Tylko widok Rejestr ukończonych — inne widoki bez zmian
- Kolor odmienny od istniejących stickerów (żeby nie mylić z CoA/zbiornik)

## Rozwiązanie

### Backend — `list_completed_registry`

W `mbr/registry/models.py:14`, rozszerzyć SELECT o kolumnę `eb.pakowanie_bezposrednie`:

```python
sql = """
    SELECT eb.ebr_id, eb.batch_id, eb.nr_partii, mt.produkt, eb.dt_end, eb.typ,
           eb.nr_zbiornika, eb.uwagi_koncowe, eb.pakowanie_bezposrednie
    FROM ebr_batches eb
    ...
"""
```

Pole `b.pakowanie_bezposrednie` trafia do JSON-a zwracanego przez `/api/registry` i dociera do frontend-u per szarża.

### Frontend — renderer wiersza

W `mbr/templates/laborant/szarze_list.html:1440`, dopisać warunkowo po zbiornikach:

```javascript
html += '<td class="td-nr">' + nrHtml
      + (b.cert_count > 0 ? ' <span class="td-cert-badge">CoA</span>' : '')
      + (b.zbiorniki && b.zbiorniki.length > 0
           ? b.zbiorniki.map(function(nr) { return ' <span class="td-zb-sticker">' + nr + '</span>'; }).join('')
           : '')
      + (b.pakowanie_bezposrednie
           ? ' <span class="td-pak-sticker">' + b.pakowanie_bezposrednie + '</span>'
           : '')
      + '</td>';
```

### CSS — nowa klasa

W tym samym pliku w bloku `<style>` (obok `.td-zb-sticker`, ok. lina 309), dodać:

```css
.td-pak-sticker {
    display: inline-block;
    padding: 1px 5px;
    font-size: 9px;
    font-weight: 600;
    font-family: var(--mono);
    background: #fef3c7;        /* amber-100, jasnopomarańczowe tło */
    color: #92400e;             /* amber-800, ciemnopomarańczowy tekst */
    border-radius: 3px;
    margin-left: 3px;
}
```

Kolor amber odróżnia od zielonego CoA i niebieskiego zbiornik.

### Legenda (opcjonalnie)

W sekcji legendy (linia 556 — `<span class="reg-legend-item">...</span>`) dopisać:

```html
<span class="reg-legend-item">
  <span class="td-pak-sticker" style="font-size:7px;padding:1px 4px;">IBC</span>
  pakowanie bezpośrednie (IBC / Beczki)
</span>
```

Żeby operator wiedział co oznacza sticker bez czytania dokumentacji.

## Weryfikacja

1. Szarża z `pakowanie_bezposrednie='IBC'` — w kolumnie Nr partii widać sticker `IBC` obok numeru (amber).
2. Szarża z `pakowanie_bezposrednie='Beczki'` — sticker `Beczki`.
3. Szarża z `pakowanie_bezposrednie=NULL` — brak stickera.
4. Szarża która ma jednocześnie CoA + zbiornik + IBC → trzy stickery w jednej linii.
5. API `/api/registry?produkt=Chegina_K7` zwraca `pakowanie_bezposrednie` w każdym obiekcie batches.

## Out of scope

- Filtrowanie po pakowanie w tabeli (można dodać w przyszłości)
- Retroaktywna migracja (nie dotyczy, to tylko UI change)
- Zmiany w widokach aktywnych szarż, PDF karcie, cert-ach

## Kryteria akceptacji

- Szarże IBC/Beczki rozpoznawalne w Rejestrze ukończonych bez klikania szczegółów
- Kolor stickera odróżnia od CoA i zbiornik
- Brak regresji — rzędy bez pakowania wyglądają tak samo jak przedtem
