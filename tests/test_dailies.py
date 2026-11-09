"""Tests for the Dailies (daily health metrics) functionality.

Tests DailyMeasure enum enhancements, DataFrame conversion, and enum
serialization without hitting the API.
"""

from datetime import date

import pandas as pd
import pytest
from pydantic import ValidationError

from sweatstack import DailyMeasure, DailyResponse, SourceResponse, WriterKind, _frames
from sweatstack.openapi_schemas import DailyStatus, MarkerRowResponse, MaxEffortRowResponse

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_dailies() -> list[DailyResponse]:
    # status is read-time state; who wrote it and where it came from exist only when stored.
    return [
        DailyResponse(date=date(2026, 4, 1), value=75.2, status="stored", writer="athlete"),
        DailyResponse(date=date(2026, 4, 2), value=75.1, status="estimated"),
        DailyResponse(date=date(2026, 4, 3), value=None, status="missing"),
    ]


# The order follows the server's document (the record first, then who wrote it); the SDK never
# reorders a model's columns.
DAILY_COLUMNS = ["date", "value", "status", "writer", "application_id", "platform"]


# ---------------------------------------------------------------------------
# DailyMeasure enum enhancement tests
# ---------------------------------------------------------------------------


class TestDailyMeasureEnum:
    def test_display_name(self):
        """display_name() should replace underscores with spaces."""
        assert DailyMeasure.body_mass.display_name() == "body mass"
        assert DailyMeasure.body_fat_pct.display_name() == "body fat pct"
        assert DailyMeasure.resting_hr.display_name() == "resting hr"
        assert DailyMeasure.sleep_duration.display_name() == "sleep duration"
        assert DailyMeasure.menstrual_cycle_day.display_name() == "menstrual cycle day"

    def test_missing_handles_unknown_values(self):
        """_missing_ should create a pseudo-member for unknown values."""
        unknown = DailyMeasure("some_future_measure")
        assert unknown.value == "some_future_measure"
        assert unknown.name == "some_future_measure"
        # Should be cached for subsequent lookups
        assert DailyMeasure("some_future_measure") is unknown

    def test_enum_to_string(self):
        """Enum .value should produce the string needed for URL paths."""
        assert DailyMeasure.body_mass.value == "body_mass"
        assert DailyMeasure.hrv.value == "hrv"
        assert DailyMeasure.sleep_altitude.value == "sleep_altitude"


# ---------------------------------------------------------------------------
# DataFrame conversion tests
# ---------------------------------------------------------------------------


class TestDataFrameConversion:
    def test_dataframe_has_date_column(self, sample_dailies: list[DailyResponse]):
        """Every frame is column-shaped: date is a column, not the index."""
        df = _frames.models_to_pandas(sample_dailies, DailyResponse)

        assert isinstance(df.index, pd.RangeIndex)
        assert len(df) == 3
        assert list(df.columns) == DAILY_COLUMNS

    def test_dataframe_values(self, sample_dailies: list[DailyResponse]):
        """DataFrame should contain correct values including None."""
        df = _frames.models_to_pandas(sample_dailies, DailyResponse).set_index("date")

        assert df.loc[date(2026, 4, 1), "value"] == 75.2
        assert df.loc[date(2026, 4, 1), "status"] == DailyStatus.stored
        # pandas keeps enum members, as for every enum column; Polars and Arrow hold strings.
        assert df.loc[date(2026, 4, 1), "writer"] is WriterKind.athlete
        assert pd.isna(df.loc[date(2026, 4, 3), "value"])
        assert df.loc[date(2026, 4, 3), "status"] == DailyStatus.missing
        assert df.loc[date(2026, 4, 3), "writer"] is None
        assert df.loc[date(2026, 4, 3), "platform"] is None

    def test_empty_dataframe(self):
        """Empty dailies list should produce valid empty DataFrame with the same columns."""
        df = _frames.models_to_pandas([], DailyResponse)

        assert len(df) == 0
        assert list(df.columns) == DAILY_COLUMNS


# ---------------------------------------------------------------------------
# Schema round-trip tests
# ---------------------------------------------------------------------------


class TestSchemaRoundTrip:
    def test_daily_response_round_trip(self):
        """A stored DailyResponse should survive serialize -> deserialize."""
        daily = DailyResponse(
            date=date(2026, 4, 1),
            value=75.2,
            status="stored",
            writer="application",
            application_id="app_123",
            platform="garmin_connect",
        )
        restored = DailyResponse.model_validate(daily.model_dump())

        assert restored.date == date(2026, 4, 1)
        assert restored.value == 75.2
        assert restored.status == DailyStatus.stored
        assert restored.writer is WriterKind.application
        assert (restored.application_id, restored.platform) == ("app_123", "garmin_connect")

    def test_daily_response_null_value(self):
        """A missing day (null value, no writer) should round-trip cleanly."""
        daily = DailyResponse(date=date(2026, 4, 1), value=None, status="missing")
        restored = DailyResponse.model_validate(daily.model_dump())

        assert restored.value is None
        assert restored.status == DailyStatus.missing
        assert restored.writer is None

    def test_an_unstored_day_has_no_writer_from_api_json(self):
        """Estimated and missing days have no writer: the three fields are null, not absent."""
        for status in ("estimated", "missing"):
            payload = {
                "date": "2026-04-02",
                "value": None,
                "status": status,
                "writer": None,
                "application_id": None,
                "platform": None,
            }
            restored = DailyResponse.model_validate(payload)
            assert (restored.writer, restored.application_id, restored.platform) == (None,) * 3
            assert restored.status is DailyStatus(status)


# One row per model that carries a writer, without the writer fields.
RECORDS = pytest.mark.parametrize(
    "model, row",
    [
        (DailyResponse, {"date": "2026-03-10", "value": 82.5, "status": "stored"}),
        (
            SourceResponse,
            {
                "id": "src_1",
                "type": "fit",
                "filename": "ride.fit",
                "status": "processing",
                "activity_ids": [],
                "created_at": "2026-03-10T09:00:00Z",
            },
        ),
        (
            MarkerRowResponse,
            {
                "id": "m1",
                "sport": "cycling",
                "marker": "second_threshold",
                "metric": "power",
                "value": 280.0,
                "date": "2026-03-10",
                "provenance": "declared",
                "pinned": False,
                "activity_id": None,
            },
        ),
        (
            MaxEffortRowResponse,
            {
                "id": "e1",
                "sport": "cycling",
                "metric": "power",
                "duration": 300,
                "distance": None,
                "value": 350.0,
                "date": "2026-03-10",
                "provenance": "measured",
                "title": None,
                "activity_id": None,
            },
        ),
    ],
    ids=["daily", "source", "marker", "max_effort"],
)


@RECORDS
@pytest.mark.parametrize(
    "writer, application_id, platform",
    [
        ("athlete", None, None),  # typed in, or uploaded by the athlete
        ("sweatstack", None, "garmin_connect"),  # SweatStack's own sync
        ("application", "app_123", "garmin_connect"),  # an app relaying a platform
        ("application", "app_123", None),  # an app's own value
        ("athlete", None, "strava"),  # an export imported through the SDK's sign-in
    ],
)
def test_every_record_says_who_wrote_it_and_where_it_came_from(
    model, row, writer, application_id, platform
):
    record = model.model_validate(
        {**row, "writer": writer, "application_id": application_id, "platform": platform}
    )
    assert record.writer is WriterKind(writer)
    assert (record.application_id, record.platform) == (application_id, platform)


@RECORDS
def test_writer_is_a_closed_set(model, row):
    # The server documents WriterKind as closed: a fourth writer is a breaking release, so it
    # must fail loudly here rather than parse as a pseudo-member (AGENTS.md, open enums).
    with pytest.raises(ValidationError):
        model.model_validate({**row, "writer": "a_writer_added_later"})


@RECORDS
def test_platform_is_an_open_set(model, row):
    record = model.model_validate({**row, "writer": "application", "platform": "a_new_platform"})
    assert record.platform == "a_new_platform"
