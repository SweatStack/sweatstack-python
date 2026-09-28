# Streamlit Integration

Requires: `pip install sweatstack[streamlit]`

## Contents

- [Direct OAuth Mode](#direct-oauth-mode)
- [Selector Components](#selector-components)
- [Behind-Proxy Mode](#behind-proxy-mode)
- [Gotchas](#gotchas)

---

## Direct OAuth Mode

Standard setup for Streamlit apps that handle their own authentication.

```python
import streamlit as st
from sweatstack.streamlit import StreamlitAuth

auth = StreamlitAuth(
    client_id="YOUR_CLIENT_ID",        # or SWEATSTACK_CLIENT_ID env var
    client_secret="YOUR_CLIENT_SECRET", # or SWEATSTACK_CLIENT_SECRET env var
    redirect_uri="http://localhost:8501", # or SWEATSTACK_REDIRECT_URI env var
)

with st.sidebar:
    auth.authenticate()  # Shows login/logout button

if not auth.is_authenticated():
    st.stop()

# Use auth.client for all API calls
activities = auth.client.get_activities(limit=10)
st.dataframe(auth.client.get_activities(output="pandas"))  # st.dataframe also accepts output="polars"
```

**`authenticate(login_label=None, show_logout=True)`** — renders login button if unauthenticated, logout button if authenticated. Handles OAuth callback automatically via `st.query_params`.

**`is_authenticated() -> bool`** — checks if a valid token exists in session state.

**`logout_button()`** — renders standalone logout button (use when `show_logout=False` in `authenticate()`).

### Environment Variables

| Variable | Purpose |
|---|---|
| `SWEATSTACK_CLIENT_ID` | OAuth client ID |
| `SWEATSTACK_CLIENT_SECRET` | OAuth client secret |
| `SWEATSTACK_REDIRECT_URI` | OAuth callback URI |
| `SWEATSTACK_SCOPES` | Comma-separated scopes (default: `data:read,profile`) |

## Selector Components

Built-in Streamlit widgets for common selection patterns. All return the selected value(s).

```python
# Activity selector — dropdown formatted as "YYYY-MM-DD sport_name"
activity = auth.select_activity(
    start=date(2025, 1, 1),       # optional
    sports=[Sport.cycling],       # optional
    tags=["race"],                # optional
    limit=100,                    # optional
)
data = auth.client.get_activity_data(activity.id)

# Sport selector
sport = auth.select_sport()                          # single select
sports = auth.select_sport(allow_multiple=True)      # multiselect
sport = auth.select_sport(only_root=True)            # top-level only
sport = auth.select_sport(only_available=False)      # all enum values, not just user's data

# Tag selector
tag = auth.select_tag()
tags = auth.select_tag(allow_multiple=True)

# Metric selector
metric = auth.select_metric()
metrics = auth.select_metric(allow_multiple=True)

# User selector (for admin/delegation)
user = auth.select_user()  # Switches client to selected user automatically
user = auth.select_user(team_id="team_abc")  # via team membership
```

## Behind-Proxy Mode

For Streamlit apps running behind an authentication proxy (e.g., the SweatStack Streamlit template proxy). The proxy handles OAuth and passes the access token via HTTP header.

```python
auth = StreamlitAuth.behind_proxy(
    redirect_uri=f"{APP_URL}/auth/callback",
    header_name="X-SweatStack-Token",  # default
    logout_uri="/logout",              # default, proxy handles this
    login_uri="/login",                # default, proxy handles this
)
auth.authenticate(show_logout=False)

if not auth.is_authenticated():
    st.stop()

auth.logout_button()  # Renders link to proxy's logout endpoint
activities = auth.client.get_activities()
```

**Key difference:** The proxy manages token lifecycle (refresh, storage). The SDK skips its own token expiry checks in this mode.

**Login/logout buttons** in proxy mode render as styled links (not Streamlit buttons) that navigate to the proxy's endpoints. On iOS standalone PWAs, they open in real Safari via `target="_blank"`.

## Gotchas

- **Always use `auth.client`** for API calls — never create a standalone `Client()` in a Streamlit app. The standalone client won't have the session's tokens.
- **Session state keys:** `sweatstack_api_key`, `sweatstack_refresh_token`. Don't overwrite these.
- **`select_user()` switches the client.** After calling it, `auth.client` operates as the selected user. Call `auth.switch_to_principal_user()` to revert.
- **Scopes default to `data:read,profile`** in Streamlit — not the broader set used by `Client.authenticate()`. Add `offline_access` if you need refresh tokens in direct OAuth mode.
