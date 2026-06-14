# Ship Gate — prism-verify v1.3.0

> Reconciled 2026-06-13 for the v1.3.0 line (originally worked 2026-06-02 for v0.4.0). Tags in
> play: `[all]` `[pypi]` `[npm]` `[cli]` `[mcp]`.
> (Also ships an HTTP service — covered under `[all]`/`[cli]` — and the `@mcptoolshop/prism-verify`
> npm launcher, covered under `[npm]`.)

**Tags:** `[all]` every repo · `[npm]` `[pypi]` `[vsix]` `[desktop]` `[container]` published artifacts · `[mcp]` MCP servers · `[cli]` CLI tools

---

## A. Security Baseline

- [x] `[all]` SECURITY.md exists (report email, supported versions, response timeline) (2026-06-02)
- [x] `[all]` README includes threat model paragraph (data touched, data NOT touched, permissions) (2026-06-02)
- [x] `[all]` No secrets, tokens, or credentials in source or diagnostics output (2026-06-02)
- [x] `[all]` No telemetry by default — stated explicitly in README + SECURITY (2026-06-02)

### Default safety posture

- [x] `[cli|mcp|desktop]` Dangerous actions require an explicit flag — `receipt prune` requires `--yes` (2026-06-02)
- [x] `[cli|mcp|desktop]` File operations constrained to known directories — receipts in `~/.prism` (2026-06-02)
- [ ] `[mcp]` Network egress off by default — **SKIP:** prism's core function IS calling alt-family verifier providers (Anthropic/OpenAI/Google/Ollama) + the read-only citation retrieval oracle (arXiv/Crossref). Egress is the product. The HTTP server binds loopback by default; caller-supplied webhook URLs are SSRF-guarded.
- [x] `[mcp]` Stack traces never exposed — structured `VerifyError` / RFC 9457 problem+json only (2026-06-02)

## B. Error Handling

- [x] `[all]` Structured Error Shape — `VerifyError{reason,detail,retryable}`; HTTP emits RFC 9457 problem+json carrying `code`/`retryable` (2026-06-02)
- [x] `[cli]` Exit codes: 0 ok · 1 user error · 2 runtime (missing signing key) · `--gate` adds opt-in verdict codes (10/20/30) (2026-06-02)
- [x] `[cli]` No raw stack traces — clean `Error:` messages (2026-06-02)
- [x] `[mcp]` Tool errors return structured results — server never crashes on bad input (out-of-enum/​fenced output degrades gracefully) (2026-06-02)
- [x] `[mcp]` State/config corruption degrades gracefully — receipt-store schema migration is idempotent; lens faults degrade to `errored` not crash (2026-06-02)

## C. Operator Docs

- [x] `[all]` README current — install (PyPI), CLI, HTTP service, Ed25519 receipts, cross-tool verify, threat model (2026-06-02)
- [x] `[all]` CHANGELOG.md (Keep a Changelog) — `[0.4.0]` written (2026-06-02)
- [x] `[all]` LICENSE present (MIT); README states support status (2026-06-02)
- [x] `[cli]` `--help` accurate for all commands (verify/replay/verify-receipt/keygen/pubkey/receipt/serve) (2026-06-02)
- [x] `[cli|mcp]` Logging levels / secrets redacted — prism never logs the signing key or API keys; failed auth logs nothing sensitive (2026-06-02)
- [x] `[mcp]` All tools documented (verify + replay) with description + parameters (2026-06-02)
- [ ] `[complex]` HANDBOOK.md — **SKIP:** prism is a library/service; daily-ops surface is covered by README + SECURITY.md. The astro-starlight docs **handbook** is the v0.4 brand-treatment deliverable (Phase 10), wired to the landing page.

## D. Shipping Hygiene

- [x] `[all]` `verify` script exists — `scripts/verify.py` (ruff + mypy + pytest + build in one command) (2026-06-02)
- [x] `[all]` Version in manifest matches git tag — `release.yml` verifies tag == pyproject before publish (2026-06-02)
- [ ] `[all]` Dependency scanning runs in CI — **SKIP:** the org GitHub-Actions rule forbids Dependabot unless explicitly requested and caps workflow files at 2 (ci.yml + release.yml). `uv.lock` pins every dependency; `mypy --strict` + `ruff` run on every push.
- [ ] `[all]` Automated dependency update mechanism — **SKIP:** same org-rule reason (no Dependabot). Updates are operator-driven via `uv lock --upgrade`.
- [x] `[pypi]` `python_requires` set — `requires-python = ">=3.11"` (2026-06-02)
- [x] `[pypi]` Clean wheel + sdist build — `uv build`; `release.yml` runs `twine check dist/*` (2026-06-02)
- [x] `[pypi]` Lockfile committed — `uv.lock` (2026-06-02)
- [x] `[npm]` Clean packaging — `@mcptoolshop/prism-verify` wrapper: `package.json` `files` pins `bin/` + READMEs + LICENSE; `bin/prism.js` passes `node --check` and derives its binary `version`/`tag` from `package.json` at runtime (self-syncing — can't ship a stale binary pin); `release.yml` asserts tag == `npm/package.json` version and that the launcher carries no hard-coded `version:` literal before publishing with provenance (2026-06-13)
- [ ] `[vsix]` `[desktop]` `[container]` — **SKIP:** not a VS Code / desktop / container artifact.

## E. Identity (soft gate — does not block ship)

- [x] `[all]` Logo in README header — `assets/prism-verify-logo.png` (2026-06-02)
- [ ] `[all]` Translations (polyglot-mcp, 8 languages) — **Phase 10** (brand treatment; run before the release tag)
- [ ] `[org]` Landing page (@mcptoolshop/site-theme) — **Phase 10**
- [ ] `[all]` GitHub repo metadata: description, homepage, topics — **Phase 10** (`gh repo edit`)

---

## Gate result

**Hard gates A–D: PASS** (every applicable line checked; SKIPs justified — egress is the product,
Dependabot is org-forbidden, vsix/desktop/container N/A, ops-handbook covered by README/SECURITY
with the docs handbook as the Phase-10 deliverable). The `[npm]` packaging gate is now **audited,
not skipped**: the repo does ship `@mcptoolshop/prism-verify`, the launcher self-syncs its binary
pin from `package.json`, and `release.yml` guards both the version match and the absence of a
hard-coded pin. **Soft gate E:** logo + translations / landing / handbook / topics shipped in the
Phase-10 brand treatment.
