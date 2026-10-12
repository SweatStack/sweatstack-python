"""The upgrade path in the CHANGELOG and UPGRADING.md.

Every breaking release has an ``### Upgrading`` section, wrapped in snippet markers so the docs
site includes it; UPGRADING.md holds the procedure and the agent prompt the docs include too.
These tests keep them in step, so a coding agent pointed at either file finds every change.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = (ROOT / "CHANGELOG.md").read_text()
UPGRADING = (ROOT / "UPGRADING.md").read_text()

ENTRY = re.compile(r"^## \[(?P<version>\d+\.\d+\.\d+)\] - (?P<date>\d{4}-\d{2}-\d{2})\n", re.M)


def _entries() -> dict[str, tuple[str, str]]:
    """``{version: (heading, body)}`` for every release entry."""
    matches = list(ENTRY.finditer(CHANGELOG))
    entries = {}
    for match, following in zip(matches, matches[1:] + [None], strict=True):
        end = following.start() if following else len(CHANGELOG)
        heading = match.group(0).removeprefix("## ").strip()
        entries[match.group("version")] = (heading, CHANGELOG[match.end() : end])
    return entries


ENTRIES = _entries()
BREAKING = {v for v, (_, body) in ENTRIES.items() if re.search(r"\bbreaking\b", body, re.I)}
UPGRADING_SECTIONS = {v for v, (_, body) in ENTRIES.items() if "### Upgrading" in body}


def _minor(version: str) -> str:
    return version.rsplit(".", 1)[0]


def test_the_changelog_parses():
    assert "0.91.0" in ENTRIES and "0.91.0" in BREAKING and "0.91.0" in UPGRADING_SECTIONS


@pytest.mark.parametrize("version", sorted(BREAKING))
def test_every_breaking_release_has_an_upgrading_section(version):
    assert version in UPGRADING_SECTIONS, f"{version} says 'breaking' without a ### Upgrading"


@pytest.mark.parametrize("version", sorted(UPGRADING_SECTIONS))
def test_every_upgrading_section_is_a_docs_snippet(version):
    name = f"upgrading-{_minor(version).replace('.', '-')}"
    _, body = ENTRIES[version]
    start, end = f"<!-- --8<-- [start:{name}] -->", f"<!-- --8<-- [end:{name}] -->"
    assert body.count(start) == 1 and body.count(end) == 1, f"{version}: wrap it in {name} markers"
    section = body[body.index(start) : body.index(end)]
    assert "### Upgrading" in section and "## [" not in section


@pytest.mark.parametrize("version", sorted(UPGRADING_SECTIONS))
def test_upgrading_sections_mark_silent_changes_consistently(version):
    # One spelling, bold, so an agent can grep for it.
    _, body = ENTRIES[version]
    section = body.split("### Upgrading", 1)[1]
    for match in re.finditer(r"silent", section, re.I):
        assert section[match.start() - 2 : match.start()] == "**", (
            f"{version}: write silent changes as **Silent:**"
        )


def test_upgrading_md_has_the_docs_snippets():
    for name in ("procedure", "prompt"):
        assert f"<!-- --8<-- [start:{name}] -->" in UPGRADING
        assert f"<!-- --8<-- [end:{name}] -->" in UPGRADING
