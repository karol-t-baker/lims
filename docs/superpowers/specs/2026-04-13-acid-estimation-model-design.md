# Acid Estimation Model for K7 Chegina

## Problem

Laborant potrzebuje podpowiedzi ile kwasu cytrynowego (sypkiego) dodać do szarży K7, aby zejść do docelowego pH 6.25. Obecnie dawka jest dobierana na podstawie doświadczenia. Model ma zaproponować dawkę, którą laborant może zaakceptować lub skorygować.

## Dane

Źródło: `data/kwas.csv` — 45 obserwacji z historycznych szarż K7.

| Kolumna | Opis |
|---------|------|
| masa [kg] | Masa szarży (3 klasy: 7400, 8600, 12600) |
| kw. Cytrynowy [kg] | Dawka kwasu cytrynowego |
| woda [kg] | Woda totalna = woda z refrakcji + kwas |
| pH start | pH przed dodaniem kwasu i wody |
| pH koniec | pH po dodaniu (cel ~6.25) |

Zależność: `woda_total = woda_refrakcja + kwas_kg`, więc `woda_refrakcja = woda - kwas`.

## Model

### Podejście: Regresja liniowa na znormalizowanych zmiennych (kwas/tonę)

Normalizacja na tonę eliminuje zależność od rozmiaru szarży i pozwala uogólniać na dowolną masę.

### Feature engineering

Z surowych danych CSV:
- `kwas_per_ton = kwas_kg / (masa_kg / 1000)`
- `woda_refrakcja = woda_total - kwas_kg`
- `woda_refrakcja_per_ton = woda_refrakcja / (masa_kg / 1000)`

### Dwa warianty do porównania

**Model A (baseline):**
```
kwas_per_ton = α + β₁ · pH_start
```
Predyktory: tylko pH_start. Minimalny, interpretowalny.

**Model B (rozszerzony):**
```
kwas_per_ton = α + β₁ · pH_start + β₂ · woda_refrakcja_per_ton
```
Predyktory: pH_start + woda z refrakcji na tonę. Woda z refrakcji jest znana przed dodaniem kwasu i niesie informację o stężeniu szarży.

### Predykcja końcowa

```
kwas_kg = kwas_per_ton_predicted · masa_kg / 1000
```

### Cel pH

Stały: 6.25. Nie wchodzi do modelu jako zmienna — dane treningowe zbierano przy zbliżonym celu.

## Walidacja

- **Leave-One-Out Cross-Validation (LOOCV)** — standardowa przy n=45
- **Metryki:** MAE (kg), MAPE (%), R²
- **Analiza residuów:**
  - Residua vs masa — test czy normalizacja na tonę działa (nie powinno być systematycznego trendu)
  - Residua vs pH_start — test liniowości
  - QQ-plot normalności residuów
- **Wykres:** predykcja vs rzeczywistość (scatter + linia idealna)

## Porównanie modeli

Model B wygrywa jeśli:
1. Woda z refrakcji jest statystycznie istotna (p < 0.05)
2. MAE spada o >5% vs Model A
3. R² rośnie bez oznak overfittingu (porównanie train vs LOOCV)

Jeśli Model B nie spełnia tych kryteriów — zostaje prostszy Model A.

## Output

Standalone Python skrypt (`acid_estimation_analysis.py`) generujący:
1. Wydruk współczynników regresji i ich istotności
2. Metryki walidacyjne (MAE, MAPE, R²) dla obu modeli
3. Wykresy matplotlib:
   - Scatter: kwas_per_ton vs pH_start (z linią regresji)
   - Predykcja vs rzeczywistość
   - Residua vs masa (test normalizacji)
   - Residua vs fitted values
4. Rekomendacja który model wybrać

## Zakres

- Tylko standalone skrypt do walidacji modelu
- Bez integracji z UI LIMS (na później)
- Bez deep learning (za mało danych)
- Tylko K7 chegina

## Technologie

- Python 3.12, numpy, pandas, scikit-learn, matplotlib, statsmodels (OLS z p-values)
- Brak nowych zależności poza standardowymi ML/data science
