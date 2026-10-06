"""The resource namespaces of :class:`sweatstack.Client`: ``client.activities``, ``client.traces``, ...

Each attribute of the client mirrors the first URL segment after ``/api/v1/`` (plan 009, R1).
"""

from ._app_metadata import AppMetadata, ProfileAppMetadata
from .activities import Activities, Longitudinal
from .dailies import Dailies
from .oauth import OAuth
from .portal import Portal, PortalSessions
from .profile import Profile
from .teams import Teams
from .tests import Tests
from .traces import Traces
from .users import Users

__all__ = [
    "Activities",
    "AppMetadata",
    "Dailies",
    "Longitudinal",
    "OAuth",
    "Portal",
    "PortalSessions",
    "Profile",
    "ProfileAppMetadata",
    "Teams",
    "Tests",
    "Traces",
    "Users",
]
