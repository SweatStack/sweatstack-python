"""Attribution: which platform the data came from, and the line to show next to it.

Records carry ``platform`` and ``attribution`` from the server. Parquet responses carry the line in
the ``SweatStack-Attribution`` header, which the SDK puts in the frame's own metadata where the
container has one: ``df.attrs["attribution"]`` (pandas) and the schema metadata
``b"attribution"`` (Arrow). The SDK never composes the line itself.
"""

from datetime import date
from io import BytesIO
from unittest.mock import patch

import httpx2
import pandas as pd
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import sweatstack
from sweatstack import client as client_module
from sweatstack.client import Client
from sweatstack.openapi_schemas import (
    ActivityDetails,
    ActivitySummary,
    TraceDetails,
)

LINE = "Data from Garmin and Strava"


@pytest.fixture(autouse=True)
def _reset_module_default():
    sweatstack.set_output(None)
    yield
    sweatstack.set_output(None)


@pytest.fixture
def client():
    c = Client.__new__(Client)
    c.url = "https://test.sweatstack.no"
    c._access_token = None
    c.streamlit_compatible = False
    c.skip_token_expiry_check = True
    c.output = None
    return c


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

ACTIVITY = {
    "id": "act_123",
    "sport": "cycling.road",
    "start": "2026-06-01T08:00:00Z",
    "end": "2026-06-01T10:00:00Z",
    "start_local": "2026-06-01T10:00:00",
    "end_local": "2026-06-01T12:00:00",
    "duration": "PT2H",
    "metrics": ["power"],
    "source_id": "src_123",
}


@pytest.mark.parametrize("model", [ActivitySummary, ActivityDetails])
@pytest.mark.parametrize("platform, attribution", [("garmin_connect", "Garmin"), (None, None)])
def test_an_activity_says_where_its_data_came_from(model, platform, attribution):
    activity = model.model_validate({**ACTIVITY, "platform": platform, "attribution": attribution})
    assert (activity.platform, activity.attribution) == (platform, attribution)


@pytest.mark.parametrize("model", [ActivitySummary, ActivityDetails])
def test_an_activity_saved_before_attribution_still_loads(model):
    # A model_dump() from an older SDK, a test double, an older server: none has the keys.
    activity = model.model_validate(ACTIVITY)
    assert activity.platform is None and activity.attribution is None


def test_the_activity_in_a_trace_carries_it():
    trace = TraceDetails.model_validate(
        {
            "id": "trace_123",
            "timestamp": "2026-06-01T09:00:00Z",
            "timestamp_local": "2026-06-01T11:00:00",
            "activity": {**ACTIVITY, "platform": "garmin_connect", "attribution": "Garmin"},
        }
    )
    assert trace.activity.attribution == "Garmin"


# ---------------------------------------------------------------------------
# List frames: the model's column order, on every backend
# ---------------------------------------------------------------------------


def _activities(client, output):
    rows = [
        ActivitySummary.model_validate(
            {**ACTIVITY, "platform": "garmin_connect", "attribution": "Garmin"}
        ),
        ActivitySummary.model_validate({**ACTIVITY, "id": "act_456"}),
    ]
    with patch.object(client.activities, "_paginate", return_value=iter(rows)):
        return client.activities.list(output=output)


def _columns(frame) -> list[str]:
    return list(frame.columns) if not isinstance(frame, pa.Table) else frame.column_names


@pytest.mark.parametrize("output", ["pandas", "polars", "arrow"])
def test_activity_frames_have_the_columns_in_the_models_order(client, output):
    columns = _columns(_activities(client, output))

    assert columns.index("platform") == columns.index("source_id") + 1
    assert columns.index("attribution") == columns.index("app_metadata") + 1
    assert columns.index("attribution") + 1 == columns.index("duration")


@pytest.mark.parametrize("output", ["pandas", "polars", "arrow"])
def test_an_activity_from_no_platform_has_nulls(client, output):
    frame = _activities(client, output)
    if isinstance(frame, pa.Table):
        frame = pl.from_arrow(frame)
    if isinstance(frame, pl.DataFrame):
        assert frame["attribution"].to_list() == ["Garmin", None]
        assert frame["platform"].to_list() == ["garmin_connect", None]
    else:  # pandas marks a missing string its own way (NaN under pandas 3's string dtype)
        assert frame["attribution"].iloc[0] == "Garmin" and pd.isna(frame["attribution"].iloc[1])
        assert frame["platform"].iloc[0] == "garmin_connect" and pd.isna(frame["platform"].iloc[1])


def test_trace_frames_carry_the_activitys_line(client):
    trace = TraceDetails.model_validate(
        {
            "id": "trace_123",
            "timestamp": "2026-06-01T09:00:00Z",
            "timestamp_local": "2026-06-01T11:00:00",
            "activity": {**ACTIVITY, "platform": "garmin_connect", "attribution": "Garmin"},
        }
    )
    with patch.object(client.traces, "_paginate", return_value=iter([trace])):
        df = client.traces.list(output="pandas")
    with patch.object(client.traces, "_paginate", return_value=iter([trace])):
        pf = client.traces.list(output="polars")

    assert df["activity.attribution"].tolist() == ["Garmin"]
    assert df["activity.platform"].tolist() == ["garmin_connect"]
    assert pf["activity"].struct.field("attribution").to_list() == ["Garmin"]


# ---------------------------------------------------------------------------
# Parquet: the header, in the frame's own metadata
# ---------------------------------------------------------------------------


def _parquet() -> bytes:
    """A parquet body as the server writes it: pandas metadata plus metadata of its own."""
    table = pa.Table.from_pandas(pd.DataFrame({"power": [200.0, 210.0]}))
    table = table.replace_schema_metadata({**table.schema.metadata, b"server": b"kept"})
    buf = BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue()


def _response(line: str | None) -> httpx2.Response:
    headers = {"SweatStack-Attribution": line} if line is not None else {}
    return httpx2.Response(200, content=_parquet(), headers=headers)


PARQUET_METHODS = pytest.mark.parametrize(
    "call",
    [
        lambda c, o: c.activities.data("act_123", output=o),
        lambda c, o: c.activities.mean_max("act_123", metric="power", output=o),
        lambda c, o: c.activities.awd("act_123", metric="power", output=o),
        lambda c, o: c.activities.longitudinal.data(
            sport="cycling", start=date(2026, 1, 1), output=o
        ),
        lambda c, o: c.activities.longitudinal.mean_max(
            sport="cycling", metric="power", start=date(2026, 1, 1), output=o
        ),
        lambda c, o: c.activities.longitudinal.awd(
            sport="cycling", metric="power", start=date(2026, 1, 1), output=o
        ),
    ],
    ids=[
        "data",
        "mean_max",
        "awd",
        "longitudinal.data",
        "longitudinal.mean_max",
        "longitudinal.awd",
    ],
)


def _fetch(client, call, output, line):
    with patch.object(client, "_request", return_value=_response(line)):
        return call(client, output)


@PARQUET_METHODS
def test_pandas_has_the_line_in_attrs(client, call):
    assert _fetch(client, call, "pandas", LINE).attrs == {"attribution": LINE}


@PARQUET_METHODS
def test_arrow_has_the_line_in_the_schema_metadata(client, call):
    metadata = _fetch(client, call, "arrow", LINE).schema.metadata

    assert metadata[b"attribution"] == LINE.encode()
    assert metadata[b"server"] == b"kept"
    assert b"pandas" not in metadata


@PARQUET_METHODS
@pytest.mark.parametrize("output", ["pandas", "arrow"])
def test_without_the_header_there_is_no_key(client, call, output):
    frame = _fetch(client, call, output, None)
    if output == "pandas":
        assert "attribution" not in frame.attrs
    else:
        assert b"attribution" not in frame.schema.metadata


@PARQUET_METHODS
@pytest.mark.parametrize("output", ["polars", "bytes"])
def test_polars_and_bytes_are_unchanged(client, call, output):
    with_line = _fetch(client, call, output, LINE)
    without = _fetch(client, call, output, None)
    if output == "bytes":
        assert with_line == without == _parquet()
    else:
        assert with_line.equals(without)


def test_the_polars_route_goes_through_arrow(client):
    table = _fetch(
        client,
        lambda c, o: c.activities.longitudinal.data(
            sport="cycling", start=date(2026, 1, 1), output=o
        ),
        "arrow",
        LINE,
    )
    line = (table.schema.metadata or {}).get(b"attribution", b"").decode() or None
    df = pl.from_arrow(table)

    assert line == LINE
    assert df.columns == ["power"]


def test_streamlit_keeps_the_line(client):
    client.streamlit_compatible = True
    df = _fetch(client, lambda c, o: c.activities.data("act_123", output=o), "pandas", LINE)
    assert df.attrs["attribution"] == LINE


def test_a_non_ascii_line_round_trips_through_arrow(client):
    table = client._read_frame(_parquet(), "arrow", attribution="Données de Garmin")
    assert table.schema.metadata[b"attribution"].decode() == "Données de Garmin"


# ---------------------------------------------------------------------------
# The cache keeps the line with the data
# ---------------------------------------------------------------------------


@pytest.fixture
def cache(client, tmp_path):
    with (
        patch.object(client_module, "_cache_config", {"path": str(tmp_path)}),
        patch.object(client, "_get_cache_dir", return_value=tmp_path),
    ):
        yield tmp_path


def _longitudinal(client, line):
    with patch.object(client, "_request", return_value=_response(line)) as request:
        df = client.activities.longitudinal.data(
            sport="cycling", start=date(2026, 1, 1), output="pandas"
        )
    return df, request.call_count


@pytest.mark.parametrize("line", [LINE, None])
def test_a_cache_hit_has_the_same_line(client, cache, line):
    miss, fetched = _longitudinal(client, line)
    hit, fetched_again = _longitudinal(client, line)

    assert (fetched, fetched_again) == (1, 0)
    assert hit.attrs == miss.attrs == ({"attribution": line} if line else {})


def test_an_entry_cached_without_its_line_is_fetched_again(client, cache):
    _longitudinal(client, LINE)
    for sidecar in cache.glob("*.attribution"):
        sidecar.unlink()  # as an SDK before 0.100 left it

    df, fetched = _longitudinal(client, LINE)

    assert fetched == 1
    assert df.attrs == {"attribution": LINE}
    assert len(list(cache.glob("*.attribution"))) == 1
