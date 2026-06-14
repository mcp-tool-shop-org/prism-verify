"""CodeJudgeBench loader (F-01 sub-build 3A) — pairwise (chosen vs rejected) coding-judgment items.

Loads the HF dataset ``mattymchen/codejudgebench`` (arXiv:2507.10535, Apache-2.0). CodeJudgeBench is
PAIRWISE: each row carries a question and two responses — ``pos_response`` (the CHOSEN/preferred
one) and ``neg_response`` (the REJECTED one). prism is a single-artifact verifier, so the harness
(``harness.py``) verifies each side separately and reduces the two verdicts to a preference via
``calibrate.pairwise_prefer``; a result is CORRECT iff prism prefers the CHOSEN side.

VERIFIED against the HF dataset card + the datasets-server ``/info`` endpoint (2026-06-14):

  * Configs ARE the task categories: ``codegen``, ``codegen_pass5``, ``coderepair``, ``testgen``.
  * Splits ARE the producing model (e.g. ``claude_3.7_sonnet``, ``gemini_2.5_pro``) — the producer
    is NOT a column; it is the split name, captured here into ``CJBItem.producer``.
  * Columns (confirmed verbatim): ``question_content`` (prompt), ``pos_response`` (CHOSEN),
    ``neg_response`` (REJECTED), ``starter_code`` (optional context), ``question_id``,
    ``question_title``, ``platform``, ``difficulty``. There is NO explicit preference-label column —
    preference is implicit in pos vs neg, which is exactly why a pos/neg SWAP would silently invert
    the entire accuracy number. So the loader ANDON-VALIDATES the columns at load time and RAISES a
    clear error if an expected column is missing/renamed — it never silently mis-maps chosen/rejected.

The default install does NOT carry the HF ``datasets`` lib: the ONLINE path lazy-imports it (clear
error pointing at ``pip install 'prism-verify[bench]'`` if absent), and the OFFLINE path reads a
committed fixture (``eval/benchmarks/codejudgebench/fixture.jsonl``) so tests + ``--offline`` need
neither network nor ``datasets`` — mirroring the lazy-torch, graceful-absence ``nli`` pattern.
"""

# ruff: noqa: E501 — schema-contract module: the column/config/split contract comments + docstrings
# (mirroring the HF dataset card verbatim) are clearer unwrapped, as in corpus.py / realbug.py.
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

# The task categories ARE the HF config names (verified against the dataset card).
CJB_TASKS = ("codegen", "codegen_pass5", "coderepair", "testgen")

# The columns the loader REQUIRES from every HF row. A missing/renamed one ANDON-fails the load
# rather than silently mis-mapping chosen vs rejected (the #1 risk: a pos/neg swap inverts accuracy).
_REQUIRED_COLUMNS = ("question_content", "pos_response", "neg_response")

# Content-hash schema id (mirrors corpus.CONTENT_HASH_SCHEMA): bump if the canonical form changes so
# an old hash is never silently compared against a new canonicalization.
CONTENT_HASH_SCHEMA = "prism-codejudgebench-content/v1"

# Default committed fixture: an attributed ~6-item slice for offline tests + ``--offline`` (NOT a
# redistribution of the full dataset). Resolved from this file so it works regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_FIXTURE = _REPO_ROOT / "eval" / "benchmarks" / "codejudgebench" / "fixture.jsonl"


class CJBColumnError(ValueError):
    """ANDON: a CodeJudgeBench row is missing/renamed an expected column.

    Raised at load time so a pos/neg swap or a schema drift on HF never silently produces an
    inverted accuracy number. Carries the missing column name + the keys actually seen.
    """


@dataclass(frozen=True)
class CJBItem:
    """One pairwise CodeJudgeBench comparison flattened into prism's verify shape.

    ``chosen_code`` is the CHOSEN/preferred response (HF ``pos_response``); ``rejected_code`` is the
    REJECTED one (HF ``neg_response``). A result is correct iff prism prefers ``chosen_code``.
    ``task`` is the HF config; ``producer`` is the HF split (the model that wrote the responses).
    """

    task: str
    producer: str
    item_id: str
    question: str
    chosen_code: str
    rejected_code: str
    context: str | None = None  # HF starter_code / wrong_code, when present
    title: str = ""
    platform: str = ""
    difficulty: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> CJBItem:
        # Tolerate extra keys in a row (e.g. a comment field) by selecting known fields only.
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})  # type: ignore[arg-type]


def _stringify(value: object) -> str:
    """Coerce a response cell to text. ``codegen_pass5`` stores responses as a LIST; take its first
    element (the comparison is still pos[0] vs neg[0]) so the loader handles all four configs."""
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return "" if value is None else str(value)


def _row_to_item(row: dict[str, object], *, task: str, producer: str, index: int) -> CJBItem:
    """Map ONE validated HF row to a ``CJBItem``. ANDON-raises on a missing required column."""
    for col in _REQUIRED_COLUMNS:
        if col not in row:
            raise CJBColumnError(
                f"CodeJudgeBench row (task={task!r}, producer={producer!r}) is missing the required "
                f"column {col!r}; columns present: {sorted(row)}. Refusing to map chosen/rejected — "
                "a renamed pos/neg column would silently invert the accuracy."
            )
    chosen = _stringify(row["pos_response"])
    rejected = _stringify(row["neg_response"])
    # ``coderepair`` carries the buggy code as ``wrong_code``; otherwise the optional starter is the
    # context. Either is forwarded as the (optional) context for the verify intent.
    ctx_raw = row.get("wrong_code") or row.get("starter_code")
    context = _stringify(ctx_raw) if ctx_raw else None
    qid = row.get("question_id")
    item_id = str(qid) if qid not in (None, "") else f"{task}-{producer}-{index}"
    return CJBItem(
        task=task,
        producer=producer,
        item_id=item_id,
        question=_stringify(row["question_content"]),
        chosen_code=chosen,
        rejected_code=rejected,
        context=context,
        title=_stringify(row.get("question_title", "")),
        platform=_stringify(row.get("platform", "")),
        difficulty=_stringify(row.get("difficulty", "")),
    )


def load_codejudgebench_offline(
    task: str | None = None, limit: int | None = None, *, source: Path = DEFAULT_FIXTURE
) -> list[CJBItem]:
    """Load the committed fixture (no network, no ``datasets`` lib). Used by tests + ``--offline``.

    The fixture is JSONL of ``CJBItem`` dicts. ANDON-validates each row exactly as the HF path does
    (so a fixture with a renamed/missing column fails loud too — the test surface for the #1 risk).
    """
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(
            f"CodeJudgeBench fixture not found at {source} — ship "
            "eval/benchmarks/codejudgebench/fixture.jsonl or pass --benchmark with a real load."
        )
    items: list[CJBItem] = []
    for index, raw in enumerate(source.read_text(encoding="utf-8").splitlines()):
        line = raw.strip()
        if not line:
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise CJBColumnError(f"fixture line {index} is not a JSON object: {line[:80]!r}")
        # Validate against the SAME required-column contract as the HF path (fixture-verified ANDON).
        row_task = str(row.get("task", "")) or "unknown"
        item = _row_to_item(row, task=row_task, producer=str(row.get("producer", "")), index=index)
        if task is not None and item.task != task:
            continue
        items.append(item)
        if limit is not None and len(items) >= limit:
            break
    return items


def _load_hf(task: str, producer: str | None, limit: int | None) -> list[CJBItem]:
    """ONLINE path: lazy-import ``datasets``, download-on-demand, ANDON-validate columns.

    Lazy import keeps ``datasets`` OUT of the default install (the fixture path needs neither network
    nor the lib). If the extra is absent we raise a clear, actionable error. The producer is the HF
    SPLIT name; ``producer=None`` loads every split for the task.
    """
    try:
        from datasets import (  # type: ignore[import-not-found, unused-ignore]
            get_dataset_split_names,
            load_dataset,
        )
    except ImportError as exc:  # pragma: no cover - exercised only without the optional [bench] extra
        raise ImportError(
            "CodeJudgeBench online load needs the HF 'datasets' library. Install the optional "
            "extra: pip install 'prism-verify[bench]'  (the --offline fixture path needs neither "
            "network nor datasets)."
        ) from exc

    producers = (
        [producer]
        if producer is not None
        else list(get_dataset_split_names("mattymchen/codejudgebench", config_name=task))
    )
    items: list[CJBItem] = []
    for split in producers:
        ds = load_dataset("mattymchen/codejudgebench", name=task, split=split)
        for index, row in enumerate(ds):  # row is a dict-like mapping of column -> value
            items.append(_row_to_item(dict(row), task=task, producer=split, index=index))
            if limit is not None and len(items) >= limit:
                return items
    return items


def load_codejudgebench(
    task: str | None = None,
    limit: int | None = None,
    *,
    producer: str | None = None,
    offline: bool = False,
    fixture: Path = DEFAULT_FIXTURE,
) -> list[CJBItem]:
    """Load CodeJudgeBench items as ``CJBItem``s.

    ``offline=True`` reads the committed fixture (no network, no ``datasets``). Otherwise the HF
    online path is used (lazy ``datasets`` import; ``task`` is REQUIRED there since it is the HF
    config name). ``producer`` filters to one HF split (model); ``limit`` caps the loaded slice.
    Columns are ANDON-validated on every row (a renamed pos/neg fails loud — see ``CJBColumnError``).
    """
    if offline:
        return load_codejudgebench_offline(task, limit, source=fixture)
    if task is None:
        raise ValueError(
            "online load_codejudgebench needs an explicit task (one of "
            f"{CJB_TASKS}); the HF config name selects the task. Use offline=True for the fixture."
        )
    if task not in CJB_TASKS:
        raise ValueError(f"unknown CodeJudgeBench task {task!r}; expected one of {CJB_TASKS}")
    return _load_hf(task, producer, limit)


def cjb_content_hash(items: list[CJBItem]) -> str:
    """Deterministic SHA-256 over the canonicalized item set (mirrors corpus.corpus_content_hash).

    A FINGERPRINT OF CONTENT, not file layout: each item is canonicalized to sorted-key JSON, the
    per-item strings are sorted, and the schema id is prefixed. A count-preserving content edit flips
    the hash (drift visible); a reorder or identical reload leaves it unchanged. The run carries this
    so a reader can assert numbers were measured on exactly this slice.
    """
    canonical = sorted(json.dumps(it.to_dict(), sort_keys=True) for it in items)
    digest = hashlib.sha256()
    digest.update(CONTENT_HASH_SCHEMA.encode("utf-8"))
    digest.update(b"\x00")
    for line in canonical:
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()
