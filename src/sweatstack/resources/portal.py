"""``client.portal``: ``/api/v1/portal/...``."""

from __future__ import annotations

from functools import cached_property
from typing import Any

from ..schemas import PortalDestination, PortalSessionResponse
from ._base import Resource


class Portal(Resource):
    """The SweatStack Portal: hosted pages, in your app's branding, for users to fix their setup.

    **Beta**: the server documents the Portal as beta.
    """

    @cached_property
    def sessions(self) -> PortalSessions:
        """Portal links: ``sessions.create(destination)``."""
        return PortalSessions(self._client)


class PortalSessions(Resource):
    """Portal sessions: one-time links into the Portal."""

    def create(
        self,
        destination: PortalDestination | str,
        *,
        return_url: str | None = None,
    ) -> PortalSessionResponse:
        """Creates a Portal link for this app's users.

        Endpoint: ``POST /api/v1/portal/sessions``

        **Beta**: the server documents the Portal as beta.

        Most apps don't need this: ``issue.action_url`` from ``client.oauth.userinfo()`` or
        ``client.profile.status()`` is already such a link. Create one to choose the
        destination or the return link.

        This is a server-to-server call. It authenticates with the client's own app
        credentials (``client_id``, and ``client_secret`` if the app has one) in the request
        body, never with a user token; the user is identified when they open the link. A
        client on the default ``client_id`` creates a Portal branded as the SweatStack Python
        client. The URL is opaque: never build one by hand.

        Args:
            destination: ``"manage-integrations"`` or ``"manage-teams"``. A string the client
                does not know is sent as is, so a newer destination works before the SDK
                learns it.
            return_url: Where "Back to {app}" points; must be one of the app's registered
                redirect URIs. Omit it to have the Portal tell the user to close the page,
                which suits native apps.

        Returns:
            PortalSessionResponse: ``url``, to send the user to.

        Raises:
            SweatStackAuthError: If the app credentials are invalid (401).
            SweatStackBadRequestError: If ``return_url`` is not registered for the app, or
                ``client_id`` is not an application (400).
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            app = Client(client_id="YOUR_CLIENT_ID", client_secret="YOUR_CLIENT_SECRET")
            session = app.portal.sessions.create(
                "manage-integrations", return_url="https://example.com/app/"
            )
            print(session.url)
            ```
        """
        client = self._client
        body: dict[str, Any] = {
            "client_id": client.client_id,
            "destination": client._enums_to_strings([destination])[0],
        }
        if client.client_secret is not None:
            body["client_secret"] = client.client_secret.get_secret_value()
        if return_url is not None:
            body["return_url"] = return_url
        response = client._request("post", "/api/v1/portal/sessions", json=body, auth=False)
        return PortalSessionResponse.model_validate(response.json())
