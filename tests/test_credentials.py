"""Where a client's tokens come from, and where a renewed pair goes.

The rule: the access token and the refresh token come from one source (arguments, else the
environment, else the token file), never one half from each, and only a client whose pair lives
in the token file writes a renewed pair back there. ``tests/conftest.py`` points the file at a
temporary directory and clears the environment variables.
"""

import base64
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sweatstack.client import Client
from sweatstack.exceptions import SweatStackTokenRefreshError
from sweatstack.schemas import TokenResponse

URL = "https://test.sweatstack.no"


def jwt(sub: str, expires_in: float) -> str:
    """An unsigned token with the two claims the client reads."""
    claims = {"sub": sub, "exp": time.time() + expires_in}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def acts_as(client: Client) -> str:
    payload = client.api_key.get_secret_value().split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=="))["sub"]


def response(payload: dict) -> SimpleNamespace:
    """What ``Client._request`` returns, as far as a token endpoint's caller reads it."""
    return SimpleNamespace(json=lambda: payload)


OWNERS = {"refresh_a": "user_a", "refresh_b": "user_b"}


@pytest.fixture
def refreshes():
    """Answers refreshes offline, from the refresh token's owner. Records the calls."""
    calls: list[str] = []

    def refresh(self, refresh_token: str) -> TokenResponse:
        calls.append(refresh_token)
        return TokenResponse(access_token=jwt(OWNERS[refresh_token], 900), expires_in=900)

    with patch.object(Client, "_do_token_refresh", refresh):
        yield calls


@pytest.fixture
def token_file(isolated_credentials):
    return isolated_credentials


def write_token_file(path, access_token, refresh_token):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"access_token": access_token, "refresh_token": refresh_token}))


class TestOneSource:
    """The regression tests for the token mixing fixed in 0.94."""

    def test_an_access_only_client_never_borrows_the_saved_refresh_token(
        self, refreshes, token_file
    ):
        write_token_file(token_file, jwt("user_b", 900), "refresh_b")  # another user's sign-in
        client = Client(jwt("user_a", -60), url=URL)
        with pytest.raises(SweatStackTokenRefreshError, match="no refresh token"):
            _ = client.api_key
        assert refreshes == []

    def test_a_bare_client_with_ambient_credentials_off_has_nothing(self, token_file):
        write_token_file(token_file, jwt("user_b", 900), "refresh_b")
        client = Client(url=URL, ambient_credentials=False)
        assert client.api_key is None
        assert client.refresh_token is None

    def test_environment_and_arguments_never_mix(self, refreshes, monkeypatch):
        monkeypatch.setenv("SWEATSTACK_REFRESH_TOKEN", "refresh_b")
        client = Client(jwt("user_a", -60), url=URL)
        with pytest.raises(SweatStackTokenRefreshError):
            _ = client.api_key
        assert refreshes == []

    def test_environment_and_file_never_mix(self, refreshes, token_file, monkeypatch):
        write_token_file(token_file, jwt("user_b", 900), "refresh_b")
        monkeypatch.setenv("SWEATSTACK_API_KEY", jwt("user_a", -60))
        with pytest.raises(SweatStackTokenRefreshError):
            _ = Client(url=URL).api_key
        assert refreshes == []

    def test_a_delegated_pair_without_refresh_token_is_token_only(self, refreshes, token_file):
        write_token_file(token_file, jwt("user_b", 900), "refresh_b")
        principal = Client(jwt("admin", 900), refresh_token="refresh_a", url=URL)
        tokens = {"access_token": jwt("user_a", -60), "refresh_token": None}
        with patch.object(principal, "_request", return_value=response(tokens)):
            delegated = principal.delegated_client("user_a")
        with pytest.raises(SweatStackTokenRefreshError):
            _ = delegated.api_key
        assert refreshes == []


class TestWriteBack:
    def test_an_explicit_pair_never_creates_the_file(self, refreshes, token_file):
        client = Client(jwt("user_a", -60), refresh_token="refresh_a", url=URL)
        assert acts_as(client) == "user_a"
        assert refreshes == ["refresh_a"]
        assert not token_file.exists()

    def test_an_environment_pair_never_creates_the_file(self, refreshes, token_file, monkeypatch):
        monkeypatch.setenv("SWEATSTACK_API_KEY", jwt("user_a", -60))
        monkeypatch.setenv("SWEATSTACK_REFRESH_TOKEN", "refresh_a")
        assert acts_as(Client(url=URL)) == "user_a"
        assert not token_file.exists()

    def test_a_file_pair_is_written_back(self, refreshes, token_file):
        write_token_file(token_file, jwt("user_a", -60), "refresh_a")
        client = Client(url=URL)
        assert acts_as(client) == "user_a"
        saved = json.loads(token_file.read_text())
        assert saved["access_token"] == client.api_key.get_secret_value()
        assert saved["refresh_token"] == "refresh_a"

    def test_a_refresh_token_alone_is_enough(self, refreshes, token_file):
        write_token_file(token_file, None, "refresh_a")
        assert acts_as(Client(url=URL)) == "user_a"
        assert json.loads(token_file.read_text())["refresh_token"] == "refresh_a"

    def test_authenticate_with_persist_makes_the_client_file_backed(self, refreshes, token_file):
        client = Client(url=URL)
        signed_in = jwt("user_a", -60)  # expired right away, to force a refresh below
        tokens = {"access_token": signed_in, "refresh_token": "refresh_a", "expires_in": 900}

        def browser_sign_in(persist):  # what _open_browser_oauth does once the code is back
            client.oauth.exchange_code("code", client_id="app_123", persist=persist)

        with (
            patch.object(client, "_request", return_value=response(tokens)),
            patch.object(client, "_open_browser_oauth", side_effect=browser_sign_in),
        ):
            client.authenticate()
        assert client._file_backed
        assert acts_as(client) == "user_a"  # refreshed after the sign-in
        assert json.loads(token_file.read_text())["access_token"] != signed_in

    def test_persist_is_refused_without_ambient_credentials(self, token_file):
        client = Client(url=URL, ambient_credentials=False)
        with pytest.raises(ValueError, match="ambient_credentials=False"):
            client.authenticate()
        with pytest.raises(ValueError, match="ambient_credentials=False"):
            client._save_tokens("access", "refresh")
        assert not token_file.exists()

    def test_exchange_code_writes_the_file_only_on_request(self, token_file):
        client = Client(url=URL)
        tokens = {
            "access_token": jwt("user_a", 900),
            "refresh_token": "refresh_a",
            "expires_in": 900,
        }
        with patch.object(client, "_request", return_value=response(tokens)):
            client.oauth.exchange_code("code", client_id="app_123")
            assert not token_file.exists()
            assert not client._file_backed
            client.oauth.exchange_code("code", client_id="app_123", persist=True)
        assert json.loads(token_file.read_text())["refresh_token"] == "refresh_a"
        assert client._file_backed


class TestRotation:
    def test_a_rotated_refresh_token_replaces_the_old_one(self, token_file):
        write_token_file(token_file, jwt("user_a", -60), "refresh_old")
        client = Client(url=URL)
        rotated = TokenResponse(
            access_token=jwt("user_a", 900), refresh_token="refresh_new", expires_in=900
        )
        seen = []
        client._on_refresh = lambda access, refresh: seen.append((access, refresh))
        with patch.object(client, "_do_token_refresh", return_value=rotated):
            _ = client.api_key
        assert client.refresh_token.get_secret_value() == "refresh_new"
        assert json.loads(token_file.read_text())["refresh_token"] == "refresh_new"
        assert seen == [(rotated.access_token, "refresh_new")]

    def test_a_response_without_refresh_token_keeps_the_old_one(self, refreshes):
        client = Client(jwt("user_a", -60), refresh_token="refresh_a", url=URL)
        _ = client.api_key
        assert client.refresh_token.get_secret_value() == "refresh_a"


class TestHook:
    def test_called_once_per_refresh_with_the_pair_in_force(self, refreshes):
        client = Client(jwt("user_a", -60), refresh_token="refresh_a", url=URL)
        seen = []
        client._on_refresh = lambda access, refresh: seen.append((access, refresh))
        _ = client.api_key
        _ = client.api_key  # valid now: no second refresh
        assert seen == [(client.api_key.get_secret_value(), "refresh_a")]

    def test_concurrent_threads_refresh_once_and_notify_once(self):
        client = Client(jwt("user_a", -60), refresh_token="refresh_a", url=URL)
        seen = []
        client._on_refresh = lambda access, refresh: seen.append(access)

        def refresh(refresh_token):
            time.sleep(0.05)
            return TokenResponse(access_token=jwt("user_a", 900), expires_in=900)

        with patch.object(client, "_do_token_refresh", side_effect=refresh) as do_refresh:
            threads = [threading.Thread(target=lambda: client.api_key) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        assert do_refresh.call_count == 1
        assert len(seen) == 1

    def test_derived_clients_inherit_the_flag_but_not_the_hook(self):
        client = Client(
            jwt("user_a", 900), refresh_token="refresh_a", url=URL, ambient_credentials=False
        )
        client._on_refresh = lambda access, refresh: None
        tokens = {"access_token": jwt("user_b", 900), "refresh_token": "refresh_b"}
        with patch.object(client, "_request", return_value=response(tokens)):
            derived = client.delegated_client("user_b")
        assert derived.ambient_credentials is False
        assert derived._on_refresh is None


class TestResolution:
    def test_a_miss_is_not_remembered(self, monkeypatch):
        client = Client(url=URL)
        assert client.api_key is None
        monkeypatch.setenv("SWEATSTACK_API_KEY", jwt("user_a", 900))
        assert acts_as(client) == "user_a"

    def test_a_hit_is_remembered(self, token_file, monkeypatch):
        write_token_file(token_file, jwt("user_a", 900), "refresh_a")
        client = Client(url=URL)
        assert acts_as(client) == "user_a"
        write_token_file(token_file, jwt("user_b", 900), "refresh_b")
        assert acts_as(client) == "user_a"

    def test_setting_one_half_makes_the_arguments_the_source(self, token_file):
        write_token_file(token_file, jwt("user_b", 900), "refresh_b")
        client = Client(url=URL)
        client.api_key = jwt("user_a", 900)
        assert client.refresh_token is None

    def test_the_module_level_client_uses_ambient_credentials(self):
        import sweatstack

        assert sweatstack.client._default_client.ambient_credentials is True
