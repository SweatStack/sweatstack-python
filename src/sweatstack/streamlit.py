import os
import urllib.parse
from datetime import date
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
from .schemas import Metric, Sport
from .utils import format_sport

class StreamlitAuth:
    def __init__(self, client_id=None, client_secret=None, scope=None, redirect_uri=None):
        """
        Args:
            client_id: The client ID to use. If not provided, the SWEATSTACK_CLIENT_ID environment variable will be used.
            client_secret: The client secret to use. If not provided, the SWEATSTACK_CLIENT_SECRET environment variable will be used.
            scope: The scope to use. If not provided, the SWEATSTACK_SCOPE environment variable will be used.
            redirect_uri: The redirect URI to use. If not provided, the SWEATSTACK_REDIRECT_URI environment variable will be used.
        """
        self.client_id = client_id or os.environ.get("SWEATSTACK_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("SWEATSTACK_CLIENT_SECRET")
        self.scope = scope or os.environ.get("SWEATSTACK_SCOPE")
        self.redirect_uri = redirect_uri or os.environ.get("SWEATSTACK_REDIRECT_URI")

        self.api_key = st.session_state.get("sweatstack_api_key")
        self.client = Client(self.api_key, streamlit_compatible=True)

    def _show_sweatstack_logout(self):
        if st.button("Logout"):
            self.api_key = None
            self.client = Client(streamlit_compatible=True)
            st.session_state.pop("sweatstack_api_key")
            st.rerun()

    def _running_on_streamlit_cloud(self):
        return os.environ.get("HOSTNAME") == "streamlit"

    def _show_sweatstack_login(self):
        authorization_url = self._get_authorization_url()
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
                    >Login with SweatStack</a>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.link_button("Login with SweatStack", authorization_url)

    def _get_authorization_url(self):
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "data:read",
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
        return self.api_key is not None

    def authenticate(self):
        if self.is_authenticated():
            if not st.session_state.get("sweatstack_auth_toast_shown", False):
                st.toast("SweatStack authentication successful!", icon="✅")
                st.session_state["sweatstack_auth_toast_shown"] = True
            self._show_sweatstack_logout()
        elif code := st.query_params.get("code"):
            self._exchange_token(code)
            st.query_params.clear()
            st.rerun()
        else:
            self._show_sweatstack_login()

    def select_user(self):
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
        """
        Select an activity from the user's activities.
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
            format_func=lambda activity: f"{activity.start.date().isoformat()} {format_sport(activity.sport)}",
        )
        return selected_activity

    def select_sport(self, only_root: bool = False, allow_multiple: bool = False, only_available: bool = True):
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
                format_func=format_sport,
            )
        else:
            selected_sport = st.selectbox(
                "Select a sport",
                sports,
                format_func=format_sport,
            )
        return selected_sport

    def select_tag(self, allow_multiple: bool = False):
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