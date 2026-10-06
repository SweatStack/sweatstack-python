"""The ``output=`` contract: which container a collection comes back in.

Covers resolution order (per-call > client > module default > method default),
validation, every backend on parquet and list endpoints, columns-everywhere
(no backend returns an index), propagation into delegated clients, and the
internal callers that must keep receiving models.
"""

from datetime import date
from io import BytesIO
from unittest.mock import MagicMock, patch

import pandas as pd
import polars as pl
import pyarrow as pa
import pytest

import sweatstack
from sweatstack import _frames
from sweatstack.client import Client
from sweatstack.openapi_schemas import ActivitySummary, DailyResponse

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


def _mean_max_with_index() -> bytes:
    """A mean-max response as the server writes it today: metric value as a pandas index."""
    df = pd.DataFrame(
        {"duration": pd.to_timedelta([1, 5, 60], unit="s"), "speed": pd.array([9.5, 9.0, 8.25], dtype="float16")},
        index=pd.Index([400.0, 350.0, 300.0], name="power"),
    )
    buf = BytesIO()
    df.to_parquet(buf)
    return buf.getvalue()


def _mean_max_without_index() -> bytes:
    """The same response once the server drops the index: plain columns."""
    df = pd.read_parquet(BytesIO(_mean_max_with_index())).reset_index()
    buf = BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def _http_returning(content: bytes):
    response = MagicMock(status_code=200, content=content)
    http = MagicMock()
    http.__enter__ = MagicMock(return_value=http)
    http.__exit__ = MagicMock(return_value=False)
    http.get.return_value = response
    return http


def _get_activity_mean_max(client, content: bytes, **kwargs):
    with patch.object(client, "_http_client", return_value=_http_returning(content)), \
         patch.object(client, "_raise_for_status"), \
         patch.object(client, "_cache_enabled", return_value=False):
        return client.get_activity_mean_max("a", "power", **kwargs)


def _activity(i: int) -> ActivitySummary:
    return ActivitySummary.model_validate({
        "id": f"a{i}",
        "start": "2025-06-01T08:00:00Z",
        "end": "2025-06-01T10:00:00Z",
        "start_local": "2025-06-01T10:00:00",
        "end_local": "2025-06-01T12:00:00",
        "sport": "cycling.road",
        "duration": "PT2H",
        "metrics": ["power"],
        "source_id": "s1",
        "summary": {"power": {"mean": 200 + i, "max": 500}},
    })


def _get_activities(client, activities, **kwargs):
    with patch.object(client, "_get_activities_generator", return_value=iter(activities)):
        return client.get_activities(**kwargs)


# ---------------------------------------------------------------------------
# Resolution and validation
# ---------------------------------------------------------------------------


def _installed(*modules):
    """Patch importlib so only ``modules`` look installed."""
    real = _frames.find_spec
    return patch.object(_frames, "find_spec", side_effect=lambda name: real(name) if name in modules else None)


class TestResolution:
    def test_method_defaults(self, client):
        # dev environment has both libraries installed: Polars wins for parquet, lists stay models
        assert isinstance(_get_activity_mean_max(client, _mean_max_with_index()), pl.DataFrame)
        assert isinstance(_get_activities(client, [_activity(1)]), list)

    def test_default_frame_is_the_installed_library(self, client):
        with _installed("pandas"):
            assert isinstance(_get_activity_mean_max(client, _mean_max_with_index()), pd.DataFrame)
        with _installed("polars"):
            assert isinstance(_get_activity_mean_max(client, _mean_max_with_index()), pl.DataFrame)
        with _installed("polars", "pandas"):
            assert isinstance(_get_activity_mean_max(client, _mean_max_with_index()), pl.DataFrame)
        with _installed("pyarrow"):  # a DuckDB-only environment
            assert isinstance(_get_activity_mean_max(client, _mean_max_with_index()), pa.Table)
        with _installed("pandas", "pyarrow"):
            assert isinstance(_get_activity_mean_max(client, _mean_max_with_index()), pd.DataFrame)

    def test_no_frame_library_is_an_actionable_error(self, client):
        with _installed(), pytest.raises(ImportError, match=r'sweatstack\[polars\].*sweatstack\[pandas\].*sweatstack\[arrow\].*bytes'):
            _get_activity_mean_max(client, _mean_max_with_index())
        with _installed():  # explicit outputs that need no library still work
            assert isinstance(_get_activity_mean_max(client, _mean_max_with_index(), output="bytes"), bytes)
            assert isinstance(_get_activities(client, [_activity(1)]), list)

    def test_configured_output_beats_the_installed_default(self, client):
        client.output = "pandas"
        assert isinstance(_get_activity_mean_max(client, _mean_max_with_index()), pd.DataFrame)

    def test_per_call_beats_client_beats_module(self, client):
        sweatstack.set_output("arrow")
        assert isinstance(_get_activity_mean_max(client, _mean_max_with_index()), pa.Table)
        client.output = "polars"
        assert isinstance(_get_activity_mean_max(client, _mean_max_with_index()), pl.DataFrame)
        assert isinstance(_get_activity_mean_max(client, _mean_max_with_index(), output="pandas"), pd.DataFrame)

    def test_client_default_applies_to_list_endpoints_too(self, client):
        client.output = "polars"
        assert isinstance(_get_activities(client, [_activity(1)]), pl.DataFrame)
        assert isinstance(_get_activities(client, [_activity(1)], output="models"), list)

    def test_configured_output_a_method_cannot_produce_is_skipped(self, client):
        client.output = "bytes"
        assert isinstance(_get_activities(client, [_activity(1)]), list)
        sweatstack.set_output("polars")  # client 'bytes' does not apply, module 'polars' does
        assert isinstance(_get_activities(client, [_activity(1)]), pl.DataFrame)

    def test_per_call_output_a_method_cannot_produce_is_an_error(self, client):  # bytes on lists, models on parquet
        with pytest.raises(ValueError, match="'arrow', 'models', 'pandas', 'polars'"):
            _get_activities(client, [_activity(1)], output="bytes")
        with pytest.raises(ValueError, match="'arrow', 'bytes', 'pandas', 'polars'"):
            _get_activity_mean_max(client, _mean_max_with_index(), output="models")

    def test_models_cannot_be_a_configured_default(self):
        with pytest.raises(ValueError, match="cannot be a default"):
            sweatstack.set_output("models")
        with pytest.raises(ValueError, match="cannot be a default"):
            Client(api_key="x", output="models")
        with pytest.raises(ValueError):
            Client(api_key="x", output="excel")

    def test_client_accepts_and_stores_frame_outputs(self):
        assert Client(api_key="x", output="polars").output == "polars"
        assert Client(api_key="x").output is None

    def test_set_output_is_public(self):
        assert "set_output" in sweatstack.__all__
        sweatstack.set_output("polars")
        assert _frames.resolve_output(None, None, allowed=_frames.LIST_OUTPUTS) == "polars"


# ---------------------------------------------------------------------------
# Parquet endpoints: every backend, columns everywhere
# ---------------------------------------------------------------------------


class TestParquetBackends:
    @pytest.mark.parametrize("content", [_mean_max_with_index(), _mean_max_without_index()], ids=["indexed", "columns"])
    def test_pandas_returns_columns_with_standard_dtypes(self, client, content):
        df = _get_activity_mean_max(client, content, output="pandas")
        assert isinstance(df.index, pd.RangeIndex)
        assert list(df.columns) == ["power", "duration", "speed"]
        assert df["speed"].dtype == "float64"
        assert df["duration"].dtype == "timedelta64[ns]"
        assert df["power"].tolist() == [400.0, 350.0, 300.0]

    @pytest.mark.parametrize("content", [_mean_max_with_index(), _mean_max_without_index()], ids=["indexed", "columns"])
    def test_polars_keeps_wire_dtypes_except_float16(self, client, content):
        df = _get_activity_mean_max(client, content, output="polars")
        assert df.columns == ["power", "duration", "speed"]
        assert df.schema["speed"] == pl.Float32
        assert df.schema["power"] == pl.Float64
        assert isinstance(df.schema["duration"], pl.Duration)
        assert df["power"].to_list() == [400.0, 350.0, 300.0]

    @pytest.mark.parametrize("content", [_mean_max_with_index(), _mean_max_without_index()], ids=["indexed", "columns"])
    def test_arrow_is_the_wire_table_without_pandas_index_metadata(self, client, content):
        table = _get_activity_mean_max(client, content, output="arrow")
        assert table.column_names == ["power", "duration", "speed"]
        assert table.schema.field("speed").type == pa.float16()  # untouched
        assert b"pandas" not in (table.schema.metadata or {})
        assert isinstance(table.to_pandas().index, pd.RangeIndex)

    def test_bytes_is_the_response_body(self, client):
        content = _mean_max_with_index()
        assert _get_activity_mean_max(client, content, output="bytes") is content

    def test_same_columns_on_every_backend(self, client):
        content = _mean_max_with_index()
        expected = ["power", "duration", "speed"]
        assert list(_get_activity_mean_max(client, content, output="pandas").columns) == expected
        assert _get_activity_mean_max(client, content, output="polars").columns == expected
        assert _get_activity_mean_max(client, content, output="arrow").column_names == expected

    def test_streamlit_compatibility_applies_to_pandas_only(self, client):
        client.streamlit_compatible = True
        with patch("sweatstack.client.make_dataframe_streamlit_compatible", side_effect=lambda df: df) as compat:
            _get_activity_mean_max(client, _mean_max_with_index(), output="pandas")
            assert compat.call_count == 1
            _get_activity_mean_max(client, _mean_max_with_index(), output="polars")
            assert compat.call_count == 1

    def test_latest_activity_data_forwards_output(self, client):
        with patch.object(client, "get_latest_activity", return_value=MagicMock(id="a")), \
             patch.object(client, "get_activity_data", return_value="frame") as get_data:
            assert client.get_latest_activity_data(output="polars") == "frame"
        assert get_data.call_args.kwargs["output"] == "polars"

    def test_latest_activity_mean_max_forwards_output(self, client):
        with patch.object(client, "get_latest_activity", return_value=MagicMock(id="a")), \
             patch.object(client, "get_activity_mean_max", return_value="frame") as get_mm:
            assert client.get_latest_activity_mean_max("power", output="arrow") == "frame"
        assert get_mm.call_args.kwargs["output"] == "arrow"


# ---------------------------------------------------------------------------
# List endpoints
# ---------------------------------------------------------------------------


class TestListBackends:
    def test_pandas_flattens_nested_fields(self, client):
        df = _get_activities(client, [_activity(1), _activity(2)], output="pandas")
        assert isinstance(df, pd.DataFrame)
        assert "summary.power.mean" in df.columns
        assert df["summary.power.mean"].tolist() == [201.0, 202.0]

    def test_polars_nests_typed_structs(self, client):
        df = _get_activities(client, [_activity(1), _activity(2)], output="polars")
        assert df.unnest("summary").unnest("power")["mean"].to_list() == [201.0, 202.0]
        assert df.schema["start"] == pl.Datetime("us", "UTC")

    def test_arrow_nests_typed_structs(self, client):
        table = _get_activities(client, [_activity(1), _activity(2)], output="arrow")
        assert isinstance(table, pa.Table)
        assert table.column("summary").to_pylist()[0]["power"]["mean"] == 201.0

    def test_empty_lists_give_typed_empty_frames(self, client):
        assert _get_activities(client, [], output="models") == []
        assert "id" in _get_activities(client, [], output="pandas").columns
        assert _get_activities(client, [], output="polars").schema["id"] == pl.String
        assert _get_activities(client, [], output="arrow").schema.field("id").type == pa.string()

    def test_dailies_date_is_a_column(self, client):
        dailies = [DailyResponse(date=date(2026, 4, 1), value=75.2, status="stored", source="manual")]
        with patch.object(client, "_http_client", return_value=_http_returning(b"")) as http, \
             patch.object(client, "_raise_for_status"):
            http.return_value.get.return_value.json.return_value = [d.model_dump(mode="json") for d in dailies]
            df = client.get_dailies("body_mass", start=date(2026, 4, 1), end=date(2026, 4, 1), output="pandas")
            pf = client.get_dailies("body_mass", start=date(2026, 4, 1), end=date(2026, 4, 1), output="polars")
        assert isinstance(df.index, pd.RangeIndex) and list(df.columns) == ["date", "value", "status", "source"]
        assert pf.columns == ["date", "value", "status", "source"]

    def test_as_dataframe_is_gone(self, client):
        with pytest.raises(TypeError):
            _get_activities(client, [], as_dataframe=True)


# ---------------------------------------------------------------------------
# Propagation and internal callers
# ---------------------------------------------------------------------------


class TestPropagation:
    def test_delegated_and_principal_clients_inherit_output(self):
        client = Client(api_key="x", output="polars")
        token = {"access_token": "a", "refresh_token": "r"}
        with patch.object(Client, "_get_delegated_token", return_value=token), \
             patch.object(Client, "_get_principal_token", return_value=token):
            assert client.delegated_client("someone").output == "polars"
            assert client.principal_client().output == "polars"

    def test_streamlit_selector_always_receives_models(self):
        streamlit = pytest.importorskip("sweatstack.streamlit")
        auth = streamlit.StreamlitAuth.__new__(streamlit.StreamlitAuth)
        auth.client = MagicMock()
        auth.client.get_activities.return_value = [_activity(1)]
        with patch.object(streamlit.st, "selectbox", side_effect=lambda label, options, **kw: options[0]):
            selected = auth.select_activity()
        assert selected.id == "a1"
        assert auth.client.get_activities.call_args.kwargs["output"] == "models"
