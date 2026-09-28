# Plan: OST sport adoption (decode-up bridge, with a removable legacy-tolerance shim)

The SweatStack API is migrating its sport vocabulary to
[OpenSportTaxonomy](https://github.com/SweatStack/open-sport-taxonomy) (OST), published as the
[`open-sport-taxonomy`](https://pypi.org/project/open-sport-taxonomy/) package on PyPI (v0.8.5 at time
of writing; requires Python ≥3.10, matching this SDK's 3.10–3.13 support). A handful of legacy sport
codes are renamed, and three become OST *modifiers* rather than codes:

| Legacy wire value (today) | OST wire value (after migration) | kind |
|---|---|---|
| `cycling.trainer` | `cycling+stationary` | leaf → modifier |
| `running.treadmill` | `running+stationary` | leaf → modifier |
| `rowing.ergometer` | `rowing+stationary` | leaf → modifier |
| `cycling.tt` | `cycling.time_trial` | rename |
| `cycling.mountainbike` | `cycling.mountain` | rename |
| `cross_country_skiing` | `xc_skiing` | rename (root) |
| `cross_country_skiing.classic` | `xc_skiing.classic` | rename |
| `cross_country_skiing.skate` | `xc_skiing.skate` | rename |
| `unknown` | `generic` | fold |

Everything else (`cycling.road`, `running`, `walking`, `swimming`, `generic`, …) is byte-identical
before and after, so this list is the *entire* delta.

## Strategy: decode UP to OST now (one client migration), drop legacy tolerance later

This SDK **adopts OST as its public sport type in this release** and consumes API data the recommended
OST way. Apps that adopt this release migrate their code to OST **once, now**, and are done — there is
no second breaking change later.

> **Direction.** Inbound sport values from the API (whether the **legacy** pre-migration server or the
> **OST** post-migration server sends them) are normalized **up to** `open_sport_taxonomy.Sport`. The
> only thing temporary is the *legacy-tolerance* shim that recognizes old SweatStack spellings; once
> the server is OST-only it is deleted, leaving pure OST. This is the mirror image of a "keep the old
> enum, decode OST down to it" shim — chosen because it reaches the OST end state immediately and
> matches "consume the API the recommended way" at the *public* surface, not just internally.

The expand → migrate → contract rollout:

1. **OST adoption release (this plan) — BREAKING (minor bump in `0.x`: `0.80.0`).** Public `Sport` becomes
   `open_sport_taxonomy.Sport`. Both inbound surfaces — pydantic response models **and** the
   parquet-backed DataFrames — decode legacy **and** OST values to OST; requests encode OST → legacy
   so a pre-migration server still understands them. The SDK works against **both** the current
   (legacy) and future (OST) server. Ask Molab Run, Myra Studio, and direct users to upgrade and port
   their code to OST.
2. **Server migration** (SweatStack `plans/027`). The API flips to OST. Apps on this release notice
   nothing — they already speak OST.
3. **Contract release — NON-breaking, patch bump in `0.x`.** Once the server is OST-only, delete the
   legacy-tolerance shim (the maps + the custom validator/encoder). The public API does not change,
   because it was already OST.

Note the version-bump structure is the inverse of a decode-down shim: the **breaking** work happens
**now** (step 1, `0.80.0`), and the cleanup (step 3) is a quiet non-breaking patch. The gate between 1 and 2 is
social: every known consumer must be on this release before the server flips. Because the consumers
barely touch sport (SweatStack `plans/027` Appendix B: the only filter anyone sends is `running`,
identical in both vocabularies), the coordination cost of the breaking change is low.

## The bridge module (the legacy-tolerance shim — the deletable part)

One new file. It owns the migration table once and derives both directions, plus the pydantic and
encode glue. Everything in here is what gets deleted at the contract release.

```python
# src/sweatstack/_sport_bridge.py
#
# TEMPORARY legacy-tolerance shim for the OST sport-vocabulary migration.
# The PUBLIC sport type is open_sport_taxonomy.Sport; this file only lets the SDK keep talking to a
# pre-migration (legacy) server during the rollout window. DELETE THIS FILE WHOLE in the contract
# release — see plans/005_ost_sport_bridge.md. A repo-wide grep for `_sport_bridge` returning zero
# hits is the definition of done for the cleanup.

from typing import Annotated, Any

from pydantic import BeforeValidator
from open_sport_taxonomy import Sport
from open_sport_taxonomy.pydantic import SportField

# The migration delta, authored once. (legacy SweatStack wire value, OST wire value).
_MIGRATION: list[tuple[str, str]] = [
    ("cycling.trainer",               "cycling+stationary"),
    ("running.treadmill",             "running+stationary"),
    ("rowing.ergometer",              "rowing+stationary"),
    ("cycling.tt",                    "cycling.time_trial"),
    ("cycling.mountainbike",          "cycling.mountain"),
    ("cross_country_skiing",          "xc_skiing"),
    ("cross_country_skiing.classic",  "xc_skiing.classic"),
    ("cross_country_skiing.skate",    "xc_skiing.skate"),
    ("unknown",                       "generic"),
]
_LEGACY_TO_OST: dict[str, str] = {legacy: ost for legacy, ost in _MIGRATION}
_OST_TO_LEGACY: dict[str, str] = {ost: legacy for legacy, ost in _MIGRATION}


def to_ost_sport(value: Any) -> Sport:
    """Normalize any inbound sport value to an OST `Sport`, tolerating legacy spellings.

    The one inbound decoder, used in two places: as the pydantic BeforeValidator in front of OST's
    `SportField` (response models), and directly where the SDK builds a Sport from a raw string
    (get_sports). It applies the SweatStack-specific renames no library can know, then defers to
    `Sport.parse` — permissive, so unknown/future codes are preserved, never raised; never the strict
    `Sport(...)` constructor. Already-built `Sport` objects pass straight through. Returning a `Sport`
    (not a string) is fine for the BeforeValidator: `SportField` still serializes it to the canonical
    wire string (verified).
    """
    if isinstance(value, Sport):
        return value
    return Sport.parse(_LEGACY_TO_OST.get(value, value))


def encode_sport(sport: Sport) -> str:
    """Serialize an OST Sport to a wire value a PRE-migration server accepts.

    During the bridge window the server speaks legacy, so the ~9 changed values are translated back;
    everything else (the vast majority, incl. `running`) is byte-identical and passes through as the
    canonical OST string. Deleted at the contract release, where `str(sport)` is sent directly.
    """
    wire = str(sport)
    return _OST_TO_LEGACY.get(wire, wire)


def normalize_sport_column(df, column: str = "sport"):
    """Translate legacy wire values to OST in a DataFrame's sport column, in place.

    Longitudinal/parquet DataFrames are read straight from the wire and bypass the pydantic models
    (and thus to_ost_sport), so this is where the response-side legacy->OST swap happens for tabular
    data. The column stays plain strings in canonical OST form (per OST's "store str(sport)" guidance),
    not Sport objects. Guarded by column presence; a no-op once the server speaks OST. Deleted at the
    contract release.
    """
    if column in df.columns:
        df[column] = df[column].map(lambda v: _LEGACY_TO_OST.get(v, v))
    return df


# Legacy-tolerant response field: OST's own SportField, fronted by the inbound normalizer.
# At the contract release this is replaced wholesale by open_sport_taxonomy.pydantic.SportField.
LegacySportField = Annotated[SportField, BeforeValidator(to_ost_sport)]
```

**Why front `SportField` instead of `Annotated[Sport, …]`** — this is the wiring that was empirically
verified, and the obvious-looking alternative is a trap. A bare `Annotated[Sport, BeforeValidator(...)]`
validates fine but **serializes wrong**: `model_dump()` emits `{'code': 'cycling', 'modifiers': […]}`
instead of the wire string `"cycling+stationary"`, corrupting the SDK's output. Fronting OST's
`SportField` (which carries the correct pydantic core schema) makes `model_dump()` round-trip to the
canonical string. `SportField` is permissive (`Sport.parse`-based), so it ingests faithfully — unknown
future codes/modifiers are preserved, not rejected — which is the recommended *parse-on-ingest*
behavior; callers `.resolve()` themselves for application logic. Storing `str(sport)` round-trips
losslessly (`str(Sport.parse("cycling.road+virtual")) == "cycling.road+virtual"`).

## Wiring (the six seams)

**1. Public type — re-export OST `Sport`.** In `schemas.py`, replace the import of the codegen'd
`Sport` enum with `from open_sport_taxonomy import Sport, Modifier`. Remove the entire legacy-enum
extension block — the `_sport_missing` hook (schemas.py:128-140, wired at :143) and the
`root_sport`/`parent_sport`/`is_sub_sport_of`/`is_root_sport`/`display_name` monkeypatching
(schemas.py:25-145). OST's `Sport` provides its own equivalents (table below). The existing export
chain then carries it through unchanged: `client.py` imports `Sport` (and now `Modifier`) from
`.schemas` (client.py:42-45), and `__init__.py`'s `from .client import *` re-exports both via the
generated `__all__` — so `from sweatstack import Sport` yields `open_sport_taxonomy.Sport`. Add
`Modifier` to `test_public_surface.py`'s core-surface list alongside `Sport`.

**2. Response decode — codegen override (AST-anchored, regeneration-safe).** The response models
(`ActivityDetails.sport`, …) must validate `sport` through the tolerant field. Add a post-generation
step to the `generate-response-models` CLI (cli.py) that replaces the whole generated `Sport` enum with
an import alias. Locate the class by name via stdlib `ast` (not a text regex, so it survives
regeneration) and splice the import + alias in over its source span:

```python
import ast
from pathlib import Path

def _replace_sport_enum(path: Path) -> None:
    """Swap the codegen'd `class Sport(Enum)` for the OST-backed legacy-tolerant field."""
    src = path.read_text()
    cls = next(n for n in ast.parse(src).body
               if isinstance(n, ast.ClassDef) and n.name == "Sport")  # no decorators on the enum
    lines = src.splitlines(keepends=True)
    lines[cls.lineno - 1 : cls.end_lineno] = [
        "from ._sport_bridge import LegacySportField\n",
        "Sport = LegacySportField  # OST adoption — see plans/005; regenerated by cli.py\n",
    ]
    path.write_text("".join(lines))
```

Putting the import *where the class was* (well past the file's `from __future__` header) avoids any
import-ordering pitfall. Every generated annotation (`sport: Sport`, `sport: Sport | None`,
`list[Sport]`) then binds to the tolerant field. **Verified against the current generated file:**
`class Sport(Enum)` is a single contiguous block (openapi_schemas.py:988); all 14 references are plain
type annotations; there are **zero** enum-member defaults (`Sport.cycling_road`); and the enum carries
no decorators — so wholesale replacement is safe.

This CLI step is **permanent infrastructure**: at the contract release only the injected target
changes (`LegacySportField` → `open_sport_taxonomy.pydantic.SportField`). Validated values are real OST
`Sport` instances and `model_dump()` emits the canonical wire string.

> **Pin it with a regeneration test (so it can't silently rot).** Because `openapi_schemas.py` is a
> committed artifact regenerated only by the manual CLI, guard the transform two ways: (a) a unit test
> that runs `_replace_sport_enum` on a tiny fixture and asserts `class Sport(` is gone and `Sport =
> LegacySportField` is present; (b) an import-level assertion in the test suite that
> `openapi_schemas.Sport is LegacySportField` and that `ActivityDetails(sport="cycling.trainer").sport`
> decodes to the OST member — so a regeneration that forgets the step fails CI loudly.

**3. Request encode — the request-path back-compat seam.** `Client._enums_to_strings`
(client.py:1017-1018) special-cases `Enum`; OST `Sport` is **not** an `Enum`, so it must be handled
explicitly — and this is the **only** request-path site that needs the legacy translation (the other
two back-compat seams, 5 and 6, are on response/read paths):

```python
from ._sport_bridge import encode_sport   # `Sport` is already imported in client.py (now the OST type)

def _enums_to_strings(self, values: list) -> list[str]:
    out = []
    for value in values:
        if isinstance(value, Sport):
            out.append(encode_sport(value))   # <- the temporary legacy translation lives here
        elif isinstance(value, Enum):
            out.append(value.value)
        else:
            out.append(value)
    return out
```

Two nearby points, both fine — the DataFrame surface is handled separately in seam 5:

- **Cache key** (client.py:149-152) already degrades correctly — OST `Sport` has no `.value`, so the
  existing `else str(v)` branch stringifies it, which is a stable, unique key. No change required
  (pin with a cache-key test).
- **No `Sport` object ever lands in a DataFrame cell**, so `utils.py` needs no sport change.
  Model-derived DataFrames are built from `model_dump()` (client.py:1154), which emits the OST wire
  string (decode already happened in pydantic); parquet-derived DataFrames hold strings. The parquet
  path still needs a legacy→OST translation, but on the *string* — that is seam 5.

**4. Internal call sites that used the old enum API.** `streamlit.py:494` iterates the enum
(`[sport for sport in Sport if "." not in sport.value]`) → `[s for s in Sport.all() if "." not in
s.code]`; and `streamlit.py:469,502,508` call `.display_name()` → `.label`. (`utils.py` imports
`Sport` only for typing.)

**5. DataFrame decode — the longitudinal/parquet path (a second decode surface).** `get_longitudinal_data`
and the other `get_longitudinal_*`/parquet methods build their result with
`pd.read_parquet(BytesIO(response.content))`, which **bypasses the pydantic models entirely** — so a
`sport` column carries raw wire strings with no translation (legacy from a pre-migration server, OST
from a post-migration one). Every one of these funnels through `_postprocess_dataframe` (client.py),
so normalize there — one seam covers all of them, cached and fresh:

```python
from ._sport_bridge import normalize_sport_column

def _postprocess_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
    df = convert_to_standard_dtypes(df)
    df = normalize_sport_column(df)          # legacy -> OST in the `sport` column (back-compat)
    if self.streamlit_compatible:
        df = make_dataframe_streamlit_compatible(df)
    return df
```

The column stays plain strings in canonical OST form (`"cycling+stationary"`, …) — consistent with the
existing string-valued DataFrame convention and OST's *store `str(sport)`* guidance; a caller who wants
objects does `df["sport"].map(Sport.parse)`. It is guarded by column presence (DataFrames without a
`sport` column are untouched) and idempotent on already-OST columns (so it's harmless on the
`model_dump()`-derived frames that also pass through here). This is a **back-compat** seam — it uses
the legacy→OST map and is removed at the contract release.

*DataFrame surface audited (confirmed with the API owner):* the **only** frame carrying a `sport`
column is `longitudinal_data`; the mean-max, AWD, and activity-level frames carry **no** sport at all,
and sport never appears in a DataFrame **index**. So the column check above is complete — no
index-level handling is needed. (Dailies likewise have no sport: `DailyResponse` is `date`/`value`/
`source`.) The `get_activities`/`get_traces` `as_dataframe` frames are built from `model_dump()`, so
their sport is already decoded; `normalize_sport_column` is a harmless no-op on them.

**6. Direct `Sport` construction — `get_sports`.** `get_sports` builds its result with
`[Sport(sport) for sport in response.json()]` (client.py:2380). After the switch, `Sport(...)` is OST's
**strict** constructor, which **raises** on any non-standard value — so against a pre-migration server
(legacy strings) it would *crash*, and even post-migration it would crash on a brand-new server sport
the SDK's OST version doesn't know. Use the tolerant helper:

```python
from ._sport_bridge import to_ost_sport
...
return [to_ost_sport(sport) for sport in response.json()]
```

The strict→`parse` change is **permanent** (never crash on an unknown server value); the legacy
translation inside `to_ost_sport` is the back-compat part, dropped at contract (→ `Sport.parse(sport)`).

## Helper-method migration (the public-API break, documented)

Per the chosen pure decode-up approach there is **no compatibility shim** — consumers move to OST's
native API. The CHANGELOG/migration guide must spell this out:

| Old SDK (legacy enum) | OST `Sport` |
|---|---|
| `Sport.cycling_road` (member) | `Sport.CYCLING_ROAD` (constant) or `Sport.parse("cycling.road")` |
| `sport.value` | `str(sport)` (full, with modifiers) or `sport.code` (no modifiers) |
| `for s in Sport:` | `Sport.all()` |
| `sport.display_name()` | `sport.label` |
| `sport.parent_sport()` | `sport.parent` |
| `sport.is_sub_sport_of(x)` | `sport.is_subsport_of(x)` — **note:** OST takes a single `Sport`; for the SDK's old list form use `any(sport.is_subsport_of(s) for s in xs)` |
| `sport.root_sport()` | **no direct equivalent** — derive `Sport.parse(sport.code.split(".")[0])` |
| `sport.is_root_sport()` | **no direct equivalent** — `"." not in sport.code` |

The two `root` helpers are the only genuine capability gap (OST exposes `.parent`/`.disciplines` but
no root). The repo does not use them internally, and it is confirmed that **no consumer uses them** —
so they are dropped with no replacement helper; the one-line derivations in the table above are
documented in the migration guide for anyone who needs them later.

## Migration prompt (ship this to consumers)

Publish the following copy-pastable prompt in the CHANGELOG/release notes so a consumer can hand it to
a coding agent to port their codebase. Keep it in sync with the table above.

````text
Migrate this codebase to the new `sweatstack` release, which replaces its custom `Sport` enum with
the OpenSportTaxonomy type (`open_sport_taxonomy.Sport`). `from sweatstack import Sport` is now that
type. Find every use of SweatStack's `Sport` and update it as follows.

1. Construction / members:
   - `Sport.cycling_road` (lower_snake member) -> `Sport.CYCLING_ROAD` (UPPER constant) or
     `Sport.parse("cycling.road")`.
   - Building a Sport from an API/string value -> `Sport.parse(value)` (permissive, never raises on
     unknown values). Use `.resolve()` only when you need the nearest *standard* sport.

2. These sport VALUES were renamed by the API migration. Update any hardcoded strings or members:
   | was            | now                  |
   |----------------|----------------------|
   | cycling.trainer        | cycling+stationary   |
   | running.treadmill      | running+stationary   |
   | rowing.ergometer       | rowing+stationary    |
   | cycling.tt             | cycling.time_trial   |
   | cycling.mountainbike   | cycling.mountain     |
   | cross_country_skiing[.classic|.skate] | xc_skiing[.classic|.skate] |
   | unknown                | generic              |
   ("stationary" etc. are now modifiers, appended with `+`; check `sport.modifiers`.)

3. Methods / attributes:
   | was                          | now                                              |
   |------------------------------|--------------------------------------------------|
   | sport.value                  | str(sport)  (full, incl. modifiers) / sport.code |
   | sport.display_name()         | sport.label                                      |
   | sport.parent_sport()         | sport.parent                                     |
   | sport.is_sub_sport_of(x)     | sport.is_subsport_of(x)  -- x must be a single Sport; for a list use any(sport.is_subsport_of(s) for s in xs) |
   | sport.root_sport()           | Sport.parse(sport.code.split(".")[0])            |
   | sport.is_root_sport()        | ("." not in sport.code)                          |
   | for s in Sport: ...          | for s in Sport.all(): ...                         |

4. Equality still works: `activity.sport == Sport.parse("cycling+stationary")`. Comparing against a
   renamed value must use the NEW spelling (see table 2).

After editing, run the test suite and fix any remaining references. Do not add a compatibility shim;
migrate call sites to the OST API directly.
````

## The dependency

Add `open-sport-taxonomy` with the `pydantic` extra **in this release** (use uv, not pip):

```bash
uv add "open-sport-taxonomy[pydantic]>=0.8.5"
```

The `[pydantic]` extra is needed now because the response models consume `sport` via OST's
`SportField` (fronted by the legacy swap; the contract release uses `SportField` directly). Floor at
`0.8.5` (first release with the `parse`/`resolve`/`modifiers` API and the `Modifier.STATIONARY` member
this plan relies on); no upper bound.

> **Verified against v0.8.5 (executed, not assumed).**
> - `Modifier.STATIONARY` (value `'stationary'`) exists. Public `Sport` API: `code`, `label`,
>   `parent`, `disciplines`, `modifiers`, `is_standard`, `is_subsport_of`, `all`, `parse`, `resolve`,
>   plus `Sport.CYCLING_ROAD`-style constants. There is **no** `root` member (hence the gap above).
> - Every migration-table row round-trips: `Sport.parse("cycling+stationary")` → code `cycling` +
>   `{STATIONARY}`; the renames come back as standard codes; `str()` round-trips faithfully.
> - **The field wiring was tested both ways.** `Annotated[SportField, BeforeValidator(to_ost_sport)]`
>   (the plan's choice) validates legacy + OST input, preserves unknown values, passes through built
>   `Sport` objects, and `model_dump()`s to the canonical **string** — even though the validator
>   returns a `Sport` object. The naive `Annotated[Sport, BeforeValidator(...)]` instead dumps
>   `{'code': …, 'modifiers': …}` — a real serialization bug, rejected.

## Lossiness (now minimal)

Decode-up is **faithful** — inbound OST modifiers are preserved, nothing is flattened. The only lossy
edge is the **encode** path *during the bridge window*: an OST sport carrying a modifier with no legacy
equivalent (e.g. filtering on `cycling.road+virtual`) cannot be expressed to a pre-migration server;
`encode_sport` sends `str(sport)` and the old server may not recognize it. Per the traffic audit no
app filters on a changed or modified sport (only `running`, identical in both), so this never bites in
practice. It disappears entirely at the contract release, when the server speaks OST. The old
`unknown`/`generic` fold is also resolved server-side (it folds to `generic`), so the SDK never sees
`unknown` post-migration.

## Permanent vs. temporary: the rip-out surface

The back-compat is concentrated so it lifts out cleanly. Everything below splits into "OST adoption
that stays" and "legacy shim that goes," and the shim is one file plus **four** call sites.

**Permanent (OST adoption — stays forever):** public `Sport` = `open_sport_taxonomy.Sport`; the
AST codegen step (only its injected target changes); `_enums_to_strings`/utils.py serializing a
`Sport` via string; streamlit's `.label`/`Sport.all()`; the removed legacy helpers.

**Temporary (the shim — deleted at the contract release):**

| What | Rip-out action |
|---|---|
| `src/sweatstack/_sport_bridge.py` (maps + `to_ost_sport` + `encode_sport` + `normalize_sport_column` + `LegacySportField`) | delete the file |
| cli.py injected codegen target | `LegacySportField` → `open_sport_taxonomy.pydantic.SportField` (one string) |
| `_enums_to_strings` in client.py | `encode_sport(value)` → `str(value)` (one call) |
| `_postprocess_dataframe` in client.py | remove the `normalize_sport_column(df)` call (one line) |
| `get_sports` in client.py | `to_ost_sport(sport)` → `Sport.parse(sport)` (one call) |

That is the **entire** rip-out: a file deletion plus four ~one-line edits, no public API change. A
repo-wide `grep _sport_bridge` surfaces exactly those references (the module, the cli import, and the
three client imports); when it returns zero the shim is gone. It ships as a **non-breaking minor
release**.

## Contract release: the steps

1. Delete `src/sweatstack/_sport_bridge.py`; apply the four call-site edits in the table above.
2. Regenerate `openapi_schemas.py` against the migrated server (`generate-response-models`); the
   AST step now injects `SportField` directly, so the migrated server's free-form `sport` string is
   consumed by OST with no legacy translation.
3. Verify `grep _sport_bridge` returns zero hits. Non-breaking patch bump within `0.x`; CHANGELOG
   notes the internal cleanup (no public change).

## Tests (write the failing ones first)

In `tests/`:

- **Public surface** — `from sweatstack import Sport` is `open_sport_taxonomy.Sport`;
  `test_public_surface.py` updated accordingly.
- **Both spellings converge** — for every migration row, the legacy and OST inbound values decode to
  the *same* OST sport: e.g. an `ActivityDetails` validated with `sport="cycling.trainer"` and one
  with `sport="cycling+stationary"` compare equal, with `.code == "cycling"` and
  `Modifier.STATIONARY in .modifiers`.
- **Renames & fold** — `cycling.tt`→`cycling.time_trial`, `cycling.mountainbike`→`cycling.mountain`,
  `cross_country_skiing[.classic|.skate]`→`xc_skiing[...]`, `unknown`→`generic`.
- **Identity passthrough** — `running`, `cycling.road`, `generic` decode unchanged.
- **Future-tolerance** — `ActivityDetails(sport="kitesurfing")` does not raise; the value is preserved
  (`is_standard` False), faithful to `Sport.parse`.
- **Serialization round-trip (the bug tripwire)** — a response model with an OST sport `model_dump()`s
  `sport` back to the **wire string** (e.g. `"cycling+stationary"`), *not* a `{code, modifiers}`
  object. This is the test that would have caught the rejected `Annotated[Sport, …]` wiring.
- **Encode (bridge window)** — `client._enums_to_strings([Sport.parse("cycling+stationary")]) ==
  ["cycling.trainer"]`; `["running"]` passes through unchanged; an OST `Sport` is never sent as a
  non-string object.
- **Cache key** — `_generate_cache_key` yields a stable string for an OST `Sport` (no `.value`
  needed), confirming the cache path needs no back-compat change.
- **Longitudinal/parquet DataFrame decode** — a DataFrame whose `sport` column holds legacy values
  (`cycling.trainer`, `cross_country_skiing`) comes out of `_postprocess_dataframe` with OST strings
  (`cycling+stationary`, `xc_skiing`); OST and unchanged values pass through; a frame with no `sport`
  column is untouched; and the normalization is idempotent on an already-OST column.
- **`get_sports` tolerance** — `get_sports` against a legacy payload (`["cycling.trainer", "running",
  "cross_country_skiing"]`) returns the OST sports without raising; an unknown future sport is
  preserved (`is_standard` False) rather than crashing — i.e. the strict `Sport(...)` constructor is
  not used.
- **Modifier member tripwire** — assert `Modifier.STATIONARY` exists, so a future OST rename fails
  loudly here.
- **str round-trip** — `str(Sport.parse("cycling.road+virtual")) == "cycling.road+virtual"`.
- **Migration map integrity** — `_OST_TO_LEGACY` is the exact inverse of `_LEGACY_TO_OST`, and both
  cover the 9-row table.

## Effort and risk

- **Effort: Medium.** Bigger than a decode-down shim: it adds the dependency, overrides codegen via an
  AST step, wires three back-compat seams (request encode + parquet-DataFrame decode + `get_sports`),
  removes the legacy enum + helpers, and is a breaking release with a migration guide. The bridge
  module itself is small (~65 lines).
- **Version: `0.80.0`.** The project stays in `0.x`, so this breaking release bumps the minor (from
  0.79.0). The CHANGELOG carries the migration prompt above and the value-rename table, clearly
  flagging the breaking sport-type change.
- **Primary risk — breaking change coordination.** Every known consumer must port to OST and adopt
  this release before the server flips. Mitigated by the small, controllable consumer set and the
  Appendix-B finding that they barely touch sport.
- **Codegen substitution.** The post-generation replacement of the `Sport` enum must be reliable
  across regenerations; pin it with a test that imports a response model and checks `sport` decodes an
  OST value.
- **New dependency at the public surface.** `open-sport-taxonomy` is now a hard, public dependency
  (not just internal). It is small, pure-Python, ≥3.10, and maintained by SweatStack itself, so risk
  is low; the modifier-member tripwire pins the one API detail keyed by name.
- **`is_subsport_of` signature change** (single vs. the old list form) — called out in the migration
  guide.
- **Request path / external dependency.** The server does **not** accept OST input, so requests
  encode OST→legacy (seam 3) and rely on the server accepting legacy input through the bridge window
  (SweatStack `plans/027`). At the atomic input+output flip this is backstopped by observed traffic:
  the only filtered sport is `running`, identical in both vocabularies, so no real request breaks even
  for the changed sports. Removable at contract.

## Confirmed decisions

- **The server does NOT accept OST sport input; the migration flips input and output together.** So
  the SDK cannot send OST early — **seam 3 (`encode_sport`, OST→legacy) is required** and stays. The
  request path relies on the server accepting legacy input through the bridge window (the documented
  `plans/027` dependency); and at the atomic flip it is backstopped by observed traffic — the only
  sport any app filters on is `running`, byte-identical in both vocabularies, so no real request breaks
  even for the changed sports.
- **The longitudinal parquet column is named `sport`** — `normalize_sport_column`'s default key is
  correct; no override needed.
- **No consumer uses `root_sport()`/`is_root_sport()`** — they are dropped with no replacement helper;
  the migration guide documents the one-line derivations for anyone who needs them later.
- **Version: `0.80.0`** — the project stays in `0.x`, so this breaking release bumps the minor (from
  0.79.0); the contract release is a later non-breaking patch within `0.x`.

## Build order (suggested, each step independently testable)

1. Add the dependency; create `_sport_bridge.py` with the four helpers + `LegacySportField`; unit-test
   them in isolation (map integrity, `to_ost_sport`, `encode_sport`, `normalize_sport_column`).
2. Seam 1 (public type) + seam 2 (codegen transform + regeneration test). Now response models decode.
3. Seams 3, 5, 6 (encode, DataFrame, `get_sports`) — the remaining I/O channels.
4. Seam 4 (streamlit) + remove dead helper code; update `test_public_surface.py`.
5. Write the CHANGELOG with the migration prompt; choose the version bump.

## Out of scope

- A backwards-compatibility shim that keeps the old `Sport.cycling_road`-style members or helper
  methods working — explicitly rejected in favor of a single clean migration to OST.
- Using OST's platform translators (`open_sport_taxonomy.platforms.*`, e.g. strava/garmin) — the SDK
  speaks SweatStack's own wire format; there is no `sweatstack` translator, which is why the migration
  map is hand-authored here.
- Helping non-SDK consumers (the Node.js apps, the KeeperCircle iOS app). They do not use this library
  and are coordinated separately; per SweatStack `plans/027` Appendix B they do not filter on sport.
