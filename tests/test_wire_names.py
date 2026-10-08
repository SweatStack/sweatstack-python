"""Every resource method's parameters are the wire names of its endpoint (AGENTS.md, R8).

Runs only when ``SWEATSTACK_OPENAPI_JSON`` points at a saved OpenAPI document (offline, like
every other test): part of the regen procedure in DEVELOPMENT.md. For each method it reads the
``Endpoint:`` line, looks the operation up in the document, and compares the method's
parameters with the operation's path, query and body parameters. The deliberate deviations
listed in AGENTS.md are the only names allowed to differ.
"""

from __future__ import annotations

import inspect
import json
import os
import re
from pathlib import Path

import pytest

from sweatstack import resources

ENDPOINT = re.compile(r"Endpoint: ``(\w+) (\S+?)``")

# Auth plumbing the server adds to every operation; never a method parameter.
AUTH_PARAMS = {"token", "refreshed-token"}

# SDK-level parameters (AGENTS.md "Deliberate deviations") and their wire counterparts, if any.
SDK_ONLY = {"output", "limit", "offset", "persist", "auto_reconnect"}
RENAMED = {"trace_resolution": "traces"}  # SDK name -> wire name

# Wire parameters the SDK leaves out on purpose, per method.
NOT_EXPOSED = {
    "Longitudinal.mean_max": {"date", "window_days"},  # deprecated on the server
    "Longitudinal.awd": {"date", "window_days", "format"},  # output= chooses the format
    "OAuth.exchange_code": {"grant_type", "refresh_token"},  # set by the method / another grant
    "PortalSessions.create": {"client_id", "client_secret"},  # from the client's app credentials
}
# SDK parameters with no wire counterpart yet (AGENTS.md: client-side name filter).
CLIENT_SIDE = {"Users.list": {"name"}, "Teams.users": {"name"}}
# Whole-body parameters: the method sends the dict as the body.
BODY_PARAM = {"data"}

SPEC = os.environ.get("SWEATSTACK_OPENAPI_JSON")
pytestmark = pytest.mark.skipif(not SPEC, reason="set SWEATSTACK_OPENAPI_JSON=path/to/openapi.json")


def _operations() -> dict[tuple[str, str], dict]:
    spec = json.loads(Path(SPEC).read_text())  # type: ignore[arg-type]
    schemas = spec["components"]["schemas"]

    def deref(schema: dict) -> dict:
        while "$ref" in schema:
            schema = schemas[schema["$ref"].split("/")[-1]]
        return schema

    ops = {}
    for path, methods in spec["paths"].items():
        for verb, op in methods.items():
            names = {p["name"] for p in op.get("parameters", [])}
            body = op.get("requestBody", {}).get("content", {})
            for content in body.values():
                names |= set(deref(content["schema"]).get("properties", {}))
            ops[(verb.upper(), path.rstrip("/"))] = names - AUTH_PARAMS
    return ops


def _methods():
    for cls_name in resources.__all__:
        cls = getattr(resources, cls_name)
        for name, member in vars(cls).items():
            if name.startswith("_") or not inspect.isfunction(member):
                continue
            match = ENDPOINT.search(inspect.getdoc(member) or "")
            if match and "|" not in match.group(2):
                yield f"{cls_name}.{name}", member, match.group(1), match.group(2)


@pytest.mark.parametrize(
    "name,method,verb,path", list(_methods()), ids=lambda x: x if isinstance(x, str) else ""
)
def test_parameters_are_wire_names(name, method, verb, path):
    ops = _operations()
    key = (verb, path.split("?")[0].rstrip("/"))
    if key not in ops:
        pytest.skip(f"{verb} {path} is not in the document (dev-only or non-API route)")
    wire = ops[key]
    sdk = {p for p in inspect.signature(method).parameters if p != "self"}
    sdk = {RENAMED.get(p, p) for p in sdk - SDK_ONLY - BODY_PARAM - CLIENT_SIDE.get(name, set())}
    not_on_wire = sdk - wire
    assert not not_on_wire, f"{name}: not on the wire: {sorted(not_on_wire)}"
    # limit/offset are SDK-level where the server has them too; the rest is listed per method.
    not_in_sdk = wire - sdk - SDK_ONLY - NOT_EXPOSED.get(name, set())
    assert not not_in_sdk, f"{name}: on the wire but not in the SDK: {sorted(not_in_sdk)}"
