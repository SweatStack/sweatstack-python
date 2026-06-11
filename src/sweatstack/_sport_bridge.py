# TEMPORARY legacy-tolerance shim for the OST sport-vocabulary migration.
#
# The PUBLIC sport type is open_sport_taxonomy.Sport; this file only lets the SDK keep talking to a
# pre-migration (legacy) server during the rollout window. DELETE THIS FILE WHOLE in the contract
# release -- see plans/005_ost_sport_bridge.md. A repo-wide grep for `_sport_bridge` returning zero
# hits is the definition of done for the cleanup.
from typing import Annotated, Any

from open_sport_taxonomy import Sport
from open_sport_taxonomy.pydantic import SportField
from pydantic import BeforeValidator

# The migration delta, authored once: (legacy SweatStack wire value, OST wire value).
# Only the values that actually changed; everything else is byte-identical in both vocabularies.
_MIGRATION: list[tuple[str, str]] = [
    ("cycling.trainer", "cycling+stationary"),
    ("running.treadmill", "running+stationary"),
    ("rowing.ergometer", "rowing+stationary"),
    ("cycling.tt", "cycling.time_trial"),
    ("cycling.mountainbike", "cycling.mountain"),
    ("cross_country_skiing", "xc_skiing"),
    ("cross_country_skiing.classic", "xc_skiing.classic"),
    ("cross_country_skiing.skate", "xc_skiing.skate"),
    ("unknown", "generic"),
]
_LEGACY_TO_OST: dict[str, str] = {legacy: ost for legacy, ost in _MIGRATION}
_OST_TO_LEGACY: dict[str, str] = {ost: legacy for legacy, ost in _MIGRATION}


def to_ost_sport(value: Any) -> Sport:
    """Normalize any inbound sport value to an OST ``Sport``, tolerating legacy spellings.

    The one inbound decoder, used in two places: as the pydantic ``BeforeValidator`` in front of OST's
    ``SportField`` (response models), and directly where the SDK builds a Sport from a raw string
    (``Client.get_sports``). It applies the SweatStack-specific renames no library can know, then
    defers to ``Sport.parse`` -- permissive, so unknown/future codes are preserved, never raised; never
    the strict ``Sport(...)`` constructor. Already-built ``Sport`` objects pass straight through.

    Returning a ``Sport`` (not a string) is fine for the ``BeforeValidator``: ``SportField`` still
    serializes it to the canonical wire string.
    """
    if isinstance(value, Sport):
        return value
    return Sport.parse(_LEGACY_TO_OST.get(value, value))


def encode_sport(sport: Sport) -> str:
    """Serialize an OST ``Sport`` to a wire value a PRE-migration server accepts.

    During the bridge window the server speaks legacy, so the changed values are translated back;
    everything else (the vast majority, incl. ``running``) is byte-identical and passes through as the
    canonical OST string. Deleted at the contract release, where ``str(sport)`` is sent directly.
    """
    wire = str(sport)
    return _OST_TO_LEGACY.get(wire, wire)


def normalize_sport_column(df, column: str = "sport"):
    """Translate legacy wire values to OST in a DataFrame's sport column, in place.

    Longitudinal/parquet DataFrames are read straight from the wire and bypass the pydantic models
    (and thus ``to_ost_sport``), so this is where the response-side legacy->OST swap happens for tabular
    data. The column stays plain strings in canonical OST form (per OST's "store ``str(sport)``"
    guidance), not Sport objects. Guarded by column presence; a no-op once the server speaks OST.
    Deleted at the contract release.
    """
    if column in df.columns:
        df[column] = df[column].map(lambda v: _LEGACY_TO_OST.get(v, v))
    return df


# Legacy-tolerant response field: OST's own SportField, fronted by the inbound normalizer.
# At the contract release this is replaced wholesale by open_sport_taxonomy.pydantic.SportField.
LegacySportField = Annotated[SportField, BeforeValidator(to_ost_sport)]
