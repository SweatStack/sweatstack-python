"""Data models for FastAPI session management."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import SecretStr

from ..utils import decode_jwt_body


@dataclass(frozen=True, slots=True)
class TokenSet:
    """Immutable token pair with user ID.

    This represents either principal or delegated tokens stored in the session.
    The frozen=True ensures tokens can't be accidentally modified.
    """

    access_token: str
    refresh_token: str
    user_id: str

    def to_dict(self) -> dict[str, str]:
        """Serialize to dictionary for session storage."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "user_id": self.user_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TokenSet:
        """Deserialize from dictionary."""
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            user_id=data["user_id"],
        )


@dataclass(slots=True)
class SessionData:
    """Type-safe wrapper for session data.

    Handles both the new format (with principal/delegated) and legacy format
    (flat access_token/refresh_token/user_id) for backwards compatibility.
    """

    principal: TokenSet
    delegated: TokenSet | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for cookie storage."""
        data: dict[str, Any] = {"principal": self.principal.to_dict()}
        if self.delegated:
            data["delegated"] = self.delegated.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionData:
        """Deserialize from dictionary.

        Handles both new format and legacy format for backwards compatibility.
        """
        # New format: has "principal" key
        if "principal" in data:
            return cls(
                principal=TokenSet.from_dict(data["principal"]),
                delegated=TokenSet.from_dict(data["delegated"]) if data.get("delegated") else None,
            )

        # Legacy format: flat structure with access_token, refresh_token, user_id
        # Migrate to new format by treating as principal
        return cls(
            principal=TokenSet(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                user_id=data["user_id"],
            ),
            delegated=None,
        )


def extract_user_id(jwt_token: str | SecretStr) -> str:
    """Extract user ID ('sub' claim) from a JWT token.

    This does not validate the signature - the token was already validated
    by the API when it was issued.

    Args:
        jwt_token: The JWT access token (str or SecretStr).

    Returns:
        The user ID from the token's 'sub' claim.

    Raises:
        ValueError: If the token is malformed or missing the 'sub' claim.
    """
    try:
        token_str = jwt_token.get_secret_value() if isinstance(jwt_token, SecretStr) else jwt_token
        payload = decode_jwt_body(token_str)
        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("Token missing 'sub' claim")
        return user_id
    except (IndexError, KeyError) as e:
        raise ValueError(f"Malformed JWT token: {e}") from e


# ---------------------------------------------------------------------------
# Token storage for webhook support
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoredTokens:
    """Token data for persistent storage.

    Used by TokenStore implementations to persist tokens for webhook handling.
    The library does NOT encrypt tokens - see Security section in documentation.

    Attributes:
        user_id: The SweatStack user ID.
        access_token: The OAuth access token.
        refresh_token: The OAuth refresh token.
        expires_at: When the access token expires.
    """

    user_id: str
    access_token: str
    refresh_token: str
    expires_at: datetime

    def __repr__(self) -> str:
        """Hide sensitive data in logs."""
        return (
            f"StoredTokens(user_id={self.user_id!r}, "
            f"access_token='***', refresh_token='***', "
            f"expires_at={self.expires_at!r})"
        )


@runtime_checkable
class TokenStore(Protocol):
    """Protocol for persisting OAuth tokens.

    Implement this interface to enable AuthenticatedUser in webhook handlers.
    The library calls these methods automatically:
    - save(): After OAuth callback and token refresh
    - load(): When handling webhooks
    - delete(): On logout

    Thread Safety:
        All methods may be called concurrently. Your implementation must be thread-safe.

    Error Handling:
        - save(): Use upsert semantics (don't raise on duplicate user_id)
        - load(): Return None if user not found (don't raise)
        - delete(): Be idempotent (don't raise if user doesn't exist)
    """

    def save(self, tokens: StoredTokens) -> None:
        """Save or update tokens for a user."""
        ...

    def load(self, user_id: str) -> StoredTokens | None:
        """Load tokens for a user. Returns None if not found."""
        ...

    def delete(self, user_id: str) -> None:
        """Delete tokens for a user. Idempotent."""
        ...
