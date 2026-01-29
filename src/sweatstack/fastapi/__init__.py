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
        return user.client.get_activities()

    @app.get("/my-athletes")
    def get_athletes(user: AuthenticatedUser):
        # Always returns the principal user's accessible users
        return user.client.get_users()

User Switching:
    The module supports two methods of user switching:

    1. URL-based switching (recommended for web apps):
        Use urls.select_user(user_id) and urls.select_self() in templates:

        <form method="post" action="{{ urls.select_user(athlete.id) }}">
            <button>View as {{ athlete.name }}</button>
        </form>

    2. Programmatic switching:
        Call client.switch_user() in your endpoint code:

        @app.post("/select/{athlete_id}")
        def select(athlete_id: str, user: AuthenticatedUser):
            user.client.switch_user(athlete_id)
            return RedirectResponse("/dashboard")

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
    )

from .config import configure, urls
from .dependencies import (
    AuthenticatedUser,
    OptionalSelectedUser,
    OptionalUser,
    SelectedUser,
    SweatStackUser,
)
from .routes import instrument

__all__ = [
    # Configuration
    "configure",
    "instrument",
    "urls",
    # User types
    "SweatStackUser",
    # Dependencies
    "AuthenticatedUser",
    "OptionalUser",
    "SelectedUser",
    "OptionalSelectedUser",
]
