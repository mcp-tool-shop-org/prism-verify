"""Reasoning-stripping middleware.

Lock 2: Strip producer chain-of-thought before artifact crosses family boundary.
Aggressive default — strips all known reasoning tag patterns.
Post-strip re-parse verification rejects if patterns survive.

Justification: Mendes et al. 2026 (arXiv:2601.14691) — manipulated CoT
inflates VLM-judge false positives by up to 90%.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# Compiled regex patterns for known reasoning formats
_PATTERNS: list[re.Pattern[str]] = [
    # XML-style tags (Anthropic <thinking>, generic <reasoning>, <scratchpad>, <scratch>)
    re.compile(r"<thinking>.*?</thinking>", re.DOTALL),
    re.compile(r"<reasoning>.*?</reasoning>", re.DOTALL),
    re.compile(r"<scratchpad>.*?</scratchpad>", re.DOTALL),
    re.compile(r"<scratch>.*?</scratch>", re.DOTALL),
    # DeepSeek-R1 format
    re.compile(r"<think>.*?</think>", re.DOTALL),
    # Vendor-namespaced trace fields in JSON-like content
    re.compile(r'"claude\.thinking[^"]*"\s*:\s*"[^"]*"', re.DOTALL),
    re.compile(r'"openai\.reasoning[^"]*"\s*:\s*"[^"]*"', re.DOTALL),
    re.compile(r'"gemini\.thinking[^"]*"\s*:\s*"[^"]*"', re.DOTALL),
    re.compile(r'"deepseek\.think[^"]*"\s*:\s*"[^"]*"', re.DOTALL),
    # OpenAI reasoning summary blocks (JSON field patterns)
    re.compile(r'"reasoning"\s*:\s*\{[^}]*"content"\s*:\s*"[^"]*"[^}]*\}', re.DOTALL),
    re.compile(r'"reasoning"\s*:\s*\{[^}]*"summary"\s*:\s*"[^"]*"[^}]*\}', re.DOTALL),
]

# Quick-check patterns for post-strip verification (cheaper than full patterns)
_VERIFICATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"<thinking>", re.IGNORECASE),
    re.compile(r"<reasoning>", re.IGNORECASE),
    re.compile(r"<scratchpad>", re.IGNORECASE),
    re.compile(r"<scratch>", re.IGNORECASE),
    re.compile(r"<think>", re.IGNORECASE),
    re.compile(r'"claude\.thinking'),
    re.compile(r'"openai\.reasoning'),
    re.compile(r'"gemini\.thinking'),
    re.compile(r'"deepseek\.think'),
]


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
