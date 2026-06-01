# Prism — Research-Grounded Design Dispatch (2026-06-01)

## Executive summary

The market needs this product, but the wedge is narrower than the brief assumes. The runtime-verifier category is real and consolidating: Patronus has ~$40M raised and owns the "hallucination model" mindshare but ships post-hoc trace scoring rather than pre-tool-call adjudication (Report 7, Braintrust competitive review 2026); Galileo was absorbed into Cisco/Splunk on 2026-05-22 and now sells as enterprise AI observability, not developer-first verification (Report 7, Cisco Blogs 2026); Braintrust raised $80M in February 2026 but remains dataset-eval + post-hoc trace scoring (Report 7, Braintrust 2026). Crucially, Galileo's Luna-2 does ship runtime blocking — so prism cannot position on "no one does runtime adjudication." What no incumbent ships is the **three primitives enforced at the API contract**: family-different verifier by construction, reasoning-stripped by contract, and replayable receipts with submodularity-aware multi-lens. The academy has converged on this pattern (Report 7: CompassVerifier arXiv:2508.03686; ToolGate arXiv:2601.04688) but ships papers, not products.

The most defensible v1 vertical slice is **a four-lens runtime adjudicator with hard family-different routing across Anthropic / OpenAI / Gemini / local-vLLM, a 2s p50 sync budget, aggressive reasoning-strip by default, and signed replayable receipts** — narrowly scoped to code/tool-call artifacts where the heritage citations (Kambhampati 2024, Huang/DeepMind 2024, Rajan 2025) are strongest and where CodeJudgeBench (Jiang 2025) gives us a benchmark to publish against. Prose/RAG verification is deferred to v1.5; same-family fallback is explicitly refused-not-degraded.

## Architectural locks

### Lock 1: Family-different verifier (mandatory, no silent same-family fallback)

The caller declares its model family in `/verify` and prism refuses to serve a same-family verifier even under provider outage — outage returns `VERIFIER_UNAVAILABLE`, never silent same-family. This is the load-bearing primitive. Justifications: **Report 1, Panickssery/Bowman/Feng (NeurIPS 2024, arXiv:2404.13076)** — self-recognition correlates *linearly* with self-preference, so partial blinding does not help; **Report 1, Li et al. (ICLR 2026, arXiv:2502.01534)** — same-lineage judges favor outputs even without identity disclosure; **Report 5, Wataoka et al. (2024, arXiv:2410.21819)** — self-preference bias is perplexity-driven (familiarity), not just identity-driven, making it a *correctness* regression to fall back same-family, not a routing one; **Report 2, Du et al. (ICML 2024, arXiv:2305.14325) + Goel et al. (2025, arXiv:2506.07962)** — same-family debate is gain-limited because errors correlate above chance.

### Lock 2: Reasoning-stripped by contract (aggressive default, conservative mode opt-in only)

The producer's chain-of-thought, scratchpads, `<thinking>` blocks, OpenAI reasoning summaries, and DeepSeek-R1 `<think>` tags are stripped from the artifact before it crosses the family boundary; the strip is verified by re-parsing the post-strip artifact and rejecting if known patterns reappear. Justifications: **Report 1, Mendes et al. (2026, arXiv:2601.14691)** — manipulated CoT inflates VLM-judge false positives by up to 90% with observations/actions held fixed, so the trace is the demonstrated attack surface; **Report 1, Arcuschin et al. (2025, arXiv:2503.08679)** — in-the-wild CoTs are post-hoc rationalizations uncorrelated with the actual decision path; **Report 1, Buçinca et al. (CHI 2025, arXiv:2410.04253; CSCW 2021, arXiv:2102.09692)** — withholding producer justification and forcing contrastive evaluation improves independent decision-making without accuracy loss.

### Lock 3: Multi-lens by default (four lenses, three minimum, ship-blocked below three)

Prism runs at least three lenses in parallel; v1 ships four. The brief's "three lenses" floor is preserved but the recommended default is four because dropping below four leaves a known blind spot. Justifications: **Report 3, Manakul et al. (2023, arXiv:2303.08896)** — SelfCheckGPT ships five variants specifically because each catches a different hallucination class; **Report 3, Rajan (2025, arXiv:2511.16708)** — CodeX-Verify's four-lens design (Correctness, Security, Performance, Style) is the closest published prior art; **Report 7, Braintrust 2026** — DeepEval/RAGAS/LangSmith all rely on user-configurable single judges, leaving the multi-lens-by-contract slot open.

### Lock 4: Submodularity-aware (refuse on too-much-agreement, not just too-little)

Prism computes pairwise rho across lens findings and **refuses to advance if rho exceeds threshold** — lenses agreeing too much means they collapsed to a redundant signal and the multi-lens claim is fraudulent. v1 ships rho ≤ 0.25 as default with per-lens-pair override. Justifications: **Report 2, Rajan (2025, arXiv:2511.16708)** — empirical correlation matrix with off-diagonal rho ∈ [0.05, 0.25] on 99 code samples is the calibration anchor; **Report 1, "How Independent are LLMs?" (arXiv:2604.07650)** — verifier diversity hides correlated failure when models share lineage; **Report 2, Wynn/Satija/Hadfield (2025, arXiv:2509.05396)** — debate can *reduce* accuracy under peer pressure, so high-agreement is empirically a refuse signal.

## V1 lens inventory (recommended)

Four lenses, with a fifth (Style/Maintainability) reserved as opt-in for v1.1+.

**L1. Contract Completeness** — Does the artifact satisfy every clause of the declared intent? Heritage: Patronus answer-relevance + context-sufficiency rubric; Google eng-practices "design + functionality" axis. Catches uniquely: missing required behavior the producer omitted but didn't lie about.

**L2. Cross-Boundary Information Flow** — Does data cross trust boundaries (PII to logs, untrusted input to tool calls, secret exfiltration) without contract permission? Heritage: NeMo Guardrails Agentic Security; SAST/DAST taint-tracking complementarity (MDPI 2020 — SAST wins 3 OWASP categories, DAST wins 4, with low overlap). Catches uniquely: behaviorally valid artifacts that smuggle information.

**L3. Invariant & Test-Adequacy** — Do claimed invariants hold under provided test cases, and is the test suite sufficient to detect a planted bug? Heritage: CodeX-Verify Correctness lens (Rajan 2025); Kambhampati LLM-Modulo external-verifier doctrine (arXiv:2402.01817). Catches uniquely: structurally well-formed artifacts whose invariants are unsatisfiable.

**L4. Groundedness / Hallucination** — For artifacts that cite/paraphrase external sources, does every load-bearing claim trace to a provided source? Heritage: SelfCheckGPT NLI variant (arXiv:2303.08896); Galileo ChainPoll Context Adherence. Catches uniquely: confident fabrications — the single most-studied failure mode in production LLM systems.

Reserved for v1.1+: **L5. Style/Maintainability**, gated opt-in because Bacchelli & Bird (ICSE 2013) show humans drift toward style when chasing bugs — useful as an explicit lens, dangerous as a default.

## V1 alt-family routing policy

**Supported families at launch (four):**
- Anthropic (Claude Haiku 4.5 / Sonnet 4.6 / Opus 4.7)
- OpenAI (GPT-5 / GPT-5.4-mini / GPT-5.5)
- Google (Gemini 2.5 Pro, GA SKU pinned — never preview)
- Local vLLM (Qwen 3.x and DeepSeek V4 for code; Hermes 4 70B / Llama 4 for prose)

**Routing algorithm when caller declares family X:**
1. Select primary alt-family from a fixed disjoint-family map: Anthropic-caller → Gemini 2.5 Pro primary, GPT-5.4-mini secondary, local Qwen 3.x tertiary; OpenAI-caller → Sonnet 4.6 primary, Gemini 2.5 Pro secondary; Gemini-caller → Sonnet 4.6 primary, GPT-5.4-mini secondary; local-caller → any hosted alt-family primary.
2. Default to cheap-tier (Haiku-class, GPT-mini-class) — Haiku 4.5 has most predictable p95 for short structured-output prompts; Sonnet/Opus reserved for `escalate` verdicts only.
3. Cache lens prompts to exploit Anthropic 90% cached-input discount and Gemini 50% batch discount.

**Fallback chain on outage:** 429/5xx → secondary alt-family within 2s budget; circuit-breaker open after 3 consecutive failures within 60s. **If every cross-family path fails: refuse with `VERIFIER_UNAVAILABLE`, never fall back same-family.**

**Compliance pins:** EU callers → EU-region endpoints by default before 2026-08-02 AI Act Article 16 enforcement. DeepSeek-hosted gated behind explicit `us_export_controls_acknowledged=true` flag; DeepSeek-local always available.

## V1 latency budget and async escalation

**Sync target: p50 ≤ 2.0s, p99 ≤ 4.0s, hard timeout 10s.** Grounded in Nielsen's 1s/10s thresholds and Drager et al.'s LLM-specific 2s/4s pivot (arXiv:2604.06183). Achievable across Anthropic Sonnet 4.6 (TokenMix 500ms TTFT median) and Haiku 4.5 (sub-600ms TTFT p95).

**Budget framing: ≤ 10% of caller's agent-step latency, configurable.**

**Async-speculative escalation triggers:**
- Artifact requires reasoning-tier verifier (o3, Claude Opus thinking) — o3 alone busts the 10s ceiling.
- 3+ lenses must run serially due to capacity constraints.
- Caller passes `mode=speculative` — Sherlock pattern (Qiu et al. 2025, arXiv:2511.00330) achieves up to 48.7% latency reduction.

**Refusal with `BUDGET_EXCEEDED`:** When estimated lens-fanout × p99 TTFT exceeds caller's declared `budget_ms` and caller hasn't opted into async-speculative.

## V1 reasoning-stripping policy

**Aggressive default behavior:**
- Strip `<thinking>`, `<reasoning>`, `<scratchpad>`, `<scratch>` tags and contents.
- Strip OpenAI reasoning-summary blocks (`reasoning.content`, `reasoning.summary`).
- Strip DeepSeek-R1 `<think>...</think>` blocks.
- Strip Anthropic `thinking` content blocks (defensively, even though API auto-strips cross-turn).
- Strip vendor-namespaced trace fields: `claude.thinking.*`, `openai.reasoning.*`, `gemini.thinking.*`, `deepseek.think.*`.
- Strip nested reasoning inside tool-call arguments and tool-call results.

**Strip verification (post-strip integrity check):**
- Re-parse stripped artifact with same tag/regex registry. If any pattern matches in post-strip body, **reject with `STRIP_VERIFICATION_FAILED`** — do not proceed with partially-stripped artifact (silent failure mode otherwise).
- Compute SHA-256 of pre-strip and post-strip artifacts; both hashes go into the replayable receipt.
- Log strip-bytes-removed per request; sudden drops across releases signal a new vendor format leaked through.

**Conservative mode (`reasoning_visibility=conservative`, opt-in):**
- Preserves a *producer-authored summary* (max 500 chars, plain text) when caller asserts verifier family is provably disjoint AND task is trace-dependent (proof verification, multi-step tool-call audit).
- Never preserves raw trace, only a summary the producer wrote for the verifier (separate field).
- Logs the leak in the receipt as `reasoning_visibility_mode=conservative` with the summary's hash.

**Anti-pattern: no "trust upstream stripping" mode.** Only Anthropic's API contractually strips today; OpenAI o-series exposes summaries and DeepSeek-R1 exposes full traces. Trusting upstream produces silent failures on those providers.

## V1 submodularity threshold and metric

**Default metric: Jaccard similarity on (file, line, finding-category) tuple sets, per lens-pair.** Threshold: **rho ≤ 0.25 per pair**; if any pair exceeds, refuse with `LENS_COLLAPSE`. Receipt carries the full pairwise rho matrix.

**Empirical basis:** Rajan 2025 (arXiv:2511.16708) reports rho ∈ [0.05, 0.25] across four agents on 99 code samples. **Caveat documented in threat model:** Rajan does not specify whether his rho is Pearson, Spearman, or Jaccard, nor whether over binary findings / severity scores / file:line sets. Prism's choice of Jaccard-on-file:line-finding-sets is a documented extrapolation.

**Why Jaccard, not AST-edit-distance or Cohen's kappa:** Song et al. (ACL 2024) show AST-edit-distance is semantically richer but expensive and language-specific. Galileo's production guidance prefers chance-corrected agreement (kappa/Krippendorff) for human-vs-judge calibration. v1 chooses Jaccard for cheap explainability and uniform behavior across artifact types; **AST-distance and Cohen's kappa are roadmap items for v1.1** once prism has its own calibration corpus.

**Per-lens-pair, not global:** the `/verify` request can override threshold per pair (`pairwise_rho_thresholds: {"L1,L2": 0.30, "L1,L4": 0.20}`) because some pairs are *expected* to correlate more.

**Degenerate-case refusal independent of measured rho:** if `caller_family == verifier_family` after routing somehow produced same-family assignment, refuse regardless of rho.

## V1 refusal-to-compensator API

**Response shape (sync HTTP, structured body):**

```json
{
  "verdict": "accept" | "revise" | "refuse" | "escalate",
  "confidence": 0.0-1.0,
  "retryable": true | false,
  "revision_hint": "<= 500 chars, optional, only on verdict=revise>",
  "lens_results": [
    {"lens": "L1", "outcome": "...", "findings": [...]}
  ],
  "pairwise_rho": {"L1,L2": 0.18},
  "receipt_id": "prism-...",
  "receipt_signature": "<HMAC over canonical receipt>"
}
```

**Four-value verdict enum** mirrors SagaLLM's Rejection/Augmentation/Feedback (Wei et al. 2025, arXiv:2503.11951) plus `escalate` for human-in-the-loop. `retryable` boolean matches Temporal's `non_retryable` ApplicationFailure flag so existing saga code branches deterministically.

**Prism never auto-triggers caller compensators.** The caller's saga coordinator owns rollback, exactly as SagaLLM's SagaCoordinatorAgent and Temporal's user-code-owns-unwind doctrine both prescribe. Prism advises; the caller enforces.

**`revision_hint` repair-loop ceiling:** capped at *one* model-assisted retry per OpenAI Cookbook guidance; prism does not loop internally.

**Fallback for callers without compensators:** verdict is still actionable — `accept` proceeds, `refuse` blocks at the call site, `revise` surfaces hint as user-facing error, `escalate` routes to a queue.

**Optional signed-webhook channel** (Stripe-style HMAC + `receipt_id` as idempotency key) offered *only* for `escalate` verdicts that exceed sync budget.

**Replayable receipt** carries pre/post-strip artifact hashes, lens prompts (hashed), verifier model + version, pairwise rho matrix, and HMAC signature so compensators can prove which refusal they're responding to.

## Competitive positioning

The wedge is **partially confirmed and must be repositioned**. The simple claim "no one ships runtime LLM verification" is refuted: Galileo Luna-2 ships runtime guardrails with low-latency scoring. The defensible claim is sharper: **no one ships family-different + reasoning-stripped + submodularity-aware multi-lens with replayable receipts as a single API contract.** Closest competitors: Patronus AI (post-hoc trace integration, single-judge, no family-different guarantee), Galileo / Cisco-Splunk (runtime-capable but observability-framed, no family-different contract, no receipts), Braintrust (dataset-eval + post-hoc trace scoring, not pre-tool-call adjudicator). Lead messaging on submodularity-aware multi-lens + signed receipts (the two primitives no incumbent ships); treat family-different as the architectural guarantee that makes the receipts trustworthy under Kambhampati 2024 + Huang/DeepMind 2024 self-verification impossibility results.

## Open questions deferred to v1.5+

- Chance-corrected agreement (Cohen's kappa / Krippendorff's alpha) vs raw Jaccard — needs prism's own calibration corpus.
- AST-edit-distance as the rho metric for code artifacts (Song 2024) — semantically richer than Jaccard but language-specific.
- L5 Style/Maintainability as a default lens vs permanent opt-in — needs production data on attention budget displacement.
- Conservative mode summary: producer-authored or verifier-extracted?
- Same-family fallback as an explicitly-degraded mode with `degraded=true` flag — currently we refuse; some enterprise callers may want degraded-with-warning.
- Async-speculative as the default mode for reasoning-tier verifiers — currently opt-in.
- L4 Groundedness for non-RAG artifacts — strongest for cited/paraphrased content; behavior for pure-generative needs more research.
- Prose / RAG verification track as parallel product line — v1 narrows to code/tool-call artifacts.

## Sources cited (consolidated bibliography)

### Reasoning-stripping and judge-bias literature (Report 1)
- Mendes et al. 2026, *Gaming the Judge: Unfaithful Chain-of-Thought Can Undermine Agent Evaluation*, https://arxiv.org/abs/2601.14691
- Arcuschin et al. 2025, *Chain-of-Thought Reasoning In The Wild Is Not Always Faithful*, https://arxiv.org/pdf/2503.08679
- Li et al. ICLR 2026, *Preference Leakage: A Contamination Problem in LLM-as-a-judge*, https://arxiv.org/abs/2502.01534
- Panickssery, Bowman & Feng NeurIPS 2024, *LLM Evaluators Recognize and Favor Their Own Generations*, https://arxiv.org/abs/2404.13076
- Shi et al. 2024-25, *Judging the Judges: A Systematic Study of Position Bias in LLM-as-a-Judge*, https://arxiv.org/abs/2406.07791
- Verga et al. 2024, *Replacing Judges with Juries (PoLL)*, https://arxiv.org/pdf/2404.18796
- "How Independent are Large Language Models?" 2026, https://arxiv.org/pdf/2604.07650
- Anthropic 2025-26, *Building with extended thinking*, https://docs.claude.com/en/docs/build-with-claude/extended-thinking
- Drori et al. 2025, *Output Supervision Can Obfuscate the Chain of Thought*, https://arxiv.org/abs/2511.11584
- Buçinca, Malaya & Gajos CSCW 2021, *To Trust or to Think*, https://arxiv.org/abs/2102.09692
- Buçinca et al. CHI 2025, *Contrastive Explanations*, https://arxiv.org/abs/2410.04253

### Submodularity, multi-agent verification, similarity metrics (Report 2)
- Rajan 2025, *Multi-Agent Code Verification via Information Theory*, https://arxiv.org/abs/2511.16708
- Du et al. ICML 2024, *Improving Factuality and Reasoning through Multiagent Debate*, https://arxiv.org/abs/2305.14325
- Wynn, Satija & Hadfield 2025, *Talk Isn't Always Cheap*, https://arxiv.org/abs/2509.05396
- Huang et al. DeepMind ICLR 2024, *LLMs Cannot Self-Correct Reasoning Yet*, https://arxiv.org/abs/2310.01798
- Kambhampati et al. ICML 2024, *LLMs Can't Plan, But Can Help Planning (LLM-Modulo)*, https://arxiv.org/abs/2402.01817
- Song et al. ACL 2024, *Revisiting Code Similarity with AST Edit Distance*, https://arxiv.org/abs/2404.08817
- Goel et al. 2025, *Correlated Errors in Large Language Models*, https://arxiv.org/html/2506.07962v1
- Galileo 2024-25, *Cohen's Kappa Metric for LLM Judge Calibration*, https://galileo.ai/blog/cohens-kappa-metric

### Lens taxonomy and verifier rubrics (Report 3)
- Bai et al. Anthropic 2022, *Constitutional AI: Harmlessness from AI Feedback*, https://arxiv.org/abs/2212.08073
- Hubinger et al. Anthropic 2024, *Sleeper Agents*, https://arxiv.org/abs/2401.05566
- NVIDIA 2026, *NeMo Guardrails Catalog*, https://docs.nvidia.com/nemo/guardrails/latest/configure-rails/guardrail-catalog/index.html
- Patronus 2025, *Lynx & Glider docs*, https://docs.patronus.ai/docs/research_and_differentiators/Lynx/base
- Galileo 2024, *Hallucination Index Methodology*, https://www.galileo.ai/hallucinationindex/methodology
- Manakul et al. 2023, *SelfCheckGPT*, https://arxiv.org/abs/2303.08896
- Google 2025, *What to look for in a code review*, https://google.github.io/eng-practices/review/reviewer/looking-for.html
- Bacchelli & Bird ICSE 2013, *Expectations, Outcomes, and Challenges of Modern Code Review*, https://www.microsoft.com/en-us/research/publication/expectations-outcomes-and-challenges-of-modern-code-review/
- MDPI 2020, *On Combining Static, Dynamic and Interactive Analysis*, https://www.mdpi.com/2076-3417/10/24/9119

### Latency, async escalation, agent-frameworks (Report 4)
- Nielsen NN/g 1993, *Response Times: The 3 Important Limits*, https://www.nngroup.com/articles/response-times-3-important-limits/
- Drager et al. 2026, *The Impact of Response Latency and Task Type on Human-LLM Interaction*, https://arxiv.org/pdf/2604.06183
- TokenMix.ai April 2026, *AI API Latency Benchmark*, https://tokenmix.ai/blog/ai-api-latency-benchmark
- Kunal Ganglani March 2026, *LLM API Latency Benchmarks*, https://www.kunalganglani.com/blog/llm-api-latency-benchmarks-2026
- Helicone 2025, *o3 vs o1 latency*, https://www.helicone.ai/blog/openai-o3
- SitePoint 2026, *Ollama vs vLLM Performance Benchmark*, https://www.sitepoint.com/ollama-vs-vllm-performance-benchmark-2026/
- Red Hat 2025, *Ollama vs vLLM Deep Dive*, https://developers.redhat.com/articles/2025/08/08/ollama-vs-vllm-deep-dive-performance-benchmarking
- Qiu et al. Microsoft Research 2025, *Sherlock: Reliable and Efficient Agentic Workflow Execution*, https://arxiv.org/abs/2511.00330
- AgentMarketCap April 2026, *LangGraph vs Temporal*, https://agentmarketcap.ai/blog/2026/04/08/langgraph-vs-temporal-long-running-agent-workflows-2026
- Tucker et al. 2025, *Economic Evaluation of LLMs*, https://arxiv.org/pdf/2507.03834

### Alt-family providers, pricing, compliance (Report 5)
- Maxim/Bifrost 2026, *Anthropic Claude API status & uptime*, https://www.getmaxim.ai/bifrost/provider-status/anthropic
- Google Cloud 2026, *Gemini Enterprise SLA*, https://cloud.google.com/terms/gemini-enterprise/sla
- OpenAI 2026, *API Pricing*, https://openai.com/api/pricing/
- CloudZero 2026, *Anthropic Claude API Pricing*, https://www.cloudzero.com/blog/claude-api-pricing/
- Google AI 2026, *Gemini Developer API pricing*, https://ai.google.dev/gemini-api/docs/pricing
- Wataoka et al. 2024, *Self-Preference Bias in LLM-as-a-Judge*, https://arxiv.org/abs/2410.21819
- Jiang et al. 2025, *CodeJudgeBench*, https://arxiv.org/abs/2507.10535
- Codersera 2026, *Llama 4 Complete Guide*, https://codersera.com/blog/llama-4-complete-guide-2026/
- Lyceum Technology 2026, *EU Data Residency for AI Infrastructure*, https://lyceum.technology/magazine/eu-data-residency-ai-infrastructure/
- EU AI Act 2024, *Article 6: Classification Rules for High-Risk AI Systems*, https://artificialintelligenceact.eu/article/6/
- House Select Committee on the CCP 2025, *DeepSeek Unmasked*, http://selectcommitteeontheccp.house.gov/media/reports/deepseek-unmasked-exposing-ccps-latest-tool-spying-stealing-and-subverting-us-export
- Portkey 2026, *Failover routing strategies for LLMs in production*, https://portkey.ai/blog/failover-routing-strategies-for-llms-in-production/
- Maxim 2026, *Retries, Fallbacks, and Circuit Breakers in LLM Apps*, https://www.getmaxim.ai/articles/retries-fallbacks-and-circuit-breakers-in-llm-apps-a-production-guide/

### Saga, compensator, refusal API patterns (Report 6)
- Temporal 2025, *Failures reference*, https://docs.temporal.io/references/failures
- Temporal 2025, *Error handling — Python SDK*, https://docs.temporal.io/develop/python/best-practices/error-handling
- Inngest 2025, *Rollbacks documentation*, https://www.inngest.com/docs/features/inngest-functions/error-retries/rollbacks
- Wei et al. 2025, *SagaLLM*, https://arxiv.org/abs/2503.11951
- OpenAI 2025, *Agents Guardrails docs*, https://developers.openai.com/api/docs/guides/agents/guardrails-approvals
- OpenAI Cookbook 2025, *How to implement LLM guardrails*, https://developers.openai.com/cookbook/examples/how_to_use_guardrails
- Anthropic engineering, *Constitutional AI summary*, https://www.anthropic.com/research/constitutional-ai-harmlessness-from-ai-feedback
- Stripe 2025, *Webhooks documentation*, https://docs.stripe.com/webhooks
- DevSecOps Now 2025, *Validating webhook guide (Kubernetes)*, https://www.devsecopsnow.com/validating-webhook/
- Hugging Face forums 2025, *AuditPlane: Signed Decision Receipts*, https://discuss.huggingface.co/t/auditplane-signed-decision-receipts-replay-drift-diffs-for-llm-safety/172374
- *Tool Receipts, not ZK Proofs* 2026, https://arxiv.org/pdf/2603.10060

### Competitive landscape (Report 7)
- VentureBeat 2024, *Patronus AI Series A*, https://venturebeat.com/ai/patronus-ai-secures-17m-to-tackle-ai-hallucinations-and-copyright-violations-fuel-enterprise-adoption
- Cisco Blogs 2026, *Cisco announces intent to acquire Galileo*, https://blogs.cisco.com/news/cisco-announces-the-intent-to-acquire-galileo
- Braintrust 2026, *Best Hallucination Detection Tools 2026*, https://www.braintrust.dev/articles/best-hallucination-detection-tools-2026
- AI Security Directory 2026, *NeMo Guardrails vs Lakera Guard*, https://aisecurityandsafety.org/en/compare/nemo-guardrails-vs-lakera-guard/
- Atlan 2026, *LLM Evaluation Frameworks Compared*, https://atlan.com/know/llm-evaluation-frameworks-compared/
- DeepEval docs, *LLM-as-a-Judge guides*, https://deepeval.com/guides/guides-llm-as-a-judge
- LangChain docs, *LangSmith LLM-as-judge*, https://docs.langchain.com/langsmith/llm-as-judge
- *CompassVerifier* 2025, https://arxiv.org/pdf/2508.03686
- *ToolGate* 2026, https://arxiv.org/pdf/2601.04688
- *Probabilistic model-checking runtime enforcement* 2025, https://arxiv.org/html/2508.00500v1
