"""``client.oauth``: ``/oauth/authorize`` and ``/api/v1/oauth/...``."""

from __future__ import annotations

import base64
import hashlib
import secrets
import urllib.parse

from ..schemas import TokenResponse, UserInfoResponse
from ._base import Resource


class OAuth(Resource):
    """OAuth2 and OpenID Connect: build sign-in links, exchange codes, read the user's claims.

    Most apps use ``sweatstack.fastapi`` or ``sweatstack.streamlit``, which do this for you.
    """

    def generate_pkce_params(self) -> tuple[str, str]:
        """Generates a PKCE code verifier and its S256 code challenge.

        Returns:
            tuple[str, str]: ``(code_verifier, code_challenge)``. Send the challenge with
            :meth:`authorization_url`; keep the verifier for :meth:`exchange_code`.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            verifier, challenge = client.oauth.generate_pkce_params()
            ```
        """
        verifier = secrets.token_urlsafe(32)
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return verifier, challenge

    def authorization_url(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        code_challenge: str | None = None,
        scope: str = "data:read data:write profile",
        prompt: str | None = "none",
        state: str | None = None,
    ) -> str:
        """Builds the URL to send a user to for signing in with SweatStack.

        Endpoint: ``GET /oauth/authorize``

        Args:
            client_id: Your app's client ID.
            redirect_uri: Where SweatStack sends the user back to; must be registered.
            code_challenge: A PKCE challenge from :meth:`generate_pkce_params`.
            scope: Space-separated scopes.
            prompt: The OAuth ``prompt``; ``None`` to omit it.
            state: An opaque value to check on the way back, against CSRF.

        Returns:
            str: The authorization URL.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            verifier, challenge = client.oauth.generate_pkce_params()
            url = client.oauth.authorization_url(
                client_id="YOUR_CLIENT_ID",
                redirect_uri="http://localhost:8000/callback",
                code_challenge=challenge,
            )
            ```
        """
        params = {"client_id": client_id, "redirect_uri": redirect_uri, "scope": scope}
        if prompt is not None:
            params["prompt"] = prompt
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        if state:
            params["state"] = state
        return urllib.parse.urljoin(
            self._client.url, "/oauth/authorize?" + urllib.parse.urlencode(params)
        )

    def exchange_code(
        self,
        code: str,
        *,
        client_id: str,
        code_verifier: str | None = None,
        client_secret: str | None = None,
        persist: bool = True,
    ) -> TokenResponse:
        """Exchanges an authorization code for tokens, and signs this client in with them.

        Endpoint: ``POST /api/v1/oauth/token``

        Args:
            code: The ``code`` from the redirect back to your app.
            client_id: Your app's client ID.
            code_verifier: The PKCE verifier, if you sent a challenge.
            client_secret: Your app's secret, for confidential clients.
            persist: Also save the tokens to this machine's token storage.

        Returns:
            TokenResponse: ``access_token``, ``refresh_token`` and their metadata.

        Raises:
            SweatStackAuthError: If the code or credentials are rejected.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            tokens = client.oauth.exchange_code(
                "code-from-redirect", client_id="YOUR_CLIENT_ID", code_verifier="verifier"
            )
            ```
        """
        data = {"grant_type": "authorization_code", "client_id": client_id, "code": code}
        if code_verifier:
            data["code_verifier"] = code_verifier
        if client_secret:
            data["client_secret"] = client_secret
        response = self._client._request("post", "/api/v1/oauth/token", data=data, auth=False)
        tokens = TokenResponse.model_validate(response.json())
        self._client.api_key = tokens.access_token
        self._client.refresh_token = tokens.refresh_token
        if persist:
            self._client._save_tokens(tokens.access_token, tokens.refresh_token)
        return tokens

    def userinfo(self) -> UserInfoResponse:
        """Retrieves the OpenID Connect claims of the user, and why they may have no data.

        Endpoint: ``GET /api/v1/oauth/userinfo``

        Requires the ``profile`` scope. Besides ``sub``, ``name``, ``given_name``,
        ``family_name``, ``email`` and ``registered_at``, the response has ``issue`` (beta):
        ``None`` when there is nothing to say, otherwise the one thing to tell the user now.
        ``issue.action_url`` opens the Portal; it is ``None`` on delegated tokens and on
        ``syncing`` or ``unavailable`` issues, so show a button only when it is set. Without
        the ``profile`` scope, ``client.profile.status()`` gives the same ``issue``.

        Returns:
            UserInfoResponse: The claims and the optional ``issue``.

        Raises:
            SweatStackAuthError: If the token lacks the ``profile`` scope.
            SweatStackAPIError: If the API request fails for any other reason.

        Examples:
            ```python
            from sweatstack import Client

            client = Client()
            user = client.oauth.userinfo()
            if user.issue:
                print(user.issue.message)
            ```
        """
        response = self._client._request("get", "/api/v1/oauth/userinfo")
        return UserInfoResponse.model_validate(response.json())
