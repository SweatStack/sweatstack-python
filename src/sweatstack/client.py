from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import random
import shutil
import threading
import time
import webbrowser
from collections.abc import Iterator
from datetime import date, datetime
from enum import Enum
from functools import cached_property, wraps
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.metadata import version
from inspect import getmembers, isfunction
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

import httpx
from platformdirs import user_cache_dir, user_data_dir
from pydantic import SecretStr

from . import _frames, _renames, _transport
from ._frames import FrameOutput, set_output
from .constants import DEFAULT_URL
from .exceptions import (
    SweatStackAPIError,
    SweatStackAuthError,
    SweatStackBadRequestError,
    SweatStackConnectionError,
    SweatStackNotFoundError,
    SweatStackRateLimitError,
    SweatStackServerError,
    SweatStackTokenRefreshError,
)
from .resources import (
    Activities,
    Dailies,
    OAuth,
    Portal,
    Profile,
    Teams,
    Tests,
    Traces,
    Users,
)
from .schemas import (
    AccountStatusResponse,
    ActivityDetails,
    ActivitySummary,
    ApplicationMemberRole,
    AuthorizedTeamResponse,
    BackfillStatus,
    Capability,
    CapabilityStatus,
    DailyMeasure,
    DailyResponse,
    IssueStatus,
    Marker,
    Metric,
    Modifier,
    PortalDestination,
    PortalSessionResponse,
    Scope,
    SourceError,
    SourceResponse,
    Sport,
    StatusIssueCode,
    StatusIssueResponse,
    TeamResponse,
    TestDetails,
    TestResults,
    TestSummary,
    TokenResponse,
    TraceDetails,
    TraceResolution,
    UserInfoResponse,
    UserResponse,
    UserSummary,
)
from .utils import decode_jwt_body, make_dataframe_streamlit_compatible

logger = logging.getLogger(__name__)

# Refresh tokens this many seconds before they expire to avoid race conditions
TOKEN_EXPIRY_MARGIN_SECONDS = 5

# Module-level cache configuration. None = caching disabled.
_cache_config: dict | None = None


def enable_cache(path: str | None = None) -> None:
    """Enable local caching of longitudinal responses.

    Args:
        path: Optional custom cache directory. Defaults to the platform cache dir.
    """
    global _cache_config
    _cache_config = {"path": path}


AUTH_SUCCESSFUL_RESPONSE = """<!DOCTYPE html>
<html>
<head>
    <style>
        body { max-width: 600px; margin: 40px auto; text-align: center; }
        h1 { color: #2C3E50; font-size: 24px; }
        p { color: #34495E; font-size: 18px; }
    </style>
</head>
<body>
    <img src="https://sweatstack.no/images/sweat-stack-python-client.png" alt="SweatStack Logo" style="width: 200px; margin: 20px auto; display: block;">
    <h1>Successfully authenticated with SweatStack!</h1>
    <p>You have successfully authenticated using the SweatStack Python client library. You can now close this window and return to your Python environment.</p>
</body>
</html>"""
OAUTH2_CLIENT_ID = "5382f68b0d254378"

try:
    __version__ = version("sweatstack")
except ImportError:
    __version__ = "unknown"


def _to_secret(value: str | SecretStr | None) -> SecretStr | None:
    """Convert a string to SecretStr, or return None if value is None."""
    if value is None:
        return None
    if isinstance(value, SecretStr):
        return value
    return SecretStr(value)


def _is_expired(access_token: str) -> bool:
    """Whether a JWT access token expires within the safety margin.

    Raises:
        SweatStackTokenRefreshError: If the token is not a JWT or has no ``exp`` claim.
    """
    try:
        payload = decode_jwt_body(access_token)
    except Exception as e:
        raise SweatStackTokenRefreshError(f"Invalid access token: {e}") from e
    expires_at = payload.get("exp")
    if expires_at is None:
        raise SweatStackTokenRefreshError("Access token missing 'exp' claim")
    return expires_at - TOKEN_EXPIRY_MARGIN_SECONDS < time.time()


class Client:
    """The SweatStack API client.

    Every endpoint group is an attribute named after its URL segment: ``client.activities``,
    ``client.traces``, ``client.tests``, ``client.dailies``, ``client.profile``,
    ``client.users``, ``client.teams``, ``client.portal`` and ``client.oauth``.

    Create one client per user. In a script or notebook, ``Client()`` finds your credentials
    (``authenticate()``, the ``SWEATSTACK_API_KEY`` environment variable, or the tokens saved
    by an earlier sign-in). In an app, use the client the FastAPI or Streamlit helper hands
    you for each signed-in user.

    Examples:
        ```python
        from sweatstack import Client

        client = Client()
        client.authenticate()  # opens the browser only when no saved sign-in exists
        latest = client.activities.latest()
        data = client.activities.data(latest.id)
        ```
    """

    # Class-level defaults, so an instance built without ``__init__`` (as the tests do) still
    # resolves them. See ``__init__`` for what each one means.
    output: FrameOutput | None = None
    timeout: float = 60.0
    max_retries: int = 2

    def __init__(
        self,
        api_key: str | SecretStr | None = None,
        refresh_token: str | SecretStr | None = None,
        url: str | None = None,
        streamlit_compatible: bool = False,
        client_id: str | None = None,
        client_secret: str | SecretStr | None = None,
        skip_token_expiry_check: bool = False,
        output: FrameOutput | None = None,
        timeout: float = 60.0,
        max_retries: int = 2,
    ):
        """Initialize a SweatStack client.

        Args:
            api_key: Optional API access token. If not provided, will check environment or storage.
            refresh_token: Optional refresh token for automatic token renewal.
            url: Optional SweatStack instance URL. Defaults to production.
            streamlit_compatible: Set to True when using in Streamlit apps.
            client_id: Optional OAuth client ID. Defaults to the public client ID.
            client_secret: Optional OAuth client secret for confidential clients.
            skip_token_expiry_check: If True, skip JWT expiry validation and use the token as-is.
                Use this when token lifecycle is managed externally (e.g. by a proxy).
            output: Default container for every method that returns a collection:
                ``"pandas"``, ``"polars"``, ``"arrow"`` or ``"bytes"``. A per-call
                ``output=`` always wins; a value a method cannot produce (``"arrow"``
                or ``"bytes"`` on list endpoints) is ignored for that method. When
                ``None``, the module default from :func:`sweatstack.set_output`
                applies; failing that, time series come back in the installed
                frame library (Polars if both are installed) and lists as models.
                Only the data endpoints take ``output`` (activities, traces, tests,
                dailies and the time series); account, team, status and Portal
                methods always return models.
            timeout: Seconds to wait for a connection and for each read. Streams have no read
                timeout.
            max_retries: How often to retry a ``GET``, ``PUT`` or ``DELETE`` after a connection
                error, a timeout, or a 408, 429 or 5xx response, with exponential backoff and
                the server's ``Retry-After``. ``POST`` is never retried, since the API has no
                idempotency keys. At most 30 s of waiting per call. Use ``0`` where latency
                matters more than resilience, such as inside a web request.

        Examples:
            ```python
            from sweatstack import Client

            client = Client(timeout=120.0, max_retries=4)  # a long batch job
            with Client(api_key="...") as client:          # closes the connection pool on exit
                client.activities.list()
            ```
        """
        if timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")
        if max_retries < 0:
            raise ValueError(f"max_retries must be 0 or more, got {max_retries}")
        self._api_key: SecretStr | None = _to_secret(api_key)
        self._refresh_token: SecretStr | None = _to_secret(refresh_token)
        self._client_secret: SecretStr | None = _to_secret(client_secret)
        self.url = url
        self.streamlit_compatible = streamlit_compatible
        self.skip_token_expiry_check = skip_token_expiry_check
        self.output = _frames.check_frame_output(output)
        self.client_id = client_id or OAUTH2_CLIENT_ID
        self.timeout = timeout
        self.max_retries = max_retries

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Closes the client's connection pool. The client opens a new one if used again.

        Call this, or use the client as a context manager, to release connections at a known
        point, for example in a worker that creates many clients.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            client.activities.list()
            client.close()
            ```
        """
        built = self.__dict__.pop("_pool_entry", None)
        if built is not None:
            built[1].close()

    def __getattr__(self, name: str) -> Any:
        # Only reached when normal lookup fails: names a removed method's replacement.
        raise _renames.attribute_error(f"{type(self).__name__!r} object", name, prefix="client")

    # -------------------------------------------------------------------------
    # Resources: one per URL segment after /api/v1/ (plan 009, R1)
    # -------------------------------------------------------------------------

    @cached_property
    def activities(self) -> Activities:
        """Activities, their time series and analyses: ``/api/v1/activities/...``."""
        return Activities(self)

    @cached_property
    def traces(self) -> Traces:
        """Traces (point measurements such as lactate): ``/api/v1/traces/...``."""
        return Traces(self)

    @cached_property
    def tests(self) -> Tests:
        """Tests (fitness assessments): ``/api/v1/tests/...``."""
        return Tests(self)

    @cached_property
    def dailies(self) -> Dailies:
        """Daily measures (body mass, HRV, ...): ``/api/v1/dailies/...``."""
        return Dailies(self)

    @cached_property
    def profile(self) -> Profile:
        """The user the client acts as: ``/api/v1/profile/...``."""
        return Profile(self)

    @cached_property
    def users(self) -> Users:
        """The users you can access, and managed users: ``/api/v1/users/...``."""
        return Users(self)

    @cached_property
    def teams(self) -> Teams:
        """Teams: ``/api/v1/teams/...``."""
        return Teams(self)

    @cached_property
    def portal(self) -> Portal:
        """The SweatStack Portal (beta): ``/api/v1/portal/...``."""
        return Portal(self)

    @cached_property
    def oauth(self) -> OAuth:
        """OAuth2 and OpenID Connect: ``/oauth/...`` and ``/api/v1/oauth/...``."""
        return OAuth(self)

    # -------------------------------------------------------------------------
    # Credentials
    # -------------------------------------------------------------------------

    def _load_token_pair(self) -> tuple[str | None, str | None]:
        """Load access and refresh tokens from available sources.

        Checks in order: instance, environment, persistent storage.

        Returns:
            Tuple of (access_token, refresh_token). Either or both may be None.
        """
        access_token: str | None = None
        refresh_token: str | None = None

        # Instance tokens take priority
        if self._api_key is not None:
            access_token = self._api_key.get_secret_value()
        if self._refresh_token is not None:
            refresh_token = self._refresh_token.get_secret_value()

        # Fill gaps from environment variables
        if access_token is None:
            access_token = os.getenv("SWEATSTACK_API_KEY")
        if refresh_token is None:
            refresh_token = os.getenv("SWEATSTACK_REFRESH_TOKEN")

        # Fill remaining gaps from persistent storage
        if access_token is None or refresh_token is None:
            stored_access, stored_refresh = self._load_persistent_tokens()
            if access_token is None:
                access_token = stored_access
            if refresh_token is None:
                refresh_token = stored_refresh

        return access_token, refresh_token

    def _do_token_refresh(self, refresh_token: str) -> str:
        """Exchange refresh token for a new access token.

        Raises:
            SweatStackTokenRefreshError: If the refresh request fails.
        """
        with self._http_client(skip_token_check=True) as client:
            response = client.post(
                "/api/v1/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self._client_secret.get_secret_value()
                    if self._client_secret
                    else None,
                },
            )

            try:
                self._raise_for_status(response)
            except SweatStackAPIError as e:
                raise SweatStackTokenRefreshError(f"Token refresh request failed: {e}") from e

            return response.json()["access_token"]

    def _refresh_if_expired(self, access_token: str, refresh_token: str | None) -> str:
        """Check token expiry and refresh if needed.

        Returns:
            Valid access token (original if not expired, refreshed otherwise).

        Raises:
            SweatStackTokenRefreshError: If the token is expired and refresh fails.
        """
        if not _is_expired(access_token):
            return access_token

        if refresh_token is None:
            raise SweatStackTokenRefreshError(
                "Access token expired but no refresh token available. "
                "Call client.authenticate(force=True) to re-authenticate."
            )

        # One refresh at a time per client: threads sharing a client would otherwise all refresh,
        # and with rotating refresh tokens all but the first would fail.
        with self.__dict__.setdefault("_refresh_lock", threading.Lock()):
            current = self._api_key.get_secret_value() if self._api_key else None
            if current is not None and current != access_token and not _is_expired(current):
                return current  # another thread refreshed while this one waited
            new_access_token = self._do_token_refresh(refresh_token)
            self._api_key = SecretStr(new_access_token)
            self._save_tokens(new_access_token, refresh_token)
        logger.debug("Refreshed and persisted access token")
        return new_access_token

    @property
    def api_key(self) -> SecretStr | None:
        """The current API access token.

        Loads from instance, environment (SWEATSTACK_API_KEY), or persistent
        storage. Automatically refreshes expired tokens.

        Returns:
            SecretStr containing the access token, or None if not authenticated.

        Raises:
            SweatStackTokenRefreshError: If the token is expired and refresh fails.
        """
        access_token, refresh_token = self._load_token_pair()

        if access_token is None:
            return None

        if self.skip_token_expiry_check:
            return SecretStr(access_token)

        valid_token = self._refresh_if_expired(access_token, refresh_token)
        return SecretStr(valid_token)

    @api_key.setter
    def api_key(self, value: str | SecretStr | None):
        self._api_key = _to_secret(value)

    @property
    def refresh_token(self) -> SecretStr | None:
        """The refresh token used for automatic token renewal.

        Loads from instance, environment (SWEATSTACK_REFRESH_TOKEN), or persistent storage.

        Returns a SecretStr to prevent accidental logging of the token.
        Use .get_secret_value() to get the actual token string.
        """
        if self._refresh_token is not None:
            return self._refresh_token
        elif value := os.getenv("SWEATSTACK_REFRESH_TOKEN"):
            return SecretStr(value)
        else:
            _, value = self._load_persistent_tokens()
            return _to_secret(value)

    @refresh_token.setter
    def refresh_token(self, value: str | SecretStr | None):
        self._refresh_token = _to_secret(value)

    @property
    def client_secret(self) -> SecretStr | None:
        """The OAuth client secret for confidential clients.

        Returns a SecretStr to prevent accidental logging of the secret.
        Use .get_secret_value() to get the actual secret string.
        """
        return self._client_secret

    @client_secret.setter
    def client_secret(self, value: str | SecretStr | None):
        self._client_secret = _to_secret(value)

    @property
    def url(self) -> str:
        """The SweatStack instance URL: the constructor's ``url``, else ``SWEATSTACK_URL``,
        else production. A non-default instance usually needs its own ``client_id`` too.
        """
        if self._url is not None:
            return self._url

        if env_url := os.getenv("SWEATSTACK_URL"):
            return env_url

        return DEFAULT_URL

    @url.setter
    def url(self, value: str | None):
        self._url = value

    # -------------------------------------------------------------------------
    # Token storage
    # -------------------------------------------------------------------------

    def _get_token_file_path(self) -> Path:
        """Get the path to the token storage file."""
        return Path(user_data_dir("SweatStack", "SweatStack")) / "tokens.json"

    def _save_tokens(self, access_token: str, refresh_token: str | None) -> None:
        """Save tokens to the user data directory, readable by the user only."""
        token_file = self._get_token_file_path()
        token_file.parent.mkdir(parents=True, exist_ok=True)
        with open(token_file, "w") as f:
            json.dump({"access_token": access_token, "refresh_token": refresh_token}, f, indent=2)
        token_file.chmod(0o600)

    def _load_persistent_tokens(self) -> tuple[str | None, str | None]:
        """Load tokens from the user data directory."""
        token_file = self._get_token_file_path()

        if not token_file.exists():
            return None, None

        try:
            with open(token_file) as f:
                token_data = json.load(f)
            return token_data.get("access_token"), token_data.get("refresh_token")
        except (json.JSONDecodeError, FileNotFoundError, KeyError):
            return None, None

    # -------------------------------------------------------------------------
    # Signing in
    # -------------------------------------------------------------------------

    def authenticate(self, force: bool = False, persist: bool = True) -> None:
        """Signs the client in, opening the browser only when no saved credentials exist.

        Looks for credentials in order: this client, the ``SWEATSTACK_API_KEY`` and
        ``SWEATSTACK_REFRESH_TOKEN`` environment variables, then the tokens saved by an earlier
        sign-in on this machine. Opens the browser for a SweatStack sign-in only when none are
        found, or when ``force=True``.

        In headless environments, set the environment variables instead of calling this.

        Args:
            force: Sign in again even if credentials exist.
            persist: Save new tokens on this machine for later sessions.

        Raises:
            Exception: If the browser sign-in fails or times out.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            client.authenticate()            # opens the browser only if needed
            client.authenticate(force=True)  # sign in again, e.g. as another user
            ```
        """
        if not force:
            access_token, _ = self._load_token_pair()
            if access_token is not None:
                return

        self._open_browser_oauth(persist=persist)

    def _open_browser_oauth(self, persist: bool = True) -> None:
        """Sign in through the browser: PKCE, a local callback server, then the code exchange."""

        class AuthHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # silence the default request logging

            def do_GET(self):
                params = parse_qs(urlparse(self.path).query)
                self.server.code = params.get("code", [None])[0]  # ty: ignore[unresolved-attribute]  # stashed on the server for the caller
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(AUTH_SUCCESSFUL_RESPONSE.encode())
                self.server.server_close()

        code_verifier, code_challenge = self.oauth.generate_pkce_params()

        while True:
            port = random.randint(8000, 9000)
            try:
                server = HTTPServer(("localhost", port), AuthHandler)
                break
            except OSError:
                continue

        authorization_url = self.oauth.authorization_url(
            client_id=OAUTH2_CLIENT_ID,
            redirect_uri=f"http://localhost:{port}",
            code_challenge=code_challenge,
            scope="data:read data:write profile offline_access",
            prompt=None,
        )

        webbrowser.open(authorization_url)

        print(f"Waiting for authorization... (listening on port {port})")
        print(f"If not redirected, open the following URL in your browser: {authorization_url}")
        print("")

        server.timeout = 30
        try:
            server.handle_request()
        except TimeoutError:
            raise Exception(
                "SweatStack Python login timed out after 30 seconds. Please try again."
            ) from None

        code = getattr(server, "code", None)
        if code is None:
            raise Exception("SweatStack Python authentication failed. Please try again.")
        try:
            self.oauth.exchange_code(
                code, client_id=OAUTH2_CLIENT_ID, code_verifier=code_verifier, persist=persist
            )
        except Exception as e:
            raise Exception("SweatStack Python authentication failed. Please try again.") from e
        print("SweatStack Python authentication successful.")

    # -------------------------------------------------------------------------
    # Acting as another user
    # -------------------------------------------------------------------------

    def delegated_client(self, user: str | UserSummary, *, team_id: str | None = None) -> Client:
        """Returns a new client that acts as another user. This client is left unchanged.

        Endpoint: ``POST /api/v1/oauth/delegated-token``

        Args:
            user: The user's ID, or a UserSummary from ``client.users.list()`` or
                ``client.teams.users(team_id)``.
            team_id: Delegate through this team's access instead of a direct share.

        Returns:
            Client: A client acting as ``user``, with this client's settings.

        Raises:
            SweatStackAuthError: If you have no access to this user (or not via this team).
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            coach = Client()
            for athlete in coach.users.list(include_managed=False):
                athlete_client = coach.delegated_client(athlete)
                print(athlete.display_name, athlete_client.activities.latest())
            ```
        """
        body: dict[str, Any] = {"sub": user.id if isinstance(user, UserSummary) else user}
        if team_id is not None:
            body["team_id"] = team_id
        tokens = self._request("post", "/api/v1/oauth/delegated-token", json=body).json()
        return self._with_tokens(tokens)

    def principal_client(self) -> Client:
        """Returns a new client that acts as the signed-in user, also from a delegated client.

        Endpoint: ``GET /api/v1/oauth/principal-token``

        Returns:
            Client: A client acting as the principal user, with this client's settings.

        Raises:
            SweatStackAuthError: If the current token cannot resolve a principal (e.g. a
                delegated session that has expired).
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            athlete_client = client.delegated_client("usr_carla")
            coach_client = athlete_client.principal_client()
            ```
        """
        tokens = self._request("get", "/api/v1/oauth/principal-token").json()
        return self._with_tokens(tokens)

    def _with_tokens(self, tokens: dict[str, Any]) -> Client:
        """A new client with these tokens and this client's settings."""
        return self.__class__(
            api_key=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            url=self._url,
            streamlit_compatible=self.streamlit_compatible,
            client_id=self.client_id,
            client_secret=self._client_secret,
            output=self.output,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )

    def whoami(self) -> UserSummary:
        """Returns the user this client acts as.

        Reads the user ID from the access token and finds it among ``client.users.list()``, so
        it works on a principal and a delegated client alike and needs no ``profile`` scope
        (unlike ``client.oauth.userinfo()``).

        Returns:
            UserSummary: The user this client acts as.

        Raises:
            ValueError: If the client is not signed in, or the user cannot be found.
            SweatStackAPIError: If the API request fails.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            print(client.whoami().display_name)
            ```
        """
        user_id = self._get_user_id_from_token()
        for user in self.users.list():
            if user.id == user_id:
                return user
        raise ValueError(f"User {user_id} is not among the users this client can access")

    def _get_user_id_from_token(self) -> str:
        """The ``sub`` claim of the access token."""
        api_key = self.api_key
        if not api_key:
            raise ValueError("Not authenticated. Call client.authenticate() first.")
        try:
            user_id = decode_jwt_body(api_key.get_secret_value()).get("sub")
        except Exception as e:
            raise ValueError(f"Invalid authentication token: {e}") from e
        if not user_id:
            raise ValueError("Invalid authentication token: no user ID")
        return user_id

    # -------------------------------------------------------------------------
    # Local cache
    # -------------------------------------------------------------------------

    def _cache_enabled(self) -> bool:
        """Whether :func:`enable_cache` was called."""
        return _cache_config is not None

    def _log_cache_error(self, operation: str, error: Exception) -> None:
        """Log cache operation errors with context."""
        try:
            cache_dir = str(self._get_cache_dir())
        except Exception:
            cache_dir = "unknown"
        logger.warning(f"Failed to {operation} cache. Cache directory: {cache_dir}. Error: {error}")

    def _get_cache_dir(self) -> Path:
        """Get cache directory for current user."""
        user_id = self._get_user_id_from_token()

        if _cache_config and _cache_config.get("path"):
            cache_dir = Path(_cache_config["path"]) / user_id
        else:
            cache_dir = Path(user_cache_dir("SweatStack", "SweatStack")) / user_id

        cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        return cache_dir

    def _generate_cache_key(self, namespace: str, **params) -> str:
        """Generate a cache key for the given namespace and parameters."""
        normalized_params = {}

        for key, value in params.items():
            if value is None:
                continue
            elif isinstance(value, list):
                normalized_params[key] = sorted(
                    [v.value if hasattr(v, "value") else str(v) for v in value]
                )
            elif hasattr(value, "value"):
                normalized_params[key] = value.value
            elif isinstance(value, (date, datetime)):
                normalized_params[key] = value.isoformat()
            else:
                normalized_params[key] = str(value)

        cache_data = f"{namespace}:{json.dumps(normalized_params, sort_keys=True)}"
        return hashlib.sha256(cache_data.encode()).hexdigest()[:16]

    def _read_cache(self, namespace: str, cache_key: str) -> bytes | None:
        """Try to read cached data. Returns raw bytes or None."""
        try:
            cache_file = self._get_cache_dir() / f"{namespace}-{cache_key}.parquet"
            if cache_file.exists():
                return cache_file.read_bytes()
        except Exception as e:
            self._log_cache_error("read", e)
        return None

    def _write_cache(self, namespace: str, cache_key: str, content: bytes) -> None:
        """Write raw bytes to cache."""
        try:
            (self._get_cache_dir() / f"{namespace}-{cache_key}.parquet").write_bytes(content)
        except Exception as e:
            self._log_cache_error("write", e)

    def clear_cache(self) -> None:
        """Deletes everything :func:`sweatstack.enable_cache` cached for the current user.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            client.clear_cache()
            ```
        """
        try:
            cache_dir = self._get_cache_dir()
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
        except Exception as e:
            self._log_cache_error("clear", e)

    # -------------------------------------------------------------------------
    # Transport: the internal API the resources use
    # -------------------------------------------------------------------------

    def _pool(self) -> httpx.Client:
        """The client's connection pool, created on first use and kept for its lifetime.

        Rebuilt if ``url`` changes. Authorization is per request (see ``_http_client``), so the
        pool itself holds no credentials.
        """
        url = self.url
        built = self.__dict__.get("_pool_entry")
        if built is not None and built[0] == url:
            return built[1]
        pool = httpx.Client(
            base_url=url,
            headers={"User-Agent": f"python-sweatstack/{__version__}"},
            timeout=self.timeout,
        )
        self.__dict__["_pool_entry"] = (url, pool)
        if built is not None:
            built[1].close()
        return pool

    @contextlib.contextmanager
    def _http_client(
        self, skip_token_check: bool = False, *, auth: bool = True
    ) -> Iterator[_transport.Session]:
        """A request scope on the client's connection pool, with the right Authorization header.

        Transport-level errors (DNS, timeouts, connection refused) are re-raised as
        SweatStackConnectionError so consumers never see raw httpx types.

        Args:
            skip_token_check: Use the raw token without the expiry check (used during
                refresh, to avoid recursion).
            auth: If False, send no Authorization header and never load or refresh a token.
                For the token exchange, which authenticates with the app's own credentials in
                the body, so a user's bearer is never sent where it is not needed.
        """
        headers = httpx.Headers({"User-Agent": f"python-sweatstack/{__version__}"})
        if not auth:
            token = None
        elif skip_token_check:
            token = self._api_key
        else:
            token = self.api_key  # may refresh

        if token:
            headers["Authorization"] = f"Bearer {token.get_secret_value()}"

        try:
            yield _transport.Session(self._pool(), headers, self.timeout)
        except httpx.HTTPError as exc:
            raise SweatStackConnectionError(str(exc)) from exc

    def _request(
        self,
        method: Literal["get", "post", "put", "delete"],
        path: str,
        *,
        auth: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send one request, retrying when safe, and raise the typed exception for an error status.

        Every resource method that makes a single request goes through here. Retries follow
        ``_transport.wait_before_retry``: ``GET``, ``PUT`` and ``DELETE`` only, at most
        ``max_retries`` times and 30 s of waiting in total.
        """
        attempt = 0
        waited = 0.0
        while True:
            try:
                with self._http_client(auth=auth) as http:
                    response = getattr(http, method)(url=path, **kwargs)
            except SweatStackConnectionError as error:
                wait = _transport.wait_before_retry(method, attempt, self.max_retries, waited)
                if wait is None:
                    raise
                logger.debug(
                    "Retrying %s %s in %.1fs after %s (retry %d)",
                    method.upper(),
                    path,
                    wait,
                    error,
                    attempt + 1,
                )
            else:
                if method == "delete" and attempt > 0 and response.status_code == 404:
                    return response  # an earlier attempt deleted it; the response was lost
                wait = _transport.wait_before_retry(
                    method, attempt, self.max_retries, waited, response
                )
                if response.is_success or wait is None:
                    self._raise_for_status(response)
                    return response
                logger.debug(
                    "Retrying %s %s in %.1fs after HTTP %d, request ID %s (retry %d)",
                    method.upper(),
                    path,
                    wait,
                    response.status_code,
                    response.headers.get("x-request-id"),
                    attempt + 1,
                )
            time.sleep(wait)
            waited += wait
            attempt += 1

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_success:
            return

        status = response.status_code
        common: dict[str, Any] = dict(
            status_code=status,
            url=str(response.request.url),
            method=response.request.method,
            request_id=response.headers.get("x-request-id"),
            body=self._parse_error_body(response),
        )

        if status in (401, 403):
            raise SweatStackAuthError(**common)
        if status == 404:
            raise SweatStackNotFoundError(**common)
        if status == 429:
            retry_after = int(response.headers.get("retry-after", "0")) or None
            raise SweatStackRateLimitError(retry_after=retry_after, **common)
        if 400 <= status < 500:
            raise SweatStackBadRequestError(**common)
        if 500 <= status < 600:
            raise SweatStackServerError(**common)
        raise SweatStackAPIError(**common)

    @staticmethod
    def _parse_error_body(response: httpx.Response) -> dict | str | None:
        try:
            return response.json()
        except Exception:
            text = response.text
            return text if text else None

    def _enums_to_strings(self, values: list[Any]) -> list[str]:
        out = []
        for value in values:
            if isinstance(value, Sport):
                out.append(str(value))  # OST Sport -> canonical wire string
            elif isinstance(value, Enum):
                out.append(value.value)
            else:
                out.append(value)
        return out

    @staticmethod
    def _require_aware(value: datetime, param: str) -> datetime:
        """Guard a write timestamp: it must carry an explicit UTC offset.

        The API stores each timestamp as an absolute instant paired with its local offset,
        so it rejects naive datetimes with HTTP 422. Failing fast names the argument.

        Raises:
            ValueError: If ``value`` is timezone-naive.
        """
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError(
                f"{param} must be timezone-aware; got naive {value!r}. "
                f"Attach a zone, e.g. datetime(..., tzinfo=ZoneInfo('Europe/Amsterdam')) "
                f"or datetime.now(timezone.utc)."
            )
        return value

    def _read_frame(self, content: bytes, output: str | None) -> Any:
        """Every parquet response becomes a frame through here."""
        output = (
            _frames.resolve_output(output, self.output, allowed=_frames.PARQUET_OUTPUTS)
            or _frames.installed_frame_output()
        )
        if output == "bytes":
            return content
        if output == "arrow":
            return _frames.parquet_to_arrow(content)
        if output == "polars":
            return _frames.parquet_to_polars(content)
        df = _frames.parquet_to_pandas(content)
        if self.streamlit_compatible:
            df = make_dataframe_streamlit_compatible(df)
        return df

    def _frame_from_models(
        self,
        models: list,
        model: type,
        output: str | None,
        *,
        flatten: tuple[str, ...] = (),
    ) -> Any:
        """Every list-of-models response becomes a frame (or stays a list) through here."""
        output = (
            _frames.resolve_output(output, self.output, allowed=_frames.LIST_OUTPUTS) or "models"
        )
        if output == "models":
            return models
        if output == "arrow":
            return _frames.models_to_arrow(models, model)
        if output == "polars":
            return _frames.models_to_polars(models, model)
        df = _frames.models_to_pandas(models, model, flatten=flatten)
        if self.streamlit_compatible:
            df = make_dataframe_streamlit_compatible(df)
        return df


# -----------------------------------------------------------------------------
# The module-level interface: one shared client, for scripts and notebooks
# -----------------------------------------------------------------------------

_default_client = Client()

RESOURCES = tuple(
    sorted(name for name, obj in vars(Client).items() if isinstance(obj, cached_property))
)
"""The resource attributes of ``Client``, mirrored at module level (``sweatstack.activities``)."""


def _generate_singleton_methods() -> list[str]:
    """Expose every public ``Client`` method as a module-level function on the default client.

    Discovery is automatic, so ``sweatstack.authenticate()`` always reaches the same surface
    as ``Client().authenticate()``, with no hand-maintained list to drift.

    Returns:
        The sorted names of the generated functions. Fed into ``__all__``.
    """

    def create_singleton_method(method_name: str):
        bound_method = getattr(_default_client, method_name)

        @wraps(bound_method)
        def singleton_method(*args: Any, **kwargs: Any) -> Any:
            return bound_method(*args, **kwargs)

        singleton_method.__annotations__ = dict(getattr(Client, method_name).__annotations__)
        return singleton_method

    names = sorted(
        name for name, obj in getmembers(Client) if not name.startswith("_") and isfunction(obj)
    )
    for name in names:
        globals()[name] = create_singleton_method(name)
    return names


_SINGLETON_METHODS = _generate_singleton_methods()

for _name in RESOURCES:
    globals()[_name] = getattr(_default_client, _name)


# Public surface. Wildcard imports from this module are well-defined.
# Schemas are re-exported here (instead of from .schemas directly) so that
# `from sweatstack import TraceDetails` works alongside the singletons.
__all__ = sorted(
    [
        "Client",
        "enable_cache",
        "set_output",
        # Schemas / enums re-exported from .schemas — keep in sync with the
        # `from .schemas import (...)` block at the top of this file.
        "AccountStatusResponse",
        "ActivityDetails",
        "ActivitySummary",
        "ApplicationMemberRole",
        "AuthorizedTeamResponse",
        "BackfillStatus",
        "Capability",
        "CapabilityStatus",
        "DailyMeasure",
        "DailyResponse",
        "IssueStatus",
        "Marker",
        "Metric",
        "Modifier",
        "PortalDestination",
        "PortalSessionResponse",
        "Scope",
        "SourceError",
        "SourceResponse",
        "Sport",
        "StatusIssueCode",
        "StatusIssueResponse",
        "TeamResponse",
        "TestDetails",
        "TestResults",
        "TestSummary",
        "TokenResponse",
        "TraceDetails",
        "TraceResolution",
        "UserInfoResponse",
        "UserResponse",
        "UserSummary",
        *_SINGLETON_METHODS,
        *RESOURCES,
    ]
)
