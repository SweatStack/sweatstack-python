from . import _renames
from .client import *  # noqa: F403
from .client import __all__ as _client_all
from .exceptions import (
    SweatStackAPIError,
    SweatStackAuthError,
    SweatStackBadRequestError,
    SweatStackConnectionError,
    SweatStackError,
    SweatStackNotFoundError,
    SweatStackRateLimitError,
    SweatStackServerError,
    SweatStackTokenRefreshError,
)

__all__ = sorted(
    [
        *_client_all,
        "SweatStackAPIError",
        "SweatStackAuthError",
        "SweatStackBadRequestError",
        "SweatStackConnectionError",
        "SweatStackError",
        "SweatStackNotFoundError",
        "SweatStackRateLimitError",
        "SweatStackServerError",
        "SweatStackTokenRefreshError",
    ]
)


def __getattr__(name: str):
    # Only reached when normal lookup fails: names a removed function's replacement (PEP 562).
    raise _renames.attribute_error("module 'sweatstack'", name, prefix="sweatstack")
