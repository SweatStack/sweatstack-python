# AGENTS.md

Working agreement for agents (and humans) changing this codebase. Read end
to end before your first change. Mechanics — install, test, regen, release —
live in [DEVELOPMENT.md](DEVELOPMENT.md).


## Guiding principle: mirror the REST API

This client is a thin Python projection of the SweatStack REST API. When
you add or change a surface, the default is to mirror the server:

| Server                                  | Python                                  |
| --------------------------------------- | --------------------------------------- |
| `GET /api/v1/tests/{id}`                | `client.get_test(test_id)`              |
| `POST /api/v1/traces/`                  | `client.create_trace(...)`              |
| `PUT /api/v1/traces/{id}` (full-replace)| `client.update_trace(trace_id, ...)`    |
| `DELETE /api/v1/dailies/{id}`           | `client.delete_daily(daily_id)`         |
| query param `?sport=cycling&sport=running` | `sports=[Sport.cycling, Sport.running]` |
| JSON body field `test_id`               | kwarg `test_id`                         |
| OpenAPI enum value `"auto"`             | `TraceResolution.auto`                  |

Match the server's field names, enum values, full-replace PUT semantics,
and pagination shape. Don't redesign the API in Python.

**Deliberate deviations** (these are the only ones — don't invent more):

- Path-param IDs are positional Python args (`get_test(test_id)`), not part
  of a URL string.
- Enum-typed params accept `Enum | str` so callers don't need to import the
  enum for one-off use.
- A `traces=` query parameter renames to `trace_resolution=` on the Python
  side when the wire name would be ambiguous as a kwarg. Document the
  mapping in the docstring.
- `as_dataframe=True` is a client-side convenience over list endpoints.
- Convenience composites that wrap multiple calls
  (`get_latest_activity_data`, `get_longitudinal_*`) live alongside the
  literal mirrors. Add new ones sparingly; only when a real workflow is
  awkward through the literal surface.


## Project shape

```
src/sweatstack/
├── openapi_schemas.py   # AUTO-GENERATED. Never hand-edit.
├── schemas.py           # Re-exports + Enum._missing_ / display_name helpers.
├── exceptions.py        # Public error contract. No httpx types leak.
├── client.py            # Single Client class + module-level singletons.
├── utils.py             # Dataframe / JWT helpers.
├── streamlit.py         # Streamlit integration (optional extra).
├── fastapi/             # FastAPI integration (optional extra).
└── cli.py               # Entry points.
```

Adding a new Pydantic model from the server takes three steps:

1. Regen `openapi_schemas.py` ([DEVELOPMENT.md](DEVELOPMENT.md#regenerating-openapi_schemaspy)).
2. Re-export it from `schemas.py`.
3. Import it into `client.py` so `from sweatstack import *` exposes it.

Skipping step 3 silently breaks the public surface. Same for new enums.


## Hard rules

- **`uv`, never `pip`.** Every command goes through `uv run` / `uv add`.
- **Never hand-edit `openapi_schemas.py`.** Regenerate.
- **`Raises:` references the typed exceptions** from
  `sweatstack.exceptions`. Don't write `HTTPStatusError` in new docstrings.
- **Public methods belong in `_generate_singleton_methods(...)`** at the
  bottom of `client.py`. Forgetting is silent.
- **Enum-typed params accept `Enum | str`** and route through
  `_enums_to_strings`. Don't introduce strict-enum-only parameters.
- **Tests are offline.** No network calls. Use `Client.__new__(Client)` to
  bypass init when you need an instance for a helper method.
- **`update_*` methods are full-replace.** Document the silent-clear
  footgun in the docstring (see below).
- **CHANGELOG entries are user-facing**, not dev-facing.


## Method shape

Every method on `Client` follows this shape. Match it.

```python
def do_thing(
    self,
    resource_id: str,                            # path params: positional
    *,                                           # rest: keyword-only
    timestamp: datetime,
    sport: Sport | str | None = None,            # enum params: Enum | str
    tags: list[str] | None = None,
) -> ThingDetails:
    """One-line summary.

    Optional paragraph for non-obvious behaviour (full-replace,
    server-side defaults, side effects).

    Args:
        ...

    Returns:
        ThingDetails: ...

    Raises:
        SweatStackNotFoundError: If <specific condition>.
        SweatStackAPIError: If the API request fails for any other reason.
    """
    sport = self._enums_to_strings([sport])[0] if sport else None
    with self._http_client() as client:
        response = client.post(
            url=f"/api/v1/things/{resource_id}",
            json={"timestamp": timestamp.isoformat(), "sport": sport, "tags": tags},
        )
        self._raise_for_status(response)
        return ThingDetails.model_validate(response.json())
```

Invariants baked into the template:

- Path-param IDs positional, everything else keyword-only.
- Datetimes serialize via `.isoformat()`.
- Body uses every field explicitly (full-replace contract).
- Request goes through `self._http_client()` context manager.
- Response goes through `self._raise_for_status()` before parsing.
- Return is a validated Pydantic model — never the raw dict.
- `update_*` methods are typed `-> None`. The server's
  `{"message": "..."}` body carries no useful info.

**List endpoints** add a `_get_<resource>_generator()` that yields
validated objects with internal pagination, plus a `get_<resource>s(...,
as_dataframe=False)` wrapper. Empty-list DataFrames go through
`_create_empty_dataframe_from_model(Model, normalize_columns=[...])` so
column names stay stable. See `get_activities` and `get_tests` for
exemplars.

**Query parameters** are only sent when the caller supplied a non-default
value. For enum-typed query params with an explicit default, compare
against the default and skip when equal. Always pass `.value` for enums
into `httpx.params` — `httpx` calls `str()`, which gives
`"TraceResolution.linked"`, not `"linked"`.


## Full-replace `update_*` methods

PUT endpoints overwrite every field, including by setting unsent fields
to `null`. Two rules:

1. **Send every field in the body, even when `None`.** Don't omit.
2. **Document the silent-clear footgun in the docstring** whenever you
   add a new optional field to an existing `update_*` method, *and*
   call it out in the CHANGELOG `### Changed` section. Existing callers
   who don't know about the new field will silently null it on their
   next update.

Don't try to soften the contract with "preserve if omitted" sentinels;
that diverges from how every other field behaves on these methods.


## Exceptions

The hierarchy in `sweatstack/exceptions.py` is the **public** error
contract — consumers should never need to import `httpx`.

```
SweatStackError
├── SweatStackConnectionError       # DNS / timeout / no response
├── SweatStackTokenRefreshError
└── SweatStackAPIError              # got a response with status >= 400
    ├── SweatStackAuthError         # 401, 403
    ├── SweatStackNotFoundError     # 404
    ├── SweatStackRateLimitError    # 429
    ├── SweatStackBadRequestError   # other 4xx
    └── SweatStackServerError       # 5xx
```

Docstrings: list specific subclasses for meaningful conditions (e.g. 404
when a path ID may not exist), then a catch-all `SweatStackAPIError`.


## Tests

Live in `tests/`. Offline only. The workhorse pattern is schema
round-tripping:

```python
restored = TraceDetails.model_validate(original.model_dump())
assert restored.test_id == "test_123"
```

Catches missing fields, type drift, and enum-casing changes from regen.
Exemplars: `tests/test_trace_test_linking.py`, `tests/test_tests.py`,
`tests/test_dtype_conversion.py`.


## CHANGELOG

User-facing only. Lead with what changed for the user; skip regen
output, file renames, refactors. Loud-callout any behaviour change in
`### Changed`, especially full-replace footguns. SemVer.

Good:

> ### Changed
> - `update_trace()` replaces all fields, including `test_id`. Callers
>   that omit `test_id` will clear any existing link.

Bad (belongs in the commit message, not the changelog):

> ### Changed
> - Local datetime fields are now `AwareDatetime`. The
>   `BodyExpressAddEmail...` schema is renamed to
>   `BodyConnectAddEmail...`.


## When in doubt

- Match the nearest existing method in `client.py`. Consistency with the
  surroundings beats local cleverness.
- Reuse the helpers: `_enums_to_strings`, `_get_*_generator`,
  `_normalize_dataframe_column`, `_create_empty_dataframe_from_model`,
  `_set_app_metadata`. Don't reinvent them.
- Don't add abstractions for hypothetical future flexibility. Three
  similar blocks is the pattern, not a smell.
