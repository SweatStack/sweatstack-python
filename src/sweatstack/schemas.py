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
from enum import Enum

from open_sport_taxonomy import Modifier, Sport

from .openapi_schemas import (
    AccountStatusResponse, ActivityDetails, ActivitySummary, ApplicationMemberRole, AuthorizedTeamResponse,
    BackfillStatus, Capability, CapabilityStatus, DailyMeasure, DailyResponse,
    Marker, Metric, PortalDestination, PortalSessionResponse, Scope,
    StatusIssueCode, StatusIssueResponse,
    TeamResponse, TestDetails, TestResults, TestSummary, TokenResponse, TraceDetails,
    TraceResolution, UserInfoResponse, UserResponse, UserSummary
)


def _open_enum(enum_cls: type[Enum]) -> None:
    """Let ``enum_cls`` accept values the bundled schema does not know yet.

    The server treats some enums as open sets (new metrics, scopes, daily measures, status
    codes and capabilities appear without notice). An unknown value becomes a pseudo-member
    with ``.value`` and ``.name`` set to the string, cached so repeated lookups return the
    same object, instead of a validation error that would break the client until it is
    updated. Closed enums (``CapabilityStatus``, ``PortalDestination``, ...) are left strict
    on purpose: the server promises those never grow, or a value the client does not know
    is not something it should act on.
    """
    @classmethod
    def _missing_(cls, value):
        pseudo_member = object.__new__(cls)
        pseudo_member._name_ = value
        pseudo_member._value_ = value
        cls._value2member_map_[value] = pseudo_member  # cache for future lookups
        return pseudo_member

    enum_cls._missing_ = _missing_


for _open in (Metric, Scope, DailyMeasure, StatusIssueCode, Capability):
    _open_enum(_open)


def _metric_display_name(metric: Metric) -> str:
    """Returns a human-readable display name for a metric.

    This function converts a Metric enum value into a formatted string suitable for display.
    """
    return metric.value.replace("_", " ")


Metric.display_name = _metric_display_name
Metric.display_name.__doc__ = _metric_display_name.__doc__


def _daily_measure_display_name(measure: DailyMeasure) -> str:
    """Returns a human-readable display name for a daily measure.

    This function converts a DailyMeasure enum value into a formatted string suitable for display.
    """
    return measure.value.replace("_", " ")


DailyMeasure.display_name = _daily_measure_display_name
DailyMeasure.display_name.__doc__ = _daily_measure_display_name.__doc__
