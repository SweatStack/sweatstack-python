.PHONY: check build publish

# Run before every commit. `publish` runs it too, so nothing ships without passing.
check:
	uv run ruff format --check src tests examples
	uv run ruff check src tests examples
	uv run --all-extras ty check
	uv run --all-extras pytest -q

build:
	rm -rf dist
	uvx --from build pyproject-build --installer uv

publish: check build
	uvx twine upload dist/*
