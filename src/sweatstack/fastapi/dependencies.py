"""FastAPI dependencies for authentication."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Annotated, NoReturn
from urllib.parse import quote

import httpx
from fastapi import Depends, HTTPException, Request, Response

from ..client import Client
from ..constants import DEFAULT_URL
from ..utils import decode_jwt_body
from .config import get_config
from .models import SessionData, TokenSet, extract_user_id
from .session import (
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    decrypt_session,
    set_session_cookie,
)

logger = logging.getLogger(__name__)

TOKEN_EXPIRY_MARGIN = 5  # seconds


@dataclass(slots=True)
class SweatStackUser:
    """Authenticated SweatStack user.

    Attributes:
        client: An authenticated Client instance for API calls.
    """

    client: Client

    @property
    def user_id(self) -> str:
        """The user ID this client acts as."""
        return extract_user_id(self.client.api_key)


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------


def _is_token_expiring(token: str) -> bool:
    """Check if a token is within TOKEN_EXPIRY_MARGIN seconds of expiring."""
    try:
        body = decode_jwt_body(token)
        return body["exp"] - TOKEN_EXPIRY_MARGIN < time.time()
    except Exception:
        return True


def _refresh_access_token(
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


def _refresh_tokens_if_needed(tokens: TokenSet) -> TokenSet | None:
    """Refresh tokens if the access token is expiring.

    Returns new TokenSet if refreshed, None if no refresh needed.
    """
    if not _is_token_expiring(tokens.access_token):
        return None

    token_body = decode_jwt_body(tokens.access_token)
    tz = token_body.get("tz", "UTC")

    config = get_config()
    new_access_token = _refresh_access_token(
        refresh_token=tokens.refresh_token,
        client_id=config.client_id,
        client_secret=config.client_secret.get_secret_value(),
        tz=tz,
    )

    return TokenSet(
        access_token=new_access_token,
        refresh_token=tokens.refresh_token,
        user_id=tokens.user_id,
    )


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


def _raise_unauthenticated(request: Request) -> NoReturn:
    """Raise appropriate exception for unauthenticated requests."""
    config = get_config()
    if config.redirect_unauthenticated:
        next_url = request.url.path
        if request.url.query:
            next_url += f"?{request.url.query}"
        login_url = f"{config.auth_route_prefix}/login?next={quote(next_url)}"
        raise HTTPException(status_code=303, headers={"Location": login_url})
    raise HTTPException(status_code=401, detail="Not authenticated")


def _get_session_or_raise(request: Request) -> SessionData:
    """Get and validate session data, raising if invalid."""
    raw_session = decrypt_session(request.cookies.get(SESSION_COOKIE_NAME))
    if not raw_session:
        _raise_unauthenticated(request)

    try:
        return SessionData.from_dict(raw_session)
    except (KeyError, TypeError):
        _raise_unauthenticated(request)


def _get_session_or_none(request: Request) -> SessionData | None:
    """Get session data if present and valid, None otherwise."""
    raw_session = decrypt_session(request.cookies.get(SESSION_COOKIE_NAME))
    if not raw_session:
        return None

    try:
        return SessionData.from_dict(raw_session)
    except (KeyError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Core dependency logic
# ---------------------------------------------------------------------------


def _create_user(
    session: SessionData,
    response: Response,
    *,
    use_delegated: bool,
) -> SweatStackUser:
    """Create user from session, refreshing tokens if needed."""
    config = get_config()

    # Select which tokens to use
    if use_delegated and session.delegated:
        tokens = session.delegated
        is_delegated = True
    else:
        tokens = session.principal
        is_delegated = False

    # Refresh tokens if needed and persist immediately
    try:
        refreshed = _refresh_tokens_if_needed(tokens)
    except Exception:
        logger.exception("Token refresh failed for user %s", tokens.user_id)
        clear_session_cookie(response)
        raise HTTPException(status_code=401, detail="Session expired")

    if refreshed:
        # Update session with refreshed tokens
        if is_delegated:
            session = SessionData(principal=session.principal, delegated=refreshed)
        else:
            session = SessionData(principal=refreshed, delegated=session.delegated)
        tokens = refreshed
        set_session_cookie(response, session.to_dict())

    return SweatStackUser(
        client=Client(
            api_key=tokens.access_token,
            refresh_token=tokens.refresh_token,
            client_id=config.client_id,
            client_secret=config.client_secret,
        )
    )


# ---------------------------------------------------------------------------
# Dependency functions
# ---------------------------------------------------------------------------


def _require_authenticated_user(
    request: Request,
    response: Response,
) -> SweatStackUser:
    """Dependency: always returns principal user."""
    session = _get_session_or_raise(request)
    return _create_user(session, response, use_delegated=False)


def _require_selected_user(
    request: Request,
    response: Response,
) -> SweatStackUser:
    """Dependency: returns delegated user if selected, otherwise principal."""
    session = _get_session_or_raise(request)
    return _create_user(session, response, use_delegated=True)


def _optional_authenticated_user(
    request: Request,
    response: Response,
) -> SweatStackUser | None:
    """Dependency: returns principal user or None."""
    session = _get_session_or_none(request)
    if not session:
        return None
    try:
        return _create_user(session, response, use_delegated=False)
    except HTTPException:
        return None


def _optional_selected_user(
    request: Request,
    response: Response,
) -> SweatStackUser | None:
    """Dependency: returns selected user or None."""
    session = _get_session_or_none(request)
    if not session:
        return None
    try:
        return _create_user(session, response, use_delegated=True)
    except HTTPException:
        return None


# ---------------------------------------------------------------------------
# Public type aliases
# ---------------------------------------------------------------------------

AuthenticatedUser = Annotated[SweatStackUser, Depends(_require_authenticated_user)]
"""Dependency that always returns the principal (logged-in) user.

Example:
    @app.get("/my-athletes")
    def get_athletes(user: AuthenticatedUser):
        return user.client.get_users()
"""

SelectedUser = Annotated[SweatStackUser, Depends(_require_selected_user)]
"""Dependency that returns the currently selected user.

Returns the delegated user if one is selected, otherwise the principal user.

Example:
    @app.get("/activities")
    def get_activities(user: SelectedUser):
        return user.client.get_activities()
"""

OptionalUser = Annotated[SweatStackUser | None, Depends(_optional_authenticated_user)]
"""Dependency that returns the principal user or None if not authenticated.

Example:
    @app.get("/")
    def home(user: OptionalUser):
        if user:
            return {"logged_in": True, "user_id": user.user_id}
        return {"logged_in": False}
"""

OptionalSelectedUser = Annotated[SweatStackUser | None, Depends(_optional_selected_user)]
"""Dependency that returns the selected user or None if not authenticated.

Example:
    @app.get("/public-profile")
    def profile(user: OptionalSelectedUser):
        if user:
            return user.client.get_user()
        return {"message": "Not logged in"}
"""
