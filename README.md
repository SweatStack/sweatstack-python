# SweatStack Python client library


# Quickstart

```
uv pip install sweatstack
```

```python
import sweatstack as ss

ss.login()

ss.list_activities()
```


# Authentication

SweatStack supports three authentication methods:

### 1. Browser-Based OAuth2 Authentication
```python
ss.login()  # Opens your default browser for authentication
```

### 2. Direct API Key Authentication
```python
client = ss.Client(api_key="your-api-key")
```

### 3. Environment Variable
Set the `SWEATSTACK_API_KEY` environment variable:
```bash
export SWEATSTACK_API_KEY="your-api-key"
```

SweatStack follows this priority order:

1. Browser-based OAuth2 (`ss.login()`)
2. Direct API key via `Client` constructor
3. `SWEATSTACK_API_KEY` environment variable

For example, calling `ss.login()` or `client.login()` will override any existing API key authentication, including those set through the constructor or environment variables.


## Interfaces: Singleton vs Class-based

This library provides both a singleton interface and a class-based interface.

Singleton interface:
```python
import sweatstack as ss

activities = ss.list_activities()
```

Class-based interface:
```python
from sweatstack import Client

client = Client()
activities = client.list_activities()
```

Although both interfaces are feature-equivalent, they serve different purposes:
- The singleton interface is the default and recommended interface. It is intended for most use cases and is the easiest to use.
- The class-based interface is intended for more advanced use cases, such as when you need to authenticate multiple users at the same time or in multi-threaded applications.


## Streamlit integration

The `sweatstack.streamlit` module provides a Streamlit integration for SweatStack. This requires the optional `streamlit` dependency that can be installed with:
```
uv pip install 'sweatstack[streamlit]'
```

The `StreamlitAuth` class is a Streamlit component that handles the OAuth2 authentication flow. It provides a `st.authenticate()` function that can be used to authenticate the user.

Example usage:

```python
from sweatstack.streamlit import StreamlitAuth

auth = StreamlitAuth()

with st.sidebar:
    st.authenticate()

if not auth.is_authenticated():
    st.write("User is not authenticated")
    st.stop()

st.write("User is authenticated")

auth.client.get_latest_activity()
```