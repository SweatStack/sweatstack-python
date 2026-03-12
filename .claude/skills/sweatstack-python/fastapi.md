# FastAPI Integration

Requires: `pip install sweatstack[fastapi]`

## Contents

- [Setup](#setup)
- [Configuration](#configuration)
- [User Dependencies](#user-dependencies)
- [URL Helpers](#url-helpers)
- [User Delegation](#user-delegation)
- [Webhooks](#webhooks)
- [Token Stores](#token-stores)

---

## Setup

Two steps: `configure()` then `instrument()`.

```python
from fastapi import FastAPI
from sweatstack.fastapi import configure, instrument, AuthenticatedUser

app = FastAPI()

configure(
    client_id="YOUR_CLIENT_ID",      # or SWEATSTACK_CLIENT_ID env var
    client_secret="YOUR_SECRET",      # or SWEATSTACK_CLIENT_SECRET env var
    app_url="http://localhost:8000",   # or APP_URL env var
    session_secret="your-fernet-key", # or SWEATSTACK_SESSION_SECRET env var
)

instrument(app)  # Registers auth routes

@app.get("/activities")
def list_activities(user: AuthenticatedUser):
    return user.client.get_activities(limit=10)
```

`instrument()` registers routes at `{auth_route_prefix}/login`, `/callback`, `/logout`, `/select-user/{user_id}`, `/select-self`. Default prefix: `/auth/sweatstack`.

## Configuration

```python
configure(
    client_id: str = None,                    # SWEATSTACK_CLIENT_ID
    client_secret: str = None,                # SWEATSTACK_CLIENT_SECRET
    app_url: str = None,                      # APP_URL
    session_secret: str = None,               # SWEATSTACK_SESSION_SECRET (Fernet key)
    scopes: list[str] = ["profile", "data:read"],
    cookie_secure: bool = None,               # auto-detected from app_url scheme
    cookie_max_age: int = 86400,              # session lifetime in seconds
    auth_route_prefix: str = "/auth/sweatstack",
    redirect_unauthenticated: bool = True,    # True = redirect to login, False = return 401
    webhook_secret: str = None,               # SWEATSTACK_WEBHOOK_SECRET
    token_store: TokenStore = None,           # for webhook user token persistence
)
```

**Redirect URI** is computed automatically: `{app_url}{auth_route_prefix}/callback`

## User Dependencies

Inject into endpoint handlers via type annotations:

```python
from sweatstack.fastapi import AuthenticatedUser, SelectedUser, OptionalUser, OptionalSelectedUser

@app.get("/me")
def get_me(user: AuthenticatedUser):
    # Always the principal (logged-in) user. Returns 401 if not authenticated.
    return user.client.get_userinfo()

@app.get("/dashboard")
def dashboard(user: SelectedUser):
    # Delegated user if one is selected, otherwise principal.
    # Returns 401 if not authenticated.
    return user.client.get_activities()

@app.get("/public")
def public(user: OptionalUser):
    # Principal user or None. Never raises 401.
    if user:
        return user.client.get_activities()
    return {"message": "Log in to see activities"}

@app.get("/feed")
def feed(user: OptionalSelectedUser):
    # Selected user or None. Never raises 401.
    ...
```

**`SweatStackUser`** — the object all dependencies return:
- `user.client` — authenticated `Client` instance
- `user.user_id` — user ID extracted from JWT

## URL Helpers

Generate URLs for auth actions in templates and redirects:

```python
from sweatstack.fastapi import urls

urls.login()                              # /auth/sweatstack/login
urls.login(next="/dashboard")             # /auth/sweatstack/login?next=/dashboard
urls.logout()                             # /auth/sweatstack/logout
urls.select_user("user_id")              # /auth/sweatstack/select-user/user_id
urls.select_user("user_id", next="/app") # /auth/sweatstack/select-user/user_id?next=/app
urls.select_self()                        # /auth/sweatstack/select-self
```

## User Delegation

Switch the session to operate as another user:

```python
@app.get("/users")
def list_users(user: AuthenticatedUser):
    # List users accessible to the principal
    users = user.client.get_users()
    # Generate switch links
    return [
        {"name": u.display_name, "switch_url": urls.select_user(u.id, next="/dashboard")}
        for u in users
    ]
```

The built-in `/select-user/{user_id}` and `/select-self` routes handle token delegation. After switching, `SelectedUser` returns the delegated user's client.

## Webhooks

Receive and verify webhook events from SweatStack.

```python
from sweatstack.fastapi import configure, WebhookPayload, AuthenticatedUser

configure(
    webhook_secret="your-webhook-secret",  # or SWEATSTACK_WEBHOOK_SECRET
    token_store=SQLiteTokenStore(),         # required for webhook user lookups
)

@app.post("/webhooks/sweatstack")
def handle_webhook(payload: WebhookPayload, user: AuthenticatedUser):
    # payload.user_id, payload.event_type, payload.resource_id, payload.timestamp
    # user.client is authenticated as the webhook's user (loaded from token store)
    activity = user.client.get_activity(payload.resource_id)
    process(activity)
```

**`WebhookPayload`** dependency verifies the `X-Sweatstack-Signature` header automatically. Returns 400 if invalid.

**Signature verification** uses HMAC-SHA256 with a 5-minute timestamp tolerance.

**Manual verification** (without the dependency):

```python
from sweatstack.fastapi import verify_signature

verify_signature(
    payload=request_body_bytes,
    signature_header=request.headers["X-Sweatstack-Signature"],
    secret="your-webhook-secret",
)
```

### Webhook Exceptions

| Exception | When |
|---|---|
| `WebhookVerificationError` | Invalid signature or expired timestamp |
| `WebhookTokenStoreError` | TokenStore not configured |
| `WebhookUserNotFoundError` | No stored tokens for the webhook's user |
| `WebhookTokenRefreshError` | Stored tokens expired and refresh failed |

## Token Stores

Required for webhooks — persists user tokens so webhooks can authenticate as the user.

Tokens are saved automatically when users log in through the OAuth flow.

**Built-in stores (development only):**

```python
from sweatstack.fastapi import SQLiteTokenStore, EncryptedSQLiteTokenStore

# Plain SQLite
store = SQLiteTokenStore(db_path="tokens.db")

# Encrypted SQLite (Fernet AES-128-CBC)
store = EncryptedSQLiteTokenStore(
    encryption_key="your-key",
    db_path="tokens_encrypted.db",
)
```

**Production:** Implement the `TokenStore` protocol:

```python
from sweatstack.fastapi import TokenStore, StoredTokens

class RedisTokenStore(TokenStore):
    def save(self, tokens: StoredTokens) -> None: ...
    def load(self, user_id: str) -> StoredTokens | None: ...
    def delete(self, user_id: str) -> None: ...
```

`StoredTokens` fields: `user_id`, `access_token`, `refresh_token`, `expires_at: datetime`.
