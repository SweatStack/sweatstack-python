"""Webhook handling for the FastAPI plugin."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from .config import get_config


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class WebhookError(Exception):
    """Base class for webhook-related errors."""

    pass


class WebhookVerificationError(WebhookError):
    """Raised when webhook signature verification fails."""

    pass


class WebhookTokenStoreError(WebhookError):
    """Raised when TokenStore is required but not configured."""

    pass


class WebhookUserNotFoundError(WebhookError):
    """Raised when no stored tokens exist for the webhook's user_id."""

    pass


class WebhookTokenRefreshError(WebhookError):
    """Raised when token refresh fails in webhook context."""

    pass


# ---------------------------------------------------------------------------
# Webhook payload model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WebhookPayloadModel:
    """Verified webhook payload data.

    Attributes:
        user_id: The SweatStack user ID this webhook relates to.
        event_type: The type of event (e.g., "activity_created").
        resource_id: The ID of the affected resource.
        timestamp: When the event occurred.
    """

    user_id: str
    event_type: str
    resource_id: str
    timestamp: datetime


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

TIMESTAMP_TOLERANCE = 300  # 5 minutes


def verify_signature(
    payload: bytes,
    signature_header: str,
    secret: str,
) -> None:
    """Verify webhook signature.

    SweatStack uses HMAC-SHA256 signatures. The signature header format is:
    t={timestamp},v1={signature}

    The signed payload is: {timestamp}.{raw_json_body}

    Args:
        payload: The raw request body bytes.
        signature_header: The X-Sweatstack-Signature header value.
        secret: The webhook secret.

    Raises:
        WebhookVerificationError: If signature is invalid or timestamp too old.
    """
    try:
        parts = dict(p.split("=", 1) for p in signature_header.split(","))
        timestamp = int(parts["t"])
        signature = parts["v1"]
    except (KeyError, ValueError) as e:
        raise WebhookVerificationError("Invalid signature header format") from e

    # Check timestamp to prevent replay attacks
    if abs(time.time() - timestamp) > TIMESTAMP_TOLERANCE:
        raise WebhookVerificationError("Timestamp outside tolerance window")

    # Compute expected signature
    signed_payload = f"{timestamp}.".encode() + payload
    expected = hmac.new(
        secret.encode(),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(expected, signature):
        raise WebhookVerificationError("Invalid signature")


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


async def _detect_webhook_context(request: Request) -> WebhookPayloadModel | None:
    """Detect if this is a webhook request and return verified payload.

    This dependency is cached per-request by FastAPI. It's used by both
    WebhookPayload (which requires it) and AuthenticatedUser (which uses it
    to detect webhook context for token loading).

    Returns:
        WebhookPayloadModel if this is a verified webhook request, None otherwise.

    Raises:
        WebhookVerificationError: If signature header is present but invalid.
    """
    signature = request.headers.get("X-Sweatstack-Signature")
    if not signature:
        return None  # Not a webhook request - fast path

    config = get_config()

    if not config.webhook_secret:
        raise WebhookVerificationError(
            "Webhook received but webhook_secret not configured. "
            "Add webhook_secret to configure() to enable webhook handling."
        )

    body = await request.body()
    secret = (
        config.webhook_secret.get_secret_value()
        if hasattr(config.webhook_secret, "get_secret_value")
        else config.webhook_secret
    )
    verify_signature(body, signature, secret)

    try:
        data = json.loads(body)
        return WebhookPayloadModel(
            user_id=data["user_id"],
            event_type=data["event_type"],
            resource_id=data["resource_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        raise WebhookVerificationError(f"Invalid webhook payload: {e}") from e


async def _require_webhook_payload(
    webhook_context: Annotated[WebhookPayloadModel | None, Depends(_detect_webhook_context)],
) -> WebhookPayloadModel:
    """Dependency that requires a verified webhook payload.

    Raises:
        HTTPException: If request is not a valid webhook.
    """
    if webhook_context is None:
        raise HTTPException(status_code=400, detail="Missing or invalid webhook signature")
    return webhook_context


# Public type alias for use in endpoint signatures
WebhookPayload = Annotated[WebhookPayloadModel, Depends(_require_webhook_payload)]
"""Dependency that returns a verified webhook payload.

The signature is verified before your handler runs. If verification fails,
a 400 response is returned automatically.

Example:
    @app.post("/webhooks/sweatstack")
    def handle_webhook(payload: WebhookPayload):
        print(f"Event: {payload.event_type} for user {payload.user_id}")
        return {"status": "received"}
"""
