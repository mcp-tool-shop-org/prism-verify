---
title: Reference
description: prism CLI commands, environment variables, verdicts, and refusal codes.
sidebar:
  order: 5
---

## CLI commands

| Command | What it does |
|---|---|
| `prism verify -a <artifact> -i <intent> --caller-family <fam>` | Verify an artifact. `-a @file` reads a file. `--type code\|tool_call\|citations`, `--provider ollama\|anthropic\|...`, `--gate` for verdict exit codes. |
| `prism replay <receipt_id>` | Print a stored receipt + `signature_valid`. |
| `prism verify-receipt <file> [--public-key <pem>]` | Cryptographically verify a standalone receipt. With `--public-key`, an Ed25519 receipt verifies with no shared secret. |
| `prism keygen [--out <path>]` | Generate an Ed25519 signing keypair. |
| `prism pubkey` | Print the configured Ed25519 public key + key id. |
| `prism receipt delete <id>` · `prism receipt prune --older-than <dur> --yes` | Compensators for the receipt store. |
| `prism serve [--host --port]` | Run the HTTP service (needs the `[http]` extra). |
| `prism eval [--split --runs --offline --family-ab]` | Measure the lenses on the labeled corpus — per-lens P/R, diversity matrix, coverage-gain, calibration. See [Calibration & benchmark](../evaluation/). |

`--gate` exit codes: `0` accept · `10` revise · `20` refuse · `30` escalate.

## Environment variables

| Variable | Purpose |
|---|---|
| `PRISM_SIGNING_KEY` | Ed25519 private-key PEM (path or inline) — the v0.4 production default. |
| `PRISM_SIGNING_SECRET` | HMAC signing secret (legacy / explicit). |
| `PRISM_DEV=1` | Use a built-in dev Ed25519 key — INSECURE, local only. |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY` | Enable a hosted verifier family. |
| `PRISM_API_KEYS` | Comma-separated SHA-256 hashes of HTTP bearer API keys. |
| `PRISM_HTTP_ALLOW_NO_AUTH=1` | Allow unauthenticated HTTP use (local dev only). |
| `PRISM_WEBHOOK_SECRET` | Sign async/escalate webhook deliveries. |
| `PRISM_TRUSTED_PROXIES` | Comma-separated CIDRs; honor `X-Forwarded-For` only from these peers (default empty = none). |
| `PRISM_MAX_ARTIFACT_BYTES` | HTTP artifact size cap (default 256 KiB). |

## Verdicts

`accept` · `revise` (with a `revision_hint`) · `refuse` · `escalate` (route to a human). The
artifact verdict aggregates conservatively: any refuse → refuse; else any revise → revise; else any
escalate → escalate; else accept.

## Refusal codes (ANDON halts)

| Code | Meaning |
|---|---|
| `VERIFIER_UNAVAILABLE` | No alternate-family verifier route is available (never falls back same-family). |
| `STRIP_VERIFICATION_FAILED` | Reasoning patterns survived stripping — cannot proceed safely. |
| `LENS_COLLAPSE` | Lenses agreed beyond the submodularity threshold (ρ ≤ 0.25). |
| `BUDGET_EXCEEDED` | The lens fan-out exceeded the caller's latency budget. |
| `INVALID_ARTIFACT` | The artifact (e.g. a citations array) is malformed. |

## HTTP endpoints

See [HTTP service](../http-service/) for `POST /verify`, `GET /replay/{id}`,
`POST /verify-receipt`, `GET /healthz`, and `/docs`.
