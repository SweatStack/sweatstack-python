"""Tests for ``/oauth/token`` refresh de-duplication.

Covers three layers:

1. The pure cache primitive (:class:`InMemoryAccessTokenCache`) —
   LRU bounds, striped locking, migration on refresh-token rotation.
2. The integration helper :func:`_resolve_access_token`, which is the
   only call site of the cache inside the library. The integration
   tests assert the user-observable property — concurrent expiring
   requests for the same session collapse to a single refresh — by
   counting calls to a stubbed ``_refresh_access_token``.
3. The thin :func:`_refresh_tokens_if_needed` wrapper used by the
   cookie-backed code path.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from sweatstack.fastapi import (
    CachedAccessToken,
    InMemoryAccessTokenCache,
    configure,
)
from sweatstack.fastapi import dependencies as deps


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_config():
    """Reset module-level config between tests."""
    import sweatstack.fastapi.config as config_module

    config_module._config = None
    yield
    config_module._config = None


@pytest.fixture
def configure_app():
    """Configure the plugin with a fresh in-memory access-token cache.

    Returns the cache so individual tests can inspect or pre-seed it.
    """
    cache = InMemoryAccessTokenCache()
    configure(
        client_id="test_client_id",
        client_secret="test_client_secret",
        app_url="http://localhost:8000",
        session_secret="dGVzdC1vbmx5LWtleS1mb3ItdW5pdC10ZXN0cy0zMmI=",
        access_token_cache=cache,
    )
    return cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _jwt(*, exp: float, sub: str = "user_1") -> str:
    """Build a JWT-shaped string whose body decodes to the given claims.

    The signature segment is unused (``decode_jwt_body`` only reads the
    body), but we include a non-empty value so the token shape is
    realistic.
    """
    body = {"exp": int(exp), "sub": sub}
    encoded = base64.urlsafe_b64encode(json.dumps(body).encode()).rstrip(b"=").decode()
    return f"header.{encoded}.signature"


def _make(access_token: str, refresh_token: str, ttl: float = 900) -> CachedAccessToken:
    return CachedAccessToken(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=time.time() + ttl,
    )


# ---------------------------------------------------------------------------
# CachedAccessToken
# ---------------------------------------------------------------------------


class TestCachedAccessToken:
    def test_is_fresh_respects_margin(self):
        now = time.time()
        assert CachedAccessToken("at", "rt", now + 100).is_fresh(margin_seconds=5)
        assert not CachedAccessToken("at", "rt", now + 3).is_fresh(margin_seconds=5)
        assert not CachedAccessToken("at", "rt", now - 1).is_fresh(margin_seconds=5)

    def test_is_immutable(self):
        token = CachedAccessToken("at", "rt", time.time() + 100)
        with pytest.raises(Exception):
            token.access_token = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# InMemoryAccessTokenCache — primitives
# ---------------------------------------------------------------------------


class TestInMemoryAccessTokenCachePrimitives:
    def test_get_returns_none_for_unknown_key(self):
        cache = InMemoryAccessTokenCache()
        assert cache.get("never-seen") is None

    def test_set_then_get_roundtrips(self):
        cache = InMemoryAccessTokenCache()
        value = _make("at", "rt")
        cache.set("rt", value)
        assert cache.get("rt") == value

    def test_set_overwrites_existing(self):
        cache = InMemoryAccessTokenCache()
        cache.set("rt", _make("at-1", "rt"))
        cache.set("rt", _make("at-2", "rt"))
        cached = cache.get("rt")
        assert cached is not None and cached.access_token == "at-2"

    def test_invalidate_drops_value(self):
        cache = InMemoryAccessTokenCache()
        cache.set("rt", _make("at", "rt"))
        cache.invalidate("rt")
        assert cache.get("rt") is None

    def test_invalidate_is_idempotent_on_unknown_key(self):
        cache = InMemoryAccessTokenCache()
        cache.invalidate("never-seen")  # must not raise

    def test_construction_validates_bounds(self):
        with pytest.raises(ValueError):
            InMemoryAccessTokenCache(max_entries=0)
        with pytest.raises(ValueError):
            InMemoryAccessTokenCache(lock_stripes=0)


# ---------------------------------------------------------------------------
# InMemoryAccessTokenCache — LRU bound
# ---------------------------------------------------------------------------


class TestLRUEviction:
    def test_oldest_entry_is_evicted_when_over_cap(self):
        cache = InMemoryAccessTokenCache(max_entries=3)
        for i in range(3):
            cache.set(f"rt-{i}", _make(f"at-{i}", f"rt-{i}"))
        cache.set("rt-3", _make("at-3", "rt-3"))

        assert cache.get("rt-0") is None
        assert cache.get("rt-3") is not None

    def test_get_promotes_to_most_recent(self):
        """A recently-read entry must survive the next eviction."""
        cache = InMemoryAccessTokenCache(max_entries=3)
        for i in range(3):
            cache.set(f"rt-{i}", _make(f"at-{i}", f"rt-{i}"))

        # Touch rt-0; it should now be most-recent.
        assert cache.get("rt-0") is not None
        cache.set("rt-3", _make("at-3", "rt-3"))

        # rt-1 was the new oldest; rt-0 must survive.
        assert cache.get("rt-0") is not None
        assert cache.get("rt-1") is None

    def test_invalidate_does_not_consume_capacity(self):
        cache = InMemoryAccessTokenCache(max_entries=2)
        cache.set("rt-0", _make("at-0", "rt-0"))
        cache.set("rt-1", _make("at-1", "rt-1"))
        cache.invalidate("rt-0")
        cache.set("rt-2", _make("at-2", "rt-2"))
        # rt-1 must still be present: invalidation freed a slot.
        assert cache.get("rt-1") is not None
        assert cache.get("rt-2") is not None


# ---------------------------------------------------------------------------
# InMemoryAccessTokenCache — lock semantics
# ---------------------------------------------------------------------------


class TestLockSemantics:
    def test_lock_yields_true_on_acquire_and_false_on_timeout(self):
        cache = InMemoryAccessTokenCache(lock_stripes=4)
        with cache.lock("rt", timeout=0) as outer:
            assert outer is True

            def try_acquire():
                with cache.lock("rt", timeout=0) as inner:
                    return inner

            with ThreadPoolExecutor(max_workers=1) as pool:
                # Same key, contested → must time out.
                assert pool.submit(try_acquire).result(timeout=1) is False

    def test_lock_releases_on_exit(self):
        cache = InMemoryAccessTokenCache()
        with cache.lock("rt", timeout=0):
            pass
        # Re-acquire after exit must succeed immediately.
        with cache.lock("rt", timeout=0) as held:
            assert held is True

    def test_lock_with_no_timeout_blocks_until_available(self):
        cache = InMemoryAccessTokenCache(lock_stripes=4)
        released = threading.Event()
        waiter_acquired = threading.Event()

        def hold_then_release():
            with cache.lock("rt", timeout=0) as held:
                assert held
                # Hold until the waiter has clearly started blocking.
                time.sleep(0.05)
            released.set()

        def waiter():
            # No timeout → must block until the holder releases.
            with cache.lock("rt") as held:
                assert held
                waiter_acquired.set()

        holder_thread = threading.Thread(target=hold_then_release)
        waiter_thread = threading.Thread(target=waiter)
        holder_thread.start()
        # Give the holder a head-start so it wins the race for the lock.
        time.sleep(0.01)
        waiter_thread.start()

        holder_thread.join(timeout=2)
        waiter_thread.join(timeout=2)
        assert released.is_set()
        assert waiter_acquired.is_set()

    def test_invalidate_does_not_break_serialisation(self):
        """After a failed refresh invalidates the value, the next
        caller must still be serialised by the same stripe — i.e. the
        lock manager is independent of the cache table."""
        cache = InMemoryAccessTokenCache(lock_stripes=4)
        cache.set("rt", _make("at", "rt"))
        cache.invalidate("rt")
        with cache.lock("rt", timeout=0) as outer:
            assert outer
            with ThreadPoolExecutor(max_workers=1) as pool:
                def contended():
                    with cache.lock("rt", timeout=0) as inner:
                        return inner
                assert pool.submit(contended).result(timeout=1) is False


# ---------------------------------------------------------------------------
# InMemoryAccessTokenCache — migration (refresh-token rotation)
# ---------------------------------------------------------------------------


class TestMigrate:
    def test_migrate_makes_value_visible_under_both_keys(self):
        cache = InMemoryAccessTokenCache()
        value = _make("at-new", "rt-new")
        cache.migrate(old_key="rt-old", new_key="rt-new", value=value)
        assert cache.get("rt-old") == value
        assert cache.get("rt-new") == value

    def test_migrate_with_equal_keys_is_a_set(self):
        cache = InMemoryAccessTokenCache(max_entries=2)
        value = _make("at", "rt")
        cache.migrate(old_key="rt", new_key="rt", value=value)
        # Must consume exactly one slot, not two.
        cache.set("rt-other", _make("at-other", "rt-other"))
        assert cache.get("rt") == value
        assert cache.get("rt-other") is not None

    def test_migrate_promotes_both_keys_to_most_recent(self):
        cache = InMemoryAccessTokenCache(max_entries=3)
        cache.set("rt-a", _make("at-a", "rt-a"))
        cache.set("rt-b", _make("at-b", "rt-b"))
        cache.migrate(
            old_key="rt-old",
            new_key="rt-new",
            value=_make("at-new", "rt-new"),
        )
        # rt-a is now the oldest; the next set evicts it, not the
        # freshly-migrated pair.
        cache.set("rt-c", _make("at-c", "rt-c"))
        assert cache.get("rt-a") is None
        assert cache.get("rt-old") is not None
        assert cache.get("rt-new") is not None


# ---------------------------------------------------------------------------
# _resolve_access_token — integration
# ---------------------------------------------------------------------------


class TestResolveAccessToken:
    def test_fresh_token_is_returned_unchanged_and_cached(self, configure_app):
        cache = configure_app
        token = _jwt(exp=time.time() + 900)

        with patch.object(deps, "_refresh_access_token") as refresh:
            result = deps._resolve_access_token(access_token=token, refresh_token="rt")

        assert result.access_token == token
        assert result.refresh_token == "rt"
        refresh.assert_not_called()

        cached = cache.get("rt")
        assert cached is not None and cached.access_token == token

    def test_cache_hit_short_circuits_refresh(self, configure_app):
        """A cached fresh token wins even if the cookie's token is stale."""
        cache = configure_app
        stale_token = _jwt(exp=time.time() - 60)
        fresh_token = _jwt(exp=time.time() + 900)
        cache.set("rt", _make(fresh_token, "rt"))

        with patch.object(deps, "_refresh_access_token") as refresh:
            result = deps._resolve_access_token(access_token=stale_token, refresh_token="rt")

        assert result.access_token == fresh_token
        refresh.assert_not_called()

    def test_expiring_token_triggers_refresh_and_populates_cache(self, configure_app):
        cache = configure_app
        stale_token = _jwt(exp=time.time() - 60)
        fresh_token = _jwt(exp=time.time() + 900)

        with patch.object(
            deps, "_refresh_access_token", return_value=(fresh_token, None)
        ) as refresh:
            result = deps._resolve_access_token(access_token=stale_token, refresh_token="rt")

        assert result.access_token == fresh_token
        assert result.refresh_token == "rt"
        refresh.assert_called_once()
        cached = cache.get("rt")
        assert cached is not None and cached.access_token == fresh_token

    def test_concurrent_expiring_requests_collapse_to_single_refresh(self, configure_app):
        """The reason this module exists: N concurrent requests for the
        same expiring session must produce exactly one ``/oauth/token``
        call. The late waiters serve from the cache the first writer
        populated.
        """
        stale_token = _jwt(exp=time.time() - 60)
        fresh_token = _jwt(exp=time.time() + 900)
        gate = threading.Event()
        call_count = 0
        call_count_lock = threading.Lock()

        def slow_refresh(*, refresh_token, client_id, client_secret):
            nonlocal call_count
            with call_count_lock:
                call_count += 1
            # Hold the refresh open long enough that all peers pile up
            # on the per-session lock before we return.
            gate.wait(timeout=5)
            return fresh_token, None

        with patch.object(deps, "_refresh_access_token", side_effect=slow_refresh):
            with ThreadPoolExecutor(max_workers=20) as pool:
                futures = [
                    pool.submit(
                        deps._resolve_access_token,
                        access_token=stale_token,
                        refresh_token="rt",
                    )
                    for _ in range(20)
                ]
                # Let the first request reach the network call, then release.
                time.sleep(0.05)
                gate.set()
                results = [f.result(timeout=5) for f in futures]

        assert all(r.access_token == fresh_token for r in results)
        assert call_count == 1

    def test_different_refresh_tokens_do_not_interfere(self, configure_app):
        """Each session gets its own cache slot. (They may share a
        stripe, but a single sequential call sequence won't observe
        that.)"""
        stale_a = _jwt(exp=time.time() - 60, sub="user_a")
        stale_b = _jwt(exp=time.time() - 60, sub="user_b")
        fresh_a = _jwt(exp=time.time() + 900, sub="user_a")
        fresh_b = _jwt(exp=time.time() + 900, sub="user_b")

        def fake_refresh(*, refresh_token, **_):
            return {"rt_a": (fresh_a, None), "rt_b": (fresh_b, None)}[refresh_token]

        with patch.object(deps, "_refresh_access_token", side_effect=fake_refresh) as refresh:
            ra = deps._resolve_access_token(access_token=stale_a, refresh_token="rt_a")
            rb = deps._resolve_access_token(access_token=stale_b, refresh_token="rt_b")

        assert ra.access_token == fresh_a
        assert rb.access_token == fresh_b
        assert refresh.call_count == 2

    def test_refresh_failure_invalidates_cache_and_propagates(self, configure_app):
        cache = configure_app
        stale_token = _jwt(exp=time.time() - 60)
        cache.set("rt", _make(stale_token, "rt", ttl=-60))

        boom = RuntimeError("refresh blew up")
        with patch.object(deps, "_refresh_access_token", side_effect=boom):
            with pytest.raises(RuntimeError, match="refresh blew up"):
                deps._resolve_access_token(access_token=stale_token, refresh_token="rt")

        assert cache.get("rt") is None

    def test_failed_refresh_does_not_starve_subsequent_caller(self, configure_app):
        stale_token = _jwt(exp=time.time() - 60)
        fresh_token = _jwt(exp=time.time() + 900)
        outcomes: list = [RuntimeError("first try fails"), (fresh_token, None)]

        def flaky_refresh(*, refresh_token, **_):
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with patch.object(deps, "_refresh_access_token", side_effect=flaky_refresh):
            with pytest.raises(RuntimeError):
                deps._resolve_access_token(access_token=stale_token, refresh_token="rt")
            result = deps._resolve_access_token(access_token=stale_token, refresh_token="rt")

        assert result.access_token == fresh_token

    def test_rotation_migrates_cache_under_new_key(self, configure_app):
        """If ``/oauth/token`` returns a new refresh token, future
        requests with that new key must hit the cache without a
        second refresh call, AND in-flight peers still arriving with
        the old key must continue to hit."""
        cache = configure_app
        stale_token = _jwt(exp=time.time() - 60)
        fresh_token = _jwt(exp=time.time() + 900)

        with patch.object(
            deps, "_refresh_access_token", return_value=(fresh_token, "rt-new")
        ) as refresh:
            result = deps._resolve_access_token(
                access_token=stale_token, refresh_token="rt-old"
            )

        assert result.access_token == fresh_token
        assert result.refresh_token == "rt-new"
        refresh.assert_called_once()

        # Both keys point at the new value.
        old_hit = cache.get("rt-old")
        new_hit = cache.get("rt-new")
        assert old_hit is not None and old_hit.access_token == fresh_token
        assert new_hit is not None and new_hit.access_token == fresh_token

        # Subsequent request with the new key short-circuits — no second refresh.
        with patch.object(deps, "_refresh_access_token") as refresh2:
            second = deps._resolve_access_token(
                access_token=stale_token, refresh_token="rt-new"
            )
        assert second.access_token == fresh_token
        refresh2.assert_not_called()

    def test_server_echoes_same_refresh_token_is_treated_as_no_rotation(self, configure_app):
        """If the server returns the same refresh token in the response,
        we must not invoke the migration path (which would write under
        two identical keys and waste capacity)."""
        cache = configure_app
        stale_token = _jwt(exp=time.time() - 60)
        fresh_token = _jwt(exp=time.time() + 900)

        with patch.object(
            deps, "_refresh_access_token", return_value=(fresh_token, "rt")
        ):
            result = deps._resolve_access_token(access_token=stale_token, refresh_token="rt")

        assert result.refresh_token == "rt"
        assert cache.get("rt") is not None

    def test_refresh_lock_timeout_raises(self, configure_app, monkeypatch):
        """When a peer holds the lock past the timeout, the waiter
        must surface :class:`RefreshLockTimeout` instead of blocking a
        threadpool worker indefinitely."""
        cache = configure_app
        stale_token = _jwt(exp=time.time() - 60)

        # Make the timeout very small so the test runs fast.
        monkeypatch.setattr(deps, "REFRESH_LOCK_TIMEOUT", 0.05)

        # Hold the stripe lock for this key.
        holder_acquired = threading.Event()
        release_holder = threading.Event()

        def hold_lock():
            with cache.lock("rt", timeout=1) as held:
                assert held
                holder_acquired.set()
                release_holder.wait(timeout=2)

        with ThreadPoolExecutor(max_workers=1) as pool:
            holder = pool.submit(hold_lock)
            assert holder_acquired.wait(timeout=1)
            try:
                with pytest.raises(deps.RefreshLockTimeout):
                    deps._resolve_access_token(
                        access_token=stale_token, refresh_token="rt"
                    )
            finally:
                release_holder.set()
            holder.result(timeout=2)


# ---------------------------------------------------------------------------
# _refresh_tokens_if_needed wrapper
# ---------------------------------------------------------------------------


class TestRefreshTokensIfNeeded:
    """Thin wrapper around _resolve_access_token; verifies the
    ``return None when unchanged`` contract used to decide whether the
    session cookie needs rewriting."""

    def test_returns_none_when_token_is_fresh(self, configure_app):
        from sweatstack.fastapi.models import TokenSet

        token = _jwt(exp=time.time() + 900)
        tokens = TokenSet(access_token=token, refresh_token="rt", user_id="user_1")

        with patch.object(deps, "_refresh_access_token") as refresh:
            assert deps._refresh_tokens_if_needed(tokens) is None
        refresh.assert_not_called()

    def test_returns_new_tokenset_when_access_token_refreshed(self, configure_app):
        from sweatstack.fastapi.models import TokenSet

        stale_token = _jwt(exp=time.time() - 60)
        fresh_token = _jwt(exp=time.time() + 900)
        tokens = TokenSet(access_token=stale_token, refresh_token="rt", user_id="user_1")

        with patch.object(
            deps, "_refresh_access_token", return_value=(fresh_token, None)
        ):
            result = deps._refresh_tokens_if_needed(tokens)

        assert result is not None
        assert result.access_token == fresh_token
        assert result.refresh_token == "rt"
        assert result.user_id == "user_1"

    def test_returns_new_tokenset_when_refresh_token_rotates(self, configure_app):
        """Rotation of the refresh token alone (extremely rare; access
        token unchanged) must still produce a new TokenSet so the
        cookie/store is rewritten."""
        from sweatstack.fastapi.models import TokenSet

        stale_token = _jwt(exp=time.time() - 60)
        fresh_token = _jwt(exp=time.time() + 900)
        tokens = TokenSet(access_token=stale_token, refresh_token="rt-old", user_id="u")

        with patch.object(
            deps, "_refresh_access_token", return_value=(fresh_token, "rt-new")
        ):
            result = deps._refresh_tokens_if_needed(tokens)

        assert result is not None
        assert result.access_token == fresh_token
        assert result.refresh_token == "rt-new"
