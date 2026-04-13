# Panel decyzji etapow — spec

## Problem

Sulfonowanie nie ma opcji perhydrolu. "Zatwierdz etap" pojawia sie bezwarunkowo. Brak mechanizmu "korekta + przejscie do nastepnego etapu". Laborant musi miec dwa jawne przyciski: korekta (petla) albo przejscie (z opcjonalna korekta przejsciowa).

## Cel

Kazdy etap cykliczny pipeline (sulfonowanie, utlenienie) ma panel decyzji z dwoma przyciskami zawsze widocznymi. Laborant jawnie wybiera: korekta (nowa runda) lub przejscie (z opcjonalnym zleceniem korekty przejsciowej).

## Panele per etap

### Sulfonowanie

Dwa przyciski:
- **"Korekta Na2SO3"** → rozwija input na ilosc → "Zalec" → ebr_korekta + close_sesja(korekta) → nowa runda
- **"Perhydrol → Utlenienie"** → rozwija input z pre-fill obliczona dawka (formula perhydrolu) → laborant moze nadpisac → "Zalec i przejdz" → ebr_korekta + close_sesja(przejscie) → start sesja utlenienie

### Utlenienie

Dwa przyciski:
- **"Korekta perhydrolem"** → rozwija input z pre-fill obliczona dawka → "Zalec" → ebr_korekta + close_sesja(korekta) → nowa runda
- **"Zatwierdz → Standaryzacja"** → close_sesja(przejscie) → start sesja standaryzacja

### Standaryzacja

Istniejacy flow — renderCyclicSections z decision bar (Przepompuj / Powtorz / Korekta). Bez zmian.

### Analiza koncowa

Istniejacy flow — "Przepompuj na zbiornik". Bez zmian (ostatni etap).

## Zmiany w DB

### etap_korekty_katalog — dodac Perhydrol do sulfonowania

```sql
INSERT INTO etap_korekty_katalog (etap_id, substancja, jednostka, wykonawca, kolejnosc, formula_ilosc, formula_zmienne)
VALUES (4, 'Perhydrol 34%', 'kg', 'produkcja', 2,
  '(C_so3 - target_so3) * 0.01214 * Meff + (target_nadtlenki > 0 ? target_nadtlenki * Meff / 350 : 0)',
  '{"C_so3":"pomiar:so3","target_so3":"target:so3","target_nadtlenki":"target:nadtlenki","Meff":"..."}');
```

To jest ta sama formula co dla utlenienia. Cel SO3 i nadtlenki bierzemy z produkt_etap_limity utlenienia (etap 5), nie sulfonowania.

### Nowa kolumna: jest_przejscie

Dodac kolumne `jest_przejscie INTEGER DEFAULT 0` do `etap_korekty_katalog`. Korekty z `jest_przejscie=1` oznaczaja "zlec korekte I przejdz do nastepnego etapu" (zamknij sesje z decyzja='przejscie' zamiast 'korekta').

Migration w init_mbr_tables:
```sql
ALTER TABLE etap_korekty_katalog ADD COLUMN jest_przejscie INTEGER DEFAULT 0;
```

Perhydrol w sulfonowaniu: jest_przejscie=1
Na2SO3 w sulfonowaniu: jest_przejscie=0
Perhydrol w utlenieniu: jest_przejscie=0

## Zmiany w JS (_fast_entry_content.html)

### Usunac

- Bezwarunkowy "Zatwierdz etap" bar w `renderPipelineSections` (linie ~1189-1199)
- Debug console.log (linie ~1117-1118)

### Dodac: renderStageDecisionPanel(container, sekcja, activeEtap)

Nowa funkcja renderujaca panel decyzji pod sekcja. Wywoływana z `renderPipelineSections` zamiast starego approve bar.

Logika:
1. Fetch korekty z `/api/pipeline/lab/ebr/{id}/etap/{etap_id}` (lazy, jednorazowo)
2. Renderuj dwa przyciski per korekta:
   - Korekty z `jest_przejscie=0` → przycisk "Korekta {substancja}"
   - Korekty z `jest_przejscie=1` → przycisk "{substancja} → {nastepny_etap}"
   - Jesli brak korekt z jest_przejscie → dodaj przycisk "Zatwierdz etap →"
3. Klik na przycisk → rozwij input z formula pre-fill (jesli formula istnieje)
4. "Zalec" / "Zalec i przejdz":
   - POST /api/pipeline/lab/ebr/{id}/korekta
   - POST /api/pipeline/lab/ebr/{id}/etap/{etap_id}/close z decyzja='korekta' lub 'przejscie'
   - Jesli korekta: startNewPipelineRound
   - Jesli przejscie: closePipelineStage (start nastepnego)

### Jesli etap nie ma korekt w katalogu

Pokaz tylko przycisk "Zatwierdz etap →" (backward compat z etapami bez korekt).

### Jesli etap jest ostatni w pipeline

Pokaz "Przepompuj na zbiornik" zamiast "Zatwierdz".

## Zmiany w pipeline_dual_write (adapter.py)

Naprawic skip dla dodatki sekcji:
```python
if base_sekcja == "dodatki" or base_sekcja.endswith("_dodatki"):
    return None
```

## Zakres

### Budujemy
- Kolumna jest_przejscie + migration
- Perhydrol w katalogu korekt sulfonowania (z formula, jest_przejscie=1)
- renderStageDecisionPanel z dwoma przyciskami
- Input z pre-fill formula per korekta
- Usuwanie starego approve bar i debug logów

### NIE budujemy
- Zmiana w standaryzacja flow (istniejacy decision bar zostaje)
- Zmiana w analiza koncowa (istniejacy flow zostaje)
- UI edycji jest_przejscie w admin (hardcoded w setup skrypcie)
