# Data Models

All models are importable from `sweatstack.schemas`.

## Sport Enum

Hierarchical values — root sports have sub-sports:

| Root | Sub-sports |
|------|-----------|
| `cycling` | `road`, `tt`, `cyclocross`, `gravel`, `mountainbike`, `track`, `trainer` |
| `running` | `road`, `track`, `trail`, `treadmill` |
| `swimming` | `pool`, `pool.25m`, `pool.50m`, `open_water`, `flume` |
| `cross_country_skiing` | `classic`, `skating` |
| `rowing` | _(none)_ |
| `walking` | `hiking` |
| `generic` | _(none)_ |

**Usage:** `Sport.cycling_road` (underscore, not dot). String values use dots: `"cycling.road"`.

**Utility methods:**
- `sport.display_name()` → `"cycling (road)"`
- `sport.root_sport()` → `Sport.cycling`
- `sport.is_root_sport()` → `True`/`False`
- `sport.is_sub_sport_of(Sport.cycling)` → `True`/`False`

**Unknown sports:** The enum handles unknown values from newer API versions gracefully — no crashes on new sports.

## Metric Enum

Available data stream names: `duration`, `power`, `speed`, `heart_rate`, `cadence`, `altitude`, `elevation`, `temperature`, `core_temperature`, `smo2`, `distance`, `latitude`, `longitude`, `lactate`, `rpe`, `respiration_rate`, `notes`

`metric.display_name()` → human-readable form.

## Scope Enum

| Enum member | Value |
|---|---|
| `Scope.data_read` | `data:read` |
| `Scope.data_write` | `data:write` |
| `Scope.profile` | `profile` |
| `Scope.openid` | `openid` |
| `Scope.admin` | `admin` |

## Response Models

**ActivitySummary** — returned by `get_activities()`:
`id`, `sport: Sport`, `start: datetime`, `end: datetime`, `start_local: datetime`, `end_local: datetime`, `duration: timedelta`, `distance: float?`, `name: str?`, `description: str?`, `metrics: list[Metric]`, `summary: ActivitySummarySummary?`, `tags: list[str]?`

The `summary` object contains per-metric aggregates: `summary.power.mean`, `summary.power.max`, `summary.heart_rate.mean`, `summary.distance.sum`, `summary.altitude.gain`, etc. All fields optional.

The `metrics` list indicates which data streams are available (e.g., `[Metric.power, Metric.heart_rate]`). Use to check availability without fetching data.

**ActivityDetails** — returned by `get_activity()`, `get_latest_activity()`:
Extends ActivitySummary with `traces: list[TraceDetails]?`, `devices: list[str]?`, `laps: list[Lap]?`

**TraceDetails** — returned by `get_traces()`, `create_trace()`:
`id`, `timestamp: datetime`, `timestamp_local: datetime`, `lactate: float?`, `rpe: int?`, `notes: str?`, `power: int?`, `speed: float?`, `heart_rate: int?`, `tags: list[str]?`, `sport: Sport?`, `activity: ActivitySummary?`

**UserSummary:** `id`, `first_name: str?`, `last_name: str?`, `display_name: str`, `admin: bool`

**UserInfoResponse:** `sub: str`, `name: str`, `given_name: str?`, `family_name: str?`, `email: str?`, `registered_at: datetime`

**UserResponse:** `id`, `first_name: str?`, `last_name: str?`, `display_name: str`, `admin: bool`, `is_managed: bool`, `registered_at: datetime`

**TokenResponse:** `access_token: str`, `token_type: str`, `expires_in: int`, `refresh_token: str`, `scope: str?`, `id_token: str?`

**BackfillStatus:** `backfill_loaded_until: datetime?`, `backfill_errors: list?`
