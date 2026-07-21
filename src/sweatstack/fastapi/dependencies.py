"""FastAPI dependencies for authentication."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, NoReturn
from urllib.parse import quote

import httpx
from fastapi import Depends, HTTPException, Request, Response

from ..client import Client
from ..constants import DEFAULT_URL
from ..utils import decode_jwt_body
from .access_token_cache import CachedAccessToken
from .config import get_config
from .models import SessionData, StoredTokens, TokenSet, extract_user_id
from .session import (
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    decrypt_session,
    set_session_cookie,
)

logger = logging.getLogger(__name__)

# Seconds of slack: a token within this margin of expiry is treated as
# already expired so that downstream API calls do not race the clock.
TOKEN_EXPIRY_MARGIN = 5

# Network timeout for the ``/oauth/token`` refresh call. The token
# endpoint is normally sub-second; 10 seconds is generous enough to
# absorb a one-off spike but tight enough that a hung server doesn't
# pin a threadpool worker for minutes.
REFRESH_HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Maximum time to wait for the per-session refresh lock. Set above
# ``REFRESH_HTTP_TIMEOUT`` plus a small slack so that under normal
# operation a waiter strictly serialises behind one in-flight refresh
# and does not itself time out before that refresh has resolved.
REFRESH_LOCK_TIMEOUT = 15.0


class RefreshLockTimeout(RuntimeError):
    """Raised when a peer refresh holds the per-session lock for too long.

    A waiter that cannot acquire the per-session lock within
    :data:`REFRESH_LOCK_TIMEOUT` raises this rather than blocking a
    threadpool worker indefinitely. Surfaces as a 401 in the
    user-facing flow.
    """


def _key_fingerprint(refresh_token: str) -> str:
    """Short, non-reversible identifier for a refresh token, for logs.

    Logging the raw refresh token would be a credential leak; logging
    nothing makes the cache impossible to debug in production. A short
    SHA-256 prefix gives us per-session correlation without exposing
    the secret.
    """
    return hashlib.sha256(refresh_token.encode()).hexdigest()[:8]


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


def _extract_expiry(access_token: str) -> datetime:
    """Extract expiry time from JWT access token."""
    body = decode_jwt_body(access_token)
    return datetime.fromtimestamp(body["exp"], tz=timezone.utc)


def _refresh_access_token(
    refresh_token: str,
    client_id: str,
    client_secret: str,
) -> tuple[str, str | None]:
    """Exchange a refresh token for a new access token.

    Returns ``(access_token, rotated_refresh_token)``. The second
    element is ``None`` when the server returned no ``refresh_token``
    field, indicating the original refresh token is still valid; it is
    a string when the server rotated the refresh token, in which case
    callers MUST persist the new value alongside the new access token.

    The current SweatStack OAuth server does not rotate refresh tokens
    on ``/oauth/token``; the tuple shape exists so that a future
    server change is handled transparently.
    """
    response = httpx.post(
        f"{DEFAULT_URL}/api/v1/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=REFRESH_HTTP_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    rotated = payload.get("refresh_token")
    if rotated == refresh_token:
        # Server echoed the same refresh token. Treat as no-rotation so
        # downstream cache logic can take the simpler ``set`` path.
        rotated = None
    return payload["access_token"], rotated


def _resolve_access_token(
    access_token: str, refresh_token: str
) -> CachedAccessToken:
    """Return a fresh access token (plus its refresh token) for a session.

    Hits the access-token cache first. On a miss, serialises concurrent
    callers per refresh token so that an N-way race for the same session
    collapses to a single ``/oauth/token`` call; late waiters return
    the freshly-cached value instead of issuing their own refresh.

    The returned ``access_token`` equals the input when no refresh was
    needed. The returned ``refresh_token`` equals the input unless the
    OAuth server rotated it during a refresh — callers should compare
    both fields against their inputs to decide whether to persist a
    new cookie / token-store row.

    Raises:
        RefreshLockTimeout: if a peer refresh has held the per-session
            lock for longer than :data:`REFRESH_LOCK_TIMEOUT`.
        Exception: any error raised by ``/oauth/token`` is propagated
            unchanged after invalidating the cache entry.
    """
    config = get_config()
    cache = config.access_token_cache
    fp = _key_fingerprint(refresh_token)

    cached = cache.get(refresh_token)
    if cached and cached.is_fresh(TOKEN_EXPIRY_MARGIN):
        logger.debug("access-token cache hit (session=%s)", fp)
        return cached

    if not _is_token_expiring(access_token):
        # The caller's token is still good. Seed the cache so parallel
        # requests for this session also fast-path. We only reach this
        # branch when ``cached`` was None or stale, so the write is
        # never redundant with a fresh entry.
        value = CachedAccessToken(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=_extract_expiry(access_token).timestamp(),
        )
        cache.set(refresh_token, value)
        logger.debug("access-token cache seed on fresh token (session=%s)", fp)
        return value

    with cache.lock(refresh_token, timeout=REFRESH_LOCK_TIMEOUT) as acquired:
        if not acquired:
            logger.warning(
                "access-token refresh lock timed out after %.1fs (session=%s)",
                REFRESH_LOCK_TIMEOUT,
                fp,
            )
            raise RefreshLockTimeout(
                f"Timed out waiting {REFRESH_LOCK_TIMEOUT}s for peer refresh"
            )

        # Re-check: a peer may have refreshed while we waited.
        cached = cache.get(refresh_token)
        if cached and cached.is_fresh(TOKEN_EXPIRY_MARGIN):
            logger.debug(
                "access-token cache hit after lock (peer refreshed; session=%s)",
                fp,
            )
            return cached

        try:
            new_access_token, rotated_refresh_token = _refresh_access_token(
                refresh_token=refresh_token,
                client_id=config.client_id,
                client_secret=config.client_secret.get_secret_value(),
            )
        except Exception:
            # Don't let a failed refresh strand a stale token in the cache.
            cache.invalidate(refresh_token)
            logger.debug(
                "access-token refresh failed; cache invalidated (session=%s)", fp
            )
            raise

        effective_refresh_token = rotated_refresh_token or refresh_token
        value = CachedAccessToken(
            access_token=new_access_token,
            refresh_token=effective_refresh_token,
            expires_at=_extract_expiry(new_access_token).timestamp(),
        )

        if rotated_refresh_token and rotated_refresh_token != refresh_token:
            # Make the new value visible under both keys: in-flight
            # peers still arriving with the old refresh token continue
            # to hit, and future requests carrying the rotated token
            # (from a freshly-written cookie / token store) also hit.
            cache.migrate(
                old_key=refresh_token,
                new_key=rotated_refresh_token,
                value=value,
            )
            logger.info(
                "access-token refresh rotated refresh token (session=%s -> %s)",
                fp,
                _key_fingerprint(rotated_refresh_token),
            )
        else:
            cache.set(refresh_token, value)
            logger.debug(
                "access-token refresh completed (session=%s)", fp
            )
        return value


def _refresh_tokens_if_needed(tokens: TokenSet) -> TokenSet | None:
    """Refresh tokens if the access token is expiring.

    Returns a new ``TokenSet`` if either the access token or the
    refresh token changed, ``None`` if the existing pair is still
    valid. Concurrent callers for the same session share a single
    underlying ``/oauth/token`` call via the access-token cache.
    """
    resolved = _resolve_access_token(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
    )
    if (
        resolved.access_token == tokens.access_token
        and resolved.refresh_token == tokens.refresh_token
    ):
        return None
    return TokenSet(
        access_token=resolved.access_token,
        refresh_token=resolved.refresh_token,
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
# Webhook user loading
# ---------------------------------------------------------------------------


def _load_user_from_store(user_id: str) -> SweatStackUser:
    """Load user from TokenStore for webhook context.

    Args:
        user_id: The user ID from the webhook payload.

    Returns:
        SweatStackUser with tokens loaded from the store.

    Raises:
        WebhookTokenStoreError: If token_store is not configured.
        WebhookUserNotFoundError: If no tokens exist for the user.
        WebhookTokenRefreshError: If token refresh fails.
    """
    # Import here to avoid circular imports
    from .webhooks import (
        WebhookTokenRefreshError,
        WebhookTokenStoreError,
        WebhookUserNotFoundError,
    )

    config = get_config()

    if not config.token_store:
        raise WebhookTokenStoreError(
            "TokenStore required when using AuthenticatedUser in webhook handlers. "
            "Configure with: configure(token_store=...)"
        )

    tokens = config.token_store.load(user_id)
    if not tokens:
        raise WebhookUserNotFoundError(
            f"No stored tokens for user {user_id}. "
            "User may not have authenticated with your app yet."
        )

    try:
        resolved = _resolve_access_token(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
        )
    except Exception as e:
        raise WebhookTokenRefreshError(
            f"Failed to refresh tokens for user {user_id}: {e}"
        ) from e

    if (
        resolved.access_token != tokens.access_token
        or resolved.refresh_token != tokens.refresh_token
    ):
        tokens = StoredTokens(
            user_id=tokens.user_id,
            access_token=resolved.access_token,
            refresh_token=resolved.refresh_token,
            expires_at=_extract_expiry(resolved.access_token),
        )
        config.token_store.save(tokens)

    return SweatStackUser(
        client=Client(
            api_key=tokens.access_token,
            refresh_token=tokens.refresh_token,
            client_id=config.client_id,
            client_secret=config.client_secret,
        )
    )


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
            # Persist refreshed principal tokens to store if configured
            if config.token_store:
                config.token_store.save(
                    StoredTokens(
                        user_id=refreshed.user_id,
                        access_token=refreshed.access_token,
                        refresh_token=refreshed.refresh_token,
                        expires_at=_extract_expiry(refreshed.access_token),
                    )
                )
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


async def _require_authenticated_user(
    request: Request,
    response: Response,
) -> SweatStackUser:
    """Dependency: always returns principal user.

    In webhook context (detected by X-Sweatstack-Signature header),
    loads the user from TokenStore instead of session cookie.
    """
    # Import here to avoid circular imports
    from .webhooks import WebhookPayloadModel, _detect_webhook_context

    # Check if this is a webhook request
    webhook_context: WebhookPayloadModel | None = await _detect_webhook_context(request)

    if webhook_context:
        # Webhook context: load from TokenStore
        return _load_user_from_store(webhook_context.user_id)

    # Browser context: load from cookie
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
