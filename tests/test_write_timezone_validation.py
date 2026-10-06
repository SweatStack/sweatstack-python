"""The write methods reject timezone-naive datetimes before hitting the API.

The server stores every timestamp as an absolute instant plus its local offset
and rejects naive datetimes with HTTP 422. The client guards the same contract
at the call site (``Client._require_aware``) so callers get a clear, immediate
error naming the offending argument instead of an opaque server response.

All offline: the guard runs before ``_http_client`` is ever touched, so a bare
``Client.__new__(Client)`` instance is enough.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from sweatstack import Sport
from sweatstack.client import Client

NAIVE = datetime(2026, 3, 15, 9, 0)
AWARE_UTC = datetime(2026, 3, 15, 9, 0, tzinfo=timezone.utc)
AWARE_ZONE = datetime(2026, 3, 15, 9, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))


class TestRequireAware:
    def test_naive_rejected_with_helpful_message(self):
        with pytest.raises(ValueError) as excinfo:
            Client._require_aware(NAIVE, "timestamp")
        message = str(excinfo.value)
        assert "timestamp" in message
        assert "timezone-aware" in message

    @pytest.mark.parametrize("value", [AWARE_UTC, AWARE_ZONE])
    def test_aware_passes_through_unchanged(self, value: datetime):
        assert Client._require_aware(value, "timestamp") is value


class TestTraceWritesRejectNaive:
    def test_create_trace_rejects_naive_timestamp(self):
        client = Client.__new__(Client)
        with pytest.raises(ValueError, match="timestamp must be timezone-aware"):
            client.create_trace(timestamp=NAIVE, lactate=2.0)

    def test_update_trace_rejects_naive_timestamp(self):
        client = Client.__new__(Client)
        with pytest.raises(ValueError, match="timestamp must be timezone-aware"):
            client.update_trace("trace_1", timestamp=NAIVE, lactate=2.0)


class TestTestWritesRejectNaive:
    def test_create_test_rejects_naive_start(self):
        client = Client.__new__(Client)
        with pytest.raises(ValueError, match="start must be timezone-aware"):
            client.create_test(sport=Sport("cycling"), start=NAIVE)

    def test_create_test_rejects_naive_end(self):
        client = Client.__new__(Client)
        with pytest.raises(ValueError, match="end must be timezone-aware"):
            client.create_test(sport=Sport("cycling"), start=AWARE_UTC, end=NAIVE)

    def test_update_test_rejects_naive_start(self):
        client = Client.__new__(Client)
        with pytest.raises(ValueError, match="start must be timezone-aware"):
            client.update_test("test_1", sport=Sport("cycling"), start=NAIVE)

    def test_update_test_rejects_naive_end(self):
        client = Client.__new__(Client)
        with pytest.raises(ValueError, match="end must be timezone-aware"):
            client.update_test("test_1", sport=Sport("cycling"), start=AWARE_UTC, end=NAIVE)
