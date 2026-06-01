<p align="center">
  <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/prism-verify/main/assets/prism-verify-logo.png" alt="prism-verify logo" width="320">
</p>

# prism-verify

Runtime adjudication service for agent workflows. Family-different, reasoning-stripped, multi-lens verification with replayable receipts.

## Install

```bash
uv add prism-verify
# or
pip install prism-verify[all]
```

## Quick start

Prism always verifies with a model family **different** from the caller's (Lock 1), so
configure at least one alternate-family provider. Set a signing secret (or `PRISM_DEV=1`
for local play) so receipts can be written:

```bash
export PRISM_SIGNING_SECRET="$(openssl rand -hex 32)"
export ANTHROPIC_API_KEY="sk-ant-..."   # alt-family verifier for an OpenAI-family caller

prism verify \
  --artifact @myfile.py \
  --intent "Sort a list in O(n log n)" \
  --caller-family openai \
  --provider anthropic
```

## Architecture

Prism enforces four architectural locks at the API contract:

1. **Family-different** — caller's model family is always excluded from verification
2. **Reasoning-stripped** — producer CoT is stripped before crossing the family boundary
3. **Multi-lens** — at least 3 independent lenses run in parallel
4. **Submodularity-aware** — refuses if lenses agree too much (collapsed signal)

## Receipts & signing

Every verification produces an HMAC-signed, replayable receipt in `~/.prism/receipts.db`.
The signature covers the verdict, the pre/post-strip artifact hashes, the verifier model,
the pairwise submodularity matrix, the per-lens prompt hashes (so a run is byte-for-byte
replayable), and the caller-actionable `confidence`/`retryable` outputs.

Set the signing secret before running anything that writes or verifies receipts:

```bash
export PRISM_SIGNING_SECRET="<a long random secret>"   # production
# or, for local development only:
export PRISM_DEV=1                                       # uses a public, INSECURE dev key
```

Prism **refuses to start** the verify / replay / MCP paths if neither is set, rather than
silently signing with a publicly known key. Receipts written by v0.1.0 under the old
built-in dev key report `signature_valid: false` once you set a real `PRISM_SIGNING_SECRET`
— that is expected (different key), not tampering.

Manage stored receipts with the compensator commands:

```bash
prism receipt delete <receipt_id>
prism receipt prune --older-than 90d --yes
```

## Security & privacy

- **Threat model.** Prism reads the artifact + intent you pass and the verifier models'
  responses, and writes signed receipts to a local SQLite DB. It does **not** read your
  source tree, environment, or credentials beyond the provider API keys you supply via
  environment variables. Receipt signatures are tamper-*evident* (local HMAC), not
  tamper-*proof* — hold `PRISM_SIGNING_SECRET` outside the receipt host for a stronger
  guarantee.
- **No telemetry.** Prism sends requests only to the model providers you configure
  (Anthropic / OpenAI / Google / local Ollama). Nothing else.
- Full policy: [SECURITY.md](SECURITY.md).

## License

MIT
