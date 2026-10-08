# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [0.91.0] - Unreleased

One namespace per API resource: `client.activities.list()` instead of `client.get_activities()`.
Every name now follows from the URL (`/api/v1/activities/...` is `client.activities`), so the
REST API reference doubles as the SDK's map. This is a breaking release with a mechanical
upgrade; see **Upgrading** below, or hand the migration prompt to your coding agent. Calling a
removed name raises an `AttributeError` that names its replacement.

### Changed

- **BREAKING: methods moved to resource namespaces**: `activities`, `traces`, `tests`, `dailies`,
  `profile`, `users`, `teams`, `portal` and `oauth`, on `Client` and at module level
  (`sweatstack.activities.list()`). The full table is under **Upgrading**.
- **BREAKING: `traces.replace()` and `tests.replace()`** are the old `update_trace()` and
  `update_test()`. The new name says what they do: every field you leave out is cleared,
  including a trace's `test_id`.
- **BREAKING: `sport=` replaces `sports=`** on every filter, as on the server (which deprecated
  `sports`). It takes one sport or a list: `sport="cycling"` or `sport=["cycling", "running"]`.
  `tags=` and `metrics=` also take a single value now.
- **BREAKING: `activities.latest()`** calls the API's `/activities/latest`: it takes only
  `sport=`, and returns `None` when there is no activity (it raised `StopIteration`).
- **BREAKING: keyword-only arguments** where they were positional: `metric=` on
  `activities.mean_max()` and `activities.awd()`, `segmentation_on=` and `metrics=` on
  `activities.data()`, `first_name=` and `last_name=` on `users.create()`, `only_root=` on
  `profile.sports()`, `scopes=` on `teams.authorize()`, and every argument of
  `oauth.authorization_url()` and `oauth.exchange_code()`.
- **BREAKING: the ID argument of `app_metadata.set()` and `app_metadata.delete()`** is
  `record_id` on activities, traces and tests (it was `activity_id`, `trace_id`, `test_id`).
  Calls that pass it positionally are unaffected.
- **BREAKING: longitudinal `date=` / `window_days=`** (deprecated since 0.70) are gone; use
  `start=` and `end=`, typed as `date` objects (`start=date(2026, 1, 1)`).
  `sport=` is a required argument of all three longitudinal methods; the API rejected a
  request without one.
- **BREAKING: `activities.upload()`** returns the processing status of each file
  (`list[SourceResponse]`) instead of a raw dict.
- **BREAKING: `users.retrieve(user_id)`** is the server's `GET /users/{id}`, which only finds
  users you manage. Find anyone else with `users.list(name=...)`, which returns every user whose
  name contains the text, ignoring case.
- **BREAKING: `switch_user()` and `switch_back()` are removed.** They changed which user a shared
  client acted as, invisibly to everything else holding it. `client.delegated_client(user)` does
  the same job and returns a new client. It takes a user ID or a `UserSummary`, not a
  name: `switch_user("Carla")` becomes a lookup with `users.list(name="Carla")` first.
- `StreamlitAuth.select_activity()` takes `sport=` instead of `sports=`.
- Clients from `delegated_client()` and `principal_client()` keep the app's `client_id` and
  `client_secret`, so `portal.sessions.create()` works on them.

- **Automatic retries**: `GET`, `PUT` and `DELETE` requests are retried up to twice after a
  connection error, a timeout, or a 408, 429 or 5xx response, with exponential backoff and the
  server's `Retry-After` (at most 30 s of waiting per call). `POST` is never retried, so a create
  can't happen twice. `Client(max_retries=0)` turns retries off, e.g. inside a web request.

### Added

- `Client(timeout=60.0, max_retries=2)`: the timeout in seconds, and how often to retry.
  Clients from `delegated_client()` and `principal_client()` keep both.
- One connection pool per client, reused across requests (each request opened a new
  connection). `client.close()` releases it; `with Client() as client:` closes on exit.
- `users.retrieve()`, `users.update()` (changes only the fields you pass) and `users.delete()`
  for managed users.
- `users.list(include_managed=, include_shared=, name=)` and `teams.users(team_id, name=)`.
- `SourceResponse` and `SourceError`, the upload status models.

### Fixed

- `activities.watch_backfill_status(auto_reconnect=True)` reconnects after a dropped
  connection; it raised instead.
- `activities.backfill_status()` and `watch_backfill_status()` return the server's updates. Its
  timestamps carry no UTC offset, which failed validation, and every update was skipped
  silently. A line the client cannot parse is now logged as a warning.
- `StreamlitAuth.select_user()` stores the selected user's own refresh token. It kept the
  signed-in user's, so after the first token refresh the app silently showed the signed-in
  user's data under the selected user's name.
- `StreamlitAuth` keeps the app's `client_id` and `client_secret` after switching users.
- Threads sharing a client refresh an expired token once; they all refreshed, which fails with
  rotating refresh tokens.
- `activities.watch_backfill_status()` no longer times out on a quiet stream: streams have no
  read timeout.
- Searching users by name ignores case; `get_user("Carla")` found nobody where `"carla"` worked.

### Removed

- **BREAKING:** the `sweatlab` and `sweatshell` commands, their example notebook, and the
  `[jupyter]` extra. In any notebook: `uv add "sweatstack[pandas]" jupyterlab`, then
  `sweatstack.authenticate()` in the first cell.
- **BREAKING:** `client.jwt`; use `client.api_key`.

<!-- --8<-- [start:upgrading-0-91] -->
### Upgrading

Removed names raise an `AttributeError` naming the replacement, so running your code points at
each change. The module-level functions moved the same way: `sweatstack.get_activities()` is
`sweatstack.activities.list()`.

| 0.90 | 0.91 |
|---|---|
| `get_activities` | `client.activities.list()` |
| `get_activity` | `client.activities.retrieve(activity_id)` |
| `get_latest_activity` | `client.activities.latest()` |
| `get_activity_data` | `client.activities.data(activity_id)` |
| `get_activity_mean_max` | `client.activities.mean_max(activity_id, metric=...)` |
| `get_activity_awd` | `client.activities.awd(activity_id)` |
| `get_latest_activity_data` | `client.activities.data(client.activities.latest().id)` |
| `get_latest_activity_mean_max` | `client.activities.mean_max(client.activities.latest().id, metric=...)` |
| `get_longitudinal_data` | `client.activities.longitudinal.data(...)` |
| `get_longitudinal_mean_max` | `client.activities.longitudinal.mean_max(...)` |
| `get_longitudinal_awd` | `client.activities.longitudinal.awd(...)` |
| `upload` | `client.activities.upload(files)` |
| `get_backfill_status` | `client.activities.backfill_status()` |
| `watch_backfill_status` | `client.activities.watch_backfill_status()` |
| `set_activity_app_metadata` | `client.activities.app_metadata.set(activity_id, data=...)` |
| `delete_activity_app_metadata` | `client.activities.app_metadata.delete(activity_id)` |
| `get_traces` | `client.traces.list()` |
| `create_trace` | `client.traces.create(...)` |
| `update_trace` | `client.traces.replace(trace_id, ...)` |
| `delete_trace` | `client.traces.delete(trace_id)` |
| `set_trace_app_metadata` | `client.traces.app_metadata.set(trace_id, data=...)` |
| `delete_trace_app_metadata` | `client.traces.app_metadata.delete(trace_id)` |
| `get_tests` | `client.tests.list()` |
| `get_test` | `client.tests.retrieve(test_id)` |
| `create_test` | `client.tests.create(...)` |
| `update_test` | `client.tests.replace(test_id, ...)` |
| `delete_test` | `client.tests.delete(test_id)` |
| `set_test_app_metadata` | `client.tests.app_metadata.set(test_id, data=...)` |
| `delete_test_app_metadata` | `client.tests.app_metadata.delete(test_id)` |
| `get_dailies` | `client.dailies.list(measure, start=..., end=...)` |
| `set_daily` | `client.dailies.set(measure, date=..., value=...)` |
| `delete_daily` | `client.dailies.delete(measure, date=...)` |
| `get_profile_status` | `client.profile.status()` |
| `get_sports` | `client.profile.sports()` |
| `get_tags` | `client.profile.tags()` |
| `set_user_app_metadata` | `client.profile.app_metadata.set(data=...)` |
| `delete_user_app_metadata` | `client.profile.app_metadata.delete()` |
| `get_users` | `client.users.list()` |
| `get_user` | `client.users.list(name=...)`: every match, so check the length |
| `create_user` | `client.users.create(first_name=...)` |
| `get_teams` | `client.teams.list()` |
| `get_team_users` | `client.teams.users(team_id)` |
| `get_team_user` | `client.teams.users(team_id, name=...)`: every match |
| `get_authorized_teams` | `client.teams.authorized()` |
| `authorize_team` | `client.teams.authorize(team_id)` |
| `create_portal_session` | `client.portal.sessions.create(destination)` |
| `get_userinfo` | `client.oauth.userinfo()` |
| `get_authorization_url` | `client.oauth.authorization_url(...)` |
| `exchange_code_for_token` | `client.oauth.exchange_code(...)` |
| `generate_pkce_params` | `client.oauth.generate_pkce_params()` |
| `switch_user` | `client.delegated_client(user)`: a new client; this one is left unchanged |
| `switch_back` | keep the original client, or `client.principal_client()` |
| `client.jwt` | `client.api_key` |

Changes that a rename alone doesn't cover. Most raise a `TypeError` naming the argument; the
ones marked **silent** don't fail loudly, so check for them.

| 0.90 | 0.91 |
|---|---|
| `sports=["cycling"]` (every filter, and `StreamlitAuth.select_activity`) | `sport="cycling"` or `sport=["cycling", "running"]` |
| `get_activity_mean_max(id, "power")`, `get_activity_awd(id, "power")` | `activities.mean_max(id, metric="power")`, `activities.awd(id, metric="power")` |
| `get_activity_data(id, "power", ["power"])` | `activities.data(id, segmentation_on="power", metrics=["power"])` |
| `create_user("Carla", "Smith")` | `users.create(first_name="Carla", last_name="Smith")` |
| `get_sports(True)`, `authorize_team(id, scopes)` | `profile.sports(only_root=True)`, `teams.authorize(id, scopes=scopes)` |
| Positional arguments to `get_authorization_url()` / `exchange_code_for_token()` | Keywords: `oauth.authorization_url(client_id=..., ...)` |
| `set_activity_app_metadata(activity_id=..., data=...)` (also traces, tests) | `activities.app_metadata.set(activity_id, data=...)`: positional, or `record_id=` |
| `get_latest_activity(start=, end=, tag=)` | `activities.latest(sport=)`; for the rest, `activities.list(start=..., end=..., tags=..., limit=1)` |
| `get_latest_activity()` raising `StopIteration` when there is none | **Silent:** `activities.latest()` returns `None`; check before using `.id` |
| `get_longitudinal_*(date=..., window_days=...)` | `start=` and `end=` |
| `get_longitudinal_*(...)` without `sport` | `sport=` is required (the API already rejected a request without one) |
| `upload(...)` returning a dict | **Silent:** `activities.upload(...)` returns `list[SourceResponse]`; read `.status` / `.error` |
| `get_user("Carla")` returning one `UserSummary` | **Silent:** `users.list(name="Carla")` returns a list, every match; `search_mode=` is gone |
| `switch_user("Carla")` (a name) | `client.delegated_client(users.list(name="Carla")[0])`: a name is not accepted |
| `client.jwt` | `client.api_key` |
| `sweatlab`, `sweatshell`, `pip install "sweatstack[jupyter]"` | `uv add "sweatstack[pandas]" jupyterlab`; `sweatstack.authenticate()` in the first cell |

New defaults that change behaviour without changing code: `GET`, `PUT` and `DELETE` requests are
retried (`Client(max_retries=0)` restores single attempts), and requests time out after 60 s
(`Client(timeout=...)`).

**Migration prompt.** Paste this into your coding agent:

```text
Upgrade this codebase to sweatstack 0.91, which moved every method to a resource namespace.
The full upgrade guide, with both tables, is the "Upgrading" section of the 0.91.0 entry in
https://github.com/SweatStack/sweatstack-python/blob/main/CHANGELOG.md
(also at https://docs.sweatstack.no/learn/python/upgrading/). Read it first.

Find every use of the sweatstack client (a Client instance, the sweatstack module, and
StreamlitAuth or FastAPI user clients) and:

1. Rename calls per the first table, e.g. get_activities() -> activities.list(),
   get_activity_data(id) -> activities.data(id),
   get_longitudinal_mean_max(...) -> activities.longitudinal.mean_max(...),
   update_trace(id, ...) -> traces.replace(id, ...), get_users() -> users.list().
2. Apply every row of the second table. In particular:
   - sports= -> sport= (one value or a list).
   - Pass by keyword: metric= (mean_max, awd), segmentation_on= and metrics= (data),
     first_name= and last_name= (users.create), only_root= (profile.sports),
     scopes= (teams.authorize), and all arguments of oauth.authorization_url() and
     oauth.exchange_code().
   - Longitudinal methods: sport= is required, and date=/window_days= become start=/end=
     (datetime.date objects).
   - activities.latest() takes only sport= and returns None when there is no activity:
     handle None.
   - activities.upload() returns list[SourceResponse], not a dict.
   - get_user(x) -> users.list(name=x), which returns a list of every match.
   - switch_user(user) -> athlete = client.delegated_client(user_id_or_summary); use that
     new client for the athlete's calls. It doesn't accept a name: look the user up first.
     switch_back() -> keep using the original client.
   - client.jwt -> client.api_key.
3. Replace get_latest_activity_data(...) with activities.data(activities.latest().id, ...),
   after checking that latest() returned an activity.
4. If the project used sweatlab, sweatshell or the [jupyter] extra, depend on
   "sweatstack[pandas]" (or [polars]) and jupyterlab instead.

Then run the code and the tests. Fix any AttributeError (its message names the replacement)
and TypeError (a renamed or keyword-only argument). Do not add compatibility shims.
```
<!-- --8<-- [end:upgrading-0-91] -->

## [0.90.0] - 2026-09-28

### Changed

- **BREAKING: mean-max curves are one row per duration**.
  `get_activity_mean_max`, `get_latest_activity_mean_max` and `get_longitudinal_mean_max` return
  `duration`, the metric (W or m/s) and `start` (UTC timestamp of the best effort), plus
  `activity_id`, `sport` and `after` on the longitudinal curve. By default 19 durations from 1 s to
  6 h; the curve can rise again at longer durations and is returned as it is.

### Added

- `durations=` on all three mean-max methods: `None` for the 19 defaults, `"all"` for the full grid,
  or a list of seconds. Keyword-only.

### Removed

- **BREAKING:** `segmentation` on `get_activity_mean_max` and `get_latest_activity_mean_max` (it never
  reduced the payload; the server ignores it). It was positional: passing `True` in that slot now
  raises `TypeError`.
- **BREAKING:** `by` on `get_longitudinal_mean_max`, and its `DeprecationWarning`. Every curve is
  duration-oriented.

## [0.89.0] - 2026-09-28

Frames on your terms. Every method that returns a collection takes `output=`:
`"pandas"`, `"polars"`, `"arrow"` or `"bytes"` for time-series endpoints, and `"models"`
(default), `"pandas"`, `"polars"` or `"arrow"` for list endpoints. Set it per call, per client
(`Client(output="polars")`) or once for everything (`sweatstack.set_output("polars")`). When you
don't say, time series come back in the frame library you installed: Polars, then pandas,
then Arrow.
Four breaking changes come with it; the upgrade is mechanical, see **Upgrading** below.

### Added

- `get_profile_status()` (beta): why this user has little or no data, and what the
  account can supply. Returns `issue` (`None`, or one `{code, status, message, action_url}`)
  and `capabilities` (`activities`, `activity_history`, `dailies`, `workouts`, each `ready`,
  `syncing`, `action_required` or `unavailable`). Accepts `data:read` or `profile`.
- `get_userinfo()` now carries the same `issue` (beta). The whole integration is
  `if user.issue: banner(user.issue.message, user.issue.action_url)`; `action_url` is `None` on
  delegated tokens and on issues the user cannot act on.
- `create_portal_session(destination, return_url=None)` (beta): mints a SweatStack Portal link
  branded for the client's app, using the app's own `client_id` / `client_secret` from the
  constructor and no user token. Works from `sweatstack.fastapi` dependencies and
  `StreamlitAuth` as is.
- New models and enums: `AccountStatusResponse`, `StatusIssueResponse`, `Capability`,
  `CapabilityStatus`, `StatusIssueCode`, `PortalDestination`, `PortalSessionResponse`.
  `StatusIssueCode` and `Capability` are open sets: values a newer server adds parse as
  pseudo-members instead of failing validation.
- `output=` on `get_activity_data`, `get_activity_mean_max`, `get_activity_awd`,
  `get_latest_activity_data`, `get_latest_activity_mean_max`, `get_longitudinal_data`,
  `get_longitudinal_mean_max`, `get_longitudinal_awd`, `get_activities`, `get_traces`,
  `get_tests` and `get_dailies`.
- `Client(output=...)` and `sweatstack.set_output(...)` to choose once. A per-call value
  always wins. Delegated clients inherit the setting.
- Polars frames keep the compact wire dtypes (Int16, Float32, Categorical, Duration) and
  give nested fields as typed structs (`df.unnest("summary")`), as do Arrow tables. On
  time-series endpoints Arrow tables are the response as-is. `"bytes"` is the raw parquet, ready for `duckdb.sql("... from 'file.parquet'")`.
- `sweatstack[polars]` and `sweatstack[arrow]` extras. `[arrow]` is pyarrow alone: what
  `output="arrow"` needs, and what DuckDB needs to query any in-memory frame. See the
  README's "Using DuckDB" for the three routes.

### Fixed

- `whoami()` raised `AttributeError` on every call since the helper it relied on was removed.
  It resolves the token's user through `get_user()` again, for principal and delegated clients
  alike, and still needs no `profile` scope.

### Changed

- **Breaking:** pandas is no longer installed by default. Install `sweatstack[pandas]`
  (pandas + pyarrow), `sweatstack[polars]` or `sweatstack[arrow]`. The `streamlit` and
  `jupyter` extras include pandas. FastAPI services and webhook consumers can stay on the base package. Asking for an
  output whose library is missing raises an `ImportError` naming the extra to install.
- **Breaking:** the default frame library is the one you installed, in the order Polars,
  pandas, Arrow. An environment with pandas and Polars now gets Polars frames from the time-series
  methods unless you set `output` (per call, `Client(output="pandas")`, or
  `sweatstack.set_output("pandas")` once).
- **Breaking:** `as_dataframe=True` is removed. Use `output="pandas"`.
- **Breaking:** no frame carries an index any more, on any backend. `timestamp` (time
  series), the metric value (mean-max and AWD curves) and `date` (dailies) are now regular
  columns, in first position. The set of columns is unchanged. Code that relied on the
  index needs `.set_index("timestamp")` (or `"power"`, `"date"`, ...) once, or should use
  the column directly. This also applies to the fatigue mean-max (`after=`) frame, which was
  previously re-indexed by the client.
- pandas frames keep the float64 / nanosecond dtype policy. Polars and Arrow do not upcast.

### Upgrading

1. Change the install line: `uv add "sweatstack[pandas]"` (or `[polars]`, or `[arrow]` for
   DuckDB). Streamlit and
   Jupyter users: `sweatstack[streamlit]` / `sweatstack[jupyter]` already include pandas.
2. To keep pandas frames in an environment that also has Polars, add
   `sweatstack.set_output("pandas")` once (or `Client(output="pandas")`).
3. Replace `as_dataframe=True` with `output="pandas"`.
4. Search for `.index`, `.loc[<timestamp>]`, `.resample(`, `.plot()` on frames from the
   time-series, mean-max, AWD and dailies methods. Where the index mattered, add
   `.set_index("timestamp")` (or the metric name, or `"date"`) right after the call.

## [0.88.0] - 2026-08-06

### Changed

- **Breaking:** `create_trace`, `update_trace`, `create_test`, and `update_test` now require timezone-aware datetimes for `timestamp`, `start`, and `end`. A naive datetime raises `ValueError` before the request is sent. Attach a zone, e.g. `datetime(..., tzinfo=ZoneInfo("Europe/Amsterdam"))` or `datetime.now(timezone.utc)`; the offset is stored alongside the instant.
- `start`, `end`, and `timestamp` on responses are absolute UTC instants (ISO 8601 with a `Z` suffix), no longer a fixed per-record local offset. For wall-clock display use the companion `start_local` / `end_local` / `timestamp_local` fields, which are always present. The Streamlit activity selector now labels activities by their local date.
- Requires a SweatStack server with offset-based timezone handling. Against an older server the aware-datetime writes still work, but responses keep the previous fixed-offset `start`/`end`/`timestamp`.

### Removed

- Token refresh no longer sends a `tz` field. The server derives all timezone information from the offsets stored with each record, so the client has nothing to pass.

## [0.87.0] - 2026-06-30

### Changed

- **Breaking:** the codec previously named NLEC is now AISC (Adaptive Intensity Segmentation Codec), and its parameters are renamed: `nlec_on` is now `segmentation_on` (on `get_activity_data`, `get_latest_activity_data`, `get_longitudinal_data`) and `nlec` is now `segmentation` (on `get_activity_mean_max`, `get_latest_activity_mean_max`). No backwards-compatible aliases.


## [0.86.0] - 2026-06-18

### Changed

- **Breaking:** renamed the adaptive-sampling parameters to NLEC (near-lossless effort codec). `adaptive_sampling_on` is now `nlec_on` (on `get_activity_data`, `get_latest_activity_data`, `get_longitudinal_data`) and `adaptive_sampling` is now `nlec` (on `get_activity_mean_max`, `get_latest_activity_mean_max`). No backwards-compatible aliases; requires the SweatStack server 0.107.0 or later.


## [0.85.0] - 2026-06-17

### Changed

- `get_longitudinal_mean_max(by=...)` now defaults to `None`: the `by` parameter is omitted from the request so the server picks the orientation. For `after` (fatigue) with `metric="power"` the server now defaults to `by="duration"`; every other case stays `by="intensity"`. The returned frame is indexed on whichever orientation the server used. Passing `by` explicitly still works.

### Deprecated

- `by="intensity"` for the `after` (fatigue) case is deprecated and now raises a `DeprecationWarning`; `by="duration"` is the default and only supported orientation going forward. Pass `by="duration"` or leave `by` unset. (`by="intensity"` remains the only orientation for `metric="speed"`.)


## [0.84.0] - 2026-06-17

### Added

- `get_longitudinal_mean_max(by=...)`: pass `by="duration"` (with `after`, for `power`) to get the fatigue curve indexed by duration instead of by intensity. Default `by="intensity"` is unchanged.

### Changed

- Require `pyarrow>=20`: pyarrow 18/19 fail to read the server's parquet ("Repetition level histogram size mismatch") for longitudinal and adaptive-sampling responses; pyarrow 20+ reads them correctly.


## [0.83.0] - 2026-06-16

### Added
- Trace responses now include `test` and `test_match` (server-side test matching).

### Fixed
- Fixes Dailies response schema.


## [0.82.0] - 2026-06-16

### Added

- `get_longitudinal_mean_max(after=...)`: fatigue-state mean-max. Pass one or more thresholds (kJ of work for `power`; metres of distance for `speed`, experimental) to get, per state, the mean-max over the portion of each ride after that threshold. The returned DataFrame stays metric-indexed with an added `after` column. Max 5 states; the date range is capped at 1 year when `after` is used.

## [0.81.0] - 2026-06-16

The SweatStack API has fully adopted [OpenSportTaxonomy](https://github.com/SweatStack/open-sport-taxonomy)
(OST), and so has this client. `sweatstack.Sport` is now the OST `Sport` type instead of a bespoke enum.
This is a **breaking change** for code that uses `Sport`.

### Changed (breaking)
- `sweatstack.Sport` is now `open_sport_taxonomy.Sport` — a rich type (`.code`, `.label`, `.modifiers`,
  `.parent`, `.is_subsport_of()`, `.resolve()`, `Sport.parse()`, `Sport.all()`) rather than a string
  enum. There are no `Sport.cycling_road`-style members; construct a known sport with
  `Sport("cycling.road")` or parse external input with `Sport.parse(value)`. The bespoke helpers
  (`root_sport()`, `parent_sport()`, `is_sub_sport_of()`, `is_root_sport()`, `display_name()`) are
  removed in favour of OST's native API.
- Sport values are now OST values, e.g. `cycling.trainer` → `cycling+stationary`, `cycling.tt` →
  `cycling.time_trial`, `cross_country_skiing` → `xc_skiing`, `unknown` → `generic`. Response data,
  longitudinal DataFrames and `get_sports()` all return OST values; requests send OST values.

### Added
- `sweatstack.Modifier` (re-exported from OpenSportTaxonomy) for inspecting sport modifiers. (For typed
  sport annotations, `StandardSport` is available from `open_sport_taxonomy` directly.)
- `open-sport-taxonomy[pydantic]` is now a runtime dependency. Response models consume `sport` via OST's
  permissive `SportField`, so sports newer than the bundled taxonomy are preserved rather than rejected.

### Migration
Hand the following prompt to a coding agent, or apply it by hand:

```text
Migrate this codebase to sweatstack 0.81.0, which replaces its custom `Sport` enum with the
OpenSportTaxonomy type (`open_sport_taxonomy.Sport`). `from sweatstack import Sport` is now that type.

1. Construction (there are no enum members like `Sport.cycling_road`):
   - Known sport in app code -> `Sport("cycling.road")` (raises on an unknown code/modifier).
   - From an API/string value -> `Sport.parse(value)` (permissive; never raises; preserves unknown).
   - For typed annotations/autocomplete of the standard catalogue ->
     `from open_sport_taxonomy import StandardSport` (a Literal).

2. These sport VALUES changed; update hardcoded strings or members:
   cycling.trainer->cycling+stationary, running.treadmill->running+stationary,
   rowing.ergometer->rowing+stationary, cycling.tt->cycling.time_trial,
   cycling.mountainbike->cycling.mountain, cross_country_skiing[.classic|.skate]->xc_skiing[...],
   unknown->generic. ("stationary" etc. are now modifiers, appended with `+`; see sport.modifiers.)

3. Methods / attributes:
   Sport.cycling_road          -> Sport("cycling.road")
   sport.value                 -> str(sport)  (canonical, incl. modifiers) or sport.code
   sport.display_name()        -> sport.label
   sport.parent_sport()        -> sport.parent
   sport.is_sub_sport_of(x)    -> sport.is_subsport_of(x)   (x is a single Sport; for a list use
                                  any(sport.is_subsport_of(s) for s in xs))
   sport.root_sport()          -> Sport(sport.code.split(".")[0])
   sport.is_root_sport()       -> ("." not in sport.code and not sport.modifiers)
   for s in Sport: ...         -> for s in Sport.all(): ...

4. Equality works: `activity.sport == Sport("cycling+stationary")`. Compare against the NEW value.

After editing, run the test suite and fix any remaining references. Do not add a compatibility shim;
migrate call sites to the OST API directly.
```


## [0.80.0] - 2026-06-12

### Changed
- Makes the Sport enum forward compatible with OpenSportTaxonomy sports.


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
