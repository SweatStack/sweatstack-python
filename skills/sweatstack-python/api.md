# API map (sweatstack 0.91+)

Every public method, grouped by namespace. Path IDs are positional; everything else is
keyword-only. `output=` exists only where shown. Full docstrings: `help(client.activities.list)`.

```python
from datetime import date, datetime, timezone

from sweatstack import Client

client = Client()
```

## activities: `/api/v1/activities/...`

```python
client.activities.list(start=None, end=None, sport=None, tags=None, limit=100, offset=0, output=None)
client.activities.retrieve("act_123")                    # ActivityDetails
client.activities.latest(sport=None)                     # ActivityDetails | None
client.activities.data("act_123", segmentation_on=None, metrics=None, output=None)  # time series
client.activities.mean_max("act_123", metric="power", durations=None, output=None)  # best average per duration
client.activities.awd("act_123", metric=None, output=None)  # accumulated work duration
client.activities.upload(["ride.fit"], sport=None)       # list[SourceResponse]; sport required for CSV
client.activities.backfill_status()                      # BackfillStatus
client.activities.watch_backfill_status(auto_reconnect=False)  # generator of BackfillStatus
client.activities.app_metadata.set("act_123", data={"k": "v"})  # app token only; replaces the dict
client.activities.app_metadata.delete("act_123")
```

## activities.longitudinal: many activities at once

```python
client.activities.longitudinal.data(sport="cycling", start=date(2026, 1, 1), end=None, metrics=None, segmentation_on=None, output=None)
client.activities.longitudinal.mean_max(sport="cycling", metric="power", start=None, end=None, after=None, durations=None, output=None)
client.activities.longitudinal.awd(sport="cycling", metric="power", start=None, end=None, output=None)
```

`after=` (one value or up to 5) computes the curve after that much accumulated work (kJ) per
activity: a fatigue-resistance curve, with an `after` column. `durations="all"` returns the full
grid; a list of seconds returns just those. `sweatstack.enable_cache()` caches `data` and
`mean_max` on disk; use fixed dates for stable cache hits.

## traces: `/api/v1/traces/...`

```python
client.traces.list(start=None, end=None, sport=None, tags=None, limit=100, offset=0, output=None)
client.traces.create(timestamp=datetime.now(timezone.utc), lactate=2.1, heart_rate=152, tags=["lactate"], test_id=None)
client.traces.replace("trace_123", timestamp=datetime.now(timezone.utc), lactate=2.4)  # clears every field you omit
client.traces.delete("trace_123")
client.traces.app_metadata.set("trace_123", data={"k": "v"})
client.traces.app_metadata.delete("trace_123")
```

## tests: `/api/v1/tests/...` (lab tests)

```python
client.tests.list(start=None, end=None, sport=None, tags=None, created_by=None, limit=50, offset=0, output=None)
client.tests.retrieve("test_123", trace_resolution="auto")  # "linked": only traces linked by test_id
client.tests.create(sport="cycling", start=datetime(2026, 5, 1, 9, tzinfo=timezone.utc), title=None, end=None, results=None, tags=None)
client.tests.replace("test_123", sport="cycling", start=datetime(2026, 5, 1, 9, tzinfo=timezone.utc))  # clears every field you omit
client.tests.delete("test_123")
client.tests.app_metadata.set("test_123", data={"k": "v"})
client.tests.app_metadata.delete("test_123")
```

## dailies: `/api/v1/dailies/{measure}`

```python
client.dailies.list("hrv", start=date(2026, 4, 1), end=date(2026, 5, 1), interpolate=True, output=None)
client.dailies.set("body_mass", date=date(2026, 5, 1), value=71.4)  # upsert
client.dailies.delete("body_mass", date=date(2026, 5, 1))
```

## profile: the user the client acts as

```python
client.profile.status()                 # AccountStatusResponse (beta): issue + capabilities
client.profile.sports(only_root=False)  # list[Sport]
client.profile.tags()                   # list[str]
client.profile.app_metadata.set(data={"onboarded": True})
client.profile.app_metadata.delete()
```

## users and teams

```python
client.users.list(include_managed=True, include_shared=True, name=None)  # everyone you can access
client.users.create(first_name="Bob", last_name=None)  # a managed user (no login of their own)
client.users.retrieve("usr_bob")                       # managed users only
client.users.update("usr_bob", last_name="Smit")       # changes only the fields you pass
client.users.delete("usr_bob")                         # and all their data

client.teams.list()
client.teams.users("team_123", name=None)              # users who authorised the team
client.teams.authorized()                              # teams you authorised
client.teams.authorize("team_123", scopes=None)

athlete = client.delegated_client("usr_carla", team_id=None)  # a new client acting as Carla
coach = athlete.principal_client()                            # back to the signed-in user
client.whoami()                                               # the user this client acts as
```

## portal and oauth

```python
client.portal.sessions.create("manage-integrations", return_url=None)  # app credentials, no user token

client.oauth.userinfo()                 # OpenID claims + issue (needs the profile scope)
verifier, challenge = client.oauth.generate_pkce_params()
client.oauth.authorization_url(client_id="YOUR_CLIENT_ID", redirect_uri="http://localhost:8000/callback", code_challenge=challenge)
client.oauth.exchange_code("code", client_id="YOUR_CLIENT_ID", code_verifier=verifier)
```

## Client

```python
Client(api_key=None, refresh_token=None, url=None, client_id=None, client_secret=None, output=None)
client.authenticate(force=False)
client.clear_cache()
```
