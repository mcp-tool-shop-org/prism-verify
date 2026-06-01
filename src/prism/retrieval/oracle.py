"""Citation existence oracle — deterministic retrieval (arXiv-ID-first, then DOI).

Stage 1 of citation verification. This is the SOUND verifier (Kambhampati 2024,
arXiv:2402.01817): existence is decided by LIVE retrieval against arXiv / Crossref, never by a
model's parametric recall (which fabricates 11-57% of citations, Naser 2026 arXiv:2603.03299).
Read-only and external — a GET, no writes — so it has no compensator (design/03). Precision-
biased: a fuzzy-only or transient outcome downgrades to UNRESOLVABLE (CANNOT_CONFIRM), never
upgrades a non-resolving citation to RESOLVED, and an oracle-down is never read as FABRICATED.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from xml.etree import ElementTree as ET

import httpx

from prism.core.types import Citation, ExistenceOutcome

ARXIV_BASE = "http://export.arxiv.org/api/query"
CROSSREF_BASE = "https://api.crossref.org/works"
DEFAULT_MAILTO = "verify@prism-verify.dev"

_ATOM = "{http://www.w3.org/2005/Atom}"

# arXiv id forms: new (2401.01234 / 2401.01234v2) and old (cond-mat/0207270).
_ARXIV_NEW = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
_ARXIV_OLD = re.compile(r"^[a-z-]+(\.[A-Z]{2})?/\d{7}(v\d+)?$")
_DOI = re.compile(r"^10\.\d{4,9}/\S+$")


@dataclass
class ExistenceResult:
    """Outcome of resolving one citation against the retrieval oracle."""

    outcome: ExistenceOutcome
    query: str
    detail: str
    source_title: str | None = None
    source_abstract: str | None = None
    source_sha256: str | None = None


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


class CitationOracle:
    """Resolves citations against arXiv (ID-first) and Crossref (DOI-second)."""

    def __init__(
        self,
        *,
        arxiv_base: str = ARXIV_BASE,
        crossref_base: str = CROSSREF_BASE,
        mailto: str = DEFAULT_MAILTO,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._arxiv_base = arxiv_base
        self._crossref_base = crossref_base.rstrip("/")
        self._mailto = mailto
        self._client = client or httpx.AsyncClient(timeout=15.0)
        self._cache: dict[str, ExistenceResult] = {}

    async def resolve(self, citation: Citation) -> ExistenceResult:
        ident = (citation.identifier or "").strip()
        if not ident:
            return ExistenceResult(
                outcome=ExistenceOutcome.UNRESOLVABLE,
                query="",
                detail="no identifier (arXiv id or DOI); title-only is a fuzzy lower-trust tier",
            )
        norm = _norm_id(ident)
        if norm in self._cache:
            return self._cache[norm]

        if _ARXIV_NEW.match(norm) or _ARXIV_OLD.match(norm):
            result = await self._resolve_arxiv(norm, citation.title)
        elif _DOI.match(norm):
            result = await self._resolve_crossref(norm, citation.title)
        else:
            result = ExistenceResult(
                outcome=ExistenceOutcome.UNRESOLVABLE,
                query="",
                detail=f"identifier {norm!r} is neither an arXiv id nor a DOI",
            )
        self._cache[norm] = result
        return result

    async def _resolve_arxiv(self, arxiv_id: str, claimed_title: str) -> ExistenceResult:
        query = f"{self._arxiv_base}?id_list={arxiv_id}"
        try:
            resp = await self._client.get(query)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            return ExistenceResult(
                outcome=ExistenceOutcome.UNRESOLVABLE,
                query=query,
                detail=f"arXiv oracle unreachable: {type(e).__name__}",
            )
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError:
            return ExistenceResult(
                outcome=ExistenceOutcome.UNRESOLVABLE,
                query=query,
                detail="arXiv returned an unparseable feed",
            )
        # A bad id yields a single error <entry> with no <published>; require a real entry.
        real = [
            e
            for e in root.findall(f"{_ATOM}entry")
            if e.find(f"{_ATOM}published") is not None
        ]
        if not real:
            return ExistenceResult(
                outcome=ExistenceOutcome.FABRICATED,
                query=query,
                detail=f"arXiv has no record for id {arxiv_id}",
            )
        title = (real[0].findtext(f"{_ATOM}title") or "").strip()
        abstract = (real[0].findtext(f"{_ATOM}summary") or "").strip()
        return self._build_resolved(query, arxiv_id, "arXiv", claimed_title, title, abstract)

    async def _resolve_crossref(self, doi: str, claimed_title: str) -> ExistenceResult:
        query = f"{self._crossref_base}/{doi}?mailto={self._mailto}"
        try:
            resp = await self._client.get(query)
        except httpx.HTTPError as e:
            return ExistenceResult(
                outcome=ExistenceOutcome.UNRESOLVABLE,
                query=query,
                detail=f"Crossref oracle unreachable: {type(e).__name__}",
            )
        if resp.status_code == 404:
            return ExistenceResult(
                outcome=ExistenceOutcome.FABRICATED,
                query=query,
                detail=f"Crossref has no record for DOI {doi}",
            )
        try:
            resp.raise_for_status()
            message = resp.json().get("message", {})
        except (httpx.HTTPError, ValueError):
            return ExistenceResult(
                outcome=ExistenceOutcome.UNRESOLVABLE,
                query=query,
                detail="Crossref oracle returned an error / unparseable response",
            )
        titles = message.get("title") or []
        title = str(titles[0]).strip() if titles else ""
        abstract = re.sub(r"<[^>]+>", "", str(message.get("abstract", "") or "")).strip()
        return self._build_resolved(query, doi, "DOI", claimed_title, title, abstract)

    def _build_resolved(
        self,
        query: str,
        ident: str,
        kind: str,
        claimed_title: str,
        title: str,
        abstract: str,
    ) -> ExistenceResult:
        source = f"{title}\n\n{abstract}".strip()
        digest = _sha256(source) if source else None
        if not _titles_match(claimed_title, title):
            return ExistenceResult(
                outcome=ExistenceOutcome.METADATA_MISMATCH,
                query=query,
                detail=f"{kind} {ident} resolves to a different title: {title!r}",
                source_title=title or None,
                source_abstract=abstract or None,
                source_sha256=digest,
            )
        return ExistenceResult(
            outcome=ExistenceOutcome.RESOLVED,
            query=query,
            detail=f"{kind} {ident} resolved",
            source_title=title or None,
            source_abstract=abstract or None,
            source_sha256=digest,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
