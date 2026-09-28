"""Frame construction for every ``output=`` backend.

Two kinds of input, one contract:

- parquet bytes from the time-series endpoints (activity data, mean-max, AWD,
  longitudinal): ``parquet_to_<backend>()``
- lists of Pydantic models from the list endpoints (activities, traces, tests,
  dailies): ``models_to_<backend>()``

Every backend returns plain columns; no frame carries an index. The pandas
functions keep the historical dtype policy (float64 upcast, ns precision) via
``utils.convert_to_standard_dtypes`` because Int16 and float16 are real footguns
in pandas. Other backends keep the compact wire dtypes.

Frame libraries are optional extras. Every import of pandas, pyarrow or polars
happens inside the function that needs it, through :func:`require`, so the base
package imports without any of them (enforced by CI's bare-install job).
"""

from __future__ import annotations

from importlib import import_module
from io import BytesIO
from typing import TYPE_CHECKING, Any, Literal, Sequence

from pydantic import BaseModel

if TYPE_CHECKING:
    import pandas as pd


Output = Literal["models", "pandas", "polars", "arrow", "bytes"]

PARQUET_OUTPUTS: frozenset[str] = frozenset({"pandas", "polars", "arrow", "bytes"})
"""Valid ``output`` values for endpoints that return parquet."""

LIST_OUTPUTS: frozenset[str] = frozenset({"models", "pandas", "polars"})
"""Valid ``output`` values for endpoints that return a list of records."""

# Which install extra provides the library behind each backend.
_EXTRA_FOR_MODULE = {"pandas": "pandas", "pyarrow": "pandas", "polars": "polars"}


def require(module: str) -> Any:
    """Import an optional frame library or raise an actionable ``ImportError``."""
    try:
        return import_module(module)
    except ImportError as exc:
        extra = _EXTRA_FOR_MODULE[module]
        raise ImportError(
            f"'{module}' is required for this output but is not installed. "
            f'Install it with: uv add "sweatstack[{extra}]"'
        ) from exc


# ---------------------------------------------------------------------------
# Parquet responses
# ---------------------------------------------------------------------------

def parquet_to_pandas(content: bytes) -> pd.DataFrame:
    """Parquet bytes to a pandas DataFrame with standard dtypes."""
    pd = require("pandas")
    from .utils import convert_to_standard_dtypes

    return convert_to_standard_dtypes(pd.read_parquet(BytesIO(content)))


# ---------------------------------------------------------------------------
# Lists of models
# ---------------------------------------------------------------------------

def models_to_pandas(
    models: Sequence[BaseModel],
    model: type[BaseModel],
    *,
    flatten: Sequence[str] = (),
) -> pd.DataFrame:
    """A list of models to a flat pandas DataFrame.

    Nested fields named in ``flatten`` are expanded into dotted columns
    (``summary.power.mean``) via ``pd.json_normalize``. An empty list yields an
    empty frame whose columns are the model's fields minus the flattened ones,
    so downstream code sees stable column names either way.
    """
    pd = require("pandas")
    from .utils import convert_to_standard_dtypes

    if not models:
        columns = [name for name in model.model_fields if name not in flatten]
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame([m.model_dump() for m in models])
    for column in flatten:
        if column in df.columns:
            df = _flatten_column(df, column)
    return convert_to_standard_dtypes(df)


def _flatten_column(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Replace one nested column with its ``json_normalize``d, dot-prefixed columns."""
    pd = require("pandas")

    normalized = pd.json_normalize(_records_for_normalize(df, column))
    normalized = normalized.add_prefix(f"{column}.")
    normalized.index = df.index
    if column == "activity":
        # A trace's activity carries its own laps/traces; those explode into
        # hundreds of columns and are never what a trace frame is for.
        normalized = normalized.drop(["activity.traces", "activity.laps"], axis=1, errors="ignore")
    return pd.concat([df.drop(column, axis=1), normalized], axis=1)


def _records_for_normalize(df: pd.DataFrame, column: str) -> list:
    """``pd.json_normalize`` wants a list of records; ``laps``/``traces`` are
    lists of lists, so each row's list is turned into an index-keyed dict."""
    values = df[column].tolist()
    if column in ("laps", "traces"):
        return [
            {i: item for i, item in enumerate(sublist)} if sublist else {}
            for sublist in values
        ]
    return values
