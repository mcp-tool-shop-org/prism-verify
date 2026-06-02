"""Tests for family-different routing (Lock 1)."""

import time

import pytest

from prism.core.routing import (
    CIRCUIT_BREAKER_RESET_S,
    CIRCUIT_BREAKER_THRESHOLD,
    DEFAULT_ROUTING_MAP,
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
            (ModelFamily.LOCAL, "mistral-small:24b"),
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

    def test_skips_family_with_no_configured_provider(self):
        """Router walks past a candidate whose family has no provider (local-only trap)."""
        router = FamilyRouter()
        # Anthropic caller, but only a local provider is configured: the primary (Google)
        # and secondary (OpenAI) routes must be skipped, not dead-ended on.
        route = router.select_verifier(ModelFamily.ANTHROPIC, available_families={"local"})
        assert route.family == ModelFamily.LOCAL
        assert route.model_id == "mistral-small:24b"

    def test_no_configured_cross_family_raises(self):
        """If the only configured provider is the caller's own family, refuse."""
        router = FamilyRouter()
        with pytest.raises(RoutingError):
            router.select_verifier(ModelFamily.ANTHROPIC, available_families={"anthropic"})

    def test_available_families_none_preserves_legacy_behavior(self):
        """Omitting available_families keeps the original primary route (no filtering)."""
        router = FamilyRouter()
        route = router.select_verifier(ModelFamily.ANTHROPIC)
        assert route.family == ModelFamily.GOOGLE
        assert route.is_fallback is False

    def test_tripped_circuit_auto_resets_after_cooldown_and_reselects(self):
        """TEST-A-004: a tripped provider auto-recovers after CIRCUIT_BREAKER_RESET_S.

        Trip the primary (Google) for an Anthropic caller — selection then falls back to OpenAI.
        Back-date the open circuit past the cooldown; the next selection must return the RECOVERED
        primary (Google) as the non-fallback route, proving the time-based auto-reset re-arms it.
        """
        router = FamilyRouter()
        primary = router.select_verifier(ModelFamily.ANTHROPIC)
        assert primary.family == ModelFamily.GOOGLE

        for _ in range(CIRCUIT_BREAKER_THRESHOLD):
            router.report_failure(primary.family, primary.model_id)
        # While open, selection skips Google -> falls back to OpenAI.
        assert router.select_verifier(ModelFamily.ANTHROPIC).family == ModelFamily.OPENAI

        # Age the open circuit past the cooldown (deterministic — no real sleep).
        circuit = router._get_circuit(f"{primary.family.value}:{primary.model_id}")
        assert circuit.is_open is True
        circuit.open_since = time.monotonic() - (CIRCUIT_BREAKER_RESET_S + 1)

        recovered = router.select_verifier(ModelFamily.ANTHROPIC)
        assert recovered.family == ModelFamily.GOOGLE  # primary re-armed
        assert recovered.is_fallback is False


def test_hosted_routing_ids_are_served_by_their_providers():
    """Guard the routing-map <-> provider drift the audit found, for the hosted families.

    Every hosted verifier model_id in DEFAULT_ROUTING_MAP must be one its provider actually
    serves (LOCAL is covered by test_local_route_id_matches_ollama_default).
    """
    from prism.providers.anthropic import AnthropicProvider
    from prism.providers.google import GoogleProvider
    from prism.providers.openai import OpenAIProvider

    served = {
        ModelFamily.ANTHROPIC: set(AnthropicProvider(api_key="x").available_models),
        ModelFamily.GOOGLE: set(GoogleProvider(api_key="x").available_models),
        ModelFamily.OPENAI: set(OpenAIProvider(api_key="x").available_models),
    }
    for routes in DEFAULT_ROUTING_MAP.values():
        for family, model_id in routes:
            if family in served:
                assert model_id in served[family], (
                    f"routing map references {family.value}:{model_id}, "
                    f"but that provider serves {sorted(served[family])}"
                )


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

    def test_time_based_auto_reset_clears_failures(self):
        """TEST-A-004 (state level): reading is_open after the cooldown re-closes the breaker
        AND clears the accumulated failures, so it takes a fresh THRESHOLD run to re-trip."""
        cs = CircuitState()
        for _ in range(CIRCUIT_BREAKER_THRESHOLD):
            cs.record_failure()
        assert cs.is_open is True

        cs.open_since = time.monotonic() - (CIRCUIT_BREAKER_RESET_S + 1)
        assert cs.is_open is False  # cooldown elapsed -> auto-reset
        assert cs.failures == []  # failure window cleared by the reset
        # One more failure must NOT immediately re-open (threshold counts from zero again).
        cs.record_failure()
        assert cs.is_open is False
