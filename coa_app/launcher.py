"""
LabCore COA — PyInstaller entry point.

Resolves paths for frozen (PyInstaller) vs dev mode,
starts Flask server, opens browser in app mode.
"""

import os
import sys
import threading
import webbrowser
from pathlib import Path


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def _resolve_paths():
    """Set path env vars for app.py to pick up."""
    if _is_frozen():
        # _MEIPASS = _internal/ dir where PyInstaller unpacks
        bundle_dir = Path(sys._MEIPASS)
        # exe sits next to _internal/, data/ is next to exe
        exe_dir = Path(sys.executable).parent
    else:
        # Dev mode: launcher.py is in coa_app/
        bundle_dir = Path(__file__).parent.parent  # repo root
        exe_dir = Path(__file__).parent  # coa_app/

    data_dir = exe_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Export for app.py
    os.environ["LABCORE_BUNDLE_DIR"] = str(bundle_dir)
    os.environ["LABCORE_DATA_DIR"] = str(data_dir)
    os.environ["LABCORE_NO_BROWSER"] = "1"  # launcher handles browser

    # Add bundle dir to sys.path so `import mbr` works
    if str(bundle_dir) not in sys.path:
        sys.path.insert(0, str(bundle_dir))


def _open_browser():
    """Open browser in app mode after short delay."""
    import time
    time.sleep(2)

    url = "http://localhost:5050"
    # Try Chrome --app mode first, then Edge, then default
    import subprocess
    import shutil

    for browser in ["chrome", "msedge"]:
        exe = shutil.which(browser)
        if exe:
            try:
                subprocess.Popen([exe, f"--app={url}"])
                return
            except Exception:
                continue

    # Windows: check common Chrome/Edge paths
    if sys.platform == "win32":
        candidates = [
            Path(os.environ.get("PROGRAMFILES", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        ]
        for c in candidates:
            if c.exists():
                try:
                    subprocess.Popen([str(c), f"--app={url}"])
                    return
                except Exception:
                    continue

    # Fallback: default browser
    webbrowser.open(url)


def main():
    _resolve_paths()

    # Suppress urllib3 SSL warnings
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Import app AFTER paths are set
    from coa_app.app import app, DB_PATH
    from mbr.db import db_session
    from mbr.models import init_mbr_tables

    # Ensure DB exists
    if not DB_PATH.exists():
        with db_session() as db:
            init_mbr_tables(db)

    # Open browser in background thread
    threading.Thread(target=_open_browser, daemon=True).start()

    print("=" * 50)
    print("  LabCore COA — http://localhost:5050")
    print("=" * 50)

    app.run(host="127.0.0.1", port=5050, debug=False)


if __name__ == "__main__":
    main()
