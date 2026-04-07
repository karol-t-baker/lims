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
    console=False,
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
