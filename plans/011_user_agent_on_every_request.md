# Plan 011: Every request the SDK makes carries its User-Agent

Requests made through `Client` identify themselves as `python-sweatstack/<version>`. The four
token calls in the FastAPI and Streamlit integrations do not: each is a bare `httpx.post`, so it
goes out as `python-httpx/<version>`, the library default. Seen from the server, an integrator's
logins, refreshes and delegations look like an unknown httpx script, not like the SDK at a known
version. That makes three things harder than they should be: telling an integrator which SDK
version they run, tying a token-endpoint failure to an SDK release, and knowing when an old
release has stopped being used.

The fix is one constant, one function and one guard. **Constant:** the header string has one
home, next to `__version__`. **Function:** every request that does not go through the client's
pool goes through `_transport.post`, which adds the header. **Guard:** a test fails on any
request made with `httpx` directly from anywhere else, so the next bare call is caught at
`make check`, not in the server's logs.

Proposed 2026-10-13. Ships in the next release, under *Fixed*, next to the scope work already under
`[Unreleased]`; no public surface changes.

> **Public repository.** This file is published with the code. It describes the SDK by its own
> source and the server by its public contract. It cites no app, no version in use, no counts
> and no time window from server logs; those are customer behaviour and stay out (AGENTS.md,
> "Public repository").


## As built (2026-10-13)

Sections 2 to 5 shipped as designed, with three refinements:

- **`__version__` is public at the package root.** `client.py` no longer defines or imports
  it; `sweatstack.__version__` re-exports it from `constants.py`, which is where Python users
  look for it. Nothing in the repository read it from `client.py`. Listed under *Added*.
- **The guard also catches `from httpx import post`.** D5 named attribute calls only; the test
  flags a `from httpx import ...` of any request-making name too, so the rule cannot be dodged
  by changing the import style.
- **The callback test runs the real route.** It mounts the router with `instrument`, sets the
  state cookie that `create_state` mints and follows the handler through to the session
  redirect, so a change to the state check or the exchange would surface here.


## 1. The problem, verified

### 1.1 What the header is for

The server reads `User-Agent` to attribute traffic to an SDK release. The client has sent
`python-sweatstack/<version>` since the pooled connection landed; every call that goes through
`Client._request` carries it, including the client's own token exchange and refresh. The value
comes from `importlib.metadata.version("sweatstack")`, with `"unknown"` as the fallback when
the package is not installed.

### 1.2 Where it is missing

On `main` at 0.94.0, four requests bypass the pool. Each is a bare `httpx.post` with no
`User-Agent`:

| Call site | Endpoint | When it runs |
|---|---|---|
| `fastapi/dependencies.py`, `_refresh_access_token` | `POST /api/v1/oauth/token` (`refresh_token`) | Every request whose session token is about to expire |
| `fastapi/routes.py`, the `/callback` route | `POST /api/v1/oauth/token` (`authorization_code`) | Every login |
| `fastapi/routes.py`, `_fetch_delegated_token` | `POST /api/v1/oauth/delegated-token` | Switching to a delegated user |
| `streamlit.py`, `StreamlitAuth._exchange_token` | `POST /api/v1/oauth/token` (`authorization_code`) | Every login |

The refresh is by far the most frequent of the four: a long-running app makes one per session
per token lifetime, which is why token traffic from the integrations is mostly anonymous today.

Nothing else is affected. `client.py` builds exactly one `httpx.Client`, the pool, with the
header set. `cli.py` fetches a local `openapi.json` with `httpx.get`; that is a developer tool
and stays as it is. No other HTTP library is used anywhere in `src/`.

### 1.3 How it got this way

Release 0.65.0 had the same defect inside `Client`: a bare `httpx.post` for the token exchange
next to a pooled client that did carry the header. The pool refactor fixed it for `Client` by
routing the exchange through `_http_client`. The integrations were never followed up. Plan 010
noted the Streamlit exchange as "not folded in" and left it for later; this is later.

The header string is also written out twice in `client.py`, once for the pool and once in
`_http_client`. Two copies today, no shared one, and `__version__` lives in `client.py`, which
is the wrong place for the integrations to import from.


## 2. Design

Five decisions. Each names the alternative it rejects.

**D1. One constant, one home.** `constants.py` gains

```python
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("sweatstack")
except PackageNotFoundError:
    __version__ = "unknown"

USER_AGENT = f"python-sweatstack/{__version__}"
```

and `client.py` imports both names from there, so `sweatstack.client.__version__` keeps
working. `constants.py` imports nothing from the package and every call-site module already
imports it, so there is no cycle to manage. *Rejected:* a new `_version.py` module. One more
file for one line, and `constants.py` is already the home for values every entry point shares.

**D2. One function for requests outside the pool.** `_transport.py` gains

```python
def post(url: str, **kwargs: Any) -> httpx.Response:
    """``httpx.post`` with the SDK's ``User-Agent``; the caller's headers win on a clash."""
    headers = httpx.Headers({"User-Agent": USER_AGENT})
    headers.update(kwargs.pop("headers", None) or {})
    return httpx.post(url, headers=headers, **kwargs)
```

It adds the header and nothing else. No retry (`POST` is never retried; see
`RETRYABLE_METHODS`), no error translation, no timeout. The four sites keep their own error
handling and timeouts exactly as they are. *Rejected:* passing `headers={"User-Agent": ...}` at
each site. It works, but then the guard has to prove that every multi-line call passes the
header, which a test cannot do reliably. With a function, the guard is one rule: nobody but
the transport talks to `httpx`.

**D3. The integrations stay stateless.** They do not acquire a `Client` to make the call. They
are deliberately thin helpers over the token endpoint, with no token pair of their own to
manage, and a `Client` would bring the refresh lock and credential resolution of plan 010 into
code paths that must not have them. *Rejected:* `Client(auth=False)._request(...)`; a bigger
change than the header needs, and it pulls a user-facing object into a server hot path.

**D4. The value stays `python-sweatstack/<version>`.** Identical to what the client sends, so
the server sees one SDK, not two. *Rejected:* appending `python-httpx/<version>` or a runtime
description, as some SDKs do. Nothing on the server reads it, and it would make the two paths
disagree.

**D5. The guard is an AST test, not a grep.** It parses every module under `src/sweatstack/`
and fails on a call to `httpx.get`, `post`, `put`, `patch`, `delete`, `request`, `stream`,
`Client` or `AsyncClient` outside an allow-list of three: `_transport.py` (the function above),
`client.py` (the pool) and `cli.py` (the developer tool). *Rejected:* the regex in the first
draft of this plan. A regex matches text, not calls, and cannot see across the lines of a call
to check what it passes.


## 3. Change

Seven files, all small. Order matters only for the first two.

1. **`constants.py`**: add `__version__` and `USER_AGENT` as in D1.
2. **`client.py`**: drop the local `__version__` block and the `importlib.metadata` import;
   `from .constants import DEFAULT_SCOPE, DEFAULT_URL, USER_AGENT, __version__`. Replace both
   header literals (the pool and `_http_client`) with `USER_AGENT`.
3. **`_transport.py`**: add `post` as in D2, importing `USER_AGENT` from `constants`.
4. **`fastapi/dependencies.py`**: `httpx.post(...)` in `_refresh_access_token` becomes
   `_transport.post(...)`, same arguments. The `timeout=REFRESH_HTTP_TIMEOUT` stays.
5. **`fastapi/routes.py`**: the same substitution in the `/callback` route and in
   `_fetch_delegated_token`. The latter keeps its `Authorization` header; the function merges it
   under the SDK header. Both keep their `httpx.HTTPError` handling, which still applies since
   the function raises what `httpx.post` raises. The `import httpx` stays, for the exception
   type.
6. **`streamlit.py`**: the same substitution in `_exchange_token`, keeping `auth=` and `data=`.
   The `import httpx` stays, for `httpx.BasicAuth`.
7. **`CHANGELOG.md`**: see section 5.

Nothing in the body, auth, timeout or error path of any of the four calls changes. A diff of
each site is one token: `httpx.post` to `_transport.post`, plus the import.


## 4. Tests

All offline, all under `tests/`. `make check` must pass with no silenced findings.

**The function** (`tests/test_transport.py`, where the HTTP layer is tested):

- `post` sends `User-Agent: python-sweatstack/<version>` and passes the URL and keyword
  arguments through unchanged.
- A caller's `Authorization` header survives the merge.
- A caller's own `User-Agent` wins, so the merge rule in the docstring is true.

**The guard** (`tests/test_transport.py`): the AST walk of D5. It fails with the file, line and
call that broke the rule, so the fix is obvious from the message.

**The four call sites** (new `tests/test_user_agent.py`): one test each, patching
`httpx.post` and asserting the request's `User-Agent` equals `constants.USER_AGENT` and that
what the site sent before is still sent (grant type, code, credentials, bearer).

- `_refresh_access_token` is a function; call it directly.
- `_fetch_delegated_token` is a function; call it directly and also assert the bearer is
  still on the request.
- The `/callback` route runs through `fastapi.testclient.TestClient` on an app configured as
  in `tests/test_access_token_cache.py`, with a `state` query parameter that matches the state
  cookie, so the handler reaches the exchange.
- `StreamlitAuth._exchange_token` runs with the session fixtures from
  `tests/test_streamlit_auth.py`.

Patching `httpx.post` rather than injecting `httpx.MockTransport` is deliberate: a module-level
`httpx.post` builds its own client and accepts no transport, and the function keeps that shape
on purpose (D2).

**Done when:**

- The four tests above and the three function tests pass.
- The guard passes on `main` plus this change, and fails when a bare `httpx.post` is put back
  into any of the four sites.
- `grep -rn "python-sweatstack/" src/` finds exactly one line, in `constants.py`.


## 5. Release

Part of the next release, with the scope work already under `[Unreleased]`. Add there:

> ### Fixed
> - Token calls from the FastAPI and Streamlit integrations (login, refresh and delegated
>   tokens) now send the `python-sweatstack/<version>` User-Agent, like every other request
>   the SDK makes. Before, they identified themselves as plain httpx.

Not breaking: no name, parameter or behaviour visible to a caller changes, so there is no
*Upgrading* section and nothing for `_renames`. The skill in `skills/sweatstack-python/` and the
docs describe the public surface, which is unchanged, so neither moves.


## 6. Seen while looking, left alone

Three things this plan does not change. Each would be its own decision.

- **`cli.py`** keeps its bare `httpx.get`. It talks to a developer's local server and is
  allow-listed by the guard with a comment saying why.
- **Timeouts differ across the four sites.** The refresh passes `REFRESH_HTTP_TIMEOUT`; the two
  logins and the delegation use httpx's default. Whether the three should share a constant is a
  reliability question, not a header question.
- **Error handling differs across the four sites.** One calls `raise_for_status`, one
  translates to the SDK's exceptions, one redirects with an error code, one raises
  `SweatStackAuthError`. Each is right for its caller; unifying them is not this plan's job.
