# Prism calibration benchmark — RESULTS

The snapshot the README/landing scorecard cites **from actual numbers**, produced by `prism eval`
over `eval/corpus/`. Methodology + research grounding:
[`design/07-slice1-calibration.md`](../design/07-slice1-calibration.md).

**Run:** 2026-06-02 · verifier **local Ollama `mistral-small:24b`** (caller family `anthropic`;
Lock 1 routes verification to the local family) · `--split public` (41 samples: code 20, tool_call
12, citations 9) · `--runs 3`. Reproduce: `prism eval --split public --runs 3 --out eval/report`
(needs Ollama up with `mistral-small:24b`, `PRISM_DEV=1` for a local signing key).

> **v1 corpus is small + authored/lens-targeted** (min 3 positives/lens « 100): recall CIs are wide
> (shown below) and the headline findings are *directional*, not statistically tight. Real-bug
> ingestion (BugsInPy) + a larger corpus is the v1.1 upgrade. These are real measurements, not mock.

## Headline

| Metric | Value |
|---|---|
| Verifier | local Ollama `mistral-small:24b` |
| Per-lens MCC (contract / cross_boundary / invariant / groundedness) | **1.00 / 0.45 / 1.00 / 0.71** |
| Krippendorff alpha (lens decisions) | **0.545** — moderate agreement; lenses are *not* highly independent |
| Union coverage recall / coverage gain | **1.00 / 0** — the union does NOT beat the best single lens here |
| Data-calibrated rho operating point | **n/a** — finding-set rho is 0.0 for every pair (degenerate sweep) |
| Same-family A/B delta (Lock 1) | not run (needs a 2nd family configured) |
| Overall verdict accuracy / ECE / Brier | **0.78** / 0.176 / 0.182 |

## Per-lens quality (on each lens's target class)

| Lens | n | pos | recall (95% CI) | precision | specificity | MCC | bal-acc |
|---|---|---|---|---|---|---|---|
| contract_completeness | 6 | 3 | 1.000 [0.44, 1.00] | 1.000 | 1.000 | 1.000 | 1.000 |
| cross_boundary | 12 | 6 | 1.000 [0.61, 1.00] | 0.600 | 0.333 | 0.447 | 0.667 |
| invariant | 8 | 4 | 1.000 [0.51, 1.00] | 1.000 | 1.000 | 1.000 | 1.000 |
| groundedness | 6 | 3 | 0.667 [0.21, 0.94] | 1.000 | 1.000 | 0.707 | 0.833 |

Verdict accuracy by class: **code 0.95**, citations 0.78, **tool_call 0.50**. Cross-run consistency 0.967.

## Findings (what the measurement actually surfaced)

1. **The runtime rho metric is blind to the lens correlation that kappa reveals — the headline
   result.** Finding-set rho (Jaccard over `(file, line, category)`) is **0.000 for every lens
   pair**, so the runtime submodularity gate (`rho <= 0.25`) would *never* fire. Yet the
   decision-level agreement (Cohen kappa) is **high** — contract↔cross_boundary 0.81,
   contract↔invariant 0.81, cross_boundary↔invariant 0.73. The lenses make strongly *correlated*
   PASS/FAIL decisions while placing findings at different locations. This empirically confirms the
   study-swarm's Kuncheva–Whitaker warning (rho alone is a weak predictor) **and** shows prism's
   specific metric — finding-location Jaccard — does not detect decision redundancy. **Design
   implication:** a future slice should evaluate a decision-correlation signal (kappa) for the
   submodularity gate, not finding-location overlap alone.

2. **Coverage gain = 0: the union does not beat the best single lens on this corpus.**
   `contract_completeness` alone catches all 16 code/tool positives (greedy marginal:
   contract `+16` → cross_boundary `+0` → invariant `+0` → groundedness `+0`). The
   "union beats any single lens" submodular thesis does **not** hold here — the lenses are
   redundant for coverage. Caveat: small authored corpus, and the lenses over-flag (see #3), so
   "catches every positive" is partly trigger-happiness, not pure skill.

3. **`cross_boundary` over-flags clean tool-calls** — precision 0.60, specificity 0.333 — which
   drags tool_call verdict accuracy to 0.50. The v1 "first-cut" boundary prompt fires on clean
   tool-calls; this is the clearest single lens-quality fix the data points to.

4. **`groundedness` missed 1 of 3** planted fabrications (recall 0.667); `contract_completeness`
   and `invariant` were perfect on their (tiny) target classes.

5. **Confidence is moderately mis-calibrated** (ECE 0.176): the reported confidence is ~17% off
   observed accuracy on average. Worth a calibration pass once the corpus is larger.

6. **The rho-threshold sweep is degenerate** (all rho = 0), so 0.25 cannot be validated or
   recalibrated from this corpus — which is itself the evidence for finding #1. The runtime default
   stays 0.25, unchanged, pending a metric/corpus that produces varied rho.

## L5 Style/Maintainability lens — ship/defer gate

Slice 1 builds the **gate**, not the lens (data, not vibes — design/07 §E). Ship criteria: a labeled
style corpus of ≥100 items with ≥2–3 independent human labels, inter-rater Krippendorff alpha ≥ 0.6,
candidate-L5 precision ≥ 0.8 per category, and a submodularity guard (L5 alone never triggers
ESCALATE; drop any category correlated with SLOC or the correctness lenses).

**Decision: DEFER.** No L5 lens and no human-labeled style corpus exist, so the gate cannot be met.
The evidence (Bacchelli & Bird ICSE 2013; weak maintainability-metric validity; LLM judges reliable
only on large quality gaps) supports a *narrow* future L5 — never scalar "maintainability scores" —
and only once the corpus clears the bar.

## CodeJudgeBench (pairwise: prism single-artifact → preference)

prism is single-artifact, but [CodeJudgeBench](https://huggingface.co/datasets/mattymchen/codejudgebench)
(arXiv:2507.10535, Apache-2.0) is pairwise. The harness (`src/prism/eval/benchmarks/`) verifies the
**chosen** and **rejected** code separately and reduces the two verdicts to a preference via
`calibrate.pairwise_prefer` (accept > escalate > revise > refuse, tie-break by confidence). A result
is **correct iff prism prefers the chosen side**; a **tie counts as WRONG** in the headline accuracy
(a tie on a known good-vs-bad pair is a real discrimination failure) and is reported separately as a
tie-rate. Both response orders are run (N ≥ 3) to measure **position consistency** (the paper reports
order substantially affects judge accuracy).

Reproduce (real): `pip install 'prism-verify[bench]'` then
`prism eval --benchmark codejudgebench --bench-task codegen --bench-limit 50`. Offline machinery
smoke (mock verifier, committed fixture — NOT a measurement):
`prism eval --benchmark codejudgebench --offline`.

The machinery + offline-fixture tests ship now; the headline numbers below need a real verifier run
(local Ollama zero-cost first pass; hosted for the published headline — director-gated).

| Bucket | Accuracy (95% CI) | Tie-rate | Position consistency |
|---|---|---|---|
| overall | (pending real run) | (pending real run) | (pending real run) |
| codegen | (pending real run) | (pending real run) | (pending real run) |
| coderepair | (pending real run) | (pending real run) | (pending real run) |
| testgen | (pending real run) | (pending real run) | (pending real run) |

> The default suite + the offline fixture path need **neither** network **nor** the HF `datasets`
> lib (the `[bench]` extra). The cap matters: both-orders × N ≥ 3 × 2 sides = up to 12 verify
> calls/pair, so `--bench-limit` is load-bearing for spend; a published number needs a full-split run.

## Next

- v1.1 corpus: real-bug ingestion (BugsInPy/Defects4J) + a post-cutoff contamination split, larger N
  to tighten the CIs.
- Investigate the `cross_boundary` over-flagging (finding #3) and trial a kappa-based diversity gate
  (finding #1).
- The same-family A/B (`--family-ab`) needs a 2nd configured family; the CodeJudgeBench headline
  needs a real verifier run (machinery + fixture tests already ship — see the section above).
