"""FastAPI integration for SweatStack authentication.

This module provides OAuth authentication for FastAPI applications using
SweatStack as the identity provider. It includes support for user switching,
allowing applications like coaching platforms to view data on behalf of
other users.

Example:
    from fastapi import FastAPI
    from sweatstack.fastapi import configure, instrument, AuthenticatedUser, SelectedUser, urls

    configure()  # uses environment variables

    app = FastAPI()
    instrument(app)

    @app.get("/activities")
    def get_activities(user: SelectedUser):
        # Returns activities for the currently selected user
        return user.client.activities.list()

    @app.get("/my-athletes")
    def get_athletes(user: AuthenticatedUser):
        # Always returns the principal user's accessible users
        return user.client.users.list()

User Switching:
    The module supports two methods of user switching:

    1. URL-based switching (recommended for web apps):
        Use urls.select_user(user_id) and urls.select_self() in templates:

        <form method="post" action="{{ urls.select_user(athlete.id) }}">
            <button>View as {{ athlete.name }}</button>
        </form>

    2. A client for another user within one request:
        delegated_client() returns a new client and leaves user.client unchanged:

        @app.get("/athletes/{athlete_id}/latest")
        def athlete_latest(athlete_id: str, user: AuthenticatedUser):
            athlete = user.client.delegated_client(athlete_id)
            return athlete.activities.latest()

Dependency Types:
    - AuthenticatedUser: Always returns the principal (logged-in) user
    - OptionalUser: Returns principal or None if not authenticated
    - SelectedUser: Returns the selected user (delegated or principal)
    - OptionalSelectedUser: Returns selected user or None if not authenticated
"""

try:
    import fastapi  # noqa: F401
except ImportError:
    raise ImportError(
        "FastAPI is required for sweatstack.fastapi. "
        "Install it with: pip install 'sweatstack[fastapi]'"
    ) from None

from .access_token_cache import (
    AccessTokenCache,
    CachedAccessToken,
    InMemoryAccessTokenCache,
)
from .config import configure, urls
from .dependencies import (
    AuthenticatedUser,
    OptionalSelectedUser,
    OptionalUser,
    RefreshLockTimeout,
    SelectedUser,
    SweatStackUser,
)
from .models import StoredTokens, TokenStore
from .routes import instrument
from .token_stores import EncryptedSQLiteTokenStore, SQLiteTokenStore
from .webhooks import (
    WebhookError,
    WebhookPayload,
    WebhookPayloadModel,
    WebhookTokenRefreshError,
    WebhookTokenStoreError,
    WebhookUserNotFoundError,
    WebhookVerificationError,
    verify_signature,
)

__all__ = [
    # Configuration
    "configure",
    "instrument",
    "urls",
    # User types
    "SweatStackUser",
    # User dependencies
    "AuthenticatedUser",
    "OptionalUser",
    "SelectedUser",
    "OptionalSelectedUser",
    # Webhook dependencies
    "WebhookPayload",
    "WebhookPayloadModel",
    # Token storage
    "TokenStore",
    "StoredTokens",
    "SQLiteTokenStore",
    "EncryptedSQLiteTokenStore",
    # Refresh de-duplication
    "AccessTokenCache",
    "CachedAccessToken",
    "InMemoryAccessTokenCache",
    "RefreshLockTimeout",
    # Webhook utilities
    "verify_signature",
    # Exceptions
    "WebhookError",
    "WebhookVerificationError",
    "WebhookTokenStoreError",
    "WebhookUserNotFoundError",
    "WebhookTokenRefreshError",
]
