"""Lock-1 bypass safety regression (F-01 1A).

The ``allow_same_family`` flag is the ONLY switch that disables Lock 1 and exists solely for the
``prism eval --family-ab`` same-family control arm. These tests lock it to opt-in: the default
router still refuses a same-family-only map (raises RoutingError), and only an explicit
``allow_same_family=True`` selects it. If anyone reverts the gate to unconditional, the first test
goes red — that is the regression alarm.
"""

from __future__ import annotations

import pytest

from prism.core.routing import FamilyRouter, RoutingError
from prism.core.types import ModelFamily


def _same_family_only_map() -> dict[ModelFamily, list[tuple[ModelFamily, str]]]:
    """A routing map whose only candidate for the caller IS the caller's own family."""
    return {ModelFamily.ANTHROPIC: [(ModelFamily.ANTHROPIC, "anthropic-control")]}


class TestLock1Bypass:
    def test_default_router_refuses_same_family_only_map(self) -> None:
        """Default (allow_same_family=False): a same-family-only map exhausts -> RoutingError.

        This is Lock 1 holding: even when the map offers only the caller's own family, the router
        refuses rather than self-preferring.
        """
        router = FamilyRouter(routing_map=_same_family_only_map())
        with pytest.raises(RoutingError):
            router.select_verifier(ModelFamily.ANTHROPIC)

    def test_default_router_refuses_even_when_caller_family_is_available(self) -> None:
        """Lock 1 holds regardless of which providers are configured."""
        router = FamilyRouter(routing_map=_same_family_only_map())
        with pytest.raises(RoutingError):
            router.select_verifier(ModelFamily.ANTHROPIC, available_families={"anthropic"})

    def test_bypass_selects_same_family_route(self) -> None:
        """allow_same_family=True: the measurement-only bypass selects the same-family route."""
        router = FamilyRouter(routing_map=_same_family_only_map(), allow_same_family=True)
        route = router.select_verifier(ModelFamily.ANTHROPIC, available_families={"anthropic"})
        assert route.family == ModelFamily.ANTHROPIC
        assert route.model_id == "anthropic-control"

    def test_bypass_get_next_fallback_mirrors_gate(self) -> None:
        """The same gate is mirrored in get_next_fallback so the bypass is consistent.

        With a two-entry same-family map, after the first model fails the fallback walk must still
        be allowed to reach the second same-family entry when the bypass is set.
        """
        two = {
            ModelFamily.ANTHROPIC: [
                (ModelFamily.ANTHROPIC, "anthropic-control-a"),
                (ModelFamily.ANTHROPIC, "anthropic-control-b"),
            ]
        }
        bypass = FamilyRouter(routing_map=two, allow_same_family=True)
        fb = bypass.get_next_fallback(
            ModelFamily.ANTHROPIC, "anthropic-control-a", available_families={"anthropic"}
        )
        assert fb is not None and fb.model_id == "anthropic-control-b"

        # Default router: same-family fallback is forbidden -> None (no self-preferring failover).
        default = FamilyRouter(routing_map=two)
        assert (
            default.get_next_fallback(
                ModelFamily.ANTHROPIC, "anthropic-control-a", available_families={"anthropic"}
            )
            is None
        )

    def test_default_attribute_is_false(self) -> None:
        """A router built the normal way (no kwarg) keeps the bypass OFF (production default)."""
        assert FamilyRouter()._allow_same_family is False
