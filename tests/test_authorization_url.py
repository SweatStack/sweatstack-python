"""The authorize URL: one builder behind ``client.oauth.authorization_url()``, the FastAPI plugin
and the Streamlit helper.

None of them sends ``prompt``: without it, SweatStack skips the consent screen when the user's
grant already covers the request (OpenID Connect Core 3.1.2.4). Every scope list is
space-delimited (RFC 6749 section 3.3).
"""

from __future__ import annotations

from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sweatstack import Client
from sweatstack.constants import DEFAULT_SCOPE
from sweatstack.fastapi import configure, instrument


def query(url: str) -> dict[str, str]:
    split = urlsplit(url)
    assert split.path == "/oauth/authorize"
    return {key: values[0] for key, values in parse_qs(split.query).items()}


class TestAuthorizationUrl:
    def test_sends_what_it_is_given_and_nothing_else(self):
        url = Client().oauth.authorization_url(
            client_id="app", redirect_uri="http://x/cb", scope="openid activities:read"
        )
        assert query(url) == {
            "client_id": "app",
            "redirect_uri": "http://x/cb",
            "scope": "openid activities:read",
        }

    def test_a_challenge_comes_with_its_method(self):
        url = Client().oauth.authorization_url(
            client_id="app", redirect_uri="http://x/cb", code_challenge="challenge"
        )
        assert query(url)["code_challenge"] == "challenge"
        assert query(url)["code_challenge_method"] == "S256"

    def test_the_documented_parameters(self):
        url = Client().oauth.authorization_url(
            client_id="app",
            redirect_uri="http://x/cb",
            prompt="consent",
            state="s",
            nonce="n",
            integration="garmin_connect",
            email_auth_mode="existing_only",
        )
        assert query(url) == {
            "client_id": "app",
            "redirect_uri": "http://x/cb",
            "scope": DEFAULT_SCOPE,
            "prompt": "consent",
            "state": "s",
            "nonce": "n",
            "integration": "garmin_connect",
            "email_auth_mode": "existing_only",
        }


@pytest.fixture
def fastapi_app():
    import sweatstack.fastapi.config as config_module

    configure(
        client_id="app",
        client_secret="secret",
        app_url="http://localhost:8000",
        session_secret="dGVzdC1vbmx5LWtleS1mb3ItdW5pdC10ZXN0cy0zMmI=",
    )
    app = FastAPI()
    instrument(app)
    yield app
    config_module._config = None


def test_the_fastapi_login_sends_no_prompt(fastapi_app):
    response = TestClient(fastapi_app, follow_redirects=False).get("/auth/sweatstack/login")
    sent = query(response.headers["location"])

    assert "prompt" not in sent
    assert "," not in sent["scope"]
    assert sent["state"]


def test_the_streamlit_helper_sends_no_prompt_and_delimits_scopes_with_spaces():
    st = pytest.importorskip("streamlit")
    from sweatstack.streamlit import StreamlitAuth

    with patch.object(st, "session_state", {}):
        auth = StreamlitAuth(client_id="app", client_secret="secret", redirect_uri="http://x")
        sent = query(auth.get_authorization_url())

    assert "prompt" not in sent
    assert "," not in sent["scope"]
