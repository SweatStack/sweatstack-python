"""The HTTP layer under ``Client``: one connection pool per client, and the retry policy.

The policy follows the OpenAI, Anthropic and Stripe clients, with one difference: ``POST`` is
never retried, because the SweatStack API has no idempotency keys and a retried create could
create twice.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx

RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
"""Statuses worth retrying: timeouts, rate limits and transient server errors."""

RETRYABLE_METHODS = frozenset({"get", "put", "delete"})
"""Methods a retry cannot duplicate: reads, full replaces and deletes. Never ``post``."""

MAX_BACKOFF = 8.0
"""Longest wait between two attempts, in seconds, when the server sends no ``Retry-After``."""

MAX_RETRY_AFTER = 60.0
"""Longest ``Retry-After`` the client honours; a longer one fails the call immediately."""

RETRY_BUDGET = 30.0
"""Most time one call may spend waiting between attempts, in seconds."""


def backoff(attempt: int) -> float:
    """Seconds to wait before retry number ``attempt + 1``: 0.5 s, 1 s, 2 s, ... ±25 %, at most 8 s."""
    return min(0.5 * 2**attempt * random.uniform(0.75, 1.25), MAX_BACKOFF)


def retry_after(response: httpx.Response) -> float | None:
    """The response's ``Retry-After`` in seconds, if it sent one as a number."""
    try:
        return float(response.headers["retry-after"])
    except (KeyError, ValueError):
        return None


def wait_before_retry(
    method: str,
    attempt: int,
    max_retries: int,
    waited: float,
    response: httpx.Response | None = None,
) -> float | None:
    """How long to wait before retrying, or ``None`` to stop.

    Args:
        method: The request's method, lower case.
        attempt: How many retries have already been made.
        max_retries: The client's ``max_retries``.
        waited: Seconds this call has already spent waiting.
        response: The error response, or ``None`` after a connection error or timeout.
    """
    if method not in RETRYABLE_METHODS or attempt >= max_retries:
        return None
    if response is not None and response.status_code not in RETRY_STATUSES:
        return None
    wait = retry_after(response) if response is not None else None
    if wait is None:
        wait = backoff(attempt)
    elif wait > MAX_RETRY_AFTER:
        return None
    if waited + wait > RETRY_BUDGET:
        return None
    return wait


class Session:
    """One request scope on the client's shared connection pool, with its own headers.

    The pool is shared by every request of a ``Client``; the headers (which bearer token, if
    any) are per request, because a token can be refreshed between two requests and some
    endpoints must never see it.
    """

    def __init__(self, http: httpx.Client, headers: httpx.Headers, timeout: float) -> None:
        self._http = http
        self.headers = headers
        self._timeout = timeout

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        return self._http.request(method, url, headers=self.headers, **kwargs)

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", url, **kwargs)

    @contextmanager
    def stream(self, method: str, url: str, **kwargs: Any) -> Iterator[httpx.Response]:
        """A streaming request. No read timeout: a stream may stay quiet for a while."""
        timeout = httpx.Timeout(self._timeout, read=None)
        with self._http.stream(method, url, headers=self.headers, timeout=timeout, **kwargs) as r:
            yield r
