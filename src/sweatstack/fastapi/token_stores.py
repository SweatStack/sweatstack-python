"""Token store implementations for development use.

WARNING: These implementations are for LOCAL DEVELOPMENT ONLY.
Do not use in production. Implement your own TokenStore with proper
database infrastructure, encryption, and monitoring.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .models import StoredTokens, TokenStore

logger = logging.getLogger(__name__)


class SQLiteTokenStore(TokenStore):
    """SQLite-based TokenStore for local development.

    WARNING: This implementation is for LOCAL DEVELOPMENT ONLY.
    Do not use in production. For production, implement your own
    TokenStore with proper database infrastructure, encryption,
    and monitoring.

    Features:
        - File-based storage (no external database required)
        - Thread-safe with connection-per-thread pattern
        - Auto-creates table on first use

    Args:
        db_path: Path to SQLite database file. Defaults to "sweatstack_tokens.db"
            in current directory.
    """

    def __init__(self, db_path: str | Path = "sweatstack_tokens.db"):
        self.db_path = str(db_path)
        self._local = threading.local()

        logger.warning(
            "SQLiteTokenStore is for LOCAL DEVELOPMENT ONLY. "
            "Do not use in production. Implement a proper TokenStore "
            "with your production database."
        )

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, "connection"):
            self._local.connection = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
            )
            self._local.connection.row_factory = sqlite3.Row
        return self._local.connection

    def _init_db(self) -> None:
        """Create tokens table if it doesn't exist."""
        conn = self._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sweatstack_tokens (
                user_id TEXT PRIMARY KEY,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
        """)
        conn.commit()

    def save(self, tokens: StoredTokens) -> None:
        """Save or update tokens for a user."""
        conn = self._get_connection()
        conn.execute(
            """
            INSERT INTO sweatstack_tokens (user_id, access_token, refresh_token, expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                expires_at = excluded.expires_at
            """,
            (
                tokens.user_id,
                tokens.access_token,
                tokens.refresh_token,
                tokens.expires_at.isoformat(),
            ),
        )
        conn.commit()

    def load(self, user_id: str) -> StoredTokens | None:
        """Load tokens for a user. Returns None if not found."""
        conn = self._get_connection()
        row = conn.execute(
            "SELECT * FROM sweatstack_tokens WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        if row:
            return StoredTokens(
                user_id=row["user_id"],
                access_token=row["access_token"],
                refresh_token=row["refresh_token"],
                expires_at=datetime.fromisoformat(row["expires_at"]),
            )
        return None

    def delete(self, user_id: str) -> None:
        """Delete tokens for a user. Idempotent."""
        conn = self._get_connection()
        conn.execute(
            "DELETE FROM sweatstack_tokens WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()


class EncryptedSQLiteTokenStore(TokenStore):
    """Encrypted SQLite TokenStore for local development.

    WARNING: This implementation is for LOCAL DEVELOPMENT ONLY.
    Do not use in production. This demonstrates the encryption pattern -
    adapt it for your production database.

    Encrypts access_token and refresh_token using Fernet (AES-128-CBC + HMAC).
    user_id and expires_at are stored unencrypted for queries.

    Args:
        encryption_key: Fernet key for encryption. Generate with:
            python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
        db_path: Path to SQLite database file.
    """

    def __init__(
        self,
        encryption_key: str | bytes,
        db_path: str | Path = "sweatstack_tokens_encrypted.db",
    ):
        # Import here so cryptography is optional for basic usage
        from cryptography.fernet import Fernet

        self.db_path = str(db_path)
        self._local = threading.local()

        if isinstance(encryption_key, str):
            encryption_key = encryption_key.encode()
        self._fernet = Fernet(encryption_key)

        logger.warning(
            "EncryptedSQLiteTokenStore is for LOCAL DEVELOPMENT ONLY. "
            "Do not use in production. This demonstrates the encryption "
            "pattern - implement with your production database."
        )

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, "connection"):
            self._local.connection = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
            )
            self._local.connection.row_factory = sqlite3.Row
        return self._local.connection

    def _init_db(self) -> None:
        """Create tokens table if it doesn't exist."""
        conn = self._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sweatstack_tokens (
                user_id TEXT PRIMARY KEY,
                access_token_encrypted TEXT NOT NULL,
                refresh_token_encrypted TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
        """)
        conn.commit()

    def _encrypt(self, value: str) -> str:
        """Encrypt a string value."""
        return self._fernet.encrypt(value.encode()).decode()

    def _decrypt(self, value: str) -> str:
        """Decrypt a string value."""
        return self._fernet.decrypt(value.encode()).decode()

    def save(self, tokens: StoredTokens) -> None:
        """Save or update tokens for a user."""
        conn = self._get_connection()
        conn.execute(
            """
            INSERT INTO sweatstack_tokens
                (user_id, access_token_encrypted, refresh_token_encrypted, expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                access_token_encrypted = excluded.access_token_encrypted,
                refresh_token_encrypted = excluded.refresh_token_encrypted,
                expires_at = excluded.expires_at
            """,
            (
                tokens.user_id,
                self._encrypt(tokens.access_token),
                self._encrypt(tokens.refresh_token),
                tokens.expires_at.isoformat(),
            ),
        )
        conn.commit()

    def load(self, user_id: str) -> StoredTokens | None:
        """Load tokens for a user. Returns None if not found."""
        conn = self._get_connection()
        row = conn.execute(
            "SELECT * FROM sweatstack_tokens WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        if row:
            return StoredTokens(
                user_id=row["user_id"],
                access_token=self._decrypt(row["access_token_encrypted"]),
                refresh_token=self._decrypt(row["refresh_token_encrypted"]),
                expires_at=datetime.fromisoformat(row["expires_at"]),
            )
        return None

    def delete(self, user_id: str) -> None:
        """Delete tokens for a user. Idempotent."""
        conn = self._get_connection()
        conn.execute(
            "DELETE FROM sweatstack_tokens WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()
