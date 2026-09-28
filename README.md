# SweatStack Python client library

This is the official Python client library for SweatStack.

Documentation can be found [here](https://docs.sweatstack.no/getting-started/).

Sports follow [OpenSportTaxonomy](https://open-sport-taxonomy.sweatstack.no): `sweatstack.Sport` is the
OST `Sport` type. See the [OpenSportTaxonomy Python guide](https://github.com/SweatStack/open-sport-taxonomy/blob/main/python/README.md)
for the full `Sport` API.

## Install

```bash
uv add "sweatstack[pandas]"     # analysis with pandas
uv add "sweatstack[polars]"     # analysis with Polars (and DuckDB via Arrow / parquet bytes)
uv add sweatstack               # models only: FastAPI services, webhook consumers
```

`sweatstack[streamlit]` and `sweatstack[jupyter]` include pandas.

## Choosing your frame library

Every method that returns a collection takes `output=`. Time-series endpoints return
`"pandas"` (default), `"polars"`, `"arrow"` or `"bytes"`; list endpoints return `"models"`
(default), `"pandas"` or `"polars"`.

```python
from datetime import date
from pathlib import Path

import polars as pl
import sweatstack

sweatstack.authenticate()

df = sweatstack.get_activity_data(activity_id)                    # pandas
pf = sweatstack.get_activity_data(activity_id, output="polars")   # polars.DataFrame
tb = sweatstack.get_activity_data(activity_id, output="arrow")    # pyarrow.Table

sweatstack.set_output("polars")                                   # or Client(output="polars")
season = sweatstack.get_longitudinal_data(sports=["cycling"], start=date(2025, 1, 1))
season.group_by("activity_id").agg(pl.col("power").mean())

acts = sweatstack.get_activities(output="polars")                 # nested fields as structs
acts.unnest("summary").unnest("power").select("id", "mean", "max")

raw = sweatstack.get_longitudinal_data(sports=["cycling"], start=date(2025, 1, 1), output="bytes")
Path("season.parquet").write_bytes(raw)                           # then query it with DuckDB
```

No frame carries an index: `timestamp`, the mean-max metric value and the dailies `date`
are ordinary first columns on every backend. pandas frames keep float64 dtypes; Polars and
Arrow keep the compact wire dtypes.

## Upgrading from 0.88 and earlier

Three mechanical changes:

1. **Install line.** pandas is an extra now: `uv add "sweatstack[pandas]"` (or `[polars]`).
   Streamlit and Jupyter extras already include it.
2. **`as_dataframe=True` → `output="pandas"`.**
3. **Indexes are columns.** If you relied on `df.index` (`.loc[timestamp]`, `.resample()`,
   `.plot()`), add `.set_index("timestamp")` (or `"power"`, `"speed"`, `"date"`) once after
   the call. The set of columns is unchanged; the former index comes first.
