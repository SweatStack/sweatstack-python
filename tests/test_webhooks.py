"""Tests for webhook functionality."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sweatstack.fastapi import (
    StoredTokens,
    TokenStore,
    WebhookPayload,
    WebhookVerificationError,
    configure,
    instrument,
    verify_signature,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_config():
    """Reset global config before each test."""
    import sweatstack.fastapi.config as config_module

    config_module._config = None
    yield
    config_module._config = None


@pytest.fixture
def webhook_secret() -> str:
    return "whsec_test_secret_key_12345"


@pytest.fixture
def configured_app(webhook_secret: str) -> FastAPI:
    """Create a configured FastAPI app with webhook support."""
    configure(
        client_id="test_client_id",
        client_secret="test_client_secret",
        app_url="http://localhost:8000",
        session_secret="dGVzdC1vbmx5LWtleS1mb3ItdW5pdC10ZXN0cy0zMmI=",
        webhook_secret=webhook_secret,
    )
    app = FastAPI()
    instrument(app)
    return app


def create_signature(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    """Create a valid webhook signature."""
    if timestamp is None:
        timestamp = int(time.time())

    signed_payload = f"{timestamp}.".encode() + payload
    signature = hmac.new(
        secret.encode(),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    return f"t={timestamp},v1={signature}"


def create_webhook_payload(
    user_id: str = "user_123",
    event_type: str = "activity_created",
    resource_id: str = "activity_456",
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    """Create a webhook payload dict."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    return {
        "user_id": user_id,
        "event_type": event_type,
        "resource_id": resource_id,
        "timestamp": timestamp.isoformat(),
    }


# ---------------------------------------------------------------------------
# Signature verification tests
# ---------------------------------------------------------------------------


class TestVerifySignature:
    def test_valid_signature(self, webhook_secret: str):
        """Test that a valid signature passes verification."""
        payload = b'{"user_id": "123"}'
        signature = create_signature(payload, webhook_secret)

        # Should not raise
        verify_signature(payload, signature, webhook_secret)

    def test_invalid_signature(self, webhook_secret: str):
        """Test that an invalid signature raises WebhookVerificationError."""
        payload = b'{"user_id": "123"}'
        signature = create_signature(payload, "wrong_secret")

        with pytest.raises(WebhookVerificationError, match="Invalid signature"):
            verify_signature(payload, signature, webhook_secret)

    def test_malformed_signature_header(self, webhook_secret: str):
        """Test that a malformed signature header raises WebhookVerificationError."""
        payload = b'{"user_id": "123"}'

        with pytest.raises(WebhookVerificationError, match="Invalid signature header format"):
            verify_signature(payload, "invalid_format", webhook_secret)

    def test_missing_timestamp(self, webhook_secret: str):
        """Test that missing timestamp raises WebhookVerificationError."""
        payload = b'{"user_id": "123"}'

        with pytest.raises(WebhookVerificationError, match="Invalid signature header format"):
            verify_signature(payload, "v1=abc123", webhook_secret)

    def test_expired_timestamp(self, webhook_secret: str):
        """Test that an expired timestamp raises WebhookVerificationError."""
        payload = b'{"user_id": "123"}'
        old_timestamp = int(time.time()) - 400  # 6+ minutes ago
        signature = create_signature(payload, webhook_secret, old_timestamp)

        with pytest.raises(WebhookVerificationError, match="Timestamp outside tolerance"):
            verify_signature(payload, signature, webhook_secret)

    def test_future_timestamp_within_tolerance(self, webhook_secret: str):
        """Test that a future timestamp within tolerance passes."""
        payload = b'{"user_id": "123"}'
        future_timestamp = int(time.time()) + 60  # 1 minute in future
        signature = create_signature(payload, webhook_secret, future_timestamp)

        # Should not raise
        verify_signature(payload, signature, webhook_secret)

    def test_tampered_payload(self, webhook_secret: str):
        """Test that a tampered payload fails verification."""
        original_payload = b'{"user_id": "123"}'
        tampered_payload = b'{"user_id": "456"}'
        signature = create_signature(original_payload, webhook_secret)

        with pytest.raises(WebhookVerificationError, match="Invalid signature"):
            verify_signature(tampered_payload, signature, webhook_secret)


# ---------------------------------------------------------------------------
# WebhookPayload dependency tests
# ---------------------------------------------------------------------------


class TestWebhookPayloadDependency:
    def test_valid_webhook_request(self, configured_app: FastAPI, webhook_secret: str):
        """Test that a valid webhook request returns parsed payload."""

        @configured_app.post("/webhooks/test")
        def webhook_handler(payload: WebhookPayload):
            return {
                "user_id": payload.user_id,
                "event_type": payload.event_type,
                "resource_id": payload.resource_id,
            }

        client = TestClient(configured_app)
        payload_data = create_webhook_payload()
        payload_bytes = json.dumps(payload_data).encode()
        signature = create_signature(payload_bytes, webhook_secret)

        response = client.post(
            "/webhooks/test",
            content=payload_bytes,
            headers={
                "X-Sweatstack-Signature": signature,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "user_123"
        assert data["event_type"] == "activity_created"
        assert data["resource_id"] == "activity_456"

    def test_missing_signature_header(self, configured_app: FastAPI):
        """Test that missing signature header returns 400."""

        @configured_app.post("/webhooks/test")
        def webhook_handler(payload: WebhookPayload):
            return {"status": "ok"}

        client = TestClient(configured_app)
        payload_data = create_webhook_payload()

        response = client.post(
            "/webhooks/test",
            json=payload_data,
        )

        assert response.status_code == 400
        assert "signature" in response.json()["detail"].lower()

    def test_invalid_signature(self, configured_app: FastAPI):
        """Test that invalid signature raises WebhookVerificationError."""

        @configured_app.post("/webhooks/test")
        def webhook_handler(payload: WebhookPayload):
            return {"status": "ok"}

        client = TestClient(configured_app, raise_server_exceptions=False)
        payload_data = create_webhook_payload()
        payload_bytes = json.dumps(payload_data).encode()
        signature = create_signature(payload_bytes, "wrong_secret")

        response = client.post(
            "/webhooks/test",
            content=payload_bytes,
            headers={
                "X-Sweatstack-Signature": signature,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 500  # WebhookVerificationError not caught

    def test_invalid_json_payload(self, configured_app: FastAPI, webhook_secret: str):
        """Test that invalid JSON raises WebhookVerificationError."""

        @configured_app.post("/webhooks/test")
        def webhook_handler(payload: WebhookPayload):
            return {"status": "ok"}

        client = TestClient(configured_app, raise_server_exceptions=False)
        payload_bytes = b"not valid json"
        signature = create_signature(payload_bytes, webhook_secret)

        response = client.post(
            "/webhooks/test",
            content=payload_bytes,
            headers={
                "X-Sweatstack-Signature": signature,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 500  # WebhookVerificationError

    def test_missing_required_fields(self, configured_app: FastAPI, webhook_secret: str):
        """Test that missing required fields raises WebhookVerificationError."""

        @configured_app.post("/webhooks/test")
        def webhook_handler(payload: WebhookPayload):
            return {"status": "ok"}

        client = TestClient(configured_app, raise_server_exceptions=False)
        payload_bytes = json.dumps({"user_id": "123"}).encode()  # Missing fields
        signature = create_signature(payload_bytes, webhook_secret)

        response = client.post(
            "/webhooks/test",
            content=payload_bytes,
            headers={
                "X-Sweatstack-Signature": signature,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 500  # WebhookVerificationError


# ---------------------------------------------------------------------------
# TokenStore tests
# ---------------------------------------------------------------------------


class InMemoryTokenStore(TokenStore):
    """Simple in-memory token store for testing."""

    def __init__(self):
        self.tokens: dict[str, StoredTokens] = {}

    def save(self, tokens: StoredTokens) -> None:
        self.tokens[tokens.user_id] = tokens

    def load(self, user_id: str) -> StoredTokens | None:
        return self.tokens.get(user_id)

    def delete(self, user_id: str) -> None:
        self.tokens.pop(user_id, None)


class TestTokenStore:
    def test_save_and_load(self):
        """Test saving and loading tokens."""
        store = InMemoryTokenStore()
        tokens = StoredTokens(
            user_id="user_123",
            access_token="access_token_value",
            refresh_token="refresh_token_value",
            expires_at=datetime.now(timezone.utc),
        )

        store.save(tokens)
        loaded = store.load("user_123")

        assert loaded is not None
        assert loaded.user_id == "user_123"
        assert loaded.access_token == "access_token_value"
        assert loaded.refresh_token == "refresh_token_value"

    def test_load_nonexistent(self):
        """Test loading nonexistent user returns None."""
        store = InMemoryTokenStore()
        assert store.load("nonexistent") is None

    def test_delete(self):
        """Test deleting tokens."""
        store = InMemoryTokenStore()
        tokens = StoredTokens(
            user_id="user_123",
            access_token="access",
            refresh_token="refresh",
            expires_at=datetime.now(timezone.utc),
        )

        store.save(tokens)
        assert store.load("user_123") is not None

        store.delete("user_123")
        assert store.load("user_123") is None

    def test_delete_nonexistent_is_idempotent(self):
        """Test deleting nonexistent user doesn't raise."""
        store = InMemoryTokenStore()
        # Should not raise
        store.delete("nonexistent")

    def test_upsert_semantics(self):
        """Test that save updates existing tokens."""
        store = InMemoryTokenStore()
        tokens1 = StoredTokens(
            user_id="user_123",
            access_token="access_v1",
            refresh_token="refresh",
            expires_at=datetime.now(timezone.utc),
        )
        tokens2 = StoredTokens(
            user_id="user_123",
            access_token="access_v2",
            refresh_token="refresh",
            expires_at=datetime.now(timezone.utc),
        )

        store.save(tokens1)
        store.save(tokens2)

        loaded = store.load("user_123")
        assert loaded is not None
        assert loaded.access_token == "access_v2"


class TestStoredTokensRepr:
    def test_repr_hides_sensitive_data(self):
        """Test that repr doesn't expose tokens."""
        tokens = StoredTokens(
            user_id="user_123",
            access_token="super_secret_access_token",
            refresh_token="super_secret_refresh_token",
            expires_at=datetime.now(timezone.utc),
        )

        repr_str = repr(tokens)

        assert "user_123" in repr_str
        assert "super_secret_access_token" not in repr_str
        assert "super_secret_refresh_token" not in repr_str
        assert "***" in repr_str


# ---------------------------------------------------------------------------
# SQLiteTokenStore tests
# ---------------------------------------------------------------------------


class TestSQLiteTokenStore:
    def test_save_load_delete(self, tmp_path):
        """Test SQLite token store basic operations."""
        from sweatstack.fastapi import SQLiteTokenStore

        db_path = tmp_path / "test_tokens.db"
        store = SQLiteTokenStore(db_path)

        tokens = StoredTokens(
            user_id="user_123",
            access_token="access",
            refresh_token="refresh",
            expires_at=datetime.now(timezone.utc),
        )

        # Save
        store.save(tokens)

        # Load
        loaded = store.load("user_123")
        assert loaded is not None
        assert loaded.user_id == "user_123"
        assert loaded.access_token == "access"

        # Delete
        store.delete("user_123")
        assert store.load("user_123") is None

    def test_upsert(self, tmp_path):
        """Test that save updates existing tokens."""
        from sweatstack.fastapi import SQLiteTokenStore

        db_path = tmp_path / "test_tokens.db"
        store = SQLiteTokenStore(db_path)

        tokens1 = StoredTokens(
            user_id="user_123",
            access_token="access_v1",
            refresh_token="refresh",
            expires_at=datetime.now(timezone.utc),
        )
        tokens2 = StoredTokens(
            user_id="user_123",
            access_token="access_v2",
            refresh_token="refresh",
            expires_at=datetime.now(timezone.utc),
        )

        store.save(tokens1)
        store.save(tokens2)

        loaded = store.load("user_123")
        assert loaded is not None
        assert loaded.access_token == "access_v2"


# ---------------------------------------------------------------------------
# Configuration validation tests
# ---------------------------------------------------------------------------


class TestWebhookConfiguration:
    def test_webhook_secret_from_env(self, monkeypatch):
        """Test that webhook_secret can be read from environment."""
        monkeypatch.setenv("SWEATSTACK_CLIENT_ID", "test_id")
        monkeypatch.setenv("SWEATSTACK_CLIENT_SECRET", "test_secret")
        monkeypatch.setenv("APP_URL", "http://localhost:8000")
        monkeypatch.setenv(
            "SWEATSTACK_SESSION_SECRET", "dGVzdC1vbmx5LWtleS1mb3ItdW5pdC10ZXN0cy0zMmI="
        )
        monkeypatch.setenv("SWEATSTACK_WEBHOOK_SECRET", "whsec_from_env")

        configure()

        from sweatstack.fastapi.config import get_config

        config = get_config()
        assert config.webhook_secret is not None
        assert config.webhook_secret.get_secret_value() == "whsec_from_env"

    def test_token_store_configuration(self):
        """Test that token_store can be configured."""
        store = InMemoryTokenStore()

        configure(
            client_id="test_id",
            client_secret="test_secret",
            app_url="http://localhost:8000",
            session_secret="dGVzdC1vbmx5LWtleS1mb3ItdW5pdC10ZXN0cy0zMmI=",
            token_store=store,
        )

        from sweatstack.fastapi.config import get_config

        config = get_config()
        assert config.token_store is store
