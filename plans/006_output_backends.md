# Plan: `output=` backends — pandas, Polars, Arrow, bytes

Make the SDK fit Polars and DuckDB workflows without abandoning pandas.
One parameter, `output`, decides the container every collection comes back
in. Every frame is column-shaped on every backend (no pandas index).
Frame libraries become optional extras.

Decided in conversation on 2026-09-25. Supersedes the "local dataset /
sync client" idea, which was evaluated and rejected (see Out of scope).
Readiness-reviewed the same day.

**Status (2026-09-28):** Track A steps 1–7 implemented on branch
`output-backends` as one commit per step, suite green, bare-install check
verified locally. Open: step 8 (release candidate against real downstream
apps) and Track B on the server.


## Summary

| Today | After |
|---|---|
| Parquet endpoints return pandas, always | `output="pandas" \| "polars" \| "arrow" \| "bytes"`, default: the installed library, Polars if both |
| List endpoints take `as_dataframe=True` | `output="models" \| "pandas" \| "polars"`, default models |
| No client-level choice | `Client(output=...)` / `sweatstack.set_output(...)` override every default |
| pandas frames carry an index (timestamp, metric value, date) | Columns everywhere, on every backend |
| pandas + pyarrow are hard dependencies | Base = httpx + pydantic + OST. `[pandas]`, `[polars]` extras |

Breaking. Ships as the next release (version to be decided; explicitly
**not** 1.0.0). Independent of any server release (see Phasing).


## Why (evidence)

- The wire format is already Arrow-native parquet (Int16, Float16,
  dictionary strings, ms timestamps). Measured on a real 6.9M-row / 35 MB
  longitudinal response from the local cache: pandas read 0.26 s plus
  0.46 s of `convert_to_standard_dtypes`; Polars 0.08 s; DuckDB 0.01 s.
  The dtype conversion exists only to paper over pandas weaknesses.
- A pandas index in parquet is a physical column plus a `pandas` metadata
  blob. Polars and DuckDB ignore the blob and already see columns. Only
  the pandas contract is index-shaped, and it is inconsistent: activity
  data, longitudinal data, both mean-max curves and activity AWD carry an
  index; `after` mean-max and longitudinal AWD are index-free. A proposed
  server change drops it for longitudinal outputs.
- A user saving a pandas frame with `to_parquet` gets 52 MB for what was
  35 MB on the wire (float64 upcast). Same query results in DuckDB. That
  size gap is the entire benefit of "keep the compact dtypes".
- Downstream analysis projects already use DuckDB and Polars against the
  raw bytes. The SDK is the laggard.


## Readiness review (2026-09-25)

Six findings. **R1 is the only prerequisite**: it is repository hygiene
that must exist before the first refactor commit. R2–R6 are requirements
on the release work itself, each folded into the Track A step named next to
it; they are listed here so the reasoning is in one place.

- **R1. Commit the safety net (prerequisite, before Track A step 1).** 15 of 16 test files, `plans/` and
  `examples/` are untracked. Commit them. Add `.github/workflows/ci.yml`:
  `uv sync --all-extras`, `uv run pytest` on 3.10–3.13. Add a second job
  that installs the **base package only** and runs
  `python -c "import sweatstack, sweatstack.fastapi"`; this is the only
  thing that keeps pandas optional afterwards (someone will add a
  top-level `import pandas` by habit).
- **R2. Internal callers must ask for models explicitly (Track A step 3).** `streamlit.py`
  (activity selectors, 2 sites), `fastapi/__init__.py` and
  `fastapi/dependencies.py` (1 site each) call `get_activities()` and
  iterate models. Under `Client(output="polars")` they would get a frame.
  Every internal call passes `output="models"`. `get_latest_activity_data`
  forwards `output` to `get_activity_data`. A test greps the package for
  internal collection calls without an explicit `output=`.
- **R3. Propagate `output` like `streamlit_compatible` (Track A step 3).**
  `delegated_client` and `principal_client` construct a new `Client` and
  already forward `url` and `streamlit_compatible`; forward `output` too.
  `switch_user` mutates in place and needs nothing.
- **R4. Typing trade-off, stated (Track A steps 3 and 7).** Per-call `Literal` overloads are
  precise. When `output` is omitted, the static return type is
  `pd.DataFrame | pl.DataFrame` for parquet endpoints (the library is only
  known at runtime) and `list[Model]` for lists, which is wrong for a
  client configured otherwise. Accepted trade-off; documented in the
  `output` docstring and README ("for type-checker precision, pass
  `output=` at the call site"). The alternative, no client-level
  override, was rejected: it defeats the set-once workflow.
- **R5. Lazy imports, enforced by R1's bare-install job (Track A step 6).** `client.py`
  and `utils.py` import pandas/numpy at module top; `fastapi/` imports
  the client. Move every pandas/numpy/pyarrow/polars import inside the
  function that uses it. `utils.convert_to_standard_dtypes` and
  `utils.make_dataframe_streamlit_compatible` keep their signatures.
- **R6. Update the guidance that would fight the change (Track A step 7).** AGENTS.md
  codifies `as_dataframe` (deliberate deviations) and
  `_create_empty_dataframe_from_model` (method shape); rewrite both
  sections for `output=` and the schema-derived empty frames. Update the skill
  reference `.claude/skills/sweatstack-python/*.md` at the source, not
  in installed copies.


## Decisions

1. **One parameter, `output`.** Present on every method that returns a
   table or a list of records. Absent on single-record methods
   (`get_activity`, `get_test`, `get_latest_activity`, ...).
2. **Values are container types:** `"models"`, `"pandas"`, `"polars"`,
   `"arrow"`, `"bytes"`.
   - Parquet endpoints: `pandas | polars | arrow | bytes`.
   - List endpoints: `models | pandas | polars | arrow`. No `bytes`:
     these responses are paginated JSON assembled client-side, so there
     is no single body to hand back.
   - Wrong combination raises `ValueError` naming the valid choices for
     that method.
3. **Per-method defaults:** parquet endpoints `"pandas"`, list endpoints
   `"models"`. `Client(output=...)` / `sweatstack.set_output(...)` replace
   the default for *all* of them, list endpoints included. Per-call
   `output=` always wins. Resolution: per-call > client instance >
   module-level `set_output` > method default.
4. **Columns everywhere.** No backend returns an index. The SDK resets any
   pandas index the server sends (`reset_index()`), so this holds against
   today's server and against one that no longer writes an index. `_shape_mean_max` and
   the dailies `set_index("date")` go away. Users who want an index add
   `.set_index(...)` themselves.
5. **Dtype policy per backend (parquet endpoints).**
   - pandas: unchanged. `convert_to_standard_dtypes` (float64 upcast,
     ns precision) still applies; Int16 cumsum overflow and float16
     are real footguns there.
   - polars: wire dtypes preserved, except `Float16 -> Float32` (Polars
     supports few operations on Float16; DuckDB upcasts too).
     Categoricals, Duration, tz-aware Datetime pass through.
   - arrow: exactly what is on the wire, no casts. The "I know what I'm
     doing" path; DuckDB queries a `pyarrow.Table` directly.
   - bytes: the response body, untouched. The "save it yourself" path.
6. **List endpoints into frames.** pandas keeps today's `json_normalize`
   flattening (`summary.power.mean`). Polars gets typed structs
   (`.unnest("summary")` is the idiom) via the schema derivation below.
7. **`as_dataframe` is removed**, not shimmed. Mechanical migration,
   loud CHANGELOG entry.
8. **Extras.** Base package has no frame library. `[arrow]` = pyarrow
   (what `output="arrow"` and DuckDB need). `[pandas]` = pandas +
   `[arrow]`. `[polars]` = polars. `[streamlit]` and `[jupyter]` depend on
   `sweatstack[pandas]`. `[fastapi]` stays frame-free. Calling a frame
   output without its library raises `ImportError` with the exact
   `uv add "sweatstack[...]"` line.
9. **The default frame library is the installed one: Polars, then pandas,
   then Arrow.**
   Decided 2026-09-28, reversing the earlier "pandas stays default": with
   frame libraries as extras, a hard-coded pandas default made a
   `sweatstack[polars]` install fail on its first call, and doing the flip
   in the same breaking release avoids a second one. Existing pandas users
   add `set_output("pandas")` once. Lists still default to models.
10. **Cache unchanged.** It stores response bytes; every backend reads
    from it. Cache key does not include `output`.


## Pydantic models -> Polars / Arrow (verified design)

The one genuinely new component. Naive approaches fail: feeding
`model_dump()` to Polars raises on nested enum/object types, and
`model_dump(mode="json")` turns datetimes into strings and gives any
all-null column a `Null` dtype, so the schema would depend on the data.

**Principle: the schema comes from JSON Schema, the values from the
model instance, and one type tree serves both Polars and Arrow.** JSON Schema is a closed grammar, it is what
`openapi_schemas.py` is generated *from*, and regen cannot introduce a
Python type the mapper has not seen without it also appearing in JSON
Schema. Two small functions, both in a new `src/sweatstack/_frames.py`:

**`field_types(Model)`** builds a small backend-neutral type tree;
`polars_schema()` and `arrow_schema()` render it. Walk
`Model.model_json_schema(schema_generator=_Gen)`, resolving `$ref`s.
Mapping, exhaustive:

| JSON Schema | Polars |
|---|---|
| `string` | `String` |
| `string` + `format: date-time` | `Datetime("us", "UTC")` |
| `string` + `format: naive-date-time` (see `_Gen`) | `Datetime("us", None)` |
| `string` + `format: date` | `Date` |
| `string` + `format: duration` | `Duration("us")` |
| `integer` | `Int64` |
| `number` | `Float64` |
| `boolean` | `Boolean` |
| `enum` / `const` | `String` |
| `array` of X | `List(X)` |
| `object` with `properties` | `Struct({...})`, recursive |
| `object` without `properties` (e.g. `app_metadata`) | `String` (JSON text) |
| `anyOf [X, null]` | X (nullable) |
| `anyOf` of only `integer`/`number` | `Float64` |
| `$ref` already on the resolution stack (recursive model) | `String` (JSON text), recorded, no warning |
| anything else | `String` (JSON text) **with a warning** |

`_Gen` is a 6-line `GenerateJsonSchema` subclass that overrides
`datetime_schema` to emit `format: naive-date-time` when the core schema
has `tz_constraint == "naive"`; stock JSON Schema cannot tell
`AwareDatetime` from `NaiveDatetime`, and `start_local` must not be
labelled UTC. Sport serialises as `{"type": "string"}` already.

**`_row(model) -> dict`.** Recursive instance walker with five cases:
`BaseModel` -> `_row`; `list` -> map; `Enum` -> `.value`; `dict` ->
`json.dumps`; `datetime | date | timedelta | bool | int | float | str |
None` -> as is; anything else (`Sport`) -> `str()`. Because it walks the
*instance* (not the dump), free-form dicts and nested models are
distinguishable.

**Assembly:** `pl.from_dicts([_row(m) for m in models], schema=schema)`.
Empty list: `pl.DataFrame(schema=schema)`. A value that does not match
its dtype raises `ComputeError` (verified), never silently coerces.

**Verified 2026-09-25** against `ActivitySummary`, `ActivityDetails`,
`TestSummary`, `TestDetails`, `TraceDetails`, `DailyResponse`,
`UserSummary`, `TeamResponse`: zero fallback warnings; two recorded
cycles (`ActivitySummary.traces[].activity`,
`TraceDetails.activity.traces[]`), matching what the pandas path already
drops; round trip of nested summary/lap structs, naive and aware
datetimes, durations, enum lists, `Sport`, JSON metadata, empty lists and
all-null structs all correct. Prototype: scratchpad
`proto_polars_schema.py`, ~80 lines including the walker.

**Regen robustness, made mechanical.** `tests/test_frames_schema.py`
does three things on every model re-exported from `schemas.py`:

1. `polars_schema(Model)` and `arrow_schema(Model)` under
   `warnings.simplefilter("error")`: any
   new JSON Schema construct the mapper does not know fails the suite at
   regen time, not in a user's notebook.
2. Round trip: build a fully populated instance from the model's JSON
   Schema example / a fixture, `_row` it, `from_dicts` with the schema,
   assert every leaf value survives and every dtype matches the table
   above.
3. Cross-check with the pandas path: the set of top-level column names
   from `field_types` equals the set of top-level keys the pandas
   `json_normalize` path starts from (before flattening).

Rule for future changes (goes in AGENTS.md): **never add a per-model
special case to `_frames.py`.** If a model needs one, the JSON Schema
grammar is missing a row in the table; add the row and its test.


## Syntax

```python
# parquet endpoints
df = client.get_activity_data(activity_id)                     # installed library, Polars if both
pf = client.get_activity_data(activity_id, output="polars")    # polars.DataFrame
tb = client.get_activity_data(activity_id, output="arrow")     # pyarrow.Table
raw = client.get_longitudinal_data(sports=["cycling"], start=date(2025, 1, 1), output="bytes")
Path("season.parquet").write_bytes(raw)
duckdb.sql("select sport, avg(power) from 'season.parquet' group by 1")

# list endpoints
acts = client.get_activities()                    # list[ActivitySummary] (default)
acts = client.get_activities(output="pandas")     # was as_dataframe=True
acts = client.get_activities(output="polars")     # summary/laps/traces are typed structs
acts.unnest("summary").unnest("power").select("id", "mean", "max")

# set once
sweatstack.set_output("polars")
sweatstack.get_activities()                # polars frame
sweatstack.get_activity_data(activity_id)  # polars frame
sweatstack.get_latest_activity()           # ActivityDetails, single record, no output
sweatstack.get_activities(output="models") # per-call override

# columns everywhere
mm = client.get_longitudinal_mean_max(sports=["cycling"], metric="power")
mm.columns   # ['power', 'duration', 'start', 'activity_id', 'sport'] on every backend
mm.set_index("power")  # only if you want the old pandas shape
```


## Phasing

Thought through with breaking releases allowed. The SDK work does not
depend on the server; the server work does not depend on the SDK once
the SDK is index-agnostic. So there are two independent tracks, not
three sequential phases.

### Track A: SDK release (this repo)

Prerequisite: R1 only. Then one release, built as ordered commits so
each step is green on its own; R2–R6 land inside the steps that cite them:

1. **Chokepoints, no behaviour change.** Introduce `_read_frame(bytes,
   output)` replacing the eight `pd.read_parquet` sites and
   `_frame_from_models(models, Model, output)` replacing the four
   `as_dataframe` blocks. `_postprocess_dataframe` becomes the pandas
   branch of `_read_frame`. Existing tests stay green.
2. **`_frames.py`: schema derivation + walker + tests** (the section
   above). Land before anything user-visible so regen safety exists from
   day one.
3. **`output=` parameter.** Add to every collection method, remove
   `as_dataframe`. `Client(output=...)`, `sweatstack.set_output(...)`,
   propagation (R3), internal callers (R2). `@overload` signatures keyed
   on `Literal` values (R4). Validation errors for invalid combinations.
4. **Polars, Arrow, bytes branches** per the dtype policy.
5. **Columns everywhere.** `reset_index()` on the pandas path for every
   parquet endpoint; delete `_shape_mean_max`'s `set_index` and the
   dailies `set_index("date")`. Verify column names per endpoint
   (activity AWD's index is named after the metric, so it resets to a
   `power`/`speed` column).
6. **Extras and lazy imports** (R5). Move pandas + pyarrow into
   `[pandas]`, add `[polars]`, make `[streamlit]`/`[jupyter]` pull
   `sweatstack[pandas]`. `ImportError` messages with the install line.
   Bare-install CI job green.
7. **Docs, AGENTS.md, skill, changelog** (R6). README, `docs/`, the skill
   reference (install lines, `output=`, no-index shapes, DuckDB example),
   CHANGELOG `### Changed` with the three migrations spelled out:
   `as_dataframe` -> `output`, index -> column, install extra.
8. **Release candidate.** Tag a pre-release, run real downstream apps
   (Streamlit and analysis projects) against it before releasing.
   **Done 2026-09-28** for one Streamlit app: migrated, run headless
   with real cached data, then run live; all checks passed. The
   migration found one silent failure (a bare `except` around index access)
   that only a live-shaped run would have caught.

### Track B: server (independent)

Not blocked on Track A for correctness, but Track A must be released
first so SDK users never notice. Then:

1. Every parquet endpoint (activity data, activity mean-max,
   longitudinal mean-max without `after`, activity AWD) stops writing
   pandas index metadata. Polars-native writer.
2. Drop float16 for float32 in the parquet writer.
3. Announce for non-SDK pandas consumers. DuckDB-WASM consumers are
   unaffected (they never saw the index).

After Track B the SDK's `reset_index()` becomes a no-op; keep it, it is
harmless and protects against older servers.

### Later, data-driven

- Flip default `output` to `"polars"` (2.0). One line plus docs.


## Tests (offline)

- `_read_frame`: a small parquet fixture written *with* a pandas
  timestamp index and one *without* (index-free shape). Both must produce
  identical columns on every backend. Same for a metric-indexed mean-max
  fixture and a metric-indexed AWD fixture.
- Dtype policy: pandas float64 upcast still applied; polars Float16 ->
  Float32, Int16/Categorical/Duration preserved; arrow untouched; bytes
  identical to input.
- `_frames.py`: the three-part `test_frames_schema.py` described above,
  plus empty lists giving correctly typed empty frames on every backend.
- Validation: `output="models"` on a parquet endpoint and
  `output="bytes"`/`"arrow"` on a list endpoint raise `ValueError`.
- Resolution order: per-call > client > module default; delegated client
  inherits.
- Internal callers: a test asserts every internal collection call in
  `streamlit.py` and `fastapi/` passes `output="models"`.
- Missing library: monkeypatch import to raise, assert the `ImportError`
  message contains the extra name.
- Public surface test (`tests/test_public_surface.py`): `set_output`
  exported, `as_dataframe` gone from every signature.
- CI bare-install job (R1) as the enforcement of R5.


## Out of scope

- **Local dataset / sync client.** Evaluated and rejected: duplicates the
  server's list-then-concat and `timestamp_local` logic, needs a
  server-side change marker that does not exist, and the measurable
  benefit is a 35 vs 52 MB file that `output="polars"` or `"bytes"`
  already closes. Users who want files write them: one call per athlete,
  one glob in DuckDB.
- **DuckDB integration in the SDK.** Nothing needed beyond `"arrow"`,
  `"polars"` and `"bytes"` plus the `[arrow]` extra (DuckDB's Python API
  bridges in-memory frames through pyarrow, verified 2026-09-28); DuckDB
  queries all three directly. README has the three routes.
- **Narwhals.** Considered for the shaping layer; the shaping is small
  enough that per-backend branches are clearer.
- **Transparent local answering of `get_longitudinal_data`** from cached
  or saved files. Coverage logic is not worth it.
- **Changing the pandas dtype policy** (native Int16 etc.). The footguns
  are real; pandas users keep float64.
- **Per-model special cases in `_frames.py`.** See the rule above.
