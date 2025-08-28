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
    def __init__(
        self,
        client_id=None,
        client_secret=None,
        scopes: List[Union[str, Scope]]=None,
        redirect_uri=None,
    ):
        """
        Args:
            client_id: The client ID to use. If not provided, the SWEATSTACK_CLIENT_ID environment variable will be used.
            client_secret: The client secret to use. If not provided, the SWEATSTACK_CLIENT_SECRET environment variable will be used.
            scopes: The scopes to use. If not provided, the SWEATSTACK_SCOPES environment variable will be used. Defaults to data:read, profile.
            redirect_uri: The redirect URI to use. If not provided, the SWEATSTACK_REDIRECT_URI environment variable will be used.
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

        self.api_key = st.session_state.get("sweatstack_api_key")
        self.client = Client(self.api_key, streamlit_compatible=True)

    def logout_button(self):
        if st.button("Logout"):
            self.api_key = None
            self.client = Client(streamlit_compatible=True)
            st.session_state.pop("sweatstack_api_key")
            st.rerun()

    def _running_on_streamlit_cloud(self):
        return os.environ.get("HOSTNAME") == "streamlit"

    def _show_sweatstack_login(self, login_label: str | None = None):
        authorization_url = self.get_authorization_url()
        login_label = login_label or "Connect with SweatStack"
        if not self._running_on_streamlit_cloud():
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
                <a href="{authorization_url}"
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
                    >{login_label}</a>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.link_button(login_label, authorization_url)

    def get_authorization_url(self):
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": ",".join([scope.value for scope in self.scopes]),
            "prompt": "none",
        }
        path = "/oauth/authorize"
        authorization_url = urllib.parse.urljoin(DEFAULT_URL, path + "?" + urllib.parse.urlencode(params))

        return authorization_url

    def _set_api_key(self, api_key):
        self.api_key = api_key
        st.session_state["sweatstack_api_key"] = api_key
        self.client = Client(self.api_key, streamlit_compatible=True)

    def _exchange_token(self, code):
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

        self._set_api_key(token_response.get("access_token"))

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

        Args:
            login_label: The label to display on the login button. Defaults to "Login with SweatStack".

        Returns:
            None
        """
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