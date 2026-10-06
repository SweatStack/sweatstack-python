---
name: sweatstack-python
description: >
  Builds Python applications using the SweatStack SDK (uv add "sweatstack[polars]" or
  "sweatstack[pandas]", version 0.91 or later). Covers authentication, activities and their time
  series, longitudinal analysis (mean-max, AWD), traces, lab tests, dailies, pandas/Polars/Arrow
  output, user delegation for coaches, teams, uploads, Streamlit dashboards and FastAPI backends.
  Use when writing Python scripts, notebooks, Streamlit apps or FastAPI services that access
  SweatStack sports data, even if the user just says "Python" and "SweatStack".
---

# SweatStack Python SDK

Install with a frame library: `uv add "sweatstack[polars]>=0.91"` (or `[pandas]`). Plain
`sweatstack` has no frame library: enough for services that only need the models. Other extras:
`[arrow]` (DuckDB), `[streamlit]`, `[fastapi]`.

**This skill describes 0.91+.** Code from older examples or training data uses flat names
(`get_activities()`, `get_activity_data()`, `switch_user()`); they no longer exist. Calling one
raises an `AttributeError` that names the replacement.

## Quickstart

```python
from sweatstack import Client

client = Client()
client.authenticate()  # browser sign-in once; saved for later runs

latest = client.activities.latest()  # ActivityDetails, or None without activities
if latest is not None:
    df = client.activities.data(latest.id, metrics=["power", "heart_rate"], output="polars")
```

## Names follow the URL

Every endpoint group is an attribute named after its URL segment, and the method name follows
from the HTTP operation. Derive a name from the REST API instead of guessing:

| URL | Python |
|---|---|
| `GET /api/v1/activities/` | `client.activities.list(...)` |
| `GET /api/v1/activities/{id}` | `client.activities.retrieve(id)` |
| `GET /api/v1/activities/{id}/data` | `client.activities.data(id)` |
| `GET /api/v1/activities/longitudinal-data` | `client.activities.longitudinal.data(...)` |
| `PUT /api/v1/traces/{id}` (overwrites every field) | `client.traces.replace(id, ...)` |
| `PUT /api/v1/users/{id}` (changes the fields you pass) | `client.users.update(id, ...)` |
| `POST /api/v1/dailies/{measure}` (upsert) | `client.dailies.set(measure, ...)` |
| `POST /api/v1/portal/sessions` | `client.portal.sessions.create(...)` |

Namespaces: `activities` (with `longitudinal`, `app_metadata`), `traces`, `tests`, `dailies`,
`profile`, `users`, `teams`, `portal`, `oauth`. Every method and its signature: [api.md](api.md).

## Rules agents get wrong

- **One `Client` per user in apps.** The module-level interface (`sweatstack.activities.list()`)
  is one shared client per process: fine in scripts and notebooks, a data leak between users in
  Streamlit or FastAPI. Use `auth.client` (Streamlit) or `user.client` (FastAPI).
- **Act as another user with a new client:** `athlete = client.delegated_client(user)`. The
  original client is unchanged.
- **IDs, not objects:** `client.activities.data(activity_id)`. For the latest activity:
  `client.activities.data(client.activities.latest().id)`. `latest()` returns `None` when the
  user has no activities.
- **`sport=`, one value or a list:** `sport="cycling"` or `sport=["cycling", "running"]`. Never
  `sports=`. Same for `tags=` and `metrics=`. A parent sport matches its sub-sports.
- **`limit` is how many items you get**; the SDK pages through the API.
- **Dates are `datetime.date`** for filters; writes (`traces.create`, `tests.create`) need
  timezone-aware `datetime`s: `datetime.now(timezone.utc)`.
- **`replace()` clears what you leave out**, including a trace's `test_id`. Retrieve first and
  pass every field back.
- **Finding a user by name returns every match:** `client.users.list(name="carla")`. Check the
  length before delegating. `users.retrieve(id)` only finds users you manage.
- **`metric=` is keyword-only:** `client.activities.mean_max(id, metric="power")`.

## Output: models or frames

List methods return Pydantic models by default; time-series methods return a frame of the
installed library (Polars, then pandas, then Arrow). Choose per call with `output=`
(`"models"`, `"pandas"`, `"polars"`, `"arrow"`, and `"bytes"` for raw parquet on time series),
per client (`Client(output="polars")`) or once (`sweatstack.set_output("pandas")`).

No frame has an index: `timestamp`, the mean-max metric and `date` are columns. pandas frames use
float64; Polars and Arrow keep the compact wire dtypes. Nested list fields are dotted columns in
pandas (`summary.power.mean`) and structs in Polars (`.unnest("summary")`).

## Authentication

- Scripts and notebooks: `client.authenticate()` (browser once, tokens saved on the machine).
- Headless: set `SWEATSTACK_API_KEY` (and `SWEATSTACK_REFRESH_TOKEN` for refresh); no
  `authenticate()` call.
- Apps where other people sign in: the Streamlit or FastAPI helper, see
  [streamlit.md](streamlit.md) and [fastapi.md](fastapi.md).

## Errors

Everything derives from `SweatStackError`; never import `httpx`. `SweatStackAPIError` (has
`status_code`, `url`, `method`, `request_id`, `body`) splits into `SweatStackAuthError` (401,
403), `SweatStackNotFoundError` (404), `SweatStackRateLimitError` (429, `retry_after`),
`SweatStackBadRequestError` (other 4xx) and `SweatStackServerError` (5xx). Also
`SweatStackConnectionError` and `SweatStackTokenRefreshError`.

## Reference

- [api.md](api.md): every namespace and method.
- [data-models.md](data-models.md): sports (OpenSportTaxonomy), enums and model fields.
- [streamlit.md](streamlit.md): `StreamlitAuth`, selectors, proxy mode.
- [fastapi.md](fastapi.md): `configure`, `instrument`, user dependencies, webhooks, token stores.
- Docs: https://docs.sweatstack.no; every page as Markdown via https://docs.sweatstack.no/llms.txt.
  REST schema: https://app.sweatstack.no/openapi.json.
