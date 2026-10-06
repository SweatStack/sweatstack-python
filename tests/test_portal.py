"""Portal sessions: ``POST /api/v1/portal/sessions`` with the app's own credentials."""

from unittest.mock import MagicMock, PropertyMock, patch

import httpx
import pytest
from pydantic import SecretStr

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
        session = app.create_portal_session(**kwargs)
    return session, http.post.call_args.kwargs, http_client.call_args.kwargs


class TestRequestBody:
    def test_public_client_sends_id_and_destination_only(self, app):
        session, call, _ = _mint(app, destination="manage-integrations")
        assert call["url"] == "/api/v1/portal/sessions"
        assert call["json"] == {"client_id": "app_123", "destination": "manage-integrations"}
        assert isinstance(session, PortalSessionResponse)
        assert session.url.startswith("https://app.sweatstack.no/portal/")

    def test_confidential_client_sends_its_secret(self, app):
        app._client_secret = SecretStr("s3cret")
        _, call, _ = _mint(app, destination=PortalDestination.manage_teams)
        assert call["json"]["client_secret"] == "s3cret"
        assert call["json"]["destination"] == "manage-teams"

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


class TestNoUserToken:
    def test_minting_uses_the_unauthenticated_http_client(self, app):
        _, _, http_client_kwargs = _mint(app, destination="manage-integrations")
        assert http_client_kwargs == {"auth": False}

    def test_auth_false_sends_no_authorization_header_and_never_loads_a_token(self, app):
        app._api_key = SecretStr("user-bearer")
        with patch.object(Client, "api_key", new_callable=PropertyMock) as api_key:
            api_key.side_effect = AssertionError("token load/refresh must not run for auth=False")
            with app._http_client(auth=False) as http:
                assert "authorization" not in {k.lower() for k in http.headers}
                assert http.headers["user-agent"].startswith("python-sweatstack/")

    def test_auth_true_still_sends_the_bearer(self, app):
        app._api_key = SecretStr("user-bearer")
        with app._http_client(skip_token_check=True) as http:
            assert http.headers["authorization"] == "Bearer user-bearer"


class TestErrors:
    def test_bad_credentials(self, app):
        http = _http_returning(401, {"detail": "Invalid client credentials"})
        with (
            patch.object(app, "_http_client", return_value=http),
            pytest.raises(SweatStackAuthError),
        ):
            app.create_portal_session("manage-integrations")

    def test_unregistered_return_url(self, app):
        http = _http_returning(400, {"detail": "return_url is not registered for this application"})
        with (
            patch.object(app, "_http_client", return_value=http),
            pytest.raises(SweatStackBadRequestError),
        ):
            app.create_portal_session("manage-integrations", return_url="https://evil.example/")
