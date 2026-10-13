from importlib.metadata import PackageNotFoundError, version

DEFAULT_URL = "https://app.sweatstack.no"

try:
    __version__ = version("sweatstack")
except PackageNotFoundError:
    __version__ = "unknown"

# What every request the SDK makes says it is, from the connection pool and from the token
# calls the integrations make outside it (``_transport.post``). One definition, so the server
# sees one SDK at one version wherever a request comes from.
USER_AGENT = f"python-sweatstack/{__version__}"

# The scopes the quickstart asks for: sign in, see the name and email, read activities, keep
# access. One constant for every entry point that carries a default, so they cannot drift.
# Wellness, reproductive health, writes and sharing are choices to type. Declared ``str`` so
# that ``DEFAULT_SCOPE.split()`` is a ``list[str]`` and not a ``list[LiteralString]``.
DEFAULT_SCOPE: str = "openid profile email activities:read offline_access"
