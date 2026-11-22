"""Hosted access checks fail closed and never trust a UI-only role."""

from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from amgen_explorer.auth import configured_admin_emails, user_is_admin


def test_admin_requires_signed_in_verified_allowlisted_email():
    allowlist = configured_admin_emails("Admin@example.com, learner@example.com")
    assert user_is_admin(
        {"is_logged_in": True, "email": "ADMIN@example.com", "email_verified": True},
        allowlist,
    )
    assert not user_is_admin(
        {"is_logged_in": False, "email": "admin@example.com", "email_verified": True},
        allowlist,
    )
    assert not user_is_admin(
        {"is_logged_in": True, "email": "admin@example.com", "email_verified": False},
        allowlist,
    )
    assert not user_is_admin(
        {"is_logged_in": True, "email": "other@example.com", "email_verified": True},
        allowlist,
    )


def test_admin_allowlist_is_normalized_and_empty_by_default(monkeypatch):
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    assert configured_admin_emails() == frozenset()
    assert configured_admin_emails(" , Admin@Example.com , ") == {"admin@example.com"}


def test_hosted_admin_route_stops_before_rendering_protected_controls():
    app = AppTest.from_string(
        """
import streamlit as st
from amgen_explorer.auth import require_admin
require_admin({"app": {"mode": "hosted", "auth_enabled": True}})
st.write("PROTECTED ADMIN CONTENT")
"""
    ).run()
    assert not app.exception
    assert any("restricted to authorized administrators" in item.value for item in app.error)
    assert not any("PROTECTED ADMIN CONTENT" in item.value for item in app.markdown)


def test_sign_in_gate_fails_closed_when_oidc_is_not_configured():
    app = AppTest.from_string(
        """
import streamlit as st
from amgen_explorer.auth import require_sign_in
require_sign_in()
st.write("PROTECTED LEARNER CONTENT")
"""
    ).run()
    assert not app.exception
    assert any("Sign-in is not configured" in item.value for item in app.error)
    assert not any("PROTECTED LEARNER CONTENT" in item.value for item in app.markdown)
