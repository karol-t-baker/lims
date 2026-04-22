# Rename K7 Process Stages: "Analiza po [etap]"

Status: Draft for user review
Date: 2026-04-22
Scope: Display labels (`nazwa`) only. Internal `kod` identifiers unchanged.

## Motivation

The K7 batch pipeline has three analytical checkpoints:
`sulfonowanie`, `utlenienie`, `standaryzacja`. In the LIMS, each of these is
a LAB ANALYSIS BLOCK that the laborant performs at the end of the
corresponding chemical phase. But in lab jargon, the same words refer to
the chemical phases themselves:

- "Sulfonowanie" — the 1+ hour chemical reaction
- "Utlenianie" — the oxidation chemistry
- "Standaryzacja" — traditionally means reagent standardization BEFORE a
  reaction, so operators expect it at the start, not at the end

In the LIMS these labels sit on the SCREEN the laborant opens to enter the
analytical results AFTER the chemical reaction. The naming mismatch causes
confusion: operators think "Sulfonowanie" is the whole reaction when it's
actually the post-reaction QC step. The third stage is the worst offender
because the label ("Standaryzacja") fights the process position (end of
batch, not beginning).

## Goal

Clarify that each stage on the laborant screen is an ANALYSIS AT THE END
of the chemical phase. Rename the user-facing display labels to "Analiza
po [etap]":

| Obecna `nazwa` | Nowa `nazwa` | `kod` (bez zmian) |
|---|---|---|
| Sulfonowanie | Analiza po sulfonowaniu | `sulfonowanie` |
| Utlenienie  | Analiza po utlenianiu   | `utlenienie` |
| Standaryzacja | Analiza po standaryzacji | `standaryzacja` |

`analiza_koncowa` (stage 4) is unchanged — already clearly named.

## Non-goals

- No rename of `kod` identifiers. The ~39 Python/SQL/JS references to
  `'standaryzacja'` as a string stay unchanged.
- No DB migration beyond a single-row UPDATE per stage.
- Other stage names (`amidowanie`, `namca`, `czwartorzedowanie`,
  `rozjasnianie`, `analiza_koncowa`) stay. They don't cause the reported
  confusion.

## Changes

### 1. Database

```sql
UPDATE etapy_analityczne SET nazwa = 'Analiza po sulfonowaniu'  WHERE kod = 'sulfonowanie';
UPDATE etapy_analityczne SET nazwa = 'Analiza po utlenianiu'    WHERE kod = 'utlenienie';
UPDATE etapy_analityczne SET nazwa = 'Analiza po standaryzacji' WHERE kod = 'standaryzacja';
```

Applied on both local dev DB and production DB. No table alteration, no FK
implications (rows keyed by id; kod unchanged).

### 2. `mbr/models.py` — default seeds for `init_mbr_tables`

Lines 365-367 currently list `("sulfonowanie", "Sulfonowanie")`,
`("utlenienie", "Utlenienie")`, `("standaryzacja", "Standaryzacja")` as
`(kod, nazwa)` tuples used on fresh DB init. Change the second element of
each tuple to the new label so new installations start with clear names.

### 3. `mbr/seed_mbr.py` — batch card sections

Lines 23-25 and 35-38 define strona-1 batch-card section labels. Two
blocks (one per K-series variant) reference the three stages with their
old names. Change `"nazwa": "Sulfonowanie"` → `"nazwa": "Analiza po
sulfonowaniu"` etc. The `sekcja_lab` key remains unchanged.

### 4. `mbr/etapy/config.py` — process-stage config

`ETAPY_ANALIZY` dict has three product blocks (`Chegina_K7`,
`Chegina_K40GLOL`, `Chegina_K40GLO`) with `"label"` fields that surface in
some specific UI. Update the labels for `sulfonowanie` and `utlenienie`
in each of the three product blocks. (This file doesn't reference
`standaryzacja` — that stage is defined only via the `etapy_analityczne`
table and `produkt_pipeline`.)

## Rollout

- All changes are forward-only label updates; zero risk of breaking
  existing data, sessions, or batch flow.
- Batches currently in progress continue normally; the next hero render
  shows the new stage labels.
- Historical audit events and exported CSVs that embed the old labels
  stay untouched (they are snapshots of the old text at the time of
  emission).

## Testing

- Unit test: seed an in-memory DB via `init_mbr_tables`, assert
  `etapy_analityczne` rows for the three stages have the new `nazwa`.
- Manual smoke: open a K7 batch hero; stage headers now read "Analiza po
  sulfonowaniu" etc.
- Manual smoke: fresh batch card (strona 1) section labels match.

## Risks

- Any production Excel/PDF report that hard-codes the old stage names
  becomes inconsistent with the LIMS. The current cert template renders
  `analiza_koncowa` block only, so certificates are unaffected.
- Operators already comfortable with old names need a short transition,
  but the new names are strictly more descriptive (add information, don't
  replace meaning).

## Scope for a single implementation plan

Four targeted edits, one-off SQL update, one regression test. Fits a
single short plan (~4–5 tasks) or inline execution.
