# Prism — Roadmap (post-v0.4, session-based)

How to read this: prism is built in **session-sized slices** (v0.1 → v0.2 → v0.3 citations →
v0.4 service). Each slice below is one such session — a coherent, shippable chunk — ordered by my
read of value-vs-risk, grounded in the study-swarms that produced the locks (`design/01`,
`design/04`, `design/05`) plus engineering judgment from building v0.4. Each slice, when built,
carries its own design doc + a `design/02` Standards-compliance update + NO-SKIP compensators per
[[workflow-standards]] — the roadmap itself is a planning doc, not a workflow.

Status at v0.4.2: installable (PyPI + npm) · HTTP-callable (FastAPI) · independently-verifiable
(Ed25519). 227 tests, workflow-standards 15/15.

---

## What's most missing — my read (the opinionated part)

Three gaps stand out. The first is the one I'd close before anything else.

1. **prism is research-grounded-by-citation, but not validated-on-its-own-data.** Every lock rests
   on a *borrowed* empirical anchor: the ρ ≤ 0.25 submodularity threshold comes from Rajan's 99
   code samples (arXiv:2511.16708), "diversity beats count" from Kim 2025 (arXiv:2506.07962),
   family-different from Panickssery 2024 (arXiv:2404.13076). prism has **never measured its own
   pairwise ρ, per-lens precision/recall, or the submodular-coverage gain on a labeled corpus.** The
   v1 prompts in `src/prism/lenses/*.py` are explicitly "first-cut." Until prism runs its lenses
   over ground truth and *measures* what it currently only *asserts*, the locks are principled but
   unproven on prism's own distribution — and `design/01` defers Cohen's-kappa, AST-edit-distance,
   and the L5 Style lens precisely "pending prism's own calibration corpus." **This is Slice 1, and
   it unlocks three deferred items.**

2. **Cost metering is the abuse control prism named but only half-built.** v0.4 ships size + concurrency
   caps, but OWASP LLM10 (Unbounded Consumption / "denial of wallet") is emphatic that *token/cost*
   throttling — not request count — is the control teams miss, with real 2026 incidents at $46k/day.
   prism is a paid-compute service now; a per-key **token/cost budget** (needs provider token
   telemetry) is the real control. Half-done is a known-gap, not a finished story.

3. **The crypto ceiling is disclosed but not closed.** I shipped the honest disclosure (an on-disk
   Ed25519 key is forgeable by a local-root attacker — third-party verifiability, not anti-forgery;
   Crosby & Wallach 2009). The *named* genuine-tamper-resistance path — HSM-held keys + an
   append-only transparency log, or Sigstore-keyless signing (PEP 740 / in-toto prior art) — is
   unbuilt. Not urgent (it's disclosed), but it's the "safe" axis the research-grounded protocol
   asks us to actually walk, not just point at.

---

## The slices (ordered)

### Slice 1 — Calibration corpus + benchmark (target v0.5) — *do this first*

**Goal:** measure, on prism's own labeled data, what the locks currently assert; publish a benchmark.

- Build a labeled corpus: planted-bug vs clean code (per the InvariantLens/contract classes),
  cited-vs-fabricated citations (reuse the meta-test traps), boundary-leak vs clean tool-calls.
- Run all lenses over it → emit a report: actual **pairwise ρ matrix** (validate the 0.25 threshold
  on real data, not Rajan's extrapolation), **per-lens precision/recall**, and whether the *union*
  beats any *single* lens (the submodular-coverage thesis — on prism's own data this time).
- Publish a results table against **CodeJudgeBench** (Jiang 2025, arXiv:2507.10535) — named in
  `design/01` as the benchmark, still unused. Ship an `eval/` pack + a `prism eval` command.
- **Unlocks** the three `design/01` deferrals: chance-corrected agreement (Cohen's kappa /
  Krippendorff — Galileo guidance), AST-edit-distance ρ for code (Song 2024, arXiv:2404.08817), and
  the **L5 Style/Maintainability** lens (Bacchelli & Bird ICSE 2013 — gate it on data, not vibes).
- *Studies:* Rajan 2511.16708 · Kim 2506.07962 · Jiang 2507.10535 · Song 2404.08817.

### Slice 2 — Prose / RAG verification track (target v0.6) — *the parallel product line*

**Goal:** the general prose/RAG groundedness layer `design/01` deferred (v1 narrowed to code/tool-call;
v0.3 citations were the *first* prose/RAG track — this generalizes it to RAG-answer verification).

- A `prose`/`rag` artifact type: decompose a prose answer into claim-triplets (RefChecker, Hu 2024,
  arXiv:2405.14486 — triplets beat sentence-level by 6.8–26.1 pts), verify each against the
  provided/retrieved source(s) with NLI-style support + a cited span (SciFact rationale, Wadden
  2020, arXiv:2004.14974), reusing the citation existence-floor pattern where sources are URLs.
- *Studies:* SelfCheckGPT (Manakul 2303.08896) · FActScore (Min 2305.14251) · ALCE (Gao 2305.14627)
  · RefChecker (Hu 2405.14486) · RAGAS (Es 2309.15217) · Onweller 2605.06635 (link-valid ≠
  claim-supported). **Validate on the Slice-1 corpus before shipping.**

### Slice 3 — Service hardening (target v0.5.x / v0.6, incremental)

**Goal:** make the v0.4 HTTP service genuinely production-operable.

- **Durable async** — replace the in-process `asyncio` task (lost on crash, disclosed in `design/05`)
  with a real queue (ARQ/Redis), and add the **polling status-monitor** variant (`202` + `Location`
  + a pending-receipt state read by `GET /replay`) alongside webhook delivery — the Google AIP-151
  shape `design/05`'s study-swarm recommended but v0.4 only half-took.
- **Per-token cost metering** (gap #2 above) — wire provider token-usage into per-key cost budgets.
- **Observability** — structured logs + metrics (verdict rates, latency p50/p99, refusal-reason
  counters, per-key cost). A verifier with no operator telemetry is a black box.
- **`GET /pubkey`** (or a published JWKS / `/.well-known/prism-pubkey`) — turnkey Ed25519 key
  distribution over a trusted channel (C2PA: a signature without a key-distribution story just
  relocates trust). Today only the `prism pubkey` CLI prints it.
- **Hardening tier:** mTLS/DPoP token-binding (RFC 9700, named/deferred) for operators terminating
  their own TLS; multi-tenant isolation if/when prism is ever hosted.

### Slice 4 — Citation v2 (target v0.5.x) — *harden the shipped layer*

- **Exact submitted-vs-adjudicated count coverage** — the role-os adversarial pass flagged
  accept-with-*fewer*-results: if prism adjudicated fewer citations than were submitted (an
  extraction/parse miss), it must surface/refuse, not silently accept the subset.
- **Semantic-Scholar / OpenAlex enrichment** (key-gated) + **full-text escalation** (the
  `NOT_ADDRESSED`/numeric path fetches full text instead of escalating to a human) — both deferred
  in `design/04` out-of-scope.
- **VCR-style record/replay cassette** for fully-offline, deterministically-replayable retrieval —
  74% of un-pinned research artifacts fail to re-run (Trisovic 2022, DOI:10.1038/s41597-022-01143-6);
  the receipt pins the *hash*, the cassette pins the *bytes*.
- Crossref bibliographic title-search fallback (fuzzy → `UNRESOLVABLE`, precision-biased).

### Slice 5 — Crypto + tamper-resistance (target v0.6.x) — *close the disclosed ceiling*

- **Operationalize Ed25519 key rotation** — v0.4 has the `kid` field but no rotation flow: a
  kid-keyed multi-key verification registry (verify old receipts with the old key after rotation),
  documented per JWS/JWK (RFC 7515/7517).
- **Genuine tamper-resistance** (gap #3) — HSM-held signing keys + an append-only transparency log
  (Crosby & Wallach 2009, USENIX) or Sigstore-keyless receipt signing (PEP 740 / in-toto prior art),
  so a receipt resists a local-root attacker, not just an external tamperer.
- **A TLS integration test** proving the webhook SSRF connection-pinning — connecting to the
  validated IP while verifying the cert against the hostname (the `sni_hostname` path) is the one
  v0.4 security control I could not verify in CI (only mocked).

### Slice 6 — Loose ends (fold in opportunistically)

- A committed **Ollama E2E test** — the kickoff stretch; manually proven against `mistral-small:24b`
  but never landed as a test (integration tests mock providers, so provider-shape drift is uncaught).
- **Conservative reasoning-visibility mode** (`design/01` deferred) — a producer-authored summary
  when the verifier family is provably disjoint AND the task is trace-dependent (proof/multi-step
  audit), logged in the receipt.
- **Same-family-fallback degraded mode** (`design/01` deferred) — a `degraded=true` flag for
  enterprise callers who want degraded-with-warning instead of a hard `VERIFIER_UNAVAILABLE` refusal.

---

## Sequencing rationale

Slice 1 first because it converts prism from *cited* to *measured* and unblocks the most deferred
work (the metrics + the L5 lens) — and because every later slice (prose track, citation v2) should
be validated *on the corpus Slice 1 builds*, not shipped on intuition. Slice 3's cost-metering and
Slice 5's crypto-ceiling are the two "we named the right thing but only half-did it" items, so they
rank above the genuinely-new product surface area where the v0.4 floor is already honest. The prose
track (Slice 2) is the biggest *product* expansion but deliberately sits behind the corpus — shipping
a new verification surface without the means to measure it would repeat the very gap this roadmap's
top finding names.
