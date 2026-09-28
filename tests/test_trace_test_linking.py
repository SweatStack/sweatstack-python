"""Tests for the trace <-> test linking surface.

Covers:

- ``test_id`` round-trips through ``TraceDetails`` and ``TraceCreateOrUpdate``.
- ``TraceResolution`` enum wire values are exactly ``"auto"`` / ``"linked"``
  (these are what the server's query parameter accepts).
- ``TraceResolution`` is exposed on the public package surface.
"""

from datetime import datetime, timezone

import sweatstack
from sweatstack import TraceDetails, TraceResolution
from sweatstack.openapi_schemas import TraceCreateOrUpdate


def _trace_details(**overrides) -> TraceDetails:
    base = dict(
        id="trace_001",
        timestamp=datetime(2026, 3, 15, 9, 30, tzinfo=timezone.utc),
        timestamp_local=datetime(2026, 3, 15, 10, 30),
    )
    base.update(overrides)
    return TraceDetails(**base)


class TestTestIdField:
    def test_trace_details_round_trip_with_test_id(self):
        original = _trace_details(test_id="test_123", lactate=4.2)
        restored = TraceDetails.model_validate(original.model_dump())

        assert restored.test_id == "test_123"
        assert restored.lactate == 4.2

    def test_trace_details_test_id_defaults_to_none(self):
        trace = _trace_details()
        assert trace.test_id is None

    def test_trace_create_or_update_accepts_test_id(self):
        payload = TraceCreateOrUpdate(
            timestamp=datetime(2026, 3, 15, 9, 30, tzinfo=timezone.utc),
            lactate=4.2,
            test_id="test_123",
        )

        dumped = payload.model_dump()
        assert dumped["test_id"] == "test_123"

    def test_trace_create_or_update_test_id_defaults_to_none(self):
        payload = TraceCreateOrUpdate(
            timestamp=datetime(2026, 3, 15, 9, 30, tzinfo=timezone.utc),
        )

        assert payload.test_id is None
        assert payload.model_dump()["test_id"] is None


class TestGetTestTraceResolution:
    """``get_test`` should accept both the enum and the bare string for
    ``trace_resolution`` (mirroring how ``sport``, ``measure`` etc. work
    elsewhere in the client)."""

    def _build_client(self):
        from sweatstack.client import Client

        return Client.__new__(Client)

    def test_enum_input(self):
        client = self._build_client()
        assert client._enums_to_strings([TraceResolution.linked]) == ["linked"]

    def test_string_input(self):
        client = self._build_client()
        assert client._enums_to_strings(["linked"]) == ["linked"]


class TestTraceResolutionEnum:
    def test_wire_values(self):
        """The wire values must match the server's query parameter exactly."""
        assert TraceResolution.auto.value == "auto"
        assert TraceResolution.linked.value == "linked"

    def test_membership(self):
        """Guards against accidental additions/removals on regen."""
        assert {m.value for m in TraceResolution} == {"auto", "linked"}

    def test_publicly_exported(self):
        """Importable from the top-level package, like other enums (e.g. Sport)."""
        assert sweatstack.TraceResolution is TraceResolution
