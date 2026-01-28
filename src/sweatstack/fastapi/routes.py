"""OAuth routes for the FastAPI plugin."""

import base64
import json
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import RedirectResponse

from ..constants import DEFAULT_URL
from ..utils import decode_jwt_body
from .config import get_config
from .session import (
    STATE_COOKIE_NAME,
    clear_session_cookie,
    clear_state_cookie,
    set_session_cookie,
    set_state_cookie,
)


def validate_redirect(url: str | None) -> str | None:
    """Validate that a redirect URL is a safe relative path.

    Returns the URL if valid, None otherwise.
    """
    if url and url.startswith("/") and not url.startswith("//"):
        return url
    return None


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
