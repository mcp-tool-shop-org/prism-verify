# Oversight FLEET + certified-receipts/assurance layer — research-grounded dispatch

**Status:** Step-4 citation gate RUN (locked path `roleos verify-citations` → prism, library driver
`design/_run_fleet_gate.mjs`, 50-min timeout). **Verdict `escalate` (advisory, non-blocking); 0 FABRICATED,
0 MISATTRIBUTED across all 52 parsed citations.** Signed prism receipt `prism-01ktkn37nj24np47cd9xddeyrg`
(`citations_sha256 05a22e58…`); full result `design/fleet-receipts-gate-result.json`. Breakdown: **34
existence-RESOLVED** (23 arXiv + 11 Crossref DOI), of which **16 full ACCEPT** (existence + groundedness — incl.
the 2026 preprints SCOPE 2602.13110 + Kuai 2604.07650, and M-FISHER 2510.03839 which confirmed the title
correction); the other 18 resolved-but-`not_addressed` = groundedness-from-abstract conservatism / no-abstract
old DOIs (the specifics are body-sourced — the protocol's "tighten-to-abstract" class, not fabrication). **18
arXiv `HTTPStatusError`** = the documented rate-limit tail of a >20-ID burst (Crossref never throttled) → **all
18 externally re-confirmed** by me: 12 via WebSearch (incl. the three strategy-changers 2504.18333 / 2603.06594 /
2501.16559), 1 companion-in-results (2505.13348), 4 via the prior signed sycophancy-gate receipts (SelfCheckGPT /
SycEval / Sharma / Buçinca), MD3 1704.00023 confirmed. **10 unparsed** = the † oracle-external prose lines, all
WebFetch/WebSearch-corroborated (RFC 6962, in-toto, EBCC, NUREG/CR-5485, Gretton, Polyzotis, Fink SSRN 5147196,
EU AI Act Art.12, ISO/IEC 42001, SAE ARP4761). **No finding is load-bearing on an unverified citation.**
**Authored:** 2026-06-08. **Via:** study-swarm round 1 `wf_86e8d406-d5f` (5 web-research agents + a completeness
critic) → the critic surfaced a systemic blind spot → round-2 gap-fill `wf_66366ace-803` (4 agents
retrieving+verifying the critic's findings). **Scope:** the runtime FLEET-level aggregation of the three shipped
watchers (conformance ✓ + sycophancy ✓ + citation ✓) + the certified-receipt / assurance trail — a genuinely
new product layer, so the study-swarm protocol fired. NOT a build order — a Mike-gated design.

## The reframe (the whole dispatch turns on this — it is the critic's finding, not round 1's)

Round 1 answered the five spine questions assuming the watchers are **honest detectors of non-hostile
inputs**. The completeness critic + round-2 retrieval demolished that frame on four axes, and the single
load-bearing reframe is:

> **Decorrelation and residual error must be MEASURED on held-out receipts and DEFENDED against an adversary —
> never assumed from family labels and never published naively.**

1. **Decorrelation is NOT free, and it worsens with capability.** Same-developer/-architecture models agree on
   the *same wrong answer* far above chance, and the strongest predictor of agree-on-error is accuracy itself —
   so as the ~14B judges improve, residual correlation *grows* [2]. A naive-independence joint-false-clear bound
   is optimistic [7,16].
2. **The watchers are adversarially attackable.** The audited action can be a hostile producer, and each LLM
   ceiling is prompt-injection-flippable through the very content it judges (single-judge ASR up to 73.8%)
   [43,44]. The cross-family committee is therefore a *security* control, not only a quality one [44].
3. **Fixed-sample certificates are invalid under a runtime stream.** Conformal/LTT [10,11] and scheduled recert
   [51] are invalidated by continuous peeking (optional stopping); the residual number needs an anytime-valid
   foundation [18-21].
4. **The human-oversight leg is a DEFEATER, not a backstop.** Art.14 review collapses to rubber-stamping under
   automation bias [59,60,61]; it must be engineered against, not banked on.

And one tension the synthesis must resolve, surfaced by no single agent but by the critic: **"publish the
residual error" (honesty/assurance) is in direct tension with handing an attacker your miss-rate and probe
bank (security).** Resolution is granularity (below).

## Research grounding (the empirical floor — verified at Step-4)

Format: `N. **finding.** Authors year (id). → implication.` ⚠ = 2026 preprint (retrieval-oracle re-check).
†= identifier is oracle-external (RFC/ISO/NUREG/SSRN/JMLR/MLSys/PMLR/book/spec); existence WebFetch-corroborated,
verdict noted in the gate triage, never silently load-bearing.

### A. Aggregation — fusing watchers of DIFFERENT duties (the architectural core)
1. **A panel of disjoint-model-family judges beats one large judge with less intra-model bias, ~7× cheaper — but PoLL judges all score the SAME property.** Verga et al. 2024 (arXiv:2404.18796). → Confirms structural cross-family decorrelation as the base, but PoLL voting does NOT transfer to cross-DUTY fusion — that needs a reliability model, not a vote.
2. **Across >350 LLMs, two wrong models pick the SAME wrong answer ~60% of the time on HELM (33% by chance); same-company/-architecture raise agree-on-error, and the STRONGEST predictor is accuracy itself — capable models converge in their errors even across providers.** Kim, Garg, Peng & Garg 2025 (arXiv:2506.07962). → Independence is the wrong null and gets worse as judges improve; the fleet must MEASURE a pairwise error-correlation matrix on held-out receipts per duty and recompute it on every re-mint.
3. **EM jointly recovers each noisy observer's confusion matrix (reliability) AND the latent truth from disagreement alone, with no ground truth.** Dawid & Skene 1979 (DOI:10.2307/2346806). → The citable closer precedent (replacing the admitted Chair-Varshney sensor-fusion analogy) for weighting each watcher's verdict by a receipt-learned reliability; caveat: vanilla D&S assumes conditionally-independent raters — exactly our risk → layer the dependence-aware extensions below.
4. **EBCC extends Dawid-Skene by explicitly inducing INTER-WORKER correlation, and wins mean accuracy over 10 baselines on 17 datasets.** Li, Rubinstein & Cohn 2019 (PMLR v97:3886-3895, ICML 2019).† → The dependence-aware upgrade to the fusion rule: when two watchers share a family/blind spot, EBCC-style modeling stops the aggregator double-counting their agreement as independent evidence.
5. **Snorkel's data-programming label model denoises sources with UNKNOWN accuracies AND correlations without any ground truth, from their agreement structure alone.** Ratner et al. 2017 (arXiv:1711.10160, PVLDB 11(3)). → The engineering-grade implementation of correlation-aware fusion: treat each watcher as a labeling function with learned accuracy + learned pairwise dependence; fuse with no oracle, keeping the aggregator leakage-audited and ground-truth-free.
6. **The multi-task weak-supervision label model recovers source accuracies AND their dependency structure with no labels, by matrix completion on the inverse generalized covariance of source outputs.** Ratner et al. 2019 (arXiv:1810.02840, AAAI). → A concrete estimator for the pairwise error-correlation matrix: ONE learned structure drives both the fusion rule and the joint-failure bound, computed on held-out receipts.
7. **LLM judges that look independent are behaviorally ENTANGLED (correlated errors); down-weighting correlated judges and up-weighting genuinely independent ones beats naive majority voting.** Kuai et al. 2026 (arXiv:2604.07650; gate-confirmed in the v0.2 sycophancy receipt). ⚠ → Decorrelation must be measured, not assumed from family labels; two entangled lenses ≈ one vote sets the ≥2-agreement threshold.
8. **The beta-factor common-cause-failure model splits a redundant component's failure into an independent fraction + a common-cause fraction β, putting a NUMBER on redundant barriers failing together (generic β ≈ 5% at 70% / 18% at 95% confidence).** Mosleh, Rasmuson & Marshall 1998 (NUREG/CR-5485).† → Replaces the naive-independence joint bound with a reliability-engineering form: report the floor as (independent product) × (1 + a *measured* common-cause β estimated from receipts); the β prior is NOT transferable from hardware — only the method is.

### B. Joint calibration + the residual-error budget
9. **A reject option guarantees selective risk ≤ r with confidence 1−δ by sacrificing coverage, via a threshold found on a held-out set.** Geifman & El-Yaniv 2017 (arXiv:1705.08500). → Each watcher publishes a per-duty risk-coverage curve and pins its operating point at a δ-guaranteed risk; the abstain-to-orchestrator volume IS the coverage sacrificed, making the residual a calibration-certified quantity.
10. **Conformal Risk Control bounds the expected value of any bounded MONOTONE loss (E[L]≤α); the canonical example bounds the false-negative rate; without monotonicity the guarantee fails.** Angelopoulos, Bates, Fisch et al. 2022 (arXiv:2208.02814). → Report E[false-clear] under CRC (oversight's risk is missed defects = FNR), choosing the abstain threshold so the false-clear loss is monotone in conservativeness.
11. **Risk control recast as multiple testing: each candidate threshold is a null "risk>α", and an FWER procedure returns thresholds controlling risk w.p. 1−δ even for NON-MONOTONE risks.** Angelopoulos, Bates, Candès et al. 2021 (arXiv:2110.01052, Learn-then-Test). → The literal mechanism for splitting ONE fleet error budget across N watchers, and the only tool that handles the non-monotone "any-watcher-flags" aggregation rule that breaks plain CRC.
12. **Selective calibration trains a separate selector to abstain on examples whose uncertainty is itself unreliable, with DRO for OOD robustness.** Fisch, Jaakkola & Barzilay 2022 (arXiv:2208.12084). → Calibrate only the non-abstained region per watcher and add simulated perturbations so the published residual holds under the OOD drift internal-first→high-risk deployment will see.
13. **SCOPE calibrates an acceptance threshold so error among NON-abstained pairwise judgments ≤ α under exchangeability, using Bidirectional Preference Entropy (both response orders) to remove positional bias; empirical risk held at 0.097-0.099 at α=0.10.** Badshah et al. 2026 (arXiv:2602.13110). ⚠ → Validates the sycophancy watcher's order-flip INV probe as a calibrated selective signal; the watcher can advertise a finite-sample α on its non-abstained verdicts + the coverage it costs.
14. **ECE is a biased, binning-dependent estimator; adaptive (equal-mass) binning reduces the bias and stabilizes metric rank-ordering.** Nixon et al. 2019 (arXiv:1904.01685). → The published residual must NOT be a bare ECE (an auditor can move it by re-binning); report adaptive/debiased calibration error + a proper score (Brier) + reliability diagram.
15. **Benjamini-Hochberg controls the false discovery rate, less conservative than Bonferroni for many simultaneous tests — but requires independence/PRDS.** Benjamini & Hochberg 1995 (DOI:10.1111/j.2517-6161.1995.tb02031.x). → An FDR target ("expected fraction of false-clears") is a higher-coverage alternative to a strict any-false-clear FWER where the use-case tolerates it — *only if* independence holds, which [2] says it does not.
16. **BH still controls FDR under positive regression dependence (PRDS), and a harmonic-factor modification (×Σ1/i ≈ ln m + 0.577) controls FDR under ARBITRARY dependence.** Benjamini & Yekutieli 2001 (DOI:10.1214/aos/1013699998). → Directly fixes the joint bound: the 3 watchers are decorrelated but NOT independent, so the joint-false-clear bound must carry the BY correction (or prove PRDS) — the receipt states which assumption it relies on.
17. **Civil aviation apportions a top-level catastrophic-failure target (1e-9/flight-hr) DOWNWARD across failure conditions, so the system target is a sum of allocated component budgets.** SAE ARP4761 / FAA AC 25.1309 1996 (SAE ARP4761).† → Adopt top-down budget apportionment: set ONE joint false-all-clear target (the assurance claim), allocate a per-watcher residual so the BY/β-corrected sum meets it; the documented allocation IS the receipt regulators expect.

### C. Streaming validity — anytime-valid inference + dependence-robust multiple testing
18. **E-processes (testing) and confidence sequences (estimation) built on test martingales stay valid at EVERY stopping time via Ville's inequality — a certificate can be peeked at continuously under optional stopping without inflating type-I error.** Ramdas, Grünwald, Vovk & Shafer 2023 (arXiv:2210.01948, Statistical Science 38(4)). → Each per-window residual-error number in the receipt should be an anytime-valid bound, not a fixed-n estimate — the published residual is then provably valid under continuous runtime peeking.
19. **Nonparametric, nonasymptotic, time-uniform confidence sequences whose width shrinks to zero at the LIL rate, generalizing the SPRT.** Howard, Ramdas, McAuliffe & Sekhon 2021 (arXiv:1810.08240, Ann. Statist. 49(2)). → The concrete estimator: a closed-form confidence sequence on each watcher's false-clear rate that tightens as the stream lengthens, so the anytime-valid envelope narrows over a deployment without becoming invalid.
20. **Time-uniform Chernoff-type bounds for scalar/matrix/Banach martingales via nonnegative supermartingales, unifying Bernstein/Bennett/Hoeffding/Freedman into anytime-valid form.** Howard, Ramdas, McAuliffe & Sekhon 2020 (arXiv:1808.03204, Probab. Surveys 17). → The construction toolkit behind the confidence sequences — the verifier engineer derives the actual numeric per-window bound from these supermartingale mixtures.
21. **A martingale of streaming non-conformity scores + Ville's inequality gives time-uniform false-alarm control at any stopping time, with sustained-shift detection delay O(log(1/δ)/Γ), tying anytime-valid testing to streaming drift.** Khan & Syed 2025 (arXiv:2510.03839, M-FISHER). → Unifies the residual cert (B) and the drift trigger (G): one e-process is BOTH the valid-under-peeking bound AND the recert signal. (NOTE: the round-1-critic lead called this "E-SHIFT"; the retrieved title/method is M-FISHER — correction recorded; mapping to LLM-watcher streams is analogical pending validation on the fleet's own scores.)
22. **A group-sequential boundary permits repeated interim looks at accumulating data while controlling overall type-I error, demanding strong early evidence and spending most α at the final look.** O'Brien & Fleming 1979 (DOI:10.2307/2530245, Biometrics 35(3)). → For scheduled recert (discrete looks), spend a fixed false-clear budget across N planned checkpoints without a separate Bonferroni penalty.
23. **An α-spending function α*(t) sets each interim boundary from the fraction of information spent so far, WITHOUT requiring the number/timing of looks fixed in advance.** Lan & DeMets 1983 (DOI:10.1093/biomet/70.3.659, Biometrika 70(3)). → Better fit than O-F because recert cadence is operationally driven: add/reschedule recert looks adaptively while still capping cumulative false-clear probability.
24. **CUSUM accumulates signed deviations from target and signals when the running sum crosses a decision interval — optimal for small persistent mean shifts.** Page 1954 (DOI:10.1093/biomet/41.1-2.100, Biometrika 41). → A fast, interpretable secondary trigger for slow degradation in a watcher's clear-rate before the anytime-valid bound itself crosses threshold.
25. **The EWMA control chart weights recent observations most heavily — a tunable-memory streaming detector.** Roberts 1959 (DOI:10.1080/00401706.1959.10489860, Technometrics 1(3)). → One tunable smoothing parameter to trade detection latency vs false-alarm rate per watcher; cheaper than recomputing a full e-process every event.

### D. Certified-receipt / assurance-case design
26. **Certificate Transparency = an append-only Merkle Hash Tree where each entry yields a signed timestamp; inclusion proofs + signed tree heads let any third party detect retroactive edits without trusting the operator.** Laurie, Langley & Kasper 2013 (RFC 6962).† → Store fleet verdicts as Merkle-log leaves; each receipt carries an inclusion proof + a periodic signed tree head, so a verdict is provably logged at decision time and never silently rewritten.
27. **The in-toto Attestation Framework specifies a minimal signed claim: a Statement (subject identified by cryptographic digest, predicateType URI, predicate object) wrapped in a DSSE envelope carrying signatures.** in-toto Project 2023 (in-toto Attestation Framework Statement spec v1).† → Adopt Statement+DSSE verbatim as the receipt schema: subject = digest of (action + watcher inputs), predicate = the verdict object below, Ed25519-signed — reuse a battle-tested envelope instead of a bespoke format.
28. **Model Cards accompany a model with structured disclosure: intended use, eval conditions, disaggregated performance, caveats.** Mitchell et al. 2019 (arXiv:1810.03993). → Ship a model card per watcher stating its duty, held-out receipt eval results, and measured residual/ABSTAIN rate — the standing "why trust this judge" artifact; it operationalizes "publish the residual error."
29. **Datasheets for Datasets: every dataset carries motivation, composition, collection, and recommended/discouraged uses.** Gebru et al. 2021 (arXiv:1803.09010). → Attach a datasheet to each watcher's minting corpus documenting the leakage-audit + flip-consistency certification — since the moat IS the minting PROCESS, the datasheet is the defensible provenance record.
30. **Assurance 2.0 replaces confidence-by-confirmation with eliminative argumentation: refute defeaters (recorded doubts) of "the system is unsafe," preserving residual-doubt history against confirmation bias.** Bloomfield, Netkachova & Rushby 2024 (arXiv:2405.15800). → Structure the fleet assurance case around defeaters; require ABSTAIN unless defeaters are addressed — making fail-open-to-ABSTAIN the architectural embodiment of eliminative argumentation, not an ad-hoc valve.
31. **A taxonomy of seven real-world defeater categories (logical, contextual, evidence-validity, requirements, structural, adversarial, uncertainty) shows assurance cases routinely fail through incompleteness.** Gohar et al. 2025 (arXiv:2502.00238). → Run the seven categories as a fixed pre-emit checklist before any non-ABSTAIN joint verdict; logging which were checked + their outcome into the receipt is concrete evidence against "assurance theater."
32. **EU AI Act Art. 12 requires high-risk systems to automatically log events over their lifetime (supporting Art. 26(5)/72 monitoring); Annex IV mandates technical documentation; Art. 14 mandates effective human oversight — binding 2 Aug 2026.** European Parliament & Council 2024 (Reg. (EU) 2024/1689, Art. 12).† → The Merkle receipt log already satisfies Art. 12; design receipts to carry the Art. 14 human-oversight hook (who reviewed/overrode an ABSTAIN, when) and map cards+datasheets onto Annex IV now, so an internal-first deployment that later becomes high-risk needs no log retrofit.
33. **ISO/IEC 42001:2023 is the first AI management-system standard (AI risk + impact assessment + lifecycle/data controls) on the certifiable Annex SL backbone shared with ISO 27001.** ISO/IEC JTC 1/SC 42 2023 (ISO/IEC 42001:2023).† → Frame the minting datasheets + watcher model cards as ISO/IEC 42001 lifecycle + impact-assessment evidence, complementing NIST AI RMF without bespoke governance.
34. **A continuous-assurance framework unifies design-time verification, runtime monitoring, and evolution-time updates so assurance arguments auto-regenerate when specs or verification results change.** Abeywickrama, Fisher, Wheeler & Dennis 2025 (arXiv:2511.14805). → Make the certified receipt a LIVING assurance case: each base bump or drift alarm regenerates it with fresh held-out evidence + a timestamp — EU-AI-Act-ready proof of ongoing validity.

### E. Active-probe producer access (the sycophancy active probe's blocker)
35. **CheckList defines three label-free oracle types: Minimum Functionality, Invariance (label-preserving perturbation must not change output), Directional Expectation (output must change in a specified direction).** Ribeiro et al. 2020 (arXiv:2005.04118). → The counterfactual stance-flip is an INV test (reversing the user's stance must NOT flip the verdict); the capitulation re-ask is a DIR test (an "are you sure?" must NOT move a correct answer toward agreement); the receipt records probe-type + expected relation.
36. **Metamorphic testing turns an input→output relation into a test oracle, validating arbitrarily many auto-generated pairs with zero labels — solving the no-oracle problem at runtime.** Zhang et al. 2020 (arXiv:1906.10742, ML Testing survey). → Encode each probe as an explicit metamorphic relation stored in the receipt; the watcher ABSTAINs (never asserts safe) when the relation cannot be evaluated.
37. **SelfCheckGPT detects unsupported content by sampling multiple stochastic responses and measuring inter-sample consistency — divergence = fabrication — label-free and retrieval-free.** Manakul et al. 2023 (arXiv:2303.08896). → Make the producer call N>1: the probe issues k pinned re-queries and emits ABSTAIN on intra-sample contradiction, both raising the consistency floor and preventing one noisy producer call from contaminating the verdict.
38. **Challenging a model is double-edged: under rebuttal, 43.5% progressive (agree-and-correct) vs 14.7% regressive (agree-and-wrong) shifts, 78.5% persistence; citation-based rebuttals specifically raise the HARMFUL regressive rate.** Fanous et al. 2025 (arXiv:2502.08177, SycEval). → The capitulation DIR probe must score the DIRECTION of a flip (regressive=defect, progressive=acceptable), pin the rebuttal to a fixed content-free form, and AVOID citation-style rebuttals — a naive "changed-its-answer" check backfires.
39. **RLHF assistants systematically cave when users disagree, and preference models sometimes prefer convincing sycophantic answers over correct ones.** Sharma et al. 2023 (arXiv:2310.13548). → Justifies producer-access at all (capitulation only appears under challenge); log baseline + post-probe verdicts as a paired observation; the probe-secrecy tension is real → rotate a held-out probe bank, certify on it, publish residual flip rates.
40. **Active testing selects which few points to label for sample-efficient performance estimation, with an unbiased variance-reduced risk estimator that corrects the non-random-selection bias.** Kossen et al. 2021 (arXiv:2103.05331). → Drive TRIGGERED (selective) probing — spend the marginal producer call only on high-suspicion actions — and apply the bias-correction so fleet-level error estimates from selectively-probed actions stay valid.
41. **Property-based testing replaces hand-written cases with universally-quantified properties checked over many auto-generated inputs — the SE ancestor of INV/DIR/metamorphic oracles.** Claessen & Hughes 2000 (DOI:10.1145/351240.351266, QuickCheck). → Frame each probe as a property ("reversing stance preserves verdict") with a GENERATED family of content-free rebuttals, giving probe diversity that resists producer gaming while the property stays pinned + replayable.
42. **Securing LLM agents requires capability-scoping: Action-Selector limits what an LLM-driven component may do; Dual-LLM / Code-Then-Execute isolate untrusted content from privileged actions.** Beurer-Kellner et al. 2025 (arXiv:2506.08837). → The probe is a privileged caller (it drives the producer) and MUST be capability-scoped: an allowlist of pinned probe prompts only, no tool/side-effect access, orchestrator-family ≠ worker-family — a compromised/looping probe cannot contaminate downstream actions or self-grade.

### F. Adversarial robustness of the watchers (the critic's biggest find — NEW)
43. **GCG-optimized adversarial suffixes drive an LLM-judge's Comparative-Undermining-Attack success rate above 30% on small open instruct judges.** Maloyan, Ashinov & Namiot 2025 (arXiv:2505.13348). → Each watcher's LLM ceiling can be flipped by content the agent controls → judged content (tool args, cited text, agent output) must enter the ceiling as spotlighted UNTRUSTED data, never as instruction, and a contaminated-content signal routes to fail-open ABSTAIN.
44. **Prompt-injection reaches up to 73.8% success against single LLM judges, but mixed-architecture committees of 5-7 models cut it to 10.2-26.8% (a 54-63pt reduction), with architectural DIVERSITY (not redundancy) carrying the gain; cross-model transfer is 50-62%.** Maloyan & Namiot 2025 (arXiv:2504.18333). → Directly VALIDATES the cross-family decorrelated committee as a SECURITY control (exceeds the critic's 20-47pt estimate); record per-family votes + committee dispersion as a tamper signal — but transfer is non-zero, so decorrelation is mitigation, not immunity; the residual-ASR band belongs in the receipt.
45. **Under the distribution shift intrinsic to adversarial eval, SOTA safety judges degrade on average to near random-chance accuracy, and many reported "attack successes" merely exploit judge insufficiencies (6,642 human-verified labels).** Schwinn et al. 2026 (arXiv:2603.06594). ⚠ → The strongest caveat against self-reported robustness: do NOT import literature ASR numbers as the fleet's assurance figure; measure each watcher on its OWN held-out adversarial receipts under realistic shift, and report measured (human-audited) accuracy in the threat-model leg.
46. **Spotlighting (delimiting / datamarking / encoding untrusted text) reduces indirect-prompt-injection success from >50% to <2% with minimal quality loss.** Hines et al. 2024 (arXiv:2403.14720). → The cheapest, highest-leverage ceiling defense: datamark all judged content before it reaches any watcher LLM; the receipt's threat-model leg records the spotlight mode per audit (an auditable, replayable step).
47. **Known-answer / game-theoretic detection (DataSentinel) prepends a secret-key instruction to the data segment; a detector that fails to echo the key flags injection, trained minimax against adaptive attacks.** Liu et al. 2025 (arXiv:2504.11358). → A cheap pre-filter ahead of the ceiling: a missed canary → ABSTAIN rather than a possibly-flipped verdict; the KAD result is a boolean leg in the receipt, and the adaptive-attacker framing matches the producer-adversarial assumption.
48. **Pairwise preference judging is MORE manipulable than absolute pointwise scoring against spurious distractor features (≈35% pairwise flips vs ≈9% absolute).** Tripathi et al. 2025 (arXiv:2504.14716). → QUALIFIES "comparative judging is the robust default": true for suffix attacks [44] but FALSE for spurious-feature manipulation here → do NOT hardcode a universally-safe scoring protocol; record which protocol each watcher used + the attack class it was hardened against.
49. **StruQ structurally separates instructions from data via reserved delimiter tokens + fine-tuning the model to ignore instructions in the data channel.** Chen et al. 2024 (arXiv:2402.06363). → For the ~14B distilled judges (fine-tunable), structured-query training is a deeper defense than prompt-level spotlighting: bake instruction/data separation into the weights so provenance becomes an attestable receipt property, not a fragile prompt convention.

### G. Drift detection + recertification
50. **Fully-unsupervised feature-drift detectors false-alarm because they ignore classifier behavior; tracking sample density in the classifier's uncertainty margin (MD3) flags only drift that degrades decisions.** Sethi & Kantardzic 2017 (arXiv:1704.00023). → Do NOT recert on raw-input drift; gate the retrain alarm on each watcher's ABSTAIN/uncertainty-margin rate so recert fires only when drift threatens verdict quality.
51. **ADWIN keeps a variable-length window that shrinks when two sub-windows differ enough, with rigorous bounds and no preset time-scale, monitoring a running error rate.** Bifet & Gavaldà 2007 (DOI:10.1137/1.9781611972771.42).† → Run ADWIN on each watcher's streaming agreement-with-gold as the performance-drift axis to auto-raise a recert-due flag between scheduled re-evals.
52. **The same deployed LLM service drifts substantially in months: GPT-4 prime-detection fell 84%→51% (Mar→Jun 2023).** Chen, Zaharia & Zou 2023 (arXiv:2307.09009). → Orchestrator-family behavioral drift is the top silent-failure risk: pin a frozen behavioral canary set and rerun on schedule, since a vendor update breaks decorrelation with NO watcher-weight change.
53. **S-LoRA serves thousands of LoRA adapters on one frozen base by computing the base activation once + per-adapter deltas (≤4× throughput).** Sheng et al. 2023 (arXiv:2311.03285). → Validates one-base co-SERVING economics for the watcher fleet — but see [54]: serving ≠ certificate validity.
54. **When a base model is deprecated/replaced, all associated LoRA adapters must be RETRAINED (original or synthetic data) unless a dedicated training-free transfer method is used — adapters do not silently survive a base swap.** Farhadzadeh et al. 2025 (arXiv:2501.16559, LoRA-X). → **REFUTES the strategy memory's "one base bump re-certifies the fleet in one pass":** a base swap VOIDS each watcher's held-out receipts → treat a base change as a full re-mint + re-certify event per adapter (leakage audit + flip-consistency), or carry an explicit transfer-validity proof. (Flag for Mike — corrects an open mitigation.)
55. **Black-box shift detection — dimensionality reduction via a pretrained classifier feeding a two-sample test (BBSD) — is the most reliable empirical dataset-shift detector, and shift can be triaged for malignancy.** Rabanser, Günnemann & Lipton 2019 (arXiv:1810.11953, Failing Loudly). → Run BBSD on the live action stream vs the certification distribution; a malignant-shift alarm is the signal to re-mint/re-certify a watcher; the alarm becomes a dated receipt entry.
56. **The Maximum Mean Discrepancy is a distribution-free kernel two-sample statistic testing whether two samples share a distribution.** Gretton et al. 2012 (JMLR 13:723-773).† → The concrete two-sample test under BBSD: MMD over watcher-input embeddings decides "is today's traffic still in the certified distribution," making recert a published reproducible number, not a judgment call.
57. **Production ML needs continuous data validation: TFX detects schema anomalies + training/serving skew at scale because input errors silently nullify accuracy gains.** Polyzotis et al. 2019 (MLSys/SysML 2019, Data Validation for ML).† → A data-validation gate on every watcher's live input (schema + skew) is a fail-open precondition: malformed/skewed actions route to ABSTAIN before the judge, and the validation report is part of the assurance trail proving inputs were in-contract.
58. **The ML Test Score is a 28-item rubric (data/model/infra/monitoring) quantifying production-readiness + technical-debt exposure.** Breck et al. 2017 (DOI:10.1109/BigData.2017.8258038). → The scoring template for the certified receipt: each watcher's recert receipt reports ML-Test-Score line items (shift monitoring present, skew checks present, rollback/compensator present) — a recognized production-readiness vocabulary, not bespoke.

### H. Human oversight efficacy + escalation semantics
59. **The EU AI Act only obligates providers to enable AWARENESS of automation bias; a provider-centric awareness mandate does not address design/context as the actual causes of over-reliance.** Laux & Ruschemeier 2025 (arXiv:2502.10036). → The fleet cannot claim Art.14 cover by merely surfacing an ABSTAIN; the assurance case treats the human-confirmation leg as a DEFEATER, and the receipt records the concrete de-biasing intervention applied (contrastive framing), not just that a human was "made aware."
60. **Art. 14 oversight works only when authority-to-override + genuine comprehension + an adequate (resourced) environment co-hold; absent these it collapses into rubber-stamping that can make good outputs worse.** Fink 2025 (SSRN 5147196).† → Each ABSTAIN-to-human receipt must positively assert all three Fink conditions for that reviewer; a handoff that cannot evidence them is logged as oversight-theater and its residual error published, not hidden.
61. **Automation complacency intensifies under multi-task load, appears in experts, and resists simple practice — over-reliance is the default human response, not an edge case.** Parasuraman & Manzey 2010 (DOI:10.1177/0018720810376055). → Assume baseline rubber-stamping (the reviewer is load-saturated): rate-limit escalations, force a contrastive choice, and NEVER count an unforced human "confirm" as independent corroboration of a watcher verdict in the assurance math.
62. **Contrastive explanations that anticipate the human's likely (mistaken) choice improve independent decision skill (N=628); one-sided explanations do not, with no accuracy loss.** Buçinca et al. 2024 (arXiv:2410.04253). → Make the contrastive frame a REQUIRED receipt field on every ABSTAIN-to-human handoff ("you likely read this as X; I abstained/flagged because Y") — the empirically-supported lever converting a rubber-stamp into an engaged decision.
63. **Effective alerting requires every page to be actionable and require intelligence; excessive low-value alerts train operators to skim/ignore and miss the real one.** Ewaschuk (in Beyer et al.) 2016 (Google SRE Book, Ch. 6).† → Triage inter-watcher disagreement like an SRE alert: only INFORMATIVE disagreement (e.g., conformance PASS but sycophancy ABSTAIN) escalates, each escalation carries a severity + required action, and correlated/duplicate flags are deduplicated — else the human leg fails by alert-fatigue exactly as [61] predicts.

## The architecture (each load-bearing choice traces to findings by number)

**Five subsystems + the receipt that ties them together. Every layer fails open to ABSTAIN — never asserts the
safe verdict on failure (the verifier/conformance/sycophancy cost-asymmetry, extended fleet-wide).**

### 1 — Aggregation: heterogeneous-duty fusion, NOT a vote
Each watcher emits per-duty `{pass | abstain | flag, calibrated_score, abstain_reason}`. The fleet does **not**
majority-vote across duties (they judge different properties) and does **not** assume independence. Fuse with a
**correlation-and-reliability-aware label model**: Dawid-Skene reliability [3] upgraded with EBCC/Snorkel/
multi-task dependence modeling [4,5,6] over a **measured pairwise error-correlation matrix on held-out receipts**
[2,6], recomputed every re-mint because correlation **grows with capability** [2]. Down-weight entangled
watchers; require a calibrated ≥2-agreement before a non-ABSTAIN flag [7]. Chair-Varshney is dropped as the
basis — [3] is the citable precedent.

### 2 — Calibration + the published residual-error budget
Each watcher is a **selective classifier** with a δ-guaranteed selective-risk operating point [9,12]; report
**E[false-clear] via Conformal Risk Control** (monotone FNR loss) [10]. Compose the fleet budget by **top-down
apportionment** [17] split across watchers via **Learn-then-Test FWER** [11] (handles the non-monotone
"any-watcher-flags" rule). Correct the JOINT bound for dependence with **Benjamini-Yekutieli** [16] (not plain
BH [15]) and inflate by a **measured common-cause β** [8]. Publish the residual as adaptive-ECE + Brier +
reliability diagram, **never bare ECE** [14]. SCOPE [13] is the template for advertising a finite-sample α on
non-abstained verdicts.

### 3 — Streaming-valid certification (the residual is read mid-stream)
Per window the receipt records an **anytime-valid bound** (e-process / confidence sequence [18,19,20]) so the
residual survives continuous peeking; the same streaming martingale **doubles as the drift trigger** [21].
Scheduled recert spends an **α-budget across looks** (Lan-DeMets [23], O'Brien-Fleming [22]); CUSUM/EWMA [24,25]
are cheap secondary triggers. Publish **both** the fixed-n point estimate and the (looser, honest) anytime-valid
envelope.

### 4 — Adversarial hardening (the audited action is a hostile producer)
Treat every audited action as adversarial-by-construction. Protect each LLM ceiling: **spotlight/datamark all
judged content** [46] (>50%→<2%), a **known-answer pre-filter → ABSTAIN on contamination** [47], optionally
**StruQ-train** the ceiling [49]. The **cross-family committee IS the security control** [44] (54-63pt ASR cut) —
record committee composition + per-family votes + dispersion as a tamper signal — but **mitigation, not
immunity** (50-62% transfer). Scoring-format choice is **attack-dependent** [44 vs 48] → record which + why,
never claim universal safety. **NEVER import literature ASR numbers** [45] — measure on the fleet's OWN held-out
adversarial receipts. Capability-scope the active prober [42].

### 5 — Active-probe producer access (unblocks the sycophancy active probe)
Formalize the two probes as CheckList **INV/DIR** [35] / explicit **metamorphic relations** [36] stored in the
receipt. Make the producer call **N>1** [37] → ABSTAIN on intra-sample contradiction. Score the **direction** of
any capitulation flip (regressive=defect), **pin content-free rebuttals**, avoid citation-style rebuttals
[38,39]. Trigger **selectively** with active-testing bias-correction [40]; generate a **probe family** [41] to
resist gaming while the property stays pinned + replayable. The prober runs capability-scoped (allowlist of
pinned probes, no side effects, different family) [42].

### 6 — The certified receipt (the artifact)
**Minimal credible receipt = an in-toto Statement + DSSE envelope** [27], Ed25519-signed, appended to an **RFC
6962 Merkle log** with inclusion proofs [26]. Predicate fields:
- per-watcher `{verdict|ABSTAIN, abstain_reason, calibrated_score}`; the **fused verdict + fusion-rule id +
  measured-correlation-matrix id** [3-7];
- the **anytime-valid residual bound** for the window [18-21] + the budget-allocation it sits under [11,16,17];
- the **THREAT-MODEL leg** [43-49]: producer-adversarial class, spotlight mode [46], KAD result [47], committee
  composition + per-family votes + dispersion [44], residual-ASR band (**measured, not imported** [45]);
- the **defeater-checklist outcome** (Gohar's 7 categories [31]) under eliminative argumentation [30];
- on any **ABSTAIN-to-human**: the **Fink three-conditions** assertion [60] + a **REQUIRED contrastive frame**
  [62] (the automation-bias mitigation [59,61]) + escalation severity [63].
Standing per-watcher artifacts: a **Model Card** [28] + a **minting-corpus Datasheet** [29] (the leakage-audit +
flip-consistency cert = the provenance the moat rests on). Regulatory mapping: the log satisfies **EU AI Act
Art. 12** [32], the human fields map **Art. 14**, cards+datasheets map **Annex IV**; framed as **ISO/IEC 42001**
AIMS evidence [33]; the whole is a **living/continuous assurance case** [34] regenerated on each base bump or
drift alarm.

### 7 — Recert + opex (the strategy correction)
**The strategy's "one base recertifies the fleet in one pass" is REFUTED** [54]: a base swap voids each
adapter's held-out receipts → re-mint + re-certify per watcher, or carry a transfer-validity proof; S-LoRA [53]
buys only co-serving economics. Recert triggers: BBSD/MMD shift on the live stream [55,56] gated on
classifier-margin/abstain rate (not raw input) [50], ADWIN on agreement-with-gold [51], a behavioral canary for
orchestrator-family vendor drift [52] (the silent decorrelation-breaker), a data-validation gate [57];
ML-Test-Score line items in every recert receipt [58].

### The honesty ↔ security tension (resolve by granularity)
Publishing the residual + probe bank is an attacker roadmap. **Resolution:** publish the residual at
**aggregate** granularity — a defensible β-inflated [8], BY-corrected [16] joint false-clear bound for the
assurance case [30] — while holding per-probe specifics + the **live probe bank as rotated secrets** [39,41].
The assurance case records that residual exists and is bounded, not the exact evasion recipe.

## Honest gaps (what is NOT settled — carried forward, not hidden)
- **No cited end-to-end heterogeneous-DUTY fusion with dependence modeling.** D&S/EBCC/Snorkel [3-6] assume the
  same latent label; fusing different duties into one verdict is a per-duty-label-model + meta-rule **synthesis**,
  not a single cited result. **Build + certify it; do not claim it from a paper.**
- **No measured error-correlation among ~14B distilled judges on these duties.** [2] is on full-size general-QA
  models — a strong directional warning, not a calibrated prior. **Measure the fleet's own matrix.**
- **β common-cause priors are NOT transferable** from hardware [8] — only the method is. Estimate β from receipts.
- **Committee ASR numbers are single-paper, small-scale (3-4B), unreplicated at 14B, no adaptive-attacker-knows-
  committee result** [44]; [45] warns they collapse under real shift. **Measure on own adversarial receipts.**
- **Comparative-vs-pointwise robustness is genuinely unresolved** ([44] vs [48], different attack classes).
- **Per-action cost/latency is NOT in the peer-reviewed literature** (three judges + N>1 active probe +
  retrieval). PoLL's 7× is judge-tier-only [1]. **A measure-it gap — benchmark the live fleet.**
- **Recert transfer-validity across a base swap is unestablished** [54] — treat as requiring fresh certification.
- **M-FISHER [21] is a single preprint** (VLM/CLIP TTA); the LLM-watcher-stream mapping is analogical pending
  validation; **and no single source unifies an anytime-valid bound with arbitrary-dependence FDR** — the
  "record both per-window" recommendation is an engineering composition, not one cited guarantee.
- **Inter-watcher escalation [63] is an SRE analogy**, not a measured result for an AI-verdict review queue.

## Standards compliance (the six — scored 0-3)
| Standard | Score | Evidence | Remediation |
|---|---|---|---|
| PIN_PER_STEP | **2** | Both swarm rounds persist a replayable script + run-ids (`wf_86e8d406-d5f`, `wf_66366ace-803`) with `resumeFromRunId` caching; the finding schema + per-question prompts are fixed in-script. Subagent model is inherited, not hashed. | P2 — emit a `dispatch.lock.json` (resolved subagent model id + per-agent prompt SHA-256 + gate run_id). |
| ANDON_AUTHORITY | **2** | Two enforced halts fired: the completeness critic halted progression to synthesis on a systemic gap → round-2 gap-fill; the Step-4 gate halts on fabricated/misattributed before any finding connects to architecture. | P3 — auto-halt a research lane that returns all `retrieved:false`. |
| NAMED_COMPENSATORS | **2** | **No skip** — this dispatch is a canon-write (a pushed doc that becomes a standing design). Compensators table below. | P2 — prove `requalify_dependent_slices` with a real receipt → 3. |
| DECOMPOSE_BY_SECRETS | **2** | One agent per question hides each search strategy behind a Parnas boundary; round 2 isolates the four gap modalities; the stable protocol vs the volatile questions are separated. | P3 — explicit stable/volatile callout. |
| UNCERTAINTY_GATED_HUMANS | **2** | The dispatch ends in Mike-gated decisions; Step-4 `CANNOT_CONFIRM` items are surfaced with a contrastive frame, never silently load-bearing; the design makes uncertainty-gated human handoff (with contrastive framing [62]) a first-class receipt field. | P3 — generalize the contrastive frame to the gap-list. |
| EXTERNAL_VERIFIER | **3** | Step-4 RUN via `roleos verify-citations` → prism: different family (ollama) by construction, reasoning-stripped, retrieval-oracle existence floor + groundedness lens. Signed receipt captured (`prism-01ktkn37nj24np47cd9xddeyrg`, `fleet-receipts-gate-result.json`); 0 fabricated / 0 misattributed; rate-limit tail + oracle-external items independently corroborated. A real dispatch through the runner with a captured receipt = the 3 criterion met. | — |

### Compensators table (NAMED_COMPENSATORS — no skip)
| Action | Irreversible? | Compensator (named undo) | Post-rollback state | Owner |
|---|---|---|---|---|
| Write/commit this dispatch doc | Mostly reversible | `revert_dispatch_commit` — `git revert <sha>` | Doc removed; if propagated, the row below applies | advisor |
| Dispatch propagates into a build decision (becomes canon) | **Yes** — git revert insufficient | `requalify_dependent_slices` — re-verify the affected slice vs the corrected/withdrawn finding; flag `evidence-withdrawn` until re-grounded | Downstream slice flagged, not silently live | advisor + slice owner |
| Dispatch N paid LLM research subagents (rounds 1+2) | **Yes** — spent tokens | `none` — bounded, owner-accepted (agent count ≤ 5+4+1; word caps) | Tokens spent | advisor |
| Step-4 gate run (local prism, read-only) | No | n/a | n/a | advisor |

## Mike-gated decisions (the point of the dispatch)
1. **Build the aggregation + receipt layer?** If yes, the first concrete slice is the **measured pairwise
   error-correlation matrix** on the existing certified receipts (closes the largest honest gap and is the
   precondition for any joint number) + the **in-toto/DSSE + Merkle receipt schema** [26,27].
2. **Adversarial hardening now or later?** Spotlighting [46] + KAD-to-ABSTAIN [47] are cheap and drop straight
   into the existing fail-open seam; they harden the three LIVE watchers immediately.
3. **Finish the sycophancy active probe** via the producer-access design (§5) — `prism probe-sycophancy` CLI /
   verify mode (the open finishing step) — gated by `PRISM_SYCOPHANCY_ENDPOINT`.
4. **Acknowledge the recert correction** [54]: update the strategy memory — a base bump is a re-mint+re-certify
   event, not a one-pass recert. (Memory edit, your call.)
5. **Citation: reuse the prism path vs a dedicated mint** — unchanged from the prior recommendation (reuse).
6. Standing Mike-gates remain OFF: the 3 consult flips, `PRISM_SYCOPHANCY_ENDPOINT`, HF publish, any push.
