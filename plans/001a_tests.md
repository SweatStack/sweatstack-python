# Plan: Add Tests (Fitness Assessments) to Python Client

## Summary

Add full CRUD support for the Tests resource - fitness assessments/evaluations containing structured physiological results (thresholds, VO2max, critical power, etc.).

## Code Quality Requirements

All code must be extremely clean, robust and maintainable:
- Follow existing patterns and conventions exactly (keyword-only params, enum handling, error handling, docstrings)
- Comprehensive type hints throughout
- Clear, concise docstrings matching the existing style (Args, Returns, Raises)
- No shortcuts, no dead code, no TODOs left behind

## Step 1: Generate schemas

Regenerate `openapi_schemas.py` from the running backend (must be running at `localhost:8080`):

```bash
uv run generate-response-models
```

This runs `datamodel-code-generator` against the OpenAPI spec (see `src/sweatstack/cli.py`). It auto-generates all Pydantic models including `TestSummary`, `TestDetails`, `TestResults`, `Marker`, `DailyMeasure`, `DailyResponse`, etc.

This step is shared across all three plans (001a/b/c). Only needs to run once.

## Step 2: Re-export new schemas from `schemas.py`

Add new models to the imports in `schemas.py` (which re-exports from `openapi_schemas.py`).

New exports needed:
- `TestSummary`, `TestDetails`, `TestResults`, `Marker`

These then become available via `from sweatstack import TestSummary` etc. since `__init__.py` is just `from .client import *` and `client.py` imports from `schemas.py`.

No `DailyMeasure` enum enhancements here - that belongs to plan 001c.

## Step 3: Add Tests methods to `client.py`

Follow the exact patterns established by activities and traces. Import new schemas in `client.py` from `schemas.py`.

### List with pagination generator (follows `_get_activities_generator` / `get_activities` pattern)

```python
def _get_tests_generator(
    self,
    *,
    start: date | None = None,
    end: date | None = None,
    sports: list[Sport | str] | None = None,
    tags: list[str] | None = None,
    created_by: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Generator[TestSummary, None, None]:
    # Same structure as _get_activities_generator.
    # default_limit = 50 (matches API default, unlike activities which use 100)
    # Query params: start, end, sport (list), tags (list), created_by, limit, offset
    # Yields TestSummary.model_validate(item) for each item
```

```python
def get_tests(
    self,
    *,
    start: date | None = None,
    end: date | None = None,
    sports: list[Sport | str] | None = None,
    tags: list[str] | None = None,
    created_by: str | None = None,
    limit: int = 50,
    offset: int = 0,
    as_dataframe: bool = False,
) -> list[TestSummary] | pd.DataFrame:
    # Consumes generator into list.
    # DataFrame conversion: model_dump() each item, then normalize the "results" column
    # using _normalize_dataframe_column (same pattern as activities normalizing "summary").
    # Empty result: use _create_empty_dataframe_from_model(TestSummary, normalize_columns=["results"])
```

### Get single test (follows `get_activity` pattern)

```python
def get_test(self, test_id: str) -> TestDetails:
    # GET /api/v1/tests/{test_id}
    # Returns TestDetails (includes resolved traces + overlapping activities)
```

### Create (follows `create_trace` pattern)

```python
def create_test(
    self,
    *,
    sport: Sport | str,
    start: datetime,
    title: str | None = None,
    end: datetime | None = None,
    results: TestResults | None = None,
    tags: list[str] | None = None,
) -> TestSummary:
    # POST /api/v1/tests/
    # sport and start are required (matching the API)
    # Convert sport enum via _enums_to_strings()
    # Serialize: start/end via .isoformat(), results via .model_dump() if not None
    # Return TestSummary.model_validate(response.json())
```

### Update (new pattern - first PUT/update in this client)

```python
def update_test(
    self,
    test_id: str,
    *,
    sport: Sport | str,
    start: datetime,
    title: str | None = None,
    end: datetime | None = None,
    results: TestResults | None = None,
    tags: list[str] | None = None,
) -> None:
    # PUT /api/v1/tests/{test_id}
    # Returns None (API returns {"message": "..."})
    #
    # Docstring must clearly state full-replace semantics:
    # "Updates a test by replacing all fields. Fields not provided are set
    # to null. To modify a single field, first fetch the test with
    # get_test(), then pass all fields back."
```

### Delete (new pattern - first DELETE in this client)

```python
def delete_test(self, test_id: str) -> None:
    # DELETE /api/v1/tests/{test_id}
    # Returns None
```

## Step 4: Register singleton methods

Add to `_generate_singleton_methods()`:
```python
"get_tests",
"get_test",
"create_test",
"update_test",
"delete_test",
```

## Step 5: Tests (pytest)

Add `tests/test_tests.py`. Follow the existing testing style (see `test_dtype_conversion.py`, `test_webhooks.py`) - test pure logic without hitting the API.

Focus on:
- **Serialization round-trip**: Create a `TestResults` with `Marker` objects, serialize via `.model_dump()`, validate back via `TestSummary.model_validate()`. Verify nested structures survive the round-trip.
- **DataFrame conversion**: Build a list of `TestSummary` objects, convert to DataFrame the same way `get_tests(as_dataframe=True)` would, verify the `results` column gets normalized into `results.first_threshold.power`, `results.vo2max` etc.
- **Empty DataFrame**: Verify `_create_empty_dataframe_from_model(TestSummary, normalize_columns=["results"])` produces a valid empty DataFrame with the right column structure.
- **Enum handling**: Verify `_enums_to_strings([Sport.cycling])` works for the sports param, and that string pass-through works.

Don't test: HTTP calls, authentication, pagination logic (that's integration testing).

## Step 6: Update skill docs

Update `.claude/skills/sweatstack-python/client.md` with the new Tests methods.

## API Reference

| Method | Path | Query/Body | Response |
|--------|------|------------|----------|
| POST | `/api/v1/tests/` | Body: `{title?, sport, start, end?, results?, tags?}` | `TestSummary` |
| GET | `/api/v1/tests/` | Query: `start?, end?, sport[]?, tags[]?, created_by?, limit, offset` | `TestSummary[]` |
| GET | `/api/v1/tests/{test_id}` | - | `TestDetails` |
| PUT | `/api/v1/tests/{test_id}` | Body: `{title?, sport, start, end?, results?, tags?}` (full replace) | `{"message": "..."}` |
| DELETE | `/api/v1/tests/{test_id}` | - | `{"message": "..."}` |

### Key Schema Details

**TestResults** contains all-optional fields:
- Thresholds: `first_threshold`, `second_threshold`, `fatmax`, `lt1`, `lt2`, `vt1`, `vt2`, `mlss` (each a `Marker`)
- Capacity: `vo2max`, `vo2peak` (mL/min), `vlamax` (mmol/L/s), `heart_rate_max` (bpm), `critical_power` (W), `critical_speed` (m/s), `w_prime` (kJ), `d_prime` (m)
- Economy: `economy` (mL O2/kg/km), `efficiency` (%)

**Marker**: `power` (W), `speed` (m/s), `heart_rate` (bpm), `lactate` (mmol/L), `vo2` (mL/min)

### Key Behaviors
- `end` defaults to `start + 3h` server-side if omitted
- TestDetails resolves traces by timestamp within window, activities by time overlap
- App ownership: tests created via app token can only be modified/deleted by that app
- Tags use AND logic for filtering, sports use OR logic
