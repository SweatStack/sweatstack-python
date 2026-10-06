"""Behaviour of the resource namespaces (``client.activities``, ``client.users``, ...).

The transport is faked at ``Client._request``, the one choke point every single-request method
goes through, so each test sees exactly what would go on the wire.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from sweatstack import Sport, UserSummary
from sweatstack.client import Client
from sweatstack.exceptions import SweatStackConnectionError


@pytest.fixture
def client():
    return Client(api_key="test-token", url="https://test.sweatstack.no")


def _response(body=None, content=b""):
    response = MagicMock()
    response.json.return_value = body
    response.content = content
    return response


def _user(user_id: str, name: str) -> dict:
    return UserSummary(
        id=user_id,
        first_name=name,
        last_name=None,
        scopes=[],
        display_name=name,
        is_managed=False,
    ).model_dump(mode="json")


class TestRepeatableParameters:
    """R8: a repeatable query parameter takes one value or a list, under its wire name."""

    @pytest.mark.parametrize(
        "sport, wire",
        [
            ("cycling", ["cycling"]),
            (Sport("cycling.road"), ["cycling.road"]),
            (["cycling", Sport("running")], ["cycling", "running"]),
            (("cycling",), ["cycling"]),
        ],
    )
    def test_sport_accepts_one_value_or_a_list(self, client, sport, wire):
        with patch.object(client, "_request", return_value=_response([])) as request:
            client.activities.list(sport=sport)
        assert request.call_args.kwargs["params"]["sport"] == wire

    def test_tags_and_metrics_accept_one_value(self, client):
        with patch.object(client, "_request", return_value=_response([])) as request:
            client.traces.list(tags="lactate")
        assert request.call_args.kwargs["params"]["tags"] == ["lactate"]
        with (
            patch.object(client, "_request", return_value=_response(content=b"")) as request,
            patch.object(client, "_read_frame"),
        ):
            client.activities.data("a", metrics="power")
        assert request.call_args.kwargs["params"]["metrics"] == ["power"]

    def test_the_old_sports_name_is_gone(self, client):
        with pytest.raises(TypeError):
            client.activities.list(sports=["cycling"])  # ty: ignore[unknown-argument]


class TestPagination:
    def test_limit_is_the_number_of_items_returned(self, client):
        pages = [[{"n": i} for i in range(100)], [{"n": i} for i in range(100, 150)]]
        with (
            patch.object(client, "_request", side_effect=[_response(p) for p in pages]) as request,
            patch(
                "sweatstack.resources.activities.ActivitySummary.model_validate",
                side_effect=lambda x: x,
            ),
            patch.object(client, "_frame_from_models", side_effect=lambda models, *a, **k: models),
        ):
            activities = client.activities.list(limit=150, offset=10)
        assert len(activities) == 150
        sent = [call.kwargs["params"] for call in request.call_args_list]
        assert [(p["limit"], p["offset"]) for p in sent] == [(100, 10), (50, 110)]

    def test_a_short_page_ends_the_listing(self, client):
        with (
            patch.object(client, "_request", return_value=_response([{"n": 1}])) as request,
            patch("sweatstack.resources.tests.TestSummary.model_validate", side_effect=lambda x: x),
            patch.object(client, "_frame_from_models", side_effect=lambda models, *a, **k: models),
        ):
            tests = client.tests.list(limit=500)
        assert tests == [{"n": 1}]
        assert request.call_count == 1
        assert request.call_args.kwargs["params"]["limit"] == 50  # the tests page size


class TestActivities:
    def test_latest_is_none_without_activities(self, client):
        with patch.object(client, "_request", return_value=_response(None)) as request:
            assert client.activities.latest(sport="cycling") is None
        assert request.call_args.args[1] == "/api/v1/activities/latest"
        assert request.call_args.kwargs["params"] == {"sport": "cycling"}

    def test_upload_returns_the_sources_and_closes_the_files(self, client, tmp_path):
        fit = tmp_path / "ride.fit"
        fit.write_bytes(b"fit")
        source = {
            "id": "src_1",
            "type": "fit",
            "origin": "manual_upload",
            "filename": "ride.fit",
            "status": "processing",
            "activity_ids": [],
            "created_at": "2026-05-01T09:00:00Z",
        }
        with patch.object(
            client, "_request", return_value=_response({"sources": [source]})
        ) as request:
            sources = client.activities.upload(fit)
        assert [s.id for s in sources] == ["src_1"]
        ((_, (name, handle)),) = request.call_args.kwargs["files"]
        assert name == "ride.fit" and handle.closed

    def test_watch_backfill_status_reconnects_after_a_dropped_connection(self, client):
        """Regression: auto_reconnect caught httpx errors the transport had already converted."""
        response = MagicMock()
        response.iter_lines.return_value = ['{"backfill_loaded_until": "2026-01-01T00:00:00Z"}']
        http = MagicMock()
        http.__enter__.return_value = http
        http.stream.return_value.__enter__.return_value = response
        dropped = SweatStackConnectionError("connection dropped")
        with (
            patch.object(client, "_http_client", side_effect=[dropped, dropped, http]),
            patch.object(client, "_raise_for_status"),
            patch("sweatstack.resources.activities.time.sleep") as sleep,
        ):
            status = next(client.activities.watch_backfill_status(auto_reconnect=True))
        assert status.backfill_loaded_until.year == 2026
        assert sleep.call_count == 2

    def test_backfill_status_accepts_the_servers_naive_timestamps(self, client, caplog):
        """Regression: the server sends no offset; every line failed validation and was skipped."""
        response = MagicMock()
        response.iter_lines.return_value = [
            "not json",
            '{"backfill_loaded_until": "2021-09-27T00:56:34.667483"}',
        ]
        http = MagicMock()
        http.__enter__.return_value = http
        http.stream.return_value.__enter__.return_value = response
        with (
            patch.object(client, "_http_client", return_value=http),
            patch.object(client, "_raise_for_status"),
        ):
            status = client.activities.backfill_status()
        assert status.backfill_loaded_until.year == 2021
        assert "Skipping a backfill status line" in caplog.text

    def test_watch_backfill_status_raises_without_auto_reconnect(self, client):
        with (
            patch.object(client, "_http_client", side_effect=SweatStackConnectionError("down")),
            pytest.raises(SweatStackConnectionError),
        ):
            next(client.activities.watch_backfill_status())

    def test_longitudinal_mean_max_requires_a_sport(self, client):
        with pytest.raises(TypeError):
            client.activities.longitudinal.mean_max(metric="power")  # ty: ignore[missing-argument]


class TestUsers:
    USERS = [_user("u1", "Anna Jansen"), _user("u2", "Carla Jansen"), _user("u3", "Carlos Bakker")]

    def _listed(self, client, **kwargs):
        principal = MagicMock()
        principal._request.return_value = _response(self.USERS)
        with patch.object(client, "principal_client", return_value=principal):
            users = client.users.list(**kwargs)
        return users, principal._request.call_args

    def test_list_runs_as_the_principal_and_sends_only_non_defaults(self, client):
        users, call = self._listed(client)
        assert [u.id for u in users] == ["u1", "u2", "u3"]
        assert call.kwargs["params"] == {}
        _, call = self._listed(client, include_shared=False)
        assert call.kwargs["params"] == {"include_shared": False}

    @pytest.mark.parametrize(
        "name, ids",
        [("carl", ["u2", "u3"]), ("CARLA", ["u2"]), ("jansen", ["u1", "u2"]), ("x", [])],
    )
    def test_name_matches_any_part_ignoring_case(self, client, name, ids):
        users, call = self._listed(client, name=name)
        assert [u.id for u in users] == ids
        assert call.kwargs["params"]["name"] == name  # also sent, for the server-side filter

    def test_team_users_filter_by_name_too(self, client):
        with patch.object(client, "_request", return_value=_response(self.USERS)) as request:
            users = client.teams.users("team_1", name="carla")
        assert [u.id for u in users] == ["u2"]
        assert request.call_args.kwargs["params"] == {"name": "carla"}

    def test_update_sends_only_the_fields_given(self, client):
        managed = {
            "id": "u9",
            "first_name": "Bob",
            "last_name": "Smit",
            "admin": False,
            "registered_at": "2026-01-01T00:00:00Z",
            "display_name": "Bob Smit",
            "is_managed": True,
        }
        with patch.object(client, "_request", return_value=_response(managed)) as request:
            client.users.update("u9", last_name="Smit")
        assert request.call_args.args == ("put", "/api/v1/users/u9")
        assert request.call_args.kwargs["data"] == {"last_name": "Smit"}


class TestStreamlitSelectUser:
    def test_the_session_keeps_the_delegated_users_own_refresh_token(self):
        """Regression: the athlete's access token was stored next to the coach's refresh token."""
        streamlit = pytest.importorskip("sweatstack.streamlit")
        auth = streamlit.StreamlitAuth.__new__(streamlit.StreamlitAuth)
        auth.client_id, auth.client_secret = "app_123", "app_secret"
        auth.client = MagicMock()
        principal = auth.client.principal_client.return_value
        principal.users.list.return_value = [
            UserSummary.model_validate(self_user) for self_user in TestUsers.USERS
        ]
        delegated = principal.delegated_client.return_value
        delegated.api_key, delegated.refresh_token = "athlete-access", "athlete-refresh"
        session = {}
        with (
            patch.object(streamlit.st, "session_state", session),
            patch.object(
                streamlit.st, "selectbox", side_effect=lambda label, options, **kw: options[1]
            ),
        ):
            selected = auth.select_user()
        assert selected.id == "u2"
        assert session == {
            "sweatstack_api_key": "athlete-access",
            "sweatstack_refresh_token": "athlete-refresh",
        }
        assert auth.client.client_id == "app_123"  # the app credentials survive the switch


def test_delegated_client_sends_the_user_id(client):
    tokens = _response({"access_token": "a", "refresh_token": "r"})
    user = UserSummary.model_validate(_user("u2", "Carla"))
    with patch.object(client, "_request", return_value=tokens) as request:
        client.delegated_client(user, team_id="team_1")
    assert request.call_args.kwargs["json"] == {"sub": "u2", "team_id": "team_1"}


def test_dailies_measure_is_the_path(client):
    with patch.object(client, "_request", return_value=_response([])) as request:
        client.dailies.list("body_mass", start=date(2026, 1, 1), end=date(2026, 1, 2))
    assert request.call_args.args == ("get", "/api/v1/dailies/body_mass")
