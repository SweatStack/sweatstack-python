"""Static type checks for the ``output=`` overloads.

Checked by ``ty`` (``make check``), never executed: editor hints are documentation, and these
pin what a type checker infers for each ``output`` value. The file name has no ``test_`` prefix
so pytest does not collect it.
"""

import pandas as pd
import polars as pl
import pyarrow as pa
from typing_extensions import assert_type  # typing.assert_type is 3.11+

from sweatstack import ActivitySummary, Client


def _check(client: Client) -> None:
    assert_type(client.get_activity_data("a", output="pandas"), pd.DataFrame)
    assert_type(client.get_activity_data("a", output="polars"), pl.DataFrame)
    assert_type(client.get_activity_data("a", output="arrow"), pa.Table)
    assert_type(client.get_activity_data("a", output="bytes"), bytes)

    assert_type(client.get_activities(output="models"), list[ActivitySummary])
    assert_type(client.get_activities(output="pandas"), pd.DataFrame)
    assert_type(client.get_activities(output="polars"), pl.DataFrame)
    assert_type(client.get_activities(output="arrow"), pa.Table)
