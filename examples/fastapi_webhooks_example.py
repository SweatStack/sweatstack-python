# /// script
# dependencies = [
#   "fastapi[standard]",
#   "sweatstack[fastapi] @ file://..",
# ]
# ///

import logging
import os
from pathlib import Path

# Required environment variables:
#   SWEATSTACK_CLIENT_ID
#   SWEATSTACK_CLIENT_SECRET
#   SWEATSTACK_SESSION_SECRET
#   SWEATSTACK_WEBHOOK_SECRET
#   SWEATSTACK_ENCRYPTION_KEY  (for EncryptedSQLiteTokenStore)
#   APP_URL (e.g. http://localhost:8001)
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from sweatstack.fastapi import (
    AuthenticatedUser,
    EncryptedSQLiteTokenStore,
    OptionalUser,
    WebhookPayload,
    configure,
    instrument,
    urls,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


db_path = Path(__file__).parent / "tokens.db"
token_store = EncryptedSQLiteTokenStore(
    encryption_key=os.environ["SWEATSTACK_ENCRYPTION_KEY"],
    db_path=db_path,
)

configure(
    token_store=token_store,
)  # Uses SWEATSTACK_* environment variables (CLIENT_ID, CLIENT_SECRET, SESSION_SECRET, WEBHOOK_SECRET, APP_URL)

app = FastAPI(title="SweatStack Webhooks Example")
instrument(app)


@app.get("/", response_class=HTMLResponse)
def home(user: OptionalUser):
    if not user:
        return f"""
        <h1>SweatStack Webhooks Example</h1>
        <p><a href="{urls.login()}">Login with SweatStack</a></p>
        """

    activities = user.client.activities.list(limit=5)
    activity_ids = [a.id for a in activities]

    return f"""
    <h1>Welcome!</h1>
    <p>User: <strong>{user.user_id}</strong></p>
    <p>Recent activities: {activity_ids}</p>
    <form method="POST" action="{urls.logout()}">
        <button type="submit">Logout</button>
    </form>
    """


@app.post("/webhooks/sweatstack")
async def handle_webhook(payload: WebhookPayload, user: AuthenticatedUser):
    logger.info(
        "Received webhook: event=%s user=%s resource=%s",
        payload.event_type,
        payload.user_id,
        payload.resource_id,
    )

    activity = user.client.activities.retrieve(payload.resource_id)
    logger.info(f"{activity=}")

    return {"status": "received", "event_type": payload.event_type}
