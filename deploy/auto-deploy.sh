#!/bin/bash
# Auto-deploy: pull from GitHub, restart if changed
set -e

cd /opt/lims

# Fetch latest
git fetch origin main --quiet

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0
fi

echo "$(date): New commits detected, deploying..."

# Backup database before deploy
mkdir -p data/backups
cp data/batch_db.sqlite "data/backups/pre-deploy-$(date +%Y%m%d-%H%M%S).sqlite"
# Keep only 10 newest backups
ls -t data/backups/pre-deploy-*.sqlite 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null

git pull origin main --quiet

# Install any new dependencies
/opt/lims/venv/bin/pip install -r requirements.txt --quiet 2>/dev/null || true

# Run pending migrations BEFORE restart (scripts must be idempotent — re-running is a no-op)
/opt/lims/venv/bin/python scripts/migrate_audit_log_v2.py --db data/batch_db.sqlite

# One-shot data backfills (idempotent — guarded by 'WHERE entity_label IS NULL'
# inside the script, so subsequent cron runs are no-op).
/opt/lims/venv/bin/python scripts/backfill_audit_legacy_to_ebr.py --db data/batch_db.sqlite

# Restart app
sudo systemctl restart lims

echo "$(date): Deploy complete ($(git log --oneline -1))"
