# Plan 008: SDK documentation (the design)

What the Python SDK's documentation should be, for human readers and AI
agents alike, without creating docs we can't keep current. **This plan is
the design.** The order of work and every checklist live in the roadmap,
[plan 009](009_road_to_1_0.md): M1 (hotfix), M5 (snippet check), M6 (the
docs), M8 (going public, `llms.txt`).

Proposed 2026-10-05, restructured 2026-10-06. Touches three repos:
`sweatstack-python` (this repo, made public at M8), `sweatstack.no`
(docs.sweatstack.no) and `sweatstack-skills`.

**Status 2026-10-06.** Built as designed: the M6 pages, reference, snippet
check in the docs build and `llms.txt` (D8) are written. Differences are
listed in plan 009 under "Deviations from this plan, as built". The repo
goes public with the 0.91 release, not at M8.


## Principles

1. **One home for readers.** Humans and agents land on docs.sweatstack.no.
   The README and the skill are entry points that link there, not
   parallel documentation.
2. **Content lives next to what it describes.** Anything that must change
   in the same commit as the code (docstrings, README, CHANGELOG, the
   skill) lives in this repo. Concept pages and guides live in the docs
   repo.
3. **Machines check what machines can check.** Every Python snippet in
   docs, skill, README, examples and docstrings is checked against the
   real SDK. Review only has to cover prose.
4. **No per-page upkeep.** Every safeguard and every generated output is
   written once and never needs updating when a page or a method is
   added. Anything that needs a hand-kept list (member lists, mocked
   responses per snippet, hand-written Markdown copies) is out.
5. **Write for agents too.** Agents copy whole code blocks, follow links,
   read docstrings in the installed package, and carry stale training data.
   Every block is complete (imports included), URLs stay stable, pages are
   available as Markdown, and a removed name raises an error that names
   the replacement (plan 009, "Renames").
6. **Written once.** The docs are written against the namespaced API
   (plan 009, M3), not before it. Until then only the hotfix (M1) touches
   them.


## Current state (verified 2026-10-05)

| Surface | State |
|---|---|
| `README.md` (also the PyPI page) | 96 lines: install extras, `output=`, DuckDB, upgrade note. No description of SweatStack, no auth, no quickstart. |
| docs: Learn › Libraries › Python | Overview (23 lines), Interfaces (33), Authentication (78), one mkdocstrings page with all 57 `Client` methods |
| docs: Frameworks | Streamlit, FastAPI: good, task-shaped. Jupyter: documents `sweatlab`/`sweatshell`, removed at M3 (D9) |
| docs: concept pages and guides | Python mixed in, mostly as `=== "Python"` tabs |
| docs: API reference | Generated from OpenAPI, no Python |
| `skills/sweatstack-python/` (moved from `.claude/skills/` on 2026-10-05) | 1,060 lines, current for 0.90, written in flat names. Rewritten short at M3 |
| `sweatstack-skills` (public) | One skill, `sweatstack` (web apps, auth, CLI, API). No Python. The docs' AI coding page claims the skills cover the Python SDK |
| `docs/` (Sphinx) and `make docs` | Abandoned ("MyPackage Documentation"). The only place the environment variables are documented. Deleted at M6 |

Broken today (fixed at M1):

1. `sweatstack.login()` does not exist (it's `authenticate()`). It's the
   first line of code on Python › Interfaces, Python › Authentication and
   the "Analyze activity data" guide.
2. `as_dataframe=True` was removed in 0.89 and is still on 6 pages.
3. Python › Overview says "Timeseries come back as pandas DataFrames" and
   installs with `uv add sweatstack`, which since 0.89 has no frame library.
4. The docs build is pinned to SDK 0.86; the SDK is at 0.90.
5. SDK release notes aren't public anywhere.

After M3 every flat-name snippet in the docs is stale too. M5's check
lists them; M6 rewrites them.

Missing:

- Examples in docstrings (1 of 57 methods has one).
- Reference for models, enums, exceptions and environment variables.
- A link between REST endpoints and Python methods.
- Pages on errors, pagination, caching, delegation and headless use.
- `llms.txt` and Markdown versions of the pages.
- Any check that the docs match the SDK.


## Decisions

| # | Question | Decision |
|---|---|---|
| D1 | Where does Python sit in the nav? | **A top-level item in the Learn sidebar**, not a header tab. It absorbs Frameworks (Streamlit and FastAPI; the Jupyter page goes, D9). The CLI moves to Tools; the "Libraries" group goes away. First after the Learn overview. |
| D2 | Python interleaved with the generic docs, or separate? | Both, by one rule: **true of the API → generic page with a Python tab; true only of Python → the Python section.** |
| D3 | Executable snippet tests with mocked HTTP? | **No.** Too much upkeep per snippet. A static check instead (see "The checker"). |
| D4 | A notebook gallery? | **No.** 3–5 Python guides, each with short output under its steps and a collapsible complete script. |
| D5 | Python docs on the site or in the GitHub repo? | **On the site.** The repo keeps only what changes with the code: docstrings, README, CHANGELOG, the skill. |
| D6 | Where does the Python skill live? | **In this repo, `skills/sweatstack-python/`.** Install with `npx skills add SweatStack/sweatstack-python` once public. `sweatstack-skills` links to it, never copies it. Detail below. |
| D7 | Make this repo public? | **Yes, at M8**, so the first public impression is the stable API. |
| D8 | `llms.txt` and Markdown pages: how? | **The `mkdocs-llmstxt` plugin**, generated from the rendered site; no hand-written copies. Detail below. |
| D9 | Keep `sweatlab` and `sweatshell`? | **No, removed at M3.** Nobody uses them (2026-10-05). Their one advantage is a plain `uvx` command, tokens are saved between sessions, and the example notebook they install calls six functions that no longer exist. |
| D10 | A generated endpoint ↔ method table? | **No** (2026-10-06). Each method's docstring carries its endpoint line, pinned by a test (plan 009, M3). Once names follow R1–R8, a table adds little. |

### D6: the skill stays in this repo

The skills CLI installs from `skills/` or `.claude/skills/` of a public
repo (verified in the vercel-labs/skills README, "Skill Discovery"). What
we keep by staying here:

- **Same commit as the code.** A public-surface change updates the skill
  in the same diff, which is why the skill is current today.
- **Checked against the working tree,** by this repo's tests (M5), before
  a release rather than after.
- **No sync step.**

Cost: two install commands instead of one; `sweatstack-skills` gets a
README row. Details:

- `skills/` is the convention for every agent and reads as a deliverable;
  `.claude/` is local tooling and git-ignored (done 2026-10-05).
- Users install from `main`, which may be ahead of PyPI, so the skill's
  install line pins the version it describes (`>=0.91`), bumped on release.
- **The skill is short.** It keeps what agents get wrong (install extras,
  auth choice, `Client()` vs module level, `output=`, the gotchas) and
  links to the docs' `.md` pages for everything else. Less duplication,
  less drift. Rewritten once at M3, against the new API.

### D8: `llms.txt` via `mkdocs-llmstxt`

[`mkdocs-llmstxt`](https://github.com/pawamoy/mkdocs-llmstxt), by the
author of mkdocstrings, writes `/llms.txt` plus a `.md` file per page. It
doesn't read our Markdown sources: it takes each **rendered** HTML page,
cleans it and converts it back to Markdown, so the mkdocstrings reference,
snippet includes and tabs all end up in the output with no second copy.
The only upkeep is one config block with globs:

```yaml
site_url: https://docs.sweatstack.no   # already set; required by the plugin
plugins:
- llmstxt:
    markdown_description: >
      SweatStack is a sports data platform ... Python SDK: `uv add "sweatstack[pandas]"`.
      Full API schema: https://app.sweatstack.no/openapi.json
    sections:
      Get started: [getting-started/*.md]
      Python SDK: [learn/python/*.md, learn/python/**/*.md]
      Concepts: [learn/data/*.md, learn/authentication/*.md, learn/applications/*.md]
      Guides: [guides/*.md]
```

- The API reference pages are left out: agents do better with
  `openapi.json`, linked from the description.
- No `llms-full.txt` for now.
- A half-day spike first: check the `.md` output for the Python Overview,
  a page with tabs, a page with admonitions and grid cards, and a
  reference page; confirm the glob syntax. Use the `preprocess` hook only
  if a construct comes out badly. **If the spike fails, ship nothing**
  rather than anything hand-maintained.
- Zensical (0.0.67) shows no `llms.txt` support in its package
  description; migrating isn't part of this plan.


## Where each piece of content lives

| Content | Edited in | Shown at | How it gets there |
|---|---|---|---|
| Method reference, endpoint line, examples | SDK docstrings | docs: Python › Reference, one page per resource | mkdocstrings, one `:::` line per resource class |
| Models, enums, exceptions | SDK source | docs: Python › Reference | mkdocstrings, one `:::` line each |
| Environment variables | docs repo | docs: Python › Configuration | moved from the Sphinx `docs/`, which is deleted |
| README | this repo | PyPI, GitHub | packaging |
| CHANGELOG | this repo | docs: Python › Changelog; GitHub Releases (M8) | build hook reads the sibling checkout `../sweatstack-python/CHANGELOG.md` and fails loudly if missing; switches to the GitHub raw URL at M8 |
| Upgrade paths | CHANGELOG `### Upgrading` sections | docs: Python › Upgrading | copied per release, newest first |
| Python skill | this repo, `skills/sweatstack-python/` | agents | `npx skills add SweatStack/sweatstack-python` (public at M8) |
| Concept pages, Python tabs | docs repo | docs: Learn | — |
| Python-only pages and guides | docs repo | docs: Learn › Python SDK | — |
| `llms.txt`, `<page>.md` | generated | docs.sweatstack.no | `mkdocs-llmstxt` |


## The checker: `sweatstack._docs`

One small, stdlib-only module **shipped inside the package**, so every
repo runs the copy that matches the SDK version it checks against. It is
private (underscore), never imported by `sweatstack/__init__.py`, and has
no runtime cost for users.

```bash
uv run pytest                                          # this repo: README, docstrings, skills/, examples/
uv run python -m sweatstack._docs check docs-dev/      # docs repo, in build-docs
```

What `check` does:

- Finds fenced `python`/`py` blocks in `.md` files (including indented
  blocks inside `=== "Python"` tabs), `Examples:` sections in docstrings,
  and whole `.py` files when given.
- Parses each block with `ast`. A syntax error is a finding.
- **Resolves attribute chains statically.** The root is `sweatstack` (the
  package) or any name whose last segment ends in `client` (`client`,
  `auth.client`, `user.client`, `athlete_client`), which resolves to
  `Client`. Each further attribute is looked up on the current class
  through its class-level annotations (`activities: Activities`) or its
  methods; so `client.activities.longitudinal.data(...)` is checked all the
  way down. This is why plan 009 M3 declares resources at class level.
- For every resolved call, and for `Client(...)` and `StreamlitAuth(...)`:
  each keyword exists in the signature, unless it has `**kwargs`.
- Prints `file:line: message` per finding; exits non-zero if any.
- Escape hatch: `<!-- docs: skip -->` on the line before a block. The
  count of skips is printed so they stay visible.

What it doesn't check: prose claims, return types, untyped receivers,
runtime behaviour. Review covers those.


## Information architecture

Learn sidebar after M6 (moved pages get 301s in `docs-dev/_redirects`):

```
Learn
├── Overview
├── Python SDK                 ← new top-level item (was Libraries › Python)
│   ├── Overview               what, install + extras, 10-line quickstart with Client(), skill install, where next
│   ├── Authentication         browser, API key, env vars, token storage, headless, precedence
│   ├── Clients                Client() first; module level as a notebook convenience; threads; delegation
│   ├── Data output            output=, pandas / Polars / Arrow / bytes, DuckDB, dtypes, no index; pagination
│   ├── Errors                 hierarchy, what to catch, retries and timeouts (009 M4), connection errors
│   ├── Configuration          SWEATSTACK_URL, SWEATSTACK_REFRESH_TOKEN, local cache, timeout, max_retries
│   ├── Streamlit              (moved from Frameworks)
│   ├── FastAPI                (moved from Frameworks)
│   ├── Guides                 Python-only guides
│   ├── Upgrading              per-release upgrade paths, newest first
│   ├── Changelog              from CHANGELOG.md
│   └── Reference
│       ├── Client             configuration, auth, delegation, close()
│       ├── Activities, Traces, Tests, Dailies, Profile, Users, Teams, Portal, OAuth
│       │                      one page per resource class, one `:::` line each
│       ├── Models and enums
│       └── Exceptions
├── Applications
├── Data
├── Authentication
├── ...
├── Tools                      now also holds the CLI
└── API reference
```

- Generic guides that are already Python (Streamlit app, FastAPI app,
  Analyze activity data) stay in Guides; the Python section links to them.
- Every Python page starts with one sentence saying what it covers. That
  sentence becomes its entry in `llms.txt` and its search snippet.

**Python guides** (M6, pick 3–5, about a day each): analyse a season with
Polars or DuckDB (revise "Analyze activity data" rather than duplicating
it); run scripts unattended (headless auth, refresh tokens, caching,
scheduling); coach workflows (loop over athletes with `delegated_client`);
write data back (traces, tests, app metadata, uploads); handle errors and
rate limits. Each: a one-sentence goal, steps with short output shown, a
collapsible complete script. The checker covers them automatically.


## Going public (executed at M8)

| Step | Status |
|---|---|
| `plans/` | Done 2026-10-05: published as is, sensitive references removed from the current files (see "Resolved"). History not rewritten; accepted. |
| Outside `plans/` | Done 2026-10-05: realistic example client ID replaced; private server plan references dropped (CHANGELOG, `_frames.py`, three test files). |
| Guardrails | Done 2026-10-05: AGENTS.md "Public repository" section; `tests/test_public_hygiene.py` scans every tracked file for real-looking IDs, JWTs, keys, home paths, server references and notebook outputs. |
| History | Reviewed 2026-10-05, no rewrite needed. Only an old package stub and the removed sport bridge were ever deleted; the secret-pattern scan matched only test fixtures and placeholders. |
| Skill location | Done 2026-10-05: `skills/sweatstack-python/`; `.claude/` git-ignored with a local symlink. |
| Secret scan | To do, just before flipping: `gitleaks detect` over the full history. Rotate anything found, even after removing it. |
| Tidy the surface | To do: LICENSE, CONTRIBUTING.md, DEVELOPMENT.md and AGENTS.md read well to outsiders; enable Issues; description and topics on GitHub. |
| Flip visibility | To do. |
| Links | To do: `[project.urls]` `Changelog`, `Issues`; `Documentation` → Python SDK Overview (M6). |
| Skills repo | To do: README row with `npx skills add SweatStack/sweatstack-python`; a "Public repository" section in its `CLAUDE.md`; restore the AI coding page's skills claim. |
| Docs repo | To do: a "Public repository" section in its AGENTS.md (it's private, but publishes everything it builds). |
| Local installs | To do: reinstall the 11 local projects from GitHub instead of a local path. |
| Releases | To do: a GitHub Release per version from the CHANGELOG section. |


## Rules for the other repos

(This repo's AGENTS.md rules are in plan 009, "Rules to add".)

**`sweatstack.no` AGENTS.md:**

- True of the API → generic page with a Python tab. True only of Python →
  Learn › Python SDK.
- Every Python block is complete: imports included, no undefined names.
- Never edit the Python reference or the changelog by hand; change the SDK
  repo.
- Every page starts with a one-sentence summary (it feeds `llms.txt`).
- Moving a page adds a 301 to `docs-dev/_redirects`.
- `build-docs` upgrades `sweatstack` to the latest release, runs the
  checker, and builds in `--strict` mode. A failing check is a docs bug,
  not something to skip.

**`sweatstack-skills` CLAUDE.md:**

- The Python skill lives in `SweatStack/sweatstack-python`. Link to it,
  never copy it.


## Rejected

| Idea | Why not |
|---|---|
| Executing snippets against mocked HTTP | A fake response to maintain per snippet. The static check catches the drift we actually had. |
| Notebook gallery | Rendered output goes stale and can't be checked cheaply. Guides with a complete script cover the same need. |
| Python as a header tab | Too prominent next to Get started / Learn / Guides. |
| Per-resource reference pages from a flat `Client` | Needed hand-kept member lists. Superseded: resource classes (009 M3) make them free. |
| A generated endpoint ↔ method table | D10. |
| Prose docs moved into this repo | Building one site from two repos for little gain. |
| Python skill in `sweatstack-skills` | Loses same-commit edits and pre-release checking for one fewer install command. |
| Hand-written Markdown copies or `llms.txt` | Duplicate content. Generated or nothing. |
| `llms-full.txt` | Huge once the reference is in; revisit if agents ask for it. |
| Docs URLs in exception messages | Nice to have; deferred past 1.0 (009, non-goals). |
| Writing the docs before the API redesign | Everything would be written twice (principle 6). |


## Resolved

- **`plans/` when the repo goes public** (2026-10-05). Published, after
  removing from the current files: named downstream apps and private
  project names, findings about API consumers and their traffic, private
  server source paths, commit hashes and plan numbers, a realistic-looking
  client ID, and local machine paths. History keeps the earlier wording;
  accepted. New plans are written as if public (AGENTS.md, "Public
  repository").


## Open questions

- **Upgrading page:** one page with a section per release (recommended) or
  a page per release? Start with one page.
