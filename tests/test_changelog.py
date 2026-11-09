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
UNRELEASED = re.compile(r"^## \[Unreleased\]\n", re.M)


def _next_minor(version: str) -> str:
    major, minor, _ = version.split(".")
    return f"{major}.{int(minor) + 1}.0"


def _entries(changelog: str) -> dict[str, tuple[str, str]]:
    """``{version: (heading, body)}`` for every release entry.

    ``## [Unreleased]`` counts as the next minor release, the version it will get (a breaking
    change is always a minor). So the work in progress is held to the same rules from its first
    commit, and not only once the release renames the heading.
    """
    matches = list(ENTRY.finditer(changelog))
    entries = {}
    for match, following in zip(matches, matches[1:] + [None], strict=True):
        end = following.start() if following else len(changelog)
        heading = match.group(0).removeprefix("## ").strip()
        entries[match.group("version")] = (heading, changelog[match.end() : end])
    unreleased = UNRELEASED.search(changelog)
    if unreleased:
        assert matches and unreleased.end() <= matches[0].start(), "[Unreleased] comes first"
        body = changelog[unreleased.end() : matches[0].start()]
        entries[_next_minor(matches[0].group("version"))] = ("[Unreleased]", body)
    return entries


ENTRIES = _entries(CHANGELOG)
BREAKING = {v for v, (_, body) in ENTRIES.items() if re.search(r"\bbreaking\b", body, re.I)}
UPGRADING_SECTIONS = {v for v, (_, body) in ENTRIES.items() if "### Upgrading" in body}


def _minor(version: str) -> str:
    return version.rsplit(".", 1)[0]


def test_the_changelog_parses():
    assert "0.91.0" in ENTRIES and "0.91.0" in BREAKING and "0.91.0" in UPGRADING_SECTIONS


def test_unreleased_is_checked_as_the_next_minor():
    changelog = (
        "# Changelog\n\n## [Unreleased]\n\nBreaking: x.\n\n"
        "## [0.98.1] - 2026-10-31\n\nFixed.\n\n## [0.98.0] - 2026-10-30\n\nAdded.\n"
    )
    entries = _entries(changelog)
    assert entries["0.99.0"] == ("[Unreleased]", "\nBreaking: x.\n\n")
    assert entries["0.98.1"] == ("[0.98.1] - 2026-10-31", "\nFixed.\n\n")
    assert "0.99.0" not in _entries(changelog.replace("## [Unreleased]\n\nBreaking: x.\n\n", ""))


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
