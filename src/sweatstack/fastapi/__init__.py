"""FastAPI integration for SweatStack authentication.

This module provides OAuth authentication for FastAPI applications using
SweatStack as the identity provider.

Example:
    from fastapi import FastAPI
    from sweatstack.fastapi import configure, instrument, AuthenticatedUser

    configure()  # uses environment variables

    app = FastAPI()
    instrument(app)

    @app.get("/me")
    def get_me(user: AuthenticatedUser):
        return user.client.get_userinfo()
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
    OptionalUser,
    SweatStackUser,
)
from .routes import instrument

__all__ = [
    "configure",
    "instrument",
    "AuthenticatedUser",
    "OptionalUser",
    "SweatStackUser",
    "urls",
]
