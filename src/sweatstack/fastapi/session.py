"""Session encryption and cookie helpers."""

import json
import logging
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Response

from .config import get_config

SESSION_COOKIE_NAME = "sweatstack_session"
STATE_COOKIE_NAME = "sweatstack_oauth_state"


def _get_fernet_instances() -> list[Fernet]:
    """Get Fernet instances for encryption/decryption."""
    config = get_config()
    secrets = config.session_secret
    if not isinstance(secrets, list):
        secrets = [secrets]
    return [Fernet(secret.get_secret_value().encode()) for secret in secrets]


def encrypt_session(data: dict[str, Any]) -> str:
    """Encrypt session data.

    Uses the first configured key for encryption.
    """
    fernets = _get_fernet_instances()
    json_data = json.dumps(data)
    return fernets[0].encrypt(json_data.encode()).decode()


def decrypt_session(encrypted: str | None) -> dict[str, Any] | None:
    """Decrypt session data.

    Tries all configured keys for decryption (supports key rotation).
    Returns None if decryption fails or data is missing.
    """
    if not encrypted:
        return None

    fernets = _get_fernet_instances()

    for fernet in fernets:
        try:
            decrypted = fernet.decrypt(encrypted.encode())
            return json.loads(decrypted)
        except InvalidToken:
            continue
        except Exception as e:
            logging.warning(f"Session decryption error: {e}")
            return None

    # All keys failed
    return None


def set_session_cookie(response: Response, session_data: dict[str, Any]) -> None:
    """Set the encrypted session cookie on the response."""
    config = get_config()
    encrypted = encrypt_session(session_data)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=encrypted,
        httponly=True,
        secure=config.cookie_secure,
        samesite="lax",
        max_age=config.cookie_max_age,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Clear the session cookie."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
    )


def set_state_cookie(response: Response, state: str) -> None:
    """Set the OAuth state cookie (short-lived, 5 minutes)."""
    config = get_config()
    response.set_cookie(
        key=STATE_COOKIE_NAME,
        value=state,
        httponly=True,
        secure=config.cookie_secure,
        samesite="lax",
        max_age=300,  # 5 minutes
        path="/",
    )


def clear_state_cookie(response: Response) -> None:
    """Clear the OAuth state cookie."""
    response.delete_cookie(
        key=STATE_COOKIE_NAME,
        path="/",
    )
