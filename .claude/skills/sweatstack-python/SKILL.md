---
name: sweatstack-python
description: >
  Builds Python applications using the SweatStack client library (uv add "sweatstack[pandas]").
  Covers authentication, activity and trace data retrieval, pandas/Polars/Arrow output, Streamlit
  dashboards, FastAPI backends, user delegation, teams, and file uploads. Use when writing
  Python scripts, notebooks, Streamlit apps, or FastAPI services that access SweatStack
  sports data — even if the user just says "Python" and "SweatStack" without naming the
  library explicitly.
---

# SweatStack Python Client

Python client library for the SweatStack sports data platform.

**Install:** `uv add "sweatstack[pandas]"` for analysis (or `"sweatstack[polars]"`); plain `uv add sweatstack` for
services that only need the models (no frame library is installed by default).

**Extras:** `sweatstack[pandas]` · `sweatstack[polars]` · `sweatstack[streamlit]` (includes pandas) · `sweatstack[fastapi]`

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
df = client.get_activities(output="pandas")     # or output="polars"; default is a list of models
```

Every collection method takes `output=` (`"pandas"`, `"polars"`, `"arrow"`, `"bytes"`; `"models"` for
lists). Time series default to the installed frame library, Polars if both are, so code that assumes
one library should set it once: `sweatstack.set_output("pandas")` or `Client(output="polars")`. No frame has an
index: `timestamp`, the mean-max metric value and `date` are columns.

## Reference

**Client API** — methods for activities, traces, longitudinal data, users, uploads. Read [client.md](client.md)

**Streamlit** — StreamlitAuth, selector components, behind-proxy mode. Read [streamlit.md](streamlit.md)

**FastAPI** — configure/instrument, dependency injection, webhooks, token stores. Read [fastapi.md](fastapi.md)

**Data Models** — Sport, Metric, Scope enums and response model fields. Read [data-models.md](data-models.md)
