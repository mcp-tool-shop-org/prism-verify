"""Phase-1 (model-free) corruptions: take a faithful claim and plant ONE targeted swap so it turns
plausible-but-unsupported. The swap is the self-check — we record exactly what changed, so the gold
label ('unsupported') is known by construction. Phase-2 (post-run, local model) adds fluent
MiniCheck-style C2D/D2C paraphrase-then-corrupt on top of these deterministic seeds."""
import re

# Semantic word-pair swaps (role / relation / polarity) — the kind that read fluent but flip meaning.
SWAP_PAIRS = [
    ("crew", "passengers"), ("absorbed into", "spun off from"), ("acquired", "merged with"),
    ("raised", "spent"), ("at least", "at most"), ("at most", "at least"),
    ("in parallel", "in sequence"), ("never preview", "preview-only"),
    ("primary", "secondary"), ("GA SKU", "preview SKU"),
]

_WORDNUM = {"forty-three": "forty-seven", "three": "five", "four": "six", "two": "three"}


def swap_pair(text):
    low = text.lower()
    for a, b in SWAP_PAIRS:
        i = low.find(a)
        if i >= 0:
            return text[:i] + b + text[i + len(a):], f"'{a}' -> '{b}'"
    return None


def swap_year(text):
    m = re.search(r"\b(?:19|20)\d\d\b", text)
    if not m:
        return None
    new = str(int(m.group()) + 1)
    return text[:m.start()] + new + text[m.end():], f"year {m.group()} -> {new}"


def swap_number(text):
    m = re.search(r"\b\d[\d,]*\b", text)
    if not m:
        return None
    orig = m.group()
    val = int(orig.replace(",", ""))
    new = str(val + (1 if val < 10 else max(1, round(val * 0.1))))
    return text[:m.start()] + new + text[m.end():], f"number {orig} -> {new}"


def swap_wordnum(text):
    for w, n in _WORDNUM.items():
        if re.search(rf"\b{re.escape(w)}\b", text):
            return re.sub(rf"\b{re.escape(w)}\b", n, text, count=1), f"'{w}' -> '{n}'"
    return None


def corrupt(text):
    """Return (corrupted_text, description) using the first applicable swap, or None."""
    for fn in (swap_pair, swap_year, swap_wordnum, swap_number):
        r = fn(text)
        if r:
            return r
    return None


def negate(text):
    """Plant a direct contradiction. COPULA-ONLY: 'is/was/are/were' + 'not' is always grammatical
    ('is not'); action verbs would give 'departed not ...' — ungrammatical, and the kickoff flags
    ungrammatical artifacts as a SHORTCUT SIGNAL (model learns broken-grammar -> unsupported instead of
    the real check). When no copula is present we return None and the claim-group simply skips the
    contradiction twin (still flip-ready via supported + abstain); the fluent Phase-2 corruptions are
    the primary, grammatical L2 source anyway."""
    for aux in (" is ", " was ", " are ", " were "):
        i = text.find(aux)
        if i >= 0:
            return text[:i + len(aux)] + "not " + text[i + len(aux):], f"negated ('{aux.strip()}')"
    return None
