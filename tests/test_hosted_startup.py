"""Synthetic OIDC configuration tests never read or print real credentials."""
from pathlib import Path
import shutil
import stat
import tomllib

import pytest

from amgen_explorer.config import load_config
from amgen_explorer.hosted_startup import google_auth_settings, streamlit_command


def environment():
    return {
        "GOOGLE_CLIENT_ID": "synthetic.apps.googleusercontent.com",
        "GOOGLE_CLIENT_SECRET": 'synthetic"quoted\nvalue',
        "SESSION_SECRET": "x" * 40,
        "AUTH_REDIRECT_URI": "https://example.test/oauth2callback",
    }


def test_private_auth_file_roundtrips_special_characters_without_changing_repo():
    values = environment()
    command = streamlit_command(values)
    path = Path(command[command.index("--secrets.files") + 1])
    try:
        auth = tomllib.loads(path.read_text())["auth"]
        assert auth == google_auth_settings(values)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    finally:
        shutil.rmtree(path.parent)


def test_missing_credentials_keeps_native_streamlit_configuration():
    assert google_auth_settings({}) is None
    assert "--secrets.files" not in streamlit_command({})


@pytest.mark.parametrize("name,value", [
    ("GOOGLE_CLIENT_ID", ""),
    ("GOOGLE_CLIENT_SECRET", ""),
    ("SESSION_SECRET", "short"),
    ("AUTH_REDIRECT_URI", "http://example.test/oauth2callback"),
    ("AUTH_REDIRECT_URI", "https://example.test/wrong"),
    ("AUTH_REDIRECT_URI", "https://example.test/oauth2callback?token=value"),
])
def test_partial_or_unsafe_oidc_configuration_fails_closed(name, value):
    values = environment()
    values[name] = value
    with pytest.raises(ValueError, match="incomplete or invalid"):
        google_auth_settings(values)


def test_production_mode_can_require_sign_in_without_changing_local_config(monkeypatch):
    monkeypatch.setenv("AMGEN_APP_MODE", "hosted")
    settings = load_config().settings["app"]
    assert settings["mode"] == "hosted"
    assert settings["auth_enabled"] is True


def test_invalid_environment_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("AMGEN_APP_MODE", "typo")
    with pytest.raises(ValueError, match="AMGEN_APP_MODE"):
        load_config()
