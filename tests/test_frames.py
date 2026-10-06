"""Frame construction from Pydantic models (``sweatstack._frames``).

The Polars path derives its schema from each model's JSON Schema. These tests
are the regen guard: any construct the mapper does not know raises here (via
``FrameSchemaWarning`` turned into an error), not in a user's notebook.
"""

import json
import warnings
from datetime import date, datetime, timedelta, timezone
from inspect import isclass

import polars as pl
import pyarrow as pa
import pytest
from pydantic import BaseModel

import sweatstack.schemas as schemas
from sweatstack import _frames
from sweatstack._frames import (
    FrameSchemaWarning,
    arrow_schema,
    field_types,
    models_to_arrow,
    models_to_pandas,
    models_to_polars,
    polars_schema,
)
from sweatstack.openapi_schemas import ActivitySummary, DailyResponse, TraceDetails

PUBLIC_MODELS = sorted(
    (obj for obj in vars(schemas).values() if isclass(obj) and issubclass(obj, BaseModel) and obj is not BaseModel),
    key=lambda model: model.__name__,
)


def _activity(**overrides) -> ActivitySummary:
    base = dict(
        id="a1",
        start="2025-06-01T08:00:00Z",
        end="2025-06-01T10:00:00Z",
        start_local="2025-06-01T10:00:00",
        end_local="2025-06-01T12:00:00",
        sport="cycling.road",
        duration="PT2H",
        tags=["race"],
        metrics=["power", "heart_rate"],
        source_id="s1",
        summary={"power": {"mean": 210, "max": 500}, "distance": {"sum": 61234}},
        laps=[],
        traces=[],
        app_metadata={"k": [1, 2]},
    )
    return ActivitySummary.model_validate({**base, **overrides})


LAP = {
    "start": "2025-06-01T08:00:00Z",
    "end": "2025-06-01T08:10:00Z",
    "duration": "PT10M",
    "start_local": "2025-06-01T10:00:00",
    "end_local": "2025-06-01T10:10:00",
    "power": {"mean": 250, "max": 400},
}


class TestRegenGuard:
    @pytest.mark.parametrize("model", PUBLIC_MODELS, ids=lambda m: m.__name__)
    def test_every_public_model_maps_without_fallback(self, model):
        field_types.cache_clear()
        with warnings.catch_warnings():
            warnings.simplefilter("error", FrameSchemaWarning)
            schema = polars_schema(model)
            assert arrow_schema(model).names == list(schema)
        assert set(schema) == set(model.model_fields), "frame columns must be the model's fields"

    @pytest.mark.parametrize("model", PUBLIC_MODELS, ids=lambda m: m.__name__)
    def test_pandas_and_polars_start_from_the_same_columns(self, model):
        assert set(models_to_pandas([], model).columns) == set(polars_schema(model))

    def test_unknown_construct_warns_and_falls_back_to_json_text(self):
        class Odd(BaseModel):
            mixed: int | str

        field_types.cache_clear()
        with pytest.warns(FrameSchemaWarning, match="Odd.mixed"):
            schema = polars_schema(Odd)
        assert schema["mixed"] == pl.String
        assert models_to_polars([Odd(mixed=3), Odd(mixed="x")], Odd)["mixed"].to_list() == ["3", "x"]


class TestPolarsSchema:
    def test_scalar_and_temporal_dtypes(self):
        schema = polars_schema(ActivitySummary)
        assert schema["id"] == pl.String
        assert schema["sport"] == pl.String  # OST Sport serialises as a string
        assert schema["start"] == pl.Datetime("us", "UTC")
        assert schema["start_local"] == pl.Datetime("us", None)  # naive wall-clock, never UTC
        assert schema["duration"] == pl.Duration("us")
        assert schema["metrics"] == pl.List(pl.String)  # enums are strings
        assert schema["app_metadata"] == pl.String  # free-form dict is JSON text

    def test_nested_models_are_typed_structs(self):
        summary = polars_schema(ActivitySummary)["summary"]
        assert isinstance(summary, pl.Struct)
        power = dict(summary.to_schema())["power"]
        assert power == pl.Struct({"mean": pl.Float64, "max": pl.Float64})
        # int | float unions collapse to Float64 instead of falling back
        assert dict(summary.to_schema())["distance"] == pl.Struct({"sum": pl.Float64})

    def test_recursive_reference_becomes_json_text(self):
        activity = polars_schema(TraceDetails)["activity"]
        assert isinstance(activity, pl.Struct)
        # activity.traces[] would be TraceDetails again: each item is JSON text
        assert dict(activity.to_schema())["traces"] == pl.List(pl.String)

    def test_aware_or_naive_datetime_union_is_utc(self):
        from sweatstack.openapi_schemas import UserResponse

        assert polars_schema(UserResponse)["registered_at"] == pl.Datetime("us", "UTC")
        def user(registered_at):
            return UserResponse(id="u", first_name="a", last_name=None, admin=False, display_name="a",
                                is_managed=False, registered_at=registered_at)

        naive = user(datetime(2025, 1, 1, 12))
        aware = user(datetime(2025, 1, 1, 12, tzinfo=timezone.utc))
        df = models_to_polars([naive, aware], UserResponse)
        assert df["registered_at"].to_list() == [datetime(2025, 1, 1, 12, tzinfo=timezone.utc)] * 2

    def test_dailies(self):
        schema = polars_schema(DailyResponse)
        assert schema["date"] == pl.Date
        assert schema["value"] == pl.Float64
        assert schema["status"] == pl.String


class TestModelsToPolars:
    def test_round_trip_values(self):
        a1 = _activity()
        a2 = _activity(id="a2", summary=None, metrics=["speed"], laps=[LAP], tags=None, app_metadata=None)
        df = models_to_polars([a1, a2], ActivitySummary)

        assert df.shape == (2, len(ActivitySummary.model_fields))
        assert df["sport"].to_list() == ["cycling.road", "cycling.road"]
        assert df["start"].to_list() == [datetime(2025, 6, 1, 8, tzinfo=timezone.utc)] * 2
        assert df["start_local"].to_list() == [datetime(2025, 6, 1, 10)] * 2
        assert df["duration"].to_list() == [timedelta(hours=2)] * 2
        assert df["metrics"].to_list() == [["power", "heart_rate"], ["speed"]]
        assert df["tags"].to_list() == [["race"], None]
        assert json.loads(df["app_metadata"][0]) == {"k": [1, 2]} and df["app_metadata"][1] is None

        power = df.unnest("summary").unnest("power")
        assert power["mean"].to_list() == [210.0, None]
        assert df.select(pl.col("laps").list.len()).to_series().to_list() == [0, 1]
        lap_mean = df.select(pl.col("laps").list.eval(pl.element().struct.field("power").struct.field("mean")))
        assert lap_mean.to_series().to_list() == [[], [250.0]]

    def test_empty_list_gives_typed_empty_frame(self):
        df = models_to_polars([], ActivitySummary)
        assert df.shape == (0, len(ActivitySummary.model_fields))
        assert df.schema == pl.Schema(polars_schema(ActivitySummary))

    def test_recursive_field_is_serialised_as_json_text(self):
        trace = TraceDetails.model_validate({
            "id": "t1",
            "timestamp": "2025-06-01T09:00:00Z",
            "timestamp_local": "2025-06-01T11:00:00",
            "sport": "cycling",
            "activity": _activity().model_dump(),
        })
        df = models_to_polars([trace], TraceDetails)
        nested = df["activity"][0]
        assert nested["id"] == "a1"
        assert nested["traces"] == []
        # a populated recursive item is JSON text, not a struct
        trace.activity.traces = [trace.model_copy(update={"activity": None})]
        nested = models_to_polars([trace], TraceDetails)["activity"][0]
        assert json.loads(nested["traces"][0])["id"] == "t1"

    def test_wrong_type_never_coerces_silently(self):
        schema = polars_schema(DailyResponse)
        with pytest.raises(pl.exceptions.ComputeError):
            pl.from_dicts([{"date": "not-a-date", "value": 1.0, "status": "stored", "source": None}], schema=schema)

    def test_dailies_values(self):
        dailies = [
            DailyResponse(date=date(2026, 4, 1), value=75.2, status="stored", source="manual"),
            DailyResponse(date=date(2026, 4, 3), value=None, status="missing", source=None),
        ]
        df = models_to_polars(dailies, DailyResponse)
        assert df["date"].to_list() == [date(2026, 4, 1), date(2026, 4, 3)]
        assert df["value"].to_list() == [75.2, None]
        assert df["status"].to_list() == ["stored", "missing"]


class TestModelsToArrow:
    def test_arrow_and_polars_agree(self):
        a1 = _activity()
        a2 = _activity(id="a2", summary=None, metrics=["speed"], laps=[LAP], tags=None, app_metadata=None)
        table = models_to_arrow([a1, a2], ActivitySummary)
        assert isinstance(table, pa.Table)
        assert table.schema.field("start").type == pa.timestamp("us", tz="UTC")
        assert table.schema.field("start_local").type == pa.timestamp("us")
        assert table.schema.field("duration").type == pa.duration("us")
        assert pa.types.is_struct(table.schema.field("summary").type)
        # one type tree, two renderings: the Arrow table round-trips into the Polars frame exactly
        assert pl.from_arrow(table).equals(models_to_polars([a1, a2], ActivitySummary))

    def test_empty_and_to_pandas(self):
        table = models_to_arrow([], ActivitySummary)
        assert table.num_rows == 0 and table.schema == arrow_schema(ActivitySummary)
        df = models_to_arrow([_activity()], ActivitySummary).to_pandas()
        assert df["sport"][0] == "cycling.road" and df["summary"][0]["power"]["mean"] == 210.0


class TestRequire:
    def test_missing_library_names_the_extra(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "polars", None)  # import machinery raises ImportError
        with pytest.raises(ImportError, match=r'uv add "sweatstack\[polars\]"'):
            _frames.require("polars")
        monkeypatch.setitem(sys.modules, "pyarrow", None)
        monkeypatch.setitem(sys.modules, "pyarrow.parquet", None)
        with pytest.raises(ImportError, match=r'uv add "sweatstack\[arrow\]"'):
            _frames.require("pyarrow.parquet")
