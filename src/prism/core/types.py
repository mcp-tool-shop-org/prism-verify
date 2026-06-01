"""Core types for Prism verification service."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class ModelFamily(StrEnum):
    """Supported model families. Lock 1: caller family is excluded from verifier selection."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"
    LOCAL = "local"


class ArtifactType(StrEnum):
    """Artifact types supported in v1 (code/tool-call only)."""

    CODE = "code"
    TOOL_CALL = "tool_call"


class Verdict(StrEnum):
    """Four-value verdict enum (SagaLLM + Temporal doctrine)."""

    ACCEPT = "accept"
    REVISE = "revise"
    REFUSE = "refuse"
    ESCALATE = "escalate"


class LensOutcome(StrEnum):
    """Per-lens outcome before aggregation."""

    PASS = "pass"
    FAIL = "fail"
    UNCERTAIN = "uncertain"


class ReasoningVisibility(StrEnum):
    """Lock 2: reasoning-stripping mode."""

    STRIPPED = "stripped"
    CONSERVATIVE = "conservative"


class RefusalReason(StrEnum):
    """Structured refusal codes returned instead of verdicts."""

    VERIFIER_UNAVAILABLE = "VERIFIER_UNAVAILABLE"
    STRIP_VERIFICATION_FAILED = "STRIP_VERIFICATION_FAILED"
    LENS_COLLAPSE = "LENS_COLLAPSE"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"


# --- Request types ---


class Artifact(BaseModel):
    """The artifact to verify."""

    type: ArtifactType
    content: str
    spec_hash: str | None = None


class CallerContext(BaseModel):
    """Caller identification — used for family-different routing."""

    model_family: ModelFamily
    model_id: str


class Budget(BaseModel):
    """Latency and lens budget constraints."""

    max_lenses: int = Field(default=4, ge=3, le=10)
    max_latency_ms: int = Field(default=5000, ge=1000, le=30000)


class VerifyRequest(BaseModel):
    """Request to verify an artifact against intent."""

    artifact: Artifact
    intent: str = Field(min_length=1, max_length=4000)
    caller: CallerContext
    lenses: list[str] | Literal["auto"] = "auto"
    reasoning_visibility: ReasoningVisibility = ReasoningVisibility.STRIPPED
    budget: Budget = Field(default_factory=Budget)
    pairwise_rho_thresholds: dict[str, float] | None = None


# --- Response types ---


class Finding(BaseModel):
    """A single finding from a lens."""

    file: str | None = None
    line: int | None = None
    category: str
    evidence: str
    severity: Literal["critical", "major", "minor"] = "major"


class LensResult(BaseModel):
    """Result from a single lens execution."""

    lens: str
    model_family: str
    model_id: str
    outcome: LensOutcome
    findings: list[Finding] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    sees_reasoning: bool = False
    latency_ms: int | None = None
    errored: bool = False  # fault placeholder (provider/parse error), not a genuine adjudication


class Receipt(BaseModel):
    """Replayable verification receipt."""

    id: str
    pre_strip_hash: str
    post_strip_hash: str
    timestamp: datetime
    verifier_models: list[str]
    pairwise_rho: dict[str, float]
    reasoning_visibility_mode: ReasoningVisibility
    signature: str
    replayable: bool = True


class VerifyResponse(BaseModel):
    """Successful verification response."""

    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    retryable: bool
    revision_hint: str | None = Field(default=None, max_length=500)
    lens_results: list[LensResult]
    pairwise_rho: dict[str, float]
    receipt: Receipt


class VerifyError(BaseModel):
    """Structured error when verification cannot proceed."""

    reason: RefusalReason
    detail: str
    retryable: bool = False
