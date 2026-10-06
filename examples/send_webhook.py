#!/usr/bin/env python3
# /// script
# dependencies = [
#   "httpx",
# ]
# ///
"""
Webhook simulator for testing SweatStack webhook endpoints.

This script simulates webhook events from SweatStack by:
1. Creating a properly formatted webhook payload
2. Signing it with the webhook secret
3. Sending it to your local webhook endpoint

Usage:
    # Send an activity_created event for a specific user
    uv run send_webhook.py --user-id user_123 --event activity_created

    # Send with custom resource ID
    uv run send_webhook.py --user-id user_123 --event activity_created --resource-id act_789

    # Send to a different endpoint
    uv run send_webhook.py --url http://localhost:8001/webhooks/sweatstack/with-data

    # Use a different webhook secret
    uv run send_webhook.py --secret "my_webhook_secret"
"""

import argparse
import hashlib
import hmac
import json
import sys
import time
from datetime import datetime, timezone

import httpx


def create_signature(payload: bytes, secret: str, timestamp: int) -> str:
    """Create a webhook signature matching SweatStack's format."""
    signed_payload = f"{timestamp}.".encode() + payload
    signature = hmac.new(
        secret.encode(),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


def send_webhook(
    url: str,
    user_id: str,
    event_type: str,
    resource_id: str,
    secret: str,
    verbose: bool = False,
) -> httpx.Response:
    """Send a webhook to the specified URL."""
    # Create payload
    payload = {
        "user_id": user_id,
        "event_type": event_type,
        "resource_id": resource_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    payload_bytes = json.dumps(payload).encode()
    timestamp = int(time.time())
    signature = create_signature(payload_bytes, secret, timestamp)

    if verbose:
        print(f"\n{'='*60}")
        print("Webhook Request")
        print(f"{'='*60}")
        print(f"URL: {url}")
        print(f"Signature: {signature}")
        print(f"Payload: {json.dumps(payload, indent=2)}")
        print(f"{'='*60}\n")

    # Send request
    response = httpx.post(
        url,
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Sweatstack-Signature": signature,
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
        default="whsec_development_secret_key",
        help="Webhook secret (default: whsec_development_secret_key)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed request/response info",
    )
    parser.add_argument(
        "-n", "--count",
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
            current_resource_id = f"{resource_id}_{i+1}"
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

        except httpx.ConnectError:
            print(f"✗ Connection failed - is the server running at {args.url}?")
            sys.exit(1)
        except httpx.TimeoutException:
            print("✗ Request timed out")
            sys.exit(1)
        except Exception as e:
            print(f"✗ Error: {e}")
            sys.exit(1)

    print("-" * 60)
    print("Done!")


if __name__ == "__main__":
    main()
