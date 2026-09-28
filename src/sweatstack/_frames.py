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

import json
import warnings
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
from importlib import import_module
from io import BytesIO
from typing import TYPE_CHECKING, Any, Literal, Sequence

from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema
from pydantic_core import to_jsonable_python

if TYPE_CHECKING:
    import pandas as pd
    import polars as pl


class FrameSchemaWarning(UserWarning):
    """A model field has a JSON Schema shape :func:`polars_schema` does not map.

    The field is stored as JSON text so nothing breaks, but the mapping table
    should gain a row (see ``tests/test_frames.py``, which turns this warning
    into a failure so schema regeneration cannot introduce one silently).
    """


Output = Literal["models", "pandas", "polars", "arrow", "bytes"]
"""Every container a collection can come back in."""

FrameOutput = Literal["pandas", "polars", "arrow", "bytes"]
"""The containers that can be configured as a default (``Client(output=...)``,
:func:`set_output`). ``"models"`` is never a default worth configuring: it is
already the default for list endpoints and impossible for parquet endpoints."""

ListOutput = Literal["models", "pandas", "polars"]
"""The containers a list endpoint can return."""

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
        extra = _EXTRA_FOR_MODULE[module.split(".")[0]]
        raise ImportError(
            f"'{module}' is required for this output but is not installed. "
            f'Install it with: uv add "sweatstack[{extra}]"'
        ) from exc


# ---------------------------------------------------------------------------
# Choosing the output
# ---------------------------------------------------------------------------

_default_output: str | None = None


def set_output(output: FrameOutput | None) -> None:
    """Set the default ``output`` for every method that returns a collection.

    Applies to the module-level singletons and to every :class:`Client` that
    does not set its own ``output``. A per-call ``output=`` always wins.
    A configured value that a method cannot produce (``"arrow"`` or ``"bytes"``
    on a list endpoint) is ignored for that method, which then uses its own
    default. Pass ``None`` to reset.

    Args:
        output: ``"pandas"``, ``"polars"``, ``"arrow"``, ``"bytes"`` or ``None``.

    Raises:
        ValueError: If ``output`` is not one of the frame outputs.
    """
    global _default_output
    _default_output = check_frame_output(output)


def check_frame_output(output: str | None) -> str | None:
    """Validate a configurable default; returns it unchanged."""
    if output is not None and output not in PARQUET_OUTPUTS:
        raise ValueError(
            f"output={output!r} cannot be a default; choose one of {_choices(PARQUET_OUTPUTS)}"
        )
    return output


def resolve_output(
    requested: str | None,
    configured: str | None,
    *,
    allowed: frozenset[str],
    default: str,
) -> str:
    """Pick the output for one call: per-call > client > module default > method default.

    A per-call value the method cannot produce is an error. A configured
    default the method cannot produce is skipped, not an error.
    """
    if requested is not None:
        if requested not in allowed:
            raise ValueError(
                f"output={requested!r} is not available here; choose one of {_choices(allowed)}"
            )
        return requested
    for candidate in (configured, _default_output):
        if candidate in allowed:
            return candidate
    return default


def _choices(allowed: frozenset[str]) -> str:
    return ", ".join(repr(choice) for choice in sorted(allowed))


# ---------------------------------------------------------------------------
# Parquet responses
#
# The server may write a pandas index (timestamp for time series, the metric
# value for mean-max curves, see server plan 020d). In parquet that is a normal
# column plus a metadata blob. Every backend here returns it as a leading
# column, so the shape is identical whether or not the server still writes the
# blob.
# ---------------------------------------------------------------------------

def parquet_to_pandas(content: bytes) -> pd.DataFrame:
    """Parquet bytes to a pandas DataFrame: columns only, standard dtypes."""
    pd = require("pandas")
    from .utils import convert_to_standard_dtypes

    df = pd.read_parquet(BytesIO(content))
    if not isinstance(df.index, pd.RangeIndex):
        df = df.reset_index()
    return convert_to_standard_dtypes(df)


def parquet_to_polars(content: bytes) -> pl.DataFrame:
    """Parquet bytes to a Polars DataFrame with the wire dtypes, except
    Float16 -> Float32 (Polars supports few operations on Float16)."""
    pl = require("polars")

    df = pl.read_parquet(BytesIO(content))
    float16 = getattr(pl, "Float16", None)  # older Polars already reads float16 as Float32
    if float16 is not None:
        df = df.cast({name: pl.Float32 for name, dtype in df.schema.items() if dtype == float16})
    metadata = pl.read_parquet_metadata(BytesIO(content))
    return df.select(_index_columns_first(df.columns, metadata.get("pandas")))


def parquet_to_arrow(content: bytes) -> Any:
    """Parquet bytes to a ``pyarrow.Table`` exactly as on the wire, minus the
    pandas index metadata (so ``to_pandas()`` also yields columns only)."""
    pq = require("pyarrow.parquet")

    table = pq.read_table(BytesIO(content))
    metadata = dict(table.schema.metadata or {})
    pandas_metadata = metadata.pop(b"pandas", None)
    table = table.select(_index_columns_first(table.column_names, pandas_metadata))
    return table.replace_schema_metadata(metadata or None)


def _index_columns_first(columns: Sequence[str], pandas_metadata: str | bytes | None) -> list[str]:
    """Column order with any former pandas index columns first, matching the
    order ``DataFrame.reset_index()`` produces on the pandas path."""
    if not pandas_metadata:
        return list(columns)
    index_columns = [
        name for name in json.loads(pandas_metadata).get("index_columns", [])
        if isinstance(name, str) and name in columns  # RangeIndex entries are dicts
    ]
    return index_columns + [name for name in columns if name not in index_columns]


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


# ---------------------------------------------------------------------------
# Lists of models -> Polars
#
# The schema comes from the model's JSON Schema, the values from the model
# instance. JSON Schema is a closed grammar and it is what openapi_schemas.py is
# generated from, so a regeneration cannot introduce a Python type this mapper
# has never seen without it also appearing below. Anything unmapped becomes
# JSON text with a FrameSchemaWarning.
#
# Never add a per-model special case here. If a model seems to need one, the
# grammar table in _polars_dtype is missing a row; add the row and its test.
# ---------------------------------------------------------------------------

def models_to_polars(models: Sequence[BaseModel], model: type[BaseModel]) -> pl.DataFrame:
    """A list of models to a Polars DataFrame with typed nested structs."""
    pl = require("polars")

    schema = polars_schema(model)
    if not models:
        return pl.DataFrame(schema=schema)
    rows = [
        {name: _plain_value(getattr(m, name), dtype) for name, dtype in schema.items()}
        for m in models
    ]
    return pl.from_dicts(rows, schema=schema)


class _JsonSchemaGenerator(GenerateJsonSchema):
    """Stock JSON Schema labels aware and naive datetimes alike (``date-time``).
    Emit ``naive-date-time`` for naive fields so ``start_local`` is not typed as UTC."""

    def datetime_schema(self, schema):
        json_schema = super().datetime_schema(schema)
        if schema.get("tz_constraint") == "naive":
            json_schema["format"] = "naive-date-time"
        return json_schema


@lru_cache(maxsize=None)
def polars_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Polars dtype per top-level field of ``model``, derived from its JSON Schema."""
    json_schema = model.model_json_schema(schema_generator=_JsonSchemaGenerator)
    definitions = json_schema.get("$defs", {})
    if "properties" in json_schema:
        root_name, root = model.__name__, json_schema
    else:  # a self-referencing model is emitted as a $ref into $defs
        root_name = _definition_name(json_schema["$ref"])
        root = definitions[root_name]
    return {
        name: _polars_dtype(node, definitions, f"{root_name}.{name}", (root_name,))
        for name, node in root["properties"].items()
    }


_DATETIME_FORMATS = frozenset({"date-time", "naive-date-time"})


def _definition_name(ref: str) -> str:
    return ref.rsplit("/", 1)[1]


def _polars_dtype(node: dict, definitions: dict, path: str, stack: tuple[str, ...]) -> Any:
    """Map one JSON Schema node to a Polars dtype. ``stack`` holds the model
    definitions currently being expanded, to cut recursive models short."""
    pl = require("polars")

    while "$ref" in node:
        name = _definition_name(node["$ref"])
        if name in stack:
            return pl.String  # recursive model: JSON text, Polars has no recursive dtype
        stack = (*stack, name)
        node = definitions[name]

    if "anyOf" in node:
        options = [option for option in node["anyOf"] if option.get("type") != "null"]
        if len(options) == 1:
            return _polars_dtype(options[0], definitions, path, stack)
        if options and all(option.get("type") in ("integer", "number") for option in options):
            return pl.Float64
        if options and all(option.get("format") in _DATETIME_FORMATS for option in options):
            return pl.Datetime("us", "UTC")  # aware | naive: naive values are taken as UTC
        return _fallback(path, node)

    if "enum" in node or "const" in node:
        return pl.String

    kind = node.get("type")
    if kind == "string":
        return {
            "date-time": pl.Datetime("us", "UTC"),
            "naive-date-time": pl.Datetime("us", None),
            "date": pl.Date,
            "duration": pl.Duration("us"),
        }.get(node.get("format", ""), pl.String)
    if kind == "integer":
        return pl.Int64
    if kind == "number":
        return pl.Float64
    if kind == "boolean":
        return pl.Boolean
    if kind == "array":
        return pl.List(_polars_dtype(node.get("items", {}), definitions, f"{path}[]", stack))
    if kind == "object" and "properties" in node:
        return pl.Struct({
            name: _polars_dtype(child, definitions, f"{path}.{name}", stack)
            for name, child in node["properties"].items()
        })
    if kind == "object":
        return pl.String  # free-form mapping (e.g. app_metadata): JSON text
    return _fallback(path, node)


def _fallback(path: str, node: dict) -> Any:
    pl = require("polars")
    warnings.warn(
        f"{path}: no Polars dtype for JSON Schema node {node!r}; stored as JSON text",
        FrameSchemaWarning,
        stacklevel=2,
    )
    return pl.String


def _plain_value(value: Any, dtype: Any) -> Any:
    """Turn a model attribute into what Polars accepts for ``dtype``."""
    pl = require("polars")

    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if dtype == pl.String:
        if isinstance(value, str):
            return value
        if isinstance(value, (BaseModel, dict, list, tuple)):
            return json.dumps(to_jsonable_python(value, fallback=str))
        return str(value)  # Sport and other value objects
    if isinstance(dtype, pl.Struct):
        return {
            field.name: _plain_value(getattr(value, field.name), field.dtype)
            for field in dtype.fields
        }
    if isinstance(dtype, pl.List):
        return [_plain_value(item, dtype.inner) for item in value]
    if isinstance(dtype, pl.Datetime) and isinstance(value, datetime):
        # Match the column's zone: a naive value in a UTC column is taken as UTC,
        # an aware value in a naive column is expressed as UTC wall-clock.
        if dtype.time_zone is None:
            return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return value  # date, timedelta, bool, int, float
