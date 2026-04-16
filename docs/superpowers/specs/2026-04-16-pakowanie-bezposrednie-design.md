# Pakowanie bezpośrednie (IBC / Beczki) — Design Spec

## Goal

Allow batches to skip the zbiornik (tank) step and go directly to IBC or barrels. Two entry points: at batch creation (planned) and at pump stage (emergency/change of plan).

## DB Change

New column on `ebr_batches`:

```sql
ALTER TABLE ebr_batches ADD COLUMN pakowanie_bezposrednie TEXT;
```

Values: `NULL` (normal flow → zbiornik), `"IBC"`, `"Beczki"`.

## Ścieżka A: At batch creation

In `_modal_nowa_szarza.html`, Step 2a (szarza form):
- New checkbox: "Pakowanie bezpośrednie (bez zbiornika)"
- When checked: show select (IBC / Beczki) + textarea for uwagi
- Zbiorniki docelowe section hides when checked
- POST includes `pakowanie_bezposrednie` field
- `uwagi_koncowe` gets the note text

## Ścieżka B: At pump stage

In `openPumpModal` / pump modal:
- New button "Na IBC / beczki" alongside tank selection
- Clicking opens inline select (IBC / Beczki) + uwagi field
- `confirmPump()` sends `pakowanie_bezposrednie` instead of zbiorniki array
- Backend sets `pakowanie_bezposrednie` on `ebr_batches`, no `zbiornik_szarze` links

## Flow impact

- If `pakowanie_bezposrednie` is set, the "Przepompuj na zbiornik" button label changes to "Zakończ → IBC" or "Zakończ → Beczki"
- `completePompuj()` skips tank selection and goes to confirm with uwagi
- Analiza końcowa unchanged

## Display

- Completed view: badge "IBC" or "Beczki" where zbiornik number would normally appear (amber color to distinguish)
- ML export: new column `pakowanie` with values "zbiornik" / "IBC" / "Beczki"

## Scope

- Only `typ='szarza'` batches (not zbiornik or platkowanie)
- Two packaging options: IBC, Beczki
- Uwagi are free text, saved to `uwagi_koncowe`
