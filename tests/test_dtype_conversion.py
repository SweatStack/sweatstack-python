"""Tests for dtype conversion functionality.

The SweatStack API returns parquet files with optimized dtypes (Int16, float16, etc.)
for bandwidth efficiency. The client converts these to standard dtypes (float64,
datetime64[ns]) for ease of use. These tests verify the conversion is correct,
idempotent, and handles edge cases properly.
"""

import math

import numpy as np
import pandas as pd
import pytest

from sweatstack.utils import convert_to_standard_dtypes


def _pyarrow_available() -> bool:
    """Check if PyArrow is available."""
    try:
        import pyarrow  # noqa: F401
        return True
    except ImportError:
        return False


class TestBasicConversion:
    """Test conversion of optimized dtypes to standard dtypes."""

    def test_integer_types_to_float64(self):
        """All integer types should convert to float64."""
        df = pd.DataFrame({
            "int8": pd.array([1, 2, 3], dtype="Int8"),
            "int16": pd.array([100, 200, 300], dtype="Int16"),
            "int32": pd.array([1000, 2000, 3000], dtype="int32"),
            "int64": pd.array([10**10, 2 * 10**10, 3 * 10**10], dtype="int64"),
        })

        result = convert_to_standard_dtypes(df)

        for col in result.columns:
            assert result[col].dtype == np.float64, f"{col} should be float64"

    def test_float_types_to_float64(self):
        """Float16 and float32 should convert to float64."""
        df = pd.DataFrame({
            "float16": pd.array([1.5, 2.5, 3.5], dtype="float16"),
            "float32": pd.array([1.123, 2.234, 3.345], dtype="float32"),
        })

        result = convert_to_standard_dtypes(df)

        assert result["float16"].dtype == np.float64
        assert result["float32"].dtype == np.float64

    def test_float64_unchanged(self):
        """Float64 should remain float64 (no unnecessary conversion)."""
        df = pd.DataFrame({
            "already_float64": pd.array([1.5, 2.5, 3.5], dtype="float64"),
        })

        result = convert_to_standard_dtypes(df)

        assert result["already_float64"].dtype == np.float64

    def test_timedelta_to_nanoseconds(self):
        """Timedelta columns should convert to nanosecond precision."""
        df = pd.DataFrame({
            "duration": pd.to_timedelta([1, 2, 3], unit="s").astype("timedelta64[s]"),
        })

        result = convert_to_standard_dtypes(df)

        assert result["duration"].dtype == np.dtype("timedelta64[ns]")
        assert result["duration"].dt.unit == "ns"

    def test_datetime_to_nanoseconds(self):
        """Datetime columns should convert to nanosecond precision."""
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(["2024-01-01", "2024-01-02"]).as_unit("s"),
        })

        result = convert_to_standard_dtypes(df)

        assert result["timestamp"].dt.unit == "ns"

    def test_datetime_preserves_timezone(self):
        """Timezone should be preserved during conversion."""
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(
                ["2024-01-01 10:00", "2024-01-02 11:00"]
            ).tz_localize("UTC").as_unit("s"),
        })

        result = convert_to_standard_dtypes(df)

        assert result["timestamp"].dt.tz is not None
        assert str(result["timestamp"].dt.tz) == "UTC"
        assert result["timestamp"].dt.unit == "ns"


class TestIndexConversion:
    """Test conversion of various index types."""

    def test_datetime_index_conversion(self):
        """DatetimeIndex should convert to nanosecond precision."""
        df = pd.DataFrame(
            {"value": [1, 2, 3]},
            index=pd.DatetimeIndex(
                ["2024-01-01", "2024-01-02", "2024-01-03"],
                tz="UTC",
            ).as_unit("s"),
        )

        result = convert_to_standard_dtypes(df)

        assert isinstance(result.index, pd.DatetimeIndex)
        assert result.index.unit == "ns"
        assert result.index.tz is not None

    def test_datetime_index_name_preserved(self):
        """Index name should be preserved during conversion."""
        df = pd.DataFrame(
            {"value": [1, 2]},
            index=pd.DatetimeIndex(
                ["2024-01-01", "2024-01-02"],
                tz="UTC",
                name="timestamp",
            ).as_unit("s"),
        )

        result = convert_to_standard_dtypes(df)

        assert result.index.name == "timestamp"

    def test_timedelta_index_conversion(self):
        """TimedeltaIndex should convert to nanosecond precision."""
        index = pd.to_timedelta([1, 5, 60], unit="s").as_unit("s")
        index.name = "duration"
        df = pd.DataFrame({"power": [400, 350, 300]}, index=index)

        result = convert_to_standard_dtypes(df)

        assert isinstance(result.index, pd.TimedeltaIndex)
        assert result.index.unit == "ns"
        assert result.index.name == "duration"

    def test_multiindex_with_datetime_level(self):
        """MultiIndex with DatetimeIndex level should be converted."""
        dates = pd.DatetimeIndex(
            ["2024-01-01", "2024-01-01", "2024-01-02"],
            tz="UTC",
        ).as_unit("s")
        activities = ["abc", "abc", "xyz"]

        df = pd.DataFrame(
            {"power": [100, 200, 150]},
            index=pd.MultiIndex.from_arrays(
                [dates, activities],
                names=["timestamp", "activity_id"],
            ),
        )

        result = convert_to_standard_dtypes(df)

        assert isinstance(result.index, pd.MultiIndex)
        assert result.index.names == ["timestamp", "activity_id"]

        datetime_level = result.index.get_level_values("timestamp")
        assert datetime_level.unit == "ns"

    def test_regular_index_unchanged(self):
        """Regular integer/range index should not be affected."""
        df = pd.DataFrame({"value": [1, 2, 3]})

        result = convert_to_standard_dtypes(df)

        assert list(result.index) == [0, 1, 2]


class TestNullableAndSpecialValues:
    """Test handling of NA, NaN, infinity, and other special values."""

    def test_nullable_integer_na_becomes_nan(self):
        """Nullable integer NA should become float NaN."""
        df = pd.DataFrame({
            "power": pd.array([100, pd.NA, 200], dtype="Int16"),
        })

        result = convert_to_standard_dtypes(df)

        assert result["power"].dtype == np.float64
        assert result["power"].iloc[0] == 100.0
        assert np.isnan(result["power"].iloc[1])
        assert result["power"].iloc[2] == 200.0

    def test_float_nan_preserved(self):
        """NaN values in float columns should be preserved."""
        df = pd.DataFrame({
            "speed": pd.array([5.0, np.nan, 10.0], dtype="float16"),
        })

        result = convert_to_standard_dtypes(df)

        assert result["speed"].iloc[0] == 5.0
        assert np.isnan(result["speed"].iloc[1])
        assert result["speed"].iloc[2] == 10.0

    def test_infinity_preserved(self):
        """Infinity values should be preserved."""
        df = pd.DataFrame({
            "value": pd.array([1.0, float("inf"), float("-inf")], dtype="float32"),
        })

        result = convert_to_standard_dtypes(df)

        assert result["value"].iloc[0] == 1.0
        assert result["value"].iloc[1] == float("inf")
        assert result["value"].iloc[2] == float("-inf")


class TestUnchangedTypes:
    """Test that certain types are intentionally not converted."""

    def test_category_unchanged(self):
        """Category columns should not be converted."""
        df = pd.DataFrame({
            "sport": pd.Categorical(["running", "cycling", "running"]),
            "activity_id": pd.Categorical(["abc123", "xyz789", "abc123"]),
        })

        result = convert_to_standard_dtypes(df)

        assert result["sport"].dtype.name == "category"
        assert result["activity_id"].dtype.name == "category"

    def test_object_unchanged(self):
        """Object columns should not be converted."""
        df = pd.DataFrame({
            "notes": ["good workout", "easy day", None],
        })

        result = convert_to_standard_dtypes(df)

        assert result["notes"].dtype == np.object_

    def test_bool_unchanged(self):
        """Boolean columns should not be converted."""
        df = pd.DataFrame({
            "is_indoor": [True, False, True],
        })

        result = convert_to_standard_dtypes(df)

        assert result["is_indoor"].dtype == np.bool_

    def test_string_dtype_unchanged(self):
        """String dtype columns should not be converted."""
        df = pd.DataFrame({
            "name": pd.array(["Alice", "Bob"], dtype="string"),
        })

        result = convert_to_standard_dtypes(df)

        assert result["name"].dtype == "string"


class TestIdempotencyAndBackwardsCompatibility:
    """Test that conversion is safe to call multiple times and on standard dtypes."""

    def test_idempotent_conversion(self):
        """Calling conversion twice should produce identical results."""
        df = pd.DataFrame({
            "power": pd.array([100, 200, pd.NA], dtype="Int16"),
            "speed": pd.array([5.0, 10.0, np.nan], dtype="float16"),
            "duration": pd.to_timedelta([1, 2, 3], unit="s").astype("timedelta64[s]"),
        }, index=pd.DatetimeIndex(
            ["2024-01-01", "2024-01-02", "2024-01-03"],
            tz="UTC",
        ).as_unit("s"))

        result1 = convert_to_standard_dtypes(df)
        result2 = convert_to_standard_dtypes(result1)

        pd.testing.assert_frame_equal(result1, result2)

    def test_already_standard_dtypes(self):
        """Conversion on already-standard dtypes should work correctly."""
        df = pd.DataFrame({
            "power": pd.array([100.0, 200.0, np.nan], dtype="float64"),
            "speed": pd.array([5.0, 10.0, np.nan], dtype="float64"),
            "duration": pd.to_timedelta([1, 2, 3], unit="s").astype("timedelta64[ns]"),
        }, index=pd.DatetimeIndex(
            ["2024-01-01", "2024-01-02", "2024-01-03"],
            tz="UTC",
        ))

        result = convert_to_standard_dtypes(df)

        assert result["power"].dtype == np.float64
        assert result["speed"].dtype == np.float64
        assert result["duration"].dtype == np.dtype("timedelta64[ns]")
        assert result.index.unit == "ns"

    def test_original_dataframe_unchanged(self):
        """Original DataFrame should not be modified."""
        df = pd.DataFrame({
            "power": pd.array([100, 200], dtype="Int16"),
            "speed": pd.array([5.0, 10.0], dtype="float16"),
        })

        original_power_dtype = df["power"].dtype
        original_speed_dtype = df["speed"].dtype

        _ = convert_to_standard_dtypes(df)

        assert df["power"].dtype == original_power_dtype
        assert df["speed"].dtype == original_speed_dtype


class TestRobustness:
    """Test handling of unknown columns and edge cases."""

    def test_unknown_columns_converted_by_dtype(self):
        """New/unknown columns should be converted based on dtype, not name."""
        df = pd.DataFrame({
            # Simulate future API adding new metrics
            "vertical_oscillation": pd.array([8.5, 9.2], dtype="float16"),
            "ground_contact_time": pd.array([250, 245], dtype="Int16"),
            "some_new_metric": pd.array([0.48, 0.52], dtype="float32"),
        })

        result = convert_to_standard_dtypes(df)

        for col in result.columns:
            assert result[col].dtype == np.float64

    def test_empty_dataframe(self):
        """Empty DataFrame should be handled correctly."""
        df = pd.DataFrame({
            "power": pd.array([], dtype="Int16"),
            "speed": pd.array([], dtype="float16"),
        })

        result = convert_to_standard_dtypes(df)

        assert len(result) == 0
        assert result["power"].dtype == np.float64
        assert result["speed"].dtype == np.float64

    def test_single_row_dataframe(self):
        """Single-row DataFrame should be handled correctly."""
        df = pd.DataFrame({
            "power": pd.array([250], dtype="Int16"),
        })

        result = convert_to_standard_dtypes(df)

        assert len(result) == 1
        assert result["power"].dtype == np.float64
        assert result["power"].iloc[0] == 250.0

    def test_no_numeric_columns(self):
        """DataFrame with only non-numeric columns should work."""
        df = pd.DataFrame({
            "activity_id": pd.Categorical(["abc", "xyz"]),
            "sport": pd.Categorical(["running", "cycling"]),
            "notes": ["good", "great"],
        })

        result = convert_to_standard_dtypes(df)

        assert result["activity_id"].dtype.name == "category"
        assert result["sport"].dtype.name == "category"
        assert result["notes"].dtype == np.object_

    def test_mixed_dtypes(self):
        """Mix of standard and optimized dtypes should be handled."""
        df = pd.DataFrame({
            # Already standard
            "power": pd.array([100.0, 200.0], dtype="float64"),
            "bool_col": pd.array([True, False], dtype="bool"),

            # Needs conversion
            "speed": pd.array([5.0, 10.0], dtype="float16"),
            "hr": pd.array([120, 150], dtype="Int16"),
        })

        result = convert_to_standard_dtypes(df)

        assert result["power"].dtype == np.float64
        assert result["bool_col"].dtype == np.bool_
        assert result["speed"].dtype == np.float64
        assert result["hr"].dtype == np.float64


class TestValuePreservation:
    """Test that values are preserved accurately during conversion."""

    def test_integer_values_preserved(self):
        """Integer values should be exactly preserved as float."""
        df = pd.DataFrame({
            "power": pd.array([0, 100, 2000, 32767], dtype="Int16"),
        })

        result = convert_to_standard_dtypes(df)

        assert result["power"].iloc[0] == 0.0
        assert result["power"].iloc[1] == 100.0
        assert result["power"].iloc[2] == 2000.0
        assert result["power"].iloc[3] == 32767.0

    def test_float16_precision_improved(self):
        """Float16 values should gain precision in float64."""
        # float16 has ~3 decimal digits, this tests that conversion works
        df = pd.DataFrame({
            "latitude": pd.array([52.123, -33.456], dtype="float16"),
        })

        result = convert_to_standard_dtypes(df)

        # After conversion, we should be able to represent more precision
        assert result["latitude"].dtype == np.float64
        # Original float16 value is approximate
        assert math.isclose(result["latitude"].iloc[0], 52.123, rel_tol=1e-2)

    def test_float32_values_preserved(self):
        """Float32 values should be preserved with full precision."""
        df = pd.DataFrame({
            "distance": pd.array([0.0, 1234.5678, 100000.125], dtype="float32"),
        })

        result = convert_to_standard_dtypes(df)

        assert math.isclose(result["distance"].iloc[1], 1234.5678, rel_tol=1e-6)

    def test_large_integers_preserved(self):
        """Large integers should be preserved (within float64 precision)."""
        df = pd.DataFrame({
            "big_number": pd.array([10**12, 2 * 10**12], dtype="int64"),
        })

        result = convert_to_standard_dtypes(df)

        assert result["big_number"].iloc[0] == 10**12
        assert result["big_number"].iloc[1] == 2 * 10**12


class TestRealisticActivityData:
    """Test with data structures that mirror real SweatStack API responses."""

    def test_activity_timeseries_data(self):
        """Test conversion of typical activity time-series data."""
        # Simulates what get_activity_data() returns from API
        df = pd.DataFrame({
            "power": pd.array([150, 200, pd.NA, 180], dtype="Int16"),
            "heart_rate": pd.array([120, 140, 150, 145], dtype="Int16"),
            "cadence": pd.array([85, 90, 88, pd.NA], dtype="Int16"),
            "speed": pd.array([8.5, 9.2, 9.0, 8.8], dtype="float16"),
            "altitude": pd.array([100.0, 102.5, 105.0, 103.0], dtype="float16"),
            "distance": pd.array([0.0, 100.0, 200.0, 300.0], dtype="float32"),
            "latitude": pd.array([52.123, 52.124, 52.125, 52.126], dtype="float32"),
            "longitude": pd.array([4.567, 4.568, 4.569, 4.570], dtype="float32"),
            "lap": pd.array([0, 0, 1, 1], dtype="Int8"),
            "activity_id": pd.Categorical(["abc123"] * 4),
            "sport": pd.Categorical(["cycling"] * 4),
        }, index=pd.DatetimeIndex(
            ["2024-01-01 10:00:00", "2024-01-01 10:00:01",
             "2024-01-01 10:00:02", "2024-01-01 10:00:03"],
            tz="UTC",
        ).as_unit("s"))

        result = convert_to_standard_dtypes(df)

        # All numeric columns should be float64
        for col in ["power", "heart_rate", "cadence", "speed",
                    "altitude", "distance", "latitude", "longitude", "lap"]:
            assert result[col].dtype == np.float64, f"{col} should be float64"

        # Category columns unchanged
        assert result["activity_id"].dtype.name == "category"
        assert result["sport"].dtype.name == "category"

        # Index converted to ns precision
        assert result.index.unit == "ns"
        assert result.index.tz is not None

        # NA values converted to NaN
        assert np.isnan(result["power"].iloc[2])
        assert np.isnan(result["cadence"].iloc[3])

        # Values preserved
        assert result["power"].iloc[0] == 150.0
        assert result["distance"].iloc[3] == 300.0

    def test_mean_max_data(self):
        """Test conversion of mean-max curve data."""
        # Simulates what get_activity_mean_max() returns
        index = pd.to_timedelta([1, 5, 60, 300, 1200], unit="s").as_unit("s")
        index.name = "duration"
        df = pd.DataFrame({
            "power": pd.array([800, 600, 400, 300, 250], dtype="Int16"),
        }, index=index)

        result = convert_to_standard_dtypes(df)

        assert result["power"].dtype == np.float64
        assert isinstance(result.index, pd.TimedeltaIndex)
        assert result.index.unit == "ns"
        assert result.index.name == "duration"

    def test_cumsum_works_after_conversion(self):
        """Verify cumsum works without overflow after conversion."""
        # This would overflow with Int16 (max 32,767)
        df = pd.DataFrame({
            "power": pd.array([1000] * 100, dtype="Int16"),
        })

        result = convert_to_standard_dtypes(df)
        cumulative = result["power"].cumsum()

        # Should be 100,000, which would overflow Int16
        assert cumulative.iloc[-1] == 100_000.0


@pytest.mark.skipif(
    not _pyarrow_available(),
    reason="PyArrow not installed"
)
class TestPyArrowBackedDtypes:
    """Test handling of PyArrow-backed dtypes (pandas 2.0+)."""

    def test_pyarrow_int_converted(self):
        """PyArrow integer types should convert to float64."""
        df = pd.DataFrame({
            "value": pd.array([1, 2, 3], dtype="int16[pyarrow]"),
        })

        result = convert_to_standard_dtypes(df)

        assert result["value"].dtype == np.float64

    def test_pyarrow_float_converted(self):
        """PyArrow float types should convert to float64."""
        df = pd.DataFrame({
            "value": pd.array([1.5, 2.5, 3.5], dtype="float[pyarrow]"),
        })

        result = convert_to_standard_dtypes(df)

        assert result["value"].dtype == np.float64
