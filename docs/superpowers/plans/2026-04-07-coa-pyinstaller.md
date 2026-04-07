# COA PyInstaller Desktop App — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the COA Flask app (`coa_app/` + `mbr/`) as a portable Windows desktop app using PyInstaller `--onedir`.

**Architecture:** A `launcher.py` entry point resolves frozen vs dev paths, sets env vars, then imports and runs the existing `app.py`. PyInstaller bundles everything into `dist/LabCore_COA/` with a writable `data/` folder next to the exe. Old .bat installers are removed.

**Tech Stack:** Python 3.12, PyInstaller, Flask, docxtpl, bcrypt, num2words, LibreOffice (external)

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Create | `coa_app/launcher.py` | PyInstaller entry point — path resolution, browser launch |
| Modify | `coa_app/app.py:27-31` | Frozen-aware path config (APP_DIR, DATA_DIR, DB_PATH, MBR_DIR) |
| Modify | `coa_app/app.py:467-487` | Remove browser launch from `__main__` (moved to launcher) |
| Create | `coa_app/labcore_coa.spec` | PyInstaller spec with datas + hiddenimports |
| Create | `coa_app/build_windows.bat` | One-click build script |
| Delete | `coa_app/SETUP.bat` | Replaced by .exe |
| Delete | `coa_app/INSTALL.bat` | Replaced by .exe |
| Delete | `coa_app/START.bat` | Replaced by .exe |
| Delete | `coa_app/install_windows.bat` | Replaced by .exe |
| Delete | `coa_app/start_coa.bat` | Replaced by .exe |

---

### Task 1: Create `launcher.py` entry point

**Files:**
- Create: `coa_app/launcher.py`

This is the PyInstaller entry point. It resolves paths, sets env vars so `app.py` can find them, launches the Flask server, and opens the browser.

- [ ] **Step 1: Create `coa_app/launcher.py`**

```python
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
```

- [ ] **Step 2: Verify launcher works in dev mode**

Run from repo root:

```bash
cd /path/to/aa
python coa_app/launcher.py
```

Expected: Flask starts on port 5050, browser opens. Ctrl+C to stop.

- [ ] **Step 3: Commit**

```bash
git add coa_app/launcher.py
git commit -m "feat(coa): add PyInstaller launcher entry point"
```

---

### Task 2: Make `app.py` frozen-aware

**Files:**
- Modify: `coa_app/app.py:17-31` (path config section)
- Modify: `coa_app/app.py:467-487` (`__main__` block)

- [ ] **Step 1: Update path config in `app.py`**

Replace lines 17-31 (from `sys.path.insert` through `DEFAULT_BACKUP_DIR`) with:

```python
# ---------------------------------------------------------------------------
# Path resolution — supports PyInstaller frozen mode
# ---------------------------------------------------------------------------

_BUNDLE_DIR = os.environ.get("LABCORE_BUNDLE_DIR")
if _BUNDLE_DIR:
    # Launched via launcher.py (frozen or dev)
    sys.path.insert(0, _BUNDLE_DIR)
    APP_DIR = Path(_BUNDLE_DIR) / "coa_app" if not getattr(sys, "frozen", False) else Path(sys._MEIPASS)
else:
    # Direct python app.py (legacy dev mode)
    sys.path.insert(0, str(Path(__file__).parent.parent))
    APP_DIR = Path(__file__).parent

_DATA_DIR_ENV = os.environ.get("LABCORE_DATA_DIR")
DATA_DIR = Path(_DATA_DIR_ENV) if _DATA_DIR_ENV else APP_DIR / "data"
DB_PATH = DATA_DIR / "batch_db.sqlite"
MBR_DIR = Path(sys._MEIPASS) / "mbr" if getattr(sys, "frozen", False) else APP_DIR.parent / "mbr"

DEFAULT_SERVER = "http://labcore.local:5001"
DEFAULT_OUTPUT_DIR = str(Path.home() / "Desktop" / "Swiadectwa")
DEFAULT_BACKUP_DIR = str(Path.home() / "Desktop" / "Backupy_LIMS")
```

- [ ] **Step 2: Simplify `__main__` block**

Replace the `if __name__ == "__main__":` block (lines 467-487) with:

```python
if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    if not DB_PATH.exists():
        from mbr.models import init_mbr_tables
        with _mbr_db.db_session() as db:
            init_mbr_tables(db)

    print("=" * 50)
    print("  LabCore COA — http://localhost:5050")
    print("=" * 50)

    if os.environ.get("LABCORE_NO_BROWSER") != "1":
        import webbrowser
        webbrowser.open("http://localhost:5050")

    app.run(host="127.0.0.1", port=5050, debug=False)
```

- [ ] **Step 3: Verify both launch modes still work**

Test direct mode (no launcher):
```bash
python coa_app/app.py
```

Test via launcher:
```bash
python coa_app/launcher.py
```

Both should start Flask on port 5050.

- [ ] **Step 4: Commit**

```bash
git add coa_app/app.py
git commit -m "feat(coa): make app.py frozen-aware for PyInstaller"
```

---

### Task 3: Create PyInstaller spec file

**Files:**
- Create: `coa_app/labcore_coa.spec`

- [ ] **Step 1: Create `coa_app/labcore_coa.spec`**

```python
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for LabCore COA desktop app."""

import os
from pathlib import Path

block_cipher = None

# Paths relative to spec file location (coa_app/)
REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
MBR_DIR = os.path.join(REPO_ROOT, "mbr")

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=[
        # mbr package source (for imports)
        (MBR_DIR, "mbr"),
        # coa_app source (app.py needs to be importable)
        (os.path.join(SPECPATH, "app.py"), "coa_app"),
        # cert config
        (os.path.join(MBR_DIR, "cert_config.json"), "mbr"),
        # Templates (HTML + DOCX)
        (os.path.join(MBR_DIR, "templates"), "mbr/templates"),
        # Static assets (CSS, JS, images)
        (os.path.join(MBR_DIR, "static"), "mbr/static"),
    ],
    hiddenimports=[
        # mbr core
        "mbr", "mbr.app", "mbr.db", "mbr.models",
        # mbr blueprints
        "mbr.auth", "mbr.auth.routes", "mbr.auth.models",
        "mbr.certs", "mbr.certs.routes", "mbr.certs.generator",
        "mbr.certs.models", "mbr.certs.mappings",
        "mbr.workers", "mbr.workers.routes", "mbr.workers.models",
        "mbr.registry", "mbr.registry.routes", "mbr.registry.models",
        "mbr.etapy", "mbr.etapy.routes", "mbr.etapy.models", "mbr.etapy.config",
        "mbr.parametry", "mbr.parametry.routes", "mbr.parametry.registry", "mbr.parametry.seed",
        "mbr.technolog", "mbr.technolog.routes", "mbr.technolog.models",
        "mbr.laborant", "mbr.laborant.routes", "mbr.laborant.models",
        "mbr.admin", "mbr.admin.routes",
        "mbr.shared", "mbr.shared.filters", "mbr.shared.context", "mbr.shared.decorators",
        "mbr.paliwo", "mbr.paliwo.routes", "mbr.paliwo.models",
        # mbr root-level modules
        "mbr.etapy_models", "mbr.etapy_config", "mbr.parametry_registry",
        "mbr.seed_parametry", "mbr.seed_mbr",
        "mbr.pdf_gen", "mbr.cert_gen",
        # third-party
        "num2words", "bcrypt", "docxtpl",
        # coa_app
        "coa_app", "coa_app.app",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["gunicorn", "tkinter", "matplotlib", "numpy", "PIL"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LabCore_COA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(SPECPATH, "labcore.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="LabCore_COA",
)
```

- [ ] **Step 2: Commit**

```bash
git add coa_app/labcore_coa.spec
git commit -m "feat(coa): add PyInstaller spec file"
```

---

### Task 4: Create build script

**Files:**
- Create: `coa_app/build_windows.bat`

- [ ] **Step 1: Create `coa_app/build_windows.bat`**

```bat
@echo off
chcp 65001 >nul
title LabCore COA — Build
echo.
echo  ╔══════════════════════════════════════╗
echo  ║     LabCore COA — Build              ║
echo  ╚══════════════════════════════════════╝
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [X] Python nie znaleziony!
    pause
    exit /b 1
)
echo  [OK] Python znaleziony

:: Install PyInstaller if needed
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo  [..] Instalacja PyInstaller...
    pip install pyinstaller --quiet
)
echo  [OK] PyInstaller dostepny

:: Install app dependencies
echo  [..] Instalacja zaleznosci...
pip install flask docxtpl requests bcrypt num2words --quiet
echo  [OK] Zaleznosci zainstalowane

:: Build
echo.
echo  [..] Budowanie aplikacji...
cd /d "%~dp0"
pyinstaller labcore_coa.spec --noconfirm
if %errorlevel% neq 0 (
    echo  [X] Build nie powiodl sie!
    pause
    exit /b 1
)

:: Create data directory in output
mkdir dist\LabCore_COA\data 2>nul

:: Copy icon next to exe
copy labcore.ico dist\LabCore_COA\ >nul 2>&1

echo.
echo  ╔══════════════════════════════════════╗
echo  ║     Build ukonczony!                 ║
echo  ╠══════════════════════════════════════╣
echo  ║                                      ║
echo  ║  Wynik: coa_app\dist\LabCore_COA\    ║
echo  ║  Uruchom: LabCore_COA.exe            ║
echo  ║                                      ║
echo  ╚══════════════════════════════════════╝
echo.
pause
```

- [ ] **Step 2: Commit**

```bash
git add coa_app/build_windows.bat
git commit -m "feat(coa): add Windows build script for PyInstaller"
```

---

### Task 5: Add `coa_app/__init__.py`

**Files:**
- Create: `coa_app/__init__.py`

PyInstaller needs `coa_app` to be a proper package for `from coa_app.app import app` to work in the launcher.

- [ ] **Step 1: Create `coa_app/__init__.py`**

```python
```

(Empty file — just makes coa_app a package.)

- [ ] **Step 2: Commit**

```bash
git add coa_app/__init__.py
git commit -m "feat(coa): add __init__.py for PyInstaller package import"
```

---

### Task 6: Delete old installer scripts

**Files:**
- Delete: `coa_app/SETUP.bat`
- Delete: `coa_app/INSTALL.bat`
- Delete: `coa_app/START.bat`
- Delete: `coa_app/install_windows.bat`
- Delete: `coa_app/start_coa.bat`

- [ ] **Step 1: Delete old scripts**

```bash
git rm coa_app/SETUP.bat coa_app/INSTALL.bat coa_app/START.bat coa_app/install_windows.bat coa_app/start_coa.bat
```

- [ ] **Step 2: Commit**

```bash
git commit -m "chore(coa): remove old installer scripts replaced by PyInstaller exe"
```

---

### Task 7: Test build on Windows

This task must be done on a Windows machine.

- [ ] **Step 1: Run build**

```bash
cd coa_app
build_windows.bat
```

Expected: `coa_app/dist/LabCore_COA/` folder created with `LabCore_COA.exe`.

- [ ] **Step 2: Test the exe**

Double-click `dist/LabCore_COA/LabCore_COA.exe`.

Expected:
- Browser opens at `http://localhost:5050` in app mode
- App loads, pages render (templates, CSS, JS all bundled)
- `dist/LabCore_COA/data/` folder created with `batch_db.sqlite`

- [ ] **Step 3: Test cert generation**

1. Go to Settings, configure server URL
2. Click Sync to download data
3. Generate a certificate PDF

Expected: PDF saved to `~/Desktop/Swiadectwa/` (requires LibreOffice installed).

- [ ] **Step 4: Fix any hidden import errors**

If the app crashes with `ModuleNotFoundError`, add the missing module to `hiddenimports` in `labcore_coa.spec` and rebuild.

Common issues:
- `_bcrypt` → add `"_bcrypt"` to hiddenimports
- `jinja2.ext` → add `"jinja2.ext"` to hiddenimports
- `email.mime` → add `"email.mime.text"` to hiddenimports

- [ ] **Step 5: Commit any spec fixes**

```bash
git add coa_app/labcore_coa.spec
git commit -m "fix(coa): add missing hidden imports for PyInstaller"
```

---

### Task 8: Add PyInstaller artifacts to .gitignore

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add PyInstaller output dirs to .gitignore**

Add these lines to `.gitignore`:

```
# PyInstaller
coa_app/build/
coa_app/dist/
*.spec.bak
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: add PyInstaller build artifacts to .gitignore"
```