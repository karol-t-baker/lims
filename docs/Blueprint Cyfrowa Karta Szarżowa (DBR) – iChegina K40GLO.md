

## 1. Architektura Danych (ML-Ready)

Zamiast statycznego formularza, zastosuj strukturę **Event Log (Dziennik Zdarzeń)**. Pozwala to modelom ML zrozumieć dynamikę procesu, a nie tylko wynik końcowy.

- **Tabela Szarż (`batches`):** `id`, `start_time`, `end_time`, `product_code`, `raw_material_lot_numbers` (kluczowe dla wykrywania błędów surowcowych).
    
- **Tabela Zdarzeń (`process_logs`):** * `batch_id` (FK)
    
    - `timestamp` (zawsze **UTC**)
        
    - `event_type` (ANALIZA | DOZOWANIE | KOREKTA | NOTATKA)
        
    - `parameter_name` (np. `pH`, `AA_conc`, `NaOH_kg`)
        
    - `value_numeric` (Float – dla obliczeń i ML)
        
    - `value_categorical` (Enum – dla mętności/barwy)
        
- **Logika Sensorów:** Każdy odczyt temp/ciśnienia z PLC powinien posiadać `batch_id`. Jeśli to niemożliwe, synchronizuj zegary (NTP) i łącz dane po czasie (tzw. _As-of Join_).
    

---

## 2. Logika Procesu i Interfejs (UX/UI)

Jako Dev/Owner, zaimplementuj **Maszynę Stanów (State Machine)**, która prowadzi laboranta/operatora za rękę.

### Etapy Krytyczne i Walidacja:

1. **Etap 1 (Synteza/SMCA):** Równoległe wpisywanie danych dla 1a i 1b. Blokada przejścia dalej bez zatwierdzenia LE (IR).
    
2. **Etap 2 (Czwartorzędowanie):** * Wymuś strukturę **1:N** dla korekt (możliwość dodania nieskończenie wielu porcji NaOH).
    
    - Każdy wpis NaOH generuje automatyczne pole na wynik pH.
        
3. **Obsługa "Mętności":** Nie używaj wolnego tekstu. Zastosuj skalę: `0: Klarowna`, `1: Opalizująca`, `2: Mętna`.
    
4. **Kalkulator Standaryzacji:** Zintegruj wzory chemiczne bezpośrednio w UI. Po wpisaniu Suchej Masy i Chlorków, system sam powinien wyliczyć ilość wody/soli do dodania.
    

---

## 3. Przygotowanie pod Machine Learning (Feature Engineering)

Aby model mógł przewidywać np. mętność lub dawkę kwasu, dane muszą być spójne:

- **Delta Recording:** Zapisuj stan _przed_ korektą i _po_ korekcie wraz z dokładną wagą dodanego surowca. To uczy model "siły reakcji" chemii.
    
- **Agregaty Sensorów:** Dla każdego etapu wyliczaj cechy (features):
    
    - `temp_avg`, `temp_max`, `temp_std_dev` (stabilność).
        
    - `press_integral` (całkowity wpływ ciśnienia).
        
- **Złoty Wzorzec (Golden Batch):** Oznacz w systemie szarże idealne, aby model miał punkt odniesienia do wykrywania anomalii.
    

---

## 4. Checklist dla Deva (Technologie i Funkcje)

- [ ] **Baza Danych:** Wykorzystaj PostgreSQL z rozszerzeniem TimescaleDB (idealne do łączenia logów laboratoryjnych z danymi z czujników).
    
- [ ] **Synchronizacja Czasu:** Upewnij się, że serwer aplikacji i sterowniki PLC mają ten sam czas (UTC).
    
- [ ] **Audit Trail:** Każda zmiana wyniku przez laboranta musi tworzyć log (stara wartość -> nowa wartość). To podstawa w przemyśle chemicznym.
    
- [ ] **Eksport do ML:** Stwórz widok SQL (View), który spłaszcza dane do formatu: `Batch_ID | Temp_Avg | Press_Max | pH_Final | AA_Final | Quality_Label`
    
- [ ] **Obsługa błędów:** System powinien blokować „przepompowanie na zbiornik”, jeśli parametry końcowe nie mieszczą się w specyfikacji (OOS - Out of Specification).