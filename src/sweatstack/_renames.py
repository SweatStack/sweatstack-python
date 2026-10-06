"""Names removed from the public API, and what replaced them.

The single source for the upgrade path: ``Client.__getattr__`` and the package's module-level
``__getattr__`` turn a removed name into an ``AttributeError`` that names the replacement, and
``tests/test_renames.py`` checks every entry against the client and the CHANGELOG.

Each value is a template: ``{c}`` becomes ``client`` or ``sweatstack``, whichever the caller
used. Entries are permanent; removing one turns a helpful error back into a bare one.
"""

from __future__ import annotations

REMOVED_IN = {
    # 0.91: flat methods became resource namespaces (plan 009, M3).
    "get_activities": ("0.91", "{c}.activities.list()"),
    "get_activity": ("0.91", "{c}.activities.retrieve(activity_id)"),
    "get_latest_activity": ("0.91", "{c}.activities.latest()"),
    "get_activity_data": ("0.91", "{c}.activities.data(activity_id)"),
    "get_activity_mean_max": ("0.91", "{c}.activities.mean_max(activity_id, metric=...)"),
    "get_activity_awd": ("0.91", "{c}.activities.awd(activity_id)"),
    "get_latest_activity_data": ("0.91", "{c}.activities.data({c}.activities.latest().id)"),
    "get_latest_activity_mean_max": (
        "0.91",
        "{c}.activities.mean_max({c}.activities.latest().id, metric=...)",
    ),
    "get_longitudinal_data": ("0.91", "{c}.activities.longitudinal.data(...)"),
    "get_longitudinal_mean_max": ("0.91", "{c}.activities.longitudinal.mean_max(...)"),
    "get_longitudinal_awd": ("0.91", "{c}.activities.longitudinal.awd(...)"),
    "upload": ("0.91", "{c}.activities.upload(files)"),
    "get_backfill_status": ("0.91", "{c}.activities.backfill_status()"),
    "watch_backfill_status": ("0.91", "{c}.activities.watch_backfill_status()"),
    "set_activity_app_metadata": ("0.91", "{c}.activities.app_metadata.set(activity_id, data=...)"),
    "delete_activity_app_metadata": ("0.91", "{c}.activities.app_metadata.delete(activity_id)"),
    "get_traces": ("0.91", "{c}.traces.list()"),
    "create_trace": ("0.91", "{c}.traces.create(...)"),
    "update_trace": ("0.91", "{c}.traces.replace(trace_id, ...)"),
    "delete_trace": ("0.91", "{c}.traces.delete(trace_id)"),
    "set_trace_app_metadata": ("0.91", "{c}.traces.app_metadata.set(trace_id, data=...)"),
    "delete_trace_app_metadata": ("0.91", "{c}.traces.app_metadata.delete(trace_id)"),
    "get_tests": ("0.91", "{c}.tests.list()"),
    "get_test": ("0.91", "{c}.tests.retrieve(test_id)"),
    "create_test": ("0.91", "{c}.tests.create(...)"),
    "update_test": ("0.91", "{c}.tests.replace(test_id, ...)"),
    "delete_test": ("0.91", "{c}.tests.delete(test_id)"),
    "set_test_app_metadata": ("0.91", "{c}.tests.app_metadata.set(test_id, data=...)"),
    "delete_test_app_metadata": ("0.91", "{c}.tests.app_metadata.delete(test_id)"),
    "get_dailies": ("0.91", "{c}.dailies.list(measure, start=..., end=...)"),
    "set_daily": ("0.91", "{c}.dailies.set(measure, date=..., value=...)"),
    "delete_daily": ("0.91", "{c}.dailies.delete(measure, date=...)"),
    "get_profile_status": ("0.91", "{c}.profile.status()"),
    "get_sports": ("0.91", "{c}.profile.sports()"),
    "get_tags": ("0.91", "{c}.profile.tags()"),
    "set_user_app_metadata": ("0.91", "{c}.profile.app_metadata.set(data=...)"),
    "delete_user_app_metadata": ("0.91", "{c}.profile.app_metadata.delete()"),
    "get_users": ("0.91", "{c}.users.list()"),
    "get_user": ("0.91", "{c}.users.list(name=...), which returns every match"),
    "create_user": ("0.91", "{c}.users.create(first_name=...)"),
    "get_teams": ("0.91", "{c}.teams.list()"),
    "get_team_users": ("0.91", "{c}.teams.users(team_id)"),
    "get_team_user": ("0.91", "{c}.teams.users(team_id, name=...), which returns every match"),
    "get_authorized_teams": ("0.91", "{c}.teams.authorized()"),
    "authorize_team": ("0.91", "{c}.teams.authorize(team_id)"),
    "create_portal_session": ("0.91", "{c}.portal.sessions.create(destination)"),
    "get_userinfo": ("0.91", "{c}.oauth.userinfo()"),
    "get_authorization_url": ("0.91", "{c}.oauth.authorization_url(...)"),
    "exchange_code_for_token": ("0.91", "{c}.oauth.exchange_code(...)"),
    "generate_pkce_params": ("0.91", "{c}.oauth.generate_pkce_params()"),
    "switch_user": (
        "0.91",
        "{c}.delegated_client(user), which returns a new client and leaves this one unchanged",
    ),
    "switch_back": ("0.91", "the original client, or {c}.principal_client()"),
    "jwt": ("0.91", "{c}.api_key"),
}


def attribute_error(owner: str, name: str, *, prefix: str) -> AttributeError:
    """The error for a missing attribute: names the replacement when ``name`` was removed.

    Args:
        owner: What the lookup was on, for the message (``"'Client' object"``, ``"module
            'sweatstack'"``).
        name: The attribute that was looked up.
        prefix: How the caller refers to the owner in code (``"client"``, ``"sweatstack"``).
    """
    if name in REMOVED_IN:
        release, hint = REMOVED_IN[name]
        return AttributeError(
            f"{owner} has no attribute {name!r}: it was removed in {release}. "
            f"Use {hint.format(c=prefix)} instead. "
            f"The CHANGELOG entry for {release} lists every change"
        )
    return AttributeError(f"{owner} has no attribute {name!r}")
