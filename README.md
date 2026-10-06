# SweatStack Python SDK

The official Python client for [SweatStack](https://sweatstack.no), the sports data platform:
one API for activities, time series, lab tests and daily measures from every wearable.

## Install

```bash
uv add "sweatstack[polars]"     # analysis with Polars
uv add "sweatstack[pandas]"     # analysis with pandas
uv add sweatstack               # models only: FastAPI services, webhook consumers
```

Other extras: `[arrow]` (DuckDB), `[streamlit]` and `[fastapi]` (sign-in helpers). Extras
combine: `sweatstack[polars,arrow]`.

## Quickstart

```python
from sweatstack import Client

client = Client()
client.authenticate()  # opens the browser once; the sign-in is saved for later runs

latest = client.activities.latest()
if latest is None:
    raise SystemExit("No activities yet: connect a wearable at https://app.sweatstack.no")
print(latest.sport, latest.start_local)

data = client.activities.data(latest.id, metrics=["power", "heart_rate"])
print(data.head())
```

Every endpoint group is an attribute named after its URL: `/api/v1/activities/...` is
`client.activities`, `/api/v1/tests/...` is `client.tests`. Collections take `output=`
(`"polars"`, `"pandas"`, `"arrow"`) for a frame instead of models.

In a script or notebook, the module-level functions use one shared client:
`sweatstack.activities.list()`. In an app that serves several users, use one `Client` per user,
such as the ones the FastAPI and Streamlit helpers give you.

## For coding agents

Install the SDK's [agent skill](skills/sweatstack-python/SKILL.md) for Claude Code, Cursor, Codex
and other agents:

```bash
npx skills add SweatStack/sweatstack-python
```

## Documentation

- [Python SDK guide](https://docs.sweatstack.no/learn/libraries/python/): authentication,
  clients, data output, errors, Streamlit and FastAPI
- [API reference](https://docs.sweatstack.no/learn/api-reference/): every endpoint and model
- [Changelog](CHANGELOG.md), with an upgrade path for every breaking change

Sports follow [OpenSportTaxonomy](https://open-sport-taxonomy.sweatstack.no): `sweatstack.Sport`
is its `Sport` type.
