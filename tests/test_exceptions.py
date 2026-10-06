"""Tests for the SweatStack exception hierarchy.

Covers:
- Exception instantiation and attributes
- Inheritance relationships
- __str__ and __repr__ formatting
- _raise_for_status status code mapping
- Transport error wrapping
"""


import httpx
import pytest

from sweatstack import Client
from sweatstack.exceptions import (
    SweatStackAPIError,
    SweatStackAuthError,
    SweatStackBadRequestError,
    SweatStackConnectionError,
    SweatStackError,
    SweatStackNotFoundError,
    SweatStackRateLimitError,
    SweatStackServerError,
    SweatStackTokenRefreshError,
)

# ---------------------------------------------------------------------------
# Hierarchy and inheritance
# ---------------------------------------------------------------------------


class TestHierarchy:
    def test_api_error_is_sweatstack_error(self):
        exc = SweatStackAPIError(status_code=500, url="http://x", method="GET")
        assert isinstance(exc, SweatStackError)
        assert isinstance(exc, Exception)

    def test_server_error_is_api_error(self):
        exc = SweatStackServerError(status_code=500, url="http://x", method="GET")
        assert isinstance(exc, SweatStackAPIError)
        assert isinstance(exc, SweatStackError)

    def test_auth_error_is_api_error(self):
        exc = SweatStackAuthError(status_code=401, url="http://x", method="GET")
        assert isinstance(exc, SweatStackAPIError)

    def test_not_found_error_is_api_error(self):
        exc = SweatStackNotFoundError(status_code=404, url="http://x", method="GET")
        assert isinstance(exc, SweatStackAPIError)

    def test_rate_limit_error_is_api_error(self):
        exc = SweatStackRateLimitError(status_code=429, url="http://x", method="GET")
        assert isinstance(exc, SweatStackAPIError)

    def test_bad_request_error_is_api_error(self):
        exc = SweatStackBadRequestError(status_code=422, url="http://x", method="POST")
        assert isinstance(exc, SweatStackAPIError)

    def test_connection_error_is_sweatstack_error_not_api_error(self):
        exc = SweatStackConnectionError("DNS failed")
        assert isinstance(exc, SweatStackError)
        assert not isinstance(exc, SweatStackAPIError)

    def test_token_refresh_error_is_sweatstack_error_not_api_error(self):
        exc = SweatStackTokenRefreshError("token expired")
        assert isinstance(exc, SweatStackError)
        assert not isinstance(exc, SweatStackAPIError)


# ---------------------------------------------------------------------------
# Attributes
# ---------------------------------------------------------------------------


class TestAttributes:
    def test_api_error_attributes(self):
        exc = SweatStackAPIError(
            status_code=500,
            url="https://api.sweatstack.no/api/v1/activities",
            method="GET",
            request_id="req-123",
            body={"error": "internal"},
        )
        assert exc.status_code == 500
        assert exc.url == "https://api.sweatstack.no/api/v1/activities"
        assert exc.method == "GET"
        assert exc.request_id == "req-123"
        assert exc.body == {"error": "internal"}

    def test_api_error_optional_attributes_default_to_none(self):
        exc = SweatStackAPIError(status_code=400, url="http://x", method="POST")
        assert exc.request_id is None
        assert exc.body is None

    def test_rate_limit_error_retry_after(self):
        exc = SweatStackRateLimitError(
            retry_after=30, status_code=429, url="http://x", method="GET"
        )
        assert exc.retry_after == 30
        assert exc.status_code == 429

    def test_rate_limit_error_retry_after_defaults_to_none(self):
        exc = SweatStackRateLimitError(status_code=429, url="http://x", method="GET")
        assert exc.retry_after is None


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


class TestFormatting:
    def test_str_basic(self):
        exc = SweatStackServerError(status_code=502, url="http://api/v1/x", method="GET")
        assert str(exc) == "502: GET http://api/v1/x"

    def test_str_with_request_id(self):
        exc = SweatStackServerError(
            status_code=503, url="http://api/v1/x", method="POST", request_id="abc-123"
        )
        assert "(request_id=abc-123)" in str(exc)

    def test_str_with_body(self):
        exc = SweatStackBadRequestError(
            status_code=400, url="http://x", method="POST", body="bad input"
        )
        assert "bad input" in str(exc)

    def test_repr(self):
        exc = SweatStackServerError(status_code=502, url="http://api/v1/x", method="GET")
        r = repr(exc)
        assert r == "SweatStackServerError(status_code=502, method='GET', url='http://api/v1/x')"

    def test_connection_error_str(self):
        exc = SweatStackConnectionError("Connection refused")
        assert str(exc) == "Connection refused"

    def test_token_refresh_error_str(self):
        exc = SweatStackTokenRefreshError("token expired")
        assert str(exc) == "token expired"


# ---------------------------------------------------------------------------
# _raise_for_status mapping
# ---------------------------------------------------------------------------


def _make_response(status_code, headers=None, json_body=None, text_body=""):
    """Create a mock httpx.Response for testing _raise_for_status."""
    request = httpx.Request("GET", "https://api.sweatstack.no/api/v1/test")
    response = httpx.Response(
        status_code=status_code,
        request=request,
        headers=headers or {},
        json=json_body,
        text=text_body if json_body is None else None,
    )
    return response


class TestRaiseForStatus:
    @pytest.fixture
    def client(self):
        return Client.__new__(Client)

    def test_success_does_not_raise(self, client):
        response = _make_response(200)
        client._raise_for_status(response)  # should not raise

    def test_401_raises_auth_error(self, client):
        response = _make_response(401)
        with pytest.raises(SweatStackAuthError) as exc_info:
            client._raise_for_status(response)
        assert exc_info.value.status_code == 401

    def test_403_raises_auth_error(self, client):
        response = _make_response(403)
        with pytest.raises(SweatStackAuthError) as exc_info:
            client._raise_for_status(response)
        assert exc_info.value.status_code == 403

    def test_404_raises_not_found_error(self, client):
        response = _make_response(404)
        with pytest.raises(SweatStackNotFoundError) as exc_info:
            client._raise_for_status(response)
        assert exc_info.value.status_code == 404

    def test_429_raises_rate_limit_error(self, client):
        response = _make_response(429, headers={"retry-after": "60"})
        with pytest.raises(SweatStackRateLimitError) as exc_info:
            client._raise_for_status(response)
        assert exc_info.value.status_code == 429
        assert exc_info.value.retry_after == 60

    def test_429_without_retry_after_header(self, client):
        response = _make_response(429)
        with pytest.raises(SweatStackRateLimitError) as exc_info:
            client._raise_for_status(response)
        assert exc_info.value.retry_after is None

    def test_400_raises_bad_request_error(self, client):
        response = _make_response(400)
        with pytest.raises(SweatStackBadRequestError) as exc_info:
            client._raise_for_status(response)
        assert exc_info.value.status_code == 400

    def test_422_raises_bad_request_error(self, client):
        response = _make_response(422, json_body={"detail": [{"msg": "field required"}]})
        with pytest.raises(SweatStackBadRequestError) as exc_info:
            client._raise_for_status(response)
        assert exc_info.value.status_code == 422
        assert exc_info.value.body == {"detail": [{"msg": "field required"}]}

    def test_500_raises_server_error(self, client):
        response = _make_response(500)
        with pytest.raises(SweatStackServerError) as exc_info:
            client._raise_for_status(response)
        assert exc_info.value.status_code == 500

    def test_502_raises_server_error(self, client):
        response = _make_response(502)
        with pytest.raises(SweatStackServerError) as exc_info:
            client._raise_for_status(response)
        assert exc_info.value.status_code == 502

    def test_503_raises_server_error(self, client):
        response = _make_response(503)
        with pytest.raises(SweatStackServerError) as exc_info:
            client._raise_for_status(response)
        assert exc_info.value.status_code == 503

    def test_request_id_populated_from_header(self, client):
        response = _make_response(500, headers={"x-request-id": "req-abc"})
        with pytest.raises(SweatStackServerError) as exc_info:
            client._raise_for_status(response)
        assert exc_info.value.request_id == "req-abc"

    def test_json_body_parsed(self, client):
        response = _make_response(400, json_body={"error": "invalid_field"})
        with pytest.raises(SweatStackBadRequestError) as exc_info:
            client._raise_for_status(response)
        assert exc_info.value.body == {"error": "invalid_field"}

    def test_text_body_fallback(self, client):
        response = _make_response(500, text_body="Internal Server Error")
        with pytest.raises(SweatStackServerError) as exc_info:
            client._raise_for_status(response)
        assert exc_info.value.body == "Internal Server Error"

    def test_url_and_method_populated(self, client):
        response = _make_response(404)
        with pytest.raises(SweatStackNotFoundError) as exc_info:
            client._raise_for_status(response)
        assert exc_info.value.url == "https://api.sweatstack.no/api/v1/test"
        assert exc_info.value.method == "GET"

    def test_catchable_as_api_error(self, client):
        response = _make_response(503)
        with pytest.raises(SweatStackAPIError):
            client._raise_for_status(response)

    def test_catchable_as_sweatstack_error(self, client):
        response = _make_response(401)
        with pytest.raises(SweatStackError):
            client._raise_for_status(response)


# ---------------------------------------------------------------------------
# Transport error wrapping
# ---------------------------------------------------------------------------


class TestTransportErrors:
    def test_http_client_wraps_connect_error(self):
        client = Client.__new__(Client)
        client.url = "http://localhost:1"
        client._api_key = None
        client._client_secret = None
        client.streamlit_compatible = False

        with pytest.raises(SweatStackConnectionError) as exc_info:
            with client._http_client(skip_token_check=True):
                raise httpx.ConnectError("Connection refused")

        assert "Connection refused" in str(exc_info.value)

    def test_http_client_wraps_timeout_error(self):
        client = Client.__new__(Client)
        client.url = "http://localhost:1"
        client._api_key = None
        client._client_secret = None
        client.streamlit_compatible = False

        with pytest.raises(SweatStackConnectionError):
            with client._http_client(skip_token_check=True):
                raise httpx.ReadTimeout("Read timed out")

    def test_connection_error_preserves_cause(self):
        client = Client.__new__(Client)
        client.url = "http://localhost:1"
        client._api_key = None
        client._client_secret = None
        client.streamlit_compatible = False

        original = httpx.ConnectError("DNS resolution failed")
        with pytest.raises(SweatStackConnectionError) as exc_info:
            with client._http_client(skip_token_check=True):
                raise original

        assert exc_info.value.__cause__ is original
