---
title: HTTP service
description: Run prism as a FastAPI service — endpoints, auth, idempotency, rate-limiting, and the signed-webhook escalate channel.
sidebar:
  order: 2
---

`prism serve` exposes the same engine over HTTP (needs the `[http]` extra). It's a thin transport
over the CLI/MCP engine — the four locks, ANDON refusals, and signed receipts are unchanged.

```bash
prism serve --host 127.0.0.1 --port 8000     # OpenAPI docs at /docs
```

## Endpoints

| Method | Path | Behavior |
|---|---|---|
| `POST` | `/verify` | Verify an artifact. Blocks within the latency budget → `200` with the verdict. With `Prefer: respond-async` + a registered `webhook`, returns `202` and delivers the verdict to the webhook. |
| `GET` | `/replay/{receipt_id}` | The stored receipt + `signature_valid`. |
| `POST` | `/verify-receipt` | Verify a standalone receipt (cross-tool) — see [Receipts](../receipts/). |
| `GET` | `/healthz` | Liveness + configured verifier families. Unauthenticated. |
| `GET` | `/docs`, `/openapi.json` | Auto-generated OpenAPI 3.1. |

## Auth (fail-closed)

prism runs caller-supplied artifacts through paid model calls, so the surface is **fail-closed**:
`/verify` is refused until API keys are configured. Keys are `prism_`-prefixed, **hashed at rest**
(only SHA-256 hashes live in config), and constant-time compared.

```bash
export PRISM_API_KEYS="<sha256(key1)>,<sha256(key2)>"   # callers send: Authorization: Bearer <key>
# local dev only — disables the requirement:
export PRISM_HTTP_ALLOW_NO_AUTH=1
```

A separate, stricter per-IP limiter throttles *failed* auth, so key-guessing costs ~0 compute and
never reaches a model.

## Back-pressure, idempotency, errors

- **Rate limit** — per-key token bucket; `429` with `Retry-After` + a `RateLimit` header (emitted on
  success too). An oversize artifact is rejected with `413` *before* any provider call.
- **Idempotency** — send an `Idempotency-Key`; a retry replays the original result (`200`/`202`),
  an in-flight key returns `409`, and the same key with a different body returns `422`.
- **Errors** — every 4xx/5xx is RFC 9457 `application/problem+json`, carrying prism's structured
  `code`/`retryable` as extension members.

## Signed-webhook escalate channel

For async / `escalate` verdicts that exceed the sync budget, prism POSTs the verdict to a
caller-registered `webhook` URL. Deliveries are **Standard-Webhooks-signed** (HMAC over
`id.timestamp.payload`, 300s tolerance, multi-signature for rotation), retried with backoff, and
dead-lettered on exhaustion. The endpoint is **SSRF-guarded**: prism requires https, resolves the
host, rejects any internal / link-local / metadata address, and pins the connection to the
validated IP. A withdrawn verdict is compensated by a signed `verdict_cancelled` follow-up.

```bash
export PRISM_WEBHOOK_SECRET="<random>"   # signs deliveries
```
