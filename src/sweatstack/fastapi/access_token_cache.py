"""De-duplication of concurrent ``/oauth/token`` refreshes.

The problem
-----------

``AuthenticatedUser`` resolves once per request. Each resolution reads
the session cookie, decides whether the access token inside is about to
expire, and — if so — calls ``/oauth/token`` to swap the refresh token
for a fresh access token, then writes the new pair back to the cookie.

The cookie write only reaches the browser when the response is sent.
Requests already in flight cannot see it. So when a single page-load
fans out into N concurrent fetches in the few-second window where the
cookie's access token is on the edge of expiry, all N independently
hit ``/oauth/token`` with the same refresh token.

The fix
-------

This module sits between the dependency and ``/oauth/token``. When a
refresh is needed, callers acquire a per-session lock and re-check the
cache; whichever caller wins the lock performs the single refresh and
stores the result, and the others return immediately with the cached
token.

The default implementation, :class:`InMemoryAccessTokenCache`, is
process-local. That is correct for single-process FastAPI deployments
(the common case for this library). Multi-worker deployments that need
cross-worker de-duplication can register a custom implementation —
e.g. one backed by Redis — via ``configure(access_token_cache=...)``.

The cache is keyed by **refresh token**, not user id. A user with two
parallel sessions (two browsers, two devices) gets two refresh tokens
and therefore two cache slots, so the sessions never invalidate each
other.

Refresh-token rotation
----------------------

The current SweatStack ``/oauth/token`` endpoint does **not** rotate
refresh tokens — every refresh returns the same refresh token. The
cache is keyed by refresh token specifically because that is a stable
per-session identifier under this assumption.

The cache is nonetheless rotation-aware: if a future server change
starts returning a new refresh token on refresh, ``_resolve_access_token``
calls :meth:`AccessTokenCache.migrate` to install the new value under
both the old and new keys, so in-flight peers that still hold the old
refresh token continue to hit the cache while future requests using the
new refresh token also fast-path. See :func:`migrate` for the contract.

Implementation notes
--------------------

The in-memory implementation uses **striped locks** rather than a lock
per key: a fixed pool of ``threading.Lock`` objects which keys are
hashed into. This decouples lock lifetime from cache entry lifetime,
so LRU eviction is a plain dict operation with no coordination with
in-flight refreshes. False sharing across stripes is bounded and
harmless — at worst two unrelated sessions briefly serialise on the
same stripe, which is well within the budget for a token refresh.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CachedAccessToken:
    """A refreshed access token plus the refresh token it was minted from.

    The refresh token is carried so callers can detect server-side
    rotation: if ``refresh_token`` differs from the one the caller
    supplied, the caller must persist the new refresh token (cookie,
    token store) alongside the new access token.

    Attributes:
        access_token: The OAuth access token (JWT).
        refresh_token: The refresh token associated with this access
            token. Equal to the caller's refresh token unless the
            server rotated it during the most recent refresh.
        expires_at: Unix epoch seconds at which the access token
            expires, as read from the JWT's ``exp`` claim.
    """

    access_token: str
    refresh_token: str
    expires_at: float

    def is_fresh(self, margin_seconds: float) -> bool:
        """Whether the token has more than ``margin_seconds`` left to live."""
        return self.expires_at - margin_seconds > time.time()


class AccessTokenCache(Protocol):
    """Cache for refreshed access tokens, with per-session refresh locking.

    Implementations must be safe to call concurrently from multiple
    threads. Keys are opaque strings (the SDK uses the session's
    refresh token).

    The intended call pattern is check-lock-recheck::

        cached = cache.get(key)
        if cached and cached.is_fresh(margin):
            return cached

        with cache.lock(key, timeout=lock_timeout) as acquired:
            if not acquired:
                raise SomeTimeoutError()
            cached = cache.get(key)               # peer may have refreshed
            if cached and cached.is_fresh(margin):
                return cached
            try:
                new_at, rotated_rt = do_refresh()
            except Exception:
                cache.invalidate(key)
                raise
            value = CachedAccessToken(new_at, rotated_rt or key, expires_at)
            if rotated_rt and rotated_rt != key:
                cache.migrate(old_key=key, new_key=rotated_rt, value=value)
            else:
                cache.set(key, value)
            return value
    """

    def get(self, key: str) -> CachedAccessToken | None:
        """Return the cached token for ``key``, or ``None`` if absent."""
        ...

    def set(self, key: str, value: CachedAccessToken) -> None:
        """Store ``value`` under ``key``, replacing any existing entry."""
        ...

    def invalidate(self, key: str) -> None:
        """Drop the cached token for ``key``.

        Implementations must keep the per-session lock for ``key``
        functional so concurrent refresh attempts continue to
        serialise after a failed refresh.
        """
        ...

    def migrate(self, *, old_key: str, new_key: str, value: CachedAccessToken) -> None:
        """Install ``value`` under both ``old_key`` and ``new_key`` atomically.

        Used when ``/oauth/token`` rotates the refresh token. Peers
        that started before the rotation reach the cache with
        ``old_key`` and must still hit; peers that start after the
        cookie/store has been updated reach the cache with ``new_key``
        and must hit too. ``old_key == new_key`` is a no-rotation
        special case and is equivalent to :meth:`set`.
        """
        ...

    def lock(self, key: str, *, timeout: float | None = None) -> AbstractContextManager[bool]:
        """Acquire the per-session refresh lock for ``key``.

        Returns a context manager that yields ``True`` if the lock was
        acquired (and will be released on exit), or ``False`` if the
        acquisition timed out. Callers MUST check the yielded value
        and only perform a refresh when it is ``True``.

        ``timeout`` is in seconds; ``None`` blocks indefinitely.
        """
        ...


# ---------------------------------------------------------------------------
# Default in-memory implementation
# ---------------------------------------------------------------------------


# Number of stripes in the lock pool. 64 is comfortably more than the
# number of concurrent refreshes a typical FastAPI process will ever
# see, so false sharing is rare; and a list of 64 locks costs ~3KB at
# startup, which is irrelevant.
_DEFAULT_LOCK_STRIPES = 64


# Default LRU cap. ~10k entries × ~2KB JWT ≈ 20MB worst case, which is
# the right shape for a library default: high enough that real
# deployments never hit it, low enough that a misuse cannot leak
# unbounded memory.
_DEFAULT_MAX_ENTRIES = 10_000


class InMemoryAccessTokenCache:
    """Process-local implementation of :class:`AccessTokenCache`.

    The cache is an LRU bounded by ``max_entries``. Locking is striped:
    keys hash into a fixed pool of ``lock_stripes`` ``threading.Lock``
    objects rather than allocating one lock per key. This means
    eviction is a pure dict operation that never needs to coordinate
    with in-flight refreshes — at worst two unrelated sessions whose
    keys collide on the same stripe briefly serialise.

    Both bounds are tuned for the common single-process FastAPI
    deployment; long-running processes with very high session churn or
    multi-worker deployments should consider swapping in an
    externally-backed implementation.
    """

    def __init__(
        self,
        *,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
        lock_stripes: int = _DEFAULT_LOCK_STRIPES,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        if lock_stripes < 1:
            raise ValueError("lock_stripes must be >= 1")
        self._max_entries = max_entries
        self._entries: OrderedDict[str, CachedAccessToken] = OrderedDict()
        self._table_lock = threading.Lock()
        self._stripes: tuple[threading.Lock, ...] = tuple(
            threading.Lock() for _ in range(lock_stripes)
        )

    def _stripe_for(self, key: str) -> threading.Lock:
        # ``hash(str)`` is randomised per-process (PYTHONHASHSEED), so
        # an attacker cannot deliberately collide all sessions onto
        # one stripe.
        return self._stripes[hash(key) % len(self._stripes)]

    def get(self, key: str) -> CachedAccessToken | None:
        with self._table_lock:
            value = self._entries.get(key)
            if value is not None:
                self._entries.move_to_end(key)
            return value

    def set(self, key: str, value: CachedAccessToken) -> None:
        with self._table_lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            self._evict_locked()

    def invalidate(self, key: str) -> None:
        with self._table_lock:
            self._entries.pop(key, None)

    def migrate(self, *, old_key: str, new_key: str, value: CachedAccessToken) -> None:
        with self._table_lock:
            self._entries[new_key] = value
            self._entries.move_to_end(new_key)
            if old_key != new_key:
                self._entries[old_key] = value
                self._entries.move_to_end(old_key)
            self._evict_locked()

    def _evict_locked(self) -> None:
        # Caller holds ``self._table_lock``. Drop oldest entries until
        # we're back under the cap. Entries are pure data; no locks
        # are tied to them, so eviction never strands a refresh.
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def lock(self, key: str, *, timeout: float | None = None) -> AbstractContextManager[bool]:
        return self._lock_cm(self._stripe_for(key), timeout)

    @staticmethod
    @contextmanager
    def _lock_cm(raw: threading.Lock, timeout: float | None) -> Iterator[bool]:
        # ``threading.Lock.acquire`` interprets ``timeout=-1`` as
        # "block indefinitely"; any non-negative value is honoured.
        acquired = raw.acquire(timeout=timeout if timeout is not None else -1)
        try:
            yield acquired
        finally:
            if acquired:
                raw.release()
