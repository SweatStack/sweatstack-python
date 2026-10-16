"""``client.oauth``: ``/oauth/authorize`` and ``/api/v1/oauth/...``."""

from __future__ import annotations

import base64
import hashlib
import secrets
import urllib.parse

from ..constants import DEFAULT_SCOPE
from ..schemas import TokenResponse, UserInfoResponse
from ._base import Resource


def build_authorization_url(
    base_url: str,
    *,
    client_id: str,
    redirect_uri: str,
    scope: str,
    code_challenge: str | None = None,
    prompt: str | None = None,
    state: str | None = None,
    nonce: str | None = None,
    integration: str | None = None,
    email_auth_mode: str | None = None,
) -> str:
    """The one place an ``/oauth/authorize`` URL is built: :meth:`OAuth.authorization_url`, the
    FastAPI plugin and the Streamlit helper all call it. A parameter that is ``None`` or empty is left out."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256" if code_challenge else None,
        "prompt": prompt,
        "state": state,
        "nonce": nonce,
        "integration": integration,
        "email_auth_mode": email_auth_mode,
    }
    query = urllib.parse.urlencode({key: value for key, value in params.items() if value})
    return urllib.parse.urljoin(base_url, "/oauth/authorize?" + query)


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
        scope: str = DEFAULT_SCOPE,
        prompt: str | None = None,
        state: str | None = None,
        nonce: str | None = None,
        integration: str | None = None,
        email_auth_mode: str | None = None,
    ) -> str:
        """Builds the URL to send a user to for signing in with SweatStack.

        Endpoint: ``GET /oauth/authorize``

        Args:
            client_id: Your app's client ID.
            redirect_uri: Where SweatStack sends the user back to; must be registered.
            code_challenge: A PKCE challenge from :meth:`generate_pkce_params`.
            scope: Space-separated scopes.
            prompt: The OpenID Connect ``prompt``. Leave it out and SweatStack skips the consent
                screen when the user's grant already covers the request; ``"consent"`` always
                shows it.
            state: An opaque value to check on the way back, against CSRF.
            nonce: Echoed in the ``id_token`` that comes with the code exchange.
            integration: One provider (``"garmin_connect"``, ``"intervals_icu"``, ``"wahoo"``):
                the user skips the sign-in chooser and goes straight to it.
            email_auth_mode: ``"existing_only"`` presents email sign-in as for existing
                accounts, so a new user picks a wearable sign-in instead.

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
        return build_authorization_url(
            self._client.url,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            scope=scope,
            prompt=prompt,
            state=state,
            nonce=nonce,
            integration=integration,
            email_auth_mode=email_auth_mode,
        )

    def exchange_code(
        self,
        code: str,
        *,
        client_id: str,
        code_verifier: str | None = None,
        client_secret: str | None = None,
        persist: bool = False,
    ) -> TokenResponse:
        """Exchanges an authorization code for tokens, and signs this client in with them.

        Endpoint: ``POST /api/v1/oauth/token``

        The tokens stay in this client. In a server, keep them with the user's session; they
        are that user's credentials, not the machine's.

        Args:
            code: The ``code`` from the redirect back to your app.
            client_id: Your app's client ID.
            code_verifier: The PKCE verifier, if you sent a challenge.
            client_secret: Your app's secret, for confidential clients.
            persist: Also save the tokens on this machine for later sessions, as
                ``authenticate()`` does. Never in a server.

        Returns:
            TokenResponse: ``access_token``, ``refresh_token`` and their metadata.

        Raises:
            SweatStackAuthError: If the code or credentials are rejected.
            SweatStackAPIError: If the API request fails for any other reason.
            ValueError: If ``persist`` is set on a client built with ``ambient_credentials=False``.

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

        Requires the ``openid`` scope. ``sub`` and ``registered_at`` always come; the name claims
        (``name``, ``given_name``, ``family_name``) need ``profile`` and ``email`` needs the
        ``email`` scope, otherwise they are ``None``. The response also has ``issue`` (beta):
        ``None`` when there is nothing to say, otherwise the one thing to tell the user now.
        ``issue.destination`` says the user can fix it in the Portal: pass it to
        ``client.portal.sessions.create()`` when they click. It is ``None`` on delegated tokens
        and on ``syncing`` issues, so show a button only when it is set. Issues are reported only
        for the capabilities your app's scopes reach.
        Without the ``openid`` scope, ``client.profile.status()`` gives the same ``issue``.

        Returns:
            UserInfoResponse: The claims and the optional ``issue``.

        Raises:
            SweatStackAuthError: If the token lacks the ``openid`` scope.
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
