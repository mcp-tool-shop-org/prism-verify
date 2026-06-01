"""Base lens protocol.

All lenses implement this protocol. A lens takes a stripped artifact + intent
and returns a LensResult via an alt-family model.
"""

from __future__ import annotations

import hashlib
import json
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Literal

from pydantic import ValidationError

from prism.core.types import Artifact, Finding, LensOutcome, LensResult

if TYPE_CHECKING:
    from prism.providers.base import ModelProvider


class Lens(ABC):
    """Abstract base for verification lenses."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique lens identifier (e.g., 'contract_completeness')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this lens checks."""
        ...

    @abstractmethod
    def build_prompts(self, artifact: Artifact, intent: str) -> tuple[str, str]:
        """Return the (system_prompt, user_prompt) this lens issues for (artifact, intent).

        Must be deterministic and side-effect-free: the engine hashes this pair into the
        receipt for replayability (PIN_PER_STEP), and evaluate() builds its request from
        the same pair.
        """
        ...

    @abstractmethod
    async def evaluate(
        self,
        artifact: Artifact,
        intent: str,
        model_family: str,
        model_id: str,
        provider: ModelProvider,
    ) -> LensResult:
        """Evaluate the artifact through this lens.

        Args:
            artifact: The (already-stripped) artifact to verify.
            intent: What the artifact is supposed to do.
            model_family: The verifier model family being used.
            model_id: The specific verifier model.
            provider: The model provider to call.

        Returns:
            LensResult with findings.
        """
        ...


_VALID_OUTCOMES = {"pass", "fail", "uncertain"}


def compute_prompt_hash(system_prompt: str, user_prompt: str) -> str:
    """SHA-256 over the (system_prompt, user_prompt) pair a lens issued.

    Pinned into the receipt so a verification is byte-for-byte replayable
    (PIN_PER_STEP). A NUL separator prevents (sys+user) collisions across the join.
    """
    h = hashlib.sha256()
    h.update(system_prompt.encode())
    h.update(b"\x00")
    h.update(user_prompt.encode())
    return h.hexdigest()


def _extract_json(text: str) -> str:
    """Strip markdown fences / surrounding prose, returning the likely JSON body.

    Local and smaller hosted models routinely wrap JSON in ```json ... ``` fences
    or prefix it with prose despite instructions; this recovers the object.
    """
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\s*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s).strip()
    if not s.startswith("{"):
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end != -1 and end > start:
            s = s[start : end + 1]
    return s


def _coerce_severity(value: object) -> Literal["critical", "major", "minor"]:
    """Map a verifier's severity string onto the Finding enum, conservatively.

    Unknown values default to ``major`` (REVISE-worthy) rather than being dropped.
    """
    v = value.strip().lower() if isinstance(value, str) else ""
    if v == "critical" or v in ("blocker", "fatal"):
        return "critical"
    if v == "minor" or v in ("low", "info", "informational", "trivial", "nit"):
        return "minor"
    return "major"


def _coerce_confidence(value: object) -> float:
    """Clamp a verifier's confidence into [0, 1]; default 0.5 if non-numeric."""
    if isinstance(value, bool):
        return 0.5
    if isinstance(value, (int, float)):
        c = float(value)
    elif isinstance(value, str):
        try:
            c = float(value)
        except ValueError:
            return 0.5
    else:
        return 0.5
    return max(0.0, min(1.0, c))


def _as_str_or_none(value: object) -> str | None:
    return None if value is None else str(value)


def _as_int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def parse_lens_response(
    content: str,
    *,
    lens: str,
    model_family: str,
    model_id: str,
    latency_ms: int | None = None,
) -> LensResult:
    """Parse a verifier's raw response into a LensResult, degrading gracefully.

    Verifier models routinely emit JSON wrapped in markdown fences, prefixed with
    prose, or carrying out-of-enum values (severity "high", outcome "accept"). None
    of these may crash ``verify()``: an unparseable response, or one whose outcome
    is unrecognized, degrades to an UNCERTAIN result flagged ``errored`` so the
    engine treats it as an availability fault, not a genuine adjudication.
    """

    def _fault(reason: str) -> LensResult:
        return LensResult(
            lens=lens,
            model_family=model_family,
            model_id=model_id,
            outcome=LensOutcome.UNCERTAIN,
            findings=[Finding(category="parse_error", evidence=reason, severity="major")],
            confidence=0.0,
            sees_reasoning=False,
            latency_ms=latency_ms,
            errored=True,
        )

    try:
        data = json.loads(_extract_json(content))
    except json.JSONDecodeError:
        return _fault("Verifier response was not valid JSON")
    if not isinstance(data, dict):
        return _fault("Verifier response JSON was not an object")

    try:
        raw_findings = data.get("findings")
        findings = [
            Finding(
                file=_as_str_or_none(f.get("file")),
                line=_as_int_or_none(f.get("line")),
                category=str(f.get("category", "unknown")),
                evidence=str(f.get("evidence", "")),
                severity=_coerce_severity(f.get("severity")),
            )
            for f in (raw_findings if isinstance(raw_findings, list) else [])
            if isinstance(f, dict)
        ]
        confidence = _coerce_confidence(data.get("confidence", 0.5))
    except (ValidationError, ValueError, TypeError) as exc:
        return _fault(f"Verifier response failed schema coercion: {exc}")

    outcome = LensOutcome.UNCERTAIN
    recognized = False
    raw_outcome = data.get("outcome")
    if isinstance(raw_outcome, str):
        normalized = raw_outcome.strip().lower()
        if normalized in _VALID_OUTCOMES:
            outcome = LensOutcome(normalized)
            recognized = True

    return LensResult(
        lens=lens,
        model_family=model_family,
        model_id=model_id,
        outcome=outcome,
        findings=findings,
        confidence=confidence,
        sees_reasoning=False,
        latency_ms=latency_ms,
        errored=not recognized,
    )
