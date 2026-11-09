# Plan 012: Who wrote a record, and which platform it came from

## Status

- **READY, 2026-11-09.** Mirrors a server release that is planned but not yet live. Every server
  fact below was checked against the server's public contract as it will be after that release,
  not as it is today. Where today's production differs, both are given.
- **Ships as 0.99.0**, a breaking minor, on the day of the server release and after it. See
  [Release](#release).
- **Effort:** under a day, plus a short release-day step.
- **Process:** red-green. Write the tests in [Tests](#tests) first.
- **One server decision is still open: whether the upload keeps its `replace` flag.** It has been
  proposed to the server to drop the flag and tell a retry from a correction by the file's bytes
  (see [Relaying files](#relaying-files)). The plan assumes the flag goes and says exactly what to
  do if it stays (S11). Commit 2's regen shows which, so nothing waits on it before then.

> **Public repository.** This file is published with the code. It describes the server by its
> public contract (the OpenAPI document and docs.sweatstack.no) and names no app, no user and
> nothing learned from server traffic (AGENTS.md, "Public repository").

## Summary

Until now one field answered two questions. `DailyResponse.source` and `SourceResponse.origin`
said `manual`, `application` or `garmin_connect`, and the last value meant both "SweatStack's sync
wrote it" and "it came from Garmin". That works until an app relays Garmin data: the writer is then
the app and the platform is Garmin, and one field cannot hold both.

After the server release, every record a writer creates carries the same three fields:

| Field | Type | Meaning |
|---|---|---|
| `writer` | `WriterKind`: `athlete`, `application`, `sweatstack` | Who is accountable for the write. Comes from the token; no request can set it. **A closed set.** |
| `application_id` | `str \| None` | Which app, when the writer is `application`. |
| `platform` | `str \| None` | The platform the data came from: `garmin_connect`, `strava`, ... or none. **An open set**: a plain string, stored and echoed in one canonical spelling. |

The five cases this model distinguishes (today's model can express three of them):

| Case | `writer` | `application_id` | `platform` |
|---|---|---|---|
| The athlete types a value or uploads a file | `athlete` | `None` | `None` |
| SweatStack's own Garmin sync | `sweatstack` | `None` | `"garmin_connect"` |
| An app relays Garmin data | `application` | `"app_123"` | `"garmin_connect"` |
| An app computes its own value | `application` | `"app_123"` | `None` |
| The athlete imports a Strava export through this SDK's sign-in | `athlete` | `None` | `"strava"` |

## The server contract this mirrors

The server's next release is breaking. As it will appear in its OpenAPI document:

**Responses.** `DailyResponse`, `SourceResponse`, `MarkerRowResponse` and `MaxEffortRowResponse`
carry `writer`, `application_id` and `platform`. `source`, `origin` and `provider` disappear from
them, and `DailySource` and `SourceOrigin` disappear from the document. On `DailyResponse`, `writer`
is optional and is set only on a stored day. An `estimated` or `missing` day has no writer, so all
three fields are `null`, just as `source` was. On the other three models, `writer` is required.

**Requests.** These writes take an optional `platform`: the upload form (`POST /activities/upload`),
`POST /dailies/{measure}` and its `/batch`, `POST /profile/markers` and `POST /profile/max-efforts`.
Who may send it:

| The client's token | Writer recorded | `platform` |
|---|---|---|
| Issued to an app (a client ID of the developer's own) | `application`, with that app's ID | accepted |
| Issued to one of SweatStack's own clients: this SDK's `authenticate()` sign-in | `athlete` | accepted |
| A personal API key from SweatStack's settings, or a web session | `athlete` | **`422`**, never ignored |

A platform name must match `^[a-z][a-z0-9_]{0,39}$`, or the server returns a `422` whose message
states that rule. A known alias resolves to its canonical name, so `"garmin"` is stored and read
back as `"garmin_connect"`. An unknown name of the right shape is stored as given. The upload
form's `provider` field goes away with no alias, and `platform` replaces it.

### Relaying files

The upload also takes `external_id`, which production already accepts and the SDK doesn't send
yet. It is for an app that relays files it received from another platform: the app's own ID for
each file, one per file in the files' order. It needs a token issued to an app, and any other token
gets a `400`. The number of IDs must equal the number of files, or the server returns a `422`. The
source echoes the ID back as `SourceResponse.external_id`.

When a file comes again with an `external_id` the server has seen from that app:

- **Same bytes**: it is a retry. The existing source comes back untouched.
- **Different bytes**: it is a correction. The server processes the new file under the same source
  ID. The source's old activities are deleted (each with an `activity_deleted` webhook) and new
  ones, with new IDs, take their place.

So retrying a lost upload is always safe. This is the contract proposed for the coming release.
Today's production instead keeps the source unless the request also sends `replace=true`, and that
flag goes if the proposal is accepted (S11 covers both outcomes).

### What a writer may replace

**It does not change.** The athlete and an app may replace anything. A sync
replaces only what a sync wrote. The platform never affects this. So the `dailies.set()` docstring
"A value you set is never overwritten by an integration import" stays true.

## Where the SDK starts from

The bundled `openapi_schemas.py` is older than today's production as well as the coming release.
Regenerating from today's production document gives about 180 changed lines that have nothing to
do with this plan: `DailySource.application`, `SourceOrigin.application`,
`SourceResponse.application_id`, `external_id` and `provider`, `DailyResponse.application_id`, the
upload form's `external_id`, `provider` and `replace`, the daily batch models, app-managed users,
connection declarations, and more. That backlog must not land inside this plan's diff
(DEVELOPMENT.md, "Regenerating", step 5), so it lands first as its own commit. See
[Commits](#commits).

Two consequences of starting from an old schema:

- **0.98 never had `SourceResponse.provider` or `DailySource.application` as typed fields.** No SDK
  user can have code that reads them through the model, so the Upgrading table has no rows for
  them.
- **0.98's `DailySource` is an open enum** (`schemas.py`, `_open_enum`). An `application` value in
  production today parses as a pseudo-member. That registration goes along with the enum.

## Decisions

| | Decision | Why |
|---|---|---|
| S1 | **Mirror the three fields as generated. No derived `source`, no shim.** | AGENTS.md: "Don't add compatibility shims". A derived field would keep two vocabularies alive in users' code and in the docs, which is exactly what the server release removes. |
| S2 | **`WriterKind` is closed: not registered with `_open_enum`.** `DailySource` leaves the open-enum list. | The server documents `WriterKind` as closed. Three principals is a fact of the model, and a fourth would be a breaking release, not a routine addition. AGENTS.md: "Leave closed sets strict." `platform` is a `str` and is open by type, so it needs nothing. |
| S3 | **`platform=` on the two write methods the SDK has**: `dailies.set(measure, *, date, value, platform=None)` and `activities.upload(files, *, platform=None)`. Keyword-only, wire name, and `None` sends nothing (R8). | They are the SDK's only methods for the writes that take it. The batch, marker and max-effort writes have no SDK method today, and adding them is a separate change (see [Not doing](#not-doing)). |
| S4 | **The SDK does not validate or normalise a platform name.** It sends the string as given, and the server's `422` is the message. | The server owns the pattern and the alias table, and both will grow. A client-side copy would drift from them, and an SDK that refuses a name the server accepts is worse than no check. |
| S5 | **On upload, one `platform` per call covers every file.** It is sent once, as a multipart form field next to the files, in the call's single request. | That is the wire shape: one form field per request. Files from different platforms need separate calls, and the docstring says so. |
| S6 | **Docstrings describe the token, not the `Client` argument.** In this SDK, `api_key=` holds whatever access token the client was given, so "an API key is refused" would mislead. They say instead: accepted with a token from `authenticate()` or one issued to your app, refused with a personal API key from SweatStack's settings. | The outcome depends on where the token came from, and a user knows that, not which argument they passed it through. |
| S7 | **A `_renames` entry for `DailySource` only, not for `SourceOrigin`.** | `_renames` turns a removed *public* name into an error that names its replacement. `sweatstack.DailySource` was public (exported since 0.98). `SourceOrigin` was never exported, only reachable through `sweatstack.openapi_schemas`, so a hint for `sweatstack.SourceOrigin` would describe a name that never existed. The CHANGELOG covers it. |
| S8 | **The SDK never retries an upload by itself, even with `external_id`.** The docstring tells the caller that retrying with the same IDs is safe. | AGENTS.md: a `POST` is sent once, with no per-method retry logic. Whether a retry is wanted is the caller's decision. The server's contract makes that decision safe. |
| S9 | **The feature commit lives on a branch until the server release is live.** Nothing is released from `main` while `main` carries a schema production doesn't serve. | 0.99's `SourceResponse` requires `writer`, so it cannot parse today's production. A patch release cut from `main` in between would break every upload. |
| S10 | **`external_id=` on `activities.upload()`: one string or a list, matched to `files` by position.** It goes through `_wire` and is sent as a repeated form field, and only when given. The SDK doesn't check that the counts match: the server's `422` says so (as S4). | R8: a repeatable parameter takes one value or a list under the wire name. A single string for a single file reads naturally: `upload("ride.fit", external_id="12345")`. It ships with `platform=` because a relaying app needs both. |
| S11 | **`replace` follows whichever contract ships.** If commit 2's regen shows the upload form without `replace` (the expected outcome), there is nothing to mirror. If the form still has it, mirror it: `replace: bool = False`, keyword-only, sent only when `True`. Its docstring says it applies only with `external_id`, and that it deletes the source's activities and creates new ones with new IDs. The [Relaying files](#relaying-files) wording then becomes "a known ID returns the existing source unless `replace=True`". | The SDK mirrors the API (AGENTS.md) and does not redesign it. The client-side burden this flag creates is the server's to remove, and that has been proposed. Hiding a parameter the server still has would make a correction impossible from the SDK. |

## Changes

### Commit 1: regenerate from today's production (lands now, on `main`)

1. `uv run generate-response-models` against a server that serves **today's production document**
   (DEVELOPMENT.md). Production's document as of 2026-11-09 is version 0.154.2.
2. Wire-name check: `SWEATSTACK_OPENAPI_JSON=... uv run pytest tests/test_wire_names.py`. Against
   that document it reports two methods:
   - `Activities.upload`: `external_id`, `provider`, `replace`. Add
     `"Activities.upload": {"external_id", "replace", "provider"}` to `NOT_EXPOSED`, with the
     comment "file relay: mirrored in plan 012, commit 2". The entry is temporary, and commit 2
     removes it.
   - `OAuth.authorization_url`: `login_hint`. **Not this plan.** Mirror it in its own small
     change before or after. It must not ride along here.
3. `make check`. The existing tests must pass unchanged. If one fails, the backlog contains a
   breaking change that needs its own CHANGELOG line. Stop and write that line; don't fix the test
   quietly.
4. CHANGELOG under `## [Unreleased]`, **Added**: `DailyResponse.application_id` (also a new
   column of the `dailies.list()` frames, which `tests/test_dailies.py` and `tests/test_output.py`
   pin), `SourceResponse.application_id` and `SourceResponse.external_id`. That keeps `main`
   accurate if anything is released before commit 2. Commit 2 folds these lines into its own entry.
   `provider` and `DailySource.application` get no line: commit 2 removes them.

### Commit 2: writer and platform (branch `writer-and-platform`)

1. **Regenerate** from a local server running the release's code. The expected diff is exactly the
   contract above:
   - `WriterKind` (`athlete`, `application`, `sweatstack`) appears. `DailySource` and
     `SourceOrigin` go.
   - `DailyResponse` gains `writer: WriterKind | None = None` and
     `platform: str | None = None` (it already has `application_id`) and loses `source`.
   - `SourceResponse` gains `writer: WriterKind` (required) and `platform` and loses `origin` and
     `provider`.
   - `MarkerRowResponse` and `MaxEffortRowResponse` gain `writer` and `platform` and lose `source`.
   - The upload form, `DailyCreate`, `DailyBatchCreate`, `MarkerWrite` and `MaxEffortWrite` gain
     `platform`. The upload form loses `provider`, and (expected, S11) `replace`.

   Anything else in the diff is a server change outside this plan. Commit it separately, as in
   commit 1.
2. **Exports.** `schemas.py` and `client.py` (its import and `__all__`) re-export `WriterKind`
   where they now re-export `DailySource`. Remove `DailySource` from `_open_enum`'s list in
   `schemas.py`, and change that function's docstring from "sources of a value" to the open sets
   that remain. Check that nothing re-exports `SourceOrigin` (true on 2026-11-09).
3. **`_renames.REMOVED_IN`**, under a `# 0.99` comment:
   `"DailySource": ("0.99", "sweatstack.WriterKind (a record's writer) and its platform field (where the data came from)")`.
   The hint names `sweatstack.` literally rather than `{c}.`, because `WriterKind` is a
   module-level name, never `client.WriterKind`. Know the limit: the hint reaches
   `sweatstack.DailySource`, while `from sweatstack import DailySource` raises Python's plain
   `ImportError` without it. UPGRADING.md, step 4, already says so, and the Upgrading table has the
   row.
4. **`dailies.set(..., platform=None)`.** The body is
   `{"date": ..., "value": ..., "platform": platform}`, with `"platform"` present only when it is
   not `None`. Docstring:
   - `Args: platform:` "Where the value came from, when another platform measured it:
     `"garmin_connect"`, `"strava"`, ... Leave it out for a value you measured or entered yourself.
     It is accepted with a token from `authenticate()` (the value's writer is then `athlete`) or one
     issued to your app (`application`), and refused with a personal API key from SweatStack's
     settings. The server stores the canonical spelling: `"garmin"` reads back as
     `"garmin_connect"`."
   - `Returns:` "The stored value, with its `writer`, `application_id` and `platform`."
   - `Raises: SweatStackBadRequestError:` "If `platform` is not a platform name (a lower-case
     letter, then up to 39 lower-case letters, digits or underscores), or the token may not name
     one."
   - Keep the `Examples:` block as it is: a plain call is the common case.
5. **`activities.upload(files, *, platform=None, external_id=None)`**, with
   `external_id: str | Sequence[str] | None`. Build `data` from the parameters given:
   `"platform": platform` when it is not `None`, and `"external_id": self._wire(external_id)` when
   it is not `None`. Send `data=` next to `files=` only when it is non-empty. Docstring:
   - `platform`: the `dailies.set` wording, plus "One platform per call: it applies to every file;
     upload files from different platforms in separate calls."
   - `external_id`: "Your app's own ID for each file, one per file in the same order (a single
     string for a single file). Needs a token issued to your app. A file sent again with an ID
     SweatStack has seen from your app returns the existing source if the file is unchanged, so
     retrying a lost upload is safe. If the file changed, SweatStack processes it again under the
     same source ID: the old activities are deleted and new ones, with new IDs, take their place."
   - `Returns:` "One entry per file, each with its `writer`, `platform` and `external_id`."
   - `Raises: SweatStackBadRequestError:` "If `platform` is not a platform name or the token may
     not name one, if `external_id` is sent with a token not issued to an app, or if the number of
     IDs differs from the number of files."
   - A second `Examples:` snippet for the relaying app:
     `client.activities.upload(["a.fit", "b.fit"], platform="garmin_connect", external_id=["1001", "1002"])`.
6. **`tests/test_wire_names.py`**: delete the `NOT_EXPOSED["Activities.upload"]` entry from
   commit 1. Every upload field is now a parameter: `platform` and `external_id`, plus `replace` if
   S11's fallback applies.
7. **The release in progress is checkable before it has a version** (`tests/test_renames.py`,
   `tests/test_changelog.py`). Both tests look for a `## [0.99.0] - <date>` heading, but the entry
   sits under `## [Unreleased]` until release day. Without this step, `make check` fails on commit 2
   and on every commit until the release.
   - In `test_renames`, a release newer than the newest released version is checked against the
     `## [Unreleased]` entry.
   - In `test_changelog`, parse `## [Unreleased]` as an entry, so its "breaking", its
     `### Upgrading` and its `upgrading-0-99` markers are held to the same rules before release.
     Name the snippet from the version the entry will get: the minor after the newest released one.
8. **Skills.** `skills/sweatstack-python/data-models.md`:
   - **DailyResponse**: `date`, `value`, `status`, `writer` (`WriterKind`: `athlete`,
     `application`, `sweatstack`; `None` on an estimated or missing day), `application_id`,
     `platform` (a string such as `garmin_connect`, or `None`). Markers and max efforts carry the
     same three fields.
   - **SourceResponse**: replace `origin` with `writer`, `application_id`, `platform`; add
     `external_id`.

   In `api.md`, the `upload` and `dailies.set` lines show `platform="strava"` and
   `platform="garmin_connect"` in a trailing comment, with a single line saying who may send it.
   A line for the relay: `upload(files, platform=..., external_id=[...])`, an app's token, and
   "retry with the same IDs is safe".
9. **AGENTS.md**, "Open enums stay open": drop "sources" from the example list, and add "`WriterKind`
   is closed by the server's contract; keep it strict." The next person to regen should not
   "fix" it.
10. **CHANGELOG** under `## [Unreleased]`: the entry in [CHANGELOG entry](#changelog-entry).

Nothing else changes: no client-side derivation of the old `source` (S1), and no validation of the
name (S4).

## Tests

Red-green: write these first. All offline (AGENTS.md).

**New**
- `dailies.set(..., platform="garmin_connect")` puts `"platform": "garmin_connect"` in the JSON
  body. Without `platform=`, the body has no `"platform"` key, not one set to `None`.
- `activities.upload(fit, platform="strava")` sends `data={"platform": "strava"}` next to the files,
  in one request for two files. Without `platform=`, it passes no `data`.
- `activities.upload([a, b], external_id=["1001", "1002"])` sends
  `data={"external_id": ["1001", "1002"]}` in one request. `upload(a, external_id="1001")` sends
  `["1001"]`. With both parameters, both keys are present. A mismatched count is sent as given:
  the SDK doesn't check it (S10).
- A relayed `SourceResponse` with `writer: "application"`, `application_id: "app_123"`,
  `platform: "garmin_connect"` and `external_id: "1001"` parses, and `external_id` reads back.
- Parsing, one row per case in [Summary](#summary): a recorded `DailyResponse` and `SourceResponse`
  for `athlete`/`None`/`None`, `application`/`"app_123"`/`"garmin_connect"` and
  `sweatstack`/`None`/`"garmin_connect"`. An estimated and a missing `DailyResponse` parse with
  `writer`, `application_id` and `platform` all `None`.
- **`WriterKind` is closed**, parametrised over `DailyResponse`, `SourceResponse`,
  `MarkerRowResponse` and `MaxEffortRowResponse`: `writer: "coach"` raises `ValidationError`. This
  replaces `test_source_is_an_open_set` (`tests/test_dailies.py`) and its rows, which carry over.
- **`platform` is open**: `platform: "a_platform_added_later"` parses as that string on all four
  models.
- **Frames**: `dailies.list(output="polars")` and `"pandas"` have the columns `writer`,
  `application_id` and `platform`, and no `source`. `writer` holds the string `"athlete"`, not an
  enum. `tests/test_frames.py` already turns a `FrameSchemaWarning` into a failure for every public
  model, so the regen's new enum is covered.
- `tests/test_renames.py` picks up the `DailySource` entry by its parametrisation, against the
  `[Unreleased]` entry (commit 2, step 7).

**Updated**, because they construct or read the removed fields:
- `tests/test_dailies.py`: imports `DailySource`, builds dailies with `source=`, asserts
  `source == DailySource.manual` (lines 12–107), and has the open-set test above.
- `tests/test_frames.py:190`, `tests/test_output.py:295`: `source=` becomes `writer=`.
- `tests/test_resources.py:114`: the upload fixture's `"origin": "manual_upload"` becomes
  `"writer": "athlete", "application_id": None, "platform": None`.

**Against the document, by hand.** `tests/test_wire_names.py` with `SWEATSTACK_OPENAPI_JSON`
pointing at the new document: green except `OAuth.authorization_url`'s `login_hint`, which has its
own change (commit 1, step 2).

`tests/test_public_hygiene.py` runs in `make check` and covers this plan and the CHANGELOG entry.

## CHANGELOG entry

Under `## [Unreleased]`, renamed to `## [0.99.0] - <server release date>` on release day.

````markdown
Records say who wrote them and which platform their data came from, as two separate answers.
Breaking: `DailyResponse.source`, `SourceResponse.origin` and `DailySource` are gone; see
**Upgrading** below, or hand the migration prompt to your coding agent.

### Changed

- Dailies, uploaded sources, markers and max efforts carry `writer` (`WriterKind`: `athlete`,
  `application` or `sweatstack`), `application_id` (the app, when the writer is an app) and
  `platform` (where the data came from: `"garmin_connect"`, `"strava"`, ..., or `None`). They
  replace `DailyResponse.source` and `SourceResponse.origin`, which said both at once. On a daily,
  all three are `None` on an estimated or missing day.
- The frames from `dailies.list()` have `writer`, `application_id` and `platform` columns instead
  of `source`.
- `DailySource` is gone, and so is `SourceOrigin` from `sweatstack.openapi_schemas`.
  `WriterKind` is a closed set: a value outside the three is an error, not a pseudo-member.

### Added

- `dailies.set()` and `activities.upload()` take `platform=` to say where the data came from.
  SweatStack accepts it with a token from `authenticate()` or one issued to your app, and answers
  `SweatStackBadRequestError` (422) for a personal API key or a malformed name. It stores the
  canonical spelling: `"garmin"` reads back as `"garmin_connect"`. One `platform` applies to every
  file in an upload.
- `activities.upload()` takes `external_id=`: your app's own ID for each file, one per file in
  order, with a token issued to your app. Sending a file again with an ID SweatStack has seen
  returns the existing source when the file is unchanged, so retrying a lost upload is safe. A
  changed file is processed again under the same source ID, with new activities. The source
  echoes the ID as `SourceResponse.external_id`.

<!-- --8<-- [start:upgrading-0-99] -->
### Upgrading

**Upgrade on the day of SweatStack's <date> release.** From that day, SDKs before 0.99 behave
like this:

- `activities.upload()` raises a pydantic `ValidationError` *after* the server has accepted the
  files. The files are uploaded, so don't retry the call.
- `dailies.list()` keeps working, but **Silent:** `source` is `None` on every day.

0.99 needs that release, and against an older server it fails on every daily it reads.

| 0.98 | 0.99 | Fails how |
|---|---|---|
| `daily.source == DailySource.manual` | `daily.writer == WriterKind.athlete` | `AttributeError` on `.source` |
| `daily.source == DailySource.application` | `daily.writer == WriterKind.application`; `daily.application_id` names the app | `AttributeError` |
| `daily.source == DailySource.garmin_connect` (or `intervals_icu`, `wahoo`) | `daily.writer == WriterKind.sweatstack and daily.platform == "garmin_connect"`. For "from Garmin, whoever wrote it": `daily.platform == "garmin_connect"` | `AttributeError` |
| `daily.source is None` (an estimated or missing day) | `daily.writer is None`, or `daily.status != DailyStatus.stored` | `AttributeError` |
| `source.origin == "manual_upload"` | `source.writer == WriterKind.athlete` | `AttributeError` on `.origin` |
| `source.origin == "garmin_connect"` (or another sync) | `source.writer == WriterKind.sweatstack and source.platform == "garmin_connect"` | `AttributeError` |
| `df["source"]` on a `dailies.list()` frame | `df["writer"]` (strings: `"athlete"`, ...) and `df["platform"]` | `KeyError` (pandas), `ColumnNotFoundError` (Polars) |
| `.get("source")` on a `model_dump()` or a frame row | `.get("writer")`, `.get("platform")` | **Silent:** returns `None` |
| `from sweatstack import DailySource` | `from sweatstack import WriterKind` | `ImportError` |
| `from sweatstack.openapi_schemas import SourceOrigin` | `from sweatstack import WriterKind` | `ImportError` |

**Migration prompt.** Paste this into your coding agent:

```text
Upgrade this codebase to sweatstack 0.99, which splits "who wrote a record" from "which
platform its data came from". The upgrade table is the "Upgrading" section of the 0.99.0 entry
in https://github.com/SweatStack/sweatstack-python/blob/main/CHANGELOG.md (also at
https://docs.sweatstack.no/learn/python/upgrading/). Read it first.

Find every read of `.source` on a daily, marker or max effort, of `.origin` on an uploaded
source, every use of DailySource or SourceOrigin, and every "source" column or key on dailies
data (frames, model_dump(), dicts). For each, decide which question the code asks:

1. Who wrote it (the athlete, an app, or SweatStack's sync)? Use `.writer` and `WriterKind`;
   `.application_id` names the app.
2. Where did the data come from (Garmin, Strava, ...)? Use `.platform`, a plain string such as
   "garmin_connect", or None.
3. Both, as the old garmin_connect value did? Combine them:
   writer == WriterKind.sweatstack and platform == "garmin_connect". Ask whether the code
   really means "from Garmin, whoever wrote it": then platform alone.

Code that checked `source is None` to find estimated or missing days should check
`status != DailyStatus.stored`. Search for `.get("source")` and "source" in column lists: those
return None or drop the column without an error. Then run the code and the tests.
```
<!-- --8<-- [end:upgrading-0-99] -->
````

Write it in user terms. Check before committing: `tests/test_changelog.py` wants every "silent" in
the section written as `**Silent:**` in bold. Don't lowercase or rephrase it.

## Commits

| # | Where | What | Done when |
|---|---|---|---|
| 1 | `main`, now | Regenerate from today's production, plus the temporary `NOT_EXPOSED` entry for the upload | `make check` green; the wire test reports only `login_hint` |
| 2 | branch `writer-and-platform` | Everything in [Commit 2](#commit-2-writer-and-platform-branch-writer-and-platform), regenerated from a local server running the release's code | `make check` green; the wire test against that document reports only `login_hint` |
| 3 | the same branch, release day | Regenerate from production (see Release), bump `pyproject.toml` to 0.99.0, rename the heading | The regen shows no diff against commit 2 |

## Release

The server ships first, and the SDK follows the same day.

1. **Wait until the server release is live**: production's `/openapi.json` has `WriterKind` and no
   `DailySource`. Until then, nothing is released from this branch, and nothing that needs it is
   released from `main` (S9).
2. **Regenerate from production** (commit 3). There should be no diff. If there is one, the server
   changed after commit 2: reconcile it like a regen diff (DEVELOPMENT.md), and don't release until
   the branch matches what production serves.
3. Rebase onto `main`, rename `## [Unreleased]` to `## [0.99.0] - <release date>`, bump the version,
   then run `make check` and `make publish`.
4. **Docs**: on the docs site's Upgrading page, add a `## 0.99` section with the
   `upgrading-0-99` include, above `## 0.94`. The generated reference follows the regen.
5. Check against production with a token from `authenticate()`:
   - `client.dailies.list("body_mass", start=..., end=...)` parses, and `writer` is set on the
     stored days.
   - `client.dailies.set(..., platform="garmin")` reads back `platform == "garmin_connect"` and
     `writer == WriterKind.athlete`. Then delete that test value.

## Not doing

- **A derived `source` or `origin`** (S1).
- **Client-side platform validation, an alias table or a `Platform` enum** (S4). The server owns
  all three, and `platform` is open.
- **SDK methods for `POST /dailies/{measure}/batch`, `POST /profile/markers` and
  `POST /profile/max-efforts`.** They take `platform` too, but the SDK has no methods for them yet.
  Adding them is an endpoint change with its own plan, named by R1–R8.
- **Automatic retries of an upload** (S8).
- **A client-side check that `external_id` and `files` have the same length** (S10). The server's
  `422` names both counts.
- **`login_hint` on `oauth.authorization_url()`**: found while regenerating; its own change.

## Maintainer's notes

- **`writer` is a fact about the token, `platform` is a claim.** The SDK sends a platform only when
  the caller passes one. It never sends a default and never infers one from a file.
- **If the server ever adds a fourth `WriterKind`, that is a breaking server release, and this
  SDK's parse will fail on purpose.** Regenerate, add the member to the Upgrading table, and keep
  the enum closed. Opening it would hide a change in who is accountable for data.
- **New platforms need no SDK change.** If a regen ever turns `platform` into an enum, the server's
  contract has changed. Open it with `_open_enum` and ask why.
- **`external_id` is what makes an upload safe to repeat.** If the server's rule for a known ID
  ever changes (for example, back to a flag), the docstring's retry sentence is the first thing to
  check. It is a promise users build retry loops on.
- **A new write endpoint that takes `platform`** gets the same parameter, docstring wording and
  tests as `dailies.set()`. Copy them; don't re-derive them.
