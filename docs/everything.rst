Complete API Reference
======================

Environment Variables
=====================

The SweatStack client library uses environment variables for configuration.
These variables provide defaults for authentication, caching, and Streamlit integration.

Authentication
--------------

.. envvar:: SWEATSTACK_API_KEY

   API access token for authenticating with SweatStack.

   Automatically loaded by the Client if not provided during initialization.
   Falls back to persistent storage if not found in environment.

   Example::

      export SWEATSTACK_API_KEY="your_token_here"

.. envvar:: SWEATSTACK_REFRESH_TOKEN

   Refresh token used for automatic token renewal.

   Loaded from environment, instance, or persistent storage. Used by the Client
   to automatically refresh expired access tokens.

.. envvar:: SWEATSTACK_URL

   Custom SweatStack instance URL.

   Override the default SweatStack API URL. Useful for testing or
   connecting to self-hosted instances.

   Default: ``https://app.sweatstack.no``

Caching
-------

.. envvar:: SWEATSTACK_LOCAL_CACHE

   Enable local filesystem caching of API responses.

   Set to any truthy value (``1``, ``true``, ``yes``) to enable caching
   of longitudinal data requests. Cached data persists across sessions.
   Use ``client.clear_cache()`` to remove cached data.

   Default: Disabled

   Example::

      export SWEATSTACK_LOCAL_CACHE=1

.. envvar:: SWEATSTACK_CACHE_DIR

   Custom directory location for cached data.

   Specify where to store cached API responses. If not set, defaults to
   the system temp directory with a ``sweatstack/{user_id}`` subdirectory.

   Default: System temp directory (e.g., ``/tmp/sweatstack/{user_id}``)

   Example::

      export SWEATSTACK_CACHE_DIR=/path/to/cache

Streamlit OAuth2
----------------

These environment variables are used by :class:`sweatstack.streamlit.StreamlitAuth`
for OAuth2 authentication in Streamlit applications.

.. envvar:: SWEATSTACK_CLIENT_ID

   OAuth2 application client ID.

   The client ID from your registered SweatStack OAuth2 application.
   Required for Streamlit authentication if not provided to StreamlitAuth.

.. envvar:: SWEATSTACK_CLIENT_SECRET

   OAuth2 application client secret.

   The client secret from your registered SweatStack OAuth2 application.
   Required for Streamlit authentication if not provided to StreamlitAuth.

.. envvar:: SWEATSTACK_SCOPES

   Comma-separated list of OAuth2 scopes.

   Specify which permissions to request during OAuth2 authorization.

   Default: ``data:read,profile``

   Example::

      export SWEATSTACK_SCOPES="data:read,data:write,profile"

.. envvar:: SWEATSTACK_REDIRECT_URI

   OAuth2 redirect URI.

   The URI where users are redirected after OAuth2 authorization.
   Must match a redirect URI registered in your OAuth2 application.

   Example::

      export SWEATSTACK_REDIRECT_URI="http://localhost:8501"

Modules
=======

sweatstack
----------

.. automodule:: sweatstack
    :members:
    :undoc-members:
    :show-inheritance:

sweatstack.client
-----------------

.. automodule:: sweatstack.client
    :members:
    :undoc-members:
    :inherited-members:
    :show-inheritance:
    :exclude-members: _LocalCacheMixin, _TokenStorageMixin, _OAuth2Mixin, _DelegationMixin


sweatstack.streamlit
--------------------

.. automodule:: sweatstack.streamlit
    :members:
    :undoc-members:
    :show-inheritance:

sweatstack.schemas
------------------

.. automodule:: sweatstack.schemas
    :members:
    :undoc-members:
    :show-inheritance:

Sport
~~~~~

.. autoclass:: sweatstack.schemas.Sport
    :members: root_sport, parent_sport, is_sub_sport_of, is_root_sport, display_name
    :undoc-members:

Metric
~~~~~~

.. autoclass:: sweatstack.schemas.Metric
    :members: display_name
    :undoc-members:

sweatstack.openapi_schemas
--------------------------

Core Data Models
~~~~~~~~~~~~~~~~

.. autoclass:: sweatstack.openapi_schemas.ActivitySummary
    :members:
    :undoc-members:
    :show-inheritance:

.. autoclass:: sweatstack.openapi_schemas.ActivityDetails
    :members:
    :undoc-members:
    :show-inheritance:

.. autoclass:: sweatstack.openapi_schemas.TraceDetails
    :members:
    :undoc-members:
    :show-inheritance:

.. autoclass:: sweatstack.openapi_schemas.Lap
    :members:
    :undoc-members:
    :show-inheritance:

Activity Summaries
~~~~~~~~~~~~~~~~~~

.. autoclass:: sweatstack.openapi_schemas.ActivitySummarySummary
    :members:
    :undoc-members:
    :show-inheritance:

.. autoclass:: sweatstack.openapi_schemas.PowerSummary
    :members:
    :undoc-members:
    :show-inheritance:

.. autoclass:: sweatstack.openapi_schemas.SpeedSummary
    :members:
    :undoc-members:
    :show-inheritance:

.. autoclass:: sweatstack.openapi_schemas.DistanceSummary
    :members:
    :undoc-members:
    :show-inheritance:

.. autoclass:: sweatstack.openapi_schemas.ElevationSummary
    :members:
    :undoc-members:
    :show-inheritance:

.. autoclass:: sweatstack.openapi_schemas.HeartRateSummary
    :members:
    :undoc-members:
    :show-inheritance:

.. autoclass:: sweatstack.openapi_schemas.TemperatureSummary
    :members:
    :undoc-members:
    :show-inheritance:

.. autoclass:: sweatstack.openapi_schemas.CoreTemperatureSummary
    :members:
    :undoc-members:
    :show-inheritance:

.. autoclass:: sweatstack.openapi_schemas.Smo2Summary
    :members:
    :undoc-members:
    :show-inheritance:

User & Authentication
~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: sweatstack.openapi_schemas.UserSummary
    :members:
    :undoc-members:
    :show-inheritance:

.. autoclass:: sweatstack.openapi_schemas.UserInfoResponse
    :members:
    :undoc-members:
    :show-inheritance:

.. autoclass:: sweatstack.openapi_schemas.TokenResponse
    :members:
    :undoc-members:
    :show-inheritance:

.. autoclass:: sweatstack.openapi_schemas.BackfillStatus
    :members:
    :undoc-members:
    :show-inheritance:
