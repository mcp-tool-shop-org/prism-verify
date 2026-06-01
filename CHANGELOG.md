# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
