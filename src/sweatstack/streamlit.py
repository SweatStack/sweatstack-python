import os
import urllib.parse

try:
    import streamlit as st
except ImportError:
    raise ImportError(
        "Streamlit features require streamlit to be installed. "
        "You can install it with:\n\n"
        "pip install 'sweatstack[streamlit]'\n\n"
    )
import httpx
from sweatstack import Client

from .constants import DEFAULT_URL


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

        self.api_key = token_response.get("access_token")
        st.session_state["sweatstack_api_key"] = self.api_key

        self.client = Client(self.api_key, streamlit_compatible=True)

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