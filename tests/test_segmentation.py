"""AISC (Adaptive Intensity Segmentation Codec) parameters are sent on the wire.

Guards the `segmentation_on` / `segmentation` query-param contract (renamed from `nlec_on` / `nlec`
in 0.87.0) and the clean break — the old names must no longer be accepted.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from sweatstack.client import Client


@pytest.fixture
def client():
    c = Client.__new__(Client)
    c.url = "https://test.sweatstack.no"
    c._access_token = None
    c.streamlit_compatible = False
    c.skip_token_expiry_check = True
    return c


def _params_sent(client, call):
    """Run `call`, mocking out HTTP + parquet, and return the query params sent to the server."""
    response = MagicMock(status_code=200, content=b"")
    http = MagicMock()
    http.__enter__ = MagicMock(return_value=http)
    http.__exit__ = MagicMock(return_value=False)
    http.get.return_value = response

    with (
        patch.object(client, "_http_client", return_value=http),
        patch.object(client, "_raise_for_status"),
        patch.object(client, "_cache_enabled", return_value=False),
        patch.object(client, "_read_frame", return_value=pd.DataFrame()),
    ):
        call()
    return http.get.call_args.kwargs["params"]


def test_get_activity_data_sends_segmentation_on(client):
    params = _params_sent(client, lambda: client.get_activity_data("a", segmentation_on="power"))
    assert params["segmentation_on"] == "power"


def test_get_activity_data_omits_segmentation_when_unset(client):
    params = _params_sent(client, lambda: client.get_activity_data("a"))
    assert "segmentation_on" not in params


def test_get_longitudinal_data_sends_segmentation_on(client):
    params = _params_sent(
        client,
        lambda: client.get_longitudinal_data(
            sports=["running"], start="2024-01-01", segmentation_on="power"
        ),
    )
    assert params["segmentation_on"] == "power"


def test_get_activity_mean_max_sends_durations(client):
    assert "durations" not in _params_sent(
        client, lambda: client.get_activity_mean_max("a", "power")
    )
    params = _params_sent(
        client, lambda: client.get_activity_mean_max("a", "power", durations=[300, 5])
    )
    assert params["durations"] == "300,5"
    params = _params_sent(
        client, lambda: client.get_activity_mean_max("a", "power", durations="all")
    )
    assert params["durations"] == "all"


def test_mean_max_segmentation_is_removed(client):
    # `segmentation` never reduced the payload and is gone. A positional True
    # in its old slot must fail loudly, not be read as durations.
    with pytest.raises(TypeError):
        client.get_activity_mean_max("a", "power", True)
    with pytest.raises(TypeError):
        client.get_activity_mean_max("a", "power", segmentation=True)


def test_old_nlec_kwargs_are_rejected(client):
    # Clean break: the pre-0.87.0 names must raise, not silently no-op.
    with pytest.raises(TypeError):
        client.get_activity_data("a", nlec_on="power")
    with pytest.raises(TypeError):
        client.get_activity_mean_max("a", "power", nlec=True)
