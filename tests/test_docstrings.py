"""Every public resource method documents its endpoint and shows an example.

The endpoint line (``Endpoint: ``GET /api/v1/...````) links each method to the REST API, in the
installed package and in the docs reference; the ``Examples:`` block is what editors, the docs
and coding agents show first. Both are part of the method template in AGENTS.md.
"""

import inspect
import re

import pytest

from sweatstack import resources
from sweatstack.client import Client

ENDPOINT = re.compile(r"^\s*Endpoint: ``(GET|POST|PUT|DELETE) /(api/v1/|oauth/)\S*``$", re.M)

# Methods that call no endpoint of their own.
NO_ENDPOINT = {"OAuth.generate_pkce_params"}

# Client-level methods that are part of the public surface and need an example too.
CLIENT_METHODS = ["authenticate", "delegated_client", "principal_client", "whoami", "clear_cache"]


def _resource_methods():
    for cls_name in resources.__all__:
        cls = getattr(resources, cls_name)
        for name, member in vars(cls).items():
            if not name.startswith("_") and inspect.isfunction(member):
                yield f"{cls_name}.{name}", member


RESOURCE_METHODS = dict(_resource_methods())


def test_the_inventory_is_not_empty():
    assert len(RESOURCE_METHODS) > 40


@pytest.mark.parametrize("name", sorted(RESOURCE_METHODS))
def test_endpoint_line(name):
    if name in NO_ENDPOINT:
        return
    doc = inspect.getdoc(RESOURCE_METHODS[name]) or ""
    assert len(ENDPOINT.findall(doc)) == 1, (
        f"{name}: needs exactly one 'Endpoint: ``VERB /path``' line"
    )


@pytest.mark.parametrize("name", sorted(RESOURCE_METHODS))
def test_path_parameters_keep_their_wire_names(name):
    """R8: ``{activity_id}`` in the endpoint is the method's ``activity_id`` parameter."""
    doc = inspect.getdoc(RESOURCE_METHODS[name]) or ""
    endpoint = ENDPOINT.search(doc)
    if not endpoint:
        return
    path_params = set(re.findall(r"\{(\w+)\}", endpoint.group(0)))
    missing = path_params - set(inspect.signature(RESOURCE_METHODS[name]).parameters)
    assert not missing, f"{name}: name the parameter(s) {sorted(missing)} as in the endpoint"


@pytest.mark.parametrize("name", sorted(RESOURCE_METHODS))
def test_resource_method_has_an_example(name):
    doc = inspect.getdoc(RESOURCE_METHODS[name]) or ""
    assert "\nExamples:\n" in doc and "```python" in doc, f"{name}: needs an Examples: block"


@pytest.mark.parametrize("name", CLIENT_METHODS)
def test_client_method_has_an_example(name):
    doc = inspect.getdoc(getattr(Client, name)) or ""
    assert "\nExamples:\n" in doc and "```python" in doc, f"Client.{name}: needs an Examples: block"
