# Client API

## Contents

- [Authentication](#authentication)
- [Activities](#activities)
- [Time-Series Data](#time-series-data)
- [Mean-Max and AWD](#mean-max-and-awd)
- [Longitudinal Data](#longitudinal-data)
- [Traces](#traces)
- [Tests](#tests)
- [Dailies](#dailies-daily-health-metrics)
- [App Metadata](#app-metadata)
- [Profile](#profile)
- [Users and Teams](#users-and-teams)
- [User Delegation](#user-delegation)
- [File Uploads](#file-uploads)
- [Singleton vs Instance](#singleton-vs-instance)
- [Gotchas](#gotchas)

---

## Authentication

Three modes — pick one:

**Interactive (scripts, notebooks):**
```python
import sweatstack
sweatstack.authenticate()  # Opens browser, persists tokens to disk
```
Tokens stored at `~/.local/share/SweatStack/SweatStack/tokens.json`. Subsequent runs reuse stored tokens automatically. Pass `force=True` to re-authenticate.

**Environment variables (CI, containers):**
```
SWEATSTACK_API_KEY=<access_token>
SWEATSTACK_REFRESH_TOKEN=<refresh_token>
```
No `authenticate()` call needed — the client picks up env vars automatically.

**Direct token (advanced):**
```python
client = Client(api_key="...", refresh_token="...")
```

Token refresh is automatic in all modes. The library handles expiry checks and refreshes transparently.

## Activities

```python
# List activities (returns list[ActivitySummary])
activities = client.get_activities(
    start=date(2025, 1, 1),      # optional
    end=date(2025, 12, 31),      # optional
    sports=[Sport.cycling_road],  # optional, list of Sport enum or strings
    tags=["race"],                # optional
    limit=100,                    # default 100
    offset=0,                     # for pagination
)

# As DataFrame instead
df = client.get_activities(as_dataframe=True)

# Single activity by ID (returns ActivityDetails)
activity = client.get_activity("activity_id")

# Most recent activity (returns ActivityDetails)
latest = client.get_latest_activity()
latest = client.get_latest_activity(sport=Sport.running)
```

## Time-Series Data

Returns pandas DataFrame with 1-second sampled data.

```python
# All available metrics
df = client.get_activity_data("activity_id")

# Specific metrics only
df = client.get_activity_data("activity_id", metrics=[Metric.power, Metric.heart_rate])

# Latest activity shortcut
df = client.get_latest_activity_data(sport=Sport.cycling)
```

Columns match requested metrics. The `duration` column is included by default.

## Mean-Max and AWD

```python
# Mean-max curve (max average power/speed at each duration)
df = client.get_activity_mean_max("activity_id", metric="power")

# Accumulated Work Duration (time spent at each intensity level)
df = client.get_activity_awd("activity_id", metric="power")

# Latest activity shortcuts
df = client.get_latest_activity_mean_max(metric="power", sport=Sport.cycling)
```

## Longitudinal Data

Aggregated time-series across multiple activities. One request instead of looping.

```python
df = client.get_longitudinal_data(
    sports=[Sport.cycling_road],        # list of Sport enum or strings
    start=date(2025, 1, 1),             # required
    end=date(2025, 12, 31),             # optional (defaults to today)
    metrics=[Metric.power, Metric.heart_rate],  # optional
)

# Multiple sports
df = client.get_longitudinal_data(
    sports=[Sport.cycling_road, Sport.cycling_gravel],
    start=date(2025, 1, 1),
)

# Longitudinal mean-max (best efforts across time range)
df = client.get_longitudinal_mean_max(
    sports=[Sport.cycling_road],
    metric="power",
    start=date(2025, 1, 1),
)

# Longitudinal AWD
df = client.get_longitudinal_awd(
    sports=[Sport.cycling_road],
    metric="power",
    start=date(2025, 1, 1),
)
```

The DataFrame has a timezone-aware datetime index and includes an `activity_id` column — group by it for per-activity aggregation.

**Local caching** for reproducible analysis (avoids re-fetching on reruns). Caches `get_longitudinal_data()` and `get_longitudinal_mean_max()`:
```python
import sweatstack
sweatstack.enable_cache()                    # platform cache dir
sweatstack.enable_cache(path="./my_cache")   # custom dir
client.clear_cache()                         # remove all cached data for current user
# Use fixed end dates (not "today") to get stable cache hits
df = client.get_longitudinal_data(sports=[Sport.cycling], start=date(2025, 1, 1), end=date(2025, 3, 31))
df = client.get_longitudinal_mean_max(sports=[Sport.cycling], metric="power", start=date(2025, 1, 1))
```

## Traces

Custom data points with measurements (e.g., lactate tests, RPE entries).

```python
# List traces
traces = client.get_traces(start=date(2025, 1, 1), as_dataframe=True)

# Create a trace
trace = client.create_trace(
    timestamp=datetime(2025, 6, 1, 10, 0),
    lactate=2.5,
    rpe=7,
    heart_rate=155,
    sport=Sport.cycling,
    tags=["test"],
    notes="Lactate threshold test",
)

# Update a trace (full replace — fields not provided are set to null)
client.update_trace(
    trace.id,
    timestamp=trace.timestamp,
    lactate=2.8,               # corrected value
    rpe=trace.rpe,             # must re-pass to keep existing values
    heart_rate=trace.heart_rate,
    sport=trace.sport,
    tags=trace.tags,
    notes=trace.notes,
)

# Delete a trace
client.delete_trace("trace_id")
```

## Tests

Fitness assessments/evaluations with structured physiological results.

```python
# List tests (returns list[TestSummary])
tests = client.get_tests(
    start=date(2025, 1, 1),           # optional
    end=date(2025, 12, 31),           # optional
    sports=[Sport.cycling],            # optional
    tags=["lab"],                      # optional
    created_by="app_id",              # optional, filter by creator app
    limit=50,                          # default 50
)

# As DataFrame (results column gets normalized into flat columns like results.vo2max)
df = client.get_tests(as_dataframe=True)

# Single test by ID (returns TestDetails with resolved traces + overlapping activities)
test = client.get_test("test_id")

# Create a test
from sweatstack import TestResults, Marker
test = client.create_test(
    sport=Sport.cycling,
    start=datetime(2025, 6, 1, 9, 0),
    title="Lab test Q2",
    results=TestResults(
        first_threshold=Marker(power=200, heart_rate=140),
        second_threshold=Marker(power=280, heart_rate=170),
        vo2max=4500.0,
        critical_power=260,
    ),
    tags=["lab"],
)

# Update a test (full replace — fields not provided are set to null)
client.update_test(
    test.id,
    sport=Sport.cycling,
    start=test.start,
    title="Lab test Q2 (revised)",
    results=test.results,  # must re-pass to keep existing results
)

# Delete a test
client.delete_test("test_id")
```

## Dailies (Daily Health Metrics)

```python
from sweatstack import DailyMeasure

# Get daily values over a date range (returns list[DailyResponse])
dailies = client.get_dailies(
    DailyMeasure.body_mass,
    start=date(2026, 1, 1),
    end=date(2026, 3, 31),
    interpolate=True,            # default; server fills gaps
)

# As DataFrame (date as index)
df = client.get_dailies(DailyMeasure.body_mass, start=date(2026, 1, 1), end=date(2026, 3, 31), as_dataframe=True)

# Set a daily value (upsert — creates or updates)
daily = client.set_daily(DailyMeasure.body_mass, date=date(2026, 4, 1), value=75.2)

# Delete a daily value
client.delete_daily(DailyMeasure.body_mass, date=date(2026, 4, 1))
```

Available measures: `body_mass`, `body_fat_pct`, `resting_hr`, `hrv`, `sleep_duration`, `sleep_altitude`, `menstrual_cycle_day`. The `measure` parameter is positional (part of the URL path). With `interpolate=False`, missing dates return `value=None, source="missing"`.

## App Metadata

Store arbitrary JSON data on entities, scoped per app. Requires an app token (token with `aud` claim).

```python
# Set metadata on an activity (full replace, max 1KB)
client.set_activity_app_metadata("activity_id", data={"score": 8.5, "notes": "good"})

# Delete it
client.delete_activity_app_metadata("activity_id")

# Same pattern for traces, tests, and the current user
client.set_trace_app_metadata("trace_id", data={"source": "lab"})
client.set_test_app_metadata("test_id", data={"protocol": "ramp"})
client.set_user_app_metadata(data={"preferences": {"unit": "metric"}})  # max 4KB

# Delete
client.delete_trace_app_metadata("trace_id")
client.delete_test_app_metadata("test_id")
client.delete_user_app_metadata()
```

Metadata appears as `app_metadata` on entity responses when accessed via app token.

## Profile

```python
sports = client.get_sports()              # list[Sport] — sports with data
root_sports = client.get_sports(only_root=True)  # top-level only
tags = client.get_tags()                  # list[str]
user = client.get_userinfo()              # UserInfoResponse (sub, name, email)
who = client.whoami()                     # UserSummary (from JWT, no API call)
```

## Users and Teams

```python
# List accessible users
users = client.get_users()

# Find a specific user (by ID or name)
user = client.get_user("john")                    # auto-detects ID vs name
user = client.get_user("abc123", search_mode="id")

# Create a managed user (no login credentials)
user = client.create_user(first_name="John", last_name="Doe")

# List teams you're a member/owner of
teams = client.get_teams()                # list[TeamResponse] with .role

# List teams you've authorized to access your data
authorized = client.get_authorized_teams()  # list[AuthorizedTeamResponse] with .scopes

# Team user management
team_users = client.get_team_users(team_id="team_abc")
athlete = client.get_team_user(team_id="team_abc", user="john")  # by name or ID
client.authorize_team(team_id="team_abc", scopes=[Scope.data_read])
```

## User Delegation

Operate on behalf of another user (requires appropriate permissions).

**Prefer `delegated_client()`** — creates a separate client, keeping the scope explicit:

```python
other = client.delegated_client("john")
other_activities = other.get_activities()
# original client is unchanged

# Via team membership
athlete = client.get_team_user(team_id="team_abc", user="john")
other = client.delegated_client(athlete, team_id="team_abc")
```

`switch_user()` modifies the client in-place — useful in interactive/notebook contexts but avoid in scripts:

```python
client.switch_user("john")                # mutates client
client.switch_user("john", team_id="team_abc")
client.switch_back()                      # revert to principal
```

## File Uploads

```python
# Upload FIT files (sport detected automatically)
client.upload("activity.fit")
client.upload(["file1.fit", "file2.fit"])

# Upload CSV (sport required)
client.upload("data.csv", sport=Sport.cycling_road)
```

CSV files must contain a `timestamp` column with ISO 8601 datetimes.

## Singleton vs Instance

**Singleton** (module-level functions) — uses a shared default `Client()`:
```python
import sweatstack
sweatstack.authenticate()
sweatstack.get_activities()
```

**Instance** — create your own client when you need multiple clients, custom URLs, or explicit control:
```python
from sweatstack import Client
client = Client(api_key="...", url="https://custom.sweatstack.no")
```

Use singleton for scripts and notebooks. Use instances for servers, multi-user apps, or tests.

## One-Off Scripts with `uv run`

For standalone analysis scripts, use PEP 723 inline metadata so `uv run script.py` handles dependencies automatically:

```python
# /// script
# requires-python = ">=3.12"
# dependencies = ["sweatstack", "matplotlib"]
# ///
import sweatstack
sweatstack.authenticate()
df = sweatstack.get_latest_activity_data()
```

## Gotchas

- **Sport enum uses underscores:** `Sport.cycling_road`, not `Sport("road")` or `Sport.cycling.road`. String values use dots: `"cycling.road"`.
- **`start` is required for longitudinal endpoints.** Unlike `get_activities()` where all filters are optional.
- **`sport` (singular) vs `sports` (list):** `get_latest_activity(sport=...)` and `create_trace(sport=...)` take a single sport. All other methods that filter by sport use `sports=[...]` (list). The singular `sport` parameter on longitudinal methods is deprecated.
- **DataFrames have standard dtypes.** The library converts API-optimized types (Int16, float16) to float64/datetime64[ns] automatically.
- **`as_dataframe=True`** is available on `get_activities()`, `get_traces()`, `get_tests()`, and `get_dailies()`. Time-series methods (`get_activity_data`, `get_longitudinal_data`, etc.) always return DataFrames.
- **`update_test()` and `update_trace()` are full replaces.** Omitted optional fields are set to null. Always re-pass all fields you want to keep.
- **`summary` fields are optional.** Always null-check: `activity.summary.power.mean if activity.summary and activity.summary.power else None`.
- **`metrics` on ActivitySummary** lists available data streams, not the data itself. Use to check availability before calling `get_activity_data()`.
