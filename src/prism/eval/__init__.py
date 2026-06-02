"""Prism evaluation pack (Slice 1).

Calibration corpus + benchmark that MEASURES — on prism's own labeled data — what the four
architectural locks currently only ASSERT: per-lens precision/recall, the inter-lens agreement
(diversity) matrix, the submodular coverage-gain, confidence calibration, and a data-calibrated
submodularity-threshold interval. See ``design/07-slice1-calibration.md`` for grounding.

Public surface is intentionally small; the CLI (`prism eval`) is the primary entry point.
"""

from __future__ import annotations

__all__ = ["metrics", "corpus"]
