# Admin Cancel Completed Batch — Design Spec

## Goal

Allow admin users to soft-delete (cancel) completed batches from the registry view. Cancelled batches remain in the database but are hidden from all views and sync.

## Architecture

- Soft delete: sets `ebr_batches.status = 'cancelled'`
- Existing queries already filter by `status='completed'`, so cancelled batches automatically disappear from registry, sync, and COA
- Two-stage confirmation UI: first a simple "are you sure?" modal, then a critical warning modal requiring the user to type the batch number to confirm

## Backend

### New endpoint

`POST /api/registry/<ebr_id>/cancel`

- **Auth:** `@role_required("admin")`
- **Logic:**
  1. Verify batch exists and `status='completed'`
  2. Set `status = 'cancelled'`
  3. Bump `sync_seq` to MAX+1 (so COA knows to remove it on next sync — COA should handle missing batches gracefully)
  4. Return `{"ok": true, "ebr_id": ..., "batch_id": ...}`
- **Errors:**
  - 404 if batch not found
  - 400 if batch is not completed (can't cancel open or already cancelled)
- **File:** `mbr/registry/routes.py`

### No model changes needed

- `ebr_batches.status` already supports `'cancelled'` via CHECK constraint
- No new columns or tables required

## Frontend

### Delete button in registry

- Visible only when `session.user.rola == 'admin'`
- Small red trash icon button at the end of each batch row in registry
- **File:** `mbr/templates/laborant/szarze_list.html` (registry section)

### Two-stage confirmation modals

**Modal 1 — Simple confirmation:**
- Title: "Usunięcie szarży"
- Body: "Czy na pewno chcesz usunąć szarżę **{nr_partii}** ({produkt})?"
- Buttons: "Anuluj" (gray), "Tak, usuń" (red)

**Modal 2 — Critical warning (shown after clicking "Tak, usuń"):**
- Red warning styling (designed with frontend-design skill)
- Title: "UWAGA — Operacja nieodwracalna"
- Body: Warning text explaining consequences
- Input field: "Wpisz numer szarży ({nr_partii}) aby potwierdzić"
- Button: "Usuń na stałe" — disabled until input matches nr_partii exactly
- Buttons: "Wróć" (gray), "Usuń na stałe" (red, disabled until match)

### After successful deletion

- Remove the batch row from the DOM (no full page reload)
- Show brief success toast/notification

## Sync implications

- Cancelled batches won't appear in `/api/completed` responses (filters `status='completed'`)
- COA app already handles missing batches gracefully (INSERT OR REPLACE, no deletion on COA side)
- If COA already has the batch, it stays in COA DB but won't get updates — acceptable for soft delete

## Testing

- Unit test: `POST /api/registry/<id>/cancel` sets status to cancelled
- Unit test: cancelled batch disappears from `list_completed_registry()` results
- Unit test: non-admin gets 403
- Unit test: cancelling non-completed batch returns 400
