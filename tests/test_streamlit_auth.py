"""The Streamlit integration's token handling: the session owns the pair.

``st.session_state`` and ``st.context.headers`` are replaced by plain mappings on the module, so
each test is one session, and a rerun is a new ``StreamlitAuth``.
"""

import json
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sweatstack.client import Client
from sweatstack.exceptions import SweatStackTokenRefreshError
from sweatstack.schemas import TokenResponse

from .test_credentials import OWNERS, acts_as, jwt, write_token_file

st = pytest.importorskip("streamlit")
from sweatstack.streamlit import StreamlitAuth  # noqa: E402  needs the extra


@pytest.fixture
def session():
    with patch.object(st, "session_state", {}) as state:
        yield state


@pytest.fixture
def headers():
    mapping: dict[str, str] = {}
    with patch.object(st, "context", SimpleNamespace(headers=mapping)):
        yield mapping


@pytest.fixture
def refreshes():
    calls: list[str] = []

    def refresh(self, refresh_token: str) -> TokenResponse:
        calls.append(refresh_token)
        return TokenResponse(access_token=jwt(OWNERS[refresh_token], 900), expires_in=900)

    with patch.object(Client, "_do_token_refresh", refresh):
        yield calls


def auth() -> StreamlitAuth:
    return StreamlitAuth(client_id="app_123", client_secret="secret", redirect_uri="http://x")


def proxied() -> StreamlitAuth:
    return StreamlitAuth.behind_proxy(redirect_uri="http://x")


class TestOAuthMode:
    def test_a_session_without_tokens_has_none(self, session, isolated_credentials, monkeypatch):
        write_token_file(isolated_credentials, jwt("user_b", 900), "refresh_b")
        monkeypatch.setenv("SWEATSTACK_API_KEY", jwt("user_b", 900))
        assert auth().client.api_key is None
        assert not auth().is_authenticated()

    def test_one_refresh_per_lifetime_across_reruns(self, session, refreshes):
        auth()._set_api_key(jwt("user_a", -60), "refresh_a")
        for _ in range(3):
            assert acts_as(auth().client) == "user_a"
        assert refreshes == ["refresh_a"]
        assert session["sweatstack_api_key"] == auth().client.api_key.get_secret_value()
        assert session["sweatstack_refresh_token"] == "refresh_a"

    def test_a_pair_without_refresh_token_does_not_keep_the_previous_one(self, session):
        auth()._set_api_key(jwt("user_a", 900), "refresh_a")
        auth()._set_api_key(jwt("user_b", 900), None)
        assert session["sweatstack_refresh_token"] is None
        assert auth().client.refresh_token is None

    def test_logout_clears_everything(self, session, isolated_credentials):
        write_token_file(isolated_credentials, jwt("user_b", 900), "refresh_b")
        session.update(
            sweatstack_api_key="a",
            sweatstack_refresh_token="r",
            sweatstack_proxy_api_key="a",
            sweatstack_proxy_refresh_token="r",
        )
        a = auth()
        with patch.object(st, "button", return_value=True), patch.object(st, "rerun"):
            a.logout_button()
        assert session == {}
        assert a.client.api_key is None
        assert not a.is_authenticated()

    def test_a_refresh_never_touches_the_file(self, session, refreshes, isolated_credentials):
        auth()._set_api_key(jwt("user_a", -60), "refresh_a")
        _ = auth().client.api_key
        assert not isolated_credentials.exists()


class TestProxyMode:
    def test_fresh_header_pair(self, session, headers, refreshes):
        headers["X-SweatStack-Token"] = jwt("user_a", 900)
        headers["X-SweatStack-Refresh-Token"] = "refresh_a"
        a = proxied()
        assert a.is_authenticated()
        assert a.client.api_key.get_secret_value() == headers["X-SweatStack-Token"]
        assert refreshes == []
        assert session["sweatstack_proxy_refresh_token"] == "refresh_a"

    def test_expired_header_token_renews_once_across_reruns(self, session, headers, refreshes):
        headers["X-SweatStack-Token"] = jwt("user_a", -60)
        headers["X-SweatStack-Refresh-Token"] = "refresh_a"
        for _ in range(3):
            assert acts_as(proxied().client) == "user_a"
        assert refreshes == ["refresh_a"]
        assert session["sweatstack_proxy_api_key"] == proxied().client.api_key.get_secret_value()

    def test_a_newer_header_token_wins_after_a_reload(self, session, headers, refreshes):
        session["sweatstack_proxy_api_key"] = jwt("user_a", 300)
        session["sweatstack_proxy_refresh_token"] = "refresh_a"
        headers["X-SweatStack-Token"] = jwt("user_a", 900)
        headers["X-SweatStack-Refresh-Token"] = "refresh_a"
        assert proxied().client.api_key.get_secret_value() == headers["X-SweatStack-Token"]
        assert refreshes == []

    def test_a_new_login_replaces_the_stored_pair(self, session, headers, refreshes):
        session["sweatstack_proxy_api_key"] = jwt("user_a", 900)
        session["sweatstack_proxy_refresh_token"] = "refresh_a"
        headers["X-SweatStack-Token"] = jwt("user_b", 300)
        headers["X-SweatStack-Refresh-Token"] = "refresh_b"
        assert acts_as(proxied().client) == "user_b"
        assert session["sweatstack_proxy_refresh_token"] == "refresh_b"

    def test_no_headers_means_logged_out(self, session, headers):
        session["sweatstack_proxy_api_key"] = jwt("user_a", 900)
        session["sweatstack_proxy_refresh_token"] = "refresh_a"
        a = proxied()
        assert not a.is_authenticated()
        assert a.client.api_key is None
        assert "sweatstack_proxy_api_key" not in session

    def test_no_refresh_header_gives_an_actionable_error_after_expiry(
        self, session, headers, refreshes
    ):
        headers["X-SweatStack-Token"] = jwt("user_a", -60)
        a = proxied()
        assert a.is_authenticated()  # the proxy says so; the token just cannot be renewed
        with pytest.raises(SweatStackTokenRefreshError, match="Reload the page"):
            _ = a.client.api_key
        assert refreshes == []
        assert "sweatstack_proxy_api_key" not in session

    def test_select_user_leaves_the_proxy_pair_alone(self, session, headers, refreshes):
        headers["X-SweatStack-Token"] = jwt("user_a", 900)
        headers["X-SweatStack-Refresh-Token"] = "refresh_a"
        a = proxied()
        delegated = Client(jwt("user_b", 900), refresh_token=None, url=None)
        athlete = SimpleNamespace(id="user_b", display_name="B")
        with (
            patch.object(Client, "principal_client", return_value=a.client),
            patch.object(Client, "users"),
            patch.object(Client, "delegated_client", return_value=delegated),
            patch.object(st, "selectbox", return_value=athlete),
        ):
            a.select_user()
        assert acts_as(a.client) == "user_b"
        assert session["sweatstack_api_key"] == delegated.api_key.get_secret_value()
        assert session["sweatstack_refresh_token"] is None
        assert session["sweatstack_proxy_refresh_token"] == "refresh_a"
        assert acts_as(proxied().client) == "user_a"  # the next rerun starts as the user again

    def test_nothing_is_read_from_or_written_to_the_file(
        self, session, headers, refreshes, isolated_credentials, monkeypatch
    ):
        write_token_file(isolated_credentials, jwt("user_b", 900), "refresh_b")
        monkeypatch.setenv("SWEATSTACK_API_KEY", jwt("user_b", 900))
        headers["X-SweatStack-Token"] = jwt("user_a", -60)
        headers["X-SweatStack-Refresh-Token"] = "refresh_a"
        assert acts_as(proxied().client) == "user_a"
        assert json.loads(isolated_credentials.read_text())["refresh_token"] == "refresh_b"


class TestHookOutsideAScriptRun:
    def test_a_worker_thread_refresh_does_not_raise(self, session, refreshes):
        auth()._set_api_key(jwt("user_a", -60), "refresh_a")
        client = auth().client
        errors = []

        def use():
            try:
                with patch.object(st, "session_state", None):  # no session in this thread
                    _ = client.api_key
            except Exception as error:  # noqa: BLE001
                errors.append(error)

        thread = threading.Thread(target=use)
        thread.start()
        thread.join()
        assert errors == []
        assert acts_as(client) == "user_a"
