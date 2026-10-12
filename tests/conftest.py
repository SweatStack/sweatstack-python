"""Suite-wide isolation from the developer's machine.

Every test runs with the token file redirected to a temporary directory and without the
``SWEATSTACK_*`` credential variables, so a client built without credentials finds none, and
a test that writes the file never touches the real one.
"""

import pytest

from sweatstack.client import Client

CREDENTIAL_VARIABLES = (
    "SWEATSTACK_API_KEY",
    "SWEATSTACK_REFRESH_TOKEN",
    "SWEATSTACK_CLIENT_ID",
    "SWEATSTACK_CLIENT_SECRET",
)


@pytest.fixture(autouse=True)
def isolated_credentials(tmp_path, monkeypatch):
    """No ambient credentials unless a test provides them."""
    monkeypatch.setattr(Client, "_get_token_file_path", lambda self: tmp_path / "tokens.json")
    for name in CREDENTIAL_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "tokens.json"
