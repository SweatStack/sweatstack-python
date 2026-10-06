"""Tests for app metadata methods.

Verifies correct API path construction for each entity type.
"""

from unittest.mock import MagicMock, patch

import pytest

from sweatstack.client import Client


@pytest.fixture
def client():
    """Create a Client instance without authentication."""
    c = Client.__new__(Client)
    c.url = "https://test.sweatstack.no"
    c._access_token = None
    c.streamlit_compatible = False
    c.skip_token_expiry_check = True
    return c


class TestAppMetadataPathConstruction:
    """Verify each method hits the correct API path."""

    @pytest.mark.parametrize(
        "method,args,kwargs,expected_path",
        [
            (
                "set_activity_app_metadata",
                ("act_123",),
                {"data": {"key": "val"}},
                "/api/v1/activities/act_123/app-metadata",
            ),
            (
                "delete_activity_app_metadata",
                ("act_123",),
                {},
                "/api/v1/activities/act_123/app-metadata",
            ),
            (
                "set_trace_app_metadata",
                ("trace_123",),
                {"data": {"key": "val"}},
                "/api/v1/traces/trace_123/app-metadata",
            ),
            (
                "delete_trace_app_metadata",
                ("trace_123",),
                {},
                "/api/v1/traces/trace_123/app-metadata",
            ),
            (
                "set_test_app_metadata",
                ("test_123",),
                {"data": {"key": "val"}},
                "/api/v1/tests/test_123/app-metadata",
            ),
            ("delete_test_app_metadata", ("test_123",), {}, "/api/v1/tests/test_123/app-metadata"),
            ("set_user_app_metadata", (), {"data": {"key": "val"}}, "/api/v1/profile/app-metadata"),
            ("delete_user_app_metadata", (), {}, "/api/v1/profile/app-metadata"),
        ],
    )
    def test_path(self, client, method, args, kwargs, expected_path):
        """Each metadata method should construct the correct API path."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_http_client = MagicMock()
        mock_http_client.__enter__ = MagicMock(return_value=mock_http_client)
        mock_http_client.__exit__ = MagicMock(return_value=False)
        mock_http_client.put.return_value = mock_response
        mock_http_client.delete.return_value = mock_response

        with patch.object(client, "_http_client", return_value=mock_http_client):
            with patch.object(client, "_raise_for_status"):
                getattr(client, method)(*args, **kwargs)

        if "set_" in method:
            mock_http_client.put.assert_called_once()
            call_kwargs = mock_http_client.put.call_args
            assert call_kwargs.kwargs["url"] == expected_path
        else:
            mock_http_client.delete.assert_called_once()
            call_kwargs = mock_http_client.delete.call_args
            assert call_kwargs.kwargs["url"] == expected_path
