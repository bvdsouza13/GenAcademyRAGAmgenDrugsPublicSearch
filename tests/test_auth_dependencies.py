"""A configured hosted login must have Streamlit's optional OIDC dependencies."""
from authlib.integrations.starlette_client import OAuth
import httpx


def test_hosted_login_dependencies_are_available():
    assert OAuth() is not None
    assert httpx.AsyncClient is not None
