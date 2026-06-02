---
title: Receipts & signing
description: Ed25519 receipts a different tool verifies with prism's public key — no shared secret — plus the honest tamper-evidence ceiling.
sidebar:
  order: 3
---

Every verification writes a signed, replayable receipt to `~/.prism/receipts.db`. The receipt is
prism's audit trail and the thing a consumer trusts: it binds the verdict to the artifact hashes
(pre- and post-strip), the verifier model, the per-lens prompt hashes, the submodularity matrix,
and — for citations — the retrieval pins (query URL + retrieved-source SHA-256).

## Why Ed25519 (v0.4)

Through v0.3 receipts were signed with **HMAC** — symmetric, so only a holder of the shared secret
could verify them. That's fine when the verifier and the consumer are the same process, but it
can't answer the cross-tool question: *can a different tool confirm this verdict without holding
prism's secret?*

v0.4 makes **Ed25519 (RFC 8032)** the production default. prism signs with a private key and
publishes the matching **public key**; any consumer verifies with the public key alone — **no
shared secret**.

```bash
prism keygen --out ~/.prism/signing_key.pem   # generate a keypair
export PRISM_SIGNING_KEY=~/.prism/signing_key.pem
prism pubkey > prism-pub.pem                   # publish this to consumers (carries a kid)
```

A consumer (for example, role-os) verifies a receipt it did not produce:

```bash
prism verify-receipt receipt.json --public-key prism-pub.pem
# exit 0 if the signature is valid, 1 if not
```

`POST /verify-receipt` does the same over HTTP.

## Version-aware

Receipts carry an `alg` (`Ed25519` or `HMAC-SHA256`) and a `kid`. The verifier **whitelists the
algorithm per receipt**, so a v4 Ed25519 receipt can't be downgraded to an HMAC forgery. Legacy
HMAC receipts (set `PRISM_SIGNING_SECRET`) still verify after the in-place schema migration — a
migrating deployment keeps the HMAC secret alongside the new Ed25519 key.

## The honest ceiling

Ed25519 buys **third-party verifiability**, not stronger anti-forgery. An on-disk private key is
still forgeable by an attacker with code execution as the operator and read access to the key —
exactly the same ceiling as the HMAC secret. For genuine tamper-resistance, hold the signing key
in an HSM and anchor receipts in an append-only transparency log. prism states this plainly rather
than shipping local crypto theatre.
