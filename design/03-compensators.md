# Named Compensators — Prism

Required by NAMED_COMPENSATORS standard. Documents the reversibility strategy for every irreversible write prism performs.

## Compensator Table

| Irreversible Action | Trigger Condition | Compensator | CLI / API Surface | Notes |
|---------------------|-------------------|-------------|-------------------|-------|
| SQLite receipt INSERT | Every successful `verify()` call | `prism receipt delete <receipt_id>` | CLI: `prism receipt delete <id>` / Python: `store.delete_receipt(id)` | Deletes the row. Cannot un-delete — but receipts are append-only evidence; deletion is an admin escape hatch, not a normal flow. |
| SQLite receipt bulk accumulation | Retention exceeds policy | `prism receipt prune --older-than <duration>` | CLI: `prism receipt prune --older-than 90d` / Python: `store.prune(older_than=timedelta(days=90))` | Bulk removal by age. Irreversible — caller should export before pruning if audit trail matters. |
| Webhook send (future, v1.5) | `verdict` dispatched to external endpoint | Cancel-event payload to same endpoint | HTTP POST with `{"event": "verdict_cancelled", "receipt_id": "..."}` | Semantic cancellation — cannot un-send the HTTP request, but can notify the receiver that the verdict is withdrawn. |
| MCP state mutation (future) | Client caches a verdict from MCP tool response | Re-issue `verify()` with same inputs; client invalidates cache | MCP tool: `prism.reverify` | Compensates stale state in the caller's context. Not a true rollback — generates a new receipt that supersedes the old one. |

## Design Principles

1. **Receipts are evidence, not state.** The primary use of receipts is audit replay, not control flow. Deletion is an escape hatch for GDPR/retention compliance, not a "whoops wrong answer" mechanism.

2. **Semantic compensation over physical rollback.** For network-sent verdicts (webhook, MCP), we cannot un-send. The compensator is a follow-up message that says "disregard previous." The receiver must handle this.

3. **Prism never compensates the caller's actions.** If a caller acts on an `accept` verdict and later prism re-verifies to `refuse`, prism is not responsible for rolling back what the caller did. Prism's compensator scope ends at "I told you the new answer."

## Implementation Status

| Compensator | Status | Tracking |
|-------------|--------|----------|
| `receipt delete` | **Not yet implemented** | P1 — add before v0.2.0 |
| `receipt prune` | **Not yet implemented** | P1 — add before v0.2.0 |
| Webhook cancel-event | Design only (v1.5) | Deferred |
| MCP reverify | Design only (v1.5) | Deferred |
