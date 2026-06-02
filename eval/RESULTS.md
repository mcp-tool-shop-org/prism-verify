# Prism calibration benchmark — RESULTS

This is the committed snapshot the README/landing scorecard cites **from actual numbers** (not
estimates). It is produced by `prism eval` over the labeled corpus in `eval/corpus/`. Methodology
and research grounding: [`design/07-slice1-calibration.md`](../design/07-slice1-calibration.md).

> **Status: PENDING THE REAL RUN.** The numbers below are placeholders. A real measurement requires
> configured providers (local Ollama, e.g. `mistral-small:24b`, or a hosted family API key) — the
> `--offline` mode is a deterministic CI smoke whose numbers are **not** a measurement. Regenerate
> with, e.g.:
>
> ```bash
> prism eval --split all --runs 3 --family-ab --report md --out eval/report
> # then copy eval/report/report.md's tables into the sections below + commit
> ```

## What is measured

- **Per-lens quality** on each lens's target class: precision / recall (with a 95% Wilson interval) /
  MCC / balanced accuracy. MCC leads; accuracy alone is never reported (a rubber-stamp lens scores
  high accuracy at MCC≈0 — the failure prism exists to expose).
- **Diversity matrix** — Krippendorff's alpha over the lens decisions + the pairwise Cohen's kappa
  matrix + the runtime finding-set rho. (Lower alpha/kappa = more independent signal.)
- **Submodular coverage-gain** — does the union of lenses beat the best single lens? The greedy
  marginal-gain curve flags any redundant (+0) lens. This is the **primary** collapse signal;
  rho is a cheap secondary tripwire (Kuncheva & Whitaker: rho alone is a weak predictor).
- **Submodularity-threshold (rho) calibration** — sweeps the refusal cutoff on prism's own data.
  Note: **0.25 is Rajan's *observed* correlation ceiling, not a validated refusal gate.** This run
  reports the data-calibrated operating point; the runtime default stays 0.25 until a real,
  varied-rho run justifies a change.
- **Verdict accuracy + calibration** (ECE / Brier), and an optional **same-family A/B** that
  demonstrates Lock 1 (a same-family verifier self-prefers and misses defects; Panickssery 2024).

## Headline numbers

_To be filled by the first real run (see Status above)._

| Metric | Value |
|---|---|
| Verifier (model/family) | _pending_ |
| Per-lens MCC (contract / boundary / invariant / groundedness) | _pending_ |
| Krippendorff alpha (lens decisions) | _pending_ |
| Union coverage recall / coverage gain | _pending_ |
| Data-calibrated rho operating point | _pending_ |
| Same-family A/B delta (Lock 1) | _pending_ |
| ECE / Brier | _pending_ |

## L5 Style/Maintainability lens — ship/defer gate

Slice 1 builds the **gate that decides L5**, it does not ship L5 (data, not vibes — design/07 §E).

**Ship criteria (all required):** a labeled style corpus of ≥100 items, each with ≥2–3 independent
human labels; inter-rater **Krippendorff alpha ≥ 0.6**; candidate-L5 **precision ≥ 0.8** per
category; and a **submodularity guard** — L5 alone may never trigger ESCALATE (corroborate /
REVISE-annotate only), and any L5 category whose findings correlate with SLOC or with the
correctness lenses is dropped.

**Decision: DEFER.** As of this slice there is no L5 lens and no human-labeled style corpus, so the
gate cannot be met. The evidence (Bacchelli & Bird ICSE 2013; weak maintainability-metric validity;
LLM judges reliable only on large quality gaps) supports a *narrow* future L5 (dead code, unused
symbols, intra-diff naming/format inconsistency) — never scalar "maintainability scores" — and only
once the corpus above clears the bar. Until then: **deferred.**
