"""Tests for the `after` (fatigue-state) param on get_longitudinal_mean_max.

Shapes are asserted on the pandas output; the backend choice itself is covered in test_output.py."""

from io import BytesIO
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from sweatstack.client import Client


@pytest.fixture
def client():
    c = Client.__new__(Client)
    c.url = "https://test.sweatstack.no"
    c._access_token = None
    c.streamlit_compatible = False
    c.skip_token_expiry_check = True
    return c


def _index_free_after_response() -> bytes:
    """An index-free `after` long-format response, as the API returns it."""
    df = pd.DataFrame(
        {
            "power": [100.0, 200.0, 90.0, 180.0],
            "after": [0.0, 0.0, 500.0, 500.0],
            "duration": pd.to_timedelta([300, 60, 200, 40], unit="s"),
            "start": pd.to_datetime(["2024-01-01"] * 4, utc=True),
            "activity_id": ["a", "a", "b", "b"],
            "sport": ["cycling"] * 4,
        }
    )
    buf = BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def _call(client, **kwargs):
    response = MagicMock(status_code=200, content=_index_free_after_response())
    http = MagicMock()
    http.__enter__ = MagicMock(return_value=http)
    http.__exit__ = MagicMock(return_value=False)
    http.get.return_value = response
    with (
        patch.object(client, "_http_client", return_value=http),
        patch.object(client, "_raise_for_status"),
        patch.object(client, "_cache_enabled", return_value=False),
    ):
        result = client.get_longitudinal_mean_max(
            sports=["cycling"], metric="power", output="pandas", **kwargs
        )
    return result, http.get.call_args.kwargs["params"]


def test_after_list_is_sent_and_default_power_is_duration_indexed(client):
    result, params = _call(client, after=[0, 500])
    # repeated query param
    assert params["after"] == [0, 500]
    # `by` unset for after+power resolves to `duration` server-side (0.85.0+). Every
    # frame is column-shaped: duration, power and after are all columns, no index.
    assert isinstance(result.index, pd.RangeIndex)
    assert {"duration", "power", "after"} <= set(result.columns)
    assert set(result["after"].unique()) == {0.0, 500.0}


def test_single_after_is_normalised_to_a_list(client):
    _result, params = _call(client, after=500)
    assert params["after"] == [500]


def test_no_after_is_unchanged(client):
    # without `after`, no after param is sent; the server's metric index becomes a leading column
    response = MagicMock(status_code=200)
    df = pd.DataFrame(
        {"duration": pd.to_timedelta([60], unit="s")}, index=pd.Index([200.0], name="power")
    )
    buf = BytesIO()
    df.to_parquet(buf)
    response.content = buf.getvalue()
    http = MagicMock()
    http.__enter__ = MagicMock(return_value=http)
    http.__exit__ = MagicMock(return_value=False)
    http.get.return_value = response
    with (
        patch.object(client, "_http_client", return_value=http),
        patch.object(client, "_raise_for_status"),
        patch.object(client, "_cache_enabled", return_value=False),
    ):
        result = client.get_longitudinal_mean_max(
            sports=["cycling"], metric="power", output="pandas"
        )
    assert "after" not in http.get.call_args.kwargs["params"]
    assert isinstance(result.index, pd.RangeIndex)
    assert list(result.columns) == ["power", "duration"]


def _index_free_by_duration_response() -> bytes:
    """An `after` response as the server returns it: one row per duration, columns only."""
    df = pd.DataFrame(
        {
            "duration": pd.to_timedelta([5, 60, 300, 5, 60], unit="s"),
            "power": [400.0, 300.0, 250.0, 380.0, 290.0],
            "activity_id": ["a", "a", "a", "b", "b"],
            "sport": ["cycling"] * 5,
            "after": [0.0, 0.0, 0.0, 50.0, 50.0],
        }
    )
    buf = BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def test_durations_are_omitted_by_default_and_sent_when_given(client):
    _result, params = _call(client, after=[0, 500])
    assert "durations" not in params and "by" not in params
    _result, params = _call(client, after=[0, 500], durations=[5, 60, 300])
    assert params["durations"] == "5,60,300"
    _result, params = _call(client, durations="all")
    assert params["durations"] == "all"


def test_by_is_removed(client):
    # Every mean-max response is duration-oriented; `by` is gone.
    with pytest.raises(TypeError):
        _call(client, after=[0, 50], by="duration")


def test_after_response_is_duration_rows_with_columns_only(client):
    response = MagicMock(status_code=200, content=_index_free_by_duration_response())
    http = MagicMock()
    http.__enter__ = MagicMock(return_value=http)
    http.__exit__ = MagicMock(return_value=False)
    http.get.return_value = response
    with (
        patch.object(client, "_http_client", return_value=http),
        patch.object(client, "_raise_for_status"),
        patch.object(client, "_cache_enabled", return_value=False),
    ):
        result = client.get_longitudinal_mean_max(
            sports=["cycling"], metric="power", after=[0, 50], output="pandas"
        )
    assert isinstance(result.index, pd.RangeIndex)
    assert {"duration", "power", "after"} <= set(result.columns)
    assert set(result["after"].unique()) == {0.0, 50.0}
