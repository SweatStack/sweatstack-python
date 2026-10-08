# AGENTS.md

Working agreement for agents (and humans) changing this codebase. Read end
to end before your first change. Mechanics — install, test, regen, release —
live in [DEVELOPMENT.md](DEVELOPMENT.md).


## Public repository

This repository is public, and so is everything in its history. Treat every
change as published the moment it is committed: code, comments, docstrings,
tests and fixtures, `plans/`, `skills/`, examples, notebooks, the CHANGELOG,
commit messages and PR descriptions. Removing something later does not
unpublish it.

Never commit:

- **Secrets and credentials**: API keys, tokens, client secrets, session
  keys, `.env` contents. Not even expired or test-account ones.
- **Real identifiers**: user, app, activity or team IDs, emails, client
  IDs, or truncated prefixes of them. Fixtures and examples use obvious
  fakes: `app_123`, `user_123`, `YOUR_CLIENT_ID`.
- **Customers and their behaviour**: names of apps, companies or people
  using SweatStack, how many there are, what they call or filter on, or
  anything learned from server logs, traffic or support conversations.
  Write "SDK users" or "downstream apps".
- **The private server codebase**: its file paths, function names, commit
  hashes, branch names and plan numbers. Describe the server by its public
  contract: the OpenAPI schema and docs.sweatstack.no. "The server now
  returns X" is fine; "see server plan N" is not.
- **Local environments**: home directories, machine paths, names of
  private sibling repos, personal data in notebook outputs or test data.
  Commit notebooks with outputs cleared.

When unsure, leave it out and ask. `tests/test_public_hygiene.py` catches
the patterns a regex can (real-looking IDs, JWTs, keys, home paths, server
references, notebook outputs). Names and behaviour of customers need you
to notice them; there is no list to check against, because the list itself
would be the leak.


## Guiding principle: mirror the REST API

This client is a thin Python projection of the SweatStack REST API. Every endpoint group is a
resource namespace on `Client`, and every name follows from the URL by eight rules. Apply them;
don't invent names.

| # | Rule | Examples |
|---|---|---|
| R1 | **The first URL segment after `/api/v1/` is the top-level namespace**, a typed `cached_property` on `Client`. | `/activities/...` → `client.activities` |
| R2 | **Collection verbs follow Stripe:** `list`, `retrieve`, `create`, `delete`. | `GET /tests/{id}` → `tests.retrieve(id)` |
| R3 | **Name writes by what they do, not by the HTTP verb.** Overwrites every field and clears what you leave out: `replace`. Changes only the fields you pass: `update`. Read the server code to tell which; the verb doesn't say. | `PUT /traces/{id}` → `traces.replace`; `PUT /users/{id}` → `users.update` |
| R4 | **A single value that is set or cleared** (an upsert, or a blob with no ID) uses `set` and `delete`. | `POST /dailies/{measure}` → `dailies.set` |
| R5 | **A nested collection is a nested namespace**, parent ID first. | `/portal/sessions` → `portal.sessions.create`; `.../{id}/app-metadata` → `activities.app_metadata.set(id, ...)` |
| R6 | **A sub-path with a single `GET` is a method named after the noun.** | `GET /activities/{id}/data` → `activities.data(id)` |
| R7 | **An action endpoint (`POST .../<verb>`) is a method named after the verb.** | `POST /activities/upload` → `activities.upload` |
| R8 | **Parameter names are the wire names.** A repeatable query parameter takes one value or a list under the same name (normalise with `Resource._wire`). | `?sport=a&sport=b` → `sport=["a", "b"]` or `sport="a"` |

Match the server's field names, enum values and write semantics. Don't redesign the API in
Python.

**Deliberate deviations** (these are the only ones; don't invent more):

- Path-param IDs are positional Python args (`tests.retrieve(test_id)`); everything else is
  keyword-only.
- Enum-typed params accept `Enum | str` so callers don't need to import the enum.
- `limit` and `offset` on list methods are SDK-level: `limit` is how many items the caller gets,
  and `Resource._paginate` pages through the endpoint to get them.
- A `traces=` query parameter is `trace_resolution=` on `tests.retrieve`, where the wire name
  would be ambiguous. The docstring states the mapping.
- `name=` on `users.list` and `teams.users` filters client-side (case-insensitive substring of
  the display name) until the server offers the filter; then it becomes the wire parameter
  with the same name and semantics. Don't add other client-side filters.
- `output=` is a client-side choice of container on the data endpoints. See "Output backends".
- `activities.longitudinal` groups the three `/activities/longitudinal-*` endpoints.
- Convenience composites that wrap several calls are a last resort. The 0.91 redesign removed
  them (`get_latest_activity_data` became chaining); add one only when a real workflow is
  awkward through the literal surface.


## Project shape

```
src/sweatstack/
├── openapi_schemas.py   # AUTO-GENERATED. Never hand-edit.
├── schemas.py           # Re-exports (incl. OST Sport/Modifier) + Metric/Scope/DailyMeasure helpers.
├── _frames.py           # output= backends: parquet/models -> pandas/polars/arrow/bytes.
├── _renames.py          # Removed names -> replacement hints. Permanent; see "Breaking changes".
├── _transport.py        # Retry policy and the per-request Session on the client's connection pool.
├── exceptions.py        # Public error contract. No httpx types leak.
├── client.py            # Client: config, auth, delegation, transport (_request), resource attributes,
│                        #   and the module-level interface (one shared default client).
├── resources/           # One module per URL segment: activities.py, traces.py, tests.py, ...
│   ├── _base.py         #   Resource, _paginate, _wire, shared parameter types.
│   └── _app_metadata.py #   One app-metadata class per endpoint (Activity/Trace/Test/Profile).
├── utils.py             # Dataframe / JWT helpers.
├── streamlit.py         # Streamlit integration (optional extra).
├── fastapi/             # FastAPI integration (optional extra).
└── cli.py               # Entry points (schema regeneration).

skills/sweatstack-python/  # The published agent skill (npx skills add). Update with the public surface.
plans/                     # Design plans, numbered. Public: see "Public repository".
tests/typing/              # Static type tests, checked by ty, never run by pytest.
```

`.claude/` is git-ignored: it is local agent tooling only.

Adding a new Pydantic model from the server takes three steps:

1. Regen `openapi_schemas.py` ([DEVELOPMENT.md](DEVELOPMENT.md#regenerating-openapi_schemaspy)).
2. Re-export it from `schemas.py`.
3. Import it into `client.py` and add it to `__all__` so `from sweatstack import *` exposes it.

Skipping step 3 silently breaks the public surface. Same for new enums.

Adding a new endpoint: find its namespace by R1, its name by R2–R7, write the method in that
resource module (template below), and add it to `skills/sweatstack-python/api.md`. A new URL
segment is a new resource module plus a `cached_property` on `Client`; the module level mirrors
it automatically.


## Hard rules

- **`uv`, never `pip`.** Every command goes through `uv run` / `uv add`.
- **`make check` before every commit.** Format, lint, types and tests; `make
  publish` runs it too. Don't silence a finding without a comment saying why.
- **Never hand-edit `openapi_schemas.py`.** Regenerate.
- **`Raises:` references the typed exceptions** from `sweatstack.exceptions`.
- **Every public resource method's docstring has an `Endpoint:` line and an `Examples:` block**
  with a complete, runnable snippet. `tests/test_docstrings.py` enforces both.
- **Public resources are typed `cached_property` attributes of `Client`**, so type checkers and
  the snippet check resolve them statically, and a client built with `Client.__new__` still
  has them. The module level mirrors them automatically.
- **A breaking change ships with its upgrade path** (see "Breaking changes").
- **A change to the public surface updates `skills/sweatstack-python/` in the same commit.**
  `tests/test_skill.py` fails when `api.md` misses a method.
- **Enum-typed params accept `Enum | str`** and route through
  `_enums_to_strings`. Don't introduce strict-enum-only parameters.
- **Open enums stay open.** When the server documents an enum as an open
  set (metrics, scopes, daily measures, status codes, capabilities),
  register it with `_open_enum(...)` in `schemas.py` so unknown values
  parse as pseudo-members. Leave closed sets strict.
- **Never retry a request the server can't safely repeat.** `_transport.RETRYABLE_METHODS`
  is `GET`, `PUT` and `DELETE`; a `POST` is sent once (no idempotency keys). Don't add
  per-method retry logic: everything goes through `_request`.
- **Server-to-server calls pass `auth=False` to `_request`.** Endpoints that authenticate with
  the app's own credentials in the body (Portal sessions, the token exchange) must never
  receive a user's bearer.
- **`Sport` is the OpenSportTaxonomy type** (`open_sport_taxonomy.Sport`), not a generated enum.
  Construct with `Sport("cycling.road")` or `Sport.parse(value)`; serialise with `str(sport)`. Codegen
  binds the `sport` field to OST's permissive `SportField` (cli.py `_bind_sport_to_ost`), so regen is
  safe and `sport`-typed fields keep decoding to `Sport`.
- **Tests are offline.** No network calls. Fake the transport at `Client._request` (see
  `tests/test_resources.py`), or use `Client.__new__(Client)` to bypass init.
- **Frame libraries are optional extras.** Never import pandas, numpy,
  pyarrow or polars at module top level; import inside the function, via
  `_frames.require(...)` where an `ImportError` should name the extra.
  CI's bare-install job fails otherwise.
- **No frame carries an index**, on any backend. Don't `set_index` in a
  method; the caller does that.
- **`replace` methods overwrite every field.** Document the silent-clear footgun in the
  docstring (see below).
- **CHANGELOG entries are user-facing**, not dev-facing.


## Method shape

Every resource method follows this shape. Match it.

```python
class Things(Resource):
    def create(
        self,
        *,                                           # keyword-only (path IDs come first, positional)
        timestamp: datetime,
        sport: Sport | str | None = None,            # enum params: Enum | str
        tags: list[str] | None = None,
    ) -> ThingDetails:
        """One-line summary.

        Endpoint: ``POST /api/v1/things/``

        Optional paragraph for non-obvious behaviour (full replace,
        server-side defaults, side effects).

        Args:
            ...

        Returns:
            ThingDetails: ...

        Raises:
            SweatStackNotFoundError: If <specific condition>.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            thing = client.things.create(timestamp=datetime.now(timezone.utc))
            ```
        """
        sport = self._client._enums_to_strings([sport])[0] if sport else None
        response = self._client._request(
            "post",
            "/api/v1/things/",
            json={"timestamp": timestamp.isoformat(), "sport": sport, "tags": tags},
        )
        return ThingDetails.model_validate(response.json())
```

Invariants baked into the template:

- Path-param IDs positional, everything else keyword-only.
- Datetimes serialize via `.isoformat()`; write timestamps go through `_require_aware`.
- Every request goes through `self._client._request(...)`, which raises the typed exception
  for an error status. Only streaming endpoints open `_http_client()` themselves.
- Return is a validated Pydantic model, never the raw dict.
- `replace` methods are typed `-> None`. The server's `{"message": "..."}` body carries no
  useful info.
- A class that defines `list` annotates with `builtins.list[...]`: inside the class body,
  `list` is the method.

**List endpoints** page with `self._paginate(path, params, Model, page_size=..., limit=...,
offset=...)` and return `self._client._frame_from_models(models, Model, output, flatten=(...))`.
Empty lists yield typed empty frames automatically. See `Activities.list`.

**Parquet endpoints** return `self._client._read_frame(response.content, output)`. Never call
`pd.read_parquet` in a method.

Both kinds take `output` as a keyword-only parameter and carry `@overload` stubs keyed on the
`Literal` values (clone the neighbours); `tests/typing/output_types.py` pins them.

**Query parameters** are only sent when the caller supplied a non-default value. Repeatable
ones go through `self._wire(value)` (R8). Always pass `.value` for enums into `httpx` params:
`httpx` calls `str()`, which gives `"TraceResolution.linked"`, not `"linked"`.


## Full-replace `replace` methods

Some PUT endpoints overwrite every field, setting unsent fields to `null` (traces, tests); their
methods are named `replace` (R3). Two rules:

1. **Send every field in the body, even when `None`.** Don't omit.
2. **Document the silent-clear footgun in the docstring** whenever you
   add a new optional field to an existing `replace` method, *and*
   call it out in the CHANGELOG `### Changed` section. Existing callers
   who don't know about the new field will silently null it on their
   next call.

Don't try to soften the contract with "preserve if omitted" sentinels;
that diverges from how every other field behaves on these methods. A PUT that leaves unsent
fields unchanged (users) is an `update` and sends only the fields given.


## Breaking changes

Until 1.0, breaking changes are allowed when they ship with an upgrade path. Every one needs:

1. A `### Upgrading` section in the CHANGELOG entry, with an old-to-new table.
2. A copy-paste migration prompt for coding agents in the same section, for any change bigger
   than a rename or two.
3. For a removed method or attribute, an entry in `_renames.REMOVED_IN`, so calling it raises an
   `AttributeError` that names the replacement. Entries are permanent.
   `tests/test_renames.py` checks each one against the client, the module and the CHANGELOG.

Removed *parameters* need no entry: Python's `TypeError` names them, and the CHANGELOG explains
the replacement.


## Output backends

`_frames.py` turns parquet bytes and lists of models into the container
the caller asked for. Resolution: per-call `output` > `Client(output=)` >
`sweatstack.set_output()` > the method's default: models for lists, and
for parquet the installed frame library (`_frames.installed_frame_output`:
Polars, then pandas, then Arrow; `ImportError` naming the extras if none).
A configured default a method cannot produce is skipped, a per-call one
is a `ValueError`. Never hard-code a frame library as a default.

**Where `output` belongs.** On the *data* endpoints only: activities,
traces, tests, dailies and the time series, the things a user groups,
filters and plots. Everything about the account, the app, teams, status
and the Portal (`oauth.userinfo`, `profile.status`, `portal.sessions.create`,
`whoami`, `users.list`, `teams.list`, `profile.sports`, `profile.tags`, ...) takes no `output` and always returns models; those
methods never call `_read_frame` or `_frame_from_models`, so a configured
output cannot reach them. A new data endpoint gets `output`; a new
control-plane endpoint does not.

Dtype policy: pandas gets `convert_to_standard_dtypes` (float64, ns);
Polars keeps wire dtypes except Float16 -> Float32; Arrow is the wire
table minus pandas index metadata; bytes is the body.

The Polars and Arrow paths for lists derive one type tree from each
model's **JSON Schema** (`_frames.field_types`) and render it per library;
values come from the instance.
**Never add a per-model special case there.** If a model needs one, the
JSON Schema grammar table in `_field_type` is missing a row: add the
row and its test. `tests/test_frames.py` turns `FrameSchemaWarning` into
a failure for every public model, so a regen that introduces an unknown
construct fails the suite, not a user's notebook.


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

Live in `tests/`. Offline only. Two workhorse patterns.

**Faking the transport** at `Client._request`, the one choke point, to see exactly what goes
on the wire:

```python
with patch.object(client, "_request", return_value=response) as request:
    client.activities.list(sport="cycling")
assert request.call_args.kwargs["params"]["sport"] == ["cycling"]
```

**Schema round-tripping:**

```python
restored = TraceDetails.model_validate(original.model_dump())
assert restored.test_id == "test_123"
```

Catches missing fields, type drift, and enum-casing changes from regen.
Exemplars: `tests/test_resources.py`, `tests/test_trace_test_linking.py`,
`tests/test_dtype_conversion.py`.


## CHANGELOG

User-facing only. Lead with what changed for the user; skip regen
output, file renames, refactors. Loud-callout any behaviour change in
`### Changed`, especially full-replace footguns. SemVer.

Good:

> ### Changed
> - `traces.replace()` replaces all fields, including `test_id`. Callers
>   that omit `test_id` will clear any existing link.

Bad (belongs in the commit message, not the changelog):

> ### Changed
> - Local datetime fields are now `AwareDatetime`. The
>   `BodyExpressAddEmail...` schema is renamed to
>   `BodyConnectAddEmail...`.


## When in doubt

- Match the nearest existing method in `resources/`. Consistency with the
  surroundings beats local cleverness.
- Reuse the helpers: `_request`, `_paginate`, `_wire`, `_enums_to_strings`,
  `_read_frame`, `_frame_from_models`, `_RecordAppMetadata`. Don't reinvent them.
- Don't add abstractions for hypothetical future flexibility. Three
  similar blocks is the pattern, not a smell.
