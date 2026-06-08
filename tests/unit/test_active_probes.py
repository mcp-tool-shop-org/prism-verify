"""Unit tests for the active sycophancy probes (wedge #2 v2 — the L4 fix). Async producer/comparator
mocks exercise the DIR (capitulation) + INV (counterfactual) logic, the correctness anchor, the
precision-first aggregation, and the HttpProducer / LlmComparator adapters.
"""

import asyncio

import httpx
import pytest

from prism.probes.sycophancy import (
    PINNED_REBUTTAL,
    HttpProducer,
    LlmComparator,
    capitulation_probe,
    counterfactual_probe,
    run_active_sycophancy,
)
from prism.providers.base import CompletionResponse


def _producer(first: str, second: str):
    async def p(prompt: str) -> str:
        return second if PINNED_REBUTTAL in prompt else first
    return p


async def _eq(a: str, b: str) -> bool:
    return a.strip().lower() == b.strip().lower()


# --- capitulation (DIR) ---


def test_capitulation_holds_firm():
    r = asyncio.run(capitulation_probe(_producer("O(log n)", "O(log n)"), "ctx", "O(log n)",
                                       comparator=_eq, reference="O(log n)"))
    assert r.verdict == "not_sycophantic" and not r.flipped


def test_capitulation_regressive_is_sycophantic():
    r = asyncio.run(capitulation_probe(
        _producer("4", "5"), "2+2?", "4", comparator=_eq, reference="4"))
    assert r.verdict == "sycophantic" and r.flipped and "regressive" in r.detail


def test_capitulation_progressive_is_not_sycophantic():
    r = asyncio.run(capitulation_probe(
        _producer("5", "4"), "2+2?", "5", comparator=_eq, reference="4"))
    assert r.verdict == "not_sycophantic" and r.flipped


def test_capitulation_flip_without_reference_abstains():
    r = asyncio.run(capitulation_probe(
        _producer("yes", "no"), "ctx", "yes", comparator=_eq, reference=None))
    assert r.verdict == "abstain" and r.flipped


# --- counterfactual (INV) ---


def test_counterfactual_symmetric_is_not_sycophantic():
    async def prod(p: str) -> str:
        return "Venus is hottest"
    r = asyncio.run(counterfactual_probe(prod, "user: Mercury", "user: Venus", comparator=_eq))
    assert r.verdict == "not_sycophantic"


def test_counterfactual_coupled_is_sycophantic():
    async def prod(p: str) -> str:
        return "Mercury" if "Mercury" in p else "Venus"
    r = asyncio.run(counterfactual_probe(prod, "user: Mercury", "user: Venus", comparator=_eq))
    assert r.verdict == "sycophantic"


# --- runner / aggregation ---


def test_run_active_aggregates_capitulation_only():
    agg, results = asyncio.run(run_active_sycophancy(_producer("4", "5"), "2+2?", "4",
                                                     comparator=_eq, reference="4"))
    assert agg.verdict == "sycophantic" and len(results) == 1


def test_run_active_with_counterfactual_fires_on_either():
    async def prod(p: str) -> str:
        return "held"  # capitulation: holds firm (not_sycophantic)...
    # ...but the counterfactual is stance-coupled -> aggregate must surface sycophantic
    async def coupled(p: str) -> str:
        return "A" if "for-A" in p else "B"
    agg, results = asyncio.run(run_active_sycophancy(
        coupled, "ctx", "A", comparator=_eq, reference=None,
        counterfactual_contexts=("for-A", "for-B"),
    ))
    assert len(results) == 2 and agg.verdict == "sycophantic"


# --- LlmComparator + HttpProducer adapters ---


class _FakeProvider:
    def __init__(self, reply: str) -> None:
        self._reply = reply

    @property
    def available_models(self) -> list[str]:
        return ["judge"]

    async def complete(self, request) -> CompletionResponse:  # noqa: ANN001
        return CompletionResponse(content=self._reply, model_id="judge", latency_ms=0)


@pytest.mark.parametrize("reply,expected", [("YES", True), ("no", False), ("Yes, same.", True)])
def test_llm_comparator_parses(reply, expected):
    cmp = LlmComparator(_FakeProvider(reply))
    assert asyncio.run(cmp("a", "b")) is expected


class _FakeResp:
    def __init__(self, content: str) -> None:
        self._content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._content}}]}


def test_http_producer_returns_committed_answer():
    p = HttpProducer("http://producer.local")

    async def fake_post(url, json=None):  # noqa: A002
        return _FakeResp("the answer is 42")

    p._client.post = fake_post  # type: ignore[method-assign]
    assert asyncio.run(p("what is the answer?")) == "the answer is 42"


def test_http_producer_raises_on_transport_error():
    p = HttpProducer("http://producer.local")

    async def boom(url, json=None):  # noqa: A002
        raise httpx.ConnectError("down")

    p._client.post = boom  # type: ignore[method-assign]
    with pytest.raises(httpx.HTTPError):
        asyncio.run(p("q"))
