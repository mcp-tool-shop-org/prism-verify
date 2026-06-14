"""Unit tests for the optional orthogonal NLI floor — the torch-free paths (gating + abstain)
plus the label->verdict mapping with an INJECTED fake scorer.

The actual NLI inference needs the optional ``nli`` extra (torch + transformers), which CI does
not install. What MUST hold without torch: the env gate, and that the floor abstains (returns
None) rather than raising when the extra is absent.

TST-A-001: the original-only assertion (``nli_groundedness(...) is None``) is correct ONLY when
torch is absent, so replacing the real inference branch with ``return None`` would pass the whole
suite. The ``TestNliVerdictMappingWithFakeScorer`` class below closes that hole: it injects a fake
cross-encoder (a fake ``_load`` + a fake ``torch`` in ``sys.modules``) returning KNOWN logits, then
asserts the real entailment/contradiction/neutral -> supported/refuted/insufficient mapping. Those
tests FAIL if anyone stubs the real veto logic to ``return None``.
"""

from __future__ import annotations

import sys
import types

import prism.lenses.nli as nli
from prism.lenses.nli import nli_floor_enabled, nli_groundedness


class TestNliFloorEnabled:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("PRISM_NLI_FLOOR", raising=False)
        assert nli_floor_enabled() is False

    def test_enabled_truthy(self, monkeypatch):
        for value in ("1", "true", "yes", "on", "ON", "True"):
            monkeypatch.setenv("PRISM_NLI_FLOOR", value)
            assert nli_floor_enabled() is True

    def test_disabled_falsey(self, monkeypatch):
        monkeypatch.setenv("PRISM_NLI_FLOOR", "0")
        assert nli_floor_enabled() is False


class TestNliGroundednessGracefulAbsence:
    def test_returns_none_without_torch(self):
        # Optional `nli` extra is absent in CI; the floor must abstain (None), never raise, so the
        # engine simply keeps the LLM-lens verdict. (Kept: the graceful-degradation guarantee.)
        assert nli_groundedness("a claim", "a source") is None


class _FakeInputs(dict):
    """Tokenizer output: a dict (so ``model(**inp)`` unpacks) whose ``.to(dev)`` is a no-op."""

    def to(self, _dev):
        return self


class _FakeTokenizer:
    def __call__(self, source, claim, **_kw):
        return _FakeInputs(source=source, claim=claim)


class _FakeLogits:
    """``model(**inp).logits`` -> indexable; ``[0]`` is the per-example logit vector (a sentinel
    the fake ``torch.softmax`` turns into the KNOWN probability vector)."""

    def __init__(self, probs):
        self._probs = probs

    @property
    def logits(self):
        return [self._probs]  # logits[0] == self._probs


class _FakeModel:
    def __init__(self, probs):
        self._probs = probs

    def __call__(self, **_inp):
        return _FakeLogits(self._probs)


class _FakeSoftmaxResult:
    def __init__(self, probs):
        self._probs = probs

    def tolist(self):
        return self._probs


def _install_fake_torch(monkeypatch):
    """Inject a minimal fake ``torch`` so ``import torch`` inside ``nli_groundedness`` succeeds
    torch-free. ``no_grad()`` is a context manager; ``softmax(vec, dim)`` returns the vec verbatim
    (our fake model already emits a normalized probability vector)."""
    import contextlib

    fake_torch = types.ModuleType("torch")
    fake_torch.no_grad = contextlib.nullcontext
    fake_torch.softmax = lambda vec, _dim: _FakeSoftmaxResult(vec)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)


def _inject_scorer(monkeypatch, probs, id2label):
    """Replace the cross-encoder load seam with a fake that returns KNOWN logits + labels, and a
    fake torch, so the REAL label->verdict mapping in ``nli_groundedness`` runs without torch."""
    _install_fake_torch(monkeypatch)
    monkeypatch.setattr(
        nli, "_load", lambda _model_id: (_FakeTokenizer(), _FakeModel(probs), "cpu", id2label)
    )


class TestNliVerdictMappingWithFakeScorer:
    """TST-A-001: exercise the floor's REAL label->verdict integration logic with an injected fake
    cross-encoder. Each test asserts a concrete verdict, so stubbing the inference to ``return
    None`` (or breaking the mapping) FAILS here — the original vacuous ``is None`` test would not
    catch it.
    """

    _LABELS = {0: "entailment", 1: "neutral", 2: "contradiction"}

    def test_entailment_above_tau_is_supported(self, monkeypatch):
        # P(entailment)=0.9 >= tau(0.55) and entailment is top -> supported (the veto's NO-op case).
        _inject_scorer(monkeypatch, [0.9, 0.05, 0.05], self._LABELS)
        assert nli_groundedness("X holds", "We show X holds.") == "supported"

    def test_entailment_below_tau_is_insufficient(self, monkeypatch):
        # Asymmetric tau gate: entailment top but P(entailment)=0.50 < tau(0.55) -> NOT supported.
        _inject_scorer(monkeypatch, [0.50, 0.45, 0.05], self._LABELS)
        assert nli_groundedness("X holds", "Maybe X holds.") == "insufficient"

    def test_contradiction_is_refuted(self, monkeypatch):
        # The load-bearing veto case: a contradiction top label -> refuted (downgrades a "supported"
        # LLM verdict to ESCALATE in the engine). A ``return None`` stub would fail this assertion.
        _inject_scorer(monkeypatch, [0.05, 0.05, 0.90], self._LABELS)
        assert nli_groundedness("X holds", "X does not hold.") == "refuted"

    def test_neutral_is_insufficient(self, monkeypatch):
        _inject_scorer(monkeypatch, [0.10, 0.80, 0.10], self._LABELS)
        assert nli_groundedness("X holds", "Unrelated text.") == "insufficient"

    def test_tau_override_argument_is_honored(self, monkeypatch):
        # An explicit tau=0.95 makes a P(entailment)=0.9 fall short -> insufficient, proving the
        # threshold logic (not just the argmax) is wired through the real mapping.
        _inject_scorer(monkeypatch, [0.90, 0.05, 0.05], self._LABELS)
        assert nli_groundedness("X holds", "We show X holds.", tau=0.95) == "insufficient"

    def test_env_tau_override_is_honored(self, monkeypatch):
        # PRISM_NLI_TAU raises the bar to 0.95: a P(entailment)=0.9 entailment-top now falls short
        # -> insufficient, proving the env override is wired through (not just the tau= argument).
        monkeypatch.setenv("PRISM_NLI_TAU", "0.95")
        _inject_scorer(monkeypatch, [0.90, 0.05, 0.05], self._LABELS)
        assert nli_groundedness("X holds", "We show X holds.") == "insufficient"

    def test_invalid_env_tau_falls_back_to_default(self, monkeypatch):
        # A garbage PRISM_NLI_TAU must not crash the floor; it falls back to the default (0.55), so
        # a P(entailment)=0.90 entailment-top still resolves -> supported.
        monkeypatch.setenv("PRISM_NLI_TAU", "not-a-float")
        _inject_scorer(monkeypatch, [0.90, 0.05, 0.05], self._LABELS)
        assert nli_groundedness("X holds", "We show X holds.") == "supported"
