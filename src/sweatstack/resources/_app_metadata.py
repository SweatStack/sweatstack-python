"""Per-app JSON metadata: ``/{activities|traces|tests}/{id}/app-metadata`` and
``/profile/app-metadata``.

One class per endpoint, so each ID parameter has the API's name (``activity_id``, ``trace_id``,
``test_id``; rule R8) and each docstring names its own endpoint. ``_RecordAppMetadata`` holds the
two requests they share.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._base import Resource

if TYPE_CHECKING:
    pass


class _RecordAppMetadata(Resource):
    _collection: str

    def _put(self, record_id: str, data: dict[str, Any]) -> None:
        self._client._request(
            "put", f"/api/v1/{self._collection}/{record_id}/app-metadata", json=data
        )

    def _delete(self, record_id: str) -> None:
        self._client._request("delete", f"/api/v1/{self._collection}/{record_id}/app-metadata")


class ActivityAppMetadata(_RecordAppMetadata):
    """This app's metadata on activitys. Requires an app token."""

    _collection = "activities"

    def set(self, activity_id: str, *, data: dict[str, Any]) -> None:
        """Replaces this app's metadata on an activity.

        Endpoint: ``PUT /api/v1/activities/{activity_id}/app-metadata``

        The whole dict is replaced; there is no merge. Each app sees only its own metadata,
        and it appears as ``app_metadata`` on the activity when read with an app token.

        Args:
            activity_id: The activity's ID.
            data: Any JSON-serialisable dict, at most 1 KB and 32 levels deep.

        Raises:
            SweatStackAuthError: If the client does not hold an app token (403). A personal
                token, from ``authenticate()`` or an API key, never qualifies.
            SweatStackBadRequestError: If ``data`` is too large (413) or too deep (422).
            SweatStackNotFoundError: If the activity does not exist.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client(api_key="app-user-token")  # e.g. user.client in FastAPI
            client.activities.app_metadata.set("act_123", data={"reviewed": True})
            ```
        """
        self._put(activity_id, data)

    def delete(self, activity_id: str) -> None:
        """Deletes this app's metadata from an activity.

        Endpoint: ``DELETE /api/v1/activities/{activity_id}/app-metadata``

        Args:
            activity_id: The activity's ID.

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
        self._delete(activity_id)


class TraceAppMetadata(_RecordAppMetadata):
    """This app's metadata on traces. Requires an app token."""

    _collection = "traces"

    def set(self, trace_id: str, *, data: dict[str, Any]) -> None:
        """Replaces this app's metadata on a trace.

        Endpoint: ``PUT /api/v1/traces/{trace_id}/app-metadata``

        The whole dict is replaced; there is no merge. Each app sees only its own metadata,
        and it appears as ``app_metadata`` on the trace when read with an app token.

        Args:
            trace_id: The trace's ID.
            data: Any JSON-serialisable dict, at most 1 KB and 32 levels deep.

        Raises:
            SweatStackAuthError: If the client does not hold an app token (403). A personal
                token, from ``authenticate()`` or an API key, never qualifies.
            SweatStackBadRequestError: If ``data`` is too large (413) or too deep (422).
            SweatStackNotFoundError: If the trace does not exist.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client(api_key="app-user-token")  # e.g. user.client in FastAPI
            client.traces.app_metadata.set("trace_123", data={"reviewed": True})
            ```
        """
        self._put(trace_id, data)

    def delete(self, trace_id: str) -> None:
        """Deletes this app's metadata from a trace.

        Endpoint: ``DELETE /api/v1/traces/{trace_id}/app-metadata``

        Args:
            trace_id: The trace's ID.

        Raises:
            SweatStackAuthError: If the client does not hold an app token (403).
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client(api_key="app-user-token")
            client.traces.app_metadata.delete("trace_123")
            ```
        """
        self._delete(trace_id)


class TestAppMetadata(_RecordAppMetadata):
    """This app's metadata on tests. Requires an app token."""

    __test__ = False  # not a pytest test class

    _collection = "tests"

    def set(self, test_id: str, *, data: dict[str, Any]) -> None:
        """Replaces this app's metadata on a test.

        Endpoint: ``PUT /api/v1/tests/{test_id}/app-metadata``

        The whole dict is replaced; there is no merge. Each app sees only its own metadata,
        and it appears as ``app_metadata`` on the test when read with an app token.

        Args:
            test_id: The test's ID.
            data: Any JSON-serialisable dict, at most 1 KB and 32 levels deep.

        Raises:
            SweatStackAuthError: If the client does not hold an app token (403). A personal
                token, from ``authenticate()`` or an API key, never qualifies.
            SweatStackBadRequestError: If ``data`` is too large (413) or too deep (422).
            SweatStackNotFoundError: If the test does not exist.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client(api_key="app-user-token")  # e.g. user.client in FastAPI
            client.tests.app_metadata.set("test_123", data={"reviewed": True})
            ```
        """
        self._put(test_id, data)

    def delete(self, test_id: str) -> None:
        """Deletes this app's metadata from a test.

        Endpoint: ``DELETE /api/v1/tests/{test_id}/app-metadata``

        Args:
            test_id: The test's ID.

        Raises:
            SweatStackAuthError: If the client does not hold an app token (403).
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client(api_key="app-user-token")
            client.tests.app_metadata.delete("test_123")
            ```
        """
        self._delete(test_id)


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
