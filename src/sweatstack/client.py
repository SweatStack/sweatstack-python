import base64
import contextlib
import json
import random
import hashlib
import logging
import os
import secrets
import shutil
import time
import urllib
import warnings
import webbrowser
from datetime import date, datetime
from enum import Enum
from functools import wraps
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.metadata import version
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Generator, get_type_hints, List, Literal

from pydantic import SecretStr
from urllib.parse import parse_qs, urlparse

import httpx
import pandas as pd
from platformdirs import user_cache_dir, user_data_dir

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
from .schemas import (
    ActivityDetails, ActivitySummary, ApplicationMemberRole, AuthorizedTeamResponse,
    BackfillStatus, DailyMeasure, DailyResponse,
    Marker, Metric, Scope, Sport,
    TeamResponse, TestDetails, TestResults, TestSummary, TokenResponse, TraceDetails,
    TraceResolution, UserInfoResponse, UserResponse, UserSummary
)
from .utils import convert_to_standard_dtypes, decode_jwt_body, make_dataframe_streamlit_compatible

logger = logging.getLogger(__name__)

# Refresh tokens this many seconds before they expire to avoid race conditions
TOKEN_EXPIRY_MARGIN_SECONDS = 5

# Module-level cache configuration. None = caching disabled.
_cache_config: dict | None = None


def enable_cache(path: str | None = None) -> None:
    """Enable local caching of API responses.

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


class _LocalCacheMixin:
    """Mixin for handling local filesystem caching of API responses.

    Caching is enabled by calling :func:`sweatstack.enable_cache`.
    Use :meth:`clear_cache` to remove all cached data for the current user.
    """

    def _cache_enabled(self) -> bool:
        """Check if local caching is enabled."""
        return _cache_config is not None

    def _log_cache_error(self, operation: str, error: Exception) -> None:
        """Log cache operation errors with context."""
        try:
            cache_dir = str(self._get_cache_dir())
        except Exception:
            cache_dir = "unknown"

        logging.warning(
            f"Failed to {operation} cache. "
            f"Cache directory: {cache_dir}. "
            f"Error: {error}"
        )

    def _get_user_id_from_token(self) -> str:
        """Extract user ID from the JWT token."""
        if not self.api_key:
            raise ValueError("Not authenticated. Please call authenticate() first.")

        try:
            jwt_body = decode_jwt_body(self.api_key.get_secret_value())
            user_id = jwt_body.get("sub")
            if not user_id:
                raise ValueError("Unable to extract user ID from token")
            return user_id
        except Exception as e:
            raise ValueError(f"Invalid authentication token: {e}")

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
                normalized_params[key] = sorted([
                    v.value if hasattr(v, 'value') else str(v) for v in value
                ])
            elif hasattr(value, 'value'):
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
            cache_dir = self._get_cache_dir()
            cache_file = cache_dir / f"{namespace}-{cache_key}.parquet"

            if cache_file.exists():
                return cache_file.read_bytes()
        except Exception as e:
            self._log_cache_error("read", e)

        return None

    def _write_cache(self, namespace: str, cache_key: str, content: bytes) -> None:
        """Write raw bytes to cache."""
        try:
            cache_dir = self._get_cache_dir()
            cache_file = cache_dir / f"{namespace}-{cache_key}.parquet"
            cache_file.write_bytes(content)
        except Exception as e:
            self._log_cache_error("write", e)

    def clear_cache(self) -> None:
        """Clear all cached data for the current user."""
        try:
            cache_dir = self._get_cache_dir()
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
        except Exception as e:
            self._log_cache_error("clear", e)


class _TokenStorageMixin:
    """Mixin for handling persistent token storage using platformdirs."""

    def _get_token_file_path(self) -> Path:
        """Get the path to the token storage file."""
        data_dir = user_data_dir("SweatStack", "SweatStack")
        return Path(data_dir) / "tokens.json"

    def _save_tokens(self, access_token: str, refresh_token: str) -> None:
        """Save tokens to the user data directory."""
        token_file = self._get_token_file_path()
        token_file.parent.mkdir(parents=True, exist_ok=True)

        token_data = {
            "access_token": access_token,
            "refresh_token": refresh_token
        }

        with open(token_file, "w") as f:
            json.dump(token_data, f, indent=2)

        # Set restrictive permissions (user read/write only)
        token_file.chmod(0o600)

    def _load_persistent_tokens(self) -> tuple[str | None, str | None]:
        """Load tokens from the user data directory."""
        token_file = self._get_token_file_path()

        if not token_file.exists():
            return None, None

        try:
            with open(token_file, "r") as f:
                token_data = json.load(f)
            return token_data.get("access_token"), token_data.get("refresh_token")
        except (json.JSONDecodeError, FileNotFoundError, KeyError):
            return None, None


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


class _OAuth2Mixin:
    """OAuth2 authentication methods for the Client class."""

    def generate_pkce_params(self) -> tuple[str, str]:
        """Generate PKCE parameters for OAuth2 authorization.

        This method generates a code verifier and its corresponding code challenge
        for use in the PKCE (Proof Key for Code Exchange) OAuth2 flow.

        Returns:
            tuple[str, str]: A tuple of (code_verifier, code_challenge)
        """
        code_verifier = secrets.token_urlsafe(32)
        code_challenge = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(code_challenge).rstrip(b"=").decode("ascii")
        return code_verifier, code_challenge

    def get_authorization_url(
        self,
        client_id: str,
        redirect_uri: str,
        code_challenge: str | None = None,
        scope: str = "data:read data:write profile",
        prompt: str | None = "none",
        state: str | None = None,
    ) -> str:
        """Generate OAuth2 authorization URL.

        Args:
            client_id: OAuth2 client ID
            redirect_uri: Redirect URI for OAuth callback
            code_challenge: Optional PKCE code challenge for enhanced security
            scope: OAuth2 scopes (default: "data:read data:write profile")
            prompt: OAuth2 prompt parameter (default: "none"). Set to None to omit.
            state: Optional state parameter for CSRF protection

        Returns:
            str: The authorization URL to redirect the user to
        """
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
        }
        if prompt is not None:
            params["prompt"] = prompt
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        if state:
            params["state"] = state

        base_url = self.url
        path = "/oauth/authorize"
        return urllib.parse.urljoin(base_url, path + "?" + urllib.parse.urlencode(params))

    def exchange_code_for_token(
        self,
        code: str,
        client_id: str,
        code_verifier: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
        persist: bool = True,
    ) -> TokenResponse:
        """Exchange authorization code for access and refresh tokens.

        This method exchanges an authorization code for tokens and automatically
        sets them on the client instance.

        Args:
            code: The authorization code received from the OAuth callback
            client_id: OAuth2 client ID
            code_verifier: PKCE code verifier (required if PKCE was used in authorization)
            client_secret: Client secret for standard OAuth2 flow
            redirect_uri: Redirect URI if required by the server
            persist: Whether to persist tokens to storage (default: True)

        Returns:
            TokenResponse: The token response containing access_token, refresh_token, etc.

        Raises:
            HTTPStatusError: If the token exchange fails
        """
        token_data = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
        }

        if code_verifier:
            token_data["code_verifier"] = code_verifier
        if client_secret:
            token_data["client_secret"] = client_secret
        if redirect_uri:
            token_data["redirect_uri"] = redirect_uri

        try:
            response = httpx.post(
                f"{self.url}/api/v1/oauth/token",
                data=token_data,
            )
        except httpx.HTTPError as exc:
            raise SweatStackConnectionError(str(exc)) from exc

        self._raise_for_status(response)

        token_response = TokenResponse.model_validate(response.json())

        self.api_key = token_response.access_token
        self.refresh_token = token_response.refresh_token

        if persist:
            self._save_tokens(token_response.access_token, token_response.refresh_token)

        return token_response

    def _open_browser_oauth(self, persist: bool = True) -> None:
        """Open browser for OAuth authentication flow.

        Starts a local HTTP server to receive the OAuth callback, opens a browser
        for user authentication, and exchanges the authorization code for tokens.

        Args:
            persist: Save tokens to persistent storage after successful auth.
        """
        class AuthHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                # This override disables logging.
                pass

            def do_GET(self):
                query = urlparse(self.path).query
                params = parse_qs(query)
                
                self.server.code = params.get("code", [None])[0]
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(AUTH_SUCCESSFUL_RESPONSE.encode())
                self.server.server_close()

        code_verifier, code_challenge = self.generate_pkce_params()

        while True:
            port = random.randint(8000, 9000)
            try:
                server = HTTPServer(("localhost", port), AuthHandler)
                break
            except OSError:
                continue

        redirect_uri = f"http://localhost:{port}"

        authorization_url = self.get_authorization_url(
            client_id=OAUTH2_CLIENT_ID,
            redirect_uri=redirect_uri,
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
            raise Exception("SweatStack Python login timed out after 30 seconds. Please try again.")

        if hasattr(server, "code"):
            try:
                self.exchange_code_for_token(
                    code=server.code,
                    client_id=OAUTH2_CLIENT_ID,
                    code_verifier=code_verifier,
                    persist=persist,
                )
                print("SweatStack Python authentication successful.")
            except Exception as e:
                raise Exception("SweatStack Python authentication failed. Please try again.") from e
        else:
            raise Exception("SweatStack Python authentication failed. Please try again.")

    def authenticate(self, force: bool = False, persist: bool = True) -> None:
        """Ensure the client is authenticated.

        Checks for existing tokens in order: instance, environment variables,
        persistent storage. Opens browser for OAuth only if no tokens are found
        or if force=True.

        For headless environments, set SWEATSTACK_API_KEY and SWEATSTACK_REFRESH_TOKEN
        environment variables instead of calling this method.

        Args:
            force: Re-authenticate even if tokens exist.
            persist: Save new tokens to persistent storage (default: True).

        Raises:
            Exception: If the browser-based authentication fails.

        Example:
            client = Client()
            client.authenticate()  # Opens browser only if needed

            # Force fresh authentication
            client.authenticate(force=True)

            # Headless: use env vars, don't call authenticate()
            # SWEATSTACK_API_KEY=... SWEATSTACK_REFRESH_TOKEN=... python script.py
        """
        if not force:
            access_token, _ = self._load_token_pair()
            if access_token is not None:
                return

        self._open_browser_oauth(persist=persist)


class _DelegationMixin:
    """User delegation methods for accessing data on behalf of other users."""

    def _validate_user(self, user: str | UserSummary):
        if isinstance(user, UserSummary):
            return user.id
        else:
            return user

    def _get_delegated_token(self, user: str | UserSummary, *, team_id: str | None = None):
        user_id = self._validate_user(user)
        body = {"sub": user_id}
        if team_id is not None:
            body["team_id"] = team_id
        with self._http_client() as client:
            response = client.post(
                "/api/v1/oauth/delegated-token",
                json=body,
            )
            self._raise_for_status(response)

        return response.json()

    def _is_user_id(self, user: str) -> bool:
        """Check if a string is a valid user ID.

        Supports both legacy 16-character IDs and 26-character ULIDs.

        Args:
            user: The string to check.

        Returns:
            bool: True if the string is a valid user ID format, False otherwise.
        """
        if not isinstance(user, str):
            return False

        return len(user) in (16, 26) and user.isalnum()

    def _find_user_by_name(self, name: str, users: list) -> UserSummary:
        """Find a user by name from a list of users.

        Args:
            name: The (partial) display name to search for.
            users: The list of UserSummary objects to search.

        Returns:
            UserSummary: The matching user.

        Raises:
            ValueError: If no match or multiple matches found.
        """
        matches = [u for u in users if name in u.display_name.lower()]

        if len(matches) == 0:
            raise ValueError(f"User with name {name} not found")
        elif len(matches) > 1:
            raise ValueError(f"Multiple users found with name {name}: {', '.join([u.display_name for u in matches])}")
        return matches[0]

    def _find_user_by_id(self, id: str, users: list) -> UserSummary:
        """Find a user by ID from a list of users.

        Args:
            id: The user ID to search for.
            users: The list of UserSummary objects to search.

        Returns:
            UserSummary: The matching user, or None if not found.
        """
        return next((u for u in users if u.id == id), None)

    def _find_user(self, user: str, users: list, search_mode: Literal["auto", "id", "name"] = "auto") -> UserSummary:
        """Find a user by ID or name from a list of users.

        Args:
            user: User ID or (part of) display name.
            users: The list of UserSummary objects to search.
            search_mode: "auto" (detect), "id", or "name".

        Returns:
            UserSummary: The matching user.
        """
        if search_mode == "auto":
            if self._is_user_id(user):
                return self._find_user_by_id(user, users)
            else:
                return self._find_user_by_name(user, users)
        elif search_mode == "id":
            return self._find_user_by_id(user, users)
        elif search_mode == "name":
            return self._find_user_by_name(user, users)

    def get_user(self, user: str, *, search_mode: Literal["auto", "id", "name"] = "auto") -> UserSummary:
        """Get a user by ID or name.
        This method will always authenticate as the principal user.

        Args:
            user: User ID or (part of) display name.
            search_mode: "auto" (detect), "id", or "name".

        Returns:
            UserSummary: The user object.

        Raises:
            ValueError: If no match or multiple matches found.
        """
        client = self.principal_client()
        users = client.get_users()
        return client._find_user(user, users, search_mode)

    def switch_user(
        self,
        user: str | UserSummary,
        *,
        team_id: str | None = None,
        search_mode: Literal["auto", "id", "name"] = "auto",
    ):
        """Switches the client to operate on behalf of another user.

        This method changes the current client's authentication to act on behalf of the specified user.
        The client will use a delegated token for all subsequent API calls.

        Args:
            user: Either a UserSummary object or a string representing the user id or (part of) the user name to switch to.

            team_id: Optional team ID. When provided, delegates via team membership
                instead of direct user permissions.

            search_mode:
                The mode to use when searching for the user.
                - "auto": Automatically determine the search mode based on the type of user argument.
                - "id": Search for the user by ID.
                - "name": Search for the user by name.

        Returns:
            None

        Raises:
            HTTPStatusError: If the delegation request fails.
        """
        self.switch_back()

        if not isinstance(user, UserSummary):
            user = self.get_user(user, search_mode=search_mode)

        token_response = self._get_delegated_token(user, team_id=team_id)
        self.api_key = token_response["access_token"]
        self.refresh_token = token_response["refresh_token"]

    def _get_principal_token(self):
        with self._http_client() as client:
            response = client.get(
                "/api/v1/oauth/principal-token",
            )
            self._raise_for_status(response)
        return response.json()

    def switch_back(self):
        """Switches the client back to the principal user.

        This method reverts the client's authentication from a delegated user back to the principal user.
        The client will use the principal token for all subsequent API calls.

        Returns:
            None

        Raises:
            HTTPStatusError: If the principal token request fails.
        """

        token_response = self._get_principal_token()
        self.api_key = token_response["access_token"]
        self.refresh_token = token_response["refresh_token"]

    def delegated_client(self, user: str | UserSummary, *, team_id: str | None = None):
        """Creates a new client instance that operates on behalf of another user.

        This method creates a new client instance with delegated authentication for the specified user.
        Unlike `switch_user`, this method does not modify the current client but returns a new one.

        Args:
            user: Either a UserSummary object or a string user ID representing the user to delegate to.
            team_id: Optional team ID. When provided, delegates via team membership
                instead of direct user permissions.

        Returns:
            Client: A new client instance authenticated as the delegated user.

        Raises:
            HTTPStatusError: If the delegation request fails.
        """
        token_response = self._get_delegated_token(user, team_id=team_id)
        return self.__class__(
            api_key=token_response["access_token"],
            refresh_token=token_response["refresh_token"],
            url=self.url,
            streamlit_compatible=self.streamlit_compatible,
        )

    def principal_client(self):
        """Creates a new client instance that operates as the principal user.

        This method creates a new client instance with authentication for the principal user.
        Unlike `switch_back`, this method does not modify the current client but returns a new one.

        Returns:
            Client: A new client instance authenticated as the principal user.

        Raises:
            HTTPStatusError: If the principal token request fails.
        """
        token_response = self._get_principal_token()
        return self.__class__(
            api_key=token_response["access_token"],
            refresh_token=token_response["refresh_token"],
            url=self.url,
            streamlit_compatible=self.streamlit_compatible,
        )


class Client(_OAuth2Mixin, _DelegationMixin, _TokenStorageMixin, _LocalCacheMixin):
    """SweatStack API client for accessing activities, traces, and user data.

    The Client handles authentication, API requests, and data retrieval from SweatStack.
    You can initialize it with credentials or use authenticate()/login() for OAuth2.

    Example:
        client = Client()
        client.authenticate()
        activities = client.get_activities(limit=10)
    """

    def __init__(
        self,
        api_key: str | SecretStr | None = None,
        refresh_token: str | SecretStr | None = None,
        url: str | None = None,
        streamlit_compatible: bool = False,
        client_id: str | None = None,
        client_secret: str | SecretStr | None = None,
        skip_token_expiry_check: bool = False,
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
        """
        self._api_key: SecretStr | None = _to_secret(api_key)
        self._refresh_token: SecretStr | None = _to_secret(refresh_token)
        self._client_secret: SecretStr | None = _to_secret(client_secret)
        self.url = url
        self.streamlit_compatible = streamlit_compatible
        self.skip_token_expiry_check = skip_token_expiry_check
        self.client_id = client_id or OAUTH2_CLIENT_ID

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

    def _do_token_refresh(self, tz: str, refresh_token: str) -> str:
        """Exchange refresh token for a new access token.

        Args:
            tz: Timezone from the expired token's JWT claims.
            refresh_token: The refresh token to use.

        Returns:
            New access token string.

        Raises:
            SweatStackTokenRefreshError: If the refresh request fails.
        """
        with self._http_client(skip_token_check=True) as client:
            response = client.post(
                "/api/v1/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "tz": tz,
                    "client_id": self.client_id,
                    "client_secret": self._client_secret.get_secret_value() if self._client_secret else None,
                },
            )

            try:
                self._raise_for_status(response)
            except SweatStackAPIError as e:
                raise SweatStackTokenRefreshError(f"Token refresh request failed: {e}") from e

            return response.json()["access_token"]

    def _refresh_if_expired(self, access_token: str, refresh_token: str | None) -> str:
        """Check token expiry and refresh if needed.

        Args:
            access_token: The current access token (JWT).
            refresh_token: The refresh token, if available.

        Returns:
            Valid access token (original if not expired, refreshed otherwise).

        Raises:
            SweatStackTokenRefreshError: If the token is expired and refresh fails.
        """
        try:
            payload = decode_jwt_body(access_token)
        except Exception as e:
            raise SweatStackTokenRefreshError(f"Invalid access token: {e}") from e

        expires_at = payload.get("exp")
        if expires_at is None:
            raise SweatStackTokenRefreshError("Access token missing 'exp' claim")

        is_expired = expires_at - TOKEN_EXPIRY_MARGIN_SECONDS < time.time()
        if not is_expired:
            return access_token

        # Token needs refresh
        if refresh_token is None:
            raise SweatStackTokenRefreshError(
                "Access token expired but no refresh token available. "
                "Call client.authenticate(force=True) to re-authenticate."
            )

        tz = payload.get("tz", "UTC")
        new_access_token = self._do_token_refresh(tz, refresh_token)

        # Update instance state
        self._api_key = SecretStr(new_access_token)

        # Persist refreshed token
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
    def jwt(self) -> SecretStr | None:
        """Alias for api_key (backward compatibility)."""
        return self.api_key

    @jwt.setter
    def jwt(self, value: str | SecretStr | None):
        self.api_key = value

    @property
    def url(self) -> str:
        """
        This determines which SweatStack URL to use, allowing the use of a non-default instance.
        This is useful for example during local development.
        Please note that changing the url probably requires changing the `OAUTH2_CLIENT_ID` as well.
        """
        if self._url is not None:
            return self._url
        
        if env_url := os.getenv("SWEATSTACK_URL"):
            return env_url
            
        return DEFAULT_URL
    
    @url.setter
    def url(self, value: str):
        self._url = value
    
    @contextlib.contextmanager
    def _http_client(self, skip_token_check: bool = False):
        """
        Creates an httpx client with the base URL and authentication headers pre-configured.

        Transport-level errors (DNS, timeouts, connection refused) are caught and
        re-raised as SweatStackConnectionError so consumers never see raw httpx types.

        Args:
            skip_token_check: If True, uses the raw _api_key without triggering token expiry check.
                              This prevents recursive token refresh attempts.
        """
        headers = {
            "User-Agent": f"python-sweatstack/{__version__}",
        }
        if skip_token_check:
            # Use raw token without triggering expiry check (used during refresh)
            token = self._api_key
        else:
            # Normal path: may trigger token refresh
            token = self.api_key

        if token:
            headers["Authorization"] = f"Bearer {token.get_secret_value()}"

        try:
            with httpx.Client(base_url=self.url, headers=headers, timeout=60) as client:
                yield client
        except httpx.HTTPError as exc:
            raise SweatStackConnectionError(str(exc)) from exc

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_success:
            return

        status = response.status_code
        body = self._parse_error_body(response)
        request_id = response.headers.get("x-request-id")
        common = dict(
            status_code=status,
            url=str(response.request.url),
            method=response.request.method,
            request_id=request_id,
            body=body,
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

    def _enums_to_strings(self, values: list[Enum | str]) -> list[str]:
        return [value.value if isinstance(value, Enum) else value for value in values]

    def _get_activities_generator(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        sports: list[Sport | str] | None = None,
        tags: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Generator[ActivitySummary, None, None]:
        num_returned = 0
        default_limit = 100
        params = {
            "limit": default_limit,
            "offset": offset,
        }
        if start is not None:
            params["start"] = start.isoformat()
        if end is not None:
            params["end"] = end.isoformat()
        if sports is not None:
            params["sport"] = self._enums_to_strings(sports)
        if tags is not None:
            params["tags"] = tags

        with self._http_client() as client:
            while True:
                response = client.get(
                    url="/api/v1/activities/",
                    params=params,
                )
                self._raise_for_status(response)
                activities = response.json()
                for activity in activities:
                    yield ActivitySummary.model_validate(activity)

                    num_returned += 1
                    if num_returned >= limit:
                        return
                if len(activities) < default_limit:
                    return

                params["limit"] = min(default_limit, limit - num_returned)
                params["offset"] += default_limit

    def _postprocess_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Post-process DataFrame returned from API.

        Converts optimized dtypes (Int16, float16, etc.) to standard dtypes
        (float64) for ease of use, and optionally converts enums to strings
        for Streamlit compatibility.
        """
        df = convert_to_standard_dtypes(df)
        if self.streamlit_compatible:
            df = make_dataframe_streamlit_compatible(df)
        return df

    def _create_empty_dataframe_from_model(self, model_class, normalize_columns: list[str] | None = None) -> pd.DataFrame:
        """Create an empty DataFrame with proper schema from a Pydantic model.

        Args:
            model_class: The Pydantic model class to extract schema from
            normalize_columns: Optional list of columns to normalize (expand nested fields)

        Returns:
            pd.DataFrame: Empty DataFrame with columns matching the model schema
        """
        # Create a dummy instance with all None values to get the structure
        fields = model_class.model_fields
        dummy_data = {}
        for field_name, field_info in fields.items():
            dummy_data[field_name] = None

        # Create a single-row DataFrame then drop the row to preserve schema
        df = pd.DataFrame([dummy_data])

        # Normalize specified columns if requested
        if normalize_columns:
            for column in normalize_columns:
                if column in df.columns:
                    # Create empty normalized columns
                    normalized = pd.DataFrame()
                    df = pd.concat([df.drop(column, axis=1), normalized], axis=1)

        # Drop the dummy row to create empty DataFrame
        df = df.iloc[0:0]

        return df

    def get_activities(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        sports: list[Sport | str] | None = None,
        tags: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
        as_dataframe: bool = False,
    ) -> list[ActivitySummary] | pd.DataFrame:
        """Gets a list of activities based on specified filters.

        Args:
            start: Optional start date to filter activities.
            end: Optional end date to filter activities.
            sports: Optional list of sports to filter activities by. Can be Sport objects or string IDs.
            tags: Optional list of tags to filter activities by.
            limit: Maximum number of activities to return. Defaults to 100.
            offset: Number of activities to skip. Defaults to 0.
            as_dataframe: Whether to return results as a pandas DataFrame. Defaults to False.

        Returns:
            Either a list of ActivitySummary objects or a pandas DataFrame containing
            the activities data, depending on the value of as_dataframe.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        activities = list(self._get_activities_generator(
            start=start,
            end=end,
            sports=sports,
            tags=tags,
            limit=limit,
            offset=offset,
        ))
        if as_dataframe:
            if not activities:
                # Return empty DataFrame with proper schema
                df = self._create_empty_dataframe_from_model(
                    ActivitySummary,
                    normalize_columns=["summary", "laps", "traces"]
                )
            else:
                df = pd.DataFrame([activity.model_dump() for activity in activities])
                df = self._normalize_dataframe_column(df, "summary")
                df = self._normalize_dataframe_column(df, "laps")
                df = self._normalize_dataframe_column(df, "traces")
            return self._postprocess_dataframe(df)
        else:
            return activities

    def get_latest_activity(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
        tag: str | None = None,
    ) -> ActivityDetails:
        """Gets the most recent activity based on specified filters.

        Args:
            start: Optional start date to filter activities.
            end: Optional end date to filter activities.
            sport: Optional sport to filter activities by. Can be a Sport object or string ID.
            tag: Optional tag to filter activities by.

        Returns:
            ActivityDetails: The most recent activity matching the filters.

        Raises:
            StopIteration: If no activities match the filters.
            HTTPStatusError: If the API request fails.
        """
        return next(self._get_activities_generator(
            start=start,
            end=end,
            sports=[sport] if sport is not None else None,
            tags=[tag] if tag is not None else None,
            limit=1,
        ))

    def get_activity(self, activity_id: str) -> ActivityDetails:
        """Gets details for a specific activity by ID.

        Args:
            activity_id: The unique identifier of the activity to retrieve.

        Returns:
            ActivityDetails: The activity details object containing all information about the activity.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        with self._http_client() as client:
            response = client.get(url=f"/api/v1/activities/{activity_id}")
            self._raise_for_status(response)
            return ActivityDetails.model_validate(response.json())

    def get_activity_data(
        self,
        activity_id: str,
        adaptive_sampling_on: Literal["power", "speed"] | None = None,
        metrics: list[Metric | str] | None = None,
    ) -> pd.DataFrame:
        """Gets the raw data for a specific activity.

        This method retrieves the time-series data for a given activity, with optional
        adaptive sampling to reduce data points for visualization.

        Args:
            activity_id: The unique identifier of the activity.
            adaptive_sampling_on: Optional parameter to apply adaptive sampling on 
                either "power" or "speed" data. If None, no adaptive sampling is applied.
            metrics: Optional list of metrics to include in the results. Can be a list of Metric enums or strings.

        Returns:
            pd.DataFrame: A pandas DataFrame containing the activity's time-series data.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        params = {}
        if adaptive_sampling_on is not None:
            params["adaptive_sampling_on"] = adaptive_sampling_on
        if metrics is not None:
            params["metrics"] = self._enums_to_strings(metrics)

        with self._http_client() as client:
            response = client.get(
                url=f"/api/v1/activities/{activity_id}/data",
                params=params,
            )
            self._raise_for_status(response)

        df = pd.read_parquet(BytesIO(response.content))
        return self._postprocess_dataframe(df)

    def get_activity_mean_max(
        self,
        activity_id: str,
        metric: Literal[Metric.power, Metric.speed] | Literal["power", "speed"],
        adaptive_sampling: bool = False,
    ) -> pd.DataFrame:
        """Gets the mean-max data for a specific activity.

        This method retrieves the mean-max curve data for a given activity, which represents
        the maximum average value of a metric (power or speed) for different time durations.

        Args:
            activity_id: The unique identifier of the activity.
            metric: The metric to calculate mean-max values for, either "power" or "speed".
            adaptive_sampling: Whether to apply adaptive sampling to reduce data points
                for visualization. Defaults to False.

        Returns:
            pd.DataFrame: A pandas DataFrame containing the mean-max curve data.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        metric = self._enums_to_strings([metric])[0]
        with self._http_client() as client:
            response = client.get(
                url=f"/api/v1/activities/{activity_id}/mean-max",
                params={
                    "metric": metric,
                    "adaptive_sampling": adaptive_sampling,
                },
            )
            self._raise_for_status(response)
            df = pd.read_parquet(BytesIO(response.content))
            return self._postprocess_dataframe(df)

    def get_activity_awd(
        self,
        activity_id: str,
        metric: Literal[Metric.power, Metric.speed] | Literal["power", "speed"] | None = None,
    ) -> pd.DataFrame:
        """Gets the accumulated work duration (AWD) for a specific activity.

        This method retrieves accumulated work duration metrics for a specific activity.
        AWD represents the total duration spent at each intensity level by sorting
        activity data by intensity.

        Args:
            activity_id: The unique identifier of the activity.
            metric: Optional metric type. Defaults to power for cycling, speed for other sports.
                Can be either "power" or "speed".

        Returns:
            pd.DataFrame: A pandas DataFrame containing the AWD data.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        params = {}
        if metric is not None:
            params["metric"] = self._enums_to_strings([metric])[0]

        with self._http_client() as client:
            response = client.get(
                url=f"/api/v1/activities/{activity_id}/accumulated-work-duration",
                params=params,
            )
            self._raise_for_status(response)
            df = pd.read_parquet(BytesIO(response.content))
            return self._postprocess_dataframe(df)

    def get_latest_activity_data(
        self,
        sport: Sport | str | None = None,
        adaptive_sampling_on: Literal["power", "speed"] | None = None,
        metrics: list[Metric | str] | None = None,
    ) -> pd.DataFrame:
        """Gets the data for the latest activity of a specific sport.

        This method retrieves the time series data for the most recent activity of the specified sport.
        If no sport is specified, it returns data for the latest activity regardless of sport.

        Args:
            sport: Optional sport to filter by. Can be a Sport enum or string.
            adaptive_sampling_on: Optional metric to apply adaptive sampling for visualization.
                Can be either "power" or "speed". Defaults to None.
            metrics: Optional list of metrics to include in the results. Can be a list of Metric enums or strings.

        Returns:
            pd.DataFrame: A pandas DataFrame containing the activity data.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        activity = self.get_latest_activity(sport=sport)
        return self.get_activity_data(activity.id, adaptive_sampling_on, metrics=metrics)

    def get_latest_activity_mean_max(
        self,
        metric: Literal[Metric.power, Metric.speed] | Literal["power", "speed"],
        sport: Sport | str | None = None,
        adaptive_sampling: bool = False,
    ) -> pd.DataFrame:
        """Gets the mean-max curve for the latest activity of a specific sport.

        This method retrieves the mean-max curve data for the most recent activity of the specified sport.
        If no sport is specified, it returns data for the latest activity regardless of sport.

        Args:
            metric: The metric to calculate the mean-max curve for. Can be either "power" or "speed".
            sport: Optional sport to filter by. Can be a Sport enum or string.
            adaptive_sampling: Whether to apply adaptive sampling to the mean-max curve data.
                Defaults to False.

        Returns:
            pd.DataFrame: A pandas DataFrame containing the mean-max curve data.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        activity = self.get_latest_activity(sport=sport)
        return self.get_activity_mean_max(activity.id, metric, adaptive_sampling)

    def get_longitudinal_data(
        self,
        *,
        sports: list[Sport | str] | None = None,
        sport: Sport | str | None = None,
        start: date | str,
        end: date | str | None = None,
        metrics: list[Metric | str] | None = None,
        adaptive_sampling_on: Literal[Metric.power, Metric.speed] | Literal["power", "speed"] | None = None,
    ) -> pd.DataFrame:
        """Gets longitudinal data for activities within a specified date range.

        This method retrieves aggregated data for activities that match the specified criteria,
        including sport type and date range. The data is returned as a pandas DataFrame.

        Args:
            sports: Optional list of sports to filter by. Can be a list of Sport enums or strings.
            sport: Deprecated. Use ``sports`` instead.
            start: The start date for the data range. Can be a date object or string in ISO format.
            end: Optional end date for the data range. Can be a date object or string in ISO format.
            metrics: Optional list of metrics to include in the results. Can be a list of Metric enums or strings.
            adaptive_sampling_on: Optional metric to apply adaptive sampling for visualization.
                Can be either "power" or "speed". Defaults to None.

        Returns:
            pd.DataFrame: A pandas DataFrame containing the longitudinal activity data.

        Raises:
            ValueError: If both 'sport' and 'sports' parameters are provided.
            HTTPStatusError: If the API request fails.
        """
        if sport is not None and sports is not None:
            raise ValueError("Cannot specify both 'sport' and 'sports'.")
        if sport is not None:
            warnings.warn(
                "'sport' is deprecated, use 'sports' instead",
                DeprecationWarning,
                stacklevel=2,
            )
            sports = [sport]
        resolved = sports if sports is not None else []

        params = {
            "sport": self._enums_to_strings(resolved),
            "start": start
        }
        if end is not None:
            params["end"] = end
        if metrics is not None:
            params["metrics"] = self._enums_to_strings(metrics)
        if adaptive_sampling_on is not None:
            params["adaptive_sampling_on"] = self._enums_to_strings([adaptive_sampling_on])[0]

        if self._cache_enabled():
            cache_key = self._generate_cache_key("longitudinal_data", **params)
            cached = self._read_cache("longitudinal_data", cache_key)
            if cached is not None:
                return self._postprocess_dataframe(pd.read_parquet(BytesIO(cached)))

        with self._http_client() as client:
            response = client.get(
                url="/api/v1/activities/longitudinal-data",
                params=params,
            )
            self._raise_for_status(response)

            if self._cache_enabled():
                self._write_cache("longitudinal_data", cache_key, response.content)

            df = pd.read_parquet(BytesIO(response.content))

        return self._postprocess_dataframe(df)

    def get_longitudinal_mean_max(
        self,
        *,
        sports: list[Sport | str] | None = None,
        sport: Sport | str | None = None,
        metric: Literal[Metric.power, Metric.speed] | Literal["power", "speed"],
        start: date | str | None = None,
        end: date | str | None = None,
        date: date | str | None = None,
        window_days: int | None = None,
    ) -> pd.DataFrame:
        """Gets the mean-max curve for one or more sports and a metric.

        Args:
            sports: List of sports to get mean-max data for. Can be Sport enums or strings.
            sport: Deprecated. Use ``sports`` instead.
            metric: The metric to calculate mean-max for. Must be either "power" or "speed".
            start: Start of the date range.
            end: End of the date range (defaults to today).
            date: Deprecated since 0.70.0. Use ``start`` and ``end`` instead.
            window_days: Deprecated since 0.70.0. Use ``start`` and ``end`` instead.

        Returns:
            pd.DataFrame: A pandas DataFrame containing the mean-max curve data.

        Raises:
            ValueError: If both ``sport`` and ``sports`` are provided, or neither is provided.
            HTTPStatusError: If the API request fails.
        """
        if sport is not None and sports is not None:
            raise ValueError("Cannot specify both 'sport' and 'sports'.")
        if sport is not None:
            warnings.warn(
                "'sport' is deprecated, use 'sports' instead",
                DeprecationWarning,
                stacklevel=2,
            )
            sports = [sport]
        if sports is None:
            raise ValueError("'sports' is required.")
        metric = self._enums_to_strings([metric])[0]

        params = {
            "sport": self._enums_to_strings(sports),
            "metric": metric,
        }
        if start is not None:
            params["start"] = start
            if end is not None:
                params["end"] = end
        else:
            if date is not None or window_days is not None:
                warnings.warn(
                    "'date' and 'window_days' are deprecated, use 'start' and 'end' instead",
                    DeprecationWarning,
                    stacklevel=2,
                )
            if date is not None:
                params["date"] = date
            if window_days is not None:
                params["window_days"] = window_days

        if self._cache_enabled():
            cache_key = self._generate_cache_key("mean_max", **params)
            cached = self._read_cache("mean_max", cache_key)
            if cached is not None:
                return self._postprocess_dataframe(pd.read_parquet(BytesIO(cached)))

        with self._http_client() as client:
            response = client.get(
                url="/api/v1/activities/longitudinal-mean-max",
                params=params,
            )
            self._raise_for_status(response)

            if self._cache_enabled():
                self._write_cache("mean_max", cache_key, response.content)

            df = pd.read_parquet(BytesIO(response.content))
            return self._postprocess_dataframe(df)

    def get_longitudinal_awd(
        self,
        *,
        sports: list[Sport | str] | None = None,
        sport: Sport | str | None = None,
        metric: Literal[Metric.power, Metric.speed] | Literal["power", "speed"],
        start: date | str | None = None,
        end: date | str | None = None,
        date: date | str | None = None,
        window_days: int | None = None,
    ) -> pd.DataFrame:
        """Gets the longitudinal accumulated work duration (AWD) for one or more sports.

        This method retrieves AWD values across four intensity levels: max (highest daily AWD),
        hard, medium, and easy (sustainable durations for respective workout intensities).

        Note: This endpoint is in development and subject to change.

        Args:
            sports: List of sports to get AWD data for. Can be Sport enums or strings.
            sport: Deprecated. Use ``sports`` instead.
            metric: The metric to calculate AWD for. Must be either "power" or "speed".
            start: Start of the date range.
            end: End of the date range (defaults to today).
            date: Deprecated since 0.70.0. Use ``start`` and ``end`` instead.
            window_days: Deprecated since 0.70.0. Use ``start`` and ``end`` instead.

        Returns:
            pd.DataFrame: A pandas DataFrame containing the longitudinal AWD data with intensity levels.

        Raises:
            ValueError: If both ``sport`` and ``sports`` are provided, or neither is provided.
            HTTPStatusError: If the API request fails.
        """
        if sport is not None and sports is not None:
            raise ValueError("Cannot specify both 'sport' and 'sports'.")
        if sport is not None:
            warnings.warn(
                "'sport' is deprecated, use 'sports' instead",
                DeprecationWarning,
                stacklevel=2,
            )
            sports = [sport]
        if sports is None:
            raise ValueError("'sports' is required.")
        metric = self._enums_to_strings([metric])[0]

        params = {
            "sport": self._enums_to_strings(sports),
            "metric": metric,
        }
        if start is not None:
            params["start"] = start
            if end is not None:
                params["end"] = end
        else:
            if date is not None or window_days is not None:
                warnings.warn(
                    "'date' and 'window_days' are deprecated, use 'start' and 'end' instead",
                    DeprecationWarning,
                    stacklevel=2,
                )
            if date is not None:
                params["date"] = date
            if window_days is not None:
                params["window_days"] = window_days

        with self._http_client() as client:
            response = client.get(
                url="/api/v1/activities/longitudinal-accumulated-work-duration",
                params=params,
            )
            self._raise_for_status(response)
            df = pd.read_parquet(BytesIO(response.content))
            return self._postprocess_dataframe(df)

    def _get_traces_generator(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        sports: list[Sport | str] | None = None,
        tags: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Generator[TraceDetails, None, None]:
        num_returned = 0
        default_limit = 100
        params = {
            "limit": default_limit,
            "offset": offset,
        }
        if start is not None:
            params["start"] = start.isoformat()
        if end is not None:
            params["end"] = end.isoformat()
        if sports is not None:
            params["sport"] = self._enums_to_strings(sports)
        if tags is not None:
            params["tags"] = tags

        with self._http_client() as client:
            while True:
                response = client.get(
                    url="/api/v1/traces/",
                    params=params,
                )
                self._raise_for_status(response)
                traces = response.json()
                for trace in traces:
                    yield TraceDetails.model_validate(trace)

                    num_returned += 1
                    if num_returned >= limit:
                        return
                if len(traces) < default_limit:
                    return

                params["limit"] = min(default_limit, limit - num_returned)
                params["offset"] += default_limit

    def _prepare_unserialized_data(self, df: pd.DataFrame, column: str) -> pd.DataFrame:
        """
        pd.json_normalize() only likes to play with lists of records (dicts?), not lists of lists.
        So that's what we're feeding it.
        """
        unserialized_data = df[column].tolist()
        if column in ["laps", "traces"]:
            result = []
            for sublist in unserialized_data:
                if sublist:
                    dict_from_sublist = {i: value for i, value in enumerate(sublist) if sublist}
                else:
                    dict_from_sublist = {}
                result.append(dict_from_sublist)

            unserialized_data = result

        return unserialized_data

    def _normalize_dataframe_column(self, df: pd.DataFrame, column: str) -> pd.DataFrame:
        normalized = pd.json_normalize(
            self._prepare_unserialized_data(df, column),
        )
        normalized = normalized.add_prefix(f"{column}.")
        normalized.index = df.index
        if column == "activity":
            normalized = normalized.drop(["activity.traces", "activity.laps"], axis=1, errors="ignore")
        return pd.concat([df.drop(column, axis=1), normalized], axis=1)

    def get_traces(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        sports: list[Sport | str] | None = None,
        tags: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
        as_dataframe: bool = False,
    ) -> list[TraceDetails] | pd.DataFrame:
        """Gets a list of traces based on specified filters.

        Args:
            start: Optional start date to filter traces.
            end: Optional end date to filter traces.
            sports: Optional list of sports to filter traces by. Can be Sport objects or string IDs.
            tags: Optional list of tags to filter traces by.
            limit: Maximum number of traces to return. Defaults to 100.
            offset: Number of traces to skip. Defaults to 0.
            as_dataframe: Whether to return results as a pandas DataFrame. Defaults to False.

        Returns:
            Either a list of TraceDetails objects or a pandas DataFrame containing
            the traces data, depending on the value of as_dataframe.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        traces = list(self._get_traces_generator(
            start=start,
            end=end,
            sports=sports,
            tags=tags,
            limit=limit,
            offset=offset,
        ))
        if not as_dataframe:
            return traces

        data = pd.DataFrame([trace.model_dump() for trace in traces])

        if "activity" in data.columns:
            data = self._normalize_dataframe_column(data, "activity")

        if "lap" in data.columns:
            data = self._normalize_dataframe_column(data, "lap")

        return self._postprocess_dataframe(data)

    def create_trace(
        self,
        *,
        timestamp: datetime,
        lactate: float | None = None,
        rpe: int | None = None,
        notes: str | None = None,
        power: int | None = None,
        speed: float | None = None,
        heart_rate: int | None = None,
        tags: list[str] | None = None,
        sport: Sport | str | None = None,
        test_id: str | None = None,
    ) -> TraceDetails:
        """Creates a new trace with the specified parameters.

        This method creates a new trace entry with the given timestamp and optional
        measurement values.

        Args:
            timestamp: The date and time when the trace was recorded.
            lactate: Optional blood lactate concentration in mmol/L.
            rpe: Optional rating of perceived exertion (typically on a scale of 1-10).
            notes: Optional text notes associated with this trace.
            power: Optional power measurement in watts.
            speed: Optional speed measurement in meters per second.
            heart_rate: Optional heart rate measurement in beats per minute.
            tags: Optional list of tags to associate with this trace.
            sport: Optional sport to associate with this trace.
            test_id: Optional ID of a test to explicitly link this trace to.
                The link is independent of timestamp — a linked trace appears
                in the test's traces list regardless of whether its timestamp
                falls inside the test window.

        Returns:
            TraceDetails: The created trace object with all details.

        Raises:
            SweatStackNotFoundError: If ``test_id`` references a test that
                does not exist.
            SweatStackAPIError: If the API request fails for any other reason.
        """
        sport = self._enums_to_strings([sport])[0] if sport else None
        with self._http_client() as client:
            response = client.post(
                url="/api/v1/traces/",
                json={
                    "timestamp": timestamp.isoformat(),
                    "lactate": lactate,
                    "rpe": rpe,
                    "notes": notes,
                    "power": power,
                    "speed": speed,
                    "heart_rate": heart_rate,
                    "tags": tags,
                    "sport": sport,
                    "test_id": test_id,
                },
            )
            self._raise_for_status(response)
            return TraceDetails.model_validate(response.json())

    def update_trace(
        self,
        trace_id: str,
        *,
        timestamp: datetime,
        lactate: float | None = None,
        rpe: int | None = None,
        notes: str | None = None,
        power: int | None = None,
        speed: float | None = None,
        heart_rate: int | None = None,
        tags: list[str] | None = None,
        sport: Sport | str | None = None,
        test_id: str | None = None,
    ) -> None:
        """Updates a trace by replacing all fields.

        This is a full replace operation. Fields not provided will be set to null
        server-side. To modify a single field, first fetch the trace with
        ``get_traces()``, then pass all fields back.

        In particular: if the trace was previously linked to a test via
        ``test_id`` and you do not pass ``test_id`` here, the link is cleared.
        Pass the existing ``test_id`` back in to preserve it.

        Args:
            trace_id: The unique identifier of the trace to update.
            timestamp: The date and time when the trace was recorded.
            lactate: Optional blood lactate concentration in mmol/L.
            rpe: Optional rating of perceived exertion (typically on a scale of 1-10).
            notes: Optional text notes associated with this trace.
            power: Optional power measurement in watts.
            speed: Optional speed measurement in meters per second.
            heart_rate: Optional heart rate measurement in beats per minute.
            tags: Optional list of tags to associate with this trace.
            sport: Optional sport to associate with this trace.
            test_id: Optional ID of a test to explicitly link this trace to.
                Pass ``None`` (or omit) to leave the trace unlinked.

        Raises:
            SweatStackNotFoundError: If ``trace_id`` does not exist, or if
                ``test_id`` references a test that does not exist.
            SweatStackAPIError: If the API request fails for any other reason.
        """
        sport = self._enums_to_strings([sport])[0] if sport else None
        with self._http_client() as client:
            response = client.put(
                url=f"/api/v1/traces/{trace_id}",
                json={
                    "timestamp": timestamp.isoformat(),
                    "lactate": lactate,
                    "rpe": rpe,
                    "notes": notes,
                    "power": power,
                    "speed": speed,
                    "heart_rate": heart_rate,
                    "tags": tags,
                    "sport": sport,
                    "test_id": test_id,
                },
            )
            self._raise_for_status(response)

    def delete_trace(self, trace_id: str) -> None:
        """Deletes a trace.

        Args:
            trace_id: The unique identifier of the trace to delete.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        with self._http_client() as client:
            response = client.delete(url=f"/api/v1/traces/{trace_id}")
            self._raise_for_status(response)

    # -------------------------------------------------------------------------
    # Tests
    # -------------------------------------------------------------------------

    def _get_tests_generator(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        sports: list[Sport | str] | None = None,
        tags: list[str] | None = None,
        created_by: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Generator[TestSummary, None, None]:
        num_returned = 0
        default_limit = 50
        params = {
            "limit": default_limit,
            "offset": offset,
        }
        if start is not None:
            params["start"] = start.isoformat()
        if end is not None:
            params["end"] = end.isoformat()
        if sports is not None:
            params["sport"] = self._enums_to_strings(sports)
        if tags is not None:
            params["tags"] = tags
        if created_by is not None:
            params["created_by"] = created_by

        with self._http_client() as client:
            while True:
                response = client.get(
                    url="/api/v1/tests/",
                    params=params,
                )
                self._raise_for_status(response)
                tests = response.json()
                for test in tests:
                    yield TestSummary.model_validate(test)

                    num_returned += 1
                    if num_returned >= limit:
                        return
                if len(tests) < default_limit:
                    return

                params["limit"] = min(default_limit, limit - num_returned)
                params["offset"] += default_limit

    def get_tests(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        sports: list[Sport | str] | None = None,
        tags: list[str] | None = None,
        created_by: str | None = None,
        limit: int = 50,
        offset: int = 0,
        as_dataframe: bool = False,
    ) -> list[TestSummary] | pd.DataFrame:
        """Gets a list of tests based on specified filters.

        Args:
            start: Optional start date to filter tests.
            end: Optional end date to filter tests.
            sports: Optional list of sports to filter tests by. Can be Sport objects or string IDs.
            tags: Optional list of tags to filter tests by.
            created_by: Optional app ID to filter tests by creator.
            limit: Maximum number of tests to return. Defaults to 50.
            offset: Number of tests to skip. Defaults to 0.
            as_dataframe: Whether to return results as a pandas DataFrame. Defaults to False.

        Returns:
            Either a list of TestSummary objects or a pandas DataFrame containing
            the tests data, depending on the value of as_dataframe.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        tests = list(self._get_tests_generator(
            start=start,
            end=end,
            sports=sports,
            tags=tags,
            created_by=created_by,
            limit=limit,
            offset=offset,
        ))
        if as_dataframe:
            if not tests:
                df = self._create_empty_dataframe_from_model(
                    TestSummary,
                    normalize_columns=["results"]
                )
            else:
                df = pd.DataFrame([test.model_dump() for test in tests])
                if "results" in df.columns:
                    df = self._normalize_dataframe_column(df, "results")
            return self._postprocess_dataframe(df)
        else:
            return tests

    def get_test(
        self,
        test_id: str,
        *,
        trace_resolution: TraceResolution | str = TraceResolution.auto,
    ) -> TestDetails:
        """Gets details for a specific test by ID.

        Args:
            test_id: The unique identifier of the test to retrieve.
            trace_resolution: How traces are matched to this test. Affects only
                the ``traces`` list on the response; ``activities`` is always
                time-overlap matched. Accepts a ``TraceResolution`` enum or
                its string value (``"auto"`` or ``"linked"``).

                - ``"auto"`` (default): traces whose timestamp falls in the
                  test's time range, plus any traces explicitly linked to
                  this test, minus any traces explicitly linked to a
                  different test.
                - ``"linked"``: only traces explicitly linked to this test
                  via ``test_id``, regardless of timestamp.

                Maps to the ``traces`` query parameter on the wire.

        Returns:
            TestDetails: The test details including resolved traces and overlapping activities.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        resolution = self._enums_to_strings([trace_resolution])[0]
        params = {} if resolution == TraceResolution.auto.value else {"traces": resolution}
        with self._http_client() as client:
            response = client.get(url=f"/api/v1/tests/{test_id}", params=params)
            self._raise_for_status(response)
            return TestDetails.model_validate(response.json())

    def create_test(
        self,
        *,
        sport: Sport | str,
        start: datetime,
        title: str | None = None,
        end: datetime | None = None,
        results: TestResults | None = None,
        tags: list[str] | None = None,
    ) -> TestSummary:
        """Creates a new test.

        Args:
            sport: The sport for this test. Can be a Sport enum or string ID.
            start: The start time of the test.
            title: Optional title for the test.
            end: Optional end time. Defaults to start + 3 hours server-side.
            results: Optional structured test results (thresholds, capacities, etc.).
            tags: Optional list of tags to associate with this test.

        Returns:
            TestSummary: The created test.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        sport = self._enums_to_strings([sport])[0]
        with self._http_client() as client:
            response = client.post(
                url="/api/v1/tests/",
                json={
                    "title": title,
                    "sport": sport,
                    "start": start.isoformat(),
                    "end": end.isoformat() if end is not None else None,
                    "results": results.model_dump() if results is not None else None,
                    "tags": tags,
                },
            )
            self._raise_for_status(response)
            return TestSummary.model_validate(response.json())

    def update_test(
        self,
        test_id: str,
        *,
        sport: Sport | str,
        start: datetime,
        title: str | None = None,
        end: datetime | None = None,
        results: TestResults | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Updates a test by replacing all fields.

        This is a full replace operation. Fields not provided will be set to null
        server-side. To modify a single field, first fetch the test with
        ``get_test()``, then pass all fields back.

        Args:
            test_id: The unique identifier of the test to update.
            sport: The sport for this test. Can be a Sport enum or string ID.
            start: The start time of the test.
            title: Optional title for the test.
            end: Optional end time. Defaults to start + 3 hours server-side.
            results: Optional structured test results (thresholds, capacities, etc.).
            tags: Optional list of tags to associate with this test.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        sport = self._enums_to_strings([sport])[0]
        with self._http_client() as client:
            response = client.put(
                url=f"/api/v1/tests/{test_id}",
                json={
                    "title": title,
                    "sport": sport,
                    "start": start.isoformat(),
                    "end": end.isoformat() if end is not None else None,
                    "results": results.model_dump() if results is not None else None,
                    "tags": tags,
                },
            )
            self._raise_for_status(response)

    def delete_test(self, test_id: str) -> None:
        """Deletes a test.

        Args:
            test_id: The unique identifier of the test to delete.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        with self._http_client() as client:
            response = client.delete(url=f"/api/v1/tests/{test_id}")
            self._raise_for_status(response)

    # -------------------------------------------------------------------------
    # Dailies (daily health metrics)
    # -------------------------------------------------------------------------

    def get_dailies(
        self,
        measure: DailyMeasure | str,
        *,
        start: date,
        end: date,
        interpolate: bool = True,
        as_dataframe: bool = False,
    ) -> list[DailyResponse] | pd.DataFrame:
        """Gets daily values for a measure over a date range.

        Args:
            measure: The daily measure to retrieve (e.g. DailyMeasure.body_mass).
            start: Start date (inclusive).
            end: End date (inclusive).
            interpolate: Whether to apply server-side estimation/interpolation.
                Defaults to True. When False, missing dates return value=None
                with source="missing".
            as_dataframe: Whether to return results as a pandas DataFrame.
                Defaults to False.

        Returns:
            Either a list of DailyResponse objects or a pandas DataFrame with
            date as index. Always returns one entry per date in the range.
        """
        measure_str = measure.value if isinstance(measure, Enum) else measure
        with self._http_client() as client:
            response = client.get(
                url=f"/api/v1/dailies/{measure_str}",
                params={
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "interpolate": interpolate,
                },
            )
            self._raise_for_status(response)
            dailies = [DailyResponse.model_validate(item) for item in response.json()]
        if as_dataframe:
            if not dailies:
                df = pd.DataFrame(columns=["date", "value", "source"])
                df = df.set_index("date")
            else:
                df = pd.DataFrame([d.model_dump() for d in dailies])
                df = df.set_index("date")
            return self._postprocess_dataframe(df)
        return dailies

    def set_daily(
        self,
        measure: DailyMeasure | str,
        *,
        date: date,
        value: float,
    ) -> DailyResponse:
        """Sets a daily value (creates or updates).

        Args:
            measure: The daily measure (e.g. DailyMeasure.body_mass).
            date: The date for the measurement.
            value: The measurement value.

        Returns:
            DailyResponse: The created/updated daily entry.
        """
        measure_str = measure.value if isinstance(measure, Enum) else measure
        with self._http_client() as client:
            response = client.post(
                url=f"/api/v1/dailies/{measure_str}",
                json={"date": date.isoformat(), "value": value},
            )
            self._raise_for_status(response)
            return DailyResponse.model_validate(response.json())

    def delete_daily(
        self,
        measure: DailyMeasure | str,
        *,
        date: date,
    ) -> None:
        """Deletes a daily value.

        Args:
            measure: The daily measure to delete.
            date: The date of the entry to delete.

        Raises:
            HTTPStatusError: 404 if entry does not exist.
        """
        measure_str = measure.value if isinstance(measure, Enum) else measure
        with self._http_client() as client:
            response = client.delete(
                url=f"/api/v1/dailies/{measure_str}",
                params={"date": date.isoformat()},
            )
            self._raise_for_status(response)

    # -------------------------------------------------------------------------
    # App Metadata
    # -------------------------------------------------------------------------

    def _set_app_metadata(self, path: str, data: dict) -> None:
        with self._http_client() as client:
            response = client.put(url=path, json=data)
            self._raise_for_status(response)

    def _delete_app_metadata(self, path: str) -> None:
        with self._http_client() as client:
            response = client.delete(url=path)
            self._raise_for_status(response)

    def set_activity_app_metadata(self, activity_id: str, *, data: dict) -> None:
        """Sets app metadata on an activity (requires app token).

        Replaces the entire metadata dict for this app on the given activity.

        Args:
            activity_id: The activity to attach metadata to.
            data: Arbitrary JSON-serializable dict (max 1KB, max nesting depth 32).

        Raises:
            HTTPStatusError: 403 if not using an app token, 413 if over size limit.
        """
        self._set_app_metadata(f"/api/v1/activities/{activity_id}/app-metadata", data)

    def delete_activity_app_metadata(self, activity_id: str) -> None:
        """Deletes app metadata from an activity (requires app token).

        Args:
            activity_id: The activity to remove metadata from.

        Raises:
            HTTPStatusError: 403 if not using an app token.
        """
        self._delete_app_metadata(f"/api/v1/activities/{activity_id}/app-metadata")

    def set_trace_app_metadata(self, trace_id: str, *, data: dict) -> None:
        """Sets app metadata on a trace (requires app token).

        Replaces the entire metadata dict for this app on the given trace.

        Args:
            trace_id: The trace to attach metadata to.
            data: Arbitrary JSON-serializable dict (max 1KB, max nesting depth 32).

        Raises:
            HTTPStatusError: 403 if not using an app token, 413 if over size limit.
        """
        self._set_app_metadata(f"/api/v1/traces/{trace_id}/app-metadata", data)

    def delete_trace_app_metadata(self, trace_id: str) -> None:
        """Deletes app metadata from a trace (requires app token).

        Args:
            trace_id: The trace to remove metadata from.

        Raises:
            HTTPStatusError: 403 if not using an app token.
        """
        self._delete_app_metadata(f"/api/v1/traces/{trace_id}/app-metadata")

    def set_test_app_metadata(self, test_id: str, *, data: dict) -> None:
        """Sets app metadata on a test (requires app token).

        Replaces the entire metadata dict for this app on the given test.

        Args:
            test_id: The test to attach metadata to.
            data: Arbitrary JSON-serializable dict (max 1KB, max nesting depth 32).

        Raises:
            HTTPStatusError: 403 if not using an app token, 413 if over size limit.
        """
        self._set_app_metadata(f"/api/v1/tests/{test_id}/app-metadata", data)

    def delete_test_app_metadata(self, test_id: str) -> None:
        """Deletes app metadata from a test (requires app token).

        Args:
            test_id: The test to remove metadata from.

        Raises:
            HTTPStatusError: 403 if not using an app token.
        """
        self._delete_app_metadata(f"/api/v1/tests/{test_id}/app-metadata")

    def set_user_app_metadata(self, *, data: dict) -> None:
        """Sets app metadata on the authenticated user (requires app token).

        Replaces the entire metadata dict for this app on the current user.

        Args:
            data: Arbitrary JSON-serializable dict (max 4KB, max nesting depth 32).

        Raises:
            HTTPStatusError: 403 if not using an app token, 413 if over size limit.
        """
        self._set_app_metadata("/api/v1/profile/app-metadata", data)

    def delete_user_app_metadata(self) -> None:
        """Deletes app metadata from the authenticated user (requires app token).

        Raises:
            HTTPStatusError: 403 if not using an app token.
        """
        self._delete_app_metadata("/api/v1/profile/app-metadata")

    def get_sports(self, only_root: bool = False) -> list[Sport]:
        """Gets a list of available sports.

        This method retrieves all sports available to the user, with an option to only
        return root sports (top-level sports without parents).

        Args:
            only_root: If True, only returns root sports without parents. Defaults to False.

        Returns:
            list[Sport]: A list of Sport objects representing the available sports.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        with self._http_client() as client:
            response = client.get(
                url="/api/v1/profile/sports/",
                params={"only_root": only_root},
            )
            self._raise_for_status(response)
            return [Sport(sport) for sport in response.json()]

    def get_tags(self) -> list[str]:
        """Gets a list of all tags used by the user.

        This method retrieves all tags that the user has created or used across
        their activities and traces.

        Returns:
            list[str]: A list of tag strings.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        with self._http_client() as client:
            response = client.get(
                url="/api/v1/profile/tags/",
            )
            self._raise_for_status(response)
            return response.json()

    def get_users(self) -> list[UserSummary]:
        """Gets a list of all users accessible to the current user.

        This method retrieves all users that the current user has access to view.
        For regular users, this typically returns only their own user information.
        For admin users, this may return information about multiple users.
        This method will always authenticate as the principal user.

        Returns:
            list[UserSummary]: A list of UserSummary objects containing basic user information.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        client = self.principal_client()
        with client._http_client() as client:
            response = client.get(
                url="/api/v1/users/",
            )
            self._raise_for_status(response)
            return [UserSummary.model_validate(user) for user in response.json()]

    def create_user(self, first_name: str, last_name: str | None = None) -> UserResponse:
        """Creates a managed user.

        Managed users have no login credentials — their data is controlled
        by the creating user via delegated tokens.

        Args:
            first_name: The user's first name.
            last_name: Optional last name.

        Returns:
            UserResponse: The created user.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        with self._http_client() as client:
            response = client.post(
                url="/api/v1/users/",
                json={"first_name": first_name, "last_name": last_name},
            )
            self._raise_for_status(response)
            return UserResponse.model_validate(response.json())

    def get_teams(self) -> list[TeamResponse]:
        """Lists all teams the current user owns or is a member of.

        Returns:
            list[TeamResponse]: Teams with the user's role (owner or member).

        Raises:
            HTTPStatusError: If the API request fails.
        """
        with self._http_client() as client:
            response = client.get(url="/api/v1/teams/")
            self._raise_for_status(response)
            return [TeamResponse.model_validate(team) for team in response.json()]

    def get_authorized_teams(self) -> list[AuthorizedTeamResponse]:
        """Lists all teams the current user has authorized to access their data.

        Returns:
            list[AuthorizedTeamResponse]: Teams with their granted scopes.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        with self._http_client() as client:
            response = client.get(url="/api/v1/teams/authorized")
            self._raise_for_status(response)
            return [AuthorizedTeamResponse.model_validate(team) for team in response.json()]

    def get_team_users(self, team_id: str) -> list[UserSummary]:
        """Lists all users who have authorized a team to access their data.

        Only accessible to members of the team.

        Args:
            team_id: The team's ID.

        Returns:
            list[UserSummary]: Users who have authorized the team, with their granted scopes.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        with self._http_client() as client:
            response = client.get(
                url=f"/api/v1/teams/{team_id}/users",
            )
            self._raise_for_status(response)
            return [UserSummary.model_validate(user) for user in response.json()]

    def get_team_user(
        self,
        *,
        team_id: str,
        user: str,
        search_mode: Literal["auto", "id", "name"] = "auto",
    ) -> UserSummary:
        """Get a team-authorized user by ID or name.

        Args:
            team_id: The team's ID.
            user: User ID or (part of) display name.
            search_mode: "auto" (detect), "id", or "name".

        Returns:
            UserSummary: The matching user.

        Raises:
            ValueError: If no match or multiple matches found.
            HTTPStatusError: If the API request fails.
        """
        users = self.get_team_users(team_id)
        return self._find_user(user, users, search_mode)

    def authorize_team(self, team_id: str, scopes: list[Scope | str] | None = None):
        """Authorizes a team to access the current user's data.

        When called as a delegated user, authorizes the team for that user.

        Args:
            team_id: The team's ID.
            scopes: Scopes to grant. Defaults to ``[Scope.data_read]``.

        Returns:
            dict: Confirmation with team_id, user_id, and granted scopes.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        if scopes is None:
            scopes = [Scope.data_read]
        scopes = self._enums_to_strings(scopes)
        with self._http_client() as client:
            response = client.post(
                url=f"/api/v1/teams/{team_id}/authorize",
                json={"scopes": scopes},
            )
            self._raise_for_status(response)
            return response.json()

    def upload(
        self,
        files: str | Path | list[str | Path],
        *,
        sport: Sport | str | None = None,
    ):
        """Uploads activity files (CSV or FIT).

        CSV files require the ``sport`` parameter and must contain a ``timestamp``
        column with ISO 8601 datetimes.  FIT files include sport metadata so
        ``sport`` is optional for them.

        Args:
            files: A file path, or a list of file paths, to upload.
            sport: Sport for the activity. Required for CSV files.

        Returns:
            dict: Confirmation message.

        Raises:
            HTTPStatusError: If the API request fails.
            FileNotFoundError: If a file does not exist.
        """
        if isinstance(files, (str, Path)):
            files = [files]

        multipart_files = []
        opened = []
        try:
            for path in files:
                path = Path(path)
                f = path.open("rb")
                opened.append(f)
                multipart_files.append(("files", (path.name, f)))

            data = {}
            if sport is not None:
                data["sport"] = sport.value if isinstance(sport, Enum) else sport

            with self._http_client() as client:
                response = client.post(
                    url="/api/v1/activities/upload",
                    files=multipart_files,
                    data=data,
                )
                self._raise_for_status(response)
                return response.json()
        finally:
            for f in opened:
                f.close()

    def get_userinfo(self) -> UserInfoResponse:
        """Gets detailed information about the current user.

        This method retrieves comprehensive information about the user currently
        authenticated with the client.

        Returns:
            UserInfoResponse: A UserInfoResponse object containing detailed user information
                including profile data, permissions, and authentication details.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        with self._http_client() as client:
            response = client.get(
                url="/api/v1/oauth/userinfo",
            )
            self._raise_for_status(response)
            return UserInfoResponse.model_validate(response.json())

    def whoami(self) -> UserSummary:
        """Gets the authenticated user's summary information.

        This method retrieves basic information about the currently authenticated user
        by extracting the user ID from the JWT token and fetching the user details.

        Returns:
            UserSummary: A UserSummary object containing the authenticated user's information.

        Raises:
            ValueError: If no authentication token is available.
            HTTPStatusError: If the API request fails or user is not found.
        """
        if not self.api_key:
            raise ValueError("Not authenticated. Please call authenticate() or login() first.")

        try:
            jwt_body = decode_jwt_body(self.api_key.get_secret_value())
            user_id = jwt_body.get("sub")
            if not user_id:
                raise ValueError("Unable to extract user ID from token")
        except Exception as e:
            raise ValueError(f"Invalid authentication token: {e}")

        return self._get_user_by_id(user_id)

    def _parse_backfill_line(self, line: str) -> BackfillStatus | None:
        """Parse a single NDJSON line from backfill status stream."""
        try:
            return BackfillStatus.model_validate_json(line)
        except Exception:
            pass
        return None

    def watch_backfill_status(self, *, auto_reconnect: bool = False) -> Generator[BackfillStatus, None, None]:
        """Watches backfill status from the activities backfill-status endpoint.

        This method connects to the backfill status event stream and yields
        backfill_loaded_until timestamps as they are received. The connection
        automatically closes after 60 seconds, but can be configured to auto-reconnect.

        Args:
            auto_reconnect: Whether to automatically reconnect when the connection
                closes and continue receiving updates. Defaults to False.

        Yields:
            BackfillStatus: A BackfillStatus object for each received message.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        while True:
            try:
                with self._http_client() as client:
                    with client.stream("GET", "/api/v1/activities/backfill-status") as response:
                        self._raise_for_status(response)

                        for line in response.iter_lines():
                            if line.strip():
                                parsed = self._parse_backfill_line(line)
                                if parsed:
                                    yield parsed

            except httpx.RequestError:
                if not auto_reconnect:
                    raise
                time.sleep(1)
            if not auto_reconnect:
                break

    def get_backfill_status(self) -> BackfillStatus:
        """Gets the current backfill status from the activities backfill-status endpoint.

        This method connects to the backfill status event stream and returns
        the first backfill_loaded_until timestamp received.

        Returns:
            BackfillStatus: A BackfillStatus object containing the current backfill status.

        Raises:
            HTTPStatusError: If the API request fails.
            ValueError: If no status message is received.
        """
        for status in self.watch_backfill_status(auto_reconnect=False):
            return status
        raise ValueError("No backfill status received")


_default_client = Client()


def _generate_singleton_methods(method_names: List[str]) -> None:
    """
    Automatically generates singleton methods for the Client class.
    
    Args:
        method_names: List of method names to expose in the singleton interface
    """

    def create_singleton_method(method_name: str):
        bound_method = getattr(_default_client, method_name)

        @wraps(bound_method)
        def singleton_method(*args: Any, **kwargs: Any) -> Any:
            return bound_method(*args, **kwargs)

        class_method = getattr(Client, method_name)
        singleton_method.__annotations__ = get_type_hints(class_method)

        return singleton_method
    
    for method_name in method_names:
        if not hasattr(Client, method_name):
            raise ValueError(f"Method '{method_name}' not found in class {Client.__name__}")
            
        class_method = getattr(Client, method_name)
        
        if not callable(class_method):
            continue
            
        globals()[method_name] = create_singleton_method(method_name)


_generate_singleton_methods(
    [
        "authenticate",
        "get_authorization_url",
        "exchange_code_for_token",
        "generate_pkce_params",

        "get_user",
        "get_users",
        "create_user",
        "get_teams",
        "get_authorized_teams",
        "get_team_users",
        "get_team_user",
        "authorize_team",
        "get_userinfo",
        "whoami",

        "upload",

        "get_backfill_status",
        "watch_backfill_status",

        "get_activities",

        "get_activity",
        "get_activity_data",
        "get_activity_mean_max",
        "get_activity_awd",

        "get_latest_activity",
        "get_latest_activity_data",
        "get_latest_activity_mean_max",

        "get_longitudinal_data",
        "get_longitudinal_mean_max",
        "get_longitudinal_awd",

        "get_traces",
        "create_trace",

        "get_tests",
        "get_test",
        "create_test",
        "update_test",
        "delete_test",

        "get_dailies",
        "set_daily",
        "delete_daily",

        "set_activity_app_metadata",
        "delete_activity_app_metadata",
        "set_trace_app_metadata",
        "delete_trace_app_metadata",
        "set_test_app_metadata",
        "delete_test_app_metadata",
        "set_user_app_metadata",
        "delete_user_app_metadata",

        "get_sports",
        "get_tags",
        "clear_cache",

        "switch_user",
        "switch_back",
        "delegated_client",
        "principal_client",
    ]
)