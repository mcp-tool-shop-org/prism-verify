"""Opt-in L4 (groundedness) training-data capture sink.

prism's receipts are a privacy-preserving AUDIT trail: they store artifact *hashes* (not text)
and never persist the per-citation ``CitationResult``s. That makes the receipt store unusable as a
training corpus for a local groundedness specialist (a planned prism ``local`` lens backend) — the
clean ``(claim, evidence, label)`` triples exist only transiently inside a ``VerifyResponse``.

This module captures those triples at verify time, BEFORE strip-to-hash discards them, and only when
explicitly enabled: ``PRISM_HARVEST_PATH`` set to a writable path. **Default OFF** — unset env means
no capture, no file written, and zero behavior change (the engine hook is a no-op). Captured records
use the ``prism-l4-harvest/v1`` schema and feed the Verifier-specialist dataset build; receipts stay
the join/provenance index via ``receipt_id``.

Two capture sources:

* **Citation path** — each RESOLVED ``CitationResult`` is a clean triple: the input claim (joined
  by position), the retrieved ``supporting_span``/``source_abstract``, and a label from
  ``finding_match``. Existence failures (FABRICATED/UNRESOLVABLE/METADATA_MISMATCH) train the
  *existence floor*, not groundedness, so they are skipped.
* **Code/tool path** — the ``groundedness`` LLM lens: a PASS with no findings means the whole
  artifact was judged grounded; each FAIL finding is a specific fabricated claim.

The label mapping mirrors prism's own verdict semantics so the corpus is a faithful distillation:
SUPPORTED -> ``supported`` (prism ACCEPT), CONTRADICTED -> ``unsupported`` (prism REVISE/REFUSE),
NOT_ADDRESSED -> ``abstain`` (prism ESCALATE).

Privacy: the sink writes artifact-derived text to a local, operator-controlled file. A best-effort
``scrub`` redacts a few high-signal secret shapes before write; it is NOT a guarantee against a
determined adversary — keep the harvest file under the same controls as the artifacts themselves.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from prism.core.citations import parse_citations
from prism.core.types import (
    ExistenceOutcome,
    FindingMatch,
    LensOutcome,
    VerifyError,
    VerifyRequest,
    VerifyResponse,
)

HARVEST_SCHEMA = "prism-l4-harvest/v1"
_ENV_PATH = "PRISM_HARVEST_PATH"

# Citation finding_match -> L4 label, mirroring prism's verdict semantics (see module docstring).
# UNCHECKED is never a groundedness signal (the existence floor handled it) -> not captured.
_FINDING_MATCH_LABEL: dict[FindingMatch, str] = {
    FindingMatch.SUPPORTED: "supported",
    FindingMatch.CONTRADICTED: "unsupported",
    FindingMatch.NOT_ADDRESSED: "abstain",
}

# Groundedness code-lens outcome -> L4 label.
_LENS_OUTCOME_LABEL: dict[LensOutcome, str] = {
    LensOutcome.PASS: "supported",
    LensOutcome.FAIL: "unsupported",
    LensOutcome.UNCERTAIN: "abstain",
}

# Conservative best-effort secret redaction (NOT a guarantee — see module docstring).
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9]{16,}"),               # OpenAI-style API keys
    re.compile(r"AKIA[0-9A-Z]{16}"),                  # AWS access key id
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),        # GitHub tokens
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),  # bearer tokens
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),  # PEM private-key blocks
    re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),  # emails
)
_REDACTED = "[REDACTED]"


def harvest_path() -> Path | None:
    """The configured harvest file, or None when capture is disabled (env unset/empty)."""
    raw = os.environ.get(_ENV_PATH)
    return Path(raw) if raw else None


def harvest_enabled() -> bool:
    """Whether L4 capture is enabled (``PRISM_HARVEST_PATH`` set to a non-empty path)."""
    return harvest_path() is not None


def _default_scrub(text: str) -> str:
    """Redact a few high-signal secret shapes. Best-effort only (see module docstring)."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


def _record(
    *,
    claim: str,
    evidence_span: str,
    verdict: str,
    confidence: float | None,
    source: str,
    request: VerifyRequest,
    response: VerifyResponse,
    scrub: Callable[[str], str],
) -> dict[str, Any]:
    return {
        "schema": HARVEST_SCHEMA,
        "claim": scrub(claim),
        "evidence_span": scrub(evidence_span),
        "verdict": verdict,
        "confidence": confidence,
        "source": source,
        "producer_family": request.caller.model_family.value,
        "artifact_type": request.artifact.type.value,
        "receipt_id": response.receipt.id,
        "multi_hop": False,
        "timestamp": response.receipt.timestamp.isoformat(),
    }


def build_records(
    request: VerifyRequest,
    response: VerifyResponse,
    *,
    scrub: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """Project a completed verification into L4 ``(claim, evidence, label)`` training records.

    Pure and side-effect-free (no file I/O) so it unit-tests directly. Returns ``[]`` when the
    response carries no groundedness signal. ``capture`` wraps this with the gated file append.
    """
    scrub = scrub or _default_scrub
    records: list[dict[str, Any]] = []

    # (1) Citation path: the clean per-claim triples. Join CitationResults back to the input claims
    # by POSITION — the engine builds citation_results in citation order (engine._verify_citations),
    # so index i corresponds to citations[i]; this is robust to missing or duplicate citation ids.
    if response.citation_results:
        try:
            claims = [c.claim for c in parse_citations(request.artifact.content)]
        except (json.JSONDecodeError, ValueError, ValidationError):
            claims = []
        for i, cr in enumerate(response.citation_results):
            if cr.existence != ExistenceOutcome.RESOLVED:
                continue  # existence failures train the existence floor, not groundedness
            label = _FINDING_MATCH_LABEL.get(cr.finding_match)
            if label is None:
                continue  # UNCHECKED — no groundedness signal
            claim = claims[i] if i < len(claims) else ""
            evidence = cr.supporting_span or cr.source_abstract or ""
            if not claim or not evidence:
                continue  # a record missing the claim or the evidence cannot train anything
            records.append(
                _record(
                    claim=claim,
                    evidence_span=evidence,
                    verdict=label,
                    confidence=cr.confidence,
                    source="prism-citation",
                    request=request,
                    response=response,
                    scrub=scrub,
                )
            )

    # (2) Code/tool path: the groundedness LLM lens. Citation-path lenses are named
    # "citation_groundedness:<i>:<id>", so this name check captures only the code-lens and never
    # double-counts citations. Errored placeholders are availability faults, not adjudications.
    for lens_result in response.lens_results:
        if lens_result.lens != "groundedness" or lens_result.errored:
            continue
        label = _LENS_OUTCOME_LABEL.get(lens_result.outcome)
        if label is None:
            continue
        if lens_result.findings:
            for finding in lens_result.findings:
                if not finding.evidence:
                    continue
                records.append(
                    _record(
                        claim=finding.evidence,
                        evidence_span=request.intent,
                        verdict=label,
                        confidence=lens_result.confidence,
                        source="prism-groundedness",
                        request=request,
                        response=response,
                        scrub=scrub,
                    )
                )
        elif lens_result.outcome == LensOutcome.PASS:
            records.append(
                _record(
                    claim=request.artifact.content,
                    evidence_span=request.intent,
                    verdict="supported",
                    confidence=lens_result.confidence,
                    source="prism-groundedness",
                    request=request,
                    response=response,
                    scrub=scrub,
                )
            )

    return records


def capture(
    request: VerifyRequest,
    response: VerifyResponse | VerifyError,
    *,
    scrub: Callable[[str], str] | None = None,
) -> int:
    """Append L4 training records for a completed verification — IFF capture is enabled.

    Returns the number of records written (0 when disabled or when there is no signal). No-op when
    ``PRISM_HARVEST_PATH`` is unset or when ``response`` is not a successful ``VerifyResponse``
    (e.g. a ``VerifyError``). Never raises into the verify path: harvesting is best-effort
    instrumentation, never part of the verdict contract, so I/O errors are swallowed.
    """
    path = harvest_path()
    if path is None or not isinstance(response, VerifyResponse):
        return 0
    records = build_records(request, response, scrub=scrub)
    if not records:
        return 0
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
    except OSError:
        return 0
    return len(records)
