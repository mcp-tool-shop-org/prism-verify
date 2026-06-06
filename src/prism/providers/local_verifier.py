"""Local fine-tuned groundedness verifier — the Verifier specialist as prism's citation backend.

Bridges prism's CITATION groundedness lens to a locally-served Qwen3-14B QLoRA (the certified
``verifier-14b600-soup``, served by llama.cpp at ``--lora scale 4``). prism hands this provider a
citation prompt — SOURCE (title+abstract) + CLAIM wrapped in ``<<<...>>>`` markers — and parses the
reply with ``parse_citation_groundedness``, which expects JSON ``{"outcome": ...}`` where outcome is
``supported | contradicted | not_addressed``.

The adapter was trained on ``(EVIDENCE, CLAIM) -> {supported|unsupported|abstain}`` and emits
``<think>...</think>\n\n{verdict}``. So this provider:
  1. RE-TEMPLATES prism's markered prompt into the model's trained EVIDENCE/CLAIM shape;
  2. queries the served model, STRIPS the ``<think>`` block, reads the bare verdict;
  3. MAPS the verdict to prism's vocabulary (matches prism's own definitions — see
     ``specialist/V-D-INTEGRATION.md``); and
  4. emits the JSON object prism parses — NEVER the bare ``<think>`` reply, which would parse as the
     safe default ``not_addressed`` and silently escalate 100% of citations.

On any failure (HTTP error, empty/garbage body, no mappable verdict) it raises ``ProviderError``
so the engine's circuit-breaker fails OVER to a hosted verifier (core/routing.py +
engine.py:_verify_citations) — a loud failover, not a silent escalate. Opt-in: registered only
when ``PRISM_LOCAL_VERIFIER_ENDPOINT`` is set (core/setup.py).
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from prism.core.types import ModelFamily
from prism.providers.base import (
    CompletionRequest,
    CompletionResponse,
    ModelProvider,
    ProviderError,
)

# The groundedness system prompt the adapter was TRAINED with (specialist/dataset/config.py
# SYSTEM_PROMPT). Embedded verbatim — re-templating to the trained prompt preserves accuracy.
VERIFIER_SYSTEM = (
    "You are a Groundedness Verifier. Given EVIDENCE and a CLAIM, decide whether the evidence "
    "supports the claim. Check every load-bearing part of the claim against the evidence. Answer "
    "'supported' (every part traces to the evidence), 'unsupported' (some part is contradicted or "
    "not present in the evidence), or 'abstain' (the evidence is silent — insufficient to judge). "
    "Reason briefly, then give the one-word verdict."
)

# model verdict -> prism citation outcome. Principled, not arbitrary: prism defines
# 'contradicted' = source conflicts with claim and 'not_addressed' = abstract insufficient
# (citations.py). Our curriculum trained 'unsupported' = a planted conflict/violation (L2) and
# 'abstain' = evidence silent (L5), so the 3-way mapping is exact.
VERDICT_MAP = {"supported": "supported", "unsupported": "contradicted", "abstain": "not_addressed"}

_SOURCE_RE = re.compile(r"<<<SOURCE\s*(.*?)\s*SOURCE>>>", re.DOTALL)
_CLAIM_RE = re.compile(r"<<<CLAIM\s*(.*?)\s*CLAIM>>>", re.DOTALL)


def retemplate(user_prompt: str) -> str:
    """prism citation user-prompt (``<<<SOURCE>>>`` / ``<<<CLAIM>>>``) -> the model's trained
    ``EVIDENCE:\\n...\\n\\nCLAIM:\\n...`` shape. Falls back to the raw prompt
    if markers are absent."""
    src = _SOURCE_RE.search(user_prompt)
    clm = _CLAIM_RE.search(user_prompt)
    evidence = src.group(1).strip() if src else user_prompt.strip()
    claim = clm.group(1).strip() if clm else ""
    return f"EVIDENCE:\n{evidence}\n\nCLAIM:\n{claim}"


def parse_verdict(text: str) -> str | None:
    """Strip the ``<think>`` block and read the trailing bare verdict. ORDER MATTERS: 'unsupported'
    contains 'supported', so it must be tested first. Returns None when no verdict is present."""
    tail = text.split("</think>")[-1].lower()
    for v in ("unsupported", "abstain", "supported"):
        if v in tail:
            return v
    return None


class LocalVerifierProvider(ModelProvider):
    """Serves the certified local groundedness verifier for prism's citation lens."""

    def __init__(
        self,
        endpoint: str,
        model_id: str = "qwen3-14b-groundedness",
        family: ModelFamily = ModelFamily.LOCAL_VERIFIER,
        timeout: float = 60.0,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model_id = model_id
        self._family = family
        self._client = httpx.AsyncClient(base_url=self._endpoint, timeout=timeout)

    @property
    def family(self) -> ModelFamily:
        return self._family

    @property
    def available_models(self) -> list[str]:
        return [self._model_id]

    def _build_response(
        self, verdict: str, latency_ms: int, usage: dict[str, Any]
    ) -> CompletionResponse:
        outcome = VERDICT_MAP[verdict]
        body = json.dumps(
            {
                "outcome": outcome,
                "confidence": 0.9 if verdict != "abstain" else 0.5,
                "supporting_span": None,
                "detail": f"local groundedness verifier ({self._model_id}): {verdict} -> {outcome}",
            }
        )
        return CompletionResponse(
            content=body,
            model_id=self._model_id,
            latency_ms=latency_ms,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        user = retemplate(request.user_prompt)
        start = time.monotonic()
        try:
            resp = await self._client.post(
                "/v1/chat/completions",
                json={
                    "messages": [
                        {"role": "system", "content": VERIFIER_SYSTEM},
                        {"role": "user", "content": user},
                    ],
                    # a generous cap independent of prism's max_tokens, so a <think> block is never
                    # truncated before the verdict token (which would map to a silent escalate).
                    "max_tokens": 512,
                    "temperature": 0.1,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError, IndexError) as exc:
            raise ProviderError(f"local verifier call failed: {exc}", retryable=True) from exc

        verdict = parse_verdict(content)
        if verdict is None:
            # No mappable verdict -> RAISE (never a silent 'not_addressed') — engine fails over.
            raise ProviderError(
                f"local verifier emitted no verdict (content={content[:160]!r})", retryable=True
            )
        latency_ms = int((time.monotonic() - start) * 1000)
        return self._build_response(verdict, latency_ms, data.get("usage") or {})

    async def health_check(self) -> bool:
        try:
            r = await self._client.get("/health")
            return r.status_code == 200
        except httpx.HTTPError:
            return False
