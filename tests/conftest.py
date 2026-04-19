"""Shared pytest setup — signals 'testing mode' to create_app."""
import os

os.environ.setdefault("MBR_TESTING", "1")

# Eagerly import mbr.app so the module-level `app = create_app()` runs
# under MBR_TESTING=1, before any individual test monkeypatches env vars.
# Without this, tests that monkeypatch.delenv("MBR_TESTING") before their
# first `from mbr.app import ...` would trigger the guard at import time.
import mbr.app  # noqa: E402, F401
