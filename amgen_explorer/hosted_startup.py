"""Start Streamlit with Google OIDC settings supplied through Replit Secrets."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]


def google_auth_settings(environment) -> dict | None:
    """Return private settings without printing credentials or provider claims."""
    client_id = environment.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = environment.get("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id and not client_secret:
        return None
    cookie_secret = environment.get("SESSION_SECRET", "")
    redirect_uri = environment.get("AUTH_REDIRECT_URI", "").strip()
    parsed = urlsplit(redirect_uri)
    if (not client_id or not client_secret or len(cookie_secret) < 32
            or parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path != "/oauth2callback"):
        raise ValueError("Google sign-in settings are incomplete or invalid. Check Replit Secrets and AUTH_REDIRECT_URI.")
    return {
        "redirect_uri": redirect_uri,
        "cookie_secret": cookie_secret,
        "client_id": client_id,
        "client_secret": client_secret,
        "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
    }


def streamlit_command(environment=None) -> list[str]:
    environment = os.environ if environment is None else environment
    command = [
        sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
        "--server.address", "0.0.0.0", "--server.port", "5000",
        "--server.headless", "true",
    ]
    auth = google_auth_settings(environment)
    if auth is not None:
        # Streamlit reads OIDC configuration before application code executes.
        # Keep this generated file private, ephemeral, and outside the repository.
        directory = Path(tempfile.mkdtemp(prefix="amgen-oidc-"))
        path = directory / "secrets.toml"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("[auth]\n")
            for name, value in auth.items():
                handle.write(f"{name} = {json.dumps(value)}\n")
        command.extend(["--secrets.files", str(path)])
    return command


def main() -> int:
    try:
        command = streamlit_command()
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    os.chdir(ROOT)
    os.execv(command[0], command)
    return 0
