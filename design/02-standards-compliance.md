# Standards Compliance — Prism v0.2.0

Scored against the six workflow standards defined in `E:/AI/.claude/rules/workflow-standards.md`.

| Standard | Score | Evidence |
|----------|-------|----------|
| PIN_PER_STEP | 3 | Receipts carry verifier model IDs, pre/post-strip SHA-256, AND `lens_prompt_hashes` — SHA-256 of `(system_prompt, user_prompt)` per lens call, stamped by the engine and **signed** into the receipt (v0.2.0). The integration test proves 4 hashes are persisted and the signature verifies end-to-end. |
| ANDON_AUTHORITY | 3 | Three enforced halt conditions — `STRIP_VERIFICATION_FAILED`, `VERIFIER_UNAVAILABLE` (incl. the v0.2.0 too-few-genuine-lenses path), `LENS_COLLAPSE` — each refuses the whole pipeline and is exercised by tests. (`BUDGET_EXCEEDED` is declared but not yet enforced — a v0.3 item; the three that matter are wired + tested.) |
| NAMED_COMPENSATORS | 2 | `prism receipt delete` / `prune` implemented in CLI + store (v0.2.0), documented in `design/03-compensators.md`, with store + CLI tests. Held at 2 until a full compensate-after-verify flow exercises the undo end-to-end; webhook/MCP compensators stay design-only (those actions don't exist yet). |
| DECOMPOSE_BY_SECRETS | 3 | `core/` / `lenses/` / `providers/` / `receipts/` / `mcp/` / `http/` / `cli/` — each module hides one secret family. Parnas-shape unchanged. |
| UNCERTAINTY_GATED_HUMANS | skip | Prism is non-interactive; humans live in the caller's workflow, surfaced via the `escalate` verdict (now reached on any genuine UNCERTAIN). Legitimate skip — see below. |
| EXTERNAL_VERIFIER | 1 | The engine **is** the external verifier (the product). Prism doesn't verify itself yet; CI runs pytest. A prism-on-prism meta-test (different family) is deferred to v0.3 — bootstrap skip; see below. |

**Total: 12/15 = 80%** (one legitimate skip excluded from the denominator), up from **8/15 (53%)** at launch — PIN_PER_STEP 1→3 and NAMED_COMPENSATORS 0→2, landed in the v0.2.0 dogfood pass.

Remaining gaps are scoped to v0.3: EXTERNAL_VERIFIER 1→3 (prism-on-prism meta-test), NAMED_COMPENSATORS 2→3 (compensate-after-verify integration flow), and `BUDGET_EXCEEDED` enforcement (ANDON follow-up).

## UNCERTAINTY_GATED_HUMANS — skip justification

Prism is a **library/service** consumed by agent workflows. It has no direct human interface. When prism returns `verdict: escalate`, the calling system (Role OS, shipcheck, CLI user) is responsible for surfacing the escalation to a human. Prism's contract is: "I will tell you when I'm uncertain" — the caller's contract is: "I will not proceed without human review when told."

This is the correct decomposition — prism should not assume anything about how humans are reached.

## EXTERNAL_VERIFIER — bootstrap skip justification

Prism is literally an external verifier. The first instance of prism cannot be verified by prism (chicken-egg). Once deployed, a future meta-test can run prism-on-prism (verify lens prompts using a different model family). Until then, the external verification is:
- 96 tests (deterministic; unit + the first end-to-end integration test)
- CI with mypy + ruff (static analysis)
- Research grounding document (design review)
- Human code review on push
