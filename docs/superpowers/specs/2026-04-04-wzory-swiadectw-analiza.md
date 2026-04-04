# Analiza Wzorów Świadectw Jakości / Certificate Templates Analysis

Data: 2026-04-04
Źródło: `data/wzory/` (86 plików: 59 .docx + 27 .doc)

---

## 1. Wspólna struktura wszystkich świadectw

Każde świadectwo ma identyczny układ (dwujęzyczny PL/EN):

```
┌─────────────────────────────────────────────────────┐
│  LOGO + NAGŁÓWEK FIRMY                              │
│  PPU Chemco Sp. z o.o., ul. Kościuszki 19,         │
│  83-033 Sobowidz, BDO: 000003546                    │
├─────────────────────────────────────────────────────┤
│  ŚWIADECTWO JAKOŚCI / CERTIFICATE OF ANALYSIS       │
│  {Nazwa produktu}                                   │
├─────────────────────────────────────────────────────┤
│  [AVON code: ...]          ← tylko wariant AVON     │
│  [AVON name: ...]          ← tylko wariant AVON     │
│                                                     │
│  Klasyfikowany na podstawie specyfikacji /           │
│  Classified on TDS: {P___}  CAS: {___-__-_}        │
│                                                     │
│  Partia / Batch: __/{rok}                           │
│  Data produkcji / Production date: __.__.____       │
│  Data ważności / Expiry date: __.__.____            │
│  [Numer zamówienia / Order No.: ___]    ← NR_ZAM   │
│  [Numer certyfikatu / Certificate No.: CU-RSPO...] │
│                                        ← MB        │
├─────────────────────────────────────────────────────┤
│  TABELA PARAMETRÓW                                  │
│  ┌──────────────┬──────────┬──────────┬──────────┐  │
│  │ Parametr     │Wymagania │ Metoda   │ Wynik    │  │
│  │/Characteristic│/Requirement│/Test method│/Result│  │
│  ├──────────────┼──────────┼──────────┼──────────┤  │
│  │ {param 1}    │ {req}    │ {method} │ {value}  │  │
│  │ ...          │ ...      │ ...      │ ...      │  │
│  └──────────────┴──────────┴──────────┴──────────┘  │
├─────────────────────────────────────────────────────┤
│  Kraj pochodzenia / Country of origin: Polska/Poland│
│  Opinia Laboratorium KJ:                            │
│  Produkt odpowiada wymaganiom {P___} /              │
│  The product complies with {P___}                   │
│                                                     │
│  Sobowidz, {data}                                   │
│  Wystawił / The certificate made by:                │
│  Specjalista ds. KJ / Quality Control Specialist    │
│  Dokument utworzony elektronicznie,                  │
│  nie wymaga podpisu.                                │
└─────────────────────────────────────────────────────┘
```

---

## 2. Warianty pól (flagi)

Każdy produkt może mieć od 1 do kilku wariantów świadectwa. Warianty różnią się **obecnością dodatkowych pól**:

| Flaga | Dodatkowe pola | Kiedy używany |
|-------|---------------|---------------|
| **base** | brak dodatkowych | Standardowe świadectwo |
| **MB** | `Numer certyfikatu / Certificate No.` + certyfikat RSPO (CU-RSPO SCC-857488) | Dla klientów wymagających numeru certyfikatu / RSPO |
| **NR_ZAM** | `Numer zamówienia / Order No.` | Dla zamówień z numerem referencyjnym klienta |
| **MB + NR_ZAM** | Oba powyższe | Kombinacja obu |
| **PELNA** | Rozszerzona tabela parametrów (więcej wierszy) | Tylko Chelamid DK |
| **AVON** | `Kod AVON / AVON code`, `Nazwa AVON / AVON name`, nr zamówienia, nr certyfikatu, RSPO | Klient AVON |
| **client-specific** | Czasem dodatkowe parametry, czasem inne wartości wymagań | Per-klient |

### Matryca wariantów per produkt

| Produkt | base | MB | NR_ZAM | MB+NR_ZAM | PELNA | Klienci |
|---------|------|----|--------|-----------|-------|---------|
| Chegina K40GLOL | x | - | - | - | - | Loreal, Loreal Belgia, Loreal Włochy, Kosmepol |
| Chegina K40GLO | x | x | x | x | - | - |
| Chegina K40GL | x | x | x | - | - | ADAM&PARTNER |
| Chegina K40GLN | x | x | - | - | - | - |
| Chegina K40GLOS | x | x | - | - | - | - |
| Chegina GLOL40 | x | x | x | - | - | OQEMA |
| Chegina K7 | x | x | x | - | - | ADAM&PARTNER, DR. MIELE |
| Chegina K7B | x | x | x | - | - | - |
| Chegina KK | x | - | - | - | - | AVON, LEHVOSS, PRIME, REVADA, SKINCHEM |
| Chegina CC | x | - | - | - | - | - |
| Chegina CCR | x | - | - | - | - | - |
| Chelamid DK | x | x | x | x | x | ELIN |
| Cheminox K | x | x | x | - | - | - |
| Cheminox K 35 | x | - | x | - | - | - |
| Monamid KO | x | - | x | - | - | AVON, GHP |
| Monamid K | x | - | - | - | - | - |
| Alkinol | x | - | - | - | - | - |
| Alkinol B | x | x | - | - | - | AVON |
| Alstermid K | x | - | - | - | - | - |
| Glikoster P | x | - | - | - | - | AVON |
| Citrowax | x | - | - | - | - | - |
| Dister E | x | - | - | - | - | - |
| Monester O | x | - | - | - | - | - |
| Monester S | x | - | - | - | - | - |
| Perlico 45 | x | - | x | - | - | + wariant REUSE |
| Chemal CS 30/70 | x | x | x | - | - | - |
| Chemal CS 50/50 | - | x | - | - | - | - |
| HSH CS 30/70 | x | x | - | - | - | - |
| SLES | x | - | - | - | - | - |

---

## 3. Katalog produktów — dane stałe

### 3.1 Betainy (rodzina Chegina)

#### Chegina K40GLOL
- **Spec:** P833 | **CAS:** 147170-44-3
- **Warianty:** base, Loreal (P826), Loreal Belgia (P826), Loreal Włochy (P826), Kosmepol (P826)
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Barwa w skali Hazena | Colour (Hazen scale) | max 150 | L928 |
| Zapach | Odour | słaby / faint | organoleptycznie / organoleptic |
| Wygląd | Appearance | klarowna ciecz / clear liquid | organoleptycznie / organoleptic |
| pH (20°C) | pH (20°C) | 4,50-5,50 | L905 |
| Substancja aktywna [%] | Active matter [%] | 37,0-42,0 | L932 |
| NaCl [%] | NaCl [%] | 5,8-7,3 | L941 |
| Sucha masa [%] | Dry matter [%] | min. 44,0 | L903 |
| H2O [%] | H2O [%] | 52,0-56,0 | L903 |
| Wolna kokamidopropylodimetyloamina [%] | Free cocamidopropyldimethylamine [%] | max 0,30 | L904 |

> **Uwaga Loreal/Kosmepol:** Spec zmienia się na P826, parametry identyczne ale bez Sucha masa i H2O w niektórych wariantach.

#### Chegina K40GLO
- **Spec:** P825 | **CAS:** 147170-44-3
- **Warianty:** base, MB, NR_ZAM, MB+NR_ZAM
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Sucha masa [%] | Dry matter [%] | min 44,0 | L903 |
| NaCl [%] | NaCl [%] | 5,8-7,3 | L941 |
| Barwa w skali Hazena | Colour (Hazen scale) | max 200 | L928 |
| pH (10%, aq) | pH (10%, aq) | 5,00-7,00 | L905 |
| Substancja aktywna [%] | Active matter [%] | min 37,0 | L932 |
| Gęstość (20°C) [g/cm3] | Density (20°C) [g/cm3] | 1,05-1,09 | L917 |

#### Chegina K40GL
- **Spec:** P827 | **CAS:** 1334422-09-1
- **Warianty:** base, MB, NR_ZAM, ADAM&PARTNER
- **Parametry (base):**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Sucha masa [%] | Dry matter [%] | min 44,0 | L903 |
| NaCl [%] | NaCl [%] | 5,8-7,3 | L941 |
| Barwa w skali Hazena | Colour (Hazen scale) | max 150 | L928 |
| pH (10%, aq) | pH (10%, aq) | 4,50-5,50 | L905 |
| Substancja aktywna [%] | Active matter [%] | min 37,0 | L932 |

> **ADAM&PARTNER dodaje:** Nadtlenki w przeliczeniu na H2O2 [%] / Peroxides as H2O2 [%] | max 0,00 | L901

#### Chegina K40GLN
- **Spec:** P836 | **CAS:** 1334422-09-1
- **Warianty:** base, MB
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Barwa w skali Hazena | Colour (Hazen scale) | max 150 | L928 |
| Zapach | Odour | słaby / faint | organoleptycznie / organoleptic |
| Wygląd | Appearance | klarowna ciecz / clear liquid | organoleptycznie / organoleptic |
| pH (20°C) | pH (20°C) | 4,50-5,50 | L905 |
| Substancja aktywna [%] | Active matter [%] | 37,6-40,0 | L932 |
| NaCl [%] | NaCl [%] | 5,8-7,3 | L941 |
| Sucha masa [%] | Dry matter [%] | min 44,0 | L903 |
| H2O [%] | H2O [%] | max. 56,0 | L903 |
| Zawartość wolnego aminoamidu [%] | Free aminoamide [%] | max 0,30 | L904 |

#### Chegina K40GLOS
- **Spec:** P834 | **CAS:** 147170-44-3
- **Warianty:** base, MB
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Barwa w skali Hazena | Colour (Hazen scale) | max 150 | L928 |
| Zapach | Odour | słaby / faint | organoleptycznie / organoleptic |
| Wygląd | Appearance | klarowna ciecz / clear liquid | organoleptycznie / organoleptic |
| pH (20°C) | pH (20°C) | 4,50-5,50 | L905 |
| Substancja aktywna [%] | Active matter [%] | 39,0-42,0 | L932 |
| NaCl [%] | NaCl [%] | 5,8-7,3 | L941 |
| Sucha masa [%] | Dry matter [%] | min 44,8 | L903 |
| H2O [%] | H2O [%] | 52,0-55,2 | L903 |
| Wolna kokamidopropylodimetyloamina [%] | Free cocamidopropyldimethylamine [%] | max 0,30 | L904 |

#### Chegina GLOL40
- **Spec:** P826 | **CAS:** 147170-44-3
- **Warianty:** base, MB, NR_ZAM, OQEMA
- **Parametry (base):**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Barwa | Colour | jasnożółty / pale yellow | organoleptycznie / organoleptic |
| Zapach | Odour | charakterystyczny słaby / characteristic faint | organoleptycznie / organoleptic |
| Wygląd | Appearance | klarowna ciecz / clear liquid | organoleptycznie / organoleptic |
| pH | pH | 4,50-5,50 | L905 |
| Substancja aktywna [%] | Active matter [%] | 37,0-42,0 | L932 |
| Wolna kokamidopropylodimetyloamina [%] | Free cocamidopropyldimethylamine [%] | max 0,30 | L904 |

> **OQEMA dodaje:** NaCl [%] 5,8-7,3 (L941) + H2O [%] 52,0-56,0 (L903)

#### Chegina K7
- **Spec:** P819 | **CAS:** 1334422-09-1
- **Warianty:** base, MB, NR_ZAM, ADAM&PARTNER, DR. MIELE
- **Parametry (base):**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Sucha masa [%] | Dry matter [%] | min 35,5 | L903 |
| Wsp. załamania światła (nD20) | Refraction (nD20) | 1,3800-1,3950 | PN-EN ISO 6320:2017-04 |
| Barwa w skali jodowej | Colour (Iodine scale) | max 3 | L928 |
| Substancja aktywna [%] | Active matter [%] | 30,0-32,0 | L932 |

> **ADAM&PARTNER dodaje:** Nadtlenki w przeliczeniu na H2O2 [%] / Peroxides as H2O2 [%] | max 0,00 | L901

#### Chegina K7B
- **Spec:** P837 | **CAS:** brak
- **Warianty:** base, MB, NR_ZAM
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Sucha masa [%] | Dry matter [%] | 36-38 | L903 |
| Barwa w skali jodowej | Colour (Iodine scale) | max 2 | L928 |
| Substancja aktywna [%] | Active matter [%] | 29-31 | L932 |

#### Chegina KK
- **Spec:** P818 | **CAS:** brak
- **Warianty:** base, AVON, LEHVOSS, PRIME, REVADA, SKINCHEM
- **Parametry (wszystkie warianty identyczne):**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Zapach | Odour | charakterystyczny, słaby tłuszczowo-aminowy / characteristic, faint fatty-amine | organoleptycznie / organoleptic |
| Wygląd | Appearance | klarowna ciecz / clear liquid | organoleptycznie / organoleptic |
| pH (10%, 25°C) | pH (10%, 25°C) | 5,00-7,00 | L905 |
| NaCl [%] | NaCl [%] | 4,0-6,0 | L941 |
| Substancja aktywna [%] | Active matter [%] | 29,0-32,0 | L932 |
| Zawartość wolnego aminoamidu [%] | Free aminoamide [%] | max 0,50 | L904 |
| Barwa w skali jodowej | Colour (Iodine scale) | max 1 | L928 |
| MCA [ppm] | MCA [ppm] | max 3000 | metoda zew. / external method |
| DCA [ppm] | DCA [ppm] | max 400 | metoda zew. / external method |
| DMAPA [ppm] | DMAPA [ppm] | max 100 | metoda zew. / external method |

> Klienci KK różnią się **tylko** obecnością pól (AVON code, nr zamówienia, nr certyfikatu) — parametry te same.

#### Chegina CC
- **Spec:** P828 | **CAS:** 66455-29-6
- **Warianty:** base
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Wygląd | Appearance | klarowna ciecz / clear liquid | organoleptycznie / organoleptic |
| Barwa w skali Hazena | Colour (Hazen scale) | max 250 | L928 |
| Zapach | Odour | charakterystyczny, słaby / faint, characteristic | organoleptycznie / organoleptic |
| pH (5%, aq, 25°C) | pH (5%, aq, 25°C) | 6,00-8,00 | L905 |
| Substancja aktywna [%] | Active matter [%] | 29,0-33,0 | L932 |
| Alkaliczność [meq/g] | Total alkalinity [meq/g] | 1,15-1,30 | L921 |

#### Chegina CCR
- **Spec:** P829 | **CAS:** 66455-29-6
- **Warianty:** base
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Wygląd | Appearance | klarowna ciecz / clear liquid | organoleptycznie / organoleptic |
| Barwa w skali Hazena | Color (Hazen scale) | max 250 | L928 |
| Zapach | Odour | charakterystyczny słaby / faint characteristic | organoleptycznie / organoleptic |
| pH (5%, aq, 25°C) | pH (5%, aq, 25°C) | 6,00-8,00 | L905 |
| Substancja aktywna [%] | Active matter [%] | 29,0-31,5 | L932 |

### 3.2 Amidy (Chelamid, Monamid)

#### Chelamid DK
- **Spec:** P816 | **CAS:** 68155-07-7
- **Warianty:** base, MB, NR_ZAM, MB+NR_ZAM, PELNA, PELNA+NR_ZAM, ELIN
- **Parametry (base):**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| DEA [%] | DEA [%] | < 3,00 | L910 |
| Barwa w skali jodowej | Colour (Iodine scale) | max 6 | L928 |
| pH (1%, aq) | pH (1%, aq) | max 11,00 | L905 |

> **ELIN dodaje:** Dietanoloamid [%] / Diethanoloamide [%] | 80,0-90,0 | L910 + Postać / Form | klarowna żółta ciecz / clear yellow liquid | organoleptycznie / organoleptic
> **PELNA:** Rozszerzona tabela — dodatkowe wiersze z parametrami (do weryfikacji w oryginalnym pliku)

#### Monamid KO
- **Spec:** P833 | **CAS:** 69227-24-3
- **Warianty:** base, NR_ZAM, AVON, GHP
- **Parametry (base/GHP):**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Barwa w skali Gardnera | Colour (Gardner scale) | max 5 (GHP: max 6) | L948 |
| Zapach | Odour | charakterystyczny aminowy / characteristic, amine-like | organoleptycznie / organoleptic |
| Wygląd | Appearance | substancja stała, woskowa / flakes, waxy | organoleptycznie / organoleptic |
| Wolne kwasy tłuszczowe [%] (kwas laurynowy M=200,3) | Free fatty acids [%] as lauric acid | max 0,5 | L925 |
| MEA [%] (M=61,1 g/mol) | MEA [%] | max 1,5 | L953 |
| Estry [%] | Esters [%] | max 6,0 | L952 |

> **AVON dodaje:** Gliceryna [%] / Glycerine [%] | max 11,0 | L954 + Rozkład kwasów tłuszczowych [%] / Fatty acid distribution [%]

#### Monamid K
- **Spec:** P824 | **CAS:** brak
- **Warianty:** base
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Barwa w skali jodowej | Colour (Iodine scale) | max 5 | L928 |
| Wolne kwasy tłuszczowe [%] (kwas laurynowy) | Free fatty acids [%] as lauric acid | max 1,0 | L925 |
| MEA [%] (M=61,1 g/mol) | MEA [%] | max 1,5 | L933 |
| Estry [%] (laurynian metylu) | Esters [%] as methyl laurate | max 6,0 | L952 |

### 3.3 Oksyetylaty aminowe (Cheminox)

#### Cheminox K
- **Spec:** P822 | **CAS:** 1471314-81-4
- **Warianty:** base, MB, NR_ZAM
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Sucha masa [%] | Dry matter [%] | 30,0-35,0 | L903 |
| Substancja aktywna [%] | Active matter [%] | 30,0-35,0 | L903 |
| Barwa w skali jodowej | Colour (Iodine scale) | max 2 | L928 |

#### Cheminox K 35
- **Spec:** P835 | **CAS:** 1471314-81-4
- **Warianty:** base, NR_ZAM
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Sucha masa [%] | Dry matter [%] | 34,0-36,0 | L903 |
| Substancja aktywna [%] | Active matter [%] | 34,0-36,0 | L903 |
| Barwa w skali jodowej | Colour (Iodine scale) | max 2 | L928 |

### 3.4 Alkohole tłuszczowe (Alkinol)

#### Alkinol
- **Spec:** P801 | **CAS:** brak
- **Warianty:** base
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Barwa w skali jodowej | Colour (Iodine scale) | max 2 | L928 |
| Zapach | Odour | charakterystyczny / characteristic | organoleptycznie / organoleptic |
| Wygląd | Appearance | wosk / wax | P801 |
| Liczba kwasowa [mg KOH/g] | Acid value [mg KOH/g] | max 2,00 | PN-EN ISO 660:2021-03 |
| Liczba zmydlania [mg KOH/g] | Saponification value [mg KOH/g] | max 2,00 | PN-EN ISO 3657:2024-01 |
| Temperatura kroplenia [°C] | Dropping point [°C] | 47,0-55,0 | L934 |
| Liczba hydroksylowa [mg KOH/g] | Hydroxyl value [mg KOH/g] | 135-160 | L929 |

#### Alkinol B
- **Spec:** P801 | **CAS:** brak
- **Warianty:** base, MB, AVON
- **Parametry (base):**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Barwa w skali jodowej | Colour (Iodine scale) | max 2 | L928 |
| Zapach | Odour | charakterystyczny / characteristic | organoleptycznie / organoleptic |
| Wygląd | Appearance | wosk / wax | P801 |
| Liczba kwasowa [mg KOH/g] | Acid value [mg KOH/g] | max 2,00 | PN-EN ISO 660:2021-03 |
| Liczba zmydlania [mg KOH/g] | Saponification value [mg KOH/g] | max 2,00 | PN-EN ISO 3657:2024-01 |
| Temperatura kroplenia [°C] | Dropping point [°C] | 47,0-55,0 | L934 |
| Liczba hydroksylowa [mg KOH/g] | Hydroxyl value [mg KOH/g] | 155-180 | L929 |
| Liczba jodowa [g I2/100g] | Iodine value [g I2/100g] | max 2,00 | PN-EN ISO 3961:2018-09 |

### 3.5 Amidoaminy (Alstermid)

#### Alstermid K
- **Spec:** P806 | **CAS:** 7651-02-7
- **Warianty:** base (2 pliki — stary .doc + nowy .docx)
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Liczba kwasowa [mg KOH/g] | Acid value [mg KOH/g] | max 15,0 | PN-EN ISO 660:2021-03 |
| Liczba aminowa [mg KOH/g] | Amine value [mg KOH/g] | 130-160 | L914 |

### 3.6 Estry (Glikoster, Dister, Monester, Citrowax)

#### Glikoster P
- **Spec:** P804 | **CAS:** 1323-39-3
- **Warianty:** base, AVON
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Barwa w skali jodowej | Colour (Iodine scale) | max 2 | L928 |
| Zapach | Odour | charakterystyczny / characteristic | organoleptycznie / organoleptic |
| Wygląd | Appearance | substancja woskowa / wax | P804 |
| Liczba kwasowa [mg KOH/g] | Acid value [mg KOH/g] | max 3,0 | PN-EN ISO 660:2021-03 |
| Wolny glikol [%] | Free glycol [%] | max 3,0 | L909 |
| Liczba hydroksylowa [mg KOH/g] | Hydroxyl value [mg KOH/g] | 70,0-130,0 | L929 |
| Monoestry [%] | Monoesters [%] | 47,0-55,0 | L930 |

> **AVON dodaje:** %C14:0, %C16:0, %C18:0&C18:1 | max 5, 47-55, 41-51 | metoda dostawcy surowca

#### Dister E
- **Spec:** P805 | **CAS:** 91031-31-1
- **Warianty:** base
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Liczba kwasowa [mg KOH/g] | Acid value [mg KOH/g] | max 6,00 | PN-EN ISO 660:2021-03 |
| Wolny glikol etylenowy [%] | Free ethylene glycol [%] | <1,00 | L909 |
| Liczba hydroksylowa [mg KOH/g] | Hydroxyl value [mg KOH/g] | max 54,0 | L929 |
| Liczba zmydlenia [mg KOH/g] | Saponification value [mg KOH/g] | 188-200 | PN-EN ISO 3657:2024-01 |
| Temperatura topnienia [°C] | Melting point [°C] | 58,0-64,0 | L934 |

#### Monester O
- **Spec:** P802 | **CAS:** 68424-61-3
- **Warianty:** base
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Liczba kwasowa [mg KOH/g] | Acid value [mg KOH/g] | max 3,00 | PN-EN ISO 660:2021-03 |
| Liczba zmydlania [mg KOH/g] | Saponification value [mg KOH/g] | 150-170 | PN-EN ISO 3657:2024-01 |
| Wsp. załamania światła nD20 | Refraction index nD20 | 1,4680-1,4730 | PN-EN ISO 6320:2017-04 |
| Liczba jodowa [g I2/100g] | Iodine value [g I2/100g] | 63,0-83,0 | PN-EN ISO 3961:2018-09 |

#### Monester S
- **Spec:** P803 | **CAS:** 31566-31-1
- **Warianty:** base
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Liczba kwasowa [mg KOH/g] | Acid value [mg KOH/g] | max 3 | PN-EN ISO 660:2021-03 |
| Temperatura kroplenia [°C] | Dropping point [°C] | 54,0-60,0 | L934 |
| Liczba zmydlania [mg KOH/g] | Saponification value [mg KOH/g] | 145-185 | PN-EN ISO 3657:2024-01 |
| Liczba jodowa [g I2/100g] | Iodine value [g I2/100g] | max 5,00 | PN-EN ISO 3961:2018-09 |

#### Citrowax
- **Spec:** P808 | **CAS:** 7775-50-0
- **Warianty:** base
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Liczba kwasowa [mg KOH/g] | Acid value [mg KOH/g] | max 1,00 | PN-EN ISO 660:2021-03 |
| Temperatura kroplenia [°C] | Dropping point [°C] | 48,0-52,0 | L934 |

### 3.7 Emulgatory (Perlico)

#### Perlico 45
- **Spec:** P809 | **CAS:** brak
- **Warianty:** base, NR_ZAM, REUSE
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Sucha masa [%] | Dry matter [%] | 43,0-45,0 | L903 |
| pH (10%, aq, 20°C) | pH (10%, aq, 20°C) | 5,00-9,00 | L905 |

### 3.8 Alkohole tłuszczowe mieszanki (Chemal, HSH)

#### Chemal CS 30/70
- **Spec:** brak | **CAS:** 67762-27-0
- **Warianty:** base, MB, NR_ZAM
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Liczba hydroksylowa [mg KOH/g] | Hydroxyl number [mg KOH/g] | 210-220 | L955 |
| Liczba kwasowa [mg KOH/g] | Acid value [mg KOH/g] | max 0,2 | zgodnie z świadectwem dostawcy |
| Liczba zmydlenia [mg KOH/g] | Saponification value [mg KOH/g] | max 1,2 | zgodnie z świadectwem dostawcy |
| Liczba jodowa [g I2/100g] | Iodine value [g I2/100g] | max 1,0 | zgodnie z świadectwem dostawcy |
| %C16 | %C16 | 25-35 | zgodnie z świadectwem dostawcy |
| %C18 | %C18 | 60-75 | zgodnie z świadectwem dostawcy |

#### Chemal CS 50/50
- **Spec:** brak | **CAS:** 67762-27-0
- **Warianty:** MB
- **Parametry:** Jak CS 30/70 ale: Liczba hydroksylowa 210-225, %C16: 45-55, %C18: 45-55

#### HSH CS 30/70
- **Spec:** brak | **CAS:** 67762-27-0
- **Warianty:** base, MB
- **Parametry:** Jak Chemal CS 30/70 ale: Liczba kwasowa max 0,1, Liczba zmydlenia max 1,0, %C16: 25-32, %C18: 65-75, metody: numery wew. (60064737*, 60065250*, etc.)

### 3.9 Tensydy anionowe

#### SLES
- **Spec:** P834 | **CAS:** brak
- **Warianty:** base
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Barwa | Colour | bezbarwna-jasnożółta / clear to light yellow | organoleptycznie / organoleptic |
| pH (3%, aq) | pH (3%, aq) | 6,50-7,50 | L905 |
| Substancja aktywna [%] | Active matter [%] | 25,0-28,0 | L920 |

### 3.10 Niezidentyfikowany

#### Kwas Stearynowy (?)
- **Spec:** P830 | **CAS:** 67701-03-5
- **Plik:** `Świadectwo_Certificate-Kw. Stearynowy WZÓR.docx`
- **Parametry:**

| Parametr PL | Parametr EN | Wymagania | Metoda |
|-------------|-------------|-----------|--------|
| Liczba kwasowa [mg KOH/g] | Acid value [mg KOH/g] | 206-212 | PN-EN ISO 660:2021-03 |
| Temperatura kroplenia [°C] | Dropping point [°C] | 54,0-56,5 | metoda dostawcy surowca |
| Liczba jodowa [g I2/100g] | Iodine value [g I2/100g] | max 0,50 | metoda dostawcy surowca |

---

## 4. Kluczowe różnice między klientami

### Pola specyficzne per klient:

| Klient | Dodatkowe pola | Produkty |
|--------|---------------|----------|
| **AVON** | Kod AVON (R#####), Nazwa AVON (INCI), Nr zamówienia, Nr certyfikatu, RSPO | Chegina KK, Alkinol B, Glikoster P, Monamid KO |
| **Loreal** | Nr zamówienia, Nr certyfikatu, RSPO | Chegina K40GLOL (base/Belgia/Włochy) |
| **Kosmepol** | Nr zamówienia, Nr certyfikatu, RSPO | Chegina K40GLOL |
| **ADAM&PARTNER** | Nr zamówienia + dodatkowy parametr (Nadtlenki H2O2) | Chegina K7, Chegina K40GL |
| **DR. MIELE** | Nr zamówienia, Nr certyfikatu | Chegina K7 |
| **PRIME** | Nr zamówienia, Nr certyfikatu, RSPO, Kod AVON(!), Nazwa AVON(!) | Chegina KK |
| **LEHVOSS** | Kod AVON(!), Nazwa AVON(!) — prawdopodobnie błąd w parsowaniu | Chegina KK |
| **REVADA** | Nr zamówienia | Chegina KK |
| **SKINCHEM** | Nr zamówienia | Chegina KK |
| **OQEMA** | Nr certyfikatu, RSPO + dodatkowe parametry (NaCl, H2O) | Chegina GLOL40 |
| **ELIN** | Nr zamówienia, Nr certyfikatu, RSPO + dodatkowe parametry | Chelamid DK |
| **GHP** | brak dodatkowych pól, ale Colour max 6 zamiast max 5 | Monamid KO |

---

## 5. Unikalne parametry — pełna lista

Wszystkie unikalne parametry występujące w świadectwach:

| ID | Parametr PL | Parametr EN | Produkty |
|----|-------------|-------------|----------|
| 1 | Sucha masa [%] | Dry matter [%] | K40GLOL, K40GLO, K40GL, K40GLN, K40GLOS, K7, K7B, Perlico 45, Cheminox K/K35 |
| 2 | Substancja aktywna [%] | Active matter [%] | K40GLOL, K40GLO, K40GL, K40GLN, K40GLOS, GLOL40, K7, K7B, KK, CC, CCR, Cheminox K/K35, SLES |
| 3 | pH | pH (różne warunki) | Prawie wszystkie |
| 4 | NaCl [%] | NaCl [%] | K40GLOL, K40GLO, K40GL, K40GLN, K40GLOS, GLOL40, KK |
| 5 | Barwa w skali Hazena | Colour (Hazen scale) | K40GLOL, K40GLO, K40GL, K40GLN, K40GLOS, CC, CCR |
| 6 | Barwa w skali jodowej | Colour (Iodine scale) | K7, K7B, KK, Chelamid DK, Cheminox K/K35, Alkinol/B, Monamid K, Glikoster P |
| 7 | Barwa w skali Gardnera | Colour (Gardner scale) | Monamid KO |
| 8 | Barwa (opisowa) | Colour (descriptive) | GLOL40, SLES |
| 9 | Wsp. załamania światła (nD20) | Refraction (nD20) | K7, Monester O |
| 10 | Gęstość (20°C) [g/cm3] | Density (20°C) [g/cm3] | K40GLO |
| 11 | H2O [%] | H2O [%] | K40GLOL, K40GLN, K40GLOS, GLOL40 |
| 12 | Wolna kokamidopropylodimetyloamina [%] | Free cocamidopropyldimethylamine [%] | K40GLOL, K40GLOS, GLOL40 |
| 13 | Zawartość wolnego aminoamidu [%] | Free aminoamide [%] | K40GLN, KK |
| 14 | Nadtlenki (H2O2) [%] | Peroxides as H2O2 [%] | K40GL (A&P), K7 (A&P) |
| 15 | Zapach | Odour | K40GLOL, K40GLN, K40GLOS, GLOL40, KK, Alkinol/B, Glikoster P, Monamid KO |
| 16 | Wygląd | Appearance | K40GLOL, K40GLN, K40GLOS, GLOL40, KK, CC, CCR, Alkinol/B, Glikoster P, Monamid KO |
| 17 | Liczba kwasowa [mg KOH/g] | Acid value [mg KOH/g] | Alkinol/B, Glikoster P, Dister E, Monester O/S, Citrowax, Chemal/HSH, Kw. Stearynowy |
| 18 | Liczba zmydlania [mg KOH/g] | Saponification value [mg KOH/g] | Alkinol B, Dister E, Monester O/S, Chemal/HSH |
| 19 | Liczba hydroksylowa [mg KOH/g] | Hydroxyl value [mg KOH/g] | Alkinol, Alkinol B, Glikoster P, Dister E, Chemal/HSH |
| 20 | Liczba jodowa [g I2/100g] | Iodine value [g I2/100g] | Alkinol B, Monester O/S, Chemal/HSH, Kw. Stearynowy |
| 21 | Temperatura kroplenia [°C] | Dropping point [°C] | Alkinol/B, Monester S, Citrowax, Kw. Stearynowy |
| 22 | Temperatura topnienia [°C] | Melting point [°C] | Dister E |
| 23 | Wolny glikol [%] | Free glycol [%] | Glikoster P |
| 24 | Wolny glikol etylenowy [%] | Free ethylene glycol [%] | Dister E |
| 25 | Monoestry [%] | Monoesters [%] | Glikoster P |
| 26 | DEA [%] | DEA [%] | Chelamid DK |
| 27 | Dietanoloamid [%] | Diethanoloamide [%] | Chelamid DK (ELIN) |
| 28 | Postać | Form | Chelamid DK (ELIN) |
| 29 | Liczba aminowa [mg KOH/g] | Amine value [mg KOH/g] | Alstermid K |
| 30 | MCA [ppm] | MCA [ppm] | Chegina KK |
| 31 | DCA [ppm] | DCA [ppm] | Chegina KK |
| 32 | DMAPA [ppm] | DMAPA [ppm] | Chegina KK |
| 33 | Wolne kwasy tłuszczowe [%] | Free fatty acids [%] | Monamid K, Monamid KO |
| 34 | MEA [%] | MEA [%] | Monamid K, Monamid KO |
| 35 | Estry [%] | Esters [%] | Monamid K, Monamid KO |
| 36 | Gliceryna [%] | Glycerine [%] | Monamid KO (AVON) |
| 37 | Rozkład kwasów tłuszczowych [%] | Fatty acid distribution [%] | Monamid KO (AVON), Glikoster P (AVON) |
| 38 | Alkaliczność [meq/g] | Total alkalinity [meq/g] | Chegina CC |
| 39 | %C16, %C18 | %C16, %C18 | Chemal CS, HSH CS |

---

## 6. Wnioski projektowe

### Co jest wspólne (jeden master template):
1. **Layout** — identyczny dla WSZYSTKICH 86 szablonów
2. **Nagłówek firmy** — PPU Chemco, adres, BDO
3. **Tytuł** — ŚWIADECTWO JAKOŚCI / CERTIFICATE OF ANALYSIS
4. **Stopka** — kraj, opinia, data, podpis, klauzula elektroniczna

### Co jest konfigurowalne (JSON/config per produkt):
1. **Nazwa produktu** — wyświetlana w tytule
2. **Numer specyfikacji** (P___) i numer CAS
3. **Lista parametrów** — od 2 do 10 wierszy, każdy z: nazwa PL/EN, wymagania, metoda
4. **Tekst opinii** — "Produkt odpowiada wymaganiom P___"

### Co jest wariantowe (flagi per zamówienie):
1. **Numer zamówienia** — obecny lub nie (flaga NR_ZAM)
2. **Numer certyfikatu + RSPO** — obecne lub nie (flaga MB)
3. **Kod/Nazwa AVON** — obecne lub nie (flaga AVON client)
4. **Dodatkowe parametry** — niektórzy klienci wymagają dodatkowych wierszy

### Struktura danych konfiguracyjnych (propozycja):

```json
{
  "product_id": "Chegina_K40GLOL",
  "display_name": "Chegina K40GLOL",
  "spec_number": "P833",
  "cas_number": "147170-44-3",
  "expiry_months": 12,
  "parameters": [
    {
      "id": "colour_hazen",
      "name_pl": "Barwa w skali Hazena",
      "name_en": "Colour (Hazen scale)",
      "requirement": "max 150",
      "method": "L928",
      "data_field": "analiza_koncowa.barwa_hz"
    },
    ...
  ],
  "client_overrides": {
    "Loreal": {
      "spec_number": "P826",
      "remove_parameters": ["dry_matter", "h2o"],
      "add_parameters": []
    },
    "ADAM&PARTNER": {
      "add_parameters": [
        {
          "id": "peroxides_h2o2",
          "name_pl": "Nadtlenki w przeliczeniu na H2O2 [%]",
          "name_en": "Peroxides as H2O2 [%]",
          "requirement": "max 0,00",
          "method": "L901",
          "data_field": "analiza_koncowa.procent_h2o2"
        }
      ]
    }
  }
}
```

### Odpowiedź na pytanie: "Jeden master, czy dobry pomysł?"

**TAK** — to jest idealne podejście, ponieważ:
- Layout jest 100% identyczny we wszystkich 86 plikach
- Jedyne różnice to: obecność/brak pól nagłówkowych + tabela parametrów
- Wystarczy **1 szablon HTML/PDF** + **1 plik JSON z konfiguracją per produkt/klient**
