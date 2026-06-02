"""Reasoning-stripping middleware.

Lock 2: Strip producer chain-of-thought before artifact crosses family boundary.
Aggressive default — strips all known reasoning tag patterns.
Post-strip re-parse verification rejects if patterns survive.

Justification: Mendes et al. 2026 (arXiv:2601.14691) — manipulated CoT
inflates VLM-judge false positives by up to 90%.

Scope & limitation: stripping is pattern-based. It removes KNOWN reasoning markers —
the XML tags in ``_REASONING_TAGS`` (attribute/whitespace tolerant, so
``<thinking signature="...">`` is caught), the vendor trace fields, and the JSON CoT-marker
keys in ``_REASONING_KEYS`` (case-insensitive, snake/camel, recursing into double-encoded JSON
strings) — and every strip target has a verification counterpart, so a known marker that
survives raises ``StripVerificationError`` rather than leaking. It deliberately does NOT strip
ambiguous business keys (``analysis``/``rationale``/...) that are often legitimate output, and
it cannot remove reasoning a producer disguises as ordinary content under a non-marker field
(e.g. ``{"answer": "<the chain of thought>"}``) — no enumeration can. Lock 2 thus defends
against standard CoT serializations biasing the verifier (the Mendes threat), not against an
adversarial producer hiding its trace in arbitrary fields.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

# XML reasoning tag names — ONE source of truth, shared by the strip patterns and their
# verification counterparts so the two can never diverge (the structural root cause of the
# original Lock-2 bypass). Open tags match tolerant of attributes / internal whitespace before
# '>', because Anthropic extended-thinking serializes as <thinking signature="...">, and a
# bare-tag-only match would silently leak it (CORE-V-001).
_REASONING_TAGS: tuple[str, ...] = (
    "thinking",
    "reasoning",
    "scratchpad",
    "scratch",
    "think",
    "thought",
)


def _xml_strip(tag: str) -> re.Pattern[str]:
    """A whole-element strip pattern for an (attribute-tolerant) reasoning tag."""
    return re.compile(rf"<{tag}(?:\s[^>]*)?>.*?</{tag}\s*>", re.DOTALL)


def _xml_open(tag: str) -> re.Pattern[str]:
    """A cheap opener-only verification pattern for an (attribute-tolerant) reasoning tag."""
    return re.compile(rf"<{tag}(?:\s[^>]*)?>", re.IGNORECASE)


# Compiled regex patterns for known reasoning formats.
_PATTERNS: list[re.Pattern[str]] = [
    # XML-style reasoning tags (attribute/whitespace tolerant), one per _REASONING_TAGS entry.
    *(_xml_strip(t) for t in _REASONING_TAGS),
    # Vendor-namespaced trace fields in JSON-like content
    re.compile(r'"claude\.thinking[^"]*"\s*:\s*"[^"]*"', re.DOTALL),
    re.compile(r'"openai\.reasoning[^"]*"\s*:\s*"[^"]*"', re.DOTALL),
    re.compile(r'"gemini\.thinking[^"]*"\s*:\s*"[^"]*"', re.DOTALL),
    re.compile(r'"deepseek\.think[^"]*"\s*:\s*"[^"]*"', re.DOTALL),
]

# Reasoning-ish object keys dropped from JSON-parseable content, matched CASE-INSENSITIVELY at
# any nesting depth and over ANY value shape (bare string, nested object, array, alternate
# subfields like trace/steps, and double-encoded JSON strings). This is the JSON-key equivalent
# of the XML reasoning tags above (<thinking>/<think>/<thought>/<scratchpad>/...), so a producer
# cannot dodge Lock 2 just by emitting chain-of-thought as {"thinking": ...} or {"COT": ...}
# instead of <thinking>...</thinking>. Deliberately CONSERVATIVE: only well-known CoT-marker keys
# are dropped, NOT ambiguous business-content keys (analysis, rationale, reflection, explanation)
# that are frequently legitimate artifact output — dropping those would corrupt real content. A
# JSON-aware drop is exhaustive over value shape and, unlike a greedy [^}]* regex, never mangles
# escaped quotes or sibling keys (CORE-A-004).
_REASONING_KEYS: frozenset[str] = frozenset(
    {
        "reasoning",
        "reasoning_content",
        "reasoningcontent",
        "thinking",
        "think",
        "thought",
        "thoughts",
        "scratchpad",
        "scratch",
        "chain_of_thought",
        "chainofthought",
        "cot",
    }
)

# Quick-check patterns for post-strip verification (cheaper than full patterns).
# Every strip target has a verification counterpart here — the last line of defense.
_VERIFICATION_PATTERNS: list[re.Pattern[str]] = [
    # XML reasoning openers (attribute-tolerant, case-insensitive) — one per _REASONING_TAGS
    # entry, so every XML strip target has a verification counterpart (the last line of defense).
    *(_xml_open(t) for t in _REASONING_TAGS),
    re.compile(r'"claude\.thinking'),
    re.compile(r'"openai\.reasoning'),
    re.compile(r'"gemini\.thinking'),
    re.compile(r'"deepseek\.think'),
    # Generic JSON reasoning fields (case-insensitive; snake AND camel via optional underscores):
    # catch a surviving "<key>": <value> the JSON-aware drop did not reach — e.g. reasoning
    # embedded in non-JSON text the parser could not load. Requires a value opener (" [ {) right
    # after the colon, so a mere MENTION of the token in prose/code (a comment naming a
    # "reasoning": field) does NOT false-trip the gate; a real surviving field still trips it.
    re.compile(
        r'"(reasoning|reasoning_?content|thinking|think|thoughts?|scratchpad|scratch'
        r'|chain_?of_?thought|cot)"\s*:\s*["\[{]',
        re.IGNORECASE,
    ),
]


def _drop_reasoning_keys(obj: Any) -> Any:
    """Recursively drop reasoning-ish keys from a parsed-JSON structure.

    Walks dicts/lists and removes any key in ``_REASONING_KEYS`` wherever it appears
    (top level or nested). Returns a new structure; non-container values pass through.
    Vendor-namespaced (``claude.thinking`` etc.) and XML-tag reasoning are handled by
    the regex pass — this covers the generic JSON ``"reasoning"`` field of any value shape.
    """
    if isinstance(obj, dict):
        return {
            k: _drop_reasoning_keys(v)
            for k, v in obj.items()
            if not (isinstance(k, str) and k.lower() in _REASONING_KEYS)
        }
    if isinstance(obj, list):
        return [_drop_reasoning_keys(v) for v in obj]
    if isinstance(obj, str):
        # Double-encoded reasoning: a string value that is itself JSON (a dict/list) may hide a
        # reasoning key (e.g. a tool result whose body is stringified JSON). Re-parse, clean, and
        # re-encode ONLY if something changed — a legitimate non-reasoning string is returned
        # byte-for-byte unchanged.
        try:
            inner = json.loads(obj)
        except (json.JSONDecodeError, ValueError, RecursionError):
            return obj
        if isinstance(inner, (dict, list)):
            cleaned_inner = _drop_reasoning_keys(inner)
            if cleaned_inner != inner:
                return json.dumps(cleaned_inner)
        return obj
    return obj


@dataclass(frozen=True)
class StripResult:
    """Result of reasoning stripping."""

    content: str
    pre_strip_hash: str
    post_strip_hash: str
    bytes_removed: int
    patterns_matched: int


class StripVerificationError(Exception):
    """Raised when post-strip re-parse finds surviving reasoning patterns."""

    def __init__(self, surviving_patterns: list[str]) -> None:
        self.surviving_patterns = surviving_patterns
        super().__init__(
            f"STRIP_VERIFICATION_FAILED: {len(surviving_patterns)} pattern(s) "
            f"survived stripping: {surviving_patterns}"
        )


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def strip_reasoning(content: str, *, verify: bool = True) -> StripResult:
    """Strip all known reasoning patterns from content.

    Args:
        content: The artifact content to strip.
        verify: If True (default), re-parse post-strip and raise
                StripVerificationError if patterns survive.

    Returns:
        StripResult with stripped content and hashes.

    Raises:
        StripVerificationError: If verify=True and patterns survive stripping.
    """
    pre_hash = _sha256(content)
    pre_len = len(content.encode())

    stripped = content
    patterns_matched = 0

    # JSON-aware pass first: if the whole artifact parses as JSON, recursively drop
    # reasoning-ish keys of ANY value shape (bare string, nested object, alternate
    # subfields) and re-serialize. This is exhaustive where the narrow regex shapes
    # below are not, and — unlike a greedy [^}]* regex — never corrupts escaped quotes
    # or sibling keys (CORE-A-004). Non-JSON / embedded text falls through to the regex
    # pass; the JSON "reasoning" verification pattern is the final backstop.
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError, RecursionError):
        # Unparseable — including pathologically deep nesting, whose RecursionError is NOT a
        # ValueError. Fall through to the regex pass; the verification backstop still refuses if
        # a reasoning field survives, so a deep-nesting input can never crash the Lock 2 gate.
        parsed = None
    if parsed is not None:
        try:
            cleaned = _drop_reasoning_keys(parsed)
        except RecursionError:
            cleaned = parsed  # too deep to clean structurally; regex + verify backstop apply
        if cleaned != parsed:
            patterns_matched += 1
            stripped = json.dumps(cleaned)

    for pattern in _PATTERNS:
        new_content, count = pattern.subn("", stripped)
        patterns_matched += count
        stripped = new_content

    post_hash = _sha256(stripped)
    post_len = len(stripped.encode())

    if verify:
        _verify_strip(stripped)

    return StripResult(
        content=stripped,
        pre_strip_hash=pre_hash,
        post_strip_hash=post_hash,
        bytes_removed=pre_len - post_len,
        patterns_matched=patterns_matched,
    )


def _verify_strip(content: str) -> None:
    """Re-parse stripped content to ensure no reasoning patterns survive.

    Raises StripVerificationError if any pattern is found.
    """
    survivors = []
    for pattern in _VERIFICATION_PATTERNS:
        if pattern.search(content):
            survivors.append(pattern.pattern)

    if survivors:
        raise StripVerificationError(survivors)
