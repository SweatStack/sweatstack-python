"""The HTTP layer: connection reuse, timeouts, retries and the token refresh lock.

Requests run through the real transport (``Client._request``, ``_http_client``,
``_transport.Session``) against ``httpx.MockTransport``, so what is tested is what goes on the
wire. ``time.sleep`` is patched; the waits it would have slept are asserted instead.
"""

import base64
import json
import threading
import time
from unittest.mock import PropertyMock, patch

import httpx
import pytest

from sweatstack import _transport
from sweatstack.client import Client
from sweatstack.exceptions import (
    SweatStackConnectionError,
    SweatStackRateLimitError,
    SweatStackServerError,
)

URL = "https://test.sweatstack.no"


def _client(handler, **kwargs) -> tuple[Client, list[httpx.Request]]:
    """A client whose pool answers with ``handler``; also returns the requests it received."""
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request, len(seen))

    client = Client(api_key="user-token", url=URL, skip_token_expiry_check=True, **kwargs)
    pool = httpx.Client(base_url=URL, transport=httpx.MockTransport(record))
    client.__dict__["_pool_entry"] = (URL, pool)
    return client, seen


def _statuses(*codes, headers=None):
    """A handler answering with these statuses in turn (the last one repeats)."""

    def handler(request, n):
        code = codes[min(n, len(codes)) - 1]
        return httpx.Response(code, json=[] if code < 400 else {"detail": "x"}, headers=headers)

    return handler


@pytest.fixture
def sleep():
    with patch("sweatstack.client.time.sleep") as sleep:
        yield sleep


class TestPolicy:
    def test_backoff_doubles_with_jitter_and_is_capped(self):
        for attempt, base in [(0, 0.5), (1, 1.0), (2, 2.0)]:
            assert base * 0.75 <= _transport.backoff(attempt) <= base * 1.25
        assert _transport.backoff(10) == _transport.MAX_BACKOFF

    @pytest.mark.parametrize("method", ["get", "put", "delete"])
    def test_safe_methods_are_retried(self, method):
        assert _transport.wait_before_retry(method, 0, 2, 0.0) is not None

    def test_post_is_never_retried(self):
        assert _transport.wait_before_retry("post", 0, 2, 0.0) is None
        assert _transport.wait_before_retry("post", 0, 2, 0.0, httpx.Response(503)) is None

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
    def test_client_errors_are_not_retried(self, status):
        assert _transport.wait_before_retry("get", 0, 2, 0.0, httpx.Response(status)) is None

    def test_retry_after_is_honoured_up_to_a_minute(self):
        honoured = httpx.Response(429, headers={"retry-after": "3"})
        assert _transport.wait_before_retry("get", 0, 2, 0.0, honoured) == 3.0
        too_long = httpx.Response(429, headers={"retry-after": "120"})
        assert _transport.wait_before_retry("get", 0, 2, 0.0, too_long) is None

    def test_the_budget_and_max_retries_stop_retrying(self):
        assert _transport.wait_before_retry("get", 2, 2, 0.0) is None
        assert _transport.wait_before_retry("get", 0, 2, _transport.RETRY_BUDGET) is None


class TestRetries:
    def test_transient_errors_are_retried_until_success(self, sleep):
        client, seen = _client(_statuses(503, 502, 200))
        assert client._request("get", "/api/v1/traces/").status_code == 200
        assert len(seen) == 3
        assert sleep.call_count == 2

    def test_exhausted_retries_raise_the_typed_error(self, sleep):
        client, seen = _client(_statuses(503))
        with pytest.raises(SweatStackServerError):
            client._request("get", "/api/v1/traces/")
        assert len(seen) == 3  # one attempt plus max_retries=2

    def test_post_is_sent_once(self, sleep):
        client, seen = _client(_statuses(503))
        with pytest.raises(SweatStackServerError):
            client._request("post", "/api/v1/traces/", json={})
        assert len(seen) == 1
        sleep.assert_not_called()

    def test_retry_after_sets_the_wait(self, sleep):
        client, _ = _client(_statuses(429, 200, headers={"retry-after": "2"}))
        client._request("get", "/api/v1/traces/")
        sleep.assert_called_once_with(2.0)

    def test_a_long_retry_after_fails_at_once_with_the_wait(self, sleep):
        client, seen = _client(_statuses(429, headers={"retry-after": "120"}))
        with pytest.raises(SweatStackRateLimitError) as error:
            client._request("get", "/api/v1/traces/")
        assert error.value.retry_after == 120
        assert len(seen) == 1

    def test_connection_errors_are_retried_then_raised(self, sleep):
        def handler(request, n):
            raise httpx.ConnectError("refused")

        client, seen = _client(handler)
        with pytest.raises(SweatStackConnectionError):
            client._request("get", "/api/v1/traces/")
        assert len(seen) == 3

    def test_a_retried_delete_that_finds_nothing_succeeded(self, sleep):
        client, _ = _client(_statuses(503, 404))
        assert client._request("delete", "/api/v1/traces/t1").status_code == 404

    def test_a_first_delete_that_finds_nothing_is_an_error(self, sleep):
        client, _ = _client(_statuses(404))
        with pytest.raises(Exception, match="404"):
            client._request("delete", "/api/v1/traces/t1")

    def test_max_retries_zero_sends_once(self, sleep):
        client, seen = _client(_statuses(503), max_retries=0)
        with pytest.raises(SweatStackServerError):
            client._request("get", "/api/v1/traces/")
        assert len(seen) == 1


class TestConnections:
    def test_requests_share_one_pool(self):
        client, seen = _client(_statuses(200))
        pool = client._pool()
        client._request("get", "/api/v1/traces/")
        client._request("get", "/api/v1/tests/")
        assert client._pool() is pool and len(seen) == 2

    def test_authorization_is_per_request(self):
        client, seen = _client(_statuses(200))
        client._request("get", "/api/v1/traces/")
        client._request("post", "/api/v1/oauth/token", data={}, auth=False)
        assert seen[0].headers["authorization"] == "Bearer user-token"
        assert "authorization" not in seen[1].headers
        assert all(r.headers["user-agent"].startswith("python-sweatstack/") for r in seen)

    def test_auth_false_sends_no_authorization_header_and_never_loads_a_token(self):
        """The token exchange runs before there is a token to load or refresh."""
        client = Client(api_key="user-bearer", url=URL)
        with patch.object(Client, "api_key", new_callable=PropertyMock) as api_key:
            api_key.side_effect = AssertionError("token load/refresh must not run for auth=False")
            with client._http_client(auth=False) as http:
                assert "authorization" not in {k.lower() for k in http.headers}
                assert http.headers["user-agent"].startswith("python-sweatstack/")

    def test_close_releases_the_pool_and_the_next_call_opens_one(self):
        client = Client(api_key="x", url=URL)
        pool = client._pool()
        with client:
            pass
        assert pool.is_closed
        assert client._pool() is not pool

    def test_timeout_reaches_the_pool_and_streams_have_no_read_timeout(self):
        client = Client(api_key="x", url=URL, timeout=7.5)
        assert client._pool().timeout.read == 7.5
        with patch.object(client._pool(), "stream") as stream:
            with client._http_client(skip_token_check=True) as http:
                with http.stream("GET", "/api/v1/activities/backfill-status"):
                    pass
        timeout = stream.call_args.kwargs["timeout"]
        assert timeout.read is None and timeout.connect == 7.5

    @pytest.mark.parametrize("kwargs", [{"timeout": 0}, {"max_retries": -1}])
    def test_invalid_settings_are_rejected(self, kwargs):
        with pytest.raises(ValueError):
            Client(api_key="x", **kwargs)

    def test_derived_clients_keep_the_settings(self):
        client, _ = _client(
            lambda request, n: httpx.Response(
                200, json={"access_token": "a", "refresh_token": "r"}
            ),
            timeout=5.0,
            max_retries=0,
        )
        for derived in (client.delegated_client("u1"), client.principal_client()):
            assert (derived.timeout, derived.max_retries) == (5.0, 0)


def _jwt(exp: float) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"sub": "u1", "exp": exp}).encode()).decode()
    return f"header.{payload.rstrip('=')}.signature"


def test_concurrent_threads_refresh_an_expired_token_once():
    client = Client(api_key=_jwt(time.time() - 60), refresh_token="refresh", url=URL)
    calls = []

    def refresh(refresh_token):
        calls.append(refresh_token)
        time.sleep(0.05)  # long enough for every thread to arrive while one refreshes
        return _jwt(time.time() + 3600)

    with (
        patch.object(client, "_do_token_refresh", side_effect=refresh),
        patch.object(client, "_save_tokens"),
    ):
        threads = [threading.Thread(target=lambda: client.api_key) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert len(calls) == 1
