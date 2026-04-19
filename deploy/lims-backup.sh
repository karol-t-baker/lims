#!/bin/bash
# Daily SQLite backup. Invoked by lims-backup.service.
set -euo pipefail

SRC="/opt/lims/data/batch_db.sqlite"
DEST_DIR="/opt/lims/data/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$DEST_DIR/daily-$STAMP.sqlite"
RETAIN_DAYS=14

mkdir -p "$DEST_DIR"

if [ ! -s "$SRC" ]; then
    echo "$(date): source DB missing or empty — $SRC" >&2
    exit 1
fi

sqlite3 "$SRC" ".backup '$DEST'"

if [ ! -s "$DEST" ]; then
    echo "$(date): backup wrote zero bytes — $DEST" >&2
    exit 1
fi

# Prune daily backups older than RETAIN_DAYS (does not touch pre-deploy-*.sqlite)
find "$DEST_DIR" -maxdepth 1 -name "daily-*.sqlite" -mtime +$RETAIN_DAYS -delete

echo "$(date): backup ok — $DEST"
