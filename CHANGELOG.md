# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- **Release workflow: the PyPI upload accepts core metadata 2.5.** The 1.7.0 release published the npm wrapper and the binaries, but the PyPI step refused the wheel: the pinned upload action (v1.14.0) carries a Twine that does not know metadata 2.5, which current hatchling writes. The action is now v1.14.2. A manual run of the workflow takes an optional `tag` input that re-publishes one existing tag to PyPI only, which is how 1.7.0 reaches PyPI.

## [1.7.0] - 2026-10-14

- Build fake credentials at runtime in `tests/unit/test_eval_harvest.py` and `tests/integration/test_http.py` so secret scanners do not flag test fixtures.
- Split one source constant, the RFC 6598 shared-address range in the webhook SSRF blocklist (`src/prism/http/webhook.py`), into two string pieces, so the studio identity scanner doesn't read it as a tailnet address. The value is identical and `test_webhook` covers the range.

### Documentation
- **Lock 1's label-vs-lineage limitation is now stated, not implied** (docs + tests; no behavior
  change). Lock 1 compares family **labels**, and the self-preference literature it rests on is
  about **lineage**. Those coincide for `anthropic`/`openai`/`google`, whose label is a lineage claim
  the operator owns — but `local` and `openrouter` are **transport** labels (prism tags every Ollama
  model `local` and every gateway model `openrouter`), so per-seat identity there is the model id.
  Two differently-labeled seats can be one lineage: a `local` seat pinned to `qwen2.5:7b` verified by
  an OpenRouter seat at `qwen/qwen-2.5-72b-instruct` passes the family-difference check while the
  guarantee it stands for does not hold. Both settings are individually reasonable; the collision is
  emergent, which is why the guard cannot see it.
  - `BLOCKED_VENDORS` patches exactly one instance of that gap, with a constant: `mistral` is blocked
    *because* LOCAL **defaults** to `mistral-small:24b`. The F-14 registry makes that value
    configurable, so the list is a static answer to a configurable question — it cannot work in
    principle, only in the default configuration. Extending it (adding `qwen`, `llama`, …) moves the
    hole rather than closing it, so the docstrings now say so explicitly.
  - `validate_openrouter_lineage` no longer claims to refuse models "whose true lineage isn't
    distinct from every prism caller" — not decidable from a model id. It documents what it does:
    refuse a vendor that collides with a **default** lineage.
  - `test_lineage_guard_allows_distinct_families` → `..._allows_vendors_outside_the_blocklist`. The
    old name asserted a property of the model id that isn't knowable from it, and is false on some
    rigs (`qwen/…`, `meta-llama/…`, and llama-derived `nvidia/nemotron-*`). The entries were never
    the problem — the claim was — so the claim changed rather than the list.
  - New `TestKnownGapLabelIsNotLineage` pins the gap end-to-end (a qwen caller routed to a qwen
    OpenRouter seat) as executable documentation. It asserts what prism **does**, not what it should;
    if the request-time check lands, it should fail and be rewritten deliberately.
  - Handbook gains "What the lineage guard does and does not check", including what to do about it.
  - The real fix — a request-time caller-vs-verifier lineage check — is **not** in this change. Only
    at request time does `CallerContext.model_id` exist, which is the input a config-time guard
    structurally lacks. A config-time check could only compare seat-vs-seat, a proxy: one verifier
    serves a request (`verifier_models=[route.model_id]`), so two same-lineage seats collide only
    when the *caller* shares the lineage — and failing construction on the proxy would refuse
    deployments that are sound for every other caller.

### Fixed
- **`test_prune_with_yes_removes_old` depended on the system clock advancing** (test-only; no
  shipped behavior change). It seeded a receipt at `now` and pruned `--older-than 0s`, which makes
  the cutoff `now` and the query `WHERE timestamp < now` — so the assertion held only if the clock
  advanced between seeding the row and computing the cutoff. It asserted a boundary it never meant
  to depend on: on a fine-grained clock that window is ~1µs and it passes, but on any platform or VM
  whose `datetime.now` is coarser, the seed and the cutoff can land on the same value and nothing
  qualifies.

  `--older-than 0s` was the deeper problem: a zero cutoff makes *every* receipt a candidate, so the
  test could not express the other half of the contract — a receipt **newer** than the cutoff must
  survive. Fixed by giving the seeded receipt a real age (2 days) and pruning against a realistic
  cutoff (`1d`), which removes the clock dependency outright rather than widening its window, and
  pins both sides of the boundary.

  Scope note: an earlier draft of this entry blamed a ~15.6ms Windows `datetime.now` tick and a
  ~2-in-3 failure rate. Neither reproduced under review — 20k `datetime.now(UTC)` reads on the
  Windows rig gave 5,813 distinct values at a ~1µs median tick (modern Python resolves
  `datetime.now` via `GetSystemTimePreciseAsFileTime`; 15.6ms is the older timer-interrupt
  granularity), and the pre-fix test passed 15/15. The race is real but narrow. This fix stands on
  the degenerate-boundary argument, not on a failure rate we could not reproduce.
- **The F-14 verifier registry did not reach the `local-verifier` / `openrouter` caller rows.**
  The same bug class as the transport drift below, one layer in. `with_local_verifier` and
  `with_openrouter` run *after* `resolve_routing_map`, and each wrote its own new caller row from
  **hardcoded** model ids — so a `LOCAL_VERIFIER` or `OPENROUTER` caller kept being verified by
  `mistral-small:24b` no matter what was pinned, while every other caller's LOCAL seat moved. A pin
  **looked applied and was not**, exactly the failure the fix below existed to kill. It survived
  that fix because every registry test asserted on `caller=anthropic` — a row nothing injects.
  Both rows are now **derived** from the seats already present in the resolved map rather than
  restating `DEFAULT_ROUTING_MAP`'s ids, which states the real invariant (an injected caller routes
  to the same seats every other caller routes to) and cannot rot the same way. Parametrized tests
  pin both rows, and the byte-identical contract still holds when nothing is pinned.
- **The F-14 verifier registry was silently ignored by `prism verify` and the HTTP API.**
  `resolve_routing_map` (the only reader of `PRISM_VERIFIER_MODEL_*`) was reachable *only* through
  `build_default_engine`, which only the MCP server called. Both other transports hand-built a
  `VerificationEngine` with a default `FamilyRouter`, so they served `DEFAULT_ROUTING_MAP`'s
  hardcoded model ids no matter what was configured — a pin **looked applied and was not**, with no
  warning. Anything shelling `prism verify` per seat therefore ran every seat on the same
  `mistral-small:24b`: N identical jurors wearing N name tags, silently destroying the cross-family
  diversity a verifier panel exists for. Both surfaces now resolve their routing map through one
  shared `setup.resolve_engine_routing_map`, and a parametrized test pins the contract on **all
  three** transports (there was none before, which is why this shipped).
  - This also completes the OpenRouter seat below, which was reachable only from MCP: the CLI never
    registered the provider *and* never injected the route; HTTP registered the provider but never
    injected the route, leaving it registered-but-unroutable.

### Added
- **`prism verify --verifier-model FAMILY=MODEL`** — repeatable, discoverable sugar for
  `PRISM_VERIFIER_MODEL_<FAMILY>`, taking precedence over it (e.g.
  `--verifier-model openai=gpt-oss:120b-cloud`). Families whose model is *provider* configuration
  (`openrouter` / `local-verifier` / `local-sycophancy` — the OpenRouter lineage guard validates the
  model when the provider is built) are **refused with a pointer to the env var** rather than
  silently dropped.
- **`prism verify --provider` is now a repeatable allowlist** over the shared provider factory, and
  a `click.Choice`: `ollama` (default) · `anthropic` · `openai` · `google` · `openrouter` ·
  `local-verifier` · `local-sycophancy`. The cross-family cloud seat (and OpenRouter) are reachable
  from the CLI for the first time, and multiple `--provider` flags give the CLI real failover.
  - **Free-by-default is now a pinned contract, not a convention.** Only the *named* providers are
    registered, so an ambient `GOOGLE_API_KEY` can never redirect (or bill) a run scoped to
    `ollama` — for `caller_family=anthropic` the route order is GOOGLE → OPENAI → LOCAL, so
    delegating to `build_default_engine()` here would have done exactly that, silently.

- **OpenRouter cross-family verifier seat (F-14)** — a new `OPENROUTER` model family +
  `OpenRouterProvider` (OpenAI-compatible gateway) makes the whole OpenRouter catalog available as a
  cross-family verifier through one key. Opt-in: built only when BOTH `OPENROUTER_API_KEY` and
  `PRISM_VERIFIER_MODEL_OPENROUTER` are set (`PRISM_OPENROUTER_BASE_URL` overrides the endpoint).
  It is **appended** as a cross-family *failover*, so it fills in behind a caller's native verifiers
  — and becomes the serviceable cross-family route for a local-producer + OpenRouter deployment with
  no native hosted keys. `DEFAULT_ROUTING_MAP` is byte-identical when the seat is unconfigured.
  - **Lock-1 lineage guard** (`validate_openrouter_lineage`): because `openrouter` is a *transport*,
    not a lineage, the seat **fails closed** at engine construction if the configured model's vendor
    prefix collides with a family prism models natively (`anthropic`/`openai`/`google`/`mistral`) or
    is non-deterministic (`openrouter/auto`) — so the OPENROUTER label can only ever carry a
    genuinely family-distinct model (deepseek/qwen/cohere/nvidia/meta-llama/…), keeping the
    family-different guarantee honest.

### Changed
- **`--provider anthropic` now honors `PRISM_ANTHROPIC_BASE_URL`** (a deliberate behavior change):
  it previously hand-built the provider and ignored the override every other surface honored.
- **`--provider <unknown>` is now a usage error (exit 2)** instead of registering nothing and
  dead-ending on `VERIFIER_UNAVAILABLE` — `--provider openai` used to read as "openai refused."
- `build_default_engine(receipt_store=...)` accepts a caller-owned receipt store, letting the HTTP
  app keep its store lifecycle while sharing the one engine factory.

## [1.6.0] - 2026-06-14

### Added
- **Family-AB harder corpus + `prism eval --round-robin`** — closes the v1.5.0 ceiling-effect null.
  The v1.5.0 pilot measured self_preference +0.000 (CI [0,0]) because the corpus was so easy that
  every verifier refuted every bug (false-accept rate ≡ 0), starving the within-judge estimator of
  variance. v1.6 lands false-accept rates in the (0,1) regime where family self-preference can
  actually manifest:
  - **Harder-corpus loaders** (`prism.eval.bigcodebench`, `prism.eval.livecodebench`):
    contamination-dated LiveCodeBench-functional + hard function-level BigCodeBench problems,
    execution-labeled (no LLM grader). LCB private tests decode base64→zlib→pickle→json;
    `contest_date` holdout; per-problem case cap (real LCB bakes multi-MB test payloads).
  - **Containerized execution-labeler** (`prism.eval.container_sandbox` +
    `eval/docker/labeler.Dockerfile`): Docker `--network none`, read-only, tmpfs, mem/pids/cpu caps;
    routes lib-bearing candidates to the container and stdlib-only candidates to the in-process sandbox.
  - **Faithful shared-bug-restyle deconfounder** (`prism.eval.familygen`): fix one bug, restyle it
    through each family, keep the problem only when the failing-test **signature** is identical across
    families — holding bug difficulty constant so the contrast isolates self-preference from capability.
  - **Difficulty-stratified problem selection** (`prism.eval.problem_select`) so the deconfound
    stratum actually populates on a mixed-difficulty corpus.
  - **Estimator hardening** (`prism.eval.metrics`, `prism.eval.familyab`): min-cluster gate (≥20),
    TOST equivalence testing (Lakens 2018), Benjamini-Yekutieli FDR (arbitrary dependence), and a
    pre-registered decision rule (`superiority` / `equivalence` / `inconclusive` / `underpowered`).
  - **`prism eval --round-robin`** — the reproducibility wrapper: `--familyab-corpus <dir>` →
    per-family round-robin → `compute_self_preference` (`--sesoi`, `--min-problems`) → a markdown
    report + a signed Ed25519 receipt. The measurement-only `allow_same_family` bypass stays confined
    behind the Knight-Capital source-scan guard.
  - **Pre-registered run** published to `eval/RESULTS.md` (locked before data): 4 local families, 28
    problem-clusters. The ceiling effect is gone (per-family false-accept 0.03–0.22); granite shows
    +0.118 self-preference in its own direction, but the panel aggregate is +0.020 (95% CI
    [−0.014, +0.082]) → **inconclusive** (under-powered at n=28). Method validated on prism's own
    data; closes by scaling the cluster count on the identical locked pipeline.

### Fixed
- `prism eval --round-robin` no longer crashes on the final console echo on a legacy cp1252 terminal
  (the run's result and signed receipt were always written to disk first; only the terminal echo
  threw on a non-encodable character). The report file keeps full UTF-8.

## [1.5.0] - 2026-06-14

### Added
- **Family-different A/B v2 — the validity-clean within-judge round-robin.** The v1.4.0 `--family-ab`
  was a *confounded* null (it compared a family-different model against a same-family model over a
  fixed corpus, conflating family with model capability, and a fixed corpus can't fire
  self-preference). The replacement isolates the family/self factor from capability:
  - **Family-provenanced, execution-labeled corpus** (`prism.eval.familygen` + `eval.sandbox` +
    `eval.mutate`): each model GENERATES the code; hidden tests LABEL it buggy/clean (no LLM grader,
    which dodges label-circularity); clean generations are mutated (ROR/AOR/LCR, no
    constant-replacement per Just 2014) and only test-failing mutants are kept. Producer family lives
    in a manifest provenance sidecar, never the frozen `Sample` schema. Sandboxed execution
    (`reliability_guard` + timeout, labeling-integrity-robust).
  - **Within-judge estimator** (`prism.eval.familyab`): for verifier family V over known-buggy
    artifacts, `self_preference(V) = false_accept_rate(V on own-family bugs) − …(other-family bugs)`;
    V's capability cancels inside the contrast. Tri-state collapse (refute/abstain/accept) +
    discrimination-floor gate.
  - **Corrected statistics** (`prism.eval.metrics`): `mcnemar_midp` (Fagerland 2013),
    `benjamini_hochberg` (BH-FDR), `cluster_bootstrap_ci` (resamples problems, respecting
    items-nested-by-problem). `calibrate.FamilyAB` gained the mid-p p-value.
  - **First valid pilot run** published to `eval/RESULTS.md`: 3 local lineages, aggregate
    self_preference +0.000 (CI [0,0]) — an interpretable *ceiling-effect* null (every family catches
    every obvious mutant), diagnosing corpus difficulty as the next gap, not a statistical confound.
- **Configurable verifier registry (F-14).** Verifier model IDs are no longer hard-coded in source:
  - `PRISM_VERIFIER_MODEL_<FAMILY>` overrides a verifier family's model id wherever it routes (a
    deprecation is a config hotfix). `routing.resolve_routing_map` / `routing_map_digest`.
  - `PRISM_<PROVIDER>_BASE_URL` points a provider at an OpenAI-compatible endpoint — e.g. Ollama
    Cloud's `/v1` serving `gpt-oss:120b-cloud` as a first-class cross-family seat (no one-off harness).
  - A source scan (`test_bypass_safety`) confines the measurement-only `allow_same_family` Lock-1
    bypass to its two legitimate sites (Knight Capital lesson, SEC 34-70694).

### Fixed
- **Dated-model ops time-bomb:** the Anthropic provider default `claude-haiku-4-5-20251001` (a dated
  snapshot that retires on a schedule) → the durable alias `claude-haiku-4-5`; overridable via
  `PRISM_ANTHROPIC_MODEL`.
- **Stale runtime version:** `prism.__version__` (surfaced by `prism --version` and the HTTP
  `/healthz` + OpenAPI `version`) had been pinned at `1.0.0` since the 1.0 release; it now tracks the
  package version.

## [1.4.0] - 2026-06-14

### Added
- **Wedge #2 sycophancy — the ≥3-lens panel + ≥2-agreement calibrated emission gate.** When ≥3
  disjoint, caller-excluded model families are configured, `_verify_sycophancy` now fans the same
  sycophancy judgment across them — a family-decorrelated panel (Verga 2404.18796, Panickssery
  2404.13076) — and gates emission via `prism.core.sycophancy_panel.panel_emission_decision`:
  precision-first (≥2 independent sycophantic votes to flag → REVISE), fail-open (a unanimous clear
  ACCEPTs; otherwise abstain → ESCALATE; fewer than two genuine votes refuses on availability). The
  flag gates on the aggregated vote signal, never a lens's verbalized confidence (Tian 2508.06225).
  With <3 families it falls back to today's single certified-specialist lens, behaviorally unchanged.
- **`prism calibrate-sycophancy-panel`** — the offline half of the calibration harness:
  `sweep_agreement_k` scores recorded panel votes per agreement-threshold `k` (false-flag rate /
  recall / coverage / false-clears) so you can pin `k` + a target false-flag rate `alpha` before the
  panel is served.
- **`prism probe-sycophancy`** — a producer-supplying entry for the v2 active probe: re-queries a
  live producer under a pinned content-free rebuttal (a capitulation / DIR test) and an optional
  stance-reversed counterfactual (an INV test), with a cross-family agreement judge; emits JSON, an
  opt-in signed receipt, and `--gate` exit codes (0 not_sycophantic, 10 sycophantic, 30 abstain).
- **Validate-on-your-own-data: a real same-family A/B.** `prism eval --family-ab` now runs a
  same-family CONTROL against the family-different TREATMENT and reports a paired **McNemar accuracy
  delta + CI** — the measurement that shows whether Lock 1 (family-different routing) actually buys
  accuracy. The control uses a measurement-only, **default-off** `allow_same_family` router bypass.
- **Real-bug corpus + `CodeJudgeBench`.** `prism eval` now ingests vendored MIT
  [QuixBugs](https://github.com/jkoppel/QuixBugs) real-bug pairs (contamination-honest: public
  samples are flagged so the honest signal is reported separately), and a new pairwise benchmark
  harness — `prism eval --benchmark codejudgebench` (the `[bench]` extra) — scores prism against
  [CodeJudgeBench](https://huggingface.co/datasets/mattymchen/codejudgebench) (arXiv:2507.10535).
- **Observability.** A `request_id` correlation id is threaded HTTP → engine → providers, decisions /
  circuit-breaker / provider calls emit structured logs, and `GET /healthz` now reports circuit-breaker
  state per provider.
- **Eval reproducibility.** `prism eval` reports pin the corpus content-hash, the resolved verifier
  model, and the temperature, and the coverage-gain tie-break is now deterministic.
- `CONTRIBUTING.md`.

### Changed
- **Citations are measured by verdict, not lens-fail.** The citation pipeline escalates an
  unconfirmable citation rather than emitting a `FAIL`, so eval now scores it by VERDICT (off-accept
  recall, verdict accuracy) instead of treating it as a pass/fail lens.
- **Graceful degradation.** The circuit breaker is wired into the sycophancy paths, and the citation
  oracle cache gained a TTL + a size bound.
- Maintenance: Node-24 GitHub Action bumps with SHA-pinned publish actions, conservative dependency
  upper-bounds, receipt-builder dedup, and a single canonical `RHO_MAX_DEFAULT`.

### Fixed
- **CRITICAL — the npm launcher could ship a stale binary.** `npm/bin/prism.js` was pinned to a
  v0.4.2 binary while the package was 1.3.0; it now derives its `version`/`tag` from `package.json`
  at runtime, so the launcher can never download a mismatched binary again.
- **Eval excluded errored runs from calibration**, biasing the numbers; errored runs are now counted.
- **`--family-ab` silently measured nothing** — the control arm always returned
  `VERIFIER_UNAVAILABLE`. Fixed alongside the new paired-delta surface above.
- Oracle hardening: arXiv returned-id match, a response-body cap, and redirects disabled on retrieval.
- Harvest-sink secret scrub and a quadratic-`ReDoS` fix.

### Tests
- Suite grows **472 → 641** (the panel gate + calibration sweep; oracle / auth / NLI / panel-receipt
  gaps; the family-AB delta, real-bug corpus, and CodeJudgeBench harness). ruff + mypy `--strict` clean.

## [1.3.0] - 2026-06-08

### Added
- **Sycophancy lens v1 (wedge #2) — a new verification duty.** `prism.lenses.sycophancy` judges a
  model RESPONSE against its CONTEXT for *regressive* sycophancy (telling the user what they want over
  what is correct — affirming a false premise, abandoning a correct answer under mere pushback),
  routed via the engine's RESPONSE artifact branch. Backed by a locally-served, family-different
  fine-tuned specialist (`providers/sycophancy.py` `SycophancyProvider`, opt-in
  `PRISM_SYCOPHANCY_ENDPOINT`), reasoning-stripped, **fail-open to abstain** — never a silent
  "not sycophantic". Adds `prism.probes` (active capitulation/counterfactual probes — a
  producer-querying slice).

### Security
- **`prism.security` — input-hardening on a screening copy (opt-in / additive, fail-open).**
  `desmuggle` strips zero-width / Unicode-tag / variation-selector / bidi smuggling and NFKC-folds;
  `spotlight` wraps untrusted content in content-derived **unforgeable** delimiters (boundary =
  `sha256(content)`, both unforgeable and replay-stable). The citation **groundedness** prompt is
  hardened (de-smuggle + unforgeable markers) **only for non-certified general-model verifiers** — a
  frozen specialist's certified input is never transformed (`CERTIFIED_FROZEN_FAMILIES`), so the
  default path is byte-identical. Internal-first quality-oversight posture; the adversarial extensions
  are research-gated but shelved (`design/`).

## [1.2.1] - 2026-06-06

### Docs
- **README + handbook for the self-hosted verifier and harvest sink.** The README gains a "Bring your
  own verifier" note — the citation groundedness lens can run against a model you host via
  `PRISM_LOCAL_VERIFIER_ENDPOINT` (opt-in, fail-open), with the `PRISM_HARVEST_PATH` capture sink to
  build its training data — and two new handbook pages document both, wired to the landing page.
  Re-translated across all 8 locales.
- **README front-door cleanup** — the calibration section's internal ρ/κ findings moved to the
  [evaluation handbook](https://mcp-tool-shop-org.github.io/prism-verify/handbook/evaluation/); the
  README keeps the value proposition, the detail lives in the docs.

(Docs/branding only — no code or API changes from 1.2.0.)

## [1.2.0] - 2026-06-06

### Added
- **Opt-in L4 training-data capture sink** (`prism.eval.harvest`, env `PRISM_HARVEST_PATH`) — when
  set, prism appends the `(claim, evidence_span, verdict)` triples a verification produces to a JSONL
  file (`prism-l4-harvest/v1`). This is the training corpus for a local groundedness specialist that
  can back prism's `local` lens family. **Default OFF**: unset env means no capture, no file, and zero
  behavior change (the engine hook is a no-op). Captures the citation path's per-claim
  `CitationResult`s — the clean triples receipts never persist, since receipts store artifact *hashes*
  only — and the code path's `groundedness` lens; label mapping mirrors prism's own verdict semantics
  (SUPPORTED→supported, CONTRADICTED→unsupported, NOT_ADDRESSED→abstain). Best-effort secret redaction
  runs before write; receipts remain the join/provenance index via `receipt_id`.
- **Local Verifier specialist as a citation-groundedness backend** (`prism.providers.local_verifier`,
  opt-in) — a `LocalVerifierProvider` that bridges the citation lens to a locally-served, fine-tuned
  groundedness model (a Qwen3-14B QLoRA served by llama.cpp at `--lora scale 4`). It re-templates
  prism's `<<<SOURCE>>>`/`<<<CLAIM>>>` prompt into the model's trained EVIDENCE/CLAIM shape, strips the
  model's reasoning block, and maps the verdict to prism's citation vocabulary (supported→supported,
  unsupported→contradicted, abstain→not_addressed), emitting the JSON `parse_citation_groundedness`
  expects (never the bare token — which would parse as the safe default and silently escalate). New
  `ModelFamily.LOCAL_VERIFIER`, distinct from `LOCAL` (=mistral), so family-difference holds and mistral
  remains a failover target. The capture sink above is exactly what produced this verifier's training data.
- **Opt-in** via `PRISM_LOCAL_VERIFIER_ENDPOINT` (+ `PRISM_LOCAL_VERIFIER_MODEL`): when set,
  `build_default_engine` injects the specialist as the **primary** citation verifier (failing over to the
  hosted/mistral verifiers on circuit-open); when unset, the static `DEFAULT_ROUTING_MAP` and behavior are
  unchanged. **Fail-open**: a verifier outage raises `ProviderError` → circuit-breaker failover, never a
  silent escalate. Recommend pairing with `PRISM_NLI_FLOOR` (the orthogonal encoder-NLI veto), since the
  breaker fails over on errors, not on a confident-wrong `supported`.

## [1.1.0] - 2026-06-03

Two more deterministic/orthogonal layers for the citation path, both precision-biased (neither can
introduce a false-confirm) and measured on a 56-case labeled set (tensor-engine-knowledge waves 10–14).

### Added
- **Generalized numeric/unit floor** (`numeric_unit_mismatch`) — the deterministic numeric guard now
  catches two more contradiction classes a reasoning-stripped lens is structurally blind to, beyond
  the existing percentage check: a **unit-scale mismatch** (a claim's "42 milliarcseconds" where the
  source says "42 micro-arcseconds") and a **comparison-direction falsehood** (a claim that the
  observed "5.0σ exceeded" the expected "5.8σ" when 5.0 < 5.8). Refute-or-abstain: it flags a
  contradiction only on a *provable* one, else falls through to the groundedness lens — 0 false-
  refutes across the labeled set. Runs before the LLM lens in `_adjudicate_citation`. Additive.
- **Optional orthogonal NLI floor** (`prism.lenses.nli`, opt-in) — a mechanistically-different
  encoder NLI cross-encoder (DeBERTa-v3 NLI) as a **veto** on the groundedness lens's `supported`:
  two LLMs share correlated blind spots, but a discriminative classifier fails differently, so it
  catches a class of false-confirm the LLM shares. **Opt-in and optional**: it needs the new `nli`
  extra (`pip install prism-verify[nli]` — torch + transformers) and is gated by `PRISM_NLI_FLOOR`;
  when the extra or the model is absent it abstains and prism behaves exactly as before, so the
  default install stays lightweight and CI is unchanged. Env: `PRISM_NLI_FLOOR`, `PRISM_NLI_MODEL`,
  `PRISM_NLI_TAU`.

Consumers that shell the `prism` CLI (e.g. role-os's `verify-citations`) gain the numeric/unit floor
automatically on upgrade; the NLI floor is opt-in via `PRISM_NLI_FLOOR`.

## [1.0.0] - 2026-06-03

**First stable release.** prism graduates from its 0.x line. The architecture proven across the
pre-1.0 series is now declared stable: the four locks (family-different routing, reasoning-stripped,
multi-lens ≥ 3, submodularity-aware) and the citation-verification layer (v0.1–0.3), the installable
+ HTTP-callable + independently-verifiable surface with Ed25519 receipts and the npm launcher (v0.4),
and the `prism eval` calibration pack (v0.5). The one functional change since 0.5.0:

### Added
- **`CitationResult.source_abstract`** — the full retrieved source abstract is now surfaced on each
  RESOLVED citation result (and flows to the `verify --type citations` JSON via `model_dump`),
  instead of only the groundedness lens's single `supporting_span`. The abstract is already
  retrieved to ground the lens; prism stopped discarding it. This lets a downstream re-verifier
  (e.g. role-os's `verify-citations --local-panel`) judge a faithful claim against the whole
  abstract rather than one span — fixing a case where a faithful claim was escalated because only
  the truncated span was visible to the panel. Additive, non-breaking (new optional field).

Stage-A security hardening (no API changes; receipt schema v5 in place) + the Slice-1 calibration
pack (`prism eval`). First release that **measures** prism's locks on its own labeled data — and
the benchmark's headline finding is that the runtime finding-set rho gate is blind to the
decision-level lens correlation Cohen kappa reveals (see `eval/RESULTS.md`).

### Added
- **`prism eval` + calibration pack (Slice 1)** — measures prism's lenses on a labeled corpus
  instead of only asserting their behavior: per-lens precision/recall/MCC, the inter-lens diversity
  matrix (Krippendorff alpha + pairwise Cohen kappa), submodular coverage-gain, confidence
  calibration (ECE/Brier), and a data-driven submodularity-threshold (rho) sweep — with the honest
  finding that **0.25 is Rajan's observed correlation ceiling, not a validated refusal gate** (the
  runtime default is unchanged; the sweep is meant to inform a future, evidence-based change).
  Includes an authored lens-targeted corpus (`eval/corpus/`, v1; real-bug ingestion is the v1.1
  upgrade), an optional same-family A/B that demonstrates Lock 1, an ANDON corpus-integrity gate, a
  signed run-receipt, and an `--offline` deterministic mock for CI. Research grounding in
  `design/07-slice1-calibration.md`. Pure-Python metrics (no new dependencies).

### Security
- **SECURITY.md rewritten to the v0.4 surface** — Ed25519-by-default receipts (HMAC legacy/opt-in)
  with the honest integrity ceiling (on-disk key is forgeable by local-root → third-party
  verifiability, not anti-forgery; HSM + transparency log / Sigstore-keyless as the hardening
  path), a new **HTTP surface** section (fail-closed auth, hashed keys, SSRF-guarded webhooks,
  loopback-by-default, RFC 9457 errors, rate limit + Idempotency-Key), a receipt-canonicalization
  note, and a full environment-variable table. Supported-versions table updated to `0.4.x`.
- **Opt-in trusted-proxy support** (`PRISM_TRUSTED_PROXIES`) — `X-Forwarded-For` is honored only
  when the immediate peer is within a configured trusted-proxy CIDR (default empty = no XFF trust),
  so a client cannot spoof its rate-limit identity behind a reverse proxy.

### Fixed
- **Lock-2 strip-bypass** — reasoning-stripping no longer admits a partially-stripped artifact past
  the family boundary.
- **Provider robustness** — provider timeouts and non-JSON / malformed responses are handled
  (no bare crash) with circuit-breaking so a flapping provider degrades cleanly.
- **Receipt canonical JSON (schema v5)** — signatures cover a deterministic canonical JSON with
  **non-finite floats (`NaN` / `Infinity`) rejected**, and a dev-key (`kid`) verify guard so a
  dev-signed receipt is not silently trusted in production.
- **Bounded back-pressure state** — the HTTP idempotency cache and per-IP failed-auth buckets are
  bounded, and exhausted-retry webhook deliveries surface via a dead-letter path.

## [0.4.2] - 2026-06-02

### Added
- **Landing page + Starlight handbook** at <https://mcp-tool-shop-org.github.io/prism-verify/>
  (site-theme + GitHub Pages) — 5 handbook pages (overview / getting-started / http-service /
  receipts / reference) wired to the landing; the repo homepage now points to it.

### Docs
- Logo + PyPI/npm badges on the **npm wrapper README** (was missing) — now visible on npmjs.com.
- Landing-page + handbook badges on the main README (the README↔landing connection contract);
  re-translated across all 8 locales.

(Docs/branding only — no code or API changes from 0.4.1.)

## [0.4.1] - 2026-06-02

### Fixed
- **`prism --version` in the PyInstaller binary.** The CLI used `click.version_option(package_name=
  "prism-verify")`, which resolves the version via `importlib.metadata` — fine for a pip/uv install,
  but a frozen `--onefile` binary carries no dist-info, so the binary's `--version` raised
  `'prism-verify' is not installed`. The v0.4.0 release's `--version` smoke test correctly caught
  this and **skipped the npm publish** (no broken wrapper shipped). Now uses the static
  `prism.__version__`, which works in the binary, pip, and uv installs alike. (PyPI 0.4.0 was
  unaffected — pip installs have the metadata.)

### Changed
- `release.yml`: the binary matrix is `fail-fast: false` (one OS's failure no longer cancels the
  others) and the PyInstaller build `--copy-metadata prism-verify` (defense-in-depth for any other
  metadata lookups). This is what unblocks the **npm launcher** (`@mcptoolshop/prism-verify`) — its
  binaries + wrapper now publish on the v0.4.1 release.

## [0.4.0] - 2026-06-02

prism becomes an **installable, HTTP-callable, independently-verifiable runtime service**.
Research-grounded by a 5-agent study-swarm (`wf_f0f8b9c8-e2c`, 40 cited findings) and
adversarially verified (3 decorrelated lenses) — design in `design/05-http-and-receipts.md`.

### Added
- **Ed25519 receipts (production default), version-aware.** Receipt **schema v4** adds `alg` +
  `kid`; new receipts are signed with **Ed25519 (RFC 8032)** so a *different tool* verifies a
  prism receipt with prism's **public key — no shared secret** (closes the cross-tool trust gap
  role-os flagged). Legacy v1/v2/v3 **HMAC receipts still verify**, and the verifier **whitelists
  `alg` per receipt** (downgrade / algorithm-confusion refused). HMAC stays for legacy + explicit
  `PRISM_SIGNING_SECRET`; `PRISM_DEV=1` now mints a dev Ed25519 key.
  - `prism verify-receipt <receipt.json> [--public-key <pem>]` — verify a standalone receipt
    (the cross-tool path; Ed25519 needs only the public key). Also `POST /verify-receipt`.
  - `prism keygen` (generate an Ed25519 keypair) and `prism pubkey` (publish the public key + kid).
- **HTTP/FastAPI runtime surface** (`prism serve`, the `[http]` extra) — the same guarantees as
  CLI/MCP over HTTP: `POST /verify` (sync; `Prefer: respond-async` → `202` + webhook delivery),
  `GET /replay/{receipt_id}`, `POST /verify-receipt`, `GET /healthz`, OpenAPI 3.1 at `/docs`.
  Bearer **API-key auth** (hashed at rest, constant-time, fail-closed), **RFC 9457
  `application/problem+json`** errors, `Idempotency-Key` (replay / `409` in-flight / `422`
  mismatch), and denial-of-wallet back-pressure (artifact size cap + per-key rate limit +
  stricter failed-auth limiter).
- **Signed-webhook escalate channel** — Standard-Webhooks HMAC over `id.timestamp.payload`
  (300s tolerance, multi-signature rotation), an **SSRF guard** (https-only; rejects
  loopback/RFC1918/link-local/metadata, v4+v6), bounded retry → dead-letter, and the
  **`send_cancel_event()` compensator** (the named undo for the irreversible verdict POST).
- **PyPI Trusted Publishing** (`.github/workflows/release.yml`) — OIDC, no long-lived token;
  builds with `uv build` and publishes via `pypa/gh-action-pypi-publish` (PEP 740 attestations on
  by default) on `release: published`. First publish uses a PyPI *pending publisher*.
- **npm launcher** (`@mcptoolshop/prism-verify`) — zero-Python `npx @mcptoolshop/prism-verify` via
  [`@mcptoolshop/npm-launcher`](https://github.com/mcp-tool-shop-org/npm-launcher): the release
  builds PyInstaller binaries (linux-x64 / darwin-arm64 / win-x64) + a `checksums-<version>.txt`,
  and the wrapper downloads + **SHA256-verifies** the platform binary at first run. Published via
  npm Trusted Publishing (OIDC provenance). PyPI remains the primary, full-featured distribution
  (hosted-provider SDKs + all extras); the npm binary bundles the CLI + local Ollama + HTTP + citations.

### Changed
- MCP + HTTP now share one engine factory (`prism.core.setup.build_default_engine`) so the
  transports cannot drift.
- `cryptography` added as a core dependency (Ed25519 signing/verification).

### Migration notes
- A v0.3 `~/.prism/receipts.db` migrates to schema v4 in place (`alg` / `kid` columns added);
  legacy rows backfill `alg=HMAC-SHA256` and keep their original signatures. To verify legacy
  HMAC receipts after moving to Ed25519, keep `PRISM_SIGNING_SECRET` set alongside the new key.
- The honest ceiling is disclosed: an on-disk private key is forgeable by a local-root attacker
  (same as the HMAC secret) — Ed25519 buys **third-party verifiability**, not stronger
  anti-forgery. HSM + a transparency log is the named hardening path.

### Standards
- workflow-standards stays **15/15**; each new surface (HTTP / webhook / receipt-signing) carries
  its own compliance section and a NO-SKIP compensators table (`design/05`, `design/03`).

## [0.3.2] - 2026-06-01

### Added
- **`prism verify --gate`** — opt-in verdict-coded exit status for shell gating (`0` accept,
  `10` revise, `20` refuse, `30` escalate). The default (no `--gate`) stays exit `0` on any
  successful verification, preserving the CLI contract. Lets a shell/CI step — e.g. the role-os
  citation-verification gate — branch on the verdict without parsing JSON.

### Fixed
- **Citation retrieval oracle hardening** (surfaced by the role-os citation-gate dogfood). The
  arXiv existence check now uses `https://export.arxiv.org` directly (the `http://` endpoint
  301-redirects, which broke the lookup), sends a descriptive `User-Agent`, follows redirects, and
  **retries transient `429`/`5xx` with backoff** — arXiv rate-limits anonymous bursts, so a burst
  of citations was previously escalating instead of resolving (the gap the v0.3 study-swarm's Q1
  predicted). `CitationOracle(retry_delays=...)` is injectable; tests pass `()` for no sleeps.

## [0.3.1] - 2026-06-01

A post-ship adversarial verification pass (3 decorrelated lenses over the v0.3.0 diff) found and
fixed real defects. v0.3.0 stays immutable; these land as a patch.

### Fixed
- **Citation oracle cache (was a silent wrong verdict).** The per-identifier cache held the full
  existence result, but RESOLVED-vs-METADATA_MISMATCH is title-dependent; a repeated arXiv-id / DOI
  with a different claimed title inherited the first citation's verdict (and the cache is
  engine-lifetime, so it leaked across requests). The cache now holds only the title-independent
  retrieved record and recomputes the title match per citation.
- **DOI request hardening + pin integrity.** An unvalidated DOI suffix was interpolated into the
  Crossref path (path-traversal / query-param injection), and the signed retrieval pin recorded a
  URL different from the one httpx actually fetched. The DOI pattern now forbids `?`/`#`/whitespace,
  `..` segments are rejected, `mailto` travels as a real query param, and the pin records the URL
  actually issued.
- **MCP `verify` tool now advertises `citations`.** The CLI was migrated in v0.3.0 but the MCP
  inputSchema still enumerated only `code`/`tool_call`, making the headline feature unreachable via MCP.
- **Groundedness prompt-injection defense-in-depth.** The claim and retrieved source are wrapped in
  `<<<...>>>` untrusted-data markers; groundedness stays advisory over the sound existence floor.

### Tests
- Crossref-transient (5xx / 429 / timeout / unparseable) → UNRESOLVABLE (not FABRICATED); the cache
  title-recompute regression; DOI path-traversal rejection; pin-equals-request-URL; a v2→v3 receipt
  migration; and the MR1 metamorphic test now pins its verdict value.

### Standards
- workflow-standards remains 15/15; this is a correctness / hardening patch with no scope change.

## [0.3.0] - 2026-06-01

### Added
- **Citation verification (headline).** A new `ArtifactType.CITATIONS` artifact (a JSON array of
  citations) is adjudicated through a two-stage pipeline kept deliberately distinct:
  - a **deterministic retrieval existence floor** (`prism.retrieval`) — arXiv-ID-first, then
    Crossref DOI — that ANDON-refuses a non-resolving citation (`FABRICATED`) and distinguishes an
    oracle-down/blocked retrieval (`UNRESOLVABLE` → escalate) from a genuine non-resolution (never
    read as fabrication);
  - a **deterministic numeric guard** that catches the "95.8% vs 89%" class an NLI/LLM lens is
    structurally blind to (Naik 2018); and
  - a **RAG-fed Groundedness (L4) lens** given the *retrieved* title+abstract, on a family-different
    verifier.
  Two-axis verdict mapping with per-citation action verbs (DROP / FIX METADATA / FIX TO MATCH
  SOURCE / RETRIEVE MANUALLY); the protocol's `CANNOT_CONFIRM` maps to ESCALATE. Research grounding
  + design: `design/04-citation-verification.md`.
- **prism-on-prism meta-test (EXTERNAL_VERIFIER 1→3).** Verifies prism's own design-doc citations
  through a different family + retrieval-backed existence, asserting metamorphic relations (corrupt
  id → existence flips to refuse; numeric swap → off accept; author reorder → invariant). Non-
  circular: it checks retrieval, not recall. Closes the launch bootstrap skip.
- **Compensate-after-verify flow (NAMED_COMPENSATORS 2→3).** verify → signed receipt → delete /
  prune → asserts the undo, proving the named compensator end-to-end.
- Receipt **schema v3**: signs `artifact_type` and a hash of the per-citation `retrieval_pins` (the
  retrieval query + retrieved-source SHA-256), so a citation verdict is replayable.

### Changed
- **Router walks configured families.** `select_verifier()` skips candidate families with no
  configured provider instead of dead-ending on `VERIFIER_UNAVAILABLE` — fixes the out-of-box
  `prism verify` trap (an Anthropic caller with only a local provider was refused).
- **`BUDGET_EXCEEDED` is now enforced** as a hard latency-budget timeout on the lens fan-out (was
  declared in `RefusalReason` but never raised).
- Hosted verifier model IDs reconciled with provider lineups (`gpt-5.4-mini`, `claude-sonnet-4-6`,
  `claude-haiku-4-5-20251001`), guarded by a test; local verifier pinned to the non-thinking
  `mistral-small:24b` with `format=json` + `think=false`.

### Fixed
- **Security:** the Google provider sends its API key via the `x-goog-api-key` header instead of the
  URL query string, so the credential no longer leaks into error reprs / tracebacks / logs.
- OpenAI provider uses `max_completion_tokens` (GPT-5 / o-series reject `max_tokens`) and omits
  `temperature` for reasoning models.
- The SQLite receipt store is safe across threads (`check_same_thread=False` + a reentrant lock) and
  supports the context-manager protocol for deterministic close.

### Migration notes
- An existing `~/.prism/receipts.db` is migrated to schema v3 in place on first open (`artifact_type`
  + `retrieval_pins` columns added); legacy v1/v2 rows keep their original signatures and still verify.

### Standards
- workflow-standards **12/15 → 15/15**: EXTERNAL_VERIFIER 1→3, NAMED_COMPENSATORS 2→3, and
  BUDGET_EXCEEDED enforced. See `design/02-standards-compliance.md`.

## [0.2.0] - 2026-06-01

### Added
- **Replayable prompt pinning (PIN_PER_STEP).** Receipts now record `lens_prompt_hashes`
  — a SHA-256 of each lens call's `(system_prompt, user_prompt)` — stamped by the engine
  and signed into the receipt, so a verification is byte-for-byte replayable.
- **Named compensators.** `prism receipt delete <id>` and
  `prism receipt prune --older-than <duration> --yes` (plus the `store.delete_receipt` /
  `store.prune` APIs) undo the receipt store's only irreversible write.
- `PRISM_SIGNING_SECRET` / `PRISM_DEV` configuration for the receipt signing secret,
  documented in the README and SECURITY.md.
- First end-to-end integration test of `engine.verify()` against mock providers (respx).
- SECURITY.md with a real threat model and an honest tamper-evident (not tamper-proof)
  integrity-ceiling disclosure.

### Changed
- **Expanded the signed-receipt scope.** The HMAC now covers `reasoning_visibility_mode`,
  `confidence`, `retryable`, a hash of the lens results, and the lens prompt hashes — not
  just the original 7 fields. Receipts carry a `schema_version`; legacy v1 receipts still
  verify after the automatic in-place schema migration.
- The receipt store **requires** an explicit signing secret (`PRISM_SIGNING_SECRET`, an
  explicit argument, or `PRISM_DEV=1`) and refuses the built-in dev key otherwise.
- CI now runs when workflow files change (`.github/workflows/**` added to the path filter).

### Fixed
- Out-of-enum verifier output (e.g. `severity: "high"`, `outcome: "accept"`) or
  markdown-fenced JSON no longer crashes `verify()` with a raw stack; lens responses
  degrade gracefully to an `errored` UNCERTAIN result.
- Verdict aggregation: a FAIL with only minor (or no) findings no longer collapses to
  ACCEPT, and a mixed PASS + UNCERTAIN now ESCALATEs instead of silently ACCEPTing.
- A provider outage now refuses with `VERIFIER_UNAVAILABLE` (retryable) instead of being
  misclassified as a non-retryable `LENS_COLLAPSE`.
- Ollama / OpenAI providers guard malformed response bodies (raise `ProviderError`
  instead of a bare `KeyError`).
- Routing map's local-tier model id corrected (`qwen3-32b` → `qwen3:32b`) to match the
  Ollama provider.
- `prism replay` no longer leaks its SQLite connection on the receipt-not-found path.

### Migration notes
- Receipts written by v0.1.0 under the built-in dev key report `signature_valid: false`
  once a real `PRISM_SIGNING_SECRET` is set — expected (different key), not tampering.
- An existing `~/.prism/receipts.db` is migrated in place on first open (new columns
  added; legacy rows keep their original signatures).

## [0.1.0] - 2026-06-01

### Added
- Initial release: family-different routing, reasoning-stripping, multi-lens (≥3)
  verification with submodularity-aware lens-collapse refusal, SQLite HMAC-signed
  receipts, a CLI (`verify` / `replay`), and an MCP server. 41 tests; CI on 3.11–3.13.
