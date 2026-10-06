"""The upgrade path for removed names (``sweatstack/_renames.py``).

A removed method must be gone, must raise an error naming its replacement, and must appear in
the CHANGELOG, so code written against an older release (or an agent's stale training data)
fails with a fix rather than a bare ``AttributeError``.
"""

import re
from pathlib import Path

import pytest

import sweatstack
from sweatstack._renames import REMOVED_IN
from sweatstack.client import Client

CHANGELOG = (Path(__file__).resolve().parent.parent / "CHANGELOG.md").read_text()


@pytest.mark.parametrize("name", sorted(REMOVED_IN))
def test_removed_name_is_gone_from_the_client(name):
    assert name not in dir(Client)


@pytest.mark.parametrize("name", sorted(REMOVED_IN))
def test_client_error_names_the_replacement(name):
    release, hint = REMOVED_IN[name]
    with pytest.raises(AttributeError) as error:
        getattr(Client(api_key="x"), name)
    message = str(error.value)
    assert f"removed in {release}" in message
    assert hint.format(c="client") in message


@pytest.mark.parametrize("name", sorted(REMOVED_IN))
def test_module_error_names_the_replacement(name):
    _, hint = REMOVED_IN[name]
    with pytest.raises(AttributeError) as error:
        getattr(sweatstack, name)
    assert hint.format(c="sweatstack") in str(error.value)


@pytest.mark.parametrize("name", sorted(REMOVED_IN))
def test_removed_name_is_in_its_changelog_entry(name):
    release, _ = REMOVED_IN[name]
    entry = re.search(rf"^## \[{re.escape(release)}\.0\].*?(?=^## \[)", CHANGELOG, re.M | re.S)
    assert entry, f"no CHANGELOG entry for {release}"
    assert f"`{name}`" in entry.group(0) or f"`client.{name}`" in entry.group(0)


def test_unknown_names_still_raise_plain_attribute_errors():
    with pytest.raises(AttributeError, match="no attribute 'nope'$"):
        Client(api_key="x").nope  # noqa: B018
    with pytest.raises(AttributeError, match="no attribute 'nope'$"):
        sweatstack.nope  # noqa: B018


def test_hasattr_and_getattr_defaults_keep_working():
    client = Client(api_key="x")
    assert not hasattr(client, "get_activities")
    assert getattr(client, "get_activities", None) is None
