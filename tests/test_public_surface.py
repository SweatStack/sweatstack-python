"""Guards the public surface of the package.

These tests exist because the singleton list used to be hand-curated and
silently drifted from the actual ``Client`` class (``update_trace`` and
``delete_trace`` shipped invisible for releases). The current implementation
auto-discovers public methods, so these tests fail loudly the moment that
mechanism regresses.
"""

from inspect import getmembers, isfunction

import sweatstack
from sweatstack.client import Client


def _public_client_methods() -> set[str]:
    return {
        name for name, obj in getmembers(Client)
        if not name.startswith("_") and isfunction(obj)
    }


class TestSingletonCoverage:
    def test_every_public_client_method_is_exposed_at_module_level(self):
        missing = []
        for name in _public_client_methods():
            attr = getattr(sweatstack, name, None)
            if not callable(attr):
                missing.append(name)
        assert not missing, (
            f"Public Client methods missing module-level singletons: {missing}"
        )

    def test_singletons_in_dunder_all(self):
        missing = sorted(_public_client_methods() - set(sweatstack.__all__))
        assert not missing, (
            f"Public Client methods missing from sweatstack.__all__: {missing}"
        )

    def test_known_previously_missing_methods_now_exposed(self):
        """Regression guard for the 0.77.x bug — these were never registered."""
        assert callable(sweatstack.update_trace)
        assert callable(sweatstack.delete_trace)


class TestDunderAll:
    def test_no_underscored_names(self):
        leaked = [n for n in sweatstack.__all__ if n.startswith("_")]
        assert not leaked, f"Underscore-prefixed names in __all__: {leaked}"

    def test_no_duplicates(self):
        assert len(sweatstack.__all__) == len(set(sweatstack.__all__))

    def test_every_entry_resolves(self):
        unresolved = [n for n in sweatstack.__all__ if not hasattr(sweatstack, n)]
        assert not unresolved, (
            f"Names in __all__ that don't resolve on the package: {unresolved}"
        )

    def test_core_surface_present(self):
        for name in (
            "Client",
            "TraceResolution",
            "Sport",
            "Modifier",
            "SweatStackNotFoundError",
            "SweatStackAPIError",
            "enable_cache",
        ):
            assert name in sweatstack.__all__, f"missing {name}"
