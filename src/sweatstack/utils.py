"""Dataframe and JWT helpers.

pandas and numpy are optional extras (``sweatstack[pandas]``), so they are
imported inside the functions that need them; importing this module must not
pull them in.
"""

from __future__ import annotations

import base64
import json
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


def convert_to_standard_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """Convert optimized dtypes to standard dtypes for ease of use.

    The SweatStack API returns parquet files with space-optimized dtypes (Int16,
    float16, datetime64[s], etc.) to reduce bandwidth. While efficient for transfer,
    these types can cause friction in analysis workflows:

    - Int16 overflows on cumulative operations (cumsum fails at 32,767)
    - float16 cannot be used as a pandas index
    - float16 has limited precision (~3 decimal digits)
    - Some numpy/scipy/sklearn functions expect float64

    This function converts all numeric columns to float64 and all datetime/timedelta
    columns to nanosecond precision, giving you DataFrames that "just work" with the
    entire Python data ecosystem.

    The function is:
    - **Idempotent**: Safe to call multiple times; no-op on already-standard dtypes
    - **Backwards compatible**: Works whether API returns optimized or standard dtypes
    - **Robust**: Handles any column via dtype detection, not column names

    Args:
        df: DataFrame with any dtypes

    Returns:
        DataFrame with standard dtypes (float64, datetime64[ns], timedelta64[ns])

    Example:
        >>> df = client.activities.data("abc123")
        >>> df["power"].dtype  # Already converted
        dtype('float64')
        >>> df["power"].cumsum()  # No overflow issues
    """
    import numpy as np
    import pandas as pd

    df = df.copy()

    for col in df.columns:
        dtype = df[col].dtype

        # Integer types (Int8, Int16, int32, etc.) → float64
        # Supports NaN and prevents overflow on cumulative operations
        if pd.api.types.is_integer_dtype(dtype):
            df[col] = df[col].astype(np.float64)

        # Float16/float32 → float64
        # Full precision, can be used as index, compatible with all libraries
        elif pd.api.types.is_float_dtype(dtype) and dtype != np.float64:
            df[col] = df[col].astype(np.float64)

        # Timedelta columns → nanosecond precision
        elif pd.api.types.is_timedelta64_dtype(dtype):
            if df[col].dt.unit != "ns":
                df[col] = df[col].astype("timedelta64[ns]")

        # Datetime columns → nanosecond precision (preserve timezone)
        elif pd.api.types.is_datetime64_any_dtype(dtype):
            if df[col].dt.unit != "ns":
                if df[col].dt.tz is not None:
                    df[col] = df[col].dt.as_unit("ns")
                else:
                    df[col] = df[col].astype("datetime64[ns]")

    # Handle DatetimeIndex
    if isinstance(df.index, pd.DatetimeIndex):
        if df.index.unit != "ns":
            df.index = df.index.as_unit("ns")

    # Handle TimedeltaIndex
    elif isinstance(df.index, pd.TimedeltaIndex):
        if df.index.unit != "ns":
            df.index = df.index.as_unit("ns")

    # Handle MultiIndex with datetime/timedelta levels
    elif isinstance(df.index, pd.MultiIndex):
        new_levels = list(df.index.levels)
        changed = False
        for i, level in enumerate(new_levels):
            if isinstance(level, (pd.DatetimeIndex, pd.TimedeltaIndex)):
                if level.unit != "ns":
                    new_levels[i] = level.as_unit("ns")
                    changed = True
        if changed:
            df.index = df.index.set_levels(new_levels)

    return df


def decode_jwt_body(jwt: str) -> dict:
    payload = jwt.split(".")[1]

    padding = len(payload) % 4
    if padding:
        payload += "=" * (4 - padding)

    decoded = base64.urlsafe_b64decode(payload)
    return json.loads(decoded)


def make_dataframe_streamlit_compatible(df: pd.DataFrame) -> pd.DataFrame:
    """
    Converts all columns containing enum values in a DataFrame to their respective string values.

    Args:
        df (pd.DataFrame): The DataFrame to process

    Returns:
        pd.DataFrame: A new DataFrame with enum values converted to strings
    """
    df_copy = None

    for column in df.columns:
        # Check if the column contains enum values
        if df[column].dtype == "object":
            # First check if it's a list column of enums
            if df[column].notna().any():
                first_value = df[column].dropna().iloc[0]

                # Handle list of enums
                if (
                    isinstance(first_value, list)
                    and first_value
                    and isinstance(first_value[0], Enum)
                ):
                    if df_copy is None:
                        df_copy = df.copy()
                    df_copy[column] = df_copy[column].apply(
                        lambda x: (
                            [item.value if isinstance(item, Enum) else item for item in x]
                            if isinstance(x, list)
                            else x
                        )
                    )
                # Handle single enum values
                elif isinstance(first_value, Enum):
                    if df_copy is None:
                        df_copy = df.copy()
                    df_copy[column] = df_copy[column].apply(
                        lambda x: x.value if isinstance(x, Enum) else x
                    )

    return df_copy if df_copy is not None else df
