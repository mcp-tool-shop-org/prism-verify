"""Offline ingester for real-bug program pairs (QuixBugs) into the prism corpus shape.

This is the F-01 v1.1 "realism upgrade" the authored corpus docstring points at: instead of
hand-written toy defects, ingest a vendored, MIT-licensed checkout of QuixBugs
(https://github.com/jkoppel/QuixBugs) — ~40 small Python programs, each shipping a single-line
buggy version and a corrected version. Each program yields TWO ``Sample``s in the EXACT
``corpus.Sample`` shape (no schema change):

  * the BUGGY source  -> ``positive=True``  (a real defect the code lens should catch),
                         ``expected_verdict='revise'`` (a single-line fix repairs it; NEVER
                         ``'accept'`` — ``check_corpus_integrity`` refuses a positive that expects
                         accept).
  * the CORRECTED source -> ``positive=False`` (clean counterpart), ``expected_verdict='accept'``.

**Pure / offline.** The vendored sources under ``eval/vendor/quixbugs/`` are read as text at
build time; there is NO network access at runtime. The lens / intent / bug-class maps below are
checked-in and hand-authored by reading each program — a wrong ``target_lens`` would silently
corrupt the per-lens metrics, so a program is ingested ONLY if it appears in all three maps.

**Contamination.** QuixBugs is small and famous; verifier models have very likely memorized it.
These samples are wired into the ``public`` split and flagged ``contaminated: true`` in the
manifest (see ``corpus.build_corpus``); a public-split number on them is a CEILING. The honest,
post-cutoff signal is the ``fresh`` split (SWE-bench-Live ingestion is deferred to v1.2).

**Lenses.** QuixBugs are plain functions, so only the two CODE-applicable lenses are used:
``invariant`` (loop / recursion / boundary / operator correctness — does the algorithm hold its
invariant?) and ``contract_completeness`` (a clause of the stated contract — a base case, an empty
guard — is missing). ``cross_boundary`` is the tool-call lens and ``groundedness`` is about
fabricated APIs/citations; neither applies to a self-contained correct/buggy algorithm pair.
"""

# ruff: noqa: E501 — data module: the checked-in lens/intent/bug-class maps + their per-program
# explanatory inline comments are clearer unwrapped (mirrors corpus.py's embedded-data exemption).
from __future__ import annotations

from pathlib import Path

from prism.core.types import ArtifactType
from prism.eval.corpus import Sample

# The two CODE lenses QuixBugs defects fall under. (cross_boundary = tool-call lens; groundedness =
# fabricated-API/citation lens — neither applies to a self-contained algorithm pair.)
_INVARIANT = "invariant"
_CONTRACT = "contract_completeness"

# program-name -> target_lens. Authored by reading each buggy/correct pair (the defect class drives
# the lens). A program absent here is NOT ingested (we never guess a lens — a wrong one corrupts the
# per-lens metrics).
_QUIXBUGS_LENS_MAP: dict[str, str] = {
    "bitcount": _INVARIANT,  # n ^= n-1 vs n &= n-1: wrong bitwise op, loop never terminates as spec'd
    "gcd": _INVARIANT,  # gcd(a % b, b) vs gcd(b, a % b): swapped recursion args break the recurrence
    "is_valid_parenthesization": _CONTRACT,  # returns True, never checks leftover unclosed depth==0
    "sieve": _INVARIANT,  # any(...) vs all(...): inverted primality test
    "sqrt": _INVARIANT,  # |x - approx| vs |x - approx**2|: wrong convergence invariant
    "to_base": _INVARIANT,  # digits appended in reverse order -> wrong result string
    "next_palindrome": _INVARIANT,  # off-by-one in the all-9s carry-out zero padding
    "possible_change": _CONTRACT,  # missing the "no coins left" base case
    "find_first_in_sorted": _INVARIANT,  # lo <= hi vs lo < hi: off-by-one, indexes past the end
    "find_in_sorted": _INVARIANT,  # binsearch(mid, end) vs mid+1: off-by-one, infinite recursion
    "flatten": _INVARIANT,  # yields flatten(x) (a generator) instead of the leaf value x
    "get_factors": _CONTRACT,  # returns [] instead of [n] for a prime remainder -> drops a factor
    "hanoi": _INVARIANT,  # appends (start, helper) vs (start, end): wrong move emitted
    "kth": _INVARIANT,  # kth(above, k) vs k - num_lessoreq: wrong rank index into the upper partition
    "lcs_length": _INVARIANT,  # dp[i-1, j] vs dp[i-1, j-1]: wrong DP predecessor cell
    "levenshtein": _INVARIANT,  # adds 1 on a character match instead of recursing free
    "max_sublist_sum": _CONTRACT,  # missing the max(0, ...) reset that drops a negative running sum
    "mergesort": _CONTRACT,  # base case len == 0 vs len <= 1: a singleton recurses forever
    "kheapsort": _INVARIANT,  # iterates arr vs arr[k:]: re-pushes the first k elements
    "pascal": _INVARIANT,  # range(0, r) vs range(0, r + 1): off-by-one, drops the last entry per row
    "powerset": _CONTRACT,  # omits the subsets that exclude `first` -> incomplete power set
    "quicksort": _INVARIANT,  # x > pivot vs x >= pivot: silently drops elements equal to the pivot
    "knapsack": _INVARIANT,  # weight < j vs weight <= j: off-by-one excludes an exactly-fitting item
    "subsequences": _CONTRACT,  # base case returns [] vs [[]]: collapses every result to empty
    "next_permutation": _INVARIANT,  # perm[j] < perm[i] vs perm[i] < perm[j]: inverted swap target
}

# program-name -> short bug_class label (NOT 'clean'/'real', which check_corpus_integrity reserves
# for negatives). Mirrors the authored corpus's vocabulary where it fits.
_QUIXBUGS_BUG_CLASS: dict[str, str] = {
    "bitcount": "wrong_operator",
    "gcd": "wrong_recursive_args",
    "is_valid_parenthesization": "missing_clause",
    "sieve": "wrong_operator",
    "sqrt": "wrong_condition",
    "to_base": "wrong_order",
    "next_palindrome": "off_by_one",
    "possible_change": "missing_clause",
    "find_first_in_sorted": "off_by_one",
    "find_in_sorted": "off_by_one",
    "flatten": "wrong_value",
    "get_factors": "missing_clause",
    "hanoi": "wrong_value",
    "kth": "wrong_index",
    "lcs_length": "wrong_index",
    "levenshtein": "wrong_value",
    "max_sublist_sum": "missing_clause",
    "mergesort": "missing_clause",
    "kheapsort": "off_by_one",
    "pascal": "off_by_one",
    "powerset": "missing_clause",
    "quicksort": "wrong_operator",
    "knapsack": "off_by_one",
    "subsequences": "missing_clause",
    "next_permutation": "wrong_operator",
}

# program-name -> one-line NL spec of what the function SHOULD do (the intent the verifier is given).
# Authored from each program's upstream docstring; kept terse and self-contained.
_QUIXBUGS_INTENT: dict[str, str] = {
    "bitcount": "Return the number of 1-bits in the binary encoding of a nonnegative int n.",
    "gcd": "Return the greatest common divisor of two nonnegative ints a and b.",
    "is_valid_parenthesization": "Return whether a string of '(' and ')' is properly nested.",
    "sieve": "Return all primes up to and including max (Sieve of Eratosthenes).",
    "sqrt": "Return a float within epsilon of sqrt(x) via Newton-Raphson; x >= 1, epsilon > 0.",
    "to_base": "Return the string representation of base-10 int num in base b (2 <= b <= 36).",
    "next_palindrome": "Given a palindrome as a list of base-10 digits, return the next palindrome.",
    "possible_change": "Return the number of distinct ways to make change for total using coins.",
    "find_first_in_sorted": "Return the lowest index i with arr[i] == x in sorted arr, else -1.",
    "find_in_sorted": "Return an index i with arr[i] == x in sorted arr, or -1 if x is absent.",
    "flatten": "Yield each non-list leaf of an arbitrarily nested list, left to right.",
    "get_factors": "Return the prime factors of n >= 1 in sorted order with repetition.",
    "hanoi": "Return the ordered (from, to) moves that solve Towers of Hanoi of the given height.",
    "kth": "Return the kth-lowest (0-based) element of arr via QuickSelect; 0 <= k < len(arr).",
    "lcs_length": "Return the length of the longest common SUBSTRING of strings s and t.",
    "levenshtein": "Return the Levenshtein edit distance between source and target strings.",
    "max_sublist_sum": "Return the maximum sum over all contiguous sublists of arr (Kadane).",
    "mergesort": "Return the elements of arr in sorted order using merge sort.",
    "kheapsort": "Yield the elements of an almost-sorted arr (each <= k from place) in sorted order.",
    "pascal": "Return the first n rows of Pascal's triangle as a list of n lists; n >= 1.",
    "powerset": "Return all subsets of arr (which has no duplicates) as a list of lists.",
    "quicksort": "Return the elements of arr in sorted order using quicksort (keep duplicates).",
    "knapsack": "Return the max total value of items fitting within capacity (0/1 knapsack).",
    "subsequences": "Return all length-k ascending int sequences drawn from range(a, b).",
    "next_permutation": "Return the lexicographically next permutation of a list of unique ints.",
}


def _read(path: Path) -> str:
    """Read a vendored source file as text (offline). Returns '' if absent."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def ingest_quixbugs(src_dir: Path, split: str = "public") -> list[Sample]:
    """Ingest the vendored QuixBugs pairs under ``src_dir`` into corpus ``Sample``s (offline).

    ``src_dir`` is the vendored root (``eval/vendor/quixbugs``) holding ``python_programs/`` (buggy)
    and ``correct_python_programs/`` (fixed). For each program that (a) has BOTH a buggy and a
    corrected source on disk and (b) appears in all three checked-in maps, emit two samples:

      * ``quixbugs-<name>-buggy``  : positive, ``expected_verdict='revise'`` (a single-line fix
        repairs the defect — never ``'accept'``), ``target_lens`` from ``_QUIXBUGS_LENS_MAP``.
      * ``quixbugs-<name>-fixed``  : negative, ``expected_verdict='accept'``, same lens/intent.

    Pure and deterministic (programs ingested in sorted name order). No network.
    """
    src_dir = Path(src_dir)
    buggy_dir = src_dir / "python_programs"
    fixed_dir = src_dir / "correct_python_programs"
    out: list[Sample] = []
    for name in sorted(_QUIXBUGS_LENS_MAP):
        if name not in _QUIXBUGS_INTENT or name not in _QUIXBUGS_BUG_CLASS:
            continue  # a program must be fully mapped or it is skipped (never guess a label)
        buggy = _read(buggy_dir / f"{name}.py")
        fixed = _read(fixed_dir / f"{name}.py")
        if not buggy.strip() or not fixed.strip():
            continue  # a pair must have BOTH sources present and non-empty
        lens = _QUIXBUGS_LENS_MAP[name]
        intent = _QUIXBUGS_INTENT[name]
        out.append(
            Sample(
                id=f"quixbugs-{name}-buggy",
                artifact_type=ArtifactType.CODE.value,
                content=buggy,
                intent=intent,
                positive=True,
                target_lens=lens,
                bug_class=_QUIXBUGS_BUG_CLASS[name],
                expected_verdict="revise",  # a single-line fix repairs it; NEVER 'accept'
                split=split,
            )
        )
        out.append(
            Sample(
                id=f"quixbugs-{name}-fixed",
                artifact_type=ArtifactType.CODE.value,
                content=fixed,
                intent=intent,
                positive=False,
                target_lens=lens,
                bug_class="clean",
                expected_verdict="accept",
                split=split,
            )
        )
    return out
