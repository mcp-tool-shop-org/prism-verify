# Scorecard — prism-verify

**Repo:** prism-verify
**Date:** 2026-06-02 (v0.4.0)
**Type tags:** `[all]` `[pypi]` `[cli]` `[mcp]`

## Assessment (v0.4.0)

| Category | Score | Notes |
|----------|-------|-------|
| A. Security | 9/10 | SECURITY.md + README threat model; no secrets; fail-closed HTTP auth (keys hashed at rest, constant-time); SSRF-guarded webhooks; Ed25519 third-party-verifiable receipts with an honest tamper-evidence ceiling. -1: genuine tamper-resistance (HSM + transparency log) is named-but-deferred. |
| B. Error Handling | 9/10 | `VerifyError{reason,detail,retryable}` + RFC 9457 problem+json; CLI exit codes; MCP/engine degrade gracefully (no crash on out-of-enum/fenced output, idempotent schema migration). |
| C. Operator Docs | 8/10 | README current for v0.4; CHANGELOG (Keep a Changelog); LICENSE; accurate `--help`; MCP tools documented. -2: the astro-starlight docs handbook + landing are the Phase-10 deliverable. |
| D. Shipping Hygiene | 9/10 | `scripts/verify.py`; tag==version gate in `release.yml`; clean `uv build` + `twine check`; `uv.lock` committed; PyPI Trusted Publishing (OIDC, PEP 740 attestations). -1: no Dependabot (org-rule SKIP). |
| E. Identity (soft) | 4/10 | Logo in README. Translations / landing / astro-starlight handbook / GitHub topics are the Phase-10 brand treatment (run before the release tag). |
| **Overall** | **39/50** | Hard gates A–D pass; E (soft) completes in Phase 10. |

## Key Gaps (all Phase-10 brand treatment, soft gate)

1. README translations (8 languages, local TranslateGemma) — run **before** the release tag.
2. Landing page (@mcptoolshop/site-theme) + astro-starlight handbook wired to it.
3. GitHub repo metadata: description, homepage, topics (`gh repo edit`).

## Remediation Priority

| Priority | Item | Status |
|----------|------|--------|
| 1 | Hard gates A–D | ✅ PASS (this session) |
| 2 | Brand treatment (E) | Phase 10 — translations → landing → handbook → topics, before the tag |
| 3 | Tamper-resistance ceiling (HSM / transparency log) | Named hardening, deferred (design/05) |
