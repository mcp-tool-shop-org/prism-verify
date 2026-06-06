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
    # A locally-served, fine-tuned SPECIALIST verifier (the Verifier specialist — a Qwen3-14B QLoRA
    # for citation groundedness). Distinct family from LOCAL (=mistral) so it satisfies
    # family-difference and leaves LOCAL as a real cross-family failover target. Opt-in via
    # PRISM_LOCAL_VERIFIER_ENDPOINT.
    LOCAL_VERIFIER = "local-verifier"


class ArtifactType(StrEnum):
    """Artifact types. v1 shipped code/tool-call; v0.3 adds citations (a JSON array)."""

    CODE = "code"
    TOOL_CALL = "tool_call"
    CITATIONS = "citations"


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
    INVALID_ARTIFACT = "INVALID_ARTIFACT"


class ExistenceOutcome(StrEnum):
    """Stage 1 (v0.3 citations): deterministic retrieval outcome for one citation."""

    RESOLVED = "resolved"
    METADATA_MISMATCH = "metadata_mismatch"
    FABRICATED = "fabricated"
    UNRESOLVABLE = "unresolvable"


class FindingMatch(StrEnum):
    """Stage 3 (v0.3 citations): groundedness outcome for a resolved citation."""

    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    NOT_ADDRESSED = "not_addressed"
    UNCHECKED = "unchecked"


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
    prompt_hash: str | None = None  # SHA-256 of (system_prompt, user_prompt); set by the engine


class Receipt(BaseModel):
    """Replayable verification receipt."""

    id: str
    pre_strip_hash: str
    post_strip_hash: str
    timestamp: datetime
    verifier_models: list[str]
    pairwise_rho: dict[str, float]
    reasoning_visibility_mode: ReasoningVisibility
    lens_prompt_hashes: dict[str, str] = Field(default_factory=dict)
    artifact_type: str = "code"
    retrieval_pins: list[dict[str, str]] = Field(default_factory=list)
    alg: str = "HMAC-SHA256"  # "Ed25519" (v0.4 default) or "HMAC-SHA256" (legacy)
    kid: str = ""  # key id (Ed25519 public-key fingerprint); empty for HMAC
    schema_version: int = 4
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
    citation_results: list[CitationResult] = Field(default_factory=list)
    receipt: Receipt


class VerifyError(BaseModel):
    """Structured error when verification cannot proceed."""

    reason: RefusalReason
    detail: str
    retryable: bool = False


# --- Citation verification types (v0.3) ---


class Citation(BaseModel):
    """A single citation to verify (one element of a CITATIONS artifact)."""

    claim: str = Field(min_length=1, max_length=2000)
    title: str = ""
    authors: str = ""
    year: int | str | None = None
    identifier: str | None = None  # arXiv:<id>, a bare arXiv id (vN ok), or a DOI
    id: str | None = None          # caller's local handle, echoed back in the result


class CitationResult(BaseModel):
    """Per-citation adjudication returned to the caller (two-axis verdict)."""

    citation_id: str | None
    identifier: str | None
    existence: ExistenceOutcome
    finding_match: FindingMatch = FindingMatch.UNCHECKED
    verdict: Verdict
    action: str
    detail: str
    source_title: str | None = None
    source_abstract: str | None = None
    supporting_span: str | None = None
    # Set only when a verdict is driven by the groundedness LLM lens (RESOLVED +
    # supported/contradicted/not_addressed): carries that lens's parsed confidence so the
    # artifact-level VerifyResponse.confidence reflects the probabilistic stage. Left None
    # for deterministic existence outcomes (FABRICATED/UNRESOLVABLE/numeric mismatch), which
    # the projection then treats as full confidence (1.0). (CORE-A-003)
    confidence: float | None = None
