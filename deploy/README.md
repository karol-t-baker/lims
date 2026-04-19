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

## Daily backup timer

Install once:

```bash
sudo cp /opt/lims/deploy/lims-backup.service /etc/systemd/system/
sudo cp /opt/lims/deploy/lims-backup.timer   /etc/systemd/system/
sudo chmod +x /opt/lims/deploy/lims-backup.sh
sudo systemctl daemon-reload
sudo systemctl enable --now lims-backup.timer
```

Verify:

```bash
systemctl list-timers | grep lims-backup
# Trigger a test run:
sudo systemctl start lims-backup.service
journalctl -u lims-backup.service -n 20
ls -lh /opt/lims/data/backups/daily-*.sqlite | tail -3
```

Retains the last 14 daily backups; pre-deploy snapshots are not pruned by this job.
