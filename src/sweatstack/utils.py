import base64
import json
from enum import Enum

import pandas as pd

from .schemas import Sport


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
        if df[column].dtype == 'object':
            # First check if it's a list column of enums
            if df[column].notna().any():
                first_value = df[column].dropna().iloc[0]

                # Handle list of enums
                if isinstance(first_value, list) and first_value and isinstance(first_value[0], Enum):
                    if df_copy is None:
                        df_copy = df.copy()
                    df_copy[column] = df_copy[column].apply(
                        lambda x: [item.value if isinstance(item, Enum) else item for item in x] if isinstance(x, list) else x
                    )
                # Handle single enum values
                elif isinstance(first_value, Enum):
                    if df_copy is None:
                        df_copy = df.copy()
                    df_copy[column] = df_copy[column].apply(
                        lambda x: x.value if isinstance(x, Enum) else x
                    )

    return df_copy if df_copy is not None else df