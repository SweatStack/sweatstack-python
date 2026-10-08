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
        """Creates a Portal link for the user this client acts for.

        Endpoint: ``POST /api/v1/portal/sessions``

        **Beta**: the server documents the Portal as beta.

        The only way to get a Portal URL. Call it when the user acts, typically with
        ``issue.destination`` from ``client.oauth.userinfo()`` or ``client.profile.status()``,
        and send the user straight there: don't store or reuse the URL.

        Needs a client holding the user's own access token (the one from your OAuth flow).
        The Portal is branded for the app that token was issued to. The URL is opaque: never
        build one by hand.

        Args:
            destination: ``"manage-integrations"`` or ``"manage-teams"``. A string the client
                does not know is sent as is, so a newer destination works before the SDK
                learns it.
            return_url: Where "Back to {app}" points. It follows the same rule as an OAuth
                redirect URI: it must equal or sit under one of the app's registered redirect
                URIs. Omit it to have the Portal tell the user to close the page, which suits
                native apps and installed PWAs.

        Returns:
            PortalSessionResponse: ``url``, to send the user to.

        Raises:
            SweatStackAuthError: If the client has no access token (401), or the token is
                delegated (403): a link minted for a coach would open the coach's own account.
            SweatStackBadRequestError: If ``return_url`` does not belong to the app, or the
                token was not issued to an app (400).
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()  # holds the user's access token
            user = client.oauth.userinfo()
            if user.issue and user.issue.destination:
                session = client.portal.sessions.create(
                    user.issue.destination, return_url="https://example.com/app/settings"
                )
                print(session.url)
            ```
        """
        client = self._client
        body: dict[str, Any] = {"destination": client._enums_to_strings([destination])[0]}
        if return_url is not None:
            body["return_url"] = return_url
        response = client._request("post", "/api/v1/portal/sessions", json=body)
        return PortalSessionResponse.model_validate(response.json())
