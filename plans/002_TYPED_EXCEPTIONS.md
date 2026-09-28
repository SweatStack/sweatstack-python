# Typed exception hierarchy for the SweatStack client

## Context

The `sweatstack` Python client currently surfaces `httpx.HTTPStatusError`
directly to consumers via `Client._raise_for_status` /
`Client._print_response_and_raise` (`src/sweatstack/client.py:968-997`).

This has two problems:

1. **Consumers can't branch on error kind without inspecting status codes.**
   Telling apart "upstream is down" (5xx, transient) from "you sent bad input"
   (4xx, your bug) requires `exc.response.status_code`. That's the leaky
   abstraction a client library exists to absorb.
2. **`httpx` is an implementation detail.** Any consumer that wants to handle
   errors must `import httpx` to catch `HTTPStatusError`. If the transport
   ever changes, every consumer breaks.

## Exception hierarchy

```
SweatStackError                       # base -- catch-all for anything sweatstack-related
├── SweatStackConnectionError         # transport-level: DNS, timeout, no response
├── SweatStackTokenRefreshError       # client-side auth failure (before any request)
└── SweatStackAPIError                # HTTP response with error status
    ├── SweatStackAuthError           # 401, 403
    ├── SweatStackNotFoundError       # 404
    ├── SweatStackRateLimitError      # 429 -- exposes retry_after
    ├── SweatStackBadRequestError     # other 4xx
    └── SweatStackServerError         # 5xx
```

`SweatStackTokenRefreshError` is a direct child of `SweatStackError`, not of
`SweatStackAPIError`. Token refresh is a client-side operation that happens
before a request is made -- it has no status code, no URL, no method. Forcing
it under `SweatStackAPIError` would violate Liskov: every `SweatStackAPIError`
guarantees `status_code: int`, and a token refresh failure can't provide one.

### Attributes on `SweatStackAPIError`

```python
class SweatStackAPIError(SweatStackError):
    status_code: int
    url: str
    method: str
    request_id: str | None   # from X-Request-ID header, if present
    body: dict | str | None  # parsed JSON if possible, else raw text, else None
```

`SweatStackRateLimitError` adds `retry_after: int | None` (seconds, from
`Retry-After` header).

`SweatStackConnectionError` and `SweatStackTokenRefreshError` take only a
`message: str`.

### Why these classes

| Class | Reason |
|---|---|
| `SweatStackServerError` | The most important new class. `except SweatStackServerError` handles "upstream is unhappy" without catching consumer bugs. |
| `SweatStackBadRequestError` | Separate from server errors: don't retry, surface to developers. Different remediation = different class. |
| `SweatStackNotFoundError` | 404 is often domain-meaningful ("trace was deleted"), not a bug. Consumers want to handle it as a business case. |
| `SweatStackRateLimitError` | Reserves the class even if the API isn't rate-limited today. Zero cost, prevents future refactoring. |
| `SweatStackConnectionError` | Covers `httpx.ConnectError`, `httpx.ReadTimeout`, etc. Currently these leak through as raw httpx types. |
| `SweatStackAuthError` | Groups 401/403 HTTP responses. |
| `SweatStackTokenRefreshError` | Client-side auth failure. Sibling of `SweatStackAPIError`, not child -- no HTTP response data to carry. |

## Implementation

### 1. New module: `src/sweatstack/exceptions.py`

Define the full hierarchy. Pure module -- no imports from `client.py`, no
`httpx`. This is the public error contract.

```python
class SweatStackError(Exception):
    """Base exception for all SweatStack errors."""

class SweatStackConnectionError(SweatStackError):
    """Transport-level failure: DNS, connect timeout, read timeout, no response."""

class SweatStackTokenRefreshError(SweatStackError):
    """Token refresh failed (expired, missing, or refresh request failed)."""

class SweatStackAPIError(SweatStackError):
    """HTTP response with an error status code."""
    def __init__(self, *, status_code, url, method, request_id=None, body=None):
        self.status_code = status_code
        self.url = url
        self.method = method
        self.request_id = request_id
        self.body = body
        super().__init__(self._format_message())

    def _format_message(self):
        msg = f"{self.status_code}: {self.method} {self.url}"
        if self.request_id:
            msg += f" (request_id={self.request_id})"
        if self.body:
            msg += f" — {self.body}"
        return msg

    def __repr__(self):
        return (
            f"{type(self).__name__}(status_code={self.status_code!r}, "
            f"method={self.method!r}, url={self.url!r})"
        )

class SweatStackAuthError(SweatStackAPIError):
    """401 or 403: authentication or authorization failure."""

class SweatStackNotFoundError(SweatStackAPIError):
    """404: resource not found."""

class SweatStackRateLimitError(SweatStackAPIError):
    """429: rate limited."""
    def __init__(self, *, retry_after=None, **kwargs):
        self.retry_after = retry_after
        super().__init__(**kwargs)

class SweatStackBadRequestError(SweatStackAPIError):
    """4xx (not 401, 403, 404, 429): client sent invalid input."""

class SweatStackServerError(SweatStackAPIError):
    """5xx: server-side failure, transient, safe to retry for idempotent ops."""
```

### 2. Translation in `client.py`

Replace `_raise_for_status` and `_print_response_and_raise` with a single
translation point:

```python
def _raise_for_status(self, response: httpx.Response) -> None:
    if response.is_success:
        return

    status = response.status_code
    body = self._parse_error_body(response)
    request_id = response.headers.get("x-request-id")
    common = dict(
        status_code=status,
        url=str(response.request.url),
        method=response.request.method,
        request_id=request_id,
        body=body,
    )

    if status in (401, 403):
        raise SweatStackAuthError(**common)
    if status == 404:
        raise SweatStackNotFoundError(**common)
    if status == 429:
        retry_after = int(response.headers.get("retry-after", "0")) or None
        raise SweatStackRateLimitError(retry_after=retry_after, **common)
    if 400 <= status < 500:
        raise SweatStackBadRequestError(**common)
    if 500 <= status < 600:
        raise SweatStackServerError(**common)
    # Fallback (e.g. 3xx that wasn't followed) -- shouldn't happen
    raise SweatStackAPIError(**common)

@staticmethod
def _parse_error_body(response: httpx.Response) -> dict | str | None:
    try:
        return response.json()
    except Exception:
        text = response.text
        return text if text else None
```

Wrap transport-level errors at the HTTP call site:

```python
try:
    response = self._http_client.request(...)
except httpx.HTTPError as exc:
    raise SweatStackConnectionError(str(exc)) from exc
self._raise_for_status(response)
```

### 3. Remove `_print_response_and_raise` and `_add_note`

These exist only to annotate `httpx.HTTPStatusError` with response text.
The new exceptions carry `body` natively, so these methods are dead code.

### 4. Clean up the 422 special case

The current code raises `ValueError(response.json())` for 422. This should
raise `SweatStackBadRequestError` like any other 4xx. The parsed validation
error body lands in `body` where consumers can inspect it.

### 5. Clean up the 401/Streamlit special case

`_raise_for_status` currently detects Streamlit and adds a hint note on 401.
After this change, it raises `SweatStackAuthError`. The Streamlit hint (if
still wanted) moves to the Streamlit integration layer, not the core error
path.

### 6. Move `TokenRefreshError` to `exceptions.py`

- Rename to `SweatStackTokenRefreshError`.
- Parent is `SweatStackError` (not `SweatStackAPIError`).
- Remove old definition from `client.py`.
- Import in `client.py` from `exceptions.py`.

### 7. Update `__init__.py` exports

```python
from .client import *
from .exceptions import (
    SweatStackError,
    SweatStackConnectionError,
    SweatStackTokenRefreshError,
    SweatStackAPIError,
    SweatStackAuthError,
    SweatStackNotFoundError,
    SweatStackRateLimitError,
    SweatStackBadRequestError,
    SweatStackServerError,
)
```

### 8. Tests

Unit tests covering each status branch (401, 403, 404, 429, 400, 422, 500,
502, 503, network error). Each test asserts:
- Correct exception type raised
- `status_code`, `url`, `method`, `body` populated correctly
- `request_id` populated when header present
- `retry_after` populated for 429
- Inheritance: e.g. `SweatStackServerError` is caught by
  `except SweatStackAPIError` and `except SweatStackError`
- `__repr__` produces structured output suitable for logging

## Backwards incompatibilities

Since no external consumers exist yet, these are listed for completeness and
to inform the changelog for the first stable release.

| What changed | Before | After |
|---|---|---|
| HTTP error exceptions | `httpx.HTTPStatusError` | `SweatStackAPIError` subclasses |
| 422 responses | `ValueError(response.json())` | `SweatStackBadRequestError` |
| Transport errors (DNS, timeout) | Raw `httpx.ConnectError`, `httpx.ReadTimeout`, etc. | `SweatStackConnectionError` |
| `TokenRefreshError` class name | `TokenRefreshError` | `SweatStackTokenRefreshError` |
| `TokenRefreshError` base class | `Exception` | `SweatStackError` |
| `TokenRefreshError` import path | `from sweatstack import TokenRefreshError` or `from sweatstack.client import TokenRefreshError` | `from sweatstack import SweatStackTokenRefreshError` or `from sweatstack.exceptions import SweatStackTokenRefreshError` |
| 401 + Streamlit hint | Appended as exception note on `httpx.HTTPStatusError` | `SweatStackAuthError` raised; Streamlit hint moves to Streamlit integration layer |
| `_print_response_and_raise` | Public-ish method on `Client` | Removed |
| `_add_note` | Helper on `Client` | Removed |

## Out of scope

- **Built-in retry on 5xx / 429.** Clean follow-up once typed exceptions exist.
- **Idempotency keys on POST.** Requires API-side support.
- **Native async client.** Separate effort.

## Acceptance criteria

- All public client methods that previously raised `httpx.HTTPStatusError`
  raise a `SweatStackAPIError` subclass appropriate to the status code.
- All transport-level failures raise `SweatStackConnectionError`.
- `httpx` types never appear in the public API surface.
- `SweatStackTokenRefreshError` is importable from `sweatstack.exceptions`
  and `sweatstack`.
- Unit tests cover each status branch and verify exception type, attributes,
  and inheritance.
- All `SweatStackAPIError` instances have a useful `__repr__` for debugging.
