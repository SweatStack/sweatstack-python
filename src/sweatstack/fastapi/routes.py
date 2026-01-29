"""OAuth routes for the FastAPI plugin."""

from __future__ import annotations

import base64
import json
import logging
import secrets
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from ..constants import DEFAULT_URL
from ..utils import decode_jwt_body
from .config import get_config
from .models import SessionData, TokenSet
from .session import (
    SESSION_COOKIE_NAME,
    STATE_COOKIE_NAME,
    clear_session_cookie,
    clear_state_cookie,
    decrypt_session,
    set_session_cookie,
    set_state_cookie,
)

logger = logging.getLogger(__name__)


def validate_redirect(url: str | None) -> str | None:
    """Validate that a redirect URL is a safe relative path.

    Returns the URL if valid, None otherwise.
    """
    if url and url.startswith("/") and not url.startswith("//"):
        return url
    return None


def _is_same_origin(referer: str | None, app_url: str) -> bool:
    """Check if a referer URL is from the same origin as the app."""
    if not referer:
        return False
    try:
        ref_parsed = urlparse(referer)
        app_parsed = urlparse(app_url)
        return (
            ref_parsed.scheme == app_parsed.scheme
            and ref_parsed.netloc == app_parsed.netloc
        )
    except Exception:
        return False


def _get_redirect_url(request: Request, next_param: str | None) -> str:
    """Determine the redirect URL after a user selection change.

    Priority: ?next= parameter > Referer header (if same-origin) > /
    """
    # First try the explicit next parameter
    if validated := validate_redirect(next_param):
        return validated

    # Then try the Referer header if same-origin
    config = get_config()
    referer = request.headers.get("referer")
    if _is_same_origin(referer, config.app_url):
        # Extract just the path from referer
        parsed = urlparse(referer)
        path = parsed.path
        if parsed.query:
            path += f"?{parsed.query}"
        if validated := validate_redirect(path):
            return validated

    # Default to root
    return "/"


def _get_session_data(request: Request) -> SessionData | None:
    """Get session data from request cookie."""
    raw_session = decrypt_session(request.cookies.get(SESSION_COOKIE_NAME))
    if not raw_session:
        return None
    try:
        return SessionData.from_dict(raw_session)
    except (KeyError, TypeError):
        return None


def _fetch_delegated_token(principal_tokens: TokenSet, target_user_id: str) -> TokenSet:
    """Fetch a delegated token for the target user using principal credentials."""
    config = get_config()

    response = httpx.post(
        f"{DEFAULT_URL}/api/v1/oauth/delegated-token",
        headers={"Authorization": f"Bearer {principal_tokens.access_token}"},
        json={"sub": target_user_id},
    )

    if response.status_code == 403:
        raise HTTPException(status_code=403, detail="You don't have access to this user")
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="User not found")

    response.raise_for_status()
    tokens = response.json()

    return TokenSet(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        user_id=target_user_id,
    )


def create_state(next_url: str | None) -> str:
    """Create an OAuth state value with nonce and optional redirect."""
    nonce = secrets.token_urlsafe(32)
    state_data = {"nonce": nonce}
    if next_url:
        state_data["next"] = next_url
    return base64.urlsafe_b64encode(json.dumps(state_data).encode()).decode()


def parse_state(state: str) -> dict:
    """Parse an OAuth state value."""
    try:
        return json.loads(base64.urlsafe_b64decode(state.encode()))
    except Exception:
        return {}


def create_router() -> APIRouter:
    """Create the auth router with login, callback, and logout routes."""
    router = APIRouter()

    @router.get("/login")
    def login(request: Request, next: str | None = None) -> Response:
        """Redirect to SweatStack OAuth authorization."""
        config = get_config()

        # Validate and create state
        validated_next = validate_redirect(next)
        state = create_state(validated_next)

        # Build authorization URL
        params = {
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "scope": " ".join(config.scopes),
            "state": state,
            "prompt": "none",
        }
        auth_url = f"{DEFAULT_URL}/oauth/authorize?{urlencode(params)}"

        # Set state cookie and redirect
        response = RedirectResponse(url=auth_url, status_code=302)
        set_state_cookie(response, state)
        return response

    @router.get("/callback")
    def callback(
        request: Request,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
    ) -> Response:
        """Handle OAuth callback from SweatStack."""
        config = get_config()

        # Get state cookie
        state_cookie = request.cookies.get(STATE_COOKIE_NAME)

        # Clear state cookie regardless of outcome
        response = RedirectResponse(url="/", status_code=302)
        clear_state_cookie(response)

        # Handle OAuth errors
        if error:
            return response

        # Verify state (CSRF protection)
        if not state or not state_cookie or state != state_cookie:
            return Response(content="Invalid state", status_code=400)

        # Exchange code for tokens
        if not code:
            return Response(content="Missing authorization code", status_code=400)

        try:
            token_response = httpx.post(
                f"{DEFAULT_URL}/api/v1/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": config.client_id,
                    "client_secret": config.client_secret.get_secret_value(),
                    "code": code,
                    "redirect_uri": config.redirect_uri,
                },
            )
            token_response.raise_for_status()
            tokens = token_response.json()
        except Exception:
            return response  # Redirect to / on token exchange failure

        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")

        if not access_token:
            return response

        # Extract user_id from JWT
        try:
            token_body = decode_jwt_body(access_token)
            user_id = token_body.get("sub")
        except Exception:
            return response

        if not user_id:
            return response

        # Create session
        session_data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user_id": user_id,
        }

        # Determine redirect URL from state
        state_data = parse_state(state)
        redirect_url = state_data.get("next", "/")

        response = RedirectResponse(url=redirect_url, status_code=302)
        clear_state_cookie(response)
        set_session_cookie(response, session_data)
        return response

    @router.post("/logout")
    def logout() -> Response:
        """Clear session and redirect to /."""
        response = RedirectResponse(url="/", status_code=302)
        clear_session_cookie(response)
        return response

    @router.post("/select-user/{user_id}")
    def select_user(request: Request, user_id: str, next: str | None = None) -> Response:
        """Switch to viewing as another user.

        Fetches a delegated token for the target user and stores it in the session.
        Redirects to Referer (if same-origin), ?next= parameter, or /.
        """
        session = _get_session_data(request)
        if not session:
            raise HTTPException(status_code=401, detail="Not authenticated")

        # Fetch delegated token for the target user
        try:
            delegated_tokens = _fetch_delegated_token(session.principal, user_id)
        except httpx.HTTPStatusError as e:
            logger.warning("Failed to fetch delegated token for user %s: %s", user_id, e)
            raise HTTPException(status_code=403, detail="You don't have access to this user")

        # Update session with delegated tokens
        updated_session = SessionData(
            principal=session.principal,
            delegated=delegated_tokens,
        )

        redirect_url = _get_redirect_url(request, next)
        response = RedirectResponse(url=redirect_url, status_code=303)
        set_session_cookie(response, updated_session.to_dict())
        return response

    @router.post("/select-self")
    def select_self(request: Request, next: str | None = None) -> Response:
        """Switch back to viewing as yourself (clear delegation).

        Removes the delegated tokens from the session.
        Redirects to Referer (if same-origin), ?next= parameter, or /.
        """
        session = _get_session_data(request)
        if not session:
            raise HTTPException(status_code=401, detail="Not authenticated")

        # Clear delegation
        updated_session = SessionData(
            principal=session.principal,
            delegated=None,
        )

        redirect_url = _get_redirect_url(request, next)
        response = RedirectResponse(url=redirect_url, status_code=303)
        set_session_cookie(response, updated_session.to_dict())
        return response

    return router


def instrument(app: FastAPI) -> None:
    """Add SweatStack auth routes to a FastAPI application.

    Args:
        app: The FastAPI application to instrument.

    Raises:
        RuntimeError: If configure() has not been called.
    """
    config = get_config()  # This will raise if not configured
    router = create_router()
    app.include_router(router, prefix=config.auth_route_prefix)
