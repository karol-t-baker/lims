# Pipeline flowchart + nawigacja sekcjami — spec

## Problem

Adapter pipeline poprawnie transformuje dane do formatu fast_entry, ale:
1. Flowchart w sidebarze (`renderSidebarEtapy`) jest hardcoded na stare etapy procesowe
2. Wszystkie sekcje parametrow renderuja sie naraz — laborant powinien widziec jeden etap

## Cel

Dynamiczny flowchart w sidebarze renderowany z pipeline `etapy_json` + nawigacja miedzy sekcjami (pokaż aktywny etap, ukryj reszty). Backward compatible — produkty bez pipeline uzywaja starego flowcharta.

## Zmiany

### 1. renderSidebarEtapy() — szarze_list.html

Nowa galaz logiki: jesli `etapy_json` zawiera pole `pipeline_etap_id` → renderuj pipeline flowchart.

#### Detekcja pipeline
```javascript
var isPipeline = etapy.some(function(e) { return e.pipeline_etap_id; });
if (isPipeline) {
    renderPipelineFlowchart();
    return;
}
// ... stary kod flowcharta ...
```

#### renderPipelineFlowchart()

Filtruje etapy — pomija te z `sekcja_lab` zawierajacym `_dodatki` lub rownym `dodatki` (sa czescia cyklicznego etapu, nie osobnym krokiem w flowcharcie).

Dla kazdego etapu okresl status:
- `done` — sekcja ma wyniki (sprawdz `wyniki[sekcja_lab]` lub `wyniki[sekcja_lab + '__1']`)
- `active` — pierwszy etap ktory nie jest done
- `pending` — po active

Renderuj istniejacymi klasami CSS:
```html
<div class="se-step is-{status}" onclick="...">
    <div class="se-num {status}">{nr}</div>
    <div class="se-info">
        <div class="se-name">{nazwa}</div>
        <div class="se-status">{statusText}</div>
    </div>
</div>
```

Statusy CSS (istniejace klasy z szarze_list.html):
- `done` → zielony (`.se-num.done`)
- `active` → teal pulsujacy (`.se-num.active`)
- `pending` → szary (`.se-num.pending`)
- `stand` → pomaranczowy (`.se-num.stand`) — dla aktywnej standaryzacji (cykliczny)
- `koncowa` → fioletowy (`.se-num.koncowa`) — dla aktywnej analizy koncowej

Cykliczne etapy: badge z runda (R1, R2...) obok nazwy, na podstawie `roundState.last_analiza`.

#### Interakcja

- Klik `done` → wywolaj `showPipelineStage(sekcja_lab)` — podglad read-only
- Klik `active` → wywolaj `showPipelineStage(sekcja_lab)` — edycja
- Klik `pending` → nic (zablokowany, `cursor: not-allowed`)
- Podswietl wybrany etap klasa `.se-selected`

### 2. showPipelineStage() — _fast_entry_content.html

Nowa globalna funkcja dodana na koncu skryptu w `_fast_entry_content.html`.

```javascript
window.showPipelineStage = function(sekcjaLab) {
    // Ukryj wszystkie sekcje
    document.querySelectorAll('.lab-section').forEach(function(s) {
        s.style.display = 'none';
    });
    // Pokaz wybrana sekcje (po data-sekcja lub id)
    // Dla cyklicznych: pokaz zarowno "analiza" jak i "dodatki"
    // (round cycling w srodku przelacza je wewnetrznie)
    ...
    // Aktualizuj sidebar — podswietl wybrany etap
    window._activePipelineStage = sekcjaLab;
    if (typeof renderSidebarEtapy === 'function') renderSidebarEtapy();
};
```

#### Identyfikacja sekcji w DOM

Sekcje sa renderowane z `data-sekcja` atrybutem lub identyfikowalne przez klase/id. Trzeba sprawdzic jak `_fast_entry_content.html` renderuje sekcje — prawdopodobnie kazda sekcja ma wrapper div z identyfikatorem sekcji.

Jesli sekcje nie maja wrapera — dodac go: kazda sekcja parametrow w `_fast_entry_content.html` opakowana w `<div class="lab-section" data-sekcja="{sekcja_key}">`.

#### Inicjalizacja

Po zaladowaniu partial i wyrenderowaniu sekcji:
1. Sprawdz czy pipeline (etapy maja `pipeline_etap_id`)
2. Jesli tak: ukryj wszystkie sekcje, pokaz aktywna
3. Jesli nie: bez zmian (stare zachowanie)

### 3. Read-only dla zakonczonych etapow

Gdy laborant klika etap ze statusem `done`:
- Sekcja sie pokazuje
- Inputy ustawione na `disabled` (lub dodatkowa klasa `.readonly-stage`)
- Laborant widzi wartosci ale nie moze edytowac

Implementacja: `showPipelineStage(sekcjaLab, readonly)` — jesli readonly, ustaw `disabled` na wszystkich inputach w sekcji.

### 4. Backward compatibility

Produkty bez pipeline:
- `etapy_json` nie zawiera `pipeline_etap_id`
- `renderSidebarEtapy()` idzie stara sciezka
- `_fast_entry_content.html` renderuje wszystkie sekcje naraz (jak dotad)
- Zero zmian w zachowaniu

### 5. Zakres

Budujemy:
- Pipeline flowchart w `renderSidebarEtapy()` (szarze_list.html)
- `showPipelineStage()` w `_fast_entry_content.html`
- Wrapper div `.lab-section[data-sekcja]` jesli nie istnieje
- Read-only dla done etapow

NIE budujemy:
- Bramki/decyzje w UI (osobny spec)
- Zmiana statusu etapu przez klikniecie (to bedzie z bramkami)
- Zmiany w backendzie
