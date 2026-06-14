"""Orthogonal NLI floor (optional) — a mechanistically-different groundedness check.

prism's citation groundedness lens is a reasoning-stripped LLM. Two LLMs (even different
families) share some CORRELATED blind spots; an ENCODER NLI cross-encoder fails differently (a
discriminative classifier, not a generator), so as a veto on the LLM lens's "supported" it
catches a class of false-confirm the LLM shares. This is the wave-10 mechanistically-orthogonal
floor (tensor-engine-knowledge), here a post-groundedness veto in the citation path.

OPT-IN + OPTIONAL. It needs the ``nli`` extra (torch + transformers) and is gated by
PRISM_NLI_FLOOR. If the extra or the model is unavailable, ``nli_groundedness()`` returns None
(abstain) and the engine keeps the LLM-lens verdict — so the default install stays lightweight
and CI is unchanged.

Env:
  PRISM_NLI_FLOOR   truthy -> the engine runs this floor as a veto after the groundedness lens
  PRISM_NLI_MODEL   the HF model id (default below)
  PRISM_NLI_TAU     P(entailment) threshold to call "supported" (default 0.55; asymmetric — only
                    the "supported" call is thresholded, since over-escalation is the safe failure)
"""

from __future__ import annotations

import functools
import os
from typing import Any, Literal

_TRUE = {"1", "true", "yes", "on"}
DEFAULT_MODEL = "MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli"
# P(entailment) threshold to call a claim "supported". Asymmetric on purpose: only the "supported"
# call is thresholded, since over-escalation (refuted/insufficient) is the safe failure for a veto.
# 0.55 is a deliberately modest bar — the floor is a corroboration check, not the primary lens.
# Override per-process with PRISM_NLI_TAU; override per-call with the ``tau=`` argument.
DEFAULT_TAU = 0.55
NLIVerdict = Literal["supported", "refuted", "insufficient"]


def nli_floor_enabled() -> bool:
    """True iff PRISM_NLI_FLOOR is set truthy (the engine then runs this floor as a veto)."""
    return os.getenv("PRISM_NLI_FLOOR", "").strip().lower() in _TRUE


def _tau() -> float:
    """The effective P(entailment) "supported" threshold: PRISM_NLI_TAU if set and parseable as a
    float, else DEFAULT_TAU. A garbage env value falls back to the default rather than raising."""
    try:
        return float(os.getenv("PRISM_NLI_TAU", str(DEFAULT_TAU)))
    except ValueError:
        return DEFAULT_TAU


@functools.lru_cache(maxsize=2)
def _load(model_id: str) -> tuple[Any, Any, str, dict[int, str]] | None:
    """(tokenizer, model, device, id2label), or None if the optional ``nli`` extra is absent."""
    try:  # pragma: no cover - exercised only with the optional torch extra installed
        import torch  # type: ignore[import-not-found, unused-ignore]
        from transformers import (  # type: ignore[import-not-found, unused-ignore]
            AutoModelForSequenceClassification,
            AutoTokenizer,
        )

        tok = AutoTokenizer.from_pretrained(model_id)
        model = AutoModelForSequenceClassification.from_pretrained(model_id)
        model.eval()
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        model.to(dev)
        id2label = {int(k): str(v).lower() for k, v in model.config.id2label.items()}
        return tok, model, dev, id2label
    except Exception:
        return None


def nli_groundedness(
    claim: str, source: str, *, model_id: str | None = None, tau: float | None = None
) -> NLIVerdict | None:
    """Encoder-NLI entailment of CLAIM by SOURCE -> supported | refuted | insufficient, or None
    when the optional NLI extra/model is unavailable (the engine keeps the LLM-lens verdict).

    Mapping (premise=source, hypothesis=claim): entailment->supported, contradiction->refuted,
    neutral->insufficient. Asymmetric: "supported" only if P(entailment) >= tau.
    """
    loaded = _load(model_id or os.getenv("PRISM_NLI_MODEL", DEFAULT_MODEL))
    if loaded is None:
        return None
    tok, model, dev, id2label = loaded  # pragma: no cover - needs the optional torch extra
    import torch

    inp = tok(source, claim, truncation=True, max_length=512, return_tensors="pt").to(dev)
    with torch.no_grad():
        probs = torch.softmax(model(**inp).logits[0], -1).tolist()
    scores: dict[str, float] = {id2label[i]: float(probs[i]) for i in range(len(probs))}
    threshold = _tau() if tau is None else tau
    top = max(scores, key=lambda k: scores[k])
    if top == "entailment":
        return "supported" if scores.get("entailment", 0.0) >= threshold else "insufficient"
    if top == "contradiction":
        return "refuted"
    return "insufficient"
