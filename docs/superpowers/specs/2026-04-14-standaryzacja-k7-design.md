# Standaryzacja K7 — dziennik zdarzeń i rundy

**Data:** 2026-04-14
**Produkt:** Chegina_K7 (pipeline: sulfonowanie → utlenienie → standaryzacja)

## Cel

Włączyć pełną cykliczną logikę standaryzacji dla Chegina K7 — identyczny flow jak sulfonowanie/utlenienie: pomiary → gate → korekta → nowa runda z dziennikiem zdarzeń.

## Zmiany konfiguracyjne (skrypt migracyjny)

### 1. Dodać parametr nD20 do etapu standaryzacja
- Parametr `nd20` — dodać do `parametry_etapy` dla etapu standaryzacja
- Kolejność: po istniejących parametrach (SM, pH 10%, NaCl, SA)

### 2. Ustawić limity produktowe dla Chegina_K7
- `nd20`: min=1.3922, max=1.3925
- `ph_10proc`: min=5.5, max=6.5 (nadpisuje obecne 4.0–6.0)

### 3. Gate conditions — tylko pH i nD20
- Usunąć obecne warunki gate (SM, NaCl, SA, pH) z `etap_warunki` dla standaryzacji
- Dodać dwa warunki: `ph_10proc` (between) i `nd20` (between)
- SM, NaCl, SA pozostają jako parametry do pomiaru, ale nie blokują gate

## Zmiany w UI

### 4. Upewnić się, że standaryzacja renderuje się przez pipeline flow
- Standaryzacja jest już `typ_cyklu=cykliczny` i jest w `produkt_pipeline`
- `renderPipelineSections()` powinno ją obsługiwać — zweryfikować
- Dziennik zdarzeń (`_loadPipelineRoundHistory`) już działa dla etapów pipeline
- Korekty (Woda, NaCl, Kwas cytrynowy) już w `etap_korekty_katalog`

## Czego NIE ruszamy
- Pipeline API routes (lab_routes.py)
- Pipeline models (create_round_with_inheritance, evaluate_gate)
- Dziennik zdarzeń UI (_loadPipelineRoundHistory)
- Kalkulator standaryzacji (_modal_standaryzacja.html)

## Limity Chegina_K7 (standaryzacja)

| Parametr | Min | Max | Gate? |
|----------|-----|-----|-------|
| SM | 40.0 | 48.0 | nie |
| pH 10% | 5.5 | 6.5 | **tak** |
| NaCl | 4.0 | 8.0 | nie |
| SA | 30.0 | 42.0 | nie |
| nD20 | 1.3922 | 1.3925 | **tak** |
