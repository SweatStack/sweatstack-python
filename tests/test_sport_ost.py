"""Tests for the OpenSportTaxonomy (OST) sport type.

``sweatstack.Sport`` is ``open_sport_taxonomy.Sport``. Response models consume sport via OST's
permissive ``SportField``; requests serialise a ``Sport`` to its canonical string; ``get_sports``
parses inbound values. These tests pin that wiring (not the OST library itself).
"""

import open_sport_taxonomy as ost
import pandas as pd

import sweatstack
from sweatstack import Modifier, Sport
from sweatstack.client import Client
from sweatstack.openapi_schemas import (
    TestCreate as SportCreateModel,  # aliased: avoid pytest "Test*" collection
)


def test_public_sport_types_are_ost():
    assert Sport is ost.Sport
    assert Modifier is ost.Modifier
    for name in ("Sport", "Modifier"):
        assert name in sweatstack.__all__
    # StandardSport is a niche typing aid, intentionally not re-exported from sweatstack.
    assert "StandardSport" not in sweatstack.__all__


def test_response_models_bind_sport_to_ost_field():
    # Guards the codegen substitution (cli._bind_sport_to_ost): sport fields are OST-typed, not `str`.
    assert SportCreateModel.model_fields["sport"].annotation is ost.Sport


def test_response_model_parses_ost_sport():
    model = SportCreateModel.model_validate({"sport": "cycling.road+virtual", "start": "2026-01-01T00:00:00+00:00"})
    assert isinstance(model.sport, Sport)
    assert model.sport == Sport("cycling.road+virtual")
    assert model.sport.code == "cycling.road"
    assert Modifier.VIRTUAL in model.sport.modifiers
    assert model.model_dump()["sport"] == "cycling.road+virtual"


def test_response_model_tolerates_sport_newer_than_bundled_taxonomy():
    # SportField is permissive: an unknown future sport is preserved, not rejected.
    model = SportCreateModel.model_validate({"sport": "kitesurfing", "start": "2026-01-01T00:00:00+00:00"})
    assert str(model.sport) == "kitesurfing"
    assert model.sport.is_standard is False


def test_enums_to_strings_serialises_sport_to_canonical_string():
    client = Client.__new__(Client)
    assert client._enums_to_strings([Sport("cycling+stationary"), Sport("running")]) == \
        ["cycling+stationary", "running"]


def test_enums_to_strings_leaves_other_enums_and_strings_untouched():
    from sweatstack import Metric
    client = Client.__new__(Client)
    assert client._enums_to_strings([Metric.power, "running"]) == ["power", "running"]


def test_get_sports_parses_payload_to_ost_sports():
    from unittest.mock import MagicMock, patch
    client = Client.__new__(Client)
    client.url = "https://test.sweatstack.no"
    client._access_token = None
    client.skip_token_expiry_check = True

    mock_response = MagicMock()
    mock_response.json.return_value = ["cycling.road", "cycling+stationary", "kitesurfing"]
    mock_http = MagicMock()
    mock_http.__enter__ = MagicMock(return_value=mock_http)
    mock_http.__exit__ = MagicMock(return_value=False)
    mock_http.get.return_value = mock_response

    with patch.object(client, "_http_client", return_value=mock_http), \
         patch.object(client, "_raise_for_status"):
        sports = client.get_sports()

    assert sports == [Sport("cycling.road"), Sport("cycling+stationary"), Sport.parse("kitesurfing")]
    assert all(isinstance(s, Sport) for s in sports)


def test_model_dump_dataframe_sport_column_is_canonical_string():
    # DataFrames built from model_dump() carry the canonical OST string, not a Sport object.
    rows = [
        SportCreateModel.model_validate({"sport": "cycling+stationary", "start": "2026-01-01T00:00:00+00:00"}).model_dump(),
        SportCreateModel.model_validate({"sport": "running", "start": "2026-01-02T00:00:00+00:00"}).model_dump(),
    ]
    df = pd.DataFrame(rows)
    assert df["sport"].tolist() == ["cycling+stationary", "running"]
