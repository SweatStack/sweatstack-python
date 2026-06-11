# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [0.79.0] - 2026-05-28

### Fixed
- `sweatstack.fastapi`: a single page load that fans out into many concurrent requests no longer produces a burst of duplicate `/oauth/token` refreshes when the session's access token is on the edge of expiring. Concurrent requests for the same session now serialise on a per-session lock and share the resulting refresh, so an N-way race collapses to a single token endpoint call.

### Added
- `sweatstack.fastapi.AccessTokenCache` (Protocol) and `InMemoryAccessTokenCache` (default), exposed via `configure(access_token_cache=...)`. The default is correct for single-worker deployments. Multi-worker deployments that want cross-worker de-duplication can plug in a shared-state implementation (e.g. Redis-backed). The default implementation is bounded by an LRU cap (10k entries) and uses striped locking, so memory growth is bounded regardless of session churn.
- `sweatstack.fastapi`: refresh-token rotation is now handled transparently. If a future `/oauth/token` response returns a new refresh token, the cache installs the result under both the old and new keys (so in-flight peers still hit), and the cookie / token store is rewritten with the new value. Current SweatStack servers do not rotate, so this is a forward-compatibility measure.
- `sweatstack.fastapi.RefreshLockTimeout`: a waiter that cannot acquire the per-session refresh lock within 15 seconds now raises this rather than blocking a FastAPI threadpool worker indefinitely. The `/oauth/token` call itself also has an explicit 10-second timeout.
- `sweatstack.fastapi`: debug logs (`sweatstack.fastapi.dependencies` logger) on every cache hit / seed / refresh / failure, keyed by a short SHA-256 fingerprint of the refresh token. Enable with `logging.getLogger("sweatstack.fastapi.dependencies").setLevel(logging.DEBUG)`.


## [0.78.0] - 2026-05-19

### Added
- `update_trace()` and `delete_trace()` are now exposed as module-level functions (e.g. `sweatstack.update_trace(...)`), matching the rest of the CRUD surface. They were previously only reachable via a `Client` instance.
- The package now declares an `__all__`, so `from sweatstack import *` and tooling that inspects the public surface (Sphinx, IDEs, type-checkers) see a well-defined list.

### Changed
- Minimum Python version is now declared as `>=3.10` (the code already required 3.10+ syntax; the previous `>=3.9` declaration was incorrect).
- Exception types in docstrings now reference the typed hierarchy introduced in 0.76.0 (`SweatStackAPIError`, `SweatStackNotFoundError`, `SweatStackAuthError`, `SweatStackBadRequestError`) instead of the now-incorrect `HTTPStatusError`.


## [0.77.1] - 2026-05-19

### Fixed
- Reverted unrelated OpenAPI schema drift.


## [0.77.0] - 2026-05-19

### Added
- Link a trace to a test via the new `test_id` argument on `create_trace()` and `update_trace()`. A linked trace appears in the test's traces regardless of its timestamp.
- `get_test()` accepts `trace_resolution=TraceResolution.linked` to return only traces explicitly linked to the test. Defaults to `TraceResolution.auto` (unchanged behaviour).

### Changed
- `update_trace()` replaces all fields, including `test_id`. Callers that omit `test_id` will clear any existing link — pass it back in to keep the trace linked.


## [0.76.2] - 2026-04-27

### Fixed
- `registered_at` on `UserInfoResponse` and `UserResponse` now accepts both aware and naive datetimes, working around the API returning naive timestamps for this field.


## [0.76.1] - 2026-04-27

### Fixed
- Local datetime fields (`start_local`, `end_local`, `timestamp_local`) in OpenAPI schemas corrected from `AwareDatetime` to `NaiveDatetime`.


## [0.76.0] - 2026-04-27

### Added
- Typed exception hierarchy (`sweatstack.exceptions`). All API errors now raise specific exception types: `SweatStackAuthError` (401/403), `SweatStackNotFoundError` (404), `SweatStackRateLimitError` (429), `SweatStackBadRequestError` (other 4xx), `SweatStackServerError` (5xx). Transport failures raise `SweatStackConnectionError`.
- Structured error metadata on all API exceptions: `status_code`, `url`, `method`, `request_id`, `body`.

### Changed
- **BREAKING:** All client methods now raise `SweatStackAPIError` subclasses instead of `httpx.HTTPStatusError`. Code that catches `httpx.HTTPStatusError` must switch to catching `SweatStackAPIError` (or a specific subclass).
- **BREAKING:** `TokenRefreshError` renamed to `SweatStackTokenRefreshError` and moved to `sweatstack.exceptions`. Import path changed from `from sweatstack import TokenRefreshError` to `from sweatstack import SweatStackTokenRefreshError`.
- **BREAKING:** 422 responses now raise `SweatStackBadRequestError` instead of `ValueError`.
- Transport errors (DNS, timeouts, connection refused) now raise `SweatStackConnectionError` instead of leaking raw httpx exceptions.

### Removed
- `httpx` is no longer part of the public error surface. Consumers do not need to import `httpx` to handle errors.


## [0.75.0] - 2026-04-23

### Added
- Update and delete traces: `update_trace()` and `delete_trace()` methods for full trace lifecycle management.


## [0.74.0] - 2026-04-22

### Added
- Team listing — `get_teams()` returns teams you own or belong to, `get_authorized_teams()` returns teams you've granted data access to.


## [0.73.0] - 2026-04-09

### Added
- Full support for fitness tests — create, retrieve, update, and delete physiological assessments (threshold tests, VO2max tests, etc.) and their results.
- App metadata — store and retrieve per-app JSON data on activities, traces, tests, and users.
- Dailies — get, set, and delete daily health metrics (body mass, HRV, resting HR, etc.) with optional server-side interpolation.


## [0.72.0] - 2026-03-13

### Added
- `sweatstack.enable_cache()` function to enable local caching via a simple API call instead of environment variables.
- Local caching for `get_longitudinal_mean_max()` responses (previously only `get_longitudinal_data()` was cached).

### Changed
- Cache directory now defaults to the platform cache dir (`platformdirs.user_cache_dir`) instead of the system temp directory.

### Fixed
- `AttributeError` on Python <3.11 when the API returns an error response (`add_note` is a Python 3.11+ feature).

### Removed
- `SWEATSTACK_LOCAL_CACHE` and `SWEATSTACK_CACHE_DIR` environment variables. Use `sweatstack.enable_cache()` instead.


## [0.71.0] - 2026-03-13

### Added
- `sports` (list) parameter on `get_longitudinal_mean_max()` and `get_longitudinal_awd()` for multi-sport support. The existing `sport` (single) parameter remains for backwards compatibility.
- `start` and `end` date-range parameters on `get_longitudinal_mean_max()` and `get_longitudinal_awd()`.

### Changed
- `get_activities()`, `get_traces()`, and `get_longitudinal_data()` now send the `sport` query key to the API instead of `sports`.

### Deprecated
- `sport` (singular) parameter on `get_longitudinal_mean_max()`, `get_longitudinal_awd()`, and `get_longitudinal_data()`. Use `sports` (list) instead.
- `date` and `window_days` parameters on `get_longitudinal_mean_max()` and `get_longitudinal_awd()`. Use `start`/`end` instead.


## [0.70.0] - 2026-03-13

### Added
- Added `get_team_user(*, team_id, user, search_mode)` method to find a single team-authorized user by ID or name.

### Changed
- Refactored internal user lookup into reusable `_find_user()`, `_find_user_by_name()`, and `_find_user_by_id()` helpers shared by `get_user()` and `get_team_user()`.


## [0.69.0] - 2026-03-12

### Added
- Passing team id when switching users now also works with the FastAPI and Streamlit integrations.


## [0.68.0] - 2026-03-12

### Added
- Added `create_user()` method for creating managed users (no login credentials).
- Added `get_team_users()` method to list users who have authorized a team.
- Added `authorize_team()` method to grant a team access to user data.
- Added `upload()` method for uploading activity files (CSV or FIT).
- Added `team_id` parameter to `switch_user()` and `delegated_client()` to support delegation via team membership.

### Fixed
- In proxy mode, the Streamlit login button now opens with `target="_blank"` so iOS standalone PWAs use real Safari (with existing sessions) instead of the in-app browser overlay.


## [0.67.0] - 2026-03-06

### Added
- Added `login_uri` parameter to `StreamlitAuth.behind_proxy()` (defaults to `"/login"`). In proxy mode the login button now points to the proxy's login endpoint instead of building an OAuth URL directly, enabling custom login flows such as PWA popup authentication.


## [0.66.0] - 2026-03-06

### Fixed
- Fixed `TokenRefreshError` when using `StreamlitAuth.behind_proxy()` with an expired access token. The SDK no longer checks token expiry in proxy mode, since token lifecycle is managed by the proxy.

### Added
- Added `skip_token_expiry_check` parameter to `Client` for cases where token lifecycle is managed externally.


## [0.65.0] - 2026-02-12

### Added
- The local browser auth flow now requests the `offline_access` scope so it receives a refresh token.


## [0.64.0] - 2026-02-06

### Added
- Automatic conversion of optimized API dtypes (Int16, float16, etc.) to standard dtypes (float64) for all DataFrame-returning methods.


## [0.63.0] - 2026-02-05

### Fixed
- Fixed token refresh failing when tokens were loaded from persistent storage.
- Fixed refreshed tokens not being persisted to storage.
- Fixed `switch_user()` and `get_user()` not recognizing ULID format for user IDs.

### Changed
- Simplified `authenticate()` signature: `force_login` → `force`, `persist_api_key` → `persist`.
- Made `login()` private. Use `authenticate(force=True)` instead.

### Added
- Added `TokenRefreshError` exception for explicit refresh failure handling.


## [0.62.0] - 2026-02-02

### Added
- Adds webhook support to FastAPI integration.


## [0.61.0] - 2026-01-29

### Added
- Added user switching support to FastAPI integration.


## [0.60.0] - 2026-01-28

### Added
- Added a FastAPI integration.


### Changed
- Converted sensitive variables to SecretStr to prevent accidental logging.


## [0.59.0] - 2026-01-27

### Changed
- Future-proofed response enums.


## [0.58.0] - 2026-01-24

### Fixed
- Fixes missing altitude metric.


## [0.57.0] - 2025-12-04

### Added
- Added a new "proxy mode" to the `ss.StreamlitAuth` class that allows running Streamlit apps behind a proxy. The proxy mode is enabled by calling `ss.StreamlitAuth.behind_proxy()`. The proxy should handle the OAuth callback and token exchange and pass the access token to the app via the `X-SweatStack-Token` (configurable) header. The OAuth2 flow is still initiated by the `ss.StreamlitAuth` class.


## [0.56.0] - 2025-11-21

### Fixed
- Fixed an issue where refreshing the token would not succeed with the Streamlit integration.


## [0.55.0] - 2025-10-24

### Added
- Added a new `get_activity_awd()` method to the `ss.Client` class that allows for getting the accumulated work duration (AWD) data for a specific activity.
- Added a new `get_longitudinal_awd()` method to the `ss.Client` class that allows for getting the AWD data for a specific date range.


## [0.54.0] - 2025-09-11

### Added

- Added new methods `get_authorization_url()`, `exchange_code_for_token()` and `get_pkce_params()` to the `ss.Client` class that allow for getting the authorization URL and exchanging a code for tokens. This should make it easier for clients to implement the SweatStack OAuth2 flow.

### Fixed

- Fixed an issue where the `ss.get_activities()` with `as_dataframe=True` method would raise an error if no activities were found.


## [0.53.0] - 2025-09-11

### Added

- Added a new `sport` parameter to the `ss.create_trace()` method that allows for associating a trace with a specific sport.


## [0.52.0] - 2025-09-10

### Changed
- Changed the default timeout for the HTTP client to 60 seconds.


## [0.51.0] - 2025-08-28

### Added

- Added a new `show_logout` parameter to the `ss.StreamlitAuth.authenticate()` method that allows for disabling the logout button. The logout button can be shown by calling `ss.StreamlitAuth.logout_button()`. This is for example useful when you want to show the login button on the main page, but the logout button in the sidebar.


## [0.50.0] - 2025-08-25

### Added

- Added a new `offset` parameter to the `ss.get_activities()`, `ss.get_activity_data()`, `ss.get_latest_activity_data()`, `ss.get_traces()`, and `ss.get_trace_data()` methods that allows for pagination of the results.


## [0.49.0] - 2025-08-18

### Added

- Added a new `metrics` parameter to the `ss.get_activity_data()` and `ss.get_latest_activity_data()` methods that allows for filtering the data by specific metrics.


## [0.48.0] - 2025-08-12

### Added

- Added optional local caching of longitudinal data, enabled by setting the `SWEATSTACK_CACHE_ENABLED` environment variable to `true`. The cache directory can be specified by setting the `SWEATSTACK_CACHE_DIR` environment variable. The cache can be cleared by calling `ss.clear_cache()`.


## [0.47.0] - 2025-08-07

### Added

- Added a new `ss.get_backfill_status()` method that returns the current backfill status from the activities backfill-status endpoint.
- Added a new `ss.watch_backfill_status()` method that watches the backfill status from the activities backfill-status endpoint.


## [0.46.0] - 2025-08-01

### Added

- Added a new `registered_at` field to the `UserInfoResponse` model that is returned by `ss.get_userinfo()`. This field is the timestamp of the user's registration with SweatStack.



## [0.45.0] - 2025-06-24

### Added

- Added a new `ss.whoami()` method that returns the authenticated user's summary information. This method is recommended over `ss.get_userinfo()` which only exists for OpenID compatibility and requires the `profile` scope.
- Added a new `ss.Metric.display_name()` method that returns a human-readable display name for a metric. For example, `ss.Metric.heart_rate.display_name()` returns "heart rate".

## [0.44.0] - 2025-06-18

### Added

- Added support for persistent storage of API keys and refresh tokens.
- Added a new `ss.authenticate()` method that handles authentication comprehensively, including calling `ss.login()` when needed. This method is now the recommended way to authenticate the client.


## Changed

- The `sweatlab` and `sweatshell` commands now use the new `ss.authenticate()` method.
