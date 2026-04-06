#!/bin/bash
# Generate self-signed SSL certificates for lims.local
# Run once on the T630

DOMAIN="lims.local"
CERT_DIR="/etc/ssl/lims"

sudo mkdir -p "$CERT_DIR"

sudo openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout "$CERT_DIR/lims.key" \
  -out "$CERT_DIR/lims.crt" \
  -subj "/CN=$DOMAIN" \
  -addext "subjectAltName=DNS:$DOMAIN,DNS:localhost,IP:127.0.0.1"

sudo chmod 600 "$CERT_DIR/lims.key"
sudo chmod 644 "$CERT_DIR/lims.crt"

echo "Certificates generated in $CERT_DIR"
echo "  lims.crt (10 years validity)"
echo "  lims.key"
