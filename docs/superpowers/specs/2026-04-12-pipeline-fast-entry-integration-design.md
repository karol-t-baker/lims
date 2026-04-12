# Pipeline → Fast Entry Integration — spec v2

## Problem

Pipeline builder (tabele, modele, admin UI) dziala poprawnie. Ale widok laboranta (fast_entry_v2) zostal zbudowany od zera zamiast rozszerzyc istniejacy fast_entry. Brakuje: kalkulatora miareczkowego, polskiego formatowania, computed fields, sidebar szarz, completion flow, audit trail, uwag. Caly widok laboranta jest zepsuty przez hard redirect.

## Cel

Zintegrowac pipeline z istniejacym fast_entry przez adapter serwerowy. Istniejacy widok (192KB JS, kalkulator, auto-save, round cycling, completion flow) zostaje niezmieniony. Pipeline dostarcza dane w formacie ktory widok juz rozumie.

## Co usunac

- `mbr/templates/pipeline/fast_entry_v2.html`
- `mbr/templates/pipeline/_fast_entry_v2_content.html`
- Page routes w `mbr/pipeline/lab_routes.py` (fast_entry_v2, fast_entry_v2_partial)
- Hard redirect w `mbr/laborant/routes.py` (przywrocic oryginalny fast_entry)
- `loadBatch` override w `mbr/templates/laborant/szarze_list.html` (przywrocic AJAX partial)

## Co zachowac bez zmian

- Admin UI pipeline (katalog, edytor, pipeline produktu) — dzialaja
- Pipeline API routes w `lab_routes.py` (sesje, pomiary, bramki, korekty) — API zostaje
- Wszystkie 9 nowych tabel — zostaja
- `mbr/pipeline/models.py` — zostaje caly
- `mbr/pipeline/routes.py` — zostaje caly
- Skrypty migracyjne — zostaja
- Istniejacy `_fast_entry_content.html` — bez zmian w renderowaniu

## Adapter serwerowy

### Nowa funkcja: `build_pipeline_context(db, produkt)`

Lokalizacja: `mbr/pipeline/models.py` (lub nowy `mbr/pipeline/adapter.py`)

Transformuje dane pipeline do formatu `etapy_json` + `parametry_lab` ktory istniejacy szablon rozumie.

#### Wejscie

- `produkt` — nazwa produktu
- `db` — polaczenie do bazy

#### Wyjscie

```python
{
    "etapy_json": [...],      # lista etapow w formacie fast_entry
    "parametry_lab": {...},   # sekcje z polami w formacie fast_entry
}
```

#### Transformacja etapy_json

Dla kazdego etapu w `get_produkt_pipeline(db, produkt)`:

```python
{
    "nr": stage.kolejnosc,
    "nazwa": stage.nazwa,       # z etapy_analityczne
    "read_only": False,
    "sekcja_lab": stage.kod,    # kod etapu = klucz sekcji
    "pipeline_etap_id": stage.etap_id,  # do identyfikacji w pipeline API
    "typ_cyklu": stage.typ_cyklu,       # cykliczny/jednorazowy
}
```

Etapy cykliczne (np. standaryzacja) generuja dodatkowy etap "dodatki":
```python
{
    "nr": stage.kolejnosc + 0.5,  # miedzy etapami
    "nazwa": f"{stage.nazwa} — dodatki",
    "read_only": False,
    "sekcja_lab": f"{stage.kod}__dodatki",
}
```

#### Transformacja parametry_lab

Dla kazdego etapu: `resolve_limity(db, produkt, etap_id)` → sekcja w parametry_lab.

Kazdy parametr transformowany z `etap_parametry` + `parametry_analityczne`:

```python
{
    "kod": pa.kod,
    "label": pa.skrot or pa.label,   # skrot ma priorytet (krotszy)
    "skrot": pa.skrot,
    "tag": pa.kod,
    "typ": "float",                  # zawsze float dla inputa
    "measurement_type": _map_typ(pa.typ),  # bezposredni/titracja/obliczeniowy/binarny
    "min": resolved.min_limit,
    "max": resolved.max_limit,
    "min_limit": resolved.min_limit,
    "max_limit": resolved.max_limit,
    "precision": resolved.precision or pa.precision or 2,
    "target": resolved.target,
    "nawazka_g": resolved.nawazka_g,
    "grupa": ep.grupa or "lab",
    "metoda_id": pa.metoda_id,
    # Jesli typ=titracja i metoda_id:
    "calc_method": {
        "name": metoda.nazwa,
        "formula": metoda.formula,
        "factor": pa.metoda_factor,
        "suggested_mass": resolved.nawazka_g,
        "method_id": pa.metoda_id,
    },
    # Jesli typ=obliczeniowy:
    "formula": ep.formula or pa.formula,
}
```

Mapowanie typow:
- `bezposredni` → `"bezp"` (measurement_type w fast_entry)
- `titracja` → `"titracja"`
- `obliczeniowy` → `"obliczeniowy"`
- `binarny` → `"binarny"`
- `jakosciowy` → `"bezp"`

Dla etapow cyklicznych: dodatkowa sekcja `{kod}__dodatki` z polami z `etap_korekty_katalog`:
```python
{
    "kod": f"korekta_{korekta.substancja.lower().replace(' ','_')}",
    "label": f"{korekta.substancja} [{korekta.jednostka}]",
    "tag": ...,
    "typ": "float",
    "measurement_type": "bezp",
    "min": 0,
    "max": None,
    "precision": 1,
}
```

### Integracja w fast_entry_partial

W `mbr/laborant/routes.py`, funkcja `fast_entry_partial`:

```python
# Na poczatku, po pobraniu ebr:
from mbr.pipeline.models import get_produkt_pipeline
from mbr.pipeline.adapter import build_pipeline_context

pipeline = get_produkt_pipeline(db, ebr["produkt"])
if pipeline:
    ctx = build_pipeline_context(db, ebr["produkt"])
    # Nadpisz etapy_json i parametry_lab z pipeline
    ebr = dict(ebr)
    ebr["etapy_json"] = json.dumps(ctx["etapy_json"])
    ebr["parametry_lab"] = json.dumps(ctx["parametry_lab"])
```

Reszta route'a i szablonu dziala bez zmian — dostaje dane w znanym formacie.

### Metody miareczkowe

Adapter musi pobrac metody z `metody_miareczkowe` zeby wypelnic `calc_method` w polach titracyjnych. Istniejaca funkcja `get_calc_methods()` z `mbr/parametry/registry.py` zwraca metody po `metoda_id`. Adapter uzywa tego samego zrodla.

### Edycja parametrow przez laboranta

Istniejacy fast_entry ma inline parameter editor (modal `.pe-modal`). Laborant moze edytowac limity, dodawac/usuwac parametry. Te zmiany idą do `parametry_etapy` (stara tabela).

Dla produktow z pipeline, edycja musi isc do `produkt_etap_limity` (nowa tabela). Potrzebna zmiana:
- W `mbr/parametry/routes.py`, endpointy PUT/POST/DELETE dla bindingow — sprawdzic czy produkt ma pipeline, jesli tak, zapisac do `produkt_etap_limity` zamiast `parametry_etapy`
- Alternatywnie: nowy endpoint w `pipeline/routes.py` dla edycji limitow z poziomu fast_entry
- Rebuild parametry_lab po edycji: ponowne wywolanie `build_pipeline_context` → aktualizacja `ebr.parametry_lab` jesli MBR nadal generuje snapshoty

### Zapis wynikow — dual write

Istniejacy `save_wyniki()` zapisuje do `ebr_wyniki`. Dla produktow z pipeline, po zapisie do `ebr_wyniki` rowniez:
1. Znajdz aktywna sesje pipeline (`ebr_etap_sesja` ze statusem `w_trakcie`)
2. Mapuj sekcja → etap_id (po kodzie)
3. Zapisz do `ebr_pomiar` przez `save_pomiar()`
4. Ewaluuj bramke przez `evaluate_gate()`

To dual-write pozwala:
- Staremu widokowi dzialac normalnie (czyta z ebr_wyniki)
- Nowym tabelom pipeline zbierac dane pod ML
- Bramkom dzialac

### Bramki i decyzje

Po save_wyniki, jesli etap ma bramke:
1. `evaluate_gate()` sprawdza warunki
2. Wynik zwracany w response JSON (nowe pole `gate`)
3. JS w `_fast_entry_content.html` — minimalne rozszerzenie:
   - Po response z `gate.passed === true`: pokaz przycisk "Etap OK — przejdz dalej"
   - Po `gate.passed === false`: pokaz komunikat "Warunek niespelniony" + lista failures
   - Klikniecie "przejdz dalej" → zamknij sesje, rozpocznij nastepny etap

### Trzecia opcja: korekta_i_przejscie

Dla standaryzacji cyklicznej, po analizie:
- **OK** → `przejscie` — koniec etapu
- **Daleko** → `korekta` — nowa runda (analiza → dodatki → analiza)
- **Blisko** → `korekta_i_przejscie` — mala korekta + koniec (komentarz w uwagach)

To mapuje sie na istniejacy round_state:
- `przejscie` = is_decision=True, user klika "Zatwierdz"
- `korekta` = is_decision=True, user klika "Kontynuuj standaryzacje" → nowa runda
- `korekta_i_przejscie` = is_decision=True, user klika "Mala korekta + zatwierdz" → dialog z polem na uwagi

### Zmiany w _fast_entry_content.html

Minimalne:
1. **Gate status bar** — po response save, jesli `gate` w response, pokaz banner pod sekcja (zielony/czerwony)
2. **Decision buttons** — w trybie is_decision, dodatkowe przyciski dla pipeline:
   - "Zatwierdz etap" (przejscie)
   - "Kontynuuj standaryzacje" (korekta → nowa runda)
   - "Mala korekta + zatwierdz" (korekta_i_przejscie → dialog z uwagami)
3. **Sidebar badge** — przy etapach pipeline, pokaz numer rundy (R1, R2...)

Te zmiany to ~50 linii JS, nie przepisywanie szablonu.

### Zmiany w save_entry route

W `mbr/laborant/routes.py`, `save_entry()`:

```python
# Po zapisie wynikow i audicie, jesli pipeline aktywny:
gate_result = None
if pipeline_active:
    sesja = get_active_pipeline_sesja(db, ebr_id, sekcja)
    if sesja:
        # Dual-write do ebr_pomiar
        for kod, val in values.items():
            save_pomiar(db, sesja["id"], parametr_id_map[kod], ...)
        # Ewaluacja bramki
        gate_result = evaluate_gate(db, sesja["etap_id"], sesja["id"])

# W response JSON:
return jsonify({"ok": True, ..., "gate": gate_result})
```

## Zakres

### Faza 1 (teraz):
1. Usunac fast_entry_v2, przywrocic stary widok
2. Adapter `build_pipeline_context` — pipeline → parametry_lab + etapy_json
3. Integracja w `fast_entry_partial` — podmiana danych dla produktow z pipeline
4. Dual-write w `save_entry` — zapis do ebr_pomiar + ewaluacja bramki
5. Minimalny gate banner w JS (po save response)

### Faza 2 (pozniej):
- Pelna obsluga decyzji (korekta/przejscie/korekta_i_przejscie)
- Edycja parametrow pipeline z poziomu fast_entry
- Round cycling z pipeline sessions zamiast round_state
- Usuwanie dual-write (tylko ebr_pomiar)

## Wazne

- `_fast_entry_content.html` (192KB) — modyfikujemy MINIMALNIE
- Kalkulator miareczkowy, computed fields, binary fields — dzialaja automatycznie jesli adapter poprawnie wypelni `calc_method`, `formula`, `measurement_type`
- Auto-save flow — bez zmian, save_entry dodaje dual-write transparentnie
- Audit trail — bez zmian, istniejacy audit w save_entry zostaje
- Polish decimal formatting — bez zmian
