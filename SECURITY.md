# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | Yes       |
| < 0.2   | No        |

## Reporting a Vulnerability

Email: **64996768+mcp-tool-shop@users.noreply.github.com**

Include:
- Description of the vulnerability
- Steps to reproduce
- Version affected
- Potential impact

### Response timeline

| Action | Target |
|--------|--------|
| Acknowledge report | 48 hours |
| Assess severity | 7 days |
| Release fix | 30 days |

## Scope & threat model

Prism is a runtime adjudication library/service. It verifies a code/tool-call artifact
against a stated intent by routing to a model family different from the caller's, and
emits an HMAC-signed, replayable receipt.

- **Data prism reads:** the artifact and intent you pass to `verify()`, and the verifier
  models' responses. It does **not** read your source tree, environment, or credentials
  beyond the provider API keys you explicitly supply via environment variables.
- **Data prism writes:** signed receipts to a local SQLite database (default
  `~/.prism/receipts.db`). Receipts hold artifact hashes, the verdict, verifier model IDs,
  the pairwise submodularity matrix, and per-lens prompt hashes — not the raw artifact.
- **Network egress:** only to the model providers you configure (Anthropic / OpenAI /
  Google / local Ollama). No telemetry, analytics, or other egress.
- **Secrets:** the receipt signing secret comes from `PRISM_SIGNING_SECRET` (or an explicit
  argument). Prism refuses to sign with the built-in dev key unless `PRISM_DEV=1` is set.
  Provider API keys are read from their standard environment variables and passed to the
  providers; they are never written to receipts.

### Integrity ceiling (honest disclosure)

Receipt signatures are tamper-**evident**, not tamper-**proof**. The HMAC key lives wherever
you put `PRISM_SIGNING_SECRET`; an attacker who can both write the SQLite file and read that
key can forge signatures. For a stronger guarantee, hold the signing secret outside the
trust boundary of the host that stores receipts (e.g. a separate signing service).
Externally-anchored integrity is a roadmap item.

## Reasoning-stripping note

Prism strips producer chain-of-thought before the artifact crosses the family boundary and
re-parses to confirm; if reasoning patterns survive, it refuses with
`STRIP_VERIFICATION_FAILED` rather than proceeding with a partially-stripped artifact.
