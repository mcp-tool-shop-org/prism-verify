"""Citation existence oracle — deterministic retrieval (arXiv-ID-first, then DOI).

Stage 1 of citation verification. This is the SOUND verifier (Kambhampati 2024,
arXiv:2402.01817): existence is decided by LIVE retrieval against arXiv / Crossref, never by a
model's parametric recall (which fabricates 11-57% of citations, Naser 2026 arXiv:2603.03299).
Read-only and external — a GET, no writes — so it has no compensator (design/03). Precision-
biased: a fuzzy-only or transient outcome downgrades to UNRESOLVABLE (CANNOT_CONFIRM), never
upgrades a non-resolving citation to RESOLVED, and an oracle-down is never read as FABRICATED.

The per-identifier cache holds only the TITLE-INDEPENDENT retrieval record (the retrieved
title/abstract/hash and whether the id was found); the RESOLVED-vs-METADATA_MISMATCH decision is
title-dependent and is recomputed against each citation's own claimed title, so a repeated id with
a different claimed title cannot inherit a sibling's verdict.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from xml.etree import ElementTree as ET

import httpx

from prism.core.types import Citation, ExistenceOutcome

ARXIV_BASE = "https://export.arxiv.org/api/query"
CROSSREF_BASE = "https://api.crossref.org/works"
DEFAULT_MAILTO = "verify@prism-verify.dev"
# Cap the upstream body we will parse. A compromised / redirected upstream could otherwise stream
# an unbounded body and OOM the verifier (ET.fromstring / resp.json parse the FULL body). 5 MiB is
# far above any real arXiv Atom feed or Crossref work record; over it -> UNRESOLVABLE, not
# FABRICATED.
DEFAULT_MAX_BODY_BYTES = 5 * 1024 * 1024
# arXiv 301-redirects http -> https and rate-limits anonymous bursts; use https directly and
# identify ourselves (arXiv asks API clients to send a descriptive User-Agent).
_USER_AGENT = "prism-verify (citation verifier; +https://github.com/mcp-tool-shop-org/prism-verify)"

_ATOM = "{http://www.w3.org/2005/Atom}"

# arXiv id forms: new (2401.01234 / 2401.01234v2) and old (cond-mat/0207270).
_ARXIV_NEW = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
_ARXIV_OLD = re.compile(r"^[a-z-]+(\.[A-Z]{2})?/\d{7}(v\d+)?$")
# DOI: forbid whitespace / '?' / '#' in the suffix so it cannot inject a query or fragment into
# the request URL; a '..' traversal segment is rejected separately in _resolve_crossref.
_DOI = re.compile(r"^10\.\d{4,9}/[^\s?#]+$")


@dataclass
class ExistenceResult:
    """Outcome of resolving one citation against the retrieval oracle."""

    outcome: ExistenceOutcome
    query: str
    detail: str
    source_title: str | None = None
    source_abstract: str | None = None
    source_sha256: str | None = None


@dataclass
class _Record:
    """Title-INDEPENDENT retrieval record — safe to cache by identifier alone."""

    status: str  # "found" | "fabricated" | "unresolvable"
    query: str
    detail: str
    title: str | None = None
    abstract: str | None = None
    sha256: str | None = None


def _norm_id(identifier: str) -> str:
    s = identifier.strip()
    if s.lower().startswith("arxiv:"):
        s = s[len("arxiv:") :]
    return s.strip()


def _norm_words(text: str) -> set[str]:
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", text.lower()).split() if len(w) > 2}


def _titles_match(claimed: str, retrieved: str) -> bool:
    """Lenient title-identity gate: token-Jaccard >= 0.5 (or no claimed title to check)."""
    if not claimed.strip():
        return True  # ID resolution alone is enough when no title was provided
    a, b = _norm_words(claimed), _norm_words(retrieved)
    if not a or not b:
        return True
    return len(a & b) / len(a | b) >= 0.5


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _arxiv_id_core(value: str) -> str:
    """Normalize an arXiv id for comparison: drop URL prefix, an ``arXiv:`` scheme, and a ``vN``
    version suffix, lower-cased. ``http://arxiv.org/abs/2402.01817v1`` and ``2402.01817`` both
    normalize to ``2402.01817`` so a returned <id> can be matched against the requested id."""
    s = value.strip().lower()
    # Strip a URL prefix like http(s)://arxiv.org/abs/ — keep only the id tail after the last '/'
    # UNLESS this is an old-style id (e.g. cond-mat/0207270), whose '/' is part of the id itself.
    if "://" in s:
        s = s.split("://", 1)[1]
        if s.startswith("arxiv.org/abs/"):
            s = s[len("arxiv.org/abs/") :]
    if s.startswith("arxiv:"):
        s = s[len("arxiv:") :]
    # Drop a trailing version suffix vN (arXiv ids may or may not carry one).
    s = re.sub(r"v\d+$", "", s)
    return s.strip()


class CitationOracle:
    """Resolves citations against arXiv (ID-first) and Crossref (DOI-second)."""

    def __init__(
        self,
        *,
        arxiv_base: str = ARXIV_BASE,
        crossref_base: str = CROSSREF_BASE,
        mailto: str = DEFAULT_MAILTO,
        client: httpx.AsyncClient | None = None,
        retry_delays: tuple[float, ...] = (1.0, 3.0),
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    ) -> None:
        self._arxiv_base = arxiv_base
        self._crossref_base = crossref_base.rstrip("/")
        self._mailto = mailto
        self._retry_delays = retry_delays
        self._max_body_bytes = max_body_bytes
        # follow_redirects=False (SSRF-adjacent hardening): an upstream 3xx could otherwise steer
        # prism's GET to an arbitrary host. Both base URLs are already https (arXiv's historical
        # http->https 301 is moot now we hit https://export.arxiv.org directly), so a redirect from
        # these endpoints is anomalous and we treat any 3xx as UNRESOLVABLE rather than chase it.
        self._client = client or httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=False,
            headers={"User-Agent": _USER_AGENT},
        )
        self._cache: dict[str, _Record] = {}

    async def _get(self, url: str, params: dict[str, str]) -> httpx.Response:
        """GET with light retry on transient rate-limit / 5xx (arXiv asks ~3s between calls)."""
        resp = await self._client.get(url, params=params)
        for delay in self._retry_delays:
            if resp.status_code not in (429, 500, 502, 503):
                return resp
            await asyncio.sleep(delay)
            resp = await self._client.get(url, params=params)
        return resp

    def _oversize_detail(self, resp: httpx.Response) -> str | None:
        """Return a detail string if the response body exceeds the body-size cap, else None.

        Checks the advertised Content-Length first (cheap, lets us refuse before materializing the
        body), then the actual byte length of the materialized body (a lying / chunked upstream can
        omit Content-Length). httpx has already buffered ``resp.content`` for a non-streamed GET, so
        reading its length does not issue extra network I/O."""
        advertised = resp.headers.get("content-length")
        if advertised is not None:
            try:
                if int(advertised) > self._max_body_bytes:
                    return f"upstream body too large ({advertised} bytes > {self._max_body_bytes})"
            except ValueError:
                pass  # unparseable header -> fall through to the actual-length check
        if len(resp.content) > self._max_body_bytes:
            return f"upstream body too large ({len(resp.content)} bytes > {self._max_body_bytes})"
        return None

    async def resolve(self, citation: Citation) -> ExistenceResult:
        ident = (citation.identifier or "").strip()
        if not ident:
            return ExistenceResult(
                outcome=ExistenceOutcome.UNRESOLVABLE,
                query="",
                detail="no identifier (arXiv id or DOI); title-only is a fuzzy lower-trust tier",
            )
        norm = _norm_id(ident)
        record = self._cache.get(norm)
        if record is None:
            if _ARXIV_NEW.match(norm) or _ARXIV_OLD.match(norm):
                record = await self._resolve_arxiv(norm)
            elif _DOI.match(norm):
                record = await self._resolve_crossref(norm)
            else:
                record = _Record(
                    "unresolvable", "", f"identifier {norm!r} is neither an arXiv id nor a DOI"
                )
            self._cache[norm] = record
        # The title-match decision is recomputed per citation (NOT cached).
        return self._finalize(record, citation.title)

    def _finalize(self, record: _Record, claimed_title: str) -> ExistenceResult:
        if record.status == "fabricated":
            return ExistenceResult(ExistenceOutcome.FABRICATED, record.query, record.detail)
        if record.status == "unresolvable":
            return ExistenceResult(ExistenceOutcome.UNRESOLVABLE, record.query, record.detail)
        if _titles_match(claimed_title, record.title or ""):
            return ExistenceResult(
                ExistenceOutcome.RESOLVED,
                record.query,
                record.detail,
                source_title=record.title,
                source_abstract=record.abstract,
                source_sha256=record.sha256,
            )
        return ExistenceResult(
            ExistenceOutcome.METADATA_MISMATCH,
            record.query,
            f"resolved, but to a different title than cited: {record.title!r}",
            source_title=record.title,
            source_abstract=record.abstract,
            source_sha256=record.sha256,
        )

    async def _resolve_arxiv(self, arxiv_id: str) -> _Record:
        intended = f"{self._arxiv_base}?id_list={arxiv_id}"
        try:
            resp = await self._get(self._arxiv_base, {"id_list": arxiv_id})
        except httpx.HTTPError as e:
            return _Record(
                "unresolvable", intended, f"arXiv oracle unreachable: {type(e).__name__}"
            )
        query = str(resp.request.url)
        # follow_redirects=False: a 3xx is not chased (SSRF-adjacent). The base URL is https, so a
        # redirect from it is anomalous -> escalate, never read it as a fabrication.
        if resp.is_redirect:
            return _Record("unresolvable", query, f"arXiv returned a redirect ({resp.status_code})")
        try:
            resp.raise_for_status()
        except httpx.HTTPError as e:
            return _Record("unresolvable", query, f"arXiv oracle unreachable: {type(e).__name__}")
        oversize = self._oversize_detail(resp)
        if oversize is not None:
            return _Record("unresolvable", query, oversize)
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError:
            return _Record("unresolvable", query, "arXiv returned an unparseable feed")
        # A bad id yields a single error <entry> with no <published>; require a real entry.
        real = [
            e
            for e in root.findall(f"{_ATOM}entry")
            if e.find(f"{_ATOM}published") is not None
        ]
        if not real:
            return _Record("fabricated", query, f"arXiv has no record for id {arxiv_id}")
        # Defense-in-depth (do NOT trust id_list semantics alone): verify a real entry's <id>
        # normalizes to the requested id. If arXiv ever returned a nearest/normalized match, a
        # fabricated id could otherwise flip FABRICATED -> RESOLVED. No match -> FABRICATED.
        want = _arxiv_id_core(arxiv_id)
        match = next(
            (e for e in real if _arxiv_id_core(e.findtext(f"{_ATOM}id") or "") == want),
            None,
        )
        if match is None:
            return _Record(
                "fabricated", query,
                f"arXiv returned an entry whose id does not match requested {arxiv_id}",
            )
        title = (match.findtext(f"{_ATOM}title") or "").strip()
        abstract = (match.findtext(f"{_ATOM}summary") or "").strip()
        source = f"{title}\n\n{abstract}".strip()
        return _Record(
            "found", query, f"arXiv id {arxiv_id} resolved",
            title=title or None, abstract=abstract or None,
            sha256=_sha256(source) if source else None,
        )

    async def _resolve_crossref(self, doi: str) -> _Record:
        # Reject path-traversal: httpx collapses '..' segments, which would steer the GET to a
        # different path than the signed pin records. The DOI's own '/' separators are fine.
        if ".." in doi:
            return _Record("unresolvable", "", f"DOI {doi!r} contains a path-traversal segment")
        intended = f"{self._crossref_base}/{doi}"
        try:
            # mailto travels as a real query param (not f-string concatenation), so an
            # attacker-shaped identifier cannot shadow or inject query parameters.
            resp = await self._get(intended, {"mailto": self._mailto})
        except httpx.HTTPError as e:
            return _Record(
                "unresolvable",
                f"{intended}?mailto={self._mailto}",
                f"Crossref oracle unreachable: {type(e).__name__}",
            )
        query = str(resp.request.url)  # the URL actually issued — what the pin should record
        # follow_redirects=False: a 3xx could otherwise steer the GET to an arbitrary host
        # (SSRF-adjacent). The base URL is https, so a redirect from it is anomalous -> escalate.
        if resp.is_redirect:
            return _Record(
                "unresolvable", query, f"Crossref returned a redirect ({resp.status_code})"
            )
        if resp.status_code == 404:
            return _Record("fabricated", query, f"Crossref has no record for DOI {doi}")
        oversize = self._oversize_detail(resp)
        if oversize is not None:
            return _Record("unresolvable", query, oversize)
        try:
            resp.raise_for_status()
            message = resp.json().get("message", {})
        except (httpx.HTTPError, ValueError):
            return _Record(
                "unresolvable", query, "Crossref oracle returned an error / unparseable response"
            )
        titles = message.get("title") or []
        title = str(titles[0]).strip() if titles else ""
        abstract = re.sub(r"<[^>]+>", "", str(message.get("abstract", "") or "")).strip()
        source = f"{title}\n\n{abstract}".strip()
        return _Record(
            "found", query, f"DOI {doi} resolved",
            title=title or None, abstract=abstract or None,
            sha256=_sha256(source) if source else None,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
