DEFAULT_URL = "https://app.sweatstack.no"

# The scopes the quickstart asks for: sign in, see the name and email, read activities, keep
# access. One constant for every entry point that carries a default, so they cannot drift.
# Wellness, reproductive health, writes and sharing are choices to type. Declared ``str`` so
# that ``DEFAULT_SCOPE.split()`` is a ``list[str]`` and not a ``list[LiteralString]``.
DEFAULT_SCOPE: str = "openid profile email activities:read offline_access"
