.PHONY: build publish docs


build:
	rm -rf dist
	uvx --from build pyproject-build --installer uv

publish: build
	uvx twine upload dist/*

docs:
	uv run sphinx-build -b markdown docs docs/_build/markdown