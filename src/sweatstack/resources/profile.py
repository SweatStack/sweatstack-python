"""``client.profile``: ``/api/v1/profile/...``, the user the client acts as."""

from __future__ import annotations

from functools import cached_property

from ..schemas import AccountStatusResponse, Sport
from ._app_metadata import ProfileAppMetadata
from ._base import Resource


class Profile(Resource):
    """The user the client acts as: account status, sports, tags and app metadata."""

    @cached_property
    def app_metadata(self) -> ProfileAppMetadata:
        """This app's metadata on the user: ``set(data=...)`` and ``delete()``."""
        return ProfileAppMetadata(self._client)

    def status(self) -> AccountStatusResponse:
        """Retrieves why the user may have little or no data, and what the account can supply.

        Endpoint: ``GET /api/v1/profile/status``

        **Beta**: the server documents this endpoint as beta.

        ``issue`` is ``None`` when there is nothing to tell the user, otherwise
        ``{code, status, message, action_url}``. Branch on ``issue.status``
        (:class:`CapabilityStatus`: ``ready``, ``syncing``, ``action_required``,
        ``unavailable``), show ``issue.message``, and show a button only when
        ``issue.action_url`` is set. Don't parse ``message`` or branch on ``code``.

        ``capabilities`` maps each :class:`Capability` (``activities``, ``activity_history``,
        ``dailies``, ``workouts``) to a :class:`CapabilityStatus`. Codes and capability keys are
        open sets: a value the client doesn't know parses as a pseudo-member; ignore it.

        Accepts a token with ``data:read`` or ``profile``. Delegated tokens are allowed and
        always get ``action_url=None``.

        Returns:
            AccountStatusResponse: ``issue`` and ``capabilities``.

        Raises:
            SweatStackAuthError: If the token has neither ``data:read`` nor ``profile``.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            status = client.profile.status()
            if status.issue:
                print(status.issue.message, status.issue.action_url)
            ```
        """
        response = self._client._request("get", "/api/v1/profile/status")
        return AccountStatusResponse.model_validate(response.json())

    def sports(self, *, only_root: bool = False) -> list[Sport]:
        """Lists the sports the user has activities in.

        Endpoint: ``GET /api/v1/profile/sports/``

        Args:
            only_root: Only top-level sports (``cycling``, not ``cycling.road``).

        Returns:
            list[Sport]: The sports. A sport newer than the installed taxonomy is still
            returned (``Sport.parse``), with ``is_standard`` set to ``False``.

        Raises:
            SweatStackAPIError: If the API request fails.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            print([sport.label for sport in client.profile.sports(only_root=True)])
            ```
        """
        params = {"only_root": True} if only_root else {}
        response = self._client._request("get", "/api/v1/profile/sports/", params=params)
        return [Sport.parse(sport) for sport in response.json()]

    def tags(self) -> list[str]:
        """Lists the tags the user has used on activities, traces and tests.

        Endpoint: ``GET /api/v1/profile/tags/``

        Returns:
            list[str]: The tags.

        Raises:
            SweatStackAPIError: If the API request fails.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            print(client.profile.tags())
            ```
        """
        return self._client._request("get", "/api/v1/profile/tags/").json()
