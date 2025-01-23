import base64
import contextlib
import random
import hashlib
import os
import secrets
import urllib
import webbrowser
from datetime import date
from functools import wraps
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Generator, get_type_hints, List
from urllib.parse import parse_qs, urlparse

import httpx
import pandas as pd

from .schemas import ActivityDetails, ActivitySummary, Sport

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
            raise Exception("SweatStack Python login timed out after 30 seconds. Please try again.")

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
                raise Exception(f"SweatStack Python login failed. Please try again.") from e
            token_response = response.json()

            self.jwt = token_response.get("access_token")
            self.api_key = self.jwt
            print(f"SweatStack Python login successful.")
        else:
            raise Exception("SweatStack Python login failed. Please try again.")


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
    
    @contextlib.contextmanager
    def _http_client(self):
        """
        Creates an httpx client with the base URL and authentication headers pre-configured.
        """
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        with httpx.Client(base_url=self.url, headers=headers) as client:
            yield client

    def _get_activities_generator(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        sports: list[Sport | str] | None = None,
        limit: int = 100,
    ) -> Generator[ActivitySummary, None, None]:
        num_returned = 0
        offset = 0
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
            params["sports"] = sports

        with self._http_client() as client:
            while True:
                response = client.get(
                    url="/api/v1/activities/",
                    params=params,
                )
                response.raise_for_status()
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

    def get_activities(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        sports: list[Sport | str] | None = None,
        limit: int = 100,
        as_dataframe: bool = False,
    ) -> Generator[ActivitySummary, None, None] | pd.DataFrame:
        generator = self._get_activities_generator(
            start=start,
            end=end,
            sports=sports,
            limit=limit,
        )
        if as_dataframe:
            return pd.DataFrame([activity.model_dump() for activity in generator])
        else:
            return generator

    def get_activity(self, activity_id: str) -> ActivityDetails:
        with self._http_client() as client:
            response = client.get(url=f"/api/v1/activities/{activity_id}")
            response.raise_for_status()
            return ActivityDetails.model_validate(response.json())


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
        "get_activities",
        "get_activity",
        "login",
    ]
)