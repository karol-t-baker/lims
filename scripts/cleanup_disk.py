"""
Disk cleanup: remove old backups, __pycache__, stale WAL files.
Keeps last 3 pre-deploy backups. Designed to run as cron.

Run: python -m scripts.cleanup_disk
"""
import os
import sys
import glob
import shutil

BASE = os.path.join(os.path.dirname(__file__), "..")
DATA = os.path.join(BASE, "data")
BACKUP_DIR = os.path.join(DATA, "backups")
KEEP_BACKUPS = 3


def cleanup():
    freed = 0

    # 1. Old pre-deploy backups (keep newest KEEP_BACKUPS)
    pattern = os.path.join(BACKUP_DIR, "pre-deploy-*.sqlite")
    backups = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    for old in backups[KEEP_BACKUPS:]:
        size = os.path.getsize(old)
        os.remove(old)
        freed += size
        print(f"  Removed backup: {os.path.basename(old)} ({size // 1024}K)")

    # 2. Legacy .bak files in data/
    for bak in glob.glob(os.path.join(DATA, "*.bak*")):
        size = os.path.getsize(bak)
        os.remove(bak)
        freed += size
        print(f"  Removed legacy bak: {os.path.basename(bak)} ({size // 1024}K)")

    # 3. __pycache__ directories
    for root, dirs, _ in os.walk(BASE):
        if "venv" in root or ".git" in root:
            continue
        for d in dirs:
            if d == "__pycache__":
                path = os.path.join(root, d)
                size = sum(
                    os.path.getsize(os.path.join(dp, f))
                    for dp, _, fns in os.walk(path) for f in fns
                )
                shutil.rmtree(path, ignore_errors=True)
                freed += size

    # 4. Stale .sqlite-shm/.sqlite-wal with 0 bytes
    for ext in ("-shm", "-wal"):
        for f in glob.glob(os.path.join(DATA, f"*{ext}")):
            if os.path.getsize(f) == 0:
                os.remove(f)
                print(f"  Removed empty WAL: {os.path.basename(f)}")

    mb = freed / (1024 * 1024)
    print(f"Cleanup done. Freed {mb:.1f} MB.")
    return freed


if __name__ == "__main__":
    cleanup()
