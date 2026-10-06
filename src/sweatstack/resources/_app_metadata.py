"""Per-app JSON metadata: ``.../{id}/app-metadata`` and ``/profile/app-metadata``.

Two classes rather than one with an optional ID: activities, traces and tests always need the
record's ID, and the profile never has one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._base import Resource

if TYPE_CHECKING:
    from ..client import Client


class AppMetadata(Resource):
    """This app's metadata on activities, traces or tests. Requires an app token."""

    def __init__(self, client: Client, collection: str) -> None:
        super().__init__(client)
        self._collection = collection

    def set(self, record_id: str, *, data: dict[str, Any]) -> None:
        """Replaces this app's metadata on a record.

        Endpoint: ``PUT /api/v1/{activities|traces|tests}/{id}/app-metadata``

        The whole dict is replaced; there is no merge. Each app sees only its own metadata,
        and it appears as ``app_metadata`` on the record when read with an app token.

        Args:
            record_id: The activity, trace or test ID.
            data: Any JSON-serialisable dict, at most 1 KB and 32 levels deep.

        Raises:
            SweatStackAuthError: If the client does not hold an app token (403). A personal
                token, from ``authenticate()`` or an API key, never qualifies.
            SweatStackBadRequestError: If ``data`` is too large (413) or too deep (422).
            SweatStackNotFoundError: If the record does not exist.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client(api_key="app-user-token")  # e.g. user.client in FastAPI
            client.activities.app_metadata.set("act_123", data={"reviewed": True})
            ```
        """
        self._client._request(
            "put", f"/api/v1/{self._collection}/{record_id}/app-metadata", json=data
        )

    def delete(self, record_id: str) -> None:
        """Deletes this app's metadata from a record.

        Endpoint: ``DELETE /api/v1/{activities|traces|tests}/{id}/app-metadata``

        Args:
            record_id: The activity, trace or test ID.

        Raises:
            SweatStackAuthError: If the client does not hold an app token (403).
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client(api_key="app-user-token")
            client.activities.app_metadata.delete("act_123")
            ```
        """
        self._client._request("delete", f"/api/v1/{self._collection}/{record_id}/app-metadata")


class ProfileAppMetadata(Resource):
    """This app's metadata on the signed-in user. Requires an app token."""

    def set(self, *, data: dict[str, Any]) -> None:
        """Replaces this app's metadata on the user the client acts as.

        Endpoint: ``PUT /api/v1/profile/app-metadata``

        Args:
            data: Any JSON-serialisable dict, at most 4 KB and 32 levels deep.

        Raises:
            SweatStackAuthError: If the client does not hold an app token (403).
            SweatStackBadRequestError: If ``data`` is too large (413) or too deep (422).
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client(api_key="app-user-token")
            client.profile.app_metadata.set(data={"onboarded": True})
            ```
        """
        self._client._request("put", "/api/v1/profile/app-metadata", json=data)

    def delete(self) -> None:
        """Deletes this app's metadata from the user the client acts as.

        Endpoint: ``DELETE /api/v1/profile/app-metadata``

        Raises:
            SweatStackAuthError: If the client does not hold an app token (403).
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client(api_key="app-user-token")
            client.profile.app_metadata.delete()
            ```
        """
        self._client._request("delete", "/api/v1/profile/app-metadata")
