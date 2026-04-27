"""Typed exception hierarchy for the SweatStack client.

This module defines all exceptions raised by the SweatStack library.
No httpx types are exposed — this is the public error contract.
"""


class SweatStackError(Exception):
    """Base exception for all SweatStack errors."""


class SweatStackConnectionError(SweatStackError):
    """Transport-level failure: DNS, connect timeout, read timeout, no response."""


class SweatStackTokenRefreshError(SweatStackError):
    """Token refresh failed (expired, missing, or refresh request failed)."""


class SweatStackAPIError(SweatStackError):
    """HTTP response with an error status code."""

    def __init__(self, *, status_code: int, url: str, method: str, request_id: str | None = None, body: dict | str | None = None):
        self.status_code = status_code
        self.url = url
        self.method = method
        self.request_id = request_id
        self.body = body
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        msg = f"{self.status_code}: {self.method} {self.url}"
        if self.request_id:
            msg += f" (request_id={self.request_id})"
        if self.body:
            msg += f" — {self.body}"
        return msg

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(status_code={self.status_code!r}, "
            f"method={self.method!r}, url={self.url!r})"
        )


class SweatStackAuthError(SweatStackAPIError):
    """401 or 403: authentication or authorization failure."""


class SweatStackNotFoundError(SweatStackAPIError):
    """404: resource not found."""


class SweatStackRateLimitError(SweatStackAPIError):
    """429: rate limited."""

    def __init__(self, *, retry_after: int | None = None, **kwargs):
        self.retry_after = retry_after
        super().__init__(**kwargs)


class SweatStackBadRequestError(SweatStackAPIError):
    """4xx (not 401, 403, 404, 429): client sent invalid input."""


class SweatStackServerError(SweatStackAPIError):
    """5xx: server-side failure, transient, safe to retry for idempotent ops."""
