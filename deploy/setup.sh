#!/bin/bash
# =============================================================================
# LIMS Setup Script for HP T630 (Ubuntu)
# Run as root: sudo bash deploy/setup.sh
# =============================================================================
set -e

REPO_URL="https://github.com/karol-t-baker/lims.git"
LIMS_DIR="/opt/lims"
LIMS_USER="lims"

echo "=== LIMS Setup for HP T630 ==="

# --- 1. System packages ---
echo "[1/8] Installing system packages..."
apt-get update -qq
apt-get install -y -qq nginx python3 python3-venv python3-pip git docker.io chromium-browser openssl

# --- 2. Docker ---
echo "[2/8] Enabling Docker..."
systemctl enable docker
systemctl start docker
docker pull gotenberg/gotenberg:8

# --- 3. User ---
echo "[3/8] Creating lims user..."
id -u $LIMS_USER &>/dev/null || useradd -r -m -s /bin/bash $LIMS_USER
# Allow lims to restart its own service
echo "lims ALL=(ALL) NOPASSWD: /bin/systemctl restart lims" > /etc/sudoers.d/lims

# --- 4. Clone repo ---
echo "[4/8] Cloning repository..."
if [ -d "$LIMS_DIR" ]; then
    echo "  $LIMS_DIR already exists, pulling..."
    cd "$LIMS_DIR"
    git pull origin main
else
    git clone "$REPO_URL" "$LIMS_DIR"
fi
chown -R $LIMS_USER:$LIMS_USER "$LIMS_DIR"

# --- 5. Python venv ---
echo "[5/8] Setting up Python environment..."
sudo -u $LIMS_USER python3 -m venv "$LIMS_DIR/venv"
sudo -u $LIMS_USER "$LIMS_DIR/venv/bin/pip" install --quiet flask gunicorn bcrypt docxtpl pymupdf

# --- 6. SSL certificates ---
echo "[6/8] Generating SSL certificates..."
bash "$LIMS_DIR/deploy/generate-certs.sh"

# --- 7. Nginx ---
echo "[7/8] Configuring nginx..."
cp "$LIMS_DIR/deploy/nginx-lims.conf" /etc/nginx/sites-available/lims
ln -sf /etc/nginx/sites-available/lims /etc/nginx/sites-enabled/lims
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

# --- 8. Services ---
echo "[8/8] Installing systemd services..."
cp "$LIMS_DIR/deploy/lims.service" /etc/systemd/system/
cp "$LIMS_DIR/deploy/gotenberg.service" /etc/systemd/system/
cp "$LIMS_DIR/deploy/kiosk.service" /etc/systemd/system/
cp "$LIMS_DIR/deploy/auto-deploy.service" /etc/systemd/system/
cp "$LIMS_DIR/deploy/auto-deploy.timer" /etc/systemd/system/
chmod +x "$LIMS_DIR/deploy/auto-deploy.sh"

systemctl daemon-reload
systemctl enable --now gotenberg
systemctl enable --now lims
systemctl enable --now auto-deploy.timer
systemctl enable kiosk

# --- DNS: add lims.local to hosts ---
grep -q "lims.local" /etc/hosts || echo "127.0.0.1 lims.local" >> /etc/hosts

# --- Init DB ---
echo "Initializing database..."
sudo -u $LIMS_USER "$LIMS_DIR/venv/bin/python" -c "from mbr.app import create_app; create_app()"

echo ""
echo "=== DONE ==="
echo ""
echo "  URL:         https://lims.local"
echo "  Kiosk:       Chromium starts on boot (reboot to test)"
echo "  Auto-deploy: git pull every 5 min from GitHub"
echo "  Gotenberg:   Docker on port 3000"
echo ""
echo "  NEXT STEPS:"
echo "  1. Edit REPO_URL in this script and re-run, or:"
echo "     cd /opt/lims && git remote set-url origin YOUR_GITHUB_URL"
echo "  2. Change MBR_SECRET_KEY in /etc/systemd/system/lims.service"
echo "  3. Restore backup: copy batch_db.sqlite + swiadectwa/ to /opt/lims/data/"
echo "  4. Reboot: sudo reboot"
echo ""
