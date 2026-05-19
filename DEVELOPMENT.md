# Development

Mechanics for working on the SweatStack Python client locally. For the
conventions you must follow when changing code, see [AGENTS.md](AGENTS.md).


## Tooling

This project uses [`uv`](https://docs.astral.sh/uv/) for everything.
**Never use `pip` directly.**

```bash
uv sync                     # install/update dependencies
uv run pytest               # run tests
uv run python -c "..."      # ad-hoc scripts
uv run generate-response-models   # regenerate OpenAPI schemas (see below)
```

Python ≥ 3.9 is supported; develop against the version pinned in
`.python-version`.


## Running locally

For interactive exploration (Jupyter):

```bash
uvx --with-editable "path/to/sweatstack-python[jupyterlab]" jupyter lab
```

Run from a scratch directory so JupyterLab does not litter the repo with
`Untitled` notebooks.


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

4. If the diff contains changes outside the feature you are working on,
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
3. `make build` and `make publish` (twine to PyPI). The `Makefile` has
   the canonical commands.


## Docs

```bash
make docs
```

Renders Sphinx to `docs/_build/markdown/`. Most public classes are
documented automatically via `autoclass` directives in `docs/everything.rst`.
