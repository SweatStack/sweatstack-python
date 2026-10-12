# Plan 010: Credentials have one source; sessions renew their own tokens

> **Sensitive until released.** Section 1.1 describes a vulnerability. The repository is
> public and so is everything committed to it, `plans/` included. Commit this file in the
> same commit as the fix, not before, and keep the CHANGELOG entry factual and brief.

Two problems, one cause, one release. A `Client` assembles its access token and refresh
token **field by field** from three places (arguments, environment, a file on the machine)
and writes every refresh back to that file. On a single-user machine that is the intended
convenience. In a server process it hands one user's credentials to another. The same
assembly is why a Streamlit session cannot renew its token sensibly: the session has no
place of its own to keep the pair, so it either borrows from the file or refreshes again on
every rerun.

The fix is one rule and one mechanism. **Rule:** a client's token pair comes from exactly
one source, and a refresh is written back only to a source that owns it. **Mechanism:** a
client can report a refresh to whoever gave it the pair, so a Streamlit session keeps its
own renewed pair in session state, and the proxy mode gets the refresh token it was missing.

Proposed 2026-10-12. Supersedes the two drafts it merges (token pair integrity; Streamlit
proxy token renewal). One minor release, **0.94.0**. Built 2026-10-12; see "As built".


## As built (2026-10-12)

Everything in sections 2 to 5 shipped as designed, with these refinements:

- **The cache is the instance pair.** D5's "cache the hit" is `_resolve_credentials` loading the
  ambient pair into `_api_key` / `_refresh_token` and setting `_file_backed`; there is no
  separate source field. A setter therefore makes the arguments the source by construction.
- **`_save_tokens` is the choke point for D2 and D3.** It marks the client file-backed and
  refuses an `ambient_credentials=False` client, so `exchange_code(persist=True)` and
  `authenticate(persist=True)` need no logic of their own beyond `authenticate()`'s early check.
- **The actionable message is a hint on the client** (`_no_refresh_hint`), the second sentence
  of the expiry error. `behind_proxy()` sets the reload advice on a client that got no refresh
  header; the default names `refresh_token=` and `authenticate(force=True)`.
- **A refresh token alone signs the client in.** D1 said so; `api_key` now renews on first use
  when the access token is missing, which also makes `SWEATSTACK_REFRESH_TOKEN` alone work.
- **`_set_api_key` always sets both halves.** It used to keep the previous refresh token when
  the new pair had none, which paired an admin-delegated access token with the principal's
  refresh token: the same mixing, one level up. Listed under Fixed.
- **Not folded in:** `_exchange_token` in `streamlit.py` still posts to the token endpoint
  itself (section 8). It stores both halves through `_set_api_key`, so nothing depends on it.


## 1. The problems, verified

### 1.1 A client can act as another user (security)

Three behaviours in `client.py` combine:

1. **Every refresh writes one file per machine.** `_refresh_if_expired` always calls
   `_save_tokens`, which writes the pair to `user_data_dir("SweatStack") / tokens.json`,
   whatever the pair's origin. The file is `0600`, which is no protection on a server: every
   session runs as the same OS user.
2. **Missing halves are filled one by one.** `_load_token_pair` takes the access token and
   the refresh token separately from: the instance, then `SWEATSTACK_API_KEY` /
   `SWEATSTACK_REFRESH_TOKEN`, then the file. The `refresh_token` property does the same.
3. **A client with no credentials takes both halves from the file.** This is the CLI feature
   (`Client()` after `authenticate()`), but it applies in any process.

In a multi-user process (Streamlit, FastAPI, any server building per-user clients):

- **A token-only client borrows a refresh token.** User B's client refreshes and writes B's
  pair to the file. User A's client, built with an access token only, expires, takes B's
  refresh token from the file, refreshes, and **acts as B** from then on.
- **A credential-less client is whoever refreshed last.** After any refresh in the process,
  a bare `Client()` is authenticated as that user. `StreamlitAuth.__init__` builds exactly
  such a client for a session that has not logged in, and the OAuth-mode logout button
  builds another. `is_authenticated()` still says `False` (it checks the auth object, not
  the client), so an app that calls `auth.client` without that check serves another
  user's data. No token is needed to hit this path, which makes it the most realistic one.
- **The environment has the same flaw with a smaller blast radius.** A server whose
  environment holds `SWEATSTACK_REFRESH_TOKEN` (a developer running an app locally, a
  service account) pairs it with every token-only client's access token.

Reproduction, offline, passes today (shows the bug). Make it the regression test:

```python
import base64, json, time
from unittest.mock import patch
from sweatstack import Client

def jwt(sub, exp):  # unsigned, enough for the client's expiry check
    body = base64.urlsafe_b64encode(json.dumps({"sub": sub, "exp": exp}).encode()).decode()
    return f"header.{body.rstrip('=')}.signature"

def acts_as(client):
    body = client.api_key.get_secret_value().split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=="))["sub"]

owners = {"refresh_b": "user_b"}
with (
    patch.object(Client, "_get_token_file_path", lambda self: tmp_path / "tokens.json"),
    patch.object(Client, "_do_token_refresh", lambda self, rt: jwt(owners[rt], time.time() + 900)),
):
    expired = time.time() - 60
    Client(jwt("user_b", expired), refresh_token="refresh_b").api_key  # B refreshes once

    assert acts_as(Client(jwt("user_a", expired))) == "user_b"   # A's client became B
    assert acts_as(Client()) == "user_b"                          # a bare client is B
```

Where it triggers today:

| Path | Writes the file | Reads the file |
|---|---|---|
| `StreamlitAuth` OAuth mode, `auth.client` after login | on every refresh | `__init__` before login; after `logout_button` |
| `StreamlitAuth.select_user` / `switch_to_principal_user`, and `delegated_client()` / `principal_client()` anywhere (clients from `_with_tokens`) | when the delegated or principal client refreshes | when the response has `refresh_token: null`, which it does for admin access to a user |
| `StreamlitAuth.behind_proxy` | never (`skip_token_expiry_check=True`) | never for that client; `select_user` as above |
| `fastapi` dependencies (`Client(api_key=, refresh_token=)` per request) | on every refresh | never (`StoredTokens.refresh_token` is always set) |
| `oauth.exchange_code(...)`, `persist=True` by default | at every login, for every user | never |
| App code: `Client(api_key=token)` from a request | on refresh, when a refresh token was given | when it was not |

### 1.2 Streamlit sessions cannot renew their token, or renew on every rerun

**Proxy mode.** An authenticating proxy (the SweatStack Streamlit template) keeps the
user's tokens in a cookie, refreshes them on HTTP requests, and forwards the access token as
`X-SweatStack-Token`. Streamlit exposes request headers through `st.context.headers` **from
the WebSocket handshake only** (its docstring: "headers sent in the initial request"), and a
session keeps that WebSocket for as long as the tab is open: hours, for an installed app left
in the background. `behind_proxy()` builds `Client(token, skip_token_expiry_check=True)`:
no refresh token, expiry check off. After the access token lifetime (15 minutes at the time
of writing) every call sends an expired token. What the user sees depends on the path:

- a 401 from the API, e.g. from `principal_client()` inside `select_user()`, which the
  template calls on every rerun;
- `SweatStackTokenRefreshError: Access token expired but no refresh token available` from
  clients that `_set_api_key` builds without the skip flag; and before this plan, a
  refresh with whatever refresh token sits in the token file (section 1.1).

Reloading the page fixes it (new handshake, fresh token), which is why it looks random.

**OAuth mode has a quieter version of the same problem.** `StreamlitAuth.__init__` rebuilds
`auth.client` on every rerun from the pair in `st.session_state`. When the client refreshes
mid-run, the new access token lives only in that client; the next rerun starts again from
the expired token in session state and refreshes again. After the first lifetime, every
rerun costs one token request, and the session can never pick up a rotated refresh token.

**Why not reconnect the WebSocket.** The proxy could close the socket before the token
expires so that Streamlit reconnects with a fresh handshake. Rejected: a disconnect is
destructive in Streamlit. `WebsocketSessionManager.disconnect_session` (verified in
Streamlit 1.64) calls `request_script_stop()` and `clear_session_caches()`, so every
recycle would abort a running script and drop the session's session-scoped caches, and the
proxy cannot tell a quiet session from one in a long computation. The token has to be
renewable where it is used.

### 1.3 Facts the design relies on

| Fact | Where it is established |
|---|---|
| A refresh returns the **same** refresh token (no rotation) | Confirmed against the API (2026-10-12); already relied on and documented in `fastapi/access_token_cache.py`. The design handles rotation anyway (D6) but the proxy mode needs the no-rotation contract (D15). |
| An access token lives 15 minutes | Confirmed against the API (2026-10-12). |
| `TokenResponse.refresh_token` is optional on the wire | `openapi_schemas.py`. A refresh response without it means "keep yours". |
| A delegated or principal token may come **without** a refresh token, and a team-delegated refresh token is **rejected** on refresh | Confirmed against the API (2026-10-12): admin access to a user yields `refresh_token: null`; a team delegation yields one that the token endpoint refuses with the instruction to delegate again. The principal-token endpoint follows the same rules. So a client built by `_with_tokens` is a token-only client in the admin case: D1 is what stops it borrowing. |
| `st.context.headers` is the handshake's headers; `st.session_state` is per session, in memory, not shared across sessions | Streamlit docs and source, 1.64; the package requires `streamlit>=1.42`. |


## 2. Design

Three principles, then the decisions that follow from them.

- **One source per pair.** The access token and the refresh token always come from the same
  place. A missing half is never filled from elsewhere.
- **Write back only to an owner.** A refreshed pair goes to the file only when the file is
  where the pair lives; to a session only when the session gave the pair; nowhere otherwise.
- **Server integrations never see ambient credentials.** Nothing in the environment or on the
  disk of a server is a user's credential.

### 2.1 The `Client`

**D1. Resolution order, whole pairs.** The client resolves its credentials from the first
source that provides *either* half, and takes both halves from that source:

1. the instance: `api_key=` / `refresh_token=` arguments and the two setters;
2. the environment: `SWEATSTACK_API_KEY` / `SWEATSTACK_REFRESH_TOKEN`;
3. the token file (CLI and notebooks).

An access token without a refresh token means "this token, no renewal": on expiry the
client raises `SweatStackTokenRefreshError` with the message it already has. A refresh token
without an access token is fine: the first use refreshes.

**D2. Write-back only to a file-backed client.** A client is *file-backed* when its pair was
loaded from the file, or saved to it by `authenticate(persist=True)` /
`exchange_code(persist=True)`. Only a file-backed client writes the file after a refresh.
Instance- and environment-sourced clients keep the new pair in memory, as they do today.

| Source | Reads env | Reads file | Writes file after refresh |
|---|---|---|---|
| instance (arguments, setters) | no | no | no |
| environment | yes | no | no |
| file | yes (first) | yes | **yes** |
| after `persist=True` | — | — | **yes** (now file-backed) |
| `ambient_credentials=False` | no | no | no |

**D3. `ambient_credentials: bool = True`**, keyword-only on `Client.__init__`. With
`False` the client stops after the instance: it never reads the environment or the file and
never writes the file; `authenticate(persist=True)` on such a client raises `ValueError`.
Every `Client(...)` call in `streamlit.py` passes `False`, and `_with_tokens` propagates it
so delegated and principal clients inherit it. The FastAPI dependencies already pass a full
pair; they pass `False` too, so the guarantee does not depend on D1. The default is unchanged
for scripts and notebooks. (Name chosen over `use_stored_credentials` and a pluggable
`storage=`: the first says what is excluded, the last is an abstraction with one real
implementation. Revisit at 1.0 only if a second store appears.)

**D4. A refresh hook.** `Client` gets a private `_on_refresh: Callable[[str, str | None],
None] | None`, called inside the refresh lock after the instance pair is updated, with the
new access token and the refresh token now in force. The Streamlit integration uses it to
write the pair back to session state (section 2.2). Private on purpose: the FastAPI
integration refreshes before building the client so it can set the cookie on the response,
and no third caller exists. Promote it to a public parameter when one does.

**D5. Resolve once, cache the hit.** `api_key` re-reads the file today on every access.
Resolution runs on first use and the pair and its source are cached on the instance; a
resolution that finds nothing is not cached, so a client created before `load_dotenv()` or
before `authenticate()` still finds credentials on its next use (this matters for the
module-level default client, created at import). The setters write the instance pair and
make it the source. Store the cache via `self.__dict__.setdefault` like the refresh lock, so
a client built with `Client.__new__` in tests keeps working.

**D6. Rotation-safe.** `_do_token_refresh` returns the whole `TokenResponse`. When it carries
a `refresh_token`, that value replaces the instance's; the write-back (D2) and the hook (D4)
see the new one. Today the client assumes the old refresh token stays valid.

**D7. `exchange_code(persist=False)` by default.** The method exists for apps that run the
authorization code flow themselves, i.e. servers, and its default writes every user's pair
to the server's disk. `authenticate()` passes `persist=True` explicitly, so the CLI flow is
unchanged. Silent behaviour change; see Upgrading.

**D8. `authenticate()`** keeps its order and its `persist=True` default. It is the one place
that chooses the file. After a successful sign-in with `persist=True` the client is
file-backed (D2), so later refreshes in the same process keep the file current.

### 2.2 `StreamlitAuth`: the session owns the pair

The per-session store is `st.session_state`. It is in memory, per session, never shared
across sessions, and it survives reruns: everything the token file is on a laptop, scoped
correctly for a server.

**D9. One pair per client, written back on refresh.** Every client the integration builds
is `Client(access, refresh_token=refresh, ambient_credentials=False, _on_refresh=...)` with
the hook writing the renewed pair to the session-state keys that pair came from. After a
refresh the next rerun starts from the renewed token: one token request per lifetime, not
one per rerun. The hook tolerates being called outside a script thread (an app that fans
out API calls to a thread pool): catch Streamlit's missing-context error, log at debug, and
move on. The renewed token still serves that run.

**D10. Session-state keys.**

| Key | Holds | Written by |
|---|---|---|
| `sweatstack_api_key`, `sweatstack_refresh_token` (existing, documented in the skill) | the pair behind `auth.client`: the signed-in user in OAuth mode, or the selected user after `select_user()` | `_set_api_key`, the hook of that client |
| `sweatstack_proxy_api_key`, `sweatstack_proxy_refresh_token` (new) | the user's own pair in proxy mode, reconciled with the handshake headers | `behind_proxy()`, the hook of that client |

Keeping the proxy pair apart from the `auth.client` pair is what lets `select_user()` keep
working in proxy mode: a delegation overwrites the first pair, never the user's own.

**D11. The header contract.** `behind_proxy(..., refresh_header_name=
"X-SweatStack-Refresh-Token")` reads the refresh token next to the access token. Both headers
are set by the proxy only; a well-behaved proxy strips client-supplied `X-SweatStack-*`
headers. `client_id` / `client_secret` come from `SWEATSTACK_CLIENT_ID` /
`SWEATSTACK_CLIENT_SECRET`, which the proxy deployment already has, because the token
endpoint authenticates application refreshes by `client_id`.

**D12. Reconciliation on every `behind_proxy()` call.** Let `(A_h, R_h)` be the header pair
and `(A_s, R_s)` the stored proxy pair, if any.

1. **No access header:** the user is logged out at the proxy. Clear the proxy pair; `auth.client`
   is a credential-less client (`ambient_credentials=False`); `is_authenticated()` is `False`.
2. **Access header, no refresh header** (older or differently configured proxy): use
   `(A_h, None)`, store nothing, expiry check **on**. Before expiry this is today's behaviour.
   After expiry the first call raises `SweatStackTokenRefreshError` whose message says to
   reload the page or have the proxy forward `X-SweatStack-Refresh-Token`, instead of a 401.
3. **Both headers, `R_s == R_h`:** same login. The access token is whichever of `A_h`, `A_s`
   expires later: the stored one after an in-session refresh, the header one after a
   reconnect or reload. An undecodable token counts as expired.
4. **Both headers, otherwise:** a new login in this tab (or nothing stored). The header pair
   replaces the stored one.

In cases 3 and 4 the stored pair is `(A, R_h)` and `auth.client` is built from it per D9.
Delegated pairs under the first key pair (D10) are left alone here; `select_user()` rebuilds
them every run, as it does today.

**D13. User switching.** `select_user()` and `switch_to_principal_user()` derive from
`self.client`, which is now renewable in both modes, so `principal_client()` keeps working
after the first lifetime. The clients they produce carry their own pair (`_with_tokens`) and
inherit `ambient_credentials=False`. A delegated pair is not always renewable (no refresh
token for admin access, a rejected one for team delegation; section 1.3): on expiry such a
client raises `SweatStackTokenRefreshError`, and the next rerun re-delegates through the
principal, which `select_user()` already does every run.

**D14. Logout.** OAuth-mode `logout_button` clears both key pairs and builds a
credential-less client with `ambient_credentials=False`. Proxy-mode logout stays a link to
the proxy; the next handshake has no header and case 1 clears the state.

**D15. The no-rotation dependency, stated.** The proxy refreshes for the cookie and the
session refreshes in memory, with the same refresh token. If the server ever rotates refresh
tokens, the two diverge: the session's rotated token invalidates the cookie's, and case 4
hands the session the dead header token on the next reload. D6 keeps the client correct; the
proxy mode would need the proxy to push tokens instead. Record this in the `behind_proxy()`
docstring and in the FastAPI cache module's existing note.

### 2.3 FastAPI

The dependencies always build a full pair, so D1 already stops the borrowing and D2 stops
the writes. Pass `ambient_credentials=False` in both constructors for defence in depth and
add the regression test (section 4). No behaviour change.

### 2.4 What does not change

`Client()` plus `authenticate()` on a laptop; the environment variables for headless use; the
expiry margin; the refresh lock; `skip_token_expiry_check` (still the right tool when a
proxy renews tokens per HTTP request and the client never should); the public exception
hierarchy. No new runtime dependency.


## 3. Implementation

In this order, each step leaving `make check` green.

1. **Test isolation first.** `tests/conftest.py` (new) with an autouse fixture that points
   `Client._get_token_file_path` at `tmp_path` and removes `SWEATSTACK_API_KEY`,
   `SWEATSTACK_REFRESH_TOKEN`, `SWEATSTACK_CLIENT_ID` and `SWEATSTACK_CLIENT_SECRET` from
   the environment. Today the suite can read the developer's real token file; the two
   existing ad-hoc patches (`test_identity.py`, `test_transport.py`) become redundant and
   go.
2. **`client.py`.** Replace `_load_token_pair` with `_resolve_credentials() -> (access,
   refresh, source)` implementing D1, D3 and D5; `api_key` and `refresh_token` properties
   read it. `_refresh_if_expired` implements D2, D4 and D6. `__init__` gains
   `ambient_credentials` and the private `_on_refresh`; `_with_tokens` propagates both the
   flag and the hook's absence (a derived client gets no hook; the integration sets its own).
   `_do_token_refresh` returns `TokenResponse`. `authenticate()` marks the client file-backed
   after `persist=True` and raises `ValueError` for `persist=True` with ambient credentials
   off. `_save_tokens` is called from exactly two places afterwards: the refresh path, when
   file-backed, and `exchange_code(persist=True)`.
3. **`resources/oauth.py`.** `exchange_code(persist=False)` (D7); with `persist=True` it
   also marks the client file-backed.
4. **`streamlit.py`.** `_set_api_key` and `__init__` build clients per D9 with a hook to the
   first key pair; `behind_proxy()` implements D11 and D12 with a hook to the proxy keys;
   `logout_button` per D14; docstrings per D15. `_exchange_token` may switch to
   `self.client.oauth.exchange_code(..., client_secret=...)` with `persist=False` now that
   the default is safe, dropping the hand-rolled `httpx.post`; optional, same commit or not.
5. **`fastapi/dependencies.py`.** `ambient_credentials=False` in both `Client(...)` calls.
6. **Skill.** `api.md`: the `Client(...)` signature line gains `ambient_credentials=True`,
   `exchange_code` shows `persist=False`. `SKILL.md` "Authentication": a fourth bullet for
   servers that build their own per-user clients. `streamlit.md`: the proxy section
   (both headers, renewal in the session, the new keys under "Don't overwrite these"), and
   replace "The SDK skips its own token expiry checks in this mode".
7. **CHANGELOG** (section 5), version bump to 0.94.0, `plans/` gets this file.


## 4. Tests

All offline. The token file is `tmp_path` via step 1; `_do_token_refresh` is stubbed and
its calls counted; Streamlit's `st.session_state` and `st.context.headers` are patched on
the module (`pytest.importorskip("streamlit")`).

**Client**

- The reproduction from 1.1, inverted: an access-only client raises on expiry and never
  reads the file's refresh token; a bare client with `ambient_credentials=False` has
  `api_key is None` with a populated file present.
- Environment and instance never mix: `SWEATSTACK_REFRESH_TOKEN` set plus an explicit
  access token only raises on expiry.
- A refresh of an explicit pair creates no file; of an environment pair, no file; of a
  file-backed pair, rewrites the file. `authenticate(persist=True)` makes a client
  file-backed, and `persist=True` with ambient credentials off raises `ValueError`.
- `exchange_code` writes the file only with `persist=True`.
- A refresh response with a new `refresh_token` replaces the instance's, reaches the file
  when file-backed, and reaches the hook; one without keeps the old one.
- The hook is called once per refresh, inside the lock, with the pair in force; eight
  threads on one expired client produce one refresh and one hook call (extends the existing
  concurrency test).
- `_with_tokens` propagates `ambient_credentials` and never the hook. A delegated response
  with `refresh_token: null` yields a token-only client that raises on expiry and reads no
  file, with a populated file present.
- Resolution caches a hit and not a miss: a bare client that found nothing picks up an
  environment variable set later.
- The module-level default client is unaffected (ambient on).

**Streamlit**

- OAuth mode: `StreamlitAuth()` with no session tokens has `auth.client.api_key is None`
  and reads no file, with a populated file present and `SWEATSTACK_API_KEY` set. After login
  and expiry, three reruns produce one refresh and the session keys hold the renewed pair.
- Proxy mode, each case of D12: fresh header pair (no refresh, header token used); expired
  header token plus refresh header (one refresh across three reruns, proxy keys updated);
  reconnect with a newer header token and the same refresh token (header token used, no
  refresh); a different refresh token (stored pair replaced); no headers (pair cleared,
  unauthenticated); expired token and no refresh header (`SweatStackTokenRefreshError` with
  the reload message on first API use; nothing stored).
- `select_user()` in proxy mode leaves the proxy keys untouched and the next
  `behind_proxy()` still reports the same login.
- Logout clears both key pairs and leaves no file.
- The hook called from a non-script thread does not raise.

**FastAPI**

- A request-scoped client whose token expires refreshes without creating a file.

**Suite hygiene**

- `tests/test_public_hygiene.py` passes on this plan file and the CHANGELOG. The regression
  tests use `header.payload.signature` tokens, never real-looking JWTs.


## 5. Docs, skill and release

**CHANGELOG, 0.94.0.** Draft:

> ### Security
> - A `Client` in a process shared by several users (Streamlit, FastAPI, any server) could
>   pick up a refresh token, or a whole token pair, saved on that machine by another user's
>   client, and act as that user. Credentials now come from a single source: the arguments
>   you pass, else the environment, else the tokens saved by `authenticate()`. A client never
>   combines halves from different sources and writes the saved tokens only when they came
>   from there. The Streamlit and FastAPI integrations never read or write saved tokens.
>   Upgrading is recommended for every app that other people sign in to.
>
> ### Fixed
> - Streamlit apps behind a proxy no longer fail after the access token expires. With a
>   proxy that forwards `X-SweatStack-Refresh-Token`, the session renews its own token and
>   keeps the renewed pair across reruns. Streamlit apps in OAuth mode refresh once per
>   token lifetime instead of once per rerun.
> - A refresh response that carries a new refresh token replaces the old one.
>
> ### Changed
> - `Client(..., ambient_credentials=False)` builds a client that never reads the
>   environment or the saved tokens and never writes them. Use it for per-user clients in
>   your own server.
> - `oauth.exchange_code()` no longer saves the tokens to the machine by default; pass
>   `persist=True` for that. `authenticate()` still saves them.
>
> ### Upgrading
>
> | 0.93 | 0.94 |
> |---|---|
> | `Client(api_key=...)` without a refresh token used `SWEATSTACK_REFRESH_TOKEN` or the saved refresh token to renew | **Silent:** it never borrows one and raises `SweatStackTokenRefreshError` on expiry. Pass `refresh_token=` too, or pass neither to use the environment or the saved tokens |
> | `oauth.exchange_code(...)` saved the tokens to this machine | **Silent:** pass `persist=True` to keep that |
> | `StreamlitAuth.behind_proxy()` sent the handshake token as-is after expiry (a 401 from the API) | Forward `X-SweatStack-Refresh-Token` from the proxy and the session renews itself. Without it, calls after expiry raise `SweatStackTokenRefreshError` with a reload hint |

Wrap the table in `<!-- --8<-- [start:upgrading-0-94] -->` / `[end:...]` and add `## 0.94`
with the include to the docs' Upgrading page. No migration prompt: nothing here is bigger
than a rename or two, and `UPGRADING.md`'s generic prompt covers it.

**Docs site.** Authentication page: a "Using the client in a server" section (build per-user
clients from explicit tokens with `ambient_credentials=False`; never use the module-level
functions or the saved tokens on a server). Streamlit page: the proxy header contract, that
`behind_proxy()` must run at the top of every rerun, and that `auth` and `auth.client` must
not be cached across sessions (`st.cache_resource`, module globals).

**Downstream.** The Streamlit template already forwards the refresh token as
`X-SweatStack-Refresh-Token` (on by default, `FORWARD_REFRESH_TOKEN=false` turns it off) and
drops client-supplied `X-SweatStack-*` headers, so D11 holds against it as shipped. It should
raise its minimum `sweatstack` to 0.94.0, and its "Tokens in your app" section becomes "the
library renews in the session; the header is the handshake snapshot".

**Disclosure.** After release, a GitHub security advisory on this repository for 1.1:
affected `< 0.94.0`, fixed `0.94.0`, scope "multi-user processes using `Client` with partial
credentials or no credentials". Keep it as factual as the CHANGELOG entry.


## 6. Risks and edge cases

- **A notebook client created before `load_dotenv()`** keeps working because a miss is not
  cached (D5). A client that resolved the environment and then sees the environment change
  does not follow it; that is the same as today's instance behaviour and is documented.
- **`enforceSerializableSessionState`.** The session keys hold strings only, so Streamlit's
  optional serialisability check never sees a `Client`.
- **Thread pools in Streamlit apps.** Covered by D9's try/except in the hook; the refresh
  itself is already serialised by the lock.
- **Rotation.** Handled in the client (D6); the proxy mode's dependency on no rotation is
  stated where it matters (D15).
- **Local development.** A developer's own `SWEATSTACK_API_KEY` in the shell no longer leaks
  into a Streamlit session on their machine; D3 is what makes that true, not D1.


## 7. Questions from the drafts, resolved

- *Flag name:* `ambient_credentials` (D3). *Pluggable store:* no, one implementation.
- *Warn when a bare `Client()` falls back to the file inside a server?* No. Detection is
  guesswork; the integrations pass the flag and the docs tell app authors to.
- *Where does proxy-mode state live?* Its own two session keys (D10), so delegation and the
  user's own pair never collide.
- *Raise in `behind_proxy()` when the header token is expired and there is no refresh
  header?* No. Build the client with the expiry check on and let the first API use raise the
  actionable error (D12, case 2): an app that renders without calling the API should still
  render.


## 8. Out of scope, noted

- `select_user()` makes three API calls on every rerun (principal token, user list,
  delegated token). Worth caching per session; unrelated to expiry.
- `_exchange_token` in `streamlit.py` duplicates `oauth.exchange_code`; step 4 may fold it
  in, but it is not part of the fix.
- Encrypting or locking the token file on shared laptops.
