# Kolumna "Surowce" w Rejestrze Ukończonych

**Data:** 2026-04-18
**Status:** spec

## Cel

Pokazać numery partii surowców wykorzystanych w szarży w tabelce Rejestru Ukończonych (`/laborant/szarze` → zakładka Ukończone). Dane są już zbierane przy tworzeniu szarży (modal "Nowa szarża", input substraty) i zapisywane w tabeli `platkowanie_substraty`; obecnie widoczne tylko w hero widoku szczegółu szarży. Dodajemy je do wiersza listy.

## Zakres

- Produkty z wpisami w `substrat_produkty` → kolumna "Surowce" pojawia się w ich rejestrze ukończonych. Obecnie: `Alkinol` + `Alkinol_B`. Skalowalne — kolejny produkt w `substrat_produkty` automatycznie dostaje kolumnę.
- Inne produkty — kolumna niewidoczna (żadnej zmiany).
- Żadnych zmian w modalu nowej szarży ani w hero (dane + UI tam już są).

## Decyzje

| Pytanie | Decyzja |
|---|---|
| Kształt danych surowców per szarża | Stała lista per produkt (z `substrat_produkty`). Dane już są. |
| Display w tabeli | Jedna kolumna "Surowce", format `Nazwa: p1, p2 · Nazwa2: p3` (mono, truncate + tooltip) |
| 2 wiersze tego samego surowca | Grupowane po nazwie, partie joined przecinkiem |
| Gdy produkt nie ma surowców | Kolumna niewidoczna (nie puste td w innych produktach) |
| Gdy szarża nie ma partii (choć produkt je ma) | `—` |

## Zmiany

### Backend — `mbr/registry/models.py`

`get_registry_columns(db, produkt)` — na końcu listy columns dorzucić:

```python
has_surowce = db.execute(
    "SELECT 1 FROM substrat_produkty WHERE produkt=? LIMIT 1", (produkt,)
).fetchone() is not None
if has_surowce:
    columns.append({"kod": "__surowce__", "label": "Surowce", "is_surowce": True})
```

`get_registry_rows(db, produkt)` (albo dowolna funkcja agregująca dane per batch) — dla każdej szarży dorzucić:

```python
batch["surowce"] = [dict(r) for r in db.execute(
    "SELECT s.nazwa, ps.nr_partii_substratu AS nr_partii "
    "FROM platkowanie_substraty ps JOIN substraty s ON s.id = ps.substrat_id "
    "WHERE ps.ebr_id = ? ORDER BY s.nazwa",
    (batch["ebr_id"],)
).fetchall()]
```

### Frontend — `mbr/templates/laborant/szarze_list.html`

W `_buildRegistryRow(columns, b)` (ok. linia 1446) — dla kolumny `col.kod === '__surowce__'`:

```javascript
if (col.kod === '__surowce__') {
  var grouped = {};
  (b.surowce || []).forEach(function(s) {
    if (!grouped[s.nazwa]) grouped[s.nazwa] = [];
    if (s.nr_partii) grouped[s.nazwa].push(s.nr_partii);
  });
  var parts = Object.keys(grouped).map(function(nazwa) {
    return nazwa + ': ' + (grouped[nazwa].length ? grouped[nazwa].join(', ') : '—');
  });
  var txt = parts.join(' · ') || '—';
  var esc = txt.replace(/"/g, '&quot;');
  html += '<td class="td-surowce" title="' + esc + '">' + txt + '</td>';
  return;
}
```

Header rendering — nie wymaga specjalnej obsługi; "Surowce" renderuje się jak każda inna kolumna. Opcjonalnie wyrównanie left.

### CSS — `mbr/static/style.css`

Dopisać (obok `.td-nr`, `.td-date`):

```css
.td-surowce {
  font-family: var(--mono); font-size: 11px;
  color: var(--text-sec);
  max-width: 240px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  text-align: left !important;
}
.registry thead th.th-surowce { text-align: left; }
```

## Testy

Dodać do `tests/test_registry.py` (jeśli istnieje, inaczej new file):

1. `test_registry_columns_includes_surowce_for_alkinol` — produkt z wpisami w `substrat_produkty` ma kolumnę `__surowce__`.
2. `test_registry_columns_skips_surowce_for_other_products` — produkt bez wpisów nie ma kolumny.
3. `test_registry_row_surowce_joined_by_comma` — szarża z 2 wierszami tego samego surowca zwraca obie partie w `batch["surowce"]`.

## Ryzyko

- **Migracja/dane:** Żadna — tabele już istnieją, dane już są zapisywane. To tylko renderowanie.
- **Produkty inne niż Alkinol**: kolumna niewidoczna, zero wpływu.
- **Długa lista surowców** (>3): ellipsis + tooltip. Cmd+hover pokazuje pełną listę.

## Wykonanie

Bez osobnego planu implementacyjnego — zmiana punktowa, jeden commit:
1. Backend: rozszerzenie `get_registry_columns` + `get_registry_rows`
2. Frontend: cell renderer + CSS
3. Testy: 3 pozycje
