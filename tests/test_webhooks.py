"""Tests for webhook functionality."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
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
    verify_standard_signature,
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
        timestamp = datetime.now(UTC)
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
            expires_at=datetime.now(UTC),
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
            expires_at=datetime.now(UTC),
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
            expires_at=datetime.now(UTC),
        )
        tokens2 = StoredTokens(
            user_id="user_123",
            access_token="access_v2",
            refresh_token="refresh",
            expires_at=datetime.now(UTC),
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
            expires_at=datetime.now(UTC),
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
            expires_at=datetime.now(UTC),
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
            expires_at=datetime.now(UTC),
        )
        tokens2 = StoredTokens(
            user_id="user_123",
            access_token="access_v2",
            refresh_token="refresh",
            expires_at=datetime.now(UTC),
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


# ---------------------------------------------------------------------------
# Standard Webhooks
# ---------------------------------------------------------------------------

#: A secret shaped like the ones SweatStack makes: "whsec_" and 64 hex characters.
STANDARD_SECRET = "whsec_" + "ab" * 32


def standard_headers(
    payload: bytes, secret: str = STANDARD_SECRET, msg_id: str = "evt_123"
) -> dict[str, str]:
    """Headers signed by someone else's reading of the specification: the reference library."""
    import standardwebhooks

    now = datetime.now(UTC)
    return {
        "webhook-id": msg_id,
        "webhook-timestamp": str(int(now.timestamp())),
        "webhook-signature": standardwebhooks.Webhook(secret).sign(msg_id, now, payload.decode()),
    }


@pytest.fixture
def standard_app() -> FastAPI:
    configure(
        client_id="test_client_id",
        client_secret="test_client_secret",
        app_url="http://localhost:8000",
        session_secret="dGVzdC1vbmx5LWtleS1mb3ItdW5pdC10ZXN0cy0zMmI=",
        webhook_secret=STANDARD_SECRET,
    )
    app = FastAPI()
    instrument(app)

    @app.post("/webhooks/test")
    def webhook_handler(payload: WebhookPayload):
        return {"id": payload.id, "user_id": payload.user_id, "event_type": payload.event_type}

    return app


class TestVerifyStandardSignature:
    def test_a_reference_signature_verifies(self):
        payload = json.dumps({**create_webhook_payload(), "id": "evt_123"}).encode()

        verify_standard_signature(payload, standard_headers(payload), STANDARD_SECRET)

    def test_header_names_are_case_insensitive(self):
        payload = b"{}"
        headers = {name.title(): value for name, value in standard_headers(payload).items()}

        verify_standard_signature(payload, headers, STANDARD_SECRET)

    def test_one_of_several_signatures_is_enough(self):
        payload = b"{}"
        headers = standard_headers(payload)
        headers["webhook-signature"] = "v1,bm90IGl0 " + headers["webhook-signature"]

        verify_standard_signature(payload, headers, STANDARD_SECRET)

    @pytest.mark.parametrize("change", ["body", "id", "timestamp", "secret"])
    def test_a_change_fails(self, change: str):
        payload = b'{"resource_id":"activity_456"}'
        headers = standard_headers(payload)
        secret = STANDARD_SECRET
        if change == "body":
            payload = b'{"resource_id":"activity_457"}'
        elif change == "id":
            headers["webhook-id"] = "evt_124"
        elif change == "timestamp":
            headers["webhook-timestamp"] = str(int(headers["webhook-timestamp"]) + 1)
        else:
            secret = "whsec_" + "cd" * 32

        with pytest.raises(WebhookVerificationError):
            verify_standard_signature(payload, headers, secret)

    def test_an_old_timestamp_fails(self):
        import standardwebhooks

        payload = b"{}"
        then = datetime.fromtimestamp(time.time() - 600, tz=UTC)
        headers = {
            "webhook-id": "evt_123",
            "webhook-timestamp": str(int(then.timestamp())),
            "webhook-signature": standardwebhooks.Webhook(STANDARD_SECRET).sign(
                "evt_123", then, "{}"
            ),
        }

        with pytest.raises(WebhookVerificationError, match="tolerance"):
            verify_standard_signature(payload, headers, STANDARD_SECRET)

    @pytest.mark.parametrize("missing", ["webhook-id", "webhook-timestamp", "webhook-signature"])
    def test_a_missing_header_fails(self, missing: str):
        payload = b"{}"
        headers = standard_headers(payload)
        del headers[missing]

        with pytest.raises(WebhookVerificationError):
            verify_standard_signature(payload, headers, STANDARD_SECRET)

    def test_a_secret_that_is_not_a_standard_key_fails(self):
        with pytest.raises(WebhookVerificationError, match="secret"):
            verify_standard_signature(b"{}", standard_headers(b"{}"), "whsec_test_secret_key_12345")


class TestStandardWebhookRequests:
    def test_the_standard_headers_alone_are_a_webhook(self, standard_app: FastAPI):
        payload = json.dumps({**create_webhook_payload(), "id": "evt_123"}).encode()

        response = TestClient(standard_app).post(
            "/webhooks/test",
            content=payload,
            headers={**standard_headers(payload), "Content-Type": "application/json"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "id": "evt_123",
            "user_id": "user_123",
            "event_type": "activity_created",
        }

    def test_the_standard_headers_win_over_the_legacy_one(self, standard_app: FastAPI):
        """A wrong legacy signature next to valid standard ones is never read."""
        payload = json.dumps({**create_webhook_payload(), "id": "evt_123"}).encode()
        headers = {
            **standard_headers(payload),
            "X-Sweatstack-Signature": f"t={int(time.time())},v1=00",
        }

        assert (
            TestClient(standard_app)
            .post("/webhooks/test", content=payload, headers=headers)
            .status_code
            == 200
        )

    def test_a_bad_standard_signature_is_refused_even_with_a_good_legacy_one(
        self, standard_app: FastAPI
    ):
        payload = json.dumps({**create_webhook_payload(), "id": "evt_123"}).encode()
        headers = {
            **standard_headers(payload, msg_id="evt_999"),
            "webhook-id": "evt_123",
            "X-Sweatstack-Signature": create_signature(payload, STANDARD_SECRET),
        }

        with pytest.raises(WebhookVerificationError):
            TestClient(standard_app).post("/webhooks/test", content=payload, headers=headers)

    def test_a_legacy_only_delivery_still_verifies_and_has_no_id(
        self, configured_app: FastAPI, webhook_secret: str
    ):
        """Until the flag day, an app whose secret is not a standard key gets the legacy header only."""

        @configured_app.post("/webhooks/test")
        def webhook_handler(payload: WebhookPayload):
            return {"id": payload.id}

        payload = json.dumps(create_webhook_payload()).encode()
        response = TestClient(configured_app).post(
            "/webhooks/test",
            content=payload,
            headers={"X-Sweatstack-Signature": create_signature(payload, webhook_secret)},
        )

        assert response.status_code == 200
        assert response.json() == {"id": None}
