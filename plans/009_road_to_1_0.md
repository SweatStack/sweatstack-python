# Plan 009: Road to 1.0 (the roadmap)

This is the ordered plan for everything up to 1.0: the SDK's shape,
robustness and stability promise (designed here) and its documentation
(designed in [plan 008](008_sdk_documentation.md)). **All checklists live
here**, in milestone order. Plan 008 holds the docs design and has no
checklists of its own.

Proposed 2026-10-05, restructured 2026-10-06. Status per milestone below.

**Stance until 1.0.** Breaking changes are fine (one external user,
2026-10-05), as long as every one ships with an upgrade path:

1. a `### Upgrading` section in the CHANGELOG, with a table from old to new
2. a copy-paste migration prompt for coding agents in the same section
3. for a removed method, a runtime error that names the replacement (see
   "Renames" under M3)

From 1.0 the stability policy (M8) applies instead.


## Roadmap

| # | Milestone | Release | Status |
|---|---|---|---|
| M0 | Commit the preparation done on 2026-10-05 | — | ready |
| M1 | Docs hotfix: the live docs call APIs that don't exist | — | ready |
| M2 | Local checks: ruff, ty, `make check` gating `make publish` | — | ready |
| M3 | Namespaced API, `Client()` first, users and sport cleanup, `sweatlab` removed, skill rewritten | **0.91** | after M2 |
| M4 | Transport: connection reuse, timeouts, retries | **0.92** | after M3 |
| M5 | Snippet check shipped in the package; docs build runs it | 0.92.x | after M3 |
| M6 | Docs written once, against the new API | — | after M5 |
| M7 | Agent test (E1, then E2) | — | after M6 |
| M8 | 1.0: stability policy, going public, `llms.txt` | **1.0** | after M7 |

Why this order: the API changes first so the docs, the skill, the docstring
examples and the agent test are all written once. The snippet check is
built for the namespaced API only. The one exception is M1: the live docs
are wrong today, and a 30-minute fix beats weeks of `login()` failing.

Each milestone has a goal, a checklist, and a definition of done. Design
detail follows the checklist where it's needed; docs design is in plan 008.


## M0: Commit the preparation

**Goal.** Land the work of 2026-10-05 as one commit.

- [ ] Commit: cleaned plans 002–007, plans 008 and 009, AGENTS.md "Public
      repository" section, `tests/test_public_hygiene.py`, the skill moved
      to `skills/`, `.claude/` ignored, CHANGELOG and test edits. Message:
      "Prepare repository for going public".

**Done when** the commit is on `main` and `uv run pytest` is green (316
tests on 2026-10-05).


## M1: Docs hotfix (30 minutes)

**Goal.** Stop the live docs from teaching APIs that don't exist. No
tooling; find and replace in `../sweatstack.no/docs-dev`.

- [ ] `sweatstack.login()` → `sweatstack.authenticate()`
      (`learn/libraries/python/interfaces.md`, `.../authentication.md`,
      `guides/analyze-activity-data.md`).
- [ ] `as_dataframe=True` → `output="pandas"` (activities, dailies, tests,
      timezones, data-model, analyze guide).
- [ ] `learn/libraries/python/index.md`: "Timeseries come back as pandas
      DataFrames" and `uv add sweatstack` → install `sweatstack[pandas]` or
      `[polars]`; frames come back in the installed library.
- [ ] Deploy (`make deploy-docs`, by hand).

**Done when** the four pages' snippets run against SDK 0.90.

The flat names (`get_activities`, ...) stay in the docs for now; M3 removes
them from the SDK and M5/M6 fix every snippet with tooling.


## M2: Local checks

**Goal.** `make check` catches formatting, lint, type and test failures
before every commit, and nothing ships without it. Local only, no new CI
job; the existing CI (pytest, bare install) stays.

- [ ] `ruff` config in `pyproject.toml`: rules `E`, `F`, `I`, `B`, `UP`;
      exclude `openapi_schemas.py` (generated, its generator runs ruff).
- [ ] One formatting commit; add its hash to `.git-blame-ignore-revs`.
- [ ] `ty` pinned to an exact version in the `dev` group, default rules, on
      `src/`. Fix or explicitly ignore its findings.
- [ ] `tests/typing/test_output_types.py`: `typing.assert_type` on the
      `output=` overloads, checked by `ty`, not run by pytest. Confirm first
      that `ty` supports `assert_type` on overloads; if not yet, keep the
      file and enable it later.
- [ ] `Makefile`: `check: ruff format --check, ruff check, ty check, pytest`;
      `publish` depends on `check`.
- [ ] AGENTS.md: run `make check` before every commit.

**Done when** `make check` is green and `make publish` refuses to run
without it.

**Why ty, pre-1.0.** Accepted on 2026-10-05. Upgrading it is a deliberate
change: new diagnostics are fixed or ignored in the same commit as the
version bump.


## M3: Namespaced API (0.91)

**Goal.** `client.activities.list()` instead of `get_activities()`, with
names that follow from the URL by eight rules. Everything else that is
breaking and already decided ships in the same release, so there is one
upgrade, not four.

### Checklist (one commit each, `make check` green after every one)

- [ ] **Scaffolding.** `resources/_base.py` (a `Resource` holding its
      client). `Client` declares every resource at class level
      (`activities: Activities`, ...) so type checkers and the snippet check
      resolve them statically, and assigns them in `__init__`.
      `_renames.py` with `Client.__getattr__` and the module-level
      `__getattr__` (see "Renames"). Tests for both.
- [ ] **One commit per resource**, nine times: `activities` (with
      `longitudinal` and `app_metadata`), `traces`, `tests`, `dailies`,
      `profile`, `users`, `teams`, `portal`, `oauth`. Each commit: the new
      module with methods per R1–R8, `@overload` stubs, docstrings with the
      endpoint line and an `Examples:` block; that resource's tests moved to
      the new names; the mapping entries; the old methods deleted from
      `client.py`.
- [ ] **Removed methods** (no 1-to-1 replacement) get mapping entries with
      a hint: `get_latest_activity_data`, `get_latest_activity_mean_max`,
      `get_team_user`, `get_user`, `switch_user`, `switch_back`.
- [ ] **Internal callers** to the new names: `streamlit.py` (7 call sites),
      `fastapi/` (5). `StreamlitAuth.select_user()` swaps `auth.client` for
      a delegated client instead of calling `switch_user`. The FastAPI
      docstring recommends `user.client.delegated_client(...)`.
- [ ] **Remove `sweatlab` and `sweatshell`** (plan 008, D9): the two
      `[project.scripts]`, `jupyterlab_oauth2_startup.py`, `sweatshell.py`,
      `ipython_init.py`, `Sweat Stack examples/`, the `[jupyter]` extra.
- [ ] **Skill rewritten once**, short, against the new API (plan 008, D6):
      what agents get wrong (install extras, auth choice, `Client()` vs
      module level, `output=`, gotchas) and links to the docs for the rest.
      Install line pins `>=0.91`.
- [ ] **README**: `Client()` first; install; a 10-line quickstart; links.
      The long output/DuckDB/upgrade material moves to the docs in M6.
- [ ] **CHANGELOG 0.91** with `### Upgrading`: the rename table, parameter
      renames, behaviour changes, the removed commands, and the migration
      prompt. A test asserts every key of the rename mapping appears in the
      CHANGELOG.
- [ ] Run your own projects against the build; fix what breaks. Release.
      Tell the external user directly.

**Done when** no flat data method remains on `Client`; every removed name
raises an error naming its replacement; the CHANGELOG lists every rename;
the skill, README and internal callers use the new names; `make check` is
green.

### Naming rules

They go into AGENTS.md verbatim, replacing today's mirror table, so the
next endpoint has one obvious name.

| # | Rule | Examples |
|---|---|---|
| R1 | **The first URL segment after `/api/v1/` is the top-level namespace.** The 9 namespaces are exactly the server's segments. | `/activities/...` → `client.activities` |
| R2 | **Collection verbs follow Stripe:** `list`, `retrieve`, `create`, `delete`. | `GET /tests/` → `tests.list()`; `GET /tests/{id}` → `tests.retrieve(id)` |
| R3 | **Name writes by what they do, not by the HTTP verb.** A write that overwrites every field and clears what you leave out is `replace`. A write that changes only the fields you pass is `update`. Check the server: `PUT /traces/{id}` and `PUT /tests/{id}` overwrite everything; `PUT /users/{id}` leaves unsent fields unchanged (verified 2026-10-05). | `traces.replace(id, ...)`; `users.update(id, ...)` |
| R4 | **A single value that is set or cleared** (an upsert, or a blob with no ID) uses `set` and `delete`. | `dailies.set(measure, ...)`; `app_metadata.set(...)` |
| R5 | **A nested collection becomes a nested namespace**, with the parent ID as the first argument. | `portal.sessions.create(...)`; `activities.app_metadata.set(id, ...)` |
| R6 | **A sub-path that only supports a single `GET` becomes a method named after the noun.** | `activities.data(id)`; `profile.status()` |
| R7 | **An action endpoint (`POST .../<verb>`) becomes a method named after the verb.** | `activities.upload(...)`; `teams.authorize(id)` |
| R8 | **Parameter names are the wire names.** A repeatable query parameter takes one value or a list under the same name. One documented exception: `limit` and `offset` on list methods are SDK-level (see "Pagination"). | `sport="cycling"` or `sport=["cycling", "running"]`; `tags=["a", "b"]` |

Unchanged: path IDs positional, everything else keyword-only, enum
parameters accept `Enum | str`, `output=` on the data methods only.

`retrieve` rather than `get`: it's what Stripe, OpenAI and Anthropic use,
so it's what agents guess, and it doesn't clash with dict `.get`.

### The full mapping

The source of truth for this table is `_renames.py` (see "Renames"); the
CHANGELOG's upgrade table is checked against it.

| 0.90 | 0.91 |
|---|---|
| `get_activities(...)` | `activities.list(...)` |
| `get_activity(id)` | `activities.retrieve(id)` |
| `get_latest_activity(...)` | `activities.latest(sport=None)`, calling `GET /activities/latest` (today it pages the list and accepts `start`, `end`, `tag`) |
| `get_activity_data(id, ...)` | `activities.data(id, *, segmentation_on=, metrics=, output=)` (keyword-only now) |
| `get_activity_mean_max(id, metric, ...)` | `activities.mean_max(id, *, metric=, ...)` |
| `get_activity_awd(id, ...)` | `activities.awd(id, ...)` |
| `get_longitudinal_data(...)` | `activities.longitudinal.data(...)` |
| `get_longitudinal_mean_max(...)` | `activities.longitudinal.mean_max(...)` |
| `get_longitudinal_awd(...)` | `activities.longitudinal.awd(...)` |
| `upload(files, ...)` | `activities.upload(files, ...)`, with a typed return value |
| `get_backfill_status()` / `watch_backfill_status(...)` | `activities.backfill_status()` / `activities.watch_backfill_status(...)` |
| `set_activity_app_metadata` / `delete_activity_app_metadata` | `activities.app_metadata.set(id, data=)` / `.delete(id)` |
| `get_latest_activity_data(...)` | removed: `activities.data(activities.latest().id, ...)` |
| `get_latest_activity_mean_max(...)` | removed: `activities.mean_max(activities.latest().id, ...)` |
| `get_traces` / `create_trace` / `update_trace` / `delete_trace` | `traces.list` / `.create` / `.replace` / `.delete` |
| `set_trace_app_metadata` / `delete_trace_app_metadata` | `traces.app_metadata.set` / `.delete` |
| `get_tests` / `get_test` / `create_test` / `update_test` / `delete_test` | `tests.list` / `.retrieve` / `.create` / `.replace` / `.delete` |
| `set_test_app_metadata` / `delete_test_app_metadata` | `tests.app_metadata.set` / `.delete` |
| `get_dailies` / `set_daily` / `delete_daily` | `dailies.list(measure, ...)` / `.set` / `.delete` |
| `get_profile_status` / `get_sports` / `get_tags` | `profile.status()` / `.sports()` / `.tags()` |
| `set_user_app_metadata` / `delete_user_app_metadata` | `profile.app_metadata.set(data=)` / `.delete()` |
| `get_users()` | `users.list(include_managed=, include_shared=, name=)` |
| `get_user(user, search_mode=)` | removed: `users.list(name=...)` (see "Users") |
| — | new: `users.retrieve(id)`, `users.update(id, ...)`, `users.delete(id)`: managed users only, as on the server |
| `create_user(first_name, last_name)` | `users.create(*, first_name, last_name=None)` |
| `get_teams` / `get_team_users(team_id)` | `teams.list()` / `teams.users(team_id, name=None)` |
| `get_team_user(team_id=, user=)` | removed: `teams.users(team_id, name=...)` |
| `get_authorized_teams` / `authorize_team` | `teams.authorized()` / `teams.authorize(team_id)` |
| `create_portal_session(...)` | `portal.sessions.create(destination, ...)` |
| `get_userinfo` / `get_authorization_url` / `exchange_code_for_token` / `generate_pkce_params` | `oauth.userinfo()` / `.authorization_url(...)` / `.exchange_code(...)` / `.generate_pkce_params()` |
| `switch_user` / `switch_back` | removed: `delegated_client(user)` returns a new client; keep the original |
| `authenticate`, `whoami`, `delegated_client`, `principal_client`, `clear_cache` | unchanged, on `Client` |
| parameter `sports=` (lists, longitudinal) and `sport=`/`sports=` twins | `sport=`, one value or a list (R8). The server deprecates `sports` and already logs its use; the SDK already sends `sport` on the wire |
| date parameters, mixed `date | str` and `date` | `date` (or `datetime` where the server takes one), everywhere |

The module-level interface follows automatically: `sweatstack.activities`
is the default client's resource. `set_output()`, `enable_cache()` and
`authenticate()` are unchanged.

### Renames: the upgrade path at runtime

`src/sweatstack/_renames.py` holds one dict, old name → hint:

```python
REMOVED = {
    "get_activities": "client.activities.list()",
    "get_latest_activity_data": "client.activities.data(client.activities.latest().id)",
    "switch_user": "client.delegated_client(user), which returns a new client",
    ...
}
```

- `Client.__getattr__` and the package's module-level `__getattr__`
  (PEP 562) raise
  `AttributeError("Client.get_activities was removed in 0.91. Use client.activities.list(). See the CHANGELOG for 0.91.")`.
  `__getattr__` only runs when normal lookup fails, so there's no cost on
  the happy path.
- Tests: every key is absent from `Client` and the module; the error names
  the hint; every key appears in `CHANGELOG.md`.
- The dict is permanent and cheap. It's what turns an agent's stale
  training data into a self-correcting error instead of a dead end.
- Removed *parameters* (`sports=`, `search_mode=`) just raise Python's
  own `TypeError: unexpected keyword argument`, and the CHANGELOG explains
  them. No special handling.

### Longitudinal: nested under `activities`

| Option | For | Against |
|---|---|---|
| `activities.longitudinal_data(...)` | Mirrors each URL. | 13 members on `activities`; a shared prefix is a namespace waiting to happen. |
| `client.longitudinal.data(...)` | Shortest. | Breaks R1: the only top-level name that isn't a URL segment. "Longitudinal" means nothing without "activities". |
| **`client.activities.longitudinal.data(...)`** | Keeps R1. Lines up with `activities.data(id)`, `.mean_max`, `.awd`. | The longest call in the SDK; autocomplete absorbs it. |

Decided 2026-10-05: nested.

### Combined methods: dropped, IDs everywhere

Every method that acts on an activity takes its ID, so the full object is
never needed first:

```python
from sweatstack import Client

client = Client()
latest = client.activities.latest()
df = client.activities.data(latest.id, output="polars")
df = client.activities.data("01HF...", output="polars")   # an ID you already have
```

Rejected: methods on the model objects (`latest.data()`). The models are
generated Pydantic classes; binding a client to them breaks serialisation
and is ambiguous under delegation. Stripe dropped that style too.

### Pagination

`limit` on list methods is **the number of items you get**, not the
server's page size: the SDK fetches pages of 100 internally until it has
`limit` items (verified in `_get_activities_generator`, 2026-10-06).
`offset` is where to start. Keep these semantics; the earlier idea of
changing the default to the server's 50 would have silently halved what
callers get. Document them in every `list()` docstring and as the R8
exception.

### Users

Verified in the server code, 2026-10-05. A coach, Anna, signed in:
**herself**; **managed users** she created (Bob, no login of his own);
**shared users** with their own account who granted her access (Carla).

| Endpoint | Returns | Who |
|---|---|---|
| `GET /users/` | `UserSummary` list: Anna, Bob, Carla, with `scopes` and `is_managed`; filters `include_managed`, `include_shared` | everyone accessible; no delegated tokens |
| `POST /users/` | a new managed user | you become the manager |
| `GET /users/{id}` | `UserResponse` | **managed users only**: Bob works; Carla and Anna give 404 |
| `PUT /users/{id}` | `UserResponse`; **partial** | managed users only |
| `DELETE /users/{id}` | deletes the user and all their data | managed users only |

Today's `get_user` never calls `GET /users/{id}`; it searches the list in
Python by ID or by part of the name, and `get_user("Carla")` fails where
`"carla"` works (bug: only the stored name is lowercased).

```python
client.users.list()                                # Anna, Bob, Carla
client.users.retrieve("usr_bob")                   # Bob
client.users.retrieve("usr_carla")                 # SweatStackNotFoundError: not a managed user
client.users.update("usr_bob", last_name="Smit")   # partial (R3)

client.users.list(name="carl")                     # [Carla Jansen, Carlos Bakker]: every match, [] if none
client.teams.users("team_1", name="carla")         # the same, within a team

matches = client.users.list(name="carla")
if len(matches) != 1:
    raise ValueError(f"Expected one user matching 'carla', found {len(matches)}")
athlete = client.delegated_client(matches[0])      # a UserSummary or an ID
```

- **`name=` is a filter on the list methods** (decided 2026-10-05). It
  returns every match, so an ambiguous search can't silently pick one.
- **The SDK doesn't wait for the server.** It sends `name` *and* filters
  the response itself. The server ignores unknown query parameters today,
  and filtering an already-filtered list changes nothing, so there's no
  version check. Once the server supports it, drop the client-side filter
  in a later minor release.
- **Meaning, fixed now:** case-insensitive match on any part of
  `display_name`. A unit test pins it. **Server request:** `GET /users/`
  and `GET /teams/{team_id}/users` accept `name` with this meaning.
- `whoami()` keeps working from the token and the list (plan 007).

### Structure

```
src/sweatstack/
├── client.py              # Client: config, auth, delegation, resource wiring
├── _renames.py            # REMOVED mapping + the two __getattr__ helpers (permanent)
├── _transport.py          # M4: the HTTP client, retries, timeouts, _raise_for_status
├── resources/
│   ├── _base.py           # Resource; AppMetadataById (activities, traces, tests); ProfileAppMetadata
│   ├── activities.py      # Activities, Longitudinal
│   └── traces.py  tests.py  dailies.py  profile.py  users.py  teams.py  portal.py  oauth.py
```

Two app-metadata classes, not one with an optional ID: the profile's has
no ID and the others require one.

**Docstrings.** Every resource method's docstring has, after the summary
line, its endpoint: `GET /api/v1/activities/{activity_id}`. A test asserts
every public resource method has exactly one such line, with a short
allowlist for methods without an endpoint (`watch_backfill_status`, the
OAuth helpers). This replaces the generated endpoint table in plan 008:
the information sits where people and mkdocstrings read it.

### Tests

- Each resource commit moves that resource's tests to the new names; no
  test is deleted without a replacement.
- `tests/test_renames.py`: absence, error message, CHANGELOG coverage.
- `tests/test_public_surface.py` updated: the public surface is the nine
  resources plus the client-level methods; the module level mirrors it.
- `tests/test_endpoints.py`: the docstring endpoint line.
- Users: the `name` filter semantics; `retrieve` maps 404.


## M4: Transport (0.92)

**Goal.** Connection reuse, configurable timeouts, safe retries. Modelled
on the OpenAI, Anthropic and Stripe clients.

### Checklist

- [ ] `_transport.py`: **one `httpx.Client` per `Client`**, created lazily
      (today every request opens a new one, verified 2026-10-06).
      `Client.close()` and context-manager support. `delegated_client()`
      gets its own.
- [ ] **Token refresh under a lock**, so two threads can't refresh at once.
- [ ] `Client(timeout=60.0, max_retries=2)`: a float in seconds, no `httpx`
      types in the public API. Both propagate through `delegated_client()`
      and `principal_client()`, as `output` does.
- [ ] The streaming endpoint (`watch_backfill_status`) uses no read timeout;
      it already has `auto_reconnect`.
- [ ] Retry policy (table below), with a total budget.
- [ ] Each retry logged at `DEBUG` on the `sweatstack` logger: method,
      path, status, attempt, request ID.
- [ ] Tests on `httpx.MockTransport`: retry per status, no retry on POST,
      backoff bounds, `Retry-After`, budget, DELETE-then-404, propagation,
      refresh lock, stream timeout, `close()`.
- [ ] CHANGELOG with the new parameters and `max_retries=0` for
      latency-sensitive apps.

**Done when** a loop of 100 `activities.retrieve` calls reuses one
connection (observable in `DEBUG` logs), and the tests above are green.

### Retry policy

| | Behaviour |
|---|---|
| What is retried | Connection errors, timeouts, and 408, 429, 500, 502, 503, 504 |
| Which requests | `GET`, `PUT`, `DELETE` only. **Never `POST`**: no server idempotency keys, so a retried `traces.create` could create two traces |
| DELETE | A 404 on a *retried* DELETE counts as success: the first attempt may have gone through |
| Backoff | 0.5 s × 2ⁿ, ±25 % jitter, at most 8 s per wait. `Retry-After` honoured up to 60 s |
| Budget | At most 30 s of waiting per call in total. Beyond it, raise. Web apps should set `max_retries=0` or a short `timeout` |
| On exhaustion | The last typed exception (`SweatStackRateLimitError` with `retry_after`, `SweatStackServerError`, `SweatStackConnectionError`), so existing `except` clauses keep working |
| Streams | Not retried mid-stream |

Deferred: `client.with_options(...)`. It needs token state shared between
client objects, which the current design doesn't have. Add it when someone
needs per-call settings.


## M5: Snippet check (0.92.x)

**Goal.** Every Python snippet in the docs, the README, the skill, the
examples and the docstrings is checked against the real SDK, so docs can't
drift again. Design: plan 008, "The checker".

### Checklist

- [ ] `src/sweatstack/_docs.py`: `python -m sweatstack._docs check <paths>`.
      Stdlib only, never imported by `sweatstack/__init__.py`, private.
- [ ] Resolution follows the namespaces: `sweatstack.activities.list`,
      `client.activities.longitudinal.data`, `auth.client.users.list`,
      resolved through the class-level annotations from M3.
- [ ] This repo's tests run it on `README.md`, every docstring `Examples:`
      block, `skills/`, and `examples/*.py`.
- [ ] `../sweatstack.no`: `build-docs` runs
      `uv lock --upgrade-package sweatstack`, then the check, then
      `mkdocs build --strict`. Removes the 0.86 pin.
- [ ] Release 0.92.x so the docs build can install it.

**Done when** `make build-docs` in the docs repo fails and lists every
snippet still using 0.90 names. That list is M6's work list.


## M6: Docs, written once

**Goal.** The docs described in plan 008, against the 0.92 API. Design,
structure and page list: plan 008 ("Information architecture", "Where
each piece of content lives").

### Checklist

- [ ] Fix everything M5's check reports.
- [ ] Learn › Python SDK section: Overview, Authentication, Clients, Data
      output, Errors, Configuration, Streamlit, FastAPI, Guides, Upgrading,
      Changelog, Reference. Frameworks folded in; CLI moved to Tools;
      Jupyter page deleted; 301s for every moved URL.
- [ ] Reference: one page per resource class, one `:::` line each, plus
      Client, Models and enums, Exceptions.
- [ ] Upgrading page: the 0.91 and 0.92 upgrade paths from the CHANGELOG,
      newest first.
- [ ] Changelog page: a build hook reads `../sweatstack-python/CHANGELOG.md`
      from the sibling checkout and fails loudly if it's missing. Switch to
      the GitHub raw URL once public (M8).
- [ ] `Client()` first on every page; the module-level interface presented
      as a notebook convenience, with the reason.
- [ ] Concept pages keep their Python tabs; nothing generic is explained
      twice (plan 008, D2).
- [ ] Python guides, 3–5 (plan 008, M6 list): analyse a season, run
      unattended, coach workflows, write data back, errors and rate limits.
- [ ] `pyproject.toml` `[project.urls]`: `Documentation` → Python SDK
      Overview; `Changelog` and `Issues` added at M8.
- [ ] Docs repo AGENTS.md rules (plan 008, "Rules").

**Done when** `make build-docs` passes in strict mode with the check; no
Python-only content remains outside the Python section; the AI coding
page's claims are true.


## M7: Agent test

**Goal.** Know whether a coding agent succeeds with our SDK, skill and
docs, see where it stumbles, and catch regressions. A pydantic-ai
reference agent with our skill, evaluated with pydantic-evals. Only
`ANTHROPIC_API_KEY` is needed.

### E1 checklist (the useful core)

- [ ] `evals` dependency group: `pydantic-ai-slim[anthropic]`,
      `pydantic-ai-harness[skills]`, `pydantic-evals`, `logfire`, **all
      pinned to exact versions** (harness is 0.x and moves fast).
- [ ] `evals/agent/agent.py`: the agent (below).
- [ ] `evals/agent/cases.py`: the six cases, each with its judge rubric.
- [ ] `evals/agent/run.py`: the task function (workspace, run, execute),
      the lifecycle (managed user "SDK eval", cleanup, keep failed
      workspaces), the evaluators, `report.print(include_reasons=True)`.
- [ ] Confirm the three documented-but-untested details (below) first.
- [ ] One run; read the reasons; file what you find as fixes.

**Done when** `uv run --group evals python evals/agent/run.py` runs all six
cases unattended and prints a report whose reasons name concrete friction.

### E2 checklist (only once E1 has proven useful)

- [ ] `--repeat N`, `--without-skill`, `--model`.
- [ ] Redacted results in `evals/agent/results/<sdk>-<model>-<date>.json`
      (assertions, scores, metrics; no outputs or reasons). Baselines are
      per model; a model change makes old results incomparable.
- [ ] `--save-baseline`; regression check: a case whose pass rate dropped
      by more than one run in three exits non-zero.
- [ ] Before every minor release: `--repeat 3`.

### The agent

```python
from pydantic_ai import Agent
from pydantic_ai.capabilities import WebFetch
from pydantic_ai_harness import FileSystem, Shell, Skills

def build_agent(workspace: Path, *, model: str, with_skill: bool) -> Agent[None, str]:
    capabilities = [
        FileSystem(root_dir=workspace),                 # write the code
        Shell(cwd=workspace, allowed_commands=["uv"]),  # uv add / uv run
        WebFetch(),                                     # docs.sweatstack.no, openapi.json
    ]
    if with_skill:
        capabilities.append(Skills(workspace / ".agents/skills"))
    return Agent(model, instructions=INSTRUCTIONS, capabilities=capabilities)
```

- The skill is copied into the workspace. `Skills` loads only `SKILL.md`
  into context; the agent reads the reference files next to it with
  `FileSystem`, as Claude Code does.
- `INSTRUCTIONS` are short and say nothing about SweatStack: write the
  solution in the named file, run it with `uv run`, stop when it works.
- The workspace is a `uv init` project with **this working tree** of the
  SDK as an editable dependency.
- `Shell` allowing only `uv` is a guardrail, not a security boundary;
  `uv run` runs whatever the agent wrote. Acceptable on your own machine;
  writes go to the "SDK eval" managed user and are deleted afterwards.
- A `UsageLimits` request limit stops a stuck agent.
- Logfire with `send_to_logfire=False`: traces stay local; they're what
  the agentic evaluators read.

### Evaluators

| Evaluator | Result |
|---|---|
| `Runs` (custom) | scripts exit 0 within the timeout; `{}` for apps |
| `ProducesFiles` (custom) | expected files exist (e.g. `plot.png`) |
| `CurrentApi` (custom) | `python -m sweatstack._docs check` passes on the generated code; the reason lists each finding |
| `ClientInApps` (custom, `ast`) | app and coach cases use `Client()` / `auth.client`, never module-level functions |
| `FailedCommands` (custom, from the trace) | each `uv run` that errored, with the first lines of its error |
| `MaxToolCalls`, `MaxModelRequests` (built-in) | step budgets |
| `HasMatchingSpan` (built-in) | loaded the skill, read its files, fetched the docs: information, not pass/fail |
| `LLMJudge` per case (built-in) | numbered rubric, `include_input=True`, temperature 0, pinned judge model |
| report evaluators | `PassRate`, `PassRateTable` per case and check, total `Cost` |

**The reasons are the point.** `CurrentApi`, `FailedCommands` and
`LLMJudge` explain each failure; that's where friction turns into fixes.

### Cases

1. `recent_activities`: my 5 most recent activities with date, sport, duration.
2. `latest_ride_plot`: power over time for my latest ride, Polars, `plot.png`.
3. `mean_max_90d`: my power mean-max curve over the last 90 days of cycling.
4. `streamlit_login`: Streamlit app with Sign in with SweatStack showing the
   user's last 10 activities (not run; judged on the code).
5. `coach_weekly_volume`: weekly volume per athlete I coach, last 4 weeks,
   one DataFrame.
6. `lactate_test`: for "SDK eval", a lactate test with two markers and a
   linked trace.

### To confirm first

- `WebFetch` can be limited to docs.sweatstack.no and app.sweatstack.no.
- `HasMatchingSpan` and the agentic evaluators see the harness's tool
  calls with Logfire local-only.
- The agent's program finds the saved SweatStack login from a subprocess
  (tokens live under `platformdirs.user_data_dir`, so `HOME` must pass
  through `Shell`).

### Data handling

Your data reaches the model API through the agent's tool output and the
judge, under your own key. Full reports and kept workspaces stay in the
git-ignored `evals/agent/runs/`. Committed results are redacted. The repo
is public; see AGENTS.md.


## M8: 1.0

**Goal.** The stability promise, and the repo public with the stable API
as its first impression.

### Checklist

- [ ] **Gate:** the external user has migrated (confirmed by contacting
      them); M7 E1 is green; M6 is done.
- [ ] Publish the stability policy (below) on the docs' Upgrading page and
      in AGENTS.md.
- [ ] Go public: the remaining items of plan 008 "Going public" (gitleaks
      over the full history, tidy the surface, flip visibility,
      `[project.urls]` `Changelog` and `Issues`, GitHub Release per version,
      `sweatstack-skills` README row, reinstall the local projects from
      GitHub, restore the AI coding page's skills claim).
- [ ] Changelog hook switches from the sibling checkout to the GitHub raw
      URL.
- [ ] `llms.txt` (plan 008, D8; any time after M6).
- [ ] Release 1.0.

**Done when** an outsider can `npx skills add SweatStack/sweatstack-python`,
read the source and changelog, open an issue, and rely on the policy.

### Stability policy (from 1.0)

- **Semantic versioning.** Breaking changes only in a major release.
  Breaking means changes to: names in `__all__` and the namespaces; method
  names, positional order and keyword names; return and exception types;
  frame column names per `output`. **`StreamlitAuth` and the
  `sweatstack.fastapi` helpers are covered.**
- **Not breaking:** new methods, optional parameters, model fields, enum
  values (the open enums tolerate them), dtypes that only widen.
- **Deprecation before removal:** `typing_extensions.deprecated(...,
  category=FutureWarning)` on the old name (editors show it; the warning
  shows everywhere, unlike `DeprecationWarning`, which Python hides outside
  `__main__`), for at least one minor release and three months. Removed in
  the next major release; then the `_renames.py` error names the
  replacement.
- **Beta surfaces are exempt and labelled** ("Beta: may change in a minor
  release"): today the Portal, profile status and `userinfo.issue`.
- **The SDK absorbs server changes.** A response-shape change the SDK can't
  absorb waits for a major release.
- **Python versions:** supported until end of life; dropping one is a
  minor release.
- **Not covered:** names starting with `_`; importing from
  `sweatstack.openapi_schemas` directly.

### Non-goals for 1.0

Deliberately out, so nobody wonders whether they were forgotten: an async
client; `with_options`; idempotency keys (needs the server); pagination
beyond today's internal paging; docs URLs in exception messages; demo
data, a live smoke test and docs analytics (dropped 2026-10-05).


## Rules to add to this repo's AGENTS.md

With M2:
- Run `make check` before every commit; `make publish` runs it anyway.

With M3:
- Replace the mirror table with R1–R8 and the method template with a
  resource method. R8 removes the `sports=` exception from "Deliberate
  deviations"; the only exception is `limit`/`offset`.
- "Public methods belong in `_generate_singleton_methods`" becomes "public
  resources are class-level attributes of `Client`; the module level
  mirrors them automatically".
- "`update_*` methods are full-replace" becomes R3.
- Every public method's docstring has the endpoint line and an `Examples:`
  block.
- **A breaking change ships with its upgrade path:** CHANGELOG `###
  Upgrading` with the old-to-new table, the migration prompt, and a
  `_renames.py` entry for every removed method.
- A change to the public surface updates `skills/sweatstack-python/` in the
  same commit.

With M4:
- Never retry a request the server can't safely repeat (`POST`).

With M8:
- The stability policy.
- Release checklist: `make check`, bump the skill's version pin, GitHub
  Release from the CHANGELOG section, rebuild and deploy the docs.


## Effort

| Milestone | Estimate |
|---|---|
| M0, M1 | 1 hour |
| M2 | ½–1 day |
| M3 | 2–4 days; the mapping table makes the moves mechanical, and there are no wrappers to write |
| M4 | 1–1½ days |
| M5 | 1 day |
| M6 | 2–3 days plus about a day per guide |
| M7 | E1: 1 day. E2: ½ day |
| M8 | 1 day |


## Rejected

| Idea | Why not |
|---|---|
| Keep the flat names | They grow with every endpoint, mix resource and verb inconsistently, and match no convention agents know. |
| Deprecated wrappers for every old name in 0.91 | Breaking is acceptable pre-1.0 (2026-10-06). Wrappers would be written, tested and then deleted; the `_renames.py` errors plus the CHANGELOG give the upgrade path for a fraction of the cost. |
| `limit` defaulting to the server's 50 | `limit` is an SDK-level total with internal paging; changing it would silently halve results (2026-10-06). |
| `get` instead of `retrieve` | Diverges from Stripe, OpenAI and Anthropic. |
| Naming writes after the HTTP verb | Our PUTs differ: traces and tests overwrite, users don't. |
| `client.longitudinal` at top level | Breaks R1 to save one segment. |
| Methods on model objects | Breaks serialisation of generated models; ambiguous under delegation. |
| `users.search(name)` | A method name for an endpoint that doesn't exist; `users.list(name=)` mirrors the requested filter. |
| Dropping name search | The `next(...)` one-liner raises `StopIteration` on no match and silently picks the first of several. |
| Keeping `switch_user` | Hidden state on a shared object; `delegated_client` does the job. |
| Retrying POST | Duplicates without idempotency keys. |
| `with_options` now | Needs shared token state; deferred. |
| A generated endpoint ↔ method table | Once names follow R1–R8 it adds little; the docstring endpoint line plus a test is simpler. |
| CI for lint and types | Local `make check` gating `make publish` is enough for one maintainer. |
| pyright | `ty` chosen, pinned, upgraded deliberately. |
| Claude Code as the test agent | Needs the CLI, hard to observe from a script, invisible to pydantic-evals. |
| A plain script for the agent test | Reinvents repeats, retries, lifecycle, baselines and the report. |
| Agent-test baseline on 0.90 before M3 | Would delay the redesign behind the most fragile tooling, for one before-and-after measurement. |
| `sports=` kept as the Python name | The server deprecated it; one name, the wire name (R8). |
