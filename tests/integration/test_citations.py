"""End-to-end citation verification: engine.verify() with a CITATIONS artifact.

Mocks arXiv retrieval (respx) and the groundedness provider (a fake), so no network is touched.
Exercises the two-axis verdict: accept, refuse (fabricated), revise (numeric mismatch caught
deterministically before the lens), escalate (oracle down), and contradicted-by-lens.
"""

from __future__ import annotations

import json
import re

import httpx
import pytest
import respx

from prism.core.engine import VerificationEngine
from prism.core.routing import FamilyRouter
from prism.core.types import (
    Artifact,
    ArtifactType,
    CallerContext,
    ExistenceOutcome,
    FindingMatch,
    ModelFamily,
    Verdict,
    VerifyError,
    VerifyRequest,
    VerifyResponse,
)
from prism.providers.base import CompletionRequest, CompletionResponse, ModelProvider
from prism.receipts.store import ReceiptStore
from prism.retrieval.oracle import CitationOracle

ARXIV = "https://export.arxiv.org/api/query"
_EMPTY = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'


def _feed(title: str, summary: str, arxiv_id: str) -> str:
    # A real arXiv feed echoes the requested id in <id>; the oracle's id-match guard verifies it,
    # so the mock must embed the id it is standing in for (not a placeholder).
    return (
        '<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
        f"<id>http://arxiv.org/abs/{arxiv_id}</id>"
        "<published>2024-01-01T00:00:00Z</published>"
        f"<title>{title}</title><summary>{summary}</summary></entry></feed>"
    )


def _arxiv_ok(title: str, summary: str):
    """respx side_effect echoing the requested id_list into the feed's <id>, as live arXiv does,
    so the oracle's id-match guard resolves the entry. Use for the RESOLVED-path mocks."""

    def _se(request: httpx.Request) -> httpx.Response:
        ident = re.sub(r"v\d+$", "", request.url.params.get("id_list", "x"))
        return httpx.Response(200, text=_feed(title, summary, ident))

    return _se


class _GroundProvider(ModelProvider):
    """Returns a fixed groundedness verdict for every call (stands in for an alt family)."""

    def __init__(self, outcome: str = "supported") -> None:
        self._outcome = outcome

    @property
    def family(self) -> ModelFamily:
        return ModelFamily.LOCAL

    @property
    def available_models(self) -> list[str]:
        return ["mistral-small:24b"]

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        return CompletionResponse(
            content=json.dumps(
                {"outcome": self._outcome, "confidence": 0.9, "supporting_span": "the abstract"}
            ),
            model_id="mistral-small:24b",
            latency_ms=5,
        )

    async def health_check(self) -> bool:
        return True


def _engine(tmp_path, outcome: str = "supported"):
    router = FamilyRouter(
        routing_map={ModelFamily.ANTHROPIC: [(ModelFamily.LOCAL, "mistral-small:24b")]}
    )
    store = ReceiptStore(db_path=tmp_path / "r.db", signing_secret=b"cit-secret")
    oracle = CitationOracle(client=httpx.AsyncClient(timeout=5.0), retry_delays=())
    engine = VerificationEngine(
        providers={"local": _GroundProvider(outcome)},
        router=router,
        receipt_store=store,
        oracle=oracle,
    )
    return engine, store


def _request(citations: list[dict]) -> VerifyRequest:
    return VerifyRequest(
        artifact=Artifact(type=ArtifactType.CITATIONS, content=json.dumps(citations)),
        intent="verify each citation exists and the finding matches the source",
        caller=CallerContext(model_family=ModelFamily.ANTHROPIC, model_id="claude-x"),
    )


async def test_resolved_and_supported_accepts(tmp_path):
    engine, store = _engine(tmp_path, outcome="supported")
    cits = [
        {
            "id": "c1",
            "claim": "LLMs cannot self-verify",
            "identifier": "2402.01817",
            "title": "LLMs Cannot Self-Verify",
        }
    ]
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(
            side_effect=_arxiv_ok("LLMs Cannot Self-Verify", "We show LLMs cannot self-verify.")
        )
        result = await engine.verify(_request(cits))

    assert isinstance(result, VerifyResponse)
    assert result.verdict == Verdict.ACCEPT
    assert result.citation_results[0].existence == ExistenceOutcome.RESOLVED
    assert result.citation_results[0].action == "OK"
    # Receipt pins the retrieval query + source hash, marks the artifact type, and is signed.
    assert result.receipt.artifact_type == "citations"
    assert result.receipt.retrieval_pins[0]["existence"] == "resolved"
    assert result.receipt.retrieval_pins[0]["source_sha256"]
    assert "export.arxiv.org" in result.receipt.retrieval_pins[0]["query"]
    assert store.verify_signature(result.receipt.id) is True
    store.close()


async def test_resolved_supported_surfaces_full_abstract(tmp_path):
    """The RESOLVED result carries the FULL retrieved abstract, not just the lens's single
    supporting_span. A downstream re-verifier (the role-os local panel) can then judge a faithful
    claim against the whole abstract instead of one span — fixing the wave-6 e2e where a faithful
    Kambhampati claim was escalated because only the truncated span was visible. The abstract is
    already retrieved to ground the lens; prism stops discarding it (model_dump carries it to
    JSON)."""
    engine, store = _engine(tmp_path, outcome="supported")
    abstract = (
        "We argue that autoregressive LLMs cannot self-verify their own outputs and require a "
        "sound external verifier to close the loop in an LLM-Modulo framework."
    )
    cits = [{"id": "c1", "claim": "LLMs cannot self-verify", "identifier": "2402.01817"}]
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(side_effect=_arxiv_ok("A Paper", abstract))
        result = await engine.verify(_request(cits))

    cr = result.citation_results[0]
    assert cr.existence == ExistenceOutcome.RESOLVED
    assert cr.finding_match == FindingMatch.SUPPORTED
    # The full retrieved abstract is surfaced on the result (previously discarded).
    assert cr.source_abstract == abstract
    # The CLI serializes via model_dump(), so the field reaches downstream consumers as JSON.
    assert result.model_dump()["citation_results"][0]["source_abstract"] == abstract
    store.close()


async def test_two_citations_same_identifier_keep_distinct_pins(tmp_path):
    """CORE-A-002: two citations sharing ONE identifier (different claims) both ground, and the
    receipt records TWO lens_prompt_hashes — the per-index lens name prevents a collision that
    would overwrite/drop one pin (the PIN must survive duplicate identifiers)."""
    engine, store = _engine(tmp_path, outcome="supported")
    cits = [
        {"id": "a", "claim": "LLMs cannot self-verify", "identifier": "2402.01817"},
        {"id": "b", "claim": "self-correction needs a signal", "identifier": "2402.01817"},
    ]
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(
            side_effect=_arxiv_ok("A Paper", "We show LLMs cannot self-verify without an oracle.")
        )
        result = await engine.verify(_request(cits))

    assert isinstance(result, VerifyResponse)
    # Both citations reached the groundedness lens (RESOLVED + abstract present).
    assert len(result.citation_results) == 2
    assert all(cr.existence == ExistenceOutcome.RESOLVED for cr in result.citation_results)
    # Two distinct lens prompt hashes are pinned — no collision/overwrite from the shared id.
    assert len(result.receipt.lens_prompt_hashes) == 2
    assert store.verify_signature(result.receipt.id) is True
    store.close()


async def test_resolved_groundedness_surfaces_real_lens_confidence(tmp_path):
    """CORE-A-003: a RESOLVED + groundedness-driven verdict surfaces the lens's REAL confidence
    (the provider returns 0.9), not a hardcoded 1.0. Deterministic existence outcomes leave
    confidence unset (-> 1.0); a probabilistic groundedness verdict must carry the lens value."""
    engine, store = _engine(tmp_path, outcome="supported")  # provider returns confidence 0.9
    cits = [
        {"id": "c1", "claim": "LLMs cannot self-verify", "identifier": "2402.01817"},
    ]
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(
            side_effect=_arxiv_ok("A Paper", "We show LLMs cannot self-verify.")
        )
        result = await engine.verify(_request(cits))

    assert isinstance(result, VerifyResponse)
    assert result.verdict == Verdict.ACCEPT
    cr = result.citation_results[0]
    # The per-citation result carries the groundedness lens's parsed confidence (0.9), not 1.0.
    assert cr.confidence == pytest.approx(0.9)
    # And the artifact-level confidence reflects it (min over the projected results), not 1.0.
    assert result.confidence == pytest.approx(0.9)
    assert result.confidence != 1.0
    store.close()


async def test_fabricated_citation_refuses(tmp_path):
    engine, store = _engine(tmp_path)
    cits = [{"id": "bad", "claim": "a fabricated finding", "identifier": "2401.99999"}]
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(return_value=httpx.Response(200, text=_EMPTY))
        result = await engine.verify(_request(cits))

    assert isinstance(result, VerifyResponse)
    assert result.verdict == Verdict.REFUSE
    assert result.citation_results[0].existence == ExistenceOutcome.FABRICATED
    assert result.citation_results[0].action == "DROP"
    store.close()


async def test_numeric_mismatch_revises_before_lens(tmp_path):
    # The groundedness provider would say "supported", but the deterministic numeric guard
    # catches the 95.8% vs 89% swap FIRST and revises.
    engine, store = _engine(tmp_path, outcome="supported")
    cits = [
        {
            "id": "num",
            "claim": "the method reaches 95.8% accuracy",
            "identifier": "2402.01817",
            "title": "A Paper",
        }
    ]
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(
            side_effect=_arxiv_ok("A Paper", "Our method reaches 89% accuracy on the benchmark.")
        )
        result = await engine.verify(_request(cits))

    assert isinstance(result, VerifyResponse)
    assert result.verdict == Verdict.REVISE
    cr = result.citation_results[0]
    assert cr.finding_match.value == "contradicted"
    assert cr.action == "FIX TO MATCH SOURCE"
    store.close()


async def test_nli_floor_vetoes_supported_when_enabled(tmp_path, monkeypatch):
    # The LLM groundedness lens says "supported", but the opt-in orthogonal NLI floor refutes it,
    # so the verdict is downgraded to ESCALATE (the wave-10 veto), never a silent accept.
    import prism.core.engine as eng

    monkeypatch.setattr(eng, "nli_floor_enabled", lambda: True)
    monkeypatch.setattr(eng, "nli_groundedness", lambda claim, source: "refuted")
    engine, store = _engine(tmp_path, outcome="supported")
    cits = [{"id": "c1", "claim": "X holds", "identifier": "2402.01817", "title": "A Paper"}]
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(
            side_effect=_arxiv_ok("A Paper", "We show that X holds.")
        )
        result = await engine.verify(_request(cits))

    assert result.verdict == Verdict.ESCALATE
    cr = result.citation_results[0]
    assert cr.action == "VERIFY: ORTHOGONAL NLI DISAGREES"
    assert "NLI" in (cr.detail or "")
    store.close()


async def test_nli_floor_absent_keeps_accept(tmp_path, monkeypatch):
    # Floor enabled but the optional NLI extra is unavailable (None) -> the lens accept stands.
    import prism.core.engine as eng

    monkeypatch.setattr(eng, "nli_floor_enabled", lambda: True)
    monkeypatch.setattr(eng, "nli_groundedness", lambda claim, source: None)
    engine, store = _engine(tmp_path, outcome="supported")
    cits = [{"id": "c1", "claim": "X holds", "identifier": "2402.01817", "title": "A Paper"}]
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(
            side_effect=_arxiv_ok("A Paper", "We show that X holds.")
        )
        result = await engine.verify(_request(cits))

    assert result.verdict == Verdict.ACCEPT
    store.close()


async def test_oracle_down_escalates(tmp_path):
    engine, store = _engine(tmp_path)
    cits = [{"id": "down", "claim": "x holds", "identifier": "2402.01817"}]
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(return_value=httpx.Response(503))
        result = await engine.verify(_request(cits))

    assert isinstance(result, VerifyResponse)
    assert result.verdict == Verdict.ESCALATE
    assert result.citation_results[0].action == "RETRIEVE MANUALLY"
    store.close()


async def test_contradicted_by_lens_revises(tmp_path):
    engine, store = _engine(tmp_path, outcome="contradicted")
    cits = [
        {
            "id": "con",
            "claim": "a claim the source contradicts",
            "identifier": "2402.01817",
            "title": "A Paper",
        }
    ]
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(
            side_effect=_arxiv_ok("A Paper", "An abstract that discusses something else entirely.")
        )
        result = await engine.verify(_request(cits))

    assert isinstance(result, VerifyResponse)
    assert result.verdict == Verdict.REVISE
    assert result.citation_results[0].finding_match.value == "contradicted"
    store.close()


async def test_invalid_artifact_refused(tmp_path):
    engine, store = _engine(tmp_path)
    request = VerifyRequest(
        artifact=Artifact(type=ArtifactType.CITATIONS, content="not json at all"),
        intent="verify",
        caller=CallerContext(model_family=ModelFamily.ANTHROPIC, model_id="c"),
    )
    result = await engine.verify(request)
    assert isinstance(result, VerifyError)
    assert result.reason.value == "INVALID_ARTIFACT"
    store.close()
