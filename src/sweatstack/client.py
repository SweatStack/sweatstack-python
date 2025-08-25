import base64
import contextlib
import json
import random
import hashlib
import logging
import os
import secrets
import shutil
import tempfile
import time
import urllib
import webbrowser
from datetime import date, datetime
from enum import Enum
from functools import wraps
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.metadata import version
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Generator, get_type_hints, List, Literal
from urllib.parse import parse_qs, urlparse

import httpx
import pandas as pd
from platformdirs import user_data_dir

from .constants import DEFAULT_URL
from .schemas import (
    ActivityDetails, ActivitySummary, BackfillStatus, Metric, Sport,
    TraceDetails, UserInfoResponse, UserSummary
)
from .utils import decode_jwt_body, make_dataframe_streamlit_compatible


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


class LocalCacheMixin:
    """Mixin for handling local filesystem caching of API responses."""

    def _cache_enabled(self) -> bool:
        """Check if local caching is enabled."""
        return bool(os.getenv("SWEATSTACK_LOCAL_CACHE"))

    def _log_cache_error(self, operation: str, error: Exception) -> None:
        """Log cache operation errors with context."""
        cache_location = os.getenv("SWEATSTACK_CACHE_DIR") or tempfile.gettempdir()
        try:
            user_id = self._get_user_id_from_token()
        except Exception:
            user_id = "unknown"

        logging.warning(
            f"Failed to {operation} cache despite SWEATSTACK_LOCAL_CACHE being enabled. "
            f"Cache directory: {cache_location}/sweatstack/{user_id}. "
            f"Error: {error}"
        )

    def _get_user_id_from_token(self) -> str:
        """Extract user ID from the JWT token."""
        if not self.api_key:
            raise ValueError("Not authenticated. Please call authenticate() or login() first.")

        try:
            jwt_body = decode_jwt_body(self.api_key)
            user_id = jwt_body.get("sub")
            if not user_id:
                raise ValueError("Unable to extract user ID from token")
            return user_id
        except Exception as e:
            raise ValueError(f"Invalid authentication token: {e}")

    def _get_cache_dir(self) -> Path:
        """Get cache directory for current user."""
        user_id = self._get_user_id_from_token()

        if cache_location := os.getenv("SWEATSTACK_CACHE_DIR"):
            cache_dir = Path(cache_location) / user_id
        else:
            cache_dir = Path(tempfile.gettempdir()) / "sweatstack" / user_id

        cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        return cache_dir

    def _generate_longitudinal_cache_key(self, **params) -> str:
        """Generate cache key for longitudinal data requests."""
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

        cache_data = f"longitudinal_data:{json.dumps(normalized_params, sort_keys=True)}"
        return hashlib.sha256(cache_data.encode()).hexdigest()[:16]

    def _read_longitudinal_cache(self, cache_key: str) -> pd.DataFrame | None:
        """Try to read cached longitudinal data."""
        try:
            cache_dir = self._get_cache_dir()
            cache_file = cache_dir / f"longitudinal-{cache_key}.parquet"

            if cache_file.exists():
                return pd.read_parquet(cache_file)
        except Exception as e:
            self._log_cache_error("read", e)

        return None

    def _write_longitudinal_cache(self, cache_key: str, content: bytes) -> None:
        """Write longitudinal data to cache."""
        try:
            cache_dir = self._get_cache_dir()
            cache_file = cache_dir / f"longitudinal-{cache_key}.parquet"
            cache_file.write_bytes(content)
        except Exception as e:
            self._log_cache_error("write", e)

    def clear_cache(self) -> None:
        """Clear all cached data for the current user.

        This removes all cached data (longitudinal data, etc.) from the temporary
        directory for the currently authenticated user.
        """
        try:
            cache_dir = self._get_cache_dir()
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
        except Exception as e:
            self._log_cache_error("clear", e)


class TokenStorageMixin:
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


class OAuth2Mixin:
    def login(self, persist_api_key: bool = True):
        """Initiates the OAuth2 login flow for SweatStack authentication.

        This method starts a local HTTP server to receive the OAuth2 callback,
        opens a browser window for the user to authenticate with SweatStack,
        and exchanges the authorization code for an access token.

        The method uses PKCE (Proof Key for Code Exchange) for enhanced security
        during the OAuth2 authorization code flow.

        Args:
            persist_api_key: Whether to save the API key to persistent storage for future use.
                Defaults to True.

        Returns:
            None

        Raises:
            Exception: If the authentication process times out or fails.

        Note:
            This method requires a working internet connection and the ability
            to open a browser window. It will also temporarily open a local HTTP
            server on a random port between 8000-9000.
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

        code_verifier = secrets.token_urlsafe(32)
        code_challenge = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(code_challenge).rstrip(b"=").decode("ascii")

        while True:
            port = random.randint(8000, 9000)
            try:
                server = HTTPServer(("localhost", port), AuthHandler)
                break
            except OSError:
                continue

        redirect_uri = f"http://localhost:{port}"
        params = {
            "client_id": OAUTH2_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "scope": "data:read profile",
            "prompt": "none",
        }
        base_url = self.url
        path = "/oauth/authorize"
        authorization_url = urllib.parse.urljoin(base_url, path + "?" + urllib.parse.urlencode(params))
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
            token_data = {
                "grant_type": "authorization_code",
                "client_id": OAUTH2_CLIENT_ID,
                "code": server.code,
                "code_verifier": code_verifier,
            }
            response = httpx.post(
                f"{self.url}/api/v1/oauth/token",
                data=token_data,
            )
            try:
                self._raise_for_status(response)
            except httpx.HTTPStatusError as e:
                raise Exception(f"SweatStack Python login failed. Please try again.") from e
            token_response = response.json()

            self.jwt = token_response.get("access_token")
            self.api_key = self.jwt
            self.refresh_token = token_response.get("refresh_token")

            if persist_api_key:
                self._save_tokens(self.api_key, self.refresh_token)
            print(f"SweatStack Python login successful.")
        else:
            raise Exception("SweatStack Python login failed. Please try again.")

    def authenticate(self, *, persist_api_key: bool = True, force_login: bool = False) -> None:
        """Ensures the client is authenticated, either using existing tokens or by initiating login.

        This method checks for authentication in the following order:
        1. Current instance tokens (if already set)
        2. Environment variables (SWEATSTACK_API_KEY, SWEATSTACK_REFRESH_TOKEN)
        3. Persistent storage tokens
        4. If none found or force_login is True, initiates OAuth2 login flow

        Args:
            persist_api_key: Whether to save tokens to persistent storage after login.
                Defaults to True.
            force_login: Whether to force a new login even if tokens are available.
                Defaults to False.

        Returns:
            None

        Raises:
            Exception: If the authentication process fails.
        """
        if force_login:
            self.login(persist_api_key=persist_api_key)
            return

        # Check if we already have valid tokens
        if self.api_key:
            return

        # If no tokens available, initiate login
        self.login(persist_api_key=persist_api_key)


class DelegationMixin:
    def _validate_user(self, user: str | UserSummary):
        if isinstance(user, UserSummary):
            return user.id
        else:
            return user

    def _get_delegated_token(self, user: str | UserSummary):
        user_id = self._validate_user(user)
        with self._http_client() as client:
            response = client.post(
                "/api/v1/oauth/delegated-token",
                json={"sub": user_id},
            )
            self._raise_for_status(response)

        return response.json()

    def _is_user_id(self, user: str) -> bool:
        """Check if a string is a valid user ID.

        Args:
            user: The string to check.

        Returns:
            bool: True if the string is a valid user ID format, False otherwise.
        """
        if not isinstance(user, str):
            return False

        return len(user) == 16 and user.isalnum()

    def _get_user_by_name(self, name: str) -> UserSummary:
        """Get a user by name.

        Args:
            name: The name of the user to get.

        Returns:
            UserSummary: The user object.

        Raises:
            ValueError: If the user is not found.
            ValueError: If multiple users are found with the same name.
        """
        matches = []
        for user in self.get_users():
            if name in user.display_name.lower():
                matches.append(user)

        if len(matches) == 0:
            raise ValueError(f"User with name {name} not found")
        elif len(matches) > 1:
            raise ValueError(f"Multiple users found with name {name}: {', '.join([user.display_name for user in matches])}")
        return matches[0]

    def _get_user_by_id(self, id: str) -> UserSummary:
        """Get a user by ID.

        Args:
            id: The ID of the user to get.

        Returns:
            UserSummary: The user object.

        Raises:
            HTTPStatusError: If the user is not found.
        """
        # TODO: Implement this using a user detail endpoint
        return next((user for user in self.get_users() if user.id == id), None)

    def get_user(self, user: str, *, search_mode: Literal["auto", "id", "name"] = "auto") -> UserSummary:
        """Get a user by ID or name.
        This method will always authenticate as the principal user.

        Args:
            user: Either a UserSummary object or a string representing the user id or (part of) the user name to get.
            search_mode: The mode to use when searching for the user.
                - "auto": Automatically determine the search mode based on the type of user argument.
                - "id": Search for the user by ID.
                - "name": Search for the user by name.

        Returns:
            UserSummary: The user object.

        Raises:
            HTTPStatusError: If the user is not found.
        """
        client = self.principal_client()
        if search_mode == "auto":
            if client._is_user_id(user):
                return client._get_user_by_id(user)
            else:
                return client._get_user_by_name(user)
        elif search_mode == "id":
            return client._get_user_by_id(user)
        elif search_mode == "name":
            return client._get_user_by_name(user)

    def switch_user(
        self,
        user: str | UserSummary,
        *,
        search_mode: Literal["auto", "id", "name"] = "auto",
    ):
        """Switches the client to operate on behalf of another user.

        This method changes the current client's authentication to act on behalf of the specified user.
        The client will use a delegated token for all subsequent API calls.

        Args:
            user: Either a UserSummary object or a string representing the user id or (part of) the user name to switch to.

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

        token_response = self._get_delegated_token(user)
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

    def delegated_client(self, user: str | UserSummary):
        """Creates a new client instance that operates on behalf of another user.

        This method creates a new client instance with delegated authentication for the specified user.
        Unlike `switch_user`, this method does not modify the current client but returns a new one.

        Args:
            user: Either a UserSummary object or a string user ID representing the user to delegate to.

        Returns:
            Client: A new client instance authenticated as the delegated user.

        Raises:
            HTTPStatusError: If the delegation request fails.
        """
        token_response = self._get_delegated_token(user)
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


class Client(OAuth2Mixin, DelegationMixin, TokenStorageMixin, LocalCacheMixin):
    def __init__(
        self,
        api_key: str | None = None,
        refresh_token: str | None = None,
        url: str | None = None,
        streamlit_compatible: bool = False,
    ):
        self.api_key = api_key
        self.refresh_token = refresh_token
        self.url = url
        self.streamlit_compatible = streamlit_compatible

    def _do_token_refresh(self, tz: str) -> str:
        with self._http_client() as client:
            response = client.post(
                "/api/v1/oauth/token",
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "tz": tz,
                },
            )

            self._raise_for_status(response)
            return response.json()["access_token"]

    def _check_token_expiry(self, token: str) -> str:
        try:
            body = decode_jwt_body(token)
            # Margin in seconds to account for time to token validation of the next request
            TOKEN_EXPIRY_MARGIN = 5
            if body["exp"] - TOKEN_EXPIRY_MARGIN < time.time():
                # Token is (almost) expired, refresh it
                token = self._do_token_refresh(body["tz"])
                self._api_key = token
        except Exception:
            # If token can't be decoded, just return as-is
            # @TODO: This probably should be handled differently
            pass

        return token

    @property
    def api_key(self) -> str:
        if self._api_key is not None:
            value = self._api_key
        elif value := os.getenv("SWEATSTACK_API_KEY"):
            pass
        else:
            value, _ = self._load_persistent_tokens()

        if value is None:
            # A non-authenticated client is a potentially valid use-case.
            return None

        return self._check_token_expiry(value)

    @api_key.setter
    def api_key(self, value: str):
        self._api_key = value
    
    @property
    def refresh_token(self) -> str:
        if self._refresh_token is not None:
            return self._refresh_token
        elif value := os.getenv("SWEATSTACK_REFRESH_TOKEN"):
            pass
        else:
            _, value = self._load_persistent_tokens()

        return value

    @refresh_token.setter
    def refresh_token(self, value: str):
        self._refresh_token = value

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
    def _http_client(self):
        """
        Creates an httpx client with the base URL and authentication headers pre-configured.
        """
        headers = {
            "User-Agent": f"python-sweatstack/{__version__}",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        with httpx.Client(base_url=self.url, headers=headers) as client:
            yield client

    def _print_response_and_raise(self, response: httpx.Response):
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exception:
            additional_info = response.text
            exception.add_note(additional_info)
            raise exception

    def _raise_for_status(self, response: httpx.Response):
        if response.status_code == 422:
            raise ValueError(response.json())
        elif response.status_code == 401:
            try:
                import streamlit
            except ImportError:
                self._print_response_and_raise(response)
            else:
                try:
                    response.raise_for_status()
                except Exception as exception:
                    if not self.streamlit_compatible:
                        streamlit_error_message = (
                            "\nStreamlit environment detected. Use StreamlitAuth.client instance.\n"
                            "Docs: https://developer.sweatstack.no/learn/integrations/streamlit/"
                        )
                        exception.add_note(streamlit_error_message)
                    raise

        else:
            self._print_response_and_raise(response)

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
            params["sports"] = self._enums_to_strings(sports)
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
        if self.streamlit_compatible:
            return make_dataframe_streamlit_compatible(df)
        else:
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
        sport: Sport | str | None = None,
        sports: list[Sport | str] | None = None,
        start: date | str,
        end: date | str | None = None,
        metrics: list[Metric | str] | None = None,
        adaptive_sampling_on: Literal[Metric.power, Metric.speed] | Literal["power", "speed"] | None = None,
    ) -> pd.DataFrame:
        """Gets longitudinal data for activities within a specified date range.

        This method retrieves aggregated data for activities that match the specified criteria,
        including sport type and date range. The data is returned as a pandas DataFrame.

        Args:
            sport: Optional single sport to filter by. Can be a Sport enum or string.
                Cannot be used together with 'sports'.
            sports: Optional list of sports to filter by. Can be a list of Sport enums or strings.
                Cannot be used together with 'sport'.
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
        if sport and sports:
            raise ValueError("Cannot specify both sport and sports")
        if sport is not None:
            sports = [sport]
        elif sports is None:
            sports = []

        params = {
            "sports": self._enums_to_strings(sports),
            "start": start
        }
        if end is not None:
            params["end"] = end
        if metrics is not None:
            params["metrics"] = self._enums_to_strings(metrics)
        if adaptive_sampling_on is not None:
            params["adaptive_sampling_on"] = self._enums_to_strings([adaptive_sampling_on])[0]

        if self._cache_enabled():
            cache_key = self._generate_longitudinal_cache_key(**params)
            cached_df = self._read_longitudinal_cache(cache_key)
            if cached_df is not None:
                return self._postprocess_dataframe(cached_df)

        with self._http_client() as client:
            response = client.get(
                url="/api/v1/activities/longitudinal-data",
                params=params,
            )
            self._raise_for_status(response)

            if self._cache_enabled():
                self._write_longitudinal_cache(cache_key, response.content)

            df = pd.read_parquet(BytesIO(response.content))

        return self._postprocess_dataframe(df)

    def get_longitudinal_mean_max(
        self,
        *,
        sport: Sport | str,
        metric: Literal[Metric.power, Metric.speed] | Literal["power", "speed"],
        date: date | str | None = None,
        window_days: int | None = None,
    ) -> pd.DataFrame:
        """Gets the mean-max curve for a specific sport and metric.

        This method retrieves the mean-max curve data for a given sport and metric,
        optionally filtered by date and window size.

        Args:
            sport: The sport to get mean-max data for. Can be a Sport enum or string ID.
            metric: The metric to calculate mean-max for. Must be either "power" or "speed".
            date: Optional reference date for the mean-max calculation. If provided,
                the mean-max curve will be calculated up to this date. Can be a date object
                or string in ISO format.
            window_days: Optional number of days to include in the calculation window
                before the reference date. If None, all available data is used.

        Returns:
            pd.DataFrame: A pandas DataFrame containing the mean-max curve data.

        Raises:
            HTTPStatusError: If the API request fails.
        """
        sport = self._enums_to_strings([sport])[0]
        metric = self._enums_to_strings([metric])[0]

        params = {
            "sport": sport,
            "metric": metric,
        }
        if date is not None:
            params["date"] = date
        if window_days is not None:
            params["window_days"] = window_days

        with self._http_client() as client:
            response = client.get(
                url="/api/v1/activities/longitudinal-mean-max",
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
            params["sports"] = self._enums_to_strings(sports)
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

        Returns:
            TraceDetails: The created trace object with all details.

        Raises:
            HTTPStatusError: If the API request fails.
        """
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
                },
            )
            self._raise_for_status(response)
            return TraceDetails.model_validate(response.json())

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
            jwt_body = decode_jwt_body(self.api_key)
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
        "login",
        "authenticate",

        "get_user",
        "get_users",
        "get_userinfo",
        "whoami",

        "get_backfill_status",
        "watch_backfill_status",

        "get_activities",

        "get_activity",
        "get_activity_data",
        "get_activity_mean_max",

        "get_latest_activity",
        "get_latest_activity_data",
        "get_latest_activity_mean_max",

        "get_longitudinal_data",
        "get_longitudinal_mean_max",

        "get_traces",
        "create_trace",

        "get_sports",
        "get_tags",
        "clear_cache",

        "switch_user",
        "switch_back",
        "delegated_client",
        "principal_client",
    ]
)