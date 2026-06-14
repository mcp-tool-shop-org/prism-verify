# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.3.x   | Yes       |
| < 1.3   | No        |

Only the latest minor (`1.3.x`) receives security fixes. Older `1.x` and all `0.x` lines are not maintained — upgrade to the current release.

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

Prism is a runtime adjudication library/service. It verifies a code / tool-call / citation
artifact against a stated intent by routing to a model family different from the caller's, and
emits a signed, replayable receipt. It runs as a library, an MCP server, a CLI, and (with the
`[http]` extra) an HTTP service.

- **Data prism reads:** the artifact and intent you pass to `verify()`, and the verifier models'
  responses. It does **not** read your source tree, environment, or credentials beyond the
  provider API keys you explicitly supply via environment variables.
- **Data prism writes:** signed receipts to a local SQLite database (default
  `~/.prism/receipts.db`). Receipts hold artifact hashes (pre/post-strip), the verdict, verifier
  model IDs, the pairwise submodularity matrix, per-lens prompt hashes, and citation-retrieval
  pins — not the raw artifact.
- **Network egress:** only to the model providers you configure (Anthropic / OpenAI / Google /
  local Ollama), the citation-retrieval oracles (arXiv / Crossref) when verifying citations, and
  any webhook URL you register for async delivery. No telemetry, analytics, or other egress.
- **Secrets:** provider API keys are read from their standard environment variables and passed to
  the providers; they are never written to receipts. The receipt signing key and the HTTP
  surface's auth/webhook secrets are described below.

## Receipts & signing

Every verification produces a signed, replayable receipt. As of v0.4 the **default signing
algorithm is Ed25519 (RFC 8032)** — an asymmetric keypair, so a third party can verify a prism
receipt with prism's **public key alone, no shared secret**. **HMAC-SHA256 is legacy / opt-in**,
retained so receipts written by older prism builds (and explicit `PRISM_SIGNING_SECRET` deploys)
keep verifying. Each receipt records its `alg` and `kid`, and the verifier dispatches on — and
whitelists — the recorded algorithm, so a downgrade / algorithm-confusion attack is refused.

- Generate a keypair with `prism keygen --out ~/.prism/signing_key.pem`, point
  `PRISM_SIGNING_KEY` at the private PEM, and publish the public key (`prism pubkey`) so consumers
  can verify your receipts.
- A consumer verifies a standalone receipt with only the public key:
  `prism verify-receipt receipt.json --public-key prism-pub.pem` (or `POST /verify-receipt`).
- Prism **refuses to start** the verify / replay / serve / MCP paths when no signing key is
  configured, rather than silently signing with a publicly known key. `PRISM_DEV=1` mints a
  built-in dev key for local play only.

### Receipt canonicalization

Signatures cover a **deterministic canonical JSON** representation of the receipt's signed
field-set (receipt schema **v5**, RFC 8785-style: keys sorted, no insignificant whitespace, UTF-8
output with no `\uXXXX` escaping, and non-finite floats — `NaN` / `Infinity` — rejected rather
than serialized). The exact byte profile is specified in the docstring of
[`src/prism/receipts/signing.py`](src/prism/receipts/signing.py); both signing and verification
go through the same canonicalizer, so a receipt is byte-for-byte replayable. Each schema version
signs only its own field-set, so legacy `v1`–`v4` receipts still verify after an in-place
migration.

### Integrity ceiling (honest disclosure)

Receipt signatures are tamper-**evident**, not tamper-**proof**. Ed25519 buys **third-party
verifiability** (anyone with the public key can confirm a receipt), **not** anti-forgery against a
local-root attacker: the signing **private key lives on disk** wherever you put
`PRISM_SIGNING_KEY` (the same ceiling as the HMAC secret), so an attacker who can both write the
SQLite file and read that key can mint forged receipts. The named hardening path for genuine
tamper-resistance is to hold the signing key in an **HSM** (so the private key never touches the
host) and anchor receipts in an **append-only transparency log** (or go **Sigstore-keyless**),
which moves integrity out of the trust boundary of the host that stores receipts.

## HTTP surface

`prism serve` (the `[http]` extra) exposes the same guarantees as the CLI/MCP over HTTP. Its
hardening:

- **Loopback-by-default binding.** `prism serve` binds `127.0.0.1` unless you pass `--host`.
- **Fail-closed API-key auth.** `POST /verify`, `GET /replay/{id}`, and `POST /verify-receipt`
  require a bearer API key; if no keys are configured the service refuses every request (401)
  rather than leaving an expensive endpoint open. `GET /healthz` is the only intended unauthenticated
  route. Opt into unauthenticated local use only with `PRISM_HTTP_ALLOW_NO_AUTH=1`.
- **Keys hashed at rest.** Only SHA-256 hashes of the keys live in `PRISM_API_KEYS`; the raw key
  is never stored, and presented keys are compared in constant time.
- **SSRF-guarded webhooks.** Caller-supplied async/escalate webhook URLs must be `https`; the host
  is resolved and **any** resolved address in a loopback / private (RFC 1918) / link-local /
  reserved / multicast / carrier-grade-NAT range, or the cloud-metadata address `169.254.169.254`
  (IPv4 and IPv6, incl. IPv4-mapped), is rejected. The connection is **pinned to the validated
  IP** (the request goes to the IP while the original hostname rides in the `Host` header + TLS
  SNI for cert verification) and **redirects are disabled**, so the resolve-vs-connect
  DNS-rebinding TOCTOU and 3xx-to-internal pivots are both closed.
- **RFC 9457 errors.** Every 4xx/5xx is an `application/problem+json` document carrying prism's
  structured `code` / `retryable` fields.
- **Denial-of-wallet back-pressure.** A per-key rate limit (`429` + `Retry-After`), a stricter
  per-IP failed-auth limiter (with a bounded, LRU-evicted bucket map so a flood of hostile IPs
  can't exhaust memory), and an artifact-size cap (rejected before any provider call).
- **Idempotency.** `POST /verify` honors an `Idempotency-Key` header (replay → original response;
  in-flight → `409`; body mismatch → `422`), on both the sync and async paths.
- **Signed webhook deliveries.** Async/escalate verdicts are Standard-Webhooks-signed
  (HMAC over `id.timestamp.payload`, 300s tolerance, multi-signature rotation), retried with a
  bounded backoff into a dead-letter on exhaustion, and carry a named `send_cancel_event()`
  compensator (a forward "disregard the prior verdict" POST) for the irreversible verdict send.

It runs caller-supplied artifacts through a model; an artifact may *attempt* prompt injection but
cannot change the verdict schema or exfiltrate prism's provider keys.

## Configuration / environment variables

| Variable | Purpose |
|----------|---------|
| `PRISM_SIGNING_KEY` | Ed25519 **private** key (inline PEM or path) used to sign new receipts — the production default. |
| `PRISM_SIGNING_SECRET` | **Legacy** HMAC-SHA256 signing secret. Set alongside `PRISM_SIGNING_KEY` to keep verifying old HMAC receipts after moving to Ed25519. |
| `PRISM_DEV` | `1` → mint a built-in dev signing key (local development only; refused implicitly in production by not being set). |
| `PRISM_API_KEYS` | Comma-separated **SHA-256 hashes** of the HTTP bearer API keys (never the raw keys). |
| `PRISM_WEBHOOK_SECRET` | Secret used to sign async/escalate webhook deliveries (Standard Webhooks). |
| `PRISM_HTTP_ALLOW_NO_AUTH` | `1` → allow unauthenticated HTTP use (local dev escape hatch; the service is otherwise fail-closed). |
| `PRISM_TRUSTED_PROXIES` | Comma-separated CIDRs of trusted reverse proxies. **Default empty = no `X-Forwarded-For` trust** (the client IP is taken from the socket). When set, the service honors `X-Forwarded-For` **only** when the immediate peer is within one of these CIDRs, so a client cannot spoof its rate-limit identity. |
| `PRISM_MAX_ARTIFACT_BYTES` | Override the artifact-size cap (default 256 KiB). |
| Provider keys | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` — read from their standard env vars, passed to the providers, never written to receipts. |

## Reasoning-stripping note

Prism strips producer chain-of-thought before the artifact crosses the family boundary and
re-parses to confirm; if reasoning patterns survive, it refuses with
`STRIP_VERIFICATION_FAILED` rather than proceeding with a partially-stripped artifact.

## No telemetry

Prism sends requests only to the model providers you configure, the citation-retrieval oracles
when verifying citations, and any webhook URL you register. There is no telemetry, analytics, or
phone-home of any kind.
