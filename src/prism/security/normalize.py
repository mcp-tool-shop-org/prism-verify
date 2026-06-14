"""Input normalization / de-smuggling — the model-free, certification-preserving core of the
``prism.security`` injection-hardening stage (design/specialist-injection-hardening-dispatch.md,
finding 9).

Character-level smuggling — zero-width spaces, Unicode TAG characters (U+E0000-U+E007F), variation
selectors, and bidirectional-control overrides — slips instructions past a human reader and bypasses
production prompt-injection detectors at up to 100% attack success (Hackett et al. 2025,
arXiv:2504.11168). Normalizing a COPY of judged content before it reaches a detector closes that
trivial-evasion class.

This NEVER mutates a certified judge's input: callers normalize the content they SCREEN, not the
bytes the judge sees, so the fixed-input-shape certification (flip-consistency + OOD gate) is
untouched (Ovadia et al. 2019, arXiv:1906.02530 — any input transform is a distribution shift, so it
is confined to the screening copy by design).

Deterministic and side-effect-free, so a normalization can be pinned into a receipt for replay.
Fail-open by contract: it only ever REMOVES known-invisible / known-control code points and reports
what it removed; it never blocks. A heavy concentration of smuggling characters is surfaced as an
advisory ``suspicious`` signal a caller MAY route to ABSTAIN — never an assertion of safety.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

# Zero-width / joiner code points: invisible, used to break up or hide an instruction.
_ZERO_WIDTH: frozenset[str] = frozenset(
    {
        "​",  # ZERO WIDTH SPACE
        "‌",  # ZERO WIDTH NON-JOINER
        "‍",  # ZERO WIDTH JOINER
        "⁠",  # WORD JOINER
        "﻿",  # ZERO WIDTH NO-BREAK SPACE / BOM
    }
)

# Bidirectional formatting / override controls (the "Trojan Source" class, Boucher & Anderson 2021):
# reorder how text renders versus how it tokenizes. No benign use inside judged content.
_BIDI: frozenset[str] = frozenset(
    {
        "‪",  # LEFT-TO-RIGHT EMBEDDING
        "‫",  # RIGHT-TO-LEFT EMBEDDING
        "‬",  # POP DIRECTIONAL FORMATTING
        "‭",  # LEFT-TO-RIGHT OVERRIDE
        "‮",  # RIGHT-TO-LEFT OVERRIDE
        "⁦",  # LEFT-TO-RIGHT ISOLATE
        "⁧",  # RIGHT-TO-LEFT ISOLATE
        "⁨",  # FIRST STRONG ISOLATE
        "⁩",  # POP DIRECTIONAL ISOLATE
    }
)

# Zero-width and variation selectors DO occur benignly (emoji, scripts), so they only contribute to
# the advisory suspicion signal past a small budget. TAG, BIDI, and C0/C1 control characters have no
# benign use in judged content (\t \n \r excepted), so a single one is suspicious on its own.
_ZW_VS_SUSPICION_BUDGET = 4


def _is_tag_char(cp: int) -> bool:
    """Unicode TAG block (U+E0000-U+E007F) — invisible carriers used to smuggle instructions."""
    return 0xE0000 <= cp <= 0xE007F


def _is_variation_selector(cp: int) -> bool:
    """Variation selectors (U+FE00-U+FE0F, U+E0100-U+E01EF) — emoji-variation smuggling carriers."""
    return 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF


def _is_control(cp: int) -> bool:
    """C0 (U+0000-U+001F) and C1 (U+0080-U+009F) control chars — invisible / non-printing carriers
    used to break up or hide an instruction (e.g. NUL, vertical tab, NEL). Whitespace that carries
    real layout meaning in judged content — TAB (\\t), LF (\\n), CR (\\r) — is preserved."""
    if cp in (0x09, 0x0A, 0x0D):  # \t \n \r — benign layout whitespace, keep
        return False
    return cp <= 0x1F or 0x80 <= cp <= 0x9F


@dataclass(frozen=True)
class NormalizationReport:
    """Result of de-smuggling a content copy.

    ``normalized`` is the cleaned text (targeted code points removed, then NFKC-folded). ``removed``
    maps each smuggling class to the count stripped. ``suspicious`` is an advisory contamination
    signal (heavy / structured smuggling) a caller MAY route to fail-open ABSTAIN — never a safety
    assertion.
    """

    normalized: str
    removed: dict[str, int]
    suspicious: bool

    @property
    def total_removed(self) -> int:
        """Total count of smuggling code points removed across all classes."""
        return sum(self.removed.values())


def desmuggle(text: str) -> NormalizationReport:
    """Strip known invisible / control smuggling characters and NFKC-fold; report what was removed.

    Removal classes: ``zero_width``, ``bidi``, ``tag``, ``variation_selector``, ``control`` (C0/C1
    control characters, except the benign whitespace ``\\t`` ``\\n`` ``\\r``). NFKC folding
    canonicalizes compatibility forms (e.g. full-width ``Ｉ`` -> ``I``) so an attacker cannot
    hide an instruction behind a visually-identical compatibility code point. Targeted code
    points are stripped first, then the remainder is NFKC-folded.
    """
    removed: dict[str, int] = {
        "zero_width": 0,
        "bidi": 0,
        "tag": 0,
        "variation_selector": 0,
        "control": 0,
    }
    kept: list[str] = []
    for ch in text:
        cp = ord(ch)
        if ch in _ZERO_WIDTH:
            removed["zero_width"] += 1
        elif ch in _BIDI:
            removed["bidi"] += 1
        elif _is_tag_char(cp):
            removed["tag"] += 1
        elif _is_variation_selector(cp):
            removed["variation_selector"] += 1
        elif _is_control(cp):
            removed["control"] += 1
        else:
            kept.append(ch)

    normalized = unicodedata.normalize("NFKC", "".join(kept))
    suspicious = (
        removed["tag"] > 0
        or removed["bidi"] > 0
        or removed["control"] > 0
        or (removed["zero_width"] + removed["variation_selector"]) > _ZW_VS_SUSPICION_BUDGET
    )
    return NormalizationReport(normalized=normalized, removed=removed, suspicious=suspicious)
