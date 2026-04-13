# Rozszerzona Karta Szarżowa V2 — Design Spec

## Overview

Rozbudowa istniejącego `fast_entry` o pełny workflow decyzyjny dla 3 etapów analitycznych (sulfonowanie → utlenianie → standaryzacja) dla 4 produktów (K7, K40GL, K40GLO, K40GLOL). Podejście A+B z elementem C: rozbudowa obecnego kodu + reużywalne partiale + tabela `etap_decyzje` jako config-driven decision layer.

**Produkty:** K7, K40GL, K40GLO, K40GLOL
**Etapy:** sulfonowanie, utlenianie, standaryzacja
**Docelowo:** mechanizm rozszerzy się na wszystkie etapy i produkty pipeline.

---

## 1. Model danych

### 1.1 Nowa tabela: `etap_decyzje`

```sql
CREATE TABLE IF NOT EXISTS etap_decyzje (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    etap_id INTEGER NOT NULL,
    typ TEXT NOT NULL CHECK (typ IN ('pass', 'fail')),
    kod TEXT NOT NULL,
    label TEXT NOT NULL,
    akcja TEXT NOT NULL CHECK (akcja IN ('next_stage', 'new_round', 'release', 'close', 'skip_to_next')),
    wymaga_komentarza INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    FOREIGN KEY (etap_id) REFERENCES produkt_pipeline(id)
);
```

Populacja per etap × produkt:

| Etap | typ | kod | label | akcja | wymaga_komentarza |
|------|-----|-----|-------|-------|-------------------|
| Sulfonowanie | pass | next_stage | Przejdź do utleniania | next_stage | 0 |
| Sulfonowanie | fail | new_round | Nowa runda | new_round | 0 |
| Utlenianie | pass | next_stage | Przejdź do standaryzacji | next_stage | 0 |
| Utlenianie | fail | new_round | Nowa runda | new_round | 0 |
| Utlenianie | fail | skip_to_next | Przenieś korektę do standaryzacji | skip_to_next | 0 |
| Standaryzacja | pass | release | Zatwierdź szarżę | release | 0 |
| Standaryzacja | fail | new_round | Kolejna runda (korekta) | new_round | 0 |
| Standaryzacja | fail | release_comment | Zwolnij z komentarzem | release | 1 |
| Standaryzacja | fail | close_note | Zamknij z notatką | close | 1 |

### 1.2 Zmiany w istniejących tabelach

**`parametry_etapy`** — nowe kolumny:
```sql
ALTER TABLE parametry_etapy ADD COLUMN edytowalny INTEGER DEFAULT 1;
ALTER TABLE parametry_etapy ADD COLUMN dt_modified TIMESTAMP;
ALTER TABLE parametry_etapy ADD COLUMN modified_by INTEGER;
```

**`ebr_pomiar`** — nowa kolumna:
```sql
ALTER TABLE ebr_pomiar ADD COLUMN odziedziczony INTEGER DEFAULT 0;
```

**`ebr_etap_sesja`** — nowa kolumna:
```sql
ALTER TABLE ebr_etap_sesja ADD COLUMN komentarz_decyzji TEXT;
```
Kolumna `decyzja` rozszerzona o nowe kody: `release_comment`, `close_note`, `skip_to_next` (obok istniejących `zamknij_etap`, `reopen_etap`).

### 1.3 Populacja bramek (`etap_warunki`)

Dla 4 produktów × 3 etapów:

| Etap | Parametr | Operator | Wartość |
|------|----------|----------|---------|
| Sulfonowanie | SO₃²⁻ (so3) | <= | 0.1 (edytowalny) |
| Utlenianie | SO₃²⁻ (so3) | <= | 0.1 |
| Utlenianie | H₂O₂ (h2o2) | <= | próg per produkt |
| Standaryzacja | per parametr z `parametry_etapy` | between | min/max per parametr (migracja generuje wiersz `etap_warunki` dla każdego parametru z zdefiniowanymi limitami) |

Progi edytowalne przez laboranta w runtime (Global Edit).

---

## 2. Inteligentne dziedziczenie rund

### Logika (backend: `pipeline/models.py`)

Przy tworzeniu sesji rundy N+1:
1. Pobierz pomiary z rundy N
2. Dla każdego pomiaru:
   - `w_limicie = 1` (OK) → kopiuj do N+1 z `odziedziczony = 1`
   - `w_limicie IS NULL` (brak limitu) → kopiuj z `odziedziczony = 1`
   - `w_limicie = 0` (poza normą) → nie kopiuj, pole puste

### Frontend

- Pola odziedziczone: `readonly`, klasa CSS `.inherited`, szare tło, tooltip "Wynik z rundy N"
- Pola do oznaczenia: edytowalne, żółte obramowanie (klasa `.needs-retest`)
- Klik na pole odziedziczone → odblokowanie (zmiana `odziedziczony = 0`, pole edytowalne)
- Historia rund: istniejący collapsible mechanizm bez zmian

### Edge case

Laborant chce powtórzyć pomiar OK → klik odblokuje pole, auto-save wysyła z `odziedziczony = 0`.

---

## 3. Global Edit — edycja limitów i wzorów

### Mechanizm

Pola limitów (min/max), target i współczynniki wzorów są edytowalnymi inputami w panelu "Specyfikacja" (prawy panel `fast_entry`).

### Flow

1. Laborant zmienia wartość limitu/wzoru
2. Blur → auto-save (istniejący mechanizm)
3. `PATCH /api/parametry-etapy/<id>` → nadpisuje rekord w `parametry_etapy`
4. Zapis: `dt_modified = NOW()`, `modified_by = current_user.id`
5. Globalny (produkt = NULL) → nadpisuje globalny rekord
6. Per produkt → nadpisuje rekord per produkt
7. Bieżąca szarża: `evaluate_gate()` re-ewaluowany z nowym limitem

### Wzory

- Wzory korekcyjne w `parametry_etapy.formula`
- Edycja inline w panelu spec → zapis → re-kalkulacja panelu korekcyjnego
- Globalne (perhydrol, NaCl): `produkt = NULL`
- Per produkt (woda): konkretny `produkt`

### Audit

Kolumny `dt_modified` + `modified_by` w `parametry_etapy`. Bez pełnej historii wersji.

---

## 4. Panele korekcyjne i auto-kalkulacje

### Architektura

Reużywalny partial `_correction_panel.html` parametryzowany kontekstem. Renderowany w sekcji "dodatki" (istniejący companion w adapterze pipeline).

### Etap 1 → 2: Panel perhydrolu

**Trigger:** sulfonowanie PASS
**Inputy:** zakres celowy SO₃²⁻, stężenie H₂O₂, masa szarży (z EBR)
**Wzór (globalny):** `dawka_kg = (target_so3 - wynik_so3) * masa * wspolczynnik`
**Output:** dawka perhydrolu [kg] — readonly, auto-obliczone
**Edycja:** współczynnik edytowalny (Global Edit) → re-kalkulacja
**Zatwierdzenie:** tworzy `ebr_korekta_v2` + `zlecenie_korekty` → przejście do utleniania

### Etap 2 → 3: Panel woda + NaCl

**Trigger:** utlenianie PASS
**Inputy:** wyniki SM (sucha masa), NaCl, aktualna masa
**Wzory:**
- `woda_kg = masa * (1 - target_sm / wynik_sm)` (per produkt)
- `nacl_kg = masa * (target_nacl - wynik_nacl) / 100` (globalny)

**Output:** dawki wody i NaCl [kg] — readonly, auto-obliczone
**Zatwierdzenie:** tworzy zlecenie korekty → przejście do standaryzacji

### Etap 3: Brak panelu korekcyjnego

Standaryzacja nie ma auto-kalkulacji — scenariusze wyjścia obsługiwane przez `etap_decyzje`.

### JS

`recomputeCorrection(panelEl)` — nasłuchuje zmiany inputów, ewaluuje wzór z DB, aktualizuje output. Rozszerza istniejący `recomputeField()`.

---

## 5. Scenariusze wyjścia i bramki decyzyjne

### Unified "Zatwierdź etap" flow

1. Laborant klika "Zatwierdź etap"
2. Backend: `evaluate_gate(db, etap_id, sesja_id)`
3. Gate PASS → `etap_decyzje WHERE typ='pass'` → zwykle "Przejdź dalej"
4. Gate FAIL → `etap_decyzje WHERE typ='fail'` → modal z listą opcji

### Modal fail

Wyświetla:
- Aktualny próg i wynik (np. "SO₃²⁻: wynik 0.15, limit ≤ 0.1")
- **Edytowalny próg** — laborant może zmienić inline → Global Edit → re-ewaluacja bramki
- Lista opcji z `etap_decyzje` (z `label` jako tekst przycisku)
- Textarea jeśli `wymaga_komentarza = 1`

### Edycja progu w modalu

Laborant zmienia próg → auto-save do `parametry_etapy` → re-ewaluacja `evaluate_gate()`:
- Jeśli teraz PASS → modal przełącza się na opcje pass
- Jeśli nadal FAIL → opcje fail bez zmian

### Zapis decyzji

- `ebr_etap_sesja.decyzja` → kod z `etap_decyzje.kod`
- `ebr_etap_sesja.komentarz_decyzji` → tekst z textarea (jeśli wymagany)

### Per etap summary

| Etap | Pass | Fail |
|------|------|------|
| Sulfonowanie | Odblokuj panel perhydrolu → utlenianie | Nowa runda (dziedziczenie) |
| Utlenianie | Odblokuj panel woda/NaCl → standaryzacja | Nowa runda LUB przenieś korektę do standaryzacji |
| Standaryzacja | Zatwierdź → status "Gotowy" | Nowa runda / zwolnienie z komentarzem / zamknięcie z notatką |

---

## 6. Implementacja — pliki do zmiany/utworzenia

### Backend

| Plik | Zmiana |
|------|--------|
| `mbr/pipeline/models.py` | Inteligentne dziedziczenie rund, rozszerzone `close_sesja()` o nowe kody decyzji |
| `mbr/pipeline/lab_routes.py` | Endpoint Global Edit (`PATCH /api/parametry-etapy/<id>`), rozszerzony `/close` o obsługę `etap_decyzje` |
| `mbr/parametry/registry.py` | Zwracanie flag `edytowalny` w kontekście spec panelu |
| `mbr/etapy/models.py` | Populacja `etap_decyzje` w `init_mbr_tables()` |
| `migrate_batch_card_v2.py` | Migracja: nowa tabela, kolumny, populacja bramek i decyzji |

### Frontend

| Plik | Zmiana |
|------|--------|
| `mbr/templates/laborant/_fast_entry_content.html` | Integracja partiali, edytowalne limity w spec panelu, klasy `.inherited`/`.needs-retest` |
| `mbr/templates/laborant/_correction_panel.html` | **NOWY** — generyczny partial panelu korekcyjnego |
| `mbr/templates/laborant/_gate_decision_modal.html` | **NOWY** — modal z opcjami decyzyjnymi z `etap_decyzje` |
| `mbr/pipeline/adapter.py` | Przekazanie flag odziedziczenia i edytowalności do kontekstu fast_entry |

### JS (w `_fast_entry_content.html` lub wydzielony)

- `recomputeCorrection()` — auto-kalkulacja paneli korekcyjnych
- `handleGateResult()` — obsługa odpowiedzi gate w modalu
- `unlockInherited()` — odblokowanie pola odziedziczonego
- `saveSpecEdit()` — Global Edit auto-save

---

## 7. Scope i ograniczenia

### In scope
- 4 produkty × 3 etapy
- Bramki twarde z edytowalnymi progami
- Inteligentne dziedziczenie rund
- Global Edit limitów/wzorów
- Panele korekcyjne: perhydrol, woda+NaCl
- Scenariusze wyjścia z `etap_decyzje`
- Audit: dt_modified + modified_by

### Out of scope
- Pozostałe etapy pipeline (amidowanie, namca, czwartorzędowanie, rozjaśnianie)
- Pozostałe produkty (zbiorniki, płatkowanie)
- Historia wersji limitów (pełny changelog)
- Workflow engine / dynamiczny rendering UI z configa
- Soft alerts (walidacja miękka)

### Co się nie zmienia
- Auto-save na blur
- Sidebar etapów
- Kalkulator titracji
- Pola obliczeniowe (recomputeField)
- Batch creation flow (pipeline init)
- Historia rund (collapsible)

### Migracja
- Ad-hoc script `migrate_batch_card_v2.py`
- Tworzy `etap_decyzje`, dodaje kolumny, populuje bramki i decyzje
- Backup DB przed uruchomieniem
