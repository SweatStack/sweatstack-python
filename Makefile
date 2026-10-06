.PHONY: check build publish agent-test

# Run before every commit. `publish` runs it too, so nothing ships without passing.
check:
	uv run ruff format --check src tests examples evals
	uv run ruff check src tests examples evals
	uv run --all-extras ty check
	uv run --all-extras pytest -q

build:
	rm -rf dist
	uvx --from build pyproject-build --installer uv

publish: check build
	uvx twine upload dist/*

# Needs ANTHROPIC_API_KEY and a saved SweatStack sign-in; see DEVELOPMENT.md.
agent-test:
	uv run --group evals python -m evals.agent.run
