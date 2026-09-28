# Plan: Trace ↔ Test linking + `TraceResolution`

## Summary

Mirror upstream `sweatstack@93cd588` ("Adds trace to test optional foreign key
relationship") in the Python client:

- Traces gain an optional `test_id` FK that *explicitly* links them to a test
  (independent of timestamp).
- `GET /api/v1/tests/{test_id}` gains a `traces` query parameter
  (`TraceResolution` enum: `auto` | `linked`) that controls how the returned
  `traces` list is resolved.
- `POST /api/v1/traces/` and `PUT /api/v1/traces/{trace_id}` may now return
  `404` when a referenced `test_id` does not exist.

Server-side behaviour:

- `auto` (default): traces whose timestamp falls in the test's window, **plus**
  traces explicitly linked to this test, **minus** traces explicitly linked to a
  *different* test.
- `linked`: only traces explicitly linked via `test_id`; the time window is
  ignored.

The `activities` list is unaffected — always time-overlap matched.

## Code Quality Requirements

Same bar as plan 001a:

- Follow existing patterns exactly (keyword-only params, enum handling,
  `_enums_to_strings`, error surface via `_raise_for_status`, docstring style).
- Comprehensive type hints. No `Any`. No string-typed enums on the surface.
- Concise Google-style docstrings (Args / Returns / Raises).
- No dead code, no TODOs, no half-finished branches.

## Step 1: Regenerate `openapi_schemas.py`

The **user will run the SweatStack server locally** at
`http://localhost:8080`. Wait for confirmation that the server is up
before running the regen, and do not attempt to start the server.

Then:

```bash
uv run generate-response-models
```

Expected diff in `src/sweatstack/openapi_schemas.py`:

- `TraceDetails`: new `test_id: str | None = Field(None, title='Test Id')`.
- `TraceCreateOrUpdate`: new `test_id: str | None = Field(None, title='Test Id')`.
- New top-level enum:

  ```python
  class TraceResolution(Enum):
      auto = 'auto'
      linked = 'linked'
  ```

**Caveat — regen pulls more than this feature.** Two intervening upstream
commits since `openapi_schemas.py` was last regenerated also touch the
schema/API surface: `feebe56` ("Adds security.txt …") and `3f29c1f`
("Better handling of tags=null"). The regenerated diff will not be
confined to this plan's scope.

Action: review the full diff. If unrelated changes appear, **split them
into a separate commit** ahead of the trace-linking commit so the
trace-linking commit stays reviewable. Do not merge regen-noise as part
of this feature.

Also verify on the running server before committing: open
`http://localhost:8080/openapi.json`, search for `TraceResolution`,
confirm wire values are `"auto"` and `"linked"` (lowercase). This guards
against an upstream `BaseEnum` casing change.

## Step 2: Re-export `TraceResolution`

Two-step exposure (mirrors `Sport`):

1. `src/sweatstack/schemas.py` — add `TraceResolution` to the import from
   `openapi_schemas`.
2. `src/sweatstack/client.py` — add `TraceResolution` to the import block
   pulling enums/schemas from `.schemas` (≈ line 45, where `Sport`,
   `TraceDetails`, etc. are imported).

`__init__.py` is `from .client import *`, so step 2 is what actually makes
`from sweatstack import TraceResolution` work. Verify with a smoke test
in the REPL after the change. (This is the step that's easy to skip and
breaks the public surface.)

## Step 3: Update `src/sweatstack/client.py`

Import `TraceResolution` from `schemas` in the existing imports block
(≈ line 45, alongside `TraceDetails`).

### 3a. `create_trace` — add `test_id` keyword arg

Location: ≈ line 1708.

- Add `test_id: str | None = None` as the **last** keyword-only param
  (preserves existing call-site compatibility — every existing caller uses
  keyword args, but appending keeps the visual ordering stable).
- Add `"test_id": test_id` to the JSON body. Do not omit when `None`; the
  server accepts `null` and other optional fields are already passed as
  `None` (consistent with `lactate`, `rpe`, etc.).
- Docstring:
  - Add `test_id: Optional ID of a test to explicitly link this trace to.
    If the test does not exist, the API raises 404.` to Args.
  - Add a `Raises:` note that an `HTTPStatusError(404)` is raised when
    `test_id` references a non-existent test (existing `_raise_for_status`
    already surfaces this; just document it).

### 3b. `update_trace` — add `test_id` keyword arg

Location: ≈ line 1762.

Identical treatment to `create_trace`. Same docstring additions.

**Behavioural-change callout (required in both docstring and CHANGELOG):**
`update_trace` is full-replace. Once `test_id` is in the signature with a
default of `None`, **existing callers that don't pass `test_id` will silently
unlink any previously linked test** the next time they call
`update_trace`. This is consistent with how every other optional field on
`update_trace` already behaves (e.g. `lactate=None` nulls lactate), but
it's a real, observable change for upgraders.

Docstring wording suggestion:

> Note: This is a full-replace operation. If a trace was previously linked
> to a test via `test_id`, you must pass that `test_id` again to preserve
> the link — otherwise it is cleared.

Do not try to work around this with "preserve if omitted" sentinels — that
would diverge from how every other field on this method behaves and rot
the contract.

### 3c. `get_test` — add `trace_resolution` keyword arg

Location: ≈ line 1934.

Current signature:

```python
def get_test(self, test_id: str) -> TestDetails:
```

New signature:

```python
def get_test(
    self,
    test_id: str,
    *,
    trace_resolution: TraceResolution = TraceResolution.auto,
) -> TestDetails:
```

Naming decision: **`trace_resolution`, not `traces`.** The wire name is
`traces=` (server query param), but on the Python method
`client.get_test("t1", traces=TraceResolution.linked)` reads as "give me
the test and traces=X" — ambiguous. `trace_resolution=` is
self-documenting. Note the wire mapping in the docstring so future
maintainers know they don't match.

Typing decision: **strict `TraceResolution`, not `TraceResolution | str`.**
This diverges from the `Sport | str` pattern used elsewhere in the
client. The deviation is deliberate: the enum has exactly two values, it
is a brand-new surface (no historical string callers to support), and
the brief asks for "extremely clean". Document the deviation in a code
review note when the PR goes up; don't surprise the reviewer.

Implementation:

```python
with self._http_client() as client:
    params = {}
    if trace_resolution is not TraceResolution.auto:
        params["traces"] = trace_resolution.value
    response = client.get(
        url=f"/api/v1/tests/{test_id}",
        params=params,
    )
    self._raise_for_status(response)
    return TestDetails.model_validate(response.json())
```

Notes:

- Use `.value` (lowercase `"auto"` / `"linked"`) explicitly. `httpx` does
  not unwrap `Enum.value` on its own — it `str()`s the value, which gives
  `"TraceResolution.linked"`. Verified pattern: `_get_tests_generator` and
  every other enum query usage in this file calls `.value`.
- **Omit the param when at default** — matches the convention used by
  `_get_activities_generator`, `_get_tests_generator`, etc., which only
  add optional query params when the caller supplied a non-default.
  Sending `?traces=auto` would deviate from this pattern.
- Keep `test_id` positional (existing call sites pass it positionally);
  only `trace_resolution` is keyword-only. Strictly additive.
- Docstring: explain `auto` vs `linked` in user terms. Copy the
  server-side wording verbatim from `app/routers/api.py` — it is the
  canonical description and survives doc drift.

### 3d. No other method changes

- `get_traces()` is unchanged. Upstream does not yet expose a `test_id`
  filter on the list endpoint; do not add a client-side filter
  (out of scope, would lie about API support).
- `_get_traces_generator()` is unchanged. The new `test_id` field rides
  along automatically in `TraceDetails`.

## Step 4: Tests

Add `tests/test_trace_test_linking.py`. Follow the no-network pattern
established by the other tests in this repo.

Coverage:

- **Schema round-trip**: build a `TraceDetails` with `test_id="t_123"`,
  `.model_dump()` → `.model_validate()` round-trip preserves it.
- **TraceCreateOrUpdate accepts `test_id`**: `TraceCreateOrUpdate(timestamp=...,
  test_id="t_123")` validates; `.model_dump()` includes the field.
- **`TraceResolution` enum values**: assert `TraceResolution.auto.value ==
  "auto"` and `TraceResolution.linked.value == "linked"` (guards against the
  generator regenerating the enum with different casing on the wire).
- **Re-export**: `from sweatstack import TraceResolution` resolves, *and*
  `import sweatstack; sweatstack.TraceResolution` resolves (catches the
  client-level import step easy to skip).

If the repo already has an httpx-mock based test harness (it currently does
not, judging by the existing files), add a single integration-style test for
`get_test(test_id, traces=TraceResolution.linked)` that asserts the request
URL carries `?traces=linked`. If not, skip — the enum-value test above
provides the same guarantee without inventing a test infrastructure for this
plan alone.

## Step 5: Examples / docs

- Quick scan of `examples/` — if there is an existing "tests" example, append
  a short snippet showing:

  ```python
  test = client.create_test(sport=Sport.cycling, start=...)
  client.create_trace(timestamp=..., lactate=4.0, test_id=test.id)
  detail = client.get_test(test.id, traces=TraceResolution.linked)
  ```

  If none exists, do **not** add a new example file for this alone.

- `docs/everything.rst` — `TraceDetails` and `TraceCreateOrUpdate` autoclass
  entries pick up the new field automatically. Add a `.. autoclass::
  sweatstack.openapi_schemas.TraceResolution` entry in the same enums block
  where `Sport` lives (if `Sport` is documented there — check before adding).

- `.claude/skills/sweatstack-python/client.md` — update the `create_trace`,
  `update_trace`, and `get_test` signatures, and add `TraceResolution` to
  the list of exported enums.

## Step 6: Changelog + version bump

- `CHANGELOG.md`: new entry under the next minor version. Must include
  both the additive feature and the behavioural-change callout.
  Wording suggestion:

  > **Added** — Traces can be explicitly linked to a test via the new
  > `test_id` parameter on `create_trace` and `update_trace`. `get_test`
  > accepts a `trace_resolution` parameter (`TraceResolution.auto` or
  > `TraceResolution.linked`) controlling how the returned traces list is
  > resolved.
  >
  > **Behaviour change** — `update_trace` is full-replace. Callers that
  > previously linked a trace to a test (e.g. via the SweatStack UI or
  > another client) and then call `update_trace` without passing
  > `test_id` will now unlink that trace. Pass the existing `test_id`
  > back in to preserve the link.

- `pyproject.toml`: bump `0.76.2 → 0.77.0` (minor — additive feature, no
  breaking change). Confirm the version cadence with the maintainer if
  unsure; this is the only judgement call in the plan.

## API Reference

| Method | Path | New parameter | Notes |
|--------|------|---------------|-------|
| POST | `/api/v1/traces/` | body `test_id?: str` | 404 if test missing |
| PUT  | `/api/v1/traces/{id}` | body `test_id?: str` | full-replace; `null` unlinks; 404 if test missing |
| GET  | `/api/v1/tests/{id}` | query `traces=auto\|linked` | default `auto` |

### Resolution semantics (server-side, reference only)

- `auto`: `(traces in window AND not claimed by another test) ∪ (traces with test_id == this test)`
- `linked`: `traces with test_id == this test` (window ignored)

## Out of Scope

- Listing/filtering traces by `test_id` on `GET /traces/` (upstream does not
  expose this).
- Bulk attach/detach helpers (`attach_traces_to_test(...)`). Not requested by
  upstream; would be premature abstraction.
- A `linked_only: bool` convenience on `get_test`. Rejected in favour of the
  enum to keep a single, faithful surface.
