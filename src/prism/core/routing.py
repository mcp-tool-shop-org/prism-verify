"""Family-different routing with circuit-breaker.

Lock 1: Caller family is ALWAYS excluded from verifier selection.
No silent same-family fallback — outage returns VERIFIER_UNAVAILABLE.

Justification:
- Panickssery/Bowman/Feng NeurIPS 2024: self-recognition correlates linearly with self-preference
- Wataoka 2024: self-preference bias is perplexity-driven (familiarity = correctness regression)
- Li et al. ICLR 2026: same-lineage judges favor outputs even without identity disclosure
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from prism.core.types import ModelFamily

# Default routing map: caller family -> ordered list of (alt_family, model_id) verifiers
DEFAULT_ROUTING_MAP: dict[ModelFamily, list[tuple[ModelFamily, str]]] = {
    ModelFamily.ANTHROPIC: [
        (ModelFamily.GOOGLE, "gemini-2.5-pro"),
        (ModelFamily.OPENAI, "gpt-5.4-mini"),
        (ModelFamily.LOCAL, "mistral-small:24b"),
    ],
    ModelFamily.OPENAI: [
        (ModelFamily.ANTHROPIC, "claude-sonnet-4-6"),
        (ModelFamily.GOOGLE, "gemini-2.5-pro"),
        (ModelFamily.LOCAL, "mistral-small:24b"),
    ],
    ModelFamily.GOOGLE: [
        (ModelFamily.ANTHROPIC, "claude-sonnet-4-6"),
        (ModelFamily.OPENAI, "gpt-5.4-mini"),
        (ModelFamily.LOCAL, "mistral-small:24b"),
    ],
    ModelFamily.LOCAL: [
        (ModelFamily.ANTHROPIC, "claude-sonnet-4-6"),
        (ModelFamily.OPENAI, "gpt-5.4-mini"),
        (ModelFamily.GOOGLE, "gemini-2.5-pro"),
    ],
}

# Circuit-breaker: open after this many consecutive failures within the window
CIRCUIT_BREAKER_THRESHOLD = 3
CIRCUIT_BREAKER_WINDOW_S = 60.0
CIRCUIT_BREAKER_RESET_S = 30.0


@dataclass
class CircuitState:
    """Per-provider circuit-breaker state."""

    failures: list[float] = field(default_factory=list)
    open_since: float | None = None

    @property
    def is_open(self) -> bool:
        if self.open_since is None:
            return False
        # Auto-reset after cooldown
        if time.monotonic() - self.open_since > CIRCUIT_BREAKER_RESET_S:
            self.open_since = None
            self.failures.clear()
            return False
        return True

    def record_failure(self) -> None:
        now = time.monotonic()
        # Prune old failures outside window
        self.failures = [t for t in self.failures if now - t < CIRCUIT_BREAKER_WINDOW_S]
        self.failures.append(now)
        if len(self.failures) >= CIRCUIT_BREAKER_THRESHOLD:
            self.open_since = now

    def record_success(self) -> None:
        self.failures.clear()
        self.open_since = None


class RoutingError(Exception):
    """All cross-family routes exhausted."""

    pass


@dataclass
class RouteSelection:
    """Selected verifier route."""

    family: ModelFamily
    model_id: str
    is_fallback: bool = False


class FamilyRouter:
    """Routes verification requests to alt-family models with circuit-breaking."""

    def __init__(
        self,
        routing_map: dict[ModelFamily, list[tuple[ModelFamily, str]]] | None = None,
    ) -> None:
        self._routing_map = routing_map or DEFAULT_ROUTING_MAP
        self._circuits: dict[str, CircuitState] = {}

    def _get_circuit(self, key: str) -> CircuitState:
        if key not in self._circuits:
            self._circuits[key] = CircuitState()
        return self._circuits[key]

    def select_verifier(
        self,
        caller_family: ModelFamily,
        available_families: set[str] | None = None,
    ) -> RouteSelection:
        """Select the best available alt-family verifier.

        Args:
            caller_family: The caller's model family (will be excluded).
            available_families: Families that actually have a configured provider. When
                given, candidates whose family has no provider are SKIPPED rather than
                selected — otherwise the router hands back a family the engine cannot serve
                and the request dead-ends on VERIFIER_UNAVAILABLE (the local-only-deployment
                trap: an Anthropic caller with only a local provider would otherwise be
                routed to Google/OpenAI and refused out of the box).

        Returns:
            RouteSelection with the chosen verifier.

        Raises:
            RoutingError: If no cross-family route is both configured and circuit-closed.
        """
        candidates = self._routing_map.get(caller_family, [])

        for i, (family, model_id) in enumerate(candidates):
            # Lock 1: never same-family (defensive check)
            if family == caller_family:
                continue

            # Walk past families with no configured provider instead of selecting an
            # unserviceable route.
            if available_families is not None and family.value not in available_families:
                continue

            circuit_key = f"{family.value}:{model_id}"
            circuit = self._get_circuit(circuit_key)

            if not circuit.is_open:
                return RouteSelection(
                    family=family,
                    model_id=model_id,
                    is_fallback=i > 0,
                )

        raise RoutingError(
            f"VERIFIER_UNAVAILABLE: no cross-family route for caller={caller_family.value} "
            f"is both configured and circuit-closed"
        )

    def report_success(self, family: ModelFamily, model_id: str) -> None:
        """Report a successful verification call."""
        circuit_key = f"{family.value}:{model_id}"
        self._get_circuit(circuit_key).record_success()

    def report_failure(self, family: ModelFamily, model_id: str) -> None:
        """Report a failed verification call."""
        circuit_key = f"{family.value}:{model_id}"
        self._get_circuit(circuit_key).record_failure()

    def get_next_fallback(
        self,
        caller_family: ModelFamily,
        failed_model_id: str,
        available_families: set[str] | None = None,
    ) -> RouteSelection | None:
        """Get the next available fallback after a failure.

        Returns None if no fallback is available (caller should raise RoutingError).
        """
        candidates = self._routing_map.get(caller_family, [])
        past_failed = False

        for i, (family, model_id) in enumerate(candidates):
            if family == caller_family:
                continue
            if model_id == failed_model_id:
                past_failed = True
                continue
            if not past_failed:
                continue
            if available_families is not None and family.value not in available_families:
                continue

            circuit_key = f"{family.value}:{model_id}"
            circuit = self._get_circuit(circuit_key)

            if not circuit.is_open:
                return RouteSelection(
                    family=family,
                    model_id=model_id,
                    is_fallback=True,
                )

        return None
