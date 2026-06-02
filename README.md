<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/prism-verify/main/assets/prism-verify-logo.png" alt="prism-verify logo" width="500">
</p>

<p align="center">
  <a href="https://pypi.org/project/prism-verify/"><img src="https://img.shields.io/pypi/v/prism-verify" alt="PyPI"></a>
  <a href="https://www.npmjs.com/package/@mcptoolshop/prism-verify"><img src="https://img.shields.io/npm/v/@mcptoolshop/prism-verify" alt="npm"></a>
  <a href="https://mcp-tool-shop-org.github.io/prism-verify/"><img src="https://img.shields.io/badge/Landing_Page-live-22d3ee" alt="Landing Page"></a>
  <a href="https://mcp-tool-shop-org.github.io/prism-verify/handbook/"><img src="https://img.shields.io/badge/Handbook-docs-22d3ee" alt="Handbook"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
</p>

# prism-verify

Runtime adjudication service for agent workflows. Family-different, reasoning-stripped, multi-lens verification with replayable receipts. **[Landing page &amp; handbook →](https://mcp-tool-shop-org.github.io/prism-verify/)**

## Install

Install the `prism` CLI (and the HTTP service) on your PATH:

```bash
uv tool install prism-verify        # or: pipx install prism-verify
```

Zero Python? Use the npm launcher (downloads + SHA256-verifies a prebuilt binary):

```bash
npx @mcptoolshop/prism-verify verify --artifact @file.py --intent "..." --caller-family openai
```

Or add it as a library — extras: `[anthropic]` `[openai]` `[google]` `[mcp]` `[http]` `[all]`:

```bash
uv add prism-verify
# or
pip install "prism-verify[all]"
```

## Quick start

Prism always verifies with a model family **different** from the caller's (Lock 1), so
configure at least one alternate-family provider. Generate an Ed25519 signing key (the default —
receipts are verifiable by anyone with the public key) so receipts can be written, or use
`PRISM_DEV=1` for local play:

```bash
prism keygen --out ~/.prism/signing_key.pem      # Ed25519 keypair (default signing)
export PRISM_SIGNING_KEY=~/.prism/signing_key.pem # or: export PRISM_DEV=1 (local play)
export ANTHROPIC_API_KEY="sk-ant-..."             # alt-family verifier for an OpenAI-family caller

prism verify \
  --artifact @myfile.py \
  --intent "Sort a list in O(n log n)" \
  --caller-family openai \
  --provider anthropic
```

> Legacy alternative: `export PRISM_SIGNING_SECRET="$(openssl rand -hex 32)"` signs receipts with
> HMAC instead (verifiable only by holders of that shared secret — see [Receipts](#receipts--signing-ed25519-verifiable-by-anyone)).

## Architecture

Prism enforces four architectural locks at the API contract:

1. **Family-different** — caller's model family is always excluded from verification
2. **Reasoning-stripped** — producer CoT is stripped before crossing the family boundary
3. **Multi-lens** — at least 3 independent lenses run in parallel
4. **Submodularity-aware** — refuses if lenses agree too much (collapsed signal)

## HTTP service

Run prism as an HTTP service (needs the `[http]` extra):

```bash
prism serve --host 127.0.0.1 --port 8000      # OpenAPI docs at /docs
```

| Endpoint | What it does |
|---|---|
| `POST /verify` | Verify an artifact (same contract as the CLI). Blocks within the budget; `Prefer: respond-async` + a `webhook` URL → `202`, verdict delivered to the (signed) webhook. |
| `GET /replay/{receipt_id}` | The signed receipt + `signature_valid`. |
| `POST /verify-receipt` | Verify a standalone receipt (cross-tool). |
| `GET /healthz` | Liveness + configured verifier families (no auth). |

Set API keys (hashed at rest) — prism is **fail-closed**, so `/verify` is refused until keys
are configured or you opt into local no-auth:

```bash
export PRISM_API_KEYS="<sha256(key1)>,<sha256(key2)>"   # callers send: Authorization: Bearer <key>
export PRISM_WEBHOOK_SECRET="<random>"                  # to sign async/escalate webhook deliveries
# local dev only:
export PRISM_HTTP_ALLOW_NO_AUTH=1
```

Errors are RFC 9457 `application/problem+json`; `POST /verify` honours an `Idempotency-Key`
header and a per-key rate limit (`429` + `Retry-After`). Async/escalate webhooks are
Standard-Webhooks-signed, SSRF-guarded (no internal/metadata targets), retried, and carry a
named cancel-event compensator.

## Receipts & signing (Ed25519, verifiable by anyone)

Every verification produces a signed, replayable receipt in `~/.prism/receipts.db`. v0.4 signs
new receipts with **Ed25519 (RFC 8032)** by default, so **a different tool can verify a prism
receipt with prism's public key — no shared secret**:

```bash
prism keygen --out ~/.prism/signing_key.pem    # generate an Ed25519 keypair
export PRISM_SIGNING_KEY=~/.prism/signing_key.pem
prism pubkey                                    # publish this public key + kid to consumers

# a consumer (e.g. role-os) verifies a receipt with ONLY the public key:
prism verify-receipt receipt.json --public-key prism-pub.pem
```

The signature covers the verdict, the pre/post-strip artifact hashes, the verifier model, the
submodularity matrix, the per-lens prompt hashes (byte-for-byte replayable), the citation
retrieval pins, and the signing `alg`/`kid`. Legacy **HMAC** receipts still verify (set
`PRISM_SIGNING_SECRET`); `PRISM_DEV=1` mints a dev key for local play. Prism **refuses to start**
the verify / replay / serve / MCP paths if no key is configured, rather than silently signing
with a publicly known key.

Manage stored receipts with the compensator commands:

```bash
prism receipt delete <receipt_id>
prism receipt prune --older-than 90d --yes
```

## Security & privacy

- **Threat model.** Prism reads the artifact + intent you pass and the verifier models'
  responses, and writes signed receipts to a local SQLite DB. It does **not** read your
  source tree, environment, or credentials beyond the provider API keys you supply via
  environment variables. Receipt signatures give **third-party verifiability** (Ed25519: a
  consumer verifies with the public key, no shared secret) but are not tamper-*proof* against a
  local-root attacker who can read the on-disk private key — that's the same ceiling as the HMAC
  secret. For genuine tamper-resistance, hold the key in an HSM and anchor receipts in a
  transparency log (the named hardening path).
- **HTTP surface.** `prism serve` binds loopback by default, is **fail-closed** (no `/verify`
  without API keys), hashes keys at rest, and **SSRF-guards** caller-supplied webhook URLs
  (no internal/link-local/metadata targets). It runs caller-supplied artifacts through a model;
  an artifact may *attempt* prompt injection but cannot change the verdict schema or exfiltrate
  prism's provider keys.
- **No telemetry.** Prism sends requests only to the model providers you configure
  (Anthropic / OpenAI / Google / local Ollama). Nothing else.
- Full policy: [SECURITY.md](SECURITY.md).

## License

MIT
