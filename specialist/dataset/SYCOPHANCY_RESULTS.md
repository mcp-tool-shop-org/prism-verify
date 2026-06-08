# Sycophancy watcher (wedge #2) — mint v1 results

**Verdict: v1 PASSED the mandatory OOD generalization gate.** The first wedge retrain to pass OOD cleanly
on attempt 1 (conformance-v0.2 and verifier-v2 both lifted the exam but died on OOD). Served artifact =
`sycophancy-14b-soup`. Pre-promotion — serving/wiring is Mike-gated. Authored 2026-06-08.

## Pipeline (cloned the verifier press unchanged; context→evidence, response→claim)
1. **Design:** `design/sycophancy-wedge-dispatch.md`, study-swarm-grounded (`wf_ba8b367b-c67`), Step-4 citation
   gate PASSED 21/21 through `roleos verify-citations` → prism.
2. **Dataset:** 2 author waves (115 agents, `wf_7eb52992-9a2` + `wf_bb3e546a-188`) → **1116 records, AUDIT PASS**
   (558/558 flip-ready, 0 torn, 0 leakage). 970 train / 146 exam (domain-atomic: 20 train domains, 3 held-out).
   5-rung curriculum (false-premise · belief-match · face-preservation · agreement-precision · abstain).
3. **Train:** Qwen3-14B QLoRA, rsLoRA r16/α32, batch2/accum8, 600 steps, 2 seeds (42, 1337), under the
   gpu_container watchdog (peaked 72°C / 94% power, no breach). `BUDGETER_TAG=sycophancy-14b600`.
4. **Soup:** `soup_adapters.py` (merged-space ΔW avg + SVD r16, 280 layers) → `sycophancy-14b-soup`.
5. **Certify (held-out exam) + OOD dogfood (8 novel, independently-authored domains, `wf_4d301247-619`).**

## Numbers (served at llama.cpp --lora scale 4; cost-asymmetric: dangerous = false all-clear)

| metric | exam (3 held-out) | **OOD (8 novel)** |
|---|---|---|
| overall acc | 0.897 | 0.901 |
| **flip-consistency** | 0.822 | **0.817** |
| false-all-clear rate | 0.057 | 0.019 |
| cost-weighted error | 0.155 | 0.120 |

**OOD ≈ exam → generalizes, no overfit collapse.** Soup > both seeds on exam (flip 0.822 vs 0.808/0.808).
flip-consistency has ±~0.04 run-to-run variance at temp 0.1 (a live console read showed 0.863 exam; the
persisted file is 0.822 — the OOD≈exam conclusion is robust to the variance).

**Per-rung OOD flip:** L1 false-premise **0.974** · L2 belief-match 0.857 · L3 face-preservation 0.800 ·
**L4 agreement-precision 0.595 (the weak rung)** · L5 abstain 0.850.

## The honest weakness + v0.2 target
**L4 (agreement-precision)** — the regressive-vs-progressive call ("is this agreement sycophantic or
legitimate deference?") — is the hardest semantic rung and the only one that degrades OOD (0.595 flip).
v0.2 = more L4 contrast pairs (shared_response shape: identical agreeable reply, user-correct vs user-wrong),
the same way conformance grew its weak rung. Everything else (false-premise, belief-match, abstain)
generalizes well.

## Artifacts
- Adapters: `E:/AI-Models/adapters/{budgeter-sycophancy-14b600-seed42,-seed1337,sycophancy-14b-soup}` (+ .gguf)
- Dataset: `sycophancy_{records,train_sft,exam_records,ood}.jsonl` + `sycophancy_config.py`
- Scripts (reuse): `build_sycophancy_records.mjs`, `build_sycophancy_ood.mjs`, `certify_sycophancy.py`,
  `train_sycophancy.ps1`, `certify_all_sycophancy.ps1`, `dogfood_sycophancy.ps1`
- Certs: `certify/sycophancy-{seed42,seed1337,soup,ood-soup}.json`

## Mike-gated next
1. Promote/serve `sycophancy-14b-soup` as the prism sycophancy lens v1 (a new `prism.lenses.sycophancy`,
   passive single-pass per the dispatch's v1 scope), behind an opt-in flag like the other specialists.
2. v0.2: lift L4 (agreement-precision) with more shared_response contrast pairs + re-run the OOD gate.
3. Design note for review: cost-asymmetry was set to the fleet's "never falsely reassure" pattern (dangerous
   = false `not_sycophantic`, fail-open to abstain) — a refinement of the dispatch's "fail open toward
   not-sycophantic" framing.
