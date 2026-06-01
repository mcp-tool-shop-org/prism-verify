"""L4: Groundedness / Hallucination lens.

Does every load-bearing claim trace to a provided source?
Catches uniquely: confident fabrications.
"""

from __future__ import annotations

import json
import time

from prism.core.types import Artifact, Finding, LensOutcome, LensResult
from prism.lenses.base import Lens
from prism.providers.base import CompletionRequest, ModelProvider

SYSTEM_PROMPT = """You are a groundedness verifier. Your job is to detect hallucinated or
fabricated claims in code artifacts — particularly in comments, docstrings, error messages,
and any text that references external facts.

You must check for:
1. Comments or docstrings that cite APIs, libraries, or behaviors that don't exist
2. Error messages referencing non-existent error codes or documentation links
3. Configuration values that claim to follow a standard but don't match it
4. Tool-call arguments referencing non-existent endpoints, parameters, or schemas
5. Any load-bearing factual claim that cannot be verified from the artifact's context

You are looking for FABRICATIONS — confident claims without grounding.
You are NOT checking correctness of logic, information flow, or style (other lenses handle those).

Respond with valid JSON matching this schema:
{
  "outcome": "pass" | "fail" | "uncertain",
  "confidence": 0.0-1.0,
  "findings": [
    {
      "file": "filename or null",
      "line": line_number_or_null,
      "category": "fabricated_reference" | "phantom_api"
                | "ungrounded_claim" | "hallucinated_behavior",
      "evidence": "the specific claim and why it appears fabricated",
      "severity": "critical" | "major" | "minor"
    }
  ]
}

If all claims appear grounded, return outcome=pass with empty findings.
Be precise. Quote the specific fabricated claim."""


class GroundednessLens(Lens):
    @property
    def name(self) -> str:
        return "groundedness"

    @property
    def description(self) -> str:
        return "Detects hallucinated or fabricated claims in artifacts."

    async def evaluate(
        self,
        artifact: Artifact,
        intent: str,
        model_family: str,
        model_id: str,
        provider: ModelProvider,
    ) -> LensResult:
        user_prompt = f"""## Intent (context for what's expected)
{intent}

## Artifact ({artifact.type.value})
```
{artifact.content}
```

Check: does this artifact contain any fabricated references, \
phantom APIs, or ungrounded factual claims?"""

        start = time.monotonic()
        response = await provider.complete(
            CompletionRequest(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model_id=model_id,
            )
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        try:
            data = json.loads(response.content)
        except json.JSONDecodeError:
            return LensResult(
                lens=self.name,
                model_family=model_family,
                model_id=model_id,
                outcome=LensOutcome.UNCERTAIN,
                findings=[
                    Finding(
                        category="parse_error",
                        evidence="Verifier response was not valid JSON",
                        severity="major",
                    )
                ],
                confidence=0.0,
                sees_reasoning=False,
                latency_ms=latency_ms,
            )

        findings = [
            Finding(
                file=f.get("file"),
                line=f.get("line"),
                category=f.get("category", "unknown"),
                evidence=f.get("evidence", ""),
                severity=f.get("severity", "major"),
            )
            for f in data.get("findings", [])
        ]

        return LensResult(
            lens=self.name,
            model_family=model_family,
            model_id=model_id,
            outcome=LensOutcome(data.get("outcome", "uncertain")),
            findings=findings,
            confidence=float(data.get("confidence", 0.5)),
            sees_reasoning=False,
            latency_ms=latency_ms,
        )
