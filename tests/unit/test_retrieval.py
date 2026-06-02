"""Unit tests for the citation existence oracle (arXiv + Crossref) against respx mocks.

The load-bearing distinctions: an empty arXiv feed / Crossref 404 is FABRICATED (a refuse), but
a transient oracle failure (5xx) is UNRESOLVABLE (escalate) — never read as fabrication.
"""

from __future__ import annotations

import httpx
import respx

from prism.core.types import Citation, ExistenceOutcome
from prism.retrieval.oracle import CitationOracle

ARXIV = "https://export.arxiv.org/api/query"
CROSSREF = "https://api.crossref.org/works"

_RESOLVED_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2402.01817v1</id>
    <published>2024-02-02T00:00:00Z</published>
    <title>LLMs Cannot Self-Verify</title>
    <summary>Autoregressive LLMs cannot self-verify; pair with an external verifier.</summary>
  </entry>
</feed>"""

_EMPTY_FEED = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'


def _oracle() -> CitationOracle:
    return CitationOracle(client=httpx.AsyncClient(timeout=5.0), retry_delays=())


async def test_arxiv_resolved_carries_abstract():
    oracle = _oracle()
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(
            return_value=httpx.Response(200, text=_RESOLVED_FEED)
        )
        r = await oracle.resolve(
            Citation(claim="x", identifier="arXiv:2402.01817", title="LLMs Cannot Self-Verify")
        )
    assert r.outcome == ExistenceOutcome.RESOLVED
    assert "external verifier" in (r.source_abstract or "")
    assert r.source_sha256
    await oracle.aclose()


async def test_arxiv_empty_feed_is_fabricated():
    oracle = _oracle()
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(
            return_value=httpx.Response(200, text=_EMPTY_FEED)
        )
        r = await oracle.resolve(Citation(claim="x", identifier="2401.99999"))
    assert r.outcome == ExistenceOutcome.FABRICATED
    await oracle.aclose()


async def test_arxiv_title_mismatch_is_metadata_mismatch():
    oracle = _oracle()
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(
            return_value=httpx.Response(200, text=_RESOLVED_FEED)
        )
        r = await oracle.resolve(
            Citation(claim="x", identifier="2402.01817", title="An unrelated paper on tomatoes")
        )
    assert r.outcome == ExistenceOutcome.METADATA_MISMATCH
    await oracle.aclose()


async def test_oracle_down_is_unresolvable_not_fabricated():
    oracle = _oracle()
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(return_value=httpx.Response(503))
        r = await oracle.resolve(Citation(claim="x", identifier="2402.01817"))
    assert r.outcome == ExistenceOutcome.UNRESOLVABLE  # NOT fabricated
    await oracle.aclose()


async def test_crossref_doi_resolved():
    oracle = _oracle()
    body = {"message": {"title": ["A Real Paper"], "abstract": "<p>We show that things work.</p>"}}
    with respx.mock:
        respx.get(url__startswith=CROSSREF).mock(return_value=httpx.Response(200, json=body))
        r = await oracle.resolve(
            Citation(claim="x", identifier="10.1234/abcd", title="A Real Paper")
        )
    assert r.outcome == ExistenceOutcome.RESOLVED
    assert "things work" in (r.source_abstract or "")
    await oracle.aclose()


async def test_crossref_404_is_fabricated():
    oracle = _oracle()
    with respx.mock:
        respx.get(url__startswith=CROSSREF).mock(return_value=httpx.Response(404))
        r = await oracle.resolve(Citation(claim="x", identifier="10.9999/nope"))
    assert r.outcome == ExistenceOutcome.FABRICATED
    await oracle.aclose()


async def test_no_identifier_is_unresolvable():
    oracle = _oracle()
    r = await oracle.resolve(Citation(claim="x", title="Some paper", identifier=None))
    assert r.outcome == ExistenceOutcome.UNRESOLVABLE
    await oracle.aclose()


async def test_non_arxiv_non_doi_identifier_unresolvable():
    oracle = _oracle()
    r = await oracle.resolve(Citation(claim="x", identifier="not-an-id"))
    assert r.outcome == ExistenceOutcome.UNRESOLVABLE
    await oracle.aclose()


async def test_arxiv_timeout_is_unresolvable_not_fabricated():
    oracle = _oracle()
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(side_effect=httpx.ConnectTimeout("slow"))
        r = await oracle.resolve(Citation(claim="x", identifier="2402.01817"))
    assert r.outcome == ExistenceOutcome.UNRESOLVABLE
    await oracle.aclose()


async def test_crossref_transient_5xx_is_unresolvable_not_fabricated():
    oracle = _oracle()
    with respx.mock:
        respx.get(url__startswith=CROSSREF).mock(return_value=httpx.Response(503))
        r = await oracle.resolve(Citation(claim="x", identifier="10.1234/abcd"))
    assert r.outcome == ExistenceOutcome.UNRESOLVABLE  # outage != fabrication
    await oracle.aclose()


async def test_crossref_429_is_unresolvable():
    oracle = _oracle()
    with respx.mock:
        respx.get(url__startswith=CROSSREF).mock(return_value=httpx.Response(429))
        r = await oracle.resolve(Citation(claim="x", identifier="10.1234/abcd"))
    assert r.outcome == ExistenceOutcome.UNRESOLVABLE
    await oracle.aclose()


async def test_crossref_unparseable_body_is_unresolvable():
    oracle = _oracle()
    with respx.mock:
        respx.get(url__startswith=CROSSREF).mock(return_value=httpx.Response(200, text="not json"))
        r = await oracle.resolve(Citation(claim="x", identifier="10.1234/abcd"))
    assert r.outcome == ExistenceOutcome.UNRESOLVABLE
    await oracle.aclose()


async def test_cache_recomputes_title_match_per_citation():
    # Regression: the cache holds the title-INDEPENDENT record; the RESOLVED-vs-METADATA_MISMATCH
    # decision is recomputed per citation, so a repeated id with a wrong title cannot inherit a
    # sibling's RESOLVED verdict.
    oracle = _oracle()
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(
            return_value=httpx.Response(200, text=_RESOLVED_FEED)
        )
        r1 = await oracle.resolve(
            Citation(claim="x", identifier="2402.01817", title="LLMs Cannot Self-Verify")
        )
        r2 = await oracle.resolve(
            Citation(claim="x", identifier="2402.01817", title="An unrelated paper on tomatoes")
        )
    assert r1.outcome == ExistenceOutcome.RESOLVED
    assert r2.outcome == ExistenceOutcome.METADATA_MISMATCH  # NOT inherited from r1
    await oracle.aclose()


async def test_doi_path_traversal_is_rejected_without_a_request():
    # '10.1234/../../admin' would otherwise steer httpx to /admin; reject before any request.
    oracle = _oracle()
    r = await oracle.resolve(Citation(claim="x", identifier="10.1234/../../../admin"))
    assert r.outcome == ExistenceOutcome.UNRESOLVABLE
    assert "traversal" in r.detail.lower()
    await oracle.aclose()


async def test_doi_pin_query_is_the_actual_request_url():
    # The signed pin must record the URL httpx actually issued (mailto via params=, not f-string),
    # so an auditor replaying the pin sees the real request.
    oracle = _oracle()
    captured: dict[str, str] = {}

    def _cap(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"message": {"title": ["A Paper"]}})

    with respx.mock:
        respx.get(url__startswith=CROSSREF).mock(side_effect=_cap)
        r = await oracle.resolve(
            Citation(claim="x", identifier="10.1234/abcd", title="A Paper")
        )
    assert r.outcome == ExistenceOutcome.RESOLVED
    assert r.query == captured["url"]
    assert "mailto=" in r.query
    await oracle.aclose()


async def test_arxiv_retries_then_resolves_on_transient_429():
    # arXiv rate-limits anonymous bursts with 429; a transient 429 must retry, not escalate.
    oracle = CitationOracle(client=httpx.AsyncClient(timeout=5.0), retry_delays=(0.0, 0.0))
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(
            side_effect=[httpx.Response(429), httpx.Response(200, text=_RESOLVED_FEED)]
        )
        r = await oracle.resolve(
            Citation(claim="x", identifier="2402.01817", title="LLMs Cannot Self-Verify")
        )
    assert r.outcome == ExistenceOutcome.RESOLVED  # 429 retried -> 200
    await oracle.aclose()
