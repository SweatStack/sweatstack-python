"""SweatStack data schemas.

Re-exports the Pydantic response models from :mod:`openapi_schemas`, the public sport types from
OpenSportTaxonomy (``Sport`` and ``Modifier``), and extends the ``Metric``, ``Scope`` and
``DailyMeasure`` enums with convenience methods.

Sport values follow OpenSportTaxonomy: construct a known sport with ``Sport("cycling.road")`` and parse
external/API input with ``Sport.parse(value)``. See https://github.com/SweatStack/open-sport-taxonomy.

Example:
    from sweatstack import Sport
    sport = Sport("cycling.road")
    print(sport.label)                              # "road cycling"
    print(sport.parent)                             # Sport("cycling")
    print(sport.is_subsport_of(Sport("cycling")))   # True
"""
from open_sport_taxonomy import Modifier, Sport

from .openapi_schemas import (
    ActivityDetails, ActivitySummary, ApplicationMemberRole, AuthorizedTeamResponse,
    BackfillStatus, DailyMeasure, DailyResponse,
    Marker, Metric, Scope,
    TeamResponse, TestDetails, TestResults, TestSummary, TokenResponse, TraceDetails,
    TraceResolution, UserInfoResponse, UserResponse, UserSummary
)


def _metric_display_name(metric: Metric) -> str:
    """Returns a human-readable display name for a metric.

    This function converts a Metric enum value into a formatted string suitable for display.
    """
    return metric.value.replace("_", " ")


@classmethod
def _metric_missing(cls, value: str):
    """Handle unknown metric values from newer API versions.

    This allows the client to gracefully handle new metrics added to the API
    without requiring a client library update. Unknown values become dynamic
    enum members that behave like regular Metric values.
    """
    pseudo_member = object.__new__(cls)
    pseudo_member._name_ = value
    pseudo_member._value_ = value
    cls._value2member_map_[value] = pseudo_member  # Cache for future lookups
    return pseudo_member


Metric._missing_ = _metric_missing
Metric.display_name = _metric_display_name
Metric.display_name.__doc__ = _metric_display_name.__doc__


@classmethod
def _scope_missing(cls, value: str):
    """Handle unknown scope values from newer API versions."""
    pseudo_member = object.__new__(cls)
    pseudo_member._name_ = value
    pseudo_member._value_ = value
    cls._value2member_map_[value] = pseudo_member
    return pseudo_member


Scope._missing_ = _scope_missing


def _daily_measure_display_name(measure: DailyMeasure) -> str:
    """Returns a human-readable display name for a daily measure.

    This function converts a DailyMeasure enum value into a formatted string suitable for display.
    """
    return measure.value.replace("_", " ")


@classmethod
def _daily_measure_missing(cls, value: str):
    """Handle unknown daily measure values from newer API versions.

    This allows the client to gracefully handle new measures added to the API
    without requiring a client library update. Unknown values become dynamic
    enum members that behave like regular DailyMeasure values.
    """
    pseudo_member = object.__new__(cls)
    pseudo_member._name_ = value
    pseudo_member._value_ = value
    cls._value2member_map_[value] = pseudo_member  # Cache for future lookups
    return pseudo_member


DailyMeasure._missing_ = _daily_measure_missing
DailyMeasure.display_name = _daily_measure_display_name
DailyMeasure.display_name.__doc__ = _daily_measure_display_name.__doc__
