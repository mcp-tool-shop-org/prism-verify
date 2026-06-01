# Standards Compliance — Prism v0.1.0

Scored against the six workflow standards defined in `E:/AI/.claude/rules/workflow-standards.md`.

| Standard | Score | Evidence | Gap → P-level |
|----------|-------|----------|---------------|
| PIN_PER_STEP | 1 | Receipt carries verifier model IDs + pre/post-strip SHA-256 hashes. Lens prompt hashes are **not** captured — each lens call's exact prompt is not pinned in the receipt. | **P1**: add `lens_prompt_hashes: dict[str, str]` field to `Receipt` + SQLite schema; compute SHA-256 over `(system_prompt, user_prompt)` per lens call. |
| ANDON_AUTHORITY | 3 | Four halt conditions: `STRIP_VERIFICATION_FAILED`, `VERIFIER_UNAVAILABLE`, `LENS_COLLAPSE`, `BUDGET_EXCEEDED`. Each refuses the entire pipeline. Unit tests assert each refusal path. | None — exemplary. |
| NAMED_COMPENSATORS | 0 | No documented compensators for prism's own irreversible writes: SQLite receipt INSERT, future webhook send, future client-visible MCP state. | **P0** (no-skip rule): see `design/03-compensators.md`. |
| DECOMPOSE_BY_SECRETS | 3 | `core/` / `lenses/` / `providers/` / `receipts/` / `mcp/` / `http/` / `cli/` — each module hides one secret family. Parnas-shape verified. | None — exemplary. |
| UNCERTAINTY_GATED_HUMANS | skip | Prism is non-interactive; humans live in the caller's workflow, surfaced via the `escalate` verdict. The caller decides how to present escalation. | Legitimate skip — document reasoning here. |
| EXTERNAL_VERIFIER | 1 | The engine **is** the external verifier (that's the product). Prism doesn't verify itself — CI runs pytest, not prism-on-prism. | **P2** (post-launch): add a meta-test that runs prism over its own lens prompts using a different family. For now: skip with "bootstrap — first instance has no parent prism." |

**Total: 8/18** with one legitimate skip = **53%**.

Better than every audited workflow except swarm-control-plane. The two zero-scores are doc-fixable (compensators table) and code-fixable (lens prompt hashing) in one session each.

## UNCERTAINTY_GATED_HUMANS — skip justification

Prism is a **library/service** consumed by agent workflows. It has no direct human interface. When prism returns `verdict: escalate`, the calling system (Role OS, shipcheck, CLI user) is responsible for surfacing the escalation to a human. Prism's contract is: "I will tell you when I'm uncertain" — the caller's contract is: "I will not proceed without human review when told."

This is the correct decomposition — prism should not assume anything about how humans are reached.

## EXTERNAL_VERIFIER — bootstrap skip justification

Prism is literally an external verifier. The first instance of prism cannot be verified by prism (chicken-egg). Once deployed, a future meta-test can run prism-on-prism (verify lens prompts using a different model family). Until then, the external verification is:
- 41 unit tests (deterministic)
- CI with mypy + ruff (static analysis)
- Research grounding document (design review)
- Human code review on push
