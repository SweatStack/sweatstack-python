"""Tests for the Teams listing functionality.

Tests schema round-trips and enum handling for TeamResponse and
AuthorizedTeamResponse without hitting the API.
"""

import pytest

from sweatstack import ApplicationMemberRole, AuthorizedTeamResponse, Scope, TeamResponse

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_team() -> TeamResponse:
    return TeamResponse(
        id="team_001",
        name="Cycling Club",
        description="Local cycling team",
        url="https://example.com",
        image="https://example.com/logo.png",
        privacy_statement="https://example.com/privacy",
        role=ApplicationMemberRole.owner,
    )


@pytest.fixture
def sample_authorized_team() -> AuthorizedTeamResponse:
    return AuthorizedTeamResponse(
        id="team_002",
        name="Coach Platform",
        description="Coaching service",
        url="https://coach.example.com",
        image="https://coach.example.com/logo.png",
        privacy_statement="https://coach.example.com/privacy",
        scopes=[Scope.data_read],
    )


# ---------------------------------------------------------------------------
# Schema round-trip tests
# ---------------------------------------------------------------------------


class TestSchemaRoundTrip:
    def test_team_response_round_trip(self, sample_team: TeamResponse):
        """TeamResponse should survive serialize -> deserialize."""
        dumped = sample_team.model_dump()
        restored = TeamResponse.model_validate(dumped)

        assert restored.id == "team_001"
        assert restored.name == "Cycling Club"
        assert restored.role == ApplicationMemberRole.owner

    def test_team_response_null_role(self):
        """TeamResponse with null role should round-trip cleanly."""
        team = TeamResponse(
            id="team_001",
            name="Test",
            description="Test",
            url="https://example.com",
            image="https://example.com/img.png",
            privacy_statement="https://example.com/privacy",
            role=None,
        )
        dumped = team.model_dump()
        restored = TeamResponse.model_validate(dumped)

        assert restored.role is None

    def test_authorized_team_response_round_trip(
        self, sample_authorized_team: AuthorizedTeamResponse
    ):
        """AuthorizedTeamResponse should survive serialize -> deserialize."""
        dumped = sample_authorized_team.model_dump()
        restored = AuthorizedTeamResponse.model_validate(dumped)

        assert restored.id == "team_002"
        assert restored.name == "Coach Platform"
        assert restored.scopes == [Scope.data_read]

    def test_authorized_team_multiple_scopes(self):
        """AuthorizedTeamResponse with multiple scopes should round-trip."""
        team = AuthorizedTeamResponse(
            id="team_003",
            name="Full Access",
            description="Test",
            url="https://example.com",
            image="https://example.com/img.png",
            privacy_statement="https://example.com/privacy",
            scopes=[Scope.data_read, Scope.data_write],
        )
        dumped = team.model_dump()
        restored = AuthorizedTeamResponse.model_validate(dumped)

        assert len(restored.scopes) == 2
        assert Scope.data_read in restored.scopes
        assert Scope.data_write in restored.scopes


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestApplicationMemberRole:
    def test_role_values(self):
        """ApplicationMemberRole should have owner and member."""
        assert ApplicationMemberRole.owner.value == "owner"
        assert ApplicationMemberRole.member.value == "member"
