# Admin Panel + Backup System — Design Spec

## Goal

Add an admin role with a dedicated panel for configuring backup path and performing manual backups of the LIMS database + data JSONs. A backup + git clone = fully restored system on a new machine in 15 minutes.

## Scope

Only the LIMS app (mbr/). OCR pipeline is a separate project and not included.

## What Gets Backed Up

1. **`data/batch_db.sqlite`** — the entire LIMS database (users, batches, results, parameters, audit log, certificates metadata, settings)
2. **`data/swiadectwa/`** — certificate generation JSON data (needed to regenerate PDFs)

These two items + the git repo = complete system restore.

## Architecture

### New role: `admin`

- Add `'admin'` to the CHECK constraint in `mbr_users.rola`
- Admin sees its own rail section with one item: "Admin"
- Admin also sees Parametry and Ustawienia (shared items)

### New blueprint: `mbr/admin/`

- `__init__.py` — blueprint definition
- `routes.py` — admin page + backup API
- All routes use `@role_required("admin")`

### Admin page (`/admin`)

Single page with two sections:

**Section 1: Backup Path**
- Input field showing current backup directory path
- Save button → stores in `user_settings` as global key `backup_dir` (login=`_system_`)
- Default if not set: `data/backups/` (relative to project root)

**Section 2: Backup**  
- "Wykonaj backup" button
- On click: copies DB + swiadectwa JSONs to `{backup_dir}/lims_backup_YYYY-MM-DD_HH-MM/`
  - `batch_db.sqlite` (copied after VACUUM INTO for consistency)
  - `swiadectwa/` (recursive copy of JSON files only, no PDFs)
- Below button: list of existing backups in the backup dir (folder name, size, date)
- Optional: delete old backups

### Backup folder structure

```
{backup_dir}/
  lims_backup_2026-04-06_14-30/
    batch_db.sqlite
    swiadectwa/
      2026/
        Chegina K7/
          Chegina K7 MB 4.json
          ...
  lims_backup_2026-04-05_09-15/
    ...
```

### Restore procedure (manual, documented)

1. `git clone` repo on new machine
2. Copy latest backup's `batch_db.sqlite` → `data/batch_db.sqlite`
3. Copy latest backup's `swiadectwa/` → `data/swiadectwa/`
4. `pip install -r requirements.txt && python run.py`
5. Done — all data restored, PDFs can be regenerated from JSON data

## Files to Create

- `mbr/admin/__init__.py` — blueprint
- `mbr/admin/routes.py` — admin page + backup API
- `mbr/templates/admin/panel.html` — admin page template

## Files to Modify

- `mbr/models.py` — add 'admin' to rola CHECK constraint
- `mbr/app.py` — register admin blueprint
- `mbr/templates/base.html` — add admin rail section

## Not in Scope

- Scheduled/automatic backups (manual button only for MVP)
- Backup compression (folders are small enough)
- OCR data backup
- Remote backup (local path only)
