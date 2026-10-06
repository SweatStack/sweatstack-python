"""``client.teams``: ``/api/v1/teams/...``."""

from __future__ import annotations

import builtins
from typing import Any

from ..schemas import AuthorizedTeamResponse, Scope, TeamResponse, UserSummary
from ._base import Resource
from .users import filter_by_name


class Teams(Resource):
    """Teams: the ones you belong to, and the ones you authorised to access your data."""

    def list(self) -> builtins.list[TeamResponse]:
        """Lists the teams you own or are a member of.

        Endpoint: ``GET /api/v1/teams/``

        Returns:
            list[TeamResponse]: The teams, each with your role.

        Raises:
            SweatStackAPIError: If the API request fails.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            for team in client.teams.list():
                print(team.name)
            ```
        """
        response = self._client._request("get", "/api/v1/teams/")
        return [TeamResponse.model_validate(team) for team in response.json()]

    def users(self, team_id: str, *, name: str | None = None) -> builtins.list[UserSummary]:
        """Lists the users who authorised a team to access their data. Team members only.

        Endpoint: ``GET /api/v1/teams/{team_id}/users``

        Args:
            team_id: The team's ID.
            name: Only users whose display name contains this, ignoring case. Returns every
                match, so check the length before picking one.

        Returns:
            list[UserSummary]: The users, with the scopes they granted.

        Raises:
            SweatStackNotFoundError: If the team does not exist.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            team = client.teams.list()[0]
            for athlete in client.teams.users(team.id):
                athlete_client = client.delegated_client(athlete, team_id=team.id)
            ```
        """
        params = {"name": name} if name is not None else {}
        response = self._client._request("get", f"/api/v1/teams/{team_id}/users", params=params)
        return filter_by_name((UserSummary.model_validate(u) for u in response.json()), name)

    def authorized(self) -> builtins.list[AuthorizedTeamResponse]:
        """Lists the teams you authorised to access your data.

        Endpoint: ``GET /api/v1/teams/authorized``

        Returns:
            list[AuthorizedTeamResponse]: The teams, with the scopes you granted.

        Raises:
            SweatStackAPIError: If the API request fails.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            print([team.name for team in client.teams.authorized()])
            ```
        """
        response = self._client._request("get", "/api/v1/teams/authorized")
        return [AuthorizedTeamResponse.model_validate(team) for team in response.json()]

    def authorize(
        self, team_id: str, *, scopes: builtins.list[Scope | str] | None = None
    ) -> dict[str, Any]:
        """Authorises a team to access your data (or, on a delegated client, that user's data).

        Endpoint: ``POST /api/v1/teams/{team_id}/authorize``

        Args:
            team_id: The team's ID.
            scopes: The scopes to grant. Defaults to ``[Scope.data_read]``.

        Returns:
            dict: ``team_id``, ``user_id`` and the granted ``scopes``.

        Raises:
            SweatStackNotFoundError: If the team does not exist.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            client.teams.authorize("team_123", scopes=["data:read"])
            ```
        """
        wire = self._client._enums_to_strings(list(scopes or [Scope.data_read]))
        response = self._client._request(
            "post", f"/api/v1/teams/{team_id}/authorize", json={"scopes": wire}
        )
        return response.json()
