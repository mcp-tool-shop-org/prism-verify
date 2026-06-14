"""Dedicated unit tests for the citation oracle's load-bearing anti-injection / SSRF guards.

These exercise the guards directly (each test fails if its guard is removed), separate from the
happy-path coverage in test_retrieval.py. Covered: DOI path-traversal reject, the _DOI regex's
query/fragment/whitespace reject, arXiv-vs-DOI dispatch, fabricated arXiv id -> FABRICATED, the
returned-id match guard (SEC-A-002), the mailto-as-query-param guard, oversized-body ->
UNRESOLVABLE (SEC-A-003), and redirect -> UNRESOLVABLE (SEC-A-004).
"""

from __future__ import annotations

import httpx
import respx

from prism.core.types import Citation, ExistenceOutcome
from prism.retrieval.oracle import _DOI, CitationOracle

ARXIV = "https://export.arxiv.org/api/query"
CROSSREF = "https://api.crossref.org/works"

# A real, resolvable arXiv entry whose <id> normalizes to 2402.01817 (matches the requested id).
_FEED_2402 = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2402.01817v1</id>
    <published>2024-02-02T00:00:00Z</published>
    <title>LLMs Cannot Self-Verify</title>
    <summary>Pair an autoregressive LLM with an external verifier.</summary>
  </entry>
</feed>"""

# A well-formed entry that RESOLVES, but whose <id> is a DIFFERENT paper than the one requested.
# arXiv's id_list should never do this, but if it ever returned a nearest match this is the attack.
_FEED_WRONG_ID = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <published>2024-01-01T00:00:00Z</published>
    <title>A Completely Different Paper</title>
    <summary>Unrelated content.</summary>
  </entry>
</feed>"""

# A single arXiv error entry (no <published>) — what a genuinely fabricated id yields.
_FEED_ERROR_ONLY = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/api/errors#incorrect_id_format_for_99999</id>
    <title>Error</title>
    <summary>incorrect id format</summary>
  </entry>
</feed>"""


def _oracle(*, max_body_bytes: int | None = None) -> CitationOracle:
    kw: dict[str, int] = {} if max_body_bytes is None else {"max_body_bytes": max_body_bytes}
    return CitationOracle(client=httpx.AsyncClient(timeout=5.0), retry_delays=(), **kw)


# --- _DOI regex: query / fragment / whitespace injection reject ----------------------------------


def test_doi_regex_rejects_query_fragment_and_whitespace() -> None:
    # The _DOI regex is the gate that keeps a malicious identifier from injecting a query (?) or
    # fragment (#) into the request URL, or smuggling whitespace. Each must fail to match.
    assert _DOI.match("10.1234/valid-suffix") is not None  # a clean DOI matches
    assert _DOI.match("10.1234/abc?evil=1") is None  # '?' would start a query
    assert _DOI.match("10.1234/abc#frag") is None  # '#' would start a fragment
    assert _DOI.match("10.1234/abc def") is None  # embedded space
    assert _DOI.match("10.1234/abc\tdef") is None  # embedded tab
    assert _DOI.match("10.1234/abc\ndef") is None  # embedded newline


async def test_doi_with_query_injection_is_unresolvable() -> None:
    # End-to-end: an identifier carrying a '?' does not match _DOI (nor arXiv), so it is classified
    # as neither-an-id and routed to UNRESOLVABLE — no request is issued with an injected query.
    oracle = _oracle()
    r = await oracle.resolve(Citation(claim="x", identifier="10.1234/abc?mailto=attacker@evil"))
    assert r.outcome == ExistenceOutcome.UNRESOLVABLE
    await oracle.aclose()


# --- DOI path-traversal reject (no request issued) -----------------------------------------------


async def test_doi_path_traversal_is_rejected_before_any_request() -> None:
    oracle = _oracle()
    with respx.mock:
        route = respx.get(url__startswith=CROSSREF).mock(return_value=httpx.Response(200))
        r = await oracle.resolve(Citation(claim="x", identifier="10.1234/../../../admin"))
    assert r.outcome == ExistenceOutcome.UNRESOLVABLE
    assert "traversal" in r.detail.lower()
    assert route.call_count == 0  # the guard must short-circuit BEFORE any network call
    await oracle.aclose()


# --- arXiv-vs-DOI dispatch routes correctly ------------------------------------------------------


async def test_dispatch_arxiv_id_hits_arxiv_not_crossref() -> None:
    oracle = _oracle()
    with respx.mock:
        ax = respx.get(url__startswith=ARXIV).mock(
            return_value=httpx.Response(200, text=_FEED_2402)
        )
        cr = respx.get(url__startswith=CROSSREF).mock(return_value=httpx.Response(200, json={}))
        r = await oracle.resolve(
            Citation(claim="x", identifier="2402.01817", title="LLMs Cannot Self-Verify")
        )
    assert r.outcome == ExistenceOutcome.RESOLVED
    assert ax.call_count == 1
    assert cr.call_count == 0  # an arXiv id must NOT be routed to Crossref
    await oracle.aclose()


async def test_dispatch_doi_hits_crossref_not_arxiv() -> None:
    oracle = _oracle()
    body = {"message": {"title": ["A Real Paper"]}}
    with respx.mock:
        ax = respx.get(url__startswith=ARXIV).mock(
            return_value=httpx.Response(200, text=_FEED_2402)
        )
        cr = respx.get(url__startswith=CROSSREF).mock(return_value=httpx.Response(200, json=body))
        r = await oracle.resolve(
            Citation(claim="x", identifier="10.1234/abcd", title="A Real Paper")
        )
    assert r.outcome == ExistenceOutcome.RESOLVED
    assert cr.call_count == 1
    assert ax.call_count == 0  # a DOI must NOT be routed to arXiv
    await oracle.aclose()


# --- fabricated arXiv id (error-only feed) -> FABRICATED ------------------------------------------


async def test_fabricated_arxiv_id_error_feed_is_fabricated() -> None:
    oracle = _oracle()
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(
            return_value=httpx.Response(200, text=_FEED_ERROR_ONLY)
        )
        r = await oracle.resolve(Citation(claim="x", identifier="9999.99999"))
    assert r.outcome == ExistenceOutcome.FABRICATED  # error-only feed != a resolved record
    await oracle.aclose()


# --- SEC-A-002: returned-id must match the requested id ------------------------------------------


async def test_arxiv_returned_id_mismatch_is_fabricated() -> None:
    # Defense-in-depth: even a well-formed RESOLVING entry must be REJECTED if its <id> is not the
    # id we asked for. Without this guard a nearest/normalized arXiv match flips FABRICATED ->
    # RESOLVED. Requested 2402.01817, feed returns 2401.00001 -> FABRICATED.
    oracle = _oracle()
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(
            return_value=httpx.Response(200, text=_FEED_WRONG_ID)
        )
        r = await oracle.resolve(
            Citation(claim="x", identifier="2402.01817", title="LLMs Cannot Self-Verify")
        )
    assert r.outcome == ExistenceOutcome.FABRICATED
    assert "does not match" in r.detail.lower()
    await oracle.aclose()


async def test_arxiv_returned_id_match_ignores_version_suffix() -> None:
    # The match must normalize away the vN version suffix: requesting the un-versioned id must
    # accept a returned v1 entry (and vice versa). This guards against the match guard being too
    # strict and rejecting legitimate resolutions.
    oracle = _oracle()
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(return_value=httpx.Response(200, text=_FEED_2402))
        r = await oracle.resolve(
            Citation(claim="x", identifier="2402.01817v3", title="LLMs Cannot Self-Verify")
        )
    assert r.outcome == ExistenceOutcome.RESOLVED  # v3 requested, v1 returned -> still a match
    await oracle.aclose()


# --- mailto travels as a query param, not f-string concatenation ---------------------------------


async def test_mailto_travels_as_query_param() -> None:
    # The mailto must be a real query parameter on the request URL (httpx-encoded), so an
    # attacker-shaped DOI cannot shadow or inject it. The recorded pin URL is the URL httpx issued.
    oracle = CitationOracle(
        client=httpx.AsyncClient(timeout=5.0), retry_delays=(), mailto="probe@prism.test"
    )
    captured: dict[str, str] = {}

    def _cap(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["mailto"] = request.url.params.get("mailto", "")
        return httpx.Response(200, json={"message": {"title": ["A Paper"]}})

    with respx.mock:
        respx.get(url__startswith=CROSSREF).mock(side_effect=_cap)
        r = await oracle.resolve(Citation(claim="x", identifier="10.1234/abcd", title="A Paper"))
    assert r.outcome == ExistenceOutcome.RESOLVED
    assert captured["mailto"] == "probe@prism.test"  # parsed as a discrete query param
    assert r.query == captured["url"]  # the pin records the actual issued URL
    await oracle.aclose()


# --- SEC-A-003: oversized response body -> UNRESOLVABLE -------------------------------------------


async def test_arxiv_oversized_body_is_unresolvable() -> None:
    oracle = _oracle(max_body_bytes=1024)
    big = "<feed xmlns='http://www.w3.org/2005/Atom'>" + ("x" * 5000) + "</feed>"
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(return_value=httpx.Response(200, text=big))
        r = await oracle.resolve(Citation(claim="x", identifier="2402.01817"))
    assert r.outcome == ExistenceOutcome.UNRESOLVABLE  # not parsed, not FABRICATED
    assert "too large" in r.detail.lower()
    await oracle.aclose()


async def test_crossref_oversized_body_is_unresolvable() -> None:
    oracle = _oracle(max_body_bytes=1024)
    big = '{"message": {"title": ["' + ("x" * 5000) + '"]}}'
    with respx.mock:
        respx.get(url__startswith=CROSSREF).mock(return_value=httpx.Response(200, text=big))
        r = await oracle.resolve(Citation(claim="x", identifier="10.1234/abcd"))
    assert r.outcome == ExistenceOutcome.UNRESOLVABLE
    assert "too large" in r.detail.lower()
    await oracle.aclose()


async def test_oversized_via_content_length_header_is_unresolvable() -> None:
    # A lying / hostile upstream may advertise a huge Content-Length; refuse on the header too.
    oracle = _oracle(max_body_bytes=1024)
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(
            return_value=httpx.Response(
                200, text="<feed/>", headers={"content-length": "999999999"}
            )
        )
        r = await oracle.resolve(Citation(claim="x", identifier="2402.01817"))
    assert r.outcome == ExistenceOutcome.UNRESOLVABLE
    assert "too large" in r.detail.lower()
    await oracle.aclose()


# --- SEC-A-004: an upstream redirect is not chased -> UNRESOLVABLE --------------------------------


async def test_arxiv_redirect_is_unresolvable_not_chased() -> None:
    # follow_redirects=False: a 3xx pointing at an arbitrary host must NOT be followed (SSRF). A
    # redirect from the https base is anomalous -> escalate (UNRESOLVABLE), never FABRICATED.
    oracle = _oracle()
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(
            return_value=httpx.Response(302, headers={"location": "https://evil.example/x"})
        )
        r = await oracle.resolve(Citation(claim="x", identifier="2402.01817"))
    assert r.outcome == ExistenceOutcome.UNRESOLVABLE
    assert "redirect" in r.detail.lower()
    await oracle.aclose()


async def test_crossref_redirect_is_unresolvable_not_chased() -> None:
    oracle = _oracle()
    with respx.mock:
        respx.get(url__startswith=CROSSREF).mock(
            return_value=httpx.Response(301, headers={"location": "https://evil.example/x"})
        )
        r = await oracle.resolve(Citation(claim="x", identifier="10.1234/abcd"))
    assert r.outcome == ExistenceOutcome.UNRESOLVABLE
    assert "redirect" in r.detail.lower()
    await oracle.aclose()


# --- EVS-B-007: cache TTL (no stale-serve) + cache bound (no unbounded growth) -------------------


async def test_cache_entry_past_ttl_is_refetched_not_served_stale() -> None:
    # A RESOLVED record cached at t0 must NOT be served forever: once an entry is older than the
    # TTL, the next resolve re-fetches it (a long-lived process never freezes on a stale verdict).
    clock = [1000.0]
    oracle = CitationOracle(
        client=httpx.AsyncClient(timeout=5.0),
        retry_delays=(),
        cache_ttl=60.0,
        clock=lambda: clock[0],
    )
    with respx.mock:
        route = respx.get(url__startswith=ARXIV).mock(
            return_value=httpx.Response(200, text=_FEED_2402)
        )
        cite = Citation(claim="x", identifier="2402.01817", title="LLMs Cannot Self-Verify")
        r1 = await oracle.resolve(cite)
        assert r1.outcome == ExistenceOutcome.RESOLVED
        assert route.call_count == 1

        # Within the TTL -> served from cache, no second network call.
        clock[0] += 30.0
        r2 = await oracle.resolve(cite)
        assert r2.outcome == ExistenceOutcome.RESOLVED
        assert route.call_count == 1  # still cached

        # Past the TTL -> the stale entry expires and is re-fetched.
        clock[0] += 31.0  # now 61s after t0 > 60s TTL
        r3 = await oracle.resolve(cite)
        assert r3.outcome == ExistenceOutcome.RESOLVED
        assert route.call_count == 2  # re-fetched, NOT served stale
    await oracle.aclose()


async def test_cache_stays_bounded_under_many_distinct_ids() -> None:
    # An unbounded per-instance cache grows without limit over a long-lived process. With a bound
    # of N, resolving many distinct ids must keep the live cache at or below N entries.
    oracle = CitationOracle(
        client=httpx.AsyncClient(timeout=5.0),
        retry_delays=(),
        cache_max=8,
    )
    with respx.mock:
        respx.get(url__startswith=ARXIV).mock(return_value=httpx.Response(200, text=_FEED_2402))
        for i in range(50):
            # 50 distinct (well-formed) arXiv ids -> 50 distinct cache keys.
            await oracle.resolve(Citation(claim="x", identifier=f"2401.{i:05d}"))
    assert oracle.cache_size <= 8  # bounded, not 50
    await oracle.aclose()


async def test_cache_evicts_oldest_first_when_bound_exceeded() -> None:
    # LRU-ish bound: inserting past the cap evicts the OLDEST entry, so the most-recent distinct
    # ids remain cached. After overflowing the cap, the first-inserted id must be gone.
    oracle = CitationOracle(
        client=httpx.AsyncClient(timeout=5.0),
        retry_delays=(),
        cache_max=2,
    )
    with respx.mock:
        route = respx.get(url__startswith=ARXIV).mock(
            return_value=httpx.Response(200, text=_FEED_2402)
        )
        await oracle.resolve(Citation(claim="x", identifier="2401.00001"))  # insert A
        await oracle.resolve(Citation(claim="x", identifier="2401.00002"))  # insert B (cache: A,B)
        await oracle.resolve(Citation(claim="x", identifier="2401.00003"))  # insert C -> evict A
        assert oracle.cache_size == 2
        before = route.call_count
        # A was evicted -> resolving it again re-fetches (one more network call).
        await oracle.resolve(Citation(claim="x", identifier="2401.00001"))
        assert route.call_count == before + 1
    await oracle.aclose()
