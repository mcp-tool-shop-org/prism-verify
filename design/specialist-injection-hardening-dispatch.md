# Hardening the oversight watchers against prompt injection — research-grounded decision dispatch

**Status:** Step-4 citation gate RUN (locked path `roleos verify-citations` → prism, `design/_run_fleet_gate.mjs`).
**Verdict `revise` (advisory, non-blocking); 0 FABRICATED, 0 METADATA-MISMATCHED across all 26 parsed citations —
every identifier resolved with the correct title** (the arXiv window had reset, so no rate-limit tail this run).
Signed receipt `prism-01ktkq71ezb7vc6xh3n4xtxn5j` (`citations_sha256 59e0ee53…`); full result
`design/specialist-injection-hardening-gate-result.json`. Breakdown: **9 full ACCEPT** (existence + groundedness —
incl. Instruction Hierarchy, DataFlip, Tripathi, Ovadia, Critical-Evaluation, Maloyan committee, When-Benchmarks-Lie
×2, Shah, CaMeL); **2 `contradicted`→revise** = the deterministic numeric guard flagging a *body* figure against the
*abstract's* headline number ([3] SecAlign "8%" vs abstract "10%"; [18] Li body tables vs abstract summary) — both
**remediated by demoting the precise figures to body parentheticals**, neither a fact error; the rest `not_addressed`→
escalate = groundedness-from-abstract conservatism / no-abstract DOIs (body-sourced specifics). **2 unparsed** = prose
lines (incl. the PoisonedRAG finding, which has no arXiv/DOI — WebSearch-confirmed: Zou et al., USENIX Security 2025).
The three critic-surfaced NEW axes (CaMeL 2503.18813, PoisonedRAG, When-Benchmarks-Lie 2602.14161) were
independently WebSearch-confirmed before synthesis. **No finding is load-bearing on an unverified or fact-contradicted
citation.** **Authored:** 2026-06-08. **Via:** study-swarm `wf_cbbbe6fb-917` (5 web-research
agents, one per decision question + a completeness critic) — fired on Mike's explicit "study swarm" trigger when
the A/B/C hardening fork proved to be a qualitative design decision where current 2025-2026 evidence changes the
answer. **Scope:** how to harden the three LIVE watchers (conformance, sycophancy, citation) against prompt
injection at runtime, fail-open, WITHOUT invalidating the fine-tuned specialists' flip-consistency + OOD
certification. **The critic reframed the question** (correctly): the answer is **per-DUTY**, not a single
fleet-wide A/B/C pick, and two axes the A/B/C frame omits are load-bearing (corpus poisoning upstream of the
citation judge; consume-side capability-gating). NOT a build order — a Mike-gated design.

## The decision (up front — the evidence is decisive)

**Anchor on A (a SEPARATE, cross-family, contamination PRE-FILTER on a normalized COPY → fail-open ABSTAIN,
judge input byte-for-byte untouched) — but explicitly as a fail-open COVERAGE floor, never a security
guarantee — and apply it PER-DUTY:**

| Duty | Load-bearing defense (certification-preserving) | Why |
|---|---|---|
| **Conformance (tool-call)** | The **deterministic schema/contract FLOOR already shipped** carries it; the LLM ceiling gets the shared pre-filter + input normalization. | Generic guardrails detect only **7-37%** of agentic tool injection and architecturally can't evaluate it at all [21]. A prose detector is near-useless here; the mechanical floor is the defense. |
| **Sycophancy** | **A** (separate decorrelated contamination detector → ABSTAIN, input untouched) layered on the **already-banked cross-family committee** + guarded abstain. Do **NOT** flip to pairwise. | The certified 14B specialist is in the most-injection-vulnerable band [7]; push the defense OFF the small judge onto the detector + committee [16]. Pairwise resists injection [16,18] but is **worse** for spurious-feature manipulation — exactly sycophancy's threat [12]. |
| **Citation** | **Spotlight** the general-model groundedness lens (free — not certified) **+ retrieval-stage hygiene/provenance**: the real threat is **corpus poisoning upstream** of the judge, which A/B/C don't touch [22]. | The retrieval oracle is already a provenance anchor; the dominant attack (~90% ASR with ~5 docs) lands before the judge input [22]. |
| **Cross-cutting (all)** | **Input normalization / de-smuggling** on the detector's COPY (NFKC, strip zero-width / Unicode-tag / emoji-variation) + **guarded abstain channel** + **consume-side capability-gating** of what a flipped verdict can DO. | Char-smuggling bypasses production detectors at up to **100%** ASR [9]; the abstain channel is itself a DoS surface [23-26]; CaMeL-style consume-side limits the blast radius of any flipped verdict, model unmodified [27]. |

**Why A is the anchor, not B (spotlight the specialist input) or C (re-mint):** the entire moat is a
**fixed-input-shape certification** (flip-consistency + held-out OOD gate). A is the **only** option that does
not alter the certified input distribution — Ovadia 2019 [13] establishes any input transform (B) or weight
change (C) moves a calibrated model off its operating point and voids the cert by construction; Liu & Gong 2024
[14] measure detection defenses at **~0% FPR with input unchanged** vs a **~0.14 accuracy tax** for transform-style
prevention. **But A is security-weak** (adaptively evadable — DataFlip drives KAD detection to **0%** while
keeping **91%** ASR [11]; over-ABSTAINs on the long-context inputs judges consume [10]), so it is a coverage
floor on top of the committee, not the protection itself.

**The one pivot the literature cannot resolve — it's studio-internal:** the A-over-C preference rests on
**re-certification being expensive**. No source measures the GPU-hours / dataset-mint cost of re-running the
flip-consistency + OOD gate on a 14B QLoRA judge. **If re-cert is cheap for the studio, C (SecAlign/Master-RM
re-mint) becomes attractive** — it's the only option with strong ASR-down AND measured low utility cost [3,17].
So: ship A+committee now (certification-safe); in parallel measure (1) the re-cert cost and (2) the detector's
FPR/FNR on the studio's OWN traffic [25]; let those two numbers decide whether C graduates from "queued" to "next
certified judge."

## Research grounding (the empirical floor — verified at Step-4)

Format: `N. **finding.** Authors year (id). → implication.` ⚠ = 2026 preprint. ◆ = gate-confirmed in the prior
fleet-receipts receipt this session (`fleet-receipts-gate-result.json`) and/or independently WebSearch-confirmed.

### A — Spotlighting the input (option B) is capability-dependent and shifts the certified distribution
1. **Spotlighting's encoding mode is detrimental on weaker models that can't decode it (recommended only for highest-capacity models); datamarking showed no impact on large general models run zero-shot.** Hines et al. 2024 (arXiv:2403.14720).◆ → A 14B QLoRA specialist is the weak regime; even datamarking was never validated on a small FINE-TUNED judge on a fixed input shape → option B is not free for the specialists.
2. **StruQ fine-tunes instruction/data separation into the weights with little utility loss — robustness lives in training, not prompt formatting.** Chen, Piet, Sitawarin & Wagner 2024 (arXiv:2402.06363).◆ → A frozen judge that never saw marked inputs gains no StruQ-like robustness from inference-time spotlighting; supports C-over-B *if* hardening the judge itself.
3. **SecAlign (preference-optimization on secure/insecure pairs) reduces injection success to below ~10% while preserving general utility (AlpacaEval2).** Chen, Zharmagambetov, Mahloujifar, Chaudhuri, Wagner & Guo 2024 (arXiv:2410.05451). *(Abstract-grounded "below 10%"; the 2-8% per-setting breakdown and ">4× over StruQ" are body figures — the gate's numeric guard correctly flagged the body "8%" against the abstract's "10%", a body-vs-abstract scope mismatch, not a contradiction of fact.)* → The anchor for option C: the only defense with strong ASR-down AND measured low utility cost — but it IS a re-mint (voids the cert), so it's the *next certified round*, not a hotfix.
4. **OpenAI's Instruction Hierarchy trains models to prioritize privileged over injected instructions, robust even to unseen attacks, minimal capability loss — a training intervention.** Wallace, Xiao, Leike, Weng, Heidecke & Beutel 2024 (arXiv:2404.13208). → Injection handling is learned, not prompted; a frozen judge has no hierarchy training → wrapping its input (B) gives it no basis to down-weight injected text.
5. **Even trained-in defenses degrade under adaptive GCG: StruQ ASR rises to 0.80-1.00, SecAlign to 0.46-0.88, both with 0.10-0.17 absolute utility loss.** Jia, Shao, Liu, Jia, Song & Gong 2025 (arXiv:2505.18333). → Tempers C: re-minting is neither guaranteed nor cost-free under adaptive attack → treat C as a separately-certified experiment, not a silver bullet.

### B — A separate detector pre-filter (option A): certification-safe, but a coverage floor not a guarantee
6. **DataSentinel fine-tunes a SEPARATE detector via a minimax game so a benign canary is overridden by injected content; near-perfect static separation (FPR 0.00 / FNR 0.01, Mistral-7B); S&P 2025 Distinguished Paper.** Liu, Jia, Jia, Song & Gong 2025 (arXiv:2504.11358).◆ → The canonical option-A pre-filter: screens content before the judge, ABSTAINs on contamination, certified input untouched, zero distribution shift. The static numbers are the *non-adaptive ceiling*, not the deployed floor.
7. **Known-answer detection prepends a secret-answer probe to untrusted data and flags contamination when the model fails to echo it; a 5-attack/10-defense benchmark found existing defenses generally insufficient, and detection defenses run at ~0% FPR with the task input UNCHANGED while transform defenses (paraphrase) cost ~0.14 accuracy.** Liu, Jia, Geng, Jia & Gong 2024 (arXiv:2310.12815, USENIX Security 2024). → Formalizes A as a *detection* (not prevention) defense: ~0% FPR, input unchanged → preserves the cert by construction; the ~0.14 transform tax is exactly why B voids it.
8. **Known-answer detection FAILS against optimization-based injection on judges (FNR 90% MT-Bench / 100% LLMBar); JudgeDeceiver itself reaches 90.8-98.9% ASR by placing a gradient-optimized injection in the candidate RESPONSE.** Shi, Yuan, Liu, Huang, Zhou, Sun & Gong 2024 (arXiv:2403.17710, CCS 2024). → A standalone KAD pre-filter leaks badly → it is a contamination *tripwire that drives ABSTAIN*, not the verdict-protector; pair with the committee.
9. **Off-the-shelf detectors are bypassed by trivial input obfuscation: ProtectAI deBERTa up to 100% ASR; emoji/Unicode-tag character smuggling 100% ASR vs Meta PromptGuard and Vijil.** Hackett, Birch, Trawicki, Suri & Garraghan 2025 (arXiv:2504.11168). → Mandates an **input-normalization / de-smuggling** pre-stage (NFKC, strip zero-width/Unicode-tag/emoji) on the detector's COPY — cheap, cert-safe (touches only the copy), closes the trivial-evasion class.
10. **DataSentinel generalizes poorly off-distribution (FNR up to 0.667) and severely over-defends (high FPR) on LONG-CONTEXT inputs (Musique, NarrativeQA).** Wang, Zhang & Gu 2025 (arXiv:2508.20890, PromptSleuth). → Judge inputs ((CONTEXT,RESPONSE), cited passages) ARE long context → A will spuriously ABSTAIN unless the detector has a long-context-aware operating threshold tuned on real traffic.
11. **The DataFlip adaptive attack drives known-answer detection to 0% while still inducing 91% malicious ASR — a STRUCTURAL KAD flaw needing no white-box access; LLM detectors can also be forced to FALSE-POSITIVE on benign input.** Choudhary, Anshumaan, Palumbo & Jha 2025 (arXiv:2507.05630, AISec 2025). → The hard cap on A: an attacker who knows the detector evades it AND can weaponize it into mass-abstain → A is coverage vs non-adaptive injection, never a guarantee; the abstain channel needs guards [23-26].
12. **Pairwise judging is MORE manipulable than pointwise for spurious/distractor features (the opposite ranking from the injection studies).** Tripathi/Han et al. 2025 (arXiv:2504.14716).◆ → Do NOT globally flip the sycophancy judge to pairwise — the protocol that resists injection worsens the spurious-feature manipulation that IS sycophancy's threat. Protocol choice is per-duty.

### C — Adding a defense without re-certification: the calibration principle
13. **Post-hoc calibration tuned on i.i.d. validation degrades sharply as distribution shift grows — in-distribution calibration does NOT survive shift.** Ovadia et al. 2019 (arXiv:1906.02530, NeurIPS 2019). → The load-bearing principle: any input transform (B) or weight change (C) moves the judge off its calibrated operating point and demands re-cert; A leaves the input untouched, so the cert is undisturbed by construction.
14. (Liu & Gong 2024, arXiv:2310.12815 — see [7]: detection ~0% FPR input-unchanged vs ~0.14 transform tax — the A-vs-B utility evidence.)
15. **A defense's utility must be re-measured on a held-out eval (incl. adaptive attacks); under that protocol existing defenses are less effective AND more utility-damaging than reported.** Jia, Shao, Liu, Jia, Song & Gong 2025 (arXiv:2505.18333). → A "no utility loss" claim from a defense paper does NOT transfer to the studio's cert gate — for B/C the held-out eval IS the flip-consistency + OOD gate, which must be re-run.

### D — The committee is the certification-preserving load-bearing defense (already banked)
16. **Single judges ~61% ASR; a mixed-architecture 5-judge committee → 18.7%, 7-judge → 12.4% (mixed beats same-arch, p<0.01); peak single-judge ASR 73.8%, smaller models most vulnerable (Gemma-3-4B 65.9% vs Claude-3-Opus 27%).** Maloyan & Namiot 2025 (arXiv:2504.18333).◆ → The fleet is ALREADY small + cross-family-decorrelated → the committee defense is structurally banked at zero re-cert cost, and "smaller = more vulnerable" is exactly why the *ensemble + ABSTAIN envelope* (not any single 14B judge) must carry robustness.
17. **Generative reward-judges are fooled ~80%+ by a single superficial cue (":"/"Thought process:"); Master-RM augments training with 20k truncated-opener negatives → FPR 0-2.9%, 96% GPT-4o agreement.** Zhao, Liu, Yu, Kung, Mi & Yu 2025 (arXiv:2507.08794). → A judge-specific instance of C with concrete low-cost numbers — strengthens that a *targeted-augmentation re-mint* can be robust + high-utility, available only by re-certifying.
18. **Comparative (pairwise) judging substantially reduces combined-attack success vs pointwise on the same judge; retokenization is the strongest *prevention* defense while delimiter/sandwich defenses and naive LLM-detection underperform (RobustJudge, 15 attacks × 7 defenses × 12 models).** Li et al. 2025 (arXiv:2506.09443, "LLMs Cannot Reliably Judge (Yet?)"). *(Qualitative claim is abstract-grounded; the precise figures — ~100%→28-63%, retokenization 59.7%→16.7%, delimiter >60%, detection ~65% — are body tables, so the gate's numeric guard flagged them against the abstract's headline number, a body-vs-abstract scope mismatch, not a contradiction of fact.)* → Pairwise + retokenization are large robustness levers for the general (citation/conformance) lenses — but delimiter-spotlighting underperforms and detection is weak, so input-side tweaks alone are insufficient; the committee does the heavy lifting.
19. **The 2026 SoK of LLM-as-judge security taxonomizes the field and DECLINES to crown a single best defense — robustness is an open problem.** Al Masoud et al. 2026 (arXiv:2603.29403). ⚠ → There is no certified-safe "just train it in" answer as of mid-2026 → the layered, per-duty stack is the defensible posture, not a single input-changing bet.
20. **A detection-only design (a separate structured LLM-as-judge, optional mixture-of-models) reaches F1 ~0.87-0.90; naive ensembling often DEGRADES — gains only in complementary pairs.** Le, Goh & Tang 2026 (arXiv:2603.25176). ⚠ → Supports A's architecture (detection as a distinct upstream stage) AND warns: add the pre-filter as its own decorrelated stage; don't blend it into the certified judge, and don't assume more judges = better.

### E — The omitted axes (critic-surfaced; reframe the per-duty answer) + the abstain-DoS guards
21. **Production guardrails (PromptGuard 2, LlamaGuard) detect only 7-37% of indirect attacks targeting agents and ARCHITECTURALLY CANNOT evaluate agentic tool injection; same-source train/test splits inflate AUC ~8.4pp.** Fomin 2026 (arXiv:2602.14161, "When Benchmarks Lie"). ⚠ → For the conformance/tool duty a generic detector is near-useless → the deterministic FLOOR is load-bearing; and set any detector's threshold on the studio's OWN traffic, not a vendor FPR.
22. **PoisonedRAG: ~5 poisoned documents in a large corpus yield ~90% ASR on targeted queries; the first knowledge-corpus poisoning attack on RAG, and existing defenses are insufficient.** Zou, Geng, Wang & Jia 2025 (USENIX Security 2025). → For the CITATION duty the dominant threat is **corpus poisoning UPSTREAM of the judge input** — an axis A/B/C don't touch → intervene at retrieval (provenance/signing, retrieval-time anomaly detection); the arXiv/Crossref oracle is already a provenance anchor.
23. **Attacking the rejector/router in a two-stage learning-to-defer system collapses accuracy 72.8%→17.2% — the abstain/escalate router is the highest-value adversarial target.** Montreuil, Carlier, Ng & Ooi 2025 (arXiv:2502.01027). → An unguarded abstain-to-orchestrator router is attackable into mass-mis-route/mass-abstain → guard it (robust/rate-limited router), don't use a naive confidence threshold.
24. **Convex surrogate losses are provably NOT calibrated for adversarial-robust reject-option classification — an adversary can craft inputs that land in the rejection region.** Shah, Chaudhari & Manwani 2024 (arXiv:2410.10736). → The risk-coverage guarantee does NOT survive an adversary optimizing to trigger abstention → the abstain trigger must be bounded by external rate limits, not a vanilla selective-prediction threshold.
25. **Malicious-prompt classifiers that score well on their own benchmarks degrade sharply under true distribution shift — reported FPR/FNR are optimistic vs deployment.** ("When Benchmarks Lie", arXiv:2602.14161 — see [21]). ⚠ → Measure the detector on the studio's own content before trusting its operating point; keep fail-open-to-ABSTAIN so detector failure degrades coverage, not safety.
26. **SOC telemetry: ~3,832 alerts/day, ~62% ignored, ~67% unhandled, ~83% false positives — flooded queues get muted/rubber-stamped.** Chuvakin 2024 (alert-fatigue synthesis; corroborated by the ACM Computing Surveys SOC review DOI:10.1145/3723158, abstract-grade). → A mass-abstain flood lands in an already-saturated human queue → rate-limit per source, aggregate repeated trips before escalation, and treat an **abstain-spike as its own attribution signal**; never raw-abstain-per-trip to a human.
27. **CaMeL defeats prompt injection BY DESIGN via control/data-flow separation + capabilities, model UNMODIFIED — 77% task completion with provable security vs 84% undefended on AgentDojo.** Debenedetti, Shumailov et al. 2025 (arXiv:2503.18813, Google Research). → The strongest moat-safe COMPLEMENT to A: harden what a flipped verdict can DO (capability-gate the orchestration consuming verdicts), not only whether it flips — touches neither judge weights nor input.

## The hardening architecture (per-duty, all certification-preserving)

**A new `prism.security` stage, sibling to reasoning-stripping (Lock 2), opt-in + fail-open, default-safe:**
1. **Input normalization / de-smuggling** [9] on a COPY of the judged content (NFKC, strip zero-width / Unicode-tag / emoji-variation) — the cert-safe first stage for ALL duties; the judge's certified input is never the normalized copy.
2. **Contamination pre-filter** (option A) [6,7]: a separate, **cross-family-decorrelated**, ideally minimax-trained (DataSentinel-class) detector on the normalized copy; a detection → maps to **UNCERTAIN → the existing fail-open ABSTAIN** [8,11]. Advisory floor, not a gate — layered on the committee [16].
3. **Per-duty load-bearing defense:** deterministic FLOOR for conformance [21]; A + committee (+ NOT-pairwise) for sycophancy [12,16]; spotlight the general groundedness lens [1,18] + **retrieval-stage hygiene** for citation [22].
4. **Guarded abstain channel** [23,24,26]: rate-limit per source, aggregate repeated trips, abstain-spike = attribution; uncertainty-gated, contrastively-framed human handoff (never raw-per-trip). Optionally **sanitize-and-retry** on a spotlighted copy before escalation (block is the adversary's goal).
5. **Consume-side capability-gating** [27]: cap what a flipped verdict can trigger downstream (orchestration layer) — moat-safe, model-unmodified.
6. **Queued, not now:** C (SecAlign/Master-RM re-mint) [3,17] as a separately-certified next round, gated on the two measurements below.

## Honest gaps (carried forward, not hidden)
- **The A-vs-C pivot is UNSOURCED + studio-internal:** no source measures the re-cert cost of a 14B QLoRA judge, nor how much certified accuracy a frozen specialist loses under spotlighted input. **Measure both before locking A-vs-C.**
- **The committee credit is extrapolated** [16] from other models/tasks — not measured on a ~14B cross-family fleet with fail-open ABSTAIN. **Validate on the real fleet, don't assume it's banked.**
- **Detector FPR/FNR are benchmark-optimistic** [10,25] — measure on the studio's own traffic; expect long-context over-ABSTAIN.
- **The pairwise fork is unresolved** [12 vs 16,18] — no head-to-head on the same judge+attack set; keep protocol choice per-duty.
- **Per-action latency/cost of a 7B detector call is unquantified** in the literature — benchmark; may favor an 86M-class detector or the deterministic floor for the hot path.
- **A few citations are abstract/secondary-grade** (PromptSleuth tables [10], SoK internals [19], the ACM SOC survey [26]); flagged at the gate, not load-bearing beyond their abstract-level thrust.

## Standards compliance (the six — scored 0-3)
| Standard | Score | Evidence |
|---|---|---|
| PIN_PER_STEP | **2** | Swarm script + run-id `wf_cbbbe6fb-917` persisted, schema + prompts fixed; subagent model inherited (not hashed). |
| ANDON_AUTHORITY | **2** | Step-4 gate halts on fabricated/misattributed; the critic halted the naive A/B/C frame and forced the per-duty reframe before synthesis. |
| NAMED_COMPENSATORS | **2** | Canon-write (dispatch doc). Compensators: `revert_dispatch_commit` (git revert); propagation → `requalify_dependent_slices`; paid subagents = bounded owner-accepted cost. No skip. |
| DECOMPOSE_BY_SECRETS | **2** | One agent per decision question (Parnas boundary); the per-duty split isolates each watcher's threat model. |
| UNCERTAINTY_GATED_HUMANS | **2** | Ends in Mike-gated decisions; CANNOT_CONFIRM citations surfaced with a contrastive frame; the design itself makes the abstain→human handoff uncertainty-gated + contrastive. |
| EXTERNAL_VERIFIER | **3** | Step-4 RUN via `roleos verify-citations` → prism (different family, reasoning-stripped, retrieval-oracle existence floor + groundedness lens). Signed receipt captured (`prism-01ktkq71ezb7vc6xh3n4xtxn5j`); 0 fabricated / 0 misattributed; the 2 `contradicted` flags were numeric body-vs-abstract artifacts, remediated. |

## Mike-gated decisions
1. **Approve the per-duty A-anchored hybrid as the hardening design?** (vs my original A/B/C — the swarm says it's richer: per-duty + coverage-floor + guarded-abstain + consume-side.)
2. **Build the first cert-safe slice now?** = `prism.security`: input-normalization + the contamination pre-filter wired as a pre-lens stage → ABSTAIN, on the general lenses + as an input-untouched pre-filter for the specialists; spotlight the citation groundedness lens. (No Receipt schema bump; opt-in; fail-open.)
3. **The two measurements that decide A-vs-C:** (a) re-cert cost of a 14B QLoRA judge; (b) detector FPR/FNR on the studio's own traffic. Run these? They gate whether C (SecAlign/Master-RM re-mint) graduates.
4. **Citation duty:** accept that its real threat is upstream corpus poisoning [22] → a retrieval-hygiene slice (separate from judge-input hardening)?
5. Standing Mike-gates remain OFF: the 3 consult flips, `PRISM_SYCOPHANCY_ENDPOINT`, HF publish, any push/commit.
