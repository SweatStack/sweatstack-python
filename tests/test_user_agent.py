"""The token calls the integrations make without a ``Client`` carry the SDK's User-Agent.

Four call sites post to the token endpoints directly: the FastAPI refresh, login and delegated
token, and the Streamlit login. Each goes through ``_transport.post``. ``httpx.post`` is patched
here, so what is asserted is the request each site hands to httpx: the SDK's ``User-Agent``,
and everything the site sent before it got one. The guard that keeps new call sites honest is
in ``test_transport.py``.
"""

import base64
import json
import time
from unittest.mock import patch

import httpx
import pytest

from sweatstack.constants import DEFAULT_URL, USER_AGENT

TOKEN_URL = f"{DEFAULT_URL}/api/v1/oauth/token"


def _jwt(sub: str = "user_123") -> str:
    """A JWT-shaped token whose body decodes; the signature is never checked offline."""
    body = json.dumps({"sub": sub, "exp": time.time() + 3600}).encode()
    return f"header.{base64.urlsafe_b64encode(body).decode().rstrip('=')}.signature"


def _token_response(**extra: str) -> httpx.Response:
    payload = {"access_token": _jwt(), "refresh_token": "refresh_123", **extra}
    return httpx.Response(200, json=payload, request=httpx.Request("POST", TOKEN_URL))


class TestFastAPI:
    @pytest.fixture(autouse=True)
    def configured(self):
        pytest.importorskip("fastapi")
        from cryptography.fernet import Fernet

        from sweatstack.fastapi import config as config_module
        from sweatstack.fastapi import configure

        configure(
            client_id="app_123",
            client_secret="secret_123",
            app_url="http://localhost:8000",
            session_secret=Fernet.generate_key().decode(),
        )
        yield
        config_module._config = None

    def test_refresh(self):
        from sweatstack.fastapi.dependencies import REFRESH_HTTP_TIMEOUT, _refresh_access_token

        with patch("httpx.post", return_value=_token_response(access_token="new")) as post:
            access_token, rotated = _refresh_access_token("refresh_123", "app_123", "secret_123")

        assert (access_token, rotated) == ("new", None)  # same refresh token echoed: no rotation
        kwargs = post.call_args.kwargs
        assert post.call_args.args == (TOKEN_URL,)
        assert kwargs["headers"]["User-Agent"] == USER_AGENT
        assert kwargs["data"] == {
            "grant_type": "refresh_token",
            "refresh_token": "refresh_123",
            "client_id": "app_123",
            "client_secret": "secret_123",
        }
        assert kwargs["timeout"] == REFRESH_HTTP_TIMEOUT

    def test_login(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from sweatstack.fastapi import instrument
        from sweatstack.fastapi.routes import create_state
        from sweatstack.fastapi.session import STATE_COOKIE_NAME

        app = FastAPI()
        instrument(app)
        http = TestClient(app, follow_redirects=False)
        state = create_state(None)
        http.cookies.set(STATE_COOKIE_NAME, state)

        with patch("httpx.post", return_value=_token_response()) as post:
            response = http.get(
                "/auth/sweatstack/callback", params={"code": "code_123", "state": state}
            )

        assert response.status_code == 302
        assert "auth_error" not in response.headers["location"]
        kwargs = post.call_args.kwargs
        assert post.call_args.args == (TOKEN_URL,)
        assert kwargs["headers"]["User-Agent"] == USER_AGENT
        assert kwargs["data"]["grant_type"] == "authorization_code"
        assert kwargs["data"]["code"] == "code_123"
        assert kwargs["data"]["client_secret"] == "secret_123"

    def test_delegated_token(self):
        from sweatstack.fastapi.models import TokenSet
        from sweatstack.fastapi.routes import _fetch_delegated_token

        principal = TokenSet(access_token=_jwt("user_1"), refresh_token="r1", user_id="user_1")
        with patch("httpx.post", return_value=_token_response()) as post:
            delegated = _fetch_delegated_token(principal, "user_2", team_id="team_123")

        assert delegated.user_id == "user_2"
        kwargs = post.call_args.kwargs
        assert post.call_args.args == (f"{DEFAULT_URL}/api/v1/oauth/delegated-token",)
        assert kwargs["headers"]["User-Agent"] == USER_AGENT
        assert kwargs["headers"]["Authorization"] == f"Bearer {principal.access_token}"
        assert kwargs["json"] == {"sub": "user_2", "team_id": "team_123"}


class TestStreamlit:
    def test_login(self):
        st = pytest.importorskip("streamlit")
        from sweatstack.streamlit import StreamlitAuth

        with patch.object(st, "session_state", {}):
            auth = StreamlitAuth(
                client_id="app_123", client_secret="secret_123", redirect_uri="http://x"
            )
            with patch("httpx.post", return_value=_token_response()) as post:
                auth._exchange_token("code_123")

        kwargs = post.call_args.kwargs
        assert post.call_args.args == (TOKEN_URL,)
        assert kwargs["headers"]["User-Agent"] == USER_AGENT
        assert kwargs["data"]["grant_type"] == "authorization_code"
        assert kwargs["data"]["code"] == "code_123"
        assert isinstance(kwargs["auth"], httpx.BasicAuth)
