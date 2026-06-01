# Named Compensators — Prism

Required by NAMED_COMPENSATORS standard. Documents the reversibility strategy for every irreversible write prism performs.

## Compensator Table

| Irreversible Action | Trigger Condition | Compensator | CLI / API Surface | Notes |
|---------------------|-------------------|-------------|-------------------|-------|
| SQLite receipt INSERT | Every successful `verify()` call | `prism receipt delete <receipt_id>` | CLI: `prism receipt delete <id>` / Python: `store.delete_receipt(id)` | Deletes the row. Cannot un-delete — but receipts are append-only evidence; deletion is an admin escape hatch, not a normal flow. |
| SQLite receipt bulk accumulation | Retention exceeds policy | `prism receipt prune --older-than <duration> --yes` | CLI: `prism receipt prune --older-than 90d --yes` / Python: `store.prune(older_than=timedelta(days=90))` | Bulk removal by age, gated behind `--yes`; prunes on the signed UTC `timestamp` column. Irreversible — export before pruning if audit trail matters. |
| Webhook send (future, v1.5) | `verdict` dispatched to external endpoint | Cancel-event payload to same endpoint | HTTP POST with `{"event": "verdict_cancelled", "receipt_id": "..."}` | Semantic cancellation — cannot un-send the HTTP request, but can notify the receiver that the verdict is withdrawn. |
| MCP state mutation (future) | Client caches a verdict from MCP tool response | Re-issue `verify()` with same inputs; client invalidates cache | MCP tool: `prism.reverify` | Compensates stale state in the caller's context. Not a true rollback — generates a new receipt that supersedes the old one. |

## Read-only external actions (no compensator — documented)

Per the no-skip rule, irreversible *writes* need a named compensator; a *read* needs none — but we
document why, so the absence is a decision, not an omission.

| Action | Why no compensator |
|--------|--------------------|
| Citation existence retrieval (`prism.retrieval` — arXiv / Crossref `GET`, v0.3) | Read-only and external: a GET against a public scholarly API, with no world-state write to undo. The oracle is a courteous, idempotent reader — per-identifier response caching within a run, arXiv's ~3 s serialization, and a Crossref `mailto` for the polite pool — so it has nothing to compensate. The only write the citation path performs is the receipt INSERT, already covered by `receipt delete` / `prune` above. |

## Design Principles

1. **Receipts are evidence, not state.** The primary use of receipts is audit replay, not control flow. Deletion is an escape hatch for GDPR/retention compliance, not a "whoops wrong answer" mechanism.

2. **Semantic compensation over physical rollback.** For network-sent verdicts (webhook, MCP), we cannot un-send. The compensator is a follow-up message that says "disregard previous." The receiver must handle this.

3. **Prism never compensates the caller's actions.** If a caller acts on an `accept` verdict and later prism re-verifies to `refuse`, prism is not responsible for rolling back what the caller did. Prism's compensator scope ends at "I told you the new answer."

## Implementation Status

| Compensator | Status | Tracking |
|-------------|--------|----------|
| `receipt delete` | **Implemented (v0.2.0); undo proven end-to-end (v0.3.0)** | `prism receipt delete <id>` · `store.delete_receipt(id)` — rowcount-backed bool; the compensate-after-verify flow (`tests/integration/test_compensate_after_verify.py`) runs verify → signed receipt → delete → asserts the row is gone |
| `receipt prune` | **Implemented (v0.2.0); undo proven end-to-end (v0.3.0)** | `prism receipt prune --older-than <dur> --yes` · `store.prune(older_than)` — UTC-timestamp, returns count; the same flow prunes a backdated post-verify receipt by age |
| Webhook cancel-event | Design only (v1.5) | Deferred |
| MCP reverify | Design only (v1.5) | Deferred |

`receipt delete` and `receipt prune` are the **terminal leaves** of the compensation tree:
they undo the receipt INSERT and intentionally have no compensator of their own (a deleted
receipt is gone). `prune` is gated behind `--yes` and keys off the signed UTC `timestamp`,
never the local `created_at`, so the cutoff window is timezone-consistent.
