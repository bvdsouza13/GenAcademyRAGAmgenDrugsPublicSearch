"""Hosted access checks fail closed and never trust a UI-only role."""

from types import SimpleNamespace

import pytest
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


def test_hosted_mutating_service_operations_recheck_admin_role(tmp_path, monkeypatch):
    from amgen_explorer.chunking import ChunkConfig
    from amgen_explorer.config import AppConfig, load_config
    from amgen_explorer.errors import UserFacingError
    from amgen_explorer.service import ExplorerService

    settings = load_config(secrets_path=tmp_path / "missing").settings
    settings["app"].update(mode="hosted", auth_enabled=True)
    service = ExplorerService(AppConfig(settings, tmp_path), _start_admin_worker=False)
    monkeypatch.setattr("amgen_explorer.auth.user_is_admin", lambda *_args, **_kwargs: False)

    operations = [
        lambda: service.import_documents([]),
        lambda: service.build_library(ChunkConfig()),
        lambda: service.verify_library("a" * 64),
        lambda: service.verify_library("a" * 64, repair=True),
        lambda: service.use_configuration("a" * 64),
        lambda: service.revert_library(),
        lambda: service.restore_library_version("a" * 64),
        lambda: service.publish("a" * 64, None),
        lambda: service.rollback("a" * 64),
    ]
    for operation in operations:
        with pytest.raises(UserFacingError, match="authorized administrators"):
            operation()


def test_hosted_library_changes_fail_closed_without_durable_storage(tmp_path, monkeypatch):
    from amgen_explorer.config import AppConfig, load_config
    from amgen_explorer.errors import UserFacingError
    from amgen_explorer.service import ExplorerService

    settings = load_config(secrets_path=tmp_path / "missing").settings
    settings["app"].update(mode="hosted", auth_enabled=True)
    service = ExplorerService(AppConfig(settings, tmp_path), _start_admin_worker=False)
    monkeypatch.setattr("amgen_explorer.auth.user_is_admin", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("amgen_explorer.durable_library.backend_enabled", lambda: False)

    with pytest.raises(UserFacingError, match="durable managed storage"):
        service.import_documents([])


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
