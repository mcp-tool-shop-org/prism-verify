"""L1: Contract Completeness lens.

Does the artifact satisfy every clause of the declared intent?
Catches uniquely: missing required behavior the producer omitted but didn't lie about.
"""

from __future__ import annotations

import json
import time

from prism.core.types import Artifact, Finding, LensOutcome, LensResult
from prism.lenses.base import Lens
from prism.providers.base import CompletionRequest, ModelProvider

SYSTEM_PROMPT = """You are a contract-completeness verifier. Your job is to determine whether
a code artifact satisfies EVERY clause of the declared intent.

You must:
1. Parse the intent into discrete, testable clauses
2. For each clause, determine if the artifact satisfies it
3. Report findings for any clause that is NOT satisfied or is ambiguously satisfied

You are looking for MISSING behavior — things the intent requires but the artifact does not provide.
You are NOT looking for bugs, style issues, or security problems (other lenses handle those).

Respond with valid JSON matching this schema:
{
  "outcome": "pass" | "fail" | "uncertain",
  "confidence": 0.0-1.0,
  "findings": [
    {
      "file": "filename or null",
      "line": line_number_or_null,
      "category": "missing_clause" | "partial_implementation" | "ambiguous_satisfaction",
      "evidence": "specific description of what's missing",
      "severity": "critical" | "major" | "minor"
    }
  ]
}

If all clauses are satisfied, return outcome=pass with empty findings.
Be precise. Cite specific intent clauses and specific code locations."""


class ContractCompletenessLens(Lens):
    @property
    def name(self) -> str:
        return "contract_completeness"

    @property
    def description(self) -> str:
        return "Verifies that the artifact satisfies every clause of the declared intent."

    async def evaluate(
        self,
        artifact: Artifact,
        intent: str,
        model_family: str,
        model_id: str,
        provider: ModelProvider,
    ) -> LensResult:
        user_prompt = f"""## Intent
{intent}

## Artifact ({artifact.type.value})
```
{artifact.content}
```

Evaluate whether this artifact satisfies every clause of the intent."""

        start = time.monotonic()
        response = await provider.complete(
            CompletionRequest(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model_id=model_id,
            )
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        # Parse structured response
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
