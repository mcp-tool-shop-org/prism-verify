# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
