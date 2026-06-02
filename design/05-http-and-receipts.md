# Prism — HTTP Runtime Surface + Independently-Verifiable Receipts (v0.4.0)

The v0.4 headline: prism becomes an **installable, HTTP-callable, independently-verifiable
runtime service**. Three new product layers — an HTTP/FastAPI surface, a signed-webhook escalate
channel, and asymmetric (Ed25519) receipts that a *different tool* can verify without prism's
secret — plus PyPI Trusted Publishing so `uv tool install prism-verify` yields a real `prism` on
PATH (directly unblocking role-os's `PRISM_CMD` venv-path hack).

Grounded by the v0.4 study-swarm (`wf_f0f8b9c8-e2c`, 2026-06-02, 5 parallel agents, 40 cited
findings). Builds on the founding dispatch (`design/01`) — the p50≤2s budget, the
refusal-to-compensator API shape, the webhook channel, and the receipt model were already
grounded there; this dispatch resolves the concrete HTTP/auth/webhook/signing/PyPI decisions
`design/01` deferred to "v1.5+".

---

## Research grounding (the empirical floor)

Each finding is connected to a specific design decision — citations without architectural
connection are noise (per [[research-grounded-advisor-protocol]]).

### HTTP contract for a compute-heavy verifier (Q1)

1. **Methods that may exceed ~10s must return an async operation token, not block.** Google AIP-151
   *Long-running operations* (https://google.aip.dev/151). → `POST /verify` does **not** block when
   the reasoning tier exceeds the ceiling; it returns one canonical async resource and reuses
   `GET /replay/{receipt_id}` as the polling/result endpoint rather than a per-artifact-type async shape.
2. **`Prefer: respond-async` lets ONE endpoint serve fast-sync and slow-async callers.** Snell 2014,
   RFC 7240 (https://www.rfc-editor.org/rfc/rfc7240). → Default: block up to p50≤2s → `200` inline.
   With `Prefer: respond-async` (or reasoning-tier): `202` + `Location: /replay/{receipt_id}`. Keeps
   role-os's existing synchronous shell-out fast path untouched.
3. **The async monitor carries a `status` + `Retry-After`.** Microsoft 2024, Azure REST Guidelines
   (async-operations). → The receipt resource exposes status mapping onto the four-value verdict;
   non-terminal polls emit `Retry-After` so callers back off instead of hot-polling.
4. **Idempotency-Key: replay completed result, 409 in-flight, 422 on payload-mismatch.** IETF
   draft-ietf-httpapi-idempotency-key-header-07 (datatracker.ietf.org). → `POST /verify` accepts an
   `Idempotency-Key`; key→receipt fingerprinted by a hash of the (artifact, intent, lenses,
   caller-family) request, so a retried key returns the cached receipt and a reused-with-different-body
   key is a `422`. Prevents duplicate **paid** reasoning runs on network flakiness.
5. **Structured `RateLimit` + `Retry-After`; Retry-After wins on a 429.** IETF
   draft-ietf-httpapi-ratelimit-headers-11 + RFC 6585 (Nottingham 2012). → A token-bucket limiter
   emits `429` with both headers; `RateLimit` is emitted on success too — back-pressure on an
   expensive endpoint is part of the contract.
6. **RFC 9457 `application/problem+json` for every error, extension members allowed.** Nottingham,
   Wilde & Dalal 2023 (https://www.rfc-editor.org/rfc/rfc9457.html). → All 4xx/5xx return
   `application/problem+json` with stable `type` URIs (`/problems/verifier-unavailable`,
   `/problems/budget-exceeded`, `/problems/idempotency-conflict`, …) carrying prism's existing
   `RefusalReason`/`detail` as extension members. Upgrades the CLI's structured-error shape to a
   wire standard.
7. **FastAPI BackgroundTasks are in-process and lossy — disqualifying for a job that owes a signed
   receipt.** FastAPI docs 2026 (Background Tasks). → The async path does **not** use
   BackgroundTasks; the durable receipt IS the job record. v0.4 runs the async verification in a
   tracked in-process `asyncio` task (awaited on shutdown via lifespan) and **delivers the result via
   the signed-webhook channel**, with an honest disclosure that durable cross-restart async needs a
   real queue (deferred to v0.5).
8. **OpenAPI 3.1 is JSON-Schema-2020-12; FastAPI generates it from `response_model` + `status_code` +
   `lifespan`.** OpenAPI Initiative 2021, OAS 3.1.0. → Typed `response_model` + explicit
   `status_code` per endpoint make `/docs` the independently-verifiable contract; `lifespan` opens the
   engine/store handles once.

### Auth + abuse controls for a single-tenant LLM-backed service (Q2)

9. **API keys are the sanctioned mechanism for M2M client auth.** OWASP API2:2023 Broken
   Authentication (owasp.org/API-Security). → A single scoped, hashed API key per deploy is correct
   for role-os→prism. **No** OAuth2/OIDC in v0.4 — there is no delegated-user problem to solve.
10. **OAuth2 BCP machinery targets delegated user authz; M2M only gains optional mTLS/DPoP binding.**
    IETF RFC 9700 (datatracker.ietf.org/doc/rfc9700). → mTLS/DPoP are a documented *hardening tier*,
    named in SECURITY.md, not the v0.4 floor (a bearer key over operator-terminated TLS).
11. **"Denial of wallet" — token/cost throttling is the control teams miss; real incidents hit
    $46k/day.** OWASP LLM10:2025 Unbounded Consumption (genai.owasp.org). → The primary abuse control
    is a per-key **cost/size** ceiling, not request-rate: cap artifact byte-size + bound the ≥3-lens
    fan-out concurrency + reject over-budget callers **before** any provider call. (Full per-token
    cost accounting needs provider token telemetry — named as the v0.5 completion; v0.4 ships
    size-cap + concurrency-cap + per-key rate limit as the honest floor.)
12. **Prompt-injection mitigation is defense-in-depth; delimiting alone is insufficient.** OWASP
    LLM01:2025 (genai.owasp.org). → Keep the existing `<<<…>>>` markers AND lean on prism's
    structural guarantees: the verifier returns a *constrained verdict schema* (output-format
    constraint), reasoning is stripped, and provider keys are prism's (least-privilege). Disclose: an
    artifact may *attempt* injection but cannot change the verdict schema or exfiltrate prism's keys.
13. **API-key hygiene: hash at rest, non-secret prefix, ≥2 active for rotation, constant-time
    compare.** Zuplo/OneUptime 2026; OWASP API2:2023 (stricter anti-brute-force on auth). → Store only
    SHA-256 hashes; emit/match a greppable `prism_` prefix; support ≥2 active keys; constant-time
    compare; a **separate stricter failed-auth limiter** so key-guessing costs ~0 compute and never
    reaches a model call.
14. **Single services need not absorb the mesh's zero-trust stack.** NIST SP 800-204A 2020
    (csrc.nist.gov). → Validates the single-tenant scope: TLS termination + infra rate limiting are
    the operator's reverse-proxy/mesh concern; prism ships app-level key auth + cost back-pressure +
    documents the recommended deployment posture.

### Signed-webhook escalate channel (Q3)

15. **Sign `timestamp.body` (not body alone); 300s tolerance; constant-time.** Stripe 2026 Webhooks
    (docs.stripe.com/webhooks). → The replay defense is the *timestamp inside the signature*.
16. **Standard Webhooks: `webhook-id`/`-timestamp`/`-signature`, HMAC-SHA256 over
    `id.timestamp.payload`, space-delimited multi-sig for rotation.** Standard Webhooks spec
    (standardwebhooks.com). → Adopt these header names + signed content; multi-sig lets prism rotate
    the webhook secret without breaking consumers.
17. **At-least-once + unordered → the message id is the consumer's idempotency key.** Standard
    Webhooks / Stripe duplicate-handling. → Stamp each POST with a **stable** `webhook-id`
    (deterministic from `receipt_id` + event-type so a retry reuses it); a cancel-event shares the
    `receipt_id` but is a *distinct* delivery (distinct id).
18. **Retry with exp backoff + full jitter, bounded budget, fail-fast on 4xx, dead-letter the rest.**
    Svix/Hookdeck 2026. → Bounded retry (injectable delays, like the arXiv oracle); on exhaustion
    persist to a **dead-letter table** in SQLite — never silently drop a verdict.
19. **A saga compensator is a NEW forward action, not a physical rollback.** Garcia-Molina & Salem
    1987, *Sagas*, ACM SIGMOD (DOI 10.1145/38713.38742). → The cancel-event (`{event:
    verdict_cancelled, receipt_id}`) is a forward POST that *semantically withdraws* the verdict;
    prism's scope ends at "I notified the consumer," leaving residual caller action as accepted
    approximation.
20. **Irreversible steps go last; name the compensator + acceptable residual.** Temporal 2026, Saga
    pattern. → The escalate POST is the **last irreversible step** of the verify saga (all in-process
    lens/routing faults can still refuse cleanly before it).
21. **Caller-controlled URL → SSRF Case 2: resolve, reject internal IPs, pin the connection.** OWASP
    2026 SSRF Prevention Cheat Sheet; Stytch 2026 (resolve-and-pin). → Before any POST: require
    `https`; resolve the host; reject **any** resolved IP in loopback/RFC1918/link-local/`169.254.169.254`
    (v4 **and** v6 `fd00::/8`, `fe80::/10`); **pin the connection to the validated IP** to close the
    DNS-rebinding TOCTOU. This is the load-bearing guard that keeps prism from being an SSRF proxy.

### Receipt signing for cross-tool verification (Q4) — Ed25519, version-aware

22. **An HMAC tag is verifiable only by a holder of the shared secret; a signature is verifiable with
    a PUBLISHED public key.** MAC-vs-signature (Dulin; EITCA). → This is the exact gap role-os names.
    Symmetric MAC *structurally cannot* serve cross-tool verification — the decisive reason to add
    Ed25519.
23. **Ed25519 verification takes only (message, 32-byte pubkey, 64-byte sig); signatures are
    deterministic.** RFC 8032 EdDSA, Josefsson & Liusvaara 2017
    (https://www.rfc-editor.org/rfc/rfc8032.html). → Determinism fits prism's byte-for-byte
    replayable receipts (no RNG state to pin); +~96 bytes/row, fast verify.
24. **Add `alg` + `kid`; the verifier MUST whitelist `alg` (never let the receipt pick its own
    verification path).** RFC 7515 JWS / RFC 7517 JWK. → Receipt schema **v4** adds `alg`
    (`HMAC-SHA256`|`Ed25519`) + `kid`; both are *signed* at v4 (downgrade defense); legacy v1/v2/v3
    rows backfill `alg=HMAC-SHA256` and verify against their own field-set.
25. **The most analogous prior art (PyPI PEP 740) chose asymmetric signatures + a separated identity
    layer.** PEP 740 (peps.python.org/pep-0740). → Validates Ed25519-migrate; design the schema so a
    stronger identity binding (OIDC/Sigstore) can land later without a format break.
26. **A signature proves integrity; trust requires binding the public key to a known identity.** C2PA
    2.4 Content Credentials. → Ship a **key-distribution story**: `prism pubkey` prints the public key
    + `kid`; role-os pins the fingerprint in config. The crypto migration ships *with* distribution,
    or it just relocates trust.
27. **Local signing — symmetric OR asymmetric — cannot stop a local-root attacker who reads the
    on-disk key; true tamper-resistance needs external anchoring.** Crosby & Wallach 2009 (USENIX). →
    The honest ceiling: an on-disk Ed25519 private key is as forgeable by local root as the HMAC
    secret. **Ed25519's real win is third-party verifiability, not stronger anti-forgery.** HSM-held
    keys + an append-only transparency log are the named path to genuine tamper-resistance.
28. **Prefer PyCA `cryptography` over PyNaCl for Ed25519.** pyca/cryptography Ed25519 docs. → Use
    `cryptography` (clean detached 64-byte sigs, `InvalidSignature` → structured error); add it as a
    **core** dep so `verify-receipt` always works.

### PyPI Trusted Publishing (Q5) — pending publisher, no placeholder

29. **A PyPI pending publisher auto-creates the project on first OIDC upload — no placeholder
    needed.** PyPI Docs, *Creating a Project Through OIDC*
    (docs.pypi.org/trusted-publishers/creating-a-project-through-oidc). → Strictly simpler than the
    npm v0.0.0 method: configure the pending publisher for `prism-verify`, then ship v0.4.0 directly.
30. **A pending publisher does NOT reserve the name until first upload.** PyPI Docs (warning box). →
    Do TP-config + tag + publish in **one session**; treat it as one atomic release step.
31. **TP needs ONLY `id-token: write`; no API token, no username/password.** PyPI Docs, *Using a
    Publisher*. → Release job: `runs-on: ubuntu-latest`, `environment: pypi`,
    `permissions: { id-token: write }`, build → `pypa/gh-action-pypi-publish@release/v1`.
32. **PEP 740 attestations are ON BY DEFAULT for TP since gh-action-pypi-publish v1.11.0.** Release
    notes; PEP 740. → prism gets signed provenance "for free" — on-brand for a verifier; cite the
    provenance URL in the README "independently verifiable" claim.
33. **`uv build` is a fast frontend over hatchling — identical artifacts to `python -m build`.** uv
    docs (Building distributions). → Release step is `uv build` → `dist/` → publish. No build-backend
    change.
34. **Gate publish on a `pypi` Environment + `release: published` trigger.** GitHub Docs, OIDC in
    PyPI. → Matches the org rule (publish workflows fire on release only). Bind the environment in the
    pending-publisher form for least-privilege.

---

## Locked design

### A. HTTP surface (`prism.http`)

A FastAPI app (`prism.http.app:create_app()`), served by `uvicorn` (the `http` extra). Reuses the
MCP `_setup_engine()` pattern (register lenses + build providers from env keys) via a shared
factory. **Same guarantees as CLI/MCP**: family-different routing, reasoning-strip, ANDON refusals,
signed replayable receipts — the HTTP layer is a thin transport over `engine.verify()`.

| Endpoint | Method | Behavior |
|---|---|---|
| `/verify` | POST | Sync (default): block ≤ budget → `200` + `VerifyResponse`. `Prefer: respond-async` (or budget-exceeding reasoning tier) + a `webhook` registered → `202` + `Location: /replay/{receipt_id}`, delivered via webhook. |
| `/replay/{receipt_id}` | GET | The receipt + `signature_valid` (status monitor for async). `404` problem+json if absent. |
| `/verify-receipt` | POST | Verify a posted receipt JSON's signature (Ed25519 via public key, or HMAC). Cross-tool path. |
| `/healthz` | GET | Liveness + configured provider families (no auth). |
| `/docs`, `/openapi.json` | GET | Auto-generated OpenAPI 3.1. |

- **Idempotency-Key** header → `key → (request_fingerprint, receipt_id)` table; replay `200` / `409`
  in-flight / `422` body-mismatch.
- **Errors** → `application/problem+json` (RFC 9457); `RefusalReason` → stable `type` URI; `detail`
  preserved. A `VerifyError` maps to the right status (`VERIFIER_UNAVAILABLE`→503,
  `BUDGET_EXCEEDED`→503+Retry-After, `INVALID_ARTIFACT`→422, `LENS_COLLAPSE`/`STRIP_*`→422).
- **Rate-limit** → token-bucket per key; `429` + `Retry-After` + `RateLimit`.
- **Lifespan** opens the engine + receipt store + signing key once.

### B. Auth + abuse controls (`prism.http.auth`)

- **Bearer API key**, `prism_`-prefixed, ≥256-bit, **SHA-256-hashed at rest**, constant-time
  compared. Keys configured via `PRISM_API_KEYS` (comma-separated hashes) or a keys file; ≥2 active
  for rotation. `/healthz` is unauthenticated; everything else requires a valid key.
- **Pre-flight rejects (before any provider call):** artifact byte-size cap (`PRISM_MAX_ARTIFACT_BYTES`,
  default 256 KiB) → `413`; ≥3-lens fan-out concurrency bounded by a global semaphore.
- **Failed-auth limiter** — a separate, stricter per-IP limiter; a failed auth never reaches a model
  call.
- **Deferred (named in SECURITY.md):** OAuth2/OIDC/mTLS (no delegated-user problem); full per-token
  cost metering (needs provider token telemetry).

### C. Signed-webhook escalate channel (`prism.http.webhook`)

For async/`escalate` verdicts that exceed the sync budget, prism POSTs the signed verdict to a
caller-registered `webhook` URL.

- **Signature** — Standard Webhooks shape: `webhook-id` (deterministic from `receipt_id`+event),
  `webhook-timestamp`, `webhook-signature: v1,<base64(HMAC-SHA256(id.timestamp.payload))>`;
  space-delimited multi-sig for rotation; consumers verify with a 300s tolerance, constant-time.
- **Delivery** — at-least-once; bounded retry (exp backoff + full jitter, injectable delays,
  ~5 attempts); fail-fast on 4xx; exhaustion → **dead-letter table** in the receipt DB.
- **SSRF guard** (`assert_safe_url`) — require `https`; resolve host; reject any resolved IP in
  loopback/RFC1918/link-local/metadata (v4+v6); **pin the connection to the validated IP**. Enforced
  at registration *and* send time.
- **Cancel-event compensator** — `{event: verdict_cancelled, receipt_id}`, same signing + delivery
  machinery, distinct `webhook-id`. The named compensator for the (irreversible) webhook send.

### D. Receipt signing v4 — Ed25519 production default (`prism.receipts.signing` + `store`)

Director decision (2026-06-02): **Ed25519 becomes the production default**, version-aware.

- **Algorithms** — a `SigningBackend` abstraction with two impls: `Ed25519Backend` (PyCA
  `cryptography`) and `HmacBackend` (legacy/explicit). Receipts carry `alg` + `kid`.
- **Key resolution** (priority): explicit key arg → `PRISM_SIGNING_KEY` (Ed25519 private-key PEM
  path/value) → Ed25519 · else `PRISM_SIGNING_SECRET` → HMAC (explicit legacy) · else `PRISM_DEV=1`
  → a built-in **dev Ed25519 key** (the new zero-config dev default) · else raise. So the documented
  production + dev paths are Ed25519; existing HMAC deployments (which set `PRISM_SIGNING_SECRET`)
  keep working unchanged.
- **Schema v4** — `ALTER TABLE … ADD COLUMN alg TEXT NOT NULL DEFAULT 'HMAC-SHA256'`, `kid TEXT NOT
  NULL DEFAULT ''`; `PRAGMA user_version = 4`. `_build_sign_data` includes `alg`+`kid` only at
  `schema_version >= 4`. Legacy rows verify against their own (v1/v2/v3) field-set — **unchanged
  signatures still verify**.
- **`verify_signature` dispatches on the stored `alg`** (whitelisted, never receipt-chosen): Ed25519
  → verify with the public key (no secret); HMAC → recompute with the secret.
- **New CLI/HTTP**:
  - `prism verify-receipt <receipt.json> [--public-key <pem>]` (+ `POST /verify-receipt`) — verify a
    *standalone* receipt's signature. Ed25519 receipts verify with only the public key → the
    cross-tool path role-os uses.
  - `prism keygen` — generate an Ed25519 keypair (writes private PEM, prints public + `kid`).
  - `prism pubkey` — print the configured public key + `kid` (the key-distribution story).
- **Honest ceiling (threat model)** — an on-disk private key is forgeable by local root, same as the
  HMAC secret. Ed25519 buys **third-party verifiability**, not stronger anti-forgery. HSM + an
  append-only transparency log are the documented path to genuine tamper-resistance.

### E. PyPI Trusted Publishing

- **Pending publisher** for `prism-verify` (owner `mcp-tool-shop-org`, workflow `release.yml`,
  environment left `(Any)` per the org convention) — configured on pypi.org by the operator
  (USER action). No placeholder publish needed.
- **`.github/workflows/release.yml`** — `on: release: { types: [published] }`,
  `permissions: { id-token: write }` (no GH environment declared, matching the `(Any)` publisher),
  `uv build` → `pypa/gh-action-pypi-publish@release/v1` (PEP 740 attestations on by default, no
  token). `actions/checkout@v5` (Node 24 — not the npm template's v4.2.2 / Node 20).
- Name reserved only on first upload → TP-config + tag + publish in one session.

---

## Standards compliance — the new v0.4 surfaces

Per [[workflow-standards]], every new surface is scored 0–3 against the six. (The repo-level
score table is `design/02`; this is the per-surface evidence for the three new layers.)

### HTTP surface

| Standard | Score | Evidence |
|---|---|---|
| PIN_PER_STEP | 3 | Every `POST /verify` flows through `engine.verify()`, which already pins the served model + per-lens prompt hashes + (citations) retrieval pins into the signed receipt. The Idempotency-Key fingerprint pins the exact request a receipt answers. |
| ANDON_AUTHORITY | 3 | The engine's halts (`STRIP_VERIFICATION_FAILED`, `VERIFIER_UNAVAILABLE`, `LENS_COLLAPSE`, `BUDGET_EXCEEDED`) surface as RFC 9457 problem+json with the right status; oversize artifacts + over-budget callers are rejected *before* any provider call. |
| NAMED_COMPENSATORS | 3 | The only HTTP-initiated irreversible write is the webhook send → the cancel-event compensator (below). The receipt INSERT keeps `receipt delete`/`prune`. |
| DECOMPOSE_BY_SECRETS | 3 | `http/app.py` (routing/OpenAPI), `http/auth.py` (key hygiene), `http/errors.py` (problem+json), `http/webhook.py` (signing/SSRF/delivery) — each hides one secret family (Parnas). |
| UNCERTAINTY_GATED_HUMANS | 2 | `escalate` verdicts are delivered via the signed webhook with the contrastive action verb; the human still lives in the caller's workflow (prism is non-interactive) → held at 2, the documented repo-wide skip rationale. |
| EXTERNAL_VERIFIER | 3 | The HTTP layer changes transport, not the verifier: family-different routing is unchanged, and `POST /verify-receipt` lets a *different tool* externally verify prism's own output. |

### Webhook channel

| Standard | Score | Evidence |
|---|---|---|
| PIN_PER_STEP | 3 | The signed payload binds `webhook-id` (from `receipt_id`) + timestamp + body; the receipt it references pins the verification. |
| ANDON_AUTHORITY | 3 | SSRF guard halts a send to an internal/metadata IP before the POST; delivery exhaustion dead-letters (never silently drops). |
| NAMED_COMPENSATORS | 3 | **NO-SKIP** — the webhook send is irreversible; the named compensator is the cancel-event POST (see `design/03`). |
| DECOMPOSE_BY_SECRETS | 3 | `webhook.py` hides signing, SSRF validation, retry/DLQ behind one boundary. |
| UNCERTAINTY_GATED_HUMANS | 2 | The channel exists *specifically* to carry uncertainty (`escalate`) to the caller's human; still caller-surfaced → 2. |
| EXTERNAL_VERIFIER | 3 | The consumer verifies the webhook HMAC independently; the verdict it carries came from a family-different verifier. |

### Receipt signing v4 (Ed25519)

| Standard | Score | Evidence |
|---|---|---|
| PIN_PER_STEP | 3 | Deterministic Ed25519 signature over the same canonical sign-data + `alg`/`kid`; byte-for-byte replayable. |
| ANDON_AUTHORITY | 3 | `verify_signature` whitelists `alg` per receipt (algorithm-confusion/downgrade refused); a tampered receipt fails verification. |
| NAMED_COMPENSATORS | 3 | The receipt INSERT is the only write — `receipt delete`/`prune` unchanged; key generation writes a PEM the operator owns (no in-prism state to undo). |
| DECOMPOSE_BY_SECRETS | 3 | New `receipts/signing.py` hides the backend selection + key handling; `store.py` keeps persistence + the version-aware sign-data. |
| UNCERTAINTY_GATED_HUMANS | skip | Same repo-wide skip — non-interactive. |
| EXTERNAL_VERIFIER | 3 | **This is the layer that moves the cross-tool story from chain-of-custody to cryptographic**: role-os verifies prism's receipt with prism's *public* key, no shared secret. Moves the protocol's EXTERNAL_VERIFIER 2→3 once wired. |

---

## Irreversible actions & compensators (the NO-SKIP table)

Mirrors `design/03-compensators.md` (updated in the same cycle). The webhook send + the two
release actions are new irreversible actions in v0.4.

| Irreversible action | Compensator | Command / surface | Owner | Post-rollback state |
|---|---|---|---|---|
| Webhook verdict POST | Cancel-event POST | `{event: verdict_cancelled, receipt_id}` to the same endpoint, signed + retried | prism HTTP runtime | Consumer notified the verdict is void; residual caller action is accepted approximation (Sagas) |
| PyPI publish (`v0.4.0`) | `yank` the release | pypi.org project → release → Yank (or API `--yank`) | release operator (director) | Version hidden from new resolves; **already-pinned installs keep resolving it — yank ≠ unpublish** |
| GitHub Release | Delete the release | `gh release delete v0.4.0 --yes` | release operator (director) | Release page gone; the **tag remains** (delete separately: `git push origin :refs/tags/v0.4.0`) |
| `gh repo edit` (topics/homepage) | Re-set prior metadata | `gh repo edit --add-topic …` / `--description …` | release operator | Restores prior topics/description (idempotent overwrite) |

**No compensator is skipped.** The read-only retrieval oracle (citations) remains the only
documented no-compensator action (`design/03`).

---

## Out of scope (v0.4)

- Durable cross-restart async (a real task queue — ARQ/Redis); v0.4 async is in-process + delivered
  by webhook, with the limitation disclosed.
- Full per-token cost metering (denial-of-wallet's strongest form) — needs provider token telemetry;
  v0.4 ships size-cap + concurrency-cap + per-key rate limit as the floor.
- mTLS/DPoP token-binding, multi-tenant hosting (operator/mesh concern).
- HSM-held signing keys + transparency-log anchoring (the named genuine-tamper-resistance path).
