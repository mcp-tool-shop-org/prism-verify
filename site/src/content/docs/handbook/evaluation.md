---
title: Calibration & benchmark
description: prism eval measures the lenses on a labeled corpus — per-lens precision/recall, the inter-lens diversity matrix, submodular coverage-gain, and a data-calibrated submodularity threshold.
sidebar:
  order: 4
---

prism's four locks are *claims*. `prism eval` turns them into *measurements*: it runs the lenses
over a labeled corpus and reports, on prism's own data, what the locks otherwise only assert.

## Run it

```bash
prism eval --split public --runs 3     # measure against the bundled corpus (needs a verifier)
prism eval --offline                    # deterministic mock — a CI smoke, NOT a measurement
prism eval --family-ab                  # add a same-family control to A/B-test Lock 1
```

A real run needs a verifier the way `prism verify` does — local Ollama (`mistral-small:24b`) or a
hosted family key — with `PRISM_DEV=1` (or a real signing key) so the run-receipt can be written.
The report (markdown + json) lands in `--out` (default `eval/report/`) beside a signed run-receipt;
`prism eval` halts before reporting if a corpus-integrity check fails (the ANDON gate).

## What it measures

- **Per-lens quality** on each lens's target class — precision, recall (with a Wilson 95% CI), and
  **MCC** (honest under class imbalance, where raw accuracy is not).
- **Diversity matrix** — Krippendorff's α over the lens decisions plus the pairwise Cohen κ matrix,
  beside the runtime finding-set ρ.
- **Submodular coverage-gain** — does the *union* of lenses beat the best *single* lens? A lens
  whose marginal gain is zero is, on that corpus, redundant.
- **Submodularity-threshold (ρ) sweep** — the data-driven operating point, because the 0.25 default
  is a *borrowed* number (Rajan's observed correlation ceiling), not one validated on prism's data.
- **Verdict accuracy + calibration** (ECE / Brier), and an optional same-family **A/B** that
  *demonstrates* Lock 1 rather than asserting it.

## What the first real run found

The v0.5 run (local `mistral-small:24b`, public split) surfaced a genuine gap in a core lock:

> The runtime submodularity metric — finding-set Jaccard ρ — reads **0.0 for every lens pair**, so
> the `ρ ≤ 0.25` gate never fires. Yet decision-level **Cohen κ is 0.73–0.81** for three of the
> pairs. The lenses make strongly *correlated* PASS/FAIL decisions while placing findings at
> different locations — the gate is blind to the redundancy κ reveals.

That is exactly what the slice exists to catch: a measurement contradicting an assumption. It points
a future slice at a κ-based diversity gate. The full table, the per-lens numbers, and the caveats
(the v1 corpus is small + authored, so the CIs are wide) live in
[`eval/RESULTS.md`](https://github.com/mcp-tool-shop-org/prism-verify/blob/main/eval/RESULTS.md);
the research grounding is in
[`design/07`](https://github.com/mcp-tool-shop-org/prism-verify/blob/main/design/07-slice1-calibration.md).

## The L5 lens gate

Slice 1 also builds the **gate that decides** whether a fifth Style/Maintainability lens should
ship — not the lens itself. The bar (a human-labeled style corpus, inter-rater α ≥ 0.6, candidate
precision ≥ 0.8, and a submodularity guard) is not yet met, so L5 stays **deferred**. Data, not vibes.
