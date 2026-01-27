"""SweatStack data schemas and utilities.

This module re-exports Pydantic models from openapi_schemas and extends
the Sport and Metric enums with convenient utility methods.

Example:
    sport = Sport.cycling_road
    print(sport.display_name())  # "cycling (road)"
    print(sport.root_sport())    # Sport.cycling
    print(sport.is_root_sport())  # False
    print(sport.is_sub_sport_of(Sport.cycling))  # True
"""
from enum import Enum
from typing import List, Union

from .openapi_schemas import (
    ActivityDetails, ActivitySummary, BackfillStatus, Metric, Scope, Sport,
    TokenResponse, TraceDetails, UserInfoResponse, UserSummary
)


def _parent_sport(sport: Sport) -> Sport:
    """Returns the parent sport of a given sport.

    For sports with a hierarchical structure (e.g., 'cycling.road'), returns the parent sport
    ('cycling'). If the sport has no parent (is already a root sport), returns the sport itself.

    Args:
        sport (Sport): The sport enum value to find the parent of.

    Returns:
        Sport: The parent sport enum value, or the original sport if it has no parent.
    """
    parts = sport.value.split(".")
    if len(parts) == 1:
        return sport
    return sport.__class__(".".join(parts[:-1]))


def _root_sport(sport: Sport) -> Sport:
    """Returns the root sport of a given sport.

    For sports with a hierarchical structure (e.g., 'cycling.road' or 'cycling.road.gravel'),
    returns the root sport ('cycling'). If the sport is already a root sport, returns the sport itself.

    Args:
        sport (Sport): The sport enum value to find the root of.

    Returns:
        Sport: The root sport enum value.
    """
    return sport.__class__(sport.value.split(".")[0])


def _is_root_sport(sport: Sport) -> bool:
    """Determines if a sport is a root sport.

    A root sport is one that doesn't have a parent sport in the hierarchy
    (e.g., 'cycling' is a root sport, while 'cycling.road' is not).

    Args:
        sport (Sport): The sport enum value to check.

    Returns:
        bool: True if the sport is a root sport, False otherwise.
    """
    return sport == _root_sport(sport)


def _is_sub_sport_of(sport: Sport, sport_or_sports: Union[Sport, List[Sport]]) -> bool:
    """Determines if a sport is a sub-sport of another sport or list of sports.

    For example, 'cycling.road' is a sub-sport of 'cycling', but not of 'running'.

    Args:
        sport (Sport): The sport to check.
        sport_or_sports (Union[Sport, List[Sport]]): A sport or list of sports to check against.

    Returns:
        bool: True if the sport is a sub-sport of any of the provided sports, False otherwise.

    Raises:
        ValueError: If sport_or_sports is not a Sport or a list of Sports.
    """
    if isinstance(sport_or_sports, Sport):
        return sport.value.startswith(sport_or_sports.value)
    elif isinstance(sport_or_sports, (list, tuple)):
        return any(_is_sub_sport_of(sport, s) for s in sport_or_sports)
    else:
        raise ValueError(f"Invalid type for sport_or_sports: {type(sport_or_sports)}")


def _display_name(sport: Sport) -> str:
    """Returns a human-readable display name for a sport.

    This function converts a Sport enum value into a formatted string suitable for display.

    Args:
        sport (Sport): The sport enum value to format.

    Returns:
        str: A human-readable display name for the sport.
    """
    parts = sport.value.split(".")
    base_sport = parts[0]
    base_sport = base_sport.replace("_", " ")
    if len(parts) == 1:
        return base_sport
    the_rest = " ".join(parts[1:]).replace("_", " ")
    return f"{base_sport} ({the_rest})"


Sport.root_sport = _root_sport
Sport.root_sport.__doc__ = _root_sport.__doc__

Sport.parent_sport = _parent_sport
Sport.parent_sport.__doc__ = _parent_sport.__doc__

Sport.is_sub_sport_of = _is_sub_sport_of
Sport.is_sub_sport_of.__doc__ = _is_sub_sport_of.__doc__

Sport.is_root_sport = _is_root_sport
Sport.is_root_sport.__doc__ = _is_root_sport.__doc__

@classmethod
def _sport_missing(cls, value: str):
    """Handle unknown sport values from newer API versions.

    This allows the client to gracefully handle new sports added to the API
    without requiring a client library update. Unknown values become dynamic
    enum members that behave like regular Sport values.
    """
    pseudo_member = object.__new__(cls)
    pseudo_member._name_ = value
    pseudo_member._value_ = value
    cls._value2member_map_[value] = pseudo_member  # Cache for future lookups
    return pseudo_member


Sport._missing_ = _sport_missing
Sport.display_name = _display_name
Sport.display_name.__doc__ = _display_name.__doc__


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