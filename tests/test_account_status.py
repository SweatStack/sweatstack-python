"""Account status: ``userinfo.issue`` and ``GET /api/v1/profile/status``.

The fixtures are the five payloads the public docs prescribe for mocking
("Why does this user have no data?"), verbatim, so these tests pin the SDK to
the documented contract rather than to our reading of it.
"""

from unittest.mock import MagicMock, patch

import httpx
import polars as pl
import pytest
from pydantic import ValidationError

from sweatstack import (
    AccountStatusResponse,
    Capability,
    CapabilityStatus,
    StatusIssueCode,
    StatusIssueResponse,
    UserInfoResponse,
)
from sweatstack._frames import polars_schema
from sweatstack.client import Client
from sweatstack.exceptions import SweatStackAuthError

DOCS_PAYLOADS = {
    "nothing_connected": {
        "issue": {
            "code": "no_source_connected",
            "status": "action_required",
            "message": "No data source is connected yet.",
            "action_url": "https://app.sweatstack.no/portal/integrations?app=x",
        }
    },
    "still_syncing": {
        "issue": {
            "code": "sync_pending",
            "status": "syncing",
            "message": "Garmin Connect data is still arriving.",
            "action_url": None,
        }
    },
    "history_not_shared": {
        "issue": {
            "code": "activity_history_not_granted",
            "status": "action_required",
            "message": "Garmin Connect isn't sharing past activities.",
            "action_url": "https://app.sweatstack.no/portal/integrations?app=x",
        }
    },
    "permanently_limited": {
        "issue": {
            "code": "dailies_unavailable",
            "status": "unavailable",
            "message": "No connected source provides daily health data.",
            "action_url": None,
        }
    },
    "all_good": {"issue": None},
}

CAPABILITIES = {
    "activities": "ready",
    "activity_history": "action_required",
    "dailies": "unavailable",
    "workouts": "ready",
}

USERINFO = {
    "sub": "01JQ8",
    "name": "Alice Anderson",
    "given_name": "Alice",
    "family_name": "Anderson",
    "email": "a@example.com",
    "registered_at": "2025-01-01T00:00:00Z",
}


@pytest.fixture
def client():
    c = Client.__new__(Client)
    c.url = "https://test.sweatstack.no"
    c._api_key = None
    c.streamlit_compatible = False
    c.skip_token_expiry_check = True
    return c


def _http_returning(status_code: int, payload) -> MagicMock:
    request = httpx.Request("GET", "https://test.sweatstack.no/api/v1/profile/status")
    response = httpx.Response(status_code, json=payload, request=request)
    http = MagicMock()
    http.__enter__ = MagicMock(return_value=http)
    http.__exit__ = MagicMock(return_value=False)
    http.get.return_value = response
    return http


class TestDocumentedPayloads:
    @pytest.mark.parametrize("payload", DOCS_PAYLOADS.values(), ids=DOCS_PAYLOADS.keys())
    def test_userinfo_round_trip(self, payload):
        user = UserInfoResponse.model_validate({**USERINFO, **payload})
        restored = UserInfoResponse.model_validate(user.model_dump())
        assert restored == user
        if payload["issue"] is None:
            assert user.issue is None
        else:
            assert isinstance(user.issue, StatusIssueResponse)
            assert user.issue.status == CapabilityStatus(payload["issue"]["status"])
            assert user.issue.code == StatusIssueCode(payload["issue"]["code"])
            assert user.issue.message == payload["issue"]["message"]
            assert user.issue.action_url == payload["issue"]["action_url"]

    @pytest.mark.parametrize("payload", DOCS_PAYLOADS.values(), ids=DOCS_PAYLOADS.keys())
    def test_profile_status_round_trip(self, payload):
        status = AccountStatusResponse.model_validate({**payload, "capabilities": CAPABILITIES})
        restored = AccountStatusResponse.model_validate(status.model_dump())
        assert restored == status
        assert status.capabilities[Capability.activity_history] == CapabilityStatus.action_required
        assert status.capabilities.get(Capability.dailies) == CapabilityStatus.unavailable

    def test_the_one_line_integration_reads_naturally(self):
        user = UserInfoResponse.model_validate({**USERINFO, **DOCS_PAYLOADS["history_not_shared"]})
        shown = []
        if user.issue:
            shown.append((user.issue.message, user.issue.action_url))
        assert shown == [
            (
                "Garmin Connect isn't sharing past activities.",
                "https://app.sweatstack.no/portal/integrations?app=x",
            )
        ]

    def test_action_url_absent_means_no_button(self):
        user = UserInfoResponse.model_validate({**USERINFO, **DOCS_PAYLOADS["still_syncing"]})
        assert user.issue is not None and user.issue.action_url is None


class TestOpenSets:
    """Codes and capability keys are open sets by contract; the status set is closed."""

    def test_unknown_code_parses_as_pseudo_member(self):
        issue = StatusIssueResponse.model_validate(
            {"code": "something_new", "status": "action_required", "message": "x"}
        )
        assert issue.code.value == "something_new"
        assert StatusIssueCode("something_new") is issue.code  # cached
        assert StatusIssueResponse.model_validate(issue.model_dump()).code == issue.code

    def test_unknown_capability_key_parses_and_known_keys_still_resolve(self):
        status = AccountStatusResponse.model_validate(
            {"issue": None, "capabilities": {**CAPABILITIES, "dailies_history": "syncing"}}
        )
        assert status.capabilities[Capability("dailies_history")] == CapabilityStatus.syncing
        assert status.capabilities[Capability.activities] == CapabilityStatus.ready

    def test_unknown_status_is_rejected(self):
        with pytest.raises(ValidationError):
            StatusIssueResponse.model_validate(
                {"code": "sync_pending", "status": "fifth_value", "message": "x"}
            )

    def test_capabilities_map_is_json_text_in_a_frame(self):
        # A map keyed by an open enum has no fixed columns; the frame path keeps it as JSON text.
        assert polars_schema(AccountStatusResponse)["capabilities"] == pl.String


class TestGetProfileStatus:
    def test_calls_the_endpoint_and_returns_the_model(self, client):
        http = _http_returning(
            200, {**DOCS_PAYLOADS["nothing_connected"], "capabilities": CAPABILITIES}
        )
        with patch.object(client, "_http_client", return_value=http):
            status = client.profile.status()
        assert http.get.call_args.kwargs["url"] == "/api/v1/profile/status"
        assert isinstance(status, AccountStatusResponse)
        assert status.issue.code == StatusIssueCode.no_source_connected

    def test_missing_scope_is_an_auth_error(self, client):
        http = _http_returning(403, {"detail": "Not enough permissions"})
        with (
            patch.object(client, "_http_client", return_value=http),
            pytest.raises(SweatStackAuthError),
        ):
            client.profile.status()

    def test_has_no_output_parameter(self, client):
        # Control-plane methods return models whatever the configured output.
        client.output = "polars"
        http = _http_returning(200, {"issue": None, "capabilities": CAPABILITIES})
        with patch.object(client, "_http_client", return_value=http):
            assert isinstance(client.profile.status(), AccountStatusResponse)
        with pytest.raises(TypeError):
            client.profile.status(output="polars")
