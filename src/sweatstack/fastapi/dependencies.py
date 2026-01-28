"""FastAPI dependencies for authentication."""

import logging
import time
from dataclasses import dataclass
from typing import Annotated, NoReturn, TypeAlias
from urllib.parse import quote

import httpx
from fastapi import Depends, HTTPException, Request, Response

from ..client import Client
from ..constants import DEFAULT_URL
from ..utils import decode_jwt_body
from .config import get_config
from .session import (
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    decrypt_session,
    set_session_cookie,
)

TOKEN_EXPIRY_MARGIN = 5  # seconds


@dataclass
class SweatStackUser:
    """Authenticated SweatStack user.

    Attributes:
        user_id: The user's SweatStack ID.
        client: An authenticated Client instance for API calls.
    """

    user_id: str
    client: Client


def is_token_expiring(token: str) -> bool:
    """Check if a token is within TOKEN_EXPIRY_MARGIN seconds of expiring."""
    try:
        body = decode_jwt_body(token)
        return body["exp"] - TOKEN_EXPIRY_MARGIN < time.time()
    except Exception:
        # If we can't decode, assume it's expired
        return True


def refresh_access_token(
    refresh_token: str,
    client_id: str,
    client_secret: str,
    tz: str,
) -> str:
    """Exchange a refresh token for a new access token."""
    response = httpx.post(
        f"{DEFAULT_URL}/api/v1/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "tz": tz,
        },
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _raise_unauthenticated(request: Request) -> NoReturn:
    """Raise appropriate exception for unauthenticated requests.

    If redirect_unauthenticated is True, redirects to login with ?next= set.
    Otherwise, raises 401 Unauthorized.
    """
    config = get_config()
    if config.redirect_unauthenticated:
        next_url = request.url.path
        if request.url.query:
            next_url += f"?{request.url.query}"
        login_url = f"{config.auth_route_prefix}/login?next={quote(next_url)}"
        raise HTTPException(status_code=303, headers={"Location": login_url})
    raise HTTPException(status_code=401, detail="Not authenticated")


def require_user(request: Request, response: Response) -> SweatStackUser:
    """Dependency that requires an authenticated user.

    Returns a SweatStackUser if the session is valid. If not authenticated,
    behavior depends on the redirect_unauthenticated config:
    - If True: redirects to login with ?next= set to current path
    - If False: raises 401 Unauthorized

    Automatically refreshes tokens if they are about to expire.
    """
    session = decrypt_session(request.cookies.get(SESSION_COOKIE_NAME))
    if not session:
        _raise_unauthenticated(request)

    access_token = session.get("access_token")
    refresh_token = session.get("refresh_token")
    user_id = session.get("user_id")

    if not access_token or not user_id:
        clear_session_cookie(response)
        _raise_unauthenticated(request)

    # Check if token needs refresh
    if is_token_expiring(access_token):
        if not refresh_token:
            clear_session_cookie(response)
            _raise_unauthenticated(request)

        try:
            # Extract timezone from current token
            token_body = decode_jwt_body(access_token)
            tz = token_body.get("tz", "UTC")

            config = get_config()
            new_access_token = refresh_access_token(
                refresh_token=refresh_token,
                client_id=config.client_id,
                client_secret=config.client_secret,
                tz=tz,
            )

            # Update session with new token
            session["access_token"] = new_access_token
            set_session_cookie(response, session)
            access_token = new_access_token

        except Exception:
            logging.exception("Token refresh failed for user %s", user_id)
            clear_session_cookie(response)
            _raise_unauthenticated(request)

    config = get_config()
    client = Client(
        api_key=access_token,
        refresh_token=refresh_token,
        client_id=config.client_id,
        client_secret=config.client_secret,  # Client accepts SecretStr directly
    )
    return SweatStackUser(user_id=user_id, client=client)


def optional_user(request: Request, response: Response) -> SweatStackUser | None:
    """Dependency that optionally returns an authenticated user.

    Returns a SweatStackUser if the session is valid, None otherwise.
    Does not raise exceptions for missing or invalid sessions.
    """
    try:
        return require_user(request, response)
    except HTTPException:
        return None


# Type aliases for use in route handlers
AuthenticatedUser: TypeAlias = Annotated[SweatStackUser, Depends(require_user)]
OptionalUser: TypeAlias = Annotated[SweatStackUser | None, Depends(optional_user)]
