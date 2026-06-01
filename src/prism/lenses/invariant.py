"""L3: Invariant & Test-Adequacy lens.

Do claimed invariants hold? Is the test suite sufficient?
Catches uniquely: structurally well-formed artifacts whose invariants are unsatisfiable.
"""

from __future__ import annotations

import json
import time

from prism.core.types import Artifact, Finding, LensOutcome, LensResult
from prism.lenses.base import Lens
from prism.providers.base import CompletionRequest, ModelProvider

SYSTEM_PROMPT = """You are an invariant and test-adequacy verifier. Your job is to determine
whether claimed invariants hold and whether the test coverage is sufficient.

You must check for:
1. Stated invariants (pre/post conditions, type contracts, assertions) that can be violated
2. Edge cases not covered by tests (null, empty, overflow, concurrent access)
3. Test suite gaps — scenarios that would catch a planted bug but aren't tested
4. Logical contradictions between claimed behavior and implementation

You are looking for INVARIANT VIOLATIONS and TEST GAPS — correctness issues.
You are NOT checking information flow, style, or contract completeness (other lenses handle those).

Respond with valid JSON matching this schema:
{
  "outcome": "pass" | "fail" | "uncertain",
  "confidence": 0.0-1.0,
  "findings": [
    {
      "file": "filename or null",
      "line": line_number_or_null,
      "category": "invariant_violation" | "untested_edge_case" | "insufficient_coverage" | "logical_contradiction",
      "evidence": "specific description of the invariant issue or test gap",
      "severity": "critical" | "major" | "minor"
    }
  ]
}

If all invariants hold and tests are adequate, return outcome=pass with empty findings.
Be precise. Name the specific invariant or edge case."""


class InvariantLens(Lens):
    @property
    def name(self) -> str:
        return "invariant"

    @property
    def description(self) -> str:
        return "Verifies invariant satisfaction and test-adequacy."

    async def evaluate(
        self,
        artifact: Artifact,
        intent: str,
        model_family: str,
        model_id: str,
        provider: ModelProvider,
    ) -> LensResult:
        user_prompt = f"""## Intent (defines expected invariants)
{intent}

## Artifact ({artifact.type.value})
```
{artifact.content}
```

Check: do all claimed invariants hold? Are there untested edge cases that would catch a planted bug?"""

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
