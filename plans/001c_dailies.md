# Plan: Add Dailies (Daily Health Metrics) to Python Client

## Summary

Add support for daily health/body metrics - time-series data like body mass, HRV, resting HR, etc. with server-side interpolation/estimation. Simple CRUD per measure with smart gap-filling on read.

## Code Quality Requirements

All code must be extremely clean, robust and maintainable:
- Follow existing patterns and conventions exactly
- Clean enum handling matching Sport/Metric patterns
- Comprehensive type hints and docstrings

## Step 1: Schemas

### Generated schemas

Schema generation (`uv run generate-response-models`) must have been run (see 001a step 1). This produces:

- `DailyMeasure` enum: `body_mass`, `body_fat_pct`, `resting_hr`, `hrv`, `sleep_duration`, `sleep_altitude`, `menstrual_cycle_day`
- `DailyResponse`: `date`, `value` (nullable float), `source` (str)

### Enum enhancements in `schemas.py`

Add `DailyMeasure` enhancements following the existing `Sport`/`Metric` pattern:
- `display_name()` method (replace underscores with spaces)
- `_missing_` classmethod handler for forward compatibility with new measures

### Re-exports

Add `DailyMeasure` and `DailyResponse` to the imports in `schemas.py` (from `openapi_schemas`) and to the imports in `client.py` (from `schemas`). They become available to users via `from sweatstack import DailyMeasure` since `__init__.py` is `from .client import *`.

## Step 2: Add Dailies methods to `client.py`

Three methods matching the three API endpoints.

**Design decision: `measure` is positional.** This breaks the convention that list/create methods use keyword-only params, but it's justified: `measure` is part of the URL path (`/dailies/{measure}`), identifying which time-series resource to operate on. It's analogous to `get_activity(activity_id)` rather than to a filter parameter.

**Design decision: `set_daily` not `create_daily`.** The API has upsert semantics (creates or updates). `create_daily` implies it would fail if the entry exists; `set_daily` honestly communicates "set this value for this date" regardless of prior state. This also aligns with `set_*_app_metadata` for other upsert operations in 001b.

```python
def get_dailies(
    self,
    measure: DailyMeasure | str,
    *,
    start: date,
    end: date,
    interpolate: bool = True,
    as_dataframe: bool = False,
) -> list[DailyResponse] | pd.DataFrame:
    """Gets daily values for a measure over a date range.

    Args:
        measure: The daily measure to retrieve (e.g. DailyMeasure.body_mass).
        start: Start date (inclusive).
        end: End date (inclusive).
        interpolate: Whether to apply server-side estimation/interpolation.
            Defaults to True. When False, missing dates return value=None
            with source="missing".
        as_dataframe: Whether to return results as a pandas DataFrame.
            Defaults to False.

    Returns:
        Either a list of DailyResponse objects or a pandas DataFrame with
        date as index. Always returns one entry per date in the range.
    """
    # GET /api/v1/dailies/{measure}
    # Convert measure enum to string for URL path
    # Query: start, end, interpolate
    # Parse response as list of DailyResponse
    # DataFrame mode: set date as index for natural time-series usage

def set_daily(
    self,
    measure: DailyMeasure | str,
    *,
    date: date,
    value: float,
) -> DailyResponse:
    """Sets a daily value (creates or updates).

    Args:
        measure: The daily measure (e.g. DailyMeasure.body_mass).
        date: The date for the measurement.
        value: The measurement value.

    Returns:
        DailyResponse: The created/updated daily entry.
    """
    # POST /api/v1/dailies/{measure}
    # Body: {date: date.isoformat(), value: value}

def delete_daily(
    self,
    measure: DailyMeasure | str,
    *,
    date: date,
) -> None:
    """Deletes a daily value.

    Args:
        measure: The daily measure to delete.
        date: The date of the entry to delete.

    Raises:
        HTTPStatusError: 404 if entry does not exist.
    """
    # DELETE /api/v1/dailies/{measure}?date={date.isoformat()}
    # Returns None (API returns 204)
```

## Step 3: Register singleton methods

Add to `_generate_singleton_methods()`:
```python
"get_dailies",
"set_daily",
"delete_daily",
```

## Step 4: Tests (pytest)

Add `tests/test_dailies.py`. Follow existing style - test pure logic without hitting the API.

Focus on:
- **DailyMeasure enum enhancements**: Verify `display_name()` returns expected strings (e.g. `DailyMeasure.body_fat_pct.display_name()` -> `"body fat pct"`). Verify `_missing_` handles unknown values gracefully.
- **DataFrame conversion**: Build a list of `DailyResponse` objects, convert to DataFrame the same way `get_dailies(as_dataframe=True)` would, verify date is set as index and columns are correct.
- **Enum to string conversion**: Verify `DailyMeasure.body_mass` serializes to `"body_mass"` for the URL path.

Don't test: HTTP calls, interpolation logic (that's server-side).

## Step 5: Update skill docs

Update `.claude/skills/sweatstack-python/client.md` with the new Dailies methods.

## Step 6: Changelog

Add entries to the `[Unreleased]` section of `CHANGELOG.md`.

## API Reference

| Method | Path | Query/Body | Response |
|--------|------|------------|----------|
| GET | `/api/v1/dailies/{measure}` | Query: `start` (date, required), `end` (date, required), `interpolate` (bool, default true) | `DailyResponse[]` |
| POST | `/api/v1/dailies/{measure}` | Body: `{date, value}` | `DailyResponse` |
| DELETE | `/api/v1/dailies/{measure}` | Query: `date` (date, required) | 204 |

### Supported Measures

| Measure | Unit | Interpolation Strategy |
|---------|------|------------------------|
| `body_mass` | kg | Linear interpolation + fill |
| `body_fat_pct` | % | Linear interpolation + fill |
| `resting_hr` | bpm | None (gaps shown) |
| `hrv` | ms | None (gaps shown) |
| `sleep_duration` | seconds | None (gaps shown) |
| `sleep_altitude` | meters | Forward/backward fill |
| `menstrual_cycle_day` | day | Auto-increment from 0 |

### Key Behaviors
- Composite key: (user, date, measure) - one value per measure per day
- Source precedence: manual entries are never overwritten by integration imports
- `interpolate=True`: server fills gaps using measure-specific strategy
- `interpolate=False`: returns raw data with `{value: None, source: "missing"}` for gaps
- Always returns exactly one entry per date in the requested range
