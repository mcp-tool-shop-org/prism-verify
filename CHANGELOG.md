# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
