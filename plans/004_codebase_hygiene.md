# Plan: Codebase hygiene follow-ups

A backlog of items that came up while landing trace-to-test linking and
writing AGENTS.md. Two buckets, with an explicit inclusion criterion so the
list stays principled instead of accumulating taste.


## Inclusion criterion

The **rough edges** section below contains items that meet at least one of:

1. **Inconsistent within the codebase** — same pattern, handled two ways.
2. **Contradicts explicit documentation** — code says one thing, docstrings
   or metadata say another.
3. **Literal falsehood** — config or metadata that is untrue.
4. **Blocks a class of improvements** — a structural absence with broad
   downstream consequence.

Items that meet none of those are stylistic preferences or open design
questions. They go in the **Design questions** section, marked as such, so
they don't quietly migrate into "things we must fix."


## Rough edges

### 1. Singleton method registration is hand-curated and inconsistent

**Observation.** `client.py` bottom: `_generate_singleton_methods([...])`
takes a hand-maintained list of method names to expose as module-level
functions. The list is incomplete: `update_test` and `delete_test` are
registered, `update_trace` and `delete_trace` are not. There is no written
rule for which methods should be in the list.

**Why fix.** A consumer calling `sweatstack.update_trace(...)` gets
`AttributeError` even though `Client.update_trace` exists. The surface
silently drifts from the class.

**Approach.** Either:

- **(a) Auto-register**: at module load, iterate `Client` methods, skip
  underscore-prefixed names, generate singletons for the rest. Single
  source of truth, no list to forget.
- **(b) Keep the list, codify the rule**: AGENTS.md says "all public
  methods on `Client` go here", and add a test that asserts the list
  matches the class.

(a) is the cleaner fix; (b) is the smaller patch. (a) preferred.

**Effort.** Small (a) / tiny (b).


### 2. Docstring exception drift since 0.76.0

**Observation.** The 0.76.0 typed-exception migration replaced
`httpx.HTTPStatusError` with `SweatStackAPIError` subclasses at the call
site, but most existing docstrings still say `Raises: HTTPStatusError`.
The library now documents an exception it does not raise.

**Why fix.** The docs lie. A consumer reading `help(client.get_activity)`
is told to catch `HTTPStatusError`; their `try/except` will never trigger.

**Approach.** One-shot sweep of `client.py`. For each `Raises:` block:

- If the endpoint has a path-param resource ID or references another
  resource by ID, list `SweatStackNotFoundError` for the 404 case.
- If it is an app-token-only endpoint (e.g. `*_app_metadata`), list
  `SweatStackAuthError` for the 403 case.
- Always finish with `SweatStackAPIError` as the catch-all.

Roughly 30 methods; mechanical but needs per-endpoint judgement.

**Effort.** Medium.


### 3. `requires-python = ">=3.9"` is a literal falsehood

**Observation.** `pyproject.toml` declares `requires-python = ">=3.9"` and
classifies for 3.9 onwards. The code uses `X | Y` union syntax (PEP 604,
Python 3.10+) freely throughout `client.py`, `schemas.py`, generated
schemas, and tests. On 3.9 the package will install and crash at first
import with a `TypeError`.

**Why fix.** The package metadata is wrong. pip/uv will happily install
into a 3.9 environment based on the declared floor.

**Approach.**

- Bump `requires-python = ">=3.10"`.
- Drop the `Programming Language :: Python :: 3.9` classifier.
- Ship as a minor bump (`0.78.0`) — tightening a Python floor is a
  breaking change for the affected versions, but in this case the
  package was already non-functional on 3.9, so no real user is
  affected.

**Effort.** Tiny. Worth bundling with another release rather than as a
standalone.


### 4. No CI type-checker or linter

**Observation.** The library ships type hints as part of its value
proposition. There is no `pyright`, `mypy`, or `ruff` config in
`pyproject.toml` and no GitHub Actions workflow that runs them.

**Why fix.** The issues we hit during trace-to-test linking — silent
type widening on regen, `Enum | str` vs strict-enum inconsistency, the
`.value` trap on `httpx.params` — are exactly what a type-checker would
surface. A linter would catch the `from .client import *` and unused
imports that creep in.

**Approach.**

- Add `ruff` config to `pyproject.toml`. Start conservative: formatter +
  the `E`, `F`, `I`, `B`, `UP` rule sets. Format the codebase in a single
  commit to keep the diff readable.
- Add `pyright` config in non-strict mode (so existing code passes), then
  flip individual `reportMissingTypeArgument`-style checks on over time.
- One GH Actions workflow: install via `uv sync --dev`, run `ruff
  check`, `ruff format --check`, `pyright`, `pytest`. Block PRs on
  failure.

**Effort.** Medium for the first pass. The follow-up of tightening
pyright strictness is open-ended; gate it on individual PRs rather than
a flag day.


## Design questions

These do **not** meet the inclusion criterion above. They are deliberate
choices that someone could reasonably make differently. Listed here so we
can record a decision and stop re-litigating each time.

### A. Should `update_*` methods return more than `None`?

**Today.** PUT methods return `None`; the server's `{"message": "..."}`
body is read but discarded.

**For.** Future-proof if the server starts returning the updated resource
or an `updated_at`. Symmetric with `create_*` (which returns a model).

**Against.** PUT-returns-no-body is standard REST. The create/update
asymmetry tracks a real semantic difference: create produces a new ID;
update mutates an existing one. The current message body is
operator-level noise, not data.

**Standing decision.** Keep as `None`. Revisit if the server contract
changes.

### B. `from .client import *` in `__init__.py`

**Today.** Wildcard import.

**For.** Explicit re-exports are easier to review; surface-area drift
shows up in diffs; tools (Sphinx, pyright) handle them better.

**Against.** Requires syncing a list every time something is added to
`client.py`. Small library, low cost.

**Standing decision.** Keep wildcard. Reconsider if (a) the public
surface exceeds what fits comfortably in a manual list, or (b) we adopt
a type-checker that struggles with `__all__`-less wildcards.

### C. `Client.__new__(Client)` in tests

**Today.** Tests that need a `Client` instance for a helper method
construct via `__new__` to skip `__init__`, then set instance attributes
directly.

**For.** A no-I/O `__init__` would let tests construct clients normally
(`Client(api_key="test")`).

**Against.** `Client.__init__` already does no I/O — it just stores
fields and wraps secrets. The `__new__` pattern in tests signals "this
test never authenticates" clearly. Two characters longer than `Client()`.

**Standing decision.** Keep. The smell is cosmetic.

### D. `_enums_to_strings([x])[0]` for single values

**Today.** Helper takes a list. Single-value callers write
`self._enums_to_strings([sport])[0] if sport else None`.

**For.** A companion `_enum_to_string(x)` would read cleaner at the
single-value call sites.

**Against.** Trivially small footprint; helper proliferation has its
own cost; the wrap-and-index idiom is already understood across the
file.

**Standing decision.** Keep. Add `_enum_to_string` only if a new
call site appears where the wrap-and-index actively confuses.

### E. `_default_client = Client()` at module import

**Today.** A `Client` instance is constructed when `sweatstack.client`
is imported, so the module-level singleton functions can bind to it.

**For.** Lazy construction would defer any cost to first use.

**Against.** `Client.__init__` is I/O-free; the cost is microseconds.
Lazy binding would complicate the `_generate_singleton_methods`
machinery for no measurable benefit.

**Standing decision.** Keep.
