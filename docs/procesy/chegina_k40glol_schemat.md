# Chegina K40GLOL — Schemat procesu produkcyjnego

Produkt: Chegina K40GLOL (betaina olejowa, wariant laurylowy)
Template: T118 | Spec: P833 | CAS: 147170-44-3

---

## Przebieg procesu

```
AMIDOWANIE → SMCA → CZWARTORZĘDOWANIE → SULFONOWANIE → UTLENIENIE (kw.cytrynowy + perhydrol) → ROZJAŚNIANIE → STANDARYZACJA → ANALIZA KOŃCOWA → PRZEPOMPOWANIE
```

**Kluczowe różnice vs K7:**
- Etap utlenienia wymaga DWÓCH kroków — najpierw kwas cytrynowy, potem perhydrol. K7 używa tylko perhydrolu.
- Dodatkowy etap ROZJAŚNIANIA (wybielania) po utlenieniu — dodatkowe porcje perhydrolu w celu poprawy barwy.

---

## Etap 1: AMIDOWANIE

**Cel:** Synteza amidu z oleju kokosowego (CNO) i DMAPA

### Operacje:
1. Załadunek surowców (CNO 1200 kg + kwasy C12-18 ~100 kg + woda)
2. Włączenie reaktora (temp. docelowa: 132°C — niższa niż K7!)
3. Załadunek DMAPA czystej (~720 kg)
4. Reakcja amidowania
5. Destylacja DMAPA (odzysk zwrotów)

### Etap analityczny:
| Parametr | Skrót | Typ | Kiedy | Kryterium |
|----------|-------|-----|-------|-----------|
| Liczba estrowa (LE) | le | titracja | w trakcie reakcji | monitorowanie postępu |
| Liczba kwasowa (LA) | la | titracja | po destylacji | monitorowanie |
| Liczba kwasowa końcowa (LK) | lk | titracja | po destylacji | < 1.0 mg KOH/g |
| Współczynnik załamania (nD20) | nd20 | bezpośredni | po destylacji | orientacyjnie ~1.46 |
| Barwa | barwa | organoleptycznie | po destylacji | notatka opisowa |
| Ilość amidu | ilosc_amidu_kg | odczyt | po destylacji | bilans masowy (~1756 kg typowo) |

### Warunek przejścia dalej:
- LK < 1.0 mg KOH/g
- Destylacja zakończona

### Możliwe korekty:
- Przedłużenie czasu reakcji
- Dodatkowa porcja DMAPA

---

## Etap 2: WYTWORZENIE SMCA

**Cel:** Przygotowanie SMCA z MCA 80% + NaOH 50%

### Operacje:
1. Rozpuszczenie MCA 80% (~760 kg)
2. Neutralizacja NaOH 50% (~588 kg)

### Etap analityczny:
| Parametr | Skrót | Typ | Kiedy | Kryterium |
|----------|-------|-----|-------|-----------|
| pH roztworu SMCA | ph | bezpośredni | po neutralizacji | 3.0 - 4.0 |

### Warunek przejścia dalej:
- pH 3.0-4.0

### Możliwe korekty:
- Dodanie NaOH (pH za niskie)
- Dodanie MCA (pH za wysokie)

---

## Etap 3: CZWARTORZĘDOWANIE

**Cel:** Reakcja amidu z SMCA → betaina kokamidopropylo-dimetyloamoniowa

### Operacje:
1. Przeciągnięcie amidu do roztworu SMCA
2. Dozowanie NaOH porcjami (typowo 3-5 porcji)
3. Po każdej porcji → analiza

### Etap analityczny (powtarzany po każdej porcji NaOH):
| Parametr | Skrót | Typ | Kiedy | Kryterium |
|----------|-------|-----|-------|-----------|
| pH 10% | ph_10proc | bezpośredni | po porcji NaOH | 11.0 - 12.0 |
| Współczynnik załamania (nD20) | nd20 | bezpośredni | po porcji NaOH | monitorowanie (~1.40-1.41) |
| Aminokwasowość (%AA) | aa | titracja (alkacymetria, f=3.015) | po porcji NaOH | < 0.30% |
| Barwa | barwa | organoleptycznie | po porcji NaOH | ~1 GAL, 3 FAU typowo |

### Warunek przejścia dalej:
- pH_10proc: 11.0-12.0
- %AA < 0.30% (surowsze niż K7!)

### Możliwe korekty:
- Dodatkowa porcja NaOH (pH < 11.0)
- Dodanie MCA (pH > 12.0)
- Wydłużenie czasu (AA za wysoka)

---

## Etap 4: SULFONOWANIE

**Cel:** Reakcja z Na₂SO₃ — sulfonowanie betainy

### Operacje:
1. Dozowanie Na₂SO₃ (~150 kg)
2. Analiza po dodaniu

### Etap analityczny:
| Parametr | Skrót | Typ | Kiedy | Kryterium |
|----------|-------|-----|-------|-----------|
| pH 10% | ph_10proc | bezpośredni | po Na₂SO₃ | monitorowanie |
| %SO₃²⁻ | so3 | titracja (jodometryczna, f=0.4) | po Na₂SO₃ | < 0.30% |
| %H₂O₂ | h2o2 | titracja (manganometryczna, f=0.17) | po Na₂SO₃ | monitorowanie |
| Współczynnik załamania (nD20) | nd20 | bezpośredni | po Na₂SO₃ | monitorowanie |

### Warunek przejścia dalej:
- %SO₃²⁻ < 0.30%

### Możliwe korekty:
- Dodatkowa porcja Na₂SO₃

---

## Etap 5: UTLENIENIE (dwuetapowe — specyficzne dla K40GLOL!)

**Cel:** Redukcja pH kwasem cytrynowym + utlenienie siarczynów perhydrolem

### KROK 5a: Kwas cytrynowy
**Operacja:** Dozowanie kwasu cytrynowego (25-100 kg, może w kilku porcjach)

**Analiza po kwasie cytrynowym:**
| Parametr | Skrót | Typ | Kryterium |
|----------|-------|-----|-----------|
| pH 10% | ph_10proc | bezpośredni | spada do ~10.0-11.0 |
| %SO₃²⁻ | so3 | titracja | może wzrosnąć tymczasowo |
| nD20 | nd20 | bezpośredni | monitorowanie |

### KROK 5b: Perhydrol
**Operacja:** Dozowanie Perhydrolu (5-100 kg, może w kilku porcjach)

**Analiza po perhydrolu:**
| Parametr | Skrót | Typ | Kryterium |
|----------|-------|-----|-----------|
| pH 10% | ph_10proc | bezpośredni | wzrasta z powrotem |
| %SO₃²⁻ | so3 | titracja (jodometryczna) | < 0.030% (cel: bliski zeru) |
| %H₂O₂ | h2o2 | titracja (manganometryczna) | < 0.010% |
| nD20 | nd20 | bezpośredni | monitorowanie |
| Barwa | barwa | organoleptycznie | monitorowanie |

### Warunek przejścia dalej:
- %SO₃²⁻ < 0.030%
- %H₂O₂ < 0.010%

### Możliwe korekty:
- Dodatkowa porcja perhydrolu (jeśli %SO₃ > 0.030%)
- Dodatkowa porcja kwasu cytrynowego (jeśli pH za wysokie)

---

## Etap 6: ROZJAŚNIANIE (WYBIELANIE)

**Cel:** Poprawa barwy produktu przez dodatkowe utlenienie perhydrolem. Etap opcjonalny — stosowany gdy barwa po utlenieniu jest zbyt ciemna.

### Operacje:
1. Dozowanie Perhydrolu (5-50 kg, może w kilku porcjach)
2. Mieszanie i oczekiwanie na reakcję (30-60 min)
3. Analiza barwy

### Etap analityczny (powtarzany po każdej porcji):
| Parametr | Skrót | Typ | Kryterium |
|----------|-------|-----|-----------|
| pH 10% | ph_10proc | bezpośredni | monitorowanie (nie powinno znacząco się zmienić) |
| %H₂O₂ | h2o2 | titracja (manganometryczna, f=0.17) | 0.005 - 0.050% (tymczasowo wyższe) |
| Barwa FAU | barwa_fau | bezpośredni | cel: < 5 FAU |
| Barwa Hz | barwa_hz | bezpośredni | cel: < 150 Hz |

### Warunek przejścia dalej:
- Barwa akceptowalna (FAU < 5, Hz < 150)
- %H₂O₂ resztkowy w kontrolowanym zakresie (rozkłada się z czasem)

### Możliwe korekty:
- Dodatkowa porcja perhydrolu (jeśli barwa nadal za ciemna)
- Wydłużenie czasu mieszania (H₂O₂ potrzebuje czasu na reakcję)

### Uwagi:
- Nadmiar perhydrolu → %H₂O₂ resztkowy za wysoki → trzeba poczekać na rozkład
- Zbyt dużo perhydrolu może pogorszyć inne parametry
- Etap może być pominięty jeśli barwa po utlenieniu jest wystarczająco jasna

---

## Etap 7: STANDARYZACJA (cykliczny)

**Cel:** Doprowadzenie produktu do specyfikacji P833/P826

### Cykl: ANALIZA → (korekta?) → ANALIZA → (korekta?) → ... → OK

### Dozwolone dodatki standaryzacyjne:
| Dodatek | Cel | Efekt |
|---------|-----|-------|
| Woda (H₂O) | Rozcieńczenie | SM↓, SA↓, H₂O↑ |
| Kwas cytrynowy | Korekta pH | pH↓ |
| Perhydrol | Odbarwienie / utlenienie | barwa↓, SO₃↓, H₂O₂↑ |
| NaCl (sól) | Korekta zasolenia | NaCl↑ |
| NaOH | Korekta pH | pH↑ |

### Etap analityczny (powtarzany po każdej korekcie):
| Parametr | Skrót | Typ | Zakres K40GLOL | Metoda |
|----------|-------|-----|----------------|--------|
| Sucha masa [%] | sm | bezpośredni | min 44.0 | L903 |
| NaCl [%] | nacl | titracja (Mohr, f=0.585) | 5.8 - 7.3 | L941 |
| pH 10% (20°C) | ph_10proc | bezpośredni | 4.5 - 5.5 | L905 |
| Współczynnik załamania (nD20) | nd20 | bezpośredni | 1.3900 - 1.4200 | PN-EN ISO 6320 |
| Substancja aktywna [%] | sa | obliczeniowy | 37.0 - 42.0 | SM - NaCl - 0.6 |
| Aminokwasowość [%] | aa | titracja (alkacymetria, f=3.015) | 0 - 0.30 | L904 |
| %H₂O₂ | h2o2 | titracja (manganometryczna, f=0.17) | 0 - 0.010 | L901 |
| %SO₃²⁻ | so3 | titracja (jodometryczna, f=0.4) | 0 - 0.030 | — |
| Barwa FAU | barwa_fau | bezpośredni | 0 - 200 | L928 |
| Barwa Hz | barwa_hz | bezpośredni | 0 - 500 | L928 |
| Wolna amina [%] | wolna_amina | titracja | 0 - 0.50 | L904 |
| H₂O [%] | h2o | bezpośredni | 50.0 - 58.0 | L903 |

### Warunek przejścia do analizy końcowej:
- WSZYSTKIE parametry w zakresie specyfikacji
- Jeśli którykolwiek poza normą → korekta → re-analiza

### Logika korekty:
| Problem | Działanie | Uwagi |
|---------|-----------|-------|
| SM za wysoka | Dodaj wodę | najczęstsza korekta |
| pH za wysoki | Dodaj kwas cytrynowy | |
| pH za niski | Dodaj NaOH | |
| NaCl za niski | Dodaj NaCl | często 15-25 kg |
| NaCl za wysoki | Dodaj wodę (rozcieńcz) | |
| Barwa za ciemna | Dodaj perhydrol | |
| SO₃ za wysoki | Dodaj perhydrol | |
| H₂O₂ za wysoki | Poczekaj (rozkład) | |
| SA za niska | Dodaj NaCl lub odparuj wodę | |
| Wolna amina za wysoka | Wydłuż czas reakcji | rzadko na tym etapie |

---

## Etap 8: ANALIZA KOŃCOWA

**Cel:** Potwierdzenie zgodności ze specyfikacją P833

### Parametry końcowe (świadectwo jakości):
| Parametr | Skrót | Zakres K40GLOL | Metoda | Format |
|----------|-------|----------------|--------|--------|
| Barwa w skali Hazena | barwa_hz | max 150 | L928 | integer |
| Zapach | — | słaby/faint | organoleptycznie | jakościowy: zgodny/right |
| Wygląd | — | klarowna ciecz/clear liquid | organoleptycznie | jakościowy: zgodny/right |
| pH (20°C) | ph_10proc | 4.50 - 5.50 | L905 | 2 miejsca |
| Substancja aktywna [%] | sa | 37.0 - 42.0 | L932 | 1 miejsce |
| NaCl [%] | nacl | 5.8 - 7.3 | L941 | 1 miejsce |
| Sucha masa [%] | sm | min 44.0 | L903 | 1 miejsce |
| H₂O [%] | h2o | 52.0 - 56.0 | L903 | 1 miejsce |
| Wolna kokamidopropylodimetyloamina [%] | wolna_amina | max 0.30 | L904 | 2 miejsca |

### Ocena jakości:
- **zgodna** → produkt trafia do zbiornika magazynowego
- **niezgodna** → rework lub downgrade
- **downgrade** → może być sprzedany jako K40GLOS, K40GLO, lub K40GL (niższa specyfikacja)

---

## Etap 9: PRZEPOMPOWANIE

**Cel:** Transfer produktu do zbiornika magazynowego

### Dane rejestrowane:
- Czas rozpoczęcia/zakończenia
- Temperatura max (typowo 40-50°C)
- Nr zbiornika docelowego (np. M1, M16, M17)
- Wskazania przepływomierza (od/do)
- Podpis operatora

---

## Różnice K40GLOL vs K7 — podsumowanie

| Aspekt | K7 | K40GLOL |
|--------|-----|---------|
| Surowiec tłuszczowy | Kwasy C12-18 | CNO (olej kokosowy) |
| Temp. amidowania | 160-170°C | 132°C |
| Utlenienie | Tylko perhydrol | Kw. cytrynowy + perhydrol |
| %AA limit | < 0.50% | < 0.30% (surowsze) |
| %SO₃ na świadectwie | nie | tak (max 0.030%) |
| %H₂O₂ na świadectwie | nie | tak (max 0.010%) |
| H₂O na świadectwie | nie | tak (52-56%) |
| Wolna amina | nie | tak (max 0.30%) |
| Barwa skala | jodowa (max 3) | Hazen (max 150) |
| pH specyfikacja | 4.50-7.50 | 4.50-5.50 (węższe) |
| SM specyfikacja | min 35.5 (na świadectwie) | min 44.0 |
| NaCl specyfikacja | max 5.5 (na świadectwie) | 5.8-7.3 |
| SA specyfikacja | 30.0-32.0 (na świadectwie) | 37.0-42.0 |
| Warianty klienckie | ADAM&PARTNER, DR. MIELE | Loreal, Kosmepol, OQEMA |
| Warianty MB | tak | tak (RSPO) |
