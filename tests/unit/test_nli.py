"""Unit tests for the optional orthogonal NLI floor — the torch-free paths (gating + abstain).

The actual NLI inference needs the optional ``nli`` extra (torch + transformers), which CI does
not install. What MUST hold without torch: the env gate, and that the floor abstains (returns
None) rather than raising when the extra is absent.
"""

from __future__ import annotations

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
        # engine simply keeps the LLM-lens verdict.
        assert nli_groundedness("a claim", "a source") is None
