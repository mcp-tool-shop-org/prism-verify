"""Citation artifact parsing, the deterministic numeric guard, and the groundedness prompt.

The pure (provider-free) half of the v0.3 citation layer. The engine orchestrates these with
the retrieval oracle and a family-different verifier; this module hides parsing, the numeric
guard, and the lens prompt (DECOMPOSE_BY_SECRETS).
"""

from __future__ import annotations

import json
import re

from prism.core.types import Citation
from prism.lenses.base import _extract_json


def parse_citations(content: str) -> list[Citation]:
    """Parse a CITATIONS artifact: a JSON array of citation objects.

    Raises json.JSONDecodeError / ValueError / pydantic ValidationError on a malformed
    artifact; the engine maps those to a structured INVALID_ARTIFACT refusal.
    """
    data = json.loads(content)
    if not isinstance(data, list):
        raise ValueError("citations artifact must be a JSON array")
    citations: list[Citation] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"citation #{i} is not a JSON object")
        citations.append(Citation(**item))
    return citations


_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def _percentages(text: str) -> set[float]:
    return {round(float(m), 3) for m in _PCT.findall(text or "")}


def numeric_mismatch(claim: str, source: str) -> tuple[bool, str]:
    """Deterministic numeric guard for the '95.8% vs 89%' class.

    Flags a contradiction only when BOTH the claim and the retrieved source state percentages
    and the claim's set is disjoint from the source's (within tolerance). A reasoning-stripped
    NLI/LLM lens is structurally blind to number swaps (Naik 2018, arXiv:1806.00692), so this
    is a separate, replayable stage (Proof-Carrying-Numbers, Solatorio 2025). Scoped to
    percentages to stay precision-biased: when the source simply omits the figure this returns
    False, leaving it to the groundedness NOT_ADDRESSED path rather than a false contradiction.
    """
    claim_pcts = _percentages(claim)
    source_pcts = _percentages(source)
    if not claim_pcts or not source_pcts:
        return False, ""
    tol = 0.5
    for c in claim_pcts:
        if any(abs(c - s) <= tol for s in source_pcts):
            return False, ""  # at least one claimed percentage is corroborated by the source
    return (
        True,
        f"claim cites {sorted(claim_pcts)}% but the source states {sorted(source_pcts)}%",
    )


CITATION_GROUNDEDNESS_SYSTEM = """You are a citation-groundedness verifier. You are given a \
SOURCE (the title and abstract of a real, retrieved paper) and a CLAIM that cites it. Decide \
whether the SOURCE supports the CLAIM.

Rules:
- Judge ONLY against the provided SOURCE text. Do NOT rely on prior knowledge of the paper.
- "supported": the source clearly states or directly implies the claim.
- "contradicted": the source states something that conflicts with the claim.
- "not_addressed": the title+abstract do not contain enough to confirm or deny (the supporting
  detail may be in the full text). This is NOT a refutation.

Respond with valid JSON:
{
  "outcome": "supported" | "contradicted" | "not_addressed",
  "confidence": 0.0-1.0,
  "supporting_span": "the sentence from the SOURCE that supports/contradicts, or null",
  "detail": "one sentence explaining the decision"
}"""


def build_citation_groundedness_prompts(
    claim: str, source_title: str, source_abstract: str
) -> tuple[str, str]:
    """Build the (system, user) groundedness prompt fed the RETRIEVED source (RAG-L4)."""
    user = f"""## SOURCE (retrieved — judge only against this)
Title: {source_title}

Abstract: {source_abstract or "(no abstract available)"}

## CLAIM
{claim}

Does the SOURCE support the CLAIM?"""
    return CITATION_GROUNDEDNESS_SYSTEM, user


_VALID_MATCHES = {"supported", "contradicted", "not_addressed"}


def parse_citation_groundedness(content: str) -> tuple[str, str | None, float]:
    """Parse the groundedness verifier's JSON -> (outcome, supporting_span, confidence).

    Degrades gracefully: an unparseable/garbage response yields ('not_addressed', None, 0.0) —
    i.e. CANNOT_CONFIRM/escalate, never a fabricated 'supported'.
    """
    try:
        data = json.loads(_extract_json(content))
    except json.JSONDecodeError:
        return "not_addressed", None, 0.0
    if not isinstance(data, dict):
        return "not_addressed", None, 0.0
    outcome = str(data.get("outcome", "")).strip().lower()
    if outcome not in _VALID_MATCHES:
        outcome = "not_addressed"
    raw_span = data.get("supporting_span")
    span = str(raw_span) if isinstance(raw_span, str) and raw_span.strip() else None
    raw_conf = data.get("confidence", 0.0)
    try:
        confidence = max(0.0, min(1.0, float(raw_conf)))
    except (TypeError, ValueError):
        confidence = 0.0
    return outcome, span, confidence
