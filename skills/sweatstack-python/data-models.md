# Data models

Import everything from `sweatstack`: `from sweatstack import Sport, Metric, ActivitySummary`.

## Sport (OpenSportTaxonomy)

`Sport` is OpenSportTaxonomy's type: dotted codes (`cycling.road`) plus `+modifiers`
(`cycling+stationary` for an indoor trainer).

```python
from sweatstack import Sport

Sport("cycling.road")           # a known sport; raises on an unknown code
Sport.parse("kitesurfing")      # tolerant: use for external input
sport.label                     # "road cycling"
sport.parent                    # Sport("cycling")
sport.is_subsport_of(Sport("cycling"))
sport.modifiers                 # e.g. {Modifier.STATIONARY}
str(sport)                      # "cycling.road", the wire value
Sport.all()                     # every standard sport
```

Filters take strings or `Sport`: `client.activities.list(sport="cycling")` matches every
cycling sub-sport. Sports in responses are always parsed, so a sport newer than the installed
taxonomy is preserved (`is_standard` is `False`) instead of failing.

## Metric, Scope, DailyMeasure

- `Metric`: data streams such as `power`, `speed`, `heart_rate`, `cadence`, `altitude`,
  `distance`, `temperature`, `core_temperature`, `smo2`, `lactate`, `rpe`. `metric.display_name()`
  gives a readable form. Open set: unknown values from a newer server still parse.
- `Scope`: `Scope.data_read` (`"data:read"`), `data_write`, `profile`, `openid`, `offline_access`, `admin`. Open set.
- `DailyMeasure`: `body_mass`, `body_fat_pct`, `resting_hr`, `hrv`, `sleep_duration`,
  `sleep_altitude`, `menstrual_cycle_day`. Open set.

## Response models (Pydantic)

- **ActivitySummary** (`activities.list()`): `id`, `sport`, `start`, `end` (UTC), `start_local`,
  `end_local` (naive local wall-clock), `duration`, `metrics` (the streams the activity has),
  `summary` (per-metric aggregates, e.g. `summary.power.mean`; every field optional), `laps`,
  `traces`, `tags`, `source_id`, `app_metadata`.
- **ActivityDetails** (`activities.retrieve()`, `latest()`): the summary plus `distance`,
  `devices`.
- **TraceDetails**: `id`, `timestamp`, `timestamp_local`, `lactate`, `rpe`, `notes`, `power`,
  `speed`, `heart_rate`, `vo2`, `sport`, `tags`, `test_id`, `activity`, `lap`, `test`,
  `test_match`, `app_metadata`.
- **TestSummary** / **TestDetails**: `id`, `title`, `sport`, `start`, `end`, `start_local`,
  `end_local`, `results` (`TestResults`: thresholds `lt1`, `lt2`, `vt1`, `vt2`, `mlss`, `fatmax`
  as `Marker`s, plus `vo2max`, `critical_power`, `w_prime`, ...), `tags`, `created_by`;
  `TestDetails` adds the resolved `traces` and overlapping `activities`.
- **DailyResponse**: `date`, `value`, `status`, `source`.
- **UserSummary** (`users.list()`): `id`, `first_name`, `last_name`, `display_name`, `scopes`,
  `is_managed`.
- **UserResponse** (`users.create()`, `retrieve()`, `update()`): `id`, `first_name`,
  `last_name`, `display_name`, `admin`, `is_managed`, `registered_at`.
- **SourceResponse** (`activities.upload()`): `id`, `type`, `origin`, `filename`, `status`
  (`processing`, `processed`, `failed`), `error`, `activity_ids`, `created_at`.
- **UserInfoResponse** (`oauth.userinfo()`): `sub`, `name`, `given_name`, `family_name`,
  `email`, `registered_at`, `issue`.
- **AccountStatusResponse** (`profile.status()`, beta): `issue` (`StatusIssueResponse | None`:
  `code` (open set), `status` (`CapabilityStatus`: `ready`, `syncing`, `action_required`,
  `unavailable`), `message` (display only), `action_url`) and `capabilities`
  (`dict[Capability, CapabilityStatus]`). Branch on `status`, show `message`, show a button
  only when `action_url` is set.
- **PortalSessionResponse**: `url` (opaque; never build one by hand).
