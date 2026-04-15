# Pipeline UI Refresh — K7 Panele + Dziennik Zdarzeń

**Data:** 2026-04-15

## Cel

Podrasować wygląd paneli korekty i dziennika zdarzeń w pipeline K7, zachowując całą istniejącą logikę. Dodać dziennik zdarzeń jako osobny widok.

## Zakres

1. **Restylowanie paneli korekty** (styl "inset panel")
2. **Dziennik zdarzeń jako osobny widok** (styl "inset table")
3. **Przycisk pod flowchartem** do dziennika

## Czego NIE ruszamy

- Logika gate evaluation, round inheritance, corrections
- Funkcje JS: `advanceWithStandV2`, `advanceStandNewRound`, `advanceWithPerhydrol`, `showPerhydrolWithStand`, `recomputeStandV2`, `_acidModelPredict`
- API routes (pipeline/lab_routes.py)
- Pipeline models (models.py, adapter.py)

---

## 1. Panele korekty — styl "Inset Panel"

Zastąpić obecne klasy `gate-section gate-h2o2` / `gate-fail` nowym stylem:

**Właściwości:**
- `background: #f5f2ec` (ciepła powierzchnia, `var(--surface-alt)`)
- `border: 1px solid var(--border)`
- `box-shadow: inset 0 1px 3px rgba(0,0,0,0.04)` (wgłębienie)
- `border-radius: 10px`

**Nagłówek (gate-head):**
- `background: #fff` (biały)
- Margin: negatywny (pełna szerokość)
- `border-bottom: 1px solid var(--border-subtle)`
- `border-radius: 10px 10px 0 0`

**Inputy:**
- `background: #fff`
- `border-color: #d4d0c8`

**Wynik/result:**
- `background: #fff`
- `border: 1px solid var(--border)`

**Warianty kolorystyczne:**
- PASS: `border-color: var(--border)` (neutralny)
- FAIL/KOREKTA: `border-color: var(--amber)` + `box-shadow: inset 0 1px 3px rgba(0,0,0,0.04), 0 0 0 2px var(--amber-bg)`

**Dotyczy paneli:**
- Perhydrol (`_renderPerhydrolPanel`)
- Standaryzacja V2 (`_renderStandaryzacjaV2Panel`)
- Generyczny FAIL (`loadCorrectionPanel`)

---

## 2. Dziennik zdarzeń — widok "Inset Table"

### 2.1 Przycisk pod flowchartem

Dodać przycisk po pipeline flowchart (pasek etapów) w `renderPipelineSections()`:

```
[Dziennik zdarzeń]
```

- Klasa: `gate-btn gate-btn-sec` (identyczny styl jak inne przyciski)
- Onclick: przełącza widok na dziennik (zamiast aktywnego etapu)
- Ikona: ✎ lub brak

### 2.2 Widok dziennika

Tabela z danymi z API `/api/pipeline/lab/ebr/<ebr_id>/etap/<etap_id>` dla każdego etapu.

**Kontener:**
- `background: #f5f2ec` (inset)
- `border: 1px solid var(--border)`
- `box-shadow: inset 0 1px 3px rgba(0,0,0,0.04)`

**Nagłówek tabeli (th):**
- `background: #fff`
- `font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px`
- Kolumny: Runda | Parametry | Status | Korekta | Kto

**Wiersze etapów (stage-row):**
- `background: #fff`
- `font-weight: 700; color: var(--teal)`
- `border-bottom: 1px solid #d0e8e8`
- Pełna szerokość (colspan=5)

**Wiersze danych (data-row):**
- `background: #fafaf7`
- Runda jako badge: `background: var(--teal-bg); color: var(--teal); border-radius: 3px; padding: 1px 6px`
- Parametry: `font-family: var(--mono); font-size: 11px`
- Status: badge OK (green) / FAIL (red)
- Kto: `font-size: 9px; color: var(--text-dim)` z godziną

**Wiersze korekt (kor-row):**
- `color: var(--amber)`
- `background: #fef8ee`
- Strzałka `→` przed substancją

### 2.3 Logika ładowania

- Dla każdego etapu w pipeline: fetch z API
- Zbiera sesje, pomiary, korekty (identyczna logika jak `_loadPipelineRoundHistory`)
- Renderuje jedną tabelę ze wszystkimi etapami
- Przycisk "Powrót" wraca do widoku etapu

### 2.4 Nawigacja

- Przycisk "Dziennik zdarzeń" pod flowchartem → pokazuje tabelę, ukrywa etap
- Przycisk "Powrót do etapu" w dzienniku → wraca do etapu
- Kliknięcie w etap na flowcharcie → wraca do widoku etapu

---

## 3. Zmiany w CSS (style.css)

Nowe klasy (dodać, nie zastępować istniejące):

```css
/* Inset panel style */
.gate-section.gate-inset { ... }
.gate-section.gate-inset .gate-head { ... }
.gate-section.gate-inset.gate-fail { ... }

/* Dziennik table */
.dz-table { ... }
.dz-table .stage-row { ... }
.dz-table .data-row { ... }
.dz-table .kor-row { ... }
.dz-table .runda-nr { ... }
```

---

## 4. Pliki do zmiany

| Plik | Zmiana |
|------|--------|
| `mbr/static/style.css` | Nowe klasy inset panel + dziennik table |
| `mbr/templates/laborant/_correction_panel.html` | Zmienić klasy kontenerów na inset |
| `mbr/templates/laborant/_fast_entry_content.html` | Przycisk dziennika + widok tabeli + nawigacja |
