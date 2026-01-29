"""Module-level configuration for the FastAPI plugin."""

import logging
import os
from dataclasses import dataclass
from urllib.parse import quote

from cryptography.fernet import Fernet
from pydantic import SecretStr

logger = logging.getLogger(__name__)


def _validate_fernet_key(key: str) -> None:
    """Validate that a string is a valid Fernet key."""
    try:
        Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        raise ValueError(
            f"Invalid session_secret. Fernet keys must be 32 url-safe base64-encoded bytes. "
            f"Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )


@dataclass
class FastAPIConfig:
    """Internal configuration for the FastAPI plugin."""

    client_id: str
    client_secret: SecretStr
    app_url: str
    session_secret: SecretStr | list[SecretStr]
    scopes: list[str]
    cookie_secure: bool
    cookie_max_age: int
    auth_route_prefix: str
    redirect_unauthenticated: bool

    @property
    def redirect_uri(self) -> str:
        """Construct the OAuth redirect URI from app_url and auth_route_prefix."""
        return f"{self.app_url.rstrip('/')}{self.auth_route_prefix}/callback"


_config: FastAPIConfig | None = None


def _to_secret(value: str | SecretStr) -> SecretStr:
    """Convert a string to SecretStr if needed."""
    if isinstance(value, SecretStr):
        return value
    return SecretStr(value)


def configure(
    *,
    client_id: str | None = None,
    client_secret: str | SecretStr | None = None,
    app_url: str | None = None,
    session_secret: str | SecretStr | list[str | SecretStr] | None = None,
    scopes: list[str] | None = None,
    cookie_secure: bool | None = None,
    cookie_max_age: int = 86400,
    auth_route_prefix: str = "/auth/sweatstack",
    redirect_unauthenticated: bool = True,
) -> None:
    """Configure the FastAPI plugin.

    Args:
        client_id: OAuth client ID. Falls back to SWEATSTACK_CLIENT_ID env var.
        client_secret: OAuth client secret. Falls back to SWEATSTACK_CLIENT_SECRET env var.
        app_url: Base URL of the application (e.g., "http://localhost:8000").
            Falls back to APP_URL env var.
            The OAuth redirect URI is derived as: app_url + auth_route_prefix + "/callback"
        session_secret: Fernet key(s) for cookie encryption. Can be a single key
            or a list of keys for key rotation (first encrypts, all decrypt).
            Falls back to SWEATSTACK_SESSION_SECRET env var.
        scopes: OAuth scopes to request. Defaults to ["profile", "data:read"].
        cookie_secure: Whether to set the Secure flag on cookies. If not specified,
            auto-detected from app_url (True for https, False for http).
        cookie_max_age: Session cookie lifetime in seconds. Defaults to 86400 (24h).
        auth_route_prefix: URL prefix for auth routes. Defaults to "/auth/sweatstack".
        redirect_unauthenticated: If True, redirect unauthenticated requests to login
            with ?next= set to the current path. If False, return 401. Defaults to True.
    """
    global _config

    # Resolve from environment variables
    client_id = client_id or os.environ.get("SWEATSTACK_CLIENT_ID")
    client_secret = client_secret or os.environ.get("SWEATSTACK_CLIENT_SECRET")
    app_url = app_url or os.environ.get("APP_URL")
    session_secret = session_secret or os.environ.get("SWEATSTACK_SESSION_SECRET")

    # Validate required parameters
    if not client_id:
        raise ValueError("client_id is required (or set SWEATSTACK_CLIENT_ID)")
    if not client_secret:
        raise ValueError("client_secret is required (or set SWEATSTACK_CLIENT_SECRET)")
    if not app_url:
        raise ValueError("app_url is required (or set APP_URL)")
    if not session_secret:
        raise ValueError("session_secret is required (or set SWEATSTACK_SESSION_SECRET)")

    # Auto-detect cookie_secure from app_url scheme
    if cookie_secure is None:
        cookie_secure = app_url.startswith("https://")
        if not cookie_secure and "localhost" not in app_url and "127.0.0.1" not in app_url:
            logger.warning(
                "Using HTTP with non-localhost URL (%s) - cookies will not be secure",
                app_url,
            )

    # Validate and convert session secret(s)
    secret_list = [session_secret] if isinstance(session_secret, (str, SecretStr)) else session_secret
    for secret in secret_list:
        secret_value = secret.get_secret_value() if isinstance(secret, SecretStr) else secret
        _validate_fernet_key(secret_value)

    # Convert to SecretStr
    client_secret_obj = _to_secret(client_secret)
    if isinstance(session_secret, (str, SecretStr)):
        session_secret_obj: SecretStr | list[SecretStr] = _to_secret(session_secret)
    else:
        session_secret_obj = [_to_secret(s) for s in session_secret]

    if scopes is None:
        scopes = ["profile", "data:read"]

    # Normalize prefix (strip trailing slash)
    auth_route_prefix = auth_route_prefix.rstrip("/")

    _config = FastAPIConfig(
        client_id=client_id,
        client_secret=client_secret_obj,
        app_url=app_url,
        session_secret=session_secret_obj,
        scopes=scopes,
        cookie_secure=cookie_secure,
        cookie_max_age=cookie_max_age,
        auth_route_prefix=auth_route_prefix,
        redirect_unauthenticated=redirect_unauthenticated,
    )


def get_config() -> FastAPIConfig:
    """Get the current configuration.

    Raises:
        RuntimeError: If configure() has not been called.
    """
    if _config is None:
        raise RuntimeError(
            "configure() must be called before instrument()"
        )
    return _config


class _Urls:
    """URL helpers for the FastAPI plugin.

    Provides methods to generate URLs for authentication and user selection routes.
    These URLs can be used in templates or redirects.

    Example:
        from sweatstack.fastapi import urls

        # In a template:
        <a href="{{ urls.login() }}">Login</a>
        <form method="post" action="{{ urls.select_user(athlete.id) }}">
            <button>View as {{ athlete.name }}</button>
        </form>
    """

    def login(self, next: str | None = None) -> str:
        """Get the login URL.

        Args:
            next: Optional path to redirect to after login.
        """
        base = f"{get_config().auth_route_prefix}/login"
        if next:
            return f"{base}?next={quote(next)}"
        return base

    def logout(self) -> str:
        """Get the logout URL."""
        return f"{get_config().auth_route_prefix}/logout"

    def select_user(self, user_id: str, next: str | None = None) -> str:
        """Get the URL to switch to viewing as another user.

        Args:
            user_id: The ID of the user to view as.
            next: Optional path to redirect to after switching.

        Example:
            <form method="post" action="{{ urls.select_user(athlete.id) }}">
                <button>View as {{ athlete.name }}</button>
            </form>
        """
        base = f"{get_config().auth_route_prefix}/select-user/{user_id}"
        if next:
            return f"{base}?next={quote(next)}"
        return base

    def select_self(self, next: str | None = None) -> str:
        """Get the URL to switch back to viewing as yourself.

        Args:
            next: Optional path to redirect to after switching.

        Example:
            <form method="post" action="{{ urls.select_self() }}">
                <button>Back to my view</button>
            </form>
        """
        base = f"{get_config().auth_route_prefix}/select-self"
        if next:
            return f"{base}?next={quote(next)}"
        return base


urls = _Urls()
