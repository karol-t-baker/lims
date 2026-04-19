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

# Clean any dirty tracked files + stale __pycache__
git checkout -- .
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Backup database before deploy
mkdir -p data/backups
cp data/batch_db.sqlite "data/backups/pre-deploy-$(date +%Y%m%d-%H%M%S).sqlite"
# Disk cleanup: old backups, __pycache__, stale WAL
/opt/lims/venv/bin/python -m scripts.cleanup_disk 2>/dev/null || true

git pull origin main --quiet

# Install any new dependencies
/opt/lims/venv/bin/pip install -r requirements.txt --quiet 2>/dev/null || true

# Run pending migrations BEFORE restart (scripts must be idempotent — re-running is a no-op)
/opt/lims/venv/bin/python scripts/migrate_audit_log_v2.py --db data/batch_db.sqlite

# One-shot data backfills (idempotent — guarded by 'WHERE entity_label IS NULL'
# inside the script, so subsequent cron runs are no-op).
/opt/lims/venv/bin/python scripts/backfill_audit_legacy_to_ebr.py --db data/batch_db.sqlite
/opt/lims/venv/bin/python scripts/migrate_uwagi_to_audit.py --db data/batch_db.sqlite
/opt/lims/venv/bin/python scripts/backfill_cert_name_en.py --db data/batch_db.sqlite
/opt/lims/venv/bin/python scripts/migrate_cert_to_etapy.py

# Rebuild Gotenberg image if Dockerfile or bundled fonts changed.
# Dockerfile.gotenberg COPIES fonts from deploy/fonts/ into the image;
# changes there aren't picked up by systemctl restart alone.
if git diff --name-only HEAD@{1} HEAD 2>/dev/null | grep -qE '^deploy/(Dockerfile\.gotenberg|fonts/)'; then
    echo "$(date): Gotenberg assets changed — rebuilding image"
    docker build -t gotenberg-lims:latest -f deploy/Dockerfile.gotenberg deploy/ && \
        sudo systemctl restart gotenberg
fi

# Restart app
sudo systemctl restart lims

echo "$(date): Deploy complete ($(git log --oneline -1))"
