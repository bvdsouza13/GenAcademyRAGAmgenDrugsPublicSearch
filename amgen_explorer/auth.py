"""Hosted pilot sign-in and application-role checks."""

from collections.abc import Mapping
import os
from typing import Any

import streamlit as st


def _claim(user: Any, name: str, default: Any = None) -> Any:
    if isinstance(user, Mapping):
        return user.get(name, default)
    try:
        return getattr(user, name, default)
    except Exception:
        return default


def user_is_logged_in(user: Any = None) -> bool:
    """Return true only when Streamlit reports a completed OIDC sign-in."""
    if user is None:
        user = st.user
    return _claim(user, "is_logged_in", False) is True


def configured_admin_emails(raw: str | None = None) -> frozenset[str]:
    """Read the administrator allowlist without exposing its configured values."""
    if raw is None:
        raw = os.environ.get("ADMIN_EMAILS", "")
    return frozenset(
        email.strip().casefold()
        for email in raw.split(",")
        if email.strip()
    )


def user_is_admin(user: Any = None, admin_emails: frozenset[str] | None = None) -> bool:
    """Authorize only signed-in users with a verified, explicitly allowlisted email."""
    if user is None:
        try:
            user = st.user
        except Exception:
            return False
    if not user_is_logged_in(user):
        return False
    if _claim(user, "email_verified") is not True:
        return False
    email = _claim(user, "email")
    if not isinstance(email, str):
        return False
    if admin_emails is None:
        admin_emails = configured_admin_emails()
    return email.strip().casefold() in admin_emails


def admin_operation_allowed(settings: Mapping[str, Any], user: Any = None) -> bool:
    """Check the role at a service boundary; local operator mode remains available."""
    app = settings.get("app", {})
    if app.get("mode") == "local" and app.get("auth_enabled") is False:
        return True
    return (
        app.get("mode") == "hosted"
        and app.get("auth_enabled") is True
        and user_is_admin(user)
    )


def _oidc_is_configured() -> bool:
    """Check the non-secret shape of Streamlit's OIDC settings."""
    try:
        auth = st.secrets.get("auth", {})
    except Exception:
        return False
    if not isinstance(auth, Mapping):
        return False
    if not auth.get("redirect_uri") or not auth.get("cookie_secret"):
        return False
    provider = auth.get("default", auth)
    return isinstance(provider, Mapping) and all(
        provider.get(key) for key in ("client_id", "client_secret", "server_metadata_url")
    )


def require_sign_in() -> Any:
    """Stop the current Streamlit run before protected content if not signed in."""
    if not _oidc_is_configured():
        st.error("Sign-in is not configured for this hosted pilot. Protected content is unavailable.")
        st.stop()
    user = st.user
    if user_is_logged_in(user):
        return user
    st.title("Sign in to continue")
    st.write("Sign in with your pilot account to access the learner workspace.")
    st.button("Sign in", key="pilot_sign_in", on_click=st.login)
    st.stop()


def require_admin(settings: Mapping[str, Any] | None = None) -> bool:
    """Enforce the hosted Admin role in Python before rendering admin controls."""
    if settings is None:
        try:
            from .config import load_config

            settings = load_config().settings
        except Exception:
            st.error("Admin access is unavailable because the access policy could not be loaded.")
            st.stop()
    app = settings.get("app", {})
    if app.get("mode") == "local" and app.get("auth_enabled") is False:
        return True
    if app.get("mode") == "hosted" and app.get("auth_enabled") is True and user_is_admin():
        return True
    st.error("This area is restricted to authorized administrators.")
    st.stop()
