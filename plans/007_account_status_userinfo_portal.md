# Plan: account status, `userinfo.issue`, and Portal sessions

Mirror three server surfaces that the SDK does not expose yet:

| Server | Python |
|---|---|
| `GET /api/v1/profile/status` | `client.get_profile_status()` (new) |
| `GET /api/v1/oauth/userinfo` now carries `issue` | `client.get_userinfo().issue` (regen; method unchanged) |
| `POST /api/v1/portal/sessions` | `client.create_portal_session(destination, *, return_url=None)` (new) |

Plus one bug found on the way: `whoami()` calls a helper that does not exist.

Proposed 2026-09-28. **Implemented 2026-09-28** on branch `output-backends` (regen chore, feature, docs), suite green. Sources: server `app/routers/api.py`,
`app/schemas.py`, `app/constants.py`, `app/logic/__init__.py`
(`create_portal_session`, `get_account_status_response`); server plans 016,
021, 045, 052; docs `learn/data/no-data.md`, `learn/portal/index.md`,
`learn/authentication/oauth2.md` §6. All three surfaces are marked **beta**
in the public docs; the SDK docstrings and CHANGELOG say so too.


## What the server offers (verified)

**`userinfo`** gained one nullable claim, `issue`: `{code, status, message,
action_url}`. At most one issue, ranked server-side, filtered by the
calling app's scopes, naming no provider. Requires `profile`. On a
delegated token `action_url` is always `null`. `name` is a computed field
and stays required.

**`GET /api/v1/profile/status`** returns `{issue, capabilities}`.
`capabilities` is a map `Capability -> CapabilityStatus` with keys
`activities`, `activity_history`, `dailies`, `workouts` and values
`ready | syncing | action_required | unavailable`. Accepts `data:read` or
`profile`. Contract from the docs: `status` (four values) is the stable
branch; `code` and the capability keys are **open sets**, apps must ignore
unknown ones; `message` is display-only.

**`POST /api/v1/portal/sessions`** is server-to-server with **no user
token**: the app authenticates with `client_id` and (only if it has one
registered) `client_secret` in the body, and gets `{url}`. `destination` is
`manage-integrations` or `manage-teams` (the generated client file only
knows the latter: it predates the endpoint's current shape).
`return_url` is optional, validated against the app's registered redirect
URIs (400 on mismatch), and omitting it is meaningful (the Portal then
says "close this page"). 401 on bad credentials. The returned URL is
opaque by contract: never build one by hand.

**Client SDK today.** `get_userinfo()` exists and returns
`UserInfoResponse` without `issue`. `get_backfill_status()` /
`watch_backfill_status()` cover the activities backfill stream and are
unrelated to the new status endpoint. `PortalSessionRequest` exists in the
generated file with `client_secret` required and one destination.
`whoami()` calls `self._get_user_by_id`, which is not defined anywhere: it
raises `AttributeError` for every caller (mypy flags it; no test covers
it).


## Decisions

1. **Names mirror paths, per AGENTS.md.** `GET /profile/status` ->
   `get_profile_status()`, `POST /portal/sessions` ->
   `create_portal_session()`. The response model keeps the server's name
   (`AccountStatusResponse`); the method follows the URL, which is the rule
   everywhere else in `client.py`. Flip to `get_account_status` only if
   the URL is renamed server-side.
2. **Open enums stay open in Python.** `StatusIssueCode` and `Capability`
   get the `_missing_` pseudo-member treatment `schemas.py` already applies
   to `Metric`, `Scope` and `DailyMeasure`, so a code or capability the
   server adds tomorrow parses today. `CapabilityStatus` and
   `PortalDestination` stay strict: the docs promise the former will never
   grow, and a destination the SDK does not know cannot be a page the
   client should send users to.
3. **`create_portal_session` uses the client's own app credentials and
   never a user token.** It reads `self.client_id` and
   `self._client_secret`, sends `client_secret` only when one is
   configured (a public client authenticates with `client_id` alone), and
   goes through `_http_client(auth=False)`, a new keyword that sends no
   `Authorization` header and never touches token storage or refresh
   (`skip_token_check=True` still attaches a raw token when one is set,
   which is not "no user token"). A bare `Client(client_id=...,
   client_secret=...)` therefore mints with zero token activity, and a
   user-bearing client never leaks its bearer to a server-to-server
   endpoint. The FastAPI dependencies and
   `StreamlitAuth` already construct their `Client` with the app's
   `client_id`/`client_secret`, so `user.client.create_portal_session(...)`
   and `auth.client.create_portal_session(...)` work with no new helper.
   With the default `client_id` (the SDK's own public client) minting also
   works, branded as the Python client; the docstring says so.
4. **Return validated models, not strings.** `create_portal_session`
   returns `PortalSessionResponse` (`.url`), matching the "never the raw
   dict" rule. `get_profile_status` returns `AccountStatusResponse`.
5. **No convenience composites.** No `has_issue()`, no "open the Portal
   for me". The docs' one-line integration is already one line in Python:
   `if user.issue: banner(user.issue.message, user.issue.action_url)`.
6. **Fix `whoami()` in the same change**, as `get_user(sub,
   search_mode="id")`, with a test. Verified constraints that rule out the
   alternatives: `GET /users/{id}` is the *managed*-user route (`profile`
   scope, no delegated tokens), and `GET /users/` lists accessible users
   including self but rejects delegated tokens. `get_user` already goes
   through `principal_client()` and so works for both a principal and a
   delegated client, at the cost of one extra token round trip, which is
   fine for a method nobody calls in a loop. This also keeps the 0.x
   promise that `whoami()` needs no `profile` scope. The skill reference's
   "from JWT, no API call" claim was never true; correct it.
7. **These methods always return models and never take `output`.** The
   `output=` contract (plan 006) covers *data you analyse*: activities,
   traces, tests, dailies and the time-series endpoints. Everything about
   the account, the app, teams, status and the Portal is control plane:
   single records or short lists that are read field by field, never
   grouped or plotted. Those methods have no `output` parameter and are
   structurally unaffected by `Client(output=...)` and `set_output()`,
   because resolution only happens inside `_read_frame` and
   `_frame_from_models`. `get_userinfo`, `get_profile_status`,
   `create_portal_session`, `whoami`, `get_users`, `get_teams`,
   `get_team_users`, `get_sports` and `get_tags` all sit on this side of
   the line. Codify the line in AGENTS.md, the `set_output` and
   `Client(output=)` docstrings and the skill reference, so the next data
   endpoint gets `output` and the next control-plane endpoint does not.
   If a control-plane list ever needs a frame (a coach's 40 athletes), add
   `output` to that one method: additive, and the rule stays.
8. **Errors map through the existing hierarchy.** 401 on minting ->
   `SweatStackAuthError`, 400 (bad `return_url`, non-application id) ->
   `SweatStackBadRequestError`, 403 on status (missing scope) ->
   `SweatStackAuthError`. Delegated tokens are *allowed* on both status
   and `userinfo`; they simply get `action_url=None`. The server's
   "delegated token gets a 404" applies to the Portal *page*, not to any
   endpoint the SDK calls, so there is nothing to map. Docstrings name
   the three above.


## Syntax

```python
# The one-line integration from the docs
user = client.get_userinfo()
if user.issue:
    banner(user.issue.message, user.issue.action_url)   # action_url is None on delegated tokens

# Apps with a specific requirement
status = client.get_profile_status()
if status.capabilities.get(Capability.activity_history) != CapabilityStatus.ready:
    ...
if status.issue and status.issue.status == CapabilityStatus.action_required and status.issue.action_url:
    show_button(status.issue.action_url)

# Mint a Portal link with the app's own credentials (no user token involved)
app = Client(client_id="01JMYRA...", client_secret="...")      # secret only if the app has one
session = app.create_portal_session("manage-integrations", return_url="https://example.com/app/")
redirect(session.url)

# From a FastAPI dependency or StreamlitAuth, the client already carries the app credentials
url = user.client.create_portal_session(PortalDestination.manage_integrations).url
```


## Steps

1. **Regenerate `openapi_schemas.py`** against a current server (per
   DEVELOPMENT.md; needs the backend running locally). Expected diff:
   `UserInfoResponse.issue`, new `StatusIssueResponse`,
   `AccountStatusResponse`, `Capability`, `CapabilityStatus`,
   `StatusIssueCode`; `PortalDestination` gains `manage_integrations`;
   `PortalSessionRequest.client_secret` becomes optional. Land unrelated
   drift as its own `chore: regenerate openapi schemas` commit first.
2. **Re-export and open the enums** in `schemas.py`: `AccountStatusResponse`,
   `StatusIssueResponse`, `Capability`, `CapabilityStatus`,
   `StatusIssueCode`, `PortalDestination`, `PortalSessionResponse`;
   `_missing_` on `StatusIssueCode` and `Capability`. Import them in
   `client.py` and add to `__all__` (the public-surface test will catch an
   omission).
3. **`get_profile_status()`** in `client.py`, next to `get_userinfo`.
   Method-shape template; `Raises:` per decision 8; docstring carries the
   contract in three lines (branch on `status`, display `message`, ignore
   unknown codes and keys) and the beta note.
4. **`get_userinfo()` docstring** gains the `issue` paragraph and the
   delegated-token note. No signature change.
5. **`_http_client(auth=False)`** (tiny, with a test), then
   **`create_portal_session(destination, *, return_url=None)`** per
   decision 3. `destination: PortalDestination | str` through
   `_enums_to_strings`; a string the enum does not know passes through
   unchanged, so a new server destination is reachable before the SDK
   learns it. Body built explicitly; `client_secret` key omitted when
   `None`.
6. **Fix `whoami()`.**
7. **Tests** (`tests/test_account_status.py`, `tests/test_portal.py`,
   addition to an identity test file), all offline:
   - Schema round-trips for `AccountStatusResponse`, `StatusIssueResponse`
     and the enriched `UserInfoResponse`, using the five payloads the
     public docs prescribe for mocking ("Nothing connected", "Still
     syncing", "History not shared", "Permanently limited", "All good")
     verbatim as fixtures, so the SDK tests are pinned to the documented
     contract rather than to our reading of it.
   - Open-enum tolerance: a payload with `"code": "something_new"` and a
     `capabilities` key the SDK does not know validates, and the unknown
     members round-trip through `.value`.
   - `get_profile_status` hits the right URL, maps 403 to
     `SweatStackAuthError`.
   - `create_portal_session`: request body has `client_id` and
     `destination`, includes `client_secret` only when configured, sends
     no `Authorization` header and no token load or refresh (assert on the
     request headers, not on how `_http_client` was called);
     `return_url` forwarded; 401 -> `SweatStackAuthError`, 400 ->
     `SweatStackBadRequestError`; string and enum destinations both
     serialise to the slug.
   - `whoami()` returns `get_user(sub, search_mode="id")`.
   - `tests/test_frames.py`'s regen guard runs over the new models
     automatically (they are re-exported from `schemas.py`); the
     `capabilities` map is `dict[Capability, CapabilityStatus]`, a
     free-form object in JSON Schema, so it lands as JSON text in a frame,
     which is right for a map keyed by an open enum. Add the explicit
     assertion so the choice is deliberate.
8. **Docs.** Skill `client.md`: a "Account status and the Portal" section
   with the four-status table condensed and the three snippets above;
   `data-models.md`: the new models and the open/closed enum note;
   `fastapi.md` and `streamlit.md`: one line each that `user.client` /
   `auth.client` can mint sessions. Correct the `whoami()` line in
   `client.md` (it makes an API call). CHANGELOG `### Added` under
   Unreleased, with the beta note. README stays lean: one bullet in the
   feature list, if one is added at all. The docs site (sweatstack.no)
   has no Python snippets for any of the three pages; proposing Python
   tabs there is a follow-up in that repo.


## Out of scope

- A FastAPI route or dependency that mints Portal sessions or renders the
  issue banner. Apps differ too much in where the banner goes; the docs'
  one-liner is the integration.
- Polling helpers or `watch_profile_status()`. The docs say not to poll
  `unavailable`, and `syncing` resolves within 24 hours; the backfill
  stream already exists for the one case where live progress matters.
- Any provider-specific field or helper. The server design exists to keep
  providers out of the contract.
- `get_backfill_status` changes. It answers a different question (how far
  the activities backfill has reached) and stays as is.
