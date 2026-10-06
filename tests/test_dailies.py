"""Tests for the Dailies (daily health metrics) functionality.

Tests DailyMeasure enum enhancements, DataFrame conversion, and enum
serialization without hitting the API.
"""

from datetime import date

import pandas as pd
import pytest

from sweatstack import DailyMeasure, DailyResponse, _frames
from sweatstack.openapi_schemas import DailySource, DailyStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_dailies() -> list[DailyResponse]:
    # status is read-time state; source (provenance) is set only when stored.
    return [
        DailyResponse(date=date(2026, 4, 1), value=75.2, status="stored", source="manual"),
        DailyResponse(date=date(2026, 4, 2), value=75.1, status="estimated", source=None),
        DailyResponse(date=date(2026, 4, 3), value=None, status="missing", source=None),
    ]


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
        assert list(df.columns) == ["date", "value", "status", "source"]

    def test_dataframe_values(self, sample_dailies: list[DailyResponse]):
        """DataFrame should contain correct values including None."""
        df = _frames.models_to_pandas(sample_dailies, DailyResponse).set_index("date")

        assert df.loc[date(2026, 4, 1), "value"] == 75.2
        assert df.loc[date(2026, 4, 1), "status"] == DailyStatus.stored
        assert df.loc[date(2026, 4, 1), "source"] == DailySource.manual
        assert pd.isna(df.loc[date(2026, 4, 3), "value"])
        assert df.loc[date(2026, 4, 3), "status"] == DailyStatus.missing
        assert df.loc[date(2026, 4, 3), "source"] is None

    def test_empty_dataframe(self):
        """Empty dailies list should produce valid empty DataFrame with the same columns."""
        df = _frames.models_to_pandas([], DailyResponse)

        assert len(df) == 0
        assert list(df.columns) == ["date", "value", "status", "source"]


# ---------------------------------------------------------------------------
# Schema round-trip tests
# ---------------------------------------------------------------------------


class TestSchemaRoundTrip:
    def test_daily_response_round_trip(self):
        """A stored DailyResponse should survive serialize -> deserialize."""
        daily = DailyResponse(date=date(2026, 4, 1), value=75.2, status="stored", source="manual")
        dumped = daily.model_dump()
        restored = DailyResponse.model_validate(dumped)

        assert restored.date == date(2026, 4, 1)
        assert restored.value == 75.2
        assert restored.status == DailyStatus.stored
        assert restored.source == DailySource.manual

    def test_daily_response_null_value(self):
        """A missing day (null value, null source) should round-trip cleanly."""
        daily = DailyResponse(date=date(2026, 4, 1), value=None, status="missing", source=None)
        dumped = daily.model_dump()
        restored = DailyResponse.model_validate(dumped)

        assert restored.value is None
        assert restored.status == DailyStatus.missing
        assert restored.source is None

    def test_daily_response_null_source_from_api_json(self):
        """Regression: estimated/missing days come back with source=null and no provenance.

        The generated model previously typed `source` as a required str, so this
        payload raised a ValidationError. source is now Optional[DailySource].
        """
        for status in ("estimated", "missing"):
            payload = {"date": "2026-04-02", "value": None, "status": status, "source": None}
            restored = DailyResponse.model_validate(payload)
            assert restored.source is None
            assert restored.status is DailyStatus(status)
