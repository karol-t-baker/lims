# TODO: ML Export — Opcja B (parquet + wersjonowanie)

**Date:** 2026-04-20
**Prerequisite:** PR1 — Long format CSV (`docs/superpowers/specs/2026-04-20-ml-export-long-format-design.md`)
**Trigger:** pierwszy wytrenowany model produkcyjny trafia do wdrożenia **albo** paczka CSV przekroczy ~5 MB **albo** pojawi się potrzeba porównywania eksportów w czasie (DVC/MLflow).

---

## Zakres

Rozszerzyć eksport ML o:

### 1. Parquet obok CSV
- Te same cztery tabele (`batches`, `sessions`, `measurements`, `corrections`) zapisane jako parquet (pyarrow).
- Zachowuje typy (float vs int vs string — CSV gubi to).
- ~5–10× mniejsze, szybsze do załadowania w pandas/polars.
- Format zipa: obok `*.csv` dorzucamy `*.parquet`. Klient wybiera co woli. (Albo dwie osobne paczki `_csv.zip` i `_parquet.zip`.)

### 2. Wersjonowanie schematu
- W `schema.json` dodaj pole `schema_version` (semver, np. `"1.0.0"`).
- Increment:
  - **patch** — dodanie wolnej kolumny w CSV (backward compat).
  - **minor** — nowa tabela, nowa kategoria parametrów.
  - **major** — breaking change (usunięcie kolumny, zmiana semantyki).
- Nazwa zipa: `k7_ml_v{YYYY-MM-DD}_s{schema_version}.zip` — data scientist wie na pierwszy rzut oka czy stary model dalej pasuje.

### 3. Rejestr eksportów w DB
- Nowa tabela `ml_exports`:
  ```sql
  CREATE TABLE ml_exports (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      dt_export TEXT NOT NULL,
      produkty_json TEXT NOT NULL,      -- lista produktów
      schema_version TEXT NOT NULL,
      batch_count INTEGER,
      file_hash TEXT,                    -- sha256 zipa
      pobrany_przez TEXT,                -- mbr_users.login
      filename TEXT
  );
  ```
- Wpisywany przy każdym `GET /api/export/ml/*`.
- Endpoint `GET /api/export/ml/history` — tabela historii eksportów (tylko admin).
- Wartość: audytowalność (kiedy powstała paczka, która posłużyła do trenowania modelu X).

### 4. Integracja z DVC / MLflow
- Nie kod — **dokumentacja** w `docs/ml/`:
  - `data-versioning.md` — jak śledzić paczki w DVC (`dvc add k7_ml_v*.zip`).
  - `training-loop.md` — jak ładować paczkę do MLflow run jako artifact.
- Opcjonalnie: przycisk „Oznacz tę paczkę jako treningową dla modelu X" z zapisem w `ml_exports.notes`.

### 5. Hash-based dedup
- Jeśli zawartość eksportu jest identyczna z poprzednim (sprawdzony po hashu), endpoint zwraca 304 + link do istniejącego pliku.
- Wymaga cache'u na dysku (`data/ml_exports/`) lub blob storage.

---

## Czego nie rozważać teraz

- Streamowanie (endpoint zwraca cały zip w pamięci — do ~50 MB OK).
- Inkrementalny parquet append (klasyczne wzorce: partycjonowanie po miesiącu / produkcie).
- Osobny worker do generowania paczki — wystarczy synchroniczny endpoint, generowanie 100 szarż powinno zajmować < 5 s.

---

## Dlaczego nie teraz (rationale)

- Do pierwszego modelu (`barwa_I2` na K7) wystarczy long CSV + pandas. Parquet robi różnicę dopiero przy > 1000 szarż lub > 10 MB.
- Decyzje o wersjonowaniu (co jest breaking?) najlepiej robić patrząc na **faktyczne** zmiany, nie hipotetyczne. PR1 daje nam runtime, który można obserwować.
- Rejestr eksportów ma sens, gdy w ogóle jest coś do audytowania (więcej niż 2–3 pobrania dziennie). Na teraz over-engineering.
- Dokumentacja DVC/MLflow zakłada, że pipeline trenujący istnieje. Napisana wcześniej jest wróżeniem z fusów.

---

## Szacunek kosztu

- Parquet dump: ~80 linii kodu, 2 h.
- Wersjonowanie: 30 linii + pole w schema.json, 1 h.
- Rejestr w DB: migracja + endpoint + UI historii — ~200 linii, 4–6 h.
- Dokumentacja DVC/MLflow: 2 h.

Łącznie ≈ 1 dzień pracy. Ale tylko gdy jest ku temu powód (patrz trigger na górze).
