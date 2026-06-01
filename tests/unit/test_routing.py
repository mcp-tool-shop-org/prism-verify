"""Tests for family-different routing (Lock 1)."""


import pytest

from prism.core.routing import (
    CIRCUIT_BREAKER_THRESHOLD,
    CircuitState,
    FamilyRouter,
    RoutingError,
)
from prism.core.types import ModelFamily


class TestFamilyRouter:
    def test_anthropic_never_routes_to_anthropic(self):
        """Lock 1: caller=anthropic must never get anthropic verifier."""
        router = FamilyRouter()
        route = router.select_verifier(ModelFamily.ANTHROPIC)
        assert route.family != ModelFamily.ANTHROPIC

    def test_openai_never_routes_to_openai(self):
        router = FamilyRouter()
        route = router.select_verifier(ModelFamily.OPENAI)
        assert route.family != ModelFamily.OPENAI

    def test_google_never_routes_to_google(self):
        router = FamilyRouter()
        route = router.select_verifier(ModelFamily.GOOGLE)
        assert route.family != ModelFamily.GOOGLE

    def test_local_never_routes_to_local(self):
        router = FamilyRouter()
        route = router.select_verifier(ModelFamily.LOCAL)
        assert route.family != ModelFamily.LOCAL

    def test_primary_route_not_fallback(self):
        router = FamilyRouter()
        route = router.select_verifier(ModelFamily.ANTHROPIC)
        assert route.is_fallback is False

    def test_fallback_after_failure(self):
        router = FamilyRouter()
        route = router.select_verifier(ModelFamily.ANTHROPIC)
        primary_model = route.model_id

        fallback = router.get_next_fallback(ModelFamily.ANTHROPIC, primary_model)
        assert fallback is not None
        assert fallback.model_id != primary_model
        assert fallback.is_fallback is True

    def test_circuit_breaker_opens_after_threshold(self):
        router = FamilyRouter()
        route = router.select_verifier(ModelFamily.ANTHROPIC)

        # Trip the circuit breaker
        for _ in range(CIRCUIT_BREAKER_THRESHOLD):
            router.report_failure(route.family, route.model_id)

        # Next selection should skip the tripped provider
        new_route = router.select_verifier(ModelFamily.ANTHROPIC)
        assert new_route.model_id != route.model_id

    def test_all_routes_exhausted_raises(self):
        """When all cross-family routes are open, raise RoutingError."""
        router = FamilyRouter()

        # Trip all circuits for anthropic caller
        for family, model_id in [
            (ModelFamily.GOOGLE, "gemini-2.5-pro"),
            (ModelFamily.OPENAI, "gpt-5.4-mini"),
            (ModelFamily.LOCAL, "qwen3-32b"),
        ]:
            for _ in range(CIRCUIT_BREAKER_THRESHOLD):
                router.report_failure(family, model_id)

        with pytest.raises(RoutingError):
            router.select_verifier(ModelFamily.ANTHROPIC)

    def test_success_resets_circuit(self):
        router = FamilyRouter()
        route = router.select_verifier(ModelFamily.ANTHROPIC)

        # Add some failures (but not enough to trip)
        router.report_failure(route.family, route.model_id)
        router.report_failure(route.family, route.model_id)

        # Success should reset
        router.report_success(route.family, route.model_id)

        # Should still select the same primary
        new_route = router.select_verifier(ModelFamily.ANTHROPIC)
        assert new_route.model_id == route.model_id


class TestCircuitState:
    def test_initially_closed(self):
        cs = CircuitState()
        assert cs.is_open is False

    def test_opens_after_threshold(self):
        cs = CircuitState()
        for _ in range(CIRCUIT_BREAKER_THRESHOLD):
            cs.record_failure()
        assert cs.is_open is True

    def test_success_closes(self):
        cs = CircuitState()
        for _ in range(CIRCUIT_BREAKER_THRESHOLD):
            cs.record_failure()
        assert cs.is_open is True

        cs.record_success()
        assert cs.is_open is False
