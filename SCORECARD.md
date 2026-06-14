# Scorecard — prism-verify

**Repo:** prism-verify
**Date:** 2026-06-13 (v1.3.0)
**Type tags:** `[all]` `[pypi]` `[npm]` `[cli]` `[mcp]`

## Assessment (v1.3.0)

| Category | Score | Notes |
|----------|-------|-------|
| A. Security | 9/10 | SECURITY.md + README threat model; no secrets; fail-closed HTTP auth (keys hashed at rest, constant-time); SSRF-guarded webhooks; Ed25519 third-party-verifiable receipts with an honest tamper-evidence ceiling. -1: genuine tamper-resistance (HSM + transparency log) is named-but-deferred. |
| B. Error Handling | 9/10 | `VerifyError{reason,detail,retryable}` + RFC 9457 problem+json; CLI exit codes; MCP/engine degrade gracefully (no crash on out-of-enum/fenced output, idempotent schema migration). |
| C. Operator Docs | 9/10 | README current for v1.3; CHANGELOG (Keep a Changelog); LICENSE; accurate `--help`; MCP tools documented; astro-starlight docs handbook + landing shipped (Phase-10). -1: deep API reference still lives in docstrings. |
| D. Shipping Hygiene | 9/10 | `scripts/verify.py`; tag==version gate in `release.yml` (PyPI + npm); the npm launcher now derives its binary `version`/`tag` from `package.json` at runtime and `release.yml` guards against a hard-coded pin (`node --check` + grep), so the wrapper can't ship a stale binary; clean `uv build` + `twine check`; `uv.lock` committed; PyPI + npm Trusted Publishing (OIDC, PEP 740 attestations / provenance). -1: no Dependabot (org-rule SKIP). |
| E. Identity (soft) | 9/10 | Logo in README; translations (8 languages), landing page, astro-starlight handbook, and GitHub topics shipped (Phase-10 brand treatment). -1: ongoing polish. |
| **Overall** | **45/50** | Hard gates A–D pass; soft gate E shipped. |

## Key Gaps

1. Tamper-resistance ceiling (HSM / transparency log) — named hardening, deferred (design/05).
2. Deep API reference currently lives in docstrings rather than the handbook.

## Remediation Priority

| Priority | Item | Status |
|----------|------|--------|
| 1 | Hard gates A–D | ✅ PASS |
| 2 | Brand treatment (E) — translations → landing → handbook → topics | ✅ Shipped (Phase 10) |
| 3 | npm launcher binary-pin drift (was shipping a stale v0.4.2 binary) | ✅ Fixed — launcher self-syncs from package.json; CI guards the pin |
| 4 | Tamper-resistance ceiling (HSM / transparency log) | Named hardening, deferred (design/05) |
