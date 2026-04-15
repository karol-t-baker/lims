"""cert_watchdog.py — Monitors Downloads for certificate PDFs and moves them to organized folders.

Usage: python cert_watchdog.py
"""

import json
import shutil
import time
import sys
from datetime import datetime
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

PRODUCTS = []  # loaded from config


def match_product(filename: str) -> str | None:
    stem = Path(filename).stem
    for p in PRODUCTS:
        if stem.startswith(p):
            return p
    return None


def move_certificate(filepath: Path, dest_dir: Path):
    # Wait for browser to finish writing
    time.sleep(2)

    if not filepath.exists() or filepath.suffix.lower() != ".pdf":
        return

    product = match_product(filepath.name)
    if not product:
        return

    # Rename: "Chegina K7 4.pdf" → "Świadectwo_certificate-Chegina K7 4.pdf"
    new_name = f"Świadectwo_certificate-{filepath.name}"

    year = str(datetime.now().year)
    target_dir = dest_dir / year / product
    target_path = target_dir / new_name

    target_dir.mkdir(parents=True, exist_ok=True)

    # Archive existing file if it would be overwritten
    if target_path.exists():
        archive_dir = target_dir / "_archiwum"
        archive_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H-%M")
        new_stem = Path(new_name).stem
        archive_path = archive_dir / f"{new_stem} ({ts}).pdf"
        shutil.move(str(target_path), str(archive_path))

    shutil.move(str(filepath), str(target_path))
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {filepath.name} -> {year}/{product}/{new_name}")


class CertHandler(FileSystemEventHandler):
    def __init__(self, dest_dir: Path):
        self.dest_dir = dest_dir

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() == ".pdf":
            move_certificate(path, self.dest_dir)


def main():
    config_path = Path(__file__).parent / "cert-watchdog.json"
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        sys.exit(1)

    config = json.loads(config_path.read_text())
    watch_dir = Path(config["watch_dir"])
    dest_dir = Path(config["dest_dir"])

    # Load products sorted longest-first
    global PRODUCTS
    PRODUCTS = sorted(config.get("products", []), key=len, reverse=True)

    if not watch_dir.exists():
        print(f"Watch directory not found: {watch_dir}")
        sys.exit(1)

    handler = CertHandler(dest_dir)
    observer = Observer()
    observer.schedule(handler, str(watch_dir), recursive=False)
    observer.start()

    print("Cert Watchdog started")
    print(f"  Watch: {watch_dir}")
    print(f"  Dest:  {dest_dir}")
    print(f"  Products: {len(PRODUCTS)}")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
