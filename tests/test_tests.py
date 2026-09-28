"""Tests for the Tests (fitness assessments) functionality.

Tests schema round-trips, DataFrame conversion, and enum handling
without hitting the API.
"""

from datetime import datetime, timezone

import pandas as pd
import pytest

from sweatstack import Marker, Sport, TestResults, TestSummary
from sweatstack.client import Client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_results() -> TestResults:
    return TestResults(
        first_threshold=Marker(power=200, heart_rate=140, lactate=1.5),
        second_threshold=Marker(power=280, heart_rate=170, lactate=4.0),
        vo2max=4500.0,
        critical_power=260,
        w_prime=20.0,
    )


@pytest.fixture
def sample_test_summary(sample_results: TestResults) -> TestSummary:
    return TestSummary(
        id="test_001",
        title="Lab test Q1",
        sport=Sport("cycling"),
        start=datetime(2026, 3, 15, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 3, 15, 11, 0, tzinfo=timezone.utc),
        results=sample_results,
        tags=["lab", "cycling"],
        start_local=datetime(2026, 3, 15, 10, 0),
        end_local=datetime(2026, 3, 15, 12, 0),
    )


# ---------------------------------------------------------------------------
# Schema round-trip tests
# ---------------------------------------------------------------------------


class TestSchemaRoundTrip:
    def test_test_results_round_trip(self, sample_results: TestResults):
        """TestResults should survive serialize -> deserialize."""
        dumped = sample_results.model_dump()
        restored = TestResults.model_validate(dumped)

        assert restored.first_threshold.power == 200
        assert restored.first_threshold.heart_rate == 140
        assert restored.first_threshold.lactate == 1.5
        assert restored.second_threshold.power == 280
        assert restored.vo2max == 4500.0
        assert restored.critical_power == 260
        assert restored.w_prime == 20.0

    def test_test_summary_round_trip(self, sample_test_summary: TestSummary):
        """TestSummary with nested results should survive serialize -> deserialize."""
        dumped = sample_test_summary.model_dump()
        restored = TestSummary.model_validate(dumped)

        assert restored.id == "test_001"
        assert restored.title == "Lab test Q1"
        assert restored.sport == Sport("cycling")
        assert restored.results.vo2max == 4500.0
        assert restored.results.first_threshold.power == 200
        assert restored.tags == ["lab", "cycling"]

    def test_test_results_all_none(self):
        """TestResults with no fields set should round-trip cleanly."""
        results = TestResults()
        dumped = results.model_dump()
        restored = TestResults.model_validate(dumped)

        assert all(v is None for v in dumped.values())
        assert restored.vo2max is None
        assert restored.first_threshold is None

    def test_marker_partial(self):
        """Marker with only some fields set should round-trip cleanly."""
        marker = Marker(power=300)
        dumped = marker.model_dump()
        restored = Marker.model_validate(dumped)

        assert restored.power == 300
        assert restored.speed is None
        assert restored.heart_rate is None
        assert restored.lactate is None
        assert restored.vo2 is None


# ---------------------------------------------------------------------------
# DataFrame conversion tests
# ---------------------------------------------------------------------------


class TestDataFrameConversion:
    def test_results_normalization(self, sample_test_summary: TestSummary):
        """Results column should be normalized into flat columns."""
        client = Client.__new__(Client)
        client.streamlit_compatible = False

        tests = [sample_test_summary]
        df = pd.DataFrame([test.model_dump() for test in tests])
        df = client._normalize_dataframe_column(df, "results")

        # Nested marker fields should be flattened
        assert "results.first_threshold.power" in df.columns
        assert "results.first_threshold.heart_rate" in df.columns
        assert "results.vo2max" in df.columns
        assert "results.critical_power" in df.columns

        # Original column should be removed
        assert "results" not in df.columns

        # Values should be correct
        assert df["results.first_threshold.power"].iloc[0] == 200
        assert df["results.vo2max"].iloc[0] == 4500.0

    def test_empty_dataframe(self):
        """Empty test list should produce valid empty DataFrame."""
        client = Client.__new__(Client)
        client.streamlit_compatible = False

        df = client._create_empty_dataframe_from_model(
            TestSummary,
            normalize_columns=["results"]
        )

        assert len(df) == 0
        assert isinstance(df, pd.DataFrame)

    def test_multiple_tests_dataframe(self, sample_results: TestResults):
        """Multiple tests should produce correct DataFrame."""
        client = Client.__new__(Client)
        client.streamlit_compatible = False

        tests = [
            TestSummary(
                id=f"test_{i}",
                sport=Sport("cycling"),
                start=datetime(2026, 1, i + 1, 9, 0, tzinfo=timezone.utc),
                end=datetime(2026, 1, i + 1, 11, 0, tzinfo=timezone.utc),
                results=sample_results if i == 0 else None,
                tags=[],
                start_local=datetime(2026, 1, i + 1, 10, 0),
                end_local=datetime(2026, 1, i + 1, 12, 0),
            )
            for i in range(3)
        ]

        df = pd.DataFrame([test.model_dump() for test in tests])
        df = client._normalize_dataframe_column(df, "results")

        assert len(df) == 3
        assert df["results.vo2max"].iloc[0] == 4500.0
        assert pd.isna(df["results.vo2max"].iloc[1])


# ---------------------------------------------------------------------------
# Enum handling tests
# ---------------------------------------------------------------------------


class TestEnumHandling:
    def test_enums_to_strings_with_sport(self):
        """Sport enums should convert to strings."""
        client = Client.__new__(Client)
        result = client._enums_to_strings([Sport("cycling"), Sport("running")])
        assert result == ["cycling", "running"]

    def test_enums_to_strings_with_strings(self):
        """String values should pass through unchanged."""
        client = Client.__new__(Client)
        result = client._enums_to_strings(["cycling", "running"])
        assert result == ["cycling", "running"]

    def test_enums_to_strings_mixed(self):
        """Mix of enums and strings should work."""
        client = Client.__new__(Client)
        result = client._enums_to_strings([Sport("cycling"), "running"])
        assert result == ["cycling", "running"]
