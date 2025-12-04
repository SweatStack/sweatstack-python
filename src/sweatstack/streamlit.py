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
    latest = auth.client.get_latest_activity()
    st.write(f"Latest: {latest.sport}")
"""
import os
import urllib.parse
from datetime import date
from typing import List, Union
try:
    import streamlit as st
except ImportError:
    raise ImportError(
        "Streamlit features require streamlit to be installed. "
        "You can install it with:\n\n"
        "pip install 'sweatstack[streamlit]'\n\n"
    )
import httpx

from .client import Client
from .constants import DEFAULT_URL
from .schemas import Metric, Scope, Sport


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
        latest_activity = auth.client.get_latest_activity()
        st.write(f"Latest activity: {latest_activity.sport} on {latest_activity.start}")

        # Switch between accessible users (admin feature)
        with st.sidebar:
            auth.select_user()

    Attributes:
        client: The SweatStack Client instance for API access.
        api_key: The current API access token.
    """

    def __init__(
        self,
        client_id=None,
        client_secret=None,
        scopes: List[Union[str, Scope]]=None,
        redirect_uri=None,
    ):
        """Initialize the StreamlitAuth component.

        Args:
            client_id: OAuth2 client ID. Falls back to SWEATSTACK_CLIENT_ID env var.
            client_secret: OAuth2 client secret. Falls back to SWEATSTACK_CLIENT_SECRET env var.
            scopes: OAuth2 scopes. Falls back to SWEATSTACK_SCOPES env var. Defaults to data:read, profile.
            redirect_uri: OAuth2 redirect URI. Falls back to SWEATSTACK_REDIRECT_URI env var.
        """
        self.client_id = client_id or os.environ.get("SWEATSTACK_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("SWEATSTACK_CLIENT_SECRET")

        if scopes is not None:
            self.scopes = [Scope(scope.strip().lower()) if isinstance(scope, str) else scope
                          for scope in scopes] if scopes else []
        elif os.environ.get("SWEATSTACK_SCOPES"):
            scopes = os.environ.get("SWEATSTACK_SCOPES").split(",")
            self.scopes = [Scope(scope.strip().lower()) if isinstance(scope, str) else scope
                          for scope in scopes]
        else:
            self.scopes = [Scope.data_read, Scope.profile]

        self.redirect_uri = redirect_uri or os.environ.get("SWEATSTACK_REDIRECT_URI")

        self._proxy_mode = False
        self._logout_uri = None

        self.api_key = st.session_state.get("sweatstack_api_key")
        self.refresh_token = st.session_state.get("sweatstack_refresh_token")
        self.client = Client(
            self.api_key,
            refresh_token=self.refresh_token,
            streamlit_compatible=True,
            client_id=self.client_id,
            client_secret=self.client_secret,
        )

    @classmethod
    def behind_proxy(
        cls,
        redirect_uri: str,
        header_name: str = "X-SweatStack-Token",
        logout_uri: str = "/logout",
    ) -> "StreamlitAuth":
        """Create a StreamlitAuth instance for use behind a proxy.

        Use this method when your Streamlit app runs behind a proxy that handles
        authentication and passes the SweatStack access token via an HTTP header.

        Args:
            redirect_uri: The URI to redirect to after login (used by proxy).
            header_name: The HTTP header name containing the access token.
                         Defaults to "X-SweatStack-Token".
            logout_uri: The URI to redirect to for logout.
                        Defaults to "/logout".

        Returns:
            StreamlitAuth: An instance configured for proxy mode.

        Example:
            auth = StreamlitAuth.behind_proxy(
                redirect_uri="https://myapp.example.com/app",
            )

            if not auth.is_authenticated():
                st.error("Missing authentication header")
                st.stop()

            activities = auth.client.get_activities()
        """
        instance = cls(redirect_uri=redirect_uri)
        instance._proxy_mode = True
        instance._logout_uri = logout_uri

        token = st.context.headers.get(header_name)
        if token:
            instance.api_key = token
            instance.client = Client(token, streamlit_compatible=True)

        return instance

    def _show_styled_link_button(self, label: str, url: str):
        """Displays a styled link button with hover effects.

        Args:
            label: Text to display on the button.
            url: The URL to navigate to when clicked.
        """
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
                target="_top"
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

    def logout_button(self):
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
            self.client = Client(streamlit_compatible=True)
            st.session_state.pop("sweatstack_api_key", None)
            st.session_state.pop("sweatstack_refresh_token", None)
            st.rerun()

    def _running_on_streamlit_cloud(self):
        """Detects if the app is running on Streamlit Cloud."""
        return os.environ.get("HOSTNAME") == "streamlit"

    def _show_sweatstack_login(self, login_label: str | None = None):
        """Displays the SweatStack login button with appropriate styling.

        Args:
            login_label: Text to display on the login button.
        """
        authorization_url = self.get_authorization_url()
        login_label = login_label or "Connect with SweatStack"
        if not self._running_on_streamlit_cloud():
            self._show_styled_link_button(login_label, authorization_url)
        else:
            st.link_button(login_label, authorization_url)

    def get_authorization_url(self):
        """Generates the OAuth2 authorization URL for SweatStack.

        This method constructs the URL users will be redirected to for OAuth2 authorization.
        It includes the client ID, redirect URI, scopes, and other OAuth2 parameters.

        Returns:
            str: The complete authorization URL.
        """
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": ",".join([scope.value for scope in self.scopes]),
            "prompt": "none",
        }
        path = "/oauth/authorize"
        authorization_url = urllib.parse.urljoin(DEFAULT_URL, path + "?" + urllib.parse.urlencode(params))

        return authorization_url

    def _set_api_key(self, api_key, refresh_token=None):
        """Sets the API key and refresh token in instance and session state, then refreshes the client.

        Args:
            api_key: The API access token to set.
            refresh_token: The refresh token to set. If None, keeps the existing refresh token.
        """
        self.api_key = api_key
        st.session_state["sweatstack_api_key"] = api_key

        if refresh_token is not None:
            self.refresh_token = refresh_token
            st.session_state["sweatstack_refresh_token"] = refresh_token

        self.client = Client(self.api_key, refresh_token=self.refresh_token, streamlit_compatible=True)

    def _exchange_token(self, code):
        """Exchanges an authorization code for an access token.

        Args:
            code: The authorization code from the OAuth2 callback.

        Raises:
            Exception: If the token exchange fails.
        """
        token_data = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
        }
        auth = httpx.BasicAuth(username=self.client_id, password=self.client_secret)
        response = httpx.post(
            f"{DEFAULT_URL}/api/v1/oauth/token",
            data=token_data,
            auth=auth,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise Exception(f"SweatStack Python login failed. Please try again.") from e
        token_response = response.json()

        self._set_api_key(
            token_response.get("access_token"),
            refresh_token=token_response.get("refresh_token")
        )

        return

    def is_authenticated(self):
        """Checks if the user is currently authenticated with SweatStack.

        This method determines if the user has a valid API key stored in the session state
        or in the instance. It does not verify if the API key is still valid with the server.

        Returns:
            bool: True if the user has an API key, False otherwise.
        """
        return self.api_key is not None

    def authenticate(self, login_label: str | None = None, show_logout: bool = True):
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

        Returns:
            None
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

    def select_user(self):
        """Displays a user selection dropdown and switches the client to the selected user.

        This method retrieves a list of users accessible to the current user and displays
        them in a dropdown. When a user is selected, the client is switched to operate on
        behalf of that user. The method first switches back to the principal user to ensure
        the full list of available users is displayed.

        Returns:
            UserSummary: The selected user object.

        Note:
            This method requires the user to have appropriate permissions to access other users.
            For regular users, this typically only shows their own user information.
        """
        self.switch_to_principal_user()
        other_users = self.client.get_users()
        selected_user = st.selectbox(
            "Select a user",
            other_users,
            format_func=lambda user: user.display_name,
        )
        self.client.switch_user(selected_user)
        self._set_api_key(self.client.api_key)

        return selected_user

    def switch_to_principal_user(self):
        """Switches the client back to the principal user.

        This method reverts the client's authentication from a delegated user back to the principal user.
        The client will use the principal token for all subsequent API calls and updates the session state
        with the new API key.

        Returns:
            None

        Raises:
            HTTPStatusError: If the principal token request fails.
        """
        self.client.switch_back()
        self._set_api_key(self.client.api_key)

    def select_activity(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        sports: list[Sport] | None = None,
        tags: list[str] | None = None,
        limit: int | None = 100,
    ):
        """Select an activity from the user's activities.

        This method retrieves activities based on specified filters and displays them in a
        dropdown for selection.

        Args:
            start: Optional start date to filter activities.
            end: Optional end date to filter activities.
            sports: Optional list of sports to filter activities by.
            tags: Optional list of tags to filter activities by.
            limit: Maximum number of activities to retrieve. Defaults to 100.

        Returns:
            The selected activity object.

        Note:
            Activities are displayed in the format "YYYY-MM-DD sport_name".
        """

        activities = self.client.get_activities(
            start=start,
            end=end,
            sports=sports,
            tags=tags,
            limit=limit,
        )
        selected_activity = st.selectbox(
            "Select an activity",
            activities,
            format_func=lambda activity: f"{activity.start.date().isoformat()} {activity.sport.display_name()}",
        )
        return selected_activity

    def select_sport(self, only_root: bool = False, allow_multiple: bool = False, only_available: bool = True):
        """Select a sport from the available sports.

        This method retrieves sports and displays them in a dropdown or multiselect for selection.

        Args:
            only_root: If True, only returns root sports without parents. Defaults to False.
            allow_multiple: If True, allows selecting multiple sports. Defaults to False.
            only_available: If True, only shows sports available to the user. If False, shows all
                sports defined in the Sport enum. Defaults to True.

        Returns:
            Sport or list[Sport]: The selected sport or list of sports, depending on allow_multiple.

        Note:
            Sports are displayed in a human-readable format using the display_name function.
        """
        if only_available:
            sports = self.client.get_sports(only_root)
        else:
            if only_root:
                sports = [sport for sport in Sport if "." not in sport.value]
            else:
                sports = Sport

        if allow_multiple:
            selected_sport = st.multiselect(
                "Select sports",
                sports,
                format_func=lambda sport: sport.display_name(),
            )
        else:
            selected_sport = st.selectbox(
                "Select a sport",
                sports,
                format_func=lambda sport: sport.display_name(),
            )
        return selected_sport

    def select_tag(self, allow_multiple: bool = False):
        """Select a tag from the available tags.

        This method retrieves tags and displays them in a dropdown or multiselect for selection.

        Args:
            allow_multiple: If True, allows selecting multiple tags. Defaults to False.

        Returns:
            str or list[str]: The selected tag or list of tags, depending on allow_multiple.

        Note:
            Empty tags are displayed as "-" in the dropdown.
        """
        tags = self.client.get_tags()
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

    def select_metric(self, allow_multiple: bool = False):
        """Select a metric from the available metrics.

        This method displays metrics in a dropdown or multiselect for selection.

        Args:
            allow_multiple: If True, allows selecting multiple metrics. Defaults to False.

        Returns:
            Metric or list[Metric]: The selected metric or list of metrics, depending on allow_multiple.
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