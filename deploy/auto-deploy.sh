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

git pull origin main --quiet

# Install any new dependencies
/opt/lims/venv/bin/pip install -r requirements.txt --quiet 2>/dev/null || true

# Restart app
sudo systemctl restart lims

echo "$(date): Deploy complete ($(git log --oneline -1))"
