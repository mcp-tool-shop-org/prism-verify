"""prism-on-prism meta-test — the EXTERNAL_VERIFIER 1->3 deliverable.

Verifies prism's OWN design-doc citations through the citation pipeline, with a DIFFERENT family
from the artifact author (caller=anthropic -> the router excludes anthropic) and retrieval-backed
existence (so the test checks RETRIEVAL, not the model's recall -> non-circular, per Naser 2026
arXiv:2603.03299 / Kambhampati 2024 arXiv:2402.01817). It asserts the metamorphic relations from
the v0.3 study-swarm Q3 (Cho 2025, arXiv:2511.02108):

  MR1  reordering authors / whitespace MUST NOT change the verdict (invariance)
  MR2  corrupting an identifier MUST flip existence resolve -> refuse
  MR3  a contradictory numeric swap MUST move the verdict off accept

These are oracle-free pass/fail relations on the pipeline — a genuine metamorphic/N-version test
rather than prism grading its own homework.
"""

from __future__ import annotations

import json
import re

import httpx
import respx

from prism.core.engine import VerificationEngine
from prism.core.routing import FamilyRouter
from prism.core.types import (
    Artifact,
    ArtifactType,
    CallerContext,
    ModelFamily,
    Verdict,
    VerifyRequest,
    VerifyResponse,
)
from prism.providers.base import CompletionRequest, CompletionResponse, ModelProvider
from prism.receipts.store import ReceiptStore
from prism.retrieval.oracle import CitationOracle

ARXIV = "http://export.arxiv.org/api/query"
_EMPTY = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'

# A representative subset of prism's OWN design-doc citations (real arXiv ids + faithful
# abstracts). The oracle is mocked to behave like live arXiv: these ids resolve, anything else
# returns an empty feed (-> fabricated), so a corrupted id is caught by RETRIEVAL, not recall.
DESIGN_CITATIONS = {
    "2402.01817": (
        "LLMs Can't Plan, But Can Help Planning in LLM-Modulo Frameworks",
        "Autoregressive LLMs cannot self-verify and must be paired with a sound external verifier.",
    ),
    "2310.01798": (
        "Large Language Models Cannot Self-Correct Reasoning Yet",
        "Self-correction without external feedback does not improve and can degrade reasoning.",
    ),
    "2511.16708": (
        "Multi-Agent Code Verification via Information Theory",
        "Four verifiers with low pairwise correlation beat any single one via submodular coverage.",
    ),
}


def _feed(title: str, summary: str) -> str:
    return (
        '<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
        "<id>http://arxiv.org/abs/x</id><published>2024-01-01T00:00:00Z</published>"
        f"<title>{title}</title><summary>{summary}</summary></entry></feed>"
    )


def _arxiv_router(request: httpx.Request) -> httpx.Response:
    """Mock arXiv: resolve known design-doc ids, empty feed (fabricated) for anything else."""
    ident = re.sub(r"v\d+$", "", request.url.params.get("id_list", ""))
    if ident in DESIGN_CITATIONS:
        title, summary = DESIGN_CITATIONS[ident]
        return httpx.Response(200, text=_feed(title, summary))
    return httpx.Response(200, text=_EMPTY)


class _DifferentFamilyVerifier(ModelProvider):
    """Stands in for a non-Anthropic groundedness verifier; always grounds (supported)."""

    @property
    def family(self) -> ModelFamily:
        return ModelFamily.LOCAL

    @property
    def available_models(self) -> list[str]:
        return ["mistral-small:24b"]

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        return CompletionResponse(
            content=json.dumps({"outcome": "supported", "confidence": 0.85}),
            model_id="mistral-small:24b",
            latency_ms=5,
        )

    async def health_check(self) -> bool:
        return True


def _meta_engine(tmp_path):
    router = FamilyRouter(
        routing_map={ModelFamily.ANTHROPIC: [(ModelFamily.LOCAL, "mistral-small:24b")]}
    )
    store = ReceiptStore(db_path=tmp_path / "meta.db", signing_secret=b"meta-secret")
    oracle = CitationOracle(client=httpx.AsyncClient(timeout=5.0))
    engine = VerificationEngine(
        providers={"local": _DifferentFamilyVerifier()},
        router=router,
        receipt_store=store,
        oracle=oracle,
    )
    return engine, store


def _request(citations: list[dict]) -> VerifyRequest:
    return VerifyRequest(
        artifact=Artifact(type=ArtifactType.CITATIONS, content=json.dumps(citations)),
        intent="verify each design-doc citation exists and the finding matches the source",
        caller=CallerContext(model_family=ModelFamily.ANTHROPIC, model_id="claude-opus"),
    )


async def test_meta_design_citations_resolve_via_different_family(tmp_path):
    engine, store = _meta_engine(tmp_path)
    cits = [
        {"id": k, "claim": f"the finding of {v[0]}", "identifier": k, "title": v[0]}
        for k, v in DESIGN_CITATIONS.items()
    ]
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(side_effect=_arxiv_router)
        result = await engine.verify(_request(cits))

    assert isinstance(result, VerifyResponse)
    assert result.verdict == Verdict.ACCEPT
    assert all(cr.existence.value == "resolved" for cr in result.citation_results)
    # The groundedness verifier is NOT the caller's (anthropic) family — EXTERNAL_VERIFIER.
    assert result.lens_results
    assert all(lr.model_family != "anthropic" for lr in result.lens_results)
    store.close()


async def test_meta_mr2_corrupting_identifier_flips_to_refuse(tmp_path):
    engine, store = _meta_engine(tmp_path)
    good_id, (title, _) = "2402.01817", DESIGN_CITATIONS["2402.01817"]
    corrupted = good_id[:-1] + ("8" if good_id[-1] != "8" else "7")  # mutate one digit
    cits = [{"id": "x", "claim": "the finding", "identifier": corrupted, "title": title}]
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(side_effect=_arxiv_router)
        result = await engine.verify(_request(cits))

    assert isinstance(result, VerifyResponse)
    assert result.verdict == Verdict.REFUSE  # MR2: existence flips resolve -> refuse
    assert result.citation_results[0].existence.value == "fabricated"
    store.close()


async def test_meta_mr3_numeric_swap_moves_off_accept(tmp_path):
    engine, store = _meta_engine(tmp_path)
    ident = "2511.16708"
    title = DESIGN_CITATIONS[ident][0]
    cits = [
        {"id": "n", "claim": "improves coverage by 95.8%", "identifier": ident, "title": title}
    ]
    # The source states a DIFFERENT percentage than the claim.
    source = _feed(title, "Submodular coverage improves recall by 30% over one verifier.")
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(return_value=httpx.Response(200, text=source))
        result = await engine.verify(_request(cits))

    assert isinstance(result, VerifyResponse)
    assert result.verdict == Verdict.REVISE  # MR3: numeric guard caught 95.8% vs 30%
    assert result.citation_results[0].finding_match.value == "contradicted"
    store.close()


async def test_meta_mr1_author_reorder_is_invariant(tmp_path):
    engine, store = _meta_engine(tmp_path)
    ident, (title, _) = "2402.01817", DESIGN_CITATIONS["2402.01817"]
    base = {
        "id": "a",
        "claim": "  llms cannot self-verify  ",
        "identifier": ident,
        "title": title,
        "authors": "Kambhampati et al.",
    }
    reordered = {**base, "authors": "et al. Kambhampati", "claim": "llms cannot self-verify"}
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(side_effect=_arxiv_router)
        r1 = await engine.verify(_request([base]))
        r2 = await engine.verify(_request([reordered]))

    assert isinstance(r1, VerifyResponse) and isinstance(r2, VerifyResponse)
    assert r1.verdict == r2.verdict  # MR1: invariant under author reorder / whitespace
    store.close()
