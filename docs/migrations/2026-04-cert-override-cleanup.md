# Cert Override Cleanup Migration

**Data:** 2026-04-28
**Spec:** `docs/superpowers/specs/2026-04-28-cert-editor-redesign-design.md` (sekcja 6)
**Skrypt:** `scripts/migrate_cert_override_cleanup.py`
**Testy:** `tests/test_migrate_cert_override_cleanup.py` (12 testów, wszystkie zielone)

## Update 2026-04-28 (Parametry Rejestr Redesign)

Skrypt rozszerzony o **czwarte pole** — `parametry_cert.format` (precyzja cyfrowa cert względem `parametry_analityczne.precision`). Logika porównania: konwersja `format` (string TEXT) na int + `precision` (INTEGER, NULL → default 2 per legacy `COALESCE(pe.precision, pa.precision, 2)` w `get_parametry_for_kontekst`); jeśli numerycznie równe → `SET format = NULL`. Malformed format strings (np. nie-numeryczne) → skip (preserved).

## Co robi

Po przebudowie edytora świadectw `parametry_cert.name_pl/name_en/method/format` są **wyłącznie nadpisaniami per produkt**. NULL = dziedzicz z rejestru (`parametry_analityczne.label/name_en/method_code/precision`). Historyczne dane mają wiele wierszy, gdzie te kolumny zawierają wartości skopiowane verbatim z rejestru przy tworzeniu wiersza — to są pseudo-nadpisania, które **blokują** propagację zmian rejestru.

Skrypt iteruje po wszystkich wierszach `parametry_cert` (bazowych i wariantowych), JOIN-uje z rejestrem po `parametr_id`, i:
- Dla `name_pl`/`name_en`/`method`: jeśli wartość override **po normalizacji whitespace** (strip + collapse wielokrotnych spacji do jednej) jest równa wartości globalnej → ustawia kolumnę na `NULL`. Porównanie **case-sensitive** (case ma znaczenie w domenie: skróty PN-EN, jednostki SI).
- Dla `format`: konwersja string→int, porównanie numeryczne z `precision` (NULL precision → traktuj jako 2). Jeśli równe → NULL. Malformed strings → skip.

**Idempotentny.** Bezpieczne wielokrotne uruchomienie. Po pierwszym pełnym przebiegu kolejne nullify-ją 0 wierszy.

## Pre-flight

1. Backup bazy:
   ```bash
   cp data/batch_db.sqlite data/batch_db.sqlite.bak.$(date +%Y%m%d-%H%M)
   ```

2. Dry-run:
   ```bash
   python -m scripts.migrate_cert_override_cleanup --dry-run
   ```

   Output pokaże ile wierszy zostałoby zmienionych + przykłady **zachowanych** override-ów (do oka admina — czy to faktycznie celowe customizacje per produkt).

   Przykład output (po D1 — z czwartym polem `format`):
   ```
   Rows processed:           319
   Override fields nulled:   673
     - name_pl:  44
     - name_en:  234
     - method:   256
     - format:   139
   Real overrides preserved: 418

   Sample preserved overrides (first 50):
     Chegina_CC/h2o/name_pl:
       override:  'H2O [%]'
       registry:  'Zawartość wody'
     Alstermid_K/lk/format:
       override:  '1'
       registry:  '2'
     ...
   ```

## Wykonanie

```bash
python -m scripts.migrate_cert_override_cleanup
```

Bez flag — wykonuje rzeczywiste UPDATE-y i COMMIT.

## Weryfikacja po migracji

1. Otwórz `/admin/wzory-cert`, wybierz dowolny produkt
2. Klik „Parametry świadectwa"
3. Sprawdź że pola w prawej kolumnie (override) są **puste** dla większości parametrów — wartości dziedziczone z lewej kolumny (rejestr)
4. Wygeneruj testowy świadectwo z dowolnej szarży — PDF powinien wyglądać **identycznie** jak przed migracją (efektywne wartości się nie zmieniają)
5. Edytuj `parametry_analityczne.label` przez `/admin/parametry` (np. zmień nazwę parametru):
   - Wygeneruj świadectwo dla produktu, który **nie miał** override-u tego pola → nowa wartość propaguje się
   - Wygeneruj dla produktu, który **miał** rzeczywisty override → stara override-owana wartość zostaje
6. Sprawdź `/admin/audit` — events `parametr.updated` (jeśli były) odzwierciedlają zmiany rejestru

## Rollback

Jeśli coś się nie zgadza, wycofaj backup:

```bash
sudo systemctl stop lims  # produkcja
cp data/batch_db.sqlite.bak.<TIMESTAMP> data/batch_db.sqlite
sudo systemctl start lims
```

## Uwagi specjalne

### Empty-string overrides

Skrypt **nulluje** także override-y które są pustym stringiem `""` jeśli rejestr też jest pusty (`""` lub NULL). Przed redesignem editor czasami zapisywał `""` zamiast NULL przy „pustym" override — to są pseudo-overrides do wyczyszczenia. Test `test_migration_nulls_empty_string_when_registry_also_empty` pokrywa ten przypadek.

### Variants

Wariantowe wiersze (`parametry_cert.variant_id IS NOT NULL`) są przetwarzane identycznie. Żaden specjalny case — variant override zNULLowany gdy równy globalnemu z rejestru.

### Co ZOSTAJE

Override-y z prawdziwie różną wartością (po normalizacji whitespace) zostają nietknięte. Przykłady real-world z dry-run:
- `'H2O [%]'` (override) vs `'Zawartość wody'` (rejestr) → preserved
- `'Substancja aktywna [%]'` vs `'Substancja aktywna'` → preserved (różne, choć podobne)
- `'organoleptycznie\n/organoleptic'` (multi-line z manual `|` break) vs `'P801'` → preserved

## Produkcja — deploy

To **NIE jest** zadanie kodu — to operacja deploy-owa:

1. SSH na produkcję
2. `sudo systemctl stop lims`
3. Backup zgodnie z pre-flight
4. Dry-run, weryfikuj sample preserved
5. Wykonaj migrację
6. `sudo systemctl start lims`
7. Smoke test w przeglądarce (kroki weryfikacji powyżej)
8. (Opcjonalnie) Zarejestruj migrację w audit log:
   ```bash
   python -c "
   from mbr.db import db_session
   from mbr.shared.audit import log_event, EVENT_SYSTEM_MIGRATION_APPLIED, actors_system
   with db_session() as db:
       log_event(EVENT_SYSTEM_MIGRATION_APPLIED, payload={'name': 'cert_override_cleanup_2026_04_28'}, actors=actors_system(), db=db)
       db.commit()
   "
   ```
