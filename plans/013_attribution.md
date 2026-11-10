# Plan 013: Attribution, the line to show next to the data

## Status

- **DONE, 2026-11-10**, verified end to end against production (records, list and trace frames,
  all four Parquet methods, the cache and the Polars route). Ships in 0.100.0.
- Mirrors server 0.157.1, live. Checked against production that day:
  - Regenerating changes the 13 fields in the [Summary](#summary), each `Field(None, ...)`, plus
    `WebhookEventBody.id` (optional), which the Standard Webhooks change in the same release
    reads.
  - The header arrives on all four Parquet routes below and is declared on them in
    `/openapi.json`. It is absent on the two accumulated-work-duration routes.
  - The existing fixtures pass unedited ([D5](#decisions)).
  - The docs section
    [`#where-the-data-came-from`](https://docs.sweatstack.no/learn/data/activities/#where-the-data-came-from)
    is written and goes live before the release ([Release](#release)).
- **Ships as 0.100.0**, a purely additive minor. Nothing is removed, renamed or newly required,
  so no Upgrading section.
- **Effort:** one day. A quarter for the regeneration, the rest for the Parquet line,
  the cache and the docs.
- **Process:** red-green. Write the tests in [Tests](#tests) first.

> **Public repository.** This file is published with the code. It describes the server by its
> public contract (the OpenAPI document and docs.sweatstack.no) and names no app, no user and
> nothing learned from server traffic (AGENTS.md, "Public repository").

## Summary

Every record whose data came from a platform now says which platform that was and what to show
next to it. The rule is the same for every platform. Garmin's brand guidelines require the line,
so an app that displays Garmin data must show it next to that data.

| Record | New field | Example |
|---|---|---|
| `ActivitySummary`, `ActivityDetails` (and so the `activity` nested in a `TraceDetails`) | `platform`, `attribution` | `"garmin_connect"`, `"Garmin"` |
| `SourceResponse`, `DailyResponse`, `MarkerRowResponse`, `MaxEffortRowResponse` | `attribution` (they already carry `platform`) | `"Garmin"` |

`attribution` is a read-only `str | None`: the platform's brand for one record, or `None` for data
from no platform (the athlete's own upload, a value an app computed, an estimated or missing day).

Parquet responses have no field for it, so four routes carry the same line in a response header,
`SweatStack-Attribution`. The header is absent when nothing came from a platform:

| SDK method | Route | Example header |
|---|---|---|
| `activities.data(id)` | `GET /activities/{id}/data` | `Garmin` |
| `activities.mean_max(id)` | `GET /activities/{id}/mean-max` | `Garmin` |
| `activities.longitudinal.data()` | `GET /activities/longitudinal-data` | `Data from Garmin and Strava` |
| `activities.longitudinal.mean_max()` | `GET /activities/longitudinal-mean-max` | `Data from Garmin and Strava` |

The longitudinal line names every platform in the requested range, most activities first. The
accumulated-work-duration routes don't send it yet.

## Decisions

| | Decision | Why |
|---|---|---|
| D1 | **The fields come from the regeneration and nothing else.** No hand-written property and no client-side rule: the SDK never composes the line, not even for a frame it builds from models. | The server owns the rule (one place, every platform). A second copy here would drift the first time a platform is added. |
| D2 | **The Parquet line goes in the frame's own metadata, where one exists, and survives the cache.** pandas gets it in `df.attrs["attribution"]` and Arrow in the schema metadata `b"attribution"`. Polars and bytes have no channel; Polars users ask for Arrow and convert. | See [D2 in detail](#d2-the-line-on-a-parquet-response). |
| D3 | **Frames gain the columns in the model's order.** The SDK never reorders a model's columns. | See [Frame columns](#frame-columns). |
| D4 | **No new methods, parameters or overloads.** No public signature changes, and `tests/typing/` stays as it is. | The fields ride on the methods that already return these records, and the line rides on the frames those four methods already return. |
| D5 | **A field added to an existing response has a default, so the server gives `attribution` one.** On 0.156.0 it is required, which breaks code that builds these models by hand, data saved with `model_dump()` by an older SDK and later validated again, and parsing against an older server. Each fails with `Field required`. The server patch makes it `Field(None, ...)` like `platform`. The SDK changes nothing for this: the existing fixtures are old recorded responses, and they must pass **unedited**. | A new field must never break an old reader (AGENTS.md, "Breaking changes"). Fixing it at the source keeps the release additive. Patching the fixtures would hide the break from users, just as it would hide it from us. |

### D2: the line on a Parquet response

The containers differ in where they can carry the line:

| `output=` | Metadata channel | The line goes |
|---|---|---|
| `"pandas"` | `DataFrame.attrs`, which pandas carries through filters, `copy`, `assign`, `merge`, `groupby` and `concat` of frames with equal `attrs` (checked on pandas 3.0) | `df.attrs["attribution"]` |
| `"arrow"` | Schema metadata, which the SDK already edits (it removes the `pandas` key) | `table.schema.metadata[b"attribution"]`, UTF-8 |
| `"polars"` | **None.** Polars 1.x frames carry no metadata (checked on 1.44). | Nowhere: use `output="arrow"`, below |
| `"bytes"` | None. This output is the raw response body. | Nowhere |

Options considered:

| Option | What a user writes | Verdict |
|---|---|---|
| **A. Native metadata where it exists** | `df.attrs["attribution"]`, `table.schema.metadata[b"attribution"]` | **Chosen.** No new API, and the line travels with the frame. |
| B. A result object carrying frame and line | `result.frame`, `result.attribution` | Rejected: breaks every caller's return type, and the SDK should mirror the REST API, not wrap it. |
| C. `with_attribution=True` returning a tuple | `df, line = ...data(..., with_attribution=True)` | Rejected for now: five more `@overload`s on each of four methods (twenty stubs) to cover one backend that has a one-line route anyway. See [Not doing](#not-doing). |
| `client.last_attribution` or similar | | Rejected: hidden state, wrong under threads. |

**Why A leaves no gap for Polars.** A single activity's line is already on the record in every
backend: `activities.retrieve(id).attribution`, or the `attribution` column of `activities.list`.
For the longitudinal line, Polars users ask for Arrow and convert. The conversion is zero-copy, and
`pl.from_arrow` is what the SDK's own Polars path amounts to:

```python
import polars as pl

table = client.activities.longitudinal.data(sport="cycling", start=date(2026, 1, 1), output="arrow")
line = (table.schema.metadata or {}).get(b"attribution", b"").decode() or None
df = pl.from_arrow(table)
```

**Mechanics.** Every step stays in the code that already handles it:

1. `Client._read_frame(content, output, attribution=None)` takes the line as a third parameter. It
   sets the line **last**, after the backend conversion and the Streamlit conversion, and only when
   it is not `None`. A missing key then means "nothing from a platform", as a missing header does
   on the wire. pandas: `df.attrs["attribution"] = attribution`. Arrow: merge
   `{b"attribution": attribution.encode()}` into the table's existing schema metadata. Polars and
   bytes ignore it.
2. **Every** Parquet call site passes `response.headers.get("SweatStack-Attribution")`, the
   accumulated-work-duration ones included. Those get nothing today, and they will get the line
   the day the server sends it, with no SDK release. Keep the header name in one module constant
   next to `_read_frame`.
3. **The cache stores the line.** `longitudinal.data` and `longitudinal.mean_max` read through
   `_cached_frame`, which stores only the body. Left as it is, a cache hit would silently drop the
   line on exactly the routes where it combines platforms. So `_write_cache` also writes
   `{namespace}-{key}.attribution` (UTF-8, empty when there was no header), and `_read_cache`
   returns `(content, attribution)` and counts as a hit only when **both** files exist. A cache
   written by an older SDK has no `.attribution` file, so its entries are misses, are fetched
   once, and are rewritten. The old cache never answers "nothing from a platform" when that is
   wrong. `clear_cache` already removes the whole directory.

## Frame columns

Additive. New columns appear, and in an activity frame the columns after each new one move along.

| Method | Polars, Arrow | pandas (flattens some columns, which go to the end) |
|---|---|---|
| `activities.list(output=...)` | `platform` after `source_id`; `attribution` after `app_metadata`, before `duration`, `start_local`, `end_local` | Same relative order. `summary.*`, `laps.*` and `traces.*` stay last, as today. |
| `dailies.list(output=...)` | `attribution` last | `attribution` last |
| `traces.list(output=...)` | the `activity` struct gains `platform` and `attribution` | `activity.platform` and `activity.attribution` columns |

No change to `_frames`: `str | None` is an existing row in the JSON Schema grammar, and
`tests/test_frames.py` fails if it isn't.

## Tests

- **Regeneration (D1):** a recorded `ActivitySummary`, `ActivityDetails`, `DailyResponse`,
  `SourceResponse`, `MarkerRowResponse` and `MaxEffortRowResponse` parse with
  `platform`/`attribution` set and with both `null`.
- **Old data still loads (D5):** each of those six, from a payload without the `attribution` key,
  parses with `attribution is None`. The existing fixtures pass **unedited**. If they fail with
  `Field required`, the server patch is missing; don't edit them.
- **Frame columns:** for each backend, the column orders in [Frame columns](#frame-columns), and a
  record from no platform gives a null.
- **The line (D2):** for each of the six Parquet methods, a response mocked at `Client._request`:
  - with `SweatStack-Attribution: Data from Garmin and Strava`: `output="pandas"` has it in
    `attrs`, `output="arrow"` has it in the schema metadata, and the Arrow table's other metadata
    is kept and `pandas` is still removed;
  - without the header: the key is absent on both;
  - `output="polars"` and `"bytes"` return what they return today;
  - `streamlit_compatible=True` keeps `attrs`;
  - a non-ASCII line round-trips through the Arrow metadata.
- **The cache (D2.3):** with the cache enabled, a miss followed by a hit gives the same line on
  the hit, and so does a range with no line. A `.parquet` without an `.attribution` file is a
  miss and is rewritten with both.
- **Public surface:** `tests/test_public_hygiene.py` on this plan and the CHANGELOG entry, and
  `tests/test_skill.py` with the skill edits.

## Docs

- **Docstrings:** in the `Returns:` of the four Parquet methods, one sentence: the line to show
  next to the data is in `df.attrs["attribution"]` (pandas) or the schema metadata
  `b"attribution"` (Arrow) when the data came from a platform, and is absent otherwise.
- **Skill** (same commit, AGENTS.md hard rule): `data-models.md` gains `attribution` next to
  `platform`. `SKILL.md`'s "Output" section gets three lines: where the line lives per backend,
  the Polars recipe, and "show it next to the data; Garmin requires it".
- **Docs site:** the Python [data output](https://docs.sweatstack.no/learn/python/data-output/)
  page gets a short section with the table from D2, the Polars recipe, and one warning: read
  `attrs` right after the call, because combining frames with different lines drops it. The
  generated reference follows the regeneration.

## CHANGELOG, under `[Unreleased]`

**Added**

- Records say which platform their data came from and the line to show next to it: `platform` and
  `attribution` on activities (also the activity in a trace), `attribution` on sources, dailies,
  markers and max efforts, and as columns in the frames from `activities.list()`,
  `dailies.list()` and `traces.list()`. Show `attribution` next to the data, near its title.
  Garmin requires it for Garmin data. See
  [Where the data came from](https://docs.sweatstack.no/learn/data/activities/#where-the-data-came-from).
- `activities.data()`, `activities.mean_max()`, `activities.longitudinal.data()` and
  `activities.longitudinal.mean_max()` put the same line in `df.attrs["attribution"]` (pandas) or
  the schema metadata `b"attribution"` (Arrow), when the data came from a platform. For Polars,
  ask for `output="arrow"` and convert with `pl.from_arrow`. With `enable_cache()` the line is
  cached with the data. Entries cached by an earlier version are fetched again once.

## Release

1. Regenerate from production 0.157.1. The diff is the 13 fields of the [Summary](#summary),
   each `Field(None, ...)`, and the optional `WebhookEventBody.id`.
2. The wire-name check against the same document passes. It found `login_hint`, which shipped
   in its own commit.
3. **Gate:** the docs anchor `#where-the-data-came-from` resolves.
4. `make check`, then `make publish` as 0.100.0, together with the Standard Webhooks change and
   `login_hint`. The Python [data output](https://docs.sweatstack.no/learn/python/data-output/)
   section deploys after the release, because the docs build checks snippets against the
   released SDK.

## Not doing

- **Composing the line in the SDK**, from records or across frames. The server owns the rule
  (D1).
- **Option C (`with_attribution=True`).** Revisit if Polars users find the Arrow route awkward in
  practice. It is additive, so nothing here blocks it.
- **Documenting the line on the accumulated-work-duration methods.** The code already passes the
  header there (D2.2). Document it once the server sends it.
- **The line on `output="bytes"`.** That output is the body, unchanged by contract.
- **The CLI.** It shows no attributed data today.
- **Decoding a non-ASCII header.** HTTP header values are Latin-1, and today's platform names are
  ASCII. If the server ever sends a non-ASCII brand, it must encode the header (RFC 8187), and the
  SDK follows then.
