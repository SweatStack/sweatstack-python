"""Static type checks for the ``output=`` overloads.

Checked by ``ty`` (``make check``), never executed: editor hints are documentation, and these
pin what a type checker infers for each ``output`` value. The file name has no ``test_`` prefix
so pytest does not collect it.
"""

from datetime import date

import pandas as pd
import polars as pl
import pyarrow as pa
from typing_extensions import assert_type  # typing.assert_type is 3.11+

from sweatstack import ActivityDetails, ActivitySummary, Client, DailyResponse


def _check(client: Client) -> None:
    assert_type(client.activities.data("a", output="pandas"), pd.DataFrame)
    assert_type(client.activities.data("a", output="polars"), pl.DataFrame)
    assert_type(client.activities.data("a", output="arrow"), pa.Table)
    assert_type(client.activities.data("a", output="bytes"), bytes)
    assert_type(client.activities.data("a"), pd.DataFrame | pl.DataFrame)

    assert_type(client.activities.list(), list[ActivitySummary])
    assert_type(client.activities.list(output="pandas"), pd.DataFrame)
    assert_type(client.activities.list(output="polars"), pl.DataFrame)
    assert_type(client.activities.list(output="arrow"), pa.Table)

    assert_type(client.activities.latest(), ActivityDetails | None)
    assert_type(client.activities.mean_max("a", metric="power", output="polars"), pl.DataFrame)
    assert_type(
        client.activities.longitudinal.data(
            sport="cycling", start=date(2026, 1, 1), output="polars"
        ),
        pl.DataFrame,
    )
    assert_type(
        client.dailies.list("hrv", start=date(2026, 1, 1), end=date(2026, 2, 1)),
        list[DailyResponse],
    )
