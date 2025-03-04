import base64
import contextlib
import random
import hashlib
import os
import secrets
import time
import urllib
import webbrowser
from datetime import date, datetime
from functools import wraps
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from typing import Any, Generator, get_type_hints, List, Literal
from urllib.parse import parse_qs, urlparse

import httpx
import pandas as pd

from .constants import DEFAULT_URL
from .schemas import (
    ActivityDetails, ActivitySummary, Sport, TraceDetails, UserSummary
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
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise Exception(f"SweatStack Python login failed. Please try again.") from e
            token_response = response.json()

            self.jwt = token_response.get("access_token")
            self.api_key = self.jwt
            self.refresh_token = token_response.get("refresh_token")
            print(f"SweatStack Python login successful.")
        else:
            raise Exception("SweatStack Python login failed. Please try again.")


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
            response.raise_for_status()

        return response.json()

    def switch_user(self, user: str | UserSummary):
        token_response = self._get_delegated_token(user)
        self.api_key = token_response["access_token"]
        self.refresh_token = token_response["refresh_token"]

    def _get_principal_token(self):
        with self._http_client() as client:
            response = client.get(
                "/api/v1/oauth/principal-token",
            )
            response.raise_for_status()
        return response.json()

    def switch_back(self):
        token_response = self._get_principal_token()
        self.api_key = token_response["access_token"]
        self.refresh_token = token_response["refresh_token"]

    def delegated_client(self, user: str | UserSummary):
        token_response = self._get_delegated_token(user)
        return self.__class__(
            api_key=token_response["access_token"],
            refresh_token=token_response["refresh_token"],
            url=self.url,
            streamlit_compatible=self.streamlit_compatible,
        )

    def principal_client(self):
        token_response = self._get_principal_token()
        return self.__class__(
            api_key=token_response["access_token"],
            refresh_token=token_response["refresh_token"],
            url=self.url,
            streamlit_compatible=self.streamlit_compatible,
        )


class Client(OAuth2Mixin, DelegationMixin):
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

    def _do_token_refresh(self, tz_offset: int) -> str:
        with self._http_client() as client:
            response = client.post(
                "/api/v1/oauth/token",
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "tz_offset": tz_offset,
                },
            )

            response.raise_for_status()
            return response.json()["access_token"]

    def _check_token_expiry(self, token: str) -> str:
        try:
            body = decode_jwt_body(token)
            # Margin in seconds to account for time to token validation of the next request
            TOKEN_EXPIRY_MARGIN = 5
            if body["exp"] - TOKEN_EXPIRY_MARGIN < time.time():
                # Token is (almost) expired, refresh it
                token = self._do_token_refresh(body["tz_offset"])
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
        else:
            value = os.getenv("SWEATSTACK_API_KEY")

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
        else:
            return os.getenv("SWEATSTACK_REFRESH_TOKEN")

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
        tags: list[str] | None = None,
        limit: int = 100,
    ) -> Generator[ActivitySummary, None, None]:
        num_returned = 0
        default_limit = 100
        params = {
            "limit": default_limit,
            "offset": 0,
        }
        if start is not None:
            params["start"] = start.isoformat()
        if end is not None:
            params["end"] = end.isoformat()
        if sports is not None:
            params["sports"] = sports
        if tags is not None:
            params["tags"] = tags

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
        as_dataframe: bool = False,
    ) -> Generator[ActivitySummary, None, None] | pd.DataFrame:
        generator = self._get_activities_generator(
            start=start,
            end=end,
            sports=sports,
            tags=tags,
            limit=limit,
        )
        if as_dataframe:
            df = pd.DataFrame([activity.model_dump() for activity in generator])
            df = df.set_index(df["start"].rename("timestamp"))
            df = self._normalize_dataframe_column(df, "summary")
            df = self._normalize_dataframe_column(df, "laps")
            df = self._normalize_dataframe_column(df, "traces")
            return self._postprocess_dataframe(df)
        else:
            return generator

    def get_latest_activity(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
        tag: str | None = None,
    ) -> ActivityDetails:
        return next(self.get_activities(
            start=start,
            end=end,
            sports=[sport] if sport is not None else None,
            tags=[tag] if tag is not None else None,
            limit=1,
        ))

    def get_activity(self, activity_id: str) -> ActivityDetails:
        with self._http_client() as client:
            response = client.get(url=f"/api/v1/activities/{activity_id}")
            response.raise_for_status()
            return ActivityDetails.model_validate(response.json())

    def get_activity_data(
        self,
        activity_id: str,
        adaptive_sampling_on: Literal["power", "speed"] | None = None,
    ) -> pd.DataFrame:
        params = {}
        if adaptive_sampling_on is not None:
            params["adaptive_sampling_on"] = adaptive_sampling_on

        with self._http_client() as client:
            response = client.get(
                url=f"/api/v1/activities/{activity_id}/data",
                params=params,
            )

        response.raise_for_status()

        df = pd.read_parquet(BytesIO(response.content))
        return self._postprocess_dataframe(df)

    def get_activity_mean_max(
        self,
        activity_id: str,
        metric: str,
        adaptive_sampling: bool = False,
    ) -> pd.DataFrame:
        with self._http_client() as client:
            response = client.get(
                url=f"/api/v1/activities/{activity_id}/mean-max",
                params={
                    "metric": metric,
                    "adaptive_sampling": adaptive_sampling,
                },
            )
            response.raise_for_status()
            df = pd.read_parquet(BytesIO(response.content))
            return self._postprocess_dataframe(df)

    def get_latest_activity_data(
        self,
        sport: Sport | None = None,
        adaptive_sampling_on: Literal["power", "speed"] | None = None,
    ) -> pd.DataFrame:
        activity = self.get_latest_activity(sport=sport)
        return self.get_activity_data(activity.id, adaptive_sampling_on)

    def get_latest_activity_mean_max(
        self,
        metric: str,
        sport: Sport | None = None,
        adaptive_sampling: bool = False,
    ) -> pd.DataFrame:
        activity = self.get_latest_activity(sport=sport)
        return self.get_activity_mean_max(activity.id, metric, adaptive_sampling)

    def get_longitudinal_data(
        self,
        *,
        sport: Sport | None = None,
        sports: list[Sport | str] | None = None,
        start: date | str,
        end: date | str | None = None,
        metrics: list[str] | None = None,
        adaptive_sampling_on: Literal["power", "speed"] | None = None,
    ) -> pd.DataFrame:
        if sport and sports:
            raise ValueError("Cannot specify both sport and sports")
        if sport is not None:
            sports = [sport]
        elif sports is None:
            sports = []

        params = {
            "sports": sports,
            "start": start,
        }
        if end is not None:
            params["end"] = end
        if metrics is not None:
            params["metrics"] = metrics
        if adaptive_sampling_on is not None:
            params["adaptive_sampling_on"] = adaptive_sampling_on

        with self._http_client() as client:
            response = client.get(
                url="/api/v1/activities/longitudinal-data",
                params=params,
            )
            response.raise_for_status()

            df = pd.read_parquet(BytesIO(response.content))
            return self._postprocess_dataframe(df)

    def get_longitudinal_mean_max(
        self,
        *,
        sport: Sport | str,
        metric: str,
        date: date | str | None = None,
        window_days: int | None = None,
    ) -> pd.DataFrame:
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
            response.raise_for_status()

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
    ) -> Generator[TraceDetails, None, None]:
        num_returned = 0
        default_limit = 100
        params = {
            "limit": default_limit,
            "offset": 0,
        }
        if start is not None:
            params["start"] = start.isoformat()
        if end is not None:
            params["end"] = end.isoformat()
        if sports is not None:
            params["sports"] = sports
        if tags is not None:
            params["tags"] = tags

        with self._http_client() as client:
            while True:
                response = client.get(
                    url="/api/v1/traces/",
                    params=params,
                )
                response.raise_for_status()
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
        as_dataframe: bool = False,
    ) -> Generator[TraceDetails, None, None] | pd.DataFrame:
        generator = self._get_traces_generator(
            start=start,
            end=end,
            sports=sports,
            tags=tags,
            limit=limit,
        )
        if not as_dataframe:
            return generator

        data = pd.DataFrame([trace.model_dump() for trace in generator])

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
            response.raise_for_status()
            return TraceDetails.model_validate(response.json())

    def get_sports(self, only_root: bool = False) -> list[Sport]:
        with self._http_client() as client:
            response = client.get(
                url="/api/v1/profile/sports/",
                params={"only_root": only_root},
            )
            response.raise_for_status()
            return [Sport(sport) for sport in response.json()]

    def get_tags(self) -> list[str]:
        with self._http_client() as client:
            response = client.get(
                url="/api/v1/profile/tags/",
            )
            response.raise_for_status()
            return response.json()

    def get_users(self) -> list[UserSummary]:
        with self._http_client() as client:
            response = client.get(
                url="/api/v1/users/",
            )
            response.raise_for_status()
            return [UserSummary.model_validate(user) for user in response.json()]

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

        "get_users",

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

        "switch_user",
        "switch_back",
        "delegated_client",
        "principal_client",
    ]
)