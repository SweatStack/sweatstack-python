"""Identity methods: ``whoami`` and ``oauth.userinfo``."""

import base64
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from pydantic import SecretStr

from sweatstack import UserInfoResponse, UserSummary
from sweatstack.client import Client


def _jwt(**claims) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


@pytest.fixture
def client():
    c = Client.__new__(Client)
    c.url = "https://test.sweatstack.no"
    c._api_key = SecretStr(_jwt(sub="01JUSER", exp=4102444800))
    c._refresh_token = None
    c._client_secret = None
    c.streamlit_compatible = False
    c.skip_token_expiry_check = True
    return c


class TestWhoami:
    def test_finds_the_token_subject_among_accessible_users(self, client):
        me, other = (
            UserSummary(
                id=user_id,
                first_name=user_id,
                last_name=None,
                scopes=[],
                display_name=user_id,
                is_managed=False,
            )
            for user_id in ("01JUSER", "01JOTHER")
        )
        with patch.object(client.users, "list", return_value=[other, me]):
            assert client.whoami() is me

    def test_unknown_subject_raises(self, client):
        with (
            patch.object(client.users, "list", return_value=[]),
            pytest.raises(ValueError, match="01JUSER"),
        ):
            client.whoami()

    def test_requires_a_token(self, client):
        client._api_key = None
        # Offline: the property would otherwise fall back to env vars and the developer's stored tokens.
        with (
            patch.object(client, "_load_token_pair", return_value=(None, None)),
            pytest.raises(ValueError, match="Not authenticated"),
        ):
            client.whoami()


class TestUserinfo:
    def test_issue_is_exposed(self, client):
        request = httpx.Request("GET", "https://test.sweatstack.no/api/v1/oauth/userinfo")
        payload = {
            "sub": "01JUSER",
            "name": "A",
            "registered_at": "2025-01-01T00:00:00Z",
            "issue": {
                "code": "no_source_connected",
                "status": "action_required",
                "message": "No data source is connected yet.",
                "action_url": "https://app.sweatstack.no/portal/x",
            },
        }
        http = MagicMock()
        http.__enter__ = MagicMock(return_value=http)
        http.__exit__ = MagicMock(return_value=False)
        http.get.return_value = httpx.Response(200, json=payload, request=request)
        with patch.object(client, "_http_client", return_value=http):
            user = client.oauth.userinfo()
        assert isinstance(user, UserInfoResponse)
        assert user.issue is not None and user.issue.action_url.endswith("/portal/x")
