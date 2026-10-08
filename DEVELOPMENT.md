# Development

Mechanics for working on the SweatStack Python client locally. For the
conventions you must follow when changing code, see [AGENTS.md](AGENTS.md).


## Tooling

This project uses [`uv`](https://docs.astral.sh/uv/) for everything.
**Never use `pip` directly.**

```bash
uv sync --all-extras        # install/update dependencies
make check                  # format, lint, types, tests: run before every commit
uv run pytest               # run tests only
uv run python -c "..."      # ad-hoc scripts
uv run generate-response-models   # regenerate OpenAPI schemas (see below)
```

Python ≥ 3.10 is supported; develop against the version pinned in
`.python-version`.


## Running locally

For interactive exploration (Jupyter):

```bash
uvx --from jupyterlab --with-editable "path/to/sweatstack-python[pandas]" jupyter-lab
```

Run from a scratch directory so JupyterLab does not litter the repo with
`Untitled` notebooks.


## Checks

`make check` runs, in order: `ruff format --check`, `ruff check`, `ty check`
and `pytest`. It is the gate for every commit, and `make publish` runs it
first. Fix formatting and most lint findings with:

```bash
uv run ruff format src tests examples evals
uv run ruff check --fix src tests examples evals
```

- **ruff** and **ty** are pinned to exact versions in the `dev` group.
  Upgrading either is a deliberate change: fix or explicitly ignore new
  findings in the same commit.
- `ty` checks `src/` and `tests/typing/`. `tests/typing/output_types.py` pins
  what a type checker infers for each `output=` value with `assert_type`; ty
  checks it, pytest never runs it. `[tool.ty.src]` in `pyproject.toml` lists
  what is excluded and why.
- Formatting-only commits are listed in `.git-blame-ignore-revs`. Run
  `git config blame.ignoreRevsFile .git-blame-ignore-revs` once so
  `git blame` skips them.


## Running tests

```bash
uv run pytest                          # full suite
uv run pytest tests/test_<name>.py     # one file
uv run pytest --ignore=tests/test_webhooks.py   # skip optional-dep tests
```

`tests/test_webhooks.py` requires `fastapi`, which is an optional extra. If
you have not installed it, ignore that file or `uv sync --extra fastapi`.

All tests are offline — no test should make a network call. See
[AGENTS.md → Testing](AGENTS.md#testing) for how to write new ones.


## Agent test

Does an AI agent with the `sweatstack-python` skill write working code? The
agent test answers that. It hands a pydantic-ai agent six tasks: a script per
common workflow, a Streamlit app, coaching and a writing task. Each one runs in a
fresh uv project with the skill installed. Then it scores the result with
pydantic-evals: whether the program runs, whether the code uses only names the
SDK has (the snippet checker), how many commands failed on the way, the tool
budget, whether the agent read the skill or the docs, and an LLM judge per case.

```bash
make agent-test                                                  # all cases
uv run --group evals python -m evals.agent.run --case mean_max_90d
uv run --group evals python -m evals.agent.run --without-skill   # what does the skill add?
uv run --group evals python -m evals.agent.run --dry-run         # wiring only, offline
```

A real run needs `ANTHROPIC_API_KEY` and a saved SweatStack sign-in, and it
runs the agent's programs against your account. Only the `lactate_test` case
writes data. It writes to a managed user named "SDK eval", and it deletes the
tests and traces it created afterwards. Workspaces of cases that failed stay in
the git-ignored `evals/agent/runs/` so you can inspect them. They contain your
data: never commit or paste them.

Run it after changing the skill, the public API or the docs, and before a
release. Expect some variance between runs. Use `--repeat 3` before
concluding that something got worse.


## Regenerating `openapi_schemas.py`

`src/sweatstack/openapi_schemas.py` is **fully machine-generated** from the
backend's OpenAPI document by `datamodel-code-generator`. Never hand-edit it.

### Procedure

1. Start the SweatStack backend so it serves `http://localhost:8080/openapi.json`.
2. Run:

   ```bash
   uv run generate-response-models
   ```

3. Review the diff carefully. The file is regenerated as a whole, so the
   diff will often include **unrelated upstream changes** since the last
   regeneration (field renames, type tightening, new endpoints).

4. Check the methods against the document, not only the models. Save it
   and run the wire-name test, which compares every resource method's
   parameters with its endpoint's path, query and body parameters (R8):

   ```bash
   curl -s http://localhost:8080/openapi.json -o /tmp/openapi.json
   SWEATSTACK_OPENAPI_JSON=/tmp/openapi.json uv run pytest tests/test_wire_names.py
   ```

   A new server field shows up here as "on the wire but not in the SDK";
   add it to the method (and to `skills/sweatstack-python/api.md`). The
   test skips without the variable, so `make check` stays offline.

5. If the diff contains changes outside the feature you are working on,
   **split them into a separate commit** (`chore: regenerate openapi
   schemas`) that lands before the feature commit. Keep the feature
   commit minimal so reviewers can read it.

### Staging only part of the regenerated file

When the regen drift is too large to include in a feature commit but you
do not want to lose it, stage only the relevant hunks:

```bash
cp src/sweatstack/openapi_schemas.py /tmp/openapi.full.py
git checkout HEAD -- src/sweatstack/openapi_schemas.py
# hand-apply only the lines relevant to your feature
git add src/sweatstack/openapi_schemas.py
cp /tmp/openapi.full.py src/sweatstack/openapi_schemas.py   # restore working tree
```

The working tree now has the full regen (unstaged), and the index has the
minimal feature delta. Commit, then handle the remainder separately.


## Releasing

1. Bump `version` in `pyproject.toml` (SemVer).
2. Add a CHANGELOG entry — see [AGENTS.md → CHANGELOG](AGENTS.md#changelog).
3. `gitleaks git .` reports no leaks (`brew install gitleaks`). Known false
   positives go in `.gitleaks.toml`, each with the reason it's safe.
4. `make publish`: runs `make check`, builds, and uploads with twine.
   The `Makefile` has the canonical commands.


## Docs

The docs live at https://docs.sweatstack.no, built from the `sweatstack.no` repository. The
Python reference there is generated from this package's docstrings.
