#!/usr/bin/env python3
# /// script
# dependencies = [
#   "httpx2",
# ]
# ///
"""
Webhook simulator for testing SweatStack webhook endpoints.

This script simulates webhook events from SweatStack by:
1. Creating a properly formatted webhook payload, with an event id
2. Signing it with the webhook secret, as Standard Webhooks
   (https://www.standardwebhooks.com/) specifies
3. Sending it to your local webhook endpoint

Usage:
    # Send an activity_created event for a specific user
    uv run send_webhook.py --user-id user_123 --event activity_created

    # Send with custom resource ID
    uv run send_webhook.py --user-id user_123 --event activity_created --resource-id act_789

    # Send to a different endpoint
    uv run send_webhook.py --url http://localhost:8001/webhooks/sweatstack/with-data

    # Use a different webhook secret (a "whsec_" secret, as SweatStack shows it)
    uv run send_webhook.py --secret "whsec_..."
"""

import argparse
import base64
import hashlib
import hmac
import json
import sys
import time
import uuid
from datetime import UTC, datetime

import httpx2


def create_signature(payload: bytes, secret: str, event_id: str, timestamp: int) -> str:
    """Create a `webhook-signature` header value, as SweatStack signs a delivery."""
    key = base64.b64decode(secret.removeprefix("whsec_"))
    signed_payload = f"{event_id}.{timestamp}.".encode() + payload
    signature = hmac.new(key, signed_payload, hashlib.sha256).digest()
    return f"v1,{base64.b64encode(signature).decode()}"


def send_webhook(
    url: str,
    user_id: str,
    event_type: str,
    resource_id: str,
    secret: str,
    verbose: bool = False,
) -> httpx2.Response:
    """Send a webhook to the specified URL."""
    # Create payload
    event_id = uuid.uuid4().hex
    payload = {
        "id": event_id,
        "user_id": user_id,
        "event_type": event_type,
        "resource_id": resource_id,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    payload_bytes = json.dumps(payload).encode()
    timestamp = int(time.time())
    signature = create_signature(payload_bytes, secret, event_id, timestamp)

    if verbose:
        print(f"\n{'=' * 60}")
        print("Webhook Request")
        print(f"{'=' * 60}")
        print(f"URL: {url}")
        print(f"Signature: {signature}")
        print(f"Payload: {json.dumps(payload, indent=2)}")
        print(f"{'=' * 60}\n")

    # Send request
    response = httpx2.post(
        url,
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Sweatstack-Event": event_type,
            "webhook-id": event_id,
            "webhook-timestamp": str(timestamp),
            "webhook-signature": signature,
        },
        timeout=10.0,
    )

    return response


def main():
    parser = argparse.ArgumentParser(
        description="Send simulated SweatStack webhooks for testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --user-id user_123 --event activity_created
  %(prog)s --user-id user_123 --event activity_updated --resource-id act_456
  %(prog)s --url http://localhost:8001/webhooks/sweatstack/with-data
        """,
    )

    parser.add_argument(
        "--url",
        default="http://localhost:8001/webhooks/sweatstack",
        help="Webhook endpoint URL (default: http://localhost:8001/webhooks/sweatstack)",
    )
    parser.add_argument(
        "--user-id",
        default="user_123",
        help="User ID for the webhook event (default: user_123)",
    )
    parser.add_argument(
        "--event",
        choices=["activity_created", "activity_updated", "activity_deleted"],
        default="activity_created",
        help="Event type (default: activity_created)",
    )
    parser.add_argument(
        "--resource-id",
        default=None,
        help="Resource ID (default: auto-generated)",
    )
    parser.add_argument(
        "--secret",
        default="whsec_" + "00" * 32,
        help="Webhook secret (default: a development secret of zeros)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed request/response info",
    )
    parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=1,
        help="Number of webhooks to send (default: 1)",
    )

    args = parser.parse_args()

    # Generate resource ID if not provided
    resource_id = args.resource_id or f"resource_{int(time.time())}"

    print(f"\nSending {args.count} webhook(s) to {args.url}")
    print(f"Event: {args.event} | User: {args.user_id} | Resource: {resource_id}")
    print("-" * 60)

    for i in range(args.count):
        if args.count > 1:
            # Generate unique resource ID for each webhook
            current_resource_id = f"{resource_id}_{i + 1}"
        else:
            current_resource_id = resource_id

        try:
            response = send_webhook(
                url=args.url,
                user_id=args.user_id,
                event_type=args.event,
                resource_id=current_resource_id,
                secret=args.secret,
                verbose=args.verbose,
            )

            status_emoji = "✓" if response.status_code < 400 else "✗"
            print(f"{status_emoji} [{response.status_code}] {response.text}")

            if args.verbose and response.headers:
                print(f"  Response headers: {dict(response.headers)}")

        except httpx2.ConnectError:
            print(f"✗ Connection failed - is the server running at {args.url}?")
            sys.exit(1)
        except httpx2.TimeoutException:
            print("✗ Request timed out")
            sys.exit(1)
        except Exception as e:
            print(f"✗ Error: {e}")
            sys.exit(1)

    print("-" * 60)
    print("Done!")


if __name__ == "__main__":
    main()
