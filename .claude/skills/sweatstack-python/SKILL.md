---
name: sweatstack-python
description: >
  Builds Python applications using the SweatStack client library (uv add sweatstack).
  Covers authentication, activity and trace data retrieval, pandas DataFrames, Streamlit
  dashboards, FastAPI backends, user delegation, teams, and file uploads. Use when writing
  Python scripts, notebooks, Streamlit apps, or FastAPI services that access SweatStack
  sports data — even if the user just says "Python" and "SweatStack" without naming the
  library explicitly.
---

# SweatStack Python Client

Python client library for the SweatStack sports data platform.

**Install:** `uv add sweatstack`

**Extras:** `uv add sweatstack[streamlit]` · `uv add sweatstack[fastapi]`

## Quick Start

```python
import sweatstack

sweatstack.authenticate()  # Opens browser, stores tokens locally
activities = sweatstack.get_activities(limit=5)
for a in activities:
    print(f"{a.start_local:%Y-%m-%d} {a.sport.display_name()} {a.duration}")
```

Or with an explicit client:

```python
from sweatstack import Client

client = Client()
client.authenticate()
df = client.get_activities(as_dataframe=True)
```

## Reference

**Client API** — methods for activities, traces, longitudinal data, users, uploads. Read [client.md](client.md)

**Streamlit** — StreamlitAuth, selector components, behind-proxy mode. Read [streamlit.md](streamlit.md)

**FastAPI** — configure/instrument, dependency injection, webhooks, token stores. Read [fastapi.md](fastapi.md)

**Data Models** — Sport, Metric, Scope enums and response model fields. Read [data-models.md](data-models.md)
