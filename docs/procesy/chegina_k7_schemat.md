# Chegina K7 — Schemat procesu produkcyjnego

Produkt: Chegina K7 (betaina olejowa)
Template: T121 | Spec: P819 | CAS: 1334422-09-1

---

## Przebieg procesu

```
AMIDOWANIE → SMCA → CZWARTORZĘDOWANIE → SULFONOWANIE → UTLENIENIE → STANDARYZACJA → ANALIZA KOŃCOWA → PRZEPOMPOWANIE
```

---

## Etap 1: AMIDOWANIE

**Cel:** Synteza amidu z kwasów tłuszczowych i DMAPA

### Operacje:
1. Załadunek surowców (kwasy C12-18, CNO/PKO, woda)
2. Włączenie reaktora (temp. docelowa: 160-170°C)
3. Załadunek DMAPA (czysta + zwrotna)
4. Reakcja amidowania (6-20h w 160-170°C)
5. Destylacja DMAPA (odzysk zwrotów)

### Etap analityczny:
| Parametr | Skrót | Typ | Kiedy | Kryterium |
|----------|-------|-----|-------|-----------|
| Liczba estrowa (LE) | le | titracja | w trakcie reakcji | monitorowanie postępu |
| Liczba kwasowa (LA) | la | titracja | po destylacji | < 5.0 mg KOH/g |
| Liczba kwasowa końcowa (LK) | lk | titracja | po destylacji | < 1.0 mg KOH/g |
| Współczynnik załamania (nD20) | nd20 | bezpośredni | po destylacji | orientacyjnie 1.46-1.47 |
| Barwa | barwa | organoleptycznie | po destylacji | notatka opisowa |
| Ilość amidu | ilosc_amidu_kg | odczyt | po destylacji | bilans masowy |

### Warunek przejścia dalej:
- LK < 1.0 mg KOH/g
- Destylacja zakończona (odzysk DMAPA)

### Możliwe korekty:
- Przedłużenie czasu reakcji (jeśli LE za wysoka)
- Dodatkowa porcja DMAPA (jeśli LK za wysoka)

---

## Etap 2: WYTWORZENIE SMCA

**Cel:** Przygotowanie roztworu monochlorooctanu sodu (SMCA) z MCA + NaOH

### Operacje:
1. Rozpuszczenie MCA 80% w wodzie
2. Neutralizacja NaOH 50% (dozowanie powolne, egzotermiczne)

### Etap analityczny:
| Parametr | Skrót | Typ | Kiedy | Kryterium |
|----------|-------|-----|-------|-----------|
| pH roztworu SMCA | ph | bezpośredni | po neutralizacji | 3.0 - 4.0 |

### Warunek przejścia dalej:
- pH w zakresie 3.0-4.0

### Możliwe korekty:
- Dodanie NaOH (jeśli pH < 3.0)
- Dodanie MCA (jeśli pH > 4.0)

---

## Etap 3: CZWARTORZĘDOWANIE

**Cel:** Reakcja amidu z SMCA w obecności NaOH → betaina

### Operacje:
1. Przeciągnięcie amidu do roztworu SMCA
2. Dozowanie NaOH porcjami (2-4 porcje, 50-250 kg każda)
3. Po każdej porcji → analiza

### Etap analityczny (powtarzany po każdej porcji NaOH):
| Parametr | Skrót | Typ | Kiedy | Kryterium |
|----------|-------|-----|-------|-----------|
| pH 10% | ph_10proc | bezpośredni | po porcji NaOH | 11.0 - 12.0 (optymalnie 11.5-11.9) |
| Współczynnik załamania (nD20) | nd20 | bezpośredni | po porcji NaOH | monitorowanie |
| Aminokwasowość (%AA) | aa | titracja (alkacymetria) | po porcji NaOH | < 0.50% |
| Barwa | barwa | organoleptycznie | po porcji NaOH | notatka |

### Warunek przejścia dalej:
- pH_10proc w zakresie 11.0-12.0
- %AA < 0.50%

### Możliwe korekty:
- Dodatkowa porcja NaOH (jeśli pH < 11.0)
- Dodanie MCA (jeśli pH > 12.0 — rzadko)
- Wydłużenie czasu reakcji (jeśli %AA za wysoka)

---

## Etap 4: SULFONOWANIE

**Cel:** Redukcja siarczanów dodaniem Na₂SO₃

### Operacje:
1. Dozowanie Na₂SO₃ (30-300 kg)
2. Analiza po dodaniu

### Etap analityczny:
| Parametr | Skrót | Typ | Kiedy | Kryterium |
|----------|-------|-----|-------|-----------|
| pH 10% | ph_10proc | bezpośredni | po Na₂SO₃ | monitorowanie |
| %SO₃²⁻ | so3 | titracja (jodometryczna) | po Na₂SO₃ | < 0.30% |
| Współczynnik załamania (nD20) | nd20 | bezpośredni | po Na₂SO₃ | monitorowanie |
| Barwa | barwa | organoleptycznie | po Na₂SO₃ | monitorowanie |

### Warunek przejścia dalej:
- %SO₃²⁻ < 0.30%

### Możliwe korekty:
- Dodatkowa porcja Na₂SO₃ (jeśli %SO₃ za wysoki)

---

## Etap 5: UTLENIENIE

**Cel:** Utlenienie resztkowych siarczynów perhydrolem (H₂O₂)

### Operacje (K7 — bez kwasu cytrynowego):
1. Dozowanie Perhydrolu (5-50 kg)
2. Analiza po dodaniu

### Etap analityczny:
| Parametr | Skrót | Typ | Kiedy | Kryterium |
|----------|-------|-----|-------|-----------|
| pH 10% | ph_10proc | bezpośredni | po perhydrolu | monitorowanie |
| %SO₃²⁻ | so3 | titracja (jodometryczna) | po perhydrolu | = 0.000% (cel: zero) |
| %H₂O₂ | h2o2 | titracja (manganometryczna) | po perhydrolu | < 0.010% |
| Współczynnik załamania (nD20) | nd20 | bezpośredni | po perhydrolu | monitorowanie |
| Barwa | barwa | organoleptycznie | po perhydrolu | monitorowanie |

### Warunek przejścia dalej:
- %SO₃²⁻ = 0.000%
- %H₂O₂ < 0.010%

### Możliwe korekty:
- Dodatkowa porcja perhydrolu (jeśli %SO₃ > 0)

---

## Etap 6: STANDARYZACJA (cykliczny)

**Cel:** Doprowadzenie produktu do specyfikacji przez dodawanie korektorów

### Cykl: ANALIZA → (korekta?) → ANALIZA → (korekta?) → ... → OK

### Dozwolone dodatki standaryzacyjne:
| Dodatek | Cel | Efekt |
|---------|-----|-------|
| Woda (H₂O) | Rozcieńczenie | SM↓, SA↓ |
| Kwas cytrynowy | Korekta pH | pH↓ |
| Perhydrol | Odbarwienie / utlenienie | barwa↓, SO₃↓ |
| MGDA-Na3 | Stabilizacja | kompleksowanie |
| NaCl | Korekta zasolenia | NaCl↑ |

### Etap analityczny (powtarzany po każdej korekcie):
| Parametr | Skrót | Typ | Zakres K7 | Metoda |
|----------|-------|-----|-----------|--------|
| Sucha masa [%] | sm | bezpośredni | 40.0 - 48.0 | L903 |
| NaCl [%] | nacl | titracja (Mohr) | 4.0 - 8.0 | L941 |
| pH 10% | ph_10proc | bezpośredni | 4.0 - 6.0 | L905 |
| Współczynnik załamania (nD20) | nd20 | bezpośredni | 1.3900 - 1.4200 | PN-EN ISO 6320 |
| Substancja aktywna [%] | sa | obliczeniowy | 30.0 - 42.0 | SM - NaCl - 0.6 |
| Barwa FAU | barwa_fau | bezpośredni | 0 - 200 | L928 |
| Barwa Hz | barwa_hz | bezpośredni | 0 - 100 | L928 |

### Warunek przejścia do analizy końcowej:
- WSZYSTKIE parametry w zakresie specyfikacji
- Jeśli którykolwiek poza normą → korekta → re-analiza

### Logika korekty:
| Problem | Działanie |
|---------|-----------|
| SM za wysoka | Dodaj wodę |
| SM za niska | Odparowanie (rzadko) |
| pH za wysoki | Dodaj kwas cytrynowy |
| pH za niski | Dodaj NaOH |
| NaCl za niski | Dodaj NaCl |
| Barwa za ciemna | Dodaj perhydrol |
| SA za niska | Dodaj NaCl (lub odprowadź wodę) |

---

## Etap 7: ANALIZA KOŃCOWA

**Cel:** Potwierdzenie zgodności ze specyfikacją P819

### Parametry końcowe:
| Parametr | Skrót | Zakres K7 | Metoda | Format na świadectwie |
|----------|-------|-----------|--------|-----------------------|
| Sucha masa [%] | sm | min 35.5 | L903 | 1 miejsce po przecinku |
| NaCl [%] | nacl | max 5.5 | L941 | 1 miejsce |
| Wsp. załamania (nD20) | nd20 | 1.3800 - 1.3950 | PN-EN ISO 6320 | 4 miejsca |
| Barwa w skali jodowej | barwa_fau | max 3 | L928 | integer |
| pH (10%, aq) | ph_10proc | 4.50 - 7.50 | L905 | 2 miejsca |
| Substancja aktywna [%] | sa | 30.0 - 32.0 | L932 | 1 miejsce |

### Ocena jakości:
- **zgodna** → produkt trafia do zbiornika magazynowego
- **niezgodna** → rework (powrót do standaryzacji) lub downgrade (np. do K7B)

---

## Etap 8: PRZEPOMPOWANIE

**Cel:** Transfer produktu do zbiornika magazynowego

### Dane rejestrowane:
- Czas rozpoczęcia/zakończenia
- Temperatura max (typowo 40-50°C)
- Nr zbiornika docelowego (M1-M30)
- Wskazania przepływomierza (od/do)
- Podpis operatora
