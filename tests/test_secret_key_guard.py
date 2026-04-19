"""create_app() must refuse to start with an unset or dev-default SECRET_KEY
unless the TESTING escape hatch is in effect."""

import pytest


def test_create_app_fails_when_secret_key_unset(monkeypatch):
    monkeypatch.delenv("MBR_SECRET_KEY", raising=False)
    monkeypatch.delenv("MBR_TESTING", raising=False)
    from mbr.app import create_app
    with pytest.raises(RuntimeError, match="MBR_SECRET_KEY"):
        create_app()


def test_create_app_fails_on_known_dev_placeholder(monkeypatch):
    monkeypatch.setenv("MBR_SECRET_KEY", "CHANGE-ME-TO-RANDOM-STRING")
    monkeypatch.delenv("MBR_TESTING", raising=False)
    from mbr.app import create_app
    with pytest.raises(RuntimeError, match="MBR_SECRET_KEY"):
        create_app()


def test_create_app_fails_on_dev_fallback_literal(monkeypatch):
    monkeypatch.setenv("MBR_SECRET_KEY", "dev-secret-change-in-prod")
    monkeypatch.delenv("MBR_TESTING", raising=False)
    from mbr.app import create_app
    with pytest.raises(RuntimeError, match="MBR_SECRET_KEY"):
        create_app()


def test_create_app_accepts_real_looking_key(monkeypatch):
    monkeypatch.setenv("MBR_SECRET_KEY", "3f9a2c5bf0e84a1b9d6e7c2a5f3d8e1b")
    monkeypatch.delenv("MBR_TESTING", raising=False)
    from mbr.app import create_app
    app = create_app()
    assert app.secret_key == "3f9a2c5bf0e84a1b9d6e7c2a5f3d8e1b"


def test_testing_env_disables_guard(monkeypatch):
    """pytest-running path: MBR_TESTING=1 lets the dev fallback through."""
    monkeypatch.delenv("MBR_SECRET_KEY", raising=False)
    monkeypatch.setenv("MBR_TESTING", "1")
    from mbr.app import create_app
    app = create_app()
    assert app.secret_key  # some value present, any value
