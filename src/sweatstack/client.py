import base64
import random
import hashlib
import os
import secrets
import urllib
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import httpx


AUTH_SUCCESSFUL_RESPONSE = "<!DOCTYPE html><html><body><h1>Authentication successful. You can now close this window.</h1></body></html>"
OAUTH2_CLIENT_ID = "5382f68b0d254378"
DEFAULT_URL = "https://app.sweatstack.no"


class OAuth2Mixin:
    def login(self):
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
            "scope": "data:read",
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
            raise Exception("Sweat Stack Python login timed out after 30 seconds. Please try again.")

        if hasattr(server, "code"):
            token_data = {
                "grant_type": "authorization_code",
                "client_id": OAUTH2_CLIENT_ID,
                "code": server.code,
                "code_verifier": code_verifier
            }
            response = httpx.post(
                f"{self.url}/oauth/token",
                data=token_data,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise Exception(f"Sweat Stack Python login failed. Please try again.") from e
            token_response = response.json()

            self.jwt = token_response.get("access_token")
            self.api_key = self.jwt
            print(f"Sweat Stack Python login successful.")
        else:
            raise Exception("Sweat Stack Python login failed. Please try again.")


class Client(OAuth2Mixin):
    def __init__(self, api_key: str | None = None, url: str | None = None):
        self.api_key = api_key
        self.url = url

    @property
    def api_key(self) -> str:
        if self._api_key is not None:
            return self._api_key
        
        return os.getenv("SWEATSTACK_API_KEY")

    @api_key.setter
    def api_key(self, value: str):
        self._api_key = value
    
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

    def list_activities(self):
        return []


_default_client = Client()


def login():
    _default_client.login()


def list_activities():
    return _default_client.list_activities()