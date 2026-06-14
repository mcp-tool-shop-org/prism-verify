"""Family-different routing with circuit-breaker.

Lock 1: Caller family is ALWAYS excluded from verifier selection.
No silent same-family fallback — outage returns VERIFIER_UNAVAILABLE.

Justification:
- Panickssery/Bowman/Feng NeurIPS 2024: self-recognition correlates linearly with self-preference
- Wataoka 2024: self-preference bias is perplexity-driven (familiarity = correctness regression)
- Li et al. ICLR 2026: same-lineage judges favor outputs even without identity disclosure

MEASUREMENT-ONLY ESCAPE HATCH (``FamilyRouter(allow_same_family=True)``): the ONLY way to disable
Lock 1. It exists solely so the ``prism eval --family-ab`` calibration can build a same-family
*control* arm and MEASURE the cost of self-preference. It defaults OFF and is set True in exactly
one place — ``_build_same_family_control`` in the eval CLI. It MUST NEVER be plumbed to the
production engine, the HTTP surface, the MCP surface, or the ``prism verify`` path. If you find
yourself passing ``allow_same_family=True`` outside the family-AB control, you are defeating Lock 1.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from prism.core.observability import get_request_id, routing_logger
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


def with_local_verifier(
    base: dict[ModelFamily, list[tuple[ModelFamily, str]]],
    model_id: str = "qwen3-14b-groundedness",
) -> dict[ModelFamily, list[tuple[ModelFamily, str]]]:
    """A routing map with the local Verifier specialist PREPENDED as the primary verifier for every
    caller (so it serves the high-frequency citation check, failing over to that caller's existing
    cross-family verifiers when its circuit opens), plus a caller row for LOCAL_VERIFIER itself.

    Injected by ``build_default_engine`` ONLY when the specialist provider is configured, so the
    static ``DEFAULT_ROUTING_MAP`` — and its shipped contract/tests — is unchanged when it is not.
    LOCAL_VERIFIER is a distinct family from LOCAL (=mistral), so family-difference holds and
    mistral stays a failover.
    """
    out = {
        caller: [(ModelFamily.LOCAL_VERIFIER, model_id), *verifiers]
        for caller, verifiers in base.items()
    }
    out[ModelFamily.LOCAL_VERIFIER] = [
        (ModelFamily.ANTHROPIC, "claude-sonnet-4-6"),
        (ModelFamily.OPENAI, "gpt-5.4-mini"),
        (ModelFamily.GOOGLE, "gemini-2.5-pro"),
        (ModelFamily.LOCAL, "mistral-small:24b"),
    ]
    return out

# Circuit-breaker: open after this many consecutive failures within the window
CIRCUIT_BREAKER_THRESHOLD = 3
CIRCUIT_BREAKER_WINDOW_S = 60.0
CIRCUIT_BREAKER_RESET_S = 30.0


@dataclass
class CircuitState:
    """Per-provider circuit-breaker state."""

    failures: list[float] = field(default_factory=list)
    open_since: float | None = None

    # Tracks whether the cooldown auto-reset has already been observed (and thus logged) since the
    # breaker last opened, so reading ``is_open`` repeatedly logs the half-open recovery only once.
    _auto_reset_logged: bool = field(default=False, repr=False)

    @property
    def is_open(self) -> bool:
        if self.open_since is None:
            return False
        # Auto-reset after cooldown (half-open: the next selection probes the recovered route).
        if time.monotonic() - self.open_since > CIRCUIT_BREAKER_RESET_S:
            self.open_since = None
            self.failures.clear()
            self._auto_reset_just_fired = not self._auto_reset_logged
            self._auto_reset_logged = True
            return False
        return True

    # Set transiently by ``is_open`` when the cooldown auto-reset fires; the router reads + clears
    # it to emit a single half-open recovery log. Not part of the persisted breaker state.
    _auto_reset_just_fired: bool = field(default=False, repr=False)

    def take_auto_reset_event(self) -> bool:
        """Return (and clear) whether the cooldown auto-reset just fired on the last ``is_open``."""
        fired = self._auto_reset_just_fired
        self._auto_reset_just_fired = False
        return fired

    def record_failure(self) -> bool:
        """Record a failure; return True iff this failure transitioned the breaker OPEN."""
        now = time.monotonic()
        was_open = self.open_since is not None
        # Prune old failures outside window
        self.failures = [t for t in self.failures if now - t < CIRCUIT_BREAKER_WINDOW_S]
        self.failures.append(now)
        if len(self.failures) >= CIRCUIT_BREAKER_THRESHOLD:
            self.open_since = now
            self._auto_reset_logged = False
            return not was_open
        return False

    def record_success(self) -> bool:
        """Record a success; return True iff this success transitioned the breaker CLOSED."""
        was_open = self.open_since is not None
        self.failures.clear()
        self.open_since = None
        self._auto_reset_logged = False
        return was_open


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
        *,
        allow_same_family: bool = False,
    ) -> None:
        """Construct the router.

        Args:
            routing_map: caller family -> ordered (alt_family, model_id) verifiers.
            allow_same_family: MEASUREMENT-ONLY Lock-1 bypass. When True, the router will select a
                same-family verifier (i.e. a route whose family == caller_family). DEFAULT False —
                this is the ONLY switch that disables Lock 1 and must be set True in exactly one
                place: ``_build_same_family_control`` for the ``--family-ab`` calibration control
                arm. NEVER set it on a router serving production traffic (engine/HTTP/MCP/verify).
        """
        self._routing_map = routing_map or DEFAULT_ROUTING_MAP
        self._circuits: dict[str, CircuitState] = {}
        self._allow_same_family = allow_same_family

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
            # Lock 1: never same-family (defensive check). The ONLY exception is the
            # measurement-only ``allow_same_family`` bypass used by the --family-ab control arm.
            if family == caller_family and not self._allow_same_family:
                continue

            # Walk past families with no configured provider instead of selecting an
            # unserviceable route.
            if available_families is not None and family.value not in available_families:
                continue

            circuit_key = f"{family.value}:{model_id}"
            circuit = self._get_circuit(circuit_key)

            open_now = circuit.is_open
            # ``is_open`` performs the time-based auto-reset; if it just fired, this selection is
            # the half-open probe of a recovered route.
            if circuit.take_auto_reset_event():
                routing_logger.info(
                    "circuit_half_open_probe",
                    extra={
                        "request_id": get_request_id(),
                        "family": family.value,
                        "model_id": model_id,
                        "circuit_key": circuit_key,
                    },
                )
            if not open_now:
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
        recovered = self._get_circuit(circuit_key).record_success()
        if recovered:
            routing_logger.info(
                "circuit_closed",
                extra={
                    "request_id": get_request_id(),
                    "family": family.value,
                    "model_id": model_id,
                    "circuit_key": circuit_key,
                },
            )

    def report_failure(self, family: ModelFamily, model_id: str) -> None:
        """Report a failed verification call."""
        circuit_key = f"{family.value}:{model_id}"
        opened = self._get_circuit(circuit_key).record_failure()
        if opened:
            routing_logger.warning(
                "circuit_open",
                extra={
                    "request_id": get_request_id(),
                    "family": family.value,
                    "model_id": model_id,
                    "circuit_key": circuit_key,
                    "threshold": CIRCUIT_BREAKER_THRESHOLD,
                },
            )

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
            # Mirror the Lock-1 gate from select_verifier: same-family is skipped unless the
            # measurement-only bypass is set (the --family-ab control arm).
            if family == caller_family and not self._allow_same_family:
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
