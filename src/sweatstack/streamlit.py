import hashlib
import base64
import os
import secrets
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
from streamlit_cookies_controller import CookieController
from sweatstack import Client

from .constants import DEFAULT_URL


cookie_controller = CookieController()


class StreamlitAuth:
    def __init__(self, set_env_var=False, client_id=None, client_secret=None, scope=None, redirect_uri=None):
        """
        Args:
            set_env_var: Whether to set the SWEATSTACK_API_KEY environment variable. Default is False.
            client_id: The client ID to use. If not provided, the SWEATSTACK_CLIENT_ID environment variable will be used.
            client_secret: The client secret to use. If not provided, the SWEATSTACK_CLIENT_SECRET environment variable will be used.
            scope: The scope to use. If not provided, the SWEATSTACK_SCOPE environment variable will be used.
            redirect_uri: The redirect URI to use. If not provided, the SWEATSTACK_REDIRECT_URI environment variable will be used.
        """
        self.set_env_var = set_env_var
        self.client_id = client_id or os.environ.get("SWEATSTACK_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("SWEATSTACK_CLIENT_SECRET")
        self.scope = scope or os.environ.get("SWEATSTACK_SCOPE")
        self.redirect_uri = redirect_uri or os.environ.get("SWEATSTACK_REDIRECT_URI")

        self.api_key = cookie_controller.get("sweatstack_api_key")
        self.client = Client(self.api_key)

        if self.api_key and self.set_env_var:
            os.environ["SWEATSTACK_API_KEY"] = self.api_key

    def _show_sweatstack_logout(self):
        if st.button("Logout"):
            self.api_key = None
            self.client = Client()
            cookie_controller.remove("sweatstack_api_key")
            if self.set_env_var:
                os.environ.pop("SWEATSTACK_API_KEY")

    def _show_sweatstack_login(self):
        st.link_button("Login", self._get_authorization_url_implicit())

    def _get_authorization_url_implicit(self):
        code_verifier = secrets.token_urlsafe(32)
        cookie_controller.set("code_verifier", code_verifier)
        code_challenge = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(code_challenge).rstrip(b"=").decode("ascii")

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "code_challenge": code_challenge,
            "scope": "data:read",
        }
        path = "/oauth/authorize"
        authorization_url = urllib.parse.urljoin(DEFAULT_URL, path + "?" + urllib.parse.urlencode(params))

        return authorization_url


    def _exchange_token_implicit(self, code):
        code_verifier = cookie_controller.get("code_verifier")
        token_data = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "code": code,
            "code_verifier": code_verifier
        }
        response = httpx.post(
            f"{DEFAULT_URL}/oauth/token",
            data=token_data,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise Exception(f"SweatStack Python login failed. Please try again.") from e
        token_response = response.json()

        self.api_key = token_response.get("access_token")
        cookie_controller.set("sweatstack_api_key", self.api_key)
        if self.set_env_var:
            os.environ["SWEATSTACK_API_KEY"] = self.api_key

        self.client = Client(self.api_key)

        cookie_controller.remove("code_verifier")

        return

    def is_authenticated(self):
        return self.api_key is not None

    def authenticate(self):
        if self.is_authenticated():
            self._show_sweatstack_logout()
        elif code := st.query_params.get("code"):
            self._exchange_token_implicit(code)
            st.query_params.clear()
            st.rerun()
        else:
            self._show_sweatstack_login()