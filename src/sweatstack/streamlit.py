"""Streamlit integration for SweatStack authentication and UI components.

This module provides authentication and UI helper components for building
Streamlit applications with SweatStack. The StreamlitAuth class handles
OAuth2 authentication flow and provides convenient selector components.

Example:
    import streamlit as st
    from sweatstack.streamlit import StreamlitAuth

    auth = StreamlitAuth(
        client_id="YOUR_APPLICATION_ID",
        client_secret="YOUR_APPLICATION_SECRET",
        redirect_uri="http://localhost:8501",
    )

    with st.sidebar:
        auth.authenticate()

    if not auth.is_authenticated():
        st.stop()

    st.write("Welcome!")
    latest = auth.client.activities.latest()
    st.write(f"Latest: {latest.sport}")
"""

import logging
import os
from collections.abc import Callable
from datetime import date

try:
    import streamlit as st
except ImportError:
    raise ImportError(
        "Streamlit features require streamlit to be installed. "
        "You can install it with:\n\n"
        "pip install 'sweatstack[streamlit]'\n\n"
    ) from None
import httpx
from pydantic import SecretStr

from . import _transport
from .client import Client
from .constants import DEFAULT_SCOPE, DEFAULT_URL
from .exceptions import SweatStackAuthError
from .resources.oauth import build_authorization_url
from .schemas import ActivitySummary, Metric, Scope, Sport, UserSummary
from .utils import decode_jwt_body

logger = logging.getLogger(__name__)

# A session's tokens live in ``st.session_state``: per session, in memory, never shared with
# another session, kept across reruns. Each client the integration builds holds one pair and
# writes a renewed pair back to the keys it came from, so a rerun starts from the renewed
# token and the token file on the server is never involved.
#
# The pair behind ``auth.client``: the signed-in user, or the selected user after ``select_user()``.
_ACCESS_KEY = "sweatstack_api_key"
_REFRESH_KEY = "sweatstack_refresh_token"
# The user's own pair in proxy mode, reconciled with the handshake headers on every rerun. Kept
# apart from the pair above so that a delegation never overwrites it.
_PROXY_ACCESS_KEY = "sweatstack_proxy_api_key"
_PROXY_REFRESH_KEY = "sweatstack_proxy_refresh_token"

_PROXY_NO_REFRESH_HINT = (
    "Reload the page, or have the proxy forward the refresh token as well "
    "(StreamlitAuth.behind_proxy reads X-SweatStack-Refresh-Token)."
)


def _secret_value(value: str | SecretStr | None) -> str | None:
    return value.get_secret_value() if isinstance(value, SecretStr) else value


def _expires_at(token: str | None) -> float:
    """The ``exp`` claim of an access token; 0 for no token or one that cannot be read."""
    if token is None:
        return 0.0
    try:
        return float(decode_jwt_body(token)["exp"])
    except Exception:  # noqa: BLE001  not a JWT, or no exp: treat as expired
        return 0.0


def _session_state_writer(access_key: str, refresh_key: str) -> Callable[[str, str | None], None]:
    """A refresh hook that keeps the renewed pair under these session-state keys."""

    def write(access_token: str, refresh_token: str | None) -> None:
        try:
            st.session_state[access_key] = access_token
            st.session_state[refresh_key] = refresh_token
        except Exception:  # noqa: BLE001  outside a script run, e.g. in an app's worker thread
            logger.debug("Could not keep the renewed token in session state", exc_info=True)
        # The client holds the renewed token either way; only the next rerun starts stale.

    return write


class StreamlitAuth:
    """Handles SweatStack authentication and provides UI components for Streamlit apps.

    This class manages OAuth2 authentication flow for Streamlit applications and provides
    convenient selector components for activities, sports, tags, and metrics. Once authenticated,
    the client property provides access to the SweatStack API.

    Example:
        import streamlit as st
        from sweatstack.streamlit import StreamlitAuth

        # Initialize authentication
        auth = StreamlitAuth(
            client_id="YOUR_APPLICATION_ID",
            client_secret="YOUR_APPLICATION_SECRET",
            redirect_uri="http://localhost:8501",
        )

        # Add authentication to sidebar
        with st.sidebar:
            auth.authenticate()

        # Check authentication
        if not auth.is_authenticated():
            st.write("Please log in to continue")
            st.stop()

        # Use the authenticated client
        st.write("Welcome to SweatStack")
        latest_activity = auth.client.activities.latest()
        st.write(f"Latest activity: {latest_activity.sport} on {latest_activity.start_local}")

        # Switch between accessible users (admin feature)
        with st.sidebar:
            auth.select_user()

    Attributes:
        client: The SweatStack Client instance for API access.
        api_key: The current API access token.
    """

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        scopes: list[str | Scope] | None = None,
        redirect_uri: str | None = None,
    ) -> None:
        """Initialize the StreamlitAuth component.

        Args:
            client_id: OAuth2 client ID. Falls back to SWEATSTACK_CLIENT_ID env var.
            client_secret: OAuth2 client secret. Falls back to SWEATSTACK_CLIENT_SECRET env var.
            scopes: OAuth2 scopes. Falls back to SWEATSTACK_SCOPES env var. Defaults to ``DEFAULT_SCOPE``.
            redirect_uri: OAuth2 redirect URI. Falls back to SWEATSTACK_REDIRECT_URI env var.
        """
        self.client_id = client_id or os.environ.get("SWEATSTACK_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("SWEATSTACK_CLIENT_SECRET")

        if scopes is not None:
            self.scopes = (
                [
                    Scope(scope.strip().lower()) if isinstance(scope, str) else scope
                    for scope in scopes
                ]
                if scopes
                else []
            )
        elif env_scopes := os.environ.get("SWEATSTACK_SCOPES"):
            self.scopes = [Scope(scope.strip().lower()) for scope in env_scopes.split(",")]
        else:
            self.scopes = [Scope(value) for value in DEFAULT_SCOPE.split()]

        self.redirect_uri = redirect_uri or os.environ.get("SWEATSTACK_REDIRECT_URI")

        self._proxy_mode = False
        self._logout_uri = "/logout"
        self._login_uri = "/login"

        self.api_key: str | None = st.session_state.get(_ACCESS_KEY)
        self.refresh_token: str | None = st.session_state.get(_REFRESH_KEY)
        self.client = self._client_for(self.api_key, self.refresh_token)

    def _client_for(
        self,
        access_token: str | SecretStr | None,
        refresh_token: str | SecretStr | None,
        keys: tuple[str, str] = (_ACCESS_KEY, _REFRESH_KEY),
    ) -> Client:
        """A client for one session's token pair, renewing into the session-state ``keys``."""
        client = Client(
            access_token,
            refresh_token=refresh_token,
            streamlit_compatible=True,
            client_id=self.client_id,
            client_secret=self.client_secret,
            ambient_credentials=False,
        )
        client._on_refresh = _session_state_writer(*keys)
        return client

    @classmethod
    def behind_proxy(
        cls,
        redirect_uri: str,
        header_name: str = "X-SweatStack-Token",
        logout_uri: str = "/logout",
        login_uri: str = "/login",
        refresh_header_name: str = "X-SweatStack-Refresh-Token",
    ) -> "StreamlitAuth":
        """Create a StreamlitAuth instance for use behind a proxy.

        Use this method when your Streamlit app runs behind a proxy that handles
        authentication and passes the SweatStack access token via an HTTP header. Call it at
        the top of every run; never keep ``auth`` or ``auth.client`` across sessions
        (``st.cache_resource``, module globals).

        Streamlit exposes the headers of the WebSocket handshake only, so the session never
        sees a token the proxy refreshed later. When the proxy also forwards the refresh token,
        the session renews the access token itself and keeps the renewed pair in
        ``st.session_state``: one token request per token lifetime, however long the tab stays
        open. Both headers must come from the proxy, which must drop any ``X-SweatStack-*``
        header the browser sends. This relies on a refresh returning the same refresh token
        (the API does not rotate them); the proxy's copy stays valid.

        Without the refresh header the handshake token is used as it is, and once it has
        expired every call raises ``SweatStackTokenRefreshError`` with the advice to reload.

        Args:
            redirect_uri: The URI to redirect to after login (used by proxy).
            header_name: The HTTP header name containing the access token.
                         Defaults to "X-SweatStack-Token".
            logout_uri: The URI to redirect to for logout.
                        Defaults to "/logout".
            login_uri: The URI to redirect to for login.
                       Defaults to "/login".
            refresh_header_name: The HTTP header name containing the refresh token.
                         Defaults to "X-SweatStack-Refresh-Token".

        Returns:
            StreamlitAuth: An instance configured for proxy mode.

        Example:
            auth = StreamlitAuth.behind_proxy(
                redirect_uri="https://myapp.example.com/app",
            )

            if not auth.is_authenticated():
                st.error("Missing authentication header")
                st.stop()

            activities = auth.client.activities.list()
        """
        instance = cls(redirect_uri=redirect_uri)
        instance._proxy_mode = True
        instance._logout_uri = logout_uri
        instance._login_uri = login_uri

        access_token = st.context.headers.get(header_name) or None
        refresh_token = st.context.headers.get(refresh_header_name) or None
        proxy_keys = (_PROXY_ACCESS_KEY, _PROXY_REFRESH_KEY)

        if access_token is None:
            # Logged out at the proxy.
            for key in proxy_keys:
                st.session_state.pop(key, None)
        elif refresh_token is not None:
            # Same login as the stored pair: continue from whichever access token lives longer,
            # the stored one after an in-session renewal, the header one after a reload.
            # Otherwise (a new login in this tab, or nothing stored yet) the header pair wins.
            stored_access = st.session_state.get(_PROXY_ACCESS_KEY)
            if st.session_state.get(_PROXY_REFRESH_KEY) == refresh_token and _expires_at(
                stored_access
            ) > _expires_at(access_token):
                access_token = stored_access
            st.session_state[_PROXY_ACCESS_KEY] = access_token
            st.session_state[_PROXY_REFRESH_KEY] = refresh_token
        # Else the proxy does not forward the refresh token: the handshake token, as it is.

        instance.api_key = access_token
        instance.refresh_token = refresh_token
        instance.client = instance._client_for(access_token, refresh_token, keys=proxy_keys)
        if access_token is not None and refresh_token is None:
            instance.client._no_refresh_hint = _PROXY_NO_REFRESH_HINT
        return instance

    def _show_styled_link_button(self, label: str, url: str):
        """Displays a styled link button with hover effects.

        Args:
            label: Text to display on the button.
            url: The URL to navigate to when clicked.
        """
        # In proxy mode use target="_blank" so that on iOS standalone PWAs
        # the link opens in real Safari (with existing sessions) instead of
        # the in-app browser overlay (SFSafariViewController).
        target = "_blank" if self._proxy_mode else "_top"
        st.markdown(
            f"""
            <style>
                .animated-button {{
                }}
                .animated-button:hover {{
                    transform: scale(1.05);
                }}
                .animated-button:active {{
                    transform: scale(1);
                }}
            </style>
            <a href="{url}"
                target="{target}"
                class="animated-button"
                style="display: inline-block;
                    padding: 10px 20px;
                    background-color: #EF2B2D;
                    color: white;
                    text-decoration: none;
                    border-radius: 6px;
                    border: none;
                    transition: all 0.3s ease;
                    cursor: pointer;"
                >{label}</a>
            """,
            unsafe_allow_html=True,
        )

    def logout_button(self) -> None:
        """Displays a logout button and handles user logout.

        In standard mode, clears the stored API key from session state,
        resets the client, and triggers a Streamlit rerun.

        In proxy mode, displays a styled link that redirects to the logout URI.
        """
        if self._proxy_mode:
            self._show_styled_link_button("Logout", self._logout_uri)
        elif st.button("Logout"):
            self.api_key = None
            self.refresh_token = None
            self.client = self._client_for(None, None)
            for key in (_ACCESS_KEY, _REFRESH_KEY, _PROXY_ACCESS_KEY, _PROXY_REFRESH_KEY):
                st.session_state.pop(key, None)
            st.rerun()

    def _running_on_streamlit_cloud(self):
        """Detects if the app is running on Streamlit Cloud."""
        return os.environ.get("HOSTNAME") == "streamlit"

    def _show_sweatstack_login(self, login_label: str | None = None):
        """Displays the SweatStack login button with appropriate styling.

        Args:
            login_label: Text to display on the login button.
        """
        if self._proxy_mode:
            url = self._login_uri
        else:
            url = self.get_authorization_url()
        login_label = login_label or "Connect with SweatStack"
        if not self._running_on_streamlit_cloud():
            self._show_styled_link_button(login_label, url)
        else:
            st.link_button(login_label, url)

    def get_authorization_url(self) -> str:
        """Generates the OAuth2 authorization URL for SweatStack.

        This method constructs the URL users will be redirected to for OAuth2 authorization.
        It includes the client ID, redirect URI, scopes, and other OAuth2 parameters.

        Returns:
            str: The complete authorization URL.

        Raises:
            ValueError: Without a client ID or a redirect URI.
        """
        if not self.client_id or not self.redirect_uri:
            raise ValueError(
                "StreamlitAuth needs client_id and redirect_uri "
                "(or SWEATSTACK_CLIENT_ID and SWEATSTACK_REDIRECT_URI)"
            )
        return build_authorization_url(
            DEFAULT_URL,
            client_id=self.client_id,
            redirect_uri=self.redirect_uri,
            scope=" ".join(scope.value for scope in self.scopes),
        )

    def _set_api_key(
        self, api_key: str | SecretStr | None, refresh_token: str | SecretStr | None
    ) -> None:
        """Makes this pair the one behind ``auth.client``, here and in session state.

        Always both halves: a pair without a refresh token (admin access to a user, a sign-in
        without ``offline_access``) cannot be renewed, and must not inherit the previous pair's.

        Args:
            api_key: The API access token to set.
            refresh_token: The refresh token to set, or None when there is none.
        """
        self.api_key = _secret_value(api_key)
        self.refresh_token = _secret_value(refresh_token)
        st.session_state[_ACCESS_KEY] = self.api_key
        st.session_state[_REFRESH_KEY] = self.refresh_token
        self.client = self._client_for(self.api_key, self.refresh_token)

    def _exchange_token(self, code):
        """Exchanges an authorization code for an access token.

        Args:
            code: The authorization code from the OAuth2 callback.

        Raises:
            Exception: If the token exchange fails.
        """
        if not self.client_id or not self.client_secret:
            raise ValueError(
                "StreamlitAuth needs client_id and client_secret "
                "(or SWEATSTACK_CLIENT_ID and SWEATSTACK_CLIENT_SECRET)"
            )
        token_data = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
        }
        auth = httpx.BasicAuth(username=self.client_id, password=self.client_secret)
        response = _transport.post(
            f"{DEFAULT_URL}/api/v1/oauth/token",
            data=token_data,
            auth=auth,
        )
        if not response.is_success:
            raise SweatStackAuthError(
                status_code=response.status_code,
                url=str(response.request.url),
                method=response.request.method,
                body="SweatStack Python login failed. Please try again.",
            )
        token_response = response.json()

        self._set_api_key(
            token_response.get("access_token"), refresh_token=token_response.get("refresh_token")
        )

        return

    def is_authenticated(self) -> bool:
        """Checks if the user is currently authenticated with SweatStack.

        This method determines if the user has a valid API key stored in the session state
        or in the instance. It does not verify if the API key is still valid with the server.

        Returns:
            bool: True if the user has an API key, False otherwise.
        """
        return self.api_key is not None

    def authenticate(self, login_label: str | None = None, show_logout: bool = True) -> None:
        """Authenticates the user with SweatStack.

        This method handles the authentication flow for SweatStack in a Streamlit app.
        It checks if the user is already authenticated, and if not, displays a login button.
        If the user is authenticated, it displays a logout button.

        When the user clicks the login button, they are redirected to the SweatStack
        authorization page. After successful authorization, they are redirected back
        to the Streamlit app with an authorization code, which is exchanged for an
        access token.

        In proxy mode, this method only shows the login button if not authenticated.
        The proxy handles the OAuth callback and token exchange.

        Args:
            login_label: The label to display on the login button. Defaults to "Login with SweatStack".

        """
        if self._proxy_mode:
            if self.is_authenticated():
                if show_logout:
                    self.logout_button()
            else:
                self._show_sweatstack_login(login_label)
            return

        if self.is_authenticated():
            if not st.session_state.get("sweatstack_auth_toast_shown", False):
                st.toast("SweatStack authentication successful!", icon="✅")
                st.session_state["sweatstack_auth_toast_shown"] = True
            if show_logout:
                self.logout_button()
        elif code := st.query_params.get("code"):
            self._exchange_token(code)
            st.query_params.clear()
            st.rerun()
        else:
            self._show_sweatstack_login(login_label)

    def select_user(self, *, team_id: str | None = None) -> UserSummary:
        """Displays a user selection dropdown; ``auth.client`` then acts as the selected user.

        Lists the users the signed-in (principal) user can access and replaces ``auth.client``
        with a client delegated to the selected one. The session keeps that user's access and
        refresh tokens together, so a token refresh never falls back to the principal.

        Args:
            team_id: Optional team ID. When provided, delegates via team membership
                instead of direct user permissions.

        Returns:
            UserSummary: The selected user object.

        Note:
            This method requires the user to have appropriate permissions to access other users.
            For regular users, this typically only shows their own user information.
        """
        principal = self.client.principal_client()
        selected_user = st.selectbox(
            "Select a user",
            principal.users.list(),
            format_func=lambda user: user.display_name,
        )
        delegated = principal.delegated_client(selected_user, team_id=team_id)
        self._set_api_key(delegated.api_key, refresh_token=delegated.refresh_token)

        return selected_user

    def switch_to_principal_user(self) -> None:
        """Switches the client back to the principal user.

        This method reverts the client's authentication from a delegated user back to the principal user.
        The client will use the principal token for all subsequent API calls and updates the session state
        with the new API key.


        Raises:
            SweatStackAPIError: If the principal token request fails.
        """
        principal = self.client.principal_client()
        self._set_api_key(principal.api_key, refresh_token=principal.refresh_token)

    def select_activity(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | str | list[Sport | str] | None = None,
        tags: str | list[str] | None = None,
        limit: int = 100,
    ) -> ActivitySummary:
        """Select an activity from the user's activities.

        This method retrieves activities based on specified filters and displays them in a
        dropdown for selection.

        Args:
            start: Optional start date to filter activities.
            end: Optional end date to filter activities.
            sport: One sport or a list; an activity matches any of them.
            tags: One tag or a list; an activity must have all of them.
            limit: Maximum number of activities to retrieve. Defaults to 100.

        Returns:
            ActivitySummary: The selected activity.

        Note:
            Activities are displayed in the format "YYYY-MM-DD sport_name".
        """

        activities = self.client.activities.list(
            start=start,
            end=end,
            sport=sport,
            tags=tags,
            limit=limit,
            output="models",  # the selector iterates models whatever the client's default output
        )
        selected_activity = st.selectbox(
            "Select an activity",
            activities,
            format_func=lambda activity: (
                f"{activity.start_local.date().isoformat()} {activity.sport.label}"
            ),
        )
        return selected_activity

    def select_sport(
        self, only_root: bool = False, allow_multiple: bool = False, only_available: bool = True
    ) -> Sport | list[Sport]:
        """Select a sport from the available sports.

        This method retrieves sports and displays them in a dropdown or multiselect for selection.

        Args:
            only_root: If True, only returns root sports without parents. Defaults to False.
            allow_multiple: If True, allows selecting multiple sports. Defaults to False.
            only_available: If True, only shows sports available to the user. If False, shows all
                standard OpenSportTaxonomy sports. Defaults to True.

        Returns:
            Sport | list[Sport]: The selected sport, or sports if ``allow_multiple``.

        Note:
            Sports are displayed in a human-readable format using each sport's ``label``.
        """
        if only_available:
            sports = self.client.profile.sports(only_root=only_root)
        else:
            if only_root:
                sports = [s for s in Sport.all() if "." not in s.code and not s.modifiers]
            else:
                sports = Sport.all()

        if allow_multiple:
            selected_sport = st.multiselect(
                "Select sports",
                sports,
                format_func=lambda sport: sport.label,
            )
        else:
            selected_sport = st.selectbox(
                "Select a sport",
                sports,
                format_func=lambda sport: sport.label,
            )
        return selected_sport

    def select_tag(self, allow_multiple: bool = False) -> str | list[str]:
        """Select a tag from the available tags.

        This method retrieves tags and displays them in a dropdown or multiselect for selection.

        Args:
            allow_multiple: If True, allows selecting multiple tags. Defaults to False.

        Returns:
            str | list[str]: The selected tag, or tags if ``allow_multiple``.

        Note:
            Empty tags are displayed as "-" in the dropdown.
        """
        tags = self.client.profile.tags()
        if allow_multiple:
            selected_tag = st.multiselect(
                "Select tags",
                tags,
            )
        else:
            selected_tag = st.selectbox(
                "Select a tag",
                tags,
                format_func=lambda tag: tag or "-",
            )
        return selected_tag

    def select_metric(self, allow_multiple: bool = False) -> Metric | list[Metric]:
        """Select a metric from the available metrics.

        This method displays metrics in a dropdown or multiselect for selection.

        Args:
            allow_multiple: If True, allows selecting multiple metrics. Defaults to False.

        Returns:
            Metric | list[Metric]: The selected metric, or metrics if ``allow_multiple``.
        """
        if allow_multiple:
            selected_metric = st.multiselect(
                "Select metrics",
                Metric,
                format_func=lambda metric: metric.value,
            )
        else:
            selected_metric = st.selectbox(
                "Select a metric",
                Metric,
                format_func=lambda metric: metric.value,
            )
        return selected_metric
