## Secrets setup (first-time deploy)

Create `/etc/lims.env` on the host:

```bash
sudo install -m 600 -o root -g lims /dev/null /etc/lims.env
sudo tee /etc/lims.env >/dev/null <<EOF
MBR_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
MBR_SYNC_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(16))")
EOF
sudo systemctl daemon-reload
sudo systemctl restart lims
```

Point the COA client at the same `MBR_SYNC_TOKEN` value (set as env var on the COA host).
