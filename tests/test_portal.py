"""Portal sessions: ``POST /api/v1/portal/sessions`` with the user's access token."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from sweatstack import PortalDestination, PortalSessionResponse
from sweatstack.client import Client
from sweatstack.exceptions import SweatStackAuthError, SweatStackBadRequestError


@pytest.fixture
def app():
    c = Client.__new__(Client)
    c.url = "https://test.sweatstack.no"
    c._api_key = None
    c._refresh_token = None
    c._client_secret = None
    c.client_id = "app_123"
    c.streamlit_compatible = False
    c.skip_token_expiry_check = True
    return c


def _http_returning(status_code: int, payload) -> MagicMock:
    request = httpx.Request("POST", "https://test.sweatstack.no/api/v1/portal/sessions")
    response = httpx.Response(status_code, json=payload, request=request)
    http = MagicMock()
    http.__enter__ = MagicMock(return_value=http)
    http.__exit__ = MagicMock(return_value=False)
    http.post.return_value = response
    return http


def _mint(app, **kwargs):
    http = _http_returning(
        200, {"url": "https://app.sweatstack.no/portal/integrations?app=app_123"}
    )
    with patch.object(app, "_http_client", return_value=http) as http_client:
        session = app.portal.sessions.create(**kwargs)
    return session, http.post.call_args.kwargs, http_client.call_args.kwargs


class TestRequestBody:
    def test_sends_the_destination_and_nothing_about_the_app(self, app):
        """The app is the token's audience, so the body names no client and carries no secret."""
        session, call, _ = _mint(app, destination="manage-integrations")
        assert call["url"] == "/api/v1/portal/sessions"
        assert call["json"] == {"destination": "manage-integrations"}
        assert isinstance(session, PortalSessionResponse)
        assert session.url.startswith("https://app.sweatstack.no/portal/")

    def test_accepts_the_enum(self, app):
        _, call, _ = _mint(app, destination=PortalDestination.manage_teams)
        assert call["json"] == {"destination": "manage-teams"}

    def test_return_url_is_forwarded_only_when_given(self, app):
        _, call, _ = _mint(
            app, destination="manage-integrations", return_url="https://example.com/app/"
        )
        assert call["json"]["return_url"] == "https://example.com/app/"
        _, call, _ = _mint(app, destination="manage-integrations")
        assert "return_url" not in call["json"]  # omitting it is meaningful to the Portal

    def test_unknown_destination_string_passes_through(self, app):
        _, call, _ = _mint(app, destination="manage-something-new")
        assert call["json"]["destination"] == "manage-something-new"


class TestUserToken:
    def test_minting_sends_the_users_bearer(self, app):
        _, _, http_client_kwargs = _mint(app, destination="manage-integrations")
        assert http_client_kwargs == {"auth": True}


class TestErrors:
    def test_no_token_or_a_delegated_one(self, app):
        http = _http_returning(403, {"detail": "Delegated token not allowed."})
        with (
            patch.object(app, "_http_client", return_value=http),
            pytest.raises(SweatStackAuthError),
        ):
            app.portal.sessions.create("manage-integrations")

    def test_return_url_outside_the_redirect_uris(self, app):
        http = _http_returning(
            400,
            {
                "detail": "return_url must equal or sit under one of the application's "
                "registered redirect URIs"
            },
        )
        with (
            patch.object(app, "_http_client", return_value=http),
            pytest.raises(SweatStackBadRequestError),
        ):
            app.portal.sessions.create("manage-integrations", return_url="https://evil.example/")
