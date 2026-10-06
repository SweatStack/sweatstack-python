"""The agent skill (``skills/sweatstack-python``) covers the whole public API.

``api.md`` is the skill's map of every method; a method missing from it is a method agents
won't find. The resource tree is walked statically, through the typed ``cached_property``
attributes, the same way the snippet check resolves ``client.activities.longitudinal.data``.
"""

import inspect
import re
import typing
from functools import cached_property
from pathlib import Path

from sweatstack.client import Client

SKILL = Path(__file__).resolve().parent.parent / "skills" / "sweatstack-python"


def _public_paths(cls: type, prefix: str) -> typing.Iterator[str]:
    for name, member in vars(cls).items():
        if name.startswith("_"):
            continue
        if isinstance(member, cached_property):
            child = typing.get_type_hints(member.func)["return"]
            yield from _public_paths(child, f"{prefix}.{name}")
        elif inspect.isfunction(member) and cls is not Client:
            yield f"{prefix}.{name}"


API_PATHS = sorted(_public_paths(Client, "client"))


def test_the_walk_finds_the_whole_tree():
    assert "client.activities.longitudinal.mean_max" in API_PATHS
    assert "client.portal.sessions.create" in API_PATHS
    assert "client.profile.app_metadata.delete" in API_PATHS
    assert len(API_PATHS) > 40


def test_api_map_lists_every_method():
    api_md = (SKILL / "api.md").read_text()
    missing = [path for path in API_PATHS if f"{path}(" not in api_md]
    assert not missing, f"skills/sweatstack-python/api.md is missing: {missing}"


def test_skill_links_resolve():
    for page in SKILL.glob("*.md"):
        for target in re.findall(r"\]\(([a-z_-]+\.md)", page.read_text()):
            assert (SKILL / target).exists(), f"{page.name} links to missing {target}"
