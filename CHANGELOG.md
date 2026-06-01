# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
